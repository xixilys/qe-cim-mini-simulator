#!/usr/bin/env python3
"""Canonical control-plane contract tests for the DSE restructure."""

from __future__ import annotations

import pytest

from dse_v2.contracts import (
    ARTIFACT_CATALOG,
    SCHEMA_REGISTRY,
    Activity,
    ActivityStatus,
    ArtifactDefinition,
    ArtifactRef,
    Campaign,
    CampaignStatus,
    CompletionStatus,
    ContractValidationError,
    FailurePolicy,
    FailureReason,
    FailureStrategy,
    Trial,
    TrialStatus,
    WorkloadRun,
    WorkloadRunStatus,
    validate_artifact_catalog,
    validate_instance,
    validate_schema_registry,
)


def test_schema_registry_is_semantically_valid_and_domain_neutral():
    validate_schema_registry()

    assert "dse.contract.campaign.v1" in SCHEMA_REGISTRY
    assert "dse.contract.trial.v1" in SCHEMA_REGISTRY
    assert "dse.contract.dft_profile.v1" in SCHEMA_REGISTRY

    forbidden_core_terms = ("dft", "qe")
    for schema_id, schema in SCHEMA_REGISTRY.items():
        if schema_id == "dse.contract.dft_profile.v1":
            continue
        payload = repr(schema).lower()
        assert all(term not in payload for term in forbidden_core_terms), schema_id


def test_artifact_catalog_has_unique_one_producer_bindings_and_examples():
    validate_artifact_catalog()

    names = [item.canonical_name for item in ARTIFACT_CATALOG]
    assert len(names) == len(set(names))
    assert {item.producer_stage for item in ARTIFACT_CATALOG}.issuperset(
        {"control_plane", "step1", "step2", "step3", "step4", "step5"}
    )

    producers = {item.canonical_name: item.producer_stage for item in ARTIFACT_CATALOG}
    assert producers["architecture_search_space.json"] == "step2"
    assert producers["architecture_candidate_generation_report.json"] == "step2"
    assert producers["architecture_screening_report.json"] == "step2"
    assert producers["mapping_candidates.jsonl"] == "step2"
    assert producers["screening_results.jsonl"] == "step2"
    assert producers["promotion_decisions.jsonl"] == "step2"
    assert producers["simulation_request.json"] == "step3"
    assert producers["simulation_result.json"] == "step3"
    assert producers["step3_status.json"] == "step3"
    assert producers["claim_validation.json"] == "step4"
    assert producers["l4_interface_metrics.json"] == "step4"
    assert producers["final_report.json"] == "step5"

    for item in ARTIFACT_CATALOG:
        assert item.schema_id in SCHEMA_REGISTRY
        if item.required:
            assert item.example
            validate_instance(item.example, SCHEMA_REGISTRY[item.schema_id])


def test_artifact_catalog_rejects_duplicate_names_unknown_schemas_and_bad_examples():
    first = ARTIFACT_CATALOG[0]
    duplicate = ArtifactDefinition(
        canonical_name=first.canonical_name,
        producer_stage="another_stage",
        schema_id=first.schema_id,
        consumers=("consumer",),
        example=first.example,
    )
    with pytest.raises(ContractValidationError, match="duplicate artifact name"):
        validate_artifact_catalog([first, duplicate])

    unknown_schema = ArtifactDefinition(
        canonical_name="unknown_schema.json",
        producer_stage="step1",
        schema_id="dse.contract.missing.v1",
        consumers=("step2",),
        example={"schema_version": "dse.contracts.v1"},
    )
    with pytest.raises(ContractValidationError, match="unknown schema"):
        validate_artifact_catalog([unknown_schema])

    bad_example = ArtifactDefinition(
        canonical_name="bad_campaign.json",
        producer_stage="control_plane",
        schema_id="dse.contract.campaign.v1",
        consumers=("ledger",),
        example={"schema_version": "dse.contracts.v1", "campaign_id": "c1"},
    )
    with pytest.raises(ContractValidationError, match="missing required fields"):
        validate_artifact_catalog([bad_example])


