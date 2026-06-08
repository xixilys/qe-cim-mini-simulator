#!/usr/bin/env python3
"""Build fail-closed full-QE integration readiness audit for real hybrid evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (  # noqa: E402
    build_full_qe_kernel_integration_readiness_audit,
)


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload is not an object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    summary = _load_json(args.summary)
    if summary is None:
        raise ValueError("--summary is required")
    hook_coverage_audit = _load_json(args.hook_coverage_audit)
    full_scf_comparison = _load_json(args.full_scf_comparison)
    audit = build_full_qe_kernel_integration_readiness_audit(
        summary=summary,
        hook_coverage_audit=hook_coverage_audit,
        full_scf_comparison=full_scf_comparison,
        candidate_id=args.candidate_id,
        workload_case_id=args.workload_case_id,
    )
    _write_json(args.out, audit)
    return {
        "status": "written",
        "audit": str(args.out),
        "passed": audit.get("passed"),
        "admission_status": audit.get("admission_status"),
        "full_qe_kernel_integration_gate_satisfied": audit.get("full_qe_kernel_integration_gate_satisfied"),
        "blockers": audit.get("blockers"),
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=Path("artifacts/qe_ic_real_hybrid_hls/real_hybrid_hls_summary.json"))
    parser.add_argument("--hook-coverage-audit", type=Path, default=None)
    parser.add_argument("--full-scf-comparison", type=Path, default=None)
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--workload-case-id", default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/qe_ic_real_hybrid_hls/real_hybrid_full_qe_integration_readiness_audit.json"),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    status = run_audit(args)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
