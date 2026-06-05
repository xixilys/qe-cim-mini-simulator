#!/usr/bin/env python3
"""Schema constants for the QE-IC closed-loop DSE campaign."""

from __future__ import annotations

QE_IC_CLOSED_LOOP_CAMPAIGN_CONFIG_SCHEMA_VERSION = "dse.qe_ic.closed_loop_dse_campaign_config.v1"
QE_IC_CLOSED_LOOP_RESULTS_SCHEMA_VERSION = "dse.qe_ic.closed_loop_dse_results.v1"
QE_IC_CLOSED_LOOP_VALIDATION_SCHEMA_VERSION = "dse.qe_ic.closed_loop_dse_validation.v1"
QE_IC_CLOSED_LOOP_MANIFEST_SCHEMA_VERSION = "dse.qe_ic.closed_loop_dse_manifest.v1"

QE_IC_CLOSED_LOOP_RESULTS_ARTIFACT = "qe_ic_closed_loop_dse_results.json"
QE_IC_CLOSED_LOOP_VALIDATION_ARTIFACT = "qe_ic_closed_loop_dse_validation.json"
QE_IC_CLOSED_LOOP_MANIFEST_ARTIFACT = "qe_ic_closed_loop_dse_manifest.json"
QE_IC_CLOSED_LOOP_README_ARTIFACT = "qe_ic_closed_loop_dse_readme.md"

QE_IC_CLOSED_LOOP_ARTIFACTS = [
    QE_IC_CLOSED_LOOP_RESULTS_ARTIFACT,
    QE_IC_CLOSED_LOOP_VALIDATION_ARTIFACT,
    QE_IC_CLOSED_LOOP_MANIFEST_ARTIFACT,
    QE_IC_CLOSED_LOOP_README_ARTIFACT,
]

LAYER_NAME = "system_qe_ic_closed_loop_dse_v1"
PRODUCER = "dse_v2.campaigns.qe_ic"

REQUIRED_LAYERS = [
    "layer1_workload_suite",
    "layer2_motif_profile",
    "layer3_target_viability",
    "layer4_candidate_plan",
    "layer5a_l1_cost_model",
    "layer6_feedback_calibration",
]

ARTIFACT_INDEX_LAYERS = list(REQUIRED_LAYERS)

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
    "fpga_superiority_claim",
    "gpu_fpga_superiority_claim",
    "hybrid_superiority_claim",
    "superiority_claim",
}

CLAIM_BOUNDARY = (
    "This artifact summarizes a QE-IC closed-loop DSE campaign through "
    "Layer-6 synthetic feedback calibration only. It does not contain "
    "SystemC/gem5/Vivado/DC/QE execution results, measured hardware "
    "performance, or final FPGA/GPU/GPU+FPGA superiority claims."
)

CONFIG_CLAIM_BOUNDARY = (
    "QE-IC closed-loop campaign config controls artifact replay and synthetic "
    "feedback calibration only. It does not enable SystemC/gem5/Vivado/DC/QE "
    "execution, measured hardware performance, hardware-proven candidates, or "
    "final GPU/FPGA/hybrid superiority claims."
)

MANIFEST_CLAIM_BOUNDARY = (
    "This manifest registers QE-IC closed-loop synthetic replay campaign "
    "artifacts only. It is not measured execution evidence or final claim "
    "adjudication."
)

VALIDITY_LEVELS = {
    "C0_contract_valid",
    "C1_l1_plausible",
    "C2_synthetic_feedback_useful",
    "C3_synthetic_feedback_false_promotion",
    "C4_high_fidelity_required",
}
