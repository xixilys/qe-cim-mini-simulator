#!/usr/bin/env python3
"""DFT hardware closure candidate-bundle template tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.codesign.evidence_ledger import sha256_file
from dse_v2.reference_workloads.dft_hardware_closure_bundle import (
    DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_INDEX_SCHEMA,
    validate_dft_hardware_closure_candidate_bundle_index,
    write_dft_hardware_closure_candidate_bundles,
)
from dse_v2.reference_workloads.dft_hardware_closure_evidence import (
    write_dft_hardware_closure_evidence_intake,
)
from dse_v2.reference_workloads.dft_hardware_closure_packets import (
    write_dft_hardware_closure_packets,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts
from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _closure_shards(path: Path) -> Path:
    units = []
    for candidate_id in ["cand-a", "cand-b"]:
        units.append(
            {
                "unit_id": f"{candidate_id}:fft_ifft_ffft",
                "candidate_id": candidate_id,
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
                    f"{candidate_id}:fft_ifft_ffft:golden_correctness",
                    f"{candidate_id}:fft_ifft_ffft:hls_or_rtl_sim",
                    f"{candidate_id}:fft_ifft_ffft:hls_or_rtl_synth",
                    f"{candidate_id}:fft_ifft_ffft:vivado_fpga_synth_or_impl",
                    f"{candidate_id}:fft_ifft_ffft:dc_asic_synth_timing_area",
                ],
                "work_item_count": 5,
                "blocked_work_item_count": 5,
                "candidate_specific_bundle_required": True,
                "candidate_specific_evidence_present": False,
                "execution_status": "queued_blocked_until_candidate_specific_bundle_and_real_tool_execution",
            }
        )
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_shards.v1",
            "status": "queued_fail_closed",
            "release_id": "release-test",
            "candidate_count": 2,
            "major_kernel_count": 1,
            "unit_count": 2,
            "shard_count": 1,
            "work_item_count": 10,
            "blocked_work_item_count": 10,
            "candidate_specific_bundle_count": 0,
            "candidate_specific_evidence_present_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "shards": [
                {
                    "shard_id": "dft_hardware_closure_shard_0000",
                    "candidate_ids": ["cand-a", "cand-b"],
                    "kernel_ids": ["fft_ifft_ffft"],
                    "required_tools": ["dc_shell", "vcs", "vivado"],
                    "unit_count": 2,
                    "work_item_count": 10,
                    "blocked_work_item_count": 10,
                    "candidate_specific_bundle_count": 0,
                    "execution_status": "queued_blocked_until_candidate_specific_bundle_and_real_tool_execution",
                    "units": units,
                }
            ],
        },
    )


def test_candidate_bundle_templates_are_written_without_raw_evidence_or_claim_upgrade(tmp_path: Path) -> None:
    shards_path = _closure_shards(tmp_path / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(tmp_path / "packets", hardware_closure_shards_path=shards_path)

    status = write_dft_hardware_closure_candidate_bundles(
        tmp_path / "bundles",
        closure_packet_index_path=tmp_path / "packets" / "dft_hardware_closure_packet_index.json",
        evidence_root=tmp_path / "evidence",
    )

    assert status["status"] == "passed"
    index = json.loads((tmp_path / "bundles" / "dft_hardware_closure_candidate_bundle_index.json").read_text())
    validation = json.loads((tmp_path / "bundles" / "dft_hardware_closure_candidate_bundle_index_validation.json").read_text())
    assert index["schema_version"] == DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_INDEX_SCHEMA
    assert index["bundle_count"] == 2
    assert index["raw_evidence_file_count"] == 0
    assert index["hardware_completion_eligible"] is False
    assert index["deliverable_complete"] is False
    assert validation["valid"] is True
    bundle_ref = index["bundles"][0]["candidate_bundle"]
    bundle = json.loads(Path(bundle_ref["path"]).read_text())
    assert bundle["status"] == "bundle_template_only_missing_raw_evidence"
    assert bundle["raw_evidence_present"] is False
    assert bundle["hardware_completion_eligible"] is False

    intake_status = write_dft_hardware_closure_evidence_intake(
        tmp_path / "intake",
        closure_packet_index_path=tmp_path / "packets" / "dft_hardware_closure_packet_index.json",
        evidence_root=tmp_path / "evidence",
    )
    intake = json.loads((tmp_path / "intake" / "dft_hardware_closure_evidence_intake.json").read_text())
    assert intake_status["status"] == "passed"
    assert intake["candidate_bundle_count"] == 2
    assert intake["present_evidence_file_count"] == 0
    assert intake["missing_evidence_file_count"] > 0
    assert intake["hardware_completion_eligible"] is False


def test_candidate_bundle_validator_rejects_claim_upgrade(tmp_path: Path) -> None:
    shards_path = _closure_shards(tmp_path / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(tmp_path / "packets", hardware_closure_shards_path=shards_path)
    write_dft_hardware_closure_candidate_bundles(
        tmp_path / "bundles",
        closure_packet_index_path=tmp_path / "packets" / "dft_hardware_closure_packet_index.json",
    )
    index = json.loads((tmp_path / "bundles" / "dft_hardware_closure_candidate_bundle_index.json").read_text())

    upgraded = json.loads(json.dumps(index))
    upgraded["hardware_completion_eligible"] = True
    upgraded["bundles"][0]["deliverable_complete"] = True
    assert validate_dft_hardware_closure_candidate_bundle_index(upgraded)["valid"] is False


def test_candidate_bundle_validator_rejects_tampered_bundle_payload(tmp_path: Path) -> None:
    shards_path = _closure_shards(tmp_path / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(tmp_path / "packets", hardware_closure_shards_path=shards_path)
    write_dft_hardware_closure_candidate_bundles(
        tmp_path / "bundles",
        closure_packet_index_path=tmp_path / "packets" / "dft_hardware_closure_packet_index.json",
    )
    index = json.loads((tmp_path / "bundles" / "dft_hardware_closure_candidate_bundle_index.json").read_text())
    bundle_path = Path(index["bundles"][0]["candidate_bundle"]["path"])
    bundle_payload = json.loads(bundle_path.read_text())
    bundle_payload["raw_evidence_file_count"] = 99
    bundle_payload["raw_evidence_present"] = True
    bundle_payload["hardware_completion_eligible"] = True
    bundle_payload["deliverable_complete"] = True
    bundle_payload["expected_evidence_files"][0]["present"] = True
    _write_json(bundle_path, bundle_payload)
    index["bundles"][0]["candidate_bundle"]["sha256"] = sha256_file(bundle_path)

    validation = validate_dft_hardware_closure_candidate_bundle_index(index)

    assert validation["valid"] is False
    fields = {error["field"] for error in validation["errors"]}
    assert any(field.endswith("raw_evidence_file_count") for field in fields)
    assert any(field.endswith("hardware_completion_eligible") for field in fields)


def test_candidate_bundle_default_root_matches_evidence_intake_default(tmp_path: Path) -> None:
    shards_path = _closure_shards(tmp_path / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(tmp_path / "packets", hardware_closure_shards_path=shards_path)

    status = write_dft_hardware_closure_candidate_bundles(
        tmp_path / "bundles",
        closure_packet_index_path=tmp_path / "packets" / "dft_hardware_closure_packet_index.json",
    )
    intake_status = write_dft_hardware_closure_evidence_intake(
        tmp_path / "intake",
        closure_packet_index_path=tmp_path / "packets" / "dft_hardware_closure_packet_index.json",
    )
    intake = json.loads((tmp_path / "intake" / "dft_hardware_closure_evidence_intake.json").read_text())

    assert status["status"] == "passed"
    assert intake_status["status"] == "passed"
    assert intake["candidate_bundle_count"] == 2


def test_candidate_bundle_writer_rejects_bundle_paths_outside_evidence_root(tmp_path: Path) -> None:
    shards_path = _closure_shards(tmp_path / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(tmp_path / "packets", hardware_closure_shards_path=shards_path)
    packet_index = json.loads((tmp_path / "packets" / "dft_hardware_closure_packet_index.json").read_text())
    packet_path = tmp_path / "packets" / packet_index["packets"][0]["packet_json"]["path"]
    packet = json.loads(packet_path.read_text())
    packet["units"][0]["candidate_bundle_json"] = "../escaped/candidate_bundle.json"
    _write_json(packet_path, packet)

    status = write_dft_hardware_closure_candidate_bundles(
        tmp_path / "bundles",
        closure_packet_index_path=tmp_path / "packets" / "dft_hardware_closure_packet_index.json",
        evidence_root=tmp_path / "evidence",
    )
    index = json.loads((tmp_path / "bundles" / "dft_hardware_closure_candidate_bundle_index.json").read_text())

    assert status["status"] == "failed"
    assert index["status"] == "failed_invalid_candidate_bundle_path"
    assert index["error_count"] == 1
    assert not (tmp_path / "escaped" / "candidate_bundle.json").exists()


def test_candidate_bundle_cli_and_step5_intake_visibility(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    shards_path = _closure_shards(run_dir / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(run_dir, hardware_closure_shards_path=shards_path)
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_candidate_bundles.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(run_dir / "dft_hardware_closure_packet_index.json"),
            "--evidence-root",
            str(run_dir),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=run_dir / "dft_hardware_closure_packet_index.json",
        evidence_root=run_dir,
    )
    _write_json(run_dir / "verdict.json", {"run_id": "bundle-step5", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})

    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    bundle_section = report["dft_hardware_closure_candidate_bundles"]
    assert bundle_section["present"] is True
    assert bundle_section["bundle_count"] == 2
    assert bundle_section["raw_evidence_file_count"] == 0
    assert bundle_section["hardware_completion_eligible"] is False
    intake_section = report["dft_hardware_closure_evidence_intake"]
    assert intake_section["present"] is True
    assert intake_section["candidate_bundle_count"] == 2
    assert intake_section["present_evidence_file_count"] == 0
    assert intake_section["missing_evidence_file_count"] > 0
    assert intake_section["hardware_completion_eligible"] is False

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=run_dir,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    requirements = {item["requirement"]: item for item in audit["prompt_to_artifact_checklist"]}
    assert requirements["DFT hardware closure candidate-bundle templates are Step5-visible and fail-closed"]["status"] == "passed"
    assert requirements["DFT hardware closure evidence intake is Step5-visible and fail-closed"]["status"] == "passed"
