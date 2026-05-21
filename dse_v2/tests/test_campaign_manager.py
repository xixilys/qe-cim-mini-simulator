#!/usr/bin/env python3
"""Regression coverage for campaign-level search admission planning."""

from __future__ import annotations

from dse_v2.contracts import SCHEMA_REGISTRY, validate_instance
from dse_v2.dse.campaign_manager import build_campaign_search_admission_plan


def _base_search_iteration_plan(**overrides):
    plan = {
        "schema_version": "dse.step2.search_iteration_plan.v1",
        "campaign_id": "campaign-001",
        "workload_run_id": "workload-run-001",
        "trial_id": "trial-001",
        "next_best_candidate_id": "candidate-001",
        "applied_feedback_count": 1,
        "output_observed_count": 2,
        "next_proposed_count": 1,
        "next_candidates": [
            {
                "candidate_id": "candidate-001",
                "search_policy_candidate_id": "candidate-001",
                "mapping_candidate_id": "mapping-001",
                "architecture_id": "arch-001",
                "parameter_hash": "sha256:abc",
                "step3_evaluable": True,
                "simulation_eligible": True,
                "search_policy_rank": 1,
                "score": 1.5,
            }
        ],
    }
    plan.update(overrides)
    return plan


def test_campaign_search_admission_plan_defaults_to_proposal_only_and_remains_fail_closed():
    plan = build_campaign_search_admission_plan(
        search_iteration_plan=_base_search_iteration_plan(),
        campaign_evaluation_plan={
            "campaign_id": "campaign-001",
            "workload_run_id": "workload-run-001",
            "trial_id": "trial-001",
            "budget_policy": {},
        },
        step3_simulation_queue={
            "schema_version": "dse.step3.simulation_queue.v1",
            "entry_count": 1,
            "entries": [
                {
                    "queue_entry_id": "queue-entry-001",
                    "candidate_id": "candidate-001",
                    "mapping_candidate_id": "mapping-001",
                    "architecture_id": "arch-001",
                }
            ],
        },
        refs={
            "campaign_evaluation_plan": "campaign_evaluation_plan.json",
            "search_iteration_plan": "search_iteration_plan.json",
            "step3_simulation_queue": "step2/step3_simulation_queue.json",
        },
    )

    validate_instance(plan, SCHEMA_REGISTRY["dse.contract.campaign_search_admission_plan.v1"])
    assert plan["admission_status"] == "proposal_only"
    assert plan["execution_allowed"] is False
    assert plan["top_k_queue_provenance_only"] is True
    assert plan["hidden_evidence_fanout_allowed"] is False
    assert plan["broad_evidence_run"] is False
    assert plan["trusted_final_claim"] is False
    assert plan["release_completion_eligible"] is False
    assert plan["already_materialized_candidate_count"] == 1
    assert plan["step2_iteration_request_count"] == 0
    assert plan["materialized_step3_queue_entry_count"] == 0
    assert plan["deferred_candidate_count"] == 1
    assert plan["deferred_candidates"][0]["status"] == "already_materialized_in_step3_queue"


def test_campaign_search_admission_plan_requests_step2_materialization_when_budget_allows():
    plan = build_campaign_search_admission_plan(
        search_iteration_plan=_base_search_iteration_plan(
            next_candidates=[
                {
                    "candidate_id": "candidate-002",
                    "search_policy_candidate_id": "candidate-002",
                    "mapping_candidate_id": "mapping-002",
                    "architecture_id": "arch-002",
                    "parameter_hash": "sha256:def",
                    "step3_evaluable": True,
                    "simulation_eligible": True,
                    "search_policy_rank": 1,
                    "score": 2.0,
                }
            ]
        ),
        campaign_evaluation_plan={
            "campaign_id": "campaign-001",
            "workload_run_id": "workload-run-001",
            "trial_id": "trial-001",
            "budget_policy": {"top_k_widening_allowed": True, "top_k_admission_budget": 1},
        },
        step3_simulation_queue={
            "schema_version": "dse.step3.simulation_queue.v1",
            "entry_count": 0,
            "entries": [],
        },
        budget_policy={"top_k_widening_allowed": True, "top_k_admission_budget": 1},
    )

    validate_instance(plan, SCHEMA_REGISTRY["dse.contract.campaign_search_admission_plan.v1"])
    assert plan["admission_status"] == "step2_materialization_required"
    assert plan["step2_iteration_request_count"] == 1
    assert plan["materialized_step3_queue_entry_count"] == 0
    assert plan["step2_iteration_requests"][0]["requested_action"] == "materialize_step2_artifacts_for_step3_queue"
    assert plan["step2_iteration_requests"][0]["execution_allowed"] is False
    assert plan["step2_iteration_requests"][0]["trusted_final_claim"] is False
    assert plan["step2_iteration_requests"][0]["release_completion_eligible"] is False


def test_campaign_search_admission_plan_preserves_embedded_materialized_step3_entry_but_keeps_execution_blocked():
    plan = build_campaign_search_admission_plan(
        search_iteration_plan=_base_search_iteration_plan(
            next_candidates=[
                {
                    "candidate_id": "candidate-003",
                    "search_policy_candidate_id": "candidate-003",
                    "mapping_candidate_id": "mapping-003",
                    "architecture_id": "arch-003",
                    "parameter_hash": "sha256:ghi",
                    "step3_evaluable": True,
                    "simulation_eligible": True,
                    "search_policy_rank": 1,
                    "score": 3.0,
                    "step3_queue_entry": {
                        "queue_entry_id": "queue-entry-003",
                        "candidate_id": "candidate-003",
                        "mapping_candidate_id": "mapping-003",
                        "architecture_id": "arch-003",
                        "mapping_id": "mapping-003",
                    },
                }
            ]
        ),
        campaign_evaluation_plan={
            "campaign_id": "campaign-001",
            "workload_run_id": "workload-run-001",
            "trial_id": "trial-001",
            "budget_policy": {"top_k_widening_allowed": True, "top_k_admission_budget": 1},
        },
        step3_simulation_queue={
            "schema_version": "dse.step3.simulation_queue.v1",
            "entry_count": 0,
            "entries": [],
        },
        budget_policy={"top_k_widening_allowed": True, "top_k_admission_budget": 1},
    )

    validate_instance(plan, SCHEMA_REGISTRY["dse.contract.campaign_search_admission_plan.v1"])
    assert plan["admission_status"] == "step3_queue_write_required"
    assert plan["step2_iteration_request_count"] == 0
    assert plan["materialized_step3_queue_entry_count"] == 1
    entry = plan["materialized_step3_queue_entries"][0]
    assert entry["queue_entry_id"] == "queue-entry-003"
    assert entry["admission_source"] == "campaign_search_admission_plan.json"
    assert entry["execution_allowed"] is False
    assert entry["trusted_final_claim"] is False
    assert entry["release_completion_eligible"] is False
