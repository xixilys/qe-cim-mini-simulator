#!/usr/bin/env python3
"""QE-IC Layer-5A L1 cost-model contract regressions."""

from __future__ import annotations

import ast
import copy
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from dse_v2.candidates.qe_ic import validate_qe_ic_candidate_plan
from dse_v2.evaluation.qe_ic import l1_cost_model
from dse_v2.evaluation.qe_ic.l1_cost_model.schema import (
    BOTTLENECK_CLASSES,
    NEXT_FIDELITY_SUGGESTIONS,
    REASON_CODE_REGISTRY,
)
from dse_v2.profiling.qe_ic import validate_qe_ic_motif_profile
from dse_v2.viability.qe_ic import validate_qe_ic_target_viability
from dse_v2.workloads.qe_ic import validate_qe_ic_workload_suite


SUITE_PATH = Path("artifacts/qe_ic_workload_suite/qe_ic_workload_suite.json")
MOTIF_PROFILE_PATH = Path("artifacts/qe_ic_motif_profile/qe_ic_motif_profile.json")
TARGET_VIABILITY_PATH = Path("artifacts/qe_ic_target_viability/qe_ic_target_viability.json")
CANDIDATE_PLAN_PATH = Path("artifacts/qe_ic_candidate_plan/qe_ic_candidate_plan.json")
MODEL_CONFIG_PATH = Path("dse_v2/testdata/qe_ic_l1_cost_model/qe_ic_l1_cost_model_config_fixture.json")
CHECKED_IN_RESULTS_DIR = Path("artifacts/qe_ic_l1_cost_model")
CLI_PATH = Path("dse_v2/scripts/dse/run_qe_ic_l1_cost_model.py")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _inputs() -> tuple[dict, dict, dict, dict, dict]:
    return (
        _load_json(SUITE_PATH),
        _load_json(MOTIF_PROFILE_PATH),
        _load_json(TARGET_VIABILITY_PATH),
        _load_json(CANDIDATE_PLAN_PATH),
        _load_json(MODEL_CONFIG_PATH),
    )


def _run_results(candidate_plan: dict | None = None, model_config: dict | None = None) -> dict:
    suite, motif_profile, target_viability, plan, config = _inputs()
    return l1_cost_model.run_qe_ic_l1_cost_model(
        suite,
        motif_profile,
        target_viability,
        candidate_plan or plan,
        model_config or config,
    )


def _decision_by_candidate(plan: dict) -> dict[str, dict]:
    return {
        decision["candidate_id"]: decision
        for decision in plan["promotion_decisions"]
    }


def _candidate_by_id(plan: dict) -> dict[str, dict]:
    return {
        candidate["candidate_id"]: candidate
        for candidate in plan["candidates"]
    }


def _result_by_candidate(results: dict) -> dict[str, dict]:
    return {
        result["candidate_id"]: result
        for result in results["results"]
    }


def test_public_api_exports_expected_functions():
    assert l1_cost_model.run_qe_ic_l1_cost_model
    assert l1_cost_model.validate_qe_ic_l1_cost_model_results
    assert l1_cost_model.write_qe_ic_l1_cost_model_artifacts
    assert l1_cost_model.load_qe_ic_l1_cost_model_results


def test_model_config_fixture_loads():
    config = _load_json(MODEL_CONFIG_PATH)

    assert config["schema_version"] == "dse.qe_ic.l1_cost_model_config.v1"
    assert config["config_id"] == "qe_ic_l1_cost_model_fixture_config"
    assert config["model_policy"]["allow_external_execution"] is False
    assert config["calibration"]["calibration_status"] == "fixture_prior"


def test_inputs_layer1_layer2_layer3_layer4_are_validated():
    suite, motif_profile, target_viability, candidate_plan, _model_config = _inputs()

    assert validate_qe_ic_workload_suite(suite)["status"] == "passed"
    assert validate_qe_ic_motif_profile(motif_profile)["status"] == "passed"
    assert validate_qe_ic_target_viability(target_viability)["status"] == "passed"
    assert validate_qe_ic_candidate_plan(candidate_plan)["status"] == "passed"


