"""L4 closure matrix and performance claim-gate regressions."""

from __future__ import annotations

from dse_v2.codesign.l4_closure import build_coverage_claim_report, build_l4_evidence_matrix


def _release_subset():
    return {
        "schema_version": "test.release_subset",
        "release_subset_hash": "release_hash",
        "legal_candidate_ids": ["cand_a", "cand_b"],
    }


def _workload_suite():
    return {
        "schema_version": "test.workload_suite",
        "manifest_hash": "workload_hash",
        "cases": [{"case_id": "qe_scf"}, {"case_id": "qe_nscf"}],
    }


def _passing_row(candidate_id: str = "cand_a", workload_case_id: str = "qe_scf"):
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
            "source_artifacts": {"transport_harness": "gem5_generic_accel_microarchitecture_v1"},
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


def test_full_candidate_workload_matrix_can_claim_deliverable_complete_only_when_all_rows_trusted():
    rows = [
        _passing_row(candidate, workload)
        for candidate in ["cand_a", "cand_b"]
        for workload in ["qe_scf", "qe_nscf"]
    ]
    matrix = build_l4_evidence_matrix(_release_subset(), _workload_suite(), rows)
    report = build_coverage_claim_report(matrix)

    assert matrix["expected_row_count"] == 4
    assert matrix["deliverable_complete_eligible"] is True
    assert {row["claim_label"] for row in matrix["rows"]} == {"l4_trusted_speedup"}
    assert report["claims"]["deliverable_complete"] is True


def test_missing_candidate_workload_row_creates_explicit_blocker_and_blocks_completion():
    matrix = build_l4_evidence_matrix(_release_subset(), _workload_suite(), [_passing_row()])
    report = build_coverage_claim_report(matrix)

    assert matrix["expected_row_count"] == 4
    assert matrix["deliverable_complete_eligible"] is False
    missing = [row for row in matrix["rows"] if row["evidence_present"] is False]
    assert len(missing) == 3
    assert all("missing_l4_evidence_row" in row["blockers"] for row in missing)
    assert report["claims"]["deliverable_complete"] is False


def test_projection_only_row_cannot_upgrade_to_trusted_speedup():
    row = _passing_row()
    row["backend"] = "systemc"
    row["evidence_tier"] = "L3"
    row.pop("gem5_l4_proof")
    matrix = build_l4_evidence_matrix(
        {"legal_candidate_ids": ["cand_a"]},
        {"workload_case_ids": ["qe_scf"]},
        [row],
    )

    only = matrix["rows"][0]
    assert only["claim_label"] == "release_l3_projection"
    assert only["trusted_speedup_eligible"] is False
    assert "projection_tier_cannot_claim_trusted_speedup" in only["blockers"]


def test_real_l4_without_correctness_baseline_or_calibration_stays_partial_not_trusted():
    row = _passing_row()
    row.pop("correctness")
    row.pop("baseline_comparison")
    row.pop("calibration_consistency")
    matrix = build_l4_evidence_matrix(
        {"legal_candidate_ids": ["cand_a"]},
        {"workload_case_ids": ["qe_scf"]},
        [row],
    )

    only = matrix["rows"][0]
    assert only["claim_label"] == "mvp_partial"
    assert only["trusted_speedup_eligible"] is False
    assert "missing_dual_correctness_result" in only["blockers"]
    assert "missing_pure_software_baseline_comparison" in only["blockers"]
    assert "missing_l4_trace_counter_calibration" in only["blockers"]


def test_fallback_or_local_transport_l4_evidence_is_blocked_for_trusted_claims():
    row = _passing_row()
    row["gem5_l4_proof"]["fallback_from_gem5"] = True
    row["gem5_l4_proof"]["transport_harness"] = "local_precise_gsim_l4"
    matrix = build_l4_evidence_matrix(
        {"legal_candidate_ids": ["cand_a"]},
        {"workload_case_ids": ["qe_scf"]},
        [row],
    )

    only = matrix["rows"][0]
    assert only["claim_label"] == "blocked"
    assert "fallback_from_gem5_not_trusted" in only["blockers"]
    assert "transport_harness_not_real_gem5_generic_accel" in only["blockers"]
