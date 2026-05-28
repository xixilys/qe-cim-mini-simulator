#!/usr/bin/env python3
"""Tests for fail-closed QE full-SCF hook coverage audit."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.reference_workloads.dft_full_scf_accounting import FULL_SCF_RUNTIME_TRACE_SCHEMA
from dse_v2.reference_workloads.qe_full_scf_hook_coverage import (
    build_qe_full_scf_hook_coverage_audit,
    parse_qe_offload_callsite_trace,
)


SCRIPT = Path("dse_v2/scripts/dse/audit_qe_full_scf_hook_coverage.py")
CAMPAIGN_SCRIPT = Path("dse_v2/scripts/dse/audit_qe_full_scf_hook_coverage_campaign.py")


def test_hook_coverage_audit_maps_current_qe_trace_but_stays_blocked(tmp_path: Path) -> None:
    trace = tmp_path / "qe_offload_callsite_trace.txt"
    trace.write_text(
        "\n".join(
            [
                "QE_OFFLOAD_CALLSITE fft Rho 1",
                "QE_OFFLOAD_CALLSITE h_psi 941 941 8 1",
                "QE_OFFLOAD_CALLSITE s_psi 941 941 8",
                "QE_OFFLOAD_CALLSITE diagonalization 1 1",
                "QE_OFFLOAD_CALLSITE rho_out 19683 24 8",
                "QE_OFFLOAD_CALLSITE mix_rho 1 8 7391",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    counts, sample = parse_qe_offload_callsite_trace(trace)
    payload = build_qe_full_scf_hook_coverage_audit(
        callsite_trace_path=trace,
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf",
    )

    assert counts["fft"] == 1
    assert sample[0].startswith("QE_OFFLOAD_CALLSITE")
    assert payload["status"] == "blocked_temporary"
    assert payload["passed"] is False
    assert payload["candidate_id"] == "cand_a"
    assert payload["workload_case_id"] == "small_multi_k_scf"
    assert payload["required_major_kernel_count"] == len(MAJOR_SCF_KERNEL_IDS)
    assert payload["trusted_replacement_evidence_count"] == 0
    by_kernel = {row["kernel_id"]: row for row in payload["major_kernel_records"]}
    assert by_kernel["fft_ifft_ffft"]["status"] == "observed_diagnostic_only"
    assert by_kernel["hpsi_local_potential"]["status"] == "observed_composite_diagnostic_only"
    assert by_kernel["transpose_layout_conversion"]["status"] == "missing_hook_observation"
    assert by_kernel["dma_hbm_movement_engine"]["required_observation_surface"] == "runtime_movement_event"
    assert "kernel_hook_observed_without_replacement_evidence::fft_ifft_ffft" in payload["blockers"]
    assert "kernel_runtime_movement_hook_missing::dma_hbm_movement_engine" in payload["blockers"]
    assert "proxy_runtime_only" in payload["forbidden_closure_shortcuts"]


def test_hook_audit_reports_exact_major_kernel_runtime_contract_without_upgrading_trace(tmp_path: Path) -> None:
    trace = tmp_path / "qe_offload_callsite_trace.txt"
    kernel_evidence = tmp_path / "kernel_evidence.json"
    provenance = tmp_path / "offload_provenance.json"
    runtime_trace = tmp_path / "full_scf_runtime_trace.json"
    runtime_proof = tmp_path / "runtime_execution_proof.json"

    trace.write_text(
        "\n".join(
            [
                "QE_OFFLOAD_CALLSITE fft Rho 1",
                "QE_OFFLOAD_CALLSITE h_psi 941 941 8 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    kernel_evidence.write_text(
        json.dumps(
            [
                {
                    "kernel_id": "fft_ifft_ffft",
                    "full_kernel_recomputed": True,
                    "qe_mainflow_integrated": True,
                    "accelerated_results_consumed_by_qe": True,
                    "software_fallback_on_critical_path": False,
                    "qe_software_kernel_execution_skipped": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "accelerated_output_written_to_qe_buffer": True,
                    "qe_consumed_accelerator_output_buffer": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                },
                {
                    # Legacy QE routine name must remain diagnostic.  It must
                    # not satisfy any strict major-kernel identity by alias.
                    "kernel_id": "h_psi",
                    "full_kernel_recomputed": True,
                    "qe_mainflow_integrated": True,
                    "accelerated_results_consumed_by_qe": True,
                    "software_fallback_on_critical_path": False,
                    "qe_software_kernel_execution_skipped": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "accelerated_output_written_to_qe_buffer": True,
                    "qe_consumed_accelerator_output_buffer": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                },
            ]
        ),
        encoding="utf-8",
    )
    provenance.write_text(
        json.dumps(
            {
                "producer": "qe-offload-test",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "trusted-major-kernel-test",
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "software_fallback_on_critical_path": False,
                "qe_software_kernel_execution_skipped": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "accelerated_output_written_to_qe_buffer": True,
                "qe_consumed_accelerator_output_buffer": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            }
        ),
        encoding="utf-8",
    )
    runtime_proof.write_text(
        json.dumps({"passed": True, "transport_harness": "qe_offload_runtime_trace"}),
        encoding="utf-8",
    )
    runtime_trace.write_text(
        json.dumps(
            {
                "schema_version": FULL_SCF_RUNTIME_TRACE_SCHEMA,
                "status": "passed",
                "trusted_runtime_trace": True,
                "runtime_trace_source": "qe_offload_runtime_trace",
                "comparison_scope": "full_scf_host_accelerator_end_to_end",
                "runtime_execution_proof": {"passed": True},
                "events": [
                    {
                        "category": "accelerated_kernel",
                        "kernel_id": "fft_ifft_ffft",
                        "duration_s": 1.0e-6,
                        "measurement_source": "qe_offload_runtime_trace",
                    },
                    {
                        "category": "accelerated_kernel",
                        "kernel_id": "h_psi",
                        "duration_s": 1.0e-6,
                        "measurement_source": "qe_offload_runtime_trace",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = build_qe_full_scf_hook_coverage_audit(
        callsite_trace_path=trace,
        kernel_evidence_path=kernel_evidence,
        offload_provenance_path=provenance,
        runtime_trace_path=runtime_trace,
        runtime_execution_proof_path=runtime_proof,
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf",
    )

    by_kernel = {row["kernel_id"]: row for row in payload["major_kernel_records"]}
    assert payload["status"] == "blocked_temporary"
    assert payload["passed"] is False
    assert payload["trusted_replacement_evidence_count"] == 1
    assert payload["trusted_runtime_cost_event_count"] == 1
    assert payload["runtime_hook_contract_passed_count"] == 1
    assert by_kernel["fft_ifft_ffft"]["runtime_hook_contract_passed"] is True
    assert by_kernel["fft_ifft_ffft"]["trusted_replacement_evidence_present"] is True
    assert by_kernel["fft_ifft_ffft"]["trusted_runtime_cost_event_present"] is True
    assert by_kernel["hpsi_local_potential"]["status"] == "observed_composite_diagnostic_only"
    assert by_kernel["hpsi_local_potential"]["kernel_evidence_rows"] == 0
    assert by_kernel["hpsi_local_potential"]["trusted_replacement_evidence_present"] is False
    assert any(
        item.startswith("kernel_replacement_evidence_missing_or_untrusted::hpsi_local_potential")
        for item in by_kernel["hpsi_local_potential"]["runtime_hook_contract_blockers"]
    )


def test_hook_audit_blocks_consumed_result_when_software_fallback_remains_on_critical_path(tmp_path: Path) -> None:
    trace = tmp_path / "qe_offload_callsite_trace.txt"
    kernel_evidence = tmp_path / "kernel_evidence.json"
    provenance = tmp_path / "offload_provenance.json"
    runtime_trace = tmp_path / "full_scf_runtime_trace.json"
    runtime_proof = tmp_path / "runtime_execution_proof.json"

    trace.write_text("QE_OFFLOAD_CALLSITE fft Rho 1\n", encoding="utf-8")
    kernel_evidence.write_text(
        json.dumps(
            [
                {
                    "kernel_id": "fft_ifft_ffft",
                    "full_kernel_recomputed": True,
                    "qe_mainflow_integrated": True,
                    "accelerated_results_consumed_by_qe": True,
                    "software_fallback_on_critical_path": True,
                    "qe_software_kernel_execution_skipped": False,
                    "qe_kernel_work_replaced_on_critical_path": False,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "accelerated_output_written_to_qe_buffer": True,
                    "qe_consumed_accelerator_output_buffer": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    provenance.write_text(
        json.dumps(
            {
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "software_fallback_on_critical_path": True,
                "qe_software_kernel_execution_skipped": False,
                "qe_kernel_work_replaced_on_critical_path": False,
                "accelerated_result_materialized_in_qe_memory": True,
                "accelerated_output_written_to_qe_buffer": True,
                "qe_consumed_accelerator_output_buffer": True,
                "l4_execution_proof": {"passed": True},
            }
        ),
        encoding="utf-8",
    )
    runtime_proof.write_text(json.dumps({"passed": True}), encoding="utf-8")
    runtime_trace.write_text(
        json.dumps(
            {
                "schema_version": FULL_SCF_RUNTIME_TRACE_SCHEMA,
                "trusted_runtime_trace": True,
                "runtime_trace_source": "qe_offload_runtime_trace",
                "comparison_scope": "full_scf_host_accelerator_end_to_end",
                "runtime_execution_proof": {"passed": True},
                "events": [
                    {
                        "category": "accelerated_kernel",
                        "kernel_id": "fft_ifft_ffft",
                        "duration_s": 1.0e-6,
                        "measurement_source": "qe_offload_runtime_trace",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = build_qe_full_scf_hook_coverage_audit(
        callsite_trace_path=trace,
        kernel_evidence_path=kernel_evidence,
        offload_provenance_path=provenance,
        runtime_trace_path=runtime_trace,
        runtime_execution_proof_path=runtime_proof,
        candidate_id="cand_fallback",
        workload_case_id="small_multi_k_scf",
    )

    fft = {row["kernel_id"]: row for row in payload["major_kernel_records"]}["fft_ifft_ffft"]
    assert payload["passed"] is False
    assert fft["trusted_replacement_evidence_present"] is False
    assert fft["runtime_hook_contract_passed"] is False
    assert (
        "kernel_replacement_evidence::fft_ifft_ffft::software_fallback_on_critical_path_not_false"
        in fft["runtime_hook_contract_blockers"]
    )
    assert (
        "kernel_replacement_evidence::fft_ifft_ffft::qe_software_kernel_execution_skipped_not_true"
        in fft["runtime_hook_contract_blockers"]
    )
    assert (
        "offload_provenance::fft_ifft_ffft::offload_provenance_software_fallback_on_critical_path_not_false"
        in fft["runtime_hook_contract_blockers"]
    )


def test_hook_audit_treats_transpose_layout_callsite_as_diagnostic_only(tmp_path: Path) -> None:
    trace = tmp_path / "qe_offload_callsite_trace.txt"
    trace.write_text(
        "\n".join(
            [
                "QE_OFFLOAD_CALLSITE fft Rho 1",
                "QE_OFFLOAD_CALLSITE transpose_layout_conversion parallel_fft pencil 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = build_qe_full_scf_hook_coverage_audit(
        callsite_trace_path=trace,
        candidate_id="cand_transpose",
        workload_case_id="slab_vacuum_large_fft_scf",
    )

    by_kernel = {row["kernel_id"]: row for row in payload["major_kernel_records"]}
    transpose = by_kernel["transpose_layout_conversion"]
    assert payload["passed"] is False
    assert payload["callsite_counts"]["transpose_layout_conversion"] == 1
    assert transpose["status"] == "observed_diagnostic_only"
    assert transpose["observed_direct_hooks"] == [
        {"callsite": "transpose_layout_conversion", "count": 1}
    ]
    assert transpose["trusted_replacement_evidence_present"] is False
    assert transpose["runtime_hook_contract_passed"] is False
    assert (
        "kernel_hook_observed_without_replacement_evidence::transpose_layout_conversion"
        in payload["blockers"]
    )
    assert (
        "kernel_direct_qe_hook_missing::transpose_layout_conversion"
        not in payload["blockers"]
    )


def test_hook_coverage_audit_cli_writes_blocked_artifact(tmp_path: Path) -> None:
    trace = tmp_path / "trace.txt"
    out = tmp_path / "audit.json"
    trace.write_text("QE_OFFLOAD_CALLSITE h_psi 4 4 1 1\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--callsite-trace",
            str(trace),
            "--out",
            str(out),
            "--candidate-id",
            "cand_cli",
            "--workload-case-id",
            "metal_smearing_scf",
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["candidate_id"] == "cand_cli"
    assert payload["callsite_counts"]["h_psi"] == 1
    assert payload["claim_boundary"].startswith("Hook coverage audit only")


def test_hook_coverage_campaign_cli_summarizes_row_blockers(tmp_path: Path) -> None:
    row_dir = tmp_path / "rows" / "cand_a" / "small_multi_k_scf_case"
    row_dir.mkdir(parents=True)
    (row_dir / "qe_offload_callsite_trace.txt").write_text(
        "\n".join(
            [
                "QE_OFFLOAD_CALLSITE fft Rho 1",
                "QE_OFFLOAD_CALLSITE h_psi 941 941 8 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (row_dir / "qe_accelerated_numeric_producer_status.json").write_text(
        json.dumps(
            {
                "candidate_id": "cand_a",
                "workload_case_id": "small_multi_k_scf_case",
                "status": "blocked",
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "campaign_hook_audit.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(CAMPAIGN_SCRIPT),
            "--row-root",
            str(tmp_path / "rows"),
            "--out",
            str(out),
            "--write-row-audits",
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["row_count"] == 1
    assert payload["blocked_row_count"] == 1
    assert payload["passed"] is False
    assert payload["kernel_status_histogram"]["fft_ifft_ffft"]["observed_diagnostic_only"] == 1
    assert payload["kernel_status_histogram"]["hpsi_local_potential"]["observed_composite_diagnostic_only"] == 1
    assert payload["kernel_runtime_hook_contract_pass_counts"] == {}
    assert payload["kernel_direct_hook_missing_counts"]["transpose_layout_conversion"] == 1
    assert payload["kernel_runtime_movement_missing_counts"]["dma_hbm_movement_engine"] == 1
    assert payload["kernel_composite_only_counts"]["hpsi_local_potential"] == 1
    assert payload["kernel_replacement_missing_or_untrusted_counts"]["fft_ifft_ffft"] == 1
    assert payload["kernel_runtime_event_missing_counts"]["dma_hbm_movement_engine"] == 1
    assert payload["kernel_next_action_matrix"]["transpose_layout_conversion"][
        "direct_hook_missing_count"
    ] == 1
    assert "exact transpose/layout conversion" in payload["kernel_next_action_matrix"][
        "transpose_layout_conversion"
    ]["required_next_action"]
    assert "runtime movement event" in payload["kernel_next_action_matrix"][
        "dma_hbm_movement_engine"
    ]["required_next_action"]
    assert any(
        item["blocker"] == "kernel_replacement_evidence_missing_or_untrusted::fft_ifft_ffft"
        for item in payload["top_blockers"]
    )
    assert (row_dir / "qe_full_scf_hook_coverage_audit.json").exists()


def test_hook_coverage_campaign_reports_empty_root_as_coordination_blocker(tmp_path: Path) -> None:
    out = tmp_path / "campaign_hook_audit.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(CAMPAIGN_SCRIPT),
            "--row-root",
            str(tmp_path / "empty_rows"),
            "--out",
            str(out),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["row_count"] == 0
    assert payload["status"] == "blocked_temporary"
    assert payload["campaign_blockers"] == ["no_qe_callsite_traces_found_under_row_root"]
    assert payload["kernel_next_action_matrix"]["dma_hbm_movement_engine"][
        "claim_boundary"
    ].startswith("Per-kernel campaign diagnostics only")
