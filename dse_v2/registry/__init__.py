"""Persistent experiment registry for DSE campaigns and trials."""

from dse_v2.registry.experiment_registry import (
    ACTIVITY_STATES,
    CAMPAIGN_STATES,
    FINAL_STATUS_LABELS,
    TRIAL_STATES,
    WORKLOAD_RUN_STATES,
    ActivityRecord,
    ArtifactRef,
    Campaign,
    ExperimentRegistry,
    FailureDecision,
    FailurePolicy,
    InvalidTransitionError,
    ProvenanceRequiredError,
    ResumePlan,
    TrialRecord,
    WorkloadRunRecord,
    completion_status_allows_final_claim,
)
from dse_v2.registry.schema import CAMPAIGN_SPEC_REQUIRED_FIELDS

__all__ = [
    "ACTIVITY_STATES",
    "CAMPAIGN_SPEC_REQUIRED_FIELDS",
    "CAMPAIGN_STATES",
    "FINAL_STATUS_LABELS",
    "TRIAL_STATES",
    "WORKLOAD_RUN_STATES",
    "ActivityRecord",
    "ArtifactRef",
    "Campaign",
    "ExperimentRegistry",
    "FailureDecision",
    "FailurePolicy",
    "InvalidTransitionError",
    "ProvenanceRequiredError",
    "ResumePlan",
    "TrialRecord",
    "WorkloadRunRecord",
    "completion_status_allows_final_claim",
]
