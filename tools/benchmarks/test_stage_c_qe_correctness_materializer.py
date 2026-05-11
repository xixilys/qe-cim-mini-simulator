from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("materialize_qe_stage_c_correctness_v0.py")
SPEC = importlib.util.spec_from_file_location("materialize_qe_stage_c_correctness_v0", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class StageCQeCorrectnessMaterializerTests(unittest.TestCase):
    def test_pass_row_materializes_claiming_report_and_matrix(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage-c-materializer-pass-") as tmp:
            root = Path(tmp)
            compare_path = root / "artifacts/compare/si8__F1.compare.json"
            candidate_path = root / "artifacts/candidate/si8__F1.json"
            baseline_path = root / "artifacts/baseline/si8.gold.json"
            write_json(
                compare_path,
                {
                    "schema_name": "qe_gold_numerical_tolerance_schema_v0",
                    "schema_version": "2026-04-13",
                    "baseline_file": str(baseline_path),
                    "candidate_file": str(candidate_path),
                    "overall_pass": True,
                    "summary": {"status": "pass", "failed_required_fields": []},
                },
            )
            summary_path = root / "qe_gold_gate_summary_v0.json"
            write_json(
                summary_path,
                {
                    "schema_version": "qe_gold_gate_summary_v0",
                    "run_id": "run-pass",
                    "gold_rows": [
                        {
                            "status": "pass",
                            "workload_id": "si8_pbe_nc",
                            "family": "F1",
                            "metrics_path": str(candidate_path),
                            "compare_report_path": str(compare_path),
                        }
                    ],
                },
            )

            matrix = MODULE.materialize(summary_path, root / "out")

            self.assertEqual(matrix["row_count"], 1)
            self.assertEqual(matrix["qe_equivalent_scf_claim_true"], 1)
            row = matrix["rows"][0]
            self.assertEqual(row["candidate_id"], "si8__F1")
            self.assertTrue(row["qe_equivalent_scf_claim"])
            self.assertEqual(row["claim_ceiling"], "qe_equivalent_scf_correctness_only")
            report = json.loads(Path(row["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["correctness_status"], "pass")
            self.assertTrue(report["qe_equivalent_scf_claim"])
            self.assertEqual(report["compare_report"]["overall_pass"], True)
            self.assertEqual(report["evidence_refs"]["baseline"], str(baseline_path))
            self.assertEqual(report["evidence_refs"]["candidate"], str(candidate_path))
            self.assertEqual(report["evidence_refs"]["compare_report"], str(compare_path))
            self.assertTrue((root / "out/stage_c_correctness_matrix_v0.json").exists())

    def test_f3_mismatch_materializes_reference_only_non_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage-c-materializer-f3-") as tmp:
            root = Path(tmp)
            compare_path = root / "artifacts/compare/si8__F3.compare.json"
            candidate_path = root / "artifacts/candidate/si8__F3.json"
            baseline_path = root / "artifacts/baseline/si8.gold.json"
            write_json(
                compare_path,
                {
                    "schema_name": "qe_gold_numerical_tolerance_schema_v0",
                    "schema_version": "2026-04-13",
                    "baseline_file": str(baseline_path),
                    "candidate_file": str(candidate_path),
                    "overall_pass": False,
                    "summary": {
                        "status": "fail",
                        "failed_required_fields": ["final_total_energy_ry"],
                    },
                },
            )
            summary_path = root / "qe_gold_gate_summary_v0.json"
            write_json(
                summary_path,
                {
                    "schema_version": "qe_gold_gate_summary_v0",
                    "run_id": "run-f3",
                    "gold_rows": [
                        {
                            "status": "mismatch",
                            "workload_id": "si8_pbe_nc",
                            "family": "F3",
                            "metrics_path": str(candidate_path),
                            "compare_report_path": str(compare_path),
                        }
                    ],
                },
            )

            matrix = MODULE.materialize(summary_path, root / "out")

            self.assertEqual(matrix["status_counts"], {"mismatch": 1})
            self.assertEqual(matrix["qe_equivalent_scf_claim_false"], 1)
            row = matrix["rows"][0]
            self.assertEqual(row["candidate_id"], "si8__F3")
            self.assertEqual(row["correctness_status"], "mismatch")
            self.assertFalse(row["qe_equivalent_scf_claim"])
            self.assertEqual(row["claim_ceiling"], "correctness_report_reference_only")
            report = json.loads(Path(row["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["correctness_status"], "mismatch")
            self.assertFalse(report["qe_equivalent_scf_claim"])
            self.assertEqual(report["claim_ceiling"], "correctness_report_reference_only")
            self.assertEqual(report["compare_report"]["summary"]["failed_required_fields"], ["final_total_energy_ry"])

    def test_candidate_map_resolves_current_e2e_candidate_id_when_gold_row_lacks_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage-c-materializer-map-") as tmp:
            root = Path(tmp)
            compare_path = root / "compare.json"
            write_json(
                compare_path,
                {
                    "schema_name": "qe_gold_numerical_tolerance_schema_v0",
                    "schema_version": "2026-04-13",
                    "overall_pass": True,
                    "summary": {"status": "pass", "failed_required_fields": []},
                },
            )
            summary_path = root / "qe_gold_gate_summary_v0.json"
            write_json(
                summary_path,
                {
                    "schema_version": "qe_gold_gate_summary_v0",
                    "run_id": "run-map",
                    "gold_rows": [
                        {
                            "status": "pass",
                            "workload_id": "si4_pbe_uspp_small",
                            "family": "F3",
                            "diag_policy": "device_first_fallback",
                            "metrics_path": "stale_candidate_name.json",
                            "compare_report_path": str(compare_path),
                        }
                    ],
                },
            )
            candidate_map = root / "candidate_map.json"
            write_json(
                candidate_map,
                {
                    "candidates": [
                        {
                            "candidate_id": (
                                "si4_pbe_uspp_small__F3__device_first_fallback__"
                                "single_hotpath__fit_first__single_hotpath_partition"
                            ),
                            "workload_id": "si4_pbe_uspp_small",
                            "family": "F3",
                            "design_axes": {"diag_policy": "device_first_fallback"},
                        }
                    ]
                },
            )

            matrix = MODULE.materialize(summary_path, root / "out", candidate_map_path=candidate_map)

            row = matrix["rows"][0]
            self.assertEqual(
                row["candidate_id"],
                "si4_pbe_uspp_small__F3__device_first_fallback__single_hotpath__fit_first__single_hotpath_partition",
            )
            self.assertEqual(matrix["candidate_map_ref"], str(candidate_map))
            report = json.loads(Path(row["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["candidate_id"], row["candidate_id"])

    def test_candidate_map_ambiguous_match_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage-c-materializer-ambiguous-") as tmp:
            root = Path(tmp)
            summary_path = root / "qe_gold_gate_summary_v0.json"
            write_json(
                summary_path,
                {
                    "schema_version": "qe_gold_gate_summary_v0",
                    "run_id": "run-ambiguous",
                    "gold_rows": [{"status": "pass", "workload_id": "si4", "family": "F2"}],
                },
            )
            candidate_map = root / "candidate_map.json"
            write_json(
                candidate_map,
                {
                    "candidates": [
                        {"candidate_id": "candidate_a", "workload_id": "si4", "family": "F2"},
                        {"candidate_id": "candidate_b", "workload_id": "si4", "family": "F2"},
                    ]
                },
            )

            with self.assertRaisesRegex(ValueError, "ambiguous"):
                MODULE.materialize(summary_path, root / "out", candidate_map_path=candidate_map)

    def test_candidate_map_missing_match_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage-c-materializer-missing-") as tmp:
            root = Path(tmp)
            summary_path = root / "qe_gold_gate_summary_v0.json"
            write_json(
                summary_path,
                {
                    "schema_version": "qe_gold_gate_summary_v0",
                    "run_id": "run-missing",
                    "gold_rows": [{"status": "pass", "workload_id": "si4", "family": "F3"}],
                },
            )
            candidate_map = root / "candidate_map.json"
            write_json(
                candidate_map,
                {"candidates": [{"candidate_id": "candidate_f2", "workload_id": "si4", "family": "F2"}]},
            )

            with self.assertRaisesRegex(ValueError, "no exact candidate-map match"):
                MODULE.materialize(summary_path, root / "out", candidate_map_path=candidate_map)


if __name__ == "__main__":
    unittest.main()
