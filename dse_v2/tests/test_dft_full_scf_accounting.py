"""Tests for strict DFT full-SCF runtime trace accounting."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.reference_workloads.dft_full_scf_accounting import (
    FULL_SCF_RUNTIME_TRACE_SCHEMA,
    build_full_scf_row_accounting_from_runtime_trace,
    validate_full_scf_row_accounting_payload,
)
from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
)


SCRIPT = Path("dse_v2/scripts/dse/build_dft_full_scf_row_accounting_from_trace.py")
TRACE_BUILDER_SCRIPT = Path("dse_v2/scripts/dse/build_dft_full_scf_runtime_trace_from_events.py")


def _trusted_trace() -> dict:
    events = [
        {
            "category": "accelerated_kernel",
            "kernel_id": kernel_id,
            "duration_s": 0.002,
            "measurement_source": "qe_offload_runtime_trace",
            "candidate_id": "cand_a",
            "workload_case_id": "small_multi_k_scf_case",
            "workload_id": "small_multi_k_scf_case",
        }
        for kernel_id in MAJOR_SCF_KERNEL_IDS
    ]
    events.extend(
        {
            "category": "host_bound_phase",
            "phase_id": phase_id,
            "duration_s": 0.001,
            "measurement_source": "qe_offload_runtime_trace",
            "candidate_id": "cand_a",
            "workload_case_id": "small_multi_k_scf_case",
            "workload_id": "small_multi_k_scf_case",
        }
        for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS
    )
    events.extend(
        {
            "category": "runtime_overhead",
            "overhead_id": overhead_id,
            "duration_s": 0.0005,
            "measurement_source": "qe_offload_runtime_trace",
            "candidate_id": "cand_a",
            "workload_case_id": "small_multi_k_scf_case",
            "workload_id": "small_multi_k_scf_case",
        }
        for overhead_id in REQUIRED_OVERHEAD_PHASE_IDS
    )
    return {
        "schema_version": FULL_SCF_RUNTIME_TRACE_SCHEMA,
        "status": "passed",
        "trusted_runtime_trace": True,
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


def _write_jsonl_events(path: Path, trace: dict) -> None:
    path.write_text("\n".join(json.dumps(event) for event in trace["events"]) + "\n", encoding="utf-8")


def _write_proof(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "passed": True,
                "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                "measurement_source": "qe_offload_runtime_trace",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_event_manifest(
    path: Path,
    *,
    missing_kernel: str | None = None,
    measurement_source: str = "qe_offload_runtime_trace",
) -> None:
    kernel_ids = [kernel_id for kernel_id in MAJOR_SCF_KERNEL_IDS if kernel_id != missing_kernel]
    path.write_text(
        json.dumps(
            {
                "schema_version": "dse.dft.numerical.full_scf_runtime_event_manifest.v1",
                "candidate_id": "cand_a",
                "workload_case_id": "small_multi_k_scf_case",
                "measurement_source": measurement_source,
                "required_event_identity": True,
                "required_event_categories": {
                    "accelerated_kernel": {
                        "id_field": "kernel_id",
                        "required_ids": kernel_ids,
                    },
                    "host_bound_phase": {
                        "id_field": "phase_id",
                        "required_ids": list(REQUIRED_HOST_BOUND_PHASE_IDS),
                    },
                    "runtime_overhead": {
                        "id_field": "overhead_id",
                        "required_ids": list(REQUIRED_OVERHEAD_PHASE_IDS),
                    },
                },
                "required_trace_booleans": {
                    "trusted_runtime_trace": True,
                    "host_accelerator_end_to_end": True,
                    "full_scf_schedule_consumed": True,
                    "host_bound_costs_included": True,
                },
                "forbidden_markers": ["fixture", "baseline_copy", "timing_only"],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_build_full_scf_row_accounting_from_trusted_trace() -> None:
    payload = build_full_scf_row_accounting_from_runtime_trace(
        _trusted_trace(),
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf_case",
    )

    assert payload["status"] == "passed"
    assert payload["blockers"] == []
    assert payload["candidate_id"] == "cand_a"
    assert set(payload["covered_accelerated_kernel_ids"]) == set(MAJOR_SCF_KERNEL_IDS)
    assert set(payload["host_bound_costs_s"]) == set(REQUIRED_HOST_BOUND_PHASE_IDS)
    assert set(payload["runtime_overhead_costs_s"]) == set(REQUIRED_OVERHEAD_PHASE_IDS)


def test_runtime_trace_accounting_accepts_zero_duration_event() -> None:
    trace = _trusted_trace()
    first_kernel = MAJOR_SCF_KERNEL_IDS[0]
    for event in trace["events"]:
        if event.get("category") == "accelerated_kernel" and event.get("kernel_id") == first_kernel:
            event["duration_s"] = 0.0
            break

    payload = build_full_scf_row_accounting_from_runtime_trace(
        trace,
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf_case",
    )

    assert payload["status"] == "passed"
    assert payload["blockers"] == []
    assert payload["accelerated_kernel_costs_s"][first_kernel] == 0.0


def test_direct_full_scf_row_accounting_requires_trusted_source_and_execution_proof() -> None:
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
        "covered_accelerated_kernel_ids": list(MAJOR_SCF_KERNEL_IDS),
        "accelerated_kernel_costs_s": {kernel_id: 0.002 for kernel_id in MAJOR_SCF_KERNEL_IDS},
        "host_bound_costs_s": {phase_id: 0.001 for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS},
        "runtime_overhead_costs_s": {phase_id: 0.0005 for phase_id in REQUIRED_OVERHEAD_PHASE_IDS},
    }

    blockers = validate_full_scf_row_accounting_payload(payload)

    assert "full_scf_row_accounting_untrusted_runtime_source:missing" in blockers
    assert "full_scf_row_accounting_missing_passed_execution_proof" in blockers

    payload["accounting_source"] = "qe_offload_runtime_trace"
    payload["l4_execution_proof"] = {
        "passed": True,
        "transport_harness": "gem5_generic_accel_microarchitecture_v1",
    }
    assert validate_full_scf_row_accounting_payload(payload) == []


def test_direct_full_scf_row_accounting_rejects_other_row_identity() -> None:
    payload = build_full_scf_row_accounting_from_runtime_trace(
        _trusted_trace(),
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf_case",
    )

    blockers = validate_full_scf_row_accounting_payload(
        payload,
        candidate_id="other_candidate",
        workload_case_id="metal_smearing_scf",
    )

    assert "full_scf_row_accounting_candidate_id_mismatch" in blockers
    assert "full_scf_row_accounting_workload_case_id_mismatch" in blockers


def test_direct_full_scf_row_accounting_rejects_proxy_runtime_flags() -> None:
    payload = build_full_scf_row_accounting_from_runtime_trace(
        _trusted_trace(),
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf_case",
    )
    assert payload["blockers"] == []
    payload["proxy_runtime_smoke_only"] = True
    payload["proxy_runtime_only"] = True
    payload["qe_callsite_gated_proxy_only"] = True

    blockers = validate_full_scf_row_accounting_payload(payload)

    assert "full_scf_row_accounting_proxy_runtime_smoke_only_forbidden" in blockers
    assert "full_scf_row_accounting_proxy_runtime_only_forbidden" in blockers
    assert "full_scf_row_accounting_qe_callsite_gated_proxy_only_forbidden" in blockers


def test_direct_full_scf_row_accounting_rejects_proxy_runtime_execution_proof_flags() -> None:
    payload = build_full_scf_row_accounting_from_runtime_trace(
        _trusted_trace(),
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf_case",
    )
    assert payload["blockers"] == []
    payload["runtime_execution_proof"] = {
        "passed": True,
        "transport_harness": "repo_native_offload_runtime_proxy_bridge",
        "proxy_runtime_smoke_only": True,
        "proxy_runtime_only": True,
        "qe_callsite_gated_proxy_only": True,
    }

    blockers = validate_full_scf_row_accounting_payload(payload)

    assert "full_scf_row_accounting_runtime_execution_proof_proxy_runtime_smoke_only_forbidden" in blockers
    assert "full_scf_row_accounting_runtime_execution_proof_proxy_runtime_only_forbidden" in blockers
    assert "full_scf_row_accounting_runtime_execution_proof_qe_callsite_gated_proxy_only_forbidden" in blockers


def test_direct_full_scf_row_accounting_rejects_proxy_runtime_execution_proof_transport() -> None:
    payload = build_full_scf_row_accounting_from_runtime_trace(
        _trusted_trace(),
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf_case",
    )
    assert payload["blockers"] == []
    payload["runtime_execution_proof"] = {
        "passed": True,
        "transport_harness": "repo_native_offload_runtime_proxy_bridge",
    }

    blockers = validate_full_scf_row_accounting_payload(payload)

    assert "full_scf_row_accounting_runtime_execution_proof_proxy_runtime_marker_forbidden:transport_harness" in blockers


def test_runtime_trace_accounting_rejects_proxy_runtime_event_flags() -> None:
    trace = _trusted_trace()
    trace["events"][0]["proxy_runtime_smoke_only"] = True
    trace["events"][0]["proxy_runtime_only"] = True
    trace["events"][0]["qe_callsite_gated_proxy_only"] = True

    payload = build_full_scf_row_accounting_from_runtime_trace(
        trace,
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf_case",
    )

    assert payload["status"] == "blocked"
    assert "runtime_trace_event_0_proxy_runtime_smoke_only_forbidden" in payload["blockers"]
    assert "runtime_trace_event_0_proxy_runtime_only_forbidden" in payload["blockers"]
    assert "runtime_trace_event_0_qe_callsite_gated_proxy_only_forbidden" in payload["blockers"]


def test_runtime_trace_accounting_rejects_proxy_runtime_execution_proof_flags() -> None:
    trace = _trusted_trace()
    trace["runtime_execution_proof"] = {
        "passed": True,
        "transport_harness": "repo_native_offload_runtime_proxy_bridge",
        "proxy_runtime_smoke_only": True,
        "proxy_runtime_only": True,
        "qe_callsite_gated_proxy_only": True,
    }

    payload = build_full_scf_row_accounting_from_runtime_trace(
        trace,
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf_case",
    )

    assert payload["status"] == "blocked"
    assert "runtime_trace_runtime_execution_proof_proxy_runtime_smoke_only_forbidden" in payload["blockers"]
    assert "runtime_trace_runtime_execution_proof_proxy_runtime_only_forbidden" in payload["blockers"]
    assert "runtime_trace_runtime_execution_proof_qe_callsite_gated_proxy_only_forbidden" in payload["blockers"]
    assert "full_scf_row_accounting_runtime_execution_proof_proxy_runtime_smoke_only_forbidden" in payload["blockers"]


def test_runtime_trace_accounting_rejects_proxy_runtime_execution_proof_transport() -> None:
    trace = _trusted_trace()
    trace["runtime_execution_proof"] = {
        "passed": True,
        "transport_harness": "repo_native_offload_runtime_proxy_bridge",
    }

    payload = build_full_scf_row_accounting_from_runtime_trace(
        trace,
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf_case",
    )

    assert payload["status"] == "blocked"
    assert "runtime_trace_runtime_execution_proof_proxy_runtime_marker_forbidden:transport_harness" in payload["blockers"]
    assert "full_scf_row_accounting_runtime_execution_proof_proxy_runtime_marker_forbidden:transport_harness" in payload["blockers"]


def test_trace_accounting_cli_writes_blocked_artifact_for_timing_model(tmp_path: Path) -> None:
    trace = _trusted_trace()
    trace["timing_only"] = True
    trace["runtime_trace_source"] = "timing_model"
    for event in trace["events"]:
        event["measurement_source"] = "timing_model"
    trace_path = tmp_path / "trace.json"
    out_path = tmp_path / "full_scf_row_accounting.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--trace",
            str(trace_path),
            "--out",
            str(out_path),
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert "runtime_trace_timing_only_forbidden" in payload["blockers"]
    assert any("untrusted_measurement_source:timing_model" in item for item in payload["blockers"])


def test_trace_accounting_cli_blocks_candidate_identity_mismatch(tmp_path: Path) -> None:
    trace = _trusted_trace()
    trace_path = tmp_path / "trace.json"
    out_path = tmp_path / "full_scf_row_accounting.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--trace",
            str(trace_path),
            "--out",
            str(out_path),
            "--candidate-id",
            "other_candidate",
            "--workload-case-id",
            "small_multi_k_scf_case",
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert any("candidate_id_mismatch" in item for item in payload["blockers"])


def test_runtime_trace_builder_cli_accepts_measured_jsonl_events_and_proof(tmp_path: Path) -> None:
    trace = _trusted_trace()
    first_kernel = MAJOR_SCF_KERNEL_IDS[0]
    for event in trace["events"]:
        if event.get("category") == "accelerated_kernel" and event.get("kernel_id") == first_kernel:
            event["duration_s"] = 0.0
            break
    events_path = tmp_path / "full_scf_runtime_events.jsonl"
    manifest_path = tmp_path / "full_scf_runtime_event_manifest.json"
    proof_path = tmp_path / "runtime_execution_proof.json"
    out_path = tmp_path / "full_scf_runtime_trace.json"
    _write_jsonl_events(events_path, trace)
    _write_event_manifest(manifest_path)
    _write_proof(proof_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(TRACE_BUILDER_SCRIPT),
            "--events",
            str(events_path),
            "--out",
            str(out_path),
            "--event-manifest",
            str(manifest_path),
            "--measurement-source",
            "qe_offload_runtime_trace",
            "--runtime-execution-proof-json",
            str(proof_path),
            "--candidate-id",
            "cand_a",
            "--workload-case-id",
            "small_multi_k_scf_case",
            "--host-accelerator-end-to-end",
            "--full-scf-schedule-consumed",
            "--host-bound-costs-included",
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    accounting = build_full_scf_row_accounting_from_runtime_trace(
        payload,
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf_case",
        trace_path=out_path,
    )
    assert payload["status"] == "passed"
    assert payload["trusted_runtime_trace"] is True
    assert payload["runtime_trace_source"] == "qe_offload_runtime_trace"
    assert payload["runtime_execution_proof"]["passed"] is True
    assert payload["source_event_log"]["path"].endswith("full_scf_runtime_events.jsonl")
    assert payload["builder"]["runtime_event_manifest_enforced"] is True
    assert payload["runtime_event_manifest_reference"]["path"].endswith("full_scf_runtime_event_manifest.json")
    assert accounting["status"] == "passed"
    assert accounting["blockers"] == []
    assert accounting["accelerated_kernel_costs_s"][first_kernel] == 0.0


def test_runtime_trace_builder_cli_accepts_hardware_counter_execution_proof(tmp_path: Path) -> None:
    trace = _trusted_trace()
    events_path = tmp_path / "full_scf_runtime_events.jsonl"
    manifest_path = tmp_path / "full_scf_runtime_event_manifest.json"
    proof_path = tmp_path / "hardware_counter_proof.json"
    out_path = tmp_path / "full_scf_runtime_trace.json"
    _write_jsonl_events(events_path, trace)
    _write_event_manifest(manifest_path, measurement_source="hardware_counter")
    _write_proof(proof_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(TRACE_BUILDER_SCRIPT),
            "--events",
            str(events_path),
            "--out",
            str(out_path),
            "--event-manifest",
            str(manifest_path),
            "--measurement-source",
            "hardware_counter",
            "--hardware-counter-proof-json",
            str(proof_path),
            "--candidate-id",
            "cand_a",
            "--workload-case-id",
            "small_multi_k_scf_case",
            "--host-accelerator-end-to-end",
            "--full-scf-schedule-consumed",
            "--host-bound-costs-included",
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    accounting = build_full_scf_row_accounting_from_runtime_trace(
        payload,
        candidate_id="cand_a",
        workload_case_id="small_multi_k_scf_case",
        trace_path=out_path,
    )
    assert accounting["status"] == "passed"
    assert accounting["hardware_counter_proof"]["passed"] is True
    assert accounting["blockers"] == []


def test_runtime_trace_builder_cli_blocks_proxy_runtime_execution_proof(tmp_path: Path) -> None:
    trace = _trusted_trace()
    events_path = tmp_path / "full_scf_runtime_events.jsonl"
    manifest_path = tmp_path / "full_scf_runtime_event_manifest.json"
    proof_path = tmp_path / "runtime_execution_proof.json"
    out_path = tmp_path / "full_scf_runtime_trace.json"
    _write_jsonl_events(events_path, trace)
    _write_event_manifest(manifest_path)
    proof_path.write_text(
        json.dumps(
            {
                "passed": True,
                "transport_harness": "repo_native_offload_runtime_proxy_bridge",
                "measurement_source": "qe_offload_runtime_trace",
                "proxy_runtime_smoke_only": True,
                "proxy_runtime_only": True,
                "qe_callsite_gated_proxy_only": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(TRACE_BUILDER_SCRIPT),
            "--events",
            str(events_path),
            "--out",
            str(out_path),
            "--event-manifest",
            str(manifest_path),
            "--measurement-source",
            "qe_offload_runtime_trace",
            "--runtime-execution-proof-json",
            str(proof_path),
            "--candidate-id",
            "cand_a",
            "--workload-case-id",
            "small_multi_k_scf_case",
            "--host-accelerator-end-to-end",
            "--full-scf-schedule-consumed",
            "--host-bound-costs-included",
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert "runtime_trace_runtime_execution_proof_proxy_runtime_smoke_only_forbidden" in payload["blockers"]
    assert "full_scf_row_accounting_runtime_execution_proof_proxy_runtime_only_forbidden" in payload["blockers"]


def test_runtime_trace_builder_cli_blocks_event_manifest_missing_required_kernel(tmp_path: Path) -> None:
    trace = _trusted_trace()
    dropped_kernel = MAJOR_SCF_KERNEL_IDS[0]
    trace["events"] = [
        event for event in trace["events"] if event.get("kernel_id") != dropped_kernel
    ]
    events_path = tmp_path / "full_scf_runtime_events.jsonl"
    manifest_path = tmp_path / "full_scf_runtime_event_manifest.json"
    proof_path = tmp_path / "runtime_execution_proof.json"
    out_path = tmp_path / "full_scf_runtime_trace.json"
    _write_jsonl_events(events_path, trace)
    _write_event_manifest(manifest_path)
    _write_proof(proof_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(TRACE_BUILDER_SCRIPT),
            "--events",
            str(events_path),
            "--out",
            str(out_path),
            "--event-manifest",
            str(manifest_path),
            "--measurement-source",
            "qe_offload_runtime_trace",
            "--runtime-execution-proof-json",
            str(proof_path),
            "--candidate-id",
            "cand_a",
            "--workload-case-id",
            "small_multi_k_scf_case",
            "--host-accelerator-end-to-end",
            "--full-scf-schedule-consumed",
            "--host-bound-costs-included",
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert (
        f"runtime_trace_builder_event_manifest_missing_event:accelerated_kernel:kernel_id:{dropped_kernel}"
        in payload["blockers"]
    )


def test_runtime_trace_builder_cli_blocks_row_identity_mismatch(tmp_path: Path) -> None:
    trace = _trusted_trace()
    trace["events"][0]["candidate_id"] = "other_candidate"
    events_path = tmp_path / "full_scf_runtime_events.jsonl"
    manifest_path = tmp_path / "full_scf_runtime_event_manifest.json"
    proof_path = tmp_path / "runtime_execution_proof.json"
    out_path = tmp_path / "full_scf_runtime_trace.json"
    _write_jsonl_events(events_path, trace)
    _write_event_manifest(manifest_path)
    _write_proof(proof_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(TRACE_BUILDER_SCRIPT),
            "--events",
            str(events_path),
            "--out",
            str(out_path),
            "--event-manifest",
            str(manifest_path),
            "--measurement-source",
            "qe_offload_runtime_trace",
            "--runtime-execution-proof-json",
            str(proof_path),
            "--candidate-id",
            "cand_a",
            "--workload-case-id",
            "small_multi_k_scf_case",
            "--host-accelerator-end-to-end",
            "--full-scf-schedule-consumed",
            "--host-bound-costs-included",
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert any(
        item.startswith("runtime_trace_builder_event_manifest_event_candidate_id_mismatch:accelerated_kernel")
        for item in payload["blockers"]
    )


def test_runtime_trace_builder_cli_blocks_missing_execution_proof(tmp_path: Path) -> None:
    trace = _trusted_trace()
    events_path = tmp_path / "full_scf_runtime_events.jsonl"
    out_path = tmp_path / "full_scf_runtime_trace.json"
    _write_jsonl_events(events_path, trace)

    completed = subprocess.run(
        [
            sys.executable,
            str(TRACE_BUILDER_SCRIPT),
            "--events",
            str(events_path),
            "--out",
            str(out_path),
            "--measurement-source",
            "qe_offload_runtime_trace",
            "--host-accelerator-end-to-end",
            "--full-scf-schedule-consumed",
            "--host-bound-costs-included",
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert "runtime_trace_builder_missing_passed_execution_proof" in payload["blockers"]
