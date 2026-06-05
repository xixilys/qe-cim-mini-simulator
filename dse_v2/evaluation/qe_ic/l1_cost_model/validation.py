#!/usr/bin/env python3
"""Fail-closed validation for QE-IC Layer-5A L1 cost-model results."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from typing import Any

from dse_v2.candidates.qe_ic import validate_qe_ic_candidate_plan
from dse_v2.evaluation.qe_ic.l1_cost_model.model_config import validate_qe_ic_l1_cost_model_config
from dse_v2.evaluation.qe_ic.l1_cost_model.schema import (
    BOTTLENECK_CLASSES,
    CANDIDATE_TYPES,
    CLAIM_BOUNDARY,
    ESTIMATE_FIELDS,
    FORBIDDEN_EXECUTION_FIELDS,
    LAYER_NAME,
    NEXT_FIDELITY_SUGGESTIONS,
    PRODUCER,
    QE_IC_L1_COST_MODEL_RESULTS_SCHEMA_VERSION,
    QE_IC_L1_COST_MODEL_VALIDATION_SCHEMA_VERSION,
    REASON_CODE_REGISTRY,
    RESULT_STATUSES,
    RISK_FIELDS,
    SOURCE_LAYER1_SUITE_ARTIFACT,
    SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
    SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT,
    SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT,
    TARGET_TYPES,
)


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _warning(warnings: list[dict[str, str]], field: str, message: str) -> None:
    warnings.append({"field": field, "message": message})


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_bounded(value: Any) -> bool:
    return _is_finite_number(value) and 0.0 <= float(value) <= 1.0


def _forbidden_field_paths(value: Any, *, prefix: str) -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_path = f"{prefix}.{key}" if prefix else str(key)
            if key in FORBIDDEN_EXECUTION_FIELDS:
                paths.append(key_path)
            paths.extend(_forbidden_field_paths(nested, prefix=key_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_forbidden_field_paths(nested, prefix=f"{prefix}[{index}]"))
    return paths


def _candidate_by_id(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate.get("candidate_id")): candidate
        for candidate in _as_list(plan.get("candidates"))
        if isinstance(candidate, Mapping)
    }


def _decision_by_candidate(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(decision.get("candidate_id")): decision
        for decision in _as_list(plan.get("promotion_decisions"))
        if isinstance(decision, Mapping)
    }


def _request_by_id(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(request.get("request_id")): request
        for request in _as_list(plan.get("evaluation_requests"))
        if isinstance(request, Mapping)
    }


def _planned_l1_request_ids(plan: Mapping[str, Any]) -> set[str]:
    return {
        str(request.get("request_id"))
        for request in _as_list(plan.get("evaluation_requests"))
        if isinstance(request, Mapping)
        and request.get("requested_fidelity") == "L1_cost_model"
        and request.get("status") == "planned_not_executed"
    }


def _promoted_nonbaseline_candidate_ids(plan: Mapping[str, Any]) -> set[str]:
    candidates = _candidate_by_id(plan)
    return {
        str(decision.get("candidate_id"))
        for decision in _as_list(plan.get("promotion_decisions"))
        if isinstance(decision, Mapping)
        and decision.get("decision") == "promote"
        and _as_mapping(candidates.get(str(decision.get("candidate_id")))).get("candidate_type") != "baseline"
    }


def _validate_claim_boundary(boundary: str, errors: list[dict[str, str]]) -> None:
    lowered = boundary.lower()
    if not boundary:
        _error(errors, "claim_boundary", "claim_boundary must be non-empty")
        return
    for term in ("deterministic l1 analytical cost-model estimates", "systemc/gem5/vivado/dc/qe execution results", "final performance claims"):
        if term not in lowered:
            _error(errors, "claim_boundary", f"claim_boundary must mention {term}")
    if "does not contain" not in lowered:
        _error(errors, "claim_boundary", "claim_boundary must be an explicit negative boundary")


def _validate_header(results: Mapping[str, Any], errors: list[dict[str, str]], warnings: list[dict[str, str]]) -> None:
    if results.get("schema_version") != QE_IC_L1_COST_MODEL_RESULTS_SCHEMA_VERSION:
        _error(errors, "schema_version", "schema_version is incorrect")
    if results.get("layer") != LAYER_NAME:
        _error(errors, "layer", f"layer must be {LAYER_NAME}")
    if results.get("producer") not in (None, PRODUCER):
        _error(errors, "producer", f"producer must be {PRODUCER} when present")
    expected = {
        "source_layer1_suite_artifact": SOURCE_LAYER1_SUITE_ARTIFACT,
        "source_layer2_motif_profile_artifact": SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
        "source_layer3_target_viability_artifact": SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT,
        "source_layer4_candidate_plan_artifact": SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT,
    }
    for field, value in expected.items():
        if results.get(field) != value:
            _error(errors, field, f"{field} must be {value}")
    _validate_claim_boundary(str(results.get("claim_boundary", "")), errors)
    if results.get("claim_boundary") != CLAIM_BOUNDARY:
        _warning(warnings, "claim_boundary", "claim_boundary differs from canonical wording")


def _validate_result(
    result: Mapping[str, Any],
    *,
    index: int,
    request_ids: set[str],
    request_by_id: Mapping[str, Mapping[str, Any]],
    candidate_by_id: Mapping[str, Mapping[str, Any]],
    decision_by_candidate: Mapping[str, Mapping[str, Any]],
    errors: list[dict[str, str]],
) -> None:
    prefix = f"results[{index}]"
    if not isinstance(result.get("result_id"), str) or not result.get("result_id"):
        _error(errors, f"{prefix}.result_id", "result_id must be non-empty")
    request = _as_mapping(request_by_id.get(str(result.get("request_id", ""))))
    if result.get("request_id") not in request_ids:
        _error(errors, f"{prefix}.request_id", "result references unknown request")
    elif request.get("candidate_id") != result.get("candidate_id"):
        _error(errors, f"{prefix}.request_id", "request_id must match result candidate_id")
    candidate_id = str(result.get("candidate_id", ""))
    candidate = _as_mapping(candidate_by_id.get(candidate_id))
    if not candidate:
        _error(errors, f"{prefix}.candidate_id", "result references unknown candidate")
    decision = _as_mapping(decision_by_candidate.get(candidate_id))
    if decision.get("decision") != "promote" or candidate.get("candidate_type") == "baseline":
        _error(errors, f"{prefix}.candidate_id", "result must reference a promoted non-baseline candidate")
    if result.get("candidate_type") not in CANDIDATE_TYPES:
        _error(errors, f"{prefix}.candidate_type", "candidate_type is unsupported")
    if result.get("target_type") not in TARGET_TYPES:
        _error(errors, f"{prefix}.target_type", "target_type is unsupported")
    if candidate:
        for field in ("candidate_type", "target_type", "workload_family_id", "motif_id", "template_id"):
            if result.get(field) != candidate.get(field):
                _error(errors, f"{prefix}.{field}", f"{field} must match candidate")
    if result.get("requested_fidelity") != "L1_cost_model":
        _error(errors, f"{prefix}.requested_fidelity", "requested_fidelity must be L1_cost_model")
    if result.get("result_status") not in RESULT_STATUSES:
        _error(errors, f"{prefix}.result_status", "result_status is unsupported")

    estimate = _as_mapping(result.get("estimate"))
    if set(estimate) != set(ESTIMATE_FIELDS):
        _error(errors, f"{prefix}.estimate", "estimate fields are incorrect")
    for field in ESTIMATE_FIELDS:
        if not _is_finite_number(estimate.get(field)):
            _error(errors, f"{prefix}.estimate.{field}", f"{field} must be finite numeric")
    if not _is_bounded(estimate.get("estimated_model_confidence")):
        _error(errors, f"{prefix}.estimate.estimated_model_confidence", "estimated_model_confidence must be in [0, 1]")
    if not _is_bounded(estimate.get("estimated_resource_pressure")):
        _error(errors, f"{prefix}.estimate.estimated_resource_pressure", "estimated_resource_pressure must be in [0, 1]")

    risk = _as_mapping(result.get("risk"))
    if set(risk) != set(RISK_FIELDS):
        _error(errors, f"{prefix}.risk", "risk fields are incorrect")
    for field in RISK_FIELDS:
        if not _is_bounded(risk.get(field)):
            _error(errors, f"{prefix}.risk.{field}", f"{field} must be in [0, 1]")

    bottleneck = _as_mapping(result.get("bottleneck_classification"))
    if bottleneck.get("primary_bottleneck") not in BOTTLENECK_CLASSES:
        _error(errors, f"{prefix}.bottleneck_classification.primary_bottleneck", "primary bottleneck is unsupported")
    secondary = bottleneck.get("secondary_bottlenecks")
    if not isinstance(secondary, list) or not set(secondary).issubset(BOTTLENECK_CLASSES):
        _error(errors, f"{prefix}.bottleneck_classification.secondary_bottlenecks", "secondary bottlenecks are unsupported")

    suggestion = _as_mapping(result.get("next_fidelity_suggestion"))
    if suggestion.get("suggestion") not in NEXT_FIDELITY_SUGGESTIONS:
        _error(errors, f"{prefix}.next_fidelity_suggestion.suggestion", "suggestion is unsupported")
    reason_codes = suggestion.get("reason_codes")
    if not isinstance(reason_codes, list) or not reason_codes:
        _error(errors, f"{prefix}.next_fidelity_suggestion.reason_codes", "reason_codes must be non-empty")
    elif not set(reason_codes).issubset(REASON_CODE_REGISTRY):
        _error(errors, f"{prefix}.next_fidelity_suggestion.reason_codes", "reason_codes contain unknown codes")

    traceability = _as_mapping(result.get("source_traceability"))
    expected_traceability = {
        "layer1_suite_id": candidate.get("traceability", {}).get("layer1_suite_id") if isinstance(candidate.get("traceability"), Mapping) else None,
        "layer2_profile_artifact": SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
        "layer3_viability_artifact": SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT,
        "layer4_candidate_plan_artifact": SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT,
    }
    for field, expected_value in expected_traceability.items():
        if traceability.get(field) != expected_value:
            _error(errors, f"{prefix}.source_traceability.{field}", f"{field} traceability is incorrect")
    if traceability.get("layer4_candidate_plan_artifact") != SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT:
        _error(errors, f"{prefix}.source_traceability.layer4_candidate_plan_artifact", "Layer-4 artifact traceability is incorrect")
    if candidate and traceability.get("source_viability_record_id") != candidate.get("source_viability_record_id"):
        _error(errors, f"{prefix}.source_traceability.source_viability_record_id", "source_viability_record_id must match candidate")
    if decision and traceability.get("promotion_decision_id") != decision.get("promotion_decision_id"):
        _error(errors, f"{prefix}.source_traceability.promotion_decision_id", "promotion_decision_id must match promotion decision")

    boundary = str(result.get("claim_boundary", "")).lower()
    if "deterministic l1 analytical estimate" not in boundary or "not measured" not in boundary:
        _error(errors, f"{prefix}.claim_boundary", "result claim_boundary must exclude measured performance")
    for path in _forbidden_field_paths(result, prefix=prefix):
        _error(errors, path, "forbidden high-fidelity execution or measured field is present")


def _expected_summary(result_rows: list[Any]) -> dict[str, Any]:
    by_target_type: dict[str, dict[str, int]] = {}
    by_suggestion: Counter[str] = Counter()
    completed = 0
    failed = 0
    high_risk = 0
    recommended = 0
    for result in result_rows:
        if not isinstance(result, Mapping):
            continue
        target_type = str(result.get("target_type"))
        bucket = by_target_type.setdefault(
            target_type,
            {
                "request_count": 0,
                "completed_estimate_count": 0,
                "failed_estimate_count": 0,
            },
        )
        bucket["request_count"] += 1
        if result.get("result_status") == "completed_estimate":
            completed += 1
            bucket["completed_estimate_count"] += 1
        elif result.get("result_status") == "failed_estimate":
            failed += 1
            bucket["failed_estimate_count"] += 1
        suggestion = _as_mapping(result.get("next_fidelity_suggestion")).get("suggestion")
        if isinstance(suggestion, str):
            by_suggestion[suggestion] += 1
            if suggestion.startswith("promote_to_"):
                recommended += 1
        risk = _as_mapping(result.get("risk"))
        if _is_finite_number(risk.get("overall_l1_risk")) and risk["overall_l1_risk"] >= 0.65:
            high_risk += 1
    return {
        "request_count": len([row for row in result_rows if isinstance(row, Mapping)]),
        "completed_estimate_count": completed,
        "failed_estimate_count": failed,
        "by_target_type": by_target_type,
        "by_suggestion": dict(sorted(by_suggestion.items())),
        "high_risk_count": high_risk,
        "recommended_next_fidelity_count": recommended,
    }


def validate_qe_ic_l1_cost_model_results(results: Mapping[str, Any]) -> dict[str, Any]:
    """Validate QE-IC Layer-5A results fail-closed."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(results, Mapping):
        _error(errors, "$", "results must be a mapping")
        return {
            "schema_version": QE_IC_L1_COST_MODEL_VALIDATION_SCHEMA_VERSION,
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "result_count": 0,
        }

    _validate_header(results, errors, warnings)
    for path in _forbidden_field_paths(results, prefix=""):
        _error(errors, path, "forbidden high-fidelity execution or measured field is present")

    model_validation = validate_qe_ic_l1_cost_model_config(_as_mapping(results.get("model_config")))
    if model_validation.get("status") != "passed":
        for error in model_validation.get("errors", []):
            if isinstance(error, Mapping):
                _error(errors, f"model_config.{error.get('field', '$')}", f"invalid model config: {error.get('message', '')}")

    candidate_plan = _as_mapping(results.get("source_layer4_candidate_plan"))
    plan_validation = validate_qe_ic_candidate_plan(candidate_plan)
    if plan_validation.get("status") != "passed":
        for error in plan_validation.get("errors", []):
            if isinstance(error, Mapping):
                _error(errors, f"source_layer4_candidate_plan.{error.get('field', '$')}", f"invalid candidate plan: {error.get('message', '')}")

    request_ids = _planned_l1_request_ids(candidate_plan)
    request_by_id = _request_by_id(candidate_plan)
    candidate_by_id = _candidate_by_id(candidate_plan)
    decision_by_candidate = _decision_by_candidate(candidate_plan)
    promoted_nonbaseline_ids = _promoted_nonbaseline_candidate_ids(candidate_plan)
    result_rows = _as_list(results.get("results"))
    result_ids: list[str] = []
    result_request_counts: Counter[str] = Counter()
    result_candidate_ids: set[str] = set()
    for index, result in enumerate(result_rows):
        if not isinstance(result, Mapping):
            _error(errors, f"results[{index}]", "result must be a mapping")
            continue
        if isinstance(result.get("result_id"), str):
            result_ids.append(result["result_id"])
        if isinstance(result.get("request_id"), str):
            result_request_counts[result["request_id"]] += 1
        if isinstance(result.get("candidate_id"), str):
            result_candidate_ids.add(result["candidate_id"])
        _validate_result(
            result,
            index=index,
            request_ids=request_ids,
            request_by_id=request_by_id,
            candidate_by_id=candidate_by_id,
            decision_by_candidate=decision_by_candidate,
            errors=errors,
        )
    if len(result_ids) != len(set(result_ids)):
        _error(errors, "results.result_id", "result_id values must be unique")
    result_request_ids = set(result_request_counts)
    if result_request_ids != request_ids:
        missing = sorted(request_ids - result_request_ids)
        extra = sorted(result_request_ids - request_ids)
        _error(
            errors,
            "results.request_id",
            f"each Layer-4 L1 evaluation request must have exactly one result; missing={missing}, extra={extra}",
        )
    duplicates = sorted(request_id for request_id, count in result_request_counts.items() if count != 1)
    if duplicates:
        _error(
            errors,
            "results.request_id",
            f"each Layer-4 L1 evaluation request must have exactly one result; duplicates={duplicates}",
        )
    if result_candidate_ids != promoted_nonbaseline_ids:
        missing = sorted(promoted_nonbaseline_ids - result_candidate_ids)
        extra = sorted(result_candidate_ids - promoted_nonbaseline_ids)
        _error(
            errors,
            "results.candidate_id",
            f"results must exactly cover promoted non-baseline candidates; missing={missing}, extra={extra}",
        )

    expected_summary = _expected_summary(result_rows)
    if _as_mapping(results.get("summary")) != expected_summary:
        _error(errors, "summary", "summary must exactly match results")

    return {
        "schema_version": QE_IC_L1_COST_MODEL_VALIDATION_SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "result_count": len(result_rows),
    }
