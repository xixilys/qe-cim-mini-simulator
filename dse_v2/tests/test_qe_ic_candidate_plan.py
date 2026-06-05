#!/usr/bin/env python3
"""QE-IC Layer-4 candidate-generation and promotion contract regressions."""

from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dse_v2.candidates import qe_ic
from dse_v2.profiling.qe_ic import validate_qe_ic_motif_profile
from dse_v2.viability.qe_ic import validate_qe_ic_target_viability
from dse_v2.workloads.qe_ic import validate_qe_ic_workload_suite


SUITE_PATH = Path("artifacts/qe_ic_workload_suite/qe_ic_workload_suite.json")
MOTIF_PROFILE_PATH = Path("artifacts/qe_ic_motif_profile/qe_ic_motif_profile.json")
TARGET_VIABILITY_PATH = Path("artifacts/qe_ic_target_viability/qe_ic_target_viability.json")
CAMPAIGN_PATH = Path("dse_v2/testdata/qe_ic_campaigns/qe_ic_layer4_campaign_fixture.json")
CHECKED_IN_PLAN_DIR = Path("artifacts/qe_ic_candidate_plan")
CLI_PATH = Path("dse_v2/scripts/dse/build_qe_ic_candidate_plan.py")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _inputs() -> tuple[dict, dict, dict, dict]:
    return (
        _load_json(SUITE_PATH),
        _load_json(MOTIF_PROFILE_PATH),
        _load_json(TARGET_VIABILITY_PATH),
        _load_json(CAMPAIGN_PATH),
    )


def _build_plan(config: dict | None = None) -> dict:
    suite, motif_profile, target_viability, campaign = _inputs()
    return qe_ic.build_qe_ic_candidate_plan(
        suite,
        motif_profile,
        target_viability,
        config or campaign,
    )


def _accelerator_candidates(plan: dict) -> list[dict]:
    return [
        candidate
        for candidate in plan["candidates"]
        if candidate["candidate_type"] in {"fpga_candidate", "hybrid_candidate"}
    ]


def _decision_by_candidate(plan: dict) -> dict[str, dict]:
    return {
        decision["candidate_id"]: decision
        for decision in plan["promotion_decisions"]
    }


def test_public_api_exports_expected_functions():
    assert qe_ic.build_qe_ic_candidate_plan
    assert qe_ic.validate_qe_ic_candidate_plan
    assert qe_ic.write_qe_ic_candidate_plan_artifacts
    assert qe_ic.load_qe_ic_candidate_plan


def test_campaign_fixture_loads():
    campaign = _load_json(CAMPAIGN_PATH)

    assert campaign["schema_version"] == "dse.qe_ic.layer4_campaign.v1"
    assert campaign["campaign_id"] == "qe_ic_layer4_fixture_campaign"
    assert campaign["promotion"]["next_fidelity"] == "L1_cost_model"
    assert campaign["promotion"]["budget"]["max_l1_cost_model_requests"] == 12
    assert campaign["candidate_generation"]["include_baseline_gpu"] is True


def test_inputs_layer1_layer2_layer3_are_validated():
    suite, motif_profile, target_viability, _campaign = _inputs()

    assert validate_qe_ic_workload_suite(suite)["status"] == "passed"
    assert validate_qe_ic_motif_profile(motif_profile)["status"] == "passed"
    assert validate_qe_ic_target_viability(target_viability)["status"] == "passed"


def test_candidate_generation_creates_gpu_baseline():
    plan = _build_plan()
    baselines = [
        candidate
        for candidate in plan["candidates"]
        if candidate["candidate_type"] == "baseline"
    ]

    assert baselines
    assert all(candidate["target_type"] == "gpu_only" for candidate in baselines)
    assert all(candidate["template_id"] == "gpu_baseline_reference" for candidate in baselines)
    assert all(
        _decision_by_candidate(plan)[candidate["candidate_id"]]["decision"] == "baseline"
        for candidate in baselines
    )


