#!/usr/bin/env python3
"""QE-IC real GPU-baseline opportunity-analysis regressions."""

from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dse_v2.evidence import qe_ic as opportunity


CONFIG_PATH = Path("dse_v2/testdata/qe_ic_evidence/qe_ic_real_baseline_opportunity_config_fixture.json")
GPU_BASELINE_PATH = Path("dse_v2/testdata/qe_ic_evidence/qe_ic_gpu_baseline_measurements_fixture.json")
CANDIDATE_RESULTS_PATH = Path("dse_v2/testdata/qe_ic_evidence/qe_ic_candidate_high_fidelity_results_fixture.json")
CHECKED_IN_RESULTS_DIR = Path("artifacts/qe_ic_real_baseline_opportunity")
CLI_PATH = Path("dse_v2/scripts/dse/analyze_qe_ic_real_baseline_opportunity.py")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _input_artifacts(config: dict | None = None) -> dict[str, dict]:
    opportunity_config = copy.deepcopy(config or _load_json(CONFIG_PATH))
    paths = opportunity_config["input_artifacts"]
    return {
        "workload_suite": _load_json(Path(paths["layer1_workload_suite"])),
        "motif_profile": _load_json(Path(paths["layer2_motif_profile"])),
        "target_viability": _load_json(Path(paths["layer3_target_viability"])),
        "candidate_plan": _load_json(Path(paths["layer4_candidate_plan"])),
        "l1_results": _load_json(Path(paths["layer5a_l1_cost_model"])),
        "closed_loop_results": _load_json(Path(paths["layer6_closed_loop_dse"])),
        "gpu_baseline_measurements": _load_json(Path(paths["gpu_baseline_measurements"])),
        "candidate_high_fidelity_results": _load_json(Path(paths["candidate_high_fidelity_results"])),
        "opportunity_config": opportunity_config,
    }


def _run_analysis(
    *,
    gpu_baseline_measurements: dict | None = None,
    candidate_high_fidelity_results: dict | None = None,
    opportunity_config: dict | None = None,
) -> dict:
    inputs = _input_artifacts(opportunity_config)
    return opportunity.analyze_qe_ic_real_baseline_opportunity(
        workload_suite=inputs["workload_suite"],
        motif_profile=inputs["motif_profile"],
        target_viability=inputs["target_viability"],
        candidate_plan=inputs["candidate_plan"],
        l1_results=inputs["l1_results"],
        closed_loop_results=inputs["closed_loop_results"],
        gpu_baseline_measurements=gpu_baseline_measurements or inputs["gpu_baseline_measurements"],
        candidate_high_fidelity_results=candidate_high_fidelity_results
        or inputs["candidate_high_fidelity_results"],
        opportunity_config=inputs["opportunity_config"],
    )


def _first_candidate(candidate_plan: dict, target_type: str) -> dict:
    inputs = _input_artifacts()
    tracked = {
        row["candidate_id"]
        for row in inputs["l1_results"]["results"]
    } & {
        row["candidate_id"]
        for row in inputs["closed_loop_results"]["candidate_trajectory"]
    }
    tracked_candidate = next(
        (
            candidate
            for candidate in candidate_plan["candidates"]
            if candidate["target_type"] == target_type and candidate["candidate_id"] in tracked
        ),
        None,
    )
    if tracked_candidate is not None:
        return tracked_candidate
    return next(
        candidate
        for candidate in candidate_plan["candidates"]
        if candidate["target_type"] == target_type
    )


def _measured_baseline(
    *,
    family_id: str,
    runtime_mean: float = 100.0,
    gpu_util: float = 0.62,
    case_id: str = "controlled_case",
    program: str = "pw.x",
    input_deck_hash: str = "sha256:" + "1" * 64,
    precision: str = "fp64_mixed",
) -> dict:
    return {
        "schema_version": "dse.qe_ic.gpu_baseline_measurements.v1",
        "measurement_role": "gpu_only_baseline",
        "evidence_status": "measured",
        "measurements_are_real": True,
        "platform": {
            "gpu_name": "controlled-a100",
            "cpu_name": "controlled-host",
            "memory": "80GB HBM fixture replacement",
            "qe_version": "7.5-controlled",
            "cuda_version": "12.4-controlled",
            "driver_version": "controlled",
            "precision": precision,
        },
        "baseline_records": [
            {
                "baseline_id": "controlled_gpu_baseline",
                "workload_family_id": family_id,
                "case_id": case_id,
                "program": program,
                "input_deck_hash": input_deck_hash,
                "precision": precision,
                "target_type": "gpu_only",
                "runtime_seconds_runs": [99.0, 100.0, 101.0],
                "runtime_seconds_mean": runtime_mean,
                "runtime_seconds_std": 1.0,
                "confidence_interval_95": {"low": 98.0, "high": 102.0},
                "gpu_utilization_mean": gpu_util,
                "gpu_memory_bandwidth_utilization_mean": 0.66,
                "host_device_transfer_seconds": 4.0,
                "communication_seconds": 3.0,
                "profile_artifact_hash": "sha256:" + "2" * 64,
                "evidence_status": "measured",
            }
        ],
        "claim_boundary": (
            "GPU baseline records are only real measurement evidence when "
            "measurements_are_real is true and evidence_status is measured."
        ),
    }


