#!/usr/bin/env python3
"""Build a DFT/QE full-SCF evaluated-hybrid descriptor artifact bundle.

The script writes schedule/cost/accounting artifacts only.  It intentionally
does not run HLS/RTL/Vivado/DC tools and does not create correctness or PPA
claims.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_full_scf_hybrid import (  # noqa: E402
    build_full_scf_evaluated_hybrid_payload,
    write_full_scf_evaluated_hybrid_artifacts,
)


def _load_cost_mapping(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object mapping ids to numeric costs")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--workload-run-id", required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--accelerated-kernel-costs-json", type=Path, required=True)
    parser.add_argument("--host-bound-costs-json", type=Path, required=True)
    parser.add_argument("--overhead-costs-json", type=Path, required=True)
    parser.add_argument("--baseline-scf-time-s", type=float)
    args = parser.parse_args(argv)

    payload = build_full_scf_evaluated_hybrid_payload(
        candidate_id=args.candidate_id,
        campaign_id=args.campaign_id,
        workload_run_id=args.workload_run_id,
        trial_id=args.trial_id,
        accelerated_kernel_costs_s=_load_cost_mapping(args.accelerated_kernel_costs_json),
        host_bound_costs_s=_load_cost_mapping(args.host_bound_costs_json),
        overhead_costs_s=_load_cost_mapping(args.overhead_costs_json),
        baseline_scf_time_s=args.baseline_scf_time_s,
    )
    status = write_full_scf_evaluated_hybrid_artifacts(args.out, payload)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
