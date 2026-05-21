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
import hashlib
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
from dse_v2.core.workload.step1_workflow import load_step1_handoff
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
from dse_v2.mapping.search_policy import (
    HIERARCHICAL_FUNNEL_STAGES,
    HierarchicalFunnelSearchPolicy,
    SearchProblem,
)
from dse_v2.mapping.domain_policy import (
    Step2CandidateHints,
    Step2DomainPolicyRegistry,
    Step2PolicyInput,
    default_step2_domain_policy_registry,
)
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
    "architecture_search_space.json",
    "search_checkpoint.json",
    "top_k_candidate_queue.json",
    "architecture_candidate_generation_report.json",
    "architecture_screening_report.json",
    "trial_state_ledger.json",
    "mapping_candidates.jsonl",
    "screening_results.jsonl",
    "promotion_decisions.jsonl",
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


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_json_safe(record), sort_keys=True) for record in records]
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


def _payload_sha256(payload: Any) -> str:
    data = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


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


def _step3_searchability(
    *,
    selected_binding: Mapping[str, Any],
    catalog_has_errors: bool,
    instance: ArchitectureInstance,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Return whether Step3 can produce a timing sample without making final claims."""

    blockers: List[Dict[str, Any]] = []
    if catalog_has_errors:
        blockers.append({
            "reason_id": "catalog_validation_error",
            "detail": "catalog validation errors block replayable Step3 timing",
        })
    if not instance.components:
        blockers.append({
            "reason_id": "no_concrete_components",
            "detail": "architecture has no concrete component set to translate into a timing request",
        })
    if not selected_binding:
        blockers.append({
            "reason_id": "missing_step3_binding",
            "detail": "selected backend binding is absent from the architecture instance",
        })
    elif not selected_binding.get("trusted_eligible", False):
        blockers.append({
            "reason_id": "untrusted_step3_binding",
            "backend": selected_binding.get("backend"),
            "detail": selected_binding.get("unavailable_reason") or "selected backend binding is not implemented for timing samples",
        })
    return not blockers, blockers



def _step2_eligibility_fields(
    *,
    step3_searchable: bool,
    step3_blockers: Sequence[Mapping[str, Any]] | Sequence[Any],
    promoted_for_simulation: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return precise Step2/Step3 eligibility names for candidate artifacts.

    `step3_searchable` is retained only as legacy compatibility while the
    restructure migrates to `step2_screenable`, `step3_evaluable`,
    `simulation_eligible`, and `simulation_blockers`.
    """
    blockers = [dict(item) if isinstance(item, Mapping) else item for item in list(step3_blockers or [])]
    step2_screenable = bool(step3_searchable)
    step3_evaluable = bool(step3_searchable)
    if promoted_for_simulation is None:
        simulation_eligible = step3_evaluable
    else:
        simulation_eligible = bool(promoted_for_simulation and step3_evaluable)
    simulation_blockers = list(blockers)
    if promoted_for_simulation is not None and not promoted_for_simulation:
        simulation_blockers.append({
            "reason_id": "not_promoted_for_simulation",
            "detail": "candidate was not promoted by Step2 policy",
        })
    if not step3_evaluable and not simulation_blockers:
        simulation_blockers.append({
            "reason_id": "not_step3_evaluable",
            "detail": "candidate failed Step2 screenability or backend eligibility",
        })
    return {
        "step2_screenable": step2_screenable,
        "step3_evaluable": step3_evaluable,
        "simulation_eligible": simulation_eligible,
        "simulation_blockers": [] if simulation_eligible else simulation_blockers,
    }


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
    step3_searchable, step3_blockers = _step3_searchability(
        selected_binding=selected_binding,
        catalog_has_errors=catalog_has_errors,
        instance=instance,
    )
    eligibility_fields = _step2_eligibility_fields(
        step3_searchable=step3_searchable,
        step3_blockers=step3_blockers,
    )
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
            "step3_searchable": step3_searchable,
            "step3_search_blockers": step3_blockers,
            **eligibility_fields,
            "full_workload_eligible": full_workload_eligible,
            "diagnostic_boundary": diagnostic_boundary,
        },
        "status": ArchitectureStatus.TRUSTED_FINAL_ELIGIBLE if trusted_final_eligible else ArchitectureStatus.CANDIDATE_ONLY,
        "trusted_final_eligible": trusted_final_eligible,
        "step3_searchable": step3_searchable,
        "step3_search_blockers": step3_blockers,
        **eligibility_fields,
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
    if op_type in {"sparse_matmul", "spmm"}:
        return 0.70 if component_type_id in {"fpga_fabric", "gpu_sm"} else 0.35
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
    source_graph: Optional[ComputeGraph] = None,
    architecture_instance: Optional[ArchitectureInstance] = None,
    architecture_artifact: Optional[Mapping[str, Any]] = None,
) -> Step2WorkflowResult:
    source_graph = source_graph or workload_package.graph
    artifacts: Dict[str, Any] = {
        "step2_status": {
            "schema_version": "dse.step2.status.v1",
            "status": status,
            "trusted_final_eligible": False,
            "workload_id": workload_package.workload_id,
            "workload_family": workload_package.workload_family,
            "source_graph_id": source_graph.graph_id,
            "executable_graph_id": lowering.report.get("executable_graph_id"),
            "reasons": reasons,
        },
        "workload_package": workload_package.to_dict(),
        "workload_graph": source_graph.to_dict(),
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
        source_graph=source_graph,
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
            for annotation in annotations.values():
                if not isinstance(annotation, Mapping):
                    continue
                phase_groups = annotation.get("phase_groups")
                if isinstance(phase_groups, list):
                    break
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
    architecture_searchable = bool(architecture_artifact.get("step3_searchable", architecture_trusted))
    full_workload_eligible = bool((architecture_artifact.get("validation", {}) or {}).get("full_workload_eligible", False))
    diagnostic_boundary = bool((architecture_artifact.get("validation", {}) or {}).get("diagnostic_boundary", False))
    low_fidelity_passed = True if low_fidelity_summary is None else bool(low_fidelity_summary.get("passed", False))
    review_flags = _candidate_hint_review_flags(candidate_hints)
    hard_review_flags = _hard_review_flags(candidate_hints, review_flags)
    review_required = bool((candidate_hints or {}).get("review_required", False) or review_flags) if isinstance(candidate_hints, Mapping) else False
    base_promoted = selected_legal and architecture_searchable and full_workload_eligible and not diagnostic_boundary and low_fidelity_passed
    promoted = base_promoted and not hard_review_flags
    reasons: List[Dict[str, Any]] = []
    if not selected_legal:
        reasons.append({"reason_id": "illegal_selected_mapping", "violations": list(selected_record.get("violations", []) or [])})
    if not architecture_searchable:
        reasons.extend(list(architecture_artifact.get("step3_search_blockers", []) or []))
    if architecture_searchable and not architecture_trusted:
        reasons.append({
            "reason_id": "architecture_searchable_but_not_final_trusted",
            "detail": "implemented timing binding permits Step3 search, but final trust remains gated by Step3/Step4 evidence and catalog status",
            "candidate_only_reasons": list(architecture_artifact.get("candidate_only_reasons", []) or []),
        })
    if not full_workload_eligible:
        reasons.append({
            "reason_id": "workload_not_full_eligible",
            "detail": "Step3 search is blocked because Step1 did not produce a full-workload eligible executable graph",
        })
    if diagnostic_boundary:
        reasons.append({
            "reason_id": "diagnostic_claim_boundary",
            "detail": "diagnostic/smoke/reduced claim boundaries do not enter Step3 scheduling",
        })
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
        "step3_searchable": architecture_searchable,
        "trusted_final_eligible_before_step3": architecture_trusted,
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


def _review_flag_payload(item: Any, *, source: str) -> Optional[Dict[str, Any]]:
    """Normalize future policy review flags without importing domain policy code."""
    if isinstance(item, str):
        flag_id = item
        payload: Dict[str, Any] = {"flag_id": flag_id}
    elif isinstance(item, Mapping):
        flag_id = str(item.get("flag_id") or item.get("reason_id") or item.get("id") or item.get("flag") or "")
        if not flag_id:
            return None
        payload = {str(key): _json_safe(value) for key, value in item.items()}
        payload["flag_id"] = flag_id
    else:
        return None

    severity = str(payload.get("severity") or payload.get("level") or "")
    if not severity:
        if flag_id in HARD_DOMAIN_REVIEW_FLAGS:
            severity = "hard"
        elif flag_id in SOFT_DOMAIN_REVIEW_FLAGS:
            severity = "soft"
        else:
            severity = "review"
    payload["severity"] = severity
    payload.setdefault("source", source)
    return payload


def _collect_review_flags(*payloads: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Collect review flags from generic artifacts while preserving domain-neutral core contracts."""
    collected: Dict[str, Dict[str, Any]] = {}
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        for key in ("review_flags", "hard_block_flags", "hard_review_flags", "review_required_flags"):
            raw = payload.get(key, [])
            if isinstance(raw, Mapping):
                raw_items: Iterable[Any] = raw.values()
            elif isinstance(raw, (str, bytes)):
                raw_items = [str(raw)]
            elif isinstance(raw, Iterable):
                raw_items = raw
            else:
                raw_items = []
            for item in raw_items:
                flag = _review_flag_payload(item, source=key)
                if flag is not None:
                    collected.setdefault(str(flag["flag_id"]), flag)

        annotations = payload.get("annotations", {})
        if isinstance(annotations, Mapping):
            domain_review = annotations.get("review_flags", [])
            if isinstance(domain_review, Iterable) and not isinstance(domain_review, (str, bytes, Mapping)):
                for item in domain_review:
                    flag = _review_flag_payload(item, source="annotations.review_flags")
                    if flag is not None:
                        collected.setdefault(str(flag["flag_id"]), flag)
    return list(collected.values())


def _reason_id_set(*reason_lists: Iterable[Mapping[str, Any]]) -> set[str]:
    reason_ids: set[str] = set()
    for reasons in reason_lists:
        for reason in reasons or []:
            if isinstance(reason, Mapping) and reason.get("reason_id"):
                reason_ids.add(str(reason["reason_id"]))
    return reason_ids


def _review_state(
    *,
    promotion_decision: Mapping[str, Any],
    selected_record: Mapping[str, Any],
    architecture_artifact: Mapping[str, Any],
) -> Tuple[List[Dict[str, Any]], bool, bool]:
    review_flags = _collect_review_flags(promotion_decision, selected_record, architecture_artifact)
    flag_ids = {str(flag.get("flag_id")) for flag in review_flags}
    hard_blocked = bool(flag_ids & HARD_DOMAIN_REVIEW_FLAGS) or bool(promotion_decision.get("hard_blocked", False))
    review_required = (
        hard_blocked
        or bool(flag_ids)
        or bool(promotion_decision.get("review_required", False))
        or bool(selected_record.get("review_required", False))
        or bool(architecture_artifact.get("review_required", False))
    )
    return review_flags, review_required, hard_blocked


def _priority_score(selected_record: Mapping[str, Any], promoted: bool) -> float:
    screening = selected_record.get("screening", {}) if isinstance(selected_record.get("screening", {}), Mapping) else {}
    score = _finite_float(screening.get("promotion_priority"), 0.0)
    return max(score, 1.0 if promoted else 0.0)


def _queue_priority_reasons(
    *,
    selected_record: Mapping[str, Any],
    promotion_decision: Mapping[str, Any],
    review_required: bool,
    hard_blocked: bool,
) -> List[Dict[str, Any]]:
    reasons: List[Dict[str, Any]] = []
    selection_reason = selected_record.get("selection_reason")
    if selection_reason:
        reasons.append({"reason_id": str(selection_reason), "source": "mapping_selected_record"})
    for reason in promotion_decision.get("reasons", []) or []:
        if isinstance(reason, Mapping) and reason.get("reason_id"):
            reasons.append({"reason_id": str(reason["reason_id"]), "source": "mapping_promotion_decision"})
    if hard_blocked:
        reasons.append({"reason_id": "domain_review_gate_blocked", "source": "review_flags"})
    elif review_required:
        reasons.append({"reason_id": "domain_review_required", "source": "review_flags"})
    if not reasons:
        reasons.append({"reason_id": "selected_entry_replayable", "source": "step3_queue"})
    return reasons


def _queue_blocked_reasons(
    *,
    queue_state: str,
    promotion_decision: Mapping[str, Any],
    selected_record: Mapping[str, Any],
    review_flags: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    if queue_state in {"scheduled_for_simulation", "scheduled_for_simulation_review_required"}:
        return []
    if queue_state == "blocked_by_review_gate":
        return [{
            "reason_id": "domain_review_gate_blocked",
            "detail": "Hard domain-policy review flags block Step3 scheduling until user review clears them.",
            "review_flags": [dict(flag) for flag in review_flags],
        }]
    if queue_state == "blocked_claim_boundary":
        return [{
            "reason_id": "diagnostic_claim_boundary",
            "detail": "Diagnostic, smoke, trace, synthetic, or reduced claim boundary cannot enter trusted Step3 simulation.",
        }]
    blocked: List[Dict[str, Any]] = [
        dict(reason)
        for reason in promotion_decision.get("reasons", []) or []
        if isinstance(reason, Mapping)
    ]
    if selected_record.get("violations"):
        blocked.append({
            "reason_id": "illegal_selected_mapping",
            "violations": list(selected_record.get("violations", []) or []),
        })
    if not blocked:
        blocked.append({
            "reason_id": "step2_not_promoted_for_simulation",
            "detail": "Step2 promotion decision did not schedule this selected entry for Step3.",
        })
    return blocked


def _queue_state_for_entry(
    *,
    promotion_decision: Mapping[str, Any],
    selected_record: Mapping[str, Any],
    architecture_artifact: Mapping[str, Any],
    review_required: bool,
    hard_blocked: bool,
) -> str:
    promoted = bool(promotion_decision.get("promoted_for_simulation", False))
    reason_ids = _reason_id_set(
        promotion_decision.get("reasons", []) or [],
        architecture_artifact.get("candidate_only_reasons", []) or [],
    )
    if "diagnostic_claim_boundary" in reason_ids:
        return "blocked_claim_boundary"
    if hard_blocked:
        return "blocked_by_review_gate"
    if not promoted or selected_record.get("violations"):
        return "blocked_not_promoted"
    if review_required:
        return "scheduled_for_simulation_review_required"
    return "scheduled_for_simulation"


def build_architecture_candidate_set(
    catalog: ArchitectureCatalog,
    *,
    workload_package: WorkloadPackage,
    selected_architecture_id: str,
    architecture_artifact: Mapping[str, Any],
    selected_record: Mapping[str, Any],
    promotion_decision: Mapping[str, Any],
    backend: str,
) -> Dict[str, Any]:
    """Build the replayable architecture candidate-set artifact for Step2 output."""
    candidates: List[Dict[str, Any]] = []
    for instance in sorted(catalog.instances.values(), key=lambda item: item.architecture_id):
        selected = instance.architecture_id == selected_architecture_id
        candidate_reason = instance.candidate_only_reason(catalog.simulation_bindings)
        instance_messages = _validation_messages(catalog, instance.architecture_id)
        instance_has_errors = any(message.get("severity") == "error" for message in instance_messages)
        selected_binding = _binding_payloads(catalog, instance).get(backend, {})
        step3_searchable, step3_blockers = _step3_searchability(
            selected_binding=selected_binding,
            catalog_has_errors=instance_has_errors,
            instance=instance,
        )
        promoted_for_simulation = bool(promotion_decision.get("promoted_for_simulation", False)) if selected else False
        eligibility_fields = _step2_eligibility_fields(
            step3_searchable=step3_searchable,
            step3_blockers=step3_blockers,
            promoted_for_simulation=promoted_for_simulation,
        )
        reasons: List[Dict[str, Any]] = []
        if candidate_reason:
            reasons.append({"reason_id": "architecture_candidate_only", "detail": candidate_reason})
        if selected:
            reasons.extend(dict(reason) for reason in promotion_decision.get("reasons", []) or [] if isinstance(reason, Mapping))
        candidate_parameters = {
            "architecture_id": instance.architecture_id,
            "architecture_family": instance.family_id,
            "backend": backend,
            "selected_mapping_candidate_id": selected_record.get("candidate_id") if selected else None,
        }
        candidates.append({
            "candidate_id": f"architecture::{instance.architecture_id}",
            "architecture_id": instance.architecture_id,
            "architecture_family": instance.family_id,
            "parameters": candidate_parameters,
            "parameter_hash": _payload_sha256(candidate_parameters),
            "candidate_identity_policy": "stable_architecture_id_with_parameter_hash_sidecar",
            "architecture_status": instance.status,
            "architecture_instance": instance.to_dict(include_bindings=True),
            "selected_for_step2_mapping": selected,
            "selected_mapping_candidate_id": selected_record.get("candidate_id") if selected else None,
            "promoted_for_simulation": promoted_for_simulation,
            "catalog_trusted_final_eligible": bool(instance.trusted_final_eligible(catalog.simulation_bindings)),
            "step3_searchable": step3_searchable,
            "step3_search_blockers": step3_blockers,
            **eligibility_fields,
            "step4_eligible": bool("gem5_systemc" in instance.simulation_bindings and step3_searchable),
            "candidate_only": bool(candidate_reason),
            "candidate_only_reasons": reasons,
            "ranking": {
                "priority_score": _priority_score(selected_record, bool(promotion_decision.get("promoted_for_simulation", False))) if selected else 0.0,
                "priority_reasons": _queue_priority_reasons(
                    selected_record=selected_record,
                    promotion_decision=promotion_decision,
                    review_required=False,
                    hard_blocked=False,
                ) if selected else [{"reason_id": "catalog_candidate_available", "source": "architecture_catalog"}],
            },
            "policy_added": False,
            "domain_policy": None,
            "trusted_final_claim": False,
        })

    return {
        "schema_version": "dse.step2.architecture_candidate_set.v1",
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "backend": backend,
        "selected_architecture_id": selected_architecture_id,
        "selected_mapping_candidate_id": selected_record.get("candidate_id"),
        "candidate_count": len(candidates),
        "queue_artifact": "step3_simulation_queue.json",
        "trusted_final_claim": False,
        "policy_scope": "generic_catalog_only",
        "candidates": candidates,
        "notes": [
            "This artifact records replayable Step2 architecture candidates; it does not alter non-domain defaults.",
            "Domain/reference policies may add or rank candidates only through explicit registration.",
        ],
    }


def build_step3_simulation_queue(
    *,
    workload_package: WorkloadPackage,
    design_point: DesignPoint,
    selected_record: Mapping[str, Any],
    promotion_decision: Mapping[str, Any],
    architecture_artifact: Mapping[str, Any],
    backend: str,
) -> Dict[str, Any]:
    """Build a selected-entry-only v1 Step3 queue without executing Step3."""
    review_flags, review_required, hard_blocked = _review_state(
        promotion_decision=promotion_decision,
        selected_record=selected_record,
        architecture_artifact=architecture_artifact,
    )
    queue_state = _queue_state_for_entry(
        promotion_decision=promotion_decision,
        selected_record=selected_record,
        architecture_artifact=architecture_artifact,
        review_required=review_required,
        hard_blocked=hard_blocked,
    )
    promoted = bool(promotion_decision.get("promoted_for_simulation", False))
    co_design = promotion_decision.get("co_design", {}) if isinstance(promotion_decision.get("co_design", {}), Mapping) else {}
    mapping_candidate_id = str(selected_record.get("candidate_id") or promotion_decision.get("candidate_id") or "selected_mapping")
    architecture_id = str(architecture_artifact.get("architecture_id") or design_point.config.get("architecture_id") or design_point.system_architecture.system_id)
    mapping_id = str(promotion_decision.get("mapping_id") or design_point.config.get("mapping_id") or f"{design_point.design_point_id}_mapping")
    entry = {
        "queue_entry_id": f"step2-selected::{architecture_id}::{mapping_candidate_id}",
        "candidate_id": f"{architecture_id}::{mapping_candidate_id}",
        "design_point_id": design_point.design_point_id,
        "design_point_artifact": "design_point.json",
        "mapping_id": mapping_id,
        "mapping_candidate_id": mapping_candidate_id,
        "architecture_id": architecture_id,
        "backend": backend,
        "required_step3_artifacts": list(promotion_decision.get("required_evidence", []) or ["simulation_request.json", "simulation_result.json", "verdict.json"]),
        "priority_score": _priority_score(selected_record, promoted),
        "priority_reasons": _queue_priority_reasons(
            selected_record=selected_record,
            promotion_decision=promotion_decision,
            review_required=review_required,
            hard_blocked=hard_blocked,
        ),
        "review_flags": [dict(flag) for flag in review_flags],
        "review_required": review_required,
        "promoted_for_simulation": promoted,
        "step3_searchable": bool(architecture_artifact.get("step3_searchable", False)),
        "trusted_final_eligible_before_step3": bool(architecture_artifact.get("trusted_final_eligible", False)),
        "step3_search_blockers": list(architecture_artifact.get("step3_search_blockers", []) or []),
        "queue_state": queue_state,
        "blocked_reasons": _queue_blocked_reasons(
            queue_state=queue_state,
            promotion_decision=promotion_decision,
            selected_record=selected_record,
            review_flags=review_flags,
        ),
        "l4_required": bool(co_design.get("l4_required", False)),
        "l4_required_reason": str(co_design.get("l4_required_reason") or ""),
        "promotion_decision_artifact": "mapping_promotion_decision.json",
        "mapping_selected_record_artifact": "mapping_selected_record.json",
        "claim_status": "legacy_pilot_only",
        "retention_policy": "legacy_pilot_regression_only",
        "release_completion_eligible": False,
        "blocked_claims": ["step2_full_dse_complete", "deliverable_complete"],
        "claim_boundary": (
            "Selected-entry queues and local regression tests are pilot/replay evidence only; "
            "they cannot establish Step2 full-DSE completion."
        ),
        "trusted_final_claim": False,
    }
    return {
        "schema_version": "dse.step3.simulation_queue.v1",
        "queue_mode": "selected-entry-only",
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "backend": backend,
        "entry_count": 1,
        "claim_status": "legacy_pilot_only",
        "retention_policy": "legacy_pilot_regression_only",
        "release_completion_eligible": False,
        "blocked_claims": ["step2_full_dse_complete", "deliverable_complete"],
        "claim_boundary": (
            "Selected-entry queues and local regression tests are pilot/replay evidence only; "
            "they cannot establish Step2 full-DSE completion."
        ),
        "trusted_final_claim": False,
        "top_k_queue_deferred": True,
        "entries": [entry],
        "notes": [
            "Step2 queues only the selected replay entry; final ranking and trusted claims require Step3+ evidence.",
            "Queue metadata cannot override mapping_promotion_decision.promoted_for_simulation=false.",
        ],
    }


def _step2_control_scope(
    workload_package: WorkloadPackage,
    *,
    trial_seed: str,
    workload_run_seed: Optional[str] = None,
) -> Dict[str, str]:
    """Return deterministic Campaign/WorkloadRun/Trial IDs for Step2 artifacts.

    Older callers do not yet provide a full Campaign ledger.  Until the ledger
    API is threaded through every Step2 entry point, these deterministic IDs
    give canonical artifacts a stable control-plane scope without leaking any
    workload-family-specific fields into the generic Step2 contract.
    """

    workflow = workload_package.workflow if isinstance(workload_package.workflow, Mapping) else {}
    source = workload_package.source if isinstance(workload_package.source, Mapping) else {}
    domain = workload_package.domain_metadata if isinstance(workload_package.domain_metadata, Mapping) else {}
    campaign_id = str(
        workflow.get("campaign_id")
        or source.get("campaign_id")
        or domain.get("campaign_id")
        or f"campaign::{workload_package.workload_id}"
    )
    workload_run_id = str(
        workflow.get("workload_run_id")
        or source.get("workload_run_id")
        or domain.get("workload_run_id")
        or workload_run_seed
        or f"workload_run::{workload_package.workload_id}"
    )
    trial_id = str(
        workflow.get("trial_id")
        or source.get("trial_id")
        or domain.get("trial_id")
        or f"trial::{trial_seed}"
    )
    return {
        "campaign_id": campaign_id,
        "workload_run_id": workload_run_id,
        "trial_id": trial_id,
    }


def _reason_id_list(items: Iterable[Any]) -> List[str]:
    """Return stable reason/blocker identifiers without losing fail-closed detail."""

    reasons: List[str] = []
    for item in items:
        if isinstance(item, Mapping):
            reason = item.get("reason_id") or item.get("blocker_id") or item.get("message") or item.get("detail")
            if reason is not None:
                reasons.append(str(reason))
        elif item is not None:
            reasons.append(str(item))
    return reasons


def _trial_state_from_flags(
    *,
    generated: bool,
    screened: bool,
    promoted: bool,
    queue_state: str,
    blockers: Sequence[str],
) -> str:
    if queue_state.startswith("scheduled_for_simulation"):
        return "queued_for_step3"
    if queue_state.startswith("blocked"):
        return queue_state
    if promoted:
        return "promoted_not_queued"
    if blockers:
        return "blocked_before_step3"
    if screened:
        return "screened_not_promoted"
    if generated:
        return "generated_not_screened"
    return "unknown"


def build_step2_trial_state_ledger(
    *,
    workload_package: WorkloadPackage,
    architecture_candidates: Sequence[Mapping[str, Any]],
    mapping_candidates: Sequence[Mapping[str, Any]],
    screening_results: Sequence[Mapping[str, Any]],
    promotion_decisions: Sequence[Mapping[str, Any]],
    step3_queue: Mapping[str, Any],
    search_space: Mapping[str, Any],
    scope: Mapping[str, str],
    policy_scope: str,
) -> Dict[str, Any]:
    """Build the domain-neutral Step2 Trial ledger.

    The ledger is intentionally still a Step2 artifact: it records candidate
    generation/screening/promotion/queue state so Step3 can be audited, but it
    never upgrades candidates to trusted winners or substitutes for evidence.
    """

    queue_entries = [
        dict(entry)
        for entry in step3_queue.get("entries", []) or []
        if isinstance(entry, Mapping)
    ]
    queue_by_candidate_id = {str(entry.get("candidate_id")): entry for entry in queue_entries if entry.get("candidate_id")}
    queue_by_architecture_id = {str(entry.get("architecture_id")): entry for entry in queue_entries if entry.get("architecture_id")}
    queue_by_mapping_id = {str(entry.get("mapping_candidate_id")): entry for entry in queue_entries if entry.get("mapping_candidate_id")}
    queue_by_architecture_mapping = {
        (str(entry.get("architecture_id")), str(entry.get("mapping_candidate_id"))): entry
        for entry in queue_entries
        if entry.get("architecture_id") and entry.get("mapping_candidate_id")
    }
    screening_by_candidate_id = {
        str(record.get("candidate_id")): dict(record)
        for record in screening_results
        if isinstance(record, Mapping) and record.get("candidate_id")
    }
    promotions_by_candidate_id = {
        str(record.get("candidate_id")): dict(record)
        for record in promotion_decisions
        if isinstance(record, Mapping) and record.get("candidate_id")
    }
    promotions_by_architecture_candidate = {
        (str(record.get("architecture_id")), str(record.get("candidate_id"))): dict(record)
        for record in promotion_decisions
        if isinstance(record, Mapping) and record.get("architecture_id") and record.get("candidate_id")
    }

    rows: List[Dict[str, Any]] = []

    def append_row(candidate_type: str, candidate: Mapping[str, Any]) -> None:
        candidate_id = str(candidate.get("candidate_id") or "")
        parameters = candidate.get("parameters", {}) if isinstance(candidate.get("parameters", {}), Mapping) else {}
        architecture_id = str(candidate.get("architecture_id") or parameters.get("architecture_id") or "")
        mapping_candidate_id = str(
            candidate.get("mapping_candidate_id")
            or candidate.get("selected_mapping_candidate_id")
            or candidate_id
        )
        screen = screening_by_candidate_id.get(candidate_id, {})
        promotion = promotions_by_architecture_candidate.get((architecture_id, candidate_id)) or promotions_by_candidate_id.get(candidate_id, {})
        if candidate_type == "architecture":
            queue = (
                queue_by_architecture_id.get(architecture_id)
                or queue_by_architecture_mapping.get((architecture_id, mapping_candidate_id))
                or queue_by_candidate_id.get(candidate_id)
                or {}
            )
        else:
            queue = (
                queue_by_candidate_id.get(candidate_id)
                or queue_by_architecture_mapping.get((architecture_id, mapping_candidate_id))
                or queue_by_mapping_id.get(mapping_candidate_id)
                or {}
            )
        promoted = bool(
            candidate.get("promoted_for_simulation")
            or candidate.get("simulation_eligible")
            or screen.get("simulation_eligible")
            or promotion.get("promoted_for_simulation")
        )
        screened = bool(screen) or candidate_type == "architecture"
        simulation_blockers = _reason_id_list(candidate.get("simulation_blockers", []) or [])
        step3_blockers = _reason_id_list(candidate.get("step3_search_blockers", []) or [])
        candidate_blockers = _reason_id_list(candidate.get("blocker_reasons", []) or [])
        screening_blockers = _reason_id_list(screen.get("blocker_reasons", []) or [])
        queue_blockers = _reason_id_list(queue.get("blocked_reasons", []) or [])
        blockers = sorted({
            *simulation_blockers,
            *step3_blockers,
            *candidate_blockers,
            *screening_blockers,
            *queue_blockers,
        })
        queue_state = str(queue.get("queue_state") or "not_queued")
        trial_state = _trial_state_from_flags(
            generated=True,
            screened=screened,
            promoted=promoted,
            queue_state=queue_state,
            blockers=blockers,
        )
        search_policy = candidate.get("search_policy", {}) if isinstance(candidate.get("search_policy", {}), Mapping) else {}
        rows.append({
            "schema_version": "dse.step2.trial_candidate_record.v1",
            **dict(scope),
            "trial_candidate_id": f"{scope.get('trial_id', 'trial')}::{candidate_type}::{candidate_id}",
            "candidate_type": candidate_type,
            "candidate_id": candidate_id,
            "architecture_id": architecture_id,
            "mapping_candidate_id": mapping_candidate_id if candidate_type == "mapping" or mapping_candidate_id != candidate_id else None,
            "parameter_hash": str(candidate.get("parameter_hash") or ""),
            "candidate_identity_policy": str(candidate.get("candidate_identity_policy") or "unknown"),
            "generated": True,
            "screened": screened,
            "step2_screenable": bool(candidate.get("step2_screenable", screen.get("step2_screenable", False))),
            "step3_evaluable": bool(candidate.get("step3_evaluable", screen.get("step3_evaluable", False))),
            "simulation_eligible": bool(candidate.get("simulation_eligible", screen.get("simulation_eligible", False))),
            "promoted_for_simulation": promoted,
            "queue_state": queue_state,
            "trial_state": trial_state,
            "blockers": blockers,
            "search_policy_name": str(candidate.get("search_policy_name") or search_policy.get("policy_name") or ""),
            "search_policy_candidate_id": str(candidate.get("search_policy_candidate_id") or search_policy.get("candidate_id") or ""),
            "search_policy_rank": candidate.get("search_policy_rank") or search_policy.get("search_policy_rank"),
            "search_policy_provenance": dict(search_policy),
            "transition_history": [
                {
                    "transition": "candidate_generated",
                    "status": "recorded",
                    "artifact": "architecture_candidate_set.json" if candidate_type == "architecture" else "mapping_candidates.jsonl",
                },
                {
                    "transition": "search_policy_proposed",
                    "status": "recorded" if search_policy else "not_available",
                    "artifact": "search_checkpoint.json",
                },
                {
                    "transition": "screened",
                    "status": "passed" if bool(screen.get("passed", candidate.get("step2_screenable", False))) else "blocked_or_not_screened",
                    "artifact": "screening_results.jsonl",
                },
                {
                    "transition": "promotion_decision",
                    "status": "promote" if promoted else str(promotion.get("decision") or "block"),
                    "artifact": "promotion_decisions.jsonl",
                },
                {
                    "transition": "step3_queue_admission",
                    "status": queue_state,
                    "artifact": "step3_simulation_queue.json",
                },
            ],
            "artifact_refs": {
                "search_space": "architecture_search_space.json",
                "candidate_set": "architecture_candidate_set.json",
                "mapping_candidates": "mapping_candidates.jsonl",
                "screening_results": "screening_results.jsonl",
                "promotion_decisions": "promotion_decisions.jsonl",
                "step3_queue": "step3_simulation_queue.json",
            },
            "trusted_final_claim": False,
        })

    for candidate in architecture_candidates:
        append_row("architecture", candidate)
    for candidate in mapping_candidates:
        append_row("mapping", candidate)

    state_counts: Dict[str, int] = {}
    for row in rows:
        state = str(row.get("trial_state"))
        state_counts[state] = state_counts.get(state, 0) + 1

    return {
        "schema_version": "dse.step2.trial_state_ledger.v1",
        **dict(scope),
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "policy_scope": policy_scope,
        "trial_state_policy": "generated_screened_promoted_queued_fail_closed_v1",
        "candidate_identity_policy": "stable_parameter_hash_sidecar",
        "search_space_artifact": "architecture_search_space.json",
        "search_space_hash": search_space.get("search_space_hash"),
        "candidate_generation_report_artifact": "architecture_candidate_generation_report.json",
        "architecture_screening_report_artifact": "architecture_screening_report.json",
        "step3_simulation_queue_artifact": "step3_simulation_queue.json",
        "queue_mode": step3_queue.get("queue_mode"),
        "candidate_count": len(rows),
        "architecture_candidate_count": len(architecture_candidates),
        "mapping_candidate_count": len(mapping_candidates),
        "queued_entry_count": len(queue_entries),
        "promoted_candidate_count": sum(1 for row in rows if row.get("promoted_for_simulation")),
        "blocked_candidate_count": sum(1 for row in rows if row.get("blockers")),
        "state_counts": state_counts,
        "all_candidates_have_parameter_hash": all(row.get("parameter_hash") for row in rows),
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "claim_boundary": (
            "Trial ledger state is Step2 search/provenance evidence only. "
            "It gates Step3 admission and auditability but cannot prove final hardware claims."
        ),
        "candidates": rows,
    }


def build_architecture_search_space_artifact(
    catalog: ArchitectureCatalog,
    *,
    workload_package: WorkloadPackage,
    architecture_ids: Sequence[str],
    backend: str,
    objective_directions: Mapping[str, str],
    random_seed: int,
    beam_width: int,
    policy_scope: str,
    scope: Mapping[str, str],
) -> Dict[str, Any]:
    """Build the canonical Step2 parameterized architecture search-space."""

    families: Dict[str, List[str]] = {}
    for architecture_id in architecture_ids:
        instance = catalog.instances.get(architecture_id)
        family_id = instance.family_id if instance is not None else "unknown"
        families.setdefault(str(family_id), []).append(str(architecture_id))
    payload: Dict[str, Any] = {
        "schema_version": "dse.step2.architecture_search_space.v1",
        **dict(scope),
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "profile_id": workload_package.profile_id,
        "backend": backend,
        "policy_scope": policy_scope,
        "objective_directions": dict(objective_directions),
        "parameters": {
            "architecture_ids": [str(item) for item in architecture_ids],
            "architecture_families": {family: sorted(ids) for family, ids in sorted(families.items())},
            "beam_width": int(beam_width),
            "random_seed": int(random_seed),
        },
        "constraints": {
            "claim_boundary": workload_package.claim_boundary,
            "step2_only": True,
            "trusted_final_claim": False,
            "candidate_identity_policy": "stable_parameter_hash_sidecar",
        },
        "generation_provenance": {
            "catalog_instance_count": len(catalog.instances),
            "selected_architecture_count": len(architecture_ids),
            "source": "Step2 catalog/domain-policy screening",
            "candidate_identity_policy": "stable_parameter_hash_sidecar",
            "candidate_identity_excludes": [
                "proposal_order",
                "transient_rank",
                "Step3_result",
                "Step4_verdict",
            ],
            "replay_inputs": [
                "architecture_catalog.json",
                "workload_package.json",
                "executable_graph.json",
                "mapping_seed_set.json",
            ],
        },
        "freeze_gate_verdict": {
            "status": "candidate_generation_only",
            "completion_evidence": False,
            "reason": "Search space defines Step2 candidates; Step3+ evidence is required for final claims.",
        },
        "trusted_final_claim": False,
    }
    payload["search_space_hash"] = _payload_sha256({key: value for key, value in payload.items() if key != "search_space_hash"})
    return payload


def _candidate_priority_score(candidate: Mapping[str, Any]) -> float:
    """Return a deterministic Step2 ordering score for provenance queues."""

    ranking = candidate.get("ranking", {}) if isinstance(candidate.get("ranking", {}), Mapping) else {}
    screening = candidate.get("screening", {}) if isinstance(candidate.get("screening", {}), Mapping) else {}
    for value in (
        candidate.get("score"),
        candidate.get("estimated_score"),
        candidate.get("promotion_priority"),
        ranking.get("priority_score"),
        screening.get("promotion_priority"),
    ):
        number = _finite_float(value, default=float("nan"))
        if math.isfinite(number):
                return number
    return 0.0


def _mapping_record_search_parameters(
    record: Mapping[str, Any],
    *,
    index: int,
    backend: str,
    architecture_id: str,
    mapping_policy: str,
) -> Dict[str, Any]:
    """Return the domain-neutral parameter record handed to SearchPolicy.

    SearchPolicy is the Step2 candidate-generation/search contract.  The
    current workflow still gets raw legal mappings from `run_mapping_search`,
    so this bridge treats those mapping records as seed candidates and records
    the policy's replayable ordering/provenance without widening Step3
    admission.
    """

    mapping = dict(record.get("mapping", {}) or {})
    candidate_id = str(record.get("candidate_id") or f"mapping_candidate_{index}")
    priority = _candidate_priority_score(record)
    return {
        "architecture_id": str(record.get("architecture_id") or architecture_id),
        "backend": backend,
        "mapping_candidate_id": candidate_id,
        "mapping_policy": mapping_policy,
        "mapping": mapping,
        "mapping_parameter_hash": str(record.get("parameter_hash") or _payload_sha256(mapping)),
        "source_state": str(record.get("state") or "unknown"),
        "source_seed_name": str(record.get("seed_name") or ""),
        "step2_candidate_rank_score": priority,
        "source_candidate_index": index,
        "release_lane": "release" if not record.get("violations") else "blocked",
    }


def _build_step2_search_policy_payload(
    *,
    workload_package: WorkloadPackage,
    mapping_candidate_records: Mapping[str, Any],
    scope: Mapping[str, str],
    backend: str,
    architecture_id: str,
    objective_directions: Mapping[str, str],
    beam_width: int,
    step3_queue: Mapping[str, Any],
) -> Dict[str, Any]:
    """Run the default SearchPolicy over Step2 seed candidates.

    This is deliberately Step2-only provenance.  It does not schedule new
    simulations and it does not alter `step3_simulation_queue.json`.
    """

    raw_records = [
        dict(record)
        for record in mapping_candidate_records.get("candidates", []) or []
        if isinstance(record, Mapping)
    ]
    mapping_policy = str(mapping_candidate_records.get("algorithm") or "workflow_seeded_beam_local_search_v1")
    seed_candidates = [
        _mapping_record_search_parameters(
            record,
            index=index,
            backend=backend,
            architecture_id=architecture_id,
            mapping_policy=mapping_policy,
        )
        for index, record in enumerate(raw_records)
    ]
    candidate_ids = [str(seed.get("mapping_candidate_id")) for seed in seed_candidates]
    release_lanes = sorted({str(seed.get("release_lane")) for seed in seed_candidates if seed.get("release_lane")})
    problem = SearchProblem(
        problem_id=f"step2::{scope.get('trial_id', workload_package.workload_id)}::mapping_candidates",
        workload_run_id=str(scope.get("workload_run_id") or workload_package.workload_id),
        objective="rank_step2_mapping_candidates",
        parameters={
            "architecture_id": sorted({str(seed.get("architecture_id") or architecture_id) for seed in seed_candidates}) or [architecture_id],
            "backend": [backend],
            "mapping_candidate_id": candidate_ids,
            "release_lane": release_lanes or ["release"],
        },
        constraints={
            "objective_directions": dict(objective_directions),
            "required_parameters": [
                "architecture_id",
                "backend",
                "mapping_candidate_id",
                "mapping_parameter_hash",
            ],
            "formal_pareto_lane_field": "release_lane",
            "release_lane": "release",
            "hierarchical_funnel_stages": list(HIERARCHICAL_FUNNEL_STAGES),
            "max_candidate_enumeration": 0,
            "candidate_source_artifact": "mapping_candidate_records.json",
            "step3_admission_queue": "step3_simulation_queue.json",
            "top_k_queue_role": "provenance_only_not_step3_admission",
            "candidate_generation_only": True,
            "trusted_final_claim": False,
        },
        seed_candidates=tuple(seed_candidates),
    )
    proposal_budget = len(seed_candidates)
    policy = HierarchicalFunnelSearchPolicy(bottleneck_keys=("step2_candidate_rank_score",))
    proposed = policy.propose(problem, budget=proposal_budget)
    candidate_payloads: List[Dict[str, Any]] = []
    for rank, record in enumerate(proposed, start=1):
        payload = record.to_dict()
        payload["search_policy_rank"] = rank
        payload["not_a_step3_queue_entry"] = True
        payload["provenance_only"] = True
        payload["trusted_final_claim"] = False
        candidate_payloads.append(payload)
    checkpoint = policy.checkpoint(problem).to_dict()
    checkpoint["candidates"] = candidate_payloads
    checkpoint["candidate_count"] = len(candidate_payloads)
    checkpoint["proposal_budget"] = proposal_budget
    return {
        "schema_version": "dse.step2.search_policy_payload.v1",
        **dict(scope),
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "policy_name": policy.policy_name,
        "problem_id": problem.problem_id,
        "problem": {
            "problem_id": problem.problem_id,
            "workload_run_id": problem.workload_run_id,
            "objective": problem.objective,
            "parameters": {key: list(values) for key, values in problem.parameters.items()},
            "constraints": dict(problem.constraints),
            "seed_candidate_count": len(seed_candidates),
            "parameter_grid_size": problem.parameter_grid_size(),
        },
        "mapping_policy": mapping_policy,
        "proposal_budget": proposal_budget,
        "proposed_count": len(candidate_payloads),
        "observed_count": int(checkpoint.get("observed_count", 0) or 0),
        "best_candidate_id": checkpoint.get("best_candidate_id"),
        "step3_simulation_queue_artifact": "step3_simulation_queue.json",
        "step3_queue_mode": step3_queue.get("queue_mode"),
        "step3_queue_entry_budget": int(step3_queue.get("entry_count", 0) or 0),
        "top_k_queue_role": "provenance_only_not_step3_admission",
        "candidate_source_artifact": "mapping_candidate_records.json",
        "candidate_identity_policy": "stable_problem_policy_parameter_hash",
        "candidates": candidate_payloads,
        "checkpoint": checkpoint,
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "claim_boundary": (
            "SearchPolicy proposals are Step2 candidate-generation provenance. "
            "They order and explain candidates but cannot admit work to Step3 except "
            "through step3_simulation_queue.json."
        ),
    }


def _search_policy_candidate_lookup(search_policy_payload: Optional[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    if not isinstance(search_policy_payload, Mapping):
        return lookup
    for candidate in search_policy_payload.get("candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        parameters = candidate.get("parameters", {}) if isinstance(candidate.get("parameters", {}), Mapping) else {}
        mapping_candidate_id = str(parameters.get("mapping_candidate_id") or "")
        if mapping_candidate_id:
            lookup[mapping_candidate_id] = dict(candidate)
    return lookup


def _compact_search_policy_candidate(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    provenance = candidate.get("provenance", {}) if isinstance(candidate.get("provenance", {}), Mapping) else {}
    parameters = candidate.get("parameters", {}) if isinstance(candidate.get("parameters", {}), Mapping) else {}
    return {
        "policy_name": provenance.get("policy_name"),
        "candidate_id": candidate.get("candidate_id"),
        "mapping_candidate_id": parameters.get("mapping_candidate_id"),
        "parameter_hash": candidate.get("parameter_hash"),
        "search_policy_rank": candidate.get("search_policy_rank"),
        "generation_reason": candidate.get("generation_reason"),
        "score": candidate.get("score"),
        "promotion_reasons": list(candidate.get("promotion_reasons", []) or []),
        "blocker_reasons": list(candidate.get("blocker_reasons", []) or []),
        "simulation_eligible": bool(candidate.get("simulation_eligible", False)),
        "provenance": dict(provenance),
        "trusted_final_claim": False,
    }


def _search_space_with_policy(
    search_space: Mapping[str, Any],
    search_policy_payload: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    payload = dict(search_space)
    if isinstance(search_policy_payload, Mapping) and search_policy_payload:
        generation_provenance = dict(payload.get("generation_provenance", {}) or {})
        generation_provenance["search_policy"] = {
            "policy_name": search_policy_payload.get("policy_name"),
            "problem_id": search_policy_payload.get("problem_id"),
            "proposal_budget": search_policy_payload.get("proposal_budget"),
            "proposed_count": search_policy_payload.get("proposed_count"),
            "candidate_source_artifact": search_policy_payload.get("candidate_source_artifact"),
            "step3_admission_queue": search_policy_payload.get("step3_simulation_queue_artifact"),
            "top_k_queue_role": search_policy_payload.get("top_k_queue_role"),
        }
        payload["generation_provenance"] = generation_provenance
        payload["search_policy_name"] = search_policy_payload.get("policy_name")
        payload["search_policy_problem_id"] = search_policy_payload.get("problem_id")
        payload["search_policy_budget"] = search_policy_payload.get("proposal_budget")
        payload["search_policy_proposed_count"] = search_policy_payload.get("proposed_count")
        payload["search_policy_candidate_source_artifact"] = search_policy_payload.get("candidate_source_artifact")
    payload["search_space_hash"] = _payload_sha256({key: value for key, value in payload.items() if key != "search_space_hash"})
    return payload


def _checkpoint_candidate_summary(
    *,
    candidate_type: str,
    candidate: Mapping[str, Any],
    source_artifact: str,
    source_index: int,
) -> Dict[str, Any]:
    parameters = candidate.get("parameters", {}) if isinstance(candidate.get("parameters", {}), Mapping) else {}
    parameter_hash = str(candidate.get("parameter_hash") or _payload_sha256(parameters or {
        "candidate_id": candidate.get("candidate_id"),
        "architecture_id": candidate.get("architecture_id"),
        "mapping": candidate.get("mapping", {}),
    }))
    search_policy = candidate.get("search_policy", {}) if isinstance(candidate.get("search_policy", {}), Mapping) else {}
    summary = {
        "candidate_type": candidate_type,
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "architecture_id": str(candidate.get("architecture_id") or ""),
        "mapping_candidate_id": str(
            candidate.get("mapping_candidate_id")
            or candidate.get("selected_mapping_candidate_id")
            or (candidate.get("candidate_id") if candidate_type == "mapping" else "")
            or ""
        ),
        "parameter_hash": parameter_hash,
        "candidate_identity_policy": str(candidate.get("candidate_identity_policy") or "stable_parameter_hash_sidecar"),
        "score": _candidate_priority_score(candidate),
        "step2_screenable": bool(candidate.get("step2_screenable", not bool(candidate.get("violations")))),
        "step3_evaluable": bool(candidate.get("step3_evaluable", candidate.get("simulation_eligible", False))),
        "simulation_eligible": bool(candidate.get("simulation_eligible", False)),
        "promoted_for_simulation": bool(candidate.get("promoted_for_simulation", candidate.get("simulation_eligible", False))),
        "simulation_blockers": list(candidate.get("simulation_blockers", candidate.get("blocker_reasons", [])) or []),
        "source_artifact": source_artifact,
        "source_index": source_index,
        "trusted_final_claim": False,
    }
    if search_policy:
        summary.update({
            "search_policy_name": str(candidate.get("search_policy_name") or search_policy.get("policy_name") or ""),
            "search_policy_candidate_id": str(candidate.get("search_policy_candidate_id") or search_policy.get("candidate_id") or ""),
            "search_policy_rank": candidate.get("search_policy_rank") or search_policy.get("search_policy_rank"),
            "search_policy_parameter_hash": str(
                candidate.get("search_policy_parameter_hash")
                or search_policy.get("parameter_hash")
                or ""
            ),
            "search_policy_generation_reason": str(search_policy.get("generation_reason") or ""),
            "search_policy": dict(search_policy),
        })
    return summary


def build_top_k_candidate_queue(
    *,
    workload_package: WorkloadPackage,
    mapping_candidate_records: Mapping[str, Any],
    mapping_candidates: Sequence[Mapping[str, Any]],
    promotion_decision: Optional[Mapping[str, Any]],
    step3_queue: Mapping[str, Any],
    scope: Mapping[str, str],
    policy_scope: str,
    beam_width: int,
    search_policy_payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a provenance-only top-K ordering queue.

    This artifact is intentionally not the Step3 admission queue.  It preserves
    ranked candidate provenance while `step3_simulation_queue.json` remains the
    selected-entry v1 handoff consumed by Step3.
    """

    canonical_by_id = {
        str(candidate.get("candidate_id")): dict(candidate)
        for candidate in mapping_candidates
        if isinstance(candidate, Mapping) and candidate.get("candidate_id")
    }
    search_policy_by_mapping_id = _search_policy_candidate_lookup(search_policy_payload)
    search_policy_name = (
        str(search_policy_payload.get("policy_name"))
        if isinstance(search_policy_payload, Mapping) and search_policy_payload.get("policy_name")
        else ""
    )
    mapping_policy_name = str(mapping_candidate_records.get("algorithm", "workflow_seeded_beam_local_search_v1"))
    step3_entries = [
        entry
        for entry in step3_queue.get("entries", []) or []
        if isinstance(entry, Mapping)
    ]
    admitted_mapping_ids = {
        str(entry.get("mapping_candidate_id"))
        for entry in step3_entries
        if entry.get("mapping_candidate_id")
        and str(entry.get("queue_state", "")).startswith("scheduled_for_simulation")
    }
    source_records = [
        dict(record)
        for record in mapping_candidate_records.get("candidates", []) or []
        if isinstance(record, Mapping)
    ]
    ranked_source = [
        record
        for record in source_records
        if not record.get("violations") and str(record.get("state", "")) in {"selected", "promoted", "predicted-only"}
    ]
    if not ranked_source:
        ranked_source = [record for record in source_records if not record.get("violations")]
    ranked_source = sorted(
        ranked_source,
        key=lambda record: (
            0 if str(record.get("state", "")) == "selected" else 1,
            -_candidate_priority_score(record),
            str(record.get("candidate_id") or ""),
        ),
    )
    top_k = ranked_source[: max(1, int(beam_width or 1))]
    entries: List[Dict[str, Any]] = []
    for rank, source in enumerate(top_k, start=1):
        candidate_id = str(source.get("candidate_id") or "")
        canonical = canonical_by_id.get(candidate_id, {})
        parameter_hash = str(
            canonical.get("parameter_hash")
            or source.get("parameter_hash")
            or _payload_sha256({
                "architecture_id": canonical.get("architecture_id") or (promotion_decision or {}).get("architecture_id") or "",
                "backend": canonical.get("parameters", {}).get("backend") if isinstance(canonical.get("parameters", {}), Mapping) else "",
                "mapping": source.get("mapping", {}),
                "mapping_policy": mapping_candidate_records.get("algorithm"),
            })
        )
        top_k_state = "selected_entry" if str(source.get("state", "")) == "selected" else "candidate_order_suggestion"
        search_policy_candidate = search_policy_by_mapping_id.get(candidate_id, {})
        entry = {
            "top_k_rank": rank,
            "top_k_entry_id": f"top-k::{scope.get('trial_id', 'trial')}::{rank}::{candidate_id}",
            "candidate_id": candidate_id,
            "mapping_candidate_id": candidate_id,
            "architecture_id": str(canonical.get("architecture_id") or (promotion_decision or {}).get("architecture_id") or ""),
            "parameter_hash": parameter_hash,
            "candidate_identity_policy": str(canonical.get("candidate_identity_policy") or source.get("candidate_identity_policy") or "stable_mapping_parameters_hash_sidecar"),
            "source_state": str(source.get("state") or "unknown"),
            "top_k_state": top_k_state,
            "priority_score": _candidate_priority_score(source),
            "step2_screenable": not bool(source.get("violations")),
            "promoted_by_mapping_search": str(source.get("state", "")) in {"selected", "promoted"},
            "admitted_by_step3_queue": candidate_id in admitted_mapping_ids,
            "step3_admission_source": "step3_simulation_queue.json",
            "execution_suggestion_only": True,
            "not_a_step3_queue_entry": True,
            "release_completion_eligible": False,
            "top_k_or_representative_completion_allowed": False,
            "trusted_final_claim": False,
            "source_artifact": "mapping_candidate_records.json",
        }
        if search_policy_candidate:
            search_policy_compact = _compact_search_policy_candidate(search_policy_candidate)
            entry.update({
                "search_policy_name": search_policy_name,
                "search_policy_candidate_id": search_policy_compact.get("candidate_id"),
                "search_policy_rank": search_policy_compact.get("search_policy_rank"),
                "search_policy_parameter_hash": search_policy_compact.get("parameter_hash"),
                "search_policy_generation_reason": search_policy_compact.get("generation_reason"),
                "search_policy": search_policy_compact,
            })
        entries.append(entry)

    return {
        "schema_version": "dse.step2.top_k_candidate_queue.v1",
        **dict(scope),
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "policy_scope": policy_scope,
        "policy_name": search_policy_name or mapping_policy_name,
        "mapping_policy_name": mapping_policy_name,
        "search_policy_name": search_policy_name or None,
        "search_policy_problem_id": search_policy_payload.get("problem_id") if isinstance(search_policy_payload, Mapping) else None,
        "search_policy_budget": search_policy_payload.get("proposal_budget") if isinstance(search_policy_payload, Mapping) else None,
        "search_policy_proposed_count": search_policy_payload.get("proposed_count") if isinstance(search_policy_payload, Mapping) else None,
        "queue_mode": "top-k-provenance-only",
        "entry_count": len(entries),
        "requested_top_k": max(1, int(beam_width or 1)),
        "candidate_source_artifact": "mapping_candidate_records.json",
        "mapping_candidates_artifact": "mapping_candidates.jsonl",
        "step3_simulation_queue_artifact": "step3_simulation_queue.json",
        "step3_queue_mode": str(step3_queue.get("queue_mode") or ""),
        "provenance_only": True,
        "execution_order_suggestion_only": True,
        "top_k_or_representative_completion_allowed": False,
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "claim_boundary": (
            "Top-K ordering is search provenance and future execution-order guidance only. "
            "It is not the Step3 admission queue and cannot establish final completion."
        ),
        "entries": entries,
    }


def build_step2_search_checkpoint_artifact(
    *,
    workload_package: WorkloadPackage,
    search_space: Mapping[str, Any],
    architecture_candidates: Sequence[Mapping[str, Any]],
    mapping_candidates: Sequence[Mapping[str, Any]],
    mapping_candidate_records: Mapping[str, Any],
    mapping_feedback_state: Optional[Mapping[str, Any]],
    convergence_status: Optional[Mapping[str, Any]],
    top_k_candidate_queue: Mapping[str, Any],
    step3_queue: Mapping[str, Any],
    scope: Mapping[str, str],
    policy_scope: str,
    search_policy_payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a compact replay checkpoint over Step2 candidate/search state."""

    candidate_summaries = [
        _checkpoint_candidate_summary(
            candidate_type="architecture",
            candidate=candidate,
            source_artifact="architecture_candidate_set.json",
            source_index=index,
        )
        for index, candidate in enumerate(architecture_candidates)
    ] + [
        _checkpoint_candidate_summary(
            candidate_type="mapping",
            candidate=candidate,
            source_artifact="mapping_candidates.jsonl",
            source_index=index,
        )
        for index, candidate in enumerate(mapping_candidates)
    ]
    best = max(candidate_summaries, key=lambda item: item.get("score", 0.0), default=None)
    feedback = mapping_feedback_state if isinstance(mapping_feedback_state, Mapping) else {}
    convergence = convergence_status if isinstance(convergence_status, Mapping) else {}
    simulation_samples = feedback.get("simulation_samples", []) if isinstance(feedback.get("simulation_samples", []), list) else []
    search_policy_name = (
        str(search_policy_payload.get("policy_name"))
        if isinstance(search_policy_payload, Mapping) and search_policy_payload.get("policy_name")
        else ""
    )
    mapping_policy_name = str(mapping_candidate_records.get("algorithm", "workflow_seeded_beam_local_search_v1"))
    compact_policy_candidates = [
        _compact_search_policy_candidate(candidate)
        for candidate in (search_policy_payload.get("candidates", []) if isinstance(search_policy_payload, Mapping) else [])
        if isinstance(candidate, Mapping)
    ]
    return {
        "schema_version": "dse.step2.search_checkpoint_summary.v1",
        **dict(scope),
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "policy_scope": policy_scope,
        "policy_name": search_policy_name or mapping_policy_name,
        "mapping_policy_name": mapping_policy_name,
        "search_policy_name": search_policy_name or None,
        "search_policy_problem_id": search_policy_payload.get("problem_id") if isinstance(search_policy_payload, Mapping) else None,
        "search_policy_proposal_budget": search_policy_payload.get("proposal_budget") if isinstance(search_policy_payload, Mapping) else None,
        "search_policy_proposed_count": search_policy_payload.get("proposed_count") if isinstance(search_policy_payload, Mapping) else None,
        "search_policy_observed_count": search_policy_payload.get("observed_count") if isinstance(search_policy_payload, Mapping) else None,
        "search_policy_candidates": compact_policy_candidates,
        "search_policy_checkpoint": search_policy_payload.get("checkpoint") if isinstance(search_policy_payload, Mapping) else None,
        "search_policy_feedback": {
            "feedback_update_artifact": "feedback_update.json",
            "calibration_record_artifact": "calibration_record.json",
            "observe_api": "SearchPolicy.observe(candidate_id, metrics)",
            "candidate_id_resolution": [
                "search_policy_candidate_id",
                "mapping_candidate_id",
                "mapping_parameter_hash",
                "parameter_hash",
                "candidate_id",
            ],
            "claim_boundary": (
                "Step4 feedback may update SearchPolicy checkpoint state, but it cannot "
                "admit extra Step3 work unless Campaign budget materializes queue entries."
            ),
        },
        "search_space_artifact": "architecture_search_space.json",
        "search_space_hash": search_space.get("search_space_hash"),
        "candidate_identity_policy": "stable_parameter_hash_sidecar",
        "architecture_candidate_count": len(architecture_candidates),
        "mapping_candidate_count": len(mapping_candidates),
        "candidate_count": len(candidate_summaries),
        "proposed_count": len(candidate_summaries),
        "observed_count": len(simulation_samples),
        "best_candidate_id": best.get("candidate_id") if best else None,
        "selected_candidate_id": mapping_candidate_records.get("selected_candidate_id"),
        "feedback_state_artifact": "mapping_feedback_state.json",
        "feedback_state_summary": {
            "source": (feedback.get("ranking_update", {}) or {}).get("source") if isinstance(feedback.get("ranking_update", {}), Mapping) else None,
            "effect": (feedback.get("ranking_update", {}) or {}).get("effect") if isinstance(feedback.get("ranking_update", {}), Mapping) else None,
            "simulation_budget": dict(feedback.get("simulation_budget", {}) or {}) if isinstance(feedback.get("simulation_budget", {}), Mapping) else {},
        },
        "convergence_status_artifact": "convergence_status.json",
        "convergence_summary": {
            "status": convergence.get("status"),
            "converged": bool(convergence.get("converged", False)),
            "stop_reason": convergence.get("stop_reason"),
        },
        "top_k_candidate_queue_artifact": "top_k_candidate_queue.json",
        "top_k_entry_count": int(top_k_candidate_queue.get("entry_count", 0) or 0),
        "step3_simulation_queue_artifact": "step3_simulation_queue.json",
        "step3_queue_mode": step3_queue.get("queue_mode"),
        "top_k_queue_provenance_only": True,
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "claim_boundary": (
            "Search checkpoint is Step2 candidate/search provenance only; final ranking requires Step3/Step4 evidence."
        ),
        "candidates": candidate_summaries,
    }


def build_step2_search_artifacts(
    *,
    catalog: ArchitectureCatalog,
    workload_package: WorkloadPackage,
    architecture_ids: Sequence[str],
    backend: str,
    objective_directions: Mapping[str, str],
    random_seed: int,
    beam_width: int,
    architecture_candidate_set: Mapping[str, Any],
    mapping_candidate_records: Mapping[str, Any],
    mapping_feedback_state: Optional[Mapping[str, Any]],
    convergence_status: Optional[Mapping[str, Any]],
    low_fidelity_summary: Optional[Mapping[str, Any]],
    promotion_decision: Optional[Mapping[str, Any]],
    step3_queue: Mapping[str, Any],
    scope: Mapping[str, str],
    policy_scope: str,
) -> Dict[str, Any]:
    """Return canonical Step2 search/provenance artifacts.

    These artifacts are deliberately redundant with legacy Step2 handoff files:
    they provide the canonical replay/audit surface required by the research
    control plane while older JSON files remain compatibility inputs for
    existing Step3 tests.
    """

    search_space = build_architecture_search_space_artifact(
        catalog,
        workload_package=workload_package,
        architecture_ids=architecture_ids,
        backend=backend,
        objective_directions=objective_directions,
        random_seed=random_seed,
        beam_width=beam_width,
        policy_scope=policy_scope,
        scope=scope,
    )
    search_policy_architecture_id = str(
        (promotion_decision or {}).get("architecture_id")
        or (architecture_ids[0] if architecture_ids else "")
    )
    search_policy_payload = _build_step2_search_policy_payload(
        workload_package=workload_package,
        mapping_candidate_records=mapping_candidate_records,
        scope=scope,
        backend=backend,
        architecture_id=search_policy_architecture_id,
        objective_directions=objective_directions,
        beam_width=beam_width,
        step3_queue=step3_queue,
    )
    search_space = _search_space_with_policy(search_space, search_policy_payload)
    search_policy_by_mapping_id = _search_policy_candidate_lookup(search_policy_payload)
    architecture_candidates = [
        dict(candidate)
        for candidate in architecture_candidate_set.get("candidates", []) or []
        if isinstance(candidate, Mapping)
    ]
    mapping_candidates: List[Dict[str, Any]] = []
    mapping_policy_name = str(mapping_candidate_records.get("algorithm", "workflow_seeded_beam_local_search_v1"))
    for index, record in enumerate(mapping_candidate_records.get("candidates", []) or []):
        if not isinstance(record, Mapping):
            continue
        candidate_id = str(record.get("candidate_id", f"mapping_candidate_{index}"))
        architecture_id = str(record.get("architecture_id") or (promotion_decision or {}).get("architecture_id") or "")
        mapping = dict(record.get("mapping", {}) or {})
        parameters = {
            "architecture_id": architecture_id,
            "backend": backend,
            "mapping": mapping,
            "mapping_policy": mapping_policy_name,
        }
        provenance = {
            "source_artifact": "mapping_candidate_records.json",
            "source_index": index,
            "algorithm": mapping_candidate_records.get("algorithm"),
            "beam_width": mapping_candidate_records.get("beam_width"),
        }
        search_policy_candidate = search_policy_by_mapping_id.get(candidate_id, {})
        row: Dict[str, Any] = {
            "schema_version": "dse.step2.mapping_candidate_record.v1",
            **dict(scope),
            "workload_id": workload_package.workload_id,
            "workload_family": workload_package.workload_family,
            "candidate_id": candidate_id,
            "architecture_id": architecture_id,
            "mapping": mapping,
            "parameters": parameters,
            "parameter_hash": _payload_sha256(parameters),
            "candidate_identity_policy": "stable_mapping_parameters_hash_sidecar",
            "provenance": provenance,
            "generation_reason": str(record.get("selection_reason") or record.get("state") or "mapping_search_candidate"),
            "score": _candidate_priority_score(record),
            "step2_screenable": not bool(record.get("violations")),
            "step3_evaluable": bool((promotion_decision or {}).get("promoted_for_simulation", False) and candidate_id == (promotion_decision or {}).get("candidate_id")),
            "simulation_eligible": bool((promotion_decision or {}).get("promoted_for_simulation", False) and candidate_id == (promotion_decision or {}).get("candidate_id")),
            "simulation_blockers": [] if bool((promotion_decision or {}).get("promoted_for_simulation", False) and candidate_id == (promotion_decision or {}).get("candidate_id")) else ["not_selected_for_step3_simulation"],
            "promotion_reasons": [
                str(reason.get("reason_id") if isinstance(reason, Mapping) else reason)
                for reason in (promotion_decision or {}).get("reasons", []) or []
                if isinstance(reason, (Mapping, str))
            ] if candidate_id == (promotion_decision or {}).get("candidate_id") else [],
            "blocker_reasons": [str(item) for item in record.get("violations", []) or []],
            "trusted_final_claim": False,
        }
        if search_policy_candidate:
            search_policy_compact = _compact_search_policy_candidate(search_policy_candidate)
            provenance["search_policy"] = search_policy_compact
            row.update({
                "search_policy_name": search_policy_payload.get("policy_name"),
                "search_policy_candidate_id": search_policy_compact.get("candidate_id"),
                "search_policy_rank": search_policy_compact.get("search_policy_rank"),
                "search_policy_parameter_hash": search_policy_compact.get("parameter_hash"),
                "search_policy_generation_reason": search_policy_compact.get("generation_reason"),
                "search_policy": search_policy_compact,
            })
        mapping_candidates.append(row)
    promoted_mapping_ids = {
        str(candidate.get("candidate_id"))
        for candidate in mapping_candidates
        if candidate.get("simulation_eligible")
    }
    screening_results = [
        {
            "schema_version": "dse.step2.screening_result_record.v1",
            **dict(scope),
            "workload_id": workload_package.workload_id,
            "workload_family": workload_package.workload_family,
            "candidate_id": str(candidate.get("candidate_id")),
            "architecture_id": str(candidate.get("architecture_id", "")),
            "screening_stage": "architecture_screening",
            "passed": bool(candidate.get("step2_screenable", False)),
            "step2_screenable": bool(candidate.get("step2_screenable", False)),
            "step3_evaluable": bool(candidate.get("step3_evaluable", False)),
            "simulation_eligible": bool(candidate.get("simulation_eligible", False)),
            "simulation_blockers": list(candidate.get("simulation_blockers", []) or []),
            "blocker_reasons": list(candidate.get("candidate_only_reasons", []) or []),
            "evidence_refs": ["architecture_candidate_set.json"],
            "trusted_final_claim": False,
        }
        for candidate in architecture_candidates
    ]
    if low_fidelity_summary:
        screening_results.append({
            "schema_version": "dse.step2.screening_result_record.v1",
            **dict(scope),
            "workload_id": workload_package.workload_id,
            "workload_family": workload_package.workload_family,
            "candidate_id": str((promotion_decision or {}).get("candidate_id") or "selected_mapping"),
            "architecture_id": str((promotion_decision or {}).get("architecture_id") or ""),
            "screening_stage": "low_fidelity_screening",
            "passed": bool(low_fidelity_summary.get("passed", False)),
            "step2_screenable": bool(low_fidelity_summary.get("passed", False)),
            "step3_evaluable": bool((promotion_decision or {}).get("promoted_for_simulation", False)),
            "simulation_eligible": bool((promotion_decision or {}).get("promoted_for_simulation", False)),
            "simulation_blockers": [] if bool((promotion_decision or {}).get("promoted_for_simulation", False)) else [
                str(blocker.get("reason_id", blocker))
                for blocker in low_fidelity_summary.get("blockers", []) or []
            ],
            "blocker_reasons": list(low_fidelity_summary.get("blockers", []) or []),
            "evidence_refs": list(low_fidelity_summary.get("required_artifacts", []) or STEP2_LOW_FIDELITY_ARTIFACTS),
            "trusted_final_claim": False,
        })
    promotion_records = [
        {
            "schema_version": "dse.step2.promotion_decision_record.v1",
            **dict(scope),
            "workload_id": workload_package.workload_id,
            "workload_family": workload_package.workload_family,
            "candidate_id": str((promotion_decision or {}).get("candidate_id") or "selected_mapping"),
            "mapping_id": str((promotion_decision or {}).get("mapping_id") or ""),
            "architecture_id": str((promotion_decision or {}).get("architecture_id") or ""),
            "decision": "promote" if bool((promotion_decision or {}).get("promoted_for_simulation", False)) else "block",
            "promoted_for_simulation": bool((promotion_decision or {}).get("promoted_for_simulation", False)),
            "reasons": [
                str(reason.get("reason_id") if isinstance(reason, Mapping) else reason)
                for reason in (promotion_decision or {}).get("reasons", []) or []
                if isinstance(reason, (Mapping, str))
            ],
            "required_evidence": list((promotion_decision or {}).get("required_evidence", []) or []),
            "queue_artifact": "step3_simulation_queue.json",
            "trusted_final_claim": False,
        }
    ] if promotion_decision else []
    top_k_candidate_queue = build_top_k_candidate_queue(
        workload_package=workload_package,
        mapping_candidate_records=mapping_candidate_records,
        mapping_candidates=mapping_candidates,
        promotion_decision=promotion_decision,
        step3_queue=step3_queue,
        scope=scope,
        policy_scope=policy_scope,
        beam_width=beam_width,
        search_policy_payload=search_policy_payload,
    )
    candidate_generation_report = {
        "schema_version": "dse.step2.architecture_candidate_generation_report.v1",
        **dict(scope),
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "search_space_artifact": "architecture_search_space.json",
        "search_space_hash": search_space["search_space_hash"],
        "policy_scope": policy_scope,
        "architecture_candidate_count": len(architecture_candidates),
        "mapping_candidate_count": len(mapping_candidates),
        "generated_candidate_ids": [str(candidate.get("candidate_id")) for candidate in architecture_candidates],
        "mapping_candidate_ids": [str(candidate.get("candidate_id")) for candidate in mapping_candidates],
        "candidate_identity_policy": "stable_parameter_hash_sidecar",
        "search_policy_name": search_policy_payload.get("policy_name"),
        "search_policy_problem_id": search_policy_payload.get("problem_id"),
        "search_policy_budget": search_policy_payload.get("proposal_budget"),
        "search_policy_proposed_count": search_policy_payload.get("proposed_count"),
        "search_policy_candidate_count": len(search_policy_payload.get("candidates", []) or []),
        "search_policy_candidate_ids": [
            str(candidate.get("candidate_id"))
            for candidate in search_policy_payload.get("candidates", []) or []
            if isinstance(candidate, Mapping) and candidate.get("candidate_id")
        ],
        "search_policy_provenance_only": True,
        "architecture_candidate_parameter_hashes": [
            str(candidate.get("parameter_hash"))
            for candidate in architecture_candidates
            if candidate.get("parameter_hash")
        ],
        "mapping_candidate_parameter_hashes": [
            str(candidate.get("parameter_hash"))
            for candidate in mapping_candidates
            if candidate.get("parameter_hash")
        ],
        "all_generated_candidates_have_parameter_hash": all(
            candidate.get("parameter_hash") for candidate in architecture_candidates
        ) and all(candidate.get("parameter_hash") for candidate in mapping_candidates),
        "search_checkpoint_artifact": "search_checkpoint.json",
        "top_k_candidate_queue_artifact": "top_k_candidate_queue.json",
        "top_k_candidate_count": int(top_k_candidate_queue.get("entry_count", 0) or 0),
        "generation_provenance": {
            "architecture_source": "architecture_catalog.json",
            "mapping_source": "mapping_candidate_records.json",
            "checkpoint_artifact": "search_checkpoint.json",
            "top_k_candidate_queue_artifact": "top_k_candidate_queue.json",
            "jsonl_artifacts": ["mapping_candidates.jsonl"],
            "candidate_identity_policy": "stable_parameter_hash_sidecar",
            "search_policy": {
                "policy_name": search_policy_payload.get("policy_name"),
                "problem_id": search_policy_payload.get("problem_id"),
                "proposal_budget": search_policy_payload.get("proposal_budget"),
                "proposed_count": search_policy_payload.get("proposed_count"),
                "candidate_source_artifact": search_policy_payload.get("candidate_source_artifact"),
                "step3_admission_queue": search_policy_payload.get("step3_simulation_queue_artifact"),
                "top_k_queue_role": search_policy_payload.get("top_k_queue_role"),
            },
        },
        "trial_state_ledger_artifact": "trial_state_ledger.json",
        "trusted_final_claim": False,
    }
    architecture_screening_report = {
        "schema_version": "dse.step2.architecture_screening_report.v1",
        **dict(scope),
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "screened_candidate_count": len(screening_results),
        "promoted_candidate_count": len(promoted_mapping_ids),
        "promotion_decision_artifact": "promotion_decisions.jsonl",
        "screening_results_artifact": "screening_results.jsonl",
        "step3_simulation_queue_artifact": "step3_simulation_queue.json",
        "trial_state_ledger_artifact": "trial_state_ledger.json",
        "search_checkpoint_artifact": "search_checkpoint.json",
        "top_k_candidate_queue_artifact": "top_k_candidate_queue.json",
        "step3_queue_entry_count": int(step3_queue.get("entry_count", 0) or 0),
        "top_k_provenance_entry_count": int(top_k_candidate_queue.get("entry_count", 0) or 0),
        "top_k_queue_mode": top_k_candidate_queue.get("queue_mode"),
        "top_k_queue_provenance_only": True,
        "search_policy_name": search_policy_payload.get("policy_name"),
        "search_policy_problem_id": search_policy_payload.get("problem_id"),
        "search_policy_proposed_count": search_policy_payload.get("proposed_count"),
        "search_policy_provenance_only": True,
        "trusted_final_claim": False,
        "claim_boundary": "Step2 screening/promotions only; final trust requires Step3/Step4 evidence.",
    }
    trial_state_ledger = build_step2_trial_state_ledger(
        workload_package=workload_package,
        architecture_candidates=architecture_candidates,
        mapping_candidates=mapping_candidates,
        screening_results=screening_results,
        promotion_decisions=promotion_records,
        step3_queue=step3_queue,
        search_space=search_space,
        scope=scope,
        policy_scope=policy_scope,
    )
    search_checkpoint = build_step2_search_checkpoint_artifact(
        workload_package=workload_package,
        search_space=search_space,
        architecture_candidates=architecture_candidates,
        mapping_candidates=mapping_candidates,
        mapping_candidate_records=mapping_candidate_records,
        mapping_feedback_state=mapping_feedback_state,
        convergence_status=convergence_status,
        top_k_candidate_queue=top_k_candidate_queue,
        step3_queue=step3_queue,
        scope=scope,
        policy_scope=policy_scope,
        search_policy_payload=search_policy_payload,
    )
    return {
        "architecture_search_space": search_space,
        "search_checkpoint": search_checkpoint,
        "top_k_candidate_queue": top_k_candidate_queue,
        "architecture_candidate_generation_report": candidate_generation_report,
        "architecture_screening_report": architecture_screening_report,
        "trial_state_ledger": trial_state_ledger,
        "mapping_candidates_jsonl": mapping_candidates,
        "screening_results_jsonl": screening_results,
        "promotion_decisions_jsonl": promotion_records,
    }


def _screening_architecture_candidate_set(
    *,
    workload_package: WorkloadPackage,
    records: Sequence[Mapping[str, Any]],
    backend: str,
) -> Dict[str, Any]:
    candidates = []
    for record in records:
        architecture_id = str(record.get("architecture_id", ""))
        eligibility_fields = _step2_eligibility_fields(
            step3_searchable=bool(record.get("step3_searchable", record.get("step3_evaluable", False))),
            step3_blockers=list(record.get("step3_search_blockers", record.get("simulation_blockers", [])) or []),
            promoted_for_simulation=bool(record.get("promoted_for_simulation", False)),
        )
        candidate_parameters = {
            "architecture_id": architecture_id,
            "architecture_family": record.get("architecture_family"),
            "backend": backend,
            "selected_mapping_candidate_id": record.get("selected_candidate_id"),
        }
        candidates.append({
            "candidate_id": f"architecture::{architecture_id}",
            "architecture_id": architecture_id,
            "architecture_family": record.get("architecture_family"),
            "parameters": candidate_parameters,
            "parameter_hash": _payload_sha256(candidate_parameters),
            "candidate_identity_policy": "stable_architecture_id_with_parameter_hash_sidecar",
            "architecture_run_dir": record.get("run_dir"),
            "selected_for_step2_mapping": True,
            "selected_mapping_candidate_id": record.get("selected_candidate_id"),
            "design_point_id": record.get("design_point_id"),
            "promoted_for_simulation": bool(record.get("promoted_for_simulation", False)),
            "step3_searchable": bool(record.get("step3_searchable", False)),
            "step3_search_blockers": list(record.get("step3_search_blockers", []) or []),
            **eligibility_fields,
            "step4_eligible": bool(record.get("step4_eligible", False)),
            "candidate_only_reasons": list(record.get("candidate_only_reasons", []) or []),
            "artifact_validation_valid": bool(record.get("artifact_validation_valid", False)),
            "policy_added": False,
            "domain_policy": None,
            "trusted_final_claim": False,
        })
    return {
        "schema_version": "dse.step2.architecture_candidate_set.v1",
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "backend": backend,
        "selected_architecture_id": None,
        "selected_mapping_candidate_id": None,
        "candidate_count": len(candidates),
        "queue_artifact": "step3_simulation_queue.json",
        "trusted_final_claim": False,
        "policy_scope": "architecture_screening",
        "candidates": candidates,
        "notes": [
            "Architecture-screening mode preserves one selected mapping/design-point entry per architecture run.",
            "Step2 screening records are candidate-generation signals only; final ranking requires Step3+ evidence.",
        ],
    }


def _screening_step3_queue(
    *,
    workload_package: WorkloadPackage,
    child_results: Sequence[Step2WorkflowResult],
    records: Sequence[Mapping[str, Any]],
    backend: str,
) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    for result, record in zip(child_results, records):
        queue = result.artifacts.get("step3_simulation_queue", {}) if isinstance(result.artifacts.get("step3_simulation_queue", {}), Mapping) else {}
        for raw_entry in queue.get("entries", []) or []:
            if not isinstance(raw_entry, Mapping):
                continue
            entry = dict(raw_entry)
            entry["architecture_run_dir"] = record.get("run_dir")
            entry["queue_entry_id"] = f"screening::{entry.get('architecture_id')}::{entry.get('mapping_candidate_id')}"
            entry["claim_status"] = "legacy_pilot_only"
            entry["retention_policy"] = "legacy_pilot_regression_only"
            entry["release_completion_eligible"] = False
            entry["blocked_claims"] = ["step2_full_dse_complete", "deliverable_complete"]
            entry["claim_boundary"] = (
                "Selected-entry queues and local regression tests are pilot/replay evidence only; "
                "they cannot establish Step2 full-DSE completion."
            )
            entries.append(entry)
    return {
        "schema_version": "dse.step3.simulation_queue.v1",
        "queue_mode": "selected-entry-only",
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "backend": backend,
        "entry_count": len(entries),
        "claim_status": "legacy_pilot_only",
        "retention_policy": "legacy_pilot_regression_only",
        "release_completion_eligible": False,
        "blocked_claims": ["step2_full_dse_complete", "deliverable_complete"],
        "claim_boundary": (
            "Selected-entry queues and local regression tests are pilot/replay evidence only; "
            "they cannot establish Step2 full-DSE completion."
        ),
        "trusted_final_claim": False,
        "top_k_queue_deferred": True,
        "entries": entries,
        "notes": [
            "Architecture-screening queue contains one selected entry per per-architecture Step2 run.",
            "Queue metadata cannot override each child mapping_promotion_decision.promoted_for_simulation=false.",
        ],
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

    architecture_candidate_set = artifacts.get("architecture_candidate_set", {})
    if isinstance(architecture_candidate_set, Mapping) and architecture_candidate_set:
        if architecture_candidate_set.get("trusted_final_claim"):
            errors.append({"field": "architecture_candidate_set.trusted_final_claim", "message": "Step2 architecture candidates cannot claim trusted final winners"})
        selected_architecture_id = architecture_candidate_set.get("selected_architecture_id")
        if selected_architecture_id and architecture.get("architecture_id") and selected_architecture_id != architecture.get("architecture_id"):
            errors.append({
                "field": "architecture_candidate_set.selected_architecture_id",
                "message": "architecture candidate set must identify the selected architecture artifact",
                "selected_architecture_id": selected_architecture_id,
                "architecture_id": architecture.get("architecture_id"),
            })
        for idx, candidate in enumerate(architecture_candidate_set.get("candidates", []) or []):
            if not isinstance(candidate, Mapping):
                errors.append({"field": f"architecture_candidate_set.candidates[{idx}]", "message": "architecture candidate record must be an object"})
                continue
            if candidate.get("trusted_final_claim"):
                errors.append({"field": f"architecture_candidate_set.candidates[{idx}].trusted_final_claim", "message": "architecture candidate records cannot claim trusted final winners"})

    step3_queue = artifacts.get("step3_simulation_queue", {})
    if isinstance(step3_queue, Mapping) and step3_queue:
        if step3_queue.get("trusted_final_claim"):
            errors.append({"field": "step3_simulation_queue.trusted_final_claim", "message": "Step2 queue cannot claim trusted final winners"})
        entries = step3_queue.get("entries", []) or []
        if step3_queue.get("queue_mode") != "selected-entry-only":
            errors.append({"field": "step3_simulation_queue.queue_mode", "message": "Step3 queue v1 must remain selected-entry-only"})
        if len(entries) != int(step3_queue.get("entry_count", len(entries)) or 0):
            errors.append({"field": "step3_simulation_queue.entry_count", "message": "entry_count must match entries length"})
        for idx, entry in enumerate(entries):
            if not isinstance(entry, Mapping):
                errors.append({"field": f"step3_simulation_queue.entries[{idx}]", "message": "queue entry must be an object"})
                continue
            if entry.get("trusted_final_claim"):
                errors.append({"field": f"step3_simulation_queue.entries[{idx}].trusted_final_claim", "message": "queue entries cannot claim trusted final winners"})
            if promotion.get("promoted_for_simulation") is False and str(entry.get("queue_state", "")).startswith("scheduled_for_simulation"):
                errors.append({
                    "field": f"step3_simulation_queue.entries[{idx}].queue_state",
                    "message": "queue metadata cannot schedule a candidate when mapping_promotion_decision.promoted_for_simulation is false",
                    "queue_state": entry.get("queue_state"),
                })
            if entry.get("design_point_id") and isinstance(artifacts.get("design_point", {}), Mapping):
                expected_design_point = artifacts["design_point"].get("design_point_id")
                if expected_design_point and entry.get("design_point_id") != expected_design_point:
                    errors.append({
                        "field": f"step3_simulation_queue.entries[{idx}].design_point_id",
                        "message": "queue entry design point must match design_point.json",
                    })
            if entry.get("mapping_id") and promotion.get("mapping_id") and entry.get("mapping_id") != promotion.get("mapping_id"):
                errors.append({
                    "field": f"step3_simulation_queue.entries[{idx}].mapping_id",
                    "message": "queue entry mapping_id must match mapping_promotion_decision.json",
                })
            if entry.get("architecture_id") and architecture.get("architecture_id") and entry.get("architecture_id") != architecture.get("architecture_id"):
                errors.append({
                    "field": f"step3_simulation_queue.entries[{idx}].architecture_id",
                    "message": "queue entry architecture_id must match architecture.json",
                })

    top_k_queue = artifacts.get("top_k_candidate_queue", {})
    if isinstance(top_k_queue, Mapping) and top_k_queue:
        if top_k_queue.get("trusted_final_claim"):
            errors.append({"field": "top_k_candidate_queue.trusted_final_claim", "message": "Top-K provenance queue cannot claim trusted final winners"})
        if top_k_queue.get("release_completion_eligible"):
            errors.append({"field": "top_k_candidate_queue.release_completion_eligible", "message": "Top-K provenance queue cannot establish release completion"})
        if top_k_queue.get("top_k_or_representative_completion_allowed"):
            errors.append({"field": "top_k_candidate_queue.top_k_or_representative_completion_allowed", "message": "Top-K or representative subsets cannot satisfy full DSE completion"})
        if top_k_queue.get("queue_mode") != "top-k-provenance-only":
            errors.append({"field": "top_k_candidate_queue.queue_mode", "message": "Top-K artifact must remain provenance-only and separate from Step3 queue"})
        if top_k_queue.get("step3_simulation_queue_artifact") not in {None, "", "step3_simulation_queue.json"}:
            errors.append({"field": "top_k_candidate_queue.step3_simulation_queue_artifact", "message": "Top-K provenance must cite the canonical Step3 queue artifact"})
        if step3_queue and top_k_queue.get("step3_queue_mode") != step3_queue.get("queue_mode"):
            errors.append({"field": "top_k_candidate_queue.step3_queue_mode", "message": "Top-K provenance must not redefine Step3 queue semantics"})
        top_k_entries = top_k_queue.get("entries", []) or []
        if len(top_k_entries) != int(top_k_queue.get("entry_count", len(top_k_entries)) or 0):
            errors.append({"field": "top_k_candidate_queue.entry_count", "message": "Top-K entry_count must match entries length"})
        for idx, entry in enumerate(top_k_entries):
            if not isinstance(entry, Mapping):
                errors.append({"field": f"top_k_candidate_queue.entries[{idx}]", "message": "Top-K entry must be an object"})
                continue
            if entry.get("trusted_final_claim"):
                errors.append({"field": f"top_k_candidate_queue.entries[{idx}].trusted_final_claim", "message": "Top-K entries cannot claim trusted final winners"})
            if entry.get("release_completion_eligible"):
                errors.append({"field": f"top_k_candidate_queue.entries[{idx}].release_completion_eligible", "message": "Top-K entries cannot establish release completion"})
            if entry.get("top_k_or_representative_completion_allowed"):
                errors.append({"field": f"top_k_candidate_queue.entries[{idx}].top_k_or_representative_completion_allowed", "message": "Top-K entries cannot satisfy full DSE completion"})
            if not entry.get("parameter_hash"):
                errors.append({"field": f"top_k_candidate_queue.entries[{idx}].parameter_hash", "message": "Top-K entries require stable parameter_hash sidecars"})
            if str(entry.get("queue_state", "")).startswith("scheduled_for_simulation"):
                errors.append({"field": f"top_k_candidate_queue.entries[{idx}].queue_state", "message": "Top-K provenance entries must not masquerade as Step3 queue entries"})

    search_checkpoint = artifacts.get("search_checkpoint", {})
    if isinstance(search_checkpoint, Mapping) and search_checkpoint:
        if search_checkpoint.get("trusted_final_claim"):
            errors.append({"field": "search_checkpoint.trusted_final_claim", "message": "Search checkpoint cannot claim trusted final winners"})
        if search_checkpoint.get("release_completion_eligible"):
            errors.append({"field": "search_checkpoint.release_completion_eligible", "message": "Search checkpoint cannot establish release completion"})
        if search_checkpoint.get("top_k_queue_provenance_only") is not True:
            errors.append({"field": "search_checkpoint.top_k_queue_provenance_only", "message": "Search checkpoint must mark Top-K queue as provenance-only"})
        checkpoint_candidates = search_checkpoint.get("candidates", []) or []
        if len(checkpoint_candidates) != int(search_checkpoint.get("candidate_count", len(checkpoint_candidates)) or 0):
            errors.append({"field": "search_checkpoint.candidate_count", "message": "Search checkpoint candidate_count must match candidates length"})
        if step3_queue and search_checkpoint.get("step3_queue_mode") != step3_queue.get("queue_mode"):
            errors.append({"field": "search_checkpoint.step3_queue_mode", "message": "Search checkpoint must not redefine Step3 queue semantics"})
        for idx, candidate in enumerate(checkpoint_candidates):
            if not isinstance(candidate, Mapping):
                errors.append({"field": f"search_checkpoint.candidates[{idx}]", "message": "Search checkpoint candidate must be an object"})
                continue
            if candidate.get("trusted_final_claim"):
                errors.append({"field": f"search_checkpoint.candidates[{idx}].trusted_final_claim", "message": "Search checkpoint candidates cannot claim trusted final winners"})
            if not candidate.get("parameter_hash"):
                errors.append({"field": f"search_checkpoint.candidates[{idx}].parameter_hash", "message": "Search checkpoint candidates require stable parameter_hash sidecars"})
        search_policy_checkpoint = search_checkpoint.get("search_policy_checkpoint", {})
        if isinstance(search_policy_checkpoint, Mapping) and search_policy_checkpoint:
            if search_policy_checkpoint.get("trusted_final_claim"):
                errors.append({"field": "search_checkpoint.search_policy_checkpoint.trusted_final_claim", "message": "Search policy checkpoint cannot claim trusted final winners"})
            if search_policy_checkpoint.get("release_completion_eligible"):
                errors.append({"field": "search_checkpoint.search_policy_checkpoint.release_completion_eligible", "message": "Search policy checkpoint cannot establish release completion"})
            policy_candidates = search_policy_checkpoint.get("candidates", []) or []
            if len(policy_candidates) != int(search_policy_checkpoint.get("candidate_count", len(policy_candidates)) or 0):
                errors.append({"field": "search_checkpoint.search_policy_checkpoint.candidate_count", "message": "Search policy checkpoint candidate_count must match candidates length"})
            for idx, candidate in enumerate(policy_candidates):
                if not isinstance(candidate, Mapping):
                    errors.append({"field": f"search_checkpoint.search_policy_checkpoint.candidates[{idx}]", "message": "Search policy checkpoint candidate must be an object"})
                    continue
                if candidate.get("trusted_final_claim"):
                    errors.append({"field": f"search_checkpoint.search_policy_checkpoint.candidates[{idx}].trusted_final_claim", "message": "Search policy checkpoint candidates cannot claim trusted final winners"})
                if not candidate.get("parameter_hash"):
                    errors.append({"field": f"search_checkpoint.search_policy_checkpoint.candidates[{idx}].parameter_hash", "message": "Search policy checkpoint candidates require stable parameter_hash sidecars"})

    trial_ledger = artifacts.get("trial_state_ledger", {})
    if isinstance(trial_ledger, Mapping) and trial_ledger:
        if trial_ledger.get("trusted_final_claim"):
            errors.append({"field": "trial_state_ledger.trusted_final_claim", "message": "Step2 Trial ledger cannot claim trusted final winners"})
        if trial_ledger.get("release_completion_eligible"):
            errors.append({"field": "trial_state_ledger.release_completion_eligible", "message": "Step2 Trial ledger cannot establish release completion"})
        if step3_queue and trial_ledger.get("queue_mode") != step3_queue.get("queue_mode"):
            errors.append({"field": "trial_state_ledger.queue_mode", "message": "Trial ledger queue_mode must match step3_simulation_queue.queue_mode"})
        candidates = trial_ledger.get("candidates", []) or []
        if len(candidates) != int(trial_ledger.get("candidate_count", len(candidates)) or 0):
            errors.append({"field": "trial_state_ledger.candidate_count", "message": "candidate_count must match Trial ledger candidate rows"})
        expected_arch_count = len(architecture_candidate_set.get("candidates", []) or []) if isinstance(architecture_candidate_set, Mapping) else 0
        if expected_arch_count and int(trial_ledger.get("architecture_candidate_count", expected_arch_count) or 0) != expected_arch_count:
            errors.append({
                "field": "trial_state_ledger.architecture_candidate_count",
                "message": "Trial ledger architecture count must match architecture_candidate_set",
            })
        mapping_candidates = artifacts.get("mapping_candidates_jsonl", [])
        expected_mapping_count = len(mapping_candidates) if isinstance(mapping_candidates, (list, tuple)) else 0
        if expected_mapping_count and int(trial_ledger.get("mapping_candidate_count", expected_mapping_count) or 0) != expected_mapping_count:
            errors.append({
                "field": "trial_state_ledger.mapping_candidate_count",
                "message": "Trial ledger mapping count must match mapping_candidates.jsonl",
            })
        if candidates and not trial_ledger.get("all_candidates_have_parameter_hash", False):
            errors.append({
                "field": "trial_state_ledger.all_candidates_have_parameter_hash",
                "message": "Trial ledger candidate rows require stable parameter_hash sidecars",
            })
        for idx, row in enumerate(candidates):
            if not isinstance(row, Mapping):
                errors.append({"field": f"trial_state_ledger.candidates[{idx}]", "message": "Trial ledger row must be an object"})
                continue
            if row.get("trusted_final_claim"):
                errors.append({"field": f"trial_state_ledger.candidates[{idx}].trusted_final_claim", "message": "Trial ledger rows cannot claim trusted final winners"})
            if not row.get("parameter_hash"):
                errors.append({"field": f"trial_state_ledger.candidates[{idx}].parameter_hash", "message": "Trial ledger rows require parameter_hash"})
            if row.get("trial_state") == "queued_for_step3" and not row.get("promoted_for_simulation"):
                errors.append({
                    "field": f"trial_state_ledger.candidates[{idx}].trial_state",
                    "message": "Trial ledger cannot mark an unpromoted candidate as queued_for_step3",
                })
    elif isinstance(artifacts.get("architecture_candidate_set", {}), Mapping) and artifacts.get("architecture_candidate_set"):
        errors.append({
            "field": "trial_state_ledger",
            "message": "Trial ledger missing; Step2 search provenance is scattered across candidate/queue artifacts",
        })
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


def _lowering_from_step1_or_recompute(
    *,
    workload_package: WorkloadPackage,
    source_graph: ComputeGraph,
    executable_graph: Optional[ComputeGraph],
    graph_lowering_report: Optional[Mapping[str, Any]],
    step1_handoff_summary: Optional[Mapping[str, Any]],
) -> GraphLoweringResult:
    """Use a consistent persisted Step1 lowering, otherwise recompute visibly."""
    replay: Dict[str, Any] = {
        "schema_version": "dse.step2.replay_metadata.v1",
        "source": "direct_package_call",
        "recomputed_from_package": True,
        "persisted_step1_handoff_used": False,
    }
    if step1_handoff_summary is not None:
        replay["source"] = "step1_handoff_fallback_recompute"
        replay["step1_handoff_summary"] = dict(step1_handoff_summary)

    if graph_lowering_report is not None and executable_graph is not None:
        report = dict(graph_lowering_report)
        expected_source = str(report.get("source_graph_id", ""))
        expected_executable = str(report.get("executable_graph_id", ""))
        consistent = (
            expected_source == source_graph.graph_id
            and expected_executable == executable_graph.graph_id
            and report.get("status") != "unsupported"
        )
        if consistent:
            report["step2_replay"] = {
                "schema_version": "dse.step2.replay_metadata.v1",
                "source": "persisted_step1_handoff",
                "recomputed_from_package": False,
                "persisted_step1_handoff_used": True,
                "step1_handoff_summary": dict(step1_handoff_summary or {}),
            }
            return GraphLoweringResult(report=report, executable_graph=executable_graph)
        replay["persisted_step1_handoff_used"] = False
        replay["persisted_inconsistency"] = {
            "report_source_graph_id": expected_source,
            "actual_source_graph_id": source_graph.graph_id,
            "report_executable_graph_id": expected_executable,
            "actual_executable_graph_id": executable_graph.graph_id,
            "report_status": report.get("status"),
        }

    lowering = lower_compute_graph(source_graph, workload_package)
    lowering.report["step2_replay"] = replay
    return lowering


def _merge_policy_hints(hints: Sequence[Step2CandidateHints]) -> Optional[Dict[str, Any]]:
    matched = [hint for hint in hints if hint.matched]
    if not matched:
        return None
    payloads = [hint.to_dict() for hint in matched]
    policy_ids = [str(payload["policy_id"]) for payload in payloads]
    domain_keys = sorted({str(payload["domain_key"]) for payload in payloads})
    review_flags = sorted({flag for payload in payloads for flag in payload.get("review_flags", [])})
    hard_block_flags = sorted({flag for payload in payloads for flag in payload.get("hard_block_flags", [])})
    review_required_flags = sorted({flag for payload in payloads for flag in payload.get("review_required_flags", [])})

    def _merged_list(key: str) -> List[Dict[str, Any]]:
        values: List[Dict[str, Any]] = []
        for payload in payloads:
            for item in payload.get(key, []) or []:
                if isinstance(item, Mapping):
                    values.append(dict(item))
        return values

    node_target_preferences: Dict[str, List[str]] = {}
    for payload in payloads:
        raw_preferences = payload.get("node_target_preferences", {})
        if not isinstance(raw_preferences, Mapping):
            continue
        for node_id, preferences in raw_preferences.items():
            existing = node_target_preferences.setdefault(str(node_id), [])
            for target in _string_list(preferences):
                if target not in existing:
                    existing.append(target)

    merged: Dict[str, Any] = {
        "schema_version": "dse.step2.domain_policy_hints.v1",
        "policy_id": policy_ids[0] if len(policy_ids) == 1 else "multi_domain_policy",
        "domain_key": domain_keys[0] if len(domain_keys) == 1 else "multi_domain",
        "matched": True,
        "policies": payloads,
        "policy_ids": policy_ids,
        "domain_keys": domain_keys,
        "domain_policy": {
            "policy_id": policy_ids[0] if len(policy_ids) == 1 else "multi_domain_policy",
            "domain_key": domain_keys[0] if len(domain_keys) == 1 else "multi_domain",
            "matched": True,
        },
        "review_flags": review_flags,
        "hard_block_flags": hard_block_flags,
        "review_required_flags": review_required_flags,
        "review_required": bool(review_flags or hard_block_flags or review_required_flags),
        "hard_blocked": bool(hard_block_flags),
        "claim_boundary": "candidate_only",
        "trusted_final_claim": False,
    }
    for key in ("architecture_candidates", "architecture_preferences", "mapping_seeds"):
        values = _merged_list(key)
        if values:
            merged[key] = values
    if node_target_preferences:
        merged["node_target_preferences"] = node_target_preferences

    if len(payloads) == 1:
        single = payloads[0]
        for key in ("data_placement", "runtime_schedule", "descriptor_protocol", "memory_policy", "step3_queue", "annotations"):
            value = single.get(key)
            if isinstance(value, Mapping) and value:
                merged[key] = dict(value)
    else:
        merged["annotations"] = {
            "policy_annotations": {
                str(payload.get("policy_id", index)): dict(payload.get("annotations", {}) or {})
                for index, payload in enumerate(payloads)
                if isinstance(payload.get("annotations"), Mapping) and payload.get("annotations")
            }
        }
    return merged


def _merge_candidate_hints(
    candidate_hints: Optional[Mapping[str, Any]],
    policy_hints: Sequence[Step2CandidateHints],
) -> Optional[Dict[str, Any]]:
    """Return the Step2 candidate-hint payload consumed by generic mapping.

    ``candidate_hints`` is the legacy/direct injection path used by tests and
    hand-authored callers.  Static domain policies use ``policy_hints``.  Keep
    the direct payload shape intact when it is the only source so existing
    consumers can still read fields such as ``policy_id`` at the top level.
    """

    direct_payload = dict(candidate_hints) if isinstance(candidate_hints, Mapping) and candidate_hints else None
    policy_payload = _merge_policy_hints(policy_hints)
    if direct_payload is None:
        return policy_payload
    direct_payload.setdefault("trusted_final_claim", False)
    if policy_payload is None:
        return direct_payload
    merged = dict(direct_payload)
    merged.setdefault("schema_version", str(direct_payload.get("schema_version") or "dse.step2.candidate_hints.v1"))
    merged["policy_hints"] = policy_payload
    if isinstance(policy_payload.get("node_target_preferences"), Mapping):
        node_preferences = {
            str(node_id): _string_list(preferences)
            for node_id, preferences in (merged.get("node_target_preferences", {}) or {}).items()
            if _string_list(preferences)
        }
        for node_id, preferences in policy_payload.get("node_target_preferences", {}).items():
            existing = node_preferences.setdefault(str(node_id), [])
            for target in _string_list(preferences):
                if target not in existing:
                    existing.append(target)
        if node_preferences:
            merged["node_target_preferences"] = node_preferences
    for key in ("architecture_candidates", "architecture_preferences", "mapping_seeds"):
        policy_values = [dict(item) for item in policy_payload.get(key, []) or [] if isinstance(item, Mapping)]
        if policy_values:
            direct_values = [dict(item) for item in merged.get(key, []) or [] if isinstance(item, Mapping)]
            merged[key] = direct_values + policy_values
    if isinstance(policy_payload.get("annotations"), Mapping):
        annotations = dict(merged.get("annotations", {}) or {})
        annotations.setdefault("policy_hints", dict(policy_payload.get("annotations", {})))
        merged["annotations"] = annotations
    merged["review_flags"] = sorted(set(_candidate_hint_review_flags(direct_payload)) | set(_candidate_hint_review_flags(policy_payload)))
    merged["review_required"] = bool(direct_payload.get("review_required", False) or policy_payload.get("review_required", False) or merged["review_flags"])
    merged["hard_block_flags"] = sorted(set(_string_list(direct_payload.get("hard_block_flags"))) | set(_string_list(policy_payload.get("hard_block_flags"))))
    merged["trusted_final_claim"] = False
    return merged


def _domain_policy_status(
    *,
    enable_domain_policies: bool,
    policy_hints_payload: Optional[Mapping[str, Any]],
    candidate_hints_payload: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional policy participation without requiring a domain."""

    direct_policy = _candidate_hint_domain_policy(candidate_hints_payload)
    policy_ids = list(policy_hints_payload.get("policy_ids", [])) if isinstance(policy_hints_payload, Mapping) else []
    if not policy_ids and direct_policy.get("policy_id"):
        policy_ids = [str(direct_policy["policy_id"])]
    review_required = bool(
        (policy_hints_payload or {}).get("review_required", False)
        if isinstance(policy_hints_payload, Mapping)
        else False
    ) or bool(
        (candidate_hints_payload or {}).get("review_required", False)
        if isinstance(candidate_hints_payload, Mapping)
        else False
    ) or bool(_candidate_hint_review_flags(candidate_hints_payload))
    hard_blocked = bool(
        (policy_hints_payload or {}).get("hard_blocked", False)
        if isinstance(policy_hints_payload, Mapping)
        else False
    ) or bool(_hard_review_flags(candidate_hints_payload, _candidate_hint_review_flags(candidate_hints_payload)))
    return {
        "enabled": bool(enable_domain_policies or candidate_hints_payload),
        "matched": bool(policy_ids or (policy_hints_payload or candidate_hints_payload)),
        "policy_ids": policy_ids,
        "review_required": review_required,
        "hard_blocked": hard_blocked,
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
    source_graph: Optional[ComputeGraph] = None,
    executable_graph: Optional[ComputeGraph] = None,
    graph_lowering_report: Optional[Mapping[str, Any]] = None,
    workload_characterization: Optional[Mapping[str, Any]] = None,
    step1_handoff_summary: Optional[Mapping[str, Any]] = None,
    domain_policy_registry: Optional[Step2DomainPolicyRegistry] = None,
    enable_domain_policies: bool = False,
    candidate_hints: Optional[Mapping[str, Any]] = None,
) -> Step2WorkflowResult:
    """Run Step2 and optionally persist all architecture/mapping artifacts."""
    catalog = catalog or seed_generic_dse_architecture_catalog()
    precision_policy = dict(precision_policy or {"default": "FP64", "unavailable_policy": "record_explicit_default"})
    fallback_policy = dict(fallback_policy or {"unsupported_ops": "host_fallback_visible", "final_claim_if_fallback": "requires_step3_evidence"})
    objective_directions = dict(objective_directions or {"latency_ms": "minimize", "energy_j": "minimize", "power_w": "minimize"})
    source_graph = source_graph or workload_package.graph

    validation = workload_package.validate()
    lowering = _lowering_from_step1_or_recompute(
        workload_package=workload_package,
        source_graph=source_graph,
        executable_graph=executable_graph,
        graph_lowering_report=graph_lowering_report,
        step1_handoff_summary=step1_handoff_summary,
    )
    policy_registry = domain_policy_registry or default_step2_domain_policy_registry()
    policy_input = Step2PolicyInput(
        workload_package=workload_package,
        source_graph=source_graph,
        executable_graph=lowering.executable_graph,
        lowering_report=lowering.report,
        workload_characterization=workload_characterization,
        step1_handoff_summary=step1_handoff_summary,
        backend=backend,
        evidence_mode=evidence_mode,
        require_l4_proof=require_l4_proof,
    )
    if enable_domain_policies:
        catalog = policy_registry.augment_catalog(policy_input, catalog)
    policy_hints = (
        policy_registry.build_hints(policy_input, catalog, architecture_id)
        if enable_domain_policies
        else []
    )
    policy_hints_payload = _merge_policy_hints(policy_hints)
    candidate_hints_payload = _merge_candidate_hints(candidate_hints, policy_hints)
    if not validation.get("valid", False):
        return _blocked_result(
            status="blocked_invalid_workload_package",
            reasons=[_status_reason("invalid_workload_package", "WorkloadPackage validation failed", validation=validation)],
            workload_package=workload_package,
            lowering=lowering,
            output_dir=output_dir,
            catalog=catalog,
            source_graph=source_graph,
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
            source_graph=source_graph,
        )
    if architecture_id not in catalog.instances:
        return _blocked_result(
            status="blocked_unknown_architecture",
            reasons=[_status_reason("unknown_architecture", f"architecture_id {architecture_id!r} is not present in catalog")],
            workload_package=workload_package,
            lowering=lowering,
            output_dir=output_dir,
            catalog=catalog,
            source_graph=source_graph,
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
    selected_record.setdefault("mapping_id", design_config["mapping_id"])
    mapping_artifacts["selected_record"] = selected_record
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
    architecture_candidate_set = build_architecture_candidate_set(
        catalog,
        workload_package=workload_package,
        selected_architecture_id=instance.architecture_id,
        architecture_artifact=architecture_artifact,
        selected_record=selected_record,
        promotion_decision=promotion_decision,
        backend=backend,
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
    step3_queue = build_step3_simulation_queue(
        workload_package=workload_package,
        design_point=design_point,
        selected_record=selected_record,
        promotion_decision=promotion_decision,
        architecture_artifact=architecture_artifact,
        backend=backend,
    )
    control_scope = _step2_control_scope(workload_package, trial_seed=run_id)
    canonical_search_artifacts = build_step2_search_artifacts(
        catalog=catalog,
        workload_package=workload_package,
        architecture_ids=sorted(catalog.instances),
        backend=backend,
        objective_directions=objective_directions,
        random_seed=random_seed,
        beam_width=beam_width,
        architecture_candidate_set=architecture_candidate_set,
        mapping_candidate_records=mapping_artifacts["candidate_records"],
        mapping_feedback_state=mapping_artifacts["feedback_state"],
        convergence_status=mapping_artifacts["convergence_status"],
        low_fidelity_summary=low_fidelity_artifacts["low_fidelity_summary"],
        promotion_decision=promotion_decision,
        step3_queue=step3_queue,
        scope=control_scope,
        policy_scope="generic_catalog_only",
    )
    design_point.config["architecture_candidate_set"] = {
        "artifact": "architecture_candidate_set.json",
        "selected_architecture_id": instance.architecture_id,
        "candidate_count": architecture_candidate_set["candidate_count"],
        "trusted_final_claim": False,
    }
    design_point.config["step3_simulation_queue"] = {
        "artifact": "step3_simulation_queue.json",
        "queue_mode": "selected-entry-only",
        "entry_count": step3_queue["entry_count"],
        "trusted_final_claim": False,
    }
    design_point.config.setdefault("output_config", {})["candidate_queue_artifacts"] = list(STEP2_CANDIDATE_QUEUE_ARTIFACTS)
    design_point.config.setdefault("replay_metadata", {})["architecture_candidate_set"] = "architecture_candidate_set.json"
    design_point.config.setdefault("replay_metadata", {})["step3_simulation_queue"] = "step3_simulation_queue.json"
    design_point.config.setdefault("replay_metadata", {})["architecture_search_space"] = "architecture_search_space.json"
    design_point.config.setdefault("replay_metadata", {})["search_checkpoint"] = "search_checkpoint.json"
    design_point.config.setdefault("replay_metadata", {})["top_k_candidate_queue"] = "top_k_candidate_queue.json"
    design_point.config.setdefault("replay_metadata", {})["architecture_candidate_generation_report"] = "architecture_candidate_generation_report.json"
    design_point.config.setdefault("replay_metadata", {})["architecture_screening_report"] = "architecture_screening_report.json"
    design_point.config.setdefault("replay_metadata", {})["trial_state_ledger"] = "trial_state_ledger.json"
    design_point.config.setdefault("replay_metadata", {})["mapping_candidates_jsonl"] = "mapping_candidates.jsonl"
    design_point.config.setdefault("replay_metadata", {})["screening_results_jsonl"] = "screening_results.jsonl"
    design_point.config.setdefault("replay_metadata", {})["promotion_decisions_jsonl"] = "promotion_decisions.jsonl"

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
            "source_graph_id": source_graph.graph_id,
            "executable_graph_id": executable_graph.graph_id,
            "architecture_id": instance.architecture_id,
            "design_point_id": design_point.design_point_id,
            "mapping_id": design_config["mapping_id"],
            "selected_candidate_id": selected_record.get("candidate_id"),
            "backend": backend,
            "required_coverage": list(lowering.report.get("required_coverage", [])),
            "step1_replay": dict(lowering.report.get("step2_replay", {})),
            "domain_policy": _domain_policy_status(
                enable_domain_policies=enable_domain_policies,
                policy_hints_payload=policy_hints_payload,
                candidate_hints_payload=candidate_hints_payload,
            ),
            "low_fidelity_screening": {
                "summary_artifact": "low_fidelity_screening_summary.json",
                "passed": bool(low_fidelity_artifacts["low_fidelity_summary"].get("passed", False)),
                "required_for_step3": bool(low_fidelity_artifacts["low_fidelity_summary"].get("required_for_step3", True)),
                "low_fidelity_role": "candidate_generator_only",
                "trusted_final_claim": False,
            },
            "review_flags": _candidate_hint_review_flags(candidate_hints_payload),
            "review_required": bool((promotion_decision or {}).get("review_required", False)),
            "review_status": (promotion_decision or {}).get("review_status", "not_required"),
            "reasons": status_reasons,
        },
        "architecture_catalog": catalog_payload,
        "architecture": architecture_artifact,
        "design_point": design_point.to_dict(),
        "workload_package": workload_package.to_dict(),
        "workload_graph": source_graph.to_dict(),
        "graph_lowering_report": lowering.report,
        "executable_graph": executable_graph.to_dict(),
        "mapping": mapping_payload,
        "promotion_decision": promotion_decision,
        "l1_evaluation_result": low_fidelity_artifacts["l1_evaluation_result"],
        "l1_promotion_decision": low_fidelity_artifacts["l1_promotion_decision"],
        "l2_evaluation_result": low_fidelity_artifacts["l2_evaluation_result"],
        "l2_promotion_decision": low_fidelity_artifacts["l2_promotion_decision"],
        "low_fidelity_summary": low_fidelity_artifacts["low_fidelity_summary"],
        "architecture_candidate_set": architecture_candidate_set,
        "step3_simulation_queue": step3_queue,
        "architecture_search_space": canonical_search_artifacts["architecture_search_space"],
        "search_checkpoint": canonical_search_artifacts["search_checkpoint"],
        "top_k_candidate_queue": canonical_search_artifacts["top_k_candidate_queue"],
        "architecture_candidate_generation_report": canonical_search_artifacts["architecture_candidate_generation_report"],
        "architecture_screening_report": canonical_search_artifacts["architecture_screening_report"],
        "trial_state_ledger": canonical_search_artifacts["trial_state_ledger"],
        "mapping_candidates_jsonl": canonical_search_artifacts["mapping_candidates_jsonl"],
        "screening_results_jsonl": canonical_search_artifacts["screening_results_jsonl"],
        "promotion_decisions_jsonl": canonical_search_artifacts["promotion_decisions_jsonl"],
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
    if workload_characterization is not None:
        artifacts["workload_characterization"] = dict(workload_characterization)
    if step1_handoff_summary is not None:
        artifacts["step1_handoff_summary"] = dict(step1_handoff_summary)
    if candidate_hints_payload is not None:
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
            "workload_characterization": "workload_characterization.json",
            "step1_handoff_summary": "step1_handoff_summary.json",
            "domain_policy_hints": "domain_policy_hints.json",
            "graph_lowering_report": "graph_lowering_report.json",
            "executable_graph": "executable_graph.json",
            "mapping": "mapping.json",
            "promotion_decision": "mapping_promotion_decision.json",
            "l1_evaluation_result": "l1_evaluation_result.json",
            "l1_promotion_decision": "l1_promotion_decision.json",
            "l2_evaluation_result": "l2_evaluation_result.json",
            "l2_promotion_decision": "l2_promotion_decision.json",
            "low_fidelity_summary": "low_fidelity_screening_summary.json",
            "architecture_search_space": "architecture_search_space.json",
            "search_checkpoint": "search_checkpoint.json",
            "top_k_candidate_queue": "top_k_candidate_queue.json",
            "architecture_candidate_generation_report": "architecture_candidate_generation_report.json",
            "architecture_screening_report": "architecture_screening_report.json",
            "trial_state_ledger": "trial_state_ledger.json",
            "architecture_candidate_set": "architecture_candidate_set.json",
            "step3_simulation_queue": "step3_simulation_queue.json",
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
            if key in artifacts:
                _write_json(output / filename, artifacts[key])
                artifact_paths[key] = filename
        jsonl_map = {
            "mapping_candidates_jsonl": "mapping_candidates.jsonl",
            "screening_results_jsonl": "screening_results.jsonl",
            "promotion_decisions_jsonl": "promotion_decisions.jsonl",
        }
        for key, filename in jsonl_map.items():
            if key in artifacts:
                _write_jsonl(output / filename, artifacts[key])
                artifact_paths[key] = filename

    return Step2WorkflowResult(
        status=status,
        trusted_final_eligible=trusted_final_eligible,
        workload_package=workload_package,
        source_graph=source_graph,
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

    handoff = load_step1_handoff(step1_dir)
    workload_package = handoff["workload_package"]
    workflow_kwargs = dict(kwargs)
    workflow_kwargs.setdefault("source_graph", handoff.get("workload_graph"))
    workflow_kwargs.setdefault("executable_graph", handoff.get("executable_graph"))
    workflow_kwargs.setdefault("graph_lowering_report", handoff.get("graph_lowering_report"))
    if handoff.get("workload_characterization") is not None:
        workflow_kwargs.setdefault("workload_characterization", handoff.get("workload_characterization"))
    workflow_kwargs.setdefault("step1_handoff_summary", {
        "schema_version": "dse.step1.handoff_summary.v1",
        "step1_dir": str(Path(step1_dir)),
        "status": handoff.get("status", {}),
        "artifact_verification": handoff.get("artifact_verification", {}),
        "loaded_artifacts": sorted(str(key) for key in handoff.keys()),
    })
    return run_step2_architecture_mapping_workflow(workload_package, **workflow_kwargs)


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
    eligibility_fields = _step2_eligibility_fields(
        step3_searchable=bool(architecture.get("step3_searchable", architecture.get("step3_evaluable", False))),
        step3_blockers=list(architecture.get("step3_search_blockers", architecture.get("simulation_blockers", [])) or []),
        promoted_for_simulation=bool(promotion.get("promoted_for_simulation", False)),
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
        "step3_searchable": bool(architecture.get("step3_searchable", False)),
        "step3_search_blockers": list(architecture.get("step3_search_blockers", []) or []),
        **eligibility_fields,
        "step4_eligible": bool(
            architecture.get("step3_searchable", False)
            and "gem5_systemc" in (
                architecture.get("architecture_instance", {}).get("simulation_bindings", {})
                if isinstance(architecture.get("architecture_instance", {}), Mapping)
                else {}
            )
        ),
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
    objective_directions = dict(objective_directions or {"latency_ms": "minimize", "energy_j": "minimize", "power_w": "minimize"})
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
    architecture_candidate_set = _screening_architecture_candidate_set(
        workload_package=workload_package,
        records=records,
        backend=backend,
    )
    step3_queue = _screening_step3_queue(
        workload_package=workload_package,
        child_results=child_results,
        records=records,
        backend=backend,
    )
    screening_scope = _step2_control_scope(
        workload_package,
        trial_seed=f"{workload_package.workload_id}__architecture_screening",
    )
    synthetic_mapping_candidates = {
        "algorithm": "architecture_screening_v1",
        "beam_width": beam_width,
        "candidates": [
            {
                "candidate_id": str(record.get("selected_candidate_id") or record.get("architecture_id")),
                "architecture_id": str(record.get("architecture_id") or ""),
                "mapping": {},
                "state": "promoted" if record.get("promoted_for_simulation") else "blocked",
                "selection_reason": "architecture_screening_record",
            }
            for record in records
        ],
    }
    aggregate_promotion_decision = {
        "candidate_id": str(promoted_records[0].get("selected_candidate_id") or promoted_records[0].get("architecture_id")),
        "mapping_id": str(promoted_records[0].get("mapping_id") or ""),
        "architecture_id": str(promoted_records[0].get("architecture_id") or ""),
        "promoted_for_simulation": True,
        "reasons": [{"reason_id": "architecture_screening_promoted"}],
        "required_evidence": ["simulation_request.json", "simulation_result.json"],
    } if promoted_records else {
        "candidate_id": "architecture_screening",
        "mapping_id": "",
        "architecture_id": "",
        "promoted_for_simulation": False,
        "reasons": [{"reason_id": "no_architecture_promoted"}],
        "required_evidence": [],
    }
    canonical_screening_artifacts = build_step2_search_artifacts(
        catalog=catalog,
        workload_package=workload_package,
        architecture_ids=selected_architecture_ids,
        backend=backend,
        objective_directions=objective_directions,
        random_seed=random_seed,
        beam_width=beam_width,
        architecture_candidate_set=architecture_candidate_set,
        mapping_candidate_records=synthetic_mapping_candidates,
        mapping_feedback_state=None,
        convergence_status=None,
        low_fidelity_summary=None,
        promotion_decision=aggregate_promotion_decision,
        step3_queue=step3_queue,
        scope=screening_scope,
        policy_scope="architecture_screening",
    )
    canonical_screening_artifacts["promotion_decisions_jsonl"] = [
        {
            "schema_version": "dse.step2.promotion_decision_record.v1",
            **dict(screening_scope),
            "workload_id": workload_package.workload_id,
            "workload_family": workload_package.workload_family,
            "candidate_id": str(record.get("selected_candidate_id") or record.get("architecture_id")),
            "mapping_id": str(record.get("mapping_id") or ""),
            "architecture_id": str(record.get("architecture_id") or ""),
            "decision": "promote" if record.get("promoted_for_simulation") else "block",
            "promoted_for_simulation": bool(record.get("promoted_for_simulation", False)),
            "reasons": [
                str(reason.get("reason_id") if isinstance(reason, Mapping) else reason)
                for reason in record.get("reasons", []) or record.get("candidate_only_reasons", []) or []
                if isinstance(reason, (Mapping, str))
            ],
            "required_evidence": ["simulation_request.json", "simulation_result.json"],
            "queue_artifact": "step3_simulation_queue.json",
            "trusted_final_claim": False,
        }
        for record in records
    ]
    canonical_screening_artifacts["trial_state_ledger"] = build_step2_trial_state_ledger(
        workload_package=workload_package,
        architecture_candidates=architecture_candidate_set.get("candidates", []),
        mapping_candidates=canonical_screening_artifacts["mapping_candidates_jsonl"],
        screening_results=canonical_screening_artifacts["screening_results_jsonl"],
        promotion_decisions=canonical_screening_artifacts["promotion_decisions_jsonl"],
        step3_queue=step3_queue,
        search_space=canonical_screening_artifacts["architecture_search_space"],
        scope=screening_scope,
        policy_scope="architecture_screening",
    )
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
    artifacts: Dict[str, Any] = {
        "architecture_screening_records": aggregate,
        "architecture_search_space": canonical_screening_artifacts["architecture_search_space"],
        "search_checkpoint": canonical_screening_artifacts["search_checkpoint"],
        "top_k_candidate_queue": canonical_screening_artifacts["top_k_candidate_queue"],
        "architecture_candidate_generation_report": canonical_screening_artifacts["architecture_candidate_generation_report"],
        "architecture_screening_report": canonical_screening_artifacts["architecture_screening_report"],
        "trial_state_ledger": canonical_screening_artifacts["trial_state_ledger"],
        "mapping_candidates_jsonl": canonical_screening_artifacts["mapping_candidates_jsonl"],
        "screening_results_jsonl": canonical_screening_artifacts["screening_results_jsonl"],
        "promotion_decisions_jsonl": canonical_screening_artifacts["promotion_decisions_jsonl"],
        "architecture_candidate_set": architecture_candidate_set,
        "step3_simulation_queue": step3_queue,
    }
    artifact_paths: Dict[str, str] = {}
    if root_dir is not None:
        _write_json(root_dir / "architecture_screening_records.json", aggregate)
        artifact_paths["architecture_screening_records"] = "architecture_screening_records.json"
        _write_json(root_dir / "architecture_search_space.json", canonical_screening_artifacts["architecture_search_space"])
        artifact_paths["architecture_search_space"] = "architecture_search_space.json"
        _write_json(root_dir / "search_checkpoint.json", canonical_screening_artifacts["search_checkpoint"])
        artifact_paths["search_checkpoint"] = "search_checkpoint.json"
        _write_json(root_dir / "top_k_candidate_queue.json", canonical_screening_artifacts["top_k_candidate_queue"])
        artifact_paths["top_k_candidate_queue"] = "top_k_candidate_queue.json"
        _write_json(root_dir / "architecture_candidate_generation_report.json", canonical_screening_artifacts["architecture_candidate_generation_report"])
        artifact_paths["architecture_candidate_generation_report"] = "architecture_candidate_generation_report.json"
        _write_json(root_dir / "architecture_screening_report.json", canonical_screening_artifacts["architecture_screening_report"])
        artifact_paths["architecture_screening_report"] = "architecture_screening_report.json"
        _write_json(root_dir / "trial_state_ledger.json", canonical_screening_artifacts["trial_state_ledger"])
        artifact_paths["trial_state_ledger"] = "trial_state_ledger.json"
        _write_jsonl(root_dir / "mapping_candidates.jsonl", canonical_screening_artifacts["mapping_candidates_jsonl"])
        artifact_paths["mapping_candidates_jsonl"] = "mapping_candidates.jsonl"
        _write_jsonl(root_dir / "screening_results.jsonl", canonical_screening_artifacts["screening_results_jsonl"])
        artifact_paths["screening_results_jsonl"] = "screening_results.jsonl"
        _write_jsonl(root_dir / "promotion_decisions.jsonl", canonical_screening_artifacts["promotion_decisions_jsonl"])
        artifact_paths["promotion_decisions_jsonl"] = "promotion_decisions.jsonl"
        _write_json(root_dir / "architecture_candidate_set.json", architecture_candidate_set)
        artifact_paths["architecture_candidate_set"] = "architecture_candidate_set.json"
        _write_json(root_dir / "step3_simulation_queue.json", step3_queue)
        artifact_paths["step3_simulation_queue"] = "step3_simulation_queue.json"

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
