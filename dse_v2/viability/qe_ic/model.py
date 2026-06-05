#!/usr/bin/env python3
"""Deterministic QE-IC Layer-3 target viability scoring model."""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping
from typing import Any

from dse_v2.viability.qe_ic.schema import (
    CLAIM_BOUNDARY,
    QE_IC_TARGET_VIABILITY_SCHEMA_VERSION,
    SOURCE_LAYER1_SUITE_ARTIFACT,
    SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
    TARGET_CONFIG_THRESHOLD_DEFAULTS,
)


CATEGORY_PRIORS: dict[str, dict[str, float]] = {
    "spectral_transform": {
        "streaming_score": 0.75,
        "fpga_resource_risk": 0.45,
        "fpga_removable_fraction": 0.35,
        "hybrid_removable_fraction": 0.30,
    },
    "operator_application": {
        "streaming_score": 0.70,
        "fpga_resource_risk": 0.50,
        "fpga_removable_fraction": 0.30,
        "hybrid_removable_fraction": 0.25,
    },
    "communication": {
        "streaming_score": 0.65,
        "fpga_resource_risk": 0.35,
        "fpga_removable_fraction": 0.25,
        "hybrid_removable_fraction": 0.35,
    },
    "memory": {
        "streaming_score": 0.55,
        "fpga_resource_risk": 0.55,
        "fpga_removable_fraction": 0.20,
        "hybrid_removable_fraction": 0.25,
    },
    "io_memory": {
        "streaming_score": 0.45,
        "fpga_resource_risk": 0.50,
        "fpga_removable_fraction": 0.10,
        "hybrid_removable_fraction": 0.20,
    },
    "linear_algebra": {
        "streaming_score": 0.25,
        "fpga_resource_risk": 0.70,
        "fpga_removable_fraction": 0.10,
        "hybrid_removable_fraction": 0.05,
    },
    "transport": {
        "streaming_score": 0.35,
        "fpga_resource_risk": 0.75,
        "fpga_removable_fraction": 0.12,
        "hybrid_removable_fraction": 0.12,
    },
    "response_solve": {
        "streaming_score": 0.45,
        "fpga_resource_risk": 0.60,
        "fpga_removable_fraction": 0.15,
        "hybrid_removable_fraction": 0.18,
    },
    "workflow_parallelism": {
        "streaming_score": 0.30,
        "fpga_resource_risk": 0.40,
        "fpga_removable_fraction": 0.05,
        "hybrid_removable_fraction": 0.10,
    },
    "structure_scale": {
        "streaming_score": 0.25,
        "fpga_resource_risk": 0.70,
        "fpga_removable_fraction": 0.05,
        "hybrid_removable_fraction": 0.05,
    },
    "post_processing": {
        "streaming_score": 0.40,
        "fpga_resource_risk": 0.45,
        "fpga_removable_fraction": 0.15,
        "hybrid_removable_fraction": 0.18,
    },
    "default": {
        "streaming_score": 0.30,
        "fpga_resource_risk": 0.60,
        "fpga_removable_fraction": 0.10,
        "hybrid_removable_fraction": 0.10,
    },
}


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp value into a closed interval."""

    return max(lo, min(hi, value))


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def _thresholds(config: Mapping[str, Any]) -> dict[str, float]:
    thresholds = dict(TARGET_CONFIG_THRESHOLD_DEFAULTS)
    raw = config.get("thresholds")
    if isinstance(raw, Mapping):
        for key, default in TARGET_CONFIG_THRESHOLD_DEFAULTS.items():
            thresholds[key] = _num(raw.get(key), default)
    return thresholds


def _motif_registry(suite: Mapping[str, Any]) -> Mapping[str, Any]:
    registry = suite.get("motif_registry")
    return registry if isinstance(registry, Mapping) else {}


def _category_for(motif_id: str, suite: Mapping[str, Any]) -> str:
    motif = _motif_registry(suite).get(motif_id)
    if isinstance(motif, Mapping) and isinstance(motif.get("category"), str):
        return motif["category"]
    return "default"


def _profile_quality_risk(
    *,
    unmapped_time_ratio: float,
    mapping_confidence: str,
    max_unmapped_time_ratio: float,
) -> float:
    if unmapped_time_ratio > max_unmapped_time_ratio:
        return 1.0
    if mapping_confidence == "high":
        return 0.1
    if mapping_confidence == "medium":
        return 0.35
    return 0.75


def _gpu_dominance_risk(
    *,
    gpu_utilization: float,
    category: str,
    strong_gpu_utilization: float,
) -> float:
    if gpu_utilization >= strong_gpu_utilization and category in {
        "linear_algebra",
        "transport",
        "spectral_transform",
    }:
        return 0.75
    if gpu_utilization >= strong_gpu_utilization:
        return 0.35
    return 0.10


def _transfer_time_ms(bytes_moved: float, bandwidth_gbps: float) -> float:
    if bandwidth_gbps <= 0:
        return 0.0
    return bytes_moved / (bandwidth_gbps * 1e9) * 1000.0


def _reason_codes(
    *,
    target_type: str,
    category: str,
    runtime_ratio: float,
    runtime_importance: float,
    gpu_utilization: float,
    streaming_score: float,
    net_gain_ratio: float,
    transfer_overhead_risk: float,
    fpga_resource_risk: float,
    profile_quality_risk: float,
    unmapped_time_ratio: float,
    thresholds: Mapping[str, float],
) -> list[str]:
    codes: set[str] = {"gpu_baseline_present"}
    if gpu_utilization >= thresholds["strong_gpu_utilization"]:
        codes.add("gpu_baseline_strong")
    else:
        codes.add("gpu_utilization_low")
    if runtime_ratio >= thresholds["high_runtime_ratio"]:
        codes.add("high_runtime_motif")
    else:
        codes.add("low_runtime_motif")
    if streaming_score >= 0.60:
        codes.add("streaming_friendly")
    if category in {"linear_algebra", "transport", "spectral_transform"} and gpu_utilization >= thresholds["strong_gpu_utilization"]:
        codes.add("dense_gpu_dominant")
    if category in {"memory", "io_memory"}:
        codes.add("memory_bound")
    if category == "communication":
        codes.add("communication_bound")
    if transfer_overhead_risk >= 0.50:
        codes.add("transfer_overhead_risk")
    if fpga_resource_risk >= 0.60:
        codes.add("fpga_resource_risk")
    if target_type == "gpu_fpga_hybrid" and net_gain_ratio >= thresholds["min_hybrid_gain_ratio_maybe"]:
        codes.add("hybrid_overlap_possible")
    if target_type == "gpu_fpga_hybrid" and net_gain_ratio < thresholds["min_hybrid_gain_ratio_maybe"]:
        codes.add("hybrid_upper_bound_too_low")
    if target_type == "fpga_only" and net_gain_ratio < 0.03:
        codes.add("fpga_upper_bound_too_low")
    if profile_quality_risk >= 0.50:
        codes.add("profile_quality_risk")
    if unmapped_time_ratio > thresholds["max_unmapped_time_ratio"]:
        codes.add("unmapped_profile_too_high")
    if profile_quality_risk >= 0.75 or runtime_importance <= 0.05:
        codes.add("insufficient_profile_evidence")
    return sorted(codes)


def _build_record(
    *,
    suite: Mapping[str, Any],
    family_group: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
    target: Mapping[str, Any],
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    motif_id = str(motif_profile.get("motif_id", ""))
    target_type = str(target.get("target_type", ""))
    category = _category_for(motif_id, suite)
    priors = CATEGORY_PRIORS.get(category, CATEGORY_PRIORS["default"])

    runtime_ratio = _num(motif_profile.get("runtime_ratio"))
    motif_time_ms = _num(motif_profile.get("time_ms"))
    family_total_time_ms = _num(family_group.get("total_time_ms"))
    memory_movement_bytes = _num(motif_profile.get("memory_movement_bytes"))
    communication_bytes = _num(motif_profile.get("communication_bytes"))
    source_event_count = _num(motif_profile.get("source_event_count"))
    unmapped_time_ratio = _num(family_group.get("unmapped_time_ratio"))
    baseline = family_group.get("gpu_baseline") if isinstance(family_group.get("gpu_baseline"), Mapping) else {}
    gpu_utilization = _num(baseline.get("gpu_utilization")) if isinstance(baseline, Mapping) else 0.0

    runtime_importance = clamp(runtime_ratio / thresholds["high_runtime_ratio"]) if thresholds["high_runtime_ratio"] else 0.0
    gpu_headroom = clamp(1.0 - gpu_utilization)
    profile_quality_risk = _profile_quality_risk(
        unmapped_time_ratio=unmapped_time_ratio,
        mapping_confidence=str(motif_profile.get("mapping_confidence", "")),
        max_unmapped_time_ratio=thresholds["max_unmapped_time_ratio"],
    )
    gpu_dominance_risk = _gpu_dominance_risk(
        gpu_utilization=gpu_utilization,
        category=category,
        strong_gpu_utilization=thresholds["strong_gpu_utilization"],
    )

    estimated_transfer_time_ms = 0.0
    estimated_sync_time_ms = 0.0
    estimated_removable_time_ms = 0.0
    estimated_net_gain_ms = 0.0
    estimated_net_gain_ratio = 0.0
    fpga_resource_risk = 0.0
    transfer_overhead_risk = 0.0

    if target_type == "gpu_only":
        decision = "baseline"
        viability_score = clamp(
            0.45 * gpu_utilization
            + 0.30 * runtime_importance
            + 0.25 * (1.0 - profile_quality_risk)
        )
        fpga_resource_risk = 0.0
    elif target_type == "fpga_only":
        fpga = target.get("fpga") if isinstance(target.get("fpga"), Mapping) else {}
        bandwidth = _num(fpga.get("memory_bandwidth_gbps")) if isinstance(fpga, Mapping) else 0.0
        estimated_transfer_time_ms = _transfer_time_ms(memory_movement_bytes, bandwidth)
        estimated_sync_time_ms = _num(fpga.get("sync_overhead_us")) * source_event_count / 1000.0 if isinstance(fpga, Mapping) else 0.0
        estimated_removable_time_ms = motif_time_ms * priors["fpga_removable_fraction"]
        estimated_net_gain_ms = estimated_removable_time_ms - estimated_transfer_time_ms - estimated_sync_time_ms
        estimated_net_gain_ratio = estimated_net_gain_ms / family_total_time_ms if family_total_time_ms > 0 else 0.0
        transfer_overhead_risk = clamp((estimated_transfer_time_ms + estimated_sync_time_ms) / motif_time_ms) if motif_time_ms > 0 else 1.0
        fpga_resource_risk = clamp(priors["fpga_resource_risk"] * (1.0 + (1.0 - _num(fpga.get("logic_budget_score"), 0.5))))
        viability_score = clamp(
            0.30 * runtime_importance
            + 0.30 * priors["streaming_score"]
            + 0.20 * gpu_headroom
            + 0.20 * clamp(max(estimated_net_gain_ratio, 0.0) / 0.10)
            - 0.25 * gpu_dominance_risk
            - 0.20 * transfer_overhead_risk
            - 0.20 * fpga_resource_risk
            - 0.20 * profile_quality_risk
        )
        if viability_score >= thresholds["viable_score"] and estimated_net_gain_ratio >= 0.10:
            decision = "viable"
        elif viability_score >= thresholds["maybe_score"] or estimated_net_gain_ratio >= 0.03:
            decision = "maybe"
        else:
            decision = "reject"
    else:
        interconnect = target.get("interconnect") if isinstance(target.get("interconnect"), Mapping) else {}
        fpga = target.get("fpga") if isinstance(target.get("fpga"), Mapping) else {}
        bandwidth = _num(interconnect.get("bandwidth_gbps")) if isinstance(interconnect, Mapping) else 0.0
        estimated_transfer_time_ms = _transfer_time_ms(memory_movement_bytes + communication_bytes, bandwidth)
        estimated_sync_time_ms = (
            (_num(fpga.get("sync_overhead_us")) if isinstance(fpga, Mapping) else 0.0)
            + (_num(interconnect.get("latency_us")) if isinstance(interconnect, Mapping) else 0.0)
        ) * source_event_count / 1000.0
        estimated_removable_time_ms = motif_time_ms * priors["hybrid_removable_fraction"]
        estimated_net_gain_ms = estimated_removable_time_ms - estimated_transfer_time_ms - estimated_sync_time_ms
        estimated_net_gain_ratio = estimated_net_gain_ms / family_total_time_ms if family_total_time_ms > 0 else 0.0
        transfer_overhead_risk = clamp((estimated_transfer_time_ms + estimated_sync_time_ms) / motif_time_ms) if motif_time_ms > 0 else 1.0
        fpga_resource_risk = clamp(priors["fpga_resource_risk"] * 0.75)
        viability_score = clamp(
            0.25 * runtime_importance
            + 0.25 * priors["streaming_score"]
            + 0.25 * gpu_headroom
            + 0.25 * clamp(max(estimated_net_gain_ratio, 0.0) / 0.10)
            - 0.30 * transfer_overhead_risk
            - 0.20 * profile_quality_risk
        )
        if (
            viability_score >= thresholds["viable_score"]
            and estimated_net_gain_ratio >= thresholds["min_hybrid_gain_ratio_viable"]
        ):
            decision = "viable"
        elif (
            viability_score >= thresholds["maybe_score"]
            or estimated_net_gain_ratio >= thresholds["min_hybrid_gain_ratio_maybe"]
        ):
            decision = "maybe"
        else:
            decision = "reject"

    overall_risk_score = clamp(
        (
            gpu_dominance_risk
            + transfer_overhead_risk
            + fpga_resource_risk
            + profile_quality_risk
        )
        / 4.0
    )
    reason_codes = _reason_codes(
        target_type=target_type,
        category=category,
        runtime_ratio=runtime_ratio,
        runtime_importance=runtime_importance,
        gpu_utilization=gpu_utilization,
        streaming_score=priors["streaming_score"],
        net_gain_ratio=estimated_net_gain_ratio,
        transfer_overhead_risk=transfer_overhead_risk,
        fpga_resource_risk=fpga_resource_risk,
        profile_quality_risk=profile_quality_risk,
        unmapped_time_ratio=unmapped_time_ratio,
        thresholds=thresholds,
    )

    return {
        "workload_family_id": family_group.get("workload_family_id"),
        "motif_id": motif_id,
        "source_profile_target": family_group.get("target"),
        "target_id": target.get("target_id"),
        "target_type": target_type,
        "decision": decision,
        "viability_score": viability_score,
        "upper_bound": {
            "family_total_time_ms": family_total_time_ms,
            "motif_time_ms": motif_time_ms,
            "runtime_ratio": runtime_ratio,
            "estimated_transfer_time_ms": estimated_transfer_time_ms,
            "estimated_sync_time_ms": estimated_sync_time_ms,
            "estimated_removable_time_ms": estimated_removable_time_ms,
            "estimated_net_gain_ms": estimated_net_gain_ms,
            "estimated_net_gain_ratio": estimated_net_gain_ratio,
        },
        "risk": {
            "overall_risk_score": overall_risk_score,
            "gpu_dominance_risk": gpu_dominance_risk,
            "transfer_overhead_risk": transfer_overhead_risk,
            "fpga_resource_risk": fpga_resource_risk,
            "profile_quality_risk": profile_quality_risk,
        },
        "reason_codes": reason_codes,
        "evidence_inputs": {
            "runtime_ratio": runtime_ratio,
            "time_ms": motif_time_ms,
            "memory_movement_bytes": memory_movement_bytes,
            "communication_bytes": communication_bytes,
            "gpu_utilization": gpu_utilization,
            "unmapped_time_ratio": unmapped_time_ratio,
            "mapping_confidence": motif_profile.get("mapping_confidence"),
        },
    }


def _summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    decisions = Counter(str(record.get("decision")) for record in records)
    by_target_type: dict[str, dict[str, int]] = {}
    for record in records:
        target_type = str(record.get("target_type"))
        bucket = by_target_type.setdefault(
            target_type,
            {
                "record_count": 0,
                "baseline_count": 0,
                "viable_count": 0,
                "maybe_count": 0,
                "reject_count": 0,
            },
        )
        bucket["record_count"] += 1
        decision = str(record.get("decision"))
        if decision in {"baseline", "viable", "maybe", "reject"}:
            bucket[f"{decision}_count"] += 1
    return {
        "record_count": len(records),
        "viable_count": decisions.get("viable", 0),
        "maybe_count": decisions.get("maybe", 0),
        "reject_count": decisions.get("reject", 0),
        "baseline_count": decisions.get("baseline", 0),
        "by_target_type": by_target_type,
    }


def build_qe_ic_target_viability(
    suite: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
    target_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Build Layer-3 target viability estimates from Layer-1, Layer-2, and target config."""

    thresholds = _thresholds(target_config)
    targets = [
        target
        for target in target_config.get("targets", [])
        if isinstance(target, Mapping)
    ]
    records: list[dict[str, Any]] = []
    for group in motif_profile.get("family_target_profiles", []):
        if not isinstance(group, Mapping):
            continue
        for motif in group.get("motif_profiles", []):
            if not isinstance(motif, Mapping):
                continue
            for target in targets:
                records.append(
                    _build_record(
                        suite=suite,
                        family_group=group,
                        motif_profile=motif,
                        target=target,
                        thresholds=thresholds,
                    )
                )

    return {
        "schema_version": QE_IC_TARGET_VIABILITY_SCHEMA_VERSION,
        "layer": "layer3_target_viability_test",
        "suite_id": suite.get("suite_id"),
        "source_layer1_suite_artifact": SOURCE_LAYER1_SUITE_ARTIFACT,
        "source_layer2_motif_profile_artifact": SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
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
        "source_layer2_motif_profile": {
            "schema_version": motif_profile.get("schema_version"),
            "suite_id": motif_profile.get("suite_id"),
        },
        "target_config": copy.deepcopy(target_config),
        "viability_records": records,
        "summary": _summary(records),
        "claim_boundary": CLAIM_BOUNDARY,
    }

