#!/usr/bin/env python3
"""Aggregation for QE-IC Layer-2 motif profiles."""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from dse_v2.profiling.qe_ic.motif_mapping import map_profile_event_to_motif
from dse_v2.profiling.qe_ic.schema import (
    CLAIM_BOUNDARY,
    QE_IC_MOTIF_PROFILE_SCHEMA_VERSION,
)
from dse_v2.profiling.qe_ic.source_registry import normalize_profile_sources


def _numeric(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _nonnegative_int(value: Any) -> int:
    number = _numeric(value)
    return int(number) if number >= 0 else 0


def _merge_gpu_baseline(records: list[Mapping[str, Any]], required: bool) -> dict[str, Any]:
    available_records = [
        record
        for record in records
        if isinstance(record, Mapping) and record.get("available") is True
    ]
    if not available_records:
        return {
            "required": required,
            "available": False,
            "speedup_vs_cpu": None,
            "gpu_utilization": None,
        }

    speedups = [
        float(record["speedup_vs_cpu"])
        for record in available_records
        if isinstance(record.get("speedup_vs_cpu"), int | float)
        and not isinstance(record.get("speedup_vs_cpu"), bool)
    ]
    utilizations = [
        float(record["gpu_utilization"])
        for record in available_records
        if isinstance(record.get("gpu_utilization"), int | float)
        and not isinstance(record.get("gpu_utilization"), bool)
    ]
    return {
        "required": required,
        "available": True,
        "speedup_vs_cpu": sum(speedups) / len(speedups) if speedups else None,
        "gpu_utilization": (
            sum(utilizations) / len(utilizations) if utilizations else None
        ),
    }


def _family_gpu_baseline_required(
    suite: Mapping[str, Any],
    family_id: str,
) -> bool:
    for family in suite.get("workload_families", []):
        if not isinstance(family, Mapping) or family.get("family_id") != family_id:
            continue
        contract = family.get("profiling_contract")
        if isinstance(contract, Mapping):
            return contract.get("gpu_baseline_required") is True
    return False


def _confidence_for(confidences: set[str]) -> str:
    mapped = {confidence for confidence in confidences if confidence != "none"}
    if not mapped:
        return "none"
    if len(mapped) == 1:
        return next(iter(mapped))
    return "medium"


def _source_event_payload(
    source: Mapping[str, Any],
    event: Mapping[str, Any],
    mapping: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "source_id": source.get("source_id"),
        "input_case": source.get("input_case"),
        "event_name": mapping.get("event_name"),
        "motif_id": mapping.get("motif_id"),
        "mapping_status": mapping.get("mapping_status"),
        "mapping_confidence": mapping.get("mapping_confidence"),
        "mapping_reason": mapping.get("mapping_reason"),
        "time_ms": _numeric(event.get("time_ms")),
        "memory_movement_bytes": _nonnegative_int(event.get("memory_movement_bytes")),
        "communication_bytes": _nonnegative_int(event.get("communication_bytes")),
        "parallel_axes": sorted(
            {
                axis
                for axis in event.get("parallel_axes", [])
                if isinstance(axis, str) and axis
            }
        ),
    }


def _build_family_target_group(
    suite: Mapping[str, Any],
    family_id: str,
    target: str,
    sources: list[Mapping[str, Any]],
) -> dict[str, Any]:
    profiled_cases = sorted(
        {
            str(source.get("input_case"))
            for source in sources
            if isinstance(source.get("input_case"), str) and source.get("input_case")
        }
    )
    source_ids = sorted(
        {
            str(source.get("source_id"))
            for source in sources
            if isinstance(source.get("source_id"), str) and source.get("source_id")
        }
    )
    baseline_records = [
        source.get("gpu_baseline")
        for source in sources
        if isinstance(source.get("gpu_baseline"), Mapping)
    ]
    total_time_ms = 0.0
    unmapped_time_ms = 0.0
    mapped_events: list[dict[str, Any]] = []
    motif_accumulators: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "time_ms": 0.0,
            "memory_movement_bytes": 0,
            "communication_bytes": 0,
            "parallel_axes": set(),
            "source_event_count": 0,
            "confidences": set(),
        }
    )

    for source in sources:
        for event in source.get("events", []):
            if not isinstance(event, Mapping):
                continue
            mapping = map_profile_event_to_motif(event, suite)
            event_payload = _source_event_payload(source, event, mapping)
            mapped_events.append(event_payload)
            event_time_ms = event_payload["time_ms"]
            total_time_ms += event_time_ms
            if mapping["mapping_status"] == "unmapped":
                unmapped_time_ms += event_time_ms
                continue
            motif_id = str(mapping["motif_id"])
            acc = motif_accumulators[motif_id]
            acc["time_ms"] += event_time_ms
            acc["memory_movement_bytes"] += event_payload["memory_movement_bytes"]
            acc["communication_bytes"] += event_payload["communication_bytes"]
            acc["parallel_axes"].update(event_payload["parallel_axes"])
            acc["source_event_count"] += 1
            acc["confidences"].add(str(mapping["mapping_confidence"]))

    motif_profiles: list[dict[str, Any]] = []
    for motif_id in sorted(motif_accumulators):
        acc = motif_accumulators[motif_id]
        motif_profiles.append(
            {
                "motif_id": motif_id,
                "time_ms": acc["time_ms"],
                "runtime_ratio": (
                    acc["time_ms"] / total_time_ms if total_time_ms > 0.0 else 0.0
                ),
                "memory_movement_bytes": acc["memory_movement_bytes"],
                "communication_bytes": acc["communication_bytes"],
                "parallel_axes": sorted(acc["parallel_axes"]),
                "source_event_count": acc["source_event_count"],
                "mapping_confidence": _confidence_for(acc["confidences"]),
            }
        )

    return {
        "workload_family_id": family_id,
        "target": target,
        "profiled_cases": profiled_cases,
        "source_ids": source_ids,
        "total_time_ms": total_time_ms,
        "unmapped_time_ms": unmapped_time_ms,
        "unmapped_time_ratio": (
            unmapped_time_ms / total_time_ms if total_time_ms > 0.0 else 0.0
        ),
        "gpu_baseline": _merge_gpu_baseline(
            baseline_records,
            _family_gpu_baseline_required(suite, family_id),
        ),
        "motif_profiles": motif_profiles,
        "mapped_events": sorted(
            mapped_events,
            key=lambda row: (
                str(row.get("source_id")),
                str(row.get("event_name")),
                str(row.get("motif_id")),
            ),
        ),
    }


