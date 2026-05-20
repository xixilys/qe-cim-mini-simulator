#!/usr/bin/env python3
"""DFT hardware closure packet/runbook tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.reference_workloads.dft_hardware_closure_packets import (
    DFT_HARDWARE_CLOSURE_PACKETS_SCHEMA,
    build_dft_hardware_closure_packet_payloads,
    validate_dft_hardware_closure_packet_index,
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


def test_closure_packets_write_per_shard_runbooks_fail_closed(tmp_path: Path) -> None:
    shards_path = _closure_shards(tmp_path / "dft_hardware_closure_shards.json")

    status = write_dft_hardware_closure_packets(
        tmp_path / "packets",
        hardware_closure_shards_path=shards_path,
    )

    assert status["status"] == "passed"
    index = json.loads((tmp_path / "packets" / "dft_hardware_closure_packet_index.json").read_text())
    validation = json.loads((tmp_path / "packets" / "dft_hardware_closure_packet_index_validation.json").read_text())
    assert index["schema_version"] == DFT_HARDWARE_CLOSURE_PACKETS_SCHEMA
    assert index["packet_count"] == 1
    assert index["unit_count"] == 2
    assert index["work_item_count"] == 10
    assert index["candidate_specific_bundle_count"] == 0
    assert index["hardware_completion_eligible"] is False
    assert validation["valid"] is True

    packet_ref = index["packets"][0]["packet_json"]["path"]
    runbook_ref = index["packets"][0]["runbook_md"]["path"]
    packet = json.loads((tmp_path / "packets" / packet_ref).read_text())
    runbook = (tmp_path / "packets" / runbook_ref).read_text()
    assert packet["status"] == "blocked_until_candidate_specific_bundle_and_real_tool_execution"
    assert {"vivado_fpga_synth_impl", "dc_asic_synth_timing_area"} <= set(packet["command_template_ids"])
    assert all(not row["present"] for unit in packet["units"] for row in unit["expected_evidence_files"])
    assert "LC_ALL=C LANG=C vivado" in runbook
    assert "dc_shell" in runbook


def test_closure_packets_validator_rejects_claim_upgrade_and_missing_refs(tmp_path: Path) -> None:
    shards_path = _closure_shards(tmp_path / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(tmp_path / "packets", hardware_closure_shards_path=shards_path)
    index = json.loads((tmp_path / "packets" / "dft_hardware_closure_packet_index.json").read_text())

    upgraded = json.loads(json.dumps(index))
    upgraded["hardware_completion_eligible"] = True
    upgraded["packets"][0]["candidate_specific_evidence_present"] = True
    assert validate_dft_hardware_closure_packet_index(upgraded, root_dir=tmp_path / "packets")["valid"] is False

    missing = json.loads(json.dumps(index))
    missing["packets"][0]["packet_json"]["path"] = "missing_packet.json"
    assert validate_dft_hardware_closure_packet_index(missing, root_dir=tmp_path / "packets")["valid"] is False

    packet_path = tmp_path / "packets" / index["packets"][0]["packet_json"]["path"]
    packet = json.loads(packet_path.read_text())
    packet["hardware_completion_eligible"] = True
    packet["deliverable_complete"] = True
    packet["units"][0]["expected_evidence_files"][0]["present"] = True
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    index["packets"][0]["packet_json"]["sha256"] = None
    assert validate_dft_hardware_closure_packet_index(index, root_dir=tmp_path / "packets")["valid"] is False


def test_build_closure_packet_payloads_and_cli(tmp_path: Path) -> None:
    shards_path = _closure_shards(tmp_path / "dft_hardware_closure_shards.json")
    payloads = build_dft_hardware_closure_packet_payloads(hardware_closure_shards_path=shards_path)
    assert len(payloads) == 1
    assert payloads[0]["expected_evidence_file_count"] > 0

    out_dir = tmp_path / "cli_packets"
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_packets.py",
            "--out",
            str(out_dir),
            "--hardware-closure-shards",
            str(shards_path),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert (out_dir / "dft_hardware_closure_packet_index.json").exists()
    assert json.loads((out_dir / "dft_hardware_closure_packet_index_validation.json").read_text())["valid"] is True


def test_closure_packets_are_step5_visible_and_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    shards_path = _closure_shards(run_dir / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(run_dir, hardware_closure_shards_path=shards_path)

    _write_json(run_dir / "verdict.json", {"run_id": "packet-step5", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text())
    markdown = (run_dir / paths["final_report_markdown"]).read_text()
    section = report["dft_hardware_closure_packets"]
    assert section["present"] is True
    assert section["status"] == "fail_closed_hardware_closure_packets_present"
    assert section["packet_count"] == 1
    assert section["unit_count"] == 2
    assert section["expected_evidence_file_count"] > 0
    assert {"vivado_fpga_synth_impl", "dc_asic_synth_timing_area"} <= set(section["command_template_ids"])
    assert len(section["packet_artifact_refs"]) == 1
    assert section["candidate_specific_bundle_count"] == 0
    assert section["hardware_completion_eligible"] is False
    assert section["deliverable_complete"] is False
    assert campaign_summary["dft_hardware_closure_packets_summary"]["present"] is True
    assert "DFT Hardware Closure Packets" in markdown
    assert "Command templates" in markdown

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=run_dir,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    requirements = {item["requirement"]: item for item in audit["prompt_to_artifact_checklist"]}
    packet_requirement = requirements["DFT hardware closure packet/runbook index is Step5-visible and fail-closed"]
    assert packet_requirement["status"] == "passed"
    assert {"vivado_fpga_synth_impl", "dc_asic_synth_timing_area"} <= set(
        packet_requirement["evidence"]["command_template_ids"]
    )
