from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("check_qe_dse_release_claim_boundaries_v0.py")
SPEC = importlib.util.spec_from_file_location("check_qe_dse_release_claim_boundaries_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


class QeDseReleaseClaimBoundaryCheckerTests(unittest.TestCase):
    def write_text(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, path: Path, payload: object) -> Path:
        return self.write_text(path, json.dumps(payload, indent=2) + "\n")

    def test_default_lane_e_docs_pass(self) -> None:
        MODULE_ANY.validate_paths(MODULE_ANY.DEFAULT_RELEASE_DOCS, require_doc_language=True)

    def test_rejects_projection_final_best_overclaim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.write_text(
                Path(tmpdir) / "bad.md",
                "A projection-screened row is the final architecture winner for QE.\n",
            )

            with self.assertRaises(MODULE_ANY.ClaimBoundaryError) as ctx:
                MODULE_ANY.validate_paths([path])

            self.assertIn("projection", str(ctx.exception))

    def test_allows_negated_projection_guardrail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.write_text(
                Path(tmpdir) / "ok.md",
                "A projection-screened row cannot be a final architecture winner without final-best-eligible evidence.\n",
            )

            MODULE_ANY.validate_paths([path])

    def test_rejects_systemc_cycle_accuracy_overclaim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.write_text(
                Path(tmpdir) / "bad.md",
                "The SystemC cycle-accounted artifact is cycle-accurate physical timing evidence.\n",
            )

            with self.assertRaises(MODULE_ANY.ClaimBoundaryError) as ctx:
                MODULE_ANY.validate_paths([path])

            self.assertIn("SystemC", str(ctx.exception))

    def test_json_higher_tiers_require_systemc_artifact_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = self.write_json(
                Path(tmpdir) / "bad.json",
                {
                    "rows": [
                        {
                            "candidate_id": "cand-a",
                            "dse_evidence_tier": "systemc-cycle-accounted",
                        }
                    ]
                },
            )
            good_path = self.write_json(
                Path(tmpdir) / "good.json",
                {
                    "rows": [
                        {
                            "candidate_id": "cand-a",
                            "dse_evidence_tier": "systemc-cycle-accounted",
                            "systemc_cycle_evidence_ref": "candidate_runs/cand-a/systemc_cycle_evidence.json",
                            "systemc_cycle_evidence_hash": "sha256:abc",
                        }
                    ]
                },
            )

            with self.assertRaises(MODULE_ANY.ClaimBoundaryError):
                MODULE_ANY.validate_paths([bad_path])
            MODULE_ANY.validate_paths([good_path])

    def test_json_final_best_requires_same_candidate_evidence_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = self.write_json(
                Path(tmpdir) / "bad.json",
                {
                    "dse_evidence_tier": "final-best-eligible",
                    "candidate_id": "cand-a",
                    "systemc_cycle_evidence_ref": "candidate_runs/cand-a/systemc_cycle_evidence.json",
                },
            )
            good_path = self.write_json(
                Path(tmpdir) / "good.json",
                {
                    "dse_evidence_tier": "final-best-eligible",
                    "candidate_id": "cand-a",
                    "stage_c_report_ref": "stage_c/cand-a.json",
                    "strict_b4_report_ref": "b4/cand-a.json",
                    "stage_d_report_ref": "stage_d/cand-a.json",
                    "systemc_cycle_evidence_ref": "candidate_runs/cand-a/systemc_cycle_evidence.json",
                    "systemc_cycle_evidence_hash": "sha256:def",
                },
            )

            with self.assertRaises(MODULE_ANY.ClaimBoundaryError):
                MODULE_ANY.validate_paths([bad_path])
            MODULE_ANY.validate_paths([good_path])

    def test_rejects_lower_tier_json_winner_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.write_json(
                Path(tmpdir) / "bad.json",
                {
                    "candidate_id": "cand-a",
                    "dse_evidence_tier": "survey-catalog",
                    "winner": True,
                },
            )

            with self.assertRaises(MODULE_ANY.ClaimBoundaryError) as ctx:
                MODULE_ANY.validate_paths([path])

            self.assertIn("cannot set winner", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
