#!/usr/bin/env python3
"""DFT hardware closure parsed-evidence manifest tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.reference_workloads.dft_hardware_closure_parsed_evidence import (
    DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_MANIFEST_SCHEMA,
    DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA,
    build_dft_hardware_closure_parsed_evidence_manifest,
    validate_dft_hardware_closure_parsed_evidence_manifest,
    write_dft_hardware_closure_parsed_evidence_manifest,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts
from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _adjudication(path: Path) -> Path:
    stages = []
    for stage_id in [
        "golden_correctness",
        "hls_or_rtl_sim",
        "hls_or_rtl_synth",
        "vivado_fpga_synth_or_impl",
        "dc_asic_synth_timing_area",
    ]:
        stages.append(
            {
                "stage_id": stage_id,
                "required_file_count": 1,
                "present_file_count": 0,
                "missing_file_count": 1,
                "missing_files": [f"missing/{stage_id}.json"],
                "candidate_bundle_present": False,
                "parsed_result_present": False,
                "parsed_result_ref": None,
                "status": "blocked_missing_candidate_bundle",
                "adjudication_result": "not_adjudicated",
                "passed": False,
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
            }
        )
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_adjudication.v1",
            "status": "blocked_missing_candidate_bundle_or_stage_evidence",
            "release_id": "release-parsed",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "packet_count": 1,
            "unit_count": 1,
            "stage_count": 5,
            "passed_stage_count": 0,
            "blocked_stage_count": 5,
            "adjudication_result": "not_adjudicated",
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "unit_rows": [
                {
                    "packet_id": "packet-a",
                    "shard_id": "shard-a",
                    "unit_id": "cand-a:fft_ifft_ffft",
                    "candidate_id": "cand-a",
                    "kernel_id": "fft_ifft_ffft",
                    "kernel_name": "FFT / iFFT / fFFT",
                    "stage_rows": stages,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                    "adjudication_result": "not_adjudicated",
                }
            ],
        },
    )


def test_parsed_evidence_manifest_reports_missing_rows_fail_closed(tmp_path: Path) -> None:
    adjudication_path = _adjudication(tmp_path / "dft_hardware_closure_adjudication.json")

    status = write_dft_hardware_closure_parsed_evidence_manifest(
        tmp_path,
        closure_adjudication_path=adjudication_path,
        parsed_root=tmp_path,
    )

    assert status["status"] == "passed"
    manifest = json.loads((tmp_path / "dft_hardware_closure_parsed_evidence_manifest.json").read_text())
    validation = json.loads((tmp_path / "dft_hardware_closure_parsed_evidence_manifest_validation.json").read_text())
    assert manifest["schema_version"] == DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_MANIFEST_SCHEMA
    assert manifest["stage_count"] == 5
    assert manifest["expected_parsed_result_count"] == 5
    assert manifest["present_parsed_result_count"] == 0
    assert manifest["missing_parsed_result_count"] == 5
    assert manifest["adjudication_result"] == "not_adjudicated_by_parsed_manifest"
    assert manifest["hardware_completion_eligible"] is False
    assert validation["valid"] is True


def test_parsed_evidence_manifest_validates_present_parser_output_without_passing_stage(tmp_path: Path) -> None:
    adjudication_path = _adjudication(tmp_path / "dft_hardware_closure_adjudication.json")
    parsed_path = tmp_path / "parsed_hard_gate_results" / "cand-a" / "fft_ifft_ffft" / "golden_correctness_parsed_result.json"
    _write_json(
        parsed_path,
        {
            "schema_version": DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA,
            "candidate_id": "cand-a",
            "kernel_id": "fft_ifft_ffft",
            "stage_id": "golden_correctness",
            "verdict": "passed",
            "parser_id": "unit-test-golden-parser",
            "raw_evidence_refs": [{"path": "raw/golden.log", "sha256": "abc"}],
            "metrics": {"max_abs_error": 0.0},
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    manifest = build_dft_hardware_closure_parsed_evidence_manifest(
        closure_adjudication_path=adjudication_path,
        parsed_root=tmp_path,
    )

    assert manifest["present_parsed_result_count"] == 1
    assert manifest["valid_parsed_result_count"] == 1
    assert manifest["missing_parsed_result_count"] == 4
    assert manifest["parsed_verdict_counts"]["passed"] == 1
    assert manifest["passed_stage_count"] == 0
    assert manifest["adjudication_result"] == "not_adjudicated_by_parsed_manifest"
    row = next(row for row in manifest["parsed_rows"] if row["stage_id"] == "golden_correctness")
    assert row["parsed_result_schema_valid"] is True
    assert row["parsed_verdict"] == "passed"
    assert row["passed"] is False


def test_parsed_evidence_manifest_accepts_parsed_hard_gate_results_as_root_without_double_prefix(tmp_path: Path) -> None:
    adjudication_path = _adjudication(tmp_path / "dft_hardware_closure_adjudication.json")
    parsed_root = tmp_path / "parsed_hard_gate_results"
    _write_json(
        parsed_root / "cand-a" / "fft_ifft_ffft" / "golden_correctness_parsed_result.json",
        {
            "schema_version": DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA,
            "candidate_id": "cand-a",
            "kernel_id": "fft_ifft_ffft",
            "stage_id": "golden_correctness",
            "verdict": "passed",
            "parser_id": "unit-test-golden-parser",
            "raw_evidence_refs": [{"path": "raw/golden.log", "sha256": "abc"}],
            "metrics": {"max_abs_error": 0.0},
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    manifest = build_dft_hardware_closure_parsed_evidence_manifest(
        closure_adjudication_path=adjudication_path,
        parsed_root=parsed_root,
    )

    row = next(row for row in manifest["parsed_rows"] if row["stage_id"] == "golden_correctness")
    assert manifest["present_parsed_result_count"] == 1
    assert row["expected_parsed_result"]["path"] == "cand-a/fft_ifft_ffft/golden_correctness_parsed_result.json"
    assert row["parsed_result_schema_valid"] is True


def test_parsed_evidence_manifest_preserves_blocked_dc_parser_result(tmp_path: Path) -> None:
    adjudication_path = _adjudication(tmp_path / "dft_hardware_closure_adjudication.json")
    parsed_path = (
        tmp_path
        / "parsed_hard_gate_results"
        / "cand-a"
        / "fft_ifft_ffft"
        / "dc_asic_synth_timing_area_parsed_result.json"
    )
    _write_json(
        parsed_path,
        {
            "schema_version": DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA,
            "candidate_id": "cand-a",
            "kernel_id": "fft_ifft_ffft",
            "stage_id": "dc_asic_synth_timing_area",
            "verdict": "blocked",
            "parser_id": "unit-test-dc-parser",
            "blocker_ids": ["dc_area_not_physical"],
            "raw_evidence_refs": [{"path": "raw/dc_area.rpt", "sha256": "abc"}],
            "metrics": {"area": 0.0},
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    manifest = build_dft_hardware_closure_parsed_evidence_manifest(
        closure_adjudication_path=adjudication_path,
        parsed_root=tmp_path,
    )

    assert manifest["present_parsed_result_count"] == 1
    assert manifest["valid_parsed_result_count"] == 1
    assert manifest["parsed_verdict_counts"]["blocked"] == 1
    assert manifest["passed_stage_count"] == 0
    row = next(row for row in manifest["parsed_rows"] if row["stage_id"] == "dc_asic_synth_timing_area")
    assert row["parsed_result_schema_valid"] is True
    assert row["parsed_verdict"] == "blocked"
    assert row["parsed_blocker_ids"] == ["dc_area_not_physical"]
    assert row["passed"] is False


def test_parsed_evidence_manifest_validator_rejects_claim_upgrade(tmp_path: Path) -> None:
    manifest = build_dft_hardware_closure_parsed_evidence_manifest(
        closure_adjudication_path=_adjudication(tmp_path / "dft_hardware_closure_adjudication.json"),
        parsed_root=tmp_path,
    )

    upgraded = json.loads(json.dumps(manifest))
    upgraded["hardware_completion_eligible"] = True
    upgraded["passed_stage_count"] = 1
    upgraded["adjudication_result"] = "passed"
    upgraded["parsed_rows"][0]["passed"] = True
    validation = validate_dft_hardware_closure_parsed_evidence_manifest(upgraded)

    assert validation["valid"] is False
    assert validation["errors"]


def test_parsed_evidence_manifest_cli_step5_and_goal_audit_visibility(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    adjudication_path = _adjudication(run_dir / "dft_hardware_closure_adjudication.json")
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_parsed_evidence_manifest.py",
            "--out",
            str(run_dir),
            "--closure-adjudication",
            str(adjudication_path),
            "--parsed-root",
            str(run_dir),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr

    _write_json(run_dir / "verdict.json", {"run_id": "parsed-step5", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text())
    markdown = (run_dir / paths["final_report_markdown"]).read_text()
    section = report["dft_hardware_closure_parsed_evidence"]
    assert section["present"] is True
    assert section["status"] == "fail_closed_hardware_closure_parsed_evidence_present"
    assert section["expected_parsed_result_count"] == 5
    assert section["present_parsed_result_count"] == 0
    assert section["passed_stage_count"] == 0
    assert section["adjudication_result"] == "not_adjudicated_by_parsed_manifest"
    assert section["hardware_completion_eligible"] is False
    assert campaign_summary["dft_hardware_closure_parsed_evidence_summary"]["present"] is True
    assert "DFT Hardware Closure Parsed Evidence" in markdown

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=run_dir,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    requirements = {item["requirement"]: item["status"] for item in audit["prompt_to_artifact_checklist"]}
    assert requirements["DFT hardware closure parsed-evidence manifest is Step5-visible and fail-closed"] == "passed"
