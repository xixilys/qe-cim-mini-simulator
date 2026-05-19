#!/usr/bin/env python3
"""Acceptance invariants for the DFT/QE full-SCF hardware DSE PRD."""

from __future__ import annotations

import pytest

from dse_v2.codesign.dft_scf_workstreams import (
    STRICT_DFT_QE_WORKLOAD_CLASSES,
    adjudicate_hardware_claim_evidence,
    build_full_scf_hybrid_step5_report,
    build_wave15_trace,
    formal_pareto_candidates,
    validate_artifact_scope_ids,
    validate_step5_full_scf_cost_report,
    validate_strict_dft_qe_bundle,
)
from dse_v2.contracts import ContractValidationError, validate_artifact_write


def _strict_case(workload_class: str) -> dict:
    return {
        "case_id": f"{workload_class}_case",
        "workload_class": workload_class,
        "qe_input": f"&CONTROL calculation='{workload_class}' /",
        "pseudopotentials": ["Si.pz-vbc.UPF"],
        "run_command": ["pw.x", "-in", f"{workload_class}.in"],
        "reference_output_hash": f"sha256:{workload_class}",
        "provenance": {"source": "pytest-fixture", "license": "fixture-only"},
        "parser_version": "qe-parser-v1",
        "tool_version": "qe-7.x-fixture",
        "proof_class": "strict_replay_fixture",
    }


def _strict_bundle() -> dict:
    return {
        "bundle_id": "strict-qe-six-class",
        "campaign_id": "campaign-prd",
        "workload_run_id": "workload-prd",
        "strict": True,
        "workload_classes": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
        "cases": [_strict_case(workload_class) for workload_class in STRICT_DFT_QE_WORKLOAD_CLASSES],
    }


def _base_claim_rows(*extra_rows: dict) -> dict:
    return {
        "evidence_rows": [
            {"evidence_class": "golden_correctness", "status": "passed"},
            {"evidence_class": "hls_csim", "status": "passed"},
            {"evidence_class": "hls_csynth", "status": "passed"},
            *extra_rows,
        ]
    }


def test_strict_bundle_rejects_missing_assets():
    bundle = _strict_bundle()
    del bundle["cases"][0]["pseudopotentials"]

    validation = validate_strict_dft_qe_bundle(bundle)

    assert validation["status"] == "blocked"
    assert validation["admitted"] is False
    assert {"case_id": "scf_ground_state_case", "asset": "pseudopotential", "reason": "required strict DFT/QE bundle asset is absent"} in validation["missing_assets"]


def test_exploratory_candidate_excluded_from_formal_pareto():
    release_candidate = {
        "candidate_id": "release-dma-hbm",
        "candidate_tier": "release",
        "seed_source": "release_seed_manifest",
        "metrics": {"end_to_end_scf_time_s": 8.0},
        "claim_eligibility": {"formal_pareto": True},
    }
    exploratory_candidate = {
        "candidate_id": "explore-unbounded-ai-core",
        "candidate_tier": "exploratory",
        "metrics": {"end_to_end_scf_time_s": 1.0},
        "claim_eligibility": {"formal_pareto": True},
    }

    filtered = formal_pareto_candidates([exploratory_candidate, release_candidate])

    assert [row["candidate_id"] for row in filtered["formal_pareto_candidates"]] == ["release-dma-hbm"]
    assert filtered["excluded_candidates"][0]["candidate_id"] == "explore-unbounded-ai-core"
    assert "exploratory_candidate_excluded_from_formal_pareto" in filtered["excluded_candidates"][0]["reasons"]


def test_unavailable_tool_log_is_blocker_not_pass():
    verdict = adjudicate_hardware_claim_evidence(
        _base_claim_rows({"evidence_class": "vivado_synth", "status": "unavailable"}),
        claim_type="fpga",
    )

    assert verdict["status"] == "blocked"
    assert verdict["claim_eligible"] is False
    assert "tool_unavailable_blocker_not_pass" in verdict["blocker_ids"]


def test_dc_only_rejected_for_fpga_claim():
    verdict = adjudicate_hardware_claim_evidence(
        _base_claim_rows({"evidence_class": "dc_synth_timing_area", "status": "passed"}),
        claim_type="fpga",
    )

    assert verdict["status"] == "blocked"
    assert "dc_only_rejected_for_fpga_claim" in verdict["blocker_ids"]
    assert "missing_fpga_branch_evidence" in verdict["blocker_ids"]


def test_vivado_only_rejected_for_asic_claim():
    verdict = adjudicate_hardware_claim_evidence(
        _base_claim_rows({"evidence_class": "vivado_implementation", "status": "passed"}),
        claim_type="asic",
    )

    assert verdict["status"] == "blocked"
    assert "vivado_only_rejected_for_asic_claim" in verdict["blocker_ids"]
    assert "missing_asic_branch_evidence" in verdict["blocker_ids"]


