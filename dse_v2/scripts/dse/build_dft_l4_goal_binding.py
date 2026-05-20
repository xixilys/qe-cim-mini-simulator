#!/usr/bin/env python3
"""Build a fail-closed DFT goal binding to existing gem5/L4 evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.dft_l4_goal_binding import (  # noqa: E402
    DEFAULT_CANDIDATE_MAPPING_POLICY,
    DEFAULT_WORKLOAD_MAPPING_POLICY,
    write_dft_l4_goal_binding,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Directory that receives dft_l4_goal_binding*.json")
    parser.add_argument("--l4-root", type=Path, required=True, help="Root containing l4_evidence_matrix.json")
    parser.add_argument("--step5-run", type=Path, default=None, help="Current DFT Step5 run root for candidate IDs")
    parser.add_argument("--candidate-crosswalk", type=Path, default=None, help="Optional explicit current-goal to L4 candidate crosswalk JSON")
    parser.add_argument("--workload-crosswalk", type=Path, default=None, help="Optional explicit current-goal to L4 workload crosswalk JSON")
    parser.add_argument(
        "--candidate-mapping-policy",
        default=DEFAULT_CANDIDATE_MAPPING_POLICY,
        choices=["separate_l4_matrix_no_wave36_candidate_equivalence", "explicit_crosswalk"],
    )
    parser.add_argument(
        "--workload-mapping-policy",
        default=DEFAULT_WORKLOAD_MAPPING_POLICY,
        choices=["legacy_qe_mainflow_not_six_scf", "explicit_crosswalk"],
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_l4_goal_binding(
        args.out,
        l4_root=args.l4_root,
        step5_run=args.step5_run,
        candidate_crosswalk=args.candidate_crosswalk,
        workload_crosswalk=args.workload_crosswalk,
        candidate_mapping_policy=args.candidate_mapping_policy,
        workload_mapping_policy=args.workload_mapping_policy,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
