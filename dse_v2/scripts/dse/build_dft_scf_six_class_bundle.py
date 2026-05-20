#!/usr/bin/env python3
"""Write the strict six-SCF descriptor-plus-runnable bundle artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_scf_six_class_suite import (  # noqa: E402
    write_dft_scf_six_class_bundle,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bundle-id", default="dft-scf-six-class-descriptor-runnable-bundle")
    parser.add_argument("--campaign-id", default="dft-scf-hardware-dse")
    parser.add_argument("--workload-run-id", default="dft_scf_six_class_suite_v1")
    parser.add_argument("--qe-command", default="pw.x")
    parser.add_argument("--reference-output-hashes-json", type=Path, default=None)
    parser.add_argument(
        "--use-local-pseudos",
        action="store_true",
        help="copy discovered local QE UPF pseudos into the bundle when all species for a case are available",
    )
    parser.add_argument("--local-pseudo-dir", type=Path, default=Path("/usr/share/espresso/pseudo"))
    parser.add_argument(
        "--run-local-qe",
        action="store_true",
        help="attempt bounded local pw.x runs to create reference_outputs/*.out and record real file hashes",
    )
    parser.add_argument("--local-pw-x", type=Path, default=Path("/usr/bin/pw.x"))
    parser.add_argument("--qe-run-timeout-seconds", type=int, default=300)
    parser.add_argument(
        "--reuse-existing-qe-outputs",
        action="store_true",
        help=(
            "when --run-local-qe is set, reuse an existing reference_outputs/<class>.out "
            "only if it already contains both JOB DONE and SCF convergence markers"
        ),
    )
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="return 0 after writing fail-closed artifacts even when real QE reference-output hashes are missing",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_scf_six_class_bundle(
        args.out,
        bundle_id=args.bundle_id,
        campaign_id=args.campaign_id,
        workload_run_id=args.workload_run_id,
        qe_command=args.qe_command,
        reference_output_hashes=args.reference_output_hashes_json,
        use_local_pseudos=args.use_local_pseudos or args.run_local_qe,
        local_pseudo_dir=args.local_pseudo_dir,
        run_local_qe=args.run_local_qe,
        local_pw_x=args.local_pw_x,
        qe_run_timeout_seconds=args.qe_run_timeout_seconds,
        reuse_existing_qe_outputs=args.reuse_existing_qe_outputs,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" or args.allow_blocked else 2


if __name__ == "__main__":
    raise SystemExit(main())
