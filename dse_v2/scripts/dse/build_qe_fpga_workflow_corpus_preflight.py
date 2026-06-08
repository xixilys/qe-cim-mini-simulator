#!/usr/bin/env python3
"""Preflight a QE workflow corpus before running QE-to-FPGA DSE."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.scripts.dse.run_qe_fpga_deployment_dse import (  # noqa: E402
    build_qe_fpga_workflow_corpus_report,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(list(argv))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = build_qe_fpga_workflow_corpus_report(args.workflow_corpus)
    readiness = report.get("measured_qe_corpus_readiness", {})
    status = {
        "schema_version": "dse.qe_fpga.workflow_corpus_preflight_status.v1",
        "status": str(readiness.get("status", "blocked")),
        "workflow_corpus": str(args.workflow_corpus),
        "report": str(args.out / "qe_fpga_workload_corpus_preflight.json"),
        "workload_count": int(report.get("workload_count", 0)),
        "measured_ready_workload_count": int(readiness.get("measured_ready_workload_count", 0)),
        "blockers": list(readiness.get("blockers", []) or []),
        "allowed_use": str(readiness.get("allowed_use", "")),
        "forbidden_use": list(readiness.get("forbidden_use", []) or []),
        "claim_boundary": "workflow_corpus_preflight_only_not_search_hardware_or_qe_correctness_evidence",
    }
    _write_json(args.out / "qe_fpga_workload_corpus_preflight.json", report)
    _write_json(args.out / "qe_fpga_workload_corpus_preflight_status.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0 if status["status"] == "ready_for_model_level_experiments" else 1


if __name__ == "__main__":
    raise SystemExit(main())
