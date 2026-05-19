#!/usr/bin/env python3
"""Emit QE full-callgraph offload-search first-pass artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.qe_callgraph_offload_search import (  # noqa: E402
    write_qe_callgraph_offload_search_artifacts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Output artifact directory")
    parser.add_argument(
        "--source-root",
        default=None,
        help="Optional QE source root; defaults to runs/dse/_tools/q-e-src",
    )
    args = parser.parse_args()
    status = write_qe_callgraph_offload_search_artifacts(
        Path(args.out), source_root=args.source_root
    )
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
