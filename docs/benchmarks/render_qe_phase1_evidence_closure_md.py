#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a human-readable Markdown summary from a QE phase-1 evidence-closure JSON report."
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to qe_phase1_evidence_closure_report_v0 JSON")
    parser.add_argument("--output", required=True, type=Path, help="Markdown output path")
    return parser.parse_args()


def load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_bool(value: bool) -> str:
    return "yes" if value else "no"


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    lines: list[str] = []
    lines.append("# QE Phase-1 Evidence Closure Summary\n")
    lines.append("## Overall status\n")
    lines.append(f"- repo_internal_status: `{summary['repo_internal_status']}`")
    lines.append(f"- decisive_lane_closed: `{fmt_bool(summary['decisive_lane_closed'])}`")
    lines.append(f"- next_blocker_class: `{summary['next_blocker_class']}`")
    lines.append(f"- gpu_decisive_ready_cases: `{summary['gpu_decisive_ready_cases']}`")
    lines.append(f"- board_ready_cases: `{summary['board_ready_cases']}`")
    lines.append(
        f"- thesis_count_candidate_ready_cases: `{summary['thesis_count_candidate_ready_cases']}`"
    )
    lines.append("")
    lines.append("## Decisive lane targets\n")
    for item in summary["decisive_lane_targets"]:
        lines.append(f"- `{item}`")
    lines.append("")
    lines.append("## Case matrix\n")
    lines.append("| case_id | gpu_decisive_ready | board_ready | thesis_count_candidate_ready | gpu_blockers | board_blockers |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for row in report["case_matrix"]:
        gpu_blockers = ", ".join(row["gpu_blockers"]) if row["gpu_blockers"] else "-"
        board_blockers = ", ".join(row["board_blockers"]) if row["board_blockers"] else "-"
        lines.append(
            f"| `{row['case_id']}` | `{fmt_bool(row['gpu_decisive_ready'])}` | "
            f"`{fmt_bool(row['board_ready'])}` | `{fmt_bool(row['thesis_count_candidate_ready'])}` | "
            f"{gpu_blockers} | {board_blockers} |"
        )
    lines.append("")
    lines.append("## GPU row details\n")
    if report["gpu_rows"]:
        lines.append("| case_id | gpu_mode | status | decisive_for_case | case_ready | reason |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for row in report["gpu_rows"]:
            lines.append(
                f"| `{row.get('case_id','-')}` | `{row.get('gpu_mode','-')}` | `{row['status']}` | "
                f"`{fmt_bool(bool(row.get('decisive_for_case', False)))}` | "
                f"`{fmt_bool(bool(row.get('case_ready', False)))}` | {row.get('reason','-')} |"
            )
    else:
        lines.append("- no GPU baseline directories were supplied")
    lines.append("")
    lines.append("## Board row details\n")
    if report["board_rows"]:
        lines.append("| case_id | status | reason |")
        lines.append("| --- | --- | --- |")
        for row in report["board_rows"]:
            lines.append(
                f"| `{row.get('case_id','-')}` | `{row['status']}` | {row.get('reason','-')} |"
            )
    else:
        lines.append("- no board directories were supplied")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    report = load_report(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(report), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