def _candidate_results_artifact(candidate_result: dict, *, real: bool = True) -> dict:
    return {
        "schema_version": "dse.qe_ic.candidate_high_fidelity_results.v1",
        "results_are_real": real,
        "candidate_results": [candidate_result],
    }


def _measured_candidate_result(
    candidate: dict,
    *,
    workflow_mean: float = 80.0,
    ci_high: float = 82.0,
    target_type: str | None = None,
    evidence_level: str = "trace_replay",
    evidence_status: str = "high_fidelity_estimate",
    resource_feasible: bool = True,
    timing_feasible: bool = True,
    runtime_runs: list[float] | None = None,
    kernel_only: bool = False,
    transfer_seconds: float = 6.0,
    workflow_overhead_seconds: float = 5.0,
    case_id: str = "controlled_case",
    program: str = "pw.x",
    input_deck_hash: str = "sha256:" + "1" * 64,
    precision: str = "fp64_mixed",
    tool_provenance: dict | None = None,
) -> dict:
    workflow_runtime = None if kernel_only else workflow_mean
    return {
        "candidate_id": candidate["candidate_id"],
        "workload_family_id": candidate["workload_family_id"],
        "motif_id": candidate["motif_id"],
        "target_type": target_type or candidate["target_type"],
        "case_id": case_id,
        "program": program,
        "input_deck_hash": input_deck_hash,
        "precision": precision,
        "evidence_level": evidence_level,
        "evidence_status": evidence_status,
        "architecture_summary": {
            "architecture_id": f"arch_{candidate['candidate_id'][:16]}",
            "architecture_family": candidate["candidate_parameters"]["template_family"],
            "gpu_role": "primary_compute" if (target_type or candidate["target_type"]) == "gpu_fpga_hybrid" else "none",
            "fpga_role": "workflow_trace_replay_sidecar",
            "host_role": "scf_control_retained",
            "dataflow_summary": "controlled workflow-level replay",
            "memory_interface": "pcie_hbm",
            "synchronization_model": "batched_barrier",
        },
        "runtime_seconds_runs": runtime_runs or [79.0, 80.0, 81.0],
        "runtime_seconds_mean": workflow_mean,
        "runtime_seconds_std": 1.0,
        "confidence_interval_95": {"low": 78.0, "high": ci_high},
        "workflow_runtime_seconds_mean": workflow_runtime,
        "kernel_runtime_seconds_mean": 60.0,
        "transfer_overhead_seconds": transfer_seconds,
        "workflow_overhead_seconds": workflow_overhead_seconds,
        "resource": {
            "resource_feasible": resource_feasible,
            "timing_feasible": timing_feasible,
            "lut_utilization": 0.62,
            "ff_utilization": 0.55,
            "bram_utilization": 0.57,
            "dsp_utilization": 0.60,
            "hbm_port_utilization": 0.50,
            "fmax_mhz": 280.0,
        },
        "evidence_artifact_hash": "sha256:" + "3" * 64,
        "tool_provenance": tool_provenance or {
            "tool": "controlled_trace_replay",
            "version": "test-fixture",
            "run_id": "controlled_trace_run",
            "config_hash": "sha256:" + "4" * 64,
            "output_artifact_hash": "sha256:" + "5" * 64,
        },
        "claim_boundary": (
            "This candidate result is not a real measured result unless "
            "results_are_real is true and evidence_status is measured or "
            "high_fidelity_estimate with explicit tool provenance."
        ),
    }


def _controlled_pass_inputs(target_type: str = "gpu_fpga_hybrid") -> tuple[dict, dict, dict]:
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], target_type)
    baseline = _measured_baseline(family_id=candidate["workload_family_id"])
    result = _measured_candidate_result(candidate)
    return baseline, _candidate_results_artifact(result), candidate


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _report_with_temp_external_evidence(
    tmp_path: Path,
    *,
    gpu_baseline_measurements: dict,
    candidate_high_fidelity_results: dict,
) -> dict:
    config = _load_json(CONFIG_PATH)
    baseline_path = tmp_path / "gpu_baseline.json"
    candidate_path = tmp_path / "candidate_results.json"
    _write_json(baseline_path, gpu_baseline_measurements)
    _write_json(candidate_path, candidate_high_fidelity_results)
    config["input_artifacts"]["gpu_baseline_measurements"] = str(baseline_path)
    config["input_artifacts"]["candidate_high_fidelity_results"] = str(candidate_path)
    report = _run_analysis(
        gpu_baseline_measurements=gpu_baseline_measurements,
        candidate_high_fidelity_results=candidate_high_fidelity_results,
        opportunity_config=config,
    )
    return report


