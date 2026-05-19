#!/usr/bin/env python3
"""Build readiness evidence for a true QE multi-callsite bundle harness."""

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
    build_bundle_harness_readiness_report,
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
        help=(
            "Directory containing offload_bundle_search_space.json and "
            "qe_callsite_patch_manifest.json."
        ),
    )
    parser.add_argument(
        "--runtime-contract-report",
        type=Path,
        default=None,
        help=(
            "Optional bundle_runtime_contract_report.json. Missing or "
            "unimplemented capabilities keep runtime blockers active."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    bundle_space = _load_json(args.artifact_root / "offload_bundle_search_space.json")
    patch_manifest = _load_json(args.artifact_root / "qe_callsite_patch_manifest.json")
    runtime_contract = (
        _load_json(args.runtime_contract_report)
        if args.runtime_contract_report is not None
        else None
    )
    report = build_bundle_harness_readiness_report(
        bundle_space,
        patch_manifest,
        runtime_capabilities=runtime_contract,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    report_path = args.out / "bundle_harness_readiness_report.json"
    _write_json(report_path, report)
    status = {
        "schema_version": "dse.qe_bundle_harness_readiness_status.v1",
        "status": report.get("status"),
        "report_path": str(report_path),
        "ready_bundle_harness_count": report.get("ready_bundle_harness_count", 0),
        "blocked_bundle_harness_count": report.get("blocked_bundle_harness_count", 0),
        "deliverable_complete": False,
        "claim_boundary": (
            "readiness only; a true bundle harness still needs real non-smoke "
            "QE/gem5 actual-compute evidence"
        ),
    }
    _write_json(args.out / "status.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
