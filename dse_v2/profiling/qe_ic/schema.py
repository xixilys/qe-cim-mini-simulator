#!/usr/bin/env python3
"""Schema and artifact constants for QE-IC Layer-2 motif profiling."""

from __future__ import annotations

QE_IC_PROFILE_SOURCES_SCHEMA_VERSION = "dse.qe_ic.profile_sources.v1"
QE_IC_MOTIF_PROFILE_SCHEMA_VERSION = "dse.qe_ic.motif_profile.v1"
QE_IC_MOTIF_PROFILE_VALIDATION_SCHEMA_VERSION = "dse.qe_ic.motif_profile_validation.v1"
QE_IC_MOTIF_PROFILE_MANIFEST_SCHEMA_VERSION = "dse.qe_ic.motif_profile_manifest.v1"

QE_IC_MOTIF_PROFILE_ARTIFACT = "qe_ic_motif_profile.json"
QE_IC_MOTIF_PROFILE_VALIDATION_ARTIFACT = "qe_ic_motif_profile_validation.json"
QE_IC_MOTIF_PROFILE_MANIFEST_ARTIFACT = "qe_ic_motif_profile_manifest.json"
QE_IC_MOTIF_PROFILE_README_ARTIFACT = "qe_ic_motif_profile_readme.md"

QE_IC_MOTIF_PROFILE_ARTIFACTS = [
    QE_IC_MOTIF_PROFILE_ARTIFACT,
    QE_IC_MOTIF_PROFILE_VALIDATION_ARTIFACT,
    QE_IC_MOTIF_PROFILE_MANIFEST_ARTIFACT,
    QE_IC_MOTIF_PROFILE_README_ARTIFACT,
]

SOURCE_LAYER1_SUITE_ARTIFACT = "qe_ic_workload_suite.json"

SUPPORTED_PROFILE_SOURCE_TYPES = [
    "manual_profile_table",
    "qe_timer_log",
    "nsight_summary",
    "mpi_trace_summary",
]

IMPLEMENTED_PROFILE_SOURCE_TYPES = ["manual_profile_table"]

PROFILE_SOURCE_REQUIRED_FIELDS = [
    "source_id",
    "workload_family_id",
    "program",
    "target",
    "input_case",
    "profile_source_type",
    "raw_artifact_path",
    "raw_artifact_hash",
    "trusted_for_layer2",
    "events",
]

EVENT_REQUIRED_FIELDS = [
    "event_name",
    "time_ms",
    "memory_movement_bytes",
    "communication_bytes",
    "parallel_axes",
]

CLAIM_BOUNDARY = (
    "This artifact contains observed or fixture-based workload motif profiling "
    "only. It does not contain architecture candidates, target viability "
    "decisions, promotion decisions, hardware implementation results, or final "
    "performance claims."
)

MANIFEST_CLAIM_BOUNDARY = (
    "This manifest registers Layer-2 motif-profile artifacts only. It is not "
    "architecture generation, target viability, promotion, or final evidence."
)

DOWNSTREAM_CONSUMERS = [
    "layer3_target_viability_test",
    "promotion_policy",
]

