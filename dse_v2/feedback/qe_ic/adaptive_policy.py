#!/usr/bin/env python3
"""Deterministic QE-IC Layer-6 adaptive feedback policy."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any

from dse_v2.feedback.qe_ic.schema import (
    FALSE_PROMOTION_LABELS,
    POLICY_VERSION,
    STOPPING_CONDITIONS,
    WASTED_BUDGET_LABELS,
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _rank_value(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 10**9


def _numeric_value(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else default


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


def build_calibration_update(
    *,
    candidate_plan: Mapping[str, Any],
    feedback_records: list[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Build deterministic threshold and risk adjustment updates."""

    thresholds = _as_mapping(config.get("initial_risk_thresholds"))
    policy = _as_mapping(config.get("calibration_policy"))
    false_rate = float(metrics.get("false_promotion_rate", 0.0))
    precision = float(metrics.get("promotion_precision", 0.0))
    tighten = float(policy.get("false_promotion_tighten_step", 0.05))
    relax = float(policy.get("useful_relax_step", 0.02))
    threshold_direction = "tighten_after_false_promotions" if false_rate > 0.0 else "relax_after_clean_promotions"
    delta = -tighten if false_rate > 0.0 else relax
    risk_threshold_updates = {
        "promotion_overall_l1_risk_max": {
            "old": thresholds.get("promotion_overall_l1_risk_max"),
            "new": _clamp(float(thresholds.get("promotion_overall_l1_risk_max", 0.45)) + delta),
            "reason_codes": [threshold_direction],
        },
        "resource_risk_max": {
            "old": thresholds.get("resource_risk_max"),
            "new": _clamp(
                float(thresholds.get("resource_risk_max", 0.75))
                - (tighten if metrics.get("resource_invalid_count", 0) else 0.0)
            ),
            "reason_codes": ["resource_invalid_feedback" if metrics.get("resource_invalid_count", 0) else "no_resource_invalid_feedback"],
        },
        "transfer_risk_max": {
            "old": thresholds.get("transfer_risk_max"),
            "new": _clamp(
                float(thresholds.get("transfer_risk_max", 0.35))
                - (tighten if metrics.get("overhead_invalid_count", 0) else 0.0)
            ),
            "reason_codes": ["overhead_invalid_feedback" if metrics.get("overhead_invalid_count", 0) else "no_overhead_invalid_feedback"],
        },
        "minimum_expected_improvement": {
            "old": thresholds.get("minimum_expected_improvement"),
            "new": _clamp(
                float(thresholds.get("minimum_expected_improvement", 0.02))
                + (0.01 if false_rate > precision else 0.0)
            ),
            "reason_codes": ["false_promotion_guard_band" if false_rate > precision else "keep_expected_improvement_floor"],
        },
    }

    by_template: dict[str, Counter[str]] = defaultdict(Counter)
    by_motif: dict[str, Counter[str]] = defaultdict(Counter)
    by_target_type: dict[str, Counter[str]] = defaultdict(Counter)
    for record in feedback_records:
        label = str(record.get("synthetic_label", "unlabeled"))
        by_template[str(record.get("template_id"))][label] += 1
        by_motif[str(record.get("motif_id"))][label] += 1
        by_target_type[str(record.get("target_type"))][label] += 1

    def _adjustments(counter_by_key: Mapping[str, Counter[str]], step: float) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for key, counter in sorted(counter_by_key.items()):
            useful = counter.get("useful", 0) + counter.get("false_rejection", 0)
            harmful = sum(counter.get(label, 0) for label in FALSE_PROMOTION_LABELS)
            if harmful > useful:
                adjustment = step
                reason = "increase_risk_after_false_promotion"
            elif useful > harmful:
                adjustment = -step
                reason = "decrease_risk_after_useful_feedback"
            else:
                adjustment = 0.0
                reason = "hold_risk_after_mixed_feedback"
            out[key] = {
                "risk_adjustment": round(adjustment, 6),
                "label_counts": dict(sorted(counter.items())),
                "reason_codes": [reason],
            }
        return out

    return {
        "risk_threshold_updates": risk_threshold_updates,
        "template_adjustments": _adjustments(
            by_template,
            float(policy.get("template_adjustment_step", 0.1)),
        ),
        "motif_adjustments": _adjustments(
            by_motif,
            float(policy.get("motif_adjustment_step", 0.08)),
        ),
        "target_type_adjustments": _adjustments(
            by_target_type,
            float(policy.get("target_type_adjustment_step", 0.06)),
        ),
    }


