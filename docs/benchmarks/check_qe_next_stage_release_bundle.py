#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def top_level_keys(payload: dict[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - set(payload))
    require(not missing, f"{label} missing required keys: {', '.join(missing)}")


def validate_component_registry_summary(payload: dict[str, Any], label: str) -> None:
    top_level_keys(
        payload,
        {
            "schema_version",
            "catalog_version",
            "seed_template_version",
            "all_strict_checks_pass",
            "component_count",
            "active_build_source_count",
            "strict_backbone_component_count",
            "future_catalog_expansion_candidate_count",
            "intentional_unmapped_active_source_count",
            "shared_anchor_count",
            "active_source_gap_categories",
        },
        label,
    )
    require(payload["schema_version"] == "qe_ic_component_registry_v0", f"{label} schema_version drifted")
    require(payload["all_strict_checks_pass"] is True, f"{label} all_strict_checks_pass must be true")


def validate_gpu_annex_summary(payload: dict[str, Any], label: str) -> None:
    top_level_keys(
        payload,
        {
            "schema_version",
            "status",
            "reason",
            "source_surface",
            "baseline_dir_count",
            "counts",
            "gpu_mode_set_measured",
            "gpu_decisive_modes",
            "decisive_case_ids",
            "row_ledger",
            "case_decision_sheet",
            "workload_group_gpu_column_manifest",
            "artifact_paths",
            "annex_note",
        },
        label,
    )
    require(payload["schema_version"] == "qe_gpu_annex_summary_v0", f"{label} schema_version drifted")
    counts = payload["counts"]
    top_level_keys(
        counts,
        {"thesis_eligible", "reference_only", "deferred", "decisive"},
        f"{label}.counts",
    )
    rows = payload["row_ledger"]
    require(payload["baseline_dir_count"] == len(rows), f"{label} baseline_dir_count drifted")
    decisive_rows = [row for row in rows if row.get("decisive_for_case") is True]
    require(
        counts["decisive"] == len(decisive_rows),
        f"{label}.counts.decisive drifted vs row_ledger",
    )
    measured_modes = sorted(
        {
            str(row["gpu_mode"])
            for row in rows
            if row.get("gpu_mode") not in (None, "")
        }
    )
    decisive_modes = sorted(
        {
            str(row["gpu_mode"])
            for row in decisive_rows
            if row.get("gpu_mode") not in (None, "")
        }
    )
    decisive_case_ids = sorted(
        {
            str(row["case_id"])
            for row in decisive_rows
            if row.get("case_id") not in (None, "")
        }
    )
    require(
        payload["gpu_mode_set_measured"] == measured_modes,
        f"{label}.gpu_mode_set_measured drifted",
    )
    require(
        payload["gpu_decisive_modes"] == decisive_modes,
        f"{label}.gpu_decisive_modes drifted",
    )
    require(
        payload["decisive_case_ids"] == decisive_case_ids,
        f"{label}.decisive_case_ids drifted",
    )
    if payload["status"] == "reference_only":
        require(counts["decisive"] == 0, f"{label} reference_only annex cannot contain decisive rows")
    if payload["reason"] == "reference_gpu_directory_materialized":
        require(
            payload["source_surface"] == "gpu_reference_bundle_readiness",
            f"{label} materialized reference GPU annex must come from gpu_reference_bundle_readiness",
        )
        require(
            payload["status"] == "reference_only",
            f"{label} materialized reference GPU annex must remain reference_only",
        )
        generated_dirs = payload.get("generated_bundle_dirs") or []
        require(
            len(generated_dirs) == payload["baseline_dir_count"],
            f"{label}.generated_bundle_dirs drifted vs baseline_dir_count",
        )
        for idx, bundle_dir in enumerate(generated_dirs):
            require(Path(bundle_dir).exists(), f"{label}.generated_bundle_dirs[{idx}] missing")
    if payload["reason"] == "no_gpu_baseline_dirs_configured":
        require(payload["baseline_dir_count"] == 0, f"{label} no_gpu_baseline_dirs_configured must have zero rows")
    reference_paths = payload.get("reference_artifact_paths")
    if reference_paths is not None:
        top_level_keys(
            reference_paths,
            {"qe_timing_json", "app_out", "cuda_gpu_kernel_summary_csv"},
            f"{label}.reference_artifact_paths",
        )
        for key, path in reference_paths.items():
            require(Path(path).exists(), f"{label}.reference_artifact_paths.{key} missing")
    artifact_paths = payload["artifact_paths"]
    top_level_keys(
        artifact_paths,
        {
            "gpu_annex_json",
            "gpu_annex_md",
            "case_decision_sheet_json",
            "case_decision_sheet_md",
            "workload_group_gpu_column_manifest_json",
            "workload_group_gpu_column_manifest_md",
        },
        f"{label}.artifact_paths",
    )
    for idx, row in enumerate(rows):
        top_level_keys(
            row,
            {"baseline_dir", "case_id", "gpu_mode", "status", "reason"},
            f"{label}.row_ledger[{idx}]",
        )
        require(
            Path(row["baseline_dir"]).exists(),
            f"{label}.row_ledger[{idx}].baseline_dir missing",
        )
        manifest_path = row.get("manifest_path")
        if manifest_path is not None:
            require(
                Path(manifest_path).exists(),
                f"{label}.row_ledger[{idx}].manifest_path missing",
            )
    case_sheet = payload["case_decision_sheet"]
    top_level_keys(
        case_sheet,
        {"schema_version", "case_count", "cases"},
        f"{label}.case_decision_sheet",
    )
    require(
        case_sheet["schema_version"] == "qe_gpu_case_decision_sheet_v0",
        f"{label}.case_decision_sheet schema_version drifted",
    )
    require(
        case_sheet["case_count"] == len(case_sheet["cases"]),
        f"{label}.case_decision_sheet case_count drifted",
    )
    case_ids_from_rows = sorted({str(row.get("case_id") or "unknown_case") for row in rows})
    case_ids_from_sheet = sorted(str(item["case_id"]) for item in case_sheet["cases"])
    require(
        case_ids_from_sheet == case_ids_from_rows,
        f"{label}.case_decision_sheet cases drifted vs row_ledger",
    )
    decisive_case_ids_from_sheet: list[str] = []
    for idx, case in enumerate(case_sheet["cases"]):
        top_level_keys(
            case,
            {
                "case_id",
                "available_gpu_rows",
                "decisive_for_case_row",
                "excluded_rows",
                "workload_group_aggregation_status",
                "workload_group_aggregation_reason",
            },
            f"{label}.case_decision_sheet.cases[{idx}]",
        )
        available_rows = case["available_gpu_rows"]
        require(bool(available_rows), f"{label}.case_decision_sheet.cases[{idx}] missing available_gpu_rows")
        require(
            all(str(row.get("case_id") or case["case_id"]) == case["case_id"] for row in rows if str(row.get("case_id") or "unknown_case") == case["case_id"]),
            f"{label}.case_decision_sheet.cases[{idx}] case_id drifted vs row_ledger",
        )
        decisive_row = case["decisive_for_case_row"]
        if decisive_row is None:
            require(
                case["workload_group_aggregation_status"] == "excluded",
                f"{label}.case_decision_sheet.cases[{idx}] missing decisive row must be excluded",
            )
        else:
            decisive_case_ids_from_sheet.append(str(case["case_id"]))
            require(
                case["workload_group_aggregation_status"] == "included",
                f"{label}.case_decision_sheet.cases[{idx}] decisive row must be included",
            )
    require(
        sorted(payload["decisive_case_ids"]) == sorted(decisive_case_ids_from_sheet),
        f"{label}.decisive_case_ids drifted vs case_decision_sheet",
    )
    workload_manifest = payload["workload_group_gpu_column_manifest"]
    top_level_keys(
        workload_manifest,
        {
            "schema_version",
            "workload_group_id",
            "fairness_policy_id",
            "power_boundary_id",
            "algorithm_rewrite_manifest_id",
            "correctness_contract_id",
            "qe_tolerance_schema_id",
            "thesis_counted_cases",
            "decisive_row_paths",
            "excluded_cases",
            "unresolved_rows",
            "safe_claim_status",
        },
        f"{label}.workload_group_gpu_column_manifest",
    )
    require(
        workload_manifest["schema_version"] == "qe_gpu_workload_group_column_manifest_v0",
        f"{label}.workload_group_gpu_column_manifest schema_version drifted",
    )
    require(
        sorted(workload_manifest["thesis_counted_cases"]) == sorted(payload["decisive_case_ids"]),
        f"{label}.workload_group_gpu_column_manifest thesis_counted_cases drifted",
    )
    decisive_paths_case_ids = sorted(
        str(item["case_id"]) for item in workload_manifest["decisive_row_paths"]
    )
    require(
        decisive_paths_case_ids == sorted(payload["decisive_case_ids"]),
        f"{label}.workload_group_gpu_column_manifest decisive_row_paths drifted",
    )