def test_reject_viability_records_do_not_generate_accelerator_candidates():
    plan = _build_plan()

    assert _accelerator_candidates(plan)
    assert all(
        candidate["source_viability_decision"] != "reject"
        for candidate in _accelerator_candidates(plan)
    )


def test_maybe_and_viable_records_generate_candidates():
    plan = _build_plan()
    accelerator_decisions = {
        candidate["source_viability_decision"]
        for candidate in _accelerator_candidates(plan)
    }

    assert "maybe" in accelerator_decisions
    assert accelerator_decisions.issubset({"maybe", "viable"})


def test_candidates_have_traceability():
    plan = _build_plan()

    for candidate in plan["candidates"]:
        traceability = candidate["traceability"]
        assert traceability["layer1_suite_id"] == plan["suite_id"]
        assert traceability["layer2_profile_artifact"] == "qe_ic_motif_profile.json"
        assert traceability["layer3_viability_artifact"] == "qe_ic_target_viability.json"
        assert candidate["source_viability_record_id"]


def test_candidate_ids_are_unique():
    plan = _build_plan()
    candidate_ids = [candidate["candidate_id"] for candidate in plan["candidates"]]

    assert len(candidate_ids) == len(set(candidate_ids))


def test_promotion_decisions_reference_known_candidates():
    plan = _build_plan()
    candidate_ids = {candidate["candidate_id"] for candidate in plan["candidates"]}

    assert plan["promotion_decisions"]
    assert all(
        decision["candidate_id"] in candidate_ids
        for decision in plan["promotion_decisions"]
    )


def test_evaluation_requests_reference_promoted_candidates():
    plan = _build_plan()
    promoted_ids = {
        decision["candidate_id"]
        for decision in plan["promotion_decisions"]
        if decision["decision"] == "promote"
    }

    assert plan["evaluation_requests"]
    assert all(
        request["candidate_id"] in promoted_ids
        for request in plan["evaluation_requests"]
    )
    assert all(request["status"] == "planned_not_executed" for request in plan["evaluation_requests"])


def test_budget_constraints_are_enforced():
    campaign = _load_json(CAMPAIGN_PATH)
    campaign["promotion"]["budget"]["max_l1_cost_model_requests"] = 3
    plan = _build_plan(campaign)

    assert plan["summary"]["promote_count"] <= 3
    assert plan["summary"]["budget_used"]["max_l1_cost_model_requests"] <= 3
    assert len(plan["evaluation_requests"]) == plan["summary"]["promote_count"]


def test_diversity_constraints_are_represented():
    plan = _build_plan()
    diversity = plan["summary"]["diversity"]

    assert diversity["target_type_required"] is True
    assert diversity["motif_required"] is True
    assert diversity["promoted_target_type_count"] >= 2
    assert diversity["promoted_motif_count"] >= 2


def test_policy_does_not_promote_only_one_motif_when_diversity_required():
    campaign = _load_json(CAMPAIGN_PATH)
    campaign["promotion"]["budget"]["max_l1_cost_model_requests"] = 4
    plan = _build_plan(campaign)
    promoted_motifs = {
        candidate["motif_id"]
        for candidate in plan["candidates"]
        if _decision_by_candidate(plan)[candidate["candidate_id"]]["decision"] == "promote"
    }

    assert len(promoted_motifs) > 1


