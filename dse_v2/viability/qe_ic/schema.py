#!/usr/bin/env python3
"""Schema and artifact constants for QE-IC Layer-3 target viability."""

from __future__ import annotations

QE_IC_TARGET_CONFIG_SCHEMA_VERSION = "dse.qe_ic.target_config.v1"
QE_IC_TARGET_VIABILITY_SCHEMA_VERSION = "dse.qe_ic.target_viability.v1"
QE_IC_TARGET_VIABILITY_VALIDATION_SCHEMA_VERSION = "dse.qe_ic.target_viability_validation.v1"
QE_IC_TARGET_VIABILITY_MANIFEST_SCHEMA_VERSION = "dse.qe_ic.target_viability_manifest.v1"

QE_IC_TARGET_VIABILITY_ARTIFACT = "qe_ic_target_viability.json"
QE_IC_TARGET_VIABILITY_VALIDATION_ARTIFACT = "qe_ic_target_viability_validation.json"
QE_IC_TARGET_VIABILITY_MANIFEST_ARTIFACT = "qe_ic_target_viability_manifest.json"
QE_IC_TARGET_VIABILITY_README_ARTIFACT = "qe_ic_target_viability_readme.md"

QE_IC_TARGET_VIABILITY_ARTIFACTS = [
    QE_IC_TARGET_VIABILITY_ARTIFACT,
    QE_IC_TARGET_VIABILITY_VALIDATION_ARTIFACT,
    QE_IC_TARGET_VIABILITY_MANIFEST_ARTIFACT,
    QE_IC_TARGET_VIABILITY_README_ARTIFACT,
]

SOURCE_LAYER1_SUITE_ARTIFACT = "qe_ic_workload_suite.json"
SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT = "qe_ic_motif_profile.json"

TARGET_TYPES = {
    "gpu_only",
    "fpga_only",
    "gpu_fpga_hybrid",
}

DECISIONS = {
    "baseline",
    "reject",
    "maybe",
    "viable",
}

REASON_CODE_REGISTRY = {
    "gpu_baseline_present",
    "gpu_baseline_strong",
    "gpu_utilization_low",
    "high_runtime_motif",
    "low_runtime_motif",
    "streaming_friendly",
    "dense_gpu_dominant",
    "memory_bound",
    "communication_bound",
    "transfer_overhead_risk",
    "fpga_resource_risk",
    "hybrid_overlap_possible",
    "hybrid_upper_bound_too_low",
    "fpga_upper_bound_too_low",
    "profile_quality_risk",
    "unmapped_profile_too_high",
    "insufficient_profile_evidence",
}

CLAIM_BOUNDARY = (
    "This artifact contains target viability estimates only. It does not "
    "contain architecture candidates, promotion decisions, SystemC/gem5/Vivado "
    "requests, hardware implementation results, or final performance claims."
)

MANIFEST_CLAIM_BOUNDARY = (
    "This manifest registers Layer-3 target-viability artifacts only. It is not "
    "architecture generation, promotion, implementation evidence, or final claim "
    "adjudication."
)

DOWNSTREAM_CONSUMERS = [
    "layer4_candidate_generation",
    "promotion_policy",
]

UPPER_BOUND_FIELDS = [
    "family_total_time_ms",
    "motif_time_ms",
    "runtime_ratio",
    "estimated_transfer_time_ms",
    "estimated_sync_time_ms",
    "estimated_removable_time_ms",
    "estimated_net_gain_ms",
    "estimated_net_gain_ratio",
]

RISK_FIELDS = [
    "overall_risk_score",
    "gpu_dominance_risk",
    "transfer_overhead_risk",
    "fpga_resource_risk",
    "profile_quality_risk",
]

TARGET_CONFIG_THRESHOLD_DEFAULTS = {
    "viable_score": 0.65,
    "maybe_score": 0.35,
    "min_hybrid_gain_ratio_viable": 0.10,
    "min_hybrid_gain_ratio_maybe": 0.03,
    "max_unmapped_time_ratio": 0.15,
    "strong_gpu_utilization": 0.70,
    "high_runtime_ratio": 0.25,
}

