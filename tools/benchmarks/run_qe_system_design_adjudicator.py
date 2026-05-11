#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = ROOT / "docs/benchmarks"
ADJUDICATOR_SCHEMA_PATH = BENCHMARKS_DIR / "qe_system_design_adjudicator_schema_v0.json"
DEFAULT_DSE_BUNDLE_NAMES = (
    "systemc_architecture_family_dse_bootstrap_v0.json",
    "fast_layer_bundle.json",
    "accurate_layer_bundle.json",
)
OPTIONAL_ARTIFACT_CANONICAL_NAMES = {
    "gpu_annex": ("qe_gpu_annex_summary.json",),
    "phase1_closure": ("qe_phase1_evidence_closure_report.json",),
    "stage_main_evidence": ("qe_next_stage_stage_main_recommendation.json",),
}
BOARD_CLOSURE_GLOBS = ("board_compare.json", "*.board_compare.json")

AUTHORITY_CONTRACT_ID = "qe_ic_adjudicator_authority_contract_v0"
INPUT_MANIFEST_CONTRACT_ID = "qe_ic_adjudicator_input_manifest_contract_v0"
MEMO_SCHEMA_VERSION = "qe_system_design_adjudicator_schema_v0"
MEMO_KIND = "qe_system_design_adjudication_memo"
DSE_BUNDLE_SCHEMA_VERSION = "systemc_architecture_family_dse_result_schema_v0"
DSE_BUNDLE_KIND = "architecture_family_dse_bundle"

IDENTITY_FIELD_ORDER = [
    "workload_group_id",
    "family",
    "diag_policy",
    "offload_scope",
    "resident_policy",
    "partition_strategy",
    "assumption_set_id",
    "qe_tolerance_schema_id",
    "accounting_boundary_id",
    "fairness_policy_id",
    "power_boundary_id",
    "observability_contract_id",
    "algorithm_rewrite_manifest_id",
]

COMPARISON_IDENTITY_FIELD_ORDER = [field_name for field_name in IDENTITY_FIELD_ORDER if field_name != "family"]

ARTIFACT_CONTRACT_ID_FIELDS = [
    "workload_group_id",
    "qe_tolerance_schema_id",
    "accounting_boundary_id",
    "fairness_policy_id",
    "power_boundary_id",
    "observability_contract_id",
    "algorithm_rewrite_manifest_id",
    "correctness_contract_id",
]

DEFERRED_PROVENANCE_VALUE = "deferred"
UNKNOWN_PROVENANCE_VALUE = "unknown"

CANDIDATE_FAMILY_VALUES = {"F1", "F2", "F3", "F4", "F5", "custom"}
RUNTIME_PROJECTION_FAMILY_VALUES = {"F1", "F2", "F3", "none", "reserved"}

CLAIM_REGISTRY = [
    "family_recommendation",
    "simulator_dse_ranking_predictiveness",
    "cpu_fpga_vs_cpu_only",
    "cpu_fpga_vs_cpu_gpu",
    "lower_whole_node_power",
    "same_correctness_tolerance",
    "resident_offload_fallback_attribution",
]

STAGE_A_FORBIDDEN_CLAIMS = [
    "family_recommendation",
    "cpu_fpga_vs_cpu_only",
    "cpu_fpga_vs_cpu_gpu",
    "lower_whole_node_power",
    "same_correctness_tolerance",
    "resident_offload_fallback_attribution",
]

STAGE_B_ACTIVATION_GATE_IDS = [
    "input_manifest_bound",
    "authority_cohort_resolved",
    "workload_group_admissible",
    "correctness_contract_closed",
    "convergence_comparable",
    "gpu_baseline_ready",
    "ranking_stability_pass",
    "board_validation_available",
]

STAGE_B_UNLOCKABLE_CLAIMS = [
    "cpu_fpga_vs_cpu_gpu",
    "lower_whole_node_power",
]

BLOCKER_PRECEDENCE = {
    "identity_contract_integrity": 1,
    "correctness_convergence_integrity": 2,
    "measured_board_evidence": 3,
    "decisive_measured_gpu_baseline": 4,
    "calibrated_proxy_evidence": 5,
    "structural_projection_evidence": 6,
}

TRUSTED_VS_PERFORMANCE_CONTRADICTION_ID = "contradiction::trusted_vs_performance_divergence"


class AdjudicatorRunError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AdjudicatorRunError(message)


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_family_value(raw_value: Any, *, label: str) -> str:
    require(raw_value is not None, f"{label} missing family value")
    family = str(raw_value)
    require(family in CANDIDATE_FAMILY_VALUES, f"{label} has invalid family value: {family}")
    return family


def normalize_runtime_projection_family_value(raw_value: Any, *, label: str) -> str | None:
    if raw_value is None:
        return None
    family = str(raw_value)
    require(family in RUNTIME_PROJECTION_FAMILY_VALUES, f"{label} has invalid runtime_projection_family value: {family}")
    return family


def row_candidate_family(row: dict[str, Any], *, label: str) -> str:
    design = row.get("design_point") or {}
    return normalize_family_value(row.get("candidate_family", design.get("family")), label=label)


def row_runtime_projection_family(row: dict[str, Any], *, label: str) -> str | None:
    return normalize_runtime_projection_family_value(row.get("runtime_projection_family"), label=label)


