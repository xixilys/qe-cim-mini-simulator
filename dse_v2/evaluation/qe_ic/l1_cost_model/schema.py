#!/usr/bin/env python3
"""Schema constants for QE-IC Layer-5A L1 cost-model results."""

from __future__ import annotations

QE_IC_L1_COST_MODEL_CONFIG_SCHEMA_VERSION = "dse.qe_ic.l1_cost_model_config.v1"
QE_IC_L1_COST_MODEL_RESULTS_SCHEMA_VERSION = "dse.qe_ic.l1_cost_model_results.v1"
QE_IC_L1_COST_MODEL_VALIDATION_SCHEMA_VERSION = "dse.qe_ic.l1_cost_model_validation.v1"
QE_IC_L1_COST_MODEL_MANIFEST_SCHEMA_VERSION = "dse.qe_ic.l1_cost_model_manifest.v1"

QE_IC_L1_COST_MODEL_RESULTS_ARTIFACT = "qe_ic_l1_cost_model_results.json"
QE_IC_L1_COST_MODEL_VALIDATION_ARTIFACT = "qe_ic_l1_cost_model_validation.json"
QE_IC_L1_COST_MODEL_MANIFEST_ARTIFACT = "qe_ic_l1_cost_model_manifest.json"
QE_IC_L1_COST_MODEL_README_ARTIFACT = "qe_ic_l1_cost_model_readme.md"

QE_IC_L1_COST_MODEL_ARTIFACTS = [
    QE_IC_L1_COST_MODEL_RESULTS_ARTIFACT,
    QE_IC_L1_COST_MODEL_VALIDATION_ARTIFACT,
    QE_IC_L1_COST_MODEL_MANIFEST_ARTIFACT,
    QE_IC_L1_COST_MODEL_README_ARTIFACT,
]

SOURCE_LAYER1_SUITE_ARTIFACT = "qe_ic_workload_suite.json"
SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT = "qe_ic_motif_profile.json"
SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT = "qe_ic_target_viability.json"
SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT = "qe_ic_candidate_plan.json"

LAYER_NAME = "layer5a_l1_cost_model_evaluation"
PRODUCER = "dse_v2.evaluation.qe_ic.l1_cost_model"

RESULT_STATUSES = {
    "completed_estimate",
    "failed_estimate",
}

CANDIDATE_TYPES = {
    "fpga_candidate",
    "hybrid_candidate",
}

TARGET_TYPES = {
    "fpga_only",
    "gpu_fpga_hybrid",
}

BOTTLENECK_CLASSES = {
    "compute",
    "memory",
    "communication",
    "transfer",
    "resource",
    "profile_quality",
    "unknown",
}

NEXT_FIDELITY_SUGGESTIONS = {
    "hold_for_more_profile",
    "promote_to_systemc_request",
    "promote_to_gem5_systemc_request",
    "promote_to_vivado_resource_request",
    "reject_before_high_fidelity",
}

REASON_CODE_REGISTRY = {
    "high_estimated_gain",
    "low_estimated_gain",
    "transfer_overhead_high",
    "transfer_overhead_low",
    "resource_pressure_high",
    "resource_pressure_low",
    "model_confidence_high",
    "model_confidence_low",
    "profile_quality_limited",
    "memory_bottleneck",
    "compute_bottleneck",
    "communication_bottleneck",
    "transfer_bottleneck",
    "resource_bottleneck",
    "hybrid_overlap_promising",
    "systemc_recommended",
    "gem5_systemc_recommended",
    "vivado_resource_check_recommended",
    "reject_before_high_fidelity",
    "insufficient_evidence",
    "hold_for_more_profile",
}

ESTIMATE_FIELDS = [
    "estimated_latency_ms",
    "estimated_speedup_vs_gpu_baseline",
    "estimated_net_gain_ratio",
    "estimated_transfer_overhead_ms",
    "estimated_compute_time_ms",
    "estimated_memory_time_ms",
    "estimated_communication_time_ms",
    "estimated_resource_pressure",
    "estimated_model_confidence",
]

RISK_FIELDS = [
    "overall_l1_risk",
    "model_uncertainty_risk",
    "resource_risk",
    "transfer_risk",
    "profile_quality_risk",
]

FORBIDDEN_EXECUTION_FIELDS = {
    "systemc_result",
    "gem5_result",
    "vivado_result",
    "dc_result",
    "qe_result",
    "rtl_result",
    "hls_result",
    "measured_latency",
    "measured_power",
    "measured_area",
    "final_performance_claim",
    "hardware_implementation_results",
    "execution_results",
}

CLAIM_BOUNDARY = (
    "This artifact contains deterministic L1 analytical cost-model estimates "
    "only. It does not contain SystemC/gem5/Vivado/DC/QE execution results, "
    "hardware implementation results, or final performance claims."
)

RESULT_CLAIM_BOUNDARY = (
    "This is a deterministic L1 analytical estimate only. It is not measured "
    "SystemC/gem5/Vivado/QE performance."
)

MANIFEST_CLAIM_BOUNDARY = (
    "This manifest registers Layer-5A analytical estimate artifacts only. "
    "It is not high-fidelity execution evidence or final claim adjudication."
)

CONFIG_CLAIM_BOUNDARY = (
    "This config controls deterministic L1 analytical estimates only. It does "
    "not permit external execution or final performance claims."
)

DOWNSTREAM_CONSUMERS = [
    "layer5b_systemc_request_builder",
    "layer5c_gem5_systemc_request_builder",
    "layer5d_vivado_request_builder",
    "layer6_feedback_update",
]

