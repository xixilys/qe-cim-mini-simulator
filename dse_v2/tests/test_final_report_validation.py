#!/usr/bin/env python3
"""Regression tests for generic DSE final report claim gating."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.reporting.final_report import (
    generate_final_report_artifacts,
    validate_report_claims,
    write_step5_report_artifacts,
)


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _seed_minimal_trusted_run(run_dir: Path) -> None:
    run_dir.mkdir(parents=True)
    required = [
        "manifest.json",
        "artifact_manifest.json",
        "verdict.json",
        "design_point.json",
        "architecture.json",
        "mapping.json",
        "workload_package.json",
        "workload_graph.json",
        "graph_lowering_report.json",
        "simulation_request.json",
        "simulation_result.json",
        "numerical_validation.json",
        "phase_breakdown.csv",
        "resource_summary.csv",
        "data_movement_summary.csv",
        "systemc_stdout.log",
        "systemc_stderr.log",
        "gem5_systemc_blockers.json",
    ]
    _write_json(run_dir / "manifest.json", {
        "schema_version": "dse.manifest.v1",
        "run_id": "trusted_run",
        "workload": "sparse_profile",
        "workload_family": "sparse_la",
        "workload_profile": "sparse_la",
        "workload_importer": "generic_json",
        "backend": "systemc",
        "evidence_mode": "debug",
        "cli_command": ["python3", "dse_v2/scripts/dse/run_full_flow_pilot.py"],
        "simulator_command": ["generic_sim"],
        "replay_metadata": {
            "python_replay_command": ["python3", "dse_v2/scripts/dse/run_full_flow_pilot.py"],
            "simulator_replay_command": ["generic_sim"],
        },
        "required_evidence_files": required,
    })
    _write_json(run_dir / "artifact_manifest.json", {"schema_version": "dse.artifact_manifest.v1", "artifacts": []})
    _write_json(run_dir / "verdict.json", {
        "schema_version": "dse.verdict.v1",
        "run_id": "trusted_run",
        "backend": "systemc",
        "evidence_mode": "debug",
        "trusted_for_final_ranking": True,
        "numerical_validation_passed": True,
        "numerical_validation_scope": "generic_systemc_timing_numeric_reference",
        "numerical_error_metrics": {"failed_check_count": 0, "max_abs_error": 0.0, "max_rel_error": 0.0},
        "required_coverage": ["load_csr", "spmv", "norm"],
        "missing_required_coverage": [],
        "gem5_systemc_blockers": [
            {"id": "gem5_systemc_binding", "detail": "L4 binding is blocked in this run."}
        ],
        "evidence_gaps": ["gem5+SystemC path remains blocked."],
    })
    _write_json(run_dir / "design_point.json", {"design_point_id": "trusted_run"})
    _write_json(run_dir / "architecture.json", {
        "architecture_id": "arch-1",
        "architecture_family": "generic_heterogeneous_pilot",
        "status": "implemented",
        "trusted_final_eligible": True,
    })
    _write_json(run_dir / "mapping.json", {
        "mapping_id": "mapping-1",
        "mapping_policy": "seeded",
        "search_status": "single_candidate",
    })
    _write_json(run_dir / "workload_package.json", {
        "schema_version": "dse.workload_package.v1",
        "workload_id": "sparse_profile",
        "workload_family": "sparse_la",
        "source": {"kind": "generated", "provenance": "test"},
        "profile": {"profile_id": "sparse_la", "profile_version": "v1", "required_coverage": ["load_csr", "spmv", "norm"]},
        "importer": {"importer_id": "generic_json", "importer_version": "v1", "claim_boundary": "full_workload"},
        "graph": {"graph_id": "sparse_profile", "nodes": {"load_csr": {}, "spmv": {}, "norm": {}}, "edges": []},
        "constraints": {},
        "calibration": {},
        "domain_metadata": {},
    })
    _write_json(run_dir / "workload_graph.json", {"graph_id": "sparse_profile", "nodes": {"load_csr": {}, "spmv": {}, "norm": {}}, "edges": []})
    _write_json(run_dir / "graph_lowering_report.json", {
        "schema_version": "dse.graph_lowering_report.v1",
        "source_graph_id": "sparse_profile",
        "executable_graph_id": "sparse_profile.lowered",
        "status": "lowered",
        "full_workload_eligible": True,
        "unsupported_constructs": [],
    })
    _write_json(run_dir / "simulation_request.json", {"run_id": "trusted_run"})
    _write_json(run_dir / "simulation_result.json", {
        "status": "passed",
        "backend": "systemc",
        "metrics": {"latency_ms": 3.0, "power_w": 5.0, "energy_j": 0.015},
        "numerical_validation": {
            "artifact": "numerical_validation.json",
            "status": "pass",
            "passed": True,
            "scope": "generic_systemc_timing_numeric_reference",
            "summary": {"failed_check_count": 0, "max_abs_error": 0.0, "max_rel_error": 0.0},
        },
    })
    _write_json(run_dir / "numerical_validation.json", {
        "schema_version": "dse.numerical_validation.v1",
        "status": "pass",
        "passed": True,
        "scope": "generic_systemc_timing_numeric_reference",
        "profile_domain_correctness_claimed": False,
        "domain_correctness_boundary": "Validates timing-level numeric outputs only.",
        "summary": {"check_count": 4, "failed_check_count": 0, "max_abs_error": 0.0, "max_rel_error": 0.0},
        "checks": [],
    })
    (run_dir / "phase_breakdown.csv").write_text(
        "phase,node_id,op_type,device,start_ns,end_ns,latency_ns,latency_ms,cycles_estimate,clock_mhz,status,unavailable_reason\n"
        "load_csr,load_csr,dma_load,fpga-0,0,1000000,1000000,1.0,250000,250,available,\n"
        "spmv,spmv,spmv,fpga-0,1000000,2500000,1500000,1.5,375000,250,available,\n"
        "norm,norm,reduction,fpga-0,2500000,3000000,500000,0.5,125000,250,available,\n",
        encoding="utf-8",
    )
    (run_dir / "resource_summary.csv").write_text("device,compute_percent\ngpu-0,80\n", encoding="utf-8")
    (run_dir / "data_movement_summary.csv").write_text("edge_id,status\n", encoding="utf-8")
    (run_dir / "systemc_stdout.log").write_text("", encoding="utf-8")
    (run_dir / "systemc_stderr.log").write_text("", encoding="utf-8")
    _write_json(run_dir / "gem5_systemc_blockers.json", {"blockers": ["gem5_systemc_binding"]})


def test_final_report_artifacts_validate_trusted_claims(tmp_path):
    run_dir = tmp_path / "trusted_run"
    _seed_minimal_trusted_run(run_dir)

    result = generate_final_report_artifacts(run_dir)

    assert result["validation_passed"] is True
    assert result["trusted_claim_count"] == 3
    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "claim_validation.json").read_text(encoding="utf-8"))
    assert report["selected_recommendation"]["status"] == "not_selected"
    assert report["trusted_ranking"][0]["trusted_scope"].startswith("single-run feasibility")
    assert report["numerical_validation"]["passed"] is True
    assert report["workload"]["profile_id"] == "sparse_la"
    assert report["workload"]["importer_id"] == "generic_json"
    assert validation["errors"] == []
    assert (run_dir / "final_report.md").exists()


def test_final_report_surfaces_low_fidelity_screening_without_trusting_it(tmp_path):
    run_dir = tmp_path / "trusted_run_with_low_fidelity"
    _seed_minimal_trusted_run(run_dir)
    low_fidelity_artifacts = [
        "l1_evaluation_result.json",
        "l1_promotion_decision.json",
        "l2_evaluation_result.json",
        "l2_promotion_decision.json",
        "low_fidelity_screening_summary.json",
    ]
    _write_json(run_dir / "l1_evaluation_result.json", {
        "schema_version": "dse.step2.l1_evaluation_result.v1",
        "fidelity_level_achieved": "L1",
        "status": "passed",
        "design_point_id": "trusted_run",
        "family": "F1",
        "metrics": {"latency_ms": 2.5, "energy_j": 0.012},
        "feasible": True,
        "confidence": 0.82,
        "promotion_score": 0.88,
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
    })
    _write_json(run_dir / "l1_promotion_decision.json", {
        "schema_version": "dse.step2.low_fidelity_promotion_decision.v1",
        "artifact": "l1_promotion_decision.json",
        "from_layer": "L1",
        "to_layer": "L2",
        "decision": "promote",
        "promote": True,
        "promotion_score": 0.88,
        "confidence": 0.82,
        "threshold": 0.60,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
    })
    _write_json(run_dir / "l2_evaluation_result.json", {
        "schema_version": "dse.step2.l2_evaluation_result.v1",
        "fidelity_level_achieved": "L2",
        "status": "passed",
        "design_point_id": "trusted_run",
        "family": "F1",
        "metrics": {"latency_ms": 2.8, "energy_j": 0.014},
        "feasible": True,
        "confidence": 0.74,
        "mape_percent": 9.0,
        "promotion_score": 0.78,
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
    })
    _write_json(run_dir / "l2_promotion_decision.json", {
        "schema_version": "dse.step2.low_fidelity_promotion_decision.v1",
        "artifact": "l2_promotion_decision.json",
        "from_layer": "L2",
        "to_layer": "L3",
        "decision": "promote",
        "promote": True,
        "promotion_score": 0.78,
        "confidence": 0.74,
        "threshold": 0.65,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
    })
    _write_json(run_dir / "low_fidelity_screening_summary.json", {
        "schema_version": "dse.step2.low_fidelity_screening_summary.v1",
        "required_for_step3": True,
        "passed": True,
        "status": "passed",
        "candidate_id": "candidate-1",
        "mapping_id": "mapping-1",
        "artifact_refs": {
            "l1_evaluation_result": "l1_evaluation_result.json",
            "l1_promotion_decision": "l1_promotion_decision.json",
            "l2_evaluation_result": "l2_evaluation_result.json",
            "l2_promotion_decision": "l2_promotion_decision.json",
            "low_fidelity_summary": "low_fidelity_screening_summary.json",
        },
        "required_artifacts": low_fidelity_artifacts,
        "promotion_scores": {"l1_to_l2": 0.88, "l2_to_l3": 0.78},
        "thresholds": {"l1_to_l2": 0.60, "l2_to_l3": 0.65},
        "confidence": {"l1": 0.82, "l2": 0.74},
        "blockers": [],
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
        "trusted_final_eligible": False,
    })

    result = generate_final_report_artifacts(run_dir)

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "claim_validation.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")
    low_fidelity = report["low_fidelity_screening"]
    predicted_ids = {item["claim"]["claim_id"] for item in report["predicted_only_candidates"]}
    validation_by_id = {item["claim_id"]: item for item in validation["validations"]}

    assert result["trusted_claim_count"] == 3
    assert low_fidelity["present"] is True
    assert low_fidelity["passed"] is True
    assert low_fidelity["low_fidelity_role"] == "candidate_generator_only"
    assert low_fidelity["trusted_final_claim"] is False
    assert low_fidelity["excluded_from_trusted_ranking"] is True
    assert low_fidelity["missing_artifacts"] == []
    assert low_fidelity["l1"]["status"] == "passed"
    assert low_fidelity["l2"]["status"] == "passed"
    assert "l1_screening_candidate_signal" in predicted_ids
    assert "l2_screening_candidate_signal" in predicted_ids
    assert validation_by_id["l1_screening_candidate_signal"]["validation_status"] == "predicted_only"
    assert validation_by_id["l2_screening_candidate_signal"]["trusted"] is False
    assert all(item["backend"] == "systemc" for item in report["trusted_ranking"])
    assert "## Low-Fidelity Screening" in markdown


def test_predicted_only_winner_is_rejected(tmp_path):
    report = {
        "claims": [
            {
                "claim_id": "bad:winner",
                "claim_type": "best_architecture",
                "trusted": False,
                "predicted_only": True,
                "blocked": False,
                "backend": "analytical",
                "source_fidelity": "L1",
                "evidence_ids": [],
            }
        ],
        "selected_recommendation": {"status": "not_selected"},
    }

    validation = validate_report_claims(report, tmp_path)

    assert validation["passed"] is False
    assert any("predicted-only candidate cannot be a winner" in error for error in validation["errors"])


def test_trusted_blocked_winner_is_rejected(tmp_path):
    _write_json(tmp_path / "verdict.json", {"trusted_for_final_ranking": False})
    report = {
        "claims": [
            {
                "claim_id": "bad:blocked-winner",
                "claim_type": "best_architecture",
                "trusted": True,
                "predicted_only": False,
                "blocked": True,
                "backend": "systemc",
                "source_fidelity": "L3",
                "evidence_ids": ["verdict.json"],
            }
        ],
        "selected_recommendation": {"status": "not_selected"},
    }

    validation = validate_report_claims(report, tmp_path)

    assert validation["passed"] is False
    assert any("trusted claim cannot be blocked" in error for error in validation["errors"])


def test_trusted_claim_rejects_unresolved_evidence_path(tmp_path):
    report = {
        "claims": [
            {
                "claim_id": "bad:missing-evidence",
                "claim_type": "feasibility",
                "trusted": True,
                "predicted_only": False,
                "blocked": False,
                "backend": "systemc",
                "source_fidelity": "L3",
                "evidence_ids": ["missing-verdict.json"],
            }
        ],
        "selected_recommendation": {"status": "not_selected"},
    }

    validation = validate_report_claims(report, tmp_path)

    assert validation["passed"] is False
    assert any("evidence id does not resolve" in error for error in validation["errors"])


def test_selected_recommendation_rejects_nonlocal_evidence_path(tmp_path):
    report = {
        "claims": [],
        "selected_recommendation": {
            "status": "selected",
            "backend": "systemc",
            "predicted_only": False,
            "evidence_ids": ["../outside-verdict.json"],
        },
    }

    validation = validate_report_claims(report, tmp_path)

    assert validation["passed"] is False
    assert any("run-local relative path" in error for error in validation["errors"])


def test_step5_surfaces_hardware_ppa_ranking_without_selecting_winner(tmp_path):
    run_dir = tmp_path / "hardware_ppa_only"
    _seed_minimal_trusted_run(run_dir)
    verdict = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
    verdict["trusted_for_final_ranking"] = False
    _write_json(run_dir / "verdict.json", verdict)
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1"})
    hardware_entry = {
        "candidate_id": "cand-a",
        "design_candidate_id": "design-cand-a",
        "rank": 1,
        "fpga_total_slice_luts": 100,
        "fpga_total_dsps": 2,
        "fpga_total_block_ram_tiles": 1,
        "fpga_total_bonded_iob": 12,
        "asic_total_cell_area": 1234.0,
        "asic_min_slack_ns": 0.5,
        "kernel_count": 8,
    }
    _write_json(
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "status": "trusted_hardware_ppa_ranking_tied",
            "release_id": "release-ppa",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "ranking_eligible_candidate_count": 1,
            "blocked_candidate_count": 0,
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
            "winner_selection_status": "tied_by_identical_kernel_ppa_no_single_winner",
            "all_candidates_metric_tied": True,
            "metric_signature_count": 1,
            "fpga_ranking": [hardware_entry],
            "asic_ranking": [hardware_entry],
            "ranking_policy": {"non_identity_axes_excluded_from_score": True},
            "pareto_frontier": {
                "schema_version": "dse.dft.hardware_ppa_pareto_frontier.v1",
                "pareto_candidate_count": 1,
                "pareto_alternatives": [hardware_entry],
            },
            "claim_boundary": "hardware PPA only",
        },
    )
    _write_json(
        run_dir / "dft_hardware_ppa_pareto_frontier.json",
        {
            "schema_version": "dse.dft.hardware_ppa_pareto_frontier.v1",
            "pareto_candidate_count": 1,
            "pareto_alternatives": [hardware_entry],
        },
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_validation.json",
        {"schema_version": "dse.dft.hardware_ppa_ranking_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_status.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking_status.v1",
            "status": "passed",
            "ranking_status": "trusted_hardware_ppa_ranking_tied",
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution.v1",
            "status": "blocked_no_unique_hardware_ppa_winners",
            "release_id": "release-ppa",
            "candidate_count": 1,
            "ranking_eligible_candidate_count": 1,
            "hardware_completion_eligible": True,
            "ppa_winner_selection_status": "tied_by_identical_kernel_ppa_no_single_winner",
            "all_candidates_metric_tied": True,
            "metric_signature_count": 1,
            "deployments": {
                "fpga": {
                    "status": "blocked_no_unique_hardware_ppa_winner",
                    "resolved": False,
                    "top_rank_candidate_count": 1,
                    "top_rank_candidate_ids": ["cand-a"],
                    "required_next_evidence": [{"task_id": "fpga_candidate_specific_ppa_tie_breaker"}],
                },
                "asic": {
                    "status": "blocked_no_unique_hardware_ppa_winner",
                    "resolved": False,
                    "top_rank_candidate_count": 1,
                    "top_rank_candidate_ids": ["cand-a"],
                    "required_next_evidence": [{"task_id": "asic_candidate_specific_ppa_tie_breaker"}],
                },
            },
            "fpga_best_architecture": None,
            "asic_best_architecture": None,
            "blockers": [{"blocker_id": "fpga_winner_not_resolved"}],
            "blocker_count": 1,
            "hardware_winner_resolution_eligible": False,
            "trusted_best_architecture_claim_eligible": False,
            "deliverable_complete": False,
            "completion_claim": "blocked",
            "claim_boundary": "winner resolution test fixture",
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution_validation.json",
        {"schema_version": "dse.dft.architecture_winner_resolution_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution_status.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution_status.v1",
            "status": "passed",
            "winner_resolution_status": "blocked_no_unique_hardware_ppa_winners",
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_candidate_specific_ppa_provenance_audit.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_provenance_audit.v1",
            "status": "blocked_candidate_specific_ppa_provenance",
            "winner_provenance_eligible": False,
            "unit_count": 8,
            "trusted_unit_count": 0,
            "blocked_unit_count": 8,
            "trusted_stage_count": 0,
            "blocked_stage_count": 40,
            "blocker_count": 40,
            "blocker_id_counts": {"commands_not_executed": 40},
            "tied_candidate_ids_requiring_fresh_ppa": ["cand-a"],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": "provenance test fixture",
        },
    )
    _write_json(
        run_dir / "dft_candidate_specific_ppa_provenance_audit_validation.json",
        {"schema_version": "dse.dft.candidate_specific_ppa_provenance_audit_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_candidate_specific_ppa_provenance_audit_status.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_provenance_audit_status.v1",
            "status": "passed",
            "winner_provenance_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_tie_breaker_execution_queue.json",
        {
            "schema_version": "dse.dft.hardware_tie_breaker_execution_queue.v1",
            "status": "fresh_candidate_specific_ppa_execution_required",
            "work_item_count": 40,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_tie_breaker_execution_queue_validation.json",
        {"schema_version": "dse.dft.hardware_tie_breaker_execution_queue_validation.v1", "valid": True, "errors": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    trusted = json.loads((run_dir / "trusted_ranking.json").read_text(encoding="utf-8"))
    pareto = json.loads((run_dir / "pareto_frontier.json").read_text(encoding="utf-8"))
    assert report["selected_recommendation"]["trusted_winner"] is False
    assert report["selected_recommendation"]["selection_status"] == "hardware_ppa_ranking_available_no_full_dse_winner"
    assert report["selected_recommendation"]["winner_resolution_status"] == "blocked_no_unique_hardware_ppa_winners"
    assert report["dft_architecture_winner_resolution"]["present"] is True
    assert report["dft_architecture_winner_resolution"]["hardware_winner_resolution_eligible"] is False
    assert report["dft_candidate_specific_ppa_provenance"]["present"] is True
    assert report["dft_candidate_specific_ppa_provenance"]["winner_provenance_eligible"] is False
    assert report["dft_candidate_specific_ppa_provenance"]["tie_breaker_work_item_count"] == 40
    assert report["trusted_ranking"][0]["trusted_scope"].startswith("candidate-stamped major-kernel hardware PPA only")
    assert trusted["ranking_scope"] == "hardware_ppa_only"
    assert trusted["dft_architecture_winner_resolution"] == "dft_architecture_winner_resolution.json"
    assert pareto["frontier_scope"] == "hardware_ppa_only"
    assert len(pareto["pareto_alternatives"]) == 1
