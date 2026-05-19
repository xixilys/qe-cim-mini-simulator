#!/usr/bin/env python3
"""Build the QE bundle multi-callsite runtime contract artifact.

The artifact defines the selector/output/provenance slot contract required for
a true single-QE-workflow bundle harness.  It is readiness metadata only and
must not be treated as smoke, actual-compute evidence, or value evidence.
"""

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
    build_bundle_runtime_contract_report,
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
            "Directory containing offload_bundle_search_space.json and, when "
            "available, offload_opportunity_manifest.json."
        ),
    )
    parser.add_argument(
        "--runtime-capabilities",
        type=Path,
        default=None,
        help=(
            "Optional JSON mapping of explicit runtime capabilities. Omit to "
            "record the current single-kernel bridge as not bundle-ready."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    bundle_space = _load_json(args.artifact_root / "offload_bundle_search_space.json")
    opportunity_manifest_path = args.artifact_root / "offload_opportunity_manifest.json"
    opportunity_manifest = (
        _load_json(opportunity_manifest_path)
        if opportunity_manifest_path.exists()
        else None
    )
    runtime_capabilities = (
        _load_json(args.runtime_capabilities)
        if args.runtime_capabilities is not None
        else None
    )
    report = build_bundle_runtime_contract_report(
        bundle_space,
        opportunity_manifest=opportunity_manifest,
        runtime_capabilities=runtime_capabilities,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    report_path = args.out / "bundle_runtime_contract_report.json"
    _write_json(report_path, report)
    status = {
        "schema_version": "dse.qe_bundle_runtime_contract_status.v1",
        "status": report.get("status"),
        "report_path": str(report_path),
        "multi_callsite_bundle_count": report.get("multi_callsite_bundle_count", 0),
        "runtime_contract_ready_bundle_count": report.get(
            "runtime_contract_ready_bundle_count", 0
        ),
        "deliverable_complete": False,
        "claim_boundary": (
            "runtime contract/readiness only; true bundle value still requires "
            "non-smoke QE/gem5 actual-compute evidence"
        ),
    }
    _write_json(args.out / "status.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
