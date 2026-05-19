#!/usr/bin/env python3
"""L4 closure matrix and performance-claim gates for complete DSE releases.

This module is intentionally small and data-oriented.  It does not run gem5;
it consumes release candidates, frozen QE workload cases, and row evidence that
upstream Step3/Step4 runners produced.  Its job is to make missing rows and
anti-downgrade claim boundaries explicit so a finite release cannot be marked
``deliverable_complete`` from projections, Top-K samples, descriptor-only rows,
or blocked tool runs.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

from dse_v2.codesign.release_domain import stable_json_hash

L4_EVIDENCE_MATRIX_SCHEMA = "dse.codesign.l4_evidence_matrix.v1"
L4_EVIDENCE_ROW_SCHEMA = "dse.codesign.l4_evidence_matrix_row.v1"
COVERAGE_CLAIM_REPORT_SCHEMA = "dse.codesign.l4_coverage_claim_report.v1"
L4_INTERFACE_METRICS_SCHEMA = "dse.l4_interface_metrics.v1"

TRUSTED_L4_TRANSPORTS = {"gem5_generic_accel_microarchitecture_v1"}
PROJECTION_TIERS = {"L1", "L2", "L3", "systemc", "generic_sim", "release_l3_projection"}
TRUSTED_ROW_CLAIM = "l4_trusted_speedup"
DELIVERABLE_CLAIM = "deliverable_complete"


def _stable_hash_without(payload: Mapping[str, Any], *excluded_keys: str) -> str:
    return stable_json_hash({key: value for key, value in payload.items() if key not in excluded_keys})


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _status_passed(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.lower() in {"pass", "passed", "trusted", "available", "complete"}
    return False


def canonicalize_l4_interface_metrics(
    raw_observations: Mapping[str, Any],
    *,
    gem5_l4_proof: Mapping[str, Any] | None = None,
    raw_observations_artifact: str | None = None,
) -> Dict[str, Any]:
    """Step4 canonicalization hook for raw gem5 L4 interface observations."""

    raw = _as_mapping(raw_observations)
    proof = _as_mapping(gem5_l4_proof)
    markers = _as_mapping(raw.get("markers"))
    descriptor = _as_mapping(raw.get("descriptor_decode"))
    request_decode = _as_mapping(raw.get("request_decode"))
    completion = _as_mapping(raw.get("completion"))
    observed = _as_mapping(raw.get("observed_metrics"))
    uarch_ops = _as_mapping(raw.get("uarch_op_summary"))

    proof_passed = proof.get("passed") is True if proof else bool(
        markers.get("descriptor_read_verified")
        and markers.get("request_decode_verified")
        and markers.get("microarchitecture_execute_verified")
        and markers.get("completion_writeback_verified")
        and markers.get("driver_status_verified")
        and markers.get("driver_completion_descriptor_verified")
    )
    missing: list[str] = []
    for field, value in [
        ("descriptor_decode.request_bytes", descriptor.get("request_bytes")),
        ("request_decode.micro_ops", request_decode.get("micro_ops")),
        ("request_decode.total_cycles", request_decode.get("total_cycles")),
        ("completion.cycles", completion.get("cycles")),
        ("observed_metrics.software_visible_latency_ms", observed.get("software_visible_latency_ms")),
    ]:
        if value is None:
            missing.append(field)
    for marker in [
        "descriptor_read_verified",
        "request_decode_verified",
        "microarchitecture_execute_verified",
        "completion_writeback_verified",
        "driver_status_verified",
        "driver_completion_descriptor_verified",
    ]:
        if markers.get(marker) is not True:
            missing.append(f"marker.{marker}")
    if not proof_passed:
        missing.append("gem5_l4_proof.passed")

    status = "passed" if not missing else "blocked"
    return {
        "schema_version": L4_INTERFACE_METRICS_SCHEMA,
        "producer_step": "Step4",
        "producer": "dse_v2.codesign.l4_closure.canonicalize_l4_interface_metrics",
        "status": status,
        "raw_observations_artifact": raw_observations_artifact,
        "raw_schema_version": raw.get("schema_version"),
        "transport_harness": raw.get("transport_harness") or proof.get("transport_harness"),
        "descriptor_decode": {
            "verified": bool(markers.get("descriptor_read_verified")),
            "descriptor_bytes": _number(descriptor.get("descriptor_bytes")),
            "request_bytes": _number(descriptor.get("request_bytes")),
            "flags": descriptor.get("flags"),
            "extension_fields": descriptor.get("extension_fields"),
        },
        "mmio": {
            "mmio_count": sum(1 for item in [
                "descriptor_read_verified",
                "request_decode_verified",
                "microarchitecture_execute_verified",
                "completion_writeback_verified",
                "driver_status_verified",
                "driver_completion_descriptor_verified",
            ] if markers.get(item) is True),
            "doorbell_observed": bool(markers.get("descriptor_read_verified")),
            "completion_status_observed": bool(markers.get("driver_status_verified")),
            "completion_descriptor_observed": bool(markers.get("driver_completion_descriptor_verified")),
            "mmio_latency_ms": None,
        },
        "dma": {
            "dma_operation_count": _number(uarch_ops.get("dma_op_count")),
            "total_dma_bytes_observed": _number(uarch_ops.get("total_dma_bytes_observed")),
            "total_payload_bytes_observed": _number(request_decode.get("total_payload_bytes")),
            "dma_time_ms": _number(observed.get("dma_time_ms")),
        },
        "queue": {
            "queue_wait_ms": None,
            "queue_wait_source": "not_observed_in_current_gem5_trace",
        },
        "host": {
            "host_overhead_ms": _number(observed.get("host_time_ms")),
        },
        "accelerator": {
            "busy_fraction": _number(observed.get("accelerator_busy_fraction")),
            "idle_fraction": _number(observed.get("accelerator_idle_fraction")),
            "device_time_ms": _number(observed.get("device_time_ms")),
        },
        "completion": {
            "completion_latency_cycles": _number(completion.get("cycles")),
            "driver_completion_latency_cycles": _number(completion.get("driver_cycles")),
            "completion_latency_ms": None,
            "software_visible_latency_ms": _number(observed.get("software_visible_latency_ms")),
        },
        "validation": {
            "gem5_l4_proof_passed": proof_passed,
            "missing_or_invalid_fields": sorted(dict.fromkeys(missing)),
            "raw_adapter_did_not_produce_canonical_metrics": raw.get("artifact_role") == "raw_l4_observations",
        },
        "claim_boundary": (
            "Step4 canonical L4 interface metrics are derived from raw gem5 observations; "
            "queue/MMIO latency fields remain null until the raw trace exposes them directly."
        ),
    }


def _candidate_ids(release_subset: Mapping[str, Any]) -> list[str]:
    ids = [str(item) for item in release_subset.get("legal_candidate_ids", []) or []]
    if ids:
        return ids
    candidates = release_subset.get("candidates", []) or []
    return [
        str(candidate.get("candidate_id"))
        for candidate in candidates
        if isinstance(candidate, Mapping) and candidate.get("legal", True) and candidate.get("candidate_id")
    ]


def _workload_case_ids(workload_suite: Mapping[str, Any]) -> list[str]:
    ids = [str(item) for item in workload_suite.get("workload_case_ids", []) or []]
    if ids:
        return ids
    cases = workload_suite.get("cases", []) or []
    return [
        str(case.get("case_id") or case.get("workload_case_id"))
        for case in cases
        if isinstance(case, Mapping) and (case.get("case_id") or case.get("workload_case_id"))
    ]


def _row_key(row: Mapping[str, Any]) -> Tuple[str, str]:
    return (str(row.get("candidate_id", "")), str(row.get("workload_case_id", "")))


def _index_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[Dict[Tuple[str, str], Mapping[str, Any]], list[Dict[str, Any]]]:
    indexed: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    duplicates: list[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = _row_key(row)
        if not all(key):
            continue
        if key in indexed:
            duplicates.append({"candidate_id": key[0], "workload_case_id": key[1], "blocker": "duplicate_evidence_row"})
        indexed[key] = row
    return indexed, duplicates


def _proof(row: Mapping[str, Any]) -> Mapping[str, Any]:
    l4 = _as_mapping(row.get("l4_evidence"))
    return _as_mapping(row.get("gem5_l4_proof") or l4.get("gem5_l4_proof") or l4.get("proof"))


def _proof_transport(proof: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    source = _as_mapping(proof.get("source_artifacts"))
    l4 = _as_mapping(row.get("l4_evidence"))
    return str(
        proof.get("transport_harness")
        or source.get("transport_harness")
        or l4.get("transport_harness")
        or ""
    )


def _real_l4_passed(row: Mapping[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    l4 = _as_mapping(row.get("l4_evidence"))
    proof = _proof(row)
    backend = str(row.get("backend") or l4.get("backend") or proof.get("backend") or "")
    evidence_tier = str(row.get("evidence_tier") or l4.get("evidence_tier") or "")
    if evidence_tier in PROJECTION_TIERS or backend in {"systemc", "generic_sim", "analytical"}:
        blockers.append("projection_tier_cannot_claim_trusted_speedup")
    if backend and backend != "gem5_systemc":
        blockers.append("backend_not_gem5_systemc")
    if not proof:
        blockers.append("missing_gem5_l4_proof")
        return False, blockers
    checks = _as_mapping(proof.get("checks"))
    required_checks = [
        "descriptor_read_verified",
        "request_decode_verified",
        "microarchitecture_execute_verified",
        "completion_writeback_verified",
        "driver_status_verified",
        "driver_completion_descriptor_verified",
        "result_status_passed",
    ]
    for check in required_checks:
        value = proof.get(check, checks.get(check))
        if value is not True:
            blockers.append(f"l4_proof_{check}_missing_or_false")
    if proof.get("passed") is not True:
        blockers.append("gem5_l4_proof_not_passed")
    if proof.get("fallback_from_gem5") is True:
        blockers.append("fallback_from_gem5_not_trusted")
    transport = _proof_transport(proof, row)
    if transport not in TRUSTED_L4_TRANSPORTS:
        blockers.append("transport_harness_not_real_gem5_generic_accel")
    return not blockers, blockers


def _correctness_passed(row: Mapping[str, Any]) -> tuple[bool, list[str]]:
    correctness = _as_mapping(row.get("correctness") or row.get("correctness_result") or row.get("qe_correctness"))
    if not correctness:
        return False, ["missing_dual_correctness_result"]
    blockers: list[str] = []
    if correctness.get("trusted_claim_eligible") is True:
        return True, []
    kernel = _as_mapping(correctness.get("kernel_gate"))
    physical = _as_mapping(correctness.get("scf_physical_gate") or correctness.get("physical_gate"))
    if kernel.get("status") != "passed":
        blockers.append("kernel_correctness_not_passed")
    if physical.get("status") != "passed":
        blockers.append("scf_physical_correctness_not_passed")
    if correctness.get("timing_only") is True:
        blockers.append("timing_only_evidence_cannot_satisfy_correctness")
    blockers.append("trusted_correctness_source_not_eligible")
    return not blockers, blockers


def _baseline_passed(row: Mapping[str, Any]) -> tuple[bool, list[str]]:
    baseline = _as_mapping(row.get("baseline_comparison") or row.get("baseline"))
    if not baseline:
        return False, ["missing_pure_software_baseline_comparison"]
    blockers: list[str] = []
    if not _status_passed(baseline.get("status")):
        blockers.append("baseline_comparison_not_passed")
    if baseline.get("pure_software_qe_baseline") is not True:
        blockers.append("missing_pure_software_qe_baseline")
    if str(baseline.get("baseline_status", "")).lower() in {"fixture_reference", "structural_only", "draft"}:
        blockers.append("fixture_or_structural_baseline_not_trusted")
    return not blockers, blockers


def _calibration_passed(row: Mapping[str, Any]) -> tuple[bool, list[str]]:
    calibration = _as_mapping(row.get("calibration_consistency") or row.get("calibration") or row.get("trace_counter_consistency"))
    if not calibration:
        return False, ["missing_l4_trace_counter_calibration"]
    blockers: list[str] = []
    if not _status_passed(calibration.get("status")):
        blockers.append("calibration_consistency_not_passed")
    if calibration.get("trace_counter_consistent") is not True:
        blockers.append("trace_counter_consistency_not_verified")
    return not blockers, blockers


def classify_l4_evidence_row(
    row: Mapping[str, Any] | None,
    *,
    candidate_id: str,
    workload_case_id: str,
) -> Dict[str, Any]:
    """Classify one candidate/workload row without upgrading partial evidence."""
    if row is None:
        payload = {
            "schema_version": L4_EVIDENCE_ROW_SCHEMA,
            "candidate_id": candidate_id,
            "workload_case_id": workload_case_id,
            "row_status": "blocked",
            "claim_label": "blocked",
            "trusted_speedup_eligible": False,
            "deliverable_complete_eligible": False,
            "blockers": ["missing_l4_evidence_row"],
            "evidence_present": False,
        }
        payload["row_hash"] = _stable_hash_without(payload, "row_hash")
        return payload

    source = dict(row)
    explicit_blockers = [str(item) for item in source.get("blockers", []) or []]
    if source.get("status") == "blocked" and not explicit_blockers:
        explicit_blockers.append("row_status_blocked")

    real_l4_ok, l4_blockers = _real_l4_passed(source)
    correctness_ok, correctness_blockers = _correctness_passed(source)
    baseline_ok, baseline_blockers = _baseline_passed(source)
    calibration_ok, calibration_blockers = _calibration_passed(source)
    blockers = sorted(dict.fromkeys(explicit_blockers + l4_blockers + correctness_blockers + baseline_blockers + calibration_blockers))

    evidence_tier = str(source.get("evidence_tier") or _as_mapping(source.get("l4_evidence")).get("evidence_tier") or "")
    if evidence_tier in PROJECTION_TIERS:
        claim_label = "release_l3_projection"
    elif not real_l4_ok:
        claim_label = "blocked"
    elif blockers or not (correctness_ok and baseline_ok and calibration_ok):
        claim_label = "mvp_partial"
    else:
        claim_label = TRUSTED_ROW_CLAIM

    trusted_speedup = claim_label == TRUSTED_ROW_CLAIM and not blockers
    payload = {
        "schema_version": L4_EVIDENCE_ROW_SCHEMA,
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "row_status": "passed" if trusted_speedup else ("projection" if claim_label == "release_l3_projection" else "blocked"),
        "claim_label": claim_label,
        "trusted_speedup_eligible": trusted_speedup,
        "deliverable_complete_eligible": trusted_speedup and not blockers,
        "evidence_present": True,
        "gates": {
            "real_l4_gem5_full_flow": real_l4_ok,
            "dual_correctness": correctness_ok,
            "pure_software_baseline": baseline_ok,
            "calibration_consistency": calibration_ok,
        },
        "blockers": blockers,
        "source_row_id": source.get("row_id"),
        "claim_boundary": (
            "l4_trusted_speedup requires real gem5 GenericAccel L4 proof, dual QE correctness, "
            "pure-software baseline comparison, and L4 trace/counter consistency. Projection, "
            "fallback, missing, or blocked rows cannot satisfy deliverable_complete."
        ),
    }
    payload["row_hash"] = _stable_hash_without(payload, "row_hash")
    return payload


def build_l4_evidence_matrix(
    release_subset: Mapping[str, Any],
    workload_suite: Mapping[str, Any],
    evidence_rows: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Build exhaustive candidate x workload L4 closure rows."""
    candidate_ids = _candidate_ids(release_subset)
    workload_case_ids = _workload_case_ids(workload_suite)
    indexed, duplicates = _index_rows(evidence_rows or [])
    rows: list[Dict[str, Any]] = []
    for candidate_id in candidate_ids:
        for workload_case_id in workload_case_ids:
            rows.append(
                classify_l4_evidence_row(
                    indexed.get((candidate_id, workload_case_id)),
                    candidate_id=candidate_id,
                    workload_case_id=workload_case_id,
                )
            )

    blocked_rows = [row for row in rows if row["deliverable_complete_eligible"] is not True]
    payload = {
        "schema_version": L4_EVIDENCE_MATRIX_SCHEMA,
        "release_subset_hash": release_subset.get("release_subset_hash") or release_subset.get("manifest_hash"),
        "workload_suite_hash": workload_suite.get("manifest_hash") or workload_suite.get("suite_hash"),
        "legal_candidate_ids": candidate_ids,
        "workload_case_ids": workload_case_ids,
        "expected_row_count": len(candidate_ids) * len(workload_case_ids),
        "row_count": len(rows),
        "rows": rows,
        "duplicate_input_rows": duplicates,
        "coverage_status": "passed" if not blocked_rows and not duplicates else "blocked",
        "deliverable_complete_eligible": not blocked_rows and not duplicates and bool(rows),
        "blocked_row_count": len(blocked_rows) + len(duplicates),
        "claim_boundary": "matrix closure only; final deliverable_complete also requires verifier-owned final report approval",
    }
    payload["matrix_hash"] = _stable_hash_without(payload, "matrix_hash")
    return payload


