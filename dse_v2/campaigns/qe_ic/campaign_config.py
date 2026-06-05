#!/usr/bin/env python3
"""Campaign config validation for the QE-IC closed-loop DSE system."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dse_v2.campaigns.qe_ic.schema import (
    CONFIG_CLAIM_BOUNDARY,
    QE_IC_CLOSED_LOOP_CAMPAIGN_CONFIG_SCHEMA_VERSION,
)


REQUIRED_ARTIFACT_PATHS = {
    "layer1_workload_suite",
    "layer2_motif_profile",
    "layer3_target_viability",
    "layer4_candidate_plan",
    "layer5a_l1_cost_model",
    "layer6_synthetic_labels",
    "layer6_feedback_config",
}


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _warning(warnings: list[dict[str, str]], field: str, message: str) -> None:
    warnings.append({"field": field, "message": message})


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def validate_qe_ic_closed_loop_dse_campaign_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate closed-loop campaign config fail-closed."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(config, Mapping):
        _error(errors, "$", "campaign config must be a mapping")
        return {
            "schema_version": "dse.qe_ic.closed_loop_dse_campaign_config_validation.v1",
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
        }
    if config.get("schema_version") != QE_IC_CLOSED_LOOP_CAMPAIGN_CONFIG_SCHEMA_VERSION:
        _error(errors, "schema_version", "campaign config schema_version is incorrect")
    if not isinstance(config.get("campaign_id"), str) or not config.get("campaign_id"):
        _error(errors, "campaign_id", "campaign_id must be a non-empty string")
    if config.get("artifact_mode") not in {"artifact_replay", "regenerate_missing"}:
        _error(errors, "artifact_mode", "artifact_mode must be artifact_replay or regenerate_missing")
    if config.get("artifact_mode") == "artifact_replay" and config.get("regenerate_missing") is not False:
        _error(errors, "regenerate_missing", "artifact_replay mode must not regenerate missing artifacts")
    if config.get("allow_real_execution") is not False:
        _error(errors, "allow_real_execution", "closed-loop fixture must not allow real execution")
    artifact_paths = _as_mapping(config.get("artifact_paths"))
    missing = sorted(REQUIRED_ARTIFACT_PATHS - set(artifact_paths))
    if missing:
        _error(errors, "artifact_paths", f"artifact_paths missing required keys: {missing}")
    for key in REQUIRED_ARTIFACT_PATHS & set(artifact_paths):
        if not isinstance(artifact_paths.get(key), str) or not artifact_paths.get(key):
            _error(errors, f"artifact_paths.{key}", f"{key} path must be a non-empty string")
    if config.get("artifact_mode") == "regenerate_missing":
        regeneration = _as_mapping(config.get("regeneration_inputs"))
        for key in (
            "layer2_profile_sources",
            "layer3_target_config",
            "layer4_campaign_config",
            "layer5a_l1_model_config",
        ):
            if not isinstance(regeneration.get(key), str) or not regeneration.get(key):
                _error(errors, f"regeneration_inputs.{key}", f"{key} path must be a non-empty string")
    boundary = str(config.get("claim_boundary", ""))
    lowered = boundary.lower()
    for term in ("artifact replay", "synthetic feedback calibration", "does not enable", "superiority claims"):
        if term not in lowered:
            _error(errors, "claim_boundary", f"claim_boundary must mention {term}")
    if config.get("claim_boundary") != CONFIG_CLAIM_BOUNDARY:
        _warning(warnings, "claim_boundary", "claim_boundary differs from canonical wording")
    return {
        "schema_version": "dse.qe_ic.closed_loop_dse_campaign_config_validation.v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
    }
