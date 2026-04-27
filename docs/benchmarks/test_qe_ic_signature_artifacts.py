from __future__ import annotations

import json
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = ROOT / "docs/benchmarks/qe_ic_computational_signature_taxonomy_v0.md"
MATRIX_PATH = ROOT / "docs/benchmarks/qe_ic_case_signature_matrix_v0.json"
PHASE_CONFIG_PATH = ROOT / "docs/benchmarks/qe_ic_full_flow_phase_config_v0.json"
WORKLOAD_MATRIX_PATH = ROOT / "docs/benchmarks/qe_device_oriented_workload_matrix_v0.md"
SCHEMA_PATH = ROOT / "docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json"
RUNNER_PATH = ROOT / "docs/benchmarks/run_systemc_architecture_family_dse_sweep.py"


class QeIcSignatureArtifactsTests(unittest.TestCase):
    def test_signature_artifacts_exist(self) -> None:
        self.assertTrue(TAXONOMY_PATH.exists())
        self.assertTrue(MATRIX_PATH.exists())
        self.assertTrue(PHASE_CONFIG_PATH.exists())
        self.assertTrue(WORKLOAD_MATRIX_PATH.exists())

    def test_case_signature_matrix_has_stage_a_and_stage_b_cases(self) -> None:
        payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["stage_a_bringup_cases"],
            ["si4_pbe_uspp_small", "graphene_pbe_uspp", "si8_pbe_nc"],
        )
        self.assertEqual(
            payload["stage_b_nonblocking_signature_coverage"],
            ["au_slab_subspace", "sic32_subspace"],
        )
        cases = {item["machine_workload_id"]: item for item in payload["cases"]}
        self.assertIn("h2_tiny", cases)
        for case_id in payload["stage_a_bringup_cases"] + payload["stage_b_nonblocking_signature_coverage"]:
            self.assertIn(case_id, cases)
            self.assertTrue(cases[case_id]["signature_id"])
        allowed_post_scf = {
            "shell_only",
            "nscf_extension",
            "dfpt_expected",
            "epw_expected",
            "mobility_extension_expected",
        }
        allowed_topology_roles = {
            "bringup_proxy",
            "accurate_anchor",
            "coverage_followon",
            "stage_b_nonblocking",
            "stress_aux",
        }
        for case in payload["cases"]:
            self.assertIn(case["post_scf_extension_level"], allowed_post_scf)
            self.assertIn(case["topology_role"], allowed_topology_roles)
            self.assertNotEqual(case["property_target"], "mobility_extension_expected")
            self.assertTrue(case["signature_id"].startswith("sig_"))
            signature_id = case["signature_id"].lower()
            self.assertIn(case["pseudopotential_family"].lower(), signature_id)
            self.assertIn(case["workload_topology"].lower(), signature_id)
            self.assertIn(case["property_target"].lower(), signature_id)

    def test_phase_config_references_taxonomy_and_signature_matrix(self) -> None:
        payload = json.loads(PHASE_CONFIG_PATH.read_text(encoding="utf-8"))
        specialization = payload["specialization"]
        self.assertEqual(
            specialization["signature_taxonomy_ref"],
            "docs/benchmarks/qe_ic_computational_signature_taxonomy_v0.md",
        )
        self.assertEqual(
            specialization["case_signature_matrix_ref"],
            "docs/benchmarks/qe_ic_case_signature_matrix_v0.json",
        )
        self.assertEqual(
            specialization["stage_b_nonblocking_signature_cases"],
            ["au_slab_subspace", "sic32_subspace"],
        )
        self.assertEqual(
            payload["strategy_axes"]["design_point_identity_fields"],
            ["family", "diag_policy", "offload_scope", "resident_policy", "partition_strategy"],
        )
        self.assertIn("partition_strategy", payload["descriptor_contract"]["shared_join_keys"])
        for layer in ("fast_layer", "accurate_layer"):
            self.assertIn("partition_strategy", payload["layers"][layer]["descriptor_fields"])
        self.assertEqual(
            payload["artifact_semantics"]["best_performance_candidate_requires"][0],
            "signature_id",
        )

    def test_workload_matrix_documents_machine_readable_mapping(self) -> None:
        text = WORKLOAD_MATRIX_PATH.read_text(encoding="utf-8")
        self.assertIn("Au slab", text)
        self.assertIn("au_slab_subspace", text)
        self.assertIn("SiC32", text)
        self.assertIn("sic32_subspace", text)
        self.assertIn("Stage A", text)
        self.assertIn("Stage B", text)

    def test_taxonomy_keeps_property_and_extension_axes_orthogonal(self) -> None:
        text = TAXONOMY_PATH.read_text(encoding="utf-8")
        property_section = text.split("### 2.1 `property_target`", 1)[1].split("### 2.2 `pseudopotential_family`", 1)[0]
        extension_section = text.split("### 2.6 `post_scf_extension_level`", 1)[1].split("## 3. Derived helper fields", 1)[0]
        self.assertNotIn("mobility_extension_expected", property_section)
        self.assertIn("mobility_extension_expected", extension_section)

    def test_runner_inventory_and_schema_include_stage_b_cases_and_lanes(self) -> None:
        spec = importlib.util.spec_from_file_location("runner", RUNNER_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        self.assertIn("au_slab_subspace", module.DEFAULT_WORKLOADS)
        self.assertIn("sic32_subspace", module.DEFAULT_WORKLOADS)
        self.assertEqual(module.DEFAULT_WORKLOADS["au_slab_subspace"]["lane"], "qe_signature_stage_b")
        self.assertTrue(module.DEFAULT_WORKLOADS["h2_tiny"]["signature_id"])
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        lane_enum = schema["$defs"]["workload"]["properties"]["lane"]["enum"]
        self.assertIn("qe_next_stage_mainline", lane_enum)
        self.assertIn("qe_generalization", lane_enum)
        self.assertIn("qe_signature_stage_b", lane_enum)

    def test_generalization_cases_have_signature_coverage(self) -> None:
        payload = json.loads(PHASE_CONFIG_PATH.read_text(encoding="utf-8"))
        cases = {
            item["machine_workload_id"]: item
            for item in json.loads(MATRIX_PATH.read_text(encoding="utf-8"))["cases"]
        }
        for workload_id in payload["layers"]["accurate_layer"]["generalization_cases"]:
            self.assertIn(workload_id, cases)
            self.assertTrue(cases[workload_id]["signature_id"])


if __name__ == "__main__":
    unittest.main()