def test_runner_executes_only_l1_cost_model_requests():
    results = _run_results()
    plan = _load_json(CANDIDATE_PLAN_PATH)
    expected_request_ids = {
        request["request_id"]
        for request in plan["evaluation_requests"]
        if request["requested_fidelity"] == "L1_cost_model"
        and request["status"] == "planned_not_executed"
    }

    assert {result["request_id"] for result in results["results"]} == expected_request_ids
    assert all(result["requested_fidelity"] == "L1_cost_model" for result in results["results"])


def test_each_l1_request_gets_exactly_one_result():
    results = _run_results()
    request_ids = [result["request_id"] for result in results["results"]]

    assert len(request_ids) == len(set(request_ids))
    assert len(request_ids) == results["summary"]["request_count"]


def test_baseline_hold_reject_candidates_do_not_get_accelerator_results():
    results = _run_results()
    plan = _load_json(CANDIDATE_PLAN_PATH)
    decisions = _decision_by_candidate(plan)

    for result in results["results"]:
        assert decisions[result["candidate_id"]]["decision"] == "promote"
        assert result["candidate_type"] in {"fpga_candidate", "hybrid_candidate"}
    assert results["baseline_references"]


def test_results_have_traceability_to_candidate_and_request():
    results = _run_results()
    plan = _load_json(CANDIDATE_PLAN_PATH)
    request_ids = {request["request_id"] for request in plan["evaluation_requests"]}
    candidate_ids = {candidate["candidate_id"] for candidate in plan["candidates"]}
    decision_ids = {
        decision["candidate_id"]: decision["promotion_decision_id"]
        for decision in plan["promotion_decisions"]
    }

    for result in results["results"]:
        traceability = result["source_traceability"]
        assert result["request_id"] in request_ids
        assert result["candidate_id"] in candidate_ids
        assert traceability["layer4_candidate_plan_artifact"] == "qe_ic_candidate_plan.json"
        assert traceability["promotion_decision_id"] == decision_ids[result["candidate_id"]]
        assert traceability["source_viability_record_id"]


def test_estimate_fields_are_present_and_numeric():
    results = _run_results()
    required = {
        "estimated_latency_ms",
        "estimated_speedup_vs_gpu_baseline",
        "estimated_net_gain_ratio",
        "estimated_transfer_overhead_ms",
        "estimated_compute_time_ms",
        "estimated_memory_time_ms",
        "estimated_communication_time_ms",
        "estimated_resource_pressure",
        "estimated_model_confidence",
    }

    for result in results["results"]:
        assert set(result["estimate"]) == required
        assert all(
            isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(float(value))
            for value in result["estimate"].values()
        )


def test_risk_fields_are_bounded():
    results = _run_results()
    required = {
        "overall_l1_risk",
        "model_uncertainty_risk",
        "resource_risk",
        "transfer_risk",
        "profile_quality_risk",
    }

    for result in results["results"]:
        assert set(result["risk"]) == required
        assert all(0.0 <= value <= 1.0 for value in result["risk"].values())


def test_bottleneck_classification_uses_registry():
    results = _run_results()

    for result in results["results"]:
        bottleneck = result["bottleneck_classification"]
        assert bottleneck["primary_bottleneck"] in BOTTLENECK_CLASSES
        assert set(bottleneck["secondary_bottlenecks"]).issubset(BOTTLENECK_CLASSES)


def test_next_fidelity_suggestion_uses_registry():
    results = _run_results()

    assert results["results"]
    for result in results["results"]:
        suggestion = result["next_fidelity_suggestion"]["suggestion"]
        assert suggestion in NEXT_FIDELITY_SUGGESTIONS


def test_reason_codes_are_from_registry():
    results = _run_results()

    for result in results["results"]:
        reason_codes = result["next_fidelity_suggestion"]["reason_codes"]
        assert reason_codes
        assert set(reason_codes).issubset(REASON_CODE_REGISTRY)


def test_summary_matches_results():
    results = _run_results()
    validation = l1_cost_model.validate_qe_ic_l1_cost_model_results(results)

    assert validation["status"] == "passed"
    assert results["summary"]["request_count"] == len(results["results"])
    assert results["summary"]["completed_estimate_count"] == len(results["results"])


