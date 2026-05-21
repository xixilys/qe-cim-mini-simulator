#!/usr/bin/env python3
"""Evidence contract implementation for profile-driven full-flow pilots."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from dse_v2.architecture.catalog import catalog_summary, seed_generic_dse_architecture_catalog
from dse_v2.codesign import (
    CODESIGN_L4_EVIDENCE_ARTIFACTS,
    CODESIGN_STEP2_ARTIFACTS,
    build_codesign_l4_evidence,
    canonicalize_l4_interface_metrics,
    split_codesign_artifacts,
    validate_codesign_artifacts,
)
from dse_v2.core.ir.compute_graph import ComputeGraph, DataEdge
from dse_v2.core.workload.lowering import lower_compute_graph
from dse_v2.core.workload.package import WorkloadPackage, package_from_graph
from dse_v2.core.workload.workflows import required_coverage_from_workflow
from dse_v2.contracts import CONTRACT_VERSION
from dse_v2.dse.orchestrator import DesignPoint
from dse_v2.mapping.search import run_mapping_search

def _profile_required_coverage(
    workload_package: WorkloadPackage,
    compute_graph: ComputeGraph,
    executable_graph: Optional[ComputeGraph],
) -> List[str]:
    """Return the workload-specific node/phase coverage required for full evidence.

    Profiles may declare explicit phase/node coverage.  If they do not, the
    default coverage is the lowered executable graph order.
    """
    graph = executable_graph or compute_graph
    try:
        order = graph.topological_sort()
    except Exception:
        order = []
    return required_coverage_from_workflow(
        workload_package.workload_family,
        workload_package.resolved_workflow(),
        graph.nodes.keys(),
        order,
    )

REQUIRED_EVIDENCE_FILES = [
    "manifest.json",
    "artifact_manifest.json",
    "verdict.json",
    "evidence_requirements.json",
    "claim_validation.json",
    "final_report.json",
    "final_report.md",
    "design_point.json",
    "architecture.json",
    "architecture_catalog.json",
    "mapping.json",
    "mapping_legality_matrix.json",
    "mapping_seed_set.json",
    "mapping_candidate_records.json",
    "mapping_selected_record.json",
    "mapping_simulation_samples.json",
    "mapping_feedback_state.json",
    "convergence_status.json",
    "workload_package.json",
    "workload_graph.json",
    "graph_lowering_report.json",
    "simulation_request.json",
    "simulation_result.json",
    "numerical_validation.json",
    "phase_breakdown.csv",
    "resource_summary.csv",
    "data_movement_summary.csv",
    "systemc_stdout.log",
    "systemc_stderr.log",
]

STEP4_REQUIRED_EVIDENCE_FILES = [
    artifact
    for artifact in REQUIRED_EVIDENCE_FILES
    if artifact not in {"final_report.json", "final_report.md", "numerical_validation.json"}
] + [
    "simulator_consistency_check.json",
    "timing_model_calibration.json",
    "calibration_record.json",
    "feedback_update.json",
    "provenance.json",
]

STEP5_REPORTING_ARTIFACTS = [
    "final_report.json",
    "final_report.md",
    "campaign_summary.json",
    "trusted_ranking.json",
    "pareto_frontier.json",
]

GEM5_UARCH_ENGINE = "gem5_generic_accel_microarchitecture_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _load_optional_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_artifact_path(run_dir: Path, raw_path: Any) -> Optional[Path]:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.exists():
        return path
    candidate = run_dir / path
    if candidate.exists():
        return candidate
    return path if path.is_absolute() else candidate


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _event_map(sim_result: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    events = sim_result.get("events", []) if sim_result else []
    return {str(event.get("node_id")): event for event in events if event.get("node_id")}


def _device_clock_map(sim_request: Mapping[str, Any]) -> Dict[str, float]:
    architecture = sim_request.get("architecture", {}) if sim_request else {}
    host = architecture.get("host", {})
    clocks = {"host": float(host.get("clock_mhz", 3000.0) or 3000.0)}
    for accel in architecture.get("accelerators", []) or []:
        accel_id = accel.get("accel_id")
        if accel_id:
            clocks[str(accel_id)] = float(accel.get("clock_mhz", 250.0) or 250.0)
    return clocks


def _topological_order_from_request(sim_request: Mapping[str, Any]) -> Tuple[List[str], List[str]]:
    workload = sim_request.get("workload", {}) if sim_request else {}
    nodes = workload.get("nodes", {}) or {}
    edges = workload.get("edges", []) or []
    in_degree = {str(node_id): 0 for node_id in sorted(nodes)}
    adjacency: Dict[str, List[str]] = {str(node_id): [] for node_id in sorted(nodes)}
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source in adjacency and target in in_degree:
            adjacency[source].append(target)
            in_degree[target] += 1

    ready = [node_id for node_id in sorted(in_degree) if in_degree[node_id] == 0]
    order: List[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for target in adjacency.get(node_id, []):
            in_degree[target] -= 1
            if in_degree[target] == 0:
                ready.append(target)

    errors = []
    if len(order) != len(nodes):
        errors.append("reference topological sort detected a cycle or missing nodes")
    return order, errors


def _required_phases_from_request(sim_request: Mapping[str, Any]) -> List[str]:
    order, _errors = _topological_order_from_request(sim_request)
    if order:
        return order
    workload = sim_request.get("workload", {}) if sim_request else {}
    nodes = workload.get("nodes", {}) or {}
    return sorted(str(node_id) for node_id in nodes)


def _find_accel(sim_request: Mapping[str, Any], accel_id: str) -> Optional[Mapping[str, Any]]:
    architecture = sim_request.get("architecture", {}) if sim_request else {}
    for accel in architecture.get("accelerators", []) or []:
        if str(accel.get("accel_id")) == accel_id:
            return accel
    return None


def _host_clock_mhz(sim_request: Mapping[str, Any]) -> float:
    architecture = sim_request.get("architecture", {}) if sim_request else {}
    host = architecture.get("host", {}) or {}
    return float(host.get("clock_mhz", 3000.0) or 3000.0)


def _interconnect_bandwidth_gbps(sim_request: Mapping[str, Any]) -> float:
    architecture = sim_request.get("architecture", {}) if sim_request else {}
    interconnect = architecture.get("interconnect") or {}
    return float(interconnect.get("bandwidth_gbps", 64.0) or 64.0)


def _tensor_size_bytes(edge: Mapping[str, Any]) -> float:
    explicit_size = edge.get("size_bytes")
    if explicit_size is not None:
        try:
            return float(explicit_size)
        except (TypeError, ValueError):
            pass
    element_size = edge.get("element_size")
    try:
        size = float(element_size) if element_size is not None else 8.0
    except (TypeError, ValueError):
        size = 8.0
    for dim in edge.get("tensor_shape", []) or []:
        size *= float(dim)
    return size


def _estimate_cycles(node: Mapping[str, Any], accel: Optional[Mapping[str, Any]], sim_request: Mapping[str, Any]) -> Tuple[float, float]:
    flops = float(node.get("estimated_flops", 0.0) or 0.0)
    op_type = str(node.get("op_type", ""))
    if accel is None:
        clock_mhz = _host_clock_mhz(sim_request)
        peak_gflops = clock_mhz * 1e6 * 4.0 / 1e9
        return flops / max(peak_gflops * 1e9, 1e-30) * clock_mhz * 1e6, clock_mhz

    clock_mhz = float(accel.get("clock_mhz", 250.0) or 250.0)
    capabilities = accel.get("capabilities", {}) or {}
    if op_type in {"gemm", "batched_gemm"}:
        capability_key = "gemm"
        fallback_ops_per_cycle = 16.0
    elif op_type == "fft":
        capability_key = "fft"
        fallback_ops_per_cycle = 8.0
    elif op_type in {"eigen", "eigensolver"}:
        capability_key = "eigen"
        fallback_ops_per_cycle = 4.0
    elif op_type in {"reduction", "sum", "max"}:
        capability_key = "reduction"
        fallback_ops_per_cycle = 8.0
    else:
        capability_key = ""
        fallback_ops_per_cycle = 8.0

    capability = capabilities.get(capability_key) if capability_key else None
    if capability:
        peak_gops = float(capability.get("peak_gops", 0.0) or 0.0)
        efficiency = float(capability.get("efficiency", 0.5) or 0.5)
        actual_gops = peak_gops * efficiency
        ops_per_cycle = actual_gops * 1e9 / max(clock_mhz * 1e6, 1e-30)
    else:
        ops_per_cycle = fallback_ops_per_cycle
    return flops / max(ops_per_cycle, 1e-30), clock_mhz


def _reference_timing_result(sim_request: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    workload = sim_request.get("workload", {}) if sim_request else {}
    nodes = workload.get("nodes", {}) or {}
    edges = workload.get("edges", []) or []
    mapping = sim_request.get("mapping", {}) or {}
    order, errors = _topological_order_from_request(sim_request)

    architecture = sim_request.get("architecture", {}) if sim_request else {}
    device_available = {"host": 0.0}
    device_compute = {"host": 0.0}
    device_dma = {"host": 0.0}
    for accel in architecture.get("accelerators", []) or []:
        accel_id = str(accel.get("accel_id"))
        device_available[accel_id] = 0.0
        device_compute[accel_id] = 0.0
        device_dma[accel_id] = 0.0

    node_end_times: Dict[str, float] = {}
    events: List[Dict[str, Any]] = []
    bandwidth_gbps = _interconnect_bandwidth_gbps(sim_request)
    for node_id in order:
        node = nodes[node_id]
        target = str(mapping.get(node_id, "host"))
        accel = None if target == "host" else _find_accel(sim_request, target)
        if target != "host" and accel is None:
            target = "host"

        earliest_start = 0.0
        for edge in edges:
            if str(edge.get("target", "")) != node_id:
                continue
            source = str(edge.get("source", ""))
            if source not in node_end_times:
                continue
            source_device = str(mapping.get(source, "host"))
            transfer_ns = 0.0
            if source_device != target:
                transfer_ns = (_tensor_size_bytes(edge) * 8.0 / max(bandwidth_gbps, 1e-30)) + 800.0
                device_dma[target] = device_dma.get(target, 0.0) + transfer_ns
            earliest_start = max(earliest_start, node_end_times[source] + transfer_ns)

        cycles, clock_mhz = _estimate_cycles(node, accel, sim_request)
        compute_ns = cycles / max(clock_mhz, 1e-30) * 1000.0
        start_ns = max(earliest_start, device_available.get(target, 0.0))
        end_ns = start_ns + compute_ns
        device_available[target] = end_ns
        device_compute[target] = device_compute.get(target, 0.0) + compute_ns
        node_end_times[node_id] = end_ns
        events.append({
            "node_id": node_id,
            "device": target,
            "start_ns": start_ns,
            "end_ns": end_ns,
            "op_type": node.get("op_type", "unknown"),
        })

    total_latency_ns = max(node_end_times.values()) if node_end_times else 0.0
    total_flops = sum(float(node.get("estimated_flops", 0.0) or 0.0) for node in nodes.values())
    latency_ms = total_latency_ns / 1e6
    power_w = sum(float((accel.get("power", {}) or {}).get("static_w", 0.0) or 0.0) for accel in architecture.get("accelerators", []) or [])
    total_data_mb = 0.0
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source in mapping and target in mapping and mapping[source] != mapping[target]:
            total_data_mb += _tensor_size_bytes(edge) / (1024.0 * 1024.0)

    return {
        "events": events,
        "metrics": {
            "latency_ms": latency_ms,
            "device_time_ms": sum(device_compute.values()) / 1e6,
            "dma_time_ms": sum(device_dma.values()) / 1e6,
            "throughput_gops": total_flops / latency_ms / 1e6 if latency_ms > 0.0 else 0.0,
            "power_w": power_w,
            "energy_j": power_w * latency_ms / 1000.0,
            "total_data_movement_mb": total_data_mb,
        },
    }, errors


def _numeric_check(name: str, actual: Any, expected: Any, *, abs_tol: float, rel_tol: float) -> Dict[str, Any]:
    try:
        actual_f = float(actual)
        expected_f = float(expected)
    except (TypeError, ValueError):
        return {
            "name": name,
            "passed": False,
            "actual": actual,
            "expected": expected,
            "reason": "non-numeric value",
        }
    abs_error = abs(actual_f - expected_f)
    rel_error = abs_error / max(abs(expected_f), 1e-30)
    tolerance = max(abs_tol, rel_tol * abs(expected_f))
    passed = math.isfinite(actual_f) and math.isfinite(expected_f) and abs_error <= tolerance
    return {
        "name": name,
        "passed": passed,
        "actual": actual_f,
        "expected": expected_f,
        "abs_error": abs_error,
        "rel_error": rel_error,
        "abs_tolerance": abs_tol,
        "rel_tolerance": rel_tol,
        "effective_tolerance": tolerance,
    }


def _bool_check(
    name: str,
    passed: bool,
    *,
    actual: Any = None,
    expected: Any = True,
    reason: str = "",
) -> Dict[str, Any]:
    check: Dict[str, Any] = {
        "name": name,
        "passed": bool(passed),
        "actual": actual,
        "expected": expected,
    }
    if reason and not passed:
        check["reason"] = reason
    return check


def _finite_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _request_node_map(sim_request: Mapping[str, Any]) -> Mapping[str, Any]:
    workload = sim_request.get("workload", {}) if sim_request else {}
    nodes = workload.get("nodes", {}) if isinstance(workload, Mapping) else {}
    return nodes if isinstance(nodes, Mapping) else {}


def _request_devices(sim_request: Mapping[str, Any]) -> List[str]:
    architecture = sim_request.get("architecture", {}) if sim_request else {}
    devices = ["host"]
    if isinstance(architecture, Mapping):
        for accel in architecture.get("accelerators", []) or []:
            if isinstance(accel, Mapping) and accel.get("accel_id"):
                devices.append(str(accel.get("accel_id")))
    return list(dict.fromkeys(devices))


def _gem5_microarchitecture_validation(
    sim_request: Mapping[str, Any],
    sim_result: Mapping[str, Any],
    required_phases: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Validate the in-gem5 GenericAccel microarchitecture result contract.

    The L4 microarchitecture model intentionally does not have to match the
    standalone L3 generic_sim formula cycle-for-cycle.  This validator therefore
    checks the software-visible L4 result for coverage and internal timing /
    resource consistency instead of comparing it against the L3 reference.
    """
    checks: List[Dict[str, Any]] = []
    metrics = sim_result.get("metrics", {}) if isinstance(sim_result.get("metrics", {}), Mapping) else {}
    summary = (
        sim_result.get("microarchitecture_summary", {})
        if isinstance(sim_result.get("microarchitecture_summary", {}), Mapping)
        else {}
    )
    details = (
        sim_result.get("microarchitecture_details", {})
        if isinstance(sim_result.get("microarchitecture_details", {}), Mapping)
        else {}
    )
    utilization = (
        sim_result.get("resource_utilization", {})
        if isinstance(sim_result.get("resource_utilization", {}), Mapping)
        else {}
    )
    events = [
        dict(event)
        for event in (sim_result.get("events", []) or [])
        if isinstance(event, Mapping)
    ]
    event_by_node = {
        str(event.get("node_id")): event
        for event in events
        if event.get("node_id")
    }
    nodes = _request_node_map(sim_request)
    mapping = sim_request.get("mapping", {}) if isinstance(sim_request.get("mapping", {}), Mapping) else {}
    required_phase_set = set(required_phases or _required_phases_from_request(sim_request))

    checks.append(_bool_check(
        "execution_engine",
        sim_result.get("execution_engine") == GEM5_UARCH_ENGINE,
        actual=sim_result.get("execution_engine"),
        expected=GEM5_UARCH_ENGINE,
        reason="L4 result did not come from the gem5 GenericAccel microarchitecture engine",
    ))
    checks.append(_bool_check(
        "microarchitecture_summary.engine",
        summary.get("engine") == GEM5_UARCH_ENGINE,
        actual=summary.get("engine"),
        expected=GEM5_UARCH_ENGINE,
    ))
    checks.append(_bool_check(
        "events.non_empty",
        bool(events),
        actual=len(events),
        expected=">0",
        reason="gem5 microarchitecture result emitted no compute events",
    ))

    latency_ms = _finite_number(metrics.get("latency_ms"))
    checks.append(_bool_check(
        "metrics.latency_ms.positive",
        latency_ms is not None and latency_ms > 0.0,
        actual=metrics.get("latency_ms"),
        expected="finite > 0",
    ))
    latency_ns = latency_ms * 1.0e6 if latency_ms is not None else None

    event_compute_ns = 0.0
    max_event_end_ns = 0.0
    for phase in sorted(required_phase_set):
        event = event_by_node.get(str(phase))
        checks.append(_bool_check(
            f"event.{phase}.present",
            event is not None,
            actual=event is not None,
            expected=True,
            reason="required workload phase missing from gem5 microarchitecture result",
        ))
        if event is None:
            continue
        node = nodes.get(str(phase), {}) if isinstance(nodes.get(str(phase), {}), Mapping) else {}
        checks.append(_bool_check(
            f"event.{phase}.op_type",
            str(event.get("op_type")) == str(node.get("op_type")),
            actual=event.get("op_type"),
            expected=node.get("op_type"),
        ))
        checks.append(_bool_check(
            f"event.{phase}.device",
            str(event.get("device")) == str(mapping.get(str(phase), "host")),
            actual=event.get("device"),
            expected=mapping.get(str(phase), "host"),
        ))

    for idx, event in enumerate(events):
        name = str(event.get("node_id") or f"event_{idx}")
        start_ns = _finite_number(event.get("start_ns"))
        end_ns = _finite_number(event.get("end_ns"))
        checks.append(_bool_check(
            f"event.{name}.start_ns.finite_non_negative",
            start_ns is not None and start_ns >= 0.0,
            actual=event.get("start_ns"),
            expected="finite >= 0",
        ))
        checks.append(_bool_check(
            f"event.{name}.end_ns.finite_and_ordered",
            start_ns is not None and end_ns is not None and end_ns >= start_ns,
            actual={"start_ns": event.get("start_ns"), "end_ns": event.get("end_ns")},
            expected="finite end_ns >= start_ns",
        ))
        if start_ns is not None and end_ns is not None and end_ns >= start_ns:
            event_compute_ns += end_ns - start_ns
            max_event_end_ns = max(max_event_end_ns, end_ns)
            if latency_ns is not None:
                checks.append(_bool_check(
                    f"event.{name}.within_latency",
                    end_ns <= latency_ns + 5.0,
                    actual=end_ns,
                    expected=f"<= {latency_ns + 5.0}",
                ))

    if latency_ns is not None:
        checks.append(_bool_check(
            "metrics.latency_covers_events",
            latency_ns + 5.0 >= max_event_end_ns,
            actual=latency_ns,
            expected=f">= {max_event_end_ns}",
        ))

    device_time_ms = _finite_number(metrics.get("device_time_ms"))
    if device_time_ms is not None:
        checks.append(_numeric_check(
            "metrics.device_time_ms.matches_event_durations",
            device_time_ms,
            event_compute_ns / 1.0e6,
            abs_tol=1e-6,
            rel_tol=1e-3,
        ))

    total_flops = sum(
        float(node.get("estimated_flops", 0.0) or 0.0)
        for node in nodes.values()
        if isinstance(node, Mapping)
    )
    summary_flops = _finite_number(summary.get("total_flops"))
    checks.append(_numeric_check(
        "microarchitecture_summary.total_flops",
        summary_flops,
        total_flops,
        abs_tol=1.0,
        rel_tol=1e-6,
    ))
    total_cycles = _finite_number(summary.get("total_cycles"))
    checks.append(_bool_check(
        "microarchitecture_summary.total_cycles.positive",
        total_cycles is not None and total_cycles > 0.0,
        actual=summary.get("total_cycles"),
        expected="finite > 0",
    ))
    micro_op_count = _finite_number(summary.get("micro_op_count"))
    checks.append(_bool_check(
        "microarchitecture_summary.micro_op_count_covers_events",
        micro_op_count is not None and micro_op_count >= len(events) + 2,
        actual=summary.get("micro_op_count"),
        expected=f">= {len(events) + 2}",
        reason="micro-op schedule must include decode, compute events, and completion",
    ))
    if latency_ns is not None and total_cycles is not None and total_cycles > 0:
        effective_clock_mhz = total_cycles / latency_ns * 1000.0
        checks.append(_bool_check(
            "microarchitecture_summary.effective_clock_mhz_plausible",
            1.0 <= effective_clock_mhz <= 10000.0,
            actual=effective_clock_mhz,
            expected="1..10000 MHz",
        ))

    power_w = _finite_number(metrics.get("power_w"))
    energy_j = _finite_number(metrics.get("energy_j"))
    if power_w is not None and latency_ms is not None and energy_j is not None:
        checks.append(_numeric_check(
            "metrics.energy_j.matches_power_latency",
            energy_j,
            power_w * latency_ms / 1000.0,
            abs_tol=1e-6,
            rel_tol=1e-4,
        ))
    throughput_gops = _finite_number(metrics.get("throughput_gops"))
    if throughput_gops is not None and latency_ms is not None and latency_ms > 0.0:
        checks.append(_numeric_check(
            "metrics.throughput_gops.matches_flops_latency",
            throughput_gops,
            total_flops / latency_ms / 1.0e6,
            abs_tol=1e-6,
            rel_tol=1e-3,
        ))

    for device in _request_devices(sim_request):
        checks.append(_bool_check(
            f"microarchitecture_details.{device}.present",
            device in details,
            actual=device in details,
            expected=True,
        ))
        checks.append(_bool_check(
            f"resource_utilization.{device}.present",
            device in utilization,
            actual=device in utilization,
            expected=True,
        ))
        detail = details.get(device, {}) if isinstance(details.get(device, {}), Mapping) else {}
        for key in ["compute_cycles", "dma_cycles", "stall_cycles", "memory_accesses"]:
            value = _finite_number(detail.get(key))
            checks.append(_bool_check(
                f"microarchitecture_details.{device}.{key}.non_negative",
                value is not None and value >= 0.0,
                actual=detail.get(key),
                expected="finite >= 0",
            ))
        for key in ["pipeline_utilization", "array_utilization"]:
            value = _finite_number(detail.get(key))
            checks.append(_bool_check(
                f"microarchitecture_details.{device}.{key}.range",
                value is not None and 0.0 <= value <= 1.0,
                actual=detail.get(key),
                expected="0..1",
            ))
        util = utilization.get(device, {}) if isinstance(utilization.get(device, {}), Mapping) else {}
        for key in ["compute_percent", "memory_percent", "bandwidth_percent"]:
            value = _finite_number(util.get(key))
            checks.append(_bool_check(
                f"resource_utilization.{device}.{key}.range",
                value is not None and 0.0 <= value <= 100.0,
                actual=util.get(key),
                expected="0..100",
            ))

    failed = [check for check in checks if not check.get("passed", False)]
    max_abs_error = max((float(check.get("abs_error", 0.0) or 0.0) for check in checks), default=0.0)
    max_rel_error = max((float(check.get("rel_error", 0.0) or 0.0) for check in checks), default=0.0)
    return {
        "schema_version": "dse.numerical_validation.v1",
        "status": "pass" if not failed else "fail",
        "passed": not failed,
        "scope": "gem5_microarchitecture_timing_internal_consistency",
        "reference_model": "in-gem5 GenericAccel microarchitecture result contract and conservation checks",
        "profile_domain_correctness_claimed": False,
        "domain_correctness_boundary": (
            "Validates L4 timing/resource internal consistency and required phase coverage only; "
            "it does not prove profile-specific numerical/domain correctness."
        ),
        "tolerances": {
            "event_time_abs_ns": 5.0,
            "internal_formula_abs": 1e-6,
            "internal_formula_rel": 1e-4,
        },
        "summary": {
            "check_count": len(checks),
            "failed_check_count": len(failed),
            "max_abs_error": max_abs_error,
            "max_rel_error": max_rel_error,
        },
        "failed_checks": failed[:20],
        "checks": checks,
    }


