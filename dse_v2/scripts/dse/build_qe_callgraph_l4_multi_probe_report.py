#!/usr/bin/env python3
"""Build a combined QE callgraph L4 evidence matrix from smoke attempts."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.qe_callgraph_offload_search import (  # noqa: E402
    build_accelerated_replacement_readiness_report,
    build_bundle_single_workflow_l4_evidence_report,
    build_callgraph_offload_blocker_report,
    build_bundle_harness_readiness_report,
    build_bundle_runtime_contract_report,
    build_l4_offload_attempt_queue,
    build_l4_speed_optimization_report,
    build_l4_value_repeatability_report,
    build_offload_bundle_viability_report,
    build_offload_bundle_search_space,
    build_offload_target_identity_schema,
    build_prompt_to_artifact_checklist,
    build_workload_variant_search_space,
    build_offload_value_l4_evidence_matrix,
    build_offload_selection_search_report,
    build_offload_value_report,
    _best_evidence_rows_by_opportunity,
    render_accelerated_replacement_readiness_report_markdown,
    render_callgraph_offload_blocker_report_markdown,
    render_l4_speed_optimization_report_markdown,
    render_l4_value_repeatability_report_markdown,
    render_offload_bundle_viability_report_markdown,
    render_offload_selection_search_report_markdown,
    render_offload_value_report_markdown,
    render_prompt_to_artifact_checklist_markdown,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_accelerated_numeric_rows(paths: Sequence[Path] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths or []:
        payload = _load_json(path)
        if isinstance(payload, Mapping) and isinstance(payload.get("rows"), list):
            rows.extend(
                dict(row) for row in payload["rows"] if isinstance(row, Mapping)
            )
        elif isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def _truthy_flag(section: Mapping[str, Any], *keys: str) -> bool:
    return any(section.get(key) is True for key in keys)


def _has_output_data_path(section: Mapping[str, Any]) -> bool:
    paths = section.get("accelerated_output_data_paths")
    if isinstance(paths, Sequence) and not isinstance(paths, (str, bytes)):
        if any(str(path or "").strip() for path in paths):
            return True
    return any(
        str(section.get(key) or "").strip()
        for key in (
            "accelerated_output_data_path",
            "accelerated_output_file",
            "accelerated_output_json",
            "accelerated_result_data_path",
            "accelerated_result_file",
            "accelerated_result_json",
            "accelerator_output_data_path",
            "accelerator_output_file",
            "QE_OFFLOAD_ACCELERATED_OUTPUT_JSON",
        )
    )


def _normalize_legacy_actual_compute_attempt(
    attempt: Mapping[str, Any],
) -> dict[str, Any]:
    """Preserve raw legacy observations while keeping strict consumption strict.

    Older actual-compute attempt artifacts sometimes used
    ``actual_compute_evidence.qe_consumed_accelerated_outputs=true`` for a raw
    patched-QE marker even when the row was blocked by correctness,
    materialization, software-kernel skip, or fallback evidence.  Rebuilding a
    cumulative report must not re-upgrade those raw markers into strict actual
    compute.  This normalization only changes the report copy; source attempt
    artifacts remain untouched for auditability.
    """

    normalized = deepcopy(dict(attempt))
    actual = normalized.get("actual_compute_evidence")
    replacement = normalized.get("accelerated_replacement")
    if not isinstance(actual, Mapping) or not isinstance(replacement, Mapping):
        return normalized

    actual_copy = dict(actual)
    replacement_copy = dict(replacement)
    raw_observed = (
        actual_copy.get("raw_accelerated_results_observed_by_qe") is True
        or actual_copy.get("qe_consumed_accelerated_outputs") is True
        or replacement_copy.get("accelerated_results_consumed_by_qe") is True
    )
    materialized = (
        actual_copy.get("accelerated_result_materialized_in_qe_memory") is True
        or _truthy_flag(
            replacement_copy,
            "accelerated_result_materialized_in_qe_memory",
            "accelerated_output_written_to_qe_buffer",
            "qe_consumed_accelerator_output_buffer",
        )
    )
    skipped = (
        actual_copy.get("qe_software_kernel_execution_skipped") is True
        or _truthy_flag(
            replacement_copy,
            "qe_software_kernel_execution_skipped",
            "software_kernel_execution_removed_from_critical_path",
            "software_kernel_work_skipped",
        )
    )
    replaced = (
        actual_copy.get("qe_kernel_work_replaced_on_critical_path") is True
        or _truthy_flag(
            replacement_copy,
            "qe_kernel_work_replaced_on_critical_path",
            "accelerated_kernel_work_removed_from_critical_path",
        )
    ) and materialized and skipped
    kernel = str(
        actual_copy.get("selected_kernel")
        or replacement_copy.get("selected_kernel")
        or replacement_copy.get("target_kernel")
        or normalized.get("kernel")
        or ""
    )
    output_path_ok = kernel in {"", "h_psi", "s_psi"} or _has_output_data_path(
        replacement_copy
    ) or bool(actual_copy.get("accelerated_output_data_path_present") is True)
    strict_consumed = (
        actual_copy.get("status") == "passed"
        and actual_copy.get("smoke_only") is not True
        and replacement_copy.get("status") == "passed"
        and raw_observed
        and materialized
        and skipped
        and replaced
        and replacement_copy.get("software_fallback_on_critical_path") is False
        and output_path_ok
    )

    actual_copy["qe_consumed_accelerated_outputs"] = strict_consumed
    actual_copy["raw_accelerated_results_observed_by_qe"] = raw_observed
    actual_copy["raw_accelerated_results_observed_before_strict_replacement"] = (
        raw_observed and not strict_consumed
    )
    actual_copy["accelerated_result_materialized_in_qe_memory"] = materialized
    actual_copy["qe_software_kernel_execution_skipped"] = skipped
    actual_copy["qe_kernel_work_replaced_on_critical_path"] = replaced
    actual_copy["accelerated_output_data_path_present"] = output_path_ok
    normalized["actual_compute_evidence"] = actual_copy
    return normalized


def _attempt_rows_from_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return attempt rows from a single-attempt or multi-row attempt artifact."""

    for key in ("attempts", "rows"):
        rows = payload.get(key)
        if isinstance(rows, list):
            normalized_rows: list[dict[str, Any]] = []
            parent_bundle_id = payload.get("bundle_id")
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                normalized_row = dict(row)
                if parent_bundle_id and not normalized_row.get("bundle_id"):
                    normalized_row["bundle_id"] = parent_bundle_id
                normalized_rows.append(normalized_row)
            return normalized_rows
    return [dict(payload)]


