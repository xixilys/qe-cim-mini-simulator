#!/usr/bin/env python3
"""Deterministic promotion policy for QE-IC Layer-4 candidate plans."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from dse_v2.candidates.qe_ic.schema import EVALUATION_REQUEST_CLAIM_BOUNDARY


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _record_index(source_records: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(record_id): record
        for record_id, record in source_records.items()
        if isinstance(record, Mapping)
    }


def extract_promotion_features(
    candidate: Mapping[str, Any],
    source_records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Extract policy features from candidate and Layer-3 source record."""

    record = _record_index(source_records).get(str(candidate.get("source_viability_record_id")), {})
    upper_bound = record.get("upper_bound") if isinstance(record.get("upper_bound"), Mapping) else {}
    risk = record.get("risk") if isinstance(record.get("risk"), Mapping) else {}
    evidence_inputs = record.get("evidence_inputs") if isinstance(record.get("evidence_inputs"), Mapping) else {}
    viability_score = _num(record.get("viability_score"))
    estimated_net_gain_ratio = _num(upper_bound.get("estimated_net_gain_ratio"))
    risk_score = _num(risk.get("overall_risk_score"), 1.0)
    runtime_ratio = _num(upper_bound.get("runtime_ratio"), _num(evidence_inputs.get("runtime_ratio")))
    profile_quality_risk = _num(risk.get("profile_quality_risk"), 1.0)
    profile_quality = _clamp(1.0 - profile_quality_risk)
    source_decision = str(record.get("decision", candidate.get("source_viability_decision", "")))
    target_type = str(candidate.get("target_type", ""))
    motif_id = str(candidate.get("motif_id", ""))
    return {
        "source_viability_score": viability_score,
        "source_decision": source_decision,
        "estimated_net_gain_ratio": estimated_net_gain_ratio,
        "risk_score": risk_score,
        "runtime_ratio": runtime_ratio,
        "profile_quality": profile_quality,
        "profile_quality_risk": profile_quality_risk,
        "target_type": target_type,
        "motif_id": motif_id,
        "diversity_group": f"{target_type}:{motif_id}",
    }


def score_candidate(features: Mapping[str, Any], *, risk_tolerance: float) -> float:
    """Score one candidate using explicit, replaceable policy weights."""

    source_decision = str(features.get("source_decision"))
    if source_decision == "viable":
        decision_bonus = 0.12
    elif source_decision == "maybe":
        decision_bonus = 0.06
    else:
        decision_bonus = 0.0
    score = (
        0.34 * _clamp(_num(features.get("source_viability_score")))
        + 0.28 * _clamp(max(_num(features.get("estimated_net_gain_ratio")), 0.0) / 0.12)
        + 0.18 * _clamp(_num(features.get("runtime_ratio")) / 0.35)
        + 0.14 * _clamp(_num(features.get("profile_quality")))
        + decision_bonus
        - 0.30 * _clamp(_num(features.get("risk_score")))
    )
    if _num(features.get("risk_score")) > risk_tolerance:
        score -= 0.20 * _clamp((_num(features.get("risk_score")) - risk_tolerance) / max(1.0 - risk_tolerance, 1e-9))
    return round(score, 6)


