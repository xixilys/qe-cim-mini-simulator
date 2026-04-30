#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "claim_ceiling_status_matrix_v0"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from unified_dse import stage_c_qe_correctness, stage_d_implementation_evidence


def load_json(path: Path | str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def load_stage_c_report(path: Path | str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return stage_c_qe_correctness.load_and_validate_qe_correctness_report(path)


def load_implementation_evidence(path: Path | str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return stage_d_implementation_evidence.load_and_validate_implementation_evidence(path)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare_overall_pass(stage_c_report: Mapping[str, Any] | None) -> bool | None:
    if not isinstance(stage_c_report, Mapping):
        return None
    compare = stage_c_report.get("compare_report")
    if not isinstance(compare, Mapping):
        return None
    value = compare.get("overall_pass")
    return value if isinstance(value, bool) else None


def metric(report: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(report, Mapping):
        return None
    metrics = report.get("metrics")
    if isinstance(metrics, Mapping):
        return metrics.get(key)
    return None


def backend_summary(path: Path | str | None, report: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        return {"report_ref": None, "claim_ceiling": "not_applicable", "execution_status": "not_requested"}
    return {
        "report_ref": None if path is None else str(path),
        "claim_ceiling": report.get("claim_ceiling"),
        "execution_status": report.get("execution_status"),
        "backend_class": report.get("backend_class"),
        "cycle_proxy": metric(report, "cycle_proxy"),
    }


def observed_ceiling(
    stage_c_report: Mapping[str, Any] | None,
    implementation_evidence: Mapping[str, Any] | None,
    b4_report: Mapping[str, Any] | None,
    b2_report: Mapping[str, Any] | None,
) -> str:
    stage_c_pass = (
        isinstance(stage_c_report, Mapping)
        and stage_c_report.get("qe_equivalent_scf_claim") is True
    )
    if isinstance(implementation_evidence, Mapping):
        stage_d_ceiling = str(implementation_evidence.get("claim_ceiling"))
        status = implementation_evidence.get("evidence_status")
        if stage_c_pass and status == "available" and stage_d_ceiling not in {"implementation_evidence_only", "None", ""}:
            return f"qe_equivalent_scf_correctness_plus_{stage_d_ceiling}"
        if stage_c_pass:
            return "qe_equivalent_scf_correctness_plus_partial_implementation_projection_only"
        return stage_d_ceiling
    if isinstance(stage_c_report, Mapping):
        return str(stage_c_report.get("claim_ceiling"))
    if isinstance(b4_report, Mapping):
        return str(b4_report.get("claim_ceiling"))
    if isinstance(b2_report, Mapping):
        return str(b2_report.get("claim_ceiling"))
    return "no_evidence"


def blockers(
    stage_c_report: Mapping[str, Any] | None,
    implementation_evidence: Mapping[str, Any] | None,
) -> list[str]:
    items: list[str] = []
    if not isinstance(stage_c_report, Mapping):
        items.append("missing_stage_c_qe_correctness_report")
    elif stage_c_report.get("qe_equivalent_scf_claim") is not True:
        items.append("stage_c_qe_equivalent_scf_not_proven")
    if not isinstance(implementation_evidence, Mapping):
        items.append("missing_stage_d_implementation_evidence")
    elif implementation_evidence.get("evidence_status") != "available":
        items.append("stage_d_implementation_evidence_not_available")
    return items


def build_matrix(
    *,
    output_ref: Path | None = None,
    candidate_id: str | None = None,
    workload_id: str | None = None,
    case_id: str | None = None,
    family: str | None = None,
    stage_c_report_ref: Path | str | None = None,
    stage_c_report: Mapping[str, Any] | None = None,
    implementation_evidence_ref: Path | str | None = None,
    implementation_evidence: Mapping[str, Any] | None = None,
    b2_report_ref: Path | str | None = None,
    b2_report: Mapping[str, Any] | None = None,
    b3_report_ref: Path | str | None = None,
    b3_report: Mapping[str, Any] | None = None,
    b4_report_ref: Path | str | None = None,
    b4_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_id = (
        candidate_id
        or (str(stage_c_report.get("candidate_id")) if isinstance(stage_c_report, Mapping) and stage_c_report.get("candidate_id") else None)
        or (str(implementation_evidence.get("candidate_id")) if isinstance(implementation_evidence, Mapping) and implementation_evidence.get("candidate_id") else None)
        or (str(b2_report.get("candidate_id")) if isinstance(b2_report, Mapping) and b2_report.get("candidate_id") else None)
        or "unknown_candidate"
    )
    workload_id = workload_id or (
        str(stage_c_report.get("workload_id")) if isinstance(stage_c_report, Mapping) and stage_c_report.get("workload_id") else None
    )
    case_id = case_id or (
        str(stage_c_report.get("case_id")) if isinstance(stage_c_report, Mapping) and stage_c_report.get("case_id") else workload_id
    )
    row = {
        "candidate_id": candidate_id,
        "family": family,
        "workload_id": workload_id,
        "case_id": case_id,
        "stage_c_report_ref": None if stage_c_report_ref is None else str(stage_c_report_ref),
        "correctness_status": stage_c_report.get("correctness_status") if isinstance(stage_c_report, Mapping) else None,
        "compare_overall_pass": compare_overall_pass(stage_c_report),
        "qe_equivalent_scf_claim": stage_c_report.get("qe_equivalent_scf_claim") is True if isinstance(stage_c_report, Mapping) else False,
        "stage_c_claim_ceiling": stage_c_report.get("claim_ceiling") if isinstance(stage_c_report, Mapping) else "not_applicable",
        "stage_d_report_ref": None if implementation_evidence_ref is None else str(implementation_evidence_ref),
        "implementation_target_class": implementation_evidence.get("implementation_target_class") if isinstance(implementation_evidence, Mapping) else None,
        "evidence_kind": implementation_evidence.get("evidence_kind") if isinstance(implementation_evidence, Mapping) else None,
        "evidence_status": implementation_evidence.get("evidence_status") if isinstance(implementation_evidence, Mapping) else None,
        "stage_d_claim_ceiling": implementation_evidence.get("claim_ceiling") if isinstance(implementation_evidence, Mapping) else "not_applicable",
        "correctness_dependency": implementation_evidence.get("correctness_dependency") if isinstance(implementation_evidence, Mapping) else None,
        "b2": backend_summary(b2_report_ref, b2_report),
        "b3": backend_summary(b3_report_ref, b3_report),
        "b4": backend_summary(b4_report_ref, b4_report),
        "final_observed_conclusion_ceiling": observed_ceiling(stage_c_report, implementation_evidence, b4_report, b2_report),
        "adjudicator_permission_scope": "not_evaluated",
        "blockers": blockers(stage_c_report, implementation_evidence),
        "non_claims": [
            "no_cycle_accuracy_claim_without_rtl_or_board_timing_evidence",
            "no_final_public_winner",
            "no_production_release_ready_claim",
        ],
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "adjudicator_permission_scope": "not_evaluated",
        "matrix_ref": None if output_ref is None else str(output_ref),
        "row_count": 1,
        "rows": [row],
        "global_non_claims": [
            "status_matrix_is_not_adjudicator_permission",
            "no_hidden_qe_or_implementation_execution",
            "no_cycle_accuracy_claim_without_rtl_or_board_timing_evidence",
            "no_final_public_winner",
        ],
    }
    return payload


def write_markdown(path: Path, matrix: Mapping[str, Any]) -> None:
    rows = matrix.get("rows", [])
    lines = [
        "# QE DSE claim-ceiling status matrix v0",
        "",
        "This matrix reports observed evidence ceilings only. It is not an adjudicator permission matrix.",
        "",
        "| candidate | Stage C | Stage D | B2 | B3 | B4 | observed ceiling | blockers |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "| {candidate} | {stage_c} | {stage_d} | {b2} | {b3} | {b4} | {ceiling} | {blockers} |".format(
                    candidate=row.get("candidate_id"),
                    stage_c=row.get("stage_c_claim_ceiling"),
                    stage_d=row.get("stage_d_claim_ceiling"),
                    b2=(row.get("b2") or {}).get("claim_ceiling") if isinstance(row.get("b2"), Mapping) else None,
                    b3=(row.get("b3") or {}).get("claim_ceiling") if isinstance(row.get("b3"), Mapping) else None,
                    b4=(row.get("b4") or {}).get("claim_ceiling") if isinstance(row.get("b4"), Mapping) else None,
                    ceiling=row.get("final_observed_conclusion_ceiling"),
                    blockers=", ".join(row.get("blockers", [])) if isinstance(row.get("blockers"), list) else "",
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build QE DSE claim-ceiling status matrix v0.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--candidate-id")
    parser.add_argument("--workload-id")
    parser.add_argument("--case-id")
    parser.add_argument("--family")
    parser.add_argument("--stage-c-report", type=Path)
    parser.add_argument("--implementation-evidence", type=Path)
    parser.add_argument("--b2-report", type=Path)
    parser.add_argument("--b3-report", type=Path)
    parser.add_argument("--b4-report", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    matrix = build_matrix(
        output_ref=args.output,
        candidate_id=args.candidate_id,
        workload_id=args.workload_id,
        case_id=args.case_id,
        family=args.family,
        stage_c_report_ref=args.stage_c_report,
        stage_c_report=load_stage_c_report(args.stage_c_report),
        implementation_evidence_ref=args.implementation_evidence,
        implementation_evidence=load_implementation_evidence(args.implementation_evidence),
        b2_report_ref=args.b2_report,
        b2_report=load_json(args.b2_report),
        b3_report_ref=args.b3_report,
        b3_report=load_json(args.b3_report),
        b4_report_ref=args.b4_report,
        b4_report=load_json(args.b4_report),
    )
    write_json(args.output, matrix)
    if args.markdown_output is not None:
        write_markdown(args.markdown_output, matrix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
