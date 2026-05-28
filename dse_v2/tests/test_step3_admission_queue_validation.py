#!/usr/bin/env python3
"""Regression tests for Step3 admission queue materialization validation."""

from __future__ import annotations

import json
import subprocess
import sys

from dse_v2.dse.step3_admission_queue_validation import (
    SCHEDULED_QUEUE_VALIDITY_FIELDS,
    validate_step3_admission_queue,
)


def _queue() -> dict:
    return {
        "schema_version": "dse.step3.simulation_queue.v1",
        "campaign_id": "campaign",
        "workload_run_id": "workload",
        "trial_id": "trial",
        "queue_mode": "selected-entry-only",
        "entry_count": 1,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "entries": [
            {
                "queue_entry_id": "step2-selected::arch::mapping-1",
                "candidate_id": "arch::mapping-1",
                "mapping_candidate_id": "mapping-1",
                "architecture_id": "arch",
                "design_point_id": "dp-1",
                "mapping_id": "map-1",
                "queue_state": "scheduled_for_simulation",
                "promoted_for_simulation": True,
                "step2_screenable": True,
                "step3_evaluable": True,
                "simulation_eligible": True,
                "simulation_blockers": [],
                "blocked_reasons": [],
                "claim_status": "legacy_pilot_only",
                "admission_source": "step2/step3_simulation_queue.json",
                "trusted_final_claim": False,
                "release_completion_eligible": False,
            }
        ],
    }


def _campaign_plan() -> dict:
    return {
        "schema_version": "dse.contracts.v1",
        "campaign_id": "campaign",
        "workload_run_id": "workload",
        "trial_id": "trial",
        "plan_id": "campaign_evaluation_plan::trial",
        "status": "active",
        "budget_policy": {},
        "step3_simulation_queue_ref": "step2/step3_simulation_queue.json",
        "top_k_candidate_queue_ref": "step2/top_k_candidate_queue.json",
        "planned_entry_count": 1,
        "planned_entries": [
            {
                "plan_entry_id": "campaign-plan::step2-selected::arch::mapping-1",
                "queue_entry_id": "step2-selected::arch::mapping-1",
                "candidate_id": "arch::mapping-1",
                "mapping_candidate_id": "mapping-1",
                "architecture_id": "arch",
                "design_point_id": "dp-1",
                "mapping_id": "map-1",
                "admission_source": "step2/step3_simulation_queue.json",
                "execution_allowed": True,
                "promoted_for_simulation": True,
                "step2_screenable": True,
                "step3_evaluable": True,
                "simulation_eligible": True,
                "simulation_blockers": [],
                "claim_status": "legacy_pilot_only",
                "broad_evidence_run": False,
                "release_completion_eligible": False,
                "trusted_final_claim": False,
            }
        ],
        "deferred_entries": [
            {
                "top_k_entry_id": "top-k::2",
                "candidate_id": "mapping-2",
                "mapping_candidate_id": "mapping-2",
                "admission_required_before_execution": "step2/step3_simulation_queue.json",
                "execution_allowed": False,
                "provenance_only": True,
                "release_completion_eligible": False,
                "trusted_final_claim": False,
            }
        ],
        "selected_entry_only": True,
        "broad_evidence_run": False,
        "admission_control": {"hidden_evidence_fanout_allowed": False},
    }


def _search_plan() -> dict:
    return {
        "schema_version": "dse.step2.search_iteration_plan.v1",
        "campaign_id": "campaign",
        "workload_run_id": "workload",
        "trial_id": "trial",
        "next_step3_admission_queue_ref": "step2/step3_simulation_queue.json",
        "step3_admission_queue": "step2/step3_simulation_queue.json",
        "next_step3_admission_candidate_count": 2,
        "next_step3_admission_candidates": [
            {
                "candidate_id": "arch::mapping-1",
                "search_policy_candidate_id": "arch::mapping-1",
                "mapping_candidate_id": "mapping-1",
                "architecture_id": "arch",
                "parameter_hash": "sha256:param-1",
                "search_policy_parameter_hash": "sha256:param-1",
                "admission_required_before_execution": "step2/step3_simulation_queue.json",
                "execution_allowed": False,
                "trusted_final_claim": False,
                "release_completion_eligible": False,
            },
            {
                "candidate_id": "arch::mapping-2",
                "search_policy_candidate_id": "arch::mapping-2",
                "mapping_candidate_id": "mapping-2",
                "architecture_id": "arch",
                "parameter_hash": "sha256:param-2",
                "search_policy_parameter_hash": "sha256:param-2",
                "admission_required_before_execution": "step2/step3_simulation_queue.json",
                "execution_allowed": False,
                "trusted_final_claim": False,
                "release_completion_eligible": False,
            },
        ],
    }


def _admission_refs() -> dict:
    return {
        "campaign_evaluation_plan_ref": "campaign_evaluation_plan.json",
        "search_iteration_plan_ref": "search_iteration_plan.json",
        "search_iteration_plan_validation_ref": "search_iteration_plan_validation.json",
        "step3_simulation_queue_ref": "step2/step3_simulation_queue.json",
    }