def _looks_like_bundle_campaign_status(payload: Mapping[str, Any]) -> bool:
    schema = str(payload.get("schema_version") or "")
    return (
        schema.startswith("dse.qe_bundle_single_workflow")
        or bool(payload.get("selected_bundle_ids"))
        or payload.get("single_qe_workflow_proven") is True
        or payload.get("bundle_level_valuable_l4") is not None
    )


def _load_bundle_campaign_statuses(
    *,
    attempt_paths: Sequence[Path],
    bundle_campaign_status_paths: Sequence[Path] | None,
) -> list[dict[str, Any]]:
    """Load explicit and colocated bundle status rows for bundle-level gates."""

    candidate_paths: list[Path] = []
    candidate_paths.extend(bundle_campaign_status_paths or [])
    for attempt_path in attempt_paths:
        sibling_status = attempt_path.parent / "status.json"
        if sibling_status.exists():
            candidate_paths.append(sibling_status)

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for status_path in candidate_paths:
        key = str(status_path.resolve())
        if key in seen or not status_path.exists():
            continue
        payload = _load_json(status_path)
        if not isinstance(payload, Mapping):
            continue
        if not _looks_like_bundle_campaign_status(payload):
            continue
        status = dict(payload)
        status["status_path"] = str(status_path)
        status.setdefault("campaign_root", str(status_path.parent))
        rows.append(status)
        seen.add(key)
    return rows


