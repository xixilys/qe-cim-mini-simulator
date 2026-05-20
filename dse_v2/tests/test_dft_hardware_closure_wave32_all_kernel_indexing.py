#!/usr/bin/env python3
"""Regression tests for Wave32 all-kernel DFT hardware closure indexing."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.reference_workloads.dft_hardware_closure_bundle import write_dft_hardware_closure_candidate_bundles
from dse_v2.reference_workloads.dft_hardware_closure_packets import write_dft_hardware_closure_packets
from dse_v2.reference_workloads.dft_hardware_closure_raw_stage_materialization import (
    validate_dft_hardware_closure_raw_stage_materialization,
    write_dft_hardware_closure_raw_stage_materialization,
)
from dse_v2.reference_workloads.dft_hardware_closure_shards import write_dft_hardware_closure_shard_queue
from dse_v2.reference_workloads.dft_hardware_closure_unit_provenance import (
    write_dft_hardware_closure_unit_provenance,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts

_WAVE32_CANDIDATE_ID = "wave32-candidate-a"
_WAVE32_KERNEL_IDS = (
    "fft_ifft_ffft",
    "transpose_layout",
    "hpsi_local_potential",
    "nonlocal_projector",
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _wave32_all_kernel_workplan(path: Path) -> Path:
    work_items = [
        {
            "work_item_id": f"{_WAVE32_CANDIDATE_ID}:{kernel_id}:golden_correctness",
            "candidate_id": _WAVE32_CANDIDATE_ID,
            "kernel_id": kernel_id,
            "kernel_name": kernel_id.replace("_", " "),
            "kernel_family": "wave32_all_kernel_regression",
            "stage_id": "golden_correctness",
            "tool_id": "python3",
            "blocked": True,
            "shared_microkernel_smoke_stage_passed": False,
            "candidate_specific_evidence_present": False,
        }
        for kernel_id in _WAVE32_KERNEL_IDS
    ]
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_completion_workplan.v1",
            "status": "blocked_wave32_all_kernel_regression",
            "release_id": "release-wave32-all-kernel-indexing-regression",
            "candidate_count": 1,
            "major_kernel_count": len(_WAVE32_KERNEL_IDS),
            "work_items": work_items,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )


def _source_flow(path: Path) -> Path:
    _write_json(
        path / "golden_correctness.json",
        {
            "schema_version": "dse.dft.kernel_golden_correctness.v1",
            "status": "passed",
            "inputs": {"fixture": "wave32-all-kernel-indexing"},
            "expected": {"stable": True},
        },
    )
    _write_json(path / "manifest.json", {"fixture": "wave32-all-kernel-indexing"})
    return path


def _materialized_kernel_ids(run_dir: Path) -> set[str]:
    payload = json.loads((run_dir / "dft_hardware_closure_raw_stage_materialization.json").read_text())
    return {row["kernel_id"] for row in payload["units"]}


def test_repeated_raw_materialization_preserves_all_wave32_candidate_kernel_units(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    source_flow_dir = _source_flow(tmp_path / "source_flow")
    workplan_path = _wave32_all_kernel_workplan(run_dir / "dft_hardware_completion_workplan.json")

    write_dft_hardware_closure_shard_queue(
        run_dir,
        hardware_completion_workplan_path=workplan_path,
        max_units_per_shard=2,
    )
    write_dft_hardware_closure_packets(
        run_dir,
        hardware_closure_shards_path=run_dir / "dft_hardware_closure_shards.json",
    )
    packet_index_path = run_dir / "dft_hardware_closure_packet_index.json"
    write_dft_hardware_closure_candidate_bundles(
        run_dir,
        closure_packet_index_path=packet_index_path,
        evidence_root=run_dir,
    )
    write_dft_hardware_closure_unit_provenance(
        run_dir,
        closure_packet_index_path=packet_index_path,
        evidence_root=run_dir,
        candidate_ids=[_WAVE32_CANDIDATE_ID],
    )

    first_status = write_dft_hardware_closure_raw_stage_materialization(
        run_dir,
        closure_packet_index_path=packet_index_path,
        source_flow_dir=source_flow_dir,
        evidence_root=run_dir,
        candidate_ids=[_WAVE32_CANDIDATE_ID],
    )
    first_kernel_ids = _materialized_kernel_ids(run_dir)

    second_status = write_dft_hardware_closure_raw_stage_materialization(
        run_dir,
        closure_packet_index_path=packet_index_path,
        source_flow_dir=source_flow_dir,
        evidence_root=run_dir,
        candidate_ids=[_WAVE32_CANDIDATE_ID],
    )
    materialization = json.loads((run_dir / "dft_hardware_closure_raw_stage_materialization.json").read_text())

    assert first_status["status"] == "passed"
    assert second_status["status"] == "passed"
    assert first_status["unit_count"] == len(_WAVE32_KERNEL_IDS)
    assert second_status["unit_count"] == len(_WAVE32_KERNEL_IDS)
    assert first_kernel_ids == set(_WAVE32_KERNEL_IDS)
    assert _materialized_kernel_ids(run_dir) == set(_WAVE32_KERNEL_IDS)
    assert materialization["materialized_unit_count"] == len(_WAVE32_KERNEL_IDS)
    assert materialization["materialized_file_count"] == 3 * len(_WAVE32_KERNEL_IDS)
    assert materialization["major_kernel_count"] == len(_WAVE32_KERNEL_IDS)
    assert validate_dft_hardware_closure_raw_stage_materialization(materialization)["valid"] is True
    assert all(row["candidate_id"] == _WAVE32_CANDIDATE_ID for row in materialization["units"])
    assert all(row["materialized_file_count"] == 3 for row in materialization["units"])

    for kernel_id in _WAVE32_KERNEL_IDS:
        unit_dir = run_dir / "candidate_specific_evidence" / _WAVE32_CANDIDATE_ID / kernel_id
        assert (unit_dir / "golden_correctness_report.json").exists()
        assert (unit_dir / "golden_reference_trace.json").exists()
        assert (unit_dir / "candidate_input_manifest.json").exists()

    _write_json(run_dir / "verdict.json", {"run_id": "wave32-all-kernel-indexing", "backend": "systemc"})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])
    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    section = report["dft_hardware_closure_raw_stage_materialization"]

    assert section["status"] == "fail_closed_hardware_closure_raw_stage_materialization_present"
    assert section["unit_count"] == len(_WAVE32_KERNEL_IDS)
    assert section["unit_ref_count"] == len(_WAVE32_KERNEL_IDS)
    assert {row["kernel_id"] for row in section["unit_refs"]} == set(_WAVE32_KERNEL_IDS)
    assert {row["candidate_id"] for row in section["unit_refs"]} == {_WAVE32_CANDIDATE_ID}
