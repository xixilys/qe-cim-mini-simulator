#!/usr/bin/env python3
"""Schema and artifact constants for QE-IC Layer-4 candidate plans."""

from __future__ import annotations

QE_IC_LAYER4_CAMPAIGN_SCHEMA_VERSION = "dse.qe_ic.layer4_campaign.v1"
QE_IC_CANDIDATE_PLAN_SCHEMA_VERSION = "dse.qe_ic.candidate_plan.v1"
QE_IC_CANDIDATE_PLAN_VALIDATION_SCHEMA_VERSION = "dse.qe_ic.candidate_plan_validation.v1"
QE_IC_CANDIDATE_PLAN_MANIFEST_SCHEMA_VERSION = "dse.qe_ic.candidate_plan_manifest.v1"

QE_IC_CANDIDATE_PLAN_ARTIFACT = "qe_ic_candidate_plan.json"
QE_IC_CANDIDATE_PLAN_VALIDATION_ARTIFACT = "qe_ic_candidate_plan_validation.json"
QE_IC_CANDIDATE_PLAN_MANIFEST_ARTIFACT = "qe_ic_candidate_plan_manifest.json"
QE_IC_CANDIDATE_PLAN_README_ARTIFACT = "qe_ic_candidate_plan_readme.md"

QE_IC_CANDIDATE_PLAN_ARTIFACTS = [
    QE_IC_CANDIDATE_PLAN_ARTIFACT,
    QE_IC_CANDIDATE_PLAN_VALIDATION_ARTIFACT,
    QE_IC_CANDIDATE_PLAN_MANIFEST_ARTIFACT,
    QE_IC_CANDIDATE_PLAN_README_ARTIFACT,
]

SOURCE_LAYER1_SUITE_ARTIFACT = "qe_ic_workload_suite.json"
SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT = "qe_ic_motif_profile.json"
SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT = "qe_ic_target_viability.json"

LAYER_NAME = "layer4_candidate_generation_and_promotion"
PRODUCER = "dse_v2.candidates.qe_ic"

TARGET_TYPES = {
    "gpu_only",
    "fpga_only",
    "gpu_fpga_hybrid",
}

CANDIDATE_TYPES = {
    "baseline",
    "fpga_candidate",
    "hybrid_candidate",
}

SOURCE_VIABILITY_DECISIONS = {
    "baseline",
    "maybe",
    "viable",
}

PROMOTION_DECISIONS = {
    "baseline",
    "reject",
    "hold",
    "promote",
}

FIDELITIES = {
    "L0_target_viability",
    "L1_cost_model",
    "none",
}

BUDGET_FIELDS = [
    "max_l1_cost_model_requests",
    "max_systemc_requests",
    "max_gem5_requests",
    "max_vivado_requests",
    "max_real_qe_requests",
]

EXECUTION_FORBIDDEN_FIELDS = {
    "systemc_results",
    "gem5_results",
    "vivado_results",
    "dc_results",
    "real_qe_results",
    "rtl_results",
    "hls_results",
    "execution_results",
    "hardware_implementation_results",
    "final_performance_claims",
    "performance_claims",
}

REQUEST_FORBIDDEN_FIELDS = {
    "execution_result",
    "measured_result",
    "performance_result",
    "systemc_result",
    "gem5_result",
    "vivado_result",
    "real_qe_result",
    "final_claim",
}

CLAIM_BOUNDARY = (
    "This artifact contains candidate specifications and promotion plans only. "
    "It does not contain executed SystemC/gem5/Vivado/QE results, hardware "
    "implementation results, or final performance claims."
)

MANIFEST_CLAIM_BOUNDARY = (
    "This manifest registers Layer-4 candidate and promotion artifacts only. "
    "It is not execution evidence or final claim adjudication."
)

CAMPAIGN_CLAIM_BOUNDARY = (
    "Layer-4 campaign config controls candidate generation and promotion "
    "planning only. It does not request execution or claim final performance."
)

EVALUATION_REQUEST_CLAIM_BOUNDARY = (
    "This is a planned evaluation request only; no execution result is included."
)

DOWNSTREAM_CONSUMERS = [
    "layer5_evaluation_runner",
    "systemc_request_builder",
    "gem5_request_builder",
    "vivado_request_builder",
    "qe_validation_runner",
]

PROMOTION_REASON_CODE_REGISTRY = {
    "baseline_reference",
    "candidate_generated_from_viability",
    "source_decision_maybe",
    "source_decision_viable",
    "source_decision_baseline",
    "source_decision_reject",
    "target_type_not_allowed",
    "template_family_not_allowed",
    "score_above_promotion_threshold",
    "score_below_reject_threshold",
    "budget_available",
    "budget_exhausted",
    "target_diversity_selected",
    "motif_diversity_selected",
    "diversity_represented",
    "duplicate_motif_deprioritized",
    "duplicate_target_type_deprioritized",
    "risk_within_tolerance",
    "risk_above_tolerance",
    "strong_viability_score",
    "moderate_viability_score",
    "low_viability_score",
    "positive_gain_estimate",
    "weak_gain_estimate",
    "high_runtime_ratio",
    "low_runtime_ratio",
    "profile_quality_high",
    "profile_quality_medium",
    "profile_quality_low",
    "planned_l1_cost_model_request",
    "not_next_fidelity_candidate",
}