def best_performance_order_key(candidate: dict[str, Any]) -> tuple[float, float, str]:
    time_to_convergence = candidate.get("time_to_convergence_s")
    energy_to_convergence = candidate.get("energy_to_convergence_j")
    return (
        float(time_to_convergence),
        float("inf") if energy_to_convergence is None else float(energy_to_convergence),
        str(candidate.get("fast_layer_result_id", "")),
    )


def validate_projection_review(review: dict[str, Any], label: str) -> None:
    top_level_keys(
        review,
        {
            "package_kind",
            "phase_id",
            "phase_config_path",
            "fast_layer_json_path",
            "accurate_layer_json_path",
            "json_path",
            "md_path",
            "stage_main_recommendation_status",
            "public_recommended_family",
            "public_recommendation_type",
            "projection_reporting_allowed",
            "promoted_candidate_count",
            "recommended_validated_candidates",
            "component_registry_path",
            "component_registry_summary",
            "review_readiness",
        },
        label,
    )
    require(review["package_kind"] == "qe_next_stage_projection_review_v0", f"{label} package_kind drifted")
    require(
        review["promoted_candidate_count"] == len(review["recommended_validated_candidates"]),
        f"{label} promoted_candidate_count does not match recommended_validated_candidates",
    )
    validate_component_registry_summary(
        review["component_registry_summary"],
        f"{label}.component_registry_summary",
    )
    require(Path(review["component_registry_path"]).exists(), f"{label}.component_registry_path missing")
    for idx, candidate in enumerate(review["recommended_validated_candidates"]):
        top_level_keys(
            candidate,
            {
                "source_workload_id",
                "selection_role",
                "fast_layer_result_id",
                "accurate_layer_result_id",
                "family",
                "diag_policy",
                "offload_scope",
                "resident_policy",
                "partition_strategy",
                "time_to_convergence_s",
                "energy_to_convergence_j",
                "gold_pass",
                "convergence_comparable_pass",
            },
            f"{label}.recommended_validated_candidates[{idx}]",
        )


def validate_stage_main_package(package: dict[str, Any], label: str) -> None:
    top_level_keys(
        package,
        {
            "package_kind",
            "phase_id",
            "phase_config_path",
            "fast_layer_json_path",
            "accurate_layer_json_path",
            "json_path",
            "md_path",
            "stage_main_recommendation_status",
            "recommended_family",
            "recommendation_type",
            "projection_reporting_allowed",
            "recommendation_status",
            "supported_source_workloads",
            "recommended_primary_candidate_count",
            "validated_alternative_candidate_count",
            "recommended_primary_candidates",
            "validated_alternative_candidates",
            "best_trusted_point",
            "best_performance_candidate",
            "component_registry_path",
            "component_registry_summary",
        },
        label,
    )
    require(
        package["package_kind"] == "qe_next_stage_stage_main_recommendation_v0",
        f"{label} package_kind drifted",
    )
    require(
        package["recommended_primary_candidate_count"] == len(package["recommended_primary_candidates"]),
        f"{label} recommended_primary_candidate_count does not match recommended_primary_candidates",
    )
    require(
        package["validated_alternative_candidate_count"] == len(package["validated_alternative_candidates"]),
        f"{label} validated_alternative_candidate_count does not match validated_alternative_candidates",
    )
    validate_component_registry_summary(
        package["component_registry_summary"],
        f"{label}.component_registry_summary",
    )
    require(Path(package["component_registry_path"]).exists(), f"{label}.component_registry_path missing")
    expected_supported = [
        item.get("source_workload_id") for item in package["recommended_primary_candidates"]
    ]
    require(
        package["supported_source_workloads"] == expected_supported,
        f"{label} supported_source_workloads drifted",
    )
    best_trusted = package["best_trusted_point"]
    top_level_keys(
        best_trusted,
        {
            "recommended_family",
            "supported_source_workloads",
            "recommended_primary_candidate_count",
        },
        f"{label}.best_trusted_point",
    )
    require(
        best_trusted["recommended_family"] == package["recommended_family"],
        f"{label}.best_trusted_point recommended_family drifted",
    )
    require(
        best_trusted["recommended_primary_candidate_count"] == package["recommended_primary_candidate_count"],
        f"{label}.best_trusted_point recommended_primary_candidate_count drifted",
    )
    require(
        best_trusted["supported_source_workloads"] == expected_supported,
        f"{label}.best_trusted_point supported_source_workloads drifted",
    )
    best_performance = package["best_performance_candidate"]
    if package["recommendation_status"] == "ready":
        require(best_performance is not None, f"{label} missing best_performance_candidate")
    if best_performance is not None:
        top_level_keys(
            best_performance,
            {
                "signature_id",
                "source_workload_id",
                "selection_role",
                "family",
                "diag_policy",
                "offload_scope",
                "resident_policy",
                "partition_strategy",
                "fast_layer_result_id",
                "accurate_layer_result_id",
                "time_to_convergence_s",
                "energy_to_convergence_j",
            },
            f"{label}.best_performance_candidate",
        )
        require(
            bool(str(best_performance["signature_id"]).strip()),
            f"{label}.best_performance_candidate signature_id missing",
        )
        comparable = package["recommended_primary_candidates"] + package["validated_alternative_candidates"]
        require(
            any(
                candidate.get("fast_layer_result_id") == best_performance["fast_layer_result_id"]
                and candidate.get("signature_id") == best_performance["signature_id"]
                and candidate.get("partition_strategy") == best_performance["partition_strategy"]
                for candidate in comparable
            ),
            f"{label}.best_performance_candidate not linked to a validated candidate",
        )
        performance_candidates = [
            candidate
            for candidate in comparable
            if candidate.get("time_to_convergence_s") is not None
        ]
        if performance_candidates:
            expected_best = min(performance_candidates, key=best_performance_order_key)
            require(
                best_performance["fast_layer_result_id"] == expected_best.get("fast_layer_result_id")
                and best_performance["signature_id"] == expected_best.get("signature_id")
                and best_performance["partition_strategy"] == expected_best.get("partition_strategy"),
                f"{label}.best_performance_candidate is not the strongest validated performance point",
            )