def test_valid_step3_queue_validation_passes_and_reports_pending_search_candidates():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_evaluation_plan=_campaign_plan(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            **_admission_refs(),
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 0,
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is True
    assert validation["status"] == "passed"
    assert validation["error_count"] == 0
    assert validation["summary"]["queue_entry_count"] == 1
    assert validation["summary"]["planned_entry_count"] == 1
    assert validation["summary"]["planned_entries_backed_by_queue"] == 1
    assert validation["summary"]["search_admission_candidate_count"] == 2
    assert validation["summary"]["materialized_search_admission_candidate_count"] == 1
    assert validation["summary"]["pending_search_admission_candidate_count"] == 1
    assert validation["pending_search_admission_candidate_ids"] == ["arch::mapping-2"]
    assert validation["campaign_scope_validation"]["valid"] is True
    assert (
        validation["summary"]["queue_entry_validity_field_coverage"]
        ["entries_missing_validity_fields"]
        == 0
    )
    assert not any(
        warning["field"] == "step3_simulation_queue.entries[0].validity_fields"
        for warning in validation["warnings"]
    )
    assert validation["trusted_final_claim"] is False


def test_search_admission_broad_alias_with_different_parameter_hash_stays_pending():
    queue = _queue()
    queue["entries"][0]["parameter_hash"] = "sha256:" + "a" * 64
    queue["entries"][0]["mapping_parameter_hash"] = "sha256:" + "b" * 64
    queue["entries"][0]["candidate_identity_policy"] = "stable_mapping_parameters_hash_sidecar"

    search_plan = _search_plan()
    search_plan["next_step3_admission_candidates"][0].update(
        {
            "candidate_id": "search-policy::mapping-1",
            "search_policy_candidate_id": "search-policy::mapping-1",
            "parameter_hash": "sha256:" + "c" * 64,
            "search_policy_parameter_hash": "sha256:" + "c" * 64,
            "mapping_parameter_hash": "sha256:" + "b" * 64,
            "candidate_identity_policy": "stable_problem_policy_parameter_hash",
        }
    )

    validation = validate_step3_admission_queue(
        step3_simulation_queue=queue,
        campaign_evaluation_plan=_campaign_plan(),
        search_iteration_plan=search_plan,
        campaign_search_admission_plan={
            **_admission_refs(),
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 0,
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is True
    assert validation["summary"]["materialized_search_admission_candidate_count"] == 0
    assert validation["summary"]["pending_search_admission_candidate_count"] == 2


def test_validator_blocks_scheduled_queue_missing_validity_fields():
    queue = _queue()
    del queue["entries"][0]["simulation_eligible"]

    validation = validate_step3_admission_queue(step3_simulation_queue=queue)

    assert validation["valid"] is False
    assert (
        validation["summary"]["queue_entry_validity_field_coverage"]
        ["entries_missing_validity_fields"]
        == 1
    )
    assert validation["summary"]["queue_entry_validity_field_coverage"]["missing_fields_by_entry"] == [
        {
            "entry_index": 0,
            "queue_entry_id": "step2-selected::arch::mapping-1",
            "candidate_id": "arch::mapping-1",
            "missing_fields": ["simulation_eligible"],
        }
    ]
    assert any(
        error["field"] == "step3_simulation_queue.entries[0].validity_fields"
        and error.get("missing_fields") == ["simulation_eligible"]
        for error in validation["errors"]
    )


def test_queue_fixture_keeps_all_scheduled_validity_fields_explicit():
    entry = _queue()["entries"][0]

    assert all(field in entry for field in SCHEDULED_QUEUE_VALIDITY_FIELDS)


def test_validator_blocks_forged_campaign_evaluation_refs():
    campaign_plan = _campaign_plan()
    campaign_plan["step3_simulation_queue_ref"] = "forged/step3_simulation_queue.json"
    campaign_plan["top_k_candidate_queue_ref"] = "forged/top_k_candidate_queue.json"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_evaluation_plan=campaign_plan,
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_evaluation_plan.step3_simulation_queue_ref" in fields
    assert "campaign_evaluation_plan.top_k_candidate_queue_ref" in fields


def test_validator_blocks_forged_search_iteration_step3_refs():
    search_plan = _search_plan()
    search_plan["next_step3_admission_queue_ref"] = "forged/step3_simulation_queue.json"
    search_plan["step3_admission_queue"] = "forged/step3_simulation_queue.json"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=search_plan,
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "search_iteration_plan.next_step3_admission_queue_ref" in fields
    assert "search_iteration_plan.step3_admission_queue" in fields


def test_validator_blocks_forged_campaign_search_admission_refs():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_search_admission_plan={
            "campaign_evaluation_plan_ref": "forged_campaign_evaluation_plan.json",
            "search_iteration_plan_ref": "forged_search_iteration_plan.json",
            "search_iteration_plan_validation_ref": "forged_search_iteration_plan_validation.json",
            "step3_simulation_queue_ref": "forged/step3_simulation_queue.json",
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 0,
            "deferred_candidates": [],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_search_admission_plan.campaign_evaluation_plan_ref" in fields
    assert "campaign_search_admission_plan.search_iteration_plan_ref" in fields
    assert "campaign_search_admission_plan.search_iteration_plan_validation_ref" in fields
    assert "campaign_search_admission_plan.step3_simulation_queue_ref" in fields


def test_validator_requires_campaign_search_admission_refs():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 0,
            "deferred_candidates": [],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_search_admission_plan.campaign_evaluation_plan_ref" in fields
    assert "campaign_search_admission_plan.search_iteration_plan_ref" in fields
    assert "campaign_search_admission_plan.search_iteration_plan_validation_ref" in fields
    assert "campaign_search_admission_plan.step3_simulation_queue_ref" in fields


def test_validator_requires_campaign_search_admission_status():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_search_admission_plan={
            **_admission_refs(),
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 0,
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_search_admission_plan.admission_status"
        and "recognized admission_status" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_planned_entries_not_backed_by_queue():
    campaign_plan = _campaign_plan()
    campaign_plan["planned_entries"][0]["queue_entry_id"] = "missing-entry"
    campaign_plan["planned_entries"][0]["candidate_id"] = "missing-candidate"
    campaign_plan["planned_entries"][0]["mapping_candidate_id"] = "missing-mapping"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_evaluation_plan=campaign_plan,
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_evaluation_plan.planned_entries[0]"
        for error in validation["errors"]
    )


def test_validator_blocks_unplanned_step3_queue_entries_under_campaign_plan():
    queue = _queue()
    extra = dict(queue["entries"][0])
    extra.update(
        {
            "queue_entry_id": "step2-selected::arch::mapping-2",
            "candidate_id": "arch::mapping-2",
            "mapping_candidate_id": "mapping-2",
            "design_point_id": "dp-2",
            "mapping_id": "map-2",
        }
    )
    queue["entries"].append(extra)
    queue["entry_count"] = 2

    validation = validate_step3_admission_queue(
        step3_simulation_queue=queue,
        campaign_evaluation_plan=_campaign_plan(),
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "step3_simulation_queue.entries[1]"
        and "enumerate every materialized Step3 queue row" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_duplicate_planned_entry_aliases():
    campaign_plan = _campaign_plan()
    duplicate = dict(campaign_plan["planned_entries"][0])
    duplicate["plan_entry_id"] = "campaign-plan::duplicate"
    campaign_plan["planned_entries"].append(duplicate)
    campaign_plan["planned_entry_count"] = 2

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_evaluation_plan=campaign_plan,
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_evaluation_plan.planned_entries.aliases"
        and "mapping-1" in error.get("duplicates", {})
        for error in validation["errors"]
    )


def test_validator_blocks_alias_backed_planned_entry_identity_rebinding():
    campaign_plan = _campaign_plan()
    campaign_plan["planned_entries"][0]["queue_entry_id"] = "forged-entry"
    campaign_plan["planned_entries"][0]["candidate_id"] = "forged-candidate"
    campaign_plan["planned_entries"][0]["architecture_id"] = "forged-arch"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_evaluation_plan=campaign_plan,
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_evaluation_plan.planned_entries[0].queue_entry_id" in fields
    assert "campaign_evaluation_plan.planned_entries[0].candidate_id" in fields
    assert "campaign_evaluation_plan.planned_entries[0].architecture_id" in fields


def test_validator_blocks_planned_entry_missing_validity_fields():
    campaign_plan = _campaign_plan()
    del campaign_plan["planned_entries"][0]["simulation_eligible"]

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_evaluation_plan=campaign_plan,
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_evaluation_plan.planned_entries[0].validity_fields"
        and error.get("missing_fields") == ["simulation_eligible"]
        for error in validation["errors"]
    )


def test_validator_blocks_planned_entry_validity_rebinding():
    campaign_plan = _campaign_plan()
    campaign_plan["planned_entries"][0]["claim_status"] = "campaign_admission_only"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_evaluation_plan=campaign_plan,
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_evaluation_plan.planned_entries[0].claim_status"
        and "must match the materialized queue entry" in error["message"]
        and error.get("expected") == "legacy_pilot_only"
        and error.get("actual") == "campaign_admission_only"
        for error in validation["errors"]
    )


def test_validator_blocks_duplicate_campaign_deferred_entry_aliases():
    campaign_plan = _campaign_plan()
    duplicate = dict(campaign_plan["deferred_entries"][0])
    duplicate["top_k_entry_id"] = "top-k::duplicate"
    campaign_plan["deferred_entries"].append(duplicate)

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_evaluation_plan=campaign_plan,
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_evaluation_plan.deferred_entries.aliases"
        and "mapping-2" in error.get("duplicates", {})
        for error in validation["errors"]
    )


def test_validator_blocks_campaign_deferred_entry_claim_and_queue_state():
    campaign_plan = _campaign_plan()
    deferred = campaign_plan["deferred_entries"][0]
    deferred["trusted_final_claim"] = True
    deferred["provenance_only"] = False
    deferred["queue_state"] = "scheduled_for_simulation"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_evaluation_plan=campaign_plan,
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_evaluation_plan.deferred_entries[0].trusted_final_claim" in fields
    assert "campaign_evaluation_plan.deferred_entries[0].provenance_only" in fields
    assert "campaign_evaluation_plan.deferred_entries[0].queue_state" in fields


def test_validator_blocks_alias_backed_search_admission_identity_rebinding():
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidates"][0]["architecture_id"] = "forged-arch"
    search_plan["next_step3_admission_candidates"][0]["design_point_id"] = "forged-dp"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=search_plan,
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "search_iteration_plan.next_step3_admission_candidates[0].architecture_id" in fields
    assert "search_iteration_plan.next_step3_admission_candidates[0].design_point_id" in fields


def test_validator_blocks_nested_search_admission_identity_rebinding():
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidates"][0]["candidate_refs"] = {
        "architecture_id": "forged-arch",
        "mapping_candidate_id": "mapping-1",
    }

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=search_plan,
    )

    assert validation["valid"] is False
    assert any(
        error["field"]
        == "search_iteration_plan.next_step3_admission_candidates[0].architecture_id"
        for error in validation["errors"]
    )


