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

DESIGN_POINT_KEYS = (
    "family",
    "diag_policy",
    "offload_scope",
    "resident_policy",
    "partition_strategy",
)
WORKLOAD_IDENTITY_KEYS = (
    "workload_id",
    "workload_group_id",
    "qe_tolerance_schema_id",
    "accounting_boundary_id",
    "fairness_policy_id",
    "power_boundary_id",
    "observability_contract_id",
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


class UnifiedDseInterfacesTests(unittest.TestCase):
    def test_design_point_dataclass_round_trips_as_authority_keys_only(self) -> None:
        interfaces = load_unified_dse_module("interfaces")
        payload = {
            "family": "F2",
            "diag_policy": "device_first_fallback",
            "offload_scope": "balanced",
            "resident_policy": "fit_first",
            "partition_strategy": "operator__build__diag__refresh",
        }

        point = interfaces.DesignPoint.from_dict(payload)

        self.assertEqual(tuple(interfaces.DESIGN_POINT_IDENTITY_KEYS), DESIGN_POINT_KEYS)
        self.assertEqual(point.to_dict(), payload)
        self.assertEqual(interfaces.DesignPoint.from_dict(point.to_dict()), point)
        self.assertNotIn("workload_id", point.to_dict())

    def test_workload_descriptor_dataclass_round_trips_identity_and_signature_fields(self) -> None:
        interfaces = load_unified_dse_module("interfaces")
        payload = json.loads((FIXTURE_DIR / "minimal_workload.json").read_text(encoding="utf-8"))

        workload = interfaces.WorkloadDescriptor.from_dict(payload)
        round_trip = workload.to_dict()

        self.assertEqual(tuple(interfaces.WORKLOAD_IDENTITY_KEYS), WORKLOAD_IDENTITY_KEYS)
        for key in WORKLOAD_IDENTITY_KEYS:
            self.assertEqual(round_trip[key], payload[key])
        self.assertEqual(round_trip["signature_id"], payload["signature_id"])
        self.assertEqual(round_trip["solver_path_class"], "generalized_overlap")
        self.assertEqual(interfaces.WorkloadDescriptor.from_dict(round_trip), workload)

    def test_evaluation_result_dataclass_round_trips_without_decision_authority(self) -> None:
        interfaces = load_unified_dse_module("interfaces")
        workload = json.loads((FIXTURE_DIR / "minimal_workload.json").read_text(encoding="utf-8"))
        design_point = {
            "family": "F4",
            "diag_policy": "device_first_fallback",
            "offload_scope": "balanced",
            "resident_policy": "fit_first",
            "partition_strategy": "operator_build_fused__diag__refresh",
        }
        payload = {
            "workload": workload,
            "design_point": design_point,
            "backend": "fast_model",
            "result_status": "stub",
            "source_kind": "stub",
            "metrics": {},
            "authority_scope": "supporting_evidence_only",
            "promotion_state": "explain-only",
            "final_public_family_winner": None,
        }

        result = interfaces.EvaluationResult.from_dict(payload)

        self.assertEqual(result.to_dict(), payload)
        self.assertEqual(interfaces.EvaluationResult.from_dict(result.to_dict()), result)
        self.assertEqual(result.to_dict()["authority_scope"], "supporting_evidence_only")
        self.assertIsNone(result.to_dict()["final_public_family_winner"])


if __name__ == "__main__":
    unittest.main()
