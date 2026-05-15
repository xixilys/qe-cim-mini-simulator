#!/usr/bin/env python3
"""Emit an auditable coverage report for first-stage DFT common modes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_modes import (  # noqa: E402
    build_first_stage_dft_mode_coverage_report,
    first_stage_dft_mode_templates,
)


def _date_text() -> str:
    return subprocess.check_output(["date", "+%Y-%m-%d %H:%M:%S %Z (%z)"], text=True).strip()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_report(out_dir: Path) -> dict[str, Any]:
    report = build_first_stage_dft_mode_coverage_report()
    report["checked_at_local"] = _date_text()
    report["artifact_claim_boundary"] = (
        "This artifact proves first-stage DFT mode template coverage only. "
        "It is not numerical correctness, all-candidate evidence closure, "
        "EDA/formal closure, or deliverable_complete evidence."
    )
    workflows = {
        mode_id: template.workflow_spec().to_dict()
        for mode_id, template in first_stage_dft_mode_templates().items()
    }
    _write_json(out_dir / "dft_mode_coverage_report.json", report)
    _write_json(out_dir / "dft_mode_workflows.json", {
        "schema_version": "dse.dft.first_stage_mode_workflows.v1",
        "checked_at_local": report["checked_at_local"],
        "claim_boundary": report["claim_boundary"],
        "workflows": workflows,
    })
    _write_json(out_dir / "status.json", {
        "schema_version": "dse.dft.first_stage_mode_coverage_status.v1",
        "checked_at_local": report["checked_at_local"],
        "status": report["status"],
        "report": str(out_dir / "dft_mode_coverage_report.json"),
        "workflows": str(out_dir / "dft_mode_workflows.json"),
        "covered_mode_ids": report["covered_mode_ids"],
        "missing_mode_ids": report["missing_mode_ids"],
        "incomplete_mode_ids": report["incomplete_mode_ids"],
        "claim_boundary": report["claim_boundary"],
    })
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output directory for coverage artifacts")
    args = parser.parse_args(argv)
    report = build_report(args.out)
    print(json.dumps({
        "status": report["status"],
        "out": str(args.out),
        "covered_mode_ids": report["covered_mode_ids"],
        "missing_mode_ids": report["missing_mode_ids"],
        "incomplete_mode_ids": report["incomplete_mode_ids"],
        "claim_boundary": report["claim_boundary"],
    }, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
