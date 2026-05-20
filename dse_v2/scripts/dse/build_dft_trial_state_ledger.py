#!/usr/bin/env python3
"""Build the DFT/QE full-SCF trial state ledger artifact bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_trial_ledger import write_dft_trial_state_ledger  # noqa: E402


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output directory for DFT trial ledger artifacts")
    parser.add_argument(
        "--hierarchical-search-report",
        type=Path,
        required=True,
        help="Step2 hierarchical_funnel_search_report.json",
    )
    parser.add_argument(
        "--per-candidate-evidence-ledger",
        type=Path,
        default=None,
        help="Optional DFT per_candidate_evidence_ledger.json",
    )
    parser.add_argument(
        "--eda-all-candidate-evidence",
        type=Path,
        default=None,
        help="Optional DFT eda_all_candidate_evidence.json",
    )
    parser.add_argument(
        "--candidate-binding-map",
        type=Path,
        default=None,
        help="Optional DFT dft_candidate_binding_map.json",
    )
    parser.add_argument("--final-report", type=Path, default=None, help="Optional Step5 final_report.json")
    parser.add_argument(
        "--goal-audit",
        type=Path,
        default=None,
        help="Optional dft_scf_hardware_goal_completion_audit.json",
    )
    parser.add_argument(
        "--dft-hardware-evidence-matrix",
        type=Path,
        default=None,
        help="Optional dft_hardware_evidence_matrix.json",
    )
    parser.add_argument(
        "--ic-eda-tool-availability",
        type=Path,
        default=None,
        help="Optional ic_eda_tool_availability.json",
    )
    parser.add_argument("--campaign-id", default="dft_scf_hardware_dse_campaign_v1")
    parser.add_argument("--workload-run-id", default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_trial_state_ledger(
        args.out,
        hierarchical_search_report_path=args.hierarchical_search_report,
        per_candidate_evidence_ledger_path=args.per_candidate_evidence_ledger,
        eda_all_candidate_evidence_path=args.eda_all_candidate_evidence,
        candidate_binding_map_path=args.candidate_binding_map,
        final_report_path=args.final_report,
        goal_audit_path=args.goal_audit,
        dft_hardware_evidence_matrix_path=args.dft_hardware_evidence_matrix,
        ic_eda_tool_availability_path=args.ic_eda_tool_availability,
        campaign_id=args.campaign_id,
        workload_run_id=args.workload_run_id,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
