from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("run_qe_stage_c_correctness_for_candidates_v0.py")
SPEC = importlib.util.spec_from_file_location("run_qe_stage_c_correctness_for_candidates_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


class StageCCorrectnessForCandidatesTests(unittest.TestCase):
    def test_missing_gold_summary_refuses_without_qe_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate_manifest = write_json(
                root / "candidate_manifest.json",
                {
                    "schema_version": "qe_candidate_evidence_manifest_v0",
                    "candidates": [
                        {
                            "candidate_id": "candidate_F3",
                            "family": "F3",
                            "workload_id": "si4_pbe_uspp_small",
                            "case_id": "si4_pbe_uspp_small",
                        }
                    ],
                },
            )

            matrix = MODULE_ANY.run_for_candidates(candidate_manifest_path=candidate_manifest, output_dir=root / "stage_c")

            self.assertEqual(matrix["execution_status"], "refused")
            self.assertFalse(matrix["rows"][0]["qe_equivalent_scf_claim"])
            self.assertEqual(matrix["rows"][0]["correctness_status"], "stage_c_not_executed")


if __name__ == "__main__":
    unittest.main()
