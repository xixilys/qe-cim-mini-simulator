#!/usr/bin/env python3
"""Schema and artifact constants for the QE-IC Layer-1 workload suite."""

from __future__ import annotations

QE_IC_WORKLOAD_SUITE_SCHEMA_VERSION = "dse.qe_ic.workload_suite.v1"
QE_IC_WORKLOAD_SUITE_MANIFEST_SCHEMA_VERSION = "dse.qe_ic.workload_suite_manifest.v1"
QE_IC_WORKLOAD_SUITE_VALIDATION_SCHEMA_VERSION = "dse.qe_ic.workload_suite_validation.v1"

QE_IC_WORKLOAD_SUITE_ID = "qe_ic_device_suite_v1"
QE_IC_PRIMARY_SCENARIO_ID = "mobility_centered_ic_device"

QE_IC_WORKLOAD_SUITE_ARTIFACT = "qe_ic_workload_suite.json"
QE_IC_WORKLOAD_SUITE_VALIDATION_ARTIFACT = "qe_ic_workload_suite_validation.json"
QE_IC_WORKLOAD_SUITE_MANIFEST_ARTIFACT = "qe_ic_workload_suite_manifest.json"
QE_IC_WORKLOAD_SUITE_README_ARTIFACT = "qe_ic_workload_suite_readme.md"

QE_IC_ARTIFACTS = [
    QE_IC_WORKLOAD_SUITE_ARTIFACT,
    QE_IC_WORKLOAD_SUITE_VALIDATION_ARTIFACT,
    QE_IC_WORKLOAD_SUITE_MANIFEST_ARTIFACT,
    QE_IC_WORKLOAD_SUITE_README_ARTIFACT,
]

DOWNSTREAM_CONSUMERS = [
    "layer2_motif_profiling",
    "layer3_target_viability_test",
    "promotion_policy",
]

PROFILING_CONTRACT_REQUIRED_FIELDS = [
    "runtime_breakdown",
    "op_mix",
    "memory_movement",
    "communication_pattern",
    "parallel_axes",
    "reuse_opportunities",
    "gpu_baseline_required",
]

REQUIRED_WORKLOAD_FAMILY_FIELDS = [
    "family_id",
    "family_name",
    "priority",
    "representative_programs",
    "depends_on_families",
    "device_relevance",
    "expected_motifs",
    "first_version_required",
    "source_basis",
    "profiling_contract",
]

CLAIM_BOUNDARY = (
    "This artifact defines workload scope only. It does not contain profiling "
    "results, architecture candidates, performance estimates, target viability "
    "results, or promotion decisions."
)

MANIFEST_CLAIM_BOUNDARY = (
    "This manifest registers Layer-1 workload-suite artifacts only. It is not "
    "profiling, architecture generation, performance estimation, target viability, "
    "promotion decision, or validation evidence."
)
