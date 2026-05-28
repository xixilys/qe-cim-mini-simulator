"""Tests for the QE offload-runtime bridge helper."""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.reference_workloads.dft_full_scf_accounting import (
    FULL_SCF_RUNTIME_TRACE_SCHEMA,
    build_full_scf_row_accounting_from_runtime_trace,
)
from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
)


SCRIPT = Path("dse_v2/scripts/dse/run_qe_offload_runtime_bridge.py")


def _jsonl_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_qe_offload_runtime_bridge_executes_proxy_and_remains_fail_closed(tmp_path: Path) -> None:
    row_dir = tmp_path / "row"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--row-dir",
            str(row_dir),
            "--candidate-id",
            "cand",
            "--workload-case-id",
            "qe_case",
            "--runtime-events",
            str(row_dir / "full_scf_runtime_events.jsonl"),
            "--runtime-execution-proof",
            str(row_dir / "runtime_execution_proof.json"),
            "--offload-provenance",
            str(row_dir / "offload_provenance.json"),
            "--accelerated-output-json",
            str(row_dir / "accelerated_output.json"),
            "--accelerated-output-data",
            str(row_dir / "accelerated_output_values.dat"),
            "--kernel-evidence",
            str(row_dir / "kernel_evidence.json"),
            "--emit-kernel-evidence",
            "--timeout",
            "30",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = json.loads((row_dir / "accelerated_output.json").read_text(encoding="utf-8"))
    proof = json.loads((row_dir / "runtime_execution_proof.json").read_text(encoding="utf-8"))
    provenance = json.loads((row_dir / "offload_provenance.json").read_text(encoding="utf-8"))
    kernel_rows = json.loads((row_dir / "kernel_evidence.json").read_text(encoding="utf-8"))
    events = _jsonl_rows(row_dir / "full_scf_runtime_events.jsonl")

    expected_event_count = (
        len(MAJOR_SCF_KERNEL_IDS)
        + len(REQUIRED_HOST_BOUND_PHASE_IDS)
        + len(REQUIRED_OVERHEAD_PHASE_IDS)
    )
    assert output["status"] == "proxy_runtime_executed_fail_closed"
    assert output["blockers"] == []
    assert output["runtime_record_count"] == expected_event_count
    assert output["passed_runtime_record_count"] == expected_event_count
    assert output["proxy_runtime_smoke_only"] is True
    assert proof["passed"] is True
    assert proof["proxy_runtime_smoke_only"] is True
    assert provenance["accelerated_results_consumed_by_qe"] is False
    assert provenance["proxy_runtime_only"] is True
    assert len(events) == expected_event_count
    assert {event["category"] for event in events} == {
        "accelerated_kernel",
        "host_bound_phase",
        "runtime_overhead",
    }
    assert all(event["proxy_runtime_smoke_only"] is True for event in events)
    assert all(event["qe_callsite_gated_proxy_only"] is True for event in events)
    assert len(kernel_rows) == len(MAJOR_SCF_KERNEL_IDS)
    assert all(row["full_kernel_recomputed"] is False for row in kernel_rows)
    assert all(row["timing_only"] is True for row in kernel_rows)

    trace = {
        "schema_version": FULL_SCF_RUNTIME_TRACE_SCHEMA,
        "status": "passed",
        "trusted_runtime_trace": True,
        "runtime_trace_source": "qe_offload_runtime_trace",
        "comparison_scope": "full_scf_host_accelerator_end_to_end",
        "host_accelerator_end_to_end": True,
        "full_scf_schedule_consumed": True,
        "host_bound_costs_included": True,
        "runtime_execution_proof": proof,
        "events": events,
    }
    accounting = build_full_scf_row_accounting_from_runtime_trace(
        trace,
        candidate_id="cand",
        workload_case_id="qe_case",
    )
    assert accounting["status"] == "blocked"
    assert any("proxy_runtime_smoke_only_forbidden" in item for item in accounting["blockers"])
    assert any("proxy_runtime_only_forbidden" in item for item in accounting["blockers"])
    assert any("qe_callsite_gated_proxy_only_forbidden" in item for item in accounting["blockers"])