def build_multi_probe_report(
    *,
    out_dir: Path,
    inventory_path: Path,
    manifest_path: Path,
    attempt_paths: Sequence[Path],
    accelerated_numeric_evidence_paths: Sequence[Path] | None = None,
    patch_manifest_path: Path | None = None,
    bundle_campaign_status_paths: Sequence[Path] | None = None,
) -> dict[str, Any]:
    inventory = _load_json(inventory_path)
    manifest = _load_json(manifest_path)
    resolved_patch_manifest_path = patch_manifest_path
    if resolved_patch_manifest_path is None:
        default_patch_manifest_path = manifest_path.parent / "qe_callsite_patch_manifest.json"
        if default_patch_manifest_path.exists():
            resolved_patch_manifest_path = default_patch_manifest_path
    patch_manifest = (
        _load_json(resolved_patch_manifest_path)
        if resolved_patch_manifest_path is not None
        and resolved_patch_manifest_path.exists()
        else None
    )
    attempts = []
    for path in attempt_paths:
        payload = _load_json(path)
        rows_from_payload = _attempt_rows_from_payload(payload)
        for row_index, raw_attempt in enumerate(rows_from_payload):
            attempt = _normalize_legacy_actual_compute_attempt(raw_attempt)
            if attempt.get("opportunity_id"):
                source = str(path)
                if len(rows_from_payload) > 1:
                    source = f"{source}#row={row_index}"
                attempt["source_attempt_artifact"] = source
            attempts.append(attempt)
    accelerated_numeric_rows = _load_accelerated_numeric_rows(
        accelerated_numeric_evidence_paths
    )
    workload_variants = build_workload_variant_search_space(manifest)
    bundles = build_offload_bundle_search_space(manifest)
    bundle_runtime_contract = build_bundle_runtime_contract_report(
        bundles,
        opportunity_manifest=manifest,
    )
    bundle_harness_readiness = build_bundle_harness_readiness_report(
        bundles,
        patch_manifest or {"patch_rows": [], "deliverable_complete": False},
        runtime_capabilities=bundle_runtime_contract,
    )
    static_candidate_summary = dict(
        dict(inventory.get("static_callgraph") or {}).get(
            "offload_candidate_summary"
        )
        or {}
    )
    attempt_queue = build_l4_offload_attempt_queue(
        bundles,
        static_candidate_summary=static_candidate_summary,
    )
    identity_schema = build_offload_target_identity_schema()
    source_attempt_artifacts = {
        str(opportunity_id): str(attempt.get("source_attempt_artifact"))
        for opportunity_id, attempt in _best_evidence_rows_by_opportunity(
            attempts
        ).items()
        if attempt.get("source_attempt_artifact")
    }
    matrix = build_offload_value_l4_evidence_matrix(manifest, attempts)
    blocker_report = build_callgraph_offload_blocker_report(
        inventory,
        matrix,
        attempts,
        source_attempt_artifacts,
    )
    speed_report = build_l4_speed_optimization_report(matrix, attempts)
    repeatability_report = build_l4_value_repeatability_report(speed_report)
    value_report = build_offload_value_report(
        matrix,
        repeatability_report=repeatability_report,
    )
    selection_report = build_offload_selection_search_report(
        manifest,
        matrix,
        blocker_report,
        workload_variants,
        repeatability_report=repeatability_report,
    )
    replacement_report = build_accelerated_replacement_readiness_report(
        matrix,
        attempts,
        source_attempt_artifacts,
        opportunity_manifest=manifest,
        accelerated_numeric_evidence_rows=accelerated_numeric_rows,
        patch_manifest=patch_manifest,
    )
    bundle_viability_report = build_offload_bundle_viability_report(
        bundles,
        matrix,
        replacement_report,
        speed_report,
        repeatability_report,
    )
    bundle_campaign_statuses = _load_bundle_campaign_statuses(
        attempt_paths=attempt_paths,
        bundle_campaign_status_paths=bundle_campaign_status_paths,
    )
    bundle_single_workflow_report = (
        build_bundle_single_workflow_l4_evidence_report(
            bundles,
            bundle_campaign_statuses,
        )
    )
    checklist = build_prompt_to_artifact_checklist(
        inventory=inventory,
        opportunities=manifest,
        workload_variants=workload_variants,
        bundles=bundles,
        patches=patch_manifest or {"rows": [], "deliverable_complete": False},
        attempt_queue=attempt_queue,
        matrix=matrix,
        value_report=value_report,
        blocker_report=blocker_report,
        replacement_report=replacement_report,
        bundle_viability_report=bundle_viability_report,
        bundle_runtime_contract=bundle_runtime_contract,
        bundle_harness_readiness=bundle_harness_readiness,
        selection_report=selection_report,
        identity_schema=identity_schema,
        speed_report=speed_report,
        bundle_single_workflow_report=bundle_single_workflow_report,
    )
    status = {
        "schema_version": "dse.qe_callgraph_offload_l4_multi_probe_status.v1",
        "status": "partial_or_blocked",
        "attempt_count": len(attempts),
        "attempted_opportunity_ids": [
            str(attempt.get("opportunity_id")) for attempt in attempts
        ],
        "attempted_kernels": [attempt.get("kernel") for attempt in attempts],
        "value_counts": matrix.get("value_counts", {}),
        "valuable_l4_count": matrix.get("valuable_l4_count", 0),
        "actual_compute_full_qe_evidence_required": matrix.get(
            "actual_compute_full_qe_evidence_required"
        ),
        "non_smoke_actual_compute_attempt_count": matrix.get(
            "non_smoke_actual_compute_attempt_count", 0
        ),
        "actual_compute_attempted_kernels": matrix.get(
            "actual_compute_attempted_kernels", []
        ),
        "actual_compute_attempted_kernel_count": matrix.get(
            "actual_compute_attempted_kernel_count", 0
        ),
        "actual_compute_attempted_kernel_counts": matrix.get(
            "actual_compute_attempted_kernel_counts", {}
        ),
        "non_hpsi_actual_compute_attempt_count": matrix.get(
            "non_hpsi_actual_compute_attempt_count", 0
        ),
        "non_hpsi_non_spsi_actual_compute_attempt_count": matrix.get(
            "non_hpsi_non_spsi_actual_compute_attempt_count", 0
        ),
        "non_hpsi_non_spsi_actual_compute_blocked_count": matrix.get(
            "non_hpsi_non_spsi_actual_compute_blocked_count", 0
        ),
        "actual_compute_full_qe_evidence_passed_count": matrix.get(
            "actual_compute_full_qe_evidence_passed_count", 0
        ),
        "actual_compute_not_valuable_l4_count": matrix.get(
            "actual_compute_not_valuable_l4_count", 0
        ),
        "actual_compute_full_qe_evidence_blocked_count": matrix.get(
            "actual_compute_full_qe_evidence_blocked_count", 0
        ),
        "smoke_dataflow_only_value_blocked_count": matrix.get(
            "smoke_dataflow_only_value_blocked_count", 0
        ),
        "smoke_value_allowed": matrix.get("smoke_value_allowed"),
        "best_speedup_vs_pure_qe": speed_report.get("best_speedup_vs_pure_qe"),
        "best_replacement_ready_speedup_vs_pure_qe": speed_report.get(
            "best_replacement_ready_speedup_vs_pure_qe"
        ),
        "baseline_gpu_context_observed_count": speed_report.get(
            "baseline_gpu_context_observed_count", 0
        ),
        "baseline_gpu_available_count": speed_report.get(
            "baseline_gpu_available_count", 0
        ),
        "replacement_ready_non_positive_speed_count": speed_report.get(
            "replacement_ready_non_positive_speed_count", 0
        ),
        "repeatability_stable_valuable_l4_count": repeatability_report.get(
            "repeatability_stable_valuable_l4_count", 0
        ),
        "repeatability_mixed_count": repeatability_report.get(
            "repeatability_mixed_count", 0
        ),
        "speed_mixed_count": repeatability_report.get("speed_mixed_count", 0),
        "single_positive_unconfirmed_count": repeatability_report.get(
            "single_positive_unconfirmed_count", 0
        ),
        "value_gate_not_passed_count": repeatability_report.get(
            "value_gate_not_passed_count", 0
        ),
        "bundle_level_valuable_l4_count": bundle_viability_report.get(
            "bundle_level_valuable_l4_count", 0
        ),
        "bundle_single_workflow_l4_evidence_status": (
            bundle_single_workflow_report.get("status")
        ),
        "bundle_single_workflow_campaign_status_count": (
            bundle_single_workflow_report.get("campaign_status_count", 0)
        ),
        "bundle_single_workflow_bundle_level_valuable_l4_count": (
            bundle_single_workflow_report.get("bundle_level_valuable_l4_count", 0)
        ),
        "per_opportunity_expanded_campaign_bundle_count": (
            bundle_single_workflow_report.get(
                "per_opportunity_expanded_campaign_bundle_count", 0
            )
        ),
        "formal_workload_variant_count": workload_variants.get(
            "formal_workload_variant_count", 0
        ),
        "bundle_runtime_contract_ready_bundle_count": bundle_runtime_contract.get(
            "runtime_contract_ready_bundle_count", 0
        ),
        "ready_bundle_harness_count": bundle_harness_readiness.get(
            "ready_bundle_harness_count", 0
        ),
        "blocked_bundle_harness_count": bundle_harness_readiness.get(
            "blocked_bundle_harness_count", 0
        ),
        "larger_granularity_bundle_count": bundle_viability_report.get(
            "larger_granularity_bundle_count", 0
        ),
        "bundles_with_raw_valuable_members_count": bundle_viability_report.get(
            "bundles_with_raw_valuable_members_count", 0
        ),
        "bundles_with_stable_repeatable_members_count": bundle_viability_report.get(
            "bundles_with_stable_repeatable_members_count", 0
        ),
        "single_workflow_bundle_candidates_with_stable_members_count": (
            bundle_viability_report.get(
                "single_workflow_bundle_candidates_with_stable_members_count",
                0,
            )
        ),
        "stable_repeatable_member_configuration_count": (
            bundle_viability_report.get(
                "stable_repeatable_member_configuration_count",
                0,
            )
        ),
        "persistent_or_batched_dispatch_required_count": speed_report.get(
            "persistent_or_batched_dispatch_required_count", 0
        ),
        "replacement_writeback_required_count": speed_report.get(
            "replacement_writeback_required_count", 0
        ),
        "replacement_ready_count": replacement_report.get(
            "replacement_ready_count", 0
        ),
        "target_kernel_mismatch_count": replacement_report.get(
            "target_kernel_mismatch_count", 0
        ),
        "accelerated_results_consumed_by_qe_count": replacement_report.get(
            "accelerated_results_consumed_by_qe_count", 0
        ),
        "accelerated_results_observed_by_qe_before_strict_replacement_count": (
            replacement_report.get(
                "accelerated_results_observed_by_qe_before_strict_replacement_count",
                0,
            )
        ),
        "qe_kernel_work_replaced_on_critical_path_count": replacement_report.get(
            "qe_kernel_work_replaced_on_critical_path_count", 0
        ),
        "software_fallback_on_critical_path_count": replacement_report.get(
            "software_fallback_on_critical_path_count", 0
        ),
        "external_accelerated_results_consumed_by_qe_count": replacement_report.get(
            "external_accelerated_results_consumed_by_qe_count", 0
        ),
        "external_consumed_but_blocked_count": replacement_report.get(
            "external_consumed_but_blocked_count", 0
        ),
        "patch_precheck_trusted_l4_replacement_candidate_count": replacement_report.get(
            "patch_precheck_trusted_l4_replacement_candidate_count", 0
        ),
        "prompt_to_artifact_checklist_status": checklist.get("status"),
        "prompt_to_artifact_checklist_hash": checklist.get("checklist_hash"),
        "deliverable_complete": False,
        "source_attempt_artifacts": [str(path) for path in attempt_paths],
        "source_accelerated_numeric_evidence_artifacts": [
            str(path) for path in accelerated_numeric_evidence_paths or []
        ],
        "source_patch_manifest_artifact": (
            str(resolved_patch_manifest_path)
            if resolved_patch_manifest_path is not None
            else None
        ),
        "source_bundle_campaign_status_artifacts": [
            str(status.get("status_path"))
            for status in bundle_campaign_statuses
            if status.get("status_path")
        ],
        "claim_boundary": (
            "multi-attempt probe broadens callgraph evidence; it is not "
            "completion and has no valuable_l4 row unless the matrix proves one"
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "qe_callgraph_inventory.json", inventory)
    _write_json(out_dir / "offload_opportunity_manifest.json", manifest)
    _write_json(
        out_dir / "offload_workload_variant_search_space.json",
        workload_variants,
    )
    _write_json(out_dir / "offload_target_identity_schema.json", identity_schema)
    _write_json(out_dir / "offload_bundle_search_space.json", bundles)
    _write_json(out_dir / "l4_offload_attempt_queue.json", attempt_queue)
    if patch_manifest is not None:
        _write_json(out_dir / "qe_callsite_patch_manifest.json", patch_manifest)
    _write_json(
        out_dir / "l4_offload_attempts.json",
        {
            "schema_version": "dse.qe_callgraph_l4_offload_attempts.v1",
            "attempts": attempts,
        },
    )
    _write_json(out_dir / "offload_value_l4_evidence_matrix.json", matrix)
    _write_json(out_dir / "offload_value_report.json", value_report)
    _write_json(out_dir / "callgraph_offload_blocker_report.json", blocker_report)
    _write_json(
        out_dir / "accelerated_replacement_readiness_report.json",
        replacement_report,
    )
    _write_json(out_dir / "offload_selection_search_report.json", selection_report)
    _write_json(out_dir / "offload_speed_optimization_report.json", speed_report)
    _write_json(out_dir / "offload_value_repeatability_report.json", repeatability_report)
    _write_json(out_dir / "offload_bundle_viability_report.json", bundle_viability_report)
    _write_json(
        out_dir / "bundle_single_workflow_l4_evidence_report.json",
        bundle_single_workflow_report,
    )
    _write_json(out_dir / "bundle_runtime_contract_report.json", bundle_runtime_contract)
    _write_json(out_dir / "bundle_harness_readiness_report.json", bundle_harness_readiness)
    _write_json(out_dir / "prompt_to_artifact_checklist.json", checklist)
    _write_text(
        out_dir / "offload_value_report.md",
        render_offload_value_report_markdown(value_report, matrix),
    )
    _write_text(
        out_dir / "callgraph_offload_blocker_report.md",
        render_callgraph_offload_blocker_report_markdown(blocker_report),
    )
    _write_text(
        out_dir / "accelerated_replacement_readiness_report.md",
        render_accelerated_replacement_readiness_report_markdown(
            replacement_report
        ),
    )
    _write_text(
        out_dir / "offload_selection_search_report.md",
        render_offload_selection_search_report_markdown(selection_report),
    )
    _write_text(
        out_dir / "offload_speed_optimization_report.md",
        render_l4_speed_optimization_report_markdown(speed_report),
    )
    _write_text(
        out_dir / "offload_value_repeatability_report.md",
        render_l4_value_repeatability_report_markdown(repeatability_report),
    )
    _write_text(
        out_dir / "offload_bundle_viability_report.md",
        render_offload_bundle_viability_report_markdown(bundle_viability_report),
    )
    _write_text(
        out_dir / "prompt_to_artifact_checklist.md",
        render_prompt_to_artifact_checklist_markdown(checklist),
    )
    _write_json(out_dir / "status.json", status)
    return status


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    parser.add_argument(
        "--accelerated-numeric-evidence",
        type=Path,
        action="append",
        default=[],
        help=(
            "Optional dse.qe_accelerated_numeric_evidence row or bundle. "
            "Rows may prove QE consumption but remain blocked unless trusted L4."
        ),
    )
    parser.add_argument(
        "--patch-manifest",
        type=Path,
        default=None,
        help=(
            "Optional qe_callsite_patch_manifest.json. If omitted, the builder "
            "uses qe_callsite_patch_manifest.json next to --manifest when present."
        ),
    )
    parser.add_argument(
        "--bundle-campaign-status",
        type=Path,
        action="append",
        default=[],
        help=(
            "Optional bundle actual-compute campaign status.json. Colocated "
            "status.json files next to --attempt paths are also auto-detected."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    status = build_multi_probe_report(
        out_dir=args.out,
        inventory_path=args.inventory,
        manifest_path=args.manifest,
        attempt_paths=args.attempt,
        accelerated_numeric_evidence_paths=args.accelerated_numeric_evidence,
        patch_manifest_path=args.patch_manifest,
        bundle_campaign_status_paths=args.bundle_campaign_status,
    )
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
