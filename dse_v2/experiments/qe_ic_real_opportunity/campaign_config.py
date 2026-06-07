#!/usr/bin/env python3
"""Config loading and validation for the QE-IC real opportunity campaign."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.experiments.qe_ic_real_opportunity.schema import (
    ALLOWED_MODES,
    CONFIG_CLAIM_BOUNDARY,
    OPTIONAL_INPUT_ARTIFACT_KEYS,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_CONFIG_SCHEMA_VERSION,
    REQUIRED_INPUT_ARTIFACT_KEYS,
)


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def load_json_object(path: Path) -> dict[str, Any]:
    """Load a JSON object from path."""

    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def validate_qe_ic_real_opportunity_campaign_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate campaign config fail-closed for software errors."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(config, Mapping):
        _error(errors, "$", "campaign config must be a mapping")
        return {"status": "failed", "errors": errors, "warnings": warnings}

    if config.get("schema_version") != QE_IC_REAL_OPPORTUNITY_CAMPAIGN_CONFIG_SCHEMA_VERSION:
        _error(errors, "schema_version", "campaign config schema_version is incorrect")
    if not isinstance(config.get("campaign_id"), str) or not config.get("campaign_id"):
        _error(errors, "campaign_id", "campaign_id must be a non-empty string")
    if config.get("mode") not in ALLOWED_MODES:
        _error(errors, "mode", f"mode must be one of {sorted(ALLOWED_MODES)}")
    if not isinstance(config.get("research_question"), str) or not config.get("research_question"):
        _error(errors, "research_question", "research_question must be a non-empty string")

    case_selection = _as_mapping(config.get("case_selection"))
    required_families = case_selection.get("required_workload_families")
    if not isinstance(required_families, list) or not all(isinstance(row, str) for row in required_families):
        _error(errors, "case_selection.required_workload_families", "required workload families must be a string list")
    if not isinstance(case_selection.get("allow_proxy_case_if_full_workload_unavailable"), bool):
        _error(
            errors,
            "case_selection.allow_proxy_case_if_full_workload_unavailable",
            "allow_proxy_case_if_full_workload_unavailable must be boolean",
        )
    if not isinstance(case_selection.get("minimum_cases_required_for_passed_campaign"), int):
        _error(
            errors,
            "case_selection.minimum_cases_required_for_passed_campaign",
            "minimum_cases_required_for_passed_campaign must be integer",
        )

    candidate_selection = _as_mapping(config.get("candidate_selection"))
    if candidate_selection.get("select_from_layer4_only") is not True:
        _error(errors, "candidate_selection.select_from_layer4_only", "campaign must select from Layer-4 only")
    if not isinstance(candidate_selection.get("max_candidates"), int):
        _error(errors, "candidate_selection.max_candidates", "max_candidates must be integer")
    target_kinds = candidate_selection.get("target_candidate_kinds")
    if not isinstance(target_kinds, list) or not all(isinstance(row, str) for row in target_kinds):
        _error(errors, "candidate_selection.target_candidate_kinds", "target_candidate_kinds must be a string list")

    evidence_policy = _as_mapping(config.get("evidence_policy"))
    if evidence_policy.get("forbid_fabricated_measurements") is not True:
        _error(errors, "evidence_policy.forbid_fabricated_measurements", "fabricated measurements must be forbidden")

    claim_policy = _as_mapping(config.get("claim_policy"))
    required_claim_fields = {
        "must_use_existing_opportunity_claim_gate",
        "minimum_speedup_for_strong_claim",
        "minimum_repeated_runs",
        "require_confidence_interval_not_crossing_one",
        "require_workflow_level_or_trace_replay",
        "require_resource_feasible",
        "require_timing_feasible",
        "allow_kernel_only_claim",
    }
    missing_claim_fields = sorted(required_claim_fields - set(claim_policy))
    if missing_claim_fields:
        _error(errors, "claim_policy", f"claim_policy missing fields: {missing_claim_fields}")
    if claim_policy.get("must_use_existing_opportunity_claim_gate") is not True:
        _error(errors, "claim_policy.must_use_existing_opportunity_claim_gate", "existing claim gate must be used")
    if claim_policy.get("allow_kernel_only_claim") is not False:
        _error(errors, "claim_policy.allow_kernel_only_claim", "kernel-only claims must be disabled")

    quality_policy = _as_mapping(config.get("implementation_quality_policy"))
    if quality_policy.get("must_distinguish_implementation_limited_from_fundamental_no_opportunity") is not True:
        _error(
            errors,
            "implementation_quality_policy.must_distinguish_implementation_limited_from_fundamental_no_opportunity",
            "implementation-limited and fundamental-no-opportunity outcomes must be distinguished",
        )

    input_artifacts = _as_mapping(config.get("input_artifacts"))
    missing_required = sorted(REQUIRED_INPUT_ARTIFACT_KEYS - set(input_artifacts))
    if missing_required:
        _error(errors, "input_artifacts", f"input_artifacts missing required keys: {missing_required}")
    unknown_inputs = sorted(set(input_artifacts) - REQUIRED_INPUT_ARTIFACT_KEYS - OPTIONAL_INPUT_ARTIFACT_KEYS)
    if unknown_inputs:
        warnings.append({"field": "input_artifacts", "message": f"unknown optional input keys ignored: {unknown_inputs}"})
    for key, value in input_artifacts.items():
        if not isinstance(value, str) or not value:
            _error(errors, f"input_artifacts.{key}", "input artifact path must be a non-empty string")

    if config.get("claim_boundary") != CONFIG_CLAIM_BOUNDARY:
        _error(errors, "claim_boundary", "claim_boundary must match canonical campaign boundary")

    return {
        "schema_version": "dse.qe_ic.real_opportunity_campaign_config_validation.v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
    }


def opportunity_config_from_campaign(config: Mapping[str, Any], input_artifacts: Mapping[str, str]) -> dict[str, Any]:
    """Build the existing opportunity-analysis config from campaign policy."""

    claim_policy = _as_mapping(config.get("claim_policy"))
    return {
        "schema_version": "dse.qe_ic.real_baseline_opportunity_config.v1",
        "analysis_role": "claim_gated_gpu_vs_fpga_hybrid_opportunity_analysis",
        "config_id": f"{config.get('campaign_id', 'qe_ic_real_opportunity')}_opportunity_gate",
        "input_artifacts": {
            "layer1_workload_suite": input_artifacts["layer1_workload_suite"],
            "layer2_motif_profile": input_artifacts["layer2_motif_profile"],
            "layer3_target_viability": input_artifacts["layer3_target_viability"],
            "layer4_candidate_plan": input_artifacts["layer4_candidate_plan"],
            "layer5a_l1_cost_model": input_artifacts["layer5a_l1_cost_model"],
            "layer6_closed_loop_dse": input_artifacts["layer6_closed_loop_dse"],
            "gpu_baseline_measurements": input_artifacts["gpu_baseline_measurements"],
            "candidate_high_fidelity_results": input_artifacts["candidate_high_fidelity_results"],
        },
        "claim_gates": {
            "minimum_speedup_for_strong_claim": claim_policy.get("minimum_speedup_for_strong_claim", 1.10),
            "minimum_repeated_runs": claim_policy.get("minimum_repeated_runs", 3),
            "require_confidence_interval_not_crossing_one": claim_policy.get(
                "require_confidence_interval_not_crossing_one",
                True,
            ),
            "require_resource_feasible": claim_policy.get("require_resource_feasible", True),
            "require_timing_feasible": claim_policy.get("require_timing_feasible", True),
            "require_workflow_level_or_trace_replay": claim_policy.get("require_workflow_level_or_trace_replay", True),
            "allow_kernel_only_claim": claim_policy.get("allow_kernel_only_claim", False),
        },
        "analysis_thresholds": {
            "gpu_dominant_utilization": 0.70,
            "transfer_overhead_dominant_ratio": 0.30,
            "resource_pressure_high": 0.85,
            "workflow_overhead_high": 0.20,
        },
        "claim_boundary": (
            "This config enables claim-gated opportunity analysis from explicit GPU "
            "baseline and candidate high-fidelity evidence. It does not allow L1 "
            "estimates or synthetic feedback to be treated as measured hardware performance."
        ),
    }
