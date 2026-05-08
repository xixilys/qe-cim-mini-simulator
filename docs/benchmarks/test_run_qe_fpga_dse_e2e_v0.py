from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("run_qe_fpga_dse_e2e_v0.py")
SPEC = importlib.util.spec_from_file_location("run_qe_fpga_dse_e2e_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


class RunQeFpgaDseE2ETests(unittest.TestCase):
    def stage_c_payload(self, candidate_id: str) -> dict[str, Any]:
        return {
            "schema_version": "qe_dse_qe_equivalent_correctness_report_v0",
            "execution_status": "executed",
            "claim_ceiling": "qe_equivalent_scf_correctness_only",
            "report_id": "stage_c_fixture",
            "candidate_id": candidate_id,
            "workload_id": "si4_pbe_uspp_small",
            "case_id": "si4_pbe_uspp_small",
            "family": "F1",
            "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
            "correctness_status": "pass",
            "qe_equivalent_scf_claim": True,
            "compare_report": {
                "schema_name": "qe_gold_numerical_tolerance_schema_v0",
                "schema_version": "2026-04-13",
                "overall_pass": True,
                "summary": {"status": "pass", "failed_required_fields": []},
            },
            "evidence_refs": {},
        }

    def stage_d_payload(self, candidate_id: str, stage_c_ref: Path) -> dict[str, Any]:
        return {
            "schema_version": "qe_dse_fpga_asic_implementation_evidence_v0",
            "execution_status": "external_evidence_referenced",
            "evidence_id": "stage_d_projection_fixture",
            "candidate_id": candidate_id,
            "implementation_target_class": "fpga",
            "evidence_kind": "implementation_projection",
            "evidence_status": "partial",
            "claim_ceiling": "implementation_evidence_only",
            "artifact_refs": {"projection_note": "artifacts/implementation/projection_note.json"},
            "metrics": {"projected_latency_cycles": 42},
            "correctness_dependency": {
                "qe_equivalent_scf_claim": True,
                "qe_correctness_report_ref": str(stage_c_ref),
            },
            "final_public_family_winner": None,
            "public_winner_claim": False,
            "production_release_ready": False,
        }

    def systemc_cycle_payload(self, candidate_id: str) -> dict[str, Any]:
        return {
            "schema_version": "qe_systemc_cycle_accounted_evidence_v0",
            "candidate_id": candidate_id,
            "workload_id": "si4_pbe_uspp_small",
            "evidence_tier": "systemc-cycle-accounted",
            "template_config_hash": "sha256:template-fixture",
            "per_stage_cycles": {"operator_sweep": 120, "reduced_build": 30},
            "per_component_cycles": {"dma": 10, "compute": 140},
            "total_cycles": 150,
            "model_support_status": "generated_config_supported",
            "calibration_refs": ["fixture://calibration"],
            "artifact_refs": {"cycle_table": "cycle_table.json"},
            "artifact_hashes": {"cycle_table_sha256": "sha256:cycle-table"},
            "non_claims": [
                "systemc_cycle_accounted_is_not_rtl_cycle_accurate",
                "not_board_or_asic_measured",
            ],
        }

    def materialized_systemc_cycle_payload(self, candidate_id: str) -> dict[str, Any]:
        return {
            "schema_version": "systemc_cycle_accounted_evidence_v0",
            "candidate_id": candidate_id,
            "workload_id": "si4_pbe_uspp_small",
            "evidence_tier_label": "systemc-cycle-accounted",
            "claim_label": "systemc-cycle-accounted",
            "template_config_hash": "sha256:template-fixture",
            "cycle_accounting": {
                "total_cycles": 150,
                "per_stage_cycle_table": [
                    {"stage_id": "cluster_a", "cycles": 120, "included_in_total": True}
                ],
                "per_component_cycle_table": [
                    {"component_id": "dma", "cycles": 10}
                ],
            },
            "model_support_status": {"status": "systemc_result_available"},
            "calibration_refs": [],
            "artifact_refs": {"systemc_candidate_result": "candidate.systemc.json"},
            "artifact_hashes": {"systemc_candidate_result": {"sha256": "sha256:candidate"}},
            "non_claims": [
                "systemc_cycle_accounting_only",
                "not_rtl_cycle_accurate",
                "not_final_best_architecture_claim",
            ],
        }

    def write_candidate_run(self, root: Path, candidate_id: str, family: str) -> dict[str, Any]:
        frontend_dir = root / "frontend_dse"
        request_dir = frontend_dir / "backend_execution_requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        request_path = request_dir / f"{candidate_id}.json"
        request_path.write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "candidate_identity": {
                        "candidate_id": candidate_id,
                        "architecture_template_id": f"template_{family}",
                        "design_axes": {"family": family},
                    },
                    "workload_identity": {"workload_id": "si4_pbe_uspp_small"},
                    "domain_extension": {
                        "qe": {
                            "case_id": "si4_pbe_uspp_small",
                            "qe_equivalent_scf_claim": False,
                        }
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        candidate_dir = root / "candidate_runs" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        systemc_report = candidate_dir / "systemc_timed_functional_report.json"
        systemc_payload = {
            "candidate_id": candidate_id,
            "execution_status": "executed",
            "backend_class": "systemc_timed_functional_proxy",
            "claim_ceiling": "systemc_proxy_only",
            "metrics": {"cycle_proxy": 100},
        }
        systemc_report.write_text(json.dumps(systemc_payload) + "\n", encoding="utf-8")
        b4_report = candidate_dir / "gem5_systemc_timed_proxy_report.json"
        b4_payload = {
            "candidate_id": candidate_id,
            "execution_status": "executed",
            "backend_class": "gem5_systemc_timed_proxy",
            "claim_ceiling": "gem5_systemc_timed_proxy_only",
            "metrics": {"cycle_proxy": 200},
        }
        b4_report.write_text(json.dumps(b4_payload) + "\n", encoding="utf-8")
        return {
            "candidate_id": candidate_id,
            "screening_rank": 1 if family == "F3" else 2,
            "stage_b0_request": request_path,
            "candidate_dir": candidate_dir,
            "systemc_report": systemc_report,
            "systemc_payload": systemc_payload,
            "gem5_b4_report": b4_report,
            "gem5_b4_payload": b4_payload,
        }

    def write_stage_c_d_pair(self, root: Path, candidate_id: str) -> tuple[Path, Path]:
        stage_c_report = root / f"{candidate_id}.stage_c.json"
        stage_d_evidence = root / f"{candidate_id}.stage_d.json"
        stage_c_report.write_text(
            json.dumps(self.stage_c_payload(candidate_id), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        stage_d_evidence.write_text(
            json.dumps(self.stage_d_payload(candidate_id, stage_c_report), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return stage_c_report, stage_d_evidence

    def test_stage_b0_request_selection_prefers_f2_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            request_dir = root / "backend_execution_requests"
            request_dir.mkdir(parents=True)
            descriptors = []
            for family in ("F1", "F2", "F3"):
                name = f"{family}.json"
                request = request_dir / name
                request.write_text(
                    json.dumps(
                        {
                            "candidate_identity": {
                                "architecture_template_id": family,
                                "design_axes": {"family": family},
                            }
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                descriptors.append({"backend_execution_request_ref": f"backend_execution_requests/{name}"})
            (root / "stage_b0_descriptor_manifest_v0.json").write_text(
                json.dumps({"descriptors": descriptors}) + "\n",
                encoding="utf-8",
            )

            selected = MODULE_ANY._first_stage_b0_request(root, preferred_family="F2")

            self.assertEqual(selected.name, "F2.json")

    def test_selected_stage_b0_requests_follow_screening_rank_not_manifest_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            request_dir = root / "backend_execution_requests"
            request_dir.mkdir(parents=True)
            descriptors = []
            for family in ("F1", "F2", "F3"):
                candidate_id = f"candidate_{family}"
                request = request_dir / f"{candidate_id}.json"
                request.write_text(
                    json.dumps(
                        {
                            "candidate_id": candidate_id,
                            "candidate_identity": {
                                "candidate_id": candidate_id,
                                "architecture_template_id": family,
                                "design_axes": {"family": family},
                            },
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                descriptors.append(
                    {
                        "candidate_id": candidate_id,
                        "backend_execution_request_ref": f"backend_execution_requests/{candidate_id}.json",
                    }
                )
            (root / "stage_b0_descriptor_manifest_v0.json").write_text(
                json.dumps({"descriptors": descriptors}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (root / "multi_fidelity_plan_v0.json").write_text(
                json.dumps(
                    {
                        "selected_candidates": [
                            {"candidate_id": "candidate_F2", "screening_rank": 2},
                            {"candidate_id": "candidate_F3", "screening_rank": 1},
                        ]
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            selected = MODULE_ANY._selected_stage_b0_requests(
                root,
                top_k=1,
                preferred_family="F2",
            )

            self.assertEqual([path.stem for path in selected], ["candidate_F3"])

    def test_require_real_gem5_smoke_rejects_refused_report(self) -> None:
        with self.assertRaisesRegex(MODULE_ANY.E2EError, "execution_status='refused'"):
            MODULE_ANY._enforce_real_gem5_smoke_gate(
                {
                    "execution_status": "refused",
                    "claim_ceiling": "gem5_systemc_smoke_only",
                    "backend_class": "gem5_systemc_smoke",
                    "artifact_refs": {"gem5_executable": "missing-gem5.opt"},
                    "correctness_gate": {"workload_equivalent_claim": False},
                },
                Path("report.json"),
            )

    def test_require_real_gem5_smoke_rejects_legacy_b3_conversion(self) -> None:
        with self.assertRaisesRegex(MODULE_ANY.E2EError, "legacy_b3_conversion_used"):
            MODULE_ANY._enforce_real_gem5_smoke_gate(
                {
                    "execution_status": "executed",
                    "claim_ceiling": "gem5_systemc_smoke_only",
                    "backend_class": "gem5_systemc_smoke",
                    "artifact_refs": {"legacy_b3_smoke_report": "legacy.json"},
                    "control_path": {"completion_source": "smoke_immediate_complete"},
                    "correctness_gate": {"workload_equivalent_claim": False},
                },
                Path("report.json"),
            )

    def test_require_real_gem5_smoke_accepts_real_qe_gem5_smoke_envelope(self) -> None:
        MODULE_ANY._enforce_real_gem5_smoke_gate(
            {
                "execution_status": "executed",
                "claim_ceiling": "gem5_systemc_smoke_only",
                "backend_class": "gem5_systemc_smoke",
                "artifact_refs": {"artifact_subtype": "real_qe_gem5_se_scf_smoke_v0"},
                "control_path": {"completion_source": "gem5_se_real_pw_stdout_parser"},
                "correctness_gate": {
                    "workload_equivalent_claim": False,
                    "qe_equivalent_scf_claim": False,
                },
            },
            Path("report.json"),
        )

    def test_require_real_gem5_b4_rejects_refused_report(self) -> None:
        with self.assertRaisesRegex(MODULE_ANY.E2EError, "execution_status='refused'"):
            MODULE_ANY._enforce_real_gem5_b4_gate(
                {
                    "execution_status": "refused",
                    "claim_ceiling": "gem5_systemc_timed_proxy_only",
                    "backend_class": "gem5_systemc_timed_proxy",
                    "environment": {},
                    "artifact_refs": {},
                    "control_path": {},
                    "metrics": {},
                    "correctness_gate": {"workload_equivalent_claim": False},
                },
                Path("report.json"),
                expected_bridge=Path("libbridge.so"),
            )

    def test_require_real_gem5_b4_accepts_bridge_provenance_and_metrics(self) -> None:
        bridge = Path("libbridge.so")
        sidecar = Path("timing_sidecar.json")
        MODULE_ANY._enforce_real_gem5_b4_gate(
            {
                "execution_status": "executed",
                "claim_ceiling": "gem5_systemc_timed_proxy_only",
                "backend_class": "gem5_systemc_timed_proxy",
                "environment": {
                    "fpga_execution_mode": "real_bridge",
                    "real_systemc_target": "1",
                    "systemc_bridge": str(bridge),
                    "timing_sidecar": str(sidecar),
                },
                "artifact_refs": {"systemc_bridge": str(bridge), "timing_sidecar": str(sidecar)},
                "control_path": {
                    "mmio_read_count": 0,
                    "mmio_write_count": 0,
                    "systemc_start_tick": 0,
                    "systemc_end_tick": 100,
                    "completion_tick": 100,
                    "dma_start_tick": 0,
                    "dma_end_tick": 100,
                },
                "metrics": {
                    "cycle_source": "timing_sidecar_projection",
                    "cycle_proxy_source": "timing_sidecar_projection",
                    "event_timed_device_activity_observed": False,
                    "candidate_device_event_delta_ticks": None,
                    "host_control_mmio_read_count": 0,
                    "host_control_mmio_write_count": 0,
                    "systemc_datapath_device_busy_ns": 100,
                    "successful_dma_transfer_bytes": 0,
                    "dma_warning_count": 0,
                },
                "correctness_gate": {
                    "workload_equivalent_claim": False,
                    "domain_equivalence_claim": False,
                },
            },
            Path("report.json"),
            expected_bridge=bridge,
        )

    def test_require_real_gem5_b4_normalizes_bridge_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bridge = root / "lib" / "libbridge.so"
            sidecar = root / "timing" / "timing_sidecar.json"
            bridge.parent.mkdir(parents=True)
            sidecar.parent.mkdir(parents=True)
            bridge.write_text("bridge\n", encoding="utf-8")
            sidecar.write_text("{}\n", encoding="utf-8")
            equivalent_bridge = bridge.parent / ".." / "lib" / bridge.name
            equivalent_sidecar = sidecar.parent / ".." / "timing" / sidecar.name

            MODULE_ANY._enforce_real_gem5_b4_gate(
                {
                    "execution_status": "executed",
                    "claim_ceiling": "gem5_systemc_timed_proxy_only",
                    "backend_class": "gem5_systemc_timed_proxy",
                    "environment": {
                        "fpga_execution_mode": "real_bridge",
                        "real_systemc_target": "1",
                        "systemc_bridge": str(equivalent_bridge),
                        "timing_sidecar": str(equivalent_sidecar),
                    },
                    "artifact_refs": {
                        "systemc_bridge": str(equivalent_bridge),
                        "timing_sidecar": str(equivalent_sidecar),
                    },
                    "control_path": {
                        "mmio_read_count": 0,
                        "mmio_write_count": 0,
                        "systemc_start_tick": 0,
                        "systemc_end_tick": 100,
                        "completion_tick": 100,
                        "dma_start_tick": 0,
                        "dma_end_tick": 100,
                    },
                    "metrics": {
                        "cycle_source": "timing_sidecar_projection",
                        "cycle_proxy_source": "timing_sidecar_projection",
                        "event_timed_device_activity_observed": False,
                        "candidate_device_event_delta_ticks": None,
                        "host_control_mmio_read_count": 0,
                        "host_control_mmio_write_count": 0,
                        "systemc_datapath_device_busy_ns": 100,
                        "successful_dma_transfer_bytes": 0,
                        "dma_warning_count": 0,
                    },
                    "correctness_gate": {
                        "workload_equivalent_claim": False,
                        "domain_equivalence_claim": False,
                    },
                },
                Path("report.json"),
                expected_bridge=bridge,
            )

    def test_require_real_gem5_b4_rejects_event_timed_claim_without_mmio_activity(self) -> None:
        bridge = Path("libbridge.so")
        with self.assertRaisesRegex(MODULE_ANY.E2EError, "event_timed_cycle_source_without_nonzero_mmio_activity"):
            MODULE_ANY._enforce_real_gem5_b4_gate(
                {
                    "execution_status": "executed",
                    "claim_ceiling": "gem5_systemc_timed_proxy_only",
                    "backend_class": "gem5_systemc_timed_proxy",
                    "environment": {
                        "fpga_execution_mode": "real_bridge",
                        "real_systemc_target": "1",
                        "systemc_bridge": str(bridge),
                        "timing_sidecar": "timing_sidecar.json",
                    },
                    "artifact_refs": {
                        "systemc_bridge": str(bridge),
                        "timing_sidecar": "timing_sidecar.json",
                    },
                    "control_path": {
                        "mmio_read_count": 0,
                        "mmio_write_count": 0,
                        "systemc_start_tick": 100,
                        "systemc_end_tick": 200,
                        "completion_tick": 220,
                        "dma_start_tick": 100,
                        "dma_end_tick": 200,
                    },
                    "metrics": {
                        "cycle_source": "gem5_event_timed_device_observed",
                        "event_timed_device_activity_observed": True,
                        "candidate_device_event_delta_ticks": 120,
                        "host_control_mmio_read_count": 0,
                        "host_control_mmio_write_count": 0,
                        "systemc_datapath_device_busy_ns": 100,
                        "successful_dma_transfer_bytes": 0,
                        "dma_warning_count": 0,
                    },
                    "correctness_gate": {
                        "workload_equivalent_claim": False,
                        "domain_equivalence_claim": False,
                    },
                },
                Path("report.json"),
                expected_bridge=bridge,
            )

    def test_b4_request_materializes_repo_and_stage_b0_file_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            frontend_dir = root / "frontend_dse"
            request_dir = frontend_dir / "backend_execution_requests"
            request_dir.mkdir(parents=True)
            request_payload = {
                "schema_version": "backend_execution_request_v0",
                "requested_fidelity": "B2",
                "execution_mode": "systemc_timed_functional",
                "claim_ceiling": "descriptor_only",
                "candidate_id": "candidate_F2",
                "backend_capability_profile": {
                    "claim_ceiling": "descriptor_only",
                    "supports_gem5_timed_proxy": False,
                    "supports_real_bridge": False,
                },
                "input_refs": {
                    "application_graph": "application_graphs/workload.json",
                    "architecture_template": "architecture_templates/template_F2.json",
                    "mapping": "mappings/mapping_F2.json",
                    "architecture_config": "architecture_configs/F2.json",
                    "systemc_config": "systemc_configs/F2.json",
                    "proxy_runtime": None,
                    "gem5_max_ticks": "1000",
                },
            }
            stage_b0_request = request_dir / "candidate_F2.json"
            stage_b0_request.write_text(
                json.dumps(request_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for key, payload in (
                (
                    "architecture_config",
                    {
                        "clusters": [
                            {
                                "cluster_id": "operator_sweep",
                                "type": "operator_sweep",
                                "on_chip_buffer_kb": 256,
                                "pipeline_depth": 4,
                                "max_concurrent_ops": 8,
                            }
                        ]
                    },
                ),
                ("systemc_config", {"candidate_id": "candidate_F2", "family": "F2"}),
            ):
                ref_path = frontend_dir / request_payload["input_refs"][key]
                ref_path.parent.mkdir(parents=True, exist_ok=True)
                ref_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            output_dir = root / "e2e"

            b4_request = MODULE_ANY._write_b4_request_from_stage_b0(
                stage_b0_request,
                output_dir,
                gem5_executable=Path("gem5_integration/gem5/build/X86/gem5.opt"),
                gem5_config=Path("gem5_integration/configs/fpga/simple_fpga_test.py"),
                systemc_bridge=Path("gem5_integration/systemc_model/build/libgem5_systemc_bridge.a"),
            )

            generated = json.loads(b4_request.read_text(encoding="utf-8"))
            original = json.loads(stage_b0_request.read_text(encoding="utf-8"))
            input_refs = generated["input_refs"]
            self.assertEqual(original, request_payload)
            self.assertEqual(generated["requested_fidelity"], "B4")
            self.assertEqual(generated["execution_mode"], "gem5_systemc_timed_proxy")
            self.assertEqual(
                input_refs["gem5_executable"],
                str((MODULE_ANY.REPO_ROOT / "gem5_integration/gem5/build/X86/gem5.opt").resolve(strict=False)),
            )
            self.assertEqual(
                input_refs["gem5_config"],
                str((MODULE_ANY.REPO_ROOT / "gem5_integration/configs/fpga/simple_fpga_test.py").resolve(strict=False)),
            )
            self.assertEqual(
                input_refs["systemc_bridge_library"],
                str((MODULE_ANY.REPO_ROOT / "gem5_integration/systemc_model/build/libgem5_systemc_bridge.a").resolve(strict=False)),
            )
            for key in (
                "application_graph",
                "architecture_template",
                "mapping",
                "architecture_config",
                "systemc_config",
            ):
                self.assertEqual(input_refs[key], str((frontend_dir / request_payload["input_refs"][key]).resolve(strict=False)))
            self.assertIsNone(input_refs["proxy_runtime"])
            self.assertEqual(input_refs["gem5_max_ticks"], "1000")
            self.assertEqual(b4_request.name, "backend_execution_request.json")
            self.assertTrue(Path(input_refs["timing_sidecar"]).exists())
            timing_sidecar = json.loads(Path(input_refs["timing_sidecar"]).read_text(encoding="utf-8"))
            self.assertEqual(timing_sidecar["metrics"]["cycle_source"], "timing_sidecar_projection")
            self.assertFalse(timing_sidecar["metrics"]["event_timed_device_activity_observed"])
            self.assertTrue(Path(input_refs["candidate_timing_profile"]).exists())
            self.assertEqual(input_refs["strict_b4_runtime_timing_input"], input_refs["candidate_timing_profile"])
            candidate_profile = json.loads(Path(input_refs["candidate_timing_profile"]).read_text(encoding="utf-8"))
            self.assertEqual(candidate_profile["runtime_timing_role"], "strict_b4_runtime_profile_input")
            self.assertGreater(candidate_profile["event_schedule"]["candidate_event_delta_ticks"], 0)
            self.assertEqual(
                generated["backend_capability_profile"]["supports_gem5_event_timed_device_proxy"],
                True,
            )
            self.assertTrue(Path(input_refs["generated_systemc_header"]).exists())
            self.assertTrue(Path(input_refs["generated_systemc_source"]).exists())
            generated_source = Path(input_refs["generated_systemc_source"]).read_text(encoding="utf-8")
            self.assertIn("candidate_timing_profile", generated_source)
            self.assertIn("candidate_event_delta_ticks", generated_source)

    def test_reranked_results_split_bounded_rank_from_final_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate_runs = [
                {
                    "candidate_id": "candidate_A",
                    "screening_rank": 1,
                    "systemc_payload": {"metrics": {"cycle_proxy": 1000}},
                    "gem5_b4_payload": {
                        "metrics": {
                            "cycle_proxy": 100,
                            "cycle_source": "timing_sidecar_projection",
                            "event_timed_device_activity_observed": False,
                            "candidate_device_event_delta_ticks": None,
                        },
                    },
                },
                {
                    "candidate_id": "candidate_B",
                    "screening_rank": 2,
                    "systemc_payload": {"metrics": {"cycle_proxy": 1100}},
                    "gem5_b4_payload": {
                        "metrics": {
                            "cycle_proxy": 200,
                            "cycle_source": "gem5_event_timed_device_observed",
                            "event_timed_device_activity_observed": True,
                            "candidate_device_event_delta_ticks": 200,
                        },
                    },
                },
            ]
            claim_matrix = {
                "rows": [
                    {
                        "candidate_id": "candidate_A",
                        "evidence_tier": "projection-screened",
                        "blockers": [],
                        "same_candidate_evidence_only": True,
                        "final_observed_conclusion_ceiling": "qe_equivalent_scf_correctness_plus_hls_synthesis_only",
                    },
                    {
                        "candidate_id": "candidate_B",
                        "evidence_tier": "final-best-eligible",
                        "blockers": [],
                        "same_candidate_evidence_only": True,
                        "final_observed_conclusion_ceiling": "qe_equivalent_scf_correctness_plus_hls_synthesis_only",
                    },
                ]
            }

            payload = MODULE_ANY._write_reranked_results(
                root / "reranked.json",
                candidate_runs,
                claim_matrix=claim_matrix,
            )

            self.assertEqual(payload["bounded_recommendation"]["candidate_id"], "candidate_A")
            self.assertEqual(payload["final_recommendation"]["candidate_id"], "candidate_B")
            self.assertEqual(
                payload["final_recommendation"]["recommendation_scope"],
                "same_candidate_stage_c_d_strict_b4_plus_systemc_cycle_accounted",
            )
            self.assertEqual(payload["final_recommendation"]["evidence_tier"], "final-best-eligible")
            row_by_candidate = {row["candidate_id"]: row for row in payload["rows"]}
            self.assertFalse(row_by_candidate["candidate_A"]["eligible_for_final_recommendation"])
            self.assertTrue(row_by_candidate["candidate_B"]["eligible_for_final_recommendation"])

    def test_systemc_b4_policy_reranked_results_treats_stage_d_as_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate_runs = [
                {
                    "candidate_id": "candidate_A",
                    "screening_rank": 1,
                    "systemc_payload": {"metrics": {"cycle_proxy": 1000}},
                    "gem5_b4_payload": {
                        "metrics": {
                            "cycle_proxy": 100,
                            "cycle_source": "gem5_event_timed_device_observed",
                            "event_timed_device_activity_observed": True,
                            "candidate_device_event_delta_ticks": 100,
                            "host_control_mmio_read_count": 3,
                            "host_control_mmio_write_count": 1,
                        },
                    },
                }
            ]
            claim_matrix = {
                "rows": [
                    {
                        "candidate_id": "candidate_A",
                        "evidence_tier": "final-best-eligible",
                        "blockers": ["missing_stage_d_implementation_evidence"],
                        "same_candidate_evidence_only": True,
                        "systemc_cycle_accounted_evidence_ref": "candidate_A.systemc_cycle.json",
                        "final_observed_conclusion_ceiling": "qe_equivalent_scf_correctness_only",
                    }
                ]
            }

            payload = MODULE_ANY._write_reranked_results(
                root / "reranked.json",
                candidate_runs,
                claim_matrix=claim_matrix,
                policy=MODULE_ANY.final_best_policy.systemc_b4_minimum_policy(),
            )

            self.assertEqual(payload["final_recommendation"]["candidate_id"], "candidate_A")
            self.assertEqual(
                payload["final_recommendation"]["recommendation_scope"],
                "same_candidate_stage_c_strict_b4_plus_systemc_cycle_accounted",
            )
            self.assertEqual(payload["final_recommendation"]["policy_id"], "qe_fpga_final_best_policy_systemc_b4_minimum_v0")
            self.assertFalse(payload["final_recommendation"]["stage_d_required_for_final_best"])
            self.assertEqual(payload["final_recommendation"]["systemc_cycle_evidence_ref"], "candidate_A.systemc_cycle.json")
            self.assertEqual(payload["final_recommendation_gate"]["requires_no_stage_c_d_blockers"], False)
            self.assertEqual(payload["rows"][0]["blockers"], [])

    def test_top_k_closure_rows_carry_release_claim_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            b4_report = root / "candidate_A.b4.json"
            b4_report.write_text("{}\n", encoding="utf-8")
            candidate_runs = [
                {
                    "candidate_id": "candidate_A",
                    "screening_rank": 1,
                    "stage_b0_request": root / "candidate_A.stage_b0.json",
                    "gem5_b4_report": b4_report,
                }
            ]
            claim_matrix = {
                "rows": [
                    {
                        "candidate_id": "candidate_A",
                        "evidence_tier": "final-best-eligible",
                        "blockers": ["missing_stage_d_implementation_evidence"],
                        "same_candidate_evidence_only": True,
                        "stage_c_report_ref": "candidate_A.stage_c.json",
                        "systemc_cycle_accounted_evidence_ref": "candidate_A.systemc_cycle.json",
                        "systemc_cycle_accounted": {"report_sha256": "abc123"},
                    }
                ]
            }

            payload = MODULE_ANY._top_k_closure_status(
                candidate_runs,
                claim_matrix,
                policy=MODULE_ANY.final_best_policy.systemc_b4_minimum_policy(),
            )

            row = payload["queue"][0]
            self.assertEqual(row["policy_id"], "qe_fpga_final_best_policy_systemc_b4_minimum_v0")
            self.assertFalse(row["stage_d_required_for_final_best"])
            self.assertEqual(row["stage_c_report_ref"], "candidate_A.stage_c.json")
            self.assertEqual(row["strict_b4_report_ref"], str(b4_report))
            self.assertEqual(row["systemc_cycle_evidence_ref"], "candidate_A.systemc_cycle.json")

    def test_claim_status_matrix_writer_links_stage_c_d_and_backend_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            frontend_dir = root / "frontend_dse"
            request_dir = frontend_dir / "backend_execution_requests"
            request_dir.mkdir(parents=True)
            candidate_id = (
                "si4_pbe_uspp_small__F1__cpu_only__single_hotpath__fit_first__"
                "single_hotpath_partition"
            )
            stage_b0_request = request_dir / f"{candidate_id}.json"
            stage_b0_request.write_text(
                json.dumps(
                    {
                        "candidate_id": candidate_id,
                        "candidate_identity": {
                            "candidate_id": candidate_id,
                            "architecture_template_id": "template_F1_stage_a",
                            "design_axes": {"family": "F1"},
                        },
                        "domain_extension": {
                            "qe": {
                                "case_id": "si4_pbe_uspp_small",
                                "qe_equivalent_scf_claim": False,
                            }
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            systemc_report = root / "systemc_report.json"
            stage_c_report = root / "stage_c.json"
            stage_d_evidence = root / "stage_d.json"
            systemc_payload = {
                "candidate_id": candidate_id,
                "execution_status": "executed",
                "backend_class": "systemc_timed_functional_proxy",
                "claim_ceiling": "systemc_proxy_only",
                "metrics": {"cycle_proxy": 100},
            }
            systemc_report.write_text(json.dumps(systemc_payload) + "\n", encoding="utf-8")
            stage_c_report.write_text(
                json.dumps(self.stage_c_payload(candidate_id), indent=2) + "\n",
                encoding="utf-8",
            )
            stage_d_evidence.write_text(
                json.dumps(self.stage_d_payload(candidate_id, stage_c_report), indent=2) + "\n",
                encoding="utf-8",
            )

            refs = MODULE_ANY._write_claim_ceiling_status_matrix(
                output_dir=root,
                stage_b0_request_path=stage_b0_request,
                systemc_report=systemc_report,
                systemc_payload=systemc_payload,
                qe_correctness_report=stage_c_report,
                implementation_evidence=stage_d_evidence,
            )

            matrix = json.loads(refs["matrix"].read_text(encoding="utf-8"))
            row = matrix["rows"][0]
            self.assertEqual(row["candidate_id"], candidate_id)
            self.assertEqual(row["family"], "F1")
            self.assertEqual(row["workload_id"], "si4_pbe_uspp_small")
            self.assertEqual(row["b2"]["claim_ceiling"], "systemc_proxy_only")
            self.assertEqual(
                row["final_observed_conclusion_ceiling"],
                "qe_equivalent_scf_correctness_plus_partial_implementation_projection_only",
            )
            self.assertIn("not an adjudicator permission matrix", refs["markdown"].read_text(encoding="utf-8"))

    def test_claim_status_matrix_for_runs_keeps_topk_b4_blocked_without_stage_c_d(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runs = [
                self.write_candidate_run(root, "candidate_F3", "F3"),
                self.write_candidate_run(root, "candidate_F2", "F2"),
            ]

            refs = MODULE_ANY._write_claim_ceiling_status_matrix_for_runs(
                output_dir=root,
                candidate_runs=runs,
            )

            matrix = json.loads(refs["matrix"].read_text(encoding="utf-8"))
            self.assertEqual(matrix["row_count"], 2)
            for row in matrix["rows"]:
                with self.subTest(candidate=row["candidate_id"]):
                    self.assertEqual(row["final_observed_conclusion_ceiling"], "gem5_systemc_timed_proxy_only")
                    self.assertIn("missing_stage_c_qe_correctness_report", row["blockers"])
                    self.assertIn("missing_stage_d_implementation_evidence", row["blockers"])
                    self.assertIn("missing_systemc_cycle_accounted_evidence", row["blockers"])
                    self.assertEqual(row["evidence_tier"], "projection-screened")
                    self.assertTrue(row["same_candidate_evidence_only"])

    def test_claim_status_matrix_for_runs_joins_systemc_cycle_evidence_by_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runs = [
                self.write_candidate_run(root, "candidate_F3", "F3"),
                self.write_candidate_run(root, "candidate_F2", "F2"),
            ]
            systemc_cycle_f3 = root / "candidate_F3.systemc_cycle.json"
            systemc_cycle_f3.write_text(
                json.dumps(self.systemc_cycle_payload("candidate_F3"), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            refs = MODULE_ANY._write_claim_ceiling_status_matrix_for_runs(
                output_dir=root,
                candidate_runs=runs,
                systemc_cycle_evidence_for={"candidate_F3": systemc_cycle_f3},
            )

            rows = {
                row["candidate_id"]: row
                for row in json.loads(refs["matrix"].read_text(encoding="utf-8"))["rows"]
            }
            self.assertEqual(rows["candidate_F3"]["systemc_cycle_accounted_evidence_ref"], str(systemc_cycle_f3))
            self.assertTrue(rows["candidate_F3"]["systemc_cycle_accounted"]["valid"])
            self.assertEqual(rows["candidate_F3"]["candidate_alignment"]["systemc_cycle_candidate_id"], "candidate_F3")
            self.assertEqual(rows["candidate_F3"]["evidence_tier"], "systemc-cycle-accounted")
            self.assertNotIn("missing_systemc_cycle_accounted_evidence", rows["candidate_F3"]["blockers"])
            self.assertEqual(rows["candidate_F2"]["evidence_tier"], "projection-screened")
            self.assertIn("missing_systemc_cycle_accounted_evidence", rows["candidate_F2"]["blockers"])

    def test_claim_status_matrix_for_runs_accepts_materialized_systemc_cycle_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runs = [self.write_candidate_run(root, "candidate_F3", "F3")]
            systemc_cycle = root / "candidate_F3.materialized_systemc_cycle.json"
            systemc_cycle.write_text(
                json.dumps(self.materialized_systemc_cycle_payload("candidate_F3"), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            refs = MODULE_ANY._write_claim_ceiling_status_matrix_for_runs(
                output_dir=root,
                candidate_runs=runs,
                systemc_cycle_evidence_for={"candidate_F3": systemc_cycle},
            )

            row = json.loads(refs["matrix"].read_text(encoding="utf-8"))["rows"][0]
            self.assertTrue(row["systemc_cycle_accounted"]["valid"])
            self.assertEqual(row["systemc_cycle_accounted"]["evidence_tier"], "systemc-cycle-accounted")
            self.assertEqual(row["systemc_cycle_accounted"]["total_cycles"], 150)
            self.assertNotIn("missing_systemc_cycle_accounted_evidence", row["blockers"])

    def test_backend_report_collection_keeps_systemc_cycle_out_of_backend_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run = self.write_candidate_run(root, "candidate_F3", "F3")
            cycle_path = root / "candidate_F3.materialized_systemc_cycle.json"
            cycle_payload = self.materialized_systemc_cycle_payload("candidate_F3")
            cycle_path.write_text(json.dumps(cycle_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            run["systemc_cycle_accounted_evidence"] = cycle_path
            run["systemc_cycle_accounted_payload"] = cycle_payload

            output = root / "backend_report_collection_v0.json"
            payload = MODULE_ANY._write_backend_report_collection(
                output,
                [run],
                generated_at_utc="2026-05-01T00:00:00Z",
            )

            self.assertEqual(payload["report_count"], 2)
            self.assertEqual(payload["systemc_cycle_accounted_report_count"], 1)
            self.assertTrue(all("backend_class" in report for report in payload["reports"]))
            self.assertIn("systemc_cycle_accounted", payload["candidate_reports"]["candidate_F3"])
            self.assertNotIn(cycle_payload, payload["reports"])

    def test_claim_status_matrix_for_runs_rejects_systemc_cycle_candidate_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runs = [self.write_candidate_run(root, "candidate_F3", "F3")]
            mismatched = root / "candidate_F2.systemc_cycle.json"
            mismatched.write_text(
                json.dumps(self.systemc_cycle_payload("candidate_F2"), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(MODULE_ANY.E2EError, "candidate_id mismatch"):
                MODULE_ANY._write_claim_ceiling_status_matrix_for_runs(
                    output_dir=root,
                    candidate_runs=runs,
                    systemc_cycle_evidence_for={"candidate_F3": mismatched},
                )

    def test_claim_status_matrix_for_runs_links_partial_candidate_stage_c_d_only_to_matching_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runs = [
                self.write_candidate_run(root, "candidate_F3", "F3"),
                self.write_candidate_run(root, "candidate_F2", "F2"),
            ]
            stage_c_f3, stage_d_f3 = self.write_stage_c_d_pair(root, "candidate_F3")

            refs = MODULE_ANY._write_claim_ceiling_status_matrix_for_runs(
                output_dir=root,
                candidate_runs=runs,
                qe_correctness_report_for={"candidate_F3": stage_c_f3},
                implementation_evidence_for={"candidate_F3": stage_d_f3},
            )

            rows = {
                row["candidate_id"]: row
                for row in json.loads(refs["matrix"].read_text(encoding="utf-8"))["rows"]
            }
            self.assertEqual(rows["candidate_F3"]["stage_c_report_ref"], str(stage_c_f3))
            self.assertEqual(rows["candidate_F3"]["stage_d_report_ref"], str(stage_d_f3))
            self.assertNotIn("missing_stage_c_qe_correctness_report", rows["candidate_F3"]["blockers"])
            self.assertNotIn("missing_stage_d_implementation_evidence", rows["candidate_F3"]["blockers"])
            self.assertEqual(
                rows["candidate_F3"]["final_observed_conclusion_ceiling"],
                "qe_equivalent_scf_correctness_plus_partial_implementation_projection_only",
            )
            self.assertIsNone(rows["candidate_F2"]["stage_c_report_ref"])
            self.assertIsNone(rows["candidate_F2"]["stage_d_report_ref"])
            self.assertIn("missing_stage_c_qe_correctness_report", rows["candidate_F2"]["blockers"])
            self.assertIn("missing_stage_d_implementation_evidence", rows["candidate_F2"]["blockers"])
            self.assertTrue(rows["candidate_F2"]["same_candidate_evidence_only"])

    def test_claim_status_matrix_for_runs_links_full_candidate_stage_c_d_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runs = [
                self.write_candidate_run(root, "candidate_F3", "F3"),
                self.write_candidate_run(root, "candidate_F2", "F2"),
            ]
            stage_c_f3, stage_d_f3 = self.write_stage_c_d_pair(root, "candidate_F3")
            stage_c_f2, stage_d_f2 = self.write_stage_c_d_pair(root, "candidate_F2")

            refs = MODULE_ANY._write_claim_ceiling_status_matrix_for_runs(
                output_dir=root,
                candidate_runs=runs,
                qe_correctness_report_for={
                    "candidate_F3": stage_c_f3,
                    "candidate_F2": stage_c_f2,
                },
                implementation_evidence_for={
                    "candidate_F3": stage_d_f3,
                    "candidate_F2": stage_d_f2,
                },
            )

            matrix = json.loads(refs["matrix"].read_text(encoding="utf-8"))
            for row in matrix["rows"]:
                with self.subTest(candidate=row["candidate_id"]):
                    self.assertEqual(row["stage_c_report_ref"], str(root / f"{row['candidate_id']}.stage_c.json"))
                    self.assertEqual(row["stage_d_report_ref"], str(root / f"{row['candidate_id']}.stage_d.json"))
                    self.assertEqual(row["candidate_alignment"]["stage_c_candidate_id"], row["candidate_id"])
                    self.assertEqual(row["candidate_alignment"]["stage_d_candidate_id"], row["candidate_id"])
                    self.assertTrue(row["same_candidate_evidence_only"])

    def test_claim_status_matrix_for_runs_rejects_candidate_map_payload_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runs = [self.write_candidate_run(root, "candidate_F3", "F3")]
            mismatched_stage_c, _ = self.write_stage_c_d_pair(root, "candidate_F2")

            with self.assertRaisesRegex(MODULE_ANY.E2EError, "candidate_id mismatch"):
                MODULE_ANY._write_claim_ceiling_status_matrix_for_runs(
                    output_dir=root,
                    candidate_runs=runs,
                    qe_correctness_report_for={"candidate_F3": mismatched_stage_c},
                )

    def test_claim_status_matrix_for_runs_preserves_legacy_singular_exact_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runs = [self.write_candidate_run(root, "candidate_F3", "F3")]
            stage_c_f3, stage_d_f3 = self.write_stage_c_d_pair(root, "candidate_F3")

            refs = MODULE_ANY._write_claim_ceiling_status_matrix_for_runs(
                output_dir=root,
                candidate_runs=runs,
                qe_correctness_report=stage_c_f3,
                implementation_evidence=stage_d_f3,
            )

            row = json.loads(refs["matrix"].read_text(encoding="utf-8"))["rows"][0]
            self.assertEqual(row["stage_c_report_ref"], str(stage_c_f3))
            self.assertEqual(row["stage_d_report_ref"], str(stage_d_f3))
            self.assertTrue(row["same_candidate_evidence_only"])

    def test_final_best_decision_helper_writes_blocked_decision_for_b4_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            b4_report = root / "candidate_runs" / "candidate_F3" / "gem5_systemc_timed_proxy_report.json"
            b4_report.parent.mkdir(parents=True, exist_ok=True)
            b4_report.write_text(
                json.dumps(
                    {
                        "candidate_id": "candidate_F3",
                        "execution_status": "executed",
                        "backend_class": "gem5_systemc_timed_proxy",
                        "claim_ceiling": "gem5_systemc_timed_proxy_only",
                        "metrics": {
                            "cycle_proxy": 200,
                            "cycle_source": "gem5_event_timed_device_observed",
                            "event_timed_device_activity_observed": True,
                            "candidate_device_event_delta_ticks": 200,
                            "host_control_mmio_read_count": 3,
                            "host_control_mmio_write_count": 1,
                            "successful_dma_transfer_bytes": 4096,
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            matrix = root / "claim_ceiling_status_matrix_v0.json"
            matrix.write_text(
                json.dumps(
                    {
                        "schema_version": "claim_ceiling_status_matrix_v0",
                        "row_count": 1,
                        "rows": [
                            {
                                "candidate_id": "candidate_F3",
                                "family": "F3",
                                "workload_id": "si4_pbe_uspp_small",
                                "case_id": "si4_pbe_uspp_small",
                                "blockers": [
                                    "missing_stage_c_qe_correctness_report",
                                    "missing_stage_d_implementation_evidence",
                                ],
                                "same_candidate_evidence_only": True,
                                "stage_c_report_ref": None,
                                "stage_d_report_ref": None,
                            }
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            collection = root / "backend_report_collection_v0.json"
            collection.write_text(
                json.dumps(
                    {
                        "schema_version": "backend_execution_report_collection_v0",
                        "candidate_reports": {
                            "candidate_F3": {"B4": {"report_ref": str(b4_report), "summary": {"cycle_proxy": 200}}}
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            manifest = root / "qe_fpga_dse_e2e_manifest_v0.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_fpga_dse_e2e_manifest_v0",
                        "repo_root": str(root),
                        "candidate_runs": [
                            {
                                "candidate_id": "candidate_F3",
                                "stage_b0_request": str(root / "candidate_F3.stage_b0.json"),
                                "gem5_b4_report": str(b4_report),
                            }
                        ],
                        "claim_ceiling_status_matrix": str(matrix),
                        "backend_report_collection": str(collection),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            output = root / "qe_fpga_final_best_architecture_decision_v0.json"

            decision = MODULE_ANY._write_final_best_architecture_decision(
                output,
                manifest_path=manifest,
                claim_matrix_path=matrix,
                backend_collection_path=collection,
                policy_path=None,
            )

            self.assertTrue(output.exists())
            self.assertIsNone(decision["winner"])
            self.assertEqual(decision["decision_status"], "blocked_no_eligible_candidates")
            self.assertEqual(decision["claim_ceiling"], "bounded_proxy_leader_only_no_final_best")


if __name__ == "__main__":
    unittest.main()
