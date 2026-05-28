#!/usr/bin/env python3
"""Normalize a trusted DFT/QE full-SCF runtime trace into row accounting.

This is a thin CLI over ``dft_full_scf_accounting`` for instrumented QE/offload
runtimes and repair/replay jobs.  It does not invent costs: blocked or untrusted
traces produce blocked accounting artifacts unless ``--fail-on-blocked`` is set,
in which case the command exits with status 2 after writing diagnostics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_full_scf_accounting import (  # noqa: E402
    materialize_full_scf_row_accounting_from_trace,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True, help="Runtime-emitted full-SCF trace JSON.")
    parser.add_argument("--out", type=Path, required=True, help="Output full_scf_row_accounting.json path.")
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--workload-case-id", default=None)
    parser.add_argument("--fail-on-blocked", action="store_true")
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = materialize_full_scf_row_accounting_from_trace(
        trace_path=args.trace,
        output_path=args.out,
        candidate_id=args.candidate_id,
        workload_case_id=args.workload_case_id,
    )
    print(json.dumps({"output": str(args.out), "status": payload.get("status"), "blockers": payload.get("blockers", [])}))
    if args.fail_on_blocked and payload.get("status") != "passed":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
