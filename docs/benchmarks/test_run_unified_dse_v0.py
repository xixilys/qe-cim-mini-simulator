from __future__ import annotations

import csv
import contextlib
import io
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = Path(__file__).with_name("run_unified_dse_v0.py")
SPEC = importlib.util.spec_from_file_location("run_unified_dse_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)

DESIGN_SPACE_PATH = ROOT / "docs/benchmarks/qe_architecture_family_design_space_spec_v0.json"
FIXTURE_DIR = Path(__file__).with_name("testdata") / "unified_dse"


class RunUnifiedDseV0Tests(unittest.TestCase):
    def make_base_args(self, out_dir: Path) -> list[str]:
        return [
            "--design-space-spec",
            str(DESIGN_SPACE_PATH),
            "--workload",
            str(FIXTURE_DIR / "minimal_workload.json"),
            "--calibration",
            str(FIXTURE_DIR / "minimal_calibration.json"),
            "--output-dir",
            str(out_dir),
            "--dry-run",
            "--max-design-points",
            "3",
        ]

    def test_cli_writes_json_csv_and_manifest_as_evidence_only_without_final_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)

            rc = MODULE_ANY.main(self.make_base_args(out_dir) + ["--source-kind", "stub"])

            self.assertEqual(rc, 0)
            result_json = out_dir / "unified_dse_results_v0.json"
            result_csv = out_dir / "unified_dse_results_v0.csv"
            manifest_json = out_dir / "unified_dse_manifest_v0.json"
            self.assertTrue(result_json.exists())
            self.assertTrue(result_csv.exists())
            self.assertTrue(manifest_json.exists())

            bundle = json.loads(result_json.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
            with result_csv.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(bundle["schema_version"], "unified_dse_result_bundle_v0")
            self.assertEqual(bundle["authority"]["claim_posture"], "evidence_only")
            self.assertEqual(bundle["authority"]["decision_authority"], "adjudicator_memo_only")
            self.assertIsNone(bundle["authority"].get("final_public_family_winner"))
            self.assertGreaterEqual(len(bundle["results"]), 1)
            self.assertGreaterEqual(len(rows), 1)
            self.assertIn("promotion_state", rows[0])
            self.assertIn("authority_scope", rows[0])

            self.assertEqual(manifest["schema_version"], "unified_dse_manifest_v0")
            self.assertEqual(manifest["authority_scope"], "supporting_evidence_only")
            self.assertEqual(manifest["claim_posture"], "evidence_only")
            self.assertEqual(manifest["decision_authority"], "adjudicator_memo_only")
            self.assertFalse(manifest["winner_declared"])
            self.assertIsNone(manifest["final_public_family_winner"])
            self.assertEqual(set(manifest["promotion_state_counts"]), {"reject", "explain-only", "promotion-eligible"})

    def test_cli_rejects_non_stub_source_kind_for_current_fast_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    MODULE_ANY.main(
                        self.make_base_args(Path(tmpdir))
                        + ["--source-kind", "trace_calibrated_proxy"]
                    )

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("current Unified DSE v0 CLI only supports --source-kind stub", stderr.getvalue())

    def test_cli_rejects_execute_systemc_in_v0_with_clear_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    MODULE_ANY.main(
                        self.make_base_args(Path(tmpdir))
                        + ["--source-kind", "stub", "--execute-systemc"]
                    )

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("SystemC execution remains via the canonical runner", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
