#!/usr/bin/env python3
"""Target-platform config validation for QE-IC Layer-3 viability."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dse_v2.viability.qe_ic.schema import (
    QE_IC_TARGET_CONFIG_SCHEMA_VERSION,
    TARGET_CONFIG_THRESHOLD_DEFAULTS,
    TARGET_TYPES,
)


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _is_positive_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and value > 0
    )


def _is_nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and value >= 0
    )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _validate_gpu(
    gpu: Mapping[str, Any],
    *,
    field: str,
    errors: list[dict[str, str]],
) -> None:
    if not isinstance(gpu.get("name"), str) or not gpu.get("name"):
        _error(errors, f"{field}.name", "GPU name must be a non-empty string")
    if not _is_positive_number(gpu.get("memory_bandwidth_gbps")):
        _error(errors, f"{field}.memory_bandwidth_gbps", "GPU memory bandwidth must be > 0")
    if not _is_nonnegative_number(gpu.get("sync_overhead_us")):
        _error(errors, f"{field}.sync_overhead_us", "GPU sync overhead must be >= 0")


def _validate_fpga(
    fpga: Mapping[str, Any],
    *,
    field: str,
    errors: list[dict[str, str]],
) -> None:
    if not isinstance(fpga.get("name"), str) or not fpga.get("name"):
        _error(errors, f"{field}.name", "FPGA name must be a non-empty string")
    if not _is_positive_number(fpga.get("memory_bandwidth_gbps")):
        _error(errors, f"{field}.memory_bandwidth_gbps", "FPGA memory bandwidth must be > 0")
    if not _is_nonnegative_number(fpga.get("sync_overhead_us")):
        _error(errors, f"{field}.sync_overhead_us", "FPGA sync overhead must be >= 0")
    if not _is_nonnegative_number(fpga.get("logic_budget_score")) or fpga.get("logic_budget_score", 0) > 1:
        _error(errors, f"{field}.logic_budget_score", "FPGA logic_budget_score must be in [0, 1]")


def _validate_interconnect(
    interconnect: Mapping[str, Any],
    *,
    field: str,
    errors: list[dict[str, str]],
) -> None:
    if not isinstance(interconnect.get("type"), str) or not interconnect.get("type"):
        _error(errors, f"{field}.type", "interconnect type must be a non-empty string")
    if not _is_positive_number(interconnect.get("bandwidth_gbps")):
        _error(errors, f"{field}.bandwidth_gbps", "interconnect bandwidth must be > 0")
    if not _is_nonnegative_number(interconnect.get("latency_us")):
        _error(errors, f"{field}.latency_us", "interconnect latency must be >= 0")


def validate_qe_ic_target_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate target config fixture fail-closed."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(config, Mapping):
        _error(errors, "$", "target_config must be a mapping")
        return {
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "target_count": 0,
        }

    if config.get("schema_version") != QE_IC_TARGET_CONFIG_SCHEMA_VERSION:
        _error(errors, "schema_version", "target_config schema_version is incorrect")

    targets = config.get("targets")
    if not isinstance(targets, list) or not targets:
        _error(errors, "targets", "targets must be a non-empty list")
        targets = []

    target_ids: list[str] = []
    for index, target in enumerate(targets):
        prefix = f"targets[{index}]"
        if not isinstance(target, Mapping):
            _error(errors, prefix, "target must be a mapping")
            continue
        target_id = target.get("target_id")
        target_type = target.get("target_type")
        if not isinstance(target_id, str) or not target_id:
            _error(errors, f"{prefix}.target_id", "target_id must be a non-empty string")
        else:
            target_ids.append(target_id)
        if target_type not in TARGET_TYPES:
            _error(errors, f"{prefix}.target_type", "target_type is unsupported")
            continue
        if target_type == "gpu_only":
            _validate_gpu(_as_mapping(target.get("gpu")), field=f"{prefix}.gpu", errors=errors)
        elif target_type == "fpga_only":
            _validate_fpga(_as_mapping(target.get("fpga")), field=f"{prefix}.fpga", errors=errors)
        elif target_type == "gpu_fpga_hybrid":
            _validate_gpu(_as_mapping(target.get("gpu")), field=f"{prefix}.gpu", errors=errors)
            _validate_fpga(_as_mapping(target.get("fpga")), field=f"{prefix}.fpga", errors=errors)
            _validate_interconnect(
                _as_mapping(target.get("interconnect")),
                field=f"{prefix}.interconnect",
                errors=errors,
            )

    if len(target_ids) != len(set(target_ids)):
        _error(errors, "targets.target_id", "target_id values must be unique")

    thresholds = _as_mapping(config.get("thresholds"))
    for key in TARGET_CONFIG_THRESHOLD_DEFAULTS:
        value = thresholds.get(key)
        if not _is_nonnegative_number(value):
            _error(errors, f"thresholds.{key}", f"{key} must be >= 0")
    for key in ("viable_score", "maybe_score", "strong_gpu_utilization", "high_runtime_ratio"):
        value = thresholds.get(key)
        if _is_nonnegative_number(value) and value > 1.0:
            _error(errors, f"thresholds.{key}", f"{key} must be <= 1")

    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "target_count": len(targets),
    }