def test_status_taxonomy_and_lifecycles_reject_invalid_transitions():
    campaign = Campaign(campaign_id="campaign-001", objective="prove contracts")
    campaign.transition_to(CampaignStatus.ACTIVE)
    campaign.transition_to(CampaignStatus.ADJUDICATING)
    campaign.transition_to(CampaignStatus.DELIVERABLE_COMPLETE)
    assert campaign.completion_status() is CompletionStatus.DELIVERABLE_COMPLETE
    assert campaign.completion_status().permits_final_completion is True

    partial = CompletionStatus.PARTIAL_BLOCKED_NOT_COMPLETE
    failed = CompletionStatus.FAILED
    assert partial.permits_final_completion is False
    assert failed.permits_final_completion is False

    workload = WorkloadRun(
        workload_run_id="workload-run-001",
        campaign_id="campaign-001",
        workload_family="generic_workload",
    )
    workload.transition_to(WorkloadRunStatus.INGESTING)
    workload.transition_to(WorkloadRunStatus.INGESTED)
    workload.transition_to(WorkloadRunStatus.LOWERED)
    with pytest.raises(ValueError, match="invalid transition"):
        workload.transition_to(WorkloadRunStatus.INGESTING)

    trial = Trial(
        trial_id="trial-001",
        campaign_id="campaign-001",
        workload_run_id="workload-run-001",
    )
    trial.transition_to(TrialStatus.SCREENED)
    trial.transition_to(TrialStatus.PROMOTED)
    trial.transition_to(TrialStatus.SCHEDULED_FOR_SIM)
    trial.transition_to(TrialStatus.SIMULATED)
    trial.transition_to(TrialStatus.ADJUDICATED)
    trial.transition_to(TrialStatus.FINALIST)
    trial.transition_to(TrialStatus.SELECTED)
    with pytest.raises(ValueError, match="invalid transition"):
        trial.transition_to(TrialStatus.REJECTED)

    activity = Activity(
        activity_id="activity-step3-001",
        campaign_id="campaign-001",
        step="step3",
    )
    activity.transition_to(ActivityStatus.RUNNING)
    activity.transition_to(ActivityStatus.RETRYABLE_FAILED)
    activity.transition_to(ActivityStatus.RUNNING)
    activity.transition_to(ActivityStatus.SUCCEEDED)
    with pytest.raises(ValueError, match="invalid transition"):
        activity.transition_to(ActivityStatus.RUNNING)


def test_artifact_refs_enforce_id_propagation_and_resume_trial_state():
    step1_ref = ArtifactRef(
        artifact_id="artifact-workload-package",
        canonical_name="workload_package.json",
        path="runs/c1/step1/workload_package.json",
        schema_id="dse.contract.workload_package.v1",
        schema_version="dse.contracts.v1",
        content_hash="sha256:111",
        producer_activity_id="activity-step1",
        campaign_id="campaign-001",
        workload_run_id="workload-run-001",
    )
    step1_ref.validate_scope("step1")

    step2_missing_trial = ArtifactRef(
        artifact_id="artifact-design-point",
        canonical_name="design_point.json",
        path="runs/c1/step2/design_point.json",
        schema_id="dse.contract.design_point.v1",
        schema_version="dse.contracts.v1",
        content_hash="sha256:222",
        producer_activity_id="activity-step2",
        campaign_id="campaign-001",
        workload_run_id="workload-run-001",
    )
    with pytest.raises(ValueError, match="trial_id is required"):
        step2_missing_trial.validate_scope("step2")

    verdict_ref = ArtifactRef(
        artifact_id="artifact-verdict",
        canonical_name="verdict.json",
        path="runs/c1/step4/verdict.json",
        schema_id="dse.contract.verdict.v1",
        schema_version="dse.contracts.v1",
        content_hash="sha256:333",
        producer_activity_id="activity-step4",
        campaign_id="campaign-001",
        workload_run_id="workload-run-001",
        trial_id="trial-001",
    )
    feedback_ref = ArtifactRef(
        artifact_id="artifact-feedback",
        canonical_name="feedback_update.json",
        path="runs/c1/step4/feedback_update.json",
        schema_id="dse.contract.feedback_update.v1",
        schema_version="dse.contracts.v1",
        content_hash="sha256:444",
        producer_activity_id="activity-step4",
        campaign_id="campaign-001",
        workload_run_id="workload-run-001",
        trial_id="trial-001",
    )
    resumed = Trial.resume_from_artifacts(
        trial_id="trial-001",
        campaign_id="campaign-001",
        workload_run_id="workload-run-001",
        status="adjudicated",
        artifact_refs=[step1_ref, verdict_ref, feedback_ref],
    )
    assert resumed.status is TrialStatus.ADJUDICATED
    assert resumed.evidence_artifact_ids == (
        "artifact-workload-package",
        "artifact-verdict",
        "artifact-feedback",
    )
    assert resumed.verdict_artifact_ids == ("artifact-verdict",)
    assert resumed.feedback_artifact_ids == ("artifact-feedback",)


def test_failure_policy_maps_retry_no_retry_and_blocker_actions():
    policy = FailurePolicy(policy_id="default", max_retries=2)
    assert policy.action_for(FailureReason.TIMEOUT, attempts=0) is FailureStrategy.RETRY
    assert policy.action_for(FailureReason.CRASH, attempts=1) is FailureStrategy.RETRY
    assert policy.action_for(FailureReason.CRASH, attempts=2) is FailureStrategy.NO_RETRY
    assert (
        policy.action_for(FailureReason.SCHEMA_INVALID, attempts=0)
        is FailureStrategy.NO_RETRY
    )
    assert (
        policy.action_for(FailureReason.MISSING_BINDING, attempts=0)
        is FailureStrategy.NO_RETRY
    )
    assert (
        policy.action_for(FailureReason.TOOL_UNAVAILABLE, attempts=0)
        is FailureStrategy.ESCALATE_BLOCKER
    )

    recovery_policy = FailurePolicy(
        policy_id="recover",
        max_retries=0,
        recovery_actions={FailureReason.TIMEOUT: "resume from last artifact"},
    )
    assert (
        recovery_policy.action_for(FailureReason.TIMEOUT, attempts=10)
        is FailureStrategy.RECOVER_AND_RESUME
    )
