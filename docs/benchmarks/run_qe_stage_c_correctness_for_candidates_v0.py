#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import gmtime, strftime
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import materialize_qe_stage_c_correctness_v0 as stage_c_materializer

SCHEMA_VERSION = "stage_c_correctness_for_candidates_run_v0"


def load_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _candidate_rows(candidate_manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = candidate_manifest.get("candidates")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, Mapping)]
    return []


def run_for_candidates(
    *,
    candidate_manifest_path: Path,
    output_dir: Path,
    gold_summary: Path | None = None,
    matrix_name: str = stage_c_materializer.DEFAULT_MATRIX_NAME,
) -> dict[str, Any]:
    candidate_manifest = load_json(candidate_manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    if gold_summary is None:
        rows = []
        for candidate in _candidate_rows(candidate_manifest):
            rows.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "family": candidate.get("family"),
                    "workload_id": candidate.get("workload_id"),
                    "case_id": candidate.get("case_id"),
                    "execution_status": "refused",
                    "correctness_status": "stage_c_not_executed",
                    "qe_equivalent_scf_claim": False,
                    "claim_ceiling": "no_stage_c_evidence",
                    "not_executed_reason": "missing_gold_summary_or_real_qe_correctness_runner",
                    "report_path": None,
                }
            )
        matrix = {
            "schema_version": "stage_c_correctness_matrix_v0",
            "generated_at_utc": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
            "source_candidate_manifest": str(candidate_manifest_path),
            "source_gold_summary": None,
            "execution_status": "refused",
            "not_executed_reason": "missing_gold_summary_or_real_qe_correctness_runner",
            "row_count": len(rows),
            "rows": rows,
            "non_claims": [
                "stage_c_wrapper_did_not_execute_qe",
                "no_qe_equivalent_scf_claim",
                "no_final_best_architecture_claim",
            ],
        }
        write_json(output_dir / matrix_name, matrix)
        return matrix
    return stage_c_materializer.materialize(
        gold_summary,
        output_dir,
        matrix_name=matrix_name,
        candidate_map_path=candidate_manifest_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run/materialize Stage C correctness for final-best candidate manifest.")
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--gold-summary", type=Path)
    parser.add_argument("--matrix-name", default=stage_c_materializer.DEFAULT_MATRIX_NAME)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_for_candidates(
        candidate_manifest_path=args.candidate_manifest,
        output_dir=args.output_dir,
        gold_summary=args.gold_summary,
        matrix_name=args.matrix_name,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
