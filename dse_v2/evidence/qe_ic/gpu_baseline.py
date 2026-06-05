#!/usr/bin/env python3
"""GPU-baseline evidence ingestion and validation for QE-IC opportunity analysis."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from dse_v2.evidence.qe_ic.schema import (
    BASELINE_EVIDENCE_STATUSES,
    GPU_BASELINE_CLAIM_BOUNDARY,
    GPU_TARGET_TYPE,
    QE_IC_GPU_BASELINE_MEASUREMENTS_SCHEMA_VERSION,
)


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


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


def _validate_ci(
    ci: Mapping[str, Any],
    *,
    prefix: str,
    mean: Any,
    errors: list[dict[str, str]],
) -> None:
    low = ci.get("low")
    high = ci.get("high")
    if not _is_number(low) or not _is_number(high):
        _error(errors, prefix, "confidence interval must contain numeric low and high")
        return
    if float(low) <= 0 or float(high) <= 0 or float(low) > float(high):
        _error(errors, prefix, "confidence interval bounds must be positive and ordered")
    if _is_number(mean) and not (float(low) <= float(mean) <= float(high)):
        _error(errors, prefix, "runtime mean must fall inside confidence interval")


def validate_qe_ic_gpu_baseline_measurements(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate GPU-only baseline measurements fail-closed."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(payload, Mapping):
        _error(errors, "$", "GPU baseline measurements must be a mapping")
        return {
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "baseline_record_count": 0,
            "measurements_are_real": False,
        }

    if payload.get("schema_version") != QE_IC_GPU_BASELINE_MEASUREMENTS_SCHEMA_VERSION:
        _error(errors, "schema_version", "schema_version is incorrect")
    if payload.get("measurement_role") != "gpu_only_baseline":
        _error(errors, "measurement_role", "measurement_role must be gpu_only_baseline")
    if payload.get("evidence_status") not in BASELINE_EVIDENCE_STATUSES:
        _error(errors, "evidence_status", "evidence_status is unsupported")
    if not isinstance(payload.get("measurements_are_real"), bool):
        _error(errors, "measurements_are_real", "measurements_are_real must be boolean")
    platform = _as_mapping(payload.get("platform"))
    for field in (
        "gpu_name",
        "cpu_name",
        "memory",
        "qe_version",
        "cuda_version",
        "driver_version",
        "precision",
    ):
        if not isinstance(platform.get(field), str) or not platform.get(field):
            _error(errors, f"platform.{field}", f"{field} must be a non-empty string")
    if str(payload.get("claim_boundary", "")) != GPU_BASELINE_CLAIM_BOUNDARY:
        _error(errors, "claim_boundary", "claim_boundary must match the canonical GPU-baseline boundary")

    records = _as_list(payload.get("baseline_records"))
    if not records:
        _error(errors, "baseline_records", "at least one baseline record is required")
    ids: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"baseline_records[{index}]"
        if not isinstance(record, Mapping):
            _error(errors, prefix, "baseline record must be a mapping")
            continue
        baseline_id = record.get("baseline_id")
        if not isinstance(baseline_id, str) or not baseline_id:
            _error(errors, f"{prefix}.baseline_id", "baseline_id must be a non-empty string")
        elif baseline_id in ids:
            _error(errors, f"{prefix}.baseline_id", "baseline_id must be unique")
        ids.add(str(baseline_id))
        for field in (
            "workload_family_id",
            "case_id",
            "program",
            "input_deck_hash",
            "precision",
            "profile_artifact_hash",
        ):
            if not isinstance(record.get(field), str) or not record.get(field):
                _error(errors, f"{prefix}.{field}", f"{field} must be a non-empty string")
        if record.get("target_type") != GPU_TARGET_TYPE:
            _error(errors, f"{prefix}.target_type", "baseline record target_type must be gpu_only")
        if record.get("evidence_status") not in BASELINE_EVIDENCE_STATUSES:
            _error(errors, f"{prefix}.evidence_status", "evidence_status is unsupported")
        runs = _as_list(record.get("runtime_seconds_runs"))
        if not runs or not all(_is_number(value) and float(value) > 0 for value in runs):
            _error(errors, f"{prefix}.runtime_seconds_runs", "runtime runs must be positive numeric values")
        for field in (
            "runtime_seconds_mean",
            "runtime_seconds_std",
            "gpu_utilization_mean",
            "gpu_memory_bandwidth_utilization_mean",
            "host_device_transfer_seconds",
            "communication_seconds",
        ):
            if not _is_number(record.get(field)):
                _error(errors, f"{prefix}.{field}", f"{field} must be numeric")
        if _is_number(record.get("runtime_seconds_mean")) and float(record["runtime_seconds_mean"]) <= 0:
            _error(errors, f"{prefix}.runtime_seconds_mean", "runtime_seconds_mean must be positive")
        for util_field in ("gpu_utilization_mean", "gpu_memory_bandwidth_utilization_mean"):
            if _is_number(record.get(util_field)) and not (0.0 <= float(record[util_field]) <= 1.0):
                _error(errors, f"{prefix}.{util_field}", f"{util_field} must be in [0, 1]")
        _validate_ci(
            _as_mapping(record.get("confidence_interval_95")),
            prefix=f"{prefix}.confidence_interval_95",
            mean=record.get("runtime_seconds_mean"),
            errors=errors,
        )
        if payload.get("measurements_are_real") is True and record.get("evidence_status") != "measured":
            _error(errors, f"{prefix}.evidence_status", "real baseline payloads require measured records")

    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "baseline_record_count": len([row for row in records if isinstance(row, Mapping)]),
        "measurements_are_real": payload.get("measurements_are_real") is True,
    }


BASELINE_MATCH_FIELDS = (
    "workload_family_id",
    "case_id",
    "program",
    "input_deck_hash",
    "precision",
)


def baseline_match_key(record: Mapping[str, Any]) -> tuple[str, str, str, str, str] | None:
    """Return the exact GPU-baseline comparison key for a record-like object."""

    values: list[str] = []
    for field in BASELINE_MATCH_FIELDS:
        value = record.get(field)
        if not isinstance(value, str) or not value:
            return None
        values.append(value)
    return tuple(values)  # type: ignore[return-value]


def baseline_records_by_match_key(payload: Mapping[str, Any]) -> dict[tuple[str, str, str, str, str], Mapping[str, Any]]:
    """Return baseline records keyed by exact workload/case/program/hash/precision."""

    keyed: dict[tuple[str, str, str, str, str], Mapping[str, Any]] = {}
    for record in _as_list(payload.get("baseline_records")):
        if isinstance(record, Mapping):
            key = baseline_match_key(record)
            if key is not None:
                keyed.setdefault(key, record)
    return keyed
