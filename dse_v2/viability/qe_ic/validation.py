#!/usr/bin/env python3
"""Fail-closed validation for QE-IC Layer-3 target viability reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dse_v2.viability.qe_ic.schema import (
    CLAIM_BOUNDARY,
    DECISIONS,
    QE_IC_TARGET_CONFIG_SCHEMA_VERSION,
    QE_IC_TARGET_VIABILITY_SCHEMA_VERSION,
    QE_IC_TARGET_VIABILITY_VALIDATION_SCHEMA_VERSION,
    REASON_CODE_REGISTRY,
    RISK_FIELDS,
    SOURCE_LAYER1_SUITE_ARTIFACT,
    SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
    TARGET_TYPES,
    UPPER_BOUND_FIELDS,
)
from dse_v2.viability.qe_ic.target_config import validate_qe_ic_target_config


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _warning(warnings: list[dict[str, str]], field: str, message: str) -> None:
    warnings.append({"field": field, "message": message})


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_bounded(value: Any, lo: float = 0.0, hi: float = 1.0) -> bool:
    return _is_number(value) and lo <= float(value) <= hi


def _family_ids(report: Mapping[str, Any]) -> set[str]:
    return {
        family_id
        for family_id in _as_list(_as_mapping(report.get("source_layer1_suite")).get("workload_family_ids"))
        if isinstance(family_id, str)
    }


def _motif_registry(report: Mapping[str, Any]) -> Mapping[str, Any]:
    return _as_mapping(_as_mapping(report.get("source_layer1_suite")).get("motif_registry"))


def _target_ids(report: Mapping[str, Any]) -> set[str]:
    return {
        target.get("target_id")
        for target in _as_list(_as_mapping(report.get("target_config")).get("targets"))
        if isinstance(target, Mapping) and isinstance(target.get("target_id"), str)
    }


def _target_types_by_id(report: Mapping[str, Any]) -> dict[str, str]:
    return {
        target["target_id"]: target["target_type"]
        for target in _as_list(_as_mapping(report.get("target_config")).get("targets"))
        if isinstance(target, Mapping)
        and isinstance(target.get("target_id"), str)
        and isinstance(target.get("target_type"), str)
    }


def _expected_summary(records: list[Any]) -> dict[str, Any]:
    summary = {
        "record_count": 0,
        "viable_count": 0,
        "maybe_count": 0,
        "reject_count": 0,
        "baseline_count": 0,
        "by_target_type": {},
    }
    for record in records:
        if not isinstance(record, Mapping):
            continue
        summary["record_count"] += 1
        decision = record.get("decision")
        target_type = record.get("target_type")
        if decision in {"baseline", "viable", "maybe", "reject"}:
            summary[f"{decision}_count"] += 1
        if isinstance(target_type, str):
            bucket = summary["by_target_type"].setdefault(
                target_type,
                {
                    "record_count": 0,
                    "baseline_count": 0,
                    "viable_count": 0,
                    "maybe_count": 0,
                    "reject_count": 0,
                },
            )
            bucket["record_count"] += 1
            if decision in {"baseline", "viable", "maybe", "reject"}:
                bucket[f"{decision}_count"] += 1
    return summary


def _validate_summary(
    summary: Mapping[str, Any],
    *,
    records: list[Any],
    errors: list[dict[str, str]],
) -> None:
    expected = _expected_summary(records)
    for field in ("record_count", "baseline_count", "maybe_count", "reject_count", "viable_count"):
        if summary.get(field) != expected[field]:
            _error(errors, f"summary.{field}", f"summary.{field} must match viability_records")
    if summary.get("by_target_type") != expected["by_target_type"]:
        _error(errors, "summary.by_target_type", "summary.by_target_type must exactly match records grouped by target_type")


def _validate_claim_boundary(boundary: str, errors: list[dict[str, str]]) -> None:
    lowered = boundary.lower()
    required_terms = (
        "target viability estimates",
        "architecture",
        "promotion",
        "implementation",
        "final performance claims",
    )
    if not boundary:
        _error(errors, "claim_boundary", "claim_boundary must be non-empty")
        return
    for term in required_terms:
        if term not in lowered:
            _error(errors, "claim_boundary", f"claim_boundary must mention absence of {term}")
    if "does not contain" not in lowered:
        _error(errors, "claim_boundary", "claim_boundary must be an explicit negative boundary")


def _validate_record(
    record: Mapping[str, Any],
    *,
    index: int,
    family_ids: set[str],
    motif_registry: Mapping[str, Any],
    target_ids: set[str],
    target_types_by_id: Mapping[str, str],
    errors: list[dict[str, str]],
) -> None:
    prefix = f"viability_records[{index}]"
    family_id = record.get("workload_family_id")
    motif_id = record.get("motif_id")
    target_id = record.get("target_id")
    target_type = record.get("target_type")
    decision = record.get("decision")

    if family_id not in family_ids:
        _error(errors, f"{prefix}.workload_family_id", f"unknown workload_family_id {family_id!r}")
    if motif_id not in motif_registry:
        _error(errors, f"{prefix}.motif_id", f"unknown motif {motif_id!r}")
    if target_id not in target_ids:
        _error(errors, f"{prefix}.target_id", f"unknown target_id {target_id!r}")
    if target_type not in TARGET_TYPES:
        _error(errors, f"{prefix}.target_type", "target_type is unsupported")
    if target_id in target_types_by_id and target_type != target_types_by_id[target_id]:
        _error(errors, f"{prefix}.target_type", "target_type does not match target config")
    if decision not in DECISIONS:
        _error(errors, f"{prefix}.decision", "decision is unsupported")
    if target_type == "gpu_only" and decision != "baseline":
        _error(errors, f"{prefix}.decision", "gpu_only records must have decision='baseline'")
    if not _is_bounded(record.get("viability_score")):
        _error(errors, f"{prefix}.viability_score", "viability_score must be in [0, 1]")

    upper_bound = _as_mapping(record.get("upper_bound"))
    for field in UPPER_BOUND_FIELDS:
        if not _is_number(upper_bound.get(field)):
            _error(errors, f"{prefix}.upper_bound.{field}", f"{field} must be numeric")

    risk = _as_mapping(record.get("risk"))
    for field in RISK_FIELDS:
        if not _is_bounded(risk.get(field)):
            _error(errors, f"{prefix}.risk.{field}", f"{field} must be in [0, 1]")

    reason_codes = record.get("reason_codes")
    if not isinstance(reason_codes, list) or not reason_codes:
        _error(errors, f"{prefix}.reason_codes", "reason_codes must be non-empty")
    else:
        unknown_codes = sorted(set(reason_codes) - REASON_CODE_REGISTRY)
        if unknown_codes:
            _error(errors, f"{prefix}.reason_codes", f"unknown reason codes: {unknown_codes}")


def validate_qe_ic_target_viability(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate target viability report contract fail-closed."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not isinstance(report, Mapping):
        _error(errors, "$", "report must be a mapping")
        return {
            "schema_version": QE_IC_TARGET_VIABILITY_VALIDATION_SCHEMA_VERSION,
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "record_count": 0,
            "target_count": 0,
        }

    if report.get("schema_version") != QE_IC_TARGET_VIABILITY_SCHEMA_VERSION:
        _error(errors, "schema_version", "schema_version is incorrect")
    if report.get("layer") != "layer3_target_viability_test":
        _error(errors, "layer", "layer must be layer3_target_viability_test")
    if report.get("source_layer1_suite_artifact") != SOURCE_LAYER1_SUITE_ARTIFACT:
        _error(
            errors,
            "source_layer1_suite_artifact",
            f"source_layer1_suite_artifact must be {SOURCE_LAYER1_SUITE_ARTIFACT}",
        )
    if report.get("source_layer2_motif_profile_artifact") != SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT:
        _error(
            errors,
            "source_layer2_motif_profile_artifact",
            f"source_layer2_motif_profile_artifact must be {SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT}",
        )

    source_layer1 = _as_mapping(report.get("source_layer1_suite"))
    source_layer2 = _as_mapping(report.get("source_layer2_motif_profile"))
    if report.get("suite_id") != source_layer1.get("suite_id"):
        _error(errors, "suite_id", "suite_id must match source Layer-1 suite")
    if source_layer2.get("schema_version") != "dse.qe_ic.motif_profile.v1":
        _error(errors, "source_layer2_motif_profile.schema_version", "Layer-2 profile schema must be present")
    if source_layer2.get("suite_id") != report.get("suite_id"):
        _error(errors, "source_layer2_motif_profile.suite_id", "Layer-2 profile suite_id must match report")

    target_config = _as_mapping(report.get("target_config"))
    target_validation = validate_qe_ic_target_config(target_config)
    if target_config.get("schema_version") != QE_IC_TARGET_CONFIG_SCHEMA_VERSION:
        _error(errors, "target_config.schema_version", "target_config schema is invalid")
    for error in target_validation.get("errors", []):
        if isinstance(error, Mapping):
            _error(errors, f"target_config.{error.get('field', '$')}", str(error.get("message", "")))

    family_ids = _family_ids(report)
    motif_registry = _motif_registry(report)
    target_ids = _target_ids(report)
    target_types_by_id = _target_types_by_id(report)
    if not family_ids:
        _error(errors, "source_layer1_suite.workload_family_ids", "known workload family IDs are missing")
    if not motif_registry:
        _error(errors, "source_layer1_suite.motif_registry", "known motifs are missing")
    if not target_ids:
        _error(errors, "target_config.targets", "known target IDs are missing")

    records = _as_list(report.get("viability_records"))
    if not records:
        _error(errors, "viability_records", "viability_records must be non-empty")
    record_target_ids = {
        record.get("target_id")
        for record in records
        if isinstance(record, Mapping) and isinstance(record.get("target_id"), str)
    }
    for target_id in sorted(target_ids):
        if target_id not in record_target_ids:
            _error(errors, f"viability_records.{target_id}", "configured target has no viability records")
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            _error(errors, f"viability_records[{index}]", "record must be a mapping")
            continue
        _validate_record(
            record,
            index=index,
            family_ids=family_ids,
            motif_registry=motif_registry,
            target_ids=target_ids,
            target_types_by_id=target_types_by_id,
            errors=errors,
        )

    summary = report.get("summary")
    if not isinstance(summary, Mapping):
        _error(errors, "summary", "summary must be a mapping")
    else:
        _validate_summary(summary, records=records, errors=errors)

    for forbidden in (
        "architecture_candidates",
        "promotion_decisions",
        "systemc_requests",
        "vivado_requests",
        "final_performance_claims",
    ):
        if forbidden in report:
            _error(
                errors,
                forbidden,
                "Layer-3 viability report must not contain architecture, promotion, implementation request, or final-claim fields",
            )

    _validate_claim_boundary(str(report.get("claim_boundary", "")), errors)
    if report.get("claim_boundary") != CLAIM_BOUNDARY:
        _warning(warnings, "claim_boundary", "claim_boundary differs from canonical Layer-3 wording")

    return {
        "schema_version": QE_IC_TARGET_VIABILITY_VALIDATION_SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "record_count": len(records),
        "target_count": len(target_ids),
    }
