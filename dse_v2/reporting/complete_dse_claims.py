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
    "MVP_partial",
    "mvp_partial",
    "projection_only",
    "l4_trusted_speedup",
    "blocked",
    "deliverable_complete",
)

TRUSTED_ROW_CLAIM = "l4_trusted_speedup"
GOAL_COMPLETION_STATUS_TAXONOMY = (
    "vertical_slice_only",
    "MVP_partial",
    "blocked",
    "projection_only",
    "deliverable_complete",
)

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

TARGET_SCOPED_RECOMMENDATION_TARGETS = ("fpga", "asic")

CLAIMABLE_RECOMMENDATION_STATUSES = {
    "resolved_hardware_ppa_deployment_recommendation",
    "claimable",
    "selected",
    "selected_recommendation",
    "best_architecture",
    "pareto_frontier",
    "trusted_winner",
}

FORBIDDEN_TARGET_RECOMMENDATION_ROW_STATUSES = {
    "projection_only_not_claimable",
    "projection_only",
    "blocked_tool_unavailable",
    "tool_unavailable",
    "unavailable",
    "blocked_missing_input",
    "missing_input",
    "missing_evidence",
    "blocked_invalid_evidence",
    "invalid",
    "invalid_evidence",
    "missing",
    "stale",
    "forged",
    "smoke_only",
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

DONE_WHEN_4_6_AUDIT_ARTIFACTS = (
    "complete_dse_done_when_4_6_audit.json",
    "status.json",
)

TARGET_EVIDENCE_GATE_LEDGER_ARTIFACTS = (
    "dft_candidate_workflow_target_evidence_gate_ledger.json",
    "dft_candidate_workflow_target_evidence_gate_ledger_validation.json",
    "dft_candidate_workflow_target_evidence_gate_ledger_status.json",
)

RELEASE_PACKAGE_REPORTING_ARTIFACTS = (
    "complete_dse_release_artifact_package.json",
    "complete_dse_release_artifact_hash_manifest.json",
)

DEPLOYMENT_DECISION_SUMMARY_REPORTING_ARTIFACTS = (
    "dft_deployment_decision_summary.json",
)

RELEASE_UNIVERSE_REPORTING_ARTIFACTS = (
    "release_universe_manifest.json",
)

TARGET_EVIDENCE_MATRIX_REPORTING_ARTIFACTS = (
    "candidate_workflow_target_evidence_matrix.json",
)

TARGET_RECOMMENDATION_REPORTING_ARTIFACTS = (
    "fpga_recommendation_report.json",
    "asic_recommendation_report.json",
    "deployment_recommendation_report.json",
)

TARGET_TOOL_EVIDENCE_MANIFEST_ARTIFACTS = (
    "fpga_hls_rtl_vivado_evidence_manifest.json",
    "asic_dc_timing_area_evidence_manifest.json",
)

TOOLCHAIN_TRANSCRIPT_REPORTING_ARTIFACTS = (
    "ic_eda_tool_availability.json",
    "ic_eda_tool_attempts.json",
    "ic_eda_toolchain_transcript_manifest.json",
)

QE_BASELINE_MATERIALIZATION_REPORTING_ARTIFACTS = (
    "dft_scf_six_class_qe_baseline_materialization.json",
    "dft_scf_six_class_qe_baseline_materialization_validation.json",
    "dft_scf_six_class_qe_baseline_materialization_status.json",
)

FULL_SCF_ACCOUNTING_REPORTING_ARTIFACTS = (
    "qe_baseline_comparison_index.json",
    *QE_BASELINE_MATERIALIZATION_REPORTING_ARTIFACTS,
    "qe_full_scf_hook_coverage_campaign_audit.json",
    "strict_full_scf_evidence_gap.json",
    "full_scf_runtime_event_manifest.json",
    "runtime_execution_proof.json",
    "full_scf_runtime_trace.json",
    "full_scf_row_accounting.json",
    "full_scf_end_to_end_comparison.json",
)
QE_BASELINE_ROW_ACCOUNTING_ATTACHMENT_ARTIFACTS = (
    "qe_baseline_comparison_index.json",
    "full_scf_row_accounting.json",
)
FULL_SCF_EVALUATED_HYBRID_STATUS_REQUIREMENT_IDS = (
    "done_when_11",
    "done_when_12",
    "done_when_13",
    "done_when_14",
    "done_when_15",
)

REQUIRED_COMPLETE_DSE_REPORT_ARTIFACTS = (
    "workload_architecture_prior_report.json",
    "architecture_prior_seed_manifest.json",
    "release_pruning_rationale_report.json",
    "release_candidate_trial_ledger.json",
    *DONE_WHEN_4_6_AUDIT_ARTIFACTS,
    *RELEASE_UNIVERSE_REPORTING_ARTIFACTS,
    *RELEASE_PACKAGE_REPORTING_ARTIFACTS,
    "architecture_candidate_generation_report.json",
    "candidate_generation_report.json",
    "architecture_screening_report.json",
    "performance_claim_policy.json",
    "l4_evidence_matrix_schema.json",
    "l4_evidence_matrix_report.json",
    "coverage_claim_report.json",
    "coverage_claim_report.md",
    "workload_coverage_report.json",
    "deployment_boundary_search_report.json",
    *DEPLOYMENT_DECISION_SUMMARY_REPORTING_ARTIFACTS,
    *TARGET_EVIDENCE_MATRIX_REPORTING_ARTIFACTS,
    *TARGET_RECOMMENDATION_REPORTING_ARTIFACTS,
    *TARGET_TOOL_EVIDENCE_MANIFEST_ARTIFACTS,
    "candidate_workflow_evidence_ledger.json",
    *TARGET_EVIDENCE_GATE_LEDGER_ARTIFACTS,
    *TOOLCHAIN_TRANSCRIPT_REPORTING_ARTIFACTS,
    *FULL_SCF_ACCOUNTING_REPORTING_ARTIFACTS,
    "claim_validation_report.json",
    "blocker_report.json",
    "artifact_hash_manifest.json",
    "requirement_evidence_matrix.json",
    "requirement_evidence_matrix.md",
    "prompt_to_artifact_checklist.json",
    "prompt_to_artifact_checklist.md",
)

GOAL_REQUIREMENT_EVIDENCE_SPECS: tuple[Dict[str, Any], ...] = (
    {
        "requirement_id": "done_when_01",
        "source": "docs/goal.md Done when 1",
        "requirement": "Adaptive five-slot preflight checkpoint proves intended lane topology, per-slot team plan, model routing, process-backed launch commands/configs, smoke-debug evidence, and completion-detection evidence.",
        "artifact_names": (
            ".omx/context/adaptive-five-slot-preflight-<timestamp>.md",
        ),
        "artifact_policy": "all",
    },
    {
        "requirement_id": "done_when_02",
        "source": "docs/goal.md Done when 2",
        "requirement": "Preflight and each slot handoff prove Superpowers/skills workflow: using-superpowers loaded first, slice skills named, and verification/completion gates recorded.",
        "artifact_names": (
            ".omx/context/adaptive-five-slot-preflight-<timestamp>.md",
            ".omx/worker-runs/adaptive-five-slot-<timestamp>/slot*/final.md",
        ),
        "artifact_policy": "all",
    },
    {
        "requirement_id": "done_when_03",
        "source": "docs/goal.md Done when 3",
        "requirement": "The required active slots for each wave each completed a verified handoff or recorded a concrete monitor-classified blocker with exact commands, artifacts, next action, and no silent idle, misassignment, lost before wrapper.done, terminal-artifact-incomplete timeout, or blanket xhigh.",
        "artifact_names": (
            ".omx/worker-runs/adaptive-five-slot-<timestamp>/slot*/final.md",
            ".omx/worker-runs/adaptive-five-slot-<timestamp>/slot*/monitor.summary",
        ),
        "artifact_policy": "all",
    },
    {
        "requirement_id": "done_when_04",
        "source": "docs/goal.md Done when 4",
        "requirement": "North-star QE workload-to-FPGA/ASIC DSE system spec covers deployment-boundary search, runtime/co-scheduling search, FPGA/ASIC/CIM-template semantics, evidence gates, and claim boundaries.",
        "artifact_names": (
            "north_star_system_spec.md",
            ".omx/context/north_star_checkpoint.md",
            "docs/architecture/qe_fpga_asic_dse.md",
        ),
        "artifact_policy": "any",
        "required_artifact_names": DONE_WHEN_4_6_AUDIT_ARTIFACTS,
    },
    {
        "requirement_id": "done_when_05",
        "source": "docs/goal.md Done when 5",
        "requirement": "QE workflow input contract represents input bundles, pseudopotentials, stages, dependencies, artifacts, correctness tolerances/oracles, baseline commands, and hardware-relevant features.",
        "artifact_names": (
            "qe_workload_contract.json",
            "qe_input_bundle_manifest.json",
            "qe_correctness_oracle.json",
        ),
        "artifact_policy": "all",
        "required_artifact_names": DONE_WHEN_4_6_AUDIT_ARTIFACTS,
    },
    {
        "requirement_id": "done_when_06",
        "source": "docs/goal.md Done when 6",
        "requirement": "Finite reproducible release universe includes workload cases, deployment boundaries, architecture templates/modules, mapping/layout policies, runtime/co-scheduling policies, target platforms, legality/pruning decisions, and stable candidate IDs.",
        "artifact_names": (
            "release_universe_manifest.json",
            "candidate_generation_report.json",
            "architecture_candidate_generation_report.json",
            "release_pruning_rationale_report.json",
        ),
        "artifact_policy": "all",
        "required_artifact_names": (
            *DONE_WHEN_4_6_AUDIT_ARTIFACTS,
            *RELEASE_PACKAGE_REPORTING_ARTIFACTS,
        ),
    },
    {
        "requirement_id": "done_when_07",
        "source": "docs/goal.md Done when 7",
        "requirement": "Complete candidate x workflow-case x deployment-boundary x target x evidence-gate matrix uses only trusted_pass, trusted_fail, pruned_with_reason, blocked_missing_input, blocked_tool_unavailable, blocked_invalid_evidence, or projection_only_not_claimable rows.",
        "artifact_names": (
            "candidate_workflow_target_evidence_matrix.json",
            "l4_evidence_matrix_report.json",
        ),
        "artifact_policy": "all",
        "required_artifact_names": TARGET_EVIDENCE_GATE_LEDGER_ARTIFACTS,
    },
    {
        "requirement_id": "done_when_08",
        "source": "docs/goal.md Done when 8",
        "requirement": "Separate best/Pareto FPGA and best/Pareto ASIC recommendations include deployment boundary, architecture/modules, mapping/layout, runtime/co-schedule, expected metrics, comparison rationale, evidence level, blockers, and claim boundaries.",
        "artifact_names": (
            "fpga_recommendation_report.json",
            "asic_recommendation_report.json",
            "deployment_recommendation_report.json",
        ),
        "artifact_policy": "all",
        "required_target_claims": ("fpga", "asic"),
    },
    {
        "requirement_id": "done_when_09",
        "source": "docs/goal.md Done when 9",
        "requirement": "FPGA recommendations are gated by FPGA-appropriate HLS/RTL simulation or synthesis plus Vivado synthesis/implementation/timing/utilization evidence when claimed, or marked blocked/projection-only.",
        "artifact_names": (
            "fpga_recommendation_report.json",
            "fpga_hls_rtl_vivado_evidence_manifest.json",
        ),
        "artifact_policy": "all",
        "required_target_claims": ("fpga",),
    },
    {
        "requirement_id": "done_when_10",
        "source": "docs/goal.md Done when 10",
        "requirement": "ASIC recommendations are gated by ASIC-appropriate RTL simulation plus Synopsys DC synthesis/timing/area/power evidence when claimed, or marked blocked/projection-only.",
        "artifact_names": (
            "asic_recommendation_report.json",
            "asic_dc_timing_area_evidence_manifest.json",
        ),
        "artifact_policy": "all",
        "required_target_claims": ("asic",),
    },
    {
        "requirement_id": "done_when_11",
        "source": "docs/goal.md Done when 11",
        "requirement": "System-level evidence includes descriptor/runtime ABI accounting, SystemC/generic simulator evidence, gem5 GenericAccel descriptor/completion evidence where feasible, QE-side correctness/baseline comparison, transfer/sync accounting, and CPU-retained stage accounting.",
        "artifact_names": (
            "system_level_evidence_report.json",
            "runtime_abi_accounting.json",
            "generic_systemc_evidence.json",
            "gem5_genericaccel_evidence.json",
            *FULL_SCF_ACCOUNTING_REPORTING_ARTIFACTS,
        ),
        "artifact_policy": "all",
    },
    {
        "requirement_id": "done_when_12",
        "source": "docs/goal.md Done when 12",
        "requirement": "Final reporting package: requirement-evidence matrix, coverage, deployment search, generation/provenance, ledger, validation, blockers, hashes, checklist.",
        "artifact_names": (
            "requirement_evidence_matrix.json",
            "workload_coverage_report.json",
            "deployment_boundary_search_report.json",
            *DEPLOYMENT_DECISION_SUMMARY_REPORTING_ARTIFACTS,
            *TARGET_EVIDENCE_MATRIX_REPORTING_ARTIFACTS,
            "candidate_generation_report.json",
            "candidate_workflow_evidence_ledger.json",
            *DONE_WHEN_4_6_AUDIT_ARTIFACTS,
            *RELEASE_UNIVERSE_REPORTING_ARTIFACTS,
            *RELEASE_PACKAGE_REPORTING_ARTIFACTS,
            *TARGET_EVIDENCE_GATE_LEDGER_ARTIFACTS,
            *TOOLCHAIN_TRANSCRIPT_REPORTING_ARTIFACTS,
            *FULL_SCF_ACCOUNTING_REPORTING_ARTIFACTS,
            "claim_validation_report.json",
            "blocker_report.json",
            "artifact_hash_manifest.json",
            "prompt_to_artifact_checklist.json",
        ),
        "artifact_policy": "all",
    },
    {
        "requirement_id": "done_when_13",
        "source": "docs/goal.md Done when 13",
        "requirement": "Adversarial fail-closed audits for forged evidence, missing rows, top-k/fixed-candidate downgrades, smoke-only evidence, projection-only evidence, tool-unavailable evidence, and incomplete full-workflow accounting.",
        "artifact_names": (
            "adversarial_audit_report.json",
            "anti_downgrade_test_report.json",
            "qe_full_scf_hook_coverage_campaign_audit.json",
            "strict_full_scf_evidence_gap.json",
        ),
        "artifact_policy": "all",
    },
    {
        "requirement_id": "done_when_14",
        "source": "docs/goal.md Done when 14",
        "requirement": "Fresh verification evidence exists: targeted Python tests, compileall, relevant SystemC/generic simulator build/ctest or blocker, relevant pilot/full-flow scripts or blocker, gem5/L4 evidence or blocker, and IC/EDA attempts when FPGA/ASIC numeric claims are implicated.",
        "artifact_names": (
            "verification_evidence_report.json",
            "python_test_report.txt",
            "compileall_report.txt",
            "systemc_ctest_report.txt",
            "pilot_full_flow_report.txt",
            "gem5_l4_evidence_report.json",
            "ic_eda_tool_attempts.json",
            "ic_eda_tool_availability.json",
            "ic_eda_toolchain_transcript_manifest.json",
        ),
        "artifact_policy": "all",
    },
    {
        "requirement_id": "done_when_15",
        "source": "docs/goal.md Done when 15",
        "requirement": "Final status explicitly distinguishes vertical_slice_only, MVP_partial, blocked, projection_only, and deliverable_complete; deliverable_complete is false unless every claimed FPGA/ASIC recommendation has matching evidence gates.",
        "artifact_names": (
            "final_status_report.json",
            "claim_validation_report.json",
            "fpga_recommendation_report.json",
            "asic_recommendation_report.json",
        ),
        "artifact_policy": "all",
        "required_target_claims": ("fpga", "asic"),
    },
    {
        "requirement_id": "done_when_16",
        "source": "docs/goal.md Done when 16",
        "requirement": "The round lifecycle is actually used: each wave has preflight, parallel dispatch, quiet follow-up, and barrier integration records; the master does not stop after the first successful slot unless the global Done when list is satisfied.",
        "artifact_names": (
            ".omx/context/adaptive-five-slot-preflight-<timestamp>.md",
            ".omx/context/adaptive-five-slot-round-<timestamp>.md",
            ".omx/worker-runs/adaptive-five-slot-<timestamp>/slot*/final.md",
            ".omx/worker-runs/adaptive-five-slot-<timestamp>/slot*/monitor.summary",
            ".omx/context/adaptive-five-slot-barrier-<timestamp>.md",
        ),
        "artifact_policy": "all",
    },
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


def _write_json(
    path: Path, payload: Mapping[str, Any] | Sequence[Any]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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


def _artifact_ref_from_payload(
    path: Path,
    *,
    base_dir: Path,
    payload: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    ref = _artifact_ref(path, base_dir=base_dir)
    if payload:
        for key in (
            "status",
            "evidence_status",
            "complete",
            "completion_complete",
            "deliverable_complete",
            "valid",
            "validation_valid",
            "projection_only",
            "smoke_only",
            "stale",
            "forged",
            "exists",
            "availability_only_not_kernel_ppa",
            "kernel_ppa_evidence",
            "hardware_completion_eligible",
            "raw_command_transcript_ref_count",
            "release_candidate_identity_provenance_status",
            "release_candidate_identity_provenance_blocker_ids",
            "release_candidate_identity_provenance_package_exists",
            "release_candidate_identity_provenance_package_status",
            "release_candidate_identity_provenance_canonical_bundle_bound",
            "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity",
            "release_candidate_identity_provenance_claim_boundary",
            "claim_upgrade_allowed_count",
            "availability_probe_only_row_count",
            "replayable_tool_transcript_ref_count",
            "candidate_kernel_axis_unbound_row_count",
            "candidate_kernel_axis_bound_row_count",
            "candidate_kernel_axis_unbound_stage_count",
            "parsed_stage_result_ref_count",
        ):
            if key in payload:
                ref[key] = payload[key]
        if "stable_blocker_reason_counts" in payload:
            ref["stable_blocker_reason_counts"] = _json_safe_artifact_ref_value(
                payload["stable_blocker_reason_counts"]
            )
        release_identity_provenance = payload.get(
            "release_candidate_identity_provenance"
        )
        if isinstance(release_identity_provenance, Mapping):
            ref["release_candidate_identity_provenance_status"] = (
                release_identity_provenance.get("status")
            )
            ref["release_candidate_identity_provenance_blocker_ids"] = (
                _json_safe_artifact_ref_value(
                    release_identity_provenance.get("blocker_ids", [])
                )
            )
            ref[
                "release_candidate_identity_provenance_package_status"
            ] = payload.get("status")
            ref[
                "release_candidate_identity_provenance_canonical_bundle_bound"
            ] = bool(release_identity_provenance.get("canonical_bundle_bound", False))
            ref[
                "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity"
            ] = bool(
                release_identity_provenance.get(
                    "trusted_for_release_package_candidate_identity", False
                )
            )
        if "raw_command_transcript_refs" in payload:
            ref["raw_command_transcript_refs"] = _json_safe_artifact_ref_value(
                payload["raw_command_transcript_refs"]
            )
        if "decision_summary_inputs" in payload:
            ref["decision_summary_inputs"] = _json_safe_artifact_ref_value(
                payload["decision_summary_inputs"]
            )
    return ref


def _merge_source_artifact_refs(
    required_refs: Dict[str, Dict[str, Any]],
    source_artifact_refs: Mapping[str, Any] | None,
) -> None:
    if not source_artifact_refs:
        return
    for artifact_name, artifact_ref in source_artifact_refs.items():
        if artifact_name not in REQUIRED_COMPLETE_DSE_REPORT_ARTIFACTS:
            continue
        if not isinstance(artifact_ref, Mapping):
            continue
        normalised = _json_safe_artifact_ref_value(dict(artifact_ref))
        if not isinstance(normalised, dict):
            continue
        normalised.setdefault("path", artifact_name)
        if normalised.get("sha256"):
            normalised.setdefault("hash_algorithm", "sha256")
        required_refs[str(artifact_name)] = normalised


def _derived_deployment_decision_summary_ref(
    source_artifact_refs: Mapping[str, Any] | None,
) -> Dict[str, Any] | None:
    if not source_artifact_refs:
        return None
    package_ref = source_artifact_refs.get("complete_dse_release_artifact_package.json")
    if not isinstance(package_ref, Mapping):
        return None
    decision_summary_inputs = package_ref.get("decision_summary_inputs")
    if not isinstance(decision_summary_inputs, Mapping):
        return None
    decision_summary_ref = decision_summary_inputs.get("deployment_decision_summary")
    if not isinstance(decision_summary_ref, Mapping):
        return None
    if not decision_summary_ref.get("path") or not decision_summary_ref.get("sha256"):
        return None
    derived = {
        str(key): _json_safe_artifact_ref_value(value)
        for key, value in decision_summary_ref.items()
    }
    derived.setdefault("path", str(decision_summary_ref.get("path")))
    derived.setdefault("hash_algorithm", "sha256")
    derived.setdefault("source_lane", package_ref.get("source_lane", "run1"))
    derived.setdefault(
        "source_alias_path",
        "complete_dse_release_artifact_package.json:decision_summary_inputs.deployment_decision_summary",
    )
    derived.setdefault("required", False)
    derived.setdefault("exists", True)
    derived.setdefault("status", "deployment_decision_summary_available")
    derived.setdefault("deliverable_complete", False)
    derived.setdefault("trusted_final_claim", False)
    derived.setdefault(
        "claim_boundary",
        "Deployment decision summary source refs are bound through the release package only and remain fail-closed for completion claims.",
    )
    return derived


def _normalise_ids(values: Iterable[str] | None) -> list[str]:
    return sorted({str(value) for value in values or []})


def _row_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("candidate_id", "")), str(
        row.get("workload_case_id", "")
    )


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list_of_mappings(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _qe_baseline_materialization_source_refs(
    source_artifact_refs: Mapping[str, Any] | None,
) -> tuple[Dict[str, Dict[str, Any]], list[str]]:
    refs: Dict[str, Dict[str, Any]] = {}
    missing: list[str] = []
    if not source_artifact_refs:
        return refs, list(QE_BASELINE_MATERIALIZATION_REPORTING_ARTIFACTS)
    for artifact_name in QE_BASELINE_MATERIALIZATION_REPORTING_ARTIFACTS:
        artifact_ref = source_artifact_refs.get(artifact_name)
        if (
            isinstance(artifact_ref, Mapping)
            and artifact_ref.get("path")
            and artifact_ref.get("sha256")
        ):
            refs[artifact_name] = {
                str(key): _json_safe_artifact_ref_value(value)
                for key, value in artifact_ref.items()
            }
            refs[artifact_name].setdefault("hash_algorithm", "sha256")
            continue
        missing.append(artifact_name)
    return refs, missing


def _workload_case_binding_status(
    artifact_refs: Mapping[str, Mapping[str, Any]],
    workload_case_id: str,
) -> tuple[str, list[str]]:
    if not workload_case_id:
        return "row_key_missing", ["candidate_workflow_row_workload_case_id_missing"]

    missing_binding: list[str] = []
    mismatched_binding: list[str] = []
    for artifact_name, artifact_ref in artifact_refs.items():
        direct_id = artifact_ref.get("workload_case_id")
        direct_ids = artifact_ref.get("workload_case_ids")
        if direct_id is not None:
            if str(direct_id) == workload_case_id:
                continue
            mismatched_binding.append(str(artifact_name))
            continue
        if isinstance(direct_ids, Sequence) and not isinstance(
            direct_ids, (str, bytes)
        ):
            if workload_case_id in {str(item) for item in direct_ids}:
                continue
            mismatched_binding.append(str(artifact_name))
            continue
        missing_binding.append(str(artifact_name))

    if mismatched_binding:
        return (
            "workload_case_mismatch",
            [
                "qe_baseline_materialization_workload_case_id_mismatch:"
                + ",".join(sorted(mismatched_binding))
            ],
        )
    if missing_binding:
        return (
            "package_level_unbound",
            ["qe_baseline_materialization_workload_case_id_missing"],
        )
    return "source_bound", []


def _candidate_workflow_ledger_rows_with_qe_baseline_materialization(
    rows: Sequence[Mapping[str, Any]],
    source_artifact_refs: Mapping[str, Any] | None,
) -> list[Dict[str, Any]]:
    source_refs, missing_artifact_names = _qe_baseline_materialization_source_refs(
        source_artifact_refs
    )
    ledger_rows = [dict(row) for row in rows]
    if not source_refs:
        return ledger_rows

    artifact_names = list(QE_BASELINE_MATERIALIZATION_REPORTING_ARTIFACTS)
    for ledger_row in ledger_rows:
        candidate_id, workload_case_id = _row_key(ledger_row)
        evidence_refs = ledger_row.get("evidence_refs", {})
        if not isinstance(evidence_refs, Mapping):
            evidence_refs = {}
        binding_status, blockers = _workload_case_binding_status(
            source_refs,
            workload_case_id,
        )
        if missing_artifact_names:
            blockers = [
                *blockers,
                "qe_baseline_materialization_triplet_incomplete:"
                + ",".join(sorted(missing_artifact_names)),
            ]
        ledger_row["evidence_refs"] = {
            **dict(evidence_refs),
            "pure_software_qe_baseline_materialization": {
                "schema_version": "dse.complete_dse.pure_software_qe_baseline_materialization_ref.v1",
                "candidate_id": candidate_id,
                "workload_case_id": workload_case_id,
                "artifact_names": artifact_names,
                "artifact_refs": source_refs,
                "workload_case_binding_status": binding_status,
                "blockers": sorted(dict.fromkeys(blockers)),
                "pure_software_qe_baseline": True,
                "claim_upgrade_allowed": False,
                "hardware_acceleration_evidence": False,
                "target_ppa_evidence": False,
                "hardware_completion_eligible": False,
                "release_completion_eligible": False,
                "trusted_final_claim": False,
                "deliverable_complete": False,
                "claim_boundary": (
                    "QE baseline materialization is pure-software baseline input "
                    "evidence for the candidate/workload row. It cannot satisfy "
                    "target FPGA/ASIC PPA gates, hardware completion, release "
                    "completion, or deliverable_complete."
                ),
            },
        }
        ledger_row["pure_software_qe_baseline_materialization_attached"] = True
        ledger_row["pure_software_qe_baseline_materialization_binding_status"] = (
            binding_status
        )
    return ledger_rows


def _collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.lower()]
    if isinstance(value, Mapping):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_collect_strings(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_collect_strings(item))
        return strings
    return []


def _common_payload(status: str) -> Dict[str, Any]:
    return {
        "schema_version": "dse.complete_dse.reporting.v1",
        "generated_at": _now_iso(),
        "status": status,
        "claim_labels": list(CLAIM_LABELS),
        "status_taxonomy": list(GOAL_COMPLETION_STATUS_TAXONOMY),
        "anti_downgrade_rules": list(ANTI_DOWNGRADE_RULES),
        "claim_boundary": (
            "Drafts, vertical slices, MVPs, projections, blockers, Top-K subsets, "
            "representative subsets, descriptor-only paths, and tool-unavailable "
            "rows are reportable audit facts but cannot satisfy deliverable_complete."
        ),
    }


def _blocked_report_payload(
    *,
    schema_version: str,
    blocker: str,
    status: str = "blocked",
    claim_boundary: str | None = None,
    **fields: Any,
) -> Dict[str, Any]:
    return {
        **_common_payload(status),
        "schema_version": schema_version,
        "status": status,
        "complete": False,
        "completion_complete": False,
        "deliverable_complete": False,
        "blockers": [blocker],
        "claim_boundary": claim_boundary
        or "This artifact is present for package traceability only and cannot satisfy deliverable_complete.",
        **fields,
    }


def _target_recommendation_report_payload(
    target: str,
    *,
    candidate_id: str,
    producer_artifact_name: str,
    evidence_manifest_name: str,
    producer_artifact_refs: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    recommendation_kind = "best_or_pareto"
    producer_refs = {
        str(name): dict(ref)
        for name, ref in (producer_artifact_refs or {}).items()
        if isinstance(ref, Mapping)
    }
    required_target_evidence = (
        [
            "golden_correctness",
            "hls_or_rtl_sim",
            "hls_or_rtl_synth",
            "vivado_fpga_synth_or_impl",
        ]
        if target == "fpga"
        else [
            "golden_correctness",
            "rtl_sim",
            "dc_asic_synth_timing_area",
        ]
    )
    manifest_name = evidence_manifest_name
    return {
        **_common_payload("blocked"),
        "schema_version": f"dse.complete_dse.{target}_recommendation_report.v1",
        "target": target,
        "recommendation_kind": recommendation_kind,
        "candidate_id": candidate_id,
        "status": "blocked_missing_target_scoped_evidence",
        "best": {
            "candidate_id": candidate_id,
            "status": "blocked_missing_target_scoped_evidence",
            "evidence_level": "projection_only",
            "producer_artifact_refs": producer_refs,
            "claim_boundary": (
                f"{target.upper()} best recommendation remains blocked until "
                "target-scoped evidence closes."
            ),
        },
        "pareto": {
            "candidate_id": candidate_id,
            "status": "blocked_missing_target_scoped_evidence",
            "evidence_level": "projection_only",
            "producer_artifact_refs": producer_refs,
            "claim_boundary": (
                f"{target.upper()} Pareto recommendation remains blocked until "
                "target-scoped evidence closes."
            ),
        },
        "deployment_boundary": "full_scf_evaluated_hybrid",
        "architecture_modules": [],
        "mapping_layout": {},
        "runtime_co_schedule": {},
        "expected_metrics": {},
        "comparison_rationale": (
            "Blocked recommendation surface derived from report-package consumer "
            "contracts only; no target-claim upgrade is implied."
        ),
        "evidence_level": "projection_only",
        "blockers": [
            f"{producer_artifact_name}:missing_required_artifact",
            f"{manifest_name}:missing_required_artifact",
        ],
        "claim_boundary": (
            f"{target.upper()} recommendation reporting is fail-closed until "
            "producer evidence and target-scoped rows are available."
        ),
        "required_target_evidence": required_target_evidence,
        "evidence_manifest_artifact": manifest_name,
        "producer_artifact_name": producer_artifact_name,
        "producer_artifact_refs": producer_refs,
        "producer_artifact_ref_count": len(producer_refs),
        "deliverable_complete": False,
        "trusted_final_claim": False,
    }


def _target_tool_evidence_manifest_payload(
    target: str,
    *,
    producer_artifact_name: str,
    stage_ids: Sequence[str],
) -> Dict[str, Any]:
    return {
        **_common_payload("blocked"),
        "schema_version": f"dse.complete_dse.{target}_tool_evidence_manifest.v1",
        "target": target,
        "producer_artifact_name": producer_artifact_name,
        "status": "blocked_missing_input",
        "deliverable_complete": False,
        "trusted_final_claim": False,
        "tool_evidence_rows": [
            {
                "stage_id": stage_id,
                "status": "blocked_missing_input",
                "claim_boundary": (
                    f"{target.upper()} evidence manifest is indexed for reporting "
                    "traceability only until producer artifacts are attached."
                ),
            }
            for stage_id in stage_ids
        ],
        "required_stage_ids": list(stage_ids),
        "blockers": [f"{producer_artifact_name}:missing_required_artifact"],
        "claim_boundary": (
            f"{target.upper()} tool evidence manifest is a fail-closed reporting "
            "surface, not claimable proof."
        ),
    }


def _deployment_recommendation_report_payload(
    fpga_report: Mapping[str, Any],
    asic_report: Mapping[str, Any],
    *,
    producer_artifact_refs: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    recommendations = {
        "fpga": dict(fpga_report),
        "asic": dict(asic_report),
    }
    producer_refs = {
        str(name): dict(ref)
        for name, ref in (producer_artifact_refs or {}).items()
        if isinstance(ref, Mapping)
    }
    return {
        **_common_payload("blocked"),
        "schema_version": "dse.complete_dse.deployment_recommendation_report.v1",
        "status": "blocked_missing_target_scoped_evidence",
        "recommendation_scope": "full_scf_evaluated_hybrid",
        "recommendations": recommendations,
        "best_recommendation_sections": {
            "fpga": recommendations["fpga"].get("best", {}),
            "asic": recommendations["asic"].get("best", {}),
        },
        "pareto_recommendation_sections": {
            "fpga": recommendations["fpga"].get("pareto", {}),
            "asic": recommendations["asic"].get("pareto", {}),
        },
        "producer_artifact_refs": producer_refs,
        "producer_artifact_ref_count": len(producer_refs),
        "deliverable_complete": False,
        "trusted_final_claim": False,
        "claim_boundary": (
            "Deployment recommendation reporting separates FPGA and ASIC "
            "recommendation surfaces without upgrading them to completion."
        ),
    }


def _build_claim_validation_report(
    validation: Mapping[str, Any],
    *,
    candidate_ids: Sequence[str],
    workload_case_ids: Sequence[str],
) -> Dict[str, Any]:
    deliverable_allowed = bool(validation.get("deliverable_complete_allowed"))
    errors = list(validation.get("errors", []) or [])
    status = "passed" if deliverable_allowed and not errors else "blocked"
    return {
        **_common_payload(status),
        "schema_version": "dse.complete_dse.claim_validation_report.v1",
        "candidate_ids": list(candidate_ids),
        "workload_case_ids": list(workload_case_ids),
        "valid": bool(validation.get("valid")),
        "deliverable_complete_allowed": deliverable_allowed,
        "validated_claims": {
            "deliverable_complete": {
                "allowed": deliverable_allowed,
                "reason": (
                    "all matrix, target recommendation, and requirement-evidence gates allow completion"
                    if deliverable_allowed
                    else "one or more matrix, target recommendation, or requirement-evidence gates remain blocked"
                ),
            },
            "fpga_recommendation": {
                "allowed": (
                    validation.get("recommendation_claim_validation", {})
                    .get("target_statuses", {})
                    .get("fpga", {})
                    .get("status")
                    == "claimable"
                ),
                "reason": "requires FPGA-specific HLS/RTL plus Vivado evidence rows",
            },
            "asic_recommendation": {
                "allowed": (
                    validation.get("recommendation_claim_validation", {})
                    .get("target_statuses", {})
                    .get("asic", {})
                    .get("status")
                    == "claimable"
                ),
                "reason": "requires ASIC-specific RTL plus Synopsys DC evidence rows",
            },
        },
        "coverage_claim_validation": dict(validation),
        "rejected_false_completion_claims": [
            "deliverable_complete",
            "fpga_best_or_pareto_without_target_gates",
            "asic_best_or_pareto_without_target_gates",
        ]
        if not deliverable_allowed
        else [],
        "claim_boundary": (
            "Claim validation reports whether completion claims are allowed. "
            "A blocked validation report is traceability evidence only and does not upgrade "
            "blocked, missing, projection-only, smoke-only, stale, forged, invalid, or "
            "tool-unavailable evidence."
        ),
    }


def _build_blocker_report(
    validation: Mapping[str, Any],
    requirement_audit: Mapping[str, Any],
    *,
    candidate_ids: Sequence[str],
    workload_case_ids: Sequence[str],
    source_producer_artifact_refs: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    producer_refs = {
        str(name): dict(ref)
        for name, ref in (source_producer_artifact_refs or {}).items()
        if isinstance(ref, Mapping)
    }
    full_scf_evaluated_hybrid_status = requirement_audit.get(
        "full_scf_evaluated_hybrid_status"
    )
    if not isinstance(full_scf_evaluated_hybrid_status, Mapping):
        full_scf_evaluated_hybrid_status = {}
    requirement_blocker_rows = [
        {
            "requirement_id": str(row.get("requirement_id")),
            "source": str(row.get("source")),
            "blockers": list(row.get("blockers", []) or []),
            "artifact_refs": dict(row.get("artifact_refs", {}) or {})
            if isinstance(row.get("artifact_refs", {}), Mapping)
            else {},
            "artifact_hashes": dict(row.get("artifact_hashes", {}) or {})
            if isinstance(row.get("artifact_hashes", {}), Mapping)
            else {},
            "next_action": "provide claimable source artifacts or keep requirement non-claimable",
            "completion_eligible": False,
            **(
                {
                    "full_scf_evaluated_hybrid_status": dict(
                        row["full_scf_evaluated_hybrid_status"]
                    )
                }
                if isinstance(row.get("full_scf_evaluated_hybrid_status"), Mapping)
                else {}
            ),
        }
        for row in (requirement_audit.get("requirement_rows", []) or [])
        if isinstance(row, Mapping) and row.get("blockers")
    ]
    matrix_validation = validation.get("matrix_validation", {})
    matrix_blocker_rows = list(
        matrix_validation.get("blockers", []) or []
    ) if isinstance(matrix_validation, Mapping) else []
    error_rows = list(validation.get("errors", []) or [])
    blocked_fields = sorted(
        {
            str(error.get("field"))
            for error in error_rows
            if isinstance(error, Mapping) and error.get("field")
        }
    )
    blocker_count = (
        len(requirement_blocker_rows) + len(matrix_blocker_rows) + len(error_rows)
    )
    blocker_matrix_rows = [
        {
            "category": "requirement",
            "requirement_id": row["requirement_id"],
            "candidate_id": None,
            "workload_case_id": None,
            "artifact_refs": dict(row.get("artifact_refs", {}) or {}),
            "blockers": list(row.get("blockers", []) or []),
            "next_action": row.get("next_action"),
            "deliverable_complete_impact": "blocks_deliverable_complete",
            "claim_boundary": (
                "Requirement blockers are not completion evidence and cannot satisfy deliverable_complete."
            ),
            **(
                {
                    "full_scf_evaluated_hybrid_status": dict(
                        row["full_scf_evaluated_hybrid_status"]
                    )
                }
                if isinstance(row.get("full_scf_evaluated_hybrid_status"), Mapping)
                else {}
            ),
        }
        for row in requirement_blocker_rows
    ]
    blocker_matrix_rows.extend(
        {
            "category": "matrix",
            "requirement_id": None,
            "candidate_id": str(row.get("candidate_id")),
            "workload_case_id": str(row.get("workload_case_id")),
            "artifact_refs": {},
            "blockers": list(row.get("reasons", []) or []),
            "next_action": "provide trusted L4 full-flow evidence for the frozen candidate/workload row",
            "deliverable_complete_impact": "blocks_deliverable_complete",
            "claim_boundary": (
                "Matrix blockers are not completion evidence and cannot satisfy deliverable_complete."
            ),
        }
        for row in matrix_blocker_rows
        if isinstance(row, Mapping)
    )
    blocker_matrix_rows.extend(
        {
            "category": "validation_error",
            "requirement_id": None,
            "candidate_id": None,
            "workload_case_id": None,
            "artifact_refs": {},
            "blockers": [str(error.get("message"))] if isinstance(error, Mapping) else [str(error)],
            "next_action": "repair the failing validation surface before claiming completion",
            "deliverable_complete_impact": "blocks_deliverable_complete",
            "claim_boundary": (
                "Validation errors are not completion evidence and cannot satisfy deliverable_complete."
            ),
        }
        for error in error_rows
    )
    deliverable_allowed = bool(validation.get("deliverable_complete_allowed"))
    status = "passed" if deliverable_allowed and blocker_count == 0 else "blocked"
    return {
        **_common_payload(status),
        "schema_version": "dse.complete_dse.blocker_report.v1",
        "candidate_ids": list(candidate_ids),
        "workload_case_ids": list(workload_case_ids),
        "deliverable_complete": deliverable_allowed,
        "blocker_count": blocker_count,
        "blocked_fields": blocked_fields,
        "requirement_blocker_rows": requirement_blocker_rows,
        "matrix_blocker_rows": matrix_blocker_rows,
        "validation_error_rows": error_rows,
        "source_producer_artifact_refs": producer_refs,
        "source_producer_artifact_ref_count": len(producer_refs),
        "full_scf_evaluated_hybrid_status": dict(full_scf_evaluated_hybrid_status),
        "source_producer_artifact_rationale": (
            "Preserves latest run1/run2 producer refs, including source blocker "
            "artifacts whose canonical names may be overwritten by generated "
            "report-package artifacts. These refs are traceability inputs only "
            "and cannot upgrade FPGA/ASIC or deliverable-complete claims."
        ),
        "blocker_matrix": {
            "schema_version": "dse.complete_dse.blocker_matrix.v1",
            "deliverable_complete": False,
            "row_count": len(blocker_matrix_rows),
            "rows": blocker_matrix_rows,
            "claim_boundary": (
                "Unified blocker matrix is fail-closed evidence only. "
                "Requirement, matrix, and validation-error rows explain why deliverable_complete remains false."
            ),
        },
        "next_action": (
            "close every listed blocker with fresh evidence before any final FPGA/ASIC recommendation"
            if blocker_count
            else "no blockers recorded by the report package"
        ),
        "claim_boundary": (
            "The blocker report explains why completion is false. Blocker rows, "
            "tool-unavailable rows, and partial package rows are not completion evidence."
        ),
    }


def _build_artifact_hash_manifest(
    artifact_refs: Mapping[str, Any],
    *,
    status: str,
) -> Dict[str, Any]:
    artifacts: Dict[str, Dict[str, Any]] = {}
    for name, ref in sorted(artifact_refs.items()):
        if not isinstance(ref, Mapping):
            continue
        digest = ref.get("sha256") or ref.get("hash")
        if not digest:
            continue
        artifacts[str(name)] = {
            "path": str(ref.get("path") or name),
            "sha256": str(digest),
            "hash_algorithm": str(ref.get("hash_algorithm") or "sha256"),
        }
    return {
        **_common_payload(status),
        "schema_version": "dse.complete_dse.artifact_hash_manifest.v1",
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "manifest_scope": (
            "Hashes generated report/package artifacts for traceability. The final "
            "reporting_artifact_manifest records the hash of this manifest itself."
        ),
        "claim_boundary": (
            "Hash presence proves artifact identity only. It does not make missing, "
            "blocked, projection-only, stale, forged, invalid, smoke-only, or "
            "tool-unavailable evidence claimable."
        ),
    }


def _seed_manifest_rows() -> list[Dict[str, Any]]:
    return [
        {
            "seed_template_id": "streaming_pipeline",
            "kind": "base_family",
            "status": "draft",
            "bounded_parameter_levels": {
                "pipeline_depth": ["small"],
                "dma_overlap": ["single_buffer"],
            },
            "source_workload_features": ["fft", "rho", "potential_update"],
        },
        {
            "seed_template_id": "simd_vector",
            "kind": "base_family",
            "status": "draft",
            "bounded_parameter_levels": {
                "lanes": [4],
                "vector_width_policy": ["portable"],
            },
            "source_workload_features": [
                "residual",
                "mix_rho",
                "vector_updates",
            ],
        },
        {
            "seed_template_id": "spatial_pe_array",
            "kind": "base_family",
            "status": "draft",
            "bounded_parameter_levels": {
                "array_shape": ["small_square"],
                "tile_policy": ["blocked"],
            },
            "source_workload_features": ["h_psi", "s_psi", "subspace_matrix"],
        },
        {
            "seed_template_id": "task_parallel_engines",
            "kind": "base_family",
            "status": "draft",
            "bounded_parameter_levels": {
                "engine_count": [2],
                "queue_policy": ["ordered_overlap"],
            },
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
            "bounded_parameter_levels": {
                "stream_to_array_policy": ["blocked_dma"]
            },
            "source_workload_features": ["h_psi", "s_psi", "subspace_matrix"],
        },
        {
            "seed_template_id": "task_parallel_simd",
            "kind": "hybrid_template",
            "status": "draft",
            "bounded_parameter_levels": {
                "assignment_policy": ["simd_friendly_to_vector_engine"]
            },
            "source_workload_features": ["mixed_full_flow", "vector_updates"],
        },
        {
            "seed_template_id": "task_parallel_spatial_array",
            "kind": "hybrid_template",
            "status": "draft",
            "bounded_parameter_levels": {
                "assignment_policy": ["dense_kernel_to_array_engine"]
            },
            "source_workload_features": ["mixed_full_flow", "dense_subspace"],
        },
        {
            "seed_template_id": "pipeline_task_overlap",
            "kind": "hybrid_template",
            "status": "draft",
            "bounded_parameter_levels": {
                "overlap_policy": ["pipeline_host_queue_dma"]
            },
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
    candidate_ids = _normalise_ids(
        expected_candidate_ids or matrix_report.get("candidate_ids", [])
    )
    workload_case_ids = _normalise_ids(
        expected_workload_case_ids
        or matrix_report.get("workload_case_ids", [])
    )
    rows = matrix_report.get("rows", [])
    if not isinstance(rows, list):
        rows = []

    errors: list[Dict[str, Any]] = []
    blockers: list[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    if not candidate_ids:
        errors.append(
            {
                "field": "candidate_ids",
                "message": "frozen candidate ids are required",
            }
        )
    if not workload_case_ids:
        errors.append(
            {
                "field": "workload_case_ids",
                "message": "frozen workload case ids are required",
            }
        )

    expected_pairs = {
        (candidate_id, workload_id)
        for candidate_id in candidate_ids
        for workload_id in workload_case_ids
    }
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(
                {"field": f"rows[{index}]", "message": "row must be an object"}
            )
            continue
        key = _row_key(row)
        if not all(key):
            errors.append(
                {
                    "field": f"rows[{index}]",
                    "message": "candidate_id and workload_case_id are required",
                }
            )
            continue
        if key in seen:
            errors.append(
                {
                    "field": f"rows[{index}]",
                    "message": "duplicate matrix row",
                    "row_key": key,
                }
            )
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
            row_reasons.append(
                f"disallowed_completion_basis:{completion_basis}"
            )
        if claim_label != TRUSTED_ROW_CLAIM:
            row_reasons.append(
                f"non_trusted_claim_label:{claim_label or 'missing'}"
            )
        if status != "passed":
            row_reasons.append(f"row_status_not_passed:{status or 'missing'}")
        if (
            tool_status in {"unavailable", "failed", "blocked", "missing"}
            and status == "passed"
        ):
            row_reasons.append(
                f"tool_status_cannot_support_passed_row:{tool_status}"
            )

        artifact_names = [
            str(name) for name in (row.get("artifact_names", []) or [])
            if str(name)
        ]
        artifact_refs = row.get("artifact_refs", {})
        if not isinstance(artifact_refs, Mapping):
            row_reasons.append("artifact_refs_missing_or_not_object")
            artifact_refs = {}
        artifact_hashes = row.get("artifact_hashes", {})
        if not isinstance(artifact_hashes, Mapping):
            row_reasons.append("artifact_hashes_missing_or_not_object")
            artifact_hashes = {}
        present_refs = row.get("present_claimable_artifact_refs", {})
        if not isinstance(present_refs, Mapping):
            row_reasons.append("present_claimable_artifact_refs_missing_or_not_object")
            present_refs = {}
        present_names = [
            str(name) for name in (row.get("present_claimable_artifact_names", []) or [])
            if str(name)
        ]
        missing_artifact_refs = [
            name for name in artifact_names if name not in artifact_refs
        ]
        if missing_artifact_refs:
            row_reasons.append(
                "missing_requirement_artifact_refs:" + ",".join(sorted(set(missing_artifact_refs)))
            )
        missing_present_refs = [
            name for name in present_names if name not in present_refs
        ]
        if missing_present_refs:
            row_reasons.append(
                "missing_present_claimable_artifact_refs:" + ",".join(sorted(set(missing_present_refs)))
            )
        hash_mismatches = [
            name
            for name, ref in artifact_refs.items()
            if isinstance(ref, Mapping)
            and ref.get("sha256")
            and artifact_hashes.get(name) != ref.get("sha256")
        ]
        if hash_mismatches:
            row_reasons.append(
                "artifact_hash_mismatch:" + ",".join(sorted(set(hash_mismatches)))
            )
        for name in present_names:
            ref = artifact_refs.get(name)
            if not isinstance(ref, Mapping):
                row_reasons.append(f"missing_present_artifact_ref:{name}")
                continue
            if not ref.get("path"):
                row_reasons.append(f"present_artifact_missing_path:{name}")
            if not ref.get("sha256"):
                row_reasons.append(f"present_artifact_missing_sha256:{name}")
        if row.get("claimable") is True and not present_names:
            row_reasons.append("claimable_row_missing_present_claimable_artifacts")

        missing_gates = [
            gate for gate in ROW_REQUIRED_GATES if gates.get(gate) is not True
        ]
        if missing_gates:
            row_reasons.append(
                "missing_required_gates:" + ",".join(missing_gates)
            )
        evidence_refs = row.get("evidence_refs", {})
        if not isinstance(evidence_refs, Mapping):
            evidence_refs = {}
        missing_evidence_refs = [
            gate
            for gate in ROW_REQUIRED_GATES
            if gates.get(gate) is True and not evidence_refs.get(gate)
        ]
        if missing_evidence_refs:
            row_reasons.append(
                "missing_required_evidence_refs:"
                + ",".join(missing_evidence_refs)
            )

        if row_reasons:
            blockers.append(
                {
                    "candidate_id": key[0],
                    "workload_case_id": key[1],
                    "reasons": row_reasons,
                }
            )

    missing_pairs = sorted(expected_pairs - seen)
    extra_pairs = sorted(seen - expected_pairs) if expected_pairs else []
    if missing_pairs:
        errors.append(
            {
                "field": "rows",
                "message": "missing frozen candidate/workload rows",
                "missing_rows": [
                    {
                        "candidate_id": candidate_id,
                        "workload_case_id": workload_id,
                    }
                    for candidate_id, workload_id in missing_pairs
                ],
            }
        )
    if extra_pairs:
        errors.append(
            {
                "field": "rows",
                "message": "matrix contains rows outside the frozen release cross-product",
                "extra_rows": [
                    {
                        "candidate_id": candidate_id,
                        "workload_case_id": workload_id,
                    }
                    for candidate_id, workload_id in extra_pairs
                ],
            }
        )
    if required_artifacts_present is False:
        errors.append(
            {
                "field": "required_artifacts",
                "message": "required report/checklist artifacts are missing",
            }
        )

    deliverable_allowed = bool(
        candidate_ids
        and workload_case_ids
        and rows
        and not errors
        and not blockers
    )
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


def _recommendation_is_claimable(recommendation: Mapping[str, Any]) -> bool:
    status = str(recommendation.get("status", "")).lower()
    recommendation_kind = str(
        recommendation.get("recommendation_kind")
        or recommendation.get("claim_type")
        or recommendation.get("kind")
        or ""
    ).lower()
    if any(
        recommendation.get(flag) is True
        for flag in (
            "claimable",
            "trusted_winner",
            "trusted_final_claim",
            "deliverable_complete",
            "can_name_winner",
            "can_name_hardware_ppa_winner",
            "can_name_targeted_deployment_recommendation",
        )
    ):
        return True
    if status in CLAIMABLE_RECOMMENDATION_STATUSES:
        return True
    return recommendation_kind in {"best", "best_architecture", "pareto", "pareto_frontier"} and not status.startswith("blocked")


def _target_from_candidate_identity(identity: Mapping[str, Any]) -> str:
    target_platform = _as_mapping(identity.get("target_platform"))
    return str(
        target_platform.get("deployment_target")
        or target_platform.get("target")
        or identity.get("deployment_target")
        or ""
    ).lower()


def _contains_forbidden_recommendation_marker(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.lower()
        return (
            normalized in FORBIDDEN_TARGET_RECOMMENDATION_ROW_STATUSES
            or normalized in DISALLOWED_COMPLETION_BASES
            or normalized in LOW_TRUST_EVIDENCE_TIERS
            or normalized in {"partial", "incomplete"}
            or normalized.startswith("blocked_")
            or "projection_only" in normalized
            or "tool_unavailable" in normalized
            or "unavailable" in normalized
            or "invalid" in normalized
            or "smoke_only" in normalized
            or "stale" in normalized
            or "forged" in normalized
            or "wrong_target" in normalized
        )
    if isinstance(value, Mapping):
        return any(_contains_forbidden_recommendation_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_recommendation_marker(item) for item in value)
    return False


def _target_scoped_recommendation_maps(
    report: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    """Return target recommendation maps from known reporting surfaces."""

    surfaces: list[Any] = [
        report.get("target_scoped_recommendations"),
        _as_mapping(report.get("deployment_recommendations")).get("recommendations"),
        _as_mapping(report.get("dft_deployment_decision_support")).get("recommendations"),
    ]
    deployments = _as_mapping(
        _as_mapping(report.get("dft_hardware_deployment_recommendation_readiness")).get("deployments")
    )
    if deployments:
        surfaces.append(deployments)

    recommendations: list[tuple[str, Mapping[str, Any]]] = []
    for surface in surfaces:
        if not isinstance(surface, Mapping):
            continue
        for target in TARGET_SCOPED_RECOMMENDATION_TARGETS:
            item = surface.get(target)
            if isinstance(item, Mapping):
                recommendations.append((target, item))
    return recommendations


def _target_scoped_rows_for_recommendation(
    report: Mapping[str, Any],
    recommendation: Mapping[str, Any],
    target: str,
) -> list[Dict[str, Any]]:
    row_keys = (
        "candidate_workflow_target_rows",
        "target_scoped_evidence_rows",
        "target_ppa_rows",
        "ppa_rows",
        "evidence_rows",
        "ledger_rows",
        "rows",
    )
    rows: list[Dict[str, Any]] = []
    for key in row_keys:
        rows.extend(_as_list_of_mappings(recommendation.get(key)))

    ranking_sources = [
        report.get("target_ppa_ranking"),
        report.get("dft_hardware_ppa_ranking"),
        _as_mapping(report.get("deployment_readiness")).get("target_ppa_ranking"),
    ]
    for source in ranking_sources:
        source_map = _as_mapping(source)
        rows.extend(_as_list_of_mappings(source_map.get(f"{target}_ranking")))
    return rows


def _target_evidence_markers(row: Mapping[str, Any]) -> Dict[str, bool]:
    """Return target-tool markers from explicit evidence-bearing row fields."""

    strings: list[str] = []
    for key in (
        "target_evidence_refs",
        "evidence_refs",
        "raw_evidence_refs",
        "tool_evidence",
        "stage_evidence",
        "source_artifacts",
        "evidence_gates",
    ):
        strings.extend(_collect_strings(row.get(key)))
    return {
        "has_hls": any("hls" in item for item in strings),
        "has_rtl": any("rtl" in item for item in strings),
        "has_vivado": any("vivado" in item for item in strings),
        "has_dc": any(
            "dc_asic" in item
            or "synopsys_dc" in item
            or "dc_timing" in item
            or "/dc" in item
            or item.endswith("dc")
            for item in strings
        ),
    }


def _validate_target_specific_tool_evidence(row: Mapping[str, Any], target: str) -> list[str]:
    markers = _target_evidence_markers(row)
    reasons: list[str] = []
    if target == "fpga":
        if not (markers["has_hls"] or markers["has_rtl"]):
            reasons.append("missing_fpga_hls_or_rtl_evidence")
        if not markers["has_vivado"]:
            reasons.append("missing_fpga_vivado_evidence")
        if markers["has_dc"] and not markers["has_vivado"]:
            reasons.append("dc_only_cannot_satisfy_fpga_claim")
    elif target == "asic":
        if not markers["has_rtl"]:
            reasons.append("missing_asic_rtl_evidence")
        if not markers["has_dc"]:
            reasons.append("missing_asic_dc_evidence")
        if markers["has_vivado"] and not markers["has_dc"]:
            reasons.append("vivado_only_cannot_satisfy_asic_claim")
    return reasons


def _validate_target_scoped_recommendation_row(
    row: Mapping[str, Any],
    *,
    target: str,
    candidate_id: str,
) -> list[str]:
    reasons: list[str] = []
    row_candidate_id = str(row.get("candidate_id") or "")
    if not row_candidate_id:
        reasons.append("missing_candidate_id")
    elif candidate_id and row_candidate_id != candidate_id:
        reasons.append(
            f"candidate_id_mismatch:{row_candidate_id}!={candidate_id}"
        )

    identity = _as_mapping(row.get("candidate_identity"))
    row_target_markers = [
        str(value).lower()
        for value in (
            row.get("target"),
            row.get("deployment_target"),
            row.get("ranking_target"),
            _target_from_candidate_identity(identity),
        )
        if str(value or "")
    ]
    deployment_marker = str(row.get("deployment") or "").lower()
    if deployment_marker in TARGET_SCOPED_RECOMMENDATION_TARGETS:
        row_target_markers.append(deployment_marker)
    if not row_target_markers:
        reasons.append("missing_target_binding")
    elif any(marker != target for marker in row_target_markers):
        reasons.append("wrong_target:" + ",".join(sorted(set(row_target_markers))))

    workflow_id = str(
        row.get("workflow_id")
        or row.get("workflow")
        or row.get("workflow_name")
        or row.get("candidate_workflow_id")
        or ""
    )
    if not workflow_id:
        reasons.append("missing_workflow_binding")

    deployment_boundary = (
        row.get("deployment_boundary")
        or row.get("deployment_boundary_id")
        or row.get("boundary_id")
        or identity.get("deployment_boundary")
    )
    if not deployment_boundary:
        reasons.append("missing_deployment_boundary_binding")

    if not identity and row.get("candidate_identity_bound") is not True and row.get("identity_bound") is not True:
        reasons.append("missing_candidate_identity_binding")

    status = str(row.get("status") or row.get("gate_status") or "").lower()
    claim_label = str(row.get("claim_label") or "").lower()
    completion_basis = str(row.get("completion_basis") or "").lower()
    evidence_tier = str(row.get("evidence_tier") or "").lower()
    tool_status = str(row.get("tool_status") or "").lower()
    if not status:
        reasons.append("missing_row_status")
    if (
        status in FORBIDDEN_TARGET_RECOMMENDATION_ROW_STATUSES
        or status.startswith("blocked")
        or "projection" in status
        or "invalid" in status
        or "smoke" in status
    ):
        reasons.append(f"forbidden_row_status:{status}")
    if claim_label in {"blocked", "projection_only", "research_projection", "vertical_slice_only", "mvp_partial"}:
        reasons.append(f"non_claimable_claim_label:{claim_label}")
    if completion_basis in DISALLOWED_COMPLETION_BASES:
        reasons.append(f"disallowed_completion_basis:{completion_basis}")
    if evidence_tier in LOW_TRUST_EVIDENCE_TIERS or "projection" in evidence_tier or "smoke" in evidence_tier:
        reasons.append(f"low_trust_evidence_tier:{evidence_tier}")
    if tool_status in {"unavailable", "failed", "blocked", "missing"}:
        reasons.append(f"tool_status_not_claimable:{tool_status}")
    if row.get("smoke_only") is True or row.get("smoke_test_only") is True:
        reasons.append("smoke_only")
    if row.get("stale") is True or row.get("stale_evidence") is True:
        reasons.append("stale_evidence")
    if row.get("forged") is True or row.get("forged_evidence") is True:
        reasons.append("forged_evidence")
    if (
        row.get("valid") is False
        or row.get("validation_valid") is False
        or row.get("evidence_valid") is False
    ):
        reasons.append("invalid_evidence")
    if row.get("ranking_eligible") is False:
        reasons.append("ranking_not_eligible")
    if row.get("candidate_gate_passed") is False:
        reasons.append("candidate_gate_not_passed")
    blockers = _as_list_of_mappings(row.get("target_specific_blockers")) + _as_list_of_mappings(row.get("blockers"))
    if blockers:
        reasons.append(f"row_has_blockers:{len(blockers)}")
    reasons.extend(_validate_target_specific_tool_evidence(row, target))
    if _contains_forbidden_recommendation_marker(row):
        reasons.append("forbidden_projection_blocked_smoke_stale_or_wrong_target_marker")
    return sorted(set(reasons))


def validate_target_scoped_recommendation_claims(
    report: Mapping[str, Any],
) -> Dict[str, Any]:
    """Fail closed on claimable FPGA/ASIC recommendations without target rows.

    This guard is intentionally independent per target: a blocked FPGA row does
    not erase an ASIC recommendation, and a passing ASIC row cannot upgrade a
    missing/projection-only FPGA recommendation.  It only evaluates
    recommendations that are emitted as claimable/best/Pareto-style outputs;
    absence of a recommendation remains a reportable non-completion state, not
    a structural validation failure.
    """

    target_statuses: Dict[str, Dict[str, Any]] = {
        target: {
            "target": target,
            "present": False,
            "claimable_requested": False,
            "status": "not_present",
            "row_count": 0,
            "blockers": [],
        }
        for target in TARGET_SCOPED_RECOMMENDATION_TARGETS
    }
    errors: list[Dict[str, Any]] = []

    for target, recommendation in _target_scoped_recommendation_maps(report):
        status = target_statuses[target]
        status["present"] = True
        claimable_requested = _recommendation_is_claimable(recommendation)
        status["claimable_requested"] = bool(status["claimable_requested"] or claimable_requested)
        if not claimable_requested:
            if status["status"] in {"not_present", "not_claimable"}:
                status["status"] = "not_claimable"
            continue

        candidate_id = str(recommendation.get("candidate_id") or "")
        rows = _target_scoped_rows_for_recommendation(report, recommendation, target)
        status["row_count"] = len(rows)
        if not rows:
            error = {
                "field": f"target_scoped_recommendations.{target}.evidence_rows",
                "target": target,
                "candidate_id": candidate_id,
                "message": "claimable target recommendation has missing target-scoped evidence rows",
            }
            errors.append(error)
            status["blockers"].append(error)
            status["status"] = "blocked"
            continue

        target_blockers: list[Dict[str, Any]] = []
        for index, row in enumerate(rows):
            reasons = _validate_target_scoped_recommendation_row(
                row,
                target=target,
                candidate_id=candidate_id,
            )
            if reasons:
                target_blockers.append(
                    {
                        "field": f"target_scoped_recommendations.{target}.evidence_rows[{index}]",
                        "target": target,
                        "candidate_id": candidate_id,
                        "row_candidate_id": row.get("candidate_id"),
                        "reasons": reasons,
                    }
                )
        if target_blockers:
            status["status"] = "blocked"
            status["blockers"] = target_blockers
            for blocker in target_blockers:
                errors.append(
                    {
                        "field": blocker["field"],
                        "target": target,
                        "candidate_id": candidate_id,
                        "message": "claimable target recommendation row is not claimable: "
                        + ",".join(blocker["reasons"]),
                    }
                )
        else:
            if status["status"] != "blocked":
                status["status"] = "claimable"

    return {
        "schema_version": "dse.complete_dse.target_scoped_recommendation_claim_validation.v1",
        "valid": not errors,
        "deliverable_complete_allowed": not errors,
        "target_statuses": target_statuses,
        "errors": errors,
        "claim_boundary": (
            "FPGA and ASIC best/Pareto recommendations are target-specific. "
            "Projection-only, blocked, missing, stale, forged, smoke-only, "
            "wrong-target, or unbound candidate×workflow×deployment-boundary×target "
            "rows cannot become claimable recommendations or deliverable_complete."
        ),
    }


def _artifact_ref_claimability(ref: Any) -> tuple[bool, list[str]]:
    if not isinstance(ref, Mapping):
        return False, ["missing_required_artifact"]
    blockers: list[str] = []
    path = str(ref.get("path") or "")
    if not path:
        blockers.append("missing_artifact_path")
    if not ref.get("sha256"):
        blockers.append("missing_source_sha256")
    if ref.get("exists") is False:
        blockers.append("artifact_marked_missing")
    status = str(ref.get("status") or ref.get("evidence_status") or "").lower()
    if status in {"partial", "incomplete"}:
        blockers.append("artifact_incomplete")
    if status and _contains_forbidden_recommendation_marker(status):
        blockers.append(f"artifact_status_not_claimable:{status}")
    if ref.get("smoke_only") is True:
        blockers.append("artifact_smoke_only")
    if ref.get("stale") is True:
        blockers.append("artifact_stale")
    if ref.get("forged") is True:
        blockers.append("artifact_forged")
    if ref.get("projection_only") is True:
        blockers.append("artifact_projection_only")
    if ref.get("complete") is False or ref.get("completion_complete") is False:
        blockers.append("artifact_incomplete")
    if ref.get("valid") is False or ref.get("validation_valid") is False:
        blockers.append("artifact_invalid")
    for blocker_id in ref.get("release_candidate_identity_provenance_blocker_ids", []) or []:
        blockers.append(
            f"release_candidate_identity_provenance:{str(blocker_id)}"
        )
    try:
        candidate_kernel_axis_unbound_count = int(
            ref.get("candidate_kernel_axis_unbound_row_count", 0) or 0
        )
    except (TypeError, ValueError):
        candidate_kernel_axis_unbound_count = 0
    if candidate_kernel_axis_unbound_count > 0:
        blockers.append("candidate_kernel_axis_unbound_rows")
    return not blockers, blockers


def _json_safe_artifact_ref_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe_artifact_ref_value(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_json_safe_artifact_ref_value(item) for item in value]
    if isinstance(value, list):
        return [_json_safe_artifact_ref_value(item) for item in value]
    return value


def _normalised_artifact_ref(
    artifact_name: str,
    artifact_ref: Any,
    *,
    claimable: bool,
    blockers: Sequence[str],
) -> Dict[str, Any]:
    if isinstance(artifact_ref, Mapping):
        normalised = {
            str(key): _json_safe_artifact_ref_value(value)
            for key, value in artifact_ref.items()
        }
    else:
        normalised = {"path": artifact_name, "exists": False}
    normalised.setdefault("path", artifact_name)
    normalised["claimable"] = bool(claimable)
    normalised["blockers"] = sorted({str(blocker) for blocker in blockers})
    if normalised.get("sha256"):
        normalised.setdefault("hash_algorithm", "sha256")
    return normalised


def _completion_statuses_from_requirement_rows(
    *,
    rows: Sequence[Mapping[str, Any]],
    claimable: bool,
    status: str,
) -> Dict[str, bool]:
    blockers = [
        str(blocker).lower()
        for row in rows
        for blocker in (row.get("blockers", []) or [])
    ]
    present_claimable_count = sum(
        len(row.get("present_claimable_artifact_names", []) or [])
        for row in rows
    )
    blocked = not claimable
    projection_only = any(
        "projection" in blocker or "l1" in blocker or "l2" in blocker or "l3" in blocker
        for blocker in blockers
    )
    vertical_slice_only = (
        str(status).lower() == "vertical_slice_only"
        or any("vertical_slice_only" in blocker for blocker in blockers)
    )
    mvp_partial = bool(
        not claimable
        and present_claimable_count
        and not vertical_slice_only
    )
    return {
        "vertical_slice_only": vertical_slice_only,
        "MVP_partial": mvp_partial,
        "blocked": blocked,
        "projection_only": projection_only,
        "deliverable_complete": claimable,
    }


def _requirement_artifact_status(
    artifact_refs: Mapping[str, Any],
    artifact_names: Sequence[str],
    policy: str,
) -> tuple[list[str], list[str], list[str], Dict[str, Dict[str, Any]]]:
    artifact_paths: list[str] = []
    present_claimable_names: list[str] = []
    blockers: list[str] = []
    requirement_artifact_refs: Dict[str, Dict[str, Any]] = {}
    for artifact_name in artifact_names:
        artifact_ref = artifact_refs.get(artifact_name)
        claimable, artifact_blockers = _artifact_ref_claimability(artifact_ref)
        requirement_artifact_refs[str(artifact_name)] = _normalised_artifact_ref(
            str(artifact_name),
            artifact_ref,
            claimable=claimable,
            blockers=artifact_blockers,
        )
        if isinstance(artifact_ref, Mapping) and artifact_ref.get("path"):
            artifact_paths.append(str(artifact_ref["path"]))
        else:
            artifact_paths.append(str(artifact_name))
        if claimable:
            present_claimable_names.append(str(artifact_name))
        else:
            blockers.extend(
                f"{artifact_name}:{blocker}" for blocker in artifact_blockers
            )
    if policy == "any" and present_claimable_names:
        blockers = [
            blocker
            for blocker in blockers
            if not blocker.endswith(":missing_required_artifact")
        ]
    return artifact_paths, present_claimable_names, blockers, requirement_artifact_refs


def _full_scf_evaluated_hybrid_status_from_artifact_refs(
    artifact_refs: Mapping[str, Any],
) -> Dict[str, Any]:
    attachment_artifact_refs: Dict[str, Dict[str, Any]] = {}
    attachment_hashes: Dict[str, str] = {}
    attachment_present_names: list[str] = []
    attachment_blocker_ids: list[str] = []
    for artifact_name in QE_BASELINE_ROW_ACCOUNTING_ATTACHMENT_ARTIFACTS:
        artifact_ref = artifact_refs.get(artifact_name)
        claimable, artifact_blockers = _artifact_ref_claimability(artifact_ref)
        normalised_ref = _normalised_artifact_ref(
            artifact_name,
            artifact_ref,
            claimable=claimable,
            blockers=artifact_blockers,
        )
        attachment_artifact_refs[artifact_name] = normalised_ref
        if claimable:
            attachment_present_names.append(artifact_name)
        if normalised_ref.get("sha256"):
            attachment_hashes[artifact_name] = str(normalised_ref["sha256"])
        attachment_blocker_ids.extend(
            f"{artifact_name}:{blocker}"
            for blocker in normalised_ref.get("blockers", []) or []
        )

    artifact_rows: Dict[str, Dict[str, Any]] = {}
    artifact_hashes: Dict[str, str] = {}
    missing_artifact_names: list[str] = []
    nonclaimable_artifact_names: list[str] = []
    blocker_ids: list[str] = []
    for artifact_name in FULL_SCF_ACCOUNTING_REPORTING_ARTIFACTS:
        artifact_ref = artifact_refs.get(artifact_name)
        claimable, artifact_blockers = _artifact_ref_claimability(artifact_ref)
        normalised_ref = _normalised_artifact_ref(
            artifact_name,
            artifact_ref,
            claimable=claimable,
            blockers=artifact_blockers,
        )
        artifact_rows[artifact_name] = normalised_ref
        if (
            not isinstance(artifact_ref, Mapping)
            or artifact_ref.get("exists") is False
        ):
            missing_artifact_names.append(artifact_name)
        if not claimable:
            nonclaimable_artifact_names.append(artifact_name)
        if normalised_ref.get("sha256"):
            artifact_hashes[artifact_name] = str(normalised_ref["sha256"])
        blocker_ids.extend(
            f"{artifact_name}:{blocker}"
            for blocker in normalised_ref.get("blockers", []) or []
        )

    required_count = len(FULL_SCF_ACCOUNTING_REPORTING_ARTIFACTS)
    artifact_set_hash_bound = len(artifact_hashes) == required_count
    accounting_artifacts_claimable = (
        artifact_set_hash_bound
        and not missing_artifact_names
        and not nonclaimable_artifact_names
    )
    blocked = not accounting_artifacts_claimable
    if missing_artifact_names:
        status = "blocked_missing_full_scf_evaluated_hybrid_artifacts"
    elif nonclaimable_artifact_names:
        status = "blocked_hash_bound_nonclaimable_full_scf_evaluated_hybrid"
    elif accounting_artifacts_claimable:
        status = "hash_bound_full_scf_evaluated_hybrid_artifacts_present"
    else:
        status = "blocked_full_scf_evaluated_hybrid_status_unknown"

    return {
        "schema_version": "dse.complete_dse.full_scf_evaluated_hybrid_status.v1",
        "deployment_boundary": "full_scf_evaluated_hybrid",
        "status": status,
        "qe_baseline_row_accounting_attachment": {
            "schema_version": "dse.complete_dse.qe_baseline_row_accounting_attachment.v1",
            "present": len(attachment_present_names) > 0,
            "status": (
                "attachment_present"
                if len(attachment_present_names)
                == len(QE_BASELINE_ROW_ACCOUNTING_ATTACHMENT_ARTIFACTS)
                else "partial_attachment_present"
                if attachment_present_names
                else "not_present"
            ),
            "required_artifact_names": list(
                QE_BASELINE_ROW_ACCOUNTING_ATTACHMENT_ARTIFACTS
            ),
            "artifact_refs": attachment_artifact_refs,
            "artifact_hashes": attachment_hashes,
            "hash_bound_artifact_count": len(attachment_hashes),
            "claim_upgrade_allowed": False,
            "hardware_completion_eligible": False,
            "trusted_final_claim": False,
            "deliverable_complete": False,
            "blocker_ids": sorted(dict.fromkeys(attachment_blocker_ids)),
            "claim_boundary": (
                "QE baseline comparison and full-SCF row accounting are visibility attachments only. "
                "They document row-level accounting context without upgrading completion, "
                "hardware-eligibility, or trusted-claim status."
            ),
        },
        "required_artifact_names": list(FULL_SCF_ACCOUNTING_REPORTING_ARTIFACTS),
        "required_artifact_count": required_count,
        "artifact_refs": artifact_rows,
        "artifact_hashes": artifact_hashes,
        "hash_bound_artifact_count": len(artifact_hashes),
        "artifact_set_hash_bound": artifact_set_hash_bound,
        "missing_artifact_names": missing_artifact_names,
        "nonclaimable_artifact_names": nonclaimable_artifact_names,
        "blocker_ids": sorted(dict.fromkeys(blocker_ids)),
        "accounting_artifacts_claimable": accounting_artifacts_claimable,
        "complete": accounting_artifacts_claimable,
        "partial": blocked,
        "projection_only": blocked,
        "blocked": blocked,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Hash-bound full-SCF evaluated-hybrid accounting artifacts are "
            "traceability inputs only here. They do not upgrade blocked, "
            "projection-only, incomplete, or target-missing FPGA/ASIC claims to "
            "deliverable_complete."
        ),
    }


def _producer_artifact_refs(
    source_artifact_refs: Mapping[str, Any] | None,
) -> Dict[str, Dict[str, Any]]:
    if not source_artifact_refs:
        return {}
    producer_refs: Dict[str, Dict[str, Any]] = {}
    for artifact_name, artifact_ref in source_artifact_refs.items():
        if artifact_name not in REQUIRED_COMPLETE_DSE_REPORT_ARTIFACTS:
            continue
        claimable, artifact_blockers = _artifact_ref_claimability(artifact_ref)
        producer_refs[str(artifact_name)] = _normalised_artifact_ref(
            str(artifact_name),
            artifact_ref,
            claimable=claimable,
            blockers=artifact_blockers,
        )
    return producer_refs


def _source_lane_summary(
    source_producer_artifact_refs: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    def _append_unique(row: Dict[str, Any], field: str, value: Any) -> None:
        text = str(value or "")
        if not text:
            return
        values = row.setdefault(field, [])
        if text not in values:
            values.append(text)

    def _merge_counter_map(row: Dict[str, Any], field: str, value: Any) -> None:
        if not isinstance(value, Mapping):
            return
        counts = row.setdefault(field, {})
        for key, count in value.items():
            key_text = str(key)
            counts[key_text] = int(counts.get(key_text, 0) or 0) + int(count or 0)

    lane_summary: Dict[str, Dict[str, Any]] = {}
    for artifact_name, artifact_ref in source_producer_artifact_refs.items():
        if not isinstance(artifact_ref, Mapping):
            continue
        source_lane = str(artifact_ref.get("source_lane") or "unknown")
        row = lane_summary.setdefault(
            source_lane,
            {
                "artifact_count": 0,
                "artifact_names": [],
                "statuses": [],
                "claimable_count": 0,
                "deliverable_complete_count": 0,
                "claim_upgrade_allowed_count": 0,
            },
        )
        row["artifact_count"] += 1
        row["artifact_names"].append(str(artifact_name))
        status = str(artifact_ref.get("status") or "")
        if status and status not in row["statuses"]:
            row["statuses"].append(status)
        if bool(artifact_ref.get("claimable", False)):
            row["claimable_count"] += 1
        if bool(artifact_ref.get("deliverable_complete", False)):
            row["deliverable_complete_count"] += 1
        if "claim_upgrade_allowed_count" in artifact_ref:
            row["claim_upgrade_allowed_count"] += int(
                artifact_ref.get("claim_upgrade_allowed_count", 0) or 0
            )
        release_status = artifact_ref.get(
            "release_candidate_identity_provenance_status"
        )
        if release_status is not None:
            statuses = row.setdefault(
                "release_candidate_identity_provenance_statuses", []
            )
            release_status_text = str(release_status)
            if release_status_text and release_status_text not in statuses:
                statuses.append(release_status_text)
        stable_blocker_counts = artifact_ref.get("stable_blocker_reason_counts")
        if isinstance(stable_blocker_counts, Mapping):
            row_counts = row.setdefault("stable_blocker_reason_counts", {})
            for reason, count in stable_blocker_counts.items():
                reason_key = str(reason)
                row_counts[reason_key] = int(row_counts.get(reason_key, 0) or 0) + int(
                    count or 0
                )
        runtime_provenance = artifact_ref.get("runtime_scheduling_provenance")
        if isinstance(runtime_provenance, Mapping):
            _append_unique(
                row,
                "runtime_schedule_ids",
                runtime_provenance.get("runtime_schedule_id"),
            )
            _append_unique(
                row,
                "co_scheduling_policy_ids",
                runtime_provenance.get("co_scheduling_policy_id"),
            )
            _append_unique(row, "queue_policies", runtime_provenance.get("queue_policy"))
        artifact_provenance = artifact_ref.get("artifact_provenance")
        if isinstance(artifact_provenance, Mapping):
            row["artifact_provenance_ref_count"] = int(
                row.get("artifact_provenance_ref_count", 0) or 0
            ) + 1
            _append_unique(
                row,
                "artifact_provenance_release_subset_hashes",
                artifact_provenance.get("release_subset_hash"),
            )
            _append_unique(
                row,
                "artifact_provenance_candidate_workflow_deployment_target_matrix_hashes",
                artifact_provenance.get(
                    "candidate_workflow_deployment_target_matrix_hash"
                )
                or artifact_provenance.get("matrix_hash"),
            )
        for count_field in (
            "replayable_tool_transcript_ref_count",
            "availability_probe_only_row_count",
            "candidate_kernel_axis_unbound_row_count",
            "candidate_kernel_axis_bound_row_count",
            "candidate_kernel_target_axis_count",
            "unknown_target_platform_kind_row_count",
            "parsed_stage_result_ref_count",
            "blocker_count",
        ):
            if count_field in artifact_ref:
                if count_field == "blocker_count" and artifact_name == "blocker_report.json":
                    continue
                row[count_field] = int(row.get(count_field, 0) or 0) + int(
                    artifact_ref.get(count_field, 0) or 0
                )
        for map_field in (
            "candidate_kernel_target_axis_counts_by_target",
            "row_counts_by_candidate_kernel_target_axis",
            "row_counts_by_target_platform_kind",
            "blocker_id_counts",
        ):
            _merge_counter_map(row, map_field, artifact_ref.get(map_field))
    for row in lane_summary.values():
        row["artifact_names"] = sorted(row["artifact_names"])
        row["statuses"] = sorted(row["statuses"])
        for list_field in (
            "runtime_schedule_ids",
            "co_scheduling_policy_ids",
            "queue_policies",
            "artifact_provenance_release_subset_hashes",
            "artifact_provenance_candidate_workflow_deployment_target_matrix_hashes",
        ):
            if list_field in row:
                row[list_field] = sorted(row[list_field])
        if "release_candidate_identity_provenance_statuses" in row:
            row["release_candidate_identity_provenance_statuses"] = sorted(
                row["release_candidate_identity_provenance_statuses"]
            )
        if "stable_blocker_reason_counts" in row:
            row["stable_blocker_reason_counts"] = dict(
                sorted(row["stable_blocker_reason_counts"].items())
            )
        for map_field in (
            "candidate_kernel_target_axis_counts_by_target",
            "row_counts_by_candidate_kernel_target_axis",
            "row_counts_by_target_platform_kind",
            "blocker_id_counts",
        ):
            if map_field in row:
                row[map_field] = dict(sorted(row[map_field].items()))
    return lane_summary


def build_requirement_evidence_audit_matrix(
    *,
    artifact_refs: Mapping[str, Any],
    recommendation_report: Mapping[str, Any] | None = None,
    source_producer_artifact_refs: Mapping[str, Any] | None = None,
    status: str = "draft",
) -> Dict[str, Any]:
    """Build a replayable docs/goal.md requirement-to-evidence audit matrix."""

    recommendation_validation = validate_target_scoped_recommendation_claims(
        recommendation_report or {}
    )
    producer_refs = {
        str(name): dict(ref)
        for name, ref in (source_producer_artifact_refs or {}).items()
        if isinstance(ref, Mapping)
    }
    target_statuses = recommendation_validation.get("target_statuses", {})
    full_scf_evaluated_hybrid_status = (
        _full_scf_evaluated_hybrid_status_from_artifact_refs(artifact_refs)
    )
    rows: list[Dict[str, Any]] = []
    for spec in GOAL_REQUIREMENT_EVIDENCE_SPECS:
        primary_artifact_names = tuple(str(name) for name in spec["artifact_names"])
        required_artifact_names = tuple(
            str(name) for name in spec.get("required_artifact_names", ())
        )
        artifact_names = tuple(
            dict.fromkeys([*primary_artifact_names, *required_artifact_names])
        )
        artifact_paths, present_names, blockers, row_artifact_refs = _requirement_artifact_status(
            artifact_refs,
            primary_artifact_names,
            str(spec.get("artifact_policy") or "all"),
        )
        if required_artifact_names:
            (
                required_paths,
                required_present_names,
                required_blockers,
                required_refs,
            ) = _requirement_artifact_status(
                artifact_refs,
                required_artifact_names,
                "all",
            )
            for artifact_path in required_paths:
                if artifact_path not in artifact_paths:
                    artifact_paths.append(artifact_path)
            for name in required_present_names:
                if name not in present_names:
                    present_names.append(name)
            blockers.extend(required_blockers)
            row_artifact_refs.update(required_refs)
        present_claimable_refs = {
            name: row_artifact_refs[name]
            for name in present_names
            if name in row_artifact_refs
        }
        required_target_claims = tuple(
            str(target) for target in spec.get("required_target_claims", ())
        )
        for target in required_target_claims:
            target_status = (
                target_statuses.get(target, {}).get("status")
                if isinstance(target_statuses, Mapping)
                else None
            )
            if target_status != "claimable":
                blockers.append(f"target_claim_not_claimable:{target}:{target_status or 'not_present'}")
        claimable = not blockers
        row = {
            "requirement_id": spec["requirement_id"],
            "source": spec["source"],
            "requirement": spec["requirement"],
            "semantic_hard_gate": True,
            "artifact_policy": spec.get("artifact_policy", "all"),
            "artifact_names": list(artifact_names),
            "primary_artifact_names": list(primary_artifact_names),
            "required_artifact_names": list(required_artifact_names),
            "artifact_paths": artifact_paths,
            "artifact_refs": row_artifact_refs,
            "artifact_hashes": {
                name: str(ref["sha256"])
                for name, ref in row_artifact_refs.items()
                if ref.get("sha256")
            },
            "present_claimable_artifact_names": present_names,
            "present_claimable_artifact_refs": present_claimable_refs,
            "required_target_claims": list(required_target_claims),
            "evidence_status": "trusted_pass" if claimable else "blocked_missing_input",
            "claimable": claimable,
            "blockers": sorted(set(blockers)),
        }
        if spec["requirement_id"] in FULL_SCF_EVALUATED_HYBRID_STATUS_REQUIREMENT_IDS:
            row["full_scf_evaluated_hybrid_status"] = full_scf_evaluated_hybrid_status
        rows.append(row)

    blocked_rows = [row for row in rows if not row["claimable"]]
    claimable = not blocked_rows and recommendation_validation.get("valid") is True
    completion_statuses = _completion_statuses_from_requirement_rows(
        rows=rows,
        claimable=claimable,
        status=status,
    )
    return {
        **_common_payload("claimable" if claimable else "blocked"),
        "schema_version": "dse.complete_dse.requirement_evidence_audit_matrix.v1",
        "source_goal": "docs/goal.md",
        "requirement_rows": rows,
        "requirement_count": len(rows),
        "blocked_requirement_count": len(blocked_rows),
        "claimability": "claimable" if claimable else "blocked",
        "deliverable_complete_allowed": claimable,
        "trusted_final_claim": claimable,
        "completion_statuses": completion_statuses,
        "full_scf_evaluated_hybrid_status": full_scf_evaluated_hybrid_status,
        "recommendation_claim_validation": recommendation_validation,
        "source_producer_artifact_refs": producer_refs,
        "source_producer_artifact_ref_count": len(producer_refs),
        "source_producer_artifact_rationale": (
            "Preserves latest integrated producer refs before generated reporting "
            "artifacts reuse the same canonical filenames. Run1 release-package "
            "refs and run2 availability/blocker refs remain fail-closed "
            "traceability evidence only."
        ),
        "blockers": [
            {
                "requirement_id": row["requirement_id"],
                "blockers": row["blockers"],
            }
            for row in blocked_rows
        ],
        "claim_boundary": (
            "This matrix maps docs/goal.md Done when requirements to concrete artifacts. "
            "Missing, projected, smoke-only, tool-unavailable, blocked, stale, forged, "
            "invalid, or wrong-target evidence remains non-claimable. FPGA claims require "
            "FPGA/HLS/RTL/Vivado evidence; ASIC claims require ASIC/RTL/DC evidence."
        ),
    }


def render_requirement_evidence_audit_markdown(audit: Mapping[str, Any]) -> str:
    lines = [
        "# Complete DSE Requirement-Evidence Audit Matrix",
        "",
        f"- Status: `{audit.get('status')}`",
        f"- Claimability: `{audit.get('claimability')}`",
        f"- Deliverable complete allowed: `{audit.get('deliverable_complete_allowed')}`",
        f"- Trusted final claim: `{audit.get('trusted_final_claim')}`",
        f"- Status taxonomy: `{', '.join(str(item) for item in (audit.get('status_taxonomy', []) or []))}`",
        f"- Completion statuses: `{audit.get('completion_statuses')}`",
        "",
        "| Requirement | Evidence status | Claimable | Artifact refs | Blockers |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in audit.get("requirement_rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        blockers = ", ".join(str(blocker) for blocker in row.get("blockers", []) or [])
        artifact_refs = row.get("present_claimable_artifact_refs", {})
        artifact_summary = ""
        if isinstance(artifact_refs, Mapping):
            artifact_summary = ", ".join(
                f"{name}={ref.get('path')}#{str(ref.get('sha256', ''))[:12]}"
                for name, ref in artifact_refs.items()
                if isinstance(ref, Mapping)
            )
        lines.append(
            f"| `{row.get('requirement_id')}` | `{row.get('evidence_status')}` | "
            f"`{row.get('claimable')}` | `{artifact_summary}` | `{blockers}` |"
        )
    lines.extend(["", "## Claim boundary", "", str(audit.get("claim_boundary", "")), ""])
    return "\n".join(lines)


def _validate_requirement_evidence_audit_matrix(
    audit: Any,
) -> Dict[str, Any]:
    errors: list[Dict[str, Any]] = []
    if not isinstance(audit, Mapping):
        return {
            "valid": False,
            "deliverable_complete_allowed": False,
            "errors": [
                {
                    "field": "requirement_evidence_matrix",
                    "message": "requirement-evidence audit matrix is missing or not an object",
                }
            ],
        }

    rows = audit.get("requirement_rows", [])
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        rows = []
        errors.append(
            {
                "field": "requirement_evidence_matrix.requirement_rows",
                "message": "requirement-evidence audit matrix rows must be explicit",
            }
        )
    row_mappings = [row for row in rows if isinstance(row, Mapping)]
    status_taxonomy = {str(item) for item in audit.get("status_taxonomy", []) or []}
    missing_statuses = sorted(set(GOAL_COMPLETION_STATUS_TAXONOMY) - status_taxonomy)
    completion_statuses = audit.get("completion_statuses", {})
    completion_statuses = completion_statuses if isinstance(completion_statuses, Mapping) else {}

    if audit.get("schema_version") != "dse.complete_dse.requirement_evidence_audit_matrix.v1":
        errors.append(
            {
                "field": "requirement_evidence_matrix.schema_version",
                "message": "requirement-evidence audit matrix schema is missing or unsupported",
            }
        )
    if audit.get("source_goal") != "docs/goal.md":
        errors.append(
            {
                "field": "requirement_evidence_matrix.source_goal",
                "message": "requirement-evidence audit matrix must identify docs/goal.md as source",
            }
        )
    if missing_statuses:
        errors.append(
            {
                "field": "requirement_evidence_matrix.status_taxonomy",
                "message": "requirement-evidence audit matrix is missing required status taxonomy entries: "
                + ",".join(missing_statuses),
            }
        )
    expected_count = len(GOAL_REQUIREMENT_EVIDENCE_SPECS)
    if len(row_mappings) != expected_count:
        errors.append(
            {
                "field": "requirement_evidence_matrix.requirement_rows",
                "message": f"requirement-evidence audit matrix must contain {expected_count} explicit rows",
            }
        )
    if audit.get("requirement_count") != len(row_mappings):
        errors.append(
            {
                "field": "requirement_evidence_matrix.requirement_count",
                "message": "requirement-evidence audit matrix requirement_count must match explicit row count",
            }
        )
    for index, row in enumerate(row_mappings):
        artifact_names = [
            str(name) for name in (row.get("artifact_names", []) or []) if str(name)
        ]
        artifact_refs = row.get("artifact_refs", {})
        artifact_hashes = row.get("artifact_hashes", {})
        present_refs = row.get("present_claimable_artifact_refs", {})
        present_names = [
            str(name)
            for name in (row.get("present_claimable_artifact_names", []) or [])
            if str(name)
        ]
        if not isinstance(artifact_refs, Mapping):
            errors.append(
                {
                    "field": f"requirement_evidence_matrix.requirement_rows[{index}].artifact_refs",
                    "message": "requirement-evidence audit matrix rows must include artifact refs",
                }
            )
            artifact_refs = {}
        if not isinstance(artifact_hashes, Mapping):
            errors.append(
                {
                    "field": f"requirement_evidence_matrix.requirement_rows[{index}].artifact_hashes",
                    "message": "requirement-evidence audit matrix rows must include artifact hashes",
                }
            )
            artifact_hashes = {}
        if not isinstance(present_refs, Mapping):
            errors.append(
                {
                    "field": f"requirement_evidence_matrix.requirement_rows[{index}].present_claimable_artifact_refs",
                    "message": "requirement-evidence audit matrix rows must include present claimable artifact refs",
                }
            )
            present_refs = {}
        if artifact_names and any(name not in artifact_refs for name in artifact_names):
            errors.append(
                {
                    "field": f"requirement_evidence_matrix.requirement_rows[{index}].artifact_refs",
                    "message": "requirement-evidence audit matrix rows must bind every artifact name to a concrete ref",
                }
            )
        if present_names and any(name not in present_refs for name in present_names):
            errors.append(
                {
                    "field": f"requirement_evidence_matrix.requirement_rows[{index}].present_claimable_artifact_refs",
                    "message": "requirement-evidence audit matrix rows must bind every present claimable artifact to a concrete ref",
                }
            )
        for name, ref in artifact_refs.items():
            if not isinstance(ref, Mapping):
                errors.append(
                    {
                        "field": f"requirement_evidence_matrix.requirement_rows[{index}].artifact_refs.{name}",
                        "message": "artifact refs must be objects",
                    }
                )
                continue
            if ref.get("sha256") and artifact_hashes.get(name) != ref.get("sha256"):
                errors.append(
                    {
                        "field": f"requirement_evidence_matrix.requirement_rows[{index}].artifact_hashes.{name}",
                        "message": "artifact hash entries must mirror the bound artifact ref sha256 values",
                    }
                )
        if row.get("claimable") is True:
            if not present_names:
                errors.append(
                    {
                        "field": f"requirement_evidence_matrix.requirement_rows[{index}].present_claimable_artifact_names",
                        "message": "claimable requirement rows must name at least one present claimable artifact",
                    }
                )
            for name in present_names:
                ref = artifact_refs.get(name)
                if not isinstance(ref, Mapping):
                    errors.append(
                        {
                            "field": f"requirement_evidence_matrix.requirement_rows[{index}].present_claimable_artifact_refs.{name}",
                            "message": "present claimable artifact refs must mirror bound artifact refs",
                        }
                    )
                    continue
                if not ref.get("path"):
                    errors.append(
                        {
                            "field": f"requirement_evidence_matrix.requirement_rows[{index}].present_claimable_artifact_refs.{name}",
                            "message": "present claimable artifact refs must include a path",
                        }
                    )
                if not ref.get("sha256"):
                    errors.append(
                        {
                            "field": f"requirement_evidence_matrix.requirement_rows[{index}].present_claimable_artifact_refs.{name}",
                            "message": "present claimable artifact refs must include a sha256 hash",
                        }
                    )
    blocked_rows = [
        row
        for row in row_mappings
        if row.get("claimable") is not True or row.get("blockers")
    ]
    if audit.get("blocked_requirement_count") != len(blocked_rows):
        errors.append(
            {
                "field": "requirement_evidence_matrix.blocked_requirement_count",
                "message": "requirement-evidence audit matrix blocked count must match blocked rows",
            }
        )
    deliverable_requested = audit.get("deliverable_complete_allowed") is True
    trusted_requested = audit.get("trusted_final_claim") is True
    if deliverable_requested != trusted_requested:
        errors.append(
            {
                "field": "requirement_evidence_matrix.trusted_final_claim",
                "message": "requirement-evidence audit matrix trusted final claim must match deliverable completion allowance",
            }
        )
    if completion_statuses.get("deliverable_complete") is not deliverable_requested:
        errors.append(
            {
                "field": "requirement_evidence_matrix.completion_statuses.deliverable_complete",
                "message": "requirement-evidence audit matrix deliverable status must match deliverable completion allowance",
            }
        )
    if deliverable_requested:
        if audit.get("claimability") != "claimable":
            errors.append(
                {
                    "field": "requirement_evidence_matrix.claimability",
                    "message": "requirement-evidence audit matrix allows completion without claimable status",
                }
            )
        if blocked_rows:
            errors.append(
                {
                    "field": "requirement_evidence_matrix.requirement_rows",
                    "message": "requirement-evidence audit matrix allows completion with blocked rows",
                }
            )
        for status in ("vertical_slice_only", "MVP_partial", "blocked", "projection_only"):
            if completion_statuses.get(status) is True:
                errors.append(
                    {
                        "field": f"requirement_evidence_matrix.completion_statuses.{status}",
                        "message": f"requirement-evidence audit matrix allows completion while reporting {status}",
                    }
                )

    valid_fail_closed = not errors
    deliverable_complete_allowed = bool(
        valid_fail_closed
        and deliverable_requested
        and audit.get("claimability") == "claimable"
        and not blocked_rows
    )
    return {
        "valid": valid_fail_closed,
        "deliverable_complete_allowed": deliverable_complete_allowed,
        "errors": errors,
    }


def validate_complete_dse_claim_report(
    report: Mapping[str, Any],
) -> Dict[str, Any]:
    """Validate a final coverage claim report and reject false completion."""
    matrix_report = report.get("l4_evidence_matrix", {})
    if not isinstance(matrix_report, Mapping):
        matrix_report = {}
    artifact_refs = report.get("required_artifacts", {})
    required_present = isinstance(artifact_refs, Mapping) and all(
        name in artifact_refs
        for name in REQUIRED_COMPLETE_DSE_REPORT_ARTIFACTS
    )
    validation = validate_l4_evidence_matrix_claims(
        matrix_report,
        expected_candidate_ids=report.get("candidate_ids", []),
        expected_workload_case_ids=report.get("workload_case_ids", []),
        required_artifacts_present=required_present,
    )
    recommendation_validation = validate_target_scoped_recommendation_claims(
        report
    )
    requirement_audit = report.get("requirement_evidence_matrix", {})
    requirement_validation = _validate_requirement_evidence_audit_matrix(
        requirement_audit
    )
    requirement_audit_attached = isinstance(requirement_audit, Mapping)
    requirement_audit_allows_completion = bool(
        requirement_validation["deliverable_complete_allowed"]
    )
    claimed_complete = (
        report.get("deliverable_complete") is True
        or report.get("status") == "deliverable_complete"
    )
    errors = list(validation["errors"])
    errors.extend(recommendation_validation["errors"])
    errors.extend(requirement_validation["errors"])
    deliverable_complete_allowed = bool(
        validation["deliverable_complete_allowed"]
        and recommendation_validation["deliverable_complete_allowed"]
        and requirement_audit_allows_completion
    )
    if claimed_complete and not requirement_audit_attached:
        errors.append(
            {
                "field": "requirement_evidence_matrix",
                "message": "report claims deliverable_complete without an attached requirement-evidence audit matrix",
            }
        )
    if claimed_complete and not deliverable_complete_allowed:
        errors.append(
            {
                "field": "deliverable_complete",
                "message": "report claims deliverable_complete but the L4 matrix, target-scoped recommendation, and requirement-evidence claim gates did not allow it",
            }
        )
    return {
        "schema_version": "dse.complete_dse.coverage_claim_validation.v1",
        "valid": not errors,
        "deliverable_complete_allowed": deliverable_complete_allowed,
        "claimed_deliverable_complete": claimed_complete,
        "errors": errors,
        "blockers": validation["blockers"],
        "matrix_validation": validation,
        "recommendation_claim_validation": recommendation_validation,
        "requirement_evidence_matrix_validation": requirement_validation,
        "requirement_evidence_audit_attached": requirement_audit_attached,
        "requirement_evidence_audit_claimability": (
            requirement_audit.get("claimability") if requirement_audit_attached else "not_attached"
        ),
        "claim_boundary": (
            "A coverage report may be structurally valid while still blocked. "
            "Claimed deliverable_complete is valid only when the matrix gate and "
            "target-scoped recommendation plus requirement-evidence gates allow it."
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
    report_status = (
        "deliverable_complete"
        if deliverable_allowed
        else ("blocked" if l4_rows else status)
    )
    report = {
        **_common_payload(report_status),
        "schema_version": "dse.complete_dse.coverage_claim_report.v1",
        "candidate_ids": candidate_id_list,
        "workload_case_ids": workload_id_list,
        "l4_evidence_matrix": matrix_report,
        "matrix_validation": matrix_validation,
        "required_artifacts": dict(required_artifacts or {}),
        "claim_summary": {
            "vertical_slice_only": any(
                row.get("claim_label") == "vertical_slice_only"
                for row in l4_rows
            ),
            "mvp_partial": bool(l4_rows and not deliverable_allowed),
            "projection_rows": [
                {
                    "candidate_id": _row_key(row)[0],
                    "workload_case_id": _row_key(row)[1],
                }
                for row in l4_rows
                if str(row.get("evidence_tier", "")).lower()
                in LOW_TRUST_EVIDENCE_TIERS
            ],
            "trusted_l4_rows": sum(
                1
                for row in l4_rows
                if row.get("claim_label") == TRUSTED_ROW_CLAIM
            ),
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
    return "\n".join(
        [
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
        ]
    )


def _build_prompt_to_artifact_checklist(
    required_artifacts: Mapping[str, Any], status: str
) -> Dict[str, Any]:
    full_scf_evaluated_hybrid_status = (
        _full_scf_evaluated_hybrid_status_from_artifact_refs(required_artifacts)
    )
    checklist = [
        {
            "requirement": "artifact::" + artifact_name,
            "artifact": required_artifacts.get(
                artifact_name, {"path": artifact_name}
            ),
            "status": (
                "present_hash_valid"
                if artifact_name in required_artifacts
                else "missing"
            ),
            "artifact_sha256": (
                str(required_artifacts[artifact_name].get("sha256"))
                if artifact_name in required_artifacts
                and isinstance(required_artifacts.get(artifact_name), Mapping)
                and required_artifacts[artifact_name].get("sha256")
                else None
            ),
            "completion_claim": "required_before_deliverable_complete",
        }
        for artifact_name in REQUIRED_COMPLETE_DSE_REPORT_ARTIFACTS
        if artifact_name
        not in {
            "prompt_to_artifact_checklist.json",
            "prompt_to_artifact_checklist.md",
        }
    ]
    checklist.extend(
        [
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
            {
                "requirement": "target_scoped_ppa_recommendation_claim_guard",
                "status": "covered_fail_closed",
                "targets": list(TARGET_SCOPED_RECOMMENDATION_TARGETS),
                "forbidden_row_statuses": sorted(
                    FORBIDDEN_TARGET_RECOMMENDATION_ROW_STATUSES
                ),
                "completion_claim": "fpga_asic_best_or_pareto_recommendations_require_candidate_workflow_deployment_boundary_target_rows",
            },
        ]
    )
    for spec in GOAL_REQUIREMENT_EVIDENCE_SPECS:
        primary_artifact_names = tuple(str(name) for name in spec["artifact_names"])
        required_artifact_names = tuple(
            str(name) for name in spec.get("required_artifact_names", ())
        )
        artifact_names = tuple(
            dict.fromkeys([*primary_artifact_names, *required_artifact_names])
        )
        artifact_paths, present_names, blockers, row_artifact_refs = _requirement_artifact_status(
            required_artifacts,
            primary_artifact_names,
            str(spec.get("artifact_policy") or "all"),
        )
        if required_artifact_names:
            (
                required_paths,
                required_present_names,
                required_blockers,
                required_refs,
            ) = _requirement_artifact_status(
                required_artifacts,
                required_artifact_names,
                "all",
            )
            for artifact_path in required_paths:
                if artifact_path not in artifact_paths:
                    artifact_paths.append(artifact_path)
            for name in required_present_names:
                if name not in present_names:
                    present_names.append(name)
            blockers.extend(required_blockers)
            row_artifact_refs.update(required_refs)
        checklist_row = {
            "requirement": str(spec["requirement_id"]),
            "source": str(spec["source"]),
            "artifact_policy": str(spec.get("artifact_policy") or "all"),
            "artifact_names": list(artifact_names),
            "primary_artifact_names": list(primary_artifact_names),
            "required_artifact_names": list(required_artifact_names),
            "artifact_paths": artifact_paths,
            "artifact_refs": row_artifact_refs,
            "artifact_hashes": {
                name: str(ref["sha256"])
                for name, ref in row_artifact_refs.items()
                if ref.get("sha256")
            },
            "present_claimable_artifact_names": present_names,
            "status": "present_hash_valid" if not blockers else "blocked_missing_input",
            "blockers": blockers,
            "completion_claim": "requirement_evidence_matrix_hash_bound",
        }
        if spec["requirement_id"] in FULL_SCF_EVALUATED_HYBRID_STATUS_REQUIREMENT_IDS:
            checklist_row[
                "full_scf_evaluated_hybrid_status"
            ] = full_scf_evaluated_hybrid_status
        checklist.append(checklist_row)
    return {
        **_common_payload(status),
        "schema_version": "dse.complete_dse.prompt_to_artifact_checklist.v1",
        "checklist": checklist,
        "full_scf_evaluated_hybrid_status": full_scf_evaluated_hybrid_status,
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
        "| Requirement | Status | Artifact refs | Completion claim |",
        "| --- | --- | --- | --- |",
    ]
    for row in checklist.get("checklist", []) or []:
        if not isinstance(row, Mapping):
            continue
        artifact_refs = row.get("artifact_refs", {})
        artifact_summary = ""
        if isinstance(artifact_refs, Mapping):
            artifact_summary = ", ".join(
                f"{name}={ref.get('path')}#{str(ref.get('sha256', ''))[:12]}"
                for name, ref in artifact_refs.items()
                if isinstance(ref, Mapping)
            )
        elif isinstance(row.get("artifact"), Mapping):
            artifact = row["artifact"]
            artifact_summary = f"{artifact.get('path')}#{str(artifact.get('sha256', ''))[:12]}"
        lines.append(
            f"| `{row.get('requirement')}` | `{row.get('status')}` | `{artifact_summary}` | `{row.get('completion_claim')}` |"
        )
    lines.extend(
        [
            "",
            "## Claim boundary",
            "",
            str(checklist.get("claim_boundary", "")),
            "",
        ]
    )
    return "\n".join(lines)


def write_complete_dse_reporting_package(
    out_dir: Path,
    *,
    candidate_ids: Iterable[str] | None = None,
    workload_case_ids: Iterable[str] | None = None,
    l4_rows: Sequence[Mapping[str, Any]] | None = None,
    source_artifact_refs: Mapping[str, Any] | None = None,
    status: str = "draft",
) -> Dict[str, Any]:
    """Write the reporting-lane artifact package and return a status payload."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_id_list = _normalise_ids(candidate_ids or ["candidate_draft"])
    workload_id_list = _normalise_ids(
        workload_case_ids or ["workload_case_draft"]
    )
    rows = [
        dict(row)
        for row in (
            l4_rows
            or [
                blocked_l4_row(
                    candidate_id_list[0],
                    workload_id_list[0],
                    reason="L4 full-flow evidence matrix has not been executed for this draft package",
                )
            ]
        )
    ]
    fpga_candidate_id = candidate_id_list[0]
    asic_candidate_id = (
        candidate_id_list[1] if len(candidate_id_list) > 1 else candidate_id_list[0]
    )
    effective_source_artifact_refs = dict(source_artifact_refs or {})
    derived_decision_summary_ref = _derived_deployment_decision_summary_ref(
        effective_source_artifact_refs
    )
    if (
        derived_decision_summary_ref is not None
        and "dft_deployment_decision_summary.json" not in effective_source_artifact_refs
    ):
        effective_source_artifact_refs[
            "dft_deployment_decision_summary.json"
        ] = derived_decision_summary_ref

    candidate_workflow_ledger_rows = (
        _candidate_workflow_ledger_rows_with_qe_baseline_materialization(
            rows,
            effective_source_artifact_refs,
        )
    )
    producer_refs = _producer_artifact_refs(effective_source_artifact_refs)
    fpga_tool_manifest = _target_tool_evidence_manifest_payload(
        "fpga",
        producer_artifact_name="dft_candidate_workflow_target_evidence_gate_ledger.json",
        stage_ids=(
            "golden_correctness",
            "hls_or_rtl_sim",
            "hls_or_rtl_synth",
            "vivado_fpga_synth_or_impl",
        ),
    )
    asic_tool_manifest = _target_tool_evidence_manifest_payload(
        "asic",
        producer_artifact_name="dft_candidate_workflow_target_evidence_gate_ledger.json",
        stage_ids=(
            "golden_correctness",
            "rtl_sim",
            "dc_asic_synth_timing_area",
        ),
    )
    fpga_recommendation_report = _target_recommendation_report_payload(
        "fpga",
        candidate_id=fpga_candidate_id,
        producer_artifact_name="dft_candidate_workflow_target_evidence_gate_ledger.json",
        evidence_manifest_name="fpga_hls_rtl_vivado_evidence_manifest.json",
        producer_artifact_refs=producer_refs,
    )
    asic_recommendation_report = _target_recommendation_report_payload(
        "asic",
        candidate_id=asic_candidate_id,
        producer_artifact_name="dft_candidate_workflow_target_evidence_gate_ledger.json",
        evidence_manifest_name="asic_dc_timing_area_evidence_manifest.json",
        producer_artifact_refs=producer_refs,
    )
    deployment_recommendation_report = _deployment_recommendation_report_payload(
        fpga_recommendation_report,
        asic_recommendation_report,
        producer_artifact_refs=producer_refs,
    )

    report_payloads: dict[str, Mapping[str, Any]] = {
        "workload_architecture_prior_report.json": {
            **_common_payload(status),
            "schema_version": "dse.complete_dse.workload_architecture_prior_report.v1",
            "workload_facts": [
                {
                    "feature": "fft_rho_potential_streaming_paths",
                    "preferred_architecture_seeds": [
                        "streaming_pipeline",
                        "pipeline_simd_fused",
                    ],
                    "claim_boundary": "Architecture prior only; not a post-freeze Top-K completion shortcut.",
                },
                {
                    "feature": "h_psi_s_psi_subspace_matrix_kernels",
                    "preferred_architecture_seeds": [
                        "spatial_pe_array",
                        "pipeline_spatial_array",
                    ],
                    "claim_boundary": "Architecture prior only; not a trusted speedup claim.",
                },
                {
                    "feature": "multi_kernel_qe_iteration_overlap",
                    "preferred_architecture_seeds": [
                        "task_parallel_engines",
                        "pipeline_task_overlap",
                    ],
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
            "allowed_prune_reasons": [
                "illegal",
                "research_only",
                "over_budget",
                "blocked",
            ],
            "pruned_combinations": [],
            "post_freeze_row_removal_allowed": False,
            "claim_boundary": (
                "Pruning is valid only as pre-freeze rationale. Post-freeze Top-K, "
                "representative, Pareto, or promoted-only substitution cannot complete a release."
            ),
        },
        "release_candidate_trial_ledger.json": {
            **_common_payload("blocked"),
            "schema_version": "dse.codesign.complete_dse.release_candidate_trial_ledger.v1",
            "status": "blocked",
            "candidate_count": len(candidate_id_list),
            "legal_candidate_count": len(candidate_id_list),
            "frozen_workload_case_count": len(workload_id_list),
            "required_l4_evidence_row_count": (
                len(candidate_id_list) * len(workload_id_list)
            ),
            "observed_l4_evidence_row_count": len(rows),
            "release_completion_eligible": False,
            "trusted_final_claim": False,
            "blockers": [
                "release_candidate_trial_ledger_is_reporting_contract_only",
                "trusted_l4_candidate_x_workload_matrix_not_complete",
            ],
            "claim_boundary": (
                "This ledger declares the frozen candidate/workload accounting "
                "required before release. Its presence does not upgrade draft, "
                "blocked, projection, or incomplete L4 rows to deliverable_complete."
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
            "allowed_claims": [
                "research_projection",
                "release_l3_projection",
                "blocked",
            ],
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
        "workload_coverage_report.json": _blocked_report_payload(
            schema_version="dse.complete_dse.workload_coverage_report.v1",
            blocker="workload_coverage_report_requires_run1_release_bundle",
            covered_workload_case_ids=workload_id_list,
        ),
        "deployment_boundary_search_report.json": _blocked_report_payload(
            schema_version="dse.complete_dse.deployment_boundary_search_report.v1",
            blocker="deployment_boundary_search_requires_run1_generated_search_artifacts",
            candidate_ids=candidate_id_list,
            searched_boundaries=[],
        ),
        "dft_deployment_decision_summary.json": _blocked_report_payload(
            schema_version="dse.dft.current_goal.deployment_decision_summary.reporting_ref.v1",
            blocker="dft_deployment_decision_summary_requires_source_artifact_ref",
            source_lane="run1",
            source_alias_path=(
                "complete_dse_release_artifact_package.json:"
                "decision_summary_inputs.deployment_decision_summary"
            ),
            deliverable_complete=False,
            claim_boundary=(
                "The canonical deployment decision-summary ref is a release-provenance "
                "surface only. It must be hash-bound from the source artifact and "
                "cannot claim FPGA/ASIC PPA, trusted speedup, or deliverable completion."
            ),
        ),
        "fpga_recommendation_report.json": fpga_recommendation_report,
        "asic_recommendation_report.json": asic_recommendation_report,
        "deployment_recommendation_report.json": deployment_recommendation_report,
        "fpga_hls_rtl_vivado_evidence_manifest.json": fpga_tool_manifest,
        "asic_dc_timing_area_evidence_manifest.json": asic_tool_manifest,
        "release_universe_manifest.json": _blocked_report_payload(
            schema_version="dse.complete_dse.release_universe_manifest.reporting_ref.v1",
            blocker="release_universe_manifest_requires_run1_release_universe_ref",
            source_lane="run1",
            expected_release_package_refs=list(RELEASE_PACKAGE_REPORTING_ARTIFACTS),
            expected_release_package_alias="release_universe_manifest",
            source_alias_path=(
                "complete_dse_release_artifact_package.json:"
                "current_goal_checklist_traceability.alias_refs.release_universe_manifest"
            ),
            deliverable_complete=False,
            claim_boundary=(
                "The release-universe ref is bound for reporting traceability only. "
                "It remains non-claimable until run1 provides a complete, hash-bound "
                "release universe and every downstream evidence gate closes."
            ),
        ),
        "candidate_workflow_target_evidence_matrix.json": _blocked_report_payload(
            schema_version="dse.dft.candidate_workflow_target_evidence_matrix.reporting_ref.v1",
            blocker="candidate_workflow_target_evidence_matrix_requires_run2_target_gate_ledger",
            source_lane="run2",
            expected_target_ledger_refs=list(TARGET_EVIDENCE_GATE_LEDGER_ARTIFACTS),
            candidate_ids=candidate_id_list,
            workload_case_ids=workload_id_list,
            rows=[],
            allowed_statuses=[
                "trusted_pass",
                "trusted_fail",
                "pruned_with_reason",
                "blocked_missing_input",
                "blocked_tool_unavailable",
                "blocked_invalid_evidence",
                "projection_only_not_claimable",
            ],
            deliverable_complete=False,
            claim_boundary=(
                "The target evidence matrix ref points to run2 ledger inputs. "
                "It cannot upgrade blocked, projection-only, unavailable-tool, or "
                "incomplete candidate x workflow x target rows into FPGA/ASIC "
                "recommendation proof."
            ),
        ),
        "candidate_workflow_evidence_ledger.json": _blocked_report_payload(
            schema_version="dse.complete_dse.candidate_workflow_evidence_ledger.v1",
            blocker="candidate_workflow_evidence_ledger_requires_run2_target_gate_rows",
            candidate_ids=candidate_id_list,
            workload_case_ids=workload_id_list,
            rows=candidate_workflow_ledger_rows,
            pure_software_qe_baseline_materialization_attached=any(
                bool(row.get("pure_software_qe_baseline_materialization_attached"))
                for row in candidate_workflow_ledger_rows
            ),
            claim_boundary=(
                "Candidate/workflow evidence ledger rows may include pure-software "
                "QE baseline materialization refs for baseline comparison traceability. "
                "Those refs are not target PPA evidence and cannot upgrade hardware, "
                "release, or deliverable-complete claims."
            ),
        ),
        "complete_dse_release_artifact_package.json": _blocked_report_payload(
            schema_version="dse.dft.current_goal.complete_dse_release_artifact_package.v1",
            blocker="complete_dse_release_artifact_package_requires_run1_materialized_release_package",
            release_id="current_goal_release_package",
            package_hash=None,
            current_goal_checklist_traceability={
                "status": "blocked_missing_run1_release_package",
                "alias_refs": {},
                "blockers": [
                    "current_goal_checklist_traceability_requires_run1_release_package"
                ],
                "claim_boundary": (
                    "Checklist traceability aliases are package-local hash refs. "
                    "They preserve release-package provenance only and cannot "
                    "upgrade completion or FPGA/ASIC recommendation claims."
                ),
            },
            artifact_hash_manifest={
                "canonical_name": "complete_dse_release_artifact_hash_manifest.json",
                "schema_version": "dse.dft.current_goal.complete_dse_release_artifact_hash_manifest.v1",
                "manifest_hash": None,
            },
            stable_artifact_names=list(RELEASE_PACKAGE_REPORTING_ARTIFACTS),
            release_candidate_identity_provenance_status="blocked",
            release_candidate_identity_provenance_blocker_ids=[
                "deployment_decision_summary_not_bound",
                "strict_qe_release_lane_bundle_not_supplied_to_audit",
            ],
            release_candidate_identity_provenance_package_exists=True,
            release_candidate_identity_provenance_package_status="blocked",
            release_candidate_identity_provenance_canonical_bundle_bound=False,
            release_candidate_identity_provenance_trusted_for_release_package_candidate_identity=False,
            release_candidate_identity_provenance_claim_boundary=(
                "Release-package candidate identity provenance is a fail-closed "
                "binding audit. It only reports whether the canonical deployment "
                "decision summary and strict release-lane bundle are bound; it "
                "is not FPGA/ASIC PPA evidence and does not imply deliverable "
                "completion."
            ),
            deliverable_complete=False,
        ),
        "complete_dse_release_artifact_hash_manifest.json": _blocked_report_payload(
            schema_version="dse.dft.current_goal.complete_dse_release_artifact_hash_manifest.v1",
            blocker="complete_dse_release_artifact_hash_manifest_requires_run1_materialized_release_package",
            release_id="current_goal_release_package",
            artifact_count=0,
            stable_artifact_names=list(RELEASE_PACKAGE_REPORTING_ARTIFACTS),
            release_candidate_identity_provenance_status="blocked",
            release_candidate_identity_provenance_blocker_ids=[
                "deployment_decision_summary_not_bound",
                "strict_qe_release_lane_bundle_not_supplied_to_audit",
            ],
            release_candidate_identity_provenance_package_exists=True,
            release_candidate_identity_provenance_package_status="blocked",
            release_candidate_identity_provenance_canonical_bundle_bound=False,
            release_candidate_identity_provenance_trusted_for_release_package_candidate_identity=False,
            release_candidate_identity_provenance_claim_boundary=(
                "Release-package candidate identity provenance is a fail-closed "
                "binding audit. It only reports whether the canonical deployment "
                "decision summary and strict release-lane bundle are bound; it "
                "is not FPGA/ASIC PPA evidence and does not imply deliverable "
                "completion."
            ),
            current_goal_checklist_traceability={
                "status": "blocked_missing_run1_release_package",
                "alias_refs": {},
                "blockers": [
                    "current_goal_checklist_traceability_requires_run1_release_package"
                ],
            },
            deliverable_complete=False,
        ),
        "complete_dse_done_when_4_6_audit.json": _blocked_report_payload(
            schema_version="dse.complete_dse.done_when_4_6_audit.v1",
            blocker="done_when_4_6_audit_not_attached_to_reporting_package",
            audited_requirements=["done_when_04", "done_when_05", "done_when_06"],
        ),
        "status.json": _blocked_report_payload(
            schema_version="dse.complete_dse.done_when_4_6_audit_status.v1",
            blocker="done_when_4_6_audit_status_not_attached_to_reporting_package",
        ),
        "dft_candidate_workflow_target_evidence_gate_ledger.json": _blocked_report_payload(
            schema_version="dse.dft.candidate_workflow_target_evidence_gate_ledger.v1",
            blocker="target_evidence_gate_ledger_requires_run2_real_tool_evidence",
            rows=[],
            allowed_statuses=[
                "trusted_pass",
                "trusted_fail",
                "pruned_with_reason",
                "blocked_missing_input",
                "blocked_tool_unavailable",
                "blocked_invalid_evidence",
                "projection_only_not_claimable",
            ],
        ),
        "dft_candidate_workflow_target_evidence_gate_ledger_validation.json": _blocked_report_payload(
            schema_version="dse.dft.candidate_workflow_target_evidence_gate_ledger_validation.v1",
            blocker="target_evidence_gate_ledger_validation_requires_complete_ledger",
            valid=False,
        ),
        "dft_candidate_workflow_target_evidence_gate_ledger_status.json": _blocked_report_payload(
            schema_version="dse.dft.candidate_workflow_target_evidence_gate_ledger_status.v1",
            blocker="target_evidence_gate_ledger_status_requires_complete_ledger",
            complete=False,
            completion_complete=False,
        ),
        "ic_eda_tool_availability.json": _blocked_report_payload(
            schema_version="dse.dft_scf.ic_eda_tool_availability.reporting_stub.v1",
            blocker="ic_eda_tool_availability_requires_run2_toolchain_probe",
            environment="unavailable",
            selected_probe_transport="blocked",
            probe_order=[],
            raw_attempts=[],
            raw_command_transcript_refs=[],
            raw_command_transcript_ref_count=0,
            availability_only_not_kernel_ppa=True,
            kernel_ppa_evidence=False,
            hardware_completion_eligible=False,
            deliverable_complete=False,
        ),
        "ic_eda_tool_attempts.json": _blocked_report_payload(
            schema_version="dse.dft_scf.ic_eda_tool_attempts.reporting_stub.v1",
            blocker="ic_eda_tool_attempts_requires_run2_toolchain_probe",
            attempts=[],
            raw_command_transcript_refs=[],
            raw_command_transcript_ref_count=0,
            deliverable_complete=False,
        ),
        "ic_eda_toolchain_transcript_manifest.json": _blocked_report_payload(
            schema_version="dse.dft_scf.ic_eda_toolchain_transcript_manifest.reporting_stub.v1",
            blocker="ic_eda_toolchain_transcript_manifest_requires_run2_toolchain_probe",
            raw_command_transcript_refs=[],
            raw_command_transcript_ref_count=0,
            transcript_count=0,
            deliverable_complete=False,
        ),
        "qe_baseline_comparison_index.json": _blocked_report_payload(
            schema_version="dse.dft.qe_baseline_comparison_index.reporting_ref.v1",
            blocker="qe_baseline_comparison_index_requires_run3_six_class_bundle",
            comparison_case_count=0,
            comparison_rows=[],
            deliverable_complete=False,
        ),
        "dft_scf_six_class_qe_baseline_materialization.json": _blocked_report_payload(
            schema_version="dse.dft_scf.six_class_qe_baseline_materialization.reporting_ref.v1",
            blocker="dft_scf_six_class_qe_baseline_materialization_requires_qe_baseline_materialization_triplet",
            source_lane="run2",
            expected_producer_artifacts=list(QE_BASELINE_MATERIALIZATION_REPORTING_ARTIFACTS),
            case_count=0,
            passed_case_count=0,
            blocked_case_count=0,
            strict_scf_class_ids=[],
            blocker_id_counts={},
            pure_software_qe_baseline=True,
            hardware_acceleration_evidence=False,
            hardware_completion_eligible=False,
            release_completion_eligible=False,
            trusted_final_claim=False,
            deliverable_complete=False,
            claim_boundary=(
                "Six-class QE baseline materialization is a pure-software "
                "baseline-reporting input. It cannot prove acceleration, PPA, "
                "hardware completion, release completion, or deliverable_complete."
            ),
        ),
        "dft_scf_six_class_qe_baseline_materialization_validation.json": _blocked_report_payload(
            schema_version="dse.dft_scf.six_class_qe_baseline_materialization_validation.reporting_ref.v1",
            blocker="dft_scf_six_class_qe_baseline_materialization_validation_requires_qe_baseline_materialization_triplet",
            source_lane="run2",
            expected_producer_artifacts=list(QE_BASELINE_MATERIALIZATION_REPORTING_ARTIFACTS),
            valid=False,
            error_count=0,
            warning_count=0,
            hardware_acceleration_evidence=False,
            hardware_completion_eligible=False,
            release_completion_eligible=False,
            trusted_final_claim=False,
            deliverable_complete=False,
            claim_boundary=(
                "The materialization validation row only records whether the "
                "pure-software QE baseline triplet is structurally valid; it is "
                "not target evidence."
            ),
        ),
        "dft_scf_six_class_qe_baseline_materialization_status.json": _blocked_report_payload(
            schema_version="dse.dft_scf.six_class_qe_baseline_materialization_status.reporting_ref.v1",
            blocker="dft_scf_six_class_qe_baseline_materialization_status_requires_qe_baseline_materialization_triplet",
            source_lane="run2",
            expected_producer_artifacts=list(QE_BASELINE_MATERIALIZATION_REPORTING_ARTIFACTS),
            materialization_complete=False,
            ready_for_accelerated_numeric_evidence=False,
            hardware_acceleration_evidence=False,
            hardware_completion_eligible=False,
            release_completion_eligible=False,
            trusted_final_claim=False,
            deliverable_complete=False,
            claim_boundary=(
                "The materialization status is a fail-closed bridge from the "
                "six-class QE bundle to baseline comparison consumers only."
            ),
        ),
        "qe_full_scf_hook_coverage_campaign_audit.json": _blocked_report_payload(
            schema_version="dse.qe.full_scf_hook_coverage_campaign_audit.reporting_ref.v1",
            blocker="qe_full_scf_hook_coverage_campaign_audit_requires_run3_hook_campaign_audit",
            audit_row_count=0,
            blocked_row_count=0,
            deliverable_complete=False,
        ),
        "strict_full_scf_evidence_gap.json": _blocked_report_payload(
            schema_version="dse.dft.numerical.strict_full_scf_evidence_gap.reporting_ref.v1",
            blocker="strict_full_scf_evidence_gap_requires_run3_runtime_trace_and_provenance",
            missing_required_artifact_labels=[],
            existing_required_artifact_labels=[],
            diagnostic_blockers=[],
            deliverable_complete=False,
        ),
        "full_scf_runtime_event_manifest.json": _blocked_report_payload(
            schema_version="dse.dft.numerical.full_scf_runtime_event_manifest.reporting_ref.v1",
            blocker="full_scf_runtime_event_manifest_requires_run3_measured_trace",
            required_event_categories={},
            deliverable_complete=False,
        ),
        "runtime_execution_proof.json": _blocked_report_payload(
            schema_version="dse.dft.numerical.runtime_execution_proof.reporting_ref.v1",
            blocker="runtime_execution_proof_requires_run3_runtime_trace_or_hardware_proof",
            passed=False,
            deliverable_complete=False,
        ),
        "full_scf_runtime_trace.json": _blocked_report_payload(
            schema_version="dse.dft.numerical.full_scf_runtime_trace.reporting_ref.v1",
            blocker="full_scf_runtime_trace_requires_run3_runtime_events",
            events=[],
            deliverable_complete=False,
        ),
        "full_scf_row_accounting.json": _blocked_report_payload(
            schema_version="dse.dft.numerical.full_scf_row_accounting.reporting_ref.v1",
            blocker="full_scf_row_accounting_requires_run3_runtime_trace",
            diagnostic_blockers=[],
            deliverable_complete=False,
        ),
        "full_scf_end_to_end_comparison.json": _blocked_report_payload(
            schema_version="dse.dft.numerical.full_scf_end_to_end_comparison.reporting_ref.v1",
            blocker="full_scf_end_to_end_comparison_requires_run3_full_matrix_rows",
            candidate_records=[],
            row_records=[],
            deliverable_complete=False,
        ),
    }

    for name, payload in report_payloads.items():
        _write_json(out_dir / name, payload)

    required_refs = {
        name: _artifact_ref_from_payload(
            out_dir / name,
            base_dir=out_dir,
            payload=payload,
        )
        for name, payload in report_payloads.items()
    }
    _merge_source_artifact_refs(required_refs, effective_source_artifact_refs)
    full_scf_evaluated_hybrid_status = (
        _full_scf_evaluated_hybrid_status_from_artifact_refs(required_refs)
    )
    for target_report in (fpga_recommendation_report, asic_recommendation_report):
        target_report[
            "full_scf_evaluated_hybrid_status"
        ] = full_scf_evaluated_hybrid_status
        for section_name in ("best", "pareto"):
            section = target_report.get(section_name)
            if isinstance(section, dict):
                section[
                    "full_scf_evaluated_hybrid_status"
                ] = full_scf_evaluated_hybrid_status
    deployment_recommendation_report[
        "full_scf_evaluated_hybrid_status"
    ] = full_scf_evaluated_hybrid_status
    deployment_recommendations = deployment_recommendation_report.get(
        "recommendations"
    )
    if isinstance(deployment_recommendations, dict):
        deployment_recommendations["fpga"] = dict(fpga_recommendation_report)
        deployment_recommendations["asic"] = dict(asic_recommendation_report)
    deployment_recommendation_report["best_recommendation_sections"] = {
        "fpga": fpga_recommendation_report.get("best", {}),
        "asic": asic_recommendation_report.get("best", {}),
    }
    deployment_recommendation_report["pareto_recommendation_sections"] = {
        "fpga": fpga_recommendation_report.get("pareto", {}),
        "asic": asic_recommendation_report.get("pareto", {}),
    }
    for name, payload in (
        ("fpga_recommendation_report.json", fpga_recommendation_report),
        ("asic_recommendation_report.json", asic_recommendation_report),
        ("deployment_recommendation_report.json", deployment_recommendation_report),
    ):
        _write_json(out_dir / name, payload)
        required_refs[name] = _artifact_ref_from_payload(
            out_dir / name,
            base_dir=out_dir,
            payload=payload,
        )

    def _refresh_requirement_surfaces(
        recommendation_report: Mapping[str, Any],
    ) -> Dict[str, Any]:
        checklist_payload = _build_prompt_to_artifact_checklist(
            required_refs, status
        )
        _write_json(out_dir / "prompt_to_artifact_checklist.json", checklist_payload)
        _write_text(
            out_dir / "prompt_to_artifact_checklist.md",
            render_prompt_to_artifact_markdown(checklist_payload),
        )
        required_refs["prompt_to_artifact_checklist.json"] = _artifact_ref_from_payload(
            out_dir / "prompt_to_artifact_checklist.json",
            base_dir=out_dir,
            payload=checklist_payload,
        )
        required_refs["prompt_to_artifact_checklist.md"] = _artifact_ref(
            out_dir / "prompt_to_artifact_checklist.md", base_dir=out_dir
        )

        audit_payload = build_requirement_evidence_audit_matrix(
            artifact_refs=required_refs,
            recommendation_report=recommendation_report,
            source_producer_artifact_refs=producer_refs,
            status=status,
        )
        _write_json(out_dir / "requirement_evidence_matrix.json", audit_payload)
        _write_text(
            out_dir / "requirement_evidence_matrix.md",
            render_requirement_evidence_audit_markdown(audit_payload),
        )
        required_refs["requirement_evidence_matrix.json"] = _artifact_ref_from_payload(
            out_dir / "requirement_evidence_matrix.json",
            base_dir=out_dir,
            payload=audit_payload,
        )
        required_refs["requirement_evidence_matrix.md"] = _artifact_ref(
            out_dir / "requirement_evidence_matrix.md", base_dir=out_dir
        )
        return audit_payload

    coverage_report = build_coverage_claim_report(
        candidate_ids=candidate_id_list,
        workload_case_ids=workload_id_list,
        l4_rows=rows,
        required_artifacts=required_refs,
        status=status,
    )
    coverage_report["target_scoped_recommendations"] = {
        "fpga": fpga_recommendation_report,
        "asic": asic_recommendation_report,
    }
    coverage_report["deployment_recommendation_report"] = deployment_recommendation_report
    coverage_report["deployment_recommendations"] = {
        "recommendations": {
            "fpga": fpga_recommendation_report,
            "asic": asic_recommendation_report,
        },
        "status": deployment_recommendation_report["status"],
        "recommendation_scope": deployment_recommendation_report["recommendation_scope"],
        "deliverable_complete": False,
        "trusted_final_claim": False,
    }
    _write_json(out_dir / "coverage_claim_report.json", coverage_report)
    _write_text(
        out_dir / "coverage_claim_report.md",
        render_coverage_claim_markdown(coverage_report),
    )
    required_refs["coverage_claim_report.json"] = _artifact_ref_from_payload(
        out_dir / "coverage_claim_report.json",
        base_dir=out_dir,
        payload=coverage_report,
    )
    required_refs["coverage_claim_report.md"] = _artifact_ref(
        out_dir / "coverage_claim_report.md", base_dir=out_dir
    )

    requirement_audit = _refresh_requirement_surfaces(coverage_report)

    final_coverage_report = {
        **coverage_report,
        "required_artifacts": required_refs,
        "requirement_evidence_matrix": requirement_audit,
    }
    final_validation = validate_complete_dse_claim_report(
        final_coverage_report
    )
    claim_validation_report = _build_claim_validation_report(
        final_validation,
        candidate_ids=candidate_id_list,
        workload_case_ids=workload_id_list,
    )
    _write_json(out_dir / "claim_validation_report.json", claim_validation_report)
    required_refs["claim_validation_report.json"] = _artifact_ref_from_payload(
        out_dir / "claim_validation_report.json",
        base_dir=out_dir,
        payload=claim_validation_report,
    )
    blocker_report = _build_blocker_report(
        final_validation,
        requirement_audit,
        candidate_ids=candidate_id_list,
        workload_case_ids=workload_id_list,
        source_producer_artifact_refs=producer_refs,
    )
    _write_json(out_dir / "blocker_report.json", blocker_report)
    required_refs["blocker_report.json"] = _artifact_ref_from_payload(
        out_dir / "blocker_report.json",
        base_dir=out_dir,
        payload=blocker_report,
    )
    artifact_hash_manifest = _build_artifact_hash_manifest(
        required_refs,
        status="passed",
    )
    _write_json(out_dir / "artifact_hash_manifest.json", artifact_hash_manifest)
    required_refs["artifact_hash_manifest.json"] = _artifact_ref_from_payload(
        out_dir / "artifact_hash_manifest.json",
        base_dir=out_dir,
        payload=artifact_hash_manifest,
    )

    final_coverage_report = {
        **coverage_report,
        "required_artifacts": required_refs,
    }
    requirement_audit = _refresh_requirement_surfaces(final_coverage_report)
    final_coverage_report["requirement_evidence_matrix"] = requirement_audit
    final_validation = validate_complete_dse_claim_report(
        final_coverage_report
    )
    claim_validation_report = _build_claim_validation_report(
        final_validation,
        candidate_ids=candidate_id_list,
        workload_case_ids=workload_id_list,
    )
    _write_json(out_dir / "claim_validation_report.json", claim_validation_report)
    required_refs["claim_validation_report.json"] = _artifact_ref_from_payload(
        out_dir / "claim_validation_report.json",
        base_dir=out_dir,
        payload=claim_validation_report,
    )
    blocker_report = _build_blocker_report(
        final_validation,
        requirement_audit,
        candidate_ids=candidate_id_list,
        workload_case_ids=workload_id_list,
        source_producer_artifact_refs=producer_refs,
    )
    _write_json(out_dir / "blocker_report.json", blocker_report)
    required_refs["blocker_report.json"] = _artifact_ref_from_payload(
        out_dir / "blocker_report.json",
        base_dir=out_dir,
        payload=blocker_report,
    )
    artifact_hash_manifest = _build_artifact_hash_manifest(
        required_refs,
        status="passed",
    )
    _write_json(out_dir / "artifact_hash_manifest.json", artifact_hash_manifest)
    required_refs["artifact_hash_manifest.json"] = _artifact_ref_from_payload(
        out_dir / "artifact_hash_manifest.json",
        base_dir=out_dir,
        payload=artifact_hash_manifest,
    )

    final_coverage_report["claim_validation"] = final_validation
    final_coverage_report["required_artifacts"] = required_refs
    _write_json(out_dir / "coverage_claim_report.json", final_coverage_report)
    _write_text(
        out_dir / "coverage_claim_report.md",
        render_coverage_claim_markdown(final_coverage_report),
    )
    required_refs["coverage_claim_report.json"] = _artifact_ref_from_payload(
        out_dir / "coverage_claim_report.json",
        base_dir=out_dir,
        payload=final_coverage_report,
    )
    required_refs["coverage_claim_report.md"] = _artifact_ref(
        out_dir / "coverage_claim_report.md", base_dir=out_dir
    )

    manifest = {
        **_common_payload("passed" if final_validation["valid"] else "failed"),
        "schema_version": "dse.complete_dse.reporting_artifact_manifest.v1",
        "artifacts": required_refs,
        "coverage_claim_validation": final_validation,
        "source_producer_artifact_refs": producer_refs,
        "source_producer_artifact_ref_count": len(producer_refs),
        "source_lane_summary": _source_lane_summary(producer_refs),
        "trusted_final_claim": final_validation[
            "deliverable_complete_allowed"
        ],
        "deliverable_complete": final_validation[
            "deliverable_complete_allowed"
        ],
    }
    _write_json(out_dir / "reporting_artifact_manifest.json", manifest)
    return manifest
