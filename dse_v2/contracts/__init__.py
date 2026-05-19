"""Canonical DSE control-plane contract surface.

This package is intentionally stdlib-only and domain-neutral.  It freezes the
small contract layer needed by the research-grade restructure before stage
writers migrate to the new artifact tree.
"""

from dse_v2.contracts.artifact_catalog import (
    ARTIFACT_CATALOG,
    ArtifactDefinition,
    artifact_definition_for,
    validate_artifact_write,
    validate_artifact_catalog,
    validate_artifact_writes,
)
from dse_v2.contracts.entities import (
    Activity,
    ActivityStatus,
    ArtifactRef,
    Campaign,
    CampaignStatus,
    CompletionStatus,
    FailurePolicy,
    FailureReason,
    FailureStrategy,
    Trial,
    TrialStatus,
    WorkloadRun,
    WorkloadRunStatus,
)
from dse_v2.contracts.schema_registry import (
    CONTRACT_VERSION,
    SCHEMA_REGISTRY,
    get_schema,
    validate_schema_registry,
)
from dse_v2.contracts.validation import (
    ContractValidationError,
    validate_instance,
    validate_schema_semantics,
)

__all__ = [
    "Activity",
    "ActivityStatus",
    "ARTIFACT_CATALOG",
    "ArtifactDefinition",
    "ArtifactRef",
    "Campaign",
    "CampaignStatus",
    "CompletionStatus",
    "CONTRACT_VERSION",
    "ContractValidationError",
    "FailurePolicy",
    "FailureReason",
    "FailureStrategy",
    "SCHEMA_REGISTRY",
    "Trial",
    "TrialStatus",
    "WorkloadRun",
    "WorkloadRunStatus",
    "get_schema",
    "artifact_definition_for",
    "validate_artifact_write",
    "validate_artifact_writes",
    "validate_artifact_catalog",
    "validate_instance",
    "validate_schema_registry",
    "validate_schema_semantics",
]
