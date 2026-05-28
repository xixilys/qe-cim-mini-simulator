#!/usr/bin/env python3
"""Build fail-closed DFT/QE FPGA/ASIC deployment decision packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_hardware_deployment_decision_packet import (  # noqa: E402
    write_dft_hardware_deployment_decision_packet,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--architecture-winner-resolution", type=Path, default=None)
    parser.add_argument("--deployment-recommendation-readiness", type=Path, default=None)
    parser.add_argument("--deployment-target-selection", type=Path, default=None)
    parser.add_argument("--targeted-deployment-accounting", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    status = write_dft_hardware_deployment_decision_packet(
        args.run_dir,
        architecture_winner_resolution_path=args.architecture_winner_resolution,
        deployment_recommendation_readiness_path=args.deployment_recommendation_readiness,
        deployment_target_selection_path=args.deployment_target_selection,
        targeted_deployment_accounting_path=args.targeted_deployment_accounting,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
