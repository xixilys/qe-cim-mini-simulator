#!/usr/bin/env python3
"""Complete-DSE reporting and claim gates.

This module owns the reporting-lane contract for the complete DSE search-space
plan.  It deliberately separates useful draft/vertical-slice/MVP/projection
artifacts from the only release-completion condition: every frozen legal
candidate and every frozen workload case has trusted L4 full-flow evidence with
both correctness gates, baseline comparison, and trace/calibration evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence


CLAIM_LABELS = (
    "research_projection",
    "release_l3_projection",
    "vertical_slice_only",
    "mvp_partial",
    "l4_trusted_speedup",
    "blocked",
    "deliverable_complete",
)

TRUSTED_ROW_CLAIM = "l4_trusted_speedup"

ROW_REQUIRED_GATES = (
    "l4_full_flow_evidence",
    "software_visible_completion",
    "descriptor_request_decode_execute_completion_trace",
    "baseline_comparison",
    "kernel_correctness",
    "scf_physical_correctness",
    "calibration_or_consistency",
)

IDENTITY_LAYERS = (
    "algorithm_parameters",
    "architecture_parameters",
    "mapping_layout_parameters",
    "compile_time_schedule_parameters",
    "runtime_scheduling_parameters",
)

EXCLUDED_IDENTITY_FIELDS = (
    "workload_case_id",
    "evidence_fidelity",
    "promotion_policy",
    "queue_order",
    "tool_status",
    "blocker_status",
    "retry_count",
)

ANTI_DOWNGRADE_RULES = (
    "no_top_k_completion",
    "no_representative_subset_completion",
    "no_promoted_only_completion",
    "no_pareto_only_completion",
    "no_smoke_only_completion",
    "no_descriptor_only_completion",
    "no_projection_only_completion",
    "no_tool_unavailable_completion",
)

DISALLOWED_COMPLETION_BASES = {
    "top_k",
    "representative",
    "representative_subset",
    "promoted_only",
    "pareto_only",
    "smoke_only",
    "descriptor_only",
    "projection_only",
    "tool_unavailable",
    "tool_failure",
    "l1_projection",
    "l2_projection",
    "l3_projection",
}

LOW_TRUST_EVIDENCE_TIERS = {
    "l1",
    "l2",
    "l3",
    "analytical",
    "tlm",
    "systemc_timing_only",
    "projection",
    "screening",
    "descriptor_only",
}

REQUIRED_COMPLETE_DSE_REPORT_ARTIFACTS = (
    "workload_architecture_prior_report.json",
    "architecture_prior_seed_manifest.json",
    "release_pruning_rationale_report.json",
    "architecture_candidate_generation_report.json",
    "candidate_generation_report.json",
    "architecture_screening_report.json",
    "performance_claim_policy.json",
    "l4_evidence_matrix_schema.json",
    "l4_evidence_matrix_report.json",
    "coverage_claim_report.json",
    "coverage_claim_report.md",
    "prompt_to_artifact_checklist.json",
    "prompt_to_artifact_checklist.md",
)

REQUIRED_SEED_TEMPLATE_IDS = (
    "streaming_pipeline",
    "simd_vector",
    "spatial_pe_array",
    "task_parallel_engines",
    "pipeline_simd_fused",
    "pipeline_spatial_array",
    "task_parallel_simd",
    "task_parallel_spatial_array",
    "pipeline_task_overlap",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ref(path: Path, *, base_dir: Path) -> Dict[str, Any]:
    return {
        "path": str(path.relative_to(base_dir)),
        "sha256": _sha256(path),
        "hash_algorithm": "sha256",
    }


def _normalise_ids(values: Iterable[str] | None) -> list[str]:
    return sorted({str(value) for value in values or []})


def _row_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("candidate_id", "")), str(row.get("workload_case_id", ""))


def _common_payload(status: str) -> Dict[str, Any]:
    return {
        "schema_version": "dse.complete_dse.reporting.v1",
        "generated_at": _now_iso(),
        "status": status,
        "claim_labels": list(CLAIM_LABELS),
        "anti_downgrade_rules": list(ANTI_DOWNGRADE_RULES),
        "claim_boundary": (
            "Drafts, vertical slices, MVPs, projections, blockers, Top-K subsets, "
            "representative subsets, descriptor-only paths, and tool-unavailable "
            "rows are reportable audit facts but cannot satisfy deliverable_complete."
        ),
    }


def _seed_manifest_rows() -> list[Dict[str, Any]]:
    return [
        {
            "seed_template_id": "streaming_pipeline",
            "kind": "base_family",
            "status": "draft",
            "bounded_parameter_levels": {"pipeline_depth": ["small"], "dma_overlap": ["single_buffer"]},
            "source_workload_features": ["fft", "rho", "potential_update"],
        },
        {
            "seed_template_id": "simd_vector",
            "kind": "base_family",
            "status": "draft",
            "bounded_parameter_levels": {"lanes": [4], "vector_width_policy": ["portable"]},
            "source_workload_features": ["residual", "mix_rho", "vector_updates"],
        },
        {
            "seed_template_id": "spatial_pe_array",
            "kind": "base_family",
            "status": "draft",
            "bounded_parameter_levels": {"array_shape": ["small_square"], "tile_policy": ["blocked"]},
            "source_workload_features": ["h_psi", "s_psi", "subspace_matrix"],
        },
        {
            "seed_template_id": "task_parallel_engines",
            "kind": "base_family",
            "status": "draft",
            "bounded_parameter_levels": {"engine_count": [2], "queue_policy": ["ordered_overlap"]},
            "source_workload_features": ["multi_kernel_iteration_overlap"],
        },
        {
            "seed_template_id": "pipeline_simd_fused",
            "kind": "hybrid_template",
            "status": "draft",
            "bounded_parameter_levels": {"fusion_policy": ["stream_vector"]},
            "source_workload_features": ["fft", "rho", "vector_updates"],
        },
        {
            "seed_template_id": "pipeline_spatial_array",
            "kind": "hybrid_template",
            "status": "draft",
            "bounded_parameter_levels": {"stream_to_array_policy": ["blocked_dma"]},
            "source_workload_features": ["h_psi", "s_psi", "subspace_matrix"],
        },
        {
            "seed_template_id": "task_parallel_simd",
            "kind": "hybrid_template",
            "status": "draft",
            "bounded_parameter_levels": {"assignment_policy": ["simd_friendly_to_vector_engine"]},
            "source_workload_features": ["mixed_full_flow", "vector_updates"],
        },
        {
            "seed_template_id": "task_parallel_spatial_array",
            "kind": "hybrid_template",
            "status": "draft",
            "bounded_parameter_levels": {"assignment_policy": ["dense_kernel_to_array_engine"]},
            "source_workload_features": ["mixed_full_flow", "dense_subspace"],
        },
        {
            "seed_template_id": "pipeline_task_overlap",
            "kind": "hybrid_template",
            "status": "draft",
            "bounded_parameter_levels": {"overlap_policy": ["pipeline_host_queue_dma"]},
            "source_workload_features": ["multi_kernel_iteration_overlap"],
        },
    ]


def trusted_l4_row(
    candidate_id: str,
    workload_case_id: str,
    *,
    evidence_refs: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return a minimal row that satisfies the trusted L4 speedup gate."""
    return {
        "candidate_id": str(candidate_id),
        "workload_case_id": str(workload_case_id),
        "status": "passed",
        "evidence_tier": "l4_full_flow",
        "claim_label": TRUSTED_ROW_CLAIM,
        "completion_basis": "full_matrix_l4_evidence",
        "tool_status": "available",
        "required_gates": {gate: True for gate in ROW_REQUIRED_GATES},
        "evidence_refs": dict(evidence_refs or {}),
        "claim_boundary": "Trusted speedup row only; release completion still requires the full frozen matrix.",
    }


