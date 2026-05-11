from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any


MODULE_PATH = Path(__file__).with_name("run_qe_system_design_adjudicator.py")
SPEC = importlib.util.spec_from_file_location("run_qe_system_design_adjudicator", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "docs/benchmarks/testdata/adjudicator"


class RunQeSystemDesignAdjudicatorTests(unittest.TestCase):
    def test_stage_a_memo_contains_schema_required_surfaces(self) -> None:
        memo = self.build_memo_from_fixture("stage_a_dse_bundle.json")

        self.assertEqual(memo["schema_version"], "qe_system_design_adjudicator_schema_v0")
        self.assertEqual(memo["memo_kind"], "qe_system_design_adjudication_memo")
        self.assertEqual(memo["memo_metadata"]["canonical_claim_permission_surface"], "claim_matrix")
        self.assertEqual(memo["policy"]["canonical_claim_permission_surface"], "claim_matrix")
        self.assertEqual(memo["confidence_summary"]["canonical_claim_permission_surface"], "claim_matrix")
        self.assertEqual(
            memo["input_artifact_manifest"]["required_input_surfaces"],
            [
                "dse_subject_row",
                "family_summary_context",
                "gpu_annex_summary",
                "gpu_decisive_baseline_summary",
                "phase1_evidence_closure",
                "stage_main_evidence",
            ],
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["family_summary_context"]["artifact_kind"],
            "family_summary_context",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["family_summary_context"]["join_key_status"],
            "family_only_context",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["gpu_decisive_baseline_summary"]["artifact_kind"],
            "gpu_decisive_baseline_summary",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["dse_subject_row"]["artifact_schema_id"],
            "systemc_architecture_family_dse_result_schema_v0",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["family_summary_context"]["artifact_schema_id"],
            "systemc_architecture_family_dse_result_schema_v0",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["gpu_annex_summary"]["artifact_schema_id"],
            "deferred",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["gpu_annex_summary"]["artifact_hashes"]["sha256"],
            "deferred",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["gpu_annex_summary"]["artifact_contract_ids"]["fairness_policy_id"],
            "deferred",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["stage_main_evidence"]["artifact_schema_id"],
            "deferred",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["stage_main_evidence"]["artifact_contract_ids"]["correctness_contract_id"],
            "deferred",
        )
        self.assertEqual(memo["allowed_claims"], [])
        self.assertEqual(memo["guarded_claims"], ["simulator_dse_ranking_predictiveness"])
        self.assertEqual(memo["forbidden_claims"], MODULE.STAGE_A_FORBIDDEN_CLAIMS)
        for claim in memo["claim_matrix"]:
            self.assertIn("required_decisive_gpu_baseline", claim)
            self.assertIn("required_board_validation", claim)

    def test_adjudicator_preserves_candidate_runtime_split(self) -> None:
        memo = self.build_memo_from_payload(
            self.equal_candidate_bundle(
                candidate_family="F4",
                runtime_projection_family="F2",
                support_status="projection_only",
                executor_claim_allowed=False,
                architecture_template_id="template_f4_compute_rich_v0",
                candidate_id="candidate_f4_unit",
            )
        )

        subject_metadata = memo["comparison_scope"]["dse_subject_metadata"]
        self.assertEqual(memo["input_artifact_manifest"]["normalized_identity_tuple"]["family"], "F4")
        self.assertEqual(subject_metadata["candidate_family"], "F4")
        self.assertEqual(subject_metadata["runtime_projection_family"], "F2")
        self.assertEqual(subject_metadata["evaluator_backend"], "systemc_timed_functional")
        self.assertEqual(subject_metadata["fidelity_class"], "projection_only")
        self.assertEqual(subject_metadata["support_status"], "projection_only")
        self.assertIs(subject_metadata["support_evidence"]["executor_claim_allowed"], False)
        self.assertEqual(subject_metadata["architecture_template_id"], "template_f4_compute_rich_v0")
        self.assertEqual(subject_metadata["candidate_id"], "candidate_f4_unit")
        self.assertEqual(subject_metadata["design_axes"]["family"], "F2")
        self.assertEqual(
            memo["input_artifact_manifest"]["dse_subject_row"]["dse_subject_metadata"],
            subject_metadata,
        )
        self.assertEqual(memo["comparison_scope"]["evaluated_families"], ["F4"])
        self.assertEqual(memo["comparison_scope"]["trusted_family_candidate"], "F4")
        blocker_ids = {blocker["blocker_id"] for blocker in memo["blocker_ledger"]}
        self.assertIn("blocker::candidate_runtime_split", blocker_ids)
        self.assertIn("blocker::projection_only_support", blocker_ids)
        self.assertIn("blocker::executor_claim_disallowed", blocker_ids)
        note_dump = json.dumps(memo["notes"] + memo["evidence_ledger"][0]["notes"])
        self.assertIn("runtime_projection_family is F2", note_dump)
        self.assertIn("executor-path metadata only", note_dump)

    def test_stage_a_blocks_projection_only_claim_unlock(self) -> None:
        memo = self.build_memo_from_payload(
            self.equal_candidate_bundle(
                candidate_family="F1",
                runtime_projection_family="F1",
                support_status="projection_only",
                executor_claim_allowed=False,
            ),
            gpu_annex_name="gpu_annex_thesis_eligible.json",
            phase1_closure_name="phase1_closure_closed.json",
            board_closure_name="board_observability_pass.json",
            stage_main_evidence_name="stage_main_recommendation_ready.json",
        )

        self.assertEqual(memo["memo_metadata"]["stage"], "stage_a")
        self.assertEqual(memo["allowed_claims"], [])
        self.assertEqual(memo["guarded_claims"], ["simulator_dse_ranking_predictiveness"])
        self.assertEqual(memo["forbidden_claims"], MODULE.STAGE_A_FORBIDDEN_CLAIMS)
        self.assertIsNone(memo["decision"]["recommended_family"])
        self.assertIn("blocker::projection_only_support", memo["decision"]["blocked_by_blocker_ids"] if memo["decision"]["status"] == "blocked" else {blocker["blocker_id"] for blocker in memo["blocker_ledger"]})
        claim_by_id = {claim["claim_id"]: claim for claim in memo["claim_matrix"]}
        self.assertEqual(claim_by_id["family_recommendation"]["permission"], "forbidden")
        self.assertEqual(claim_by_id["cpu_fpga_vs_cpu_gpu"]["permission"], "forbidden")
        self.assertEqual(claim_by_id["lower_whole_node_power"]["permission"], "forbidden")
        self.assertIn(
            "executor_claim_allowed is executor-path metadata only",
            json.dumps(memo["notes"]),
        )

    def test_legacy_fixture_without_equal_candidate_fields_still_works(self) -> None:
        memo = self.build_memo_from_fixture("stage_a_dse_bundle.json")

        subject_metadata = memo["comparison_scope"]["dse_subject_metadata"]
        self.assertEqual(memo["input_artifact_manifest"]["normalized_identity_tuple"]["family"], "F1")
        self.assertEqual(subject_metadata["candidate_family"], "F1")
        self.assertIsNone(subject_metadata["runtime_projection_family"])
        self.assertIsNone(subject_metadata["evaluator_backend"])
        self.assertIsNone(subject_metadata["support_status"])
        self.assertIsNone(subject_metadata["support_evidence"]["executor_claim_allowed"])
        self.assertEqual(memo["comparison_scope"]["evaluated_families"], ["F1"])
        self.assertFalse(
            any(
                blocker["blocker_id"] in {
                    "blocker::candidate_runtime_split",
                    "blocker::projection_only_support",
                    "blocker::executor_claim_disallowed",
                }
                for blocker in memo["blocker_ledger"]
            )
        )

    def test_manifest_artifact_refs_publish_required_provenance_metadata(self) -> None:
        memo = self.build_memo_from_fixture(
            "stage_b_dse_bundle.json",
            gpu_annex_name="gpu_annex_thesis_eligible.json",
            phase1_closure_name="phase1_closure_closed.json",
            board_closure_name="board_observability_pass.json",
            stage_main_evidence_name="stage_main_recommendation_ready.json",
        )

        input_manifest = memo["input_artifact_manifest"]
        surfaces = [
            input_manifest["dse_subject_row"],
            input_manifest["family_summary_context"],
            input_manifest["gpu_annex_summary"],
            input_manifest["gpu_decisive_baseline_summary"],
            input_manifest["phase1_evidence_closure"],
            input_manifest["stage_main_evidence"],
            input_manifest["additional_evidence_refs"][0],
        ]
        for surface in surfaces:
            self.assertIn("artifact_schema_id", surface)
            self.assertIn("artifact_contract_ids", surface)
            self.assertIn("artifact_hashes", surface)
            self.assertIn("sha256", surface["artifact_hashes"])
            self.assertIn("fairness_policy_id", surface["artifact_contract_ids"])
            self.assertIn("observability_contract_id", surface["artifact_contract_ids"])
            self.assertIn("correctness_contract_id", surface["artifact_contract_ids"])
        self.assertEqual(input_manifest["gpu_annex_summary"]["artifact_schema_id"], "unknown")
        self.assertEqual(input_manifest["phase1_evidence_closure"]["artifact_schema_id"], "unknown")
        self.assertEqual(input_manifest["additional_evidence_refs"][0]["artifact_schema_id"], "unknown")
        self.assertEqual(
            input_manifest["stage_main_evidence"]["artifact_schema_id"],
            "qe_next_stage_stage_main_recommendation_v0",
        )
        self.assertEqual(
            input_manifest["dse_subject_row"]["artifact_contract_ids"]["algorithm_rewrite_manifest_id"],
            "qe_algorithm_rewrite_manifest_v0",
        )
        self.assertEqual(
            input_manifest["stage_main_evidence"]["artifact_contract_ids"]["correctness_contract_id"],
            "unknown",
        )
        self.assertRegex(input_manifest["dse_subject_row"]["artifact_hashes"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(input_manifest["gpu_annex_summary"]["artifact_hashes"]["sha256"], r"^[0-9a-f]{64}$")

    def test_trusted_vs_performance_divergence_is_reported_on_comparison_scope_and_decision(self) -> None:
        memo = self.build_memo_from_fixture("divergent_family_bundle.json")

        self.assertEqual(memo["comparison_scope"]["evaluated_families"], ["F1", "F2"])
        self.assertEqual(memo["comparison_scope"]["trusted_family_candidate"], "F1")
        self.assertEqual(memo["comparison_scope"]["best_performance_family_candidate"], "F2")
        self.assertEqual(
            memo["comparison_scope"]["trusted_vs_performance_divergence"]["status"],
            "diverged",
        )
        self.assertEqual(
            memo["comparison_scope"]["trusted_vs_performance_divergence"]["contradiction_ids"],
            ["contradiction::trusted_vs_performance_divergence"],
        )
        self.assertEqual(
            [entry["contradiction_class"] for entry in memo["contradiction_ledger"]],
            ["trusted_vs_performance_divergence"],
        )
        self.assertEqual(
            memo["confidence_summary"]["active_contradiction_ids"],
            ["contradiction::trusted_vs_performance_divergence"],
        )
        self.assertTrue(memo["decision"]["trusted_vs_performance_divergence_reported"])
        self.assertEqual(memo["decision"]["public_family_decision_status"], "no_recommendation")
        self.assertIsNone(memo["decision"]["recommended_family"])
        claim_by_id = {claim["claim_id"]: claim for claim in memo["claim_matrix"]}
        self.assertEqual(claim_by_id["family_recommendation"]["permission"], "forbidden")
        self.assertEqual(
            claim_by_id["family_recommendation"]["contradiction_ids"],
            ["contradiction::trusted_vs_performance_divergence"],
        )
        self.assertEqual(
            claim_by_id["simulator_dse_ranking_predictiveness"]["contradiction_ids"],
            [],
        )

    def test_not_selected_alternatives_stay_out_of_blocker_ledger(self) -> None:
        memo = self.build_memo_from_fixture(
            "stage_b_dse_bundle.json",
            gpu_annex_name="gpu_annex_with_not_selected_alternative.json",
            phase1_closure_name="phase1_closure_closed.json",
            board_closure_name="board_observability_pass.json",
            stage_main_evidence_name="stage_main_recommendation_ready.json",
        )

        self.assertEqual(memo["memo_metadata"]["stage"], "stage_b")
        self.assertEqual(memo["blocker_ledger"], [])
        blocker_dump = json.dumps(memo["blocker_ledger"])
        self.assertNotIn("not_selected_for_case_decision", blocker_dump)
        self.assertEqual(
            memo["input_artifact_manifest"]["gpu_annex_summary"]["artifact_status"],
            "present",
        )
        self.assertEqual(memo["decision"]["status"], "claim_ready")

    def test_stage_b_happy_path_fixture_unlocks_final_claims(self) -> None:
        memo = self.build_memo_from_fixture(
            "stage_b_dse_bundle.json",
            gpu_annex_name="gpu_annex_thesis_eligible.json",
            phase1_closure_name="phase1_closure_closed.json",
            board_closure_name="board_observability_pass.json",
            stage_main_evidence_name="stage_main_recommendation_ready.json",
        )

        self.assertEqual(memo["memo_metadata"]["stage"], "stage_b")
        self.assertEqual(memo["activation"]["activation_mode"], "stage_b_closure_bound")
        self.assertEqual(memo["decision"]["status"], "claim_ready")
        self.assertEqual(memo["decision"]["public_family_decision_status"], "family_selected")
        self.assertEqual(memo["decision"]["recommended_family"], "F1")
        self.assertEqual(
            memo["allowed_claims"],
            [
                "family_recommendation",
                "simulator_dse_ranking_predictiveness",
                "cpu_fpga_vs_cpu_gpu",
                "lower_whole_node_power",
                "same_correctness_tolerance",
                "resident_offload_fallback_attribution",
            ],
        )
        claim_by_id = {claim["claim_id"]: claim for claim in memo["claim_matrix"]}
        self.assertEqual(claim_by_id["cpu_fpga_vs_cpu_gpu"]["permission"], "allowed")
        self.assertEqual(claim_by_id["lower_whole_node_power"]["permission"], "allowed")
        self.assertEqual(memo["blocker_ledger"], [])
        self.assertEqual(
            memo["input_artifact_manifest"]["gpu_annex_summary"]["join_key_status"],
            "exact_match",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["phase1_evidence_closure"]["join_key_status"],
            "exact_match",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["stage_main_evidence"]["join_key_status"],
            "exact_match",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["additional_evidence_refs"][0]["join_key_status"],
            "exact_match",
        )

    def test_stage_b_unresolved_divergence_stays_conditional(self) -> None:
        memo = self.build_memo_from_fixture(
            "divergent_family_bundle.json",
            gpu_annex_name="gpu_annex_thesis_eligible.json",
            phase1_closure_name="phase1_closure_closed.json",
            board_closure_name="board_observability_pass.json",
            stage_main_evidence_name="stage_main_recommendation_ready.json",
        )

        self.assertEqual(memo["memo_metadata"]["stage"], "stage_b")
        self.assertEqual(memo["decision"]["status"], "claim_ready")
        self.assertEqual(memo["decision"]["public_family_decision_status"], "conditional_recommendation")
        self.assertIsNone(memo["decision"]["recommended_family"])
        self.assertEqual(
            memo["decision"]["trusted_vs_performance_resolution"],
            "conditional_until_measured_resolution",
        )
        claim_by_id = {claim["claim_id"]: claim for claim in memo["claim_matrix"]}
        self.assertEqual(claim_by_id["family_recommendation"]["permission"], "guarded")
        self.assertEqual(
            claim_by_id["family_recommendation"]["contradiction_ids"],
            ["contradiction::trusted_vs_performance_divergence"],
        )

    def test_artifact_side_join_key_drift_is_machine_readable(self) -> None:
        memo = self.build_memo_from_fixture(
            "stage_b_dse_bundle.json",
            gpu_annex_name="gpu_annex_join_key_drift.json",
            phase1_closure_name="phase1_closure_closed.json",
            board_closure_name="board_observability_pass.json",
            stage_main_evidence_name="stage_main_recommendation_ready.json",
        )

        self.assertEqual(memo["memo_metadata"]["stage"], "stage_a")
        self.assertEqual(
            memo["input_artifact_manifest"]["gpu_annex_summary"]["join_key_status"],
            "join_key_drift",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["gpu_annex_summary"]["artifact_status"],
            "missing",
        )
        self.assertEqual(
            memo["input_artifact_manifest"]["gpu_decisive_baseline_summary"]["join_key_status"],
            "join_key_drift",
        )
        join_key_drift_blockers = [
            blocker for blocker in memo["blocker_ledger"] if blocker["blocker_class"] == "join_key_drift"
        ]
        self.assertTrue(join_key_drift_blockers)
        self.assertTrue(
            any(
                "gpu_annex_summary::primary" in blocker["affected_artifact_ref_ids"]
                for blocker in join_key_drift_blockers
            )
        )
        self.assertEqual(memo["decision"]["public_family_decision_status"], "no_recommendation")

    def test_join_key_drift_fixture_fails_identity_validation(self) -> None:
        bundle_path = self.fixture_path("join_key_drift_bundle.json")
        with self.assertRaisesRegex(MODULE.AdjudicatorRunError, "missing identity field"):
            MODULE.build_stage_a_memo(
                dse_bundle_path=bundle_path,
                dse_bundle=MODULE.load_dse_bundle(bundle_path),
                gpu_annex=None,
                phase1_closure=None,
                board_closure=None,
                stage_main_evidence=None,
            )

    def test_frontdoor_only_proxy_fixture_stays_blocked(self) -> None:
        memo = self.build_memo_from_fixture("frontdoor_only_bundle.json")

        self.assertEqual(memo["memo_metadata"]["stage"], "stage_a")
        self.assertIsNone(memo["comparison_scope"]["trusted_family_candidate"])
        self.assertEqual(memo["decision"]["public_family_decision_status"], "blocked")
        self.assertEqual(memo["decision"]["release_posture"], "blocked")
        self.assertIn("blocker::graph_projection_only", memo["decision"]["blocked_by_blocker_ids"])
        self.assertEqual(
            [blocker["blocker_class"] for blocker in memo["blocker_ledger"]],
            [
                "gpu_baseline_missing_or_deferred",
                "graph_projection_only",
                "workload_group_not_admissible",
                "correctness_mismatch",
                "convergence_not_comparable",
            ],
        )

    def test_workload_group_incomplete_closure_fixture_blocks_stage_b_activation(self) -> None:
        memo = self.build_memo_from_fixture(
            "workload_group_incomplete_bundle.json",
            gpu_annex_name="gpu_annex_thesis_eligible.json",
            phase1_closure_name="phase1_closure_workload_group_incomplete.json",
            board_closure_name="board_observability_pass.json",
            stage_main_evidence_name="stage_main_recommendation_ready.json",
        )

        self.assertEqual(memo["memo_metadata"]["stage"], "stage_a")
        self.assertEqual(memo["decision"]["status"], "evidence_bounded")
        self.assertEqual(memo["decision"]["public_family_decision_status"], "no_recommendation")
        self.assertEqual(
            memo["activation"]["gate_statuses"]["workload_group_admissible"]["status"],
            "deferred",
        )
        blocker_by_class = {blocker["blocker_class"]: blocker for blocker in memo["blocker_ledger"]}
        self.assertIn("workload_group_not_admissible", blocker_by_class)
        self.assertEqual(
            blocker_by_class["workload_group_not_admissible"]["blocking_scope"],
            "workload_group",
        )

    def test_main_loads_stage_main_evidence_from_bundle_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            dse_dir = root / "phase_like_dir"
            dse_dir.mkdir()
            bundle_path = dse_dir / "systemc_architecture_family_dse_bootstrap_v0.json"
            bundle_path.write_text(
                self.fixture_path("stage_a_dse_bundle.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            stage_main_path = dse_dir / "qe_next_stage_stage_main_recommendation.json"
            stage_main_path.write_text(
                self.fixture_path("stage_main_recommendation_ready.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            output_dir = root / "out"

            import sys

            old_argv = sys.argv
            try:
                sys.argv = [
                    "run_qe_system_design_adjudicator.py",
                    "--dse-bundle",
                    str(bundle_path),
                    "--output-dir",
                    str(output_dir),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv

            self.assertEqual(rc, 0)
            memo = json.loads((output_dir / "decision_memo.json").read_text(encoding="utf-8"))
            self.assertEqual(
                memo["input_artifact_manifest"]["stage_main_evidence"]["artifact_status"],
                "present",
            )
            self.assertEqual(
                memo["input_artifact_manifest"]["stage_main_evidence"]["artifact_path"],
                str(stage_main_path),
            )

    def build_memo_from_fixture(
        self,
        bundle_name: str,
        *,
        gpu_annex_name: str | None = None,
        phase1_closure_name: str | None = None,
        board_closure_name: str | None = None,
        stage_main_evidence_name: str | None = None,
    ) -> dict[str, Any]:
        bundle_path = self.fixture_path(bundle_name)
        return MODULE.build_stage_a_memo(
            dse_bundle_path=bundle_path,
            dse_bundle=MODULE.load_dse_bundle(bundle_path),
            gpu_annex=self.wrap_optional_artifact("gpu_annex", gpu_annex_name),
            phase1_closure=self.wrap_optional_artifact("phase1_closure", phase1_closure_name),
            board_closure=self.wrap_optional_artifact("board_closure", board_closure_name),
            stage_main_evidence=self.wrap_optional_artifact("stage_main_evidence", stage_main_evidence_name),
        )

    def build_memo_from_payload(
        self,
        payload: dict[str, Any],
        *,
        gpu_annex_name: str | None = None,
        phase1_closure_name: str | None = None,
        board_closure_name: str | None = None,
        stage_main_evidence_name: str | None = None,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = Path(tmpdir) / "equal_candidate_bundle.json"
            bundle_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return MODULE.build_stage_a_memo(
                dse_bundle_path=bundle_path,
                dse_bundle=MODULE.load_dse_bundle(bundle_path),
                gpu_annex=self.wrap_optional_artifact("gpu_annex", gpu_annex_name),
                phase1_closure=self.wrap_optional_artifact("phase1_closure", phase1_closure_name),
                board_closure=self.wrap_optional_artifact("board_closure", board_closure_name),
                stage_main_evidence=self.wrap_optional_artifact("stage_main_evidence", stage_main_evidence_name),
            )

    @staticmethod
    def equal_candidate_bundle(
        *,
        candidate_family: str,
        runtime_projection_family: str,
        support_status: str,
        executor_claim_allowed: bool,
        architecture_template_id: str = "template_equal_candidate_v0",
        candidate_id: str = "candidate_equal_unit",
    ) -> dict[str, Any]:
        return {
            "schema_version": "systemc_architecture_family_dse_result_schema_v0",
            "result_bundle_kind": "architecture_family_dse_bundle",
            "generated_at_utc": "2026-04-25T00:00:00Z",
            "results": [
                {
                    "result_id": f"si4__{candidate_family}__runtime_{runtime_projection_family}",
                    "source_kind": "timed_functional_proxy",
                    "candidate_family": candidate_family,
                    "runtime_projection_family": runtime_projection_family,
                    "evaluator_backend": "systemc_timed_functional",
                    "fidelity_class": "projection_only" if support_status == "projection_only" else "timed_functional_proxy",
                    "support_status": support_status,
                    "support_evidence": {
                        "executor_claim_allowed": executor_claim_allowed,
                        "native_runtime_evidence_path": None,
                        "projection_reason": "Projected through runtime family for equal-candidate coverage.",
                        "future_backend_note": "Native executor path remains future work for this candidate family.",
                        "claim_boundary": "Stage-A evidence only; not final/public architecture or performance claim permission.",
                    },
                    "architecture_template_id": architecture_template_id,
                    "candidate_id": candidate_id,
                    "workload": {
                        "workload_id": "si4_pbe_uspp_small"
                    },
                    "design_point": {
                        "family": runtime_projection_family,
                        "diag_policy": "cpu_only",
                        "offload_scope": "single_hotpath",
                        "resident_policy": "fit_first",
                        "partition_strategy": "single_hotpath_partition",
                        "canonical_profile_match": True,
                    },
                    "comparison_contract": {
                        "workload_group_id": "qe_fpga_phase1_workload_group_v0",
                        "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                        "accounting_boundary_id": "scf_shell_convergence_scope_v1",
                        "fairness_policy_id": "qe_cpu_gpu_fpga_fairness_and_power_contract_v0",
                        "power_boundary_id": "whole_node_steady_state_single_cpu_single_accelerator_v0",
                        "observability_contract_id": "qe_simulator_board_observability_contract_v0",
                        "algorithm_rewrite_manifest_id": "qe_algorithm_rewrite_manifest_v0",
                    },
                    "primary_metrics": {
                        "time_to_convergence_s": 10.0
                    },
                    "projection": {
                        "assumption_set_id": "qe_next_stage_phase_v0",
                        "ranking_grade_ready": True,
                        "projection_grade_ready": True,
                    },
                }
            ],
            "family_summary": [
                {
                    "family": runtime_projection_family
                }
            ],
            "candidate_family_summary": [
                {
                    "candidate_family": candidate_family,
                    "runtime_projection_families": [runtime_projection_family],
                    "support_status_counts": {support_status: 1}
                }
            ],
        }

    @staticmethod
    def fixture_path(name: str) -> Path:
        return FIXTURE_DIR / name

    def wrap_optional_artifact(
        self,
        label: str,
        fixture_name: str | None,
    ) -> dict[str, Any] | None:
        if fixture_name is None:
            return None
        path = self.fixture_path(fixture_name)
        return {
            "label": label,
            "path": path,
            "payload": json.loads(path.read_text(encoding="utf-8")),
        }


if __name__ == "__main__":
    unittest.main()
