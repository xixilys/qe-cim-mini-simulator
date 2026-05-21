#!/usr/bin/env python3
"""Build DFT/QE hardware PPA ranking artifacts from Step5 closure evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_hardware_ppa_ranking import (  # noqa: E402
    write_dft_hardware_ppa_ranking,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--candidate-universe-manifest",
        type=Path,
        default=None,
        help=(
            "Optional candidate_universe_manifest.json. Identity assignments are "
            "reported for audit context but non-identity axes are excluded from "
            "hardware PPA score."
        ),
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_hardware_ppa_ranking(
        args.run_dir,
        candidate_universe_manifest=args.candidate_universe_manifest,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