def test_validation_passes_default_fixture():
    results = _run_results()
    validation = l1_cost_model.validate_qe_ic_l1_cost_model_results(results)

    assert validation["status"] == "passed"
    assert validation["errors"] == []
    assert validation["result_count"] == len(results["results"])


def test_validation_fails_missing_request_result():
    results = _run_results()
    missing = results["results"].pop()
    results["summary"]["request_count"] -= 1
    results["summary"]["completed_estimate_count"] -= 1
    results["summary"]["by_target_type"][missing["target_type"]]["completed_estimate_count"] -= 1
    suggestion = missing["next_fidelity_suggestion"]["suggestion"]
    results["summary"]["by_suggestion"][suggestion] -= 1

    validation = l1_cost_model.validate_qe_ic_l1_cost_model_results(results)

    assert validation["status"] == "failed"
    assert any("exactly one result" in error["message"] for error in validation["errors"])


def test_validation_fails_duplicate_request_result():
    results = _run_results()
    duplicate = copy.deepcopy(results["results"][0])
    duplicate["result_id"] += "_duplicate"
    results["results"].append(duplicate)
    results["summary"]["request_count"] += 1
    results["summary"]["completed_estimate_count"] += 1
    results["summary"]["by_target_type"][duplicate["target_type"]]["completed_estimate_count"] += 1
    results["summary"]["by_suggestion"][duplicate["next_fidelity_suggestion"]["suggestion"]] += 1

    validation = l1_cost_model.validate_qe_ic_l1_cost_model_results(results)

    assert validation["status"] == "failed"
    assert any("exactly one result" in error["message"] for error in validation["errors"])


def test_validation_fails_unknown_candidate_reference():
    results = _run_results()
    results["results"][0]["candidate_id"] = "missing_candidate"

    validation = l1_cost_model.validate_qe_ic_l1_cost_model_results(results)

    assert validation["status"] == "failed"
    assert any("unknown candidate" in error["message"] for error in validation["errors"])


def test_validation_fails_result_for_non_promoted_candidate():
    results = _run_results()
    plan = results["source_layer4_candidate_plan"]
    hold_candidate = next(
        candidate
        for candidate in plan["candidates"]
        if _decision_by_candidate(plan)[candidate["candidate_id"]]["decision"] == "hold"
    )
    results["results"][0]["candidate_id"] = hold_candidate["candidate_id"]

    validation = l1_cost_model.validate_qe_ic_l1_cost_model_results(results)

    assert validation["status"] == "failed"
    assert any("promoted non-baseline" in error["message"] for error in validation["errors"])


def test_validation_fails_forbidden_high_fidelity_execution_fields():
    results = _run_results()
    results["systemc_result"] = {}
    results["results"][0]["measured_latency"] = 1.0

    validation = l1_cost_model.validate_qe_ic_l1_cost_model_results(results)

    assert validation["status"] == "failed"
    assert any("execution" in error["message"].lower() for error in validation["errors"])


def test_validation_fails_nested_forbidden_high_fidelity_execution_fields():
    results = _run_results()
    results["results"][0]["estimate"]["measured_power"] = 1.0

    validation = l1_cost_model.validate_qe_ic_l1_cost_model_results(results)

    assert validation["status"] == "failed"
    assert any("forbidden" in error["message"].lower() for error in validation["errors"])


def test_validation_fails_result_traceability_artifact_mismatch():
    results = _run_results()
    results["results"][0]["source_traceability"]["layer2_profile_artifact"] = "bad.json"

    validation = l1_cost_model.validate_qe_ic_l1_cost_model_results(results)

    assert validation["status"] == "failed"
    assert any("traceability" in error["field"] for error in validation["errors"])


def test_writer_emits_required_artifacts(tmp_path: Path):
    result = l1_cost_model.write_qe_ic_l1_cost_model_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_VIABILITY_PATH,
        CANDIDATE_PLAN_PATH,
        MODEL_CONFIG_PATH,
    )

    assert result["status"] == "passed"
    assert result["artifacts"] == [
        "qe_ic_l1_cost_model_results.json",
        "qe_ic_l1_cost_model_validation.json",
        "qe_ic_l1_cost_model_manifest.json",
        "qe_ic_l1_cost_model_readme.md",
    ]
    for artifact in result["artifacts"]:
        assert (tmp_path / artifact).exists()


