#!/usr/bin/env python3
"""QE-IC system-level closed-loop DSE campaign regressions."""

from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

from dse_v2.campaigns import qe_ic as campaign


CAMPAIGN_CONFIG_PATH = Path("dse_v2/testdata/qe_ic_campaigns/qe_ic_closed_loop_dse_campaign_fixture.json")
CHECKED_IN_RESULTS_DIR = Path("artifacts/qe_ic_closed_loop_dse")
CLI_PATH = Path("dse_v2/scripts/dse/run_qe_ic_closed_loop_dse.py")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _run_campaign(config: dict | None = None) -> dict:
    campaign_config = config or _load_json(CAMPAIGN_CONFIG_PATH)
    return campaign.run_qe_ic_closed_loop_dse_campaign(campaign_config)


def _candidate_by_id(result: dict) -> dict[str, dict]:
    return {
        candidate["candidate_id"]: candidate
        for candidate in result["source_artifacts"]["layer4_candidate_plan"]["candidates"]
    }


def test_closed_loop_public_api_exports_expected_functions():
    assert campaign.run_qe_ic_closed_loop_dse_campaign
    assert campaign.validate_qe_ic_closed_loop_dse_results
    assert campaign.write_qe_ic_closed_loop_dse_artifacts
    assert campaign.load_qe_ic_closed_loop_dse_results


def test_closed_loop_campaign_fixture_loads():
    config = _load_json(CAMPAIGN_CONFIG_PATH)

    assert config["schema_version"] == "dse.qe_ic.closed_loop_dse_campaign_config.v1"
    assert config["campaign_id"] == "qe_ic_closed_loop_dse_fixture_campaign"
    assert config["artifact_mode"] == "artifact_replay"
    assert config["claim_boundary"].startswith("QE-IC closed-loop campaign config")


def test_campaign_runner_uses_existing_valid_layer_artifacts():
    result = _run_campaign()

    assert result["campaign_config"]["artifact_mode"] == "artifact_replay"
    assert all(row["status"] == "passed" for row in result["layer_status"])
    assert all(row["source"] == "artifact_replay" for row in result["layer_status"][:5])


def test_campaign_result_contains_layers_1_to_6():
    result = _run_campaign()
    layer_names = {row["layer"] for row in result["layer_status"]}

    assert {
        "layer1_workload_suite",
        "layer2_motif_profile",
        "layer3_target_viability",
        "layer4_candidate_plan",
        "layer5a_l1_cost_model",
        "layer6_feedback_calibration",
    }.issubset(layer_names)


def test_artifact_index_contains_all_required_layers():
    result = _run_campaign()

    assert set(result["artifact_index"]) == {
        "layer1_workload_suite",
        "layer2_motif_profile",
        "layer3_target_viability",
        "layer4_candidate_plan",
        "layer5a_l1_cost_model",
        "layer6_feedback_calibration",
    }


def test_system_summary_matches_underlying_artifacts():
    result = _run_campaign()
    source = result["source_artifacts"]
    feedback_result = result["feedback_summary"]
    summary = result["system_summary"]

    assert summary["workload_family_count"] == len(source["layer1_workload_suite"]["workload_families"])
    assert summary["motif_profile_count"] == len(source["layer2_motif_profile"]["family_target_profiles"])
    assert summary["target_viability_record_count"] == len(source["layer3_target_viability"]["viability_records"])
    assert summary["candidate_count"] == len(source["layer4_candidate_plan"]["candidates"])
    assert summary["promoted_candidate_count"] == source["layer4_candidate_plan"]["summary"]["promote_count"]
    assert summary["l1_result_count"] == len(source["layer5a_l1_cost_model"]["results"])
    assert summary["synthetic_label_count"] == feedback_result["metrics"]["candidate_label_coverage"]["labeled_candidate_count"]
    assert summary["promotion_precision"] == feedback_result["metrics"]["promotion_precision"]


def test_candidate_trajectory_links_layer4_layer5a_layer6():
    result = _run_campaign()
    candidates = _candidate_by_id(result)
    l1_ids = {
        row["candidate_id"]
        for row in result["source_artifacts"]["layer5a_l1_cost_model"]["results"]
    }
    feedback_ids = {
        row["candidate_id"]
        for row in result["feedback_summary"]["candidate_feedback_records"]
    }

    for row in result["candidate_trajectory"]:
        assert row["candidate_id"] in candidates
        if row["layer4_decision"] == "promote":
            assert row["candidate_id"] in l1_ids or row["candidate_id"] in feedback_ids


def test_candidate_validity_levels_do_not_include_hardware_proven():
    result = _run_campaign()

    assert all(
        trajectory["candidate_validity_level"] != "C5_hardware_proven"
        for trajectory in result["candidate_trajectory"]
    )


def test_next_round_plan_is_generated():
    result = _run_campaign()
    plan = result["next_round_plan"]

    assert plan["policy_version"] == result["adaptive_policy_state"]["policy_version"]
    assert plan["candidate_suggestions"]
    assert plan["acquisition_priorities"]


def test_stop_conditions_are_reported():
    result = _run_campaign()
    stop = result["next_round_plan"]["stopping_condition_evaluation"]

    assert stop["decision_basis"] == "synthetic_replay_stop_decision"
    assert stop["stop_decision"] in {"continue", "stop"}
    assert stop["conditions"]


