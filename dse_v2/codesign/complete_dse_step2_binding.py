#!/usr/bin/env python3
"""Step2 admission binding for complete-DSE release candidates.

The complete-DSE release subset freezes stable ``cdse_*`` identities.  This
module turns that finite universe into Step2-owned admission artifacts so later
Step3/L4 runners do not silently bypass candidate generation provenance.  The
artifacts remain claim-neutral: queue admission proves only that every legal
release candidate is scheduled for evaluation, not that timing, correctness, PPA,
or final deployment claims passed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.complete_dse_search_space import (
    RELEASE_ID,
    build_complete_dse_search_effectiveness_report,
    build_release_subset_manifest,
)
from dse_v2.codesign.release_domain import stable_json_hash

BINDING_SCHEMA = "dse.codesign.complete_dse.step2_binding.v1"
QUEUE_SCHEMA = "dse.step3.simulation_queue.v1"
LEDGER_SCHEMA = "dse.step2.trial_state_ledger.v1"
VALIDATION_SCHEMA = "dse.codesign.complete_dse.step2_binding_validation.v1"
STATUS_SCHEMA = "dse.codesign.complete_dse.step2_binding_status.v1"
QUEUE_MODE = "complete-dse-release-universe"


def _stable_hash_without(payload: Mapping[str, Any], *excluded_keys: str) -> str:
    return stable_json_hash(
        {key: value for key, value in payload.items() if key not in excluded_keys}
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _candidate_ids(release_subset: Mapping[str, Any]) -> list[str]:
    ids = [str(item) for item in release_subset.get("legal_candidate_ids", []) or []]
    if ids:
        return ids
    return [
        str(candidate.get("candidate_id"))
        for candidate in release_subset.get("candidates", []) or []
        if isinstance(candidate, Mapping)
        and candidate.get("legal", True)
        and candidate.get("candidate_id")
    ]


def _candidate_index(release_subset: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate.get("candidate_id")): candidate
        for candidate in release_subset.get("candidates", []) or []
        if isinstance(candidate, Mapping) and candidate.get("candidate_id")
    }


def _identity_layers(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    identity = _as_mapping(candidate.get("identity"))
    return _as_mapping(identity.get("identity_layers"))


def _layer(candidate: Mapping[str, Any], layer_name: str) -> Dict[str, Any]:
    return _as_mapping(_identity_layers(candidate).get(layer_name))


def _taxonomy_id(candidate: Mapping[str, Any]) -> str:
    architecture = _layer(candidate, "architecture_parameters")
    return str(architecture.get("taxonomy_id") or candidate.get("taxonomy_id") or "")


def _mapping_id(candidate: Mapping[str, Any]) -> str:
    mapping = _layer(candidate, "mapping_layout_parameters")
    return str(mapping.get("mapping_id") or candidate.get("mapping_id") or "")


def _compile_schedule_id(candidate: Mapping[str, Any]) -> str:
    schedule = _layer(candidate, "compile_time_schedule_parameters")
    return str(schedule.get("compile_schedule_id") or candidate.get("compile_schedule_id") or "")


def _runtime_schedule_id(candidate: Mapping[str, Any]) -> str:
    schedule = _layer(candidate, "runtime_scheduling_parameters")
    return str(schedule.get("runtime_schedule_id") or candidate.get("runtime_schedule_id") or "")


def _profile_id(candidate: Mapping[str, Any]) -> str:
    for name in (
        "algorithm_parameters",
        "architecture_parameters",
        "mapping_layout_parameters",
        "compile_time_schedule_parameters",
        "runtime_scheduling_parameters",
        "target_platform_parameters",
    ):
        layer = _layer(candidate, name)
        if layer.get("parameter_profile_id"):
            return str(layer["parameter_profile_id"])
    return str(candidate.get("parameter_profile_id") or "")


def _target_platform(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    return _layer(candidate, "target_platform_parameters")


def _release_matrix_provenance(release_subset: Mapping[str, Any]) -> Dict[str, Any]:
    contract = _as_mapping(
        release_subset.get("candidate_workflow_deployment_target_matrix_contract")
    )
    provenance = _as_mapping(release_subset.get("generation_provenance"))
    return {
        "schema_version": "dse.codesign.complete_dse.release_matrix_provenance.v1",
        "release_id": release_subset.get("release_id"),
        "matrix_contract_hash": contract.get("contract_hash"),
        "matrix_rows_hash": release_subset.get(
            "candidate_workflow_deployment_target_matrix_rows_hash"
        ),
        "matrix_validation_hash": provenance.get(
            "candidate_workflow_deployment_target_matrix_validation_hash"
        ),
        "target_axis_complete": contract.get("target_axis_complete") is True,
        "target_kind_axis_complete": contract.get("target_kind_axis_complete")
        is True,
        "required_target_platform_ids": list(
            contract.get("required_target_platform_ids", []) or []
        ),
        "required_target_platform_kinds": list(
            contract.get("required_target_platform_kinds", []) or []
        ),
        "source_artifact": "release_subset_manifest.json",
    }


def _parameter_hash(candidate: Mapping[str, Any]) -> str:
    identity_hash = candidate.get("identity_hash")
    if identity_hash:
        return f"sha256:{identity_hash}" if not str(identity_hash).startswith("sha256:") else str(identity_hash)
    layers = _identity_layers(candidate)
    if layers:
        return "sha256:" + stable_json_hash(layers)
    return "sha256:" + stable_json_hash({"candidate_id": candidate.get("candidate_id")})


def _candidate_binding(
    candidate_id: str,
    candidate: Mapping[str, Any],
    *,
    release_subset_hash: str | None,
    matrix_provenance: Mapping[str, Any],
    campaign_id: str,
    workload_run_id: str,
    index: int,
) -> Dict[str, Any]:
    taxonomy_id = _taxonomy_id(candidate)
    mapping_id = _mapping_id(candidate)
    compile_id = _compile_schedule_id(candidate)
    runtime_id = _runtime_schedule_id(candidate)
    parameter_profile_id = _profile_id(candidate)
    target = _target_platform(candidate)
    parameter_hash = _parameter_hash(candidate)
    trial_id = f"trial::{RELEASE_ID}::step2::{candidate_id}"
    return {
        "schema_version": "dse.codesign.complete_dse.step2_candidate_binding.v1",
        "release_id": RELEASE_ID,
        "campaign_id": campaign_id,
        "workload_run_id": workload_run_id,
        "trial_id": trial_id,
        "trial_candidate_id": f"{trial_id}::candidate::{candidate_id}",
        "candidate_id": candidate_id,
        "complete_dse_candidate_id": candidate_id,
        "candidate_index": index,
        "release_subset_hash": release_subset_hash,
        "candidate_record_hash": candidate.get("record_hash"),
        "parameter_hash": parameter_hash,
        "candidate_identity_policy": "complete_dse_seven_layer_design_identity",
        "candidate_identity": _identity_layers(candidate),
        "candidate_workflow_deployment_target_matrix_provenance": dict(
            matrix_provenance
        ),
        "taxonomy_id": taxonomy_id,
        "architecture_id": f"release_v1_{taxonomy_id}" if taxonomy_id else "release_v1_unknown",
        "mapping_id": mapping_id,
        "compile_schedule_id": compile_id,
        "runtime_schedule_id": runtime_id,
        "parameter_profile_id": parameter_profile_id,
        "target_platform_id": target.get("target_platform_id"),
        "platform_kind": target.get("platform_kind"),
        "toolchain_flow": target.get("toolchain_flow"),
        "required_claim_gate": target.get("required_claim_gate"),
        "step2_screenable": candidate.get("legal", True) is True,
        "step3_evaluable": candidate.get("legal", True) is True,
        "simulation_eligible": candidate.get("legal", True) is True,
        "promoted_for_simulation": candidate.get("legal", True) is True,
        "simulation_blockers": [] if candidate.get("legal", True) is True else ["candidate_illegal"],
        "queue_state": "scheduled_for_simulation" if candidate.get("legal", True) is True else "blocked_before_step3",
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": (
            "Step2 binding admits a frozen complete-DSE candidate to the Step3/L4 "
            "evaluation queue. It is not timing, correctness, PPA, Pareto, or "
            "deliverable-complete evidence."
        ),
    }


def build_complete_dse_step2_binding(
    release_subset: Mapping[str, Any] | None = None,
    *,
    campaign_id: str | None = None,
    workload_run_id: str | None = None,
) -> Dict[str, Any]:
    subset = dict(release_subset or build_release_subset_manifest())
    candidate_ids = _candidate_ids(subset)
    candidates = _candidate_index(subset)
    release_subset_hash = subset.get("release_subset_hash") or subset.get("manifest_hash")
    matrix_provenance = _release_matrix_provenance(subset)
    campaign = campaign_id or f"campaign::{RELEASE_ID}"
    workload_run = workload_run_id or f"workload_run::{RELEASE_ID}::frozen_suite"
    bindings = [
        _candidate_binding(
            candidate_id,
            candidates.get(candidate_id, {"candidate_id": candidate_id, "legal": True}),
            release_subset_hash=str(release_subset_hash) if release_subset_hash else None,
            matrix_provenance=matrix_provenance,
            campaign_id=campaign,
            workload_run_id=workload_run,
            index=index,
        )
        for index, candidate_id in enumerate(candidate_ids)
    ]
    payload = {
        "schema_version": BINDING_SCHEMA,
        "status": "passed" if bindings and len(bindings) == len(candidate_ids) else "blocked",
        "release_id": RELEASE_ID,
        "campaign_id": campaign,
        "workload_run_id": workload_run,
        "release_subset_hash": release_subset_hash,
        "candidate_workflow_deployment_target_matrix_provenance": matrix_provenance,
        "candidate_count": len(bindings),
        "candidate_ids": candidate_ids,
        "queue_mode": QUEUE_MODE,
        "step3_simulation_queue_artifact": "step3_simulation_queue.json",
        "trial_state_ledger_artifact": "trial_state_ledger.json",
        "candidate_bindings": bindings,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": (
            "Complete-DSE Step2 binding preserves the frozen release candidate "
            "universe for Step3 admission; downstream evidence gates still decide "
            "all speedup, PPA, winner, and completion claims."
        ),
    }
    payload["binding_hash"] = _stable_hash_without(payload, "binding_hash")
    return payload


def build_complete_dse_step3_simulation_queue(
    binding: Mapping[str, Any],
    *,
    backend: str = "gem5_systemc",
) -> Dict[str, Any]:
    entries: list[Dict[str, Any]] = []
    for row in binding.get("candidate_bindings", []) or []:
        if not isinstance(row, Mapping):
            continue
        candidate_id = str(row.get("candidate_id") or "")
        entries.append(
            {
                "queue_entry_id": f"complete-dse-step2::{candidate_id}",
                "candidate_id": candidate_id,
                "complete_dse_candidate_id": candidate_id,
                "design_point_id": f"{candidate_id}::__workload_case_bound_at_step3",
                "design_point_artifact": "rows/<candidate>/<workload>/design_point.json",
                "architecture_id": row.get("architecture_id"),
                "taxonomy_id": row.get("taxonomy_id"),
                "mapping_id": row.get("mapping_id"),
                "compile_schedule_id": row.get("compile_schedule_id"),
                "runtime_schedule_id": row.get("runtime_schedule_id"),
                "parameter_profile_id": row.get("parameter_profile_id"),
                "target_platform_id": row.get("target_platform_id"),
                "platform_kind": row.get("platform_kind"),
                "toolchain_flow": row.get("toolchain_flow"),
                "required_claim_gate": row.get("required_claim_gate"),
                "parameter_hash": row.get("parameter_hash"),
                "candidate_identity": row.get("candidate_identity", {}),
                "candidate_record_hash": row.get("candidate_record_hash"),
                "release_subset_hash": binding.get("release_subset_hash"),
                "candidate_workflow_deployment_target_matrix_provenance": row.get(
                    "candidate_workflow_deployment_target_matrix_provenance"
                ),
                "backend": backend,
                "required_step3_artifacts": [
                    "candidate_record.json",
                    "workload_case.json",
                    "design_point.json",
                    "l3_systemc/simulation_request.json",
                    "l3_systemc/simulation_result.json",
                    "l4_gem5/gem5_l4_proof.json",
                    "evidence_row.json",
                ],
                "priority_score": float(len(entries) + 1),
                "priority_reasons": [
                    {
                        "reason_id": "complete_dse_exhaustive_release_universe",
                        "source": "complete_dse_step2_binding.json",
                    }
                ],
                "review_flags": [],
                "review_required": False,
                "promoted_for_simulation": row.get("promoted_for_simulation") is True,
                "step2_screenable": row.get("step2_screenable") is True,
                "step3_evaluable": row.get("step3_evaluable") is True,
                "simulation_eligible": row.get("simulation_eligible") is True,
                "step3_search_blockers": list(row.get("simulation_blockers", []) or []),
                "queue_state": row.get("queue_state"),
                "blocked_reasons": list(row.get("simulation_blockers", []) or []),
                "l4_required": True,
                "l4_required_reason": "complete-DSE release closure requires every candidate×workload L4 row",
                "admission_source": "complete_dse_step2_binding.json",
                "claim_status": "step2_admission_only",
                "retention_policy": "complete_dse_release_universe",
                "release_completion_eligible": False,
                "blocked_claims": ["trusted_speedup", "hardware_winner", "deliverable_complete"],
                "trusted_final_claim": False,
                "claim_boundary": (
                    "Queue admission is exhaustive Step2 provenance only; L4/QE/EDA "
                    "evidence rows decide trusted claims."
                ),
            }
        )
    payload = {
        "schema_version": QUEUE_SCHEMA,
        "queue_mode": QUEUE_MODE,
        "release_id": RELEASE_ID,
        "campaign_id": binding.get("campaign_id"),
        "workload_run_id": binding.get("workload_run_id"),
        "release_subset_hash": binding.get("release_subset_hash"),
        "candidate_workflow_deployment_target_matrix_provenance": binding.get(
            "candidate_workflow_deployment_target_matrix_provenance"
        ),
        "backend": backend,
        "entry_count": len(entries),
        "candidate_ids": [str(entry.get("candidate_id")) for entry in entries],
        "claim_status": "step2_admission_only",
        "retention_policy": "complete_dse_release_universe",
        "release_completion_eligible": False,
        "blocked_claims": ["trusted_speedup", "hardware_winner", "deliverable_complete"],
        "trusted_final_claim": False,
        "top_k_queue_deferred": False,
        "entries": entries,
        "notes": [
            "Every legal release candidate is admitted; Top-K/representative filtering cannot replace this queue.",
            "Rows remain fail-closed until Step3/Step4/L4/QE/EDA evidence passes.",
        ],
        "claim_boundary": (
            "Complete-DSE Step3 queue preserves release-candidate admission only; "
            "it cannot establish final ranking or completion."
        ),
    }
    payload["queue_hash"] = _stable_hash_without(payload, "queue_hash")
    return payload


def build_complete_dse_trial_state_ledger(
    binding: Mapping[str, Any],
    queue: Mapping[str, Any],
) -> Dict[str, Any]:
    queue_entries = {
        str(entry.get("candidate_id")): entry
        for entry in queue.get("entries", []) or []
        if isinstance(entry, Mapping) and entry.get("candidate_id")
    }
    rows = []
    for row in binding.get("candidate_bindings", []) or []:
        if not isinstance(row, Mapping):
            continue
        candidate_id = str(row.get("candidate_id") or "")
        queue_entry = queue_entries.get(candidate_id, {})
        blockers = list(row.get("simulation_blockers", []) or []) + list(
            queue_entry.get("blocked_reasons", []) or []
        )
        blockers = sorted(dict.fromkeys(str(item) for item in blockers))
        trial_state = "queued_for_step3" if queue_entry.get("queue_state") == "scheduled_for_simulation" else "blocked_before_step3"
        rows.append(
            {
                "schema_version": "dse.step2.trial_candidate_record.v1",
                "campaign_id": row.get("campaign_id"),
                "workload_run_id": row.get("workload_run_id"),
                "trial_id": row.get("trial_id"),
                "trial_candidate_id": row.get("trial_candidate_id"),
                "candidate_type": "complete_dse_release_candidate",
                "candidate_id": candidate_id,
                "complete_dse_candidate_id": candidate_id,
                "architecture_id": row.get("architecture_id"),
                "mapping_candidate_id": row.get("mapping_id"),
                "target_platform_id": row.get("target_platform_id"),
                "platform_kind": row.get("platform_kind"),
                "toolchain_flow": row.get("toolchain_flow"),
                "required_claim_gate": row.get("required_claim_gate"),
                "parameter_hash": row.get("parameter_hash"),
                "candidate_identity_policy": row.get("candidate_identity_policy"),
                "candidate_workflow_deployment_target_matrix_provenance": row.get(
                    "candidate_workflow_deployment_target_matrix_provenance"
                ),
                "generated": True,
                "screened": True,
                "step2_screenable": row.get("step2_screenable") is True,
                "step3_evaluable": row.get("step3_evaluable") is True,
                "simulation_eligible": row.get("simulation_eligible") is True,
                "promoted_for_simulation": row.get("promoted_for_simulation") is True,
                "queue_state": queue_entry.get("queue_state", "not_queued"),
                "trial_state": trial_state,
                "blockers": blockers,
                "search_policy_name": "complete_dse_release_universe_binding",
                "search_policy_candidate_id": candidate_id,
                "search_policy_rank": row.get("candidate_index"),
                "search_policy_provenance": {
                    "source": "complete_dse_step2_binding.json",
                    "release_subset_hash": binding.get("release_subset_hash"),
                    "queue_mode": QUEUE_MODE,
                },
                "transition_history": [
                    {
                        "transition": "candidate_generated",
                        "status": "recorded",
                        "artifact": "release_subset_manifest.json",
                    },
                    {
                        "transition": "step2_binding_admitted",
                        "status": "recorded",
                        "artifact": "complete_dse_step2_binding.json",
                    },
                    {
                        "transition": "promotion_decision",
                        "status": "promote" if row.get("promoted_for_simulation") is True else "block",
                        "artifact": "complete_dse_step2_binding.json",
                    },
                    {
                        "transition": "step3_queue_admission",
                        "status": queue_entry.get("queue_state", "not_queued"),
                        "artifact": "step3_simulation_queue.json",
                    },
                ],
                "artifact_refs": {
                    "release_subset": "release_subset_manifest.json",
                    "step2_binding": "complete_dse_step2_binding.json",
                    "step3_queue": "step3_simulation_queue.json",
                },
                "trusted_final_claim": False,
            }
        )
    state_counts: Dict[str, int] = {}
    for row in rows:
        state = str(row.get("trial_state"))
        state_counts[state] = state_counts.get(state, 0) + 1
    payload = {
        "schema_version": LEDGER_SCHEMA,
        "release_id": RELEASE_ID,
        "campaign_id": binding.get("campaign_id"),
        "workload_run_id": binding.get("workload_run_id"),
        "trial_id": f"trial::{RELEASE_ID}::step2_release_universe",
        "workload_id": str(binding.get("workload_run_id") or RELEASE_ID),
        "workload_family": "complete_dse_release_universe",
        "policy_scope": "complete_dse_release_candidate_binding",
        "trial_state_policy": "complete_dse_generated_screened_promoted_queued_fail_closed_v1",
        "candidate_identity_policy": "complete_dse_seven_layer_design_identity",
        "search_space_artifact": "release_subset_manifest.json",
        "search_space_hash": binding.get("release_subset_hash"),
        "candidate_workflow_deployment_target_matrix_provenance": binding.get(
            "candidate_workflow_deployment_target_matrix_provenance"
        ),
        "candidate_generation_report_artifact": "complete_dse_step2_binding.json",
        "architecture_screening_report_artifact": "complete_dse_step2_binding.json",
        "step3_simulation_queue_artifact": "step3_simulation_queue.json",
        "queue_mode": queue.get("queue_mode"),
        "candidate_count": len(rows),
        "architecture_candidate_count": len(rows),
        "mapping_candidate_count": len(rows),
        "queued_entry_count": len(queue_entries),
        "promoted_candidate_count": sum(1 for row in rows if row.get("promoted_for_simulation")),
        "blocked_candidate_count": sum(1 for row in rows if row.get("blockers")),
        "state_counts": state_counts,
        "all_candidates_have_parameter_hash": all(row.get("parameter_hash") for row in rows),
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "claim_boundary": (
            "Complete-DSE Trial ledger records Step2 admission state only. It "
            "cannot prove L4 speedup, hardware PPA, winner selection, or final completion."
        ),
        "candidates": rows,
    }
    payload["ledger_hash"] = _stable_hash_without(payload, "ledger_hash")
    return payload


def validate_complete_dse_step2_queue(
    *,
    release_subset: Mapping[str, Any],
    step3_queue: Mapping[str, Any],
) -> Dict[str, Any]:
    expected_ids = _candidate_ids(release_subset)
    expected_candidates = _candidate_index(release_subset)
    entries = [
        dict(entry)
        for entry in step3_queue.get("entries", []) or []
        if isinstance(entry, Mapping)
    ]
    actual_ids = [str(entry.get("candidate_id") or "") for entry in entries]
    declared_ids = [
        str(item)
        for item in step3_queue.get("candidate_ids", []) or []
    ]
    expected_hash = release_subset.get("release_subset_hash") or release_subset.get("manifest_hash")
    actual_hash = step3_queue.get("release_subset_hash")
    expected_matrix_provenance = _release_matrix_provenance(release_subset)
    blockers: list[Dict[str, Any]] = []
    expected_queue_hash = _stable_hash_without(step3_queue, "queue_hash")
    if step3_queue.get("queue_hash") != expected_queue_hash:
        blockers.append(
            {
                "id": "step3_queue_hash_mismatch",
                "expected": expected_queue_hash,
                "actual": step3_queue.get("queue_hash"),
            }
        )
    if step3_queue.get("schema_version") != QUEUE_SCHEMA:
        blockers.append({"id": "step3_queue_schema_mismatch", "actual": step3_queue.get("schema_version")})
    if step3_queue.get("queue_mode") != QUEUE_MODE:
        blockers.append({"id": "step3_queue_mode_not_complete_dse_release_universe", "actual": step3_queue.get("queue_mode")})
    if expected_hash and actual_hash != expected_hash:
        blockers.append({"id": "release_subset_hash_mismatch", "expected": expected_hash, "actual": actual_hash})
    if (
        step3_queue.get("candidate_workflow_deployment_target_matrix_provenance")
        != expected_matrix_provenance
    ):
        blockers.append(
            {
                "id": "step3_queue_matrix_provenance_mismatch",
                "expected": expected_matrix_provenance,
                "actual": step3_queue.get(
                    "candidate_workflow_deployment_target_matrix_provenance"
                ),
            }
        )
    if len(entries) != len(expected_ids) or int(step3_queue.get("entry_count") or -1) != len(entries):
        blockers.append(
            {
                "id": "step3_queue_entry_count_mismatch",
                "expected": len(expected_ids),
                "actual": len(entries),
                "declared": step3_queue.get("entry_count"),
            }
        )
    if actual_ids != expected_ids:
        blockers.append(
            {
                "id": "step3_queue_candidate_order_mismatch",
                "expected_count": len(expected_ids),
                "actual_count": len(actual_ids),
                "first_expected": expected_ids[:5],
                "first_actual": actual_ids[:5],
            }
        )
    if declared_ids != actual_ids:
        blockers.append(
            {
                "id": "step3_queue_declared_candidate_ids_mismatch",
                "entry_count": len(actual_ids),
                "declared_count": len(declared_ids),
                "first_entry_ids": actual_ids[:5],
                "first_declared_ids": declared_ids[:5],
            }
        )
    if len(set(actual_ids)) != len(actual_ids):
        blockers.append({"id": "step3_queue_duplicate_candidate_ids"})
    entry_invariant_violations: list[Dict[str, Any]] = []
    for index, entry in enumerate(entries):
        candidate_id = actual_ids[index]
        candidate = expected_candidates.get(candidate_id, {"candidate_id": candidate_id, "legal": True})
        taxonomy_id = _taxonomy_id(candidate)
        target = _target_platform(candidate)
        expected_fields = {
            "complete_dse_candidate_id": candidate_id,
            "queue_entry_id": f"complete-dse-step2::{candidate_id}",
            "design_point_id": f"{candidate_id}::__workload_case_bound_at_step3",
            "architecture_id": f"release_v1_{taxonomy_id}" if taxonomy_id else "release_v1_unknown",
            "taxonomy_id": taxonomy_id,
            "mapping_id": _mapping_id(candidate),
            "compile_schedule_id": _compile_schedule_id(candidate),
            "runtime_schedule_id": _runtime_schedule_id(candidate),
            "parameter_profile_id": _profile_id(candidate),
            "target_platform_id": target.get("target_platform_id"),
            "platform_kind": target.get("platform_kind"),
            "toolchain_flow": target.get("toolchain_flow"),
            "required_claim_gate": target.get("required_claim_gate"),
            "parameter_hash": _parameter_hash(candidate),
            "candidate_identity": _identity_layers(candidate),
            "candidate_record_hash": candidate.get("record_hash"),
            "release_subset_hash": expected_hash,
            "candidate_workflow_deployment_target_matrix_provenance": expected_matrix_provenance,
            "admission_source": "complete_dse_step2_binding.json",
            "claim_status": "step2_admission_only",
            "queue_state": "scheduled_for_simulation",
        }
        mismatches = [
            {
                "field": field,
                "expected": expected,
                "actual": entry.get(field),
            }
            for field, expected in expected_fields.items()
            if entry.get(field) != expected
        ]
        for field in (
            "promoted_for_simulation",
            "step2_screenable",
            "step3_evaluable",
            "simulation_eligible",
            "l4_required",
        ):
            if entry.get(field) is not True:
                mismatches.append(
                    {"field": field, "expected": True, "actual": entry.get(field)}
                )
        for field in ("trusted_final_claim", "release_completion_eligible"):
            if entry.get(field) is not False:
                mismatches.append(
                    {"field": field, "expected": False, "actual": entry.get(field)}
                )
        for field in ("step3_search_blockers", "blocked_reasons"):
            if entry.get(field) not in ([], None):
                mismatches.append(
                    {"field": field, "expected": [], "actual": entry.get(field)}
                )
        if mismatches:
            entry_invariant_violations.append(
                {
                    "candidate_id": candidate_id,
                    "entry_index": index,
                    "mismatches": mismatches[:20],
                }
            )
    if entry_invariant_violations:
        blockers.append(
            {
                "id": "step3_queue_entry_identity_invariant_mismatch",
                "entry_count": len(entry_invariant_violations),
                "entries": entry_invariant_violations[:20],
            }
        )
    trusted_claim_entries = [
        str(entry.get("candidate_id")) for entry in entries if entry.get("trusted_final_claim") is True
    ]
    if step3_queue.get("trusted_final_claim") is True or trusted_claim_entries:
        blockers.append(
            {
                "id": "step3_queue_claim_upgrade_forbidden",
                "candidate_ids": trusted_claim_entries,
            }
        )
    noneligible = [
        str(entry.get("candidate_id"))
        for entry in entries
        if entry.get("simulation_eligible") is not True
        or entry.get("queue_state") != "scheduled_for_simulation"
    ]
    if noneligible:
        blockers.append({"id": "step3_queue_noneligible_entries", "candidate_ids": noneligible[:20]})
    payload = {
        "schema_version": VALIDATION_SCHEMA,
        "status": "passed" if not blockers else "blocked",
        "valid": not blockers,
        "release_id": RELEASE_ID,
        "release_subset_hash": expected_hash,
        "queue_hash": step3_queue.get("queue_hash"),
        "expected_candidate_count": len(expected_ids),
        "actual_candidate_count": len(actual_ids),
        "declared_candidate_count": len(declared_ids),
        "candidate_ids": actual_ids,
        "blockers": blockers,
        "claim_boundary": "Step2 queue validation proves candidate admission consistency only.",
    }
    payload["validation_hash"] = _stable_hash_without(payload, "validation_hash")
    return payload


def build_complete_dse_step2_binding_bundle(
    release_subset: Mapping[str, Any] | None = None,
    *,
    backend: str = "gem5_systemc",
    campaign_id: str | None = None,
    workload_run_id: str | None = None,
) -> Dict[str, Dict[str, Any]]:
    subset = dict(release_subset or build_release_subset_manifest())
    binding = build_complete_dse_step2_binding(
        subset,
        campaign_id=campaign_id,
        workload_run_id=workload_run_id,
    )
    queue = build_complete_dse_step3_simulation_queue(binding, backend=backend)
    ledger = build_complete_dse_trial_state_ledger(binding, queue)
    validation = validate_complete_dse_step2_queue(release_subset=subset, step3_queue=queue)
    search_effectiveness = build_complete_dse_search_effectiveness_report(
        subset,
        step3_queue=queue,
    )
    return {
        "complete_dse_step2_binding.json": binding,
        "step3_simulation_queue.json": queue,
        "trial_state_ledger.json": ledger,
        "complete_dse_search_effectiveness_report.json": search_effectiveness,
        "complete_dse_step2_binding_validation.json": validation,
    }


def write_complete_dse_step2_binding_artifacts(
    out_dir: Path,
    *,
    release_subset: Mapping[str, Any] | None = None,
    backend: str = "gem5_systemc",
    campaign_id: str | None = None,
    workload_run_id: str | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    subset = dict(release_subset or build_release_subset_manifest())
    bundle = build_complete_dse_step2_binding_bundle(
        subset,
        backend=backend,
        campaign_id=campaign_id,
        workload_run_id=workload_run_id,
    )
    _write_json(out_dir / "release_subset_manifest.json", subset)
    for name, payload in bundle.items():
        _write_json(out_dir / name, payload)
    status = {
        "schema_version": STATUS_SCHEMA,
        "status": bundle["complete_dse_step2_binding_validation.json"]["status"],
        "release_id": RELEASE_ID,
        "out_dir": str(out_dir),
        "artifacts": {
            "release_subset_manifest": str(out_dir / "release_subset_manifest.json"),
            **{
                name[:-5] if name.endswith(".json") else name: str(out_dir / name)
                for name in bundle
            },
        },
        "candidate_count": bundle["complete_dse_step2_binding.json"]["candidate_count"],
        "queue_entry_count": bundle["step3_simulation_queue.json"]["entry_count"],
        "valid": bundle["complete_dse_step2_binding_validation.json"]["valid"],
        "claim_boundary": "artifact emission only; no complete-DSE final claim",
    }
    status["status_hash"] = _stable_hash_without(status, "status_hash")
    _write_json(out_dir / "complete_dse_step2_binding_status.json", status)
    return status


__all__ = [
    "BINDING_SCHEMA",
    "LEDGER_SCHEMA",
    "QUEUE_MODE",
    "QUEUE_SCHEMA",
    "VALIDATION_SCHEMA",
    "build_complete_dse_step2_binding",
    "build_complete_dse_step2_binding_bundle",
    "build_complete_dse_step3_simulation_queue",
    "build_complete_dse_trial_state_ledger",
    "validate_complete_dse_step2_queue",
    "write_complete_dse_step2_binding_artifacts",
]
