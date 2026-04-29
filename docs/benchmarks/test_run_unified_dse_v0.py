from __future__ import annotations

import csv
import contextlib
import io
import importlib.util
import json
import subprocess
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

    def assert_no_generic_qe_leak(self, root: Path) -> None:
        allowed_empty = {None, "", "None", "null", "not_applicable", False}

        def meaningful(value: Any) -> bool:
            if isinstance(value, str) and value and value[0] in "[{":
                try:
                    return meaningful(json.loads(value))
                except json.JSONDecodeError:
                    pass
            if isinstance(value, dict):
                return any(meaningful(item) for item in value.values())
            if isinstance(value, list):
                return any(meaningful(item) for item in value)
            return value not in allowed_empty

        def scan_json(value: Any, path: Path, trail: str = "$") -> None:
            if isinstance(value, dict):
                domain_extension = value.get("domain_extension")
                if isinstance(domain_extension, dict) and "qe" in domain_extension:
                    self.fail(f"domain_extension.qe leaked into {path}:{trail}.domain_extension")
                if "qe_anchor_refs" in value and meaningful(value["qe_anchor_refs"]):
                    self.fail(f"nonempty qe_anchor_refs leaked into {path}:{trail}.qe_anchor_refs")
                for key, item in value.items():
                    allowed_global_status = key in {
                        "qe_anchor_refs_present",
                        "qe_correctness_report_status",
                        "qe_correctness_report_ref",
                        "qe_equivalent_scf_claim",
                    }
                    if key.startswith("qe_") and meaningful(item) and not allowed_global_status:
                        self.fail(f"meaningful {key} leaked into {path}:{trail}.{key}")
                    scan_json(item, path, f"{trail}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    scan_json(item, path, f"{trail}[{index}]")

        for path in root.rglob("*.json"):
            scan_json(json.loads(path.read_text(encoding="utf-8")), path)
        for path in root.rglob("*.csv"):
            with path.open(newline="", encoding="utf-8") as handle:
                for row_index, row in enumerate(csv.DictReader(handle), start=2):
                    for key, value in row.items():
                        if key and key.startswith("qe_") and meaningful(value):
                            self.fail(f"meaningful {key} leaked into {path}:row{row_index}")
                        if key == "domain_extension" and "qe" in (value or ""):
                            self.fail(f"domain_extension.qe leaked into {path}:row{row_index}")

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
            self.assertEqual(descriptor_manifest["schema_version"], "stage_b0_descriptor_manifest_v0")
            self.assertEqual(descriptor_manifest["execution_status"], "not_executed")
            self.assertEqual(descriptor_manifest["claim_ceiling"], "descriptor_generation_only")
            self.assertEqual(len(descriptor_manifest["descriptors"]), 3)
            self.assertEqual(descriptor_manifest["blocked_descriptors"], [])

            first = descriptor_manifest["descriptors"][0]
            systemc_config = json.loads((out_dir / first["systemc_config_ref"]).read_text(encoding="utf-8"))
            architecture_config = json.loads((out_dir / first["architecture_config_ref"]).read_text(encoding="utf-8"))
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
            self.assertEqual(architecture_config["schema_version"], "systemc_architecture_config_v1")
            self.assertEqual(architecture_config["descriptor_provenance"]["systemc_config_separated"], True)
            self.assertEqual(architecture_config["non_claims"][0], "not_systemc_executed")
            self.assertEqual(systemc_config["candidate_identity"]["candidate_id"], first["candidate_id"])
            self.assertEqual(systemc_config["candidate_identity"]["design_axes"], systemc_config["design_point"])
            self.assertFalse(systemc_config["backend_neutral_schema"]["cim_lockin"])
            self.assertEqual(systemc_config["candidate_descriptor"]["schema_version"], "candidate_descriptor_v0")
            self.assertEqual(
                systemc_config["backend_execution_request"]["schema_version"],
                "backend_execution_request_v0",
            )
            self.assertEqual(
                systemc_config["workload_anchor_refs"]["workload_id"],
                systemc_config["qe_anchor_refs"]["workload_id"],
            )

            self.assertEqual(
                gem5_descriptor["schema_version"],
                "qe_dse_gem5_systemc_handoff_descriptor_stage_b0_v0",
            )
            self.assertEqual(gem5_descriptor["execution_status"], "not_executed")
            self.assertEqual(gem5_descriptor["claim_ceiling"], "stage_b0_handoff_descriptor_only")
            self.assertEqual(gem5_descriptor["systemc_config_ref"], first["systemc_config_ref"])
            self.assertEqual(gem5_descriptor["architecture_config_ref"], first["architecture_config_ref"])
            self.assertEqual(gem5_descriptor["candidate_identity"]["candidate_id"], first["candidate_id"])
            self.assertFalse(gem5_descriptor["qe_anchor_refs"]["qe_equivalent_scf_claim"])
            self.assertIn("stage_b_gem5_systemc_scf_driver", gem5_descriptor["expected_command"])
            self.assertEqual(backend_request["schema_version"], "backend_execution_request_v0")
            self.assertEqual(backend_request["expected_report_schema"], "backend_execution_report_v0")
            self.assertEqual(backend_request["input_refs"]["systemc_config"], first["systemc_config_ref"])
            self.assertEqual(backend_request["input_refs"]["architecture_config"], first["architecture_config_ref"])
            self.assertEqual(backend_request["workload_identity"]["adapter"], "qe")
            self.assertEqual(
                backend_request["candidate_identity"]["validity_class"],
                "valid_executable",
            )
            self.assertTrue(
                backend_request["backend_capability_profile"][
                    "supports_systemc_timed_functional"
                ]
            )
            self.assertFalse(backend_request["backend_capability_profile"]["supports_real_bridge"])
            required_groups = set(backend_request["metrics_contract"]["required_groups"])
            for key in (
                "time_to_completion_s",
                "device_busy_s",
                "host_wait_s",
                "dma_read_bytes",
                "dma_write_bytes",
                "bytes_moved_to_convergence",
                "resident_reuse_ratio",
                "fallback_ratio",
                "spill_ratio",
                "cycle_proxy",
            ):
                self.assertIn(key, required_groups)
            self.assertEqual(backend_request["claim_ceiling"], "descriptor_only")
            self.assertIn("not_systemc_executed", backend_request["non_claims"])
            self.assertIn("not_qe_correctness_executed", backend_request["non_claims"])

    def test_generic_workload_emits_no_qe_domain_extension_or_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workload_path = root / "generic_workload.json"
            workload_path.write_text(
                json.dumps(
                    {
                        "schema_version": "generic_trace_workload_v0",
                        "workload_id": "generic_spmv_small",
                        "domain": "sparse_linear_algebra",
                        "app_adapter": "generic_trace",
                        "dimension_n": 64,
                        "dimension_m": 4,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            out_dir = root / "out"

            rc = MODULE_ANY.main(
                [
                    "--design-space-spec",
                    str(DESIGN_SPACE_PATH),
                    "--workload",
                    str(workload_path),
                    "--output-dir",
                    str(out_dir),
                    "--source-kind",
                    "stub",
                    "--search-backend",
                    "bounded_cartesian",
                    "--max-design-points",
                    "1",
                    "--dry-run",
                    "--emit-stage-b0-descriptors",
                ]
            )

            self.assertEqual(rc, 0)
            bundle = json.loads((out_dir / "unified_dse_results_v0.json").read_text(encoding="utf-8"))
            row = bundle["results"][0]
            self.assertEqual(row["workload_identity"]["domain"], "sparse_linear_algebra")
            self.assertEqual(row["workload_identity"]["app_adapter"], "generic_trace")
            self.assertEqual(row["workload_identity"]["adapter"], "generic")
            self.assertEqual(row["domain_extension"], {})
            self.assertEqual(row["qe_anchor_refs"], {})
            descriptor_manifest = json.loads(
                (out_dir / "stage_b0_descriptor_manifest_v0.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(descriptor_manifest["descriptors"]), 1)
            backend_request = json.loads(
                (
                    out_dir
                    / descriptor_manifest["descriptors"][0]["backend_execution_request_ref"]
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(backend_request["workload_identity"]["adapter"], "generic")
            self.assertEqual(
                backend_request["candidate_identity"]["validity_class"],
                "valid_executable",
            )
            self.assertEqual(backend_request["domain_extension"], {})
            self.assert_no_generic_qe_leak(out_dir)

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
                        "claim_ceiling": "timed_functional_proxy_feedback_only",
                        "backend_class": "systemc_timed_functional_proxy",
                        "report_schema_version": "backend_execution_report_v0",
                        "rows": [
                            {
                                "candidate_id": candidate_id,
                                "claim_ceiling": "timed_functional_proxy_feedback_only",
                                "correctness_gate": {
                                    "status": "not_evaluated",
                                    "qe_equivalent_scf_claim": False,
                                },
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
            self.assertEqual(manifest["systemc_feedback_candidate_count"], 1)
            self.assertEqual(manifest["systemc_feedback_matched_candidate_count"], 1)
            self.assertEqual(manifest["systemc_feedback_unmatched_candidate_ids"], [])
            self.assertEqual(manifest["systemc_feedback_rejected_candidate_ids"], [])
            self.assertIsNone(row["final_public_family_winner"])

    def test_cli_rejects_feedback_for_invalid_candidate_before_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            candidate_id = (
                "si4_pbe_uspp_small__F1__aggressive_device__single_hotpath__fit_first__"
                "single_hotpath_partition"
            )
            feedback_path = out_dir / "invalid_candidate_feedback.json"
            feedback_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_systemc_feedback_artifact_v0",
                        "execution_status": "executed",
                        "source_kind": "timed_functional_proxy",
                        "claim_ceiling": "timed_functional_proxy_feedback_only",
                        "backend_class": "systemc_timed_functional_proxy",
                        "report_schema_version": "backend_execution_report_v0",
                        "rows": [
                            {
                                "candidate_id": candidate_id,
                                "claim_ceiling": "timed_functional_proxy_feedback_only",
                                "correctness_gate": {
                                    "status": "not_evaluated",
                                    "qe_equivalent_scf_claim": False,
                                },
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

            with self.assertRaisesRegex(ValueError, "feedback targets non-executable candidate"):
                MODULE_ANY.main(
                    self.make_base_args(out_dir)
                    + [
                        "--source-kind",
                        "stub",
                        "--max-design-points",
                        "100",
                        "--systemc-feedback",
                        str(feedback_path),
                    ]
                )
            self.assertFalse((out_dir / "unified_dse_manifest_v0.json").exists())

    def test_cli_rejects_unknown_feedback_candidate_before_manifest_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            feedback_path = out_dir / "unknown_candidate_feedback.json"
            feedback_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_systemc_feedback_artifact_v0",
                        "execution_status": "executed",
                        "source_kind": "timed_functional_proxy",
                        "claim_ceiling": "timed_functional_proxy_feedback_only",
                        "backend_class": "systemc_timed_functional_proxy",
                        "report_schema_version": "backend_execution_report_v0",
                        "rows": [
                            {
                                "candidate_id": "unknown_candidate_should_not_match",
                                "claim_ceiling": "timed_functional_proxy_feedback_only",
                                "correctness_gate": {
                                    "status": "not_evaluated",
                                    "qe_equivalent_scf_claim": False,
                                },
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

            with self.assertRaisesRegex(ValueError, "feedback contains unknown candidate IDs"):
                MODULE_ANY.main(
                    self.make_base_args(out_dir)
                    + [
                        "--source-kind",
                        "stub",
                        "--max-design-points",
                        "3",
                        "--systemc-feedback",
                        str(feedback_path),
                    ]
                )
            self.assertFalse((out_dir / "unified_dse_manifest_v0.json").exists())

    def test_cli_zero_row_feedback_is_validated_but_not_reported_as_ingested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            feedback_path = out_dir / "zero_row_feedback.json"
            feedback_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_systemc_feedback_artifact_v0",
                        "execution_status": "executed",
                        "source_kind": "timed_functional_proxy",
                        "claim_ceiling": "timed_functional_proxy_feedback_only",
                        "backend_class": "systemc_timed_functional_proxy",
                        "report_schema_version": "backend_execution_report_v0",
                        "rows": [],
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
            self.assertEqual(manifest["systemc_feedback_ingest_status"], "artifact_validated_no_rows")
            self.assertEqual(manifest["systemc_feedback_candidate_count"], 0)
            self.assertEqual(manifest["systemc_feedback_matched_candidate_count"], 0)
            self.assertEqual(manifest["systemc_feedback_unmatched_candidate_ids"], [])
            self.assertFalse(any("systemc_feedback_ingest" in row for row in bundle["results"]))

    def test_cli_rejects_overclaiming_systemc_feedback_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            feedback_path = out_dir / "bad_systemc_feedback.json"
            feedback_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_systemc_feedback_artifact_v0",
                        "execution_status": "executed",
                        "source_kind": "board_measured_overclaim",
                        "claim_ceiling": "board_or_physical_measured",
                        "backend_class": "physical_board",
                        "report_schema_version": "backend_execution_report_v0",
                        "rows": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "source_kind|claim_ceiling|backend_class"):
                MODULE_ANY.main(
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

    def test_cli_rejects_systemc_feedback_rows_without_correctness_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            feedback_path = out_dir / "bad_systemc_feedback_row.json"
            feedback_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_systemc_feedback_artifact_v0",
                        "execution_status": "executed",
                        "source_kind": "timed_functional_proxy",
                        "claim_ceiling": "timed_functional_proxy_feedback_only",
                        "backend_class": "systemc_timed_functional_proxy",
                        "report_schema_version": "backend_execution_report_v0",
                        "rows": [
                            {
                                "candidate_id": "candidate",
                                "claim_ceiling": "timed_functional_proxy_feedback_only",
                                "metrics": {},
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "correctness_gate|non_claims"):
                MODULE_ANY.main(
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

    def test_cli_rejects_systemc_feedback_rows_with_empty_correctness_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            feedback_path = out_dir / "bad_systemc_feedback_empty_gate.json"
            feedback_path.write_text(
                json.dumps(
                    {
                        "schema_version": "qe_dse_systemc_feedback_artifact_v0",
                        "execution_status": "executed",
                        "source_kind": "timed_functional_proxy",
                        "claim_ceiling": "timed_functional_proxy_feedback_only",
                        "backend_class": "systemc_timed_functional_proxy",
                        "report_schema_version": "backend_execution_report_v0",
                        "rows": [
                            {
                                "candidate_id": "candidate",
                                "claim_ceiling": "timed_functional_proxy_feedback_only",
                                "correctness_gate": {},
                                "metrics": {},
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "correctness_gate.status|non_claims"):
                MODULE_ANY.main(
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
                stages["stage_c_qe_equivalent_scf"]["status"],
                "blocked_waiting_qe_equivalent_correctness_report",
            )
            self.assertEqual(
                stages["stage_d_fpga_asic_implementation"]["status"],
                "blocked_waiting_fpga_asic_implementation_evidence",
            )

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

    def test_cli_backend_report_ingestion_emits_evidence_calibration_and_release_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "out"
            report_path = Path(tmpdir) / "backend_report.json"
            candidate_id = (
                "si4_pbe_uspp_small__F1__cpu_only__single_hotpath__fit_first__"
                "single_hotpath_partition"
            )
            report_path.write_text(
                json.dumps(
                    {
                        "schema_version": "backend_execution_report_v0",
                        "candidate_id": candidate_id,
                        "backend_class": "systemc_timed_functional_proxy",
                        "source_kind": "timed_functional_proxy",
                        "fidelity": "systemc_timed_functional",
                        "execution_status": "executed",
                        "metrics": {
                            "time_to_convergence_s": 0.5,
                            "energy_to_convergence_j": 1.0,
                            "bytes_moved_to_convergence": 2.0,
                            "fallback_ratio": 0.0,
                            "spill_ratio": 0.0,
                        },
                        "claim_ceiling": "systemc_proxy_only",
                        "correctness_gate": {
                            "status": "not_evaluated",
                            "qe_equivalent_scf_claim": False,
                        },
                        "non_claims": ["not_qe_equivalent_scf", "not_board_measured"],
                        "artifact_refs": {"report": "external/systemc_report.json"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rc = MODULE_ANY.main(
                [
                    "--design-space-spec",
                    str(DESIGN_SPACE_PATH),
                    "--workload",
                    str(FIXTURE_DIR / "minimal_workload.json"),
                    "--output-dir",
                    str(out_dir),
                    "--source-kind",
                    "fast_model_screening",
                    "--max-design-points",
                    "1",
                    "--backend-report",
                    str(report_path),
                    "--emit-release-bundle",
                    "--dry-run",
                ]
            )

            self.assertEqual(rc, 0)
            bundle = json.loads((out_dir / "unified_dse_results_v0.json").read_text(encoding="utf-8"))
            manifest = json.loads((out_dir / "unified_dse_manifest_v0.json").read_text(encoding="utf-8"))
            release = json.loads((out_dir / "frontend_release_bundle_v0.json").read_text(encoding="utf-8"))
            row = bundle["results"][0]

            self.assertEqual(manifest["backend_report_ingest_status"], "evidence_ir_normalized")
            self.assertEqual(manifest["evidence_ir_count"], 1)
            self.assertEqual(row["evidence_ir"]["schema_version"], "evidence_ir_v0")
            self.assertEqual(row["source_kind"], "timed_functional_proxy")
            self.assertTrue((out_dir / "calibration_metadata_v0.json").exists())
            self.assertEqual(release["schema_version"], "release_bundle_v0")
            self.assertIsNone(release["final_public_family_winner"])
            self.assertFalse(release["non_touch_guard"]["backend_execution_performed_by_frontend"])

    def test_cli_ingests_refused_backend_execution_report_without_execution_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "out"
            report_path = Path(tmpdir) / "backend_refused_report.json"
            candidate_id = (
                "si4_pbe_uspp_small__F1__cpu_only__single_hotpath__fit_first__"
                "single_hotpath_partition"
            )
            report_path.write_text(
                json.dumps(
                    {
                        "schema_version": "backend_execution_report_v0",
                        "candidate_id": candidate_id,
                        "backend_class": "systemc_timed_functional_proxy",
                        "source_kind": "backend_runner_dry_run",
                        "fidelity": "descriptor_only",
                        "execution_status": "refused",
                        "metrics": {},
                        "claim_ceiling": "descriptor_only",
                        "correctness_gate": {
                            "status": "not_evaluated",
                            "qe_equivalent_scf_claim": False,
                        },
                        "non_claims": [
                            "not_backend_executed",
                            "not_qe_correctness_claim",
                            "not_board_or_physical_measurement_claim",
                        ],
                        "artifact_refs": {"report": "external/backend_refusal_report.json"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rc = MODULE_ANY.main(
                [
                    "--design-space-spec",
                    str(DESIGN_SPACE_PATH),
                    "--workload",
                    str(FIXTURE_DIR / "minimal_workload.json"),
                    "--output-dir",
                    str(out_dir),
                    "--source-kind",
                    "fast_model_screening",
                    "--max-design-points",
                    "1",
                    "--backend-report",
                    str(report_path),
                    "--dry-run",
                ]
            )

            self.assertEqual(rc, 0)
            bundle = json.loads((out_dir / "unified_dse_results_v0.json").read_text(encoding="utf-8"))
            manifest = json.loads((out_dir / "unified_dse_manifest_v0.json").read_text(encoding="utf-8"))
            row = bundle["results"][0]

            self.assertEqual(manifest["backend_report_ingest_status"], "evidence_ir_normalized")
            self.assertEqual(manifest["evidence_ir_count"], 1)
            self.assertEqual(row["evidence_ir"]["execution_status"], "refused")
            self.assertEqual(row["evidence_ir"]["claim_ceiling"], "descriptor_only")
            self.assertEqual(row["source_kind"], "backend_runner_dry_run")
            self.assertNotEqual(row["result_status"], "executed")
            self.assertIn("not_backend_executed", row["evidence_ir"]["non_claims"])

    def test_scheduler_selected_stage_b0_emits_only_plan_selected_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)

            rc = MODULE_ANY.main(
                self.make_base_args(out_dir)
                + [
                    "--source-kind",
                    "fast_model_screening",
                    "--max-design-points",
                    "9",
                    "--shortlist-policy",
                    "top_fast_uncertain_diverse",
                    "--shortlist-size",
                    "2",
                    "--emit-multi-fidelity-plan",
                    "--emit-stage-b0-descriptors",
                    "--stage-b0-emission-mode",
                    "scheduler_selected_only",
                ]
            )

            self.assertEqual(rc, 0)
            plan = json.loads((out_dir / "multi_fidelity_plan_v0.json").read_text(encoding="utf-8"))
            descriptor_manifest = json.loads(
                (out_dir / "stage_b0_descriptor_manifest_v0.json").read_text(encoding="utf-8")
            )
            selected_ids = {item["candidate_id"] for item in plan["selected_candidates"]}
            emitted_ids = {item["candidate_id"] for item in descriptor_manifest["descriptors"]}

            self.assertEqual(plan["schema_version"], "multi_fidelity_plan_v0")
            self.assertEqual(descriptor_manifest["emission_mode"], "scheduler_selected_only")
            self.assertEqual(emitted_ids, selected_ids)
            self.assertEqual(descriptor_manifest["descriptor_count"], plan["selected_count"])
            self.assertGreaterEqual(descriptor_manifest["unselected_valid_candidate_count"], 1)

    def test_qedse_frontend_wrapper_help_for_all_subcommands(self) -> None:
        script = ROOT / "docs/benchmarks/qedse_frontend.py"
        for command in (
            "enumerate",
            "optimize",
            "emit-handoff",
            "ingest-feedback",
            "calibrate",
            "adjudicate",
            "release",
        ):
            with self.subTest(command=command):
                proc = subprocess.run(
                    ["python3", str(script), "frontend", command, "--help"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("usage:", proc.stdout)

    def test_cli_rejects_backend_source_kind_for_current_frontend_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    MODULE_ANY.main(
                        self.make_base_args(Path(tmpdir))
                        + ["--source-kind", "trace_calibrated_proxy"]
                    )

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("stub or fast_model_screening", stderr.getvalue())

    def test_cli_fast_model_screening_is_frontend_only_and_ranked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)

            rc = MODULE_ANY.main(
                self.make_base_args(out_dir)
                + [
                    "--source-kind",
                    "fast_model_screening",
                    "--max-design-points",
                    "4",
                    "--search-backend",
                    "bounded_cartesian",
                    "--shortlist-policy",
                    "top_fast_uncertain_diverse",
                    "--shortlist-size",
                    "2",
                    "--emit-stage-b0-descriptors",
                ]
            )

            self.assertEqual(rc, 0)
            bundle = json.loads((out_dir / "unified_dse_results_v0.json").read_text(encoding="utf-8"))
            rows = bundle["results"]
            self.assertTrue(any(row["result_status"] == "screened" for row in rows))
            self.assertEqual({row["source_kind"] for row in rows}, {"fast_model_screening"})
            ranked = [row for row in rows if row["promotion_state"] == "promotion-eligible"]
            self.assertGreaterEqual(len(ranked), 1)
            self.assertEqual({row["ranking_claim_ceiling"] for row in ranked}, {"fast_model_screening_only"})
            self.assertIsNone(bundle["authority"]["final_public_family_winner"])
            self.assertTrue(any(row["shortlisted_for_backend"] for row in rows))
            first = rows[0]
            self.assertEqual(first["model_metadata"]["claim_ceiling"], "fast_model_screening_only")
            self.assertEqual(first["backend_neutral_schema"]["source_kind"], "fast_model_screening")
            self.assertEqual(
                first["candidate_descriptor"]["candidate_identity"]["source_kind"],
                "fast_model_screening",
            )
            self.assertEqual(first["candidate_descriptor"]["schema_version"], "candidate_descriptor_v0")
            self.assertEqual(
                first["backend_execution_request"]["expected_report_schema"],
                "backend_execution_report_v0",
            )

    def test_stage_b0_descriptor_emission_blocks_projection_only_rows_directly(self) -> None:
        stage_b0_descriptors = importlib.import_module("unified_dse.stage_b0_descriptors")
        stage_a_contracts = importlib.import_module("unified_dse.stage_a_contracts")
        workload = json.loads((FIXTURE_DIR / "minimal_workload.json").read_text(encoding="utf-8"))
        row = {
            "workload": workload,
            "design_point": {
                "family": "F4",
                "diag_policy": "device_first_fallback",
                "offload_scope": "balanced",
                "resident_policy": "fit_first",
                "partition_strategy": "operator__build__diag__refresh",
            },
            "backend": "fast_model",
            "result_status": "stub",
            "source_kind": "stub",
            "metrics": {},
            "authority_scope": "supporting_evidence_only",
            "promotion_state": "explain-only",
            "final_public_family_winner": None,
        }
        row = stage_a_contracts.attach_stage_a_contracts(row)

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = stage_b0_descriptors.emit_stage_b0_descriptors(Path(tmpdir), [row])

            self.assertEqual(manifest["descriptor_count"], 0)
            self.assertEqual(manifest["blocked_descriptor_count"], 1)
            self.assertEqual(
                manifest["blocked_descriptors"][0]["validity_class"],
                "projection_only",
            )
            self.assertFalse((Path(tmpdir) / "systemc_configs").exists())

    def test_stage_b0_descriptor_validation_matches_stage_a_row_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            rc = MODULE_ANY.main(
                self.make_base_args(out_dir)
                + ["--source-kind", "stub", "--max-design-points", "1", "--emit-stage-b0-descriptors"]
            )

            self.assertEqual(rc, 0)
            bundle = json.loads((out_dir / "unified_dse_results_v0.json").read_text(encoding="utf-8"))
            descriptor_manifest = json.loads(
                (out_dir / "stage_b0_descriptor_manifest_v0.json").read_text(encoding="utf-8")
            )
            row = bundle["results"][0]
            descriptor = descriptor_manifest["descriptors"][0]
            systemc_config = json.loads(
                (out_dir / descriptor["systemc_config_ref"]).read_text(encoding="utf-8")
            )
            gem5_descriptor = json.loads(
                (out_dir / descriptor["gem5_descriptor_ref"]).read_text(encoding="utf-8")
            )

            self.assertEqual(systemc_config["design_validation"], row["design_validation"])
            self.assertEqual(gem5_descriptor["design_validation"], row["design_validation"])
            self.assertNotIn("target_resource_model", systemc_config["design_validation"]["missing_evidence"])

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
