#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = ROOT / "docs/benchmarks"
TOOLS_BENCHMARKS_DIR = Path(__file__).resolve().parent
ASSESSOR_PATH = TOOLS_BENCHMARKS_DIR / "assess_qe_phase1_evidence_closure.py"
RENDERER_PATH = TOOLS_BENCHMARKS_DIR / "render_qe_phase1_evidence_closure_md.py"


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the phase-1 evidence-closure JSON+Markdown pipeline for incoming GPU/FPGA artifact directories."
    )
    parser.add_argument(
        "--gpu-baseline-dir",
        action="append",
        default=[],
        help="CPU+GPU baseline directory. May be repeated.",
    )
    parser.add_argument(
        "--board-dir",
        action="append",
        default=[],
        help="FPGA board artifact directory. May be repeated.",
    )
    parser.add_argument(
        "--output-prefix",
        required=True,
        type=Path,
        help="Output prefix path without suffix. The pipeline writes <prefix>.json and <prefix>.md.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    assessor = load_module(ASSESSOR_PATH, "qe_phase1_evidence_closure")
    renderer = load_module(RENDERER_PATH, "qe_phase1_evidence_closure_md")

    json_path = args.output_prefix.with_suffix(".json")
    md_path = args.output_prefix.with_suffix(".md")

    assessor_args = type(
        "Args",
        (),
        {
            "gpu_baseline_dir": args.gpu_baseline_dir,
            "board_dir": args.board_dir,
            "output": json_path,
        },
    )()
    gpu_rows, gpu_by_case = assessor.assess_gpu_rows(assessor_args.gpu_baseline_dir)
    board_rows, board_by_case = assessor.assess_board_dirs(assessor_args.board_dir)
    case_matrix = assessor.build_case_matrix(gpu_by_case, board_by_case)
    report = assessor.build_summary(gpu_rows, board_rows, case_matrix)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(__import__("json").dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md_path.write_text(renderer.render_markdown(report), encoding="utf-8")
    print(json_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
