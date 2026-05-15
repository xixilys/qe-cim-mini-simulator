#!/usr/bin/env python3
"""Normalized DFT workflow summary contract tests."""

from __future__ import annotations

from dse_v2.reference_workloads.dft_workflow import (
    DftClaimEvidence,
    DftHotspotClaim,
    DftStage,
    DftStageDependency,
    DftWorkflowSpec,
)


def test_dft_workflow_spec_serializes_stage_dependency_and_claim_groups():
    stage = DftStage(
        stage_id="stage_00_scf",
        stage_type="scf",
        source_program="pw.x",
        calculation_kind="scf",
        phase_skeleton=[{"phase_id": "h_psi", "label": "h psi"}],
        evidence=[DftClaimEvidence(evidence_level="declared_input", source_type="input")],
        coverage_level="common_mode",
    )
    claim = DftHotspotClaim(
        claim_id="stage_00_scf:h_psi:predicted:hotspot",
        stage_id="stage_00_scf",
        phase_id="h_psi",
        kernel_kind="gemm_fft_composite",
        evidence_label="predicted",
        estimated_flops=10.0,
        evidence_level="static_complexity_model",
        review_status="needs_review",
    )
    workflow = DftWorkflowSpec(
        workflow_id="qe_common_flow",
        source_software="qe",
        coverage_level="common_mode",
        stages=[stage],
        dependencies=[DftStageDependency("stage_00_scf", "stage_01_bands", ["wavefunctions"])],
        hotspot_claims=[claim],
        review_flags=["needs_review"],
    )

    payload = workflow.to_dict()
    summary = workflow.workflow_summary()
    claims = workflow.claim_summary()

    assert payload["schema_version"] == "dse.dft.workflow_spec.v1"
    assert summary["schema_version"] == "dse.domain_workflow_summary.v1"
    assert summary["stage_count"] == 1
    assert summary["dependencies"][0]["artifact_names"] == ["wavefunctions"]
    assert claims["schema_version"] == "dse.domain_claim_summary.v1"
    assert claims["predicted_hotspots"][0]["claim_id"] == claim.claim_id
    assert claims["observed_hotspots"] == []
    assert claims["needs_review"][0]["claim_id"] == claim.claim_id


def test_observed_claims_require_observed_evidence_level():
    try:
        DftHotspotClaim(
            claim_id="bad",
            stage_id="stage",
            phase_id="fft",
            kernel_kind="fft",
            evidence_label="observed",
            evidence_level="heuristic_phase",
        )
    except ValueError as exc:
        assert "observed claims require" in str(exc)
    else:
        raise AssertionError("observed claim accepted non-observed evidence")
