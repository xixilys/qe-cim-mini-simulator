#!/usr/bin/env python3
"""Domain-neutral control-plane entities and lifecycle taxonomy.

The objects here are deliberately lightweight: they define the canonical IDs,
status words, retry policy, artifact references, and transition checks shared by
future Step1--Step5 writers.  They do not encode DFT/QE-specific fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class CompletionStatus(str, Enum):
    """Top-level completion claim taxonomy.

    Only ``deliverable_complete`` is a completed user-facing status.  The other
    terminal labels are reportable states, but explicitly cannot satisfy a final
    completion claim.
    """

    DELIVERABLE_COMPLETE = "deliverable_complete"
    PARTIAL_BLOCKED_NOT_COMPLETE = "partial_blocked_not_complete"
    FAILED = "failed"

    @property
    def permits_final_completion(self) -> bool:
        return self is CompletionStatus.DELIVERABLE_COMPLETE


class CampaignStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ADJUDICATING = "adjudicating"
    DELIVERABLE_COMPLETE = CompletionStatus.DELIVERABLE_COMPLETE.value
    PARTIAL_BLOCKED_NOT_COMPLETE = CompletionStatus.PARTIAL_BLOCKED_NOT_COMPLETE.value
    FAILED = CompletionStatus.FAILED.value


class WorkloadRunStatus(str, Enum):
    CREATED = "created"
    INGESTING = "ingesting"
    INGESTED = "ingested"
    LOWERED = "lowered"
    BLOCKED = "blocked"
    FAILED = "failed"


class TrialStatus(str, Enum):
    GENERATED = "generated"
    SCREENED = "screened"
    PROMOTED = "promoted"
    SCHEDULED_FOR_SIM = "scheduled_for_sim"
    SIMULATED = "simulated"
    ADJUDICATED = "adjudicated"
    REPORTED = "reported"
    FINALIST = "finalist"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    SELECTED = "selected"


class ActivityStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILED = "retryable_failed"
    NON_RETRYABLE_FAILED = "non_retryable_failed"
    SKIPPED = "skipped"


class FailureReason(str, Enum):
    TIMEOUT = "timeout"
    CRASH = "crash"
    SCHEMA_INVALID = "schema_invalid"
    MISSING_BINDING = "missing_binding"
    TOOL_UNAVAILABLE = "tool_unavailable"
    EXTERNAL_BLOCKER = "external_blocker"


class FailureStrategy(str, Enum):
    RETRY = "retry"
    NO_RETRY = "no_retry"
    RECOVER_AND_RESUME = "recover_and_resume"
    ESCALATE_BLOCKER = "escalate_blocker"


TERMINAL_CAMPAIGN_STATUSES = frozenset(
    {
        CampaignStatus.DELIVERABLE_COMPLETE,
        CampaignStatus.PARTIAL_BLOCKED_NOT_COMPLETE,
        CampaignStatus.FAILED,
    }
)
TERMINAL_WORKLOAD_RUN_STATUSES = frozenset(
    {
        WorkloadRunStatus.LOWERED,
        WorkloadRunStatus.BLOCKED,
        WorkloadRunStatus.FAILED,
    }
)
TERMINAL_TRIAL_STATUSES = frozenset(
    {
        TrialStatus.FINALIST,
        TrialStatus.REJECTED,
        TrialStatus.BLOCKED,
        TrialStatus.SELECTED,
    }
)
TERMINAL_ACTIVITY_STATUSES = frozenset(
    {
        ActivityStatus.SUCCEEDED,
        ActivityStatus.NON_RETRYABLE_FAILED,
        ActivityStatus.SKIPPED,
    }
)

_ALLOWED_CAMPAIGN_TRANSITIONS: Mapping[CampaignStatus, frozenset[CampaignStatus]] = {
    CampaignStatus.DRAFT: frozenset({CampaignStatus.ACTIVE, CampaignStatus.FAILED}),
    CampaignStatus.ACTIVE: frozenset(
        {
            CampaignStatus.PAUSED,
            CampaignStatus.ADJUDICATING,
            CampaignStatus.PARTIAL_BLOCKED_NOT_COMPLETE,
            CampaignStatus.FAILED,
        }
    ),
    CampaignStatus.PAUSED: frozenset({CampaignStatus.ACTIVE, CampaignStatus.FAILED}),
    CampaignStatus.ADJUDICATING: frozenset(
        {
            CampaignStatus.ACTIVE,
            CampaignStatus.DELIVERABLE_COMPLETE,
            CampaignStatus.PARTIAL_BLOCKED_NOT_COMPLETE,
            CampaignStatus.FAILED,
        }
    ),
}
_ALLOWED_WORKLOAD_TRANSITIONS: Mapping[
    WorkloadRunStatus, frozenset[WorkloadRunStatus]
] = {
    WorkloadRunStatus.CREATED: frozenset(
        {WorkloadRunStatus.INGESTING, WorkloadRunStatus.BLOCKED, WorkloadRunStatus.FAILED}
    ),
    WorkloadRunStatus.INGESTING: frozenset(
        {WorkloadRunStatus.INGESTED, WorkloadRunStatus.BLOCKED, WorkloadRunStatus.FAILED}
    ),
    WorkloadRunStatus.INGESTED: frozenset(
        {WorkloadRunStatus.LOWERED, WorkloadRunStatus.BLOCKED, WorkloadRunStatus.FAILED}
    ),
}
_ALLOWED_TRIAL_TRANSITIONS: Mapping[TrialStatus, frozenset[TrialStatus]] = {
    TrialStatus.GENERATED: frozenset({TrialStatus.SCREENED, TrialStatus.BLOCKED}),
    TrialStatus.SCREENED: frozenset(
        {TrialStatus.PROMOTED, TrialStatus.REJECTED, TrialStatus.BLOCKED}
    ),
    TrialStatus.PROMOTED: frozenset(
        {TrialStatus.SCHEDULED_FOR_SIM, TrialStatus.REJECTED, TrialStatus.BLOCKED}
    ),
    TrialStatus.SCHEDULED_FOR_SIM: frozenset(
        {TrialStatus.SIMULATED, TrialStatus.BLOCKED, TrialStatus.REJECTED}
    ),
    TrialStatus.SIMULATED: frozenset(
        {TrialStatus.ADJUDICATED, TrialStatus.BLOCKED, TrialStatus.REJECTED}
    ),
    TrialStatus.ADJUDICATED: frozenset(
        {TrialStatus.REPORTED, TrialStatus.FINALIST, TrialStatus.REJECTED, TrialStatus.BLOCKED}
    ),
    TrialStatus.REPORTED: frozenset(
        {TrialStatus.FINALIST, TrialStatus.SELECTED, TrialStatus.REJECTED}
    ),
    TrialStatus.FINALIST: frozenset({TrialStatus.SELECTED, TrialStatus.REJECTED}),
}
_ALLOWED_ACTIVITY_TRANSITIONS: Mapping[ActivityStatus, frozenset[ActivityStatus]] = {
    ActivityStatus.PENDING: frozenset({ActivityStatus.RUNNING, ActivityStatus.SKIPPED}),
    ActivityStatus.RUNNING: frozenset(
        {
            ActivityStatus.SUCCEEDED,
            ActivityStatus.RETRYABLE_FAILED,
            ActivityStatus.NON_RETRYABLE_FAILED,
        }
    ),
    ActivityStatus.RETRYABLE_FAILED: frozenset(
        {ActivityStatus.RUNNING, ActivityStatus.NON_RETRYABLE_FAILED}
    ),
}


def _transition_allowed(
    current: Enum,
    target: Enum,
    table: Mapping[Enum, frozenset[Enum]],
) -> bool:
    if current == target:
        return True
    return target in table.get(current, frozenset())


def _require_transition(
    current: Enum,
    target: Enum,
    table: Mapping[Enum, frozenset[Enum]],
) -> None:
    if not _transition_allowed(current, target, table):
        raise ValueError(f"invalid transition: {current.value} -> {target.value}")


@dataclass(frozen=True)
class FailurePolicy:
    """Retry/recovery policy applied to activities and trials."""

    policy_id: str
    timeout_seconds: int | None = None
    max_retries: int = 0
    retryable_reasons: tuple[FailureReason, ...] = (
        FailureReason.TIMEOUT,
        FailureReason.CRASH,
    )
    no_retry_reasons: tuple[FailureReason, ...] = (
        FailureReason.SCHEMA_INVALID,
        FailureReason.MISSING_BINDING,
    )
    recovery_actions: Mapping[FailureReason, str] = field(default_factory=dict)

    def action_for(self, reason: FailureReason | str, attempts: int) -> FailureStrategy:
        failure_reason = FailureReason(reason)
        if failure_reason in self.no_retry_reasons:
            return FailureStrategy.NO_RETRY
        if (
            failure_reason in self.recovery_actions
            or failure_reason.value in self.recovery_actions
        ):
            return FailureStrategy.RECOVER_AND_RESUME
        if failure_reason in self.retryable_reasons and attempts < self.max_retries:
            return FailureStrategy.RETRY
        if failure_reason in {
            FailureReason.TOOL_UNAVAILABLE,
            FailureReason.EXTERNAL_BLOCKER,
        }:
            return FailureStrategy.ESCALATE_BLOCKER
        return FailureStrategy.NO_RETRY


@dataclass(frozen=True)
class ArtifactRef:
    """Immutable reference to a claim-relevant artifact."""

    artifact_id: str
    canonical_name: str
    path: str
    schema_id: str
    schema_version: str
    content_hash: str
    producer_activity_id: str
    campaign_id: str
    workload_run_id: str | None = None
    trial_id: str | None = None
    consuming_activity_ids: tuple[str, ...] = ()

    def validate_scope(self, phase: str) -> None:
        """Validate required ID propagation for a Step1--Step5 artifact."""

        if not self.campaign_id:
            raise ValueError("campaign_id is required for every artifact")
        if phase in {"step1", "step2", "step3", "step4", "step5"} and not self.workload_run_id:
            raise ValueError(f"workload_run_id is required for {phase} artifacts")
        if phase in {"step2", "step3", "step4", "step5"} and not self.trial_id:
            raise ValueError(f"trial_id is required for {phase} artifacts")


@dataclass
class Activity:
    activity_id: str
    campaign_id: str
    step: str
    status: ActivityStatus = ActivityStatus.PENDING
    command: tuple[str, ...] = ()
    environment_ref: str | None = None
    input_artifact_ids: tuple[str, ...] = ()
    output_artifact_ids: tuple[str, ...] = ()
    failure_policy_id: str | None = None

    def transition_to(self, target: ActivityStatus) -> None:
        _require_transition(self.status, target, _ALLOWED_ACTIVITY_TRANSITIONS)
        self.status = target


@dataclass
class WorkloadRun:
    workload_run_id: str
    campaign_id: str
    workload_family: str
    status: WorkloadRunStatus = WorkloadRunStatus.CREATED
    artifact_ids: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def transition_to(self, target: WorkloadRunStatus) -> None:
        _require_transition(self.status, target, _ALLOWED_WORKLOAD_TRANSITIONS)
        self.status = target


@dataclass
class Trial:
    trial_id: str
    campaign_id: str
    workload_run_id: str
    parent_candidate_refs: tuple[str, ...] = ()
    generation_reasons: tuple[str, ...] = ()
    status: TrialStatus = TrialStatus.GENERATED
    evidence_artifact_ids: tuple[str, ...] = ()
    feedback_artifact_ids: tuple[str, ...] = ()
    verdict_artifact_ids: tuple[str, ...] = ()
    terminal_reason: str | None = None

    def transition_to(self, target: TrialStatus) -> None:
        _require_transition(self.status, target, _ALLOWED_TRIAL_TRANSITIONS)
        self.status = target

    @classmethod
    def resume_from_artifacts(
        cls,
        *,
        trial_id: str,
        campaign_id: str,
        workload_run_id: str,
        status: TrialStatus | str,
        artifact_refs: Sequence[ArtifactRef],
    ) -> "Trial":
        """Reconstruct auditable state from immutable artifact refs."""

        normalized_status = TrialStatus(status)
        evidence_ids = tuple(ref.artifact_id for ref in artifact_refs)
        verdict_ids = tuple(
            ref.artifact_id
            for ref in artifact_refs
            if ref.canonical_name in {"verdict.json", "codesign_verdict.json"}
        )
        feedback_ids = tuple(
            ref.artifact_id
            for ref in artifact_refs
            if ref.canonical_name in {"feedback_update.json", "calibration_record.json"}
        )
        return cls(
            trial_id=trial_id,
            campaign_id=campaign_id,
            workload_run_id=workload_run_id,
            status=normalized_status,
            evidence_artifact_ids=evidence_ids,
            feedback_artifact_ids=feedback_ids,
            verdict_artifact_ids=verdict_ids,
        )


@dataclass
class Campaign:
    campaign_id: str
    objective: str
    status: CampaignStatus = CampaignStatus.DRAFT
    budgets: Mapping[str, Any] = field(default_factory=dict)
    policies: Mapping[str, str] = field(default_factory=dict)
    environment_ref: str | None = None
    git_revision: str | None = None
    global_stop_criteria: tuple[str, ...] = ()

    def transition_to(self, target: CampaignStatus) -> None:
        _require_transition(self.status, target, _ALLOWED_CAMPAIGN_TRANSITIONS)
        self.status = target

    def completion_status(self) -> CompletionStatus | None:
        if self.status in TERMINAL_CAMPAIGN_STATUSES:
            return CompletionStatus(self.status.value)
        return None
