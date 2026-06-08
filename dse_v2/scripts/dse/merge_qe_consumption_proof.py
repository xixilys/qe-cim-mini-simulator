#!/usr/bin/env python3
"""Merge a patched-QE post-bridge consumption proof into row evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.qe_consumption_proof import merge_qe_consumption_proof_artifacts  # noqa: E402


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consumption-proof", type=Path, required=True)
    parser.add_argument("--kernel-evidence", type=Path, required=True)
    parser.add_argument("--offload-provenance", type=Path, required=True)
    parser.add_argument("--accelerated-output-json", type=Path, default=None)
    parser.add_argument("--accelerated-output-data", type=Path, default=None)
    parser.add_argument("--runtime-events", type=Path, default=None)
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--workload-case-id", default=None)
    parser.add_argument("--target-kernel", default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--fail-on-blocked", action="store_true")
    return parser.parse_args(argv)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = merge_qe_consumption_proof_artifacts(
        consumption_proof_path=args.consumption_proof,
        kernel_evidence_path=args.kernel_evidence,
        offload_provenance_path=args.offload_provenance,
        accelerated_output_json_path=args.accelerated_output_json,
        accelerated_output_data_path=args.accelerated_output_data,
        runtime_events_path=args.runtime_events,
        candidate_id=args.candidate_id,
        workload_case_id=args.workload_case_id,
        target_kernel=args.target_kernel,
    )
    if args.out is not None:
        _write_json(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.fail_on_blocked and result.get("passed") is not True:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