def build_numerical_validation(
    sim_request: Mapping[str, Any],
    sim_result: Mapping[str, Any],
    required_phases: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Compare simulator numeric outputs with an independent Python reference.

    This validates the timing-level SystemC/generic-simulator numeric result
    contract.  It does not claim profile/importer-domain correctness, convergence,
    application-level equivalence, or board/ASIC measurements.
    """
    if not sim_result or sim_result.get("status") != "passed":
        return {
            "schema_version": "dse.numerical_validation.v1",
            "status": "unavailable",
            "passed": False,
            "scope": "generic_systemc_timing_numeric_reference",
            "profile_domain_correctness_claimed": False,
            "reason": "simulation result did not pass, so numeric timing reference comparison is unavailable",
            "checks": [],
            "summary": {"check_count": 0, "failed_check_count": 0},
        }

    if sim_result.get("execution_engine") == GEM5_UARCH_ENGINE:
        return _gem5_microarchitecture_validation(sim_request, sim_result, required_phases)

    reference, errors = _reference_timing_result(sim_request)
    checks: List[Dict[str, Any]] = []
    if errors:
        checks.append({
            "name": "reference_topology",
            "passed": False,
            "reason": "; ".join(errors),
        })

    result_events = {
        str(event.get("node_id")): event
        for event in sim_result.get("events", []) or []
        if event.get("node_id")
    }
    required_phase_set = set(required_phases or _required_phases_from_request(sim_request))
    for event in reference["events"]:
        node_id = str(event["node_id"])
        actual = result_events.get(node_id)
        if actual is None:
            checks.append({
                "name": f"event.{node_id}.present",
                "passed": False,
                "reason": "simulator did not emit event",
            })
            continue
        checks.append({
            "name": f"event.{node_id}.device",
            "passed": str(actual.get("device")) == str(event.get("device")),
            "actual": actual.get("device"),
            "expected": event.get("device"),
        })
        checks.append({
            "name": f"event.{node_id}.op_type",
            "passed": str(actual.get("op_type")) == str(event.get("op_type")),
            "actual": actual.get("op_type"),
            "expected": event.get("op_type"),
        })
        if node_id in required_phase_set:
            checks.append(_numeric_check(f"event.{node_id}.start_ns", actual.get("start_ns"), event.get("start_ns"), abs_tol=5.0, rel_tol=1e-5))
            checks.append(_numeric_check(f"event.{node_id}.end_ns", actual.get("end_ns"), event.get("end_ns"), abs_tol=5.0, rel_tol=1e-5))

    metrics = sim_result.get("metrics", {}) or {}
    for metric, expected in reference["metrics"].items():
        checks.append(_numeric_check(f"metrics.{metric}", metrics.get(metric), expected, abs_tol=1e-9, rel_tol=1e-5))

    failed = [check for check in checks if not check.get("passed", False)]
    max_abs_error = max((float(check.get("abs_error", 0.0) or 0.0) for check in checks), default=0.0)
    max_rel_error = max((float(check.get("rel_error", 0.0) or 0.0) for check in checks), default=0.0)
    return {
        "schema_version": "dse.numerical_validation.v1",
        "status": "pass" if not failed else "fail",
        "passed": not failed,
        "scope": "generic_systemc_timing_numeric_reference",
        "reference_model": "independent Python reproduction of generic_sim graph scheduling, transfer, and metric formulas",
        "profile_domain_correctness_claimed": False,
        "domain_correctness_boundary": (
            "Validates timing-level numeric outputs only; does not prove profile-specific domain "
            "correctness, convergence, application-level equivalence, or physical-system correctness."
        ),
        "tolerances": {
            "event_time_abs_ns": 5.0,
            "event_time_rel": 1e-5,
            "metric_abs": 1e-9,
            "metric_rel": 1e-5,
        },
        "summary": {
            "check_count": len(checks),
            "failed_check_count": len(failed),
            "max_abs_error": max_abs_error,
            "max_rel_error": max_rel_error,
        },
        "failed_checks": failed[:20],
        "checks": checks,
    }


def build_simulator_consistency_check(numerical_validation: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the Step4 canonical simulator-consistency artifact.

    The legacy builder name is retained for compatibility, but the staged
    Step3/Step4/Step5 contract no longer treats ``numerical_validation.json`` as
    the canonical timing-simulator artifact.  Step4 writes this renamed payload.
    """
    summary = numerical_validation.get("summary", {}) if isinstance(numerical_validation.get("summary", {}), Mapping) else {}
    return {
        "schema_version": "dse.simulator_consistency_check.v1",
        "status": numerical_validation.get("status", "unavailable"),
        "passed": bool(numerical_validation.get("passed", False)),
        "scope": numerical_validation.get("scope"),
        "reference_model": numerical_validation.get("reference_model"),
        "profile_domain_correctness_claimed": False,
        "domain_correctness_boundary": numerical_validation.get(
            "domain_correctness_boundary",
            "Simulator consistency checks do not prove profile-specific domain correctness.",
        ),
        "summary": dict(summary),
        "tolerances": dict(numerical_validation.get("tolerances", {}) or {}),
        "failed_checks": list(numerical_validation.get("failed_checks", []) or []),
        "checks": list(numerical_validation.get("checks", []) or []),
        "legacy_replacement": {
            "replaces": "numerical_validation.json",
            "reason": "timing-simulator consistency is Step4 adjudication evidence, not Step3 numerical correctness",
        },
    }


def build_phase_results(
    sim_result: Mapping[str, Any],
    sim_request: Mapping[str, Any],
    required_phases: Optional[Iterable[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    events = _event_map(sim_result)
    clocks = _device_clock_map(sim_request)
    phases: Dict[str, Dict[str, Any]] = {}
    for phase in (list(required_phases) if required_phases is not None else _required_phases_from_request(sim_request)):
        event = events.get(phase)
        if not event:
            phases[phase] = {
                "status": "unavailable",
                "unavailable_reason": "no timing event emitted by simulator for required workload phase/node",
            }
            continue
        start_ns = float(event.get("start_ns", 0.0) or 0.0)
        end_ns = float(event.get("end_ns", 0.0) or 0.0)
        latency_ns = max(0.0, end_ns - start_ns)
        device = str(event.get("device", "unknown"))
        clock_mhz = clocks.get(device)
        phases[phase] = {
            "status": "available",
            "node_id": phase,
            "op_type": event.get("op_type", "unknown"),
            "device": device,
            "start_ns": start_ns,
            "end_ns": end_ns,
            "latency_ns": latency_ns,
            "latency_ms": latency_ns / 1e6,
            "cycles_estimate": latency_ns * clock_mhz / 1000.0 if clock_mhz else None,
            "clock_mhz": clock_mhz,
        }
    return phases


def _write_phase_breakdown(path: Path, phase_results: Mapping[str, Mapping[str, Any]]) -> None:
    fields = [
        "phase",
        "node_id",
        "op_type",
        "device",
        "start_ns",
        "end_ns",
        "latency_ns",
        "latency_ms",
        "cycles_estimate",
        "clock_mhz",
        "status",
        "unavailable_reason",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for phase, data in phase_results.items():
            row = {field: data.get(field, "") for field in fields}
            row["phase"] = phase
            writer.writerow(row)


def _write_resource_summary(
    path: Path,
    sim_result: Mapping[str, Any],
) -> None:
    events = sim_result.get("events", []) if sim_result else []
    event_compute_ms: Dict[str, float] = {}
    for event in events:
        device = str(event.get("device", "unknown"))
        latency_ms = max(0.0, float(event.get("end_ns", 0.0) or 0.0) - float(event.get("start_ns", 0.0) or 0.0)) / 1e6
        event_compute_ms[device] = event_compute_ms.get(device, 0.0) + latency_ms
    utilization = sim_result.get("resource_utilization", {}) if sim_result else {}
    devices = sorted(set(event_compute_ms) | set(utilization))
    fields = ["device", "compute_percent", "memory_percent", "bandwidth_percent", "event_compute_time_ms"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for device in devices:
            util = utilization.get(device, {}) or {}
            writer.writerow({
                "device": device,
                "compute_percent": util.get("compute_percent", ""),
                "memory_percent": util.get("memory_percent", ""),
                "bandwidth_percent": util.get("bandwidth_percent", ""),
                "event_compute_time_ms": event_compute_ms.get(device, 0.0),
            })


def _edge_size(edge: DataEdge) -> Tuple[int, float]:
    if edge.tensor_spec is None:
        return 0, 0.0
    size_bytes = edge.tensor_spec.size_bytes()
    return size_bytes, size_bytes / (1024.0 * 1024.0)


def _write_data_movement_summary(
    path: Path,
    graph: ComputeGraph,
    mapping: Mapping[str, str],
) -> None:
    fields = [
        "edge_id",
        "source",
        "target",
        "tensor_name",
        "source_device",
        "target_device",
        "size_bytes",
        "size_mb",
        "cross_device",
        "status",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for idx, edge in enumerate(graph.edges):
            source_device = mapping.get(edge.source_node, "host")
            target_device = mapping.get(edge.target_node, "host")
            size_bytes, size_mb = _edge_size(edge)
            cross = source_device != target_device
            writer.writerow({
                "edge_id": f"edge_{idx}",
                "source": edge.source_node,
                "target": edge.target_node,
                "tensor_name": edge.tensor_name,
                "source_device": source_device,
                "target_device": target_device,
                "size_bytes": size_bytes,
                "size_mb": f"{size_mb:.9f}",
                "cross_device": str(cross).lower(),
                "status": "cross_device_transfer" if cross else "same_device",
            })


def claim_can_be_trusted(claim: Mapping[str, Any], verdict: Optional[Mapping[str, Any]] = None) -> bool:
    """Return whether a final report claim is allowed in trusted ranking.

    L1/L2 analytical/TLM or predicted-only claims are never trusted final-ranking
    evidence. A claim needs SystemC/gem5+SystemC backing and at least one evidence id.
    """
    if claim.get("predicted_only"):
        return False
    fidelity = str(claim.get("fidelity", claim.get("source_fidelity", ""))).lower()
    if fidelity in {"l1", "l2", "analytical", "tlm", "surrogate", "predicted"}:
        return False
    backend = str(claim.get("backend", claim.get("source_backend", ""))).lower()
    if backend not in {"systemc", "gem5_systemc"}:
        return False
    if not claim.get("evidence_ids"):
        return False
    if verdict is not None and not verdict.get("trusted_for_final_ranking", False):
        return False
    return True


def _parse_gem5_stats_file(path: Path) -> Dict[str, float]:
    """Parse scalar numeric counters from gem5's m5out stats.txt."""
    if not path.exists():
        return {}
    metrics: Dict[str, float] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("----------"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            value = float(parts[1])
        except ValueError:
            continue
        if math.isfinite(value):
            metrics[parts[0]] = value
    return metrics


def classify_gem5_l4_non_smoke(
    gem5_log: Optional[str],
    sim_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """Classify whether gem5 GenericAccel evidence is more than smoke/descriptor-only.

    Descriptor ingestion and completion markers are necessary but not sufficient:
    completion eligibility also requires decoded request execution plus non-zero
    accelerator-side activity in the L4 result.
    """
    log = gem5_log or ""
    summary = sim_result.get("microarchitecture_summary", {}) if isinstance(sim_result.get("microarchitecture_summary", {}), Mapping) else {}
    engine = str(sim_result.get("execution_engine") or summary.get("engine") or "")
    events = [event for event in sim_result.get("events", []) or [] if isinstance(event, Mapping)]
    accelerator_events = [
        event for event in events
        if str(event.get("device", "host")) not in {"", "host", "cpu", "host-0"}
    ]

    def _positive_number(value: Any) -> bool:
        try:
            return float(value) > 0.0
        except (TypeError, ValueError):
            return False

    checks = {
        "descriptor_read_verified": "descriptor_read verified=true" in log,
        "request_decode_verified": "uarch_request_decode verified=true" in log,
        "microarchitecture_execute_verified": "microarchitecture_execute verified=true" in log,
        "result_status_passed": sim_result.get("status") == "passed",
        "accelerator_event_count": len(accelerator_events),
        "microarchitecture_summary_present": bool(summary),
        "generic_accel_engine": engine == "gem5_generic_accel_microarchitecture_v1",
        "micro_op_count_positive": _positive_number(summary.get("micro_op_count")),
        "total_cycles_positive": _positive_number(summary.get("total_cycles")),
    }
    engine_activity = bool(
        checks["generic_accel_engine"]
        and checks["micro_op_count_positive"]
        and checks["total_cycles_positive"]
    )
    if not checks["descriptor_read_verified"]:
        classification = "not_observed"
        reasons = ["descriptor_read marker is absent"]
    elif not checks["request_decode_verified"] and not checks["microarchitecture_execute_verified"]:
        classification = "descriptor_only"
        reasons = ["descriptor/completion markers without in-gem5 request decode or microarchitecture execution are descriptor-only evidence"]
    elif not accelerator_events and not engine_activity:
        classification = "smoke_or_host_only"
        reasons = ["L4 result contains no non-host GenericAccel activity events"]
    elif checks["microarchitecture_summary_present"] and (not checks["micro_op_count_positive"] or not checks["total_cycles_positive"]):
        classification = "smoke_or_zero_activity"
        reasons = ["L4 microarchitecture summary has zero or missing micro-op/cycle counts"]
    elif not checks["result_status_passed"]:
        classification = "failed_l4_result"
        reasons = ["L4 result JSON did not pass"]
    elif checks["request_decode_verified"] and checks["microarchitecture_execute_verified"]:
        classification = "non_smoke"
        reasons = []
    else:
        classification = "incomplete_l4_execution"
        reasons = ["request decode and microarchitecture execution markers must both be present"]

    return {
        "schema_version": "dse.gem5_l4_non_smoke_classification.v1",
        "classification": classification,
        "completion_eligible": classification == "non_smoke",
        "checks": checks,
        "accelerator_devices": sorted({
            str(event.get("device"))
            for event in accelerator_events
            if event.get("device")
        }),
        "reasons": reasons,
        "claim_boundary": (
            "Non-smoke L4 completion requires descriptor ingestion, request decode, "
            "in-gem5 microarchitecture execution, a passed L4 result, and non-zero "
            "accelerator-side activity; descriptor-only or smoke/host-only evidence is rejected."
        ),
    }


def build_gem5_l4_proof(
    gem5_log: Optional[str],
    gem5_stdout: Optional[str],
    sim_result: Mapping[str, Any],
    source_artifacts: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Audit real gem5 GenericAccel microarchitecture descriptor evidence.

    This is deliberately stricter than a gem5 process returning 0: it requires
    the GenericAccel debug log to prove descriptor ingestion, in-gem5 request
    decode, microarchitecture execution, and completion writeback, plus the
    guest driver to observe success.
    """
    log = gem5_log or ""
    stdout = gem5_stdout or ""
    artifact_sources = dict(source_artifacts or {})
    request_decode_verified = "uarch_request_decode verified=true" in log
    microarchitecture_execute_verified = "microarchitecture_execute verified=true" in log
    summary = sim_result.get("microarchitecture_summary", {}) if isinstance(sim_result.get("microarchitecture_summary", {}), Mapping) else {}
    events = [event for event in sim_result.get("events", []) or [] if isinstance(event, Mapping)]
    accelerator_events = [
        event for event in events
        if str(event.get("device", "host")) not in {"", "host", "cpu", "host-0"}
    ]

    def _artifact_exists(key: str) -> bool:
        value = artifact_sources.get(key)
        return bool(value) and Path(str(value)).exists()

    def _positive_number(value: Any) -> bool:
        try:
            return float(value) > 0.0
        except (TypeError, ValueError):
            return False

    require_stats_config = bool(artifact_sources.get("require_gem5_stats_config", False))
    required_stats = ["simTicks", "finalTick", "simInsts", "simOps", "system.cpu.numCycles"]
    stats_path_value = artifact_sources.get("gem5_stats")
    stats_metrics = _parse_gem5_stats_file(Path(str(stats_path_value))) if stats_path_value else {}
    stats_missing = [name for name in required_stats if name not in stats_metrics]
    stats_nonpositive = [name for name in required_stats if name in stats_metrics and not _positive_number(stats_metrics[name])]
    stats_semantics_present = not stats_missing and not stats_nonpositive
    nonzero_activity = bool(
        accelerator_events
        and _positive_number(summary.get("micro_op_count"))
        and _positive_number(summary.get("total_cycles"))
        and microarchitecture_execute_verified
    )
    non_smoke_classification = classify_gem5_l4_non_smoke(log, sim_result)
    checks = {
        "descriptor_read_verified": "descriptor_read verified=true" in log,
        "request_decode_verified": request_decode_verified,
        "microarchitecture_execute_verified": microarchitecture_execute_verified,
        "systemc_submit_verified": "systemc_submit verified=true" in log,
        "legacy_systemc_or_microarchitecture_verified": (
            "systemc_submit verified=true" in log or microarchitecture_execute_verified
        ),
        "completion_writeback_verified": "completion_writeback verified=true" in log,
        "driver_status_verified": "generic_accel_l4_status=1 error_code=0" in stdout,
        "driver_completion_descriptor_verified": (
            "completion_magic=0x4753494d completion_status=0" in stdout
            or "completion_magic=0x4753494D completion_status=0" in stdout
        ),
        "result_status_passed": sim_result.get("status") == "passed",
        "non_smoke_l4_activity": bool(non_smoke_classification.get("completion_eligible", False)),
    }
    if require_stats_config:
        checks.update({
            "stats_txt_present": _artifact_exists("gem5_stats"),
            "stats_semantics_present": stats_semantics_present,
            "config_present": _artifact_exists("gem5_config_ini") or _artifact_exists("gem5_config_json"),
            "nonzero_accelerator_activity": nonzero_activity,
        })
    required = [
        ("descriptor_read_verified", "gem5.log must contain descriptor_read verified=true"),
        ("request_decode_verified", "gem5.log must contain uarch_request_decode verified=true"),
        ("microarchitecture_execute_verified", "gem5.log must contain microarchitecture_execute verified=true"),
        ("completion_writeback_verified", "gem5.log must contain completion_writeback verified=true"),
        ("driver_status_verified", "driver stdout must contain generic_accel_l4_status=1 error_code=0"),
        ("driver_completion_descriptor_verified", "driver stdout must show GSIM completion descriptor status 0"),
        ("result_status_passed", "L4 result JSON must have status=passed"),
        ("non_smoke_l4_activity", "L4 evidence must classify as non-smoke GenericAccel activity; descriptor-only or smoke/host-only evidence is not completion evidence"),
    ]
    if require_stats_config:
        required.extend([
            ("stats_txt_present", "gem5 m5out stats.txt must be preserved in the evidence directory"),
            ("stats_semantics_present", "gem5 m5out stats.txt must contain positive simTicks/finalTick/simInsts/simOps/system.cpu.numCycles counters"),
            ("config_present", "gem5 m5out config.ini or config.json must be preserved in the evidence directory"),
            ("nonzero_accelerator_activity", "L4 result must contain non-zero GenericAccel activity on at least one accelerator device"),
        ])
    missing = [detail for key, detail in required if not checks[key]]
    artifact_sources.setdefault("gem5_log", "gem5.log")
    artifact_sources.setdefault("gem5_stdout", "systemc_stdout.log")
    artifact_sources.setdefault("gem5_stderr", "systemc_stderr.log")
    artifact_sources.setdefault("simulation_request", "simulation_request.json")
    artifact_sources.setdefault("simulation_result", "simulation_result.json")
    artifact_sources.setdefault("gem5_command_descriptor", "gem5_command_descriptor.json")
    artifact_sources.setdefault("gem5_completion_descriptor", "gem5_completion_descriptor.json")
    transport_harness = str(artifact_sources.get("transport_harness") or "gem5_generic_accel")
    fallback_from_gem5 = bool(artifact_sources.get("fallback_from_gem5", False))
    return {
        "schema_version": "dse.gem5_l4_proof.v1",
        "passed": not missing,
        "proof_status": "passed" if not missing else "failed",
        "transport_harness": transport_harness,
        "fallback_from_gem5": fallback_from_gem5,
        "required_checks": [key for key, _ in required],
        "checks": checks,
        "non_smoke_classification": non_smoke_classification,
        "missing_evidence": missing,
        "gem5_stats_summary": {
            "required_fields": required_stats,
            "parsed_required_fields": {name: stats_metrics.get(name) for name in required_stats if name in stats_metrics},
            "missing_fields": stats_missing,
            "nonpositive_fields": stats_nonpositive,
        } if require_stats_config else {},
        "source_artifacts": artifact_sources,
        "claim_boundary": (
            "L4 gem5 GenericAccel is trusted only when guest descriptor submission, "
            "in-gem5 request decode, microarchitecture execution, completion writeback, "
            "and guest-visible completion are all observed; it is not a profile-domain correctness claim."
        ),
    }


def _artifact_entries(run_dir: Path, required_files: Iterable[str]) -> List[Dict[str, Any]]:
    entries = []
    for rel in sorted(set(required_files)):
        path = run_dir / rel
        entry: Dict[str, Any] = {
            "path": rel,
            "required": rel in STEP4_REQUIRED_EVIDENCE_FILES or rel in STEP5_REPORTING_ARTIFACTS,
            "exists": path.exists(),
        }
        if path.exists() and path.is_file():
            entry.update({
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            })
        else:
            entry["unavailable_reason"] = "not generated for this backend/run"
        entries.append(entry)
    return entries


def _hash_existing_artifacts(run_dir: Path, names: Iterable[str]) -> Dict[str, str]:
    """Return sha256 bindings for source artifacts that exist in ``run_dir``."""

    hashes: Dict[str, str] = {}
    for name in names:
        rel = str(name)
        path = run_dir / rel
        if path.exists() and path.is_file():
            hashes[rel] = f"sha256:{_sha256(path)}"
    return hashes


def _control_plane_scope(
    *,
    workload_package: WorkloadPackage,
    compute_graph: ComputeGraph,
    design_point: DesignPoint,
) -> Dict[str, str]:
    """Derive stable Campaign/WorkloadRun/Trial IDs for canonical Step4 artifacts.

    Older pilot paths do not yet allocate real registry IDs before calling this
    writer.  Until those paths are fully ledger-owned, the emitted artifacts use
    deterministic IDs derived from the workload/design-point identity so schema
    validation and artifact hash binding remain explicit instead of absent.
    """

    source = workload_package.source if isinstance(workload_package.source, Mapping) else {}
    metadata = compute_graph.metadata if isinstance(compute_graph.metadata, Mapping) else {}
    config = design_point.config if isinstance(design_point.config, Mapping) else {}
    workload_id = str(workload_package.workload_id or compute_graph.graph_id or "workload")
    design_point_id = str(design_point.design_point_id or "design-point")
    return {
        "campaign_id": str(source.get("campaign_id") or metadata.get("campaign_id") or f"campaign-{workload_id}"),
        "workload_run_id": str(source.get("workload_run_id") or metadata.get("workload_run_id") or f"workload-run-{workload_id}"),
        "trial_id": str(config.get("trial_id") or metadata.get("trial_id") or f"trial-{design_point_id}"),
    }


def write_full_flow_evidence(
    *,
    run_dir: Path,
    backend: str,
    evidence_mode: str,
    design_point: DesignPoint,
    compute_graph: ComputeGraph,
    simulation_request: Mapping[str, Any],
    simulation_result: Optional[Mapping[str, Any]],
    simulator_cmd: List[str],
    simulator_returncode: int,
    systemc_stdout: str,
    systemc_stderr: str,
    cli_command: List[str],
    gem5_attempted: bool = False,
    gem5_log: Optional[str] = None,
    gem5_source_artifacts: Optional[Mapping[str, Any]] = None,
    additional_feedback_samples: Optional[Iterable[Mapping[str, Any]]] = None,
    extra_artifact_paths: Optional[Iterable[str]] = None,
    feedback_sample_budget: Optional[int] = None,
    workload_package: Optional[WorkloadPackage] = None,
    codesign_candidate: Optional[Mapping[str, Any]] = None,
    emit_step4_artifacts: bool = True,
    emit_step5_artifacts: bool = True,
) -> Dict[str, Any]:
    """Write staged evidence artifacts for a selected full workload package.

    ``emit_step4_artifacts=False`` is used by Step3-only workflows: simulation
    request/result/log artifacts are written, while canonical adjudication and
    reporting artifacts remain absent until Step4/Step5 APIs are invoked.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_result = dict(simulation_result or {})
    workload_package = workload_package or package_from_graph(
        compute_graph,
        workload_id=compute_graph.graph_id,
        workload_family=str(compute_graph.metadata.get("workload_family", "dynamic_custom")),
        profile_id=str(compute_graph.metadata.get("profile_id", compute_graph.metadata.get("workload_family", "dynamic_custom"))),
        importer_id=str(compute_graph.metadata.get("importer_id", "direct_graph")),
        claim_boundary=str(compute_graph.metadata.get("claim_boundary", "full_workload")),
        source_kind="generated",
    )
    graph_lowering = lower_compute_graph(compute_graph, workload_package)
    lowering_report = graph_lowering.report
    required_coverage = _profile_required_coverage(workload_package, compute_graph, graph_lowering.executable_graph)
    phase_results = build_phase_results(raw_result, simulation_request, required_coverage)
    missing_phases = [p for p, r in phase_results.items() if r.get("status") != "available"]
    simulation_passed = simulator_returncode == 0 and raw_result.get("status") == "passed"
    numerical_validation = build_numerical_validation(simulation_request, raw_result, required_coverage)
    simulator_consistency_check = build_simulator_consistency_check(numerical_validation)
    numerical_passed = bool(simulator_consistency_check.get("passed", False))
    gem5_l4_proof = build_gem5_l4_proof(gem5_log, systemc_stdout, raw_result, gem5_source_artifacts) if backend == "gem5_systemc" else {
        "schema_version": "dse.gem5_l4_proof.v1",
        "passed": False,
        "proof_status": "not_applicable",
        "required_checks": [],
        "checks": {},
        "missing_evidence": ["backend is not gem5_systemc"],
        "source_artifacts": {},
        "claim_boundary": "not applicable to standalone SystemC runs",
    }
    raw_l4_observations_artifact = None
    l4_interface_metrics: Dict[str, Any] = {}
    if backend == "gem5_systemc":
        source_artifacts = gem5_l4_proof.get("source_artifacts", {})
        if isinstance(source_artifacts, Mapping):
            raw_l4_observations_artifact = source_artifacts.get("raw_l4_interface_observations")
        raw_l4_path = _resolve_artifact_path(run_dir, raw_l4_observations_artifact)
        raw_l4_observations = _load_optional_json(raw_l4_path) if raw_l4_path is not None else {}
        l4_interface_metrics = canonicalize_l4_interface_metrics(
            raw_l4_observations,
            gem5_l4_proof=gem5_l4_proof,
            raw_observations_artifact=str(raw_l4_observations_artifact) if raw_l4_observations_artifact else None,
        )
    full_workload_eligible = bool(lowering_report.get("full_workload_eligible", False)) and workload_package.is_full_workload()
    trusted_systemc = backend == "systemc" and simulation_passed and not missing_phases and numerical_passed and full_workload_eligible
    trusted_gem5_systemc = (
        backend == "gem5_systemc"
        and simulation_passed
        and not missing_phases
        and numerical_passed
        and full_workload_eligible
        and gem5_attempted
        and bool(gem5_l4_proof.get("passed", False))
    )
    trusted_for_final = trusted_systemc or trusted_gem5_systemc
    run_id = str(simulation_request.get("run_id", design_point.design_point_id))
    codesign_artifacts = split_codesign_artifacts(codesign_candidate)
    codesign_validation = (
        validate_codesign_artifacts(codesign_artifacts)
        if codesign_artifacts.get("codesign_candidate")
        else {
            "schema_version": "dse.codesign_artifact_validation.v1",
            "valid": False,
            "errors": [{"field": "codesign_candidate", "message": "no Step2 co-design candidate supplied"}],
            "warnings": [],
            "checked_artifacts": [],
        }
    )

    design_point_payload = design_point.to_dict()
    catalog = seed_generic_dse_architecture_catalog()
    catalog_payload = catalog.to_dict()
    catalog_payload["summary"] = catalog_summary(catalog)
    catalog_payload["required_workload_ops"] = sorted({node.op_type for node in compute_graph.nodes.values()})
    architecture_payload = {
        "architecture_id": design_point.system_architecture.system_id,
        "architecture_family": "generic_heterogeneous_pilot",
        "architecture_scope": "broad host plus heterogeneous accelerator timing-level pilot; not hardcoded to any single cluster template",
        "catalog_version": catalog.version,
        "catalog_default_instance": "balanced-generic-systemc-v0",
        "legacy_four_cluster_role": "reference_candidate_only_not_default",
        "status": "implemented" if trusted_for_final else "unverified",
        "trusted_final_eligible": trusted_for_final,
        "system_architecture": design_point.system_architecture.to_dict(),
    }
    workload_package_payload = workload_package.to_dict()
    workload_payload = compute_graph.to_dict()
    workflow_payload = workload_package.resolved_workflow()
    workflow_domain_validation = workflow_payload.get("domain_validation", {}) if isinstance(workflow_payload.get("domain_validation", {}), Mapping) else {}
    profile_domain_validation = {
        "status": "unavailable_unclaimed",
        "correctness_claimed": False,
        "correctness_claim_requires_profile_evidence": bool(
            workflow_domain_validation.get(
                "correctness_claim_requires_profile_evidence",
                workflow_domain_validation.get("correctness_claim_requires_adapter_evidence", True),
            )
        ),
        "required_artifacts": list(workflow_domain_validation.get("correctness_artifacts", []) or []),
        "boundary": workflow_domain_validation.get(
            "unclaimed_domain_correctness",
            "Profile/importer-domain correctness is not inferred from generic timing evidence.",
        ),
        "timing_only_allowed": bool(workflow_domain_validation.get("timing_only_allowed", True)),
    }
    unavailable_metric_records = [
        {"metric": "phase_timing", "phases": missing_phases, "reason": "simulator did not emit events"}
    ] if missing_phases else []
    unavailable_metric_records.extend(
        {
            "metric": str(label),
            "scope": "profile_domain_validation",
            "reason": "profile/importer-domain validator evidence was not supplied; generic timing evidence does not claim this metric",
        }
        for label in workflow_payload.get("unavailable_metric_labels", []) or []
    )

    public_result = dict(raw_result)
    gem5_uarch_result = raw_result.get("execution_engine") == GEM5_UARCH_ENGINE
    public_result.update({
        "backend": backend,
        "timing_level": True,
        "trusted_timing_source": (
            "SystemC/generic timing backend"
            if backend == "systemc"
            else "gem5 GenericAccel microarchitecture backend"
            if gem5_uarch_result
            else "gem5+SystemC"
        ),
        "workload_package": {
            "artifact": "workload_package.json",
            "workload_id": workload_package.workload_id,
            "workload_family": workload_package.workload_family,
            "profile_id": workload_package.profile_id,
            "profile_version": workload_package.profile_version,
            "importer_id": workload_package.importer_id,
            "importer_version": workload_package.importer_version,
            "claim_boundary": workload_package.claim_boundary,
        },
        "graph_lowering": {
            "artifact": "graph_lowering_report.json",
            "status": lowering_report.get("status"),
            "full_workload_eligible": lowering_report.get("full_workload_eligible", False),
        },
        "workflow": workflow_payload,
        "required_coverage": required_coverage,
        "profile_required_coverage": required_coverage,
        "domain_validation": profile_domain_validation,
        "profile_domain_validation": profile_domain_validation,
        "required_workload_phases": required_coverage,
        "phase_results": phase_results,
        "missing_required_coverage": missing_phases,
        "simulator_consistency_check": {
            "artifact": "simulator_consistency_check.json",
            "status": simulator_consistency_check.get("status"),
            "passed": numerical_passed,
            "scope": simulator_consistency_check.get("scope"),
            "summary": simulator_consistency_check.get("summary", {}),
        },
        "gem5_l4_proof": {
            "artifact": "gem5_l4_proof.json",
            "passed": bool(gem5_l4_proof.get("passed", False)),
            "proof_status": gem5_l4_proof.get("proof_status"),
            "checks": gem5_l4_proof.get("checks", {}),
            "source_artifacts": gem5_l4_proof.get("source_artifacts", {}),
        },
        "simulator_returncode": simulator_returncode,
        "unavailable_metrics": unavailable_metric_records,
    })
    if emit_step4_artifacts and emit_step5_artifacts:
        public_result["numerical_validation"] = {
            "artifact": "numerical_validation.json",
            "status": numerical_validation.get("status"),
            "passed": numerical_passed,
            "scope": numerical_validation.get("scope"),
            "summary": numerical_validation.get("summary", {}),
        }

    mapping_artifacts = run_mapping_search(
        compute_graph,
        design_point.system_architecture,
        selected_mapping=design_point.task_mapping,
        simulation_result=public_result,
        additional_feedback_samples=list(additional_feedback_samples or []),
        trusted_sample=trusted_for_final,
        beam_width=int(feedback_sample_budget or 3),
    )
    selected_mapping_record = mapping_artifacts["selected_record"]
    selected_mapping_violations = list(selected_mapping_record.get("violations", []) or [])
    if selected_mapping_violations and trusted_for_final:
        trusted_for_final = False
        architecture_payload["status"] = "unverified"
        architecture_payload["trusted_final_eligible"] = False
        public_result["trusted_final_disqualification"] = {
            "reason": "selected mapping failed legality validation",
            "violations": selected_mapping_violations,
        }
        mapping_artifacts = run_mapping_search(
            compute_graph,
            design_point.system_architecture,
            selected_mapping=design_point.task_mapping,
            simulation_result=public_result,
            additional_feedback_samples=list(additional_feedback_samples or []),
            trusted_sample=False,
            beam_width=int(feedback_sample_budget or 3),
        )
        selected_mapping_record = mapping_artifacts["selected_record"]
    mapping_payload = {
        "mapping_id": f"{run_id}_mapping",
        "mapping_policy": "workload_family_seeded_beam_local_search_with_systemc_feedback",
        "placements": design_point.task_mapping,
        "search_status": "selected_for_systemc_sample" if trusted_for_final else "selected_but_untrusted_or_blocked",
        "selected_candidate_id": selected_mapping_record.get("candidate_id"),
        "promotion_reason": selected_mapping_record.get("promotion_reason") or selected_mapping_record.get("selection_reason"),
        "trusted_final_eligible": trusted_for_final,
        "notes": [
            "Mapping was selected from deterministic seed/beam search artifacts.",
            "Low-fidelity screening is a candidate generator only; trusted ranking uses SystemC/gem5+SystemC evidence.",
            "A single vertical-slice sample is not a catalog-wide mapping winner or convergence claim.",
        ],
    }

    gem5_blockers = []
    raw_gem5_blockers = raw_result.get("gem5_systemc_blockers") if isinstance(raw_result, Mapping) else None
    if raw_gem5_blockers:
        gem5_blockers = [dict(blocker) if isinstance(blocker, Mapping) else {"id": str(blocker), "status": "blocked", "detail": str(blocker)} for blocker in raw_gem5_blockers]
    elif backend == "gem5_systemc" and not gem5_l4_proof.get("passed", False):
        gem5_blockers = [
            {
                "id": "gem5_descriptor_ingestion",
                "status": "blocked",
                "detail": "The real gem5 L4 run did not verify descriptor ingestion from guest software into GenericAccel.",
                "required_evidence": ["gem5.log descriptor_read", "gem5 command descriptor", "request payload checksum"],
            },
            {
                "id": "gem5_completion_result_writeback",
                "status": "blocked",
                "detail": "The real gem5 L4 run did not verify completion/result writeback visible to guest software.",
                "required_evidence": ["gem5.log completion_writeback", "completion descriptor", "guest-visible result pointer"],
            },
            {
                "id": "gem5_microarchitecture_execution",
                "status": "blocked",
                "detail": "gem5 L4 is untrusted for this sample until GenericAccel decodes the request and executes the in-gem5 microarchitecture schedule.",
                "required_evidence": ["gem5.log uarch_request_decode", "gem5.log microarchitecture_execute", "L4 result path from GenericAccel"],
            },
        ]

    evidence_gaps = []
    if not full_workload_eligible:
        evidence_gaps.append(
            f"Workload package is not full-workload eligible: claim_boundary={workload_package.claim_boundary}, lowering_status={lowering_report.get('status')}"
        )
    if missing_phases:
        evidence_gaps.append(f"Missing required phase timing events: {', '.join(missing_phases)}")
    if simulation_passed and not numerical_passed:
        failed_count = numerical_validation.get("summary", {}).get("failed_check_count", "unknown")
        if numerical_validation.get("scope") == "gem5_microarchitecture_timing_internal_consistency":
            evidence_gaps.append(f"gem5 microarchitecture timing consistency validation failed: {failed_count} failed checks")
        else:
            evidence_gaps.append(f"Numerical validation failed for timing-level simulator outputs: {failed_count} failed checks")
    elif not simulation_passed:
        evidence_gaps.append("Numerical validation unavailable because the simulator did not complete with status=passed.")
    if selected_mapping_violations:
        evidence_gaps.append(f"Selected mapping failed legality validation: {', '.join(selected_mapping_violations)}")
    if backend == "gem5_systemc" and not gem5_l4_proof.get("passed", False):
        missing_l4_evidence = gem5_l4_proof.get("missing_evidence", [])
        if not isinstance(missing_l4_evidence, list):
            missing_l4_evidence = [missing_l4_evidence]
        evidence_gaps.extend(str(item) for item in missing_l4_evidence)
    if gem5_blockers:
        evidence_gaps.append("gem5 GenericAccel descriptor/decode/microarchitecture/completion proof is missing for this run; no L4 completion claim is made.")
    if codesign_artifacts.get("codesign_candidate") and not codesign_validation.get("valid", False):
        evidence_gaps.append("Co-design candidate artifacts failed replay validation; software-visible co-design claims are blocked.")
    required_profile_artifacts = profile_domain_validation["required_artifacts"]
    if not isinstance(required_profile_artifacts, list):
        required_profile_artifacts = [required_profile_artifacts]
    if required_profile_artifacts:
        evidence_gaps.append(
            "Profile/importer-domain correctness is unclaimed: missing validator artifacts "
            f"{', '.join(str(artifact) for artifact in required_profile_artifacts)}"
        )

    forbidden_domain_claim = (
        f"{workload_package.workload_family} profile-domain correctness beyond supplied profile validation artifacts"
    )

    verdict = {
        "schema_version": "dse.verdict.v1",
        "run_id": run_id,
        "backend": backend,
        "evidence_mode": evidence_mode,
        "trusted_for_final_ranking": trusted_for_final,
        "trusted_paths": [backend] if trusted_for_final else [],
        "simulation_passed": simulation_passed,
        "phase_coverage_passed": not missing_phases,
        "full_workload_eligible": full_workload_eligible,
        "required_coverage": required_coverage,
        "missing_required_coverage": missing_phases,
        "domain_validation": profile_domain_validation,
        "profile_required_coverage": required_coverage,
        "workflow": workflow_payload,
        "profile": workflow_payload,
        "profile_domain_validation": profile_domain_validation,
        "workload_package": {
            "workload_id": workload_package.workload_id,
            "workload_family": workload_package.workload_family,
            "profile_id": workload_package.profile_id,
            "profile_version": workload_package.profile_version,
            "importer_id": workload_package.importer_id,
            "importer_version": workload_package.importer_version,
            "claim_boundary": workload_package.claim_boundary,
        },
        "graph_lowering": {
            "status": lowering_report.get("status"),
            "full_workload_eligible": lowering_report.get("full_workload_eligible", False),
            "unsupported_constructs": lowering_report.get("unsupported_constructs", []),
        },
        "simulator_consistency_passed": numerical_passed,
        "simulator_consistency_scope": simulator_consistency_check.get("scope"),
        "simulator_consistency_metrics": simulator_consistency_check.get("summary", {}),
        "numerical_validation_passed": numerical_passed,
        "numerical_validation_scope": numerical_validation.get("scope"),
        "numerical_error_metrics": numerical_validation.get("summary", {}),
        "gem5_l4_proof_passed": bool(gem5_l4_proof.get("passed", False)),
        "gem5_l4_proof": gem5_l4_proof,
        "binding_status": {
            "standalone_systemc_full_workload": "implemented" if trusted_systemc else ("not_run" if backend != "systemc" else "blocked"),
            "gem5_systemc_full_workload": "implemented" if trusted_gem5_systemc else ("not_run" if backend != "gem5_systemc" else "untrusted"),
            "l1_l2_predicted_final_ranking": "unsupported",
        },
        "status_boundary": {
            "selected_workload_profile": workload_package.profile_id,
            "selected_workload_importer": workload_package.importer_id,
            "selected_workload_claim_boundary": workload_package.claim_boundary,
            "timing_level_phase_execution": "implemented" if simulation_passed else "blocked",
            "fixed_timing_smoke_done_evidence": "unsupported",
            "predicted_only_done_evidence": "unsupported",
            "architecture_catalog_full_expansion": "implemented_initial_catalog",
            "mapping_search_optimizer": "implemented_seeded_feedback_loop",
        },
        "required_workload_phases": required_coverage,
        "evidence_gaps": evidence_gaps,
        "gem5_systemc_blockers": gem5_blockers,
        "claim_gating": {
            "best_architecture": "not_claimed_by_single_pilot; requires trusted multi-candidate SystemC/gem5+SystemC evidence",
            "mapping_comparison": "not_claimed_by_single_pilot; requires comparable trusted runs",
            "bottleneck": "allowed_only_if_phase_breakdown_csv_and_simulation_result_phase_results_are_cited",
            "feasibility": "allowed_for_this_design_only_if_verdict_and_simulation_result_are_cited",
            "numerical_correctness": "allowed_only_for_generic_sim_timing_numeric_outputs_if_numerical_validation_json_passes; profile/importer-domain correctness requires profile/importer-owned validation evidence",
            "microarchitecture_timing_consistency": "allowed_for_gem5_generic_accel_microarchitecture_outputs_when numerical_validation scope is gem5_microarchitecture_timing_internal_consistency and gem5_l4_proof.json passes",
            "pareto_frontier": "not_claimed_by_single_pilot",
            "debug_replay": "allowed_if_manifest_and_artifact_manifest_are_cited",
        },
        "forbidden_claims": [
            "L4 gem5+SystemC complete without passing gem5_l4_proof.json" if gem5_blockers else "predicted-only final ranking",
            "L1/L2 analytical/TLM winner as final trusted result",
            "toy smoke/fixed-timing diagnostic as Done evidence",
            forbidden_domain_claim,
        ],
    }
    codesign_l4_artifacts: Dict[str, Dict[str, Any]] = {}
    if codesign_artifacts.get("codesign_candidate"):
        if backend == "gem5_systemc":
            codesign_l4_artifacts = build_codesign_l4_evidence(
                codesign_candidate=codesign_artifacts["codesign_candidate"],
                backend=backend,
                sim_result=public_result,
                gem5_l4_proof=gem5_l4_proof,
                gem5_log=gem5_log,
                gem5_stdout=systemc_stdout,
                trusted_for_final=trusted_for_final and bool(codesign_validation.get("valid", False)),
            )
            verdict["codesign_verdict"] = {
                "artifact": "codesign_verdict.json",
                "status": codesign_l4_artifacts["codesign_verdict"].get("status"),
                "trusted_for_codesign_ranking": bool(codesign_l4_artifacts["codesign_verdict"].get("trusted_for_codesign_ranking", False)),
                "candidate_artifact": "codesign_candidate.json",
            }
        else:
            verdict["codesign_verdict"] = {
                "artifact": "codesign_candidate.json",
                "status": "l4_not_run",
                "trusted_for_codesign_ranking": False,
                "candidate_artifact": "codesign_candidate.json",
            }
        public_result["codesign_candidate"] = {
            "artifact": "codesign_candidate.json",
            "codesign_candidate_id": codesign_artifacts["codesign_candidate"].get("codesign_candidate_id"),
            "l4_required": bool(
                (codesign_artifacts["codesign_candidate"].get("promotion_policy", {}) or {}).get("l4_required", False)
                if isinstance(codesign_artifacts["codesign_candidate"].get("promotion_policy", {}), Mapping)
                else False
            ),
        }

    if emit_step4_artifacts:
        _write_json(run_dir / "design_point.json", design_point_payload)
        _write_json(run_dir / "architecture.json", architecture_payload)
        _write_json(run_dir / "architecture_catalog.json", catalog_payload)
        _write_json(run_dir / "mapping.json", mapping_payload)
        _write_json(run_dir / "mapping_legality_matrix.json", mapping_artifacts["legality_matrix"])
        _write_json(run_dir / "mapping_seed_set.json", mapping_artifacts["seed_set"])
        _write_json(run_dir / "mapping_candidate_records.json", mapping_artifacts["candidate_records"])
        _write_json(run_dir / "mapping_selected_record.json", mapping_artifacts["selected_record"])
        _write_json(run_dir / "mapping_simulation_samples.json", mapping_artifacts["simulation_samples"])
        _write_json(run_dir / "mapping_feedback_state.json", mapping_artifacts["feedback_state"])
        _write_json(run_dir / "convergence_status.json", mapping_artifacts["convergence_status"])
        _write_json(run_dir / "workload_package.json", workload_package_payload)
        _write_json(run_dir / "workload_graph.json", workload_payload)
        _write_json(run_dir / "graph_lowering_report.json", lowering_report)
        if graph_lowering.executable_graph is not None:
            _write_json(run_dir / "executable_graph.json", graph_lowering.executable_graph.to_dict())
        if codesign_artifacts.get("codesign_candidate"):
            _write_json(run_dir / "codesign_candidate.json", codesign_artifacts["codesign_candidate"])
            _write_json(run_dir / "software_stack_config.json", codesign_artifacts["software_stack_config"])
            _write_json(run_dir / "compiler_lowering.json", codesign_artifacts["compiler_lowering"])
            _write_json(run_dir / "runtime_schedule.json", codesign_artifacts["runtime_schedule"])
            _write_json(run_dir / "descriptor_protocol.json", codesign_artifacts["descriptor_protocol"])
            _write_json(run_dir / "memory_policy.json", codesign_artifacts["memory_policy"])
            _write_json(run_dir / "codesign_artifact_validation.json", codesign_validation)
    for key, filename in [
        ("l4_execution_trace", "l4_execution_trace.json"),
        ("dma_trace", "dma_trace.json"),
        ("mmio_trace", "mmio_trace.json"),
        ("cpu_runtime_trace", "cpu_runtime_trace.json"),
        ("accelerator_trace", "accelerator_trace.json"),
        ("completion_proof", "completion_proof.json"),
    ]:
        if key in codesign_l4_artifacts:
            _write_json(run_dir / filename, codesign_l4_artifacts[key])
    if emit_step4_artifacts and "codesign_verdict" in codesign_l4_artifacts:
        _write_json(run_dir / "codesign_verdict.json", codesign_l4_artifacts["codesign_verdict"])
    _write_json(run_dir / "simulation_request.json", simulation_request)
    _write_json(run_dir / "simulation_result.json", public_result)
    if emit_step4_artifacts:
        _write_json(run_dir / "simulator_consistency_check.json", simulator_consistency_check)
        if emit_step5_artifacts:
            _write_json(run_dir / "numerical_validation.json", numerical_validation)
        control_scope = _control_plane_scope(
            workload_package=workload_package,
            compute_graph=compute_graph,
            design_point=design_point,
        )
        _write_json(run_dir / "timing_model_calibration.json", {
            "schema_version": "dse.timing_model_calibration.v1",
            "status": "calibrated_from_simulator_consistency" if numerical_passed else "blocked",
            "source_artifact": "simulator_consistency_check.json",
            "valid_region": {"backend": backend, "workload_profile": workload_package.profile_id},
            "confidence": 0.8 if numerical_passed else 0.0,
            "summary": simulator_consistency_check.get("summary", {}),
        })
        calibration_source_hashes = _hash_existing_artifacts(
            run_dir,
            ["simulation_result.json", "simulator_consistency_check.json"],
        )
        _write_json(run_dir / "calibration_record.json", {
            "schema_version": CONTRACT_VERSION,
            **control_scope,
            "levels": ["l3", "l4" if backend == "gem5_systemc" else "l3_reference"],
            "confidence": 0.8 if numerical_passed else 0.0,
            "valid_region": {"backend": backend, "workload_profile": workload_package.profile_id},
            "error_metrics": simulator_consistency_check.get("summary", {}),
            "source_artifact_hashes": calibration_source_hashes,
        })
        feedback_source_hashes = _hash_existing_artifacts(
            run_dir,
            ["simulation_result.json", "mapping_feedback_state.json", "calibration_record.json"],
        )
        public_metrics = public_result.get("metrics", {}) if isinstance(public_result.get("metrics", {}), Mapping) else {}
        search_feedback_metrics = {
            "trusted_sample": trusted_for_final,
            "promoted": trusted_for_final,
            "step4_verdict": "trusted_pass" if trusted_for_final else "blocked_or_untrusted",
            "step4_quality_score": 80.0 if numerical_passed else 0.0,
            "calibrated_score_delta": 1.0 if trusted_for_final else -1.0,
        }
        for metric_name in ("latency_ms", "power_w", "energy_j", "total_data_movement_mb"):
            if metric_name in public_metrics:
                search_feedback_metrics[metric_name] = public_metrics.get(metric_name)
        search_feedback_candidate_refs = {
            "candidate_id": selected_mapping_record.get("candidate_id"),
            "mapping_candidate_id": selected_mapping_record.get("candidate_id"),
            "mapping_parameter_hash": selected_mapping_record.get("parameter_hash"),
            "mapping_id": mapping_payload.get("mapping_id"),
            "architecture_id": design_point.system_architecture.system_id,
            "design_point_id": design_point.design_point_id,
        }
        _write_json(run_dir / "feedback_update.json", {
            "schema_version": CONTRACT_VERSION,
            **control_scope,
            "updates": [
                {
                    "target": "promotion_policy",
                    "status": "available",
                    "trusted_sample": trusted_for_final,
                    "mapping_feedback_state": "mapping_feedback_state.json",
                    "source_artifacts": ["simulation_result.json", "mapping_feedback_state.json"],
                },
                {
                    "target": "search_policy",
                    "status": "available",
                    "observation_role": "search_policy_feedback",
                    "trusted_sample": trusted_for_final,
                    "candidate_refs": search_feedback_candidate_refs,
                    "metrics": search_feedback_metrics,
                    "observe_api": "SearchPolicy.observe(candidate_id, metrics)",
                    "candidate_id_resolution": [
                        "search_policy_candidate_id",
                        "mapping_candidate_id",
                        "mapping_parameter_hash",
                        "candidate_id",
                    ],
                    "mapping_feedback_state": "mapping_feedback_state.json",
                    "source_artifacts": [
                        "simulation_result.json",
                        "mapping_feedback_state.json",
                        "calibration_record.json",
                    ],
                }
            ],
            "source_artifact_hashes": feedback_source_hashes,
        })
        _write_json(run_dir / "gem5_l4_proof.json", gem5_l4_proof)
        if backend == "gem5_systemc":
            _write_json(run_dir / "l4_interface_metrics.json", l4_interface_metrics)
    _write_json(run_dir / "simulation_result.raw.json", raw_result)
    _write_text(run_dir / "systemc_stdout.log", systemc_stdout)
    _write_text(run_dir / "systemc_stderr.log", systemc_stderr)
    _write_phase_breakdown(run_dir / "phase_breakdown.csv", phase_results)
    _write_resource_summary(run_dir / "resource_summary.csv", raw_result)
    _write_data_movement_summary(run_dir / "data_movement_summary.csv", compute_graph, design_point.task_mapping)
    _write_json(run_dir / "gem5_systemc_blockers.json", {"blockers": gem5_blockers})
    if gem5_log is not None:
        _write_text(run_dir / "gem5.log", gem5_log)
    if not emit_step4_artifacts:
        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "trusted_for_final_ranking": False,
            "simulation_passed": simulation_passed,
            "missing_required_coverage": missing_phases,
            "profile_required_coverage": required_coverage,
            "step4_pending": True,
            "step5_pending": True,
            "verdict": verdict,
            "simulator_consistency_check": simulator_consistency_check,
            "report_artifacts": {},
        }

    _write_json(run_dir / "verdict.json", verdict)
    _write_json(run_dir / "provenance.json", {
        "schema_version": "dse.step4.provenance.v1",
        "run_id": run_id,
        "generated_at": _now_iso(),
        "producer_step": "step4_evidence_adjudication",
        "inputs": [
            "simulation_request.json",
            "simulation_result.json",
            "simulation_result.raw.json",
            "systemc_stdout.log",
            "systemc_stderr.log",
        ],
        "outputs": [
            "verdict.json",
            "simulator_consistency_check.json",
            "timing_model_calibration.json",
            "calibration_record.json",
            "feedback_update.json",
        ],
    })

    manifest = {
        "schema_version": "dse.manifest.v1",
        "run_id": run_id,
        "created_at": _now_iso(),
        "workload": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "workload_profile": workload_package.profile_id,
        "workload_profile_version": workload_package.profile_version,
        "workload_importer": workload_package.importer_id,
        "workload_importer_version": workload_package.importer_version,
        "backend": backend,
        "evidence_mode": evidence_mode,
        "cwd": os.getcwd(),
        "cli_command": cli_command,
        "simulator_command": simulator_cmd,
        "replay_metadata": {
            "python_replay_command": cli_command,
            "simulator_replay_command": simulator_cmd,
            "simulation_request": "simulation_request.json",
            "simulation_result": "simulation_result.json",
        },
        "trusted_for_final_ranking": trusted_for_final,
        "required_evidence_files": STEP4_REQUIRED_EVIDENCE_FILES
        + (["l4_interface_metrics.json"] if backend == "gem5_systemc" else [])
        + (STEP5_REPORTING_ARTIFACTS if emit_step5_artifacts else []),
        "optional_evidence_files": [
            "executable_graph.json",
            "simulation_result.raw.json",
            "gem5_systemc_blockers.json",
            "gem5_l4_proof.json",
            "gem5.log",
            "gem5_command_descriptor.json",
            "gem5_completion_descriptor.json",
            "stats.txt",
            "config.ini",
            "config.json",
            "gem5_activity_summary.json",
            "simulation_trace.json",
        ] + CODESIGN_STEP2_ARTIFACTS + CODESIGN_L4_EVIDENCE_ARTIFACTS,
    }
    _write_json(run_dir / "manifest.json", manifest)

    codesign_paths: List[str] = []
    if codesign_artifacts.get("codesign_candidate"):
        codesign_paths.extend(CODESIGN_STEP2_ARTIFACTS)
    if codesign_l4_artifacts:
        codesign_paths.extend(CODESIGN_L4_EVIDENCE_ARTIFACTS)
    artifact_paths = list(dict.fromkeys(
        STEP4_REQUIRED_EVIDENCE_FILES
        + (STEP5_REPORTING_ARTIFACTS if emit_step5_artifacts else [])
        + (["numerical_validation.json"] if emit_step5_artifacts else [])
        + [
            "simulation_result.raw.json",
            "gem5_systemc_blockers.json",
            "gem5_l4_proof.json",
            "simulator_consistency_check.json",
            "timing_model_calibration.json",
            "calibration_record.json",
            "feedback_update.json",
            "provenance.json",
        ]
        + (["l4_interface_metrics.json"] if backend == "gem5_systemc" else [])
        + codesign_paths
        + list(extra_artifact_paths or [])
    ))
    if (run_dir / "executable_graph.json").exists():
        artifact_paths.append("executable_graph.json")
    for optional_path in [
        "gem5.log",
        "gem5_command_descriptor.json",
        "gem5_completion_descriptor.json",
        "stats.txt",
        "config.ini",
        "config.json",
        "gem5_activity_summary.json",
    ]:
        if (run_dir / optional_path).exists() or (optional_path == "gem5.log" and gem5_log is not None):
            artifact_paths.append(optional_path)

    from dse_v2.reporting.final_report import (
        write_step4_claim_validation_artifacts,
        write_step5_report_artifacts,
    )

    step4_report_artifacts = write_step4_claim_validation_artifacts(run_dir, artifact_paths=artifact_paths)
    manifest["step4_adjudication_artifacts"] = step4_report_artifacts
    _write_json(run_dir / "manifest.json", manifest)
    artifact_paths.extend(step4_report_artifacts.values())
    report_artifacts: Dict[str, str] = {}
    if emit_step5_artifacts:
        report_artifacts = write_step5_report_artifacts(run_dir, artifact_paths=artifact_paths)
        manifest["step5_reporting_artifacts"] = report_artifacts
        _write_json(run_dir / "manifest.json", manifest)
        artifact_paths.extend(report_artifacts.values())

    artifact_entries = _artifact_entries(run_dir, artifact_paths)
    for entry in artifact_entries:
        if entry["path"] == "artifact_manifest.json":
            entry["exists"] = True
            entry.pop("unavailable_reason", None)
            entry["self_referential_manifest"] = True
            entry["hash_unavailable_reason"] = "artifact_manifest.json is generated from this artifact listing"
    artifact_manifest = {
        "schema_version": "dse.artifact_manifest.v1",
        "run_id": run_id,
        "generated_at": _now_iso(),
        "artifacts": artifact_entries,
    }
    _write_json(run_dir / "artifact_manifest.json", artifact_manifest)

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "trusted_for_final_ranking": trusted_for_final,
        "missing_required_coverage": missing_phases,
        "profile_required_coverage": required_coverage,
        "verdict": verdict,
        "codesign_verdict": codesign_l4_artifacts.get("codesign_verdict") if codesign_l4_artifacts else None,
        "step4_adjudication_artifacts": step4_report_artifacts,
        "report_artifacts": report_artifacts,
    }
