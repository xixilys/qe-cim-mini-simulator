#!/usr/bin/env python3
"""Run2 target JSON consumer and candidate×kernel×target gate tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dse_v2.reference_workloads.dft_candidate_workflow_target_evidence_gate_ledger import (
    build_dft_candidate_workflow_target_evidence_gate_ledger,
    validate_dft_candidate_workflow_target_evidence_gate_ledger,
)
from dse_v2.reference_workloads.dft_hardware_deployment_target_selection import (
    build_dft_hardware_deployment_target_selection,
    validate_dft_hardware_deployment_target_selection,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fresh_ref(path: Path) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"raw source for {path.name}\n", encoding="utf-8")
    return {
        "path": str(path),
        "exists": True,
        "status": "present_hash_valid",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "hash_algorithm": "sha256",
    }


def test_hash_backed_target_jsons_are_consumed_as_planning_context_only(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    fpga_ref = _fresh_ref(run_dir / "raw" / "fpga_capacity_raw.json")
    asic_ref = _fresh_ref(run_dir / "raw" / "asic_target_library_raw.json")
    fpga_path = _write_json(
        run_dir / "fpga_target_catalog.json",
        {
            "schema_version": "dse.dft.fpga_target_catalog.v1",
            "status": "passed",
            "source_refs": [fpga_ref],
            "targets": [
                {
                    "status": "available",
                    "target_device_id": "xc7a35t-live-capacity",
                    "vendor": "xilinx",
                    "part": "xc7a35tcpg236-1",
                    "family": "Artix-7",
                    "capacity": {"slice_luts": 20800, "dsps": 90, "block_ram_tiles": 50},
                    "source_refs": [fpga_ref],
                }
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    asic_path = _write_json(
        run_dir / "asic_target_library_probe.json",
        {
            "schema_version": "dse.dft.asic_target_library_probe.v1",
            "status": "passed",
            "source_refs": [asic_ref],
            "target_libraries": [
                {
                    "target_library_id": "lsi_10k",
                    "process_node": "library_defined_unknown",
                    "pvt_corner": "library_defined_unknown",
                    "discovery_status": "real_target_library_present",
                    "source_refs": [asic_ref],
                }
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    payload = build_dft_hardware_deployment_target_selection(
        run_dir,
        fpga_target_catalog_path=fpga_path,
        asic_target_library_probe_path=asic_path,
    )
    validation = validate_dft_hardware_deployment_target_selection(payload)

    assert validation["valid"] is True
    assert payload["deployment_target_selection_ready"] is True
    assert payload["deployments"]["fpga"]["part"] == "xc7a35tcpg236-1"
    assert payload["deployments"]["asic"]["target_library_id"] == "lsi_10k"
    assert payload["hardware_completion_eligible"] is False
    assert payload["deliverable_complete"] is False
    assert payload["can_name_final_recommendation"] is False


def _matrix_row(candidate_id: str, target: str, gate_id: str) -> dict[str, object]:
    return {
        "row_id": f"matrix::{candidate_id}::{target}::{gate_id}",
        "candidate_id": candidate_id,
        "workflow_case_id": "qe_full_scf_case_0",
        "deployment_boundary_id": "full_scf_evaluated_hybrid",
        "target_platform_id": f"{target}_target_v1",
        "target_platform_kind": target,
        "status": "blocked_missing_input",
        "status_reason": "Step2 row requires target-specific hard-gate evidence",
        "workflow_case": {"workflow_case_id": "qe_full_scf_case_0"},
        "deployment_boundary": {"deployment_boundary_id": "full_scf_evaluated_hybrid"},
        "target_platform": {"target_platform_id": f"{target}_target_v1", "platform_kind": target},
        "evidence_gate_id": gate_id,
        "evidence_gate": {"evidence_gate_id": gate_id, "applies_to_target_platform_kinds": [target]},
    }


def test_candidate_workflow_target_ledger_expands_bound_kernel_contexts_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    matrix_path = _write_json(
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        {
            "schema_version": "unit-test.matrix.v1",
            "release_id": "run2-test-release",
            "rows": [
                _matrix_row("cand-fpga", "fpga", "golden_correctness"),
                _matrix_row("cand-fpga", "fpga", "hls_or_rtl_simulation"),
                _matrix_row("cand-fpga", "fpga", "hls_or_rtl_synthesis"),
                _matrix_row("cand-fpga", "fpga", "vivado_synthesis_or_implementation"),
                _matrix_row("cand-asic", "asic", "golden_correctness"),
                _matrix_row("cand-asic", "asic", "hls_or_rtl_simulation"),
                _matrix_row("cand-asic", "asic", "hls_or_rtl_synthesis"),
                _matrix_row("cand-asic", "asic", "dc_synthesis_timing_area"),
            ],
            "deliverable_complete": False,
        },
    )
    context_path = _write_json(
        run_dir / "candidate_kernel_context_index_for_gate_ledger.json",
        {
            "schema_version": "dse.dft.candidate_kernel_context_index_for_gate_ledger.v1",
            "status": "kernel_context_index_only_not_candidate_specific_execution",
            "units": [
                {"candidate_id": "cand-fpga", "kernel_id": "fft_ifft_ffft", "stage_results": []},
                {"candidate_id": "cand-asic", "kernel_id": "fft_ifft_ffft", "stage_results": []},
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=matrix_path,
        candidate_specific_ppa_execution_path=context_path,
    )
    validation = validate_dft_candidate_workflow_target_evidence_gate_ledger(ledger)

    assert validation["valid"] is True
    assert ledger["row_count"] == 8
    assert ledger["candidate_kernel_axis_unbound_row_count"] == 0
    assert ledger["row_counts_by_target_platform_kind"] == {"asic": 4, "fpga": 4}
    assert ledger["status_counts"] == {"blocked_missing_input": 8}
    assert ledger["stable_blocker_reason_counts"] == {"missing_target_specific_gate_evidence": 8}
    assert ledger["hardware_completion_eligible"] is False
    assert ledger["deliverable_complete"] is False
    fpga_gates = {row["evidence_gate_id"] for row in ledger["rows"] if row["target_platform_kind"] == "fpga"}
    asic_gates = {row["evidence_gate_id"] for row in ledger["rows"] if row["target_platform_kind"] == "asic"}
    assert fpga_gates == {"golden_correctness", "hls_or_rtl_sim", "hls_or_rtl_synth", "vivado_fpga_synth_or_impl"}
    assert asic_gates == {"golden_correctness", "hls_or_rtl_sim", "hls_or_rtl_synth", "dc_asic_synth_timing_area"}
