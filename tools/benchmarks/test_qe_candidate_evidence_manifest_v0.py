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

    def test_build_manifest_includes_closure_tiers_and_artifact_hashes(self) -> None:
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
                },
            )
            systemc_report = write_json(root / "candidate_runs" / "candidate_F3" / "systemc.json", {"candidate_id": "candidate_F3"})
            cycle_report = write_json(
                root / "candidate_runs" / "candidate_F3" / "systemc_cycle.json",
                {
                    "candidate_id": "candidate_F3",
                    "evidence_tier": "systemc-cycle-accounted",
                    "total_cycles": 123,
                },
            )
            claim_matrix = write_json(
                root / "claim_ceiling_status_matrix_v0.json",
                {
                    "schema_version": "claim_ceiling_status_matrix_v0",
                    "rows": [
                        {
                            "candidate_id": "candidate_F3",
                            "evidence_tier": "systemc-cycle-accounted",
                            "same_candidate_evidence_only": True,
                            "systemc_cycle_accounted_evidence_ref": str(cycle_report),
                            "stage_c_report_ref": None,
                            "stage_d_report_ref": None,
                            "blockers": ["missing_stage_c_qe_correctness_report"],
                            "candidate_alignment": {
                                "stage_b0_candidate_id": "candidate_F3",
                                "systemc_cycle_candidate_id": "candidate_F3",
                            },
                        }
                    ],
                },
            )
            e2e_manifest = write_json(
                root / "qe_fpga_dse_e2e_manifest_v0.json",
                {
                    "schema_version": "qe_fpga_dse_e2e_manifest_v0",
                    "claim_ceiling_status_matrix": str(claim_matrix),
                    "top_k_closure": {
                        "schema_version": "qe_top_k_evidence_closure_status_v0",
                        "queue_count": 1,
                        "queue": [{"candidate_id": "candidate_F3"}],
                        "evidence_tier_counts": {"systemc-cycle-accounted": 1},
                    },
                    "candidate_runs": [
                        {
                            "candidate_id": "candidate_F3",
                            "stage_b0_request": str(request),
                            "systemc_backend_report": str(systemc_report),
                            "systemc_cycle_accounted_evidence": str(cycle_report),
                        }
                    ],
                },
            )

            payload = MODULE_ANY.build_manifest(e2e_manifest)

            candidate = payload["candidates"][0]
            self.assertEqual(candidate["evidence_tier"], "systemc-cycle-accounted")
            self.assertEqual(candidate["blockers"], ["missing_stage_c_qe_correctness_report"])
            self.assertEqual(
                candidate["artifact_refs"]["systemc_cycle_accounted_evidence"]["sha256"],
                MODULE_ANY.sha256_file(cycle_report),
            )
            self.assertEqual(payload["evidence_tier_counts"]["systemc-cycle-accounted"], 1)
            self.assertEqual(payload["top_k_closure"]["queue_count"], 1)


if __name__ == "__main__":
    unittest.main()
