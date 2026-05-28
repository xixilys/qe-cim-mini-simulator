#!/usr/bin/env python3
"""DFT deployment-comparator artifact tests."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.codesign.complete_dse_search_space import build_release_subset_manifest
from dse_v2.reference_workloads.dft_deployment_comparator import (
    DFT_DEPLOYMENT_COMPARATOR_SCHEMA,
    build_dft_deployment_comparator,
    validate_dft_deployment_comparator,
    write_dft_deployment_comparator,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_release_subset(run_dir: Path) -> dict:
    subset = build_release_subset_manifest()
    _write_json(run_dir / "release_subset_manifest.json", subset)
    return subset


def _candidate_ids_by_target(subset: dict) -> dict[str, list[str]]:
    by_target = {"fpga": [], "asic": []}
    for candidate in subset["candidates"]:
        if candidate.get("legal") is not True:
            continue
        target = candidate["identity"]["identity_layers"]["target_platform_parameters"][
            "platform_kind"
        ]
        if target in by_target:
            by_target[target].append(candidate["candidate_id"])
    return by_target


def _fpga_row(candidate_id: str, *, rank: int, registers: int) -> dict:
    return {
        "candidate_id": candidate_id,
        "design_candidate_id": candidate_id,
        "target": "fpga",
        "rank": rank,
        "tie_key": [1901.0, float(registers), 23.0, 0.0, 841.0, -0.093],
        "identity_assignments": {
            "architecture_id": candidate_id.split("::", 1)[0],
            "hardware_target": "fpga",
        },
        "required_stage_ids": [
            "golden_correctness",
            "hls_or_rtl_sim",
            "hls_or_rtl_synth",
            "vivado_fpga_synth_or_impl",
        ],
        "fpga_total_slice_luts": 1901,
        "fpga_total_slice_registers": registers,
        "fpga_total_dsps": 23,
        "fpga_total_block_ram_tiles": 0,
        "fpga_total_bonded_iob": 841,
        "fpga_min_wns_ns": 0.093,
        "vivado_route_completed_kernel_count": 8,
        "kernel_count": 8,
    }


def _asic_row(candidate_id: str, *, rank: int = 1, area: float = 726984.724724) -> dict:
    return {
        "candidate_id": candidate_id,
        "design_candidate_id": candidate_id,
        "target": "asic",
        "rank": rank,
        "tie_key": [area, -0.0],
        "identity_assignments": {
            "architecture_id": candidate_id.split("::", 1)[0],
            "hardware_target": "asic",
        },
        "required_stage_ids": [
            "golden_correctness",
            "hls_or_rtl_sim",
            "hls_or_rtl_synth",
            "dc_asic_synth_timing_area",
        ],
        "asic_total_cell_area": area,
        "asic_min_slack_ns": 0.0,
        "asic_slack_deficit_ns": 0.0,
        "dc_real_target_library_kernel_count": 8,
        "kernel_count": 8,
    }


def _seed_comparator_inputs(run_dir: Path) -> dict[str, object]:
    subset = _write_release_subset(run_dir)
    by_target = _candidate_ids_by_target(subset)
    fpga_ids = by_target["fpga"]
    asic_ids = by_target["asic"]
    fpga_rows = [
        _fpga_row(
            candidate_id,
            rank=1 if index < 2 else index + 1,
            registers=1152 if index < 2 else 1152 + index,
        )
        for index, candidate_id in enumerate(fpga_ids)
    ]
    asic_rows = [
        _asic_row(
            candidate_id,
            rank=1 if index == 0 else index + 1,
            area=726984.724724 + index,
        )
        for index, candidate_id in enumerate(asic_ids)
    ]
    _write_json(
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "status": "trusted_hardware_ppa_ranking_available",
            "release_id": subset["release_id"],
            "release_subset_hash": subset["release_subset_hash"],
            "candidate_count": subset["legal_candidate_count"],
            "ranking_eligible_candidate_count": subset["legal_candidate_count"],
            "hardware_completion_eligible": True,
            "winner_selection_status": "ranked_candidates_available",
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
        run_dir / "dft_candidate_specific_ppa_provenance_audit.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_provenance_audit.v1",
            "status": "trusted_candidate_specific_ppa_provenance",
            "winner_provenance_eligible": True,
            "blocker_count": 0,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution.v1",
            "status": "blocked_no_unique_hardware_ppa_winners",
            "deliverable_complete": False,
        },
    )
    return {
        "subset": subset,
        "fpga_top_ids": fpga_ids[:2],
        "asic_top_id": asic_ids[0],
    }


def test_deployment_comparator_reports_fpga_tie_set_and_unique_asic_winner(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    seeded = _seed_comparator_inputs(run_dir)

    status = write_dft_deployment_comparator(run_dir)
    comparator = json.loads((run_dir / "dft_deployment_comparator.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "dft_deployment_comparator_validation.json").read_text(encoding="utf-8"))

    assert status["status"] == "passed"
    assert comparator["schema_version"] == DFT_DEPLOYMENT_COMPARATOR_SCHEMA
    assert comparator["status"] == "partial_recommendation_available"
    assert comparator["fpga_recommendation"]["recommendation_kind"] == "best_physical_tie_set"
    assert comparator["fpga_recommendation"]["unique_winner"] is None
    assert comparator["fpga_recommendation"]["top_candidate_ids"] == seeded["fpga_top_ids"]
    assert comparator["asic_recommendation"]["recommendation_kind"] == "unique_candidate"
    assert comparator["asic_recommendation"]["unique_winner"]["candidate_id"] == seeded["asic_top_id"]
    asic_provenance = comparator["asic_recommendation"]["unique_winner"][
        "release_universe_provenance"
    ]
    assert asic_provenance["legal"] is True
    assert asic_provenance["deployment_boundary_id"]
    assert asic_provenance["target_platform_kind"] == "asic"
    assert asic_provenance["search_policy_provenance"]["generation_source"]
    assert asic_provenance["search_policy_provenance"]["pruning_rationale_hash"]
    assert comparator["release_universe_binding"]["valid"] is True
    assert comparator["release_universe_binding"]["release_subset_hash"] == seeded["subset"][
        "release_subset_hash"
    ]
    assert comparator["target_recommendation_available_count"] == 2
    assert comparator["cross_target_comparison_eligible"] is True
    assert comparator["hardware_completion_eligible_for_deployment_comparison"] is True
    assert comparator["cross_target_recommendation"]["single_cross_target_winner"] is None
    assert comparator["cross_target_recommendation"]["objective_required"] is True
    assert comparator["non_physical_tie_breakers_used"] is False
    assert "step2_design_score" in comparator["forbidden_tie_breakers"]
    assert comparator["deliverable_complete"] is False
    assert validation["valid"] is True


def test_deployment_comparator_distinguishes_one_sided_recommendation_from_cross_target_comparison(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _seed_comparator_inputs(run_dir)
    ranking = json.loads((run_dir / "dft_hardware_ppa_ranking.json").read_text(encoding="utf-8"))
    ranking["fpga_ranking"] = []
    _write_json(run_dir / "dft_hardware_ppa_ranking.json", ranking)

    comparator = build_dft_deployment_comparator(run_dir)
    validation = validate_dft_deployment_comparator(comparator)

    assert comparator["status"] == "partial_recommendation_available"
    assert comparator["fpga_recommendation"]["recommendation_kind"] == "blocked"
    assert comparator["asic_recommendation"]["recommendation_kind"] == "unique_candidate"
    assert comparator["target_recommendation_available_count"] == 1
    assert comparator["cross_target_comparison_eligible"] is False
    assert comparator["hardware_completion_eligible_for_deployment_comparison"] is False
    assert validation["valid"] is True


def test_deployment_comparator_validation_rejects_collapsed_physical_tie(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _seed_comparator_inputs(run_dir)
    comparator = build_dft_deployment_comparator(run_dir)
    comparator["fpga_recommendation"]["unique_winner"] = comparator["fpga_recommendation"]["top_candidates"][0]

    validation = validate_dft_deployment_comparator(comparator)

    assert validation["valid"] is False
    assert "fpga_physical_tie_must_not_have_unique_winner" in validation["errors"]


def test_deployment_comparator_validation_rejects_inconsistent_cross_target_eligibility(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _seed_comparator_inputs(run_dir)
    ranking = json.loads((run_dir / "dft_hardware_ppa_ranking.json").read_text(encoding="utf-8"))
    ranking["fpga_ranking"] = []
    _write_json(run_dir / "dft_hardware_ppa_ranking.json", ranking)
    comparator = build_dft_deployment_comparator(run_dir)
    comparator["target_recommendation_available_count"] = 1
    comparator["cross_target_comparison_eligible"] = True
    comparator["hardware_completion_eligible_for_deployment_comparison"] = True

    validation = validate_dft_deployment_comparator(comparator)

    assert validation["valid"] is False
    assert "cross_target_comparison_eligible_mismatch" in validation["errors"]
    assert "deployment_comparison_hardware_completion_eligibility_mismatch" in validation["errors"]


def test_deployment_comparator_blocks_manual_candidates_not_in_release_universe(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _seed_comparator_inputs(run_dir)
    ranking = json.loads((run_dir / "dft_hardware_ppa_ranking.json").read_text(encoding="utf-8"))
    ranking["fpga_ranking"] = [_fpga_row("manual-fpga-fixed-seed", rank=1, registers=1)]
    ranking["asic_ranking"] = [_asic_row("manual-asic-fixed-seed")]
    _write_json(run_dir / "dft_hardware_ppa_ranking.json", ranking)

    comparator = build_dft_deployment_comparator(run_dir)
    validation = validate_dft_deployment_comparator(comparator)

    assert comparator["status"] == "blocked_no_deployment_recommendations"
    assert comparator["release_universe_binding"]["valid"] is False
    blocker_ids = {
        blocker["blocker_id"]
        for blocker in comparator["release_universe_binding"]["blockers"]
    }
    assert "fpga_ranking_row_candidate_not_in_release_universe" in blocker_ids
    assert "asic_ranking_row_candidate_not_in_release_universe" in blocker_ids
    assert comparator["fpga_recommendation"]["recommendation_kind"] == "blocked"
    assert comparator["asic_recommendation"]["recommendation_kind"] == "blocked"
    assert validation["valid"] is True


def test_deployment_comparator_blocks_top_k_rows_missing_release_universe_targets(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    seeded = _seed_comparator_inputs(run_dir)
    ranking = json.loads((run_dir / "dft_hardware_ppa_ranking.json").read_text(encoding="utf-8"))
    ranking["fpga_ranking"] = ranking["fpga_ranking"][:1]
    ranking["asic_ranking"] = ranking["asic_ranking"][:1]
    _write_json(run_dir / "dft_hardware_ppa_ranking.json", ranking)

    comparator = build_dft_deployment_comparator(run_dir)

    assert comparator["status"] == "blocked_no_deployment_recommendations"
    assert comparator["release_universe_binding"]["valid"] is False
    by_target = comparator["release_universe_binding"]["target_coverage"]
    assert by_target["fpga"]["required_candidate_count"] > 1
    assert by_target["fpga"]["present_ranking_row_count"] == 1
    assert by_target["asic"]["required_candidate_count"] > 1
    assert by_target["asic"]["present_ranking_row_count"] == 1
    blocker_ids = {
        blocker["blocker_id"]
        for blocker in comparator["release_universe_binding"]["blockers"]
    }
    assert "fpga_missing_release_universe_target_ranking_rows" in blocker_ids
    assert "asic_missing_release_universe_target_ranking_rows" in blocker_ids
    assert seeded["fpga_top_ids"][0] in by_target["fpga"]["present_candidate_ids"]
