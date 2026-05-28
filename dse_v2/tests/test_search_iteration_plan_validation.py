#!/usr/bin/env python3
"""Regression tests for fail-closed search-iteration plan validation."""

from __future__ import annotations

import json
import subprocess
import sys

from dse_v2.mapping.search_plan_validation import validate_search_iteration_plan
from dse_v2.mapping.search_policy import (
    HIERARCHICAL_FUNNEL_STAGES,
    HierarchicalFunnelSearchPolicy,
    SearchProblem,
    build_search_iteration_plan,
)


def _valid_complete_dse_plan() -> dict:
    candidate_identity = {
        "taxonomy_id": "fft_stream",
        "mapping_id": "mapping-identity",
        "compile_schedule_id": "compile-identity",
        "runtime_schedule_id": "runtime-identity",
        "parameter_profile_id": "profile-identity",
    }
    problem = SearchProblem(
        problem_id="validation-plan",
        workload_run_id="validation-workload",
        objective="maximize throughput",
        parameters={
            "release_lane": ["release"],
            "complete_dse_candidate_id": ["complete-candidate-plan"],
            "architecture_id": ["release_v1_fft_stream"],
            "taxonomy_id": ["fft_stream"],
            "design_point_id": ["complete-candidate-plan::__workload_case_bound_at_step3"],
            "mapping_id": ["mapping-identity"],
            "mapping_candidate_id": ["mapping-identity"],
            "mapping_parameter_hash": ["sha256:mapping"],
            "compile_schedule_id": ["compile-identity"],
            "runtime_schedule_id": ["runtime-identity"],
            "parameter_profile_id": ["profile-identity"],
            "candidate_record_hash": ["sha256:record"],
            "release_subset_hash": ["sha256:release-subset"],
            "candidate_identity": [candidate_identity],
            "candidate_identity_policy": ["complete_dse_release_subset_v1"],
            "step2_candidate_rank_score": [10],
        },
        constraints={
            "formal_pareto_lane_field": "release_lane",
            "release_lane": "release",
            "hierarchical_funnel_stages": HIERARCHICAL_FUNNEL_STAGES,
        },
    )
    policy = HierarchicalFunnelSearchPolicy(bottleneck_keys=("step2_candidate_rank_score",))
    first_round = policy.propose(problem, budget=1)
    checkpoint = policy.checkpoint(problem).to_dict()
    return build_search_iteration_plan(
        search_checkpoint={
            "schema_version": "dse.step2.search_checkpoint_summary.v1",
            "search_policy_name": "hierarchical_funnel",
            "search_policy_problem": problem.to_dict(),
            "search_policy_checkpoint": checkpoint,
            "search_policy_proposal_budget": 1,
        },
        feedback_update={
            "schema_version": "dse.contract.feedback_update.v1",
            "campaign_id": "campaign",
            "workload_run_id": "validation-workload",
            "trial_id": "trial",
            "updates": [
                {
                    "target": "search_policy",
                    "status": "available",
                    "candidate_refs": {
                        "complete_dse_candidate_id": "complete-candidate-plan",
                        "search_policy_candidate_id": first_round[0].candidate_id,
                    },
                    "metrics": {
                        "objective_metric_name": "latency_ms",
                        "objective_direction": "minimize",
                        "objective_metric_value": 0.7,
                        "latency_ms": 0.7,
                        "trusted_sample": True,
                    },
                }
            ],
            "source_artifact_hashes": {},
        },
        calibration_record={"confidence": 0.95, "error_metrics": {"max_abs_error": 0.0}},
        refs={"step3_simulation_queue": "step2/complete_dse_step3_simulation_queue.json"},
    )


