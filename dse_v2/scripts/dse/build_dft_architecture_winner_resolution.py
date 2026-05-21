#!/usr/bin/env python3
"""Build fail-closed DFT/QE FPGA/ASIC architecture winner-resolution artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_architecture_winner_resolution import (  # noqa: E402
    write_dft_architecture_winner_resolution,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True, help="Step5 run directory containing dft_hardware_ppa_ranking.json")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    status = write_dft_architecture_winner_resolution(args.run_dir)
    if not args.quiet:
        print(json.dumps(status, indent=2))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
