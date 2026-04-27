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
import unified_dse.stage_b0_descriptors as stage_b0_descriptors
import unified_dse.stage_b3_gem5_smoke as stage_b3_gem5_smoke
import unified_dse.stage_a_contracts as stage_a_contracts
import unified_dse.stage_c_qe_correctness as stage_c_qe_correctness
import unified_dse.stage_d_implementation_evidence as stage_d_implementation_evidence
import unified_dse.stage_status as stage_status
import unified_dse.systemc_feedback_adapter as systemc_feedback_adapter
import unified_dse.workload_frontend as workload_frontend
from unified_dse.fast_model import FastModelBackend

calibration_engine = importlib.import_module("unified_dse.calibration_engine")
result_analysis = importlib.import_module("unified_dse.result_analysis")
search_engine = importlib.import_module("unified_dse.search_engine")


RESULT_JSON_NAME = "unified_dse_results_v0.json"
RESULT_CSV_NAME = "unified_dse_results_v0.csv"
MANIFEST_JSON_NAME = "unified_dse_manifest_v0.json"
STAGE_B0_DESCRIPTOR_MANIFEST_NAME = stage_b0_descriptors.DESCRIPTOR_MANIFEST_NAME
FULL_STAGE_STATUS_NAME = stage_status.FULL_STAGE_STATUS_NAME

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
    "backend_neutral_schema",
    "systemc_feedback_contract",
    "systemc_feedback_contract_status",
    "systemc_feedback_execution_status",
    "systemc_feedback_claim_ceiling",
    "gem5_handoff_contract",
    "gem5_handoff_contract_status",
    "gem5_handoff_status",
    "gem5_handoff_execution_status",
    "gem5_handoff_platform_status",
    "gem5_handoff_claim_ceiling",
    "qe_anchor_refs",
    "qe_anchor_status",
    "qe_equivalent_scf_claim",
    "screening_rank",
    "pareto_membership",
    "shortlist_reason",
    "ranking_claim_ceiling",
    "final_public_family_winner",
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Unified DSE v0 Stage-A evidence-only CLI orchestrator."
    )
    parser.add_argument("--design-space-spec", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument(
        "--systemc-feedback",
        type=Path,
        help=(
            "Optional Stage B1/B2 SystemC feedback artifact to ingest into DSE rows; "
            "the CLI reads the artifact but does not execute SystemC."
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-kind", choices=SOURCE_KINDS, default="stub")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--execute-systemc",
        action="store_true",
        help="Reserved explicit SystemC execution guard; v0 CLI never invokes SystemC directly.",
    )
    parser.add_argument("--max-design-points", type=int, default=8)
    parser.add_argument(
        "--emit-stage-b0-descriptors",
        action="store_true",
        help=(
            "Emit descriptor-only SystemC config and gem5 handoff sidecars for Stage B0; "
            "does not execute SystemC or gem5."
        ),
    )
    parser.add_argument(
        "--emit-full-stage-status",
        action="store_true",
        help=(
            "Emit a claim-safe A/B/C/D stage status artifact. Later stages without "
            "external evidence are reported as blocked, not completed."
        ),
    )
    parser.add_argument("--gem5-smoke-report", type=Path)
    parser.add_argument("--qe-correctness-report", type=Path)
    parser.add_argument("--implementation-evidence", type=Path)
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
        row = stage_a_contracts.attach_stage_a_contracts(row)
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
    results: Sequence[Mapping[str, Any]],
    stage_b0_descriptor_manifest: Mapping[str, Any] | None = None,
    systemc_feedback_ref: str | None = None,
    gem5_smoke_report_ref: str | None = None,
    qe_correctness_report_ref: str | None = None,
    qe_correctness_summary: Mapping[str, Any] | None = None,
    implementation_evidence_ref: str | None = None,
    implementation_evidence_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    counts = {state: int(promotion_state_counts.get(state, 0)) for state in result_analysis.PROMOTION_STATES}
    gates = _stage_a_gates(results)
    manifest = {
        "schema_version": "unified_dse_manifest_v0",
        "authority_scope": "supporting_evidence_only",
        "claim_posture": "evidence_only",
        "claim_boundary": "stage_a_evidence_only_no_final_public_winner",
        "decision_authority": "adjudicator_memo_only",
        "winner_declared": False,
        "final_public_family_winner": None,
        "result_count": result_count,
        "promotion_state_counts": counts,
        **gates,
        "stage_a_gate_blockers": {
            key: "missing_or_incomplete_stage_a_contract_field"
            for key, value in gates.items()
            if not value
        },
    }
    if stage_b0_descriptor_manifest is not None:
        manifest.update(
            {
                "stage_b0_descriptor_generation_status": "generated_not_executed",
                "stage_b0_descriptor_count": int(
                    stage_b0_descriptor_manifest.get("descriptor_count", 0)
                ),
                "stage_b0_descriptor_manifest_ref": STAGE_B0_DESCRIPTOR_MANIFEST_NAME,
                "stage_b0_claim_ceiling": "descriptor_generation_only",
            }
        )
    else:
        manifest.update(
            {
                "stage_b0_descriptor_generation_status": "not_requested",
                "stage_b0_descriptor_count": 0,
                "stage_b0_descriptor_manifest_ref": None,
                "stage_b0_claim_ceiling": "not_applicable",
            }
        )
    if systemc_feedback_ref is not None:
        manifest.update(
            {
                "systemc_feedback_ingest_status": "artifact_ingested_not_executed_by_cli",
                "systemc_feedback_ref": systemc_feedback_ref,
                "stage_b1_b2_claim_ceiling": "timed_functional_proxy_feedback_only",
            }
        )
    else:
        manifest.update(
            {
                "systemc_feedback_ingest_status": "not_requested",
                "systemc_feedback_ref": None,
                "stage_b1_b2_claim_ceiling": "not_applicable",
            }
        )
    if gem5_smoke_report_ref is not None:
        manifest.update(
            {
                "gem5_smoke_report_status": "external_smoke_report_validated_not_executed_by_cli",
                "gem5_smoke_report_ref": gem5_smoke_report_ref,
                "stage_b3_claim_ceiling": "gem5_systemc_smoke_only",
            }
        )
    else:
        manifest.update(
            {
                "gem5_smoke_report_status": "not_requested",
                "gem5_smoke_report_ref": None,
                "stage_b3_claim_ceiling": "not_applicable",
            }
        )
    if qe_correctness_report_ref is not None and qe_correctness_summary is not None:
        qe_claim = qe_correctness_summary.get("qe_equivalent_scf_claim") is True
        manifest.update(
            {
                "qe_correctness_report_status": (
                    "external_qe_equivalent_correctness_pass_referenced"
                    if qe_claim
                    else "external_correctness_report_referenced_not_proven"
                ),
                "qe_correctness_report_ref": qe_correctness_report_ref,
                "stage_c_qe_equivalent_scf_claim": qe_claim,
                "stage_c_claim_ceiling": qe_correctness_summary.get("claim_ceiling"),
            }
        )
    else:
        manifest.update(
            {
                "qe_correctness_report_status": "not_requested",
                "qe_correctness_report_ref": None,
                "stage_c_qe_equivalent_scf_claim": False,
                "stage_c_claim_ceiling": "not_applicable",
            }
        )
    if implementation_evidence_ref is not None and implementation_evidence_summary is not None:
        manifest.update(
            {
                "implementation_evidence_status": "external_implementation_evidence_validated",
                "implementation_evidence_ref": implementation_evidence_ref,
                "stage_d_implementation_target_class": implementation_evidence_summary.get(
                    "implementation_target_class"
                ),
                "stage_d_evidence_kind": implementation_evidence_summary.get("evidence_kind"),
                "stage_d_claim_ceiling": implementation_evidence_summary.get("claim_ceiling"),
            }
        )
    else:
        manifest.update(
            {
                "implementation_evidence_status": "not_requested",
                "implementation_evidence_ref": None,
                "stage_d_implementation_target_class": None,
                "stage_d_evidence_kind": None,
                "stage_d_claim_ceiling": "not_applicable",
            }
        )
    return manifest


def _has_keys(value: Any, keys: Sequence[str]) -> bool:
    return isinstance(value, Mapping) and all(key in value for key in keys)


def _valid_backend_neutral_schema(value: Any) -> bool:
    if not _has_keys(
        value,
        (
            "schema_version",
            "architecture_family",
            "implementation_backend",
            "source_kind",
            "supported_target_classes",
            "cim_lockin",
            "claim_ceiling",
        ),
    ):
        return False
    assert isinstance(value, Mapping)
    return (
        value["schema_version"] == stage_a_contracts.BACKEND_NEUTRAL_SCHEMA_VERSION
        and value["cim_lockin"] is False
        and value["claim_ceiling"] == "backend_identity_and_stage_a_contract_only"
        and value["supported_target_classes"] == ["fpga", "asic"]
        and value["implementation_backend"] in {"fast_model", "systemc", "implementation"}
        and value["source_kind"] in SOURCE_KINDS
    )


def _valid_systemc_feedback(value: Any) -> bool:
    if not _has_keys(
        value,
        (
            "schema_version",
            "status",
            "execution_status",
            "backend_class",
            "candidate_config_ref",
            "metrics_ref",
            "metrics_expected_keys",
            "calibration_join_keys",
            "calibration_status",
            "claim_ceiling",
            "subprocess_invoked",
            "implementation_target_class",
            "backend_profile_id",
            "design_axes",
        ),
    ):
        return False
    assert isinstance(value, Mapping)
    return (
        value["schema_version"] == stage_a_contracts.SYSTEMC_FEEDBACK_CONTRACT_VERSION
        and value["status"] in {"planned_not_executed", "feedback_artifact_ingested"}
        and value["execution_status"] in {"not_executed", "executed"}
        and value["backend_class"] == "systemc_timed_functional_proxy"
        and value["claim_ceiling"] == "timed_functional_proxy_contract_only"
        and isinstance(value["subprocess_invoked"], bool)
        and isinstance(value["metrics_expected_keys"], list)
        and isinstance(value["calibration_join_keys"], list)
        and isinstance(value["design_axes"], Mapping)
    )


def _valid_gem5_handoff(value: Any) -> bool:
    if not _has_keys(
        value,
        (
            "schema_version",
            "status",
            "handoff_status",
            "execution_status",
            "platform_status",
            "input_descriptor_ref",
            "expected_command",
            "expected_report_ref",
            "output_report_expected_keys",
            "claim_ceiling",
        ),
    ):
        return False
    assert isinstance(value, Mapping)
    return (
        value["schema_version"] == stage_a_contracts.GEM5_SYSTEMC_HANDOFF_CONTRACT_VERSION
        and value["status"] == "planned_for_stage_b"
        and value["handoff_status"] == "planned"
        and value["execution_status"] == "not_executed"
        and value["platform_status"] == "requires_linux_x86_validation"
        and value["claim_ceiling"] == "stage_b_handoff_contract_only"
        and isinstance(value["output_report_expected_keys"], list)
    )


def _valid_qe_anchor_refs(value: Any) -> bool:
    if not _has_keys(
        value,
        (
            "schema_version",
            "status",
            "workload_id",
            "case_id",
            "trace_ref",
            "dump_ref",
            "correctness_anchor_ref",
            "anchor_evidence_kind",
            "qe_equivalent_scf_claim",
            "claim_ceiling",
        ),
    ):
        return False
    assert isinstance(value, Mapping)
    return (
        value["schema_version"] == stage_a_contracts.QE_ANCHOR_REFS_VERSION
        and value["status"] == "trace_or_correctness_anchor_only"
        and value["anchor_evidence_kind"]
        in {
            "missing_or_trace_only",
            "trace_only",
            "correctness_capable_anchor",
            "measured_reference",
        }
        and value["qe_equivalent_scf_claim"] is False
        and value["claim_ceiling"] == "anchor_reference_only"
    )


def _valid_ranking_semantics(row: Mapping[str, Any]) -> bool:
    return (
        "screening_rank" in row
        and row.get("pareto_membership") in {"not_evaluated", "screening_candidate"}
        and isinstance(row.get("shortlist_reason"), str)
        and row.get("ranking_claim_ceiling") == result_analysis.RANKING_CLAIM_CEILING
        and row.get("final_public_family_winner") is None
    )


def _stage_a_gates(results: Sequence[Mapping[str, Any]]) -> dict[str, bool]:
    rows = list(results)
    if not rows:
        return {
            "backend_neutral_schema_present": False,
            "systemc_feedback_contract_present": False,
            "gem5_handoff_contract_present": False,
            "qe_anchor_refs_present": False,
            "ranking_semantics_present": False,
            "claim_boundary_present": False,
        }
    return {
        "backend_neutral_schema_present": all(
            _valid_backend_neutral_schema(row.get("backend_neutral_schema")) for row in rows
        ),
        "systemc_feedback_contract_present": all(
            _valid_systemc_feedback(row.get("systemc_feedback_contract")) for row in rows
        ),
        "gem5_handoff_contract_present": all(
            _valid_gem5_handoff(row.get("gem5_handoff_contract")) for row in rows
        ),
        "qe_anchor_refs_present": all(_valid_qe_anchor_refs(row.get("qe_anchor_refs")) for row in rows),
        "ranking_semantics_present": all(_valid_ranking_semantics(row) for row in rows),
        "claim_boundary_present": all(
            row.get("authority_scope") == "supporting_evidence_only"
            and row.get("final_public_family_winner") is None
            and row.get("ranking_claim_ceiling") == result_analysis.RANKING_CLAIM_CEILING
            for row in rows
        ),
    }


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return json.dumps(value)
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
    systemc_feedback = row.get("systemc_feedback_contract", {})
    gem5_handoff = row.get("gem5_handoff_contract", {})
    qe_anchor_refs = row.get("qe_anchor_refs", {})
    if not isinstance(systemc_feedback, Mapping):
        systemc_feedback = {}
    if not isinstance(gem5_handoff, Mapping):
        gem5_handoff = {}
    if not isinstance(qe_anchor_refs, Mapping):
        qe_anchor_refs = {}

    flat: dict[str, Any] = {
        "backend": row.get("backend"),
        "result_status": row.get("result_status"),
        "source_kind": row.get("source_kind"),
        "promotion_state": row.get("promotion_state"),
        "authority_scope": row.get("authority_scope"),
        "metrics": row.get("metrics", {}),
        "projection": row.get("projection", {}),
        "calibration": row.get("calibration", {}),
        "backend_neutral_schema": row.get("backend_neutral_schema", {}),
        "systemc_feedback_contract": row.get("systemc_feedback_contract", {}),
        "systemc_feedback_contract_status": systemc_feedback.get("status"),
        "systemc_feedback_execution_status": systemc_feedback.get("execution_status"),
        "systemc_feedback_claim_ceiling": systemc_feedback.get("claim_ceiling"),
        "gem5_handoff_contract": row.get("gem5_handoff_contract", {}),
        "gem5_handoff_contract_status": gem5_handoff.get("status"),
        "gem5_handoff_status": gem5_handoff.get("handoff_status"),
        "gem5_handoff_execution_status": gem5_handoff.get("execution_status"),
        "gem5_handoff_platform_status": gem5_handoff.get("platform_status"),
        "gem5_handoff_claim_ceiling": gem5_handoff.get("claim_ceiling"),
        "qe_anchor_refs": row.get("qe_anchor_refs", {}),
        "qe_anchor_status": qe_anchor_refs.get("status"),
        "qe_equivalent_scf_claim": qe_anchor_refs.get("qe_equivalent_scf_claim"),
        "screening_rank": row.get("screening_rank"),
        "pareto_membership": row.get("pareto_membership"),
        "shortlist_reason": row.get("shortlist_reason"),
        "ranking_claim_ceiling": row.get("ranking_claim_ceiling"),
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
    systemc_feedback = None
    if args.systemc_feedback is not None:
        systemc_feedback = systemc_feedback_adapter.load_systemc_feedback_artifact(args.systemc_feedback)
    gem5_smoke_report = None
    if args.gem5_smoke_report is not None:
        gem5_smoke_report = stage_b3_gem5_smoke.load_and_validate_gem5_smoke_report(
            args.gem5_smoke_report
        )
    qe_correctness_report = None
    qe_correctness_summary = None
    if args.qe_correctness_report is not None:
        qe_correctness_report = stage_c_qe_correctness.load_and_validate_qe_correctness_report(
            args.qe_correctness_report
        )
        qe_correctness_summary = stage_c_qe_correctness.summarize_qe_correctness_report(
            qe_correctness_report
        )
    implementation_evidence = None
    implementation_evidence_summary = None
    if args.implementation_evidence is not None:
        implementation_evidence = (
            stage_d_implementation_evidence.load_and_validate_implementation_evidence(
                args.implementation_evidence
            )
        )
        implementation_evidence_summary = (
            stage_d_implementation_evidence.summarize_implementation_evidence(
                implementation_evidence
            )
        )

    results = _evaluate_design_points(
        spec=spec,
        workload=workload,
        calibration_feedback=calibration_feedback,
        source_kind=args.source_kind,
        max_design_points=args.max_design_points,
    )
    if systemc_feedback is not None:
        results = systemc_feedback_adapter.apply_systemc_feedback(
            rows=results,
            feedback=systemc_feedback,
            feedback_ref=str(args.systemc_feedback),
        )
    summary = result_analysis.summarize_results(results)
    results = summary["rows"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stage_b0_descriptor_manifest = None
    if args.emit_stage_b0_descriptors:
        stage_b0_descriptor_manifest = stage_b0_descriptors.emit_stage_b0_descriptors(
            output_dir=args.output_dir,
            rows=results,
        )
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
        results=results,
        stage_b0_descriptor_manifest=stage_b0_descriptor_manifest,
        systemc_feedback_ref=str(args.systemc_feedback) if args.systemc_feedback is not None else None,
        gem5_smoke_report_ref=str(args.gem5_smoke_report) if gem5_smoke_report is not None else None,
        qe_correctness_report_ref=(
            str(args.qe_correctness_report) if qe_correctness_report is not None else None
        ),
        qe_correctness_summary=qe_correctness_summary,
        implementation_evidence_ref=(
            str(args.implementation_evidence) if implementation_evidence is not None else None
        ),
        implementation_evidence_summary=implementation_evidence_summary,
    )

    _write_json(args.output_dir / RESULT_JSON_NAME, bundle)
    _write_csv(args.output_dir / RESULT_CSV_NAME, results)
    _write_json(args.output_dir / MANIFEST_JSON_NAME, manifest)
    if args.emit_full_stage_status:
        stage_status.emit_full_stage_status(
            output_dir=args.output_dir,
            manifest=manifest,
            stage_b0_descriptor_manifest_ref=(
                STAGE_B0_DESCRIPTOR_MANIFEST_NAME if stage_b0_descriptor_manifest is not None else None
            ),
            systemc_feedback_ref=str(args.systemc_feedback) if args.systemc_feedback is not None else None,
            gem5_smoke_report_ref=str(args.gem5_smoke_report) if args.gem5_smoke_report else None,
            qe_correctness_report_ref=(
                str(args.qe_correctness_report) if args.qe_correctness_report else None
            ),
            qe_correctness_summary=qe_correctness_summary,
            implementation_evidence_ref=(
                str(args.implementation_evidence) if args.implementation_evidence else None
            ),
            implementation_evidence_summary=implementation_evidence_summary,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