def _add_lower_scoring_candidate(plan: dict) -> str:
    lower_candidate_id = "second-candidate"
    lower_identity = {
        "taxonomy_id": "fft_stream",
        "mapping_id": "second-mapping",
        "compile_schedule_id": "second-compile",
        "runtime_schedule_id": "second-runtime",
        "parameter_profile_id": "second-profile",
    }
    second_candidate = json.loads(json.dumps(plan["next_candidates"][0]))
    second_checkpoint = json.loads(json.dumps(plan["next_checkpoint"]["candidates"][0]))
    second_admission = json.loads(json.dumps(plan["next_step3_admission_candidates"][0]))
    for row in (second_candidate, second_checkpoint, second_admission):
        row["candidate_id"] = lower_candidate_id
        row["search_policy_candidate_id"] = lower_candidate_id
        row["complete_dse_candidate_id"] = "second-complete-candidate"
        row["design_point_id"] = "second-complete-candidate::__workload_case_bound_at_step3"
        row["mapping_id"] = "second-mapping"
        row["mapping_candidate_id"] = "second-mapping"
        row["compile_schedule_id"] = "second-compile"
        row["runtime_schedule_id"] = "second-runtime"
        row["parameter_profile_id"] = "second-profile"
        row["candidate_record_hash"] = "sha256:second-record"
        row["release_subset_hash"] = "sha256:second-release"
        row["parameter_hash"] = "sha256:second-candidate"
        row["search_policy_parameter_hash"] = "sha256:second-candidate"
        row["mapping_parameter_hash"] = "sha256:second-mapping"
        row["score"] = float(plan["next_candidates"][0]["score"]) - 100.0
        row["candidate_identity"] = dict(lower_identity)
        if isinstance(row.get("parameters"), dict):
            row["parameters"].update({
                "complete_dse_candidate_id": "second-complete-candidate",
                "design_point_id": "second-complete-candidate::__workload_case_bound_at_step3",
                "mapping_id": "second-mapping",
                "mapping_candidate_id": "second-mapping",
                "mapping_parameter_hash": "sha256:second-mapping",
                "compile_schedule_id": "second-compile",
                "runtime_schedule_id": "second-runtime",
                "parameter_profile_id": "second-profile",
                "candidate_record_hash": "sha256:second-record",
                "release_subset_hash": "sha256:second-release",
                "candidate_identity": dict(lower_identity),
            })
        if isinstance(row.get("provenance"), dict):
            row["provenance"].update({
                "parameter_hash": "sha256:second-candidate",
                "candidate_identity": dict(lower_identity),
            })
    second_candidate["search_policy_rank"] = 2
    second_admission["search_policy_rank"] = 2
    plan["next_candidates"].append(second_candidate)
    plan["next_step3_admission_candidates"].append(second_admission)
    plan["next_checkpoint"]["candidates"].append(second_checkpoint)
    plan["next_proposed_count"] = len(plan["next_candidates"])
    plan["next_step3_admission_candidate_count"] = len(plan["next_step3_admission_candidates"])
    plan["next_checkpoint"]["candidate_count"] = len(plan["next_checkpoint"]["candidates"])
    plan["next_checkpoint"]["proposed_count"] = len(plan["next_checkpoint"]["candidates"])
    return lower_candidate_id


def test_valid_search_iteration_plan_passes_fail_closed_validator():
    plan = _valid_complete_dse_plan()

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is True
    assert validation["status"] == "passed"
    assert validation["error_count"] == 0
    assert validation["summary"]["next_candidate_count"] == 1
    assert validation["summary"]["eligible_candidate_count"] == 1
    assert validation["summary"]["admission_candidate_count"] == 1
    assert validation["summary"]["feedback_observation_count"] == 1
    assert validation["summary"]["applied_feedback_count"] == 1
    assert validation["campaign_scope_validation"]["valid"] is True
    assert validation["campaign_scope_validation"]["plan_scope"] == {
        "campaign_id": "campaign",
        "workload_run_id": "validation-workload",
        "trial_id": "trial",
    }
    assert validation["campaign_scope_validation"]["row_scope_error_count"] == 0
    assert validation["campaign_scope_validation"]["row_scope_errors"] == []
    assert validation["trusted_final_claim"] is False
    assert validation["release_completion_eligible"] is False
    assert validation["deliverable_complete"] is False
    provenance = plan["source_artifact_provenance"]
    assert provenance["input_search_checkpoint"]["payload_hash"].startswith("sha256:")
    assert provenance["feedback_update"]["ref"] == "feedback_update.json"
    assert plan["campaign_id"] == "campaign"
    assert plan["workload_run_id"] == "validation-workload"
    assert plan["trial_id"] == "trial"


def test_validator_blocks_hidden_execution_and_completion_flags():
    plan = _valid_complete_dse_plan()
    plan["trusted_final_claim"] = True
    plan["hidden_evidence_fanout_allowed"] = True
    plan["next_candidates"][0]["execution_allowed"] = True
    plan["next_candidates"][0]["deliverable_complete"] = True
    plan["next_step3_admission_candidates"][0]["execution_allowed"] = True
    plan["next_step3_admission_candidates"][0]["release_completion_eligible"] = True

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "plan.trusted_final_claim" in error_fields
    assert "hidden_evidence_fanout_allowed" in error_fields
    assert "next_candidates[0].execution_allowed" in error_fields
    assert "next_candidates[0].deliverable_complete" in error_fields
    assert "next_step3_admission_candidates[0].execution_allowed" in error_fields
    assert "next_step3_admission_candidates[0].release_completion_eligible" in error_fields


def test_validator_blocks_forged_step3_admission_queue_refs():
    plan = _valid_complete_dse_plan()
    plan["step3_admission_queue"] = "forged/step3_simulation_queue.json"
    plan["next_candidates"][0]["admission_required_before_execution"] = "forged/step3_simulation_queue.json"
    plan["next_step3_admission_candidates"][0]["admission_required_before_execution"] = "forged/step3_simulation_queue.json"

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "step3_admission_queue" in error_fields
    assert "next_candidates[0].admission_required_before_execution" in error_fields
    assert "next_step3_admission_candidates[0].admission_required_before_execution" in error_fields


