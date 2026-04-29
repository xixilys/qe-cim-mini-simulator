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
    "domain",
    "app_adapter",
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
        payload["case_id"] = "si4_case_001"
        payload["trace_ref"] = "traces/si4.csv"
        payload["correctness_anchor_ref"] = "gold/si4.json"

        workload = interfaces.WorkloadDescriptor.from_dict(payload)
        round_trip = workload.to_dict()

        self.assertEqual(tuple(interfaces.WORKLOAD_IDENTITY_KEYS), WORKLOAD_IDENTITY_KEYS)
        for key in WORKLOAD_IDENTITY_KEYS:
            if key in {"domain", "app_adapter"}:
                continue
            self.assertEqual(round_trip[key], payload[key])
        self.assertEqual(round_trip["domain"], "dft")
        self.assertEqual(round_trip["app_adapter"], "qe")
        self.assertEqual(round_trip["signature_id"], payload["signature_id"])
        self.assertEqual(round_trip["case_id"], "si4_case_001")
        self.assertEqual(round_trip["trace_ref"], "traces/si4.csv")
        self.assertEqual(round_trip["correctness_anchor_ref"], "gold/si4.json")
        self.assertEqual(round_trip["solver_path_class"], "generalized_overlap")
        self.assertEqual(interfaces.WorkloadDescriptor.from_dict(round_trip), workload)

    def test_generic_workload_descriptor_uses_defaults_without_qe_fields(self) -> None:
        interfaces = load_unified_dse_module("interfaces")
        payload = {
            "schema_version": "generic_trace_workload_v0",
            "workload_id": "generic_spmv_small",
            "domain": "sparse_linear_algebra",
            "app_adapter": "generic_trace",
            "dimension_n": 64,
            "dimension_m": 4,
        }

        workload = interfaces.WorkloadDescriptor.from_dict(payload)
        round_trip = workload.to_dict()

        self.assertEqual(round_trip["workload_id"], "generic_spmv_small")
        self.assertEqual(round_trip["qe_tolerance_schema_id"], "not_applicable")
        self.assertEqual(round_trip["pseudopotential_family"], "not_applicable")
        self.assertEqual(round_trip["domain"], "sparse_linear_algebra")
        self.assertEqual(round_trip["app_adapter"], "generic_trace")
        domain_contracts = load_unified_dse_module("domain_contracts")
        self.assertEqual(domain_contracts.domain_extension(round_trip), {})
        self.assertEqual(domain_contracts.qe_anchor_refs_compat(round_trip), {})

    def test_workload_identity_maps_frontend_adapters_to_backend_adapter_names(self) -> None:
        domain_contracts = load_unified_dse_module("domain_contracts")
        qe_payload = json.loads((FIXTURE_DIR / "minimal_workload.json").read_text(encoding="utf-8"))
        generic_payload = {
            "schema_version": "generic_trace_workload_v0",
            "workload_id": "generic_spmv_small",
            "domain": "sparse_linear_algebra",
            "app_adapter": "generic_trace",
        }
        abinit_payload = {
            "schema_version": "generic_trace_workload_v0",
            "workload_id": "abinit_like_trace",
            "domain": "dft",
            "app_adapter": "abinit_trace",
        }
        synthetic_payload = {
            "schema_version": "generic_trace_workload_v0",
            "workload_id": "gemm_128",
            "app_adapter": "synthetic_gemm",
            "kernel_type": "gemm",
        }

        self.assertEqual(domain_contracts.workload_identity(qe_payload)["adapter"], "qe")
        generic_identity = domain_contracts.workload_identity(generic_payload)
        self.assertEqual(generic_identity["adapter"], "generic")
        self.assertEqual(generic_identity["app_adapter"], "generic_trace")
        self.assertEqual(domain_contracts.workload_identity(abinit_payload)["adapter"], "generic")
        synthetic_identity = domain_contracts.workload_identity(synthetic_payload)
        self.assertEqual(synthetic_identity["adapter"], "synthetic")
        self.assertEqual(synthetic_identity["app_adapter"], "synthetic_gemm")

    def test_explicit_non_qe_dft_adapter_does_not_emit_qe_extension(self) -> None:
        interfaces = load_unified_dse_module("interfaces")
        payload = {
            "schema_version": "generic_trace_workload_v0",
            "workload_id": "dft_non_qe_small",
            "domain": "dft",
            "app_adapter": "abinit_trace",
            "dimension_n": 32,
            "dimension_m": 4,
        }

        workload = interfaces.WorkloadDescriptor.from_dict(payload)
        round_trip = workload.to_dict()

        self.assertEqual(round_trip["domain"], "dft")
        self.assertEqual(round_trip["app_adapter"], "abinit_trace")
        self.assertEqual(round_trip["qe_tolerance_schema_id"], "not_applicable")
        domain_contracts = load_unified_dse_module("domain_contracts")
        self.assertFalse(domain_contracts.is_qe_workload(round_trip))
        self.assertEqual(domain_contracts.domain_extension(round_trip), {})
        self.assertEqual(domain_contracts.qe_anchor_refs_compat(round_trip), {})

    def test_backend_execution_request_exposes_backend_runner_shape_without_overclaim(self) -> None:
        domain_contracts = load_unified_dse_module("domain_contracts")
        workload = json.loads((FIXTURE_DIR / "minimal_workload.json").read_text(encoding="utf-8"))
        design_point = {
            "family": "F2",
            "diag_policy": "cpu_only",
            "offload_scope": "balanced",
            "resident_policy": "fit_first",
            "partition_strategy": "operator__build__diag__refresh",
        }
        validation = {"validity_class": "valid_executable", "claim_ceiling": "descriptor_only"}

        for requested_fidelity in ("B1", "B2"):
            request = domain_contracts.build_backend_execution_request(
                candidate_id=f"candidate_{requested_fidelity}",
                workload=workload,
                design_point=design_point,
                architecture_template_id="template_F2_stage_a",
                target_class="fpga",
                backend_profile_id="stage_a_systemc_timed_functional_proxy",
                source_kind="stub",
                systemc_config_ref=f"systemc_configs/candidate_{requested_fidelity}.json",
                requested_fidelity=requested_fidelity,
                design_validation=validation,
            )

            self.assertEqual(request["schema_version"], "backend_execution_request_v0")
            self.assertEqual(request["workload_identity"]["adapter"], "qe")
            self.assertEqual(request["candidate_identity"]["validity_class"], "valid_executable")
            self.assertTrue(
                request["backend_capability_profile"]["supports_systemc_timed_functional"]
            )
            self.assertFalse(request["backend_capability_profile"]["supports_real_bridge"])
            required_groups = set(request["metrics_contract"]["required_groups"])
            for key in domain_contracts.BACKEND_METRICS_REQUIRED_GROUPS:
                self.assertIn(key, required_groups)
            self.assertEqual(request["claim_ceiling"], "descriptor_only")
            self.assertIn("not_systemc_executed", request["non_claims"])
            self.assertIn("not_qe_correctness_executed", request["non_claims"])

        projection_request = domain_contracts.build_backend_execution_request(
            candidate_id="projection_candidate",
            workload=workload,
            design_point={**design_point, "family": "F4"},
            architecture_template_id="template_F4_stage_a",
            target_class="fpga",
            backend_profile_id="stage_a_systemc_timed_functional_proxy",
            source_kind="stub",
            systemc_config_ref="systemc_configs/projection_candidate.json",
            design_validation={"validity_class": "projection_only"},
        )
        self.assertEqual(
            projection_request["candidate_identity"]["validity_class"],
            "projection_only",
        )

    def test_domain_contracts_validate_backend_execution_report_shape(self) -> None:
        domain_contracts = load_unified_dse_module("domain_contracts")
        payload = {
            "schema_version": "backend_execution_report_v0",
            "candidate_id": "candidate",
            "backend_class": "systemc_timed_functional_proxy",
            "source_kind": "timed_functional_proxy",
            "execution_status": "executed",
            "fidelity": "systemc_timed_functional",
            "claim_ceiling": "systemc_timed_functional_proxy_only",
            "metrics": {},
            "correctness_gate": {},
            "non_claims": ["not_qe_equivalent_scf"],
            "artifact_refs": {},
            "backend_extra": "allowed",
        }

        domain_contracts.validate_backend_execution_report(payload)
        for status in ("partial", "refused"):
            with self.subTest(execution_status=status):
                alternate = dict(payload)
                alternate["execution_status"] = status
                if status == "refused":
                    alternate["fidelity"] = "descriptor_only"
                    alternate["claim_ceiling"] = "descriptor_only"
                    alternate["non_claims"] = [
                        "not_backend_executed",
                        "not_qe_correctness_claim",
                    ]
                domain_contracts.validate_backend_execution_report(alternate)
        bad = dict(payload)
        bad["schema_version"] = "future_schema"
        with self.assertRaisesRegex(ValueError, "schema_version"):
            domain_contracts.validate_backend_execution_report(bad)

    def test_domain_neutral_ir_helpers_round_trip(self) -> None:
        domain_contracts = load_unified_dse_module("domain_contracts")
        app_graph = domain_contracts.ApplicationGraphIR.from_dict(
            {
                "app_id": "generic_app",
                "domain": "generic",
                "nodes": [{"node_id": "kernel", "op_type": "spmv"}],
                "edges": [],
            }
        )
        arch = domain_contracts.ArchitectureTemplateIR.from_dict(
            {
                "template_id": "balanced_fpga_pipeline",
                "target_classes": ["fpga"],
                "components": [{"component_id": "host_runtime", "type": "software_runtime"}],
                "knobs": {"parallel_units": [1, 2]},
            }
        )
        mapping = domain_contracts.MappingIR.from_dict(
            {
                "mapped_nodes": {"kernel": "fpga.operator_engine"},
                "control_policy": {"submission": "async"},
            }
        )
        evidence = domain_contracts.EvidenceIR.from_dict(
            {
                "candidate_id": "candidate",
                "fidelity": "fast_model_screening",
                "execution_status": "screened",
                "metrics": {"latency_s": 1.0},
                "claim_ceiling": "fast_model_screening_only",
                "non_claims": ["not_backend_executed"],
            }
        )

        self.assertEqual(app_graph.to_dict()["schema_version"], "app_graph_ir_v0")
        self.assertEqual(arch.to_dict()["schema_version"], "architecture_template_ir_v0")
        self.assertEqual(mapping.to_dict()["schema_version"], "mapping_ir_v0")
        self.assertEqual(evidence.to_dict()["schema_version"], "evidence_ir_v0")

    def test_workload_adapters_emit_qe_and_generic_application_graphs(self) -> None:
        adapters = load_unified_dse_module("adapters")
        qe_payload = json.loads((FIXTURE_DIR / "minimal_workload.json").read_text(encoding="utf-8"))
        generic_payload = {
            "schema_version": "generic_trace_workload_v0",
            "workload_id": "generic_kernel",
            "domain": "sparse_linear_algebra",
            "app_adapter": "generic_trace",
            "application_nodes": [{"node_id": "spmv", "op_type": "spmv"}],
            "application_edges": [],
        }

        qe_bundle = adapters.workload_sidecar_bundle(qe_payload)
        generic_bundle = adapters.workload_sidecar_bundle(generic_payload)

        self.assertEqual(qe_bundle["adapter_name"], "qe")
        self.assertEqual(qe_bundle["application_graph"]["schema_version"], "app_graph_ir_v0")
        self.assertIn("qe", qe_bundle["domain_extension"])
        self.assertEqual(generic_bundle["adapter_name"], "generic_trace")
        self.assertEqual(generic_bundle["domain_extension"], {})
        self.assertEqual(generic_bundle["application_graph"]["nodes"][0]["node_id"], "spmv")
        self.assertNotIn("qe_anchor_refs", generic_bundle["legacy_aliases"])

    def test_backend_feedback_adapter_normalizes_backend_report_to_evidence_ir(self) -> None:
        backend_feedback_adapter = load_unified_dse_module("backend_feedback_adapter")
        report = {
            "schema_version": "backend_execution_report_v0",
            "candidate_id": "candidate",
            "backend_class": "gem5_systemc_smoke",
            "source_kind": "gem5_smoke",
            "execution_status": "executed",
            "fidelity": "gem5_smoke",
            "claim_ceiling": "gem5_smoke_only",
            "metrics": {"gem5_ticks": 12},
            "correctness_gate": {"status": "not_evaluated"},
            "non_claims": ["not_timed_performance"],
            "artifact_refs": {"report": "external/gem5.json"},
        }

        evidence = backend_feedback_adapter.normalize_backend_report_artifact(report)

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["schema_version"], "evidence_ir_v0")
        self.assertEqual(evidence[0]["backend_class"], "gem5_systemc_smoke")
        self.assertEqual(evidence[0]["artifact_refs"]["report"], "external/gem5.json")

    def test_backend_feedback_adapter_ingests_refused_backend_execution_report(self) -> None:
        backend_feedback_adapter = load_unified_dse_module("backend_feedback_adapter")
        report = {
            "schema_version": "backend_execution_report_v0",
            "candidate_id": "candidate",
            "backend_class": "systemc_timed_functional_proxy",
            "source_kind": "backend_runner_dry_run",
            "execution_status": "refused",
            "fidelity": "descriptor_only",
            "claim_ceiling": "descriptor_only",
            "metrics": {},
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

        evidence = backend_feedback_adapter.normalize_backend_report_artifact(report)

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["schema_version"], "evidence_ir_v0")
        self.assertEqual(evidence[0]["execution_status"], "refused")
        self.assertEqual(evidence[0]["fidelity"], "descriptor_only")
        self.assertEqual(evidence[0]["claim_ceiling"], "descriptor_only")
        self.assertEqual(evidence[0]["metrics"], {})

    def test_evaluation_result_dataclass_round_trips_without_decision_authority(self) -> None:
        interfaces = load_unified_dse_module("interfaces")
        workload = json.loads((FIXTURE_DIR / "minimal_workload.json").read_text(encoding="utf-8"))
        workload["domain"] = "dft"
        workload["app_adapter"] = "qe"
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
            "systemc_feedback_contract": {
                "schema_version": "qe_dse_systemc_feedback_contract_v0",
                "status": "planned_not_executed",
                "execution_status": "not_executed",
                "subprocess_invoked": False,
                "claim_ceiling": "timed_functional_proxy_contract_only",
            },
            "gem5_handoff_contract": {
                "schema_version": "qe_dse_gem5_systemc_handoff_contract_v0",
                "status": "planned_for_stage_b",
                "handoff_status": "planned",
                "execution_status": "not_executed",
                "platform_status": "requires_linux_x86_validation",
                "claim_ceiling": "stage_b_handoff_contract_only",
            },
            "qe_anchor_refs": {
                "schema_version": "qe_anchor_refs_v0",
                "status": "trace_or_correctness_anchor_only",
                "case_id": "si4_case_001",
                "anchor_evidence_kind": "missing_or_trace_only",
                "qe_equivalent_scf_claim": False,
            },
            "screening_rank": None,
            "pareto_membership": "not_evaluated",
            "shortlist_reason": "insufficient_metrics_for_shortlist",
            "ranking_claim_ceiling": "stage_a_screening_only",
        }

        result = interfaces.EvaluationResult.from_dict(payload)

        self.assertEqual(result.to_dict(), payload)
        self.assertEqual(interfaces.EvaluationResult.from_dict(result.to_dict()), result)
        self.assertEqual(result.to_dict()["authority_scope"], "supporting_evidence_only")
        self.assertIsNone(result.to_dict()["final_public_family_winner"])
        self.assertEqual(
            result.to_dict()["systemc_feedback_contract"]["status"],
            "planned_not_executed",
        )
        self.assertEqual(result.to_dict()["ranking_claim_ceiling"], "stage_a_screening_only")


if __name__ == "__main__":
    unittest.main()
