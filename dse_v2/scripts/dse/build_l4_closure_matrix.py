#!/usr/bin/env python3
"""Build complete-DSE L4 closure matrix and coverage claim report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.l4_closure import build_coverage_claim_report, build_l4_evidence_matrix  # noqa: E402


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _evidence_rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        rows = payload.get("rows", [])
        return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
    return []


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-subset", type=Path, required=True, help="release_subset_manifest.json")
    parser.add_argument("--workload-suite", type=Path, required=True, help="qe_mainflow_workload_suite_manifest.json or compatible fixture")
    parser.add_argument("--evidence-rows", type=Path, required=True, help="JSON list or object with rows[]")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    args = parser.parse_args()

    matrix = build_l4_evidence_matrix(
        _load_json(args.release_subset),
        _load_json(args.workload_suite),
        _evidence_rows(_load_json(args.evidence_rows)),
    )
    report = build_coverage_claim_report(matrix)
    _write_json(args.out / "l4_evidence_matrix.json", matrix)
    _write_json(args.out / "coverage_claim_report.json", report)
    print(json.dumps({
        "schema_version": "dse.codesign.l4_closure_matrix_cli_status.v1",
        "status": report["status"],
        "l4_evidence_matrix": str(args.out / "l4_evidence_matrix.json"),
        "coverage_claim_report": str(args.out / "coverage_claim_report.json"),
        "deliverable_complete": report["claims"]["deliverable_complete"],
        "blocked_row_count": report["blocked_row_count"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
