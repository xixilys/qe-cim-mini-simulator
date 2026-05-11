from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("check_qe_next_stage_release_bundle.py")
SPEC = importlib.util.spec_from_file_location("check_qe_next_stage_release_bundle", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

PHASE_RUNNER_PATH = Path(__file__).with_name("run_qe_next_stage_dse_phase.py")
PHASE_SPEC = importlib.util.spec_from_file_location("run_qe_next_stage_dse_phase", PHASE_RUNNER_PATH)
PHASE_MODULE = importlib.util.module_from_spec(PHASE_SPEC)
assert PHASE_SPEC is not None
assert PHASE_SPEC.loader is not None
PHASE_SPEC.loader.exec_module(PHASE_MODULE)


class NextStageReleaseBundleTests(unittest.TestCase):
    def write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_json(self, path: Path, payload: object) -> None:
        self.write_text(path, json.dumps(payload, indent=2) + "\n")

    def make_ready_payloads(self, root: Path) -> tuple[Path, dict, dict, dict, dict]:
        component_registry_json = root / "qe_ic_component_registry_v0.json"
        gpu_annex_json = root / "qe_gpu_annex_summary.json"
        gpu_annex_md = root / "qe_gpu_annex_summary.md"
        review_json = root / "qe_next_stage_projection_review.json"
        review_md = root / "qe_next_stage_projection_review.md"
        stage_json = root / "qe_next_stage_stage_main_recommendation.json"
        stage_md = root / "qe_next_stage_stage_main_recommendation.md"
        manifest_json = root / "qe_next_stage_artifact_bundle_manifest.json"
        manifest_md = root / "qe_next_stage_artifact_bundle_manifest.md"
        advisor_json = root / "qe_next_stage_advisor_pack_summary.json"
        advisor_md = root / "qe_next_stage_advisor_pack_summary.md"
        release_evidence_json = root / "qe_next_stage_release_evidence.json"
        release_evidence_md = root / "qe_next_stage_release_evidence.md"
        phase1_json = root / "qe_phase1_evidence_closure_report.json"
        phase1_md = root / "qe_phase1_evidence_closure_report.md"
        phase_json = root / "qe_next_stage_dse_phase_summary.json"
        phase_md = root / "qe_next_stage_dse_phase_summary.md"
        fast_json = root / "fast_layer" / "fast_layer_bundle.json"
        accurate_json = root / "accurate_layer" / "accurate_layer_bundle.json"
        coverage_json = root / "accurate_coverage" / "accurate_coverage_bundle.json"
        generalization_json = root / "generalization_coverage" / "generalization_coverage_bundle.json"

        for md in [gpu_annex_md, review_md, stage_md, manifest_md, advisor_md, release_evidence_md, phase1_md, phase_md]:
            self.write_text(md, "# ok\n")

        component_registry_summary = {
            "schema_version": "qe_ic_component_registry_v0",
            "catalog_version": "qe_ic_component_catalog_seed_v0",
            "seed_template_version": "qe_ic_graph_seed_templates_v0",
            "all_strict_checks_pass": True,
            "component_count": 29,
            "active_build_source_count": 30,
            "strict_backbone_component_count": 16,
            "future_catalog_expansion_candidate_count": 1,
            "intentional_unmapped_active_source_count": 1,
            "shared_anchor_count": 1,
            "active_source_gap_categories": {
                "intentional_v0_container_gap": 1,
                "runtime_support_not_seeded_yet": 1,
            },
        }
        self.write_json(
            component_registry_json,
            {
                "schema_version": "qe_ic_component_registry_v0",
                "catalog_version": "qe_ic_component_catalog_seed_v0",
                "seed_template_version": "qe_ic_graph_seed_templates_v0",
                "validation": {"all_strict_checks_pass": True},
            },
        )

        self.write_json(fast_json, {"results": []})
        self.write_json(accurate_json, {"results": []})
        self.write_json(
            coverage_json,
            {
                "results": [
                    {"workload": {"workload_id": "si8_pbe_uspp"}, "correctness": {"gold_pass": True, "status": "pass"}},
                    {"workload": {"workload_id": "si8_pbe_uspp"}, "correctness": {"gold_pass": True, "status": "pass"}},
                ]
            },
        )
        self.write_json(
            generalization_json,
            {
                "results": [
                    {"workload": {"workload_id": "si4_pbe_uspp_small"}, "correctness": {"gold_pass": True, "status": "pass"}},
                    {"workload": {"workload_id": "graphene_pbe_uspp"}, "correctness": {"gold_pass": False, "status": "mismatch"}},
                ]
            },
        )

        review = {
                "package_kind": "qe_next_stage_projection_review_v0",
                "phase_id": "qe_next_stage_dse_simulator_v0",
                "phase_config_path": "/tmp/config.json",
                "fast_layer_json_path": str(fast_json),
                "accurate_layer_json_path": str(accurate_json),
                "json_path": str(review_json),
                "md_path": str(review_md),
                "stage_main_recommendation_status": "projection_eligible",
                "public_recommended_family": "F1",
                "public_recommendation_type": "projection-grade",
                "projection_reporting_allowed": True,
                "promoted_candidate_count": 1,
                "component_registry_path": str(component_registry_json),
                "component_registry_summary": component_registry_summary,
                "recommended_validated_candidates": [
                    {
                        "source_workload_id": "si4_pbe_uspp_small",
                        "selection_role": "primary_candidate",
                        "fast_layer_result_id": "si4__F1__cpu_only__single_hotpath__fit_first__single_hotpath_partition",
                        "accurate_layer_result_id": "si8__F1__cpu_only__single_hotpath__fit_first__single_hotpath_partition",
                        "family": "F1",
                        "diag_policy": "cpu_only",
                        "offload_scope": "single_hotpath",
                        "resident_policy": "fit_first",
                        "partition_strategy": "single_hotpath_partition",
                        "time_to_convergence_s": 0.53,
                        "energy_to_convergence_j": 13.2,
                        "gold_pass": True,
                        "convergence_comparable_pass": True,
                    }
                ],
                "review_readiness": "ready",
            }
        stage = {
            "package_kind": "qe_next_stage_stage_main_recommendation_v0",
            "phase_id": "qe_next_stage_dse_simulator_v0",
            "phase_config_path": "/tmp/config.json",
            "fast_layer_json_path": str(fast_json),
            "accurate_layer_json_path": str(accurate_json),
            "json_path": str(stage_json),
            "md_path": str(stage_md),
            "stage_main_recommendation_status": "projection_eligible",
            "recommended_family": "F1",
            "recommendation_type": "projection-grade",
            "projection_reporting_allowed": True,
            "component_registry_path": str(component_registry_json),
            "component_registry_summary": component_registry_summary,
            "recommendation_status": "ready",
            "runtime_risk_summary": {"overall_runtime_risk": "medium"},
            "supported_source_workloads": ["si4_pbe_uspp_small"],
            "recommended_primary_candidate_count": 1,
            "validated_alternative_candidate_count": 1,
            "recommended_primary_candidates": [
                {
                    "source_workload_id": "si4_pbe_uspp_small",
                    "signature_id": "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
                    "family": "F1",
                "fast_layer_result_id": "si4__F1__cpu_only__single_hotpath__fit_first__single_hotpath_partition",
                "partition_strategy": "single_hotpath_partition",
                }
            ],
            "validated_alternative_candidates": [
                {
                    "source_workload_id": "si4_pbe_uspp_small",
                    "signature_id": "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
                    "selection_role": "fallback_candidate",
                    "family": "F2",
                    "fast_layer_result_id": "si4__F2__device_first_fallback__balanced__fit_first__operator__build__diag__refresh",
                    "partition_strategy": "operator__build__diag__refresh",
                }
            ],
            "best_trusted_point": {
                "recommended_family": "F1",
                "supported_source_workloads": ["si4_pbe_uspp_small"],
                "recommended_primary_candidate_count": 1,
            },
            "best_performance_candidate": {
                "signature_id": "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
                "source_workload_id": "si4_pbe_uspp_small",
                "selection_role": "primary_candidate",
                "family": "F1",
                "diag_policy": "cpu_only",
                "offload_scope": "single_hotpath",
                "resident_policy": "fit_first",
                "partition_strategy": "single_hotpath_partition",
                "fast_layer_result_id": "si4__F1__cpu_only__single_hotpath__fit_first__single_hotpath_partition",
                "accurate_layer_result_id": "si8__F1__cpu_only__single_hotpath__fit_first__single_hotpath_partition",
                "time_to_convergence_s": 0.53,
                "energy_to_convergence_j": 13.2,
                "runtime_risk_level": "medium",
                "runtime_risk_score": 3,
                "graph_topology_summary": "style=host_heavy",
                "graph_execution_plan_summary": "requested=A>C | resolved=A>B>C>D_bypass",
                "graph_component_driver_summary": "source=runtime_cluster_signature_weighted",
            },
            "next_action": "ship it",
        }
        gpu_annex = {
            "schema_version": "qe_gpu_annex_summary_v0",
            "status": "reference_only",
            "reason": "reference_gpu_directory_materialized",
            "source_surface": "gpu_reference_bundle_readiness",
            "baseline_dir_count": 1,
            "counts": {
                "thesis_eligible": 0,
                "reference_only": 1,
                "deferred": 0,
                "decisive": 0,
            },
            "gpu_mode_set_measured": ["practical"],
            "gpu_decisive_modes": [],
            "decisive_case_ids": [],
            "row_ledger": [
                {
                    "baseline_dir": str(root / "gpu_reference_baselines" / "qe_si54_profile__cpu_gpu__practical_reference"),
                    "case_id": "qe_si54_profile",
                    "gpu_mode": "practical",
                    "status": "reference_only",
                    "reason": "correctness_or_convergence_not_closed",
                    "decisive_for_case": False,
                    "blocker_class": "correctness_or_convergence",
                    "manifest_path": str(
                        root
                        / "gpu_reference_baselines"
                        / "qe_si54_profile__cpu_gpu__practical_reference"
                        / "cpu_gpu_baseline_manifest.json"
                    ),
                    "contract_ids": {
                        "workload_group_id": "qe_fpga_phase1_workload_group_v0",
                        "fairness_policy_id": "qe_cpu_gpu_fpga_fairness_and_power_contract_v0",
                        "power_boundary_id": "whole_node_steady_state_single_cpu_single_accelerator_v0",
                        "algorithm_rewrite_manifest_id": "qe_algorithm_rewrite_manifest_v0",
                        "correctness_contract_id": "qe_gold_correctness_contract_v0",
                        "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                    },
                    "baseline_state": "reference_only",
                    "rewrite_mode": "reference_trace_only",
                    "gpu_mode_attempts": ["practical"],
                    "mode_attempt_exemption_note": "strict_fp64 baseline not available in reference trace bundle",
                    "artifact_paths": {
                        "stdout": str(root / "gpu_reference_baselines" / "qe_si54_profile__cpu_gpu__practical_reference" / "stdout.txt")
                    },
                }
            ],
            "annex_note": "GPU annex is derived from readiness outputs.",
            "generated_bundle_dirs": [
                str(root / "gpu_reference_baselines" / "qe_si54_profile__cpu_gpu__practical_reference")
            ],
            "case_decision_sheet": {
                "schema_version": "qe_gpu_case_decision_sheet_v0",
                "case_count": 1,
                "cases": [
                    {
                        "case_id": "qe_si54_profile",
                        "available_gpu_rows": [
                            {
                                "baseline_dir": str(root / "gpu_reference_baselines" / "qe_si54_profile__cpu_gpu__practical_reference"),
                                "manifest_path": str(
                                    root
                                    / "gpu_reference_baselines"
                                    / "qe_si54_profile__cpu_gpu__practical_reference"
                                    / "cpu_gpu_baseline_manifest.json"
                                ),
                                "gpu_mode": "practical",
                                "status": "reference_only",
                                "baseline_state": "reference_only",
                                "reason": "correctness_or_convergence_not_closed",
                                "blocker_class": "correctness_or_convergence",
                                "decisive_for_case": False,
                                "case_ready": False,
                                "time_to_convergence_s": None,
                                "avg_whole_node_power_w": None,
                                "energy_to_solution_j": None,
                                "rewrite_mode": "reference_trace_only",
                                "contract_ids": {
                                    "workload_group_id": "qe_fpga_phase1_workload_group_v0",
                                    "fairness_policy_id": "qe_cpu_gpu_fpga_fairness_and_power_contract_v0",
                                    "power_boundary_id": "whole_node_steady_state_single_cpu_single_accelerator_v0",
                                    "algorithm_rewrite_manifest_id": "qe_algorithm_rewrite_manifest_v0",
                                    "correctness_contract_id": "qe_gold_correctness_contract_v0",
                                    "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                                },
                            }
                        ],
                        "decisive_for_case_row": None,
                        "excluded_rows": [
                            {
                                "baseline_dir": str(root / "gpu_reference_baselines" / "qe_si54_profile__cpu_gpu__practical_reference"),
                                "manifest_path": str(
                                    root
                                    / "gpu_reference_baselines"
                                    / "qe_si54_profile__cpu_gpu__practical_reference"
                                    / "cpu_gpu_baseline_manifest.json"
                                ),
                                "gpu_mode": "practical",
                                "status": "reference_only",
                                "baseline_state": "reference_only",
                                "reason": "correctness_or_convergence_not_closed",
                                "blocker_class": "correctness_or_convergence",
                            }
                        ],
                        "workload_group_aggregation_status": "excluded",
                        "workload_group_aggregation_reason": "no_decisive_gpu_row",
                    }
                ],
            },
            "workload_group_gpu_column_manifest": {
                "schema_version": "qe_gpu_workload_group_column_manifest_v0",
                "workload_group_id": "qe_fpga_phase1_workload_group_v0",
                "fairness_policy_id": "qe_cpu_gpu_fpga_fairness_and_power_contract_v0",
                "power_boundary_id": "whole_node_steady_state_single_cpu_single_accelerator_v0",
                "algorithm_rewrite_manifest_id": "qe_algorithm_rewrite_manifest_v0",
                "correctness_contract_id": "qe_gold_correctness_contract_v0",
                "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                "thesis_counted_cases": [],
                "decisive_row_paths": [],
                "excluded_cases": [
                    {
                        "case_id": "qe_si54_profile",
                        "reason": "no_decisive_gpu_row",
                        "available_row_count": 1,
                        "row_statuses": ["reference_only"],
                        "blockers": ["correctness_or_convergence_not_closed"],
                    }
                ],
                "unresolved_rows": [
                    {
                        "case_id": "qe_si54_profile",
                        "baseline_dir": str(root / "gpu_reference_baselines" / "qe_si54_profile__cpu_gpu__practical_reference"),
                        "manifest_path": str(
                            root
                            / "gpu_reference_baselines"
                            / "qe_si54_profile__cpu_gpu__practical_reference"
                            / "cpu_gpu_baseline_manifest.json"
                        ),
                        "gpu_mode": "practical",
                        "status": "reference_only",
                        "reason": "correctness_or_convergence_not_closed",
                        "blocker_class": "correctness_or_convergence",
                    }
                ],
                "safe_claim_status": "no_gpu_decisive_column",
            },
            "artifact_paths": {
                "gpu_annex_json": str(gpu_annex_json),
                "gpu_annex_md": str(gpu_annex_md),
                "case_decision_sheet_json": str(root / "qe_gpu_case_decision_sheet.json"),
                "case_decision_sheet_md": str(root / "qe_gpu_case_decision_sheet.md"),
                "workload_group_gpu_column_manifest_json": str(root / "qe_gpu_workload_group_column_manifest.json"),
                "workload_group_gpu_column_manifest_md": str(root / "qe_gpu_workload_group_column_manifest.md"),
            },
        }
        self.write_json(
            Path(gpu_annex["row_ledger"][0]["manifest_path"]),
            {"schema_version": "qe_cpu_gpu_baseline_manifest_v0"},
        )
        self.write_text(Path(gpu_annex["artifact_paths"]["case_decision_sheet_md"]), "# case sheet\n")
        self.write_text(Path(gpu_annex["artifact_paths"]["workload_group_gpu_column_manifest_md"]), "# gpu column\n")
        self.write_json(Path(gpu_annex["artifact_paths"]["case_decision_sheet_json"]), gpu_annex["case_decision_sheet"])
        self.write_json(
            Path(gpu_annex["artifact_paths"]["workload_group_gpu_column_manifest_json"]),
            gpu_annex["workload_group_gpu_column_manifest"],
        )
        best_point = {
            "status": "ready",
            "source_surface": "stage_main_recommendation_package",
            "stage_main_recommendation_status": "projection_eligible",
            "public_recommended_family": "F1",
            "recommendation_family": "F1",
            "trusted_family": "F1",
            "performance_family": "F1",
            "supported_source_workloads": ["si4_pbe_uspp_small"],
            "projection_reporting_allowed": True,
            "recommendation_type": "projection-grade",
            "runtime_risk_overall": "medium",
            "best_point_fast_layer_result_id": "si4__F1__cpu_only__single_hotpath__fit_first__single_hotpath_partition",
            "best_point_accurate_layer_result_id": "si8__F1__cpu_only__single_hotpath__fit_first__single_hotpath_partition",
            "best_point_time_to_convergence_s": 0.53,
            "best_point_energy_to_convergence_j": 13.2,
            "best_point_runtime_risk_level": "medium",
            "best_point_runtime_risk_score": 3,
            "best_point_graph_topology_summary": "style=host_heavy",
            "best_point_graph_execution_plan_summary": "requested=A>C | resolved=A>B>C>D_bypass",
            "best_point_graph_component_driver_summary": "source=runtime_cluster_signature_weighted",
            "next_action": "ship it",
        }
        phase1_evidence_closure = {
            "json_path": str(phase1_json),
            "md_path": str(phase1_md),
            "summary": {
                "gpu_input_rows": 1,
                "board_input_rows": 0,
                "gpu_decisive_ready_cases": 0,
                "board_ready_cases": 0,
                "thesis_count_candidate_ready_cases": 0,
                "decisive_lane_targets": ["si4_pbe_uspp_small", "graphene_pbe_uspp"],
                "decisive_lane_closed": False,
                "repo_internal_status": "complete",
                "next_blocker_class": "external_measurement_artifacts",
            },
            "case_matrix": [
                {
                    "case_id": "si4_pbe_uspp_small",
                    "gpu_decisive_ready": False,
                    "board_ready": False,
                    "thesis_count_candidate_ready": False,
                    "gpu_blockers": [],
                    "board_blockers": [],
                },
                {
                    "case_id": "graphene_pbe_uspp",
                    "gpu_decisive_ready": False,
                    "board_ready": False,
                    "thesis_count_candidate_ready": False,
                    "gpu_blockers": [],
                    "board_blockers": [],
                },
            ],
        }
        self.write_json(
            phase1_json,
            {
                "schema_version": "qe_phase1_evidence_closure_report_v0",
                "gpu_rows": gpu_annex["row_ledger"],
                "board_rows": [],
                "case_matrix": phase1_evidence_closure["case_matrix"],
                "summary": phase1_evidence_closure["summary"],
            },
        )
        manifest = {
            "package_kind": "qe_next_stage_artifact_bundle_manifest_v0",
            "phase_id": "qe_next_stage_dse_simulator_v0",
            "phase_config_path": "/tmp/config.json",
            "json_path": str(manifest_json),
            "md_path": str(manifest_md),
            "public_recommended_family": "F1",
            "public_recommendation_type": "projection-grade",
            "stage_main_recommendation_status": "projection_eligible",
            "bundle_readiness": "ready",
            "release_ready_recommendation": True,
            "recommended_primary_candidate_count": 1,
            "validated_alternative_candidate_count": 1,
            "projection_review_candidate_count": 1,
            "component_registry_summary": component_registry_summary,
            "accurate_coverage_summary": {
                "coverage_workload_count": 1,
                "coverage_result_count": 2,
                "coverage_pass_count": 2,
                "coverage_mismatch_count": 0,
                "coverage_ready": True,
            },
            "generalization_coverage_summary": {
                "generalization_workload_count": 2,
                "generalization_result_count": 2,
                "generalization_pass_count": 1,
                "generalization_mismatch_count": 1,
                "generalization_ready": False,
            },
            "gpu_annex_summary": gpu_annex,
            "phase1_evidence_closure_summary": phase1_evidence_closure["summary"],
            "artifact_paths": {
                "fast_layer_json": str(fast_json),
                "fast_layer_csv": str(root / "fast_layer" / "fast_layer_bundle.csv"),
                "accurate_layer_json": str(accurate_json),
                "accurate_layer_csv": str(root / "accurate_layer" / "accurate_layer_bundle.csv"),
                "accurate_coverage_json": str(coverage_json),
                "accurate_coverage_csv": str(root / "accurate_coverage" / "accurate_coverage_bundle.csv"),
                "generalization_coverage_json": str(generalization_json),
                "generalization_coverage_csv": str(root / "generalization_coverage" / "generalization_coverage_bundle.csv"),
                "gpu_annex_json": str(gpu_annex_json),
                "gpu_annex_md": str(gpu_annex_md),
                "gpu_case_decision_sheet_json": str(root / "qe_gpu_case_decision_sheet.json"),
                "gpu_case_decision_sheet_md": str(root / "qe_gpu_case_decision_sheet.md"),
                "gpu_workload_group_manifest_json": str(root / "qe_gpu_workload_group_column_manifest.json"),
                "gpu_workload_group_manifest_md": str(root / "qe_gpu_workload_group_column_manifest.md"),
                "component_registry_json": str(component_registry_json),
                "phase1_evidence_closure_json": str(phase1_json),
                "phase1_evidence_closure_md": str(phase1_md),
                "phase_summary_json": str(phase_json),
                "phase_summary_md": str(phase_md),
                "projection_review_json": str(review_json),
                "projection_review_md": str(review_md),
                "stage_main_recommendation_json": str(stage_json),
                "stage_main_recommendation_md": str(stage_md),
                "advisor_pack_json": str(advisor_json),
                "advisor_pack_md": str(advisor_md),
                "release_evidence_json": str(release_evidence_json),
                "release_evidence_md": str(release_evidence_md),
            },
            "next_action": "ship it",
        }
        advisor = {
            "package_kind": "qe_next_stage_advisor_pack_summary_v0",
            "phase_id": "qe_next_stage_dse_simulator_v0",
            "phase_config_path": "/tmp/config.json",
            "closure_scope": "qe_ic_dse_recommendation_package_only",
            "release_entry_kind": "stage_artifact_bundle_manifest",
            "public_recommended_family": "F1",
            "public_recommendation_type": "projection-grade",
            "advisor_release_ready": True,
            "trusted_family": "F1",
            "performance_family": "F1",
            "trusted_performance_divergence": False,
            "gpu_annex_status": "reference_only",
            "gpu_annex_reason": "reference_gpu_directory_materialized",
            "thesis_claim_status": "reference_only",
            "phase1_decisive_lane_closed": False,
            "phase1_next_blocker_class": "external_measurement_artifacts",
            "best_point_summary": best_point,
            "known_limitations": ["gpu_annex_reference_only", "phase1_evidence_external_measurement_artifacts"],
            "artifact_paths": {
                "manifest_json": str(manifest_json),
                "manifest_md": str(manifest_md),
                "projection_review_json": str(review_json),
                "projection_review_md": str(review_md),
                "stage_main_recommendation_json": str(stage_json),
                "stage_main_recommendation_md": str(stage_md),
                "gpu_annex_json": str(gpu_annex_json),
                "gpu_annex_md": str(gpu_annex_md),
                "phase1_evidence_closure_json": str(phase1_json),
                "phase1_evidence_closure_md": str(phase1_md),
                "release_evidence_json": str(release_evidence_json),
                "release_evidence_md": str(release_evidence_md),
            },
            "next_action": "ship it",
            "json_path": str(advisor_json),
            "md_path": str(advisor_md),
        }
        release_evidence = {
            "package_kind": "qe_next_stage_release_evidence_v0",
            "phase_id": "qe_next_stage_dse_simulator_v0",
            "phase_config_path": "/tmp/config.json",
            "release_entry_kind": "stage_artifact_bundle_manifest",
            "bundle_readiness": "ready",
            "release_ready_recommendation": True,
            "public_recommended_family": "F1",
            "public_recommendation_type": "projection-grade",
            "best_point_source_surface": "stage_main_recommendation_package",
            "best_point_fast_layer_result_id": "si4__F1__cpu_only__single_hotpath__fit_first__single_hotpath_partition",
            "best_point_accurate_layer_result_id": "si8__F1__cpu_only__single_hotpath__fit_first__single_hotpath_partition",
            "gpu_annex_status": "reference_only",
            "gpu_annex_reason": "reference_gpu_directory_materialized",
            "phase1_decisive_lane_closed": False,
            "phase1_next_blocker_class": "external_measurement_artifacts",
            "verification_commands": {
                "phase_runner_command": "python3 tools/benchmarks/run_qe_next_stage_dse_phase.py --output-dir /tmp/out",
                "release_validator_command": "python3 tools/benchmarks/check_qe_next_stage_release_bundle.py --summary /tmp/out/qe_next_stage_dse_phase_summary.json",
            },
            "artifact_paths": {
                "manifest_json": str(manifest_json),
                "manifest_md": str(manifest_md),
                "advisor_pack_json": str(advisor_json),
                "advisor_pack_md": str(advisor_md),
                "gpu_annex_json": str(gpu_annex_json),
                "gpu_annex_md": str(gpu_annex_md),
                "phase1_evidence_closure_json": str(phase1_json),
                "phase1_evidence_closure_md": str(phase1_md),
                "phase_summary_json": str(phase_json),
                "phase_summary_md": str(phase_md),
            },
            "safe_claims": [
                "manifest_is_top_level_release_entry",
                "stage_main_package_is_trusted_performance_authority",
                "best_point_summary_is_derived_only",
                "gpu_thesis_claim_not_ready",
            ],
            "residual_risks": [
                "gpu_annex_reference_only",
                "phase1_evidence_external_measurement_artifacts",
            ],
            "json_path": str(release_evidence_json),
            "md_path": str(release_evidence_md),
        }
        self.write_json(gpu_annex_json, gpu_annex)
        self.write_json(advisor_json, advisor)
        self.write_json(release_evidence_json, release_evidence)
        summary = {
            "schema_version": "qe_next_stage_dse_phase_summary_v0",
            "phase_id": "qe_next_stage_dse_simulator_v0",
            "phase_config_path": "/tmp/config.json",
            "component_registry": {
                "json_path": str(component_registry_json),
                "summary": component_registry_summary,
            },
            "public_recommendation": {
                "public_recommended_family": "F1",
                "public_recommendation_type": "projection-grade",
                "projection_reporting_allowed": True,
            },
            "gpu_annex_summary": gpu_annex,
            "phase1_evidence_closure": phase1_evidence_closure,
            "best_point_summary": best_point,
            "release_evidence_summary": release_evidence,
            "fast_layer": {},
            "accurate_layer": {
                "stage_recommendation_gate": {
                    "stage_main_recommendation_status": "projection_eligible",
                }
            },
            "projection_review": review,
            "stage_main_recommendation_package": stage,
            "stage_artifact_bundle_manifest": manifest,
            "advisor_pack_summary": advisor,
        }
        return phase_json, review, stage, manifest, summary

    def test_ready_release_bundle_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_json, review, stage, manifest, summary = self.make_ready_payloads(root)
            self.write_json(Path(review["json_path"]), review)
            self.write_json(Path(stage["json_path"]), stage)
            self.write_json(Path(manifest["json_path"]), manifest)
            self.write_json(summary_json, summary)
            MODULE.validate_release_bundle(summary_json)

    def test_release_bundle_fails_when_best_trusted_supported_workloads_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_json, review, stage, manifest, summary = self.make_ready_payloads(root)
            stage["best_trusted_point"]["supported_source_workloads"] = ["graphene_pbe_uspp"]
            summary["stage_main_recommendation_package"] = stage
            self.write_json(Path(review["json_path"]), review)
            self.write_json(Path(stage["json_path"]), stage)
            self.write_json(Path(manifest["json_path"]), manifest)
            self.write_json(summary_json, summary)
            with self.assertRaisesRegex(MODULE.ValidationError, "supported_source_workloads drifted"):
                MODULE.validate_release_bundle(summary_json)

    def test_release_bundle_fails_when_best_performance_candidate_not_in_validated_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_json, review, stage, manifest, summary = self.make_ready_payloads(root)
            stage["best_performance_candidate"]["fast_layer_result_id"] = "unknown__F9"
            summary["stage_main_recommendation_package"] = stage
            self.write_json(Path(review["json_path"]), review)
            self.write_json(Path(stage["json_path"]), stage)
            self.write_json(Path(manifest["json_path"]), manifest)
            self.write_json(summary_json, summary)
            with self.assertRaisesRegex(MODULE.ValidationError, "not linked to a validated candidate"):
                MODULE.validate_release_bundle(summary_json)

    def test_release_bundle_fails_when_best_performance_candidate_is_slower_than_validated_alternative(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_json, review, stage, manifest, summary = self.make_ready_payloads(root)
            stage["validated_alternative_candidates"] = [
                {
                    "source_workload_id": "si4_pbe_uspp_small",
                    "signature_id": "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
                    "selection_role": "fallback_candidate",
                    "family": "F2",
                    "diag_policy": "device_first_fallback",
                    "offload_scope": "balanced",
                    "resident_policy": "fit_first",
                    "partition_strategy": "operator__build__diag__refresh",
                    "fast_layer_result_id": "si4__F2__device_first_fallback__balanced__fit_first__operator__build__diag__refresh",
                    "accurate_layer_result_id": "si8__F2__device_first_fallback__balanced__fit_first__operator__build__diag__refresh",
                    "time_to_convergence_s": 0.41,
                    "energy_to_convergence_j": 16.5,
                }
            ]
            summary["stage_main_recommendation_package"] = stage
            self.write_json(Path(review["json_path"]), review)
            self.write_json(Path(stage["json_path"]), stage)
            self.write_json(Path(manifest["json_path"]), manifest)
            self.write_json(summary_json, summary)
            with self.assertRaisesRegex(MODULE.ValidationError, "strongest validated performance point"):
                MODULE.validate_release_bundle(summary_json)

    def test_release_bundle_fails_when_best_performance_candidate_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_json, review, stage, manifest, summary = self.make_ready_payloads(root)
            stage["best_performance_candidate"] = None
            summary["stage_main_recommendation_package"] = stage
            self.write_json(Path(review["json_path"]), review)
            self.write_json(Path(stage["json_path"]), stage)
            self.write_json(Path(manifest["json_path"]), manifest)
            self.write_json(summary_json, summary)
            with self.assertRaisesRegex(MODULE.ValidationError, "missing best_performance_candidate"):
                MODULE.validate_release_bundle(summary_json)

    def test_release_bundle_fails_on_family_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_json, review, stage, manifest, summary = self.make_ready_payloads(root)
            stage["recommended_family"] = "F2"
            summary["stage_main_recommendation_package"] = stage
            self.write_json(Path(review["json_path"]), review)
            self.write_json(Path(stage["json_path"]), stage)
            self.write_json(Path(manifest["json_path"]), manifest)
            self.write_json(summary_json, summary)
            with self.assertRaisesRegex(MODULE.ValidationError, "recommended_family drifted"):
                MODULE.validate_release_bundle(summary_json)

    def test_release_bundle_fails_when_projection_review_family_drifts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_json, review, stage, manifest, summary = self.make_ready_payloads(root)
            review["public_recommended_family"] = "F2"
            summary["projection_review"] = review
            self.write_json(Path(review["json_path"]), review)
            self.write_json(Path(stage["json_path"]), stage)
            self.write_json(Path(manifest["json_path"]), manifest)
            self.write_json(summary_json, summary)
            with self.assertRaisesRegex(MODULE.ValidationError, "public_recommended_family drift between summary and projection_review"):
                MODULE.validate_release_bundle(summary_json)

    def test_release_bundle_fails_when_projection_review_candidate_payload_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_json, review, stage, manifest, summary = self.make_ready_payloads(root)
            review["recommended_validated_candidates"] = [{"family": "F1"}]
            review["promoted_candidate_count"] = 1
            summary["projection_review"] = review
            self.write_json(Path(review["json_path"]), review)
            self.write_json(Path(stage["json_path"]), stage)
            self.write_json(Path(manifest["json_path"]), manifest)
            self.write_json(summary_json, summary)
            with self.assertRaisesRegex(MODULE.ValidationError, "recommended_validated_candidates\\[0\\] missing required keys"):
                MODULE.validate_release_bundle(summary_json)

    def test_release_bundle_fails_when_supported_source_workloads_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_json, review, stage, manifest, summary = self.make_ready_payloads(root)
            stage["supported_source_workloads"] = ["graphene_pbe_uspp"]
            summary["stage_main_recommendation_package"] = stage
            self.write_json(Path(review["json_path"]), review)
            self.write_json(Path(stage["json_path"]), stage)
            self.write_json(Path(manifest["json_path"]), manifest)
            self.write_json(summary_json, summary)
            with self.assertRaisesRegex(MODULE.ValidationError, "supported_source_workloads drifted"):
                MODULE.validate_release_bundle(summary_json)

    def test_generated_execute_model_summary_passes_release_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            old_argv = sys.argv
            try:
                sys.argv = [
                    "run_qe_next_stage_dse_phase.py",
                    "--output-dir",
                    str(out_dir),
                    "--execute-model",
                ]
                rc = PHASE_MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            MODULE.validate_release_bundle(out_dir / "qe_next_stage_dse_phase_summary.json")

    def test_release_bundle_fails_when_advisor_pack_gpu_status_drifts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_json, review, stage, manifest, summary = self.make_ready_payloads(root)
            summary["advisor_pack_summary"]["gpu_annex_status"] = "deferred"
            self.write_json(Path(review["json_path"]), review)
            self.write_json(Path(stage["json_path"]), stage)
            self.write_json(Path(manifest["json_path"]), manifest)
            self.write_json(Path(summary["gpu_annex_summary"]["row_ledger"][0]["manifest_path"]), {"schema_version": "qe_cpu_gpu_baseline_manifest_v0"})
            self.write_json(Path(summary["advisor_pack_summary"]["json_path"]), summary["advisor_pack_summary"])
            self.write_json(Path(manifest["artifact_paths"]["gpu_annex_json"]), summary["gpu_annex_summary"])
            self.write_json(summary_json, summary)
            with self.assertRaisesRegex(MODULE.ValidationError, "advisor_pack_summary gpu_annex_status drifted"):
                MODULE.validate_release_bundle(summary_json)


if __name__ == "__main__":
    unittest.main()
