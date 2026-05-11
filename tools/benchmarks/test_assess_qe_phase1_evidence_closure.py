from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("assess_qe_phase1_evidence_closure.py")
SPEC = importlib.util.spec_from_file_location("assess_qe_phase1_evidence_closure", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

INIT_PATH = Path(__file__).with_name("init_qe_phase1_artifact_bundle.py")
INIT_SPEC = importlib.util.spec_from_file_location("init_qe_phase1_artifact_bundle", INIT_PATH)
INIT = importlib.util.module_from_spec(INIT_SPEC)
assert INIT_SPEC is not None
assert INIT_SPEC.loader is not None
INIT_SPEC.loader.exec_module(INIT)


class AssessPhase1EvidenceClosureTests(unittest.TestCase):
    def make_gpu_dir(self, root: Path, name: str, *, gpu_mode: str, case_id: str, time_s: float) -> Path:
        target = root / name
        args = [
            "baseline",
            "--out-dir", str(target),
            "--workload-id", case_id,
            "--gpu-mode", gpu_mode,
            "--run-tag", "20260414-140000",
        ]
        INIT.main(args)
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
        rewrite["entries"][0]["affected_workload_ids"] = [case_id]
        rewrite_path.write_text(json.dumps(rewrite, indent=2) + "\n", encoding="utf-8")
        a = manifest["artifact_paths"]
        for key in ["stdout", "stderr", "summary"]:
            (target / a[key]).write_text(key, encoding="utf-8")
        (target / a["correctness"]).write_text(
            json.dumps({"gold_pass": True, "convergence_comparable_pass": True}, indent=2) + "\n",
            encoding="utf-8",
        )
        (target / a["convergence"]).write_text(
            json.dumps({"convergence_comparable_pass": True}, indent=2) + "\n",
            encoding="utf-8",
        )
        (target / a["timing"]).write_text(
            json.dumps({"time_to_convergence_s": time_s}, indent=2) + "\n",
            encoding="utf-8",
        )
        (target / a["power"]).write_text(
            json.dumps({"avg_whole_node_power_w": 150.0, "energy_to_solution_j": 150.0 * time_s}, indent=2) + "\n",
            encoding="utf-8",
        )
        return target

    def make_board_dir(self, root: Path, name: str, *, case_id: str) -> Path:
        target = root / name
        args = [
            "board",
            "--out-dir", str(target),
            "--workload-id", case_id,
            "--architecture-family", "F2",
            "--assumption-set-id", "phase1_calibrated_v0",
            "--request-id", "REQ-001",
            "--scf-iteration", "6",
            "--episode-id", "2",
        ]
        INIT.main(args)
        return target

    def test_decisive_lane_is_closed_only_when_gpu_and_board_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gpu_dirs = [
                self.make_gpu_dir(root, "si4_strict", gpu_mode="strict_fp64", case_id="si4_pbe_uspp_small", time_s=12.0),
                self.make_gpu_dir(root, "si4_practical", gpu_mode="practical", case_id="si4_pbe_uspp_small", time_s=9.0),
                self.make_gpu_dir(root, "graphene_strict", gpu_mode="strict_fp64", case_id="graphene_pbe_uspp", time_s=11.0),
                self.make_gpu_dir(root, "graphene_practical", gpu_mode="practical", case_id="graphene_pbe_uspp", time_s=8.0),
            ]
            board_dirs = [
                self.make_board_dir(root, "si4_board", case_id="si4_pbe_uspp_small"),
                self.make_board_dir(root, "graphene_board", case_id="graphene_pbe_uspp"),
            ]
            gpu_rows, gpu_by_case = MODULE.assess_gpu_rows([str(p) for p in gpu_dirs])
            board_rows, board_by_case = MODULE.assess_board_dirs([str(p) for p in board_dirs])
            case_matrix = MODULE.build_case_matrix(gpu_by_case, board_by_case)
            summary = MODULE.build_summary(gpu_rows, board_rows, case_matrix)
            self.assertTrue(summary["summary"]["decisive_lane_closed"])
            self.assertEqual(summary["summary"]["thesis_count_candidate_ready_cases"], 2)

    def test_missing_board_artifacts_keep_case_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gpu_dirs = [
                self.make_gpu_dir(root, "si4_strict", gpu_mode="strict_fp64", case_id="si4_pbe_uspp_small", time_s=12.0),
                self.make_gpu_dir(root, "si4_practical", gpu_mode="practical", case_id="si4_pbe_uspp_small", time_s=9.0),
            ]
            gpu_rows, gpu_by_case = MODULE.assess_gpu_rows([str(p) for p in gpu_dirs])
            board_rows, board_by_case = MODULE.assess_board_dirs([])
            case_matrix = MODULE.build_case_matrix(gpu_by_case, board_by_case)
            summary = MODULE.build_summary(gpu_rows, board_rows, case_matrix)
            self.assertFalse(summary["summary"]["decisive_lane_closed"])
            self.assertEqual(summary["summary"]["thesis_count_candidate_ready_cases"], 0)


if __name__ == "__main__":
    unittest.main()