def test_validator_blocks_nested_search_admission_candidate_identity_rebinding():
    search_plan = _search_plan()
    identity = {"architecture_id": "arch", "mapping_candidate_id": "mapping-1"}
    search_plan["next_step3_admission_candidates"][0]["candidate_identity"] = identity
    search_plan["next_step3_admission_candidates"][0]["provenance"] = {
        "candidate_identity": {
            "architecture_id": "forged-arch",
            "mapping_candidate_id": "mapping-1",
        }
    }

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=search_plan,
    )

    assert validation["valid"] is False
    assert any(
        error["field"]
        == "search_iteration_plan.next_step3_admission_candidates[0].candidate_identity"
        for error in validation["errors"]
    )


def test_validator_blocks_ambiguous_search_admission_candidate_aliases():
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidates"][1]["mapping_candidate_id"] = "mapping-1"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=search_plan,
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "search_iteration_plan.next_step3_admission_candidates.aliases"
        and "mapping-1" in error.get("duplicates", {})
        for error in validation["errors"]
    )


def test_validator_blocks_forged_search_admission_row_authority_ref():
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidates"][1][
        "admission_required_before_execution"
    ] = "forged/step3_simulation_queue.json"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=search_plan,
    )

    assert validation["valid"] is False
    assert any(
        error["field"]
        == "search_iteration_plan.next_step3_admission_candidates[1].admission_required_before_execution"
        and error.get("expected") == "step2/step3_simulation_queue.json"
        and error.get("actual") == "forged/step3_simulation_queue.json"
        for error in validation["errors"]
    )


def test_validator_blocks_missing_search_admission_row_authority_ref():
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidates"][1].pop(
        "admission_required_before_execution"
    )

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=search_plan,
    )

    assert validation["valid"] is False
    assert any(
        error["field"]
        == "search_iteration_plan.next_step3_admission_candidates[1].admission_required_before_execution"
        and error.get("expected") == "step2/step3_simulation_queue.json"
        for error in validation["errors"]
    )


def test_validator_blocks_contradictory_scheduled_queue_validity_fields():
    queue = _queue()
    queue["entries"][0].update(
        {
            "step2_screenable": False,
            "step3_evaluable": False,
            "simulation_eligible": False,
            "simulation_blockers": ["not_eligible"],
            "claim_status": "release_completion_eligible",
            "admission_source": "step2/top_k_candidate_queue.json",
        }
    )

    validation = validate_step3_admission_queue(step3_simulation_queue=queue)
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "step3_simulation_queue.entries[0].step2_screenable" in fields
    assert "step3_simulation_queue.entries[0].step3_evaluable" in fields
    assert "step3_simulation_queue.entries[0].simulation_eligible" in fields
    assert "step3_simulation_queue.entries[0].simulation_blockers" in fields
    assert "step3_simulation_queue.entries[0].claim_status" in fields
    assert "step3_simulation_queue.entries[0].admission_source" in fields


