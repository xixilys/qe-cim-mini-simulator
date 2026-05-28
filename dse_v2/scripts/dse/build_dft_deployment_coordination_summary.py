#!/usr/bin/env python3
"""Build a DFT deployment coordination summary across three Codex lanes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_deployment_coordination import (  # noqa: E402
    write_dft_deployment_coordination_summary,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="DFT Step5 run directory containing FPGA/ASIC deployment summary artifacts.",
    )
    parser.add_argument(
        "--search-loop-summary",
        type=Path,
        required=True,
        help="Search effectiveness loop pilot summary proving control-plane candidate progression.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Output directory for coordination artifacts. Defaults to --run-dir.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    status = write_dft_deployment_coordination_summary(
        run_dir=args.run_dir,
        out_dir=args.out_dir,
        search_loop_summary_path=args.search_loop_summary,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