def build_qe_ic_motif_profile(
    suite: Mapping[str, Any],
    profile_sources: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build Layer-2 motif profile from Layer-1 suite and profile sources."""

    normalized_sources, warnings = normalize_profile_sources(profile_sources)
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for source in normalized_sources:
        family_id = source.get("workload_family_id")
        target = source.get("target")
        if isinstance(family_id, str) and isinstance(target, str):
            grouped[(family_id, target)].append(source)

    family_target_profiles = [
        _build_family_target_group(suite, family_id, target, sources)
        for (family_id, target), sources in sorted(grouped.items())
    ]

    return {
        "schema_version": QE_IC_MOTIF_PROFILE_SCHEMA_VERSION,
        "suite_id": suite.get("suite_id"),
        "suite_schema_version": suite.get("schema_version"),
        "layer": "layer2_motif_profiling",
        "source_layer1_suite": {
            "suite_id": suite.get("suite_id"),
            "schema_version": suite.get("schema_version"),
            "workload_family_ids": [
                family.get("family_id")
                for family in suite.get("workload_families", [])
                if isinstance(family, Mapping)
            ],
            "motif_registry": copy.deepcopy(suite.get("motif_registry", {})),
        },
        "profile_source_count": len(normalized_sources),
        "profile_sources": copy.deepcopy(normalized_sources),
        "profile_source_warnings": warnings,
        "family_target_profiles": family_target_profiles,
        "claim_boundary": CLAIM_BOUNDARY,
    }

