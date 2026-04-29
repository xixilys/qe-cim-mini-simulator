from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from frontend.dse_core.ir import contracts
from frontend.dse_core.workloads import adapters
from frontend.dse_core.search import backends
from frontend.dse_core.feedback import evidence
from frontend.dse_core.calibration import engine as calibration
from frontend.dse_core.adjudication import engine as adjudication
from frontend.dse_core.release import bundle as release_bundle


class ProFrontendCoreTests(unittest.TestCase):
    def test_synthetic_adapters_emit_domain_neutral_application_graphs(self) -> None:
        payload = {
            "workload_id": "gemm_128",
            "app_adapter": "synthetic_gemm",
            "kernel_type": "gemm",
            "shape": {"m": 128, "n": 128, "k": 64},
        }
        adapter = adapters.detect_workload_adapter(payload)
        self.assertEqual(adapter.name, "synthetic_gemm")
        sidecars = adapters.workload_sidecar_bundle(payload)
        self.assertEqual(sidecars["domain_extension"]["synthetic_kernel"]["kernel_type"], "gemm")
        self.assertEqual(sidecars["legacy_aliases"], {})
        graph = sidecars["application_graph"]
        contracts.validate_application_graph_ir(graph)
        self.assertEqual(graph["nodes"][0]["op_type"], "dense_matrix_multiply")
        self.assertNotIn("qe", json.dumps(sidecars).lower())

    def test_architecture_and_mapping_ir_are_validated_and_nonempty(self) -> None:
        workload = {"workload_id": "stencil_0", "app_adapter": "synthetic_stencil", "kernel_type": "stencil"}
        point = {
            "family": "F2",
            "diag_policy": "cpu_only",
            "offload_scope": "device_heavy",
            "resident_policy": "fit_first",
            "partition_strategy": "operator__build__diag__refresh",
        }
        arch = contracts.build_architecture_template_ir("template_F2", point, "fpga")
        mapping = contracts.build_mapping_ir(point, workload)
        contracts.validate_architecture_template_ir(arch)
        contracts.validate_mapping_ir(mapping)
        self.assertIn("host_device_link", {item["component_id"] for item in arch["components"]})
        self.assertIn("host_device_event_sequence", mapping["control_policy"])

    def test_search_facade_has_latin_hypercube_without_hard_dependencies(self) -> None:
        axes = {
            "family": ["F1", "F2", "F3"],
            "diag_policy": ["cpu_only"],
            "offload_scope": ["balanced", "device_heavy"],
            "resident_policy": ["fit_first"],
            "partition_strategy": ["operator__build__diag__refresh"],
        }
        result = backends.search_candidates(axes, 4, backend="random_latin_hypercube")
        self.assertTrue(result.metadata["available"])
        self.assertEqual(result.metadata["backend"], "random_latin_hypercube")
        self.assertGreaterEqual(len(result.candidates), 1)

    def test_legacy_reports_normalize_to_evidence_ir(self) -> None:
        gem5_report = {
            "schema_version": "qe_dse_gem5_systemc_smoke_report_v0",
            "execution_status": "executed",
            "claim_ceiling": "gem5_systemc_smoke_only",
            "run_id": "gem5_run_0",
            "candidate_id": "cand_0",
            "environment": {"sim": "gem5"},
            "scf_control_loop_status": "smoke_passed",
            "systemc_bridge_status": "smoke_passed",
            "qe_equivalence_status": "not_claimed",
            "metrics": {"latency_s": 1.0},
            "correctness_gate": {"qe_equivalent_scf_claim": False},
        }
        rows = evidence.normalize_backend_report_artifact(gem5_report)
        self.assertEqual(rows[0]["schema_version"], "evidence_ir_v0")
        self.assertEqual(rows[0]["fidelity"], "gem5_smoke")
        self.assertEqual(rows[0]["claim_ceiling"], "gem5_smoke_only")

    def test_calibration_adjudication_and_release_bundle_link_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {
                "candidate_id": "cand_0",
                "screening_rank": 1,
                "promotion_state": "promotion-eligible",
                "ranking_claim_ceiling": "fast_model_screening_only",
                "claim_ceiling": "fast_model_screening_only",
                "source_kind": "fast_model_screening",
                "metrics": {"latency_s": 1.0},
                "candidate_descriptor": {"candidate_id": "cand_0"},
            }
            evidence_row = {
                "schema_version": "evidence_ir_v0",
                "candidate_id": "cand_0",
                "backend_class": "systemc",
                "source_kind": "report",
                "fidelity": "systemc_timed_functional",
                "execution_status": "executed",
                "metrics": {"latency_s": 2.0},
                "claim_ceiling": "systemc_proxy_only",
                "correctness_gate": {"status": "not_claimed"},
                "non_claims": ["not_board_measured"],
                "artifact_refs": {"report": "systemc.json"},
            }
            model = calibration.fit_calibration_model([row], [evidence_row])
            summary = adjudication.build_adjudication_summary(
                [row], result_bundle_ref="unified_dse_results_v0.json", calibration_model_ref="calibration_model_v0.json"
            )
            (root / "unified_dse_results_v0.json").write_text("{}\n", encoding="utf-8")
            (root / "unified_dse_manifest_v0.json").write_text("{}\n", encoding="utf-8")
            (root / "calibration_model_v0.json").write_text(json.dumps(model), encoding="utf-8")
            (root / "frontend_adjudication_summary_v0.json").write_text(json.dumps(summary), encoding="utf-8")
            payload = release_bundle.emit_release_bundle(
                root,
                calibration_metadata_ref="calibration_model_v0.json",
                adjudication_summary_ref="frontend_adjudication_summary_v0.json",
            )
            release_bundle.validate_release_bundle_links(payload, root)
            self.assertTrue((root / "frontend_release_sha256_manifest_v0.json").exists())
            self.assertIsNone(payload["final_public_family_winner"])


if __name__ == "__main__":
    unittest.main()
