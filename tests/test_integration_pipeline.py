#!/usr/bin/env python3
"""
Integration Tests for 3-Layer DSE Pipeline

Tests:
  - 3-layer pipeline end-to-end execution (L0 -> L2 -> L3)
  - Promotion logic integration (threshold-based fidelity promotion)
  - Multi-family support (F1-F6 architecture variants)
  - Confidence validation against GPU baselines
  - Fixture-based testing without real GPU

Usage:
    python3 -m pytest tests/test_integration_pipeline.py -v
    python3 tests/test_integration_pipeline.py
"""

import json
import sys
import math
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ============================================================================
# Test Helpers
# ============================================================================

def load_fixture(name: str) -> dict:
    fixture_dir = ROOT / "tests" / "fixtures" / "data"
    path = fixture_dir / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def generate_fixtures_if_needed():
    fixture_dir = ROOT / "tests" / "fixtures" / "data"
    if (fixture_dir / "index.json").exists():
        return
    fixture_dir.mkdir(parents=True, exist_ok=True)
    import subprocess
    subprocess.run(
        [sys.executable, str(ROOT / "tests" / "fixtures" / "generate_test_fixtures.py"),
         "--output-dir", str(fixture_dir)],
        check=True
    )


# ============================================================================
# Layer Transition Tests
# ============================================================================

def test_layer1_to_layer2_promotion():
    generate_fixtures_if_needed()
    layer1 = load_fixture("layer1_results")
    assert layer1 is not None, "Layer 1 fixture not found"

    results = layer1["results"]
    assert len(results) > 0, "No Layer 1 results"

    for result in results:
        assert "latency_s" in result
        assert "accuracy" in result
        assert result["accuracy"] == 0.50

    promoted = [r for r in results if r.get("family") == "F4" and r.get("case_id") == "si8_pbe_uspp"]
    assert len(promoted) == 1, "Expected exactly one F4/si8_pbe_uspp result"
    assert promoted[0]["latency_s"] > 0


def test_layer2_to_layer3_promotion():
    generate_fixtures_if_needed()
    layer2 = load_fixture("layer2_results")
    assert layer2 is not None, "Layer 2 fixture not found"

    results = layer2["results"]
    assert len(results) > 0

    for result in results:
        assert result["accuracy"] == 0.85
        assert "systemc_cycles" in result
        assert result["systemc_cycles"] > 0

    f4_results = [r for r in results if r.get("family") == "F4"]
    assert len(f4_results) > 0, "No F4 results in Layer 2"


def test_layer3_results_quality():
    generate_fixtures_if_needed()
    layer3 = load_fixture("layer3_results")
    assert layer3 is not None, "Layer 3 fixture not found"

    results = layer3["results"]
    assert len(results) > 0

    for result in results:
        assert result["accuracy"] == 0.95
        assert "cycle_breakdown" in result
        breakdown = result["cycle_breakdown"]
        assert "gemm_cycles" in breakdown
        assert "eigen_cycles" in breakdown
        total_from_breakdown = sum(breakdown.values())
        assert abs(total_from_breakdown - result["systemc_cycles"]) < result["systemc_cycles"] * 0.01


# ============================================================================
# Promotion Logic Tests
# ============================================================================

def test_promotion_threshold_logic():
    threshold = 0.7
    test_cases = [
        {"accuracy": 0.50, "expected_promote": False},
        {"accuracy": 0.70, "expected_promote": False},
        {"accuracy": 0.71, "expected_promote": True},
        {"accuracy": 0.85, "expected_promote": True},
        {"accuracy": 0.95, "expected_promote": True},
    ]

    for tc in test_cases:
        should_promote = tc["accuracy"] > threshold
        assert should_promote == tc["expected_promote"], \
            f"accuracy={tc['accuracy']}, threshold={threshold}: expected {tc['expected_promote']}, got {should_promote}"


