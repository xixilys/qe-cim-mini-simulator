#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARKS_DIR = SCRIPT_DIR.parent
if str(BENCHMARKS_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_DIR))

import materialize_qe_stage_d_implementation_evidence_v0 as stage_d_materializer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize Stage-D HLS synthesis evidence for candidate-id keyed final-best manifests. "
            "Input map entries must provide real artifact_refs.hls_report plus estimated_lut and "
            "estimated_bram or fmax_mhz metrics; placeholder data is downgraded to projection."
        )
    )
    parser.add_argument("--candidate-evidence-map", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--qe-correctness-report-for", action="append", default=[], metavar="candidate_id=path")
    parser.add_argument("--matrix-name", default=stage_d_materializer.DEFAULT_MATRIX_NAME)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    qe_correctness_report_for = stage_d_materializer.parse_path_bindings(
        args.qe_correctness_report_for,
        "--qe-correctness-report-for",
    )
    stage_d_materializer.materialize_many(
        candidate_evidence_map=args.candidate_evidence_map,
        output_dir=args.output_dir,
        implementation_target_class="fpga",
        evidence_kind="hls_synthesis",
        evidence_status="available",
        qe_correctness_report_for=qe_correctness_report_for,
        matrix_name=args.matrix_name,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