def build_coverage_claim_report(matrix: Mapping[str, Any]) -> Dict[str, Any]:
    rows = [row for row in matrix.get("rows", []) or [] if isinstance(row, Mapping)]
    blocked = [
        {
            "candidate_id": row.get("candidate_id"),
            "workload_case_id": row.get("workload_case_id"),
            "claim_label": row.get("claim_label"),
            "blockers": list(row.get("blockers", []) or []),
        }
        for row in rows
        if row.get("deliverable_complete_eligible") is not True
    ]
    expected = int(matrix.get("expected_row_count") or 0)
    row_count = int(matrix.get("row_count") or len(rows))
    complete = bool(expected and row_count == expected and not blocked and not matrix.get("duplicate_input_rows"))
    payload = {
        "schema_version": COVERAGE_CLAIM_REPORT_SCHEMA,
        "matrix_hash": matrix.get("matrix_hash"),
        "expected_row_count": expected,
        "row_count": row_count,
        "all_rows_present": row_count == expected and expected > 0,
        "blocked_rows": blocked,
        "blocked_row_count": len(blocked) + len(matrix.get("duplicate_input_rows", []) or []),
        "claim_labels": sorted({str(row.get("claim_label")) for row in rows}),
        "claims": {
            DELIVERABLE_CLAIM: complete,
            TRUSTED_ROW_CLAIM: complete,
            "projection_only_completion_allowed": False,
            "top_k_or_representative_completion_allowed": False,
        },
        "status": "deliverable_complete" if complete else "blocked_or_partial",
        "claim_boundary": (
            "deliverable_complete is true only when every legal release candidate x frozen QE mainflow "
            "row is present and eligible for l4_trusted_speedup; any missing, blocked, fallback, or "
            "projection-only row keeps completion false."
        ),
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


__all__ = [
    "COVERAGE_CLAIM_REPORT_SCHEMA",
    "DELIVERABLE_CLAIM",
    "L4_EVIDENCE_MATRIX_SCHEMA",
    "L4_EVIDENCE_ROW_SCHEMA",
    "L4_INTERFACE_METRICS_SCHEMA",
    "TRUSTED_ROW_CLAIM",
    "build_coverage_claim_report",
    "build_l4_evidence_matrix",
    "canonicalize_l4_interface_metrics",
    "classify_l4_evidence_row",
]
