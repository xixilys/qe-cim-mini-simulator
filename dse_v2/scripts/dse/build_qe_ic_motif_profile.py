#!/usr/bin/env python3
"""Build QE-IC Layer-2 motif-profile artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.profiling.qe_ic import write_qe_ic_motif_profile_artifacts  # noqa: E402


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        type=Path,
        default=Path("artifacts/qe_ic_workload_suite/qe_ic_workload_suite.json"),
        help="Layer-1 QE-IC workload-suite artifact.",
    )
    parser.add_argument(
        "--profile-sources",
        type=Path,
        required=True,
        help="QE-IC profile-source fixture or summary envelope.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/qe_ic_motif_profile"),
        help="Output directory for QE-IC motif-profile artifacts.",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result = write_qe_ic_motif_profile_artifacts(
        args.out,
        args.suite,
        args.profile_sources,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