def test_writer_fail_closed_for_invalid_candidate_plan(tmp_path: Path):
    candidate_plan_path = tmp_path / "candidate_plan.json"
    candidate_plan = _load_json(CANDIDATE_PLAN_PATH)
    candidate_plan["schema_version"] = "bad"
    candidate_plan_path.write_text(json.dumps(candidate_plan))

    result = l1_cost_model.write_qe_ic_l1_cost_model_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_VIABILITY_PATH,
        candidate_plan_path,
        MODEL_CONFIG_PATH,
    )

    assert result["status"] == "failed"
    assert result["artifacts"] == ["qe_ic_l1_cost_model_validation.json"]
    assert (tmp_path / "qe_ic_l1_cost_model_validation.json").exists()
    assert not (tmp_path / "qe_ic_l1_cost_model_results.json").exists()
    assert not (tmp_path / "qe_ic_l1_cost_model_manifest.json").exists()
    assert not (tmp_path / "qe_ic_l1_cost_model_readme.md").exists()


def test_writer_fail_closed_removes_stale_canonical_artifacts(tmp_path: Path):
    valid_result = l1_cost_model.write_qe_ic_l1_cost_model_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_VIABILITY_PATH,
        CANDIDATE_PLAN_PATH,
        MODEL_CONFIG_PATH,
    )
    assert valid_result["status"] == "passed"
    candidate_plan_path = tmp_path / "candidate_plan.json"
    candidate_plan = _load_json(CANDIDATE_PLAN_PATH)
    candidate_plan["schema_version"] = "bad"
    candidate_plan_path.write_text(json.dumps(candidate_plan))

    failed_result = l1_cost_model.write_qe_ic_l1_cost_model_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_VIABILITY_PATH,
        candidate_plan_path,
        MODEL_CONFIG_PATH,
    )

    assert failed_result["status"] == "failed"
    assert (tmp_path / "qe_ic_l1_cost_model_validation.json").exists()
    assert not (tmp_path / "qe_ic_l1_cost_model_results.json").exists()
    assert not (tmp_path / "qe_ic_l1_cost_model_manifest.json").exists()
    assert not (tmp_path / "qe_ic_l1_cost_model_readme.md").exists()


def test_checked_in_qe_ic_l1_cost_model_artifacts_match_builder_output(tmp_path: Path):
    l1_cost_model.write_qe_ic_l1_cost_model_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_VIABILITY_PATH,
        CANDIDATE_PLAN_PATH,
        MODEL_CONFIG_PATH,
    )

    for artifact in [
        "qe_ic_l1_cost_model_results.json",
        "qe_ic_l1_cost_model_validation.json",
        "qe_ic_l1_cost_model_manifest.json",
        "qe_ic_l1_cost_model_readme.md",
    ]:
        assert (CHECKED_IN_RESULTS_DIR / artifact).read_text() == (tmp_path / artifact).read_text()


def test_manifest_declares_downstream_request_builders():
    manifest = _load_json(CHECKED_IN_RESULTS_DIR / "qe_ic_l1_cost_model_manifest.json")

    assert manifest["artifact_role"] == "dse_layer5a_l1_cost_model_results"
    assert "layer5b_systemc_request_builder" in manifest["downstream_consumers"]
    assert "layer5d_vivado_request_builder" in manifest["downstream_consumers"]