def build_adaptive_policy_state(
    *,
    candidate_plan: Mapping[str, Any],
    feedback_records: list[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    calibration_update: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Build deterministic next-round acquisition priorities and suggestions."""

    candidates = _candidate_by_id(candidate_plan)
    suggestions: list[dict[str, Any]] = []
    inconclusive: list[dict[str, Any]] = []
    for record in sorted(
        feedback_records,
        key=lambda row: (
            _rank_value(row.get("synthetic_rank")),
            str(row.get("candidate_id")),
        ),
    ):
        candidate_id = str(record.get("candidate_id"))
        candidate = _as_mapping(candidates.get(candidate_id))
        label = str(record.get("synthetic_label", "unlabeled"))
        if label in {"useful", "false_rejection"}:
            suggestion = "promote"
            validity = "C2_synthetic_feedback_useful"
            reason = "prioritize_useful_synthetic_feedback"
        elif label in FALSE_PROMOTION_LABELS:
            suggestion = "reject"
            validity = "C3_synthetic_feedback_false_promotion"
            reason = "avoid_false_promotion_pattern"
        else:
            suggestion = "hold"
            validity = "C4_high_fidelity_required"
            reason = "hold_inconclusive_synthetic_feedback"
            inconclusive.append(
                {
                    "candidate_id": candidate_id,
                    "reason_codes": ["synthetic_label_inconclusive"],
                }
            )
        suggestions.append(
            {
                "candidate_id": candidate_id,
                "suggestion": suggestion,
                "candidate_validity_level": validity,
                "priority_score": round(
                    _numeric_value(record.get("expected_improvement"))
                    - _numeric_value(record.get("l1_risk")),
                    6,
                ),
                "motif_id": candidate.get("motif_id"),
                "template_id": candidate.get("template_id"),
                "target_type": candidate.get("target_type"),
                "reason_codes": [reason],
            }
        )

    priority_rules = [
        {
            "rule_id": "prefer_synthetic_useful_with_low_l1_risk",
            "description": "Prioritize useful or false-rejected candidates with lower L1 risk.",
        },
        {
            "rule_id": "downrank_false_promotion_templates",
            "description": "Increase risk for templates and motifs associated with synthetic false promotions.",
        },
        {
            "rule_id": "hold_inconclusive_until_real_evidence_budget",
            "description": "Keep inconclusive labels out of final claims and require future high-fidelity evidence.",
        },
    ]

    return {
        "policy_version": str(config.get("policy_version", POLICY_VERSION)),
        "next_round_priority_rules": priority_rules,
        "next_round_candidate_suggestions": suggestions,
        "uncertainty_or_inconclusive_cases": inconclusive,
        "policy_update_reason_codes": [
            "synthetic_replay_feedback_consumed",
            "false_promotion_budget_accounted",
            "claim_boundary_preserved",
        ],
        "calibration_update_digest": {
            "risk_threshold_update_count": len(_as_mapping(calibration_update.get("risk_threshold_updates"))),
            "template_adjustment_count": len(_as_mapping(calibration_update.get("template_adjustments"))),
            "motif_adjustment_count": len(_as_mapping(calibration_update.get("motif_adjustments"))),
            "target_type_adjustment_count": len(_as_mapping(calibration_update.get("target_type_adjustments"))),
        },
    }


def evaluate_stopping_conditions(
    *,
    metrics: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate closed-loop synthetic replay stopping conditions."""

    stopping = _as_mapping(config.get("stopping_conditions"))
    current_round = int(stopping.get("current_round", 0))
    max_rounds = int(stopping.get("max_rounds", 0))
    label_budget = int(stopping.get("synthetic_label_budget", 0))
    labeled_count = int(_as_mapping(metrics.get("candidate_label_coverage")).get("labeled_candidate_count", 0))
    no_new_rounds = int(stopping.get("no_new_useful_candidate_rounds", 0))
    no_new_limit = int(stopping.get("no_new_useful_candidate_rounds_limit", 0))
    false_rate = float(metrics.get("false_promotion_rate", 1.0))
    false_target = float(stopping.get("false_promotion_rate_target", 0.0))
    expected_improvement = float(metrics.get("expected_improvement_max", 0.0))
    expected_threshold = float(stopping.get("expected_improvement_threshold", 0.0))
    top_k_useful = int(metrics.get("top_k_useful_count", 0))
    top_k_target = int(stopping.get("top_k_useful_target", 0))

    conditions = {
        "max_rounds_reached": current_round >= max_rounds,
        "high_fidelity_synthetic_label_budget_exhausted": labeled_count >= label_budget,
        "no_new_useful_candidate_for_n_rounds": no_new_rounds >= no_new_limit,
        "false_promotion_rate_below_target_threshold": false_rate <= false_target,
        "expected_improvement_below_threshold": expected_improvement <= expected_threshold,
        "top_k_useful_count_target_reached": top_k_useful >= top_k_target,
    }
    rows = [
        {
            "condition": name,
            "satisfied": bool(conditions[name]),
        }
        for name in STOPPING_CONDITIONS
    ]
    stop_reasons = [row["condition"] for row in rows if row["satisfied"]]
    hard_stop_reasons = {
        "max_rounds_reached",
        "high_fidelity_synthetic_label_budget_exhausted",
        "no_new_useful_candidate_for_n_rounds",
        "top_k_useful_count_target_reached",
    }
    stop = any(reason in hard_stop_reasons for reason in stop_reasons)
    return {
        "decision_basis": "synthetic_replay_stop_decision",
        "stop_decision": "stop" if stop else "continue",
        "stop_reasons": stop_reasons,
        "conditions": rows,
    }
