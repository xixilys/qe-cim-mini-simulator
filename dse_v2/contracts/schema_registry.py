#!/usr/bin/env python3
"""Canonical JSON Schema registry for DSE control-plane artifacts.

Schemas are kept as Python data so the first milestone stays inside the
``dse_v2/contracts`` write scope and remains stdlib-only.  Future lanes may
materialize these definitions into repository-level JSON files once the shared
schema location is approved.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from dse_v2.contracts.entities import (
    ActivityStatus,
    CampaignStatus,
    CompletionStatus,
    FailureReason,
    TrialStatus,
    WorkloadRunStatus,
)
from dse_v2.contracts.validation import (
    validate_schema_semantics,
    validate_unique_schema_ids,
)

CONTRACT_VERSION = "dse.contracts.v1"


def _string(min_length: int = 1) -> dict[str, Any]:
    return {"type": "string", "minLength": min_length}


def _string_or_null() -> dict[str, Any]:
    return {"type": ["string", "null"]}


def _array_of_strings() -> dict[str, Any]:
    return {"type": "array", "items": _string(), "minItems": 0}


def _metadata() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": True}


def _schema(
    schema_id: str,
    required: list[str],
    properties: Mapping[str, Any],
    *,
    additional: bool = False,
) -> dict[str, Any]:
    base_properties = {
        "schema_version": {"type": "string", "const": CONTRACT_VERSION},
        **properties,
    }
    base_required = ["schema_version", *required]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        "additionalProperties": additional,
        "required": base_required,
        "properties": base_properties,
    }


COMMON_SCOPE_PROPERTIES: dict[str, Any] = {
    "campaign_id": _string(),
    "workload_run_id": _string_or_null(),
    "trial_id": _string_or_null(),
}

ARTIFACT_REF_PROPERTIES: dict[str, Any] = {
    "artifact_id": _string(),
    "canonical_name": _string(),
    "path": _string(),
    "schema_id": _string(),
    "artifact_schema_version": _string(),
    "content_hash": _string(),
    "producer_activity_id": _string(),
    **COMMON_SCOPE_PROPERTIES,
}

ENTITY_SCHEMAS: dict[str, dict[str, Any]] = {
    "dse.contract.campaign.v1": _schema(
        "dse.contract.campaign.v1",
        ["campaign_id", "objective", "status"],
        {
            "campaign_id": _string(),
            "objective": _string(),
            "status": {"type": "string", "enum": [item.value for item in CampaignStatus]},
            "budgets": _metadata(),
            "policies": _metadata(),
            "environment_ref": _string_or_null(),
            "git_revision": _string_or_null(),
            "global_stop_criteria": _array_of_strings(),
            "final_completion_status": {
                "type": ["string", "null"],
                "enum": [None, *[item.value for item in CompletionStatus]],
            },
        },
    ),
    "dse.contract.campaign_ledger.v1": _schema(
        "dse.contract.campaign_ledger.v1",
        [
            "campaign_id",
            "workload_run_id",
            "trial_id",
            "objective",
            "status",
            "budgets",
            "policies",
            "workload_run_ref",
            "step2_refs",
            "step3_refs",
            "broad_evidence_run",
        ],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "run_id": _string(),
            "workload_id": _string(),
            "workload_family": _string(),
            "profile_id": _string(),
            "importer_id": _string(),
            "objective": _string(),
            "status": {"type": "string", "enum": [item.value for item in CampaignStatus]},
            "budgets": _metadata(),
            "policies": _metadata(),
            "broad_evidence_run": {"type": "boolean"},
            "trusted_final_claim": {"type": "boolean"},
            "release_completion_eligible": {"type": "boolean"},
            "claim_boundary": _string(),
            "workload_run_ref": _metadata(),
            "step2_refs": _metadata(),
            "step3_refs": _metadata(),
            "step4_refs": _metadata(),
            "step5_refs": _metadata(),
            "selected_trial_refs": _metadata(),
            "resume_next_actions": _array_of_strings(),
        },
        additional=True,
    ),
    "dse.contract.workload_run.v1": _schema(
        "dse.contract.workload_run.v1",
        ["campaign_id", "workload_run_id", "workload_family", "status"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "workload_family": _string(),
            "status": {"type": "string", "enum": [item.value for item in WorkloadRunStatus]},
            "artifact_ids": _array_of_strings(),
            "blockers": _array_of_strings(),
        },
    ),
    "dse.contract.trial.v1": _schema(
        "dse.contract.trial.v1",
        ["campaign_id", "workload_run_id", "trial_id", "status"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "status": {"type": "string", "enum": [item.value for item in TrialStatus]},
            "parent_candidate_refs": _array_of_strings(),
            "generation_reasons": _array_of_strings(),
            "evidence_artifact_ids": _array_of_strings(),
            "feedback_artifact_ids": _array_of_strings(),
            "verdict_artifact_ids": _array_of_strings(),
            "terminal_reason": _string_or_null(),
        },
    ),
    "dse.contract.activity.v1": _schema(
        "dse.contract.activity.v1",
        ["activity_id", "campaign_id", "step", "status"],
        {
            "activity_id": _string(),
            "campaign_id": _string(),
            "step": _string(),
            "status": {"type": "string", "enum": [item.value for item in ActivityStatus]},
            "command": _array_of_strings(),
            "environment_ref": _string_or_null(),
            "input_artifact_ids": _array_of_strings(),
            "output_artifact_ids": _array_of_strings(),
            "failure_policy_id": _string_or_null(),
        },
    ),
    "dse.contract.artifact_ref.v1": _schema(
        "dse.contract.artifact_ref.v1",
        [
            "artifact_id",
            "canonical_name",
            "path",
            "schema_id",
            "artifact_schema_version",
            "content_hash",
            "producer_activity_id",
            "campaign_id",
        ],
        ARTIFACT_REF_PROPERTIES,
    ),
    "dse.contract.failure_policy.v1": _schema(
        "dse.contract.failure_policy.v1",
        ["policy_id", "max_retries", "retryable_reasons", "no_retry_reasons"],
        {
            "policy_id": _string(),
            "timeout_seconds": {"type": ["integer", "null"], "minimum": 1},
            "max_retries": {"type": "integer", "minimum": 0},
            "retryable_reasons": {
                "type": "array",
                "items": {"type": "string", "enum": [item.value for item in FailureReason]},
            },
            "no_retry_reasons": {
                "type": "array",
                "items": {"type": "string", "enum": [item.value for item in FailureReason]},
            },
            "recovery_actions": _metadata(),
        },
    ),
}

ARTIFACT_SCHEMAS: dict[str, dict[str, Any]] = {
    "dse.contract.workload_package.v1": _schema(
        "dse.contract.workload_package.v1",
        ["campaign_id", "workload_run_id", "workload_family", "source_refs"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": {"type": "null"},
            "workload_family": _string(),
            "source_refs": _array_of_strings(),
            "claim_boundary": _string(),
        },
    ),
    "dse.contract.compute_graph.v1": _schema(
        "dse.contract.compute_graph.v1",
        ["campaign_id", "workload_run_id", "nodes", "edges"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": {"type": "null"},
            "nodes": {"type": "array", "items": _metadata()},
            "edges": {"type": "array", "items": _metadata()},
        },
    ),
    "dse.contract.architecture_catalog.v1": _schema(
        "dse.contract.architecture_catalog.v1",
        ["campaign_id", "workload_run_id", "trial_id", "families"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "families": {"type": "array", "items": _metadata(), "minItems": 1},
            "generation_provenance": _metadata(),
        },
    ),
    "dse.contract.design_point.v1": _schema(
        "dse.contract.design_point.v1",
        ["campaign_id", "workload_run_id", "trial_id", "parameters"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "parameters": _metadata(),
            "generation_reasons": _array_of_strings(),
        },
    ),
    "dse.contract.architecture_search_space.v1": _schema(
        "dse.contract.architecture_search_space.v1",
        ["campaign_id", "workload_run_id", "trial_id", "parameters", "generation_provenance", "search_space_hash"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "workload_id": _string(),
            "workload_family": _string(),
            "backend": _string(),
            "policy_scope": _string(),
            "objective_directions": _metadata(),
            "parameters": _metadata(),
            "constraints": _metadata(),
            "generation_provenance": _metadata(),
            "freeze_gate_verdict": _metadata(),
            "search_space_hash": _string(),
            "trusted_final_claim": {"type": "boolean", "const": False},
        },
    ),
    "dse.contract.search_checkpoint_summary.v1": _schema(
        "dse.contract.search_checkpoint_summary.v1",
        ["campaign_id", "workload_run_id", "trial_id", "policy_name", "candidate_count", "top_k_candidate_queue_artifact"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "workload_id": _string(),
            "workload_family": _string(),
            "policy_scope": _string(),
            "policy_name": _string(),
            "search_space_artifact": _string(),
            "search_space_hash": _string(),
            "candidate_identity_policy": _string(),
            "candidate_count": {"type": "integer", "minimum": 0},
            "proposed_count": {"type": "integer", "minimum": 0},
            "observed_count": {"type": "integer", "minimum": 0},
            "top_k_candidate_queue_artifact": _string(),
            "step3_simulation_queue_artifact": _string(),
            "top_k_queue_provenance_only": {"type": "boolean", "const": True},
            "release_completion_eligible": {"type": "boolean", "const": False},
            "trusted_final_claim": {"type": "boolean", "const": False},
        },
    ),
    "dse.contract.top_k_candidate_queue.v1": _schema(
        "dse.contract.top_k_candidate_queue.v1",
        ["campaign_id", "workload_run_id", "trial_id", "queue_mode", "entry_count", "step3_simulation_queue_artifact"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "workload_id": _string(),
            "workload_family": _string(),
            "policy_scope": _string(),
            "policy_name": _string(),
            "queue_mode": {"type": "string", "const": "top-k-provenance-only"},
            "entry_count": {"type": "integer", "minimum": 0},
            "candidate_source_artifact": _string(),
            "mapping_candidates_artifact": _string(),
            "step3_simulation_queue_artifact": _string(),
            "provenance_only": {"type": "boolean", "const": True},
            "execution_order_suggestion_only": {"type": "boolean", "const": True},
            "top_k_or_representative_completion_allowed": {"type": "boolean", "const": False},
            "release_completion_eligible": {"type": "boolean", "const": False},
            "trusted_final_claim": {"type": "boolean", "const": False},
            "entries": {"type": "array", "items": _metadata(), "minItems": 0},
        },
    ),
    "dse.contract.architecture_candidate_generation_report.v1": _schema(
        "dse.contract.architecture_candidate_generation_report.v1",
        ["campaign_id", "workload_run_id", "trial_id", "search_space_artifact", "search_space_hash"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "workload_id": _string(),
            "workload_family": _string(),
            "search_space_artifact": _string(),
            "search_space_hash": _string(),
            "policy_scope": _string(),
            "architecture_candidate_count": {"type": "integer", "minimum": 0},
            "mapping_candidate_count": {"type": "integer", "minimum": 0},
            "generated_candidate_ids": _array_of_strings(),
            "mapping_candidate_ids": _array_of_strings(),
            "generation_provenance": _metadata(),
            "trusted_final_claim": {"type": "boolean", "const": False},
        },
    ),
    "dse.contract.architecture_screening_report.v1": _schema(
        "dse.contract.architecture_screening_report.v1",
        ["campaign_id", "workload_run_id", "trial_id", "screened_candidate_count", "promotion_decision_artifact"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "workload_id": _string(),
            "workload_family": _string(),
            "screened_candidate_count": {"type": "integer", "minimum": 0},
            "promoted_candidate_count": {"type": "integer", "minimum": 0},
            "promotion_decision_artifact": _string(),
            "screening_results_artifact": _string(),
            "step3_simulation_queue_artifact": _string(),
            "step3_queue_entry_count": {"type": "integer", "minimum": 0},
            "claim_boundary": _string(),
            "trusted_final_claim": {"type": "boolean", "const": False},
        },
    ),
    "dse.contract.mapping_candidate_record.v1": _schema(
        "dse.contract.mapping_candidate_record.v1",
        ["campaign_id", "workload_run_id", "trial_id", "candidate_id", "mapping", "parameters", "provenance"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "candidate_id": _string(),
            "workload_id": _string(),
            "workload_family": _string(),
            "mapping": _metadata(),
            "parameters": _metadata(),
            "provenance": _metadata(),
            "generation_reason": _string(),
            "score": {"type": ["number", "integer", "null"]},
            "step2_screenable": {"type": "boolean"},
            "step3_evaluable": {"type": "boolean"},
            "simulation_eligible": {"type": "boolean"},
            "simulation_blockers": _array_of_strings(),
            "promotion_reasons": _array_of_strings(),
            "blocker_reasons": _array_of_strings(),
            "trusted_final_claim": {"type": "boolean", "const": False},
        },
    ),
    "dse.contract.screening_result_record.v1": _schema(
        "dse.contract.screening_result_record.v1",
        ["campaign_id", "workload_run_id", "trial_id", "candidate_id", "screening_stage", "passed"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "candidate_id": _string(),
            "workload_id": _string(),
            "workload_family": _string(),
            "architecture_id": _string(),
            "screening_stage": _string(),
            "passed": {"type": "boolean"},
            "step2_screenable": {"type": "boolean"},
            "step3_evaluable": {"type": "boolean"},
            "simulation_eligible": {"type": "boolean"},
            "simulation_blockers": _array_of_strings(),
            "blocker_reasons": {"type": "array", "items": _metadata()},
            "evidence_refs": _array_of_strings(),
            "trusted_final_claim": {"type": "boolean", "const": False},
        },
    ),
    "dse.contract.promotion_decision_record.v1": _schema(
        "dse.contract.promotion_decision_record.v1",
        ["campaign_id", "workload_run_id", "trial_id", "candidate_id", "decision", "reasons"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "candidate_id": _string(),
            "workload_id": _string(),
            "workload_family": _string(),
            "mapping_id": _string(),
            "architecture_id": _string(),
            "decision": {"type": "string", "enum": ["promote", "reject", "block"]},
            "promoted_for_simulation": {"type": "boolean"},
            "reasons": _array_of_strings(),
            "required_evidence": _array_of_strings(),
            "queue_artifact": _string(),
            "trusted_final_claim": {"type": "boolean", "const": False},
        },
    ),
    "dse.contract.mapping_candidate.v1": _schema(
        "dse.contract.mapping_candidate.v1",
        ["campaign_id", "workload_run_id", "trial_id", "mapping"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "mapping": _metadata(),
            "simulation_blockers": _array_of_strings(),
        },
    ),
    "dse.contract.promotion_decision.v1": _schema(
        "dse.contract.promotion_decision.v1",
        ["campaign_id", "workload_run_id", "trial_id", "decision", "reasons"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "decision": {"type": "string", "enum": ["promote", "reject", "block"]},
            "reasons": _array_of_strings(),
        },
    ),
    "dse.contract.simulation_request.v1": _schema(
        "dse.contract.simulation_request.v1",
        ["campaign_id", "workload_run_id", "trial_id", "backend", "inputs"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "backend": _string(),
            "inputs": _array_of_strings(),
        },
    ),
    "dse.contract.simulation_result.v1": _schema(
        "dse.contract.simulation_result.v1",
        ["campaign_id", "workload_run_id", "trial_id", "backend", "raw_observations"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "backend": _string(),
            "raw_observations": _metadata(),
            "measurement_units": _metadata(),
        },
    ),
    "dse.contract.step_status.v1": _schema(
        "dse.contract.step_status.v1",
        ["campaign_id", "workload_run_id", "step", "status"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string_or_null(),
            "step": _string(),
            "status": _string(),
            "blockers": _array_of_strings(),
        },
    ),
    "dse.contract.evidence_manifest.v1": _schema(
        "dse.contract.evidence_manifest.v1",
        ["campaign_id", "workload_run_id", "trial_id", "artifact_refs"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "artifact_refs": {"type": "array", "items": _metadata(), "minItems": 1},
        },
    ),
    "dse.contract.provenance.v1": _schema(
        "dse.contract.provenance.v1",
        ["campaign_id", "workload_run_id", "trial_id", "activities"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "activities": {"type": "array", "items": _metadata()},
        },
    ),
    "dse.contract.verdict.v1": _schema(
        "dse.contract.verdict.v1",
        ["campaign_id", "workload_run_id", "trial_id", "verdict", "evidence_refs"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "verdict": {"type": "string", "enum": ["pass", "fail", "blocked"]},
            "evidence_refs": _array_of_strings(),
            "claim_boundary": _string(),
        },
    ),
    "dse.contract.claim_validation.v1": _schema(
        "dse.contract.claim_validation.v1",
        ["campaign_id", "workload_run_id", "trial_id", "completion_status", "required_gates"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "completion_status": {
                "type": "string",
                "enum": [item.value for item in CompletionStatus],
            },
            "required_gates": {"type": "array", "items": _metadata(), "minItems": 1},
        },
    ),
    "dse.contract.calibration_record.v1": _schema(
        "dse.contract.calibration_record.v1",
        ["campaign_id", "workload_run_id", "trial_id", "levels", "confidence", "source_artifact_hashes"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "levels": _array_of_strings(),
            "valid_region": _metadata(),
            "error_metrics": _metadata(),
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "source_artifact_hashes": _metadata(),
        },
    ),
    "dse.contract.feedback_update.v1": _schema(
        "dse.contract.feedback_update.v1",
        ["campaign_id", "workload_run_id", "trial_id", "updates", "source_artifact_hashes"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "updates": {"type": "array", "items": _metadata()},
            "source_artifact_hashes": _metadata(),
        },
    ),
    "dse.contract.l4_interface_metrics.v1": _schema(
        "dse.contract.l4_interface_metrics.v1",
        ["campaign_id", "workload_run_id", "trial_id", "metrics", "raw_observation_refs"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "metrics": _metadata(),
            "raw_observation_refs": _array_of_strings(),
        },
    ),
    "dse.contract.final_report.v1": _schema(
        "dse.contract.final_report.v1",
        ["campaign_id", "workload_run_id", "trial_id", "claim_validation_ref", "summary"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": _string(),
            "claim_validation_ref": _string(),
            "summary": _string(),
        },
    ),
    "dse.contract.dft_profile.v1": _schema(
        "dse.contract.dft_profile.v1",
        ["campaign_id", "workload_run_id", "profile_id", "claim_boundary"],
        {
            "campaign_id": _string(),
            "workload_run_id": _string(),
            "trial_id": {"type": "null"},
            "profile_id": _string(),
            "claim_boundary": _string(),
            "profile_metadata": _metadata(),
        },
    ),
}

SCHEMA_REGISTRY: dict[str, dict[str, Any]] = {
    **ENTITY_SCHEMAS,
    **ARTIFACT_SCHEMAS,
}


def get_schema(schema_id: str) -> dict[str, Any]:
    return deepcopy(SCHEMA_REGISTRY[schema_id])


def validate_schema_registry(registry: Mapping[str, Mapping[str, Any]] | None = None) -> None:
    active_registry = SCHEMA_REGISTRY if registry is None else registry
    validate_unique_schema_ids(list(active_registry.values()))
    for key, schema in active_registry.items():
        if schema.get("$id") != key:
            raise ValueError(f"schema registry key {key!r} does not match $id")
        validate_schema_semantics(schema)
