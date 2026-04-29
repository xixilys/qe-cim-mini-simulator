from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


CORRECTNESS_REPORT_SCHEMA_VERSION = "correctness_report_v0"
WORKLOAD_EQUIVALENT_CLAIM_CEILING = "workload_equivalent_correctness_only"
CORRECTNESS_REFERENCE_CLAIM_CEILING = "correctness_report_reference_only"

CORRECTNESS_STATUSES = {
    "pass",
    "mismatch",
    "baseline_missing",
    "baseline_normalization_error",
    "candidate_missing",
    "model_error",
    "compare_error",
}

CLAIM_CEILINGS = {
    WORKLOAD_EQUIVALENT_CLAIM_CEILING,
    CORRECTNESS_REFERENCE_CLAIM_CEILING,
}


def load_and_validate_correctness_report(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("correctness report root must be an object")
    validate_correctness_report(payload)
    return payload


def _require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"correctness report requires mapping field: {key}")
    return value


def _compare_overall_pass(compare_report: Mapping[str, Any]) -> bool | None:
    value = compare_report.get("overall_pass")
    if isinstance(value, bool):
        return value
    summary = compare_report.get("summary")
    if isinstance(summary, Mapping):
        status = summary.get("status")
        if status == "pass":
            return True
        if status in CORRECTNESS_STATUSES - {"pass"}:
            return False
    return None


def validate_correctness_report(payload: Mapping[str, Any]) -> None:
    required = (
        "schema_version",
        "execution_status",
        "claim_ceiling",
        "report_id",
        "candidate_id",
        "workload_identity",
        "tolerance_schema_id",
        "correctness_status",
        "workload_equivalent_claim",
        "compare_report",
        "evidence_refs",
    )
    for key in required:
        if key not in payload:
            raise ValueError(f"correctness report missing field: {key}")
    if payload["schema_version"] != CORRECTNESS_REPORT_SCHEMA_VERSION:
        raise ValueError("unsupported correctness report schema_version")
    if payload["execution_status"] != "executed":
        raise ValueError("correctness report must represent an executed external correctness check")
    if payload["claim_ceiling"] not in CLAIM_CEILINGS:
        raise ValueError("invalid correctness report claim_ceiling")
    if payload["correctness_status"] not in CORRECTNESS_STATUSES:
        raise ValueError("invalid correctness_status")
    if not isinstance(payload["workload_equivalent_claim"], bool):
        raise ValueError("correctness report workload_equivalent_claim must be boolean")

    workload_identity = _require_mapping(payload, "workload_identity")
    if not isinstance(workload_identity.get("workload_id"), str):
        raise ValueError("workload_identity.workload_id must be a string")
    if not isinstance(workload_identity.get("domain"), str):
        raise ValueError("workload_identity.domain must be a string")
    if not isinstance(workload_identity.get("adapter"), str):
        raise ValueError("workload_identity.adapter must be a string")

    compare_report = _require_mapping(payload, "compare_report")
    _require_mapping(payload, "evidence_refs")
    compare_pass = _compare_overall_pass(compare_report)
    claim = payload["workload_equivalent_claim"] is True
    correctness_pass = payload["correctness_status"] == "pass"

    if claim:
        if payload["claim_ceiling"] != WORKLOAD_EQUIVALENT_CLAIM_CEILING:
            raise ValueError(
                "workload-equivalent claim requires workload_equivalent_correctness_only ceiling"
            )
        if not correctness_pass:
            raise ValueError("workload-equivalent claim requires correctness_status pass")
        if compare_pass is not True:
            raise ValueError("workload-equivalent claim requires compare_report overall_pass true")
    else:
        if payload["claim_ceiling"] != CORRECTNESS_REFERENCE_CLAIM_CEILING:
            raise ValueError(
                "non-claim correctness reports require correctness_report_reference_only ceiling"
            )
    if correctness_pass and compare_pass is False:
        raise ValueError("correctness_status pass conflicts with compare_report failure")


def summarize_correctness_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    workload_identity = payload.get("workload_identity", {})
    if not isinstance(workload_identity, Mapping):
        workload_identity = {}
    compare_report = payload.get("compare_report", {})
    compare_pass = _compare_overall_pass(compare_report) if isinstance(compare_report, Mapping) else None
    return {
        "schema_version": str(payload.get("schema_version")),
        "report_id": str(payload.get("report_id")),
        "candidate_id": str(payload.get("candidate_id")),
        "workload_id": str(workload_identity.get("workload_id")),
        "domain": str(workload_identity.get("domain")),
        "adapter": str(workload_identity.get("adapter")),
        "execution_status": str(payload.get("execution_status")),
        "correctness_status": str(payload.get("correctness_status")),
        "workload_equivalent_claim": payload.get("workload_equivalent_claim") is True,
        "compare_overall_pass": compare_pass,
        "claim_ceiling": str(payload.get("claim_ceiling")),
    }
