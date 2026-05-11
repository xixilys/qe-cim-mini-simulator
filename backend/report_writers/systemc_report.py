from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.benchmarks.unified_dse.backend_execution import (
    MODE_TO_BACKEND_CLASS,
    MODE_TO_CLAIM_CEILING,
    MODE_TO_REQUESTED_FIDELITY,
    MODE_TO_SOURCE_KIND,
    request_candidate_validity_class,
    request_is_executable_candidate,
    validate_backend_execution_report,
    validate_backend_execution_request,
    validate_backend_execution_request_for_execution,
)


SCHEMA_VERSION = "backend_execution_report_v0"
SYSTEMC_CANDIDATE_SCHEMA_VERSION = "systemc_architecture_candidate_result_v0"

DEFAULT_NON_CLAIMS = [
    "no_qe_equivalent_scf_claim",
    "no_cycle_accuracy_claim",
    "no_rtl_hls_board_or_asic_implementation_claim",
    "no_final_architecture_recommendation",
]

BASE_METRICS: dict[str, Any] = {
    "time_to_completion_s": None,
    "cycle_proxy": None,
    "host_wait_s": None,
    "device_busy_s": None,
    "dma_read_bytes": None,
    "dma_write_bytes": None,
    "bytes_moved_to_convergence": None,
    "resident_reuse_ratio": None,
    "spill_ratio": None,
    "fallback_ratio": None,
}

METRIC_UNITS: dict[str, str] = {
    "time_to_completion_s": "s",
    "cycle_proxy": "cycles",
    "host_wait_s": "s",
    "device_busy_s": "s",
    "dma_read_bytes": "bytes",
    "dma_write_bytes": "bytes",
    "bytes_moved_to_convergence": "bytes",
    "resident_reuse_ratio": "ratio",
    "spill_ratio": "ratio",
    "fallback_ratio": "ratio",
    "host_control_mmio_read_count": "count",
    "host_control_mmio_write_count": "count",
    "host_control_polling_read_count": "count",
    "host_control_interrupt_count": "count",
    "host_control_queue_wait_ns": "ns",
    "systemc_datapath_device_busy_ns": "ns",
    "systemc_datapath_compute_ns": "ns",
    "systemc_datapath_dma_read_ns": "ns",
    "systemc_datapath_dma_write_ns": "ns",
    "systemc_datapath_queue_depth": "count",
    "systemc_datapath_backpressure_count": "count",
    "systemc_datapath_dma_read_bytes": "bytes",
    "systemc_datapath_dma_write_bytes": "bytes",
    "logical_dma_payload_bytes": "bytes",
    "observed_gem5_dma_stat_bytes": "bytes",
    "successful_dma_transfer_bytes": "bytes",
    "dma_warning_count": "count",
    "gem5_dma_stat_bytes": "bytes",
    "logical_dma_payload_bytes_tested": "bytes",
    "gem5_pci_dma_packet_count": "count",
    "runtime_smoke_ticks": "ticks",
    "fs_pci_smoke_ticks": "ticks",
    "systemc_scf_iterations": "count",
}

METRIC_GROUPS: dict[str, tuple[str, ...]] = {
    "summary": (
        "time_to_completion_s",
        "cycle_proxy",
        "bytes_moved_to_convergence",
    ),
    "host": (
        "host_wait_s",
        "host_control_mmio_read_count",
        "host_control_mmio_write_count",
        "host_control_polling_read_count",
        "host_control_interrupt_count",
        "host_control_queue_wait_ns",
    ),
    "device": (
        "device_busy_s",
        "systemc_datapath_device_busy_ns",
        "resident_reuse_ratio",
        "spill_ratio",
        "fallback_ratio",
        "systemc_datapath_queue_depth",
        "systemc_datapath_backpressure_count",
    ),
    "dma": (
        "dma_read_bytes",
        "dma_write_bytes",
        "logical_dma_payload_bytes",
        "observed_gem5_dma_stat_bytes",
        "successful_dma_transfer_bytes",
        "dma_warning_count",
        "gem5_dma_stat_bytes",
        "logical_dma_payload_bytes_tested",
    ),
    "systemc": (
        "systemc_converged",
        "systemc_scf_iterations",
        "systemc_datapath_dma_read_bytes",
        "systemc_datapath_dma_write_bytes",
        "systemc_datapath_compute_ns",
        "systemc_datapath_dma_read_ns",
        "systemc_datapath_dma_write_ns",
    ),
    "gem5": (
        "gem5_pci_dma_packet_count",
        "runtime_smoke_ticks",
        "fs_pci_smoke_ticks",
    ),
}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _metric_value(metrics: Mapping[str, Any], control_path: Mapping[str, Any], key: str) -> Any:
    if key in metrics:
        return metrics[key]
    control_key_by_metric = {
        "host_control_mmio_read_count": "mmio_read_count",
        "host_control_mmio_write_count": "mmio_write_count",
        "host_control_polling_read_count": "polling_read_count",
        "host_control_interrupt_count": "interrupt_count",
    }
    control_key = control_key_by_metric.get(key)
    if control_key is not None:
        return control_path.get(control_key)
    return None


