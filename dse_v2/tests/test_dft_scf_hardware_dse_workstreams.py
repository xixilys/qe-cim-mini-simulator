#!/usr/bin/env python3
"""Acceptance invariants for the DFT/QE full-SCF hardware DSE PRD."""

from __future__ import annotations

import json

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
from dse_v2.codesign.dft_hardware_evidence import (
    MAJOR_SCF_KERNEL_IDS,
    build_ic_eda_tool_availability_report,
    build_major_kernel_evidence_matrix,
    run_tool_probe_commands,
)
from dse_v2.contracts import ContractValidationError, validate_artifact_write
from dse_v2.reference_workloads.dft_kinetic_add_rtl_flow import (
    build_kinetic_add_evidence_rows,
    initialize_kinetic_add_rtl_flow,
    write_kinetic_add_major_kernel_matrix,
)
from dse_v2.scripts.dse import probe_dft_ic_eda_tools as ic_eda_probe_cli
from dse_v2.scripts.dse.build_dft_wave15_trace import build_wave15_trace_artifacts


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
    assert {
        "case_id": "small_multi_k_scf_case",
        "asset": "pseudopotential",
        "reason": "required strict DFT/QE bundle asset is absent",
    } in validation["missing_assets"]


def test_strict_scf_bundle_requires_six_representative_research_classes():
    assert set(STRICT_DFT_QE_WORKLOAD_CLASSES) == {
        "small_multi_k_scf",
        "metal_smearing_scf",
        "insulator_scf",
        "slab_vacuum_large_fft_scf",
        "gamma_only_supercell_scf",
        "projector_orthogonalization_heavy_scf",
    }
    bundle = _strict_bundle()
    bundle["workload_classes"].remove("slab_vacuum_large_fft_scf")
    bundle["cases"] = [
        case
        for case in bundle["cases"]
        if case["workload_class"] != "slab_vacuum_large_fft_scf"
    ]

    validation = validate_strict_dft_qe_bundle(bundle)

    assert validation["admitted"] is False
    assert validation["missing_workload_classes"] == ["slab_vacuum_large_fft_scf"]