def test_public_api_exports_expected_functions():
    assert opportunity.analyze_qe_ic_real_baseline_opportunity
    assert opportunity.validate_qe_ic_real_baseline_opportunity_report
    assert opportunity.write_qe_ic_real_baseline_opportunity_artifacts
    assert opportunity.load_qe_ic_real_baseline_opportunity_report


def test_opportunity_config_fixture_loads():
    config = _load_json(CONFIG_PATH)

    assert config["schema_version"] == "dse.qe_ic.real_baseline_opportunity_config.v1"
    assert config["analysis_role"] == "claim_gated_gpu_vs_fpga_hybrid_opportunity_analysis"
    assert set(config["input_artifacts"]) == {
        "layer1_workload_suite",
        "layer2_motif_profile",
        "layer3_target_viability",
        "layer4_candidate_plan",
        "layer5a_l1_cost_model",
        "layer6_closed_loop_dse",
        "gpu_baseline_measurements",
        "candidate_high_fidelity_results",
    }
    assert "does not allow l1 estimates" in config["claim_boundary"].lower()


def test_gpu_baseline_measurement_fixture_loads():
    baseline = _load_json(GPU_BASELINE_PATH)

    assert baseline["schema_version"] == "dse.qe_ic.gpu_baseline_measurements.v1"
    assert baseline["measurement_role"] == "gpu_only_baseline"
    assert baseline["measurements_are_real"] is False
    assert baseline["baseline_records"]


def test_candidate_high_fidelity_fixture_loads():
    results = _load_json(CANDIDATE_RESULTS_PATH)

    assert results["schema_version"] == "dse.qe_ic.candidate_high_fidelity_results.v1"
    assert results["results_are_real"] is False
    assert {row["evidence_level"] for row in results["candidate_results"]} >= {
        "l1_estimate_only",
        "trace_replay",
    }


def test_fixture_evidence_cannot_make_real_claim():
    report = _run_analysis()

    assert report["system_conclusion"]["overall_verdict"] == "fixture_only_inconclusive"
    assert report["system_conclusion"]["best_candidate_id"] is None
    assert all(not row["claim_allowed"] for row in report["opportunity_records"])
    assert all(row["is_real_measurement_claim"] is False for row in report["opportunity_records"])
    assert "insufficient to conclude" in report["system_conclusion"]["answer_to_research_question"].lower()


def test_fixture_transfer_overhead_still_inconclusive():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    fixture_baseline = copy.deepcopy(inputs["gpu_baseline_measurements"])
    fixture_baseline["baseline_records"] = [
        {
            **fixture_baseline["baseline_records"][0],
            "workload_family_id": candidate["workload_family_id"],
            "case_id": "controlled_case",
            "evidence_status": "fixture_example",
            "input_deck_hash": "sha256:" + "1" * 64,
            "precision": "fp64_mixed",
            "program": "pw.x",
        }
    ]
    fixture_result = _measured_candidate_result(
        candidate,
        transfer_seconds=60.0,
        evidence_status="fixture_example",
    )
    fixture_result.pop("tool_provenance")

    report = _run_analysis(
        gpu_baseline_measurements=fixture_baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(fixture_result, real=False),
    )

    row = report["opportunity_records"][0]
    assert "transfer_overhead_dominates" in row["failure_reasons"]
    assert row["verdict"] == "fixture_only_inconclusive"
    assert row["claim_allowed"] is False


def test_l1_estimate_only_cannot_make_opportunity_claim():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "fpga_only")
    baseline = _measured_baseline(family_id=candidate["workload_family_id"])
    result = _measured_candidate_result(
        candidate,
        evidence_level="l1_estimate_only",
        evidence_status="high_fidelity_estimate",
    )

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["claim_allowed"] is False
    assert row["claim_strength"] != "strong"
    assert row["verdict"] == "fpga_or_hybrid_inconclusive"
    assert "l1_only_insufficient" in row["claim_blockers"]


def test_missing_gpu_baseline_blocks_claim():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "fpga_only")
    baseline = _measured_baseline(family_id="different_workload_family")
    result = _measured_candidate_result(candidate)

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["gpu_baseline_id"] is None
    assert row["claim_allowed"] is False
    assert row["verdict"] == "evidence_missing"
    assert "gpu_baseline_missing" in row["claim_blockers"]


