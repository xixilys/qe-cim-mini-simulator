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

import unified_dse.active_multifidelity as active_multifidelity
import unified_dse.backend_feedback_adapter as backend_feedback_adapter
import unified_dse.adjudication as adjudication
import unified_dse.architecture_space as architecture_space
import unified_dse.constraints as constraints
import unified_dse.stage_b0_descriptors as stage_b0_descriptors
import unified_dse.stage_b3_gem5_smoke as stage_b3_gem5_smoke
import unified_dse.stage_a_contracts as stage_a_contracts
import unified_dse.stage_c_qe_correctness as stage_c_qe_correctness
import unified_dse.stage_d_implementation_evidence as stage_d_implementation_evidence
import unified_dse.stage_status as stage_status
import unified_dse.release_bundle as release_bundle
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
MULTI_FIDELITY_PLAN_NAME = active_multifidelity.DEFAULT_PLAN_NAME
RELEASE_BUNDLE_NAME = release_bundle.RELEASE_BUNDLE_NAME
ADJUDICATION_SUMMARY_NAME = "frontend_adjudication_summary_v0.json"

SOURCE_KINDS = (
    "stub",
    "timed_functional_proxy",
    "trace_calibrated_proxy",
    "mixed",
    "fast_model_screening",
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
    "model_metadata",
    "projection",
    "calibration",
    "calibrated_metrics",
    "calibration_metadata",
    "workload_identity",
    "workload_anchor_refs",
    "domain_extension",
    "design_validation",
    "candidate_descriptor",
    "backend_execution_request",
    "claim_ceiling",
    "non_claims",
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
    "shortlisted_for_backend",
    "shortlist_policy",
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
    parser.add_argument(
        "--backend-report",
        type=Path,
        help=(
            "Optional backend_execution_report_v0 or collection artifact to normalize to "
            "EvidenceIR; the CLI ingests JSON only and does not execute a backend."
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-kind", choices=SOURCE_KINDS, default="stub")
    parser.add_argument(
        "--search-backend",
        choices=search_engine.SEARCH_BACKENDS,
        default="bounded_cartesian",
    )
    parser.add_argument(
        "--shortlist-policy",
        choices=active_multifidelity.SHORTLIST_POLICIES,
        default=active_multifidelity.SHORTLIST_NONE,
    )
    parser.add_argument("--shortlist-size", type=int, default=0)
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
        "--stage-b0-emission-mode",
        choices=stage_b0_descriptors.EMISSION_MODES,
        default=stage_b0_descriptors.EMISSION_ALL_VALID_EXECUTABLE,
    )
    parser.add_argument(
        "--emit-multi-fidelity-plan",
        action="store_true",
        help="Emit multi_fidelity_plan_v0 for scheduler-selected backend handoff.",
    )
    parser.add_argument(
        "--emit-release-bundle",
        action="store_true",
        help="Emit frontend_release_bundle_v0 linking frontend artifacts and evidence refs.",
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


def _row_candidate_id(row: Mapping[str, Any]) -> str | None:
    for key in ("systemc_feedback_contract", "candidate_descriptor"):
        value = row.get(key)
        if isinstance(value, Mapping) and value.get("candidate_id"):
            return str(value["candidate_id"])
    if row.get("candidate_id"):
        return str(row["candidate_id"])
    return None


def _row_workload_id(row: Mapping[str, Any]) -> str | None:
    workload = row.get("workload")
    if isinstance(workload, Mapping) and workload.get("workload_id"):
        return str(workload["workload_id"])
    descriptor = row.get("candidate_descriptor")
    if isinstance(descriptor, Mapping):
        workload_identity = descriptor.get("workload_identity")
        if isinstance(workload_identity, Mapping) and workload_identity.get("workload_id"):
            return str(workload_identity["workload_id"])
    return None


def _row_case_id(row: Mapping[str, Any]) -> str | None:
    qe_anchor_refs = row.get("qe_anchor_refs")
    if isinstance(qe_anchor_refs, Mapping) and qe_anchor_refs.get("case_id"):
        return str(qe_anchor_refs["case_id"])
    descriptor = row.get("candidate_descriptor")
    if isinstance(descriptor, Mapping):
        domain_extension = descriptor.get("domain_extension")
        if isinstance(domain_extension, Mapping):
            qe_extension = domain_extension.get("qe")
            if isinstance(qe_extension, Mapping) and qe_extension.get("case_id"):
                return str(qe_extension["case_id"])
    return _row_workload_id(row)


def _known_result_rows(results: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    known: dict[str, Mapping[str, Any]] = {}
    for row in results:
        candidate_id = _row_candidate_id(row)
        if candidate_id:
            if candidate_id in known:
                raise ValueError(f"duplicate evaluated candidate ID: {candidate_id}")
            known[candidate_id] = row
    return known


def _selected_candidate_ids(multi_fidelity_plan: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(multi_fidelity_plan, Mapping):
        return set()
    selected = multi_fidelity_plan.get("selected_candidates")
    if not isinstance(selected, list):
        return set()
    return {
        str(item["candidate_id"])
        for item in selected
        if isinstance(item, Mapping) and item.get("candidate_id")
    }


def _validate_selected_candidate_context(
    *,
    results: Sequence[Mapping[str, Any]],
    candidate_id: str,
    artifact_label: str,
    multi_fidelity_plan: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    known = _known_result_rows(results)
    if candidate_id not in known:
        raise ValueError(f"{artifact_label} targets unknown evaluated candidate: {candidate_id}")
    selected_ids = _selected_candidate_ids(multi_fidelity_plan)
    if selected_ids and candidate_id not in selected_ids:
        raise ValueError(f"{artifact_label} targets unselected candidate: {candidate_id}")
    return known[candidate_id]


def _validate_qe_correctness_join(
    *,
    results: Sequence[Mapping[str, Any]],
    qe_correctness_report: Mapping[str, Any],
    multi_fidelity_plan: Mapping[str, Any] | None = None,
) -> None:
    candidate_id = str(qe_correctness_report.get("candidate_id"))
    row = _validate_selected_candidate_context(
        results=results,
        candidate_id=candidate_id,
        artifact_label="QE correctness report",
        multi_fidelity_plan=multi_fidelity_plan,
    )
    workload_id = str(qe_correctness_report.get("workload_id"))
    case_id = str(qe_correctness_report.get("case_id"))
    row_workload_id = _row_workload_id(row)
    row_case_id = _row_case_id(row)
    if workload_id != row_workload_id:
        raise ValueError(
            "QE correctness report workload_id does not match evaluated row: "
            f"{workload_id!r} != {row_workload_id!r}"
        )
    if case_id != row_case_id:
        raise ValueError(
            "QE correctness report case_id does not match evaluated row: "
            f"{case_id!r} != {row_case_id!r}"
        )


def _same_ref(left: Any, right: Path | None) -> bool:
    if right is None:
        return left in (None, "")
    if not isinstance(left, str) or not left:
        return False
    left_path = Path(left).expanduser()
    right_path = right.expanduser()
    try:
        return left_path.resolve(strict=False) == right_path.resolve(strict=False)
    except OSError:
        return str(left_path) == str(right_path)


def _validate_implementation_evidence_join(
    *,
    results: Sequence[Mapping[str, Any]],
    implementation_evidence: Mapping[str, Any],
    qe_correctness_report: Mapping[str, Any] | None = None,
    qe_correctness_report_ref: Path | None = None,
    multi_fidelity_plan: Mapping[str, Any] | None = None,
) -> None:
    candidate_id = str(implementation_evidence.get("candidate_id"))
    _validate_selected_candidate_context(
        results=results,
        candidate_id=candidate_id,
        artifact_label="implementation evidence",
        multi_fidelity_plan=multi_fidelity_plan,
    )
    correctness_dependency = implementation_evidence.get("correctness_dependency")
    if not isinstance(correctness_dependency, Mapping):
        raise ValueError("implementation evidence correctness_dependency must be a mapping")
    dependency_claim = correctness_dependency.get("qe_equivalent_scf_claim") is True
    dependency_ref = correctness_dependency.get("qe_correctness_report_ref")
    if qe_correctness_report is None:
        if dependency_claim:
            raise ValueError("implementation evidence cannot claim QE dependency without Stage C report")
        if dependency_ref not in (None, ""):
            raise ValueError("implementation evidence references Stage C report that was not provided")
        return

    stage_c_candidate_id = str(qe_correctness_report.get("candidate_id"))
    if candidate_id != stage_c_candidate_id:
        raise ValueError(
            "implementation evidence candidate_id does not match QE correctness report: "
            f"{candidate_id!r} != {stage_c_candidate_id!r}"
        )
    stage_c_claim = qe_correctness_report.get("qe_equivalent_scf_claim") is True
    if dependency_claim and not stage_c_claim:
        raise ValueError("implementation evidence claims QE dependency but Stage C report did not pass")
    if dependency_ref not in (None, "") and not _same_ref(dependency_ref, qe_correctness_report_ref):
        raise ValueError("implementation evidence QE correctness report ref does not match selected Stage C report")


def _generate_design_points_with_metadata(
    spec: architecture_space.DesignSpaceSpec,
    max_design_points: int,
    search_backend: str,
) -> tuple[list[Any], dict[str, Any]]:
    if max_design_points < 0:
        raise ValueError("--max-design-points must be non-negative")

    search_result = search_engine.search_candidates(
        spec.design_axes,
        max_design_points,
        backend=search_backend,
    )
    if not search_result.metadata.get("available", True):
        raise ValueError(
            f"search backend {search_backend} unavailable: "
            f"{search_result.metadata.get('skipped_reason')}"
        )
    design_points = []
    for candidate in search_result.candidates:
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
    return design_points, dict(search_result.metadata)


def _generate_design_points(
    spec: architecture_space.DesignSpaceSpec,
    max_design_points: int,
    search_backend: str,
) -> list[Any]:
    return _generate_design_points_with_metadata(
        spec, max_design_points, search_backend
    )[0]


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
    search_backend: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    backend = FastModelBackend(source_kind=source_kind)
    rows = []
    design_points, search_metadata = _generate_design_points_with_metadata(
        spec, max_design_points, search_backend
    )
    for design_point in design_points:
        row = backend.evaluate(workload, design_point).to_dict()
        row["projection"] = _projection_payload(spec, design_point.family)
        row["design_validation"] = constraints.validate_design_point(
            design_point,
            workload,
            backend_capability={"target_resource_model": True},
            design_space_spec=spec,
        )
        if (
            source_kind == "fast_model_screening"
            and row["design_validation"]["validity_class"] == "valid_executable"
        ):
            row["projection"]["ranking_grade_ready"] = result_analysis.metrics_are_ranking_grade(
                row.get("metrics", {})
            )
        if calibration_feedback is not None:
            row = calibration_engine.apply_calibration_feedback(row, calibration_feedback)
        row = stage_a_contracts.attach_stage_a_contracts(row)
        rows.append(row)
    return result_analysis.summarize_results(rows)["rows"], search_metadata


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
    search_backend: str,
    results: Sequence[Mapping[str, Any]],
    search_metadata: Mapping[str, Any] | None = None,
    multi_fidelity_plan_ref: str | None = None,
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
            "search_backend": search_backend,
        },
        "search_metadata": dict(search_metadata or {}),
        "multi_fidelity_plan_ref": multi_fidelity_plan_ref,
        "results": list(results),
    }


def _manifest(
    result_count: int,
    promotion_state_counts: Mapping[str, int],
    results: Sequence[Mapping[str, Any]],
    stage_b0_descriptor_manifest: Mapping[str, Any] | None = None,
    systemc_feedback_ref: str | None = None,
    systemc_feedback_summary: Mapping[str, Any] | None = None,
    backend_report_ref: str | None = None,
    evidence_count: int = 0,
    search_metadata: Mapping[str, Any] | None = None,
    multi_fidelity_plan: Mapping[str, Any] | None = None,
    release_bundle_ref: str | None = None,
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
        "search_metadata": dict(search_metadata or {}),
        "multi_fidelity_plan_status": (
            "generated_not_executed" if multi_fidelity_plan is not None else "not_requested"
        ),
        "multi_fidelity_plan_ref": (
            MULTI_FIDELITY_PLAN_NAME if multi_fidelity_plan is not None else None
        ),
        "multi_fidelity_selected_count": int(
            (multi_fidelity_plan or {}).get("selected_count", 0)
        ) if isinstance(multi_fidelity_plan, Mapping) else 0,
        "backend_report_ingest_status": (
            "evidence_ir_normalized" if backend_report_ref is not None else "not_requested"
        ),
        "backend_report_ref": backend_report_ref,
        "evidence_ir_count": evidence_count,
        "release_bundle_ref": release_bundle_ref,
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
        feedback_summary = dict(systemc_feedback_summary or {})
        feedback_status = str(
            feedback_summary.get(
                "systemc_feedback_ingest_status",
                "artifact_ingested_not_executed_by_cli",
            )
        )
        manifest.update(
            {
                "systemc_feedback_ingest_status": feedback_status,
                "systemc_feedback_ref": systemc_feedback_ref,
                "systemc_feedback_candidate_count": int(
                    feedback_summary.get("systemc_feedback_candidate_count", 0)
                ),
                "systemc_feedback_matched_candidate_count": int(
                    feedback_summary.get("systemc_feedback_matched_candidate_count", 0)
                ),
                "systemc_feedback_unmatched_candidate_ids": list(
                    feedback_summary.get("systemc_feedback_unmatched_candidate_ids", [])
                ),
                "systemc_feedback_rejected_candidate_ids": list(
                    feedback_summary.get("systemc_feedback_rejected_candidate_ids", [])
                ),
                "stage_b1_b2_claim_ceiling": (
                    "timed_functional_proxy_feedback_only"
                    if feedback_status == "artifact_ingested_not_executed_by_cli"
                    else "not_applicable"
                ),
            }
        )
    else:
        manifest.update(
            {
                "systemc_feedback_ingest_status": "not_requested",
                "systemc_feedback_ref": None,
                "systemc_feedback_candidate_count": 0,
                "systemc_feedback_matched_candidate_count": 0,
                "systemc_feedback_unmatched_candidate_ids": [],
                "systemc_feedback_rejected_candidate_ids": [],
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
    if value == {}:
        return True
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
        and row.get("ranking_claim_ceiling") in result_analysis.RANKING_CLAIM_CEILINGS
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
            "generic_frontend_contracts_present": False,
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
        "generic_frontend_contracts_present": all(
            isinstance(row.get("candidate_descriptor"), Mapping)
            and row["candidate_descriptor"].get("schema_version") == "candidate_descriptor_v0"
            and isinstance(row.get("backend_execution_request"), Mapping)
            and row["backend_execution_request"].get("schema_version")
            == "backend_execution_request_v0"
            and isinstance(row.get("workload_anchor_refs"), Mapping)
            and row["workload_anchor_refs"].get("schema_version") == "workload_anchor_refs_v0"
            for row in rows
        ),
        "ranking_semantics_present": all(_valid_ranking_semantics(row) for row in rows),
        "claim_boundary_present": all(
            row.get("authority_scope") == "supporting_evidence_only"
            and row.get("final_public_family_winner") is None
            and row.get("ranking_claim_ceiling") in result_analysis.RANKING_CLAIM_CEILINGS
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
        "model_metadata": row.get("model_metadata", {}),
        "projection": row.get("projection", {}),
        "calibration": row.get("calibration", {}),
        "calibrated_metrics": row.get("calibrated_metrics", {}),
        "calibration_metadata": row.get("calibration_metadata", {}),
        "workload_identity": row.get("workload_identity", {}),
        "workload_anchor_refs": row.get("workload_anchor_refs", {}),
        "domain_extension": row.get("domain_extension", {}),
        "design_validation": row.get("design_validation", {}),
        "candidate_descriptor": row.get("candidate_descriptor", {}),
        "backend_execution_request": row.get("backend_execution_request", {}),
        "claim_ceiling": row.get("claim_ceiling"),
        "non_claims": row.get("non_claims", []),
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
        "shortlisted_for_backend": row.get("shortlisted_for_backend"),
        "shortlist_policy": row.get("shortlist_policy"),
        "final_public_family_winner": row.get("final_public_family_winner"),
    }
    for key in CSV_COLUMNS:
        if key in workload:
            flat[key] = workload[key]
        if key in design_point:
            flat[key] = design_point[key]
    return {key: _csv_value(flat.get(key)) for key in CSV_COLUMNS}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    if args.source_kind not in {"stub", "fast_model_screening"}:
        parser.error(
            "this frontend-only CLI supports --source-kind stub or fast_model_screening; "
            "SystemC/gem5 feedback remains external"
        )
    if args.shortlist_size < 0:
        parser.error("--shortlist-size must be non-negative")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    spec = architecture_space.load_design_space_spec(args.design_space_spec)
    workload = workload_frontend.load_workload_descriptor(args.workload)
    calibration_feedback = _load_json_if_provided(args.calibration)
    systemc_feedback = None
    if args.systemc_feedback is not None:
        systemc_feedback = systemc_feedback_adapter.load_systemc_feedback_artifact(args.systemc_feedback)
    backend_report = None
    evidence_rows: list[dict[str, Any]] = []
    if args.backend_report is not None:
        backend_report = backend_feedback_adapter.load_backend_report_artifact(args.backend_report)
        evidence_rows = backend_feedback_adapter.normalize_backend_report_artifact(backend_report)
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

    results, search_metadata = _evaluate_design_points(
        spec=spec,
        workload=workload,
        calibration_feedback=calibration_feedback,
        source_kind=args.source_kind,
        max_design_points=args.max_design_points,
        search_backend=args.search_backend,
    )
    systemc_feedback_summary = None
    if systemc_feedback is not None:
        systemc_feedback_summary = systemc_feedback_adapter.feedback_ingest_summary(
            rows=results,
            feedback=systemc_feedback,
        )
        results = systemc_feedback_adapter.apply_systemc_feedback(
            rows=results,
            feedback=systemc_feedback,
            feedback_ref=str(args.systemc_feedback),
        )
    if evidence_rows:
        results = backend_feedback_adapter.apply_evidence_to_rows(
            rows=results,
            evidence_rows=evidence_rows,
            evidence_ref=str(args.backend_report),
        )
        evidence_dir = args.output_dir / "evidence_ir"
        for evidence in evidence_rows:
            _write_json(evidence_dir / f"{evidence['candidate_id']}.json", evidence)
        calibration_metadata = calibration_engine.fit_residual_calibration(results, evidence_rows)
        _write_json(args.output_dir / "calibration_metadata_v0.json", calibration_metadata)
        calibration_model = calibration_engine.fit_calibration_model(results, evidence_rows)
        _write_json(args.output_dir / "calibration_model_v0.json", calibration_model)
        results = calibration_engine.apply_calibration_metadata_to_rows(results, calibration_metadata)

    summary = result_analysis.summarize_results(results)
    results = summary["rows"]
    results = active_multifidelity.apply_shortlist_policy(
        rows=results,
        policy=args.shortlist_policy,
        shortlist_size=args.shortlist_size,
    )

    multi_fidelity_plan = None
    if args.emit_multi_fidelity_plan or args.stage_b0_emission_mode == stage_b0_descriptors.EMISSION_SCHEDULER_SELECTED_ONLY:
        plan_size = args.shortlist_size if args.shortlist_size > 0 else min(3, len(results))
        plan_policy = args.shortlist_policy
        if plan_policy == active_multifidelity.SHORTLIST_NONE and plan_size > 0:
            plan_policy = active_multifidelity.SHORTLIST_TOP_FAST_UNCERTAIN_DIVERSE
        multi_fidelity_plan = active_multifidelity.build_multi_fidelity_plan(
            rows=results,
            policy=plan_policy,
            shortlist_size=plan_size,
        )
        _write_json(args.output_dir / MULTI_FIDELITY_PLAN_NAME, multi_fidelity_plan)

    if qe_correctness_report is not None:
        _validate_qe_correctness_join(
            results=results,
            qe_correctness_report=qe_correctness_report,
            multi_fidelity_plan=multi_fidelity_plan,
        )
    if implementation_evidence is not None:
        _validate_implementation_evidence_join(
            results=results,
            implementation_evidence=implementation_evidence,
            qe_correctness_report=qe_correctness_report,
            qe_correctness_report_ref=args.qe_correctness_report,
            multi_fidelity_plan=multi_fidelity_plan,
        )

    stage_b0_descriptor_manifest = None
    if args.emit_stage_b0_descriptors:
        stage_b0_descriptor_manifest = stage_b0_descriptors.emit_stage_b0_descriptors(
            output_dir=args.output_dir,
            rows=results,
            emission_mode=args.stage_b0_emission_mode,
            multi_fidelity_plan=multi_fidelity_plan,
        )
    bundle = _result_bundle(
        spec=spec,
        workload_path=args.workload,
        calibration_path=args.calibration,
        source_kind=args.source_kind,
        dry_run=args.dry_run,
        max_design_points=args.max_design_points,
        search_backend=args.search_backend,
        results=results,
        search_metadata=search_metadata,
        multi_fidelity_plan_ref=(
            MULTI_FIDELITY_PLAN_NAME if multi_fidelity_plan is not None else None
        ),
    )
    manifest = _manifest(
        result_count=len(results),
        promotion_state_counts=summary["promotion_state_counts"],
        results=results,
        stage_b0_descriptor_manifest=stage_b0_descriptor_manifest,
        systemc_feedback_ref=str(args.systemc_feedback) if args.systemc_feedback is not None else None,
        systemc_feedback_summary=systemc_feedback_summary,
        backend_report_ref=str(args.backend_report) if args.backend_report is not None else None,
        evidence_count=len(evidence_rows),
        search_metadata=search_metadata,
        multi_fidelity_plan=multi_fidelity_plan,
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
    if args.emit_release_bundle:
        manifest["release_bundle_ref"] = RELEASE_BUNDLE_NAME
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
        adjudication_summary = adjudication.build_adjudication_summary(
            results,
            result_bundle_ref=RESULT_JSON_NAME,
            calibration_model_ref=("calibration_model_v0.json" if evidence_rows else None),
            evidence_refs=[
                str(path)
                for path in (
                    args.backend_report,
                    args.qe_correctness_report,
                    args.implementation_evidence,
                )
                if path is not None
            ],
        )
        _write_json(args.output_dir / ADJUDICATION_SUMMARY_NAME, adjudication_summary)
        release_evidence_refs = []
        if args.backend_report is not None:
            release_evidence_refs.append(str(args.backend_report))
        if args.systemc_feedback is not None:
            release_evidence_refs.append(str(args.systemc_feedback))
        if args.gem5_smoke_report is not None:
            release_evidence_refs.append(str(args.gem5_smoke_report))
        if args.qe_correctness_report is not None:
            release_evidence_refs.append(str(args.qe_correctness_report))
        if args.implementation_evidence is not None:
            release_evidence_refs.append(str(args.implementation_evidence))
        release_bundle.emit_release_bundle(
            args.output_dir,
            stage_status_ref=(FULL_STAGE_STATUS_NAME if args.emit_full_stage_status else None),
            stage_b0_descriptor_manifest_ref=(
                STAGE_B0_DESCRIPTOR_MANIFEST_NAME if stage_b0_descriptor_manifest is not None else None
            ),
            multi_fidelity_plan_ref=(
                MULTI_FIDELITY_PLAN_NAME if multi_fidelity_plan is not None else None
            ),
            evidence_refs=release_evidence_refs,
            calibration_metadata_ref=(
                "calibration_metadata_v0.json" if evidence_rows else None
            ),
            calibration_model_ref=(
                "calibration_model_v0.json" if evidence_rows else None
            ),
            adjudication_summary_ref=ADJUDICATION_SUMMARY_NAME,
        )
    _write_json(args.output_dir / MANIFEST_JSON_NAME, manifest)
    if args.emit_full_stage_status and not args.emit_release_bundle:
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