def test_validator_blocks_non_run_local_step3_admission_queue_refs():
    for bad_ref in ("/tmp/external_step3_queue.json", "step2/../../external_step3_queue.json"):
        plan = _valid_complete_dse_plan()
        plan["next_step3_admission_queue_ref"] = bad_ref
        plan["step3_admission_queue"] = bad_ref
        plan["next_candidates"][0]["admission_required_before_execution"] = bad_ref
        plan["next_step3_admission_candidates"][0]["admission_required_before_execution"] = bad_ref

        validation = validate_search_iteration_plan(plan)
        error_fields = {error["field"] for error in validation["errors"]}

        assert validation["valid"] is False
        assert "next_step3_admission_queue_ref" in error_fields


def test_validator_blocks_missing_and_extra_admission_candidates():
    plan = _valid_complete_dse_plan()
    eligible_id = plan["next_candidates"][0]["candidate_id"]
    plan["next_step3_admission_candidates"] = [
        {
            **plan["next_step3_admission_candidates"][0],
            "candidate_id": "not-an-eligible-candidate",
        }
    ]

    validation = validate_search_iteration_plan(plan)
    matching_errors = [
        error for error in validation["errors"]
        if error["field"] == "next_step3_admission_candidates"
    ]

    assert validation["valid"] is False
    assert any(error.get("missing_candidate_ids") == [eligible_id] for error in matching_errors)
    assert any(error.get("extra_candidate_ids") == ["not-an-eligible-candidate"] for error in matching_errors)


def test_validator_blocks_ambiguous_admission_candidate_aliases():
    plan = _valid_complete_dse_plan()
    second_candidate = json.loads(json.dumps(plan["next_candidates"][0]))
    second_checkpoint = json.loads(json.dumps(plan["next_checkpoint"]["candidates"][0]))
    second_admission = json.loads(json.dumps(plan["next_step3_admission_candidates"][0]))
    for row in (second_candidate, second_checkpoint, second_admission):
        row["candidate_id"] = "second-candidate"
        row["search_policy_candidate_id"] = "second-candidate"
        row["complete_dse_candidate_id"] = "second-complete-candidate"
        row["parameter_hash"] = "sha256:second-candidate"
        row["search_policy_parameter_hash"] = "sha256:second-candidate"
        row["search_policy_rank"] = 2
    plan["next_candidates"].append(second_candidate)
    plan["next_step3_admission_candidates"].append(second_admission)
    plan["next_checkpoint"]["candidates"].append(second_checkpoint)
    plan["next_proposed_count"] = len(plan["next_candidates"])
    plan["next_step3_admission_candidate_count"] = len(plan["next_step3_admission_candidates"])
    plan["next_checkpoint"]["candidate_count"] = len(plan["next_checkpoint"]["candidates"])
    plan["next_checkpoint"]["proposed_count"] = len(plan["next_checkpoint"]["candidates"])

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert validation["summary"]["duplicate_admission_alias_count"] >= 1
    assert any(
        error["field"] == "next_step3_admission_candidates.aliases"
        and "mapping-identity" in error.get("duplicates", {})
        for error in validation["errors"]
    )


def test_validator_blocks_ambiguous_next_candidate_aliases():
    plan = _valid_complete_dse_plan()
    second_candidate = json.loads(json.dumps(plan["next_candidates"][0]))
    second_checkpoint = json.loads(json.dumps(plan["next_checkpoint"]["candidates"][0]))
    second_admission = json.loads(json.dumps(plan["next_step3_admission_candidates"][0]))
    for row in (second_candidate, second_checkpoint, second_admission):
        row["candidate_id"] = "second-candidate"
        row["search_policy_candidate_id"] = "second-candidate"
        row["complete_dse_candidate_id"] = "second-complete-candidate"
        row["mapping_candidate_id"] = "second-mapping"
        row["parameter_hash"] = "sha256:second-candidate"
        row["search_policy_parameter_hash"] = "sha256:second-candidate"
        row["search_policy_rank"] = 2
    second_candidate["mapping_parameter_hash"] = plan["next_candidates"][0]["mapping_parameter_hash"]
    plan["next_candidates"].append(second_candidate)
    plan["next_step3_admission_candidates"].append(second_admission)
    plan["next_checkpoint"]["candidates"].append(second_checkpoint)
    plan["next_proposed_count"] = len(plan["next_candidates"])
    plan["next_step3_admission_candidate_count"] = len(plan["next_step3_admission_candidates"])
    plan["next_checkpoint"]["candidate_count"] = len(plan["next_checkpoint"]["candidates"])
    plan["next_checkpoint"]["proposed_count"] = len(plan["next_checkpoint"]["candidates"])

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert validation["summary"]["duplicate_candidate_alias_count"] >= 1
    assert any(
        error["field"] == "next_candidates.aliases"
        and plan["next_candidates"][0]["mapping_parameter_hash"] in error.get("duplicates", {})
        for error in validation["errors"]
    )


def test_validator_blocks_feedback_route_detached_from_checkpoint():
    plan = _valid_complete_dse_plan()
    plan["feedback_observation_routing"][0]["matched_candidate_id"] = "candidate-not-in-checkpoint"

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "feedback_observation_routing[0].matched_candidate_id"
        for error in validation["errors"]
    )


