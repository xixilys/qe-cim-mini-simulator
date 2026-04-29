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
        self.assertEqual(report.backend_class, "systemc_standalone_proxy")
        self.assertEqual(report.source_kind, "backend_runner_systemc")

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
                request["backend_capability_profile"] = {
                    "profile_id": "all_modes_unit",
                    "supports_systemc_standalone": True,
                    "supports_systemc_timed_functional": True,
                    "supports_gem5_smoke": True,
                    "supports_gem5_timed_proxy": True,
                    "supports_real_bridge": True,
                }
                backend_execution.BackendExecutionRequest.from_dict(request)

                report = minimal_report()
                report.update(
                    {
                        "fidelity": mode,
                        "claim_ceiling": ceiling,
                        "backend_class": backend_execution.MODE_TO_BACKEND_CLASS[mode],
                        "source_kind": backend_execution.MODE_TO_SOURCE_KIND[mode],
                    }
                )
                backend_execution.BackendExecutionReport.from_dict(report)

    def test_request_execution_gate_requires_valid_executable_candidate(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        payload = load_fixture("backend_execution_request_minimal.json")
        backend_execution.validate_backend_execution_request_for_execution(payload)

        payload = load_fixture("backend_execution_request_minimal.json")
        payload["candidate_identity"]["validity_class"] = "projection_only"
        with self.assertRaisesRegex(ValueError, "valid_executable"):
            backend_execution.validate_backend_execution_request_for_execution(payload)

        payload = load_fixture("backend_execution_request_minimal.json")
        del payload["candidate_identity"]["validity_class"]
        with self.assertRaisesRegex(ValueError, "valid_executable"):
            backend_execution.validate_backend_execution_request_for_execution(payload)

        payload = load_fixture("backend_execution_request_minimal.json")
        del payload["backend_capability_profile"]
        with self.assertRaisesRegex(ValueError, "backend_capability_profile"):
            backend_execution.validate_backend_execution_request_for_execution(payload)

        payload = load_fixture("backend_execution_request_minimal.json")
        del payload["metrics_contract"]
        with self.assertRaisesRegex(ValueError, "metrics_contract"):
            backend_execution.validate_backend_execution_request_for_execution(payload)

    def test_backend_capability_profile_rejects_unsupported_mode(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        payload = load_fixture("backend_execution_request_minimal.json")
        payload["backend_capability_profile"] = {
            "profile_id": "no_b1_support",
            "supports_systemc_standalone": False,
        }

        with self.assertRaisesRegex(ValueError, "does not support"):
            backend_execution.BackendExecutionRequest.from_dict(payload)

    def test_optional_request_extensions_must_be_mappings(self) -> None:
        backend_execution = load_unified_dse_module("backend_execution")
        payload = load_fixture("backend_execution_request_minimal.json")
        payload["metrics_contract"] = ["not", "a", "mapping"]

        with self.assertRaisesRegex(ValueError, "metrics_contract"):
            backend_execution.BackendExecutionRequest.from_dict(payload)

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

        payload = load_fixture("backend_execution_request_minimal.json")
        payload["domain_extension"]["qe"]["observability_contract_id"] = (
            "qe_simulator_board_observability_v0"
        )
        payload["domain_extension"]["qe"]["accounting_boundary_id"] = "scf_board_boundary_id_v0"
        payload["domain_extension"]["qe"]["power_boundary_id"] = "board_power_boundary_v0"
        backend_execution.BackendExecutionRequest.from_dict(payload)

        payload = minimal_report()
        payload["artifact_refs"]["hidden"] = {"note": "cycle_accurate_rtl_result_available"}
        with self.assertRaisesRegex(ValueError, "must not claim"):
            backend_execution.BackendExecutionReport.from_dict(payload)

        for key, value in (
            ("board_evidence_claim", "passed"),
            ("implementation_status", "RTL implementation passed"),
            ("hls_result", "available"),
            ("asic_evidence", "available"),
            ("timing_claim", "cycle-accurate result available"),
        ):
            payload = load_fixture("backend_execution_request_minimal.json")
            payload["domain_extension"]["qe"][key] = value
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "must not claim"):
                    backend_execution.BackendExecutionRequest.from_dict(payload)

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

    def test_domain_neutral_correctness_report_keeps_workload_claims_separate(self) -> None:
        correctness_report = load_unified_dse_module("correctness_report")
        payload = {
            "schema_version": "correctness_report_v0",
            "execution_status": "executed",
            "claim_ceiling": "correctness_report_reference_only",
            "report_id": "correctness_unit",
            "candidate_id": "candidate_generic",
            "workload_identity": {
                "workload_id": "generic_proxy",
                "domain": "synthetic",
                "adapter": "generic",
            },
            "tolerance_schema_id": "generic_proxy_tolerance_v0",
            "correctness_status": "baseline_missing",
            "workload_equivalent_claim": False,
            "compare_report": {"overall_pass": False},
            "evidence_refs": {"baseline": "missing"},
        }

        correctness_report.validate_correctness_report(payload)
        summary = correctness_report.summarize_correctness_report(payload)

        self.assertFalse(summary["workload_equivalent_claim"])
        self.assertEqual(summary["claim_ceiling"], "correctness_report_reference_only")

        payload = dict(payload)
        payload.update(
            {
                "claim_ceiling": "workload_equivalent_correctness_only",
                "correctness_status": "pass",
                "workload_equivalent_claim": True,
                "compare_report": {"overall_pass": True},
            }
        )
        correctness_report.validate_correctness_report(payload)

    def test_calibration_feedback_rejects_identity_updates(self) -> None:
        calibration_feedback = load_unified_dse_module("calibration_feedback")
        payload = {
            "schema_version": "calibration_feedback_v0",
            "feedback_id": "calibration_unit",
            "candidate_id": "candidate_generic",
            "calibration_status": "partial",
            "claim_ceiling": "calibration_feedback_only",
            "source_report_refs": {"backend": "backend_report.json"},
            "updated_parameters": {"host_wait_scale": 1.1},
            "residual_summary": {"status": "partial", "sample_count": 1},
            "evidence_refs": {},
        }

        calibration_feedback.validate_calibration_feedback(payload)
        summary = calibration_feedback.summarize_calibration_feedback(payload)

        self.assertEqual(summary["updated_parameter_count"], 1)
        payload["updated_parameters"] = {"workload_id": "must_not_change"}
        with self.assertRaisesRegex(ValueError, "identity key"):
            calibration_feedback.validate_calibration_feedback(payload)


if __name__ == "__main__":
    unittest.main()