def validate_best_point_summary(
    best_point: dict[str, Any],
    public_recommendation: dict[str, Any],
    package: dict[str, Any],
    gate_status: str,
) -> None:
    top_level_keys(
        best_point,
        {
            "status",
            "source_surface",
            "stage_main_recommendation_status",
            "public_recommended_family",
            "recommendation_family",
            "trusted_family",
            "performance_family",
            "supported_source_workloads",
            "projection_reporting_allowed",
            "recommendation_type",
            "runtime_risk_overall",
            "best_point_fast_layer_result_id",
            "best_point_accurate_layer_result_id",
            "best_point_time_to_convergence_s",
            "best_point_energy_to_convergence_j",
            "best_point_runtime_risk_level",
            "best_point_runtime_risk_score",
            "best_point_graph_topology_summary",
            "best_point_graph_execution_plan_summary",
            "best_point_graph_component_driver_summary",
            "next_action",
        },
        "best_point_summary",
    )
    require(
        best_point["source_surface"] == "stage_main_recommendation_package",
        "best_point_summary must remain derived from stage_main_recommendation_package",
    )
    require(
        best_point["stage_main_recommendation_status"] == gate_status,
        "best_point_summary stage_main_recommendation_status drifted",
    )
    expected_status = "ready" if package.get("recommendation_status") == "ready" else "incomplete"
    require(best_point["status"] == expected_status, "best_point_summary status drifted")
    require(
        best_point["public_recommended_family"] == public_recommendation["public_recommended_family"],
        "best_point_summary public_recommended_family drifted",
    )
    require(
        best_point["recommendation_family"] == package["recommended_family"],
        "best_point_summary recommendation_family drifted",
    )
    require(
        best_point["trusted_family"] == package["best_trusted_point"]["recommended_family"],
        "best_point_summary trusted_family drifted",
    )
    best_performance = package.get("best_performance_candidate")
    require(
        best_point["performance_family"]
        == (None if best_performance is None else best_performance.get("family")),
        "best_point_summary performance_family drifted",
    )
    require(
        best_point["supported_source_workloads"] == package["supported_source_workloads"],
        "best_point_summary supported_source_workloads drifted",
    )
    require(
        best_point["projection_reporting_allowed"] == package["projection_reporting_allowed"],
        "best_point_summary projection_reporting_allowed drifted",
    )
    require(
        best_point["recommendation_type"] == package["recommendation_type"],
        "best_point_summary recommendation_type drifted",
    )
    require(
        best_point["runtime_risk_overall"]
        == (package.get("runtime_risk_summary") or {}).get("overall_runtime_risk"),
        "best_point_summary runtime_risk_overall drifted",
    )
    require(
        best_point["next_action"] == package.get("next_action"),
        "best_point_summary next_action drifted",
    )
    expected_best_fields = {
        "best_point_fast_layer_result_id": None if best_performance is None else best_performance.get("fast_layer_result_id"),
        "best_point_accurate_layer_result_id": None if best_performance is None else best_performance.get("accurate_layer_result_id"),
        "best_point_time_to_convergence_s": None if best_performance is None else best_performance.get("time_to_convergence_s"),
        "best_point_energy_to_convergence_j": None if best_performance is None else best_performance.get("energy_to_convergence_j"),
        "best_point_runtime_risk_level": None if best_performance is None else best_performance.get("runtime_risk_level"),
        "best_point_runtime_risk_score": None if best_performance is None else best_performance.get("runtime_risk_score"),
        "best_point_graph_topology_summary": None if best_performance is None else best_performance.get("graph_topology_summary"),
        "best_point_graph_execution_plan_summary": None if best_performance is None else best_performance.get("graph_execution_plan_summary"),
        "best_point_graph_component_driver_summary": None if best_performance is None else best_performance.get("graph_component_driver_summary"),
    }
    for key, expected in expected_best_fields.items():
        require(best_point[key] == expected, f"best_point_summary {key} drifted")