def _metric_source_kind(key: str, mode: str, value: Any) -> str:
    if value is None:
        return "not_measured"
    if key.startswith("host_control_"):
        return "host_control_counter"
    if key.startswith("systemc_") or mode.startswith("systemc_"):
        return "systemc_source_artifact"
    if key.startswith("gem5_") or key.endswith("_ticks") or mode.startswith("gem5_"):
        return "gem5_stats_or_proxy_log"
    if key.startswith("dma_") or "dma" in key:
        return "dma_counter"
    return "backend_runner_normalized"


def build_metric_groups(
    metrics: Mapping[str, Any],
    control_path: Mapping[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    grouped: dict[str, Any] = {}
    for group, keys in METRIC_GROUPS.items():
        grouped[group] = {}
        for key in keys:
            value = _metric_value(metrics, control_path, key)
            grouped[group][key] = {
                "value": value,
                "unit": METRIC_UNITS.get(key, "unspecified"),
                "source_kind": _metric_source_kind(key, mode, value),
            }
    grouped["runner"] = {
        "completion_source": {
            "value": control_path.get("completion_source"),
            "unit": "enum",
            "source_kind": "backend_runner_normalized",
        },
        "deadlock": {
            "value": control_path.get("deadlock"),
            "unit": "bool",
            "source_kind": "backend_runner_normalized",
        },
    }
    return grouped


def request_candidate_id(request: Mapping[str, Any] | None) -> str:
    if not request:
        return "unknown_candidate"
    value = request.get("candidate_id")
    return value if isinstance(value, str) and value else "unknown_candidate"


def request_domain(request: Mapping[str, Any] | None) -> str:
    workload_identity = _as_mapping(request.get("workload_identity") if request else None)
    value = workload_identity.get("domain")
    return value if isinstance(value, str) and value else "dft"


def make_report(
    request: Mapping[str, Any] | None,
    *,
    mode: str,
    execution_status: str,
    reason: str | None = None,
    environment: Mapping[str, Any] | None = None,
    control_path: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    artifact_refs: Mapping[str, Any] | None = None,
    non_claims: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    merged_metrics = dict(BASE_METRICS)
    if metrics:
        merged_metrics.update(dict(metrics))
    if "metric_groups" in merged_metrics and not isinstance(merged_metrics["metric_groups"], Mapping):
        raise ValueError("metrics.metric_groups must be a mapping when present")

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": request_candidate_id(request),
        "execution_status": execution_status,
        "fidelity": mode,
        "claim_ceiling": MODE_TO_CLAIM_CEILING.get(mode, "unsupported_backend_mode"),
        "backend_class": MODE_TO_BACKEND_CLASS.get(mode, "unsupported_backend_mode"),
        "source_kind": MODE_TO_SOURCE_KIND.get(mode, "unsupported_backend_mode"),
        "environment": dict(environment or {}),
        "control_path": {
            "host_launch_count": 0,
            "completion_count": 0,
            "fallback_count": 0,
            "deadlock": False,
            "completion_source": "not_executed",
        },
        "metrics": merged_metrics,
        "correctness_gate": {
            "workload_equivalent_claim": False,
            "domain": request_domain(request),
            "domain_equivalence_claim": False,
        },
        "artifact_refs": dict(artifact_refs or {}),
        "non_claims": list(non_claims or DEFAULT_NON_CLAIMS),
    }
    if control_path:
        report["control_path"].update(dict(control_path))
    report["metrics"].setdefault(
        "metric_groups",
        build_metric_groups(report["metrics"], report["control_path"], mode=mode),
    )
    if reason:
        report["refusal_reason" if execution_status == "refused" else "status_reason"] = reason
    if notes:
        report["notes"] = list(notes)
    return report


def refusal_report(
    request: Mapping[str, Any] | None,
    *,
    mode: str,
    reason: str,
    artifact_refs: Mapping[str, Any] | None = None,
    environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return make_report(
        request,
        mode=mode,
        execution_status="refused",
        reason=reason,
        artifact_refs=artifact_refs,
        environment=environment,
    )


def validate_request(payload: Mapping[str, Any], *, mode: str | None = None) -> None:
    validate_backend_execution_request(payload)
    if mode is not None and payload.get("execution_mode") != mode:
        raise ValueError(
            f"CLI mode {mode} does not match "
            f"request execution_mode {payload.get('execution_mode')}"
        )


def request_validity_class(payload: Mapping[str, Any]) -> str | None:
    return request_candidate_validity_class(payload)


def is_executable_request(payload: Mapping[str, Any]) -> bool:
    return request_is_executable_candidate(payload)


def validate_request_for_execution(payload: Mapping[str, Any]) -> None:
    validate_backend_execution_request_for_execution(payload)


def validate_report(payload: Mapping[str, Any]) -> None:
    validate_backend_execution_report(payload)


def convert_systemc_candidate_result(
    candidate: Mapping[str, Any],
    request: Mapping[str, Any] | None,
    *,
    source_path: Path | str | None = None,
    mode: str = "systemc_standalone",
) -> dict[str, Any]:
    if candidate.get("schema_version") != SYSTEMC_CANDIDATE_SCHEMA_VERSION:
        raise ValueError("unsupported SystemC candidate result schema_version")

    run_summary = _as_mapping(candidate.get("run_summary"))
    metrics_in = _as_mapping(candidate.get("metrics"))
    timing = _as_mapping(candidate.get("timing"))
    final = _as_mapping(candidate.get("final"))
    iteration_diagnostics = _as_list(candidate.get("iteration_diagnostics"))

    total_episodes = _safe_int(run_summary.get("total_episodes"))
    cpu_fallbacks = _safe_int(metrics_in.get("cpu_fallbacks"))
    resident_reuse_hits = _safe_int(metrics_in.get("resident_reuse_hits"))
    spill_count = sum(
        1
        for item in iteration_diagnostics
        if isinstance(item, Mapping) and item.get("spill_active") is True
    )

    total_data_kib = _safe_float(metrics_in.get("total_data_movement_kib"))
    dma_read_kib = _safe_float(metrics_in.get("dma_read_kib"))
    dma_write_kib = _safe_float(metrics_in.get("dma_write_kib"))

    normalized_metrics: dict[str, Any] = {
        "time_to_completion_s": _safe_float(timing.get("wall_time_s")),
        "cycle_proxy": _safe_int(run_summary.get("total_ref_cycles")),
        "host_wait_s": None,
        "device_busy_s": None,
        "dma_read_bytes": None if dma_read_kib is None else int(round(dma_read_kib * 1024.0)),
        "dma_write_bytes": None if dma_write_kib is None else int(round(dma_write_kib * 1024.0)),
        "bytes_moved_to_convergence": (
            None if total_data_kib is None else int(round(total_data_kib * 1024.0))
        ),
        "resident_reuse_ratio": _ratio(resident_reuse_hits, total_episodes),
        "spill_ratio": _ratio(spill_count, total_episodes),
        "fallback_ratio": _ratio(cpu_fallbacks, total_episodes),
        "systemc_converged": final.get("converged"),
        "systemc_scf_iterations": final.get("scf_iterations"),
    }

    artifact_refs: dict[str, Any] = {
        "source_schema_version": candidate.get("schema_version"),
        "source_case_id": candidate.get("case_id"),
        "source_architecture_family": candidate.get("architecture_family"),
        "source_run_summary": dict(run_summary),
        "source_cluster_metrics": candidate.get("cluster_metrics", {}),
    }
    if source_path is not None:
        artifact_refs["systemc_candidate_result"] = str(source_path)

    report = make_report(
        request,
        mode=mode,
        execution_status="executed",
        environment={
            "systemc_generated_at_utc": candidate.get("generated_at_utc"),
            "assumption_set_id": candidate.get("assumption_set_id"),
        },
        control_path={
            "host_launch_count": total_episodes or 0,
            "completion_count": total_episodes or 0,
            "fallback_count": cpu_fallbacks or 0,
            "deadlock": False,
            "completion_source": "systemc_candidate_result",
        },
        metrics=normalized_metrics,
        artifact_refs=artifact_refs,
        notes=[
            "Converted from systemc_architecture_candidate_result_v0; "
            "QE/domain equivalence remains unclaimed."
        ],
    )
    validate_report(report)
    return report
