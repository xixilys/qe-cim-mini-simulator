#!/usr/bin/env python3
"""Build DFT/QE candidate/workflow/target evidence-gate ledger artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_candidate_workflow_target_evidence_gate_ledger import (  # noqa: E402
    write_dft_candidate_workflow_target_evidence_gate_ledger,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=None, help="Run/output directory")
    parser.add_argument("--out", type=Path, default=None, help="Backward-compatible alias for --run-dir")
    parser.add_argument("--release-matrix", type=Path, default=None)
    parser.add_argument("--release-subset", type=Path, default=None)
    parser.add_argument("--gate-adjudication", type=Path, default=None)
    parser.add_argument("--candidate-specific-ppa-execution", type=Path, default=None)
    parser.add_argument("--ic-eda-tool-availability", type=Path, default=None)
    parser.add_argument("--ic-eda-tool-attempts", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(list(argv))
    if args.run_dir is None and args.out is None:
        parser.error("one of --run-dir or --out is required")
    args.run_dir = args.run_dir or args.out
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_candidate_workflow_target_evidence_gate_ledger(
        args.run_dir,
        release_matrix_path=args.release_matrix,
        release_subset_path=args.release_subset,
        gate_adjudication_path=args.gate_adjudication,
        candidate_specific_ppa_execution_path=args.candidate_specific_ppa_execution,
        ic_eda_tool_availability_path=args.ic_eda_tool_availability,
        ic_eda_tool_attempts_path=args.ic_eda_tool_attempts,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
