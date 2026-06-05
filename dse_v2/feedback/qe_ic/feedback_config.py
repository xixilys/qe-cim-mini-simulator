#!/usr/bin/env python3
"""Config validation for QE-IC Layer-6 synthetic feedback calibration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dse_v2.feedback.qe_ic.schema import (
    CONFIG_CLAIM_BOUNDARY,
    POLICY_VERSION,
    QE_IC_FEEDBACK_CONFIG_SCHEMA_VERSION,
    SYNTHETIC_LABELS,
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


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_bounded(value: Any) -> bool:
    return _is_number(value) and 0.0 <= float(value) <= 1.0


def validate_qe_ic_feedback_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate Layer-6 feedback config fail-closed."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(config, Mapping):
        _error(errors, "$", "feedback config must be a mapping")
        return {
            "schema_version": "dse.qe_ic.feedback_config_validation.v1",
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
        }

    if config.get("schema_version") != QE_IC_FEEDBACK_CONFIG_SCHEMA_VERSION:
        _error(errors, "schema_version", "feedback config schema_version is incorrect")
    if not isinstance(config.get("config_id"), str) or not config.get("config_id"):
        _error(errors, "config_id", "config_id must be a non-empty string")
    if config.get("policy_version") != POLICY_VERSION:
        _error(errors, "policy_version", f"policy_version must be {POLICY_VERSION}")
    if not _is_positive_int(config.get("top_k")):
        _error(errors, "top_k", "top_k must be a positive integer")

    label_policy = _as_mapping(config.get("label_policy"))
    if label_policy.get("labels_are_synthetic_replay_only") is not True:
        _error(
            errors,
            "label_policy.labels_are_synthetic_replay_only",
            "labels_are_synthetic_replay_only must be true",
        )
    allowed_labels = set(_as_list(label_policy.get("allowed_labels")))
    if allowed_labels != SYNTHETIC_LABELS:
        _error(
            errors,
            "label_policy.allowed_labels",
            f"allowed_labels must equal {sorted(SYNTHETIC_LABELS)}",
        )

    thresholds = _as_mapping(config.get("initial_risk_thresholds"))
    for field in (
        "promotion_overall_l1_risk_max",
        "resource_risk_max",
        "transfer_risk_max",
        "minimum_expected_improvement",
    ):
        if not _is_bounded(thresholds.get(field)):
            _error(errors, f"initial_risk_thresholds.{field}", f"{field} must be in [0, 1]")

    policy = _as_mapping(config.get("calibration_policy"))
    for field in (
        "false_promotion_tighten_step",
        "useful_relax_step",
        "template_adjustment_step",
        "motif_adjustment_step",
        "target_type_adjustment_step",
    ):
        if not _is_bounded(policy.get(field)):
            _error(errors, f"calibration_policy.{field}", f"{field} must be in [0, 1]")

    stopping = _as_mapping(config.get("stopping_conditions"))
    if stopping.get("decision_basis") != "synthetic_replay_stop_decision":
        _error(
            errors,
            "stopping_conditions.decision_basis",
            "decision_basis must be synthetic_replay_stop_decision",
        )
    for field in (
        "current_round",
        "max_rounds",
        "synthetic_label_budget",
        "no_new_useful_candidate_rounds",
        "no_new_useful_candidate_rounds_limit",
        "top_k_useful_target",
    ):
        if not _is_nonnegative_int(stopping.get(field)):
            _error(errors, f"stopping_conditions.{field}", f"{field} must be a non-negative integer")
    for field in ("false_promotion_rate_target", "expected_improvement_threshold"):
        if not _is_bounded(stopping.get(field)):
            _error(errors, f"stopping_conditions.{field}", f"{field} must be in [0, 1]")

    boundary = str(config.get("claim_boundary", ""))
    lowered = boundary.lower()
    for term in ("synthetic replay calibration", "does not request", "final performance claims"):
        if term not in lowered:
            _error(errors, "claim_boundary", f"claim_boundary must mention {term}")
    if config.get("claim_boundary") != CONFIG_CLAIM_BOUNDARY:
        _warning(warnings, "claim_boundary", "claim_boundary differs from canonical wording")

    return {
        "schema_version": "dse.qe_ic.feedback_config_validation.v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
    }
