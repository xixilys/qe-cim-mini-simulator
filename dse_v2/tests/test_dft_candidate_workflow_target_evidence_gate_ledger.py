#!/usr/bin/env python3
"""DFT candidate/workflow/target evidence-gate ledger tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_candidate_workflow_target_evidence_gate_ledger import (
    DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_SCHEMA,
    LEDGER_ARTIFACT_NAME,
    LEDGER_STATUS_ARTIFACT_NAME,
    LEDGER_VALIDATION_ARTIFACT_NAME,
    build_dft_candidate_workflow_target_evidence_gate_ledger,
    validate_dft_candidate_workflow_target_evidence_gate_ledger,
    write_dft_candidate_workflow_target_evidence_gate_ledger,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_BUILDER = (
    REPO_ROOT
    / "dse_v2"
    / "scripts"
    / "dse"
    / "build_dft_candidate_workflow_target_evidence_gate_ledger.py"
)
FPGA_STAGES = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
)
ASIC_STAGES = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "dc_asic_synth_timing_area",
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _matrix_row(
    *,
    candidate_id: str,
    target: str,
    status: str = "blocked_missing_input",
    status_reason: str = "",
) -> dict[str, object]:
    target_platform_id = {
        "fpga": "fpga_vivado_release_v1",
        "asic": "asic_synopsys_dc_release_v1",
    }.get(target, f"{target}_target_release_v1")
    return {
        "row_id": f"matrix::{candidate_id}::{target}",
        "candidate_id": candidate_id,
        "workflow_case_id": "qe_full_scf_small",
        "deployment_boundary_id": "full_scf_evaluated_hybrid",
        "target_platform_id": target_platform_id,
        "target_platform_kind": target,
        "status": status,
        "status_reason": status_reason,
        "workflow_case": {"workflow_case_id": "qe_full_scf_small"},
        "deployment_boundary": {
            "deployment_boundary_id": "full_scf_evaluated_hybrid",
            "descriptor_granularity": "graph_node_command",
        },
        "target_platform": {
            "target_platform_id": target_platform_id,
            "platform_kind": target,
        },
    }


def _write_matrix(path: Path, rows: list[dict[str, object]]) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "unit-test.release_matrix.v1",
            "release_id": "release-ledger-test",
            "row_count": len(rows),
            "expected_row_count": len(rows),
            "rows": rows,
            "deliverable_complete": False,
        },
    )


def _stage_row(candidate_id: str, stage_id: str, *, verdict: str = "passed") -> dict[str, object]:
    passed = verdict == "passed"
    return {
        "candidate_id": candidate_id,
        "kernel_id": "fft_ifft_ffft",
        "stage_id": stage_id,
        "parsed_result_present": True,
        "parsed_result_schema_valid": verdict != "invalid",
        "parsed_verdict": verdict,
        "stage_gate_passed": passed,
        "status": "stage_gate_passed_pending_unit_closure"
        if passed
        else "failed_parsed_result"
        if verdict == "failed"
        else "blocked_invalid_parsed_result",
        "adjudication_result": "passed_stage_gate"
        if passed
        else "failed_stage_gate"
        if verdict == "failed"
        else "blocked_stage_gate",
        "parsed_result": {
            "path": f"parsed_hard_gate_results/{candidate_id}/fft_ifft_ffft/{stage_id}_parsed_result.json",
            "exists": True,
            "sha256": f"sha256-{candidate_id}-{stage_id}",
            "hash_algorithm": "sha256",
        },
        "raw_evidence_ref_count": 1,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
    }


def _write_gate_adjudication(path: Path, stage_rows_by_candidate: dict[str, list[str]]) -> Path:
    units = []
    for candidate_id, stage_ids in stage_rows_by_candidate.items():
        stage_rows = [_stage_row(candidate_id, stage_id) for stage_id in stage_ids]
        units.append(
            {
                "unit_id": f"{candidate_id}:fft_ifft_ffft",
                "candidate_id": candidate_id,
                "kernel_id": "fft_ifft_ffft",
                "stage_rows": stage_rows,
                "unit_gate_passed": set(stage_ids) in (set(FPGA_STAGES), set(ASIC_STAGES)),
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
            }
        )
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication.v1",
            "release_id": "release-ledger-test",
            "status": "all_unit_stage_gates_passed_pending_release_claim",
            "unit_rows": units,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )


def test_ledger_enumerates_target_specific_gate_rows_and_maps_adjudication(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [
            _matrix_row(candidate_id="cand-fpga", target="fpga"),
            _matrix_row(candidate_id="cand-asic", target="asic"),
        ],
    )
    gate_path = _write_gate_adjudication(
        run_dir / "dft_hardware_closure_gate_adjudication.json",
        {
            "cand-fpga": list(FPGA_STAGES),
            "cand-asic": list(ASIC_STAGES),
        },
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        gate_adjudication_path=gate_path,
    )
    validation = validate_dft_candidate_workflow_target_evidence_gate_ledger(ledger)

    assert ledger["schema_version"] == DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_SCHEMA
    assert validation["valid"] is True
    assert ledger["row_count"] == 8
    assert ledger["expected_row_count"] == 8
    assert ledger["deliverable_complete"] is False
    assert {row["status"] for row in ledger["rows"]} == {"trusted_pass"}
    fpga_gates = {
        row["evidence_gate_id"]
        for row in ledger["rows"]
        if row["target_platform_kind"] == "fpga"
    }
    asic_gates = {
        row["evidence_gate_id"]
        for row in ledger["rows"]
        if row["target_platform_kind"] == "asic"
    }
    assert fpga_gates == set(FPGA_STAGES)
    assert asic_gates == set(ASIC_STAGES)
    assert "dc_asic_synth_timing_area" not in fpga_gates
    assert "vivado_fpga_synth_or_impl" not in asic_gates
    assert all(row["claim_boundary"] for row in ledger["rows"])
    assert all(row["deliverable_complete"] is False for row in ledger["rows"])


def test_ledger_consumes_complete_dse_matrix_gate_rows_without_reexpanding(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    complete_dse_gate_aliases = {
        "golden_correctness": "golden_correctness",
        "hls_or_rtl_simulation": "hls_or_rtl_sim",
        "hls_or_rtl_synthesis": "hls_or_rtl_synth",
        "vivado_synthesis_or_implementation": "vivado_fpga_synth_or_impl",
    }
    rows = []
    for source_gate_id in complete_dse_gate_aliases:
        row = _matrix_row(candidate_id="cand-fpga", target="fpga")
        row["row_id"] = f"matrix::cand-fpga::fpga::{source_gate_id}"
        row["evidence_gate_id"] = source_gate_id
        row["evidence_gate"] = {
            "evidence_gate_id": source_gate_id,
            "applies_to_target_platform_kinds": ["fpga"],
        }
        rows.append(row)
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        rows,
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
    )
    validation = validate_dft_candidate_workflow_target_evidence_gate_ledger(
        ledger
    )

    assert validation["valid"] is True
    assert ledger["row_count"] == len(complete_dse_gate_aliases)
    assert ledger["expected_row_count"] == len(complete_dse_gate_aliases)
    assert {
        row["source_matrix_evidence_gate_id"]: row["evidence_gate_id"]
        for row in ledger["rows"]
    } == complete_dse_gate_aliases
    assert ledger["row_counts_by_candidate_kernel_target_axis"] == {
        "cand-fpga::__unbound__::fpga": len(complete_dse_gate_aliases),
    }


def test_ledger_emits_explicit_fail_closed_unknown_target_axis_row(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [_matrix_row(candidate_id="cand-unknown", target="gpu")],
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
    )
    validation = validate_dft_candidate_workflow_target_evidence_gate_ledger(ledger)

    assert validation["valid"] is True
    assert ledger["row_count"] == 1
    assert ledger["expected_row_count"] == 1
    assert ledger["candidate_kernel_target_axis_count"] == 1
    assert ledger["candidate_kernel_target_axis_counts_by_target"] == {"gpu": 1}
    assert ledger["row_counts_by_candidate_kernel_target_axis"] == {
        "cand-unknown::__unbound__::gpu": 1,
    }
    assert ledger["row_counts_by_target_platform_kind"] == {"gpu": 1}
    assert ledger["unknown_target_platform_kind_row_count"] == 1
    row = ledger["rows"][0]
    assert row["target_platform_kind"] == "gpu"
    assert row["evidence_gate_id"] == "__unknown_target__"
    assert row["status"] == "blocked_invalid_evidence"
    assert "unknown_target_platform_kind:gpu" in row["blocker_ids"]
    assert row["row_classification"]["candidate_kernel_axis_bound"] is False
    assert row["row_classification"]["unknown_target_platform_kind"] is True
    assert validation["unknown_target_platform_kind_row_count"] == 1
    assert validation["blockers"] == []
    assert ledger["hardware_completion_eligible"] is False
    assert ledger["deliverable_complete"] is False


def test_ledger_expands_concrete_gate_rows_by_kernel_without_mixing_refs(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [_matrix_row(candidate_id="cand-multi-kernel", target="fpga")],
    )
    units = []
    for kernel_id in ("fft_ifft_ffft", "reduction_tree"):
        stage_rows = []
        for stage_id in FPGA_STAGES:
            row = _stage_row("cand-multi-kernel", stage_id)
            row["kernel_id"] = kernel_id
            row["parsed_result"]["path"] = (
                f"parsed_hard_gate_results/cand-multi-kernel/"
                f"{kernel_id}/{stage_id}_parsed_result.json"
            )
            stage_rows.append(row)
        units.append(
            {
                "unit_id": f"cand-multi-kernel:{kernel_id}",
                "candidate_id": "cand-multi-kernel",
                "kernel_id": kernel_id,
                "stage_rows": stage_rows,
                "unit_gate_passed": True,
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
            }
        )
    gate_path = _write_json(
        run_dir / "dft_hardware_closure_gate_adjudication.json",
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication.v1",
            "release_id": "release-ledger-test",
            "status": "all_unit_stage_gates_passed_pending_release_claim",
            "unit_rows": units,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        gate_adjudication_path=gate_path,
    )
    validation = validate_dft_candidate_workflow_target_evidence_gate_ledger(ledger)

    assert validation["valid"] is True
    assert ledger["row_count"] == len(FPGA_STAGES) * 2
    assert ledger["expected_row_count"] == len(FPGA_STAGES) * 2
    assert ledger["trusted_pass_count"] == len(FPGA_STAGES) * 2
    assert {row["kernel_id"] for row in ledger["rows"]} == {
        "fft_ifft_ffft",
        "reduction_tree",
    }
    fft_vivado = next(
        row
        for row in ledger["rows"]
        if row["kernel_id"] == "fft_ifft_ffft"
        and row["evidence_gate_id"] == "vivado_fpga_synth_or_impl"
    )
    reduction_vivado = next(
        row
        for row in ledger["rows"]
        if row["kernel_id"] == "reduction_tree"
        and row["evidence_gate_id"] == "vivado_fpga_synth_or_impl"
    )
    assert fft_vivado["row_classification"]["candidate_kernel_axis_bound"] is True
    assert reduction_vivado["row_classification"]["candidate_kernel_axis_bound"] is True
    assert {
        ref["path"]
        for ref in fft_vivado["evidence_refs"]
        if ref.get("evidence_role") == "parsed_stage_result"
    } == {
        "parsed_hard_gate_results/cand-multi-kernel/fft_ifft_ffft/"
        "vivado_fpga_synth_or_impl_parsed_result.json"
    }
    assert {
        ref["path"]
        for ref in reduction_vivado["evidence_refs"]
        if ref.get("evidence_role") == "parsed_stage_result"
    } == {
        "parsed_hard_gate_results/cand-multi-kernel/reduction_tree/"
        "vivado_fpga_synth_or_impl_parsed_result.json"
    }
    assert fft_vivado["hardware_completion_eligible"] is False
    assert fft_vivado["deliverable_complete"] is False


def test_ledger_rejects_dc_only_fpga_and_vivado_only_asic_shortcuts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [
            _matrix_row(candidate_id="cand-fpga", target="fpga"),
            _matrix_row(candidate_id="cand-asic", target="asic"),
        ],
    )
    gate_path = _write_gate_adjudication(
        run_dir / "dft_hardware_closure_gate_adjudication.json",
        {
            "cand-fpga": ["dc_asic_synth_timing_area"],
            "cand-asic": ["vivado_fpga_synth_or_impl"],
        },
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        gate_adjudication_path=gate_path,
    )

    fpga_vivado = next(
        row for row in ledger["rows"] if row["candidate_id"] == "cand-fpga" and row["evidence_gate_id"] == "vivado_fpga_synth_or_impl"
    )
    asic_dc = next(
        row for row in ledger["rows"] if row["candidate_id"] == "cand-asic" and row["evidence_gate_id"] == "dc_asic_synth_timing_area"
    )
    assert fpga_vivado["status"] == "blocked_invalid_evidence"
    assert fpga_vivado["wrong_target_evidence_rejected"] is True
    assert "dc_only_fpga_evidence_shortcut_rejected" in fpga_vivado["blocker_ids"]
    assert asic_dc["status"] == "blocked_invalid_evidence"
    assert asic_dc["wrong_target_evidence_rejected"] is True
    assert "vivado_only_asic_evidence_shortcut_rejected" in asic_dc["blocker_ids"]
    assert "trusted_pass" not in {row["status"] for row in ledger["rows"]}


def test_ledger_rejects_smoke_only_passed_gate_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [_matrix_row(candidate_id="cand-smoke", target="fpga")],
    )
    gate_path = _write_json(
        run_dir / "dft_hardware_closure_gate_adjudication.json",
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication.v1",
            "release_id": "release-ledger-test",
            "status": "blocked_incomplete_hard_gate_evidence",
            "unit_rows": [
                {
                    "unit_id": "cand-smoke:fft_ifft_ffft",
                    "candidate_id": "cand-smoke",
                    "kernel_id": "fft_ifft_ffft",
                    "stage_rows": [
                        {
                            "candidate_id": "cand-smoke",
                            "kernel_id": "fft_ifft_ffft",
                            "stage_id": "vivado_fpga_synth_or_impl",
                            "parsed_result_present": True,
                            "parsed_result_schema_valid": True,
                            "parsed_verdict": "passed",
                            "stage_gate_passed": False,
                            "status": "blocked_invalid_parsed_result",
                            "blocker_id": "parsed_result_not_kernel_ppa_evidence",
                            "parsed_blocker_ids": [
                                "parsed_result_not_kernel_ppa_evidence"
                            ],
                            "adjudication_result": "blocked_stage_gate",
                            "parsed_result": {
                                "path": "parsed_hard_gate_results/cand-smoke/fft_ifft_ffft/vivado_fpga_synth_or_impl_parsed_result.json",
                                "exists": True,
                                "sha256": "sha256-smoke-vivado",
                                "hash_algorithm": "sha256",
                            },
                            "raw_evidence_refs": [
                                {
                                    "path": "commands/smoke_vivado_probe.txt",
                                    "sha256": "sha256-smoke-transcript",
                                    "hash_algorithm": "sha256",
                                    "artifact_role": "raw_command_transcript_only_not_kernel_ppa",
                                    "availability_only_not_kernel_ppa": True,
                                    "kernel_ppa_evidence": False,
                                    "evidence_role": "raw_stage_evidence",
                                }
                            ],
                            "raw_evidence_ref_count": 1,
                            "hardware_completion_eligible": False,
                            "deliverable_complete": False,
                        }
                    ],
                    "unit_gate_passed": False,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                }
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        gate_adjudication_path=gate_path,
    )
    validation = validate_dft_candidate_workflow_target_evidence_gate_ledger(ledger)

    vivado_row = next(
        row
        for row in ledger["rows"]
        if row["candidate_id"] == "cand-smoke"
        and row["evidence_gate_id"] == "vivado_fpga_synth_or_impl"
    )
    assert validation["valid"] is True
    assert vivado_row["status"] == "blocked_invalid_evidence"
    assert "parsed_result_not_kernel_ppa_evidence" in vivado_row["blocker_ids"]
    assert vivado_row["wrong_target_evidence_rejected"] is False
    assert vivado_row["row_classification"]["claim_upgrade_allowed"] is False
    assert vivado_row["required_next_evidence"][0]["required_tool"] == "vivado"
    assert ledger["status_counts"]["blocked_invalid_evidence"] == 1
    assert ledger["trusted_pass_count"] == 0
    assert ledger["deliverable_complete"] is False


def test_ledger_maps_pruned_projection_tool_unavailable_and_cli_writes_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [
            _matrix_row(
                candidate_id="cand-pruned",
                target="fpga",
                status="pruned_with_reason",
                status_reason="resource_budget_screen_rejected",
            ),
            _matrix_row(
                candidate_id="cand-projection",
                target="asic",
                status="projection_only_not_claimable",
                status_reason="model_only_no_dc_timing_area",
            ),
            _matrix_row(candidate_id="cand-tool", target="fpga"),
        ],
    )
    tool_path = _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "blocked",
            "tool_rows": [
                {"tool": "vivado", "available": False, "reason": "unit-test-unavailable"},
                {"tool": "vcs", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
        },
    )

    status = write_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        ic_eda_tool_availability_path=tool_path,
    )
    ledger = json.loads(
        (run_dir / "dft_candidate_workflow_target_evidence_gate_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    validation = json.loads(
        (
            run_dir
            / "dft_candidate_workflow_target_evidence_gate_ledger_validation.json"
        ).read_text(encoding="utf-8")
    )

    assert status["status"] == "passed"
    assert validation["valid"] is True
    assert ledger["deliverable_complete"] is False
    assert {
        row["status"]
        for row in ledger["rows"]
        if row["candidate_id"] == "cand-pruned"
    } == {"pruned_with_reason"}
    assert {
        row["status"]
        for row in ledger["rows"]
        if row["candidate_id"] == "cand-projection"
    } == {"projection_only_not_claimable"}
    tool_vivado = next(
        row for row in ledger["rows"] if row["candidate_id"] == "cand-tool" and row["evidence_gate_id"] == "vivado_fpga_synth_or_impl"
    )
    assert tool_vivado["status"] == "blocked_tool_unavailable"
    assert "required_tool_unavailable:vivado" in tool_vivado["blocker_ids"]
    assert tool_vivado["required_next_evidence"]

    cli_run_dir = tmp_path / "cli-run"
    cli_matrix_path = _write_matrix(
        cli_run_dir / "candidate_workflow_deployment_target_matrix.json",
        [_matrix_row(candidate_id="cand-cli", target="fpga")],
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(LEDGER_BUILDER),
            "--run-dir",
            str(cli_run_dir),
            "--release-matrix",
            str(cli_matrix_path),
            "--quiet",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert (cli_run_dir / "dft_candidate_workflow_target_evidence_gate_ledger.json").exists()
    assert (cli_run_dir / "dft_candidate_workflow_target_evidence_gate_ledger_status.json").exists()


def test_ledger_links_tool_unavailable_rows_to_replayable_attempt_transcripts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [_matrix_row(candidate_id="cand-fpga", target="fpga")],
    )
    transcript_path = run_dir / "commands" / "01_ssh_vivado.txt"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        "\n".join(
            [
                "schema_version: dse.dft_scf.ic_eda_tool_probe_transcript.v1",
                "tool: vivado",
                "transport: ssh",
                "returncode: 127",
                "command:",
                "ssh ic-eda source ~/.bashrc; which vivado || true; LC_ALL=C LANG=C vivado -version",
                "stderr:",
                "vivado: command not found",
            ]
        ),
        encoding="utf-8",
    )
    transcript_ref = {
        "path": "commands/01_ssh_vivado.txt",
        "exists": True,
        "sha256": "sha256-vivado-transcript",
        "hash_algorithm": "sha256",
        "tool": "vivado",
        "transport": "ssh",
        "returncode": 127,
        "artifact_role": "raw_command_transcript_only_not_kernel_ppa",
        "availability_only_not_kernel_ppa": True,
        "kernel_ppa_evidence": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
    }
    attempt = {
        "tool": "vivado",
        "command": "ssh ic-eda source ~/.bashrc; which vivado || true; LC_ALL=C LANG=C vivado -version",
        "returncode": 127,
        "stdout": "",
        "stderr": "vivado: command not found",
        "transport": "ssh",
        "environment": "ssh ic-eda",
        "artifact_role": "tool_availability_only_not_kernel_ppa",
        "availability_only_not_kernel_ppa": True,
        "kernel_ppa_evidence": False,
        "hardware_completion_eligible": False,
        "raw_command_transcript_ref": transcript_ref,
    }
    tool_path = _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "blocked",
            "tool_rows": [
                {"tool": "vivado", "available": False, "reason": "command_not_found"},
                {"tool": "vcs", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
            "raw_attempts": [attempt],
            "raw_command_transcript_refs": [transcript_ref],
            "completion_claim": "availability_only_not_kernel_ppa",
        },
    )
    attempts_path = _write_json(run_dir / "ic_eda_tool_attempts.json", [attempt])

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        ic_eda_tool_availability_path=tool_path,
        ic_eda_tool_attempts_path=attempts_path,
    )
    validation = validate_dft_candidate_workflow_target_evidence_gate_ledger(ledger)

    vivado_row = next(
        row
        for row in ledger["rows"]
        if row["candidate_id"] == "cand-fpga"
        and row["evidence_gate_id"] == "vivado_fpga_synth_or_impl"
    )
    assert validation["valid"] is True
    assert ledger["source_artifacts"]["ic_eda_tool_attempts"]["exists"] is True
    assert vivado_row["status"] == "blocked_tool_unavailable"
    assert vivado_row["tool_attempt_ref_count"] == 1
    assert vivado_row["tool_attempt_refs"][0]["tool"] == "vivado"
    assert vivado_row["tool_attempt_refs"][0]["raw_command_transcript_ref"]["path"] == (
        "commands/01_ssh_vivado.txt"
    )
    assert {
        ref["evidence_role"]
        for ref in vivado_row["evidence_refs"]
    } >= {"tool_availability_attempt"}
    assert vivado_row["tool_attempt_refs"][0]["kernel_ppa_evidence"] is False
    assert vivado_row["deliverable_complete"] is False


def test_ledger_surfaces_candidate_specific_execution_transcripts_and_fail_closed_counts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [
            _matrix_row(candidate_id="cand-pass", target="fpga"),
            _matrix_row(
                candidate_id="cand-projection",
                target="asic",
                status="projection_only_not_claimable",
                status_reason="model_only_no_dc_timing_area",
            ),
            _matrix_row(candidate_id="cand-tool", target="fpga"),
            _matrix_row(candidate_id="cand-wrong", target="fpga"),
        ],
    )
    gate_path = _write_json(
        run_dir / "dft_hardware_closure_gate_adjudication.json",
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication.v1",
            "release_id": "release-ledger-test",
            "status": "blocked_incomplete_hard_gate_evidence",
            "unit_rows": [
                {
                    "unit_id": "cand-pass:fft_ifft_ffft",
                    "candidate_id": "cand-pass",
                    "kernel_id": "fft_ifft_ffft",
                    "stage_rows": [_stage_row("cand-pass", stage_id) for stage_id in FPGA_STAGES],
                    "unit_gate_passed": True,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                },
                {
                    "unit_id": "cand-wrong:fft_ifft_ffft",
                    "candidate_id": "cand-wrong",
                    "kernel_id": "fft_ifft_ffft",
                    "stage_rows": [_stage_row("cand-wrong", "dc_asic_synth_timing_area")],
                    "unit_gate_passed": False,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                },
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    execution_transcript_ref = {
        "path": "candidate_specific_evidence/cand-pass/fft_ifft_ffft/raw_transcript_index.json",
        "exists": True,
        "sha256": "sha256-cand-pass-transcript-index",
        "hash_algorithm": "sha256",
    }
    _write_json(
        run_dir / execution_transcript_ref["path"],
        {
            "schema_version": "dse.dft.hardware_closure.raw_transcript_index.v1",
            "candidate_id": "cand-pass",
            "kernel_id": "fft_ifft_ffft",
            "unit_id": "cand-pass:fft_ifft_ffft",
            "status": "fresh_raw_transcript_refs_recorded",
            "raw_transcript_refs": [
                {
                    "candidate_id": "cand-pass",
                    "kernel_id": "fft_ifft_ffft",
                    "stage_id": "golden_correctness",
                    "path": "candidate_specific_evidence/cand-pass/fft_ifft_ffft/golden_correctness.log",
                    "sha256": "sha256-qe-transcript",
                    "hash_algorithm": "sha256",
                    "candidate_specific": True,
                    "shared_microkernel_smoke_only": False,
                    "source_role": "fresh_candidate_specific_raw_stage_evidence",
                }
            ],
        },
    )
    execution_path = _write_json(
        run_dir / "dft_candidate_specific_ppa_execution.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_execution.v1",
            "status": "fresh_candidate_specific_execution_recorded",
            "units": [
                {
                    "candidate_id": "cand-pass",
                    "kernel_id": "fft_ifft_ffft",
                    "unit_evidence_dir": "candidate_specific_evidence/cand-pass/fft_ifft_ffft",
                    "provenance_refs": [execution_transcript_ref],
                }
            ],
        },
    )
    tool_path = _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "blocked",
            "tool_rows": [
                {"tool": "vivado", "available": False, "reason": "command_not_found"},
                {"tool": "vcs", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
            "raw_attempts": [
                {
                    "tool": "vivado",
                    "command": "ssh ic-eda source ~/.bashrc; which vivado || true; LC_ALL=C LANG=C vivado -version",
                    "returncode": 127,
                    "stdout": "",
                    "stderr": "vivado: command not found",
                    "transport": "ssh",
                    "environment": "ssh ic-eda",
                    "artifact_role": "tool_availability_only_not_kernel_ppa",
                    "availability_only_not_kernel_ppa": True,
                    "kernel_ppa_evidence": False,
                    "hardware_completion_eligible": False,
                    "raw_command_transcript_ref": {
                        "path": "commands/01_ssh_vivado.txt",
                        "exists": True,
                        "sha256": "sha256-vivado-transcript",
                        "hash_algorithm": "sha256",
                        "tool": "vivado",
                        "transport": "ssh",
                        "returncode": 127,
                        "artifact_role": "raw_command_transcript_only_not_kernel_ppa",
                        "availability_only_not_kernel_ppa": True,
                        "kernel_ppa_evidence": False,
                        "hardware_completion_eligible": False,
                        "deliverable_complete": False,
                    },
                }
            ],
            "raw_command_transcript_refs": [
                {
                    "path": "commands/01_ssh_vivado.txt",
                    "exists": True,
                    "sha256": "sha256-vivado-transcript",
                    "hash_algorithm": "sha256",
                    "tool": "vivado",
                    "transport": "ssh",
                    "returncode": 127,
                    "artifact_role": "raw_command_transcript_only_not_kernel_ppa",
                    "availability_only_not_kernel_ppa": True,
                    "kernel_ppa_evidence": False,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                }
            ],
            "completion_claim": "availability_only_not_kernel_ppa",
        },
    )
    attempts_path = _write_json(
        run_dir / "ic_eda_tool_attempts.json",
        [
            {
                "tool": "vivado",
                "command": "ssh ic-eda source ~/.bashrc; which vivado || true; LC_ALL=C LANG=C vivado -version",
                "returncode": 127,
                "stdout": "",
                "stderr": "vivado: command not found",
                "transport": "ssh",
                "environment": "ssh ic-eda",
                "artifact_role": "tool_availability_only_not_kernel_ppa",
                "availability_only_not_kernel_ppa": True,
                "kernel_ppa_evidence": False,
                "hardware_completion_eligible": False,
                "raw_command_transcript_ref": {
                    "path": "commands/01_ssh_vivado.txt",
                    "exists": True,
                    "sha256": "sha256-vivado-transcript",
                    "hash_algorithm": "sha256",
                    "tool": "vivado",
                    "transport": "ssh",
                    "returncode": 127,
                    "artifact_role": "raw_command_transcript_only_not_kernel_ppa",
                    "availability_only_not_kernel_ppa": True,
                    "kernel_ppa_evidence": False,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                },
            }
        ],
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        gate_adjudication_path=gate_path,
        candidate_specific_ppa_execution_path=execution_path,
        ic_eda_tool_availability_path=tool_path,
        ic_eda_tool_attempts_path=attempts_path,
    )

    assert ledger["replayable_tool_transcript_ref_count"] == 1
    assert ledger["replayable_execution_transcript_ref_count"] == 1
    assert ledger["replayable_execution_transcript_refs"] == [
        {
            "candidate_id": "cand-pass",
            "kernel_id": "fft_ifft_ffft",
            "stage_id": "golden_correctness",
            "path": "candidate_specific_evidence/cand-pass/fft_ifft_ffft/golden_correctness.log",
            "sha256": "sha256-qe-transcript",
            "hash_algorithm": "sha256",
            "candidate_specific": True,
            "shared_microkernel_smoke_only": False,
            "source_role": "fresh_candidate_specific_raw_stage_evidence",
        }
    ]
    assert ledger["fail_closed_row_count"] == ledger["row_count"] - ledger["trusted_pass_count"]
    assert ledger["projection_only_row_count"] == 4
    assert ledger["wrong_target_evidence_rejected_row_count"] == 1
    assert ledger["availability_probe_only_row_count"] == 1
    assert ledger["smoke_only_not_kernel_ppa_row_count"] == 0
    assert ledger["stable_blocker_reason_counts"]["required_tool_unavailable:vivado"] == 1
    assert ledger["status_counts"]["projection_only_not_claimable"] == 4


def test_ledger_rows_expose_stable_fail_closed_classification_and_blocker_counts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [
            _matrix_row(
                candidate_id="cand-pruned",
                target="fpga",
                status="pruned_with_reason",
                status_reason="screened_by_release_budget",
            ),
            _matrix_row(candidate_id="cand-tool", target="fpga"),
        ],
    )
    transcript_ref = {
        "path": "commands/01_ssh_vivado.txt",
        "exists": True,
        "sha256": "sha256-vivado-transcript",
        "hash_algorithm": "sha256",
        "tool": "vivado",
        "transport": "ssh",
        "returncode": 127,
        "artifact_role": "raw_command_transcript_only_not_kernel_ppa",
        "availability_only_not_kernel_ppa": True,
        "kernel_ppa_evidence": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
    }
    attempt = {
        "tool": "vivado",
        "command": "ssh ic-eda source ~/.bashrc; which vivado || true; LC_ALL=C LANG=C vivado -version",
        "returncode": 127,
        "stdout": "",
        "stderr": "vivado: command not found",
        "transport": "ssh",
        "environment": "ssh ic-eda",
        "raw_command_transcript_ref": transcript_ref,
    }
    tool_path = _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "blocked",
            "tool_rows": [
                {"tool": "vivado", "available": False, "reason": "command_not_found"},
                {"tool": "vcs", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
            "raw_attempts": [attempt],
            "completion_claim": "availability_only_not_kernel_ppa",
        },
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        ic_eda_tool_availability_path=tool_path,
    )
    validation = validate_dft_candidate_workflow_target_evidence_gate_ledger(ledger)

    assert validation["valid"] is True
    assert ledger["stable_blocker_reason_counts"]["screened_by_release_budget"] == len(FPGA_STAGES)
    assert ledger["stable_blocker_reason_counts"]["required_tool_unavailable:vivado"] == 1
    assert ledger["replayable_tool_transcript_ref_count"] == 1

    pruned_row = next(row for row in ledger["rows"] if row["candidate_id"] == "cand-pruned")
    assert pruned_row["row_classification"] == {
        "source_matrix_status": "pruned_with_reason",
        "ledger_status": "pruned_with_reason",
        "stable_blocker_reason_id": "screened_by_release_budget",
        "candidate_workflow_deployment_target_axes_bound": True,
        "candidate_kernel_axis_bound": False,
        "availability_probe_only": False,
        "claim_upgrade_allowed": False,
        "replayable_tool_transcript_ref_count": 0,
    }

    tool_row = next(
        row
        for row in ledger["rows"]
        if row["candidate_id"] == "cand-tool"
        and row["evidence_gate_id"] == "vivado_fpga_synth_or_impl"
    )
    assert tool_row["row_classification"]["source_matrix_status"] == "blocked_missing_input"
    assert tool_row["row_classification"]["stable_blocker_reason_id"] == "required_tool_unavailable:vivado"
    assert tool_row["row_classification"]["availability_probe_only"] is True
    assert tool_row["row_classification"]["claim_upgrade_allowed"] is False
    assert tool_row["row_classification"]["replayable_tool_transcript_ref_count"] == 1
    assert tool_row["tool_attempt_refs"][0]["kernel_ppa_evidence"] is False
    assert tool_row["hardware_completion_eligible"] is False


def test_ledger_status_exposes_kernel_unbound_parsed_stage_refs_fail_closed(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [_matrix_row(candidate_id="cand-unbound", target="fpga")],
    )
    parsed_ref = {
        "path": (
            "parsed_hard_gate_results/cand-unbound/__unbound__/"
            "vivado_fpga_synth_or_impl_parsed_result.json"
        ),
        "exists": True,
        "sha256": "sha256-unbound-vivado",
        "hash_algorithm": "sha256",
    }
    gate_path = _write_json(
        run_dir / "dft_hardware_closure_gate_adjudication.json",
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication.v1",
            "release_id": "release-ledger-test",
            "status": "blocked_incomplete_hard_gate_evidence",
            "candidate_kernel_axis_unbound_stage_count": 1,
            "parsed_stage_result_ref_count": 1,
            "parsed_stage_result_refs": [parsed_ref],
            "unit_rows": [
                {
                    "unit_id": "cand-unbound:__unbound__",
                    "candidate_id": "cand-unbound",
                    "kernel_id": "__unbound__",
                    "candidate_kernel_axis_bound": False,
                    "stage_rows": [
                        {
                            "candidate_id": "cand-unbound",
                            "kernel_id": "__unbound__",
                            "candidate_kernel_axis_bound": False,
                            "stage_id": "vivado_fpga_synth_or_impl",
                            "parsed_result_present": True,
                            "parsed_result_schema_valid": True,
                            "parsed_verdict": "passed",
                            "stage_gate_passed": False,
                            "status": "blocked_invalid_parsed_result",
                            "blocker_id": "parsed_result_kernel_axis_unbound",
                            "parsed_blocker_ids": [
                                "parsed_result_kernel_axis_unbound"
                            ],
                            "adjudication_result": "blocked_stage_gate",
                            "parsed_result": parsed_ref,
                            "raw_evidence_ref_count": 1,
                            "hardware_completion_eligible": False,
                            "deliverable_complete": False,
                        }
                    ],
                    "unit_gate_passed": False,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                }
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        gate_adjudication_path=gate_path,
    )
    validation = validate_dft_candidate_workflow_target_evidence_gate_ledger(ledger)
    status = write_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        gate_adjudication_path=gate_path,
    )
    status_payload = json.loads((run_dir / LEDGER_STATUS_ARTIFACT_NAME).read_text(encoding="utf-8"))

    vivado_row = next(
        row
        for row in ledger["rows"]
        if row["candidate_id"] == "cand-unbound"
        and row["evidence_gate_id"] == "vivado_fpga_synth_or_impl"
    )
    assert validation["valid"] is True
    assert vivado_row["kernel_id"] == "__unbound__"
    assert vivado_row["row_classification"]["candidate_kernel_axis_bound"] is False
    assert vivado_row["status"] == "blocked_invalid_evidence"
    assert "parsed_result_kernel_axis_unbound" in vivado_row["blocker_ids"]
    assert {
        ref["path"]
        for ref in vivado_row["evidence_refs"]
        if ref.get("evidence_role") == "parsed_stage_result"
    } == {parsed_ref["path"]}
    assert ledger["candidate_kernel_axis_unbound_row_count"] == len(FPGA_STAGES)
    assert ledger["parsed_stage_result_ref_count"] == 1
    assert ledger["parsed_stage_result_refs"] == [
        {**parsed_ref, "evidence_role": "parsed_stage_result"}
    ]
    assert validation["candidate_kernel_axis_unbound_row_count"] == len(FPGA_STAGES)
    assert validation["parsed_stage_result_ref_count"] == 1
    assert status_payload["candidate_kernel_axis_unbound_row_count"] == len(FPGA_STAGES)
    assert status_payload["parsed_stage_result_ref_count"] == 1
    assert status_payload["parsed_stage_result_refs"] == ledger["parsed_stage_result_refs"]
    assert status["candidate_kernel_axis_unbound_row_count"] == len(FPGA_STAGES)


def test_ledger_status_exposes_candidate_kernel_target_axes_and_target_counts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [
            _matrix_row(candidate_id="cand-a", target="fpga"),
            _matrix_row(candidate_id="cand-b", target="asic"),
        ],
    )
    parsed_refs = {
        "fpga": {
            "path": (
                "parsed_hard_gate_results/cand-a/fft_ifft_ffft/"
                "vivado_fpga_synth_or_impl_parsed_result.json"
            ),
            "exists": True,
            "sha256": "sha256-cand-a-vivado",
            "hash_algorithm": "sha256",
        },
        "asic": {
            "path": (
                "parsed_hard_gate_results/cand-b/reduction_tree/"
                "dc_asic_synth_timing_area_parsed_result.json"
            ),
            "exists": True,
            "sha256": "sha256-cand-b-dc",
            "hash_algorithm": "sha256",
        },
    }
    gate_path = _write_json(
        run_dir / "dft_hardware_closure_gate_adjudication.json",
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication.v1",
            "release_id": "release-ledger-axis-visibility",
            "status": "blocked_incomplete_hard_gate_evidence",
            "unit_rows": [
                {
                    "unit_id": "cand-a:fft_ifft_ffft",
                    "candidate_id": "cand-a",
                    "kernel_id": "fft_ifft_ffft",
                    "target_platform_kind": "fpga",
                    "candidate_kernel_target_axis_id": "cand-a::fft_ifft_ffft::fpga",
                    "stage_rows": [
                        {
                            **_stage_row("cand-a", "vivado_fpga_synth_or_impl"),
                            "target_platform_kind": "fpga",
                            "parsed_result": parsed_refs["fpga"],
                        }
                    ],
                    "unit_gate_passed": False,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                },
                {
                    "unit_id": "cand-b:reduction_tree",
                    "candidate_id": "cand-b",
                    "kernel_id": "reduction_tree",
                    "target_platform_kind": "asic",
                    "candidate_kernel_target_axis_id": "cand-b::reduction_tree::asic",
                    "stage_rows": [
                        {
                            **_stage_row("cand-b", "dc_asic_synth_timing_area"),
                            "kernel_id": "reduction_tree",
                            "target_platform_kind": "asic",
                            "parsed_result": parsed_refs["asic"],
                        }
                    ],
                    "unit_gate_passed": False,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                },
            ],
            "candidate_kernel_target_axis_count": 2,
            "candidate_kernel_target_axis_counts_by_target": {"asic": 1, "fpga": 1},
            "parsed_stage_result_ref_count": 2,
            "parsed_stage_result_refs": [parsed_refs["fpga"], parsed_refs["asic"]],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    status = write_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        gate_adjudication_path=gate_path,
    )
    ledger = json.loads((run_dir / LEDGER_ARTIFACT_NAME).read_text(encoding="utf-8"))
    validation = json.loads(
        (run_dir / LEDGER_VALIDATION_ARTIFACT_NAME).read_text(encoding="utf-8")
    )

    assert ledger["candidate_kernel_target_axis_count"] == 2
    assert ledger["candidate_kernel_target_axis_counts_by_target"] == {
        "asic": 1,
        "fpga": 1,
    }
    assert ledger["row_counts_by_candidate_kernel_target_axis"] == {
        "cand-a::fft_ifft_ffft::fpga": len(FPGA_STAGES),
        "cand-b::reduction_tree::asic": len(ASIC_STAGES),
    }
    assert ledger["row_counts_by_target_platform_kind"] == {
        "asic": len(ASIC_STAGES),
        "fpga": len(FPGA_STAGES),
    }
    assert {row["candidate_kernel_target_axis_id"] for row in ledger["rows"]} == {
        "cand-a::fft_ifft_ffft::fpga",
        "cand-b::reduction_tree::asic",
    }
    assert {
        tuple(row["target_required_stage_ids"])
        for row in ledger["rows"]
        if row["target_platform_kind"] == "fpga"
    } == {FPGA_STAGES}
    assert validation["candidate_kernel_target_axis_count"] == 2
    assert validation["row_counts_by_target_platform_kind"] == {
        "asic": len(ASIC_STAGES),
        "fpga": len(FPGA_STAGES),
    }
    assert status["candidate_kernel_target_axis_count"] == 2
    assert status["candidate_kernel_target_axis_counts_by_target"] == {
        "asic": 1,
        "fpga": 1,
    }
    assert status["row_counts_by_candidate_kernel_target_axis"] == {
        "cand-a::fft_ifft_ffft::fpga": len(FPGA_STAGES),
        "cand-b::reduction_tree::asic": len(ASIC_STAGES),
    }
    assert status["row_counts_by_target_platform_kind"] == {
        "asic": len(ASIC_STAGES),
        "fpga": len(FPGA_STAGES),
    }
    assert status["parsed_stage_result_refs"] == ledger["parsed_stage_result_refs"]
    assert status["deliverable_complete"] is False


def test_missing_input_rows_cite_available_tool_attempts_without_upgrading_claims(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [_matrix_row(candidate_id="cand-tool", target="fpga")],
    )
    transcript_ref = {
        "path": "commands/01_ssh_vivado.txt",
        "exists": True,
        "sha256": "sha256-vivado-transcript",
        "hash_algorithm": "sha256",
        "tool": "vivado",
        "transport": "ssh",
        "returncode": 0,
        "artifact_role": "raw_command_transcript_only_not_kernel_ppa",
        "availability_only_not_kernel_ppa": True,
        "kernel_ppa_evidence": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
    }
    attempts_path = _write_json(
        run_dir / "ic_eda_tool_attempts.json",
        [
            {
                "tool": "vivado",
                "command": "ssh ic-eda source ~/.bashrc; which vivado || true; LC_ALL=C LANG=C vivado -version",
                "returncode": 0,
                "stdout": "Vivado v2019.1",
                "stderr": "",
                "transport": "ssh",
                "environment": "ssh ic-eda",
                "artifact_role": "tool_availability_only_not_kernel_ppa",
                "availability_only_not_kernel_ppa": True,
                "kernel_ppa_evidence": False,
                "hardware_completion_eligible": False,
                "raw_command_transcript_ref": transcript_ref,
            }
        ],
    )
    tool_path = _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vivado", "available": True},
                {"tool": "vcs", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
            "raw_attempts": [
                {
                    "tool": "vivado",
                    "command": "ssh ic-eda source ~/.bashrc; which vivado || true; LC_ALL=C LANG=C vivado -version",
                    "returncode": 0,
                    "stdout": "Vivado v2019.1",
                    "stderr": "",
                    "transport": "ssh",
                    "environment": "ssh ic-eda",
                    "artifact_role": "tool_availability_only_not_kernel_ppa",
                    "availability_only_not_kernel_ppa": True,
                    "kernel_ppa_evidence": False,
                    "hardware_completion_eligible": False,
                    "raw_command_transcript_ref": transcript_ref,
                }
            ],
            "raw_command_transcript_refs": [transcript_ref],
            "completion_claim": "availability_only_not_kernel_ppa",
        },
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        ic_eda_tool_availability_path=tool_path,
        ic_eda_tool_attempts_path=attempts_path,
    )

    vivado_row = next(
        row
        for row in ledger["rows"]
        if row["candidate_id"] == "cand-tool"
        and row["evidence_gate_id"] == "vivado_fpga_synth_or_impl"
    )
    assert vivado_row["status"] == "blocked_missing_input"
    assert vivado_row["row_classification"]["availability_probe_only"] is True
    assert vivado_row["row_classification"]["required_tool"] == "vivado"
    assert vivado_row["row_classification"]["required_tool_availability_status"] == (
        "available_from_availability_probe"
    )
    assert vivado_row["row_classification"]["availability_probe_transport"] == ["ssh"]
    assert vivado_row["row_classification"]["availability_probe_kernel_ppa_evidence"] is False
    assert vivado_row["tool_attempt_ref_count"] == 1
    assert vivado_row["tool_attempt_refs"][0]["tool"] == "vivado"
    assert vivado_row["tool_attempt_refs"][0]["availability_only_not_kernel_ppa"] is True
    assert vivado_row["ic_eda_tool_availability_ref"]["path"] == str(tool_path)
    assert vivado_row["ic_eda_tool_availability_ref"]["exists"] is True
    assert vivado_row["ic_eda_tool_availability_ref"]["sha256"]
    assert vivado_row["ic_eda_tool_availability_ref"]["artifact_role"] == "ic_eda_tool_availability"
    assert vivado_row["required_next_evidence"][0]["required_tool"] == "vivado"
    assert vivado_row["required_next_evidence"][0]["availability_prerequisite_status"] == (
        "available_from_availability_probe"
    )
    assert vivado_row["required_next_evidence"][0]["candidate_kernel_specific_gate_required"] is True
    assert vivado_row["required_next_evidence"][0]["availability_only_not_kernel_ppa"] is True
    assert vivado_row["required_next_evidence"][0]["kernel_ppa_evidence"] is False
    assert vivado_row["required_next_evidence"][0]["required_artifacts"] == [
        "vivado_synth_or_impl.log",
        "vivado_timing_summary.rpt",
        "vivado_utilization.rpt",
        "vivado_route_status.json",
    ]
    assert {
        ref["evidence_role"]
        for ref in vivado_row["evidence_refs"]
    } >= {"tool_availability_attempt", "ic_eda_tool_availability"}
    assert vivado_row["hardware_completion_eligible"] is False
    assert vivado_row["deliverable_complete"] is False


def test_missing_input_rows_attach_candidate_specific_execution_stage_refs(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [_matrix_row(candidate_id="cand-exec", target="fpga")],
    )
    execution_path = _write_json(
        run_dir / "dft_candidate_specific_ppa_execution.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_execution.v1",
            "status": "blocked_fresh_candidate_specific_execution",
            "units": [
                {
                    "unit_id": "cand-exec:fft_ifft_ffft",
                    "candidate_id": "cand-exec",
                    "kernel_id": "fft_ifft_ffft",
                    "status": "blocked_fresh_candidate_specific_execution",
                    "command_run_id": "fresh_ppa_unit_test",
                    "unit_evidence_dir": "candidate_specific_evidence/cand-exec/fft_ifft_ffft",
                    "stage_ids": ["vivado_fpga_synth_or_impl"],
                    "stage_results": [
                        {
                            "stage_id": "vivado_fpga_synth_or_impl",
                            "status": "blocked_missing_required_outputs",
                            "gate_passed": False,
                            "raw_evidence_captured": False,
                            "materialized_raw_file_count": 0,
                            "required_outputs": [
                                {
                                    "file_name": "vivado_synth_or_impl.log",
                                    "path": (
                                        "candidate_specific_evidence/cand-exec/"
                                        "fft_ifft_ffft/vivado_synth_or_impl.log"
                                    ),
                                    "exists": False,
                                },
                                {
                                    "file_name": "vivado_timing_summary.rpt",
                                    "path": (
                                        "candidate_specific_evidence/cand-exec/"
                                        "fft_ifft_ffft/vivado_timing_summary.rpt"
                                    ),
                                    "exists": False,
                                },
                            ],
                            "missing_required_outputs": [
                                "vivado_synth_or_impl.log",
                                "vivado_timing_summary.rpt",
                            ],
                            "blocker_ids": [
                                "vivado_fpga_synth_or_impl:missing_required_outputs"
                            ],
                        }
                    ],
                    "materialized_rows": [],
                    "provenance_refs": [
                        {
                            "path": (
                                "candidate_specific_evidence/cand-exec/"
                                "fft_ifft_ffft/raw_transcript_index.json"
                            ),
                            "exists": True,
                            "sha256": "sha256-raw-index",
                            "hash_algorithm": "sha256",
                        }
                    ],
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                }
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        candidate_specific_ppa_execution_path=execution_path,
    )
    validation = validate_dft_candidate_workflow_target_evidence_gate_ledger(ledger)

    vivado_row = next(
        row
        for row in ledger["rows"]
        if row["candidate_id"] == "cand-exec"
        and row["evidence_gate_id"] == "vivado_fpga_synth_or_impl"
    )
    assert validation["valid"] is True
    assert vivado_row["status"] == "blocked_missing_input"
    assert vivado_row["candidate_specific_execution_ref_count"] == 1
    assert vivado_row["candidate_specific_execution_refs"][0] == {
        "evidence_role": "candidate_specific_stage_execution",
        "candidate_id": "cand-exec",
        "kernel_id": "fft_ifft_ffft",
        "unit_id": "cand-exec:fft_ifft_ffft",
        "stage_id": "vivado_fpga_synth_or_impl",
        "stage_status": "blocked_missing_required_outputs",
        "unit_status": "blocked_fresh_candidate_specific_execution",
        "command_run_id": "fresh_ppa_unit_test",
        "unit_evidence_dir": "candidate_specific_evidence/cand-exec/fft_ifft_ffft",
        "required_outputs": [
            {
                "file_name": "vivado_synth_or_impl.log",
                "path": (
                    "candidate_specific_evidence/cand-exec/"
                    "fft_ifft_ffft/vivado_synth_or_impl.log"
                ),
                "exists": False,
            },
            {
                "file_name": "vivado_timing_summary.rpt",
                "path": (
                    "candidate_specific_evidence/cand-exec/"
                    "fft_ifft_ffft/vivado_timing_summary.rpt"
                ),
                "exists": False,
            },
        ],
        "missing_required_outputs": [
            "vivado_synth_or_impl.log",
            "vivado_timing_summary.rpt",
        ],
        "blocker_ids": ["vivado_fpga_synth_or_impl:missing_required_outputs"],
        "materialized_raw_file_count": 0,
        "candidate_specific": True,
        "availability_only_not_kernel_ppa": False,
        "kernel_ppa_evidence": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
    }
    assert {
        ref["evidence_role"]
        for ref in vivado_row["evidence_refs"]
    } >= {"candidate_specific_stage_execution"}
    assert vivado_row["required_next_evidence"][0][
        "target_specific_missing_input_reason"
    ] == "missing_target_specific_gate_evidence:fpga:vivado_fpga_synth_or_impl"
    assert ledger["candidate_specific_execution_ref_count"] == 1
    assert vivado_row["hardware_completion_eligible"] is False
    assert vivado_row["deliverable_complete"] is False

    status = write_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        candidate_specific_ppa_execution_path=execution_path,
    )
    status_payload = json.loads((run_dir / LEDGER_STATUS_ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert status_payload["candidate_specific_execution_ref_count"] == 1
    assert status["candidate_specific_execution_ref_count"] == 1


def test_missing_input_rows_cite_standalone_raw_transcript_refs_without_upgrading_claims(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [_matrix_row(candidate_id="cand-tool", target="asic")],
    )
    transcript_ref = {
        "path": "commands/06_ssh_dc_shell.txt",
        "exists": True,
        "sha256": "sha256-dc-shell-transcript",
        "hash_algorithm": "sha256",
        "tool": "dc_shell",
        "transport": "ssh",
        "returncode": 1,
        "artifact_role": "raw_command_transcript_only_not_kernel_ppa",
        "availability_only_not_kernel_ppa": True,
        "kernel_ppa_evidence": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
    }
    tool_path = _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vivado", "available": True},
                {"tool": "vcs", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
            "raw_command_transcript_refs": [transcript_ref],
            "raw_command_transcript_ref_count": 1,
            "completion_claim": "availability_only_not_kernel_ppa",
        },
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        ic_eda_tool_availability_path=tool_path,
    )

    dc_row = next(
        row
        for row in ledger["rows"]
        if row["candidate_id"] == "cand-tool"
        and row["evidence_gate_id"] == "dc_asic_synth_timing_area"
    )
    assert dc_row["status"] == "blocked_missing_input"
    assert dc_row["row_classification"]["availability_probe_only"] is True
    assert dc_row["row_classification"]["replayable_tool_transcript_ref_count"] == 1
    assert dc_row["tool_attempt_ref_count"] == 1
    assert dc_row["tool_attempt_refs"][0]["raw_command_transcript_ref"] == transcript_ref
    assert dc_row["tool_attempt_refs"][0]["kernel_ppa_evidence"] is False
    assert dc_row["required_next_evidence"][0]["required_tool"] == "dc_shell"
    assert dc_row["hardware_completion_eligible"] is False
    assert dc_row["deliverable_complete"] is False
    assert ledger["replayable_tool_transcript_ref_count"] == 1


def test_written_status_exposes_replayability_summary_for_report_consumers(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [_matrix_row(candidate_id="cand-tool", target="fpga")],
    )
    transcript_ref = {
        "path": "commands/01_ssh_vivado.txt",
        "exists": True,
        "sha256": "sha256-vivado-transcript",
        "hash_algorithm": "sha256",
        "tool": "vivado",
        "transport": "ssh",
        "returncode": 127,
        "artifact_role": "raw_command_transcript_only_not_kernel_ppa",
        "availability_only_not_kernel_ppa": True,
        "kernel_ppa_evidence": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
    }
    attempt = {
        "tool": "vivado",
        "command": "ssh ic-eda source ~/.bashrc; which vivado || true; LC_ALL=C LANG=C vivado -version",
        "returncode": 127,
        "stdout": "",
        "stderr": "vivado: command not found",
        "transport": "ssh",
        "environment": "ssh ic-eda",
        "raw_command_transcript_ref": transcript_ref,
    }
    tool_path = _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "blocked",
            "tool_rows": [
                {"tool": "vivado", "available": False, "reason": "command_not_found"},
                {"tool": "vcs", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
            "raw_attempts": [attempt],
            "raw_command_transcript_refs": [transcript_ref],
            "completion_claim": "availability_only_not_kernel_ppa",
        },
    )

    status = write_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        ic_eda_tool_availability_path=tool_path,
    )
    status_payload = json.loads((run_dir / LEDGER_STATUS_ARTIFACT_NAME).read_text(encoding="utf-8"))
    validation = json.loads(
        (run_dir / LEDGER_VALIDATION_ARTIFACT_NAME).read_text(encoding="utf-8")
    )

    assert status_payload["stable_blocker_reason_counts"][
        "required_tool_unavailable:vivado"
    ] == 1
    assert validation["stable_blocker_reason_counts"][
        "required_tool_unavailable:vivado"
    ] == 1
    assert validation["blocker_count"] == 0
    assert status_payload["replayable_tool_transcript_ref_count"] == 1
    assert status_payload["replayable_tool_transcript_refs"] == [transcript_ref]
    assert status_payload["replayable_execution_transcript_ref_count"] == 0
    assert status_payload["replayable_execution_transcript_refs"] == []
    assert status_payload["fail_closed_row_count"] == 4
    assert status_payload["projection_only_row_count"] == 0
    assert status_payload["wrong_target_evidence_rejected_row_count"] == 0
    assert status_payload["smoke_only_not_kernel_ppa_row_count"] == 0
    assert status_payload["availability_probe_only_row_count"] == 1
    assert status_payload["claim_upgrade_allowed_count"] == 0
    assert status_payload["hardware_completion_eligible"] is False
    assert status_payload["deliverable_complete"] is False
    assert status["replayable_tool_transcript_ref_count"] == 1


def test_written_ledger_exposes_stable_report_package_input_contract(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_matrix(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        [_matrix_row(candidate_id="cand-package", target="fpga")],
    )

    status = write_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
    )
    ledger = json.loads((run_dir / LEDGER_ARTIFACT_NAME).read_text(encoding="utf-8"))
    validation = json.loads(
        (run_dir / LEDGER_VALIDATION_ARTIFACT_NAME).read_text(encoding="utf-8")
    )
    status_payload = json.loads((run_dir / LEDGER_STATUS_ARTIFACT_NAME).read_text(encoding="utf-8"))

    contract = status_payload["report_package_input_contract"]
    assert contract["package_id"] == "dft_candidate_workflow_target_evidence_gate_ledger"
    assert contract["consumer_hint"] == "run3_complete_dse_claims_report_integration"
    assert contract["artifact_names"] == [
        LEDGER_ARTIFACT_NAME,
        LEDGER_VALIDATION_ARTIFACT_NAME,
        LEDGER_STATUS_ARTIFACT_NAME,
    ]
    assert [artifact["artifact_role"] for artifact in contract["artifacts"]] == [
        "target_evidence_gate_ledger",
        "target_evidence_gate_ledger_validation",
        "target_evidence_gate_ledger_status",
    ]
    assert all(artifact["required_for_report_package"] is True for artifact in contract["artifacts"])
    assert all(artifact["path"] for artifact in contract["artifacts"])
    assert all(artifact["schema_id"] for artifact in contract["artifacts"])
    assert contract["deliverable_complete"] is False
    assert contract["required_counter_fields"] == [
        "candidate_kernel_target_axis_count",
        "candidate_kernel_target_axis_counts_by_target",
        "row_counts_by_candidate_kernel_target_axis",
        "row_counts_by_target_platform_kind",
        "unknown_target_platform_kind_row_count",
        "parsed_stage_result_ref_count",
        "stable_blocker_reason_counts",
        "blocker_count",
    ]
    assert contract["counter_field_groups"] == {
        "target_axis_counters": [
            "candidate_kernel_target_axis_count",
            "candidate_kernel_target_axis_counts_by_target",
            "row_counts_by_candidate_kernel_target_axis",
            "row_counts_by_target_platform_kind",
        ],
        "unknown_target_counters": ["unknown_target_platform_kind_row_count"],
        "parsed_stage_ref_counters": ["parsed_stage_result_ref_count"],
        "blocker_counters": ["stable_blocker_reason_counts", "blocker_count"],
    }

    assert ledger["report_package_input_contract"]["package_id"] == contract["package_id"]
    assert validation["report_package_input_contract"]["package_id"] == contract["package_id"]
    assert status["report_package_input_contract"]["package_id"] == contract["package_id"]