def test_validator_blocks_promoted_queue_entry_without_scheduled_state():
    queue = _queue()
    queue["entries"][0]["queue_state"] = "blocked_not_promoted"

    validation = validate_step3_admission_queue(step3_simulation_queue=queue)

    assert validation["valid"] is False
    assert any(
        error["field"] == "step3_simulation_queue.entries[0].queue_state"
        and "promoted queue entries must be scheduled_for_simulation" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_mixed_campaign_scope_between_campaign_and_search_plan():
    search_plan = _search_plan()
    search_plan["trial_id"] = "trial-forged"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_evaluation_plan=_campaign_plan(),
        search_iteration_plan=search_plan,
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_scope.trial_id" in fields
    scope_validation = validation["campaign_scope_validation"]
    assert scope_validation["valid"] is False
    assert scope_validation["conflict_count"] == 1
    assert scope_validation["conflicts"][0]["field"] == "trial_id"


def test_validator_blocks_mixed_campaign_scope_between_queue_and_campaign_plan():
    queue = _queue()
    queue["campaign_id"] = "campaign-forged"
    queue["workload_run_id"] = "workload-forged"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=queue,
        campaign_evaluation_plan=_campaign_plan(),
        search_iteration_plan=_search_plan(),
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_scope.campaign_id" in fields
    assert "campaign_scope.workload_run_id" in fields
    assert validation["campaign_scope_validation"]["conflict_count"] == 2


def test_validator_blocks_row_local_campaign_scope_rebinding():
    queue = _queue()
    queue["entries"][0]["candidate_refs"] = {"campaign_id": "campaign-forged"}
    campaign_plan = _campaign_plan()
    campaign_plan["planned_entries"][0]["workload_run_id"] = "workload-forged"
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidates"][0]["parameters"] = {
        "trial_id": "trial-forged"
    }

    validation = validate_step3_admission_queue(
        step3_simulation_queue=queue,
        campaign_evaluation_plan=campaign_plan,
        search_iteration_plan=search_plan,
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 1,
            "deferred_candidates": [
                {
                    "search_policy_candidate_id": "arch::mapping-2",
                    "search_policy_rank": 2,
                    "status": "deferred_budget_not_materialized",
                    "execution_allowed": False,
                    "not_a_step3_queue_entry": True,
                    "candidate_refs": {"campaign_id": "campaign-forged"},
                }
            ],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert validation["campaign_scope_validation"]["valid"] is False
    assert validation["campaign_scope_validation"]["row_scope_error_count"] == 4
    assert "step3_simulation_queue.entries[0].campaign_id" in fields
    assert "campaign_evaluation_plan.planned_entries[0].workload_run_id" in fields
    assert "search_iteration_plan.next_step3_admission_candidates[0].trial_id" in fields
    assert "campaign_search_admission_plan.deferred_candidates[0].campaign_id" in fields


def test_validator_blocks_row_scope_without_top_level_campaign_scope():
    queue = _queue()
    for field in ("campaign_id", "workload_run_id", "trial_id"):
        queue.pop(field, None)
    queue["entries"][0]["candidate_refs"] = {"campaign_id": "row-campaign"}

    validation = validate_step3_admission_queue(step3_simulation_queue=queue)
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert validation["campaign_scope_validation"]["valid"] is False
    assert validation["campaign_scope_validation"]["row_scope_error_count"] == 1
    assert "step3_simulation_queue.entries[0].campaign_id" in fields
    row_scope_error = validation["campaign_scope_validation"]["row_scope_errors"][0]
    assert row_scope_error["observed_values"] == ["row-campaign"]
    assert row_scope_error["sources_by_value"] == {
        "row-campaign": ["candidate_refs"]
    }


def test_validator_blocks_identity_and_metric_scope_rebinding():
    queue = _queue()
    queue["entries"][0]["candidate_identity"] = {"campaign_id": "campaign-forged"}
    campaign_plan = _campaign_plan()
    campaign_plan["planned_entries"][0]["metrics"] = {
        "workload_run_id": "workload-forged"
    }
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidates"][0]["metrics"] = {
        "trial_id": "trial-forged"
    }

    validation = validate_step3_admission_queue(
        step3_simulation_queue=queue,
        campaign_evaluation_plan=campaign_plan,
        search_iteration_plan=search_plan,
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 1,
            "deferred_candidates": [
                {
                    "search_policy_candidate_id": "arch::mapping-2",
                    "status": "deferred_budget_not_materialized",
                    "execution_allowed": False,
                    "not_a_step3_queue_entry": True,
                    "observed_metrics": {"campaign_id": "campaign-forged"},
                }
            ],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert validation["campaign_scope_validation"]["valid"] is False
    assert validation["campaign_scope_validation"]["row_scope_error_count"] == 4
    assert "step3_simulation_queue.entries[0].campaign_id" in fields
    assert "campaign_evaluation_plan.planned_entries[0].workload_run_id" in fields
    assert "search_iteration_plan.next_step3_admission_candidates[0].trial_id" in fields
    assert "campaign_search_admission_plan.deferred_candidates[0].campaign_id" in fields


def test_validator_blocks_row_scope_direct_nested_disagreement():
    queue = _queue()
    queue["entries"][0]["campaign_id"] = "campaign"
    queue["entries"][0]["candidate_refs"] = {"campaign_id": "campaign-nested"}

    validation = validate_step3_admission_queue(step3_simulation_queue=queue)

    assert validation["valid"] is False
    assert validation["campaign_scope_validation"]["valid"] is False
    assert validation["campaign_scope_validation"]["row_scope_error_count"] == 2
    assert any(
        error["field"] == "step3_simulation_queue.entries[0].campaign_id"
        and "direct and nested" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_non_mapping_rows_in_admission_lists():
    campaign_plan = _campaign_plan()
    campaign_plan["planned_entries"].append("not-a-planned-entry")
    campaign_plan["planned_entry_count"] = 1
    campaign_plan["deferred_entries"].append(["not-a-deferred-entry"])
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidates"].append("not-a-candidate")
    search_plan["next_step3_admission_candidate_count"] = 2

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_evaluation_plan=campaign_plan,
        search_iteration_plan=search_plan,
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": ["not-a-write-entry"],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": ["not-a-request"],
            "deferred_candidate_count": 0,
            "deferred_candidates": ["not-a-deferred-candidate"],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_evaluation_plan.planned_entries[1]" in fields
    assert "campaign_evaluation_plan.deferred_entries[1]" in fields
    assert "search_iteration_plan.next_step3_admission_candidates[2]" in fields
    assert "campaign_search_admission_plan.materialized_step3_queue_entries[0]" in fields
    assert "campaign_search_admission_plan.step2_iteration_requests[0]" in fields
    assert "campaign_search_admission_plan.deferred_candidates[0]" in fields


def test_validator_blocks_non_list_admission_containers():
    queue = _queue()
    queue["entries"] = "not-a-list"
    queue["entry_count"] = 0
    campaign_plan = _campaign_plan()
    campaign_plan["planned_entries"] = "not-a-list"
    campaign_plan["planned_entry_count"] = 0
    campaign_plan["deferred_entries"] = "not-a-list"
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidates"] = "not-a-list"
    search_plan["next_step3_admission_candidate_count"] = 0

    validation = validate_step3_admission_queue(
        step3_simulation_queue=queue,
        campaign_evaluation_plan=campaign_plan,
        search_iteration_plan=search_plan,
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": "not-a-list",
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": "not-a-list",
            "deferred_candidate_count": 0,
            "deferred_candidates": "not-a-list",
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "step3_simulation_queue.entries" in fields
    assert "campaign_evaluation_plan.planned_entries" in fields
    assert "campaign_evaluation_plan.deferred_entries" in fields
    assert "search_iteration_plan.next_step3_admission_candidates" in fields
    assert "campaign_search_admission_plan.materialized_step3_queue_entries" in fields
    assert "campaign_search_admission_plan.step2_iteration_requests" in fields
    assert "campaign_search_admission_plan.deferred_candidates" in fields


def test_validator_requires_canonical_count_fields():
    queue = _queue()
    del queue["entry_count"]
    campaign_plan = _campaign_plan()
    del campaign_plan["planned_entry_count"]
    search_plan = _search_plan()
    del search_plan["next_step3_admission_candidate_count"]

    validation = validate_step3_admission_queue(
        step3_simulation_queue=queue,
        campaign_evaluation_plan=campaign_plan,
        search_iteration_plan=search_plan,
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "materialized_step3_queue_entries": [],
            "step2_iteration_requests": [],
            "deferred_candidates": [],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "step3_simulation_queue.entry_count" in fields
    assert "campaign_evaluation_plan.planned_entry_count" in fields
    assert "search_iteration_plan.next_step3_admission_candidate_count" in fields
    assert "campaign_search_admission_plan.admitted_entry_count" in fields
    assert "campaign_search_admission_plan.materialized_step3_queue_entry_count" in fields
    assert "campaign_search_admission_plan.step2_iteration_request_count" in fields
    assert "campaign_search_admission_plan.deferred_candidate_count" in fields


def test_validator_reports_malformed_count_fields_without_crashing():
    queue = _queue()
    queue["entry_count"] = True
    campaign_plan = _campaign_plan()
    campaign_plan["planned_entry_count"] = True
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidate_count"] = "not-an-integer"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=queue,
        campaign_evaluation_plan=campaign_plan,
        search_iteration_plan=search_plan,
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": "not-an-integer",
            "materialized_step3_queue_entry_count": False,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": False,
            "step2_iteration_requests": [],
            "deferred_candidate_count": False,
            "deferred_candidates": [],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "step3_simulation_queue.entry_count" in fields
    assert "campaign_evaluation_plan.planned_entry_count" in fields
    assert "search_iteration_plan.next_step3_admission_candidate_count" in fields
    assert "campaign_search_admission_plan.admitted_entry_count" in fields
    assert "campaign_search_admission_plan.materialized_step3_queue_entry_count" in fields
    assert "campaign_search_admission_plan.step2_iteration_request_count" in fields
    assert "campaign_search_admission_plan.deferred_candidate_count" in fields


def test_validator_rejects_float_string_and_negative_count_values():
    queue = _queue()
    queue["entry_count"] = 1.9
    campaign_plan = _campaign_plan()
    campaign_plan["planned_entry_count"] = "1"
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidate_count"] = 2.0

    validation = validate_step3_admission_queue(
        step3_simulation_queue=queue,
        campaign_evaluation_plan=campaign_plan,
        search_iteration_plan=search_plan,
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": -1,
            "materialized_step3_queue_entry_count": "0",
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0.0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": "0",
            "deferred_candidates": [],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "step3_simulation_queue.entry_count" in fields
    assert "campaign_evaluation_plan.planned_entry_count" in fields
    assert "search_iteration_plan.next_step3_admission_candidate_count" in fields
    assert "campaign_search_admission_plan.admitted_entry_count" in fields
    assert "campaign_search_admission_plan.materialized_step3_queue_entry_count" in fields
    assert "campaign_search_admission_plan.step2_iteration_request_count" in fields
    assert "campaign_search_admission_plan.deferred_candidate_count" in fields


def test_validator_blocks_invalid_campaign_materialized_write_entries():
    bad_entry = dict(_queue()["entries"][0])
    bad_entry.update(
        {
            "admission_source": "forged_authority.json",
            "queue_state": "executed",
            "promoted_for_simulation": False,
            "execution_allowed": True,
            "provenance_only": True,
        }
    )

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        campaign_search_admission_plan={
            "admission_status": "step3_queue_write_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 1,
            "materialized_step3_queue_entries": [bad_entry],
            "step2_iteration_requests": [],
            "deferred_candidates": [],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_search_admission_plan.materialized_step3_queue_entries[0]" in fields
    assert (
        "campaign_search_admission_plan.materialized_step3_queue_entries[0].execution_allowed"
        in fields
    )
    assert (
        "campaign_search_admission_plan.materialized_step3_queue_entries[0].admission_source"
        in fields
    )
    assert "campaign_search_admission_plan.materialized_step3_queue_entries[0].queue_state" in fields
    assert (
        "campaign_search_admission_plan.materialized_step3_queue_entries[0].promoted_for_simulation"
        in fields
    )


def test_validator_blocks_campaign_materialized_write_entry_without_search_backing():
    forged_entry = dict(_queue()["entries"][0])
    forged_entry.update(
        {
            "queue_entry_id": "step2-selected::forged::mapping-x",
            "candidate_id": "forged::mapping-x",
            "mapping_candidate_id": "mapping-x",
            "architecture_id": "forged-arch",
            "admission_source": "campaign_search_admission_plan.json",
            "execution_allowed": False,
            "not_a_step3_queue_entry": False,
            "provenance_only": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        }
    )

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "step3_queue_write_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 1,
            "materialized_step3_queue_entries": [forged_entry],
            "step2_iteration_requests": [],
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_search_admission_plan.materialized_step3_queue_entries[0]"
        and "not backed by a search_iteration_plan admission candidate" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_campaign_materialized_write_entry_identity_rebinding():
    rebound_entry = dict(_queue()["entries"][0])
    rebound_entry.update(
        {
            "admission_source": "campaign_search_admission_plan.json",
            "architecture_id": "forged-arch",
            "execution_allowed": False,
            "not_a_step3_queue_entry": False,
            "provenance_only": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        }
    )

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "step3_queue_write_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 1,
            "materialized_step3_queue_entries": [rebound_entry],
            "step2_iteration_requests": [],
            "deferred_candidates": [],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_search_admission_plan.materialized_step3_queue_entries[0].architecture_id" in fields


def test_validator_accepts_search_backed_campaign_materialized_write_with_validity_fields():
    materialized_entry = dict(_queue()["entries"][0])
    materialized_entry.update(
        {
            "admission_source": "campaign_search_admission_plan.json",
            "claim_status": "campaign_admission_only",
            "step2_screenable": True,
            "step3_evaluable": True,
            "simulation_eligible": True,
            "simulation_blockers": [],
            "admission_required_before_execution": "step2/step3_simulation_queue.json",
            "execution_allowed": False,
            "not_a_step3_queue_entry": False,
            "provenance_only": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        }
    )

    validation = validate_step3_admission_queue(
        step3_simulation_queue={
            "schema_version": "dse.step3.simulation_queue.v1",
            "queue_mode": "selected-entry-only",
            "entries": [],
            "entry_count": 0,
        },
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            **_admission_refs(),
            "admission_status": "step3_queue_write_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 1,
            "materialized_step3_queue_entries": [materialized_entry],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 0,
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is True


def test_validator_blocks_campaign_materialized_write_nested_identity_rebinding():
    materialized_entry = dict(_queue()["entries"][0])
    materialized_entry.update(
        {
            "admission_source": "campaign_search_admission_plan.json",
            "claim_status": "campaign_admission_only",
            "step2_screenable": True,
            "step3_evaluable": True,
            "simulation_eligible": True,
            "simulation_blockers": [],
            "execution_allowed": False,
            "not_a_step3_queue_entry": False,
            "provenance_only": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "candidate_refs": {
                "architecture_id": "forged-arch",
                "mapping_candidate_id": "mapping-1",
            },
        }
    )

    validation = validate_step3_admission_queue(
        step3_simulation_queue={
            "schema_version": "dse.step3.simulation_queue.v1",
            "queue_mode": "selected-entry-only",
            "entries": [],
            "entry_count": 0,
        },
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "step3_queue_write_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 1,
            "materialized_step3_queue_entries": [materialized_entry],
            "step2_iteration_requests": [],
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is False
    assert any(
        error["field"]
        == "campaign_search_admission_plan.materialized_step3_queue_entries[0].architecture_id"
        for error in validation["errors"]
    )


def test_validator_blocks_campaign_materialized_write_nested_candidate_identity_rebinding():
    identity = {"architecture_id": "arch", "mapping_candidate_id": "mapping-1"}
    materialized_entry = dict(_queue()["entries"][0])
    materialized_entry.update(
        {
            "admission_source": "campaign_search_admission_plan.json",
            "claim_status": "campaign_admission_only",
            "step2_screenable": True,
            "step3_evaluable": True,
            "simulation_eligible": True,
            "simulation_blockers": [],
            "execution_allowed": False,
            "not_a_step3_queue_entry": False,
            "provenance_only": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "candidate_identity": identity,
            "provenance": {
                "candidate_identity": {
                    "architecture_id": "forged-arch",
                    "mapping_candidate_id": "mapping-1",
                }
            },
        }
    )
    search_plan = _search_plan()
    search_plan["next_step3_admission_candidates"][0]["candidate_identity"] = identity

    validation = validate_step3_admission_queue(
        step3_simulation_queue={
            "schema_version": "dse.step3.simulation_queue.v1",
            "queue_mode": "selected-entry-only",
            "entries": [],
            "entry_count": 0,
        },
        search_iteration_plan=search_plan,
        campaign_search_admission_plan={
            "admission_status": "step3_queue_write_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 1,
            "materialized_step3_queue_entries": [materialized_entry],
            "step2_iteration_requests": [],
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is False
    assert any(
        error["field"]
        == "campaign_search_admission_plan.materialized_step3_queue_entries[0].candidate_identity"
        for error in validation["errors"]
    )


def test_validator_blocks_materialized_write_duplicate_existing_queue_alias():
    materialized_entry = dict(_queue()["entries"][0])
    materialized_entry.update(
        {
            "admission_source": "campaign_search_admission_plan.json",
            "claim_status": "campaign_admission_only",
            "step2_screenable": True,
            "step3_evaluable": True,
            "simulation_eligible": True,
            "simulation_blockers": [],
            "execution_allowed": False,
            "not_a_step3_queue_entry": False,
            "provenance_only": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        }
    )

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "step3_queue_write_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 1,
            "materialized_step3_queue_entries": [materialized_entry],
            "step2_iteration_requests": [],
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_search_admission_plan.materialized_step3_queue_entries[0]"
        and "existing Step3 queue" in error["message"]
        and "mapping-1" in error.get("shared_aliases", [])
        for error in validation["errors"]
    )


def test_validator_blocks_campaign_materialized_write_missing_validity_fields():
    materialized_entry = dict(_queue()["entries"][0])
    for field in SCHEDULED_QUEUE_VALIDITY_FIELDS:
        materialized_entry.pop(field, None)
    materialized_entry.update(
        {
            "admission_source": "campaign_search_admission_plan.json",
            "execution_allowed": False,
            "not_a_step3_queue_entry": False,
            "provenance_only": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        }
    )

    validation = validate_step3_admission_queue(
        step3_simulation_queue={
            "schema_version": "dse.step3.simulation_queue.v1",
            "queue_mode": "selected-entry-only",
            "entries": [],
            "entry_count": 0,
        },
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "step3_queue_write_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 1,
            "materialized_step3_queue_entries": [materialized_entry],
            "step2_iteration_requests": [],
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_search_admission_plan.materialized_step3_queue_entries[0].validity_fields"
        and {
            "step2_screenable",
            "step3_evaluable",
            "simulation_eligible",
            "simulation_blockers",
            "claim_status",
        }.issubset(set(error.get("missing_fields", [])))
        for error in validation["errors"]
    )


def test_validator_accepts_search_backed_step2_materialization_request():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            **_admission_refs(),
            "admission_status": "step2_materialization_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 1,
            "step2_iteration_requests": [
                {
                    "request_id": "step2-materialize::mapping-2",
                    "requested_action": "materialize_step2_artifacts_for_step3_queue",
                    "search_policy_candidate_id": "arch::mapping-2",
                    "mapping_candidate_id": "mapping-2",
                    "architecture_id": "arch",
                    "search_policy_parameter_hash": "sha256:param-2",
                    "admission_required_before_execution": "step2/step3_simulation_queue.json",
                    "materialization_status": "requested_pending_step2_writer",
                    "not_a_step3_queue_entry": True,
                    "execution_allowed": False,
                    "trusted_final_claim": False,
                    "release_completion_eligible": False,
                    "deliverable_complete": False,
                }
            ],
            "deferred_candidate_count": 0,
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is True


def test_validator_blocks_step2_materialization_request_count_and_status_mismatch():
    request = {
        "request_id": "step2-materialize::mapping-2",
        "requested_action": "materialize_step2_artifacts_for_step3_queue",
        "search_policy_candidate_id": "arch::mapping-2",
        "mapping_candidate_id": "mapping-2",
        "architecture_id": "arch",
        "search_policy_parameter_hash": "sha256:param-2",
        "materialization_status": "requested_pending_step2_writer",
        "not_a_step3_queue_entry": True,
        "execution_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
    }

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            **_admission_refs(),
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 2,
            "step2_iteration_requests": [request],
            "deferred_candidates": [],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_search_admission_plan.step2_iteration_request_count" in fields
    assert "campaign_search_admission_plan.admission_status" in fields


def test_validator_blocks_duplicate_step2_materialization_request_aliases():
    request = {
        "request_id": "step2-materialize::mapping-2",
        "requested_action": "materialize_step2_artifacts_for_step3_queue",
        "search_policy_candidate_id": "arch::mapping-2",
        "mapping_candidate_id": "mapping-2",
        "architecture_id": "arch",
        "search_policy_parameter_hash": "sha256:param-2",
        "materialization_status": "requested_pending_step2_writer",
        "not_a_step3_queue_entry": True,
        "execution_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
    }
    duplicate = dict(request)
    duplicate["request_id"] = "step2-materialize::mapping-2::duplicate"

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "step2_materialization_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 2,
            "step2_iteration_requests": [request, duplicate],
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_search_admission_plan.step2_iteration_requests.aliases"
        and "mapping-2" in error.get("duplicates", {})
        for error in validation["errors"]
    )


def test_validator_blocks_step2_materialization_status_without_requests():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "step2_materialization_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_search_admission_plan.admission_status"
        and "needs step2_iteration_requests" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_step2_materialization_request_masquerading_as_queue_row():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "step2_materialization_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 1,
            "step2_iteration_requests": [
                {
                    "request_id": "step2-materialize::mapping-2",
                    "requested_action": "write_step3_queue_entry_directly",
                    "search_policy_candidate_id": "arch::mapping-2",
                    "mapping_candidate_id": "mapping-2",
                    "architecture_id": "arch",
                    "search_policy_parameter_hash": "sha256:param-2",
                    "materialization_status": "already_materialized",
                    "queue_state": "scheduled_for_simulation",
                    "not_a_step3_queue_entry": False,
                    "execution_allowed": False,
                    "trusted_final_claim": False,
                    "release_completion_eligible": False,
                    "deliverable_complete": False,
                }
            ],
            "deferred_candidates": [],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_search_admission_plan.step2_iteration_requests[0].requested_action" in fields
    assert "campaign_search_admission_plan.step2_iteration_requests[0].materialization_status" in fields
    assert "campaign_search_admission_plan.step2_iteration_requests[0].not_a_step3_queue_entry" in fields
    assert "campaign_search_admission_plan.step2_iteration_requests[0].queue_state" in fields


def test_validator_blocks_unbacked_step2_materialization_request():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "step2_materialization_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_requests": [
                {
                    "request_id": "step2-materialize::forged",
                    "requested_action": "materialize_step2_artifacts_for_step3_queue",
                    "search_policy_candidate_id": "forged-candidate",
                    "mapping_candidate_id": "mapping-x",
                    "architecture_id": "forged-arch",
                    "materialization_status": "requested_pending_step2_writer",
                    "not_a_step3_queue_entry": True,
                    "execution_allowed": False,
                    "trusted_final_claim": False,
                    "release_completion_eligible": False,
                }
            ],
            "deferred_candidates": [],
        },
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_search_admission_plan.step2_iteration_requests[0]"
        and "not backed by a search_iteration_plan admission candidate" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_step2_materialization_request_identity_rebinding():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "step2_materialization_required",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_requests": [
                {
                    "request_id": "step2-materialize::mapping-2",
                    "requested_action": "materialize_step2_artifacts_for_step3_queue",
                    "search_policy_candidate_id": "arch::mapping-2",
                    "mapping_candidate_id": "mapping-2",
                    "architecture_id": "forged-arch",
                    "search_policy_parameter_hash": "sha256:param-2",
                    "materialization_status": "requested_pending_step2_writer",
                    "not_a_step3_queue_entry": True,
                    "execution_allowed": False,
                    "trusted_final_claim": False,
                    "release_completion_eligible": False,
                }
            ],
            "deferred_candidates": [],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_search_admission_plan.step2_iteration_requests[0].architecture_id" in fields


def test_validator_accepts_search_backed_deferred_candidate():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            **_admission_refs(),
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 1,
            "deferred_candidates": [
                {
                    "search_policy_candidate_id": "arch::mapping-2",
                    "search_policy_rank": 2,
                    "status": "deferred_budget_not_materialized",
                    "admission_required_before_execution": "step2/step3_simulation_queue.json",
                    "execution_allowed": False,
                    "not_a_step3_queue_entry": True,
                }
            ],
        },
    )

    assert validation["valid"] is True


def test_validator_blocks_campaign_rows_with_forged_authority_refs():
    materialized_entry = dict(_queue()["entries"][0])
    materialized_entry.update(
        {
            "admission_source": "campaign_search_admission_plan.json",
            "claim_status": "campaign_admission_only",
            "step2_screenable": True,
            "step3_evaluable": True,
            "simulation_eligible": True,
            "simulation_blockers": [],
            "admission_required_before_execution": "forged/step3_simulation_queue.json",
            "execution_allowed": False,
            "not_a_step3_queue_entry": False,
            "provenance_only": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        }
    )
    step2_request = {
        "request_id": "step2-materialize::mapping-2",
        "requested_action": "materialize_step2_artifacts_for_step3_queue",
        "search_policy_candidate_id": "arch::mapping-2",
        "mapping_candidate_id": "mapping-2",
        "architecture_id": "arch",
        "search_policy_parameter_hash": "sha256:param-2",
        "admission_required_before_execution": "forged/step3_simulation_queue.json",
        "materialization_status": "requested_pending_step2_writer",
        "not_a_step3_queue_entry": True,
        "execution_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
    }
    deferred_candidate = {
        "search_policy_candidate_id": "arch::mapping-2",
        "search_policy_rank": 2,
        "status": "deferred_budget_not_materialized",
        "admission_required_before_execution": "forged/step3_simulation_queue.json",
        "execution_allowed": False,
        "not_a_step3_queue_entry": True,
    }
    cases = [
        (
            "step3_queue_write_required",
            [materialized_entry],
            [],
            [],
            "campaign_search_admission_plan.materialized_step3_queue_entries[0].admission_required_before_execution",
        ),
        (
            "step2_materialization_required",
            [],
            [step2_request],
            [],
            "campaign_search_admission_plan.step2_iteration_requests[0].admission_required_before_execution",
        ),
        (
            "proposal_only",
            [],
            [],
            [deferred_candidate],
            "campaign_search_admission_plan.deferred_candidates[0].admission_required_before_execution",
        ),
    ]

    for status, materialized_entries, step2_requests, deferred_candidates, expected_field in cases:
        validation = validate_step3_admission_queue(
            step3_simulation_queue={
                "schema_version": "dse.step3.simulation_queue.v1",
                "queue_mode": "selected-entry-only",
                "entries": [],
                "entry_count": 0,
            },
            search_iteration_plan=_search_plan(),
            campaign_search_admission_plan={
                **_admission_refs(),
                "admission_status": status,
                "execution_allowed": False,
                "hidden_evidence_fanout_allowed": False,
                "broad_evidence_run": False,
                "trusted_final_claim": False,
                "release_completion_eligible": False,
                "admitted_entry_count": 0,
                "materialized_step3_queue_entry_count": len(materialized_entries),
                "materialized_step3_queue_entries": materialized_entries,
                "step2_iteration_request_count": len(step2_requests),
                "step2_iteration_requests": step2_requests,
                "deferred_candidate_count": len(deferred_candidates),
                "deferred_candidates": deferred_candidates,
            },
        )

        assert validation["valid"] is False
        assert any(
            error["field"] == expected_field
            and error.get("expected") == "step2/step3_simulation_queue.json"
            and error.get("actual") == "forged/step3_simulation_queue.json"
            for error in validation["errors"]
        )


def test_validator_blocks_deferred_candidate_without_search_backing():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 1,
            "deferred_candidates": [
                {
                    "search_policy_candidate_id": "forged-candidate",
                    "search_policy_rank": 2,
                    "status": "deferred_budget_not_materialized",
                    "execution_allowed": False,
                    "not_a_step3_queue_entry": True,
                }
            ],
        },
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_search_admission_plan.deferred_candidates[0]"
        and "not backed by a search_iteration_plan admission candidate" in error["message"]
        for error in validation["errors"]
    )


def test_validator_blocks_deferred_candidate_identity_rebinding():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 1,
            "deferred_candidates": [
                {
                    "search_policy_candidate_id": "arch::mapping-2",
                    "mapping_candidate_id": "mapping-2",
                    "architecture_id": "forged-arch",
                    "search_policy_rank": 2,
                    "status": "deferred_budget_not_materialized",
                    "execution_allowed": False,
                    "not_a_step3_queue_entry": True,
                }
            ],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_search_admission_plan.deferred_candidates[0].architecture_id" in fields


def test_validator_blocks_duplicate_deferred_candidate_aliases():
    candidate = {
        "search_policy_candidate_id": "arch::mapping-2",
        "search_policy_rank": 2,
        "status": "deferred_budget_not_materialized",
        "execution_allowed": False,
        "not_a_step3_queue_entry": True,
    }
    duplicate = dict(candidate)
    duplicate["search_policy_rank"] = 3

    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 2,
            "deferred_candidates": [candidate, duplicate],
        },
    )

    assert validation["valid"] is False
    assert any(
        error["field"] == "campaign_search_admission_plan.deferred_candidates.aliases"
        and "arch::mapping-2" in error.get("duplicates", {})
        for error in validation["errors"]
    )