def test_claim_gate_fails_when_baseline_case_id_mismatch():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    baseline = _measured_baseline(family_id=candidate["workload_family_id"], case_id="different_case")
    result = _measured_candidate_result(candidate, case_id="controlled_case")

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["gpu_baseline_id"] is None
    assert row["claim_allowed"] is False
    assert "gpu_baseline_missing" in row["claim_blockers"]


def test_claim_gate_fails_when_input_deck_hash_mismatch():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    baseline = _measured_baseline(
        family_id=candidate["workload_family_id"],
        input_deck_hash="sha256:" + "9" * 64,
    )
    result = _measured_candidate_result(candidate, input_deck_hash="sha256:" + "1" * 64)

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["gpu_baseline_id"] is None
    assert row["claim_allowed"] is False
    assert "gpu_baseline_missing" in row["claim_blockers"]


def test_claim_gate_uses_exact_baseline_not_first_family_record():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    wrong = _measured_baseline(
        family_id=candidate["workload_family_id"],
        runtime_mean=1000.0,
        case_id="wrong_case",
    )["baseline_records"][0]
    right = _measured_baseline(
        family_id=candidate["workload_family_id"],
        runtime_mean=100.0,
        case_id="controlled_case",
    )["baseline_records"][0]
    wrong["baseline_id"] = "wrong_first_family_baseline"
    right["baseline_id"] = "right_exact_baseline"
    baseline = _measured_baseline(family_id=candidate["workload_family_id"])
    baseline["baseline_records"] = [wrong, right]
    result = _measured_candidate_result(candidate, workflow_mean=80.0, case_id="controlled_case")

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["gpu_baseline_id"] == "right_exact_baseline"
    assert row["speedup_vs_gpu_mean"] == pytest.approx(1.25)


def test_speedup_vs_gpu_is_computed_correctly():
    baseline, candidates, _candidate = _controlled_pass_inputs()

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=candidates,
    )

    assert report["opportunity_records"][0]["speedup_vs_gpu_mean"] == pytest.approx(1.25)


def test_conservative_ci_speedup_is_computed_correctly():
    baseline, candidates, _candidate = _controlled_pass_inputs()

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=candidates,
    )

    assert report["opportunity_records"][0]["speedup_vs_gpu_conservative_ci"] == pytest.approx(98.0 / 82.0)


def test_claim_gate_passes_for_valid_measured_speedup_fixture():
    baseline, candidates, candidate = _controlled_pass_inputs(target_type="gpu_fpga_hybrid")

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=candidates,
    )

    row = report["opportunity_records"][0]
    assert row["candidate_id"] == candidate["candidate_id"]
    assert row["workload_family_id"] == candidate["workload_family_id"]
    assert row["motif_id"] == candidate["motif_id"]
    assert row["speedup_vs_gpu_mean"] == pytest.approx(1.25)
    assert row["speedup_vs_gpu_conservative_ci"] == pytest.approx(98.0 / 82.0)
    assert row["claim_allowed"] is True
    assert row["claim_strength"] == "strong"
    assert row["verdict"] == "hybrid_opportunity_found"


def test_claim_gate_fails_when_ci_crosses_one():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    baseline = _measured_baseline(family_id=candidate["workload_family_id"])
    result = _measured_candidate_result(candidate, ci_high=105.0)

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["claim_allowed"] is False
    assert "confidence_interval_crosses_one" in row["claim_blockers"]


def test_claim_gate_fails_when_resource_infeasible():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "fpga_only")
    baseline = _measured_baseline(family_id=candidate["workload_family_id"])
    result = _measured_candidate_result(candidate, resource_feasible=False)

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["verdict"] == "candidate_invalid_resource"
    assert "resource_infeasible" in row["claim_blockers"]


def test_claim_gate_fails_when_timing_infeasible():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "fpga_only")
    baseline = _measured_baseline(family_id=candidate["workload_family_id"])
    result = _measured_candidate_result(candidate, timing_feasible=False)

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["verdict"] == "candidate_invalid_resource"
    assert "timing_infeasible" in row["claim_blockers"]


def test_claim_gate_fails_for_kernel_only_result():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "fpga_only")
    baseline = _measured_baseline(family_id=candidate["workload_family_id"])
    result = _measured_candidate_result(candidate, kernel_only=True)

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["claim_allowed"] is False
    assert row["speedup_vs_gpu_mean"] is None
    assert "kernel_only_insufficient" in row["claim_blockers"]


def test_failure_reasons_include_transfer_overhead_when_dominant():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    baseline = _measured_baseline(family_id=candidate["workload_family_id"])
    result = _measured_candidate_result(candidate, transfer_seconds=35.0)

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["verdict"] == "candidate_invalid_transfer_overhead"
    assert "transfer_overhead_dominates" in row["failure_reasons"]


