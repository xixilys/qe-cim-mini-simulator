from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

try:
    from .systemc_report import make_report, validate_report
except ImportError:  # pragma: no cover - script-path fallback
    from systemc_report import make_report, validate_report  # type: ignore


LEGACY_B3_SCHEMA_VERSION = "qe_dse_gem5_systemc_smoke_report_v0"
_EQUIVALENCE_CLAIM_KEYS = {
    "qe_equivalence_status",
    "qe_equivalent_scf_claim",
    "qe_equivalence_claim",
    "workload_equivalent_claim",
    "workload_equivalence_claim",
    "domain_equivalence_claim",
}
_FORBIDDEN_EQUIVALENCE_CLAIM_TOKENS = (
    "qe_equivalence",
    "qe-equivalence",
    "qe equivalence",
    "qe_equivalent",
    "qe-equivalent",
    "qe equivalent",
    "workload_equivalence",
    "workload-equivalence",
    "workload equivalence",
    "workload_equivalent",
    "workload-equivalent",
    "workload equivalent",
    "domain_equivalence",
    "domain-equivalence",
    "domain equivalence",
    "domain_equivalent",
    "domain-equivalent",
    "domain equivalent",
)


def _iter_json_items(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    items = [(path, value)]
    if isinstance(value, Mapping):
        for key, child in value.items():
            items.extend(_iter_json_items(child, path + (str(key),)))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            items.extend(_iter_json_items(child, path + (str(index),)))
    return items


def _is_non_claim_text(text: str) -> bool:
    normalized = text.strip().lower().replace("-", "_")
    if normalized.startswith("no_") or normalized.startswith("not_"):
        return True
    return any(
        marker in text
        for marker in (
            "not ",
            "no ",
            "without ",
            "unclaimed",
            "not_claimed",
            "non-claim",
            "non_claim",
        )
    )


def _reject_hidden_equivalence_claims(payload: Mapping[str, Any]) -> None:
    for path, value in _iter_json_items(payload):
        if not path:
            continue
        key = path[-1].lower()
        if key in _EQUIVALENCE_CLAIM_KEYS and value not in (False, "not_claimed"):
            if isinstance(value, str) and _is_non_claim_text(value.lower()):
                continue
            raise ValueError(f"{'.'.join(path)} must not claim QE-equivalent SCF")
        if isinstance(value, str):
            lowered = value.lower()
            if any(token in lowered for token in _FORBIDDEN_EQUIVALENCE_CLAIM_TOKENS):
                if not _is_non_claim_text(lowered):
                    raise ValueError(f"{'.'.join(path)} must not claim QE-equivalent SCF")


def validate_legacy_b3_smoke_report(payload: Mapping[str, Any]) -> None:
    required = (
        "schema_version",
        "run_id",
        "candidate_id",
        "execution_status",
        "claim_ceiling",
        "environment",
        "metrics",
        "correctness_gate",
        "non_claims",
    )
    for key in required:
        if key not in payload:
            raise ValueError(f"legacy B3 smoke report missing field: {key}")
    if payload["schema_version"] != LEGACY_B3_SCHEMA_VERSION:
        raise ValueError("unsupported legacy B3 smoke report schema_version")
    if payload["execution_status"] != "executed":
        raise ValueError("legacy B3 smoke report must be executed")
    if payload["claim_ceiling"] != "gem5_systemc_smoke_only":
        raise ValueError("legacy B3 smoke report must keep gem5_systemc_smoke_only claim ceiling")
    correctness_gate = payload.get("correctness_gate")
    if not isinstance(correctness_gate, Mapping):
        raise ValueError("legacy B3 smoke report requires correctness_gate object")
    if correctness_gate.get("qe_equivalent_scf_claim") is not False:
        raise ValueError("legacy B3 smoke report must not claim QE equivalence")
    _reject_hidden_equivalence_claims(payload)


def convert_legacy_b3_smoke_report(
    legacy: Mapping[str, Any],
    request: Mapping[str, Any] | None,
    *,
    source_path: Path | str | None = None,
) -> dict[str, Any]:
    validate_legacy_b3_smoke_report(legacy)
    metrics_in = legacy.get("metrics")
    metrics_in = metrics_in if isinstance(metrics_in, Mapping) else {}

    normalized_metrics = dict(metrics_in)
    normalized_metrics.update(
        {
            "time_to_completion_s": None,
            "cycle_proxy": metrics_in.get("runtime_smoke_ticks") or metrics_in.get("fs_pci_smoke_ticks"),
            "host_wait_s": None,
            "device_busy_s": None,
            "dma_read_bytes": None,
            "dma_write_bytes": metrics_in.get("gem5_dma_stat_bytes"),
            "bytes_moved_to_convergence": metrics_in.get("logical_dma_payload_bytes_tested"),
            "resident_reuse_ratio": None,
            "spill_ratio": None,
            "fallback_ratio": None,
        }
    )

    artifact_refs: dict[str, Any] = {
        "legacy_schema_version": legacy.get("schema_version"),
        "legacy_run_id": legacy.get("run_id"),
        "legacy_candidate_id": legacy.get("candidate_id"),
        "legacy_m5out_refs": metrics_in.get("m5out_refs", []),
        "legacy_runtime_smoke_command": metrics_in.get("runtime_smoke_command"),
        "legacy_fs_pci_smoke_command": metrics_in.get("fs_pci_smoke_command"),
    }
    if source_path is not None:
        artifact_refs["legacy_b3_smoke_report"] = str(source_path)

    report_request = dict(request or {})
    report_request.setdefault("candidate_id", legacy.get("candidate_id", "unknown_candidate"))
    report = make_report(
        report_request,
        mode="gem5_systemc_smoke",
        execution_status="executed",
        environment=legacy.get("environment") if isinstance(legacy.get("environment"), Mapping) else {},
        control_path={
            "host_launch_count": int(metrics_in.get("minimal_qe_like_iterations") or 0),
            "completion_count": 1,
            "fallback_count": 0,
            "deadlock": False,
            "completion_source": "smoke_immediate_complete",
            "scf_control_loop_status": legacy.get("scf_control_loop_status"),
            "systemc_bridge_status": legacy.get("systemc_bridge_status"),
            "qe_equivalence_status": legacy.get("qe_equivalence_status"),
        },
        metrics=normalized_metrics,
        artifact_refs=artifact_refs,
        non_claims=list(legacy.get("non_claims") or []),
        notes=list(legacy.get("notes") or []) + ["Converted from legacy Stage B3 smoke report envelope."],
    )
    validate_report(report)
    return report
