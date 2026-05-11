from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class QeIcGraphContractArtifactsTests(unittest.TestCase):
    def test_component_catalog_seed_contains_required_component_types(self) -> None:
        payload = json.loads(
            (ROOT / "docs/architecture/qe_ic_component_catalog_seed_v0.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["catalog_version"], "qe_ic_component_catalog_seed_v0")
        component_types = {item["component_type"] for item in payload["components"]}
        self.assertTrue(
            {
                "SystemContainer",
                "GraphExecutor",
                "HostController",
                "CIMArray",
                "FFTUnit",
                "DiagUnit",
                "DMAChannel",
                "EpisodeController",
                "Scheduler",
                "NearMemoryBuffer",
            }
            <= component_types
        )

    def test_graph_schema_has_required_top_level_fields(self) -> None:
        schema = json.loads(
            (ROOT / "docs/architecture/qe_ic_graph_schema_v0.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["graph_schema_version"]["const"], "qe_ic_graph_schema_v0")
        required = set(schema["required"])
        self.assertTrue(
            {
                "graph_schema_version",
                "graph_id",
                "seed_template_id",
                "workload_class",
                "join_keys",
                "modules",
                "links",
                "flows",
                "placement",
                "estimation_profile",
                "constraints",
                "observability_requirements",
            }
            <= required
        )

    def test_graph_export_examples_cover_f1_f2_f3_and_round_trip(self) -> None:
        payload = json.loads(
            (ROOT / "docs/architecture/qe_ic_graph_export_examples_v0.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["baseline_ssot"], "family_scaffold")
        families = {item["projected_design_point"]["family"] for item in payload["examples"]}
        self.assertEqual(families, {"F1", "F2", "F3"})
        for item in payload["examples"]:
            self.assertEqual(item["round_trip_expected_template_id"], item["seed_template_id"])
            self.assertIn("partition_strategy", item["projected_design_point"])
            self.assertIn("observability_contract_id", item["shared_join_keys"])
            self.assertIn("graph_topology_summary", item)
            self.assertGreaterEqual(item["graph_topology_summary"]["module_instance_count"], 18)
            self.assertIn("system_container", item["graph_topology_summary"]["key_component_refs"])
            self.assertIn("cluster_flow_executor", item["graph_topology_summary"]["key_component_refs"])
            self.assertIn("context_loader", item["graph_topology_summary"]["key_component_refs"])
            self.assertIn("cim_array_core", item["graph_topology_summary"]["key_component_refs"])

    def test_seed_templates_are_family_compatible_overlay_templates(self) -> None:
        payload = json.loads(
            (ROOT / "docs/architecture/qe_ic_graph_seed_templates_v0.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["seed_template_version"], "qe_ic_graph_seed_templates_v0")
        templates = payload["templates"]
        self.assertEqual(len(templates), 3)
        families = {item["join_keys"]["family"] for item in templates}
        self.assertEqual(families, {"F1", "F2", "F3"})
        for item in templates:
            self.assertTrue(item["constraints"]["family_compatible"])
            self.assertTrue(item["observability_requirements"]["require_runtime_projection"])
            self.assertGreaterEqual(len(item["modules"]), 18)
            self.assertGreaterEqual(len(item["flows"]), 1)
            component_refs = {module["component_ref"] for module in item["modules"]}
            self.assertIn("system_container", component_refs)
            self.assertIn("chip_execution_facade", component_refs)
            self.assertIn("cluster_flow_executor", component_refs)
            self.assertIn("command_scheduler", component_refs)
            self.assertIn("context_loader", component_refs)
            self.assertIn("cim_array_core", component_refs)

    def test_export_contract_markdown_freezes_ssot_and_sidecar_rules(self) -> None:
        text = (ROOT / "docs/architecture/qe_ic_graph_export_contract_v0.md").read_text(encoding="utf-8")
        self.assertIn("SSOT", text)
        self.assertIn("No-parallel-universe invariant", text)
        self.assertIn("graph_evidence", text)
        self.assertIn("round-trip success predicate", text)

    def test_evaluator_and_axes_docs_exist_and_freeze_staged_rollout(self) -> None:
        evaluator = (ROOT / "docs/benchmarks/qe_ic_architecture_evaluator_contract_v0.md").read_text(encoding="utf-8")
        system_axes = (ROOT / "docs/benchmarks/qe_ic_system_level_dse_axes_v0.md").read_text(encoding="utf-8")
        hw_axes = (ROOT / "docs/benchmarks/qe_ic_fine_grained_hw_axes_v0.md").read_text(encoding="utf-8")
        self.assertIn("Evaluator", evaluator)
        self.assertIn("先系统级，后细粒度硬件维度", system_axes)
        self.assertIn("当前阶段", hw_axes)
        self.assertIn("不全面打开搜索", hw_axes)


if __name__ == "__main__":
    unittest.main()
