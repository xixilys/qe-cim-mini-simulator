#!/usr/bin/env python3

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from interfaces.validator import InterfaceValidator
from pipeline import ArtifactStore, Step4_FidelityConfig, Step5_Execute
from tests.test_interfaces import design_point, evaluation_config


FIDELITY_ORDER = ["L0", "L1", "L2", "L3", "L4"]


def run_execute_for_fidelity(fidelity, tmp_path):
    config = evaluation_config(fidelity)
    store = ArtifactStore(tmp_path)
    validator = InterfaceValidator()
    input_hash = store.store(config)
    output_hash, _ = Step5_Execute(store, validator).execute(input_hash)
    return store.load(output_hash)


def test_fidelity_ladder_contains_all_ordered_levels(tmp_path):
    store = ArtifactStore(tmp_path)
    validator = InterfaceValidator()
    input_hash = store.store(design_point())
    output_hash, _ = Step4_FidelityConfig(store, validator).execute(input_hash)
    config = store.load(output_hash)

    assert list(config["fidelity_config"].keys()) == FIDELITY_ORDER
    assert config["fidelity_level"] == "L0"
    assert validator.validate(config, "evaluation_config_v1").valid


def test_fidelity_cost_budget_increases_monotonically():
    config = evaluation_config()
    costs = [config["fidelity_config"][level]["max_cost_seconds"] for level in FIDELITY_ORDER]
    assert costs == sorted(costs)
    assert len(set(costs)) == len(costs)


@pytest.mark.parametrize(
    "fidelity,expected_recommendation",
    [("L0", "hold"), ("L1", "hold"), ("L2", "promote"), ("L3", "promote"), ("L4", "promote")],
)
def test_promotion_recommendation_follows_accuracy_threshold(fidelity, expected_recommendation, tmp_path):
    result = run_execute_for_fidelity(fidelity, tmp_path)
    assert result["promotion_recommendation"] == expected_recommendation
    assert result["promotion_score"] == result["metrics"]["accuracy_vs_reference"]


def test_promotion_scores_do_not_decrease_with_higher_fidelity(tmp_path):
    scores = [run_execute_for_fidelity(level, tmp_path / level)["promotion_score"] for level in FIDELITY_ORDER]
    assert scores == sorted(scores)


def test_promoted_results_are_always_passed(tmp_path):
    for level in FIDELITY_ORDER:
        result = run_execute_for_fidelity(level, tmp_path / level)
        if result["promotion_recommendation"] == "promote":
            assert result["status"] == "passed"
            assert result["promotion_score"] > 0.7


def test_fidelity_model_used_matches_selected_level(tmp_path):
    for level in FIDELITY_ORDER:
        result = run_execute_for_fidelity(level, tmp_path / level)
        assert result["fidelity_level_achieved"] == level
        assert result["provenance"]["model_used"] == evaluation_config(level)["fidelity_config"][level]["model"]
