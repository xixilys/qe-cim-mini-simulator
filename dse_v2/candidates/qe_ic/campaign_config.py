#!/usr/bin/env python3
"""Campaign config validation for QE-IC Layer-4 candidate planning."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dse_v2.candidates.qe_ic.schema import (
    BUDGET_FIELDS,
    CAMPAIGN_CLAIM_BOUNDARY,
    QE_IC_LAYER4_CAMPAIGN_SCHEMA_VERSION,
    TARGET_TYPES,
)


ALLOWED_GENERATION_DECISIONS = {"maybe", "viable"}
ALLOWED_OBJECTIVES = {"risk_aware_budgeted_promotion"}
ALLOWED_ENTRY_FIDELITIES = {"L0_target_viability"}
ALLOWED_NEXT_FIDELITIES = {"L1_cost_model"}


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _warning(warnings: list[dict[str, str]], field: str, message: str) -> None:
    warnings.append({"field": field, "message": message})


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_bounded_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and 0.0 <= float(value) <= 1.0
    )


def _validate_claim_boundary(boundary: str, errors: list[dict[str, str]]) -> None:
    lowered = boundary.lower()
    if not boundary:
        _error(errors, "claim_boundary", "claim_boundary must be non-empty")
        return
    for term in ("candidate generation", "promotion", "execution", "final performance"):
        if term not in lowered:
            _error(errors, "claim_boundary", f"claim_boundary must mention {term}")
    if "does not" not in lowered and "not" not in lowered:
        _error(errors, "claim_boundary", "claim_boundary must explicitly exclude execution and final claims")


def validate_qe_ic_campaign_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a Layer-4 campaign config fail-closed."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(config, Mapping):
        _error(errors, "$", "campaign config must be a mapping")
        return {
            "schema_version": "dse.qe_ic.layer4_campaign_validation.v1",
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
        }

    if config.get("schema_version") != QE_IC_LAYER4_CAMPAIGN_SCHEMA_VERSION:
        _error(errors, "schema_version", "campaign schema_version is incorrect")
    if not isinstance(config.get("campaign_id"), str) or not config.get("campaign_id"):
        _error(errors, "campaign_id", "campaign_id must be a non-empty string")

    generation = _as_mapping(config.get("candidate_generation"))
    if generation.get("include_baseline_gpu") is not True:
        _error(
            errors,
            "candidate_generation.include_baseline_gpu",
            "include_baseline_gpu must be true for QE-IC Layer-4 baseline traceability",
        )
    decisions = _as_list(generation.get("generate_from_decisions"))
    if not decisions:
        _error(errors, "candidate_generation.generate_from_decisions", "generate_from_decisions must be non-empty")
    elif not set(decisions).issubset(ALLOWED_GENERATION_DECISIONS):
        _error(
            errors,
            "candidate_generation.generate_from_decisions",
            f"generate_from_decisions must be within {sorted(ALLOWED_GENERATION_DECISIONS)}",
        )
    if generation.get("ignore_reject_records") is not True:
        _error(
            errors,
            "candidate_generation.ignore_reject_records",
            "ignore_reject_records must be true so reject records do not generate accelerators",
        )
    if not _is_positive_int(generation.get("max_candidates_per_motif")):
        _error(errors, "candidate_generation.max_candidates_per_motif", "max_candidates_per_motif must be > 0")
    if not _is_positive_int(generation.get("max_candidates_per_target_type")):
        _error(
            errors,
            "candidate_generation.max_candidates_per_target_type",
            "max_candidates_per_target_type must be > 0",
        )

    allowed_target_types = _as_list(config.get("allowed_target_types"))
    if not allowed_target_types:
        _error(errors, "allowed_target_types", "allowed_target_types must be non-empty")
    elif not set(allowed_target_types).issubset(TARGET_TYPES):
        _error(errors, "allowed_target_types", f"allowed_target_types must be within {sorted(TARGET_TYPES)}")
    if "gpu_only" not in allowed_target_types:
        _error(errors, "allowed_target_types", "gpu_only must be allowed for baseline generation")

    template_families = _as_list(config.get("allowed_candidate_template_families"))
    if not template_families:
        _error(
            errors,
            "allowed_candidate_template_families",
            "allowed_candidate_template_families must be non-empty",
        )

    promotion = _as_mapping(config.get("promotion"))
    if promotion.get("entry_fidelity") not in ALLOWED_ENTRY_FIDELITIES:
        _error(errors, "promotion.entry_fidelity", "entry_fidelity must be L0_target_viability")
    if promotion.get("next_fidelity") not in ALLOWED_NEXT_FIDELITIES:
        _error(errors, "promotion.next_fidelity", "next_fidelity must be L1_cost_model")
    if promotion.get("objective") not in ALLOWED_OBJECTIVES:
        _error(errors, "promotion.objective", "promotion objective is unsupported")
    for field in ("require_diversity_across_target_type", "require_diversity_across_motif"):
        if not isinstance(promotion.get(field), bool):
            _error(errors, f"promotion.{field}", f"{field} must be boolean")
    budget = _as_mapping(promotion.get("budget"))
    for field in BUDGET_FIELDS:
        if not _is_nonnegative_int(budget.get(field)):
            _error(errors, f"promotion.budget.{field}", f"{field} must be a non-negative integer")
    for zero_budget_field in (
        "max_systemc_requests",
        "max_gem5_requests",
        "max_vivado_requests",
        "max_real_qe_requests",
    ):
        if _is_nonnegative_int(budget.get(zero_budget_field)) and budget.get(zero_budget_field) != 0:
            _error(
                errors,
                f"promotion.budget.{zero_budget_field}",
                f"{zero_budget_field} must be 0 for Layer-4 planning-only artifacts",
            )

    risk_tolerance = config.get("risk_tolerance", 0.65)
    if not _is_bounded_number(risk_tolerance):
        _error(errors, "risk_tolerance", "risk_tolerance must be in [0, 1]")
    _validate_claim_boundary(str(config.get("claim_boundary", "")), errors)
    if config.get("claim_boundary") != CAMPAIGN_CLAIM_BOUNDARY:
        _warning(warnings, "claim_boundary", "claim_boundary differs from canonical Layer-4 campaign wording")

    replay = config.get("replay_validation")
    if replay is not None and not isinstance(replay, Mapping):
        _error(errors, "replay_validation", "replay_validation must be a mapping when present")

    return {
        "schema_version": "dse.qe_ic.layer4_campaign_validation.v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
    }

