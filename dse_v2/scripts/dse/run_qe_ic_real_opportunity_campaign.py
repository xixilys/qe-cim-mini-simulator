#!/usr/bin/env python3
"""Run the QE-IC real GPU-vs-FPGA/hybrid opportunity campaign."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.experiments.qe_ic_real_opportunity import write_qe_ic_real_opportunity_campaign_artifacts  # noqa: E402


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="QE-IC real opportunity campaign config.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/qe_ic_real_opportunity_campaign"),
        help="Output directory for campaign artifacts.",
    )
    parser.add_argument(
        "--execute-real",
        action="store_true",
        help="Attempt real QE/GPU/candidate evidence execution when tools and inputs are available.",
    )
    parser.add_argument(
        "--allow-generated-inputs",
        action="store_true",
        help="Allow generated benchmark/proxy input decks when real input decks are missing.",
    )
    parser.add_argument(
        "--nonblocking",
        action="store_true",
        help="Continue with generated benchmark/proxy evidence instead of terminal missing-input/evidence blockers.",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result = write_qe_ic_real_opportunity_campaign_artifacts(
        args.out,
        args.config,
        execute_real=args.execute_real,
        allow_generated_inputs=args.allow_generated_inputs,
        nonblocking=args.nonblocking,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