def test_policy_prefers_lower_risk_when_gain_is_similar():
    suite, motif_profile, target_viability, campaign = _inputs()
    campaign["promotion"]["budget"]["max_l1_cost_model_requests"] = 1
    campaign["promotion"]["require_diversity_across_target_type"] = False
    campaign["promotion"]["require_diversity_across_motif"] = False
    target_viability = copy.deepcopy(target_viability)
    source = next(
        record
        for record in target_viability["viability_records"]
        if record["target_type"] == "fpga_only" and record["decision"] == "maybe"
    )
    gpu_source = next(
        record
        for record in target_viability["viability_records"]
        if record["target_type"] == "gpu_only" and record["decision"] == "baseline"
    )
    hybrid_source = next(
        record
        for record in target_viability["viability_records"]
        if record["target_type"] == "gpu_fpga_hybrid"
    )
    low_risk = copy.deepcopy(source)
    low_risk.update(
        workload_family_id="ground_state_band_structure",
        motif_id="fft_transpose",
        target_id="fpga_only_low_risk_fixture",
    )
    low_risk["viability_score"] = 0.50
    low_risk["upper_bound"]["estimated_net_gain_ratio"] = 0.080
    low_risk["upper_bound"]["runtime_ratio"] = 0.30
    low_risk["risk"]["overall_risk_score"] = 0.10
    high_risk = copy.deepcopy(source)
    high_risk.update(
        workload_family_id="phonon_dfpt",
        motif_id="reduction_collective",
        target_id="fpga_only_high_risk_fixture",
    )
    high_risk["viability_score"] = 0.52
    high_risk["upper_bound"]["estimated_net_gain_ratio"] = 0.081
    high_risk["upper_bound"]["runtime_ratio"] = 0.30
    high_risk["risk"]["overall_risk_score"] = 0.90
    gpu_record = copy.deepcopy(gpu_source)
    gpu_record["target_id"] = "gpu_only_synthetic_fixture"
    hybrid_record = copy.deepcopy(hybrid_source)
    hybrid_record["target_id"] = "gpu_fpga_hybrid_synthetic_fixture"
    hybrid_record["decision"] = "reject"
    target_viability["viability_records"] = [gpu_record, low_risk, high_risk, hybrid_record]
    target_viability["target_config"]["targets"] = [
        {
            "target_id": "gpu_only_synthetic_fixture",
            "target_type": "gpu_only",
            "gpu": {"name": "gpu", "memory_bandwidth_gbps": 1.0, "sync_overhead_us": 1.0},
        },
        {
            "target_id": "fpga_only_low_risk_fixture",
            "target_type": "fpga_only",
            "fpga": {"name": "low", "memory_bandwidth_gbps": 1.0, "sync_overhead_us": 1.0, "logic_budget_score": 0.5},
        },
        {
            "target_id": "fpga_only_high_risk_fixture",
            "target_type": "fpga_only",
            "fpga": {"name": "high", "memory_bandwidth_gbps": 1.0, "sync_overhead_us": 1.0, "logic_budget_score": 0.5},
        },
        {
            "target_id": "gpu_fpga_hybrid_synthetic_fixture",
            "target_type": "gpu_fpga_hybrid",
            "gpu": {"name": "gpu", "memory_bandwidth_gbps": 1.0, "sync_overhead_us": 1.0},
            "fpga": {"name": "fpga", "memory_bandwidth_gbps": 1.0, "sync_overhead_us": 1.0, "logic_budget_score": 0.5},
            "interconnect": {"type": "pcie", "bandwidth_gbps": 1.0, "latency_us": 1.0},
        },
    ]
    target_viability["summary"] = {
        "record_count": 4,
        "baseline_count": 1,
        "maybe_count": 2,
        "reject_count": 1,
        "viable_count": 0,
        "by_target_type": {
            "gpu_only": {
                "record_count": 1,
                "baseline_count": 1,
                "maybe_count": 0,
                "reject_count": 0,
                "viable_count": 0,
            },
            "fpga_only": {
                "record_count": 2,
                "baseline_count": 0,
                "maybe_count": 2,
                "reject_count": 0,
                "viable_count": 0,
            },
            "gpu_fpga_hybrid": {
                "record_count": 1,
                "baseline_count": 0,
                "maybe_count": 0,
                "reject_count": 1,
                "viable_count": 0,
            },
        },
    }
    plan = qe_ic.build_qe_ic_candidate_plan(suite, motif_profile, target_viability, campaign)
    promoted = [
        candidate
        for candidate in plan["candidates"]
        if _decision_by_candidate(plan)[candidate["candidate_id"]]["decision"] == "promote"
    ]

    assert len(promoted) == 1
    assert promoted[0]["motif_id"] == "fft_transpose"


