#!/usr/bin/env python3
"""Fail-closed validation for QE-IC Layer-4 candidate plans."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from dse_v2.candidates.qe_ic.campaign_config import validate_qe_ic_campaign_config
from dse_v2.candidates.qe_ic.schema import (
    BUDGET_FIELDS,
    CANDIDATE_TYPES,
    CLAIM_BOUNDARY,
    EXECUTION_FORBIDDEN_FIELDS,
    FIDELITIES,
    LAYER_NAME,
    PRODUCER,
    PROMOTION_DECISIONS,
    PROMOTION_REASON_CODE_REGISTRY,
    QE_IC_CANDIDATE_PLAN_SCHEMA_VERSION,
    QE_IC_CANDIDATE_PLAN_VALIDATION_SCHEMA_VERSION,
    REQUEST_FORBIDDEN_FIELDS,
    SOURCE_LAYER1_SUITE_ARTIFACT,
    SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
    SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT,
    SOURCE_VIABILITY_DECISIONS,
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


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _as_int(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _source_family_ids(plan: Mapping[str, Any]) -> set[str]:
    return {
        str(family_id)
        for family_id in _as_list(_as_mapping(plan.get("source_indexes")).get("workload_family_ids"))
        if isinstance(family_id, str)
    }


def _source_motif_ids(plan: Mapping[str, Any]) -> set[str]:
    return {
        str(motif_id)
        for motif_id in _as_list(_as_mapping(plan.get("source_indexes")).get("motif_ids"))
        if isinstance(motif_id, str)
    }


def _source_record_ids(plan: Mapping[str, Any]) -> set[str]:
    return set(_as_mapping(_as_mapping(plan.get("source_indexes")).get("viability_records_by_id")).keys())


def _source_records(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    return _as_mapping(_as_mapping(plan.get("source_indexes")).get("viability_records_by_id"))


def _validate_claim_boundary(boundary: str, *, field: str, errors: list[dict[str, str]]) -> None:
    lowered = boundary.lower()
    if not boundary:
        _error(errors, field, "claim_boundary must be non-empty")
        return
    for term in ("candidate specifications", "promotion plans", "executed systemc/gem5/vivado/qe results", "final performance claims"):
        if term not in lowered:
            _error(errors, field, f"claim_boundary must mention {term}")
    if "does not contain" not in lowered:
        _error(errors, field, "claim_boundary must be an explicit negative boundary")


def _validate_plan_header(
    plan: Mapping[str, Any],
    *,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    if plan.get("schema_version") != QE_IC_CANDIDATE_PLAN_SCHEMA_VERSION:
        _error(errors, "schema_version", "schema_version is incorrect")
    if plan.get("layer") != LAYER_NAME:
        _error(errors, "layer", f"layer must be {LAYER_NAME}")
    expected_artifacts = {
        "source_layer1_suite_artifact": SOURCE_LAYER1_SUITE_ARTIFACT,
        "source_layer2_motif_profile_artifact": SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
        "source_layer3_target_viability_artifact": SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT,
    }
    for field, expected in expected_artifacts.items():
        if plan.get(field) != expected:
            _error(errors, field, f"{field} must be {expected}")
    if not isinstance(plan.get("suite_id"), str) or not plan.get("suite_id"):
        _error(errors, "suite_id", "suite_id must be non-empty")
    registry = _as_mapping(plan.get("candidate_template_registry"))
    if not isinstance(plan.get("candidate_template_registry"), Mapping):
        _error(errors, "candidate_template_registry", "candidate_template_registry must be present")
    elif not _as_mapping(registry.get("templates")):
        _error(errors, "candidate_template_registry.templates", "candidate_template_registry must include templates")
    if not isinstance(plan.get("source_indexes"), Mapping):
        _error(errors, "source_indexes", "source_indexes must be present")
    _validate_claim_boundary(str(plan.get("claim_boundary", "")), field="claim_boundary", errors=errors)
    if plan.get("claim_boundary") != CLAIM_BOUNDARY:
        _warning(warnings, "claim_boundary", "claim_boundary differs from canonical wording")


def _validate_campaign(plan: Mapping[str, Any], errors: list[dict[str, str]]) -> None:
    config = _as_mapping(plan.get("campaign_config"))
    validation = validate_qe_ic_campaign_config(config)
    if validation.get("status") != "passed":
        for error in _as_list(validation.get("errors")):
            if isinstance(error, Mapping):
                _error(
                    errors,
                    f"campaign_config.{error.get('field', '$')}",
                    f"invalid campaign config: {error.get('message', '')}",
                )


def _validate_candidate(
    candidate: Mapping[str, Any],
    *,
    index: int,
    suite_id: str,
    family_ids: set[str],
    motif_ids: set[str],
    source_record_ids: set[str],
    source_records: Mapping[str, Any],
    errors: list[dict[str, str]],
) -> None:
    prefix = f"candidates[{index}]"
    for field in (
        "candidate_id",
        "candidate_type",
        "target_type",
        "workload_family_id",
        "motif_id",
        "source_viability_record_id",
        "source_viability_decision",
        "template_id",
        "candidate_parameters",
        "traceability",
    ):
        if field not in candidate:
            _error(errors, f"{prefix}.{field}", "required candidate field is missing")
    if not isinstance(candidate.get("candidate_id"), str) or not candidate.get("candidate_id"):
        _error(errors, f"{prefix}.candidate_id", "candidate_id must be a non-empty string")
    if candidate.get("candidate_type") not in CANDIDATE_TYPES:
        _error(errors, f"{prefix}.candidate_type", "candidate_type is unsupported")
    if candidate.get("target_type") not in TARGET_TYPES:
        _error(errors, f"{prefix}.target_type", "target_type is unsupported")
    if candidate.get("workload_family_id") not in family_ids:
        _error(errors, f"{prefix}.workload_family_id", "candidate references unknown workload family")
    if candidate.get("motif_id") not in motif_ids:
        _error(errors, f"{prefix}.motif_id", "candidate references unknown motif")
    source_id = str(candidate.get("source_viability_record_id", ""))
    if source_id not in source_record_ids:
        _error(errors, f"{prefix}.source_viability_record_id", "candidate references unknown source viability record")
    source_record = _as_mapping(source_records.get(source_id))
    source_decision = candidate.get("source_viability_decision")
    if source_decision not in SOURCE_VIABILITY_DECISIONS:
        _error(errors, f"{prefix}.source_viability_decision", "source_viability_decision is unsupported")
    if candidate.get("candidate_type") == "baseline":
        if candidate.get("target_type") != "gpu_only":
            _error(errors, f"{prefix}.target_type", "baseline candidates must target gpu_only")
        if source_decision != "baseline":
            _error(errors, f"{prefix}.source_viability_decision", "baseline GPU candidates must be marked baseline")
    elif source_record.get("decision") == "reject":
        _error(errors, f"{prefix}.source_viability_record_id", "reject viability records must not generate accelerator candidates")
    traceability = _as_mapping(candidate.get("traceability"))
    if not traceability:
        _error(errors, f"{prefix}.traceability", "every candidate must include traceability")
    else:
        if traceability.get("layer1_suite_id") != suite_id:
            _error(errors, f"{prefix}.traceability.layer1_suite_id", "layer1_suite_id must match plan suite_id")
        if traceability.get("layer2_profile_artifact") != SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT:
            _error(errors, f"{prefix}.traceability.layer2_profile_artifact", "Layer-2 artifact traceability is incorrect")
        if traceability.get("layer3_viability_artifact") != SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT:
            _error(errors, f"{prefix}.traceability.layer3_viability_artifact", "Layer-3 artifact traceability is incorrect")


def _validate_promotion_decision(
    decision: Mapping[str, Any],
    *,
    index: int,
    candidate_ids: set[str],
    errors: list[dict[str, str]],
) -> None:
    prefix = f"promotion_decisions[{index}]"
    if not isinstance(decision.get("promotion_decision_id"), str) or not decision.get("promotion_decision_id"):
        _error(errors, f"{prefix}.promotion_decision_id", "promotion_decision_id must be non-empty")
    if decision.get("candidate_id") not in candidate_ids:
        _error(errors, f"{prefix}.candidate_id", "promotion decision references unknown candidate")
    if decision.get("decision") not in PROMOTION_DECISIONS:
        _error(errors, f"{prefix}.decision", "promotion decision is unsupported")
    if decision.get("current_fidelity") != "L0_target_viability":
        _error(errors, f"{prefix}.current_fidelity", "current_fidelity must be L0_target_viability")
    if decision.get("next_fidelity") not in FIDELITIES:
        _error(errors, f"{prefix}.next_fidelity", "next_fidelity is unsupported")
    if not isinstance(decision.get("promotion_priority"), int):
        _error(errors, f"{prefix}.promotion_priority", "promotion_priority must be an integer")
    if not _is_number(decision.get("promotion_score")):
        _error(errors, f"{prefix}.promotion_score", "promotion_score must be numeric")
    reason_codes = decision.get("reason_codes")
    if not isinstance(reason_codes, list) or not reason_codes:
        _error(errors, f"{prefix}.reason_codes", "every promotion decision must have reason codes")
    else:
        unknown_codes = sorted(set(reason_codes) - PROMOTION_REASON_CODE_REGISTRY)
        if unknown_codes:
            _error(errors, f"{prefix}.reason_codes", f"unknown reason codes: {unknown_codes}")
    evidence = _as_mapping(decision.get("evidence_summary"))
    for field in (
        "source_viability_score",
        "source_decision",
        "estimated_net_gain_ratio",
        "risk_score",
        "runtime_ratio",
        "diversity_group",
    ):
        if field not in evidence:
            _error(errors, f"{prefix}.evidence_summary.{field}", "required evidence summary field is missing")


def _validate_request(
    request: Mapping[str, Any],
    *,
    index: int,
    promoted_ids: set[str],
    errors: list[dict[str, str]],
) -> None:
    prefix = f"evaluation_requests[{index}]"
    if not isinstance(request.get("request_id"), str) or not request.get("request_id"):
        _error(errors, f"{prefix}.request_id", "request_id must be non-empty")
    if request.get("candidate_id") not in promoted_ids:
        _error(errors, f"{prefix}.candidate_id", "evaluation request references a non-promoted candidate")
    if request.get("requested_fidelity") != "L1_cost_model":
        _error(errors, f"{prefix}.requested_fidelity", "Layer-4 may only request L1_cost_model")
    if request.get("status") != "planned_not_executed":
        _error(errors, f"{prefix}.status", "evaluation request status must be planned_not_executed")
    if not isinstance(request.get("required_inputs"), list) or not request.get("required_inputs"):
        _error(errors, f"{prefix}.required_inputs", "required_inputs must be non-empty")
    boundary = str(request.get("claim_boundary", ""))
    if "planned evaluation request only" not in boundary.lower() or "no execution result" not in boundary.lower():
        _error(errors, f"{prefix}.claim_boundary", "request claim_boundary must exclude execution results")
    for forbidden in REQUEST_FORBIDDEN_FIELDS:
        if forbidden in request:
            _error(errors, f"{prefix}.{forbidden}", "evaluation request must not include execution or final-claim results")


def _validate_budget_and_summary(
    plan: Mapping[str, Any],
    *,
    decisions: list[Any],
    requests: list[Any],
    errors: list[dict[str, str]],
) -> None:
    promotion = _as_mapping(_as_mapping(plan.get("campaign_config")).get("promotion"))
    budget = _as_mapping(promotion.get("budget"))
    promote_count = sum(
        1
        for decision in decisions
        if isinstance(decision, Mapping) and decision.get("decision") == "promote"
    )
    if promote_count > _as_int(budget.get("max_l1_cost_model_requests")):
        _error(errors, "summary.budget_used.max_l1_cost_model_requests", "promotion budget is exceeded")
    for field in BUDGET_FIELDS[1:]:
        if _as_int(budget.get(field)) != 0:
            _error(errors, f"campaign_config.promotion.budget.{field}", "Layer-4 budget for execution stages must be zero")
    summary = _as_mapping(plan.get("summary"))
    expected_counts = Counter(
        decision.get("decision")
        for decision in decisions
        if isinstance(decision, Mapping)
    )
    expected = {
        "candidate_count": len(_as_list(plan.get("candidates"))),
        "baseline_count": expected_counts.get("baseline", 0),
        "promote_count": expected_counts.get("promote", 0),
        "hold_count": expected_counts.get("hold", 0),
        "reject_count": expected_counts.get("reject", 0),
        "evaluation_request_count": len(requests),
    }
    for field, value in expected.items():
        if summary.get(field) != value:
            _error(errors, f"summary.{field}", f"summary.{field} must match plan contents")
    budget_used = _as_mapping(summary.get("budget_used"))
    if budget_used.get("max_l1_cost_model_requests") != promote_count:
        _error(errors, "summary.budget_used.max_l1_cost_model_requests", "budget_used must equal promoted request count")


def _validate_diversity(plan: Mapping[str, Any], errors: list[dict[str, str]]) -> None:
    promotion = _as_mapping(_as_mapping(plan.get("campaign_config")).get("promotion"))
    summary = _as_mapping(plan.get("summary"))
    diversity = _as_mapping(summary.get("diversity"))
    promote_count = _as_int(summary.get("promote_count"))
    for field, campaign_field in (
        ("target_type_required", "require_diversity_across_target_type"),
        ("motif_required", "require_diversity_across_motif"),
    ):
        if diversity.get(field) != promotion.get(campaign_field):
            _error(errors, f"summary.diversity.{field}", "diversity requirement representation is inconsistent")
    if promotion.get("require_diversity_across_target_type") is True and promote_count > 1:
        if _as_int(diversity.get("promoted_target_type_count")) <= 1:
            _error(errors, "summary.diversity.promoted_target_type_count", "target diversity is required but not represented")
    if promotion.get("require_diversity_across_motif") is True and promote_count > 1:
        if _as_int(diversity.get("promoted_motif_count")) <= 1:
            _error(errors, "summary.diversity.promoted_motif_count", "motif diversity is required but not represented")


def validate_qe_ic_candidate_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate QE-IC Layer-4 candidate plan contract fail-closed."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(plan, Mapping):
        _error(errors, "$", "candidate plan must be a mapping")
        return {
            "schema_version": QE_IC_CANDIDATE_PLAN_VALIDATION_SCHEMA_VERSION,
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "candidate_count": 0,
            "promotion_decision_count": 0,
            "evaluation_request_count": 0,
        }

    _validate_plan_header(plan, errors=errors, warnings=warnings)
    _validate_campaign(plan, errors)
    for forbidden in EXECUTION_FORBIDDEN_FIELDS:
        if forbidden in plan:
            _error(errors, forbidden, "Layer-4 candidate plan must not contain execution results or final performance claims")

    family_ids = _source_family_ids(plan)
    motif_ids = _source_motif_ids(plan)
    source_record_ids = _source_record_ids(plan)
    source_records = _source_records(plan)
    if not family_ids:
        _error(errors, "source_indexes.workload_family_ids", "source Layer-1 family references are missing")
    if not motif_ids:
        _error(errors, "source_indexes.motif_ids", "source Layer-1 motif references are missing")
    if not source_record_ids:
        _error(errors, "source_indexes.viability_records_by_id", "source Layer-3 viability records are missing")

    candidates = _as_list(plan.get("candidates"))
    if not candidates:
        _error(errors, "candidates", "candidates must be non-empty")
    candidate_ids: list[str] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            _error(errors, f"candidates[{index}]", "candidate must be a mapping")
            continue
        if isinstance(candidate.get("candidate_id"), str):
            candidate_ids.append(candidate["candidate_id"])
        _validate_candidate(
            candidate,
            index=index,
            suite_id=str(plan.get("suite_id", "")),
            family_ids=family_ids,
            motif_ids=motif_ids,
            source_record_ids=source_record_ids,
            source_records=source_records,
            errors=errors,
        )
    if len(candidate_ids) != len(set(candidate_ids)):
        _error(errors, "candidates.candidate_id", "candidate IDs must be unique")

    candidate_id_set = set(candidate_ids)
    decisions = _as_list(plan.get("promotion_decisions"))
    decision_ids: list[str] = []
    if not decisions:
        _error(errors, "promotion_decisions", "promotion_decisions must be non-empty")
    for index, decision in enumerate(decisions):
        if not isinstance(decision, Mapping):
            _error(errors, f"promotion_decisions[{index}]", "promotion decision must be a mapping")
            continue
        if isinstance(decision.get("promotion_decision_id"), str):
            decision_ids.append(decision["promotion_decision_id"])
        _validate_promotion_decision(
            decision,
            index=index,
            candidate_ids=candidate_id_set,
            errors=errors,
        )
    if len(decision_ids) != len(set(decision_ids)):
        _error(errors, "promotion_decisions.promotion_decision_id", "promotion decision IDs must be unique")

    promoted_ids = {
        str(decision.get("candidate_id"))
        for decision in decisions
        if isinstance(decision, Mapping) and decision.get("decision") == "promote"
    }
    requests = _as_list(plan.get("evaluation_requests"))
    for index, request in enumerate(requests):
        if not isinstance(request, Mapping):
            _error(errors, f"evaluation_requests[{index}]", "evaluation request must be a mapping")
            continue
        _validate_request(request, index=index, promoted_ids=promoted_ids, errors=errors)

    _validate_budget_and_summary(plan, decisions=decisions, requests=requests, errors=errors)
    _validate_diversity(plan, errors)

    if plan.get("producer") not in (None, PRODUCER):
        _error(errors, "producer", f"producer must be {PRODUCER} when present")

    return {
        "schema_version": QE_IC_CANDIDATE_PLAN_VALIDATION_SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "candidate_count": len(candidates),
        "promotion_decision_count": len(decisions),
        "evaluation_request_count": len(requests),
    }