def test_step5_reports_host_transfer_sync_costs():
    report = build_full_scf_hybrid_step5_report(
        candidate_id="release-dma-hbm",
        campaign_id="campaign-prd",
        workload_run_id="workload-prd",
        trial_id="trial-prd",
        kernel_speedup=10.0,
        baseline_scf_time_s=100.0,
        accelerated_scf_time_s=50.0,
        host_bound_compute_cost_s=20.0,
        transfer_cost_s=5.0,
        synchronization_cost_s=2.0,
        queueing_cost_s=1.5,
        layout_cost_s=1.0,
        cpu_bound_costs_s={
            "io": 3.0,
            "scf_control": 4.0,
            "convergence": 6.0,
            "diagonalization": 7.0,
            "mixing": 0.5,
        },
        kernel_evidence_levels={"fft": "vivado_blocked"},
        candidate_claim_eligible=False,
    )
    validation = validate_step5_full_scf_cost_report(report)

    assert validation["passed"] is True
    assert report["speedups"]["kernel_speedup"] == 10.0
    assert report["speedups"]["end_to_end_scf_evaluated_speedup"] == 2.0
    assert report["cost_breakdown"]["host_bound_compute_cost_s"] == 20.0
    assert report["cost_breakdown"]["transfer_cost_s"] == 5.0
    assert report["cost_breakdown"]["synchronization_queueing_layout_cost_s"] == 4.5
    assert report["cost_breakdown"]["scf_control_cost_s"] == 4.0
    assert report["cost_breakdown"]["diagonalization_cost_s"] == 7.0
    assert report["cost_breakdown"]["mixing_cost_s"] == 0.5


def test_artifact_ids_propagate_campaign_workload_trial_scope():
    step1_ref = {
        "artifact_id": "artifact-workload",
        "campaign_id": "campaign-prd",
        "workload_run_id": "workload-prd",
    }
    step2_ref_missing_trial = {
        "artifact_id": "artifact-candidate",
        "campaign_id": "campaign-prd",
        "workload_run_id": "workload-prd",
    }
    step5_ref = {
        "artifact_id": "artifact-report",
        "campaign_id": "campaign-prd",
        "workload_run_id": "workload-prd",
        "trial_id": "trial-prd",
    }

    assert validate_artifact_scope_ids(step1_ref, producer_stage="step1")["passed"] is True
    assert validate_artifact_scope_ids(step2_ref_missing_trial, producer_stage="step2")["passed"] is False
    assert validate_artifact_scope_ids(step2_ref_missing_trial, producer_stage="step2")["missing_ids"] == ["trial_id"]
    assert validate_artifact_scope_ids(step5_ref, producer_stage="step5")["passed"] is True


def test_step_artifact_ownership_rejects_cross_writes():
    validate_artifact_write("step3", "simulation_result.json")
    validate_artifact_write("step5", "final_report.json")

    with pytest.raises(ContractValidationError, match="step3 cannot write claim_validation.json"):
        validate_artifact_write("step3", "claim_validation.json")
    with pytest.raises(ContractValidationError, match="step4 cannot write final_report.json"):
        validate_artifact_write("step4", "final_report.json")


def test_wave15_trace_reaches_step5_without_completion_claim():
    candidate = {
        "candidate_id": "release-dma-hbm",
        "candidate_tier": "release",
        "seed_source": "release_seed_manifest",
        "trial_id": "trial-prd",
        "metrics": {
            "kernel_speedup": 3.0,
            "baseline_scf_time_s": 30.0,
            "accelerated_scf_time_s": 20.0,
        },
        "costs": {
            "host_bound_compute_cost_s": 10.0,
            "transfer_cost_s": 2.0,
            "synchronization_cost_s": 1.0,
            "queueing_cost_s": 1.0,
            "layout_cost_s": 1.0,
        },
        "cpu_bound_costs_s": {
            "io": 1.0,
            "scf_control": 2.0,
            "convergence": 3.0,
            "diagonalization": 4.0,
            "mixing": 1.0,
        },
    }
    trace = build_wave15_trace(
        strict_bundle=_strict_bundle(),
        release_candidate=candidate,
        tool_evidence=_base_claim_rows({"evidence_class": "vivado_synth", "status": "unavailable"}),
        claim_type="fpga",
    )

    assert trace["status"] == "progress_only"
    assert trace["progress_only"] is True
    assert trace["completion_claim"] is False
    assert trace["mvp_claim"] is False
    assert [row["step"] for row in trace["artifact_chain"]] == ["step1", "step2", "step3", "step4", "step5"]
    assert trace["artifact_chain"][2]["status"] == "blocked"
    assert trace["artifact_chain"][4]["status"] == "passed"
    assert trace["step5_report"]["candidate_claim_eligibility"]["trusted_full_scf_hybrid_claim"] is False

