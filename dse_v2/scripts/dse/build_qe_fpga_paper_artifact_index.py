#!/usr/bin/env python3
"""Archive paper-facing QE-FPGA summary artifacts and write provenance index."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True, help="Source paper_ready_experiment_summary.json")
    parser.add_argument("--tables", type=Path, required=True, help="Generated results_tables.tex")
    parser.add_argument("--out", type=Path, required=True, help="Output artifact_index.json")
    parser.add_argument("--archive-summary", type=Path, required=True, help="Repo-local archived summary path")
    parser.add_argument("--pdf", type=Path, required=True, help="Compiled ACM/DAC manuscript PDF")
    parser.add_argument("--table-command", default="", help="Command used to generate the table include")
    parser.add_argument("--latex-command", default="", help="Command used to build the paper PDF")
    return parser.parse_args(list(argv))


def _load_json_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _artifact_ref(path: Path) -> Dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _file_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _summary_ref(path: Path, summary: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        **_artifact_ref(path),
        "schema_version": str(summary.get("schema_version", "")),
        "status": str(summary.get("status", "")),
        "method_name": str(summary.get("method_name", "")),
        "method_full_name": str(summary.get("method_full_name", "")),
        "algorithm_family": str(summary.get("algorithm_family", "")),
        "neuromf_policy_evaluation": dict(summary.get("neuromf_policy_evaluation", {}))
        if isinstance(summary.get("neuromf_policy_evaluation"), Mapping)
        else {},
        "independent_algorithm_benchmark": dict(summary.get("independent_algorithm_benchmark", {}))
        if isinstance(summary.get("independent_algorithm_benchmark"), Mapping)
        else {},
        "wamf_dse": dict(summary.get("wamf_dse", {}))
        if isinstance(summary.get("wamf_dse"), Mapping)
        else {},
        "workload_corpus": dict(summary.get("workload_corpus", {}))
        if isinstance(summary.get("workload_corpus"), Mapping)
        else {},
        "search": dict(summary.get("search", {})) if isinstance(summary.get("search"), Mapping) else {},
        "l3_feedback": dict(summary.get("l3_feedback", {}))
        if isinstance(summary.get("l3_feedback"), Mapping)
        else {},
        "claim_boundary": str(summary.get("claim_boundary", "")),
    }


def build_index(
    *,
    summary_path: Path,
    tables_path: Path,
    pdf_path: Path,
    out_path: Path,
    archive_summary_path: Path,
    table_command: str,
    latex_command: str,
) -> Dict[str, Any]:
    summary = _load_json_object(summary_path)
    if summary.get("schema_version") != "dse.qe_fpga_paper_ready_experiment_summary.v1":
        raise ValueError("unexpected paper-ready experiment summary schema")
    if not tables_path.exists():
        raise FileNotFoundError(tables_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    archive_summary_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(summary_path, archive_summary_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    archived_summary = _load_json_object(archive_summary_path)
    if archived_summary != summary:
        raise ValueError("archived summary does not match source summary")

    index = {
        "schema_version": "dse.qe_fpga_paper_artifact_index.v1",
        "status": "indexed",
        "source_summary": _summary_ref(summary_path, summary),
        "archived_summary": _summary_ref(archive_summary_path, archived_summary),
        "generated_tables": _artifact_ref(tables_path),
        "compiled_pdf": {
            **_artifact_ref(pdf_path),
            "artifact_role": "compiled_acm_dac_latex_pdf",
        },
        "commands": {
            "table_generation": str(table_command),
            "latex_build": str(latex_command),
        },
        "limitations": [
            "fixture_corpus_not_measured_QE_benchmark_suite",
            "generic_sim_feedback_not_QE_correctness_or_hardware_timing",
            "HLS_Vivado_bitstream_results_still_missing",
            "paper_artifact_index_records_current_fixture_tables_not_final_DAC_evidence",
        ],
        "paper_artifact_boundary": "fixture_generic_sim_tables_not_DAC_final_hardware_result",
    }
    out_path.write_text(json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return index


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    index = build_index(
        summary_path=args.summary,
        tables_path=args.tables,
        pdf_path=args.pdf,
        out_path=args.out,
        archive_summary_path=args.archive_summary,
        table_command=args.table_command,
        latex_command=args.latex_command,
    )
    print(json.dumps({"status": index["status"], "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
