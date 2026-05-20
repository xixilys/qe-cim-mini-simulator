#!/usr/bin/env python3
"""Tests for DFT real source-flow shard runner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_hardware_closure_packets import write_dft_hardware_closure_packets
from dse_v2.reference_workloads.dft_hardware_closure_real_source_flow_run import (
    validate_dft_hardware_closure_real_source_flow_run,
)
from dse_v2.reference_workloads.dft_hardware_closure_shards import write_dft_hardware_closure_shard_queue

CANDIDATE_ID = "cand-a"
KERNEL_IDS = ("fft_ifft_ffft", "kinetic_add")
STAGES = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _packetized_run(run_dir: Path) -> Path:
    work_items = []
    for kernel_id in KERNEL_IDS:
        for stage_id in STAGES:
            work_items.append(
                {
                    "work_item_id": f"{CANDIDATE_ID}:{kernel_id}:{stage_id}",
                    "candidate_id": CANDIDATE_ID,
                    "kernel_id": kernel_id,
                    "kernel_name": kernel_id.replace("_", " "),
                    "kernel_family": "real_source_flow_run_test",
                    "stage_id": stage_id,
                    "tool_id": "python3" if stage_id == "golden_correctness" else "real_tool",
                    "blocked": True,
                    "shared_microkernel_smoke_stage_passed": False,
                    "candidate_specific_evidence_present": False,
                }
            )
    workplan_path = _write_json(
        run_dir / "dft_hardware_completion_workplan.json",
        {
            "schema_version": "dse.dft.hardware_completion_workplan.v1",
            "status": "blocked_real_source_flow_run_test",
            "release_id": "release-real-source-flow-run-test",
            "candidate_count": 1,
            "major_kernel_count": len(KERNEL_IDS),
            "work_items": work_items,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
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


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_real_source_flow_runner_cli_writes_candidate_stamped_map_without_claim_upgrade(tmp_path: Path) -> None:
    packet_index = _packetized_run(tmp_path / "packetized")
    out_dir = tmp_path / "real-source-flow-run"

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_dft_hardware_closure_real_source_flows.py",
            "--out",
            str(out_dir),
            "--closure-packet-index",
            str(packet_index),
            "--candidate-id",
            CANDIDATE_ID,
            "--max-units",
            "2",
            "--jobs",
            "2",
            "--skip-remote",
            "--quiet",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    payload = _load(out_dir / "dft_hardware_closure_real_source_flow_run.json")
    validation = _load(out_dir / "dft_hardware_closure_real_source_flow_run_validation.json")
    status = _load(out_dir / "dft_hardware_closure_real_source_flow_run_status.json")
    source_flow_map = _load(out_dir / "source_flow_map.json")

    assert validation["valid"] is True
    assert status["status"] == "passed"
    assert payload["selected_unit_count"] == 2
    assert payload["source_flow_ready_count"] == 2
    assert payload["blocked_unit_count"] == 0
    assert payload["hardware_completion_eligible"] is False
    assert payload["deliverable_complete"] is False
    assert source_flow_map["flow_count"] == 2
    assert source_flow_map["hardware_completion_eligible"] is False
    assert source_flow_map["deliverable_complete"] is False
    assert {
        (row["candidate_id"], row["kernel_id"])
        for row in source_flow_map["flows"]
    } == {(CANDIDATE_ID, kernel_id) for kernel_id in KERNEL_IDS}

    for row in payload["units"]:
        flow_dir = Path(row["source_flow_dir"])
        manifest = _load(flow_dir / "manifest.json")
        matrix = _load(flow_dir / "dft_hardware_evidence_matrix.json")
        assert manifest["candidate_id"] == CANDIDATE_ID
        assert manifest["kernel_id"] == row["kernel_id"]
        assert matrix["candidate_id"] == CANDIDATE_ID
        assert row["source_flow_ready"] is True
        assert row["hardware_completion_eligible"] is False
        assert row["deliverable_complete"] is False
        command = row["command"]
        assert "--remote-dir" in command
        remote_dir = command[command.index("--remote-dir") + 1]
        assert remote_dir.startswith("/tmp/dft_accelerate_real-source-flow-run_")
        assert CANDIDATE_ID in remote_dir
        assert row["kernel_id"] in remote_dir


def test_real_source_flow_run_validator_rejects_claim_upgrade(tmp_path: Path) -> None:
    packet_index = _packetized_run(tmp_path / "packetized")
    out_dir = tmp_path / "real-source-flow-run"
    subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_dft_hardware_closure_real_source_flows.py",
            "--out",
            str(out_dir),
            "--closure-packet-index",
            str(packet_index),
            "--candidate-id",
            CANDIDATE_ID,
            "--kernel-id",
            KERNEL_IDS[0],
            "--skip-remote",
            "--quiet",
        ],
        check=True,
    )
    payload = _load(out_dir / "dft_hardware_closure_real_source_flow_run.json")

    upgraded = json.loads(json.dumps(payload))
    upgraded["hardware_completion_eligible"] = True
    upgraded["units"][0]["deliverable_complete"] = True

    validation = validate_dft_hardware_closure_real_source_flow_run(upgraded)

    assert validation["valid"] is False
    fields = {error["field"] for error in validation["errors"]}
    assert "hardware_completion_eligible" in fields
    assert "units[0].deliverable_complete" in fields
