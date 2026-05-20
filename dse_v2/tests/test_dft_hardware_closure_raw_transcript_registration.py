#!/usr/bin/env python3
"""DFT hardware closure raw-transcript registration tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.codesign.evidence_ledger import sha256_file
from dse_v2.reference_workloads.dft_hardware_closure_bundle import write_dft_hardware_closure_candidate_bundles
from dse_v2.reference_workloads.dft_hardware_closure_evidence import write_dft_hardware_closure_evidence_intake
from dse_v2.reference_workloads.dft_hardware_closure_packets import write_dft_hardware_closure_packets
from dse_v2.reference_workloads.dft_hardware_closure_parser_run import build_dft_hardware_closure_parser_run
from dse_v2.reference_workloads.dft_hardware_closure_raw_transcript_registration import (
    DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_SCHEMA,
    validate_dft_hardware_closure_raw_transcript_registration,
    write_dft_hardware_closure_raw_transcript_registration,
)
from dse_v2.reference_workloads.dft_hardware_closure_unit_provenance import (
    write_dft_hardware_closure_unit_provenance,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts
from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)

_STAGE_IDS = [
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


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _closure_shards(path: Path) -> Path:
    unit = {
        "unit_id": "cand-a:fft_ifft_ffft",
        "candidate_id": "cand-a",
        "kernel_id": "fft_ifft_ffft",
        "kernel_name": "FFT / iFFT / fFFT",
        "kernel_family": "spectral_transform",
        "stage_ids": list(_STAGE_IDS),
        "required_tools": ["dc_shell", "vcs", "vivado"],
        "work_item_ids": [f"cand-a:fft_ifft_ffft:{stage_id}" for stage_id in _STAGE_IDS],
        "work_item_count": len(_STAGE_IDS),
        "blocked_work_item_count": len(_STAGE_IDS),
        "candidate_specific_bundle_required": True,
        "candidate_specific_evidence_present": False,
    }
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_shards.v1",
            "status": "queued_fail_closed",
            "release_id": "release-raw-transcript-registration",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "unit_count": 1,
            "shard_count": 1,
            "work_item_count": len(_STAGE_IDS),
            "blocked_work_item_count": len(_STAGE_IDS),
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
                    "work_item_count": len(_STAGE_IDS),
                    "blocked_work_item_count": len(_STAGE_IDS),
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


def _unit_from_packet(run_dir: Path) -> dict:
    packet = json.loads(
        (run_dir / "dft_hardware_closure_packets" / "dft_hardware_closure_shard_0000_packet.json").read_text()
    )
    return packet["units"][0]


def _stage_raw_files(run_dir: Path, unit: dict, stage_id: str, *, verdict: str = "PASS") -> list[Path]:
    written = []
    for expected in unit["expected_evidence_files"]:
        if expected["stage_id"] != stage_id:
            continue
        path = run_dir / expected["path"]
        if path.suffix == ".json":
            written.append(
                _write_json(
                    path,
                    {
                        "schema_version": "unit-test.raw_evidence.v1",
                        "candidate_id": unit["candidate_id"],
                        "kernel_id": unit["kernel_id"],
                        "stage_id": stage_id,
                        "status": verdict,
                        "verdict": verdict.lower(),
                        "passed": verdict.upper() in {"PASS", "PASSED", "SUCCESS", "MET"},
                        "max_abs_error": 0.0,
                    },
                )
            )
        else:
            written.append(_write_text(path, f"{stage_id} {verdict}\n"))
    return written


def _prepare_run(run_dir: Path) -> tuple[Path, dict]:
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    write_dft_hardware_closure_candidate_bundles(run_dir, closure_packet_index_path=packet_index, evidence_root=run_dir)
    write_dft_hardware_closure_unit_provenance(run_dir, closure_packet_index_path=packet_index, evidence_root=run_dir)
    return packet_index, unit


def test_raw_transcript_registration_hashes_present_raw_files_and_enables_parser(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index, unit = _prepare_run(run_dir)
    raw_paths = _stage_raw_files(run_dir, unit, "golden_correctness", verdict="PASS")

    status = write_dft_hardware_closure_raw_transcript_registration(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
        stage_ids=["golden_correctness"],
    )

    assert status["status"] == "passed"
    registration = json.loads((run_dir / "dft_hardware_closure_raw_transcript_registration.json").read_text())
    validation = json.loads((run_dir / "dft_hardware_closure_raw_transcript_registration_validation.json").read_text())
    assert registration["schema_version"] == DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_SCHEMA
    assert registration["registered_unit_count"] == 1
    assert registration["registered_raw_stage_evidence_file_count"] == len(raw_paths)
    assert registration["hardware_completion_eligible"] is False
    assert registration["deliverable_complete"] is False
    assert validation["valid"] is True
    transcript_ref = registration["units"][0]["raw_transcript_index"]
    transcript = json.loads(Path(transcript_ref["path"]).read_text())
    assert transcript["raw_stage_evidence_file_count"] == len(raw_paths)
    assert len(transcript["raw_transcript_refs"]) == len(raw_paths)
    assert {ref["sha256"] for ref in transcript["raw_transcript_refs"]} == {sha256_file(path) for path in raw_paths}

    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )
    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )
    golden = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "golden_correctness")
    assert golden["status"] == "parsed_result_written_pending_adjudication"
    assert golden["parsed_result"]["verdict"] == "passed"
    assert parser_run["passed_stage_count"] == 0
    assert parser_run["hardware_completion_eligible"] is False


def test_raw_transcript_registration_without_raw_files_is_valid_but_non_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index, _unit = _prepare_run(run_dir)

    status = write_dft_hardware_closure_raw_transcript_registration(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
        stage_ids=["golden_correctness"],
    )

    assert status["status"] == "passed"
    registration = json.loads((run_dir / "dft_hardware_closure_raw_transcript_registration.json").read_text())
    assert registration["status"] == "no_raw_stage_evidence_present"
    assert registration["registered_raw_stage_evidence_file_count"] == 0
    assert registration["passed_stage_count"] == 0
    assert registration["hardware_completion_eligible"] is False


def test_raw_transcript_registration_rejects_mismatched_raw_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index, unit = _prepare_run(run_dir)
    raw_paths = _stage_raw_files(run_dir, unit, "golden_correctness", verdict="PASS")
    first_payload = json.loads(raw_paths[0].read_text())
    first_payload["candidate_id"] = "wrong-candidate"
    _write_json(raw_paths[0], first_payload)

    status = write_dft_hardware_closure_raw_transcript_registration(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
        stage_ids=["golden_correctness"],
    )

    assert status["status"] == "passed"
    registration = json.loads((run_dir / "dft_hardware_closure_raw_transcript_registration.json").read_text())
    row = registration["units"][0]
    assert row["status"] == "blocked_invalid_raw_stage_evidence"
    assert row["registered_raw_stage_evidence_file_count"] == 0
    assert row["invalid_raw_stage_evidence_file_count"] == 1
    assert validate_dft_hardware_closure_raw_transcript_registration(registration)["valid"] is True


def test_raw_transcript_registration_validator_rejects_claim_upgrade_or_hash_tamper(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index, unit = _prepare_run(run_dir)
    _stage_raw_files(run_dir, unit, "golden_correctness", verdict="PASS")
    write_dft_hardware_closure_raw_transcript_registration(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
        stage_ids=["golden_correctness"],
    )
    registration = json.loads((run_dir / "dft_hardware_closure_raw_transcript_registration.json").read_text())

    upgraded = json.loads(json.dumps(registration))
    upgraded["hardware_completion_eligible"] = True
    upgraded["units"][0]["deliverable_complete"] = True
    assert validate_dft_hardware_closure_raw_transcript_registration(upgraded)["valid"] is False

    tampered = json.loads(json.dumps(registration))
    transcript_path = Path(tampered["units"][0]["raw_transcript_index"]["path"])
    transcript = json.loads(transcript_path.read_text())
    transcript["raw_transcript_refs"][0]["sha256"] = "bad-hash"
    _write_json(transcript_path, transcript)
    tampered["units"][0]["raw_transcript_index"]["sha256"] = sha256_file(transcript_path)
    assert validate_dft_hardware_closure_raw_transcript_registration(tampered)["valid"] is False


def test_raw_transcript_registration_cli_step5_and_goal_audit_visibility(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    packet_index, unit = _prepare_run(run_dir)
    _stage_raw_files(run_dir, unit, "golden_correctness", verdict="PASS")
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_raw_transcript_registration.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(packet_index),
            "--evidence-root",
            str(run_dir),
            "--stage-id",
            "golden_correctness",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr

    _write_json(run_dir / "verdict.json", {"run_id": "raw-transcript-registration-step5", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text())
    markdown = (run_dir / paths["final_report_markdown"]).read_text()
    section = report["dft_hardware_closure_raw_transcript_registration"]
    assert section["present"] is True
    assert section["status"] == "fail_closed_hardware_closure_raw_transcript_registration_present"
    assert section["registered_unit_count"] == 1
    assert section["registered_raw_stage_evidence_file_count"] == 3
    assert section["passed_stage_count"] == 0
    assert section["hardware_completion_eligible"] is False
    assert section["deliverable_complete"] is False
    assert campaign_summary["dft_hardware_closure_raw_transcript_registration_summary"]["present"] is True
    assert "DFT Hardware Closure Raw Transcript Registration" in markdown

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=run_dir,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    requirements = {item["requirement"]: item["status"] for item in audit["prompt_to_artifact_checklist"]}
    assert requirements["DFT hardware closure raw transcript registration is Step5-visible and fail-closed"] == "passed"
