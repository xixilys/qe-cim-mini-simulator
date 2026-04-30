from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("materialize_qe_stage_d_implementation_evidence_v0.py")
SPEC = importlib.util.spec_from_file_location("materialize_qe_stage_d_implementation_evidence_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


class StageDImplementationEvidenceMaterializerTests(unittest.TestCase):
    def run_materializer(self, args: list[str]) -> dict[str, Any]:
        rc = MODULE_ANY.main(args)
        self.assertEqual(rc, 0)
        output = Path(args[args.index("--output") + 1])
        return json.loads(output.read_text(encoding="utf-8"))

    def write_qe_correctness(self, path: Path, candidate_id: str, *, claim: bool = True) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "qe_dse_qe_equivalent_correctness_report_v0",
                    "execution_status": "executed",
                    "claim_ceiling": (
                        "qe_equivalent_scf_correctness_only"
                        if claim
                        else "correctness_report_reference_only"
                    ),
                    "report_id": f"stage_c_fixture::{candidate_id}",
                    "candidate_id": candidate_id,
                    "workload_id": "si8_pbe_nc",
                    "case_id": "si8_pbe_nc",
                    "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                    "correctness_status": "pass" if claim else "mismatch",
                    "qe_equivalent_scf_claim": claim,
                    "compare_report": {
                        "schema_name": "qe_gold_numerical_tolerance_schema_v0",
                        "schema_version": "2026-04-13",
                        "overall_pass": claim,
                        "summary": {
                            "status": "pass" if claim else "fail",
                            "failed_required_fields": [] if claim else ["final_total_energy_ry"],
                        },
                    },
                    "evidence_refs": {},
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def test_placeholder_hls_downgrades_to_projection_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "evidence.json"
            payload = self.run_materializer(
                [
                    "--candidate-id",
                    "candidate_f1",
                    "--output",
                    str(output),
                    "--implementation-target-class",
                    "fpga",
                    "--evidence-kind",
                    "hls_synthesis",
                    "--artifact-ref",
                    "hls_report=PLACEHOLDER/report.json",
                    "--metric",
                    "estimated_lut=1000",
                    "--metric",
                    "estimated_bram=8",
                ]
            )

            self.assertEqual(payload["evidence_kind"], "implementation_projection")
            self.assertEqual(payload["evidence_status"], "partial")
            self.assertEqual(payload["claim_ceiling"], "implementation_evidence_only")
            self.assertEqual(payload["artifact_refs"]["hls_report"], "PLACEHOLDER/report.json")

    def test_real_hls_evidence_stays_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "evidence.json"
            payload = self.run_materializer(
                [
                    "--candidate-id",
                    "candidate_f1",
                    "--output",
                    str(output),
                    "--implementation-target-class",
                    "fpga",
                    "--evidence-kind",
                    "hls_synthesis",
                    "--artifact-ref",
                    "hls_report=artifacts/implementation/candidate_f1_hls.json",
                    "--metric",
                    "estimated_lut=1200",
                    "--metric",
                    "estimated_bram=16",
                ]
            )

            self.assertEqual(payload["schema_version"], "qe_dse_fpga_asic_implementation_evidence_v0")
            self.assertEqual(payload["execution_status"], "external_evidence_referenced")
            self.assertEqual(payload["candidate_id"], "candidate_f1")
            self.assertEqual(payload["implementation_target_class"], "fpga")
            self.assertEqual(payload["evidence_kind"], "hls_synthesis")
            self.assertEqual(payload["evidence_status"], "available")
            self.assertEqual(payload["claim_ceiling"], "hls_synthesis_only")
            self.assertEqual(payload["metrics"]["estimated_lut"], 1200)
            self.assertEqual(payload["metrics"]["estimated_bram"], 16)

    def test_output_is_overclaim_safe_even_with_correctness_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            output = tmp / "evidence.json"
            correctness_report = self.write_qe_correctness(tmp / "qe_correctness.json", "candidate_f1")

            payload = self.run_materializer(
                [
                    "--candidate-id",
                    "candidate_f1",
                    "--output",
                    str(output),
                    "--implementation-target-class",
                    "fpga",
                    "--evidence-kind",
                    "implementation_projection",
                    "--evidence-status",
                    "available",
                    "--artifact-ref",
                    "projection_note=artifacts/implementation/projection_note.json",
                    "--metric",
                    "projected_latency_cycles=42",
                    "--qe-correctness-report",
                    str(correctness_report),
                ]
            )

            self.assertEqual(payload["evidence_kind"], "implementation_projection")
            self.assertEqual(payload["evidence_status"], "partial")
            self.assertEqual(payload["claim_ceiling"], "implementation_evidence_only")
            self.assertIsNone(payload["final_public_family_winner"])
            self.assertFalse(payload["public_winner_claim"])
            self.assertFalse(payload["production_release_ready"])
            self.assertTrue(payload["correctness_dependency"]["qe_equivalent_scf_claim"])
            self.assertEqual(payload["correctness_dependency"]["qe_correctness_report_ref"], str(correctness_report))

    def test_multi_candidate_map_materializes_dependency_safe_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            stage_c_f3 = self.write_qe_correctness(tmp / "stage_c_f3.json", "candidate_f3")
            stage_c_f2 = self.write_qe_correctness(tmp / "stage_c_f2.json", "candidate_f2", claim=False)
            candidate_map = tmp / "stage_d_map.json"
            candidate_map.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "candidate_id": "candidate_f3",
                                "implementation_target_class": "fpga",
                                "evidence_kind": "hls_synthesis",
                                "artifact_refs": {"hls_report": "artifacts/f3_hls.json"},
                                "metrics": {"estimated_lut": 1200, "estimated_bram": 16},
                            },
                            {
                                "candidate_id": "candidate_f2",
                                "implementation_target_class": "fpga",
                                "evidence_kind": "implementation_projection",
                                "artifact_refs": {"projection_note": "artifacts/f2_projection.json"},
                                "metrics": {"projected_latency_cycles": 42},
                            },
                        ]
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            matrix = MODULE_ANY.materialize_many(
                candidate_evidence_map=candidate_map,
                output_dir=tmp / "out",
                qe_correctness_report_for={
                    "candidate_f3": stage_c_f3,
                    "candidate_f2": stage_c_f2,
                },
            )

            self.assertEqual(matrix["row_count"], 2)
            rows = {row["candidate_id"]: row for row in matrix["rows"]}
            self.assertEqual(rows["candidate_f3"]["evidence_kind"], "hls_synthesis")
            self.assertEqual(rows["candidate_f3"]["evidence_status"], "available")
            self.assertEqual(rows["candidate_f3"]["claim_ceiling"], "hls_synthesis_only")
            self.assertTrue(rows["candidate_f3"]["qe_equivalent_scf_claim"])
            self.assertEqual(rows["candidate_f2"]["evidence_kind"], "implementation_projection")
            self.assertEqual(rows["candidate_f2"]["evidence_status"], "partial")
            self.assertFalse(rows["candidate_f2"]["qe_equivalent_scf_claim"])
            for row in rows.values():
                self.assertTrue(Path(row["report_path"]).exists())

    def test_multi_candidate_map_rejects_qe_dependency_candidate_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            wrong_stage_c = self.write_qe_correctness(tmp / "wrong_stage_c.json", "candidate_other")
            candidate_map = tmp / "stage_d_map.json"
            candidate_map.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "candidate_id": "candidate_f3",
                                "implementation_target_class": "fpga",
                                "evidence_kind": "hls_synthesis",
                                "qe_correctness_report": str(wrong_stage_c),
                                "artifact_refs": {"hls_report": "artifacts/f3_hls.json"},
                                "metrics": {"estimated_lut": 1200, "estimated_bram": 16},
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(MODULE_ANY.EvidenceInputError, "candidate_id must match"):
                MODULE_ANY.materialize_many(
                    candidate_evidence_map=candidate_map,
                    output_dir=tmp / "out",
                )


if __name__ == "__main__":
    raise SystemExit(unittest.main())
