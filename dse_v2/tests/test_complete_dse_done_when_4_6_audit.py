#!/usr/bin/env python3
"""Fail-closed current-goal Done-when 4-6 audit tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.complete_dse_search_space import build_release_subset_manifest
from dse_v2.reference_workloads.complete_dse_done_when_4_6_audit import (
    COMPLETE_DSE_DONE_WHEN_4_6_AUDIT_SCHEMA,
    build_complete_dse_done_when_4_6_audit,
)
import dse_v2.reference_workloads.complete_dse_done_when_4_6_audit as done_when_4_6
from dse_v2.reference_workloads.dft_deployment_decision_summary import (
    write_dft_deployment_decision_summary,
)
from dse_v2.reference_workloads.dft_scf_six_class_suite import (
    DFT_SCF_SIX_CLASS_MANIFEST_NAME,
    REQUIRED_DFT_SCF_CLASS_IDS,
    write_dft_scf_six_class_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "audit_complete_dse_done_when_4_6.py"
PACKAGE_CLI = (
    REPO_ROOT
    / "dse_v2"
    / "scripts"
    / "dse"
    / "build_complete_dse_release_artifact_package.py"
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


def _control_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    goal = tmp_path / "goal.md"
    barrier = tmp_path / "barrier.md"
    preflight = tmp_path / "preflight.md"
    goal.write_text(
        "Done-when 4: north-star spec\n"
        "Done-when 5: QE workload inputs\n"
        "Done-when 6: finite release universe over six strict SCF classes\n",
        encoding="utf-8",
    )
    barrier.write_text(
        "run1: default workflow axis is 4 while release obligation is six strict SCF cases\n",
        encoding="utf-8",
    )
    preflight.write_text(
        "run1 writable scope: Done-when 4-6 audit/report\n",
        encoding="utf-8",
    )
    return goal, barrier, preflight


def _done_when(payload: dict, done_when_id: int) -> dict:
    return next(item for item in payload["checklist"] if item["done_when_id"] == done_when_id)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_target_counter_artifacts(run_dir: Path) -> dict[str, Path]:
    ledger_path = _write_json(
        run_dir / "dft_candidate_workflow_target_evidence_gate_ledger.json",
        {
            "schema_version": "dse.dft.candidate_workflow_target_evidence_gate_ledger.v1",
            "generated_at": "2026-05-26T02:00:00Z",
            "release_id": "release-target-counter-test",
            "row_count": 2,
            "expected_row_count": 2,
            "candidate_kernel_target_axis_count": 2,
            "candidate_kernel_target_axis_counts_by_target": {"asic": 1, "fpga": 1},
            "row_counts_by_candidate_kernel_target_axis": {
                "cand-a::fft_ifft_ffft::fpga": 1,
                "cand-b::reduction_tree::asic": 1,
            },
            "row_counts_by_target_platform_kind": {"asic": 1, "fpga": 1},
            "candidate_kernel_axis_unbound_row_count": 0,
            "unknown_target_platform_kind_row_count": 0,
            "parsed_stage_result_ref_count": 2,
            "stable_blocker_reason_counts": {
                "parsed_result_kernel_axis_unbound": 0,
                "required_tool_unavailable:vivado": 1,
            },
            "blocker_count": 1,
            "source_artifacts": {
                "candidate_workflow_deployment_target_matrix": {
                    "path": str(run_dir / "candidate_workflow_deployment_target_matrix.json"),
                    "exists": True,
                    "sha256": "sha256-matrix",
                    "hash_algorithm": "sha256",
                }
            },
            "rows": [
                {
                    "candidate_id": "cand-a",
                    "kernel_id": "fft_ifft_ffft",
                    "workflow_case_id": "qe_full_scf_small",
                    "deployment_boundary_id": "full_scf_evaluated_hybrid",
                    "target_platform_id": "fpga_vivado_release_v1",
                    "target_platform_kind": "fpga",
                    "evidence_gate_id": "vivado_fpga_synth_or_impl",
                    "source_matrix_evidence_gate_id": "vivado_synthesis_or_implementation",
                    "source_matrix_row_id": "matrix::cand-a::fpga::vivado_synthesis_or_implementation",
                    "row_provenance": {
                        "source_matrix_evidence_gate_id": "vivado_synthesis_or_implementation",
                        "source_matrix_row_hash": "source-row-hash-fpga",
                    },
                    "status": "blocked_tool_unavailable",
                    "deliverable_complete": False,
                },
                {
                    "candidate_id": "cand-b",
                    "kernel_id": "reduction_tree",
                    "workflow_case_id": "qe_full_scf_small",
                    "deployment_boundary_id": "full_scf_evaluated_hybrid",
                    "target_platform_id": "asic_synopsys_dc_release_v1",
                    "target_platform_kind": "asic",
                    "evidence_gate_id": "dc_asic_synth_timing_area",
                    "source_matrix_evidence_gate_id": "dc_synthesis_timing_area",
                    "source_matrix_row_id": "matrix::cand-b::asic::dc_synthesis_timing_area",
                    "row_provenance": {
                        "source_matrix_evidence_gate_id": "dc_synthesis_timing_area",
                        "source_matrix_row_hash": "source-row-hash-asic",
                    },
                    "status": "blocked_missing_input",
                    "deliverable_complete": False,
                },
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    ledger_validation_path = _write_json(
        run_dir / "dft_candidate_workflow_target_evidence_gate_ledger_validation.json",
        {
            "schema_version": "dse.dft.candidate_workflow_target_evidence_gate_ledger_validation.v1",
            "valid": True,
            "row_count": 2,
            "expected_row_count": 2,
            "candidate_kernel_target_axis_count": 2,
            "candidate_kernel_target_axis_counts_by_target": {"asic": 1, "fpga": 1},
            "row_counts_by_candidate_kernel_target_axis": {
                "cand-a::fft_ifft_ffft::fpga": 1,
                "cand-b::reduction_tree::asic": 1,
            },
            "row_counts_by_target_platform_kind": {"asic": 1, "fpga": 1},
            "candidate_kernel_axis_unbound_row_count": 0,
            "unknown_target_platform_kind_row_count": 0,
            "parsed_stage_result_ref_count": 2,
            "stable_blocker_reason_counts": {
                "parsed_result_kernel_axis_unbound": 0,
                "required_tool_unavailable:vivado": 1,
            },
            "blocker_count": 0,
            "blockers": [],
            "deliverable_complete": False,
        },
    )
    ledger_status_path = _write_json(
        run_dir / "dft_candidate_workflow_target_evidence_gate_ledger_status.json",
        {
            "schema_version": "dse.dft.candidate_workflow_target_evidence_gate_ledger_status.v1",
            "generated_at": "2026-05-26T02:00:00Z",
            "status": "passed",
            "ledger_status": "recorded",
            "row_count": 2,
            "expected_row_count": 2,
            "candidate_kernel_axis_count": 2,
            "candidate_kernel_target_axis_count": 2,
            "candidate_kernel_target_axis_counts_by_target": {"asic": 1, "fpga": 1},
            "status_counts": {"blocked_tool_unavailable": 1, "trusted_pass": 1},
            "stable_blocker_reason_counts": {
                "parsed_result_kernel_axis_unbound": 0,
                "required_tool_unavailable:vivado": 1,
            },
            "replayable_tool_transcript_ref_count": 1,
            "replayable_execution_transcript_ref_count": 0,
            "candidate_specific_execution_ref_count": 0,
            "row_counts_by_candidate_kernel_target_axis": {
                "cand-a::fft_ifft_ffft::fpga": 1,
                "cand-b::reduction_tree::asic": 1,
            },
            "row_counts_by_target_platform_kind": {"asic": 1, "fpga": 1},
            "fail_closed_row_count": 1,
            "projection_only_row_count": 0,
            "wrong_target_evidence_rejected_row_count": 0,
            "smoke_only_not_kernel_ppa_row_count": 0,
            "candidate_kernel_axis_unbound_row_count": 0,
            "unknown_target_platform_kind_row_count": 0,
            "parsed_stage_result_ref_count": 2,
            "parsed_stage_result_refs": [
                {
                    "path": "parsed/cand-a/fft_ifft_ffft/vivado_fpga_synth_or_impl.json",
                    "exists": True,
                    "sha256": "sha256-cand-a-vivado",
                    "hash_algorithm": "sha256",
                },
                {
                    "path": "parsed/cand-b/reduction_tree/dc_asic_synth_timing_area.json",
                    "exists": True,
                    "sha256": "sha256-cand-b-dc",
                    "hash_algorithm": "sha256",
                },
            ],
            "availability_probe_only_row_count": 1,
            "claim_upgrade_allowed_count": 0,
            "blocker_count": 1,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    gate_path = _write_json(
        run_dir / "dft_hardware_closure_gate_adjudication.json",
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication.v1",
            "release_id": "release-target-counter-test",
            "status": "blocked_incomplete_hard_gate_evidence",
            "candidate_kernel_target_axis_count": 2,
            "candidate_kernel_target_axis_counts_by_target": {"asic": 1, "fpga": 1},
            "stage_counts_by_target": {"asic": 1, "fpga": 1},
            "unknown_target_platform_kind_unit_count": 0,
            "unknown_target_platform_kind_stage_count": 0,
            "blocker_id_counts": {"required_tool_unavailable:vivado": 1},
            "stage_gate_passed_count": 1,
            "blocked_stage_count": 1,
            "failed_stage_count": 0,
            "unit_gate_passed_count": 0,
            "candidate_kernel_axis_unbound_stage_count": 0,
            "parsed_stage_result_ref_count": 2,
            "parsed_stage_result_refs": [
                {
                    "path": "parsed/cand-a/fft_ifft_ffft/vivado_fpga_synth_or_impl.json",
                    "exists": True,
                    "sha256": "sha256-cand-a-vivado",
                    "hash_algorithm": "sha256",
                },
                {
                    "path": "parsed/cand-b/reduction_tree/dc_asic_synth_timing_area.json",
                    "exists": True,
                    "sha256": "sha256-cand-b-dc",
                    "hash_algorithm": "sha256",
                },
            ],
            "unit_rows": [
                {
                    "unit_id": "cand-a:fft_ifft_ffft",
                    "candidate_id": "cand-a",
                    "kernel_id": "fft_ifft_ffft",
                    "target_platform_kind": "fpga",
                    "candidate_kernel_target_axis_id": "cand-a::fft_ifft_ffft::fpga",
                    "required_stage_ids": list(FPGA_STAGES),
                    "stage_rows": [
                        {
                            "candidate_id": "cand-a",
                            "kernel_id": "fft_ifft_ffft",
                            "stage_id": "vivado_fpga_synth_or_impl",
                            "parsed_result_present": True,
                            "parsed_result_schema_valid": True,
                            "parsed_verdict": "passed",
                            "stage_gate_passed": True,
                            "status": "stage_gate_passed_pending_unit_closure",
                            "blocker_id": None,
                            "parsed_blocker_ids": [],
                            "adjudication_result": "passed_stage_gate",
                            "parsed_result": {
                                "path": "parsed/cand-a/fft_ifft_ffft/vivado_fpga_synth_or_impl.json",
                                "exists": True,
                                "sha256": "sha256-cand-a-vivado",
                                "hash_algorithm": "sha256",
                            },
                            "raw_evidence_ref_count": 1,
                            "hardware_completion_eligible": False,
                            "deliverable_complete": False,
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
                    "required_stage_ids": list(ASIC_STAGES),
                    "stage_rows": [
                        {
                            "candidate_id": "cand-b",
                            "kernel_id": "reduction_tree",
                            "stage_id": "dc_asic_synth_timing_area",
                            "parsed_result_present": True,
                            "parsed_result_schema_valid": True,
                            "parsed_verdict": "blocked",
                            "stage_gate_passed": False,
                            "status": "blocked_parser_reported_blocked_or_unknown",
                            "blocker_id": "parsed_result_blocked_or_unknown",
                            "parsed_blocker_ids": ["parsed_result_blocked_or_unknown"],
                            "adjudication_result": "blocked_stage_gate",
                            "parsed_result": {
                                "path": "parsed/cand-b/reduction_tree/dc_asic_synth_timing_area.json",
                                "exists": True,
                                "sha256": "sha256-cand-b-dc",
                                "hash_algorithm": "sha256",
                            },
                            "raw_evidence_ref_count": 1,
                            "hardware_completion_eligible": False,
                            "deliverable_complete": False,
                        }
                    ],
                    "unit_gate_passed": False,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                },
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    gate_validation_path = _write_json(
        run_dir / "dft_hardware_closure_gate_adjudication_validation.json",
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication_validation.v1",
            "valid": True,
            "unit_count": 2,
            "stage_count": 2,
            "candidate_kernel_axis_count": 2,
            "candidate_kernel_target_axis_count": 2,
            "candidate_kernel_target_axis_counts_by_target": {"asic": 1, "fpga": 1},
            "stage_counts_by_target": {"asic": 1, "fpga": 1},
            "unknown_target_platform_kind_unit_count": 0,
            "unknown_target_platform_kind_stage_count": 0,
            "blocker_id_counts": {"required_tool_unavailable:vivado": 1},
            "candidate_kernel_axis_unbound_stage_count": 0,
            "parsed_stage_result_ref_count": 2,
            "parsed_stage_result_refs": [
                {
                    "path": "parsed/cand-a/fft_ifft_ffft/vivado_fpga_synth_or_impl.json",
                    "exists": True,
                    "sha256": "sha256-cand-a-vivado",
                    "hash_algorithm": "sha256",
                },
                {
                    "path": "parsed/cand-b/reduction_tree/dc_asic_synth_timing_area.json",
                    "exists": True,
                    "sha256": "sha256-cand-b-dc",
                    "hash_algorithm": "sha256",
                },
            ],
            "errors": [],
            "deliverable_complete": False,
        },
    )
    gate_status_path = _write_json(
        run_dir / "dft_hardware_closure_gate_adjudication_status.json",
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication_status.v1",
            "status": "passed",
            "gate_adjudication": str(run_dir / "dft_hardware_closure_gate_adjudication.json"),
            "validation": str(run_dir / "dft_hardware_closure_gate_adjudication_validation.json"),
            "unit_count": 2,
            "stage_count": 2,
            "candidate_kernel_axis_count": 2,
            "candidate_kernel_target_axis_count": 2,
            "candidate_kernel_target_axis_counts_by_target": {"asic": 1, "fpga": 1},
            "stage_counts_by_target": {"asic": 1, "fpga": 1},
            "unknown_target_platform_kind_unit_count": 0,
            "unknown_target_platform_kind_stage_count": 0,
            "blocker_id_counts": {"required_tool_unavailable:vivado": 1},
            "stage_gate_passed_count": 1,
            "blocked_stage_count": 1,
            "failed_stage_count": 0,
            "unit_gate_passed_count": 0,
            "candidate_kernel_axis_unbound_stage_count": 0,
            "parsed_stage_result_ref_count": 2,
            "parsed_stage_result_refs": [
                {
                    "path": "parsed/cand-a/fft_ifft_ffft/vivado_fpga_synth_or_impl.json",
                    "exists": True,
                    "sha256": "sha256-cand-a-vivado",
                    "hash_algorithm": "sha256",
                },
                {
                    "path": "parsed/cand-b/reduction_tree/dc_asic_synth_timing_area.json",
                    "exists": True,
                    "sha256": "sha256-cand-b-dc",
                    "hash_algorithm": "sha256",
                },
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": "hard-gate status is fail-closed only",
        },
    )
    return {
        "ledger": ledger_path,
        "ledger_validation": ledger_validation_path,
        "ledger_status": ledger_status_path,
        "gate": gate_path,
        "gate_validation": gate_validation_path,
        "gate_status": gate_status_path,
    }


def test_done_when_4_6_audit_reports_six_case_release_universe_without_global_completion(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)

    payload = build_complete_dse_done_when_4_6_audit(
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
    )

    assert payload["schema_version"] == COMPLETE_DSE_DONE_WHEN_4_6_AUDIT_SCHEMA
    assert payload["deliverable_complete"] is False
    assert {item["done_when_id"] for item in payload["checklist"]} == {4, 5, 6}

    done4 = _done_when(payload, 4)
    done5 = _done_when(payload, 5)
    done6 = _done_when(payload, 6)
    assert done4["status"] == "proven"
    assert done5["status"] == "partial"
    assert done5["evidence"]["required_strict_scf_class_count"] == 6
    assert done6["status"] == "proven"

    blocker_ids = {blocker["id"] for blocker in done6["blockers"]}
    assert "release_workflow_axis_case_count_mismatch" not in blocker_ids
    assert "predeclared_seed_rows_not_real_search_generation_claim" not in blocker_ids
    assert done6["evidence"]["default_matrix_workflow_case_count"] == 6
    assert done6["evidence"]["workflow_case_ids"] == [
        "release_workflow_case_00",
        "release_workflow_case_01",
        "release_workflow_case_02",
        "release_workflow_case_03",
        "release_workflow_case_04",
        "release_workflow_case_05",
    ]
    assert payload["release_universe_audit"]["current_goal_required_workflow_case_count"] == 6
    assert payload["release_universe_audit"]["default_matrix_workflow_case_count"] == 6
    assert payload["release_universe_audit"]["workflow_axis_blocked"] is False
    assert payload["release_universe_audit"]["deliverable_complete"] is False
    assert "strict_qe_release_lane_bundle_not_supplied_to_audit" in {
        blocker["id"] for blocker in done5["blockers"]
    }

    identity_contract = payload["candidate_identity_contract"]
    assert identity_contract["domain_neutral_core"] is True
    assert "workload_case_id" in identity_contract["non_identity_fields"]
    assert all(
        artifact["exists"] and artifact["sha256"]
        for artifact in done6["source_artifacts"]
        if artifact["label"] == "complete_dse_search_space"
    )
    assert "deliverable completion" in payload["claim_boundary"]


def test_done_when_4_6_audit_records_supplied_strict_six_class_bundle_without_final_qe_claim(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    bundle_dir = tmp_path / "six_class_bundle"
    status = write_dft_scf_six_class_bundle(bundle_dir)
    assert status["case_count"] == 6

    payload = build_complete_dse_done_when_4_6_audit(
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
        strict_qe_release_bundle_manifest_path=bundle_dir / DFT_SCF_SIX_CLASS_MANIFEST_NAME,
    )

    done5 = _done_when(payload, 5)
    done5_blocker_ids = {blocker["id"] for blocker in done5["blockers"]}
    bundle_evidence = done5["evidence"]["strict_qe_release_bundle"]

    assert "strict_qe_release_lane_bundle_not_supplied_to_audit" not in done5_blocker_ids
    assert "strict_qe_release_bundle_not_final_real_qe_evidence" in done5_blocker_ids
    assert bundle_evidence["supplied"] is True
    assert bundle_evidence["case_count"] == 6
    assert bundle_evidence["required_class_ids"] == list(REQUIRED_DFT_SCF_CLASS_IDS)
    assert bundle_evidence["present_class_ids"] == list(REQUIRED_DFT_SCF_CLASS_IDS)
    assert bundle_evidence["admitted"] is False
    assert bundle_evidence["final_real_qe_evidence"] is False
    assert payload["deliverable_complete"] is False


def test_done_when_4_6_cli_writes_report_and_status(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "audit"

    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--out",
            str(out_dir),
            "--goal-path",
            str(goal),
            "--barrier-path",
            str(barrier),
            "--preflight-path",
            str(preflight),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    stdout = json.loads(completed.stdout)
    report_path = out_dir / "complete_dse_done_when_4_6_audit.json"
    status_path = out_dir / "status.json"
    assert stdout["artifact"] == str(report_path)
    assert stdout["deliverable_complete"] is False
    assert report_path.is_file()
    assert status_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["deliverable_complete"] is False
    assert status["status"] == "partial"
    assert "strict_qe_release_lane_bundle_not_supplied_to_audit" in status["blocker_ids"]


def test_done_when_4_6_cli_binds_target_counter_artifacts_fail_closed(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "audit"
    counter_paths = _write_target_counter_artifacts(tmp_path / "target_counter_run")

    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--out",
            str(out_dir),
            "--goal-path",
            str(goal),
            "--barrier-path",
            str(barrier),
            "--preflight-path",
            str(preflight),
            "--target-evidence-ledger",
            str(counter_paths["ledger"]),
            "--target-evidence-ledger-validation",
            str(counter_paths["ledger_validation"]),
            "--target-evidence-ledger-status",
            str(counter_paths["ledger_status"]),
            "--gate-adjudication",
            str(counter_paths["gate"]),
            "--gate-adjudication-validation",
            str(counter_paths["gate_validation"]),
            "--gate-adjudication-status",
            str(counter_paths["gate_status"]),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    stdout = json.loads(completed.stdout)
    report_path = out_dir / "complete_dse_done_when_4_6_audit.json"
    status_path = out_dir / "status.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))
    counter_audit = payload["target_counter_audit"]

    assert stdout["target_counter_audit_status"] == "partial"
    assert status["target_counter_audit_status"] == "partial"
    assert counter_audit["status"] == "partial"
    assert counter_audit["counter_source"] == "producer_output_artifacts"
    assert counter_audit["hard_gate_counter_source"] == "gate_adjudication_artifacts"
    assert counter_audit["ledger_counters"]["candidate_kernel_target_axis_count"] == 2
    assert counter_audit["ledger_counters"]["candidate_kernel_target_axis_counts_by_target"] == {
        "asic": 1,
        "fpga": 1,
    }
    assert counter_audit["ledger_counters"]["stable_blocker_reason_counts"] == {
        "parsed_result_kernel_axis_unbound": 0,
        "required_tool_unavailable:vivado": 1,
    }
    assert counter_audit["ledger_counters"]["unknown_target_platform_kind_row_count"] == 0
    assert counter_audit["ledger_counters"]["claim_upgrade_allowed_count"] == 0
    assert counter_audit["gate_adjudication_counters"]["blocker_id_counts"] == {
        "required_tool_unavailable:vivado": 1,
    }
    assert counter_audit["gate_adjudication_counters"]["stage_counts_by_target"] == {
        "asic": 1,
        "fpga": 1,
    }
    assert counter_audit["artifact_refs"]["target_evidence_gate_ledger"]["exists"] is True
    assert counter_audit["artifact_refs"]["target_evidence_gate_ledger"]["sha256"]
    assert counter_audit["artifact_refs"]["gate_adjudication_status"]["exists"] is True
    assert counter_audit["producer_output_visible"] is True
    assert counter_audit["test_fixture_only_visible"] is False
    assert "required_tool_unavailable:vivado" in counter_audit["blocker_ids"]
    assert payload["deliverable_complete"] is False
    assert counter_audit["hardware_completion_eligible"] is False
    assert counter_audit["deliverable_complete"] is False


def test_release_artifact_package_writes_stable_manifest_hashes_and_fail_closed_status(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "release_package"

    status = done_when_4_6.write_complete_dse_release_artifact_package(
        out_dir,
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
    )

    package_path = out_dir / "complete_dse_release_artifact_package.json"
    hash_manifest_path = out_dir / "complete_dse_release_artifact_hash_manifest.json"
    status_path = out_dir / "status.json"
    matrix_path = out_dir / "candidate_workflow_deployment_target_matrix.json"
    assert status["status"] == "partial"
    assert status["deliverable_complete"] is False
    assert status["artifact_package"] == str(package_path)
    assert status["hash_manifest"] == str(hash_manifest_path)
    assert package_path.is_file()
    assert hash_manifest_path.is_file()
    assert status_path.is_file()
    assert matrix_path.is_file()

    package = json.loads(package_path.read_text(encoding="utf-8"))
    hash_manifest = json.loads(hash_manifest_path.read_text(encoding="utf-8"))
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    artifacts_by_name = {
        artifact["canonical_name"]: artifact for artifact in package["artifacts"]
    }
    hash_by_name = {
        artifact["canonical_name"]: artifact for artifact in hash_manifest["artifacts"]
    }

    assert package["stable_artifact_names"] == [
        "search_space/release_subset_manifest.json",
        "candidate_workflow_deployment_target_matrix.json",
        "audit/complete_dse_done_when_4_6_audit.json",
        "audit/status.json",
        "search_space/candidate_generation_report.json",
        "search_space/freeze_gate_verdict.json",
        "search_space/status.json",
    ]
    assert package["strict_six_class_bundle_linkage"]["supplied"] is False
    assert "strict_qe_release_lane_bundle_not_supplied_to_audit" in package["blocker_ids"]
    assert package["release_universe"]["workflow_case_count"] == 6
    assert matrix["workflow_case_count"] == 6
    assert package["release_universe"]["matrix_hash"] == matrix["matrix_hash"]
    assert package["generated_search_provenance"]["source"] == "bounded_parameterized_release_generator_v1"
    assert package["generated_search_provenance"]["real_search_generation_eligible"] is True
    traceability = package["current_goal_checklist_traceability"]
    trace_refs = traceability["artifact_refs"]
    assert traceability["hash_binding_status"] == "passed"
    assert traceability["status"] == "partial"
    assert traceability["deliverable_complete"] is False
    assert trace_refs["complete_dse_done_when_4_6_audit.json"]["path"] == (
        "audit/complete_dse_done_when_4_6_audit.json"
    )
    assert trace_refs["status.json"]["path"] == "audit/status.json"
    assert trace_refs["release_universe_manifest.json"]["path"] == (
        "search_space/release_subset_manifest.json"
    )
    assert trace_refs["candidate_generation_report.json"]["path"] == (
        "search_space/candidate_generation_report.json"
    )
    assert trace_refs["candidate_workflow_deployment_target_matrix.json"]["path"] == (
        "candidate_workflow_deployment_target_matrix.json"
    )
    assert trace_refs["complete_dse_done_when_4_6_audit.json"]["status"] == "partial"
    assert trace_refs["status.json"]["status"] == "partial"
    assert trace_refs["status.json"]["source_status"] == "partial"
    for alias, source_name in {
        "complete_dse_done_when_4_6_audit.json": "audit/complete_dse_done_when_4_6_audit.json",
        "status.json": "audit/status.json",
        "release_universe_manifest.json": "search_space/release_subset_manifest.json",
        "candidate_generation_report.json": "search_space/candidate_generation_report.json",
        "candidate_workflow_deployment_target_matrix.json": "candidate_workflow_deployment_target_matrix.json",
    }.items():
        ref = trace_refs[alias]
        source_ref = artifacts_by_name[source_name]
        assert ref["source_canonical_name"] == source_name
        assert ref["sha256"] == source_ref["sha256"]
        assert ref["hash_algorithm"] == "sha256"
        assert traceability["artifact_hashes"][alias] == source_ref["sha256"]
        assert not ref["hash_binding_blockers"]
    assert hash_manifest["current_goal_checklist_traceability"]["artifact_refs"] == trace_refs
    assert package["fixed_or_manual_seed_completion_claim_allowed"] is False
    assert package["deliverable_complete"] is False
    assert "completion" in package["claim_boundary"]

    for canonical_name in package["stable_artifact_names"]:
        artifact = artifacts_by_name[canonical_name]
        hash_ref = hash_by_name[canonical_name]
        assert artifact["exists"] is True
        assert artifact["sha256"]
        assert artifact["sha256"] == hash_ref["sha256"]
        assert hash_ref["hash_algorithm"] == "sha256"


def test_release_artifact_package_checklist_traceability_fails_closed_for_missing_hash_ref(tmp_path):
    release_subset = build_release_subset_manifest()
    stable_artifacts = []
    for canonical_name in done_when_4_6.STABLE_RELEASE_PACKAGE_ARTIFACT_NAMES:
        present = canonical_name != "audit/status.json"
        stable_artifacts.append(
            {
                "canonical_name": canonical_name,
                "artifact_role": canonical_name.replace("/", "_").removesuffix(".json"),
                "path": str(tmp_path / canonical_name),
                "required": True,
                "exists": present,
                "status": "present_hash_valid" if present else "missing_required",
                "sha256": "a" * 64 if present else None,
                "hash_algorithm": "sha256",
            }
        )

    package, hash_manifest = done_when_4_6.build_complete_dse_release_artifact_package(
        package_root=tmp_path,
        repo_root=REPO_ROOT,
        control_root=tmp_path,
        search_space_status={"status": "passed"},
        audit_status={"status": "partial"},
        release_subset=release_subset,
        audit_payload={
            "status": "partial",
            "blocker_ids": [],
            "candidate_identity_contract": {},
        },
        stable_artifacts=stable_artifacts,
    )

    traceability = package["current_goal_checklist_traceability"]
    status_ref = traceability["artifact_refs"]["status.json"]
    assert package["status"] == "blocked"
    assert hash_manifest["status"] == "failed"
    assert traceability["status"] == "blocked"
    assert traceability["hash_binding_status"] == "blocked"
    assert status_ref["path"] == "audit/status.json"
    assert status_ref["sha256"] is None
    assert {
        "missing_hash_bound_source_artifact",
        "missing_source_sha256",
    } <= set(status_ref["hash_binding_blockers"])
    assert "status.json:missing_source_sha256" in traceability["hash_binding_blockers"]


def test_release_artifact_package_links_supplied_strict_six_bundle_without_final_claim(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    bundle_dir = tmp_path / "six_class_bundle"
    write_dft_scf_six_class_bundle(bundle_dir)

    status = done_when_4_6.write_complete_dse_release_artifact_package(
        tmp_path / "release_package",
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
        strict_qe_release_bundle_manifest_path=bundle_dir / DFT_SCF_SIX_CLASS_MANIFEST_NAME,
    )

    package = json.loads(Path(status["artifact_package"]).read_text(encoding="utf-8"))
    linkage = package["strict_six_class_bundle_linkage"]
    assert linkage["supplied"] is True
    assert linkage["case_count"] == 6
    assert linkage["present_class_ids"] == list(REQUIRED_DFT_SCF_CLASS_IDS)
    assert linkage["artifact"]["exists"] is True
    assert linkage["artifact"]["sha256"]
    assert linkage["final_real_qe_evidence"] is False
    assert package["status"] == "partial"
    assert package["deliverable_complete"] is False
    assert "strict_qe_release_bundle_not_final_real_qe_evidence" in package["blocker_ids"]


def test_release_artifact_package_exposes_replay_cli_and_candidate_id_audit(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "release_package"

    status = done_when_4_6.write_complete_dse_release_artifact_package(
        out_dir,
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
    )

    package = json.loads(Path(status["artifact_package"]).read_text(encoding="utf-8"))
    hash_manifest = json.loads(Path(status["hash_manifest"]).read_text(encoding="utf-8"))
    release_subset = json.loads(
        (out_dir / "search_space" / "release_subset_manifest.json").read_text(
            encoding="utf-8"
        )
    )

    replay_cli = package["replay_cli"]
    assert replay_cli["entrypoint"] == (
        "dse_v2/scripts/dse/build_complete_dse_release_artifact_package.py"
    )
    assert replay_cli["cwd"] == str(REPO_ROOT)
    assert replay_cli["argv"][:3] == ["python3", replay_cli["entrypoint"], "--out"]
    assert "--repo-root" in replay_cli["argv"]
    assert "--goal-path" in replay_cli["argv"]
    assert replay_cli["command"].startswith("python3 ")
    assert status["replay_cli"] == replay_cli
    assert hash_manifest["replay_cli"] == replay_cli

    candidate_audit = package["deployment_search_candidate_id_audit"]
    assert candidate_audit["status"] == "passed"
    assert candidate_audit["candidate_source"] == (
        "release_subset_manifest.legal_candidate_ids"
    )
    assert candidate_audit["candidate_ids"] == release_subset["legal_candidate_ids"]
    assert candidate_audit["matrix_candidate_ids"] == release_subset["legal_candidate_ids"]
    assert candidate_audit["candidate_ids_recomputed_from_release_universe"] is True
    assert candidate_audit["manual_candidate_id_blockers"] == []
    assert candidate_audit["fixed_or_manual_candidate_completion_claim_allowed"] is False
    assert hash_manifest["deployment_search_candidate_id_audit"] == candidate_audit
    assert status["deployment_search_candidate_id_audit_status"] == "passed"
    assert status["deployment_search_candidate_id_audit_hash"] == candidate_audit["audit_hash"]


def test_release_artifact_package_hash_binds_target_evidence_gate_ledger_source_matrix_ids(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "release_package"
    counter_paths = _write_target_counter_artifacts(tmp_path / "target_counter_run")

    status = done_when_4_6.write_complete_dse_release_artifact_package(
        out_dir,
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
        target_evidence_ledger_path=counter_paths["ledger"],
        target_evidence_ledger_validation_path=counter_paths["ledger_validation"],
        target_evidence_ledger_status_path=counter_paths["ledger_status"],
    )

    package = json.loads(Path(status["artifact_package"]).read_text(encoding="utf-8"))
    hash_manifest = json.loads(Path(status["hash_manifest"]).read_text(encoding="utf-8"))
    linkage = package["target_evidence_gate_ledger_linkage"]

    assert linkage["status"] == "bound"
    assert linkage["artifact_refs"]["target_evidence_gate_ledger"]["exists"] is True
    assert linkage["artifact_refs"]["target_evidence_gate_ledger"]["sha256"]
    assert linkage["source_matrix_ref"]["sha256"] == "sha256-matrix"
    assert linkage["source_matrix_evidence_gate_ids"] == [
        "dc_synthesis_timing_area",
        "vivado_synthesis_or_implementation",
    ]
    assert linkage["source_matrix_to_target_gate_rows"] == [
        {
            "candidate_id": "cand-b",
            "kernel_id": "reduction_tree",
            "workflow_case_id": "qe_full_scf_small",
            "deployment_boundary_id": "full_scf_evaluated_hybrid",
            "target_platform_id": "asic_synopsys_dc_release_v1",
            "target_platform_kind": "asic",
            "source_matrix_evidence_gate_id": "dc_synthesis_timing_area",
            "target_evidence_gate_id": "dc_asic_synth_timing_area",
            "source_matrix_row_id": "matrix::cand-b::asic::dc_synthesis_timing_area",
            "source_matrix_row_hash": "source-row-hash-asic",
        },
        {
            "candidate_id": "cand-a",
            "kernel_id": "fft_ifft_ffft",
            "workflow_case_id": "qe_full_scf_small",
            "deployment_boundary_id": "full_scf_evaluated_hybrid",
            "target_platform_id": "fpga_vivado_release_v1",
            "target_platform_kind": "fpga",
            "source_matrix_evidence_gate_id": "vivado_synthesis_or_implementation",
            "target_evidence_gate_id": "vivado_fpga_synth_or_impl",
            "source_matrix_row_id": "matrix::cand-a::fpga::vivado_synthesis_or_implementation",
            "source_matrix_row_hash": "source-row-hash-fpga",
        },
    ]
    assert hash_manifest["target_evidence_gate_ledger_linkage"] == linkage
    assert status["target_evidence_gate_ledger_linkage_status"] == "bound"
    assert "--target-evidence-ledger-path" in status["replay_cli"]["argv"]
    assert str(counter_paths["ledger"]) in status["replay_cli"]["argv"]
    assert package["deliverable_complete"] is False


def test_release_artifact_package_hash_binds_optional_decision_summary_input(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "release_package"
    decision_summary_path = tmp_path / "dft_deployment_decision_summary.json"
    _write_json(
        decision_summary_path,
        {
            "schema_version": "dse.dft.deployment_decision_summary.v1",
            "status": "deployment_decision_summary_available",
            "deliverable_complete": False,
        },
    )

    status = done_when_4_6.write_complete_dse_release_artifact_package(
        out_dir,
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
        deployment_decision_summary_path=decision_summary_path,
    )

    package = json.loads(Path(status["artifact_package"]).read_text(encoding="utf-8"))
    hash_manifest = json.loads(Path(status["hash_manifest"]).read_text(encoding="utf-8"))
    decision_summary_ref = package["decision_summary_inputs"][
        "deployment_decision_summary"
    ]

    assert decision_summary_ref["exists"] is True
    assert decision_summary_ref["sha256"]
    assert decision_summary_ref["path"] == str(decision_summary_path)
    assert decision_summary_ref["status"] == "deployment_decision_summary_available"
    assert decision_summary_ref["deliverable_complete"] is False
    assert hash_manifest["decision_summary_inputs"] == package["decision_summary_inputs"]
    assert status["decision_summary_input_count"] == 1
    assert status["decision_summary_binding_status"] == "bound_to_supplied_artifact"
    assert status["decision_summary_candidate_id_audit_status"] == "passed"
    assert status["decision_summary_candidate_id_audit_blocker_ids"] == []
    assert "--deployment-decision-summary-path" in status["replay_cli"]["argv"]
    assert str(decision_summary_path) in status["replay_cli"]["argv"]


def test_release_artifact_package_records_unbound_decision_summary_audit(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "release_package"

    status = done_when_4_6.write_complete_dse_release_artifact_package(
        out_dir,
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
    )

    package = json.loads(Path(status["artifact_package"]).read_text(encoding="utf-8"))
    hash_manifest = json.loads(Path(status["hash_manifest"]).read_text(encoding="utf-8"))
    decision_inputs = package["decision_summary_inputs"]
    decision_ref = decision_inputs["deployment_decision_summary"]

    assert decision_inputs["status"] == "unbound"
    assert decision_inputs["binding_status"] == "unbound_no_deployment_decision_summary_artifact"
    assert decision_inputs["blocker_ids"] == ["deployment_decision_summary_not_bound"]
    assert decision_ref["exists"] is False
    assert decision_ref["status"] == "unbound"
    assert hash_manifest["decision_summary_inputs"] == decision_inputs
    assert status["decision_summary_input_status"] == "unbound"
    assert status["decision_summary_input_blocker_ids"] == ["deployment_decision_summary_not_bound"]
    assert status["decision_summary_binding_status"] == (
        "unbound_no_deployment_decision_summary_artifact"
    )
    assert status["decision_summary_candidate_id_audit_status"] == "unbound"
    assert status["decision_summary_candidate_id_audit_blocker_ids"] == [
        "deployment_decision_summary_not_bound"
    ]
    assert status["decision_summary_input_count"] == 0
    assert "deployment_decision_summary_not_bound" in package["blocker_ids"]
    assert "deployment_decision_summary_not_bound" in status["blocker_ids"]
    assert package["deliverable_complete"] is False


def test_release_artifact_package_blocks_candidate_identity_provenance_without_canonical_bundle(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "release_package"

    status = done_when_4_6.write_complete_dse_release_artifact_package(
        out_dir,
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
    )

    package = json.loads(Path(status["artifact_package"]).read_text(encoding="utf-8"))
    hash_manifest = json.loads(Path(status["hash_manifest"]).read_text(encoding="utf-8"))
    provenance = package["release_candidate_identity_provenance"]

    assert provenance["status"] == "blocked"
    assert provenance["trusted_for_release_package_candidate_identity"] is False
    assert provenance["deployment_decision_summary_binding_status"] == (
        "unbound_no_deployment_decision_summary_artifact"
    )
    assert provenance["strict_qe_release_bundle_binding_status"] == (
        "unbound_no_strict_qe_release_bundle_manifest"
    )
    assert provenance["canonical_bundle_bound"] is False
    assert provenance["blocker_ids"] == [
        "deployment_decision_summary_not_bound",
        "strict_qe_release_lane_bundle_not_supplied_to_audit",
    ]
    assert "not FPGA/ASIC PPA evidence" in provenance["claim_boundary"]
    assert hash_manifest["release_candidate_identity_provenance"] == provenance
    assert status["release_candidate_identity_provenance_status"] == "blocked"
    assert status["release_candidate_identity_provenance_blocker_ids"] == [
        "deployment_decision_summary_not_bound",
        "strict_qe_release_lane_bundle_not_supplied_to_audit",
    ]
    assert package["deliverable_complete"] is False


def test_release_artifact_package_blocks_fail_closed_generated_decision_summary(
    tmp_path,
):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "release_package"
    decision_summary_run_dir = tmp_path / "generated_decision_summary"
    generated_status = write_dft_deployment_decision_summary(decision_summary_run_dir)
    decision_summary_path = decision_summary_run_dir / "dft_deployment_decision_summary.json"

    assert generated_status["decision_summary_status"] == "blocked_missing_required_deployment_artifacts"

    status = done_when_4_6.write_complete_dse_release_artifact_package(
        out_dir,
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
        deployment_decision_summary_path=decision_summary_path,
    )

    package = json.loads(Path(status["artifact_package"]).read_text(encoding="utf-8"))
    decision_inputs = package["decision_summary_inputs"]
    candidate_audit = decision_inputs["deployment_decision_summary_candidate_id_audit"]

    assert decision_inputs["status"] == "blocked"
    assert decision_inputs["binding_status"] == "blocked_supplied_summary_fail_closed"
    assert decision_inputs["deployment_decision_summary"]["status"] == (
        "blocked_missing_required_deployment_artifacts"
    )
    assert candidate_audit["status"] == "blocked"
    assert candidate_audit["candidate_ids"] == []
    assert candidate_audit["candidate_ids_bound_to_release_universe"] is False
    assert candidate_audit["blocker_ids"] == [
        "deployment_decision_summary_not_release_usable"
    ]
    assert "deployment_decision_summary_not_release_usable" in package["blocker_ids"]
    assert status["decision_summary_binding_status"] == "blocked_supplied_summary_fail_closed"
    assert status["decision_summary_candidate_id_audit_status"] == "blocked"
    assert status["decision_summary_candidate_id_audit_blocker_ids"] == [
        "deployment_decision_summary_not_release_usable"
    ]
    assert "deployment_decision_summary_not_release_usable" in status["blocker_ids"]
    assert package["deliverable_complete"] is False


def test_release_artifact_package_blocks_manual_decision_summary_candidate_ids(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "release_package"
    decision_summary_path = tmp_path / "dft_deployment_decision_summary.json"
    _write_json(
        decision_summary_path,
        {
            "schema_version": "dse.dft.deployment_decision_summary.v1",
            "status": "deployment_decision_summary_available",
            "selected_candidate_id": "cand-manual-asic",
            "best_current_deployment_recommendation": {
                "recommended_candidate_id": "cand-manual-asic",
                "selected_candidate": {"candidate_id": "cand-manual-asic"},
                "trusted_final_claim": False,
                "deliverable_complete": False,
            },
            "deliverable_complete": False,
        },
    )

    status = done_when_4_6.write_complete_dse_release_artifact_package(
        out_dir,
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
        deployment_decision_summary_path=decision_summary_path,
    )

    package = json.loads(Path(status["artifact_package"]).read_text(encoding="utf-8"))
    hash_manifest = json.loads(Path(status["hash_manifest"]).read_text(encoding="utf-8"))
    decision_inputs = package["decision_summary_inputs"]
    candidate_audit = decision_inputs["deployment_decision_summary_candidate_id_audit"]

    assert decision_inputs["status"] == "blocked"
    assert decision_inputs["binding_status"] == "bound_to_supplied_artifact"
    assert candidate_audit["status"] == "blocked"
    assert candidate_audit["candidate_source"] == "deployment_decision_summary"
    assert candidate_audit["candidate_ids"] == ["cand-manual-asic"]
    assert candidate_audit["candidate_ids_bound_to_release_universe"] is False
    assert candidate_audit["extra_candidate_ids"] == ["cand-manual-asic"]
    assert candidate_audit["missing_candidate_ids"] == []
    assert candidate_audit["blocker_ids"] == [
        "decision_summary_candidate_ids_not_in_release_subset"
    ]
    assert hash_manifest["decision_summary_inputs"] == decision_inputs
    assert status["decision_summary_input_status"] == "blocked"
    assert status["decision_summary_input_blocker_ids"] == [
        "decision_summary_candidate_ids_not_in_release_subset"
    ]
    assert status["decision_summary_binding_status"] == "bound_to_supplied_artifact"
    assert status["decision_summary_candidate_id_audit_status"] == "blocked"
    assert status["decision_summary_candidate_id_audit_blocker_ids"] == [
        "decision_summary_candidate_ids_not_in_release_subset"
    ]
    assert "decision_summary_candidate_ids_not_in_release_subset" in package["blocker_ids"]
    assert "decision_summary_candidate_ids_not_in_release_subset" in status["blocker_ids"]
    assert package["deliverable_complete"] is False


def test_release_artifact_package_blocks_nested_decision_summary_candidate_ids(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "release_package"
    decision_summary_path = tmp_path / "dft_deployment_decision_summary.json"
    _write_json(
        decision_summary_path,
        {
            "schema_version": "dse.dft.deployment_decision_summary.v1",
            "status": "deployment_decision_summary_available",
            "target_assessments": {
                "fpga": {
                    "recommendation_trace": {
                        "shortlisted_candidates": [
                            {"candidate_id": "cand-buried-fpga"}
                        ]
                    }
                }
            },
            "deliverable_complete": False,
        },
    )

    status = done_when_4_6.write_complete_dse_release_artifact_package(
        out_dir,
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
        deployment_decision_summary_path=decision_summary_path,
    )

    package = json.loads(Path(status["artifact_package"]).read_text(encoding="utf-8"))
    candidate_audit = package["decision_summary_inputs"][
        "deployment_decision_summary_candidate_id_audit"
    ]

    assert candidate_audit["status"] == "blocked"
    assert candidate_audit["candidate_ids"] == ["cand-buried-fpga"]
    assert candidate_audit["extra_candidate_ids"] == ["cand-buried-fpga"]
    assert candidate_audit["candidate_id_refs"] == [
        {
            "path": "$.target_assessments.fpga.recommendation_trace.shortlisted_candidates[0].candidate_id",
            "candidate_id": "cand-buried-fpga",
        }
    ]
    assert status["decision_summary_input_status"] == "blocked"
    assert status["decision_summary_input_blocker_ids"] == [
        "decision_summary_candidate_ids_not_in_release_subset"
    ]
    assert status["decision_summary_binding_status"] == "bound_to_supplied_artifact"
    assert status["decision_summary_candidate_id_audit_status"] == "blocked"
    assert status["decision_summary_candidate_id_audit_blocker_ids"] == [
        "decision_summary_candidate_ids_not_in_release_subset"
    ]
    assert "decision_summary_candidate_ids_not_in_release_subset" in package["blocker_ids"]
    assert "decision_summary_candidate_ids_not_in_release_subset" in status["blocker_ids"]
    assert package["deliverable_complete"] is False


def test_release_artifact_package_cli_smoke_writes_status(tmp_path):
    goal, barrier, preflight = _control_files(tmp_path)
    out_dir = tmp_path / "release_package"

    completed = subprocess.run(
        [
            sys.executable,
            str(PACKAGE_CLI),
            "--out",
            str(out_dir),
            "--goal-path",
            str(goal),
            "--barrier-path",
            str(barrier),
            "--preflight-path",
            str(preflight),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    stdout = json.loads(completed.stdout)
    assert stdout["status"] == "partial"
    assert stdout["deliverable_complete"] is False
    assert stdout["artifact_package"].endswith("complete_dse_release_artifact_package.json")
    assert (out_dir / "complete_dse_release_artifact_hash_manifest.json").is_file()
