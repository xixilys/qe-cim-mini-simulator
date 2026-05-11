from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).with_name("unified_dse")
FIXTURE_DIR = ROOT / "docs/benchmarks/testdata/unified_dse"
IDENTITY_KEYS = (
    "workload_id",
    "workload_group_id",
    "qe_tolerance_schema_id",
    "accounting_boundary_id",
    "fairness_policy_id",
    "power_boundary_id",
    "observability_contract_id",
    "family",
    "diag_policy",
    "offload_scope",
    "resident_policy",
    "partition_strategy",
)


VALID_EXECUTABLE_VALIDATION = {
    "schema_version": "design_point_validation_v0",
    "validity_class": "valid_executable",
    "claim_ceiling": "descriptor_only",
    "missing_evidence": [],
    "promotion_blockers": [],
    "reasons": ["valid_executable_stage_a_descriptor"],
}


def load_unified_dse_module(module_name: str) -> Any:
    package = sys.modules.get("unified_dse")
    if package is None:
        package = ModuleType("unified_dse")
        package.__path__ = [str(PACKAGE_DIR)]
        sys.modules["unified_dse"] = package

    module_path = PACKAGE_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"unified_dse.{module_name}", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_row() -> dict[str, Any]:
    workload = json.loads((FIXTURE_DIR / "minimal_workload.json").read_text(encoding="utf-8"))
    return {
        "workload": workload,
        "design_point": {
            "family": "F2",
            "diag_policy": "device_first_fallback",
            "offload_scope": "balanced",
            "resident_policy": "fit_first",
            "partition_strategy": "operator__build__diag__refresh",
        },
        "result_status": "stub",
        "source_kind": "stub",
        "metrics": {},
        "projection": {"ranking_grade_ready": False},
    }


