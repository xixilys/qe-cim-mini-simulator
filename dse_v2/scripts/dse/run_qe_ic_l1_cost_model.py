#!/usr/bin/env python3
"""Run QE-IC Layer-5A L1 cost-model artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.evaluation.qe_ic.l1_cost_model import write_qe_ic_l1_cost_model_artifacts  # noqa: E402


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        type=Path,
        default=Path("artifacts/qe_ic_workload_suite/qe_ic_workload_suite.json"),
        help="Layer-1 QE-IC workload-suite artifact.",
    )
    parser.add_argument(
        "--motif-profile",
        type=Path,
        default=Path("artifacts/qe_ic_motif_profile/qe_ic_motif_profile.json"),
        help="Layer-2 QE-IC motif-profile artifact.",
    )
    parser.add_argument(
        "--target-viability",
        type=Path,
        default=Path("artifacts/qe_ic_target_viability/qe_ic_target_viability.json"),
        help="Layer-3 QE-IC target-viability artifact.",
    )
    parser.add_argument(
        "--candidate-plan",
        type=Path,
        default=Path("artifacts/qe_ic_candidate_plan/qe_ic_candidate_plan.json"),
        help="Layer-4 QE-IC candidate-plan artifact.",
    )
    parser.add_argument(
        "--model-config",
        type=Path,
        required=True,
        help="Layer-5A QE-IC L1 cost-model config.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/qe_ic_l1_cost_model"),
        help="Output directory for QE-IC L1 cost-model artifacts.",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result = write_qe_ic_l1_cost_model_artifacts(
        args.out,
        args.suite,
        args.motif_profile,
        args.target_viability,
        args.candidate_plan,
        args.model_config,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
