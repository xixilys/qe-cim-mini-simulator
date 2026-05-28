#!/usr/bin/env python3
"""Audit patched-QE call-site coverage against strict full-SCF gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.qe_full_scf_hook_coverage import (  # noqa: E402
    build_qe_full_scf_hook_coverage_audit,
    write_qe_full_scf_hook_coverage_audit,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--callsite-trace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--kernel-evidence", type=Path, default=None)
    parser.add_argument("--offload-provenance", type=Path, default=None)
    parser.add_argument("--runtime-trace", type=Path, default=None)
    parser.add_argument("--runtime-execution-proof", type=Path, default=None)
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--workload-case-id", default=None)
    parser.add_argument("--fail-on-blocked", action="store_true")
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_qe_full_scf_hook_coverage_audit(
        callsite_trace_path=args.callsite_trace,
        kernel_evidence_path=args.kernel_evidence,
        offload_provenance_path=args.offload_provenance,
        runtime_trace_path=args.runtime_trace,
        runtime_execution_proof_path=args.runtime_execution_proof,
        candidate_id=args.candidate_id,
        workload_case_id=args.workload_case_id,
    )
    write_qe_full_scf_hook_coverage_audit(args.out, payload)
    print(
        json.dumps(
            {
                "artifact": str(args.out),
                "status": payload["status"],
                "passed": payload["passed"],
                "blockers": payload["blockers"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if args.fail_on_blocked and payload["passed"] is not True:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