class UnifiedDseAnalysisTests(unittest.TestCase):
    def test_calibration_feedback_cannot_mutate_identity_keys(self) -> None:
        calibration_engine = load_unified_dse_module("calibration_engine")
        row = make_row()
        feedback = json.loads((FIXTURE_DIR / "minimal_calibration.json").read_text(encoding="utf-8"))

        for key in IDENTITY_KEYS:
            with self.subTest(identity_key=key):
                mutated = dict(feedback)
                mutated[key] = "mutated_identity_value"
                with self.assertRaisesRegex(ValueError, "identity key"):
                    calibration_engine.apply_calibration_feedback(row, mutated)

    def test_valid_calibration_feedback_updates_copy_without_identity_drift(self) -> None:
        calibration_engine = load_unified_dse_module("calibration_engine")
        row = make_row()
        row["metrics"] = {
            "time_to_convergence_s": 2.0,
            "energy_to_convergence_j": 3.0,
            "bytes_moved_to_convergence": 4.0,
            "fallback_ratio": 0.0,
            "spill_ratio": 0.0,
        }
        feedback = json.loads((FIXTURE_DIR / "minimal_calibration.json").read_text(encoding="utf-8"))
        feedback["source_kind"] = "trace_calibrated_proxy"
        feedback["alpha_family"] = 2.0
        feedback["beta_workload"] = 1.5
        feedback["gamma_transfer"] = 0.25
        feedback["calibration_residual_summary"] = {
            "status": "bounded_proxy_residual",
            "max_relative_error": 0.02,
            "sample_count": 3,
        }

        updated = calibration_engine.apply_calibration_feedback(row, feedback)

        self.assertIsNot(updated, row)
        self.assertEqual(row["source_kind"], "stub")
        self.assertEqual(updated["source_kind"], "trace_calibrated_proxy")
        self.assertEqual(updated["workload"]["workload_id"], row["workload"]["workload_id"])
        self.assertEqual(updated["design_point"]["family"], row["design_point"]["family"])
        self.assertEqual(updated["calibration"]["calibration_manifest_id"], "unit_calibration_manifest_v0")
        self.assertEqual(updated["calibration_metadata"]["calibration_data_count"], 3)
        self.assertAlmostEqual(updated["calibrated_metrics"]["time_to_convergence_s"], 6.25)

    def test_calibration_feedback_preserves_fast_model_screening_source_kind(self) -> None:
        calibration_engine = load_unified_dse_module("calibration_engine")
        row = make_row()
        row["result_status"] = "screened"
        row["source_kind"] = "fast_model_screening"
        feedback = json.loads((FIXTURE_DIR / "minimal_calibration.json").read_text(encoding="utf-8"))

        updated = calibration_engine.apply_calibration_feedback(row, feedback)

        self.assertEqual(updated["source_kind"], "fast_model_screening")
        self.assertEqual(updated["calibration"]["source_kind"], "stub")

    def test_result_analysis_promotion_states_are_closed_set(self) -> None:
        result_analysis = load_unified_dse_module("result_analysis")
        rows = [
            {
                "result_status": "model_error",
                "metrics": {},
                "projection": {"ranking_grade_ready": False},
            },
            {
                "result_status": "stub",
                "metrics": {},
                "projection": {"ranking_grade_ready": False},
            },
            {
                "result_status": "executed",
                "metrics": {
                    "time_to_convergence_s": 1.0,
                    "energy_to_convergence_j": 2.0,
                    "bytes_moved_to_convergence": 3.0,
                    "fallback_ratio": 0.0,
                    "spill_ratio": 0.0,
                },
                "projection": {"ranking_grade_ready": True},
                "design_validation": dict(VALID_EXECUTABLE_VALIDATION),
            },
        ]

        summary = result_analysis.summarize_results(rows)
        allowed = {"reject", "explain-only", "promotion-eligible"}

        self.assertEqual(set(result_analysis.PROMOTION_STATES), allowed)
        self.assertEqual(set(summary["promotion_state_counts"]), allowed)
        self.assertEqual({row["promotion_state"] for row in summary["rows"]}, allowed)
        for row in summary["rows"]:
            self.assertEqual(row["ranking_claim_ceiling"], "stage_a_screening_only")
            self.assertIn("screening_rank", row)
            self.assertIn("pareto_membership", row)
            self.assertIn("shortlist_reason", row)
            self.assertIsNone(row["final_public_family_winner"])
        explain_rows = [row for row in summary["rows"] if row["promotion_state"] != "promotion-eligible"]
        self.assertEqual(
            {row["pareto_membership"] for row in explain_rows},
            {"not_evaluated"},
        )
        with self.assertRaisesRegex(ValueError, "promotion state"):
            result_analysis.validate_promotion_state("winner")

    def test_result_analysis_ranks_only_promotion_eligible_rows(self) -> None:
        result_analysis = load_unified_dse_module("result_analysis")
        rows = [
            {
                "result_status": "executed",
                "screening_rank": 99,
                "metrics": {
                    "time_to_convergence_s": 2.0,
                    "energy_to_convergence_j": 2.0,
                    "bytes_moved_to_convergence": 2.0,
                    "fallback_ratio": 0.0,
                    "spill_ratio": 0.0,
                },
                "projection": {"ranking_grade_ready": True},
                "design_validation": dict(VALID_EXECUTABLE_VALIDATION),
            },
            {
                "result_status": "stub",
                "metrics": {},
                "projection": {"ranking_grade_ready": False},
            },
            {
                "result_status": "executed",
                "metrics": {
                    "time_to_convergence_s": 1.0,
                    "energy_to_convergence_j": 3.0,
                    "bytes_moved_to_convergence": 3.0,
                    "fallback_ratio": 0.0,
                    "spill_ratio": 0.0,
                },
                "projection": {"ranking_grade_ready": True},
                "design_validation": dict(VALID_EXECUTABLE_VALIDATION),
            },
        ]

        summary = result_analysis.summarize_results(rows)
        ranked = [row for row in summary["rows"] if row["promotion_state"] == "promotion-eligible"]
        unranked = [row for row in summary["rows"] if row["promotion_state"] != "promotion-eligible"]

        self.assertEqual([row["screening_rank"] for row in ranked], [2, 1])
        self.assertEqual({row["pareto_membership"] for row in ranked}, {"screening_candidate"})
        self.assertEqual([row["screening_rank"] for row in unranked], [None])
        self.assertEqual({row["pareto_membership"] for row in unranked}, {"not_evaluated"})

    def test_result_analysis_never_promotes_non_executable_rows(self) -> None:
        result_analysis = load_unified_dse_module("result_analysis")
        metrics = {
            "time_to_convergence_s": 1.0,
            "energy_to_convergence_j": 2.0,
            "bytes_moved_to_convergence": 3.0,
            "fallback_ratio": 0.0,
            "spill_ratio": 0.0,
        }
        rows = [
            {
                "result_status": "executed",
                "metrics": dict(metrics),
                "projection": {"ranking_grade_ready": True},
                "design_validation": {
                    "validity_class": "invalid",
                    "claim_ceiling": "descriptor_only",
                    "missing_evidence": ["device_diag_engine"],
                    "promotion_blockers": ["device_diag_engine_missing"],
                    "reasons": ["aggressive_device_requires_device_diag_engine"],
                },
            },
            {
                "result_status": "executed",
                "metrics": dict(metrics),
                "projection": {"ranking_grade_ready": True},
                "design_validation": {
                    "validity_class": "projection_only",
                    "claim_ceiling": "descriptor_only",
                    "missing_evidence": ["backend_executor_for_projection_family"],
                    "promotion_blockers": ["projection_family_not_backend_executable"],
                    "reasons": ["projection_only_family:F4"],
                },
            },
            {
                "result_status": "executed",
                "metrics": dict(metrics),
                "projection": {"ranking_grade_ready": True},
            },
        ]

        summary = result_analysis.summarize_results(rows)

        self.assertEqual(summary["promotion_state_counts"]["promotion-eligible"], 0)
        self.assertEqual({row["promotion_state"] for row in summary["rows"]}, {"explain-only"})
        self.assertEqual([row["screening_rank"] for row in summary["rows"]], [None, None, None])
        self.assertEqual(
            {row["pareto_membership"] for row in summary["rows"]},
            {"not_evaluated"},
        )

    def test_non_numeric_required_metrics_are_not_promotion_eligible(self) -> None:
        result_analysis = load_unified_dse_module("result_analysis")
        rows = [
            {
                "result_status": "executed",
                "metrics": {
                    "time_to_convergence_s": "n/a",
                    "energy_to_convergence_j": 2.0,
                    "bytes_moved_to_convergence": 3.0,
                    "fallback_ratio": 0.0,
                    "spill_ratio": 0.0,
                },
                "projection": {"ranking_grade_ready": True},
                "design_validation": dict(VALID_EXECUTABLE_VALIDATION),
            }
        ]

        summary = result_analysis.summarize_results(rows)
        row = summary["rows"][0]

        self.assertEqual(row["promotion_state"], "explain-only")
        self.assertIsNone(row["screening_rank"])
        self.assertEqual(row["pareto_membership"], "not_evaluated")
        self.assertEqual(row["shortlist_reason"], "insufficient_metrics_for_shortlist")

    def test_multi_fidelity_plan_records_selected_unselected_and_blocked(self) -> None:
        active_multifidelity = load_unified_dse_module("active_multifidelity")
        rows = [
            {
                "promotion_state": "promotion-eligible",
                "screening_rank": 1,
                "design_point": {"family": "F1", "diag_policy": "cpu_only"},
                "design_validation": {"validity_class": "valid_executable"},
                "systemc_feedback_contract": {"candidate_id": "c1"},
            },
            {
                "promotion_state": "promotion-eligible",
                "screening_rank": 2,
                "design_point": {"family": "F2", "diag_policy": "cpu_only"},
                "design_validation": {"validity_class": "valid_executable"},
                "systemc_feedback_contract": {"candidate_id": "c2"},
            },
            {
                "promotion_state": "explain-only",
                "design_point": {"family": "F4", "diag_policy": "cpu_only"},
                "design_validation": {"validity_class": "projection_only", "promotion_blockers": ["projection"]},
                "systemc_feedback_contract": {"candidate_id": "c3"},
            },
        ]

        plan = active_multifidelity.build_multi_fidelity_plan(
            rows,
            policy=active_multifidelity.SHORTLIST_TOP_FAST_UNCERTAIN_DIVERSE,
            shortlist_size=1,
        )

        self.assertEqual(plan["schema_version"], "multi_fidelity_plan_v0")
        self.assertEqual(plan["selected_count"], 1)
        self.assertEqual(plan["selected_candidates"][0]["candidate_id"], "c1")
        self.assertEqual(plan["unselected_valid_candidate_count"], 1)
        self.assertEqual(plan["blocked_candidate_count"], 1)

    def test_residual_calibration_metadata_uses_evidence_ir(self) -> None:
        calibration_engine = load_unified_dse_module("calibration_engine")
        rows = [
            {
                "systemc_feedback_contract": {"candidate_id": "c1"},
                "metrics": {"time_to_convergence_s": 2.0},
                "source_kind": "fast_model_screening",
            }
        ]
        evidence = [
            {
                "schema_version": "evidence_ir_v0",
                "candidate_id": "c1",
                "metrics": {"time_to_convergence_s": 4.0},
            }
        ]

        metadata = calibration_engine.fit_residual_calibration(rows, evidence)
        updated = calibration_engine.apply_calibration_metadata_to_rows(rows, metadata)

        self.assertEqual(metadata["calibration_data_count"], 1)
        self.assertEqual(metadata["alpha_family"], 2.0)
        self.assertEqual(updated[0]["ranking_claim_ceiling"], "fast_model_calibrated_screening")
        self.assertEqual(updated[0]["calibrated_metrics"]["time_to_convergence_s"], 4.0)

    def test_shortlist_policy_seeds_one_candidate_per_family_before_rank_fill(self) -> None:
        active_multifidelity = load_unified_dse_module("active_multifidelity")
        rows = []
        for index, family in enumerate(("F3", "F3", "F3", "F2", "F1"), start=1):
            rows.append(
                {
                    "promotion_state": "promotion-eligible",
                    "screening_rank": index,
                    "design_point": {"family": family},
                    "design_validation": {"validity_class": "valid_executable"},
                }
            )

        selected = active_multifidelity.apply_shortlist_policy(
            rows,
            policy=active_multifidelity.SHORTLIST_TOP_FAST_UNCERTAIN_DIVERSE,
            shortlist_size=4,
        )
        shortlisted = sorted(
            (row for row in selected if row["shortlisted_for_backend"]),
            key=lambda row: row["shortlist_order"],
        )

        self.assertEqual([row["design_point"]["family"] for row in shortlisted], ["F3", "F2", "F1", "F3"])
        self.assertEqual(
            [row["shortlist_reason"] for row in shortlisted],
            ["diverse_family_seed", "diverse_family_seed", "diverse_family_seed", "rank_fill"],
        )

    def test_shortlist_policy_with_size_below_family_count_uses_ranked_distinct_families(self) -> None:
        active_multifidelity = load_unified_dse_module("active_multifidelity")
        rows = [
            {
                "promotion_state": "promotion-eligible",
                "screening_rank": rank,
                "design_point": {"family": family},
                "design_validation": {"validity_class": "valid_executable"},
            }
            for rank, family in ((1, "F2"), (2, "F1"), (3, "F3"))
        ]

        selected = active_multifidelity.apply_shortlist_policy(
            rows,
            policy=active_multifidelity.SHORTLIST_TOP_FAST_UNCERTAIN_DIVERSE,
            shortlist_size=2,
        )
        shortlisted = [row for row in selected if row["shortlisted_for_backend"]]

        self.assertEqual([row["design_point"]["family"] for row in shortlisted], ["F2", "F1"])


if __name__ == "__main__":
    unittest.main()
