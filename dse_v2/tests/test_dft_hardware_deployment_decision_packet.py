#!/usr/bin/env python3
"""DFT hardware deployment decision packet tests."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.reference_workloads.dft_hardware_deployment_decision_packet import (
    build_dft_hardware_deployment_decision_packet,
    validate_dft_hardware_deployment_decision_packet,
    write_dft_hardware_deployment_decision_packet,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_ready_sources(run_dir: Path) -> None:
    winner_payload = {
        "schema_version": "dse.dft.architecture_winner_resolution.v1",
        "status": "resolved_hardware_ppa_deployment_winners",
        "release_id": "release-decision-packet-test",
        "candidate_count": 2,
        "ranking_eligible_candidate_count": 2,
        "hardware_completion_eligible": True,
        "hardware_winner_resolution_eligible": True,
        "deliverable_complete": False,
        "deployments": {
            "fpga": {
                "status": "resolved_unique_hardware_ppa_winner",
                "resolved": True,
                "winner_resolution_basis": "design_candidate_id_duplicate_evaluation_rows_collapsed",
                "top_rank_candidate_count": 1,
                "top_rank_candidate_ids": ["cand-fpga"],
                "top_rank_design_count": 1,
                "top_rank_design_ids": ["design-fpga"],
                "duplicate_top_rank_evaluation_rows_collapsed": True,
                "winner": {
                    "deployment": "fpga",
                    "candidate_id": "cand-fpga",
                    "representative_candidate_id": "cand-fpga",
                    "design_candidate_id": "design-fpga",
                    "rank": 1,
                    "metrics": {
                        "fpga_total_slice_luts": 2867,
                        "fpga_total_dsps": 23,
                        "fpga_total_block_ram_tiles": 0,
                        "fpga_total_bonded_iob": 834,
                        "vivado_route_completed_kernel_count": 8,
                    },
                    "claim_boundary": "hardware-PPA only",
                },
                "required_next_evidence": [],
            },
            "asic": {
                "status": "resolved_unique_hardware_ppa_winner",
                "resolved": True,
                "winner_resolution_basis": "design_candidate_id_duplicate_evaluation_rows_collapsed",
                "top_rank_candidate_count": 1,
                "top_rank_candidate_ids": ["cand-asic"],
                "top_rank_design_count": 1,
                "top_rank_design_ids": ["design-asic"],
                "duplicate_top_rank_evaluation_rows_collapsed": True,
                "winner": {
                    "deployment": "asic",
                    "candidate_id": "cand-asic",
                    "representative_candidate_id": "cand-asic",
                    "design_candidate_id": "design-asic",
                    "rank": 1,
                    "metrics": {
                        "asic_total_cell_area": 718569.638518,
                        "asic_min_slack_ns": 0.0,
                        "asic_slack_deficit_ns": 0.0,
                        "dc_real_target_library_kernel_count": 8,
                    },
                    "claim_boundary": "hardware-PPA only",
                },
                "required_next_evidence": [],
            },
        },
        "fpga_best_architecture": {"candidate_id": "cand-fpga"},
        "asic_best_architecture": {"candidate_id": "cand-asic"},
    }
    _write_json(run_dir / "dft_architecture_winner_resolution.json", winner_payload)
    _write_json(
        run_dir / "dft_architecture_winner_resolution_validation.json",
        {"schema_version": "dse.dft.architecture_winner_resolution_validation.v1", "valid": True, "errors": []},
    )
    target_trust_gates = {
        "schema_version": (
            "dse.dft.hardware_deployment_recommendation_readiness."
            "target_selection_trust_gates.v1"
        ),
        "present": True,
        "all_trusted": True,
        "gates": {
            "fpga_target_catalog": {
                "trust_class": "fpga_target_catalog",
                "trusted": True,
                "source_ref_count": 1,
                "source_refs": [{"path": "fpga_catalog.json", "status": "test_fixture"}],
                "blockers": [],
            },
            "asic_target_library_probe": {
                "trust_class": "asic_target_library_probe",
                "trusted": True,
                "source_ref_count": 1,
                "source_refs": [{"path": "asic_probe.json", "status": "test_fixture"}],
                "blockers": [],
            },
        },
    }
    target_payload = {
        "schema_version": "dse.dft.hardware_deployment_target_selection.v1",
        "status": "target_selection_ready",
        "input_trust_gates": target_trust_gates["gates"],
        "deployment_target_selection_ready": True,
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "deployments": {
            "fpga": {
                "selection_status": "selected",
                "target_device_id": "fpga-large-test",
                "vendor": "amd-xilinx",
                "part": "xc7k480tffg1156-3",
                "family": "kintex-7",
                "capacity": {"slice_luts": 298600, "dsps": 1920, "block_ram_tiles": 1910},
                "capacity_units": "test-catalog-units",
                "source_refs": [{"path": "fpga_catalog.json", "status": "test_fixture"}],
                "deliverable_complete": False,
            },
            "asic": {
                "selection_status": "selected",
                "target_library_id": "fsa0a_c_generic_core_tt1p8v25c",
                "process_node": "library_defined",
                "pvt_corner": "tt_1p8v_25c",
                "voltage_v": 1.8,
                "temperature_c": 25,
                "source_refs": [{"path": "asic_probe.json", "status": "test_fixture"}],
                "deliverable_complete": False,
            },
        },
    }
    _write_json(run_dir / "dft_hardware_deployment_target_selection.json", target_payload)
    _write_json(
        run_dir / "dft_hardware_deployment_target_selection_validation.json",
        {"schema_version": "dse.dft.hardware_deployment_target_selection_validation.v1", "valid": True, "errors": []},
    )
    full_scf_gate = {
        "present": True,
        "artifact": "full_scf_end_to_end_comparison.json",
        "status": "blocked_temporary",
        "passed": False,
        "candidate_count": 2,
        "blocked_candidate_count": 2,
        "row_record_count": 12,
        "blocked_row_record_count": 12,
        "trusted_accelerated_numeric_source": False,
    }
    full_scf_workplan = {
        "required": True,
        "status": "required_full_scf_numerical_evidence_missing",
        "work_item_count": 2,
        "class_row_work_item_count": 12,
        "required_next_evidence": [
            {"task_id": "run_trusted_full_scf_qe_bundle", "reason": "trusted_evidence_missing"}
        ],
    }
    readiness_payload = {
        "schema_version": "dse.dft.hardware_deployment_recommendation_readiness.v1",
        "status": "ready_to_name_hardware_ppa_winners_not_final_recommendation",
        "release_id": "release-decision-packet-test",
        "candidate_count": 2,
        "ranking_eligible_candidate_count": 2,
        "can_name_hardware_ppa_winners": True,
        "fpga_can_name_winner": True,
        "asic_can_name_winner": True,
        "deployment_target_selection_ready": True,
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "hardware_completion_eligible": True,
        "hardware_winner_resolution_eligible": True,
        "deployment_target_selection_trust_gates": target_trust_gates,
        "deployments": {
            "fpga": {
                "status": "ready_to_name_hardware_ppa_winner_not_final_recommendation",
                "can_name_hardware_ppa_winner": True,
                "target_selection": {
                    "present": True,
                    "selection_present": True,
                    "deployment": "fpga",
                    "status": "target_selection_ready",
                    "ready_for_targeted_recommendation": True,
                    "selection_status": "selected",
                    "selected_target": {
                        "target_device_id": "fpga-large-test",
                        "part": "xc7k480tffg1156-3",
                        "vendor": "amd-xilinx",
                        "family": "kintex-7",
                    },
                    "source_refs": [{"path": "fpga_catalog.json", "status": "test_fixture"}],
                    "input_trust_gate": target_trust_gates["gates"]["fpga_target_catalog"],
                },
                "required_next_evidence": [],
                "final_recommendation_required_next_evidence": [
                    {"task_id": "fpga_full_scf_targeted_deployment_accounting", "deployment": "fpga"}
                ],
            },
            "asic": {
                "status": "ready_to_name_hardware_ppa_winner_not_final_recommendation",
                "can_name_hardware_ppa_winner": True,
                "target_selection": {
                    "present": True,
                    "selection_present": True,
                    "deployment": "asic",
                    "status": "target_selection_ready",
                    "ready_for_targeted_recommendation": True,
                    "selection_status": "selected",
                    "selected_target": {
                        "target_library_id": "fsa0a_c_generic_core_tt1p8v25c",
                        "process_node": "library_defined",
                        "pvt_corner": "tt_1p8v_25c",
                    },
                    "source_refs": [{"path": "asic_probe.json", "status": "test_fixture"}],
                    "input_trust_gate": target_trust_gates["gates"]["asic_target_library_probe"],
                },
                "required_next_evidence": [],
                "final_recommendation_required_next_evidence": [
                    {"task_id": "asic_full_scf_targeted_deployment_accounting", "deployment": "asic"}
                ],
            },
        },
        "full_scf_numerical_gate": full_scf_gate,
        "full_scf_numerical_closure_workplan": full_scf_workplan,
        "release_completion_gates": {"full_scf_numerical_passed": False, "deliverable_complete": False},
        "required_next_evidence": {"fpga": [], "asic": []},
        "final_recommendation_required_next_evidence": {
            "fpga": [{"task_id": "fpga_full_scf_targeted_deployment_accounting"}],
            "asic": [{"task_id": "asic_full_scf_targeted_deployment_accounting"}],
        },
        "forbidden_shortcuts": ["target selection treated as PPA"],
    }
    _write_json(run_dir / "dft_hardware_deployment_recommendation_readiness.json", readiness_payload)
    _write_json(
        run_dir / "dft_hardware_deployment_recommendation_readiness_validation.json",
        {"schema_version": "dse.dft.hardware_deployment_recommendation_readiness_validation.v1", "valid": True, "errors": []},
    )


def _attach_target_selection_trust_gate_evidence(run_dir: Path) -> None:
    trust_gates = {
        "schema_version": (
            "dse.dft.hardware_deployment_recommendation_readiness."
            "target_selection_trust_gates.v1"
        ),
        "present": True,
        "all_trusted": True,
        "gates": {
            "fpga_target_catalog": {
                "trust_class": "fpga_target_catalog",
                "trusted": True,
                "source_ref_count": 1,
                "blockers": [],
            },
            "asic_target_library_probe": {
                "trust_class": "asic_target_library_probe",
                "trusted": True,
                "source_ref_count": 1,
                "blockers": [],
            },
        },
    }
    target_path = run_dir / "dft_hardware_deployment_target_selection.json"
    target_payload = _load(target_path)
    target_payload["input_trust_gates"] = trust_gates["gates"]
    _write_json(target_path, target_payload)

    readiness_path = run_dir / "dft_hardware_deployment_recommendation_readiness.json"
    readiness_payload = _load(readiness_path)
    readiness_payload["deployment_target_selection_trust_gates"] = trust_gates
    readiness_payload["deployments"]["fpga"]["target_selection"]["input_trust_gate"] = trust_gates["gates"][
        "fpga_target_catalog"
    ]
    readiness_payload["deployments"]["asic"]["target_selection"]["input_trust_gate"] = trust_gates["gates"][
        "asic_target_library_probe"
    ]
    _write_json(readiness_path, readiness_payload)


def test_decision_packet_names_scoped_winners_but_blocks_final_claim(tmp_path: Path) -> None:
    _seed_ready_sources(tmp_path)

    payload = build_dft_hardware_deployment_decision_packet(tmp_path)
    validation = validate_dft_hardware_deployment_decision_packet(payload)

    assert validation["valid"] is True
    assert payload["status"] == "scoped_hardware_ppa_planning_ready_final_recommendation_blocked"
    assert payload["planning_packet_ready"] is True
    assert payload["can_name_scoped_hardware_ppa_winners"] is True
    assert payload["deployment_target_selection_ready"] is True
    assert payload["full_scf_numerical_gate_passed"] is False
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert payload["deliverable_complete"] is False
    assert payload["deployments"]["fpga"]["scoped_hardware_ppa_winner"]["candidate_id"] == "cand-fpga"
    assert payload["deployments"]["fpga"]["selected_target"]["part"] == "xc7k480tffg1156-3"
    assert payload["deployments"]["asic"]["scoped_hardware_ppa_winner"]["design_candidate_id"] == "design-asic"
    assert payload["deployments"]["asic"]["selected_target"]["target_library_id"] == "fsa0a_c_generic_core_tt1p8v25c"
    assert any(
        blocker["blocker_id"] == "full_scf_numerical_gate_not_passed"
        for blocker in payload["final_claim_blockers"]
    )


def test_decision_packet_propagates_target_selection_trust_gates_without_final_upgrade(tmp_path: Path) -> None:
    _seed_ready_sources(tmp_path)
    _attach_target_selection_trust_gate_evidence(tmp_path)

    payload = build_dft_hardware_deployment_decision_packet(tmp_path)
    validation = validate_dft_hardware_deployment_decision_packet(payload)

    trust_gates = payload["deployment_target_selection_trust_gates"]
    assert trust_gates["all_trusted"] is True
    assert trust_gates["gates"]["fpga_target_catalog"]["trusted"] is True
    assert (
        payload["deployments"]["fpga"]["target_selection_trust_gate"]["trust_class"]
        == "fpga_target_catalog"
    )
    assert payload["deployments"]["asic"]["target_selection_trust_gate"]["trusted"] is True
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert payload["trusted_final_claim"] is False
    assert payload["deliverable_complete"] is False
    assert validation["valid"] is True


def test_decision_packet_writer_emits_validation_and_status(tmp_path: Path) -> None:
    _seed_ready_sources(tmp_path)

    status = write_dft_hardware_deployment_decision_packet(tmp_path)

    assert status["status"] == "passed"
    assert status["planning_packet_ready"] is True
    assert status["full_scf_numerical_gate_passed"] is False
    assert (tmp_path / "dft_hardware_deployment_decision_packet.json").exists()
    assert _load(tmp_path / "dft_hardware_deployment_decision_packet_validation.json")["valid"] is True
    status_artifact = _load(tmp_path / "dft_hardware_deployment_decision_packet_status.json")
    assert status_artifact["can_name_targeted_deployment_recommendation"] is False
    assert status_artifact["deliverable_complete"] is False


def test_decision_packet_validation_rejects_targeted_or_final_overclaim(tmp_path: Path) -> None:
    _seed_ready_sources(tmp_path)
    payload = build_dft_hardware_deployment_decision_packet(tmp_path)
    payload["can_name_final_recommendation"] = True
    payload["deployments"]["fpga"]["can_name_targeted_deployment_recommendation"] = True

    validation = validate_dft_hardware_deployment_decision_packet(payload)

    assert validation["valid"] is False
    assert "can_name_final_recommendation_must_remain_false" in validation["errors"]
    assert "fpga_can_name_targeted_deployment_recommendation_must_remain_false" in validation["errors"]
