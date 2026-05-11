#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_unified_dse_v0
from unified_dse import adjudication, backend_feedback_adapter, calibration_engine, release_bundle


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _add_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--design-space-spec", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-design-points", type=int, default=8)
    parser.add_argument("--search-backend", default="bounded_cartesian")
    parser.add_argument("--calibration", type=Path)


def _run_unified(args: argparse.Namespace, extra: list[str]) -> int:
    argv = [
        "--design-space-spec",
        str(args.design_space_spec),
        "--workload",
        str(args.workload),
        "--output-dir",
        str(args.output_dir),
        "--max-design-points",
        str(args.max_design_points),
        "--search-backend",
        str(args.search_backend),
        "--dry-run",
    ]
    if getattr(args, "calibration", None) is not None:
        argv.extend(["--calibration", str(args.calibration)])
    argv.extend(extra)
    return run_unified_dse_v0.main(argv)


def cmd_enumerate(args: argparse.Namespace) -> int:
    return _run_unified(args, ["--source-kind", "stub"])


def cmd_optimize(args: argparse.Namespace) -> int:
    extra = [
        "--source-kind",
        "fast_model_screening",
        "--shortlist-policy",
        args.shortlist_policy,
        "--shortlist-size",
        str(args.shortlist_size),
        "--emit-multi-fidelity-plan",
    ]
    return _run_unified(args, extra)


def cmd_emit_handoff(args: argparse.Namespace) -> int:
    extra = [
        "--source-kind",
        args.source_kind,
        "--emit-stage-b0-descriptors",
        "--stage-b0-emission-mode",
        args.stage_b0_emission_mode,
    ]
    if args.emit_multi_fidelity_plan:
        extra.append("--emit-multi-fidelity-plan")
    return _run_unified(args, extra)


def cmd_ingest_feedback(args: argparse.Namespace) -> int:
    payload = backend_feedback_adapter.load_backend_report_artifact(args.backend_report)
    evidence_rows = backend_feedback_adapter.normalize_backend_report_artifact(payload)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        args.output_dir / "evidence_ir_collection_v0.json",
        {
            "schema_version": "evidence_ir_collection_v0",
            "source_ref": str(args.backend_report),
            "evidence_count": len(evidence_rows),
            "evidence": evidence_rows,
        },
    )
    for evidence in evidence_rows:
        _write_json(args.output_dir / "evidence_ir" / f"{evidence['candidate_id']}.json", evidence)
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    evidence_payload = json.loads(args.evidence_ir.read_text(encoding="utf-8"))
    evidence_rows = evidence_payload.get("evidence", [])
    if not isinstance(evidence_rows, list):
        raise ValueError("evidence_ir collection requires evidence list")
    metadata = calibration_engine.fit_residual_calibration([], evidence_rows)
    model = calibration_engine.fit_calibration_model([], evidence_rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.output_dir / "calibration_metadata_v0.json", metadata)
    _write_json(args.output_dir / "calibration_model_v0.json", model)
    return 0


def cmd_adjudicate(args: argparse.Namespace) -> int:
    rows = []
    if args.result_bundle is not None and args.result_bundle.exists():
        bundle = json.loads(args.result_bundle.read_text(encoding="utf-8"))
        if isinstance(bundle.get("results"), list):
            rows = bundle["results"]
    summary = adjudication.build_adjudication_summary(
        rows,
        result_bundle_ref=str(args.result_bundle) if args.result_bundle else None,
        calibration_model_ref=args.calibration_model_ref,
        evidence_refs=args.evidence_ref or [],
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.output_dir / "frontend_adjudication_summary_v0.json", summary)
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    release_bundle.emit_release_bundle(
        args.output_dir,
        stage_status_ref=args.stage_status_ref,
        stage_b0_descriptor_manifest_ref=args.stage_b0_descriptor_manifest_ref,
        multi_fidelity_plan_ref=args.multi_fidelity_plan_ref,
        evidence_refs=args.evidence_ref or [],
        calibration_metadata_ref=args.calibration_metadata_ref,
        calibration_model_ref=args.calibration_model_ref,
        adjudication_summary_ref=args.adjudication_summary_ref,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Thin frontend wrapper for unified DSE JSON contracts.")
    subparsers = parser.add_subparsers(dest="surface", required=True)
    frontend = subparsers.add_parser("frontend", help="frontend-only DSE commands")
    commands = frontend.add_subparsers(dest="command", required=True)

    enumerate_parser = commands.add_parser("enumerate", help="enumerate descriptor-only candidates")
    _add_common_run_args(enumerate_parser)
    enumerate_parser.set_defaults(func=cmd_enumerate)

    optimize_parser = commands.add_parser("optimize", help="run fast-model frontend optimization")
    _add_common_run_args(optimize_parser)
    optimize_parser.add_argument("--shortlist-policy", default="top_fast_uncertain_diverse")
    optimize_parser.add_argument("--shortlist-size", type=int, default=3)
    optimize_parser.set_defaults(func=cmd_optimize)

    handoff_parser = commands.add_parser("emit-handoff", help="emit Stage-B0 backend handoff descriptors")
    _add_common_run_args(handoff_parser)
    handoff_parser.add_argument("--source-kind", default="stub", choices=("stub", "fast_model_screening"))
    handoff_parser.add_argument(
        "--stage-b0-emission-mode",
        default="all_valid_executable",
        choices=("all_valid_executable", "scheduler_selected_only"),
    )
    handoff_parser.add_argument("--emit-multi-fidelity-plan", action="store_true")
    handoff_parser.set_defaults(func=cmd_emit_handoff)

    ingest_parser = commands.add_parser("ingest-feedback", help="normalize backend report JSON into EvidenceIR")
    ingest_parser.add_argument("--backend-report", type=Path, required=True)
    ingest_parser.add_argument("--output-dir", type=Path, required=True)
    ingest_parser.set_defaults(func=cmd_ingest_feedback)

    calibrate_parser = commands.add_parser("calibrate", help="fit minimal residual calibration metadata")
    calibrate_parser.add_argument("--evidence-ir", type=Path, required=True)
    calibrate_parser.add_argument("--output-dir", type=Path, required=True)
    calibrate_parser.set_defaults(func=cmd_calibrate)

    adjudicate_parser = commands.add_parser("adjudicate", help="emit claim-safe adjudication summary")
    adjudicate_parser.add_argument("--result-bundle", type=Path)
    adjudicate_parser.add_argument("--calibration-model-ref")
    adjudicate_parser.add_argument("--evidence-ref", action="append")
    adjudicate_parser.add_argument("--output-dir", type=Path, required=True)
    adjudicate_parser.set_defaults(func=cmd_adjudicate)

    release_parser = commands.add_parser("release", help="emit release_bundle_v0")
    release_parser.add_argument("--output-dir", type=Path, required=True)
    release_parser.add_argument("--stage-status-ref")
    release_parser.add_argument("--stage-b0-descriptor-manifest-ref")
    release_parser.add_argument("--multi-fidelity-plan-ref")
    release_parser.add_argument("--evidence-ref", action="append")
    release_parser.add_argument("--calibration-metadata-ref")
    release_parser.add_argument("--calibration-model-ref")
    release_parser.add_argument("--adjudication-summary-ref")
    release_parser.set_defaults(func=cmd_release)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
