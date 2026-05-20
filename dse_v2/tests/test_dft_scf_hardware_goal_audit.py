#!/usr/bin/env python3
"""Goal-level anti-downgrade audit tests for DFT/QE full-SCF hardware DSE."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def _base_report(*, deliverable_complete: bool = False, trusted_winner: bool = False) -> dict:
    return {
        "schema_version": "dse.final_report.v1",
        "selected_recommendation": {
            "trusted_winner": trusted_winner,
            "selection_status": "trusted" if trusted_winner else "no_trusted_recommendation",
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
        },
    }


def test_dft_scf_goal_audit_stays_in_progress_before_june_horizon(tmp_path):
    report_path = tmp_path / "final_report.json"
    _write_json(report_path, _base_report(deliverable_complete=True, trusted_winner=True))

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