def test_qe_offload_runtime_bridge_can_materialize_domain_correct_fft_payload(tmp_path: Path) -> None:
    row_dir = tmp_path / "row"
    input_data = row_dir / "accelerated_input_values.dat"
    input_json = row_dir / "accelerated_input.json"
    input_data.parent.mkdir(parents=True, exist_ok=True)
    with input_data.open("wb") as handle:
        handle.write(struct.pack("<q", 2))
        handle.write(struct.pack("<dddd", 1.0, 0.0, 0.0, 0.0))
    input_json.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_fft_input_buffer.v1",
                "target_kernel": "fft",
                "fft_direction": "inverse",
                "howmany": 1,
                "nr1x": 2,
                "nr2x": 1,
                "nr3x": 1,
                "binary_values_path": str(input_data),
                "binary_value_format": "stream_int64_count_real64_pairs",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--row-dir",
            str(row_dir),
            "--candidate-id",
            "cand",
            "--workload-case-id",
            "qe_case",
            "--target-kernel",
            "fft",
            "--runtime-events",
            str(row_dir / "full_scf_runtime_events.jsonl"),
            "--runtime-execution-proof",
            str(row_dir / "runtime_execution_proof.json"),
            "--offload-provenance",
            str(row_dir / "offload_provenance.json"),
            "--accelerated-input-json",
            str(input_json),
            "--accelerated-input-data",
            str(input_data),
            "--accelerated-output-json",
            str(row_dir / "accelerated_output.json"),
            "--accelerated-output-data",
            str(row_dir / "accelerated_output_values.dat"),
            "--kernel-evidence",
            str(row_dir / "kernel_evidence.json"),
            "--emit-kernel-evidence",
            "--enable-domain-correct-fft-payload",
            "--timeout",
            "30",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = json.loads((row_dir / "accelerated_output.json").read_text(encoding="utf-8"))
    proof = json.loads((row_dir / "runtime_execution_proof.json").read_text(encoding="utf-8"))
    provenance = json.loads((row_dir / "offload_provenance.json").read_text(encoding="utf-8"))
    kernel_rows = json.loads((row_dir / "kernel_evidence.json").read_text(encoding="utf-8"))
    output_data = (row_dir / "accelerated_output_values.dat").read_bytes()
    events_path = row_dir / "full_scf_runtime_events.jsonl"
    expected_proxy_event_count = (
        len(MAJOR_SCF_KERNEL_IDS)
        + len(REQUIRED_HOST_BOUND_PHASE_IDS)
        + len(REQUIRED_OVERHEAD_PHASE_IDS)
    )

    assert output["status"] == "domain_correct_fft_payload_materialized"
    assert output["domain_correct_fft_payload_available"] is True
    assert output["domain_correct_fft_recomputed"] is True
    assert output["writeback_path_proof_only"] is False
    assert output["not_fpga_or_asic_evidence"] is True
    assert output["event_count"] == 0
    assert output["suppressed_proxy_event_count"] == expected_proxy_event_count
    assert output["proxy_runtime_events_suppressed_for_domain_correct_payload"] is True
    assert output["qe_callsite_gated_proxy_only"] is False
    assert output["numeric_payload"]["numeric_compute_backend"] == "numpy_fft"
    assert proof["passed"] is True
    assert provenance["full_kernel_recomputed"] is True
    assert provenance["domain_correct_fft_recomputed"] is True
    assert provenance["accelerated_results_consumed_by_qe"] is False
    assert provenance["qe_callsite_gated_proxy_only"] is False
    assert provenance["not_fpga_or_asic_evidence"] is True
    assert len(kernel_rows) == 1
    assert kernel_rows[0]["kernel_id"] == "fft_ifft_ffft"
    assert kernel_rows[0]["kernel_scope"] == "full_fft"
    assert kernel_rows[0]["full_kernel_recomputed"] is True
    assert kernel_rows[0]["domain_correct_fft_recomputed"] is True
    assert kernel_rows[0]["accelerated_results_consumed_by_qe"] is False
    assert kernel_rows[0]["not_fpga_or_asic_evidence"] is True
    assert not output_data.startswith(b"schema=")
    assert struct.unpack("<q", output_data[:8])[0] == 2
    assert not events_path.exists() or _jsonl_rows(events_path) == []
