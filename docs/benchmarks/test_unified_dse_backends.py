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


def make_workload(interfaces: Any) -> Any:
    payload = json.loads((FIXTURE_DIR / "minimal_workload.json").read_text(encoding="utf-8"))
    return interfaces.WorkloadDescriptor.from_dict(payload)


def make_design_point(interfaces: Any) -> Any:
    return interfaces.DesignPoint.from_dict(
        {
            "family": "F4",
            "diag_policy": "device_first_fallback",
            "offload_scope": "balanced",
            "resident_policy": "fit_first",
            "partition_strategy": "operator_build_fused__diag__refresh",
        }
    )


class UnifiedDseBackendTests(unittest.TestCase):
    def test_fast_model_stub_result_remains_evidence_only(self) -> None:
        interfaces = load_unified_dse_module("interfaces")
        fast_model = load_unified_dse_module("fast_model")
        backend = fast_model.FastModelBackend(source_kind="stub")

        result = backend.evaluate(make_workload(interfaces), make_design_point(interfaces))
        payload = result.to_dict()

        self.assertEqual(payload["backend"], "fast_model")
        self.assertEqual(payload["source_kind"], "stub")
        self.assertEqual(payload["authority_scope"], "supporting_evidence_only")
        self.assertIsNone(payload.get("final_public_family_winner"))

    def test_systemc_dry_run_does_not_execute_subprocess(self) -> None:
        interfaces = load_unified_dse_module("interfaces")
        systemc_backend = load_unified_dse_module("systemc_backend")
        backend = systemc_backend.SystemCBackend(
            model_path=Path("/definitely/not/a/qe_band_solver_model"),
            dry_run=True,
        )
        original_run = systemc_backend.subprocess.run

        def forbidden_run(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("SystemC dry-run must not call subprocess.run")

        systemc_backend.subprocess.run = forbidden_run
        try:
            result = backend.evaluate(make_workload(interfaces), make_design_point(interfaces))
        finally:
            systemc_backend.subprocess.run = original_run

        payload = result.to_dict()
        self.assertEqual(payload["backend"], "systemc")
        self.assertEqual(payload["result_status"], "dry_run")
        self.assertEqual(payload["source_kind"], "stub")
        self.assertFalse(payload["backend_observability"]["executed"])
        self.assertEqual(payload["authority_scope"], "supporting_evidence_only")

    def test_systemc_requires_explicit_opt_in_before_subprocess_execution(self) -> None:
        interfaces = load_unified_dse_module("interfaces")
        systemc_backend = load_unified_dse_module("systemc_backend")
        backend = systemc_backend.SystemCBackend(
            model_path=Path("/definitely/not/a/qe_band_solver_model"),
            dry_run=False,
        )
        original_run = systemc_backend.subprocess.run

        def forbidden_run(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("SystemC execution without explicit opt-in must not call subprocess.run")

        systemc_backend.subprocess.run = forbidden_run
        try:
            with self.assertRaisesRegex(ValueError, "explicit opt-in"):
                backend.evaluate(make_workload(interfaces), make_design_point(interfaces))
        finally:
            systemc_backend.subprocess.run = original_run

    def test_systemc_executed_path_uses_timed_proxy_and_nonzero_is_model_error(self) -> None:
        interfaces = load_unified_dse_module("interfaces")
        systemc_backend = load_unified_dse_module("systemc_backend")
        backend = systemc_backend.SystemCBackend(
            model_path=Path("/fake/qe_band_solver_model"),
            dry_run=False,
            allow_execute=True,
        )
        original_run = systemc_backend.subprocess.run

        class FakeCompleted:
            returncode = 7

        def fake_run(*args: Any, **kwargs: Any) -> FakeCompleted:
            return FakeCompleted()

        systemc_backend.subprocess.run = fake_run
        try:
            result = backend.evaluate(make_workload(interfaces), make_design_point(interfaces))
        finally:
            systemc_backend.subprocess.run = original_run

        payload = result.to_dict()
        self.assertEqual(payload["backend"], "systemc")
        self.assertEqual(payload["source_kind"], "timed_functional_proxy")
        self.assertEqual(payload["result_status"], "model_error")
        self.assertEqual(payload["backend_observability"]["returncode"], 7)
        self.assertTrue(payload["backend_observability"]["executed"])
        self.assertEqual(payload["authority_scope"], "supporting_evidence_only")

    def test_implementation_backend_returns_only_stub_or_reserved_status(self) -> None:
        interfaces = load_unified_dse_module("interfaces")
        implementation_backend = load_unified_dse_module("implementation_backend")
        backend = implementation_backend.ImplementationBackend()

        result = backend.evaluate(make_workload(interfaces), make_design_point(interfaces))
        payload = result.to_dict()

        self.assertEqual(payload["backend"], "implementation")
        self.assertIn(payload["result_status"], {"stub", "reserved"})
        self.assertEqual(payload["source_kind"], "stub")
        self.assertEqual(payload["metrics"], {})
        self.assertEqual(payload["authority_scope"], "supporting_evidence_only")
        self.assertFalse(payload["claim_bearing"])
        self.assertIn("implementation_backend_reserved", payload["stub_reason"])


if __name__ == "__main__":
    unittest.main()
