#!/usr/bin/env python3
"""DFT hard-gate adjudication tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.reference_workloads.dft_hardware_closure_gate_adjudication import (
    DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_SCHEMA,
    build_dft_hardware_closure_gate_adjudication,
    validate_dft_hardware_closure_gate_adjudication,
    write_dft_hardware_closure_gate_adjudication,
)
from dse_v2.reference_workloads.dft_hardware_closure_parsed_evidence import (
    DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA,
    write_dft_hardware_closure_parsed_evidence_manifest,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts
from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)


STAGES = [
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
]


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _safe_slug(value: str) -> str:
    return value.strip().lower().replace("/", "_").replace(" ", "_")


def _adjudication(path: Path) -> Path:
    stages = []
    for stage_id in STAGES:
        stages.append(
            {
                "stage_id": stage_id,
                "claim_role": f"{stage_id}_gate",
                "required_file_count": 1,
                "present_file_count": 1,
                "missing_file_count": 0,
                "missing_files": [],
                "candidate_bundle_present": True,
                "parsed_result_present": False,
                "parsed_result_ref": None,
                "status": "files_present_waiting_for_parsed_adjudication",
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
            "status": "files_present_waiting_for_parsed_adjudication",
            "release_id": "release-gate",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "packet_count": 1,
            "unit_count": 1,
            "stage_count": len(STAGES),
            "passed_stage_count": 0,
            "blocked_stage_count": 0,
            "files_present_unadjudicated_stage_count": len(STAGES),
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
                    "stage_count": len(STAGES),
                    "passed_stage_count": 0,
                    "blocked_stage_count": 0,
                    "files_present_unadjudicated_stage_count": len(STAGES),
                    "expected_evidence_file_count": len(STAGES),
                    "present_evidence_file_count": len(STAGES),
                    "missing_evidence_file_count": 0,
                    "candidate_bundle_present": True,
                    "status": "files_present_waiting_for_parsed_adjudication",
                    "adjudication_result": "not_adjudicated",
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                    "stage_rows": stages,
                }
            ],
        },
    )


def _write_manifest(run_dir: Path) -> Path:
    write_dft_hardware_closure_parsed_evidence_manifest(
        run_dir,
        closure_adjudication_path=_adjudication(run_dir / "dft_hardware_closure_adjudication.json"),
        parsed_root=run_dir,
    )
    return run_dir / "dft_hardware_closure_parsed_evidence_manifest.json"


def _write_parsed_result(run_dir: Path, stage_id: str, verdict: str = "passed") -> Path:
    parsed_path = (
        run_dir
        / "parsed_hard_gate_results"
        / _safe_slug("cand-a")
        / _safe_slug("fft_ifft_ffft")
        / f"{_safe_slug(stage_id)}_parsed_result.json"
    )
    return _write_json(
        parsed_path,
        {
            "schema_version": DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA,
            "candidate_id": "cand-a",
            "kernel_id": "fft_ifft_ffft",
            "stage_id": stage_id,
            "verdict": verdict,
            "parser_id": f"unit-test-{stage_id}-parser",
            "raw_evidence_refs": [{"path": f"raw/{stage_id}.log", "sha256": "abc", "hash_algorithm": "sha256"}],
            "metrics": {},
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )


def test_gate_adjudication_blocks_missing_parsed_results_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    manifest_path = _write_manifest(run_dir)

    status = write_dft_hardware_closure_gate_adjudication(
        run_dir,
        parsed_evidence_manifest_path=manifest_path,
    )

    assert status["status"] == "passed"
    adjudication = json.loads((run_dir / "dft_hardware_closure_gate_adjudication.json").read_text())
    validation = json.loads((run_dir / "dft_hardware_closure_gate_adjudication_validation.json").read_text())
    assert adjudication["schema_version"] == DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_SCHEMA
    assert adjudication["status"] == "blocked_incomplete_hard_gate_evidence"
    assert adjudication["stage_count"] == len(STAGES)
    assert adjudication["stage_gate_passed_count"] == 0
    assert adjudication["blocked_stage_count"] == len(STAGES)
    assert adjudication["unit_gate_passed_count"] == 0
    assert adjudication["hardware_completion_eligible"] is False
    assert adjudication["deliverable_complete"] is False
    assert {row["status"] for row in adjudication["unit_rows"][0]["stage_rows"]} == {"blocked_missing_parsed_result"}
    assert validation["valid"] is True


def test_gate_adjudication_can_pass_one_stage_without_release_completion(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_parsed_result(run_dir, "golden_correctness", verdict="passed")
    manifest_path = _write_manifest(run_dir)

    adjudication = build_dft_hardware_closure_gate_adjudication(
        parsed_evidence_manifest_path=manifest_path,
    )

    assert adjudication["status"] == "blocked_incomplete_hard_gate_evidence"
    assert adjudication["stage_gate_passed_count"] == 1
    assert adjudication["blocked_stage_count"] == len(STAGES) - 1
    assert adjudication["unit_gate_passed_count"] == 0
    assert adjudication["hardware_completion_eligible"] is False
    assert adjudication["deliverable_complete"] is False
    stage = next(row for row in adjudication["unit_rows"][0]["stage_rows"] if row["stage_id"] == "golden_correctness")
    assert stage["stage_gate_passed"] is True
    assert stage["adjudication_result"] == "passed_stage_gate"
    assert stage["hardware_completion_eligible"] is False
    assert stage["deliverable_complete"] is False


def test_gate_adjudication_keeps_blocked_parser_verdict_blocked(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_parsed_result(run_dir, "dc_asic_synth_timing_area", verdict="blocked")
    manifest_path = _write_manifest(run_dir)

    adjudication = build_dft_hardware_closure_gate_adjudication(
        parsed_evidence_manifest_path=manifest_path,
    )

    dc_stage = next(
        row
        for row in adjudication["unit_rows"][0]["stage_rows"]
        if row["stage_id"] == "dc_asic_synth_timing_area"
    )
    assert dc_stage["parsed_verdict"] == "blocked"
    assert dc_stage["stage_gate_passed"] is False
    assert dc_stage["status"] == "blocked_parser_reported_blocked_or_unknown"
    assert dc_stage["blocker_id"] == "parsed_result_blocked_or_unknown"
    assert dc_stage["adjudication_result"] == "blocked_stage_gate"
    assert adjudication["unit_gate_passed_count"] == 0
    assert adjudication["hardware_completion_eligible"] is False
    assert adjudication["deliverable_complete"] is False


def test_gate_adjudication_all_stages_pass_but_still_no_deliverable_completion(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    for stage_id in STAGES:
        _write_parsed_result(run_dir, stage_id, verdict="passed")
    manifest_path = _write_manifest(run_dir)

    adjudication = build_dft_hardware_closure_gate_adjudication(
        parsed_evidence_manifest_path=manifest_path,
    )

    assert adjudication["status"] == "all_unit_stage_gates_passed_pending_release_claim"
    assert adjudication["adjudication_result"] == "all_stage_gates_passed_pending_release_claim"
    assert adjudication["stage_gate_passed_count"] == len(STAGES)
    assert adjudication["unit_gate_passed_count"] == 1
    assert adjudication["hardware_completion_eligible"] is False
    assert adjudication["deliverable_complete"] is False
    unit = adjudication["unit_rows"][0]
    assert unit["unit_gate_passed"] is True
    assert unit["hardware_completion_eligible"] is False
    assert unit["deliverable_complete"] is False


def test_gate_adjudication_validator_rejects_claim_upgrade(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    manifest_path = _write_manifest(run_dir)
    adjudication = build_dft_hardware_closure_gate_adjudication(
        parsed_evidence_manifest_path=manifest_path,
    )

    upgraded = json.loads(json.dumps(adjudication))
    upgraded["hardware_completion_eligible"] = True
    upgraded["deliverable_complete"] = True
    upgraded["stage_gate_passed_count"] = 1
    upgraded["unit_gate_passed_count"] = 1
    upgraded["unit_rows"][0]["deliverable_complete"] = True
    upgraded["unit_rows"][0]["stage_rows"][0]["stage_gate_passed"] = True
    upgraded["unit_rows"][0]["stage_rows"][0]["hardware_completion_eligible"] = True
    validation = validate_dft_hardware_closure_gate_adjudication(upgraded)

    assert validation["valid"] is False
    fields = {err["field"] for err in validation["errors"]}
    assert "hardware_completion_eligible" in fields
    assert "deliverable_complete" in fields
    assert "unit_rows[0].stage_rows[0].stage_gate_passed" in fields


def test_gate_adjudication_cli_step5_and_goal_audit_visibility(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    manifest_path = _write_manifest(run_dir)
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_gate_adjudication.py",
            "--out",
            str(run_dir),
            "--parsed-evidence-manifest",
            str(manifest_path),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr

    _write_json(run_dir / "verdict.json", {"run_id": "gate-adj-step5", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text())
    markdown = (run_dir / paths["final_report_markdown"]).read_text()
    section = report["dft_hardware_closure_gate_adjudication"]
    assert section["present"] is True
    assert section["status"] == "fail_closed_hardware_closure_gate_adjudication_present"
    assert section["stage_count"] == len(STAGES)
    assert section["stage_gate_passed_count"] == 0
    assert section["blocked_stage_count"] == len(STAGES)
    assert section["unit_gate_passed_count"] == 0
    assert section["hardware_completion_eligible"] is False
    assert section["deliverable_complete"] is False
    assert section["trusted_final_claim"] is False
    assert section["completion_claim"] == "blocked"
    assert campaign_summary["dft_hardware_closure_gate_adjudication_summary"]["present"] is True
    assert "DFT Hardware Closure Gate Adjudication" in markdown

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=run_dir,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    requirements = {item["requirement"]: item["status"] for item in audit["prompt_to_artifact_checklist"]}
    assert requirements["DFT hardware closure gate adjudication is Step5-visible and fail-closed"] == "passed"
    assert audit["summary"]["dft_hardware_closure_gate_adjudication_present"] is True
