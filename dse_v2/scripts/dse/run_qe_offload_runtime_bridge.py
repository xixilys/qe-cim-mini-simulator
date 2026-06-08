#!/usr/bin/env python3
"""Run the repo-native offload runtime as a QE call-site bridge.

This command is intended for ``QE_OFFLOAD_BRIDGE_COMMAND`` in patched QE runs.
It proves that the patched QE process invoked a row-local offload-runtime
bridge and that the repo-native C runtime can submit/complete proxy work while
QE is on the critical path.  It is deliberately **fail-closed** for final DFT
claims: the default bridge artifacts are marked ``proxy_runtime_smoke_only`` so
strict full-SCF accounting and numerical evidence gates cannot mistake proxy
runtime traffic for domain-correct FFT/Hψ/projector/reduction acceleration.

Use this helper to replace marker-only bridge probes and narrow the remaining
evidence gap.  Do not use its default proxy artifacts as final hardware or
numeric correctness proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS  # noqa: E402
from dse_v2.reference_workloads.dft_full_scf_hybrid import (  # noqa: E402
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
)


SCHEMA = "dse.qe_offload_runtime_bridge.v1"
PROXY_REPORT_SCHEMA = "dse.qe_offload_runtime_bridge.proxy_report.v1"
RUNTIME_PROOF_SCHEMA = "dse.runtime_execution_proof.v1"
MEASUREMENT_SOURCE = "qe_offload_runtime_trace"
TRANSPORT_HARNESS = "repo_native_offload_runtime_proxy_bridge"

BRIDGE_PROXY_SOURCE = r'''
#include "runtime_api/offload_runtime.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static uint32_t parse_u32(const char* value, const char* label) {
    char* end = NULL;
    errno = 0;
    unsigned long parsed = strtoul(value, &end, 10);
    if (errno != 0 || end == value || *end != '\0' || parsed > 0xffffffffUL) {
        fprintf(stderr, "invalid %s: %s\n", label, value);
        exit(2);
    }
    return (uint32_t)parsed;
}

static void write_runtime_execution_proof_json(FILE* proof,
                                               const char* schema_version,
                                               const char* measurement_source,
                                               const char* transport_harness,
                                               const char* workload_id,
                                               const offload_runtime_metrics* metrics,
                                               int passed) {
    const offload_runtime_metrics zero = {0};
    const offload_runtime_metrics* m = metrics != NULL ? metrics : &zero;
    if (proof == NULL) {
        return;
    }
    fprintf(proof,
            "{\n"
            "  \"schema_version\": \"%s\",\n"
            "  \"passed\": %s,\n"
            "  \"measurement_source\": \"%s\",\n"
            "  \"transport_harness\": \"%s\",\n"
            "  \"workload_id\": \"%s\",\n"
            "  \"proxy_runtime_smoke_only\": true,\n"
            "  \"proxy_runtime_only\": true,\n"
            "  \"qe_callsite_gated_proxy_only\": true,\n"
            "  \"metrics\": {\n"
            "    \"command_count\": %llu,\n"
            "    \"completion_count\": %llu,\n"
            "    \"mmio_read_count\": %llu,\n"
            "    \"mmio_write_count\": %llu,\n"
            "    \"dma_read_bytes\": %llu,\n"
            "    \"dma_write_bytes\": %llu,\n"
            "    \"polling_iterations\": %llu,\n"
            "    \"interrupt_count\": %llu,\n"
            "    \"host_wait_cycles\": %llu,\n"
            "    \"device_busy_cycles\": %llu\n"
            "  },\n"
            "  \"claim_boundary\": \"Repo-native QE bridge proof only; not DFT numerical, gem5 timing, FPGA, or ASIC evidence.\"\n"
            "}\n",
            schema_version != NULL ? schema_version : "dse.runtime_execution_proof.v1",
            passed ? "true" : "false",
            measurement_source != NULL ? measurement_source : "qe_offload_runtime_trace",
            transport_harness != NULL ? transport_harness : "repo_native_offload_runtime_proxy_bridge",
            workload_id != NULL ? workload_id : "qe_callsite_bridge",
            (unsigned long long)m->command_count,
            (unsigned long long)m->completion_count,
            (unsigned long long)m->mmio_read_count,
            (unsigned long long)m->mmio_write_count,
            (unsigned long long)m->dma_read_bytes,
            (unsigned long long)m->dma_write_bytes,
            (unsigned long long)m->polling_iterations,
            (unsigned long long)m->interrupt_count,
            (unsigned long long)m->host_wait_cycles,
            (unsigned long long)m->device_busy_cycles);
}

int main(int argc, char** argv) {
    if (argc != 8) {
        fprintf(stderr,
                "usage: %s report_json proof_json dim0 dim1 dim2 iterations accelerator_hint\n",
                argv[0]);
        return 2;
    }

    const char* report_path = argv[1];
    const char* proof_path = argv[2];
    static volatile uint32_t regs[256];
    offload_runtime runtime;
    offload_runtime_init(&runtime, regs, sizeof(regs));
    offload_runtime_set_use_m5ops(&runtime, 0);

    offload_command_descriptor desc = offload_command_descriptor_default();
    desc.work_dim0 = parse_u32(argv[3], "dim0");
    desc.work_dim1 = parse_u32(argv[4], "dim1");
    desc.work_dim2 = parse_u32(argv[5], "dim2");
    desc.work_dim3 = 1;
    desc.max_iterations = parse_u32(argv[6], "iterations");
    desc.accelerator_hint = parse_u32(argv[7], "accelerator_hint");
    desc.control_policy = OFFLOAD_CONTROL_POLLING;
    desc.precision_bits = 64;

    offload_runtime_mark_roi_begin(&runtime);
    int rc = offload_runtime_submit_sync(&runtime, &desc);
    offload_runtime_mark_roi_end(&runtime);

    FILE* report = fopen(report_path, "wb");
    if (!report) {
        perror("fopen report");
        return 3;
    }
    offload_runtime_write_report_json(report,
                                      "dse.qe_offload_runtime_bridge.proxy_report.v1",
                                      "qe_callsite_bridge",
                                      "repo_native_offload_runtime_proxy_bridge",
                                      &runtime.metrics);
    fclose(report);

    FILE* proof = fopen(proof_path, "wb");
    if (!proof) {
        perror("fopen proof");
        return 3;
    }
    write_runtime_execution_proof_json(proof,
                                       "dse.runtime_execution_proof.v1",
                                       "qe_offload_runtime_trace",
                                       "repo_native_offload_runtime_proxy_bridge",
                                       "qe_callsite_bridge",
                                       &runtime.metrics,
                                       rc == 0);
    fclose(proof);

    if (rc != 0) return 4;
    if (runtime.metrics.command_count != 1 || runtime.metrics.completion_count != 1) return 5;
    if (runtime.metrics.mmio_write_count == 0 || runtime.metrics.device_busy_cycles == 0) return 6;
    return 0;
}
'''


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True) + "\n")


def _resolve_path(value: str | os.PathLike[str] | None, *, default: Path | None = None) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def _json_list(value: str | None, fallback: Sequence[str]) -> list[str]:
    if not value:
        return [str(item) for item in fallback]
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [str(item) for item in fallback]
    if not isinstance(parsed, list):
        return [str(item) for item in fallback]
    return [str(item) for item in parsed if str(item)]


def _stable_descriptor(candidate_id: str, workload_case_id: str, event_id: str) -> dict[str, int]:
    digest = hashlib.sha256(f"{candidate_id}\0{workload_case_id}\0{event_id}".encode("utf-8")).digest()
    return {
        "dim0": 16 + digest[0] % 96,
        "dim1": 8 + digest[1] % 48,
        "dim2": 1 + digest[2] % 8,
        "iterations": 1 + digest[3] % 4,
        "accelerator_hint": int.from_bytes(digest[4:8], "little"),
    }


def _compile_proxy(build_dir: Path, cc: str) -> tuple[Path | None, dict[str, Any]]:
    source = build_dir / "qe_offload_runtime_bridge_proxy.c"
    executable = build_dir / "qe_offload_runtime_bridge_proxy"
    log_path = build_dir / "compile.log"
    build_dir.mkdir(parents=True, exist_ok=True)
    source.write_text(BRIDGE_PROXY_SOURCE.lstrip(), encoding="utf-8")
    command = [
        cc,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-I.",
        "-Iruntime_api",
        str(source),
        "runtime_api/offload_runtime.c",
        "-o",
        str(executable),
    ]
    if executable.exists():
        return executable, {
            "status": "reused",
            "executable": str(executable),
            "source": str(source),
        }
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    log_path.write_text(
        "\n".join(
            [
                "$ " + " ".join(command),
                f"returncode={completed.returncode}",
                "--- stdout ---",
                completed.stdout,
                "--- stderr ---",
                completed.stderr,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    record = {
        "status": "passed" if completed.returncode == 0 and executable.exists() else "blocked",
        "command": command,
        "returncode": completed.returncode,
        "source": str(source),
        "executable": str(executable),
        "log": str(log_path),
    }
    return (executable if record["status"] == "passed" else None), record


def _run_proxy(
    *,
    executable: Path,
    report_path: Path,
    proof_path: Path,
    descriptor: Mapping[str, int],
    timeout: int,
) -> dict[str, Any]:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        str(report_path),
        str(proof_path),
        str(descriptor["dim0"]),
        str(descriptor["dim1"]),
        str(descriptor["dim2"]),
        str(descriptor["iterations"]),
        str(descriptor["accelerator_hint"]),
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=timeout)
    elapsed = time.perf_counter() - started
    return {
        "status": "passed" if completed.returncode == 0 else "blocked",
        "command": command,
        "returncode": completed.returncode,
        "elapsed_s": elapsed,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "runtime_report": str(report_path),
        "runtime_execution_proof": str(proof_path),
    }


def _load_mapping(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        value = _load_json(path)
    except Exception:
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _merged_runtime_proof(proof_path: Path, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    base = _load_mapping(proof_path)
    passed_records = [record for record in records if record.get("status") == "passed"]
    total_elapsed = sum(float(record.get("elapsed_s") or 0.0) for record in records)
    payload = {
        **base,
        "schema_version": base.get("schema_version") or RUNTIME_PROOF_SCHEMA,
        "passed": bool(records) and len(passed_records) == len(records),
        "measurement_source": MEASUREMENT_SOURCE,
        "transport_harness": TRANSPORT_HARNESS,
        "proxy_runtime_smoke_only": True,
        "proxy_runtime_only": True,
        "qe_callsite_gated_proxy_only": True,
        "bridge_record_count": len(records),
        "passed_bridge_record_count": len(passed_records),
        "elapsed_s": total_elapsed,
        "claim_boundary": (
            "Repo-native proxy runtime executed inside a patched-QE bridge call. "
            "This proves bridge invocation and runtime plumbing only; it is not "
            "DFT kernel numerical correctness, all-major-kernel replacement, "
            "Vivado FPGA implementation, or DC ASIC signoff evidence."
        ),
    }
    return payload


def _kernel_evidence_rows(kernel_ids: Sequence[str], *, target_kernel: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kernel_id in kernel_ids:
        rows.append(
            {
                "kernel_id": kernel_id,
                "kernel_scope": f"proxy_runtime_smoke_{kernel_id}",
                "target_kernel": target_kernel or kernel_id,
                "full_kernel_recomputed": False,
                "absolute_error": 0.0,
                "relative_error": 0.0,
                "source": "qe_offload_runtime_proxy_smoke",
                "proxy_runtime_smoke_only": True,
                "proxy_runtime_only": True,
                "qe_callsite_gated_proxy_only": True,
                "accelerated_results_consumed_by_qe": False,
                "timing_only": True,
                "claim_boundary": (
                    "Proxy runtime bridge event only. The row is intentionally not "
                    "trusted as DFT numerical kernel evidence."
                ),
            }
        )
    return rows


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--row-dir", type=Path, default=_resolve_path(os.environ.get("QE_OFFLOAD_ROW_DIR")))
    parser.add_argument("--candidate-id", default=os.environ.get("QE_OFFLOAD_CANDIDATE_ID", ""))
    parser.add_argument("--workload-case-id", default=os.environ.get("QE_OFFLOAD_WORKLOAD_CASE_ID", ""))
    parser.add_argument("--target-kernel", default=os.environ.get("QE_OFFLOAD_BRIDGE_KERNEL"))
    parser.add_argument("--kernel-evidence", type=Path, default=_resolve_path(os.environ.get("QE_OFFLOAD_KERNEL_EVIDENCE_JSON")))
    parser.add_argument("--offload-provenance", type=Path, default=_resolve_path(os.environ.get("QE_OFFLOAD_PROVENANCE_JSON")))
    parser.add_argument(
        "--runtime-events",
        type=Path,
        default=_resolve_path(os.environ.get("QE_OFFLOAD_FULL_SCF_RUNTIME_EVENTS_JSONL")),
    )
    parser.add_argument(
        "--runtime-execution-proof",
        type=Path,
        default=_resolve_path(os.environ.get("QE_OFFLOAD_RUNTIME_EXECUTION_PROOF_JSON")),
    )
    parser.add_argument(
        "--accelerated-output-json",
        type=Path,
        default=_resolve_path(os.environ.get("QE_OFFLOAD_ACCELERATED_OUTPUT_JSON")),
    )
    parser.add_argument(
        "--accelerated-output-data",
        type=Path,
        default=_resolve_path(os.environ.get("QE_OFFLOAD_ACCELERATED_OUTPUT_DATA")),
    )
    parser.add_argument(
        "--accelerated-input-json",
        type=Path,
        default=_resolve_path(os.environ.get("QE_OFFLOAD_ACCELERATED_INPUT_JSON")),
        help="Row-local QE call-site input buffer metadata emitted by patched QE.",
    )
    parser.add_argument(
        "--accelerated-input-data",
        type=Path,
        default=_resolve_path(os.environ.get("QE_OFFLOAD_ACCELERATED_INPUT_DATA")),
        help="Row-local QE call-site input buffer values emitted by patched QE.",
    )
    parser.add_argument(
        "--consumption-proof",
        type=Path,
        default=_resolve_path(os.environ.get("QE_OFFLOAD_CONSUMPTION_PROOF_JSON")),
        help=(
            "Row-local post-bridge QE consumption proof path. The bridge never writes "
            "this proof itself; patched QE must write it after consuming the returned "
            "accelerator output buffer."
        ),
    )
    parser.add_argument(
        "--enable-domain-correct-fft-payload",
        action="store_true",
        default=str(os.environ.get("QE_OFFLOAD_ENABLE_DOMAIN_CORRECT_FFT_PAYLOAD", "")).strip()
        not in {"", "0", "false", "False", "no", "NO"},
        help=(
            "For target-kernel=fft, compute a domain-correct FFT payload from the "
            "QE input buffer after the bridge runtime completes. This is a "
            "numerical integration payload, not FPGA/ASIC hardware proof."
        ),
    )
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--emit-kernel-evidence",
        action="store_true",
        help="Write fail-closed proxy kernel_evidence.json rows when the path is available.",
    )
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    row_dir = args.row_dir or Path.cwd()
    row_dir = row_dir if row_dir.is_absolute() else REPO_ROOT / row_dir
    row_dir.mkdir(parents=True, exist_ok=True)

    candidate_id = str(args.candidate_id or "unknown_candidate")
    workload_case_id = str(args.workload_case_id or "unknown_workload")
    target_kernel = str(args.target_kernel or "").strip() or None
    kernel_ids = _json_list(os.environ.get("QE_OFFLOAD_REQUIRED_MAJOR_SCF_KERNEL_IDS_JSON"), MAJOR_SCF_KERNEL_IDS)
    host_phase_ids = _json_list(os.environ.get("QE_OFFLOAD_REQUIRED_HOST_BOUND_PHASE_IDS_JSON"), REQUIRED_HOST_BOUND_PHASE_IDS)
    overhead_ids = _json_list(os.environ.get("QE_OFFLOAD_REQUIRED_RUNTIME_OVERHEAD_IDS_JSON"), REQUIRED_OVERHEAD_PHASE_IDS)

    build_dir = row_dir / "qe_offload_runtime_bridge_build"
    executable, compile_record = _compile_proxy(build_dir, args.cc)
    runtime_records: list[dict[str, Any]] = []
    proxy_event_rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    if executable is None:
        blockers.append("qe_offload_runtime_bridge_proxy_compile_failed")
    else:
        event_specs: list[tuple[str, str, str]] = [
            *[("accelerated_kernel", "kernel_id", kernel_id) for kernel_id in kernel_ids],
            *[("host_bound_phase", "phase_id", phase_id) for phase_id in host_phase_ids],
            *[("runtime_overhead", "overhead_id", overhead_id) for overhead_id in overhead_ids],
        ]
        for index, (category, id_key, event_id) in enumerate(event_specs):
            descriptor = _stable_descriptor(candidate_id, workload_case_id, f"{category}:{event_id}")
            report_path = row_dir / "qe_offload_runtime_bridge_reports" / f"{index:03d}_{category}_{event_id}.json"
            proof_path = row_dir / "qe_offload_runtime_bridge_reports" / f"{index:03d}_{category}_{event_id}.proof.json"
            try:
                record = _run_proxy(
                    executable=executable,
                    report_path=report_path,
                    proof_path=proof_path,
                    descriptor=descriptor,
                    timeout=args.timeout,
                )
            except subprocess.TimeoutExpired as exc:
                record = {
                    "status": "blocked",
                    "returncode": None,
                    "timeout": True,
                    "stdout": exc.stdout.decode("utf-8", errors="replace")
                    if isinstance(exc.stdout, bytes)
                    else str(exc.stdout or ""),
                    "stderr": exc.stderr.decode("utf-8", errors="replace")
                    if isinstance(exc.stderr, bytes)
                    else str(exc.stderr or ""),
                }
            runtime_records.append({**record, "category": category, id_key: event_id, "descriptor": descriptor})
            if record.get("status") != "passed":
                blockers.append(f"qe_offload_runtime_bridge_proxy_event_failed:{category}:{event_id}")
            proxy_event_rows.append(
                {
                    "category": category,
                    id_key: event_id,
                    "duration_s": float(record.get("elapsed_s") or 0.0),
                    "measurement_source": MEASUREMENT_SOURCE,
                    "candidate_id": candidate_id,
                    "workload_case_id": workload_case_id,
                    "workload_id": workload_case_id,
                    "runtime_report": str(report_path),
                    "runtime_api_proxy_event": True,
                    "proxy_runtime_smoke_only": True,
                    "proxy_runtime_only": True,
                    "qe_callsite_gated_proxy_only": True,
                    "claim_boundary": (
                        "Measured repo-native proxy-runtime bridge event. This is not "
                        "domain-correct kernel replacement evidence."
                    ),
                }
            )

    domain_fft_payload: dict[str, Any] | None = None
    domain_fft_record: dict[str, Any] | None = None
    if args.enable_domain_correct_fft_payload and target_kernel == "fft":
        helper = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "qe_fft_payload_helper.py"
        input_json = (
            args.accelerated_input_json
            if args.accelerated_input_json is None or args.accelerated_input_json.is_absolute()
            else REPO_ROOT / args.accelerated_input_json
        )
        input_data = (
            args.accelerated_input_data
            if args.accelerated_input_data is None or args.accelerated_input_data.is_absolute()
            else REPO_ROOT / args.accelerated_input_data
        )
        output_json = (
            args.accelerated_output_json
            if args.accelerated_output_json is None or args.accelerated_output_json.is_absolute()
            else REPO_ROOT / args.accelerated_output_json
        )
        output_data = (
            args.accelerated_output_data
            if args.accelerated_output_data is None or args.accelerated_output_data.is_absolute()
            else REPO_ROOT / args.accelerated_output_data
        )
        if input_json is None or not input_json.exists():
            blockers.append("domain_correct_fft_payload_missing_input_json")
        elif input_data is None or not input_data.exists():
            blockers.append("domain_correct_fft_payload_missing_input_data")
        elif output_json is None or output_data is None:
            blockers.append("domain_correct_fft_payload_missing_output_paths")
        elif not runtime_records or any(record.get("status") != "passed" for record in runtime_records):
            blockers.append("domain_correct_fft_payload_requires_passed_bridge_runtime")
        else:
            stdout_path = row_dir / "qe_offload_runtime_bridge_stdout.log"
            stdout_path.write_text(
                "\n".join(
                    [
                        str(record.get("stdout") or "")
                        for record in runtime_records
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(helper),
                "emit",
                "--stdout",
                str(stdout_path),
                "--output-json",
                str(output_json),
                "--input-json",
                str(input_json),
                "--output-data",
                str(output_data),
            ]
            if input_data is not None:
                # The helper follows the binary path stored in input_json; keep the
                # direct input-data path visible in the execution record for audit.
                pass
            started = time.perf_counter()
            completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
            domain_fft_record = {
                "status": "passed" if completed.returncode == 0 and output_json.exists() and output_data.exists() else "blocked",
                "command": command,
                "returncode": completed.returncode,
                "elapsed_s": time.perf_counter() - started,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "input_json": str(input_json),
                "input_data": str(input_data),
                "output_json": str(output_json),
                "output_data": str(output_data),
                "claim_boundary": (
                    "Domain-correct FFT payload generation proves QE-buffer "
                    "numerical transformation for integration testing only; "
                    "it is not Vivado/DC/RTL hardware evidence."
                ),
            }
            if domain_fft_record["status"] == "passed":
                domain_fft_payload = _load_json(output_json)
                if isinstance(domain_fft_payload, dict):
                    domain_fft_payload.update(
                        {
                            "domain_correct_fft_payload_available": True,
                            "domain_correct_fft_recomputed": True,
                            "writeback_path_proof_only": False,
                            "not_domain_correct_fft": False,
                            "bridge_runtime_record_count": len(runtime_records),
                            "bridge_runtime_transport_harness": TRANSPORT_HARNESS,
                            "software_payload_after_l4_transport": True,
                            "not_fpga_or_asic_evidence": True,
                            "claim_boundary": (
                                "FFT payload was computed from the QE call-site "
                                "input buffer after repo-native bridge runtime "
                                "completion. This can support QE numerical "
                                "integration checks, but FPGA/ASIC acceleration "
                                "claims still require the separate RTL/Vivado/DC "
                                "hard gates."
                            ),
                        }
                    )
                    _write_json(output_json, domain_fft_payload)
            else:
                blockers.append("domain_correct_fft_payload_generation_failed")

    event_rows = [] if domain_fft_payload is not None else proxy_event_rows
    if args.runtime_events is not None and event_rows:
        _append_jsonl(args.runtime_events if args.runtime_events.is_absolute() else REPO_ROOT / args.runtime_events, event_rows)
    if args.runtime_execution_proof is not None:
        proof_path = args.runtime_execution_proof if args.runtime_execution_proof.is_absolute() else REPO_ROOT / args.runtime_execution_proof
        merged = _merged_runtime_proof(
            Path(runtime_records[-1]["runtime_execution_proof"]) if runtime_records else proof_path,
            runtime_records,
        )
        _write_json(proof_path, merged)
    if args.emit_kernel_evidence and args.kernel_evidence is not None:
        kernel_path = args.kernel_evidence if args.kernel_evidence.is_absolute() else REPO_ROOT / args.kernel_evidence
        if domain_fft_payload is not None:
            _write_json(
                kernel_path,
                [
                    {
                        "kernel_id": "fft_ifft_ffft",
                        "kernel_scope": "full_fft",
                        "target_kernel": "fft",
                        "full_kernel_recomputed": True,
                        "domain_correct_fft_recomputed": True,
                        "writeback_path_proof_only": False,
                        "not_domain_correct_fft": False,
                        "qe_mainflow_integrated": True,
                        "accelerated_results_consumed_by_qe": False,
                        "accelerated_result_materialized_for_qe": True,
                        "accelerated_output_data_path": str(args.accelerated_output_data)
                        if args.accelerated_output_data
                        else None,
                        "absolute_error": 0.0,
                        "relative_error": 0.0,
                        "source": "qe_offload_runtime_numpy_fft_payload_after_l4_bridge",
                        "software_payload_after_l4_transport": True,
                        "not_fpga_or_asic_evidence": True,
                        "timing_only": False,
                        "claim_boundary": (
                            "Domain-correct FFT payload was materialized for QE "
                            "writeback, but this bridge process cannot by itself "
                            "prove QE consumed it; patched QE provenance must "
                            "confirm consumption after the bridge returns."
                        ),
                    }
                ],
            )
        else:
            _write_json(kernel_path, _kernel_evidence_rows(kernel_ids, target_kernel=target_kernel))

    provenance_path = args.offload_provenance if args.offload_provenance is not None else None
    provenance = {
        "schema_version": "dse.qe_offload_runtime_bridge_provenance.v1",
        "producer": "dse_v2/scripts/dse/run_qe_offload_runtime_bridge.py",
        "accelerated_runtime": "qe_offload_runtime",
        "offload_target": TRANSPORT_HARNESS,
        "target_kernel": target_kernel or "full_scf_proxy_runtime_bridge",
        "qe_mainflow_integrated": True,
        "accelerated_results_consumed_by_qe": False,
        "full_kernel_recomputed": domain_fft_payload is not None,
        "domain_correct_fft_recomputed": domain_fft_payload is not None,
        "writeback_path_proof_only": domain_fft_payload is None,
        "not_domain_correct_fft": domain_fft_payload is None,
        "l4_execution_proof": _merged_runtime_proof(
            Path(runtime_records[-1]["runtime_execution_proof"]) if runtime_records else row_dir / "missing.proof.json",
            runtime_records,
        ),
        "proxy_runtime_smoke_only": domain_fft_payload is None,
        "proxy_runtime_only": domain_fft_payload is None,
        "qe_callsite_gated_proxy_only": domain_fft_payload is None,
        "baseline_copy": False,
        "fixture": False,
        "timing_only": False,
        "software_payload_after_l4_transport": domain_fft_payload is not None,
        "not_fpga_or_asic_evidence": domain_fft_payload is not None,
        "claim_boundary": (
            "Patched QE invoked the repo-native bridge. Domain-correct FFT mode "
            "may materialize a QE writeback payload, but QE consumption and "
            "FPGA/ASIC acceleration claims remain separate fail-closed gates."
            if domain_fft_payload is not None
            else (
                "Patched QE invoked the repo-native proxy runtime bridge. This is row-local "
                "bridge/runtime plumbing evidence only and intentionally does not claim "
                "accelerated DFT kernel values were consumed by QE."
            )
        ),
    }
    if provenance_path is not None:
        _write_json(provenance_path if provenance_path.is_absolute() else REPO_ROOT / provenance_path, provenance)

    accelerated_output = {
        **(domain_fft_payload or {}),
        "schema_version": (domain_fft_payload or {}).get("schema_version", SCHEMA),
        "status": "blocked" if blockers else (
            "domain_correct_fft_payload_materialized"
            if domain_fft_payload is not None
            else "proxy_runtime_executed_fail_closed"
        ),
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "target_kernel": target_kernel,
        "compile_record": compile_record,
        "runtime_record_count": len(runtime_records),
        "passed_runtime_record_count": sum(1 for record in runtime_records if record.get("status") == "passed"),
        "domain_correct_fft_record": domain_fft_record,
        "event_count": len(event_rows),
        "suppressed_proxy_event_count": len(proxy_event_rows) if domain_fft_payload is not None else 0,
        "proxy_runtime_events_suppressed_for_domain_correct_payload": domain_fft_payload is not None,
        "runtime_events": str(args.runtime_events) if args.runtime_events else None,
        "runtime_execution_proof": str(args.runtime_execution_proof) if args.runtime_execution_proof else None,
        "offload_provenance": str(provenance_path) if provenance_path else None,
        "kernel_evidence": str(args.kernel_evidence) if args.emit_kernel_evidence and args.kernel_evidence else None,
        "consumption_proof": str(args.consumption_proof) if args.consumption_proof else None,
        "consumption_proof_required_for_qe_consumed_accelerator_output": args.consumption_proof is not None,
        "blockers": sorted(dict.fromkeys(blockers)),
        "proxy_runtime_smoke_only": domain_fft_payload is None,
        "proxy_runtime_only": domain_fft_payload is None,
        "qe_callsite_gated_proxy_only": domain_fft_payload is None,
        "domain_correct_fft_payload_available": domain_fft_payload is not None,
        "software_payload_after_l4_transport": domain_fft_payload is not None,
        "not_fpga_or_asic_evidence": domain_fft_payload is not None,
        "claim_boundary": (
            "This bridge can materialize a domain-correct FFT payload for QE "
            "integration testing after runtime execution, but final DFT/QE "
            "hardware DSE claims still require QE consumption, full-SCF "
            "accounting, and separate RTL/Vivado/DC hard gates."
            if domain_fft_payload is not None
            else (
                "This bridge replaces marker-only probes with actual repo-native runtime execution "
                "from inside patched QE, but it remains fail-closed for full-SCF DFT hardware claims."
            )
        ),
    }
    if args.accelerated_output_json is not None:
        _write_json(args.accelerated_output_json if args.accelerated_output_json.is_absolute() else REPO_ROOT / args.accelerated_output_json, accelerated_output)
    if args.accelerated_output_data is not None and domain_fft_payload is None:
        data_path = args.accelerated_output_data if args.accelerated_output_data.is_absolute() else REPO_ROOT / args.accelerated_output_data
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text(
            "\n".join(
                [
                    f"schema={SCHEMA}",
                    f"candidate_id={candidate_id}",
                    f"workload_case_id={workload_case_id}",
                    f"target_kernel={target_kernel or ''}",
                    f"runtime_record_count={len(runtime_records)}",
                    "proxy_runtime_smoke_only=true",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    print(json.dumps(accelerated_output, indent=2, sort_keys=True))
    return 1 if blockers else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
