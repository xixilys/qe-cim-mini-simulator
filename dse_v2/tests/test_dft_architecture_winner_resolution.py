#!/usr/bin/env python3
"""DFT architecture winner-resolution tests."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.reference_workloads.dft_architecture_winner_resolution import (
    DFT_ARCHITECTURE_WINNER_RESOLUTION_SCHEMA,
    build_dft_architecture_winner_resolution,
    validate_dft_architecture_winner_resolution,
    write_dft_architecture_winner_resolution,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _row(candidate_id: str, *, rank: int, lut: int, area: float) -> dict:
    return {
        "candidate_id": candidate_id,
        "design_candidate_id": f"design-{candidate_id}",
        "identity_assignments": {
            "hardware_microarchitecture": "host_fpga_minimal_v0",
            "mapping_data_layout": "fft_grid_hbm_tiled",
        },
        "non_identity_assignments": {
            "dft_phase_hotspot_selection": "scf_hpsi_density",
            "evidence_fidelity_promotion_policy": "systemc_gem5_eda_formal_ladder",
        },
        "rank": rank,
        "tie_key": [lut, 2, 1, 12],
        "fpga_total_slice_luts": lut,
        "fpga_total_dsps": 2,
        "fpga_total_block_ram_tiles": 1,
        "fpga_total_bonded_iob": 12,
        "vivado_route_completed_kernel_count": 8,
        "asic_total_cell_area": area,
        "asic_min_slack_ns": 0.5,
        "asic_slack_deficit_ns": 0.0,
        "dc_real_target_library_kernel_count": 8,
        "kernel_count": 8,
    }


def _seed_ppa(run_dir: Path, *, tied: bool) -> None:
    if tied:
        fpga_rows = [_row("cand-a", rank=1, lut=100, area=1000.0), _row("cand-b", rank=1, lut=100, area=1000.0)]
        asic_rows = [_row("cand-a", rank=1, lut=100, area=1000.0), _row("cand-b", rank=1, lut=100, area=1000.0)]
        status = "trusted_hardware_ppa_ranking_tied"
        winner_status = "tied_by_identical_kernel_ppa_no_single_winner"
    else:
        fpga_rows = [_row("cand-a", rank=1, lut=100, area=1000.0), _row("cand-b", rank=2, lut=200, area=2000.0)]
        asic_rows = [_row("cand-a", rank=1, lut=100, area=1000.0), _row("cand-b", rank=2, lut=200, area=2000.0)]
        status = "trusted_hardware_ppa_ranking_available"
        winner_status = "ranked_candidates_available"
    _write_json(
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "status": status,
            "release_id": "release-winner-test",
            "candidate_count": 2,
            "ranking_eligible_candidate_count": 2,
            "hardware_completion_eligible": True,
            "winner_selection_status": winner_status,
            "all_candidates_metric_tied": tied,
            "metric_signature_count": 1 if tied else 2,
            "fpga_ranking": fpga_rows,
            "asic_ranking": asic_rows,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_validation.json",
        {"schema_version": "dse.dft.hardware_ppa_ranking_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_status.json",
        {"schema_version": "dse.dft.hardware_ppa_ranking_status.v1", "status": "passed"},
    )


def _seed_provenance(run_dir: Path, *, eligible: bool) -> None:
    _write_json(
        run_dir / "dft_candidate_specific_ppa_provenance_audit.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_provenance_audit.v1",
            "status": (
                "trusted_candidate_specific_ppa_provenance"
                if eligible
                else "blocked_candidate_specific_ppa_provenance"
            ),
            "winner_provenance_eligible": eligible,
            "unit_count": 16,
            "trusted_unit_count": 16 if eligible else 0,
            "blocked_unit_count": 0 if eligible else 16,
            "blocker_count": 0 if eligible else 16,
            "blocker_id_counts": {} if eligible else {"commands_not_executed": 16},
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_candidate_specific_ppa_provenance_audit_validation.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_provenance_audit_validation.v1",
            "valid": True,
            "errors": [],
        },
    )
    _write_json(
        run_dir / "dft_hardware_tie_breaker_execution_queue.json",
        {
            "schema_version": "dse.dft.hardware_tie_breaker_execution_queue.v1",
            "work_item_count": 0 if eligible else 80,
        },
    )


def test_winner_resolution_rejects_identical_ppa_tie(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ppa(run_dir, tied=True)
    _seed_provenance(run_dir, eligible=False)

    status = write_dft_architecture_winner_resolution(run_dir)
    payload = json.loads((run_dir / "dft_architecture_winner_resolution.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "dft_architecture_winner_resolution_validation.json").read_text(encoding="utf-8"))

    assert status["status"] == "passed"
    assert payload["schema_version"] == DFT_ARCHITECTURE_WINNER_RESOLUTION_SCHEMA
    assert payload["status"] == "blocked_no_unique_hardware_ppa_winners"
    assert payload["hardware_winner_resolution_eligible"] is False
    assert payload["fpga_best_architecture"] is None
    assert payload["asic_best_architecture"] is None
    assert payload["deployments"]["fpga"]["top_rank_candidate_count"] == 2
    assert payload["deployments"]["fpga"]["required_next_evidence"]
    assert "candidate-id deterministic tie order" in payload["deployments"]["fpga"]["required_next_evidence"][0]["forbidden_shortcuts"]
    assert validation["valid"] is True


def test_winner_resolution_accepts_unique_fpga_and_asic_rank_one_without_completion_claim(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ppa(run_dir, tied=False)
    _seed_provenance(run_dir, eligible=True)

    payload = build_dft_architecture_winner_resolution(run_dir)
    validation = validate_dft_architecture_winner_resolution(payload)

    assert payload["status"] == "resolved_hardware_ppa_deployment_winners"
    assert payload["hardware_winner_resolution_eligible"] is True
    assert payload["fpga_best_architecture"]["candidate_id"] == "cand-a"
    assert payload["asic_best_architecture"]["candidate_id"] == "cand-a"
    assert payload["trusted_best_architecture_claim_eligible"] is False
    assert payload["deliverable_complete"] is False
    assert validation["valid"] is True
