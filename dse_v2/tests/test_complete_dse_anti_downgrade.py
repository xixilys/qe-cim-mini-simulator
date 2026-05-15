"""Anti-downgrade regressions for complete-DSE release claims.

These tests mirror the PRD/test-spec guardrail: Top-K or representative
coverage, descriptor-only L4 rows, timing-only correctness, and projection
evidence must not become ``deliverable_complete`` or trusted speedup evidence.
"""

from __future__ import annotations

from dse_v2.codesign.l4_closure import build_coverage_claim_report, build_l4_evidence_matrix


def _release_subset(*candidate_ids: str):
    return {
        "schema_version": "test.release_subset",
        "release_subset_hash": "release_hash",
        "legal_candidate_ids": list(candidate_ids),
    }


def _workload_suite(*workload_case_ids: str):
    return {
        "schema_version": "test.workload_suite",
        "manifest_hash": "workload_hash",
        "workload_case_ids": list(workload_case_ids),
    }


def _trusted_row(candidate_id: str = "cand_a", workload_case_id: str = "qe_scf"):
    return {
        "row_id": f"{candidate_id}:{workload_case_id}",
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "backend": "gem5_systemc",
        "gem5_l4_proof": {
            "passed": True,
            "descriptor_read_verified": True,
            "request_decode_verified": True,
            "microarchitecture_execute_verified": True,
            "completion_writeback_verified": True,
            "driver_status_verified": True,
            "driver_completion_descriptor_verified": True,
            "result_status_passed": True,
            "fallback_from_gem5": False,
            "transport_harness": "gem5_generic_accel_microarchitecture_v1",
        },
        "correctness": {
            "trusted_claim_eligible": True,
            "kernel_gate": {"status": "passed"},
            "scf_physical_gate": {"status": "passed"},
        },
        "baseline_comparison": {
            "status": "passed",
            "pure_software_qe_baseline": True,
            "baseline_status": "real_qe_baseline",
        },
        "calibration_consistency": {
            "status": "passed",
            "trace_counter_consistent": True,
        },
    }


def test_top_k_or_representative_subset_cannot_complete_release():
    matrix = build_l4_evidence_matrix(
        _release_subset("cand_a", "cand_b"),
        _workload_suite("qe_scf", "qe_nscf"),
        [_trusted_row("cand_a", "qe_scf")],
    )
    report = build_coverage_claim_report(matrix)

    assert matrix["expected_row_count"] == 4
    assert matrix["blocked_row_count"] == 3
    assert report["claims"]["deliverable_complete"] is False
    assert report["claims"]["top_k_or_representative_completion_allowed"] is False
    assert all(row["claim_label"] == "blocked" for row in matrix["rows"] if not row["evidence_present"])


def test_descriptor_only_l4_row_cannot_claim_trusted_speedup():
    row = _trusted_row()
    row["gem5_l4_proof"] = {
        "passed": True,
        "descriptor_read_verified": True,
        "fallback_from_gem5": False,
        "transport_harness": "gem5_generic_accel_microarchitecture_v1",
    }

    matrix = build_l4_evidence_matrix(_release_subset("cand_a"), _workload_suite("qe_scf"), [row])
    only = matrix["rows"][0]

    assert only["claim_label"] == "blocked"
    assert only["trusted_speedup_eligible"] is False
    assert only["deliverable_complete_eligible"] is False
    assert "l4_proof_microarchitecture_execute_verified_missing_or_false" in only["blockers"]
    assert "l4_proof_completion_writeback_verified_missing_or_false" in only["blockers"]


def test_projection_and_timing_only_correctness_cannot_upgrade_to_release_completion():
    row = _trusted_row()
    row["backend"] = "generic_sim"
    row["evidence_tier"] = "L3"
    row["correctness"] = {
        "kernel_gate": {"status": "passed"},
        "scf_physical_gate": {"status": "passed"},
        "timing_only": True,
    }

    matrix = build_l4_evidence_matrix(_release_subset("cand_a"), _workload_suite("qe_scf"), [row])
    report = build_coverage_claim_report(matrix)
    only = matrix["rows"][0]

    assert only["claim_label"] == "release_l3_projection"
    assert only["trusted_speedup_eligible"] is False
    assert only["deliverable_complete_eligible"] is False
    assert "projection_tier_cannot_claim_trusted_speedup" in only["blockers"]
    assert "timing_only_evidence_cannot_satisfy_correctness" in only["blockers"]
    assert report["claims"]["projection_only_completion_allowed"] is False
    assert report["claims"]["deliverable_complete"] is False
