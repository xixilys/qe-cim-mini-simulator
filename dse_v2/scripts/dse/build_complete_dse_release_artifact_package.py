#!/usr/bin/env python3
"""Emit the current-goal Complete-DSE release artifact package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.complete_dse_done_when_4_6_audit import (  # noqa: E402
    write_complete_dse_release_artifact_package,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--control-root", type=Path, default=None)
    parser.add_argument("--goal-path", type=Path, default=None)
    parser.add_argument("--barrier-path", type=Path, default=None)
    parser.add_argument("--preflight-path", type=Path, default=None)
    parser.add_argument("--north-star-path", type=Path, default=None)
    parser.add_argument("--deployment-decision-summary-path", type=Path, default=None)
    parser.add_argument("--strict-qe-release-bundle-manifest-path", type=Path, default=None)
    parser.add_argument("--target-evidence-ledger-path", type=Path, default=None)
    parser.add_argument("--target-evidence-ledger-validation-path", type=Path, default=None)
    parser.add_argument("--target-evidence-ledger-status-path", type=Path, default=None)
    return parser.parse_args(argv)


def _deployment_decision_summary_path(args: argparse.Namespace) -> Path | None:
    if args.deployment_decision_summary_path is not None:
        return args.deployment_decision_summary_path
    generated_summary = args.out / "dft_deployment_decision_summary.json"
    return generated_summary if generated_summary.is_file() else None


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    status = write_complete_dse_release_artifact_package(
        args.out,
        repo_root=args.repo_root,
        control_root=args.control_root,
        goal_path=args.goal_path,
        barrier_path=args.barrier_path,
        preflight_path=args.preflight_path,
        north_star_path=args.north_star_path,
        deployment_decision_summary_path=_deployment_decision_summary_path(args),
        strict_qe_release_bundle_manifest_path=args.strict_qe_release_bundle_manifest_path,
        target_evidence_ledger_path=args.target_evidence_ledger_path,
        target_evidence_ledger_validation_path=args.target_evidence_ledger_validation_path,
        target_evidence_ledger_status_path=args.target_evidence_ledger_status_path,
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
