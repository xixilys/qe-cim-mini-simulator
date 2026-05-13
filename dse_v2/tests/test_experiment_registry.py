#!/usr/bin/env python3
"""Persistent experiment registry regressions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dse_v2.registry import CAMPAIGN_SPEC_REQUIRED_FIELDS, Campaign, ExperimentRegistry, TrialRecord


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
