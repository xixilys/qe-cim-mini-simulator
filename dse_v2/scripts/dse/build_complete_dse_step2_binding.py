#!/usr/bin/env python3
"""Emit Step2 admission artifacts for complete-DSE release candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.complete_dse_step2_binding import (  # noqa: E402
    write_complete_dse_step2_binding_artifacts,
)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output directory for Step2 binding artifacts.")
    parser.add_argument("--release-subset", type=Path, default=None, help="Optional release_subset_manifest.json to bind.")
    parser.add_argument("--backend", default="gem5_systemc", help="Backend recorded in step3_simulation_queue.json.")
    args = parser.parse_args()
    release_subset = _load_json(args.release_subset) if args.release_subset else None
    status = write_complete_dse_step2_binding_artifacts(
        args.out,
        release_subset=release_subset,
        backend=args.backend,
    )
    print(json.dumps(status, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
