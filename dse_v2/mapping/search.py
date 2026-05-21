#!/usr/bin/env python3
"""Deterministic mapping search and feedback artifacts for generic DSE.

This first implementation is intentionally small but complete enough for the
end-to-end evidence contract: it builds a legality matrix, emits domain seeds,
screens/promotes candidates, integrates a SystemC sample, and records
convergence/budget status. Low-fidelity scores are candidate-generation signals
only; trusted selection requires SystemC/gem5+SystemC evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from dse_v2.core.architecture.accelerator import Accelerator, SystemArchitecture
from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload.profiles import canonical_workload_family, resolve_profile_metadata

FAMILY_OP_TARGET_PREFERENCES = {
    "ml_tensor": {
        "placeholder": ["host"],
        "gemm": ["gpu", "fpga", "cim", "host"],
        "batched_gemm": ["gpu", "fpga", "host"],
        "conv2d": ["gpu", "fpga", "host"],
        "attention": ["gpu", "fpga", "host"],
        "softmax": ["gpu", "host"],
        "relu": ["gpu", "cim", "fpga", "host"],
        "elementwise": ["gpu", "cim", "fpga", "host"],
    },
    "sparse_la": {
        "dma_load": ["fpga", "gpu", "host"],
        "spmv": ["fpga", "gpu", "host"],
        "sparse_matvec": ["fpga", "gpu", "host"],
        "gather": ["fpga", "host"],
        "scatter": ["fpga", "host"],
        "reduction": ["fpga", "gpu", "cim", "host"],
        "preconditioner": ["fpga", "gpu", "host"],
    },
    "stencil_streaming": {
        "dma_load": ["fpga", "host"],
        "stencil": ["fpga", "gpu", "host"],
        "fft": ["fpga", "gpu", "host"],
        "residual_check": ["fpga", "gpu", "host"],
        "elementwise": ["fpga", "gpu", "cim", "host"],
        "reduction": ["fpga", "gpu", "cim", "host"],
    },
    "graph_analytics": {
        "dma_load": ["fpga", "host"],
        "frontier_expand": ["fpga", "gpu", "host"],
        "message_passing": ["gpu", "fpga", "host"],
        "reduction": ["fpga", "gpu", "cim", "host"],
        "scatter": ["fpga", "host"],
        "gather": ["fpga", "host"],
    },
    "database_vector_search": {
        "index_scan": ["fpga", "host"],
        "distance_compute": ["gpu", "fpga", "host"],
        "topk": ["fpga", "gpu", "host"],
        "predicate_filter": ["fpga", "host"],
        "aggregation": ["fpga", "gpu", "host"],
        "join": ["fpga", "gpu", "host"],
    },
    "dynamic_custom": {
        "state_update": ["host", "fpga"],
        "data_dependent_branch": ["host", "fpga"],
        "custom": ["fpga", "host"],
        "elementwise": ["gpu", "cim", "fpga", "host"],
    },
}

GENERIC_OP_TARGET_PREFERENCES = {
    "gemm": ["gpu", "fpga", "cim", "host"],
    "batched_gemm": ["gpu", "fpga", "host"],
    "fft": ["fpga", "gpu", "host"],
    "eigen": ["gpu", "fpga", "host"],
    "eigensolver": ["gpu", "fpga", "host"],
    "reduction": ["fpga", "gpu", "cim", "host"],
    "elementwise": ["gpu", "cim", "fpga", "host"],
    "dma_load": ["fpga", "gpu", "host"],
    "placeholder": ["host"],
}


def _workload_family(graph: ComputeGraph) -> str:
    family = str(graph.metadata.get("workload_family", graph.metadata.get("profile_id", "dynamic_custom")))
    return canonical_workload_family(family)


def _workflow_for_graph(graph: ComputeGraph) -> Dict[str, Any]:
    workflow = graph.metadata.get("profile", graph.metadata.get("workflow", {}))
    profile_id = str(graph.metadata.get("profile_id", _workload_family(graph)))
    return resolve_profile_metadata(profile_id, workflow if isinstance(workflow, Mapping) else {})


def _workload_metadata(graph: ComputeGraph) -> Dict[str, Any]:
    workflow = _workflow_for_graph(graph)
    return {
        "graph_id": graph.graph_id,
        "workload_family": workflow.get("workload_family", _workload_family(graph)),
        "workflow": workflow,
        "node_count": len(graph.nodes),
    }


def _node_precisions(node) -> List[str]:
    precisions = []
    for spec in list(node.input_specs.values()) + list(node.output_specs.values()):
        dtype = str(spec.dtype)
        if dtype.startswith("COMPLEX_"):
            dtype = dtype.replace("COMPLEX_", "")
        if dtype and dtype not in precisions:
            precisions.append(dtype)
    return precisions or ["FP64"]


def _node_preferences(graph: ComputeGraph, node_id: str) -> List[str]:
    family = _workload_family(graph)
    node = graph.nodes[node_id]
    workflow = _workflow_for_graph(graph)
    profile_preferences = workflow.get("mapping_preferences", {}) if isinstance(workflow, Mapping) else {}
    if isinstance(profile_preferences, Mapping):
        if node_id in profile_preferences:
            return [str(item) for item in profile_preferences[node_id]]
        if node.op_type in profile_preferences:
            return [str(item) for item in profile_preferences[node.op_type]]
    family_preferences = FAMILY_OP_TARGET_PREFERENCES.get(family, {})
    return family_preferences.get(node.op_type, GENERIC_OP_TARGET_PREFERENCES.get(node.op_type, ["gpu", "fpga", "cim", "host"]))


def _family_seed_name(family: str) -> str:
    return f"{family}_workflow_balanced"


@dataclass(frozen=True)
class MappingCandidate:
    candidate_id: str
    seed_name: str
    mapping: Dict[str, str]
    parameter_hash: str
    predicted_latency_ms: float
    predicted_energy_j: float
    predicted_data_movement_mb: float
    confidence: float
    promotion_priority: float
    state: str
    selection_reason: str
    violations: List[str]
    annotations: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "candidate_id": self.candidate_id,
            "seed_name": self.seed_name,
            "mapping": dict(self.mapping),
            "parameters": {"mapping": dict(self.mapping)},
            "parameter_hash": self.parameter_hash,
            "candidate_identity_policy": "stable_graph_architecture_mapping_hash",
            "screening": {
                "fidelity": "L1_screening",
                "predicted_latency_ms": self.predicted_latency_ms,
                "predicted_energy_j": self.predicted_energy_j,
                "predicted_data_movement_mb": self.predicted_data_movement_mb,
                "confidence": self.confidence,
                "promotion_priority": self.promotion_priority,
            },
            "state": self.state,
            "selection_reason": self.selection_reason,
            "violations": list(self.violations),
            "trusted_final_eligible": False,
        }
        if self.annotations:
            payload["annotations"] = dict(self.annotations)
        return payload


def target_ids(architecture: SystemArchitecture) -> List[str]:
    return ["host"] + [accel.accel_id for accel in architecture.accelerators]


def accelerator_by_id(architecture: SystemArchitecture) -> Dict[str, Accelerator]:
    return {accel.accel_id: accel for accel in architecture.accelerators}


def build_legality_matrix(graph: ComputeGraph, architecture: SystemArchitecture) -> Dict[str, Any]:
    accels = accelerator_by_id(architecture)
    targets = target_ids(architecture)
    rows: List[Dict[str, Any]] = []
    for node_id, node in graph.nodes.items():
        legal_targets: List[str] = []
        cells: List[Dict[str, Any]] = []
        for target in targets:
            reasons: List[str] = []
            legal = True
            if target == "host":
                reasons.append("host_fallback_available")
            else:
                accel = accels[target]
                if not accel.can_execute(node.op_type):
                    legal = False
                    reasons.append(f"unsupported_op:{node.op_type}")
                else:
                    reasons.append("operator_supported")
                supported_precisions = {precision for precision, peak in accel.compute.peak_flops.items() if peak > 0.0}
                unsupported_precisions = [precision for precision in _node_precisions(node) if precision not in supported_precisions]
                if unsupported_precisions:
                    legal = False
                    reasons.append(f"unsupported_precision:{','.join(unsupported_precisions)}")
                capacity = accel.memory.total_capacity_bytes()
                if capacity and node.estimated_memory_bytes > capacity:
                    legal = False
                    reasons.append("working_set_exceeds_local_memory")
                if not accel.communication.host_link and architecture.interconnect is None:
                    legal = False
                    reasons.append("no_declared_route")
            if legal:
                legal_targets.append(target)
            cells.append({"target": target, "legal": legal, "reasons": reasons})
        rows.append({
            "node_id": node_id,
            "op_type": node.op_type,
            "estimated_memory_bytes": node.estimated_memory_bytes,
            "legal_targets": legal_targets,
            "cells": cells,
        })
    return {
        "schema_version": "dse.mapping_legality_matrix.v1",
        "architecture_id": architecture.system_id,
        "workload": _workload_metadata(graph),
        "targets": targets,
        "rows": rows,
        "summary": {
            "node_count": len(rows),
            "all_nodes_have_legal_target": all(row["legal_targets"] for row in rows),
        },
    }


def _first_by_type(architecture: SystemArchitecture, type_names: Sequence[str], legal_targets: Iterable[str]) -> str:
    legal_sequence = [str(target) for target in legal_targets]
    legal = set(legal_sequence)
    for type_name in type_names:
        type_name = str(type_name)
        if type_name in legal:
            return type_name
        if type_name == "host" and "host" in legal:
            return "host"
        for accel in architecture.accelerators:
            if accel.accel_type == type_name and accel.accel_id in legal:
                return accel.accel_id
    return legal_sequence[0] if legal_sequence else "host"


def _legality_lookup(matrix: Mapping[str, Any]) -> Dict[str, List[str]]:
    return {row["node_id"]: list(row["legal_targets"]) for row in matrix.get("rows", [])}


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        for key in ("preferred_targets", "target_preferences", "targets", "target_ids", "target_types", "resource_preferences", "architecture_targets"):
            if key in value:
                return _string_list(value.get(key))
        if "target" in value:
            return _string_list(value.get("target"))
        if "target_id" in value:
            return _string_list(value.get("target_id"))
        if "target_type" in value:
            return _string_list(value.get("target_type"))
        return []
    if isinstance(value, Iterable):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _hint_policy_id(candidate_hints: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(candidate_hints, Mapping):
        return "domain_policy"
    domain_policy = candidate_hints.get("domain_policy", {})
    if isinstance(domain_policy, Mapping) and domain_policy.get("policy_id"):
        return str(domain_policy.get("policy_id"))
    return str(candidate_hints.get("policy_id") or "domain_policy")


def _hint_domain_policy(candidate_hints: Mapping[str, Any]) -> Dict[str, Any]:
    domain_policy = candidate_hints.get("domain_policy", {})
    if isinstance(domain_policy, Mapping):
        payload = {str(key): value for key, value in domain_policy.items() if key in {"policy_id", "domain_key", "matched"}}
    else:
        payload = {}
    payload.setdefault("policy_id", _hint_policy_id(candidate_hints))
    if "domain_key" in candidate_hints:
        payload.setdefault("domain_key", candidate_hints.get("domain_key"))
    if "matched" in candidate_hints:
        payload.setdefault("matched", bool(candidate_hints.get("matched")))
    return payload


def _hint_review_flags(candidate_hints: Mapping[str, Any]) -> List[str]:
    flags: List[str] = []
    for key in ("review_flags", "review_required_flags", "hard_block_flags", "hard_review_flags"):
        flags.extend(_string_list(candidate_hints.get(key)))
    review = candidate_hints.get("review", {})
    if isinstance(review, Mapping):
        flags.extend(_string_list(review.get("flags")))
        flags.extend(_string_list(review.get("hard_block_flags")))
        flags.extend(_string_list(review.get("review_required_flags")))
    return sorted(dict.fromkeys(flag for flag in flags if flag))


def _hint_phase_groups(candidate_hints: Mapping[str, Any]) -> List[Any]:
    phase_groups = candidate_hints.get("phase_groups")
    if phase_groups is None:
        annotations = candidate_hints.get("annotations", {})
        if isinstance(annotations, Mapping):
            for annotation in annotations.values():
                if not isinstance(annotation, Mapping):
                    continue
                phase_groups = annotation.get("phase_groups")
                if isinstance(phase_groups, list):
                    break
    if isinstance(phase_groups, list):
        return list(phase_groups)
    return []


def _hint_annotations(
    candidate_hints: Mapping[str, Any],
    *,
    seed_role: str,
    description: str,
) -> Dict[str, Any]:
    review_flags = _hint_review_flags(candidate_hints)
    annotations: Dict[str, Any] = {
        "candidate_hint_source": "step2_domain_policy",
        "domain_policy": _hint_domain_policy(candidate_hints),
        "seed_role": seed_role,
        "seed_reason": description,
        "review_flags": review_flags,
        "review_required": bool(candidate_hints.get("review_required", False) or review_flags),
        "review_status": "review_required" if (candidate_hints.get("review_required", False) or review_flags) else "not_required",
        "claim_boundary": str(candidate_hints.get("claim_boundary", "candidate_only")),
        "trusted_final_claim": False,
    }
    phase_groups = _hint_phase_groups(candidate_hints)
    if phase_groups:
        annotations["phase_groups"] = phase_groups
    if isinstance(candidate_hints.get("annotations"), Mapping):
        annotations["policy_annotations"] = dict(candidate_hints.get("annotations", {}))
    return annotations


def _node_hint_entries(candidate_hints: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(candidate_hints, Mapping):
        return []
    raw = (
        candidate_hints.get("node_target_preferences")
        or candidate_hints.get("node_preferences")
        or candidate_hints.get("target_preferences")
        or []
    )
    entries: List[Dict[str, Any]] = []
    if isinstance(raw, Mapping):
        for node_id, spec in raw.items():
            if isinstance(spec, Mapping):
                entry = dict(spec)
            else:
                entry = {"preferred_targets": spec}
            entry.setdefault("node_id", str(node_id))
            entries.append(entry)
    elif isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
        for item in raw:
            if isinstance(item, Mapping):
                entries.append(dict(item))
    return entries


def _entry_matches_node(entry: Mapping[str, Any], node_id: str, op_type: str) -> bool:
    if str(entry.get("node_id", "")) == node_id:
        return True
    node_ids = _string_list(entry.get("node_ids"))
    if node_id in node_ids:
        return True
    op_types = _string_list(entry.get("op_type") or entry.get("op_types"))
    return bool(op_types and op_type in op_types)


def _entry_targets(entry: Mapping[str, Any]) -> List[str]:
    for key in ("preferred_targets", "target_preferences", "targets", "target_ids", "target_types", "resource_preferences", "architecture_targets"):
        targets = _string_list(entry.get(key))
        if targets:
            return targets
    return _string_list(entry.get("target") or entry.get("target_id") or entry.get("target_type"))


def _hint_preferences_for_node(candidate_hints: Optional[Mapping[str, Any]], node_id: str, op_type: str) -> List[str]:
    preferences: List[str] = []
    for entry in _node_hint_entries(candidate_hints):
        if _entry_matches_node(entry, node_id, op_type):
            preferences.extend(_entry_targets(entry))
    return list(dict.fromkeys(preferences))


def _hinted_mapping(
    *,
    graph: ComputeGraph,
    architecture: SystemArchitecture,
    legal: Mapping[str, List[str]],
    candidate_hints: Mapping[str, Any],
    fallback: str,
) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for node_id, node in graph.nodes.items():
        preferences = _hint_preferences_for_node(candidate_hints, node_id, node.op_type)
        if not preferences and fallback == "workflow":
            preferences = _node_preferences(graph, node_id)
        elif not preferences and fallback == "host_visible":
            preferences = ["host"]
        elif not preferences:
            preferences = ["fpga", "gpu", "cim", "asic", "host"]
        mapping[node_id] = _first_by_type(architecture, preferences, legal.get(node_id, ["host"]))
    return mapping


def _explicit_hint_seed_mappings(
    *,
    graph: ComputeGraph,
    architecture: SystemArchitecture,
    legal: Mapping[str, List[str]],
    candidate_hints: Mapping[str, Any],
) -> List[Tuple[str, str, Dict[str, str], Dict[str, Any]]]:
    policy_id = _hint_policy_id(candidate_hints)
    raw_seeds = candidate_hints.get("mapping_seeds", []) or []
    if isinstance(raw_seeds, Mapping):
        raw_seeds = [raw_seeds]
    seeds: List[Tuple[str, str, Dict[str, str], Dict[str, Any]]] = []
    if not isinstance(raw_seeds, Iterable) or isinstance(raw_seeds, (str, bytes)):
        return seeds
    for index, seed in enumerate(raw_seeds):
        if not isinstance(seed, Mapping):
            continue
        raw_mapping = seed.get("mapping") or seed.get("placements") or {}
        if not isinstance(raw_mapping, Mapping):
            continue
        mapping: Dict[str, str] = {}
        for node_id, node in graph.nodes.items():
            requested = raw_mapping.get(node_id)
            preferences = _string_list(requested) or _hint_preferences_for_node(candidate_hints, node_id, node.op_type) or _node_preferences(graph, node_id)
            mapping[node_id] = _first_by_type(architecture, preferences, legal.get(node_id, ["host"]))
        seed_role = str(seed.get("seed_role") or seed.get("seed_name") or f"explicit_{index}")
        name = str(seed.get("seed_name") or f"policy:{policy_id}:{seed_role}")
        if not name.startswith("policy:"):
            name = f"policy:{policy_id}:{name}"
        description = str(seed.get("description") or "policy supplied mapping seed filtered through the generic legality matrix")
        annotations = _hint_annotations(candidate_hints, seed_role=seed_role, description=description)
        if isinstance(seed.get("annotations"), Mapping):
            annotations["seed_annotations"] = dict(seed.get("annotations", {}))
        seeds.append((name, description, mapping, annotations))
    return seeds


def _policy_hint_seeds(
    graph: ComputeGraph,
    architecture: SystemArchitecture,
    legal: Mapping[str, List[str]],
    candidate_hints: Optional[Mapping[str, Any]],
) -> List[Tuple[str, str, Dict[str, str], Dict[str, Any]]]:
    if not isinstance(candidate_hints, Mapping) or not candidate_hints:
        return []
    policy_id = _hint_policy_id(candidate_hints)
    seeds = _explicit_hint_seed_mappings(
        graph=graph,
        architecture=architecture,
        legal=legal,
        candidate_hints=candidate_hints,
    )
    balanced_desc = "phase-aware policy preferences applied to legal generic targets"
    dominant_desc = "dominant hinted nodes offloaded when legal, with workflow fallback"
    review_desc = "host-visible review-safe placement derived from policy review boundary"
    seeds.extend([
        (
            f"policy:{policy_id}:phase_aware_balanced",
            balanced_desc,
            _hinted_mapping(graph=graph, architecture=architecture, legal=legal, candidate_hints=candidate_hints, fallback="workflow"),
            _hint_annotations(candidate_hints, seed_role="phase_aware_balanced", description=balanced_desc),
        ),
        (
            f"policy:{policy_id}:dominant_phase_offload",
            dominant_desc,
            _hinted_mapping(graph=graph, architecture=architecture, legal=legal, candidate_hints=candidate_hints, fallback="accelerator"),
            _hint_annotations(candidate_hints, seed_role="dominant_phase_offload", description=dominant_desc),
        ),
        (
            f"policy:{policy_id}:host_visible_review_safe",
            review_desc,
            _hinted_mapping(graph=graph, architecture=architecture, legal=legal, candidate_hints=candidate_hints, fallback="host_visible"),
            _hint_annotations(candidate_hints, seed_role="host_visible_review_safe", description=review_desc),
        ),
    ])
    return seeds


def generate_seed_mappings(
    graph: ComputeGraph,
    architecture: SystemArchitecture,
    matrix: Optional[Mapping[str, Any]] = None,
    candidate_hints: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    matrix = matrix or build_legality_matrix(graph, architecture)
    legal = _legality_lookup(matrix)
    family = _workload_family(graph)
    workflow = _workflow_for_graph(graph)

    def all_to(target: str) -> Dict[str, str]:
        return {node_id: target if target in legal.get(node_id, []) else "host" for node_id in graph.nodes}

    seeds: List[Tuple[str, str, Dict[str, str], Dict[str, Any]]] = [
        ("host_baseline", "all nodes on host fallback", all_to("host"), {}),
    ]
    for accel in architecture.accelerators:
        seeds.append((f"all_{accel.accel_type}_{accel.accel_id}", f"all legal nodes on {accel.accel_id}", all_to(accel.accel_id), {}))

    workflow_mapping: Dict[str, str] = {}
    for node_id, node in graph.nodes.items():
        preferences = _node_preferences(graph, node_id)
        workflow_mapping[node_id] = _first_by_type(architecture, preferences, legal.get(node_id, ["host"]))
    seeds.append((
        _family_seed_name(family),
        f"{family} workflow-declared balanced placement",
        workflow_mapping,
        {},
    ))

    streaming_mapping: Dict[str, str] = {}
    for node_id, node in graph.nodes.items():
        preferences = ["fpga", "cim", "gpu", "host"] if node.op_type in {"reduction", "fft", "elementwise"} else ["gpu", "fpga", "host"]
        streaming_mapping[node_id] = _first_by_type(architecture, preferences, legal.get(node_id, ["host"]))
    seeds.append(("streaming_memory_locality", "favor FPGA/CIM for streaming and reductions", streaming_mapping, {}))
    seeds.extend(_policy_hint_seeds(graph, architecture, legal, candidate_hints))

    unique: Dict[Tuple[Tuple[str, str], ...], Dict[str, Any]] = {}
    for name, description, mapping, annotations in seeds:
        key = tuple(sorted(mapping.items()))
        payload = {
            "seed_name": name,
            "description": description,
            "workload_family": family,
            "workflow_mapping_policies": list(workflow.get("default_mapping_policies", []) or []),
            "mapping": mapping,
        }
        if annotations:
            payload["annotations"] = dict(annotations)
        unique.setdefault(key, payload)
    return list(unique.values())


def _target_cost(target: str, node_op: str, architecture: SystemArchitecture) -> Tuple[float, float]:
    if target == "host":
        return 1.0e10, 140.0
    accel = architecture.get_accelerator(target)
    if accel is None:
        return 1.0e9, 100.0
    peak = max(accel.compute.get_peak_flops("FP64"), 1.0)
    efficiency = max(accel.compute.get_op_efficiency(node_op), 0.05)
    power = max(accel.power.static_power_w, 1.0)
    return peak * efficiency, power


def _data_movement_mb(graph: ComputeGraph, mapping: Mapping[str, str]) -> float:
    total = 0.0
    for edge in graph.edges:
        if mapping.get(edge.source_node, "host") != mapping.get(edge.target_node, "host"):
            if edge.tensor_spec is not None:
                total += edge.tensor_spec.size_bytes() / (1024.0 * 1024.0)
    return total


def mapping_violations(mapping: Mapping[str, str], graph: ComputeGraph, matrix: Mapping[str, Any]) -> List[str]:
    """Return explicit legality violations for a complete node-to-target mapping."""
    legal = _legality_lookup(matrix)
    violations: List[str] = []
    for node_id in graph.nodes:
        target = mapping.get(node_id)
        if target is None:
            violations.append(f"{node_id}:missing_mapping")
            continue
        legal_targets = legal.get(node_id, [])
        if target not in legal_targets:
            allowed = ",".join(legal_targets) if legal_targets else "<none>"
            violations.append(f"{node_id}:{target}:illegal_target:allowed={allowed}")
    extra_nodes = sorted(set(mapping) - set(graph.nodes))
    for node_id in extra_nodes:
        violations.append(f"{node_id}:unknown_node")
    return violations


def _mapping_parameter_hash(mapping: Mapping[str, str]) -> str:
    payload = json.dumps(dict(mapping), sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stable_mapping_candidate_id(graph: ComputeGraph, architecture: SystemArchitecture, mapping: Mapping[str, str]) -> str:
    identity_payload = {
        "graph_id": graph.graph_id,
        "architecture_id": architecture.system_id,
        "parameter_hash": _mapping_parameter_hash(mapping),
    }
    digest = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return f"map_{digest[:16]}"


def screen_mapping(seed: Mapping[str, Any], graph: ComputeGraph, architecture: SystemArchitecture, candidate_index: int) -> MappingCandidate:
    mapping = dict(seed["mapping"])
    violations: List[str] = []
    predicted_latency_ms = 0.0
    predicted_energy_j = 0.0
    for node_id, node in graph.nodes.items():
        target = mapping.get(node_id, "host")
        throughput, power = _target_cost(target, node.op_type, architecture)
        compute_ms = node.estimated_flops / throughput * 1000.0
        memory_ms = node.estimated_memory_bytes * 8.0 / 1.0e11 * 1000.0
        node_ms = max(compute_ms, memory_ms)
        predicted_latency_ms += node_ms
        predicted_energy_j += power * node_ms / 1000.0
        if target != "host":
            accel = architecture.get_accelerator(target)
            if accel is None or not accel.can_execute(node.op_type):
                violations.append(f"{node_id}:{target}:unsupported_op:{node.op_type}")
    movement = _data_movement_mb(graph, mapping)
    predicted_latency_ms += movement * 0.002
    confidence = 0.72 if not violations else 0.35
    priority = 1.0 / max(predicted_latency_ms, 1e-9) * confidence
    parameter_hash = _mapping_parameter_hash(mapping)
    return MappingCandidate(
        candidate_id=_stable_mapping_candidate_id(graph, architecture, mapping),
        seed_name=str(seed["seed_name"]),
        mapping=mapping,
        parameter_hash=parameter_hash,
        predicted_latency_ms=predicted_latency_ms,
        predicted_energy_j=predicted_energy_j,
        predicted_data_movement_mb=movement,
        confidence=confidence,
        promotion_priority=priority,
        state="screened" if not violations else "rejected",
        selection_reason="workflow_seed_screening" if not violations else "illegal_mapping",
        violations=violations,
        annotations=dict(seed.get("annotations", {}) if isinstance(seed.get("annotations", {}), Mapping) else {}),
    )


def select_initial_mapping(graph: ComputeGraph, architecture: SystemArchitecture) -> Dict[str, str]:
    """Return a legal first sample mapping, preferring the workflow-family seed."""
    matrix = build_legality_matrix(graph, architecture)
    candidates = [
        screen_mapping(seed, graph, architecture, idx)
        for idx, seed in enumerate(generate_seed_mappings(graph, architecture, matrix))
    ]
    legal = [candidate for candidate in candidates if not candidate.violations]
    if not legal:
        return {node_id: "host" for node_id in graph.nodes}
    preferred_seed = _family_seed_name(_workload_family(graph))
    for candidate in legal:
        if candidate.seed_name == preferred_seed:
            return dict(candidate.mapping)
    selected = sorted(legal, key=lambda c: (-c.promotion_priority, c.predicted_latency_ms, c.candidate_id))[0]
    return dict(selected.mapping)


def _state_for_candidate(candidate: MappingCandidate, selected_mapping: Mapping[str, str], promoted_ids: Iterable[str]) -> str:
    if candidate.violations:
        return "rejected"
    if dict(candidate.mapping) == dict(selected_mapping):
        return "selected"
    if candidate.candidate_id in set(promoted_ids):
        return "promoted"
    return "predicted-only"


def run_mapping_search(
    graph: ComputeGraph,
    architecture: SystemArchitecture,
    *,
    selected_mapping: Optional[Mapping[str, str]] = None,
    simulation_result: Optional[Mapping[str, Any]] = None,
    additional_feedback_samples: Optional[Sequence[Mapping[str, Any]]] = None,
    trusted_sample: bool = False,
    beam_width: int = 3,
    candidate_hints: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Run deterministic seed/beam mapping search and return artifact payloads."""
    matrix = build_legality_matrix(graph, architecture)
    seed_set = generate_seed_mappings(graph, architecture, matrix, candidate_hints=candidate_hints)
    candidates = [screen_mapping(seed, graph, architecture, idx) for idx, seed in enumerate(seed_set)]
    legal = [candidate for candidate in candidates if not candidate.violations]
    legal_sorted = sorted(legal, key=lambda c: (-c.promotion_priority, c.predicted_latency_ms, c.candidate_id))
    promoted = legal_sorted[: max(1, beam_width)]
    promoted_ids = {candidate.candidate_id for candidate in promoted}
    selected_mapping = dict(selected_mapping or (dict(promoted[0].mapping) if promoted else {node_id: "host" for node_id in graph.nodes}))

    candidate_records: List[Dict[str, Any]] = []
    selected_candidate_id = None
    for candidate in candidates:
        record = candidate.to_dict()
        record["state"] = _state_for_candidate(candidate, selected_mapping, promoted_ids)
        if record["state"] == "selected":
            selected_candidate_id = candidate.candidate_id
            record["trusted_final_eligible"] = bool(trusted_sample)
            record["selection_reason"] = "selected_for_systemc_sample"
        candidate_records.append(record)

    if selected_candidate_id is None:
        selected_candidate_id = "external_selected_mapping"
        violations = mapping_violations(selected_mapping, graph, matrix)
        candidate_records.append({
            "candidate_id": selected_candidate_id,
            "seed_name": "external_selected_mapping",
            "mapping": selected_mapping,
            "screening": {"fidelity": "external", "confidence": 0.5, "promotion_priority": 0.0},
            "state": "selected" if not violations else "rejected",
            "selection_reason": "provided_by_orchestrator" if not violations else "provided_by_orchestrator_illegal",
            "promotion_reason": "provided mapping scheduled for simulation sample" if not violations else "provided mapping failed legality validation",
            "violations": violations,
            "trusted_final_eligible": bool(trusted_sample and not violations),
        })

    selected_record = next(record for record in candidate_records if record["candidate_id"] == selected_candidate_id)
    selected_record.setdefault("promotion_reason", selected_record.get("selection_reason", "selected for simulation sample"))
    selected_mapping_legal = not selected_record.get("violations")

    simulation_sample: Optional[Dict[str, Any]] = None
    sample_trusted = False
    sample_blocked = False
    sample_backend = ""
    sample_status = ""
    if simulation_result:
        metrics = simulation_result.get("metrics", {})
        if not isinstance(metrics, Mapping):
            metrics = {}
        sample_backend = str(simulation_result.get("backend", "systemc"))
        sample_status = str(simulation_result.get("status", "unknown"))
        sample_trusted = bool(trusted_sample and selected_mapping_legal and sample_status == "passed")
        sample_blocked = not sample_trusted
        evidence_ids = ["simulation_result.json", "phase_breakdown.csv", "verdict.json"]
        if sample_backend == "gem5_systemc":
            evidence_ids.append("gem5_l4_proof.json")
        gem5_l4_proof_raw = simulation_result.get("gem5_l4_proof", {}) if sample_backend == "gem5_systemc" else {}
        gem5_l4_proof = gem5_l4_proof_raw if isinstance(gem5_l4_proof_raw, Mapping) else {}
        blockers: List[Dict[str, Any]] = []
        if sample_backend == "gem5_systemc" and not bool(gem5_l4_proof.get("passed", False)):
            blockers.append({
                "id": "missing_or_failed_l4_proof",
                "status": "blocked",
                "missing_evidence": list(gem5_l4_proof.get("missing_evidence", []) or []),
            })
        simulation_sample = {
            "candidate_id": selected_candidate_id,
            "backend": sample_backend,
            "fidelity": "L3" if sample_backend == "systemc" else "L4",
            "status": sample_status,
            "sample_role": "trusted_feedback" if sample_trusted else "blocked_or_untrusted_attempt",
            "trusted_final_eligible": sample_trusted,
            "evidence_quality": "trusted_high_fidelity" if sample_trusted else "blocked_or_untrusted",
            "metrics": {
                "latency_ms": metrics.get("latency_ms"),
                "power_w": metrics.get("power_w"),
                "energy_j": metrics.get("energy_j"),
                "total_data_movement_mb": metrics.get("total_data_movement_mb"),
            },
            "evidence_ids": evidence_ids,
            "blockers": blockers,
        }

    simulation_samples = [simulation_sample] if simulation_sample else []
    for sample in additional_feedback_samples or []:
        normalized = dict(sample)
        normalized.setdefault("sample_role", "trusted_feedback" if normalized.get("trusted_final_eligible") else "blocked_or_untrusted_attempt")
        normalized.setdefault("evidence_quality", "trusted_high_fidelity" if normalized.get("trusted_final_eligible") else "blocked_or_untrusted")
        normalized.setdefault("evidence_ids", [])
        simulation_samples.append(normalized)

    attempted_samples = len(simulation_samples)
    trusted_completed_samples = sum(1 for sample in simulation_samples if sample.get("trusted_final_eligible"))
    blocked_samples = sum(1 for sample in simulation_samples if not sample.get("trusted_final_eligible"))
    requested_samples = max(beam_width, attempted_samples)
    remaining_promoted = max(0, len(promoted) - attempted_samples)
    budget_exhausted = attempted_samples >= requested_samples and remaining_promoted == 0
    metric_history: List[Dict[str, Any]] = [
        {
            "candidate_id": sample.get("candidate_id"),
            "backend": sample.get("backend"),
            "fidelity": sample.get("fidelity"),
            "trusted_final_eligible": bool(sample.get("trusted_final_eligible", False)),
            "latency_ms": (sample.get("metrics", {}) or {}).get("latency_ms"),
            "energy_j": (sample.get("metrics", {}) or {}).get("energy_j"),
            "power_w": (sample.get("metrics", {}) or {}).get("power_w"),
            "evidence_ids": list(sample.get("evidence_ids", []) or []),
        }
        for sample in simulation_samples
    ]

    if not simulation_samples:
        feedback_source = "screening_only"
        feedback_effect = "awaiting high-fidelity simulation before trusted ranking update"
        convergence_status = "awaiting_simulation"
    elif sample_trusted:
        feedback_source = "trusted_gem5_systemc_sample" if sample_backend == "gem5_systemc" else "trusted_systemc_sample"
        feedback_effect = "trusted samples integrated into ranking" if trusted_completed_samples > 1 else "selected candidate promoted to trusted ranking"
        convergence_status = "trusted_samples_integrated" if trusted_completed_samples > 1 else "trusted_sample_integrated"
    elif sample_backend == "gem5_systemc" and sample_status == "blocked":
        feedback_source = "blocked_gem5_systemc_attempt"
        feedback_effect = "selected candidate remains blocked; no trusted ranking update"
        convergence_status = "blocked_attempt_recorded"
    else:
        feedback_source = "untrusted_simulation_attempt"
        feedback_effect = "selected candidate remains untrusted; no trusted ranking update"
        convergence_status = "untrusted_attempt_recorded"

    converged = False
    stop_reason = "incomplete"
    limitations: List[str] = []
    if not simulation_samples:
        stop_reason = "incomplete"
        limitations.append("No high-fidelity simulation sample has been attempted.")
    elif trusted_completed_samples < 2:
        stop_reason = "budget_exhausted" if budget_exhausted else "incomplete"
        limitations.append("Comparative convergence is not established with fewer than two trusted high-fidelity samples.")
    elif budget_exhausted:
        stop_reason = "budget_exhausted"
        limitations.append("High-fidelity sample budget was exhausted before top-K/frontier stability was established.")
    else:
        stop_reason = "incomplete"
        limitations.append("Additional feedback iterations are required before convergence can be claimed.")

    convergence_artifact: Dict[str, Any] = {
        "schema_version": "dse.convergence_status.v1",
        "architecture_id": architecture.system_id,
        "workload": _workload_metadata(graph),
        "status": convergence_status,
        "converged": converged,
        "stop_reason": stop_reason,
        "criteria": {
            "trusted_frontier_stability": {
                "enabled": True,
                "status": "not_established_single_iteration",
                "required_iterations": 2,
            },
            "top_k_stability": {
                "enabled": True,
                "status": "not_established_single_iteration",
                "required_iterations": 2,
            },
            "improvement_threshold": {
                "enabled": True,
                "epsilon_latency_ms": 0.0,
                "status": "not_evaluated",
            },
            "family_coverage": {
                "enabled": False,
                "status": "not_configured_for_pilot",
            },
        },
        "simulation_budget": {
            "requested_samples": requested_samples,
            "attempted_samples": attempted_samples,
            "completed_samples": trusted_completed_samples,
            "trusted_completed_samples": trusted_completed_samples,
            "blocked_samples": blocked_samples,
            "remaining_promoted_candidates": remaining_promoted,
            "budget_exhausted": budget_exhausted,
        },
        "metric_history": metric_history,
        "limitations": limitations,
        "next_step": "simulate another feedback iteration or widen family coverage before global best-architecture claims",
    }

    feedback_state = {
        "schema_version": "dse.mapping_feedback.v1",
        "architecture_id": architecture.system_id,
        "workload": _workload_metadata(graph),
        "selected_candidate_id": selected_candidate_id,
        "screened_count": len(candidate_records),
        "promoted_count": len(promoted),
        "simulation_budget": dict(convergence_artifact["simulation_budget"]),
        "simulation_samples": simulation_samples,
        "ranking_update": {
            "source": feedback_source,
            "effect": feedback_effect,
            "low_fidelity_role": "candidate_generator_only",
            "confidence_update": "trusted samples raise confidence for measured mappings only" if trusted_completed_samples else "confidence not raised from blocked, illegal, or predicted-only evidence",
            "pruning_policy": "pruning policy: do not prune solely from L1/L2 screening; require comparable SystemC/gem5+SystemC samples",
            "promotion_policy": "promote legal seeds to simulation budget; final ranking gated by trusted evidence",
        },
        "convergence": {
            "status": convergence_artifact["status"],
            "converged": convergence_artifact["converged"],
            "stop_reason": convergence_artifact["stop_reason"],
            "budget_exhausted": convergence_artifact["simulation_budget"]["budget_exhausted"],
            "top_k_stability": convergence_artifact["criteria"]["top_k_stability"]["status"],
            "next_step": convergence_artifact["next_step"],
        },
    }

    return {
        "legality_matrix": matrix,
        "seed_set": {
            "schema_version": "dse.mapping_seed_set.v1",
            "architecture_id": architecture.system_id,
            "workload": _workload_metadata(graph),
            "seeds": seed_set,
        },
        "candidate_records": {
            "schema_version": "dse.mapping_candidates.v1",
            "architecture_id": architecture.system_id,
            "workload": _workload_metadata(graph),
            "algorithm": "workflow_seeded_beam_local_search_v1",
            "beam_width": beam_width,
            "candidates": candidate_records,
            "selected_candidate_id": selected_candidate_id,
        },
        "selected_record": {
            "schema_version": "dse.mapping_selected_record.v1",
            "workload": _workload_metadata(graph),
            **selected_record,
        },
        "simulation_samples": {
            "schema_version": "dse.mapping_simulation_samples.v1",
            "architecture_id": architecture.system_id,
            "workload": _workload_metadata(graph),
            "samples": simulation_samples,
        },
        "feedback_state": feedback_state,
        "convergence_status": convergence_artifact,
    }
