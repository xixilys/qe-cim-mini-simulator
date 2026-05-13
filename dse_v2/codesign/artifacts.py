#!/usr/bin/env python3
"""HW/SW co-design candidate and L4 evidence artifacts.

The co-design layer makes software/runtime/interface decisions explicit before
an expensive L4 gem5+SystemC sample is attempted.  L4 evidence remains
proof-gated: these helpers describe and report the candidate, but they never
convert missing descriptor/request/completion evidence into trusted claims.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from dse_v2.backends.gem5_systemc_adapter import (
    GSIM_COMMAND_TYPE_GRAPH,
    GSIM_DESCRIPTOR_VERSION,
    GSIM_MAGIC,
)
from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload.package import WorkloadPackage
from dse_v2.dse.orchestrator import DesignPoint

CODESIGN_STEP2_ARTIFACTS = [
    "codesign_candidate.json",
    "software_stack_config.json",
    "compiler_lowering.json",
    "runtime_schedule.json",
    "descriptor_protocol.json",
    "memory_policy.json",
    "codesign_artifact_validation.json",
]

CODESIGN_L4_EVIDENCE_ARTIFACTS = [
    "l4_execution_trace.json",
    "dma_trace.json",
    "mmio_trace.json",
    "cpu_runtime_trace.json",
    "accelerator_trace.json",
    "completion_proof.json",
    "codesign_verdict.json",
]

_REQUIRED_CANDIDATE_FIELDS = [
    "schema_version",
    "codesign_candidate_id",
    "design_point_id",
    "workload_id",
    "architecture_id",
    "mapping_id",
    "hardware_config",
    "software_stack_config",
    "compiler_lowering",
    "runtime_schedule",
    "descriptor_protocol",
    "memory_policy",
    "simulation_binding",
    "expected_claims",
    "promotion_policy",
]


def _mapping_id(design_point: DesignPoint) -> str:
    return str(design_point.config.get("mapping_id") or f"{design_point.design_point_id}_mapping")


def _architecture_id(design_point: DesignPoint, architecture_artifact: Mapping[str, Any]) -> str:
    return str(architecture_artifact.get("architecture_id") or design_point.config.get("architecture_id") or design_point.system_architecture.system_id)


def _tensor_layouts(graph: ComputeGraph) -> Dict[str, Dict[str, Any]]:
    tensors: Dict[str, Dict[str, Any]] = {}
    for node in graph.nodes.values():
        for name, spec in {**node.input_specs, **node.output_specs}.items():
            tensors[name] = {
                "dtype": spec.dtype,
                "layout": spec.layout,
                "shape": list(spec.shape),
                "size_bytes": spec.size_bytes() if spec.dtype else None,
            }
    for edge in graph.edges:
        if edge.tensor_name and edge.tensor_spec is not None:
            tensors.setdefault(edge.tensor_name, {
                "dtype": edge.tensor_spec.dtype,
                "layout": edge.tensor_spec.layout,
                "shape": list(edge.tensor_spec.shape),
                "size_bytes": edge.tensor_spec.size_bytes(),
            })
    return tensors


def _schedule_entries(graph: ComputeGraph, mapping: Mapping[str, str]) -> List[Dict[str, Any]]:
    try:
        order = graph.topological_sort()
    except Exception:
        order = sorted(graph.nodes.keys())
    return [
        {
            "sequence_index": idx,
            "node_id": node_id,
            "op_type": graph.nodes[node_id].op_type if node_id in graph.nodes else "unknown",
            "target": str(mapping.get(node_id, "host")),
            "descriptor_granularity": "graph_node_command",
        }
        for idx, node_id in enumerate(order)
    ]


def build_default_codesign_artifacts(
    *,
    design_point: DesignPoint,
    workload_package: WorkloadPackage,
    executable_graph: ComputeGraph,
    architecture_artifact: Mapping[str, Any],
    selected_record: Mapping[str, Any],
    promotion_decision: Mapping[str, Any],
    backend: str,
    evidence_mode: str,
    l4_required: bool = False,
    l4_reason: str = "software-visible descriptor/request/completion proof requested for co-design claim",
    software_stack_config: Optional[Mapping[str, Any]] = None,
    compiler_lowering: Optional[Mapping[str, Any]] = None,
    runtime_schedule: Optional[Mapping[str, Any]] = None,
    descriptor_protocol: Optional[Mapping[str, Any]] = None,
    memory_policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build a replayable Step2 co-design artifact set.

    Defaults are deliberately conservative and domain-neutral.  They record the
    current software-visible path (runtime API + GenericAccel descriptor) and
    leave final trust to L4 evidence gates.
    """
    mapping = {str(k): str(v) for k, v in design_point.task_mapping.items()}
    candidate_id = f"{design_point.design_point_id}__codesign"
    architecture_id = _architecture_id(design_point, architecture_artifact)
    mapping_id = _mapping_id(design_point)
    bindings = architecture_artifact.get("simulation_bindings", {}) if isinstance(architecture_artifact.get("simulation_bindings", {}), Mapping) else {}
    l3_binding = bindings.get("systemc", {}) if isinstance(bindings.get("systemc", {}), Mapping) else {}
    l4_binding = bindings.get("gem5_systemc", {}) if isinstance(bindings.get("gem5_systemc", {}), Mapping) else {}
    tensor_layouts = _tensor_layouts(executable_graph)
    schedule_entries = _schedule_entries(executable_graph, mapping)

    sw = dict(software_stack_config or {
        "schema_version": "dse.codesign.software_stack_config.v1",
        "software_stack_config_id": f"{candidate_id}__software",
        "driver": {
            "kind": "guest_driver",
            "implementation": "gem5_integration/test_programs/generic_accel/generic_accel_l4_driver.c",
            "role": "submit GSIM command descriptor and observe completion status",
        },
        "runtime": {
            "implementation": "runtime_api/offload_runtime.c",
            "abi": "runtime_api/command_descriptor.h",
            "policy": "domain_neutral_offload_proxy",
        },
        "host_pre_post_processing": {
            "policy": "host_visible_fallback_and_completion_check",
            "fallback_path": design_point.config.get("fallback_policy", {}).get("unsupported_ops", "host_fallback_visible") if isinstance(design_point.config.get("fallback_policy", {}), Mapping) else "host_fallback_visible",
        },
        "synchronization": "poll_status_then_read_completion_descriptor",
    })

    lowering = dict(compiler_lowering or {
        "schema_version": "dse.codesign.compiler_lowering.v1",
        "compiler_lowering_id": f"{candidate_id}__lowering",
        "lowering_pipeline": "generic_compute_graph_to_gsim_request",
        "operator_lowering": [
            {
                "node_id": entry["node_id"],
                "op_type": entry["op_type"],
                "target": entry["target"],
                "lowering": "emit_graph_node_payload",
            }
            for entry in schedule_entries
        ],
        "data_layout": {
            "policy": "preserve_declared_layouts_unless_backend_requires_transform",
            "tensors": tensor_layouts,
        },
        "precision_policy": dict(design_point.config.get("precision_policy", {"default": "FP64"}) if isinstance(design_point.config.get("precision_policy", {}), Mapping) else {"default": "FP64"}),
        "fusion_policy": "none_by_default_record_explicitly",
        "tiling_policy": "backend_default_timing_level_tiles",
    })

    runtime = dict(runtime_schedule or {
        "schema_version": "dse.codesign.runtime_schedule.v1",
        "runtime_schedule_id": f"{candidate_id}__runtime_schedule",
        "scheduling_policy": design_point.scheduling_policy,
        "command_queue": {
            "queue_count": 1,
            "queue_depth": 64,
            "ordering": "in_order_descriptor_queue",
            "backpressure": "device_status_polling",
        },
        "batching": {
            "policy": "single_graph_descriptor",
            "batch_size": 1,
        },
        "copy_compute_overlap": {
            "policy": "allow_dma_compute_overlap_when_backend_reports_it",
            "requires_l4_calibration": True,
        },
        "completion_policy": {
            "mode": "polling",
            "interrupts_enabled": False,
            "guest_visible_status_required": True,
        },
        "schedule": schedule_entries,
    })

    descriptor = dict(descriptor_protocol or {
        "schema_version": "dse.codesign.descriptor_protocol.v1",
        "descriptor_protocol_id": f"{candidate_id}__descriptor_protocol",
        "format": "GSIM command descriptor",
        "magic": f"0x{GSIM_MAGIC:08x}",
        "version": GSIM_DESCRIPTOR_VERSION,
        "command_type": GSIM_COMMAND_TYPE_GRAPH,
        "descriptor_fields": [
            "magic",
            "version",
            "command_type",
            "request_addr",
            "request_bytes",
            "result_addr",
            "result_bytes",
            "completion_addr",
            "flags",
        ],
        "doorbell": {
            "path": "MMIO",
            "policy": "write_descriptor_pointer_then_ring_doorbell",
            "ordering_required": True,
        },
        "completion": {
            "path": "guest_visible_memory_and_status_mmio",
            "required_fields": ["completion_magic", "completion_status", "cycles", "result_addr"],
            "success_status": 0,
        },
        "shared_memory_layout": {
            "request_payload": "JSON simulation_request_v1/v2 payload",
            "result_payload": "JSON simulation_result payload",
            "completion_descriptor": "fixed GSIM completion record",
        },
        "copy_policy": "copy_payload_to_guest_visible_workspace",
        "cacheability": "uncached_mmio_descriptor_workspace",
    })

    memory = dict(memory_policy or {
        "schema_version": "dse.codesign.memory_policy.v1",
        "memory_policy_id": f"{candidate_id}__memory_policy",
        "data_placement": dict(design_point.config.get("data_placement", {}) if isinstance(design_point.config.get("data_placement", {}), Mapping) else {}),
        "tensor_placement": {tensor: {"preferred_location": "mapped_target_or_host_visible", **info} for tensor, info in tensor_layouts.items()},
        "host_device_allocation": {
            "request_payload": "guest_visible_pinned_buffer",
            "result_payload": "guest_visible_pinned_buffer",
            "tensor_payloads": "host_owned_or_backend_allocated_by_mapping",
        },
        "dma": {
            "enabled": True,
            "direction": "host_to_device_and_device_to_host",
            "coalescing_policy": "descriptor_payload_burst_when_possible",
        },
        "coherency": {
            "mode": "software_managed_for_L4_prototype",
            "cache_flush_required_before_doorbell": True,
            "cache_invalidate_required_after_completion": True,
        },
    })

    expected_claims = ["timing", "resource", "data_movement"]
    if l4_required or backend == "gem5_systemc":
        expected_claims.extend([
            "software_visible_descriptor_ingestion",
            "gem5_microarchitecture_executed_from_device_path",
            "guest_visible_completion",
        ])

    candidate = {
        "schema_version": "dse.codesign_candidate.v1",
        "codesign_candidate_id": candidate_id,
        "design_point_id": design_point.design_point_id,
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "architecture_id": architecture_id,
        "mapping_id": mapping_id,
        "mapping_candidate_id": selected_record.get("candidate_id"),
        "hardware_config": {
            "architecture_artifact": "architecture.json",
            "architecture_id": architecture_id,
            "system_architecture_id": design_point.system_architecture.system_id,
            "accelerator_count": len(design_point.system_architecture.accelerators),
            "hardware_knobs": {
                "host_cpu_cores": design_point.system_architecture.host_cpu_cores,
                "host_memory_gb": design_point.system_architecture.host_memory_gb,
                "interconnect_bandwidth_gbps": design_point.system_architecture.interconnect.bandwidth_gbps if design_point.system_architecture.interconnect else None,
                "accelerators": [
                    {
                        "accel_id": accel.accel_id,
                        "accel_type": accel.accel_type,
                        "local_memory_bytes": accel.memory.total_capacity_bytes(),
                        "host_link_bandwidth_gbps": accel.communication.host_link.bandwidth_gbps if accel.communication.host_link else None,
                    }
                    for accel in design_point.system_architecture.accelerators
                ],
            },
        },
        "software_stack_config": sw,
        "compiler_lowering": lowering,
        "runtime_schedule": runtime,
        "descriptor_protocol": descriptor,
        "memory_policy": memory,
        "simulation_binding": {
            "l3_systemc": l3_binding.get("binding_id"),
            "l3_status": l3_binding.get("status"),
            "l4_gem5_systemc": l4_binding.get("binding_id"),
            "l4_status": l4_binding.get("status"),
            "selected_backend": backend,
            "evidence_mode": evidence_mode,
        },
        "expected_claims": expected_claims,
        "promotion_policy": {
            "l4_required": bool(l4_required or backend == "gem5_systemc"),
            "reason": l4_reason if (l4_required or backend == "gem5_systemc") else "L3 timing evidence is sufficient for non-software-visible timing claim; L4 remains optional calibration sample.",
            "l4_sampling_role": "claim_critical_or_calibration_sample" if (l4_required or backend == "gem5_systemc") else "optional_expensive_oracle_sample",
            "step2_trusted_claim": False,
            "step2_promotion_decision": "mapping_promotion_decision.json",
            "promoted_for_simulation": bool(promotion_decision.get("promoted_for_simulation", False)),
        },
        "replay_artifacts": {
            "design_point": "design_point.json",
            "workload_package": "workload_package.json",
            "executable_graph": "executable_graph.json",
            "mapping": "mapping.json",
            "software_stack_config": "software_stack_config.json",
            "compiler_lowering": "compiler_lowering.json",
            "runtime_schedule": "runtime_schedule.json",
            "descriptor_protocol": "descriptor_protocol.json",
            "memory_policy": "memory_policy.json",
        },
        "trusted_final_claim": False,
    }
    return {
        "codesign_candidate": candidate,
        "software_stack_config": sw,
        "compiler_lowering": lowering,
        "runtime_schedule": runtime,
        "descriptor_protocol": descriptor,
        "memory_policy": memory,
    }