def validate_advisor_pack_summary(
    advisor: dict[str, Any],
    manifest: dict[str, Any],
    review: dict[str, Any],
    package: dict[str, Any],
    public_recommendation: dict[str, Any],
    best_point: dict[str, Any],
    gpu_annex: dict[str, Any],
    phase1_evidence_closure: dict[str, Any],
) -> None:
    top_level_keys(
        advisor,
        {
            "package_kind",
            "phase_id",
            "phase_config_path",
            "closure_scope",
            "release_entry_kind",
            "public_recommended_family",
            "public_recommendation_type",
            "advisor_release_ready",
            "trusted_family",
            "performance_family",
            "trusted_performance_divergence",
            "gpu_annex_status",
            "gpu_annex_reason",
            "thesis_claim_status",
            "phase1_decisive_lane_closed",
            "phase1_next_blocker_class",
            "best_point_summary",
            "known_limitations",
            "artifact_paths",
            "next_action",
            "json_path",
            "md_path",
        },
        "advisor_pack_summary",
    )
    require(
        advisor["package_kind"] == "qe_next_stage_advisor_pack_summary_v0",
        "advisor_pack_summary package_kind drifted",
    )
    require(
        advisor["closure_scope"] == "qe_ic_dse_recommendation_package_only",
        "advisor_pack_summary closure_scope drifted",
    )
    require(
        advisor["release_entry_kind"] == "stage_artifact_bundle_manifest",
        "advisor_pack_summary release_entry_kind drifted",
    )
    require(Path(advisor["json_path"]).exists(), "advisor_pack_summary json_path missing")
    require(Path(advisor["md_path"]).exists(), "advisor_pack_summary md_path missing")
    require(
        advisor["public_recommended_family"] == public_recommendation["public_recommended_family"],
        "advisor_pack_summary public_recommended_family drifted",
    )
    require(
        advisor["public_recommendation_type"] == public_recommendation["public_recommendation_type"],
        "advisor_pack_summary public_recommendation_type drifted",
    )
    require(
        advisor["advisor_release_ready"] == manifest["release_ready_recommendation"],
        "advisor_pack_summary advisor_release_ready drifted",
    )
    require(
        advisor["trusted_family"] == best_point["trusted_family"],
        "advisor_pack_summary trusted_family drifted",
    )
    require(
        advisor["performance_family"] == best_point["performance_family"],
        "advisor_pack_summary performance_family drifted",
    )
    expected_divergence = (
        best_point["trusted_family"] is not None
        and best_point["performance_family"] is not None
        and best_point["trusted_family"] != best_point["performance_family"]
    )
    require(
        advisor["trusted_performance_divergence"] == expected_divergence,
        "advisor_pack_summary trusted_performance_divergence drifted",
    )
    require(
        advisor["gpu_annex_status"] == gpu_annex["status"],
        "advisor_pack_summary gpu_annex_status drifted",
    )
    require(
        advisor["gpu_annex_reason"] == gpu_annex["reason"],
        "advisor_pack_summary gpu_annex_reason drifted",
    )
    expected_thesis_claim_status = (
        "gpu_annex_ready_but_not_auto_claimed"
        if gpu_annex["status"] == "thesis_eligible"
        else ("reference_only" if gpu_annex["status"] == "reference_only" else "deferred")
    )
    require(
        advisor["thesis_claim_status"] == expected_thesis_claim_status,
        "advisor_pack_summary thesis_claim_status drifted",
    )
    require(
        advisor["phase1_decisive_lane_closed"] == phase1_evidence_closure["summary"]["decisive_lane_closed"],
        "advisor_pack_summary phase1_decisive_lane_closed drifted",
    )
    require(
        advisor["phase1_next_blocker_class"] == phase1_evidence_closure["summary"]["next_blocker_class"],
        "advisor_pack_summary phase1_next_blocker_class drifted",
    )
    require(
        advisor["best_point_summary"] == best_point,
        "advisor_pack_summary best_point_summary drifted",
    )
    expected_limitations: list[str] = []
    if expected_divergence:
        expected_limitations.append("trusted_family_differs_from_performance_family")
    if gpu_annex["status"] != "thesis_eligible":
        expected_limitations.append(f"gpu_annex_{gpu_annex['status']}")
    for limitation in expected_limitations:
        require(
            limitation in advisor["known_limitations"],
            f"advisor_pack_summary missing known limitation {limitation}",
        )
    top_level_keys(
        advisor["artifact_paths"],
        {
            "manifest_json",
            "manifest_md",
            "projection_review_json",
            "projection_review_md",
            "stage_main_recommendation_json",
            "stage_main_recommendation_md",
            "gpu_annex_json",
            "gpu_annex_md",
            "phase1_evidence_closure_json",
            "phase1_evidence_closure_md",
            "release_evidence_json",
            "release_evidence_md",
        },
        "advisor_pack_summary.artifact_paths",
    )
    require(
        Path(advisor["artifact_paths"]["manifest_json"]).resolve() == Path(manifest["json_path"]).resolve(),
        "advisor_pack_summary manifest_json drifted",
    )
    require(
        Path(advisor["artifact_paths"]["manifest_md"]).resolve() == Path(manifest["md_path"]).resolve(),
        "advisor_pack_summary manifest_md drifted",
    )
    require(
        Path(advisor["artifact_paths"]["projection_review_json"]).resolve()
        == Path(review["json_path"]).resolve(),
        "advisor_pack_summary projection_review_json drifted",
    )
    require(
        Path(advisor["artifact_paths"]["projection_review_md"]).resolve()
        == Path(review["md_path"]).resolve(),
        "advisor_pack_summary projection_review_md drifted",
    )
    require(
        Path(advisor["artifact_paths"]["stage_main_recommendation_json"]).resolve()
        == Path(package["json_path"]).resolve(),
        "advisor_pack_summary stage_main_recommendation_json drifted",
    )
    require(
        Path(advisor["artifact_paths"]["stage_main_recommendation_md"]).resolve()
        == Path(package["md_path"]).resolve(),
        "advisor_pack_summary stage_main_recommendation_md drifted",
    )
    require(
        Path(advisor["artifact_paths"]["gpu_annex_json"]).resolve()
        == Path(manifest["artifact_paths"]["gpu_annex_json"]).resolve(),
        "advisor_pack_summary gpu_annex_json drifted",
    )
    require(
        Path(advisor["artifact_paths"]["gpu_annex_md"]).resolve()
        == Path(manifest["artifact_paths"]["gpu_annex_md"]).resolve(),
        "advisor_pack_summary gpu_annex_md drifted",
    )
    require(
        Path(advisor["artifact_paths"]["phase1_evidence_closure_json"]).resolve()
        == Path(phase1_evidence_closure["json_path"]).resolve(),
        "advisor_pack_summary phase1_evidence_closure_json drifted",
    )
    require(
        Path(advisor["artifact_paths"]["phase1_evidence_closure_md"]).resolve()
        == Path(phase1_evidence_closure["md_path"]).resolve(),
        "advisor_pack_summary phase1_evidence_closure_md drifted",
    )
    release_evidence_json = advisor["artifact_paths"]["release_evidence_json"]
    release_evidence_md = advisor["artifact_paths"]["release_evidence_md"]
    if release_evidence_json is not None:
        require(
            Path(release_evidence_json).exists(),
            "advisor_pack_summary release_evidence_json missing",
        )
    if release_evidence_md is not None:
        require(
            Path(release_evidence_md).exists(),
            "advisor_pack_summary release_evidence_md missing",
        )


def validate_phase1_evidence_closure(payload: dict[str, Any], label: str) -> None:
    top_level_keys(
        payload,
        {"json_path", "md_path", "summary", "case_matrix"},
        label,
    )
    require(Path(payload["json_path"]).exists(), f"{label}.json_path missing")
    require(Path(payload["md_path"]).exists(), f"{label}.md_path missing")
    summary = payload["summary"]
    top_level_keys(
        summary,
        {
            "gpu_input_rows",
            "board_input_rows",
            "gpu_decisive_ready_cases",
            "board_ready_cases",
            "thesis_count_candidate_ready_cases",
            "decisive_lane_targets",
            "decisive_lane_closed",
            "repo_internal_status",
            "next_blocker_class",
        },
        f"{label}.summary",
    )
    case_matrix = payload["case_matrix"]
    require(isinstance(case_matrix, list), f"{label}.case_matrix must be a list")
    for idx, row in enumerate(case_matrix):
        top_level_keys(
            row,
            {
                "case_id",
                "gpu_decisive_ready",
                "board_ready",
                "thesis_count_candidate_ready",
                "gpu_blockers",
                "board_blockers",
            },
            f"{label}.case_matrix[{idx}]",
        )


