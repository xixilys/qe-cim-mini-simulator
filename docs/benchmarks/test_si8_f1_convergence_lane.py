from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("run_systemc_architecture_family_dse_sweep.py")
SPEC = importlib.util.spec_from_file_location("run_systemc_architecture_family_dse_sweep", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Si8F1ConvergenceLaneTests(unittest.TestCase):
    def sample_row(self, metrics_path: str) -> dict[str, object]:
        return {
            "result_id": "si8_pbe_nc__F1__cpu_only__single_hotpath__fit_first",
            "workload": {
                "workload_id": "si8_pbe_nc",
                "gold_required": True,
            },
            "design_point": {
                "family": "F1",
                "canonical_profile_match": True,
            },
            "correctness": {
                "notes": [],
            },
            "artifacts": {
                "metrics_path": metrics_path,
                "raw_trace_paths": [],
            },
        }

    def sample_baseline_payload(self) -> dict[str, object]:
        return {
            "final": {
                "total_energy_ry": -62.28748772,
                "converged": True,
                "residual_threshold_reached": True,
                "scf_iterations": 8,
            }
        }

    def sample_candidate_payload(self) -> dict[str, object]:
        return {
            "run_config": {
                "max_scf_iters": 8,
            },
            "final": {
                "total_energy_ry": -11.60964194917396,
                "converged": True,
                "residual_threshold_reached": True,
                "scf_iterations": 3,
                "residual_norm": 0.28,
                "density_delta": 0.0692,
            },
            "iteration_diagnostics": [
                {
                    "scf_iteration": 1,
                    "total_energy_ry": -11.18,
                    "diag_path": "host_cpu_fallback",
                    "cpu_diag_fallback": True,
                    "resident_reused": False,
                    "spill_active": False,
                    "used_device_fft": False,
                },
                {
                    "scf_iteration": 2,
                    "total_energy_ry": -11.41,
                    "diag_path": "host_cpu_fallback",
                    "cpu_diag_fallback": True,
                    "resident_reused": True,
                    "spill_active": False,
                    "used_device_fft": False,
                },
                {
                    "scf_iteration": 3,
                    "total_energy_ry": -11.60964194917396,
                    "diag_path": "host_cpu_fallback",
                    "cpu_diag_fallback": True,
                    "resident_reused": True,
                    "spill_active": False,
                    "used_device_fft": False,
                },
            ],
        }

    def sample_compare_report(self) -> dict[str, object]:
        return {
            "overall_pass": False,
            "field_results": [
                {
                    "name": "final_total_energy_ry",
                    "required": True,
                    "status": "fail",
                    "abs_err": 50.67784577082604,
                    "rel_err": 0.8136119728995556,
                },
                {
                    "name": "final_converged",
                    "required": True,
                    "status": "pass",
                },
                {
                    "name": "final_residual_threshold_reached",
                    "required": True,
                    "status": "pass",
                },
                {
                    "name": "scf_iterations",
                    "required": False,
                    "status": "fail",
                },
            ],
        }

    def test_build_report_flags_energy_trajectory_blocker(self) -> None:
        row = self.sample_row(metrics_path="unused.json")
        report = MODULE.build_si8_f1_convergence_report(
            row,
            self.sample_baseline_payload(),
            self.sample_candidate_payload(),
            self.sample_compare_report(),
        )

        self.assertEqual(report["dominant_blocker"]["kind"], "energy_trajectory_mismatch")
        self.assertEqual(report["iteration_context"]["last_diag_path"], "host_cpu_fallback")
        self.assertEqual(report["gap_report"]["candidate_iterations"], 3)
        self.assertEqual(report["gap_report"]["baseline_iterations"], 8)
        self.assertIn("host_cpu_fallback", report["explicit_next_narrowing_move"])

    def test_emit_artifacts_writes_json_and_markdown(self) -> None:
        candidate_payload = self.sample_candidate_payload()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps(candidate_payload), encoding="utf-8")
            row = self.sample_row(metrics_path=str(candidate_path))

            paths = MODULE.emit_si8_f1_convergence_artifacts(
                row,
                tmp_path,
                self.sample_baseline_payload(),
                self.sample_compare_report(),
            )

            self.assertEqual(len(paths), 2)
            report_json_path, report_md_path = paths
            self.assertTrue(report_json_path.exists())
            self.assertTrue(report_md_path.exists())

            report = json.loads(report_json_path.read_text(encoding="utf-8"))
            self.assertEqual(report["priority_target"]["first_priority_convergence_case"], True)
            self.assertIn(str(report_json_path), row["artifacts"]["raw_trace_paths"])
            self.assertIn("si8_f1_convergence_report=", row["correctness"]["notes"][0])


if __name__ == "__main__":
    unittest.main()
