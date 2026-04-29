#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "docs" / "benchmarks"
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from unified_dse.backend_execution import (  # type: ignore  # noqa: E402
    validate_backend_execution_report,
)
from unified_dse.calibration_feedback import (  # type: ignore  # noqa: E402
    summarize_calibration_feedback,
    validate_calibration_feedback,
)
from unified_dse.correctness_report import (  # type: ignore  # noqa: E402
    summarize_correctness_report,
    validate_correctness_report,
)
from unified_dse.stage_c_qe_correctness import (  # type: ignore  # noqa: E402
    summarize_qe_correctness_report,
    validate_qe_correctness_report,
)
from unified_dse.stage_d_implementation_evidence import (  # type: ignore  # noqa: E402
    summarize_implementation_evidence,
    validate_implementation_evidence,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a claim-safe backend release bundle v0")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--request", action="append", default=[])
    parser.add_argument("--backend-report", action="append", default=[])
    parser.add_argument("--correctness-report")
    parser.add_argument("--implementation-evidence")
    parser.add_argument("--calibration-feedback")
    parser.add_argument("--reproduction-command", action="append", default=[])
    return parser.parse_args(argv)


def load_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact root must be an object: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def backend_summary(path: str) -> dict[str, Any]:
    payload = load_json(path)
    validate_backend_execution_report(payload)
    return {
        "artifact_ref": path,
        "candidate_id": payload.get("candidate_id"),
        "execution_status": payload.get("execution_status"),
        "fidelity": payload.get("fidelity"),
        "claim_ceiling": payload.get("claim_ceiling"),
    }


def optional_correctness_summary(path: str | None) -> dict[str, Any]:
    if path is None:
        return {
            "artifact_ref": None,
            "correctness_status": "baseline_missing",
            "workload_equivalent_claim": False,
            "claim_ceiling": "not_applicable",
        }
    payload = load_json(path)
    if payload.get("schema_version") == "correctness_report_v0":
        validate_correctness_report(payload)
        summary = summarize_correctness_report(payload) | {"artifact_ref": path}
        summary["qe_equivalent_scf_claim"] = False
        return summary
    validate_qe_correctness_report(payload)
    summary = summarize_qe_correctness_report(payload) | {"artifact_ref": path}
    summary["workload_equivalent_claim"] = summary.get("qe_equivalent_scf_claim") is True
    return summary


def optional_implementation_summary(path: str | None) -> dict[str, Any]:
    if path is None:
        return {
            "artifact_ref": None,
            "evidence_status": "missing",
            "claim_ceiling": "not_applicable",
        }
    payload = load_json(path)
    validate_implementation_evidence(payload)
    return summarize_implementation_evidence(payload) | {"artifact_ref": path}


def optional_calibration_summary(path: str | None) -> dict[str, Any]:
    if path is None:
        return {
            "artifact_ref": None,
            "calibration_status": "not_measured",
            "claim_ceiling": "not_applicable",
        }
    payload = load_json(path)
    if payload.get("schema_version") == "calibration_feedback_v0":
        validate_calibration_feedback(payload)
        return summarize_calibration_feedback(payload) | {"artifact_ref": path}
    residual_summary = payload.get("calibration_residual_summary")
    residual_summary = residual_summary if isinstance(residual_summary, Mapping) else {}
    return {
        "artifact_ref": path,
        "calibration_status": str(residual_summary.get("status", "referenced")),
        "claim_ceiling": "calibration_reference_only",
        "schema_version": str(payload.get("schema_version")),
    }


def build_claim_matrix(reports: list[Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    for item in reports:
        rows.append(
            {
                "candidate_id": item.get("candidate_id"),
                "fidelity": item.get("fidelity"),
                "execution_status": item.get("execution_status"),
                "claim_ceiling": item.get("claim_ceiling"),
                "allowed_claim": "backend proxy evidence at the stated fidelity only",
                "forbidden_claims": [
                    "QE/domain/workload equivalence unless a separate correctness report passes",
                    "RTL/HLS/board/ASIC implementation evidence",
                    "final architecture recommendation",
                ],
            }
        )
    return {
        "schema_version": "backend_claim_ceiling_matrix_v0",
        "rows": rows,
        "global_non_claims": [
            "no_hidden_systemc_or_gem5_execution",
            "no_qe_equivalent_scf_without_correctness_report",
            "no_implementation_claim_without_external_evidence",
            "no_final_architecture_recommendation",
        ],
    }


def build_reproduction_commands(
    requests: list[str],
    reports: list[Mapping[str, Any]],
    provided_commands: list[str],
) -> list[str]:
    if provided_commands:
        return list(provided_commands)
    commands: list[str] = []
    for index, report in enumerate(reports):
        request_ref = requests[index] if index < len(requests) else "<request.json>"
        report_ref = report.get("artifact_ref") or "<backend_report.json>"
        mode = report.get("fidelity") or "<mode>"
        commands.append(
            "python3 backend/runners/run_backend_execution_v0.py "
            f"--request {request_ref} --output {report_ref} --mode {mode} --allow-execute"
        )
    return commands


def write_memo(path: Path, manifest: Mapping[str, Any]) -> None:
    reports = manifest.get("backend_reports", [])
    lines = [
        "# Backend release bundle memo",
        "",
        "This bundle is claim-safe backend execution evidence only.",
        "",
        "## Backend reports",
    ]
    if isinstance(reports, list):
        for item in reports:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"- `{item.get('candidate_id')}`: {item.get('execution_status')} "
                f"{item.get('fidelity')} ({item.get('claim_ceiling')})"
            )
    lines += [
        "",
        "## Correctness and calibration",
        f"- Correctness: {manifest.get('correctness', {}).get('correctness_status', 'unknown')}",
        f"- Calibration: {manifest.get('calibration_feedback', {}).get('calibration_status', 'unknown')}",
        "",
        "## Non-claims",
        "- No QE-equivalent SCF correctness is claimed by BackendExecutionReport artifacts.",
        "- No RTL/HLS/board/ASIC measurement is claimed by backend proxy reports.",
        "- No final architecture recommendation is made by this bundle.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    backend_reports = [backend_summary(path) for path in args.backend_report]
    correctness = optional_correctness_summary(args.correctness_report)
    implementation = optional_implementation_summary(args.implementation_evidence)
    calibration = optional_calibration_summary(args.calibration_feedback)

    claim_matrix = build_claim_matrix(backend_reports)
    matrix_path = output_dir / "claim_ceiling_matrix_v0.json"
    write_json(matrix_path, claim_matrix)

    manifest = {
        "schema_version": "backend_release_bundle_manifest_v0",
        "requests": list(args.request),
        "backend_reports": backend_reports,
        "correctness": correctness,
        "implementation_evidence": implementation,
        "calibration_feedback": calibration,
        "calibration_feedback_ref": args.calibration_feedback,
        "claim_ceiling_matrix_ref": str(matrix_path),
        "reproduction_commands": build_reproduction_commands(
            list(args.request),
            backend_reports,
            list(args.reproduction_command),
        ),
        "bundle_status": "generated",
        "claim_posture": "supporting_backend_evidence_only",
    }
    manifest_path = output_dir / "backend_release_bundle_manifest_v0.json"
    write_json(manifest_path, manifest)
    write_memo(output_dir / "adjudicator_memo_backend_v0.md", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
