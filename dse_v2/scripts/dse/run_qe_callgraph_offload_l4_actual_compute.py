#!/usr/bin/env python3
"""Run a non-smoke full-QE GenericAccel L4 actual-compute attempt.

This wrapper intentionally uses the shared QE/gem5 attempt machinery from the
dataflow-smoke runner, but forces the attempt evidence contract to
``actual_compute``.  In this mode the row is blocked unless patched QE emits
runtime provenance proving that the selected kernel consumed the accelerated
replacement output during a full QE run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke import (
    EVIDENCE_MODE_ACTUAL_COMPUTE,
    main as _shared_main,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--evidence-mode" not in args:
        args.extend(["--evidence-mode", EVIDENCE_MODE_ACTUAL_COMPUTE])
    return _shared_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
