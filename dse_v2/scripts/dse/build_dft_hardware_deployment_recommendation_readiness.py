#!/usr/bin/env python3
"""Build fail-closed DFT/QE FPGA/ASIC deployment-recommendation readiness.

The readiness bundle is coordination evidence only.  It may show whether
hardware-PPA winner names are ready to be surfaced, but it never names final
deployment recommendations or marks deliverable completion.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_hardware_deployment_recommendation_readiness import (  # noqa: E402
    write_dft_hardware_deployment_recommendation_readiness,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=None, help="Run/output directory for readiness artifacts")
    parser.add_argument("--out", type=Path, default=None, help="Backward-compatible alias for --run-dir")
    parser.add_argument("--hardware-completion-workplan", type=Path, default=None)
    parser.add_argument("--tie-breaker-execution-queue", type=Path, default=None)
    parser.add_argument("--candidate-specific-ppa-freshness-queue", type=Path, default=None)
    parser.add_argument("--architecture-winner-resolution", type=Path, default=None)
    parser.add_argument("--ic-eda-tool-availability", type=Path, default=None)
    parser.add_argument("--deployment-target-selection", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(list(argv))
    if args.run_dir is None and args.out is None:
        parser.error("one of --run-dir or --out is required")
    args.run_dir = args.run_dir or args.out
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_hardware_deployment_recommendation_readiness(
        args.run_dir,
        hardware_completion_workplan_path=args.hardware_completion_workplan,
        tie_breaker_execution_queue_path=args.tie_breaker_execution_queue,
        freshness_queue_path=args.candidate_specific_ppa_freshness_queue,
        architecture_winner_resolution_path=args.architecture_winner_resolution,
        ic_eda_tool_availability_path=args.ic_eda_tool_availability,
        deployment_target_selection_path=args.deployment_target_selection,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
