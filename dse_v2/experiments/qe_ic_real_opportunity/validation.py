#!/usr/bin/env python3
"""Validation for QE-IC real opportunity campaign reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dse_v2.experiments.qe_ic_real_opportunity.schema import (
    ALLOWED_CAMPAIGN_STATUSES,
    ALLOWED_TOP_LEVEL_ANSWERS,
    CLAIM_BOUNDARY,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_SCHEMA_VERSION,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_SCHEMA_VERSION,
)


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _candidate_ids(rows: list[Any]) -> set[str]:
    return {
        str(row.get("candidate_id"))
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("candidate_id"), str)
    }


def _forbidden_paths(value: Any, *, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() == "hardware_proven":
                paths.append(key_path)
            paths.extend(_forbidden_paths(nested, prefix=key_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_forbidden_paths(nested, prefix=f"{prefix}[{index}]"))
    return paths


def validate_qe_ic_real_opportunity_campaign_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate campaign report consistency and claim boundaries."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(report, Mapping):
        _error(errors, "$", "campaign report must be a mapping")
        return {
            "schema_version": QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_SCHEMA_VERSION,
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
        }
    if report.get("schema_version") != QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_SCHEMA_VERSION:
        _error(errors, "schema_version", "schema_version is incorrect")
    if report.get("campaign_status") not in ALLOWED_CAMPAIGN_STATUSES:
        _error(errors, "campaign_status", "campaign_status is unsupported")
    if report.get("claim_boundary") != CLAIM_BOUNDARY:
        _error(errors, "claim_boundary", "claim_boundary must match canonical boundary")
    for path in _forbidden_paths(report):
        _error(errors, path, "hardware_proven fields are forbidden in campaign reports")

    final = _as_mapping(report.get("final_answer"))
    overall = final.get("overall_answer")
    if overall not in ALLOWED_TOP_LEVEL_ANSWERS:
        _error(errors, "final_answer.overall_answer", "overall_answer is unsupported")

    selected_ids = _candidate_ids(_as_list(report.get("candidate_selection")))
    for index, row in enumerate(_as_list(report.get("candidate_selection"))):
        if isinstance(row, Mapping) and row.get("selection_source") != "layer4_candidate_plan":
            _error(
                errors,
                f"candidate_selection[{index}].selection_source",
                "selected candidates must come from the Layer-4 candidate plan",
            )
    opportunity = _as_mapping(report.get("opportunity_summary"))
    records = [row for row in _as_list(opportunity.get("opportunity_records")) if isinstance(row, Mapping)]
    claimable = [row for row in records if row.get("claim_allowed") is True]
    if claimable and not opportunity.get("claim_gate_invoked"):
        _error(errors, "opportunity_summary.claim_gate_invoked", "claimable records require existing claim gate invocation")
    if overall == "opportunity_found" and not claimable:
        _error(errors, "final_answer.overall_answer", "opportunity_found requires a claim_allowed opportunity record")
    if overall in {"fundamental_no_opportunity", "gpu_dominant_no_fpga_or_hybrid_opportunity", "implementation_limited"} and not records:
        _error(
            errors,
            "final_answer.overall_answer",
            f"{overall} requires underlying opportunity records and cannot be reported from missing evidence",
        )
    if overall != "opportunity_found" and final.get("best_candidate_id") is not None:
        _error(errors, "final_answer.best_candidate_id", "best_candidate_id requires opportunity_found")
    if final.get("best_candidate_id") is not None and final.get("best_candidate_id") not in selected_ids:
        _error(errors, "final_answer.best_candidate_id", "best candidate must be selected from Layer-4")
    if overall == "fundamental_no_opportunity":
        audit_classes = {
            str(row.get("implementation_quality_classification"))
            for row in _as_list(report.get("implementation_audit"))
            if isinstance(row, Mapping)
        }
        if audit_classes != {"fundamental_no_opportunity"}:
            _error(
                errors,
                "implementation_audit",
                "fundamental_no_opportunity requires all implementation audit rows to classify fundamental_no_opportunity",
            )
    if overall == "evidence_missing":
        baseline = _as_mapping(report.get("gpu_baseline_summary"))
        candidate = _as_mapping(report.get("candidate_evidence_summary"))
        if baseline.get("measurements_are_real") is True and candidate.get("results_are_real") is True and records:
            warnings.append({"field": "final_answer.overall_answer", "message": "evidence_missing despite available evidence"})
    text = str(final.get("answer_text", "")).lower()
    if "superiority claim" in text and overall != "opportunity_found":
        _error(errors, "final_answer.answer_text", "superiority claim text requires opportunity_found")

    return {
        "schema_version": QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "candidate_selection_count": len(selected_ids),
        "opportunity_record_count": len(records),
        "overall_answer": overall,
    }