def row_support_evidence(row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("support_evidence")
    return evidence if isinstance(evidence, dict) else {}


def row_executor_claim_allowed(row: dict[str, Any]) -> bool | None:
    value = row_support_evidence(row).get("executor_claim_allowed")
    return value if isinstance(value, bool) else None


def dse_subject_metadata(row: dict[str, Any]) -> dict[str, Any]:
    design = row.get("design_point") or {}
    support_evidence = row_support_evidence(row)
    design_axes = {
        key: design.get(key)
        for key in [
            "family",
            "diag_policy",
            "offload_scope",
            "resident_policy",
            "partition_strategy",
            "canonical_profile_match",
        ]
        if key in design
    }
    return {
        "candidate_family": row_candidate_family(row, label="dse_subject_row"),
        "runtime_projection_family": row_runtime_projection_family(row, label="dse_subject_row"),
        "evaluator_backend": row.get("evaluator_backend"),
        "fidelity_class": row.get("fidelity_class"),
        "support_status": row.get("support_status"),
        "support_evidence": {
            "executor_claim_allowed": row_executor_claim_allowed(row),
            "native_runtime_evidence_path": support_evidence.get("native_runtime_evidence_path"),
            "projection_reason": support_evidence.get("projection_reason"),
            "future_backend_note": support_evidence.get("future_backend_note"),
            "claim_boundary": support_evidence.get("claim_boundary"),
        },
        "architecture_template_id": row.get("architecture_template_id"),
        "candidate_id": row.get("candidate_id"),
        "design_axes": design_axes,
    }


def dse_subject_support_notes(row: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    candidate_family = row_candidate_family(row, label="dse_subject_row")
    runtime_family = row_runtime_projection_family(row, label="dse_subject_row")
    support_status = row.get("support_status")
    executor_claim_allowed = row_executor_claim_allowed(row)
    support_evidence = row_support_evidence(row)
    if runtime_family is not None and candidate_family != runtime_family:
        notes.append(
            f"Candidate identity is {candidate_family}, while runtime_projection_family is {runtime_family}; runtime projection is evaluator metadata only and is not used as the adjudicator identity."
        )
    if support_status == "projection_only":
        notes.append("support_status=projection_only means this DSE row is evidence/projection support only and cannot unlock Stage-A final/public architecture or performance claims.")
    if executor_claim_allowed is False:
        notes.append("support_evidence.executor_claim_allowed=false is executor-path metadata only; it never grants final/public claim permission and here keeps executor-backed claim unlocking blocked.")
    claim_boundary = support_evidence.get("claim_boundary")
    if isinstance(claim_boundary, str) and claim_boundary.strip():
        notes.append(f"DSE support claim boundary: {claim_boundary}")
    return notes


def dse_subject_support_blocks_claim_unlock(row: dict[str, Any]) -> bool:
    candidate_family = row_candidate_family(row, label="dse_subject_row")
    runtime_family = row_runtime_projection_family(row, label="dse_subject_row")
    return (
        (runtime_family is not None and candidate_family != runtime_family)
        or row.get("support_status") == "projection_only"
        or row_executor_claim_allowed(row) is False
    )


def resolve_dse_bundle_path(path: Path) -> Path:
    if path.is_file():
        return path
    require(path.is_dir(), f"--dse-bundle must be a JSON file or directory: {path}")
    for name in DEFAULT_DSE_BUNDLE_NAMES:
        candidate = path / name
        if candidate.exists():
            return candidate
    raise AdjudicatorRunError(
        f"could not resolve a DSE bundle JSON inside {path}; looked for {', '.join(DEFAULT_DSE_BUNDLE_NAMES)}"
    )


def resolve_optional_artifact_path(path: Path, label: str) -> Path:
    if path.is_file():
        return path
    require(path.is_dir(), f"--{label.replace('_', '-')} must be a JSON file or directory: {path}")
    if label in OPTIONAL_ARTIFACT_CANONICAL_NAMES:
        for name in OPTIONAL_ARTIFACT_CANONICAL_NAMES[label]:
            candidate = path / name
            if candidate.exists():
                return candidate
    if label == "board_closure":
        for pattern in BOARD_CLOSURE_GLOBS:
            matches = sorted(path.glob(pattern))
            if matches:
                return matches[0]
    raise AdjudicatorRunError(f"could not resolve {label} JSON from {path}")


def load_optional_artifact(path: Path | None, label: str) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = resolve_optional_artifact_path(path, label)
    payload = load_json(resolved)
    require(isinstance(payload, dict), f"{label} payload must be a JSON object: {resolved}")
    return {
        "label": label,
        "path": resolved,
        "payload": payload,
    }


def load_optional_artifact_from_directory(path: Path, label: str) -> dict[str, Any] | None:
    if not path.is_dir():
        return None
    try:
        resolved = resolve_optional_artifact_path(path, label)
    except AdjudicatorRunError:
        return None
    payload = load_json(resolved)
    require(isinstance(payload, dict), f"{label} payload must be a JSON object: {resolved}")
    return {
        "label": label,
        "path": resolved,
        "payload": payload,
    }


def load_dse_bundle(path: Path) -> dict[str, Any]:
    bundle = load_json(path)
    require(isinstance(bundle, dict), f"DSE bundle must be a JSON object: {path}")
    require(bundle.get("schema_version") == DSE_BUNDLE_SCHEMA_VERSION, f"unsupported DSE bundle schema_version in {path}")
    require(bundle.get("result_bundle_kind") == DSE_BUNDLE_KIND, f"unsupported DSE bundle kind in {path}")
    results = bundle.get("results")
    family_summary = bundle.get("family_summary")
    require(isinstance(results, list) and len(results) > 0, f"DSE bundle has no results: {path}")
    require(isinstance(family_summary, list) and len(family_summary) > 0, f"DSE bundle has no family_summary: {path}")
    return bundle


def select_subject_row(bundle: dict[str, Any]) -> dict[str, Any]:
    def row_key(row: dict[str, Any]) -> tuple[Any, ...]:
        design = row.get("design_point") or {}
        workload = row.get("workload") or {}
        return (
            not bool(design.get("canonical_profile_match", False)),
            str(workload.get("workload_id", "")),
            row_candidate_family(row, label="dse_bundle.result"),
            str(row.get("result_id", "")),
        )

    rows = [row for row in bundle["results"] if isinstance(row, dict)]
    require(len(rows) > 0, "DSE bundle results are empty after filtering invalid rows")
    return min(rows, key=row_key)


def family_summary_for(bundle: dict[str, Any], family: str) -> dict[str, Any]:
    for summary in bundle["family_summary"]:
        if isinstance(summary, dict) and summary.get("family") == family:
            return summary
    for summary in bundle.get("candidate_family_summary", []):
        if isinstance(summary, dict) and summary.get("candidate_family") == family:
            return {"family": family, **summary}
    return {
        "family": family,
        "summary_status": "candidate_family_summary_unavailable",
        "notes": [
            "No legacy family_summary row matched the candidate family; this advisory context is synthesized so candidate identity remains intact."
        ],
    }


def build_normalized_identity_tuple(row: dict[str, Any]) -> dict[str, str]:
    design = row.get("design_point") or {}
    contract = row.get("comparison_contract") or {}
    projection = row.get("projection") or {}
    identity = {
        "workload_group_id": str(contract.get("workload_group_id", "")),
        "family": row_candidate_family(row, label="dse_subject_row"),
        "diag_policy": str(design.get("diag_policy", "")),
        "offload_scope": str(design.get("offload_scope", "")),
        "resident_policy": str(design.get("resident_policy", "")),
        "partition_strategy": str(design.get("partition_strategy", "")),
        "assumption_set_id": str(projection.get("assumption_set_id", "")),
        "qe_tolerance_schema_id": str(contract.get("qe_tolerance_schema_id", "")),
        "accounting_boundary_id": str(contract.get("accounting_boundary_id", "")),
        "fairness_policy_id": str(contract.get("fairness_policy_id", "")),
        "power_boundary_id": str(contract.get("power_boundary_id", "")),
        "observability_contract_id": str(contract.get("observability_contract_id", "")),
        "algorithm_rewrite_manifest_id": str(contract.get("algorithm_rewrite_manifest_id", "")),
    }
    for field_name in IDENTITY_FIELD_ORDER:
        require(identity[field_name] != "", f"dse_subject_row missing identity field: {field_name}")
    return identity


def evaluated_families(
    bundle: dict[str, Any],
    *,
    identity_tuple: dict[str, str] | None = None,
    include_family: bool = True,
) -> list[str]:
    families = sorted(
        {
            row_candidate_family(row, label="dse_bundle.result")
            for row in bundle["results"]
            if isinstance(row, dict)
            and (identity_tuple is None or row_identity_matches(row, identity_tuple, include_family=include_family))
        }
    )
    require(len(families) > 0, "could not derive evaluated families from DSE bundle")
    return families


def row_time_to_convergence(row: dict[str, Any]) -> float | None:
    primary = row.get("primary_metrics") or {}
    value = primary.get("time_to_convergence_s")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def row_identity_matches(
    row: dict[str, Any],
    identity_tuple: dict[str, str],
    *,
    include_family: bool = True,
) -> bool:
    try:
        row_identity = build_normalized_identity_tuple(row)
    except AdjudicatorRunError:
        return False
    field_order = IDENTITY_FIELD_ORDER if include_family else COMPARISON_IDENTITY_FIELD_ORDER
    for field_name in field_order:
        if row_identity[field_name] != identity_tuple[field_name]:
            return False
    return True


def dse_ranking_ready(row: dict[str, Any]) -> bool:
    projection = row.get("projection") or {}
    return bool(projection.get("ranking_grade_ready"))


def dse_projection_grade_ready(row: dict[str, Any]) -> bool:
    projection = row.get("projection") or {}
    return bool(projection.get("projection_grade_ready"))


def trusted_row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    design = row.get("design_point") or {}
    time_to_convergence = row_time_to_convergence(row)
    return (
        0 if dse_projection_grade_ready(row) else 1,
        0 if time_to_convergence is not None else 1,
        time_to_convergence if time_to_convergence is not None else float("inf"),
        0 if bool(design.get("canonical_profile_match", False)) else 1,
        str(row.get("result_id", "")),
    )


def build_stage_a_context(bundle: dict[str, Any], subject_row: dict[str, Any], identity_tuple: dict[str, str]) -> dict[str, Any]:
    family_rows: dict[str, list[dict[str, Any]]] = {}
    canonical_family_candidate = normalize_family_value(
        row_candidate_family(subject_row, label="subject_row"),
        label="subject_row.candidate_family",
    )
    for row in bundle["results"]:
        if not isinstance(row, dict):
            continue
        if not row_identity_matches(row, identity_tuple, include_family=False):
            continue
        family = row_candidate_family(row, label="stage_a_context.result")
        family_rows.setdefault(family, []).append(row)
    trusted_points_per_family: dict[str, dict[str, Any]] = {}
    for family, rows in family_rows.items():
        eligible_rows = [row for row in rows if dse_projection_grade_ready(row)]
        if eligible_rows:
            trusted_points_per_family[family] = min(eligible_rows, key=trusted_row_key)
    trusted_family_candidate = None
    if trusted_points_per_family:
        best_trusted_row = min(trusted_points_per_family.values(), key=trusted_row_key)
        trusted_family_candidate = row_candidate_family(best_trusted_row, label="trusted_family_candidate")
    return {
        "canonical_family_candidate": canonical_family_candidate,
        "comparison_eligible_families": sorted(family_rows),
        "trusted_family_candidate": trusted_family_candidate,
        "best_performance_family_candidate": best_performance_family_candidate(bundle, identity_tuple=identity_tuple),
        "graph_projection_only": trusted_family_candidate is None,
        "dse_subject_metadata": dse_subject_metadata(subject_row),
        "dse_subject_support_notes": dse_subject_support_notes(subject_row),
        "dse_subject_support_blocks_claim_unlock": dse_subject_support_blocks_claim_unlock(subject_row),
        "overall_confidence": "bounded" if trusted_family_candidate is not None else "exploratory",
        "ranking_grade_support_present": any(dse_ranking_ready(row) for rows in family_rows.values() for row in rows),
    }


def subject_case_id(subject_row: dict[str, Any]) -> str:
    return str((subject_row.get("workload") or {}).get("workload_id", ""))


def payload_dict(artifact: dict[str, Any] | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    payload = artifact.get("payload")
    return payload if isinstance(payload, dict) else {}


def payload_list(artifact: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    values = payload_dict(artifact).get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def artifact_identity_source(payload: dict[str, Any]) -> dict[str, Any] | None:
    normalized_identity = payload.get("normalized_identity_tuple")
    if isinstance(normalized_identity, dict):
        return normalized_identity
    join_key = payload.get("join_key")
    if isinstance(join_key, dict):
        return join_key
    if any(field_name in payload for field_name in IDENTITY_FIELD_ORDER) or "architecture_family" in payload:
        return payload
    return None


def normalize_artifact_identity_tuple(source: dict[str, Any], *, label: str) -> tuple[dict[str, str], list[str]]:
    normalized: dict[str, str] = {}
    missing_fields: list[str] = []
    for field_name in IDENTITY_FIELD_ORDER:
        raw_value = source.get(field_name)
        if field_name == "family" and raw_value is None:
            raw_value = source.get("architecture_family")
        if raw_value is None or str(raw_value).strip() == "":
            missing_fields.append(field_name)
            continue
        if field_name == "family":
            try:
                normalized[field_name] = normalize_family_value(raw_value, label=f"{label}.{field_name}")
            except AdjudicatorRunError:
                missing_fields.append(field_name)
            continue
        normalized[field_name] = str(raw_value)
    return normalized, missing_fields


def evaluate_artifact_join_key(
    *,
    identity_tuple: dict[str, str],
    artifact: dict[str, Any] | None,
    artifact_ref_id: str,
    label: str,
) -> dict[str, Any]:
    if artifact is None:
        return {
            "artifact_ref_id": artifact_ref_id,
            "join_key_status": "not_applicable",
            "normalized_identity_tuple": None,
            "missing_fields": [],
            "drift_fields": [],
        }
    source = artifact_identity_source(payload_dict(artifact))
    if not isinstance(source, dict):
        return {
            "artifact_ref_id": artifact_ref_id,
            "join_key_status": "join_key_missing",
            "normalized_identity_tuple": None,
            "missing_fields": list(IDENTITY_FIELD_ORDER),
            "drift_fields": [],
        }
    normalized_identity, missing_fields = normalize_artifact_identity_tuple(source, label=label)
    if missing_fields:
        return {
            "artifact_ref_id": artifact_ref_id,
            "join_key_status": "join_key_missing",
            "normalized_identity_tuple": normalized_identity,
            "missing_fields": missing_fields,
            "drift_fields": [],
        }
    drift_fields = [
        field_name
        for field_name in IDENTITY_FIELD_ORDER
        if normalized_identity[field_name] != identity_tuple[field_name]
    ]
    return {
        "artifact_ref_id": artifact_ref_id,
        "join_key_status": "join_key_drift" if drift_fields else "exact_match",
        "normalized_identity_tuple": normalized_identity,
        "missing_fields": [],
        "drift_fields": drift_fields,
    }


def build_artifact_join_key_results(
    *,
    identity_tuple: dict[str, str],
    gpu_annex: dict[str, Any] | None,
    phase1_closure: dict[str, Any] | None,
    board_closure: dict[str, Any] | None,
    stage_main_evidence: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    gpu_result = evaluate_artifact_join_key(
        identity_tuple=identity_tuple,
        artifact=gpu_annex,
        artifact_ref_id="gpu_annex_summary::primary",
        label="gpu_annex_summary",
    )
    return {
        "gpu_annex_summary": gpu_result,
        "gpu_decisive_baseline_summary": {
            **gpu_result,
            "artifact_ref_id": "gpu_decisive_baseline_summary::primary",
        },
        "phase1_evidence_closure": evaluate_artifact_join_key(
            identity_tuple=identity_tuple,
            artifact=phase1_closure,
            artifact_ref_id="phase1_evidence_closure::primary",
            label="phase1_evidence_closure",
        ),
        "board_closure": evaluate_artifact_join_key(
            identity_tuple=identity_tuple,
            artifact=board_closure,
            artifact_ref_id="board_closure::primary",
            label="board_closure",
        ),
        "stage_main_evidence": evaluate_artifact_join_key(
            identity_tuple=identity_tuple,
            artifact=stage_main_evidence,
            artifact_ref_id="stage_main_evidence::primary",
            label="stage_main_evidence",
        ),
    }


def find_case_payload_entry(entries: list[dict[str, Any]], case_id: str) -> dict[str, Any] | None:
    for entry in entries:
        if entry.get("case_id") == case_id:
            return entry
    return None


def bool_payload(value: Any) -> bool:
    return value is True


def gpu_annex_status(gpu_annex: dict[str, Any] | None) -> str:
    status = payload_dict(gpu_annex).get("status")
    return str(status) if isinstance(status, str) else "deferred"


def board_projection_ready(board_closure: dict[str, Any] | None) -> bool:
    payload = payload_dict(board_closure)
    explicit = payload.get("ranking_stability_status")
    if isinstance(explicit, str):
        return explicit == "pass"
    projection = payload.get("projection_cross_check")
    if not isinstance(projection, dict):
        return False
    return (
        bool_payload(projection.get("ranking_grade_ready"))
        and bool_payload(projection.get("projection_grade_ready"))
        and projection.get("projection_consistency_status") == "pass"
    )


def board_power_ready(board_closure: dict[str, Any] | None) -> bool:
    payload = payload_dict(board_closure)
    confidence = payload.get("confidence")
    if isinstance(confidence, dict) and bool_payload(confidence.get("power_claim_ready")):
        return True
    return bool_payload(payload.get("power_claim_ready"))


def resolve_trusted_vs_performance_measured_resolution(
    *,
    board_closure: dict[str, Any] | None,
    trusted_family_candidate: str | None,
    best_performance_family_candidate: str | None,
) -> str:
    if trusted_family_candidate is None or best_performance_family_candidate is None:
        return "not_applicable"
    if trusted_family_candidate == best_performance_family_candidate:
        return "aligned"
    payload = payload_dict(board_closure)
    explicit = payload.get("trusted_vs_performance_resolution")
    if explicit == "resolved_in_favor_of_trusted_family":
        resolved_family = payload.get("trusted_vs_performance_resolved_family", trusted_family_candidate)
        try:
            if normalize_family_value(resolved_family, label="board_closure.trusted_vs_performance_resolved_family") == trusted_family_candidate:
                return "resolved_in_favor_of_trusted_family"
        except AdjudicatorRunError:
            return "conditional_until_measured_resolution"
    resolved_family = payload.get("trusted_vs_performance_resolved_family")
    resolution_source = payload.get("trusted_vs_performance_resolution_source")
    if isinstance(resolution_source, str) and resolution_source in {"board_validated", "whole_node_measured"} and resolved_family is not None:
        try:
            if normalize_family_value(resolved_family, label="board_closure.trusted_vs_performance_resolved_family") == trusted_family_candidate:
                return "resolved_in_favor_of_trusted_family"
        except AdjudicatorRunError:
            return "conditional_until_measured_resolution"
    return "conditional_until_measured_resolution"


def build_stage_context(
    *,
    bundle: dict[str, Any],
    subject_row: dict[str, Any],
    identity_tuple: dict[str, str],
    artifact_join_key_results: dict[str, dict[str, Any]],
    gpu_annex: dict[str, Any] | None,
    phase1_closure: dict[str, Any] | None,
    board_closure: dict[str, Any] | None,
) -> dict[str, Any]:
    stage_a_context = build_stage_a_context(bundle, subject_row, identity_tuple)
    case_id = subject_case_id(subject_row)
    gpu_payload = payload_dict(gpu_annex)
    phase1_payload = payload_dict(phase1_closure)
    board_payload = payload_dict(board_closure)
    phase1_summary_raw = phase1_payload.get("summary")
    phase1_summary: dict[str, Any] = phase1_summary_raw if isinstance(phase1_summary_raw, dict) else {}
    phase1_case_entry = find_case_payload_entry(payload_list(phase1_closure, "case_matrix"), case_id)
    decisive_case_ids = {
        str(value)
        for value in gpu_payload.get("decisive_case_ids", [])
        if str(value)
    } if isinstance(gpu_payload.get("decisive_case_ids"), list) else set()
    workload_manifest = gpu_payload.get("workload_group_gpu_column_manifest")
    if not isinstance(workload_manifest, dict):
        workload_manifest = {}
    thesis_counted_cases = {
        str(value)
        for value in workload_manifest.get("thesis_counted_cases", [])
        if str(value)
    } if isinstance(workload_manifest.get("thesis_counted_cases"), list) else set()
    decisive_modes = sorted(
        {
            str(value)
            for value in gpu_payload.get("gpu_decisive_modes", [])
            if str(value)
        }
    ) if isinstance(gpu_payload.get("gpu_decisive_modes"), list) else []
    correctness_raw = board_payload.get("correctness")
    correctness: dict[str, Any] = correctness_raw if isinstance(correctness_raw, dict) else {}
    gpu_join_key_ok = artifact_join_key_results["gpu_annex_summary"]["join_key_status"] == "exact_match"
    phase1_join_key_ok = artifact_join_key_results["phase1_evidence_closure"]["join_key_status"] == "exact_match"
    board_join_key_ok = artifact_join_key_results["board_closure"]["join_key_status"] == "exact_match"
    gpu_ready = (
        gpu_join_key_ok
        and
        gpu_annex_status(gpu_annex) == "thesis_eligible"
        and case_id in decisive_case_ids
        and len(decisive_modes) > 0
    )
    phase1_case_ready = phase1_join_key_ok and bool(phase1_case_entry and phase1_case_entry.get("thesis_count_candidate_ready") is True)
    workload_group_ready = (
        gpu_join_key_ok
        and phase1_join_key_ok
        and
        phase1_summary.get("decisive_lane_closed") is True
        and int(phase1_summary.get("thesis_count_candidate_ready_cases", 0)) >= 2
        and phase1_case_ready
        and workload_manifest.get("safe_claim_status") == "gpu_column_ready"
        and case_id in thesis_counted_cases
    )
    correctness_closed = phase1_join_key_ok and board_join_key_ok and bool_payload(correctness.get("gold_pass")) and phase1_case_ready
    convergence_closed = phase1_join_key_ok and board_join_key_ok and bool_payload(correctness.get("convergence_comparable_pass")) and phase1_case_ready
    board_power_claim_ready = board_join_key_ok and board_power_ready(board_closure)
    board_validation_ready = board_join_key_ok and correctness_closed and convergence_closed and board_projection_ready(board_closure)
    ranking_stability_ready = board_join_key_ok and board_projection_ready(board_closure) and stage_a_context["ranking_grade_support_present"]
    stage_b_activatable = all(
        [
            stage_a_context["trusted_family_candidate"] is not None,
            not stage_a_context.get("dse_subject_support_blocks_claim_unlock", False),
            gpu_ready,
            workload_group_ready,
            correctness_closed,
            convergence_closed,
            board_validation_ready,
            ranking_stability_ready,
        ]
    )
    stage = "stage_b" if stage_b_activatable else "stage_a"
    overall_confidence = stage_a_context["overall_confidence"]
    if stage == "stage_b":
        overall_confidence = "board_validated" if board_power_claim_ready else "conditional"
    return {
        **stage_a_context,
        "stage": stage,
        "case_id": case_id,
        "gpu_ready": gpu_ready,
        "gpu_decisive_modes": decisive_modes,
        "phase1_summary": phase1_summary,
        "phase1_case_ready": phase1_case_ready,
        "workload_group_ready": workload_group_ready,
        "correctness_closed": correctness_closed,
        "convergence_closed": convergence_closed,
        "board_validation_ready": board_validation_ready,
        "board_power_ready": board_power_claim_ready,
        "ranking_stability_ready": ranking_stability_ready,
        "thesis_counted_cases": sorted(thesis_counted_cases),
        "trusted_vs_performance_measured_resolution": resolve_trusted_vs_performance_measured_resolution(
            board_closure=board_closure,
            trusted_family_candidate=stage_a_context["trusted_family_candidate"],
            best_performance_family_candidate=stage_a_context["best_performance_family_candidate"],
        ),
        "overall_confidence": overall_confidence,
    }


def best_performance_family_candidate(bundle: dict[str, Any], *, identity_tuple: dict[str, str] | None = None) -> str | None:
    ranked_rows: list[tuple[float, str, dict[str, Any]]] = []
    for row in bundle["results"]:
        if not isinstance(row, dict):
            continue
        if identity_tuple is not None and not row_identity_matches(row, identity_tuple, include_family=False):
            continue
        primary = row.get("primary_metrics") or {}
        time_to_convergence = primary.get("time_to_convergence_s")
        if isinstance(time_to_convergence, (int, float)):
            ranked_rows.append((float(time_to_convergence), str(row.get("result_id", "")), row))
    if not ranked_rows:
        return None
    _, _, best_row = min(ranked_rows)
    return row_candidate_family(best_row, label="best_performance_row")


def dse_projection_ready(row: dict[str, Any]) -> bool:
    return dse_projection_grade_ready(row)


def dse_evidence_tier(row: dict[str, Any]) -> str:
    if dse_projection_grade_ready(row):
        return "projection_grade"
    if dse_ranking_ready(row):
        return "projection_grade"
    return "graph_projection_only"


def gate_status_entry(status: str, *, blocking: bool = False, blocker_ids: list[str] | None = None, notes: list[str] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "status": status,
        "blocking": blocking,
        "blocker_ids": blocker_ids or [],
    }
    if notes:
        entry["notes"] = notes
    return entry


def artifact_path_token(label: str) -> str:
    return f"deferred://{label}"


def infer_optional_source_kind(label: str, artifact: dict[str, Any] | None) -> str | None:
    if artifact is None:
        return None
    if label == "board_closure":
        return "measured"
    payload = artifact["payload"]
    source_kind = payload.get("source_kind")
    if isinstance(source_kind, str) and source_kind in {"stub", "timed_functional_proxy", "trace_calibrated_proxy", "measured", "mixed"}:
        return source_kind
    if label == "stage_main_evidence":
        return "mixed"
    return None


def placeholder_contract_ids(value: str) -> dict[str, str]:
    return {field_name: value for field_name in ARTIFACT_CONTRACT_ID_FIELDS}


def contract_ids_from_mapping(mapping: dict[str, Any] | None, *, placeholder: str) -> dict[str, str]:
    contract_ids = placeholder_contract_ids(placeholder)
    if not isinstance(mapping, dict):
        return contract_ids
    for field_name in ARTIFACT_CONTRACT_ID_FIELDS:
        raw_value = mapping.get(field_name)
        if isinstance(raw_value, str) and raw_value.strip():
            contract_ids[field_name] = raw_value
    return contract_ids


def schema_id_from_payload(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return UNKNOWN_PROVENANCE_VALUE
    for field_name in ["schema_version", "package_kind", "result_bundle_kind"]:
        value = payload.get(field_name)
        if isinstance(value, str) and value.strip():
            return value
    return UNKNOWN_PROVENANCE_VALUE


def hash_metadata_for_artifact(path: Path | None, *, placeholder: str) -> dict[str, str]:
    if path is None:
        return {"sha256": placeholder}
    return {"sha256": file_sha256(path)}


def subject_row_contract_ids(identity_tuple: dict[str, str]) -> dict[str, str]:
    contract_ids = placeholder_contract_ids(UNKNOWN_PROVENANCE_VALUE)
    for field_name in [
        "workload_group_id",
        "qe_tolerance_schema_id",
        "accounting_boundary_id",
        "fairness_policy_id",
        "power_boundary_id",
        "observability_contract_id",
        "algorithm_rewrite_manifest_id",
    ]:
        contract_ids[field_name] = identity_tuple[field_name]
    return contract_ids


def build_present_artifact_provenance(
    *,
    artifact: dict[str, Any],
    fallback_contract_ids: dict[str, str],
) -> dict[str, Any]:
    payload = payload_dict(artifact)
    contract_source = payload.get("contract_ids")
    if not isinstance(contract_source, dict):
        contract_source = artifact_identity_source(payload)
    contract_ids = contract_ids_from_mapping(contract_source, placeholder=UNKNOWN_PROVENANCE_VALUE)
    for field_name, field_value in fallback_contract_ids.items():
        if contract_ids[field_name] == UNKNOWN_PROVENANCE_VALUE and field_value != UNKNOWN_PROVENANCE_VALUE:
            contract_ids[field_name] = field_value
    return {
        "artifact_schema_id": schema_id_from_payload(payload),
        "artifact_contract_ids": contract_ids,
        "artifact_hashes": hash_metadata_for_artifact(artifact["path"], placeholder=UNKNOWN_PROVENANCE_VALUE),
    }


def build_deferred_artifact_provenance() -> dict[str, Any]:
    return {
        "artifact_schema_id": DEFERRED_PROVENANCE_VALUE,
        "artifact_contract_ids": placeholder_contract_ids(DEFERRED_PROVENANCE_VALUE),
        "artifact_hashes": hash_metadata_for_artifact(None, placeholder=DEFERRED_PROVENANCE_VALUE),
    }


def build_optional_artifact_ref(
    *,
    artifact_ref_id: str,
    artifact_kind: str,
    artifact: dict[str, Any] | None,
    deferred_label: str,
    fallback_contract_ids: dict[str, str],
    join_key_status: str = "not_applicable",
) -> dict[str, Any]:
    if artifact is None:
        return {
            "artifact_ref_id": artifact_ref_id,
            "artifact_kind": artifact_kind,
            "artifact_path": artifact_path_token(deferred_label),
            "artifact_status": "deferred",
            "join_key_status": "not_applicable",
            "source_kind": None,
            **build_deferred_artifact_provenance(),
        }
    return {
        "artifact_ref_id": artifact_ref_id,
        "artifact_kind": artifact_kind,
        "artifact_path": str(artifact["path"]),
        "artifact_status": "present",
        "join_key_status": join_key_status,
        "source_kind": infer_optional_source_kind(artifact["label"], artifact),
        **build_present_artifact_provenance(artifact=artifact, fallback_contract_ids=fallback_contract_ids),
    }


def build_family_summary_context_ref(
    *,
    dse_bundle_path: Path,
    family: str,
    source_kind: str | None,
    dse_bundle: dict[str, Any],
    fallback_contract_ids: dict[str, str],
) -> dict[str, Any]:
    return {
        "artifact_ref_id": f"family_summary_context::{family}",
        "artifact_kind": "family_summary_context",
        "artifact_path": str(dse_bundle_path),
        "artifact_status": "present",
        "join_key_status": "family_only_context",
        "source_kind": source_kind,
        "artifact_schema_id": str(dse_bundle.get("schema_version", UNKNOWN_PROVENANCE_VALUE)),
        "artifact_contract_ids": fallback_contract_ids,
        "artifact_hashes": hash_metadata_for_artifact(dse_bundle_path, placeholder=UNKNOWN_PROVENANCE_VALUE),
    }


def build_gpu_decisive_baseline_summary_ref(
    *,
    gpu_annex: dict[str, Any] | None,
    fallback_contract_ids: dict[str, str],
) -> dict[str, Any]:
    if gpu_annex is None:
        return {
            "artifact_ref_id": "gpu_decisive_baseline_summary::primary",
            "artifact_kind": "gpu_decisive_baseline_summary",
            "artifact_path": artifact_path_token("gpu_decisive_baseline_summary"),
            "artifact_status": "deferred",
            "join_key_status": "not_applicable",
            "source_kind": None,
            **build_deferred_artifact_provenance(),
        }
    return {
        "artifact_ref_id": "gpu_decisive_baseline_summary::primary",
        "artifact_kind": "gpu_decisive_baseline_summary",
        "artifact_path": str(gpu_annex["path"]),
        "artifact_status": "advisory_only",
        "join_key_status": "not_applicable",
        "source_kind": infer_optional_source_kind("gpu_annex", gpu_annex),
        **build_present_artifact_provenance(artifact=gpu_annex, fallback_contract_ids=fallback_contract_ids),
    }


def manifest_artifact_status(artifact: dict[str, Any] | None, join_key_status: str) -> str:
    if artifact is None:
        return "deferred"
    if join_key_status in {"join_key_missing", "join_key_drift"}:
        return "missing"
    return "present"


def build_input_artifact_manifest(
    *,
    dse_bundle_path: Path,
    dse_bundle: dict[str, Any],
    subject_row: dict[str, Any],
    identity_tuple: dict[str, str],
    artifact_join_key_results: dict[str, dict[str, Any]],
    gpu_annex: dict[str, Any] | None,
    phase1_closure: dict[str, Any] | None,
    stage_main_evidence: dict[str, Any] | None,
    board_closure: dict[str, Any] | None,
) -> dict[str, Any]:
    fallback_contract_ids = subject_row_contract_ids(identity_tuple)
    subject_ref = {
        "artifact_ref_id": f"dse_subject_row::{subject_row['result_id']}",
        "artifact_kind": "dse_result_row",
        "artifact_path": str(dse_bundle_path),
        "artifact_status": "present",
        "join_key_status": "exact_match",
        "source_kind": subject_row.get("source_kind"),
        "dse_subject_metadata": dse_subject_metadata(subject_row),
        "artifact_schema_id": str(dse_bundle.get("schema_version", UNKNOWN_PROVENANCE_VALUE)),
        "artifact_contract_ids": fallback_contract_ids,
        "artifact_hashes": hash_metadata_for_artifact(dse_bundle_path, placeholder=UNKNOWN_PROVENANCE_VALUE),
    }
    manifest: dict[str, Any] = {
        "required_input_surfaces": [
            "dse_subject_row",
            "family_summary_context",
            "gpu_annex_summary",
            "gpu_decisive_baseline_summary",
            "phase1_evidence_closure",
            "stage_main_evidence",
        ],
        "normalized_identity_tuple": identity_tuple,
        "dse_subject_row": subject_ref,
        "family_summary_context": build_family_summary_context_ref(
            dse_bundle_path=dse_bundle_path,
            family=identity_tuple["family"],
            source_kind=subject_row.get("source_kind"),
            dse_bundle=dse_bundle,
            fallback_contract_ids=fallback_contract_ids,
        ),
        "gpu_annex_summary": build_optional_artifact_ref(
            artifact_ref_id="gpu_annex_summary::primary",
            artifact_kind="gpu_annex_summary",
            artifact=gpu_annex,
            deferred_label="gpu_annex_summary",
            fallback_contract_ids=fallback_contract_ids,
            join_key_status=artifact_join_key_results["gpu_annex_summary"]["join_key_status"],
        ),
        "gpu_decisive_baseline_summary": build_gpu_decisive_baseline_summary_ref(
            gpu_annex=gpu_annex,
            fallback_contract_ids=fallback_contract_ids,
        ),
        "phase1_evidence_closure": build_optional_artifact_ref(
            artifact_ref_id="phase1_evidence_closure::primary",
            artifact_kind="phase1_evidence_closure",
            artifact=phase1_closure,
            deferred_label="phase1_evidence_closure",
            fallback_contract_ids=fallback_contract_ids,
            join_key_status=artifact_join_key_results["phase1_evidence_closure"]["join_key_status"],
        ),
        "stage_main_evidence": build_optional_artifact_ref(
            artifact_ref_id="stage_main_evidence::primary",
            artifact_kind="stage_main_recommendation_evidence",
            artifact=stage_main_evidence,
            deferred_label="stage_main_recommendation_evidence",
            fallback_contract_ids=fallback_contract_ids,
            join_key_status=artifact_join_key_results["stage_main_evidence"]["join_key_status"],
        ),
    }
    manifest["gpu_annex_summary"]["artifact_status"] = manifest_artifact_status(
        gpu_annex,
        artifact_join_key_results["gpu_annex_summary"]["join_key_status"],
    )
    manifest["phase1_evidence_closure"]["artifact_status"] = manifest_artifact_status(
        phase1_closure,
        artifact_join_key_results["phase1_evidence_closure"]["join_key_status"],
    )
    manifest["stage_main_evidence"]["artifact_status"] = manifest_artifact_status(
        stage_main_evidence,
        artifact_join_key_results["stage_main_evidence"]["join_key_status"],
    )
    if gpu_annex is not None:
        manifest["gpu_decisive_baseline_summary"]["join_key_status"] = artifact_join_key_results["gpu_decisive_baseline_summary"]["join_key_status"]
        manifest["gpu_decisive_baseline_summary"]["artifact_status"] = (
            "missing"
            if artifact_join_key_results["gpu_decisive_baseline_summary"]["join_key_status"] in {"join_key_missing", "join_key_drift"}
            else "advisory_only"
        )
    if board_closure is not None:
        manifest["additional_evidence_refs"] = [
            build_optional_artifact_ref(
                artifact_ref_id="board_closure::primary",
                artifact_kind="board_compare",
                artifact=board_closure,
                deferred_label="board_compare",
                fallback_contract_ids=fallback_contract_ids,
                join_key_status=artifact_join_key_results["board_closure"]["join_key_status"],
            )
        ]
        manifest["additional_evidence_refs"][0]["artifact_status"] = manifest_artifact_status(
            board_closure,
            artifact_join_key_results["board_closure"]["join_key_status"],
        )
    return manifest


def build_policy_surface() -> dict[str, Any]:
    return {
        "policy_id": "qe_ic_evidence_claim_policy_v0",
        "evidence_axes_are_distinct": True,
        "canonical_claim_permission_surface": "claim_matrix",
        "source_kind_authority_rule": "source_kind_is_provenance_only",
        "contradiction_precedence": [
            "identity_contract_integrity",
            "correctness_convergence_integrity",
            "measured_board_evidence",
            "decisive_measured_gpu_baseline",
            "calibrated_proxy_evidence",
            "structural_projection_evidence",
        ],
        "trusted_vs_performance_divergence_rule": "trusted_point_per_family_remains_authority; divergence_must_be_reported; stage_a_no_public_recommendation; stage_b_requires_measured_resolution",
        "stage_b_release_rule": "stage_b_claims_and_public_release_require_measured_board_or_whole_node_evidence_plus_closed_correctness_convergence_fairness_and_power_boundaries",
        "decisive_gpu_baseline_rule": "cpu_fpga_vs_cpu_gpu_and_lower_whole_node_power_claims_require_decisive_measured_gpu_baseline_and_closed_shared_rewrite_fairness_context",
        "stage_a_forbidden_claim_ids": STAGE_A_FORBIDDEN_CLAIMS,
        "stage_b_same_schema": True,
    }


def build_blocker_record(
    *,
    blocker_id: str,
    blocker_class: str,
    precedence_category: str,
    severity: str,
    blocking_scope: str,
    affected_claim_ids: list[str],
    affected_artifact_ref_ids: list[str],
    rationale: str,
) -> dict[str, Any]:
    return {
        "blocker_id": blocker_id,
        "blocker_class": blocker_class,
        "precedence_category": precedence_category,
        "precedence_rank": BLOCKER_PRECEDENCE[precedence_category],
        "severity": severity,
        "status": "active",
        "blocking_scope": blocking_scope,
        "affected_claim_ids": affected_claim_ids,
        "affected_artifact_ref_ids": affected_artifact_ref_ids,
        "hard_gate_source": None,
        "rationale": rationale,
    }


def build_blocker_ledger(
    *,
    subject_row: dict[str, Any],
    stage_a_context: dict[str, Any],
    artifact_join_key_results: dict[str, dict[str, Any]],
    gpu_annex: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    stage = stage_a_context.get("stage", "stage_a")
    artifact_label = {
        "gpu_annex_summary": "gpu_annex_summary",
        "phase1_evidence_closure": "phase1_evidence_closure",
        "board_closure": "board_closure",
        "stage_main_evidence": "stage_main_evidence",
    }
    for key, result in artifact_join_key_results.items():
        if key == "gpu_decisive_baseline_summary":
            continue
        join_key_status = result["join_key_status"]
        if join_key_status not in {"join_key_missing", "join_key_drift"}:
            continue
        field_list = result["missing_fields"] if join_key_status == "join_key_missing" else result["drift_fields"]
        field_summary = ", ".join(field_list)
        blockers.append(
            build_blocker_record(
                blocker_id=f"blocker::{join_key_status}::{artifact_label[key]}",
                blocker_class=join_key_status,
                precedence_category="identity_contract_integrity",
                severity="hard_block",
                blocking_scope="memo" if key in {"gpu_annex_summary", "phase1_evidence_closure", "board_closure"} else "claim",
                affected_claim_ids=["family_recommendation", "simulator_dse_ranking_predictiveness"] if key == "stage_main_evidence" else ["family_recommendation", "simulator_dse_ranking_predictiveness", "cpu_fpga_vs_cpu_gpu", "lower_whole_node_power", "same_correctness_tolerance", "resident_offload_fallback_attribution"],
                affected_artifact_ref_ids=[result["artifact_ref_id"]],
                rationale=(
                    f"{artifact_label[key]} is comparison-ineligible because its normalized adjudicator identity tuple is missing required fields: {field_summary}."
                    if join_key_status == "join_key_missing"
                    else f"{artifact_label[key]} is comparison-ineligible because its normalized adjudicator identity tuple drifted from the DSE subject row on: {field_summary}."
                ),
            )
        )
    candidate_family = row_candidate_family(subject_row, label="dse_subject_row")
    runtime_family = row_runtime_projection_family(subject_row, label="dse_subject_row")
    if runtime_family is not None and candidate_family != runtime_family:
        blockers.append(
            build_blocker_record(
                blocker_id="blocker::candidate_runtime_split",
                blocker_class="provenance_ambiguity",
                precedence_category="structural_projection_evidence",
                severity="blocking",
                blocking_scope="claim",
                affected_claim_ids=[
                    "family_recommendation",
                    "cpu_fpga_vs_cpu_only",
                    "cpu_fpga_vs_cpu_gpu",
                    "lower_whole_node_power",
                    "same_correctness_tolerance",
                    "resident_offload_fallback_attribution",
                ],
                affected_artifact_ref_ids=[f"dse_subject_row::{subject_row['result_id']}"],
                rationale=(
                    f"Candidate identity {candidate_family} differs from runtime_projection_family {runtime_family}. "
                    "The runtime projection is evaluator metadata only, so it is recorded as support evidence but cannot unlock final/public architecture or performance claims."
                ),
            )
        )
    if subject_row.get("support_status") == "projection_only":
        blockers.append(
            build_blocker_record(
                blocker_id="blocker::projection_only_support",
                blocker_class="provenance_ambiguity",
                precedence_category="structural_projection_evidence",
                severity="blocking",
                blocking_scope="claim",
                affected_claim_ids=[
                    "family_recommendation",
                    "cpu_fpga_vs_cpu_only",
                    "cpu_fpga_vs_cpu_gpu",
                    "lower_whole_node_power",
                    "same_correctness_tolerance",
                    "resident_offload_fallback_attribution",
                ],
                affected_artifact_ref_ids=[f"dse_subject_row::{subject_row['result_id']}"],
                rationale="The selected DSE row is support_status=projection_only, so it remains Stage-A evidence and cannot unlock final/public architecture, performance, correctness, or board-power claims.",
            )
        )
    if row_executor_claim_allowed(subject_row) is False:
        blockers.append(
            build_blocker_record(
                blocker_id="blocker::executor_claim_disallowed",
                blocker_class="provenance_ambiguity",
                precedence_category="structural_projection_evidence",
                severity="blocking",
                blocking_scope="claim",
                affected_claim_ids=[
                    "family_recommendation",
                    "cpu_fpga_vs_cpu_only",
                    "cpu_fpga_vs_cpu_gpu",
                    "lower_whole_node_power",
                    "same_correctness_tolerance",
                    "resident_offload_fallback_attribution",
                ],
                affected_artifact_ref_ids=[f"dse_subject_row::{subject_row['result_id']}"],
                rationale="support_evidence.executor_claim_allowed=false is executor-path metadata only. It never grants public claim permission, and a false value blocks executor-backed final claim unlocking.",
            )
        )
    if not stage_a_context.get("gpu_ready", False):
        blockers.append(
            build_blocker_record(
                blocker_id="blocker::gpu_baseline_missing_or_deferred",
                blocker_class="gpu_baseline_missing_or_deferred",
                precedence_category="decisive_measured_gpu_baseline",
                severity="warning",
                blocking_scope="claim",
                affected_claim_ids=[
                    "cpu_fpga_vs_cpu_gpu",
                    "lower_whole_node_power",
                ],
                affected_artifact_ref_ids=["gpu_annex_summary::primary", "gpu_decisive_baseline_summary::primary"],
                rationale="No decisive measured GPU baseline is available for the normalized workload-group context, so comparative GPU and lower-whole-node-power claims remain blocked.",
            )
        )
    if stage_a_context["graph_projection_only"]:
        blockers.append(
            build_blocker_record(
                blocker_id="blocker::graph_projection_only",
                blocker_class="graph_projection_only",
                precedence_category="structural_projection_evidence",
                severity="blocking",
                blocking_scope="memo",
                affected_claim_ids=[
                    "family_recommendation",
                    "simulator_dse_ranking_predictiveness",
                    "resident_offload_fallback_attribution",
                ],
                affected_artifact_ref_ids=[f"dse_subject_row::{subject_row['result_id']}"],
                rationale="The available evidence is frontdoor/projection-only, so Stage A cannot support an internal shortlist family, must stay at a proxy-tier ceiling, and must forbid microarchitectural-causality or fallback-attribution language.",
            )
        )
    if not stage_a_context.get("workload_group_ready", False):
        blockers.append(
            build_blocker_record(
                blocker_id="blocker::workload_group_not_admissible",
                blocker_class="workload_group_not_admissible",
                precedence_category="correctness_convergence_integrity",
                severity="blocking",
                blocking_scope="workload_group",
                affected_claim_ids=[
                    "family_recommendation",
                    "cpu_fpga_vs_cpu_gpu",
                    "lower_whole_node_power",
                ],
                affected_artifact_ref_ids=["phase1_evidence_closure::primary", "gpu_annex_summary::primary"],
                rationale="Stage B requires workload-group admissibility and decisive-lane closure. A single strong case is not enough when the normalized workload-group closure is still incomplete or non-admissible.",
            )
        )
    if not stage_a_context.get("correctness_closed", False):
        blockers.append(
            build_blocker_record(
                blocker_id="blocker::correctness_mismatch",
                blocker_class="correctness_mismatch",
                precedence_category="correctness_convergence_integrity",
                severity="blocking",
                blocking_scope="claim",
                affected_claim_ids=[
                    "cpu_fpga_vs_cpu_only",
                    "cpu_fpga_vs_cpu_gpu",
                    "same_correctness_tolerance",
                ],
                affected_artifact_ref_ids=["phase1_evidence_closure::primary", "board_closure::primary"],
                rationale="Same-correctness closure is not yet closed on the normalized Stage B surfaces, so correctness-sensitive comparative claims remain blocked.",
            )
        )
    if not stage_a_context.get("convergence_closed", False):
        blockers.append(
            build_blocker_record(
                blocker_id="blocker::convergence_not_comparable",
                blocker_class="convergence_not_comparable",
                precedence_category="correctness_convergence_integrity",
                severity="blocking",
                blocking_scope="claim",
                affected_claim_ids=[
                    "cpu_fpga_vs_cpu_only",
                    "cpu_fpga_vs_cpu_gpu",
                    "same_correctness_tolerance",
                ],
                affected_artifact_ref_ids=["phase1_evidence_closure::primary", "board_closure::primary"],
                rationale="Convergence comparability is not yet closed under the frozen workload/accounting boundary, so end-to-end comparative claims remain blocked.",
            )
        )
    if stage == "stage_b" and not stage_a_context.get("board_validation_ready", False):
        blockers.append(
            build_blocker_record(
                blocker_id="blocker::observability_hard_gate_fail",
                blocker_class="observability_hard_gate_fail",
                precedence_category="measured_board_evidence",
                severity="blocking",
                blocking_scope="memo",
                affected_claim_ids=[
                    "family_recommendation",
                    "cpu_fpga_vs_cpu_only",
                    "cpu_fpga_vs_cpu_gpu",
                    "same_correctness_tolerance",
                    "resident_offload_fallback_attribution",
                ],
                affected_artifact_ref_ids=["board_closure::primary"],
                rationale="Stage B requires board-validated observability/correctness closure. Missing or non-passing board compare content keeps the memo below thesis-grade release authority.",
            )
        )
    if stage == "stage_b" and not stage_a_context.get("board_power_ready", False):
        blockers.append(
            build_blocker_record(
                blocker_id="blocker::power_boundary_open",
                blocker_class="power_boundary_open",
                precedence_category="measured_board_evidence",
                severity="blocking",
                blocking_scope="claim",
                affected_claim_ids=["lower_whole_node_power"],
                affected_artifact_ref_ids=["board_closure::primary"],
                rationale="Whole-node power closure is not yet claim-ready on the board evidence surface, so lower whole-node power must remain blocked even when timing looks favorable.",
            )
        )
    if stage == "stage_b" and not stage_a_context.get("ranking_stability_ready", False):
        blockers.append(
            build_blocker_record(
                blocker_id="blocker::ranking_instability",
                blocker_class="ranking_instability",
                precedence_category="measured_board_evidence",
                severity="blocking",
                blocking_scope="family",
                affected_claim_ids=["family_recommendation", "simulator_dse_ranking_predictiveness"],
                affected_artifact_ref_ids=["board_closure::primary", f"dse_subject_row::{subject_row['result_id']}"],
                rationale="Stage B recommendation authority requires ranking stability to survive into the board-validated closure surfaces.",
            )
        )
    return blockers


def build_gate_statuses(
    *,
    dse_bundle_path: Path,
    subject_row: dict[str, Any],
    gpu_annex: dict[str, Any] | None,
    phase1_closure: dict[str, Any] | None,
    board_closure: dict[str, Any] | None,
    stage_a_context: dict[str, Any],
    blocker_ids_by_class: dict[str, str],
) -> dict[str, Any]:
    graph_projection_blocker = blocker_ids_by_class.get("graph_projection_only")
    gpu_blocker = blocker_ids_by_class.get("gpu_baseline_missing_or_deferred")
    workload_blocker = blocker_ids_by_class.get("workload_group_not_admissible")
    correctness_blocker = blocker_ids_by_class.get("correctness_mismatch")
    convergence_blocker = blocker_ids_by_class.get("convergence_not_comparable")
    power_blocker = blocker_ids_by_class.get("power_boundary_open")
    observability_blocker = blocker_ids_by_class.get("observability_hard_gate_fail")
    ranking_blocker = blocker_ids_by_class.get("ranking_instability")
    stage = stage_a_context.get("stage", "stage_a")
    return {
        "input_manifest_bound": gate_status_entry(
            "pass",
            notes=[f"Loaded DSE bundle and normalized subject row from {dse_bundle_path}"] + stage_a_context.get("dse_subject_support_notes", [])
        ),
        "authority_cohort_resolved": gate_status_entry(
            "pass" if stage_a_context["trusted_family_candidate"] is not None else "deferred",
            blocking=stage_a_context["trusted_family_candidate"] is None,
            blocker_ids=[] if stage_a_context["trusted_family_candidate"] is not None or graph_projection_blocker is None else [graph_projection_blocker],
            notes=[
                f"Internal trusted shortlist family is {stage_a_context['trusted_family_candidate']}; Stage A still emits no public family recommendation."
            ] if stage_a_context["trusted_family_candidate"] is not None else [
                "No trusted_point_per_family survives at projection grade, so Stage A remains at a blocked/no-public-recommendation posture."
            ]
        ),
        "workload_group_admissible": gate_status_entry(
            "pass" if stage_a_context.get("workload_group_ready", False) else ("deferred" if stage == "stage_a" else "fail"),
            blocking=not stage_a_context.get("workload_group_ready", False) and stage == "stage_b",
            blocker_ids=[] if stage_a_context.get("workload_group_ready", False) or workload_blocker is None else [workload_blocker],
            notes=[
                "Normalized workload-group closure and GPU aggregation admissibility are closed for the subject case."
            ] if stage_a_context.get("workload_group_ready", False) else [
                "Workload-group closure is incomplete or non-admissible; Stage B must remain blocked even if one case looks decisive."
            ]
        ),
        "correctness_contract_closed": gate_status_entry(
            "pass" if stage_a_context.get("correctness_closed", False) else ("deferred" if stage == "stage_a" else "fail"),
            blocking=not stage_a_context.get("correctness_closed", False) and stage == "stage_b",
            blocker_ids=[] if stage_a_context.get("correctness_closed", False) or correctness_blocker is None else [correctness_blocker],
            notes=["Board compare and phase1 closure both support same-correctness closure for the subject case."] if stage_a_context.get("correctness_closed", False) else ["Same-correctness closure is not yet established on the normalized Stage B evidence surfaces."]
        ),
        "convergence_comparable": gate_status_entry(
            "pass" if stage_a_context.get("convergence_closed", False) else ("deferred" if stage == "stage_a" else "fail"),
            blocking=not stage_a_context.get("convergence_closed", False) and stage == "stage_b",
            blocker_ids=[] if stage_a_context.get("convergence_closed", False) or convergence_blocker is None else [convergence_blocker],
            notes=["Convergence comparability is closed for the normalized subject case and accounting boundary."] if stage_a_context.get("convergence_closed", False) else ["Convergence comparability remains open, so comparative time-to-solution claims cannot be promoted."]
        ),
        "gpu_baseline_ready": gate_status_entry(
            "pass" if stage_a_context.get("gpu_ready", False) else ("deferred" if stage == "stage_a" else "fail"),
            blocking=not stage_a_context.get("gpu_ready", False) and stage == "stage_b",
            blocker_ids=[] if stage_a_context.get("gpu_ready", False) or gpu_blocker is None else [gpu_blocker],
            notes=[f"Decisive GPU baseline is ready with modes: {', '.join(stage_a_context.get('gpu_decisive_modes', []))}."] if stage_a_context.get("gpu_ready", False) else ["No decisive measured GPU baseline is available for the normalized workload-group context."]
        ),
        "power_boundary_closed": gate_status_entry(
            "pass" if stage_a_context.get("board_power_ready", False) else ("deferred" if stage == "stage_a" else "fail"),
            blocking=not stage_a_context.get("board_power_ready", False) and stage == "stage_b",
            blocker_ids=[] if stage_a_context.get("board_power_ready", False) or power_blocker is None else [power_blocker],
            notes=["Board power confidence marks the whole-node power claim as ready."] if stage_a_context.get("board_power_ready", False) else ["Whole-node power closure is still open or downgraded on the board evidence surface."]
        ),
        "observability_hard_gates_pass": gate_status_entry(
            "pass" if stage_a_context.get("board_validation_ready", False) else ("deferred" if stage == "stage_a" else "fail"),
            blocking=not stage_a_context.get("board_validation_ready", False) and stage == "stage_b",
            blocker_ids=[] if stage_a_context.get("board_validation_ready", False) or observability_blocker is None else [observability_blocker],
            notes=["Board compare content satisfies the normalized observability / projection hard-gate requirements."] if stage_a_context.get("board_validation_ready", False) else ["Board observability hard gates are not yet closed on the normalized board compare surface."]
        ),
        "ranking_stability_pass": gate_status_entry(
            "pass" if stage_a_context.get("ranking_stability_ready", False) else ("deferred" if stage == "stage_a" else "fail"),
            blocking=not stage_a_context.get("ranking_stability_ready", False) and stage == "stage_b",
            blocker_ids=[] if stage_a_context.get("ranking_stability_ready", False) else ([ranking_blocker] if ranking_blocker is not None else ([graph_projection_blocker] if graph_projection_blocker is not None else [])),
            notes=["Projection-grade ranking support survives into the normalized board closure path."] if stage_a_context.get("ranking_stability_ready", False) else ["Ranking stability is not yet closed at thesis-grade authority."]
        ),
        "board_validation_available": gate_status_entry(
            "pass" if stage_a_context.get("board_validation_ready", False) else ("deferred" if stage == "stage_a" else "fail"),
            blocking=not stage_a_context.get("board_validation_ready", False) and stage == "stage_b",
            blocker_ids=[] if stage_a_context.get("board_validation_ready", False) or observability_blocker is None else [observability_blocker],
            notes=["Board validation is closed for the normalized subject case."] if stage_a_context.get("board_validation_ready", False) else ["Board validation artifact is missing or does not yet pass the normalized closure checks."]
        ),
    }


def build_divergence_summary(
    *,
    authority_family: str | None,
    comparison_family: str | None,
    contradiction_ids: list[str],
    authority_effect: str,
    summary: str,
) -> dict[str, Any]:
    if authority_family is None or comparison_family is None:
        status = "not_evaluable"
        contradiction_ids = []
        authority_effect = "not_applicable"
    elif authority_family == comparison_family:
        status = "aligned"
        contradiction_ids = []
        authority_effect = "aligned"
    else:
        status = "diverged"
    return {
        "status": status,
        "authority_family": authority_family,
        "comparison_family": comparison_family,
        "contradiction_ids": contradiction_ids,
        "authority_effect": authority_effect,
        "summary": summary,
    }


def build_comparison_scope(
    *,
    bundle: dict[str, Any],
    identity_tuple: dict[str, str],
    stage_a_context: dict[str, Any],
) -> dict[str, Any]:
    trusted_family_candidate = stage_a_context["trusted_family_candidate"]
    performance_family = stage_a_context["best_performance_family_candidate"]
    canonical_family_candidate = stage_a_context["canonical_family_candidate"]
    trusted_vs_performance_contradiction_ids = []
    if trusted_family_candidate is not None and performance_family is not None and trusted_family_candidate != performance_family:
        trusted_vs_performance_contradiction_ids = [TRUSTED_VS_PERFORMANCE_CONTRADICTION_ID]
    return {
        "normalized_identity_tuple": identity_tuple,
        "dse_subject_metadata": stage_a_context["dse_subject_metadata"],
        "evaluated_families": evaluated_families(bundle, identity_tuple=identity_tuple, include_family=False),
        "compared_cohorts": [
            "canonical_family_profile",
            "trusted_point_per_family",
            "best_performance_point",
        ],
        "authority_cohort": "trusted_point_per_family",
        "authority_fallback_rule": "no_recommendation_if_no_trusted_point_per_family_survives_hard_blocks",
        "trusted_family_candidate": trusted_family_candidate,
        "best_performance_family_candidate": performance_family,
        "authority_vs_canonical_divergence": build_divergence_summary(
            authority_family=trusted_family_candidate,
            comparison_family=canonical_family_candidate,
            contradiction_ids=[],
            authority_effect="reported_no_public_recommendation",
            summary="Stage A keeps the canonical family context visible as explain-only context. If it diverges from the trusted shortlist family, the memo reports the difference without naming a public winner.",
        ),
        "authority_vs_best_performance_divergence": build_divergence_summary(
            authority_family=trusted_family_candidate,
            comparison_family=performance_family,
            contradiction_ids=trusted_vs_performance_contradiction_ids,
            authority_effect="reported_no_public_recommendation",
            summary="Stage A keeps the raw best-performance family visible for tradeoff narration, but it does not become the public authority surface.",
        ),
        "trusted_vs_performance_divergence": build_divergence_summary(
            authority_family=trusted_family_candidate,
            comparison_family=performance_family,
            contradiction_ids=trusted_vs_performance_contradiction_ids,
            authority_effect="reported_no_public_recommendation",
            summary="Stage A may surface a trusted shortlist family for internal use, but if it diverges from the raw best-performance family the memo must report that tradeoff and still withhold any public family recommendation.",
        ),
    }


def build_confidence_summary(
    *,
    blockers: list[dict[str, Any]],
    overall_confidence: str,
    contradiction_ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    active_blocker_ids = [blocker["blocker_id"] for blocker in blockers if blocker["status"] == "active"]
    active_contradiction_ids = contradiction_ids_active(contradiction_ledger)
    if blockers:
        binding = min(blockers, key=lambda item: item["precedence_rank"])["precedence_category"]
    else:
        binding = "measured_board_evidence" if overall_confidence in {"conditional", "board_validated"} else ("calibrated_proxy_evidence" if overall_confidence == "bounded" else "structural_projection_evidence")
    return {
        "overall_confidence": overall_confidence,
        "confidence_ceiling_applied": overall_confidence,
        "binding_precedence_category": binding,
        "canonical_claim_permission_surface": "claim_matrix",
        "active_blocker_ids": active_blocker_ids,
        "active_contradiction_ids": active_contradiction_ids,
        "summary": "Claim permissions are derived from claim_matrix on the shared memo surface. Stage A stays bounded by projection-grade evidence, while Stage B may rise to conditional or board-validated confidence only when the normalized closure gates and measured surfaces genuinely pass.",
    }


def blocker_classes_for_claim(blocker_ledger: list[dict[str, Any]], claim_id: str) -> set[str]:
    return {
        str(blocker["blocker_class"])
        for blocker in blocker_ledger
        if blocker.get("status") == "active" and claim_id in blocker.get("affected_claim_ids", [])
    }


def evidence_tier_for_artifact_ref(artifact_ref_id: str) -> str:
    if artifact_ref_id == "gpu_annex_summary::primary" or artifact_ref_id == "gpu_decisive_baseline_summary::primary":
        return "gpu_baseline_measured"
    if artifact_ref_id == "phase1_evidence_closure::primary":
        return "closure_bound"
    if artifact_ref_id == "board_closure::primary":
        return "board_validated"
    return "provenance_only"


def build_claim_matrix(
    *,
    stage_a_context: dict[str, Any],
    contradiction_ledger: list[dict[str, Any]],
    blocker_ledger: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    claim_scope = {
        "family_recommendation": "family_decision",
        "simulator_dse_ranking_predictiveness": "predictiveness",
        "cpu_fpga_vs_cpu_only": "comparative_time_to_solution",
        "cpu_fpga_vs_cpu_gpu": "comparative_time_to_solution",
        "lower_whole_node_power": "comparative_power",
        "same_correctness_tolerance": "correctness_tolerance",
        "resident_offload_fallback_attribution": "policy_attribution",
    }
    public_claim_label = {
        "family_recommendation": "family_recommendation",
        "simulator_dse_ranking_predictiveness": "simulator_dse_ranking_predictiveness",
        "cpu_fpga_vs_cpu_only": "cpu_fpga_vs_cpu_only",
        "cpu_fpga_vs_cpu_gpu": "cpu_fpga_vs_cpu_gpu",
        "lower_whole_node_power": "lower_whole_node_power",
        "same_correctness_tolerance": "same_correctness_tolerance",
        "resident_offload_fallback_attribution": "microarchitectural_causality",
    }
    required_gate_ids = {
        "family_recommendation": ["authority_cohort_resolved", "gpu_baseline_ready", "board_validation_available"],
        "simulator_dse_ranking_predictiveness": ["input_manifest_bound", "ranking_stability_pass"],
        "cpu_fpga_vs_cpu_only": ["correctness_contract_closed", "convergence_comparable", "board_validation_available"],
        "cpu_fpga_vs_cpu_gpu": ["correctness_contract_closed", "convergence_comparable", "gpu_baseline_ready"],
        "lower_whole_node_power": ["power_boundary_closed", "board_validation_available"],
        "same_correctness_tolerance": ["correctness_contract_closed", "convergence_comparable"],
        "resident_offload_fallback_attribution": ["observability_hard_gates_pass", "board_validation_available"],
    }
    required_evidence_tiers = {
        "family_recommendation": ["board_validated"],
        "simulator_dse_ranking_predictiveness": ["projection_grade"],
        "cpu_fpga_vs_cpu_only": ["board_validated"],
        "cpu_fpga_vs_cpu_gpu": ["gpu_baseline_measured", "board_validated"],
        "lower_whole_node_power": ["whole_node_power_measured"],
        "same_correctness_tolerance": ["board_validated"],
        "resident_offload_fallback_attribution": ["board_validated"],
    }
    required_confidence = {
        "family_recommendation": "board_validated",
        "simulator_dse_ranking_predictiveness": "bounded",
        "cpu_fpga_vs_cpu_only": "board_validated",
        "cpu_fpga_vs_cpu_gpu": "conditional",
        "lower_whole_node_power": "board_validated",
        "same_correctness_tolerance": "board_validated",
        "resident_offload_fallback_attribution": "board_validated",
    }
    blocking_blockers = {
        "family_recommendation": ["join_key_missing", "join_key_drift", "workload_group_not_admissible", "gpu_baseline_missing_or_deferred"],
        "simulator_dse_ranking_predictiveness": ["join_key_missing", "join_key_drift", "ranking_instability", "graph_projection_only"],
        "cpu_fpga_vs_cpu_only": ["correctness_mismatch", "convergence_not_comparable"],
        "cpu_fpga_vs_cpu_gpu": ["correctness_mismatch", "convergence_not_comparable", "gpu_baseline_missing_or_deferred"],
        "lower_whole_node_power": ["power_boundary_open"],
        "same_correctness_tolerance": ["correctness_mismatch", "convergence_not_comparable"],
        "resident_offload_fallback_attribution": ["observability_hard_gate_fail", "provenance_ambiguity"],
    }
    rationale = {
        "family_recommendation": "Stage A may surface an internal trusted shortlist family in comparison_scope when projection-grade evidence supports it, but the public family_recommendation claim itself remains forbidden on the shared memo surface.",
        "simulator_dse_ranking_predictiveness": "Stage A may retain guarded predictiveness language only as bounded projection-grade or evidence-tradeoff narration; it never becomes final thesis authority.",
        "cpu_fpga_vs_cpu_only": "Comparative CPU+FPGA vs CPU-only thesis claims stay forbidden until later measured closure work lands.",
        "cpu_fpga_vs_cpu_gpu": "Comparative CPU+FPGA vs CPU+GPU claims stay forbidden until decisive GPU and board evidence closes on the same authority surface.",
        "lower_whole_node_power": "Whole-node power claims remain forbidden until the power boundary is closed with measured evidence.",
        "same_correctness_tolerance": "Same-correctness public claims remain forbidden until correctness/convergence closure is adjudicated from measured artifacts.",
        "resident_offload_fallback_attribution": "This claim is the Stage A microarchitectural-causality / fallback-attribution guardrail. It remains forbidden, and frontdoor-only evidence explicitly keeps it at no-public-claim status.",
    }
    required_decisive_gpu_baseline = {
        "family_recommendation": False,
        "simulator_dse_ranking_predictiveness": False,
        "cpu_fpga_vs_cpu_only": False,
        "cpu_fpga_vs_cpu_gpu": True,
        "lower_whole_node_power": True,
        "same_correctness_tolerance": False,
        "resident_offload_fallback_attribution": False,
    }
    required_board_validation = {
        "family_recommendation": True,
        "simulator_dse_ranking_predictiveness": False,
        "cpu_fpga_vs_cpu_only": True,
        "cpu_fpga_vs_cpu_gpu": True,
        "lower_whole_node_power": True,
        "same_correctness_tolerance": True,
        "resident_offload_fallback_attribution": True,
    }
    claim_matrix: list[dict[str, Any]] = []
    stage = stage_a_context.get("stage", "stage_a")
    predictiveness_ceiling = "board_validated_claim" if stage == "stage_b" and stage_a_context.get("ranking_stability_ready", False) else ("projection_grade_only" if stage_a_context["ranking_grade_support_present"] else "evidence_tradeoff_only")
    family_recommendation_resolved = stage_a_context.get("trusted_vs_performance_measured_resolution") in {"not_applicable", "aligned", "resolved_in_favor_of_trusted_family"}
    for claim_id in CLAIM_REGISTRY:
        permission = "guarded" if claim_id == "simulator_dse_ranking_predictiveness" else "forbidden"
        public_wording_ceiling = predictiveness_ceiling if claim_id == "simulator_dse_ranking_predictiveness" else "no_public_claim"
        if stage == "stage_b":
            if claim_id == "simulator_dse_ranking_predictiveness":
                permission = "allowed"
                public_wording_ceiling = "board_validated_claim"
            elif claim_id == "family_recommendation" and stage_a_context.get("board_validation_ready", False) and family_recommendation_resolved:
                permission = "allowed"
                public_wording_ceiling = "board_validated_claim"
            elif claim_id == "family_recommendation" and stage_a_context.get("board_validation_ready", False):
                permission = "guarded"
                public_wording_ceiling = "evidence_tradeoff_only"
            elif claim_id == "same_correctness_tolerance" and stage_a_context.get("correctness_closed", False) and stage_a_context.get("convergence_closed", False) and stage_a_context.get("board_validation_ready", False):
                permission = "allowed"
                public_wording_ceiling = "board_validated_claim"
            elif claim_id == "resident_offload_fallback_attribution" and stage_a_context.get("board_validation_ready", False):
                permission = "allowed"
                public_wording_ceiling = "board_validated_claim"
            elif claim_id == "cpu_fpga_vs_cpu_gpu" and stage_a_context.get("gpu_ready", False) and stage_a_context.get("correctness_closed", False) and stage_a_context.get("convergence_closed", False) and stage_a_context.get("board_validation_ready", False) and stage_a_context.get("workload_group_ready", False):
                permission = "allowed"
                public_wording_ceiling = "conditional_comparative_claim"
            elif claim_id == "lower_whole_node_power" and stage_a_context.get("gpu_ready", False) and stage_a_context.get("board_power_ready", False) and stage_a_context.get("board_validation_ready", False) and stage_a_context.get("workload_group_ready", False):
                permission = "allowed"
                public_wording_ceiling = "board_validated_claim"
        active_blocker_classes = blocker_classes_for_claim(blocker_ledger, claim_id)
        if "join_key_missing" in active_blocker_classes or "join_key_drift" in active_blocker_classes:
            if claim_id == "simulator_dse_ranking_predictiveness":
                permission = "guarded"
                public_wording_ceiling = "evidence_tradeoff_only"
            else:
                permission = "forbidden"
                public_wording_ceiling = "no_public_claim"
        claim_matrix.append(
            {
                "claim_id": claim_id,
                "public_claim_label": public_claim_label[claim_id],
                "permission": permission,
                "claim_scope": claim_scope[claim_id],
                "public_wording_ceiling": public_wording_ceiling,
                "required_gate_ids": required_gate_ids[claim_id],
                "required_evidence_tiers": required_evidence_tiers[claim_id],
                "required_confidence_level": required_confidence[claim_id],
                "blocking_blocker_classes": blocking_blockers[claim_id],
                "required_decisive_gpu_baseline": required_decisive_gpu_baseline[claim_id],
                "required_board_validation": required_board_validation[claim_id],
                "contradiction_ids": contradiction_ids_for_claim(contradiction_ledger, claim_id),
                "trusted_vs_performance_divergence_sensitive": claim_id == "family_recommendation",
                "rationale": rationale[claim_id],
            }
        )
    return claim_matrix


def derive_claim_lists(claim_matrix: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    allowed_claims: list[str] = []
    guarded_claims: list[str] = []
    forbidden_claims: list[str] = []
    for claim in claim_matrix:
        permission = claim["permission"]
        claim_id = claim["claim_id"]
        if permission == "allowed":
            allowed_claims.append(claim_id)
        elif permission == "guarded":
            guarded_claims.append(claim_id)
        elif permission == "forbidden":
            forbidden_claims.append(claim_id)
        else:
            raise AdjudicatorRunError(f"unsupported claim permission: {permission}")
    return allowed_claims, guarded_claims, forbidden_claims


def build_contradiction_ledger(*, stage_a_context: dict[str, Any]) -> list[dict[str, Any]]:
    trusted_family_candidate = stage_a_context["trusted_family_candidate"]
    best_performance_family_candidate = stage_a_context["best_performance_family_candidate"]
    if trusted_family_candidate is None or best_performance_family_candidate is None:
        return []
    if trusted_family_candidate == best_performance_family_candidate:
        return []
    return [
        {
            "contradiction_id": TRUSTED_VS_PERFORMANCE_CONTRADICTION_ID,
            "contradiction_class": "trusted_vs_performance_divergence",
            "precedence_category": "structural_projection_evidence",
            "precedence_rank": BLOCKER_PRECEDENCE["structural_projection_evidence"],
            "severity": "advisory",
            "status": "acknowledged",
            "authority_cohort": "trusted_point_per_family",
            "comparison_cohort": "best_performance_point",
            "affected_claim_ids": ["family_recommendation"],
            "summary": f"Trusted shortlist family {trusted_family_candidate} diverges from raw best-performance family {best_performance_family_candidate}; the memo must keep recommendation authority bound to trusted_point_per_family and withhold public family selection until measured evidence resolves the divergence in favor of the trusted family.",
            "resolution_rule": "Stage A reports the tradeoff with no public winner. Stage B may select the trusted family only after measured board or whole-node evidence resolves the divergence in favor of the trusted family.",
        }
    ]


def contradiction_ids_active(contradiction_ledger: list[dict[str, Any]]) -> list[str]:
    return [
        contradiction["contradiction_id"]
        for contradiction in contradiction_ledger
        if contradiction.get("status") in {"active", "acknowledged"}
    ]


def contradiction_ids_for_claim(contradiction_ledger: list[dict[str, Any]], claim_id: str) -> list[str]:
    return [
        contradiction["contradiction_id"]
        for contradiction in contradiction_ledger
        if contradiction.get("status") in {"active", "acknowledged"}
        and claim_id in contradiction.get("affected_claim_ids", [])
    ]


def trusted_vs_performance_divergence_active(contradiction_ledger: list[dict[str, Any]]) -> bool:
    return TRUSTED_VS_PERFORMANCE_CONTRADICTION_ID in contradiction_ids_active(contradiction_ledger)


def build_evidence_ledger(
    *,
    dse_bundle_path: Path,
    subject_row: dict[str, Any],
    family_summary: dict[str, Any],
    artifact_join_key_results: dict[str, dict[str, Any]],
    gpu_annex: dict[str, Any] | None,
    phase1_closure: dict[str, Any] | None,
    stage_main_evidence: dict[str, Any] | None,
    board_closure: dict[str, Any] | None,
    blocker_ledger: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    family = normalize_family_value(family_summary.get("family"), label="family_summary")
    blocker_classes_by_artifact_ref: dict[str, list[str]] = {}
    for blocker in blocker_ledger:
        if blocker.get("status") != "active":
            continue
        for artifact_ref_id in blocker.get("affected_artifact_ref_ids", []):
            blocker_classes_by_artifact_ref.setdefault(str(artifact_ref_id), []).append(str(blocker["blocker_class"]))

    def evidence_admissibility(artifact_ref_id: str, default: str) -> str:
        join_key_status = artifact_join_key_results.get(artifact_ref_id.replace("::primary", ""), {}).get("join_key_status")
        if join_key_status in {"join_key_missing", "join_key_drift"}:
            return "comparison_ineligible"
        return default

    def evidence_tier_with_join_key(
        artifact_ref_id: str,
        default_tier: str,
        artifact_present: bool,
    ) -> str:
        if not artifact_present:
            return "provenance_only"
        join_key_status = artifact_join_key_results.get(artifact_ref_id.replace("::primary", ""), {}).get("join_key_status")
        if join_key_status in {"join_key_missing", "join_key_drift"}:
            return "provenance_only"
        return default_tier

    ledger = [
        {
            "evidence_id": "evidence::dse_subject_row",
            "evidence_surface": "dse_result_row",
            "artifact_ref_id": f"dse_subject_row::{subject_row['result_id']}",
            "evidence_tier": dse_evidence_tier(subject_row),
            "source_kind": subject_row.get("source_kind"),
            "admissibility": "supporting_only",
            "related_claim_ids": ["simulator_dse_ranking_predictiveness"],
            "blocker_classes_if_limiting": sorted(set(([] if dse_projection_grade_ready(subject_row) else (["graph_projection_only"] if not dse_ranking_ready(subject_row) else [])) + blocker_classes_by_artifact_ref.get(f"dse_subject_row::{subject_row['result_id']}", []))),
            "notes": [f"Loaded subject row from {dse_bundle_path}"] + dse_subject_support_notes(subject_row),
        },
        {
            "evidence_id": "evidence::family_summary_context",
            "evidence_surface": "family_summary_context",
            "artifact_ref_id": f"family_summary_context::{family}",
            "evidence_tier": "graph_projection_only",
            "source_kind": subject_row.get("source_kind"),
            "admissibility": "explain_only",
            "related_claim_ids": ["family_recommendation", "simulator_dse_ranking_predictiveness"],
            "blocker_classes_if_limiting": ["graph_projection_only"],
            "notes": ["family_summary is loaded as advisory family-only context, not as recommendation authority."],
        },
        {
            "evidence_id": "evidence::gpu_annex_summary",
            "evidence_surface": "gpu_annex_summary",
            "artifact_ref_id": "gpu_annex_summary::primary",
            "evidence_tier": evidence_tier_with_join_key("gpu_annex_summary::primary", "gpu_baseline_measured", gpu_annex is not None),
            "source_kind": infer_optional_source_kind("gpu_annex", gpu_annex),
            "admissibility": evidence_admissibility("gpu_annex_summary::primary", "supporting_only" if gpu_annex is not None else "explain_only"),
            "related_claim_ids": ["cpu_fpga_vs_cpu_gpu", "lower_whole_node_power"],
            "blocker_classes_if_limiting": blocker_classes_by_artifact_ref.get("gpu_annex_summary::primary", ([] if gpu_annex is not None else ["gpu_baseline_missing_or_deferred"])),
            "notes": ["gpu_annex loaded"] if gpu_annex is not None else ["gpu_annex was not supplied; Stage A output remains structurally valid but blocked/no-recommendation."],
        },
        {
            "evidence_id": "evidence::gpu_decisive_baseline_summary",
            "evidence_surface": "gpu_decisive_baseline_summary",
            "artifact_ref_id": "gpu_decisive_baseline_summary::primary",
            "evidence_tier": evidence_tier_with_join_key("gpu_decisive_baseline_summary::primary", "gpu_baseline_measured", gpu_annex is not None),
            "source_kind": infer_optional_source_kind("gpu_annex", gpu_annex),
            "admissibility": evidence_admissibility("gpu_decisive_baseline_summary::primary", "explain_only"),
            "related_claim_ids": ["cpu_fpga_vs_cpu_gpu", "lower_whole_node_power"],
            "blocker_classes_if_limiting": blocker_classes_by_artifact_ref.get("gpu_decisive_baseline_summary::primary", ([] if gpu_annex is not None else ["gpu_baseline_missing_or_deferred"])),
            "notes": ["gpu decisive baseline is not yet split into its own artifact; the runner reuses the normalized gpu_annex surface as an advisory placeholder."] if gpu_annex is not None else ["gpu decisive baseline summary is deferred until a normalized decisive-baseline artifact exists."],
        },
        {
            "evidence_id": "evidence::phase1_evidence_closure",
            "evidence_surface": "phase1_evidence_closure",
            "artifact_ref_id": "phase1_evidence_closure::primary",
            "evidence_tier": evidence_tier_with_join_key("phase1_evidence_closure::primary", "closure_bound", phase1_closure is not None),
            "source_kind": infer_optional_source_kind("phase1_closure", phase1_closure),
            "admissibility": evidence_admissibility("phase1_evidence_closure::primary", "supporting_only" if phase1_closure is not None else "explain_only"),
            "related_claim_ids": ["family_recommendation", "same_correctness_tolerance"],
            "blocker_classes_if_limiting": blocker_classes_by_artifact_ref.get("phase1_evidence_closure::primary", []),
            "notes": ["phase1_evidence_closure loaded"] if phase1_closure is not None else ["phase1_evidence_closure not supplied to the runner boundary."],
        },
        {
            "evidence_id": "evidence::stage_main_evidence",
            "evidence_surface": "stage_main_recommendation_evidence",
            "artifact_ref_id": "stage_main_evidence::primary",
            "evidence_tier": evidence_tier_with_join_key("stage_main_evidence::primary", "provenance_only", stage_main_evidence is not None),
            "source_kind": infer_optional_source_kind("stage_main_evidence", stage_main_evidence),
            "admissibility": evidence_admissibility("stage_main_evidence::primary", "explain_only"),
            "related_claim_ids": ["family_recommendation"],
            "blocker_classes_if_limiting": blocker_classes_by_artifact_ref.get("stage_main_evidence::primary", []),
            "notes": ["stage-main recommendation evidence is intentionally left deferred in this task scope."],
        },
    ]
    if board_closure is not None:
        ledger.append(
            {
                "evidence_id": "evidence::board_closure",
                "evidence_surface": "board_compare",
                "artifact_ref_id": "board_closure::primary",
                "evidence_tier": evidence_tier_with_join_key("board_closure::primary", "board_validated", True),
                "source_kind": infer_optional_source_kind("board_closure", board_closure),
                "admissibility": evidence_admissibility("board_closure::primary", "supporting_only"),
                "related_claim_ids": ["same_correctness_tolerance", "resident_offload_fallback_attribution"],
                "blocker_classes_if_limiting": blocker_classes_by_artifact_ref.get("board_closure::primary", []),
                "notes": ["board_closure is loaded only as an optional normalized artifact placeholder in this runner-boundary task."],
            }
        )
    return ledger


def build_next_actions(
    *,
    gpu_annex: dict[str, Any] | None,
    phase1_closure: dict[str, Any] | None,
    board_closure: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    actions = [
        {
            "action_id": "action::collect_gpu_annex",
            "priority": "high",
            "action_type": "collect_artifact",
            "target_surface": "gpu_annex_summary",
            "unblocks_claim_ids": ["cpu_fpga_vs_cpu_gpu", "lower_whole_node_power"],
            "unblocks_blocker_classes": ["gpu_baseline_missing_or_deferred"],
            "description": "Load a normalized gpu_annex summary to narrow GPU-comparative blockers while keeping Stage A on the shared memo surface.",
        },
        {
            "action_id": "action::collect_phase1_closure",
            "priority": "high",
            "action_type": "collect_artifact",
            "target_surface": "phase1_evidence_closure",
            "unblocks_claim_ids": ["family_recommendation", "same_correctness_tolerance"],
            "unblocks_blocker_classes": [],
            "description": "Load the normalized phase1_evidence_closure report so later tasks can close correctness and convergence gates without changing the Stage A memo shape.",
        },
        {
            "action_id": "action::collect_board_closure",
            "priority": "medium",
            "action_type": "collect_artifact",
            "target_surface": "board_closure",
            "unblocks_claim_ids": ["family_recommendation", "resident_offload_fallback_attribution"],
            "unblocks_blocker_classes": ["observability_hard_gate_fail", "power_boundary_open"],
            "description": "Supply normalized board evidence only when later Stage B claim logic needs board-validated or observability-grounded authority.",
        },
    ]
    if gpu_annex is not None:
        actions[0]["description"] = "GPU annex is already loaded; later tasks can use it to resolve decisive-GPU-baseline and fairness closure beyond Stage A."
        actions[0]["priority"] = "medium"
        actions[0]["action_type"] = "schema_followup"
    if phase1_closure is not None:
        actions[1]["description"] = "Phase-1 closure is already loaded; the next follow-on task can consume it for real blocker and contradiction resolution."
        actions[1]["priority"] = "medium"
        actions[1]["action_type"] = "schema_followup"
    if board_closure is not None:
        actions[2]["description"] = "Board closure is already loaded as optional evidence; later tasks can promote it into measured blocker and claim-permission logic."
        actions[2]["action_type"] = "schema_followup"
    return actions


def determine_decision(
    *,
    stage_a_context: dict[str, Any],
    claim_matrix: list[dict[str, Any]],
    blocker_ledger: list[dict[str, Any]],
    contradiction_ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    trusted_family_candidate = stage_a_context["trusted_family_candidate"]
    best_performance_family_candidate = stage_a_context["best_performance_family_candidate"]
    stage = stage_a_context.get("stage", "stage_a")
    permissions = {item["claim_id"]: item["permission"] for item in claim_matrix}
    has_trusted_performance_divergence = trusted_vs_performance_divergence_active(contradiction_ledger)
    if trusted_family_candidate is None:
        status = "blocked"
        public_family_decision_status = "blocked"
        release_posture = "blocked"
        blocked_by_blocker_ids = [blocker["blocker_id"] for blocker in blocker_ledger if blocker["status"] == "active"]
        trusted_vs_performance_resolution = "not_applicable"
        summary = "Stage A remains blocked because the available DSE evidence is still frontdoor/graph-projection only. The memo records the graph_projection_only limitation, caps wording at proxy-tier tradeoff narration, and keeps microarchitectural-causality claims forbidden."
    elif stage == "stage_b":
        status = "claim_ready"
        blocked_by_blocker_ids = [blocker["blocker_id"] for blocker in blocker_ledger if blocker["status"] == "active"]
        trusted_vs_performance_resolution = (
            stage_a_context["trusted_vs_performance_measured_resolution"]
            if has_trusted_performance_divergence
            else "aligned"
        )
        join_key_blocker_active = any(
            blocker["blocker_class"] in {"join_key_missing", "join_key_drift"}
            for blocker in blocker_ledger
            if blocker["status"] == "active"
        )
        divergence_resolved = (
            not has_trusted_performance_divergence
            or trusted_vs_performance_resolution == "resolved_in_favor_of_trusted_family"
        )
        recommended_family = (
            trusted_family_candidate
            if permissions.get("family_recommendation") == "allowed" and divergence_resolved and not join_key_blocker_active
            else None
        )
        public_family_decision_status = "family_selected" if recommended_family is not None else "conditional_recommendation"
        release_posture = "board_validated_public_memo" if stage_a_context.get("board_power_ready", False) and permissions.get("lower_whole_node_power") == "allowed" else "conditional_public_memo"
        if has_trusted_performance_divergence and trusted_vs_performance_resolution != "resolved_in_favor_of_trusted_family":
            summary = (
                f"Stage B closure gates pass for trusted family {trusted_family_candidate}, but measured evidence has not resolved the trusted-vs-performance divergence against faster family {best_performance_family_candidate}. "
                "The memo therefore remains conditional and withholds public family selection until measured board or whole-node evidence resolves the divergence in favor of the trusted family."
            )
        elif join_key_blocker_active:
            summary = (
                f"Stage B closure artifacts are present for trusted family {trusted_family_candidate}, but one or more required artifact-side identity joins are comparison-ineligible. "
                "The memo remains conditional until the normalized adjudicator identity tuple matches across the required closure artifacts."
            )
        else:
            summary = f"Stage B is activated on the shared memo surface because decisive GPU baseline, phase1 closure, board closure, ranking stability, and workload-group admissibility all pass for {trusted_family_candidate}. Comparative GPU and whole-node-power claims are only unlocked where the normalized closure artifacts keep their blockers absent."
        return {
            "status": status,
            "public_family_decision_status": public_family_decision_status,
            "recommended_family": recommended_family,
            "release_posture": release_posture,
            "decision_confidence": stage_a_context["overall_confidence"],
            "blocked_by_blocker_ids": blocked_by_blocker_ids,
            "contradiction_ids": [item["contradiction_id"] for item in contradiction_ledger],
            "authority_vs_canonical_divergence_reported": trusted_family_candidate is not None and trusted_family_candidate != stage_a_context["canonical_family_candidate"],
            "authority_vs_best_performance_divergence_reported": trusted_family_candidate is not None and best_performance_family_candidate is not None and trusted_family_candidate != best_performance_family_candidate,
            "trusted_vs_performance_divergence_reported": has_trusted_performance_divergence,
            "trusted_vs_performance_resolution": trusted_vs_performance_resolution,
            "summary": summary,
        }
    else:
        status = "evidence_bounded"
        public_family_decision_status = "no_recommendation"
        release_posture = "bounded_projection_grade_public_memo"
        blocked_by_blocker_ids = []
        if best_performance_family_candidate is None:
            trusted_vs_performance_resolution = "not_applicable"
            summary = f"Stage A identifies {trusted_family_candidate} as the internal trusted shortlist family from projection-grade evidence, but public family recommendation remains forbidden on the shared memo surface."
        elif best_performance_family_candidate == trusted_family_candidate:
            trusted_vs_performance_resolution = "aligned"
            summary = f"Stage A identifies {trusted_family_candidate} as the internal trusted shortlist family, and it aligns with the raw best-performance family. Public recommendation still remains forbidden, so the memo stays at bounded projection-grade posture only."
        else:
            trusted_vs_performance_resolution = "reported_no_public_recommendation"
            summary = f"Stage A identifies {trusted_family_candidate} as the internal trusted shortlist family while {best_performance_family_candidate} remains the raw best-performance family. The memo reports that divergence explicitly and still issues no public family recommendation."
    return {
        "status": status,
        "public_family_decision_status": public_family_decision_status,
        "recommended_family": None,
        "release_posture": release_posture,
        "decision_confidence": stage_a_context["overall_confidence"],
        "blocked_by_blocker_ids": blocked_by_blocker_ids,
        "contradiction_ids": [item["contradiction_id"] for item in contradiction_ledger],
        "authority_vs_canonical_divergence_reported": trusted_family_candidate is not None and trusted_family_candidate != stage_a_context["canonical_family_candidate"],
        "authority_vs_best_performance_divergence_reported": trusted_family_candidate is not None and best_performance_family_candidate is not None and trusted_family_candidate != best_performance_family_candidate,
        "trusted_vs_performance_divergence_reported": has_trusted_performance_divergence,
        "trusted_vs_performance_resolution": trusted_vs_performance_resolution,
        "summary": summary,
    }


def build_memo_metadata(subject_row: dict[str, Any], dse_bundle_path: Path, *, stage: str) -> dict[str, Any]:
    return {
        "memo_id": f"{stage}::{dse_bundle_path.stem}::{subject_row['result_id']}",
        "stage": stage,
        "memo_schema_shared_across_stages": True,
        "public_authority_surface": "adjudicator",
        "claim_registry": CLAIM_REGISTRY,
        "canonical_claim_permission_surface": "claim_matrix",
        "evidence_tier_taxonomy": [
            "graph_projection_only",
            "projection_grade",
            "closure_bound",
            "gpu_baseline_measured",
            "board_validated",
            "whole_node_power_measured",
            "provenance_only",
        ],
        "confidence_taxonomy": [
            "exploratory",
            "bounded",
            "conditional",
            "decision_grade",
            "board_validated",
        ],
        "claim_permission_taxonomy": ["allowed", "guarded", "forbidden"],
        "blocker_class_taxonomy": [
            "join_key_missing",
            "join_key_drift",
            "correctness_mismatch",
            "convergence_not_comparable",
            "gpu_baseline_missing_or_deferred",
            "power_boundary_open",
            "observability_hard_gate_fail",
            "ranking_instability",
            "workload_group_not_admissible",
            "graph_projection_only",
            "provenance_ambiguity",
        ],
        "blocker_severity_taxonomy": ["advisory", "warning", "blocking", "hard_block"],
    }


def build_activation(
    *,
    dse_bundle_path: Path,
    subject_row: dict[str, Any],
    gpu_annex: dict[str, Any] | None,
    phase1_closure: dict[str, Any] | None,
    board_closure: dict[str, Any] | None,
    stage_a_context: dict[str, Any],
    blocker_ids_by_class: dict[str, str],
) -> dict[str, Any]:
    stage = stage_a_context.get("stage", "stage_a")
    gate_statuses = build_gate_statuses(
        dse_bundle_path=dse_bundle_path,
        subject_row=subject_row,
        gpu_annex=gpu_annex,
        phase1_closure=phase1_closure,
        board_closure=board_closure,
        stage_a_context=stage_a_context,
        blocker_ids_by_class=blocker_ids_by_class,
    )
    if stage == "stage_b":
        unlocked_claim_ids = [
            "family_recommendation",
            "simulator_dse_ranking_predictiveness",
            "same_correctness_tolerance",
            "resident_offload_fallback_attribution",
            *STAGE_B_UNLOCKABLE_CLAIMS,
        ]
        stage_forbidden_claim_ids = [claim_id for claim_id in CLAIM_REGISTRY if claim_id not in unlocked_claim_ids]
        allowed_release_postures = [
            "blocked",
            "no_public_recommendation",
            "conditional_public_memo",
            "board_validated_public_memo",
        ]
        evidence_tier_ceiling = "whole_node_power_measured" if stage_a_context.get("board_power_ready", False) else "board_validated"
        confidence_ceiling = stage_a_context["overall_confidence"]
        activation_mode = "stage_b_closure_bound"
    else:
        stage_forbidden_claim_ids = STAGE_A_FORBIDDEN_CLAIMS
        unlocked_claim_ids = ["simulator_dse_ranking_predictiveness"]
        allowed_release_postures = [
            "blocked",
            "no_public_recommendation",
            "bounded_projection_grade_public_memo",
        ]
        evidence_tier_ceiling = "gpu_baseline_measured"
        confidence_ceiling = "bounded"
        activation_mode = "stage_a_projection_grade"
    return {
        "stage": stage,
        "shared_schema": True,
        "activation_mode": activation_mode,
        "evidence_tier_ceiling": evidence_tier_ceiling,
        "confidence_ceiling": confidence_ceiling,
        "gate_statuses": gate_statuses,
        "stage_forbidden_claim_ids": stage_forbidden_claim_ids,
        "allowed_release_postures": allowed_release_postures,
        "unlocked_claim_ids": unlocked_claim_ids,
    }


def build_stage_a_memo(
    *,
    dse_bundle_path: Path,
    dse_bundle: dict[str, Any],
    gpu_annex: dict[str, Any] | None,
    phase1_closure: dict[str, Any] | None,
    board_closure: dict[str, Any] | None,
    stage_main_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    subject_row = select_subject_row(dse_bundle)
    identity_tuple = build_normalized_identity_tuple(subject_row)
    family_summary = family_summary_for(dse_bundle, identity_tuple["family"])
    artifact_join_key_results = build_artifact_join_key_results(
        identity_tuple=identity_tuple,
        gpu_annex=gpu_annex,
        phase1_closure=phase1_closure,
        board_closure=board_closure,
        stage_main_evidence=stage_main_evidence,
    )
    stage_a_context = build_stage_context(
        bundle=dse_bundle,
        subject_row=subject_row,
        identity_tuple=identity_tuple,
        artifact_join_key_results=artifact_join_key_results,
        gpu_annex=gpu_annex,
        phase1_closure=phase1_closure,
        board_closure=board_closure,
    )
    blocker_ledger = build_blocker_ledger(
        subject_row=subject_row,
        stage_a_context=stage_a_context,
        artifact_join_key_results=artifact_join_key_results,
        gpu_annex=gpu_annex,
    )
    blocker_ids_by_class = {blocker["blocker_class"]: blocker["blocker_id"] for blocker in blocker_ledger}
    contradiction_ledger = build_contradiction_ledger(stage_a_context=stage_a_context)
    claim_matrix = build_claim_matrix(
        stage_a_context=stage_a_context,
        contradiction_ledger=contradiction_ledger,
        blocker_ledger=blocker_ledger,
    )
    allowed_claims, guarded_claims, forbidden_claims = derive_claim_lists(claim_matrix)
    memo = {
        "schema_version": MEMO_SCHEMA_VERSION,
        "memo_kind": MEMO_KIND,
        "generated_at_utc": iso_utc_now(),
        "authority_contract_id": AUTHORITY_CONTRACT_ID,
        "input_manifest_contract_id": INPUT_MANIFEST_CONTRACT_ID,
        "memo_metadata": build_memo_metadata(subject_row, dse_bundle_path, stage=stage_a_context["stage"]),
        "input_artifact_manifest": build_input_artifact_manifest(
            dse_bundle_path=dse_bundle_path,
            dse_bundle=dse_bundle,
            subject_row=subject_row,
            identity_tuple=identity_tuple,
            artifact_join_key_results=artifact_join_key_results,
            gpu_annex=gpu_annex,
            phase1_closure=phase1_closure,
            stage_main_evidence=stage_main_evidence,
            board_closure=board_closure,
        ),
        "policy": build_policy_surface(),
        "activation": build_activation(
            dse_bundle_path=dse_bundle_path,
            subject_row=subject_row,
            gpu_annex=gpu_annex,
            phase1_closure=phase1_closure,
            board_closure=board_closure,
            stage_a_context=stage_a_context,
            blocker_ids_by_class=blocker_ids_by_class,
        ),
        "comparison_scope": build_comparison_scope(
            bundle=dse_bundle,
            identity_tuple=identity_tuple,
            stage_a_context=stage_a_context,
        ),
        "confidence_summary": build_confidence_summary(
            blockers=blocker_ledger,
            overall_confidence=stage_a_context["overall_confidence"],
            contradiction_ledger=contradiction_ledger,
        ),
        "evidence_ledger": build_evidence_ledger(
            dse_bundle_path=dse_bundle_path,
            subject_row=subject_row,
            family_summary=family_summary,
            artifact_join_key_results=artifact_join_key_results,
            gpu_annex=gpu_annex,
            phase1_closure=phase1_closure,
            stage_main_evidence=stage_main_evidence,
            board_closure=board_closure,
            blocker_ledger=blocker_ledger,
        ),
        "claim_matrix": claim_matrix,
        "blocker_ledger": blocker_ledger,
        "contradiction_ledger": contradiction_ledger,
        "allowed_claims": allowed_claims,
        "guarded_claims": guarded_claims,
        "forbidden_claims": forbidden_claims,
        "decision": determine_decision(
            stage_a_context=stage_a_context,
            claim_matrix=claim_matrix,
            blocker_ledger=blocker_ledger,
            contradiction_ledger=contradiction_ledger,
        ),
        "next_actions": build_next_actions(
            gpu_annex=gpu_annex,
            phase1_closure=phase1_closure,
            board_closure=board_closure,
        ),
        "notes": [
            "This runner stays on the single adjudicator memo surface: Stage A and Stage B differ only through activation gates and claim permissions, not through a second schema.",
            "claim_matrix is the canonical claim-permission surface; allowed/guarded/forbidden summary lists are derived from it for readability only.",
            "stage_main recommendation evidence remains an input surface only; the adjudicator memo itself is the authority surface for release posture and claim unlocking.",
            "DSE support_evidence.executor_claim_allowed is executor-path metadata only; final/public claim permission is always determined by adjudicator stage gates and claim_matrix.",
            *stage_a_context.get("dse_subject_support_notes", []),
        ],
    }
    validate_memo_invariants(memo)
    validate_against_schema_if_available(memo, ADJUDICATOR_SCHEMA_PATH)
    return memo


def validate_memo_invariants(memo: dict[str, Any]) -> None:
    required_top_level = [
        "schema_version",
        "memo_kind",
        "generated_at_utc",
        "authority_contract_id",
        "input_manifest_contract_id",
        "memo_metadata",
        "input_artifact_manifest",
        "policy",
        "activation",
        "comparison_scope",
        "confidence_summary",
        "evidence_ledger",
        "claim_matrix",
        "blocker_ledger",
        "contradiction_ledger",
        "allowed_claims",
        "guarded_claims",
        "forbidden_claims",
        "decision",
        "next_actions",
    ]
    for key in required_top_level:
        require(key in memo, f"memo missing required top-level field: {key}")
    require(memo["schema_version"] == MEMO_SCHEMA_VERSION, "memo schema_version mismatch")
    require(memo["memo_kind"] == MEMO_KIND, "memo kind mismatch")
    require(memo["authority_contract_id"] == AUTHORITY_CONTRACT_ID, "authority contract mismatch")
    require(memo["input_manifest_contract_id"] == INPUT_MANIFEST_CONTRACT_ID, "input manifest contract mismatch")
    require(memo["memo_metadata"]["canonical_claim_permission_surface"] == "claim_matrix", "memo metadata canonical claim surface mismatch")
    require(memo["policy"]["canonical_claim_permission_surface"] == "claim_matrix", "policy canonical claim surface mismatch")
    require(memo["confidence_summary"]["canonical_claim_permission_surface"] == "claim_matrix", "confidence canonical claim surface mismatch")
    activation = memo["activation"]
    require(activation["stage"] == memo["memo_metadata"]["stage"], "metadata/activation stage mismatch")
    claim_ids = [item["claim_id"] for item in memo["claim_matrix"]]
    require(claim_ids == CLAIM_REGISTRY, "claim_matrix registry order mismatch")
    allowed_claims, guarded_claims, forbidden_claims = derive_claim_lists(memo["claim_matrix"])
    require(memo["allowed_claims"] == allowed_claims, "allowed_claims must be derived from claim_matrix")
    require(memo["guarded_claims"] == guarded_claims, "guarded_claims must be derived from claim_matrix")
    require(memo["forbidden_claims"] == forbidden_claims, "forbidden_claims must be derived from claim_matrix")
    permissions = {item["claim_id"]: item["permission"] for item in memo["claim_matrix"]}
    decision = memo["decision"]
    stage = activation["stage"]
    comparison_scope = memo["comparison_scope"]
    contradiction_ids = [item["contradiction_id"] for item in memo["contradiction_ledger"]]
    active_contradiction_ids = contradiction_ids_active(memo["contradiction_ledger"])
    require(
        memo["confidence_summary"]["active_contradiction_ids"] == active_contradiction_ids,
        "confidence_summary active_contradiction_ids must be derived from contradiction_ledger",
    )
    for claim in memo["claim_matrix"]:
        require(
            claim["contradiction_ids"] == contradiction_ids_for_claim(memo["contradiction_ledger"], claim["claim_id"]),
            f"claim contradiction_ids must be derived from contradiction_ledger: {claim['claim_id']}",
        )
    trusted_performance_summary = comparison_scope["trusted_vs_performance_divergence"]
    if trusted_performance_summary["status"] == "diverged":
        require(
            TRUSTED_VS_PERFORMANCE_CONTRADICTION_ID in contradiction_ids,
            "trusted/performance divergence must be reflected in contradiction_ledger",
        )
        require(
            decision["trusted_vs_performance_divergence_reported"] is True,
            "decision must report trusted/performance divergence when comparison_scope diverges",
        )
    else:
        require(
            TRUSTED_VS_PERFORMANCE_CONTRADICTION_ID not in contradiction_ids,
            "trusted/performance contradiction row must disappear when divergence is not present",
        )
    if stage == "stage_a":
        require(activation["activation_mode"] == "stage_a_projection_grade", "unexpected Stage A activation mode")
        require(memo["allowed_claims"] == [], "Stage A allowed_claims must be empty")
        require(memo["guarded_claims"] == ["simulator_dse_ranking_predictiveness"], "Stage A guarded_claims mismatch")
        require(memo["forbidden_claims"] == STAGE_A_FORBIDDEN_CLAIMS, "Stage A forbidden_claims mismatch")
        require(permissions["simulator_dse_ranking_predictiveness"] == "guarded", "Stage A predictiveness claim must stay guarded")
        for claim_id in STAGE_A_FORBIDDEN_CLAIMS:
            require(permissions[claim_id] == "forbidden", f"Stage A claim must remain forbidden: {claim_id}")
        require(decision["recommended_family"] is None, "Stage A memo must not recommend a family")
        require(decision["public_family_decision_status"] in {"blocked", "no_recommendation"}, "Stage A public decision status invalid")
        require(decision["release_posture"] in {"blocked", "no_public_recommendation", "bounded_projection_grade_public_memo"}, "Stage A release posture invalid")
    else:
        require(stage == "stage_b", "unsupported adjudicator stage")
        require(activation["activation_mode"] == "stage_b_closure_bound", "unexpected Stage B activation mode")
        require(decision["public_family_decision_status"] in {"conditional_recommendation", "family_selected"}, "Stage B decision status invalid")
        require(decision["release_posture"] in {"conditional_public_memo", "board_validated_public_memo"}, "Stage B release posture invalid")
        require(permissions["cpu_fpga_vs_cpu_gpu"] == "allowed", "Stage B comparative GPU claim must be unlocked on happy-path closure")
        require(permissions["lower_whole_node_power"] == "allowed", "Stage B lower whole-node power claim must be unlocked on happy-path closure")
        if trusted_performance_summary["status"] == "diverged":
            require(
                decision["public_family_decision_status"] == "conditional_recommendation",
                "Stage B must stay conditional until trusted/performance divergence is resolved by measured evidence",
            )
            require(
                decision["recommended_family"] is None,
                "Stage B must not recommend a family while trusted/performance divergence remains unresolved",
            )
            require(
                decision["trusted_vs_performance_resolution"] in {"conditional_until_measured_resolution", "blocked_by_unresolved_divergence"},
                "Stage B unresolved divergence must be machine-readable",
            )
        input_manifest = memo["input_artifact_manifest"]
        for surface_name in ["gpu_annex_summary", "gpu_decisive_baseline_summary", "phase1_evidence_closure", "stage_main_evidence"]:
            surface = input_manifest[surface_name]
            require(
                surface["join_key_status"] != "not_applicable" or surface["artifact_status"] == "deferred",
                f"present artifact must expose join_key_status for {surface_name}",
            )
        for surface in input_manifest.get("additional_evidence_refs", []):
            require(
                surface["join_key_status"] != "not_applicable" or surface["artifact_status"] == "deferred",
                f"present artifact must expose join_key_status for {surface['artifact_ref_id']}",
            )
    trusted_family_candidate = memo["comparison_scope"]["trusted_family_candidate"]
    if stage == "stage_a" and trusted_family_candidate is None:
        require(decision["public_family_decision_status"] == "blocked", "frontdoor-only Stage A must be blocked")
        require("blocker::graph_projection_only" in decision["blocked_by_blocker_ids"], "frontdoor-only Stage A must expose graph_projection_only blocker")
    elif stage == "stage_a":
        require(decision["public_family_decision_status"] == "no_recommendation", "supported Stage A shortlist must still withhold public recommendation")
        require(decision["release_posture"] == "bounded_projection_grade_public_memo", "supported Stage A shortlist should emit bounded projection-grade posture")


def validate_against_schema_if_available(memo: dict[str, Any], schema_path: Path) -> None:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return
    schema = load_json(schema_path)
    jsonschema.validate(instance=memo, schema=schema)


def render_markdown(memo: dict[str, Any]) -> str:
    metadata = memo["memo_metadata"]
    input_manifest = memo["input_artifact_manifest"]
    decision = memo["decision"]
    comparison_scope = memo["comparison_scope"]
    confidence = memo["confidence_summary"]
    lines = [
        "# QE System Design Adjudication Memo",
        "",
        f"- memo_id: `{metadata['memo_id']}`",
        f"- stage: `{metadata['stage']}`",
        f"- generated_at_utc: `{memo['generated_at_utc']}`",
        f"- authority_contract_id: `{memo['authority_contract_id']}`",
        f"- input_manifest_contract_id: `{memo['input_manifest_contract_id']}`",
        f"- public_family_decision_status: `{decision['public_family_decision_status']}`",
        f"- recommended_family: `{decision['recommended_family']}`",
        f"- release_posture: `{decision['release_posture']}`",
        f"- decision_confidence: `{decision['decision_confidence']}`",
        "",
        "## Decision summary",
        "",
        decision["summary"],
        "",
        "## Comparison scope",
        "",
        f"- evaluated_families: `{', '.join(comparison_scope['evaluated_families'])}`",
        f"- authority_cohort: `{comparison_scope['authority_cohort']}`",
        f"- trusted_family_candidate: `{comparison_scope['trusted_family_candidate']}`",
        f"- best_performance_family_candidate: `{comparison_scope['best_performance_family_candidate']}`",
        f"- candidate_family: `{comparison_scope['dse_subject_metadata']['candidate_family']}`",
        f"- runtime_projection_family: `{comparison_scope['dse_subject_metadata']['runtime_projection_family']}`",
        f"- evaluator_backend: `{comparison_scope['dse_subject_metadata']['evaluator_backend']}`",
        f"- fidelity_class: `{comparison_scope['dse_subject_metadata']['fidelity_class']}`",
        f"- support_status: `{comparison_scope['dse_subject_metadata']['support_status']}`",
        f"- executor_claim_allowed: `{comparison_scope['dse_subject_metadata']['support_evidence']['executor_claim_allowed']}` (executor-path metadata only; never final/public claim permission)",
        f"- overall_confidence: `{confidence['overall_confidence']}`",
        f"- confidence_ceiling_applied: `{confidence['confidence_ceiling_applied']}`",
        f"- binding_precedence_category: `{confidence['binding_precedence_category']}`",
        "",
        "## Normalized identity tuple",
        "",
    ]
    for field_name in IDENTITY_FIELD_ORDER:
        lines.append(f"- {field_name}: `{input_manifest['normalized_identity_tuple'][field_name]}`")
    lines.extend(
        [
            "",
            "## Input artifact manifest",
            "",
            "| surface | status | join_key_status | artifact_path |",
            "| --- | --- | --- | --- |",
        ]
    )
    dse_subject = input_manifest["dse_subject_row"]
    lines.append(
        f"| dse_subject_row | `{dse_subject['artifact_status']}` | `{dse_subject['join_key_status']}` | `{dse_subject['artifact_path']}` |"
    )
    lines.append(
        f"| family_summary_context | advisory | family_only_context | `{input_manifest['family_summary_context']['artifact_path']}` |"
    )
    for surface_name in ["gpu_annex_summary", "gpu_decisive_baseline_summary", "phase1_evidence_closure", "stage_main_evidence"]:
        surface = input_manifest[surface_name]
        lines.append(
            f"| {surface_name} | `{surface['artifact_status']}` | `{surface['join_key_status']}` | `{surface['artifact_path']}` |"
        )
    for surface in input_manifest.get("additional_evidence_refs", []):
        lines.append(
            f"| {surface['artifact_ref_id']} | `{surface['artifact_status']}` | `{surface['join_key_status']}` | `{surface['artifact_path']}` |"
        )
    lines.extend(
        [
            "",
            "## Claim matrix",
            "",
            "| claim_id | public_claim_label | permission | public_wording_ceiling | required_confidence_level |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for claim in memo["claim_matrix"]:
        lines.append(
            f"| `{claim['claim_id']}` | `{claim['public_claim_label']}` | `{claim['permission']}` | `{claim['public_wording_ceiling']}` | `{claim['required_confidence_level']}` |"
        )
    lines.extend(
        [
            "",
            "## Blocker ledger",
            "",
            "| blocker_id | blocker_class | severity | precedence_category | rationale |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if memo["blocker_ledger"]:
        for blocker in memo["blocker_ledger"]:
            lines.append(
                f"| `{blocker['blocker_id']}` | `{blocker['blocker_class']}` | `{blocker['severity']}` | `{blocker['precedence_category']}` | {blocker['rationale']} |"
            )
    else:
        lines.append("| `—` | `—` | `—` | `—` | none |")
    lines.extend(
        [
            "",
            "## Next actions",
            "",
        ]
    )
    for action in memo["next_actions"]:
        lines.append(f"- `{action['action_id']}` ({action['priority']}, {action['action_type']} -> {action['target_surface']}): {action['description']}")
    if memo.get("notes"):
        lines.extend(["", "## Notes", ""])
        for note in memo["notes"]:
            lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def write_decision_memo_artifacts(
    *,
    dse_bundle_path: Path,
    output_dir: Path,
    gpu_annex_path: Path | None = None,
    phase1_closure_path: Path | None = None,
    board_closure_path: Path | None = None,
    stage_main_evidence_path: Path | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    resolved_dse_bundle_path = resolve_dse_bundle_path(dse_bundle_path)
    dse_bundle = load_dse_bundle(resolved_dse_bundle_path)
    gpu_annex = load_optional_artifact(gpu_annex_path, "gpu_annex")
    phase1_closure = load_optional_artifact(phase1_closure_path, "phase1_closure")
    board_closure = load_optional_artifact(board_closure_path, "board_closure")
    if stage_main_evidence_path is not None:
        stage_main_evidence = load_optional_artifact(stage_main_evidence_path, "stage_main_evidence")
    else:
        stage_main_evidence = load_optional_artifact_from_directory(
            resolved_dse_bundle_path.parent,
            "stage_main_evidence",
        )

    memo = build_stage_a_memo(
        dse_bundle_path=resolved_dse_bundle_path,
        dse_bundle=dse_bundle,
        gpu_annex=gpu_annex,
        phase1_closure=phase1_closure,
        board_closure=board_closure,
        stage_main_evidence=stage_main_evidence,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "decision_memo.json"
    md_path = output_dir / "decision_memo.md"
    write_json(json_path, memo)
    md_path.write_text(render_markdown(memo), encoding="utf-8")
    return memo, json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize QE adjudicator Stage A inputs and emit a shared-schema decision memo skeleton."
    )
    parser.add_argument("--dse-bundle", type=Path, required=True, help="Path to a DSE bundle JSON file or a directory containing one.")
    parser.add_argument("--gpu-annex", type=Path, default=None, help="Optional path to a normalized gpu_annex JSON file or a directory containing qe_gpu_annex_summary.json.")
    parser.add_argument("--phase1-closure", type=Path, default=None, help="Optional path to a normalized phase1 closure JSON file or a directory containing qe_phase1_evidence_closure_report.json.")
    parser.add_argument("--board-closure", type=Path, default=None, help="Optional path to a normalized board closure JSON artifact (for example board_compare.json).")
    parser.add_argument("--stage-main-evidence", type=Path, default=None, help="Optional path to a stage-main evidence JSON artifact. When omitted, the runner only auto-discovers qe_next_stage_stage_main_recommendation.json next to the resolved DSE bundle.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory where decision_memo.json and decision_memo.md will be written.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    memo, json_path, md_path = write_decision_memo_artifacts(
        dse_bundle_path=args.dse_bundle,
        output_dir=args.output_dir,
        gpu_annex_path=args.gpu_annex,
        phase1_closure_path=args.phase1_closure,
        board_closure_path=args.board_closure,
        stage_main_evidence_path=args.stage_main_evidence,
    )

    print(f"[ok] wrote adjudicator memo JSON: {json_path}")
    print(f"[ok] wrote adjudicator memo Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AdjudicatorRunError as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
