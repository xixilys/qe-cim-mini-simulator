#!/usr/bin/env python3
"""Regression coverage for search feedback/replay audit summarization."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from dse_v2.contracts import ARTIFACT_CATALOG, SCHEMA_REGISTRY, validate_instance
from dse_v2.scripts.dse.audit_search_feedback_loop import (
    build_search_effectiveness_audit,
    build_search_loop_audit_summary,
)
from dse_v2.scripts.dse.run_materialized_handoff_sweep import _candidate_identity_aliases
from dse_v2.mapping.search_policy import (
    build_search_iteration_plan,
    search_checkpoint_from_iteration_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
AUDITOR = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "audit_search_feedback_loop.py"
AUDITOR_SCHEMA_IDS = {
    "dse.contract.search_feedback_closure_audit.v1",
    "dse.contract.search_replay_safety_audit.v1",
    "dse.contract.search_loop_audit_summary.v1",
    "dse.contract.search_effectiveness_audit.v1",
    "dse.step2.search_iteration_plan.v1",
}


def test_search_feedback_auditor_schema_ids_are_registry_complete():
    missing = sorted(AUDITOR_SCHEMA_IDS - set(SCHEMA_REGISTRY))

    assert missing == []


def _catalog_example(name: str) -> dict:
    for item in ARTIFACT_CATALOG:
        if item.canonical_name == name:
            return copy.deepcopy(dict(item.example))
    if name == "search_feedback_closure_audit.json":
        return {
            "schema_version": "dse.contract.search_feedback_closure_audit.v1",
            "status": "closed_for_next_iteration",
            "blocker_count": 0,
            "blockers": [],
            "executed_candidate_count": 1,
            "feedback_update_count": 1,
            "global_checks": {
                "execution_allowed": False,
                "hidden_evidence_fanout_allowed": False,
                "trusted_final_claim": False,
                "release_completion_eligible": False,
                "feedback_update_written": True,
            },
            "lineage": [
                {
                    "returncode": 0,
                    "selected_candidate_id": "candidate-001",
                    "selected_candidate_parameter_hash": "sha256:candidate-001",
                    "mapping_parameter_hash": "sha256:candidate-001",
                    "search_policy_parameter_hash": "sha256:candidate-001",
                    "request_parameter_hash": "sha256:candidate-001",
                    "request_mapping_parameter_hash": "sha256:candidate-001",
                    "request_search_policy_parameter_hash": "sha256:candidate-001",
                    "search_iteration_candidate_id": "candidate-001",
                    "search_iteration_parameter_hash": "sha256:candidate-001",
                    "run_dir": "child",
                    "source_materialized_dir": "step2/materialized_candidates/request-001",
                }
            ],
        }
    if name == "search_replay_safety_audit.json":
        return {
            "schema_version": "dse.contract.search_replay_safety_audit.v1",
            "status": "closed_for_next_iteration",
            "blocker_count": 0,
            "blockers": [],
            "global_checks": {
                "observed_feedback_not_re_requested": True,
                "campaign_plan_safe_to_execute_step3": False,
                "execution_allowed": False,
                "hidden_evidence_fanout_allowed": False,
                "trusted_final_claim": False,
                "release_completion_eligible": False,
            },
            "observed_feedback_alias_count": 1,
            "rejected_feedback_alias_count": 0,
            "observed_feedback_classification": [
                {
                    "alias": "candidate-001",
                    "aliases": ["candidate-001", "sha256:candidate-001"],
                    "parameter_hashes": ["sha256:candidate-001"],
                    "search_policy_parameter_hash": "sha256:candidate-001",
                    "mapping_parameter_hash": "sha256:candidate-001",
                }
            ],
            "campaign_step2_iteration_request_count": 1,
            "campaign_materialized_step3_entry_count": 0,
            "campaign_request_lineage": [
                {
                    "candidate_id": "candidate-next",
                    "request_parameter_hash": "sha256:candidate-next",
                    "request_search_policy_parameter_hash": "sha256:candidate-next",
                    "request_mapping_parameter_hash": "sha256:candidate-next",
                    "matched_search_candidate_id": "candidate-next",
                    "matched_search_candidate_parameter_hash": "sha256:candidate-next",
                }
            ],
        }
    if name == "search_iteration_plan.json":
        return {
            "schema_version": "dse.step2.search_iteration_plan.v1",
            "applied_feedback_count": 1,
            "next_candidates": [],
            "feedback_influence_summary": {
                "schema_version": "dse.step2.search_feedback_influence_summary.v1",
                "applied_feedback_count": 1,
                "feedback_influenced_ordering": True,
                "feedback_influenced_scores": True,
                "feedback_influenced_candidate_selection": True,
                "feedback_influence_blockers": [],
                "safe_to_execute_step3_from_summary": False,
                "safe_to_claim_convergence_from_summary": False,
                "trusted_final_claim": False,
                "release_completion_eligible": False,
                "claim_boundary": "control_plane_feedback_scheduling_evidence_only_not_convergence_or_final_ranking",
            },
        }
    if name == "campaign_materialization_summary.json":
        return {
            "schema_version": "dse.campaign.materialization_summary.v1",
            "request_count": 1,
            "materialized_count": 1,
            "blocked_count": 0,
            "coverage_closed": True,
            "authorized_step3_queue_entry_count": 1,
            "materialization_coverage_blocker_count": 0,
            "materialization_coverage": {
                "coverage_closed": True,
                "authorized_step3_queue_entry_count": 1,
                "blocker_count": 0,
                "blockers": [],
            },
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
        }
    raise AssertionError(f"missing catalog example: {name}")


def _validate_registered_schema(payload: dict, schema_id: str) -> None:
    validate_instance(payload, SCHEMA_REGISTRY[schema_id])


def _payload_sha256(payload: object) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write_audit_pair(
    run_dir: Path,
    *,
    blocked: bool = False,
    selected_candidate_id: str = "candidate-001",
    selected_parameter_hash: str | None = None,
    observed_alias: str | None = None,
    request_candidate_id: str = "candidate-next",
    request_parameter_hash: str | None = None,
    request_count: int | None = None,
    feedback_influenced: bool = True,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    closure = _catalog_example("search_feedback_closure_audit.json")
    replay = _catalog_example("search_replay_safety_audit.json")
    search_iteration_plan = _catalog_example("search_iteration_plan.json")
    observed_alias = observed_alias or selected_candidate_id
    selected_parameter_hash = selected_parameter_hash or f"sha256:{selected_candidate_id}"
    request_parameter_hash = request_parameter_hash or f"sha256:{request_candidate_id}"
    closure["lineage"][0]["selected_candidate_id"] = selected_candidate_id
    closure["lineage"][0]["selected_candidate_parameter_hash"] = selected_parameter_hash
    closure["lineage"][0]["mapping_parameter_hash"] = selected_parameter_hash
    closure["lineage"][0]["search_policy_parameter_hash"] = selected_parameter_hash
    closure["lineage"][0]["request_parameter_hash"] = selected_parameter_hash
    closure["lineage"][0]["request_mapping_parameter_hash"] = selected_parameter_hash
    closure["lineage"][0]["request_search_policy_parameter_hash"] = selected_parameter_hash
    closure["lineage"][0]["search_iteration_candidate_id"] = selected_candidate_id
    closure["lineage"][0]["search_iteration_parameter_hash"] = selected_parameter_hash
    replay["observed_feedback_classification"][0]["alias"] = observed_alias
    replay["observed_feedback_classification"][0]["aliases"] = [
        observed_alias,
        selected_candidate_id,
        selected_parameter_hash,
    ]
    replay["observed_feedback_classification"][0]["parameter_hashes"] = [selected_parameter_hash]
    replay["observed_feedback_classification"][0]["search_policy_parameter_hash"] = selected_parameter_hash
    replay["observed_feedback_classification"][0]["mapping_parameter_hash"] = selected_parameter_hash
    replay["campaign_request_lineage"][0]["candidate_id"] = request_candidate_id
    replay["campaign_request_lineage"][0]["request_parameter_hash"] = request_parameter_hash
    replay["campaign_request_lineage"][0]["request_search_policy_parameter_hash"] = request_parameter_hash
    replay["campaign_request_lineage"][0]["request_mapping_parameter_hash"] = request_parameter_hash
    replay["campaign_request_lineage"][0]["matched_search_candidate_id"] = request_candidate_id
    replay["campaign_request_lineage"][0]["matched_search_candidate_parameter_hash"] = request_parameter_hash
    search_iteration_plan["applied_feedback_count"] = 1
    search_iteration_plan["feedback_influence_summary"] = {
        "schema_version": "dse.step2.search_feedback_influence_summary.v1",
        "normalized_feedback_observation_count": 1,
        "applied_feedback_count": 1,
        "unmatched_feedback_observation_count": 0,
        "pre_feedback_candidate_id_order": [request_candidate_id, selected_candidate_id],
        "post_feedback_candidate_id_order": [selected_candidate_id, request_candidate_id]
        if feedback_influenced
        else [request_candidate_id, selected_candidate_id],
        "pre_feedback_parameter_hash_order": [request_parameter_hash, selected_parameter_hash],
        "post_feedback_parameter_hash_order": [selected_parameter_hash, request_parameter_hash]
        if feedback_influenced
        else [request_parameter_hash, selected_parameter_hash],
        "candidate_rank_score_changes": [
            {
                "candidate_id": selected_candidate_id,
                "parameter_hash": selected_parameter_hash,
                "change_type": "rank_and_score_changed",
                "pre_rank": 2,
                "post_rank": 1,
                "pre_score": 1.0,
                "post_score": 3.0,
                "rank_delta": 1,
                "score_delta": 2.0,
                "observed_feedback": True,
            }
        ]
        if feedback_influenced
        else [],
        "feedback_influenced_ordering": bool(feedback_influenced),
        "feedback_influenced_scores": bool(feedback_influenced),
        "feedback_influenced_candidate_selection": bool(feedback_influenced),
        "feedback_influence_blockers": []
        if feedback_influenced
        else ["feedback_did_not_change_candidate_order", "feedback_did_not_change_candidate_scores"],
        "safe_to_execute_step3_from_summary": False,
        "safe_to_claim_convergence_from_summary": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": "control_plane_feedback_scheduling_evidence_only_not_convergence_or_final_ranking",
    }
    if request_count is not None:
        replay["campaign_step2_iteration_request_count"] = request_count
        if request_count == 0:
            replay["campaign_request_lineage"] = []
    if blocked:
        replay["status"] = "partial_blocked_not_complete"
        replay["blocker_count"] = 1
        replay["blockers"] = [{"reason_id": "observed_candidate_re_requested"}]
        replay["global_checks"]["observed_feedback_not_re_requested"] = False
    (run_dir / "search_feedback_closure_audit.json").write_text(
        json.dumps(closure),
        encoding="utf-8",
    )
    (run_dir / "search_replay_safety_audit.json").write_text(
        json.dumps(replay),
        encoding="utf-8",
    )
    (run_dir / "search_iteration_plan.json").write_text(
        json.dumps(search_iteration_plan),
        encoding="utf-8",
    )


def _write_search_effectiveness_sources(
    run_dir: Path,
    *,
    coverage_effective: bool = True,
    materialization_present: bool = True,
    request_to_execution_progression: bool = False,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    if request_to_execution_progression:
        round1 = run_dir / "round1"
        round2 = run_dir / "round2"
        _write_audit_pair(
            round1,
            selected_candidate_id="candidate-001",
            selected_parameter_hash="sha256:candidate-001",
            request_candidate_id="candidate-next",
            request_parameter_hash="sha256:candidate-next",
        )
        _write_audit_pair(
            round2,
            selected_candidate_id="candidate-next",
            selected_parameter_hash="sha256:candidate-next",
            observed_alias="candidate-next",
            request_candidate_id="candidate-final",
            request_parameter_hash="sha256:candidate-final",
        )
        loop_summary = build_search_loop_audit_summary([round1, round2])
    else:
        _write_audit_pair(run_dir)
        loop_summary = build_search_loop_audit_summary([run_dir])
    (run_dir / "search_loop_audit_summary.json").write_text(
        json.dumps(loop_summary),
        encoding="utf-8",
    )
    coverage_blockers = [] if coverage_effective else [{"reason_id": "single_architecture_family_only"}]
    coverage = {
        "schema_version": "dse.step2.architecture_search_coverage_summary.v1",
        "coverage_status": "search_space_effective" if coverage_effective else "partial_blocked_not_complete",
        "search_space_effective": coverage_effective,
        "blocker_count": len(coverage_blockers),
        "blockers": coverage_blockers,
        "candidate_generation_provenance_complete": coverage_effective,
        "search_policy_enumeration_effective": coverage_effective,
        "search_policy_candidate_enumeration_mode": (
            "bounded_parameter_grid" if coverage_effective else "seed_candidates_only"
        ),
        "architecture_proposal_enumeration_modes": [
            "bounded_parameter_grid" if coverage_effective else "seed_candidates_only"
        ],
        "enumeration_record_count": 1,
        "seed_only_search_policy_enumeration_count": 0 if coverage_effective else 1,
        "non_seed_search_policy_enumeration_count": 1 if coverage_effective else 0,
        "family_count": 3 if coverage_effective else 1,
        "parameterized_family_count": 2 if coverage_effective else 0,
        "architecture_parameter_proposal_count": 6 if coverage_effective else 0,
        "non_default_architecture_parameter_proposal_count": 3 if coverage_effective else 0,
        "materialized_candidate_count": 6 if coverage_effective else 0,
        "non_default_materialized_candidate_count": 3 if coverage_effective else 0,
        "search_policy_candidate_count": 2 if coverage_effective else 0,
        "execution_allowed": False,
        "hidden_evidence_fanout_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "step3_admission_authority": "step2/step3_simulation_queue.json",
    }
    coverage["summary_hash"] = _payload_sha256({
        key: value
        for key, value in coverage.items()
        if key != "summary_hash"
    })
    step2_dir = run_dir / "step2"
    step2_dir.mkdir(exist_ok=True)
    (step2_dir / "architecture_search_space.json").write_text(
        json.dumps({"architecture_search_coverage_summary": coverage}),
        encoding="utf-8",
    )
    admission = _catalog_example("campaign_search_admission_plan.json")
    admission["step2_iteration_request_count"] = 1
    admission["step2_iteration_requests"] = [
        {"request_id": "request-001", "mapping_candidate_id": "mapping-001"}
    ]
    admission["deferred_candidate_count"] = 0
    admission["deferred_candidates"] = []
    (run_dir / "campaign_search_admission_plan.json").write_text(
        json.dumps(admission),
        encoding="utf-8",
    )
    if materialization_present:
        materialization = _catalog_example("campaign_materialization_summary.json")
        (run_dir / "campaign_materialization_summary.json").write_text(
            json.dumps(materialization),
            encoding="utf-8",
        )


def test_materialized_replay_identity_excludes_parent_mapping_anchor():
    aliases = _candidate_identity_aliases({
        "target": "search_policy",
        "status": "available",
        "candidate_refs": {
            "candidate_id": "map_parent",
            "mapping_candidate_id": "map_parent",
            "mapping_id": "mapping-record",
            "selected_candidate_id": "map_executed_child",
            "search_policy_candidate_id": "architecture::materialized-balanced-abc123",
            "materialized_architecture_candidate_id": "architecture::materialized-balanced-abc123",
            "architecture_id": "materialized-balanced-abc123",
            "design_point_id": "workload__materialized-balanced-abc123__step2",
            "source_proposal_id": "step2::trial::architecture_parameter::abc123",
            "architecture_parameter_hash": "sha256:arch",
        },
    })

    assert "architecture::materialized-balanced-abc123" in aliases
    assert "materialized-balanced-abc123" in aliases
    assert "step2::trial::architecture_parameter::abc123" in aliases
    assert "map_parent" not in aliases
    assert "map_executed_child" not in aliases
    assert "mapping-record" not in aliases


def test_search_feedback_loop_auditor_closes_safe_run_dir(tmp_path):
    run_dir = tmp_path / "sweep_ok"
    _write_audit_pair(run_dir)

    summary = build_search_loop_audit_summary([run_dir])

    assert summary["status"] == "closed_for_next_iteration"
    assert summary["run_count"] == 1
    assert summary["closure_closed_count"] == 1
    assert summary["replay_safety_closed_count"] == 1
    assert summary["all_closure_closed"] is True
    assert summary["all_replay_safe"] is True
    assert summary["all_global_checks_safe"] is True
    assert summary["cross_run_replay_safe"] is True
    assert summary["total_blocker_count"] == 0
    assert summary["cross_run_blocker_count"] == 0
    assert summary["progression_safe"] is True
    assert summary["progression_blocker_count"] == 0
    assert summary["effective_round_count"] == 1
    assert summary["new_candidate_execution_count"] == 1
    assert summary["new_executed_candidate_ids"] == ["candidate-001"]
    assert summary["new_candidate_discovery_count"] == 1
    assert summary["new_campaign_request_candidate_ids"] == ["candidate-next"]
    assert summary["request_to_execution_progression_count"] == 0
    assert summary["candidate_progression_ids"] == ["candidate-001", "candidate-next"]
    assert summary["feedback_influence_audit_count"] == 1
    assert summary["missing_feedback_influence_audit_count"] == 0
    assert summary["feedback_influenced_round_count"] == 1
    assert summary["feedback_influence_safe"] is True
    assert summary["all_feedback_influence_effective"] is True
    assert summary["feedback_influence_blocker_count"] == 0
    assert summary["execution_allowed"] is False
    assert summary["hidden_evidence_fanout_allowed"] is False
    assert summary["trusted_final_claim"] is False
    assert summary["release_completion_eligible"] is False
    assert summary["entries"][0]["observed_feedback_alias_count"] >= 1
    assert summary["entries"][0]["campaign_step2_iteration_request_count"] >= 1
    assert summary["entries"][0]["executed_candidate_ids"] == ["candidate-001"]
    assert "candidate-001" in summary["entries"][0]["executed_candidate_aliases"]
    assert "candidate-001" in summary["entries"][0]["observed_feedback_aliases"]
    assert summary["entries"][0]["campaign_request_candidate_ids"] == ["candidate-next"]
    assert summary["entries"][0]["actionable_next_candidate_count"] == 1
    assert summary["entries"][0]["new_campaign_request_candidate_ids"] == ["candidate-next"]
    assert summary["entries"][0]["effective_search_round"] is True
    assert summary["entries"][0]["feedback_influenced_candidate_selection"] is True
    assert summary["entries"][0]["feedback_influence_blocker_count"] == 0


def test_search_iteration_plan_round_trips_to_search_checkpoint():
    plan = build_search_iteration_plan(
        search_checkpoint={
            "schema_version": "dse.step2.search_checkpoint_summary.v1",
            "search_policy_name": "hierarchical_funnel",
            "search_policy_problem": {
                "problem_id": "problem-roundtrip",
                "workload_run_id": "workload-roundtrip",
                "objective": "maximize throughput",
                "parameters": {"pe_count": [1]},
                "constraints": {},
                "seed_candidates": [],
            },
            "search_policy_checkpoint": {
                "schema_version": "dse.step2.search_checkpoint.v1",
                "policy_name": "hierarchical_funnel",
                "problem_id": "problem-roundtrip",
                "proposed_count": 1,
                "observed_count": 0,
                "best_candidate_id": "candidate-roundtrip",
                "candidates": [
                    {
                        "candidate_id": "candidate-roundtrip",
                        "parameters": {"pe_count": 1},
                        "provenance": {"policy_name": "hierarchical_funnel"},
                        "generation_reason": "seed",
                        "parameter_hash": "sha256:roundtrip",
                        "promotion_reasons": ["promoted_for_simulation"],
                        "blocker_reasons": [],
                        "observed_metrics": {},
                    }
                ],
            },
            "search_policy_proposal_budget": 1,
        },
        feedback_update={
            "schema_version": "dse.contract.feedback_update.v1",
            "campaign_id": "campaign",
            "workload_run_id": "workload-roundtrip",
            "trial_id": "trial",
            "updates": [],
            "source_artifact_hashes": {},
        },
    )

    checkpoint = search_checkpoint_from_iteration_plan(
        plan,
        campaign_id="campaign",
        workload_run_id="workload-roundtrip",
        trial_id="trial",
        refs={"search_iteration_plan": "search_iteration_plan.json"},
    )

    assert checkpoint["schema_version"] == "dse.step2.search_checkpoint_summary.v1"
    assert checkpoint["campaign_id"] == "campaign"
    assert checkpoint["workload_run_id"] == "workload-roundtrip"
    assert checkpoint["trial_id"] == "trial"
    assert checkpoint["candidate_count"] == 1
    assert checkpoint["search_policy_checkpoint"]["policy_name"] == "hierarchical_funnel"
    assert checkpoint["search_policy_candidates"][0]["candidate_id"] == plan["next_candidates"][0]["candidate_id"]
    assert checkpoint["trusted_final_claim"] is False
    assert checkpoint["release_completion_eligible"] is False


def test_search_effectiveness_audit_closes_when_all_control_plane_gates_close(tmp_path):
    run_dir = tmp_path / "search_effective"
    _write_search_effectiveness_sources(run_dir, request_to_execution_progression=True)

    audit = build_search_effectiveness_audit(run_dir)

    _validate_registered_schema(audit, "dse.contract.search_effectiveness_audit.v1")
    assert audit["status"] == "closed_for_search_effectiveness"
    assert audit["effectiveness_gate_passed"] is True
    assert audit["coverage_effective"] is True
    assert audit["architecture_search_coverage_count_proof_present"] is True
    assert audit["architecture_search_coverage_count_proof_closed"] is True
    assert audit["architecture_search_coverage_count_values"]["family_count"] >= 2
    assert audit["architecture_search_coverage_count_values"]["non_default_materialized_candidate_count"] >= 1
    assert audit["campaign_admission_safe"] is True
    assert audit["materialization_coverage_closed"] is True
    assert audit["search_progression_safe"] is True
    assert audit["candidate_progression_effective"] is True
    assert audit["candidate_parameter_progression_effective"] is True
    assert audit["request_to_execution_progression_effective"] is True
    assert audit["candidate_progression_parameter_hash_count"] == 3
    assert audit["new_executed_candidate_parameter_hash_count"] == 2
    assert audit["new_campaign_request_candidate_parameter_hash_count"] == 2
    assert audit["request_to_execution_progression_count"] == 1
    assert audit["request_to_execution_progressed_candidate_parameter_hash_count"] == 1
    assert audit["request_to_execution_progressed_candidate_parameter_hashes"] == ["sha256:candidate-next"]
    assert audit["step3_admission_safe"] is True
    assert audit["execution_allowed"] is False
    assert audit["trusted_final_claim"] is False


def test_search_effectiveness_audit_requires_request_to_execution_progression(tmp_path):
    run_dir = tmp_path / "single_round_search"
    _write_search_effectiveness_sources(run_dir)

    audit = build_search_effectiveness_audit(run_dir)

    _validate_registered_schema(audit, "dse.contract.search_effectiveness_audit.v1")
    assert audit["status"] == "partial_blocked_not_complete"
    assert audit["effectiveness_gate_passed"] is False
    assert audit["candidate_progression_effective"] is True
    assert audit["candidate_parameter_progression_effective"] is True
    assert audit["request_to_execution_progression_effective"] is False
    assert audit["request_to_execution_progression_count"] == 0
    blocker_ids = {blocker["reason_id"] for blocker in audit["blockers"]}
    assert "no_request_to_execution_progression" in blocker_ids
    assert "no_request_to_execution_parameter_hash_progression" in blocker_ids


def test_search_effectiveness_audit_blocks_shallow_or_unmaterialized_search(tmp_path):
    shallow_dir = tmp_path / "shallow"
    missing_materialization_dir = tmp_path / "missing_materialization"
    _write_search_effectiveness_sources(shallow_dir, coverage_effective=False)
    _write_search_effectiveness_sources(missing_materialization_dir, materialization_present=False)

    shallow = build_search_effectiveness_audit(shallow_dir)
    missing_materialization = build_search_effectiveness_audit(missing_materialization_dir)

    assert shallow["status"] == "partial_blocked_not_complete"
    assert shallow["coverage_effective"] is False
    shallow_blocker_ids = {blocker["reason_id"] for blocker in shallow["blockers"]}
    assert "architecture_search_coverage_not_effective" in shallow_blocker_ids
    assert "architecture_search_coverage_insufficient_count_proof" in shallow_blocker_ids
    assert missing_materialization["status"] == "partial_blocked_not_complete"
    assert missing_materialization["materialization_coverage_closed"] is False
    assert "missing_campaign_materialization_summary" in {
        blocker["reason_id"] for blocker in missing_materialization["blockers"]
    }


def test_search_effectiveness_audit_rejects_status_without_count_proof(tmp_path):
    missing_counts_dir = tmp_path / "missing_counts"
    zero_counts_dir = tmp_path / "zero_counts"
    _write_search_effectiveness_sources(missing_counts_dir)
    _write_search_effectiveness_sources(zero_counts_dir)

    missing_path = missing_counts_dir / "step2" / "architecture_search_space.json"
    missing_payload = json.loads(missing_path.read_text(encoding="utf-8"))
    missing_coverage = missing_payload["architecture_search_coverage_summary"]
    for key in [
        "family_count",
        "parameterized_family_count",
        "architecture_parameter_proposal_count",
        "non_default_architecture_parameter_proposal_count",
        "materialized_candidate_count",
        "non_default_materialized_candidate_count",
        "search_policy_candidate_count",
        "non_seed_search_policy_enumeration_count",
    ]:
        missing_coverage.pop(key, None)
    missing_coverage["summary_hash"] = _payload_sha256({
        key: value for key, value in missing_coverage.items() if key != "summary_hash"
    })
    missing_path.write_text(json.dumps(missing_payload), encoding="utf-8")

    zero_path = zero_counts_dir / "step2" / "architecture_search_space.json"
    zero_payload = json.loads(zero_path.read_text(encoding="utf-8"))
    zero_coverage = zero_payload["architecture_search_coverage_summary"]
    zero_coverage.update({
        "family_count": 1,
        "parameterized_family_count": 0,
        "architecture_parameter_proposal_count": 0,
        "non_default_architecture_parameter_proposal_count": 0,
        "materialized_candidate_count": 0,
        "non_default_materialized_candidate_count": 0,
        "search_policy_candidate_count": 0,
        "non_seed_search_policy_enumeration_count": 0,
    })
    zero_coverage["summary_hash"] = _payload_sha256({
        key: value for key, value in zero_coverage.items() if key != "summary_hash"
    })
    zero_path.write_text(json.dumps(zero_payload), encoding="utf-8")

    missing = build_search_effectiveness_audit(missing_counts_dir)
    zero = build_search_effectiveness_audit(zero_counts_dir)

    assert missing["status"] == "partial_blocked_not_complete"
    assert zero["status"] == "partial_blocked_not_complete"
    assert missing["architecture_search_coverage_count_proof_present"] is False
    assert missing["architecture_search_coverage_count_proof_closed"] is False
    assert zero["architecture_search_coverage_count_proof_present"] is True
    assert zero["architecture_search_coverage_count_proof_closed"] is False
    assert "architecture_search_coverage_missing_count_proof" in {
        blocker["reason_id"] for blocker in missing["blockers"]
    }
    assert "architecture_search_coverage_insufficient_count_proof" in {
        blocker["reason_id"] for blocker in zero["blockers"]
    }


def test_search_effectiveness_audit_blocks_coverage_overclaims_and_hash_tamper(tmp_path):
    run_dir = tmp_path / "coverage_overclaim"
    _write_search_effectiveness_sources(run_dir)
    search_space_path = run_dir / "step2" / "architecture_search_space.json"
    search_space = json.loads(search_space_path.read_text(encoding="utf-8"))
    coverage = search_space["architecture_search_coverage_summary"]
    coverage.update({
        "execution_allowed": True,
        "hidden_evidence_fanout_allowed": True,
        "trusted_final_claim": True,
        "release_completion_eligible": True,
        "step3_admission_authority": "top_k_candidate_queue.json",
        "summary_hash": "sha256:" + ("0" * 64),
    })
    search_space_path.write_text(json.dumps(search_space), encoding="utf-8")

    audit = build_search_effectiveness_audit(run_dir)

    _validate_registered_schema(audit, "dse.contract.search_effectiveness_audit.v1")
    assert audit["status"] == "partial_blocked_not_complete"
    assert audit["effectiveness_gate_passed"] is False
    assert audit["search_effective"] is False
    blocker_ids = {blocker["reason_id"] for blocker in audit["blockers"]}
    assert {
        "architecture_search_coverage_allows_execution",
        "architecture_search_coverage_allows_hidden_evidence_fanout",
        "architecture_search_coverage_claims_trusted_final_result",
        "architecture_search_coverage_claims_release_completion",
        "architecture_search_coverage_invalid_step3_admission_authority",
        "architecture_search_coverage_summary_hash_mismatch",
    }.issubset(blocker_ids)


def test_search_effectiveness_audit_is_schema_valid_fail_closed_for_empty_run_dir(tmp_path):
    run_dir = tmp_path / "empty_run"
    run_dir.mkdir()

    audit = build_search_effectiveness_audit(run_dir)

    _validate_registered_schema(audit, "dse.contract.search_effectiveness_audit.v1")
    assert audit["status"] == "partial_blocked_not_complete"
    assert audit["effectiveness_gate_passed"] is False
    assert audit["search_effective"] is False
    assert audit["architecture_search_coverage_ref"] == "step2/architecture_search_space.json"
    assert audit["campaign_search_admission_plan_ref"] == "campaign_search_admission_plan.json"
    assert audit["campaign_materialization_summary_ref"] == "campaign_materialization_summary.json"
    assert audit["search_loop_audit_summary_ref"] == "search_loop_audit_summary.json"
    assert audit["execution_allowed"] is False
    assert audit["trusted_final_claim"] is False
    assert audit["release_completion_eligible"] is False
    assert {
        blocker["reason_id"] for blocker in audit["blockers"]
    } == {
        "missing_architecture_search_coverage_summary",
        "missing_campaign_search_admission_plan",
        "missing_campaign_materialization_summary",
        "missing_search_loop_audit_summary",
    }


def test_search_feedback_loop_auditor_reports_blocked_or_missing_runs(tmp_path):
    ok_dir = tmp_path / "sweep_ok"
    blocked_dir = tmp_path / "sweep_blocked"
    missing_dir = tmp_path / "sweep_missing"
    _write_audit_pair(ok_dir, selected_candidate_id="candidate-ok", request_candidate_id="candidate-next-ok")
    _write_audit_pair(
        blocked_dir,
        blocked=True,
        selected_candidate_id="candidate-blocked",
        request_candidate_id="candidate-next-blocked",
    )
    missing_dir.mkdir()

    summary = build_search_loop_audit_summary([ok_dir, blocked_dir, missing_dir])

    assert summary["status"] == "partial_blocked_not_complete"
    assert summary["run_count"] == 3
    assert summary["missing_closure_audit_count"] == 1
    assert summary["missing_replay_safety_audit_count"] == 1
    assert summary["total_blocker_count"] == 3
    assert summary["progression_safe"] is False
    assert summary["progression_blocker_count"] == 1
    assert summary["feedback_influence_blocker_count"] == 1
    assert summary["progression_blockers"] == [
        {
            "reason_id": "progression_not_evaluable_missing_audits",
            "run_dir": str(missing_dir.resolve()),
        }
    ]
    assert summary["all_replay_safe"] is False
    blocked_entry = next(entry for entry in summary["entries"] if entry["run_dir"] == str(blocked_dir.resolve()))
    assert blocked_entry["replay_safety_status"] == "partial_blocked_not_complete"
    assert blocked_entry["replay_safety_global_check_failures"] == ["observed_feedback_not_re_requested"]


def test_search_feedback_loop_auditor_blocks_vacuous_safe_loop_without_next_candidate(tmp_path):
    run_dir = tmp_path / "sweep_safe_but_stalled"
    _write_audit_pair(run_dir, request_count=0)

    summary = build_search_loop_audit_summary([run_dir])

    assert summary["status"] == "partial_blocked_not_complete"
    assert summary["all_closure_closed"] is True
    assert summary["all_replay_safe"] is True
    assert summary["cross_run_replay_safe"] is True
    assert summary["progression_safe"] is False
    assert summary["progression_blocker_count"] == 1
    assert summary["progression_blockers"] == [
        {
            "reason_id": "no_actionable_next_candidate_for_followup",
            "run_dir": str(run_dir.resolve()),
        }
    ]
    assert summary["total_blocker_count"] == 1
    assert summary["new_candidate_execution_count"] == 1
    assert summary["new_candidate_discovery_count"] == 0
    assert summary["entries"][0]["effective_search_round"] is False


def test_search_feedback_loop_auditor_blocks_loop_without_feedback_influence(tmp_path):
    run_dir = tmp_path / "sweep_safe_but_feedback_vacuous"
    _write_audit_pair(run_dir, feedback_influenced=False)

    summary = build_search_loop_audit_summary([run_dir])

    assert summary["status"] == "partial_blocked_not_complete"
    assert summary["all_closure_closed"] is True
    assert summary["all_replay_safe"] is True
    assert summary["progression_safe"] is True
    assert summary["feedback_influence_safe"] is False
    assert summary["all_feedback_influence_effective"] is False
    assert summary["feedback_influenced_round_count"] == 0
    assert summary["feedback_influence_blocker_count"] >= 1
    blocker_ids = {blocker["reason_id"] for blocker in summary["feedback_influence_blockers"]}
    assert "feedback_did_not_influence_ordering_or_scores" in blocker_ids
    assert summary["entries"][0]["feedback_influenced_candidate_selection"] is False


def test_search_feedback_loop_auditor_blocks_cross_run_replay_regression(tmp_path):
    round1 = tmp_path / "round1"
    round2 = tmp_path / "round2"
    _write_audit_pair(round1, selected_candidate_id="candidate-a", request_candidate_id="candidate-b")
    _write_audit_pair(round2, selected_candidate_id="candidate-b", request_candidate_id="candidate-a")

    summary = build_search_loop_audit_summary([round1, round2])

    assert summary["status"] == "partial_blocked_not_complete"
    assert summary["per_run_blocker_count"] == 0
    assert summary["cross_run_replay_safe"] is False
    assert summary["cross_run_blocker_count"] == 1
    assert summary["cross_run_re_requested_observed_candidate_ids"] == ["candidate-a"]
    assert summary["cross_run_duplicate_executed_candidate_ids"] == []
    assert summary["progression_safe"] is False
    assert summary["request_to_execution_progression_count"] == 1
    assert summary["request_to_execution_progressed_candidate_ids"] == ["candidate-b"]
    assert summary["progression_blockers"] == [
        {
            "reason_id": "no_new_actionable_campaign_request_candidate",
            "run_dir": str(round2.resolve()),
        }
    ]
    assert summary["total_blocker_count"] == 2
    assert summary["cross_run_blockers"] == [
        {
            "reason_id": "cross_run_observed_candidate_re_requested",
            "run_dir": str(round2.resolve()),
            "candidate_id": "candidate-a",
        }
    ]


def test_search_feedback_loop_auditor_blocks_parameter_hash_replay_when_ids_change(tmp_path):
    round1 = tmp_path / "round1"
    round2 = tmp_path / "round2"
    repeated_hash = "sha256:reused-parameter-point"
    _write_audit_pair(
        round1,
        selected_candidate_id="candidate-a",
        selected_parameter_hash=repeated_hash,
        request_candidate_id="candidate-b",
        request_parameter_hash="sha256:request-round1",
    )
    _write_audit_pair(
        round2,
        selected_candidate_id="candidate-a-renamed",
        selected_parameter_hash=repeated_hash,
        observed_alias="candidate-a-renamed",
        request_candidate_id="candidate-c",
        request_parameter_hash=repeated_hash,
    )

    summary = build_search_loop_audit_summary([round1, round2])

    assert summary["status"] == "partial_blocked_not_complete"
    assert summary["cross_run_replay_safe"] is False
    assert summary["cross_run_duplicate_executed_candidate_ids"] == []
    assert summary["cross_run_duplicate_executed_candidate_parameter_hashes"] == [repeated_hash]
    assert summary["cross_run_re_requested_observed_candidate_ids"] == []
    assert summary["cross_run_re_requested_observed_candidate_parameter_hashes"] == [repeated_hash]
    assert summary["progression_safe"] is False
    assert summary["progression_blocker_count"] >= 1
    assert summary["new_executed_candidate_ids"] == ["candidate-a", "candidate-a-renamed"]
    assert summary["new_executed_candidate_parameter_hashes"] == [repeated_hash]
    assert summary["candidate_progression_parameter_hashes"].count(repeated_hash) == 1
    assert "sha256:request-round1" in summary["candidate_progression_parameter_hashes"]
    assert any(
        blocker["reason_id"] == "cross_run_candidate_parameter_hash_executed_more_than_once"
        for blocker in summary["cross_run_blockers"]
    )
    assert any(
        blocker["reason_id"] == "cross_run_observed_candidate_parameter_hash_re_requested"
        for blocker in summary["cross_run_blockers"]
    )


def test_search_feedback_loop_auditor_cli_discovers_and_writes_summary(tmp_path):
    run_dir = tmp_path / "nested" / "sweep_ok"
    _write_audit_pair(run_dir)
    out = tmp_path / "search_loop_audit_summary.json"

    result = subprocess.run(
        [
            sys.executable,
            str(AUDITOR),
            "--discover-under",
            str(tmp_path),
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(out.read_text(encoding="utf-8"))
    stdout_summary = json.loads(result.stdout)
    assert summary == stdout_summary
    assert summary["status"] == "closed_for_next_iteration"
    assert summary["run_count"] == 1


def test_search_feedback_loop_auditor_discovery_depth_is_bounded(tmp_path):
    shallow_dir = tmp_path / "shallow"
    deep_dir = tmp_path / "a" / "b" / "c" / "deep"
    _write_audit_pair(shallow_dir)
    _write_audit_pair(deep_dir)

    result = subprocess.run(
        [
            sys.executable,
            str(AUDITOR),
            "--discover-under",
            str(tmp_path),
            "--max-depth",
            "1",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "closed_for_next_iteration"
    assert summary["run_count"] == 1
    assert summary["entries"][0]["run_dir"] == str(shallow_dir.resolve())


def test_search_feedback_loop_auditor_strict_cli_fails_on_partial(tmp_path):
    blocked_dir = tmp_path / "sweep_blocked"
    _write_audit_pair(blocked_dir, blocked=True)

    result = subprocess.run(
        [
            sys.executable,
            str(AUDITOR),
            "--run-dir",
            str(blocked_dir),
            "--strict",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "partial_blocked_not_complete"
