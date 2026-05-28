#!/usr/bin/env python3
"""Write the DFT/QE hardware release-gate missing-input matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_hardware_closure_release_gate_input_matrix import (  # noqa: E402
    write_dft_hardware_closure_release_gate_input_matrix,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--slot2-target-input-dir", type=Path, default=None)
    parser.add_argument("--slot2-target-consumer-run-dir", type=Path, default=None)
    parser.add_argument("--parsed-evidence-manifest", type=Path, default=None)
    parser.add_argument("--gate-adjudication", type=Path, default=None)
    parser.add_argument("--per-candidate-evidence-ledger", type=Path, default=None)
    parser.add_argument("--candidate-workflow-target-evidence-gate-ledger", type=Path, default=None)
    parser.add_argument("--release-subset-manifest", type=Path, default=None)
    parser.add_argument("--hardware-ppa-ranking", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_hardware_closure_release_gate_input_matrix(
        args.run_dir,
        slot2_target_input_dir=args.slot2_target_input_dir,
        slot2_target_consumer_run_dir=args.slot2_target_consumer_run_dir,
        parsed_evidence_manifest_path=args.parsed_evidence_manifest,
        gate_adjudication_path=args.gate_adjudication,
        per_candidate_evidence_ledger_path=args.per_candidate_evidence_ledger,
        candidate_workflow_target_evidence_gate_ledger_path=args.candidate_workflow_target_evidence_gate_ledger,
        release_subset_manifest_path=args.release_subset_manifest,
        hardware_ppa_ranking_path=args.hardware_ppa_ranking,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
