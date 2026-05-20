#!/usr/bin/env python3
"""DFT hardware closure evidence-intake tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.reference_workloads.dft_hardware_closure_evidence import (
    DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_SCHEMA,
    build_dft_hardware_closure_evidence_intake,
    validate_dft_hardware_closure_evidence_intake,
    write_dft_hardware_closure_evidence_intake,
)
from dse_v2.reference_workloads.dft_hardware_closure_packets import write_dft_hardware_closure_packets
from dse_v2.reporting.final_report import write_step5_report_artifacts
from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _closure_shards(path: Path) -> Path:
    unit = {
        "unit_id": "cand-a:fft_ifft_ffft",
        "candidate_id": "cand-a",
        "kernel_id": "fft_ifft_ffft",
        "kernel_name": "FFT / iFFT / fFFT",
        "kernel_family": "spectral_transform",
        "stage_ids": [
            "golden_correctness",
            "hls_or_rtl_sim",
            "hls_or_rtl_synth",
            "vivado_fpga_synth_or_impl",
            "dc_asic_synth_timing_area",
        ],
        "required_tools": ["dc_shell", "vcs", "vivado"],
        "work_item_ids": [
            "cand-a:fft_ifft_ffft:golden_correctness",
            "cand-a:fft_ifft_ffft:hls_or_rtl_sim",
            "cand-a:fft_ifft_ffft:hls_or_rtl_synth",
            "cand-a:fft_ifft_ffft:vivado_fpga_synth_or_impl",
            "cand-a:fft_ifft_ffft:dc_asic_synth_timing_area",
        ],
        "work_item_count": 5,
        "blocked_work_item_count": 5,
        "candidate_specific_bundle_required": True,
        "candidate_specific_evidence_present": False,
    }
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_shards.v1",
            "status": "queued_fail_closed",
            "release_id": "release-intake",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "unit_count": 1,
            "shard_count": 1,
            "work_item_count": 5,
            "blocked_work_item_count": 5,
            "candidate_specific_bundle_count": 0,
            "candidate_specific_evidence_present_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "shards": [
                {
                    "shard_id": "dft_hardware_closure_shard_0000",
                    "candidate_ids": ["cand-a"],
                    "kernel_ids": ["fft_ifft_ffft"],
                    "required_tools": ["dc_shell", "vcs", "vivado"],
                    "unit_count": 1,
                    "work_item_count": 5,
                    "blocked_work_item_count": 5,
                    "candidate_specific_bundle_count": 0,
                    "units": [unit],
                }
            ],
        },
    )


def _packetized_run(run_dir: Path) -> Path:
    shards_path = _closure_shards(run_dir / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(run_dir, hardware_closure_shards_path=shards_path)
    return run_dir / "dft_hardware_closure_packet_index.json"


def test_evidence_intake_reports_missing_candidate_specific_files_fail_closed(tmp_path: Path) -> None:
    packet_index = _packetized_run(tmp_path / "run")

    status = write_dft_hardware_closure_evidence_intake(
        tmp_path / "run",
        closure_packet_index_path=packet_index,
        evidence_root=tmp_path / "run",
    )

    assert status["status"] == "passed"
    intake = json.loads((tmp_path / "run" / "dft_hardware_closure_evidence_intake.json").read_text())
    validation = json.loads((tmp_path / "run" / "dft_hardware_closure_evidence_intake_validation.json").read_text())
    assert intake["schema_version"] == DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_SCHEMA
    assert intake["status"] == "blocked_missing_candidate_bundle_or_evidence"
    assert intake["packet_count"] == 1
    assert intake["unit_count"] == 1
    assert intake["expected_evidence_file_count"] > 0
    assert intake["present_evidence_file_count"] == 0
    assert intake["missing_evidence_file_count"] == intake["expected_evidence_file_count"]
    assert intake["candidate_bundle_count"] == 0
    assert intake["adjudication_status"] == "not_adjudicated_by_intake"
    assert intake["hardware_completion_eligible"] is False
    assert validation["valid"] is True


def test_evidence_intake_counts_present_files_without_adjudicating(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    packet = json.loads((run_dir / "dft_hardware_closure_packets" / "dft_hardware_closure_shard_0000_packet.json").read_text())
    unit = packet["units"][0]
    _write_json(run_dir / unit["candidate_bundle_json"], {"candidate_id": unit["candidate_id"], "kernel_id": unit["kernel_id"]})
    first_expected = unit["expected_evidence_files"][0]["path"]
    (run_dir / first_expected).parent.mkdir(parents=True, exist_ok=True)
    (run_dir / first_expected).write_text("partial raw evidence\n", encoding="utf-8")

    intake = build_dft_hardware_closure_evidence_intake(
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    assert intake["candidate_bundle_count"] == 1
    assert intake["present_evidence_file_count"] == 1
    assert intake["missing_evidence_file_count"] == intake["expected_evidence_file_count"] - 1
    assert intake["status"] == "blocked_missing_candidate_bundle_or_evidence"
    assert intake["adjudication_status"] == "not_adjudicated_by_intake"
    assert intake["hardware_completion_eligible"] is False


def test_evidence_intake_validator_rejects_claim_upgrade(tmp_path: Path) -> None:
    packet_index = _packetized_run(tmp_path / "run")
    intake = build_dft_hardware_closure_evidence_intake(closure_packet_index_path=packet_index)

    upgraded = json.loads(json.dumps(intake))
    upgraded["hardware_completion_eligible"] = True
    upgraded["packets"][0]["unit_rows"][0]["deliverable_complete"] = True
    upgraded["adjudication_status"] = "passed"
    validation = validate_dft_hardware_closure_evidence_intake(upgraded)

    assert validation["valid"] is False
    assert validation["errors"]


def test_evidence_intake_cli_step5_and_goal_audit_visibility(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    packet_index = _packetized_run(run_dir)
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_evidence_intake.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(packet_index),
            "--evidence-root",
            str(run_dir),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr

    _write_json(run_dir / "verdict.json", {"run_id": "intake-step5", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text())
    markdown = (run_dir / paths["final_report_markdown"]).read_text()
    section = report["dft_hardware_closure_evidence_intake"]
    assert section["present"] is True
    assert section["status"] == "fail_closed_hardware_closure_evidence_intake_present"
    assert section["missing_evidence_file_count"] == section["expected_evidence_file_count"]
    assert section["adjudication_status"] == "not_adjudicated_by_intake"
    assert section["hardware_completion_eligible"] is False
    assert campaign_summary["dft_hardware_closure_evidence_intake_summary"]["present"] is True
    assert "DFT Hardware Closure Evidence Intake" in markdown

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=run_dir,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    requirements = {item["requirement"]: item["status"] for item in audit["prompt_to_artifact_checklist"]}
    assert requirements["DFT hardware closure evidence intake is Step5-visible and fail-closed"] == "passed"