def test_policy_holds_candidates_when_budget_exhausted():
    campaign = _load_json(CAMPAIGN_PATH)
    campaign["promotion"]["budget"]["max_l1_cost_model_requests"] = 2
    plan = _build_plan(campaign)

    assert plan["summary"]["promote_count"] == 2
    assert plan["summary"]["hold_count"] > 0
    assert any(
        "budget_exhausted" in decision["reason_codes"]
        for decision in plan["promotion_decisions"]
        if decision["decision"] == "hold"
    )


def test_validation_passes_default_fixture():
    plan = _build_plan()
    validation = qe_ic.validate_qe_ic_candidate_plan(plan)

    assert validation["status"] == "passed"
    assert validation["errors"] == []
    assert validation["candidate_count"] == len(plan["candidates"])


def test_validation_fails_budget_overuse():
    plan = _build_plan()
    plan["campaign_config"]["promotion"]["budget"]["max_l1_cost_model_requests"] = 1

    validation = qe_ic.validate_qe_ic_candidate_plan(plan)

    assert validation["status"] == "failed"
    assert any("budget" in error["field"] for error in validation["errors"])


def test_validation_fails_unknown_candidate_reference():
    plan = _build_plan()
    plan["promotion_decisions"][0]["candidate_id"] = "missing_candidate"

    validation = qe_ic.validate_qe_ic_candidate_plan(plan)

    assert validation["status"] == "failed"
    assert any("unknown candidate" in error["message"] for error in validation["errors"])


def test_validation_fails_forbidden_execution_results():
    plan = _build_plan()
    plan["systemc_results"] = []
    plan["evaluation_requests"][0]["execution_result"] = {"latency_ms": 1.0}

    validation = qe_ic.validate_qe_ic_candidate_plan(plan)

    assert validation["status"] == "failed"
    assert any("execution" in error["message"].lower() for error in validation["errors"])


def test_writer_emits_required_artifacts(tmp_path: Path):
    result = qe_ic.write_qe_ic_candidate_plan_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_VIABILITY_PATH,
        CAMPAIGN_PATH,
    )

    assert result["status"] == "passed"
    assert result["artifacts"] == [
        "qe_ic_candidate_plan.json",
        "qe_ic_candidate_plan_validation.json",
        "qe_ic_candidate_plan_manifest.json",
        "qe_ic_candidate_plan_readme.md",
    ]
    for artifact in result["artifacts"]:
        assert (tmp_path / artifact).exists()


def test_writer_fail_closed_for_invalid_layer3_viability(tmp_path: Path):
    target_path = tmp_path / "target_viability.json"
    target_viability = _load_json(TARGET_VIABILITY_PATH)
    target_viability["schema_version"] = "bad"
    target_path.write_text(json.dumps(target_viability))

    result = qe_ic.write_qe_ic_candidate_plan_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        target_path,
        CAMPAIGN_PATH,
    )

    assert result["status"] == "failed"
    assert result["artifacts"] == ["qe_ic_candidate_plan_validation.json"]
    assert (tmp_path / "qe_ic_candidate_plan_validation.json").exists()
    assert not (tmp_path / "qe_ic_candidate_plan.json").exists()
    assert not (tmp_path / "qe_ic_candidate_plan_manifest.json").exists()
    assert not (tmp_path / "qe_ic_candidate_plan_readme.md").exists()


def test_writer_fail_closed_removes_stale_canonical_artifacts(tmp_path: Path):
    valid_result = qe_ic.write_qe_ic_candidate_plan_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_VIABILITY_PATH,
        CAMPAIGN_PATH,
    )
    assert valid_result["status"] == "passed"

    target_path = tmp_path / "target_viability.json"
    target_viability = _load_json(TARGET_VIABILITY_PATH)
    target_viability["schema_version"] = "bad"
    target_path.write_text(json.dumps(target_viability))
    failed_result = qe_ic.write_qe_ic_candidate_plan_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        target_path,
        CAMPAIGN_PATH,
    )

    assert failed_result["status"] == "failed"
    assert (tmp_path / "qe_ic_candidate_plan_validation.json").exists()
    assert not (tmp_path / "qe_ic_candidate_plan.json").exists()
    assert not (tmp_path / "qe_ic_candidate_plan_manifest.json").exists()
    assert not (tmp_path / "qe_ic_candidate_plan_readme.md").exists()


