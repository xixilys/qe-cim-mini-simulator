#!/usr/bin/env python3
"""DFT hardware closure unit-provenance staging tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.codesign.evidence_ledger import sha256_file
from dse_v2.reference_workloads.dft_hardware_closure_bundle import (
    write_dft_hardware_closure_candidate_bundles,
)
from dse_v2.reference_workloads.dft_hardware_closure_evidence import (
    write_dft_hardware_closure_evidence_intake,
)
from dse_v2.reference_workloads.dft_hardware_closure_packets import (
    write_dft_hardware_closure_packets,
)
from dse_v2.reference_workloads.dft_hardware_closure_parser_run import (
    build_dft_hardware_closure_parser_run,
)
from dse_v2.reference_workloads.dft_hardware_closure_unit_provenance import (
    DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_INDEX_SCHEMA,
    validate_dft_hardware_closure_unit_provenance_index,
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


def _closure_shards(path: Path, *, candidate_ids: tuple[str, ...] = ("cand-a", "cand-b")) -> Path:
    units = []
    for candidate_id in candidate_ids:
        units.append(
            {
                "unit_id": f"{candidate_id}:fft_ifft_ffft",
                "candidate_id": candidate_id,
                "kernel_id": "fft_ifft_ffft",
                "kernel_name": "FFT / iFFT / fFFT",
                "kernel_family": "spectral_transform",
                "stage_ids": list(_STAGE_IDS),
                "required_tools": ["dc_shell", "vcs", "vivado"],
                "work_item_ids": [f"{candidate_id}:fft_ifft_ffft:{stage_id}" for stage_id in _STAGE_IDS],
                "work_item_count": len(_STAGE_IDS),
                "blocked_work_item_count": len(_STAGE_IDS),
                "candidate_specific_bundle_required": True,
                "candidate_specific_evidence_present": False,
            }
        )
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_shards.v1",
            "status": "queued_fail_closed",
            "release_id": "release-unit-provenance",
            "candidate_count": len(candidate_ids),
            "major_kernel_count": 1,
            "unit_count": len(units),
            "shard_count": 1,
            "work_item_count": len(units) * len(_STAGE_IDS),
            "blocked_work_item_count": len(units) * len(_STAGE_IDS),
            "candidate_specific_bundle_count": 0,
            "candidate_specific_evidence_present_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "shards": [
                {
                    "shard_id": "dft_hardware_closure_shard_0000",
                    "candidate_ids": list(candidate_ids),
                    "kernel_ids": ["fft_ifft_ffft"],
                    "required_tools": ["dc_shell", "vcs", "vivado"],
                    "unit_count": len(units),
                    "work_item_count": len(units) * len(_STAGE_IDS),
                    "blocked_work_item_count": len(units) * len(_STAGE_IDS),
                    "candidate_specific_bundle_count": 0,
                    "units": units,
                }
            ],
        },
    )


def _packetized_run(run_dir: Path, *, candidate_ids: tuple[str, ...] = ("cand-a", "cand-b")) -> Path:
    shards_path = _closure_shards(run_dir / "dft_hardware_closure_shards.json", candidate_ids=candidate_ids)
    write_dft_hardware_closure_packets(run_dir, hardware_closure_shards_path=shards_path)
    return run_dir / "dft_hardware_closure_packet_index.json"


def _unit_from_packet(run_dir: Path, index: int = 0) -> dict:
    packet = json.loads(
        (run_dir / "dft_hardware_closure_packets" / "dft_hardware_closure_shard_0000_packet.json").read_text()
    )
    return packet["units"][index]


def _write_candidate_bundles(run_dir: Path, packet_index: Path) -> None:
    status = write_dft_hardware_closure_candidate_bundles(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )
    assert status["status"] == "passed"


def _write_stage_raw_files(run_dir: Path, unit: dict, stage_id: str, *, verdict: str = "PASS") -> list[Path]:
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


def test_unit_provenance_stages_metadata_only_for_selected_units(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)

    status = write_dft_hardware_closure_unit_provenance(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
        max_units=1,
    )

    assert status["status"] == "passed"
    assert status["staged_unit_count"] == 1
    assert status["global_provenance_file_count"] == 4
    assert status["raw_stage_evidence_file_count"] == 0
    index = json.loads((run_dir / "dft_hardware_closure_unit_provenance_index.json").read_text())
    validation = json.loads((run_dir / "dft_hardware_closure_unit_provenance_validation.json").read_text())
    assert index["schema_version"] == DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_INDEX_SCHEMA
    assert index["status"] == "candidate_specific_provenance_staged_pending_raw_evidence"
    assert index["hardware_completion_eligible"] is False
    assert index["deliverable_complete"] is False
    assert validation["valid"] is True
    unit = index["units"][0]
    assert set(unit["provenance_files"]) == {
        "tool_versions.json",
        "command_manifest.json",
        "raw_transcript_index.json",
        "source_bundle_manifest.json",
    }
    for ref in unit["provenance_files"].values():
        payload = json.loads(Path(ref["path"]).read_text())
        assert payload["candidate_id"] == "cand-a"
        assert payload["kernel_id"] == "fft_ifft_ffft"
        assert payload["candidate_specific_closure"] is True
        assert payload["raw_evidence_scope"] == "candidate_specific_closure"
        assert payload["hardware_completion_eligible"] is False
        assert payload["deliverable_complete"] is False
    transcript = json.loads(Path(unit["provenance_files"]["raw_transcript_index.json"]["path"]).read_text())
    assert transcript["raw_stage_evidence_file_count"] == 0
    assert transcript["raw_transcript_refs"] == []


def test_unit_provenance_validator_rejects_claim_upgrade_hash_mismatch_and_path_escape(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir, candidate_ids=("cand-a",))
    write_dft_hardware_closure_unit_provenance(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
        max_units=1,
    )
    index = json.loads((run_dir / "dft_hardware_closure_unit_provenance_index.json").read_text())

    upgraded = json.loads(json.dumps(index))
    upgraded["hardware_completion_eligible"] = True
    upgraded["units"][0]["deliverable_complete"] = True
    first_ref = upgraded["units"][0]["provenance_files"]["tool_versions.json"]
    first_payload_path = Path(first_ref["path"])
    payload = json.loads(first_payload_path.read_text())
    payload["hardware_completion_eligible"] = True
    _write_json(first_payload_path, payload)
    first_ref["sha256"] = sha256_file(first_payload_path)
    assert validate_dft_hardware_closure_unit_provenance_index(upgraded)["valid"] is False

    tampered = json.loads(json.dumps(index))
    source_manifest = Path(tampered["units"][0]["provenance_files"]["source_bundle_manifest.json"]["path"])
    _write_json(source_manifest, {"candidate_id": "wrong", "kernel_id": "fft_ifft_ffft"})
    assert validate_dft_hardware_closure_unit_provenance_index(tampered)["valid"] is False

    escaped = json.loads(json.dumps(index))
    escaped["units"][0]["provenance_files"]["command_manifest.json"]["path"] = str(tmp_path / "outside.json")
    escaped["units"][0]["provenance_files"]["command_manifest.json"]["sha256"] = "not-a-real-hash"
    assert validate_dft_hardware_closure_unit_provenance_index(escaped)["valid"] is False


def test_unit_provenance_rejects_packet_index_path_escape(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir, candidate_ids=("cand-a",))
    malicious_packet = _write_json(
        tmp_path / "malicious_packet.json",
        {
            "schema_version": "dse.dft.hardware_closure_packet.v1",
            "packet_id": "malicious",
            "shard_id": "malicious",
            "units": [_unit_from_packet(run_dir)],
        },
    )
    index = json.loads(packet_index.read_text())
    index["packets"][0]["packet_json"]["path"] = str(malicious_packet)
    _write_json(packet_index, index)

    status = write_dft_hardware_closure_unit_provenance(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )
    payload = json.loads((run_dir / "dft_hardware_closure_unit_provenance_index.json").read_text())
    validation = json.loads((run_dir / "dft_hardware_closure_unit_provenance_validation.json").read_text())

    assert status["status"] == "failed"
    assert payload["status"] == "failed_invalid_unit_provenance_path"
    assert payload["staged_unit_count"] == 0
    assert validation["valid"] is False
    assert not (run_dir / "candidate_specific_evidence").exists()


def test_parser_after_staged_unit_provenance_blocks_on_missing_raw_stage_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir, candidate_ids=("cand-a",))
    _write_candidate_bundles(run_dir, packet_index)
    write_dft_hardware_closure_unit_provenance(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
        max_units=1,
    )
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

    assert parser_run["parsed_result_written_count"] == 0
    assert parser_run["blocked_stage_count"] == 5
    assert {row["status"] for row in parser_run["parser_rows"]} == {"blocked_missing_raw_stage_evidence"}
    assert {tuple(row["candidate_specific_provenance_blockers"]) for row in parser_run["parser_rows"]} == {()}


def test_parser_with_staged_provenance_and_raw_file_requires_transcript_refs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir, candidate_ids=("cand-a",))
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundles(run_dir, packet_index)
    write_dft_hardware_closure_unit_provenance(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
        max_units=1,
    )
    _write_stage_raw_files(run_dir, unit, "golden_correctness", verdict="PASS")
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

    assert parser_run["parsed_result_written_count"] == 0
    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "golden_correctness")
    assert row["status"] == "blocked_invalid_candidate_specific_provenance"
    assert "raw_stage_file_missing_from_raw_transcript_index" in row["candidate_specific_provenance_blockers"]
    assert not (run_dir / "parsed_hard_gate_results").exists()


def test_unit_provenance_cli_step5_and_goal_audit_visibility(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    packet_index = _packetized_run(run_dir, candidate_ids=("cand-a",))
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_unit_provenance.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(packet_index),
            "--evidence-root",
            str(run_dir),
            "--max-units",
            "1",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr

    _write_json(run_dir / "verdict.json", {"run_id": "unit-provenance-step5", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text())
    markdown = (run_dir / paths["final_report_markdown"]).read_text()
    section = report["dft_hardware_closure_unit_provenance"]
    assert section["present"] is True
    assert section["status"] == "fail_closed_hardware_closure_unit_provenance_present"
    assert section["staged_unit_count"] == 1
    assert section["global_provenance_file_count"] == 4
    assert section["raw_stage_evidence_file_count"] == 0
    assert section["hardware_completion_eligible"] is False
    assert section["deliverable_complete"] is False
    assert campaign_summary["dft_hardware_closure_unit_provenance_summary"]["present"] is True
    assert "DFT Hardware Closure Unit Provenance" in markdown

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=run_dir,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    requirements = {item["requirement"]: item["status"] for item in audit["prompt_to_artifact_checklist"]}
    assert requirements["DFT hardware closure unit provenance staging is Step5-visible and fail-closed"] == "passed"
