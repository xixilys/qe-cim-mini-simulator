from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("render_qe_phase1_evidence_closure_md.py")
SPEC = importlib.util.spec_from_file_location("render_qe_phase1_evidence_closure_md", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RenderPhase1EvidenceClosureMdTests(unittest.TestCase):
    def test_render_contains_summary_and_case_rows(self) -> None:
        report = {
            "summary": {
                "repo_internal_status": "complete",
                "decisive_lane_closed": False,
                "next_blocker_class": "external_measurement_artifacts",
                "gpu_decisive_ready_cases": 1,
                "board_ready_cases": 1,
                "thesis_count_candidate_ready_cases": 1,
                "decisive_lane_targets": ["si4_pbe_uspp_small", "graphene_pbe_uspp"],
            },
            "case_matrix": [
                {
                    "case_id": "si4_pbe_uspp_small",
                    "gpu_decisive_ready": True,
                    "board_ready": True,
                    "thesis_count_candidate_ready": True,
                    "gpu_blockers": [],
                    "board_blockers": [],
                },
                {
                    "case_id": "graphene_pbe_uspp",
                    "gpu_decisive_ready": False,
                    "board_ready": False,
                    "thesis_count_candidate_ready": False,
                    "gpu_blockers": ["missing_gpu_bundle"],
                    "board_blockers": ["missing_board_bundle"],
                },
            ],
            "gpu_rows": [
                {
                    "case_id": "si4_pbe_uspp_small",
                    "gpu_mode": "practical",
                    "status": "thesis_eligible",
                    "decisive_for_case": True,
                    "case_ready": True,
                    "reason": "all_phase1_gates_closed",
                }
            ],
            "board_rows": [
                {
                    "case_id": "si4_pbe_uspp_small",
                    "status": "board_ready",
                }
            ],
        }
        md = MODULE.render_markdown(report)
        self.assertIn("# QE Phase-1 Evidence Closure Summary", md)
        self.assertIn("`si4_pbe_uspp_small`", md)
        self.assertIn("external_measurement_artifacts", md)
        self.assertIn("missing_gpu_bundle", md)

    def test_main_writes_markdown_file(self) -> None:
        report = {
            "summary": {
                "repo_internal_status": "complete",
                "decisive_lane_closed": True,
                "next_blocker_class": "none",
                "gpu_decisive_ready_cases": 2,
                "board_ready_cases": 2,
                "thesis_count_candidate_ready_cases": 2,
                "decisive_lane_targets": ["si4_pbe_uspp_small", "graphene_pbe_uspp"],
            },
            "case_matrix": [],
            "gpu_rows": [],
            "board_rows": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "report.json"
            out_path = Path(tmpdir) / "report.md"
            in_path.write_text(json.dumps(report), encoding="utf-8")
            args = type("Args", (), {"input": in_path, "output": out_path})()
            loaded = MODULE.load_report(args.input)
            out_path.write_text(MODULE.render_markdown(loaded), encoding="utf-8")
            self.assertTrue(out_path.exists())
            self.assertIn("decisive_lane_closed", out_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
