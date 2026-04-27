from __future__ import annotations

import importlib.util
import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("run_systemc_architecture_family_dse_sweep.py")
SPEC = importlib.util.spec_from_file_location("run_systemc_architecture_family_dse_sweep", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)

EXPANDED_TEMPLATE_IDS = {
    "f1_host_heavy_cpu_baseline_v1",
    "f3_tensor_systolic_fpga_offload_v1",
    "f2_systolic_fpga_dense_path_v1",
    "f3_hbm_streaming_operator_pipeline_v1",
    "custom_multichiplet_noc_partition_v1",
    "custom_near_memory_pim_resident_v1",
    "f5_cgra_dataflow_operator_v1",
    "f4_cim_dsp_hbm_hybrid_v1",
}

PROJECTION_ONLY_TEMPLATE_IDS = EXPANDED_TEMPLATE_IDS

RUNTIME_F2_FALLBACK_TEMPLATE_IDS = {
    "custom_multichiplet_noc_partition_v1",
    "custom_near_memory_pim_resident_v1",
    "f5_cgra_dataflow_operator_v1",
    "f4_cim_dsp_hbm_hybrid_v1",
}


class RunSystemcArchitectureFamilyDseSweepTests(unittest.TestCase):
    def test_unknown_fast_layer_assumption_set_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            assumptions_path = root / "proxy_assumptions.json"
            assumptions_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_fast_layer_proxy_assumption_set_v0",
                        "default_assumption_set_id": "qe_next_stage_phase_v0",
                        "assumption_sets": {
                            "qe_next_stage_phase_v0": {
                                "host_control_w": 1.0,
                                "host_assist_w": 1.0,
                                "dma_w": 1.0,
                                "idle_static_w": 1.0,
                                "family_device_power_w": {
                                    "F1": {"runtime": 1.0, "datapath": 1.0},
                                    "F2": {"runtime": 1.0, "datapath": 1.0},
                                    "F3": {"runtime": 1.0, "datapath": 1.0},
                                },
                            }
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(KeyError, "unknown fast-layer proxy assumption set"):
                MODULE.energy_proxy_assumptions("definitely_missing", assumptions_path)

    def test_energy_proxy_assumptions_missing_default_uses_canonical_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            assumptions_path = root / "proxy_assumptions.json"
            assumptions_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_fast_layer_proxy_assumption_set_v0",
                        "assumption_sets": {
                            "qe_next_stage_phase_v0": {
                                "host_control_w": 1.0,
                                "host_assist_w": 2.0,
                                "dma_w": 3.0,
                                "idle_static_w": 4.0,
                                "family_device_power_w": {
                                    "F1": {"runtime": 1.0, "datapath": 1.0},
                                    "F2": {"runtime": 1.0, "datapath": 1.0},
                                    "F3": {"runtime": 1.0, "datapath": 1.0},
                                },
                            }
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            selected = MODULE.energy_proxy_assumptions("", assumptions_path)

            self.assertEqual(selected["host_assist_w"], 2.0)

    def test_run_model_for_row_populates_fast_layer_ranking_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "cpu_baseline.json"
            baseline_path.write_text(
                json.dumps(
                    [
                        {
                            "case_id": "si4_pbe_uspp_small",
                            "electrons_wall_s": 0.35,
                            "scf_iterations": 7,
                        }
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )
            args = self.make_args(baseline_path)
            row = MODULE.build_result_row(
                MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"],
                "F1",
                "cpu_only",
                "single_hotpath",
                "fit_first",
                args,
            )
            bundle = {"experiment": {"run_id": "test-run"}}
            artifacts_dir = root / "artifacts"

            candidate = self.make_candidate()
            original_run = MODULE.subprocess.run

            def fake_run(cmd, cwd=None, env=None, stdout=None, stderr=None, text=None, check=False):
                assert env is not None
                result_json = Path(env["QEBS_RESULT_JSON"])
                result_json.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            MODULE.subprocess.run = fake_run
            try:
                ok, reason = MODULE.run_model_for_row(bundle, row, args, artifacts_dir)
            finally:
                MODULE.subprocess.run = original_run

            self.assertTrue(ok)
            self.assertEqual(reason, "executed")
            self.assertEqual(row["result_status"], "executed")
            self.assertEqual(row["stub_reason"], "")
            self.assertAlmostEqual(row["primary_metrics"]["time_to_convergence_s"], 0.01)
            self.assertAlmostEqual(row["primary_metrics"]["speedup_to_convergence"], 35.0)
            self.assertAlmostEqual(row["primary_metrics"]["bytes_moved_to_convergence"], 512.0 * 1024.0)
            self.assertAlmostEqual(row["secondary_metrics"]["fallback_ratio"], 1.0 / 4.0)
            self.assertAlmostEqual(row["secondary_metrics"]["spill_ratio"], 1.0 / 4.0)
            self.assertEqual(row["runtime_observability"]["last_diag_path"], "host_cpu_fallback")
            self.assertEqual(row["runtime_observability"]["last_support_grid_mode"], "FFT_AUX")
            self.assertEqual(row["runtime_observability"]["configured_max_inner_steps"], 4)
            self.assertEqual(row["runtime_observability"]["realized_inner_steps"], 3)
            self.assertEqual(row["runtime_observability"]["host_cpu_fallback_count"], 3)
            self.assertEqual(row["graph_evidence"]["seed_template_id"], "f1_single_hotpath_graph_v0")
            self.assertTrue(row["graph_evidence"]["lossless_export_pass"])
            self.assertEqual(row["graph_evidence"]["module_instance_count"], 18)
            self.assertEqual(row["graph_evidence"]["link_count"], 18)
            self.assertEqual(row["graph_evidence"]["flow_count"], 2)
            self.assertEqual(row["graph_evidence"]["topology_style"], "host_heavy")
            self.assertIn("host_managed", row["graph_evidence"]["control_plane_summary"])
            self.assertIn("context_loader", row["graph_evidence"]["bottleneck_component_summary"])
            self.assertIn("cim_array_core", row["graph_evidence"]["leaf_bottleneck_component_summary"])
            self.assertIn("context_loader", row["graph_evidence"]["leaf_component_refs_summary"])
            self.assertIn("cim_array_core", row["graph_evidence"]["component_score_summary"])
            self.assertEqual(row["graph_evidence"]["component_score_source"], "runtime_cluster_signature_weighted")
            self.assertIsNone(row["graph_evidence"]["execution_plan_summary"])
            self.assertIn("cluster_a=", row["graph_evidence"]["cluster_cycle_summary"])
            self.assertIn("signature=", row["graph_evidence"]["component_score_signal_summary"])
            self.assertIn("projector=high", row["graph_evidence"]["component_score_signal_summary"])
            self.assertIn("host_fallback=", row["graph_evidence"]["iteration_behavior_summary"])
            self.assertIn("system_container", row["graph_evidence"]["key_component_refs_summary"])
            self.assertIsNotNone(row["primary_metrics"]["energy_to_convergence_j"])
            self.assertAlmostEqual(
                row["primary_metrics"]["avg_system_power_proxy_w"],
                row["primary_metrics"]["energy_to_convergence_j"] / row["primary_metrics"]["time_to_convergence_s"],
            )
            self.assertTrue(row["projection"]["ranking_grade_ready"])
            self.assertEqual(row["design_point"]["partition_strategy"], "single_hotpath_partition")
            self.assertEqual(row["workload"]["signature_id"], "sig_small_si__uspp__generalized_overlap__bulk__band_structure")
            energy_total = sum(row["energy_ledger"][key] for key in row["energy_ledger"])
            self.assertAlmostEqual(row["primary_metrics"]["energy_to_convergence_j"], energy_total)

        # row should use the measured CPU shell aggregate as the fast-layer baseline id
        self.assertEqual(
            row["comparison_contract"]["qe_baseline_id"],
            "si4_pbe_uspp_small_qe_cpu_shell_aggregate_v0",
        )

    def test_build_model_env_includes_signature_fields(self) -> None:
        row = MODULE.build_result_row(
            MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"],
            "F1",
            "cpu_only",
            "single_hotpath",
            "fit_first",
            self.make_args(Path('/tmp/cpu_baseline.json')),
        )
        env = MODULE.model_env(
            MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"],
            row,
            Path("/tmp/candidate.json"),
            self.make_args(Path('/tmp/cpu_baseline.json')),
            1,
        )
        self.assertEqual(env["QEBS_SIGNATURE_ID"], "sig_small_si__uspp__generalized_overlap__bulk__band_structure")
        self.assertEqual(env["QEBS_PROPERTY_TARGET"], "band_structure")
        self.assertEqual(env["QEBS_PSEUDOPOTENTIAL_FAMILY"], "USPP")
        self.assertEqual(env["QEBS_SOLVER_PATH_CLASS"], "generalized_overlap")
        self.assertEqual(env["QEBS_WORKLOAD_TOPOLOGY"], "bulk")
        self.assertEqual(env["QEBS_POST_SCF_EXTENSION_LEVEL"], "shell_only")
        self.assertEqual(env["QEBS_PROJECTOR_PRESSURE"], "medium")
        self.assertEqual(env["QEBS_NONLOCAL_PRESSURE"], "medium")
        self.assertNotIn("QEBS_ARCH_CONFIG", env)

    def test_template_driven_bundle_emits_projected_config_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "cpu_baseline.json"
            baseline_path.write_text("[]", encoding="utf-8")
            template_dir = root / "templates"
            template_dir.mkdir()
            template_path = template_dir / "custom_template.json"
            template_path.write_text(
                json.dumps(self.make_template("custom_template_v1"), indent=2),
                encoding="utf-8",
            )
            design_space_spec = root / "design_space.json"
            design_space_spec.write_text(
                json.dumps(
                    {
                        "schema_version": "design_space_spec_v0",
                        "design_space_spec_id": "unit_design_space_v0",
                        "artifacts": [{"artifact_id": "template_catalog_unit"}],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            args = self.make_args(baseline_path)
            args.run_id = None
            args.source_model = "model/qe_band_solver_model"
            args.output_dir = root / "out"
            args.template_driven = True
            args.architecture_template_dir = template_dir
            args.architecture_template_ids = ["custom_template_v1"]
            args.design_space_spec = design_space_spec
            args.emit_projected_configs = True
            args.canonical_only = False
            args.max_design_points = 1

            bundle = MODULE.build_bundle(
                args,
                MODULE.utc_now(),
                [MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"]],
                ["F1", "F2", "F3"],
                MODULE.DIAG_POLICIES,
                MODULE.OFFLOAD_SCOPES,
                MODULE.RESIDENT_POLICIES,
                None,
            )

            self.assertEqual(len(bundle["results"]), 1)
            row = bundle["results"][0]
            self.assertEqual(row["architecture_template_id"], "custom_template_v1")
            self.assertEqual(row["candidate_id"], "0001__custom_template_v1__si4_pbe_uspp_small")
            self.assertEqual(row["template_family"], "F2")
            self.assertEqual(row["candidate_family"], "F2")
            self.assertEqual(row["runtime_projection_family"], "F2")
            self.assertEqual(row["evaluator_backend"], "systemc_timed_functional")
            self.assertEqual(row["support_status"], "projection_only")
            self.assertEqual(row["template_risk_level"], "low")
            self.assertEqual(row["template_validation_status"], "unit validated")
            self.assertEqual(row["design_space_spec_id"], "unit_design_space_v0")
            projected_config_path = Path(row["projected_config_path"])
            self.assertTrue(projected_config_path.exists())
            projected_config = json.loads(projected_config_path.read_text(encoding="utf-8"))
            self.assertEqual(projected_config["template_id"], "custom_template_v1")
            self.assertEqual(projected_config["architecture_family"], "F2")
            self.assertEqual(
                projected_config["projection_metadata"]["design_space_spec_id"],
                "unit_design_space_v0",
            )
            self.assertEqual(projected_config["projection_metadata"]["candidate_family"], "F2")
            self.assertEqual(projected_config["projection_metadata"]["runtime_projection_family"], "F2")
            self.assertEqual(projected_config["projection_metadata"]["support_status"], "projection_only")
            self.assertEqual(bundle["experiment"]["architecture_template_ids"], ["custom_template_v1"])
            self.assertEqual(bundle["experiment"]["design_space_spec_summary"]["artifact_ids"], ["template_catalog_unit"])

            env = MODULE.model_env(
                MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"],
                row,
                root / "candidate.json",
                args,
                1,
            )
            self.assertEqual(env["QEBS_ARCH_CONFIG"], str(projected_config_path))
            self.assertEqual(env["QEBS_CANDIDATE_FAMILY"], "F2")
            self.assertEqual(env["QEBS_RUNTIME_PROJECTION_FAMILY"], "F2")

            flat = MODULE.flatten_result(
                {
                    "schema_version": "systemc_architecture_family_dse_result_schema_v0",
                    "generated_at_utc": "2026-04-16T00:00:00Z",
                    "experiment": {"run_id": "test-run"},
                },
                row,
            )
            self.assertEqual(flat["architecture_template_id"], "custom_template_v1")
            self.assertEqual(flat["projected_config_path"], str(projected_config_path))
            self.assertEqual(flat["candidate_family"], "F2")
            self.assertEqual(flat["runtime_projection_family"], "F2")
            self.assertEqual(flat["support_status"], "projection_only")
            self.assertFalse(flat["executor_claim_allowed"])

    def test_template_driven_stage_a_expanded_catalog_rows_configs_and_projection_tags(self) -> None:
        template_specs = {
            "f1_host_heavy_cpu_baseline_v1": ("F1", "traditional_fpga_dsp", ["scaffold_only", "projection_only"]),
            "f3_tensor_systolic_fpga_offload_v1": ("F3", "traditional_fpga_dsp", ["scaffold_only", "projection_only"]),
            "f2_systolic_fpga_dense_path_v1": ("F2", "traditional_fpga_dsp", ["scaffold_only", "projection_only"]),
            "f3_hbm_streaming_operator_pipeline_v1": ("F3", "traditional_fpga_dsp", ["scaffold_only", "projection_only"]),
            "custom_multichiplet_noc_partition_v1": ("custom", "custom", ["scaffold_only", "projection_only"]),
            "custom_near_memory_pim_resident_v1": ("custom", "pim_3d_stacked", ["scaffold_only", "projection_only"]),
            "f5_cgra_dataflow_operator_v1": ("F5", "custom", ["scaffold_only", "projection_only"]),
            "f4_cim_dsp_hbm_hybrid_v1": ("F4", "hybrid_cim_dsp", ["scaffold_only", "projection_only"]),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "cpu_baseline.json"
            baseline_path.write_text("[]", encoding="utf-8")
            template_dir = root / "templates"
            template_dir.mkdir()
            for template_id, (family, compute_unit, tags) in template_specs.items():
                (template_dir / f"{template_id}.json").write_text(
                    json.dumps(
                        self.make_template(
                            template_id,
                            family=family,
                            compute_unit=compute_unit,
                            tags=tags,
                        ),
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            design_space_spec = root / "design_space.json"
            design_space_spec.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_architecture_family_design_space_spec_v0",
                        "design_space_id": "unit_expanded_stage_a_design_space_v0",
                        "artifacts": [{"artifact_id": "expanded_template_catalog_unit"}],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            args = self.make_args(baseline_path)
            args.run_id = None
            args.source_model = "model/qe_band_solver_model"
            args.output_dir = root / "out"
            args.template_driven = True
            args.architecture_template_dir = template_dir
            args.architecture_template_ids = list(template_specs)
            args.design_space_spec = design_space_spec
            args.emit_projected_configs = True
            args.canonical_only = False
            args.max_design_points = None

            bundle = MODULE.build_bundle(
                args,
                MODULE.utc_now(),
                [MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"]],
                ["F1", "F2", "F3"],
                MODULE.DIAG_POLICIES,
                MODULE.OFFLOAD_SCOPES,
                MODULE.RESIDENT_POLICIES,
                None,
            )

            emitted_ids = {str(row["architecture_template_id"]) for row in bundle["results"]}
            self.assertTrue(EXPANDED_TEMPLATE_IDS <= emitted_ids)
            self.assertEqual(set(bundle["experiment"]["architecture_template_ids"]), EXPANDED_TEMPLATE_IDS)
            self.assertEqual(
                bundle["experiment"]["design_space_spec_summary"]["design_space_spec_id"],
                "unit_expanded_stage_a_design_space_v0",
            )

            rows_by_template = {str(row["architecture_template_id"]): row for row in bundle["results"]}
            for template_id in EXPANDED_TEMPLATE_IDS:
                row = rows_by_template[template_id]
                projected_config_path = Path(str(row["projected_config_path"]))
                self.assertTrue(projected_config_path.exists(), template_id)
                projected_config = json.loads(projected_config_path.read_text(encoding="utf-8"))
                self.assertEqual(projected_config["template_id"], template_id)
                self.assertEqual(projected_config["architecture_family"], template_specs[template_id][0])
                self.assertEqual(row["candidate_family"], template_specs[template_id][0])
                self.assertEqual(
                    projected_config["projection_metadata"]["candidate_family"],
                    template_specs[template_id][0],
                )
                self.assertEqual(
                    projected_config["projection_metadata"]["source_template_id"],
                    template_id,
                )
                tags = set(projected_config["template_metadata"]["dse_metadata"].get("tags", []))
                row_tags = set(row["template_tags"])
                if template_id in PROJECTION_ONLY_TEMPLATE_IDS:
                    self.assertTrue({"scaffold_only", "projection_only"} <= tags, template_id)
                    self.assertTrue({"scaffold_only", "projection_only"} <= row_tags, template_id)
                    self.assertTrue(MODULE.row_is_projection_only(row), template_id)
                    self.assertEqual(row["support_status"], "projection_only", template_id)
                    self.assertFalse(row["support_evidence"]["executor_claim_allowed"], template_id)
                    if template_id in RUNTIME_F2_FALLBACK_TEMPLATE_IDS:
                        self.assertEqual(row["design_point"]["family"], "F2")
                        self.assertEqual(row["runtime_projection_family"], "F2")
                    else:
                        self.assertEqual(row["design_point"]["family"], template_specs[template_id][0])
                        self.assertEqual(row["runtime_projection_family"], template_specs[template_id][0])
                else:
                    self.assertFalse(MODULE.row_is_projection_only(row), template_id)

            manifest = MODULE.build_stage_a_coverage_manifest(
                bundle,
                root / "systemc_architecture_family_dse_bootstrap_v0.json",
            )
            self.assertEqual(manifest["coverage"]["architecture_template_count"], len(EXPANDED_TEMPLATE_IDS))
            self.assertTrue(EXPANDED_TEMPLATE_IDS <= set(manifest["coverage"]["architecture_template_ids"]))
            self.assertTrue({"F1", "F2", "F3", "F4", "F5", "custom"} <= set(manifest["coverage"]["candidate_families"]))
            self.assertIn("F2", set(manifest["coverage"]["runtime_families"]))
            self.assertEqual(manifest["coverage"]["support_status_counts"]["projection_only"], len(EXPANDED_TEMPLATE_IDS))
            self.assertEqual(
                manifest["readiness_counts"]["projection_only_rows"],
                len(PROJECTION_ONLY_TEMPLATE_IDS),
            )
            coverage_by_template = {
                item["architecture_template_id"]: item
                for item in manifest["template_coverage"]
            }
            for template_id in PROJECTION_ONLY_TEMPLATE_IDS:
                self.assertTrue(coverage_by_template[template_id]["projection_only"], template_id)
            for template_id in RUNTIME_F2_FALLBACK_TEMPLATE_IDS:
                self.assertEqual(coverage_by_template[template_id]["runtime_projection_family"], ["F2"])

    def test_template_candidate_family_preserved_for_projection_templates(self) -> None:
        template_specs = {
            "f4_unit": ("F4", "hybrid_cim_dsp", ["projection_only"]),
            "f5_unit": ("F5", "custom", ["projection_only"]),
            "custom_unit": ("custom", "pim_3d_stacked", ["projection_only"]),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = self.build_template_bundle(Path(tmpdir), template_specs)
            rows_by_template = {str(row["architecture_template_id"]): row for row in bundle["results"]}
            for template_id, (candidate_family, _compute_unit, _tags) in template_specs.items():
                row = rows_by_template[template_id]
                self.assertEqual(row["candidate_family"], candidate_family)
                self.assertEqual(row["runtime_projection_family"], "F2")
                self.assertEqual(row["design_point"]["family"], "F2")
                self.assertEqual(row["support_status"], "projection_only")
                self.assertTrue(MODULE.row_is_projection_only(row))

    def test_candidate_family_summary_counts_projection_only_templates(self) -> None:
        template_specs = {
            "f1_unit": ("F1", "traditional_fpga_dsp", ["projection_only"]),
            "f2_unit": ("F2", "traditional_fpga_dsp", ["projection_only"]),
            "f3_unit": ("F3", "traditional_fpga_dsp", ["projection_only"]),
            "f4_unit": ("F4", "hybrid_cim_dsp", ["projection_only"]),
            "f5_unit": ("F5", "custom", ["projection_only"]),
            "custom_unit": ("custom", "pim_3d_stacked", ["projection_only"]),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = self.build_template_bundle(Path(tmpdir), template_specs)
            summary_by_family = {item["candidate_family"]: item for item in bundle["candidate_family_summary"]}
            self.assertEqual(set(summary_by_family), {"F1", "F2", "F3", "F4", "F5", "custom"})
            for family in template_specs.values():
                summary = summary_by_family[family[0]]
                self.assertEqual(summary["result_count"], 1)
                self.assertEqual(summary["projection_only_rows"], 1)
                self.assertEqual(summary["support_status_counts"], {"projection_only": 1})

    def test_support_status_separate_from_candidate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = self.build_template_bundle(
                Path(tmpdir),
                {"f4_unit": ("F4", "hybrid_cim_dsp", ["projection_only"])},
            )
            row = bundle["results"][0]
            self.assertEqual(row["candidate_family"], "F4")
            self.assertEqual(row["runtime_projection_family"], "F2")
            self.assertEqual(row["support_status"], "projection_only")
            self.assertFalse(row["support_evidence"]["executor_claim_allowed"])
            self.assertIn("F4 candidate semantics", row["support_evidence"]["projection_reason"])

    def test_coverage_manifest_reports_candidate_and_runtime_axes(self) -> None:
        template_specs = {
            "f4_unit": ("F4", "hybrid_cim_dsp", ["projection_only"]),
            "custom_unit": ("custom", "pim_3d_stacked", ["projection_only"]),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = self.build_template_bundle(root, template_specs)
            manifest = MODULE.build_stage_a_coverage_manifest(
                bundle,
                root / "systemc_architecture_family_dse_bootstrap_v0.json",
            )
            self.assertEqual(set(manifest["coverage"]["candidate_families"]), {"F4", "custom"})
            self.assertEqual(manifest["coverage"]["runtime_families"], ["F2"])
            self.assertEqual(manifest["coverage"]["evaluator_backend_counts"], {"systemc_timed_functional": 2})
            self.assertEqual(manifest["coverage"]["fidelity_class_counts"], {"projection_only": 2})
            self.assertEqual(manifest["coverage"]["support_status_counts"], {"projection_only": 2})
            coverage_by_family = {item["candidate_family"]: item for item in manifest["candidate_family_coverage"]}
            self.assertEqual(coverage_by_family["F4"]["runtime_projection_families"], ["F2"])
            self.assertEqual(coverage_by_family["custom"]["runtime_projection_families"], ["F2"])

    def test_csv_includes_equal_candidate_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = self.build_template_bundle(
                root,
                {"f5_unit": ("F5", "custom", ["projection_only"])},
            )
            csv_path = root / "rows.csv"
            MODULE.write_csv(csv_path, bundle)
            with csv_path.open("r", encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["candidate_family"], "F5")
            self.assertEqual(rows[0]["runtime_projection_family"], "F2")
            self.assertEqual(rows[0]["support_status"], "projection_only")
            self.assertEqual(rows[0]["executor_claim_allowed"], "False")
            self.assertIn("F5 candidate semantics", rows[0]["projection_reason"])
            self.assertIn("Stage-A evidence only", rows[0]["claim_boundary"])

    def test_invalid_evidence_tuple_rejected_or_flagged(self) -> None:
        row = MODULE.build_result_row(
            MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"],
            "F2",
            "device_first_fallback",
            "balanced",
            "fit_first",
            self.make_args(Path("/tmp/cpu_baseline.json")),
        )
        row["evaluator_backend"] = "gem5_systemc_cosim_stub"
        row["fidelity_class"] = "measured"
        row["support_status"] = "native_runtime_supported"
        row["support_evidence"] = {
            "executor_claim_allowed": True,
            "native_runtime_evidence_path": "/tmp/native.json",
            "projection_reason": None,
            "future_backend_note": None,
            "claim_boundary": "invalid",
        }
        errors = MODULE.validate_evidence_tuple(row)
        self.assertIn("gem5_stub_requires_reserved_fidelity", errors)
        self.assertIn("gem5_stub_requires_stub_reserved_support", errors)
        self.assertIn("gem5_stub_cannot_allow_executor_claim", errors)
        self.assertIn("gem5_stub_cannot_have_native_evidence", errors)

    def test_native_support_requires_evidence_artifact(self) -> None:
        row = MODULE.build_result_row(
            MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"],
            "F2",
            "device_first_fallback",
            "balanced",
            "fit_first",
            self.make_args(Path("/tmp/cpu_baseline.json")),
        )
        row["support_status"] = "native_runtime_supported"
        row["fidelity_class"] = "timed_functional_proxy"
        row["support_evidence"] = {
            "executor_claim_allowed": True,
            "native_runtime_evidence_path": None,
            "projection_reason": None,
            "future_backend_note": None,
            "claim_boundary": "executor path only",
        }
        self.assertIn(
            "native_runtime_supported_requires_evidence_artifact",
            MODULE.validate_evidence_tuple(row),
        )

    def test_custom_rows_preserve_template_identity_in_summaries(self) -> None:
        template_specs = {
            "custom_a": ("custom", "custom", ["projection_only"]),
            "custom_b": ("custom", "pim_3d_stacked", ["projection_only"]),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = self.build_template_bundle(Path(tmpdir), template_specs)
            summary_by_family = {item["candidate_family"]: item for item in bundle["candidate_family_summary"]}
            custom_summary = summary_by_family["custom"]
            self.assertEqual(custom_summary["result_count"], 2)
            self.assertEqual(set(custom_summary["architecture_template_ids"]), {"custom_a", "custom_b"})
            self.assertEqual(len(custom_summary["candidate_ids"]), 2)
            manifest = MODULE.build_stage_a_coverage_manifest(
                bundle,
                Path(tmpdir) / "systemc_architecture_family_dse_bootstrap_v0.json",
            )
            coverage_by_family = {item["candidate_family"]: item for item in manifest["candidate_family_coverage"]}
            self.assertEqual(set(coverage_by_family["custom"]["architecture_template_ids"]), {"custom_a", "custom_b"})

    def test_template_driven_honors_max_design_points_before_sidecar_emit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "cpu_baseline.json"
            baseline_path.write_text("[]", encoding="utf-8")
            template_dir = root / "templates"
            template_dir.mkdir()
            for template_id in ("template_a", "template_b"):
                (template_dir / f"{template_id}.json").write_text(
                    json.dumps(self.make_template(template_id), indent=2),
                    encoding="utf-8",
                )
            args = self.make_args(baseline_path)
            args.run_id = None
            args.source_model = "model/qe_band_solver_model"
            args.output_dir = root / "out"
            args.template_driven = True
            args.architecture_template_dir = template_dir
            args.architecture_template_ids = None
            args.design_space_spec = None
            args.emit_projected_configs = True
            args.canonical_only = False
            args.max_design_points = 1

            bundle = MODULE.build_bundle(
                args,
                MODULE.utc_now(),
                [MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"]],
                ["F1", "F2", "F3"],
                MODULE.DIAG_POLICIES,
                MODULE.OFFLOAD_SCOPES,
                MODULE.RESIDENT_POLICIES,
                None,
            )

            self.assertEqual(len(bundle["results"]), 1)
            emitted = sorted((args.output_dir / "artifacts" / "architecture_configs").glob("*.json"))
            self.assertEqual(len(emitted), 1)
            self.assertIn("template_a", emitted[0].name)

    def test_run_model_for_row_missing_required_fast_metric_keeps_ranking_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "cpu_baseline.json"
            baseline_path.write_text(
                json.dumps(
                    [
                        {
                            "case_id": "si4_pbe_uspp_small",
                            "electrons_wall_s": 0.35,
                            "scf_iterations": 7,
                        }
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )
            args = self.make_args(baseline_path)
            row = MODULE.build_result_row(
                MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"],
                "F1",
                "cpu_only",
                "single_hotpath",
                "fit_first",
                args,
            )
            bundle = {"experiment": {"run_id": "test-run"}}
            artifacts_dir = root / "artifacts"

            candidate = self.make_candidate(include_total_ref_cycles=False)
            candidate_any = cast(Any, candidate)
            candidate_any["metrics"]["device_busy_ref_cycles"] = 0
            candidate_any["metrics"]["dma_ref_cycles"] = 0
            candidate_any["metrics"]["host_assist_ref_cycles"] = 0
            for cluster_metric in candidate_any["cluster_metrics"].values():
                cluster_metric["accounted_ref_cycles"] = 0
            original_run = MODULE.subprocess.run

            def fake_run(cmd, cwd=None, env=None, stdout=None, stderr=None, text=None, check=False):
                assert env is not None
                result_json = Path(env["QEBS_RESULT_JSON"])
                result_json.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            MODULE.subprocess.run = fake_run
            try:
                ok, reason = MODULE.run_model_for_row(bundle, row, args, artifacts_dir)
            finally:
                MODULE.subprocess.run = original_run

            self.assertTrue(ok)
            self.assertEqual(reason, "executed")
            self.assertIsNone(row["primary_metrics"]["energy_to_convergence_j"])
            self.assertFalse(row["projection"]["ranking_grade_ready"])

            config = json.loads(Path(MODULE.ROOT / "docs/benchmarks/qe_next_stage_dse_simulator_phase_config_v0.json").read_text(encoding="utf-8"))
            classification = self.load_phase_runner_module().classify_fast_layer_result(row, config)
            self.assertEqual(classification["state"], "explain-only")
            self.assertEqual(classification["reason"], "missing_fast_layer_metrics")

    def test_run_model_for_row_derives_energy_from_component_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "cpu_baseline.json"
            baseline_path.write_text(
                json.dumps(
                    [
                        {
                            "case_id": "si4_pbe_uspp_small",
                            "electrons_wall_s": 0.35,
                            "scf_iterations": 7,
                        }
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )
            args = self.make_args(baseline_path)
            row = MODULE.build_result_row(
                MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"],
                "F1",
                "cpu_only",
                "single_hotpath",
                "fit_first",
                args,
            )
            bundle = {"experiment": {"run_id": "test-run"}}
            artifacts_dir = root / "artifacts"

            candidate = self.make_candidate(include_total_ref_cycles=False)
            original_run = MODULE.subprocess.run

            def fake_run(cmd, cwd=None, env=None, stdout=None, stderr=None, text=None, check=False):
                assert env is not None
                result_json = Path(env["QEBS_RESULT_JSON"])
                result_json.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            MODULE.subprocess.run = fake_run
            try:
                ok, reason = MODULE.run_model_for_row(bundle, row, args, artifacts_dir)
            finally:
                MODULE.subprocess.run = original_run

            self.assertTrue(ok)
            self.assertEqual(reason, "executed")
            self.assertAlmostEqual(row["secondary_metrics"]["device_busy_ref_cycles"], 600.0)
            self.assertAlmostEqual(row["secondary_metrics"]["dma_ref_cycles"], 200.0)
            self.assertAlmostEqual(row["secondary_metrics"]["host_assist_ref_cycles"], 100.0)
            self.assertIsNotNone(row["primary_metrics"]["energy_to_convergence_j"])
            self.assertAlmostEqual(
                row["primary_metrics"]["avg_system_power_proxy_w"],
                row["primary_metrics"]["energy_to_convergence_j"] / row["primary_metrics"]["time_to_convergence_s"],
            )
            self.assertTrue(row["projection"]["ranking_grade_ready"])

    def test_finalize_fast_layer_bundle_metrics_anchors_to_cpu_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "cpu_baseline.json"
            baseline_path.write_text(
                json.dumps(
                    [
                        {
                            "case_id": "si4_pbe_uspp_small",
                            "pwscf_wall_s": 0.53,
                            "electrons_wall_s": 0.35,
                            "scf_iterations": 7,
                        }
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )
            args = self.make_args(baseline_path)
            row_f1 = MODULE.build_result_row(
                MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"],
                "F1",
                "cpu_only",
                "single_hotpath",
                "fit_first",
                args,
            )
            row_f2 = MODULE.build_result_row(
                MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"],
                "F2",
                "device_first_fallback",
                "balanced",
                "fit_first",
                args,
            )
            for row, ref_cycles, fallbacks in ((row_f1, 1000, 4), (row_f2, 1200, 0)):
                row["result_status"] = "executed"
                row["projection"]["ranking_grade_ready"] = False
                row["secondary_metrics"]["device_busy_ref_cycles"] = ref_cycles
                row["secondary_metrics"]["dma_ref_cycles"] = ref_cycles // 2
                row["secondary_metrics"]["host_assist_ref_cycles"] = ref_cycles // 4
                row["secondary_metrics"]["resident_reuse_hits"] = 2
                row["secondary_metrics"]["fallback_ratio"] = fallbacks / 4.0
                row["secondary_metrics"]["spill_ratio"] = 0.0
                row["primary_metrics"]["bytes_moved_to_convergence"] = 1024.0
                row["artifacts"]["metrics_path"] = str(root / f"{row['result_id']}.json")
                payload = {
                    "final": {
                        "converged": True,
                        "scf_iterations": 4,
                    },
                    "run_summary": {
                        "total_ref_cycles": ref_cycles,
                    },
                }
                Path(row["artifacts"]["metrics_path"]).write_text(
                    json.dumps(payload, indent=2), encoding="utf-8"
                )

            bundle = {
                "experiment": {"workloads": [MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"]]},
                "results": [row_f1, row_f2],
                "family_summary": MODULE.build_family_summary([row_f1, row_f2]),
            }

            MODULE.finalize_fast_layer_bundle_metrics(bundle, args)
            MODULE.refresh_family_summary(bundle)

            self.assertAlmostEqual(row_f1["primary_metrics"]["time_to_convergence_s"], 0.53)
            self.assertAlmostEqual(row_f1["primary_metrics"]["speedup_to_convergence"], 1.0)
            self.assertAlmostEqual(
                row_f1["primary_metrics"]["avg_system_power_proxy_w"],
                row_f1["primary_metrics"]["energy_to_convergence_j"] / row_f1["primary_metrics"]["time_to_convergence_s"],
            )
            self.assertAlmostEqual(row_f2["primary_metrics"]["time_to_convergence_s"], 0.636)
            self.assertAlmostEqual(row_f2["primary_metrics"]["speedup_to_convergence"], 0.8333333333333334)
            self.assertAlmostEqual(
                row_f2["primary_metrics"]["avg_system_power_proxy_w"],
                row_f2["primary_metrics"]["energy_to_convergence_j"] / row_f2["primary_metrics"]["time_to_convergence_s"],
            )
            self.assertTrue(row_f1["projection"]["ranking_grade_ready"])
            self.assertTrue(row_f2["projection"]["ranking_grade_ready"])
            summary_by_family = {item["family"]: item for item in bundle["family_summary"]}
            self.assertEqual(summary_by_family["F1"]["ranking_grade_status"], "ready")
            self.assertEqual(summary_by_family["F2"]["ranking_grade_status"], "ready")
            self.assertEqual(summary_by_family["F1"]["canonical_partition_strategy"], "single_hotpath_partition")
            flat = MODULE.flatten_result(
                {
                    "schema_version": "systemc_architecture_family_dse_result_schema_v0",
                    "generated_at_utc": "2026-04-16T00:00:00Z",
                    "experiment": {"run_id": "test-run"},
                },
                row_f1,
            )
            self.assertEqual(flat["partition_strategy"], "single_hotpath_partition")
            self.assertEqual(flat["signature_id"], "sig_small_si__uspp__generalized_overlap__bulk__band_structure")
            self.assertAlmostEqual(
                flat["avg_system_power_proxy_w"],
                row_f1["primary_metrics"]["avg_system_power_proxy_w"],
            )

    def test_finalize_preserves_direct_ranking_ready_without_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "cpu_baseline.json"
            baseline_path.write_text(
                json.dumps(
                    [
                        {
                            "case_id": "si4_pbe_uspp_small",
                            "electrons_wall_s": 0.35,
                            "scf_iterations": 7,
                        }
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )
            args = self.make_args(baseline_path)
            row = MODULE.build_result_row(
                MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"],
                "F2",
                "device_first_fallback",
                "balanced",
                "fit_first",
                args,
            )
            row["result_status"] = "executed"
            row["primary_metrics"]["time_to_convergence_s"] = 0.01
            row["primary_metrics"]["speedup_to_convergence"] = 35.0
            row["primary_metrics"]["energy_to_convergence_j"] = 0.1
            row["primary_metrics"]["bytes_moved_to_convergence"] = 1024.0
            row["secondary_metrics"]["fallback_ratio"] = 0.0
            row["secondary_metrics"]["spill_ratio"] = 0.0
            row["secondary_metrics"]["device_busy_ref_cycles"] = 0.0
            row["secondary_metrics"]["dma_ref_cycles"] = 128.0
            row["secondary_metrics"]["host_assist_ref_cycles"] = 0.0
            row["projection"]["ranking_grade_ready"] = True
            row["artifacts"]["metrics_path"] = str(root / f"{row['result_id']}.json")
            Path(row["artifacts"]["metrics_path"]).write_text(
                json.dumps(
                    {
                        "final": {
                            "converged": True,
                            "scf_iterations": 11,
                        },
                        "run_summary": {
                            "total_ref_cycles": 0,
                        },
                        "metrics": {
                            "device_busy_ref_cycles": 0,
                            "dma_ref_cycles": 128,
                            "host_assist_ref_cycles": 0,
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            bundle = {
                "experiment": {"workloads": [MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"]]},
                "results": [row],
                "family_summary": MODULE.build_family_summary([row]),
            }

            MODULE.finalize_fast_layer_bundle_metrics(bundle, args)

            self.assertTrue(row["projection"]["ranking_grade_ready"])

    def test_main_consumes_case_pack_workload_descriptors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_pack = root / "case_pack.json"
            case_pack.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_ic_case_pack_v0",
                        "bundle_role": "canonical_f1_seed_pack",
                        "seed_family": "F1",
                        "stage_a_bringup_descriptors": [
                            {
                                "workload_id": "si4_pbe_uspp_small",
                                "display_label": "Custom si4 label",
                                "software_family": "QE",
                                "flow_family": "QE_SCF",
                                "trait_bucket": "USPP-heavy",
                                "lane": "qe_next_stage_mainline",
                                "gold_required": False,
                                "first_priority_convergence_case": False,
                                "signature_id": "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
                                "property_target": "band_structure",
                                "pseudopotential_family": "USPP",
                                "solver_path_class": "generalized_overlap",
                                "workload_topology": "bulk",
                                "post_scf_extension_level": "shell_only",
                                "projector_pressure": "medium",
                                "nonlocal_pressure": "medium",
                                "generalized_ratio_bucket": "medium",
                                "diag_dominance": "medium",
                                "fft_grid_pressure": "medium",
                                "family": "F1",
                                "diag_policy": "cpu_only",
                                "offload_scope": "single_hotpath",
                                "resident_policy": "fit_first",
                                "partition_strategy": "single_hotpath_partition",
                                "canonical_profile_match": True,
                                "workload_group_id": MODULE.PHASE1_WORKLOAD_GROUP_ID,
                                "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                                "accounting_boundary_id": "scf_shell_convergence_scope_v1",
                                "fairness_policy_id": MODULE.PHASE1_FAIRNESS_POLICY_ID,
                                "power_boundary_id": MODULE.PHASE1_POWER_BOUNDARY_ID,
                                "observability_contract_id": MODULE.PHASE1_OBSERVABILITY_CONTRACT_ID,
                                "algorithm_rewrite_manifest_id": MODULE.PHASE1_REWRITE_MANIFEST_ID,
                                "algorithm_contract_deviation": False,
                                "source_kind": "trace_calibrated_proxy",
                                "trace_shape_id": "si4_pbe_uspp_small__trace_shape_v0",
                                "trace_shape_summary": {
                                    "trait_bucket": "USPP-heavy",
                                    "signature_id": "sig_small_si__uspp__generalized_overlap__bulk__band_structure",
                                },
                                "fast_proxy_assumption_set_id": "qe_next_stage_phase_v0",
                                "gpu_baseline_state": "pending",
                                "gpu_baseline_row_ref": None,
                            }
                        ],
                        "stage_b_nonblocking_signature_descriptors": [],
                        "accurate_layer_anchor_descriptors": [],
                        "accurate_layer_coverage_descriptors": [],
                        "accurate_layer_generalization_descriptors": [],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            out = root / "out"
            import sys
            old_argv = sys.argv
            try:
                sys.argv = [
                    "run_systemc_architecture_family_dse_sweep.py",
                    "--output-dir",
                    str(out),
                    "--workloads",
                    "si4_pbe_uspp_small",
                    "--case-pack",
                    str(case_pack),
                    "--max-design-points",
                    "1",
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            bundle_path = out / "systemc_architecture_family_dse_bootstrap_v0.json"
            bundle_text = bundle_path.read_text(encoding="utf-8")
            self.assertNotIn("pending_calibration_v0", bundle_text)
            self.assertNotIn("pending_qe_numerical_tolerance_schema_v0", bundle_text)
            bundle = json.loads(bundle_text)
            self.assertEqual(bundle["experiment"]["assumption_set_id"], "qe_next_stage_phase_v0")
            self.assertEqual(
                bundle["experiment"]["qe_tolerance_schema_id"],
                "qe_gold_numerical_tolerance_schema_v0",
            )
            self.assertEqual(bundle["experiment"]["case_pack_summary"]["bundle_role"], "canonical_f1_seed_pack")
            self.assertEqual(
                bundle["results"][0]["comparison_contract"]["qe_tolerance_schema_id"],
                "qe_gold_numerical_tolerance_schema_v0",
            )
            self.assertEqual(bundle["results"][0]["projection"]["assumption_set_id"], "qe_next_stage_phase_v0")
            self.assertEqual(bundle["results"][0]["workload"]["label"], "Custom si4 label")
            self.assertTrue(bundle["results"][0]["projection"]["projection_grade_ready"])
            self.assertEqual(bundle["results"][0]["graph_evidence"]["seed_template_id"], "f1_single_hotpath_graph_v0")
            graph_sidecar = Path(bundle["results"][0]["artifacts"]["graph_evidence_path"])
            self.assertTrue(graph_sidecar.exists())
            coverage_path = out / "stage_a_coverage_manifest_v0.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            self.assertEqual(coverage["coverage"]["result_count"], 1)
            self.assertEqual(coverage["readiness_counts"]["projection_grade_ready"], 1)
            self.assertEqual(coverage["projection_readiness_failure_counts"], {})
            adjudicator_ref_path = out / "qe_system_design_adjudicator_reference.json"
            adjudicator_ref = json.loads(adjudicator_ref_path.read_text(encoding="utf-8"))
            self.assertEqual(adjudicator_ref["authority_scope"], "adjudicator_only")
            self.assertEqual(adjudicator_ref["reference_status"], "present")
            self.assertEqual(Path(adjudicator_ref["reference_path"]), adjudicator_ref_path)
            self.assertTrue(Path(adjudicator_ref["decision_memo_json"]).exists())
            self.assertTrue(Path(adjudicator_ref["decision_memo_md"]).exists())
            self.assertIn(
                "Authority note: this DSE bundle is an evidence input only; final recommendation authority belongs to the adjudicator memo.",
                bundle["notes"],
            )
            self.assertIn(
                f"Adjudicator reference JSON: {adjudicator_ref_path}",
                bundle["notes"],
            )
            self.assertIn(
                f"Stage-A coverage manifest JSON: {coverage_path}",
                bundle["notes"],
            )

    def test_main_rejects_duplicate_workload_ids_without_section_selector(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_pack = root / "case_pack.json"
            case_pack.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_ic_case_pack_v0",
                        "bundle_role": "canonical_f1_seed_pack",
                        "seed_family": "F1",
                        "stage_a_bringup_descriptors": [
                            {"workload_id": "si4_pbe_uspp_small", "display_label": "Stage A label", "software_family": "QE", "flow_family": "QE_SCF", "trait_bucket": "USPP-heavy", "lane": "qe_next_stage_mainline", "gold_required": False, "first_priority_convergence_case": False, "signature_id": "sigA", "property_target": "band_structure", "pseudopotential_family": "USPP", "solver_path_class": "generalized_overlap", "workload_topology": "bulk", "post_scf_extension_level": "shell_only", "projector_pressure": "medium", "nonlocal_pressure": "medium", "generalized_ratio_bucket": "medium", "diag_dominance": "medium", "fft_grid_pressure": "medium", "family": "F1", "diag_policy": "cpu_only", "offload_scope": "single_hotpath", "resident_policy": "fit_first", "partition_strategy": "single_hotpath_partition", "canonical_profile_match": True, "workload_group_id": MODULE.PHASE1_WORKLOAD_GROUP_ID, "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0", "accounting_boundary_id": "scf_shell_convergence_scope_v1", "fairness_policy_id": MODULE.PHASE1_FAIRNESS_POLICY_ID, "power_boundary_id": MODULE.PHASE1_POWER_BOUNDARY_ID, "observability_contract_id": MODULE.PHASE1_OBSERVABILITY_CONTRACT_ID, "algorithm_rewrite_manifest_id": MODULE.PHASE1_REWRITE_MANIFEST_ID, "algorithm_contract_deviation": False, "source_kind": "trace_calibrated_proxy", "trace_shape_id": "si4__trace", "trace_shape_summary": {"trait_bucket": "USPP-heavy", "signature_id": "sigA"}, "fast_proxy_assumption_set_id": "qe_next_stage_phase_v0", "gpu_baseline_state": "pending", "gpu_baseline_row_ref": None}
                        ],
                        "stage_b_nonblocking_signature_descriptors": [],
                        "accurate_layer_anchor_descriptors": [],
                        "accurate_layer_coverage_descriptors": [],
                        "accurate_layer_generalization_descriptors": [
                            {"workload_id": "si4_pbe_uspp_small", "display_label": "Generalization label", "software_family": "QE", "flow_family": "QE_SCF", "trait_bucket": "USPP-heavy", "lane": "qe_next_stage_mainline", "gold_required": True, "first_priority_convergence_case": False, "signature_id": "sigB", "property_target": "band_structure", "pseudopotential_family": "USPP", "solver_path_class": "generalized_overlap", "workload_topology": "bulk", "post_scf_extension_level": "shell_only", "projector_pressure": "medium", "nonlocal_pressure": "medium", "generalized_ratio_bucket": "medium", "diag_dominance": "medium", "fft_grid_pressure": "medium", "family": "F1", "diag_policy": "cpu_only", "offload_scope": "single_hotpath", "resident_policy": "fit_first", "partition_strategy": "single_hotpath_partition", "workload_group_id": MODULE.PHASE1_WORKLOAD_GROUP_ID, "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0", "accounting_boundary_id": "scf_shell_convergence_scope_v1", "fairness_policy_id": MODULE.PHASE1_FAIRNESS_POLICY_ID, "power_boundary_id": MODULE.PHASE1_POWER_BOUNDARY_ID, "observability_contract_id": MODULE.PHASE1_OBSERVABILITY_CONTRACT_ID, "algorithm_rewrite_manifest_id": MODULE.PHASE1_REWRITE_MANIFEST_ID, "algorithm_contract_deviation": False, "source_kind": "trace_calibrated_proxy", "calibration_manifest_id": "si4__cal", "gold_case_bundle_id": "si4__gold", "gold_source_path": "/tmp/gold", "reduced_space_contract_id": "qe_reduced_space_validation_contract_v0", "convergence_reference_id": "si4__conv", "numerical_provenance_tag": "calibrated", "gpu_baseline_state": "pending", "gpu_baseline_row_ref": None, "decisive_for_case": False}
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            out = root / "out"
            import sys
            old_argv = sys.argv
            try:
                sys.argv = [
                    "run_systemc_architecture_family_dse_sweep.py",
                    "--output-dir",
                    str(out),
                    "--workloads",
                    "si4_pbe_uspp_small",
                    "--case-pack",
                    str(case_pack),
                    "--max-design-points",
                    "1",
                ]
                with self.assertRaisesRegex(ValueError, "appears in multiple selected sections"):
                    MODULE.main()
            finally:
                sys.argv = old_argv

    def test_main_consumes_duplicate_workload_with_explicit_section_selector(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_pack = root / "case_pack.json"
            case_pack.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_ic_case_pack_v0",
                        "bundle_role": "canonical_f1_seed_pack",
                        "seed_family": "F1",
                        "stage_a_bringup_descriptors": [
                            {"workload_id": "si4_pbe_uspp_small", "display_label": "Stage A label", "software_family": "QE", "flow_family": "QE_SCF", "trait_bucket": "USPP-heavy", "lane": "qe_next_stage_mainline", "gold_required": False, "first_priority_convergence_case": False, "signature_id": "sigA", "property_target": "band_structure", "pseudopotential_family": "USPP", "solver_path_class": "generalized_overlap", "workload_topology": "bulk", "post_scf_extension_level": "shell_only", "projector_pressure": "medium", "nonlocal_pressure": "medium", "generalized_ratio_bucket": "medium", "diag_dominance": "medium", "fft_grid_pressure": "medium", "family": "F1", "diag_policy": "cpu_only", "offload_scope": "single_hotpath", "resident_policy": "fit_first", "partition_strategy": "single_hotpath_partition", "canonical_profile_match": True, "workload_group_id": MODULE.PHASE1_WORKLOAD_GROUP_ID, "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0", "accounting_boundary_id": "scf_shell_convergence_scope_v1", "fairness_policy_id": MODULE.PHASE1_FAIRNESS_POLICY_ID, "power_boundary_id": MODULE.PHASE1_POWER_BOUNDARY_ID, "observability_contract_id": MODULE.PHASE1_OBSERVABILITY_CONTRACT_ID, "algorithm_rewrite_manifest_id": MODULE.PHASE1_REWRITE_MANIFEST_ID, "algorithm_contract_deviation": False, "source_kind": "trace_calibrated_proxy", "trace_shape_id": "si4__trace", "trace_shape_summary": {"trait_bucket": "USPP-heavy", "signature_id": "sigA"}, "fast_proxy_assumption_set_id": "qe_next_stage_phase_v0", "gpu_baseline_state": "pending", "gpu_baseline_row_ref": None}
                        ],
                        "stage_b_nonblocking_signature_descriptors": [],
                        "accurate_layer_anchor_descriptors": [],
                        "accurate_layer_coverage_descriptors": [],
                        "accurate_layer_generalization_descriptors": [
                            {"workload_id": "si4_pbe_uspp_small", "display_label": "Generalization label", "software_family": "QE", "flow_family": "QE_SCF", "trait_bucket": "USPP-heavy", "lane": "qe_next_stage_mainline", "gold_required": True, "first_priority_convergence_case": False, "signature_id": "sigB", "property_target": "band_structure", "pseudopotential_family": "USPP", "solver_path_class": "generalized_overlap", "workload_topology": "bulk", "post_scf_extension_level": "shell_only", "projector_pressure": "medium", "nonlocal_pressure": "medium", "generalized_ratio_bucket": "medium", "diag_dominance": "medium", "fft_grid_pressure": "medium", "family": "F1", "diag_policy": "cpu_only", "offload_scope": "single_hotpath", "resident_policy": "fit_first", "partition_strategy": "single_hotpath_partition", "workload_group_id": MODULE.PHASE1_WORKLOAD_GROUP_ID, "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0", "accounting_boundary_id": "scf_shell_convergence_scope_v1", "fairness_policy_id": MODULE.PHASE1_FAIRNESS_POLICY_ID, "power_boundary_id": MODULE.PHASE1_POWER_BOUNDARY_ID, "observability_contract_id": MODULE.PHASE1_OBSERVABILITY_CONTRACT_ID, "algorithm_rewrite_manifest_id": MODULE.PHASE1_REWRITE_MANIFEST_ID, "algorithm_contract_deviation": False, "source_kind": "trace_calibrated_proxy", "calibration_manifest_id": "si4__cal", "gold_case_bundle_id": "si4__gold", "gold_source_path": "/tmp/gold", "reduced_space_contract_id": "qe_reduced_space_validation_contract_v0", "convergence_reference_id": "si4__conv", "numerical_provenance_tag": "calibrated", "gpu_baseline_state": "pending", "gpu_baseline_row_ref": None, "decisive_for_case": False}
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            out = root / "out"
            import sys
            old_argv = sys.argv
            try:
                sys.argv = [
                    "run_systemc_architecture_family_dse_sweep.py",
                    "--output-dir",
                    str(out),
                    "--workloads",
                    "si4_pbe_uspp_small",
                    "--case-pack",
                    str(case_pack),
                    "--case-pack-sections",
                    "stage_a_bringup_descriptors",
                    "--max-design-points",
                    "1",
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            bundle = json.loads((out / "systemc_architecture_family_dse_bootstrap_v0.json").read_text(encoding="utf-8"))
            self.assertEqual(bundle["results"][0]["workload"]["label"], "Stage A label")
            self.assertEqual(bundle["experiment"]["case_pack_summary"]["selected_sections"], ["stage_a_bringup_descriptors"])

    def build_template_bundle(
        self,
        root: Path,
        template_specs: dict[str, tuple[str, str, list[str]]],
    ) -> Any:
        baseline_path = root / "cpu_baseline.json"
        baseline_path.write_text("[]", encoding="utf-8")
        template_dir = root / "templates"
        template_dir.mkdir()
        for template_id, (family, compute_unit, tags) in template_specs.items():
            (template_dir / f"{template_id}.json").write_text(
                json.dumps(
                    self.make_template(
                        template_id,
                        family=family,
                        compute_unit=compute_unit,
                        tags=tags,
                    ),
                    indent=2,
                ),
                encoding="utf-8",
            )
        args = self.make_args(baseline_path)
        args.run_id = None
        args.source_model = "model/qe_band_solver_model"
        args.output_dir = root / "out"
        args.template_driven = True
        args.architecture_template_dir = template_dir
        args.architecture_template_ids = list(template_specs)
        args.design_space_spec = None
        args.emit_projected_configs = True
        args.canonical_only = False
        args.max_design_points = None
        return MODULE.build_bundle(
            args,
            MODULE.utc_now(),
            [MODULE.DEFAULT_WORKLOADS["si4_pbe_uspp_small"]],
            ["F1", "F2", "F3"],
            MODULE.DIAG_POLICIES,
            MODULE.OFFLOAD_SCOPES,
            MODULE.RESIDENT_POLICIES,
            None,
        )

    @staticmethod
    def make_args(baseline_path: Path) -> SimpleNamespace:
        assumptions_path = baseline_path.parent / "proxy_assumptions.json"
        assumptions_path.write_text(
            json.dumps(
                {
                    "schema_version": "qe_fast_layer_proxy_assumption_set_v0",
                    "default_assumption_set_id": "qe_next_stage_phase_v0",
                    "assumption_sets": {
                        "pending_calibration_v0": {
                            "host_control_w": 12.0,
                            "host_assist_w": 16.0,
                            "dma_w": 4.0,
                            "idle_static_w": 2.0,
                            "family_device_power_w": {
                                "F1": {"runtime": 3.0, "datapath": 5.0},
                                "F2": {"runtime": 3.5, "datapath": 6.5},
                                "F3": {"runtime": 4.0, "datapath": 8.0},
                            },
                        },
                        "qe_next_stage_phase_v0": {
                            "host_control_w": 12.0,
                            "host_assist_w": 16.0,
                            "dma_w": 4.0,
                            "idle_static_w": 2.0,
                            "family_device_power_w": {
                                "F1": {"runtime": 3.0, "datapath": 5.0},
                                "F2": {"runtime": 3.5, "datapath": 6.5},
                                "F3": {"runtime": 4.0, "datapath": 8.0},
                            },
                        },
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(
            source_kind="timed_functional_proxy",
            qe_tolerance_schema_id="qe_gold_numerical_tolerance_schema_v0",
            assumption_set_id="qe_next_stage_phase_v0",
            model_max_scf_iters=1,
            auto_match_baseline_iters=True,
            cpu_shell_aggregate_path=baseline_path,
            fast_layer_proxy_assumptions_path=assumptions_path,
            model_bin=Path("/tmp/fake-qe-band-solver-model"),
        )

    @staticmethod
    def make_candidate(*, include_total_ref_cycles: bool = True) -> dict[str, object]:
        run_summary: dict[str, object] = {
            "total_episodes": 4,
            "total_backpressure_ref_cycles": 20,
            "convergence_reason": "mixed_density_converged",
        }
        if include_total_ref_cycles:
            run_summary["total_ref_cycles"] = 1000
        return {
            "run_config": {
                "projector_pressure": "high",
                "nonlocal_pressure": "medium",
                "generalized_ratio_bucket": "medium",
                "diag_dominance": "high",
                "fft_grid_pressure": "medium",
            },
            "final": {
                "total_energy_ry": -11.5,
                "residual_threshold_reached": True,
                "converged": True,
                "scf_iterations": 4,
            },
            "run_summary": run_summary,
            "last_iteration": {
                "confidence_label": "high",
            },
            "iteration_diagnostics": [
                {
                    "spill_active": False,
                    "diag_path": "device_accelerator",
                    "support_grid_mode": "FFT_AUX",
                    "workload_bucket": "large",
                    "band_count": 48,
                    "panel_count": 5,
                    "max_inner_steps": 4,
                    "inner_steps": 1,
                    "max_diag_condition_estimate": 1.57,
                },
                {
                    "spill_active": True,
                    "diag_path": "host_cpu_fallback",
                    "support_grid_mode": "FFT_AUX",
                    "workload_bucket": "large",
                    "band_count": 48,
                    "panel_count": 5,
                    "max_inner_steps": 4,
                    "inner_steps": 2,
                    "max_diag_condition_estimate": 1.57,
                    "cpu_diag_fallback": True,
                },
                {
                    "spill_active": False,
                    "diag_path": "host_cpu_fallback",
                    "support_grid_mode": "FFT_AUX",
                    "workload_bucket": "large",
                    "band_count": 48,
                    "panel_count": 5,
                    "max_inner_steps": 4,
                    "inner_steps": 3,
                    "max_diag_condition_estimate": 1.57,
                },
                {
                    "spill_active": False,
                    "diag_path": "host_cpu_fallback",
                    "support_grid_mode": "FFT_AUX",
                    "workload_bucket": "large",
                    "band_count": 48,
                    "panel_count": 5,
                    "max_inner_steps": 4,
                    "inner_steps": 3,
                    "max_diag_condition_estimate": 1.57,
                },
            ],
            "metrics": {
                "device_busy_ref_cycles": 600,
                "dma_ref_cycles": 200,
                "host_assist_ref_cycles": 100,
                "cpu_fallbacks": 1,
                "resident_reuse_hits": 3,
                "total_data_movement_kib": 512.0,
            },
            "cluster_metrics": {
                "cluster_a": {
                    "cluster_name": "ClusterA",
                    "invocations": 4,
                    "accounted_ref_cycles": 360,
                    "backpressure_ref_cycles": 9,
                    "data_movement_kib": 320.0,
                    "dominant_resource": "CIM_PROJECT_BACKPROJECT_CHAIN",
                },
                "cluster_b": {
                    "cluster_name": "ClusterB",
                    "invocations": 4,
                    "accounted_ref_cycles": 120,
                    "backpressure_ref_cycles": 4,
                    "data_movement_kib": 24.0,
                    "dominant_resource": "ReductionClosureEngine",
                },
                "cluster_c": {
                    "cluster_name": "ClusterC",
                    "invocations": 4,
                    "accounted_ref_cycles": 80,
                    "backpressure_ref_cycles": 3,
                    "data_movement_kib": 8.0,
                    "dominant_resource": "ClusterC.SolverPipeline",
                },
                "cluster_d": {
                    "cluster_name": "ClusterD",
                    "invocations": 4,
                    "accounted_ref_cycles": 40,
                    "backpressure_ref_cycles": 2,
                    "data_movement_kib": 6.0,
                    "dominant_resource": "ClusterD.RefreshWriteback",
                },
            },
            "timing": {
                "wall_time_s": 0.01,
            },
        }

    @staticmethod
    def make_template(
        template_id: str,
        *,
        family: str = "F2",
        compute_unit: str = "cim_array",
        tags: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "template_id": template_id,
            "template_version": "v1",
            "family": family,
            "label": "Unit test architecture template",
            "clusters": [
                {
                    "cluster_id": "cluster_a",
                    "role": "operator_sweep",
                    "compute_unit": compute_unit,
                    "enabled": True,
                    "timing_model": "proxy_formula",
                    "resource_budget": {"dsp_count": 0, "bram_18k_count": 1, "lut_count": 1, "uram_count": 0},
                }
            ],
            "policies": {
                "diag_policy": "device_first_fallback",
                "offload_scope": "balanced",
                "resident_policy": "fit_first",
                "partition_strategy": "operator__build__diag__refresh",
            },
            "dse_metadata": {"risk_level": "low", "tags": tags or []},
            "notes": {"validation_status": "unit validated"},
        }

    @staticmethod
    def load_phase_runner_module():
        phase_runner_path = MODULE_PATH.with_name("run_qe_next_stage_dse_phase.py")
        spec = importlib.util.spec_from_file_location("run_qe_next_stage_dse_phase", phase_runner_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
