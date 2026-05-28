#!/usr/bin/env python3
"""Release-gate missing-input matrix tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_hardware_closure_release_gate_input_matrix import (
    DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_SCHEMA,
    DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_STATUS_SCHEMA,
    build_dft_hardware_closure_release_gate_input_matrix,
    validate_dft_hardware_closure_release_gate_input_matrix,
    write_dft_hardware_closure_release_gate_input_matrix,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_release_gate_input_matrix_records_missing_required_inputs(tmp_path: Path) -> None:
    matrix = build_dft_hardware_closure_release_gate_input_matrix(tmp_path)
    validation = validate_dft_hardware_closure_release_gate_input_matrix(matrix)

    assert matrix["schema_version"] == DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_SCHEMA
    assert matrix["status"] == "blocked_missing_release_gate_inputs"
    assert matrix["release_gate_buildable"] is False
    assert "missing_gate_adjudication" in matrix["blocker_ids"]
    assert "missing_parsed_evidence_manifest" in matrix["blocker_ids"]
    assert matrix["deliverable_complete"] is False
    assert validation["valid"] is True


def test_release_gate_input_matrix_binds_slot2_target_jsons_without_upgrading(tmp_path: Path) -> None:
    slot2 = tmp_path / "slot2"
    fpga = _write_json(slot2 / "fpga_target_catalog.json", {"schema_version": "x", "deliverable_complete": False})
    asic = _write_json(slot2 / "asic_target_library_probe.json", {"schema_version": "y", "deliverable_complete": False})
    _write_json(tmp_path / "dft_hardware_closure_gate_adjudication.json", {"schema_version": "gate"})

    status = write_dft_hardware_closure_release_gate_input_matrix(
        tmp_path,
        slot2_target_input_dir=slot2,
    )
    matrix = json.loads((tmp_path / "dft_hardware_closure_release_gate_input_matrix.json").read_text(encoding="utf-8"))

    assert status["schema_version"] == DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_STATUS_SCHEMA
    assert status["status"] == "passed"
    assert matrix["source_artifacts"]["slot2_fpga_target_catalog"]["path"] == str(fpga)
    assert matrix["source_artifacts"]["slot2_asic_target_library_probe"]["path"] == str(asic)
    assert matrix["target_source_inputs_bound"] is True
    assert matrix["release_gate_buildable"] is True
    assert matrix["hardware_completion_eligible"] is False
    assert matrix["deliverable_complete"] is False


def test_release_gate_input_matrix_binds_slot2_target_consumer_artifacts_without_upgrading(tmp_path: Path) -> None:
    slot2 = tmp_path / "slot2_consumer"
    ledger = _write_json(
        slot2 / "dft_candidate_workflow_target_evidence_gate_ledger.json",
        {
            "schema_version": "dse.dft.candidate_workflow_target_evidence_gate_ledger.v1",
            "row_count": 12,
            "blocked_row_count": 12,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    ledger_status = _write_json(
        slot2 / "dft_candidate_workflow_target_evidence_gate_ledger_status.json",
        {
            "schema_version": "dse.dft.candidate_workflow_target_evidence_gate_ledger_status.v1",
            "status": "passed",
            "row_count": 12,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    worklist = _write_json(
        slot2 / "candidate_kernel_target_ppa_gate_worklist.json",
        {
            "schema_version": "dse.dft.run2.candidate_kernel_target_ppa_gate_worklist.v1",
            "status": "recorded_fail_closed_worklist",
            "worklist_hash": "abc123",
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    release_gate = _write_json(
        slot2 / "dft_hardware_closure_release_gate.json",
        {
            "schema_version": "dse.dft.hardware_closure_release_gate.v1",
            "status": "failed_empty_gate_adjudication",
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    release_gate_validation = _write_json(
        slot2 / "dft_hardware_closure_release_gate_validation.json",
        {
            "schema_version": "dse.dft.hardware_closure_release_gate_validation.v1",
            "valid": False,
            "errors": [{"field": "candidate_count", "message": "candidate_count must be positive"}],
        },
    )

    matrix = build_dft_hardware_closure_release_gate_input_matrix(
        tmp_path,
        slot2_target_consumer_run_dir=slot2,
    )
    validation = validate_dft_hardware_closure_release_gate_input_matrix(matrix)

    assert validation["valid"] is True
    assert matrix["target_consumer_inputs_bound"] is True
    assert matrix["release_gate_buildable"] is False
    assert matrix["hardware_completion_eligible"] is False
    assert matrix["deliverable_complete"] is False
    assert matrix["source_artifacts"]["slot2_candidate_workflow_target_evidence_gate_ledger"]["path"] == str(
        ledger
    )
    assert matrix["source_artifacts"]["slot2_candidate_workflow_target_evidence_gate_ledger_status"]["path"] == str(
        ledger_status
    )
    assert matrix["source_artifacts"]["slot2_candidate_kernel_target_ppa_gate_worklist"]["path"] == str(worklist)
    assert matrix["source_artifacts"]["slot2_hardware_closure_release_gate"]["path"] == str(release_gate)
    assert matrix["source_artifacts"]["slot2_hardware_closure_release_gate_validation"]["path"] == str(
        release_gate_validation
    )
    assert matrix["target_consumer_summary"]["ledger_row_count"] == 12
    assert matrix["target_consumer_summary"]["release_gate_status"] == "failed_empty_gate_adjudication"
    assert matrix["target_consumer_summary"]["release_gate_validation_valid"] is False
    assert "slot2_target_consumer_release_gate_not_valid" in matrix["blocker_ids"]


def test_release_gate_input_matrix_cli_writes_expected_files(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_release_gate_input_matrix.py",
            "--run-dir",
            str(tmp_path),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert (tmp_path / "dft_hardware_closure_release_gate_input_matrix.json").is_file()
