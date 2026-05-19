#!/usr/bin/env python3
"""Materialize QE bundle patch files from member callsite patch artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.qe_callgraph_offload_search import (  # noqa: E402
    materialize_qe_bundle_patch_files,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        required=True,
        help="Directory containing offload_bundle_search_space.json.",
    )
    parser.add_argument(
        "--patch-dir",
        type=Path,
        default=REPO_ROOT / "patches" / "qe_callsite_offload_hooks",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    bundle_space = _load_json(args.artifact_root / "offload_bundle_search_space.json")
    report = materialize_qe_bundle_patch_files(
        bundle_space,
        patch_dir=args.patch_dir,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    report_path = args.out / "bundle_patch_materialization_report.json"
    _write_json(report_path, report)
    status = {
        "schema_version": "dse.qe_bundle_patch_materialization_status.v1",
        "status": report.get("status"),
        "report_path": str(report_path),
        "materialized_bundle_patch_count": report.get(
            "materialized_bundle_patch_count", 0
        ),
        "blocked_bundle_patch_count": report.get("blocked_bundle_patch_count", 0),
        "deliverable_complete": False,
        "claim_boundary": (
            "bundle patch materialization is provenance only; runtime "
            "single-workflow L4 evidence remains required"
        ),
    }
    _write_json(args.out / "status.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0 if report.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
