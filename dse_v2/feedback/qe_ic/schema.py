#!/usr/bin/env python3
"""Schema constants for QE-IC Layer-6 synthetic feedback calibration."""

from __future__ import annotations

QE_IC_FEEDBACK_CONFIG_SCHEMA_VERSION = "dse.qe_ic.feedback_config.v1"
QE_IC_SYNTHETIC_LABELS_SCHEMA_VERSION = "dse.qe_ic.synthetic_high_fidelity_labels.v1"
QE_IC_FEEDBACK_CALIBRATION_SCHEMA_VERSION = "dse.qe_ic.feedback_calibration.v1"
QE_IC_FEEDBACK_VALIDATION_SCHEMA_VERSION = "dse.qe_ic.feedback_validation.v1"
QE_IC_FEEDBACK_MANIFEST_SCHEMA_VERSION = "dse.qe_ic.feedback_manifest.v1"

QE_IC_FEEDBACK_CALIBRATION_ARTIFACT = "qe_ic_feedback_calibration.json"
QE_IC_FEEDBACK_VALIDATION_ARTIFACT = "qe_ic_feedback_validation.json"
QE_IC_FEEDBACK_MANIFEST_ARTIFACT = "qe_ic_feedback_manifest.json"
QE_IC_FEEDBACK_README_ARTIFACT = "qe_ic_feedback_readme.md"

QE_IC_FEEDBACK_ARTIFACTS = [
    QE_IC_FEEDBACK_CALIBRATION_ARTIFACT,
    QE_IC_FEEDBACK_VALIDATION_ARTIFACT,
    QE_IC_FEEDBACK_MANIFEST_ARTIFACT,
    QE_IC_FEEDBACK_README_ARTIFACT,
]

SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT = "qe_ic_candidate_plan.json"
SOURCE_LAYER5A_L1_RESULTS_ARTIFACT = "qe_ic_l1_cost_model_results.json"

LAYER_NAME = "layer6_feedback_calibration"
PRODUCER = "dse_v2.feedback.qe_ic"
POLICY_VERSION = "qe_ic_layer6_heuristic_policy_v1"

SYNTHETIC_LABELS = {
    "useful",
    "false_promotion",
    "false_rejection",
    "resource_invalid",
    "overhead_invalid",
    "inconclusive",
}

FALSE_PROMOTION_LABELS = {
    "false_promotion",
    "resource_invalid",
    "overhead_invalid",
}

WASTED_BUDGET_LABELS = FALSE_PROMOTION_LABELS | {"inconclusive"}

FORBIDDEN_FIELDS = {
    "hardware_proven",
    "measured_latency",
    "measured_power",
    "measured_area",
    "systemc_result",
    "gem5_result",
    "vivado_result",
    "dc_result",
    "qe_result",
    "rtl_result",
    "hls_result",
    "final_performance_claim",
    "superiority_claim",
    "fpga_superiority_claim",
    "gpu_fpga_superiority_claim",
    "hybrid_superiority_claim",
}

CLAIM_BOUNDARY = (
    "This artifact contains synthetic replay feedback calibration only. It is "
    "not measured hardware execution evidence and does not prove final performance."
)

CONFIG_CLAIM_BOUNDARY = (
    "Layer-6 feedback config controls synthetic replay calibration only. It "
    "does not request SystemC/gem5/Vivado/DC/QE execution, measured hardware "
    "performance, or final performance claims."
)

MANIFEST_CLAIM_BOUNDARY = (
    "This manifest registers QE-IC Layer-6 synthetic feedback calibration "
    "artifacts only. It is not measured execution evidence or final claim "
    "adjudication."
)

STOPPING_CONDITIONS = [
    "max_rounds_reached",
    "high_fidelity_synthetic_label_budget_exhausted",
    "no_new_useful_candidate_for_n_rounds",
    "false_promotion_rate_below_target_threshold",
    "expected_improvement_below_threshold",
    "top_k_useful_count_target_reached",
]
