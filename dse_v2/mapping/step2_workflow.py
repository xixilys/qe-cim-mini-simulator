#!/usr/bin/env python3
"""Step2 architecture/mapping workflow for generic DSE.

Step2 is the handoff boundary between Step1 workload lowering and Step3+
simulation/evidence.  It consumes only serialized/generic Step1 artifacts,
selects an auditable architecture instance, builds a replayable DesignPoint,
runs workflow-aware mapping search, and writes the artifact set that downstream
simulation can reload without hidden Python process state.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from dse_v2.architecture.catalog import (
    ArchitectureCatalog,
    ArchitectureInstance,
    ArchitectureStatus,
    SimulationBinding,
    catalog_summary,
    seed_generic_dse_architecture_catalog,
)
from dse_v2.core.architecture.accelerator import (
    Accelerator,
    CommunicationCapability,
    ComputeCapability,
    HostLink,
    InterconnectTopology,
    MemoryHierarchy,
    MemoryLevel,
    PeerLink,
    PowerModel,
    SystemArchitecture,
)
from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload.lowering import GraphLoweringResult, lower_compute_graph
from dse_v2.core.workload.package import WorkloadPackage
from dse_v2.core.workload.step1_workflow import load_step1_workload_package
from dse_v2.core.workload.workflows import DIAGNOSTIC_CLAIM_BOUNDARIES
from dse_v2.codesign import (
    CODESIGN_L4_EVIDENCE_ARTIFACTS,
    CODESIGN_STEP2_ARTIFACTS,
    build_default_codesign_artifacts,
    validate_codesign_artifacts,
)
from dse_v2.dse.orchestrator import DesignPoint
from dse_v2.dse.analytical_evaluator import EnhancedAnalyticalEvaluator
from dse_v2.dse.tlm_evaluator import TLMEvaluator
from dse_v2.mapping.search import mapping_violations, run_mapping_search, target_ids
from dse_v2.promotion.promotion_engine import PromotionEngine

STEP2_REQUIRED_MAPPING_ARTIFACTS = [
    "mapping_legality_matrix.json",
    "mapping_seed_set.json",
    "mapping_candidate_records.json",
    "mapping_selected_record.json",
    "mapping_simulation_samples.json",
    "mapping_feedback_state.json",
    "convergence_status.json",
]

STEP2_LOW_FIDELITY_ARTIFACTS = [
    "l1_evaluation_result.json",
    "l1_promotion_decision.json",
    "l2_evaluation_result.json",
    "l2_promotion_decision.json",
    "low_fidelity_screening_summary.json",
]

STEP2_LOW_FIDELITY_ARTIFACT_KEYS = {
    "l1_evaluation_result": "l1_evaluation_result.json",
    "l1_promotion_decision": "l1_promotion_decision.json",
    "l2_evaluation_result": "l2_evaluation_result.json",
    "l2_promotion_decision": "l2_promotion_decision.json",
    "low_fidelity_summary": "low_fidelity_screening_summary.json",
}

STEP2_CANDIDATE_QUEUE_ARTIFACTS = [
    "architecture_candidate_set.json",
    "step3_simulation_queue.json",
]

STEP2_ARTIFACT_NAMES = [
    "step2_status.json",
    "architecture_catalog.json",
    "architecture.json",
    "design_point.json",
    "workload_package.json",
    "workload_graph.json",
    "graph_lowering_report.json",
    "executable_graph.json",
    "mapping.json",
    "mapping_promotion_decision.json",
] + STEP2_REQUIRED_MAPPING_ARTIFACTS + STEP2_LOW_FIDELITY_ARTIFACTS + CODESIGN_STEP2_ARTIFACTS + STEP2_CANDIDATE_QUEUE_ARTIFACTS

HARD_DOMAIN_REVIEW_FLAGS = {"project_critical_conflict", "segmentation_uncertain"}
SOFT_DOMAIN_REVIEW_FLAGS = {"insufficient_evidence", "important_input_parameter"}


@dataclass
class Step2WorkflowResult:
    """In-memory view of a completed or blocked Step2 workflow."""

    status: str
    trusted_final_eligible: bool
    workload_package: WorkloadPackage
    source_graph: ComputeGraph
    lowering: GraphLoweringResult
    executable_graph: Optional[ComputeGraph]
    architecture_instance: Optional[ArchitectureInstance]
    system_architecture: Optional[SystemArchitecture]
    design_point: Optional[DesignPoint]
    artifacts: Dict[str, Any] = field(default_factory=dict)
    artifact_paths: Dict[str, str] = field(default_factory=dict)
    reasons: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "trusted_final_eligible": self.trusted_final_eligible,
            "workload_id": self.workload_package.workload_id,
            "workload_family": self.workload_package.workload_family,
            "source_graph_id": self.source_graph.graph_id,
            "executable_graph_id": self.executable_graph.graph_id if self.executable_graph else None,
            "architecture_id": self.architecture_instance.architecture_id if self.architecture_instance else None,
            "design_point_id": self.design_point.design_point_id if self.design_point else None,
            "artifact_paths": dict(self.artifact_paths),
            "reasons": list(self.reasons),
        }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validation_messages(catalog: ArchitectureCatalog, architecture_id: str) -> List[Dict[str, Any]]:
    return [message.to_dict() for message in catalog.validate() if message.item_id in {architecture_id} or message.severity == "error"]


def _binding_payloads(catalog: ArchitectureCatalog, instance: ArchitectureInstance) -> Dict[str, Any]:
    payloads: Dict[str, Any] = {}
    for backend, binding_id in instance.simulation_bindings.items():
        binding = catalog.simulation_bindings.get(binding_id)
        if binding is None:
            payloads[backend] = {
                "binding_id": binding_id,
                "backend": backend,
                "status": "missing",
                "trusted_eligible": False,
                "unavailable_reason": "binding id is absent from catalog",
            }
        else:
            payloads[backend] = binding.to_dict()
    return payloads


def build_architecture_artifact(
    catalog: ArchitectureCatalog,
    instance: ArchitectureInstance,
    *,
    workload_package: WorkloadPackage,
    lowering: GraphLoweringResult,
    backend: str = "systemc",
) -> Dict[str, Any]:
    """Return the reviewable Step2 architecture artifact for one instance."""
    binding_payloads = _binding_payloads(catalog, instance)
    catalog_messages = _validation_messages(catalog, instance.architecture_id)
    catalog_has_errors = any(message.get("severity") == "error" for message in catalog_messages)
    catalog_trusted = instance.trusted_final_eligible(catalog.simulation_bindings)
    selected_binding = binding_payloads.get(backend, {})
    selected_binding_trusted = bool(selected_binding.get("trusted_eligible", False))
    full_workload_eligible = bool(lowering.report.get("full_workload_eligible", False)) and workload_package.is_full_workload()
    diagnostic_boundary = workload_package.claim_boundary in DIAGNOSTIC_CLAIM_BOUNDARIES

    reasons: List[Dict[str, Any]] = []
    candidate_reason = instance.candidate_only_reason(catalog.simulation_bindings)
    if candidate_reason:
        reasons.append({"reason_id": "architecture_candidate_only", "detail": candidate_reason})
    if catalog_has_errors:
        reasons.append({"reason_id": "catalog_validation_error", "detail": "catalog validation has errors", "messages": catalog_messages})
    if not selected_binding_trusted:
        reasons.append({
            "reason_id": "missing_or_untrusted_binding",
            "backend": backend,
            "detail": selected_binding.get("unavailable_reason") or "selected backend binding is missing, stub, planned, prototype, or unsupported",
        })
    if not full_workload_eligible:
        reasons.append({
            "reason_id": "workload_not_full_eligible",
            "claim_boundary": workload_package.claim_boundary,
            "lowering_status": lowering.report.get("status"),
            "detail": "Step1 lowering/claim boundary is not eligible for trusted final promotion",
        })
    if diagnostic_boundary:
        reasons.append({
            "reason_id": "diagnostic_claim_boundary",
            "claim_boundary": workload_package.claim_boundary,
            "detail": "diagnostic, smoke, synthetic, trace-only, or reduced inputs cannot become final trusted claims",
        })

    trusted_final_eligible = catalog_trusted and selected_binding_trusted and full_workload_eligible and not catalog_has_errors and not diagnostic_boundary
    return {
        "schema_version": "dse.step2.architecture.v1",
        "catalog_version": catalog.version,
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "source_graph_id": workload_package.graph.graph_id,
        "executable_graph_id": lowering.report.get("executable_graph_id"),
        "architecture_id": instance.architecture_id,
        "architecture_family": instance.family_id,
        "architecture_instance": instance.to_dict(include_bindings=True),
        "components": [component.to_dict() for component in instance.components],
        "constraints": instance.constraints.to_dict(),
        "simulation_bindings": binding_payloads,
        "selected_backend": backend,
        "selected_backend_binding": selected_binding,
        "validation": {
            "catalog_valid": not catalog_has_errors,
            "messages": catalog_messages,
            "catalog_trusted_final_eligible": catalog_trusted,
            "selected_binding_trusted_eligible": selected_binding_trusted,
            "full_workload_eligible": full_workload_eligible,
            "diagnostic_boundary": diagnostic_boundary,
        },
        "status": ArchitectureStatus.TRUSTED_FINAL_ELIGIBLE if trusted_final_eligible else ArchitectureStatus.CANDIDATE_ONLY,
        "trusted_final_eligible": trusted_final_eligible,
        "candidate_only_reasons": reasons,
    }


def _component_peak_flops(component_type_id: str, precision: str) -> float:
    if component_type_id == "gpu_sm":
        return {"FP64": 9.7e12, "FP32": 19.5e12, "FP16": 156.0e12, "INT8": 0.0}.get(precision, 0.0)
    if component_type_id == "fpga_fabric":
        return {"FP64": 1.0e12, "FP32": 8.0e12, "INT8": 32.0e12}.get(precision, 0.0)
    if component_type_id == "cim_array":
        return {"FP64": 0.1e12, "FP32": 0.5e12, "INT8": 4.0e12}.get(precision, 0.0)
    if component_type_id == "asic_block":
        return {"FP64": 2.0e12, "FP32": 8.0e12}.get(precision, 0.0)
    return {"FP64": 0.25e12, "FP32": 1.0e12}.get(precision, 0.0)


def _op_efficiency(component_type_id: str, op_type: str) -> float:
    if op_type in {"gemm", "batched_gemm", "conv2d", "attention"}:
        return 0.90 if component_type_id in {"gpu_sm", "fpga_fabric", "cim_array"} else 0.55
    if op_type in {"fft", "stencil", "stream"}:
        return 0.80 if component_type_id == "fpga_fabric" else 0.55
    if op_type in {"eigen", "eigensolver", "diagonalize"}:
        return 0.35 if component_type_id in {"gpu_sm", "fpga_fabric", "asic_block"} else 0.10
    if op_type in {"reduction", "elementwise", "vector_add"}:
        return 0.85 if component_type_id in {"fpga_fabric", "cim_array"} else 0.65
    return 0.50


def architecture_instance_to_system_architecture(instance: ArchitectureInstance) -> SystemArchitecture:
    """Convert a catalog instance into the SystemArchitecture object used by backends."""
    host_cores = 64
    host_memory_gb = 64.0
    host_ids = {component.component_id for component in instance.components if component.role.startswith("control_host") or component.component_type_id == "host_cpu"}
    if not host_ids:
        host_ids = {"host-0"}

    accelerators: List[Accelerator] = []
    for component in instance.components:
        if component.component_type_id in {"host_cpu", "hbm_memory", "noc_interconnect"}:
            if component.component_type_id == "host_cpu" and component.memory_bytes:
                host_memory_gb = max(host_memory_gb, component.memory_bytes / 1024**3)
            continue
        if component.role == "shared_hbm" or component.component_type_id.endswith("memory"):
            continue

        accel_type = {
            "fpga_fabric": "fpga",
            "gpu_sm": "gpu",
            "cim_array": "cim",
            "asic_block": "asic",
        }.get(component.component_type_id, "custom")
        precisions = list(component.precision_support or ["FP64"])
        peak_flops = {precision: _component_peak_flops(component.component_type_id, precision) for precision in precisions}
        supported_ops = list(component.supported_ops)
        op_efficiency = {op_type: _op_efficiency(component.component_type_id, op_type) for op_type in supported_ops}
        memory_capacity = max(int(component.memory_bytes or 0), 1 * 1024 * 1024)
        bandwidth = float(component.bandwidth_gbps or 64.0)
        memory = MemoryHierarchy([
            MemoryLevel(
                name=f"{component.component_id}_local",
                capacity_bytes=memory_capacity,
                bandwidth_gbps=bandwidth,
                latency_ns=50.0,
                mem_type="HBM" if bandwidth >= 400.0 else "SRAM",
            )
        ])
        peer_links = [
            PeerLink(peer, "catalog_route", bandwidth, 1.0)
            for peer in component.connected_to
            if peer not in host_ids
        ]
        host_link = HostLink("catalog_host_route", bandwidth, 2.0) if any(peer in host_ids for peer in component.connected_to) else None
        accelerators.append(Accelerator(
            accel_id=component.component_id,
            accel_type=accel_type,
            compute=ComputeCapability(
                peak_flops=peak_flops,
                supported_ops=supported_ops,
                op_efficiency=op_efficiency,
                special_capabilities=[component.role],
            ),
            memory=memory,
            communication=CommunicationCapability(
                peer_links=peer_links,
                host_link=host_link,
                supported_primitives=["send", "recv", "dma"],
            ),
            power=PowerModel(static_power_w=float(component.power_w or 0.0)),
            vendor="catalog",
            model=component.component_type_id,
            version="step2",
        ))

    topology = instance.interconnect_topology or {}
    interconnect = InterconnectTopology(
        topology_type=str(topology.get("type", "catalog_interconnect")),
        bandwidth_gbps=float(topology.get("bandwidth_gbps", 64.0) or 64.0),
        latency_us=float(topology.get("latency_us", 1.0) or 1.0),
    )
    return SystemArchitecture(
        system_id=instance.architecture_id,
        host_cpu_cores=host_cores,
        host_memory_gb=host_memory_gb,
        accelerators=accelerators,
        interconnect=interconnect,
        max_power_w=float(instance.constraints.max_power_w or 1000.0),
        max_area_mm2=float(instance.constraints.max_area_mm2 or 1000.0),
    )


def _memory_level_from_dict(data: Mapping[str, Any]) -> MemoryLevel:
    return MemoryLevel(
        name=str(data.get("name", "memory")),
        capacity_bytes=int(data.get("capacity_bytes", 0) or 0),
        bandwidth_gbps=float(data.get("bandwidth_gbps", 0.0) or 0.0),
        latency_ns=float(data.get("latency_ns", 0.0) or 0.0),
        mem_type=str(data.get("type", data.get("mem_type", "SRAM"))),
    )


def system_architecture_from_dict(data: Mapping[str, Any]) -> SystemArchitecture:
    """Reconstruct SystemArchitecture from a persisted DesignPoint artifact."""
    accelerators: List[Accelerator] = []
    for accel_data in data.get("accelerators", []) or []:
        compute_data = accel_data.get("compute", {}) or {}
        memory_data = accel_data.get("memory", {}) or {}
        communication_data = accel_data.get("communication", {}) or {}
        power_data = accel_data.get("power", {}) or {}
        host_link_data = communication_data.get("host_link")
        host_link = None
        if isinstance(host_link_data, Mapping):
            host_link = HostLink(
                link_type=str(host_link_data.get("link_type", "pcie")),
                bandwidth_gbps=float(host_link_data.get("bandwidth_gbps", 0.0) or 0.0),
                latency_us=float(host_link_data.get("latency_us", 0.0) or 0.0),
            )
        peer_links = [
            PeerLink(
                target_accel_id=str(link.get("target_accel_id", "")),
                link_type=str(link.get("link_type", "custom")),
                bandwidth_gbps=float(link.get("bandwidth_gbps", 0.0) or 0.0),
                latency_us=float(link.get("latency_us", 0.0) or 0.0),
            )
            for link in communication_data.get("peer_links", []) or []
            if isinstance(link, Mapping)
        ]
        accelerators.append(Accelerator(
            accel_id=str(accel_data.get("accel_id", "")),
            accel_type=str(accel_data.get("accel_type", "custom")),
            compute=ComputeCapability(
                peak_flops={str(k): float(v or 0.0) for k, v in (compute_data.get("peak_flops", {}) or {}).items()},
                supported_ops=[str(op) for op in compute_data.get("supported_ops", []) or []],
                op_efficiency={str(k): float(v or 0.0) for k, v in (compute_data.get("op_efficiency", {}) or {}).items()},
                special_capabilities=[str(x) for x in compute_data.get("special_capabilities", []) or []],
            ),
            memory=MemoryHierarchy([_memory_level_from_dict(level) for level in memory_data.get("levels", []) or []]),
            communication=CommunicationCapability(
                peer_links=peer_links,
                host_link=host_link,
                supported_primitives=[str(x) for x in communication_data.get("supported_primitives", []) or []],
            ),
            power=PowerModel(static_power_w=float(power_data.get("static_power_w", 0.0) or 0.0)),
            vendor=str(accel_data.get("vendor", "")),
            model=str(accel_data.get("model", "")),
            version=str(accel_data.get("version", "")),
        ))
    interconnect_data = data.get("interconnect")
    interconnect = None
    if isinstance(interconnect_data, Mapping):
        interconnect = InterconnectTopology(
            topology_type=str(interconnect_data.get("topology_type", "custom")),
            bandwidth_gbps=float(interconnect_data.get("bandwidth_gbps", 0.0) or 0.0),
            latency_us=float(interconnect_data.get("latency_us", 0.0) or 0.0),
        )
    return SystemArchitecture(
        system_id=str(data.get("system_id", "")),
        host_cpu_cores=int(data.get("host_cpu_cores", 1) or 1),
        host_memory_gb=float(data.get("host_memory_gb", 32.0) or 32.0),
        accelerators=accelerators,
        interconnect=interconnect,
        max_power_w=float(data.get("max_power_w", 1000.0) or 1000.0),
        max_area_mm2=float(data.get("max_area_mm2", 1000.0) or 1000.0),
    )


def design_point_from_dict(payload: Mapping[str, Any]) -> DesignPoint:
    """Reconstruct a backend-ready DesignPoint from persisted JSON."""
    return DesignPoint(
        design_point_id=str(payload.get("design_point_id", "")),
        system_architecture=system_architecture_from_dict(payload.get("system_architecture", {}) or {}),
        task_mapping={str(k): str(v) for k, v in (payload.get("task_mapping", {}) or {}).items()},
        scheduling_policy=str(payload.get("scheduling_policy", "static")),
        config=dict(payload.get("config", {}) or {}),
    )


def load_step2_design_point(run_dir: Path) -> DesignPoint:
    """Load the selected Step2 DesignPoint artifact from disk."""
    payload = json.loads((Path(run_dir) / "design_point.json").read_text(encoding="utf-8"))
    return design_point_from_dict(payload)


def _status_reason(reason_id: str, detail: str, **extra: Any) -> Dict[str, Any]:
    payload = {"reason_id": reason_id, "detail": detail}
    payload.update(extra)
    return payload


def _blocked_result(
    *,
    status: str,
    reasons: List[Dict[str, Any]],
    workload_package: WorkloadPackage,
    lowering: GraphLoweringResult,
    output_dir: Optional[Path],
    catalog: Optional[ArchitectureCatalog] = None,
    architecture_instance: Optional[ArchitectureInstance] = None,
    architecture_artifact: Optional[Mapping[str, Any]] = None,
) -> Step2WorkflowResult:
    artifacts: Dict[str, Any] = {
        "step2_status": {
            "schema_version": "dse.step2.status.v1",
            "status": status,
            "trusted_final_eligible": False,
            "workload_id": workload_package.workload_id,
            "workload_family": workload_package.workload_family,
            "source_graph_id": workload_package.graph.graph_id,
            "executable_graph_id": lowering.report.get("executable_graph_id"),
            "reasons": reasons,
        },
        "workload_package": workload_package.to_dict(),
        "workload_graph": workload_package.graph.to_dict(),
        "graph_lowering_report": lowering.report,
    }
    if catalog is not None:
        catalog_payload = catalog.to_dict()
        catalog_payload["summary"] = catalog_summary(catalog)
        artifacts["architecture_catalog"] = catalog_payload
    if architecture_artifact is not None:
        artifacts["architecture"] = dict(architecture_artifact)

    artifact_paths: Dict[str, str] = {}
    if output_dir is not None:
        output = Path(output_dir)
        for key, filename in [
            ("step2_status", "step2_status.json"),
            ("workload_package", "workload_package.json"),
            ("workload_graph", "workload_graph.json"),
            ("graph_lowering_report", "graph_lowering_report.json"),
            ("architecture_catalog", "architecture_catalog.json"),
            ("architecture", "architecture.json"),
        ]:
            if key in artifacts:
                _write_json(output / filename, artifacts[key])
                artifact_paths[key] = filename
    return Step2WorkflowResult(
        status=status,
        trusted_final_eligible=False,
        workload_package=workload_package,
        source_graph=workload_package.graph,
        lowering=lowering,
        executable_graph=lowering.executable_graph,
        architecture_instance=architecture_instance,
        system_architecture=None,
        design_point=None,
        artifacts=artifacts,
        artifact_paths=artifact_paths,
        reasons=reasons,
    )


def _json_safe(value: Any) -> Any:
    """Return a strict JSON-safe copy, replacing non-finite floats with None."""
    if is_dataclass(value):
        value = asdict(value)
    elif hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return []
    if isinstance(value, Iterable):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _candidate_hint_domain_policy(candidate_hints: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(candidate_hints, Mapping) or not candidate_hints:
        return {}
    raw = candidate_hints.get("domain_policy", {})
    policy = dict(raw) if isinstance(raw, Mapping) else {}
    policy.setdefault("policy_id", str(candidate_hints.get("policy_id") or "domain_policy"))
    if "domain_key" in candidate_hints:
        policy.setdefault("domain_key", candidate_hints.get("domain_key"))
    if "matched" in candidate_hints:
        policy.setdefault("matched", bool(candidate_hints.get("matched")))
    return {
        str(key): value
        for key, value in policy.items()
        if key in {"policy_id", "domain_key", "matched", "policy_version"}
    }


def _candidate_hint_review_flags(candidate_hints: Optional[Mapping[str, Any]]) -> List[str]:
    if not isinstance(candidate_hints, Mapping):
        return []
    flags: List[str] = []
    for key in ("review_flags", "review_required_flags", "hard_block_flags", "hard_review_flags"):
        flags.extend(_string_list(candidate_hints.get(key)))
    review = candidate_hints.get("review", {})
    if isinstance(review, Mapping):
        flags.extend(_string_list(review.get("flags")))
        flags.extend(_string_list(review.get("hard_block_flags")))
        flags.extend(_string_list(review.get("review_required_flags")))
    return sorted(dict.fromkeys(flag for flag in flags if flag))


def _candidate_hint_phase_groups(candidate_hints: Optional[Mapping[str, Any]]) -> List[Any]:
    if not isinstance(candidate_hints, Mapping):
        return []
    phase_groups = candidate_hints.get("phase_groups")
    if phase_groups is None:
        annotations = candidate_hints.get("annotations", {})
        if isinstance(annotations, Mapping):
            dft_annotations = annotations.get("dft", {})
            if isinstance(dft_annotations, Mapping):
                phase_groups = dft_annotations.get("phase_groups")
    return list(phase_groups) if isinstance(phase_groups, list) else []


def _candidate_hint_metadata(candidate_hints: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(candidate_hints, Mapping) or not candidate_hints:
        return {}
    review_flags = _candidate_hint_review_flags(candidate_hints)
    metadata: Dict[str, Any] = {
        "domain_policy": _candidate_hint_domain_policy(candidate_hints),
        "review_flags": review_flags,
        "review_required": bool(candidate_hints.get("review_required", False) or review_flags),
        "review_status": "review_required" if (candidate_hints.get("review_required", False) or review_flags) else "not_required",
        "claim_boundary": str(candidate_hints.get("claim_boundary", "candidate_only")),
        "trusted_final_claim": False,
    }
    phase_groups = _candidate_hint_phase_groups(candidate_hints)
    if phase_groups:
        metadata["phase_groups"] = phase_groups
    annotations = candidate_hints.get("annotations")
    if isinstance(annotations, Mapping):
        metadata["policy_annotations"] = dict(annotations)
    return metadata


def _attach_candidate_hint_metadata(payload: Dict[str, Any], candidate_hints: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    metadata = _candidate_hint_metadata(candidate_hints)
    if not metadata:
        return payload
    for key in ("domain_policy", "review_flags", "review_required", "review_status", "phase_groups", "claim_boundary", "trusted_final_claim"):
        if key in metadata:
            payload[key] = metadata[key]
    annotations = dict(payload.get("annotations", {}) if isinstance(payload.get("annotations", {}), Mapping) else {})
    annotations.setdefault("domain_policy", metadata.get("domain_policy", {}))
    annotations.setdefault("review_flags", list(metadata.get("review_flags", []) or []))
    annotations.setdefault("review_status", metadata.get("review_status", "not_required"))
    annotations.setdefault("claim_boundary", metadata.get("claim_boundary", "candidate_only"))
    annotations.setdefault("trusted_final_claim", False)
    if "phase_groups" in metadata:
        annotations.setdefault("phase_groups", metadata["phase_groups"])
    if "policy_annotations" in metadata:
        annotations.setdefault("policy_annotations", metadata["policy_annotations"])
    payload["annotations"] = annotations
    return payload


def _hard_review_flags(candidate_hints: Optional[Mapping[str, Any]], review_flags: Sequence[str]) -> List[str]:
    hard_defaults = {"project_critical_conflict", "segmentation_uncertain"}
    explicit = set()
    if isinstance(candidate_hints, Mapping):
        explicit.update(_string_list(candidate_hints.get("hard_block_flags")))
        explicit.update(_string_list(candidate_hints.get("hard_review_flags")))
    return sorted(flag for flag in set(review_flags) if flag in hard_defaults or flag in explicit)


def _result_to_dict(result: Any) -> Dict[str, Any]:
    payload = _json_safe(result)
    return payload if isinstance(payload, dict) else {"value": payload}


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _metric_payload(result: Mapping[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    for key in keys:
        if key in result:
            metrics[key] = _json_safe(result[key])
    return metrics


def _low_fidelity_family(design_point: DesignPoint) -> str:
    if not design_point.system_architecture.accelerators:
        return "F1"
    accel_type = design_point.system_architecture.accelerators[0].accel_type
    return {
        "fpga": "F1",
        "gpu": "F3",
        "cim": "F4",
        "asic": "F5",
    }.get(accel_type, "F1")


def _normalize_low_fidelity_policy(policy: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    merged = {
        "schema_version": "dse.step2.low_fidelity_policy.v1",
        "require_l1": True,
        "require_l2": True,
        "enable_l2": True,
        "l1_evaluator": "dse_v2.dse.analytical_evaluator.EnhancedAnalyticalEvaluator",
        "l2_evaluator": "dse_v2.dse.tlm_evaluator.TLMEvaluator",
        "promotion_engine": "dse_v2.promotion.promotion_engine.PromotionEngine",
        "step3_gate": "l1_status_and_required_l2_to_l3_promotion",
    }
    merged.update(dict(policy or {}))
    merged["require_l1"] = bool(merged.get("require_l1", True))
    merged["require_l2"] = bool(merged.get("require_l2", True))
    merged["enable_l2"] = bool(merged.get("enable_l2", True))
    return merged


def _low_fidelity_provenance(
    *,
    layer: str,
    design_point: DesignPoint,
    compute_graph: ComputeGraph,
    evaluator: str,
) -> Dict[str, Any]:
    return {
        "layer": layer,
        "evaluator": evaluator,
        "design_point_id": design_point.design_point_id,
        "compute_graph_id": compute_graph.graph_id,
        "mapping_id": design_point.config.get("mapping_id"),
        "candidate_id": design_point.config.get("selected_candidate_id"),
        "replay_inputs": {
            "design_point": "design_point.json",
            "executable_graph": "executable_graph.json",
            "mapping_selected_record": "mapping_selected_record.json",
        },
    }


def _normalize_l1_result(
    raw_result: Any,
    *,
    design_point: DesignPoint,
    compute_graph: ComputeGraph,
    selected_record: Mapping[str, Any],
) -> Dict[str, Any]:
    result = _result_to_dict(raw_result)
    feasible = bool(result.get("feasible", True))
    violations = [str(reason) for reason in result.get("violation_reasons", []) or []]
    screening = selected_record.get("screening", {}) if isinstance(selected_record.get("screening", {}), Mapping) else {}
    screening_confidence = _finite_float(screening.get("confidence"), 0.60)
    compute_efficiency = _finite_float(result.get("compute_efficiency"), 0.0)
    memory_efficiency = _finite_float(result.get("memory_efficiency"), 0.0)
    confidence = max(0.0, min(0.92, max(screening_confidence, 0.55 + 0.25 * min(memory_efficiency, 1.0) + 0.10 * min(compute_efficiency * 10.0, 1.0))))
    promotion_score = max(0.0, min(1.0, 0.55 + 0.40 * confidence))
    power_w = _finite_float(result.get("power_w"), 0.0)
    power_limit = max(_finite_float(design_point.system_architecture.max_power_w, 1000.0), 1.0)

    metrics = _metric_payload(result, [
        "latency_ms",
        "throughput_gops",
        "power_w",
        "energy_j",
        "area_mm2",
        "compute_efficiency",
        "memory_efficiency",
        "total_data_movement_mb",
        "communication_overhead_ms",
    ])
    nonfinite_metrics = sorted(key for key in metrics if metrics[key] is None)
    status = "passed" if feasible and not violations else "failed"
    return {
        "schema_version": "dse.step2.l1_evaluation_result.v1",
        "fidelity_level_achieved": "L1",
        "layer": "L1",
        "status": status,
        "design_point_id": design_point.design_point_id,
        "family": _low_fidelity_family(design_point),
        "metrics": metrics,
        "feasible": feasible,
        "violation_reasons": violations,
        "confidence": confidence,
        "uncertainty": {
            "confidence_level": confidence,
            "model": "analytical_roofline_parallel_schedule",
            "nonfinite_metrics": nonfinite_metrics,
        },
        "promotion_score": promotion_score,
        "resource_legal": not violations,
        "resource_utilization": {
            "power_percent": min(999.0, power_w / power_limit * 100.0),
        },
        "candidate_id": selected_record.get("candidate_id"),
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
        "provenance": _low_fidelity_provenance(
            layer="L1",
            design_point=design_point,
            compute_graph=compute_graph,
            evaluator="EnhancedAnalyticalEvaluator",
        ),
        "raw_result": result,
    }


def _normalize_l2_result(
    raw_result: Any,
    *,
    design_point: DesignPoint,
    compute_graph: ComputeGraph,
    selected_record: Mapping[str, Any],
) -> Dict[str, Any]:
    result = _result_to_dict(raw_result)
    tlm_details = result.get("tlm_details", {}) if isinstance(result.get("tlm_details", {}), Mapping) else {}
    status = str(tlm_details.get("status") or ("passed" if result.get("feasible") else "failed"))
    confidence = _finite_float(tlm_details.get("confidence"), 0.0)
    promotion_score = _finite_float(tlm_details.get("promotion_score"), 0.0)
    mape_percent = max(5.0, 22.0 * (1.0 - confidence)) if confidence else 100.0
    metrics = _metric_payload(result, [
        "latency_ms",
        "throughput_gops",
        "power_w",
        "energy_j",
        "area_mm2",
        "compute_efficiency",
        "memory_efficiency",
        "total_data_movement_mb",
        "communication_overhead_ms",
    ])
    return {
        "schema_version": "dse.step2.l2_evaluation_result.v1",
        "fidelity_level_achieved": "L2",
        "layer": "L2",
        "status": status,
        "design_point_id": design_point.design_point_id,
        "family": str(tlm_details.get("family") or _low_fidelity_family(design_point)),
        "metrics": metrics,
        "feasible": bool(result.get("feasible", status == "passed")),
        "confidence": confidence,
        "uncertainty": {
            "confidence_level": confidence,
            "mape_percent": mape_percent,
            "model": "python_transaction_level_model",
        },
        "mape_percent": mape_percent,
        "promotion_score": promotion_score,
        "resource_utilization": _json_safe(tlm_details.get("resource_utilization", {})),
        "candidate_id": selected_record.get("candidate_id"),
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
        "provenance": _low_fidelity_provenance(
            layer="L2",
            design_point=design_point,
            compute_graph=compute_graph,
            evaluator="TLMEvaluator",
        ),
        "raw_result": result,
    }


def _blocked_low_fidelity_result(
    *,
    layer: str,
    design_point: DesignPoint,
    compute_graph: ComputeGraph,
    selected_record: Mapping[str, Any],
    reason_id: str,
    detail: str,
) -> Dict[str, Any]:
    return {
        "schema_version": f"dse.step2.{layer.lower()}_evaluation_result.v1",
        "fidelity_level_achieved": layer,
        "layer": layer,
        "status": "blocked",
        "design_point_id": design_point.design_point_id,
        "family": _low_fidelity_family(design_point),
        "metrics": {},
        "feasible": False,
        "confidence": 0.0,
        "uncertainty": {"confidence_level": 0.0},
        "promotion_score": 0.0,
        "candidate_id": selected_record.get("candidate_id"),
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
        "blockers": [{"reason_id": reason_id, "detail": detail}],
        "provenance": _low_fidelity_provenance(
            layer=layer,
            design_point=design_point,
            compute_graph=compute_graph,
            evaluator="not_run" if reason_id.endswith("_skipped") else "exception",
        ),
    }


def _promotion_decision_payload(decision: Any, *, artifact: str) -> Dict[str, Any]:
    payload = _result_to_dict(decision)
    promote = bool(payload.get("promote", False))
    return {
        "schema_version": "dse.step2.low_fidelity_promotion_decision.v1",
        "artifact": artifact,
        "from_layer": payload.get("from_layer"),
        "source_layer": payload.get("from_layer"),
        "to_layer": payload.get("to_layer"),
        "target_layer": payload.get("to_layer"),
        "decision": "promote" if promote else "block",
        "promote": promote,
        "reason": payload.get("reason", "unknown"),
        "promotion_score": _json_safe(payload.get("promotion_score")),
        "score": _json_safe(payload.get("promotion_score")),
        "confidence": _json_safe(payload.get("confidence")),
        "threshold": _json_safe(payload.get("threshold")),
        "details": _json_safe(payload.get("details", {})),
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
    }


def _skipped_promotion_decision_payload(
    *,
    from_layer: str,
    to_layer: str,
    reason: str,
    artifact: str,
) -> Dict[str, Any]:
    return {
        "schema_version": "dse.step2.low_fidelity_promotion_decision.v1",
        "artifact": artifact,
        "from_layer": from_layer,
        "source_layer": from_layer,
        "to_layer": to_layer,
        "target_layer": to_layer,
        "decision": "skipped",
        "promote": False,
        "reason": reason,
        "promotion_score": None,
        "score": None,
        "confidence": None,
        "threshold": None,
        "details": {"status": "skipped"},
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
    }


def _evaluate_layer_promotion(result: Mapping[str, Any], *, artifact: str) -> Dict[str, Any]:
    try:
        decision = PromotionEngine().evaluate(result)
    except Exception as exc:
        layer = str(result.get("fidelity_level_achieved", "L1"))
        target = "L3" if layer == "L2" else "L2"
        return {
            "schema_version": "dse.step2.low_fidelity_promotion_decision.v1",
            "artifact": artifact,
            "from_layer": layer,
            "source_layer": layer,
            "to_layer": target,
            "target_layer": target,
            "decision": "block",
            "promote": False,
            "reason": "promotion_engine_exception",
            "promotion_score": result.get("promotion_score"),
            "score": result.get("promotion_score"),
            "confidence": result.get("confidence"),
            "threshold": None,
            "details": {"exception": str(exc)},
            "candidate_generation_only": True,
            "low_fidelity_role": "candidate_generator_only",
            "trusted_final_claim": False,
        }
    return _promotion_decision_payload(decision, artifact=artifact)


def _low_fidelity_summary_payload(
    *,
    policy: Mapping[str, Any],
    selected_record: Mapping[str, Any],
    l1_result: Mapping[str, Any],
    l1_decision: Mapping[str, Any],
    l2_result: Mapping[str, Any],
    l2_decision: Mapping[str, Any],
) -> Dict[str, Any]:
    require_l1 = bool(policy.get("require_l1", True))
    require_l2 = bool(policy.get("require_l2", True))
    blockers: List[Dict[str, Any]] = []

    if selected_record.get("violations"):
        blockers.append({
            "reason_id": "illegal_selected_mapping",
            "detail": "selected mapping has legality violations before low-fidelity screening",
            "violations": list(selected_record.get("violations", []) or []),
        })
    if require_l1 and l1_result.get("status") != "passed":
        blockers.append({
            "reason_id": "l1_screening_not_passed",
            "detail": "required L1 analytical screening did not pass",
            "status": l1_result.get("status"),
        })
    if require_l2:
        if l2_result.get("status") != "passed":
            blockers.append({
                "reason_id": "l2_screening_not_passed",
                "detail": "required L2 TLM screening did not pass",
                "status": l2_result.get("status"),
            })
        if not bool(l2_decision.get("promote", False)):
            blockers.append({
                "reason_id": "l2_to_l3_promotion_blocked",
                "detail": "required L2->L3 promotion decision did not allow Step3 entry",
                "decision_reason": l2_decision.get("reason"),
                "threshold": l2_decision.get("threshold"),
                "score": l2_decision.get("promotion_score"),
                "confidence": l2_decision.get("confidence"),
            })

    passed = not blockers
    return {
        "schema_version": "dse.step2.low_fidelity_screening_summary.v1",
        "required_for_step3": True,
        "passed": passed,
        "status": "passed" if passed else "failed",
        "require_l1": require_l1,
        "require_l2": require_l2,
        "policy": dict(policy),
        "candidate_id": selected_record.get("candidate_id"),
        "mapping_id": selected_record.get("mapping_id"),
        "artifact_refs": dict(STEP2_LOW_FIDELITY_ARTIFACT_KEYS),
        "required_artifacts": list(STEP2_LOW_FIDELITY_ARTIFACTS),
        "promotion_scores": {
            "l1_to_l2": l1_decision.get("promotion_score"),
            "l2_to_l3": l2_decision.get("promotion_score"),
        },
        "thresholds": {
            "l1_to_l2": l1_decision.get("threshold"),
            "l2_to_l3": l2_decision.get("threshold"),
        },
        "confidence": {
            "l1": l1_result.get("confidence"),
            "l2": l2_result.get("confidence"),
        },
        "decisions": {
            "l1_to_l2": {
                "artifact": "l1_promotion_decision.json",
                "decision": l1_decision.get("decision"),
                "promote": bool(l1_decision.get("promote", False)),
                "reason": l1_decision.get("reason"),
            },
            "l2_to_l3": {
                "artifact": "l2_promotion_decision.json",
                "decision": l2_decision.get("decision"),
                "promote": bool(l2_decision.get("promote", False)),
                "reason": l2_decision.get("reason"),
            },
        },
        "blockers": blockers,
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
        "trusted_final_eligible": False,
        "notes": [
            "L1/L2 evidence is only a candidate-generation gate for Step3 entry.",
            "Final ranking and trusted winners require Step3+ high-fidelity evidence.",
        ],
    }


def run_low_fidelity_screening(
    design_point: DesignPoint,
    compute_graph: ComputeGraph,
    *,
    selected_record: Optional[Mapping[str, Any]] = None,
    low_fidelity_policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Run Step2-owned L1/L2 screening and return replayable artifact payloads."""
    policy = _normalize_low_fidelity_policy(low_fidelity_policy)
    selected = selected_record or {}

    try:
        raw_l1 = EnhancedAnalyticalEvaluator().evaluate(design_point, compute_graph)
        l1_result = _normalize_l1_result(
            raw_l1,
            design_point=design_point,
            compute_graph=compute_graph,
            selected_record=selected,
        )
    except Exception as exc:
        l1_result = _blocked_low_fidelity_result(
            layer="L1",
            design_point=design_point,
            compute_graph=compute_graph,
            selected_record=selected,
            reason_id="l1_evaluator_exception",
            detail=str(exc),
        )
    l1_decision = _evaluate_layer_promotion(l1_result, artifact="l1_promotion_decision.json")

    l2_required = bool(policy.get("require_l2", True))
    l2_enabled = bool(policy.get("enable_l2", True))
    should_run_l2 = l2_enabled and (l2_required or bool(l1_decision.get("promote", False)))
    if should_run_l2:
        try:
            raw_l2 = TLMEvaluator().evaluate(design_point, compute_graph)
            l2_result = _normalize_l2_result(
                raw_l2,
                design_point=design_point,
                compute_graph=compute_graph,
                selected_record=selected,
            )
        except Exception as exc:
            l2_result = _blocked_low_fidelity_result(
                layer="L2",
                design_point=design_point,
                compute_graph=compute_graph,
                selected_record=selected,
                reason_id="l2_evaluator_exception",
                detail=str(exc),
            )
        l2_decision = _evaluate_layer_promotion(l2_result, artifact="l2_promotion_decision.json")
    else:
        reason = "l2_disabled_by_policy" if not l2_enabled else "l2_not_required_by_policy"
        l2_result = _blocked_low_fidelity_result(
            layer="L2",
            design_point=design_point,
            compute_graph=compute_graph,
            selected_record=selected,
            reason_id=f"{reason}_skipped",
            detail="L2 TLM screening was explicitly skipped by Step2 low-fidelity policy.",
        )
        l2_result["status"] = "skipped"
        l2_decision = _skipped_promotion_decision_payload(
            from_layer="L2",
            to_layer="L3",
            reason=reason,
            artifact="l2_promotion_decision.json",
        )

    summary = _low_fidelity_summary_payload(
        policy=policy,
        selected_record=selected,
        l1_result=l1_result,
        l1_decision=l1_decision,
        l2_result=l2_result,
        l2_decision=l2_decision,
    )
    return {
        "l1_evaluation_result": l1_result,
        "l1_promotion_decision": l1_decision,
        "l2_evaluation_result": l2_result,
        "l2_promotion_decision": l2_decision,
        "low_fidelity_summary": summary,
    }


