#!/usr/bin/env python3
"""Schema constants for QE-IC real-baseline opportunity analysis."""

from __future__ import annotations

QE_IC_REAL_BASELINE_OPPORTUNITY_CONFIG_SCHEMA_VERSION = "dse.qe_ic.real_baseline_opportunity_config.v1"
QE_IC_GPU_BASELINE_MEASUREMENTS_SCHEMA_VERSION = "dse.qe_ic.gpu_baseline_measurements.v1"
QE_IC_CANDIDATE_HIGH_FIDELITY_RESULTS_SCHEMA_VERSION = "dse.qe_ic.candidate_high_fidelity_results.v1"
QE_IC_REAL_BASELINE_OPPORTUNITY_REPORT_SCHEMA_VERSION = "dse.qe_ic.real_baseline_opportunity_report.v1"
QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_SCHEMA_VERSION = "dse.qe_ic.real_baseline_opportunity_validation.v1"
QE_IC_REAL_BASELINE_OPPORTUNITY_MANIFEST_SCHEMA_VERSION = "dse.qe_ic.real_baseline_opportunity_manifest.v1"

QE_IC_REAL_BASELINE_OPPORTUNITY_REPORT_ARTIFACT = "qe_ic_real_baseline_opportunity_report.json"
QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_ARTIFACT = "qe_ic_real_baseline_opportunity_validation.json"
QE_IC_REAL_BASELINE_OPPORTUNITY_MANIFEST_ARTIFACT = "qe_ic_real_baseline_opportunity_manifest.json"
QE_IC_REAL_BASELINE_OPPORTUNITY_README_ARTIFACT = "qe_ic_real_baseline_opportunity_readme.md"

QE_IC_REAL_BASELINE_OPPORTUNITY_ARTIFACTS = [
    QE_IC_REAL_BASELINE_OPPORTUNITY_REPORT_ARTIFACT,
    QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_ARTIFACT,
    QE_IC_REAL_BASELINE_OPPORTUNITY_MANIFEST_ARTIFACT,
    QE_IC_REAL_BASELINE_OPPORTUNITY_README_ARTIFACT,
]

ANALYSIS_ROLE = "claim_gated_gpu_vs_fpga_hybrid_opportunity_analysis"
PRODUCER = "dse_v2.evidence.qe_ic"
LAYER_NAME = "qe_ic_real_gpu_baseline_opportunity_analysis_v1"

REQUIRED_INPUT_ARTIFACT_KEYS = [
    "layer1_workload_suite",
    "layer2_motif_profile",
    "layer3_target_viability",
    "layer4_candidate_plan",
    "layer5a_l1_cost_model",
    "layer6_closed_loop_dse",
    "gpu_baseline_measurements",
    "candidate_high_fidelity_results",
]

GPU_BASELINE_CLAIM_BOUNDARY = (
    "GPU baseline records are only real measurement evidence when "
    "measurements_are_real is true and evidence_status is measured."
)

CANDIDATE_RESULT_CLAIM_BOUNDARY = (
    "This candidate result is not a real measured result unless results_are_real "
    "is true and evidence_status is measured or high_fidelity_estimate with "
    "explicit tool provenance."
)

REQUIRED_HIGH_FIDELITY_PROVENANCE_FIELDS = (
    "tool",
    "version",
    "run_id",
    "config_hash",
    "output_artifact_hash",
)

CLAIM_BOUNDARY = (
    "This report only makes GPU-vs-FPGA/hybrid opportunity claims when explicit "
    "GPU baseline and candidate high-fidelity evidence pass claim gates. It does "
    "not treat L1 estimates or synthetic labels as measured performance."
)

CONFIG_CLAIM_BOUNDARY = (
    "This config enables claim-gated opportunity analysis from explicit GPU "
    "baseline and candidate high-fidelity evidence. It does not allow L1 "
    "estimates or synthetic feedback to be treated as measured hardware performance."
)

MANIFEST_CLAIM_BOUNDARY = (
    "This manifest registers QE-IC real GPU-baseline opportunity-analysis artifacts. "
    "It is not itself measured GPU, FPGA, or GPU+FPGA superiority evidence."
)

ALLOWED_VERDICTS = {
    "evidence_missing",
    "fixture_only_inconclusive",
    "gpu_dominant_no_fpga_opportunity",
    "fpga_opportunity_found",
    "hybrid_opportunity_found",
    "fpga_or_hybrid_inconclusive",
    "candidate_invalid_resource",
    "candidate_invalid_transfer_overhead",
    "candidate_invalid_workflow_overhead",
}

SYSTEM_VERDICTS = {
    "evidence_missing",
    "fixture_only_inconclusive",
    "no_fpga_or_hybrid_opportunity_found",
    "fpga_opportunity_found",
    "hybrid_opportunity_found",
    "mixed",
}

CLAIM_STRENGTHS = {"none", "weak", "moderate", "strong"}
TARGET_TYPES = {"fpga_only", "gpu_fpga_hybrid"}
GPU_TARGET_TYPE = "gpu_only"

CANDIDATE_EVIDENCE_LEVELS = {
    "l1_estimate_only",
    "systemc_timing",
    "gem5_systemc",
    "vivado_resource_timing",
    "trace_replay",
    "real_qe_run",
}

WORKFLOW_LEVEL_EVIDENCE_LEVELS = {
    "systemc_timing",
    "gem5_systemc",
    "trace_replay",
    "real_qe_run",
}

CANDIDATE_EVIDENCE_STATUSES = {
    "fixture_example",
    "measured",
    "high_fidelity_estimate",
}

BASELINE_EVIDENCE_STATUSES = {
    "fixture_example",
    "measured",
}

OPPORTUNITY_FOUND_VERDICTS = {
    "fpga_opportunity_found",
    "hybrid_opportunity_found",
}

FORBIDDEN_REPORT_TERMS = {
    "hardware_proven",
    "final_superiority_claim",
    "fpga_superiority_claim",
    "gpu_fpga_superiority_claim",
    "hybrid_superiority_claim",
}