def test_checked_in_qe_ic_candidate_plan_artifacts_match_builder_output(tmp_path: Path):
    qe_ic.write_qe_ic_candidate_plan_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_VIABILITY_PATH,
        CAMPAIGN_PATH,
    )

    for artifact in [
        "qe_ic_candidate_plan.json",
        "qe_ic_candidate_plan_validation.json",
        "qe_ic_candidate_plan_manifest.json",
        "qe_ic_candidate_plan_readme.md",
    ]:
        assert (CHECKED_IN_PLAN_DIR / artifact).read_text() == (tmp_path / artifact).read_text()


def test_manifest_declares_layer5_downstream():
    manifest = _load_json(CHECKED_IN_PLAN_DIR / "qe_ic_candidate_plan_manifest.json")

    assert "layer5_evaluation_runner" in manifest["downstream_consumers"]
    assert manifest["artifact_role"] == "dse_layer4_candidate_plan"


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
            "--campaign",
            str(CAMPAIGN_PATH),
            "--out",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"


def test_core_logic_not_in_cli():
    tree = ast.parse(CLI_PATH.read_text())
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert function_names == {"parse_args", "main"}
    assert "promotion_score" not in CLI_PATH.read_text()
    assert "candidate_parameters" not in CLI_PATH.read_text()


def test_claim_boundary_blocks_execution_and_final_performance_claims():
    plan = _build_plan()
    lowered = plan["claim_boundary"].lower()

    assert "does not contain executed systemc/gem5/vivado/qe results" in lowered
    assert "final performance claims" in lowered
    assert qe_ic.validate_qe_ic_candidate_plan(plan)["status"] == "passed"


def test_replay_policy_reduces_false_promotions_on_synthetic_fixture():
    labels = [
        {"candidate_id": "a", "high_fidelity_label": "false_promotion"},
        {"candidate_id": "b", "high_fidelity_label": "useful"},
        {"candidate_id": "c", "high_fidelity_label": "useful"},
    ]
    decisions = [
        {"candidate_id": "a", "decision": "hold"},
        {"candidate_id": "b", "decision": "promote"},
        {"candidate_id": "c", "decision": "promote"},
    ]
    replay = qe_ic.evaluate_qe_ic_promotion_replay(decisions, labels)

    assert replay["false_promotion_count"] == 0
    assert replay["avoided_false_promotion_count"] == 1


def test_replay_policy_tracks_wasted_budget_metric():
    labels = [
        {"candidate_id": "a", "high_fidelity_label": "false_promotion"},
        {"candidate_id": "b", "high_fidelity_label": "useful"},
    ]
    decisions = [
        {"candidate_id": "a", "decision": "promote"},
        {"candidate_id": "b", "decision": "hold"},
    ]
    replay = qe_ic.evaluate_qe_ic_promotion_replay(decisions, labels)

    assert replay["wasted_budget_count"] == 1
    assert replay["wasted_budget_ratio"] == pytest.approx(1.0)


def test_replay_policy_reports_promotion_precision_metric():
    labels = [
        {"candidate_id": "a", "high_fidelity_label": "false_promotion"},
        {"candidate_id": "b", "high_fidelity_label": "useful"},
        {"candidate_id": "c", "high_fidelity_label": "useful"},
    ]
    decisions = [
        {"candidate_id": "a", "decision": "promote"},
        {"candidate_id": "b", "decision": "promote"},
        {"candidate_id": "c", "decision": "hold"},
    ]
    replay = qe_ic.evaluate_qe_ic_promotion_replay(decisions, labels)

    assert replay["promotion_precision"] == pytest.approx(0.5)
    assert replay["promoted_count"] == 2
