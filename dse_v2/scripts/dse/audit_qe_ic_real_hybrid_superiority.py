#!/usr/bin/env python3
"""Build a fail-closed superiority proof audit for QE IC real-hybrid evidence."""

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
    build_real_hybrid_superiority_proof_audit,
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload is not an object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    summary = _load_json(args.summary)
    claim_closure = _load_json(args.claim_closure)
    gpu_baseline = _load_json(args.gpu_baseline)
    audit = build_real_hybrid_superiority_proof_audit(
        summary=summary,
        claim_closure=claim_closure,
        gpu_baseline=gpu_baseline,
    )
    _write_json(args.out, audit)
    return {
        "status": "written",
        "audit": str(args.out),
        "decision": audit.get("decision"),
        "strong_superiority_claim_allowed": audit.get("strong_superiority_claim_allowed"),
        "missing_gate_ids": audit.get("missing_gate_ids"),
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=Path("artifacts/qe_ic_real_hybrid_hls/real_hybrid_hls_summary.json"))
    parser.add_argument("--claim-closure", type=Path, default=Path("artifacts/qe_ic_real_hybrid_hls/real_hybrid_claim_closure.json"))
    parser.add_argument("--gpu-baseline", type=Path, default=Path("artifacts/qe_ic_7day_prelim/qe_ic_7day_gpu_baseline.json"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/qe_ic_real_hybrid_hls/real_hybrid_superiority_proof_audit.json"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    status = run_audit(args)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
