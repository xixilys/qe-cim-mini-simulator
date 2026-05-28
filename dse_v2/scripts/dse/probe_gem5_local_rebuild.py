#!/usr/bin/env python3
"""Probe whether this lane can rebuild gem5 locally without faking evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.generic_accel_l4_release import probe_gem5_local_rebuild  # noqa: E402


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--runroot", type=Path, default=None, help="Optional runroot where local_rebuild_probe_report.json is written")
    parser.add_argument("--source-root", type=Path, action="append", default=[], help="Additional read-only gem5 source roots to inspect")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = probe_gem5_local_rebuild(
        repo_root=args.repo_root,
        runroot=args.runroot,
        source_roots=args.source_root,
    )
    if not args.quiet:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") != "blocked_unexpected_probe_error" else 2


if __name__ == "__main__":
    raise SystemExit(main())
