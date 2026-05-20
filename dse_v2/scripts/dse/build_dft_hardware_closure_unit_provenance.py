#!/usr/bin/env python3
"""Stage fail-closed candidate-specific unit provenance files for DFT closure."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_hardware_closure_unit_provenance import (  # noqa: E402
    write_dft_hardware_closure_unit_provenance,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--closure-packet-index", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=None)
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--kernel-id", action="append", default=[])
    parser.add_argument("--max-units", type=int, default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_hardware_closure_unit_provenance(
        args.out,
        closure_packet_index_path=args.closure_packet_index,
        evidence_root=args.evidence_root,
        candidate_ids=args.candidate_id,
        kernel_ids=args.kernel_id,
        max_units=args.max_units,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
