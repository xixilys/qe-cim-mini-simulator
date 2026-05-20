#!/usr/bin/env python3
"""Tests for latest real-source-flow discovery map helper."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.reference_workloads.dft_hardware_closure_packets import (
    write_dft_hardware_closure_packets,
)

KERNEL_IDS = tuple(MAJOR_SCF_KERNEL_IDS)
STAGES = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _closure_shards(path: Path, *, candidate_id: str) -> Path:
    units = []
    for kernel_id in KERNEL_IDS:
        units.append(
            {
                "unit_id": f"{candidate_id}:{kernel_id}",
                "candidate_id": candidate_id,
                "kernel_id": kernel_id,
                "kernel_name": kernel_id.replace("_", " "),
                "kernel_family": "latest_source_flow_map_test",
                "stage_ids": list(STAGES),
                "required_tools": ["python3", "vcs", "vivado", "dc_shell"],
                "work_item_ids": [
                    f"{candidate_id}:{kernel_id}:{stage_id}" for stage_id in STAGES
                ],
                "work_item_count": len(STAGES),
                "blocked_work_item_count": len(STAGES),
                "candidate_specific_bundle_required": True,
                "candidate_specific_evidence_present": False,
            }
        )
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_shards.v1",
            "status": "queued_fail_closed",
            "release_id": "release-latest-source-flow-map-test",
            "candidate_count": 1,
            "major_kernel_count": len(KERNEL_IDS),
            "unit_count": len(units),
            "shard_count": 1,
            "work_item_count": len(units) * len(STAGES),
            "blocked_work_item_count": len(units) * len(STAGES),
            "candidate_specific_bundle_count": 0,
            "candidate_specific_evidence_present_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "shards": [
                {
                    "shard_id": "dft_hardware_closure_shard_0000",
                    "candidate_ids": [candidate_id],
                    "kernel_ids": list(KERNEL_IDS),
                    "required_tools": ["python3", "vcs", "vivado", "dc_shell"],
                    "unit_count": len(units),
                    "work_item_count": len(units) * len(STAGES),
                    "blocked_work_item_count": len(units) * len(STAGES),
                    "candidate_specific_bundle_count": 0,
                    "units": units,
                }
            ],
        },
    )


def _packetized_run(run_dir: Path, *, candidate_id: str) -> Path:
    shards_path = _closure_shards(
        run_dir / "dft_hardware_closure_shards.json", candidate_id=candidate_id
    )
    write_dft_hardware_closure_packets(
        run_dir, hardware_closure_shards_path=shards_path
    )
    return run_dir / "dft_hardware_closure_packet_index.json"


def _source_flow(root: Path, *, candidate_id: str, kernel_id: str) -> None:
    flow_dir = root / candidate_id / kernel_id
    _write_json(
        flow_dir / "manifest.json",
        {
            "schema_version": f"dse.dft_scf.{kernel_id}.rtl_flow.v1",
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "claim_boundary": "latest source-flow map test fixture only",
        },
    )
    (flow_dir / f"{kernel_id}.v").write_text("// rtl fixture\n", encoding="utf-8")


def _real_source_flow_run(
    run_root: Path,
    *,
    candidate_id: str,
    status: str = "source_flows_ready_pending_step5",
    ready_count: int = 8,
    blocked_count: int = 0,
) -> Path:
    run_dir = run_root / f"wave36_real_source_flow_run_{candidate_id}_all8_fixture"
    source_root = run_dir / "source_flows"
    for kernel_id in KERNEL_IDS:
        _source_flow(source_root, candidate_id=candidate_id, kernel_id=kernel_id)
    units = [
        {
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "status": "source_flow_ready_pending_step5",
            "source_flow_dir": str(source_root / candidate_id / kernel_id),
            "source_flow_ready": True,
            "blocker_ids": [],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        }
        for kernel_id in KERNEL_IDS
    ]
    return _write_json(
        run_dir / "dft_hardware_closure_real_source_flow_run.json",
        {
            "schema_version": "dse.dft.hardware_closure_real_source_flow_run.v1",
            "status": status,
            "candidate_count": 1,
            "major_kernel_count": len(KERNEL_IDS),
            "selected_unit_count": len(KERNEL_IDS),
            "run_unit_count": len(KERNEL_IDS),
            "source_flow_ready_count": ready_count,
            "blocked_unit_count": blocked_count,
            "units": units,
            "adjudication_result": "not_adjudicated_by_real_source_flow_run",
            "passed_stage_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_latest_source_flow_map_cli_includes_only_ready_all8_run_roots(
    tmp_path: Path,
) -> None:
    packet_index = _packetized_run(tmp_path / "packetized", candidate_id="cand-ready")
    run_root = tmp_path / "runs" / "dse"
    ready_manifest = _real_source_flow_run(run_root, candidate_id="cand-ready")
    blocked_manifest = _real_source_flow_run(
        run_root,
        candidate_id="cand-blocked",
        status="blocked_partial_source_flow_run",
        ready_count=7,
        blocked_count=1,
    )
    out_dir = tmp_path / "latest-map"

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_latest_source_flow_map.py",
            "--out",
            str(out_dir),
            "--closure-packet-index",
            str(packet_index),
            "--run-root",
            str(run_root),
            "--quiet",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    discovery = _load(out_dir / "discovery_status.json")
    source_map = _load(out_dir / "source_flow_map.json")
    status = _load(out_dir / "source_flow_map_status.json")
    validation = _load(out_dir / "source_flow_map_validation.json")

    assert discovery["included_run_count"] == 1
    assert discovery["excluded_run_count"] == 1
    assert discovery["source_flow_roots"] == [str(ready_manifest.parent / "source_flows")]
    assert discovery["included_runs"][0]["manifest"] == str(ready_manifest)
    assert discovery["excluded_runs"][0]["manifest"] == str(blocked_manifest)
    assert "run_status_not_source_flows_ready_pending_step5" in discovery[
        "excluded_runs"
    ][0]["blocker_ids"]
    assert "source_flow_ready_count_not_8" in discovery["excluded_runs"][0][
        "blocker_ids"
    ]
    assert discovery["hardware_completion_eligible"] is False
    assert discovery["deliverable_complete"] is False

    assert status["status"] == "passed"
    assert validation["valid"] is True
    assert source_map["unit_count"] == 8
    assert source_map["source_flow_mapped_count"] == 8
    assert source_map["source_flow_missing_count"] == 0
    assert source_map["blocked_unit_count"] == 0
    assert {row["candidate_id"] for row in source_map["flows"]} == {"cand-ready"}
    assert all(
        str(ready_manifest.parent / "source_flows") in row["source_flow_dir"]
        for row in source_map["flows"]
    )
    assert all(
        str(blocked_manifest.parent / "source_flows") not in row["source_flow_dir"]
        for row in source_map["flows"]
    )
    assert source_map["hardware_completion_eligible"] is False
    assert source_map["deliverable_complete"] is False


def test_latest_source_flow_map_cli_candidate_filter_limits_discovery(
    tmp_path: Path,
) -> None:
    packet_index = _packetized_run(tmp_path / "packetized", candidate_id="cand-b")
    run_root = tmp_path / "runs" / "dse"
    _real_source_flow_run(run_root, candidate_id="cand-a")
    cand_b_manifest = _real_source_flow_run(run_root, candidate_id="cand-b")
    out_dir = tmp_path / "latest-map"

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_latest_source_flow_map.py",
            "--out",
            str(out_dir),
            "--closure-packet-index",
            str(packet_index),
            "--run-root",
            str(run_root),
            "--candidate-id",
            "cand-b",
            "--quiet",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    discovery = _load(out_dir / "discovery_status.json")
    source_map = _load(out_dir / "source_flow_map.json")

    assert discovery["candidate_ids"] == ["cand-b"]
    assert discovery["included_run_count"] == 1
    assert discovery["excluded_run_count"] == 1
    assert discovery["included_runs"][0]["manifest"] == str(cand_b_manifest)
    assert discovery["excluded_runs"][0]["blocker_ids"] == [
        "candidate_id_filter_mismatch"
    ]
    assert source_map["unit_count"] == 8
    assert source_map["source_flow_mapped_count"] == 8
    assert source_map["blocked_unit_count"] == 0
    assert {row["candidate_id"] for row in source_map["flows"]} == {"cand-b"}
