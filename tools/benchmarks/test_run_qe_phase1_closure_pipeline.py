from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PIPELINE_PATH = Path(__file__).with_name("run_qe_phase1_closure_pipeline.py")
PIPELINE_SPEC = importlib.util.spec_from_file_location("run_qe_phase1_closure_pipeline", PIPELINE_PATH)
PIPELINE = importlib.util.module_from_spec(PIPELINE_SPEC)
assert PIPELINE_SPEC is not None
assert PIPELINE_SPEC.loader is not None
PIPELINE_SPEC.loader.exec_module(PIPELINE)

INIT_PATH = Path(__file__).with_name("init_qe_phase1_artifact_bundle.py")
INIT_SPEC = importlib.util.spec_from_file_location("init_qe_phase1_artifact_bundle", INIT_PATH)
INIT = importlib.util.module_from_spec(INIT_SPEC)
assert INIT_SPEC is not None
assert INIT_SPEC.loader is not None
INIT_SPEC.loader.exec_module(INIT)


class RunPhase1ClosurePipelineTests(unittest.TestCase):
    def make_gpu_dir(self, root: Path, name: str, *, gpu_mode: str, time_s: float) -> Path:
        target = root / name
        INIT.main(
            [
                "baseline",
                "--out-dir",
                str(target),
                "--workload-id",
                "si4_pbe_uspp_small",
                "--gpu-mode",
                gpu_mode,
                "--run-tag",
                "20260414-150000",
            ]
        )
        manifest_path = target / "cpu_gpu_baseline_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["gpu_mode_attempts"] = ["strict_fp64", "practical"]
        manifest["shared_rewrite_closed"] = True
        manifest["host_platform_comparable"] = True
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        rewrite_path = target / "algorithm_rewrite_manifest.json"
        rewrite = json.loads(rewrite_path.read_text(encoding="utf-8"))
        rewrite["entries"][0]["review_status"] = "accepted"
        rewrite["entries"][0]["gpu_enabled_in_baseline"] = "yes"
        rewrite_path.write_text(json.dumps(rewrite, indent=2) + "\n", encoding="utf-8")

        artifacts = manifest["artifact_paths"]
        for key in ["stdout", "stderr", "summary"]:
            (target / artifacts[key]).write_text(key, encoding="utf-8")
        (target / artifacts["correctness"]).write_text(
            json.dumps({"gold_pass": True, "convergence_comparable_pass": True}, indent=2) + "\n",
            encoding="utf-8",
        )
        (target / artifacts["convergence"]).write_text(
            json.dumps({"convergence_comparable_pass": True}, indent=2) + "\n",
            encoding="utf-8",
        )
        (target / artifacts["timing"]).write_text(
            json.dumps({"time_to_convergence_s": time_s}, indent=2) + "\n",
            encoding="utf-8",
        )
        (target / artifacts["power"]).write_text(
            json.dumps({"avg_whole_node_power_w": 150.0, "energy_to_solution_j": 150.0 * time_s}, indent=2) + "\n",
            encoding="utf-8",
        )
        return target

    def make_board_dir(self, root: Path, name: str) -> Path:
        target = root / name
        INIT.main(
            [
                "board",
                "--out-dir",
                str(target),
                "--workload-id",
                "si4_pbe_uspp_small",
                "--architecture-family",
                "F2",
                "--assumption-set-id",
                "phase1_calibrated_v0",
                "--request-id",
                "REQ-001",
                "--scf-iteration",
                "6",
                "--episode-id",
                "2",
            ]
        )
        return target

    def test_pipeline_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            strict_dir = self.make_gpu_dir(root, "strict", gpu_mode="strict_fp64", time_s=12.0)
            practical_dir = self.make_gpu_dir(root, "practical", gpu_mode="practical", time_s=9.0)
            board_dir = self.make_board_dir(root, "board")
            prefix = root / "closure_report"

            rc = PIPELINE.main.__wrapped__ if hasattr(PIPELINE.main, "__wrapped__") else None
            # fallback to direct main via argv monkeypatch style
            import sys

            old_argv = sys.argv
            try:
                sys.argv = [
                    "run_qe_phase1_closure_pipeline.py",
                    "--gpu-baseline-dir",
                    str(strict_dir),
                    "--gpu-baseline-dir",
                    str(practical_dir),
                    "--board-dir",
                    str(board_dir),
                    "--output-prefix",
                    str(prefix),
                ]
                result = PIPELINE.main()
            finally:
                sys.argv = old_argv

            self.assertEqual(result, 0)
            json_path = prefix.with_suffix(".json")
            md_path = prefix.with_suffix(".md")
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            report = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["repo_internal_status"], "complete")
            si4_row = next(
                row for row in report["case_matrix"] if row["case_id"] == "si4_pbe_uspp_small"
            )
            self.assertTrue(si4_row["thesis_count_candidate_ready"])
            self.assertIn("QE Phase-1 Evidence Closure Summary", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
