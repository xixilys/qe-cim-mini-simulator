from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("run_qe_next_stage_dse_phase.py")
SPEC = importlib.util.spec_from_file_location("run_qe_next_stage_dse_phase", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


class RunQeNextStageDsePhaseTests(unittest.TestCase):
    def test_phase_runner_records_case_pack_summary_when_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            case_pack = out_dir / "case_pack.json"
            case_pack.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_ic_case_pack_v0",
                        "matrix_path": "/tmp/matrix.json",
                        "phase_config_path": "/tmp/phase.json",
                        "bundle_role": "canonical_f1_seed_pack",
                        "seed_family": "F1",
                        "stage_a_bringup_descriptors": [
                            {"workload_id": "si4_pbe_uspp_small", "display_label": "Custom si4 label"},
                            {"workload_id": "graphene_pbe_uspp", "display_label": "Custom graphene label"},
                            {"workload_id": "si8_pbe_nc", "display_label": "Custom si8 label"},
                        ],
                        "stage_b_nonblocking_signature_descriptors": [],
                        "accurate_layer_anchor_descriptors": [{"workload_id": "si8_pbe_nc", "display_label": "Custom anchor"}],
                        "accurate_layer_coverage_descriptors": [{"workload_id": "si8_pbe_uspp", "display_label": "Custom coverage"}],
                        "accurate_layer_generalization_descriptors": [
                            {"workload_id": "si4_pbe_uspp_small", "display_label": "Custom si4 gen"},
                            {"workload_id": "graphene_pbe_uspp", "display_label": "Custom graphene gen"},
                            {"workload_id": "graphene_pbe_paw", "display_label": "Custom paw gen"},
                            {"workload_id": "h2_tiny", "display_label": "Custom h2 gen"},
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            import sys

            old_argv = sys.argv
            try:
                sys.argv = [
                    "run_qe_next_stage_dse_phase.py",
                    "--output-dir",
                    str(out_dir),
                    "--case-pack",
                    str(case_pack),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv

            self.assertEqual(rc, 0)
            summary = json.loads((out_dir / "qe_next_stage_dse_phase_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["case_pack_path"], str(case_pack))
            self.assertEqual(summary["case_pack_summary"]["bundle_role"], "canonical_f1_seed_pack")
            self.assertTrue(summary["case_pack_summary"]["all_referenced_workloads_present"])
            self.assertTrue(summary["component_registry"]["summary"]["all_strict_checks_pass"])
            self.assertTrue(Path(summary["component_registry"]["json_path"]).exists())
            self.assertEqual(
                summary["case_pack_summary"]["sections"]["accurate_layer_coverage"],
                ["si8_pbe_uspp"],
            )
            fast = json.loads((out_dir / "fast_layer" / "fast_layer_bundle.json").read_text(encoding="utf-8"))
            fast_labels = {row["workload"]["workload_id"]: row["workload"]["label"] for row in fast["results"]}
            self.assertEqual(fast_labels["si4_pbe_uspp_small"], "Custom si4 label")
            accurate = json.loads((out_dir / "accurate_layer" / "accurate_layer_bundle.json").read_text(encoding="utf-8"))
            accurate_labels = {row["workload"]["workload_id"]: row["workload"]["label"] for row in accurate["results"]}
            self.assertEqual(accurate_labels["si8_pbe_nc"], "Custom anchor")

    def test_phase_runner_emits_fast_and_accurate_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            import sys

            old_argv = sys.argv
            try:
                sys.argv = [
                    "run_qe_next_stage_dse_phase.py",
                    "--output-dir",
                    str(out_dir),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv

            self.assertEqual(rc, 0)
            fast_json = out_dir / "fast_layer" / "fast_layer_bundle.json"
            accurate_json = out_dir / "accurate_layer" / "accurate_layer_bundle.json"
            summary_json = out_dir / "qe_next_stage_dse_phase_summary.json"
            summary_md = out_dir / "qe_next_stage_dse_phase_summary.md"
            self.assertTrue(fast_json.exists())
            self.assertTrue(accurate_json.exists())
            self.assertTrue(summary_json.exists())
            self.assertTrue(summary_md.exists())
            self.assertTrue((out_dir / "qe_gpu_annex_summary.json").exists())
            self.assertTrue((out_dir / "qe_gpu_annex_summary.md").exists())
            self.assertTrue((out_dir / "qe_phase1_evidence_closure_report.json").exists())
            self.assertTrue((out_dir / "qe_phase1_evidence_closure_report.md").exists())
            self.assertFalse((out_dir / "qe_next_stage_release_evidence.json").exists())
            self.assertFalse((out_dir / "qe_next_stage_release_evidence.md").exists())

            fast = json.loads(fast_json.read_text(encoding="utf-8"))
            workloads = {row["workload"]["workload_id"] for row in fast["results"]}
            self.assertEqual(workloads, {"si4_pbe_uspp_small", "graphene_pbe_uspp"})
            self.assertIn("fast_layer_proxy_assumptions_path", fast["experiment"])
            self.assertIn("fast_layer_proxy_assumptions_schema_version", fast["experiment"])
            self.assertRegex(
                fast["experiment"]["fast_layer_proxy_assumptions_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertTrue((out_dir / "fast_layer" / "graph_evidence").exists())

            accurate = json.loads(accurate_json.read_text(encoding="utf-8"))
            accurate_workloads = {row["workload"]["workload_id"] for row in accurate["results"]}
            self.assertEqual(accurate_workloads, {"si8_pbe_nc"})
            coverage_json = out_dir / "accurate_coverage" / "accurate_coverage_bundle.json"
            self.assertTrue(coverage_json.exists())
            coverage = json.loads(coverage_json.read_text(encoding="utf-8"))
            coverage_workloads = {row["workload"]["workload_id"] for row in coverage["results"]}
            self.assertEqual(coverage_workloads, {"si8_pbe_uspp"})
            self.assertIn("validation_targets", summary := json.loads(summary_json.read_text(encoding="utf-8"))["accurate_layer"])

            summary = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual(summary["fast_layer"]["primary_objective"], "time_to_convergence_s")
            self.assertTrue(summary["fast_layer"]["graph_evidence_dir"].endswith("/fast_layer/graph_evidence"))
            self.assertTrue(summary["component_registry"]["summary"]["all_strict_checks_pass"])
            self.assertEqual(summary["component_registry"]["summary"]["component_count"], 29)
            self.assertTrue((out_dir / "qe_ic_component_registry_v0.json").exists())
            self.assertEqual(
                summary["fast_layer"]["promotion_policy"]["tie_band_rule"]["max_relative_margin"],
                0.05,
            )
            self.assertEqual(len(summary["fast_layer"]["shortlists"]), 2)
            self.assertEqual(len(summary["accurate_layer"]["selected_design_points"]), 2)
            self.assertEqual(summary["accurate_coverage"]["workloads"], ["si8_pbe_uspp"])
            self.assertFalse(summary["phase1_evidence_closure"]["summary"]["decisive_lane_closed"])
            self.assertEqual(
                summary["phase1_evidence_closure"]["summary"]["next_blocker_class"],
                "external_measurement_artifacts",
            )
            self.assertIsNone(summary["release_evidence_summary"])
            self.assertEqual(
                summary["accurate_coverage"]["summary"],
                {
                    "coverage_workload_count": 1,
                    "coverage_result_count": 2,
                    "coverage_pass_count": 0,
                    "coverage_mismatch_count": 0,
                    "coverage_ready": False,
                },
            )
            self.assertEqual(summary["accurate_layer"]["validation_targets"], [])
            self.assertNotIn("generalization_coverage", summary)
            self.assertEqual(
                summary["accurate_layer"]["validation_summary_by_source_workload"],
                [
                    {
                        "source_workload_id": "si4_pbe_uspp_small",
                        "validation_target_count": 0,
                        "eligible_candidate_count": 0,
                        "ranking_observation_count": 0,
                        "blocked_candidate_count": 0,
                        "validation_gate_status": "not_assessed",
                        "blocked_selection_roles": [],
                        "gate_reasons": [],
                    },
                    {
                        "source_workload_id": "graphene_pbe_uspp",
                        "validation_target_count": 0,
                        "eligible_candidate_count": 0,
                        "ranking_observation_count": 0,
                        "blocked_candidate_count": 0,
                        "validation_gate_status": "not_assessed",
                        "blocked_selection_roles": [],
                        "gate_reasons": [],
                    },
                ],
            )
            self.assertEqual(
                summary["accurate_layer"]["stage_recommendation_gate"],
                {
                    "stage_main_recommendation_status": "awaiting_accurate_layer",
                    "eligible_source_workload_count": 0,
                    "blocked_source_workload_count": 0,
                    "not_assessed_source_workload_count": 2,
                    "blocked_source_workloads": [],
                    "not_assessed_source_workloads": [
                        "si4_pbe_uspp_small",
                        "graphene_pbe_uspp",
                    ],
                },
            )
            self.assertEqual(summary["public_recommendation"]["public_recommended_family"], "none-yet")
            self.assertEqual(summary["public_recommendation"]["public_recommendation_type"], "evidence-incomplete")
            self.assertEqual(summary["public_recommendation"]["authority_scope"], "supporting_evidence_only")
            self.assertEqual(summary["gpu_annex_summary"]["status"], "deferred")
            self.assertEqual(summary["gpu_annex_summary"]["reason"], "no_gpu_baseline_dirs_configured")
            self.assertEqual(summary["gpu_annex_summary"]["source_surface"], "gpu_baseline_readiness")
            self.assertEqual(summary["best_point_summary"]["status"], "awaiting_accurate_layer")
            self.assertEqual(summary["best_point_summary"]["source_surface"], "public_recommendation")
            self.assertEqual(summary["best_point_summary"]["recommendation_family"], "none-yet")
            self.assertEqual(summary["decision_authority"]["authority_scope"], "adjudicator_only")
            self.assertEqual(summary["decision_authority"]["reference_status"], "present")
            self.assertTrue(Path(summary["decision_authority"]["adjudicator_reference_path"]).exists())
            self.assertTrue(Path(summary["decision_authority"]["decision_memo_json"]).exists())
            self.assertTrue(Path(summary["decision_authority"]["decision_memo_md"]).exists())
            self.assertEqual(summary["adjudicator_reference"]["authority_scope"], "adjudicator_only")
            self.assertEqual(summary["adjudicator_reference"]["reference_status"], "present")
            self.assertIsNone(summary["advisor_pack_summary"])
            self.assertFalse(summary["public_recommendation"]["ranking_observations_retained"])
            self.assertEqual(summary["public_recommendation"]["ranking_observation_source_workloads"], [])
            self.assertFalse(summary["public_recommendation"]["projection_reporting_allowed"])
            self.assertEqual(summary["public_recommendation"]["suppression_reason"], "awaiting_fast_or_accurate_layer")
            self.assertEqual(
                summary["public_recommendation"]["next_narrowing_moves"],
                [
                    "Run accurate-layer validation for shortlisted candidates before promoting any stage-main recommendation."
                ],
            )
            self.assertEqual(
                summary["public_recommendation"]["runtime_risk_summary"]["overall_runtime_risk"],
                "unknown",
            )
            self.assertIsNone(summary["projection_review"])
            self.assertIsNone(summary["stage_main_recommendation_package"])
            self.assertIsNone(summary["stage_artifact_bundle_manifest"])
            self.assertTrue(
                all(
                    {
                        "selection_status",
                        "state_counts",
                        "design_points",
                        "primary_candidate",
                        "fallback_candidate",
                        "extra_promoted_candidates",
                        "recommendation_status",
                        "publication_status",
                        "projection_reporting_allowed",
                        "next_narrowing_move",
                    }
                    <= set(item)
                    for item in summary["fast_layer"]["shortlists"]
                )
            )
            self.assertIn("qe_next_stage_dse_phase_summary", summary_json.read_text(encoding="utf-8"))
            self.assertIn("## Component registry evidence", summary_md.read_text(encoding="utf-8"))
            self.assertIn("## Accurate-layer validation targets", summary_md.read_text(encoding="utf-8"))
            self.assertIn("## Public recommendation view", summary_md.read_text(encoding="utf-8"))
            self.assertIn("## GPU annex summary", summary_md.read_text(encoding="utf-8"))
            self.assertFalse((out_dir / "qe_next_stage_projection_review.json").exists())
            self.assertFalse((out_dir / "qe_next_stage_projection_review.md").exists())
            self.assertFalse((out_dir / "qe_next_stage_stage_main_recommendation.json").exists())
            self.assertFalse((out_dir / "qe_next_stage_stage_main_recommendation.md").exists())
            self.assertFalse((out_dir / "qe_next_stage_artifact_bundle_manifest.json").exists())
            self.assertFalse((out_dir / "qe_next_stage_artifact_bundle_manifest.md").exists())
            self.assertFalse((out_dir / "qe_next_stage_advisor_pack_summary.json").exists())
            self.assertFalse((out_dir / "qe_next_stage_advisor_pack_summary.md").exists())
            self.assertTrue((out_dir / "qe_system_design_adjudicator_reference.json").exists())
            self.assertTrue((out_dir / "adjudicator" / "decision_memo.json").exists())
            self.assertTrue((out_dir / "adjudicator" / "decision_memo.md").exists())

    def test_phase_runner_uses_gpu_reference_dir_as_reference_only_annex(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "out"
            ref = Path(tmpdir) / "reference_qe"
            ref.mkdir()
            (ref / "qe_timing.json").write_text(
                json.dumps(
                    {
                        "total_wall_s": None,
                        "entries": [
                            {"name": "electrons", "wall_s": 12.5, "gpu_s": 0.0},
                            {"name": "fftw", "wall_s": 8.1, "gpu_s": 8.1},
                            {"name": "rdiaghg", "wall_s": 1.2, "gpu_s": 1.2},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (ref / "qe_iter2_app.out").write_text(
                "GPU acceleration is ACTIVE.\nDevice name: NVIDIA GeForce RTX 4060 Laptop GPU\n",
                encoding="utf-8",
            )
            (ref / "qe_si54_profile_cuda_gpu_kern_sum.csv").write_text(
                "Time (%),Name\n28.1,fft_kernel\n25.4,gemm_kernel\n15.5,diag_kernel\n",
                encoding="utf-8",
            )

            import sys

            old_argv = sys.argv
            try:
                sys.argv = [
                    "run_qe_next_stage_dse_phase.py",
                    "--output-dir",
                    str(out_dir),
                    "--gpu-reference-dir",
                    str(ref),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv

            self.assertEqual(rc, 0)
            summary = json.loads((out_dir / "qe_next_stage_dse_phase_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["gpu_annex_summary"]["status"], "reference_only")
            self.assertEqual(summary["gpu_annex_summary"]["reason"], "reference_gpu_directory_materialized")
            self.assertEqual(summary["gpu_annex_summary"]["source_surface"], "gpu_reference_bundle_readiness")
            self.assertEqual(summary["gpu_annex_summary"]["counts"]["reference_only"], 1)
            self.assertEqual(summary["gpu_annex_summary"]["row_ledger"][0]["gpu_mode"], "practical")
            self.assertEqual(summary["gpu_annex_summary"]["case_decision_sheet"]["case_count"], 1)
            self.assertEqual(
                summary["gpu_annex_summary"]["workload_group_gpu_column_manifest"]["safe_claim_status"],
                "no_gpu_decisive_column",
            )
            self.assertTrue((out_dir / "qe_gpu_annex_summary.json").exists())
            self.assertTrue((out_dir / "qe_gpu_annex_summary.md").exists())
            self.assertTrue((out_dir / "qe_gpu_case_decision_sheet.json").exists())
            self.assertTrue((out_dir / "qe_gpu_case_decision_sheet.md").exists())
            self.assertTrue((out_dir / "qe_gpu_workload_group_column_manifest.json").exists())
            self.assertTrue((out_dir / "qe_gpu_workload_group_column_manifest.md").exists())
            self.assertIn(
                "qe_si54_profile | practical | reference_only",
                (out_dir / "qe_gpu_annex_summary.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "workload_group_aggregation_status",
                (out_dir / "qe_gpu_case_decision_sheet.md").read_text(encoding="utf-8"),
            )
            self.assertIsNone(summary["release_evidence_summary"])
            generated_dir = Path(summary["gpu_annex_summary"]["generated_bundle_dirs"][0])
            self.assertTrue((generated_dir / "cpu_gpu_baseline_manifest.json").exists())
            self.assertTrue((generated_dir / "algorithm_rewrite_manifest.json").exists())

    def test_build_gpu_annex_summary_defaults_to_deferred_without_dirs(self) -> None:
        annex = MODULE.build_gpu_annex_summary([])
        self.assertEqual(annex["schema_version"], "qe_gpu_annex_summary_v0")
        self.assertEqual(annex["status"], "deferred")
        self.assertEqual(annex["reason"], "no_gpu_baseline_dirs_configured")
        self.assertEqual(annex["baseline_dir_count"], 0)
        self.assertEqual(annex["counts"]["thesis_eligible"], 0)
        self.assertEqual(annex["gpu_mode_set_measured"], [])
        self.assertEqual(annex["decisive_case_ids"], [])

    def test_build_gpu_annex_summary_uses_reference_dir_as_reference_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ref = root / "qe"
            ref.mkdir()
            (ref / "qe_timing.json").write_text(
                json.dumps(
                    {
                        "total_wall_s": None,
                        "entries": [
                            {"name": "electrons", "wall_s": 12.5, "gpu_s": 0.0},
                            {"name": "fftw", "wall_s": 8.1, "gpu_s": 8.1},
                            {"name": "rdiaghg", "wall_s": 1.2, "gpu_s": 1.2},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (ref / "qe_iter2_app.out").write_text(
                "GPU acceleration is ACTIVE.\nDevice name: NVIDIA GeForce RTX 4060 Laptop GPU\n",
                encoding="utf-8",
            )
            (ref / "qe_si54_profile_cuda_gpu_kern_sum.csv").write_text(
                "Time (%),Name\n28.1,fft_kernel\n25.4,gemm_kernel\n15.5,diag_kernel\n",
                encoding="utf-8",
            )
            annex = MODULE.enrich_gpu_annex_summary(MODULE.build_gpu_annex_summary([], [ref]))
            self.assertEqual(annex["status"], "reference_only")
            self.assertEqual(annex["reason"], "reference_gpu_directory_only")
            self.assertEqual(annex["source_surface"], "gpu_reference_directory")
            self.assertEqual(annex["baseline_dir_count"], 1)
            self.assertEqual(annex["counts"]["reference_only"], 1)
            self.assertEqual(annex["row_ledger"][0]["case_id"], "qe_si54_profile")
            self.assertEqual(annex["row_ledger"][0]["gpu_mode"], "practical_reference")
            self.assertFalse(annex["row_ledger"][0]["decisive_for_case"])
            self.assertEqual(annex["gpu_mode_set_measured"], ["practical_reference"])
            self.assertEqual(annex["decisive_case_ids"], [])
            self.assertEqual(annex["case_decision_sheet"]["case_count"], 1)
            self.assertEqual(
                annex["workload_group_gpu_column_manifest"]["safe_claim_status"],
                "no_gpu_decisive_column",
            )
            md = MODULE.render_gpu_annex_summary_md(annex)
            self.assertIn("Reference artifacts", md)
            self.assertIn("qe_si54_profile_cuda_gpu_kern_sum.csv", md)

    def test_phase_runner_execute_model_emits_generalization_lane_with_h2_tiny(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            import sys

            original_write_bundle_for_lane = MODULE_ANY.write_bundle_for_lane
            original_build_accurate_validation_targets = MODULE_ANY.build_accurate_validation_targets
            original_summarize_accurate_validation_targets = MODULE_ANY.summarize_accurate_validation_targets
            original_annotate_shortlists_with_accurate_layer = MODULE_ANY.annotate_shortlists_with_accurate_layer
            original_build_stage_recommendation_gate = MODULE_ANY.build_stage_recommendation_gate
            original_build_public_recommendation_summary = MODULE_ANY.build_public_recommendation_summary
            original_build_projection_review_summary = MODULE_ANY.build_projection_review_summary
            original_build_stage_main_recommendation_package = MODULE_ANY.build_stage_main_recommendation_package
            original_build_stage_artifact_bundle_manifest = MODULE_ANY.build_stage_artifact_bundle_manifest

            lane_calls = []

            def fake_write_bundle_for_lane(
                lane_name,
                workloads,
                families,
                args,
                runner,
                case_pack=None,
                selected_design_points=None,
                force_gold_required=False,
            ):
                lane_calls.append((lane_name, list(workloads), force_gold_required))
                lane_dir = args.output_dir / lane_name
                lane_dir.mkdir(parents=True, exist_ok=True)
                json_path = lane_dir / f"{lane_name}_bundle.json"
                csv_path = lane_dir / f"{lane_name}_bundle.csv"
                if lane_name == "fast_layer":
                    results = []
                    for workload_id in workloads:
                        results.append(
                            {
                                "result_id": f"{workload_id}__F1",
                                "result_status": "executed",
                                "correctness": {"status": "not_required"},
                                "design_point": {
                                    "family": "F1",
                                    "diag_policy": "cpu_only",
                                    "offload_scope": "single_hotpath",
                                    "resident_policy": "fit_first",
                                    "partition_strategy": "single_hotpath_partition",
                                },
                                "primary_metrics": {
                                    "time_to_convergence_s": 1.0,
                                    "energy_to_convergence_j": 2.0,
                                    "bytes_moved_to_convergence": 3.0,
                                },
                                "secondary_metrics": {
                                    "fallback_ratio": 0.0,
                                    "spill_ratio": 0.0,
                                },
                                "projection": {"ranking_grade_ready": True},
                                "workload": {
                                    "workload_id": workload_id,
                                    "label": workload_id,
                                    "signature_id": f"sig::{workload_id}",
                                },
                            }
                        )
                else:
                    results = [
                        {"workload": {"workload_id": workload_id}, "correctness": {"gold_pass": None, "status": "pending"}}
                        for workload_id in workloads
                    ]
                bundle = {
                    "results": results
                }
                json_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
                csv_path.write_text("stub\n", encoding="utf-8")
                return {
                    "json_path": str(json_path),
                    "csv_path": str(csv_path),
                    "workloads": list(workloads),
                    "families": list(families),
                }

            MODULE_ANY.write_bundle_for_lane = fake_write_bundle_for_lane
            MODULE_ANY.build_accurate_validation_targets = lambda *args, **kwargs: []
            MODULE_ANY.summarize_accurate_validation_targets = lambda targets, workload_ids: [
                {
                    "source_workload_id": workload_id,
                    "validation_target_count": 0,
                    "eligible_candidate_count": 0,
                    "ranking_observation_count": 0,
                    "blocked_candidate_count": 0,
                    "validation_gate_status": "not_assessed",
                    "blocked_selection_roles": [],
                    "gate_reasons": [],
                }
                for workload_id in workload_ids
            ]
            MODULE_ANY.annotate_shortlists_with_accurate_layer = lambda shortlists, targets: shortlists
            MODULE_ANY.build_stage_recommendation_gate = lambda summary: {
                "stage_main_recommendation_status": "awaiting_accurate_layer",
                "eligible_source_workload_count": 0,
                "blocked_source_workload_count": 0,
                "not_assessed_source_workload_count": len(summary),
                "blocked_source_workloads": [],
                "not_assessed_source_workloads": [item["source_workload_id"] for item in summary],
            }
            MODULE_ANY.build_public_recommendation_summary = lambda *args, **kwargs: {
                "public_recommended_family": "none-yet",
                "public_recommendation_type": "evidence-incomplete",
                "authority_scope": "supporting_evidence_only",
                "authority_notes": [],
                "ranking_observations_retained": False,
                "ranking_observation_source_workloads": [],
                "projection_reporting_allowed": False,
                "suppression_reason": "awaiting_fast_or_accurate_layer",
                "next_narrowing_moves": [],
                "runtime_risk_summary": {
                    "overall_runtime_risk": "unknown",
                    "candidate_count": 0,
                    "max_runtime_risk_score": 0,
                    "counts": {"low": 0, "medium": 0, "high": 0, "unknown": 0},
                    "high_risk_result_ids": [],
                    "contributing_reasons": {},
                },
            }
            MODULE_ANY.build_projection_review_summary = lambda *args, **kwargs: None
            MODULE_ANY.build_stage_main_recommendation_package = lambda *args, **kwargs: None
            MODULE_ANY.build_stage_artifact_bundle_manifest = lambda *args, **kwargs: None

            old_argv = sys.argv
            try:
                sys.argv = [
                    "run_qe_next_stage_dse_phase.py",
                    "--output-dir",
                    str(out_dir),
                    "--execute-model",
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv
                MODULE_ANY.write_bundle_for_lane = original_write_bundle_for_lane
                MODULE_ANY.build_accurate_validation_targets = original_build_accurate_validation_targets
                MODULE_ANY.summarize_accurate_validation_targets = original_summarize_accurate_validation_targets
                MODULE_ANY.annotate_shortlists_with_accurate_layer = original_annotate_shortlists_with_accurate_layer
                MODULE_ANY.build_stage_recommendation_gate = original_build_stage_recommendation_gate
                MODULE_ANY.build_public_recommendation_summary = original_build_public_recommendation_summary
                MODULE_ANY.build_projection_review_summary = original_build_projection_review_summary
                MODULE_ANY.build_stage_main_recommendation_package = original_build_stage_main_recommendation_package
                MODULE_ANY.build_stage_artifact_bundle_manifest = original_build_stage_artifact_bundle_manifest

            self.assertEqual(rc, 0)
            self.assertIn(
                ("generalization_coverage", ["si4_pbe_uspp_small", "graphene_pbe_uspp", "graphene_pbe_paw", "h2_tiny"], True),
                lane_calls,
            )
            summary = json.loads((out_dir / "qe_next_stage_dse_phase_summary.json").read_text(encoding="utf-8"))
            self.assertIn("generalization_coverage", summary)
            self.assertEqual(
                summary["generalization_coverage"]["workloads"],
                ["si4_pbe_uspp_small", "graphene_pbe_uspp", "graphene_pbe_paw", "h2_tiny"],
            )

    def test_shortlist_summary_promotes_ready_candidates_and_honors_tie_band(self) -> None:
        config = json.loads(Path(MODULE.PHASE_CONFIG_PATH).read_text(encoding="utf-8"))
        bundle = {
            "results": [
                self.make_fast_result("caseA__F1", "caseA", "F1", 10.0, 100.0, 1000.0, 0.01, 0.01, True),
                self.make_fast_result("caseA__F2", "caseA", "F2", 10.3, 101.0, 1100.0, 0.02, 0.02, True),
                self.make_fast_result("caseA__F3", "caseA", "F3", 10.4, 102.0, 1200.0, 0.03, 0.03, True),
                self.make_fast_result("caseA__F4", "caseA", "F2", None, None, None, None, None, False),
            ]
        }
        summary = MODULE.summarize_fast_layer_shortlists(bundle, config)
        self.assertEqual(len(summary), 1)
        item = summary[0]
        self.assertEqual(item["selection_status"], "ready")
        self.assertEqual(item["primary_candidate"]["result_id"], "caseA__F1")
        self.assertEqual(item["fallback_candidate"]["result_id"], "caseA__F2")
        self.assertEqual(
            item["primary_candidate"]["runtime_observability"]["last_diag_path"],
            "device_accelerator",
        )
        self.assertTrue(
            any("primary_runtime:" in note for note in item["selection_notes"])
        )
        self.assertTrue(
            any("primary_runtime_risk:" in note for note in item["selection_notes"])
        )
        self.assertTrue(
            any("primary_graph:" in note for note in item["selection_notes"])
        )
        self.assertTrue(
            any("primary_graph_topology:" in note for note in item["selection_notes"])
        )
        self.assertTrue(
            any("primary_graph_components:" in note for note in item["selection_notes"])
        )
        self.assertTrue(
            any("leaf_bottleneck=" in note for note in item["selection_notes"])
        )
        self.assertTrue(
            any("score=" in note for note in item["selection_notes"])
        )
        self.assertTrue(
            any("source=runtime_cluster_signature_weighted" in note for note in item["selection_notes"])
        )
        self.assertTrue(
            any("exec=requested=A>C" in note for note in item["selection_notes"])
        )
        self.assertTrue(
            any("cluster=cluster_a=" in note for note in item["selection_notes"])
        )
        self.assertTrue(
            any("signal=signature=" in note for note in item["selection_notes"])
        )
        self.assertTrue(
            any("iter=iters=" in note for note in item["selection_notes"])
        )
        self.assertEqual(item["primary_candidate"]["graph_evidence"]["seed_template_id"], "f1_single_hotpath_graph_v0")
        self.assertEqual(item["runtime_risk_summary"]["candidate_count"], 3)
        self.assertEqual([candidate["result_id"] for candidate in item["extra_promoted_candidates"]], ["caseA__F3"])
        self.assertEqual(item["state_counts"]["promotion-eligible"], 3)
        self.assertEqual(item["state_counts"]["explain-only"], 1)

    def test_shortlist_prefers_lower_runtime_risk_as_tie_breaker(self) -> None:
        config = json.loads(Path(MODULE.PHASE_CONFIG_PATH).read_text(encoding="utf-8"))
        safe = cast(dict[str, Any], self.make_fast_result("caseB__F1", "caseB", "F1", 10.0, 100.0, 1000.0, 0.0, 0.0, True))
        risky = cast(dict[str, Any], self.make_fast_result("caseB__F2", "caseB", "F2", 10.0, 100.0, 1000.0, 1.0, 1.0, True))
        safe["runtime_observability"]["last_diag_path"] = "device_accelerator"
        safe["runtime_observability"]["host_cpu_fallback_count"] = 0
        safe["runtime_observability"]["spill_active_count"] = 0
        safe["runtime_observability"]["last_support_grid_mode"] = "BYPASS"
        risky["runtime_observability"]["last_diag_path"] = "host_cpu_fallback"
        risky["runtime_observability"]["host_cpu_fallback_count"] = 2
        risky["runtime_observability"]["spill_active_count"] = 1
        risky["runtime_observability"]["last_support_grid_mode"] = "FFT_AUX"
        bundle = {"results": [risky, safe]}
        summary = MODULE.summarize_fast_layer_shortlists(bundle, config)
        self.assertEqual(summary[0]["primary_candidate"]["result_id"], "caseB__F1")
        self.assertEqual(summary[0]["fallback_candidate"]["result_id"], "caseB__F2")
        self.assertEqual(summary[0]["primary_candidate"]["runtime_risk_level"], "low")
        self.assertEqual(summary[0]["fallback_candidate"]["runtime_risk_level"], "high")
        self.assertEqual(summary[0]["runtime_risk_summary"]["overall_runtime_risk"], "high")

    def test_shortlist_reports_missing_graph_seed_when_graph_evidence_unmatched(self) -> None:
        config = json.loads(Path(MODULE.PHASE_CONFIG_PATH).read_text(encoding="utf-8"))
        candidate = cast(dict[str, Any], self.make_fast_result("caseC__F1", "caseC", "F1", 10.0, 100.0, 1000.0, 0.0, 0.0, True))
        candidate["graph_evidence"]["seed_template_id"] = None
        candidate["graph_evidence"]["lossless_export_pass"] = False
        candidate["graph_evidence"]["mapping_risk_summary"] = "no_matching_seed_template"
        bundle = {"results": [candidate]}
        summary = MODULE.summarize_fast_layer_shortlists(bundle, config)
        self.assertTrue(
            any("primary_graph_missing: no_matching_seed_template" in note for note in summary[0]["selection_notes"])
        )

    def test_selected_design_points_and_validation_targets_follow_shortlists(self) -> None:
        config = json.loads(Path(MODULE.PHASE_CONFIG_PATH).read_text(encoding="utf-8"))
        runner = MODULE.load_runner()
        shortlists = [
            {
                "workload_id": "si4_pbe_uspp_small",
                "primary_candidate": {
                    "result_id": "si4__F1",
                    "signature_id": "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
                    "family": "F1",
                    "diag_policy": "cpu_only",
                    "offload_scope": "single_hotpath",
                    "resident_policy": "fit_first",
                    "partition_strategy": "single_hotpath_partition",
                    "time_to_convergence_s": 1.0,
                    "energy_to_convergence_j": 2.0,
                    "bytes_moved_to_convergence": 3.0,
                    "fallback_ratio": 0.1,
                    "spill_ratio": 0.0,
                    "ranking_grade_ready": True,
                },
                "fallback_candidate": {
                    "result_id": "si4__F2",
                    "family": "F2",
                    "diag_policy": "device_first_fallback",
                    "offload_scope": "balanced",
                    "resident_policy": "fit_first",
                    "time_to_convergence_s": 1.1,
                    "energy_to_convergence_j": 2.1,
                    "bytes_moved_to_convergence": 3.1,
                    "fallback_ratio": 0.0,
                    "spill_ratio": 0.0,
                    "ranking_grade_ready": True,
                },
                "extra_promoted_candidates": [],
            },
            {
                "workload_id": "graphene_pbe_uspp",
                "primary_candidate": {
                    "result_id": "graphene__F1",
                    "family": "F1",
                    "diag_policy": "cpu_only",
                    "offload_scope": "single_hotpath",
                    "resident_policy": "fit_first",
                    "time_to_convergence_s": 1.0,
                    "energy_to_convergence_j": 2.0,
                    "bytes_moved_to_convergence": 3.0,
                    "fallback_ratio": 0.1,
                    "spill_ratio": 0.0,
                    "ranking_grade_ready": True,
                },
                "fallback_candidate": None,
                "extra_promoted_candidates": [],
            },
        ]
        selected = MODULE.selected_design_points_for_accurate_layer(shortlists, config, runner)
        self.assertEqual(
            selected,
            [
                {
                    "family": "F1",
                    "diag_policy": "cpu_only",
                    "offload_scope": "single_hotpath",
                    "resident_policy": "fit_first",
                    "partition_strategy": "single_hotpath_partition",
                },
                {
                    "family": "F2",
                    "diag_policy": "device_first_fallback",
                    "offload_scope": "balanced",
                    "resident_policy": "fit_first",
                    "partition_strategy": "operator__build__diag__refresh",
                },
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_path = root / "si8_f1.json"
            report_path.write_text(
                json.dumps(
                    {
                        "dominant_blocker": {"kind": "energy_trajectory_mismatch"},
                        "explicit_next_narrowing_move": "Calibrate the host_cpu_fallback energy path against the QE trajectory.",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            accurate_bundle = {
                "results": [
                    {
                        "result_id": "si8_pbe_nc__F1__cpu_only__single_hotpath__fit_first",
                        "workload": {"workload_id": "si8_pbe_nc"},
                        "design_point": selected[0],
                        "correctness": {
                            "status": "mismatch",
                            "gold_pass": False,
                            "convergence_comparable_pass": True,
                            "required_field_failures": ["final_total_energy_ry"],
                            "notes": [
                                f"si8_f1_convergence_report={report_path}",
                                "si8_f1_convergence_summary=/tmp/si8_f1.md",
                            ],
                        },
                    },
                    {
                        "result_id": "si8_pbe_nc__F2__device_first_fallback__balanced__fit_first",
                        "workload": {"workload_id": "si8_pbe_nc"},
                        "design_point": selected[1],
                        "correctness": {
                            "status": "mismatch",
                            "gold_pass": False,
                            "convergence_comparable_pass": True,
                            "required_field_failures": ["final_total_energy_ry"],
                            "notes": [],
                        },
                    },
                ]
            }
            targets = MODULE.build_accurate_validation_targets(shortlists, accurate_bundle)
            self.assertEqual(len(targets), 3)
            self.assertEqual(targets[0]["selection_role"], "primary_candidate")
            self.assertEqual(targets[1]["selection_role"], "fallback_candidate")
            self.assertEqual(targets[2]["selection_role"], "primary_candidate")
            self.assertEqual(targets[0]["correctness_status"], "mismatch")
            self.assertFalse(targets[0]["gold_pass"])
            self.assertTrue(targets[0]["convergence_comparable_pass"])
            self.assertFalse(targets[0]["recommendation_eligible"])
            self.assertTrue(targets[0]["ranking_observation_retained"])
            self.assertEqual(targets[0]["gate_reason"], "gold_mismatch")
            self.assertEqual(targets[0]["required_field_failures"], ["final_total_energy_ry"])
            self.assertEqual(targets[0]["dominant_blocker_kind"], "energy_trajectory_mismatch")
            self.assertEqual(
                targets[0]["explicit_next_narrowing_move"],
                "Calibrate the host_cpu_fallback energy path against the QE trajectory.",
            )
            self.assertEqual(targets[0]["narrowing_summary_path"], "/tmp/si8_f1.md")
            workload_summary = MODULE.summarize_accurate_validation_targets(
                targets, ["si4_pbe_uspp_small", "graphene_pbe_uspp"]
            )
            self.assertEqual(
                workload_summary,
                [
                    {
                        "source_workload_id": "si4_pbe_uspp_small",
                        "validation_target_count": 2,
                        "eligible_candidate_count": 0,
                        "ranking_observation_count": 2,
                        "blocked_candidate_count": 2,
                        "validation_gate_status": "all_candidates_blocked",
                        "blocked_selection_roles": ["primary_candidate", "fallback_candidate"],
                        "gate_reasons": ["gold_mismatch"],
                    },
                    {
                        "source_workload_id": "graphene_pbe_uspp",
                        "validation_target_count": 1,
                        "eligible_candidate_count": 0,
                        "ranking_observation_count": 1,
                        "blocked_candidate_count": 1,
                        "validation_gate_status": "all_candidates_blocked",
                        "blocked_selection_roles": ["primary_candidate"],
                        "gate_reasons": ["gold_mismatch"],
                    },
                ],
            )
            annotated_shortlists = MODULE.annotate_shortlists_with_accurate_layer(shortlists, targets)
            self.assertEqual(len(annotated_shortlists), 2)
            self.assertEqual(annotated_shortlists[0]["workload_id"], "si4_pbe_uspp_small")
            self.assertEqual(annotated_shortlists[0]["recommendation_status"], "blocked_by_accurate_layer")
            self.assertEqual(annotated_shortlists[0]["publication_status"], "ranking_observation_only")
            self.assertFalse(annotated_shortlists[0]["projection_reporting_allowed"])
            self.assertEqual(annotated_shortlists[0]["primary_candidate"]["dominant_blocker_kind"], "energy_trajectory_mismatch")
            self.assertEqual(annotated_shortlists[0]["primary_candidate"]["narrowing_report_path"], str(report_path))
            self.assertEqual(annotated_shortlists[0]["fallback_candidate"]["dominant_blocker_kind"], None)
            self.assertEqual(annotated_shortlists[1]["workload_id"], "graphene_pbe_uspp")
            self.assertEqual(annotated_shortlists[1]["primary_candidate"]["gate_reason"], "gold_mismatch")
            self.assertEqual(
                MODULE.build_stage_recommendation_gate(workload_summary),
                {
                    "stage_main_recommendation_status": "blocked_by_accurate_layer",
                    "eligible_source_workload_count": 0,
                    "blocked_source_workload_count": 2,
                    "not_assessed_source_workload_count": 0,
                    "blocked_source_workloads": [
                        "si4_pbe_uspp_small",
                        "graphene_pbe_uspp",
                    ],
                    "not_assessed_source_workloads": [],
                },
            )
            public = MODULE.build_public_recommendation_summary(
                annotated_shortlists,
                workload_summary,
                MODULE.build_stage_recommendation_gate(workload_summary),
            )
            self.assertEqual(public["public_recommended_family"], "none-yet")
            self.assertEqual(public["public_recommendation_type"], "evidence-incomplete")
            self.assertTrue(public["ranking_observations_retained"])
            self.assertEqual(
                public["ranking_observation_source_workloads"],
                ["si4_pbe_uspp_small", "graphene_pbe_uspp"],
            )
            self.assertFalse(public["projection_reporting_allowed"])
            self.assertEqual(public["suppression_reason"], "blocked_by_accurate_layer")
            self.assertEqual(
                public["next_narrowing_moves"],
                [
                    "Narrow the final_total_energy_ry mismatch on si8_pbe_nc for the shortlisted candidate(s) before allowing projection-grade recommendation."
                ],
            )
            self.assertEqual(public["runtime_risk_summary"]["overall_runtime_risk"], "unknown")
    def test_selected_design_points_fall_back_to_primary_families(self) -> None:
        config = json.loads(Path(MODULE.PHASE_CONFIG_PATH).read_text(encoding="utf-8"))
        runner = MODULE.load_runner()
        selected = MODULE.selected_design_points_for_accurate_layer([], config, runner)
        self.assertEqual(
            selected,
            [
                {
                    "family": "F1",
                    "diag_policy": "cpu_only",
                    "offload_scope": "single_hotpath",
                    "resident_policy": "fit_first",
                    "partition_strategy": "single_hotpath_partition",
                },
                {
                    "family": "F2",
                    "diag_policy": "device_first_fallback",
                    "offload_scope": "balanced",
                    "resident_policy": "fit_first",
                    "partition_strategy": "operator__build__diag__refresh",
                },
            ],
        )
        self.assertEqual(
            MODULE.summarize_accurate_validation_targets([], ["si4_pbe_uspp_small"]),
            [
                {
                    "source_workload_id": "si4_pbe_uspp_small",
                    "validation_target_count": 0,
                    "eligible_candidate_count": 0,
                    "ranking_observation_count": 0,
                    "blocked_candidate_count": 0,
                    "validation_gate_status": "not_assessed",
                    "blocked_selection_roles": [],
                    "gate_reasons": [],
                }
            ],
        )
        self.assertEqual(
            MODULE.build_stage_recommendation_gate(
                MODULE.summarize_accurate_validation_targets([], ["si4_pbe_uspp_small"])
            ),
            {
                "stage_main_recommendation_status": "awaiting_accurate_layer",
                "eligible_source_workload_count": 0,
                "blocked_source_workload_count": 0,
                "not_assessed_source_workload_count": 1,
                "blocked_source_workloads": [],
                "not_assessed_source_workloads": ["si4_pbe_uspp_small"],
            },
        )
        not_assessed_shortlists = [
            {
                "workload_id": "si4_pbe_uspp_small",
                "selection_status": "insufficient_evidence",
                "state_counts": {"reject": 0, "explain-only": 2, "promotion-eligible": 0},
                "primary_candidate": None,
                "fallback_candidate": None,
                "extra_promoted_candidates": [],
                "selection_notes": [],
                "design_points": [],
                "recommendation_status": "awaiting_accurate_layer",
                "publication_status": "awaiting_accurate_layer",
                "projection_reporting_allowed": False,
                "next_narrowing_move": "Run accurate-layer validation for shortlisted candidates before promoting any stage-main recommendation.",
            }
        ]
        public = MODULE.build_public_recommendation_summary(
            not_assessed_shortlists,
            MODULE.summarize_accurate_validation_targets([], ["si4_pbe_uspp_small"]),
            MODULE.build_stage_recommendation_gate(
                MODULE.summarize_accurate_validation_targets([], ["si4_pbe_uspp_small"])
            ),
        )
        self.assertEqual(public["public_recommended_family"], "none-yet")
        self.assertEqual(public["public_recommendation_type"], "evidence-incomplete")
        self.assertFalse(public["ranking_observations_retained"])
        self.assertEqual(public["ranking_observation_source_workloads"], [])
        self.assertFalse(public["projection_reporting_allowed"])
        self.assertEqual(public["suppression_reason"], "awaiting_fast_or_accurate_layer")
        self.assertEqual(
            public["next_narrowing_moves"],
            [
                "Run accurate-layer validation for shortlisted candidates before promoting any stage-main recommendation."
            ],
        )
        self.assertEqual(public["runtime_risk_summary"]["overall_runtime_risk"], "unknown")

    def test_filter_bundle_refreshes_candidate_family_summary_for_equal_candidates(self) -> None:
        runner = MODULE.load_runner()
        rows = [
            self.make_projected_candidate_result("caseA", "F2", "f2_template", "caseA__F2"),
            self.make_projected_candidate_result("caseA", "F4", "f4_template", "caseA__F4"),
            self.make_projected_candidate_result("caseA", "F5", "f5_template", "caseA__F5"),
            self.make_projected_candidate_result("caseA", "custom", "custom_template", "caseA__custom"),
        ]
        bundle = {
            "experiment": {
                "workloads": [
                    {
                        "workload_id": "caseA",
                        "lane": "qe_next_stage_mainline",
                    }
                ]
            },
            "results": rows,
            "family_summary": runner.build_family_summary(rows),
            "candidate_family_summary": [
                {
                    "candidate_family": "F5",
                    "result_count": 99,
                    "runtime_projection_families": ["stale"],
                    "architecture_template_ids": ["stale_template"],
                    "candidate_ids": ["stale_candidate"],
                    "support_status_counts": {"stale": 99},
                    "evaluator_backend_counts": {"stale": 99},
                    "fidelity_class_counts": {"stale": 99},
                    "projection_only_rows": 99,
                }
            ],
        }
        selected = [
            MODULE.candidate_to_design_point(MODULE.build_candidate_brief(row))
            for row in rows
            if row["candidate_family"] in {"F4", "F5", "custom"}
        ]

        MODULE.filter_bundle_to_design_points(bundle, selected, runner)

        self.assertEqual({row["candidate_family"] for row in bundle["results"]}, {"F4", "F5", "custom"})
        self.assertEqual({row["design_point"]["family"] for row in bundle["results"]}, {"F2"})
        family_by_id = {item["family"]: item for item in bundle["family_summary"]}
        self.assertEqual(family_by_id["F2"]["result_count"], 3)
        candidate_by_family = {
            item["candidate_family"]: item for item in bundle["candidate_family_summary"]
        }
        for family, template_id, candidate_id in (
            ("F4", "f4_template", "caseA__F4"),
            ("F5", "f5_template", "caseA__F5"),
            ("custom", "custom_template", "caseA__custom"),
        ):
            summary = candidate_by_family[family]
            self.assertEqual(summary["result_count"], 1)
            self.assertEqual(summary["runtime_projection_families"], ["F2"])
            self.assertEqual(summary["architecture_template_ids"], [template_id])
            self.assertEqual(summary["candidate_ids"], [candidate_id])
            self.assertEqual(summary["support_status_counts"], {"projection_only": 1})
            self.assertEqual(summary["evaluator_backend_counts"], {"systemc_timed_functional": 1})
            self.assertEqual(summary["fidelity_class_counts"], {"projection_only": 1})
            self.assertEqual(summary["projection_only_rows"], 1)
        self.assertEqual(candidate_by_family["F2"]["result_count"], 0)
        self.assertEqual(candidate_by_family["F5"]["architecture_template_ids"], ["f5_template"])

    def test_accurate_validation_targets_keep_equal_candidates_projected_through_f2_distinct(self) -> None:
        fast_rows = [
            self.make_projected_candidate_result("fast_case", "F4", "f4_template", "fast__F4"),
            self.make_projected_candidate_result("fast_case", "F5", "f5_template", "fast__F5"),
            self.make_projected_candidate_result("fast_case", "custom", "custom_template", "fast__custom"),
        ]
        accurate_rows = [
            self.make_projected_candidate_result("anchor_case", "F4", "f4_template", "anchor__F4"),
            self.make_projected_candidate_result("anchor_case", "F5", "f5_template", "anchor__F5"),
            self.make_projected_candidate_result("anchor_case", "custom", "custom_template", "anchor__custom"),
        ]
        shortlist = {
            "workload_id": "fast_case",
            "primary_candidate": MODULE.build_candidate_brief(fast_rows[0]),
            "fallback_candidate": MODULE.build_candidate_brief(fast_rows[1]),
            "extra_promoted_candidates": [MODULE.build_candidate_brief(fast_rows[2])],
        }

        targets = MODULE.build_accurate_validation_targets(
            [shortlist],
            {"results": accurate_rows},
        )

        target_by_role = {item["selection_role"]: item for item in targets}
        self.assertEqual(target_by_role["primary_candidate"]["accurate_layer_result_id"], "anchor__F4")
        self.assertEqual(target_by_role["fallback_candidate"]["accurate_layer_result_id"], "anchor__F5")
        self.assertEqual(target_by_role["extra_promoted_candidate_1"]["accurate_layer_result_id"], "anchor__custom")
        self.assertEqual(
            {row["runtime_projection_family"] for row in accurate_rows},
            {"F2"},
        )
        self.assertEqual(
            {cast(dict[str, Any], row["design_point"])["family"] for row in accurate_rows},
            {"F2"},
        )

    def test_build_projection_review_summary_for_projection_eligible_stage(self) -> None:
        shortlists = [
            {
                "workload_id": "si4_pbe_uspp_small",
                "workload_label": "QE small-Si proxy",
                "primary_candidate": {
                    "result_id": "si4__F1",
                    "family": "F1",
                    "diag_policy": "cpu_only",
                    "offload_scope": "single_hotpath",
                    "resident_policy": "fit_first",
                    "time_to_convergence_s": 0.53,
                    "energy_to_convergence_j": 13.2,
                    "bytes_moved_to_convergence": 1547633.6,
                    "fallback_ratio": 1.0,
                    "spill_ratio": 0.4,
                    "correctness_status": "pass",
                    "gold_pass": True,
                    "convergence_comparable_pass": True,
                    "recommendation_eligible": True,
                    "gate_reason": "accurate_layer_pass",
                    "accurate_layer_result_id": "si8__F1",
                    "runtime_observability": {
                        "last_diag_path": "device_accelerator",
                        "last_support_grid_mode": "FFT_AUX",
                        "last_workload_bucket": "medium",
                        "last_band_count": 24,
                        "last_panel_count": 3,
                        "configured_max_inner_steps": 3,
                        "realized_inner_steps": 3,
                        "last_max_diag_condition_estimate": 1.65,
                        "spill_active_count": 0,
                        "host_cpu_fallback_count": 0,
                    },
                    "graph_evidence": {
                        "seed_template_id": "f1_single_hotpath_graph_v0",
                        "topology_style": "host_heavy",
                        "cluster_cycle_summary": "cluster_a=0.60, cluster_b=0.20, cluster_c=0.13, cluster_d=0.07",
                        "component_score_source": "runtime_cluster_signature_weighted",
                        "execution_plan_summary": "requested=A>C | resolved=A>B_bypass>C>D_bypass | executed=A>B_bypass>C>D_bypass | source=resolved_cluster_sequence",
                    },
                    "graph_evidence_path": "/tmp/si4__F1.graph.json",
                    "narrowing_report_path": "report.json",
                    "narrowing_summary_path": "report.md",
                },
                "fallback_candidate": None,
                "extra_promoted_candidates": [],
                "next_narrowing_move": "Promote the accurate-layer-passing candidate into projection-grade recommendation review.",
            }
        ]
        stage_gate = {
            "stage_main_recommendation_status": "projection_eligible",
            "eligible_source_workload_count": 1,
            "blocked_source_workload_count": 0,
            "not_assessed_source_workload_count": 0,
            "blocked_source_workloads": [],
            "not_assessed_source_workloads": [],
        }
        public_recommendation = {
            "public_recommended_family": "F1",
            "public_recommendation_type": "projection-grade",
            "ranking_observations_retained": True,
            "ranking_observation_source_workloads": ["si4_pbe_uspp_small"],
            "projection_reporting_allowed": True,
            "suppression_reason": "none",
            "next_narrowing_moves": [
                "Promote the accurate-layer-passing candidate into projection-grade recommendation review."
            ],
        }

        review = MODULE.build_projection_review_summary(
            shortlists,
            stage_gate,
            public_recommendation,
        )

        self.assertEqual(review["package_kind"], "qe_next_stage_projection_review_v0")
        self.assertEqual(review["public_recommended_family"], "F1")
        self.assertEqual(review["promoted_candidate_count"], 1)
        self.assertEqual(review["promoted_source_workloads"], ["si4_pbe_uspp_small"])
        self.assertEqual(review["runtime_risk_summary"]["overall_runtime_risk"], "medium")
        self.assertEqual(
            review["recommended_validated_candidates"][0]["graph_evidence"]["seed_template_id"],
            "f1_single_hotpath_graph_v0",
        )
        self.assertIn(
            "style=",
            review["recommended_validated_candidates"][0]["graph_topology_summary"],
        )
        self.assertIn(
            "executed=A>B_bypass>C>D_bypass",
            review["recommended_validated_candidates"][0]["graph_execution_plan_summary"],
        )
        self.assertIn(
            "exec=requested=A>C",
            review["recommended_validated_candidates"][0]["graph_component_driver_summary"],
        )
        self.assertEqual(
            review["recommended_validated_candidates"][0]["accurate_layer_result_id"],
            "si8__F1",
        )
        self.assertEqual(
            review["recommended_validated_candidates"][0]["selection_role"],
            "primary_candidate",
        )
        self.assertEqual(review["review_readiness"], "ready")
        md = MODULE.render_projection_review_md(review)
        self.assertIn("runtime note", md)
        self.assertIn("device_accelerator", md)
        self.assertIn("runtime risk", md)
        self.assertIn("f1_single_hotpath_graph_v0", md)
        self.assertIn("graph_execution_plan", md)
        self.assertIn("/tmp/si4__F1.graph.json", md)

    def test_build_projection_review_summary_includes_eligible_fallbacks(self) -> None:
        shortlists = [
            {
                "workload_id": "graphene_pbe_uspp",
                "workload_label": "QE graphene USPP 2D proxy",
                "primary_candidate": {
                    "result_id": "graphene__F1",
                    "signature_id": "sig_graphene__uspp__generalized_overlap__2D__effective_mass",
                    "family": "F1",
                    "diag_policy": "cpu_only",
                    "offload_scope": "single_hotpath",
                    "resident_policy": "fit_first",
                    "partition_strategy": "single_hotpath_partition",
                    "recommendation_eligible": False,
                },
                "fallback_candidate": {
                    "result_id": "graphene__F2",
                    "signature_id": "sig_graphene__uspp__generalized_overlap__2D__effective_mass",
                    "family": "F2",
                    "diag_policy": "device_first_fallback",
                    "offload_scope": "balanced",
                    "resident_policy": "fit_first",
                    "partition_strategy": "operator__build__diag__refresh",
                    "time_to_convergence_s": 0.68,
                    "energy_to_convergence_j": 17.9,
                    "bytes_moved_to_convergence": 2001680.0,
                    "fallback_ratio": 0.5,
                    "spill_ratio": 0.5,
                    "correctness_status": "pass",
                    "gold_pass": True,
                    "convergence_comparable_pass": True,
                    "recommendation_eligible": True,
                    "gate_reason": "accurate_layer_pass",
                    "accurate_layer_result_id": "si8__F2",
                    "runtime_observability": {
                        "last_diag_path": "device_accelerator",
                        "last_support_grid_mode": "FFT_AUX",
                        "last_workload_bucket": "medium",
                        "last_band_count": 28,
                        "last_panel_count": 3,
                        "configured_max_inner_steps": 3,
                        "realized_inner_steps": 3,
                        "last_max_diag_condition_estimate": 1.60,
                        "spill_active_count": 0,
                        "host_cpu_fallback_count": 0,
                    },
                    "graph_evidence": {
                        "seed_template_id": "f2_balanced_graph_v0",
                        "topology_style": "balanced",
                        "cluster_cycle_summary": "cluster_a=0.54, cluster_b=0.22, cluster_c=0.16, cluster_d=0.08",
                        "component_score_source": "runtime_cluster_signature_weighted",
                        "execution_plan_summary": "requested=A>B>C | resolved=A>B>C>D_bypass | executed=A>B>C>D_bypass | source=projected_hints",
                    },
                    "graph_evidence_path": "/tmp/graphene__F2.graph.json",
                },
                "extra_promoted_candidates": [],
                "next_narrowing_move": "Promote the accurate-layer-passing candidate into projection-grade recommendation review.",
            }
        ]
        stage_gate = {
            "stage_main_recommendation_status": "projection_eligible",
            "eligible_source_workload_count": 1,
            "blocked_source_workload_count": 0,
            "not_assessed_source_workload_count": 0,
            "blocked_source_workloads": [],
            "not_assessed_source_workloads": [],
        }
        public_recommendation = {
            "public_recommended_family": "F1",
            "public_recommendation_type": "projection-grade",
            "ranking_observations_retained": True,
            "ranking_observation_source_workloads": ["graphene_pbe_uspp"],
            "projection_reporting_allowed": True,
            "suppression_reason": "none",
            "next_narrowing_moves": [
                "Promote the accurate-layer-passing candidate into projection-grade recommendation review."
            ],
        }

        review = MODULE.build_projection_review_summary(
            shortlists,
            stage_gate,
            public_recommendation,
        )

        self.assertEqual(review["promoted_candidate_count"], 1)
        self.assertEqual(review["runtime_risk_summary"]["overall_runtime_risk"], "medium")
        self.assertEqual(
            review["recommended_validated_candidates"][0]["selection_role"],
            "fallback_candidate",
        )
        self.assertEqual(
            review["recommended_validated_candidates"][0]["graph_evidence"]["seed_template_id"],
            "f2_balanced_graph_v0",
        )
        self.assertEqual(
            review["recommended_validated_candidates"][0]["fast_layer_result_id"],
            "graphene__F2",
        )
        self.assertEqual(
            review["recommended_validated_candidates"][0]["partition_strategy"],
            "operator__build__diag__refresh",
        )
        self.assertIn(
            "resolved=A>B>C>D_bypass",
            review["recommended_validated_candidates"][0]["graph_execution_plan_summary"],
        )
        self.assertIn(
            "source=projected_hints",
            review["recommended_validated_candidates"][0]["graph_component_driver_summary"],
        )
        md = MODULE.render_projection_review_md(review)
        self.assertIn("device_accelerator", md)
        self.assertIn("medium[", md)

    def test_build_stage_main_recommendation_package_separates_primary_and_alternatives(self) -> None:
        shortlists = [
            {
                "workload_id": "si4_pbe_uspp_small",
                "workload_label": "QE small-Si proxy",
                "primary_candidate": {
                    "result_id": "si4__F1",
                    "signature_id": "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
                    "family": "F1",
                    "diag_policy": "cpu_only",
                    "offload_scope": "single_hotpath",
                    "resident_policy": "fit_first",
                    "partition_strategy": "single_hotpath_partition",
                    "time_to_convergence_s": 0.53,
                    "energy_to_convergence_j": 13.2,
                    "avg_system_power_proxy_w": 13.2 / 0.53,
                    "correctness_status": "pass",
                    "gold_pass": True,
                    "convergence_comparable_pass": True,
                    "recommendation_eligible": True,
                    "gate_reason": "accurate_layer_pass",
                    "accurate_layer_result_id": "si8__F1",
                    "graph_evidence": {
                        "seed_template_id": "f1_single_hotpath_graph_v0",
                        "topology_style": "host_heavy",
                        "cluster_cycle_summary": "cluster_a=0.60, cluster_b=0.20, cluster_c=0.13, cluster_d=0.07",
                        "component_score_source": "runtime_cluster_signature_weighted",
                        "execution_plan_summary": "requested=A>C | resolved=A>B_bypass>C>D_bypass | executed=A>B_bypass>C>D_bypass | source=resolved_cluster_sequence",
                    },
                    "graph_evidence_path": "/tmp/si4__F1.graph.json",
                    "runtime_observability": {
                        "last_diag_path": "device_accelerator",
                        "last_support_grid_mode": "FFT_AUX",
                        "last_workload_bucket": "medium",
                        "last_band_count": 24,
                        "last_panel_count": 3,
                        "configured_max_inner_steps": 3,
                        "realized_inner_steps": 3,
                        "last_max_diag_condition_estimate": 1.65,
                        "spill_active_count": 0,
                        "host_cpu_fallback_count": 0,
                    },
                },
                "fallback_candidate": {
                    "result_id": "si4__F2",
                    "signature_id": "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
                    "family": "F2",
                    "diag_policy": "device_first_fallback",
                    "offload_scope": "balanced",
                    "resident_policy": "fit_first",
                    "partition_strategy": "operator__build__diag__refresh",
                    "time_to_convergence_s": 0.67,
                    "energy_to_convergence_j": 17.5,
                    "avg_system_power_proxy_w": 17.5 / 0.67,
                    "correctness_status": "pass",
                    "gold_pass": True,
                    "convergence_comparable_pass": True,
                    "recommendation_eligible": True,
                    "gate_reason": "accurate_layer_pass",
                    "accurate_layer_result_id": "si8__F2",
                    "graph_evidence": {
                        "seed_template_id": "f2_balanced_graph_v0",
                        "topology_style": "balanced",
                        "cluster_cycle_summary": "cluster_a=0.54, cluster_b=0.22, cluster_c=0.16, cluster_d=0.08",
                        "component_score_source": "runtime_cluster_signature_weighted",
                        "execution_plan_summary": "requested=A>B>C | resolved=A>B>C>D_bypass | executed=A>B>C>D_bypass | source=projected_hints",
                    },
                    "graph_evidence_path": "/tmp/si4__F2.graph.json",
                    "runtime_observability": {
                        "last_diag_path": "device_accelerator",
                        "last_support_grid_mode": "FFT_AUX",
                        "last_workload_bucket": "medium",
                        "last_band_count": 28,
                        "last_panel_count": 4,
                        "configured_max_inner_steps": 3,
                        "realized_inner_steps": 3,
                        "last_max_diag_condition_estimate": 1.60,
                        "spill_active_count": 0,
                        "host_cpu_fallback_count": 0,
                    },
                },
                "extra_promoted_candidates": [],
            }
        ]
        stage_gate = {
            "stage_main_recommendation_status": "projection_eligible",
            "eligible_source_workload_count": 1,
            "blocked_source_workload_count": 0,
            "not_assessed_source_workload_count": 0,
            "blocked_source_workloads": [],
            "not_assessed_source_workloads": [],
        }
        public_recommendation = {
            "public_recommended_family": "F1",
            "public_recommendation_type": "projection-grade",
            "ranking_observations_retained": True,
            "ranking_observation_source_workloads": ["si4_pbe_uspp_small"],
            "projection_reporting_allowed": True,
            "suppression_reason": "none",
            "next_narrowing_moves": [
                "Promote the accurate-layer-passing candidate into projection-grade recommendation review."
            ],
        }

        package = MODULE.build_stage_main_recommendation_package(
            shortlists,
            stage_gate,
            public_recommendation,
        )

        self.assertEqual(package["package_kind"], "qe_next_stage_stage_main_recommendation_v0")
        self.assertEqual(package["recommended_family"], "F1")
        self.assertEqual(package["recommended_primary_candidate_count"], 1)
        self.assertEqual(package["validated_alternative_candidate_count"], 1)
        self.assertEqual(len(package["why_not_other_families"]), 1)
        self.assertEqual(package["supported_source_workloads"], ["si4_pbe_uspp_small"])
        self.assertEqual(package["recommended_primary_candidates"][0]["family"], "F1")
        self.assertEqual(
            package["recommended_primary_candidates"][0]["signature_id"],
            "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
        )
        self.assertEqual(
            package["best_trusted_point"],
            {
                "recommended_family": "F1",
                "supported_source_workloads": ["si4_pbe_uspp_small"],
                "recommended_primary_candidate_count": 1,
            },
        )
        self.assertEqual(
            package["best_performance_candidate"]["signature_id"],
            "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
        )
        self.assertEqual(
            package["best_performance_candidate"]["partition_strategy"],
            "single_hotpath_partition",
        )
        self.assertEqual(package["best_performance_candidate"]["runtime_risk_level"], "medium")
        self.assertEqual(package["runtime_risk_summary"]["overall_runtime_risk"], "medium")
        self.assertEqual(
            package["best_performance_candidate"]["graph_evidence"]["seed_template_id"],
            "f1_single_hotpath_graph_v0",
        )
        self.assertIn(
            "style=",
            package["best_performance_candidate"]["graph_topology_summary"],
        )
        self.assertIn(
            "executed=A>B_bypass>C>D_bypass",
            package["best_performance_candidate"]["graph_execution_plan_summary"],
        )
        self.assertIn(
            "cluster=",
            package["best_performance_candidate"]["graph_component_driver_summary"],
        )
        self.assertEqual(
            package["validated_alternative_candidates"][0]["selection_role"],
            "fallback_candidate",
        )
        self.assertEqual(
            package["why_not_other_families"][0]["alternative_family"],
            "F2",
        )
        self.assertIn(
            "risk=",
            package["why_not_other_families"][0]["why_not_summary"],
        )
        best_point_summary = MODULE.build_best_point_summary(
            public_recommendation,
            stage_gate,
            projection_review=None,
            stage_main_package=package,
        )
        self.assertEqual(best_point_summary["status"], "ready")
        self.assertEqual(best_point_summary["source_surface"], "stage_main_recommendation_package")
        self.assertEqual(best_point_summary["recommendation_family"], "F1")
        self.assertEqual(best_point_summary["trusted_family"], "F1")
        self.assertEqual(best_point_summary["performance_family"], "F1")
        self.assertAlmostEqual(best_point_summary["best_point_avg_system_power_proxy_w"], 13.2 / 0.53)
        self.assertIn(
            "executed=A>B_bypass>C>D_bypass",
            best_point_summary["best_point_graph_execution_plan_summary"],
        )
        self.assertIn(
            "cluster=",
            best_point_summary["best_point_graph_component_driver_summary"],
        )

    def test_stage_main_package_can_split_trusted_and_performance_points(self) -> None:
        shortlists = [
            {
                "workload_id": "si4_pbe_uspp_small",
                "workload_label": "QE small-Si proxy",
                "primary_candidate": {
                    "result_id": "si4__F1",
                    "signature_id": "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
                    "family": "F1",
                    "diag_policy": "cpu_only",
                    "offload_scope": "single_hotpath",
                    "resident_policy": "fit_first",
                    "partition_strategy": "single_hotpath_partition",
                    "time_to_convergence_s": 0.53,
                    "energy_to_convergence_j": 13.2,
                    "correctness_status": "pass",
                    "gold_pass": True,
                    "convergence_comparable_pass": True,
                    "recommendation_eligible": True,
                    "gate_reason": "accurate_layer_pass",
                    "accurate_layer_result_id": "si8__F1",
                    "graph_evidence": {
                        "seed_template_id": "f1_single_hotpath_graph_v0",
                    },
                    "graph_evidence_path": "/tmp/si4__F1.graph.json",
                    "runtime_observability": {
                        "last_diag_path": "device_accelerator",
                        "last_support_grid_mode": "FFT_AUX",
                        "last_workload_bucket": "medium",
                        "last_band_count": 24,
                        "last_panel_count": 3,
                        "configured_max_inner_steps": 3,
                        "realized_inner_steps": 3,
                        "last_max_diag_condition_estimate": 1.65,
                        "spill_active_count": 0,
                        "host_cpu_fallback_count": 0,
                    },
                },
                "fallback_candidate": {
                    "result_id": "si4__F2",
                    "signature_id": "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
                    "family": "F2",
                    "diag_policy": "device_first_fallback",
                    "offload_scope": "balanced",
                    "resident_policy": "fit_first",
                    "partition_strategy": "operator__build__diag__refresh",
                    "time_to_convergence_s": 0.41,
                    "energy_to_convergence_j": 16.5,
                    "correctness_status": "pass",
                    "gold_pass": True,
                    "convergence_comparable_pass": True,
                    "recommendation_eligible": True,
                    "gate_reason": "accurate_layer_pass",
                    "accurate_layer_result_id": "si8__F2",
                    "graph_evidence": {
                        "seed_template_id": "f2_balanced_graph_v0",
                    },
                    "graph_evidence_path": "/tmp/si4__F2.graph.json",
                    "runtime_observability": {
                        "last_diag_path": "device_accelerator",
                        "last_support_grid_mode": "FFT_AUX",
                        "last_workload_bucket": "medium",
                        "last_band_count": 28,
                        "last_panel_count": 4,
                        "configured_max_inner_steps": 3,
                        "realized_inner_steps": 3,
                        "last_max_diag_condition_estimate": 1.60,
                        "spill_active_count": 0,
                        "host_cpu_fallback_count": 0,
                    },
                },
                "extra_promoted_candidates": [],
            }
        ]
        stage_gate = {
            "stage_main_recommendation_status": "projection_eligible",
            "eligible_source_workload_count": 1,
            "blocked_source_workload_count": 0,
            "not_assessed_source_workload_count": 0,
            "blocked_source_workloads": [],
            "not_assessed_source_workloads": [],
        }
        public_recommendation = {
            "public_recommended_family": "F1",
            "public_recommendation_type": "projection-grade",
            "ranking_observations_retained": True,
            "ranking_observation_source_workloads": ["si4_pbe_uspp_small"],
            "projection_reporting_allowed": True,
            "suppression_reason": "none",
            "next_narrowing_moves": [],
        }
        package = MODULE.build_stage_main_recommendation_package(
            shortlists,
            stage_gate,
            public_recommendation,
        )
        self.assertEqual(package["best_trusted_point"]["recommended_family"], "F1")
        self.assertEqual(package["best_performance_candidate"]["family"], "F2")
        self.assertEqual(package["runtime_risk_summary"]["overall_runtime_risk"], "medium")
        self.assertEqual(
            package["best_performance_candidate"]["fast_layer_result_id"],
            "si4__F2",
        )
        md = MODULE.render_stage_main_recommendation_md(package)
        self.assertIn("- diag_policy: `device_first_fallback`", md)
        self.assertIn("- offload_scope: `balanced`", md)
        self.assertIn("- resident_policy: `fit_first`", md)
        self.assertIn("- runtime_risk: `medium[", md)
        self.assertIn("- runtime: `diag=device_accelerator", md)
        self.assertIn("f2_balanced_graph_v0", md)
        self.assertIn("/tmp/si4__F2.graph.json", md)
        self.assertIn("## Why not other families", md)
        self.assertIn("time=", md)

    def test_build_stage_artifact_bundle_manifest_ready_when_packages_present(self) -> None:
        fast_info = {
            "json_path": "/tmp/fast.json",
            "csv_path": "/tmp/fast.csv",
        }
        accurate_info = {
            "json_path": "/tmp/accurate.json",
            "csv_path": "/tmp/accurate.csv",
        }
        accurate_coverage_info = {
            "json_path": "/tmp/coverage.json",
            "csv_path": "/tmp/coverage.csv",
        }
        accurate_coverage_summary = {
            "coverage_workload_count": 1,
            "coverage_result_count": 2,
            "coverage_pass_count": 2,
            "coverage_mismatch_count": 0,
            "coverage_ready": True,
        }
        generalization_coverage_info = {
            "json_path": "/tmp/generalization.json",
            "csv_path": "/tmp/generalization.csv",
        }
        generalization_coverage_summary = {
            "generalization_workload_count": 2,
            "generalization_result_count": 4,
            "generalization_pass_count": 2,
            "generalization_mismatch_count": 2,
            "generalization_ready": False,
        }
        stage_gate = {
            "stage_main_recommendation_status": "projection_eligible",
        }
        public_recommendation = {
            "public_recommended_family": "F1",
            "public_recommendation_type": "projection-grade",
        }
        projection_review = {
            "review_readiness": "ready",
            "promoted_candidate_count": 4,
            "json_path": "/tmp/review.json",
            "md_path": "/tmp/review.md",
        }
        stage_main_package = {
            "recommendation_status": "ready",
            "recommended_primary_candidate_count": 2,
            "validated_alternative_candidate_count": 2,
            "json_path": "/tmp/stage_main.json",
            "md_path": "/tmp/stage_main.md",
            "next_action": "ship it",
        }
        gpu_annex_summary = {
            "schema_version": "qe_gpu_annex_summary_v0",
            "status": "deferred",
            "reason": "no_gpu_baseline_dirs_configured",
            "source_surface": "gpu_baseline_readiness",
            "baseline_dir_count": 0,
            "counts": {
                "thesis_eligible": 0,
                "reference_only": 0,
                "deferred": 0,
                "decisive": 0,
            },
            "gpu_mode_set_measured": [],
            "gpu_decisive_modes": [],
            "decisive_case_ids": [],
            "row_ledger": [],
            "annex_note": "deferred",
        }

        manifest = MODULE.build_stage_artifact_bundle_manifest(
            phase_id="qe_next_stage_dse_simulator_v0",
            phase_config_path="/tmp/config.json",
            execute_model=True,
            source_kind="timed_functional_proxy",
            fast_info=fast_info,
            accurate_info=accurate_info,
            accurate_coverage_info=accurate_coverage_info,
            accurate_coverage_summary=accurate_coverage_summary,
            generalization_coverage_info=generalization_coverage_info,
            generalization_coverage_summary=generalization_coverage_summary,
            gpu_annex_summary=gpu_annex_summary,
            phase1_evidence_closure=None,
            stage_gate=stage_gate,
            public_recommendation=public_recommendation,
            projection_review=projection_review,
            stage_main_package=stage_main_package,
        )

        self.assertEqual(manifest["package_kind"], "qe_next_stage_artifact_bundle_manifest_v0")
        self.assertEqual(manifest["authority_scope"], "supporting_evidence_only")
        self.assertEqual(manifest["bundle_readiness"], "ready")
        self.assertTrue(manifest["release_ready_recommendation"])
        self.assertEqual(manifest["recommended_primary_candidate_count"], 2)
        self.assertEqual(manifest["validated_alternative_candidate_count"], 2)
        self.assertEqual(manifest["projection_review_candidate_count"], 4)
        self.assertEqual(manifest["accurate_coverage_summary"]["coverage_pass_count"], 2)
        self.assertEqual(manifest["generalization_coverage_summary"]["generalization_result_count"], 4)
        self.assertEqual(manifest["artifact_paths"]["fast_layer_json"], "/tmp/fast.json")
        self.assertEqual(manifest["artifact_paths"]["accurate_coverage_json"], "/tmp/coverage.json")
        self.assertEqual(manifest["artifact_paths"]["generalization_coverage_json"], "/tmp/generalization.json")
        self.assertEqual(manifest["gpu_annex_summary"]["status"], "deferred")
        self.assertIsNone(manifest["artifact_paths"]["gpu_annex_json"])
        self.assertIsNone(manifest["artifact_paths"]["gpu_case_decision_sheet_json"])
        self.assertIsNone(manifest["artifact_paths"]["gpu_workload_group_manifest_json"])
        self.assertEqual(
            manifest["artifact_paths"]["stage_main_recommendation_json"],
            "/tmp/stage_main.json",
        )

    def test_build_stage_artifact_bundle_manifest_requires_coverage_ready_when_present(self) -> None:
        gpu_annex_summary = {
            "schema_version": "qe_gpu_annex_summary_v0",
            "status": "deferred",
            "reason": "no_gpu_baseline_dirs_configured",
            "source_surface": "gpu_baseline_readiness",
            "baseline_dir_count": 0,
            "counts": {
                "thesis_eligible": 0,
                "reference_only": 0,
                "deferred": 0,
                "decisive": 0,
            },
            "gpu_mode_set_measured": [],
            "gpu_decisive_modes": [],
            "decisive_case_ids": [],
            "row_ledger": [],
            "annex_note": "deferred",
        }
        manifest = MODULE.build_stage_artifact_bundle_manifest(
            phase_id="qe_next_stage_dse_simulator_v0",
            phase_config_path="/tmp/config.json",
            execute_model=True,
            source_kind="timed_functional_proxy",
            fast_info={"json_path": "/tmp/fast.json", "csv_path": "/tmp/fast.csv"},
            accurate_info={"json_path": "/tmp/accurate.json", "csv_path": "/tmp/accurate.csv"},
            accurate_coverage_info={"json_path": "/tmp/coverage.json", "csv_path": "/tmp/coverage.csv"},
            accurate_coverage_summary={
                "coverage_workload_count": 1,
                "coverage_result_count": 2,
                "coverage_pass_count": 1,
                "coverage_mismatch_count": 1,
                "coverage_ready": False,
            },
            generalization_coverage_info=None,
            generalization_coverage_summary=None,
            gpu_annex_summary=gpu_annex_summary,
            phase1_evidence_closure=None,
            stage_gate={"stage_main_recommendation_status": "projection_eligible"},
            public_recommendation={
                "public_recommended_family": "F1",
                "public_recommendation_type": "projection-grade",
            },
            projection_review={
                "review_readiness": "ready",
                "promoted_candidate_count": 4,
                "json_path": "/tmp/review.json",
                "md_path": "/tmp/review.md",
            },
            stage_main_package={
                "recommendation_status": "ready",
                "recommended_primary_candidate_count": 2,
                "validated_alternative_candidate_count": 2,
                "json_path": "/tmp/stage_main.json",
                "md_path": "/tmp/stage_main.md",
                "next_action": "ship it",
            },
        )
        self.assertEqual(manifest["bundle_readiness"], "incomplete")
        self.assertFalse(manifest["release_ready_recommendation"])

    def test_build_advisor_pack_summary_uses_manifest_as_release_entry(self) -> None:
        manifest = {
            "json_path": "/tmp/manifest.json",
            "md_path": "/tmp/manifest.md",
            "release_ready_recommendation": True,
            "artifact_paths": {
                "gpu_annex_json": "/tmp/gpu_annex.json",
                "gpu_annex_md": "/tmp/gpu_annex.md",
            },
        }
        public_recommendation = {
            "public_recommended_family": "F1",
            "public_recommendation_type": "projection-grade",
        }
        best_point_summary = {
            "status": "ready",
            "recommendation_family": "F1",
            "trusted_family": "F1",
            "performance_family": "F2",
            "best_point_fast_layer_result_id": "si4__F2",
            "best_point_accurate_layer_result_id": "si8__F2",
            "best_point_time_to_convergence_s": 0.41,
            "best_point_energy_to_convergence_j": 16.5,
            "best_point_graph_topology_summary": "style=balanced",
            "best_point_graph_execution_plan_summary": "requested=A>B>C | resolved=A>B>C>D_bypass",
            "best_point_graph_component_driver_summary": "cluster=cluster_a=0.54",
        }
        gpu_annex_summary = {
            "status": "deferred",
            "reason": "no_gpu_baseline_dirs_configured",
        }
        phase1_evidence_closure = {
            "json_path": "/tmp/phase1.json",
            "md_path": "/tmp/phase1.md",
            "summary": {
                "decisive_lane_closed": False,
                "next_blocker_class": "external_measurement_artifacts",
            },
        }
        stage_main_package = {
            "json_path": "/tmp/stage_main.json",
            "md_path": "/tmp/stage_main.md",
        }
        advisor = MODULE.build_advisor_pack_summary(
            phase_id="qe_next_stage_dse_simulator_v0",
            phase_config_path="/tmp/config.json",
            stage_artifact_bundle_manifest=manifest,
            public_recommendation=public_recommendation,
            best_point_summary=best_point_summary,
            gpu_annex_summary=gpu_annex_summary,
            phase1_evidence_closure=phase1_evidence_closure,
            projection_review=None,
            stage_main_package=stage_main_package,
        )
        self.assertEqual(advisor["package_kind"], "qe_next_stage_advisor_pack_summary_v0")
        self.assertEqual(advisor["release_entry_kind"], "stage_artifact_bundle_manifest")
        self.assertEqual(advisor["authority_scope"], "supporting_evidence_only")
        self.assertEqual(advisor["closure_scope"], "qe_ic_dse_recommendation_package_only")
        self.assertEqual(advisor["trusted_family"], "F1")
        self.assertEqual(advisor["performance_family"], "F2")
        self.assertTrue(advisor["trusted_performance_divergence"])
        self.assertEqual(advisor["gpu_annex_status"], "deferred")
        self.assertEqual(advisor["thesis_claim_status"], "deferred")
        self.assertFalse(advisor["phase1_decisive_lane_closed"])
        self.assertEqual(advisor["phase1_next_blocker_class"], "external_measurement_artifacts")
        self.assertEqual(advisor["artifact_paths"]["manifest_json"], "/tmp/manifest.json")
        self.assertEqual(advisor["artifact_paths"]["gpu_annex_json"], "/tmp/gpu_annex.json")
        self.assertEqual(advisor["artifact_paths"]["phase1_evidence_closure_json"], "/tmp/phase1.json")
        md = MODULE.render_advisor_pack_summary_md(advisor)
        self.assertIn("QE Next-Stage Advisor Pack Summary", md)
        self.assertIn("release_entry_kind", md)
        self.assertIn("stage_artifact_bundle_manifest", md)

    def test_build_release_evidence_summary_tracks_phase1_and_gpu_residual_risks(self) -> None:
        manifest = {
            "json_path": "/tmp/manifest.json",
            "md_path": "/tmp/manifest.md",
            "bundle_readiness": "ready",
            "release_ready_recommendation": True,
            "artifact_paths": {
                "gpu_annex_json": "/tmp/gpu_annex.json",
                "gpu_annex_md": "/tmp/gpu_annex.md",
                "phase_summary_json": "/tmp/summary.json",
                "phase_summary_md": "/tmp/summary.md",
            },
        }
        public_recommendation = {
            "public_recommended_family": "F1",
            "public_recommendation_type": "projection-grade",
        }
        gpu_annex_summary = {
            "status": "reference_only",
            "reason": "reference_gpu_directory_materialized",
        }
        phase1_evidence_closure = {
            "json_path": "/tmp/phase1.json",
            "md_path": "/tmp/phase1.md",
            "summary": {
                "decisive_lane_closed": False,
                "next_blocker_class": "external_measurement_artifacts",
            },
        }
        best_point_summary = {
            "source_surface": "stage_main_recommendation_package",
            "best_point_fast_layer_result_id": "si4__F1",
            "best_point_accurate_layer_result_id": "si8__F1",
            "trusted_family": "F1",
            "performance_family": "F1",
        }
        advisor_pack_summary = {
            "json_path": "/tmp/advisor.json",
            "md_path": "/tmp/advisor.md",
        }
        release = MODULE.build_release_evidence_summary(
            phase_id="qe_next_stage_dse_simulator_v0",
            phase_config_path="/tmp/config.json",
            phase_runner_command="python3 run_qe_next_stage_dse_phase.py --output-dir /tmp/out",
            release_validator_command="python3 check_qe_next_stage_release_bundle.py --summary /tmp/out/summary.json",
            manifest=manifest,
            public_recommendation=public_recommendation,
            gpu_annex_summary=gpu_annex_summary,
            phase1_evidence_closure=phase1_evidence_closure,
            best_point_summary=best_point_summary,
            advisor_pack_summary=advisor_pack_summary,
        )
        self.assertEqual(release["package_kind"], "qe_next_stage_release_evidence_v0")
        self.assertEqual(release["gpu_annex_status"], "reference_only")
        self.assertFalse(release["phase1_decisive_lane_closed"])
        self.assertIn("gpu_annex_reference_only", release["residual_risks"])
        self.assertIn("phase1_evidence_external_measurement_artifacts", release["residual_risks"])
        self.assertIn("manifest_is_top_level_release_entry", release["safe_claims"])
        self.assertIn("stage_main_package_is_supporting_context_only", release["safe_claims"])
        md = MODULE.render_release_evidence_summary_md(release)
        self.assertIn("QE Next-Stage Release Evidence", md)

    def test_summarize_generalization_coverage_bundle_counts_pass_and_mismatch(self) -> None:
        bundle = {
            "results": [
                {
                    "workload": {"workload_id": "si4_pbe_uspp_small"},
                    "correctness": {"gold_pass": True, "status": "pass"},
                },
                {
                    "workload": {"workload_id": "graphene_pbe_uspp"},
                    "correctness": {"gold_pass": False, "status": "mismatch"},
                },
            ]
        }
        summary = MODULE.summarize_generalization_coverage_bundle(bundle)
        self.assertEqual(
            summary,
            {
                "generalization_workload_count": 2,
                "generalization_result_count": 2,
                "generalization_pass_count": 1,
                "generalization_mismatch_count": 1,
                "generalization_ready": False,
            },
        )

    def test_runner_default_workloads_include_h2_tiny_generalization_case(self) -> None:
        runner = MODULE.load_runner()
        self.assertIn("h2_tiny", runner.DEFAULT_WORKLOADS)
        self.assertEqual(runner.DEFAULT_WORKLOADS["h2_tiny"]["lane"], "qe_generalization")
        self.assertIn("graphene_pbe_paw", runner.DEFAULT_WORKLOADS)
        self.assertEqual(runner.DEFAULT_WORKLOADS["graphene_pbe_paw"]["lane"], "qe_generalization")

    @staticmethod
    def make_fast_result(
        result_id: str,
        workload_id: str,
        family: str,
        time_s: float | None,
        energy_j: float | None,
        bytes_moved: float | None,
        fallback_ratio: float | None,
        spill_ratio: float | None,
        ranking_ready: bool,
    ) -> dict[str, object]:
        return {
            "result_id": result_id,
            "result_status": "executed",
            "correctness": {"status": "not_required"},
            "design_point": {
                "family": family,
                "diag_policy": "cpu_only",
                "offload_scope": "single_hotpath",
                "resident_policy": "fit_first",
                "partition_strategy": "single_hotpath_partition",
            },
            "primary_metrics": {
                "time_to_convergence_s": time_s,
                "energy_to_convergence_j": energy_j,
                "bytes_moved_to_convergence": bytes_moved,
            },
            "secondary_metrics": {
                "fallback_ratio": fallback_ratio,
                "spill_ratio": spill_ratio,
            },
            "runtime_observability": {
                "last_diag_path": "device_accelerator",
                "last_support_grid_mode": "FFT_AUX",
                "last_workload_bucket": "medium",
                "last_band_count": 24,
                "last_panel_count": 3,
                "configured_max_inner_steps": 3,
                "realized_inner_steps": 3,
                "last_max_diag_condition_estimate": 1.65,
                "spill_active_count": 0,
                "host_cpu_fallback_count": 0,
            },
            "graph_evidence": {
                "graph_id": f"{result_id}::graph",
                "graph_schema_version": "qe_ic_graph_schema_v0",
                "seed_template_id": (
                    "f1_single_hotpath_graph_v0"
                    if family == "F1"
                    else ("f2_balanced_graph_v0" if family == "F2" else "f3_device_heavy_graph_v0")
                ),
                "graph_export_authority": "sidecar_evidence",
                "lossless_export_pass": True,
                "module_instance_count": 18 if family == "F1" else (25 if family == "F2" else 26),
                "link_count": 18 if family == "F1" else (25 if family == "F2" else 26),
                "flow_count": 2 if family != "F2" else 3,
                "critical_path_summary": (
                    "sys0 -> host -> dma0 -> chip0 -> flow0 -> sched0 -> cim0 -> diag0"
                    if family == "F1"
                    else (
                        "sys0 -> host -> dma0 -> chip0 -> flow0 -> epc0 -> sched0 -> nmem0 -> fft0 -> cim0 -> red0 -> diag0"
                        if family == "F2"
                        else "sys0 -> host -> dma0 -> chip0 -> flow0 -> epc0 -> sched0 -> nmem0 -> fft0 -> cim0 -> red0 -> diag0 -> vdiag0 -> ref0"
                    )
                ),
                "dataflow_bottleneck_summary": (
                    "host_to_fpga single-hotpath DMA handoff dominates"
                    if family == "F1"
                    else "operator-build-diag-refresh handoff dominates reduced-space dataflow"
                ),
                "topology_style": (
                    "host_heavy"
                    if family == "F1"
                    else ("balanced" if family == "F2" else "device_heavy")
                ),
                "control_plane_summary": (
                    "host_managed: system_container, host_controller, chip_execution_facade, cluster_flow_executor, command_scheduler"
                    if family == "F1"
                    else (
                        "shared_host_episode: system_container, host_controller, chip_execution_facade, cluster_flow_executor, episode_controller, command_scheduler"
                        if family == "F2"
                        else "episode_dominant: system_container, host_controller, chip_execution_facade, cluster_flow_executor, episode_controller, command_scheduler"
                    )
                ),
                "datapath_stage_summary": (
                    "context_loader -> digit_serial_input_boundary -> conjugate_sign_selector -> cim_operator_subchain -> cim_array_core -> residue_3m_core -> coefficient_accumulator -> near_sram_coeff_buffer -> near_sram_row_buffer -> row_merge_tree -> cim_array -> diag_unit"
                    if family == "F1"
                    else (
                        "near_memory_domain -> near_sram_support -> context_loader -> digit_serial_input_boundary -> conjugate_sign_selector -> cim_operator_subchain -> cim_array_core -> residue_3m_core -> coefficient_accumulator -> near_sram_coeff_buffer -> near_sram_row_buffer -> row_merge_tree -> fft_unit -> cim_array -> reduction_closure_engine -> reduction_unit -> diag_unit -> vector_diag_companion"
                        if family == "F2"
                        else "near_memory_domain -> near_sram_support -> context_loader -> digit_serial_input_boundary -> conjugate_sign_selector -> cim_operator_subchain -> cim_array_core -> residue_3m_core -> coefficient_accumulator -> near_sram_coeff_buffer -> near_sram_row_buffer -> row_merge_tree -> fft_unit -> cim_array -> reduction_closure_engine -> reduction_unit -> diag_unit -> vector_diag_companion -> refresh_unit"
                    )
                ),
                "key_component_refs_summary": (
                    "system_container, host_controller, dma_channel, chip_execution_facade, cluster_flow_executor, command_scheduler, context_loader, digit_serial_input_boundary, conjugate_sign_selector, cim_operator_subchain, cim_array_core, residue_3m_core, coefficient_accumulator, near_sram_coeff_buffer, near_sram_row_buffer, row_merge_tree, cim_array, diag_unit"
                    if family == "F1"
                    else (
                        "system_container, host_controller, dma_channel, chip_execution_facade, cluster_flow_executor, episode_controller, command_scheduler, near_memory_domain, near_sram_support, context_loader, digit_serial_input_boundary, conjugate_sign_selector, cim_operator_subchain, cim_array_core, residue_3m_core, coefficient_accumulator, near_sram_coeff_buffer, near_sram_row_buffer, row_merge_tree, fft_unit, cim_array, reduction_closure_engine, reduction_unit, diag_unit, vector_diag_companion"
                        if family == "F2"
                        else "system_container, host_controller, dma_channel, chip_execution_facade, cluster_flow_executor, episode_controller, command_scheduler, near_memory_domain, near_sram_support, context_loader, digit_serial_input_boundary, conjugate_sign_selector, cim_operator_subchain, cim_array_core, residue_3m_core, coefficient_accumulator, near_sram_coeff_buffer, near_sram_row_buffer, row_merge_tree, fft_unit, cim_array, reduction_closure_engine, reduction_unit, diag_unit, vector_diag_companion, refresh_unit"
                    )
                ),
                "leaf_component_refs_summary": (
                    "context_loader, digit_serial_input_boundary, conjugate_sign_selector, cim_operator_subchain, cim_array_core, residue_3m_core, coefficient_accumulator, near_sram_coeff_buffer, near_sram_row_buffer, row_merge_tree"
                    if family == "F1"
                    else "near_sram_support, context_loader, digit_serial_input_boundary, conjugate_sign_selector, cim_operator_subchain, cim_array_core, residue_3m_core, coefficient_accumulator, near_sram_coeff_buffer, near_sram_row_buffer, row_merge_tree, reduction_closure_engine"
                ),
                "bottleneck_component_summary": (
                    "dma_channel, context_loader, cim_array_core, residue_3m_core, diag_unit"
                    if family == "F1"
                    else (
                        "near_sram_support, context_loader, cim_array_core, residue_3m_core, reduction_closure_engine, diag_unit"
                        if family == "F2"
                        else "near_sram_support, context_loader, cim_array_core, residue_3m_core, reduction_closure_engine, vector_diag_companion, refresh_unit"
                    )
                ),
                "leaf_bottleneck_component_summary": (
                    "context_loader, cim_array_core, residue_3m_core, row_merge_tree"
                    if family == "F1"
                    else (
                        "near_sram_support, context_loader, cim_array_core, reduction_closure_engine"
                        if family == "F2"
                        else "near_sram_support, context_loader, cim_array_core, reduction_closure_engine"
                    )
                ),
                "risk_driver_component_summary": (
                    "host_controller, dma_channel, command_scheduler, context_loader, diag_unit"
                    if family == "F1"
                    else (
                        "episode_controller, near_memory_domain, near_sram_support, context_loader, reduction_closure_engine, vector_diag_companion"
                        if family == "F2"
                        else "episode_controller, near_memory_domain, near_sram_support, context_loader, reduction_closure_engine, vector_diag_companion, refresh_unit"
                    )
                ),
                "component_score_summary": (
                    "dma_channel=0.14, cim_array_core=0.12, residue_3m_core=0.10, context_loader=0.08, cim_operator_subchain=0.08, chip_execution_facade=0.08"
                    if family == "F1"
                    else (
                        "cim_array_core=0.09, residue_3m_core=0.08, near_sram_support=0.07, reduction_closure_engine=0.07, near_memory_domain=0.06, context_loader=0.06"
                        if family == "F2"
                        else "cim_array_core=0.09, residue_3m_core=0.08, near_sram_support=0.08, reduction_closure_engine=0.07, near_memory_domain=0.06, refresh_unit=0.05"
                    )
                ),
                "component_score_source": "runtime_cluster_signature_weighted",
                "execution_plan_summary": (
                    "requested=A>C, resolved=A>B_bypass>C>D_bypass, executed=A>B_bypass>C>D_bypass, source=resolved_cluster_sequence"
                    if family == "F1"
                    else (
                        "requested=A>B>C, resolved=A>B>C>D_bypass, executed=A>B>C>D_bypass, source=projected_hints"
                        if family == "F2"
                        else "requested=A>B>C>D, resolved=A>B>C>D, executed=A>B>C>D, source=resolved_cluster_sequence"
                    )
                ),
                "cluster_cycle_summary": (
                    "cluster_a=0.60, cluster_b=0.20, cluster_c=0.13, cluster_d=0.07"
                    if family == "F1"
                    else (
                        "cluster_a=0.54, cluster_b=0.22, cluster_c=0.16, cluster_d=0.08"
                        if family == "F2"
                        else "cluster_a=0.50, cluster_b=0.22, cluster_c=0.16, cluster_d=0.12"
                    )
                ),
                "component_score_signal_summary": (
                    "signature=projector=high,diag=high | runtime=iters=4, host_fallback=1/4, spill=0/4, fft_active=4/4, inner_cap_hits=1/4"
                    if family == "F1"
                    else (
                        "signature=projector=high,generalized=medium,fft=medium | runtime=iters=4, host_fallback=1/4, spill=1/4, fft_active=4/4, inner_cap_hits=1/4"
                        if family == "F2"
                        else "signature=projector=high,generalized=medium,diag=high,fft=medium | runtime=iters=4, host_fallback=1/4, spill=1/4, fft_active=4/4, inner_cap_hits=2/4"
                    )
                ),
                "iteration_behavior_summary": (
                    "iters=4, host_fallback=1/4, spill=0/4, fft_active=4/4, inner_cap_hits=1/4"
                    if family == "F1"
                    else (
                        "iters=4, host_fallback=1/4, spill=1/4, fft_active=4/4, inner_cap_hits=1/4"
                        if family == "F2"
                        else "iters=4, host_fallback=1/4, spill=1/4, fft_active=4/4, inner_cap_hits=2/4"
                    )
                ),
                "mapping_risk_summary": "low mapping risk: compatible with current family-scaffold export path",
            },
            "artifacts": {
                "graph_evidence_path": f"/tmp/{result_id}.graph.json",
            },
            "projection": {"ranking_grade_ready": ranking_ready},
            "workload": {
                "workload_id": workload_id,
                "label": workload_id,
                "signature_id": (
                    "sig_small_si__uspp__generalized_overlap__bulk__band_structure"
                    if workload_id == "si4_pbe_uspp_small"
                    else "sig_graphene__uspp__generalized_overlap__2D__effective_mass"
                ),
            },
        }

    @staticmethod
    def make_projected_candidate_result(
        workload_id: str,
        candidate_family: str,
        architecture_template_id: str,
        result_id: str,
    ) -> dict[str, object]:
        return {
            "result_id": result_id,
            "result_status": "executed",
            "candidate_family": candidate_family,
            "runtime_projection_family": "F2",
            "architecture_template_id": architecture_template_id,
            "candidate_id": result_id,
            "support_status": "projection_only",
            "evaluator_backend": "systemc_timed_functional",
            "fidelity_class": "projection_only",
            "correctness": {
                "status": "pass",
                "gold_pass": True,
                "convergence_comparable_pass": True,
                "required_field_failures": [],
                "notes": [],
            },
            "workload": {
                "workload_id": workload_id,
                "label": workload_id,
                "signature_id": f"sig::{workload_id}",
            },
            "design_point": {
                "family": "F2",
                "diag_policy": "device_first_fallback",
                "offload_scope": "balanced",
                "resident_policy": "fit_first",
                "partition_strategy": "operator__build__diag__refresh",
            },
            "primary_metrics": {
                "time_to_convergence_s": 1.0,
                "energy_to_convergence_j": 2.0,
                "avg_system_power_proxy_w": 2.0,
                "bytes_moved_to_convergence": 3.0,
            },
            "secondary_metrics": {
                "fallback_ratio": 0.0,
                "spill_ratio": 0.0,
            },
            "runtime_observability": {
                "last_diag_path": "device_accelerator",
                "last_support_grid_mode": "BYPASS",
                "last_workload_bucket": "medium",
                "last_band_count": 24,
                "last_panel_count": 3,
                "configured_max_inner_steps": 3,
                "realized_inner_steps": 2,
                "last_max_diag_condition_estimate": 1.2,
                "spill_active_count": 0,
                "host_cpu_fallback_count": 0,
            },
            "graph_evidence": {
                "seed_template_id": "f2_balanced_graph_v0",
            },
            "artifacts": {
                "graph_evidence_path": f"/tmp/{result_id}.graph.json",
            },
            "projection": {
                "ranking_grade_ready": True,
                "projection_grade_ready": True,
                "confidence": "exploratory",
            },
        }


if __name__ == "__main__":
    unittest.main()