def test_validator_blocks_deferred_candidate_count_and_queue_like_claims():
    validation = validate_step3_admission_queue(
        step3_simulation_queue=_queue(),
        search_iteration_plan=_search_plan(),
        campaign_search_admission_plan={
            "admission_status": "proposal_only",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 2,
            "deferred_candidates": [
                {
                    "search_policy_candidate_id": "arch::mapping-2",
                    "status": "deferred_budget_not_materialized",
                    "execution_allowed": True,
                    "not_a_step3_queue_entry": False,
                    "queue_state": "scheduled_for_simulation",
                    "trusted_final_claim": True,
                }
            ],
        },
    )
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "campaign_search_admission_plan.deferred_candidate_count" in fields
    assert "campaign_search_admission_plan.deferred_candidates[0].execution_allowed" in fields
    assert "campaign_search_admission_plan.deferred_candidates[0].not_a_step3_queue_entry" in fields
    assert "campaign_search_admission_plan.deferred_candidates[0].queue_state" in fields
    assert "campaign_search_admission_plan.deferred_candidates[0].trusted_final_claim" in fields


def test_validator_blocks_provenance_rows_and_claim_upgrades_in_queue():
    queue = _queue()
    queue["trusted_final_claim"] = True
    queue["entries"][0]["provenance_only"] = True
    queue["entries"][0]["execution_allowed"] = True

    validation = validate_step3_admission_queue(step3_simulation_queue=queue)
    fields = {error["field"] for error in validation["errors"]}

    assert validation["valid"] is False
    assert "step3_simulation_queue.trusted_final_claim" in fields
    assert "step3_simulation_queue.entries[0]" in fields
    assert "step3_simulation_queue.entries[0].execution_allowed" in fields


