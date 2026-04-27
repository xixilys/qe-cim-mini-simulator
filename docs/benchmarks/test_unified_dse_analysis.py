from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any


PACKAGE_DIR = Path(__file__).with_name("unified_dse")
FIXTURE_DIR = Path(__file__).with_name("testdata") / "unified_dse"
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
        feedback = json.loads((FIXTURE_DIR / "minimal_calibration.json").read_text(encoding="utf-8"))
        feedback["source_kind"] = "trace_calibrated_proxy"
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
            },
        ]

        summary = result_analysis.summarize_results(rows)
        allowed = {"reject", "explain-only", "promotion-eligible"}

        self.assertEqual(set(result_analysis.PROMOTION_STATES), allowed)
        self.assertEqual(set(summary["promotion_state_counts"]), allowed)
        self.assertEqual({row["promotion_state"] for row in summary["rows"]}, allowed)
        with self.assertRaisesRegex(ValueError, "promotion state"):
            result_analysis.validate_promotion_state("winner")


if __name__ == "__main__":
    unittest.main()