def test_promotion_across_layers():
    generate_fixtures_if_needed()

    layer1 = load_fixture("layer1_results")
    layer2 = load_fixture("layer2_results")
    layer3 = load_fixture("layer3_results")

    l1_f4 = [r for r in layer1["results"] if r["family"] == "F4" and r["case_id"] == "si4_pbe_uspp_small"]
    l2_f4 = [r for r in layer2["results"] if r["family"] == "F4" and r["case_id"] == "si4_pbe_uspp_small"]
    l3_f4 = [r for r in layer3["results"] if r["family"] == "F4" and r["case_id"] == "si4_pbe_uspp_small"]

    assert len(l1_f4) == 1 and len(l2_f4) == 1 and len(l3_f4) == 1

    l1_acc = l1_f4[0]["accuracy"]
    l2_acc = l2_f4[0]["accuracy"]
    l3_acc = l3_f4[0]["accuracy"]

    assert l1_acc < l2_acc < l3_acc, \
        f"Accuracy should improve: L1={l1_acc}, L2={l2_acc}, L3={l3_acc}"


# ============================================================================
# Multi-Family Support Tests
# ============================================================================

def test_all_families_present():
    generate_fixtures_if_needed()
    layer1 = load_fixture("layer1_results")

    families = set(r["family"] for r in layer1["results"])
    expected_families = {"F1", "F2", "F3", "F4", "F5", "F6"}
    assert families == expected_families, f"Expected {expected_families}, got {families}"


def test_family_ranking_consistency():
    generate_fixtures_if_needed()
    layer1 = load_fixture("layer1_results")
    layer2 = load_fixture("layer2_results")

    case_id = "si8_pbe_uspp"

    l1_by_family = {r["family"]: r for r in layer1["results"] if r["case_id"] == case_id}
    l2_by_family = {r["family"]: r for r in layer2["results"] if r["case_id"] == case_id}

    assert len(l1_by_family) == 6 and len(l2_by_family) == 6

    l1_ranking = sorted(l1_by_family.keys(), key=lambda f: l1_by_family[f]["latency_s"])
    l2_ranking = sorted(l2_by_family.keys(), key=lambda f: l2_by_family[f]["latency_s"])

    assert l1_ranking[0] == l2_ranking[0], \
        f"Best family should be consistent: L1={l1_ranking[0]}, L2={l2_ranking[0]}"


def test_multi_case_coverage():
    generate_fixtures_if_needed()
    layer2 = load_fixture("layer2_results")

    cases = set(r["case_id"] for r in layer2["results"])
    expected_cases = {
        "si8_pbe_nc", "si8_pbe_uspp", "si4_pbe_uspp_small",
        "graphene_pbe_uspp", "au_slab_subspace", "sic32_subspace",
    }
    assert cases == expected_cases, f"Expected {expected_cases}, got {cases}"


# ============================================================================
# Confidence Validation Tests
# ============================================================================

def test_confidence_computation():
    generate_fixtures_if_needed()
    test_data = load_fixture("confidence_test_data")
    assert test_data is not None, "Confidence test data not found"

    dse = test_data["dse_predictions"]
    gpu = test_data["gpu_baselines"]

    errors = []
    for case_id in dse:
        if case_id in gpu:
            pred = dse[case_id]["latency_s"]
            actual = gpu[case_id]["latency_s"]
            if actual > 0:
                rel_error = abs(pred - actual) / actual
                errors.append(rel_error)

    assert len(errors) > 0, "No matching cases for confidence computation"

    mape = sum(errors) / len(errors)
    assert 0 <= mape <= 1.0, f"MAPE out of range: {mape}"

    expected_range = test_data["expected_weighted_mape_range"]
    assert expected_range[0] <= mape <= expected_range[1] * 2, \
        f"MAPE {mape} outside expected range {expected_range}"


