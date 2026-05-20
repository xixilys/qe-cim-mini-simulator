#!/usr/bin/env python3
"""Run selected candidate/kernel RTL/HLS source-flow shards."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_hardware_closure_real_source_flow_run import (  # noqa: E402
    write_dft_hardware_closure_real_source_flow_run,
)


def _split_csv(values: Sequence[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for item in str(value).split(','):
            stripped = item.strip()
            if stripped:
                items.append(stripped)
    return items


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--closure-packet-index', type=Path, required=True)
    parser.add_argument('--candidate-id', action='append', default=[], help='Candidate filter; repeatable or comma-separated')
    parser.add_argument('--kernel-id', action='append', default=[], help='Kernel filter; repeatable or comma-separated')
    parser.add_argument('--max-units', type=int, default=None)
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--ssh-target', default='ic-eda')
    parser.add_argument('--timeout-s', type=int, default=900)
    parser.add_argument('--skip-remote', action='store_true', help='Create candidate-stamped local source flows without remote EDA')
    parser.add_argument('--strict-returncode', action='store_true', help='Do not pass --allow-blocked to kernel runners')
    parser.add_argument('--quiet', action='store_true')
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_hardware_closure_real_source_flow_run(
        args.out,
        closure_packet_index_path=args.closure_packet_index,
        candidate_ids=_split_csv(args.candidate_id),
        kernel_ids=_split_csv(args.kernel_id),
        max_units=args.max_units,
        jobs=args.jobs,
        ssh_target=args.ssh_target,
        timeout_s=args.timeout_s,
        skip_remote=args.skip_remote,
        allow_blocked=not args.strict_returncode,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
