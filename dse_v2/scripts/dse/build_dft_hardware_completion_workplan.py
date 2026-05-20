#!/usr/bin/env python3
"""Build DFT/QE candidate × kernel hardware completion workplan artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_hardware_completion_workplan import (  # noqa: E402
    write_dft_hardware_completion_workplan,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-candidate-evidence-ledger", type=Path, required=True)
    parser.add_argument("--dft-hardware-evidence-matrix", type=Path, default=None)
    parser.add_argument("--ic-eda-tool-availability", type=Path, default=None)
    parser.add_argument("--candidate-binding-map", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_hardware_completion_workplan(
        args.out,
        per_candidate_evidence_ledger_path=args.per_candidate_evidence_ledger,
        dft_hardware_evidence_matrix_path=args.dft_hardware_evidence_matrix,
        ic_eda_tool_availability_path=args.ic_eda_tool_availability,
        candidate_binding_map_path=args.candidate_binding_map,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
