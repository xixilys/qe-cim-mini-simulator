#!/usr/bin/env python3

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from interfaces.validator import InterfaceValidator
from pipeline import ArtifactStore, Step5_Execute, Step6_Release
from tests.test_interfaces import evaluation_config


def execute_result(fidelity, tmp_path):
    store = ArtifactStore(tmp_path)
    validator = InterfaceValidator()
    input_hash = store.store(evaluation_config(fidelity))
    output_hash, _ = Step5_Execute(store, validator).execute(input_hash)
    return store, store.load(output_hash), output_hash


def test_latency_confidence_interval_contains_point_estimate(tmp_path):
    _, result, _ = execute_result("L2", tmp_path)
    lower, upper = result["uncertainty"]["latency_ci_95"]
    assert lower < result["metrics"]["latency_ms"] < upper


def test_throughput_confidence_interval_contains_point_estimate(tmp_path):
    _, result, _ = execute_result("L2", tmp_path)
    lower, upper = result["uncertainty"]["throughput_ci_95"]
    assert lower < result["metrics"]["throughput_gops"] < upper


def test_uncertainty_reports_confidence_level_and_sample_size(tmp_path):
    _, result, _ = execute_result("L2", tmp_path)
    uncertainty = result["uncertainty"]
    assert uncertainty["confidence_level"] == 0.95
    assert uncertainty["sample_size"] >= 1
    assert uncertainty["mape_percent"] >= 0


def test_confidence_quantification_validates_for_all_fidelity_levels(tmp_path):
    validator = InterfaceValidator()
    for fidelity in ["L0", "L1", "L2", "L3", "L4"]:
        _, result, _ = execute_result(fidelity, tmp_path / fidelity)
        validation = validator.validate(result, "evaluation_result_v1")
        assert validation.valid, validation.errors
        assert 0 <= result["metrics"]["accuracy_vs_reference"] <= 1
        assert 0 <= result["promotion_score"] <= 1


def test_release_bundle_confidence_is_bounded_and_authority_scoped(tmp_path):
    store, result, result_hash = execute_result("L2", tmp_path)
    bundle_hash, _ = Step6_Release(store, InterfaceValidator()).execute(result_hash)
    bundle = store.load(bundle_hash)
    assert 0 <= bundle["recommendation"]["confidence"] <= 1
    assert bundle["authority"]["stage"] == "A"
    assert bundle["authority"]["claim_posture"] == "evidence_only"


def test_confidence_intervals_have_positive_width(tmp_path):
    _, result, _ = execute_result("L3", tmp_path)
    for interval_name in ["latency_ci_95", "throughput_ci_95"]:
        lower, upper = result["uncertainty"][interval_name]
        assert upper - lower > 0
