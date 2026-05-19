#!/usr/bin/env python3
"""Collect per-row QE accelerated numeric evidence from a requirements manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.qe_accelerated_evidence import (  # noqa: E402
    QE_ACCELERATED_NUMERIC_EVIDENCE_SCHEMA,
    build_evidence_from_files,
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _blocked_row(row: Mapping[str, Any], blockers: Sequence[str], *, source_kind: str) -> Dict[str, Any]:
    return {
        "schema_version": QE_ACCELERATED_NUMERIC_EVIDENCE_SCHEMA,
        "candidate_id": str(row.get("candidate_id", "")),
        "workload_case_id": str(row.get("workload_case_id", "")),
        "source_kind": source_kind,
        "accelerated_output_status": "blocked",
        "trusted_accelerated_numeric_source": False,
        "baseline_reference": {"path": row.get("baseline_comparison")},
        "accelerated_reference": row.get("required_outputs", {}),
        "kernel_evidence": [],
        "physical_evidence": {},
        "blockers": sorted(dict.fromkeys(str(item) for item in blockers)),
        "claim_boundary": "Campaign collector could not build trusted accelerated QE numeric evidence for this row.",
    }


def _required_path(row: Mapping[str, Any], key: str) -> Path | None:
    required_outputs = row.get("required_outputs", {})
    if not isinstance(required_outputs, Mapping):
        return None
    value = required_outputs.get(key)
    return Path(str(value)) if value else None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--source-kind", default="qe_offload_runtime")
    parser.add_argument("--fail-on-blocked", action="store_true")
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    requirements = json.loads(args.requirements.read_text(encoding="utf-8"))
    rows = requirements.get("rows", []) if isinstance(requirements, Mapping) else []
    evidence_rows: list[Dict[str, Any]] = []
    blocked_count = 0

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        candidate_id = str(row.get("candidate_id", ""))
        workload_case_id = str(row.get("workload_case_id", ""))
        row_out = args.out_dir / candidate_id / workload_case_id / "qe_accelerated_numeric_evidence.json"
        baseline = Path(str(row.get("baseline_comparison", ""))) if row.get("baseline_comparison") else None
        accelerated_stdout = _required_path(row, "accelerated_stdout")
        kernel_evidence = _required_path(row, "kernel_evidence_json")
        provenance = _required_path(row, "offload_provenance_json")
        missing = [
            f"missing_required_campaign_input:{name}:{path}"
            for name, path in [
                ("baseline_comparison", baseline),
                ("accelerated_stdout", accelerated_stdout),
                ("kernel_evidence_json", kernel_evidence),
                ("offload_provenance_json", provenance),
            ]
            if path is None or not path.exists()
        ]
        if missing:
            evidence = _blocked_row(row, missing, source_kind=args.source_kind)
        else:
            try:
                evidence = build_evidence_from_files(
                    candidate_id=candidate_id,
                    workload_case_id=workload_case_id,
                    baseline_comparison_path=baseline,
                    accelerated_stdout_path=accelerated_stdout,
                    source_kind=args.source_kind,
                    kernel_evidence_path=kernel_evidence,
                    offload_provenance_path=provenance,
                )
            except Exception as exc:  # pragma: no cover - defensive campaign preservation
                evidence = _blocked_row(row, [f"campaign_evidence_build_exception:{exc}"], source_kind=args.source_kind)
        _write_json(row_out, evidence)
        evidence_rows.append(evidence)
        if evidence.get("trusted_accelerated_numeric_source") is not True:
            blocked_count += 1

    index = {
        "schema_version": "dse.qe_accelerated_numeric_evidence_campaign_index.v1",
        "requirements": str(args.requirements),
        "out_dir": str(args.out_dir),
        "row_count": len(evidence_rows),
        "trusted_row_count": len(evidence_rows) - blocked_count,
        "blocked_row_count": blocked_count,
        "rows": [
            {
                "candidate_id": row.get("candidate_id"),
                "workload_case_id": row.get("workload_case_id"),
                "trusted_accelerated_numeric_source": row.get("trusted_accelerated_numeric_source"),
                "blockers": row.get("blockers", []),
            }
            for row in evidence_rows
        ],
        "claim_boundary": "Campaign collection is an input to the full L4 matrix runner; it is not a completion claim by itself.",
    }
    _write_json(args.out_dir / "qe_accelerated_numeric_evidence_campaign_index.json", index)
    print(json.dumps(index, indent=2, sort_keys=True))
    return 2 if args.fail_on_blocked and blocked_count else 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