def blocked_l4_row(
    candidate_id: str,
    workload_case_id: str,
    *,
    reason: str,
    evidence_tier: str = "l4_full_flow",
    completion_basis: str = "blocked",
) -> Dict[str, Any]:
    """Return a blocked matrix row that is explicit non-completion evidence."""
    return {
        "candidate_id": str(candidate_id),
        "workload_case_id": str(workload_case_id),
        "status": "blocked",
        "evidence_tier": evidence_tier,
        "claim_label": "blocked",
        "completion_basis": completion_basis,
        "tool_status": "blocked",
        "blocker_reason": reason,
        "required_gates": {gate: False for gate in ROW_REQUIRED_GATES},
        "evidence_refs": {},
        "completion_eligible": False,
        "claim_boundary": "Blocked row is diagnostic evidence and cannot satisfy deliverable_complete.",
    }


def validate_l4_evidence_matrix_claims(
    matrix_report: Mapping[str, Any],
    *,
    expected_candidate_ids: Iterable[str] | None = None,
    expected_workload_case_ids: Iterable[str] | None = None,
    required_artifacts_present: bool | None = None,
) -> Dict[str, Any]:
    """Validate the complete-DSE L4 matrix and return a claim decision.

    Validation is intentionally conservative.  ``deliverable_complete_allowed``
    is true only when the frozen candidate/workload cross-product is complete
    and every row passes the trusted L4 gate.
    """
    candidate_ids = _normalise_ids(expected_candidate_ids or matrix_report.get("candidate_ids", []))
    workload_case_ids = _normalise_ids(expected_workload_case_ids or matrix_report.get("workload_case_ids", []))
    rows = matrix_report.get("rows", [])
    if not isinstance(rows, list):
        rows = []

    errors: list[Dict[str, Any]] = []
    blockers: list[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    if not candidate_ids:
        errors.append({"field": "candidate_ids", "message": "frozen candidate ids are required"})
    if not workload_case_ids:
        errors.append({"field": "workload_case_ids", "message": "frozen workload case ids are required"})

    expected_pairs = {(candidate_id, workload_id) for candidate_id in candidate_ids for workload_id in workload_case_ids}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append({"field": f"rows[{index}]", "message": "row must be an object"})
            continue
        key = _row_key(row)
        if not all(key):
            errors.append({"field": f"rows[{index}]", "message": "candidate_id and workload_case_id are required"})
            continue
        if key in seen:
            errors.append({"field": f"rows[{index}]", "message": "duplicate matrix row", "row_key": key})
        seen.add(key)

        row_reasons: list[str] = []
        evidence_tier = str(row.get("evidence_tier", "")).lower()
        claim_label = str(row.get("claim_label", "")).lower()
        completion_basis = str(row.get("completion_basis", "")).lower()
        status = str(row.get("status", "")).lower()
        tool_status = str(row.get("tool_status", "")).lower()
        gates = row.get("required_gates", {})
        if not isinstance(gates, Mapping):
            gates = {}

        if evidence_tier in LOW_TRUST_EVIDENCE_TIERS:
            row_reasons.append(f"low_trust_evidence_tier:{evidence_tier}")
        if completion_basis in DISALLOWED_COMPLETION_BASES:
            row_reasons.append(f"disallowed_completion_basis:{completion_basis}")
        if claim_label != TRUSTED_ROW_CLAIM:
            row_reasons.append(f"non_trusted_claim_label:{claim_label or 'missing'}")
        if status != "passed":
            row_reasons.append(f"row_status_not_passed:{status or 'missing'}")
        if tool_status in {"unavailable", "failed", "blocked", "missing"} and status == "passed":
            row_reasons.append(f"tool_status_cannot_support_passed_row:{tool_status}")

        missing_gates = [gate for gate in ROW_REQUIRED_GATES if gates.get(gate) is not True]
        if missing_gates:
            row_reasons.append("missing_required_gates:" + ",".join(missing_gates))
        evidence_refs = row.get("evidence_refs", {})
        if not isinstance(evidence_refs, Mapping):
            evidence_refs = {}
        missing_evidence_refs = [
            gate
            for gate in ROW_REQUIRED_GATES
            if gates.get(gate) is True and not evidence_refs.get(gate)
        ]
        if missing_evidence_refs:
            row_reasons.append("missing_required_evidence_refs:" + ",".join(missing_evidence_refs))

        if row_reasons:
            blockers.append({
                "candidate_id": key[0],
                "workload_case_id": key[1],
                "reasons": row_reasons,
            })

    missing_pairs = sorted(expected_pairs - seen)
    extra_pairs = sorted(seen - expected_pairs) if expected_pairs else []
    if missing_pairs:
        errors.append({
            "field": "rows",
            "message": "missing frozen candidate/workload rows",
            "missing_rows": [
                {"candidate_id": candidate_id, "workload_case_id": workload_id}
                for candidate_id, workload_id in missing_pairs
            ],
        })
    if extra_pairs:
        errors.append({
            "field": "rows",
            "message": "matrix contains rows outside the frozen release cross-product",
            "extra_rows": [
                {"candidate_id": candidate_id, "workload_case_id": workload_id}
                for candidate_id, workload_id in extra_pairs
            ],
        })
    if required_artifacts_present is False:
        errors.append({"field": "required_artifacts", "message": "required report/checklist artifacts are missing"})

    deliverable_allowed = bool(candidate_ids and workload_case_ids and rows and not errors and not blockers)
    return {
        "schema_version": "dse.complete_dse.l4_matrix_claim_validation.v1",
        "valid": not errors,
        "deliverable_complete_allowed": deliverable_allowed,
        "row_count": len(rows),
        "expected_row_count": len(expected_pairs),
        "candidate_count": len(candidate_ids),
        "workload_case_count": len(workload_case_ids),
        "blocked_row_count": len(blockers),
        "errors": errors,
        "blockers": blockers,
        "anti_downgrade_rules": list(ANTI_DOWNGRADE_RULES),
        "claim_boundary": (
            "deliverable_complete_allowed is true only for a complete frozen "
            "candidate × workload matrix of trusted L4 full-flow rows."
        ),
    }


def validate_complete_dse_claim_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a final coverage claim report and reject false completion."""
    matrix_report = report.get("l4_evidence_matrix", {})
    if not isinstance(matrix_report, Mapping):
        matrix_report = {}
    artifact_refs = report.get("required_artifacts", {})
    required_present = (
        isinstance(artifact_refs, Mapping)
        and all(name in artifact_refs for name in REQUIRED_COMPLETE_DSE_REPORT_ARTIFACTS)
    )
    validation = validate_l4_evidence_matrix_claims(
        matrix_report,
        expected_candidate_ids=report.get("candidate_ids", []),
        expected_workload_case_ids=report.get("workload_case_ids", []),
        required_artifacts_present=required_present,
    )
    claimed_complete = report.get("deliverable_complete") is True or report.get("status") == "deliverable_complete"
    errors = list(validation["errors"])
    if claimed_complete and not validation["deliverable_complete_allowed"]:
        errors.append({
            "field": "deliverable_complete",
            "message": "report claims deliverable_complete but the L4 matrix claim gate did not allow it",
        })
    return {
        "schema_version": "dse.complete_dse.coverage_claim_validation.v1",
        "valid": not errors,
        "deliverable_complete_allowed": validation["deliverable_complete_allowed"],
        "claimed_deliverable_complete": claimed_complete,
        "errors": errors,
        "blockers": validation["blockers"],
        "matrix_validation": validation,
        "claim_boundary": (
            "A coverage report may be structurally valid while still blocked. "
            "Claimed deliverable_complete is valid only when the matrix gate allows it."
        ),
    }


def build_coverage_claim_report(
    *,
    candidate_ids: Iterable[str],
    workload_case_ids: Iterable[str],
    l4_rows: Sequence[Mapping[str, Any]],
    required_artifacts: Mapping[str, Any] | None = None,
    status: str = "draft",
) -> Dict[str, Any]:
    """Build a machine-readable coverage claim report from L4 matrix rows."""
    candidate_id_list = _normalise_ids(candidate_ids)
    workload_id_list = _normalise_ids(workload_case_ids)
    matrix_report = {
        "schema_version": "dse.complete_dse.l4_evidence_matrix_report.v1",
        "status": status,
        "candidate_ids": candidate_id_list,
        "workload_case_ids": workload_id_list,
        "rows": [dict(row) for row in l4_rows],
        "claim_boundary": (
            "The matrix is complete only when every frozen candidate/workload pair "
            "has a trusted L4 full-flow row with all required gates passing."
        ),
    }
    matrix_validation = validate_l4_evidence_matrix_claims(
        matrix_report,
        required_artifacts_present=required_artifacts is not None,
    )
    deliverable_allowed = matrix_validation["deliverable_complete_allowed"]
    report_status = "deliverable_complete" if deliverable_allowed else ("blocked" if l4_rows else status)
    report = {
        **_common_payload(report_status),
        "schema_version": "dse.complete_dse.coverage_claim_report.v1",
        "candidate_ids": candidate_id_list,
        "workload_case_ids": workload_id_list,
        "l4_evidence_matrix": matrix_report,
        "matrix_validation": matrix_validation,
        "required_artifacts": dict(required_artifacts or {}),
        "claim_summary": {
            "vertical_slice_only": any(row.get("claim_label") == "vertical_slice_only" for row in l4_rows),
            "mvp_partial": bool(l4_rows and not deliverable_allowed),
            "projection_rows": [
                {"candidate_id": _row_key(row)[0], "workload_case_id": _row_key(row)[1]}
                for row in l4_rows
                if str(row.get("evidence_tier", "")).lower() in LOW_TRUST_EVIDENCE_TIERS
            ],
            "trusted_l4_rows": sum(1 for row in l4_rows if row.get("claim_label") == TRUSTED_ROW_CLAIM),
            "blocked_rows": matrix_validation["blocked_row_count"],
        },
        "deliverable_complete": deliverable_allowed,
        "rejected_false_completion_bases": sorted(DISALLOWED_COMPLETION_BASES),
    }
    return report


def render_coverage_claim_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise human-readable coverage report."""
    validation = report.get("matrix_validation", {})
    summary = report.get("claim_summary", {})
    return "\n".join([
        "# Complete DSE Coverage Claim Report",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Deliverable complete: `{report.get('deliverable_complete')}`",
        f"- Candidates: `{len(report.get('candidate_ids', []))}`",
        f"- Workload cases: `{len(report.get('workload_case_ids', []))}`",
        f"- Matrix rows: `{validation.get('row_count', 0)}` / `{validation.get('expected_row_count', 0)}`",
        f"- Trusted L4 rows: `{summary.get('trusted_l4_rows', 0)}`",
        f"- Blocked rows: `{summary.get('blocked_rows', 0)}`",
        "",
        "## Claim boundary",
        "",
        str(report.get("claim_boundary", "")),
        "",
    ])


def _build_prompt_to_artifact_checklist(required_artifacts: Mapping[str, Any], status: str) -> Dict[str, Any]:
    checklist = [
        {
            "requirement": "artifact::" + artifact_name,
            "artifact": required_artifacts.get(artifact_name, {"path": artifact_name}),
            "status": "present_hash_valid" if artifact_name in required_artifacts else "missing",
            "completion_claim": "required_before_deliverable_complete",
        }
        for artifact_name in REQUIRED_COMPLETE_DSE_REPORT_ARTIFACTS
        if artifact_name not in {"prompt_to_artifact_checklist.json", "prompt_to_artifact_checklist.md"}
    ]
    checklist.extend([
        {
            "requirement": "claim_label_separation",
            "status": "covered",
            "claim_labels": list(CLAIM_LABELS),
            "completion_claim": "deliverable_complete_separate_from_vertical_slice_mvp_projection_blocked",
        },
        {
            "requirement": "anti_downgrade_rules",
            "status": "covered",
            "anti_downgrade_rules": list(ANTI_DOWNGRADE_RULES),
            "completion_claim": "downgraded_evidence_never_satisfies_completion",
        },
        {
            "requirement": "full_l4_matrix_closure",
            "status": "blocked_until_all_rows_pass",
            "required_gates": list(ROW_REQUIRED_GATES),
            "completion_claim": "all_legal_candidates_times_all_workload_cases",
        },
    ])
    return {
        **_common_payload(status),
        "schema_version": "dse.complete_dse.prompt_to_artifact_checklist.v1",
        "checklist": checklist,
        "claim_boundary": (
            "Checklist maps prompt/PRD requirements to artifacts. It never upgrades "
            "missing, blocked, projection, Top-K, or representative evidence to completion."
        ),
    }


def render_prompt_to_artifact_markdown(checklist: Mapping[str, Any]) -> str:
    lines = [
        "# Complete DSE Prompt-to-Artifact Checklist",
        "",
        f"- Status: `{checklist.get('status')}`",
        "",
        "| Requirement | Status | Completion claim |",
        "| --- | --- | --- |",
    ]
    for row in checklist.get("checklist", []) or []:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"| `{row.get('requirement')}` | `{row.get('status')}` | `{row.get('completion_claim')}` |"
        )
    lines.extend(["", "## Claim boundary", "", str(checklist.get("claim_boundary", "")), ""])
    return "\n".join(lines)


