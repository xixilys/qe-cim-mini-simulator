from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).with_name("unified_dse")
FIXTURE_DIR = Path(__file__).with_name("testdata") / "unified_dse"
DESIGN_SPACE_PATH = ROOT / "docs/benchmarks/qe_architecture_family_design_space_spec_v0.json"


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


class UnifiedDseFrontendTests(unittest.TestCase):
    def test_design_space_spec_loads_canonical_axes_and_authority(self) -> None:
        architecture_space = load_unified_dse_module("architecture_space")

        spec = architecture_space.load_design_space_spec(DESIGN_SPACE_PATH)

        self.assertEqual(spec.schema_version, "qe_architecture_family_design_space_spec_v0")
        self.assertEqual(spec.design_space_id, "qe_complete_architecture_family_dse_framework_v0")
        self.assertEqual(spec.authority_stage["claim_posture"], "evidence_only")
        self.assertEqual(spec.authority_stage["decision_authority"], "adjudicator_memo_only")
        self.assertEqual(set(spec.design_axes["family"]), {"F1", "F2", "F3", "F4", "F5", "custom"})

    def test_unknown_family_is_rejected_before_backend_dispatch(self) -> None:
        architecture_space = load_unified_dse_module("architecture_space")
        spec = architecture_space.load_design_space_spec(DESIGN_SPACE_PATH)

        with self.assertRaisesRegex(ValueError, "unknown architecture family"):
            architecture_space.make_design_point(
                spec,
                family="F9",
                diag_policy="device_first_fallback",
                offload_scope="balanced",
                resident_policy="fit_first",
                partition_strategy="operator__build__diag__refresh",
            )

    def test_f4_f5_and_custom_are_projection_scaffolds_not_executor_support(self) -> None:
        architecture_space = load_unified_dse_module("architecture_space")
        spec = architecture_space.load_design_space_spec(DESIGN_SPACE_PATH)

        for family in ("F4", "F5", "custom"):
            with self.subTest(family=family):
                support = architecture_space.family_support_status(spec, family)
                self.assertEqual(support.family, family)
                self.assertEqual(support.runtime_support_status, "projection_scaffold")
                self.assertEqual(support.stage_a_status, "projection_only")
                self.assertFalse(support.runtime_executor_backed)
                self.assertEqual(support.runtime_projection_family, "F2")

    def test_workload_frontend_loads_fixture_without_mutating_identity_keys(self) -> None:
        workload_frontend = load_unified_dse_module("workload_frontend")

        workload = workload_frontend.load_workload_descriptor(FIXTURE_DIR / "minimal_workload.json")
        payload = workload.to_dict()

        self.assertEqual(payload["workload_id"], "si4_pbe_uspp_small")
        self.assertEqual(payload["workload_group_id"], "qe_next_stage_mainline")
        self.assertEqual(payload["fairness_policy_id"], "qe_cpu_gpu_fpga_fairness_v0")
        self.assertEqual(payload["power_boundary_id"], "whole_node_power_v0")
        self.assertEqual(payload["observability_contract_id"], "qe_simulator_board_observability_v0")


if __name__ == "__main__":
    unittest.main()
