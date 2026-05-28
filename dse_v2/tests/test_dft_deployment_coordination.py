#!/usr/bin/env python3
"""DFT three-lane deployment coordination summary tests."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.contracts import SCHEMA_REGISTRY, validate_instance
from dse_v2.codesign.complete_dse_search_space import (
    DEFAULT_FROZEN_WORKLOAD_CASE_COUNT,
    build_release_cardinality_budget,
    build_release_l4_runtime_cost_report,
)
from dse_v2.reference_workloads.dft_deployment_coordination import (
    DFT_DEPLOYMENT_COORDINATION_SUMMARY_SCHEMA,
    build_dft_deployment_coordination_summary,
    validate_dft_deployment_coordination_summary,
    write_dft_deployment_coordination_summary,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _validate_registered_schema(payload: dict, schema_id: str) -> None:
    if schema_id in SCHEMA_REGISTRY:
        validate_instance(payload, SCHEMA_REGISTRY[schema_id])


def _release_candidate_ids(count: int = 504) -> list[str]:
    ids = ["cand-asic", "cand-fpga"]
    ids.extend(f"cand-release-{idx:03d}" for idx in range(2, count))
    return ids


def _binding_rows(candidate_ids: list[str]) -> list[dict[str, object]]:
    rows = [
        {
            "search_candidate_id": "search-fpga",
            "release_candidate_id": "cand-fpga",
            "evaluation_record_id": "cand-fpga",
            "legacy_candidate_id": "cand-fpga",
            "design_candidate_id": "design-fpga",
            "binding_status": "matched_by_template_axis_heuristic",
            "candidate_id_kind": "evaluation_record_id",
            "candidate_id_authoritative_for_design": False,
            "completion_eligible": False,
        },
        {
            "search_candidate_id": "search-asic",
            "release_candidate_id": "cand-asic",
            "evaluation_record_id": "cand-asic",
            "legacy_candidate_id": "cand-asic",
            "design_candidate_id": "design-asic",
            "binding_status": "matched_by_template_axis_heuristic",
            "candidate_id_kind": "evaluation_record_id",
            "candidate_id_authoritative_for_design": False,
            "completion_eligible": False,
        },
    ]
    for idx, candidate_id in enumerate(candidate_ids[2:], start=2):
        rows.append({
            "search_candidate_id": f"search-{idx:03d}",
            "release_candidate_id": candidate_id,
            "evaluation_record_id": candidate_id,
            "legacy_candidate_id": candidate_id,
            "design_candidate_id": f"design-{idx:03d}",
            "binding_status": "matched_by_template_axis_heuristic",
            "candidate_id_kind": "evaluation_record_id",
            "candidate_id_authoritative_for_design": False,
            "completion_eligible": False,
        })
    return rows


def _seed_complete_dse_obligation(run_dir: Path, candidate_ids: list[str]) -> None:
    workload_count = 6
    required_rows = len(candidate_ids) * workload_count
    _write_json(
        run_dir / "release_candidate_trial_ledger.json",
        {
            "schema_version": "dse.codesign.complete_dse.release_candidate_trial_ledger.v1",
            "status": "passed",
            "release_id": "complete_dse_release_v1",
            "release_subset_hash": "fixture-release-subset-hash",
            "candidate_count": len(candidate_ids),
            "legal_candidate_count": len(candidate_ids),
            "illegal_candidate_count": 0,
            "frozen_workload_case_count": workload_count,
            "required_l4_evidence_row_count": required_rows,
            "all_candidates_have_trial_rows": True,
            "all_trial_rows_have_stable_hashes": True,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "blockers": [],
            "rows": [
                {
                    "candidate_id": candidate_id,
                    "legal": True,
                    "candidate_record_hash": f"record-{idx:03d}",
                    "identity_hash": f"identity-{idx:03d}",
                    "frozen_workload_case_count": workload_count,
                    "required_l4_row_count": workload_count,
                    "trusted_final_claim": False,
                    "release_completion_eligible": False,
                }
                for idx, candidate_id in enumerate(candidate_ids)
            ],
        },
    )
    _write_json(
        run_dir / "l4_evidence_matrix.json",
        {
            "schema_version": "dse.codesign.l4_evidence_matrix.v1",
            "expected_row_count": required_rows,
            "row_count": required_rows,
            "rows": [
                {
                    "candidate_id": candidate_id,
                    "workload_case_id": f"scf_case_{case_idx}",
                    "row_id": f"{candidate_id}::scf_case_{case_idx}",
                    "trusted_speedup_eligible": False,
                    "blockers": ["fixture_blocked_l4_row"],
                }
                for candidate_id in candidate_ids
                for case_idx in range(workload_count)
            ],
        },
    )
    _write_json(
        run_dir / "coverage_claim_report.json",
        {
            "schema_version": "dse.codesign.coverage_claim_report.v1",
            "expected_row_count": required_rows,
            "row_count": required_rows,
            "all_rows_present": True,
            "blocked_row_count": required_rows,
            "claims": {
                "deliverable_complete": False,
                "top_k_or_representative_completion_allowed": False,
            },
        },
    )
    _write_json(
        run_dir / "complete_dse_full_l4_evidence_report.json",
        {
            "schema_version": "dse.codesign.complete_dse_full_l4_evidence_report.v1",
            "status": "blocked_or_partial",
            "expected_row_count": required_rows,
            "row_count": required_rows,
            "claims": {"deliverable_complete": False},
        },
    )


def _seed_coordination_inputs(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "wave504"
    candidate_ids = _release_candidate_ids()
    search_summary = tmp_path / "search" / "search_effectiveness_loop_pilot_summary.json"
    _write_json(
        search_summary,
        {
            "schema_version": "dse.search_effectiveness_loop_pilot.v1",
            "control_plane_search_effectiveness_closed": True,
            "latest_effectiveness_gate_passed": True,
            "latest_effectiveness_blockers": [],
            "completed_rounds": 2,
            "total_executed_count": 4,
            "latest_search_effectiveness_audit_ref": "sweep_round_02/search_effectiveness_audit.json",
            "dft_template_binding_report_seen": True,
            "latest_dft_template_binding_gate_passed": True,
            "latest_dft_template_binding_status": "passed",
            "latest_dft_template_binding_report_ref": "sweep_round_02/dft_template_binding_report.json",
            "latest_dft_template_bound_candidate_count": 8,
            "latest_dft_template_blocked_candidate_count": 0,
        },
    )
    _write_json(
        run_dir / "dft_fpga_asic_deployment_summary.json",
        {
            "schema_version": "dse.dft.fpga_asic_deployment_summary.v1",
            "status": "resolved_best_deployment",
            "best_deployment_claim_eligible": True,
            "deliverable_complete": False,
            "fpga": {
                "deployment": "fpga",
                "status": "resolved_best_deployment",
                "resolved": True,
                "best_candidate_id": "cand-fpga",
                "best_design_candidate_id": "design-fpga",
                "equivalent_top_candidate_ids": [],
                "metrics": {
                    "fpga_total_slice_luts": 4304,
                    "fpga_total_dsps": 23,
                    "vivado_route_completed_kernel_count": 8,
                    "kernel_count": 8,
                },
                "device_selection_status": "not_explicitly_proven",
                "device_summary": {
                    "selected_device": None,
                    "selected_fpga_device": None,
                    "device_selection_status": "not_explicitly_proven",
                    "kernel_row_target_evidence": {
                        "status": "not_explicitly_proven",
                        "targeted_kernel_count": 0,
                        "expected_kernel_count": 8,
                    },
                },
            },
            "asic": {
                "deployment": "asic",
                "status": "resolved_best_deployment",
                "resolved": True,
                "best_candidate_id": "cand-asic",
                "best_design_candidate_id": "design-asic",
                "equivalent_top_candidate_ids": ["cand-asic-dup"],
                "metrics": {
                    "asic_total_cell_area": 727575.31,
                    "asic_min_slack_ns": 0.0,
                    "dc_real_target_library_kernel_count": 8,
                    "kernel_count": 8,
                },
                "device_selection_status": "resolved_from_kernel_row_evidence",
                "device_summary": {
                    "selected_device": "fsa0a_c_generic_core_tt1p8v25c",
                    "selected_asic_target": "fsa0a_c_generic_core_tt1p8v25c",
                    "device_selection_status": "resolved_from_kernel_row_evidence",
                    "kernel_row_target_evidence": {
                        "status": "resolved_from_kernel_row_evidence",
                        "selected_target": "fsa0a_c_generic_core_tt1p8v25c",
                        "targeted_kernel_count": 8,
                        "expected_kernel_count": 8,
                    },
                },
            },
        },
    )
    _write_json(
        run_dir / "dft_fpga_asic_deployment_summary_validation.json",
        {"schema_version": "dse.dft.fpga_asic_deployment_summary_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution.v1",
            "hardware_winner_resolution_eligible": True,
            "trusted_best_architecture_claim_eligible": True,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_candidate_binding_map.json",
        {
            "schema_version": "dse.dft.candidate_binding_map.v1",
            "status": "passed",
            "candidate_admission_status": "release_admission_closed",
            "candidate_set_scope": "full_release_universe",
            "search_covers_full_release_universe": True,
            "release_admission_closure": True,
            "release_admission_claim_eligible": True,
            "search_candidate_count": len(candidate_ids),
            "legal_release_candidate_count": len(candidate_ids),
            "bound_candidate_count": len(candidate_ids),
            "unmatched_candidate_count": 0,
            "unique_release_candidate_count": len(candidate_ids),
            "release_admission_candidate_count": len(candidate_ids),
            "release_only_admission_candidate_count": 0,
            "release_only_admission_candidate_ids": [],
            "duplicate_release_candidate_ids": [],
            "completion_eligible": False,
            "deliverable_complete": False,
            "candidate_universe_reconciliation": {
                "schema_version": "dse.dft.candidate_universe_reconciliation.v1",
                "status": "release_admission_closed",
                "candidate_admission_status": "release_admission_closed",
                "candidate_set_scope": "full_release_universe",
                "search_candidate_count": len(candidate_ids),
                "legal_release_candidate_count": len(candidate_ids),
                "unique_release_candidate_count": len(candidate_ids),
                "release_admission_candidate_count": len(candidate_ids),
                "release_only_admission_candidate_count": 0,
                "release_only_admission_candidate_ids": [],
                "search_covers_full_release_universe": True,
                "release_admission_closure": True,
                "release_admission_claim_eligible": True,
            },
            "binding_rows": _binding_rows(candidate_ids),
        },
    )
    _write_json(
        run_dir / "dft_candidate_binding_map_validation.json",
        {
            "schema_version": "dse.dft.candidate_binding_map_validation.v1",
            "valid": True,
            "row_count": len(candidate_ids),
            "errors": [],
        },
    )
    _write_json(
        run_dir / "dft_hardware_closure_release_gate.json",
        {
            "schema_version": "dse.dft.hardware_closure_release_gate.v1",
            "status": "hardware_release_gate_passed",
            "release_gate_result": "hardware_release_gate_passed",
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
            "candidate_count": len(candidate_ids),
            "candidate_admission_gate_passed": True,
            "candidate_admission_blocker_count": 0,
            "candidate_admission_gate": {
                "schema_version": "dse.dft.hardware_closure_release_gate_candidate_admission.v1",
                "status": "passed_candidate_admission_gate",
                "candidate_admission_gate_passed": True,
                "release_gate_candidate_count": len(candidate_ids),
                "candidate_binding_map_present": True,
                "candidate_binding_map_supplied_validation_valid": True,
                "candidate_binding_map_inline_validation_valid": True,
                "candidate_binding_map_bound_candidate_count": len(candidate_ids),
                "candidate_binding_map_unique_release_candidate_count": len(candidate_ids),
                "candidate_binding_map_release_admission_candidate_count": len(candidate_ids),
                "candidate_binding_map_release_only_admission_candidate_count": 0,
                "candidate_binding_map_candidate_admission_status": "release_admission_closed",
                "candidate_binding_map_release_admission_closure": True,
                "candidate_binding_map_duplicate_release_candidate_ids": [],
                "trial_state_ledger_present": True,
                "trial_state_ledger_validation_valid": True,
                "trial_state_ledger_candidate_binding_map_validated": True,
                "trial_state_ledger_candidate_count": len(candidate_ids),
                "trial_state_ledger_release_admission_candidate_count": len(candidate_ids),
                "trial_state_ledger_release_only_admission_candidate_count": 0,
                "trial_state_ledger_blocked_trial_count": len(candidate_ids),
                "release_gate_candidate_ids": candidate_ids,
                "candidate_binding_map_release_candidate_ids": candidate_ids,
                "trial_state_ledger_release_candidate_ids": candidate_ids,
                "blocker_count": 0,
                "blockers": [],
            },
        },
    )
    _write_json(
        run_dir / "dft_scf_hardware_goal_completion_audit_current.json",
        {
            "schema_version": "dse.dft_scf_hardware.goal_completion_audit.v1",
            "status": "in_progress",
        },
    )
    _seed_complete_dse_obligation(run_dir, candidate_ids)
    return run_dir, search_summary


def test_complete_dse_workload_count_contract_is_strict_six_scf() -> None:
    budget = build_release_cardinality_budget()
    report = build_release_l4_runtime_cost_report({"legal_candidate_count": 7})

    assert DEFAULT_FROZEN_WORKLOAD_CASE_COUNT == 6
    assert budget["frozen_workload_case_count"] == 6
    assert budget["frozen_workload_cases_target_min"] == 6
    assert budget["frozen_workload_cases_hard_cap"] == 6
    assert report["frozen_workload_case_count"] == 6
    assert report["required_l4_evidence_rows"] == 42


def test_deployment_coordination_summary_assigns_three_lanes_and_best_candidates(tmp_path: Path) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )
    validation = validate_dft_deployment_coordination_summary(payload)

    assert payload["schema_version"] == DFT_DEPLOYMENT_COORDINATION_SUMMARY_SCHEMA
    assert payload["status"] == "coordinated_current_best_with_open_release_blockers"
    assert payload["current_best_available"] is True
    assert payload["release_completion_eligible"] is False
    assert len(payload["process_lanes"]) == 3
    assert payload["search_lane"]["status"] == "closed_for_current_coordination"
    assert payload["deployment_recommendations"]["fpga"]["best_candidate_id"] == "cand-fpga"
    assert payload["deployment_recommendations"]["fpga"]["blocker_count"] == 1
    assert payload["deployment_recommendations"]["asic"]["best_candidate_id"] == "cand-asic"
    assert payload["deployment_recommendations"]["asic"]["selected_device"] == "fsa0a_c_generic_core_tt1p8v25c"
    assert payload["deployment_recommendations"]["asic"]["blocker_count"] == 0
    assert payload["candidate_admission_claim_eligible"] is True
    assert payload["candidate_admission_audit"]["status"] == "passed"
    assert payload["complete_dse_release_obligation_passed"] is True
    assert payload["complete_dse_release_obligation"]["ledger_legal_candidate_count"] == 504
    assert payload["complete_dse_release_obligation"]["ledger_required_l4_evidence_row_count"] == 504 * 6
    assert payload["release_gate_candidate_admission_gate_passed"] is True
    assert payload["release_gate_candidate_admission_blocker_count"] == 0
    assert payload["release_gate_candidate_admission"]["status"] == "passed"
    assert payload["candidate_admission_audit"]["deployments"]["fpga"]["matched_binding_row_count"] == 1
    assert payload["candidate_admission_audit"]["deployments"]["asic"]["matched_binding_row_count"] == 1
    assert "full_goal_audit_not_complete" in {
        blocker["blocker_id"] for blocker in payload["coordination_blockers"]
    }
    assert validation["valid"] is True
    _validate_registered_schema(payload, "dse.dft.deployment_coordination_summary.v1")


def test_deployment_coordination_blocks_missing_complete_dse_trial_ledger(tmp_path: Path) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    (run_dir / "release_candidate_trial_ledger.json").unlink()

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )
    validation = validate_dft_deployment_coordination_summary(payload)

    assert payload["complete_dse_release_obligation_passed"] is False
    assert payload["best_deployment_claim_eligible"] is False
    assert payload["hardware_completion_eligible"] is False
    blocker_ids = {blocker["blocker_id"] for blocker in payload["coordination_blockers"]}
    assert "complete_dse_release_obligation_not_satisfied" in blocker_ids
    audit_blocker_ids = {
        blocker["blocker_id"]
        for blocker in payload["complete_dse_release_obligation"]["blockers"]
    }
    assert "release_candidate_trial_ledger_missing" in audit_blocker_ids
    assert validation["valid"] is False
    assert "missing_required_source_artifact:release_candidate_trial_ledger" in validation["errors"]


def test_deployment_coordination_blocks_stale_36_row_complete_dse_obligation(
    tmp_path: Path,
) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    stale_ids = _release_candidate_ids(36)
    _seed_complete_dse_obligation(run_dir, stale_ids)

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )
    validation = validate_dft_deployment_coordination_summary(payload)

    assert payload["complete_dse_release_obligation_passed"] is False
    assert payload["best_deployment_claim_eligible"] is False
    assert payload["raw_best_deployment_claim_eligible"] is True
    audit = payload["complete_dse_release_obligation"]
    assert audit["ledger_legal_candidate_count"] == 36
    assert audit["ledger_required_l4_evidence_row_count"] == 36 * 6
    assert {
        blocker["blocker_id"]
        for blocker in audit["blockers"]
    } >= {
        "release_candidate_trial_ledger_below_release_target_min",
        "candidate_binding_map_unique_release_candidate_count_does_not_match_release_candidate_trial_ledger",
        "hardware_release_gate_candidate_count_does_not_match_release_candidate_trial_ledger",
    }
    assert validation["valid"] is True


def test_fpga_raw_target_feasibility_is_diagnostic_not_device_binding(tmp_path: Path) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    _write_json(
        run_dir / "dft_deployment_target_feasibility.json",
        {
            "schema_version": "dse.dft.deployment_target_feasibility.v1",
            "status": "target_feasibility_ready",
            "fpga_target_feasibility": {
                "status": "raw_package_feasible_target_selected",
                "target_selection_class": "raw_package_capacity_screen",
                "selected_device": "VU19P",
                "selected_part": "XCVU19P",
                "selected_package": "A3824-class raw package",
                "resource_fit": True,
                "bitstream_implementation_claim_eligible": False,
                "board_deployment_claim_eligible": False,
                "deployment_target_claim_eligible": False,
                "can_clear_physical_target_blocker": False,
                "claim_aware_next_gate": "per_kernel_vivado_part_or_platform_consensus",
            },
            "asic_target_binding": {
                "status": "bound_from_dc_kernel_row_consensus",
                "target_binding_claim_eligible": True,
                "selected_target_library": "fsa0a_c_generic_core_tt1p8v25c",
            },
        },
    )
    _write_json(
        run_dir / "dft_deployment_target_feasibility_validation.json",
        {"schema_version": "dse.dft.deployment_target_feasibility_validation.v1", "valid": True, "errors": []},
    )

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )

    fpga = payload["deployment_recommendations"]["fpga"]
    fpga_blocker_ids = {blocker["blocker_id"] for blocker in fpga["blockers"]}
    assert fpga["status"] == "recommended_with_open_target_blockers"
    assert fpga["selected_device"] is None
    assert fpga["fpga_target_selection_class"] == "raw_package_capacity_screen"
    assert fpga["fpga_selected_part"] == "XCVU19P"
    assert fpga["fpga_resource_fit"] is True
    assert fpga["fpga_deployment_target_claim_eligible"] is False
    assert fpga["fpga_can_clear_physical_target_blocker"] is False
    assert fpga["fpga_claim_aware_next_gate"] == "per_kernel_vivado_part_or_platform_consensus"
    assert fpga["target_feasibility_status"] == "raw_package_feasible_target_selected"
    assert "fpga_physical_target_not_explicitly_proven" in fpga_blocker_ids
    assert "fpga_raw_target_feasible_but_bitstream_or_board_not_proven" not in fpga_blocker_ids
    assert "fpga_physical_target_not_explicitly_proven" in {
        blocker["blocker_id"] for blocker in payload["coordination_blockers"]
    }
    assert payload["deployment_recommendations"]["asic"]["status"] == "recommended_with_bound_target"
    assert (
        payload["deployment_recommendations"]["asic"]["selected_device"]
        == "fsa0a_c_generic_core_tt1p8v25c"
    )


def test_fpga_raw_target_feasibility_overclaim_remains_blocked(tmp_path: Path) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    _write_json(
        run_dir / "dft_deployment_target_feasibility.json",
        {
            "schema_version": "dse.dft.deployment_target_feasibility.v1",
            "status": "target_feasibility_ready",
            "fpga_target_feasibility": {
                "status": "raw_package_feasible_target_selected",
                "target_selection_class": "raw_package_capacity_screen",
                "selected_device": "VU19P",
                "selected_part": "XCVU19P",
                "selected_package": "A3824-class raw package",
                "resource_fit": True,
                "bitstream_implementation_claim_eligible": False,
                "board_deployment_claim_eligible": False,
                "deployment_target_claim_eligible": True,
                "can_clear_physical_target_blocker": True,
                "claim_aware_next_gate": "per_kernel_vivado_part_or_platform_consensus",
            },
            "asic_target_binding": {
                "status": "bound_from_dc_kernel_row_consensus",
                "target_binding_claim_eligible": True,
                "selected_target_library": "fsa0a_c_generic_core_tt1p8v25c",
            },
        },
    )
    _write_json(
        run_dir / "dft_deployment_target_feasibility_validation.json",
        {"schema_version": "dse.dft.deployment_target_feasibility_validation.v1", "valid": False, "errors": []},
    )

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )

    fpga = payload["deployment_recommendations"]["fpga"]
    fpga_blocker_ids = {blocker["blocker_id"] for blocker in fpga["blockers"]}
    assert fpga["selected_device"] is None
    assert fpga["fpga_deployment_target_claim_eligible"] is True
    assert fpga["fpga_can_clear_physical_target_blocker"] is True
    assert "fpga_raw_target_feasibility_overclaimed_deployment_target" in fpga_blocker_ids
    assert "fpga_raw_target_feasibility_attempted_to_clear_physical_target_blocker" in fpga_blocker_ids
    assert "fpga_raw_target_feasibility_overclaimed_deployment_target" in {
        blocker["blocker_id"] for blocker in payload["coordination_blockers"]
    }


def test_deployment_coordination_summary_fails_closed_without_search_closure(tmp_path: Path) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    search_summary.unlink()

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )
    validation = validate_dft_deployment_coordination_summary(payload)

    assert payload["status"] == "partial_blocked_not_complete"
    assert payload["current_best_available"] is True
    assert payload["search_lane"]["status"] == "incomplete"
    assert "search_lane_not_closed" in {blocker["blocker_id"] for blocker in payload["coordination_blockers"]}
    assert validation["valid"] is False
    assert "missing_required_source_artifact:search_effectiveness_loop_pilot_summary" in validation["errors"]


def test_deployment_coordination_summary_requires_dft_template_binding_report(tmp_path: Path) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    payload = json.loads(search_summary.read_text(encoding="utf-8"))
    for key in (
        "dft_template_binding_report_seen",
        "latest_dft_template_binding_gate_passed",
        "latest_dft_template_binding_status",
        "latest_dft_template_binding_report_ref",
        "latest_dft_template_bound_candidate_count",
        "latest_dft_template_blocked_candidate_count",
    ):
        payload.pop(key, None)
    _write_json(search_summary, payload)

    summary = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )

    assert summary["status"] == "partial_blocked_not_complete"
    assert summary["search_lane"]["status"] == "incomplete"
    assert summary["search_lane"]["dft_template_binding_report_seen"] is False
    assert "dft_template_binding_report_missing_for_dft_primary_proof" in {
        blocker["blocker_id"] for blocker in summary["search_lane"]["blockers"]
    }
    assert "search_lane_not_closed" in {
        blocker["blocker_id"] for blocker in summary["coordination_blockers"]
    }


def test_deployment_coordination_summary_blocks_unbound_winner_candidates(tmp_path: Path) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    binding_map = json.loads((run_dir / "dft_candidate_binding_map.json").read_text(encoding="utf-8"))
    binding_map["binding_rows"] = [
        {
            **binding_map["binding_rows"][0],
            "search_candidate_id": "search-other",
            "release_candidate_id": "cand-other",
            "evaluation_record_id": "cand-other",
            "legacy_candidate_id": "cand-other",
            "design_candidate_id": "design-other",
        }
    ]
    binding_map["search_candidate_count"] = 1
    binding_map["legal_release_candidate_count"] = 1
    binding_map["bound_candidate_count"] = 1
    binding_map["unique_release_candidate_count"] = 1
    _write_json(run_dir / "dft_candidate_binding_map.json", binding_map)
    _write_json(
        run_dir / "dft_candidate_binding_map_validation.json",
        {
            "schema_version": "dse.dft.candidate_binding_map_validation.v1",
            "valid": True,
            "row_count": 1,
            "errors": [],
        },
    )

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )

    assert payload["candidate_admission_claim_eligible"] is False
    audit = payload["candidate_admission_audit"]
    assert audit["status"] == "blocked"
    assert audit["deployments"]["fpga"]["matched_binding_row_count"] == 0
    assert audit["deployments"]["asic"]["matched_binding_row_count"] == 0
    assert "deployment_winner_not_bound_to_search_candidate" in {
        blocker["blocker_id"] for blocker in payload["coordination_blockers"]
    }


def test_deployment_coordination_summary_blocks_binding_map_without_release_admission_closure(
    tmp_path: Path,
) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    binding_map = json.loads((run_dir / "dft_candidate_binding_map.json").read_text(encoding="utf-8"))
    binding_map.update(
        {
            "status": "passed",
            "candidate_admission_status": "search_subset_not_release_admission_closed",
            "candidate_set_scope": "search_subset_with_release_only_admission_rows",
            "search_covers_full_release_universe": False,
            "release_admission_closure": False,
            "release_admission_claim_eligible": False,
            "legal_release_candidate_count": 3,
            "release_admission_candidate_count": 3,
            "release_only_admission_candidate_count": 1,
            "release_only_admission_candidate_ids": ["cand-release-only"],
            "candidate_universe_reconciliation": {
                **binding_map["candidate_universe_reconciliation"],
                "status": "search_subset_not_release_admission_closed",
                "candidate_admission_status": "search_subset_not_release_admission_closed",
                "candidate_set_scope": "search_subset_with_release_only_admission_rows",
                "search_covers_full_release_universe": False,
                "release_admission_closure": False,
                "release_admission_claim_eligible": False,
                "legal_release_candidate_count": 3,
                "release_admission_candidate_count": 3,
                "release_only_admission_candidate_count": 1,
                "release_only_admission_candidate_ids": ["cand-release-only"],
            },
        }
    )
    _write_json(run_dir / "dft_candidate_binding_map.json", binding_map)

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )
    validation = validate_dft_deployment_coordination_summary(payload)

    assert payload["current_best_available"] is True
    assert payload["candidate_admission_audit"]["status"] == "blocked"
    assert payload["candidate_admission_audit"]["release_admission_closure"] is False
    assert payload["candidate_admission_audit"]["release_admission_claim_eligible"] is False
    assert payload["candidate_admission_claim_eligible"] is False
    assert payload["best_deployment_claim_eligible"] is False
    assert payload["hardware_completion_eligible"] is False
    assert payload["trusted_best_architecture_claim_eligible"] is False
    blocker_ids = {blocker["blocker_id"] for blocker in payload["coordination_blockers"]}
    assert "candidate_binding_release_admission_not_closed" in blocker_ids
    assert "candidate_binding_release_admission_claim_not_eligible" in blocker_ids
    closure_blocker = next(
        blocker
        for blocker in payload["coordination_blockers"]
        if blocker["blocker_id"] == "candidate_binding_release_admission_not_closed"
    )
    assert closure_blocker["release_only_admission_candidate_ids"] == ["cand-release-only"]
    assert validation["valid"] is True
    _validate_registered_schema(payload, "dse.dft.deployment_coordination_summary.v1")


def test_deployment_coordination_summary_blocks_release_gate_candidate_admission_mismatch(
    tmp_path: Path,
) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    release_gate = json.loads(
        (run_dir / "dft_hardware_closure_release_gate.json").read_text(encoding="utf-8")
    )
    release_gate["status"] = "blocked_incomplete_hardware_release_gate"
    release_gate["release_gate_result"] = "blocked_incomplete_hardware_release_gate"
    release_gate["hardware_completion_eligible"] = False
    release_gate["candidate_count"] = 3
    release_gate["candidate_admission_gate_passed"] = False
    release_gate["candidate_admission_blocker_count"] = 2
    release_gate["candidate_admission_gate"].update(
        {
            "status": "blocked_candidate_admission_gate",
            "candidate_admission_gate_passed": False,
            "release_gate_candidate_count": 3,
            "candidate_binding_map_bound_candidate_count": 2,
            "candidate_binding_map_unique_release_candidate_count": 2,
            "trial_state_ledger_candidate_count": 2,
            "release_gate_candidate_ids": ["cand-asic", "cand-fpga", "cand-extra"],
            "candidate_binding_map_release_candidate_ids": ["cand-asic", "cand-fpga"],
            "trial_state_ledger_release_candidate_ids": ["cand-asic", "cand-fpga"],
            "blocker_count": 2,
            "blockers": [
                {
                    "blocker_id": "release_gate_candidate_set_does_not_match_candidate_binding_map",
                    "release_gate_only_candidate_ids": ["cand-extra"],
                    "binding_map_only_candidate_ids": [],
                },
                {
                    "blocker_id": "release_gate_candidate_set_does_not_match_trial_state_ledger",
                    "release_gate_only_candidate_ids": ["cand-extra"],
                    "trial_ledger_only_candidate_ids": [],
                },
            ],
        }
    )
    _write_json(run_dir / "dft_hardware_closure_release_gate.json", release_gate)

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )
    validation = validate_dft_deployment_coordination_summary(payload)

    assert payload["current_best_available"] is True
    assert payload["raw_best_deployment_claim_eligible"] is True
    assert payload["best_deployment_claim_eligible"] is False
    assert payload["candidate_admission_audit"]["status"] == "passed"
    assert payload["candidate_admission_claim_eligible"] is False
    assert payload["release_gate_candidate_admission_gate_passed"] is False
    assert payload["release_gate_candidate_admission_blocker_count"] == 2
    assert payload["hardware_completion_eligible"] is False
    assert payload["raw_hardware_completion_eligible"] is True
    assert payload["trusted_best_architecture_claim_eligible"] is False
    assert payload["raw_trusted_best_architecture_claim_eligible"] is True
    blocker_ids = {blocker["blocker_id"] for blocker in payload["coordination_blockers"]}
    assert "release_gate_candidate_admission_not_passed" in blocker_ids
    release_blocker = next(
        blocker
        for blocker in payload["coordination_blockers"]
        if blocker["blocker_id"] == "release_gate_candidate_admission_not_passed"
    )
    assert release_blocker["release_gate_candidate_count"] == 3
    assert release_blocker["candidate_binding_map_unique_release_candidate_count"] == 2
    assert release_blocker["trial_state_ledger_candidate_count"] == 2
    assert release_blocker["candidate_admission_blocker_count"] == 2
    assert release_blocker["candidate_admission_blockers"][0]["release_gate_only_candidate_ids"] == [
        "cand-extra"
    ]
    assert validation["valid"] is True
    _validate_registered_schema(payload, "dse.dft.deployment_coordination_summary.v1")


def test_deployment_coordination_summary_propagates_release_only_admission_gate_blockers(
    tmp_path: Path,
) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    release_gate = json.loads(
        (run_dir / "dft_hardware_closure_release_gate.json").read_text(encoding="utf-8")
    )
    release_gate["status"] = "blocked_incomplete_hardware_release_gate"
    release_gate["release_gate_result"] = "blocked_incomplete_hardware_release_gate"
    release_gate["hardware_completion_eligible"] = False
    release_gate["candidate_admission_gate_passed"] = False
    release_gate["candidate_admission_blocker_count"] = 2
    release_gate["candidate_admission_gate"].update(
        {
            "status": "blocked_candidate_admission_gate",
            "candidate_admission_gate_passed": False,
            "release_gate_candidate_count": 2,
            "candidate_binding_map_release_admission_candidate_count": 3,
            "candidate_binding_map_release_only_admission_candidate_count": 1,
            "candidate_binding_map_candidate_admission_status": (
                "search_subset_not_release_admission_closed"
            ),
            "candidate_binding_map_release_admission_closure": False,
            "trial_state_ledger_release_admission_candidate_count": 3,
            "trial_state_ledger_release_only_admission_candidate_count": 1,
            "blocker_count": 2,
            "blockers": [
                {
                    "blocker_id": "candidate_binding_map_search_subset_not_release_admission_closed",
                    "candidate_admission_status": "search_subset_not_release_admission_closed",
                    "release_admission_closure": False,
                    "release_only_admission_candidate_count": 1,
                    "release_only_admission_candidate_ids": ["cand-release-only"],
                },
                {
                    "blocker_id": "trial_state_ledger_has_release_only_admission_rows",
                    "release_only_admission_candidate_count": 1,
                    "release_only_admission_candidate_ids": ["cand-release-only"],
                },
            ],
        }
    )
    _write_json(run_dir / "dft_hardware_closure_release_gate.json", release_gate)

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )
    validation = validate_dft_deployment_coordination_summary(payload)

    assert payload["current_best_available"] is True
    assert payload["raw_best_deployment_claim_eligible"] is True
    assert payload["raw_hardware_completion_eligible"] is True
    assert payload["raw_trusted_best_architecture_claim_eligible"] is True
    assert payload["candidate_admission_audit"]["status"] == "passed"
    assert payload["candidate_admission_claim_eligible"] is False
    assert payload["best_deployment_claim_eligible"] is False
    assert payload["hardware_completion_eligible"] is False
    assert payload["trusted_best_architecture_claim_eligible"] is False
    assert payload["release_gate_candidate_admission_gate_passed"] is False
    assert payload["release_gate_candidate_admission_blocker_count"] == 3
    assert {
        blocker["blocker_id"]
        for blocker in payload["release_gate_candidate_admission_blockers"]
    } == {
        "candidate_binding_map_search_subset_not_release_admission_closed",
        "trial_state_ledger_has_release_only_admission_rows",
        "release_gate_candidate_binding_release_admission_not_closed",
    }
    top_blocker = next(
        blocker
        for blocker in payload["coordination_blockers"]
        if blocker["blocker_id"] == "release_gate_candidate_admission_not_passed"
    )
    assert top_blocker["candidate_binding_map_candidate_admission_status"] == (
        "search_subset_not_release_admission_closed"
    )
    assert top_blocker["candidate_binding_map_release_admission_closure"] is False
    assert top_blocker["candidate_binding_map_release_admission_candidate_count"] == 3
    assert top_blocker["candidate_binding_map_release_only_admission_candidate_count"] == 1
    assert top_blocker["trial_state_ledger_release_admission_candidate_count"] == 3
    assert top_blocker["trial_state_ledger_release_only_admission_candidate_count"] == 1
    assert {
        blocker["blocker_id"]
        for blocker in top_blocker["candidate_admission_blockers"]
    } == {
        "candidate_binding_map_search_subset_not_release_admission_closed",
        "trial_state_ledger_has_release_only_admission_rows",
        "release_gate_candidate_binding_release_admission_not_closed",
    }
    assert validation["valid"] is True
    _validate_registered_schema(payload, "dse.dft.deployment_coordination_summary.v1")


def test_deployment_coordination_summary_blocks_stale_release_gate_with_open_release_admission(
    tmp_path: Path,
) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    release_gate = json.loads(
        (run_dir / "dft_hardware_closure_release_gate.json").read_text(encoding="utf-8")
    )
    release_gate["candidate_admission_gate_passed"] = True
    release_gate["candidate_admission_blocker_count"] = 0
    release_gate["candidate_admission_gate"].update(
        {
            "status": "passed_candidate_admission_gate",
            "candidate_admission_gate_passed": True,
            "candidate_binding_map_candidate_admission_status": (
                "search_subset_not_release_admission_closed"
            ),
            "candidate_binding_map_release_admission_closure": False,
            "candidate_binding_map_release_only_admission_candidate_count": 1,
            "trial_state_ledger_release_only_admission_candidate_count": 1,
            "blocker_count": 0,
            "blockers": [],
        }
    )
    _write_json(run_dir / "dft_hardware_closure_release_gate.json", release_gate)

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )
    validation = validate_dft_deployment_coordination_summary(payload)

    assert payload["raw_best_deployment_claim_eligible"] is True
    assert payload["best_deployment_claim_eligible"] is False
    assert payload["release_gate_candidate_admission_gate_passed"] is False
    assert payload["release_gate_candidate_admission"]["status"] == "blocked"
    release_blockers = payload["release_gate_candidate_admission"]["blockers"]
    assert {
        blocker["blocker_id"] for blocker in release_blockers
    } == {"release_gate_candidate_binding_release_admission_not_closed"}
    assert release_blockers[0]["candidate_binding_map_release_only_admission_candidate_count"] == 1
    assert release_blockers[0]["trial_state_ledger_release_only_admission_candidate_count"] == 1
    top_blocker = next(
        blocker
        for blocker in payload["coordination_blockers"]
        if blocker["blocker_id"] == "release_gate_candidate_admission_not_passed"
    )
    assert top_blocker["candidate_binding_map_release_admission_closure"] is False
    assert top_blocker["candidate_binding_map_release_only_admission_candidate_count"] == 1
    assert top_blocker["trial_state_ledger_release_only_admission_candidate_count"] == 1
    assert validation["valid"] is True
    _validate_registered_schema(payload, "dse.dft.deployment_coordination_summary.v1")


def test_write_deployment_coordination_summary_artifacts(tmp_path: Path) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)
    out_dir = tmp_path / "coordination"

    status = write_dft_deployment_coordination_summary(
        run_dir=run_dir,
        out_dir=out_dir,
        search_loop_summary_path=search_summary,
    )

    assert status["status"] == "passed"
    assert status["current_best_available"] is True
    assert (out_dir / "dft_deployment_coordination_summary.json").exists()
    assert (out_dir / "dft_deployment_coordination_summary_validation.json").exists()
    assert (out_dir / "dft_deployment_coordination_summary_status.json").exists()
    _validate_registered_schema(
        json.loads((out_dir / "dft_deployment_coordination_summary.json").read_text()),
        "dse.dft.deployment_coordination_summary.v1",
    )
    _validate_registered_schema(
        json.loads((out_dir / "dft_deployment_coordination_summary_validation.json").read_text()),
        "dse.dft.deployment_coordination_summary_validation.v1",
    )
    _validate_registered_schema(
        json.loads((out_dir / "dft_deployment_coordination_summary_status.json").read_text()),
        "dse.dft.deployment_coordination_summary_status.v1",
    )


def test_deployment_coordination_validation_rejects_stale_deployment_summary_source(tmp_path: Path) -> None:
    run_dir, search_summary = _seed_coordination_inputs(tmp_path)

    payload = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_summary,
    )
    summary_path = run_dir / "dft_fpga_asic_deployment_summary.json"
    deployment_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    deployment_summary["best_deployment_claim_eligible"] = False
    _write_json(summary_path, deployment_summary)

    validation = validate_dft_deployment_coordination_summary(payload)

    assert validation["valid"] is False
    assert "stale_source_artifact:dft_fpga_asic_deployment_summary" in validation["errors"]
