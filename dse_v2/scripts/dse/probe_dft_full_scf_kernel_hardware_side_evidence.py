#!/usr/bin/env python3
"""Probe hardware side evidence for one DFT full-SCF kernel.

This diagnostic command records parsed golden/RTL/Vivado/DC evidence as
hardware-side progress only.  It deliberately does not emit trusted runtime
events or QE-consumed numeric rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_full_scf_evidence_gap import (  # noqa: E402
    build_kernel_hardware_side_evidence_progress,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--workload-case-id", required=True)
    parser.add_argument("--kernel-id", required=True)
    parser.add_argument(
        "--source-root",
        action="append",
        default=[],
        help="Parsed hard-gate/evidence root to scan; may be passed multiple times.",
    )
    parser.add_argument("--out", required=True, help="kernel hardware-side progress JSON output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    progress = build_kernel_hardware_side_evidence_progress(
        candidate_id=args.candidate_id,
        workload_case_id=args.workload_case_id,
        kernel_id=args.kernel_id,
        source_roots=[Path(item) for item in args.source_root],
    )
    out_path = Path(args.out)
    _write_json(out_path, progress)
    print(
        json.dumps(
            {
                "status": progress["status"],
                "candidate_id": progress["candidate_id"],
                "workload_case_id": progress["workload_case_id"],
                "kernel_id": progress["kernel_id"],
                "hardware_side_evidence_found": progress["hardware_side_evidence_found"],
                "hardware_stage_pass_count": progress["hardware_stage_pass_count"],
                "hardware_stage_required_count": progress["hardware_stage_required_count"],
                "scanned_json_file_count": progress["scanned_json_file_count"],
                "full_scf_seed_eligible": progress["full_scf_seed_eligible"],
                "remaining_blockers": progress["remaining_blockers"],
                "out": str(out_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
