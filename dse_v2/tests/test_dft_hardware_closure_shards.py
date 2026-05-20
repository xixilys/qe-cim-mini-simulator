#!/usr/bin/env python3
"""DFT hardware closure shard queue tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_hardware_closure_shards import (
    DFT_HARDWARE_CLOSURE_SHARDS_SCHEMA,
    build_dft_hardware_closure_shard_queue,
    validate_dft_hardware_closure_shard_queue,
    write_dft_hardware_closure_shard_queue,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _workplan(path: Path) -> Path:
    items = []
    for candidate_id in ["cand-a", "cand-b"]:
        for kernel_id in ["fft_ifft_ffft", "kinetic_add"]:
            for stage_id in ["golden_correctness", "hls_or_rtl_sim", "dc_asic_synth_timing_area"]:
                items.append(
                    {
                        "work_item_id": f"{candidate_id}:{kernel_id}:{stage_id}",
                        "candidate_id": candidate_id,
                        "kernel_id": kernel_id,
                        "kernel_name": kernel_id,
                        "kernel_family": "unit_test",
                        "stage_id": stage_id,
                        "tool_id": "dc_shell" if stage_id.startswith("dc") else "vcs",
                        "blocked": True,
                        "shared_microkernel_smoke_stage_passed": stage_id != "dc_asic_synth_timing_area",
                        "candidate_specific_evidence_present": False,
                    }
                )
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_completion_workplan.v1",
            "status": "blocked_temporary",
            "release_id": "release-test",
            "candidate_count": 2,
            "major_kernel_count": 2,
            "work_items": items,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )


def test_closure_shards_group_candidate_kernel_units_fail_closed(tmp_path: Path) -> None:
    workplan_path = _workplan(tmp_path / "dft_hardware_completion_workplan.json")

    status = write_dft_hardware_closure_shard_queue(
        tmp_path / "shards",
        hardware_completion_workplan_path=workplan_path,
        max_units_per_shard=2,
    )

    assert status["status"] == "passed"
    payload = json.loads((tmp_path / "shards" / "dft_hardware_closure_shards.json").read_text())
    validation = json.loads((tmp_path / "shards" / "dft_hardware_closure_shards_validation.json").read_text())
    assert payload["schema_version"] == DFT_HARDWARE_CLOSURE_SHARDS_SCHEMA
    assert payload["unit_count"] == 4
    assert payload["shard_count"] == 2
    assert payload["work_item_count"] == 12
    assert payload["blocked_work_item_count"] == 12
    assert payload["candidate_specific_bundle_count"] == 0
    assert payload["hardware_completion_eligible"] is False
    assert validation["valid"] is True
    assert all(unit["candidate_specific_bundle_required"] for shard in payload["shards"] for unit in shard["units"])


def test_closure_shard_validator_rejects_claim_upgrade_and_fabricated_bundle(tmp_path: Path) -> None:
    payload = build_dft_hardware_closure_shard_queue(
        hardware_completion_workplan_path=_workplan(tmp_path / "dft_hardware_completion_workplan.json"),
        max_units_per_shard=8,
    )

    fabricated = json.loads(json.dumps(payload))
    fabricated["shards"][0]["candidate_specific_bundle_count"] = 1
    fabricated["shards"][0]["units"][0]["candidate_specific_bundle_ref"] = "fake.json"
    assert validate_dft_hardware_closure_shard_queue(fabricated)["valid"] is False

    upgraded = json.loads(json.dumps(payload))
    upgraded["hardware_completion_eligible"] = True
    upgraded["deliverable_complete"] = True
    assert validate_dft_hardware_closure_shard_queue(upgraded)["valid"] is False


def test_build_closure_shards_cli_writes_artifacts(tmp_path: Path) -> None:
    workplan_path = _workplan(tmp_path / "dft_hardware_completion_workplan.json")
    out_dir = tmp_path / "cli_shards"

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_shards.py",
            "--out",
            str(out_dir),
            "--hardware-completion-workplan",
            str(workplan_path),
            "--max-units-per-shard",
            "2",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert (out_dir / "dft_hardware_closure_shards.json").exists()
    assert json.loads((out_dir / "dft_hardware_closure_shards_validation.json").read_text())["valid"] is True
