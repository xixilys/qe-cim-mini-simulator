#!/usr/bin/env python3
"""Build DFT-first seven-axis release-domain/search-space artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_codesign_domain import write_dft_seven_axis_artifacts  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument(
        "--timing-run-dir",
        type=Path,
        default=Path("runs/dse/dft_first_qe_real_gem5_hardened_audit"),
        help="Optional existing DFT timing/gem5 run to seed feedback trace evidence",
    )
    args = parser.parse_args(argv)
    status = write_dft_seven_axis_artifacts(args.out, timing_run_dir=args.timing_run_dir)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
