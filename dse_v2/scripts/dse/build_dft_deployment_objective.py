#!/usr/bin/env python3
"""Write a conservative explicit DFT/QE deployment objective."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_deployment_objective import (  # noqa: E402
    write_conservative_dft_deployment_objective,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--objective-id", default="evidence-first-neutral-cross-target-v1")
    parser.add_argument("--goal-path", type=Path, default=None)
    parser.add_argument("--barrier-path", type=Path, default=None)
    parser.add_argument("--prior-status-path", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_conservative_dft_deployment_objective(
        args.out,
        objective_id=args.objective_id,
        goal_path=args.goal_path,
        barrier_path=args.barrier_path,
        prior_status_path=args.prior_status_path,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