def test_campaign_validation_passes_default_fixture():
    result = _run_campaign()
    validation = campaign.validate_qe_ic_closed_loop_dse_results(result)

    assert validation["status"] == "passed"
    assert validation["errors"] == []
    assert validation["candidate_trajectory_count"] == len(result["candidate_trajectory"])


def test_campaign_validation_fails_missing_layer():
    result = _run_campaign()
    result["artifact_index"].pop("layer6_feedback_calibration")

    validation = campaign.validate_qe_ic_closed_loop_dse_results(result)

    assert validation["status"] == "failed"
    assert any("artifact_index" in error["field"] for error in validation["errors"])


def test_campaign_validation_fails_broken_traceability():
    result = _run_campaign()
    result["candidate_trajectory"][0]["candidate_id"] = "missing_candidate"

    validation = campaign.validate_qe_ic_closed_loop_dse_results(result)

    assert validation["status"] == "failed"
    assert any("unknown candidate" in error["message"] for error in validation["errors"])


def test_campaign_validation_fails_inconsistent_summary():
    result = _run_campaign()
    result["system_summary"]["candidate_count"] += 1

    validation = campaign.validate_qe_ic_closed_loop_dse_results(result)

    assert validation["status"] == "failed"
    assert any("system_summary" in error["field"] for error in validation["errors"])


def test_campaign_validation_fails_forbidden_execution_results():
    result = _run_campaign()
    result["gem5_result"] = {"latency_ms": 1.0}

    validation = campaign.validate_qe_ic_closed_loop_dse_results(result)

    assert validation["status"] == "failed"
    assert any("forbidden" in error["message"].lower() for error in validation["errors"])


def test_campaign_writer_fail_closed(tmp_path: Path):
    bad_config = _load_json(CAMPAIGN_CONFIG_PATH)
    bad_config["artifact_paths"]["layer1_workload_suite"] = str(tmp_path / "missing.json")
    bad_path = tmp_path / "bad_campaign.json"
    bad_path.write_text(json.dumps(bad_config))

    result = campaign.write_qe_ic_closed_loop_dse_artifacts(tmp_path, bad_path)

    assert result["status"] == "failed"
    assert result["artifacts"] == ["qe_ic_closed_loop_dse_validation.json"]
    assert (tmp_path / "qe_ic_closed_loop_dse_validation.json").exists()
    assert not (tmp_path / "qe_ic_closed_loop_dse_results.json").exists()
    assert not (tmp_path / "qe_ic_closed_loop_dse_manifest.json").exists()
    assert not (tmp_path / "qe_ic_closed_loop_dse_readme.md").exists()


def test_campaign_writer_removes_stale_artifacts(tmp_path: Path):
    valid = campaign.write_qe_ic_closed_loop_dse_artifacts(tmp_path, CAMPAIGN_CONFIG_PATH)
    assert valid["status"] == "passed"
    bad_config = _load_json(CAMPAIGN_CONFIG_PATH)
    bad_config["artifact_paths"]["layer1_workload_suite"] = str(tmp_path / "missing.json")
    bad_path = tmp_path / "bad_campaign.json"
    bad_path.write_text(json.dumps(bad_config))

    failed = campaign.write_qe_ic_closed_loop_dse_artifacts(tmp_path, bad_path)

    assert failed["status"] == "failed"
    assert (tmp_path / "qe_ic_closed_loop_dse_validation.json").exists()
    assert not (tmp_path / "qe_ic_closed_loop_dse_results.json").exists()
    assert not (tmp_path / "qe_ic_closed_loop_dse_manifest.json").exists()
    assert not (tmp_path / "qe_ic_closed_loop_dse_readme.md").exists()


def test_checked_in_closed_loop_campaign_artifacts_match_builder_output(tmp_path: Path):
    campaign.write_qe_ic_closed_loop_dse_artifacts(tmp_path, CAMPAIGN_CONFIG_PATH)

    for artifact in [
        "qe_ic_closed_loop_dse_results.json",
        "qe_ic_closed_loop_dse_validation.json",
        "qe_ic_closed_loop_dse_manifest.json",
        "qe_ic_closed_loop_dse_readme.md",
    ]:
        assert (CHECKED_IN_RESULTS_DIR / artifact).read_text() == (tmp_path / artifact).read_text()


def test_closed_loop_manifest_lists_layers_1_to_6():
    manifest = _load_json(CHECKED_IN_RESULTS_DIR / "qe_ic_closed_loop_dse_manifest.json")

    assert manifest["layers"] == [
        "layer1_workload_suite",
        "layer2_motif_profile",
        "layer3_target_viability",
        "layer4_candidate_plan",
        "layer5a_l1_cost_model",
        "layer6_feedback_calibration",
    ]


def test_closed_loop_cli_emits_passed_status(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "--campaign",
            str(CAMPAIGN_CONFIG_PATH),
            "--out",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "passed"


def test_closed_loop_cli_is_thin_wrapper():
    tree = ast.parse(CLI_PATH.read_text())
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert function_names == {"parse_args", "main"}
    assert "promotion_precision" not in CLI_PATH.read_text()
    assert "false_promotion_rate" not in CLI_PATH.read_text()


def test_closed_loop_readme_explains_goal_boundary_and_results():
    readme = (CHECKED_IN_RESULTS_DIR / "qe_ic_closed_loop_dse_readme.md").read_text().lower()

    assert "layer-6 synthetic feedback" in readme
    assert "not measured hardware performance" in readme
    assert "does not prove fpga" in readme
