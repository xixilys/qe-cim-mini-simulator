#!/usr/bin/env python3
"""Standalone Quantum ESPRESSO profile JSON importer.

This module intentionally stops at profile -> ComputeGraph/WorkloadPackage.
It does not partition regions, select hardware, run simulation, or modify any
campaign/evidence/backend flow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode, DataEdge, TensorSpec
from dse_v2.core.workload.package import WorkloadPackage, package_from_graph

DOMAIN = "dft_qe"
WORKLOAD_FAMILY = "dft_qe_profiled"
PROFILE_ID = "qe_profile_imported"
IMPORTER_ID = "qe_profile_json"
IMPORTER_VERSION = "v1"


def load_qe_profile(path: str | Path) -> Dict[str, Any]:
    """Load a QE profile JSON document from ``path``.

    The importer expects a mapping with ``case_id``, ``problem``, ``phases``,
    and optional ``edges``.  Validation here is deliberately structural; domain
    correctness remains outside this profile-ingestion slice.
    """

    profile_path = Path(path)
    with profile_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("QE profile JSON must contain an object at the top level")
    _require_mapping(payload, "profile")
    _require_list(payload, "phases")
    if "edges" in payload:
        _require_list(payload, "edges")
    return payload


def qe_profile_to_compute_graph(profile: Mapping[str, Any]) -> ComputeGraph:
    """Convert a QE profile mapping into a flat phase ``ComputeGraph``."""

    _require_mapping(profile, "profile")
    phases = _require_list(profile, "phases")
    edges = list(profile.get("edges", []) or [])
    case_id = _required_string(profile, "case_id")
    problem = profile.get("problem", {})
    if not isinstance(problem, Mapping):
        raise ValueError("QE profile field 'problem' must be an object")

    graph = ComputeGraph(
        graph_id=str(profile.get("graph_id") or f"{case_id}_graph"),
        metadata={
            "domain": DOMAIN,
            "workload_family": WORKLOAD_FAMILY,
            "profile_id": PROFILE_ID,
            "case_id": case_id,
            "problem": dict(problem),
            "phase_count": len(phases),
            "edge_count": len(edges),
            "source_schema_version": str(profile.get("schema_version", "dse.qe_profile.v1")),
        },
    )

    for phase in phases:
        if not isinstance(phase, Mapping):
            raise ValueError("QE profile phases must be objects")
        node = _phase_to_node(phase)
        graph.add_node(node)

    for edge in edges:
        if not isinstance(edge, Mapping):
            raise ValueError("QE profile edges must be objects")
        graph.add_edge(_edge_to_data_edge(edge))

    return graph


def qe_profile_to_workload_package(profile: Mapping[str, Any]) -> WorkloadPackage:
    """Convert a QE profile mapping into a valid generic ``WorkloadPackage``."""

    graph = qe_profile_to_compute_graph(profile)
    case_id = str(graph.metadata["case_id"])
    coverage = list(graph.topological_sort())
    profile_payload = _profile_payload(coverage)
    return package_from_graph(
        graph,
        workload_id=case_id,
        workload_family=WORKLOAD_FAMILY,
        profile_id=PROFILE_ID,
        profile_version="v1",
        importer_id=IMPORTER_ID,
        importer_version=IMPORTER_VERSION,
        claim_boundary="full_workload",
        source_kind="qe_profile_json",
        domain_metadata={
            "domain": DOMAIN,
            "case_id": case_id,
            "problem": dict(graph.metadata.get("problem", {})),
            "phase_count": len(graph.nodes),
            "edge_count": len(graph.edges),
        },
        profile=profile_payload,
        required_coverage=coverage,
    )


def _phase_to_node(phase: Mapping[str, Any]) -> ComputeNode:
    phase_id = _phase_id(phase)
    attributes = dict(phase.get("attributes", {}) or {})
    attributes.setdefault("phase_id", phase_id)
    if "label" in phase:
        attributes.setdefault("label", phase["label"])
    if "source" in phase:
        attributes.setdefault("source", phase["source"])

    return ComputeNode(
        node_id=phase_id,
        op_type=str(phase.get("op_type", phase.get("operation", "qe_phase"))),
        inputs=[str(item) for item in phase.get("inputs", []) or []],
        outputs=[str(item) for item in phase.get("outputs", []) or []],
        input_specs=_tensor_specs(phase.get("input_specs", {})),
        output_specs=_tensor_specs(phase.get("output_specs", {})),
        estimated_flops=float(phase.get("estimated_flops", phase.get("flops", 0.0)) or 0.0),
        estimated_memory_bytes=float(phase.get("estimated_memory_bytes", phase.get("memory_bytes", 0.0)) or 0.0),
        attributes=attributes,
    )


def _edge_to_data_edge(edge: Mapping[str, Any]) -> DataEdge:
    source = str(edge.get("source_node", edge.get("source", "")))
    target = str(edge.get("target_node", edge.get("target", "")))
    if not source or not target:
        raise ValueError("QE profile edges require source/source_node and target/target_node")
    attributes = dict(edge.get("attributes", {}) or {})
    if "bytes" in edge:
        attributes.setdefault("bytes", edge["bytes"])
    return DataEdge(
        source_node=source,
        target_node=target,
        tensor_name=str(edge.get("tensor_name", edge.get("tensor", ""))),
        tensor_spec=_optional_tensor_spec(edge.get("tensor_spec")),
        edge_kind=str(edge.get("edge_kind", "data")),
        attributes=attributes,
    )


def _profile_payload(required_coverage: list[str]) -> Dict[str, Any]:
    return {
        "schema_version": "dse.workload_profile.v1",
        "profile_id": PROFILE_ID,
        "profile_version": "v1",
        "workload_family": WORKLOAD_FAMILY,
        "accepted_source_kinds": ["qe_profile_json"],
        "accepted_sources": ["qe_profile_json"],
        "graph_pattern": "profiled_phase_dag",
        "lowering_policy": "identity_dag",
        "default_mapping_policies": ["host-baseline", "profile-declared"],
        "domain_validation": {
            "timing_only_allowed": True,
            "correctness_claim_requires_profile_evidence": True,
            "unclaimed_domain_correctness": "QE/DFT numerical correctness is not inferred from profile ingestion.",
        },
        "default_claim_boundary": "full_workload",
        "required_coverage": list(required_coverage),
        "description": "Standalone QE profile importer for DFT/QE profiled phase graphs.",
        "plugin_metadata": {
            "domain": DOMAIN,
            "importer_id": IMPORTER_ID,
            "scope": "profile_to_graph_package_only",
            "region_partitioning": False,
        },
    }


def _tensor_specs(payload: Any) -> Dict[str, TensorSpec]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ValueError("tensor specs must be an object keyed by tensor name")
    return {str(name): _tensor_spec(spec) for name, spec in payload.items()}


def _optional_tensor_spec(payload: Any) -> TensorSpec | None:
    if payload is None:
        return None
    return _tensor_spec(payload)


def _tensor_spec(payload: Any) -> TensorSpec:
    if not isinstance(payload, Mapping):
        raise ValueError("tensor spec must be an object")
    spec = dict(payload)
    if "dtype" in spec:
        spec["dtype"] = str(spec["dtype"]).upper()
    return TensorSpec.from_dict(spec)


def _phase_id(phase: Mapping[str, Any]) -> str:
    phase_id = str(phase.get("phase_id", phase.get("id", phase.get("node_id", ""))))
    if not phase_id:
        raise ValueError("QE profile phases require phase_id, id, or node_id")
    return phase_id


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key, ""))
    if not value:
        raise ValueError(f"QE profile field {key!r} is required")
    return value


def _require_mapping(payload: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"QE {name} must be an object")
    return payload


def _require_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"QE profile field {key!r} must be a list")
    return value


__all__ = [
    "DOMAIN",
    "WORKLOAD_FAMILY",
    "PROFILE_ID",
    "IMPORTER_ID",
    "load_qe_profile",
    "qe_profile_to_compute_graph",
    "qe_profile_to_workload_package",
]