def _base_reason_codes(
    *,
    candidate: Mapping[str, Any],
    features: Mapping[str, Any],
    score: float,
    risk_tolerance: float,
) -> list[str]:
    codes: set[str] = {"candidate_generated_from_viability"}
    source_decision = str(features.get("source_decision"))
    if source_decision == "viable":
        codes.add("source_decision_viable")
    elif source_decision == "maybe":
        codes.add("source_decision_maybe")
    elif source_decision == "baseline":
        codes.add("source_decision_baseline")
    elif source_decision == "reject":
        codes.add("source_decision_reject")
    if _num(features.get("source_viability_score")) >= 0.65:
        codes.add("strong_viability_score")
    elif _num(features.get("source_viability_score")) >= 0.35:
        codes.add("moderate_viability_score")
    else:
        codes.add("low_viability_score")
    if _num(features.get("estimated_net_gain_ratio")) > 0.0:
        codes.add("positive_gain_estimate")
    else:
        codes.add("weak_gain_estimate")
    if _num(features.get("runtime_ratio")) >= 0.25:
        codes.add("high_runtime_ratio")
    else:
        codes.add("low_runtime_ratio")
    if _num(features.get("profile_quality")) >= 0.75:
        codes.add("profile_quality_high")
    elif _num(features.get("profile_quality")) >= 0.50:
        codes.add("profile_quality_medium")
    else:
        codes.add("profile_quality_low")
    if _num(features.get("risk_score")) <= risk_tolerance:
        codes.add("risk_within_tolerance")
    else:
        codes.add("risk_above_tolerance")
    if score < 0.05:
        codes.add("score_below_reject_threshold")
    else:
        codes.add("score_above_promotion_threshold")
    if candidate.get("candidate_type") == "baseline":
        codes = {"baseline_reference", "source_decision_baseline", "not_next_fidelity_candidate"}
    return sorted(codes)


def _decision_payload(
    *,
    candidate: Mapping[str, Any],
    decision: str,
    score: float,
    priority: int,
    features: Mapping[str, Any],
    reason_codes: Sequence[str],
    next_fidelity: str,
    budget_account: str,
) -> dict[str, Any]:
    return {
        "promotion_decision_id": f"promotion_{candidate.get('candidate_id')}",
        "candidate_id": candidate.get("candidate_id"),
        "decision": decision,
        "current_fidelity": "L0_target_viability",
        "next_fidelity": next_fidelity,
        "promotion_priority": priority,
        "promotion_score": score,
        "budget_account": budget_account,
        "reason_codes": sorted(set(reason_codes)),
        "evidence_summary": {
            "source_viability_score": features.get("source_viability_score"),
            "source_decision": features.get("source_decision"),
            "estimated_net_gain_ratio": features.get("estimated_net_gain_ratio"),
            "risk_score": features.get("risk_score"),
            "runtime_ratio": features.get("runtime_ratio"),
            "diversity_group": features.get("diversity_group"),
        },
    }


