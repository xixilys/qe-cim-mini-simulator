#!/usr/bin/env python3
"""Aggregate fresh candidate-specific PPA execution shards into a Step5 run."""

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
    write_dft_candidate_specific_ppa_execution_aggregate,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--shard-glob",
        default="fresh_candidate_specific_ppa_execution_*/dft_candidate_specific_ppa_execution.json",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_candidate_specific_ppa_execution_aggregate(
        args.run_dir,
        shard_glob=args.shard_glob,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
