"""Persistent experiment registry for DSE campaigns and trials."""

from dse_v2.registry.experiment_registry import Campaign, ExperimentRegistry, TrialRecord
from dse_v2.registry.schema import CAMPAIGN_SPEC_REQUIRED_FIELDS

__all__ = [
    "CAMPAIGN_SPEC_REQUIRED_FIELDS",
    "Campaign",
    "ExperimentRegistry",
    "TrialRecord",
]
