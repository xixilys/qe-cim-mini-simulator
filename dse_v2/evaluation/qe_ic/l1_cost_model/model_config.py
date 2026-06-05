#!/usr/bin/env python3
"""Model config validation for QE-IC Layer-5A L1 cost model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dse_v2.evaluation.qe_ic.l1_cost_model.schema import (
    CONFIG_CLAIM_BOUNDARY,
    NEXT_FIDELITY_SUGGESTIONS,
    QE_IC_L1_COST_MODEL_CONFIG_SCHEMA_VERSION,
)


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _warning(warnings: list[dict[str, str]], field: str, message: str) -> None:
    warnings.append({"field": field, "message": message})


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _validate_claim_boundary(boundary: str, errors: list[dict[str, str]]) -> None:
    lowered = boundary.lower()
    if not boundary:
        _error(errors, "claim_boundary", "claim_boundary must be non-empty")
        return
    for term in ("deterministic l1 analytical estimates", "external execution", "final performance claims"):
        if term not in lowered:
            _error(errors, "claim_boundary", f"claim_boundary must mention {term}")
    if "does not permit" not in lowered and "not" not in lowered:
        _error(errors, "claim_boundary", "claim_boundary must explicitly prohibit execution and final claims")


def validate_qe_ic_l1_cost_model_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate Layer-5A model config fail-closed."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(config, Mapping):
        _error(errors, "$", "model config must be a mapping")
        return {"status": "failed", "errors": errors, "warnings": warnings}

    if config.get("schema_version") != QE_IC_L1_COST_MODEL_CONFIG_SCHEMA_VERSION:
        _error(errors, "schema_version", "model config schema_version is incorrect")
    if not isinstance(config.get("config_id"), str) or not config.get("config_id"):
        _error(errors, "config_id", "config_id must be a non-empty string")
    if config.get("model_role") != "deterministic_analytical_l1_cost_model":
        _error(errors, "model_role", "model_role must be deterministic_analytical_l1_cost_model")

    policy = _as_mapping(config.get("model_policy"))
    for field in (
        "allow_external_execution",
        "allow_systemc",
        "allow_gem5",
        "allow_vivado",
        "allow_dc",
        "allow_real_qe",
    ):
        if policy.get(field) is not False:
            _error(errors, f"model_policy.{field}", f"{field} must be false")

    components = _as_mapping(config.get("estimate_components"))
    for field in ("runtime", "memory", "communication", "resource", "risk"):
        if components.get(field) is not True:
            _error(errors, f"estimate_components.{field}", f"{field} must be true")

    calibration = _as_mapping(config.get("calibration"))
    if calibration.get("calibration_status") != "fixture_prior":
        _error(errors, "calibration.calibration_status", "calibration_status must be fixture_prior")
    if calibration.get("calibration_source") != "not_measured_hardware":
        _error(errors, "calibration.calibration_source", "calibration_source must be not_measured_hardware")
    if calibration.get("requires_future_high_fidelity_calibration") is not True:
        _error(
            errors,
            "calibration.requires_future_high_fidelity_calibration",
            "requires_future_high_fidelity_calibration must be true",
        )

    next_policy = _as_mapping(config.get("next_fidelity_policy"))
    if next_policy.get("allow_suggestions") is not True:
        _error(errors, "next_fidelity_policy.allow_suggestions", "allow_suggestions must be true")
    supported = _as_list(next_policy.get("supported_suggestions"))
    if not supported:
        _error(errors, "next_fidelity_policy.supported_suggestions", "supported_suggestions must be non-empty")
    elif set(supported) != NEXT_FIDELITY_SUGGESTIONS:
        _error(
            errors,
            "next_fidelity_policy.supported_suggestions",
            "supported_suggestions must exactly match the fixed suggestion registry",
        )

    _validate_claim_boundary(str(config.get("claim_boundary", "")), errors)
    if config.get("claim_boundary") != CONFIG_CLAIM_BOUNDARY:
        _warning(warnings, "claim_boundary", "claim_boundary differs from canonical wording")

    return {
        "schema_version": "dse.qe_ic.l1_cost_model_config_validation.v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
    }