def test_validator_blocks_feedback_route_alias_not_owned_by_matched_checkpoint_candidate():
    plan = _valid_complete_dse_plan()
    route = plan["feedback_observation_routing"][0]
    route["matched_candidate_alias"] = "forged-candidate-alias"
    route["candidate_aliases"] = ["forged-candidate-alias"]
    route["checked_candidate_aliases"] = ["forged-candidate-alias"]

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "feedback_observation_routing[0].matched_candidate_alias"
        and "matched checkpoint candidate" in error["message"]
        for error in validation["errors"]
    )


def test_validator_does_not_treat_non_identity_parameter_scalars_as_feedback_aliases():
    plan = _valid_complete_dse_plan()
    plan["next_candidates"][0]["parameters"]["source_state"] = "selected"
    plan["next_candidates"][0]["parameters"]["mapping"] = {
        "fft": "host",
        "reduction": "gpu-0",
    }
    plan["next_checkpoint"]["candidates"][0]["parameters"] = dict(
        plan["next_candidates"][0]["parameters"]
    )
    route = plan["feedback_observation_routing"][0]
    route["matched_candidate_alias"] = "host"
    route["candidate_aliases"] = ["host"]
    route["checked_candidate_aliases"] = ["host"]

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "feedback_observation_routing[0].matched_candidate_alias"
        and "matched checkpoint candidate" in error["message"]
        and error["actual"] == "host"
        for error in validation["errors"]
    )


def test_validator_blocks_feedback_route_alias_with_ambiguous_checkpoint_owner():
    plan = _valid_complete_dse_plan()
    shared_alias = plan["next_checkpoint"]["candidates"][0]["parameters"]["mapping_parameter_hash"]
    second_checkpoint = json.loads(json.dumps(plan["next_checkpoint"]["candidates"][0]))
    second_checkpoint["candidate_id"] = "second-checkpoint-candidate"
    second_checkpoint["search_policy_candidate_id"] = "second-checkpoint-candidate"
    second_checkpoint["complete_dse_candidate_id"] = "second-complete-candidate"
    second_checkpoint["parameter_hash"] = "sha256:second-checkpoint-candidate"
    second_checkpoint["provenance"]["parameter_hash"] = "sha256:second-checkpoint-candidate"
    second_checkpoint["parameters"]["complete_dse_candidate_id"] = "second-complete-candidate"
    plan["next_checkpoint"]["candidates"].append(second_checkpoint)
    plan["next_checkpoint"]["candidate_count"] = len(plan["next_checkpoint"]["candidates"])
    plan["next_checkpoint"]["proposed_count"] = len(plan["next_checkpoint"]["candidates"])
    route = plan["feedback_observation_routing"][0]
    route["matched_candidate_alias"] = shared_alias
    route["candidate_aliases"] = [shared_alias]
    route["checked_candidate_aliases"] = [shared_alias]

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert validation["summary"]["ambiguous_checkpoint_feedback_alias_count"] >= 1
    assert any(
        error["field"] == "feedback_observation_routing[0].matched_candidate_alias"
        and "exactly one checkpoint candidate owner" in error["message"]
        and shared_alias == error["actual"]
        for error in validation["errors"]
    )


def test_validator_blocks_feedback_route_missing_matched_alias_from_candidate_aliases():
    plan = _valid_complete_dse_plan()
    route = plan["feedback_observation_routing"][0]
    matched_alias = route["matched_candidate_alias"]
    route["candidate_aliases"] = ["other-checked-alias"]
    route["checked_candidate_aliases"] = [matched_alias]

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "feedback_observation_routing[0].candidate_aliases"
        and "matched_candidate_alias" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_feedback_route_missing_matched_alias_from_checked_aliases():
    plan = _valid_complete_dse_plan()
    route = plan["feedback_observation_routing"][0]
    matched_alias = route["matched_candidate_alias"]
    route["candidate_aliases"] = [matched_alias, "later-alias"]
    route["checked_candidate_aliases"] = ["other-checked-alias"]

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "feedback_observation_routing[0].checked_candidate_aliases"
        and "matched_candidate_alias" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_feedback_route_checked_aliases_after_match():
    plan = _valid_complete_dse_plan()
    route = plan["feedback_observation_routing"][0]
    matched_alias = route["matched_candidate_alias"]
    route["candidate_aliases"] = [matched_alias, "later-alias"]
    route["checked_candidate_aliases"] = [matched_alias, "later-alias"]

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "feedback_observation_routing[0].checked_candidate_aliases"
        and "stop at matched_candidate_alias" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_feedback_route_source_alias_rebinding():
    plan = _valid_complete_dse_plan()
    route = plan["feedback_observation_routing"][0]
    original_source = route["source_candidate_id"]
    complete_alias = route["candidate_refs"]["complete_dse_candidate_id"]
    route["candidate_aliases"] = ["forged-source-alias", original_source, complete_alias]

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "feedback_observation_routing[0].source_candidate_id"
        for error in validation["errors"]
    )