def test_exploratory_candidate_excluded_from_formal_pareto():
    release_candidate = {
        "candidate_id": "release-dma-hbm",
        "release_policy": {"lane": "release", "formal_pareto_allowed": True},
        "seed_source": "release_seed_manifest",
        "metrics": {"end_to_end_scf_time_s": 8.0},
        "claim_eligibility": {"formal_pareto": True},
    }
    exploratory_candidate = {
        "candidate_id": "explore-unbounded-ai-core",
        "release_policy": {"lane": "exploratory", "formal_pareto_allowed": False},
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
        "release_policy": {"lane": "release", "formal_pareto_allowed": True},
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

    assert trace["status"] == "blocked_progress_only"
    assert trace["progress_only"] is True
    assert trace["completion_claim"] is False
    assert trace["mvp_claim"] is False
    assert [row["step"] for row in trace["artifact_chain"]] == ["step1", "step2", "step3", "step4", "step5"]
    assert trace["artifact_chain"][2]["status"] == "blocked"
    assert trace["artifact_chain"][4]["status"] == "passed"
    assert trace["step5_report"]["candidate_claim_eligibility"]["trusted_full_scf_hybrid_claim"] is False


def test_wave15_trace_cli_artifacts_are_blocked_progress_only_until_evidence_closes(tmp_path):
    outputs = build_wave15_trace_artifacts(tmp_path / "wave15")

    out_dir = tmp_path / "wave15"
    assert set(outputs) == {
        "strict_workload_bundle",
        "release_candidate",
        "tool_evidence",
        "wave15_trace",
        "wave15_summary",
        "wave15_runbook",
    }
    trace = json.loads((out_dir / outputs["wave15_trace"]).read_text(encoding="utf-8"))
    summary = json.loads((out_dir / outputs["wave15_summary"]).read_text(encoding="utf-8"))
    runbook = (out_dir / outputs["wave15_runbook"]).read_text(encoding="utf-8")
    assert trace["schema_version"] == "dse.dft_scf.wave15_trace.v1"
    assert trace["status"] == "blocked_progress_only"
    assert trace["progress_only"] is True
    assert trace["completion_claim"] is False
    assert trace["mvp_claim"] is False
    assert summary["progress_only"] is True
    assert summary["status"] == "blocked_progress_only"
    assert summary["completion_claim"] is False
    assert [row["step"] for row in summary["step_chain_status"]] == ["step1", "step2", "step3", "step4", "step5"]
    assert "not final DFT/QE full-SCF hardware DSE closure" in runbook


def _fpga_pass_rows(kernel_id: str) -> list[dict]:
    return [
        {"kernel_id": kernel_id, "evidence_type": "golden_correctness", "status": "passed"},
        {"kernel_id": kernel_id, "evidence_type": "hls_csim", "status": "passed"},
        {"kernel_id": kernel_id, "evidence_type": "hls_csynth", "status": "passed"},
        {"kernel_id": kernel_id, "evidence_type": "vivado_synth", "status": "passed"},
    ]


def test_claim_gate_requires_complete_ladder_for_each_claimed_kernel():
    dispositions = [
        {
            "kernel_id": kernel_id,
            "disposition": "host_bound",
            "host_cost_accounted": True,
        }
        for kernel_id in MAJOR_SCF_KERNEL_IDS
    ]
    dispositions[0] = {
        "kernel_id": "fft_ifft_ffft",
        "disposition": "accelerated_claim",
        "claim_type": "fpga",
    }

    passed = build_major_kernel_evidence_matrix(
        dispositions,
        evidence_rows=_fpga_pass_rows("fft_ifft_ffft"),
        candidate_id="cand-wave2",
    )

    assert passed["status"] == "passed"
    assert passed["trusted"] is True
    assert len(passed["kernel_rows"]) == 8

    blocked = build_major_kernel_evidence_matrix(
        dispositions,
        evidence_rows=_fpga_pass_rows("transpose_layout_conversion"),
        candidate_id="cand-wave2",
    )

    assert blocked["status"] == "blocked"
    assert "hardware_claim_gate_blocked" in blocked["blocker_ids"]
    fft_row = next(row for row in blocked["kernel_rows"] if row["kernel_id"] == "fft_ifft_ffft")
    assert fft_row["hardware_claim_gate"]["missing_or_blocked_stages"] == [
        "golden_correctness",
        "hls_or_rtl_sim",
        "hls_or_rtl_synth",
        "vivado_fpga_synth_or_impl",
    ]


def test_major_kernel_matrix_rejects_missing_disposition_and_uncosted_host_bound():
    matrix = build_major_kernel_evidence_matrix(
        [
            {
                "kernel_id": "fft_ifft_ffft",
                "disposition": "host_bound",
                "host_cost_accounted": False,
            }
        ],
        candidate_id="cand-incomplete",
    )

    assert matrix["status"] == "blocked"
    assert "host_bound_kernel_cost_not_accounted" in matrix["blocker_ids"]
    assert "missing_major_kernel_disposition" in matrix["blocker_ids"]


def test_ic_eda_tool_availability_report_records_real_tool_probe_boundary():
    report = build_ic_eda_tool_availability_report(
        [
            {"tool": "dc_shell", "returncode": 1, "stdout": "dc_shell version - O-2018.06-SP1"},
            {"tool": "vcs", "returncode": 0, "stdout": "vcs script version : O-2018.09"},
            {"tool": "vivado", "returncode": 0, "stdout": "Vivado v2019.1 (64-bit)"},
        ],
        environment="ssh ic-eda",
    )

    assert report["status"] == "passed"
    assert report["all_required_tools_available"] is True
    assert report["required_tools"] == ["dc_shell", "vcs", "vivado"]
    assert report["completion_claim"] == "availability_only_not_kernel_ppa"
    assert report["kernel_ppa_evidence"] is False
    assert report["hardware_completion_eligible"] is False
    assert report["deliverable_complete"] is False
    assert report["tool_rows"][0]["availability_evidence_kind"] == "version_like_output_nonzero_returncode"
    assert report["tool_rows"][0]["hardware_completion_eligible"] is False
    assert report["tool_rows"][0]["completion_eligible"] is False
    assert "not kernel synthesis" in report["claim_boundary"]


def test_ic_eda_tool_availability_rejects_command_not_found_even_with_zero_returncode():
    report = build_ic_eda_tool_availability_report(
        [
            {"tool": "dc_shell", "returncode": 0, "stdout": "dc_shell: command not found"},
            {"tool": "vcs", "returncode": 0, "stdout": "VCS version O-2018.09"},
            {"tool": "vivado", "returncode": 0, "stdout": "Vivado v2019.1"},
        ],
        environment="unit-test",
    )

    assert report["status"] == "blocked"
    dc_row = next(row for row in report["tool_rows"] if row["tool"] == "dc_shell")
    assert dc_row["available"] is False
    assert dc_row["availability_evidence_kind"] == "not_found_error"
    assert "dc_shell" in report["blockers"][0]["tools"]


def test_ic_eda_tool_availability_blocks_missing_required_tools():
    report = build_ic_eda_tool_availability_report(
        [{"tool": "dc_shell", "returncode": 0, "stdout": "dc_shell version"}],
        environment="ssh ic-eda",
    )

    assert report["status"] == "blocked"
    assert report["all_required_tools_available"] is False
    assert report["blockers"][0]["tools"] == ["vcs", "vivado"]


def test_tool_probe_runner_normalizes_command_results():
    def fake_runner(command):
        return {"returncode": 0, "stdout": " ".join(command)}

    report = run_tool_probe_commands(
        {
            "dc_shell": ["dc_shell", "-version"],
            "vcs": ["vcs", "-ID"],
            "vivado": ["vivado", "-version"],
        },
        runner=fake_runner,
        environment="unit-test",
    )

    assert report["status"] == "passed"
    assert [row["tool"] for row in report["tool_rows"]] == ["dc_shell", "vcs", "vivado"]


def test_ic_eda_probe_cli_falls_back_from_missing_ic_to_ssh_availability_only(
    tmp_path,
    monkeypatch,
):
    calls = []

    def fake_run(command, *, timeout_s):
        calls.append(list(command))
        joined = " ".join(command)
        if command == ["bash", "-lc", "command -v ic"]:
            return {"returncode": 1, "stdout": "", "stderr": "ic missing"}
        if command[0] == "ssh" and "dc_shell" in joined:
            return {"returncode": 1, "stdout": "/eda/bin/dc_shell\ndc_shell version O-2018.06-SP1\n", "stderr": ""}
        if command[0] == "ssh" and "vcs" in joined:
            return {"returncode": 0, "stdout": "/eda/bin/vcs\nvcs script version O-2018.09\n", "stderr": ""}
        if command[0] == "ssh" and "vivado" in joined:
            return {"returncode": 0, "stdout": "/eda/bin/vivado\nVivado v2019.1 (64-bit)\n", "stderr": ""}
        raise AssertionError(f"unexpected command: {command}")

    out_dir = tmp_path / "probe"
    monkeypatch.setattr(ic_eda_probe_cli, "_run", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["probe_dft_ic_eda_tools.py", "--out", str(out_dir), "--timeout-s", "5"],
    )

    assert ic_eda_probe_cli.main() == 0

    report = json.loads((out_dir / "ic_eda_tool_availability.json").read_text(encoding="utf-8"))
    attempts = json.loads((out_dir / "ic_eda_tool_attempts.json").read_text(encoding="utf-8"))
    assert calls[0] == ["bash", "-lc", "command -v ic"]
    assert report["status"] == "passed"
    assert report["selected_probe_transport"] == "ssh"
    assert report["probe_order"] == ["local_ic", "ssh"]
    assert report["completion_claim"] == "availability_only_not_kernel_ppa"
    assert report["availability_only_not_kernel_ppa"] is True
    assert report["kernel_ppa_evidence"] is False
    assert report["timing_area_evidence"] is False
    assert report["implementation_evidence"] is False
    assert report["hardware_completion_eligible"] is False
    assert report["deliverable_complete"] is False
    assert {attempt["transport"] for attempt in attempts} == {"local_ic", "ssh"}
    assert all(attempt["availability_only_not_kernel_ppa"] is True for attempt in attempts)
    assert any(
        "source ~/.bashrc; which dc_shell || true; dc_shell -version" in attempt["command"]
        for attempt in attempts
    )
    assert any(
        "source ~/.bashrc; which vivado || true; LC_ALL=C LANG=C vivado -version" in attempt["command"]
        for attempt in attempts
    )


def test_ic_eda_probe_cli_exposes_ssh_tool_blockers_without_completion_claim(
    tmp_path,
    monkeypatch,
):
    def fake_run(command, *, timeout_s):
        joined = " ".join(command)
        if command == ["bash", "-lc", "command -v ic"]:
            return {"returncode": 1, "stdout": "", "stderr": "ic missing"}
        if command[0] == "ssh" and "vivado" in joined:
            return {"returncode": 127, "stdout": "", "stderr": "vivado: command not found"}
        if command[0] == "ssh" and "dc_shell" in joined:
            return {"returncode": 0, "stdout": "dc_shell version O-2018.06-SP1\n", "stderr": ""}
        if command[0] == "ssh" and "vcs" in joined:
            return {"returncode": 0, "stdout": "vcs script version O-2018.09\n", "stderr": ""}
        raise AssertionError(f"unexpected command: {command}")

    out_dir = tmp_path / "probe_blocked"
    monkeypatch.setattr(ic_eda_probe_cli, "_run", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["probe_dft_ic_eda_tools.py", "--out", str(out_dir), "--timeout-s", "5"],
    )

    assert ic_eda_probe_cli.main() == 2

    report = json.loads((out_dir / "ic_eda_tool_availability.json").read_text(encoding="utf-8"))
    assert report["status"] == "blocked"
    assert report["completion_claim"] == "availability_only_not_kernel_ppa"
    assert report["kernel_ppa_evidence"] is False
    assert report["hardware_completion_eligible"] is False
    assert report["deliverable_complete"] is False
    assert report["blockers"][0]["id"] == "required_ic_eda_tool_blocked"
    assert report["blockers"][0]["tools"] == ["vivado"]


def test_kinetic_add_rtl_flow_is_fail_closed_before_remote_tool_outputs(tmp_path):
    initialize_kinetic_add_rtl_flow(tmp_path)

    evidence = build_kinetic_add_evidence_rows(tmp_path)
    matrix = write_kinetic_add_major_kernel_matrix(
        tmp_path,
        candidate_id="unit-kinetic-add-before-tools",
        evidence_rows=evidence["evidence_rows"],
    )

    assert (tmp_path / "kinetic_add.v").exists()
    assert (tmp_path / "tb_kinetic_add.v").exists()
    assert evidence["fpga_gate_candidate"] is False
    assert evidence["asic_gate_candidate"] is False
    assert evidence["asic_attempt_evidence_rows"][0]["status"] == "blocked"
    assert matrix["status"] == "blocked"
    kinetic_row = next(row for row in matrix["kernel_rows"] if row["kernel_id"] == "kinetic_add")
    assert kinetic_row["hardware_claim_gate"]["missing_or_blocked_stages"] == [
        "hls_or_rtl_sim",
        "hls_or_rtl_synth",
        "vivado_fpga_synth_or_impl",
    ]


def test_kinetic_add_rtl_flow_builds_fpga_matrix_and_keeps_dc_attempt_separate(tmp_path):
    initialize_kinetic_add_rtl_flow(tmp_path)
    (tmp_path / "vcs_run.log").write_text("KINETIC_ADD_RTL_PASS re=39 im=-7\n", encoding="utf-8")
    (tmp_path / "vivado_stdout.log").write_text("synth_design completed successfully\n", encoding="utf-8")
    (tmp_path / "vivado_utilization.rpt").write_text("DSPs | 2\n", encoding="utf-8")
    (tmp_path / "dc_stdout.log").write_text(
        "Error: Could not read the following target libraries: your_library.db\n",
        encoding="utf-8",
    )
    (tmp_path / "dc_area.rpt").write_text("Library(s) Used:\n    gtech\nunmapped logic\n", encoding="utf-8")

    evidence = build_kinetic_add_evidence_rows(tmp_path)
    matrix = write_kinetic_add_major_kernel_matrix(
        tmp_path,
        candidate_id="unit-kinetic-add-fpga-smoke",
        evidence_rows=evidence["evidence_rows"],
    )

    assert evidence["fpga_gate_candidate"] is True
    assert evidence["asic_gate_candidate"] is False
    assert evidence["asic_attempt_evidence_rows"][0]["status"] == "blocked"
    assert matrix["status"] == "passed"
    kinetic_row = next(row for row in matrix["kernel_rows"] if row["kernel_id"] == "kinetic_add")
    assert kinetic_row["claim_allowed"] is True
    assert kinetic_row["hardware_claim_gate"]["missing_or_blocked_stages"] == []
