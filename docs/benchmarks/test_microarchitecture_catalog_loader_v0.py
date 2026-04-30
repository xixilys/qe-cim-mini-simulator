from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("microarchitecture_catalog_loader_v0.py")
SPEC = importlib.util.spec_from_file_location("microarchitecture_catalog_loader_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


class MicroarchitectureCatalogLoaderTests(unittest.TestCase):
    def load_default_payload(self) -> dict[str, Any]:
        return json.loads(MODULE_ANY.DEFAULT_CATALOG_PATH.read_text(encoding="utf-8"))

    def write_catalog(self, payload: dict[str, Any]) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "catalog.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def test_valid_catalog_loads_and_exposes_search_rows(self) -> None:
        catalog = MODULE_ANY.load_catalog()

        self.assertGreaterEqual(len(catalog.entries), 6)
        rows = catalog.as_search_rows()
        self.assertEqual(len(rows), len(catalog.entries))
        self.assertTrue(all(row["final_best_eligible"] is False for row in rows))
        self.assertTrue(all(row["dse_evidence_tier"] in {"survey-catalog", "projection-screened"} for row in rows))
        self.assertTrue(any(row["support_status"] == "unsupported" for row in rows))
        self.assertIn("systemc_configurable", catalog.support_summary())

    def test_schema_file_has_exact_four_tiers(self) -> None:
        schema = MODULE_ANY.load_schema()
        tier_enum = schema["$defs"]["microarchitecture_entry"]["properties"]["supported_evidence_tiers"]["items"]["enum"]

        self.assertIn("survey-catalog", tier_enum)
        self.assertIn("projection-screened", tier_enum)
        self.assertIn("systemc-cycle-accounted", tier_enum)
        self.assertNotIn("final-best-eligible", tier_enum)

    def test_missing_provenance_is_rejected(self) -> None:
        payload = self.load_default_payload()
        payload["entries"][0].pop("provenance")
        path = self.write_catalog(payload)

        with self.assertRaises(MODULE_ANY.CatalogValidationError) as ctx:
            MODULE_ANY.load_catalog(path)

        self.assertIn("provenance", str(ctx.exception))

    def test_missing_support_status_is_rejected(self) -> None:
        payload = self.load_default_payload()
        payload["entries"][0].pop("support_status")
        path = self.write_catalog(payload)

        with self.assertRaises(MODULE_ANY.CatalogValidationError) as ctx:
            MODULE_ANY.load_catalog(path)

        self.assertIn("support_status", str(ctx.exception))

    def test_unsupported_entries_are_limited_to_catalog_projection_tiers(self) -> None:
        payload = self.load_default_payload()
        unsupported_entry = next(entry for entry in payload["entries"] if entry["support_status"] == "unsupported")
        unsupported_entry["supported_evidence_tiers"] = ["survey-catalog", "systemc-cycle-accounted"]
        path = self.write_catalog(payload)

        with self.assertRaises(MODULE_ANY.CatalogValidationError) as ctx:
            MODULE_ANY.load_catalog(path)

        self.assertIn("unsupported entries may only use survey-catalog/projection-screened", str(ctx.exception))

    def test_final_best_tier_is_rejected_in_catalog_entries(self) -> None:
        payload = self.load_default_payload()
        payload["entries"][0]["supported_evidence_tiers"] = ["survey-catalog", "final-best-eligible"]
        path = self.write_catalog(payload)

        with self.assertRaises(MODULE_ANY.CatalogValidationError) as ctx:
            MODULE_ANY.load_catalog(path)

        self.assertIn("forbidden tiers", str(ctx.exception))

    def test_unknown_parameter_requires_reason(self) -> None:
        payload = self.load_default_payload()
        payload["entries"][0]["parameter_ranges"]["new_unknown_axis"] = {
            "kind": "unknown",
            "description": "Missing reason should fail."
        }
        path = self.write_catalog(payload)

        with self.assertRaises(MODULE_ANY.CatalogValidationError) as ctx:
            MODULE_ANY.load_catalog(path)

        self.assertIn("unknown_reason", str(ctx.exception))

    def test_duplicate_microarchitecture_ids_are_rejected(self) -> None:
        payload = self.load_default_payload()
        duplicate = copy.deepcopy(payload["entries"][0])
        payload["entries"].append(duplicate)
        path = self.write_catalog(payload)

        with self.assertRaises(MODULE_ANY.CatalogValidationError) as ctx:
            MODULE_ANY.load_catalog(path)

        self.assertIn("duplicate microarchitecture_id", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
