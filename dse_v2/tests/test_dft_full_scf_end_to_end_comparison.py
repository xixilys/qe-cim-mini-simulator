#!/usr/bin/env python3
"""Regression coverage for strict full-SCF numerical comparison production."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.codesign.dft_scf_workstreams import STRICT_DFT_QE_WORKLOAD_CLASSES
from dse_v2.reference_workloads.dft_codesign_domain import write_dft_seven_axis_artifacts
from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _legal_candidate_ids(release_dir: Path) -> list[str]:
    manifest = json.loads((release_dir / "candidate_universe_manifest.json").read_text(encoding="utf-8"))
    return [str(item) for item in manifest["legal_candidate_ids"]]


def _comparison_companions(out_dir: Path) -> tuple[dict, dict]:
    validation = json.loads(
        (out_dir / "full_scf_end_to_end_comparison_validation.json").read_text(encoding="utf-8")
    )
    status = json.loads(
        (out_dir / "full_scf_end_to_end_comparison_status.json").read_text(encoding="utf-8")
    )
    return validation, status


def _write_full_scf_rows(root: Path, candidate_ids: list[str]) -> None:
    for candidate_id in candidate_ids:
        for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES:
            _write_json(
                root / candidate_id / class_id / "full_scf_end_to_end_numerical_evidence.json",
                {
                    "schema_version": "dse.dft.numerical.full_scf_row_evidence.v1",
                    "candidate_id": candidate_id,
                    "class_id": class_id,
                    "status": "passed",
                    "passed": True,
                    "comparison_scope": "full_scf_host_accelerator_end_to_end",
                    "trusted_accelerated_numeric_source": True,
                    "host_accelerator_end_to_end": True,
                    "full_scf_schedule_consumed": True,
                    "host_bound_costs_included": True,
                    "accounting_source": "qe_offload_runtime_trace",
                    "l4_execution_proof": {
                        "passed": True,
                        "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                    },
                    "fixture": False,
                    "baseline_copy": False,
                    "timing_only": False,
                    "covered_accelerated_kernel_ids": list(MAJOR_SCF_KERNEL_IDS),
                    "accelerated_kernel_costs_s": {
                        kernel_id: 0.002 for kernel_id in MAJOR_SCF_KERNEL_IDS
                    },
                    "host_bound_costs_s": {
                        phase_id: 0.001 for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS
                    },
                    "runtime_overhead_costs_s": {
                        phase_id: 0.0005 for phase_id in REQUIRED_OVERHEAD_PHASE_IDS
                    },
                    "physical_evidence": {
                        "total_energy_error_ry": 0.0,
                        "density_residual": 0.0,
                        "force_error_ry_bohr": 0.0,
                        "stress_error_kbar": 0.0,
                        "eigenvalue_summary_error_ry": 0.0,
                    },
                },
            )


def test_build_full_scf_end_to_end_comparison_passes_only_with_full_matrix(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    candidate_ids = _legal_candidate_ids(release_dir)
    row_root = tmp_path / "rows"
    _write_full_scf_rows(row_root, candidate_ids)

    out_dir = tmp_path / "comparison"
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_full_scf_end_to_end_comparison.py",
            "--out",
            str(out_dir),
            "--release-artifact-dir",
            str(release_dir),
            "--row-evidence-root",
            str(row_root),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    status = json.loads(result.stdout)
    payload = json.loads((out_dir / "full_scf_end_to_end_comparison.json").read_text(encoding="utf-8"))
    assert status["status"] == "passed"
    assert status["candidate_count"] == len(candidate_ids)
    assert status["passed_candidate_count"] == len(candidate_ids)
    assert status["row_record_count"] == len(candidate_ids) * len(STRICT_DFT_QE_WORKLOAD_CLASSES)
    assert payload["passed"] is True
    assert payload["blocked_candidate_count"] == 0
    assert payload["blocker_count"] == 0
    assert payload["required_candidate_class_row_count"] == len(candidate_ids) * len(STRICT_DFT_QE_WORKLOAD_CLASSES)
    assert payload["missing_candidate_class_row_count"] == 0
    assert payload["evidence_gap_summary"]["required_next_evidence"] == "none"
    assert payload["comparison_scope"] == "full_scf_host_accelerator_end_to_end"
    assert payload["trusted_accelerated_numeric_source"] is True
    assert payload["host_bound_costs_included"] is True
    assert {record["measurement_source"] for record in payload["row_records"]} == {"qe_offload_runtime_trace"}
    assert all(record["execution_proof_present"] is True for record in payload["row_records"])
    assert set(payload["strict_scf_class_ids"]) == set(STRICT_DFT_QE_WORKLOAD_CLASSES)
    assert set(payload["covered_accelerated_kernel_ids"]) == set(MAJOR_SCF_KERNEL_IDS)
    assert {record["status"] for record in payload["candidate_records"]} == {"passed"}
    validation, companion_status = _comparison_companions(out_dir)
    assert validation["schema_version"] == "dse.dft.numerical.full_scf_end_to_end_comparison_validation.v1"
    assert validation["status"] == "passed"
    assert validation["passed"] is True
    assert validation["valid"] is True
    assert validation["errors"] == []
    assert validation["candidate_count"] == payload["candidate_count"]
    assert validation["row_record_count"] == payload["row_record_count"]
    assert validation["blocked_candidate_count"] == payload["blocked_candidate_count"]
    assert validation["blocked_row_record_count"] == payload["blocked_row_record_count"]
    assert validation["comparison_artifact"]["exists"] is True
    assert validation["comparison_artifact"]["hash_algorithm"] == "sha256"
    assert companion_status["schema_version"] == "dse.dft.numerical.full_scf_end_to_end_comparison_status.v1"
    assert companion_status["status"] == "comparison_passed"
    assert companion_status["comparison_status"] == "passed"
    assert companion_status["comparison_passed"] is True
    assert companion_status["validation_status"] == "passed"
    assert companion_status["validation_passed"] is True
    assert companion_status["candidate_count"] == payload["candidate_count"]
    assert companion_status["row_record_count"] == payload["row_record_count"]
    assert companion_status["blocked_candidate_count"] == 0
    assert companion_status["blocked_row_record_count"] == 0
    assert companion_status["trusted_final_claim"] is False
    assert companion_status["deliverable_complete"] is False
    assert companion_status["hardware_completion_eligible"] is False
    assert companion_status["release_completion_eligible"] is False
    assert companion_status["numerical_correctness_claim_eligible"] is False


def test_build_full_scf_end_to_end_comparison_accepts_explicit_json_out_path(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    candidate_ids = _legal_candidate_ids(release_dir)
    row_root = tmp_path / "rows"
    _write_full_scf_rows(row_root, candidate_ids)

    out_file = tmp_path / "comparison" / "custom_full_scf_end_to_end_comparison.json"
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_full_scf_end_to_end_comparison.py",
            "--out",
            str(out_file),
            "--release-artifact-dir",
            str(release_dir),
            "--row-evidence-root",
            str(row_root),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    status = json.loads(result.stdout)
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    nested_artifact = out_file / "full_scf_end_to_end_comparison.json"

    assert status["status"] == "passed"
    assert status["artifact"] == str(out_file)
    assert payload["passed"] is True
    assert not nested_artifact.exists()


def test_build_full_scf_end_to_end_comparison_overlays_newer_rows_without_duplicate_blocker(tmp_path):
    release_dir = tmp_path / "release"
    candidate_ids = ["cand_overlay"]
    _write_json(
        release_dir / "release_subset_manifest.json",
        {
            "schema_version": "dse.dft.current_goal_l4.release_subset_manifest.v1",
            "legal_candidate_ids": candidate_ids,
            "candidates": [{"candidate_id": candidate_id, "legal": True} for candidate_id in candidate_ids],
        },
    )
    row_root = tmp_path / "rows"
    overlay_root = tmp_path / "overlay_rows"
    _write_full_scf_rows(row_root, candidate_ids)
    _write_full_scf_rows(overlay_root, candidate_ids)
    stale_row = row_root / "cand_overlay" / STRICT_DFT_QE_WORKLOAD_CLASSES[0] / "full_scf_end_to_end_numerical_evidence.json"
    stale_payload = json.loads(stale_row.read_text(encoding="utf-8"))
    stale_payload.update(
        {
            "status": "blocked_temporary",
            "passed": False,
            "trusted_accelerated_numeric_source": False,
            "runtime_execution_proof": {
                "passed": True,
                "transport_harness": "repo_native_offload_runtime_proxy_bridge",
                "proxy_runtime_only": True,
            },
        }
    )
    stale_row.write_text(json.dumps(stale_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    out_dir = tmp_path / "comparison"
    subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_full_scf_end_to_end_comparison.py",
            "--out",
            str(out_dir),
            "--release-artifact-dir",
            str(release_dir),
            "--row-evidence-root",
            str(row_root),
            "--overlay-row-evidence-root",
            str(overlay_root),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads((out_dir / "full_scf_end_to_end_comparison.json").read_text(encoding="utf-8"))

    assert payload["passed"] is True
    assert payload["row_record_count"] == len(STRICT_DFT_QE_WORKLOAD_CLASSES)
    assert payload["overlay_row_evidence_roots"] == [str(overlay_root)]
    assert payload["duplicate_candidate_class_rows"] == []
    assert payload["superseded_candidate_class_rows"]
    assert "duplicate_candidate_class_rows_present" not in payload["blockers"]
    assert all(record["row_evidence_root_role"] == "overlay" for record in payload["row_records"])


def test_build_full_scf_end_to_end_comparison_accepts_release_subset_manifest(tmp_path):
    release_dir = tmp_path / "release"
    candidate_ids = ["cand_subset_a", "cand_subset_b"]
    _write_json(
        release_dir / "release_subset_manifest.json",
        {
            "schema_version": "dse.dft.current_goal_l4.release_subset_manifest.v1",
            "legal_candidate_ids": candidate_ids,
            "candidates": [{"candidate_id": candidate_id, "legal": True} for candidate_id in candidate_ids],
        },
    )
    row_root = tmp_path / "rows"
    _write_full_scf_rows(row_root, candidate_ids)

    out_dir = tmp_path / "comparison"
    subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_full_scf_end_to_end_comparison.py",
            "--out",
            str(out_dir),
            "--release-artifact-dir",
            str(release_dir),
            "--row-evidence-root",
            str(row_root),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads((out_dir / "full_scf_end_to_end_comparison.json").read_text(encoding="utf-8"))
    assert payload["passed"] is True


def test_build_full_scf_end_to_end_comparison_rejects_rows_without_runtime_source_and_proof(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    candidate_id = _legal_candidate_ids(release_dir)[0]
    class_id = STRICT_DFT_QE_WORKLOAD_CLASSES[0]
    row_root = tmp_path / "rows_missing_proof"
    _write_json(
        row_root / candidate_id / class_id / "full_scf_end_to_end_numerical_evidence.json",
        {
            "schema_version": "dse.dft.numerical.full_scf_row_evidence.v1",
            "candidate_id": candidate_id,
            "class_id": class_id,
            "status": "passed",
            "passed": True,
            "comparison_scope": "full_scf_host_accelerator_end_to_end",
            "trusted_accelerated_numeric_source": True,
            "host_accelerator_end_to_end": True,
            "full_scf_schedule_consumed": True,
            "host_bound_costs_included": True,
            "fixture": False,
            "baseline_copy": False,
            "timing_only": False,
            "covered_accelerated_kernel_ids": list(MAJOR_SCF_KERNEL_IDS),
            "accelerated_kernel_costs_s": {kernel_id: 0.002 for kernel_id in MAJOR_SCF_KERNEL_IDS},
            "host_bound_costs_s": {phase_id: 0.001 for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS},
            "runtime_overhead_costs_s": {phase_id: 0.0005 for phase_id in REQUIRED_OVERHEAD_PHASE_IDS},
            "physical_evidence": {
                "total_energy_error_ry": 0.0,
                "density_residual": 0.0,
            },
        },
    )

    out_dir = tmp_path / "comparison"
    subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_full_scf_end_to_end_comparison.py",
            "--out",
            str(out_dir),
            "--release-artifact-dir",
            str(release_dir),
            "--row-evidence-root",
            str(row_root),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads((out_dir / "full_scf_end_to_end_comparison.json").read_text(encoding="utf-8"))
    row = payload["row_records"][0]
    assert payload["passed"] is False
    assert row["status"] == "blocked_temporary"
    assert "row_untrusted_runtime_source:missing" in row["blockers"]
    assert "row_missing_passed_execution_proof" in row["blockers"]
    assert "not_all_legal_candidates_passed_full_scf_comparison" in payload["blockers"]
    validation, companion_status = _comparison_companions(out_dir)
    assert validation["status"] == "blocked_temporary"
    assert validation["passed"] is False
    assert validation["valid"] is False
    assert "not_all_legal_candidates_passed_full_scf_comparison" in validation["errors"]
    assert validation["blocked_candidate_count"] == payload["blocked_candidate_count"]
    assert validation["blocked_row_record_count"] == payload["blocked_row_record_count"]
    assert companion_status["status"] == "comparison_blocked"
    assert companion_status["comparison_status"] == "blocked_temporary"
    assert companion_status["comparison_passed"] is False
    assert companion_status["validation_status"] == "blocked_temporary"
    assert companion_status["validation_passed"] is False
    assert companion_status["blockers"] == payload["blockers"]
    assert companion_status["trusted_final_claim"] is False
    assert companion_status["deliverable_complete"] is False
    assert companion_status["numerical_correctness_claim_eligible"] is False


def test_build_full_scf_end_to_end_comparison_rejects_proxy_runtime_execution_proof(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    candidate_id = _legal_candidate_ids(release_dir)[0]
    class_id = STRICT_DFT_QE_WORKLOAD_CLASSES[0]
    row_root = tmp_path / "rows_proxy_proof"
    _write_json(
        row_root / candidate_id / class_id / "full_scf_end_to_end_numerical_evidence.json",
        {
            "schema_version": "dse.dft.numerical.full_scf_row_evidence.v1",
            "candidate_id": candidate_id,
            "class_id": class_id,
            "status": "passed",
            "passed": True,
            "comparison_scope": "full_scf_host_accelerator_end_to_end",
            "trusted_accelerated_numeric_source": True,
            "host_accelerator_end_to_end": True,
            "full_scf_schedule_consumed": True,
            "host_bound_costs_included": True,
            "accounting_source": "qe_offload_runtime_trace",
            "runtime_execution_proof": {
                "passed": True,
                "transport_harness": "repo_native_offload_runtime_proxy_bridge",
                "proxy_runtime_smoke_only": True,
                "proxy_runtime_only": True,
                "qe_callsite_gated_proxy_only": True,
            },
            "fixture": False,
            "baseline_copy": False,
            "timing_only": False,
            "covered_accelerated_kernel_ids": list(MAJOR_SCF_KERNEL_IDS),
            "accelerated_kernel_costs_s": {kernel_id: 0.002 for kernel_id in MAJOR_SCF_KERNEL_IDS},
            "host_bound_costs_s": {phase_id: 0.001 for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS},
            "runtime_overhead_costs_s": {phase_id: 0.0005 for phase_id in REQUIRED_OVERHEAD_PHASE_IDS},
            "physical_evidence": {
                "total_energy_error_ry": 0.0,
                "density_residual": 0.0,
                "force_error_ry_bohr": 0.0,
                "stress_error_kbar": 0.0,
                "eigenvalue_summary_error_ry": 0.0,
            },
        },
    )

    out_dir = tmp_path / "comparison"
    subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_full_scf_end_to_end_comparison.py",
            "--out",
            str(out_dir),
            "--release-artifact-dir",
            str(release_dir),
            "--row-evidence-root",
            str(row_root),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads((out_dir / "full_scf_end_to_end_comparison.json").read_text(encoding="utf-8"))
    row = payload["row_records"][0]

    assert row["execution_proof_present"] is True
    assert row["status"] == "blocked_temporary"
    assert "row_runtime_execution_proof_proxy_runtime_smoke_only_forbidden" in row["blockers"]
    assert "row_runtime_execution_proof_proxy_runtime_only_forbidden" in row["blockers"]
    assert "row_runtime_execution_proof_qe_callsite_gated_proxy_only_forbidden" in row["blockers"]
    assert payload["candidate_blocker_histogram"][f"{class_id}::row_runtime_execution_proof_proxy_runtime_only_forbidden"] == 1
    assert payload["passed"] is False


def test_build_full_scf_end_to_end_comparison_rejects_hpsi_only_legacy_rows(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    candidate_ids = _legal_candidate_ids(release_dir)
    row_root = tmp_path / "legacy_rows"
    _write_json(
        row_root / candidate_ids[0] / "qe_si_scf_small_v1" / "qe_accelerated_numeric_evidence.json",
        {
            "schema_version": "dse.qe_accelerated_numeric_evidence.v1",
            "candidate_id": candidate_ids[0],
            "workload_case_id": "qe_si_scf_small_v1",
            "status": "passed",
            "trusted_accelerated_numeric_source": True,
            "kernel_evidence": [{"kernel_id": "h_psi", "status": "passed"}],
            "physical_evidence": {"total_energy_error_ry": 0.0, "density_residual": 0.0},
            "claim_boundary": "Historical h_psi-only evidence is not strict full-SCF closure.",
        },
    )

    out_dir = tmp_path / "comparison"
    subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_full_scf_end_to_end_comparison.py",
            "--out",
            str(out_dir),
            "--release-artifact-dir",
            str(release_dir),
            "--row-evidence-root",
            str(row_root),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads((out_dir / "full_scf_end_to_end_comparison.json").read_text(encoding="utf-8"))
    assert payload["status"] == "blocked_temporary"
    assert payload["passed"] is False
    assert payload["blocked_candidate_count"] == len(candidate_ids)
    assert payload["evidence_gap_summary"]["required_next_evidence"].startswith("trusted full-SCF")
    assert payload["trusted_accelerated_numeric_source"] is False
    assert "not_all_legal_candidates_passed_full_scf_comparison" in payload["blockers"]
    assert payload["row_blocker_histogram"]["major_accelerated_kernels_not_all_covered"] == 1
    assert payload["row_blocker_category_histogram"]["major_kernel_runtime_coverage"] >= 1
    assert payload["evidence_gap_summary"]["observed_missing_kernel_histogram"]["fft_ifft_ffft"] == 1
    assert payload["evidence_gap_summary"]["observed_missing_kernel_histogram"]["transpose_layout_conversion"] == 1
    assert payload["evidence_gap_summary"]["row_blocker_category_histogram"]["row_scope_and_source"] >= 1
    row = payload["row_records"][0]
    assert "strict_scf_class_id_not_in_required_suite" in row["blockers"]
    assert "comparison_scope_not_full_scf_host_accelerator_end_to_end" in row["blockers"]
    assert "major_accelerated_kernels_not_all_covered" in row["blockers"]
    assert "full_scf_schedule_consumed_not_true" in row["blockers"]
    assert "host_bound_costs_included_not_true" in row["blockers"]


def test_build_full_scf_end_to_end_comparison_normalizes_scf_case_path_class(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    candidate_id = _legal_candidate_ids(release_dir)[0]
    row_root = tmp_path / "current_l4_rows"
    row_dir = row_root / candidate_id / "small_multi_k_scf_case"
    _write_json(
        row_dir / "qe_accelerated_numeric_evidence.json",
        {
            "schema_version": "dse.qe_accelerated_numeric_evidence.v1",
            "status": "blocked",
            "trusted_accelerated_numeric_source": False,
            "kernel_evidence": [{"kernel_id": kernel_id, "status": "passed"} for kernel_id in MAJOR_SCF_KERNEL_IDS],
            "blockers": [
                "missing_accelerated_qe_kernel_numeric_outputs",
                "missing_accelerated_qe_scf_physical_outputs",
            ],
        },
    )
    _write_json(
        row_dir / "qe_correctness_for_l4_closure.json",
        {
            "schema_version": "dse.qe_correctness_for_l4_closure.v1",
            "status": "passed",
            "passed": True,
            "trusted_accelerated_numeric_source": True,
            "comparison_scope": "full_scf_host_accelerator_end_to_end",
            "claim_boundary": "Lower-priority sibling artifacts in the same row directory must not be double-counted.",
        },
    )

    out_dir = tmp_path / "comparison"
    subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_full_scf_end_to_end_comparison.py",
            "--out",
            str(out_dir),
            "--release-artifact-dir",
            str(release_dir),
            "--row-evidence-root",
            str(row_root),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads((out_dir / "full_scf_end_to_end_comparison.json").read_text(encoding="utf-8"))
    assert payload["status"] == "blocked_temporary"
    assert payload["passed"] is False
    assert payload["row_record_count"] == 1
    row = payload["row_records"][0]
    assert row["candidate_id"] == candidate_id
    assert row["class_id"] == "small_multi_k_scf"
    assert "strict_scf_class_id_not_in_required_suite" not in row["blockers"]
    assert "row_status_not_passed" in row["blockers"]
    assert "trusted_accelerated_numeric_source_not_true" in row["blockers"]
    assert payload["evidence_gap_summary"]["missing_strict_class_histogram"]["metal_smearing_scf"] >= 1
    assert payload["candidate_blocker_category_histogram"]["suite_identity_coverage"] >= 1
    candidate_record = next(record for record in payload["candidate_records"] if record["candidate_id"] == candidate_id)
    assert candidate_record["missing_strict_scf_class_ids"] == [
        class_id for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES if class_id != "small_multi_k_scf"
    ]
    assert payload["missing_candidate_class_row_count"] >= len(STRICT_DFT_QE_WORKLOAD_CLASSES) - 1
    assert payload["candidate_blocker_histogram"]["not_all_strict_scf_rows_passed"] >= 1
