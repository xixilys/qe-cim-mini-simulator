#!/usr/bin/env python3
"""Analyze QE-IC real GPU-baseline FPGA/hybrid opportunity."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.evidence.qe_ic import write_qe_ic_real_baseline_opportunity_artifacts  # noqa: E402


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="QE-IC real-baseline opportunity config.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/qe_ic_real_baseline_opportunity"),
        help="Output directory for QE-IC real-baseline opportunity artifacts.",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result = write_qe_ic_real_baseline_opportunity_artifacts(args.out, args.config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
