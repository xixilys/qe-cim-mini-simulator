from __future__ import annotations

import argparse
import csv
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, cast


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import unified_dse.architecture_space as architecture_space
import unified_dse.workload_frontend as workload_frontend
from unified_dse.fast_model import FastModelBackend

calibration_engine = importlib.import_module("unified_dse.calibration_engine")
result_analysis = importlib.import_module("unified_dse.result_analysis")
search_engine = importlib.import_module("unified_dse.search_engine")


RESULT_JSON_NAME = "unified_dse_results_v0.json"
RESULT_CSV_NAME = "unified_dse_results_v0.csv"
MANIFEST_JSON_NAME = "unified_dse_manifest_v0.json"

SOURCE_KINDS = (
    "stub",
    "timed_functional_proxy",
    "trace_calibrated_proxy",
    "mixed",
)

CSV_COLUMNS = (
    "workload_id",
    "workload_group_id",
    "qe_tolerance_schema_id",
    "accounting_boundary_id",
    "fairness_policy_id",
    "power_boundary_id",
    "observability_contract_id",
    "family",
    "diag_policy",
    "offload_scope",
    "resident_policy",
    "partition_strategy",
    "backend",
    "result_status",
    "source_kind",
    "promotion_state",
    "authority_scope",
    "metrics",
    "projection",
    "calibration",
    "final_public_family_winner",
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Unified DSE v0 Stage-A evidence-only CLI orchestrator."
    )
    parser.add_argument("--design-space-spec", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-kind", choices=SOURCE_KINDS, default="stub")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--execute-systemc",
        action="store_true",
        help="Reserved explicit SystemC execution guard; v0 CLI never invokes SystemC directly.",
    )
    parser.add_argument("--max-design-points", type=int, default=8)
    return parser


def _load_json_if_provided(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _generate_design_points(
    spec: architecture_space.DesignSpaceSpec,
    max_design_points: int,
) -> list[Any]:
    if max_design_points < 0:
        raise ValueError("--max-design-points must be non-negative")

    candidates = search_engine.bounded_cartesian_product(spec.design_axes, max_design_points)
    design_points = []
    for candidate in candidates:
        design_points.append(
            architecture_space.make_design_point(
                spec,
                family=candidate["family"],
                diag_policy=candidate["diag_policy"],
                offload_scope=candidate["offload_scope"],
                resident_policy=candidate["resident_policy"],
                partition_strategy=candidate["partition_strategy"],
            )
        )
    return design_points


def _projection_payload(
    spec: architecture_space.DesignSpaceSpec,
    family: str,
) -> dict[str, Any]:
    support = architecture_space.family_support_status(spec, family)
    return {
        "family_identity": support.family,
        "runtime_support_status": support.runtime_support_status,
        "stage_a_status": support.stage_a_status,
        "runtime_executor_backed": support.runtime_executor_backed,
        "runtime_projection_family": support.runtime_projection_family,
        "ranking_grade_ready": False,
    }


def _evaluate_design_points(
    spec: architecture_space.DesignSpaceSpec,
    workload: Any,
    calibration_feedback: dict[str, Any] | None,
    source_kind: str,
    max_design_points: int,
) -> list[dict[str, Any]]:
    backend = FastModelBackend(source_kind=source_kind)
    rows = []
    for design_point in _generate_design_points(spec, max_design_points):
        row = backend.evaluate(workload, design_point).to_dict()
        row["projection"] = _projection_payload(spec, design_point.family)
        if calibration_feedback is not None:
            row = calibration_engine.apply_calibration_feedback(row, calibration_feedback)
        rows.append(row)
    return result_analysis.summarize_results(rows)["rows"]


def _authority_bundle() -> dict[str, Any]:
    return {
        "claim_posture": "evidence_only",
        "decision_authority": "adjudicator_memo_only",
        "final_public_family_winner": None,
    }


def _result_bundle(
    spec: architecture_space.DesignSpaceSpec,
    workload_path: Path,
    calibration_path: Path | None,
    source_kind: str,
    dry_run: bool,
    max_design_points: int,
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "unified_dse_result_bundle_v0",
        "authority": _authority_bundle(),
        "design_space": {
            "schema_version": spec.schema_version,
            "design_space_id": spec.design_space_id,
        },
        "inputs": {
            "workload": str(workload_path),
            "calibration": str(calibration_path) if calibration_path is not None else None,
            "source_kind": source_kind,
            "dry_run": dry_run,
            "max_design_points": max_design_points,
        },
        "results": list(results),
    }


def _manifest(
    result_count: int,
    promotion_state_counts: Mapping[str, int],
) -> dict[str, Any]:
    counts = {state: int(promotion_state_counts.get(state, 0)) for state in result_analysis.PROMOTION_STATES}
    return {
        "schema_version": "unified_dse_manifest_v0",
        "authority_scope": "supporting_evidence_only",
        "claim_posture": "evidence_only",
        "decision_authority": "adjudicator_memo_only",
        "winner_declared": False,
        "final_public_family_winner": None,
        "result_count": result_count,
        "promotion_state_counts": counts,
    }


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _csv_row(row: Mapping[str, Any]) -> dict[str, str]:
    workload = row.get("workload", {})
    design_point = row.get("design_point", {})
    if not isinstance(workload, Mapping):
        workload = {}
    if not isinstance(design_point, Mapping):
        design_point = {}

    flat: dict[str, Any] = {
        "backend": row.get("backend"),
        "result_status": row.get("result_status"),
        "source_kind": row.get("source_kind"),
        "promotion_state": row.get("promotion_state"),
        "authority_scope": row.get("authority_scope"),
        "metrics": row.get("metrics", {}),
        "projection": row.get("projection", {}),
        "calibration": row.get("calibration", {}),
        "final_public_family_winner": row.get("final_public_family_winner"),
    }
    for key in CSV_COLUMNS:
        if key in workload:
            flat[key] = workload[key]
        if key in design_point:
            flat[key] = design_point[key]
    return {key: _csv_value(flat.get(key)) for key in CSV_COLUMNS}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(cast(Any, _csv_row(row)))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.execute_systemc:
        parser.error(
            "SystemC execution remains via the canonical runner / future explicit adapter; "
            "Unified DSE v0 CLI does not execute SystemC"
        )
    if args.source_kind != "stub":
        parser.error(
            "current Unified DSE v0 CLI only supports --source-kind stub for FastModelBackend "
            "stub/projection rows"
        )

    spec = architecture_space.load_design_space_spec(args.design_space_spec)
    workload = workload_frontend.load_workload_descriptor(args.workload)
    calibration_feedback = _load_json_if_provided(args.calibration)

    results = _evaluate_design_points(
        spec=spec,
        workload=workload,
        calibration_feedback=calibration_feedback,
        source_kind=args.source_kind,
        max_design_points=args.max_design_points,
    )
    summary = result_analysis.summarize_results(results)
    results = summary["rows"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    bundle = _result_bundle(
        spec=spec,
        workload_path=args.workload,
        calibration_path=args.calibration,
        source_kind=args.source_kind,
        dry_run=args.dry_run,
        max_design_points=args.max_design_points,
        results=results,
    )
    manifest = _manifest(
        result_count=len(results),
        promotion_state_counts=summary["promotion_state_counts"],
    )

    _write_json(args.output_dir / RESULT_JSON_NAME, bundle)
    _write_csv(args.output_dir / RESULT_CSV_NAME, results)
    _write_json(args.output_dir / MANIFEST_JSON_NAME, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