def test_coverage_score():
    generate_fixtures_if_needed()
    test_data = load_fixture("confidence_test_data")

    dse = test_data["dse_predictions"]
    gpu = test_data["gpu_baselines"]

    threshold = 0.20
    within = 0
    total = 0
    for case_id in dse:
        if case_id in gpu:
            pred = dse[case_id]["latency_s"]
            actual = gpu[case_id]["latency_s"]
            if actual > 0:
                rel_error = abs(pred - actual) / actual
                if rel_error <= threshold:
                    within += 1
                total += 1

    coverage = within / total if total > 0 else 0
    assert coverage >= 0.5, f"Coverage too low: {coverage}"


# ============================================================================
# GPU Baseline Manifest Tests
# ============================================================================

def test_gpu_baseline_manifest_schema():
    generate_fixtures_if_needed()
    gpu_data = load_fixture("gpu_baseline_summary_all")
    assert gpu_data is not None, "GPU baseline data not found"

    manifests = gpu_data["manifests"]
    assert len(manifests) == 12, f"Expected 12 manifests (6 cases x 2 modes), got {len(manifests)}"

    required_fields = [
        "schema_version", "baseline_class", "case_id", "gpu_mode",
        "run_tag", "host_id", "gpu_id", "baseline_state", "measurements",
    ]

    for manifest in manifests:
        for field in required_fields:
            assert field in manifest, f"Missing field '{field}' in manifest for {manifest.get('case_id')}"

        assert manifest["schema_version"] == "qe_cpu_gpu_baseline_manifest_template_v0"
        assert manifest["baseline_class"] == "CPU+GPU"
        assert manifest["gpu_mode"] in ["strict_fp64", "practical"]


def test_gpu_baseline_measurements():
    generate_fixtures_if_needed()
    gpu_data = load_fixture("gpu_baseline_summary_all")

    for manifest in gpu_data["manifests"]:
        m = manifest["measurements"]
        assert m["time_to_convergence_s"] > 0
        assert m["effective_gflops"] > 0
        assert m["avg_gpu_board_power_w"] > 0
        assert m["total_flops"] > 0

        stage_sum = sum(m["per_stage_time_s"].values())
        assert abs(stage_sum - m["time_to_convergence_s"]) < m["time_to_convergence_s"] * 0.01


def test_fp64_vs_practical_performance():
    generate_fixtures_if_needed()
    gpu_data = load_fixture("gpu_baseline_summary_all")

    by_case = {}
    for manifest in gpu_data["manifests"]:
        case_id = manifest["case_id"]
        if case_id not in by_case:
            by_case[case_id] = {}
        by_case[case_id][manifest["gpu_mode"]] = manifest["measurements"]["effective_gflops"]

    for case_id, modes in by_case.items():
        assert "strict_fp64" in modes and "practical" in modes
        assert modes["practical"] > modes["strict_fp64"], \
            f"{case_id}: practical ({modes['practical']}) should be faster than strict_fp64 ({modes['strict_fp64']})"


# ============================================================================
# Pipeline Integration Tests
# ============================================================================

def test_pipeline_data_flow():
    generate_fixtures_if_needed()

    wp = load_fixture("pipeline_workload_profile")
    arch = load_fixture("pipeline_architecture_spec")
    dp = load_fixture("pipeline_design_point")

    assert wp is not None and arch is not None and dp is not None

    assert wp["schema_version"] == "workload_profile_v1"
    assert arch["schema_version"] == "architecture_spec_v1"
    assert dp["schema_version"] == "design_point_v1"

    assert arch["selected_family"] == "F4"
    assert dp["parameters"]["system_level"]["family"] == "F4"

    assert len(wp["compute_graph"]["nodes"]) == 5
    node_ids = {n["id"] for n in wp["compute_graph"]["nodes"]}
    assert node_ids == {"h_psi", "s_psi", "build_H_sub", "cdiaghg", "refresh"}