def split_codesign_artifacts(candidate: Optional[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Return top-level config artifacts embedded in a candidate."""
    if not isinstance(candidate, Mapping) or not candidate:
        return {}
    return {
        "codesign_candidate": dict(candidate),
        "software_stack_config": dict(candidate.get("software_stack_config", {}) if isinstance(candidate.get("software_stack_config", {}), Mapping) else {}),
        "compiler_lowering": dict(candidate.get("compiler_lowering", {}) if isinstance(candidate.get("compiler_lowering", {}), Mapping) else {}),
        "runtime_schedule": dict(candidate.get("runtime_schedule", {}) if isinstance(candidate.get("runtime_schedule", {}), Mapping) else {}),
        "descriptor_protocol": dict(candidate.get("descriptor_protocol", {}) if isinstance(candidate.get("descriptor_protocol", {}), Mapping) else {}),
        "memory_policy": dict(candidate.get("memory_policy", {}) if isinstance(candidate.get("memory_policy", {}), Mapping) else {}),
    }


def validate_codesign_artifacts(artifacts: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate replay references and proof-gate boundaries for Step2 co-design."""
    candidate = artifacts.get("codesign_candidate", {}) if isinstance(artifacts.get("codesign_candidate", {}), Mapping) else {}
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    if not candidate:
        errors.append({"field": "codesign_candidate", "message": "codesign_candidate artifact is required"})
    else:
        for field in _REQUIRED_CANDIDATE_FIELDS:
            if field not in candidate:
                errors.append({"field": f"codesign_candidate.{field}", "message": "required field missing"})
        if candidate.get("trusted_final_claim"):
            errors.append({"field": "codesign_candidate.trusted_final_claim", "message": "Step2 co-design candidate cannot claim trusted final results"})
        promotion = candidate.get("promotion_policy", {}) if isinstance(candidate.get("promotion_policy", {}), Mapping) else {}
        if promotion.get("step2_trusted_claim"):
            errors.append({"field": "codesign_candidate.promotion_policy.step2_trusted_claim", "message": "Step2 cannot close L4 software-visible proof"})
        descriptor = candidate.get("descriptor_protocol", {}) if isinstance(candidate.get("descriptor_protocol", {}), Mapping) else {}
        if descriptor.get("magic") not in {f"0x{GSIM_MAGIC:08x}", f"0x{GSIM_MAGIC:08X}", GSIM_MAGIC}:
            errors.append({"field": "descriptor_protocol.magic", "message": "descriptor magic must identify GSIM"})
        if descriptor.get("version") != GSIM_DESCRIPTOR_VERSION:
            errors.append({"field": "descriptor_protocol.version", "message": "descriptor protocol version mismatch"})
        if descriptor.get("command_type") != GSIM_COMMAND_TYPE_GRAPH:
            errors.append({"field": "descriptor_protocol.command_type", "message": "descriptor command_type must be graph execution"})
        if promotion.get("l4_required") and not (candidate.get("simulation_binding", {}) or {}).get("l4_gem5_systemc"):
            warnings.append({"field": "simulation_binding.l4_gem5_systemc", "message": "L4 proof is required but catalog L4 binding id is unavailable; Step3 must block trusted co-design claims"})

    for artifact_key in ["software_stack_config", "compiler_lowering", "runtime_schedule", "descriptor_protocol", "memory_policy"]:
        top_level = artifacts.get(artifact_key, {})
        embedded = candidate.get(artifact_key, {}) if isinstance(candidate, Mapping) else {}
        if not isinstance(top_level, Mapping) or not top_level:
            errors.append({"field": artifact_key, "message": "top-level co-design subartifact missing"})
        elif isinstance(embedded, Mapping) and embedded and dict(top_level) != dict(embedded):
            errors.append({"field": artifact_key, "message": "top-level subartifact must match codesign_candidate embedded config"})

    return {
        "schema_version": "dse.codesign_artifact_validation.v1",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_artifacts": sorted(str(key) for key in artifacts.keys()),
    }


def _regex_int(pattern: str, text: str) -> Optional[int]:
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        return int(match.group(1), 0)
    except ValueError:
        return None


def _proof_checks(proof: Mapping[str, Any]) -> Mapping[str, Any]:
    checks = proof.get("checks", {}) if isinstance(proof.get("checks", {}), Mapping) else proof
    return checks if isinstance(checks, Mapping) else {}


def _blockers_from_result(sim_result: Mapping[str, Any], proof: Mapping[str, Any]) -> List[Dict[str, Any]]:
    blockers: List[Dict[str, Any]] = []
    raw = sim_result.get("gem5_systemc_blockers") if isinstance(sim_result, Mapping) else None
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        for item in raw:
            blockers.append(dict(item) if isinstance(item, Mapping) else {"id": "gem5_systemc_blocker", "detail": str(item)})
    missing = proof.get("missing_evidence", []) if isinstance(proof, Mapping) else []
    if isinstance(missing, str):
        missing = [missing]
    for item in missing or []:
        blockers.append({"id": "missing_l4_evidence", "detail": str(item), "status": "blocked"})
    return blockers


def build_codesign_l4_evidence(
    *,
    codesign_candidate: Mapping[str, Any],
    backend: str,
    sim_result: Mapping[str, Any],
    gem5_l4_proof: Mapping[str, Any],
    gem5_log: Optional[str],
    gem5_stdout: Optional[str],
    trusted_for_final: bool,
) -> Dict[str, Dict[str, Any]]:
    """Build L4 trace/proof/verdict artifacts for one co-design candidate."""
    candidate_id = str(codesign_candidate.get("codesign_candidate_id", "unknown_codesign_candidate"))
    checks = dict(_proof_checks(gem5_l4_proof))
    proof_passed = bool(gem5_l4_proof.get("passed", False))
    log = gem5_log or ""
    stdout = gem5_stdout or ""
    blockers = _blockers_from_result(sim_result, gem5_l4_proof)
    trusted_codesign = backend == "gem5_systemc" and proof_passed and trusted_for_final

    request_bytes = _regex_int(r"request_bytes=(0x[0-9a-fA-F]+|\d+)", log)
    result_bytes = _regex_int(r"result_bytes=(0x[0-9a-fA-F]+|\d+)", log)
    cycles = _regex_int(r"cycles=(0x[0-9a-fA-F]+|\d+)", log + "\n" + stdout)
    metrics = sim_result.get("metrics", {}) if isinstance(sim_result.get("metrics", {}), Mapping) else {}

    execution_trace = {
        "schema_version": "dse.l4_execution_trace.v1",
        "codesign_candidate_id": candidate_id,
        "backend": backend,
        "trace_status": "trusted" if trusted_codesign else ("blocked" if backend == "gem5_systemc" else "not_applicable"),
        "events": [
            {
                "event": "guest_descriptor_submitted",
                "software_visible": True,
                "observed": bool(checks.get("descriptor_read_verified", False)),
                "source": "gem5.log descriptor_read verified=true",
            },
            {
                "event": "generic_accel_request_consumed",
                "software_visible": False,
                "observed": bool(checks.get("descriptor_read_verified", False)),
                "source": "GenericAccel descriptor ingestion log",
            },
            {
                "event": "gem5_microarchitecture_model_executed_from_device_path",
                "software_visible": False,
                "observed": bool(checks.get("microarchitecture_execute_verified", checks.get("systemc_submit_verified", False))),
                "source": "gem5.log microarchitecture_execute verified=true",
            },
            {
                "event": "completion_writeback_to_guest_visible_memory",
                "software_visible": True,
                "observed": bool(checks.get("completion_writeback_verified", False)),
                "source": "gem5.log completion_writeback verified=true",
            },
            {
                "event": "guest_driver_observed_success_status",
                "software_visible": True,
                "observed": bool(checks.get("driver_status_verified", False) and checks.get("driver_completion_descriptor_verified", False)),
                "source": "driver stdout completion/status lines",
            },
        ],
        "source_artifacts": dict(gem5_l4_proof.get("source_artifacts", {}) if isinstance(gem5_l4_proof.get("source_artifacts", {}), Mapping) else {}),
        "blockers": blockers,
    }

    dma_trace = {
        "schema_version": "dse.dma_trace.v1",
        "codesign_candidate_id": candidate_id,
        "trace_status": execution_trace["trace_status"],
        "request_bytes": request_bytes,
        "result_bytes": result_bytes,
        "total_payload_bytes_observed": (request_bytes or 0) + (result_bytes or 0) if request_bytes is not None or result_bytes is not None else None,
        "simulated_total_data_movement_mb": metrics.get("total_data_movement_mb"),
        "dma_time_ms": metrics.get("dma_time_ms"),
        "stall_time_ms": None,
        "unavailable_reason": None if trusted_codesign else "trusted DMA timing requires passing L4 descriptor/completion proof",
    }

    mmio_trace = {
        "schema_version": "dse.mmio_trace.v1",
        "codesign_candidate_id": candidate_id,
        "trace_status": execution_trace["trace_status"],
        "mmio_count": sum(
            1
            for key in [
                "descriptor_read_verified",
                "request_decode_verified",
                "microarchitecture_execute_verified",
                "completion_writeback_verified",
                "driver_status_verified",
            ]
            if checks.get(key)
        ),
        "doorbell_observed": bool(checks.get("descriptor_read_verified", False)),
        "status_poll_or_completion_observed": bool(checks.get("driver_status_verified", False) or checks.get("driver_completion_descriptor_verified", False)),
        "mmio_latency_ms": None,
        "unavailable_reason": None if trusted_codesign else "MMIO latency calibration requires real gem5 timing trace beyond proof markers",
    }

    cpu_runtime_trace = {
        "schema_version": "dse.cpu_runtime_trace.v1",
        "codesign_candidate_id": candidate_id,
        "trace_status": execution_trace["trace_status"],
        "completion_policy": (codesign_candidate.get("runtime_schedule", {}) or {}).get("completion_policy", {}) if isinstance(codesign_candidate.get("runtime_schedule", {}), Mapping) else {},
        "driver_status_verified": bool(checks.get("driver_status_verified", False)),
        "driver_completion_descriptor_verified": bool(checks.get("driver_completion_descriptor_verified", False)),
        "host_overhead_ms": None,
        "cpu_occupancy": None,
        "cycles_observed": cycles,
        "unavailable_reason": None if trusted_codesign else "host/runtime timing is blocked until L4 proof and timing markers are complete",
    }

    accelerator_trace = {
        "schema_version": "dse.accelerator_trace.v1",
        "codesign_candidate_id": candidate_id,
        "trace_status": execution_trace["trace_status"],
        "microarchitecture_execute_verified": bool(checks.get("microarchitecture_execute_verified", checks.get("systemc_submit_verified", False))),
        "request_decode_verified": bool(checks.get("request_decode_verified", False)),
        # Deprecated compatibility key for old report readers.  New L4 evidence
        # is the in-gem5 microarchitecture execution marker.
        "systemc_submit_verified": bool(checks.get("systemc_submit_verified", False)),
        "result_status_passed": bool(checks.get("result_status_passed", False)),
        "accelerator_utilization": sim_result.get("resource_utilization", {}) if isinstance(sim_result, Mapping) else {},
        "queue_stall_time_ms": None,
        "compute_latency_ms": metrics.get("device_time_ms"),
    }

    completion_proof = {
        "schema_version": "dse.completion_proof.v1",
        "codesign_candidate_id": candidate_id,
        "passed": bool(
            checks.get("completion_writeback_verified", False)
            and checks.get("driver_status_verified", False)
            and checks.get("driver_completion_descriptor_verified", False)
        ),
        "guest_visible_completion": bool(checks.get("driver_status_verified", False) and checks.get("driver_completion_descriptor_verified", False)),
        "completion_writeback_verified": bool(checks.get("completion_writeback_verified", False)),
        "cycles_observed": cycles,
        "source_artifacts": execution_trace["source_artifacts"],
        "blockers": blockers,
    }

    codesign_verdict = {
        "schema_version": "dse.codesign_verdict.v1",
        "codesign_candidate_id": candidate_id,
        "design_point_id": codesign_candidate.get("design_point_id"),
        "backend": backend,
        "status": "trusted" if trusted_codesign else ("blocked" if backend == "gem5_systemc" else "diagnostic_only"),
        "trusted_for_codesign_ranking": trusted_codesign,
        "trusted_claim": False if not trusted_codesign else "software_visible_single_candidate_feasibility",
        "proof_gate": {
            "gem5_l4_proof": "gem5_l4_proof.json",
            "passed": proof_passed,
            "checks": checks,
        },
        "allowed_claims": list(codesign_candidate.get("expected_claims", []) or []) if trusted_codesign else [],
        "blocked_claims": [] if trusted_codesign else list(codesign_candidate.get("expected_claims", []) or []),
        "evidence_ids": [
            "codesign_candidate.json",
            "l4_execution_trace.json",
            "dma_trace.json",
            "mmio_trace.json",
            "cpu_runtime_trace.json",
            "accelerator_trace.json",
            "completion_proof.json",
            "gem5_l4_proof.json",
            "simulation_result.json",
        ],
        "blockers": blockers,
        "calibration_feedback": {
            "status": "available" if trusted_codesign else "blocked",
            "latency_ms": metrics.get("latency_ms"),
            "host_overhead_ms": cpu_runtime_trace["host_overhead_ms"],
            "dma_time_ms": metrics.get("dma_time_ms"),
            "queue_stall_time_ms": accelerator_trace["queue_stall_time_ms"],
            "software_visible_completion_latency_ms": None,
        },
        "claim_boundary": (
            "Trusted co-design requires guest descriptor submission, GenericAccel request consumption, "
            "in-gem5 microarchitecture execution from that device path, and guest-visible completion."
        ),
    }

    return {
        "l4_execution_trace": execution_trace,
        "dma_trace": dma_trace,
        "mmio_trace": mmio_trace,
        "cpu_runtime_trace": cpu_runtime_trace,
        "accelerator_trace": accelerator_trace,
        "completion_proof": completion_proof,
        "codesign_verdict": codesign_verdict,
    }
