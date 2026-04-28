from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = ROOT / "docs/benchmarks/unified_dse"
FIXTURE_DIR = ROOT / "docs/benchmarks/testdata/unified_dse"


def load_unified_dse_module(module_name: str) -> ModuleType:
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


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def minimal_report() -> dict[str, Any]:
    return load_fixture("backend_execution_report_minimal.json")


class BackendExecutionContractTests(unittest.TestCase):
    def test_valid_minimal_request_loads(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        payload = load_fixture("backend_execution_request_minimal.json")

        request = backend_execution.BackendExecutionRequest.from_dict(payload)

        self.assertEqual(request.to_dict(), payload)
        self.assertEqual(request.expected_report_schema, "backend_execution_report_v0")
        self.assertEqual(request.requested_fidelity, "B1")
        self.assertIn("qe", request.domain_extension)

    def test_valid_minimal_report_loads(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        payload = minimal_report()

        report = backend_execution.BackendExecutionReport.from_dict(payload)

        self.assertEqual(report.to_dict(), payload)
        self.assertEqual(report.execution_status, "refused")
        self.assertEqual(report.claim_ceiling, "systemc_standalone_proxy_only")

    def test_valid_b3_smoke_result_fixture_loads(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        path = ROOT / "docs/benchmarks/results/backend_execution_report_gem5_systemc_smoke_v0.json"

        report = backend_execution.load_backend_execution_report(path)

        self.assertEqual(report.execution_status, "executed")
        self.assertEqual(report.fidelity, "gem5_systemc_smoke")
        self.assertEqual(report.claim_ceiling, "gem5_systemc_smoke_only")
        self.assertFalse(report.correctness_gate["workload_equivalent_claim"])

    def test_missing_required_fields_fail_with_clear_errors(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        request_payload = load_fixture("backend_execution_request_minimal.json")
        report_payload = minimal_report()
        del request_payload["candidate_identity"]
        del report_payload["control_path"]

        with self.assertRaisesRegex(ValueError, "missing field: candidate_identity"):
            backend_execution.BackendExecutionRequest.from_dict(request_payload)
        with self.assertRaisesRegex(ValueError, "missing field: control_path"):
            backend_execution.BackendExecutionReport.from_dict(report_payload)

    def test_unsupported_execution_mode_fails(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        payload = load_fixture("backend_execution_request_minimal.json")
        payload["execution_mode"] = "unsupported_backend_mode"

        with self.assertRaisesRegex(ValueError, "execution_mode"):
            backend_execution.BackendExecutionRequest.from_dict(payload)

    def test_fidelity_claim_ceiling_mismatch_fails(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        payload = minimal_report()
        payload["claim_ceiling"] = "systemc_timed_functional_proxy_only"

        with self.assertRaisesRegex(ValueError, "claim_ceiling"):
            backend_execution.BackendExecutionReport.from_dict(payload)

    def test_stage_b1_to_b4_fidelity_mode_and_claim_ceiling_mappings(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        expected = {
            "systemc_standalone": ("B1", "systemc_standalone_proxy_only"),
            "systemc_timed_functional": ("B2", "systemc_timed_functional_proxy_only"),
            "gem5_systemc_smoke": ("B3", "gem5_systemc_smoke_only"),
            "gem5_systemc_timed_proxy": ("B4", "gem5_systemc_timed_proxy_only"),
        }
        for mode, (stage, ceiling) in expected.items():
            with self.subTest(mode=mode):
                request = load_fixture("backend_execution_request_minimal.json")
                request.update({"requested_fidelity": stage, "execution_mode": mode})
                backend_execution.BackendExecutionRequest.from_dict(request)

                report = minimal_report()
                report.update({"fidelity": mode, "claim_ceiling": ceiling})
                backend_execution.BackendExecutionReport.from_dict(report)

    def test_overclaim_rejection_for_workload_domain_and_implementation_claims(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        payload = minimal_report()
        payload["correctness_gate"]["workload_equivalent_claim"] = True
        with self.assertRaisesRegex(ValueError, "workload_equivalent_claim"):
            backend_execution.BackendExecutionReport.from_dict(payload)

        payload = minimal_report()
        payload["correctness_gate"]["domain_equivalence_claim"] = True
        with self.assertRaisesRegex(ValueError, "domain_equivalence_claim"):
            backend_execution.BackendExecutionReport.from_dict(payload)

        for claim_text in (
            "board_measured_claim",
            "rtl_simulation_claim",
            "hls_synthesis_claim",
            "asic_physical_claim",
            "cycle_accurate_rtl_claim",
        ):
            payload = minimal_report()
            payload["non_claims"].append(claim_text)
            with self.subTest(claim_text=claim_text):
                with self.assertRaisesRegex(ValueError, "must not claim"):
                    backend_execution.BackendExecutionReport.from_dict(payload)

    def test_hidden_nested_equivalence_claims_are_rejected(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")

        payload = load_fixture("backend_execution_request_minimal.json")
        payload["domain_extension"]["qe"]["qe_equivalent_scf_claim"] = True
        with self.assertRaisesRegex(ValueError, "qe_equivalent_scf_claim"):
            backend_execution.BackendExecutionRequest.from_dict(payload)

        payload = load_fixture("backend_execution_request_minimal.json")
        payload["domain_extension"]["qe"]["nested"] = {
            "workload_equivalent_claim": True,
        }
        with self.assertRaisesRegex(ValueError, "workload_equivalent_claim"):
            backend_execution.BackendExecutionRequest.from_dict(payload)

        payload = minimal_report()
        payload["artifact_refs"]["hidden_domain_claim"] = {
            "domain_equivalence_claim": True,
        }
        with self.assertRaisesRegex(ValueError, "domain_equivalence_claim"):
            backend_execution.BackendExecutionReport.from_dict(payload)

        payload = minimal_report()
        payload["artifact_refs"]["hidden_text_claim"] = "QE-equivalent SCF passed"
        with self.assertRaisesRegex(ValueError, "QE/workload/domain equivalence"):
            backend_execution.BackendExecutionReport.from_dict(payload)

        payload = minimal_report()
        payload["notes"] = ["QE-equivalence passed"]
        with self.assertRaisesRegex(ValueError, "QE/workload/domain equivalence"):
            backend_execution.BackendExecutionReport.from_dict(payload)

        payload = minimal_report()
        payload["control_path"]["qe_equivalence_status"] = "proven"
        with self.assertRaisesRegex(ValueError, "qe_equivalence_status"):
            backend_execution.BackendExecutionReport.from_dict(payload)

        payload = minimal_report()
        payload["notes"] = ["domain equivalent passed"]
        with self.assertRaisesRegex(ValueError, "QE/workload/domain equivalence"):
            backend_execution.BackendExecutionReport.from_dict(payload)

        payload = minimal_report()
        payload["notes"] = ["domain-equivalence passed"]
        with self.assertRaisesRegex(ValueError, "QE/workload/domain equivalence"):
            backend_execution.BackendExecutionReport.from_dict(payload)

    def test_hidden_nested_implementation_claim_text_is_rejected(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")

        payload = minimal_report()
        payload["artifact_refs"]["hidden"] = {"note": "cycle_accurate_rtl_result_available"}
        with self.assertRaisesRegex(ValueError, "must not claim"):
            backend_execution.BackendExecutionReport.from_dict(payload)

        payload = minimal_report()
        payload["artifact_refs"]["no_rtl_hls_board_or_asic_implementation_claim"] = "not_claimed"
        backend_execution.BackendExecutionReport.from_dict(payload)

    def test_qe_extension_is_accepted_only_under_domain_extension_qe(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        payload = load_fixture("backend_execution_request_minimal.json")
        payload["domain_extension"]["qe"]["pseudopotential_family"] = "uspp"
        backend_execution.BackendExecutionRequest.from_dict(payload)

        payload = load_fixture("backend_execution_request_minimal.json")
        payload["qe_case_id"] = "top_level_not_allowed"
        with self.assertRaisesRegex(ValueError, "domain_extension.qe"):
            backend_execution.BackendExecutionRequest.from_dict(payload)

    def test_report_status_vocabulary_excludes_not_executed_and_blocked(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        for status in ("executed", "partial", "failed", "refused"):
            payload = minimal_report()
            payload["execution_status"] = status
            with self.subTest(status=status):
                backend_execution.BackendExecutionReport.from_dict(payload)

        for status in ("not_executed", "blocked"):
            payload = minimal_report()
            payload["execution_status"] = status
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "execution_status"):
                    backend_execution.BackendExecutionReport.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