def write_complete_dse_reporting_package(
    out_dir: Path,
    *,
    candidate_ids: Iterable[str] | None = None,
    workload_case_ids: Iterable[str] | None = None,
    l4_rows: Sequence[Mapping[str, Any]] | None = None,
    status: str = "draft",
) -> Dict[str, Any]:
    """Write the reporting-lane artifact package and return a status payload."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_id_list = _normalise_ids(candidate_ids or ["candidate_draft"])
    workload_id_list = _normalise_ids(workload_case_ids or ["workload_case_draft"])
    rows = [dict(row) for row in (l4_rows or [
        blocked_l4_row(
            candidate_id_list[0],
            workload_id_list[0],
            reason="L4 full-flow evidence matrix has not been executed for this draft package",
        )
    ])]

    report_payloads: dict[str, Mapping[str, Any]] = {
        "workload_architecture_prior_report.json": {
            **_common_payload(status),
            "schema_version": "dse.complete_dse.workload_architecture_prior_report.v1",
            "workload_facts": [
                {
                    "feature": "fft_rho_potential_streaming_paths",
                    "preferred_architecture_seeds": ["streaming_pipeline", "pipeline_simd_fused"],
                    "claim_boundary": "Architecture prior only; not a post-freeze Top-K completion shortcut.",
                },
                {
                    "feature": "h_psi_s_psi_subspace_matrix_kernels",
                    "preferred_architecture_seeds": ["spatial_pe_array", "pipeline_spatial_array"],
                    "claim_boundary": "Architecture prior only; not a trusted speedup claim.",
                },
                {
                    "feature": "multi_kernel_qe_iteration_overlap",
                    "preferred_architecture_seeds": ["task_parallel_engines", "pipeline_task_overlap"],
                    "claim_boundary": "Runtime overlap remains untrusted until gem5-visible queue traces pass.",
                },
            ],
        },
        "architecture_prior_seed_manifest.json": {
            **_common_payload(status),
            "schema_version": "dse.complete_dse.architecture_prior_seed_manifest.v1",
            "seed_templates": _seed_manifest_rows(),
            "required_seed_template_ids": list(REQUIRED_SEED_TEMPLATE_IDS),
            "pre_freeze_only": True,
            "claim_boundary": (
                "Seed templates bound the release universe before candidate freeze. "
                "They cannot remove already-frozen rows or claim completion by selection."
            ),
        },
        "release_pruning_rationale_report.json": {
            **_common_payload(status),
            "schema_version": "dse.complete_dse.release_pruning_rationale_report.v1",
            "allowed_prune_reasons": ["illegal", "research_only", "over_budget", "blocked"],
            "pruned_combinations": [],
            "post_freeze_row_removal_allowed": False,
            "claim_boundary": (
                "Pruning is valid only as pre-freeze rationale. Post-freeze Top-K, "
                "representative, Pareto, or promoted-only substitution cannot complete a release."
            ),
        },
        "architecture_candidate_generation_report.json": {
            **_common_payload(status),
            "schema_version": "dse.complete_dse.architecture_candidate_generation_report.v1",
            "identity_layers": list(IDENTITY_LAYERS),
            "excluded_identity_fields": list(EXCLUDED_IDENTITY_FIELDS),
            "candidate_ids": candidate_id_list,
            "stable_candidate_ids_emitted": False,
            "stable_id_preconditions": {
                layer: "required_before_freeze" for layer in IDENTITY_LAYERS
            },
            "claim_boundary": (
                "Candidate generation proves identity structure only. Workload, "
                "evidence tier, promotion policy, tool status, and queue order do not affect candidate id."
            ),
        },
        "candidate_generation_report.json": {
            **_common_payload(status),
            "schema_version": "dse.complete_dse.candidate_generation_report.v1",
            "identity_layers": list(IDENTITY_LAYERS),
            "excluded_identity_fields": list(EXCLUDED_IDENTITY_FIELDS),
            "candidate_ids": candidate_id_list,
            "stable_candidate_ids_emitted": False,
            "claim_boundary": "Compatibility report for the PRD candidate_generation_report artifact.",
        },
        "architecture_screening_report.json": {
            **_common_payload("projection_only"),
            "schema_version": "dse.complete_dse.architecture_screening_report.v1",
            "screening_status": "projection_only",
            "candidate_ids": candidate_id_list,
            "allowed_claims": ["research_projection", "release_l3_projection", "blocked"],
            "forbidden_claims": ["l4_trusted_speedup", "deliverable_complete"],
            "claim_boundary": "Architecture screening can rank or explain candidates but cannot claim trusted speedup.",
        },
        "performance_claim_policy.json": {
            **_common_payload(status),
            "schema_version": "dse.complete_dse.performance_claim_policy.v1",
            "projection_only_tiers": sorted(LOW_TRUST_EVIDENCE_TIERS),
            "trusted_speedup_required_evidence_tier": "l4_full_flow",
            "trusted_row_required_gates": list(ROW_REQUIRED_GATES),
            "rejected_completion_bases": sorted(DISALLOWED_COMPLETION_BASES),
            "claim_boundary": "Only L4 full-flow rows with every required gate passed may claim trusted speedup.",
        },
        "l4_evidence_matrix_schema.json": {
            **_common_payload(status),
            "schema_version": "dse.complete_dse.l4_evidence_matrix_schema.v1",
            "required_row_fields": [
                "candidate_id",
                "workload_case_id",
                "status",
                "evidence_tier",
                "claim_label",
                "required_gates",
                "evidence_refs",
            ],
            "trusted_row_required_gates": list(ROW_REQUIRED_GATES),
            "claim_boundary": "The schema is a gate contract, not completion evidence.",
        },
        "l4_evidence_matrix_report.json": {
            "schema_version": "dse.complete_dse.l4_evidence_matrix_report.v1",
            "status": status,
            "candidate_ids": candidate_id_list,
            "workload_case_ids": workload_id_list,
            "rows": rows,
            "claim_boundary": (
                "Every legal candidate × workload case must have a trusted L4 row "
                "before deliverable_complete can be allowed."
            ),
        },
    }

    for name, payload in report_payloads.items():
        _write_json(out_dir / name, payload)

    required_refs = {
        name: _artifact_ref(out_dir / name, base_dir=out_dir)
        for name in report_payloads
    }
    coverage_report = build_coverage_claim_report(
        candidate_ids=candidate_id_list,
        workload_case_ids=workload_id_list,
        l4_rows=rows,
        required_artifacts=required_refs,
        status=status,
    )
    _write_json(out_dir / "coverage_claim_report.json", coverage_report)
    _write_text(out_dir / "coverage_claim_report.md", render_coverage_claim_markdown(coverage_report))
    required_refs["coverage_claim_report.json"] = _artifact_ref(out_dir / "coverage_claim_report.json", base_dir=out_dir)
    required_refs["coverage_claim_report.md"] = _artifact_ref(out_dir / "coverage_claim_report.md", base_dir=out_dir)

    checklist = _build_prompt_to_artifact_checklist(required_refs, status)
    _write_json(out_dir / "prompt_to_artifact_checklist.json", checklist)
    _write_text(out_dir / "prompt_to_artifact_checklist.md", render_prompt_to_artifact_markdown(checklist))
    required_refs["prompt_to_artifact_checklist.json"] = _artifact_ref(
        out_dir / "prompt_to_artifact_checklist.json", base_dir=out_dir
    )
    required_refs["prompt_to_artifact_checklist.md"] = _artifact_ref(
        out_dir / "prompt_to_artifact_checklist.md", base_dir=out_dir
    )

    final_coverage_report = {
        **coverage_report,
        "required_artifacts": required_refs,
    }
    final_validation = validate_complete_dse_claim_report(final_coverage_report)
    final_coverage_report["claim_validation"] = final_validation
    _write_json(out_dir / "coverage_claim_report.json", final_coverage_report)
    _write_text(out_dir / "coverage_claim_report.md", render_coverage_claim_markdown(final_coverage_report))
    required_refs["coverage_claim_report.json"] = _artifact_ref(out_dir / "coverage_claim_report.json", base_dir=out_dir)
    required_refs["coverage_claim_report.md"] = _artifact_ref(out_dir / "coverage_claim_report.md", base_dir=out_dir)

    manifest = {
        **_common_payload("passed" if final_validation["valid"] else "failed"),
        "schema_version": "dse.complete_dse.reporting_artifact_manifest.v1",
        "artifacts": required_refs,
        "coverage_claim_validation": final_validation,
        "deliverable_complete": final_validation["deliverable_complete_allowed"],
    }
    _write_json(out_dir / "reporting_artifact_manifest.json", manifest)
    return manifest