def test_validator_blocks_ambiguous_queue_aliases():
    queue = _queue()
    duplicate = dict(queue["entries"][0])
    duplicate["queue_entry_id"] = "step2-selected::arch::mapping-2"
    duplicate["candidate_id"] = "arch::mapping-2"
    duplicate["mapping_id"] = "map-2"
    queue["entries"].append(duplicate)
    queue["entry_count"] = 2

    validation = validate_step3_admission_queue(step3_simulation_queue=queue)

    assert validation["valid"] is False
    assert any(
        error["field"] == "step3_simulation_queue.entries.aliases"
        and "mapping-1" in error.get("duplicates", {})
        for error in validation["errors"]
    )


def test_cli_writes_status_and_returns_nonzero_on_invalid_queue(tmp_path):
    queue_path = tmp_path / "step3_simulation_queue.json"
    plan_path = tmp_path / "campaign_evaluation_plan.json"
    out_dir = tmp_path / "validation"
    queue_path.write_text(json.dumps(_queue(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    plan_path.write_text(json.dumps(_campaign_plan(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    ok = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/validate_step3_admission_queue.py",
            str(queue_path),
            "--campaign-evaluation-plan",
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
    assert (out_dir / "step3_admission_queue_validation.json").exists()
    assert (out_dir / "status.json").exists()

    queue = _queue()
    queue["entry_count"] = 2
    queue_path.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bad = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/validate_step3_admission_queue.py",
            str(queue_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    bad_validation = json.loads(bad.stdout)
    assert bad.returncode == 1
    assert bad_validation["valid"] is False