def test_failure_reasons_include_gpu_dominant_when_gpu_utilization_high():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "fpga_only")
    baseline = _measured_baseline(family_id=candidate["workload_family_id"], gpu_util=0.90)
    result = _measured_candidate_result(candidate, workflow_mean=96.0, ci_high=101.0)

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert "gpu_utilization_high" in row["failure_reasons"]
    assert row["verdict"] == "gpu_dominant_no_fpga_opportunity"


def test_report_system_conclusion_matches_records():
    baseline, candidates, _candidate = _controlled_pass_inputs(target_type="gpu_fpga_hybrid")

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=candidates,
    )

    assert report["system_conclusion"]["overall_verdict"] == "hybrid_opportunity_found"
    assert report["system_conclusion"]["best_candidate_id"] == report["opportunity_records"][0]["candidate_id"]
    assert report["system_conclusion"]["best_speedup_vs_gpu"] == report["opportunity_records"][0]["speedup_vs_gpu_mean"]


def test_validation_passes_default_fixture():
    report = _run_analysis()
    validation = opportunity.validate_qe_ic_real_baseline_opportunity_report(report)

    assert validation["status"] == "passed"
    assert validation["errors"] == []
    assert validation["opportunity_record_count"] == len(report["opportunity_records"])


def test_validation_fails_inconsistent_speedup():
    baseline, candidates, _candidate = _controlled_pass_inputs()
    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=candidates,
    )
    report["opportunity_records"][0]["speedup_vs_gpu_mean"] = 9.99

    validation = opportunity.validate_qe_ic_real_baseline_opportunity_report(report)

    assert validation["status"] == "failed"
    assert any("speedup_vs_gpu_mean" in error["field"] for error in validation["errors"])


def test_validation_fails_strong_claim_from_fixture():
    report = _run_analysis()
    report["opportunity_records"][0]["claim_strength"] = "strong"
    report["opportunity_records"][0]["claim_allowed"] = True

    validation = opportunity.validate_qe_ic_real_baseline_opportunity_report(report)

    assert validation["status"] == "failed"
    assert any("fixture" in error["message"].lower() for error in validation["errors"])


def test_validation_fails_opportunity_found_without_claim_allowed():
    baseline, candidates, _candidate = _controlled_pass_inputs()
    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=candidates,
    )
    report["opportunity_records"][0]["claim_allowed"] = False

    validation = opportunity.validate_qe_ic_real_baseline_opportunity_report(report)

    assert validation["status"] == "failed"
    assert any("claim_allowed" in error["message"] for error in validation["errors"])


def test_validation_fails_missing_referenced_input_artifact(tmp_path: Path):
    report = _run_analysis()
    report["input_artifact_index"]["layer1_workload_suite"] = str(tmp_path / "missing_layer1.json")

    validation = opportunity.validate_qe_ic_real_baseline_opportunity_report(report)

    assert validation["status"] == "failed"
    assert any("input_artifact_index.layer1_workload_suite" in error["field"] for error in validation["errors"])


def test_validation_fails_superiority_claim_outside_system_conclusion():
    report = _run_analysis()
    report["unvetted_summary"] = "FPGA is stronger than GPU for this workflow."

    validation = opportunity.validate_qe_ic_real_baseline_opportunity_report(report)

    assert validation["status"] == "failed"
    assert any("superiority claim outside system_conclusion" in error["message"] for error in validation["errors"])


def test_validation_fails_raw_candidate_result_not_in_referenced_artifact(tmp_path: Path):
    baseline, candidates, _candidate = _controlled_pass_inputs()
    report = _report_with_temp_external_evidence(
        tmp_path,
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=candidates,
    )
    report["opportunity_records"][0]["raw_claim_gate_inputs"]["candidate_result"]["runtime_seconds_mean"] = 77.0

    validation = opportunity.validate_qe_ic_real_baseline_opportunity_report(report)

    assert validation["status"] == "failed"
    assert any("raw_claim_gate_inputs.candidate_result" in error["field"] for error in validation["errors"])


def test_validation_fails_raw_gpu_baseline_not_in_referenced_artifact(tmp_path: Path):
    baseline, candidates, _candidate = _controlled_pass_inputs()
    report = _report_with_temp_external_evidence(
        tmp_path,
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=candidates,
    )
    report["opportunity_records"][0]["raw_claim_gate_inputs"]["gpu_baseline_record"]["runtime_seconds_mean"] = 999.0

    validation = opportunity.validate_qe_ic_real_baseline_opportunity_report(report)

    assert validation["status"] == "failed"
    assert any("raw_claim_gate_inputs.gpu_baseline_record" in error["field"] for error in validation["errors"])


def test_validation_fails_raw_gpu_baseline_null_when_referenced_artifact_has_match(tmp_path: Path):
    baseline, candidates, _candidate = _controlled_pass_inputs()
    report = _report_with_temp_external_evidence(
        tmp_path,
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=candidates,
    )
    report["opportunity_records"][0]["raw_claim_gate_inputs"]["gpu_baseline_record"] = None

    validation = opportunity.validate_qe_ic_real_baseline_opportunity_report(report)

    assert validation["status"] == "failed"
    assert any("raw_claim_gate_inputs.gpu_baseline_record" in error["field"] for error in validation["errors"])


