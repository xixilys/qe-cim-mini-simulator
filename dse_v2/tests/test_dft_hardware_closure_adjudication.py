#!/usr/bin/env python3
"""DFT hardware closure adjudication scaffold tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.reference_workloads.dft_hardware_closure_adjudication import (
    DFT_HARDWARE_CLOSURE_ADJUDICATION_SCHEMA,
    build_dft_hardware_closure_adjudication,
    validate_dft_hardware_closure_adjudication,
    write_dft_hardware_closure_adjudication,
)
from dse_v2.reference_workloads.dft_hardware_closure_evidence import write_dft_hardware_closure_evidence_intake
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
            "release_id": "release-adjudication",
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


def _intake_run(run_dir: Path) -> Path:
    shards_path = _closure_shards(run_dir / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(run_dir, hardware_closure_shards_path=shards_path)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=run_dir / "dft_hardware_closure_packet_index.json",
        evidence_root=run_dir,
    )
    return run_dir / "dft_hardware_closure_evidence_intake.json"


def test_closure_adjudication_builds_required_stage_rows_fail_closed(tmp_path: Path) -> None:
    intake_path = _intake_run(tmp_path / "run")

    status = write_dft_hardware_closure_adjudication(
        tmp_path / "run",
        closure_evidence_intake_path=intake_path,
    )

    assert status["status"] == "passed"
    adjudication = json.loads((tmp_path / "run" / "dft_hardware_closure_adjudication.json").read_text())
    validation = json.loads((tmp_path / "run" / "dft_hardware_closure_adjudication_validation.json").read_text())
    assert adjudication["schema_version"] == DFT_HARDWARE_CLOSURE_ADJUDICATION_SCHEMA
    assert adjudication["unit_count"] == 1
    assert adjudication["stage_count"] == 5
    assert adjudication["passed_stage_count"] == 0
    assert adjudication["blocked_stage_count"] == 5
    assert adjudication["adjudication_result"] == "not_adjudicated"
    assert adjudication["hardware_completion_eligible"] is False
    assert validation["valid"] is True
    stage_ids = {row["stage_id"] for row in adjudication["unit_rows"][0]["stage_rows"]}
    assert stage_ids == {
        "golden_correctness",
        "hls_or_rtl_sim",
        "hls_or_rtl_synth",
        "vivado_fpga_synth_or_impl",
        "dc_asic_synth_timing_area",
    }


def test_closure_adjudication_validator_rejects_claim_upgrade(tmp_path: Path) -> None:
    intake_path = _intake_run(tmp_path / "run")
    payload = build_dft_hardware_closure_adjudication(closure_evidence_intake_path=intake_path)

    upgraded = json.loads(json.dumps(payload))
    upgraded["hardware_completion_eligible"] = True
    upgraded["passed_stage_count"] = 1
    upgraded["adjudication_result"] = "passed"
    upgraded["unit_rows"][0]["stage_rows"][0]["passed"] = True
    upgraded["unit_rows"][0]["stage_rows"][0]["parsed_result_present"] = True
    validation = validate_dft_hardware_closure_adjudication(upgraded)

    assert validation["valid"] is False
    assert validation["errors"]


def test_closure_adjudication_cli_step5_and_goal_audit_visibility(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    intake_path = _intake_run(run_dir)
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_adjudication.py",
            "--out",
            str(run_dir),
            "--closure-evidence-intake",
            str(intake_path),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr

    _write_json(run_dir / "verdict.json", {"run_id": "adjudication-step5", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text())
    markdown = (run_dir / paths["final_report_markdown"]).read_text()
    section = report["dft_hardware_closure_adjudication"]
    assert section["present"] is True
    assert section["status"] == "fail_closed_hardware_closure_adjudication_present"
    assert section["stage_count"] == 5
    assert section["passed_stage_count"] == 0
    assert section["adjudication_result"] == "not_adjudicated"
    assert section["hardware_completion_eligible"] is False
    assert campaign_summary["dft_hardware_closure_adjudication_summary"]["present"] is True
    assert "DFT Hardware Closure Adjudication" in markdown

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=run_dir,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    requirements = {item["requirement"]: item["status"] for item in audit["prompt_to_artifact_checklist"]}
    assert requirements["DFT hardware closure adjudication ledger is Step5-visible and fail-closed"] == "passed"
