#!/usr/bin/env python3
"""Artifact I/O for QE-IC real opportunity campaigns."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.experiments.qe_ic_real_opportunity.campaign_config import load_json_object
from dse_v2.experiments.qe_ic_real_opportunity.opportunity_campaign import (
    QeIcRealOpportunityCampaignError,
    run_qe_ic_real_opportunity_campaign,
)
from dse_v2.experiments.qe_ic_real_opportunity.schema import (
    MANIFEST_CLAIM_BOUNDARY,
    PRODUCER,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_ARTIFACTS,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_MANIFEST_ARTIFACT,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_MANIFEST_SCHEMA_VERSION,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_README_ARTIFACT,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_ARTIFACT,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_ARTIFACT,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_SCHEMA_VERSION,
)
from dse_v2.experiments.qe_ic_real_opportunity.validation import validate_qe_ic_real_opportunity_campaign_report


class QeIcRealOpportunityArtifactError(ValueError):
    """Raised when persisted campaign artifacts fail validation."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _remove_stale_canonical_artifacts(out_dir: Path) -> None:
    for artifact_name in (
        QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_ARTIFACT,
        QE_IC_REAL_OPPORTUNITY_CAMPAIGN_MANIFEST_ARTIFACT,
        QE_IC_REAL_OPPORTUNITY_CAMPAIGN_README_ARTIFACT,
    ):
        path = out_dir / artifact_name
        if path.exists():
            path.unlink()


def _failed_validation(message: str) -> dict[str, Any]:
    return {
        "schema_version": QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_SCHEMA_VERSION,
        "status": "failed",
        "errors": [{"field": "input", "message": message}],
        "warnings": [],
        "candidate_selection_count": 0,
        "opportunity_record_count": 0,
        "overall_answer": None,
    }


def build_qe_ic_real_opportunity_campaign_manifest(report: Mapping[str, Any]) -> dict[str, Any]:
    """Build campaign manifest."""

    return {
        "schema_version": QE_IC_REAL_OPPORTUNITY_CAMPAIGN_MANIFEST_SCHEMA_VERSION,
        "artifact_role": "qe_ic_real_gpu_vs_fpga_hybrid_opportunity_campaign",
        "report_artifact": QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_ARTIFACT,
        "validation_artifact": QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_ARTIFACT,
        "readme_artifact": QE_IC_REAL_OPPORTUNITY_CAMPAIGN_README_ARTIFACT,
        "producer": PRODUCER,
        "campaign_id": report.get("campaign_id"),
        "overall_answer": dict(report.get("final_answer", {})).get("overall_answer"),
        "claim_boundary": MANIFEST_CLAIM_BOUNDARY,
    }


