#!/usr/bin/env python3
"""Build the DFT/QE candidate binding map artifact bundle.

The binding map relates DFT hierarchical-search candidate IDs to frozen
seven-axis release candidate IDs.  It is ID-provenance metadata only and never
upgrades numerical, PPA, Pareto, or deliverable-completion claims.
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

from dse_v2.reference_workloads.dft_candidate_binding import write_dft_candidate_binding_map  # noqa: E402


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output directory for binding-map artifacts")
    parser.add_argument(
        "--hierarchical-search-report",
        type=Path,
        required=True,
        help="Step2 hierarchical_funnel_search_report.json",
    )
    parser.add_argument(
        "--candidate-universe-manifest",
        type=Path,
        required=True,
        help="Frozen seven-axis candidate_universe_manifest.json",
    )
    parser.add_argument(
        "--per-candidate-evidence-ledger",
        type=Path,
        default=None,
        help="Optional per_candidate_evidence_ledger.json for evidence-row presence checks",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_candidate_binding_map(
        args.out,
        hierarchical_search_report_path=args.hierarchical_search_report,
        candidate_universe_manifest_path=args.candidate_universe_manifest,
        per_candidate_evidence_ledger_path=args.per_candidate_evidence_ledger,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
