#!/usr/bin/env python3
"""Goal-level anti-downgrade audit tests for DFT/QE full-SCF hardware DSE."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)
from dse_v2.reporting.complete_dse_claims import GOAL_REQUIREMENT_EVIDENCE_SPECS


_GOAL_REQUIREMENT_COUNT = len(GOAL_REQUIREMENT_EVIDENCE_SPECS)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _semantic_closure_section(*, overall_passed: bool = True) -> dict:
    check_ids = [
        "phase_hotspot_identity",
        "evaluation_policy_legality",
        "candidate_tier_absence",
        "coverage_vector_derivation",
        "reference_hash_admission",
    ]
    source_artifacts = {
        name: {
            "path": f"semantic_sources/{name}.json",
            "exists": True,
            "required": True,
            "sha256": f"{index:064x}",
            "hash_algorithm": "sha256",
        }
        for index, name in enumerate(
            [
                "domain_freeze",
                "candidate_universe_manifest",
                "candidate_legality_report",
                "hierarchical_funnel_search_report",
                "dft_candidate_binding_map",
                "dft_trial_state_ledger",
                "dft_scf_six_class_bundle_manifest",
                "reference_admission_ledger",
            ],
            start=1,
        )
    }
    return {
        "schema_version": "dse.dft_scf.semantic_audit_closure.v1",
        "overall_passed": overall_passed,
        "source_hash_backed": True,
        "source_artifacts": source_artifacts,
        "checks": [
            {
                "check_id": check_id,
                "passed": overall_passed,
                "blockers": [] if overall_passed else ["test_forced_semantic_blocker"],
                "evidence_refs": list(source_artifacts),
                "claim_boundary": "semantic closure only, not hardware completion",
            }
            for check_id in check_ids
        ],
        "claim_boundary": "semantic audit closure only; not final DFT hardware-DSE completion",
    }


def _write_file_backed_semantic_closure(
    run_dir: Path,
    *,
    overall_passed: bool = True,
) -> dict:
    source_dir = run_dir / "semantic_sources"
    source_refs = {}
    for name in [
        "domain_freeze",
        "candidate_universe_manifest",
        "candidate_legality_report",
        "hierarchical_funnel_search_report",
        "dft_candidate_binding_map",
        "dft_trial_state_ledger",
        "dft_scf_six_class_bundle_manifest",
        "reference_admission_ledger",
    ]:
        path = source_dir / f"{name}.json"
        _write_json(path, {"schema_version": f"test.{name}.v1", "name": name})
        source_refs[name] = {
            "path": f"semantic_sources/{name}.json",
            "exists": True,
            "required": True,
            "sha256": _sha256(path),
            "hash_algorithm": "sha256",
        }
    closure = _semantic_closure_section(overall_passed=overall_passed)
    closure["source_artifacts"] = source_refs
    _write_json(run_dir / "dft_audit_semantic_closure.json", closure)
    return closure


def _target_selection_trust_gates() -> dict:
    return {
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
        "claim_boundary": "target trust gates are audit inputs only",
    }


def _requirement_evidence_rows(deliverable_complete: bool) -> list[dict]:
    rows = []
    for index in range(1, _GOAL_REQUIREMENT_COUNT + 1):
        blocked = not deliverable_complete and index == _GOAL_REQUIREMENT_COUNT
        rows.append(
            {
                "requirement_id": f"done_when_{index:02d}",
                "source": f"docs/goal.md Done when {index}",
                "requirement": f"test requirement {index}",
                "semantic_hard_gate": True,
                "artifact_policy": "all",
                "artifact_names": [f"artifact_{index}.json"],
                "artifact_paths": [f"artifact_{index}.json"],
                "present_claimable_artifact_names": []
                if blocked
                else [f"artifact_{index}.json"],
                "required_target_claims": [],
                "evidence_status": "blocked_missing_input" if blocked else "trusted_pass",
                "claimable": not blocked,
                "blockers": ["test_fixture_incomplete"] if blocked else [],
            }
        )
    return rows


def _base_report(*, deliverable_complete: bool = False, trusted_winner: bool = False) -> dict:
    requirement_rows = _requirement_evidence_rows(deliverable_complete)
    target_trust_gates = _target_selection_trust_gates() if deliverable_complete else {}
    target_trust_gate_summary = {
        "present": True,
        "all_trusted": True,
        "trusted_gate_count": 2,
        "gate_count": 2,
        "blocked_gate_count": 0,
    } if deliverable_complete else {}
    target_input_trust_gates = {
        "fpga": target_trust_gates["gates"]["fpga_target_catalog"],
        "asic": target_trust_gates["gates"]["asic_target_library_probe"],
    } if deliverable_complete else {}
    return {
        "schema_version": "dse.final_report.v1",
        "selected_recommendation": {
            "trusted_winner": trusted_winner,
            "selection_status": "trusted" if trusted_winner else "no_trusted_recommendation",
        },
        "requirement_evidence_matrix": {
            "schema_version": "dse.complete_dse.requirement_evidence_audit_matrix.v1",
            "source_goal": "docs/goal.md",
            "claimability": "claimable" if deliverable_complete else "blocked",
            "deliverable_complete_allowed": deliverable_complete,
            "trusted_final_claim": deliverable_complete,
            "requirement_count": _GOAL_REQUIREMENT_COUNT,
            "blocked_requirement_count": 0 if deliverable_complete else 1,
            "status_taxonomy": [
                "vertical_slice_only",
                "MVP_partial",
                "blocked",
                "projection_only",
                "deliverable_complete",
            ],
            "completion_statuses": {
                "vertical_slice_only": False,
                "MVP_partial": not deliverable_complete,
                "blocked": not deliverable_complete,
                "projection_only": False,
                "deliverable_complete": deliverable_complete,
            },
            "requirement_rows": requirement_rows,
            "blockers": [] if deliverable_complete else [
                {
                    "requirement_id": "done_when_test",
                    "blockers": ["test_fixture_incomplete"],
                }
            ],
        },
        "dft_audit_semantic_closure": _semantic_closure_section(),
        "dft_evidence_ledger": {
            "present": True,
            "status": "audit_artifacts_present",
            "release_id": "release-audit",
            "deliverable_complete": deliverable_complete,
            "release_claim_gate": {
                "deliverable_complete": deliverable_complete,
                "blocked_candidate_count": 0 if deliverable_complete else 1,
            },
            "eda_summary": {
                "major_kernel_matrix_status": "passed",
                "major_kernel_matrix_trusted": True,
                "hardware_completion_eligible": deliverable_complete,
                "tool_availability_status": "passed",
                "ic_eda_tool_availability": {"path": "ic_eda_tool_availability.json"},
                "ic_eda_tool_availability_payload_status": "passed",
                "ic_eda_tool_availability_all_required_tools_available": True,
                "ic_eda_tool_availability_raw_attempt_count": 3,
                "ic_eda_tool_availability_completion_claim": "availability_only_not_kernel_ppa",
                "ic_eda_tool_availability_raw_completion_claim": "availability_only_not_kernel_ppa",
                "ic_eda_tool_availability_payload_claim_boundary_valid": True,
                "ic_eda_tool_availability_payload_claim_upgrade_detected": False,
                "ic_eda_tool_availability_kernel_ppa_evidence": False,
                "ic_eda_tool_availability_hardware_completion_eligible": False,
                "dft_hardware_evidence_matrix": {
                    "path": "dft_hardware_evidence_matrix.json",
                },
            },
        },
        "dft_trial_state_ledger": {
            "present": True,
            "status": "fail_closed_trial_ledger_present",
            "candidate_count": 1,
            "blocked_trial_count": 0 if deliverable_complete else 1,
            "completion_eligible": deliverable_complete,
            "deliverable_complete": deliverable_complete,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "trial state is orchestration/audit provenance only",
        },
        "dft_candidate_binding_map": {
            "present": True,
            "status": "fail_closed_candidate_binding_map_present",
            "search_candidate_count": 8,
            "bound_candidate_count": 8,
            "unmatched_candidate_count": 0,
            "duplicate_release_candidate_ids": [],
            "completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "candidate binding is heuristic ID provenance only",
        },
        "dft_hardware_completion_workplan": {
            "present": True,
            "status": "fail_closed_hardware_completion_workplan_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "required_work_item_count": 40,
            "blocked_work_item_count": 40,
            "candidate_specific_evidence_present_count": 0,
            "shared_microkernel_smoke_stage_present_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "hardware completion workplan is execution scheduling only",
        },
        "dft_hardware_closure_shards": {
            "present": True,
            "status": "fail_closed_hardware_closure_shards_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "unit_count": 8,
            "shard_count": 1,
            "work_item_count": 40,
            "blocked_work_item_count": 40,
            "candidate_specific_bundle_count": 0,
            "candidate_specific_evidence_present_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "hardware closure shards are parallel queue metadata only",
        },
        "dft_hardware_closure_packets": {
            "present": True,
            "status": "fail_closed_hardware_closure_packets_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "shard_count": 1,
            "packet_count": 1,
            "unit_count": 8,
            "work_item_count": 40,
            "blocked_work_item_count": 40,
            "expected_evidence_file_count": 160,
            "candidate_specific_bundle_count": 0,
            "candidate_specific_evidence_present_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "hardware closure packets are execution runbooks only",
        },
        "dft_hardware_closure_candidate_bundles": {
            "present": True,
            "status": "fail_closed_candidate_bundle_templates_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "bundle_count": 8,
            "bundle_ref_count": 8,
            "expected_evidence_file_count": 160,
            "raw_evidence_file_count": 0,
            "bundle_template_only": True,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "hardware closure candidate bundles are template contracts only",
        },
        "dft_hardware_closure_unit_provenance": {
            "present": True,
            "status": "fail_closed_hardware_closure_unit_provenance_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "staged_unit_count": 8,
            "unit_ref_count": 8,
            "global_provenance_file_count": 32,
            "raw_stage_evidence_file_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "hardware closure unit provenance is metadata only",
        },
        "dft_hardware_closure_raw_transcript_registration": {
            "present": True,
            "status": "fail_closed_hardware_closure_raw_transcript_registration_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "unit_count": 8,
            "registered_unit_count": 0,
            "blocked_unit_count": 0,
            "registered_raw_stage_evidence_file_count": 0,
            "present_raw_stage_evidence_file_count": 0,
            "missing_raw_stage_evidence_file_count": 160,
            "invalid_raw_stage_evidence_file_count": 0,
            "adjudication_result": "not_adjudicated_by_raw_transcript_registration",
            "passed_stage_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "raw transcript registration indexes existing raw refs only",
        },
        "dft_hardware_closure_evidence_intake": {
            "present": True,
            "status": "fail_closed_hardware_closure_evidence_intake_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "packet_count": 1,
            "unit_count": 8,
            "expected_evidence_file_count": 160,
            "present_evidence_file_count": 0,
            "missing_evidence_file_count": 160,
            "candidate_bundle_count": 0,
            "adjudication_status": "not_adjudicated_by_intake",
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "hardware closure intake is file-presence only",
        },
        "dft_hardware_closure_adjudication": {
            "present": True,
            "status": "fail_closed_hardware_closure_adjudication_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "packet_count": 1,
            "unit_count": 8,
            "stage_count": 40,
            "passed_stage_count": 0,
            "blocked_stage_count": 40,
            "files_present_unadjudicated_stage_count": 0,
            "expected_evidence_file_count": 160,
            "present_evidence_file_count": 0,
            "missing_evidence_file_count": 160,
            "candidate_bundle_count": 0,
            "adjudication_result": "not_adjudicated",
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "hardware closure adjudication is fail-closed stage ledger only",
        },
        "dft_hardware_closure_parsed_evidence": {
            "present": True,
            "status": "fail_closed_hardware_closure_parsed_evidence_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "packet_count": 1,
            "unit_count": 8,
            "stage_count": 40,
            "expected_parsed_result_count": 40,
            "present_parsed_result_count": 0,
            "missing_parsed_result_count": 40,
            "valid_parsed_result_count": 0,
            "invalid_parsed_result_count": 0,
            "parsed_verdict_counts": {"blocked": 0, "failed": 0, "inconclusive": 0, "passed": 0},
            "adjudication_result": "not_adjudicated_by_parsed_manifest",
            "passed_stage_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "hardware closure parsed evidence is parser/readiness only",
        },
        "dft_hardware_closure_parser_run": {
            "present": True,
            "status": "fail_closed_hardware_closure_parser_run_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "packet_count": 1,
            "unit_count": 8,
            "stage_count": 40,
            "parsed_result_written_count": 0,
            "blocked_stage_count": 40,
            "verdict_counts": {"blocked": 40, "failed": 0, "inconclusive": 0, "passed": 0},
            "adjudication_result": "not_adjudicated_by_parser_run",
            "passed_stage_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "hardware closure parser run is parser-output readiness only",
        },
        "dft_hardware_closure_gate_adjudication": {
            "present": True,
            "status": "fail_closed_hardware_closure_gate_adjudication_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "packet_count": 1,
            "unit_count": 8,
            "stage_count": 40,
            "stage_gate_passed_count": 0,
            "blocked_stage_count": 40,
            "failed_stage_count": 0,
            "unit_gate_passed_count": 0,
            "blocked_unit_count": 8,
            "failed_unit_count": 0,
            "adjudication_result": "blocked_incomplete_hard_gate_evidence",
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "hardware closure gate adjudication is per-stage only",
        },
        "dft_hardware_closure_release_gate": {
            "present": True,
            "status": "fail_closed_hardware_closure_release_gate_present",
            "release_id": "release-audit",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "unit_count": 8,
            "stage_count": 40,
            "stage_gate_passed_count": 40 if deliverable_complete else 0,
            "blocked_stage_count": 0 if deliverable_complete else 40,
            "failed_stage_count": 0,
            "unit_gate_passed_count": 8 if deliverable_complete else 0,
            "blocked_unit_count": 0 if deliverable_complete else 8,
            "failed_unit_count": 0,
            "candidate_gate_passed_count": 1 if deliverable_complete else 0,
            "blocked_candidate_count": 0 if deliverable_complete else 1,
            "failed_candidate_count": 0,
            "release_gate_result": (
                "all_candidates_passed_pending_deliverable_claim"
                if deliverable_complete
                else "blocked_incomplete_hardware_release_gate"
            ),
            "hardware_completion_eligible": deliverable_complete,
            "deliverable_complete": False,
            "validation": {"present": True, "valid": True, "error_count": 0},
            "claim_boundary": "hardware closure release gate is rollup only",
        },
        "dft_candidate_specific_ppa_provenance": {
            "present": True,
            "status": (
                "trusted_candidate_specific_ppa_provenance"
                if deliverable_complete
                else "blocked_candidate_specific_ppa_provenance"
            ),
            "validation": {"present": True, "valid": True, "error_count": 0},
            "winner_provenance_eligible": deliverable_complete,
            "unit_count": 8,
            "trusted_unit_count": 8 if deliverable_complete else 0,
            "blocked_unit_count": 0 if deliverable_complete else 8,
            "blocker_count": 0 if deliverable_complete else 8,
            "blocker_id_counts": {} if deliverable_complete else {"commands_not_executed": 8},
            "tie_breaker_work_item_count": 0 if deliverable_complete else 40,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": "candidate-specific PPA provenance blocks winner proof if command/tool provenance is missing",
        },
        "dft_architecture_winner_resolution": {
            "present": True,
            "status": (
                "resolved_hardware_ppa_deployment_winners"
                if deliverable_complete
                else "blocked_no_unique_hardware_ppa_winners"
            ),
            "validation": {"present": True, "valid": True, "error_count": 0},
            "hardware_winner_resolution_eligible": deliverable_complete,
            "trusted_best_architecture_claim_eligible": False,
            "deliverable_complete": False,
            "fpga_status": (
                "resolved_unique_hardware_ppa_winner"
                if deliverable_complete
                else "blocked_no_unique_hardware_ppa_winner"
            ),
            "asic_status": (
                "resolved_unique_hardware_ppa_winner"
                if deliverable_complete
                else "blocked_no_unique_hardware_ppa_winner"
            ),
            "fpga_top_rank_candidate_count": 1 if deliverable_complete else 2,
            "asic_top_rank_candidate_count": 1 if deliverable_complete else 2,
            "all_candidates_metric_tied": not deliverable_complete,
            "claim_boundary": "winner resolution is separate from deliverable completion",
        },
        "dft_hardware_deployment_recommendation_readiness": {
            "present": True,
            "status": (
                "ready_to_name_hardware_ppa_winners_not_final_recommendation"
                if deliverable_complete
                else "blocked_deployment_recommendation_evidence_pending"
            ),
            "validation": {"present": True, "valid": True, "error_count": 0},
            "fpga_status": (
                "ready_to_name_hardware_ppa_winner_not_final_recommendation"
                if deliverable_complete
                else "blocked_deployment_recommendation_evidence_pending"
            ),
            "asic_status": (
                "ready_to_name_hardware_ppa_winner_not_final_recommendation"
                if deliverable_complete
                else "blocked_deployment_recommendation_evidence_pending"
            ),
            "fpga_can_name_winner": deliverable_complete,
            "asic_can_name_winner": deliverable_complete,
            "can_name_hardware_ppa_winners": deliverable_complete,
            "deployment_target_selection_ready": deliverable_complete,
            "can_name_targeted_deployment_recommendation": False,
            "readiness_upgrade_detected": False,
            "can_name_final_recommendation": False,
            "deliverable_complete": False,
            "deployment_target_selection_trust_gates": target_trust_gates,
            "deployment_target_selection_trust_gate_summary": target_trust_gate_summary,
            "target_selection_input_trust_gates": target_input_trust_gates,
            "required_next_evidence_counts": {
                "fpga": 0 if deliverable_complete else 1,
                "asic": 0 if deliverable_complete else 1,
            },
            "final_recommendation_required_next_evidence_counts": {
                "fpga": 1,
                "asic": 1,
            },
            "claim_boundary": "deployment readiness is planning evidence and not a final recommendation",
        },
        "dft_deployment_comparator": {
            "present": True,
            "status": "target_recommendations_available" if deliverable_complete else "blocked_no_target_recommendations",
            "validation": {"present": True, "valid": True, "error_count": 0},
            "deployment_comparison_status": "target_recommendations_available" if deliverable_complete else "blocked",
            "fpga_recommendation_status": "unique_physical_winner",
            "fpga_recommendation_kind": "unique_candidate",
            "fpga_top_candidate_count": 1,
            "asic_recommendation_status": "unique_physical_winner",
            "asic_recommendation_kind": "unique_candidate",
            "asic_top_candidate_count": 1,
            "target_recommendation_available_count": 2 if deliverable_complete else 0,
            "cross_target_comparison_eligible": deliverable_complete,
            "hardware_completion_eligible_for_deployment_comparison": deliverable_complete,
            "single_cross_target_winner": None,
            "cross_target_recommendation_status": "no_single_cross_target_winner_without_user_objective",
            "non_physical_tie_breakers_used": False,
            "deliverable_complete": False,
            "claim_boundary": "comparator is decision support only",
        },
        "dft_deployment_selector": {
            "present": True,
            "status": "blocked_missing_explicit_objective",
            "selection_status": "blocked_missing_explicit_objective",
            "validation": {"present": True, "valid": True, "error_count": 0},
            "objective_present": False,
            "selected_candidate_id": None,
            "selected_deployment_target": None,
            "non_physical_tie_breakers_used": False,
            "deliverable_complete": False,
            "claim_boundary": "selector requires explicit objective",
        },
        "dft_l4_goal_binding": {
            "present": True,
            "status": "fail_closed_l4_goal_binding_present",
            "binding_status": "passed_current_goal_l4_bound",
            "l4_software_visible_proof_present": True,
            "final_closure_eligible": True,
            "deliverable_complete": False,
            "l4_matrix": {
                "coverage_status": "passed",
                "row_count": 36,
                "expected_row_count": 36,
                "blocked_row_count": 0,
                "candidate_count": 9,
                "workload_case_count": 4,
                "matrix_hash": "hash-l4",
            },
            "row_level_proofs": {
                "expected_gem5_l4_proof_count": 36,
                "present_gem5_l4_proof_count": 36,
            },
            "current_goal_binding": {
                "candidate_mapping_policy": "explicit_crosswalk",
                "workload_mapping_policy": "explicit_crosswalk",
                "step5_candidate_count": 1,
                "candidate_crosswalk_count": 1,
                "candidate_identity_binding_explicit": True,
                "workload_crosswalk_count": 1,
                "workload_identity_binding_explicit": True,
                "current_goal_l4_bound": True,
            },
            "validation": {"present": True, "valid": True, "error_count": 0, "warning_count": 0},
            "blockers": [],
            "claim_boundary": "L4 binding is software-visible proof only",
        },
        "dft_full_scf_evaluated_hybrid": {
            "present": True,
            "status": "ledger_artifact_bundle_present",
            "source": "dft_evidence_ledger.full_scf_hybrid_bundle",
            "required_artifacts_present": True,
            "prototype_boundary": "full_scf_evaluated_hybrid",
            "device_residency": "host_orchestrated_hybrid",
            "completion_claim": False,
            "numerical_correctness_claim_eligible": False,
            "ppa_claim_eligible": False,
        },
        "full_scf_evaluated_hybrid_costs": {
            "source": "full_scf_accelerator_descriptor.json",
            "required_cost_fields_present": True,
            "kernel_speedup": 3.5,
            "end_to_end_scf_speedup": 2.1,
            "host_bound_compute_cost_ms": 10.0,
            "transfer_cost_ms": 2.0,
            "synchronization_queueing_layout_cost_ms": 1.0,
        },
    }


def test_dft_scf_goal_audit_stays_in_progress_before_june_horizon(tmp_path):
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, _base_report(deliverable_complete=True, trusted_winner=True))
    _write_file_backed_semantic_closure(tmp_path)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 5, 31, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert audit["status"] == "in_progress"
    assert audit["completion_decision"] == "do_not_mark_complete_before_date_horizon"
    assert audit["horizon_reached"] is False
    assert audit["in_progress_requirements"][0]["requirement"].startswith("Use date")
    assert audit["blocked_requirements"] == []
    assert audit["failed_requirements"] == []


def test_dft_scf_goal_audit_blocks_hardware_completion_on_candidate_set_mismatch(tmp_path):
    report_path = tmp_path / "final_report.json"
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    report["dft_evidence_ledger"]["eda_summary"]["hardware_completion_eligible"] = False
    report["dft_deployment_decision_support"] = {
        "present": True,
        "release_completion_gates": {
            "candidate_set_consistency_status": "candidate_set_mismatch",
            "candidate_set_consistency_source": "dft_candidate_set_consistency.json",
            "release_gate_only_candidate_ids": ["cand-release-only"],
            "binding_map_only_candidate_ids": [],
            "trial_ledger_only_candidate_ids": [],
            "release_gate_missing_candidate_ids": [],
            "binding_map_missing_candidate_ids": ["cand-release-only"],
            "trial_ledger_missing_candidate_ids": ["cand-release-only"],
        },
        "trusted_final_claim": False,
        "deliverable_complete": False,
    }
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocker = next(
        item
        for item in audit["hardware_eligibility_blockers"]
        if item["blocker_id"] == "candidate_set_consistency_not_passed"
    )
    assert blocker["candidate_set_consistency_status"] == "candidate_set_mismatch"
    assert blocker["release_gate_only_candidate_ids"] == ["cand-release-only"]
    assert audit["summary"]["current_release_gate_hardware_completion_eligible"] is False
    blocked_requirements = {item["requirement"] for item in audit["blocked_requirements"]}
    assert "FPGA/ASIC hardware completion gate is eligible only after full per-kernel hard evidence" in blocked_requirements


def test_dft_scf_goal_audit_blocks_hardware_completion_on_candidate_set_validation_invalid(tmp_path):
    report_path = tmp_path / "final_report.json"
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    report["dft_evidence_ledger"]["eda_summary"]["hardware_completion_eligible"] = False
    report["dft_deployment_decision_support"] = {
        "present": True,
        "release_completion_gates": {
            "candidate_set_consistency_status": "candidate_sets_not_checked_validation_invalid",
            "candidate_set_consistency_source": "dft_candidate_set_consistency.json",
            "candidate_set_consistency_validation_valid": False,
            "release_gate_only_candidate_ids": [],
            "binding_map_only_candidate_ids": [],
            "trial_ledger_only_candidate_ids": [],
            "release_gate_missing_candidate_ids": [],
            "binding_map_missing_candidate_ids": [],
            "trial_ledger_missing_candidate_ids": [],
        },
        "trusted_final_claim": False,
        "deliverable_complete": False,
    }
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocker = next(
        item
        for item in audit["hardware_eligibility_blockers"]
        if item["blocker_id"] == "candidate_set_consistency_not_passed"
    )
    assert blocker["candidate_set_consistency_status"] == "candidate_sets_not_checked_validation_invalid"
    assert blocker["candidate_set_consistency_validation_valid"] is False
    assert audit["summary"]["current_release_gate_hardware_completion_eligible"] is False


def test_dft_scf_goal_audit_recomputes_candidate_set_sidecar_when_report_is_stale(tmp_path):
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    report["dft_evidence_ledger"]["eda_summary"]["hardware_completion_eligible"] = False
    report["dft_deployment_decision_support"] = {
        "present": True,
        "release_completion_gates": {
            "candidate_set_consistency_status": "candidate_sets_match",
            "candidate_set_consistency_source": "final_report_stale_fixture",
            "candidate_set_consistency_validation_valid": True,
            "release_gate_only_candidate_ids": [],
            "binding_map_only_candidate_ids": [],
            "trial_ledger_only_candidate_ids": [],
            "release_gate_missing_candidate_ids": [],
            "binding_map_missing_candidate_ids": [],
            "trial_ledger_missing_candidate_ids": [],
        },
        "trusted_final_claim": False,
        "deliverable_complete": False,
    }
    _write_json(tmp_path / "final_report.json", report)
    _write_json(
        tmp_path / "dft_candidate_set_consistency.json",
        {
            "schema_version": "dse.dft.candidate_set_consistency.v1",
            "status": "passed",
            "candidate_set_consistency_status": "candidate_sets_match",
            "required_sources": ["release_gate", "binding_map", "trial_ledger"],
            "candidate_sets": {
                "release_gate": {
                    "present": True,
                    "candidate_count": 2,
                    "candidate_ids": ["cand-a", "cand-b"],
                    "raw_candidate_ids": ["cand-a", "cand-b"],
                    "duplicate_candidate_ids": [],
                },
                "binding_map": {
                    "present": True,
                    "candidate_count": 1,
                    "candidate_ids": ["cand-a"],
                    "raw_candidate_ids": ["cand-a"],
                    "duplicate_candidate_ids": [],
                },
                "trial_ledger": {
                    "present": True,
                    "candidate_count": 1,
                    "candidate_ids": ["cand-a"],
                    "raw_candidate_ids": ["cand-a"],
                    "duplicate_candidate_ids": [],
                },
            },
            "required_source_count": 3,
            "present_source_count": 3,
            "missing_sources": [],
            "empty_sources": [],
            "duplicate_sources": [],
            "all_required_sources_present": True,
            "all_sources_nonempty": True,
            "all_required_sources_match_and_nonempty": True,
            "union_candidate_count": 2,
            "union_candidate_ids": ["cand-a", "cand-b"],
            "common_candidate_count": 2,
            "common_candidate_ids": ["cand-a", "cand-b"],
            "source_only_candidate_ids": {
                "release_gate": [],
                "binding_map": [],
                "trial_ledger": [],
            },
            "source_missing_candidate_ids": {
                "release_gate": [],
                "binding_map": [],
                "trial_ledger": [],
            },
            "release_gate_only_candidate_ids": [],
            "binding_map_only_candidate_ids": [],
            "trial_ledger_only_candidate_ids": [],
            "release_gate_missing_candidate_ids": [],
            "binding_map_missing_candidate_ids": [],
            "trial_ledger_missing_candidate_ids": [],
            "pairwise_mismatch_count": 0,
            "pairwise_mismatches": [],
            "blocker_count": 0,
            "blockers": [],
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=tmp_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocker = next(
        item
        for item in audit["hardware_eligibility_blockers"]
        if item["blocker_id"] == "candidate_set_consistency_not_passed"
    )
    assert blocker["candidate_set_consistency_status"] == (
        "candidate_sets_not_checked_validation_invalid"
    )
    assert blocker["candidate_set_consistency_source"] == (
        "dft_candidate_set_consistency.json:fresh_audit_validation"
    )
    assert blocker["candidate_set_consistency_validation_valid"] is False
    assert blocker["binding_map_missing_candidate_ids"] == ["cand-b"]
    assert blocker["trial_ledger_missing_candidate_ids"] == ["cand-b"]
    assert any(
        item["blocker_id"] == "candidate_set_mismatch"
        for item in blocker["candidate_set_blockers"]
    )
    assert audit["summary"]["current_release_gate_hardware_completion_eligible"] is False


def test_dft_scf_goal_audit_blocks_hardware_completion_on_deployment_alignment_mismatch(tmp_path):
    report_path = tmp_path / "final_report.json"
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    report["dft_evidence_ledger"]["eda_summary"]["hardware_completion_eligible"] = False
    report["dft_deployment_decision_support"] = {
        "present": True,
        "release_completion_gates": {
            "candidate_set_consistency_status": "candidate_sets_match",
            "candidate_set_consistency_source": "dft_candidate_set_consistency.json",
            "candidate_set_consistency_validation_valid": True,
            "deployment_candidate_alignment_status": "deployment_candidate_alignment_mismatch",
            "deployment_recommendation_candidate_ids": {
                "fpga": "cand-fpga",
                "asic": "cand-asic",
            },
            "deployment_candidate_ids_missing_from_candidate_set": {},
            "deployment_candidate_ids_missing_from_full_scf": {"fpga": ["cand-fpga"]},
            "deployment_candidate_alignment_blockers": [
                {
                    "blocker_id": "deployment_candidate_not_in_full_scf_candidate_set",
                    "deployment": "fpga",
                    "candidate_id": "cand-fpga",
                }
            ],
        },
        "trusted_final_claim": False,
        "deliverable_complete": False,
    }
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocker = next(
        item
        for item in audit["hardware_eligibility_blockers"]
        if item["blocker_id"] == "deployment_candidate_alignment_not_passed"
    )
    assert blocker["deployment_candidate_alignment_status"] == "deployment_candidate_alignment_mismatch"
    assert blocker["full_scf_missing"] == {"fpga": ["cand-fpga"]}
    assert audit["summary"]["current_release_gate_hardware_completion_eligible"] is False


def test_dft_scf_goal_audit_blocks_hardware_completion_on_deployment_source_mismatch(tmp_path):
    report_path = tmp_path / "final_report.json"
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    report["dft_evidence_ledger"]["eda_summary"]["hardware_completion_eligible"] = False
    report["dft_deployment_decision_support"] = {
        "present": True,
        "release_completion_gates": {
            "candidate_set_consistency_status": "candidate_sets_match",
            "candidate_set_consistency_source": "dft_candidate_set_consistency.json",
            "candidate_set_consistency_validation_valid": True,
            "deployment_source_consensus_status": "deployment_source_consensus_mismatch",
            "deployment_source_consensus_blockers": [
                {
                    "blocker_id": "deployment_candidate_source_mismatch",
                    "deployment": "fpga",
                    "candidate_id_by_source": {
                        "winner_resolution": "cand-fpga",
                        "deployment_summary": "cand-other-fpga",
                    },
                }
            ],
        },
        "trusted_final_claim": False,
        "deliverable_complete": False,
    }
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocker = next(
        item
        for item in audit["hardware_eligibility_blockers"]
        if item["blocker_id"] == "deployment_source_consensus_mismatch"
    )
    assert blocker["deployment_source_consensus_status"] == "deployment_source_consensus_mismatch"
    assert blocker["source_consensus_blockers"][0]["deployment"] == "fpga"
    assert audit["summary"]["current_release_gate_hardware_completion_eligible"] is False


def test_dft_scf_goal_audit_blocks_hardware_completion_on_deployment_target_mismatch(tmp_path):
    report_path = tmp_path / "final_report.json"
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    report["dft_evidence_ledger"]["eda_summary"]["hardware_completion_eligible"] = False
    report["dft_deployment_decision_support"] = {
        "present": True,
        "release_completion_gates": {
            "candidate_set_consistency_status": "candidate_sets_match",
            "candidate_set_consistency_source": "dft_candidate_set_consistency.json",
            "candidate_set_consistency_validation_valid": True,
            "deployment_target_consensus_status": "deployment_target_consensus_mismatch",
            "deployment_target_consensus_blockers": [
                {
                    "blocker_id": "fpga_selected_device_source_mismatch",
                    "deployment": "fpga",
                    "selected_device_by_source": {
                        "coordination_summary": "xc7a35tcsg324-1",
                        "target_feasibility": "VU19P",
                    },
                }
            ],
        },
        "trusted_final_claim": False,
        "deliverable_complete": False,
    }
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocker = next(
        item
        for item in audit["hardware_eligibility_blockers"]
        if item["blocker_id"] == "deployment_target_consensus_mismatch"
    )
    assert blocker["deployment_target_consensus_status"] == "deployment_target_consensus_mismatch"
    assert blocker["target_consensus_blockers"][0]["deployment"] == "fpga"
    assert audit["summary"]["current_release_gate_hardware_completion_eligible"] is False


def test_dft_scf_goal_audit_reports_blocked_when_evidence_is_incomplete_after_horizon(tmp_path):
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, _base_report(deliverable_complete=False, trusted_winner=False))

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert audit["status"] == "in_progress"
    assert audit["completion_decision"] == "do_not_mark_complete_blocked_or_incomplete"
    blocked_requirements = {item["requirement"] for item in audit["blocked_requirements"]}
    assert "Release claim gate allows deliverable_complete only after all required evidence closes" in blocked_requirements
    assert "FPGA/ASIC hardware completion gate is eligible only after full per-kernel hard evidence" in blocked_requirements
    assert "IC/EDA availability bridge is Step5-visible and not PPA evidence" not in blocked_requirements
    assert "DFT candidate binding map is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware completion workplan is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware closure shard queue is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware closure packet/runbook index is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware closure candidate-bundle templates are Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware closure unit provenance staging is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware closure raw transcript registration is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware closure evidence intake is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware closure adjudication ledger is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware closure parsed-evidence manifest is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware closure parser run is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware closure gate adjudication is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT hardware closure release gate is Step5-visible and fail-closed" not in blocked_requirements
    assert "DFT L4/gem5 goal binding artifact is Step5-visible and fail-closed" not in blocked_requirements
    assert "L4/gem5 proof is explicitly bound to current DFT candidates and workloads" not in blocked_requirements
    assert {
        blocker["blocker_id"] for blocker in audit["hardware_eligibility_blockers"]
    } == {"blocked_candidate_kernel_units"}
    assert {
        blocker["blocker_id"] for blocker in audit["deliverable_completion_blockers"]
    } == {
        "release_gate_cannot_mark_deliverable_complete",
        "hardware_completion_not_eligible",
        "release_claim_gate_deliverable_complete_false",
    }
    assert audit["failed_requirements"] == []


def test_dft_scf_goal_audit_rejects_trusted_winner_without_dft_deliverable_complete(tmp_path):
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, _base_report(deliverable_complete=False, trusted_winner=True))

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert audit["status"] == "failed"
    assert audit["completion_decision"] == "do_not_mark_complete_failed_requirements"
    assert audit["failed_requirements"][0]["requirement"] == (
        "Step5 trusted winner is not upgraded while DFT deliverable completion is false"
    )


def test_dft_scf_goal_audit_rejects_targeted_deployment_recommendation_upgrade(tmp_path):
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    readiness["can_name_targeted_deployment_recommendation"] = True
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert audit["status"] == "failed"
    failed_requirements = {item["requirement"] for item in audit["failed_requirements"]}
    assert "DFT deployment recommendation readiness is Step5-visible and non-final" in failed_requirements
    assert audit["summary"]["dft_hardware_deployment_recommendation_readiness_targeted_ready"] is True


def test_dft_scf_goal_audit_rejects_clamped_readiness_upgrade_detection(tmp_path):
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    readiness["can_name_targeted_deployment_recommendation"] = False
    readiness["readiness_upgrade_detected"] = True
    readiness["safety_findings"] = ["readiness_attempted_targeted_deployment_recommendation_upgrade"]
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert audit["status"] == "failed"
    failed_requirements = {item["requirement"] for item in audit["failed_requirements"]}
    assert "DFT deployment recommendation readiness is Step5-visible and non-final" in failed_requirements
    assert audit["summary"]["dft_hardware_deployment_recommendation_readiness_upgrade_detected"] is True


def test_dft_scf_goal_audit_blocks_completion_without_real_ic_eda_probe(tmp_path):
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    eda_summary = report["dft_evidence_ledger"]["eda_summary"]
    eda_summary["tool_availability_status"] = "not_recorded"
    eda_summary["ic_eda_tool_availability"] = None
    eda_summary["ic_eda_tool_availability_payload_status"] = None
    eda_summary["ic_eda_tool_availability_all_required_tools_available"] = None
    eda_summary["ic_eda_tool_availability_raw_attempt_count"] = 0
    eda_summary["ic_eda_tool_availability_completion_claim"] = ""
    eda_summary["ic_eda_tool_availability_payload_claim_boundary_valid"] = False
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocked_requirements = {item["requirement"] for item in audit["blocked_requirements"]}
    assert audit["status"] == "in_progress"
    assert "IC/EDA availability bridge is Step5-visible and not PPA evidence" in blocked_requirements


def test_dft_scf_goal_audit_blocks_availability_if_it_is_mislabeled_as_ppa(tmp_path):
    report = _base_report(deliverable_complete=False, trusted_winner=False)
    report["dft_evidence_ledger"]["eda_summary"]["ic_eda_tool_availability_kernel_ppa_evidence"] = True
    report["dft_evidence_ledger"]["eda_summary"]["ic_eda_tool_availability_completion_claim"] = "kernel_ppa"
    report["dft_evidence_ledger"]["eda_summary"]["ic_eda_tool_availability_raw_completion_claim"] = "kernel_ppa"
    report["dft_evidence_ledger"]["eda_summary"]["ic_eda_tool_availability_payload_claim_boundary_valid"] = False
    report["dft_evidence_ledger"]["eda_summary"]["ic_eda_tool_availability_payload_claim_upgrade_detected"] = True
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocked_requirements = {item["requirement"] for item in audit["blocked_requirements"]}
    assert "IC/EDA availability bridge is Step5-visible and not PPA evidence" in blocked_requirements
    assert audit["failed_requirements"] == []


def test_dft_scf_goal_audit_blocks_missing_l4_goal_binding(tmp_path):
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    report.pop("dft_l4_goal_binding")
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocked_requirements = {item["requirement"] for item in audit["blocked_requirements"]}
    assert audit["status"] == "in_progress"
    assert "DFT L4/gem5 goal binding artifact is Step5-visible and fail-closed" in blocked_requirements
    assert "L4/gem5 proof is explicitly bound to current DFT candidates and workloads" in blocked_requirements


def test_dft_scf_goal_audit_blocks_l4_visibility_without_current_goal_crosswalk(tmp_path):
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    binding = report["dft_l4_goal_binding"]
    binding["binding_status"] = "blocked_l4_visible_but_identity_or_workload_unbound"
    binding["final_closure_eligible"] = False
    binding["current_goal_binding"]["candidate_mapping_policy"] = "separate_l4_matrix_no_wave36_candidate_equivalence"
    binding["current_goal_binding"]["workload_mapping_policy"] = "legacy_qe_mainflow_not_six_scf"
    binding["current_goal_binding"]["candidate_identity_binding_explicit"] = False
    binding["current_goal_binding"]["workload_identity_binding_explicit"] = False
    binding["current_goal_binding"]["current_goal_l4_bound"] = False
    binding["validation"]["warning_count"] = 2
    binding["blockers"] = [
        "candidate_identity_crosswalk_missing_or_incomplete",
        "workload_identity_crosswalk_missing_or_incomplete",
    ]
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocked_requirements = {item["requirement"] for item in audit["blocked_requirements"]}
    assert "DFT L4/gem5 goal binding artifact is Step5-visible and fail-closed" not in blocked_requirements
    assert "L4/gem5 proof is explicitly bound to current DFT candidates and workloads" in blocked_requirements
    assert audit["failed_requirements"] == []



def test_dft_scf_goal_audit_requires_semantic_closure_artifact(tmp_path):
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    report.pop("dft_audit_semantic_closure")
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocked_requirements = {item["requirement"] for item in audit["blocked_requirements"]}
    assert audit["status"] == "in_progress"
    assert "DFT semantic audit closure artifact is source-hash backed and passed" in blocked_requirements
    assert audit["summary"]["dft_audit_semantic_closure_valid"] is False


def test_dft_scf_goal_audit_rejects_failed_semantic_closure(tmp_path):
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    report["dft_audit_semantic_closure"] = _semantic_closure_section(overall_passed=False)
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocked = [
        item
        for item in audit["blocked_requirements"]
        if item["requirement"] == "DFT semantic audit closure artifact is source-hash backed and passed"
    ]
    assert blocked
    assert set(blocked[0]["evidence"]["failed_checks"]) == {
        "phase_hotspot_identity",
        "evaluation_policy_legality",
        "candidate_tier_absence",
        "coverage_vector_derivation",
        "reference_hash_admission",
    }

def test_dft_scf_goal_audit_can_pass_after_horizon_with_closed_evidence(tmp_path):
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, _base_report(deliverable_complete=True, trusted_winner=True))
    _write_file_backed_semantic_closure(tmp_path)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert audit["status"] == "complete"
    assert audit["completion_decision"] == "ready_to_mark_complete"
    assert audit["blocked_requirements"] == []
    assert audit["failed_requirements"] == []
    assert audit["hardware_eligibility_blockers"] == []
    assert audit["deliverable_completion_blockers"] == []

# --- run2 comparator/selector/admissibility regression coverage merged during RUN5 integration ---
def test_dft_scf_goal_audit_blocks_contradictory_deployment_comparator_eligibility(tmp_path):
    report = _base_report(deliverable_complete=False, trusted_winner=False)
    comparator = report["dft_deployment_comparator"]
    comparator["status"] = "partial_recommendation_available"
    comparator["deployment_comparison_status"] = "partial_recommendation_available"
    comparator["fpga_recommendation_status"] = "blocked_no_fpga_recommendation"
    comparator["fpga_recommendation_kind"] = "blocked"
    comparator["target_recommendation_available_count"] = 1
    comparator["cross_target_comparison_eligible"] = False
    comparator["hardware_completion_eligible_for_deployment_comparison"] = True
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    deployment_item = next(
        item
        for item in audit["prompt_to_artifact_checklist"]
        if item["requirement"] == "FPGA-vs-ASIC deployment comparator is replayable and does not collapse physical ties"
    )
    assert deployment_item["status"] == "blocked"
    assert deployment_item["evidence"]["target_recommendation_available_count"] == 1
    assert deployment_item["evidence"]["cross_target_comparison_eligible"] is False
    assert deployment_item["evidence"]["hardware_completion_eligible_for_deployment_comparison"] is True
    assert audit["summary"]["dft_deployment_comparator_safe"] is False


def test_dft_scf_goal_audit_separates_hardware_gate_from_ledger_candidate_placeholders(tmp_path):
    report = _base_report(deliverable_complete=False, trusted_winner=False)
    release_claim_gate = report["dft_evidence_ledger"]["release_claim_gate"]
    release_claim_gate.update(
        {
            "deliverable_complete": False,
            "hardware_release_gate_eligible": True,
            "ledger_candidate_claims_eligible": False,
            "candidate_claim_requirement_satisfied": True,
            "candidate_claim_requirement_source": "canonical_hardware_release_gate",
            "all_candidate_claims_eligible": False,
            "blocked_candidate_ids": ["diagnostic-placeholder-candidate"],
            "deliverable_completion_blockers": [
                {
                    "blocker_id": "ledger_candidate_rows_diagnostic_only_after_hardware_release_gate",
                    "reason": "generic ledger rows are diagnostics once the canonical hardware gate is eligible",
                },
                {
                    "blocker_id": "external_goal_gates_not_evaluated_by_candidate_ledger",
                    "reason": "reference/date/final goal gates remain outside the candidate ledger",
                },
            ],
        }
    )
    eda_summary = report["dft_evidence_ledger"]["eda_summary"]
    eda_summary["hardware_completion_eligible"] = True
    eda_summary["hardware_release_gate_eligible"] = True
    release_gate = report["dft_hardware_closure_release_gate"]
    release_gate.update(
        {
            "stage_gate_passed_count": 40,
            "blocked_stage_count": 0,
            "unit_gate_passed_count": 8,
            "blocked_unit_count": 0,
            "candidate_gate_passed_count": 1,
            "blocked_candidate_count": 0,
            "release_gate_result": "hardware_completion_eligible_pending_deliverable_claim",
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
            "deliverable_completion_blockers": [
                {
                    "blocker_id": "release_gate_cannot_mark_deliverable_complete",
                    "reason": "deliverable completion is owned by the goal-level claim gate",
                }
            ],
        }
    )
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    checklist = {item["requirement"]: item for item in audit["prompt_to_artifact_checklist"]}
    release_item = checklist["Release claim gate allows deliverable_complete only after all required evidence closes"]
    blocked_requirements = {item["requirement"] for item in audit["blocked_requirements"]}
    assert release_item["status"] == "passed"
    assert release_item["evidence"]["fail_closed_after_hardware_release_gate"] is True
    assert release_item["evidence"]["current_release_gate_hardware_completion_eligible"] is True
    assert release_item["evidence"]["candidate_claim_requirement_satisfied"] is True
    assert "Release claim gate allows deliverable_complete only after all required evidence closes" not in blocked_requirements
    assert audit["summary"]["release_claim_gate_fail_closed_after_hardware"] is True
    assert audit["summary"]["deliverable_complete"] is False


def test_dft_scf_goal_audit_surfaces_l4_accelerated_qe_blocker_summary(tmp_path):
    report = _base_report(deliverable_complete=False, trusted_winner=False)
    report["dft_l4_goal_binding"]["accelerated_qe_blocker_summary"] = {
        "schema_version": "dse.dft.l4_accelerated_qe_blocker_summary.v1",
        "status": "blocked_missing_accelerated_qe_numeric_evidence",
        "requirements": {"row_count": 12, "candidate_count": 2, "workload_case_count": 6},
        "index": {
            "status": "not_configured",
            "row_count": 0,
            "blockers": ["accelerated_numeric_evidence_not_configured"],
        },
        "l4_matrix": {
            "blocked_row_count": 12,
            "blocker_counts": {"missing_accelerated_qe_kernel_numeric_outputs": 12},
        },
        "commands": {
            "campaign_producer_command_template": [
                "/usr/bin/python3",
                "dse_v2/scripts/dse/run_qe_accelerated_numeric_producer.py",
                "--fail-on-blocked",
            ]
        },
        "claim_boundary": "actionability only; not claim closure",
    }
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    l4_item = next(
        item
        for item in audit["prompt_to_artifact_checklist"]
        if item["requirement"] == "DFT L4/gem5 goal binding artifact is Step5-visible and fail-closed"
    )
    assert l4_item["evidence"]["accelerated_qe_blocker_summary"]["status"] == (
        "blocked_missing_accelerated_qe_numeric_evidence"
    )
    assert audit["summary"]["l4_accelerated_qe_blocker_status"] == (
        "blocked_missing_accelerated_qe_numeric_evidence"
    )


def test_dft_scf_goal_audit_consumes_target_selection_trust_gates_without_completion_upgrade(tmp_path):
    report = _base_report(deliverable_complete=False, trusted_winner=False)
    trust_gates = _target_selection_trust_gates()
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    readiness["deployment_target_selection_ready"] = True
    readiness["deployment_target_selection_trust_gates"] = trust_gates
    readiness["deployment_target_selection_trust_gate_summary"] = {
        "present": True,
        "all_trusted": True,
        "trusted_gate_count": 2,
        "gate_count": 2,
        "blocked_gate_count": 0,
    }
    readiness["target_selection_input_trust_gates"] = {
        "fpga": trust_gates["gates"]["fpga_target_catalog"],
        "asic": trust_gates["gates"]["asic_target_library_probe"],
    }
    readiness["deployments"] = {
        "fpga": {
            "target_selection_input_trust_gate": trust_gates["gates"]["fpga_target_catalog"],
        },
        "asic": {
            "target_selection_input_trust_gate": trust_gates["gates"]["asic_target_library_probe"],
        },
    }
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    item = next(
        row
        for row in audit["prompt_to_artifact_checklist"]
        if row["requirement"] == "DFT deployment target-selection trust gates are Step5-visible and non-final"
    )
    assert item["status"] == "passed"
    assert item["evidence"]["trust_gate_summary"] == {
        "present": True,
        "all_trusted": True,
        "trusted_gate_count": 2,
        "gate_count": 2,
        "blocked_gate_count": 0,
    }
    assert item["evidence"]["target_selection_input_trust_gates"]["fpga"]["trusted"] is True
    assert audit["summary"]["dft_hardware_deployment_recommendation_readiness_target_trust_gates_all_trusted"] is True
    assert audit["summary"]["dft_hardware_deployment_recommendation_readiness_target_trust_gate_count"] == 2
    assert audit["summary"]["deliverable_complete"] is False
    assert audit["status_classification"]["deliverable_complete"] is False



def test_dft_scf_goal_audit_blocks_missing_requirement_evidence_matrix(tmp_path):
    report = _base_report(deliverable_complete=False, trusted_winner=False)
    report.pop("requirement_evidence_matrix", None)
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    item = next(
        row for row in audit["prompt_to_artifact_checklist"]
        if row["requirement"] == "docs/goal.md Done-when requirement-evidence matrix is present and fail-closed"
    )
    assert item["status"] == "blocked"
    assert item["evidence"]["present"] is False
    assert audit["requirement_evidence_matrix"]["present"] is False
    assert audit["status_classification"]["blocked"] is True
    assert audit["status_classification"]["deliverable_complete"] is False


def test_dft_scf_goal_audit_requirement_matrix_count_tracks_goal_specs(tmp_path):
    report = _base_report(deliverable_complete=False, trusted_winner=False)
    rows = report["requirement_evidence_matrix"]["requirement_rows"]
    report["requirement_evidence_matrix"]["requirement_count"] = len(rows)
    report["requirement_evidence_matrix"]["blocked_requirement_count"] = len(
        [
            row
            for row in rows
            if row["claimable"] is not True or row["blockers"]
        ]
    )
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert audit["requirement_evidence_matrix"]["present"] is True
    assert audit["requirement_evidence_matrix"]["requirement_count"] == len(
        GOAL_REQUIREMENT_EVIDENCE_SPECS
    )
    assert not any(
        error.startswith("requirement_row_count_mismatch")
        for error in audit["requirement_evidence_matrix"]["matrix_errors"]
    )


def test_dft_scf_goal_audit_tracks_live_requirement_specs(tmp_path, monkeypatch):
    from dse_v2 import reporting as reporting_pkg
    from dse_v2.reporting import complete_dse_claims as complete_dse_claims_mod

    original_specs = complete_dse_claims_mod.GOAL_REQUIREMENT_EVIDENCE_SPECS
    extra_spec = {
        "requirement_id": "done_when_17",
        "source": "docs/goal.md Done when 17",
        "requirement": "Adaptive requirement spec extension is consumed dynamically by the audit.",
        "artifact_names": ("adaptive_requirement_spec_extension.json",),
        "artifact_policy": "all",
    }
    monkeypatch.setattr(
        complete_dse_claims_mod,
        "GOAL_REQUIREMENT_EVIDENCE_SPECS",
        original_specs + (extra_spec,),
    )
    monkeypatch.setattr(
        reporting_pkg.complete_dse_claims,
        "GOAL_REQUIREMENT_EVIDENCE_SPECS",
        original_specs + (extra_spec,),
    )

    report = _base_report(deliverable_complete=False, trusted_winner=False)
    rows = report["requirement_evidence_matrix"]["requirement_rows"]
    rows.append(
        {
            "requirement_id": extra_spec["requirement_id"],
            "source": extra_spec["source"],
            "requirement": extra_spec["requirement"],
            "semantic_hard_gate": True,
            "artifact_policy": "all",
            "artifact_names": list(extra_spec["artifact_names"]),
            "artifact_paths": list(extra_spec["artifact_names"]),
            "present_claimable_artifact_names": [],
            "required_target_claims": [],
            "evidence_status": "blocked_missing_input",
            "claimable": False,
            "blockers": ["test_fixture_incomplete"],
        }
    )
    report["requirement_evidence_matrix"]["requirement_count"] = len(rows)
    report["requirement_evidence_matrix"]["blocked_requirement_count"] = len(
        [
            row
            for row in rows
            if row["claimable"] is not True or row["blockers"]
        ]
    )
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert audit["requirement_evidence_matrix"]["requirement_count"] == len(
        complete_dse_claims_mod.GOAL_REQUIREMENT_EVIDENCE_SPECS
    )
    assert audit["requirement_evidence_matrix"]["valid_fail_closed"] is True


def test_dft_scf_goal_audit_surfaces_exact_status_classification(tmp_path):
    report = _base_report(deliverable_complete=False, trusted_winner=False)
    requirement_rows = _requirement_evidence_rows(True)
    for row in requirement_rows[:2]:
        row["present_claimable_artifact_names"] = []
        row["evidence_status"] = "blocked_missing_input"
        row["claimable"] = False
        row["blockers"] = ["test_fixture_projection_or_blocker"]
    report["requirement_evidence_matrix"] = {
        "schema_version": "dse.complete_dse.requirement_evidence_audit_matrix.v1",
        "source_goal": "docs/goal.md",
        "claimability": "blocked",
        "deliverable_complete_allowed": False,
        "trusted_final_claim": False,
        "blocked_requirement_count": 2,
        "requirement_count": _GOAL_REQUIREMENT_COUNT,
        "completion_statuses": {
            "vertical_slice_only": False,
            "MVP_partial": True,
            "blocked": True,
            "projection_only": True,
            "deliverable_complete": False,
        },
        "status_taxonomy": [
            "vertical_slice_only",
            "MVP_partial",
            "blocked",
            "projection_only",
            "deliverable_complete",
        ],
        "requirement_rows": requirement_rows,
        "blockers": [
            {
                "requirement_id": row["requirement_id"],
                "blockers": row["blockers"],
            }
            for row in requirement_rows[:2]
        ],
    }
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert audit["status_classification"] == {
        "vertical_slice_only": False,
        "MVP_partial": True,
        "blocked": True,
        "projection_only": True,
        "deliverable_complete": False,
    }
    item = next(
        row for row in audit["prompt_to_artifact_checklist"]
        if row["requirement"] == "docs/goal.md Done-when requirement-evidence matrix is present and fail-closed"
    )
    assert item["status"] == "passed"
    assert item["evidence"]["blocked_requirement_count"] == 2


def test_dft_scf_goal_audit_blocks_forged_claimable_requirement_evidence_matrix_without_rows(tmp_path):
    report = _base_report(deliverable_complete=False, trusted_winner=False)
    report["requirement_evidence_matrix"] = {
        "schema_version": "dse.complete_dse.requirement_evidence_audit_matrix.v1",
        "source_goal": "docs/goal.md",
        "claimability": "claimable",
        "deliverable_complete_allowed": True,
        "trusted_final_claim": True,
        "blocked_requirement_count": 0,
        "requirement_count": _GOAL_REQUIREMENT_COUNT,
        "completion_statuses": {
            "vertical_slice_only": False,
            "MVP_partial": False,
            "blocked": False,
            "projection_only": False,
            "deliverable_complete": True,
        },
        "status_taxonomy": [
            "vertical_slice_only",
            "MVP_partial",
            "blocked",
            "projection_only",
            "deliverable_complete",
        ],
        "requirement_rows": [],
        "blockers": [],
    }
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=report_path,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    item = next(
        row for row in audit["prompt_to_artifact_checklist"]
        if row["requirement"] == "docs/goal.md Done-when requirement-evidence matrix is present and fail-closed"
    )
    assert item["status"] == "blocked"
    assert audit["requirement_evidence_matrix"]["valid_fail_closed"] is False
    assert "requirement_rows_missing" in audit["requirement_evidence_matrix"]["matrix_errors"]
    assert audit["status_classification"]["deliverable_complete"] is False

def test_dft_scf_goal_audit_rehashes_file_backed_semantic_closure_sources(tmp_path):
    run_dir = tmp_path / "run"
    source_dir = run_dir / "semantic_sources"
    source_names = [
        "domain_freeze",
        "candidate_universe_manifest",
        "candidate_legality_report",
        "hierarchical_funnel_search_report",
        "dft_candidate_binding_map",
        "dft_trial_state_ledger",
        "dft_scf_six_class_bundle_manifest",
        "reference_admission_ledger",
    ]
    source_refs = {}
    for name in source_names:
        path = source_dir / f"{name}.json"
        _write_json(path, {"schema_version": f"test.{name}.v1", "name": name})
        source_refs[name] = {
            "path": f"semantic_sources/{name}.json",
            "exists": True,
            "required": True,
            "sha256": _sha256(path),
            "hash_algorithm": "sha256",
        }
    closure = _semantic_closure_section(overall_passed=True)
    closure["source_artifacts"] = source_refs
    _write_json(run_dir / "dft_audit_semantic_closure.json", closure)
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    _write_json(run_dir / "final_report.json", report)

    mutated = source_dir / "dft_trial_state_ledger.json"
    _write_json(mutated, {"schema_version": "test.dft_trial_state_ledger.v1", "mutated": True})

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=run_dir,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocked = [
        item
        for item in audit["blocked_requirements"]
        if item["requirement"] == "DFT semantic audit closure artifact is source-hash backed and passed"
    ]
    assert blocked
    assert blocked[0]["evidence"]["source"]["kind"] == "file"
    assert "dft_trial_state_ledger:source_hash_mismatch" in blocked[0]["evidence"]["source_hash_errors"]
    assert audit["summary"]["dft_audit_semantic_closure_source_hash_backed"] is False


def test_dft_scf_goal_audit_rejects_embedded_fake_semantic_closure_hashes(tmp_path):
    run_dir = tmp_path / "run"
    report = _base_report(deliverable_complete=True, trusted_winner=True)
    closure = _semantic_closure_section(overall_passed=True)
    closure["source_artifacts"] = {
        "domain_freeze": {
            "path": "semantic_sources/domain_freeze.json",
            "exists": True,
            "required": True,
            "sha256": "f" * 64,
            "hash_algorithm": "sha256",
        }
    }
    report["dft_audit_semantic_closure"] = closure
    _write_json(run_dir / "final_report.json", report)

    audit = build_dft_scf_hardware_goal_completion_audit(
        final_report=run_dir / "final_report.json",
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    blocked = [
        item
        for item in audit["blocked_requirements"]
        if item["requirement"] == "DFT semantic audit closure artifact is source-hash backed and passed"
    ]
    assert blocked
    assert blocked[0]["evidence"]["source"]["kind"] == "final_report_section"
    assert audit["summary"]["dft_audit_semantic_closure_source_hash_backed"] is False
    assert audit["summary"]["dft_audit_semantic_closure_valid"] is False