def test_validator_blocks_feedback_route_candidate_ref_alias_detached_from_aliases():
    plan = _valid_complete_dse_plan()
    route = plan["feedback_observation_routing"][0]
    route["candidate_refs"]["mapping_candidate_id"] = "mapping-ref-not-in-aliases"

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "feedback_observation_routing[0].candidate_refs.mapping_candidate_id"
        for error in validation["errors"]
    )


def test_validator_blocks_feedback_route_metric_alias_rebinding():
    plan = _valid_complete_dse_plan()
    route = plan["feedback_observation_routing"][0]
    route["metrics"]["step4_feedback_source_candidate_id"] = "forged-source"
    route["metrics"]["step4_feedback_matched_candidate_alias"] = "forged-match"

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "feedback_observation_routing[0].metrics.step4_feedback_source_candidate_id" in error_fields
    assert "feedback_observation_routing[0].metrics.step4_feedback_matched_candidate_alias" in error_fields


def test_validator_blocks_observed_count_drift_from_feedback_routes():
    plan = _valid_complete_dse_plan()
    plan["output_observed_count"] += 1

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "output_observed_count" in error_fields
    assert "next_checkpoint.observed_count" in error_fields


def test_validator_blocks_missing_feedback_checkpoint_count_contract():
    plan = _valid_complete_dse_plan()
    del plan["input_observed_count"]
    del plan["output_observed_count"]
    del plan["next_checkpoint"]["observed_count"]

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "input_observed_count" in error_fields
    assert "output_observed_count" in error_fields
    assert "next_checkpoint.observed_count" in error_fields


def test_validator_blocks_proposals_detached_from_checkpoint():
    plan = _valid_complete_dse_plan()
    candidate_id = plan["next_candidates"][0]["candidate_id"]
    plan["next_checkpoint"]["candidates"] = []
    plan["next_checkpoint"]["candidate_count"] = 0
    plan["next_checkpoint"]["proposed_count"] = 0

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "next_checkpoint.candidates"
        and error.get("missing_candidate_ids") == [candidate_id]
        for error in validation["errors"]
    )


def test_validator_blocks_checkpoint_only_candidate_feedback_route():
    plan = _valid_complete_dse_plan()
    hidden = json.loads(json.dumps(plan["next_checkpoint"]["candidates"][0]))
    hidden["candidate_id"] = "hidden-checkpoint-only"
    hidden["search_policy_candidate_id"] = "hidden-checkpoint-only"
    hidden["complete_dse_candidate_id"] = "hidden-complete"
    hidden["parameter_hash"] = "sha256:hidden"
    hidden["provenance"]["parameter_hash"] = "sha256:hidden"
    hidden["parameters"]["complete_dse_candidate_id"] = "hidden-complete"

    plan["next_checkpoint"]["candidates"].append(hidden)
    plan["next_checkpoint"]["candidate_count"] = len(plan["next_checkpoint"]["candidates"])
    plan["next_checkpoint"]["proposed_count"] = len(plan["next_checkpoint"]["candidates"])

    route = plan["feedback_observation_routing"][0]
    route["matched_candidate_id"] = "hidden-checkpoint-only"
    route["matched_candidate_alias"] = "hidden-complete"
    route["source_candidate_id"] = "hidden-complete"
    route["candidate_aliases"] = ["hidden-complete"]
    route["checked_candidate_aliases"] = ["hidden-complete"]
    route["candidate_refs"] = {"complete_dse_candidate_id": "hidden-complete"}
    route["metrics"]["step4_feedback_source_candidate_id"] = "hidden-complete"
    route["metrics"]["step4_feedback_matched_candidate_alias"] = "hidden-complete"

    validation = validate_search_iteration_plan(plan)
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "next_checkpoint.candidates" in fields
    assert "feedback_observation_routing[0].matched_candidate_id" in fields


def test_validator_blocks_proposal_rebound_from_checkpoint_payload():
    plan = _valid_complete_dse_plan()
    candidate_id = plan["next_candidates"][0]["candidate_id"]
    plan["next_candidates"][0]["parameter_hash"] = "sha256:forged-proposal-hash"
    plan["next_candidates"][0]["parameters"] = {"forged": True}
    plan["next_candidates"][0]["simulation_eligible"] = False
    plan["next_candidates"][0]["score"] += 10

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert f"next_candidates[{candidate_id}].parameter_hash" in error_fields
    assert f"next_candidates[{candidate_id}].parameters" in error_fields
    assert f"next_candidates[{candidate_id}].simulation_eligible" in error_fields
    assert f"next_candidates[{candidate_id}].score" in error_fields


def test_validator_blocks_forged_checkpoint_summary_fields():
    plan = _valid_complete_dse_plan()
    plan["next_checkpoint"]["best_candidate_id"] = "not-the-plan-best"
    plan["next_checkpoint"]["candidate_count"] += 1
    plan["next_checkpoint"]["proposal_budget"] = plan["next_proposal_budget"] + 1

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "next_checkpoint.best_candidate_id" in error_fields
    assert "next_checkpoint.candidate_count" in error_fields
    assert "next_checkpoint.proposal_budget" in error_fields