def _ranked_candidates(
    candidates: Sequence[Mapping[str, Any]],
    source_records: Mapping[str, Mapping[str, Any]],
    *,
    risk_tolerance: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("candidate_type") == "baseline":
            continue
        features = extract_promotion_features(candidate, source_records)
        score = score_candidate(features, risk_tolerance=risk_tolerance)
        rows.append(
            {
                "candidate": candidate,
                "features": features,
                "score": score,
                "reason_codes": _base_reason_codes(
                    candidate=candidate,
                    features=features,
                    score=score,
                    risk_tolerance=risk_tolerance,
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            -float(row["score"]),
            _num(row["features"].get("risk_score")),
            -_num(row["features"].get("estimated_net_gain_ratio")),
            str(row["candidate"].get("target_type")),
            str(row["candidate"].get("motif_id")),
            str(row["candidate"].get("candidate_id")),
        )
    )
    return rows


def _select_with_diversity(
    rows: list[dict[str, Any]],
    *,
    budget: int,
    require_target_diversity: bool,
    require_motif_diversity: bool,
) -> set[str]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    used_targets: set[str] = set()
    used_motifs: set[str] = set()

    def add(row: dict[str, Any]) -> bool:
        if len(selected) >= budget:
            return False
        candidate_id = str(row["candidate"].get("candidate_id"))
        if candidate_id in selected_ids:
            return False
        selected.append(row)
        selected_ids.add(candidate_id)
        used_targets.add(str(row["candidate"].get("target_type")))
        used_motifs.add(str(row["candidate"].get("motif_id")))
        return True

    if budget <= 0:
        return selected_ids

    if require_target_diversity and budget > 1:
        for target_type in sorted({str(row["candidate"].get("target_type")) for row in rows}):
            target_rows = [row for row in rows if str(row["candidate"].get("target_type")) == target_type]
            for row in target_rows:
                if add(row):
                    break
            if len(selected) >= budget:
                return selected_ids

    if require_motif_diversity and budget > 1:
        for row in rows:
            motif_id = str(row["candidate"].get("motif_id"))
            if motif_id in used_motifs:
                continue
            add(row)
            if len(selected) >= budget:
                return selected_ids

    for row in rows:
        add(row)
        if len(selected) >= budget:
            break
    return selected_ids


def _request_id(candidate_id: str) -> str:
    digest = hashlib.sha1(candidate_id.encode("utf-8")).hexdigest()[:10]
    return f"qeic_l4_l1_cost_model_request_{digest}"


def build_evaluation_requests(
    promotion_decisions: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build planned next-fidelity requests for promoted non-baseline candidates."""

    candidate_by_id = {
        str(candidate.get("candidate_id")): candidate
        for candidate in candidates
        if isinstance(candidate, Mapping)
    }
    requests: list[dict[str, Any]] = []
    for decision in promotion_decisions:
        if not isinstance(decision, Mapping) or decision.get("decision") != "promote":
            continue
        candidate_id = str(decision.get("candidate_id"))
        candidate = candidate_by_id.get(candidate_id)
        if not candidate or candidate.get("candidate_type") == "baseline":
            continue
        requests.append(
            {
                "request_id": _request_id(candidate_id),
                "candidate_id": candidate_id,
                "requested_fidelity": "L1_cost_model",
                "status": "planned_not_executed",
                "required_inputs": [
                    "qe_ic_candidate_plan.json",
                    "qe_ic_workload_suite.json",
                    "qe_ic_motif_profile.json",
                    "qe_ic_target_viability.json",
                    "qe_ic_layer4_campaign_fixture.json",
                ],
                "claim_boundary": EVALUATION_REQUEST_CLAIM_BOUNDARY,
            }
        )
    requests.sort(key=lambda request: str(request["request_id"]))
    return requests


def promote_qe_ic_candidates(
    candidates: Sequence[Mapping[str, Any]],
    source_records: Mapping[str, Mapping[str, Any]],
    campaign_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Apply a deterministic, auditable promotion policy."""

    promotion = campaign_config.get("promotion") if isinstance(campaign_config.get("promotion"), Mapping) else {}
    budget = promotion.get("budget") if isinstance(promotion.get("budget"), Mapping) else {}
    max_requests = int(budget.get("max_l1_cost_model_requests", 0))
    risk_tolerance = _num(campaign_config.get("risk_tolerance"), 0.65)
    require_target_diversity = promotion.get("require_diversity_across_target_type") is True
    require_motif_diversity = promotion.get("require_diversity_across_motif") is True

    ranked = _ranked_candidates(candidates, source_records, risk_tolerance=risk_tolerance)
    selected_ids = _select_with_diversity(
        ranked,
        budget=max_requests,
        require_target_diversity=require_target_diversity,
        require_motif_diversity=require_motif_diversity,
    )
    row_by_id = {
        str(row["candidate"].get("candidate_id")): row
        for row in ranked
    }

    decisions: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: str(item.get("candidate_id"))):
        candidate_id = str(candidate.get("candidate_id"))
        if candidate.get("candidate_type") == "baseline":
            features = {
                "source_viability_score": 0.0,
                "source_decision": "baseline",
                "estimated_net_gain_ratio": 0.0,
                "risk_score": 0.0,
                "runtime_ratio": 0.0,
                "diversity_group": f"{candidate.get('target_type')}:{candidate.get('motif_id')}",
            }
            decisions.append(
                _decision_payload(
                    candidate=candidate,
                    decision="baseline",
                    score=0.0,
                    priority=0,
                    features=features,
                    reason_codes=["baseline_reference", "source_decision_baseline", "not_next_fidelity_candidate"],
                    next_fidelity="none",
                    budget_account="none",
                )
            )
            continue
        row = row_by_id[candidate_id]
        reason_codes = set(row["reason_codes"])
        if candidate_id in selected_ids:
            decision = "promote"
            next_fidelity = "L1_cost_model"
            budget_account = "max_l1_cost_model_requests"
            reason_codes.update({"budget_available", "planned_l1_cost_model_request"})
            if require_target_diversity:
                reason_codes.add("target_diversity_selected")
            if require_motif_diversity:
                reason_codes.add("motif_diversity_selected")
            reason_codes.add("diversity_represented")
        elif row["score"] < 0.05 or row["features"].get("source_decision") == "reject":
            decision = "reject"
            next_fidelity = "none"
            budget_account = "none"
            reason_codes.add("score_below_reject_threshold")
        else:
            decision = "hold"
            next_fidelity = "none"
            budget_account = "max_l1_cost_model_requests"
            reason_codes.add("budget_exhausted")
            if require_motif_diversity:
                reason_codes.add("duplicate_motif_deprioritized")
            if require_target_diversity:
                reason_codes.add("duplicate_target_type_deprioritized")

        priority = 0 if decision != "promote" else sorted(selected_ids).index(candidate_id) + 1
        decisions.append(
            _decision_payload(
                candidate=candidate,
                decision=decision,
                score=float(row["score"]),
                priority=priority,
                features=row["features"],
                reason_codes=sorted(reason_codes),
                next_fidelity=next_fidelity,
                budget_account=budget_account,
            )
        )

    promoted_order = {
        decision["candidate_id"]: rank
        for rank, decision in enumerate(
            sorted(
                [
                    decision
                    for decision in decisions
                    if decision["decision"] == "promote"
                ],
                key=lambda decision: (
                    -float(decision["promotion_score"]),
                    float(decision["evidence_summary"].get("risk_score", 1.0)),
                    str(decision["candidate_id"]),
                ),
            ),
            start=1,
        )
    }
    for decision in decisions:
        if decision["decision"] == "promote":
            decision["promotion_priority"] = promoted_order[str(decision["candidate_id"])]
    decisions.sort(
        key=lambda decision: (
            0 if decision["decision"] == "baseline" else 1,
            -float(decision["promotion_score"]),
            str(decision["candidate_id"]),
        )
    )
    return decisions


def evaluate_qe_ic_promotion_replay(
    promotion_decisions: Sequence[Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate synthetic replay labels without making real performance claims."""

    label_by_id = {
        str(label.get("candidate_id")): str(label.get("high_fidelity_label"))
        for label in labels
        if isinstance(label, Mapping)
    }
    promoted = [
        decision
        for decision in promotion_decisions
        if isinstance(decision, Mapping) and decision.get("decision") == "promote"
    ]
    promoted_ids = {str(decision.get("candidate_id")) for decision in promoted}
    useful_promotions = [
        candidate_id
        for candidate_id in promoted_ids
        if label_by_id.get(candidate_id) == "useful"
    ]
    false_promotions = [
        candidate_id
        for candidate_id in promoted_ids
        if label_by_id.get(candidate_id) == "false_promotion"
    ]
    avoided_false_promotions = [
        candidate_id
        for candidate_id, label in label_by_id.items()
        if label == "false_promotion" and candidate_id not in promoted_ids
    ]
    promoted_count = len(promoted_ids)
    false_count = len(false_promotions)
    return {
        "schema_version": "dse.qe_ic.synthetic_replay_validation.v1",
        "claim_boundary": (
            "Synthetic replay labels test promotion-policy behavior only. They are "
            "not QE, FPGA, GPU, or performance evidence."
        ),
        "label_count": len(label_by_id),
        "promoted_count": promoted_count,
        "useful_promotion_count": len(useful_promotions),
        "false_promotion_count": false_count,
        "avoided_false_promotion_count": len(avoided_false_promotions),
        "wasted_budget_count": false_count,
        "wasted_budget_ratio": (false_count / promoted_count) if promoted_count else 0.0,
        "promotion_precision": (len(useful_promotions) / promoted_count) if promoted_count else 0.0,
    }

