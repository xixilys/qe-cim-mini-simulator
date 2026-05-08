#!/usr/bin/env python3
"""Validate DSE predictions against a truthy GPU/baseline case list.

The validator now supports 15-case case lists, deferred rows, and status-only
reports. When prediction data is unavailable, the report still records completed
vs deferred coverage and surfaces the missing comparison surfaces explicitly.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_MAPE_THRESHOLD = 0.20
DEFAULT_CASE_LIST = Path("docs/benchmarks/gpu_case_list_v0.json")
DEFAULT_DSE_RESULTS = Path("docs/benchmarks/results/systemc_architecture_family_dse_bootstrap/systemc_architecture_family_dse_bootstrap_v0.json")


@dataclass
class CaseConfidence:
    case_id: str
    status: str
    predicted_latency_s: Optional[float]
    actual_latency_s: Optional[float]
    relative_error: Optional[float]
    abs_relative_error: Optional[float]
    within_threshold: Optional[bool]
    weight: float
    note: str = ""


def load_case_list(path: Path) -> List[Dict]:
    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    if isinstance(payload, dict) and "cases" in payload:
        return payload["cases"]
    if isinstance(payload, list):
        return payload
    raise ValueError(f"Unsupported case-list structure in {path}")


def load_dse_results(path: Path) -> Dict[str, Dict]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    predictions: Dict[str, Dict] = {}
    for row in data.get("results", []):
        workload = row.get("workload", {})
        case_id = workload.get("workload_id") or workload.get("case_id") or row.get("workload_id") or row.get("case_id")
        if not case_id:
            continue
        metrics = row.get("primary_metrics", {})
        latency = metrics.get("time_to_convergence_s")
        predictions[case_id] = {
            "predicted_latency_s": latency,
            "result_status": row.get("result_status", "unknown"),
            "source_kind": row.get("source_kind", "unknown"),
        }
    return predictions


def compute_relative_error(predicted: float, actual: float) -> float:
    if actual == 0:
        return float("inf") if predicted != 0 else 0.0
    return (predicted - actual) / actual


def classify_confidence(weighted_mape: Optional[float], coverage_score: float, evaluated_count: int) -> str:
    if evaluated_count == 0 or weighted_mape is None:
        return "insufficient"
    if weighted_mape <= 0.10 and coverage_score >= 0.80:
        return "high"
    if weighted_mape <= 0.20 and coverage_score >= 0.60:
        return "medium"
    if weighted_mape <= 0.35 and coverage_score >= 0.40:
        return "low"
    return "insufficient"


def build_case_results(case_list: List[Dict], dse_predictions: Dict[str, Dict], mape_threshold: float) -> List[CaseConfidence]:
    total_cases = len(case_list) or 1
    results: List[CaseConfidence] = []
    for case in case_list:
        case_id = case["case_id"]
        status = case.get("status", "unknown")
        weight = 1.0 / total_cases
        pred = dse_predictions.get(case_id, {}).get("predicted_latency_s")
        actual = case.get("actual_latency_s")
        note = case.get("status_note", case.get("defer_reason", ""))

        rel_error = None
        abs_rel_error = None
        within_threshold = None
        if status == "completed" and isinstance(pred, (int, float)) and isinstance(actual, (int, float)) and actual > 0:
            rel_error = compute_relative_error(float(pred), float(actual))
            abs_rel_error = abs(rel_error)
            within_threshold = abs_rel_error <= mape_threshold

        results.append(
            CaseConfidence(
                case_id=case_id,
                status=status,
                predicted_latency_s=pred if isinstance(pred, (int, float)) else None,
                actual_latency_s=actual if isinstance(actual, (int, float)) else None,
                relative_error=rel_error,
                abs_relative_error=abs_rel_error,
                within_threshold=within_threshold,
                weight=weight,
                note=note,
            )
        )
    return results


def compute_metrics(case_results: List[CaseConfidence], mape_threshold: float) -> Dict:
    total_cases = len(case_results)
    completed = [r for r in case_results if r.status == "completed"]
    deferred = [r for r in case_results if r.status != "completed"]
    evaluated = [r for r in completed if r.predicted_latency_s is not None and r.actual_latency_s is not None and r.actual_latency_s > 0]

    weighted_mape: Optional[float] = None
    if evaluated:
        total_weight = sum(r.weight for r in evaluated)
        if total_weight > 0:
            weighted_mape = sum(r.weight * (r.abs_relative_error or 0.0) for r in evaluated) / total_weight

    coverage_score = len(completed) / total_cases if total_cases else 0.0
    overall_confidence = classify_confidence(weighted_mape, coverage_score, len(evaluated))

    return {
        "weighted_mape": weighted_mape,
        "coverage_score": coverage_score,
        "overall_confidence": overall_confidence,
        "summary": {
            "total_cases": total_cases,
            "completed_cases": len(completed),
            "deferred_cases": len(deferred),
            "evaluated_cases": len(evaluated),
            "cases_within_threshold": sum(1 for r in evaluated if r.within_threshold),
            "cases_outside_threshold": sum(1 for r in evaluated if r.within_threshold is False),
            "completed_case_ids": [r.case_id for r in completed],
            "deferred_case_ids": [r.case_id for r in deferred],
            "deferred_status_counts": {status: sum(1 for r in deferred if r.status == status) for status in sorted({r.status for r in deferred})},
            "evaluated_case_ids": [r.case_id for r in evaluated],
            "comparison_mode": "status_only" if not evaluated else "hybrid",
            "mape_threshold": mape_threshold,
        },
    }


def generate_json_report(case_results: List[CaseConfidence], validation_metrics: Dict, dse_path: str, case_list_path: str, mape_threshold: float) -> Dict:
    return {
        "schema_version": "dse_gpu_confidence_report_v0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dse_result_path": dse_path,
        "case_list_path": case_list_path,
        "mape_threshold": mape_threshold,
        "case_results": [asdict(r) for r in case_results],
        "weighted_mape": validation_metrics["weighted_mape"],
        "coverage_score": validation_metrics["coverage_score"],
        "overall_confidence": validation_metrics["overall_confidence"],
        "summary": validation_metrics["summary"],
    }


def generate_markdown_report(report: Dict) -> str:
    lines = [
        "# DSE vs GPU Baseline Confidence Report",
        "",
        f"**Generated:** {report['timestamp']}",
        f"**DSE Results:** `{report['dse_result_path']}`",
        f"**Case List:** `{report['case_list_path']}`",
        f"**MAPE Threshold:** {report['mape_threshold']:.0%}",
        "",
        "## Overall Assessment",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Weighted MAPE | {('N/A' if report['weighted_mape'] is None else f'{report['weighted_mape']:.2%}')} |",
        f"| Coverage Score | {report['coverage_score']:.2%} |",
        f"| Overall Confidence | **{report['overall_confidence'].upper()}** |",
        "",
        "## Per-Case Status",
        "",
        "| Case | Status | Predicted (s) | Actual (s) | Rel. Error | Note |",
        "|------|--------|---------------|------------|------------|------|",
    ]
    for case in report["case_results"]:
        pred = "N/A" if case["predicted_latency_s"] is None else f"{case['predicted_latency_s']:.3f}"
        actual = "N/A" if case["actual_latency_s"] is None else f"{case['actual_latency_s']:.3f}"
        rel = "N/A" if case["relative_error"] is None else f"{case['relative_error']:+.1%}"
        note = case.get("note", "").replace("|", "\\|")
        lines.append(f"| {case['case_id']} | {case['status']} | {pred} | {actual} | {rel} | {note} |")

    summary = report["summary"]
    lines.extend([
        "",
        "## Summary",
        "",
        f"- Total cases: {summary['total_cases']}",
        f"- Completed cases: {summary['completed_cases']}",
        f"- Deferred cases: {summary['deferred_cases']}",
        f"- Evaluated cases: {summary['evaluated_cases']}",
        f"- Cases within threshold: {summary['cases_within_threshold']}",
        f"- Cases outside threshold: {summary['cases_outside_threshold']}",
        f"- Comparison mode: {summary['comparison_mode']}",
        "",
        "## Deferred Cases",
        "",
    ])
    for case_id in summary["deferred_case_ids"]:
        lines.append(f"- {case_id}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate DSE predictions against a truthy GPU/baseline case list")
    parser.add_argument("--case-list", type=Path, default=DEFAULT_CASE_LIST, help="Case-list JSON file")
    parser.add_argument("--dse-results", type=Path, default=DEFAULT_DSE_RESULTS, help="DSE result JSON file")
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/gpu_confidence_reports"), help="Output directory")
    parser.add_argument("--mape-threshold", type=float, default=DEFAULT_MAPE_THRESHOLD, help=f"MAPE threshold (default: {DEFAULT_MAPE_THRESHOLD})")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    case_list = load_case_list(args.case_list)
    dse_predictions = load_dse_results(args.dse_results)
    case_results = build_case_results(case_list, dse_predictions, args.mape_threshold)
    validation_metrics = compute_metrics(case_results, args.mape_threshold)

    json_report = generate_json_report(case_results, validation_metrics, str(args.dse_results), str(args.case_list), args.mape_threshold)
    json_path = args.output_dir / "confidence_report.json"
    json_path.write_text(json.dumps(json_report, indent=2), encoding="utf-8")

    md_report = generate_markdown_report(json_report)
    md_path = args.output_dir / "confidence_report.md"
    md_path.write_text(md_report, encoding="utf-8")

    print(f"JSON report written: {json_path}")
    print(f"Markdown report written: {md_path}")
    print(f"Coverage Score: {validation_metrics['coverage_score']:.2%}")
    print(f"Completed cases: {validation_metrics['summary']['completed_cases']}")
    print(f"Deferred cases: {validation_metrics['summary']['deferred_cases']}")
    print(f"Overall Confidence: {validation_metrics['overall_confidence'].upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