def test_cli_emits_passed_status(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "--suite",
            str(SUITE_PATH),
            "--motif-profile",
            str(MOTIF_PROFILE_PATH),
            "--target-viability",
            str(TARGET_VIABILITY_PATH),
            "--candidate-plan",
            str(CANDIDATE_PLAN_PATH),
            "--model-config",
            str(MODEL_CONFIG_PATH),
            "--out",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "passed"


def test_core_logic_not_in_cli():
    tree = ast.parse(CLI_PATH.read_text())
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert function_names == {"parse_args", "main"}
    assert "estimated_latency_ms" not in CLI_PATH.read_text()
    assert "next_fidelity_suggestion" not in CLI_PATH.read_text()


def test_claim_boundary_blocks_execution_and_final_performance_claims():
    results = _run_results()
    lowered = results["claim_boundary"].lower()

    assert "does not contain systemc/gem5/vivado/dc/qe execution results" in lowered
    assert "final performance claims" in lowered
    assert all("not measured" in result["claim_boundary"].lower() for result in results["results"])


def test_high_transfer_overhead_receives_higher_transfer_risk():
    plan = _load_json(CANDIDATE_PLAN_PATH)
    config = _load_json(MODEL_CONFIG_PATH)
    low = next(
        candidate
        for candidate in plan["candidates"]
        if candidate["candidate_type"] == "fpga_candidate"
    )
    high_plan = copy.deepcopy(plan)
    high_candidate = _candidate_by_id(high_plan)[low["candidate_id"]]
    high_candidate["candidate_parameters"]["estimated_net_gain_ratio"] = 0.02
    source = high_plan["source_indexes"]["viability_records_by_id"][high_candidate["source_viability_record_id"]]
    source["upper_bound"]["estimated_transfer_time_ms"] = source["upper_bound"]["motif_time_ms"] * 0.75
    high_results = _run_results(candidate_plan=high_plan, model_config=config)
    default_results = _run_results()

    assert _result_by_candidate(high_results)[low["candidate_id"]]["risk"]["transfer_risk"] > _result_by_candidate(default_results)[low["candidate_id"]]["risk"]["transfer_risk"]


def test_high_resource_pressure_is_not_blindly_suggested_for_high_fidelity():
    plan = _load_json(CANDIDATE_PLAN_PATH)
    candidate = next(candidate for candidate in plan["candidates"] if candidate["candidate_type"] == "fpga_candidate")
    candidate["candidate_parameters"]["risk_score"] = 0.95
    source = plan["source_indexes"]["viability_records_by_id"][candidate["source_viability_record_id"]]
    source["risk"]["fpga_resource_risk"] = 1.0
    results = _run_results(candidate_plan=plan)
    suggestion = _result_by_candidate(results)[candidate["candidate_id"]]["next_fidelity_suggestion"]["suggestion"]

    assert suggestion in {"hold_for_more_profile", "reject_before_high_fidelity", "promote_to_vivado_resource_request"}


def test_better_gain_and_lower_risk_receives_stronger_next_fidelity_suggestion():
    results = _run_results()
    suggestions = {
        result["next_fidelity_suggestion"]["suggestion"]
        for result in results["results"]
        if result["estimate"]["estimated_net_gain_ratio"] >= 0.10
        and result["risk"]["overall_l1_risk"] <= 0.45
    }

    assert suggestions
    assert suggestions <= {"promote_to_systemc_request", "promote_to_gem5_systemc_request", "promote_to_vivado_resource_request"}


def test_model_confidence_decreases_when_profile_quality_is_poor():
    plan = _load_json(CANDIDATE_PLAN_PATH)
    candidate = next(candidate for candidate in plan["candidates"] if candidate["candidate_type"] == "fpga_candidate")
    poor_plan = copy.deepcopy(plan)
    poor_candidate = _candidate_by_id(poor_plan)[candidate["candidate_id"]]
    source = poor_plan["source_indexes"]["viability_records_by_id"][poor_candidate["source_viability_record_id"]]
    source["risk"]["profile_quality_risk"] = 0.95
    poor_candidate["candidate_parameters"]["profile_quality_risk"] = 0.95
    default_confidence = _result_by_candidate(_run_results())[candidate["candidate_id"]]["estimate"]["estimated_model_confidence"]
    poor_confidence = _result_by_candidate(_run_results(candidate_plan=poor_plan))[candidate["candidate_id"]]["estimate"]["estimated_model_confidence"]

    assert poor_confidence < default_confidence


def test_no_result_is_interpreted_as_measured_performance():
    results = _run_results()
    forbidden = {"measured_latency", "measured_power", "measured_area", "final_performance_claim"}

    for result in results["results"]:
        assert not (forbidden & set(result))
        assert "not measured" in result["claim_boundary"].lower()
