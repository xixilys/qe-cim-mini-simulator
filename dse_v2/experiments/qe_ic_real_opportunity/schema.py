#!/usr/bin/env python3
"""Schema constants for the QE-IC real opportunity campaign."""

from __future__ import annotations

QE_IC_REAL_OPPORTUNITY_CAMPAIGN_CONFIG_SCHEMA_VERSION = "dse.qe_ic.real_opportunity_campaign_config.v1"
QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_SCHEMA_VERSION = "dse.qe_ic.real_opportunity_campaign_report.v1"
QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_SCHEMA_VERSION = "dse.qe_ic.real_opportunity_campaign_validation.v1"
QE_IC_REAL_OPPORTUNITY_CAMPAIGN_MANIFEST_SCHEMA_VERSION = "dse.qe_ic.real_opportunity_campaign_manifest.v1"

QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_ARTIFACT = "qe_ic_real_opportunity_campaign_report.json"
QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_ARTIFACT = "qe_ic_real_opportunity_campaign_validation.json"
QE_IC_REAL_OPPORTUNITY_CAMPAIGN_MANIFEST_ARTIFACT = "qe_ic_real_opportunity_campaign_manifest.json"
QE_IC_REAL_OPPORTUNITY_CAMPAIGN_README_ARTIFACT = "qe_ic_real_opportunity_campaign_readme.md"

QE_IC_REAL_OPPORTUNITY_CAMPAIGN_ARTIFACTS = [
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_ARTIFACT,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_ARTIFACT,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_MANIFEST_ARTIFACT,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_README_ARTIFACT,
]

PRODUCER = "dse_v2.experiments.qe_ic_real_opportunity"
CAMPAIGN_LAYER = "qe_ic_real_gpu_vs_fpga_hybrid_opportunity_campaign_v1"

CLAIM_BOUNDARY = (
    "No FPGA/GPU+FPGA superiority claim is made unless real or high-fidelity "
    "evidence passes the existing claim gate."
)

CONFIG_CLAIM_BOUNDARY = (
    "This campaign may only claim FPGA/hybrid opportunity when real or "
    "high-fidelity evidence passes the existing claim gate. It must not "
    "fabricate measured results."
)

MANIFEST_CLAIM_BOUNDARY = (
    "This manifest registers the QE-IC real opportunity campaign artifacts. "
    "It is not GPU, FPGA, or GPU+FPGA superiority evidence."
)

ALLOWED_MODES = {"run_if_available", "ingest_only", "run_if_available_or_ingest_only"}
ALLOWED_CAMPAIGN_STATUSES = {
    "ready",
    "partially_ready",
    "measured",
    "blocked",
    "evidence_missing",
    "blocked_by_missing_qe",
    "blocked_by_missing_input_deck",
    "blocked_by_missing_candidate_evidence",
    "completed_real_claimable",
    "completed_proxy_only",
    "completed_implementation_limited",
    "completed_no_opportunity",
    "gpu_execution_failed",
    "eda_execution_failed",
    "software_validation_failed",
}
ALLOWED_TOP_LEVEL_ANSWERS = {
    "opportunity_found",
    "implementation_limited",
    "fundamental_no_opportunity",
    "evidence_missing",
    "blocked_by_missing_qe",
    "blocked_by_missing_input_deck",
    "blocked_by_missing_candidate_evidence",
    "proxy_only_inconclusive",
    "gpu_or_eda_failure",
    "inconclusive",
}
ALLOWED_ENVIRONMENT_STATUSES = {
    "ready",
    "partially_ready",
    "blocked_by_missing_qe",
    "blocked_by_missing_input_deck",
    "blocked_by_missing_profiler",
    "blocked_by_missing_candidate_design",
    "blocked_by_missing_systemc",
    "blocked_by_missing_eda",
    "ingest_only_available",
}
REQUIRED_WORKLOAD_FAMILIES = {
    "ground_state_band_structure",
    "electron_phonon_mobility",
}

REQUIRED_INPUT_ARTIFACT_KEYS = {
    "layer1_workload_suite",
    "layer2_motif_profile",
    "layer3_target_viability",
    "layer4_candidate_plan",
    "layer5a_l1_cost_model",
    "layer6_closed_loop_dse",
}

OPTIONAL_INPUT_ARTIFACT_KEYS = {
    "gpu_baseline_runs",
    "gpu_baseline_measurements",
    "profile_logs",
    "candidate_high_fidelity_results",
    "candidate_evidence",
}