def test_validator_recomputes_best_candidate_from_checkpoint_scores():
    plan = _valid_complete_dse_plan()
    lower_candidate_id = _add_lower_scoring_candidate(plan)
    assert validate_search_iteration_plan(plan)["valid"] is True
    plan["next_best_candidate_id"] = lower_candidate_id
    plan["next_checkpoint"]["best_candidate_id"] = lower_candidate_id

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "next_checkpoint.best_candidate_id"
        and "highest candidate score" in error["message"]
        and error.get("actual") == lower_candidate_id
        for error in validation["errors"]
    )


def test_validator_reports_malformed_search_count_fields_without_crashing():
    plan = _valid_complete_dse_plan()
    plan["next_proposed_count"] = "not-an-integer"
    plan["next_step3_admission_candidate_count"] = True
    plan["next_proposal_budget"] = 1.5
    plan["next_checkpoint"]["candidate_count"] = 1.5
    plan["next_checkpoint"]["proposed_count"] = -1
    plan["next_checkpoint"]["proposal_budget"] = "1"
    enumeration = plan["next_candidates"][0]["provenance"]["search_space_enumeration"]
    enumeration["grid_candidate_count"] = "1"
    enumeration["grid_candidate_enumerated_count"] = True

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "next_proposed_count" in error_fields
    assert "next_step3_admission_candidate_count" in error_fields
    assert "next_proposal_budget" in error_fields
    assert "next_checkpoint.candidate_count" in error_fields
    assert "next_checkpoint.proposed_count" in error_fields
    assert "next_checkpoint.proposal_budget" in error_fields
    assert (
        "next_candidates[0].provenance.search_space_enumeration.grid_candidate_count"
        in error_fields
    )
    assert (
        "next_candidates[0].provenance.search_space_enumeration.grid_candidate_enumerated_count"
        in error_fields
    )


def test_validator_blocks_forged_feedback_route_counts_and_claims():
    plan = _valid_complete_dse_plan()
    plan["applied_feedback_count"] = 0
    plan["feedback_observation_count"] = 2
    plan["feedback_unresolved_observation_count"] = 0
    plan["feedback_routing_status"] = "all_feedback_observations_routed"
    plan["feedback_observation_routing"][0]["trusted_final_claim"] = True
    plan["feedback_observation_routing"][0]["routing_blockers"] = ["should_not_be_present"]

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "feedback_observation_count" in error_fields
    assert "applied_feedback_count" in error_fields
    assert "feedback_observation_routing[0].trusted_final_claim" in error_fields
    assert "feedback_observation_routing[0].routing_blockers" in error_fields


def test_validator_requires_explicit_zero_feedback_routing_contract():
    plan = _valid_complete_dse_plan()
    plan["applied_feedback_count"] = 0
    plan["output_observed_count"] = plan["input_observed_count"]
    plan["next_checkpoint"]["observed_count"] = plan["output_observed_count"]
    for field in (
        "feedback_observation_routing",
        "feedback_observation_count",
        "feedback_unresolved_observation_count",
        "feedback_routing_status",
    ):
        plan.pop(field)

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "feedback_observation_routing" in error_fields
    assert "feedback_observation_count" in error_fields
    assert "feedback_unresolved_observation_count" in error_fields
    assert "feedback_routing_status" in error_fields


def test_validator_reports_malformed_feedback_count_fields_without_crashing():
    plan = _valid_complete_dse_plan()
    plan["applied_feedback_count"] = True
    plan["input_observed_count"] = "0"
    plan["output_observed_count"] = 1.0
    plan["candidate_alias_count"] = True
    plan["feedback_observation_count"] = True
    plan["feedback_unresolved_observation_count"] = False
    plan["next_checkpoint"]["observed_count"] = 1.0

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "applied_feedback_count" in error_fields
    assert "input_observed_count" in error_fields
    assert "output_observed_count" in error_fields
    assert "candidate_alias_count" in error_fields
    assert "feedback_observation_count" in error_fields
    assert "feedback_unresolved_observation_count" in error_fields
    assert "next_checkpoint.observed_count" in error_fields


def test_validator_blocks_non_list_search_plan_containers():
    plan = _valid_complete_dse_plan()
    plan["next_candidates"] = "not-a-list"
    plan["next_proposed_count"] = 0
    plan["next_step3_admission_candidates"] = "not-a-list"
    plan["next_step3_admission_candidate_count"] = 0
    plan["next_checkpoint"]["candidates"] = "not-a-list"
    plan["next_checkpoint"]["candidate_count"] = 0
    plan["next_checkpoint"]["proposed_count"] = 0
    plan["feedback_observation_routing"] = "not-a-list"
    plan["feedback_observation_count"] = 0

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "next_candidates" in error_fields
    assert "next_step3_admission_candidates" in error_fields
    assert "next_checkpoint.candidates" in error_fields
    assert "feedback_observation_routing" in error_fields