def build_qe_ic_real_opportunity_campaign_readme(report: Mapping[str, Any]) -> str:
    """Build README text explaining how to run and interpret the campaign."""

    final = report.get("final_answer") if isinstance(report.get("final_answer"), Mapping) else {}
    return "\n".join(
        [
            "# QE-IC Real Opportunity Campaign",
            "",
            "## Campaign Flow",
            "",
            "The campaign probes the local GPU, QE, profiler, SystemC, and EDA environment; "
            "prepares the ground_state_band_structure and electron_phonon_mobility cases; "
            "attempts CPU and GPU baselines without substituting CPU timing for GPU evidence; "
            "selects Layer-4 FPGA/hybrid candidates; "
            "generates non-claimable candidate stubs for EDA syntax attempts when real designs are missing; "
            "ingests candidate high-fidelity evidence; audits implementation quality; and "
            "calls the existing real-baseline opportunity claim gate.",
            "",
            "## Modes",
            "",
            "`run_if_available` may execute available local measurements. `ingest_only` only "
            "accepts externally provided logs or JSON records. `run_if_available_or_ingest_only` "
            "uses local measurements when available and otherwise emits evidence_missing rather "
            "than fabricating results. In nonblocking execute-real mode, generated stubs may be "
            "sent to real EDA tools as syntax/readiness evidence, not acceleration evidence.",
            "",
            "## Real GPU Baseline",
            "",
            "A real GPU baseline requires at least three repeated GPU-only QE runs for the same "
            "case, program, input_deck_hash, and precision. The baseline must carry "
            "`measurements_are_real=true` and `evidence_status=measured`. CPU-only QE timing is "
            "reported separately as CPU context and must not replace GPU-only evidence.",
            "",
            "## Generated Benchmark Boundary",
            "",
            "Nonblocking generated QE cases use `case_origin=generated_benchmark` and "
            "`scientific_claim_scope=performance_benchmark_only`. Missing pseudopotentials are "
            "reported explicitly; QE runtime is not fabricated.",
            "",
            "## Candidate High-Fidelity Evidence",
            "",
            "Candidate high-fidelity evidence may be workflow-level trace replay, SystemC timing, "
            "gem5/SystemC, real QE candidate runs, or Vivado/DC resource and timing evidence with "
            "explicit tool provenance. L1 estimates and synthetic labels are not high-fidelity evidence.",
            "",
            "## Generated EDA Stub Evidence",
            "",
            "When selected Layer-4 candidates do not have implementation bindings, the campaign "
            "generates minimal RTL, HLS, and SystemC stubs and attempts a real EDA syntax run "
            "through local tools or `ic-eda`. Remote EDA commands force `LC_ALL=C LANG=C`. "
            "The resulting `qe_ic_candidate_eda_stub_evidence_real_run.json` artifact is "
            "non-claimable and does not replace workflow-level candidate evidence.",
            "",
            "## Implementation-Limited vs Fundamental-No-Opportunity",
            "",
            "`implementation_limited` means the current candidate loses but weak utilization, poor "
            "overlap, low fmax, immature implementation, missing calibration, or an idealized upper "
            "bound above 1.0 leaves opportunity open. `fundamental_no_opportunity` is only allowed "
            "when real baseline and workflow-level candidate evidence exist, implementation quality "
            "passes, resource and timing are feasible or intrinsically infeasible, the idealized "
            "upper bound is at or below 1.0, and no claim gate passes.",
            "",
            "## Replace Templates",
            "",
            "Replace templates by adding real input deck paths, GPU baseline run JSON, profile logs, "
            "and candidate evidence JSON to the campaign config. Missing tools or missing decks "
            "produce evidence_missing or blocked status, not fake measurements.",
            "",
            "## Forbidden Conclusions",
            "",
            "Do not claim FPGA-only or GPU+FPGA is faster than GPU-only unless the claim gate passes. "
            "EDA tool availability and generated-stub syntax success do not imply speedup. Fixture "
            "evidence, templates, L1 estimates, and synthetic labels are progress evidence only.",
            "",
            "## Current Answer",
            "",
            str(final.get("answer_text")),
            "",
        ]
    )


def write_qe_ic_real_opportunity_campaign_artifacts(
    out_dir: Path,
    config_path: Path,
    *,
    execute_real: bool = False,
    allow_generated_inputs: bool = False,
    nonblocking: bool = False,
) -> dict[str, Any]:
    """Write campaign report, validation, manifest, and README artifacts."""

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        config = load_json_object(config_path)
        if config.get("schema_version") != "dse.qe_ic.real_opportunity_campaign_config.v1":
            raise QeIcRealOpportunityCampaignError("campaign config schema_version is incorrect")
        report = run_qe_ic_real_opportunity_campaign(
            config_path,
            out_dir=out_dir,
            execute_real=execute_real,
            allow_generated_inputs=allow_generated_inputs,
            nonblocking=nonblocking,
        )
        validation = validate_qe_ic_real_opportunity_campaign_report(report)
    except (OSError, ValueError, QeIcRealOpportunityCampaignError) as exc:
        _remove_stale_canonical_artifacts(out_dir)
        validation = _failed_validation(str(exc))
        _write_json(out_dir / QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_ARTIFACT, validation)
        return {
            "status": "failed",
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_ARTIFACT],
        }

    _remove_stale_canonical_artifacts(out_dir)
    _write_json(out_dir / QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_ARTIFACT, validation)
    if validation["status"] != "passed":
        return {
            "status": validation["status"],
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_REAL_OPPORTUNITY_CAMPAIGN_VALIDATION_ARTIFACT],
        }

    manifest = build_qe_ic_real_opportunity_campaign_manifest(report)
    readme = build_qe_ic_real_opportunity_campaign_readme(report)
    _write_json(out_dir / QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_ARTIFACT, report)
    _write_json(out_dir / QE_IC_REAL_OPPORTUNITY_CAMPAIGN_MANIFEST_ARTIFACT, manifest)
    (out_dir / QE_IC_REAL_OPPORTUNITY_CAMPAIGN_README_ARTIFACT).write_text(readme, encoding="utf-8")
    return {
        "status": "passed",
        "out_dir": str(out_dir),
        "artifacts": list(QE_IC_REAL_OPPORTUNITY_CAMPAIGN_ARTIFACTS),
    }


def load_qe_ic_real_opportunity_campaign_report(path: Path) -> dict[str, Any]:
    """Load and validate a persisted campaign report."""

    payload = load_json_object(path)
    validation = validate_qe_ic_real_opportunity_campaign_report(payload)
    if validation["status"] != "passed":
        raise QeIcRealOpportunityArtifactError(f"{path} failed campaign validation: {validation['errors']}")
    return payload