def validate_release_evidence_summary(
    payload: dict[str, Any],
    manifest: dict[str, Any],
    public_recommendation: dict[str, Any],
    gpu_annex: dict[str, Any],
    phase1_evidence_closure: dict[str, Any],
    best_point_summary: dict[str, Any],
    advisor_pack_summary: dict[str, Any],
) -> None:
    top_level_keys(
        payload,
        {
            "package_kind",
            "phase_id",
            "phase_config_path",
            "release_entry_kind",
            "bundle_readiness",
            "release_ready_recommendation",
            "public_recommended_family",
            "public_recommendation_type",
            "best_point_source_surface",
            "best_point_fast_layer_result_id",
            "best_point_accurate_layer_result_id",
            "gpu_annex_status",
            "gpu_annex_reason",
            "phase1_decisive_lane_closed",
            "phase1_next_blocker_class",
            "verification_commands",
            "artifact_paths",
            "safe_claims",
            "residual_risks",
            "json_path",
            "md_path",
        },
        "release_evidence_summary",
    )
    require(
        payload["package_kind"] == "qe_next_stage_release_evidence_v0",
        "release_evidence_summary package_kind drifted",
    )
    require(
        payload["release_entry_kind"] == "stage_artifact_bundle_manifest",
        "release_evidence_summary release_entry_kind drifted",
    )
    require(Path(payload["json_path"]).exists(), "release_evidence_summary json_path missing")
    require(Path(payload["md_path"]).exists(), "release_evidence_summary md_path missing")
    require(
        payload["bundle_readiness"] == manifest["bundle_readiness"],
        "release_evidence_summary bundle_readiness drifted",
    )
    require(
        payload["release_ready_recommendation"] == manifest["release_ready_recommendation"],
        "release_evidence_summary release_ready_recommendation drifted",
    )
    require(
        payload["public_recommended_family"] == public_recommendation["public_recommended_family"],
        "release_evidence_summary public_recommended_family drifted",
    )
    require(
        payload["public_recommendation_type"] == public_recommendation["public_recommendation_type"],
        "release_evidence_summary public_recommendation_type drifted",
    )
    require(
        payload["best_point_source_surface"] == best_point_summary["source_surface"],
        "release_evidence_summary best_point_source_surface drifted",
    )
    require(
        payload["best_point_fast_layer_result_id"] == best_point_summary["best_point_fast_layer_result_id"],
        "release_evidence_summary best_point_fast_layer_result_id drifted",
    )
    require(
        payload["best_point_accurate_layer_result_id"] == best_point_summary["best_point_accurate_layer_result_id"],
        "release_evidence_summary best_point_accurate_layer_result_id drifted",
    )
    require(
        payload["gpu_annex_status"] == gpu_annex["status"],
        "release_evidence_summary gpu_annex_status drifted",
    )
    require(
        payload["gpu_annex_reason"] == gpu_annex["reason"],
        "release_evidence_summary gpu_annex_reason drifted",
    )
    require(
        payload["phase1_decisive_lane_closed"] == phase1_evidence_closure["summary"]["decisive_lane_closed"],
        "release_evidence_summary phase1_decisive_lane_closed drifted",
    )
    require(
        payload["phase1_next_blocker_class"] == phase1_evidence_closure["summary"]["next_blocker_class"],
        "release_evidence_summary phase1_next_blocker_class drifted",
    )
    top_level_keys(
        payload["verification_commands"],
        {"phase_runner_command", "release_validator_command"},
        "release_evidence_summary.verification_commands",
    )
    top_level_keys(
        payload["artifact_paths"],
        {
            "manifest_json",
            "manifest_md",
            "advisor_pack_json",
            "advisor_pack_md",
            "gpu_annex_json",
            "gpu_annex_md",
            "phase1_evidence_closure_json",
            "phase1_evidence_closure_md",
            "phase_summary_json",
            "phase_summary_md",
        },
        "release_evidence_summary.artifact_paths",
    )
    require(
        Path(payload["artifact_paths"]["manifest_json"]).resolve() == Path(manifest["json_path"]).resolve(),
        "release_evidence_summary manifest_json drifted",
    )
    require(
        Path(payload["artifact_paths"]["manifest_md"]).resolve() == Path(manifest["md_path"]).resolve(),
        "release_evidence_summary manifest_md drifted",
    )
    require(
        Path(payload["artifact_paths"]["advisor_pack_json"]).resolve()
        == Path(advisor_pack_summary["json_path"]).resolve(),
        "release_evidence_summary advisor_pack_json drifted",
    )
    require(
        Path(payload["artifact_paths"]["advisor_pack_md"]).resolve()
        == Path(advisor_pack_summary["md_path"]).resolve(),
        "release_evidence_summary advisor_pack_md drifted",
    )
    require(
        Path(payload["artifact_paths"]["gpu_annex_json"]).resolve()
        == Path(manifest["artifact_paths"]["gpu_annex_json"]).resolve(),
        "release_evidence_summary gpu_annex_json drifted",
    )
    require(
        Path(payload["artifact_paths"]["gpu_annex_md"]).resolve()
        == Path(manifest["artifact_paths"]["gpu_annex_md"]).resolve(),
        "release_evidence_summary gpu_annex_md drifted",
    )
    require(
        Path(payload["artifact_paths"]["phase1_evidence_closure_json"]).resolve()
        == Path(phase1_evidence_closure["json_path"]).resolve(),
        "release_evidence_summary phase1_evidence_closure_json drifted",
    )
    require(
        Path(payload["artifact_paths"]["phase1_evidence_closure_md"]).resolve()
        == Path(phase1_evidence_closure["md_path"]).resolve(),
        "release_evidence_summary phase1_evidence_closure_md drifted",
    )
    require(
        "manifest_is_top_level_release_entry" in payload["safe_claims"],
        "release_evidence_summary missing manifest_is_top_level_release_entry safe claim",
    )


