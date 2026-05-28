#!/usr/bin/env python3
"""Build repo-owned GenericAccel L4 release-consumable artifacts.

Consumes an expanded gem5 GenericAccel proof matrix under --runroot and emits
Step4 rows, coverage matrices, release binding, repair queue, replay contract,
and hash manifest.  The builder is fail-closed: synthetic L4 rows do not become
trusted CDSE/release rows without explicit structured crosswalks and downstream
QE/PPA gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.generic_accel_l4_release import generate_release_artifacts  # noqa: E402


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runroot", type=Path, required=True, help="Runroot containing generic_accel_l4_expanded_proof_matrix.json")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Repository root for runtime prerequisites and replay contract")
    parser.add_argument("--slot2-worklist", type=Path, default=None, help="Run2 candidate/kernel/target worklist JSON")
    parser.add_argument("--candidate-crosswalk", type=Path, default=None, help="Optional structured CDSE -> L4 candidate crosswalk JSON")
    parser.add_argument("--workload-crosswalk", type=Path, default=None, help="Optional structured CDSE kernel/workload -> L4 workload crosswalk JSON")
    parser.add_argument("--gem5-bin", type=Path, default=None, help="gem5 binary path to embed in replay contract")
    parser.add_argument("--slot-root", type=Path, default=None, help="Optional slot root whose status/final files are hash-referenced")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = generate_release_artifacts(
        runroot=args.runroot,
        repo_root=args.repo_root,
        slot2_worklist=args.slot2_worklist,
        candidate_crosswalk=args.candidate_crosswalk,
        workload_crosswalk=args.workload_crosswalk,
        gem5_bin=args.gem5_bin,
        slot_root=args.slot_root,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
