"""L4 closure matrix and performance claim-gate regressions."""

from __future__ import annotations

from dse_v2.backends.gem5_systemc_adapter import build_raw_l4_interface_observations
from dse_v2.codesign.l4_closure import (
    L4_INTERFACE_METRICS_SCHEMA,
    build_coverage_claim_report,
    build_l4_evidence_matrix,
    canonicalize_l4_interface_metrics,
)


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


def test_real_l4_with_explicit_provenance_blocker_cannot_look_trusted():
    row = _passing_row()
    row["blockers"] = ["payload_declares_accelerated_numeric_source_untrusted"]
    matrix = build_l4_evidence_matrix(
        {"legal_candidate_ids": ["cand_a"]},
        {"workload_case_ids": ["qe_scf"]},
        [row],
    )

    only = matrix["rows"][0]
    assert only["gates"]["real_l4_gem5_full_flow"] is True
    assert only["claim_label"] == "mvp_partial"
    assert only["row_status"] == "blocked"
    assert only["trusted_speedup_eligible"] is False
    assert only["deliverable_complete_eligible"] is False
    assert "payload_declares_accelerated_numeric_source_untrusted" in only["blockers"]


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


def test_adapter_emits_raw_l4_observations_and_step4_canonicalizes_metrics():
    gem5_log = "\n".join([
        "100: system.generic_accel: descriptor_read verified=true addr=0x8000000 request_addr=0x8001000 result_addr=0x8120000 request_bytes=1024 descriptor_bytes=128 flags=0xff extension_fields=true",
        "120: system.generic_accel: uarch_request_decode verified=true engine=gem5_generic_accel_microarchitecture_v1 request_bytes=1024 micro_ops=5 result_bytes=2048 result_path=/tmp/result.json result_file_written=true total_cycles=250 total_payload_bytes=4096",
        "140: system.generic_accel: uarch_op_complete verified=true kind=dma_transfer node=linear device=gpu-0 op_type=gemm start_tick=1 end_tick=11 cycles=10 bytes=3072",
        "180: system.generic_accel: microarchitecture_execute verified=true engine=gem5_generic_accel_microarchitecture_v1 micro_ops=5 result_bytes=2048 result_path=/tmp/result.json cycles=250",
        "200: system.generic_accel: completion_writeback verified=true result_addr=0x8120000 completion_addr=0x8110000 result_bytes=2048 cycles=250 error_code=0",
    ])
    raw = build_raw_l4_interface_observations(
        gem5_log=gem5_log,
        gem5_stdout="generic_accel_l4_status=1 error_code=0\ncompletion_magic=0x4753494d completion_status=0 cycles=250\n",
        result={
            "status": "passed",
            "metrics": {"latency_ms": 0.5, "host_time_ms": 0.01, "device_time_ms": 0.4, "dma_time_ms": 0.1},
            "resource_utilization": {"gpu-0": {"compute_percent": 80.0}, "host": {"compute_percent": 2.0}},
            "microarchitecture_summary": {"micro_op_count": 5, "total_cycles": 250},
            "events": [{"device": "gpu-0", "start_ns": 0.0, "end_ns": 100.0}],
        },
        source_artifacts={"transport_harness": "gem5_generic_accel_microarchitecture_v1"},
    )

    assert raw["artifact_role"] == "raw_l4_observations"
    assert raw["canonical_artifact_owner"] == "Step4"
    assert raw["request_decode"]["total_payload_bytes"] == 4096
    assert raw["uarch_op_summary"]["total_dma_bytes_observed"] == 3072

    canonical = canonicalize_l4_interface_metrics(
        raw,
        gem5_l4_proof={"passed": True, "transport_harness": "gem5_generic_accel_microarchitecture_v1"},
        raw_observations_artifact="raw_l4_interface_observations.json",
    )

    assert canonical["schema_version"] == L4_INTERFACE_METRICS_SCHEMA
    assert canonical["producer_step"] == "Step4"
    assert canonical["status"] == "passed"
    assert canonical["raw_observations_artifact"] == "raw_l4_interface_observations.json"
    assert canonical["dma"]["total_dma_bytes_observed"] == 3072
    assert canonical["completion"]["software_visible_latency_ms"] == 0.5
    assert canonical["accelerator"]["busy_fraction"] == 0.8


def test_step4_canonical_l4_metrics_block_when_raw_proof_markers_are_missing():
    canonical = canonicalize_l4_interface_metrics(
        {
            "schema_version": "dse.raw_l4_interface_observations.v1",
            "artifact_role": "raw_l4_observations",
            "markers": {"descriptor_read_verified": True},
            "descriptor_decode": {"request_bytes": 128},
            "request_decode": {},
            "completion": {},
            "observed_metrics": {},
        },
        gem5_l4_proof={"passed": False},
        raw_observations_artifact="raw_l4_interface_observations.json",
    )

    assert canonical["status"] == "blocked"
    assert canonical["validation"]["raw_adapter_did_not_produce_canonical_metrics"] is True
    assert "gem5_l4_proof.passed" in canonical["validation"]["missing_or_invalid_fields"]
    assert "marker.completion_writeback_verified" in canonical["validation"]["missing_or_invalid_fields"]


def test_l4_closure_cli_writes_matrix_and_report(tmp_path):
    import json
    import subprocess
    from pathlib import Path

    release = tmp_path / "release_subset_manifest.json"
    workloads = tmp_path / "qe_mainflow_workload_suite_manifest.json"
    rows = tmp_path / "evidence_rows.json"
    out = tmp_path / "out"
    release.write_text(json.dumps({"legal_candidate_ids": ["cand_a"]}), encoding="utf-8")
    workloads.write_text(json.dumps({"workload_case_ids": ["qe_scf"]}), encoding="utf-8")
    rows.write_text(json.dumps([_passing_row()]), encoding="utf-8")

    script = Path("dse_v2/scripts/dse/build_l4_closure_matrix.py")
    completed = subprocess.run(
        ["python3", str(script), "--release-subset", str(release), "--workload-suite", str(workloads), "--evidence-rows", str(rows), "--out", str(out)],
        check=True,
        capture_output=True,
        text=True,
    )

    status = json.loads(completed.stdout)
    report = json.loads((out / "coverage_claim_report.json").read_text(encoding="utf-8"))
    assert status["deliverable_complete"] is True
    assert report["claims"]["deliverable_complete"] is True
