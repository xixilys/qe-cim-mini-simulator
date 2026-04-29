from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

try:
    from .interfaces import DESIGN_POINT_IDENTITY_KEYS, WORKLOAD_IDENTITY_KEYS
except ImportError:  # pragma: no cover - script-path fallback
    from interfaces import DESIGN_POINT_IDENTITY_KEYS, WORKLOAD_IDENTITY_KEYS  # type: ignore


CALIBRATION_FEEDBACK_SCHEMA_VERSION = "calibration_feedback_v0"
CALIBRATION_FEEDBACK_CLAIM_CEILING = "calibration_feedback_only"

CALIBRATION_STATUSES = {
    "calibrated",
    "partial",
    "not_measured",
    "baseline_missing",
    "rejected",
}

_IDENTITY_KEYS = set(WORKLOAD_IDENTITY_KEYS + DESIGN_POINT_IDENTITY_KEYS)


def load_and_validate_calibration_feedback(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("calibration feedback root must be an object")
    validate_calibration_feedback(payload)
    return payload


def _require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"calibration feedback requires mapping field: {key}")
    return value


def validate_calibration_feedback(payload: Mapping[str, Any]) -> None:
    required = (
        "schema_version",
        "feedback_id",
        "candidate_id",
        "calibration_status",
        "claim_ceiling",
        "source_report_refs",
        "updated_parameters",
        "residual_summary",
        "evidence_refs",
    )
    for key in required:
        if key not in payload:
            raise ValueError(f"calibration feedback missing field: {key}")
    if payload["schema_version"] != CALIBRATION_FEEDBACK_SCHEMA_VERSION:
        raise ValueError("unsupported calibration feedback schema_version")
    if payload["claim_ceiling"] != CALIBRATION_FEEDBACK_CLAIM_CEILING:
        raise ValueError("calibration feedback claim_ceiling must be calibration_feedback_only")
    if payload["calibration_status"] not in CALIBRATION_STATUSES:
        raise ValueError("invalid calibration_status")
    if not isinstance(payload["feedback_id"], str) or not payload["feedback_id"]:
        raise ValueError("feedback_id must be a non-empty string")
    if not isinstance(payload["candidate_id"], str) or not payload["candidate_id"]:
        raise ValueError("candidate_id must be a non-empty string")

    _require_mapping(payload, "source_report_refs")
    updated_parameters = _require_mapping(payload, "updated_parameters")
    _require_mapping(payload, "residual_summary")
    _require_mapping(payload, "evidence_refs")

    forbidden = sorted(str(key) for key in updated_parameters if str(key) in _IDENTITY_KEYS)
    if forbidden:
        raise ValueError(f"calibration feedback cannot update identity key: {forbidden[0]}")
    if payload.get("final_public_family_winner") is not None:
        raise ValueError("calibration feedback must not declare a final public family winner")
    if payload.get("production_release_ready") is True:
        raise ValueError("calibration feedback must not claim production release readiness")


def summarize_calibration_feedback(payload: Mapping[str, Any]) -> dict[str, Any]:
    updated_parameters = payload.get("updated_parameters", {})
    if not isinstance(updated_parameters, Mapping):
        updated_parameters = {}
    residual_summary = payload.get("residual_summary", {})
    if not isinstance(residual_summary, Mapping):
        residual_summary = {}
    return {
        "schema_version": str(payload.get("schema_version")),
        "feedback_id": str(payload.get("feedback_id")),
        "candidate_id": str(payload.get("candidate_id")),
        "calibration_status": str(payload.get("calibration_status")),
        "claim_ceiling": str(payload.get("claim_ceiling")),
        "updated_parameter_count": len(updated_parameters),
        "residual_status": residual_summary.get("status"),
    }
