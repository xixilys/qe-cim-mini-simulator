#!/usr/bin/env python3
"""Artifact I/O for QE-IC real GPU-baseline opportunity analysis."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.evidence.qe_ic.opportunity import analyze_qe_ic_real_baseline_opportunity
from dse_v2.evidence.qe_ic.schema import (
    ANALYSIS_ROLE,
    CONFIG_CLAIM_BOUNDARY,
    MANIFEST_CLAIM_BOUNDARY,
    PRODUCER,
    QE_IC_REAL_BASELINE_OPPORTUNITY_CONFIG_SCHEMA_VERSION,
    QE_IC_REAL_BASELINE_OPPORTUNITY_ARTIFACTS,
    QE_IC_REAL_BASELINE_OPPORTUNITY_MANIFEST_ARTIFACT,
    QE_IC_REAL_BASELINE_OPPORTUNITY_MANIFEST_SCHEMA_VERSION,
    QE_IC_REAL_BASELINE_OPPORTUNITY_README_ARTIFACT,
    QE_IC_REAL_BASELINE_OPPORTUNITY_REPORT_ARTIFACT,
    QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_ARTIFACT,
    QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_SCHEMA_VERSION,
    REQUIRED_INPUT_ARTIFACT_KEYS,
)
from dse_v2.evidence.qe_ic.validation import (
    validate_qe_ic_opportunity_input_artifacts,
    validate_qe_ic_real_baseline_opportunity_report,
)


class QeIcRealBaselineOpportunityArtifactError(ValueError):
    """Raised when persisted QE-IC opportunity artifacts fail validation."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open() as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise QeIcRealBaselineOpportunityArtifactError(f"{path} does not exist") from exc
    if not isinstance(payload, dict):
        raise QeIcRealBaselineOpportunityArtifactError(f"{path} did not contain a JSON object")
    return payload


def _remove_stale_canonical_artifacts(out_dir: Path) -> None:
    for artifact_name in (
        QE_IC_REAL_BASELINE_OPPORTUNITY_REPORT_ARTIFACT,
        QE_IC_REAL_BASELINE_OPPORTUNITY_MANIFEST_ARTIFACT,
        QE_IC_REAL_BASELINE_OPPORTUNITY_README_ARTIFACT,
    ):
        artifact_path = out_dir / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()


def _failed_validation(errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_SCHEMA_VERSION,
        "status": "failed",
        "errors": errors,
        "warnings": [],
        "opportunity_record_count": 0,
        "overall_verdict": None,
        "best_candidate_id": None,
    }


def _input_path(config: Mapping[str, Any], key: str) -> Path:
    input_artifacts = config.get("input_artifacts")
    if not isinstance(input_artifacts, Mapping):
        raise QeIcRealBaselineOpportunityArtifactError("config.input_artifacts must be a mapping")
    if key not in input_artifacts:
        raise QeIcRealBaselineOpportunityArtifactError(f"config.input_artifacts missing {key}")
    return Path(str(input_artifacts[key]))


