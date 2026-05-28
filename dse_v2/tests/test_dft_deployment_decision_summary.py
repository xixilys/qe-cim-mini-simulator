#!/usr/bin/env python3
"""DFT deployment decision-summary artifact tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.complete_dse_search_space import build_release_subset_manifest
from dse_v2.reference_workloads.complete_dse_done_when_4_6_audit import (
    write_complete_dse_release_artifact_package,
)
from dse_v2.reference_workloads.dft_deployment_comparator import write_dft_deployment_comparator
from dse_v2.reference_workloads.dft_deployment_decision_summary import (
    DFT_DEPLOYMENT_DECISION_SUMMARY_SCHEMA,
    build_dft_deployment_decision_summary,
    validate_dft_deployment_decision_summary,
    write_dft_deployment_decision_summary,
)
from dse_v2.reference_workloads.dft_deployment_selector import (
    DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
    write_dft_deployment_selector,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDER = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "build_dft_deployment_decision_summary.py"
RELEASE_PACKAGE_BUILDER = (
    REPO_ROOT
    / "dse_v2"
    / "scripts"
    / "dse"
    / "build_complete_dse_release_artifact_package.py"
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _release_candidate_ids_by_target() -> tuple[dict, dict[str, list[str]]]:
    subset = build_release_subset_manifest()
    ids_by_target: dict[str, list[str]] = {"fpga": [], "asic": []}
    for candidate in subset["candidates"]:
        identity = candidate["identity"]["identity_layers"]
        target = identity["target_platform_parameters"]["platform_kind"]
        if candidate["legal"] is True and target in ids_by_target:
            ids_by_target[target].append(candidate["candidate_id"])
    return subset, ids_by_target


def _fpga_row(candidate_id: str, rank: int) -> dict:
    return {
        "candidate_id": candidate_id,
        "design_candidate_id": candidate_id,
        "target": "fpga",
        "rank": rank,
        "tie_key": [1900.0 + rank, 1152.0 + rank, 23.0, 0.0, 841.0, -0.093],
        "identity_assignments": {"architecture_id": candidate_id.split("::", 1)[0], "hardware_target": "fpga"},
        "required_stage_ids": ["golden_correctness", "hls_or_rtl_sim", "hls_or_rtl_synth", "vivado_fpga_synth_or_impl"],
        "fpga_total_slice_luts": 1901,
        "fpga_total_slice_registers": 1152,
        "fpga_total_dsps": 23,
        "fpga_total_block_ram_tiles": 0,
        "fpga_total_bonded_iob": 841,
        "fpga_min_wns_ns": 0.093,
        "vivado_route_completed_kernel_count": 8,
        "kernel_count": 8,
    }


def _asic_row(candidate_id: str, rank: int) -> dict:
    return {
        "candidate_id": candidate_id,
        "design_candidate_id": candidate_id,
        "target": "asic",
        "rank": rank,
        "tie_key": [722431.891054 + rank, -0.0],
        "identity_assignments": {"architecture_id": candidate_id.split("::", 1)[0], "hardware_target": "asic"},
        "required_stage_ids": ["golden_correctness", "hls_or_rtl_sim", "hls_or_rtl_synth", "dc_asic_synth_timing_area"],
        "asic_total_cell_area": 722431.891054,
        "asic_min_slack_ns": 0.0,
        "asic_slack_deficit_ns": 0.0,
        "dc_real_target_library_kernel_count": 8,
        "kernel_count": 8,
    }


def _seed_deployment_artifacts(run_dir: Path) -> dict[str, str]:
    release_subset, ids_by_target = _release_candidate_ids_by_target()
    _write_json(run_dir / "release_subset_manifest.json", release_subset)
    fpga = ids_by_target["fpga"][0]
    asic = ids_by_target["asic"][0]
    fpga_ranking = [
        _fpga_row(candidate_id, rank=index + 1)
        for index, candidate_id in enumerate(ids_by_target["fpga"])
    ]
    asic_ranking = [
        _asic_row(candidate_id, rank=index + 1)
        for index, candidate_id in enumerate(ids_by_target["asic"])
    ]
    _write_json(
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "status": "trusted_hardware_ppa_ranking_available",
            "release_id": release_subset["release_id"],
            "candidate_count": len(fpga_ranking) + len(asic_ranking),
            "ranking_eligible_candidate_count": len(fpga_ranking) + len(asic_ranking),
            "hardware_completion_eligible": True,
            "winner_selection_status": "ranked_candidates_available",
            "source_artifacts": {
                "release_subset_manifest": {
                    "path": str(run_dir / "release_subset_manifest.json")
                }
            },
            "fpga_ranking": fpga_ranking,
            "asic_ranking": asic_ranking,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_validation.json",
        {"schema_version": "dse.dft.hardware_ppa_ranking_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_status.json",
        {"schema_version": "dse.dft.hardware_ppa_ranking_status.v1", "status": "passed", "ranking_status": "trusted_hardware_ppa_ranking_available"},
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
        run_dir / "dft_deployment_target_model_selection.json",
        {
            "schema_version": "dse.dft.deployment_target_model_selection.v1",
            "status": "target_model_selection_available",
            "selection_rows": [
                {
                    "target": "asic",
                    "candidate_id": asic,
                    "selection_status": "selected_model_inferred_from_dc_probe_pending_binding",
                    "selected_model": {
                        "model_id": "dc_target_library:fsa0a_c_generic_core_tt1p8v25c",
                        "library_name": "fsa0a_c_generic_core_tt1p8v25c",
                        "dc_target_library": "fsa0a_c_generic_core_tt1p8v25c",
                        "library_db_path": "/eda/lib/fsa0a_c_generic_core_tt1p8v25c.db",
                    },
                },
                {
                    "target": "fpga",
                    "candidate_id": fpga,
                    "selection_status": "selected_catalog_model_pending_local_binding",
                    "selected_model": {
                        "model_id": "amd_alveo_u280_a_u280",
                        "board_or_device_model": "AMD Alveo U280 Data Center Accelerator Card",
                        "vivado_part": "xcu280-fsvh2892-2L-e",
                    },
                },
            ],
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_deployment_target_model_selection_status.json",
        {"schema_version": "dse.dft.deployment_target_model_selection_status.v1", "status": "target_model_selection_available"},
    )
    _write_json(
        run_dir / "dft_deployment_target_model_binding.json",
        {
            "schema_version": "dse.dft.deployment_target_model_binding.v1",
            "status": "blocked_target_model_binding_required",
            "blocker_ids": ["fpga_selected_model_not_supported_by_vivado_probe"],
            "target_binding_rows": [
                {
                    "target": "asic",
                    "binding_status": "bound_model_inferred_from_dc_probe",
                    "blocker_ids": [],
                    "selected_model": {
                        "model_id": "dc_target_library:fsa0a_c_generic_core_tt1p8v25c",
                        "library_name": "fsa0a_c_generic_core_tt1p8v25c",
                        "dc_target_library": "fsa0a_c_generic_core_tt1p8v25c",
                        "library_db_path": "/eda/lib/fsa0a_c_generic_core_tt1p8v25c.db",
                    },
                    "selected_dc_target_libraries": ["fsa0a_c_generic_core_tt1p8v25c"],
                    "dc_supported_target_libraries": ["fsa0a_c_generic_core_tt1p8v25c"],
                    "dc_library_db_paths": ["/eda/lib/fsa0a_c_generic_core_tt1p8v25c.db"],
                    "execution_permitted_for_target_profile": True,
                },
                {
                    "target": "fpga",
                    "binding_status": "blocked_selected_model_not_supported_by_vivado_probe",
                    "blocker_ids": ["fpga_selected_model_not_supported_by_vivado_probe"],
                    "selected_model": {
                        "model_id": "amd_alveo_u280_a_u280",
                        "board_or_device_model": "AMD Alveo U280 Data Center Accelerator Card",
                        "vivado_part": "xcu280-fsvh2892-2L-e",
                    },
                    "selected_vivado_parts": ["xcu280-fsvh2892-2L-e"],
                    "vivado_supported_parts": ["xc7a35tcsg324-1"],
                    "execution_permitted_for_target_profile": False,
                },
            ],
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_vivado_part_support_probe.json",
        {
            "schema_version": "dse.dft.vivado_part_support_probe.v1",
            "status": "blocked_requested_parts_not_supported_by_probe",
            "requested_parts": ["xcu280-fsvh2892-2L-e"],
            "supported_parts": [],
            "missing_requested_parts": ["xcu280-fsvh2892-2L-e"],
            "selected_probe_transport": "ssh",
            "selected_probe_returncode": 0,
            "vivado_part_support_probe_attempted": True,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    write_dft_deployment_comparator(run_dir)
    objective = {
        "schema_version": DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
        "objective_id": "no-budget-evidence-priority",
        "deployment_target": "cross_target",
        "target_score_direction": "min",
        "target_score_normalization": "unitless_weighted_cost",
        "target_scores": {"fpga": 2.0, "asic": 1.0},
    }
    write_dft_deployment_selector(run_dir, objective=objective)
    return {"fpga": fpga, "asic": asic}


def test_deployment_decision_summary_recommends_asic_and_preserves_fpga_vivado_blocker(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    ids = _seed_deployment_artifacts(run_dir)

    summary = build_dft_deployment_decision_summary(run_dir)
    validation = validate_dft_deployment_decision_summary(summary)

    assert summary["schema_version"] == DFT_DEPLOYMENT_DECISION_SUMMARY_SCHEMA
    assert summary["status"] == "deployment_decision_summary_available"
    assert (
        summary["best_current_deployment_recommendation"]["status"]
        == "selected_deployment_recommendation_available_with_blocked_side_targets"
    )
    assert summary["best_current_deployment_recommendation"]["recommended_target"] == "asic"
    assert summary["best_current_deployment_recommendation"]["recommended_candidate_id"] == ids["asic"]
    assert summary["target_recommendation_available_count"] == 2
    assert summary["cross_target_comparison_eligible"] is True
    assert summary["hardware_completion_eligible_for_deployment_comparison"] is True
    assert summary["best_current_deployment_recommendation"]["selected_target_blocker_ids"] == []
    assert summary["best_current_deployment_recommendation"]["side_target_blocker_ids"] == [
        "fpga_selected_model_not_supported_by_vivado_probe"
    ]
    assert summary["asic_deployment_assessment"]["target_model_binding_status"] == "bound_model_inferred_from_dc_probe"
    assert summary["fpga_deployment_assessment"]["selected_model_id"] == "amd_alveo_u280_a_u280"
    assert "fpga_selected_model_not_supported_by_vivado_probe" in summary["fpga_deployment_assessment"]["blocker_ids"]
    assert summary["source_artifacts"]["dft_vivado_part_support_probe"]["exists"] is True
    assert summary["vivado_part_support_probe_status"] == "blocked_requested_parts_not_supported_by_probe"
    fpga_probe = summary["fpga_deployment_assessment"]["tool_support"]["vivado_part_support_probe"]
    assert fpga_probe["present"] is True
    assert fpga_probe["missing_requested_parts"] == ["xcu280-fsvh2892-2L-e"]
    assert summary["trusted_final_claim"] is False
    assert summary["deliverable_complete"] is False
    assert validation["valid"] is True


def test_deployment_decision_summary_surfaces_release_candidate_identity_provenance_blocker(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    goal = tmp_path / "goal.md"
    barrier = tmp_path / "barrier.md"
    preflight = tmp_path / "preflight.md"
    goal.write_text("done-when 4\n", encoding="utf-8")
    barrier.write_text("barrier\n", encoding="utf-8")
    preflight.write_text("preflight\n", encoding="utf-8")

    write_complete_dse_release_artifact_package(
        run_dir,
        repo_root=REPO_ROOT,
        goal_path=goal,
        barrier_path=barrier,
        preflight_path=preflight,
    )
    _seed_deployment_artifacts(run_dir)

    summary = build_dft_deployment_decision_summary(run_dir)
    validation = validate_dft_deployment_decision_summary(summary)

    assert summary["release_candidate_identity_provenance_status"] == "blocked"
    assert summary["release_candidate_identity_provenance_blocker_ids"] == [
        "deployment_decision_summary_not_bound",
        "strict_qe_release_lane_bundle_not_supplied_to_audit",
    ]
    assert (
        summary[
            "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity"
        ]
        is False
    )
    assert summary["release_candidate_identity_provenance_package_exists"] is True
    assert summary["release_candidate_identity_provenance_package_status"] == "partial"
    assert "Release-package candidate identity provenance" in summary[
        "release_candidate_identity_provenance_claim_boundary"
    ]
    assert summary["best_current_deployment_recommendation"]["trusted_final_claim"] is False
    assert validation["valid"] is True


def test_deployment_decision_summary_writer_and_cli(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_deployment_artifacts(run_dir)

    status = write_dft_deployment_decision_summary(run_dir)
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--run-dir", str(run_dir)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    summary = json.loads((run_dir / "dft_deployment_decision_summary.json").read_text(encoding="utf-8"))
    status_payload = json.loads((run_dir / "dft_deployment_decision_summary_status.json").read_text(encoding="utf-8"))

    assert status["status"] == "passed"
    assert result.returncode == 0, result.stdout + result.stderr
    assert status_payload["recommended_target"] == "asic"
    assert status_payload["target_recommendation_available_count"] == 2
    assert status_payload["cross_target_comparison_eligible"] is True
    assert status_payload["hardware_completion_eligible_for_deployment_comparison"] is True
    assert status_payload["side_target_blocker_ids"] == ["fpga_selected_model_not_supported_by_vivado_probe"]
    assert summary["best_current_deployment_recommendation"]["trusted_final_claim"] is False
    assert summary["best_current_deployment_recommendation"]["deliverable_complete"] is False


def test_release_package_cli_auto_binds_generated_deployment_decision_summary(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    goal = tmp_path / "goal.md"
    barrier = tmp_path / "barrier.md"
    preflight = tmp_path / "preflight.md"
    goal.write_text("done-when 4\n", encoding="utf-8")
    barrier.write_text("barrier\n", encoding="utf-8")
    preflight.write_text("preflight\n", encoding="utf-8")
    _seed_deployment_artifacts(run_dir)
    write_dft_deployment_decision_summary(run_dir)
    decision_summary_path = run_dir / "dft_deployment_decision_summary.json"
    decision_summary_sha256 = hashlib.sha256(
        decision_summary_path.read_bytes()
    ).hexdigest()

    result = subprocess.run(
        [
            sys.executable,
            str(RELEASE_PACKAGE_BUILDER),
            "--out",
            str(run_dir),
            "--repo-root",
            str(REPO_ROOT),
            "--goal-path",
            str(goal),
            "--barrier-path",
            str(barrier),
            "--preflight-path",
            str(preflight),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    package = json.loads(
        (run_dir / "complete_dse_release_artifact_package.json").read_text(
            encoding="utf-8"
        )
    )
    decision_inputs = package["decision_summary_inputs"]
    decision_ref = decision_inputs["deployment_decision_summary"]

    assert result.returncode == 0, result.stdout + result.stderr
    assert decision_inputs["status"] == "bound"
    assert decision_inputs["supplied_input_count"] == 1
    assert decision_ref["path"] == str(decision_summary_path)
    assert decision_ref["sha256"] == decision_summary_sha256
    assert package["release_candidate_identity_provenance"][
        "deployment_decision_summary_binding_status"
    ] == "bound_to_supplied_artifact"
    assert "--deployment-decision-summary-path" in package["replay_cli"]["argv"]
    assert str(decision_summary_path) in package["replay_cli"]["argv"]
    assert package["deliverable_complete"] is False


def test_deployment_decision_summary_blocks_stale_cross_target_selector_without_bilateral_comparator(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _seed_deployment_artifacts(run_dir)
    ranking = json.loads((run_dir / "dft_hardware_ppa_ranking.json").read_text(encoding="utf-8"))
    ranking["fpga_ranking"] = []
    _write_json(run_dir / "dft_hardware_ppa_ranking.json", ranking)
    write_dft_deployment_comparator(run_dir)
    comparator = json.loads((run_dir / "dft_deployment_comparator.json").read_text(encoding="utf-8"))
    comparator["hardware_completion_eligible_for_deployment_comparison"] = True
    _write_json(run_dir / "dft_deployment_comparator.json", comparator)

    summary = build_dft_deployment_decision_summary(run_dir)
    validation = validate_dft_deployment_decision_summary(summary)
    best = summary["best_current_deployment_recommendation"]

    assert summary["target_recommendation_available_count"] == 1
    assert summary["cross_target_comparison_eligible"] is False
    assert summary["hardware_completion_eligible_for_deployment_comparison"] is False
    assert best["status"] == "blocked_stale_selector_cross_target_requires_bilateral_recommendations"
    assert best["recommended_target"] is None
    assert best["recommended_candidate_id"] is None
    assert best["blocker_ids"] == ["cross_target_requires_fpga_and_asic_recommendations"]
    assert validation["valid"] is True


def test_deployment_decision_summary_blocks_candidate_ids_outside_frozen_release_universe(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _seed_deployment_artifacts(run_dir)
    selector = json.loads((run_dir / "dft_deployment_selector.json").read_text(encoding="utf-8"))
    selector["selected_candidate_id"] = "dft-manual::map_hpsi"
    selector["selected_candidate"] = {
        "candidate_id": "dft-manual::map_hpsi",
        "target": "asic",
    }
    _write_json(run_dir / "dft_deployment_selector.json", selector)

    summary = build_dft_deployment_decision_summary(run_dir)
    validation = validate_dft_deployment_decision_summary(summary)
    binding = summary["release_universe_candidate_identity_binding"]
    best = summary["best_current_deployment_recommendation"]

    assert binding["status"] == "blocked"
    assert binding["release_id"] == "complete_dse_qe_release_v1"
    assert binding["extra_candidate_ids"] == ["dft-manual::map_hpsi"]
    assert binding["blocker_ids"] == [
        "deployment_summary_candidate_ids_not_in_frozen_release_universe"
    ]
    assert binding["candidate_ids_bound_to_frozen_release_universe"] is False
    assert best["status"] == "blocked_release_universe_candidate_identity_binding"
    assert best["recommended_target"] is None
    assert best["recommended_candidate_id"] is None
    assert "deployment_summary_candidate_ids_not_in_frozen_release_universe" in best["blocker_ids"]
    assert summary["status"] == "deployment_decision_summary_fail_closed"
    assert validation["valid"] is True


def test_deployment_decision_summary_missing_selector_is_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "dft_deployment_comparator.json",
        {
            "schema_version": "dse.dft.deployment_comparator.v1",
            "status": "blocked_no_deployment_recommendations",
            "cross_target_recommendation": {"status": "no_single_cross_target_winner_without_user_objective"},
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_deployment_comparator_validation.json",
        {"schema_version": "dse.dft.deployment_comparator_validation.v1", "valid": True, "errors": []},
    )

    summary = build_dft_deployment_decision_summary(run_dir)
    validation = validate_dft_deployment_decision_summary(summary)

    assert summary["status"] == "blocked_missing_required_deployment_artifacts"
    assert "dft_deployment_selector" in summary["missing_required_artifacts"]
    assert summary["best_current_deployment_recommendation"]["recommended_target"] is None
    assert validation["valid"] is True
