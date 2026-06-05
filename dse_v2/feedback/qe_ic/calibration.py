#!/usr/bin/env python3
"""QE-IC Layer-6 synthetic feedback calibration runner."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from dse_v2.feedback.qe_ic.adaptive_policy import (
    build_adaptive_policy_state,
    build_calibration_update,
    evaluate_stopping_conditions,
)
from dse_v2.feedback.qe_ic.schema import (
    CLAIM_BOUNDARY,
    FALSE_PROMOTION_LABELS,
    LAYER_NAME,
    POLICY_VERSION,
    PRODUCER,
    QE_IC_FEEDBACK_CALIBRATION_SCHEMA_VERSION,
    SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT,
    SOURCE_LAYER5A_L1_RESULTS_ARTIFACT,
    WASTED_BUDGET_LABELS,
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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


def _l1_result_by_candidate(l1_results: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(result.get("candidate_id")): result
        for result in _as_list(l1_results.get("results"))
        if isinstance(result, Mapping)
    }


def _labels_by_candidate(labels: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(label.get("candidate_id")): label
        for label in _as_list(labels.get("labels"))
        if isinstance(label, Mapping)
    }


def _extract_l1_features(result: Mapping[str, Any]) -> dict[str, Any]:
    estimate = _as_mapping(result.get("estimate"))
    risk = _as_mapping(result.get("risk"))
    suggestion = _as_mapping(result.get("next_fidelity_suggestion"))
    return {
        "l1_estimated_net_gain_ratio": estimate.get("estimated_net_gain_ratio"),
        "l1_estimated_speedup_vs_gpu_baseline": estimate.get("estimated_speedup_vs_gpu_baseline"),
        "l1_estimated_model_confidence": estimate.get("estimated_model_confidence"),
        "l1_risk": risk.get("overall_l1_risk"),
        "l1_resource_risk": risk.get("resource_risk"),
        "l1_transfer_risk": risk.get("transfer_risk"),
        "l1_next_fidelity_suggestion": suggestion.get("suggestion"),
    }


def _build_feedback_records(
    *,
    candidate_plan: Mapping[str, Any],
    l1_results: Mapping[str, Any],
    labels: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates = _candidate_by_id(candidate_plan)
    decisions = _decision_by_candidate(candidate_plan)
    l1_by_candidate = _l1_result_by_candidate(l1_results)
    labels_by_candidate = _labels_by_candidate(labels)
    records: list[dict[str, Any]] = []
    for candidate_id in sorted(candidates):
        candidate = candidates[candidate_id]
        decision = _as_mapping(decisions.get(candidate_id))
        label = _as_mapping(labels_by_candidate.get(candidate_id))
        l1_result = _as_mapping(l1_by_candidate.get(candidate_id))
        label_value = str(label.get("label", "unlabeled"))
        promoted = decision.get("decision") == "promote"
        l1_features = _extract_l1_features(l1_result) if l1_result else {
            "l1_estimated_net_gain_ratio": None,
            "l1_estimated_speedup_vs_gpu_baseline": None,
            "l1_estimated_model_confidence": None,
            "l1_risk": None,
            "l1_resource_risk": None,
            "l1_transfer_risk": None,
            "l1_next_fidelity_suggestion": None,
        }
        mismatch = False
        if label:
            if promoted and label_value in FALSE_PROMOTION_LABELS:
                mismatch = True
            elif decision.get("decision") in {"hold", "reject"} and label_value == "false_rejection":
                mismatch = True
            elif promoted and label_value == "inconclusive":
                mismatch = True
        records.append(
            {
                "candidate_id": candidate_id,
                "workload_family_id": candidate.get("workload_family_id"),
                "motif_id": candidate.get("motif_id"),
                "template_id": candidate.get("template_id"),
                "target_type": candidate.get("target_type"),
                "layer4_decision": decision.get("decision"),
                "layer4_promotion_score": decision.get("promotion_score"),
                "layer4_promotion_priority": decision.get("promotion_priority"),
                "has_l1_result": bool(l1_result),
                **l1_features,
                "synthetic_label": label_value,
                "synthetic_rank": label.get("synthetic_rank"),
                "label_confidence": label.get("label_confidence"),
                "expected_improvement": label.get("expected_improvement"),
                "feedback_class": (
                    "useful_promotion"
                    if promoted and label_value == "useful"
                    else "false_promotion"
                    if promoted and label_value in FALSE_PROMOTION_LABELS
                    else "wasted_or_inconclusive_promotion"
                    if promoted and label_value in WASTED_BUDGET_LABELS
                    else "false_rejection"
                    if decision.get("decision") in {"hold", "reject"} and label_value == "false_rejection"
                    else "unlabeled"
                    if not label
                    else "consistent_nonpromotion_or_hold"
                ),
                "ranking_mismatch": mismatch,
                "comparison_reason_codes": (
                    ["synthetic_false_promotion_detected"]
                    if promoted and label_value in FALSE_PROMOTION_LABELS
                    else ["synthetic_false_rejection_detected"]
                    if decision.get("decision") in {"hold", "reject"} and label_value == "false_rejection"
                    else ["synthetic_label_inconclusive"]
                    if label_value == "inconclusive"
                    else ["synthetic_feedback_consistent"]
                    if label
                    else ["no_synthetic_label"]
                ),
            }
        )
    return records


def _compute_metrics(
    *,
    candidate_plan: Mapping[str, Any],
    labels: Mapping[str, Any],
    feedback_records: list[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    decisions = _decision_by_candidate(candidate_plan)
    labels_by_candidate = _labels_by_candidate(labels)
    promoted_ids = {
        candidate_id
        for candidate_id, decision in decisions.items()
        if decision.get("decision") == "promote"
    }
    promoted_labeled_ids = promoted_ids & set(labels_by_candidate)
    useful_promoted_ids = {
        candidate_id
        for candidate_id in promoted_labeled_ids
        if labels_by_candidate[candidate_id].get("label") == "useful"
    }
    false_promoted_ids = {
        candidate_id
        for candidate_id in promoted_labeled_ids
        if labels_by_candidate[candidate_id].get("label") in FALSE_PROMOTION_LABELS
    }
    wasted_ids = {
        candidate_id
        for candidate_id in promoted_labeled_ids
        if labels_by_candidate[candidate_id].get("label") in WASTED_BUDGET_LABELS
    }
    false_rejected_ids = {
        candidate_id
        for candidate_id, label in labels_by_candidate.items()
        if label.get("label") == "false_rejection"
        and _as_mapping(decisions.get(candidate_id)).get("decision") in {"hold", "reject"}
    }
    useful_candidate_count = sum(
        1
        for label in labels_by_candidate.values()
        if label.get("label") == "useful"
    )
    rejected_before_high_fidelity_count = sum(
        1
        for decision in decisions.values()
        if decision.get("decision") in {"hold", "reject"}
    )
    hold_count = sum(1 for decision in decisions.values() if decision.get("decision") == "hold")
    ranking_mismatch_count = sum(1 for row in feedback_records if row.get("ranking_mismatch"))
    top_k = int(config.get("top_k", 5))
    top_k_rows = sorted(
        labels_by_candidate.values(),
        key=lambda row: int(row.get("synthetic_rank", 10**9)),
    )[:top_k]
    top_k_useful_count = sum(1 for row in top_k_rows if row.get("label") == "useful")
    label_counter = Counter(str(label.get("label")) for label in labels_by_candidate.values())
    expected_improvements = [
        float(label.get("expected_improvement", 0.0))
        for label in labels_by_candidate.values()
        if isinstance(label.get("expected_improvement"), int | float)
        and not isinstance(label.get("expected_improvement"), bool)
    ]
    l1_gain_error_values = []
    for record in feedback_records:
        if record.get("synthetic_label") == "unlabeled":
            continue
        l1_gain = record.get("l1_estimated_net_gain_ratio")
        expected = record.get("expected_improvement")
        if (
            isinstance(l1_gain, int | float)
            and not isinstance(l1_gain, bool)
            and isinstance(expected, int | float)
            and not isinstance(expected, bool)
        ):
            l1_gain_error_values.append(abs(float(l1_gain) - float(expected)))
    calibration_error_summary = {
        "count": len(l1_gain_error_values),
        "mean_absolute_expected_improvement_error": (
            sum(l1_gain_error_values) / len(l1_gain_error_values)
            if l1_gain_error_values
            else 0.0
        ),
        "max_absolute_expected_improvement_error": max(l1_gain_error_values) if l1_gain_error_values else 0.0,
    }
    promoted_labeled_count = len(promoted_labeled_ids)
    return {
        "promotion_precision": (
            len(useful_promoted_ids) / promoted_labeled_count
            if promoted_labeled_count
            else 0.0
        ),
        "false_promotion_rate": (
            len(false_promoted_ids) / promoted_labeled_count
            if promoted_labeled_count
            else 0.0
        ),
        "false_promotion_count": len(false_promoted_ids),
        "resource_invalid_count": label_counter.get("resource_invalid", 0),
        "overhead_invalid_count": label_counter.get("overhead_invalid", 0),
        "false_rejection_count": len(false_rejected_ids),
        "wasted_budget_count": len(wasted_ids),
        "wasted_budget_ratio": (
            len(wasted_ids) / promoted_labeled_count
            if promoted_labeled_count
            else 0.0
        ),
        "useful_candidate_count": useful_candidate_count,
        "rejected_before_high_fidelity_count": rejected_before_high_fidelity_count,
        "hold_count": hold_count,
        "ranking_mismatch_count": ranking_mismatch_count,
        "ranking_error": ranking_mismatch_count,
        "top_k_useful_count": top_k_useful_count,
        "calibration_error_summary": calibration_error_summary,
        "candidate_label_coverage": {
            "known_candidate_count": len(decisions),
            "labeled_candidate_count": len(labels_by_candidate),
            "unlabeled_candidate_count": max(len(decisions) - len(labels_by_candidate), 0),
            "promoted_labeled_candidate_count": promoted_labeled_count,
        },
        "expected_improvement_max": max(expected_improvements) if expected_improvements else 0.0,
        "synthetic_label_counts": dict(sorted(label_counter.items())),
    }


def run_qe_ic_feedback_calibration(
    candidate_plan: Mapping[str, Any],
    l1_results: Mapping[str, Any],
    synthetic_high_fidelity_labels: Mapping[str, Any],
    feedback_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Run Layer-6 synthetic feedback calibration and adaptive policy update."""

    feedback_records = _build_feedback_records(
        candidate_plan=candidate_plan,
        l1_results=l1_results,
        labels=synthetic_high_fidelity_labels,
    )
    metrics = _compute_metrics(
        candidate_plan=candidate_plan,
        labels=synthetic_high_fidelity_labels,
        feedback_records=feedback_records,
        config=feedback_config,
    )
    calibration_update = build_calibration_update(
        candidate_plan=candidate_plan,
        feedback_records=feedback_records,
        metrics=metrics,
        config=feedback_config,
    )
    adaptive_policy_state = build_adaptive_policy_state(
        candidate_plan=candidate_plan,
        feedback_records=feedback_records,
        metrics=metrics,
        calibration_update=calibration_update,
        config=feedback_config,
    )
    stopping = evaluate_stopping_conditions(metrics=metrics, config=feedback_config)

    return {
        "schema_version": QE_IC_FEEDBACK_CALIBRATION_SCHEMA_VERSION,
        "layer": LAYER_NAME,
        "producer": PRODUCER,
        "source_layer4_candidate_plan_artifact": SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT,
        "source_layer5a_l1_results_artifact": SOURCE_LAYER5A_L1_RESULTS_ARTIFACT,
        "source_layer4_candidate_plan": dict(candidate_plan),
        "source_layer5a_l1_results": dict(l1_results),
        "feedback_config": dict(feedback_config),
        "synthetic_high_fidelity_labels": list(_as_list(synthetic_high_fidelity_labels.get("labels"))),
        "candidate_feedback_records": feedback_records,
        "metrics": metrics,
        "calibration_update": calibration_update,
        "adaptive_policy_state": adaptive_policy_state,
        "stopping_condition_evaluation": stopping,
        "claim_boundary": CLAIM_BOUNDARY,
    }
