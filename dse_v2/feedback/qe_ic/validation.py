#!/usr/bin/env python3
"""Fail-closed validation for QE-IC Layer-6 synthetic feedback calibration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from dse_v2.candidates.qe_ic import validate_qe_ic_candidate_plan
from dse_v2.evaluation.qe_ic.l1_cost_model import validate_qe_ic_l1_cost_model_results
from dse_v2.feedback.qe_ic.calibration import _compute_metrics
from dse_v2.feedback.qe_ic.feedback_config import validate_qe_ic_feedback_config
from dse_v2.feedback.qe_ic.replay import validate_qe_ic_synthetic_high_fidelity_labels
from dse_v2.feedback.qe_ic.schema import (
    CLAIM_BOUNDARY,
    FORBIDDEN_FIELDS,
    LAYER_NAME,
    POLICY_VERSION,
    QE_IC_FEEDBACK_CALIBRATION_SCHEMA_VERSION,
    QE_IC_FEEDBACK_VALIDATION_SCHEMA_VERSION,
    SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT,
    SOURCE_LAYER5A_L1_RESULTS_ARTIFACT,
    STOPPING_CONDITIONS,
    SYNTHETIC_LABELS,
)


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


def _decision_by_candidate(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(decision.get("candidate_id")): decision
        for decision in _as_list(plan.get("promotion_decisions"))
        if isinstance(decision, Mapping)
    }


def _labels_object(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "dse.qe_ic.synthetic_high_fidelity_labels.v1",
        "label_set_id": "embedded_layer6_labels",
        "labels_are_real_hardware_evidence": False,
        "labels": list(_as_list(result.get("synthetic_high_fidelity_labels"))),
        "claim_boundary": "This fixture contains synthetic high-fidelity replay labels only. It is not measured SystemC/gem5/Vivado/DC/QE execution evidence and does not prove hardware performance.",
    }


def _compare_numbers(expected: Any, actual: Any, *, eps: float = 1e-12) -> bool:
    if _is_number(expected) and _is_number(actual):
        return abs(float(expected) - float(actual)) <= eps
    return expected == actual


def validate_qe_ic_feedback_calibration(result: Mapping[str, Any]) -> dict[str, Any]:
    """Validate Layer-6 feedback calibration with recomputed metrics."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(result, Mapping):
        _error(errors, "$", "feedback calibration must be a mapping")
        return {
            "schema_version": QE_IC_FEEDBACK_VALIDATION_SCHEMA_VERSION,
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "candidate_feedback_record_count": 0,
        }

    if result.get("schema_version") != QE_IC_FEEDBACK_CALIBRATION_SCHEMA_VERSION:
        _error(errors, "schema_version", "feedback calibration schema_version is incorrect")
    if result.get("layer") != LAYER_NAME:
        _error(errors, "layer", f"layer must be {LAYER_NAME}")
    if result.get("source_layer4_candidate_plan_artifact") != SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT:
        _error(
            errors,
            "source_layer4_candidate_plan_artifact",
            f"source_layer4_candidate_plan_artifact must be {SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT}",
        )
    if result.get("source_layer5a_l1_results_artifact") != SOURCE_LAYER5A_L1_RESULTS_ARTIFACT:
        _error(
            errors,
            "source_layer5a_l1_results_artifact",
            f"source_layer5a_l1_results_artifact must be {SOURCE_LAYER5A_L1_RESULTS_ARTIFACT}",
        )
    if result.get("claim_boundary") != CLAIM_BOUNDARY:
        _warning(warnings, "claim_boundary", "claim_boundary differs from canonical wording")
    lowered_boundary = str(result.get("claim_boundary", "")).lower()
    for term in ("synthetic replay feedback calibration", "not measured hardware execution evidence", "does not prove final performance"):
        if term not in lowered_boundary:
            _error(errors, "claim_boundary", f"claim_boundary must mention {term}")
    for path in _forbidden_paths(result):
        _error(errors, path, "forbidden high-fidelity execution, measured, or hardware_proven field is present")

    candidate_plan = _as_mapping(result.get("source_layer4_candidate_plan"))
    plan_validation = validate_qe_ic_candidate_plan(candidate_plan)
    if plan_validation.get("status") != "passed":
        for row in _as_list(plan_validation.get("errors")):
            if isinstance(row, Mapping):
                _error(errors, f"source_layer4_candidate_plan.{row.get('field', '$')}", f"invalid candidate plan: {row.get('message', '')}")
    l1_results = _as_mapping(result.get("source_layer5a_l1_results"))
    l1_validation = validate_qe_ic_l1_cost_model_results(l1_results)
    if l1_validation.get("status") != "passed":
        for row in _as_list(l1_validation.get("errors")):
            if isinstance(row, Mapping):
                _error(errors, f"source_layer5a_l1_results.{row.get('field', '$')}", f"invalid L1 results: {row.get('message', '')}")
    config = _as_mapping(result.get("feedback_config"))
    config_validation = validate_qe_ic_feedback_config(config)
    if config_validation.get("status") != "passed":
        for row in _as_list(config_validation.get("errors")):
            if isinstance(row, Mapping):
                _error(errors, f"feedback_config.{row.get('field', '$')}", f"invalid feedback config: {row.get('message', '')}")
    label_validation = validate_qe_ic_synthetic_high_fidelity_labels(_labels_object(result))
    if label_validation.get("status") != "passed":
        for row in _as_list(label_validation.get("errors")):
            if isinstance(row, Mapping):
                _error(errors, f"synthetic_high_fidelity_labels.{row.get('field', '$')}", f"invalid synthetic labels: {row.get('message', '')}")

    candidates = _candidate_by_id(candidate_plan)
    decisions = _decision_by_candidate(candidate_plan)
    label_ids = {
        str(row.get("candidate_id"))
        for row in _as_list(result.get("synthetic_high_fidelity_labels"))
        if isinstance(row, Mapping)
    }
    for candidate_id in label_ids:
        if candidate_id not in candidates:
            _error(errors, "synthetic_high_fidelity_labels", f"label references unknown candidate {candidate_id}")

    records = _as_list(result.get("candidate_feedback_records"))
    record_ids: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"candidate_feedback_records[{index}]"
        if not isinstance(record, Mapping):
            _error(errors, prefix, "feedback record must be a mapping")
            continue
        candidate_id = str(record.get("candidate_id", ""))
        record_ids.add(candidate_id)
        candidate = _as_mapping(candidates.get(candidate_id))
        if not candidate:
            _error(errors, f"{prefix}.candidate_id", "record references unknown candidate")
            continue
        for field in ("workload_family_id", "motif_id", "template_id", "target_type"):
            if record.get(field) != candidate.get(field):
                _error(errors, f"{prefix}.{field}", f"{field} must match candidate")
        decision = _as_mapping(decisions.get(candidate_id))
        if record.get("layer4_decision") != decision.get("decision"):
            _error(errors, f"{prefix}.layer4_decision", "layer4_decision must match candidate plan")
        if decision.get("decision") == "promote" and not record.get("has_l1_result") and candidate.get("candidate_type") != "baseline":
            _error(errors, f"{prefix}.has_l1_result", "promoted candidate must have L1 result or feedback state")
        if record.get("synthetic_label") not in SYNTHETIC_LABELS | {"unlabeled"}:
            _error(errors, f"{prefix}.synthetic_label", "synthetic_label is unsupported")
    missing_records = set(candidates) - record_ids
    if missing_records:
        _error(errors, "candidate_feedback_records", f"missing feedback records for candidates: {sorted(missing_records)[:5]}")

    expected_metrics = _compute_metrics(
        candidate_plan=candidate_plan,
        labels=_labels_object(result),
        feedback_records=[row for row in records if isinstance(row, Mapping)],
        config=config,
    )
    metrics = _as_mapping(result.get("metrics"))
    for field, expected_value in expected_metrics.items():
        actual_value = metrics.get(field)
        if isinstance(expected_value, Mapping):
            if actual_value != expected_value:
                _error(errors, f"metrics.{field}", f"metrics.{field} does not match recomputed value")
        elif not _compare_numbers(expected_value, actual_value):
            _error(errors, f"metrics.{field}", f"metrics.{field} does not match recomputed value")

    calibration_update = _as_mapping(result.get("calibration_update"))
    for field in (
        "risk_threshold_updates",
        "template_adjustments",
        "motif_adjustments",
        "target_type_adjustments",
    ):
        if not _as_mapping(calibration_update.get(field)):
            _error(errors, f"calibration_update.{field}", f"{field} must be non-empty")
    adaptive = _as_mapping(result.get("adaptive_policy_state"))
    if adaptive.get("policy_version") != POLICY_VERSION:
        _error(errors, "adaptive_policy_state.policy_version", f"policy_version must be {POLICY_VERSION}")
    if not _as_list(adaptive.get("next_round_priority_rules")):
        _error(errors, "adaptive_policy_state.next_round_priority_rules", "priority rules must be non-empty")
    for index, suggestion in enumerate(_as_list(adaptive.get("next_round_candidate_suggestions"))):
        if not isinstance(suggestion, Mapping):
            _error(errors, f"adaptive_policy_state.next_round_candidate_suggestions[{index}]", "suggestion must be a mapping")
            continue
        candidate_id = str(suggestion.get("candidate_id", ""))
        candidate = _as_mapping(candidates.get(candidate_id))
        if not candidate:
            _error(errors, f"adaptive_policy_state.next_round_candidate_suggestions[{index}].candidate_id", "suggestion references unknown candidate")
            continue
        for field in ("motif_id", "template_id", "target_type"):
            if suggestion.get(field) != candidate.get(field):
                _error(errors, f"adaptive_policy_state.next_round_candidate_suggestions[{index}].{field}", f"{field} must match candidate")
        if suggestion.get("suggestion") not in {"promote", "hold", "reject"}:
            _error(errors, f"adaptive_policy_state.next_round_candidate_suggestions[{index}].suggestion", "suggestion is unsupported")

    stopping = _as_mapping(result.get("stopping_condition_evaluation"))
    if stopping.get("decision_basis") != "synthetic_replay_stop_decision":
        _error(errors, "stopping_condition_evaluation.decision_basis", "decision_basis must be synthetic_replay_stop_decision")
    if stopping.get("stop_decision") not in {"continue", "stop"}:
        _error(errors, "stopping_condition_evaluation.stop_decision", "stop_decision must be continue or stop")
    condition_names = {
        row.get("condition")
        for row in _as_list(stopping.get("conditions"))
        if isinstance(row, Mapping)
    }
    if condition_names != set(STOPPING_CONDITIONS):
        _error(errors, "stopping_condition_evaluation.conditions", "stopping conditions are incomplete")
    recomputed_stop_reasons = [
        row.get("condition")
        for row in _as_list(stopping.get("conditions"))
        if isinstance(row, Mapping) and row.get("satisfied") is True
    ]
    if stopping.get("stop_reasons") != recomputed_stop_reasons:
        _error(errors, "stopping_condition_evaluation.stop_reasons", "stop_reasons do not match satisfied conditions")

    return {
        "schema_version": QE_IC_FEEDBACK_VALIDATION_SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "candidate_feedback_record_count": len([row for row in records if isinstance(row, Mapping)]),
        "promotion_precision": metrics.get("promotion_precision"),
        "false_promotion_rate": metrics.get("false_promotion_rate"),
        "wasted_budget_ratio": metrics.get("wasted_budget_ratio"),
    }
