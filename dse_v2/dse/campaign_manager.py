#!/usr/bin/env python3
"""Campaign-level scheduling helpers for search feedback loops.

The helpers in this module are intentionally domain-neutral.  They consume
Step2/Step4 control-plane artifacts and decide what may be scheduled next, but
they do not run evidence and they do not let proposal-only artifacts bypass the
canonical Step3 queue.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Set

from dse_v2.contracts import CONTRACT_VERSION


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _short_id(*values: Any) -> str:
    digest = hashlib.sha256(_stable_json(values).encode("utf-8")).hexdigest()
    return digest[:16]


def _append_alias(aliases: List[str], value: Any) -> None:
    alias = str(value or "")
    if alias and alias not in aliases:
        aliases.append(alias)


def _candidate_aliases(candidate: Mapping[str, Any]) -> List[str]:
    parameters = _as_mapping(candidate.get("parameters"))
    provenance = _as_mapping(candidate.get("provenance"))
    aliases: List[str] = []
    for key in (
        "candidate_id",
        "search_policy_candidate_id",
        "mapping_candidate_id",
        "parameter_hash",
        "search_policy_parameter_hash",
        "mapping_parameter_hash",
        "top_k_entry_id",
        "queue_entry_id",
    ):
        _append_alias(aliases, candidate.get(key))
        _append_alias(aliases, parameters.get(key))
        _append_alias(aliases, provenance.get(key))
    return aliases


def _queue_entry_aliases(entry: Mapping[str, Any]) -> List[str]:
    aliases: List[str] = []
    for key in (
        "queue_entry_id",
        "candidate_id",
        "mapping_candidate_id",
        "search_policy_candidate_id",
        "parameter_hash",
        "mapping_parameter_hash",
        "search_policy_parameter_hash",
        "top_k_entry_id",
    ):
        _append_alias(aliases, entry.get(key))
    return aliases


def _existing_step3_aliases(step3_simulation_queue: Mapping[str, Any]) -> Set[str]:
    aliases: Set[str] = set()
    for entry in _as_list(step3_simulation_queue.get("entries")):
        if isinstance(entry, Mapping):
            aliases.update(_queue_entry_aliases(entry))
    return aliases


def _budget_int(policy: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = policy.get(key)
        if value in (None, "", False):
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def _candidate_parameter(candidate: Mapping[str, Any], key: str, default: str = "") -> str:
    parameters = _as_mapping(candidate.get("parameters"))
    value = candidate.get(key, parameters.get(key, default))
    return str(value or default)


def _candidate_rank(candidate: Mapping[str, Any], fallback: int) -> int:
    for key in ("search_policy_rank", "top_k_rank", "rank"):
        value = candidate.get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return fallback


def _candidate_priority(candidate: Mapping[str, Any]) -> float:
    for key in ("score", "priority_score", "step2_candidate_rank_score"):
        value = candidate.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    parameters = _as_mapping(candidate.get("parameters"))
    value = parameters.get("step2_candidate_rank_score")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _embedded_step3_queue_entry(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    for key in ("step3_queue_entry", "materialized_step3_queue_entry"):
        value = candidate.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _step2_iteration_request(
    candidate: Mapping[str, Any],
    *,
    rank: int,
    search_iteration_plan_ref: str,
) -> Dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or f"candidate-{rank}")
    mapping_candidate_id = _candidate_parameter(candidate, "mapping_candidate_id")
    architecture_id = _candidate_parameter(candidate, "architecture_id")
    return {
        "request_id": f"step2-materialize::{rank}::{_short_id(candidate_id, mapping_candidate_id, architecture_id)}",
        "requested_action": "materialize_step2_artifacts_for_step3_queue",
        "search_policy_candidate_id": candidate_id,
        "search_policy_rank": rank,
        "architecture_id": architecture_id,
        "mapping_candidate_id": mapping_candidate_id,
        "mapping_parameter_hash": _candidate_parameter(candidate, "mapping_parameter_hash"),
        "search_policy_parameter_hash": str(candidate.get("parameter_hash") or ""),
        "priority_score": _candidate_priority(candidate),
        "source_artifact": search_iteration_plan_ref,
        "required_materialized_artifacts": [
            "design_point.json",
            "mapping_selected_record.json",
            "mapping_promotion_decision.json",
            "step3_simulation_queue.json",
        ],
        "materialization_status": "requested_pending_step2_writer",
        "not_a_step3_queue_entry": True,
        "execution_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
    }


def _normalize_materialized_step3_entry(
    candidate: Mapping[str, Any],
    entry: Mapping[str, Any],
    *,
    rank: int,
    search_iteration_plan_ref: str,
) -> Dict[str, Any]:
    payload = dict(entry)
    search_policy_candidate_id = str(candidate.get("candidate_id") or payload.get("search_policy_candidate_id") or "")
    mapping_candidate_id = _candidate_parameter(candidate, "mapping_candidate_id", str(payload.get("mapping_candidate_id") or ""))
    architecture_id = _candidate_parameter(candidate, "architecture_id", str(payload.get("architecture_id") or ""))
    payload.setdefault("queue_entry_id", f"campaign-search::{rank}::{_short_id(search_policy_candidate_id, mapping_candidate_id)}")
    payload.setdefault("candidate_id", f"{architecture_id}::{mapping_candidate_id}" if architecture_id and mapping_candidate_id else search_policy_candidate_id)
    payload.setdefault("search_policy_candidate_id", search_policy_candidate_id)
    payload.setdefault("mapping_candidate_id", mapping_candidate_id)
    payload.setdefault("architecture_id", architecture_id)
    payload.setdefault("priority_score", _candidate_priority(candidate))
    payload.setdefault("queue_state", "scheduled_for_simulation")
    payload.setdefault("promoted_for_simulation", True)
    payload.setdefault("admission_source", "campaign_search_admission_plan.json")
    payload.setdefault("source_artifact", search_iteration_plan_ref)
    payload.setdefault("required_step3_artifacts", [
        "simulation_request.json",
        "simulation_result.json",
        "verdict.json",
        "phase_breakdown.csv",
    ])
    payload["execution_allowed"] = False
    payload["trusted_final_claim"] = False
    payload["release_completion_eligible"] = False
    return payload


def build_campaign_search_admission_plan(
    *,
    search_iteration_plan: Mapping[str, Any],
    campaign_evaluation_plan: Optional[Mapping[str, Any]] = None,
    step3_simulation_queue: Optional[Mapping[str, Any]] = None,
    budget_policy: Optional[Mapping[str, Any]] = None,
    refs: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Build the Campaign Manager handoff after Step4 search feedback.

    The output consumes `search_iteration_plan.json` and decides what must
    happen before any wider evidence run.  By default it emits only deferred
    candidate records.  With an explicit budget it can request a Step2
    materialization pass; it only emits actual Step3 queue entries when the
    candidate already carries a materialized queue entry payload.
    """

    campaign_plan = _as_mapping(campaign_evaluation_plan)
    queue = _as_mapping(step3_simulation_queue)
    refs_payload = {
        "search_iteration_plan": "search_iteration_plan.json",
        "campaign_evaluation_plan": "campaign_evaluation_plan.json",
        "step3_simulation_queue": "step2/step3_simulation_queue.json",
        **dict(refs or {}),
    }
    combined_budget = {}
    combined_budget.update(_as_mapping(campaign_plan.get("budget_policy")))
    combined_budget.update(dict(budget_policy or {}))

    requested_budget = _budget_int(
        combined_budget,
        "next_step3_queue_entry_budget",
        "top_k_admission_budget",
        "search_feedback_admission_budget",
    )
    widening_requested = bool(
        combined_budget.get("top_k_widening_requested")
        or combined_budget.get("search_feedback_widening_requested")
        or requested_budget > 0
    )
    widening_allowed = bool(
        combined_budget.get("top_k_widening_allowed")
        or combined_budget.get("search_feedback_widening_allowed")
        or combined_budget.get("next_step3_queue_entry_budget_allowed")
    ) and widening_requested
    materialization_allowed = widening_allowed and requested_budget > 0

    existing_aliases = _existing_step3_aliases(queue)
    ranked_candidates = [
        (index, dict(candidate))
        for index, candidate in enumerate(_as_list(search_iteration_plan.get("next_candidates")), start=1)
        if isinstance(candidate, Mapping)
    ]
    ranked_candidates.sort(key=lambda item: _candidate_rank(item[1], item[0]))
    next_candidates = [candidate for _, candidate in ranked_candidates]

    step2_iteration_requests: List[Dict[str, Any]] = []
    materialized_entries: List[Dict[str, Any]] = []
    deferred_candidates: List[Dict[str, Any]] = []
    already_materialized_count = 0
    authorized_count = 0

    for fallback_rank, candidate in ranked_candidates:
        rank = _candidate_rank(candidate, fallback_rank)
        aliases = set(_candidate_aliases(candidate))
        already_materialized = bool(aliases & existing_aliases)
        eligible = bool(candidate.get("simulation_eligible", candidate.get("step3_evaluable", False)))
        if already_materialized:
            already_materialized_count += 1
            deferred_candidates.append({
                "search_policy_candidate_id": str(candidate.get("candidate_id") or ""),
                "search_policy_rank": rank,
                "status": "already_materialized_in_step3_queue",
                "execution_allowed": False,
                "reason": "existing step3_simulation_queue already owns this candidate alias",
                "not_a_step3_queue_entry": True,
            })
            continue
        if not eligible:
            deferred_candidates.append({
                "search_policy_candidate_id": str(candidate.get("candidate_id") or ""),
                "search_policy_rank": rank,
                "status": "deferred_not_simulation_eligible",
                "execution_allowed": False,
                "reason": "candidate is not Step3-evaluable in the search iteration plan",
                "not_a_step3_queue_entry": True,
            })
            continue
        if not materialization_allowed or authorized_count >= requested_budget:
            deferred_candidates.append({
                "search_policy_candidate_id": str(candidate.get("candidate_id") or ""),
                "search_policy_rank": rank,
                "status": "deferred_budget_not_materialized",
                "execution_allowed": False,
                "budget_widening_requested": widening_requested,
                "budget_widening_allowed": widening_allowed,
                "not_a_step3_queue_entry": True,
            })
            continue

        authorized_count += 1
        embedded_entry = _embedded_step3_queue_entry(candidate)
        if embedded_entry:
            materialized_entries.append(_normalize_materialized_step3_entry(
                candidate,
                embedded_entry,
                rank=rank,
                search_iteration_plan_ref=refs_payload["search_iteration_plan"],
            ))
        else:
            step2_iteration_requests.append(_step2_iteration_request(
                candidate,
                rank=rank,
                search_iteration_plan_ref=refs_payload["search_iteration_plan"],
            ))

    campaign_id = str(
        campaign_plan.get("campaign_id")
        or search_iteration_plan.get("campaign_id")
        or queue.get("campaign_id")
        or "campaign"
    )
    workload_run_id = str(
        campaign_plan.get("workload_run_id")
        or search_iteration_plan.get("workload_run_id")
        or queue.get("workload_run_id")
        or "workload_run"
    )
    trial_id = str(
        campaign_plan.get("trial_id")
        or search_iteration_plan.get("trial_id")
        or queue.get("trial_id")
        or "trial"
    )
    plan_id = f"campaign_search_admission_plan::{_short_id(campaign_id, workload_run_id, trial_id, search_iteration_plan.get('next_best_candidate_id'))}"
    if materialized_entries:
        admission_status = "step3_queue_write_required"
    elif step2_iteration_requests:
        admission_status = "step2_materialization_required"
    else:
        admission_status = "proposal_only"
    return {
        "schema_version": CONTRACT_VERSION,
        "campaign_id": campaign_id,
        "workload_run_id": workload_run_id,
        "trial_id": trial_id,
        "plan_id": plan_id,
        "status": "active",
        "admission_status": admission_status,
        "plan_scope": "post_step4_search_feedback_budget_bridge",
        "budget_policy": dict(combined_budget),
        "campaign_evaluation_plan_ref": refs_payload["campaign_evaluation_plan"],
        "search_iteration_plan_ref": refs_payload["search_iteration_plan"],
        "step3_simulation_queue_ref": refs_payload["step3_simulation_queue"],
        "search_iteration_applied_feedback_count": int(search_iteration_plan.get("applied_feedback_count", 0) or 0),
        "next_candidate_count": len(next_candidates),
        "existing_step3_queue_entry_count": int(queue.get("entry_count", len(_as_list(queue.get("entries")))) or 0),
        "already_materialized_candidate_count": already_materialized_count,
        "step2_iteration_request_count": len(step2_iteration_requests),
        "step2_iteration_requests": step2_iteration_requests,
        "materialized_step3_queue_entry_count": len(materialized_entries),
        "materialized_step3_queue_entries": materialized_entries,
        "admitted_entry_count": 0,
        "deferred_candidate_count": len(deferred_candidates),
        "deferred_candidates": deferred_candidates,
        "admission_control": {
            "step3_admission_authority": "step2/step3_simulation_queue.json",
            "search_iteration_plan_role": "proposal_ordering_not_step3_admission",
            "requested_next_step3_queue_entry_budget": requested_budget,
            "widening_requested_by_budget": widening_requested,
            "widening_allowed_by_budget": widening_allowed,
            "materialized_step3_queue_required": True,
            "step2_materialization_required_for_unmaterialized_candidates": True,
            "hidden_evidence_fanout_allowed": False,
            "claim_boundary": (
                "Search feedback may request Step2 candidate materialization, but Step3 "
                "execution remains blocked until canonical step3_simulation_queue.json "
                "contains materialized entries."
            ),
        },
        "execution_allowed": False,
        "top_k_queue_provenance_only": True,
        "hidden_evidence_fanout_allowed": False,
        "broad_evidence_run": False,
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "claim_boundary": (
            "Campaign search admission plans consume feedback-informed search ordering "
            "only. They are not evidence runs and cannot establish final ranking or "
            "release completion."
        ),
        "resume_next_actions": [
            "run Step2 materialization for step2_iteration_requests before Step3",
            "write any authorized candidates into step2/step3_simulation_queue.json before execution",
            "do not execute deferred_candidates without an explicit widened Campaign budget",
        ],
    }


__all__ = ["build_campaign_search_admission_plan"]
