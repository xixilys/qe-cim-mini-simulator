#!/usr/bin/env python3
"""Candidate high-fidelity evidence ingestion for QE-IC opportunity analysis."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from dse_v2.evidence.qe_ic.schema import (
    CANDIDATE_EVIDENCE_LEVELS,
    CANDIDATE_EVIDENCE_STATUSES,
    CANDIDATE_RESULT_CLAIM_BOUNDARY,
    QE_IC_CANDIDATE_HIGH_FIDELITY_RESULTS_SCHEMA_VERSION,
    REQUIRED_HIGH_FIDELITY_PROVENANCE_FIELDS,
    TARGET_TYPES,
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


def validate_qe_ic_candidate_high_fidelity_results(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate candidate high-fidelity result records."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(payload, Mapping):
        _error(errors, "$", "candidate high-fidelity results must be a mapping")
        return {
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "candidate_result_count": 0,
            "results_are_real": False,
        }

    if payload.get("schema_version") != QE_IC_CANDIDATE_HIGH_FIDELITY_RESULTS_SCHEMA_VERSION:
        _error(errors, "schema_version", "schema_version is incorrect")
    if not isinstance(payload.get("results_are_real"), bool):
        _error(errors, "results_are_real", "results_are_real must be boolean")
    records = _as_list(payload.get("candidate_results"))
    if not records:
        _error(errors, "candidate_results", "at least one candidate result is required")
    ids: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"candidate_results[{index}]"
        if not isinstance(record, Mapping):
            _error(errors, prefix, "candidate result must be a mapping")
            continue
        candidate_id = record.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            _error(errors, f"{prefix}.candidate_id", "candidate_id must be a non-empty string")
        elif candidate_id in ids:
            _error(errors, f"{prefix}.candidate_id", "candidate_id must be unique")
        ids.add(str(candidate_id))
        for field in (
            "workload_family_id",
            "motif_id",
            "case_id",
            "program",
            "input_deck_hash",
            "precision",
        ):
            if not isinstance(record.get(field), str) or not record.get(field):
                _error(errors, f"{prefix}.{field}", f"{field} must be a non-empty string")
        if record.get("target_type") not in TARGET_TYPES:
            _error(errors, f"{prefix}.target_type", "target_type must be fpga_only or gpu_fpga_hybrid")
        if record.get("evidence_level") not in CANDIDATE_EVIDENCE_LEVELS:
            _error(errors, f"{prefix}.evidence_level", "evidence_level is unsupported")
        if record.get("evidence_status") not in CANDIDATE_EVIDENCE_STATUSES:
            _error(errors, f"{prefix}.evidence_status", "evidence_status is unsupported")

        architecture = _as_mapping(record.get("architecture_summary"))
        for field in (
            "architecture_id",
            "architecture_family",
            "gpu_role",
            "fpga_role",
            "host_role",
            "dataflow_summary",
            "memory_interface",
            "synchronization_model",
        ):
            if not isinstance(architecture.get(field), str) or not architecture.get(field):
                _error(errors, f"{prefix}.architecture_summary.{field}", f"{field} must be a non-empty string")

        runs = _as_list(record.get("runtime_seconds_runs"))
        if not runs or not all(_is_number(value) and float(value) > 0 for value in runs):
            _error(errors, f"{prefix}.runtime_seconds_runs", "runtime runs must be positive numeric values")
        for field in (
            "runtime_seconds_mean",
            "runtime_seconds_std",
            "kernel_runtime_seconds_mean",
            "transfer_overhead_seconds",
            "workflow_overhead_seconds",
        ):
            if not _is_number(record.get(field)):
                _error(errors, f"{prefix}.{field}", f"{field} must be numeric")
        workflow_runtime = record.get("workflow_runtime_seconds_mean")
        if workflow_runtime is not None and not _is_number(workflow_runtime):
            _error(errors, f"{prefix}.workflow_runtime_seconds_mean", "workflow runtime must be numeric or null")
        if _is_number(workflow_runtime) and float(workflow_runtime) <= 0:
            _error(errors, f"{prefix}.workflow_runtime_seconds_mean", "workflow runtime must be positive")
        _validate_ci(
            _as_mapping(record.get("confidence_interval_95")),
            prefix=f"{prefix}.confidence_interval_95",
            mean=record.get("runtime_seconds_mean"),
            errors=errors,
        )
        resource = _as_mapping(record.get("resource"))
        if not isinstance(resource.get("resource_feasible"), bool):
            _error(errors, f"{prefix}.resource.resource_feasible", "resource_feasible must be boolean")
        if not isinstance(resource.get("timing_feasible"), bool):
            _error(errors, f"{prefix}.resource.timing_feasible", "timing_feasible must be boolean")
        for field in (
            "lut_utilization",
            "ff_utilization",
            "bram_utilization",
            "dsp_utilization",
            "hbm_port_utilization",
            "fmax_mhz",
        ):
            if not _is_number(resource.get(field)):
                _error(errors, f"{prefix}.resource.{field}", f"{field} must be numeric")
        for field in (
            "lut_utilization",
            "ff_utilization",
            "bram_utilization",
            "dsp_utilization",
            "hbm_port_utilization",
        ):
            if _is_number(resource.get(field)) and not (0.0 <= float(resource[field]) <= 1.0):
                _error(errors, f"{prefix}.resource.{field}", f"{field} must be in [0, 1]")
        if not isinstance(record.get("evidence_artifact_hash"), str) or not record.get("evidence_artifact_hash"):
            _error(errors, f"{prefix}.evidence_artifact_hash", "evidence_artifact_hash must be non-empty")
        if str(record.get("claim_boundary", "")) != CANDIDATE_RESULT_CLAIM_BOUNDARY:
            _error(errors, f"{prefix}.claim_boundary", "claim_boundary must match canonical candidate boundary")
        if (
            payload.get("results_are_real") is True
            and record.get("evidence_status") == "high_fidelity_estimate"
            and not isinstance(record.get("tool_provenance"), Mapping)
        ):
            _error(errors, f"{prefix}.tool_provenance", "high_fidelity_estimate claims require tool provenance")
        if payload.get("results_are_real") is True and record.get("evidence_status") == "high_fidelity_estimate":
            provenance = _as_mapping(record.get("tool_provenance"))
            for field in REQUIRED_HIGH_FIDELITY_PROVENANCE_FIELDS:
                if not isinstance(provenance.get(field), str) or not provenance.get(field):
                    _error(errors, f"{prefix}.tool_provenance.{field}", f"{field} must be a non-empty string")
        if payload.get("results_are_real") is True and record.get("evidence_status") == "fixture_example":
            _error(errors, f"{prefix}.evidence_status", "real candidate payloads must not contain fixture_example records")

    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "candidate_result_count": len([row for row in records if isinstance(row, Mapping)]),
        "results_are_real": payload.get("results_are_real") is True,
    }


def candidate_results_by_id(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Return candidate-result records by candidate_id."""

    return {
        str(record.get("candidate_id")): record
        for record in _as_list(payload.get("candidate_results"))
        if isinstance(record, Mapping) and isinstance(record.get("candidate_id"), str)
    }