def test_validator_blocks_non_mapping_checkpoint_candidate_rows():
    plan = _valid_complete_dse_plan()
    plan["next_checkpoint"]["candidates"].append("not-a-checkpoint-row")
    plan["next_checkpoint"]["candidate_count"] = 2
    plan["next_checkpoint"]["proposed_count"] = 2

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "next_checkpoint.candidates[1]"
        and "must be a mapping" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_missing_search_iteration_source_provenance():
    plan = _valid_complete_dse_plan()
    del plan["source_artifact_provenance"]

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "source_artifact_provenance"
        for error in validation["errors"]
    )


def test_validator_blocks_source_refs_without_provenance_even_without_feedback():
    plan = _valid_complete_dse_plan()
    plan["applied_feedback_count"] = 0
    plan["feedback_observation_count"] = 0
    plan["feedback_unresolved_observation_count"] = 0
    plan["feedback_observation_routing"] = []
    plan["feedback_routing_status"] = "no_feedback_observations"
    plan["output_observed_count"] = plan["input_observed_count"]
    plan["next_checkpoint"]["observed_count"] = plan["output_observed_count"]
    del plan["source_artifact_provenance"]

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "source_artifact_provenance.input_search_checkpoint" in error_fields
    assert "source_artifact_provenance.feedback_update" in error_fields
    assert "source_artifact_provenance.calibration_record" in error_fields


def test_validator_blocks_stale_or_rebound_search_iteration_source_refs():
    plan = _valid_complete_dse_plan()
    plan["input_search_checkpoint_ref"] = "stale_sidecar/search_checkpoint.old.json"
    plan["feedback_update_ref"] = "wrong_source_artifact.json"
    plan["calibration_record_ref"] = "wrong_calibration.json"
    plan["source_artifact_provenance"]["feedback_update"]["payload_hash"] = "not-a-sha"

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "input_search_checkpoint_ref" in error_fields
    assert "feedback_update_ref" in error_fields
    assert "calibration_record_ref" in error_fields
    assert "source_artifact_provenance.input_search_checkpoint.ref" in error_fields
    assert "source_artifact_provenance.feedback_update.ref" in error_fields
    assert "source_artifact_provenance.feedback_update.payload_hash" in error_fields


def test_validator_blocks_unresolved_feedback_route_without_blocker():
    plan = _valid_complete_dse_plan()
    route = plan["feedback_observation_routing"][0]
    route["routing_status"] = "unresolved_candidate_alias"
    route["routed_to_search_policy"] = False
    route["matched_candidate_id"] = ""
    route["matched_candidate_alias"] = ""
    route["routing_blockers"] = []
    plan["applied_feedback_count"] = 0
    plan["feedback_unresolved_observation_count"] = 1
    plan["feedback_routing_status"] = "partial_unresolved_feedback_observations"

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "feedback_observation_routing[0].routing_blockers"
        for error in validation["errors"]
    )


def test_validator_blocks_admission_projection_identity_rebinding():
    plan = _valid_complete_dse_plan()
    admission = plan["next_step3_admission_candidates"][0]
    admission["complete_dse_candidate_id"] = "forged-complete-candidate"
    admission["architecture_id"] = "forged-architecture"
    admission["mapping_candidate_id"] = "forged-mapping"
    admission["candidate_identity"] = {"taxonomy_id": "forged"}
    admission["search_policy_rank"] = 99

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "next_step3_admission_candidates[0].complete_dse_candidate_id" in error_fields
    assert "next_step3_admission_candidates[0].architecture_id" in error_fields
    assert "next_step3_admission_candidates[0].mapping_candidate_id" in error_fields
    assert "next_step3_admission_candidates[0].candidate_identity" in error_fields
    assert "next_step3_admission_candidates[0].search_policy_rank" in error_fields


def test_validator_blocks_search_iteration_row_scope_rebinding():
    plan = _valid_complete_dse_plan()
    plan["next_candidates"][0]["campaign_id"] = "campaign-forged"
    plan["next_step3_admission_candidates"][0]["parameters"] = {
        "workload_run_id": "workload-forged"
    }
    plan["next_checkpoint"]["candidates"][0]["trial_id"] = "trial-forged"
    plan["feedback_observation_routing"][0]["candidate_refs"]["campaign_id"] = "campaign-forged"

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert validation["campaign_scope_validation"]["valid"] is False
    assert validation["campaign_scope_validation"]["status"] == "failed"
    assert validation["campaign_scope_validation"]["row_scope_error_count"] == 4
    assert "next_candidates[0].campaign_id" in error_fields
    assert "next_step3_admission_candidates[0].workload_run_id" in error_fields
    assert "next_checkpoint.candidates[0].trial_id" in error_fields
    assert "feedback_observation_routing[0].campaign_id" in error_fields