def test_validation_fails_raw_claim_gate_inputs_tampered_to_measured(tmp_path: Path):
    fixture_report = _run_analysis()
    measured_baseline, measured_candidates, _candidate = _controlled_pass_inputs()
    config = _load_json(CONFIG_PATH)
    fixture_baseline_path = tmp_path / "fixture_baseline.json"
    fixture_candidate_path = tmp_path / "fixture_candidates.json"
    _write_json(fixture_baseline_path, _load_json(GPU_BASELINE_PATH))
    _write_json(fixture_candidate_path, _load_json(CANDIDATE_RESULTS_PATH))
    config["input_artifacts"]["gpu_baseline_measurements"] = str(fixture_baseline_path)
    config["input_artifacts"]["candidate_high_fidelity_results"] = str(fixture_candidate_path)
    fixture_report["input_artifact_index"] = config["input_artifacts"]
    row = fixture_report["opportunity_records"][0]
    row["raw_claim_gate_inputs"]["gpu_baseline_record"] = measured_baseline["baseline_records"][0]
    row["raw_claim_gate_inputs"]["candidate_result"] = measured_candidates["candidate_results"][0]
    row["claim_allowed"] = True
    row["claim_strength"] = "strong"
    row["claim_blockers"] = []
    row["failure_reasons"] = ["speedup_claim_gate_passed"]
    row["verdict"] = "hybrid_opportunity_found"

    validation = opportunity.validate_qe_ic_real_baseline_opportunity_report(fixture_report)

    assert validation["status"] == "failed"
    assert any("referenced artifact" in error["message"] for error in validation["errors"])


def test_validation_fails_opportunity_record_identity_mismatches_raw_candidate(tmp_path: Path):
    baseline, candidates, _candidate = _controlled_pass_inputs()
    report = _report_with_temp_external_evidence(
        tmp_path,
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=candidates,
    )
    row = report["opportunity_records"][0]
    row["candidate_id"] = "misattributed_candidate"
    report["system_conclusion"]["best_candidate_id"] = "misattributed_candidate"

    validation = opportunity.validate_qe_ic_real_baseline_opportunity_report(report)

    assert validation["status"] == "failed"
    assert any("candidate_id" in error["field"] for error in validation["errors"])


