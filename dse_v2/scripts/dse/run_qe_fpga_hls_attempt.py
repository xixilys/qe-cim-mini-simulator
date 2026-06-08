#!/usr/bin/env python3
"""Run an HLS attempt for one materialized QE FPGA implementation package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.qe_fpga_deployment_dse import run_qe_fpga_hls_attempt  # noqa: E402


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--hls-tool", default=None, help="Path/name of vivado_hls or vitis_hls")
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument("--strict-returncode", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    attempt = run_qe_fpga_hls_attempt(
        args.package_root,
        hls_tool=args.hls_tool,
        timeout_s=args.timeout_s,
    )
    print(json.dumps(attempt, indent=2, sort_keys=True, ensure_ascii=False))
    if attempt["status"] == "hls_attempt_passed":
        return 0
    if args.strict_returncode:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
