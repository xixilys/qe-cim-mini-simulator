#!/usr/bin/env python3
"""Fail-closed validation for QE-IC closed-loop DSE campaign results."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from dse_v2.campaigns.qe_ic.campaign_config import validate_qe_ic_closed_loop_dse_campaign_config
from dse_v2.campaigns.qe_ic.runner import _build_candidate_trajectory, _system_summary
from dse_v2.campaigns.qe_ic.schema import (
    ARTIFACT_INDEX_LAYERS,
    CLAIM_BOUNDARY,
    FORBIDDEN_FIELDS,
    LAYER_NAME,
    QE_IC_CLOSED_LOOP_RESULTS_SCHEMA_VERSION,
    QE_IC_CLOSED_LOOP_VALIDATION_SCHEMA_VERSION,
    REQUIRED_LAYERS,
    VALIDITY_LEVELS,
)
from dse_v2.candidates.qe_ic import validate_qe_ic_candidate_plan
from dse_v2.evaluation.qe_ic.l1_cost_model import validate_qe_ic_l1_cost_model_results
from dse_v2.feedback.qe_ic import validate_qe_ic_feedback_calibration
from dse_v2.profiling.qe_ic import validate_qe_ic_motif_profile
from dse_v2.viability.qe_ic import validate_qe_ic_target_viability
from dse_v2.workloads.qe_ic import validate_qe_ic_workload_suite


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _warning(warnings: list[dict[str, str]], field: str, message: str) -> None:
    warnings.append({"field": field, "message": message})


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _forbidden_paths(value: Any, *, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_path = f"{prefix}.{key}" if prefix else str(key)
            lowered_key = str(key).lower()
            if lowered_key in FORBIDDEN_FIELDS or "hardware_proven" in lowered_key:
                paths.append(key_path)
            paths.extend(_forbidden_paths(nested, prefix=key_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_forbidden_paths(nested, prefix=f"{prefix}[{index}]"))
    elif isinstance(value, str) and "hardware_proven" in value.lower():
        paths.append(prefix)
    return paths


def _candidate_by_id(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate.get("candidate_id")): candidate
        for candidate in _as_list(plan.get("candidates"))
        if isinstance(candidate, Mapping)
    }


def _compare(expected: Any, actual: Any, *, eps: float = 1e-12) -> bool:
    if _is_number(expected) and _is_number(actual):
        return abs(float(expected) - float(actual)) <= eps
    return expected == actual


def _validate_embedded_layers(result: Mapping[str, Any], errors: list[dict[str, str]]) -> dict[str, Mapping[str, Any]]:
    source = _as_mapping(result.get("source_artifacts"))
    layers = {
        "layer1_workload_suite": _as_mapping(source.get("layer1_workload_suite")),
        "layer2_motif_profile": _as_mapping(source.get("layer2_motif_profile")),
        "layer3_target_viability": _as_mapping(source.get("layer3_target_viability")),
        "layer4_candidate_plan": _as_mapping(source.get("layer4_candidate_plan")),
        "layer5a_l1_cost_model": _as_mapping(source.get("layer5a_l1_cost_model")),
    }
    validators = {
        "layer1_workload_suite": validate_qe_ic_workload_suite,
        "layer2_motif_profile": validate_qe_ic_motif_profile,
        "layer3_target_viability": validate_qe_ic_target_viability,
        "layer4_candidate_plan": validate_qe_ic_candidate_plan,
        "layer5a_l1_cost_model": validate_qe_ic_l1_cost_model_results,
    }
    for layer, payload in layers.items():
        validation = validators[layer](payload)
        if validation.get("status") != "passed":
            for row in _as_list(validation.get("errors")):
                if isinstance(row, Mapping):
                    _error(errors, f"source_artifacts.{layer}.{row.get('field', '$')}", f"invalid {layer}: {row.get('message', '')}")
    feedback_validation = validate_qe_ic_feedback_calibration(_as_mapping(result.get("feedback_summary")))
    if feedback_validation.get("status") != "passed":
        for row in _as_list(feedback_validation.get("errors")):
            if isinstance(row, Mapping):
                _error(errors, f"feedback_summary.{row.get('field', '$')}", f"invalid feedback summary: {row.get('message', '')}")
    return layers


def validate_qe_ic_closed_loop_dse_results(result: Mapping[str, Any]) -> dict[str, Any]:
    """Validate system-level closed-loop campaign results."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(result, Mapping):
        _error(errors, "$", "closed-loop campaign result must be a mapping")
        return {
            "schema_version": QE_IC_CLOSED_LOOP_VALIDATION_SCHEMA_VERSION,
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "candidate_trajectory_count": 0,
        }

    if result.get("schema_version") != QE_IC_CLOSED_LOOP_RESULTS_SCHEMA_VERSION:
        _error(errors, "schema_version", "schema_version is incorrect")
    if result.get("layer") != LAYER_NAME:
        _error(errors, "layer", f"layer must be {LAYER_NAME}")
    if result.get("claim_boundary") != CLAIM_BOUNDARY:
        _warning(warnings, "claim_boundary", "claim_boundary differs from canonical wording")
    boundary = str(result.get("claim_boundary", "")).lower()
    for term in ("layer-6 synthetic feedback calibration", "does not contain", "superiority claims"):
        if term not in boundary:
            _error(errors, "claim_boundary", f"claim_boundary must mention {term}")
    for path in _forbidden_paths(result):
        _error(errors, path, "forbidden high-fidelity execution, measured, or hardware_proven field is present")

    config_validation = validate_qe_ic_closed_loop_dse_campaign_config(_as_mapping(result.get("campaign_config")))
    if config_validation.get("status") != "passed":
        for row in _as_list(config_validation.get("errors")):
            if isinstance(row, Mapping):
                _error(errors, f"campaign_config.{row.get('field', '$')}", f"invalid campaign config: {row.get('message', '')}")

    artifact_index = _as_mapping(result.get("artifact_index"))
    if set(artifact_index) != set(ARTIFACT_INDEX_LAYERS):
        _error(errors, "artifact_index", f"artifact_index must contain {ARTIFACT_INDEX_LAYERS}")
    layer_status = _as_list(result.get("layer_status"))
    layer_names = {
        row.get("layer")
        for row in layer_status
        if isinstance(row, Mapping)
    }
    if set(REQUIRED_LAYERS) - layer_names:
        _error(errors, "layer_status", f"layer_status missing {sorted(set(REQUIRED_LAYERS) - layer_names)}")
    for row in layer_status:
        if isinstance(row, Mapping) and row.get("status") != "passed":
            _error(errors, "layer_status", f"{row.get('layer')} did not pass")

    layers = _validate_embedded_layers(result, errors)
    feedback_summary = _as_mapping(result.get("feedback_summary"))
    expected_summary = _system_summary(
        suite=layers["layer1_workload_suite"],
        motif_profile=layers["layer2_motif_profile"],
        target_viability=layers["layer3_target_viability"],
        candidate_plan=layers["layer4_candidate_plan"],
        l1_results=layers["layer5a_l1_cost_model"],
        feedback_calibration=feedback_summary,
    )
    actual_summary = _as_mapping(result.get("system_summary"))
    for field, expected_value in expected_summary.items():
        if not _compare(expected_value, actual_summary.get(field)):
            _error(errors, f"system_summary.{field}", f"system_summary.{field} does not match underlying artifacts")

    candidate_plan = layers["layer4_candidate_plan"]
    candidates = _candidate_by_id(candidate_plan)
    expected_trajectory = _build_candidate_trajectory(
        candidate_plan=candidate_plan,
        l1_results=layers["layer5a_l1_cost_model"],
        feedback_calibration=feedback_summary,
    )
    trajectory = _as_list(result.get("candidate_trajectory"))
    if len(trajectory) != len(expected_trajectory):
        _error(errors, "candidate_trajectory", "candidate trajectory length does not match candidate count")
    expected_by_id = {
        row["candidate_id"]: row
        for row in expected_trajectory
    }
    for index, row in enumerate(trajectory):
        prefix = f"candidate_trajectory[{index}]"
        if not isinstance(row, Mapping):
            _error(errors, prefix, "candidate trajectory row must be a mapping")
            continue
        candidate_id = str(row.get("candidate_id", ""))
        if candidate_id not in candidates:
            _error(errors, f"{prefix}.candidate_id", "candidate trajectory references unknown candidate")
            continue
        if row.get("candidate_validity_level") not in VALIDITY_LEVELS:
            _error(errors, f"{prefix}.candidate_validity_level", "candidate validity level is unsupported")
        expected = _as_mapping(expected_by_id.get(candidate_id))
        for field in ("layer4_decision", "has_l1_result", "synthetic_label", "candidate_validity_level"):
            if row.get(field) != expected.get(field):
                _error(errors, f"{prefix}.{field}", f"{field} does not match recomputed trajectory")

    adaptive = _as_mapping(result.get("adaptive_policy_state"))
    plan = _as_mapping(result.get("next_round_plan"))
    if not adaptive.get("policy_version"):
        _error(errors, "adaptive_policy_state.policy_version", "adaptive policy state must have policy_version")
    if plan.get("policy_version") != adaptive.get("policy_version"):
        _error(errors, "next_round_plan.policy_version", "next_round_plan policy_version must match adaptive policy")
    known_motifs = {str(candidate.get("motif_id")) for candidate in candidates.values()}
    known_templates = {str(candidate.get("template_id")) for candidate in candidates.values()}
    known_targets = {str(candidate.get("target_type")) for candidate in candidates.values()}
    for index, suggestion in enumerate(_as_list(plan.get("candidate_suggestions"))):
        if not isinstance(suggestion, Mapping):
            _error(errors, f"next_round_plan.candidate_suggestions[{index}]", "candidate suggestion must be a mapping")
            continue
        if suggestion.get("motif_id") not in known_motifs:
            _error(errors, f"next_round_plan.candidate_suggestions[{index}].motif_id", "suggestion references unknown motif")
        if suggestion.get("template_id") not in known_templates:
            _error(errors, f"next_round_plan.candidate_suggestions[{index}].template_id", "suggestion references unknown template")
        if suggestion.get("target_type") not in known_targets:
            _error(errors, f"next_round_plan.candidate_suggestions[{index}].target_type", "suggestion references unknown target")
    stop = _as_mapping(plan.get("stopping_condition_evaluation"))
    if plan.get("decision_basis") != "synthetic_replay_stop_decision" or stop.get("decision_basis") != "synthetic_replay_stop_decision":
        _error(errors, "next_round_plan.decision_basis", "next_round_plan must use synthetic_replay_stop_decision")
    if actual_summary.get("stop_decision") != stop.get("stop_decision"):
        _error(errors, "system_summary.stop_decision", "stop_decision must match next_round_plan")

    return {
        "schema_version": QE_IC_CLOSED_LOOP_VALIDATION_SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "candidate_trajectory_count": len([row for row in trajectory if isinstance(row, Mapping)]),
        "layer_count": len(layer_status),
        "stop_decision": actual_summary.get("stop_decision"),
    }
