#!/usr/bin/env python3
"""Build one QE accelerated numeric evidence JSON row from audited outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.qe_accelerated_evidence import (  # noqa: E402
    build_evidence_from_files,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--workload-case-id", required=True)
    parser.add_argument("--baseline-comparison", type=Path, required=True)
    parser.add_argument("--accelerated-stdout", type=Path, required=True)
    parser.add_argument("--source-kind", required=True)
    parser.add_argument("--kernel-evidence", type=Path, default=None)
    parser.add_argument("--offload-provenance", type=Path, default=None)
    parser.add_argument("--density-residual", type=float, default=None)
    parser.add_argument("--force-error-ry-bohr", type=float, default=None)
    parser.add_argument("--stress-error-kbar", type=float, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--fail-on-blocked",
        action="store_true",
        help="Exit 2 if the generated evidence is blocked or untrusted.",
    )
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    evidence = build_evidence_from_files(
        candidate_id=args.candidate_id,
        workload_case_id=args.workload_case_id,
        baseline_comparison_path=args.baseline_comparison,
        accelerated_stdout_path=args.accelerated_stdout,
        source_kind=args.source_kind,
        kernel_evidence_path=args.kernel_evidence,
        offload_provenance_path=args.offload_provenance,
        density_residual=args.density_residual,
        force_error_ry_bohr=args.force_error_ry_bohr,
        stress_error_kbar=args.stress_error_kbar,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "schema_version": "dse.qe_accelerated_numeric_evidence_build_status.v1",
        "out": str(args.out),
        "status": evidence["accelerated_output_status"],
        "trusted_accelerated_numeric_source": evidence["trusted_accelerated_numeric_source"],
        "blockers": evidence["blockers"],
    }
    print(json.dumps(status, indent=2, sort_keys=True))
    return 2 if args.fail_on_blocked and not evidence["trusted_accelerated_numeric_source"] else 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
