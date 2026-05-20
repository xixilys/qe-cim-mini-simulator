#!/usr/bin/env python3
"""DFT hardware closure source-flow map builder tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.reference_workloads.dft_hardware_closure_packets import (
    write_dft_hardware_closure_packets,
)
from dse_v2.reference_workloads.dft_hardware_closure_source_flow_map import (
    DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_SCHEMA,
    validate_dft_hardware_closure_source_flow_map,
    write_dft_hardware_closure_source_flow_map,
)
from dse_v2.reference_workloads.dft_hardware_closure_source_flow_plan import (
    write_dft_hardware_closure_source_flow_plan,
)

STAGES = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)
CANDIDATE_IDS = tuple(f"release-candidate-{index:02d}" for index in range(36))
KERNEL_IDS = tuple(MAJOR_SCF_KERNEL_IDS)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _closure_shards(
    path: Path,
    *,
    candidate_ids: tuple[str, ...] = CANDIDATE_IDS,
    kernel_ids: tuple[str, ...] = KERNEL_IDS,
) -> Path:
    units = []
    for candidate_id in candidate_ids:
        for kernel_id in kernel_ids:
            units.append(
                {
                    "unit_id": f"{candidate_id}:{kernel_id}",
                    "candidate_id": candidate_id,
                    "kernel_id": kernel_id,
                    "kernel_name": kernel_id.replace("_", " "),
                    "kernel_family": "source_flow_map_test",
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
            "release_id": "release-source-flow-map-test",
            "candidate_count": len(candidate_ids),
            "major_kernel_count": len(kernel_ids),
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
                    "candidate_ids": list(candidate_ids),
                    "kernel_ids": list(kernel_ids),
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


def _packetized_run(
    run_dir: Path,
    *,
    candidate_ids: tuple[str, ...] = CANDIDATE_IDS,
    kernel_ids: tuple[str, ...] = KERNEL_IDS,
) -> Path:
    shards_path = _closure_shards(
        run_dir / "dft_hardware_closure_shards.json",
        candidate_ids=candidate_ids,
        kernel_ids=kernel_ids,
    )
    write_dft_hardware_closure_packets(
        run_dir, hardware_closure_shards_path=shards_path
    )
    return run_dir / "dft_hardware_closure_packet_index.json"


def _source_flow(root: Path, *, candidate_id: str, kernel_id: str) -> Path:
    flow_dir = root / candidate_id / kernel_id
    _write_json(
        flow_dir / "manifest.json",
        {
            "schema_version": f"dse.dft_scf.{kernel_id}.rtl_flow.v1",
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "source_files": {"rtl": f"{kernel_id}.v", "testbench": f"tb_{kernel_id}.v"},
            "claim_boundary": "candidate/kernel source-flow fixture for source-flow map tests only",
        },
    )
    (flow_dir / f"{kernel_id}.v").write_text("// rtl fixture\n", encoding="utf-8")
    return flow_dir


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_source_flow_map_enumerates_36x8_packet_units_from_generated_roots_fail_closed(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    source_root = tmp_path / "generated_source_flows"
    for candidate_id in CANDIDATE_IDS:
        for kernel_id in KERNEL_IDS:
            _source_flow(source_root, candidate_id=candidate_id, kernel_id=kernel_id)

    status = write_dft_hardware_closure_source_flow_map(
        run_dir,
        closure_packet_index_path=packet_index,
        source_flow_roots=[source_root],
    )

    assert status["status"] == "passed"
    assert status["map_status"] == "source_flow_map_ready_pending_plan"
    source_map = _load(run_dir / "source_flow_map.json")
    validation = _load(run_dir / "source_flow_map_validation.json")
    assert source_map["schema_version"] == DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_SCHEMA
    assert source_map["unit_count"] == 36 * 8
    assert source_map["source_flow_mapped_count"] == 36 * 8
    assert source_map["source_flow_missing_count"] == 0
    assert source_map["duplicate_unit_count"] == 0
    assert len(source_map["flows"]) == 36 * 8
    assert validation["valid"] is True
    assert source_map["hardware_completion_eligible"] is False
    assert source_map["deliverable_complete"] is False
    assert all(
        row["status"] == "source_flow_mapped_pending_plan"
        for row in source_map["units"]
    )
    assert {(row["candidate_id"], row["kernel_id"]) for row in source_map["flows"]} == {
        (candidate_id, kernel_id)
        for candidate_id in CANDIDATE_IDS
        for kernel_id in KERNEL_IDS
    }

    write_dft_hardware_closure_source_flow_plan(
        run_dir / "plan",
        closure_packet_index_path=packet_index,
        source_flow_map_path=run_dir / "source_flow_map.json",
    )
    plan = _load(run_dir / "plan" / "dft_hardware_closure_source_flow_plan.json")
    assert plan["source_flow_present_count"] == 36 * 8
    assert plan["hardware_completion_eligible"] is False
    assert plan["deliverable_complete"] is False


def test_source_flow_map_detects_missing_duplicate_and_orphan_source_flow_dirs(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_ids = ("cand-a", "cand-b")
    kernel_ids = ("fft_ifft_ffft", "complex_gemm_gemv_tile")
    packet_index = _packetized_run(
        run_dir, candidate_ids=candidate_ids, kernel_ids=kernel_ids
    )
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    _source_flow(root_a, candidate_id="cand-a", kernel_id="fft_ifft_ffft")
    _source_flow(root_b, candidate_id="cand-a", kernel_id="fft_ifft_ffft")
    _source_flow(root_a, candidate_id="not-in-packets", kernel_id="fft_ifft_ffft")

    status = write_dft_hardware_closure_source_flow_map(
        run_dir,
        closure_packet_index_path=packet_index,
        source_flow_roots=[root_a, root_b, tmp_path / "missing-root"],
    )

    assert status["status"] == "passed"
    assert status["map_status"] == "blocked_no_candidate_specific_source_flows"
    source_map = _load(run_dir / "source_flow_map.json")
    validation = _load(run_dir / "source_flow_map_validation.json")
    assert validation["valid"] is True
    assert source_map["unit_count"] == 4
    assert source_map["source_flow_mapped_count"] == 0
    assert source_map["source_flow_missing_count"] == 3
    assert source_map["duplicate_unit_count"] == 1
    assert source_map["blocked_unit_count"] == 4
    assert source_map["root_missing_count"] == 1
    assert source_map["orphan_source_flow_count"] == 1
    duplicate = next(
        row
        for row in source_map["units"]
        if row["candidate_id"] == "cand-a" and row["kernel_id"] == "fft_ifft_ffft"
    )
    assert duplicate["status"] == "blocked_duplicate_source_flow_dirs"
    assert "duplicate_source_flow_dirs_for_unit" in duplicate["blocker_ids"]
    assert len(duplicate["source_flow_candidates"]) == 2
    missing = [
        row
        for row in source_map["units"]
        if row["status"] == "blocked_missing_source_flow_dir"
    ]
    assert len(missing) == 3
    assert source_map["flows"] == []
    assert source_map["hardware_completion_eligible"] is False
    assert source_map["deliverable_complete"] is False


def test_source_flow_map_requires_exact_manifest_candidate_and_kernel_match(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(
        run_dir, candidate_ids=("cand-a",), kernel_ids=("fft_ifft_ffft",)
    )
    source_root = tmp_path / "flows"
    _write_json(
        source_root / "bad-candidate" / "manifest.json",
        {
            "schema_version": "test",
            "candidate_id": "cand-b",
            "kernel_id": "fft_ifft_ffft",
        },
    )
    _write_json(
        source_root / "missing-kernel" / "manifest.json",
        {"schema_version": "test", "candidate_id": "cand-a"},
    )

    write_dft_hardware_closure_source_flow_map(
        run_dir,
        closure_packet_index_path=packet_index,
        source_flow_roots=[source_root],
    )
    source_map = _load(run_dir / "source_flow_map.json")

    assert source_map["source_flow_mapped_count"] == 0
    assert source_map["source_flow_missing_count"] == 1
    assert source_map["invalid_manifest_count"] == 1
    assert source_map["orphan_source_flow_count"] == 1
    assert source_map["units"][0]["status"] == "blocked_missing_source_flow_dir"
    blocker_sets = {
        tuple(row["blocker_ids"]) for row in source_map["discovered_source_flows"]
    }
    assert ("source_flow_not_in_packet_index",) in blocker_sets
    assert ("source_flow_kernel_id_missing",) in blocker_sets


def test_source_flow_map_validator_rejects_claim_upgrade_and_fabricated_mapping(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(
        run_dir, candidate_ids=("cand-a",), kernel_ids=("fft_ifft_ffft",)
    )
    source_root = tmp_path / "flows"
    _source_flow(source_root, candidate_id="cand-a", kernel_id="fft_ifft_ffft")
    write_dft_hardware_closure_source_flow_map(
        run_dir,
        closure_packet_index_path=packet_index,
        source_flow_roots=[source_root],
    )
    source_map = _load(run_dir / "source_flow_map.json")

    upgraded = json.loads(json.dumps(source_map))
    upgraded["hardware_completion_eligible"] = True
    assert validate_dft_hardware_closure_source_flow_map(upgraded)["valid"] is False

    fabricated = json.loads(json.dumps(source_map))
    fabricated["units"][0]["manifest_kernel_id"] = "wrong-kernel"
    assert validate_dft_hardware_closure_source_flow_map(fabricated)["valid"] is False


def test_source_flow_map_cli_writes_map_validation_and_status_artifacts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(
        run_dir, candidate_ids=("cand-a",), kernel_ids=("fft_ifft_ffft",)
    )
    source_root = tmp_path / "flows"
    _source_flow(source_root, candidate_id="cand-a", kernel_id="fft_ifft_ffft")

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_source_flow_map.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(packet_index),
            "--source-flow-root",
            str(source_root),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert (run_dir / "source_flow_map.json").exists()
    assert (run_dir / "source_flow_map_validation.json").exists()
    assert (run_dir / "source_flow_map_status.json").exists()
    status = _load(run_dir / "source_flow_map_status.json")
    assert status["status"] == "passed"
    assert status["hardware_completion_eligible"] is False
    assert status["deliverable_complete"] is False
