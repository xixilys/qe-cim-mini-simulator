#!/usr/bin/env python3
"""Domain-neutral validation gates for multi-fidelity DSE method results."""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Sequence


def build_multifidelity_algorithm_validation_report(
    *,
    proposed_policy_id: str,
    policy_results: Sequence[Mapping[str, Any]],
    independent_feedback: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Judge whether the proposed search policy is validated by current data.

    This gate is intentionally conservative.  It does not try to make a weak
    algorithm result look good; it records when a proposed policy loses to a
    baseline or when independent feedback contradicts the cheap-model ranking.
    """

    rows = [_normalized_policy_result(row) for row in policy_results if isinstance(row, Mapping)]
    proposed_id = str(proposed_policy_id)
    proposed = next((row for row in rows if row["policy_id"] == proposed_id), {})
    best_by_edp = _best_policy(rows, metric="final_best_edp")
    best_by_rank = _best_policy(rows, metric="final_oracle_rank")
    feedback_summary = _independent_feedback_summary(independent_feedback or {})
    blockers: list[str] = []

    if not proposed:
        blockers.append("missing_proposed_policy_result")
    else:
        proposed_edp = _finite_float(proposed.get("final_best_edp"), default=float("inf"))
        proposed_rank = _finite_float(proposed.get("final_oracle_rank"), default=float("inf"))
        for row in rows:
            policy_id = str(row.get("policy_id", ""))
            if not policy_id or policy_id == proposed_id:
                continue
            baseline_edp = _finite_float(row.get("final_best_edp"), default=float("inf"))
            baseline_rank = _finite_float(row.get("final_oracle_rank"), default=float("inf"))
            if baseline_edp < proposed_edp:
                blockers.append(f"proposed_policy_loses_edp_to_baseline:{policy_id}")
            if baseline_rank < proposed_rank:
                blockers.append(f"proposed_policy_loses_rank_to_baseline:{policy_id}")
        if proposed.get("top_k_hit") is False:
            blockers.append("proposed_policy_misses_top_k")

    rank_correlation = feedback_summary.get("rank_correlation")
    if rank_correlation is not None and _finite_float(rank_correlation, default=0.0) < 0.0:
        blockers.append("negative_independent_feedback_rank_correlation")
    if feedback_summary.get("status") == "insufficient":
        blockers.append("insufficient_independent_feedback")

    blockers = _dedupe_keep_order(blockers)
    if any(blocker.startswith("proposed_policy_loses_") for blocker in blockers) or (
        "negative_independent_feedback_rank_correlation" in blockers
    ):
        status = "algorithm_not_validated"
        next_action = "recalibrate_models_and_run_exploration_fallback"
    elif blockers:
        status = "algorithm_validation_incomplete"
        next_action = "collect_more_independent_feedback"
    else:
        status = "algorithm_validated_for_model_evaluation"
        next_action = "promote_selected_candidates_to_independent_fidelity"

    return {
        "schema_version": "dse.multifidelity_algorithm_validation.v1",
        "status": status,
        "proposed_policy_id": proposed_id,
        "proposed_policy": proposed,
        "best_policy_by_edp": best_by_edp,
        "best_policy_by_rank": best_by_rank,
        "policy_count": len(rows),
        "policies": rows,
        "independent_feedback": feedback_summary,
        "blockers": blockers,
        "recommended_next_action": next_action,
        "validation_boundary": "method_quality_gate_not_hardware_evidence",
    }


def build_validation_gated_search_control_report(
    *,
    validation_report: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    budget: int,
) -> Dict[str, Any]:
    """Choose the next search-control mode from method-validation status.

    When validation contradicts the proposed policy, the next useful action is
    exploration/calibration sampling rather than more nominal acquisition.
    """

    status = str(validation_report.get("status", ""))
    next_action = str(validation_report.get("recommended_next_action", ""))
    blockers = [str(item) for item in validation_report.get("blockers", []) or []]
    if status != "algorithm_not_validated":
        return {
            "schema_version": "dse.multifidelity_search_control.v1",
            "mode": "nominal_policy",
            "control_reason": status or "validation_status_missing",
            "recommended_next_action": next_action or "continue_nominal_policy",
            "budget": max(0, int(budget)),
            "selected_candidate_ids": [],
            "selection": [],
            "validation_blockers": blockers,
            "control_boundary": "search_control_policy_not_hardware_evidence",
        }

    selected = _exploration_fallback_selection(candidates, budget=max(0, int(budget)))
    return {
        "schema_version": "dse.multifidelity_search_control.v1",
        "mode": "exploration_fallback",
        "control_reason": "algorithm_not_validated",
        "recommended_next_action": next_action or "recalibrate_models_and_run_exploration_fallback",
        "budget": max(0, int(budget)),
        "selected_candidate_ids": [str(row.get("candidate_id", "")) for row in selected],
        "selection": selected,
        "validation_blockers": blockers,
        "control_boundary": "search_control_policy_not_hardware_evidence",
    }


def build_validation_gated_next_evaluation_queue(
    *,
    search_control: Mapping[str, Any],
    nominal_candidates: Sequence[Mapping[str, Any]],
    budget: int,
    next_fidelity: str,
) -> Dict[str, Any]:
    """Materialize the next evaluation queue implied by validation-gated control.

    The queue is a Step2 search-control artifact: it decides what should be
    sampled next, but it does not authorize execution or make tool-specific
    evidence claims.
    """

    mode = str(search_control.get("mode", "nominal_policy") or "nominal_policy")
    selected_limit = max(0, int(budget))
    candidate_by_id = {
        str(row.get("candidate_id", "")): dict(row)
        for row in nominal_candidates
        if isinstance(row, Mapping) and str(row.get("candidate_id", ""))
    }
    if mode == "exploration_fallback":
        candidate_ids = [
            str(candidate_id)
            for candidate_id in search_control.get("selected_candidate_ids", []) or []
            if str(candidate_id)
        ]
        selection_by_id = {
            str(row.get("candidate_id", "")): dict(row)
            for row in search_control.get("selection", []) or []
            if isinstance(row, Mapping) and str(row.get("candidate_id", ""))
        }
        queue = [
            _next_evaluation_queue_row(
                candidate_by_id.get(candidate_id, {"candidate_id": candidate_id}),
                selected_by_control=selection_by_id.get(candidate_id, {}),
                mode=mode,
                next_fidelity=next_fidelity,
                order=index + 1,
            )
            for index, candidate_id in enumerate(candidate_ids[:selected_limit])
        ]
    else:
        queue = [
            _next_evaluation_queue_row(
                row,
                selected_by_control={},
                mode=mode,
                next_fidelity=next_fidelity,
                order=index + 1,
            )
            for index, row in enumerate(
                [
                    row for row in nominal_candidates
                    if isinstance(row, Mapping) and str(row.get("candidate_id", ""))
                ][:selected_limit]
            )
        ]
    return {
        "schema_version": "dse.multifidelity_next_evaluation_queue.v1",
        "mode": mode,
        "control_reason": str(search_control.get("control_reason", "")),
        "recommended_next_action": str(search_control.get("recommended_next_action", "")),
        "budget": selected_limit,
        "next_fidelity": str(next_fidelity),
        "selected_candidate_ids": [str(row.get("candidate_id", "")) for row in queue],
        "queue": queue,
        "validation_blockers": [str(item) for item in search_control.get("validation_blockers", []) or []],
        "algorithm_contract": {
            "domain_neutral": True,
            "validation_controls_next_iteration": True,
            "selection_scope": "next_iteration_candidate_evaluation_queue",
            "execution_allowed": False,
            "evidence_role": "feedback_calibration_not_search_objective",
        },
        "queue_boundary": "step2_search_control_queue_not_step3_execution_or_hardware_evidence",
    }


def _normalized_policy_result(row: Mapping[str, Any]) -> Dict[str, Any]:
    final = _final_budget_point(row)
    payload = {
        "policy_id": str(row.get("policy_id", "")),
        "final_best_edp": row.get("final_best_edp", final.get("best_tlm_edp", final.get("best_tlm_edp_mean"))),
        "final_oracle_rank": row.get(
            "final_oracle_rank",
            final.get("oracle_rank_of_best", final.get("oracle_rank_of_best_mean")),
        ),
        "top_k_hit": row.get("top_k_hit", final.get("top_k_hit")),
    }
    if final:
        payload["final_budget"] = int(final.get("budget", row.get("final_budget", 0)) or 0)
    elif row.get("final_budget") is not None:
        payload["final_budget"] = int(row.get("final_budget", 0) or 0)
    return payload


def _next_evaluation_queue_row(
    candidate: Mapping[str, Any],
    *,
    selected_by_control: Mapping[str, Any],
    mode: str,
    next_fidelity: str,
    order: int,
) -> Dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id", ""))
    reason = str(
        selected_by_control.get(
            "selection_reason",
            "nominal_policy_next_iteration" if mode != "exploration_fallback" else "calibration_exploration_after_validation_failure",
        )
    )
    row = {
        "candidate_id": candidate_id,
        "design_key": str(candidate.get("design_key", selected_by_control.get("design_key", ""))),
        "queue_order": int(order),
        "queue_mode": mode,
        "queue_reason": reason,
        "recommended_next_fidelity": str(next_fidelity),
        "execution_allowed": False,
        "not_a_step3_queue": True,
    }
    for key in ("objectives", "constraints", "risk_axes", "metadata"):
        if isinstance(candidate.get(key), Mapping):
            row[key] = dict(candidate.get(key, {}))
    if "fallback_score" in selected_by_control:
        row["control_score"] = selected_by_control.get("fallback_score")
    if isinstance(selected_by_control.get("fallback_score_components"), Mapping):
        row["control_score_components"] = dict(selected_by_control.get("fallback_score_components", {}))
    return row


def _exploration_fallback_selection(
    candidates: Sequence[Mapping[str, Any]],
    *,
    budget: int,
) -> list[Dict[str, Any]]:
    selected: list[Dict[str, Any]] = []
    selected_design_keys: set[str] = set()
    remaining = [row for row in candidates if isinstance(row, Mapping)]
    for _ in range(max(0, int(budget))):
        scored = [
            _fallback_candidate_row(row, selected_design_keys=selected_design_keys)
            for row in remaining
        ]
        scored = [row for row in scored if row["candidate_id"]]
        if not scored:
            break
        scored.sort(key=lambda row: (-float(row["fallback_score"]), row["candidate_id"]))
        chosen = scored[0]
        selected.append(chosen)
        if chosen.get("design_key"):
            selected_design_keys.add(str(chosen["design_key"]))
        chosen_id = str(chosen["candidate_id"])
        remaining = [
            row for row in remaining
            if str(row.get("candidate_id", "")) != chosen_id
        ]
    return selected


def _fallback_candidate_row(
    candidate: Mapping[str, Any],
    *,
    selected_design_keys: set[str],
) -> Dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id", ""))
    design_key = str(candidate.get("design_key", ""))
    uncertainty = _clamp(_finite_float(candidate.get("uncertainty"), default=0.0), 0.0, 1.0)
    risk_axes = candidate.get("risk_axes", {}) if isinstance(candidate.get("risk_axes"), Mapping) else {}
    risk_values = [
        _clamp(_finite_float(value, default=0.0), 0.0, 1.0)
        for value in risk_axes.values()
    ]
    risk_coverage = max(risk_values) if risk_values else 0.0
    diversity = 0.0 if design_key and design_key in selected_design_keys else 1.0
    cost = max(1.0e-9, _finite_float(candidate.get("evaluation_cost"), default=1.0))
    score = (
        0.60 * uncertainty
        + 0.30 * risk_coverage
        + 0.10 * diversity
        - 0.03 * max(0.0, cost - 1.0)
    )
    return {
        "candidate_id": candidate_id,
        "design_key": design_key,
        "fallback_score": round(score, 9),
        "fallback_score_components": {
            "uncertainty": round(uncertainty, 9),
            "risk_coverage": round(risk_coverage, 9),
            "design_diversity": round(diversity, 9),
            "evaluation_cost": round(cost, 9),
        },
        "selection_reason": "calibration_exploration_after_validation_failure",
    }


def _final_budget_point(row: Mapping[str, Any]) -> Mapping[str, Any]:
    curve = row.get("budget_curve", row.get("points", []))
    if isinstance(curve, list) and curve:
        final = curve[-1]
        if isinstance(final, Mapping):
            return final
    return {}


def _best_policy(rows: Sequence[Mapping[str, Any]], *, metric: str) -> Dict[str, Any]:
    finite_rows = [
        (index, row) for index, row in enumerate(rows)
        if math.isfinite(_finite_float(row.get(metric), default=float("inf")))
    ]
    if not finite_rows:
        return {}
    return dict(
        min(
            finite_rows,
            key=lambda item: (
                _finite_float(item[1].get(metric), default=float("inf")),
                item[0],
            ),
        )[1]
    )


def _independent_feedback_summary(feedback: Mapping[str, Any]) -> Dict[str, Any]:
    rank = feedback.get("rank_correlation", {}) if isinstance(feedback.get("rank_correlation"), Mapping) else {}
    raw_correlation = (
        rank.get("l1_estimated_edp_vs_l3_edp_spearman")
        if rank
        else feedback.get("rank_correlation")
    )
    rank_correlation = _finite_float(raw_correlation, default=float("nan"))
    status = str(rank.get("status", feedback.get("status", "")) or "")
    if not math.isfinite(rank_correlation):
        status = "insufficient"
        rendered_correlation: float | None = None
    else:
        rendered_correlation = round(rank_correlation, 9)
        if not status:
            status = "usable" if int(feedback.get("sample_count", 0) or 0) > 0 else "insufficient"
    return {
        "status": status,
        "sample_count": int(feedback.get("sample_count", feedback.get("usable_sample_count", 0)) or 0),
        "rank_correlation": rendered_correlation,
        "source": str(feedback.get("source", "independent_feedback")),
    }


def _finite_float(value: Any, *, default: float) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _dedupe_keep_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        if value in seen:
            continue
        rows.append(value)
        seen.add(value)
    return rows
