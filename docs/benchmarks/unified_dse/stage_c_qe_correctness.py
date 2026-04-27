from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


QE_CORRECTNESS_REPORT_SCHEMA_VERSION = "qe_dse_qe_equivalent_correctness_report_v0"
QE_TOLERANCE_SCHEMA_ID = "qe_gold_numerical_tolerance_schema_v0"
QE_EQUIVALENT_CLAIM_CEILING = "qe_equivalent_scf_correctness_only"
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
    QE_EQUIVALENT_CLAIM_CEILING,
    CORRECTNESS_REFERENCE_CLAIM_CEILING,
}


def load_and_validate_qe_correctness_report(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_qe_correctness_report(payload)
    return payload


def _require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"QE correctness report requires mapping field: {key}")
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


def validate_qe_correctness_report(payload: Mapping[str, Any]) -> None:
    required = (
        "schema_version",
        "execution_status",
        "claim_ceiling",
        "report_id",
        "candidate_id",
        "workload_id",
        "case_id",
        "qe_tolerance_schema_id",
        "correctness_status",
        "qe_equivalent_scf_claim",
        "compare_report",
        "evidence_refs",
    )
    for key in required:
        if key not in payload:
            raise ValueError(f"QE correctness report missing field: {key}")
    if payload["schema_version"] != QE_CORRECTNESS_REPORT_SCHEMA_VERSION:
        raise ValueError("unsupported QE correctness report schema_version")
    if payload["execution_status"] != "executed":
        raise ValueError("QE correctness report must represent an executed external correctness run")
    if payload["claim_ceiling"] not in CLAIM_CEILINGS:
        raise ValueError("invalid QE correctness report claim_ceiling")
    if payload["qe_tolerance_schema_id"] != QE_TOLERANCE_SCHEMA_ID:
        raise ValueError("QE correctness report must use the frozen QE gold tolerance schema")
    if payload["correctness_status"] not in CORRECTNESS_STATUSES:
        raise ValueError("invalid QE correctness_status")
    if not isinstance(payload["qe_equivalent_scf_claim"], bool):
        raise ValueError("QE correctness report qe_equivalent_scf_claim must be boolean")

    compare_report = _require_mapping(payload, "compare_report")
    _require_mapping(payload, "evidence_refs")
    compare_pass = _compare_overall_pass(compare_report)
    claim = payload["qe_equivalent_scf_claim"] is True
    correctness_pass = payload["correctness_status"] == "pass"

    if claim:
        if payload["claim_ceiling"] != QE_EQUIVALENT_CLAIM_CEILING:
            raise ValueError("QE-equivalent SCF claim requires qe_equivalent_scf_correctness_only ceiling")
        if not correctness_pass:
            raise ValueError("QE-equivalent SCF claim requires correctness_status pass")
        if compare_pass is not True:
            raise ValueError("QE-equivalent SCF claim requires compare_report overall_pass true")
    if correctness_pass and compare_pass is False:
        raise ValueError("QE correctness_status pass conflicts with compare_report failure")


def summarize_qe_correctness_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    compare_report = payload.get("compare_report", {})
    compare_pass = _compare_overall_pass(compare_report) if isinstance(compare_report, Mapping) else None
    return {
        "schema_version": str(payload.get("schema_version")),
        "report_id": str(payload.get("report_id")),
        "candidate_id": str(payload.get("candidate_id")),
        "workload_id": str(payload.get("workload_id")),
        "case_id": str(payload.get("case_id")),
        "execution_status": str(payload.get("execution_status")),
        "correctness_status": str(payload.get("correctness_status")),
        "qe_equivalent_scf_claim": payload.get("qe_equivalent_scf_claim") is True,
        "compare_overall_pass": compare_pass,
        "claim_ceiling": str(payload.get("claim_ceiling")),
    }
