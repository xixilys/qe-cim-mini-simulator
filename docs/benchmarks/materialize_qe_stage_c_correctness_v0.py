#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REPORT_SCHEMA_VERSION = "qe_dse_qe_equivalent_correctness_report_v0"
MATRIX_SCHEMA_VERSION = "stage_c_correctness_matrix_v0"
QE_TOLERANCE_SCHEMA_ID = "qe_gold_numerical_tolerance_schema_v0"
PASS_CLAIM_CEILING = "qe_equivalent_scf_correctness_only"
REFERENCE_ONLY_CLAIM_CEILING = "correctness_report_reference_only"
DEFAULT_MATRIX_NAME = "stage_c_correctness_matrix_v0.json"
REPORTS_DIR_NAME = "stage_c_reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize producer-side Stage C QE correctness reports from an "
            "existing qe_gold_gate_summary_v0.json."
        )
    )
    parser.add_argument(
        "--gold-summary",
        type=Path,
        required=True,
        help="Path to qe_gold_gate_summary_v0.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory that will receive stage_c_reports/ and the matrix JSON.",
    )
    parser.add_argument(
        "--matrix-name",
        default=DEFAULT_MATRIX_NAME,
        help=f"Matrix JSON filename under --output-dir (default: {DEFAULT_MATRIX_NAME}).",
    )
    parser.add_argument(
        "--candidate-map",
        type=Path,
        help=(
            "Optional JSON manifest/map used to resolve rows that lack candidate_id. "
            "Supports top-level candidates/selected_candidates/rows lists or a "
            "candidate_id-keyed object. Missing or ambiguous matches fail loudly."
        ),
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_filename_stem(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return name or "candidate"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _candidate_entries_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        raw_entries = payload
    elif isinstance(payload, dict):
        raw_entries = []
        for key in ("candidates", "selected_candidates", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                raw_entries = value
                break
        if not raw_entries:
            for candidate_id, value in payload.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("candidate_id", candidate_id)
                    raw_entries.append(item)
    else:
        raise ValueError("candidate map must be a JSON object or list")

    entries: list[dict[str, Any]] = []
    for index, item in enumerate(raw_entries):
        if not isinstance(item, dict):
            raise ValueError(f"candidate map entry {index} must be an object")
        candidate_identity = _mapping(item.get("candidate_identity"))
        design_axes = _mapping(item.get("design_axes")) or _mapping(candidate_identity.get("design_axes"))
        workload_identity = _mapping(item.get("workload_identity"))
        domain_extension = _mapping(item.get("domain_extension"))
        qe_extension = _mapping(domain_extension.get("qe"))
        candidate_id = item.get("candidate_id") or candidate_identity.get("candidate_id")
        if not candidate_id:
            raise ValueError(f"candidate map entry {index} missing candidate_id")
        family = (
            item.get("family")
            or design_axes.get("family")
            or candidate_identity.get("candidate_family")
            or candidate_identity.get("architecture_template_id")
        )
        workload_id = (
            item.get("workload_id")
            or workload_identity.get("workload_id")
            or qe_extension.get("workload_id")
            or qe_extension.get("case_id")
        )
        case_id = item.get("case_id") or qe_extension.get("case_id") or workload_id
        entries.append(
            {
                "candidate_id": str(candidate_id),
                "workload_id": str(workload_id) if workload_id is not None else None,
                "case_id": str(case_id) if case_id is not None else None,
                "family": str(family) if family is not None else None,
                "design_axes": design_axes,
            }
        )
    return entries


def load_candidate_map(path: Path | None) -> list[dict[str, Any]] | None:
    if path is None:
        return None
    return _candidate_entries_from_payload(load_json(path))


def _row_design_axes(row: dict[str, Any]) -> dict[str, Any]:
    design_axes = row.get("design_axes")
    if isinstance(design_axes, dict):
        return dict(design_axes)
    axes: dict[str, Any] = {}
    for key in ("diag_policy", "memory_policy", "mapping_policy", "partition_policy"):
        if key in row:
            axes[key] = row[key]
    return axes


def _entry_matches_row(entry: dict[str, Any], row: dict[str, Any]) -> bool:
    row_workload = first_present(row.get("workload_id"), row.get("case_id"))
    row_case = first_present(row.get("case_id"), row.get("workload_id"))
    row_family = first_present(row.get("family"))
    if row_workload and row_workload not in {entry.get("workload_id"), entry.get("case_id")}:
        return False
    if row_case and row_case not in {entry.get("case_id"), entry.get("workload_id")}:
        return False
    if row_family and str(row_family) != str(entry.get("family")):
        return False
    entry_axes = _mapping(entry.get("design_axes"))
    for key, value in _row_design_axes(row).items():
        if key not in entry_axes or str(entry_axes[key]) != str(value):
            return False
    return True


def candidate_id_for_row(
    row: dict[str, Any],
    index: int,
    candidate_map: list[dict[str, Any]] | None = None,
) -> str:
    candidate_id = row.get("candidate_id")
    if candidate_id:
        return str(candidate_id)
    if candidate_map is not None:
        matches = [entry for entry in candidate_map if _entry_matches_row(entry, row)]
        if len(matches) == 1:
            return str(matches[0]["candidate_id"])
        if len(matches) > 1:
            match_ids = ", ".join(str(entry["candidate_id"]) for entry in matches)
            raise ValueError(f"gold row {index} candidate map match is ambiguous: {match_ids}")
        raise ValueError(f"gold row {index} has no candidate_id and no exact candidate-map match")
    metrics_path = row.get("metrics_path")
    if metrics_path:
        return Path(str(metrics_path)).stem
    workload_id = str(row.get("workload_id") or row.get("case_id") or "unknown_workload")
    family = str(row.get("family") or "unknown_family")
    return f"{workload_id}__{family}__row_{index}"


def load_compare_report(row: dict[str, Any], gold_summary_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    compare_report_path = row.get("compare_report_path")
    if not compare_report_path:
        return None, None
    path = Path(str(compare_report_path))
    if not path.is_absolute():
        candidates = [path, gold_summary_path.parent / path]
    else:
        candidates = [path]
    for candidate in candidates:
        if candidate.exists():
            return load_json(candidate), str(compare_report_path)
    return None, str(compare_report_path)


def first_present(*values: Any) -> str | None:
    for value in values:
        if value is not None and value != "":
            return str(value)
    return None


def evidence_refs_for_row(
    row: dict[str, Any],
    compare_report: dict[str, Any] | None,
    compare_report_path: str | None,
) -> dict[str, str | None]:
    return {
        "baseline": first_present(
            row.get("baseline_path"),
            row.get("gold_path"),
            row.get("baseline_file"),
            compare_report.get("baseline_file") if isinstance(compare_report, dict) else None,
        ),
        "candidate": first_present(
            row.get("candidate_path"),
            row.get("metrics_path"),
            row.get("candidate_file"),
            compare_report.get("candidate_file") if isinstance(compare_report, dict) else None,
        ),
        "compare_report": compare_report_path,
    }


def report_for_row(
    row: dict[str, Any],
    index: int,
    gold_summary_path: Path,
    run_id: str,
    candidate_map: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidate_id = candidate_id_for_row(row, index, candidate_map)
    correctness_status = str(row.get("correctness_status") or row.get("status") or "compare_error")
    compare_report, compare_report_path = load_compare_report(row, gold_summary_path)
    if compare_report is None:
        compare_report = {
            "schema_name": QE_TOLERANCE_SCHEMA_ID,
            "schema_version": "2026-04-13",
            "overall_pass": False,
            "summary": {
                "status": correctness_status if correctness_status != "pass" else "compare_error",
                "failed_required_fields": list(row.get("required_field_failures", [])),
            },
        }
    compare_overall_pass = compare_report.get("overall_pass") is True
    is_pass = correctness_status == "pass" and compare_overall_pass
    workload_id = str(row.get("workload_id") or row.get("case_id") or "")
    case_id = str(row.get("case_id") or row.get("workload_id") or "")

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "execution_status": "executed",
        "claim_ceiling": PASS_CLAIM_CEILING if is_pass else REFERENCE_ONLY_CLAIM_CEILING,
        "report_id": f"{run_id}::{candidate_id}",
        "candidate_id": candidate_id,
        "workload_id": workload_id,
        "case_id": case_id,
        "family": row.get("family"),
        "qe_tolerance_schema_id": QE_TOLERANCE_SCHEMA_ID,
        "correctness_status": correctness_status,
        "qe_equivalent_scf_claim": is_pass,
        "compare_report": compare_report,
        "evidence_refs": evidence_refs_for_row(row, compare_report, compare_report_path),
    }


def materialize(
    gold_summary_path: Path,
    output_dir: Path,
    matrix_name: str = DEFAULT_MATRIX_NAME,
    candidate_map_path: Path | None = None,
) -> dict[str, Any]:
    summary = load_json(gold_summary_path)
    rows = summary.get("gold_rows")
    if not isinstance(rows, list):
        raise ValueError("gold summary must contain a top-level gold_rows list")

    run_id = str(summary.get("run_id") or gold_summary_path.stem)
    candidate_map = load_candidate_map(candidate_map_path)
    reports_dir = output_dir / REPORTS_DIR_NAME
    reports_dir.mkdir(parents=True, exist_ok=True)

    matrix_rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    claim_counts = {"qe_equivalent_scf_claim_true": 0, "qe_equivalent_scf_claim_false": 0}

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"gold_rows[{index}] must be an object")
        report = report_for_row(row, index, gold_summary_path, run_id, candidate_map)
        report_filename = f"{safe_filename_stem(report['candidate_id'])}.qe_dse_qe_equivalent_correctness_report_v0.json"
        report_path = reports_dir / report_filename
        write_json(report_path, report)

        status = str(report["correctness_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        claim_key = "qe_equivalent_scf_claim_true" if report["qe_equivalent_scf_claim"] else "qe_equivalent_scf_claim_false"
        claim_counts[claim_key] += 1
        matrix_rows.append(
            {
                "candidate_id": report["candidate_id"],
                "workload_id": report["workload_id"],
                "case_id": report["case_id"],
                "family": report["family"],
                "correctness_status": report["correctness_status"],
                "compare_overall_pass": report["compare_report"].get("overall_pass") is True,
                "qe_equivalent_scf_claim": report["qe_equivalent_scf_claim"],
                "claim_ceiling": report["claim_ceiling"],
                "report_path": str(report_path),
                "evidence_refs": report["evidence_refs"],
            }
        )

    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "source_gold_summary": str(gold_summary_path),
        "candidate_map_ref": str(candidate_map_path) if candidate_map_path else None,
        "source_gold_summary_schema_version": summary.get("schema_version"),
        "run_id": run_id,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "qe_tolerance_schema_id": QE_TOLERANCE_SCHEMA_ID,
        "reports_dir": str(reports_dir),
        "row_count": len(matrix_rows),
        "status_counts": status_counts,
        **claim_counts,
        "rows": matrix_rows,
    }
    write_json(output_dir / matrix_name, matrix)
    return matrix


def main() -> int:
    args = parse_args()
    materialize(args.gold_summary, args.output_dir, args.matrix_name, args.candidate_map)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
