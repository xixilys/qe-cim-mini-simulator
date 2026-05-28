#!/usr/bin/env python3
"""Regression coverage for strict full-SCF numerical row materialization."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.codesign.dft_scf_workstreams import STRICT_DFT_QE_WORKLOAD_CLASSES
from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
)
from dse_v2.reference_workloads.dft_full_scf_accounting import FULL_SCF_RUNTIME_TRACE_SCHEMA


ROW_BUILDER = Path("dse_v2/scripts/dse/build_dft_full_scf_numerical_rows.py")
COMPARISON_BUILDER = Path("dse_v2/scripts/dse/build_dft_full_scf_end_to_end_comparison.py")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _trusted_qe_row(candidate_id: str, class_id: str) -> dict:
    return {
        "schema_version": "dse.qe_accelerated_numeric_evidence.v1",
        "candidate_id": candidate_id,
        "workload_case_id": class_id,
        "accelerated_output_status": "passed",
        "trusted_accelerated_numeric_source": True,
        "source_kind": "qe_offload_runtime",
        "kernel_evidence": [
            {
                "kernel_id": kernel_id,
                "kernel_scope": f"full_{kernel_id}",
                "full_kernel_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "absolute_error": 0.0,
                "relative_error": 0.0,
            }
            for kernel_id in MAJOR_SCF_KERNEL_IDS
        ],
        "physical_evidence": {
            "total_energy_error_ry": 0.0,
            "density_residual": 0.0,
            "eigenvalue_summary_error_ry": 0.0,
            "force_error_ry_bohr": 0.0,
            "stress_error_kbar": 0.0,
        },
        "blockers": [],
    }


def _strict_accounting(candidate_id: str | None = None, workload_case_id: str | None = None) -> dict:
    payload = {
        "schema_version": "dse.dft.numerical.full_scf_row_accounting.v1",
        "status": "passed",
        "comparison_scope": "full_scf_host_accelerator_end_to_end",
        "host_accelerator_end_to_end": True,
        "full_scf_schedule_consumed": True,
        "host_bound_costs_included": True,
        "fixture": False,
        "baseline_copy": False,
        "timing_only": False,
        "accounting_source": "qe_offload_runtime_trace",
        "l4_execution_proof": {
            "passed": True,
            "transport_harness": "gem5_generic_accel_microarchitecture_v1",
        },
        "covered_accelerated_kernel_ids": list(MAJOR_SCF_KERNEL_IDS),
        "accelerated_kernel_costs_s": {kernel_id: 0.002 for kernel_id in MAJOR_SCF_KERNEL_IDS},
        "host_bound_costs_s": {phase_id: 0.001 for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS},
        "runtime_overhead_costs_s": {phase_id: 0.0005 for phase_id in REQUIRED_OVERHEAD_PHASE_IDS},
    }
    if candidate_id is not None:
        payload["candidate_id"] = candidate_id
    if workload_case_id is not None:
        payload["workload_case_id"] = workload_case_id
    return payload


def _trusted_runtime_trace(candidate_id: str, workload_case_id: str) -> dict:
    events = [
        {
            "category": "accelerated_kernel",
            "kernel_id": kernel_id,
            "duration_s": 0.002,
            "measurement_source": "qe_offload_runtime_trace",
            "candidate_id": candidate_id,
            "workload_case_id": workload_case_id,
            "workload_id": workload_case_id,
        }
        for kernel_id in MAJOR_SCF_KERNEL_IDS
    ]
    events.extend(
        {
            "category": "host_bound_phase",
            "phase_id": phase_id,
            "duration_s": 0.001,
            "measurement_source": "qe_offload_runtime_trace",
            "candidate_id": candidate_id,
            "workload_case_id": workload_case_id,
            "workload_id": workload_case_id,
        }
        for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS
    )
    events.extend(
        {
            "category": "runtime_overhead",
            "overhead_id": overhead_id,
            "duration_s": 0.0005,
            "measurement_source": "qe_offload_runtime_trace",
            "candidate_id": candidate_id,
            "workload_case_id": workload_case_id,
            "workload_id": workload_case_id,
        }
        for overhead_id in REQUIRED_OVERHEAD_PHASE_IDS
    )
    return {
        "schema_version": FULL_SCF_RUNTIME_TRACE_SCHEMA,
        "status": "passed",
        "trusted_runtime_trace": True,
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "runtime_trace_source": "qe_offload_runtime_trace",
        "comparison_scope": "full_scf_host_accelerator_end_to_end",
        "host_accelerator_end_to_end": True,
        "full_scf_schedule_consumed": True,
        "host_bound_costs_included": True,
        "l4_execution_proof": {
            "passed": True,
            "transport_harness": "gem5_generic_accel_microarchitecture_v1",
        },
        "physical_evidence": {"density_residual": 0.0},
        "events": events,
    }


def test_full_scf_row_materializer_blocks_trusted_qe_row_without_full_scf_accounting(tmp_path: Path) -> None:
    source_root = tmp_path / "source_rows"
    out_root = tmp_path / "strict_rows"
    candidate_id = "cand_test_0001"
    class_id = "small_multi_k_scf"
    _write_json(
        source_root / candidate_id / f"{class_id}_case" / "qe_accelerated_numeric_evidence.json",
        _trusted_qe_row(candidate_id, class_id),
    )

    completed = subprocess.run(
        [sys.executable, str(ROW_BUILDER), "--source-row-root", str(source_root), "--out-root", str(out_root)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    index = json.loads(completed.stdout)
    row = json.loads((out_root / candidate_id / class_id / "full_scf_end_to_end_numerical_evidence.json").read_text(encoding="utf-8"))
    assert index["status"] == "blocked_temporary"
    assert index["blocked_row_count"] == 1
    assert index["blocker_histogram"]["full_scf_row_accounting_missing"] == 1
    assert index["missing_full_scf_accounting_row_count"] == 1
    assert index["evidence_gap_summary"]["required_next_evidence"].startswith("trusted QE/offload")
    assert row["class_id"] == class_id
    assert row["passed"] is False
    assert "full_scf_row_accounting_missing" in row["blockers"]
    assert "accelerated_kernel_costs_s_missing" in row["blockers"]
    assert "host_bound_costs_s_missing" in row["blockers"]
    assert "runtime_overhead_costs_s_missing" in row["blockers"]
    assert row["trusted_accelerated_numeric_source"] is False


def test_full_scf_row_materializer_blocks_duplicate_source_rows_for_same_identity(tmp_path: Path) -> None:
    source_root = tmp_path / "source_rows"
    out_root = tmp_path / "strict_rows"
    candidate_id = "cand_duplicate_0001"
    class_id = "small_multi_k_scf"

    canonical_dir = source_root / "rows" / candidate_id / f"{class_id}_case"
    overlay_dir = source_root / "accelerated_numeric_inputs" / candidate_id / f"{class_id}_case"
    _write_json(canonical_dir / "qe_accelerated_numeric_evidence.json", _trusted_qe_row(candidate_id, class_id))
    _write_json(canonical_dir / "full_scf_row_accounting.json", _strict_accounting(candidate_id, class_id))
    _write_json(overlay_dir / "qe_accelerated_numeric_evidence.json", _trusted_qe_row(candidate_id, class_id))
    _write_json(overlay_dir / "full_scf_row_accounting.json", _strict_accounting(candidate_id, class_id))

    completed = subprocess.run(
        [sys.executable, str(ROW_BUILDER), "--source-row-root", str(source_root), "--out-root", str(out_root)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    index = json.loads(completed.stdout)
    row = json.loads(
        (out_root / candidate_id / class_id / "full_scf_end_to_end_numerical_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert index["status"] == "blocked_temporary"
    assert index["row_count"] == 1
    assert index["blocked_row_count"] == 1
    assert index["passed_row_count"] == 0
    assert index["duplicate_source_row_count"] == 2
    assert index["duplicate_source_identity_count"] == 1
    assert index["blocker_histogram"]["duplicate_source_qe_accelerated_numeric_rows"] == 1
    assert index["evidence_gap_summary"]["duplicate_source_row_count"] == 2
    assert row["passed"] is False
    assert row["trusted_accelerated_numeric_source"] is False
    assert row["duplicate_source_row_count"] == 2
    assert len(row["duplicate_source_rows"]) == 2
    assert len(row["duplicate_source_qe_accelerated_numeric_row_paths"]) == 2
    assert "duplicate_source_qe_accelerated_numeric_rows" in row["blockers"]


def test_full_scf_row_materializer_requires_per_kernel_qe_consumption(tmp_path: Path) -> None:
    source_root = tmp_path / "source_rows"
    out_root = tmp_path / "strict_rows"
    candidate_id = "cand_no_consumption_0001"
    class_id = "small_multi_k_scf"
    source = _trusted_qe_row(candidate_id, class_id)
    for kernel_row in source["kernel_evidence"]:
        kernel_row.pop("qe_mainflow_integrated", None)
        kernel_row.pop("accelerated_results_consumed_by_qe", None)
    row_dir = source_root / candidate_id / f"{class_id}_case"
    _write_json(row_dir / "qe_accelerated_numeric_evidence.json", source)
    _write_json(row_dir / "full_scf_row_accounting.json", _strict_accounting(candidate_id, class_id))

    completed = subprocess.run(
        [sys.executable, str(ROW_BUILDER), "--source-row-root", str(source_root), "--out-root", str(out_root)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    index = json.loads(completed.stdout)
    row = json.loads(
        (out_root / candidate_id / class_id / "full_scf_end_to_end_numerical_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert index["status"] == "blocked_temporary"
    assert row["passed"] is False
    assert "kernel_consumption_evidence_qe_mainflow_integrated_not_true::fft_ifft_ffft" in row["blockers"]
    assert (
        "kernel_consumption_evidence_accelerated_results_consumed_by_qe_not_true::fft_ifft_ffft"
        in row["blockers"]
    )


def test_full_scf_row_materializer_normalizes_runtime_trace_into_accounting(tmp_path: Path) -> None:
    source_root = tmp_path / "source_rows"
    out_root = tmp_path / "strict_rows"
    release_dir = tmp_path / "release"
    comparison_dir = tmp_path / "comparison"
    candidate_id = "cand_trace_0001"
    _write_json(release_dir / "release_subset_manifest.json", {"legal_candidate_ids": [candidate_id]})

    for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES:
        row_dir = source_root / candidate_id / f"{class_id}_case"
        _write_json(row_dir / "qe_accelerated_numeric_evidence.json", _trusted_qe_row(candidate_id, class_id))
        _write_json(row_dir / "full_scf_runtime_trace.json", _trusted_runtime_trace(candidate_id, class_id))

    completed = subprocess.run(
        [sys.executable, str(ROW_BUILDER), "--source-row-root", str(source_root), "--out-root", str(out_root)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    index = json.loads(completed.stdout)
    strict_row_dir = out_root / candidate_id / STRICT_DFT_QE_WORKLOAD_CLASSES[0]
    strict_row = json.loads((strict_row_dir / "full_scf_end_to_end_numerical_evidence.json").read_text(encoding="utf-8"))
    materialized_accounting = json.loads((strict_row_dir / "full_scf_row_accounting.json").read_text(encoding="utf-8"))

    assert index["status"] == "passed"
    assert index["blocked_row_count"] == 0
    assert strict_row["passed"] is True
    assert strict_row["runtime_trace_materialized_to_accounting"] is True
    assert strict_row["source_full_scf_runtime_trace"]["path"].endswith("full_scf_runtime_trace.json")
    assert strict_row["source_full_scf_row_accounting"]["path"].endswith("full_scf_row_accounting.json")
    assert materialized_accounting["status"] == "passed"
    assert materialized_accounting["runtime_trace_reference"]["path"].endswith("full_scf_runtime_trace.json")

    comparison = subprocess.run(
        [
            sys.executable,
            str(COMPARISON_BUILDER),
            "--out",
            str(comparison_dir),
            "--release-artifact-dir",
            str(release_dir),
            "--row-evidence-root",
            str(out_root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    status = json.loads(comparison.stdout)
    payload = json.loads((comparison_dir / "full_scf_end_to_end_comparison.json").read_text(encoding="utf-8"))
    assert status["status"] == "passed"
    assert payload["passed"] is True
    assert payload["passed_candidate_count"] == 1


def test_full_scf_row_materializer_follows_accelerated_reference_runtime_trace(tmp_path: Path) -> None:
    source_root = tmp_path / "source_rows"
    out_root = tmp_path / "strict_rows"
    trace_root = tmp_path / "runtime_traces"
    candidate_id = "cand_trace_ref_0001"
    class_id = "small_multi_k_scf"
    trace_path = trace_root / candidate_id / class_id / "full_scf_runtime_trace.json"
    source = _trusted_qe_row(candidate_id, class_id)
    source["accelerated_reference"] = {"full_scf_runtime_trace_json": str(trace_path)}
    _write_json(
        source_root / candidate_id / f"{class_id}_case" / "qe_accelerated_numeric_evidence.json",
        source,
    )
    _write_json(trace_path, _trusted_runtime_trace(candidate_id, class_id))

    completed = subprocess.run(
        [sys.executable, str(ROW_BUILDER), "--source-row-root", str(source_root), "--out-root", str(out_root)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    index = json.loads(completed.stdout)
    strict_row_dir = out_root / candidate_id / class_id
    strict_row = json.loads((strict_row_dir / "full_scf_end_to_end_numerical_evidence.json").read_text(encoding="utf-8"))
    accounting = json.loads((strict_row_dir / "full_scf_row_accounting.json").read_text(encoding="utf-8"))
    assert index["status"] == "passed"
    assert strict_row["passed"] is True
    assert strict_row["runtime_trace_materialized_to_accounting"] is True
    assert strict_row["source_full_scf_runtime_trace"]["path"] == str(trace_path)
    assert accounting["runtime_trace_reference"]["path"] == str(trace_path)


def test_full_scf_row_materializer_blocks_proxy_materialized_runtime_trace(tmp_path: Path) -> None:
    source_root = tmp_path / "source_rows"
    out_root = tmp_path / "strict_rows"
    candidate_id = "cand_proxy_trace_0001"
    class_id = "small_multi_k_scf"
    row_dir = source_root / candidate_id / f"{class_id}_case"
    runtime_trace = _trusted_runtime_trace(candidate_id, class_id)
    runtime_trace["proxy_runtime_only"] = True
    runtime_trace["proxy_runtime_smoke_only"] = True
    runtime_trace["runtime_trace_source"] = "proxy_runtime_smoke_only"
    runtime_trace["l4_execution_proof"]["proxy_runtime_only"] = True
    for event in runtime_trace["events"]:
        event["measurement_source"] = "proxy_runtime_smoke_only"
        event["proxy_runtime_only"] = True

    _write_json(row_dir / "qe_accelerated_numeric_evidence.json", _trusted_qe_row(candidate_id, class_id))
    _write_json(row_dir / "full_scf_runtime_trace.json", runtime_trace)

    completed = subprocess.run(
        [sys.executable, str(ROW_BUILDER), "--source-row-root", str(source_root), "--out-root", str(out_root)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    index = json.loads(completed.stdout)
    strict_row_dir = out_root / candidate_id / class_id
    strict_row = json.loads(
        (strict_row_dir / "full_scf_end_to_end_numerical_evidence.json").read_text(encoding="utf-8")
    )
    materialized_accounting = json.loads((strict_row_dir / "full_scf_row_accounting.json").read_text(encoding="utf-8"))

    assert index["status"] == "blocked_temporary"
    assert index["blocked_row_count"] == 1
    assert index["passed_row_count"] == 0
    assert strict_row["status"] == "blocked_temporary"
    assert strict_row["passed"] is False
    assert strict_row["trusted_accelerated_numeric_source"] is False
    assert strict_row["runtime_trace_materialized_to_accounting"] is True
    assert strict_row["source_full_scf_runtime_trace"]["path"].endswith("full_scf_runtime_trace.json")
    assert materialized_accounting["status"] == "blocked"
    assert materialized_accounting["passed"] is False
    assert "runtime_trace_proxy_runtime_only_forbidden" in materialized_accounting["blockers"]
    assert "runtime_trace_proxy_runtime_smoke_only_forbidden" in materialized_accounting["blockers"]
    assert (
        "runtime_trace_l4_execution_proof_proxy_runtime_only_forbidden"
        in materialized_accounting["blockers"]
    )
    assert any(
        blocker.startswith("runtime_trace_event_")
        and blocker.endswith("_untrusted_measurement_source:proxy_runtime_smoke_only")
        for blocker in materialized_accounting["blockers"]
    )
    assert "full_scf_row_accounting_status_not_passed" in strict_row["blockers"]
    assert "full_scf_row_accounting_proxy_runtime_only_forbidden" in strict_row["blockers"]
    assert (
        "full_scf_row_accounting_l4_execution_proof_proxy_runtime_only_forbidden"
        in strict_row["blockers"]
    )


def test_full_scf_row_materializer_outputs_rows_that_close_strict_comparison(tmp_path: Path) -> None:
    source_root = tmp_path / "source_rows"
    out_root = tmp_path / "strict_rows"
    release_dir = tmp_path / "release"
    comparison_dir = tmp_path / "comparison"
    candidate_id = "cand_test_0001"
    _write_json(release_dir / "candidate_universe_manifest.json", {"legal_candidate_ids": [candidate_id]})

    for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES:
        row_dir = source_root / candidate_id / f"{class_id}_case"
        _write_json(row_dir / "qe_accelerated_numeric_evidence.json", _trusted_qe_row(candidate_id, class_id))
        _write_json(row_dir / "full_scf_row_accounting.json", _strict_accounting(candidate_id, class_id))

    completed = subprocess.run(
        [sys.executable, str(ROW_BUILDER), "--source-row-root", str(source_root), "--out-root", str(out_root)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    index = json.loads(completed.stdout)
    assert index["status"] == "passed"
    assert index["row_count"] == len(STRICT_DFT_QE_WORKLOAD_CLASSES)
    assert index["blocked_row_count"] == 0
    assert index["evidence_gap_summary"]["required_next_evidence"] == "none"
    strict_row = json.loads(
        (out_root / candidate_id / STRICT_DFT_QE_WORKLOAD_CLASSES[0] / "full_scf_end_to_end_numerical_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert strict_row["accounting_source"] == "qe_offload_runtime_trace"
    assert strict_row["l4_execution_proof"]["passed"] is True

    comparison = subprocess.run(
        [
            sys.executable,
            str(COMPARISON_BUILDER),
            "--out",
            str(comparison_dir),
            "--release-artifact-dir",
            str(release_dir),
            "--row-evidence-root",
            str(out_root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    status = json.loads(comparison.stdout)
    payload = json.loads((comparison_dir / "full_scf_end_to_end_comparison.json").read_text(encoding="utf-8"))
    assert status["status"] == "passed"
    assert payload["passed"] is True
    assert payload["candidate_count"] == 1
    assert payload["row_record_count"] == len(STRICT_DFT_QE_WORKLOAD_CLASSES)
    assert payload["passed_candidate_count"] == 1


def test_full_scf_row_materializer_blocks_accounting_identity_relabel(tmp_path: Path) -> None:
    source_root = tmp_path / "source_rows"
    out_root = tmp_path / "strict_rows"
    candidate_id = "cand_identity_0001"
    class_id = "small_multi_k_scf"
    row_dir = source_root / candidate_id / f"{class_id}_case"
    _write_json(row_dir / "qe_accelerated_numeric_evidence.json", _trusted_qe_row(candidate_id, class_id))
    _write_json(
        row_dir / "full_scf_row_accounting.json",
        _strict_accounting("other_candidate", "metal_smearing_scf"),
    )

    completed = subprocess.run(
        [sys.executable, str(ROW_BUILDER), "--source-row-root", str(source_root), "--out-root", str(out_root)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    index = json.loads(completed.stdout)
    strict_row = json.loads(
        (out_root / candidate_id / class_id / "full_scf_end_to_end_numerical_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert index["status"] == "blocked_temporary"
    assert strict_row["passed"] is False
    assert "full_scf_row_accounting_candidate_id_mismatch" in strict_row["blockers"]
    assert "full_scf_row_accounting_workload_case_id_mismatch" in strict_row["blockers"]