def test_validator_blocks_missing_plan_scope_for_feedback_informed_plan():
    plan = _valid_complete_dse_plan()
    for field in ("campaign_id", "workload_run_id", "trial_id"):
        del plan[field]
    plan["next_candidates"][0]["campaign_id"] = "other-campaign"
    plan["feedback_observation_routing"][0]["candidate_refs"]["trial_id"] = "other-trial"

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert validation["campaign_scope_validation"]["valid"] is False
    assert "campaign_id" in error_fields
    assert "workload_run_id" in error_fields
    assert "trial_id" in error_fields
    assert "next_candidates[0].campaign_id" in error_fields
    assert "feedback_observation_routing[0].trial_id" in error_fields


def test_validator_blocks_provenance_scope_rebinding():
    plan = _valid_complete_dse_plan()
    plan["next_candidates"][0]["provenance"]["campaign_id"] = "campaign-forged"
    plan["next_step3_admission_candidates"][0]["provenance"] = {
        "workload_run_id": "workload-forged"
    }
    plan["next_checkpoint"]["candidates"][0]["provenance"]["trial_id"] = "trial-forged"
    plan["feedback_observation_routing"][0]["provenance"] = {
        "campaign_id": "campaign-forged"
    }

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert validation["campaign_scope_validation"]["valid"] is False
    assert validation["campaign_scope_validation"]["row_scope_error_count"] == 4
    assert "next_candidates[0].campaign_id" in error_fields
    assert "next_step3_admission_candidates[0].workload_run_id" in error_fields
    assert "next_checkpoint.candidates[0].trial_id" in error_fields
    assert "feedback_observation_routing[0].campaign_id" in error_fields


def test_validator_blocks_identity_and_metric_scope_rebinding():
    plan = _valid_complete_dse_plan()
    for row in (
        plan["next_candidates"][0],
        plan["next_step3_admission_candidates"][0],
        plan["next_checkpoint"]["candidates"][0],
    ):
        row["candidate_identity"]["campaign_id"] = "campaign-forged"
    for row in (plan["next_candidates"][0], plan["next_checkpoint"]["candidates"][0]):
        row["observed_metrics"]["workload_run_id"] = "workload-forged"
    plan["feedback_observation_routing"][0]["metrics"]["trial_id"] = "trial-forged"

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert validation["campaign_scope_validation"]["valid"] is False
    assert validation["campaign_scope_validation"]["row_scope_error_count"] == 8
    assert "next_candidates[0].campaign_id" in error_fields
    assert "next_step3_admission_candidates[0].campaign_id" in error_fields
    assert "next_checkpoint.candidates[0].campaign_id" in error_fields
    assert "next_candidates[0].workload_run_id" in error_fields
    assert "next_checkpoint.candidates[0].workload_run_id" in error_fields
    assert "feedback_observation_routing[0].trial_id" in error_fields


def test_validator_blocks_proposal_search_policy_id_rebinding():
    plan = _valid_complete_dse_plan()
    plan["next_candidates"][0]["search_policy_candidate_id"] = "other-search-policy-id"

    validation = validate_search_iteration_plan(plan)

    assert validation["valid"] is False
    assert any(
        error["field"] == "next_candidates[0].search_policy_candidate_id"
        for error in validation["errors"]
    )


def test_validator_blocks_duplicate_parameter_hashes_and_bad_enumeration():
    plan = _valid_complete_dse_plan()
    duplicate = json.loads(json.dumps(plan["next_candidates"][0]))
    duplicate["candidate_id"] = "second-candidate"
    duplicate["provenance"]["search_space_enumeration"]["complete_grid_enumeration"] = False
    duplicate["provenance"]["search_space_enumeration"].pop("max_candidate_enumeration", None)
    plan["next_candidates"].append(duplicate)
    plan["next_proposed_count"] = len(plan["next_candidates"])

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "next_candidates.parameter_hash" in error_fields
    assert (
        "next_candidates[1].provenance.search_space_enumeration.max_candidate_enumeration"
        in error_fields
    )


def test_validator_blocks_missing_search_space_enumeration_provenance():
    plan = _valid_complete_dse_plan()
    plan["next_candidates"][0]["provenance"].pop("search_space_enumeration")

    validation = validate_search_iteration_plan(plan)
    error_fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert (
        "next_candidates[0].provenance.search_space_enumeration"
        in error_fields
    )
    assert validation["summary"]["complete_grid_enumeration"] is False


def test_cli_writes_validation_status_and_returns_nonzero_on_invalid_plan(tmp_path):
    plan = _valid_complete_dse_plan()
    plan_path = tmp_path / "search_iteration_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_dir = tmp_path / "validation"

    ok = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/validate_search_iteration_plan.py",
            str(plan_path),
            "--out",
            str(out_dir),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    ok_status = json.loads(ok.stdout)
    assert ok_status["valid"] is True
    assert (out_dir / "search_iteration_plan_validation.json").exists()
    assert (out_dir / "status.json").exists()

    plan["next_candidates"][0]["trusted_final_claim"] = True
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bad = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/validate_search_iteration_plan.py",
            str(plan_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    bad_validation = json.loads(bad.stdout)
    assert bad.returncode == 1
    assert bad_validation["valid"] is False
