from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("build_qe_candidate_evidence_manifest_v0.py")
SPEC = importlib.util.spec_from_file_location("build_qe_candidate_evidence_manifest_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


class CandidateEvidenceManifestTests(unittest.TestCase):
    def test_build_manifest_preserves_candidate_join_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            request = write_json(
                root / "frontend_dse" / "backend_execution_requests" / "candidate_F3.json",
                {
                    "candidate_id": "candidate_F3",
                    "candidate_identity": {
                        "candidate_id": "candidate_F3",
                        "architecture_template_id": "template_F3",
                        "design_axes": {"family": "F3"},
                    },
                    "workload_identity": {"workload_id": "si4_pbe_uspp_small"},
                    "domain_extension": {"qe": {"case_id": "si4_pbe_uspp_small"}},
                },
            )
            e2e_manifest = write_json(
                root / "qe_fpga_dse_e2e_manifest_v0.json",
                {
                    "schema_version": "qe_fpga_dse_e2e_manifest_v0",
                    "candidate_runs": [
                        {
                            "candidate_id": "candidate_F3",
                            "stage_b0_request": str(request),
                            "systemc_backend_report": "systemc.json",
                            "gem5_b4_report": "b4.json",
                        }
                    ],
                },
            )

            payload = MODULE_ANY.build_manifest(e2e_manifest)

            self.assertEqual(payload["schema_version"], "qe_candidate_evidence_manifest_v0")
            self.assertEqual(payload["candidate_count"], 1)
            candidate = payload["candidates"][0]
            self.assertEqual(candidate["candidate_id"], "candidate_F3")
            self.assertEqual(candidate["family"], "F3")
            self.assertEqual(candidate["workload_id"], "si4_pbe_uspp_small")
            self.assertEqual(candidate["implementation_target_class"], "fpga")


if __name__ == "__main__":
    unittest.main()
