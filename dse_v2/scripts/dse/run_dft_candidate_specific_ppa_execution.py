#!/usr/bin/env python3
"""Execute fresh candidate-specific PPA queue slices for DFT hardware closure."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_candidate_specific_ppa_execution import (  # noqa: E402
    write_dft_candidate_specific_ppa_execution,
)


def _split_csv(values: Sequence[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for item in str(value).split(","):
            stripped = item.strip()
            if stripped:
                items.append(stripped)
    return items


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--tie-breaker-queue", type=Path, default=None)
    parser.add_argument("--candidate-id", action="append", default=[], help="Candidate filter; repeatable or comma-separated")
    parser.add_argument("--kernel-id", action="append", default=[], help="Kernel filter; repeatable or comma-separated")
    parser.add_argument("--stage-id", action="append", default=[], help="Stage filter; repeatable or comma-separated")
    parser.add_argument("--max-units", type=int, default=None)
    parser.add_argument("--ssh-target", default="ic-eda")
    parser.add_argument(
        "--remote-base-dir",
        default="/tmp",
        help="Remote scratch root for candidate-specific IC/EDA runner work dirs",
    )
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument("--skip-remote", action="store_true", help="Only initialize/local golden evidence; record remote tool probe but skip EDA runs")
    parser.add_argument("--strict-returncode", action="store_true", help="Return nonzero when execution status is blocked")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out_dir = args.out or (args.run_dir / "fresh_candidate_specific_ppa_execution")
    status = write_dft_candidate_specific_ppa_execution(
        out_dir,
        run_dir=args.run_dir,
        tie_breaker_queue_path=args.tie_breaker_queue,
        candidate_ids=_split_csv(args.candidate_id),
        kernel_ids=_split_csv(args.kernel_id),
        stage_ids=_split_csv(args.stage_id),
        max_units=args.max_units,
        ssh_target=args.ssh_target,
        remote_base_dir=args.remote_base_dir,
        timeout_s=args.timeout_s,
        skip_remote=args.skip_remote,
        allow_blocked=not args.strict_returncode,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    if status["status"] != "passed":
        return 1
    if args.strict_returncode and str(status.get("execution_status", "")).startswith("blocked"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
