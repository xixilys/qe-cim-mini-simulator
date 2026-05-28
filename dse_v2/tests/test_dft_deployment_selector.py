#!/usr/bin/env python3
"""DFT deployment-selector artifact tests."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.codesign.complete_dse_search_space import build_release_subset_manifest
from dse_v2.reference_workloads.dft_deployment_comparator import write_dft_deployment_comparator
from dse_v2.reference_workloads.dft_deployment_selector import (
    DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
    DFT_DEPLOYMENT_SELECTOR_SCHEMA,
    build_dft_deployment_selector,
    validate_dft_deployment_selector,
    write_dft_deployment_selector,
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


def _seed_selector_inputs(run_dir: Path, *, tied_fpga_metrics: bool = True) -> dict:
    subset = _write_release_subset(run_dir)
    by_target = _candidate_ids_by_target(subset)
    low_power = by_target["fpga"][0]
    memory_rich = by_target["fpga"][1]
    asic = by_target["asic"][0]
    low_power_registers = 1100 if not tied_fpga_metrics else 1152
    memory_rich_registers = 1152
    fpga_rows = [
        _fpga_row(
            candidate_id,
            rank=1 if index < 2 else index + 1,
            registers=(
                low_power_registers
                if index == 0
                else memory_rich_registers
                if index == 1
                else 1152 + index
            ),
        )
        for index, candidate_id in enumerate(by_target["fpga"])
    ]
    asic_rows = [
        _asic_row(
            candidate_id,
            rank=1 if index == 0 else index + 1,
            area=726984.724724 + index,
        )
        for index, candidate_id in enumerate(by_target["asic"])
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
    write_dft_deployment_comparator(run_dir)
    return {"low_power": low_power, "memory_rich": memory_rich, "asic": asic}


def test_deployment_selector_missing_objective_is_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_selector_inputs(run_dir)

    status = write_dft_deployment_selector(run_dir)
    selector = json.loads((run_dir / "dft_deployment_selector.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "dft_deployment_selector_validation.json").read_text(encoding="utf-8"))

    assert status["status"] == "passed"
    assert selector["schema_version"] == DFT_DEPLOYMENT_SELECTOR_SCHEMA
    assert selector["status"] == "blocked_missing_explicit_objective"
    assert selector["selected_deployment_target"] is None
    assert selector["selected_candidate"] is None
    assert selector["non_physical_tie_breakers_used"] is False
    assert selector["deliverable_complete"] is False
    assert validation["valid"] is True


def test_deployment_selector_discovers_run_local_objective_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    ids = _seed_selector_inputs(run_dir)
    _write_json(
        run_dir / "dft_deployment_objective_no_budget_available_hard_gate.json",
        {
            "schema_version": DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
            "objective_id": "no-budget-evidence-priority",
            "deployment_target": "cross_target",
            "target_score_direction": "min",
            "target_score_normalization": "unitless_planning_score",
            "target_scores": {"fpga": 2.0, "asic": 1.0},
        },
    )

    status = write_dft_deployment_selector(run_dir)
    selector = json.loads((run_dir / "dft_deployment_selector.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "dft_deployment_selector_validation.json").read_text(encoding="utf-8"))

    assert status["selection_status"] == "unique_deployment_candidate_selected_by_explicit_objective"
    assert selector["objective_present"] is True
    assert selector["objective"]["objective_id"] == "no-budget-evidence-priority"
    assert selector["source_artifacts"]["deployment_objective"]["exists"] is True
    assert selector["selected_deployment_target"] == "asic"
    assert selector["selected_candidate_id"] == ids["asic"]
    assert validation["valid"] is True


def test_deployment_selector_keeps_fpga_physical_tie_when_objective_metrics_tie(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    ids = _seed_selector_inputs(run_dir, tied_fpga_metrics=True)
    objective = {
        "schema_version": DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
        "objective_id": "min-fpga-registers",
        "deployment_target": "fpga",
        "selection_metrics": [{"metric": "fpga_total_slice_registers", "direction": "min"}],
    }

    selector = build_dft_deployment_selector(run_dir, objective=objective)
    validation = validate_dft_deployment_selector(selector)

    assert selector["status"] == "objective_tie_no_unique_deployment_candidate"
    assert selector["selected_candidate"] is None
    assert sorted(selector["candidate_selection"]["tie_candidate_ids"]) == sorted(
        [ids["low_power"], ids["memory_rich"]]
    )
    assert validation["valid"] is True


def test_deployment_selector_selects_fpga_only_when_objective_metric_breaks_tie(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    ids = _seed_selector_inputs(run_dir, tied_fpga_metrics=False)
    objective = {
        "schema_version": DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
        "objective_id": "min-fpga-registers",
        "deployment_target": "fpga",
        "selection_metrics": [{"metric": "fpga_total_slice_registers", "direction": "min"}],
    }

    selector = build_dft_deployment_selector(run_dir, objective=objective)
    validation = validate_dft_deployment_selector(selector)

    assert selector["status"] == "unique_deployment_candidate_selected_by_explicit_objective"
    assert selector["selected_deployment_target"] == "fpga"
    assert selector["selected_candidate_id"] == ids["low_power"]
    assert selector["selected_candidate"]["candidate_id"] == ids["low_power"]
    assert selector["non_physical_tie_breakers_used"] is False
    assert validation["valid"] is True


def test_deployment_selector_can_select_asic_with_explicit_cross_target_scores(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    ids = _seed_selector_inputs(run_dir)
    objective = {
        "schema_version": DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
        "objective_id": "explicit-cross-target-cost",
        "deployment_target": "cross_target",
        "target_score_direction": "min",
        "target_score_normalization": "unitless_weighted_cost",
        "target_scores": {"fpga": 2.0, "asic": 1.0},
    }

    selector = build_dft_deployment_selector(run_dir, objective=objective)
    validation = validate_dft_deployment_selector(selector)

    assert selector["status"] == "unique_deployment_candidate_selected_by_explicit_objective"
    assert selector["selected_deployment_target"] == "asic"
    assert selector["selected_candidate_id"] == ids["asic"]
    assert selector["target_selection"]["status"] == "unique_target_selected_by_explicit_objective"
    assert validation["valid"] is True


def test_deployment_selector_blocks_cross_target_choice_without_both_target_recommendations(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    ids = _seed_selector_inputs(run_dir)
    ranking = json.loads((run_dir / "dft_hardware_ppa_ranking.json").read_text(encoding="utf-8"))
    ranking["fpga_ranking"] = []
    _write_json(run_dir / "dft_hardware_ppa_ranking.json", ranking)
    write_dft_deployment_comparator(run_dir)
    objective = {
        "schema_version": DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
        "objective_id": "explicit-cross-target-cost",
        "deployment_target": "cross_target",
        "target_score_direction": "min",
        "target_score_normalization": "unitless_weighted_cost",
        "target_scores": {"fpga": 2.0, "asic": 1.0},
    }

    selector = build_dft_deployment_selector(run_dir, objective=objective)
    validation = validate_dft_deployment_selector(selector)

    assert selector["status"] == "blocked_cross_target_requires_fpga_and_asic_recommendations"
    assert selector["selected_deployment_target"] is None
    assert selector["selected_candidate_id"] is None
    assert selector["target_selection"]["missing_recommendation_targets"] == ["fpga"]
    assert selector["blockers"][0]["blocker_id"] == "cross_target_requires_fpga_and_asic_recommendations"
    assert ids["asic"] != selector["selected_candidate_id"]
    assert validation["valid"] is True


def test_deployment_selector_treats_auto_as_cross_target_objective(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    ids = _seed_selector_inputs(run_dir)
    objective = {
        "schema_version": DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
        "objective_id": "auto-cross-target-cost",
        "deployment_target": "auto",
        "target_score_direction": "min",
        "target_score_normalization": "unitless_weighted_cost",
        "target_scores": {"fpga": 2.0, "asic": 1.0},
    }

    selector = build_dft_deployment_selector(run_dir, objective=objective)
    validation = validate_dft_deployment_selector(selector)

    assert selector["status"] == "unique_deployment_candidate_selected_by_explicit_objective"
    assert selector["objective"]["deployment_target"] == "auto"
    assert selector["selected_deployment_target"] == "asic"
    assert selector["selected_candidate_id"] == ids["asic"]
    assert selector["target_selection"]["status"] == "unique_target_selected_by_explicit_objective"
    assert validation["valid"] is True


def test_deployment_selector_rejects_non_physical_tie_breaker_objective(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _seed_selector_inputs(run_dir)
    objective = {
        "schema_version": DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
        "objective_id": "illegal-candidate-id-order",
        "deployment_target": "fpga",
        "tie_breaker": "candidate_id_order",
    }

    selector = build_dft_deployment_selector(run_dir, objective=objective)
    validation = validate_dft_deployment_selector(selector)

    assert selector["status"] == "blocked_invalid_or_non_physical_objective"
    assert selector["selected_candidate"] is None
    assert selector["blockers"][0]["blocker_id"] == "forbidden_objective_tie_breaker"
    assert validation["valid"] is True


def test_deployment_selector_requires_cross_target_score_normalization(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _seed_selector_inputs(run_dir)
    objective = {
        "schema_version": DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
        "objective_id": "unnormalized-cross-target-cost",
        "deployment_target": "cross_target",
        "target_score_direction": "min",
        "target_scores": {"fpga": 2.0, "asic": 1.0},
    }

    selector = build_dft_deployment_selector(run_dir, objective=objective)
    validation = validate_dft_deployment_selector(selector)

    assert selector["status"] == "blocked_invalid_or_non_physical_objective"
    assert selector["selected_candidate"] is None
    assert selector["blockers"][0]["blocker_id"] == "cross_target_score_normalization_required"
    assert validation["valid"] is True