def _validate_opportunity_config(config: Mapping[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if config.get("schema_version") != QE_IC_REAL_BASELINE_OPPORTUNITY_CONFIG_SCHEMA_VERSION:
        errors.append({"field": "schema_version", "message": "schema_version is incorrect"})
    if config.get("analysis_role") != ANALYSIS_ROLE:
        errors.append({"field": "analysis_role", "message": "analysis_role is incorrect"})
    if not isinstance(config.get("config_id"), str) or not config.get("config_id"):
        errors.append({"field": "config_id", "message": "config_id must be non-empty"})
    if config.get("claim_boundary") != CONFIG_CLAIM_BOUNDARY:
        errors.append({"field": "claim_boundary", "message": "claim_boundary must match canonical wording"})
    input_artifacts = config.get("input_artifacts")
    if not isinstance(input_artifacts, Mapping):
        errors.append({"field": "input_artifacts", "message": "input_artifacts must be a mapping"})
    elif set(input_artifacts) != set(REQUIRED_INPUT_ARTIFACT_KEYS):
        errors.append({"field": "input_artifacts", "message": f"input_artifacts must contain {REQUIRED_INPUT_ARTIFACT_KEYS}"})
    claim_gates = config.get("claim_gates")
    required_gate_fields = {
        "minimum_speedup_for_strong_claim",
        "minimum_repeated_runs",
        "require_confidence_interval_not_crossing_one",
        "require_resource_feasible",
        "require_timing_feasible",
        "require_workflow_level_or_trace_replay",
        "allow_kernel_only_claim",
    }
    if not isinstance(claim_gates, Mapping):
        errors.append({"field": "claim_gates", "message": "claim_gates must be a mapping"})
    elif set(claim_gates) != required_gate_fields:
        errors.append({"field": "claim_gates", "message": f"claim_gates must contain {sorted(required_gate_fields)}"})
    thresholds = config.get("analysis_thresholds")
    required_thresholds = {
        "gpu_dominant_utilization",
        "transfer_overhead_dominant_ratio",
        "resource_pressure_high",
        "workflow_overhead_high",
    }
    if not isinstance(thresholds, Mapping):
        errors.append({"field": "analysis_thresholds", "message": "analysis_thresholds must be a mapping"})
    elif set(thresholds) != required_thresholds:
        errors.append({"field": "analysis_thresholds", "message": f"analysis_thresholds must contain {sorted(required_thresholds)}"})
    return errors


def build_qe_ic_real_baseline_opportunity_manifest(report: Mapping[str, Any]) -> dict[str, Any]:
    """Build the opportunity-analysis artifact manifest."""

    return {
        "schema_version": QE_IC_REAL_BASELINE_OPPORTUNITY_MANIFEST_SCHEMA_VERSION,
        "artifact_role": "qe_ic_real_gpu_baseline_opportunity_analysis",
        "report_artifact": QE_IC_REAL_BASELINE_OPPORTUNITY_REPORT_ARTIFACT,
        "validation_artifact": QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_ARTIFACT,
        "readme_artifact": QE_IC_REAL_BASELINE_OPPORTUNITY_README_ARTIFACT,
        "producer": PRODUCER,
        "input_artifact_index": dict(report.get("input_artifact_index", {})),
        "claim_boundary": MANIFEST_CLAIM_BOUNDARY,
    }


def build_qe_ic_real_baseline_opportunity_readme(report: Mapping[str, Any]) -> str:
    """Build README text for opportunity-analysis artifacts."""

    conclusion = report.get("system_conclusion") if isinstance(report.get("system_conclusion"), Mapping) else {}
    return "\n".join(
        [
            "# QE-IC Real GPU-Baseline Opportunity Analysis",
            "",
            "## What Question This Layer Answers",
            "",
            "This layer asks whether FPGA-only or GPU+FPGA hybrid candidates have "
            "a claim-gated opportunity against a real GPU-only QE baseline for a "
            "specific workload family, motif, and candidate architecture.",
            "",
            "## Why True GPU Baseline Is Required",
            "",
            "A GPU-vs-FPGA or GPU-vs-hybrid statement is only meaningful when the "
            "GPU-only baseline is measured for the same workload family and carries "
            "`measurements_are_real=true` plus `evidence_status=measured`.",
            "",
            "## Why L1 And Synthetic Replay Are Insufficient",
            "",
            "L1 and synthetic replay are insufficient for final GPU-vs-FPGA claims "
            "because they are search, screening, or calibration evidence. They do not "
            "replace measured GPU timing or high-fidelity candidate execution evidence.",
            "",
            "## How speedup_vs_gpu Is Computed",
            "",
            "`speedup_vs_gpu_mean = gpu_baseline.runtime_seconds_mean / "
            "candidate.workflow_runtime_seconds_mean`. Conservative CI speedup uses "
            "the GPU low confidence bound divided by the candidate high confidence bound.",
            "",
            "## Accepted Evidence Levels",
            "",
            "Accepted evidence levels are `systemc_timing`, `gem5_systemc`, "
            "`vivado_resource_timing`, `trace_replay`, and `real_qe_run` when they "
            "include workflow-level runtime where required. `l1_estimate_only` is "
            "accepted for ingestion but blocked from opportunity claims.",
            "",
            "## Claim Gates",
            "",
            "Claim gates require a matching measured GPU baseline, real measured or "
            "high-fidelity candidate evidence with provenance, workflow-level runtime, "
            "minimum repeated runs, speedup above threshold, conservative CI above 1.0 "
            "when configured, resource feasibility, timing feasibility, and no L1-only "
            "or synthetic-only evidence.",
            "",
            "## evidence_missing",
            "",
            "`evidence_missing` means the report could not find the exact baseline, "
            "workflow runtime, repeated-run data, provenance, or candidate evidence "
            "needed to adjudicate the opportunity claim.",
            "",
            "## GPU Is Dominant",
            "",
            "`gpu_dominant_no_fpga_opportunity` means the supplied measured evidence "
            "does not pass the speedup gate and GPU utilization is high enough that "
            "the report classifies GPU-only as the practical dominant baseline for "
            "that record.",
            "",
            "## FPGA/Hybrid Opportunity Is Found",
            "",
            "`fpga_opportunity_found` or `hybrid_opportunity_found` means the candidate "
            "passed all configured claim gates. The conclusion identifies the candidate, "
            "workload family, motif, architecture family, speedup, bottlenecks, and "
            "feasibility summary.",
            "",
            "## Replace Fixture Evidence",
            "",
            "To replace fixture evidence, edit the config input paths for "
            "`gpu_baseline_measurements` and `candidate_high_fidelity_results` so they "
            "point at measured GPU baseline records and real measured or high-fidelity "
            "candidate result records with explicit tool provenance.",
            "",
            "## No Final Claim Is Made Unless Claim Gates Pass",
            "",
            "No final claim is made unless claim gates pass. Fixture evidence, L1-only "
            "estimates, synthetic labels, kernel-only timing, missing workflow overhead, "
            "or infeasible resource/timing records remain progress evidence only.",
            "",
            "## Current Report Answer",
            "",
            str(conclusion.get("answer_to_research_question")),
            "",
        ]
    )


def write_qe_ic_real_baseline_opportunity_artifacts(
    out_dir: Path,
    opportunity_config_path: Path,
) -> dict[str, Any]:
    """Write report, validation, manifest, and README artifacts."""

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        config = _load_json_object(opportunity_config_path)
        config_errors = _validate_opportunity_config(config)
        if config_errors:
            raise QeIcRealBaselineOpportunityArtifactError(f"invalid opportunity config: {config_errors}")
        paths = {key: _input_path(config, key) for key in REQUIRED_INPUT_ARTIFACT_KEYS}
        workload_suite = _load_json_object(paths["layer1_workload_suite"])
        motif_profile = _load_json_object(paths["layer2_motif_profile"])
        target_viability = _load_json_object(paths["layer3_target_viability"])
        candidate_plan = _load_json_object(paths["layer4_candidate_plan"])
        l1_results = _load_json_object(paths["layer5a_l1_cost_model"])
        closed_loop_results = _load_json_object(paths["layer6_closed_loop_dse"])
        gpu_baseline_measurements = _load_json_object(paths["gpu_baseline_measurements"])
        candidate_high_fidelity_results = _load_json_object(paths["candidate_high_fidelity_results"])
        input_validation = validate_qe_ic_opportunity_input_artifacts(
            workload_suite=workload_suite,
            motif_profile=motif_profile,
            target_viability=target_viability,
            candidate_plan=candidate_plan,
            l1_results=l1_results,
            closed_loop_results=closed_loop_results,
            gpu_baseline_measurements=gpu_baseline_measurements,
            candidate_high_fidelity_results=candidate_high_fidelity_results,
        )
        if input_validation["status"] != "passed":
            raise QeIcRealBaselineOpportunityArtifactError(
                f"invalid opportunity inputs: {input_validation['errors']}"
            )
        report = analyze_qe_ic_real_baseline_opportunity(
            workload_suite=workload_suite,
            motif_profile=motif_profile,
            target_viability=target_viability,
            candidate_plan=candidate_plan,
            l1_results=l1_results,
            closed_loop_results=closed_loop_results,
            gpu_baseline_measurements=gpu_baseline_measurements,
            candidate_high_fidelity_results=candidate_high_fidelity_results,
            opportunity_config=config,
        )
        validation = validate_qe_ic_real_baseline_opportunity_report(report)
    except QeIcRealBaselineOpportunityArtifactError as exc:
        _remove_stale_canonical_artifacts(out_dir)
        validation = _failed_validation(errors=[{"field": "input", "message": str(exc)}])
        _write_json(out_dir / QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_ARTIFACT, validation)
        return {
            "status": "failed",
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_ARTIFACT],
        }

    _remove_stale_canonical_artifacts(out_dir)
    _write_json(out_dir / QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_ARTIFACT, validation)
    if validation["status"] != "passed":
        return {
            "status": validation["status"],
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_ARTIFACT],
        }

    manifest = build_qe_ic_real_baseline_opportunity_manifest(report)
    readme = build_qe_ic_real_baseline_opportunity_readme(report)
    _write_json(out_dir / QE_IC_REAL_BASELINE_OPPORTUNITY_REPORT_ARTIFACT, report)
    _write_json(out_dir / QE_IC_REAL_BASELINE_OPPORTUNITY_MANIFEST_ARTIFACT, manifest)
    (out_dir / QE_IC_REAL_BASELINE_OPPORTUNITY_README_ARTIFACT).write_text(readme)
    return {
        "status": validation["status"],
        "out_dir": str(out_dir),
        "artifacts": list(QE_IC_REAL_BASELINE_OPPORTUNITY_ARTIFACTS),
    }


def load_qe_ic_real_baseline_opportunity_report(path: Path) -> dict[str, Any]:
    """Load and validate a persisted QE-IC opportunity report."""

    payload = _load_json_object(path)
    validation = validate_qe_ic_real_baseline_opportunity_report(payload)
    if validation["status"] != "passed":
        raise QeIcRealBaselineOpportunityArtifactError(
            f"{path} failed QE-IC opportunity-report validation: {validation['errors']}"
        )
    return payload
