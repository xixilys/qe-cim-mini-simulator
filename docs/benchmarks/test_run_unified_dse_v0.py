from __future__ import annotations

import csv
import contextlib
import io
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = Path(__file__).with_name("run_unified_dse_v0.py")
SPEC = importlib.util.spec_from_file_location("run_unified_dse_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)

DESIGN_SPACE_PATH = ROOT / "docs/benchmarks/qe_architecture_family_design_space_spec_v0.json"
FIXTURE_DIR = Path(__file__).with_name("testdata") / "unified_dse"


class RunUnifiedDseV0Tests(unittest.TestCase):
    def make_base_args(self, out_dir: Path) -> list[str]:
        return [
            "--design-space-spec",
            str(DESIGN_SPACE_PATH),
            "--workload",
            str(FIXTURE_DIR / "minimal_workload.json"),
            "--calibration",
            str(FIXTURE_DIR / "minimal_calibration.json"),
            "--output-dir",
            str(out_dir),
            "--dry-run",
            "--max-design-points",
            "3",
        ]

    def test_cli_writes_json_csv_and_manifest_as_evidence_only_without_final_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)

            rc = MODULE_ANY.main(self.make_base_args(out_dir) + ["--source-kind", "stub"])

            self.assertEqual(rc, 0)
            result_json = out_dir / "unified_dse_results_v0.json"
            result_csv = out_dir / "unified_dse_results_v0.csv"
            manifest_json = out_dir / "unified_dse_manifest_v0.json"
            self.assertTrue(result_json.exists())
            self.assertTrue(result_csv.exists())
            self.assertTrue(manifest_json.exists())

            bundle = json.loads(result_json.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
            with result_csv.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(bundle["schema_version"], "unified_dse_result_bundle_v0")
            self.assertEqual(bundle["authority"]["claim_posture"], "evidence_only")
            self.assertEqual(bundle["authority"]["decision_authority"], "adjudicator_memo_only")
            self.assertIsNone(bundle["authority"].get("final_public_family_winner"))
            self.assertGreaterEqual(len(bundle["results"]), 1)
            self.assertGreaterEqual(len(rows), 1)
            self.assertIn("promotion_state", rows[0])
            self.assertIn("authority_scope", rows[0])
            first_result = bundle["results"][0]
            self.assertEqual(
                first_result["systemc_feedback_contract"]["schema_version"],
                "qe_dse_systemc_feedback_contract_v0",
            )
            self.assertEqual(
                first_result["systemc_feedback_contract"]["status"],
                "planned_not_executed",
            )
            self.assertEqual(
                first_result["systemc_feedback_contract"]["execution_status"],
                "not_executed",
            )
            self.assertEqual(
                first_result["systemc_feedback_contract"]["claim_ceiling"],
                "timed_functional_proxy_contract_only",
            )
            self.assertEqual(
                first_result["systemc_feedback_contract"]["backend_class"],
                "systemc_timed_functional_proxy",
            )
            self.assertIn("systemc_configs/", first_result["systemc_feedback_contract"]["candidate_config_ref"])
            self.assertIsNone(first_result["systemc_feedback_contract"]["metrics_ref"])
            self.assertIn("time_proxy_s", first_result["systemc_feedback_contract"]["metrics_expected_keys"])
            self.assertIn("candidate_id", first_result["systemc_feedback_contract"]["calibration_join_keys"])
            self.assertFalse(first_result["systemc_feedback_contract"]["subprocess_invoked"])
            self.assertEqual(
                first_result["systemc_feedback_contract"]["implementation_target_class"],
                "unknown",
            )
            self.assertEqual(
                first_result["systemc_feedback_contract"]["backend_profile_id"],
                "stage_a_systemc_timed_functional_proxy",
            )
            self.assertEqual(
                first_result["systemc_feedback_contract"]["design_axes"],
                first_result["design_point"],
            )
            self.assertEqual(
                first_result["systemc_feedback_contract"]["calibration_status"],
                "not_applicable_for_dry_run",
            )
            self.assertEqual(
                first_result["gem5_handoff_contract"]["schema_version"],
                "qe_dse_gem5_systemc_handoff_contract_v0",
            )
            self.assertEqual(first_result["gem5_handoff_contract"]["status"], "planned_for_stage_b")
            self.assertEqual(first_result["gem5_handoff_contract"]["handoff_status"], "planned")
            self.assertEqual(first_result["gem5_handoff_contract"]["execution_status"], "not_executed")
            self.assertEqual(
                first_result["gem5_handoff_contract"]["platform_status"],
                "requires_linux_x86_validation",
            )
            self.assertEqual(
                first_result["gem5_handoff_contract"]["claim_ceiling"],
                "stage_b_handoff_contract_only",
            )
            self.assertIn("gem5_systemc_handoff/", first_result["gem5_handoff_contract"]["input_descriptor_ref"])
            self.assertIn("stage_b_gem5_systemc_scf_driver", first_result["gem5_handoff_contract"]["expected_command"])
            self.assertIn("gem5_systemc_reports/", first_result["gem5_handoff_contract"]["expected_report_ref"])
            self.assertIn("scf_control_loop_status", first_result["gem5_handoff_contract"]["output_report_expected_keys"])
            self.assertEqual(first_result["qe_anchor_refs"]["schema_version"], "qe_anchor_refs_v0")
            self.assertEqual(first_result["qe_anchor_refs"]["status"], "trace_or_correctness_anchor_only")
            self.assertEqual(first_result["qe_anchor_refs"]["case_id"], first_result["workload"]["workload_id"])
            self.assertEqual(first_result["qe_anchor_refs"]["anchor_evidence_kind"], "missing_or_trace_only")
            self.assertFalse(first_result["qe_anchor_refs"]["qe_equivalent_scf_claim"])
            self.assertEqual(first_result["qe_anchor_refs"]["claim_ceiling"], "anchor_reference_only")
            self.assertIsNone(first_result["screening_rank"])
            self.assertEqual(first_result["pareto_membership"], "not_evaluated")
            self.assertEqual(first_result["shortlist_reason"], "insufficient_metrics_for_shortlist")
            self.assertEqual(first_result["ranking_claim_ceiling"], "stage_a_screening_only")
            self.assertIsNone(first_result["final_public_family_winner"])
            for key in (
                "systemc_feedback_contract",
                "systemc_feedback_contract_status",
                "gem5_handoff_contract",
                "gem5_handoff_status",
                "gem5_handoff_platform_status",
                "gem5_handoff_claim_ceiling",
                "qe_anchor_refs",
                "qe_equivalent_scf_claim",
                "ranking_claim_ceiling",
            ):
                self.assertIn(key, rows[0])
            self.assertEqual(rows[0]["qe_equivalent_scf_claim"], "false")

            self.assertEqual(manifest["schema_version"], "unified_dse_manifest_v0")
            self.assertEqual(manifest["authority_scope"], "supporting_evidence_only")
            self.assertEqual(manifest["claim_posture"], "evidence_only")
            self.assertEqual(manifest["claim_boundary"], "stage_a_evidence_only_no_final_public_winner")
            self.assertEqual(manifest["decision_authority"], "adjudicator_memo_only")
            self.assertFalse(manifest["winner_declared"])
            self.assertIsNone(manifest["final_public_family_winner"])
            self.assertEqual(set(manifest["promotion_state_counts"]), {"reject", "explain-only", "promotion-eligible"})
            for key in (
                "backend_neutral_schema_present",
                "systemc_feedback_contract_present",
                "gem5_handoff_contract_present",
                "qe_anchor_refs_present",
                "ranking_semantics_present",
                "claim_boundary_present",
            ):
                self.assertTrue(manifest[key])
            self.assertEqual(manifest["stage_a_gate_blockers"], {})

    def test_cli_can_emit_stage_b0_descriptors_without_execution_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)

            rc = MODULE_ANY.main(
                self.make_base_args(out_dir)
                + ["--source-kind", "stub", "--emit-stage-b0-descriptors"]
            )

            self.assertEqual(rc, 0)
            manifest = json.loads(
                (out_dir / "unified_dse_manifest_v0.json").read_text(encoding="utf-8")
            )
            descriptor_manifest = json.loads(
                (out_dir / "stage_b0_descriptor_manifest_v0.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["stage_b0_descriptor_generation_status"], "generated_not_executed")
            self.assertEqual(manifest["stage_b0_descriptor_count"], 3)
            self.assertEqual(
                manifest["stage_b0_descriptor_manifest_ref"],
                "stage_b0_descriptor_manifest_v0.json",
            )
            self.assertEqual(
                manifest["backend_execution_request_generation_status"],
                "generated_not_executed",
            )
            self.assertEqual(manifest["backend_execution_request_count"], 3)
            self.assertEqual(
                manifest["backend_execution_request_claim_ceiling"],
                "descriptor_generation_only",
            )
            self.assertEqual(descriptor_manifest["schema_version"], "stage_b0_descriptor_manifest_v0")
            self.assertEqual(descriptor_manifest["execution_status"], "not_executed")
            self.assertEqual(descriptor_manifest["claim_ceiling"], "descriptor_generation_only")
            self.assertEqual(
                descriptor_manifest["backend_execution_request_generation_status"],
                "generated_not_executed",
            )
            self.assertEqual(descriptor_manifest["backend_execution_request_count"], 3)
            self.assertEqual(len(descriptor_manifest["descriptors"]), 3)

            first = descriptor_manifest["descriptors"][0]
            systemc_config = json.loads((out_dir / first["systemc_config_ref"]).read_text(encoding="utf-8"))
            gem5_descriptor = json.loads((out_dir / first["gem5_descriptor_ref"]).read_text(encoding="utf-8"))
            backend_request = json.loads(
                (out_dir / first["backend_execution_request_ref"]).read_text(encoding="utf-8")
            )

            self.assertEqual(
                systemc_config["schema_version"],
                "qe_dse_systemc_candidate_config_stage_b0_v0",
            )
            self.assertEqual(systemc_config["execution_status"], "not_executed")
            self.assertEqual(systemc_config["claim_ceiling"], "systemc_config_descriptor_only")
            self.assertEqual(systemc_config["candidate_identity"]["candidate_id"], first["candidate_id"])
            self.assertEqual(systemc_config["candidate_identity"]["design_axes"], systemc_config["design_point"])
            self.assertFalse(systemc_config["backend_neutral_schema"]["cim_lockin"])

            self.assertEqual(
                gem5_descriptor["schema_version"],
                "qe_dse_gem5_systemc_handoff_descriptor_stage_b0_v0",
            )
            self.assertEqual(gem5_descriptor["execution_status"], "not_executed")
            self.assertEqual(gem5_descriptor["claim_ceiling"], "stage_b0_handoff_descriptor_only")
            self.assertEqual(gem5_descriptor["systemc_config_ref"], first["systemc_config_ref"])
            self.assertEqual(gem5_descriptor["candidate_identity"]["candidate_id"], first["candidate_id"])
            self.assertFalse(gem5_descriptor["qe_anchor_refs"]["qe_equivalent_scf_claim"])
            self.assertIn("stage_b_gem5_systemc_scf_driver", gem5_descriptor["expected_command"])

            self.assertEqual(backend_request["schema_version"], "backend_execution_request_v0")
            self.assertEqual(backend_request["candidate_id"], first["candidate_id"])
            self.assertEqual(backend_request["requested_fidelity"], "B2")
            self.assertEqual(backend_request["execution_mode"], "systemc_timed_functional")
            self.assertEqual(
                backend_request["input_refs"]["systemc_config"],
                f"../{first['systemc_config_ref']}",
            )
            self.assertEqual(
                backend_request["input_refs"]["gem5_handoff_descriptor"],
                f"../{first['gem5_descriptor_ref']}",
            )
            self.assertEqual(backend_request["expected_report_schema"], "backend_execution_report_v0")
            self.assertFalse(
                backend_request["domain_extension"]["qe"]["qe_equivalent_scf_claim"]
            )
            MODULE_ANY.backend_execution.BackendExecutionRequest.from_dict(backend_request)
            request_root = (out_dir / first["backend_execution_request_ref"]).parent
            self.assertTrue((request_root / backend_request["input_refs"]["systemc_config"]).resolve().exists())
            self.assertTrue(
                (request_root / backend_request["input_refs"]["gem5_handoff_descriptor"]).resolve().exists()
            )

    def test_cli_can_ingest_systemc_feedback_artifact_for_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            candidate_id = (
                "si4_pbe_uspp_small__F1__cpu_only__single_hotpath__fit_first__"
                "single_hotpath_partition"
            )
            feedback_path = out_dir / "systemc_feedback.json"
            feedback_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_systemc_feedback_artifact_v0",
                        "execution_status": "executed",
                        "source_kind": "timed_functional_proxy",
                        "rows": [
                            {
                                "candidate_id": candidate_id,
                                "metrics": {
                                    "time_to_convergence_s": 1.0,
                                    "energy_to_convergence_j": 2.0,
                                    "bytes_moved_to_convergence": 3.0,
                                    "fallback_ratio": 0.0,
                                    "spill_ratio": 0.0,
                                },
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rc = MODULE_ANY.main(
                self.make_base_args(out_dir)
                + [
                    "--source-kind",
                    "stub",
                    "--max-design-points",
                    "1",
                    "--systemc-feedback",
                    str(feedback_path),
                ]
            )

            self.assertEqual(rc, 0)
            bundle = json.loads((out_dir / "unified_dse_results_v0.json").read_text(encoding="utf-8"))
            manifest = json.loads((out_dir / "unified_dse_manifest_v0.json").read_text(encoding="utf-8"))
            row = bundle["results"][0]

            self.assertEqual(manifest["systemc_feedback_ingest_status"], "artifact_ingested_not_executed_by_cli")
            self.assertEqual(manifest["systemc_feedback_ref"], str(feedback_path))
            self.assertEqual(row["result_status"], "executed")
            self.assertEqual(row["source_kind"], "timed_functional_proxy")
            self.assertEqual(row["promotion_state"], "promotion-eligible")
            self.assertEqual(row["screening_rank"], 1)
            self.assertEqual(row["pareto_membership"], "screening_candidate")
            self.assertEqual(row["systemc_feedback_contract"]["status"], "feedback_artifact_ingested")
            self.assertEqual(row["systemc_feedback_contract"]["execution_status"], "executed")
            self.assertEqual(row["systemc_feedback_ingest"]["claim_ceiling"], "timed_functional_proxy_feedback_only")
            self.assertIsNone(row["final_public_family_winner"])

    def test_cli_can_emit_full_stage_status_with_later_stage_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)

            rc = MODULE_ANY.main(
                self.make_base_args(out_dir)
                + [
                    "--source-kind",
                    "stub",
                    "--max-design-points",
                    "1",
                    "--emit-stage-b0-descriptors",
                    "--emit-full-stage-status",
                ]
            )

            self.assertEqual(rc, 0)
            stage_status = json.loads(
                (out_dir / "unified_dse_full_stage_status_v0.json").read_text(encoding="utf-8")
            )
            stages = stage_status["stages"]

            self.assertEqual(stage_status["final_public_family_winner"], None)
            self.assertEqual(stages["stage_a_dse_core"]["status"], "complete")
            self.assertEqual(
                stages["stage_b0_descriptor_handoff"]["status"],
                "generated_not_executed",
            )
            self.assertEqual(
                stages["stage_b1_b2_systemc_feedback"]["status"],
                "blocked_waiting_systemc_feedback_artifact",
            )
            self.assertEqual(
                stages["stage_b3_gem5_systemc_smoke"]["status"],
                "blocked_waiting_gem5_systemc_smoke_report",
            )
            self.assertEqual(
                stages["stage_b_backend_execution_report"]["status"],
                "blocked_waiting_backend_execution_report",
            )
            self.assertEqual(
                stages["stage_c_qe_equivalent_scf"]["status"],
                "blocked_waiting_qe_equivalent_correctness_report",
            )
            self.assertEqual(
                stages["stage_d_fpga_asic_implementation"]["status"],
                "blocked_waiting_fpga_asic_implementation_evidence",
            )

    def test_cli_can_reference_backend_execution_report_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            report_ref = FIXTURE_DIR / "backend_execution_report_minimal.json"

            rc = MODULE_ANY.main(
                self.make_base_args(out_dir)
                + [
                    "--source-kind",
                    "stub",
                    "--max-design-points",
                    "1",
                    "--backend-execution-report",
                    str(report_ref),
                    "--emit-full-stage-status",
                ]
            )

            self.assertEqual(rc, 0)
            manifest = json.loads(
                (out_dir / "unified_dse_manifest_v0.json").read_text(encoding="utf-8")
            )
            stage_status = json.loads(
                (out_dir / "unified_dse_full_stage_status_v0.json").read_text(encoding="utf-8")
            )

            self.assertEqual(
                manifest["backend_execution_report_status"],
                "external_backend_report_validated_not_executed_by_cli",
            )
            self.assertEqual(manifest["backend_execution_report_execution_status"], "refused")
            self.assertEqual(
                manifest["backend_execution_report_claim_ceiling"],
                "systemc_standalone_proxy_only",
            )
            backend_stage = stage_status["stages"]["stage_b_backend_execution_report"]
            self.assertEqual(backend_stage["status"], "external_backend_report_referenced")
            self.assertEqual(backend_stage["execution_status"], "refused")
            self.assertEqual(backend_stage["claim_ceiling"], "systemc_standalone_proxy_only")

    def test_cli_validates_gem5_smoke_report_before_marking_stage_b3_referenced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            report_path = out_dir / "gem5_smoke_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_gem5_systemc_smoke_report_v0",
                        "execution_status": "executed",
                        "claim_ceiling": "gem5_systemc_smoke_only",
                        "run_id": "stage_b3_smoke_fixture",
                        "candidate_id": (
                            "si4_pbe_uspp_small__F1__cpu_only__single_hotpath__fit_first__"
                            "single_hotpath_partition"
                        ),
                        "environment": {
                            "host_os": "linux",
                            "host_arch": "x86_64",
                            "gem5_build_ref": "external-fixture",
                            "systemc_build_ref": "external-fixture",
                        },
                        "scf_control_loop_status": "smoke_passed",
                        "systemc_bridge_status": "smoke_passed",
                        "qe_equivalence_status": "not_claimed",
                        "metrics": {
                            "gem5_ticks": 100,
                            "systemc_transactions": 4,
                        },
                        "correctness_gate": {
                            "qe_equivalent_scf_claim": False,
                            "status": "not_evaluated",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rc = MODULE_ANY.main(
                self.make_base_args(out_dir)
                + [
                    "--source-kind",
                    "stub",
                    "--max-design-points",
                    "1",
                    "--gem5-smoke-report",
                    str(report_path),
                    "--emit-full-stage-status",
                ]
            )

            self.assertEqual(rc, 0)
            stage_status = json.loads(
                (out_dir / "unified_dse_full_stage_status_v0.json").read_text(encoding="utf-8")
            )
            stage_b3 = stage_status["stages"]["stage_b3_gem5_systemc_smoke"]

            self.assertEqual(stage_b3["status"], "external_smoke_report_referenced")
            self.assertEqual(stage_b3["execution_status"], "external_artifact_referenced")
            self.assertEqual(stage_b3["claim_ceiling"], "gem5_systemc_smoke_only")
            self.assertEqual(stage_b3["artifact_ref"], str(report_path))

    def test_cli_rejects_gem5_smoke_report_that_claims_qe_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            report_path = out_dir / "bad_gem5_smoke_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_gem5_systemc_smoke_report_v0",
                        "execution_status": "executed",
                        "claim_ceiling": "gem5_systemc_smoke_only",
                        "run_id": "bad_stage_b3_smoke",
                        "candidate_id": "candidate",
                        "environment": {},
                        "scf_control_loop_status": "smoke_passed",
                        "systemc_bridge_status": "smoke_passed",
                        "qe_equivalence_status": "proven",
                        "metrics": {},
                        "correctness_gate": {
                            "qe_equivalent_scf_claim": True,
                            "status": "passed",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "QE-equivalent"):
                MODULE_ANY.main(
                    self.make_base_args(out_dir)
                    + [
                        "--source-kind",
                        "stub",
                        "--max-design-points",
                        "1",
                        "--gem5-smoke-report",
                        str(report_path),
                        "--emit-full-stage-status",
                    ]
                )

    def test_cli_rejects_gem5_smoke_report_with_hidden_equivalence_text(self) -> None:
        for hidden_text in (
            "QE-equivalence passed",
            "domain_equivalent passed",
            "domain equivalent passed",
            "domain-equivalence passed",
        ):
            with self.subTest(hidden_text=hidden_text):
                with tempfile.TemporaryDirectory() as tmpdir:
                    out_dir = Path(tmpdir)
                    report_path = out_dir / "hidden_bad_gem5_smoke_report.json"
                    report_path.write_text(
                        json.dumps(
                            {
                                "schema_version": "qe_dse_gem5_systemc_smoke_report_v0",
                                "execution_status": "executed",
                                "claim_ceiling": "gem5_systemc_smoke_only",
                                "run_id": "hidden_bad_stage_b3_smoke",
                                "candidate_id": "candidate",
                                "environment": {},
                                "scf_control_loop_status": "smoke_passed",
                                "systemc_bridge_status": "smoke_passed",
                                "qe_equivalence_status": "not_claimed",
                                "metrics": {},
                                "correctness_gate": {
                                    "qe_equivalent_scf_claim": False,
                                    "status": "not_evaluated",
                                },
                                "notes": [hidden_text],
                            }
                        )
                        + "\n",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(ValueError, "QE-equivalent"):
                        MODULE_ANY.main(
                            self.make_base_args(out_dir)
                            + [
                                "--source-kind",
                                "stub",
                                "--max-design-points",
                                "1",
                                "--gem5-smoke-report",
                                str(report_path),
                                "--emit-full-stage-status",
                            ]
                        )

    def test_cli_validates_qe_correctness_report_and_marks_stage_c_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            report_path = out_dir / "qe_correctness_report.json"
            candidate_id = (
                "si4_pbe_uspp_small__F1__cpu_only__single_hotpath__fit_first__"
                "single_hotpath_partition"
            )
            report_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_qe_equivalent_correctness_report_v0",
                        "execution_status": "executed",
                        "claim_ceiling": "qe_equivalent_scf_correctness_only",
                        "report_id": "stage_c_correctness_fixture",
                        "candidate_id": candidate_id,
                        "workload_id": "si4_pbe_uspp_small",
                        "case_id": "si4_pbe_uspp_small",
                        "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                        "correctness_status": "pass",
                        "qe_equivalent_scf_claim": True,
                        "compare_report": {
                            "schema_name": "qe_gold_numerical_tolerance_schema_v0",
                            "schema_version": "2026-04-13",
                            "overall_pass": True,
                            "summary": {
                                "status": "pass",
                                "failed_required_fields": [],
                            },
                        },
                        "evidence_refs": {
                            "baseline": "artifacts/baseline/si4.gold.json",
                            "candidate": "artifacts/candidate/si4.candidate.json",
                            "compare_report": "artifacts/compare/si4.compare.json",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rc = MODULE_ANY.main(
                self.make_base_args(out_dir)
                + [
                    "--source-kind",
                    "stub",
                    "--max-design-points",
                    "1",
                    "--qe-correctness-report",
                    str(report_path),
                    "--emit-full-stage-status",
                ]
            )

            self.assertEqual(rc, 0)
            manifest = json.loads((out_dir / "unified_dse_manifest_v0.json").read_text(encoding="utf-8"))
            stage_status = json.loads(
                (out_dir / "unified_dse_full_stage_status_v0.json").read_text(encoding="utf-8")
            )
            stage_c = stage_status["stages"]["stage_c_qe_equivalent_scf"]

            self.assertEqual(
                manifest["qe_correctness_report_status"],
                "external_qe_equivalent_correctness_pass_referenced",
            )
            self.assertTrue(manifest["stage_c_qe_equivalent_scf_claim"])
            self.assertEqual(
                manifest["stage_c_claim_ceiling"],
                "qe_equivalent_scf_correctness_only",
            )
            self.assertEqual(stage_c["status"], "external_qe_equivalent_correctness_pass_referenced")
            self.assertTrue(stage_c["qe_equivalent_scf_claim"])
            self.assertTrue(stage_c["compare_overall_pass"])

    def test_cli_rejects_qe_correctness_report_that_claims_without_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            report_path = out_dir / "bad_qe_correctness_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_qe_equivalent_correctness_report_v0",
                        "execution_status": "executed",
                        "claim_ceiling": "qe_equivalent_scf_correctness_only",
                        "report_id": "bad_stage_c_correctness",
                        "candidate_id": "candidate",
                        "workload_id": "si4_pbe_uspp_small",
                        "case_id": "si4_pbe_uspp_small",
                        "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                        "correctness_status": "mismatch",
                        "qe_equivalent_scf_claim": True,
                        "compare_report": {
                            "schema_name": "qe_gold_numerical_tolerance_schema_v0",
                            "schema_version": "2026-04-13",
                            "overall_pass": False,
                            "summary": {"status": "mismatch"},
                        },
                        "evidence_refs": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "QE-equivalent SCF claim"):
                MODULE_ANY.main(
                    self.make_base_args(out_dir)
                    + [
                        "--source-kind",
                        "stub",
                        "--max-design-points",
                        "1",
                        "--qe-correctness-report",
                        str(report_path),
                        "--emit-full-stage-status",
                    ]
                )

    def test_cli_validates_implementation_evidence_and_marks_stage_d_referenced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            evidence_path = out_dir / "implementation_evidence.json"
            evidence_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_fpga_asic_implementation_evidence_v0",
                        "execution_status": "external_evidence_referenced",
                        "evidence_id": "stage_d_hls_fixture",
                        "candidate_id": (
                            "si4_pbe_uspp_small__F1__cpu_only__single_hotpath__fit_first__"
                            "single_hotpath_partition"
                        ),
                        "implementation_target_class": "fpga",
                        "evidence_kind": "hls_synthesis",
                        "evidence_status": "available",
                        "claim_ceiling": "hls_synthesis_only",
                        "artifact_refs": {
                            "hls_report": "artifacts/implementation/f1_hls_report.json",
                        },
                        "metrics": {
                            "estimated_lut": 1000,
                            "estimated_bram": 8,
                        },
                        "correctness_dependency": {
                            "qe_equivalent_scf_claim": False,
                            "qe_correctness_report_ref": None,
                        },
                        "final_public_family_winner": None,
                        "production_release_ready": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rc = MODULE_ANY.main(
                self.make_base_args(out_dir)
                + [
                    "--source-kind",
                    "stub",
                    "--max-design-points",
                    "1",
                    "--implementation-evidence",
                    str(evidence_path),
                    "--emit-full-stage-status",
                ]
            )

            self.assertEqual(rc, 0)
            manifest = json.loads((out_dir / "unified_dse_manifest_v0.json").read_text(encoding="utf-8"))
            stage_status = json.loads(
                (out_dir / "unified_dse_full_stage_status_v0.json").read_text(encoding="utf-8")
            )
            stage_d = stage_status["stages"]["stage_d_fpga_asic_implementation"]

            self.assertEqual(manifest["implementation_evidence_status"], "external_implementation_evidence_validated")
            self.assertEqual(manifest["stage_d_implementation_target_class"], "fpga")
            self.assertEqual(manifest["stage_d_evidence_kind"], "hls_synthesis")
            self.assertEqual(stage_d["status"], "external_implementation_evidence_referenced")
            self.assertEqual(stage_d["claim_ceiling"], "hls_synthesis_only")
            self.assertFalse(stage_d["qe_equivalent_scf_dependency_met"])

    def test_cli_rejects_implementation_evidence_with_public_winner_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            evidence_path = out_dir / "bad_implementation_evidence.json"
            evidence_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_fpga_asic_implementation_evidence_v0",
                        "execution_status": "external_evidence_referenced",
                        "evidence_id": "bad_stage_d",
                        "candidate_id": "candidate",
                        "implementation_target_class": "fpga",
                        "evidence_kind": "hls_synthesis",
                        "evidence_status": "available",
                        "claim_ceiling": "hls_synthesis_only",
                        "artifact_refs": {},
                        "metrics": {},
                        "correctness_dependency": {
                            "qe_equivalent_scf_claim": False,
                        },
                        "final_public_family_winner": "F1",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "final public family winner"):
                MODULE_ANY.main(
                    self.make_base_args(out_dir)
                    + [
                        "--source-kind",
                        "stub",
                        "--max-design-points",
                        "1",
                        "--implementation-evidence",
                        str(evidence_path),
                        "--emit-full-stage-status",
                    ]
                )

    def test_cli_rejects_non_stub_source_kind_for_current_fast_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    MODULE_ANY.main(
                        self.make_base_args(Path(tmpdir))
                        + ["--source-kind", "trace_calibrated_proxy"]
                    )

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("current Unified DSE v0 CLI only supports --source-kind stub", stderr.getvalue())

    def test_manifest_gates_reject_incomplete_contract_objects(self) -> None:
        valid_row = {
            "backend_neutral_schema": {
                "schema_version": "unified_dse_backend_neutral_schema_stage_a_v0",
                "architecture_family": "F2",
                "implementation_backend": "fast_model",
                "source_kind": "stub",
                "supported_target_classes": ["fpga", "asic"],
                "cim_lockin": False,
                "claim_ceiling": "backend_identity_and_stage_a_contract_only",
            },
            "systemc_feedback_contract": {
                "schema_version": "qe_dse_systemc_feedback_contract_v0",
                "status": "planned_not_executed",
                "execution_status": "not_executed",
                "backend_class": "systemc_timed_functional_proxy",
                "candidate_config_ref": "systemc_configs/candidate.json",
                "metrics_ref": None,
                "metrics_expected_keys": ["time_proxy_s"],
                "calibration_join_keys": ["candidate_id"],
                "calibration_status": "not_applicable_for_dry_run",
                "claim_ceiling": "timed_functional_proxy_contract_only",
                "subprocess_invoked": False,
                "implementation_target_class": "unknown",
                "backend_profile_id": "stage_a_systemc_timed_functional_proxy",
                "design_axes": {
                    "family": "F2",
                    "diag_policy": "device_first_fallback",
                    "offload_scope": "balanced",
                    "resident_policy": "fit_first",
                    "partition_strategy": "operator__build__diag__refresh",
                },
            },
            "gem5_handoff_contract": {
                "schema_version": "qe_dse_gem5_systemc_handoff_contract_v0",
                "status": "planned_for_stage_b",
                "handoff_status": "planned",
                "execution_status": "not_executed",
                "platform_status": "requires_linux_x86_validation",
                "input_descriptor_ref": "gem5_systemc_handoff/candidate.json",
                "expected_command": "stage_b_gem5_systemc_scf_driver --descriptor x --output y",
                "expected_report_ref": "gem5_systemc_reports/candidate.json",
                "output_report_expected_keys": ["scf_control_loop_status"],
                "claim_ceiling": "stage_b_handoff_contract_only",
            },
            "qe_anchor_refs": {
                "schema_version": "qe_anchor_refs_v0",
                "status": "trace_or_correctness_anchor_only",
                "workload_id": "si4",
                "case_id": "si4",
                "trace_ref": None,
                "dump_ref": None,
                "correctness_anchor_ref": None,
                "anchor_evidence_kind": "missing_or_trace_only",
                "qe_equivalent_scf_claim": False,
                "claim_ceiling": "anchor_reference_only",
            },
            "screening_rank": None,
            "pareto_membership": "not_evaluated",
            "shortlist_reason": "insufficient_metrics_for_shortlist",
            "ranking_claim_ceiling": "stage_a_screening_only",
            "authority_scope": "supporting_evidence_only",
            "final_public_family_winner": None,
        }
        incomplete = json.loads(json.dumps(valid_row))
        del incomplete["systemc_feedback_contract"]["backend_class"]
        cim_locked = json.loads(json.dumps(valid_row))
        cim_locked["backend_neutral_schema"]["cim_lockin"] = True
        overclaimed = json.loads(json.dumps(valid_row))
        overclaimed["backend_neutral_schema"]["claim_ceiling"] = "board_measured"
        wrong_schema = json.loads(json.dumps(valid_row))
        wrong_schema["backend_neutral_schema"]["schema_version"] = "future_claim_schema_v9"

        valid_gates = MODULE_ANY._stage_a_gates([valid_row])
        incomplete_gates = MODULE_ANY._stage_a_gates([incomplete])
        cim_locked_gates = MODULE_ANY._stage_a_gates([cim_locked])
        overclaimed_gates = MODULE_ANY._stage_a_gates([overclaimed])
        wrong_schema_gates = MODULE_ANY._stage_a_gates([wrong_schema])

        self.assertTrue(valid_gates["backend_neutral_schema_present"])
        self.assertTrue(valid_gates["systemc_feedback_contract_present"])
        self.assertTrue(valid_gates["claim_boundary_present"])
        self.assertFalse(incomplete_gates["systemc_feedback_contract_present"])
        self.assertFalse(cim_locked_gates["backend_neutral_schema_present"])
        self.assertFalse(overclaimed_gates["backend_neutral_schema_present"])
        self.assertFalse(wrong_schema_gates["backend_neutral_schema_present"])

    def test_cli_rejects_execute_systemc_in_v0_with_clear_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    MODULE_ANY.main(
                        self.make_base_args(Path(tmpdir))
                        + ["--source-kind", "stub", "--execute-systemc"]
                    )

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("SystemC execution remains via the canonical runner", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