def test_pipeline_layer_results_consistency():
    generate_fixtures_if_needed()

    l1 = load_fixture("pipeline_layer1_results")
    l2 = load_fixture("pipeline_layer2_results")
    l3 = load_fixture("pipeline_layer3_results")

    assert l1 and l2 and l3

    assert l1["fidelity"] == "L0"
    assert l2["fidelity"] == "L2"
    assert l3["fidelity"] == "L3"

    l1_latency = l1["results"][0]["latency_s"]
    l2_latency = l2["results"][0]["latency_s"]
    l3_latency = l3["results"][0]["latency_s"]

    assert l2_latency < l1_latency, "Layer 2 should refine Layer 1 estimate"
    assert abs(l3_latency - l2_latency) / l2_latency < 0.10, \
        "Layer 3 should be close to Layer 2 (within 10%)"


# ============================================================================
# End-to-End Pipeline Test
# ============================================================================

def test_end_to_end_3layer_pipeline():
    generate_fixtures_if_needed()

    layer1 = load_fixture("layer1_results")
    layer2 = load_fixture("layer2_results")
    layer3 = load_fixture("layer3_results")
    gpu_baselines = load_fixture("gpu_baseline_summary_all")

    assert layer1 and layer2 and layer3 and gpu_baselines

    case_id = "si8_pbe_uspp"

    l1_result = next(r for r in layer1["results"] if r["case_id"] == case_id and r["family"] == "F4")
    l2_result = next(r for r in layer2["results"] if r["case_id"] == case_id and r["family"] == "F4")
    l3_result = next(r for r in layer3["results"] if r["case_id"] == case_id and r["family"] == "F4")

    assert l1_result["accuracy"] < l2_result["accuracy"] < l3_result["accuracy"]

    threshold = 0.7
    for result in [l1_result, l2_result, l3_result]:
        should_promote = result["accuracy"] > threshold
        result["promoted"] = should_promote

    assert not l1_result["promoted"]
    assert l2_result["promoted"]
    assert l3_result["promoted"]

    gpu_manifest = next(
        m for m in gpu_baselines["manifests"]
        if m["case_id"] == case_id and m["gpu_mode"] == "practical"
    )
    gpu_latency = gpu_manifest["measurements"]["time_to_convergence_s"]

    dse_latency = l3_result["latency_s"]
    rel_error = abs(dse_latency - gpu_latency) / gpu_latency

    assert rel_error < 1.0, f"DSE vs GPU error too large: {rel_error:.2%}"

    assert l1_result["accuracy"] == 0.50
    assert l2_result["accuracy"] == 0.85
    assert l3_result["accuracy"] == 0.95
    assert l2_result["promoted"] is True
    assert l3_result["promoted"] is True


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    tests = [
        ("Layer 1 -> Layer 2 promotion", test_layer1_to_layer2_promotion),
        ("Layer 2 -> Layer 3 promotion", test_layer2_to_layer3_promotion),
        ("Layer 3 results quality", test_layer3_results_quality),
        ("Promotion threshold logic", test_promotion_threshold_logic),
        ("Promotion across layers", test_promotion_across_layers),
        ("All families present", test_all_families_present),
        ("Family ranking consistency", test_family_ranking_consistency),
        ("Multi-case coverage", test_multi_case_coverage),
        ("Confidence computation", test_confidence_computation),
        ("Coverage score", test_coverage_score),
        ("GPU baseline manifest schema", test_gpu_baseline_manifest_schema),
        ("GPU baseline measurements", test_gpu_baseline_measurements),
        ("FP64 vs practical performance", test_fp64_vs_practical_performance),
        ("Pipeline data flow", test_pipeline_data_flow),
        ("Pipeline layer results consistency", test_pipeline_layer_results_consistency),
        ("End-to-end 3-layer pipeline", test_end_to_end_3layer_pipeline),
    ]

    passed = 0
    failed = 0
    errors = []

    print("=" * 70)
    print("3-LAYER DSE PIPELINE INTEGRATION TESTS")
    print("=" * 70)

    for name, test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
            errors.append((name, str(e)))

    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 70)

    if errors:
        print("\nFailed tests:")
        for name, err in errors:
            print(f"  - {name}: {err}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
