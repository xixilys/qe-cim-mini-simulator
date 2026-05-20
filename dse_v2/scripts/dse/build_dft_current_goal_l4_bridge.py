#!/usr/bin/env python3
"""Build fail-closed current-goal DFT L4 bridge artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_current_goal_l4_bridge import (  # noqa: E402
    write_dft_current_goal_l4_bridge,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--release-gate", type=Path, required=True, help="Step5 dft_hardware_closure_release_gate.json")
    parser.add_argument("--six-scf-manifest", type=Path, required=True, help="dft_scf_six_class_bundle_manifest.json")
    parser.add_argument("--pending-l4-root", type=Path, default=None, help="Optional output root for blocked/pending L4 matrix artifacts")
    parser.add_argument("--no-pending-l4-root", action="store_true", help="Do not emit the blocked/pending L4 root")
    parser.add_argument("--allow-blocked", action="store_true", help="Return 0 after writing fail-closed artifacts even if bridge inputs are invalid")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_current_goal_l4_bridge(
        args.out,
        release_gate_path=args.release_gate,
        six_scf_manifest_path=args.six_scf_manifest,
        emit_pending_l4_root=not args.no_pending_l4_root,
        pending_l4_root=args.pending_l4_root,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" or args.allow_blocked else 2


if __name__ == "__main__":
    raise SystemExit(main())
