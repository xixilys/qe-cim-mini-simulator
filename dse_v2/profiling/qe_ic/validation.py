#!/usr/bin/env python3
"""Fail-closed validation for QE-IC Layer-2 motif profiles."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from dse_v2.profiling.qe_ic.schema import (
    CLAIM_BOUNDARY,
    EVENT_REQUIRED_FIELDS,
    PROFILE_SOURCE_REQUIRED_FIELDS,
    QE_IC_MOTIF_PROFILE_SCHEMA_VERSION,
    QE_IC_MOTIF_PROFILE_VALIDATION_SCHEMA_VERSION,
    SUPPORTED_PROFILE_SOURCE_TYPES,
)


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _warning(warnings: list[dict[str, str]], field: str, message: str) -> None:
    warnings.append({"field": field, "message": message})


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and value >= 0
    )


def _family_ids_from_layer1(profile: Mapping[str, Any]) -> list[str]:
    return [
        family_id
        for family_id in _as_list(_as_mapping(profile.get("source_layer1_suite")).get("workload_family_ids"))
        if isinstance(family_id, str) and family_id
    ]


def _motif_registry(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    return _as_mapping(_as_mapping(profile.get("source_layer1_suite")).get("motif_registry"))


def _validate_claim_boundary(
    boundary: str,
    *,
    errors: list[dict[str, str]],
) -> None:
    lowered = boundary.lower()
    required_terms = (
        "profiling",
        "architecture",
        "viability",
        "promotion",
        "performance claims",
    )
    if not boundary:
        _error(errors, "claim_boundary", "claim_boundary must be non-empty")
        return
    for term in required_terms:
        if term not in lowered:
            _error(errors, "claim_boundary", f"claim_boundary must mention absence of {term}")
    if "does not contain" not in lowered:
        _error(errors, "claim_boundary", "claim_boundary must be an explicit negative boundary")


def _validate_profile_source(
    source: Mapping[str, Any],
    *,
    index: int,
    family_ids: set[str],
    source_ids: list[str],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    prefix = f"profile_sources[{index}]"
    for field in PROFILE_SOURCE_REQUIRED_FIELDS:
        if field not in source:
            _error(errors, f"{prefix}.{field}", "required profile-source field is missing")

    source_id = source.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        _error(errors, f"{prefix}.source_id", "source_id must be a non-empty string")
    else:
        source_ids.append(source_id)

    family_id = source.get("workload_family_id")
    if not isinstance(family_id, str) or not family_id:
        _error(errors, f"{prefix}.workload_family_id", "workload_family_id must be a non-empty string")
    elif family_id not in family_ids:
        _error(errors, f"{prefix}.workload_family_id", f"unknown workload family {family_id!r}")

    for field in ("program", "target", "input_case", "raw_artifact_path", "raw_artifact_hash"):
        if not isinstance(source.get(field), str) or not source.get(field):
            _error(errors, f"{prefix}.{field}", f"{field} must be a non-empty string")

    source_type = source.get("profile_source_type")
    if source_type not in SUPPORTED_PROFILE_SOURCE_TYPES:
        _error(errors, f"{prefix}.profile_source_type", "profile_source_type is unsupported")
    elif source_type != "manual_profile_table":
        _warning(
            warnings,
            f"{prefix}.profile_source_type",
            "parser_not_implemented_for_source_type",
        )

    if source.get("trusted_for_layer2") is not True:
        _error(errors, f"{prefix}.trusted_for_layer2", "trusted_for_layer2 must be true for Layer-2 coverage")

    events = source.get("events")
    if not isinstance(events, list) or not events:
        _error(errors, f"{prefix}.events", "events must be a non-empty list")
        return

    for event_index, event in enumerate(events):
        event_prefix = f"{prefix}.events[{event_index}]"
        if not isinstance(event, Mapping):
            _error(errors, event_prefix, "event must be a mapping")
            continue
        for field in EVENT_REQUIRED_FIELDS:
            if field not in event:
                _error(errors, f"{event_prefix}.{field}", "required event field is missing")
        if not isinstance(event.get("event_name"), str) or not event.get("event_name"):
            _error(errors, f"{event_prefix}.event_name", "event_name must be a non-empty string")
        for field in ("time_ms", "memory_movement_bytes", "communication_bytes"):
            if not _is_nonnegative_number(event.get(field)):
                _error(errors, f"{event_prefix}.{field}", f"{field} must be >= 0")
        axes = event.get("parallel_axes")
        if not isinstance(axes, list) or not all(isinstance(axis, str) and axis for axis in axes):
            _error(errors, f"{event_prefix}.parallel_axes", "parallel_axes must contain non-empty strings")


def _validate_family_target_profile(
    group: Mapping[str, Any],
    *,
    index: int,
    family_ids: set[str],
    motif_registry: Mapping[str, Any],
    errors: list[dict[str, str]],
) -> float:
    prefix = f"family_target_profiles[{index}]"
    family_id = group.get("workload_family_id")
    if family_id not in family_ids:
        _error(errors, f"{prefix}.workload_family_id", f"unknown workload family {family_id!r}")

    if not isinstance(group.get("target"), str) or not group.get("target"):
        _error(errors, f"{prefix}.target", "target must be a non-empty string")

    for field in ("profiled_cases", "source_ids", "motif_profiles", "mapped_events"):
        if not isinstance(group.get(field), list):
            _error(errors, f"{prefix}.{field}", f"{field} must be a list")

    total_time_ms = group.get("total_time_ms")
    unmapped_time_ms = group.get("unmapped_time_ms")
    unmapped_ratio = group.get("unmapped_time_ratio")
    if not _is_nonnegative_number(total_time_ms):
        _error(errors, f"{prefix}.total_time_ms", "total_time_ms must be >= 0")
    if not _is_nonnegative_number(unmapped_time_ms):
        _error(errors, f"{prefix}.unmapped_time_ms", "unmapped_time_ms must be >= 0")
    if not _is_nonnegative_number(unmapped_ratio):
        _error(errors, f"{prefix}.unmapped_time_ratio", "unmapped_time_ratio must be >= 0")
        unmapped_ratio_value = 0.0
    else:
        unmapped_ratio_value = float(unmapped_ratio)
        if unmapped_ratio_value > 0.15:
            _error(errors, f"{prefix}.unmapped_time_ratio", "unmapped_time_ratio must be <= 0.15")

    baseline = _as_mapping(group.get("gpu_baseline"))
    if baseline.get("required") is True:
        if group.get("target") != "gpu_only":
            _error(errors, f"{prefix}.target", "gpu_baseline_required family must include target=gpu_only")
        if baseline.get("available") is not True:
            _error(errors, f"{prefix}.gpu_baseline.available", "required GPU baseline must be available")
    if baseline.get("available") is True:
        for field in ("speedup_vs_cpu", "gpu_utilization"):
            if not _is_nonnegative_number(baseline.get(field)):
                _error(errors, f"{prefix}.gpu_baseline.{field}", f"{field} must be >= 0")

    ratio_sum = unmapped_ratio_value
    for motif_index, motif_profile in enumerate(_as_list(group.get("motif_profiles"))):
        motif_prefix = f"{prefix}.motif_profiles[{motif_index}]"
        if not isinstance(motif_profile, Mapping):
            _error(errors, motif_prefix, "motif profile must be a mapping")
            continue
        motif_id = motif_profile.get("motif_id")
        if motif_id not in motif_registry:
            _error(errors, f"{motif_prefix}.motif_id", f"unknown motif {motif_id!r}")
        for field in ("time_ms", "runtime_ratio"):
            if not _is_nonnegative_number(motif_profile.get(field)):
                _error(errors, f"{motif_prefix}.{field}", f"{field} must be >= 0")
        if _is_nonnegative_number(motif_profile.get("runtime_ratio")):
            ratio_sum += float(motif_profile["runtime_ratio"])
        for field in ("memory_movement_bytes", "communication_bytes", "source_event_count"):
            if not _is_nonnegative_number(motif_profile.get(field)):
                _error(errors, f"{motif_prefix}.{field}", f"{field} must be >= 0")
        axes = motif_profile.get("parallel_axes")
        if not isinstance(axes, list) or axes != sorted(set(axes)):
            _error(errors, f"{motif_prefix}.parallel_axes", "parallel_axes must be deduplicated and sorted")
        if motif_profile.get("mapping_confidence") not in {"high", "medium", "none"}:
            _error(errors, f"{motif_prefix}.mapping_confidence", "mapping_confidence is invalid")

    if group.get("total_time_ms", 0) and not math.isclose(ratio_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
        _error(errors, f"{prefix}.runtime_ratio_sum", "mapped motif + unmapped runtime ratios must sum to 1.0")

    for event_index, event in enumerate(_as_list(group.get("mapped_events"))):
        event_prefix = f"{prefix}.mapped_events[{event_index}]"
        if not isinstance(event, Mapping):
            _error(errors, event_prefix, "mapped event must be a mapping")
            continue
        status = event.get("mapping_status")
        motif_id = event.get("motif_id")
        if status == "mapped" and motif_id not in motif_registry:
            _error(
                errors,
                f"{event_prefix}.motif_id",
                f"mapped event references unknown motif {motif_id!r}",
            )
        if status == "unmapped" and motif_id != "unmapped":
            _error(
                errors,
                f"{event_prefix}.motif_id",
                "unmapped event must use motif_id='unmapped'",
            )

    return unmapped_ratio_value


def validate_qe_ic_motif_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Validate motif profile contract fail-closed."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not isinstance(profile, Mapping):
        _error(errors, "$", "profile must be a mapping")
        return {
            "schema_version": QE_IC_MOTIF_PROFILE_VALIDATION_SCHEMA_VERSION,
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "family_profile_count": 0,
            "profile_source_count": 0,
            "unmapped_time_ratio_max": 0.0,
            "gpu_baseline_coverage_closed": False,
        }

    if profile.get("schema_version") != QE_IC_MOTIF_PROFILE_SCHEMA_VERSION:
        _error(errors, "schema_version", "schema_version is incorrect")

    source_layer1 = _as_mapping(profile.get("source_layer1_suite"))
    if profile.get("suite_id") != source_layer1.get("suite_id"):
        _error(errors, "suite_id", "suite_id must match source Layer-1 suite")

    family_ids = _family_ids_from_layer1(profile)
    family_id_set = set(family_ids)
    motif_registry = _motif_registry(profile)
    if not family_ids:
        _error(errors, "source_layer1_suite.workload_family_ids", "Layer-1 family list must be non-empty")
    if not motif_registry:
        _error(errors, "source_layer1_suite.motif_registry", "Layer-1 motif registry must be non-empty")

    profile_sources = _as_list(profile.get("profile_sources"))
    if not profile_sources:
        _error(errors, "profile_sources", "profile_sources must be non-empty")
    source_ids: list[str] = []
    for index, source in enumerate(profile_sources):
        if not isinstance(source, Mapping):
            _error(errors, f"profile_sources[{index}]", "profile source must be a mapping")
            continue
        _validate_profile_source(
            source,
            index=index,
            family_ids=family_id_set,
            source_ids=source_ids,
            errors=errors,
            warnings=warnings,
        )

    if len(source_ids) != len(set(source_ids)):
        _error(errors, "profile_sources.source_id", "source_id values must be unique")

    trusted_family_ids = {
        source.get("workload_family_id")
        for source in profile_sources
        if isinstance(source, Mapping) and source.get("trusted_for_layer2") is True
    }
    for family_id in family_ids:
        if family_id not in trusted_family_ids:
            _error(errors, f"profile_sources.{family_id}", "first-version family lacks trusted profile source")

    family_target_profiles = _as_list(profile.get("family_target_profiles"))
    if not family_target_profiles:
        _error(errors, "family_target_profiles", "family_target_profiles must be non-empty")

    unmapped_ratios: list[float] = []
    gpu_baseline_coverage_closed = True
    covered_gpu_families: set[str] = set()
    for index, group in enumerate(family_target_profiles):
        if not isinstance(group, Mapping):
            _error(errors, f"family_target_profiles[{index}]", "family-target profile must be a mapping")
            continue
        unmapped_ratios.append(
            _validate_family_target_profile(
                group,
                index=index,
                family_ids=family_id_set,
                motif_registry=motif_registry,
                errors=errors,
            )
        )
        baseline = _as_mapping(group.get("gpu_baseline"))
        if baseline.get("required") is True:
            if group.get("target") == "gpu_only" and baseline.get("available") is True:
                covered_gpu_families.add(str(group.get("workload_family_id")))
            else:
                gpu_baseline_coverage_closed = False

    for family_id in family_ids:
        if family_id not in covered_gpu_families:
            gpu_baseline_coverage_closed = False
            _error(errors, f"family_target_profiles.{family_id}.gpu_baseline", "gpu_baseline_required family lacks target=gpu_only with available baseline")

    _validate_claim_boundary(str(profile.get("claim_boundary", "")), errors=errors)
    if profile.get("claim_boundary") != CLAIM_BOUNDARY:
        _warning(warnings, "claim_boundary", "claim_boundary differs from canonical Layer-2 wording")

    for forbidden_field in (
        "architecture_candidates",
        "target_viability",
        "promotion_decisions",
        "hardware_implementation_results",
        "final_performance_claims",
    ):
        if forbidden_field in profile:
            _error(errors, forbidden_field, "Layer-2 profile must not contain architecture, viability, promotion, hardware, or final-claim fields")

    profile_source_warnings = _as_list(profile.get("profile_source_warnings"))
    for warning in profile_source_warnings:
        if isinstance(warning, Mapping):
            _warning(
                warnings,
                str(warning.get("field", "profile_source_warnings")),
                str(warning.get("message", "")),
            )

    status = "passed" if not errors else "failed"
    return {
        "schema_version": QE_IC_MOTIF_PROFILE_VALIDATION_SCHEMA_VERSION,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "family_profile_count": len(family_target_profiles),
        "profile_source_count": len(profile_sources),
        "unmapped_time_ratio_max": max(unmapped_ratios) if unmapped_ratios else 0.0,
        "gpu_baseline_coverage_closed": gpu_baseline_coverage_closed,
    }
