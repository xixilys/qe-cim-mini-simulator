#!/usr/bin/env python3
"""Aggregate DFT hardware closure Step5 sequence runner tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_hardware_closure_packets import write_dft_hardware_closure_packets
from dse_v2.reference_workloads.dft_hardware_closure_shards import write_dft_hardware_closure_shard_queue

STAGES = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)
CANDIDATE_ID = "cand-a"
KERNEL_IDS = ("fft_ifft_ffft", "transpose_layout_conversion")


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _workplan(path: Path) -> Path:
    work_items = []
    for kernel_id in KERNEL_IDS:
        for stage_id in STAGES:
            work_items.append(
                {
                    "work_item_id": f"{CANDIDATE_ID}:{kernel_id}:{stage_id}",
                    "candidate_id": CANDIDATE_ID,
                    "kernel_id": kernel_id,
                    "kernel_name": kernel_id.replace("_", " "),
                    "kernel_family": "step5_sequence_test",
                    "stage_id": stage_id,
                    "tool_id": "python3" if stage_id == "golden_correctness" else "real_tool",
                    "blocked": True,
                    "shared_microkernel_smoke_stage_passed": False,
                    "candidate_specific_evidence_present": False,
                }
            )
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_completion_workplan.v1",
            "status": "blocked_step5_sequence_test",
            "release_id": "release-step5-sequence-test",
            "candidate_count": 1,
            "major_kernel_count": len(KERNEL_IDS),
            "work_items": work_items,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )


def _packetized_run(run_dir: Path) -> Path:
    workplan_path = _workplan(run_dir / "dft_hardware_completion_workplan.json")
    write_dft_hardware_closure_shard_queue(
        run_dir,
        hardware_completion_workplan_path=workplan_path,
        max_units_per_shard=1,
    )
    write_dft_hardware_closure_packets(
        run_dir,
        hardware_closure_shards_path=run_dir / "dft_hardware_closure_shards.json",
    )
    return run_dir / "dft_hardware_closure_packet_index.json"


def _source_flow(path: Path, *, full_matrix: bool, candidate_id: str, kernel_id: str) -> Path:
    _write_json(
        path / "golden_correctness.json",
        {
            "schema_version": "dse.dft.kernel_golden_correctness.v1",
            "status": "passed",
            "inputs": {"fixture": path.name},
            "expected": {"stable": True},
            "max_abs_error": 0.0,
        },
    )
    _write_json(
        path / "manifest.json",
        {
            "fixture": path.name,
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "schema_version": f"dse.dft_scf.{kernel_id}.rtl_flow.v1",
        },
    )
    if not full_matrix:
        return path

    _write_text(path / "vcs_compile.log", "compile PASS\n")
    _write_text(path / "vcs_run.log", "RTL_PASS\n")
    _write_text(path / "vivado_stdout.log", "synth_design completed successfully\nroute_design complete\nTIMING MET\n")
    _write_text(path / "vivado_stderr.log", "")
    _write_text(path / "vivado_timing_summary.rpt", "WNS 0.125\nTIMING MET\n")
    _write_text(path / "vivado_utilization.rpt", "LUT 42\nFF 64\n")
    _write_text(path / "dc_stdout.log", "Loading link library 'fsa0a_c_generic_core_tt'\nslack (MET) 0.07\ntotal cell area: 123.4\n")
    _write_text(path / "dc_stderr.log", "")
    _write_text(path / "dc_timing.rpt", "Library: fsa0a_c_generic_core_tt\nslack (MET) 0.07\n")
    _write_text(path / "dc_area.rpt", "total cell area: 123.4\n")
    _write_text(path / "dc_synth.ddc", "binary-ddc-placeholder-for-test\n")
    return path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_step5_sequence_preserves_units_uses_parsed_root_and_fails_closed_on_partial_matrix(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    evidence_root = tmp_path / "evidence-root"
    parsed_root = tmp_path / "parsed-results"
    packet_index = _packetized_run(run_dir)
    full_flow = _source_flow(
        tmp_path / "flows" / "full_fft",
        full_matrix=True,
        candidate_id=CANDIDATE_ID,
        kernel_id=KERNEL_IDS[0],
    )
    partial_flow = _source_flow(
        tmp_path / "flows" / "partial_transpose",
        full_matrix=False,
        candidate_id=CANDIDATE_ID,
        kernel_id=KERNEL_IDS[1],
    )
    source_flow_map = _write_json(
        tmp_path / "source_flow_map.json",
        {
            "flows": [
                {"candidate_id": CANDIDATE_ID, "kernel_id": KERNEL_IDS[0], "source_flow_dir": str(full_flow)},
                {"candidate_id": CANDIDATE_ID, "kernel_id": KERNEL_IDS[1], "source_flow_dir": str(partial_flow)},
            ]
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_dft_hardware_closure_step5_sequence.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(packet_index),
            "--evidence-root",
            str(evidence_root),
            "--parsed-root",
            str(parsed_root),
            "--source-flow-map",
            str(source_flow_map),
            "--candidate-id",
            CANDIDATE_ID,
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    summary = _load(run_dir / "dft_hardware_closure_step5_sequence_status.json")
    assert summary["release_gate_result"] == "blocked_incomplete_hardware_release_gate"
    assert summary["hardware_completion_eligible"] is False

    assert (evidence_root / "candidate_specific_bundles" / CANDIDATE_ID / KERNEL_IDS[0] / "candidate_bundle.json").exists()
    assert _load(run_dir / "dft_hardware_closure_candidate_bundle_index.json")["bundle_count"] == len(KERNEL_IDS)
    assert _load(run_dir / "dft_hardware_closure_unit_provenance_index.json")["staged_unit_count"] == len(KERNEL_IDS)

    materialization = _load(run_dir / "dft_hardware_closure_raw_stage_materialization.json")
    assert materialization["evidence_root"] == str(evidence_root)
    assert materialization["unit_count"] == len(KERNEL_IDS)
    assert {row["kernel_id"] for row in materialization["units"]} == set(KERNEL_IDS)
    assert materialization["materialized_unit_count"] == len(KERNEL_IDS)

    eligible_packet_index = _load(run_dir / "dft_hardware_closure_materialization_eligible_packet_index.json")
    assert eligible_packet_index["unit_count"] == len(KERNEL_IDS)
    eligible_packet_status = _load(run_dir / "dft_hardware_closure_materialization_eligible_packet_index_status.json")
    assert eligible_packet_status["materialization_eligible_unit_count"] == len(KERNEL_IDS)
    assert eligible_packet_status["skipped_ineligible_unit_count"] == 0

    registration = _load(run_dir / "dft_hardware_closure_raw_transcript_registration.json")
    assert registration["unit_count"] == len(KERNEL_IDS)
    assert {row["kernel_id"] for row in registration["units"]} == set(KERNEL_IDS)

    intake = _load(run_dir / "dft_hardware_closure_evidence_intake.json")
    assert intake["unit_count"] == len(KERNEL_IDS)
    assert sum(packet["unit_count"] for packet in intake["packets"]) == len(KERNEL_IDS)

    parser_run = _load(run_dir / "dft_hardware_closure_parser_run.json")
    assert parser_run["parsed_root"] == str(parsed_root)
    assert parser_run["unit_count"] == len(KERNEL_IDS)
    assert parser_run["stage_count"] == len(KERNEL_IDS) * len(STAGES)
    assert parser_run["parsed_result_written_count"] == len(STAGES) + 1
    assert (parsed_root / "parsed_hard_gate_results" / CANDIDATE_ID / KERNEL_IDS[0] / "dc_asic_synth_timing_area_parsed_result.json").exists()
    assert (parsed_root / "parsed_hard_gate_results" / CANDIDATE_ID / KERNEL_IDS[1] / "golden_correctness_parsed_result.json").exists()

    adjudication = _load(run_dir / "dft_hardware_closure_adjudication.json")
    assert adjudication["unit_count"] == len(KERNEL_IDS)

    parsed_manifest = _load(run_dir / "dft_hardware_closure_parsed_evidence_manifest.json")
    assert parsed_manifest["parsed_root"] == str(parsed_root)
    assert parsed_manifest["stage_count"] == len(KERNEL_IDS) * len(STAGES)
    assert parsed_manifest["present_parsed_result_count"] == len(STAGES) + 1
    assert parsed_manifest["missing_parsed_result_count"] == len(STAGES) - 1

    gate = _load(run_dir / "dft_hardware_closure_gate_adjudication.json")
    assert gate["unit_count"] == len(KERNEL_IDS)
    assert gate["unit_gate_passed_count"] == 1
    assert gate["blocked_unit_count"] == 1

    release = _load(run_dir / "dft_hardware_closure_release_gate.json")
    assert release["unit_count"] == len(KERNEL_IDS)
    assert release["unit_gate_passed_count"] == 1
    assert release["blocked_unit_count"] == 1
    assert release["candidate_gate_passed_count"] == 0
    assert release["release_gate_result"] == "blocked_incomplete_hardware_release_gate"
    assert release["hardware_completion_eligible"] is False
    assert release["deliverable_complete"] is False

    report = _load(run_dir / "final_report.json")
    assert report["dft_hardware_closure_source_flow_plan"]["present"] is True
    assert report["dft_hardware_closure_source_flow_plan"]["unit_count"] == len(KERNEL_IDS)
    assert report["dft_hardware_closure_source_flow_plan"]["source_flow_present_count"] == len(KERNEL_IDS)
    assert report["dft_hardware_closure_source_flow_plan"]["materialization_eligible_unit_count"] == len(KERNEL_IDS)
    assert report["dft_hardware_closure_source_flow_plan"]["source_flow_map"]["exists"] is True
    assert report["dft_hardware_closure_source_flow_plan"]["blocker_id_counts"] == {}
    assert report["dft_hardware_closure_release_gate"]["present"] is True
    assert report["dft_hardware_closure_release_gate"]["unit_count"] == len(KERNEL_IDS)
    assert report["dft_hardware_closure_release_gate"]["hardware_completion_eligible"] is False
    assert report["dft_hardware_closure_raw_stage_materialization"]["unit_ref_count"] == len(KERNEL_IDS)


def test_step5_sequence_fails_on_source_flow_entry_without_matching_unit(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    packet_index = _packetized_run(run_dir)
    source_flow = _source_flow(
        tmp_path / "flows" / "orphan",
        full_matrix=True,
        candidate_id="not-a-candidate",
        kernel_id="not-a-kernel",
    )
    source_flow_map = _write_json(
        tmp_path / "source_flow_map.json",
        {
            "flows": [
                {"candidate_id": "not-a-candidate", "kernel_id": "not-a-kernel", "source_flow_dir": str(source_flow)}
            ]
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_dft_hardware_closure_step5_sequence.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(packet_index),
            "--source-flow-map",
            str(source_flow_map),
            "--quiet",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 1
    summary = _load(run_dir / "dft_hardware_closure_step5_sequence_status.json")
    assert summary["status"] == "failed"
    assert "source_flow_plan" in summary["failed_stage_keys"]
    assert "raw_stage_materialization" in summary["failed_stage_keys"]
    assert "materialization_eligible_packet_index" in summary["failed_stage_keys"]
    assert summary["source_flow_plan_blockers"]["materialization_eligible_unit_count"] == 0
    assert summary["source_flow_plan_blockers"]["error_count"] == 1
    source_flow_plan = _load(run_dir / "dft_hardware_closure_source_flow_plan.json")
    assert source_flow_plan["errors"][0]["status"] == "failed_no_matching_units"
    materialization = _load(run_dir / "dft_hardware_closure_raw_stage_materialization.json")
    assert materialization["status"] == "failed_no_matching_units"
    eligible_packet_index = _load(run_dir / "dft_hardware_closure_materialization_eligible_packet_index.json")
    assert eligible_packet_index["unit_count"] == 0
    report = _load(run_dir / "final_report.json")
    assert report["dft_hardware_closure_source_flow_plan"]["error_count"] == 1
    assert report["dft_hardware_closure_source_flow_plan"]["blocker_id_counts"] == {"missing_source_flow": len(KERNEL_IDS)}


def test_step5_sequence_blocks_wrong_candidate_source_flow_before_registration_and_parser(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    evidence_root = tmp_path / "evidence-root"
    parsed_root = tmp_path / "parsed-results"
    packet_index = _packetized_run(run_dir)
    valid_flow = _source_flow(
        tmp_path / "flows" / "valid_fft",
        full_matrix=True,
        candidate_id=CANDIDATE_ID,
        kernel_id=KERNEL_IDS[0],
    )
    wrong_candidate_flow = _source_flow(
        tmp_path / "flows" / "wrong_candidate_transpose",
        full_matrix=True,
        candidate_id="wrong-candidate",
        kernel_id=KERNEL_IDS[1],
    )
    source_flow_map = _write_json(
        tmp_path / "source_flow_map.json",
        {
            "flows": [
                {"candidate_id": CANDIDATE_ID, "kernel_id": KERNEL_IDS[0], "source_flow_dir": str(valid_flow)},
                {
                    "candidate_id": CANDIDATE_ID,
                    "kernel_id": KERNEL_IDS[1],
                    "source_flow_dir": str(wrong_candidate_flow),
                },
            ]
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_dft_hardware_closure_step5_sequence.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(packet_index),
            "--evidence-root",
            str(evidence_root),
            "--parsed-root",
            str(parsed_root),
            "--source-flow-map",
            str(source_flow_map),
            "--quiet",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    source_flow_plan = _load(run_dir / "dft_hardware_closure_source_flow_plan.json")
    wrong_row = next(row for row in source_flow_plan["units"] if row["kernel_id"] == KERNEL_IDS[1])
    assert wrong_row["status"] == "blocked_wrong_candidate_source_flow"
    assert wrong_row["materialization_eligible"] is False
    assert wrong_row["blocker_ids"] == ["source_flow_candidate_id_mismatch"]

    materialization = _load(run_dir / "dft_hardware_closure_raw_stage_materialization.json")
    assert materialization["unit_count"] == 1
    assert materialization["units"][0]["kernel_id"] == KERNEL_IDS[0]

    eligible_packet_index = _load(run_dir / "dft_hardware_closure_materialization_eligible_packet_index.json")
    assert eligible_packet_index["unit_count"] == 1
    assert eligible_packet_index["packets"][0]["kernel_ids"] == [KERNEL_IDS[0]]
    registration = _load(run_dir / "dft_hardware_closure_raw_transcript_registration.json")
    assert registration["unit_count"] == 1
    assert registration["units"][0]["kernel_id"] == KERNEL_IDS[0]
    parser_run = _load(run_dir / "dft_hardware_closure_parser_run.json")
    assert parser_run["unit_count"] == 1
    assert {row["kernel_id"] for row in parser_run["parser_rows"]} == {KERNEL_IDS[0]}
    assert not (parsed_root / "parsed_hard_gate_results" / CANDIDATE_ID / KERNEL_IDS[1]).exists()

    report = _load(run_dir / "final_report.json")
    source_flow_report = report["dft_hardware_closure_source_flow_plan"]
    assert source_flow_report["materialization_eligible_unit_count"] == 1
    assert source_flow_report["blocked_wrong_candidate_reuse_count"] == 1
    assert source_flow_report["blocker_id_counts"] == {"source_flow_candidate_id_mismatch": 1}
    assert source_flow_report["hardware_completion_eligible"] is False
    assert source_flow_report["deliverable_complete"] is False

    audit_path = run_dir / "audit.json"
    audit = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/audit_dft_scf_hardware_dse_goal_completion.py",
            "--run-dir",
            str(run_dir),
            "--out",
            str(audit_path),
            "--allow-in-progress",
            "--quiet",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert audit.returncode == 0, audit.stderr
    audit_payload = _load(audit_path)
    assert audit_payload["status"] in {"blocked", "in_progress"}
    source_flow_items = [
        item
        for item in audit_payload["prompt_to_artifact_checklist"]
        if item["requirement"] == "DFT hardware closure source-flow plan is Step5-visible and fail-closed"
    ]
    assert source_flow_items
    assert source_flow_items[0]["evidence"]["blocker_id_counts"] == {"source_flow_candidate_id_mismatch": 1}


def test_step5_sequence_max_units_limits_prevalidated_materialization_entries(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    evidence_root = tmp_path / "evidence-root"
    parsed_root = tmp_path / "parsed-results"
    packet_index = _packetized_run(run_dir)
    flows = [
        _source_flow(
            tmp_path / "flows" / kernel_id,
            full_matrix=True,
            candidate_id=CANDIDATE_ID,
            kernel_id=kernel_id,
        )
        for kernel_id in KERNEL_IDS
    ]
    source_flow_map = _write_json(
        tmp_path / "source_flow_map.json",
        {
            "flows": [
                {"candidate_id": CANDIDATE_ID, "kernel_id": kernel_id, "source_flow_dir": str(flow)}
                for kernel_id, flow in zip(KERNEL_IDS, flows)
            ]
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_dft_hardware_closure_step5_sequence.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(packet_index),
            "--evidence-root",
            str(evidence_root),
            "--parsed-root",
            str(parsed_root),
            "--source-flow-map",
            str(source_flow_map),
            "--max-units",
            "1",
            "--quiet",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    source_flow_plan = _load(run_dir / "dft_hardware_closure_source_flow_plan.json")
    assert source_flow_plan["source_flow_present_count"] == len(KERNEL_IDS)

    materialization = _load(run_dir / "dft_hardware_closure_raw_stage_materialization.json")
    assert materialization["unit_count"] == 1
    selected_kernel_id = materialization["units"][0]["kernel_id"]

    eligible_packet_index = _load(run_dir / "dft_hardware_closure_materialization_eligible_packet_index.json")
    assert eligible_packet_index["unit_count"] == 1
    assert eligible_packet_index["packets"][0]["kernel_ids"] == [selected_kernel_id]
    eligible_packet_status = _load(run_dir / "dft_hardware_closure_materialization_eligible_packet_index_status.json")
    assert eligible_packet_status["materialization_eligible_unit_count"] == 1
    assert eligible_packet_status["skipped_ineligible_unit_count"] == len(KERNEL_IDS) - 1

    registration = _load(run_dir / "dft_hardware_closure_raw_transcript_registration.json")
    assert registration["unit_count"] == 1
    parser_run = _load(run_dir / "dft_hardware_closure_parser_run.json")
    assert parser_run["unit_count"] == 1
    assert {row["kernel_id"] for row in parser_run["parser_rows"]} == {selected_kernel_id}


def test_step5_sequence_preserves_existing_relative_source_flow_paths(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    packet_index = _packetized_run(run_dir)
    source_flow = _source_flow(
        tmp_path / "flows" / "full_fft",
        full_matrix=True,
        candidate_id=CANDIDATE_ID,
        kernel_id=KERNEL_IDS[0],
    )
    relative_source_flow = Path(os.path.relpath(source_flow, Path.cwd()))
    source_flow_map = _write_json(
        run_dir / "maps" / "source_flow_map.json",
        {
            "flows": [
                {"candidate_id": CANDIDATE_ID, "kernel_id": KERNEL_IDS[0], "source_flow_dir": str(relative_source_flow)}
            ]
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_dft_hardware_closure_step5_sequence.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(packet_index),
            "--source-flow-map",
            str(source_flow_map),
            "--candidate-id",
            CANDIDATE_ID,
            "--kernel-id",
            KERNEL_IDS[0],
            "--quiet",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    materialization = _load(run_dir / "dft_hardware_closure_raw_stage_materialization.json")
    assert materialization["unit_count"] == 1
    assert materialization["units"][0]["source_flow_dir"] == str(relative_source_flow)
    assert materialization["materialized_unit_count"] == 1
