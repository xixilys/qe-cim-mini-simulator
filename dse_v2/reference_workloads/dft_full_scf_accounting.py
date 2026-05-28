#!/usr/bin/env python3
"""Fail-closed full-SCF row accounting contracts for DFT/QE evidence.

The strict DFT/QE numerical path accepts row-local full-SCF accounting only when
the accelerated runtime records host+accelerator end-to-end scope, consumed
schedule pieces, host-bound costs, runtime overheads, and all claimed major
accelerated-kernel costs.  This module intentionally lives in
``reference_workloads`` so the generic control plane does not learn DFT phase
names.

Runtime traces may be normalized into ``full_scf_row_accounting.json``, but only
when the trace itself declares trusted runtime measurement provenance.  Timing
models, fixtures, baseline copies, or smoke-only component traces are preserved
as blocked accounting artifacts rather than being upgraded into trusted rows.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
)


FULL_SCF_ROW_ACCOUNTING_SCHEMA = "dse.dft.numerical.full_scf_row_accounting.v1"
FULL_SCF_RUNTIME_TRACE_SCHEMA = "dse.dft.numerical.full_scf_runtime_trace.v1"

FULL_SCF_ROW_ACCOUNTING_SCHEMAS = {
    FULL_SCF_ROW_ACCOUNTING_SCHEMA,
    "dse.dft_scf.full_scf_row_accounting.v1",
}
FULL_SCF_RUNTIME_TRACE_SCHEMAS = {
    FULL_SCF_RUNTIME_TRACE_SCHEMA,
    "dse.dft_scf.full_scf_runtime_trace.v1",
}

TRUSTED_RUNTIME_TRACE_SOURCES = {
    "accelerated_qe_runtime_trace",
    "qe_offload_runtime_trace",
    "qe_offload_runtime",
    "gem5_generic_accel_qe_extension",
    "gem5_generic_accel_runtime_counter",
    "hardware_counter",
    "wall_clock_instrumentation",
}
UNTRUSTED_RUNTIME_TRACE_SOURCES = {
    "",
    "fixture",
    "synthetic",
    "baseline_copy",
    "pure_software_qe_baseline",
    "timing_only",
    "timing_model",
    "estimated",
    "model_estimate",
    "component_model",
    "smoke_only",
}
_FORBIDDEN_BOOL_FLAGS = (
    "fixture",
    "baseline_copy",
    "timing_only",
    "synthetic",
    "model_estimate",
    "component_model_reference_replay_only",
    "software_component_model_not_l4",
    "single_hpsi_call_smoke_only",
    "proxy_runtime_smoke_only",
    "proxy_runtime_only",
    "qe_callsite_gated_proxy_only",
)
_EXECUTION_PROOF_FIELDS = (
    "runtime_execution_proof",
    "l4_execution_proof",
    "hardware_counter_proof",
    "tool_execution_proof",
)
_PROXY_RUNTIME_MARKER_SUBSTRINGS = (
    "repo_native_offload_runtime_proxy_bridge",
    "proxy_runtime",
    "qe_callsite_gated_proxy",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ref(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": str(path)}
    if path.exists():
        payload.update({"exists": True, "hash": _sha256_file(path), "hash_algorithm": "sha256"})
    else:
        payload.update({"exists": False})
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _boolish_true(payload: Mapping[str, Any], key: str) -> bool:
    return payload.get(key) is True


def _cost_map(payload: Mapping[str, Any], *field_names: str) -> Mapping[str, Any] | None:
    for field_name in field_names:
        value = payload.get(field_name)
        if isinstance(value, Mapping):
            return value
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _event_cost_s(event: Mapping[str, Any]) -> float | None:
    for field_name in ("duration_s", "cost_s", "elapsed_s", "elapsed_seconds", "wall_time_s"):
        if field_name not in event:
            continue
        parsed = _float_or_none(event.get(field_name))
        if parsed is not None:
            return parsed
    return None


def _validate_full_scf_required_cost_map(
    payload: Mapping[str, Any],
    *,
    field_names: Sequence[str],
    required_ids: Sequence[str],
    blocker_prefix: str,
) -> list[str]:
    costs = _cost_map(payload, *field_names)
    if costs is None:
        return [f"full_scf_row_accounting_missing_{blocker_prefix}"]
    blockers: list[str] = []
    for cost_id in required_ids:
        if cost_id not in costs:
            blockers.append(f"full_scf_row_accounting_{blocker_prefix}_missing_{cost_id}")
            continue
        value = _float_or_none(costs[cost_id])
        if value is None:
            blockers.append(f"full_scf_row_accounting_{blocker_prefix}_{cost_id}_not_numeric")
            continue
        if value < 0.0:
            blockers.append(f"full_scf_row_accounting_{blocker_prefix}_{cost_id}_negative")
    return blockers


def _accounting_source(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("runtime_trace_source")
        or payload.get("accounting_source")
        or payload.get("measurement_source")
        or payload.get("source_kind")
        or payload.get("source")
        or ""
    ).strip().lower()


def validate_full_scf_row_accounting_payload(
    payload: Mapping[str, Any],
    *,
    candidate_id: str | None = None,
    workload_case_id: str | None = None,
) -> list[str]:
    """Return blockers for a strict full-SCF row-accounting payload."""
    blockers: list[str] = []
    expected_candidate = _nonempty_text(candidate_id)
    if expected_candidate:
        payload_candidate = _nonempty_text(payload.get("candidate_id"))
        if not payload_candidate:
            blockers.append("full_scf_row_accounting_missing_candidate_id")
        elif payload_candidate != expected_candidate:
            blockers.append("full_scf_row_accounting_candidate_id_mismatch")
    expected_workload = _normalize_trace_workload_id(workload_case_id)
    if expected_workload:
        payload_workloads = [
            value
            for value in (
                _normalize_trace_workload_id(payload.get("workload_case_id")),
                _normalize_trace_workload_id(payload.get("workload_id")),
            )
            if value
        ]
        if not payload_workloads:
            blockers.append("full_scf_row_accounting_missing_workload_case_id")
        elif any(value != expected_workload for value in payload_workloads):
            blockers.append("full_scf_row_accounting_workload_case_id_mismatch")
    if payload.get("schema_version") not in FULL_SCF_ROW_ACCOUNTING_SCHEMAS:
        blockers.append("full_scf_row_accounting_schema_mismatch")
    if payload.get("status") not in {"passed", "complete"} and payload.get("passed") is not True:
        blockers.append("full_scf_row_accounting_status_not_passed")
    if payload.get("comparison_scope") != "full_scf_host_accelerator_end_to_end":
        blockers.append("full_scf_row_accounting_scope_not_full_scf_host_accelerator_end_to_end")
    for key in (
        "host_accelerator_end_to_end",
        "full_scf_schedule_consumed",
        "host_bound_costs_included",
    ):
        if payload.get(key) is not True:
            blockers.append(f"full_scf_row_accounting_{key}_not_true")
    for key in _FORBIDDEN_BOOL_FLAGS:
        if payload.get(key) is True:
            blockers.append(f"full_scf_row_accounting_{key}_forbidden")
    source = _accounting_source(payload)
    if source in UNTRUSTED_RUNTIME_TRACE_SOURCES or source not in TRUSTED_RUNTIME_TRACE_SOURCES:
        blockers.append(f"full_scf_row_accounting_untrusted_runtime_source:{source or 'missing'}")
    blockers.extend(_execution_proof_blockers(payload, blocker_prefix="full_scf_row_accounting"))
    blockers.extend(
        _validate_full_scf_required_cost_map(
            payload,
            field_names=("accelerated_kernel_costs_s", "accelerated_costs_s"),
            required_ids=MAJOR_SCF_KERNEL_IDS,
            blocker_prefix="accelerated_kernel_costs_s",
        )
    )
    blockers.extend(
        _validate_full_scf_required_cost_map(
            payload,
            field_names=("host_bound_costs_s", "host_bound_stage_costs_s"),
            required_ids=REQUIRED_HOST_BOUND_PHASE_IDS,
            blocker_prefix="host_bound_costs_s",
        )
    )
    blockers.extend(
        _validate_full_scf_required_cost_map(
            payload,
            field_names=("runtime_overhead_costs_s", "overhead_costs_s"),
            required_ids=REQUIRED_OVERHEAD_PHASE_IDS,
            blocker_prefix="runtime_overhead_costs_s",
        )
    )
    covered = payload.get("covered_accelerated_kernel_ids") or payload.get("major_kernel_ids") or []
    covered_ids = {str(item) for item in covered} if isinstance(covered, list) else set()
    missing_kernels = [kernel_id for kernel_id in MAJOR_SCF_KERNEL_IDS if kernel_id not in covered_ids]
    if missing_kernels:
        blockers.append("full_scf_row_accounting_major_accelerated_kernels_not_all_covered")
    return sorted(dict.fromkeys(blockers))


def _proof_passed(trace: Mapping[str, Any]) -> bool:
    for key in _EXECUTION_PROOF_FIELDS:
        proof = trace.get(key)
        if isinstance(proof, Mapping) and proof.get("passed") is True:
            return True
    return False


def _execution_proof_blockers(payload: Mapping[str, Any], *, blocker_prefix: str) -> list[str]:
    """Return fail-closed blockers for execution proof provenance.

    A proof object marked ``passed`` is not sufficient for strict full-SCF
    accounting if the same proof also declares smoke/proxy/timing/fixture
    provenance.  This prevents rows from becoming final merely because all
    required event IDs were later filled while the underlying execution proof was
    still a repo-native proxy or callsite smoke harness.
    """

    blockers: list[str] = []
    passed_proof_seen = False
    for proof_key in _EXECUTION_PROOF_FIELDS:
        proof = payload.get(proof_key)
        if not isinstance(proof, Mapping) or proof.get("passed") is not True:
            continue
        passed_proof_seen = True
        for flag in _FORBIDDEN_BOOL_FLAGS:
            if proof.get(flag) is True:
                blockers.append(f"{blocker_prefix}_{proof_key}_{flag}_forbidden")
        blockers.extend(_proxy_runtime_marker_blockers(proof, blocker_prefix=blocker_prefix, proof_key=proof_key))
    if not passed_proof_seen:
        blockers.append(f"{blocker_prefix}_missing_passed_execution_proof")
    return sorted(dict.fromkeys(blockers))


def _proxy_runtime_marker_blockers(
    proof: Mapping[str, Any],
    *,
    blocker_prefix: str,
    proof_key: str,
) -> list[str]:
    blockers: list[str] = []
    for field_name, raw_value in proof.items():
        if not isinstance(raw_value, str):
            continue
        normalized = raw_value.strip().lower()
        if any(marker in normalized for marker in _PROXY_RUNTIME_MARKER_SUBSTRINGS):
            blockers.append(f"{blocker_prefix}_{proof_key}_proxy_runtime_marker_forbidden:{field_name}")
    return blockers


def _trace_source(trace: Mapping[str, Any], event: Mapping[str, Any]) -> str:
    return str(
        event.get("measurement_source")
        or event.get("source_kind")
        or event.get("source")
        or trace.get("runtime_trace_source")
        or trace.get("source_kind")
        or ""
    ).strip().lower()


def _trace_events(trace: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("events", "runtime_events", "schedule", "schedule_events"):
        value = trace.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _nonempty_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_trace_workload_id(value: Any) -> str:
    text = _nonempty_text(value)
    return text[:-5] if text.endswith("_case") else text


def _resolve_trace_row_identity(
    trace: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    *,
    candidate_id: str | None,
    workload_case_id: str | None,
) -> tuple[str | None, str | None, list[str]]:
    """Resolve and validate the row identity carried by a runtime trace.

    Direct trace-to-accounting replay must not be able to relabel a trace from
    another candidate/workload row by passing different CLI arguments.  The trace
    may carry the row identity at the top level, or every event may carry it
    (the producer-generated event manifest enforces the latter).  Mismatches or
    missing identity remain blocked so a copied trace cannot satisfy a strict
    full-SCF row.
    """

    blockers: list[str] = []
    trace_candidate = _nonempty_text(trace.get("candidate_id"))
    trace_workload = _normalize_trace_workload_id(trace.get("workload_case_id") or trace.get("workload_id"))
    expected_candidate = _nonempty_text(candidate_id) or trace_candidate
    expected_workload = _normalize_trace_workload_id(workload_case_id) or trace_workload

    event_candidates = [
        (index, _nonempty_text(event.get("candidate_id")))
        for index, event in enumerate(events)
    ]
    event_candidate_values = {value for _, value in event_candidates if value}
    if not expected_candidate and len(event_candidate_values) == 1:
        expected_candidate = next(iter(event_candidate_values))
    if expected_candidate:
        if trace_candidate and trace_candidate != expected_candidate:
            blockers.append("runtime_trace_candidate_id_mismatch")
        for index, value in event_candidates:
            if value and value != expected_candidate:
                blockers.append(f"runtime_trace_event_{index}_candidate_id_mismatch")
            elif not value and not trace_candidate:
                blockers.append(f"runtime_trace_event_{index}_missing_candidate_id")
    else:
        blockers.append("runtime_trace_missing_candidate_id")

    event_workloads = [
        (
            index,
            [
                value
                for value in (
                _normalize_trace_workload_id(event.get("workload_case_id")),
                _normalize_trace_workload_id(event.get("workload_id")),
                )
                if value
            ],
        )
        for index, event in enumerate(events)
    ]
    event_workload_values = {value for _, values in event_workloads for value in values}
    if not expected_workload and len(event_workload_values) == 1:
        expected_workload = next(iter(event_workload_values))
    if expected_workload:
        if trace_workload and trace_workload != expected_workload:
            blockers.append("runtime_trace_workload_case_id_mismatch")
        for index, values in event_workloads:
            if values and expected_workload not in values:
                blockers.append(f"runtime_trace_event_{index}_workload_case_id_mismatch")
            elif not values and not trace_workload:
                blockers.append(f"runtime_trace_event_{index}_missing_workload_case_id")
    else:
        blockers.append("runtime_trace_missing_workload_case_id")

    return expected_candidate or None, expected_workload or None, sorted(dict.fromkeys(blockers))


def build_full_scf_row_accounting_from_runtime_trace(
    trace: Mapping[str, Any],
    *,
    candidate_id: str | None = None,
    workload_case_id: str | None = None,
    trace_path: Path | None = None,
) -> Dict[str, Any]:
    """Normalize a trusted runtime trace into strict row accounting.

    The output is intentionally fail-closed.  If any required source, proof, or
    cost is missing, a blocked accounting payload is still returned so downstream
    producers can preserve the diagnostic artifact without trusting it.
    """
    blockers: list[str] = []
    if trace.get("schema_version") not in FULL_SCF_RUNTIME_TRACE_SCHEMAS:
        blockers.append("runtime_trace_schema_mismatch")
    if trace.get("status") not in {"passed", "complete"} and trace.get("passed") is not True:
        blockers.append("runtime_trace_status_not_passed")
    if trace.get("trusted_runtime_trace") is not True and trace.get("trusted_runtime_execution") is not True:
        blockers.append("runtime_trace_not_marked_trusted")
    if trace.get("comparison_scope") != "full_scf_host_accelerator_end_to_end":
        blockers.append("runtime_trace_scope_not_full_scf_host_accelerator_end_to_end")
    for key in (
        "host_accelerator_end_to_end",
        "full_scf_schedule_consumed",
        "host_bound_costs_included",
    ):
        if trace.get(key) is not True:
            blockers.append(f"runtime_trace_{key}_not_true")
    for key in _FORBIDDEN_BOOL_FLAGS:
        if trace.get(key) is True:
            blockers.append(f"runtime_trace_{key}_forbidden")
    blockers.extend(_execution_proof_blockers(trace, blocker_prefix="runtime_trace"))

    accelerated_costs: dict[str, float] = {}
    host_costs: dict[str, float] = {}
    overhead_costs: dict[str, float] = {}
    covered_kernels: set[str] = set()
    events = _trace_events(trace)
    if not events:
        blockers.append("runtime_trace_missing_events")
    resolved_candidate_id, resolved_workload_case_id, identity_blockers = _resolve_trace_row_identity(
        trace,
        events,
        candidate_id=candidate_id,
        workload_case_id=workload_case_id,
    )
    blockers.extend(identity_blockers)
    for index, event in enumerate(events):
        for key in _FORBIDDEN_BOOL_FLAGS:
            if event.get(key) is True:
                blockers.append(f"runtime_trace_event_{index}_{key}_forbidden")
        source = _trace_source(trace, event)
        if source in UNTRUSTED_RUNTIME_TRACE_SOURCES or source not in TRUSTED_RUNTIME_TRACE_SOURCES:
            blockers.append(f"runtime_trace_event_{index}_untrusted_measurement_source:{source or 'missing'}")
        cost = _event_cost_s(event)
        if cost is None:
            blockers.append(f"runtime_trace_event_{index}_cost_not_numeric")
            continue
        if cost < 0.0:
            blockers.append(f"runtime_trace_event_{index}_cost_negative")
            continue
        category = str(event.get("category") or "").strip()
        if category == "accelerated_kernel":
            kernel_id = str(event.get("kernel_id") or event.get("id") or "").strip()
            if kernel_id not in MAJOR_SCF_KERNEL_IDS:
                blockers.append(f"runtime_trace_event_{index}_unsupported_kernel_id:{kernel_id or 'missing'}")
                continue
            accelerated_costs[kernel_id] = accelerated_costs.get(kernel_id, 0.0) + cost
            covered_kernels.add(kernel_id)
        elif category == "host_bound_phase":
            phase_id = str(event.get("phase_id") or event.get("id") or "").strip()
            if phase_id not in REQUIRED_HOST_BOUND_PHASE_IDS:
                blockers.append(f"runtime_trace_event_{index}_unsupported_host_phase_id:{phase_id or 'missing'}")
                continue
            host_costs[phase_id] = host_costs.get(phase_id, 0.0) + cost
        elif category == "runtime_overhead":
            overhead_id = str(event.get("overhead_id") or event.get("id") or "").strip()
            if overhead_id not in REQUIRED_OVERHEAD_PHASE_IDS:
                blockers.append(f"runtime_trace_event_{index}_unsupported_overhead_id:{overhead_id or 'missing'}")
                continue
            overhead_costs[overhead_id] = overhead_costs.get(overhead_id, 0.0) + cost
        else:
            blockers.append(f"runtime_trace_event_{index}_unsupported_category:{category or 'missing'}")

    payload: Dict[str, Any] = {
        "schema_version": FULL_SCF_ROW_ACCOUNTING_SCHEMA,
        "candidate_id": resolved_candidate_id,
        "workload_case_id": resolved_workload_case_id,
        "status": "passed",
        "passed": True,
        "comparison_scope": "full_scf_host_accelerator_end_to_end",
        "host_accelerator_end_to_end": trace.get("host_accelerator_end_to_end") is True,
        "full_scf_schedule_consumed": trace.get("full_scf_schedule_consumed") is True,
        "host_bound_costs_included": trace.get("host_bound_costs_included") is True,
        "fixture": False,
        "baseline_copy": False,
        "timing_only": False,
        "covered_accelerated_kernel_ids": sorted(covered_kernels),
        "accelerated_kernel_costs_s": dict(sorted(accelerated_costs.items())),
        "host_bound_costs_s": dict(sorted(host_costs.items())),
        "runtime_overhead_costs_s": dict(sorted(overhead_costs.items())),
        "physical_evidence": dict(trace.get("physical_evidence", {}))
        if isinstance(trace.get("physical_evidence"), Mapping)
        else {},
        "runtime_trace_source": trace.get("runtime_trace_source") or trace.get("source_kind"),
        "claim_boundary": (
            "Generated from runtime-emitted full-SCF trace only; fixtures, timing models, "
            "or missing execution proofs remain blocked and cannot satisfy final DFT/QE closure."
        ),
    }
    for proof_key in _EXECUTION_PROOF_FIELDS:
        proof = trace.get(proof_key)
        payload[proof_key] = dict(proof) if isinstance(proof, Mapping) else None
    if trace_path is not None:
        payload["runtime_trace_reference"] = _artifact_ref(trace_path)
    for key in _FORBIDDEN_BOOL_FLAGS:
        if trace.get(key) is True:
            payload[key] = True

    structural_blockers = validate_full_scf_row_accounting_payload(
        payload,
        candidate_id=resolved_candidate_id,
        workload_case_id=resolved_workload_case_id,
    )
    blockers = sorted(dict.fromkeys([*blockers, *structural_blockers]))
    if blockers:
        payload["status"] = "blocked"
        payload["passed"] = False
    payload["blockers"] = blockers
    return payload


def materialize_full_scf_row_accounting_from_trace(
    *,
    trace_path: Path,
    output_path: Path,
    candidate_id: str | None = None,
    workload_case_id: str | None = None,
) -> Dict[str, Any]:
    """Read a runtime trace, write row accounting, and return the payload."""
    trace = _load_json(trace_path)
    trace_map = trace if isinstance(trace, Mapping) else {}
    payload = build_full_scf_row_accounting_from_runtime_trace(
        trace_map,
        candidate_id=candidate_id,
        workload_case_id=workload_case_id,
        trace_path=trace_path,
    )
    _write_json(output_path, payload)
    return payload


__all__ = [
    "FULL_SCF_ROW_ACCOUNTING_SCHEMA",
    "FULL_SCF_RUNTIME_TRACE_SCHEMA",
    "TRUSTED_RUNTIME_TRACE_SOURCES",
    "build_full_scf_row_accounting_from_runtime_trace",
    "materialize_full_scf_row_accounting_from_trace",
    "validate_full_scf_row_accounting_payload",
]
