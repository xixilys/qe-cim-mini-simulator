#!/usr/bin/env python3
"""DAC/ACM paper artifact regressions."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PAPER_DIR = REPO_ROOT / "paper" / "dac_qe_fpga_dse"
BUILD_TABLES = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "build_qe_fpga_paper_results_tables.py"
BUILD_ARTIFACT_INDEX = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "build_qe_fpga_paper_artifact_index.py"


def test_dac_acm_paper_scaffold_uses_acmart_not_beamer() -> None:
    main_tex = PAPER_DIR / "main.tex"
    references = PAPER_DIR / "references.bib"
    build_script = PAPER_DIR / "build.sh"
    latexmkrc = PAPER_DIR / ".latexmkrc"

    assert main_tex.exists()
    assert references.exists()
    assert build_script.exists()
    assert latexmkrc.exists()

    source = main_tex.read_text(encoding="utf-8")
    assert "\\documentclass[sigconf,anonymous,review]{acmart}" in source
    assert "\\documentclass" in source
    assert "beamer" not in source.lower()
    assert "\\begin{abstract}" in source
    assert "\\section{Introduction}" in source
    assert "\\section{Method}" in source
    assert "\\section{Evaluation Plan and Current Artifacts}" in source
    assert "\\section{Limitations}" in source
    assert "\\bibliography{references}" in source
    assert "\\title{WAMF-DSE: Workflow-Abstraction-Guided Multi-Fidelity Active DSE for QE-to-FPGA Deployment}" in source
    assert "Workflow-Abstraction-Guided Multi-Fidelity Active DSE" in source
    assert "domain-neutral constrained active-Pareto acquisition kernel" in source
    assert "WAMF-kernel" in source
    assert "workflow-aware Pareto funnel is a cheap prior" in source
    assert "compares the WAMF-kernel policy against" in source
    assert "proposed funnel" not in source
    assert "Workflow-Aware Risk-Active Pareto Funnel" not in source


def test_dac_acm_paper_method_text_centers_formal_wamf_algorithm() -> None:
    source = (PAPER_DIR / "main.tex").read_text(encoding="utf-8")

    assert "\\subsection{Formal WAMF-DSE algorithm}" in source
    assert "Let $W$ denote the QE workflow workload set" in source
    assert "$X$ the FPGA deployment candidate space" in source
    assert "$F$ the ordered fidelity ladder" in source
    assert "$a_t=(x,f)$" in source
    assert "candidate--fidelity action" in source
    assert "A_t(x,f) &= P_{\\mathrm{feas}}(x)" in source
    assert "EHVI" in source
    assert "I_G(f)" in source
    assert "U_R(f)" in source
    assert "C_x C_f" in source
    assert "r_f(x,w)=\\log y_f(x,w)-\\log y_{L1}(x,w)" in source
    assert "The neural model is therefore a residual and uncertainty model" in source
    assert "not a standalone architecture generator" in source
    assert "retrospective oracle is not used inside the method loop" in source
    assert "random, manual HBM heuristic, NSGA-II/EA" in source
    assert "no-workflow-abstraction, no-multi-fidelity-feedback, no-active-Pareto" in source
    assert "Evidence gates consume the action queue; they do not define the search objective" in source


def test_dac_acm_paper_method_does_not_center_evidence_status_matrix() -> None:
    source = (PAPER_DIR / "main.tex").read_text(encoding="utf-8")

    assert "Current search layers and evidence status" not in source
    assert "\\label{tab:layers}" not in source
    assert "Layer & Current artifact & Status" not in source
    assert "The WAMF-DSE report records the problem formulation" in source
    assert "hardware-generation path" in source
    assert "HLS synthesis is not yet closed" in source
    assert "bitstream generation remains future work" in source


def test_dac_acm_paper_scaffold_records_current_artifacts_without_final_hardware_result() -> None:
    source = (PAPER_DIR / "main.tex").read_text(encoding="utf-8")

    assert "qe_fpga_search_baseline_report.json" in source
    assert "qe_fpga_multi_workload_experiment_report.json" in source
    assert "qe_fpga_implementation_package_materialization.json" in source
    assert "\\subsection{Artifact and Table Provenance}" in source
    assert "generated/results_tables.tex" in source
    assert "vector-lane count, HBM channel count, tile capacity" in source
    assert "not yet validated by implementation timing or bitstream evidence" in source
    assert "HLS synthesis is not yet closed" in source
    assert "bitstream generation remains future work" in source
    assert "not yet a hardware performance result" in source


def test_qe_fpga_paper_results_tables_are_generated_from_summary(tmp_path: Path) -> None:
    summary_path = tmp_path / "paper_ready_experiment_summary.json"
    out_tex = tmp_path / "results_tables.tex"
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_fpga_paper_ready_experiment_summary.v1",
                "status": "fixture_l3_closed_loop_complete_not_dac_final",
                "method_name": "WAMF-DSE",
                "method_full_name": "Workflow-Abstraction-Guided Multi-Fidelity Active DSE",
                "algorithm_family": "workflow_conditioned_multifidelity_active_pareto_dse",
                "workload_corpus": {
                    "corpus_id": "qe_fpga_representative_fixture_corpus_v1",
                    "workload_count": 4,
                    "workflow_classes": ["bands", "dos", "nscf", "projwfc", "relax", "scf"],
                    "measured_qe_ready_workload_count": 0,
                    "measured_qe_corpus_readiness": {
                        "status": "blocked",
                        "measured_ready_workload_count": 0,
                        "workload_count": 4,
                    },
                },
                "search": {
                    "candidate_count": 384,
                    "promotion_count": 5,
                    "implementation_package_count": 1,
                },
                "wamf_dse": {
                    "schema_version": "dse.qe_fpga_wamf_dse_report.v1",
                    "method_name": "WAMF-DSE",
                    "method_full_name": "Workflow-Abstraction-Guided Multi-Fidelity Active DSE",
                    "model_stack": {
                        "surrogate": {
                            "backend": "trained_tabular_mlp_deep_ensemble_surrogate",
                        },
                    },
                    "selected_final_candidates": {
                        "candidate_count": 2,
                    },
                    "claim_boundary": "wamf_dse_algorithm_report_not_fpga_implementation_evidence",
                },
                "l3_feedback": {
                    "executed_count": 3,
                    "feedback_sample_count": 3,
                },
                "l3_validation_metrics": {
                    "schema_version": "dse.qe_fpga_l3_feedback_validation_metrics.v1",
                    "status": "usable_for_sampled_rank_validation",
                    "rank_correlation": {
                        "l1_estimated_edp_vs_l3_edp_spearman": 0.774596669,
                    },
                    "top_k_overlap": {
                        "k": 2,
                        "overlap_count": 2,
                        "jaccard": 1.0,
                        "l3_top_k_recovered_by_l1_top_k": 1.0,
                    },
                    "promotion_quality": {
                        "k": 2,
                        "evaluated_promoted_count": 2,
                        "evaluated_holdout_count": 1,
                        "precision_at_k": 1.0,
                        "recall_at_k": 1.0,
                        "false_negative_holdout_top_k_candidate_ids": [],
                    },
                    "claim_boundary": "l3_generic_sim_validation_metrics_only_not_hardware_or_qe_correctness_evidence",
                },
                "policy_validation": {
                    "status": "usable_for_policy_comparison",
                    "feedback_fidelity": "L3_generic_sim",
                },
                "search_quality": {
                    "baseline_oracle_fidelity": "L2_python_tlm",
                    "budget_sweep": {"budgets": [1, 2, 4, 5]},
                    "limitations": [
                        "baseline_and_ablation_rows_use_L2_python_tlm_oracle",
                        "closed_loop_L3_feedback_only_covers_sampled_candidates",
                    ],
                },
                "multi_workload_experiment": {
                    "schema_version": "dse.qe_fpga_multi_workload_experiment_report.v1",
                    "workload_count": 4,
                    "aggregate": {
                        "search_quality_summary": {
                            "schema_version": "dse.qe_fpga.multi_workload_search_quality_summary.v1",
                            "evaluation_protocol": "equal_budget_multi_workload_l2_tlm_oracle",
                            "workload_count": 4,
                            "method_policy_id": "wamf_generic_active_pareto",
                            "budget": 5,
                            "policy_rows": [
                                {
                                    "policy_id": "wamf_generic_active_pareto",
                                    "workload_count": 4,
                                    "win_count": 2,
                                    "selection_count_mean": 5,
                                    "final_simple_regret_mean": 0.02,
                                    "final_simple_regret_std": 0.01,
                                    "final_oracle_rank_mean": 1.25,
                                    "top_k_hit_rate": 1.0,
                                    "evaluations_to_top_5_hit_mean": 2.0,
                                },
                                {
                                    "policy_id": "neuromf_trained_surrogate",
                                    "workload_count": 4,
                                    "win_count": 1,
                                    "selection_count_mean": 5,
                                    "final_simple_regret_mean": 0.08,
                                    "final_simple_regret_std": 0.04,
                                    "final_oracle_rank_mean": 2.75,
                                    "top_k_hit_rate": 0.75,
                                    "evaluations_to_top_5_hit_mean": 3.0,
                                },
                                {
                                    "policy_id": "random_seeded",
                                    "workload_count": 4,
                                    "win_count": 0,
                                    "selection_count_mean": 5,
                                    "final_simple_regret_mean": 0.31,
                                    "final_simple_regret_std": 0.07,
                                    "final_oracle_rank_mean": 8.5,
                                    "top_k_hit_rate": 0.25,
                                    "evaluations_to_top_5_hit_mean": None,
                                },
                            ],
                            "best_by_mean_regret": {
                                "policy_id": "wamf_generic_active_pareto",
                            },
                            "method_row": {
                                "policy_id": "wamf_generic_active_pareto",
                                "final_simple_regret_mean": 0.02,
                            },
                            "method_vs_best": {
                                "regret_gap": 0.0,
                            },
                            "limitations": [
                                "multi_workload_rows_use_L2_python_tlm_model_oracle",
                                "not_measured_QE_HLS_Vivado_bitstream_or_board_result",
                            ],
                        }
                    },
                },
                "neuromf_policy_evaluation": {
                    "artifact": "qe_fpga_neuromf_policy_evaluation_report.json",
                    "artifact_ref": {
                        "path": "paper/generated/qe_fpga_neuromf_policy_evaluation_report.json",
                        "sha256": "sha256:123",
                        "size_bytes": 456,
                    },
                    "policy_count": 4,
                    "best_policy_id": "wamf_generic_active_pareto",
                    "best_policy_simple_regret": 0.0,
                    "best_policy_oracle_rank": 1,
                    "trained_neuromf_rank": 1,
                    "trained_neuromf_final_regret": 0.0,
                    "policy_ids_ranked_by_final_regret": [
                        "wamf_generic_active_pareto",
                        "neuromf_trained_surrogate",
                        "workflow_aware_pareto_funnel",
                        "random_seeded",
                    ],
                    "claim_boundary": "policy_evaluation_model_oracle_only_not_final_hardware_evidence",
                },
                "independent_algorithm_benchmark": {
                    "schema_version": "dse.multifidelity_search_benchmark.v1",
                    "scenario_id": "workflow_shift_resource_cliff",
                    "oracle_kind": "independent_synthetic_workflow_mismatch",
                    "best_policy_id": "wamf_constrained_active_pareto",
                    "best_policy_simple_regret": 0.0,
                    "claim_boundary": "algorithm_method_validation_not_hardware_evidence",
                },
                "independent_algorithm_benchmark_suite": {
                    "schema_version": "dse.multifidelity_search_benchmark_suite.v1",
                    "scenario_count": 3,
                    "final_budget": 8,
                    "best_policy_by_mean_regret": {
                        "policy_id": "wamf_constrained_active_pareto",
                    },
                    "policy_statistics": [
                        {
                            "policy_id": "wamf_constrained_active_pareto",
                            "scenario_count": 3,
                            "final_budget": 8,
                            "mean_simple_regret": 0.04,
                            "std_simple_regret": 0.03,
                            "mean_hypervolume_ratio": 0.80,
                            "top_k_hit_rate": 1.0,
                            "win_rate_by_simple_regret": 0.67,
                        },
                        {
                            "policy_id": "cheap_l1_edp",
                            "scenario_count": 3,
                            "final_budget": 8,
                            "mean_simple_regret": 0.29,
                            "std_simple_regret": 0.08,
                            "mean_hypervolume_ratio": 0.46,
                            "top_k_hit_rate": 0.33,
                            "win_rate_by_simple_regret": 0.0,
                        },
                    ],
                },
                "search_control": {
                    "schema_version": "dse.multifidelity_search_control.v1",
                    "mode": "exploration_fallback",
                    "control_reason": "algorithm_not_validated",
                    "recommended_next_action": "recalibrate_models_and_run_exploration_fallback",
                    "selected_candidate_ids": ["cand_a", "cand_b"],
                    "validation_blockers": ["negative_independent_feedback_rank_correlation"],
                    "control_boundary": "search_control_policy_not_hardware_evidence",
                },
                "paper_table_rows": {
                    "workloads": [
                        {
                            "workload_id": "si_scf_nscf_bands_small",
                            "material": "Si",
                            "size_class": "small",
                            "workflow_classes": ["scf", "nscf", "bands"],
                            "stage_count": 3,
                            "observed_runtime": True,
                        },
                        {
                            "workload_id": "al_metal_scf_dos_medium",
                            "material": "Al",
                            "size_class": "medium",
                            "workflow_classes": ["scf", "dos"],
                            "stage_count": 2,
                            "observed_runtime": True,
                        },
                        {
                            "workload_id": "slab_gamma_fft_io_heavy",
                            "material": "Si_slab",
                            "size_class": "large_fft_fixture",
                            "workflow_classes": ["scf"],
                            "stage_count": 1,
                            "observed_runtime": True,
                        },
                    ],
                    "wamf_dse": [
                        {
                            "policy_id": "selected_final_candidates",
                            "label": "WAMF-selected",
                            "final_budget": 5,
                            "final_best_edp": 96.0,
                            "final_oracle_rank": 1,
                            "selected_candidate_count": 2,
                            "method_name": "WAMF-DSE",
                            "surrogate_backend": "trained_tabular_mlp_deep_ensemble_surrogate",
                            "pareto_frontier_count": 4,
                        },
                        {
                            "policy_id": "workflow_aware_pareto_funnel",
                            "label": "Workflow-aware prior",
                            "final_budget": 5,
                            "final_best_edp": 100.0,
                            "final_oracle_rank": 2,
                            "selected_candidate_count": 1,
                            "method_name": "WAMF-DSE",
                            "component_role": "l1_workflow_prior_baseline",
                            "surrogate_backend": "",
                            "pareto_frontier_count": 4,
                        },
                    ],
                    "next_evaluation_actions": [
                        {
                            "action_id": "cand_a::L2_systemc_or_tlm",
                            "candidate_id": "cand_a",
                            "fidelity": "L2_systemc_or_tlm",
                            "action_cost": 1.0,
                            "action_score": 0.42,
                            "constrained_pareto_gain": 0.31,
                            "workflow_risk_coverage": 0.80,
                            "fidelity_information_gain": 0.45,
                            "method_role": "primary_algorithm_decision_queue",
                            "search_objective": "choose_candidate_fidelity_actions_under_budget",
                            "not_an_evidence_closure_matrix": True,
                        },
                        {
                            "action_id": "qe_mainflow_fpga_deployment_dse:hierarchical_funnel:e71867a74e0e119b::L2_systemc_or_tlm",
                            "candidate_id": "qe_mainflow_fpga_deployment_dse:hierarchical_funnel:e71867a74e0e119b",
                            "fidelity": "L2_systemc_or_tlm",
                            "action_cost": 1.13,
                            "action_score": 0.064,
                            "constrained_pareto_gain": 0.332,
                            "workflow_risk_coverage": 0.217,
                            "fidelity_information_gain": 0.45,
                            "method_role": "primary_algorithm_decision_queue",
                            "search_objective": "choose_candidate_fidelity_actions_under_budget",
                            "not_an_evidence_closure_matrix": True,
                        },
                    ],
                    "baseline_budget_curves": [
                        {
                            "policy_id": "workflow_aware_pareto_funnel",
                            "final_budget": 5,
                            "final_best_edp": 100.0,
                            "final_oracle_rank": 1,
                        },
                        {
                            "policy_id": "kernel_level_hotspot_only",
                            "final_budget": 5,
                            "final_best_edp": 140.0,
                            "final_oracle_rank": 4,
                        },
                        {
                            "policy_id": "manual_hbm_streaming_heuristic",
                            "final_budget": 5,
                            "final_best_edp": 150.0,
                            "final_oracle_rank": 5,
                        },
                        {
                            "policy_id": "nsga2_lite_multi_objective",
                            "final_budget": 5,
                            "final_best_edp": 110.0,
                            "final_oracle_rank": 2,
                        },
                    ],
                    "feature_ablations": [
                        {
                            "ablation_id": "full_workflow_structural_features",
                            "removed_feature_groups": [],
                            "best_tlm_edp": 100.0,
                            "oracle_rank_of_best": 1,
                            "comparison_to_full": {
                                "decision_changed": False,
                                "candidate_jaccard_with_full": 1.0,
                                "rank_delta_vs_full": 0,
                                "best_edp_ratio_vs_full": 1.0,
                            },
                        },
                        {
                            "ablation_id": "kernel_histogram_only",
                            "removed_feature_groups": [
                                "data_object_lifetime",
                                "host_control_event_counts",
                            ],
                            "best_tlm_edp": 140.0,
                            "oracle_rank_of_best": 4,
                            "comparison_to_full": {
                                "decision_changed": True,
                                "candidate_jaccard_with_full": 0.25,
                                "rank_delta_vs_full": 3,
                                "best_edp_ratio_vs_full": 1.4,
                            },
                        },
                    ],
                    "method_component_ablations": [
                        {
                            "component_id": "full_method",
                            "policy_id": "wamf_generic_active_pareto",
                            "removed_component": "none",
                            "final_best_edp": 96.0,
                            "final_oracle_rank": 1,
                            "edp_ratio_vs_full": 1.0,
                        },
                        {
                            "component_id": "no_multifidelity_feedback",
                            "policy_id": "single_fidelity_l1_edp",
                            "removed_component": "multi_fidelity_feedback",
                            "final_best_edp": 115.0,
                            "final_oracle_rank": 3,
                            "edp_ratio_vs_full": 1.15,
                        },
                        {
                            "component_id": "no_pareto_active_selection",
                            "policy_id": "random_seeded_multi_seed",
                            "removed_component": "pareto_active_selection",
                            "final_best_edp": 130.0,
                            "final_oracle_rank": 4,
                            "edp_ratio_vs_full": 1.3,
                        },
                        {
                            "component_id": "kernel_only_search",
                            "policy_id": "kernel_level_hotspot_only",
                            "removed_component": "workflow_abstraction",
                            "final_best_edp": 140.0,
                            "final_oracle_rank": 5,
                            "edp_ratio_vs_full": 1.4,
                        },
                    ],
                    "policy_validation": [
                        {
                            "policy_id": "workflow_aware_pareto_funnel",
                            "feedback_overlap_count": 2,
                            "best_feedback_edp": 123.0,
                            "feedback_rank_of_best": 1,
                            "feedback_top_k_hit_at_5": True,
                        }
                    ],
                    "neuromf_policy_evaluation": [
                        {
                            "policy_id": "wamf_generic_active_pareto",
                            "final_budget": 5,
                            "final_best_edp": 96.0,
                            "final_oracle_rank": 1,
                            "trained_neuromf_rank": 1,
                            "trained_neuromf_final_regret": 0.0,
                            "closed_loop_feedback": True,
                            "feedback_observation_count": 4,
                            "final_selection_frontier_source": "observed_high_fidelity_frontier",
                        },
                        {
                            "policy_id": "neuromf_trained_surrogate",
                            "final_budget": 5,
                            "final_best_edp": 96.0,
                            "final_oracle_rank": 1,
                            "trained_neuromf_rank": 1,
                            "trained_neuromf_final_regret": 0.0,
                        },
                        {
                            "policy_id": "workflow_aware_pareto_funnel",
                            "final_budget": 5,
                            "final_best_edp": 100.0,
                            "final_oracle_rank": 2,
                            "trained_neuromf_rank": None,
                            "trained_neuromf_final_regret": None,
                        },
                        {
                            "policy_id": "random_seeded",
                            "final_budget": 5,
                            "final_best_edp": 130.0,
                            "final_oracle_rank": 4,
                            "trained_neuromf_rank": None,
                            "trained_neuromf_final_regret": None,
                        },
                    ],
                    "wamf_required_ablations": [
                        {
                            "ablation_id": "no_multifidelity_feedback",
                            "maps_to": "single_fidelity_l1_edp",
                            "removed_component": "multi_fidelity_feedback",
                            "final_budget": 5,
                            "final_best_edp": 115.0,
                            "final_oracle_rank": 3,
                            "final_simple_regret": 0.15,
                            "same_budget_vs_method": True,
                            "edp_ratio_vs_method": 1.15,
                            "rank_delta_vs_method": 2,
                            "regret_delta_vs_method": 0.10,
                            "uses_workflow_abstraction": True,
                            "uses_multi_fidelity_feedback": False,
                            "uses_active_pareto_selection": False,
                            "algorithm_contract": {
                                "same_candidate_pool_as_method": True,
                                "same_evaluation_budget_as_method": True,
                                "retrospective_oracle_only": True,
                                "removed_components": ["multi_fidelity_feedback"],
                            },
                        }
                    ],
                    "independent_algorithm_benchmark": [
                        {
                            "policy_id": "wamf_constrained_active_pareto",
                            "final_budget": 8,
                            "final_simple_regret": 0.0,
                            "final_oracle_rank": 1,
                            "top_k_hit": True,
                            "final_hypervolume_ratio": 0.82,
                            "final_feasibility_weighted_hv_ratio": 0.77,
                            "final_cost_normalized_hv_gain": 0.12,
                            "final_pareto_coverage": 0.40,
                        },
                        {
                            "policy_id": "cheap_l1_edp",
                            "final_budget": 8,
                            "final_simple_regret": 0.31,
                            "final_oracle_rank": 7,
                            "top_k_hit": False,
                            "final_hypervolume_ratio": 0.45,
                            "final_feasibility_weighted_hv_ratio": 0.39,
                            "final_cost_normalized_hv_gain": 0.05,
                            "final_pareto_coverage": 0.10,
                        },
                        {
                            "policy_id": "random_seeded",
                            "final_budget": 8,
                            "final_simple_regret": 0.52,
                            "final_oracle_rank": 12,
                            "top_k_hit": False,
                            "final_hypervolume_ratio": 0.22,
                            "final_feasibility_weighted_hv_ratio": 0.18,
                            "final_cost_normalized_hv_gain": 0.02,
                            "final_pareto_coverage": 0.00,
                        },
                        {
                            "policy_id": "manual_hbm_streaming",
                            "final_budget": 8,
                            "final_simple_regret": 0.45,
                            "final_oracle_rank": 9,
                            "top_k_hit": False,
                            "final_hypervolume_ratio": 0.36,
                            "final_feasibility_weighted_hv_ratio": 0.30,
                            "final_cost_normalized_hv_gain": 0.04,
                            "final_pareto_coverage": 0.10,
                        },
                    ],
                },
                "limitations": [
                    "fixture_corpus_not_measured_QE_benchmark_suite",
                    "generic_sim_feedback_not_QE_correctness_or_hardware_timing",
                    "HLS_Vivado_bitstream_results_still_missing",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(BUILD_TABLES),
            "--summary",
            str(summary_path),
            "--out",
            str(out_tex),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    tex = out_tex.read_text(encoding="utf-8")
    assert "\\begin{table}" in tex
    assert "\\label{tab:generated-workloads}" in tex
    assert "\\label{tab:generated-search-quality}" in tex
    assert "\\label{tab:generated-multi-workload-search-quality}" in tex
    assert "\\label{tab:generated-corpus-readiness}" in tex
    assert "\\label{tab:generated-wamf-dse}" in tex
    assert "\\label{tab:generated-next-actions}" in tex
    assert "\\label{tab:generated-l3-validation}" in tex
    assert "\\label{tab:generated-ablations}" in tex
    assert "\\label{tab:generated-method-ablations}" in tex
    source_hash = "sha256:" + hashlib.sha256(summary_path.read_bytes()).hexdigest()
    assert f"% Source file: {summary_path}" in tex
    assert f"% Source sha256: {source_hash}" in tex
    assert "generic-sim feedback experiment" in tex
    assert "L3-feedback" not in tex
    assert "generic-sim overlap and rank" in tex
    assert "L3 overlap & L3 rank" not in tex
    assert "Policy & Bgt. & EDP & L2 & GS ov. & GS" in tex
    assert "Multi-workload search quality for the WAMF-DSE method and baselines" in tex
    assert "\\setlength{\\tabcolsep}{2.5pt}" in tex
    assert tex.count("\\setlength{\\tabcolsep}{2.5pt}") >= 8
    assert "Policy & W & B & Reg. & Std & Rnk & Top-k & E@5" in tex
    assert "WAMF-kernel & 4 & 5 & 0.020 & 0.010 & 1.250 & 1.00 & 2.000" in tex
    assert "NeuroMF-trained & 4 & 5 & 0.080 & 0.040 & 2.750 & 0.75 & 3.000" in tex
    assert "Random & 4 & 5 & 0.310 & 0.070 & 8.500 & 0.25 & --" in tex
    assert "Protocol: equal\\_budget\\_multi\\_workload\\_l2\\_tlm\\_oracle" in tex
    assert "model oracle; not measured QE, HLS, Vivado, bitstream, or board result" in tex
    assert "Corpus readiness & blocked" in tex
    assert "Measured-ready workloads & 0/4" in tex
    assert "QE corpus readiness is an input-quality gate only; it does not provide hardware performance or QE correctness evidence." in tex
    assert "Metric & Value" in tex
    assert "Spearman L1--GS & 0.775" in tex
    assert "Top-2 overlap & 2" in tex
    assert "Top-2 Jaccard & 1.00" in tex
    assert "Promotion P/R & 1.00/1.00" in tex
    assert "\\label{tab:generated-neuromf-policy-evaluation}" in tex
    assert "\\label{tab:generated-independent-benchmark}" in tex
    assert "\\label{tab:generated-independent-benchmark-suite}" in tex
    assert "\\label{tab:generated-search-control}" in tex
    assert "Search-control decision for the next multi-fidelity iteration" in tex
    assert "Mode & exploration\\_fallback" in tex
    assert "Selected & 2" in tex
    assert "Next & Recalibrate-Models" in tex
    assert "Independent algorithm benchmark under synthetic workflow/model mismatch" in tex
    assert "Policy & Bgt. & Regret & Rank & HV & FHV & C-HV & Pcov & Top-k" in tex
    assert "WAMF & 8 & 0.000 & 1 & 0.82 & 0.77 & 0.12 & 0.40 & Y" in tex
    assert "L1-only & 8 & 0.310 & 7 & 0.45 & 0.39 & 0.05 & 0.10 & N" in tex
    assert "Random & 8 & 0.520 & 12 & 0.22 & 0.18 & 0.02 & 0.00 & N" in tex
    assert "Manual & 8 & 0.450 & 9 & 0.36 & 0.30 & 0.04 & 0.10 & N" in tex
    assert "independent synthetic oracle; not HLS/Vivado/bitstream or QE measurement" in tex
    assert "Multi-scenario algorithm robustness benchmark" in tex
    assert "Policy & Scen. & Bgt. & Regret & Std & HV & Top-k & Win" in tex
    assert "WAMF & 3 & 8 & 0.040 & 0.030 & 0.80 & 1.00 & 0.67" in tex
    assert "WAMF-DSE policy component evaluation" in tex
    assert "NeuroMF policy evaluation over the replayable candidate pool" not in tex
    assert "Policy & Bgt. & EDP & L2 & CL & FB" in tex
    assert "WAMF-kernel & 5 & 96.0 & 1 & Y & 4" in tex
    assert "NeuroMF-trained & 5 & 96.0 & 1 & N & 0" in tex
    assert "Random & 5 & 130.0 & 4 & N & 0" in tex
    assert "closed-loop WAMF feedback count" in tex
    assert "WAMF-DSE unified method summary" in tex
    assert "WAMF-selected & 5 & 96.0 & 1 & 2 & WAMF-DSE" in tex
    assert "Workflow-aware prior & 5 & 100.0 & 2 & 1 & WAMF-DSE" in tex
    assert "WAMF-DSE next candidate--fidelity actions" in tex
    assert "Cand & Fidelity & Cost & Score & P-gain & Risk & IG" in tex
    assert "cand\\_a & L2-systemc-or-tlm & 1.000 & 0.420 & 0.310 & 0.800 & 0.450" in tex
    assert "A2 & L2-systemc-or-tlm & 1.130 & 0.064 & 0.332 & 0.217 & 0.450" in tex
    assert "qe\\_mainflow\\_fpga\\_deployment\\_dse:hierarchical\\_funnel:e71867a74e0e119b" not in tex
    assert "These rows are the algorithm decision queue; they request feedback and are not an evidence-closure matrix." in tex
    assert "WorkflowAwareParetoFunnel" not in tex
    assert "surrogate backend: trained\\_tabular\\_mlp\\_deep\\_ensemble\\_surrogate" in tex
    assert "L3 validation uses sampled generic\\_sim timing projection only; no HLS/Vivado/bitstream or QE correctness." in tex
    assert "Best EDP &" not in tex
    assert "Var. & Removed & EDP & L2 & $\\Delta$ & Ratio & Chg." in tex
    assert "Comp. & Policy & Removed & EDP & L2 & Ratio" in tex
    assert "Full method & WAMF-kernel & none & 96.0 & 1 & 1.00" in tex
    assert "No multi-fid. & L1-only & multi-fid. & 115.0 & 3 & 1.15" in tex
    assert "No active sel. & Random & active sel. & 130.0 & 4 & 1.30" in tex
    assert "Kernel-only & Kernel-only & workflow & 140.0 & 5 & 1.40" in tex
    assert "Abl. & Rem. & Pol. & B & EDP & L2 & E/W & $\\Delta$L2" in tex
    assert "Abl. & Removed & Policy & B & EDP & L2 & E/W & $\\Delta$L2" not in tex
    assert "No multi-fid. & multi-fid. & L1-only & 5 & 115.0 & 3 & 1.15 & 2" in tex
    assert "W1 & Si & small & scf,nscf,bands & 3" in tex
    assert "W3 & Si slab & large-fft & scf & 1" in tex
    assert "large\\_fft\\_fixture" not in tex
    assert "\\small" in tex
    assert "\\begin{tabular}{@{}llllr@{}}" in tex
    assert "Funnel & 5 & 100.0 & 1 & 2 & 1" in tex
    assert "WAMF-kernel" in tex
    assert "NSGA-II & 5 & 110.0 & 2 & 0 & --" in tex
    assert "Kernel-only & 5 & 140.0 & 4 & 0 & --" in tex
    assert "Manual & 5 & 150.0 & 5 & 0 & --" in tex
    assert "Full & none & 100.0 & 1 & 0 & 1.00 & N" in tex
    assert "No workflow & lifetime,host & 140.0 & 4 & 3 & 1.40 & Y" in tex
    assert "si\\_scf\\_nscf\\_bands\\_small" not in tex
    assert "workflow\\_aware\\_pareto\\_funnel" not in tex
    assert "kernel\\_histogram\\_only" not in tex
    assert "L2\\_python\\_tlm" in tex
    assert "fixture corpus; generic\\_sim timing projection; no HLS/Vivado/bitstream" in tex


def test_qe_fpga_paper_tables_flag_unvalidated_algorithm_quality(tmp_path: Path) -> None:
    summary_path = tmp_path / "paper_ready_experiment_summary.json"
    out_tex = tmp_path / "results_tables.tex"
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_fpga_paper_ready_experiment_summary.v1",
                "status": "fixture_l3_closed_loop_complete_not_dac_final",
                "method_name": "WAMF-DSE",
                "workload_corpus": {
                    "workload_count": 1,
                    "measured_qe_corpus_readiness": {
                        "status": "blocked",
                        "measured_ready_workload_count": 0,
                        "workload_count": 1,
                    },
                },
                "wamf_dse": {
                    "schema_version": "dse.qe_fpga_wamf_dse_report.v1",
                    "method_name": "WAMF-DSE",
                    "selected_final_candidates": {"candidate_count": 1},
                    "model_stack": {"surrogate": {"backend": "bootstrap_tabular"}},
                },
                "l3_validation_metrics": {
                    "schema_version": "dse.qe_fpga_l3_feedback_validation_metrics.v1",
                    "status": "usable_for_sampled_rank_validation",
                    "sample_count": 8,
                    "rank_correlation": {
                        "l1_estimated_edp_vs_l3_edp_spearman": -0.667,
                        "status": "usable",
                    },
                    "top_k_overlap": {"k": 2, "overlap_count": 0, "jaccard": 0.0},
                    "promotion_quality": {"k": 2, "precision_at_k": 0.0, "recall_at_k": 0.0},
                },
                "paper_table_rows": {
                    "workloads": [],
                    "wamf_dse": [
                        {
                            "policy_id": "wamf_generic_active_pareto",
                            "label": "WAMF-kernel",
                            "final_budget": 8,
                            "final_best_edp": 196.0,
                            "final_oracle_rank": 51,
                            "selected_candidate_count": 8,
                            "method_name": "WAMF-DSE",
                            "top_k_hit": False,
                        }
                    ],
                    "baseline_budget_curves": [
                        {
                            "policy_id": "wamf_generic_active_pareto",
                            "final_budget": 8,
                            "final_best_edp": 196.0,
                            "final_oracle_rank": 51,
                            "top_k_hit": False,
                        },
                        {
                            "policy_id": "single_fidelity_l1_edp",
                            "final_budget": 8,
                            "final_best_edp": 133.0,
                            "final_oracle_rank": 1,
                            "top_k_hit": True,
                        },
                        {
                            "policy_id": "nsga2_lite_multi_objective",
                            "final_budget": 8,
                            "final_best_edp": 133.0,
                            "final_oracle_rank": 1,
                            "top_k_hit": True,
                        },
                    ],
                },
                "search_control": {
                    "schema_version": "dse.multifidelity_search_control.v1",
                    "mode": "exploration_fallback",
                    "control_reason": "algorithm_not_validated",
                    "recommended_next_action": "recalibrate_models_and_run_exploration_fallback",
                    "selected_candidate_ids": ["uncertain-host-control", "uncertain-data-residency"],
                    "validation_blockers": ["negative_independent_feedback_rank_correlation"],
                    "control_boundary": "search_control_policy_not_hardware_evidence",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(BUILD_TABLES),
            "--summary",
            str(summary_path),
            "--out",
            str(out_tex),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    tex = out_tex.read_text(encoding="utf-8")
    assert "\\label{tab:generated-algorithm-validation}" in tex
    assert "\\label{tab:generated-search-control}" in tex
    assert "Algorithm quality gate for the replayable model-level experiment" in tex
    assert "Status & algorithm\\_not\\_validated" in tex
    assert "Best EDP policy & L1-only" in tex
    assert "Best rank policy & L1-only" in tex
    assert "Rank corr. & -0.667" in tex
    assert "Blocker count & 6" in tex
    assert "Next & Recalibrate-Models" in tex
    assert "Mode & exploration\\_fallback" in tex
    assert "Reason & algorithm\\_not\\_validated" in tex
    assert "Selected & 2" in tex
    assert "proposed\\_policy\\_loses\\_edp\\_to\\_baseline:single\\_fidelity\\_l1\\_edp" not in tex


def test_qe_fpga_paper_artifact_index_archives_summary_and_table_provenance(tmp_path: Path) -> None:
    summary_path = tmp_path / "closed_loop" / "paper_ready_experiment_summary.json"
    table_path = tmp_path / "paper" / "generated" / "results_tables.tex"
    pdf_path = tmp_path / "paper" / "main.pdf"
    index_path = tmp_path / "paper" / "generated" / "artifact_index.json"
    archived_summary = tmp_path / "paper" / "generated" / "paper_ready_experiment_summary.json"
    summary_path.parent.mkdir(parents=True)
    table_path.parent.mkdir(parents=True)
    summary = {
        "schema_version": "dse.qe_fpga_paper_ready_experiment_summary.v1",
        "status": "fixture_l3_closed_loop_complete_not_dac_final",
        "method_name": "WAMF-DSE",
        "method_full_name": "Workflow-Abstraction-Guided Multi-Fidelity Active DSE",
        "algorithm_family": "workflow_conditioned_multifidelity_active_pareto_dse",
        "workload_corpus": {
            "corpus_id": "qe_fpga_representative_fixture_corpus_v1",
            "workload_count": 4,
            "workflow_classes": ["bands", "dos", "nscf", "projwfc", "relax", "scf"],
            "measured_qe_ready_workload_count": 0,
            "measured_qe_corpus_readiness": {
                "status": "blocked",
                "measured_ready_workload_count": 0,
                "workload_count": 4,
            },
        },
        "search": {"candidate_count": 384, "promotion_count": 5},
        "wamf_dse": {
            "schema_version": "dse.qe_fpga_wamf_dse_report.v1",
            "method_name": "WAMF-DSE",
            "method_full_name": "Workflow-Abstraction-Guided Multi-Fidelity Active DSE",
            "claim_boundary": "wamf_dse_algorithm_report_not_fpga_implementation_evidence",
        },
        "l3_feedback": {"feedback_sample_count": 5},
        "l3_validation_metrics": {},
        "search_quality": {"baseline_oracle_fidelity": "L2_python_tlm"},
        "neuromf_policy_evaluation": {
            "artifact": "qe_fpga_neuromf_policy_evaluation_report.json",
            "artifact_ref": {
                "path": str(summary_path.parent / "qe_fpga_neuromf_policy_evaluation_report.json"),
                "sha256": "sha256:abc",
                "size_bytes": 123,
            },
            "policy_count": 4,
            "best_policy_id": "wamf_generic_active_pareto",
            "best_policy_simple_regret": 0.0,
            "best_policy_oracle_rank": 1,
            "trained_neuromf_rank": 1,
            "trained_neuromf_final_regret": 0.0,
            "policy_ids_ranked_by_final_regret": [
                "wamf_generic_active_pareto",
                "neuromf_trained_surrogate",
                "workflow_aware_pareto_funnel",
                "random_seeded",
            ],
            "claim_boundary": "policy_evaluation_model_oracle_only_not_final_hardware_evidence",
        },
        "independent_algorithm_benchmark": {
            "schema_version": "dse.multifidelity_search_benchmark.v1",
            "scenario_id": "workflow_shift_resource_cliff",
            "oracle_kind": "independent_synthetic_workflow_mismatch",
            "best_policy_id": "wamf_constrained_active_pareto",
            "best_policy_simple_regret": 0.0,
            "claim_boundary": "algorithm_method_validation_not_hardware_evidence",
        },
        "paper_table_rows": {"workloads": [], "wamf_dse": [], "baseline_budget_curves": []},
        "claim_boundary": "paper_ready_summary_for_fixture_experiment_only_not_DAC_final_result",
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    table_path.write_text(
        "% Auto-generated by build_qe_fpga_paper_results_tables.py.\n"
        f"% Source file: {archived_summary}\n"
        "% Source sha256: sha256:placeholder\n",
        encoding="utf-8",
    )
    pdf_path.write_bytes(b"%PDF-1.7\n% fixture compiled ACM/DAC PDF\n")

    completed = subprocess.run(
        [
            sys.executable,
            str(BUILD_ARTIFACT_INDEX),
            "--summary",
            str(summary_path),
            "--tables",
            str(table_path),
            "--out",
            str(index_path),
            "--archive-summary",
            str(archived_summary),
            "--pdf",
            str(pdf_path),
            "--table-command",
            "python3 dse_v2/scripts/dse/build_qe_fpga_paper_results_tables.py --summary paper/dac_qe_fpga_dse/generated/paper_ready_experiment_summary.json --out paper/dac_qe_fpga_dse/generated/results_tables.tex",
            "--latex-command",
            "latexmk -g -pdf -interaction=nonstopmode -halt-on-error main.tex",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert archived_summary.exists()
    assert json.loads(archived_summary.read_text(encoding="utf-8")) == summary
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["schema_version"] == "dse.qe_fpga_paper_artifact_index.v1"
    assert index["status"] == "indexed"
    assert index["paper_artifact_boundary"] == "fixture_generic_sim_tables_not_DAC_final_hardware_result"
    assert index["source_summary"]["path"] == str(summary_path)
    assert index["archived_summary"]["path"] == str(archived_summary)
    assert index["generated_tables"]["path"] == str(table_path)
    assert index["compiled_pdf"]["path"] == str(pdf_path)
    assert index["compiled_pdf"]["sha256"] == "sha256:" + hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert index["compiled_pdf"]["size_bytes"] == pdf_path.stat().st_size
    assert index["compiled_pdf"]["artifact_role"] == "compiled_acm_dac_latex_pdf"
    assert index["source_summary"]["sha256"] == index["archived_summary"]["sha256"]
    assert index["source_summary"]["schema_version"] == "dse.qe_fpga_paper_ready_experiment_summary.v1"
    assert index["source_summary"]["status"] == "fixture_l3_closed_loop_complete_not_dac_final"
    assert index["source_summary"]["method_name"] == "WAMF-DSE"
    assert index["source_summary"]["algorithm_family"] == "workflow_conditioned_multifidelity_active_pareto_dse"
    assert index["source_summary"]["wamf_dse"]["method_name"] == "WAMF-DSE"
    assert index["source_summary"]["wamf_dse"]["schema_version"] == "dse.qe_fpga_wamf_dse_report.v1"
    assert index["source_summary"]["neuromf_policy_evaluation"]["policy_count"] == 4
    assert index["source_summary"]["independent_algorithm_benchmark"]["schema_version"] == "dse.multifidelity_search_benchmark.v1"
    assert index["source_summary"]["independent_algorithm_benchmark"]["oracle_kind"] == "independent_synthetic_workflow_mismatch"
    assert index["source_summary"]["workload_corpus"]["measured_qe_corpus_readiness"]["status"] == "blocked"
    assert index["commands"]["table_generation"].startswith("python3 dse_v2/scripts/dse/build_qe_fpga_paper_results_tables.py")
    assert index["commands"]["latex_build"] == "latexmk -g -pdf -interaction=nonstopmode -halt-on-error main.tex"
    assert "generic_sim_feedback_not_QE_correctness_or_hardware_timing" in index["limitations"]
    assert "HLS_Vivado_bitstream_results_still_missing" in index["limitations"]


def test_qe_fpga_main_tex_includes_generated_results_tables() -> None:
    main_tex = (PAPER_DIR / "main.tex").read_text(encoding="utf-8")
    assert "\\input{generated/results_tables.tex}" in main_tex


def test_qe_fpga_paper_readme_records_table_regeneration_commands() -> None:
    readme = (PAPER_DIR / "README.md").read_text(encoding="utf-8")
    assert "build_qe_fpga_representative_workflow_corpus.py" in readme
    assert "run_qe_fpga_l3_feedback_closed_loop.py" in readme
    assert "build_qe_fpga_paper_results_tables.py" in readme
    assert "latexmk -g -pdf -interaction=nonstopmode -halt-on-error main.tex" in readme


def test_qe_fpga_expert_review_notes_record_multi_agent_critique() -> None:
    notes = (PAPER_DIR / "expert_review_notes.md").read_text(encoding="utf-8")
    assert "Algorithm reviewer" in notes
    assert "Hardware reviewer" in notes
    assert "Manuscript and reproducibility reviewer" in notes
    assert "not submission-ready" in notes
    assert "real QE measured corpus" in notes
    assert "HLS/Vivado/bitstream" in notes
