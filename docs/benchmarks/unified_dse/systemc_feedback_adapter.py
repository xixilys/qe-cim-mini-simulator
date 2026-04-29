from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import result_analysis


SYSTEMC_FEEDBACK_ARTIFACT_SCHEMA_VERSION = "qe_dse_systemc_feedback_artifact_v0"
BACKEND_EXECUTION_REPORT_SCHEMA_VERSION = "backend_execution_report_v0"
ALLOWED_EXECUTION_STATUSES = {"not_executed", "executed"}
ALLOWED_SOURCE_KINDS = {"timed_functional_proxy", "trace_calibrated_proxy"}
ALLOWED_BACKEND_CLASSES = {
    "systemc_timed_functional_proxy",
    "systemc_trace_calibrated_proxy",
}
ALLOWED_FEEDBACK_CLAIM_CEILINGS = {
    "timed_functional_proxy_feedback_only",
    "trace_calibrated_proxy_feedback_only",
}
ALLOWED_ROW_CLAIM_CEILINGS = ALLOWED_FEEDBACK_CLAIM_CEILINGS | {
    "timed_functional_proxy_contract_only",
}


def load_systemc_feedback_artifact(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_systemc_feedback_artifact(payload)
    return payload


def validate_systemc_feedback_artifact(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != SYSTEMC_FEEDBACK_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported SystemC feedback artifact schema_version")
    for key in (
        "execution_status",
        "source_kind",
        "claim_ceiling",
        "backend_class",
        "report_schema_version",
        "rows",
    ):
        if key not in payload:
            raise ValueError(f"SystemC feedback artifact missing field: {key}")
    if payload["execution_status"] not in ALLOWED_EXECUTION_STATUSES:
        raise ValueError("unsupported SystemC feedback execution_status")
    if payload["source_kind"] not in ALLOWED_SOURCE_KINDS:
        raise ValueError("unsupported SystemC feedback source_kind")
    if payload["backend_class"] not in ALLOWED_BACKEND_CLASSES:
        raise ValueError("unsupported SystemC feedback backend_class")
    if payload["claim_ceiling"] not in ALLOWED_FEEDBACK_CLAIM_CEILINGS:
        raise ValueError("unsupported SystemC feedback claim_ceiling")
    if payload["report_schema_version"] != BACKEND_EXECUTION_REPORT_SCHEMA_VERSION:
        raise ValueError("unsupported SystemC feedback report_schema_version")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("SystemC feedback artifact requires a rows list")
    for index, row in enumerate(rows):
        _validate_feedback_row(row, index=index, top_claim_ceiling=str(payload["claim_ceiling"]))


def _validate_feedback_row(row: Any, *, index: int, top_claim_ceiling: str) -> None:
    if not isinstance(row, Mapping):
        raise ValueError(f"SystemC feedback row {index} must be a mapping")
    for key in ("candidate_id", "metrics", "claim_ceiling"):
        if key not in row:
            raise ValueError(f"SystemC feedback row {index} missing field: {key}")
    if not row.get("candidate_id"):
        raise ValueError(f"SystemC feedback row {index} candidate_id is required")
    if not isinstance(row.get("metrics"), Mapping):
        raise ValueError(f"SystemC feedback row {index} metrics must be a mapping")
    row_claim = str(row.get("claim_ceiling"))
    if row_claim not in ALLOWED_ROW_CLAIM_CEILINGS:
        raise ValueError(f"SystemC feedback row {index} claim_ceiling over claim ceiling")
    if row_claim in ALLOWED_FEEDBACK_CLAIM_CEILINGS and row_claim != top_claim_ceiling:
        raise ValueError(f"SystemC feedback row {index} claim_ceiling exceeds artifact ceiling")
    correctness_gate = row.get("correctness_gate")
    non_claims = row.get("non_claims")
    has_correctness_status = (
        isinstance(correctness_gate, Mapping)
        and bool(correctness_gate.get("status"))
    )
    has_explicit_non_claims = isinstance(non_claims, list) and bool(non_claims)
    if not has_correctness_status and not has_explicit_non_claims:
        raise ValueError(
            f"SystemC feedback row {index} requires correctness_gate.status or explicit non_claims"
        )


def _candidate_id(row: Mapping[str, Any]) -> str | None:
    contract = row.get("systemc_feedback_contract", {})
    if isinstance(contract, Mapping) and contract.get("candidate_id"):
        return str(contract["candidate_id"])
    return None


def _feedback_rows(feedback: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = feedback.get("rows", [])
    if not isinstance(rows, Sequence):
        return []
    return [item for item in rows if isinstance(item, Mapping)]


def _feedback_candidate_ids(feedback: Mapping[str, Any]) -> list[str]:
    candidate_ids: list[str] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in _feedback_rows(feedback):
        candidate_id = str(item.get("candidate_id"))
        if candidate_id in seen:
            duplicates.append(candidate_id)
        seen.add(candidate_id)
        candidate_ids.append(candidate_id)
    if duplicates:
        raise ValueError(f"duplicate feedback candidate ID: {sorted(set(duplicates))}")
    return candidate_ids


def _feedback_by_candidate(feedback: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["candidate_id"]): item
        for item in _feedback_rows(feedback)
    }


def _known_candidate_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    known: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        candidate_id = _candidate_id(row)
        if candidate_id is None:
            continue
        if candidate_id in known:
            raise ValueError(f"duplicate known candidate ID: {candidate_id}")
        known[candidate_id] = row
    return known


def _require_candidate_descriptor(
    row: Mapping[str, Any],
    candidate_id: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    descriptor = row.get("candidate_descriptor")
    if not isinstance(descriptor, Mapping):
        raise ValueError(f"feedback target missing candidate_descriptor: {candidate_id}")
    descriptor_validation = descriptor.get("design_validation")
    if not isinstance(descriptor_validation, Mapping):
        raise ValueError(
            f"feedback target missing candidate_descriptor.design_validation: {candidate_id}"
        )
    return descriptor, descriptor_validation


def _row_can_receive_backend_feedback(row: Mapping[str, Any], candidate_id: str) -> bool:
    contract = row.get("systemc_feedback_contract")
    if not isinstance(contract, Mapping) or contract.get("status") != "planned_not_executed":
        return False

    descriptor, descriptor_validation = _require_candidate_descriptor(row, candidate_id)
    row_validation = row.get("design_validation")
    if not isinstance(row_validation, Mapping):
        raise ValueError(f"feedback candidate validation mismatch: {candidate_id}")

    validity_classes = {
        str(row_validation.get("validity_class", "")),
        str(descriptor.get("validity_class", "")),
        str(descriptor_validation.get("validity_class", "")),
    }
    if len(validity_classes) != 1 or "" in validity_classes:
        raise ValueError(f"feedback candidate validation mismatch: {candidate_id}")
    return validity_classes == {"valid_executable"}


def _validate_feedback_candidate_join(
    rows: Sequence[Mapping[str, Any]],
    feedback: Mapping[str, Any],
) -> list[str]:
    feedback_candidate_ids = _feedback_candidate_ids(feedback)
    if not feedback_candidate_ids:
        return []

    known_candidates = _known_candidate_rows(rows)
    unknown = sorted(
        candidate_id
        for candidate_id in feedback_candidate_ids
        if candidate_id not in known_candidates
    )
    if unknown:
        raise ValueError(f"feedback contains unknown candidate IDs: {unknown}")

    for candidate_id in feedback_candidate_ids:
        row = known_candidates[candidate_id]
        if not _row_can_receive_backend_feedback(row, candidate_id):
            raise ValueError(f"feedback targets non-executable candidate: {candidate_id}")
    return feedback_candidate_ids


def _metrics_from_feedback(item: Mapping[str, Any]) -> dict[str, Any]:
    metrics = item.get("metrics", {})
    if not isinstance(metrics, Mapping):
        raise ValueError("SystemC feedback row metrics must be a mapping")
    return dict(metrics)


def feedback_ingest_summary(
    rows: Sequence[Mapping[str, Any]],
    feedback: Mapping[str, Any],
) -> dict[str, Any]:
    validate_systemc_feedback_artifact(feedback)
    matched_candidate_ids = _validate_feedback_candidate_join(rows, feedback)
    return {
        "systemc_feedback_ingest_status": (
            "artifact_ingested_not_executed_by_cli"
            if matched_candidate_ids
            else "artifact_validated_no_rows"
        ),
        "systemc_feedback_candidate_count": len(matched_candidate_ids),
        "systemc_feedback_matched_candidate_count": len(matched_candidate_ids),
        "systemc_feedback_unmatched_candidate_ids": [],
        "systemc_feedback_rejected_candidate_ids": [],
    }


def apply_systemc_feedback(
    rows: Sequence[Mapping[str, Any]],
    feedback: Mapping[str, Any],
    feedback_ref: str | None = None,
) -> list[dict[str, Any]]:
    validate_systemc_feedback_artifact(feedback)
    _validate_feedback_candidate_join(rows, feedback)
    execution_status = str(feedback.get("execution_status", "not_executed"))
    source_kind = str(feedback.get("source_kind", "timed_functional_proxy"))
    claim_ceiling = str(feedback.get("claim_ceiling", "timed_functional_proxy_feedback_only"))
    by_candidate = _feedback_by_candidate(feedback)
    updated_rows: list[dict[str, Any]] = []
    for row in rows:
        copied = deepcopy(dict(row))
        candidate_id = _candidate_id(copied)
        feedback_row = by_candidate.get(candidate_id or "")
        if feedback_row is None:
            updated_rows.append(copied)
            continue

        copied["metrics"] = _metrics_from_feedback(feedback_row)
        copied["source_kind"] = source_kind
        copied["result_status"] = "executed" if execution_status == "executed" else "dry_run"
        projection = copied.get("projection", {})
        if not isinstance(projection, Mapping):
            projection = {}
        copied["projection"] = dict(projection)
        copied["projection"]["ranking_grade_ready"] = result_analysis.metrics_are_ranking_grade(
            copied["metrics"]
        )
        systemc_feedback = copied.get("systemc_feedback_contract", {})
        if isinstance(systemc_feedback, Mapping):
            copied["systemc_feedback_contract"] = dict(systemc_feedback)
            copied["systemc_feedback_contract"].update(
                {
                    "status": "feedback_artifact_ingested",
                    "execution_status": execution_status,
                    "metrics_ref": feedback_ref,
                    "claim_ceiling": "timed_functional_proxy_contract_only",
                    "subprocess_invoked": execution_status == "executed",
                }
            )
        copied["systemc_feedback_ingest"] = {
            "schema_version": "qe_dse_systemc_feedback_ingest_v0",
            "feedback_ref": feedback_ref,
            "candidate_id": candidate_id,
            "execution_status": execution_status,
            "source_kind": source_kind,
            "claim_ceiling": claim_ceiling,
        }
        updated_rows.append(copied)
    return updated_rows