def _promotion_decision(
    *,
    architecture_artifact: Mapping[str, Any],
    selected_record: Mapping[str, Any],
    backend: str,
    evidence_mode: str,
    required_coverage: Sequence[str],
    simulation_budget: int,
    require_l4_proof: bool = False,
    l4_reason: str = "software-visible descriptor/request/completion proof requested for co-design claim",
    low_fidelity_summary: Optional[Mapping[str, Any]] = None,
    candidate_hints: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    selected_legal = not selected_record.get("violations")
    architecture_trusted = bool(architecture_artifact.get("trusted_final_eligible", False))
    low_fidelity_passed = True if low_fidelity_summary is None else bool(low_fidelity_summary.get("passed", False))
    review_flags = _candidate_hint_review_flags(candidate_hints)
    hard_review_flags = _hard_review_flags(candidate_hints, review_flags)
    review_required = bool((candidate_hints or {}).get("review_required", False) or review_flags) if isinstance(candidate_hints, Mapping) else False
    base_promoted = selected_legal and architecture_trusted and low_fidelity_passed
    promoted = base_promoted and not hard_review_flags
    reasons: List[Dict[str, Any]] = []
    if not selected_legal:
        reasons.append({"reason_id": "illegal_selected_mapping", "violations": list(selected_record.get("violations", []) or [])})
    if not architecture_trusted:
        reasons.extend(list(architecture_artifact.get("candidate_only_reasons", []) or []))
    if not low_fidelity_passed:
        reasons.append({
            "reason_id": "low_fidelity_screening_failed",
            "detail": "Step2 L1/L2 screening summary did not satisfy the pre-Step3 gate",
            "blockers": list((low_fidelity_summary or {}).get("blockers", []) or []),
        })
    if hard_review_flags:
        reasons.append({
            "reason_id": "domain_review_gate_blocked",
            "detail": "domain policy hard review flags must be resolved before Step3 scheduling",
            "review_flags": hard_review_flags,
        })
    elif review_required:
        reasons.append({
            "reason_id": "domain_review_required",
            "detail": "domain policy marks this candidate for human review before trusting downstream interpretation",
            "review_flags": review_flags,
        })
    if promoted:
        reasons.append({
            "reason_id": "ready_for_step3_simulation",
            "detail": "legal selected mapping on a bound full-workload architecture; final ranking still requires Step3+ evidence",
        })
    l4_required = bool(require_l4_proof or backend == "gem5_systemc")
    required_evidence = ["simulation_request.json", "simulation_result.json", "verdict.json", "phase_breakdown.csv"]
    if l4_required:
        required_evidence.extend(CODESIGN_L4_EVIDENCE_ARTIFACTS + ["gem5_l4_proof.json", "gem5.log"])
    return {
        "schema_version": "dse.step2.promotion_decision.v1",
        "candidate_id": selected_record.get("candidate_id"),
        "mapping_id": selected_record.get("mapping_id"),
        "architecture_id": architecture_artifact.get("architecture_id"),
        "backend": backend,
        "evidence_mode": evidence_mode,
        "promoted_for_simulation": promoted,
        "review_flags": review_flags,
        "review_required": review_required,
        "review_status": "blocked_by_review_gate" if hard_review_flags else ("review_required" if review_required else "not_required"),
        "domain_policy": _candidate_hint_domain_policy(candidate_hints),
        "trusted_final_claim": False,
        "low_fidelity_role": "candidate_generator_only",
        "low_fidelity_screening": {
            "required_for_step3": bool((low_fidelity_summary or {}).get("required_for_step3", True)),
            "passed": low_fidelity_passed,
            "status": (low_fidelity_summary or {}).get("status", "not_run" if low_fidelity_summary is None else "failed"),
            "require_l1": bool((low_fidelity_summary or {}).get("require_l1", True)),
            "require_l2": bool((low_fidelity_summary or {}).get("require_l2", True)),
            "artifact_refs": dict((low_fidelity_summary or {}).get("artifact_refs", STEP2_LOW_FIDELITY_ARTIFACT_KEYS)),
            "required_artifacts": list((low_fidelity_summary or {}).get("required_artifacts", STEP2_LOW_FIDELITY_ARTIFACTS)),
            "promotion_scores": dict((low_fidelity_summary or {}).get("promotion_scores", {})),
            "thresholds": dict((low_fidelity_summary or {}).get("thresholds", {})),
            "confidence": dict((low_fidelity_summary or {}).get("confidence", {})),
            "blockers": list((low_fidelity_summary or {}).get("blockers", []) or []),
            "low_fidelity_role": "candidate_generator_only",
            "trusted_final_claim": False,
        },
        "required_evidence": required_evidence,
        "required_coverage": list(required_coverage),
        "simulation_budget": {"requested_samples": simulation_budget, "selected_candidate_budget_cost": 1 if promoted else 0},
        "co_design": {
            "candidate_artifact": "codesign_candidate.json",
            "l4_required": l4_required,
            "l4_required_reason": l4_reason if l4_required else "L4 is optional for non-software-visible L3 timing evidence.",
            "l4_sampling_role": "claim_critical_or_calibration_sample" if l4_required else "optional_expensive_oracle_sample",
            "trusted_claim_after_step2": False,
            "blocked_if_l4_proof_missing": l4_required,
        },
        "reasons": reasons,
    }


def _mapping_summary_payload(
    *,
    run_id: str,
    design_point: DesignPoint,
    selected_record: Mapping[str, Any],
    promotion_decision: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": "dse.step2.mapping.v1",
        "mapping_id": design_point.config.get("mapping_id"),
        "mapping_policy": "workflow_seeded_beam_local_search_v1",
        "placements": dict(design_point.task_mapping),
        "selected_candidate_id": selected_record.get("candidate_id"),
        "promotion_decision": "promoted_for_simulation" if promotion_decision.get("promoted_for_simulation") else "candidate_only_or_blocked",
        "trusted_final_eligible": False,
        "trusted_final_claim": False,
        "notes": [
            "Step2 may promote candidates to Step3+ simulation, but it never creates final winners by itself.",
            "Low-fidelity screening and predicted-only records remain candidate-generation signals only.",
        ],
        "run_id": run_id,
    }


def _design_point_config(
    *,
    run_id: str,
    workload_package: WorkloadPackage,
    lowering: GraphLoweringResult,
    architecture_artifact: Mapping[str, Any],
    selected_record: Mapping[str, Any],
    backend: str,
    evidence_mode: str,
    scheduling_policy: str,
    precision_policy: Mapping[str, Any],
    fallback_policy: Mapping[str, Any],
    objective_directions: Mapping[str, str],
    random_seed: int,
    require_l4_proof: bool = False,
    low_fidelity_policy: Optional[Mapping[str, Any]] = None,
    candidate_hints: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    mapping_id = f"{run_id}_mapping"
    config = {
        "schema_version": "dse.step2.design_point_config.v1",
        "step": "step2_architecture_mapping",
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "source_graph_id": workload_package.graph.graph_id,
        "executable_graph_id": lowering.report.get("executable_graph_id"),
        "architecture_id": architecture_artifact.get("architecture_id"),
        "architecture_family": architecture_artifact.get("architecture_family"),
        "mapping_id": mapping_id,
        "selected_candidate_id": selected_record.get("candidate_id"),
        "data_placement": {
            "policy_id": "default_same_target_or_host_visible",
            "status": "explicit_default",
            "placements": dict(selected_record.get("mapping", {})),
        },
        "scheduling_policy": scheduling_policy,
        "precision_policy": dict(precision_policy),
        "fallback_policy": dict(fallback_policy),
        "simulation_config": {
            "backend": backend,
            "mode": "standalone_systemc" if backend == "systemc" else backend,
            "requires_high_fidelity_evidence": True,
            "requires_l4_software_visible_proof": bool(require_l4_proof or backend == "gem5_systemc"),
            "step3_request_builder": "dse_v2.backends.generic_systemc_bridge.GenericSystemCBackend._build_request",
        },
        "co_design": {
            "codesign_candidate": "codesign_candidate.json",
            "software_stack_config": "software_stack_config.json",
            "runtime_schedule": "runtime_schedule.json",
            "compiler_lowering": "compiler_lowering.json",
            "descriptor_protocol": "descriptor_protocol.json",
            "memory_policy": "memory_policy.json",
            "l4_required": bool(require_l4_proof or backend == "gem5_systemc"),
            "trusted_claim_after_step2": False,
        },
        "output_config": {
            "evidence_mode": evidence_mode,
            "required_mapping_artifacts": list(STEP2_REQUIRED_MAPPING_ARTIFACTS),
            "required_low_fidelity_artifacts": list(STEP2_LOW_FIDELITY_ARTIFACTS),
            "required_codesign_artifacts": list(CODESIGN_STEP2_ARTIFACTS),
        },
        "low_fidelity_policy": _normalize_low_fidelity_policy(low_fidelity_policy),
        "objective_directions": dict(objective_directions),
        "random_seed": random_seed,
        "workflow": workload_package.resolved_workflow(),
        "required_coverage": list(lowering.report.get("required_coverage", [])),
        "claim_boundary": workload_package.claim_boundary,
        "graph_lowering": {
            "artifact": "graph_lowering_report.json",
            "status": lowering.report.get("status"),
            "full_workload_eligible": lowering.report.get("full_workload_eligible", False),
            "source_to_executable_nodes": dict(lowering.report.get("source_to_executable_nodes", {}) or {}),
            "unsupported_constructs": list(lowering.report.get("unsupported_constructs", []) or []),
            "approximations": list(lowering.report.get("approximations", []) or []),
        },
        "replay_metadata": {
            "workload_package": "workload_package.json",
            "source_graph": "workload_graph.json",
            "executable_graph": "executable_graph.json",
            "architecture": "architecture.json",
            "mapping_selected_record": "mapping_selected_record.json",
            "mapping_legality_matrix": "mapping_legality_matrix.json",
            **STEP2_LOW_FIDELITY_ARTIFACT_KEYS,
            "no_hidden_python_state_required": True,
        },
    }
    hint_metadata = _candidate_hint_metadata(candidate_hints)
    if hint_metadata:
        config["domain_policy"] = {
            "hints_artifact": "domain_policy_hints.json",
            "domain_policy": hint_metadata.get("domain_policy", {}),
            "review_flags": list(hint_metadata.get("review_flags", []) or []),
            "review_required": bool(hint_metadata.get("review_required", False)),
            "review_status": hint_metadata.get("review_status", "not_required"),
            "claim_boundary": hint_metadata.get("claim_boundary", "candidate_only"),
            "trusted_final_claim": False,
        }
        config["replay_metadata"]["domain_policy_hints"] = "domain_policy_hints.json"
        data_hint = candidate_hints.get("data_placement") if isinstance(candidate_hints, Mapping) else None
        if isinstance(data_hint, Mapping):
            config["data_placement"].update({
                key: data_hint[key]
                for key in ("policy_id", "status", "placements", "preferred_locations", "phase_groups", "data_locality_intent")
                if key in data_hint
            })
            config["data_placement"].setdefault("trusted_final_claim", False)
            config["data_placement"].setdefault("claim_boundary", hint_metadata.get("claim_boundary", "candidate_only"))
    return config


def validate_step2_artifacts(artifacts: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate Step2 artifact references before Step3 promotion."""
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    executable_graph = artifacts.get("executable_graph") or artifacts.get("workload_graph", {})
    graph_nodes = set((executable_graph.get("nodes", {}) or {}).keys()) if isinstance(executable_graph, Mapping) else set()
    architecture = artifacts.get("architecture", {}) if isinstance(artifacts.get("architecture", {}), Mapping) else {}
    system_arch = artifacts.get("system_architecture")
    if system_arch is None and isinstance(artifacts.get("design_point", {}), Mapping):
        system_arch = (artifacts.get("design_point", {}) or {}).get("system_architecture", {})
    resource_ids = {"host"}
    if isinstance(system_arch, Mapping):
        resource_ids.update(str(accel.get("accel_id")) for accel in system_arch.get("accelerators", []) or [] if accel.get("accel_id"))
    else:
        instance = architecture.get("architecture_instance", {}) if isinstance(architecture, Mapping) else {}
        resource_ids.update(str(component.get("component_id")) for component in instance.get("components", []) or [] if component.get("component_id"))

    selected = artifacts.get("selected_record") or artifacts.get("mapping_selected_record") or {}
    if isinstance(selected, Mapping):
        mapping = selected.get("mapping", {}) or {}
        for node_id, target in mapping.items():
            if str(node_id) not in graph_nodes:
                errors.append({"field": "mapping", "message": "selected mapping references unknown node", "node_id": str(node_id)})
            if str(target) not in resource_ids:
                errors.append({"field": "mapping", "message": "selected mapping references unknown target", "target": str(target)})
        if selected.get("trusted_final_eligible"):
            warnings.append({"field": "mapping_selected_record.trusted_final_eligible", "message": "Step2 selected records should not become trusted before Step3+ evidence"})
        if selected.get("violations"):
            errors.append({"field": "mapping_selected_record.violations", "message": "selected mapping has legality violations", "violations": list(selected.get("violations", []) or [])})
    else:
        errors.append({"field": "mapping_selected_record", "message": "selected mapping record missing or invalid"})

    promotion = artifacts.get("promotion_decision", {}) if isinstance(artifacts.get("promotion_decision", {}), Mapping) else {}
    if promotion.get("trusted_final_claim"):
        errors.append({"field": "promotion_decision.trusted_final_claim", "message": "Step2 cannot claim trusted final winners"})
    if promotion.get("promoted_for_simulation") and not architecture.get("trusted_final_eligible", False):
        errors.append({"field": "promotion_decision.promoted_for_simulation", "message": "promotion requires architecture trusted-final eligibility"})
    low_summary = artifacts.get("low_fidelity_summary") or artifacts.get("low_fidelity_screening_summary") or {}
    if isinstance(low_summary, Mapping):
        if low_summary.get("trusted_final_claim"):
            errors.append({"field": "low_fidelity_summary.trusted_final_claim", "message": "L1/L2 screening cannot claim trusted final winners"})
        if low_summary and low_summary.get("low_fidelity_role") != "candidate_generator_only":
            errors.append({"field": "low_fidelity_summary.low_fidelity_role", "message": "L1/L2 screening must remain candidate-generator only"})
    else:
        low_summary = {}
    if promotion.get("promoted_for_simulation"):
        if not low_summary:
            errors.append({"field": "low_fidelity_summary", "message": "promoted Step2 handoff requires low_fidelity_screening_summary.json"})
        elif not low_summary.get("passed", False):
            errors.append({
                "field": "low_fidelity_summary.passed",
                "message": "promoted Step2 handoff requires passed low-fidelity screening",
                "blockers": list(low_summary.get("blockers", []) or []),
            })
        for key, filename in STEP2_LOW_FIDELITY_ARTIFACT_KEYS.items():
            if artifacts.get(key) is None:
                errors.append({"field": key, "message": f"promoted Step2 handoff requires {filename}"})
    for key in STEP2_LOW_FIDELITY_ARTIFACT_KEYS:
        payload = artifacts.get(key)
        if not isinstance(payload, Mapping):
            continue
        if payload.get("trusted_final_claim"):
            errors.append({"field": f"{key}.trusted_final_claim", "message": "L1/L2 artifacts cannot claim trusted final winners"})
        if payload.get("low_fidelity_role") != "candidate_generator_only":
            errors.append({"field": f"{key}.low_fidelity_role", "message": "L1/L2 artifacts must remain candidate-generator only"})

    feedback = artifacts.get("feedback_state", {}) if isinstance(artifacts.get("feedback_state", {}), Mapping) else {}
    ranking_update = feedback.get("ranking_update", {}) if isinstance(feedback.get("ranking_update", {}), Mapping) else {}
    if ranking_update and ranking_update.get("low_fidelity_role") != "candidate_generator_only":
        errors.append({"field": "feedback_state.ranking_update.low_fidelity_role", "message": "low-fidelity screening must remain candidate-generator only"})

    if artifacts.get("codesign_candidate") is not None:
        codesign_validation = validate_codesign_artifacts({
            "codesign_candidate": artifacts.get("codesign_candidate", {}),
            "software_stack_config": artifacts.get("software_stack_config", {}),
            "compiler_lowering": artifacts.get("compiler_lowering", {}),
            "runtime_schedule": artifacts.get("runtime_schedule", {}),
            "descriptor_protocol": artifacts.get("descriptor_protocol", {}),
            "memory_policy": artifacts.get("memory_policy", {}),
        })
        for error in codesign_validation.get("errors", []) or []:
            errors.append({"field": f"codesign.{error.get('field')}", "message": error.get("message", "co-design artifact validation failed")})
        warnings.extend(
            {"field": f"codesign.{warning.get('field')}", "message": warning.get("message", "co-design artifact validation warning")}
            for warning in codesign_validation.get("warnings", []) or []
        )

    return {
        "schema_version": "dse.step2.artifact_validation.v1",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_artifacts": sorted(str(key) for key in artifacts.keys()),
    }


def run_step2_architecture_mapping_workflow(
    workload_package: WorkloadPackage,
    *,
    catalog: Optional[ArchitectureCatalog] = None,
    architecture_id: str = "balanced-generic-systemc-v0",
    backend: str = "systemc",
    evidence_mode: str = "summary",
    output_dir: Optional[Path] = None,
    scheduling_policy: str = "static_timing_level",
    precision_policy: Optional[Mapping[str, Any]] = None,
    fallback_policy: Optional[Mapping[str, Any]] = None,
    objective_directions: Optional[Mapping[str, str]] = None,
    random_seed: int = 0,
    beam_width: int = 3,
    require_l4_proof: bool = False,
    l4_reason: str = "software-visible descriptor/request/completion proof requested for co-design claim",
    low_fidelity_policy: Optional[Mapping[str, Any]] = None,
    candidate_hints: Optional[Mapping[str, Any]] = None,
) -> Step2WorkflowResult:
    """Run Step2 and optionally persist all architecture/mapping artifacts."""
    catalog = catalog or seed_generic_dse_architecture_catalog()
    precision_policy = dict(precision_policy or {"default": "FP64", "unavailable_policy": "record_explicit_default"})
    fallback_policy = dict(fallback_policy or {"unsupported_ops": "host_fallback_visible", "final_claim_if_fallback": "requires_step3_evidence"})
    objective_directions = dict(objective_directions or {"latency_ms": "minimize", "energy_j": "minimize", "power_w": "minimize"})
    candidate_hints_payload = _json_safe(candidate_hints) if isinstance(candidate_hints, Mapping) and candidate_hints else None

    validation = workload_package.validate()
    lowering = lower_compute_graph(workload_package.graph, workload_package)
    if not validation.get("valid", False):
        return _blocked_result(
            status="blocked_invalid_workload_package",
            reasons=[_status_reason("invalid_workload_package", "WorkloadPackage validation failed", validation=validation)],
            workload_package=workload_package,
            lowering=lowering,
            output_dir=output_dir,
            catalog=catalog,
        )
    if lowering.report.get("status") == "unsupported" or lowering.executable_graph is None:
        return _blocked_result(
            status="blocked_unsupported_graph_lowering",
            reasons=[_status_reason(
                "unsupported_graph_lowering",
                "graph_lowering_report is unsupported or lacks executable_graph",
                lowering_status=lowering.report.get("status"),
                unsupported_constructs=lowering.report.get("unsupported_constructs", []),
                errors=lowering.report.get("errors", []),
            )],
            workload_package=workload_package,
            lowering=lowering,
            output_dir=output_dir,
            catalog=catalog,
        )
    if architecture_id not in catalog.instances:
        return _blocked_result(
            status="blocked_unknown_architecture",
            reasons=[_status_reason("unknown_architecture", f"architecture_id {architecture_id!r} is not present in catalog")],
            workload_package=workload_package,
            lowering=lowering,
            output_dir=output_dir,
            catalog=catalog,
        )

    instance = catalog.instances[architecture_id]
    system_arch = architecture_instance_to_system_architecture(instance)
    architecture_artifact = build_architecture_artifact(
        catalog,
        instance,
        workload_package=workload_package,
        lowering=lowering,
        backend=backend,
    )
    executable_graph = lowering.executable_graph
    mapping_artifacts = run_mapping_search(
        executable_graph,
        system_arch,
        selected_mapping=None,
        trusted_sample=False,
        beam_width=beam_width,
        candidate_hints=candidate_hints_payload,
    )
    selected_record = dict(mapping_artifacts["selected_record"])
    _attach_candidate_hint_metadata(selected_record, candidate_hints_payload)
    selected_mapping = {str(k): str(v) for k, v in (selected_record.get("mapping", {}) or {}).items()}
    selected_violations = mapping_violations(selected_mapping, executable_graph, mapping_artifacts["legality_matrix"])
    if selected_violations:
        selected_record["violations"] = selected_violations
        selected_record["state"] = "rejected"
        selected_record["trusted_final_eligible"] = False
    mapping_artifacts["selected_record"] = selected_record

    run_id = f"{workload_package.workload_id}__{instance.architecture_id}__step2"
    design_config = _design_point_config(
        run_id=run_id,
        workload_package=workload_package,
        lowering=lowering,
        architecture_artifact=architecture_artifact,
        selected_record=selected_record,
        backend=backend,
        evidence_mode=evidence_mode,
        scheduling_policy=scheduling_policy,
        precision_policy=precision_policy,
        fallback_policy=fallback_policy,
        objective_directions=objective_directions,
        random_seed=random_seed,
        require_l4_proof=require_l4_proof,
        low_fidelity_policy=low_fidelity_policy,
        candidate_hints=candidate_hints_payload,
    )
    design_point = DesignPoint(
        design_point_id=run_id,
        system_architecture=system_arch,
        task_mapping=selected_mapping,
        scheduling_policy=scheduling_policy,
        config=design_config,
    )
    low_fidelity_artifacts = run_low_fidelity_screening(
        design_point,
        executable_graph,
        selected_record=selected_record,
        low_fidelity_policy=low_fidelity_policy,
    )
    design_point.config["low_fidelity_screening"] = {
        "summary_artifact": "low_fidelity_screening_summary.json",
        "passed": bool(low_fidelity_artifacts["low_fidelity_summary"].get("passed", False)),
        "required_for_step3": bool(low_fidelity_artifacts["low_fidelity_summary"].get("required_for_step3", True)),
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
        "artifact_refs": dict(STEP2_LOW_FIDELITY_ARTIFACT_KEYS),
    }
    promotion_decision = _promotion_decision(
        architecture_artifact=architecture_artifact,
        selected_record=selected_record,
        backend=backend,
        evidence_mode=evidence_mode,
        required_coverage=list(lowering.report.get("required_coverage", [])),
        simulation_budget=max(1, beam_width),
        require_l4_proof=require_l4_proof,
        l4_reason=l4_reason,
        low_fidelity_summary=low_fidelity_artifacts["low_fidelity_summary"],
        candidate_hints=candidate_hints_payload,
    )
    mapping_payload = _mapping_summary_payload(
        run_id=run_id,
        design_point=design_point,
        selected_record=selected_record,
        promotion_decision=promotion_decision,
    )
    codesign_artifacts = build_default_codesign_artifacts(
        design_point=design_point,
        workload_package=workload_package,
        executable_graph=executable_graph,
        architecture_artifact=architecture_artifact,
        selected_record=selected_record,
        promotion_decision=promotion_decision,
        backend=backend,
        evidence_mode=evidence_mode,
        l4_required=require_l4_proof or backend == "gem5_systemc",
        l4_reason=l4_reason,
        candidate_hints=candidate_hints_payload,
    )
    codesign_validation = validate_codesign_artifacts(codesign_artifacts)

    status_reasons = list(architecture_artifact.get("candidate_only_reasons", []) or [])
    if selected_violations:
        status_reasons.append({"reason_id": "illegal_selected_mapping", "violations": selected_violations})
    if not low_fidelity_artifacts["low_fidelity_summary"].get("passed", False):
        status_reasons.extend(list(low_fidelity_artifacts["low_fidelity_summary"].get("blockers", []) or []))
    if promotion_decision.get("promoted_for_simulation"):
        status = "ready_for_step3_simulation"
    elif workload_package.claim_boundary in DIAGNOSTIC_CLAIM_BOUNDARIES:
        status = "diagnostic_only_candidate"
    else:
        status = "candidate_only_or_blocked"
    trusted_final_eligible = bool(promotion_decision.get("promoted_for_simulation", False))

    catalog_payload = catalog.to_dict()
    catalog_payload["summary"] = catalog_summary(catalog)
    artifacts: Dict[str, Any] = {
        "step2_status": {
            "schema_version": "dse.step2.status.v1",
            "status": status,
            "trusted_final_eligible": trusted_final_eligible,
            "trusted_final_claim": False,
            "workload_id": workload_package.workload_id,
            "workload_family": workload_package.workload_family,
            "source_graph_id": workload_package.graph.graph_id,
            "executable_graph_id": executable_graph.graph_id,
            "architecture_id": instance.architecture_id,
            "design_point_id": design_point.design_point_id,
            "mapping_id": design_config["mapping_id"],
            "selected_candidate_id": selected_record.get("candidate_id"),
            "backend": backend,
            "required_coverage": list(lowering.report.get("required_coverage", [])),
            "low_fidelity_screening": {
                "summary_artifact": "low_fidelity_screening_summary.json",
                "passed": bool(low_fidelity_artifacts["low_fidelity_summary"].get("passed", False)),
                "required_for_step3": bool(low_fidelity_artifacts["low_fidelity_summary"].get("required_for_step3", True)),
                "low_fidelity_role": "candidate_generator_only",
                "trusted_final_claim": False,
            },
            "domain_policy": _candidate_hint_domain_policy(candidate_hints_payload),
            "review_flags": _candidate_hint_review_flags(candidate_hints_payload),
            "review_required": bool((promotion_decision or {}).get("review_required", False)),
            "review_status": (promotion_decision or {}).get("review_status", "not_required"),
            "reasons": status_reasons,
        },
        "architecture_catalog": catalog_payload,
        "architecture": architecture_artifact,
        "design_point": design_point.to_dict(),
        "workload_package": workload_package.to_dict(),
        "workload_graph": workload_package.graph.to_dict(),
        "graph_lowering_report": lowering.report,
        "executable_graph": executable_graph.to_dict(),
        "mapping": mapping_payload,
        "promotion_decision": promotion_decision,
        "l1_evaluation_result": low_fidelity_artifacts["l1_evaluation_result"],
        "l1_promotion_decision": low_fidelity_artifacts["l1_promotion_decision"],
        "l2_evaluation_result": low_fidelity_artifacts["l2_evaluation_result"],
        "l2_promotion_decision": low_fidelity_artifacts["l2_promotion_decision"],
        "low_fidelity_summary": low_fidelity_artifacts["low_fidelity_summary"],
        "legality_matrix": mapping_artifacts["legality_matrix"],
        "seed_set": mapping_artifacts["seed_set"],
        "candidate_records": mapping_artifacts["candidate_records"],
        "selected_record": mapping_artifacts["selected_record"],
        "simulation_samples": mapping_artifacts["simulation_samples"],
        "feedback_state": mapping_artifacts["feedback_state"],
        "convergence_status": mapping_artifacts["convergence_status"],
        "codesign_candidate": codesign_artifacts["codesign_candidate"],
        "software_stack_config": codesign_artifacts["software_stack_config"],
        "compiler_lowering": codesign_artifacts["compiler_lowering"],
        "runtime_schedule": codesign_artifacts["runtime_schedule"],
        "descriptor_protocol": codesign_artifacts["descriptor_protocol"],
        "memory_policy": codesign_artifacts["memory_policy"],
        "codesign_artifact_validation": codesign_validation,
    }
    if candidate_hints_payload:
        artifacts["domain_policy_hints"] = candidate_hints_payload
    artifacts["step2_artifact_validation"] = validate_step2_artifacts({
        **artifacts,
        "system_architecture": design_point.system_architecture.to_dict(),
    })
    artifacts["step2_status"]["artifact_validation"] = artifacts["step2_artifact_validation"]

    artifact_paths: Dict[str, str] = {}
    if output_dir is not None:
        output = Path(output_dir)
        name_map = {
            "step2_status": "step2_status.json",
            "architecture_catalog": "architecture_catalog.json",
            "architecture": "architecture.json",
            "design_point": "design_point.json",
            "workload_package": "workload_package.json",
            "workload_graph": "workload_graph.json",
            "graph_lowering_report": "graph_lowering_report.json",
            "executable_graph": "executable_graph.json",
            "mapping": "mapping.json",
            "promotion_decision": "mapping_promotion_decision.json",
            "l1_evaluation_result": "l1_evaluation_result.json",
            "l1_promotion_decision": "l1_promotion_decision.json",
            "l2_evaluation_result": "l2_evaluation_result.json",
            "l2_promotion_decision": "l2_promotion_decision.json",
            "low_fidelity_summary": "low_fidelity_screening_summary.json",
            "legality_matrix": "mapping_legality_matrix.json",
            "seed_set": "mapping_seed_set.json",
            "candidate_records": "mapping_candidate_records.json",
            "selected_record": "mapping_selected_record.json",
            "simulation_samples": "mapping_simulation_samples.json",
            "feedback_state": "mapping_feedback_state.json",
            "convergence_status": "convergence_status.json",
            "step2_artifact_validation": "step2_artifact_validation.json",
            "codesign_candidate": "codesign_candidate.json",
            "software_stack_config": "software_stack_config.json",
            "compiler_lowering": "compiler_lowering.json",
            "runtime_schedule": "runtime_schedule.json",
            "descriptor_protocol": "descriptor_protocol.json",
            "memory_policy": "memory_policy.json",
            "codesign_artifact_validation": "codesign_artifact_validation.json",
        }
        if "domain_policy_hints" in artifacts:
            name_map["domain_policy_hints"] = "domain_policy_hints.json"
        for key, filename in name_map.items():
            _write_json(output / filename, artifacts[key])
            artifact_paths[key] = filename

    return Step2WorkflowResult(
        status=status,
        trusted_final_eligible=trusted_final_eligible,
        workload_package=workload_package,
        source_graph=workload_package.graph,
        lowering=lowering,
        executable_graph=executable_graph,
        architecture_instance=instance,
        system_architecture=system_arch,
        design_point=design_point,
        artifacts=artifacts,
        artifact_paths=artifact_paths,
        reasons=status_reasons,
    )


def run_step2_architecture_mapping_workflow_from_step1(
    step1_dir: Path,
    **kwargs: Any,
) -> Step2WorkflowResult:
    """Load a persisted Step1 handoff from disk, then run Step2.

    This is the disk-boundary entry point for the control-flow contract: Step2
    reconstructs the workload from `workload_package.json` instead of receiving
    a live importer/package object from Step1.
    """

    workload_package = load_step1_workload_package(step1_dir)
    return run_step2_architecture_mapping_workflow(workload_package, **kwargs)


def _architecture_screening_record(result: Step2WorkflowResult, run_dir: Path) -> Dict[str, Any]:
    architecture = result.artifacts.get("architecture", {}) if isinstance(result.artifacts.get("architecture"), Mapping) else {}
    promotion = result.artifacts.get("promotion_decision", {}) if isinstance(result.artifacts.get("promotion_decision"), Mapping) else {}
    selected = result.artifacts.get("selected_record", {}) if isinstance(result.artifacts.get("selected_record"), Mapping) else {}
    validation = result.artifacts.get("step2_artifact_validation", {}) if isinstance(result.artifacts.get("step2_artifact_validation"), Mapping) else {}
    low_summary = result.artifacts.get("low_fidelity_summary", {}) if isinstance(result.artifacts.get("low_fidelity_summary"), Mapping) else {}
    architecture_id = (
        result.architecture_instance.architecture_id
        if result.architecture_instance is not None
        else str(architecture.get("architecture_id", ""))
    )
    return {
        "schema_version": "dse.step2.architecture_screening_record.v1",
        "architecture_id": architecture_id,
        "architecture_family": architecture.get("architecture_family"),
        "step2_status": result.status,
        "run_dir": str(run_dir),
        "design_point_id": result.design_point.design_point_id if result.design_point else None,
        "mapping_id": promotion.get("mapping_id") or (result.design_point.config.get("mapping_id") if result.design_point else None),
        "selected_candidate_id": selected.get("candidate_id"),
        "promoted_for_simulation": bool(promotion.get("promoted_for_simulation", False)),
        "low_fidelity_screening_passed": bool(low_summary.get("passed", False)),
        "trusted_final_claim": False,
        "trusted_final_eligible_before_step3": False,
        "artifact_validation_valid": bool(validation.get("valid", False)),
        "candidate_only_reasons": list(architecture.get("candidate_only_reasons", []) or result.reasons),
        "reasons": list(result.reasons),
    }


def run_step2_architecture_screening_workflow(
    workload_package: WorkloadPackage,
    *,
    catalog: Optional[ArchitectureCatalog] = None,
    architecture_ids: Optional[Sequence[str]] = None,
    backend: str = "systemc",
    evidence_mode: str = "summary",
    output_dir: Optional[Path] = None,
    scheduling_policy: str = "static_timing_level",
    precision_policy: Optional[Mapping[str, Any]] = None,
    fallback_policy: Optional[Mapping[str, Any]] = None,
    objective_directions: Optional[Mapping[str, str]] = None,
    random_seed: int = 0,
    beam_width: int = 3,
    low_fidelity_policy: Optional[Mapping[str, Any]] = None,
    candidate_hints: Optional[Mapping[str, Any]] = None,
) -> Step2WorkflowResult:
    """Run Step2 architecture screening over multiple catalog instances.

    This orchestration layer deliberately reuses the single-architecture Step2
    workflow as the per-candidate primitive, so each promoted architecture keeps
    the same persisted handoff shape expected by Step3.
    """
    catalog = catalog or seed_generic_dse_architecture_catalog()
    selected_architecture_ids = list(architecture_ids) if architecture_ids is not None else sorted(catalog.instances)
    root_dir = Path(output_dir) if output_dir is not None else None
    architecture_root = root_dir / "architectures" if root_dir is not None else None

    child_results: List[Step2WorkflowResult] = []
    records: List[Dict[str, Any]] = []
    for architecture_id in selected_architecture_ids:
        child_dir = architecture_root / architecture_id if architecture_root is not None else None
        child = run_step2_architecture_mapping_workflow(
            workload_package,
            catalog=catalog,
            architecture_id=architecture_id,
            backend=backend,
            evidence_mode=evidence_mode,
            output_dir=child_dir,
            scheduling_policy=scheduling_policy,
            precision_policy=precision_policy,
            fallback_policy=fallback_policy,
            objective_directions=objective_directions,
            random_seed=random_seed,
            beam_width=beam_width,
            low_fidelity_policy=low_fidelity_policy,
            candidate_hints=candidate_hints,
        )
        child_results.append(child)
        records.append(_architecture_screening_record(child, child_dir or Path(architecture_id)))

    promoted_records = [record for record in records if record["promoted_for_simulation"]]
    status = "architecture_screening_completed" if records else "architecture_screening_empty"
    aggregate = {
        "schema_version": "dse.step2.architecture_screening_records.v1",
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "source_graph_id": workload_package.graph.graph_id,
        "status": status,
        "architecture_count": len(records),
        "promoted_count": len(promoted_records),
        "trusted_final_claim": False,
        "low_fidelity_role": "candidate_generator_only",
        "records": records,
        "notes": [
            "Step2 architecture screening only builds candidate handoffs; final ranking requires Step3 evidence.",
            "Each per-architecture run directory preserves the single-architecture Step2 artifact contract consumed by Step3.",
        ],
    }
    artifacts: Dict[str, Any] = {"architecture_screening_records": aggregate}
    artifact_paths: Dict[str, str] = {}
    if root_dir is not None:
        _write_json(root_dir / "architecture_screening_records.json", aggregate)
        artifact_paths["architecture_screening_records"] = "architecture_screening_records.json"

    representative = child_results[0] if child_results else None
    return Step2WorkflowResult(
        status=status,
        trusted_final_eligible=False,
        workload_package=workload_package,
        source_graph=workload_package.graph,
        lowering=representative.lowering if representative else lower_compute_graph(workload_package.graph, workload_package),
        executable_graph=representative.executable_graph if representative else None,
        architecture_instance=None,
        system_architecture=None,
        design_point=None,
        artifacts=artifacts,
        artifact_paths=artifact_paths,
        reasons=[] if records else [_status_reason("no_architectures_screened", "architecture_ids was empty")],
    )