def validate_bundle_manifest(
    manifest: dict[str, Any],
    summary_path: Path,
    summary: dict[str, Any],
) -> None:
    top_level_keys(
        manifest,
        {
            "package_kind",
            "phase_id",
            "phase_config_path",
            "json_path",
            "md_path",
            "public_recommended_family",
            "public_recommendation_type",
            "stage_main_recommendation_status",
            "bundle_readiness",
            "release_ready_recommendation",
            "recommended_primary_candidate_count",
            "validated_alternative_candidate_count",
            "projection_review_candidate_count",
            "component_registry_summary",
            "gpu_annex_summary",
            "phase1_evidence_closure_summary",
            "artifact_paths",
        },
        "stage_artifact_bundle_manifest",
    )
    require(
        manifest["package_kind"] == "qe_next_stage_artifact_bundle_manifest_v0",
        "stage_artifact_bundle_manifest package_kind drifted",
    )
    artifact_paths = manifest["artifact_paths"]
    validate_component_registry_summary(
        manifest["component_registry_summary"],
        "stage_artifact_bundle_manifest.component_registry_summary",
    )
    top_level_keys(
        artifact_paths,
        {
            "fast_layer_json",
            "accurate_layer_json",
            "accurate_coverage_json",
            "generalization_coverage_json",
            "component_registry_json",
            "phase_summary_json",
            "phase_summary_md",
            "projection_review_json",
            "projection_review_md",
            "stage_main_recommendation_json",
            "stage_main_recommendation_md",
            "gpu_annex_json",
            "gpu_annex_md",
            "gpu_case_decision_sheet_json",
            "gpu_case_decision_sheet_md",
            "gpu_workload_group_manifest_json",
            "gpu_workload_group_manifest_md",
            "phase1_evidence_closure_json",
            "phase1_evidence_closure_md",
            "advisor_pack_json",
            "advisor_pack_md",
            "release_evidence_json",
            "release_evidence_md",
        },
        "stage_artifact_bundle_manifest.artifact_paths",
    )
    require(
        Path(artifact_paths["phase_summary_json"]).resolve() == summary_path.resolve(),
        "stage_artifact_bundle_manifest phase_summary_json must point at the summary json",
    )
    require(
        Path(artifact_paths["phase_summary_md"]).exists(),
        "stage_artifact_bundle_manifest phase_summary_md path missing",
    )
    require(
        Path(artifact_paths["component_registry_json"]).exists(),
        "stage_artifact_bundle_manifest component_registry_json path missing",
    )
    require(
        Path(artifact_paths["gpu_annex_json"]).exists(),
        "stage_artifact_bundle_manifest gpu_annex_json path missing",
    )
    require(
        Path(artifact_paths["gpu_annex_md"]).exists(),
        "stage_artifact_bundle_manifest gpu_annex_md path missing",
    )
    require(
        Path(artifact_paths["advisor_pack_json"]).exists(),
        "stage_artifact_bundle_manifest advisor_pack_json path missing",
    )
    require(
        Path(artifact_paths["advisor_pack_md"]).exists(),
        "stage_artifact_bundle_manifest advisor_pack_md path missing",
    )
    require(
        Path(artifact_paths["release_evidence_json"]).exists(),
        "stage_artifact_bundle_manifest release_evidence_json path missing",
    )
    require(
        Path(artifact_paths["release_evidence_md"]).exists(),
        "stage_artifact_bundle_manifest release_evidence_md path missing",
    )
    require(
        Path(artifact_paths["gpu_case_decision_sheet_json"]).exists(),
        "stage_artifact_bundle_manifest gpu_case_decision_sheet_json path missing",
    )
    require(
        Path(artifact_paths["gpu_case_decision_sheet_md"]).exists(),
        "stage_artifact_bundle_manifest gpu_case_decision_sheet_md path missing",
    )
    require(
        Path(artifact_paths["gpu_workload_group_manifest_json"]).exists(),
        "stage_artifact_bundle_manifest gpu_workload_group_manifest_json path missing",
    )
    require(
        Path(artifact_paths["gpu_workload_group_manifest_md"]).exists(),
        "stage_artifact_bundle_manifest gpu_workload_group_manifest_md path missing",
    )
    require(
        Path(artifact_paths["phase1_evidence_closure_json"]).exists(),
        "stage_artifact_bundle_manifest phase1_evidence_closure_json path missing",
    )
    require(
        Path(artifact_paths["phase1_evidence_closure_md"]).exists(),
        "stage_artifact_bundle_manifest phase1_evidence_closure_md path missing",
    )

    review = summary.get("projection_review")
    package = summary.get("stage_main_recommendation_package")
    gpu_annex = summary.get("gpu_annex_summary")
    phase1_evidence_closure = summary.get("phase1_evidence_closure")
    coverage = summary.get("accurate_coverage")
    coverage_summary = manifest.get("accurate_coverage_summary")
    generalization = summary.get("generalization_coverage")
    generalization_summary = manifest.get("generalization_coverage_summary")
    advisor = summary.get("advisor_pack_summary")

    require(
        manifest["gpu_annex_summary"] == gpu_annex,
        "stage_artifact_bundle_manifest gpu_annex_summary drifted vs phase summary",
    )
    require(
        manifest["phase1_evidence_closure_summary"]
        == (None if phase1_evidence_closure is None else phase1_evidence_closure["summary"]),
        "stage_artifact_bundle_manifest phase1_evidence_closure_summary drifted vs phase summary",
    )

    if review is not None:
        require(
            manifest["projection_review_candidate_count"] == review["promoted_candidate_count"],
            "stage_artifact_bundle_manifest projection_review_candidate_count drifted",
        )
        require(
            manifest["stage_main_recommendation_status"] == review["stage_main_recommendation_status"],
            "stage_artifact_bundle_manifest stage_main_recommendation_status drifted vs projection_review",
        )
        require(
            manifest["public_recommendation_type"] == review["public_recommendation_type"],
            "stage_artifact_bundle_manifest public_recommendation_type drifted vs projection_review",
        )
        require(
            Path(artifact_paths["projection_review_json"]).resolve()
            == Path(review["json_path"]).resolve(),
            "stage_artifact_bundle_manifest projection_review_json drifted",
        )
    if package is not None:
        require(
            manifest["stage_main_recommendation_status"] == package["stage_main_recommendation_status"],
            "stage_artifact_bundle_manifest stage_main_recommendation_status drifted vs stage_main_recommendation_package",
        )
        require(
            manifest["public_recommendation_type"] == package["recommendation_type"],
            "stage_artifact_bundle_manifest public_recommendation_type drifted vs stage_main_recommendation_package",
        )
        require(
            manifest["recommended_primary_candidate_count"]
            == package["recommended_primary_candidate_count"],
            "stage_artifact_bundle_manifest recommended_primary_candidate_count drifted",
        )
        require(
            manifest["validated_alternative_candidate_count"]
            == package["validated_alternative_candidate_count"],
            "stage_artifact_bundle_manifest validated_alternative_candidate_count drifted",
        )
        require(
            Path(artifact_paths["stage_main_recommendation_json"]).resolve()
            == Path(package["json_path"]).resolve(),
            "stage_artifact_bundle_manifest stage_main_recommendation_json drifted",
        )
    if gpu_annex is not None:
        gpu_paths = gpu_annex["artifact_paths"]
        require(
            Path(artifact_paths["gpu_annex_json"]).resolve()
            == Path(gpu_paths["gpu_annex_json"]).resolve(),
            "stage_artifact_bundle_manifest gpu_annex_json drifted",
        )
        require(
            Path(artifact_paths["gpu_annex_md"]).resolve()
            == Path(gpu_paths["gpu_annex_md"]).resolve(),
            "stage_artifact_bundle_manifest gpu_annex_md drifted",
        )
        require(
            Path(artifact_paths["gpu_case_decision_sheet_json"]).resolve()
            == Path(gpu_paths["case_decision_sheet_json"]).resolve(),
            "stage_artifact_bundle_manifest gpu_case_decision_sheet_json drifted",
        )
        require(
            Path(artifact_paths["gpu_case_decision_sheet_md"]).resolve()
            == Path(gpu_paths["case_decision_sheet_md"]).resolve(),
            "stage_artifact_bundle_manifest gpu_case_decision_sheet_md drifted",
        )
        require(
            Path(artifact_paths["gpu_workload_group_manifest_json"]).resolve()
            == Path(gpu_paths["workload_group_gpu_column_manifest_json"]).resolve(),
            "stage_artifact_bundle_manifest gpu_workload_group_manifest_json drifted",
        )
        require(
            Path(artifact_paths["gpu_workload_group_manifest_md"]).resolve()
            == Path(gpu_paths["workload_group_gpu_column_manifest_md"]).resolve(),
            "stage_artifact_bundle_manifest gpu_workload_group_manifest_md drifted",
        )
    if phase1_evidence_closure is not None:
        require(
            Path(artifact_paths["phase1_evidence_closure_json"]).resolve()
            == Path(phase1_evidence_closure["json_path"]).resolve(),
            "stage_artifact_bundle_manifest phase1_evidence_closure_json drifted",
        )
        require(
            Path(artifact_paths["phase1_evidence_closure_md"]).resolve()
            == Path(phase1_evidence_closure["md_path"]).resolve(),
            "stage_artifact_bundle_manifest phase1_evidence_closure_md drifted",
        )
    if advisor is not None:
        require(
            Path(artifact_paths["advisor_pack_json"]).resolve()
            == Path(advisor["json_path"]).resolve(),
            "stage_artifact_bundle_manifest advisor_pack_json drifted",
        )
        require(
            Path(artifact_paths["advisor_pack_md"]).resolve()
            == Path(advisor["md_path"]).resolve(),
            "stage_artifact_bundle_manifest advisor_pack_md drifted",
        )
    release_evidence = summary.get("release_evidence_summary")
    if release_evidence is not None:
        require(
            Path(artifact_paths["release_evidence_json"]).resolve()
            == Path(release_evidence["json_path"]).resolve(),
            "stage_artifact_bundle_manifest release_evidence_json drifted",
        )
        require(
            Path(artifact_paths["release_evidence_md"]).resolve()
            == Path(release_evidence["md_path"]).resolve(),
            "stage_artifact_bundle_manifest release_evidence_md drifted",
        )

    if coverage is not None:
        require(
            artifact_paths.get("accurate_coverage_json") is not None,
            "stage_artifact_bundle_manifest missing accurate_coverage_json",
        )
        coverage_bundle = load_json(Path(artifact_paths["accurate_coverage_json"]))
        coverage_result_count = len(coverage_bundle.get("results", []))
        coverage_pass_count = sum(
            1 for row in coverage_bundle.get("results", []) if row["correctness"]["gold_pass"] is True
        )
        require(coverage_summary is not None, "stage_artifact_bundle_manifest missing accurate_coverage_summary")
        require(
            coverage_summary["coverage_result_count"] == coverage_result_count,
            "stage_artifact_bundle_manifest coverage_result_count drifted",
        )
        require(
            coverage_summary["coverage_pass_count"] == coverage_pass_count,
            "stage_artifact_bundle_manifest coverage_pass_count drifted",
        )
        require(
            coverage_summary["coverage_ready"] is True or manifest["release_ready_recommendation"] is False,
            "release_ready_recommendation cannot be true when accurate_coverage_ready is false",
        )

    if generalization is not None:
        require(
            artifact_paths.get("generalization_coverage_json") is not None,
            "stage_artifact_bundle_manifest missing generalization_coverage_json",
        )
        generalization_bundle = load_json(Path(artifact_paths["generalization_coverage_json"]))
        generalization_result_count = len(generalization_bundle.get("results", []))
        generalization_pass_count = sum(
            1
            for row in generalization_bundle.get("results", [])
            if row["correctness"]["gold_pass"] is True
        )
        require(
            generalization_summary is not None,
            "stage_artifact_bundle_manifest missing generalization_coverage_summary",
        )
        require(
            generalization_summary["generalization_result_count"] == generalization_result_count,
            "stage_artifact_bundle_manifest generalization_result_count drifted",
        )
        require(
            generalization_summary["generalization_pass_count"] == generalization_pass_count,
            "stage_artifact_bundle_manifest generalization_pass_count drifted",
        )
        generalization_workload_count = len(
            {row["workload"]["workload_id"] for row in generalization_bundle.get("results", [])}
        )
        generalization_mismatch_count = sum(
            1
            for row in generalization_bundle.get("results", [])
            if row["correctness"]["gold_pass"] is not True
        )
        expected_generalization_ready = generalization_mismatch_count == 0
        require(
            generalization_summary["generalization_workload_count"] == generalization_workload_count,
            "stage_artifact_bundle_manifest generalization_workload_count drifted",
        )
        require(
            generalization_summary["generalization_mismatch_count"] == generalization_mismatch_count,
            "stage_artifact_bundle_manifest generalization_mismatch_count drifted",
        )
        require(
            generalization_summary["generalization_ready"] == expected_generalization_ready,
            "stage_artifact_bundle_manifest generalization_ready drifted",
        )

    if manifest["release_ready_recommendation"] is True:
        require(
            manifest["bundle_readiness"] == "ready",
            "release_ready_recommendation=true requires bundle_readiness=ready",
        )