def test_validation_fails_candidate_result_not_in_layer4_candidate_plan():
    inputs = _input_artifacts()
    candidate = copy.deepcopy(_first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid"))
    result = _measured_candidate_result(candidate)
    result["candidate_id"] = "not_in_layer4_candidate_plan"
    candidates = _candidate_results_artifact(result)

    validation = opportunity.validate_qe_ic_opportunity_input_artifacts(
        workload_suite=inputs["workload_suite"],
        motif_profile=inputs["motif_profile"],
        target_viability=inputs["target_viability"],
        candidate_plan=inputs["candidate_plan"],
        l1_results=inputs["l1_results"],
        closed_loop_results=inputs["closed_loop_results"],
        gpu_baseline_measurements=_measured_baseline(family_id=candidate["workload_family_id"]),
        candidate_high_fidelity_results=candidates,
    )

    assert validation["status"] == "failed"
    assert any("Layer-4" in error["message"] or "layer4" in error["field"] for error in validation["errors"])


def test_validation_fails_candidate_result_not_in_closed_loop_trajectory():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    result = _measured_candidate_result(candidate)
    closed_loop = copy.deepcopy(inputs["closed_loop_results"])
    closed_loop["candidate_trajectory"] = [
        row
        for row in closed_loop["candidate_trajectory"]
        if row["candidate_id"] != candidate["candidate_id"]
    ]

    validation = opportunity.validate_qe_ic_opportunity_input_artifacts(
        workload_suite=inputs["workload_suite"],
        motif_profile=inputs["motif_profile"],
        target_viability=inputs["target_viability"],
        candidate_plan=inputs["candidate_plan"],
        l1_results=inputs["l1_results"],
        closed_loop_results=closed_loop,
        gpu_baseline_measurements=_measured_baseline(family_id=candidate["workload_family_id"]),
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    assert validation["status"] == "failed"
    assert any("Layer-6" in error["message"] or "closed_loop" in error["field"] for error in validation["errors"])


def test_unknown_candidate_result_cannot_make_opportunity_claim():
    inputs = _input_artifacts()
    candidate = copy.deepcopy(_first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid"))
    result = _measured_candidate_result(candidate)
    result["candidate_id"] = "not_in_layer4_candidate_plan"

    report = _run_analysis(
        gpu_baseline_measurements=_measured_baseline(family_id=candidate["workload_family_id"]),
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["claim_allowed"] is False
    assert row["verdict"] == "evidence_missing"
    assert "unknown_candidate_not_claimable" in row["claim_blockers"]


def test_validation_fails_candidate_result_workload_mismatch():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    result = _measured_candidate_result(candidate)
    result["workload_family_id"] = "different_workload"
    validation = opportunity.validate_qe_ic_opportunity_input_artifacts(
        workload_suite=inputs["workload_suite"],
        motif_profile=inputs["motif_profile"],
        target_viability=inputs["target_viability"],
        candidate_plan=inputs["candidate_plan"],
        l1_results=inputs["l1_results"],
        closed_loop_results=inputs["closed_loop_results"],
        gpu_baseline_measurements=_measured_baseline(family_id=candidate["workload_family_id"]),
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    assert validation["status"] == "failed"
    assert any("workload_family_id" in error["field"] for error in validation["errors"])


def test_validation_fails_candidate_result_motif_mismatch():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    result = _measured_candidate_result(candidate)
    result["motif_id"] = "different_motif"
    validation = opportunity.validate_qe_ic_opportunity_input_artifacts(
        workload_suite=inputs["workload_suite"],
        motif_profile=inputs["motif_profile"],
        target_viability=inputs["target_viability"],
        candidate_plan=inputs["candidate_plan"],
        l1_results=inputs["l1_results"],
        closed_loop_results=inputs["closed_loop_results"],
        gpu_baseline_measurements=_measured_baseline(family_id=candidate["workload_family_id"]),
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    assert validation["status"] == "failed"
    assert any("motif_id" in error["field"] for error in validation["errors"])


def test_validation_fails_candidate_result_target_type_mismatch():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    result = _measured_candidate_result(candidate, target_type="fpga_only")
    validation = opportunity.validate_qe_ic_opportunity_input_artifacts(
        workload_suite=inputs["workload_suite"],
        motif_profile=inputs["motif_profile"],
        target_viability=inputs["target_viability"],
        candidate_plan=inputs["candidate_plan"],
        l1_results=inputs["l1_results"],
        closed_loop_results=inputs["closed_loop_results"],
        gpu_baseline_measurements=_measured_baseline(family_id=candidate["workload_family_id"]),
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    assert validation["status"] == "failed"
    assert any("target_type" in error["field"] for error in validation["errors"])


def test_validation_fails_candidate_result_architecture_family_mismatch():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    result = _measured_candidate_result(candidate)
    result["architecture_summary"]["architecture_family"] = "fpga_streaming_pipeline"
    validation = opportunity.validate_qe_ic_opportunity_input_artifacts(
        workload_suite=inputs["workload_suite"],
        motif_profile=inputs["motif_profile"],
        target_viability=inputs["target_viability"],
        candidate_plan=inputs["candidate_plan"],
        l1_results=inputs["l1_results"],
        closed_loop_results=inputs["closed_loop_results"],
        gpu_baseline_measurements=_measured_baseline(family_id=candidate["workload_family_id"]),
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    assert validation["status"] == "failed"
    assert any("architecture_family" in error["field"] for error in validation["errors"])


def test_high_fidelity_estimate_requires_strict_tool_provenance():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    result = _measured_candidate_result(
        candidate,
        tool_provenance={
            "tool": "controlled_trace_replay",
            "version": "test-fixture",
            "run_id": "controlled_trace_run",
        },
    )

    validation = opportunity.validate_qe_ic_candidate_high_fidelity_results(_candidate_results_artifact(result))

    assert validation["status"] == "failed"
    assert any("config_hash" in error["field"] or "output_artifact_hash" in error["field"] for error in validation["errors"])


def test_claim_gate_blocks_high_fidelity_estimate_with_partial_tool_provenance():
    inputs = _input_artifacts()
    candidate = _first_candidate(inputs["candidate_plan"], "gpu_fpga_hybrid")
    baseline = _measured_baseline(family_id=candidate["workload_family_id"])
    result = _measured_candidate_result(
        candidate,
        tool_provenance={
            "tool": "controlled_trace_replay",
            "version": "test-fixture",
            "run_id": "controlled_trace_run",
        },
    )

    report = _run_analysis(
        gpu_baseline_measurements=baseline,
        candidate_high_fidelity_results=_candidate_results_artifact(result),
    )

    row = report["opportunity_records"][0]
    assert row["claim_allowed"] is False
    assert row["verdict"] != "hybrid_opportunity_found"
    assert "high_fidelity_provenance_missing" in row["claim_blockers"]


def test_writer_emits_required_artifacts(tmp_path: Path):
    result = opportunity.write_qe_ic_real_baseline_opportunity_artifacts(tmp_path, CONFIG_PATH)

    assert result["status"] == "passed"
    assert sorted(result["artifacts"]) == sorted(
        [
            "qe_ic_real_baseline_opportunity_report.json",
            "qe_ic_real_baseline_opportunity_validation.json",
            "qe_ic_real_baseline_opportunity_manifest.json",
            "qe_ic_real_baseline_opportunity_readme.md",
        ]
    )
    for artifact in result["artifacts"]:
        assert (tmp_path / artifact).exists()


def test_writer_fail_closed_for_invalid_candidate_evidence(tmp_path: Path):
    config = _load_json(CONFIG_PATH)
    bad_candidate_path = tmp_path / "bad_candidate_results.json"
    bad_candidate_path.write_text(json.dumps({"schema_version": "wrong"}))
    config["input_artifacts"]["candidate_high_fidelity_results"] = str(bad_candidate_path)
    config_path = tmp_path / "bad_config.json"
    config_path.write_text(json.dumps(config))

    result = opportunity.write_qe_ic_real_baseline_opportunity_artifacts(tmp_path, config_path)

    assert result["status"] == "failed"
    assert result["artifacts"] == ["qe_ic_real_baseline_opportunity_validation.json"]
    assert (tmp_path / "qe_ic_real_baseline_opportunity_validation.json").exists()
    assert not (tmp_path / "qe_ic_real_baseline_opportunity_report.json").exists()


def test_writer_fail_closed_for_invalid_config_schema(tmp_path: Path):
    config = _load_json(CONFIG_PATH)
    config["schema_version"] = "wrong"
    config_path = tmp_path / "bad_config.json"
    config_path.write_text(json.dumps(config))

    result = opportunity.write_qe_ic_real_baseline_opportunity_artifacts(tmp_path, config_path)

    assert result["status"] == "failed"
    assert result["artifacts"] == ["qe_ic_real_baseline_opportunity_validation.json"]
    assert not (tmp_path / "qe_ic_real_baseline_opportunity_report.json").exists()


def test_writer_removes_stale_artifacts_on_failure(tmp_path: Path):
    valid = opportunity.write_qe_ic_real_baseline_opportunity_artifacts(tmp_path, CONFIG_PATH)
    assert valid["status"] == "passed"
    config = _load_json(CONFIG_PATH)
    config["input_artifacts"]["candidate_high_fidelity_results"] = str(tmp_path / "missing.json")
    config_path = tmp_path / "bad_config.json"
    config_path.write_text(json.dumps(config))

    failed = opportunity.write_qe_ic_real_baseline_opportunity_artifacts(tmp_path, config_path)

    assert failed["status"] == "failed"
    assert (tmp_path / "qe_ic_real_baseline_opportunity_validation.json").exists()
    assert not (tmp_path / "qe_ic_real_baseline_opportunity_report.json").exists()
    assert not (tmp_path / "qe_ic_real_baseline_opportunity_manifest.json").exists()
    assert not (tmp_path / "qe_ic_real_baseline_opportunity_readme.md").exists()


def test_checked_in_opportunity_artifacts_match_builder_output(tmp_path: Path):
    opportunity.write_qe_ic_real_baseline_opportunity_artifacts(tmp_path, CONFIG_PATH)

    for artifact in [
        "qe_ic_real_baseline_opportunity_report.json",
        "qe_ic_real_baseline_opportunity_validation.json",
        "qe_ic_real_baseline_opportunity_manifest.json",
        "qe_ic_real_baseline_opportunity_readme.md",
    ]:
        assert (CHECKED_IN_RESULTS_DIR / artifact).read_text() == (tmp_path / artifact).read_text()


def test_cli_emits_passed_status(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "--config",
            str(CONFIG_PATH),
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
    assert "speedup_vs_gpu" not in CLI_PATH.read_text()
    assert "claim_allowed" not in CLI_PATH.read_text()


def test_readme_explains_how_to_answer_research_question():
    readme = (CHECKED_IN_RESULTS_DIR / "qe_ic_real_baseline_opportunity_readme.md").read_text().lower()

    for required in [
        "what question this layer answers",
        "true gpu baseline is required",
        "l1 and synthetic replay are insufficient",
        "speedup_vs_gpu",
        "accepted evidence levels",
        "claim gates",
        "evidence_missing",
        "gpu is dominant",
        "fpga/hybrid opportunity is found",
        "replace fixture evidence",
        "no final claim is made unless claim gates pass",
    ]:
        assert required in readme


def test_claim_boundary_blocks_unverified_gpu_fpga_superiority():
    report = _run_analysis()
    combined = json.dumps(report).lower()

    assert "fixture_only_inconclusive" in combined
    assert "does not treat l1 estimates or synthetic labels as measured performance" in combined
    assert "fpga is stronger than gpu" not in combined
    assert "gpu+fpga is stronger than gpu" not in combined
