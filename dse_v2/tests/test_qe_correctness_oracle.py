#!/usr/bin/env python3
"""QE dual correctness oracle regressions."""

from __future__ import annotations

from dse_v2.reference_workloads.qe_correctness import (
    default_qe_correctness_tolerances,
    evaluate_qe_correctness_row,
    numerical_correctness_oracle_schema,
    validate_qe_correctness_tolerances,
)


def _passing_row(**overrides):
    row = {
        "row_id": "cand_a__qe_si_scf_small_v1",
        "candidate_id": "cand_a",
        "workload_case_id": "qe_si_scf_small_v1",
        "workload_stage_type": "scf",
        "kernel_evidence": [
            {"kernel_id": "h_psi", "absolute_error": 1.0e-12, "relative_error": 1.0e-10},
            {"kernel_id": "diagonalization", "absolute_error": 5.0e-12, "relative_error": 1.0e-10},
        ],
        "physical_evidence": {
            "total_energy_error_ry": 1.0e-8,
            "density_residual": 1.0e-8,
            "eigenvalue_summary_error_ry": 1.0e-7,
        },
    }
    row.update(overrides)
    return row


def test_default_tolerances_are_complete_and_positive():
    tolerances = default_qe_correctness_tolerances()
    schema = numerical_correctness_oracle_schema()
    report = validate_qe_correctness_tolerances(tolerances)

    assert report["valid"] is True
    assert schema["gate_policy"]["timing_only_evidence_allowed_for_correctness"] is False
    assert set(schema["required_tolerance_fields"]).issubset(tolerances)


def test_oracle_allows_trusted_claim_only_when_kernel_and_scf_gates_pass():
    result = evaluate_qe_correctness_row(_passing_row(), default_qe_correctness_tolerances())

    assert result["kernel_gate"]["status"] == "passed"
    assert result["scf_physical_gate"]["status"] == "passed"
    assert result["trusted_claim_eligible"] is True
    assert result["requested_claim_status"] == "passed"
    assert "l4_trusted_speedup" in result["allowed_claim_labels"]


def test_kernel_failure_is_independent_from_scf_physical_pass():
    row = _passing_row(kernel_evidence=[{"kernel_id": "h_psi", "absolute_error": 1.0e-2, "relative_error": 1.0e-2}])
    result = evaluate_qe_correctness_row(row, default_qe_correctness_tolerances())

    assert result["kernel_gate"]["status"] == "failed"
    assert result["scf_physical_gate"]["status"] == "passed"
    assert result["trusted_claim_eligible"] is False
    assert result["requested_claim_status"] == "blocked"
    assert "kernel_gate_failed" in result["downgrade_blocks"]


def test_scf_physical_failure_is_independent_from_kernel_pass():
    row = _passing_row(physical_evidence={"total_energy_error_ry": 1.0e-2, "density_residual": 1.0e-8, "eigenvalue_summary_error_ry": 1.0e-7})
    result = evaluate_qe_correctness_row(row, default_qe_correctness_tolerances())

    assert result["kernel_gate"]["status"] == "passed"
    assert result["scf_physical_gate"]["status"] == "failed"
    assert result["trusted_claim_eligible"] is False
    assert "scf_physical_gate_failed" in result["downgrade_blocks"]


def test_timing_only_or_placeholder_tolerances_block_trusted_claims():
    timing_only = evaluate_qe_correctness_row(
        _passing_row(timing_only=True),
        default_qe_correctness_tolerances(),
    )
    assert timing_only["trusted_claim_eligible"] is False
    assert "timing_only_evidence_cannot_satisfy_correctness" in timing_only["downgrade_blocks"]

    tolerances = default_qe_correctness_tolerances()
    tolerances["kernel_absolute_tolerance"] = "TBD"
    placeholder = evaluate_qe_correctness_row(_passing_row(), tolerances)
    assert placeholder["trusted_claim_eligible"] is False
    assert "invalid_or_placeholder_tolerances" in placeholder["downgrade_blocks"]
