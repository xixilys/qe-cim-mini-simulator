#!/usr/bin/env python3
"""Persistent experiment registry regressions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from dse_v2.registry import (
    CAMPAIGN_SPEC_REQUIRED_FIELDS,
    ArtifactRef,
    Campaign,
    ExperimentRegistry,
    FailurePolicy,
    InvalidTransitionError,
    ProvenanceRequiredError,
    TrialRecord,
    WorkloadRunRecord,
    completion_status_allows_final_claim,
)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.microsecond == 0
    return parsed


def test_registry_public_api_creates_updates_and_queries_trials(tmp_path: Path):
    registry = ExperimentRegistry(tmp_path / "campaign.sqlite")

    campaign = registry.create_campaign("test_dse", metadata={"workload": "synthetic"})
    trial = registry.add_trial(
        campaign.campaign_id,
        params={"x": 1.0},
        fidelity="L1",
        status="queued",
        artifacts={"design_point": "design_point.json"},
    )
    updated = registry.update_trial(trial.trial_id, status="completed", metrics={"latency_ms": 2.0})
    completed = registry.query_trials(campaign_id=campaign.campaign_id, status="completed")

    assert isinstance(campaign, Campaign)
    assert isinstance(trial, TrialRecord)
    assert isinstance(updated, TrialRecord)
    assert len(completed) == 1
    assert completed[0].trial_id == trial.trial_id
    assert completed[0].campaign_id == campaign.campaign_id
    assert completed[0].params == {"x": 1.0}
    assert completed[0].fidelity == "L1"
    assert completed[0].status == "completed"
    assert completed[0].metrics == {"latency_ms": 2.0}
    assert completed[0].artifacts == {"design_point": "design_point.json"}
    assert completed[0].created_at == trial.created_at
    assert _parse_timestamp(completed[0].updated_at) >= _parse_timestamp(completed[0].created_at)


def test_registry_lists_and_looks_up_campaigns_with_json_metadata(tmp_path: Path):
    registry = ExperimentRegistry(tmp_path / "campaign.sqlite")

    first = registry.create_campaign("first", metadata={"workload": "synthetic", "tags": ["smoke", "L1"]})
    second = registry.create_campaign("second", metadata={"workload": "qe_ref"})

    assert registry.get_campaign(first.campaign_id) == first
    assert registry.get_campaign(999999) is None
    assert registry.list_campaigns() == [first, second]
    assert _parse_timestamp(first.created_at) <= _parse_timestamp(second.created_at)
    assert first.updated_at == first.created_at


def test_registry_filters_trials_by_campaign_status_and_fidelity(tmp_path: Path):
    registry = ExperimentRegistry(tmp_path / "campaign.sqlite")
    campaign_a = registry.create_campaign("campaign_a")
    campaign_b = registry.create_campaign("campaign_b")

    a_l1 = registry.add_trial(campaign_a.campaign_id, params={"x": 1}, fidelity="L1", status="queued")
    a_l2 = registry.add_trial(campaign_a.campaign_id, params={"x": 2}, fidelity="L2", status="completed")
    _ = registry.add_trial(campaign_b.campaign_id, params={"x": 3}, fidelity="L1", status="completed")
    _ = registry.update_trial(a_l1.trial_id, status="completed")

    completed_a = registry.query_trials(campaign_id=campaign_a.campaign_id, status="completed")
    l1_completed_a = registry.query_trials(campaign_id=campaign_a.campaign_id, status="completed", fidelity="L1")

    assert [trial.trial_id for trial in completed_a] == [a_l1.trial_id, a_l2.trial_id]
    assert [trial.trial_id for trial in l1_completed_a] == [a_l1.trial_id]


def test_registry_persists_campaigns_and_trials_after_reopen(tmp_path: Path):
    db_path = tmp_path / "campaign.sqlite"
    registry = ExperimentRegistry(db_path)
    campaign = registry.create_campaign("persistent", metadata={"workload": "synthetic"})
    trial = registry.add_trial(
        campaign.campaign_id,
        params={"x": 4.0, "nested": {"policy": "balanced"}},
        fidelity="L1",
        status="queued",
        metrics={"score": 0.5},
        artifacts={"manifest": "manifest.json"},
    )
    registry.close()

    reopened = ExperimentRegistry(db_path)
    loaded_campaign = reopened.get_campaign(campaign.campaign_id)
    loaded_trials = reopened.query_trials(campaign_id=campaign.campaign_id, fidelity="L1")

    assert loaded_campaign == campaign
    assert len(loaded_trials) == 1
    assert loaded_trials[0].trial_id == trial.trial_id
    assert loaded_trials[0].params == {"x": 4.0, "nested": {"policy": "balanced"}}
    assert loaded_trials[0].metrics == {"score": 0.5}
    assert loaded_trials[0].artifacts == {"manifest": "manifest.json"}


def test_registry_preserves_structured_campaign_specs(tmp_path: Path):
    registry = ExperimentRegistry(tmp_path / "campaign.sqlite")
    campaign_spec = {
        "campaign_id": "qe_architecture_family_reference",
        "purpose": "preserve the existing benchmark campaign contract",
        "families_primary": ["F1", "F2"],
        "families_conditional": ["F3"],
        "main_cases": ["si8"],
        "anchor_cases": ["si4"],
        "coverage_cases": ["graphene"],
        "generalization_cases": ["custom"],
        "design_axes": ["memory", "compute"],
        "objectives": ["latency_ms", "energy_j"],
        "required_gates": ["systemc"],
        "expected_outputs": ["pareto", "report"],
    }

    campaign = registry.create_campaign_from_spec(campaign_spec)
    registry.close()

    reopened = ExperimentRegistry(tmp_path / "campaign.sqlite")
    loaded = reopened.get_campaign(campaign.campaign_id)

    assert loaded is not None
    assert campaign.name == "qe_architecture_family_reference"
    assert set(CAMPAIGN_SPEC_REQUIRED_FIELDS).issubset(loaded.metadata)
    assert loaded.metadata["campaign_id"] == "qe_architecture_family_reference"
    assert loaded.metadata["families_primary"] == ["F1", "F2"]


def _prov(reason: str = "test") -> dict[str, object]:
    return {"actor": "pytest", "reason": reason}


def _ready_workload(registry: ExperimentRegistry, campaign_id: int) -> WorkloadRunRecord:
    workload = registry.create_workload_run(
        campaign_id,
        {"workload_package": "step1/workload_package.json", "workload_family": "synthetic"},
        provenance=_prov("create workload run"),
    )
    assert workload.status == "created"
    workload = registry.transition_workload_run(workload.workload_run_id, "ingesting", provenance=_prov("start step1"))
    workload = registry.transition_workload_run(workload.workload_run_id, "lowered", provenance=_prov("lowered graph"))
    workload = registry.transition_workload_run(workload.workload_run_id, "validated", provenance=_prov("validated package"))
    workload = registry.transition_workload_run(workload.workload_run_id, "ready_for_step2", provenance=_prov("handoff to step2"))
    return workload


def test_policy_owned_campaign_workload_trial_state_machine_accepts_valid_transitions(tmp_path: Path):
    registry = ExperimentRegistry(tmp_path / "campaign.sqlite")
    campaign = registry.create_campaign("policy_campaign")
    campaign = registry.transition_campaign(campaign.campaign_id, "running", provenance=_prov("begin campaign"))
    workload = _ready_workload(registry, campaign.campaign_id)

    trial = registry.create_trial(
        workload.workload_run_id,
        {"design_point": "seeded_beam_0"},
        "L3",
        generation_reasons=["seeded by workload bottleneck"],
        provenance=_prov("generate trial"),
    )
    assert trial.campaign_id == campaign.campaign_id
    assert trial.workload_run_id == workload.workload_run_id
    assert trial.status == "generated"
    assert trial.generation == {"generation_reasons": ["seeded by workload bottleneck"]}

    for status in [
        "screened",
        "promoted",
        "scheduled_for_sim",
        "simulated",
        "adjudicated",
        "reported",
        "finalist",
        "selected",
    ]:
        trial = registry.transition_trial(trial.trial_id, status, provenance=_prov(f"advance to {status}"))
        assert trial.status == status

    campaign = registry.transition_campaign(campaign.campaign_id, "deliverable_complete", provenance=_prov("all hard gates passed"))
    assert campaign.status == "deliverable_complete"
    assert completion_status_allows_final_claim(campaign.status) is True


def test_registry_rejects_invalid_transitions_and_missing_provenance(tmp_path: Path):
    registry = ExperimentRegistry(tmp_path / "campaign.sqlite")
    campaign = registry.create_campaign("invalid_transition_campaign")
    workload = registry.create_workload_run(
        campaign.campaign_id,
        {"workload_package": "step1/workload_package.json"},
        provenance=_prov("create workload"),
    )

    with pytest.raises(ProvenanceRequiredError):
        registry.transition_workload_run(workload.workload_run_id, "ingesting", provenance={"actor": "pytest"})

    with pytest.raises(InvalidTransitionError):
        registry.create_trial(
            workload.workload_run_id,
            {"design_point": "too_early"},
            "L3",
            generation_reasons=["invalid parent state"],
            provenance=_prov("try trial before step1 ready"),
        )

    workload = _ready_workload(registry, campaign.campaign_id)
    trial = registry.create_trial(
        workload.workload_run_id,
        {"design_point": "seeded_beam_0"},
        "L3",
        generation_reasons=["seeded by workload bottleneck"],
        provenance=_prov("generate trial"),
    )

    with pytest.raises(InvalidTransitionError):
        registry.transition_trial(trial.trial_id, "simulated", provenance=_prov("skip screening and scheduling"))

    trial = registry.transition_trial(trial.trial_id, "rejected", provenance=_prov("screening rejected candidate"))
    with pytest.raises(InvalidTransitionError):
        registry.transition_trial(trial.trial_id, "selected", provenance=_prov("terminal state cannot change"))


def test_artifact_refs_propagate_campaign_workload_and_trial_ids_and_resume_after_reopen(tmp_path: Path):
    db_path = tmp_path / "campaign.sqlite"
    registry = ExperimentRegistry(db_path)
    campaign = registry.create_campaign("artifact_ref_campaign")
    workload = _ready_workload(registry, campaign.campaign_id)
    step1_activity = registry.create_activity(
        campaign.campaign_id,
        "step1_ingestion",
        workload_run_id=workload.workload_run_id,
        status="succeeded",
        command={"argv": ["run_step1"]},
        outputs={"workload_package": "step1/workload_package.json"},
        provenance=_prov("record step1 activity"),
    )
    workload_artifact = registry.register_artifact_ref(
        campaign_id=campaign.campaign_id,
        workload_run_id=workload.workload_run_id,
        scope="workload_run",
        path="step1/workload_package.json",
        schema_id="workload_package",
        schema_version="v1",
        content_hash="00" * 32,
        producing_activity_id=step1_activity.activity_id,
        metadata={"canonical_name": "workload_package.json"},
    )
    assert isinstance(workload_artifact, ArtifactRef)
    assert workload_artifact.campaign_id == campaign.campaign_id
    assert workload_artifact.workload_run_id == workload.workload_run_id
    assert workload_artifact.trial_id is None

    trial = registry.create_trial(
        workload.workload_run_id,
        {"design_point": "seeded_beam_0"},
        "L3",
        generation_reasons=["seeded by workload bottleneck"],
        provenance=_prov("generate trial"),
    )
    step2_activity = registry.create_activity(
        campaign.campaign_id,
        "step2_candidate_generation",
        workload_run_id=workload.workload_run_id,
        trial_id=trial.trial_id,
        status="succeeded",
        command={"argv": ["run_step2"]},
        inputs={"workload_package_ref": workload_artifact.artifact_ref_id},
        outputs={"design_point": "step2/design_point.json"},
        provenance=_prov("record step2 activity"),
    )
    trial_artifact = registry.register_artifact_ref(
        campaign_id=campaign.campaign_id,
        trial_id=trial.trial_id,
        scope="trial",
        path="step2/design_point.json",
        schema_id="design_point",
        schema_version="v1",
        content_hash="11" * 32,
        producing_activity_id=step2_activity.activity_id,
        consuming_activity_ids=[step2_activity.activity_id],
        metadata={"canonical_name": "design_point.json"},
    )
    assert trial_artifact.workload_run_id == workload.workload_run_id
    assert trial_artifact.trial_id == trial.trial_id
    assert trial_artifact.consuming_activity_ids == (step2_activity.activity_id,)
    registry.close()

    reopened = ExperimentRegistry(db_path)
    resume = reopened.resume_trial(trial.trial_id)
    assert resume.campaign.campaign_id == campaign.campaign_id
    assert resume.workload_run is not None
    assert resume.workload_run.workload_run_id == workload.workload_run_id
    assert resume.trial is not None
    assert resume.trial.status == "generated"
    assert [artifact.path for artifact in resume.artifacts] == ["step2/design_point.json"]
    assert resume.next_actions == ("screen_candidate",)


def test_failure_policy_maps_retry_and_no_retry_reasons_and_updates_resume_state(tmp_path: Path):
    registry = ExperimentRegistry(tmp_path / "campaign.sqlite")
    campaign = registry.create_campaign("failure_policy_campaign")
    workload = _ready_workload(registry, campaign.campaign_id)
    trial = registry.create_trial(
        workload.workload_run_id,
        {"design_point": "seeded_beam_0"},
        "L3",
        generation_reasons=["seeded by workload bottleneck"],
        provenance=_prov("generate trial"),
        failure_policy=FailurePolicy(max_retries=2),
    )
    trial = registry.transition_trial(trial.trial_id, "screened", provenance=_prov("screen candidate"))
    trial = registry.transition_trial(trial.trial_id, "promoted", provenance=_prov("promote candidate"))
    trial = registry.transition_trial(trial.trial_id, "scheduled_for_sim", provenance=_prov("schedule simulation"))

    retry = registry.resolve_failure_action(reason="timeout", attempts=1, policy=trial.failure_policy)
    no_retry_by_budget = registry.resolve_failure_action(reason="timeout", attempts=2, policy=trial.failure_policy)
    schema_invalid = registry.resolve_failure_action(reason="schema-invalid", attempts=0, policy=trial.failure_policy)
    missing_binding = registry.resolve_failure_action(reason="missing-binding", attempts=0, policy=trial.failure_policy)

    assert retry.action == "retry"
    assert retry.retry_allowed is True
    assert no_retry_by_budget.action == "no_retry"
    assert schema_invalid.action == "no_retry"
    assert missing_binding.action == "no_retry"

    blocked, decision = registry.record_trial_failure(
        trial.trial_id,
        reason="timeout",
        attempts=1,
        provenance=_prov("simulator timeout"),
    )
    assert blocked.status == "blocked"
    assert decision.retry_allowed is True
    assert blocked.resume is not None
    assert blocked.resume["resume_allowed"] is True
    assert blocked.resume["last_failure"]["reason"] == "timeout"

    resumed = registry.transition_trial(
        trial.trial_id,
        "scheduled_for_sim",
        provenance=_prov("retry simulation after timeout"),
        resume={"resume_allowed": True, "resumed_from_failure": decision.to_dict()},
    )
    assert resumed.status == "scheduled_for_sim"
    assert registry.resume_trial(trial.trial_id).next_actions == ("run_simulation",)


def test_terminal_status_taxonomy_only_allows_deliverable_complete_for_final_claim():
    assert completion_status_allows_final_claim("deliverable_complete") is True
    assert completion_status_allows_final_claim("partial_blocked_not_complete") is False
    assert completion_status_allows_final_claim("failed") is False
