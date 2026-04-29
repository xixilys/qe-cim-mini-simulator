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


def make_feedback(candidate_id: str, *, duplicate: bool = False) -> dict[str, Any]:
    row = {
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
    rows = [dict(row)]
    if duplicate:
        rows.append(dict(row))
    return {
        "schema_version": "qe_dse_systemc_feedback_artifact_v0",
        "execution_status": "executed",
        "source_kind": "timed_functional_proxy",
        "claim_ceiling": "timed_functional_proxy_feedback_only",
        "backend_class": "systemc_timed_functional_proxy",
        "report_schema_version": "backend_execution_report_v0",
        "rows": rows,
    }


def make_feedback_target_row(
    *,
    family: str = "F1",
    diag_policy: str = "cpu_only",
) -> dict[str, Any]:
    workload = json.loads((FIXTURE_DIR / "minimal_workload.json").read_text(encoding="utf-8"))
    row = {
        "workload": workload,
        "design_point": {
            "family": family,
            "diag_policy": diag_policy,
            "offload_scope": "single_hotpath",
            "resident_policy": "fit_first",
            "partition_strategy": "single_hotpath_partition",
        },
        "backend": "fast_model",
        "result_status": "stub",
        "source_kind": "stub",
        "metrics": {},
        "authority_scope": "supporting_evidence_only",
        "promotion_state": "explain-only",
        "final_public_family_winner": None,
    }
    stage_a_contracts = load_unified_dse_module("stage_a_contracts")
    return stage_a_contracts.attach_stage_a_contracts(row)


def feedback_candidate_id(row: dict[str, Any]) -> str:
    return str(row["systemc_feedback_contract"]["candidate_id"])


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
        self.assertEqual(payload["systemc_feedback_contract"]["status"], "planned_not_executed")
        self.assertEqual(payload["systemc_feedback_contract"]["backend_class"], "systemc_timed_functional_proxy")
        self.assertIn("candidate_config_ref", payload["systemc_feedback_contract"])
        self.assertFalse(payload["systemc_feedback_contract"]["subprocess_invoked"])
        self.assertEqual(payload["gem5_handoff_contract"]["status"], "planned_for_stage_b")
        self.assertEqual(payload["gem5_handoff_contract"]["handoff_status"], "planned")
        self.assertIn("input_descriptor_ref", payload["gem5_handoff_contract"])
        self.assertFalse(payload["qe_anchor_refs"]["qe_equivalent_scf_claim"])
        self.assertIn("case_id", payload["qe_anchor_refs"])

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
        self.assertEqual(payload["systemc_feedback_contract"]["execution_status"], "not_executed")
        self.assertEqual(
            payload["systemc_feedback_contract"]["claim_ceiling"],
            "timed_functional_proxy_contract_only",
        )
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
        self.assertEqual(payload["systemc_feedback_contract"]["execution_status"], "executed")
        self.assertTrue(payload["systemc_feedback_contract"]["subprocess_invoked"])
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

    def test_feedback_join_rejects_unknown_duplicate_and_non_executable_candidates(self) -> None:
        systemc_feedback_adapter = load_unified_dse_module("systemc_feedback_adapter")
        valid = make_feedback_target_row()
        invalid = make_feedback_target_row(diag_policy="aggressive_device")
        projection = make_feedback_target_row(family="F4")

        with self.assertRaisesRegex(ValueError, "feedback contains unknown candidate IDs"):
            systemc_feedback_adapter.apply_systemc_feedback(
                [valid],
                make_feedback("unknown_candidate"),
            )
        with self.assertRaisesRegex(ValueError, "duplicate feedback candidate ID"):
            systemc_feedback_adapter.apply_systemc_feedback(
                [valid],
                make_feedback(feedback_candidate_id(valid), duplicate=True),
            )
        with self.assertRaisesRegex(ValueError, "feedback targets non-executable candidate"):
            systemc_feedback_adapter.apply_systemc_feedback(
                [invalid],
                make_feedback(feedback_candidate_id(invalid)),
            )
        with self.assertRaisesRegex(ValueError, "feedback targets non-executable candidate"):
            systemc_feedback_adapter.apply_systemc_feedback(
                [projection],
                make_feedback(feedback_candidate_id(projection)),
            )

    def test_feedback_join_rejects_missing_or_malformed_candidate_descriptor(self) -> None:
        systemc_feedback_adapter = load_unified_dse_module("systemc_feedback_adapter")
        missing_descriptor = make_feedback_target_row()
        descriptor_id = feedback_candidate_id(missing_descriptor)
        del missing_descriptor["candidate_descriptor"]

        with self.assertRaisesRegex(ValueError, "feedback target missing candidate_descriptor"):
            systemc_feedback_adapter.apply_systemc_feedback(
                [missing_descriptor],
                make_feedback(descriptor_id),
            )

        missing_descriptor_validation = make_feedback_target_row()
        validation_id = feedback_candidate_id(missing_descriptor_validation)
        del missing_descriptor_validation["candidate_descriptor"]["design_validation"]

        with self.assertRaisesRegex(
            ValueError,
            "feedback target missing candidate_descriptor.design_validation",
        ):
            systemc_feedback_adapter.apply_systemc_feedback(
                [missing_descriptor_validation],
                make_feedback(validation_id),
            )

    def test_zero_row_feedback_has_non_ingest_summary(self) -> None:
        systemc_feedback_adapter = load_unified_dse_module("systemc_feedback_adapter")
        valid = make_feedback_target_row()
        feedback = make_feedback(feedback_candidate_id(valid))
        feedback["rows"] = []

        summary = systemc_feedback_adapter.feedback_ingest_summary([valid], feedback)
        updated = systemc_feedback_adapter.apply_systemc_feedback([valid], feedback)

        self.assertEqual(
            summary["systemc_feedback_ingest_status"],
            "artifact_validated_no_rows",
        )
        self.assertEqual(summary["systemc_feedback_candidate_count"], 0)
        self.assertEqual(summary["systemc_feedback_matched_candidate_count"], 0)
        self.assertEqual(summary["systemc_feedback_unmatched_candidate_ids"], [])
        self.assertEqual(updated, [valid])


if __name__ == "__main__":
    unittest.main()
