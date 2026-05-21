#!/usr/bin/env python3
"""Canonical artifact catalog and ownership validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from dse_v2.contracts.schema_registry import CONTRACT_VERSION, SCHEMA_REGISTRY
from dse_v2.contracts.validation import ContractValidationError, validate_instance


@dataclass(frozen=True)
class ArtifactDefinition:
    canonical_name: str
    producer_stage: str
    schema_id: str
    consumers: tuple[str, ...]
    artifact_class: str = "canonical"
    required: bool = True
    legacy_names: tuple[str, ...] = ()
    migration_note: str = "canonical contract; legacy names must not be silently dual-written"
    example: Mapping[str, Any] = field(default_factory=dict)


_SCOPE = {
    "schema_version": CONTRACT_VERSION,
    "campaign_id": "campaign-001",
    "workload_run_id": "workload-run-001",
    "trial_id": "trial-001",
}
_STEP1_SCOPE = {
    "schema_version": CONTRACT_VERSION,
    "campaign_id": "campaign-001",
    "workload_run_id": "workload-run-001",
    "trial_id": None,
}


def _definition(
    canonical_name: str,
    producer_stage: str,
    schema_id: str,
    consumers: Sequence[str],
    example: Mapping[str, Any],
    *,
    artifact_class: str = "canonical",
    legacy_names: Sequence[str] = (),
    required: bool = True,
) -> ArtifactDefinition:
    return ArtifactDefinition(
        canonical_name=canonical_name,
        producer_stage=producer_stage,
        schema_id=schema_id,
        consumers=tuple(consumers),
        artifact_class=artifact_class,
        legacy_names=tuple(legacy_names),
        required=required,
        example=dict(example),
    )


ARTIFACT_CATALOG: tuple[ArtifactDefinition, ...] = (
    _definition(
        "campaign.json",
        "control_plane",
        "dse.contract.campaign.v1",
        ("ledger", "step5"),
        {
            "schema_version": CONTRACT_VERSION,
            "campaign_id": "campaign-001",
            "objective": "research-grade DSE restructure proof run",
            "status": "active",
            "budgets": {},
            "policies": {},
            "environment_ref": None,
            "git_revision": "abc123",
            "global_stop_criteria": ["all hard gates pass"],
            "final_completion_status": None,
        },
    ),
    _definition(
        "campaign_ledger.json",
        "control_plane",
        "dse.contract.campaign_ledger.v1",
        ("ledger", "step1", "step2", "step3", "step4", "step5"),
        {
            "schema_version": CONTRACT_VERSION,
            "campaign_id": "campaign-001",
            "workload_run_id": "workload-run-001",
            "trial_id": "trial-001",
            "run_id": "pilot-run-001",
            "workload_id": "generic-workload-001",
            "workload_family": "generic_workload",
            "profile_id": "generic_profile",
            "importer_id": "generic_importer",
            "objective": "bounded DSE pilot with auditable Step1/Step2/Step3 refs",
            "status": "active",
            "budgets": {"broad_evidence_run": False, "step3_queue_entry_budget": 1},
            "policies": {"step3_admission_queue": "step2/step3_simulation_queue.json"},
            "broad_evidence_run": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "claim_boundary": "pilot provenance only; not deliverable completion",
            "workload_run_ref": {"workload_package": "step1/workload_package.json"},
            "step2_refs": {"trial_state_ledger": "step2/trial_state_ledger.json"},
            "step3_refs": {"simulation_result": "simulation_result.json"},
            "step4_refs": {"verdict": "verdict.json"},
            "step5_refs": {"final_report": "final_report.json"},
            "selected_trial_refs": {"queue_mode": "selected-entry-only"},
            "resume_next_actions": ["resume from step2/search_checkpoint.json"],
        },
    ),
    _definition(
        "campaign_evaluation_plan.json",
        "control_plane",
        "dse.contract.campaign_evaluation_plan.v1",
        ("ledger", "step3", "step4"),
        {
            "schema_version": CONTRACT_VERSION,
            "campaign_id": "campaign-001",
            "workload_run_id": "workload-run-001",
            "trial_id": "trial-001",
            "plan_id": "evaluation-plan-001",
            "run_id": "pilot-run-001",
            "workload_id": "generic-workload-001",
            "workload_family": "generic_workload",
            "status": "active",
            "plan_scope": "bounded_selected_entry_pilot",
            "budget_policy": {
                "step3_queue_entry_budget": 1,
                "evidence_fanout_policy": "selected_entry_only_for_pilot",
            },
            "step3_simulation_queue_ref": "step2/step3_simulation_queue.json",
            "top_k_candidate_queue_ref": "step2/top_k_candidate_queue.json",
            "search_checkpoint_ref": "step2/search_checkpoint.json",
            "planned_entry_count": 1,
            "planned_entries": [
                {
                    "queue_entry_id": "step2-selected::architecture::mapping",
                    "mapping_candidate_id": "mapping-001",
                    "execution_allowed": True,
                    "admission_source": "step2/step3_simulation_queue.json",
                }
            ],
            "deferred_entry_count": 0,
            "deferred_entries": [],
            "selected_entry_only": True,
            "broad_evidence_run": False,
            "release_completion_eligible": False,
            "trusted_final_claim": False,
            "claim_boundary": "budgeted execution plan only; final trust requires evidence adjudication",
            "resume_next_actions": ["run planned entries through Step3 before widening budget"],
        },
    ),
    _definition(
        "workload_run.json",
        "step1",
        "dse.contract.workload_run.v1",
        ("step2", "ledger"),
        {
            "schema_version": CONTRACT_VERSION,
            "campaign_id": "campaign-001",
            "workload_run_id": "workload-run-001",
            "workload_family": "generic_workload",
            "status": "lowered",
            "artifact_ids": ["artifact-workload-package"],
            "blockers": [],
        },
    ),
    _definition(
        "trial.json",
        "step2",
        "dse.contract.trial.v1",
        ("step3", "step4", "step5", "ledger"),
        {
            **_SCOPE,
            "status": "promoted",
            "parent_candidate_refs": [],
            "generation_reasons": ["screened feasible"],
            "evidence_artifact_ids": [],
            "feedback_artifact_ids": [],
            "verdict_artifact_ids": [],
            "terminal_reason": None,
        },
    ),
    _definition(
        "activity.json",
        "control_plane",
        "dse.contract.activity.v1",
        ("ledger", "provenance"),
        {
            "schema_version": CONTRACT_VERSION,
            "activity_id": "activity-step3-001",
            "campaign_id": "campaign-001",
            "step": "step3",
            "status": "succeeded",
            "command": ["python3", "runner.py"],
            "environment_ref": "env-001",
            "input_artifact_ids": ["artifact-simulation-request"],
            "output_artifact_ids": ["artifact-simulation-result"],
            "failure_policy_id": "policy-default",
        },
    ),
    _definition(
        "artifact_ref.json",
        "control_plane",
        "dse.contract.artifact_ref.v1",
        ("ledger", "artifact_manifest"),
        {
            "schema_version": CONTRACT_VERSION,
            "artifact_id": "artifact-simulation-result",
            "canonical_name": "simulation_result.json",
            "path": "runs/campaign-001/step3/simulation_result.json",
            "schema_id": "dse.contract.simulation_result.v1",
            "artifact_schema_version": CONTRACT_VERSION,
            "content_hash": "sha256:0123456789abcdef",
            "producer_activity_id": "activity-step3-001",
            "campaign_id": "campaign-001",
            "workload_run_id": "workload-run-001",
            "trial_id": "trial-001",
        },
    ),
    _definition(
        "failure_policy.json",
        "control_plane",
        "dse.contract.failure_policy.v1",
        ("ledger", "activities"),
        {
            "schema_version": CONTRACT_VERSION,
            "policy_id": "policy-default",
            "timeout_seconds": 3600,
            "max_retries": 1,
            "retryable_reasons": ["timeout", "crash"],
            "no_retry_reasons": ["schema_invalid", "missing_binding"],
            "recovery_actions": {"tool_unavailable": "record blocker and retry alternate path"},
        },
    ),
    _definition(
        "workload_package.json",
        "step1",
        "dse.contract.workload_package.v1",
        ("step2", "step4"),
        {
            **_STEP1_SCOPE,
            "workload_family": "generic_workload",
            "source_refs": ["input.json"],
            "claim_boundary": "workload facts only; no performance claim",
        },
    ),
    _definition(
        "compute_graph.json",
        "step1",
        "dse.contract.compute_graph.v1",
        ("step2", "step3"),
        {**_STEP1_SCOPE, "nodes": [], "edges": []},
    ),
    _definition(
        "architecture_catalog.json",
        "step2",
        "dse.contract.architecture_catalog.v1",
        ("step2", "step4"),
        {**_SCOPE, "families": [{"family": "generic_accel"}], "generation_provenance": {}},
    ),
    _definition(
        "architecture_instance.json",
        "step2",
        "dse.contract.design_point.v1",
        ("step3", "step4"),
        {**_SCOPE, "parameters": {"pe_count": 1}, "generation_reasons": ["seed"]},
    ),
    _definition(
        "design_point.json",
        "step2",
        "dse.contract.design_point.v1",
        ("step3", "step4"),
        {**_SCOPE, "parameters": {"memory_kib": 64}, "generation_reasons": ["legal"]},
    ),
    _definition(
        "architecture_search_space.json",
        "step2",
        "dse.contract.architecture_search_space.v1",
        ("step2", "step4"),
        {
            **_SCOPE,
            "workload_id": "workload-001",
            "workload_family": "generic_workload",
            "backend": "systemc",
            "policy_scope": "generic_catalog_only",
            "objective_directions": {"latency_ms": "minimize"},
            "parameters": {"architecture_ids": ["balanced-generic-systemc-v0"]},
            "constraints": {"trusted_final_claim": False},
            "generation_provenance": {"source": "architecture_catalog.json"},
            "freeze_gate_verdict": {"status": "candidate_generation_only"},
            "search_space_hash": "sha256:0123456789abcdef",
            "trusted_final_claim": False,
        },
    ),
    _definition(
        "search_checkpoint.json",
        "step2",
        "dse.contract.search_checkpoint_summary.v1",
        ("step3", "step4", "ledger"),
        {
            **_SCOPE,
            "workload_id": "workload-001",
            "workload_family": "generic_workload",
            "policy_scope": "generic_catalog_only",
            "policy_name": "workflow_seeded_beam_local_search_v1",
            "search_space_artifact": "architecture_search_space.json",
            "search_space_hash": "sha256:0123456789abcdef",
            "candidate_identity_policy": "stable_parameter_hash_sidecar",
            "candidate_count": 2,
            "proposed_count": 2,
            "observed_count": 0,
            "top_k_candidate_queue_artifact": "top_k_candidate_queue.json",
            "step3_simulation_queue_artifact": "step3_simulation_queue.json",
            "top_k_queue_provenance_only": True,
            "release_completion_eligible": False,
            "trusted_final_claim": False,
        },
    ),
    _definition(
        "top_k_candidate_queue.json",
        "step2",
        "dse.contract.top_k_candidate_queue.v1",
        ("step3", "step4", "ledger"),
        {
            **_SCOPE,
            "workload_id": "workload-001",
            "workload_family": "generic_workload",
            "policy_scope": "generic_catalog_only",
            "policy_name": "workflow_seeded_beam_local_search_v1",
            "queue_mode": "top-k-provenance-only",
            "entry_count": 1,
            "candidate_source_artifact": "mapping_candidate_records.json",
            "mapping_candidates_artifact": "mapping_candidates.jsonl",
            "step3_simulation_queue_artifact": "step3_simulation_queue.json",
            "provenance_only": True,
            "execution_order_suggestion_only": True,
            "top_k_or_representative_completion_allowed": False,
            "release_completion_eligible": False,
            "trusted_final_claim": False,
            "entries": [
                {
                    "top_k_rank": 1,
                    "candidate_id": "mapping-001",
                    "parameter_hash": "sha256:0123456789abcdef",
                    "execution_suggestion_only": True,
                    "not_a_step3_queue_entry": True,
                    "trusted_final_claim": False,
                }
            ],
        },
    ),
    _definition(
        "architecture_candidate_generation_report.json",
        "step2",
        "dse.contract.architecture_candidate_generation_report.v1",
        ("step4",),
        {
            **_SCOPE,
            "workload_id": "workload-001",
            "workload_family": "generic_workload",
            "search_space_artifact": "architecture_search_space.json",
            "search_space_hash": "sha256:0123456789abcdef",
            "policy_scope": "generic_catalog_only",
            "architecture_candidate_count": 1,
            "mapping_candidate_count": 1,
            "generated_candidate_ids": ["architecture::balanced-generic-systemc-v0"],
            "mapping_candidate_ids": ["mapping-001"],
            "generation_provenance": {"mapping_source": "mapping_candidate_records.json"},
            "trusted_final_claim": False,
        },
    ),
    _definition(
        "architecture_screening_report.json",
        "step2",
        "dse.contract.architecture_screening_report.v1",
        ("step3", "step4"),
        {
            **_SCOPE,
            "workload_id": "workload-001",
            "workload_family": "generic_workload",
            "screened_candidate_count": 1,
            "promoted_candidate_count": 1,
            "promotion_decision_artifact": "promotion_decisions.jsonl",
            "screening_results_artifact": "screening_results.jsonl",
            "step3_simulation_queue_artifact": "step3_simulation_queue.json",
            "step3_queue_entry_count": 1,
            "claim_boundary": "Step2 screening only; final trust requires Step3/Step4 evidence.",
            "trusted_final_claim": False,
        },
    ),
    _definition(
        "mapping_candidates.jsonl",
        "step2",
        "dse.contract.mapping_candidate_record.v1",
        ("step3", "step4"),
        {
            **_SCOPE,
            "workload_id": "workload-001",
            "workload_family": "generic_workload",
            "candidate_id": "mapping-001",
            "mapping": {"kernel": "accelerator"},
            "parameters": {"backend": "systemc"},
            "provenance": {"source_artifact": "mapping_candidate_records.json"},
            "generation_reason": "mapping_search_candidate",
            "score": 1.0,
            "step2_screenable": True,
            "step3_evaluable": True,
            "simulation_eligible": True,
            "simulation_blockers": [],
            "promotion_reasons": ["ready_for_step3_simulation"],
            "blocker_reasons": [],
            "trusted_final_claim": False,
        },
    ),
    _definition(
        "screening_results.jsonl",
        "step2",
        "dse.contract.screening_result_record.v1",
        ("step4",),
        {
            **_SCOPE,
            "workload_id": "workload-001",
            "workload_family": "generic_workload",
            "candidate_id": "architecture::balanced-generic-systemc-v0",
            "architecture_id": "balanced-generic-systemc-v0",
            "screening_stage": "architecture_screening",
            "passed": True,
            "step2_screenable": True,
            "step3_evaluable": True,
            "simulation_eligible": True,
            "simulation_blockers": [],
            "blocker_reasons": [],
            "evidence_refs": ["architecture_candidate_set.json"],
            "trusted_final_claim": False,
        },
    ),
    _definition(
        "promotion_decisions.jsonl",
        "step2",
        "dse.contract.promotion_decision_record.v1",
        ("step3", "step4"),
        {
            **_SCOPE,
            "workload_id": "workload-001",
            "workload_family": "generic_workload",
            "candidate_id": "mapping-001",
            "mapping_id": "mapping-001",
            "architecture_id": "balanced-generic-systemc-v0",
            "decision": "promote",
            "promoted_for_simulation": True,
            "reasons": ["ready_for_step3_simulation"],
            "required_evidence": ["simulation_request.json", "simulation_result.json"],
            "queue_artifact": "step3_simulation_queue.json",
            "trusted_final_claim": False,
        },
    ),
    _definition(
        "mapping_candidate.json",
        "step2",
        "dse.contract.mapping_candidate.v1",
        ("step3", "step4"),
        {**_SCOPE, "mapping": {"kernel": "accelerator"}, "simulation_blockers": []},
    ),
    _definition(
        "promotion_decision.json",
        "step2",
        "dse.contract.promotion_decision.v1",
        ("step3", "step4"),
        {**_SCOPE, "decision": "promote", "reasons": ["passes screening"]},
    ),
    _definition(
        "simulation_request.json",
        "step3",
        "dse.contract.simulation_request.v1",
        ("backend", "step4"),
        {**_SCOPE, "backend": "systemc", "inputs": ["design_point.json"]},
    ),
    _definition(
        "simulation_result.json",
        "step3",
        "dse.contract.simulation_result.v1",
        ("step4", "step5"),
        {
            **_SCOPE,
            "backend": "systemc",
            "raw_observations": {"cycles": 10},
            "measurement_units": {"cycles": "cycle"},
        },
    ),
    _definition(
        "step3_status.json",
        "step3",
        "dse.contract.step_status.v1",
        ("step4", "ledger"),
        {**_SCOPE, "step": "step3", "status": "simulated", "blockers": []},
    ),
    _definition(
        "backend_log.txt",
        "step3",
        "dse.contract.artifact_ref.v1",
        ("step4",),
        {
            "schema_version": CONTRACT_VERSION,
            "artifact_id": "artifact-backend-log",
            "canonical_name": "backend_log.txt",
            "path": "runs/campaign-001/step3/backend_log.txt",
            "schema_id": "dse.contract.artifact_ref.v1",
            "artifact_schema_version": CONTRACT_VERSION,
            "content_hash": "sha256:abcdef0123456789",
            "producer_activity_id": "activity-step3-001",
            "campaign_id": "campaign-001",
            "workload_run_id": "workload-run-001",
            "trial_id": "trial-001",
        },
        artifact_class="raw",
        required=False,
    ),
    _definition(
        "raw_trace.jsonl",
        "step3",
        "dse.contract.artifact_ref.v1",
        ("step4",),
        {
            "schema_version": CONTRACT_VERSION,
            "artifact_id": "artifact-raw-trace",
            "canonical_name": "raw_trace.jsonl",
            "path": "runs/campaign-001/step3/raw_trace.jsonl",
            "schema_id": "dse.contract.artifact_ref.v1",
            "artifact_schema_version": CONTRACT_VERSION,
            "content_hash": "sha256:feedface01234567",
            "producer_activity_id": "activity-step3-001",
            "campaign_id": "campaign-001",
            "workload_run_id": "workload-run-001",
            "trial_id": "trial-001",
        },
        artifact_class="raw",
        required=False,
    ),
    _definition(
        "manifest.json",
        "step4",
        "dse.contract.evidence_manifest.v1",
        ("step5", "ledger"),
        {**_SCOPE, "artifact_refs": [{"artifact_id": "artifact-simulation-result"}]},
    ),
    _definition(
        "artifact_manifest.json",
        "step4",
        "dse.contract.evidence_manifest.v1",
        ("step5", "ledger"),
        {**_SCOPE, "artifact_refs": [{"artifact_id": "artifact-simulation-result"}]},
    ),
    _definition(
        "provenance.json",
        "step4",
        "dse.contract.provenance.v1",
        ("step5", "ledger"),
        {**_SCOPE, "activities": [{"activity_id": "activity-step3-001"}]},
    ),
    _definition(
        "verdict.json",
        "step4",
        "dse.contract.verdict.v1",
        ("step5", "ledger"),
        {
            **_SCOPE,
            "verdict": "pass",
            "evidence_refs": ["artifact-simulation-result"],
            "claim_boundary": "adjudicated evidence only",
        },
    ),
    _definition(
        "evidence_requirements.json",
        "step4",
        "dse.contract.evidence_manifest.v1",
        ("step5",),
        {**_SCOPE, "artifact_refs": [{"required_gate": "systemc_ctest"}]},
    ),
    _definition(
        "claim_validation.json",
        "step4",
        "dse.contract.claim_validation.v1",
        ("step5", "ledger"),
        {
            **_SCOPE,
            "completion_status": "partial_blocked_not_complete",
            "required_gates": [{"gate": "systemc", "status": "pending"}],
        },
        legacy_names=("step3_claim_validation.json",),
    ),
    _definition(
        "feedback_update.json",
        "step4",
        "dse.contract.feedback_update.v1",
        ("step2", "step5"),
        {
            **_SCOPE,
            "updates": [{"target": "promotion_policy"}],
            "source_artifact_hashes": {"simulation_result.json": "sha256:0123456789abcdef"},
        },
    ),
    _definition(
        "calibration_record.json",
        "step4",
        "dse.contract.calibration_record.v1",
        ("step2", "step5"),
        {
            **_SCOPE,
            "levels": ["l3", "l4"],
            "valid_region": {},
            "error_metrics": {},
            "confidence": 0.5,
            "source_artifact_hashes": {"simulation_result.json": "sha256:0123456789abcdef"},
        },
    ),
    _definition(
        "codesign_verdict.json",
        "step4",
        "dse.contract.verdict.v1",
        ("step5", "ledger"),
        {
            **_SCOPE,
            "verdict": "pass",
            "evidence_refs": ["artifact-calibration-record"],
            "claim_boundary": "codesign decision evidence only",
        },
    ),
    _definition(
        "l4_interface_metrics.json",
        "step4",
        "dse.contract.l4_interface_metrics.v1",
        ("step5", "promotion"),
        {
            **_SCOPE,
            "metrics": {"descriptor_decodes": 1, "completion_latency_cycles": 10},
            "raw_observation_refs": ["raw_trace.jsonl"],
        },
    ),
    _definition(
        "final_report.json",
        "step5",
        "dse.contract.final_report.v1",
        ("user", "archive"),
        {
            **_SCOPE,
            "claim_validation_ref": "claim_validation.json",
            "summary": "report consumes Step4 adjudicated evidence",
        },
        legacy_names=("step3_final_report.json",),
    ),
    _definition(
        "final_report.md",
        "step5",
        "dse.contract.final_report.v1",
        ("user", "archive"),
        {
            **_SCOPE,
            "claim_validation_ref": "claim_validation.json",
            "summary": "human report consumes Step4 adjudicated evidence",
        },
        required=False,
    ),
    _definition(
        "dft_profile.json",
        "profile_adapter",
        "dse.contract.dft_profile.v1",
        ("step1", "step4"),
        {
            **_STEP1_SCOPE,
            "profile_id": "dft-reference-profile",
            "claim_boundary": "DFT reference proof metadata; not a core IR field",
            "profile_metadata": {"domain": "dft"},
        },
    ),
)


def _catalog_sequence(
    catalog: Sequence[ArtifactDefinition] | Mapping[str, ArtifactDefinition] | None,
) -> tuple[ArtifactDefinition, ...]:
    if catalog is None:
        return ARTIFACT_CATALOG
    if isinstance(catalog, Mapping):
        return tuple(catalog.values())
    return tuple(catalog)


def validate_artifact_catalog(
    catalog: Sequence[ArtifactDefinition] | Mapping[str, ArtifactDefinition] | None = None,
    *,
    schema_registry: Mapping[str, Mapping[str, Any]] | None = None,
    validate_examples: bool = True,
) -> None:
    """Validate canonical artifact ownership and schema bindings."""

    active_catalog = _catalog_sequence(catalog)
    active_schemas = SCHEMA_REGISTRY if schema_registry is None else schema_registry
    producers_by_name: dict[str, str] = {}
    seen_names: set[str] = set()
    for item in active_catalog:
        if not item.canonical_name:
            raise ContractValidationError("artifact canonical_name is required")
        if item.canonical_name in seen_names:
            raise ContractValidationError(f"duplicate artifact name: {item.canonical_name}")
        seen_names.add(item.canonical_name)
        if item.canonical_name in producers_by_name:
            raise ContractValidationError(
                f"artifact {item.canonical_name!r} has more than one producer"
            )
        producers_by_name[item.canonical_name] = item.producer_stage
        if not item.producer_stage:
            raise ContractValidationError(f"{item.canonical_name} missing producer_stage")
        if item.schema_id not in active_schemas:
            raise ContractValidationError(
                f"{item.canonical_name} references unknown schema {item.schema_id!r}"
            )
        if item.required and not item.example:
            raise ContractValidationError(f"{item.canonical_name} missing required example")
        if item.required and not item.consumers:
            raise ContractValidationError(f"{item.canonical_name} missing consumers")
        if validate_examples and item.example:
            validate_instance(item.example, active_schemas[item.schema_id])
        if item.producer_stage == "step3" and item.canonical_name in {
            "artifact_manifest.json",
            "claim_validation.json",
            "final_report.json",
            "final_report.md",
            "l4_interface_metrics.json",
            "manifest.json",
            "provenance.json",
            "verdict.json",
        }:
            raise ContractValidationError(
                f"Step3 cannot own adjudication/report artifact {item.canonical_name}"
            )
        if item.canonical_name == "l4_interface_metrics.json" and item.producer_stage != "step4":
            raise ContractValidationError("Step4 must own canonical l4_interface_metrics.json")
        if item.artifact_class not in {"canonical", "raw"}:
            raise ContractValidationError(
                f"{item.canonical_name} has invalid artifact_class {item.artifact_class!r}"
            )


def artifact_definition_for(
    canonical_name: str,
    catalog: Sequence[ArtifactDefinition] | Mapping[str, ArtifactDefinition] | None = None,
) -> ArtifactDefinition:
    """Return the canonical artifact definition for ``canonical_name``."""

    for item in _catalog_sequence(catalog):
        if item.canonical_name == canonical_name or canonical_name in item.legacy_names:
            return item
    raise ContractValidationError(f"unknown artifact {canonical_name!r}")


def validate_artifact_write(
    producer_stage: str,
    canonical_name: str,
    catalog: Sequence[ArtifactDefinition] | Mapping[str, ArtifactDefinition] | None = None,
) -> None:
    """Validate that ``producer_stage`` is allowed to write ``canonical_name``.

    This is the runtime guard for the Step1--Step5 ownership table: producers
    may consume artifacts from other stages but cannot silently cross-write
    another stage's canonical outputs.
    """

    item = artifact_definition_for(canonical_name, catalog)
    if item.producer_stage != producer_stage:
        raise ContractValidationError(
            f"{producer_stage} cannot write {canonical_name}; canonical producer is {item.producer_stage}"
        )


def validate_artifact_writes(
    producer_stage: str,
    canonical_names: Iterable[str],
    catalog: Sequence[ArtifactDefinition] | Mapping[str, ArtifactDefinition] | None = None,
) -> None:
    """Validate a batch of producer-stage artifact writes."""

    for canonical_name in canonical_names:
        validate_artifact_write(producer_stage, canonical_name, catalog)
