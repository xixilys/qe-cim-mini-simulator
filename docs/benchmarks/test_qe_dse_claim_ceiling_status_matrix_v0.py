from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("build_qe_dse_claim_ceiling_status_matrix_v0.py")
SPEC = importlib.util.spec_from_file_location("build_qe_dse_claim_ceiling_status_matrix_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


def stage_c_report(candidate_id: str = "candidate_f1") -> dict[str, Any]:
    return {
        "schema_version": "qe_dse_qe_equivalent_correctness_report_v0",
        "execution_status": "executed",
        "claim_ceiling": "qe_equivalent_scf_correctness_only",
        "report_id": "stage_c_fixture",
        "candidate_id": candidate_id,
        "workload_id": "si8_pbe_nc",
        "case_id": "si8_pbe_nc",
        "family": "F1",
        "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
        "correctness_status": "pass",
        "qe_equivalent_scf_claim": True,
        "compare_report": {
            "schema_name": "qe_gold_numerical_tolerance_schema_v0",
            "schema_version": "2026-04-13",
            "overall_pass": True,
            "summary": {"status": "pass", "failed_required_fields": []},
        },
        "evidence_refs": {},
    }


def stage_d_projection(candidate_id: str = "candidate_f1") -> dict[str, Any]:
    return {
        "schema_version": "qe_dse_fpga_asic_implementation_evidence_v0",
        "execution_status": "external_evidence_referenced",
        "evidence_id": "stage_d_projection_fixture",
        "candidate_id": candidate_id,
        "implementation_target_class": "fpga",
        "evidence_kind": "implementation_projection",
        "evidence_status": "partial",
        "claim_ceiling": "implementation_evidence_only",
        "artifact_refs": {"projection_note": "artifacts/implementation/projection_note.json"},
        "metrics": {"projected_latency_cycles": 42},
        "correctness_dependency": {
            "qe_equivalent_scf_claim": True,
            "qe_correctness_report_ref": "stage_c.json",
        },
        "final_public_family_winner": None,
        "public_winner_claim": False,
        "production_release_ready": False,
    }


class QeDseClaimCeilingStatusMatrixTests(unittest.TestCase):
    def test_stage_c_pass_plus_stage_d_projection_remains_partial_evidence_only(self) -> None:
        matrix = MODULE_ANY.build_matrix(
            candidate_id="candidate_f1",
            family="F1",
            stage_c_report_ref=Path("stage_c.json"),
            stage_c_report=stage_c_report(),
            implementation_evidence_ref=Path("stage_d.json"),
            implementation_evidence=stage_d_projection(),
            b2_report_ref=Path("b2.json"),
            b2_report={
                "candidate_id": "candidate_f1",
                "execution_status": "executed",
                "backend_class": "systemc_timed_functional_proxy",
                "claim_ceiling": "systemc_proxy_only",
                "metrics": {"cycle_proxy": 100},
            },
        )

        self.assertEqual(matrix["schema_version"], "claim_ceiling_status_matrix_v0")
        self.assertEqual(matrix["adjudicator_permission_scope"], "not_evaluated")
        row = matrix["rows"][0]
        self.assertTrue(row["qe_equivalent_scf_claim"])
        self.assertEqual(row["evidence_status"], "partial")
        self.assertEqual(
            row["final_observed_conclusion_ceiling"],
            "qe_equivalent_scf_correctness_plus_partial_implementation_projection_only",
        )
        self.assertIn("stage_d_implementation_evidence_not_available", row["blockers"])
        self.assertIn("no_final_public_winner", row["non_claims"])

    def test_missing_stage_c_and_d_are_reported_as_blockers_not_permissions(self) -> None:
        matrix = MODULE_ANY.build_matrix(
            candidate_id="candidate_f2",
            b2_report={
                "candidate_id": "candidate_f2",
                "execution_status": "executed",
                "backend_class": "systemc_timed_functional_proxy",
                "claim_ceiling": "systemc_proxy_only",
            },
        )

        row = matrix["rows"][0]
        self.assertEqual(row["adjudicator_permission_scope"], "not_evaluated")
        self.assertEqual(row["final_observed_conclusion_ceiling"], "systemc_proxy_only")
        self.assertEqual(
            row["blockers"],
            ["missing_stage_c_qe_correctness_report", "missing_stage_d_implementation_evidence"],
        )

    def test_cli_writes_json_and_markdown_with_validated_stage_c_d_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stage_c = root / "stage_c.json"
            stage_d = root / "stage_d.json"
            output = root / "claim_matrix.json"
            markdown = root / "claim_matrix.md"
            stage_c.write_text(json.dumps(stage_c_report(), indent=2) + "\n", encoding="utf-8")
            stage_d.write_text(json.dumps(stage_d_projection(), indent=2) + "\n", encoding="utf-8")

            rc = MODULE_ANY.main(
                [
                    "--output",
                    str(output),
                    "--markdown-output",
                    str(markdown),
                    "--stage-c-report",
                    str(stage_c),
                    "--implementation-evidence",
                    str(stage_d),
                ]
            )

            self.assertEqual(rc, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["row_count"], 1)
            self.assertEqual(payload["rows"][0]["candidate_id"], "candidate_f1")
            self.assertIn("not an adjudicator permission matrix", markdown.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
