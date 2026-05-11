from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


BUILDER_PATH = Path(__file__).with_name("build_qe_microarchitecture_catalog_freeze_manifest_v0.py")
BUILDER_SPEC = importlib.util.spec_from_file_location(
    "build_qe_microarchitecture_catalog_freeze_manifest_v0",
    BUILDER_PATH,
)
assert BUILDER_SPEC is not None
assert BUILDER_SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(BUILDER_SPEC)
sys.modules[BUILDER_SPEC.name] = BUILDER
BUILDER_SPEC.loader.exec_module(BUILDER)
BUILDER_ANY = cast(Any, BUILDER)

CHECKER_PATH = Path(__file__).with_name("check_qe_microarchitecture_catalog_freeze_v0.py")
CHECKER_SPEC = importlib.util.spec_from_file_location(
    "check_qe_microarchitecture_catalog_freeze_v0",
    CHECKER_PATH,
)
assert CHECKER_SPEC is not None
assert CHECKER_SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(CHECKER_SPEC)
sys.modules[CHECKER_SPEC.name] = CHECKER
CHECKER_SPEC.loader.exec_module(CHECKER)
CHECKER_ANY = cast(Any, CHECKER)

LOADER_PATH = Path(__file__).with_name("microarchitecture_catalog_loader_v0.py")
LOADER_SPEC = importlib.util.spec_from_file_location("microarchitecture_catalog_loader_v0", LOADER_PATH)
assert LOADER_SPEC is not None
assert LOADER_SPEC.loader is not None
LOADER = importlib.util.module_from_spec(LOADER_SPEC)
sys.modules[LOADER_SPEC.name] = LOADER
LOADER_SPEC.loader.exec_module(LOADER)
LOADER_ANY = cast(Any, LOADER)


class QeMicroarchitectureCatalogFreezeTests(unittest.TestCase):
    def default_catalog_payload(self) -> dict[str, Any]:
        return json.loads(LOADER_ANY.DEFAULT_CATALOG_PATH.read_text(encoding="utf-8"))

    def write_json(self, root: Path, name: str, payload: dict[str, Any]) -> Path:
        path = root / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def test_default_catalog_freeze_manifest_passes_all_gates(self) -> None:
        manifest = BUILDER_ANY.build_freeze_manifest()

        self.assertEqual(manifest["schema_version"], BUILDER_ANY.SCHEMA_VERSION)
        self.assertEqual(manifest["freeze_status"], "passed")
        self.assertIn(
            "tensor_systolic_dense_path",
            manifest["partitions"]["competitive_evaluable"],
        )
        self.assertIn(
            "four_cluster_cim_system_baseline",
            manifest["partitions"]["coverage_only"],
        )
        self.assertIn(
            "cgra_dataflow_operator",
            manifest["partitions"]["excluded_from_best_universe"],
        )
        self.assertEqual(manifest["coverage_summary"]["missing_coverage_tags"], [])
        self.assertEqual(
            {gate["status"] for gate in manifest["freeze_gates"]},
            {"passed"},
        )
        self.assertFalse(CHECKER_ANY.validate_freeze_manifest(manifest))

    def test_cli_writes_manifest_and_checker_accepts_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output = root / "freeze.json"

            rc = BUILDER_ANY.main(["--output", str(output)])

            self.assertEqual(rc, 0)
            self.assertTrue(output.exists())
            self.assertEqual(CHECKER_ANY.main(["--manifest", str(output)]), 0)

    def test_missing_competitive_candidate_blocks_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload = self.default_catalog_payload()
            for entry in payload["entries"]:
                if entry["support_status"] == "systemc_configurable":
                    entry["support_status"] = "projection_only"
                    entry["model_support_status"] = {
                        "status": "projection_only",
                        "notes": "test fixture removes executable support",
                        "supporting_artifact_refs": ["docs/architecture/architecture_templates/f3_tensor_systolic_fpga_offload_v1.json"],
                    }
                    entry["supported_evidence_tiers"] = ["survey-catalog", "projection-screened"]
            catalog_path = self.write_json(root, "catalog.json", payload)

            manifest = BUILDER_ANY.build_freeze_manifest(catalog_path=catalog_path)

            self.assertEqual(manifest["freeze_status"], "blocked")
            gate = {
                item["gate_id"]: item
                for item in manifest["freeze_gates"]
            }["evidence_path_per_competitive_candidate"]
            self.assertEqual(gate["status"], "blocked")
            self.assertIn(
                "at least one competitive_evaluable candidate is required",
                "\n".join(CHECKER_ANY.validate_freeze_manifest(manifest)),
            )

    def test_checker_rejects_failed_gate(self) -> None:
        manifest = BUILDER_ANY.build_freeze_manifest()
        broken = copy.deepcopy(manifest)
        broken["freeze_gates"][0]["status"] = "blocked"

        issues = CHECKER_ANY.validate_freeze_manifest(broken)

        self.assertTrue(any("research_coverage_proof" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
