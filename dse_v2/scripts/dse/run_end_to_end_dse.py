#!/usr/bin/env python3
"""Run the auditable generic DSE end-to-end workflow wrapper."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.scripts.dse.run_full_flow_pilot import main as run_full_flow_main


def main(argv: List[str] | None = None) -> int:
    return run_full_flow_main(
        list(sys.argv[1:] if argv is None else argv),
        cli_script="dse_v2/scripts/dse/run_end_to_end_dse.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