def validate_release_bundle(summary_path: Path) -> None:
    summary = load_json(summary_path)
    top_level_keys(
        summary,
        {
            "schema_version",
            "phase_id",
            "phase_config_path",
            "component_registry",
            "public_recommendation",
            "gpu_annex_summary",
            "phase1_evidence_closure",
            "best_point_summary",
            "release_evidence_summary",
            "fast_layer",
            "accurate_layer",
            "projection_review",
            "stage_main_recommendation_package",
            "stage_artifact_bundle_manifest",
            "advisor_pack_summary",
        },
        "phase summary",
    )
    require(
        summary["schema_version"] == "qe_next_stage_dse_phase_summary_v0",
        "phase summary schema_version drifted",
    )

    review = summary["projection_review"]
    package = summary["stage_main_recommendation_package"]
    manifest = summary["stage_artifact_bundle_manifest"]
    gpu_annex = summary["gpu_annex_summary"]
    phase1_evidence_closure = summary["phase1_evidence_closure"]
    best_point_summary = summary["best_point_summary"]
    release_evidence_summary = summary["release_evidence_summary"]
    advisor_pack_summary = summary["advisor_pack_summary"]
    require(review is not None, "release bundle summary missing projection_review")
    require(package is not None, "release bundle summary missing stage_main_recommendation_package")
    require(manifest is not None, "release bundle summary missing stage_artifact_bundle_manifest")
    require(gpu_annex is not None, "release bundle summary missing gpu_annex_summary")
    require(phase1_evidence_closure is not None, "release bundle summary missing phase1_evidence_closure")
    require(best_point_summary is not None, "release bundle summary missing best_point_summary")
    require(release_evidence_summary is not None, "release bundle summary missing release_evidence_summary")
    require(advisor_pack_summary is not None, "release bundle summary missing advisor_pack_summary")

    validate_gpu_annex_summary(gpu_annex, "gpu_annex_summary")
    validate_phase1_evidence_closure(phase1_evidence_closure, "phase1_evidence_closure")
    validate_projection_review(review, "projection_review")
    validate_stage_main_package(package, "stage_main_recommendation_package")

    gate_status = summary["accurate_layer"]["stage_recommendation_gate"]["stage_main_recommendation_status"]
    public_recommendation = summary["public_recommendation"]
    component_registry = summary["component_registry"]
    top_level_keys(component_registry, {"json_path", "summary"}, "component_registry")
    validate_component_registry_summary(component_registry["summary"], "component_registry.summary")
    require(Path(component_registry["json_path"]).exists(), "component_registry json_path missing")

    require(
        public_recommendation["public_recommended_family"] == package["recommended_family"],
        "public_recommended_family drift between summary and stage_main_recommendation_package",
    )
    require(
        public_recommendation["public_recommended_family"] == review["public_recommended_family"],
        "public_recommended_family drift between summary and projection_review",
    )
    require(
        public_recommendation["public_recommended_family"]
        == manifest["public_recommended_family"],
        "public_recommended_family drift between summary and stage_artifact_bundle_manifest",
    )
    require(
        review["public_recommendation_type"] == public_recommendation["public_recommendation_type"],
        "public_recommendation_type drift between summary and projection_review",
    )
    require(
        package["recommendation_type"] == public_recommendation["public_recommendation_type"],
        "public_recommendation_type drift between summary and stage_main_recommendation_package",
    )
    require(
        manifest["public_recommendation_type"] == public_recommendation["public_recommendation_type"],
        "public_recommendation_type drift between summary and stage_artifact_bundle_manifest",
    )
    require(
        review["stage_main_recommendation_status"] == gate_status,
        "projection_review stage_main_recommendation_status drift",
    )
    require(
        package["stage_main_recommendation_status"] == gate_status,
        "stage_main_recommendation_package stage_main_recommendation_status drift",
    )
    require(
        manifest["stage_main_recommendation_status"] == gate_status,
        "stage_artifact_bundle_manifest stage_main_recommendation_status drift",
    )
    require(
        package["projection_reporting_allowed"] == public_recommendation["projection_reporting_allowed"],
        "stage_main_recommendation_package projection_reporting_allowed drift",
    )
    require(
        review["projection_reporting_allowed"] == public_recommendation["projection_reporting_allowed"],
        "projection_review projection_reporting_allowed drift",
    )
    require(
        review["component_registry_path"] == component_registry["json_path"],
        "projection_review component_registry_path drift",
    )
    require(
        package["component_registry_path"] == component_registry["json_path"],
        "stage_main_recommendation_package component_registry_path drift",
    )
    require(
        manifest["artifact_paths"]["component_registry_json"] == component_registry["json_path"],
        "stage_artifact_bundle_manifest component_registry_json drift",
    )
    require(
        review["component_registry_summary"] == component_registry["summary"],
        "projection_review component_registry_summary drift",
    )
    require(
        package["component_registry_summary"] == component_registry["summary"],
        "stage_main_recommendation_package component_registry_summary drift",
    )
    require(
        manifest["component_registry_summary"] == component_registry["summary"],
        "stage_artifact_bundle_manifest component_registry_summary drift",
    )

    validate_best_point_summary(best_point_summary, public_recommendation, package, gate_status)
    validate_advisor_pack_summary(
        advisor_pack_summary,
        manifest,
        review,
        package,
        public_recommendation,
        best_point_summary,
        gpu_annex,
        phase1_evidence_closure,
    )
    validate_release_evidence_summary(
        release_evidence_summary,
        manifest,
        public_recommendation,
        gpu_annex,
        phase1_evidence_closure,
        best_point_summary,
        advisor_pack_summary,
    )
    require(
        advisor_pack_summary["artifact_paths"]["release_evidence_json"] == release_evidence_summary["json_path"],
        "advisor_pack_summary release_evidence_json drifted",
    )
    require(
        advisor_pack_summary["artifact_paths"]["release_evidence_md"] == release_evidence_summary["md_path"],
        "advisor_pack_summary release_evidence_md drifted",
    )

    require(
        load_json(Path(review["json_path"])) == review,
        "projection_review json artifact drifted",
    )
    require(
        load_json(Path(package["json_path"])) == package,
        "stage_main_recommendation_package json artifact drifted",
    )
    require(
        load_json(Path(manifest["json_path"])) == manifest,
        "stage_artifact_bundle_manifest json artifact drifted",
    )
    require(
        load_json(Path(manifest["artifact_paths"]["gpu_annex_json"])) == gpu_annex,
        "gpu_annex_summary json artifact drifted",
    )
    require(
        load_json(Path(gpu_annex["artifact_paths"]["case_decision_sheet_json"]))
        == gpu_annex["case_decision_sheet"],
        "gpu_annex_summary case_decision_sheet json artifact drifted",
    )
    require(
        load_json(Path(gpu_annex["artifact_paths"]["workload_group_gpu_column_manifest_json"]))
        == gpu_annex["workload_group_gpu_column_manifest"],
        "gpu_annex_summary workload_group_gpu_column_manifest json artifact drifted",
    )
    phase1_report = load_json(Path(phase1_evidence_closure["json_path"]))
    require(
        phase1_report["summary"] == phase1_evidence_closure["summary"],
        "phase1_evidence_closure summary json artifact drifted",
    )
    require(
        phase1_report["case_matrix"] == phase1_evidence_closure["case_matrix"],
        "phase1_evidence_closure case_matrix json artifact drifted",
    )
    require(
        load_json(Path(advisor_pack_summary["json_path"])) == advisor_pack_summary,
        "advisor_pack_summary json artifact drifted",
    )
    require(
        load_json(Path(release_evidence_summary["json_path"])) == release_evidence_summary,
        "release_evidence_summary json artifact drifted",
    )

    validate_bundle_manifest(manifest, summary_path, summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a qe_next_stage release-facing bundle rooted at qe_next_stage_dse_phase_summary.json."
    )
    parser.add_argument("--summary", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validate_release_bundle(args.summary)
    print(f"[PASS] release bundle summary: {args.summary}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
