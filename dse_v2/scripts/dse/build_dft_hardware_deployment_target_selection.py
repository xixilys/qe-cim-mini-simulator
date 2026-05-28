#!/usr/bin/env python3
"""Build fail-closed DFT/QE FPGA/ASIC deployment target-selection context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_hardware_deployment_target_selection import (  # noqa: E402
    write_dft_hardware_deployment_target_selection,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--fpga-target-catalog", type=Path, default=None)
    parser.add_argument("--asic-target-library-probe", type=Path, default=None)
    parser.add_argument("--ic-eda-tool-availability", type=Path, default=None)
    parser.add_argument(
        "--budget-policy",
        default="unbounded_budget_current_catalog_required",
        help="Deployment planning budget policy; default records the user's unbounded-FPGA-budget intent.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    status = write_dft_hardware_deployment_target_selection(
        args.run_dir,
        fpga_target_catalog_path=args.fpga_target_catalog,
        asic_target_library_probe_path=args.asic_target_library_probe,
        ic_eda_tool_availability_path=args.ic_eda_tool_availability,
        budget_policy=args.budget_policy,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
