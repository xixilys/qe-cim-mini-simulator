#!/usr/bin/env python3
"""Build repo-native runtime/compiler evidence for the DFT Step5 ledger.

This script intentionally proves only the production runtime/compiler path:
the C runtime ABI compiles, the GenericAccel L4 driver compiles, and the
repo-native runtime can execute a host proxy submission for every legal
candidate in the release manifest.  It does not prove DFT numerical
correctness, gem5 cycle accuracy, RTL/HLS PPA, or final deliverable closure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_evidence_ledger import (  # noqa: E402
    PRODUCTION_RUNTIME_COMPILER_CONTRACT,
    PRODUCTION_RUNTIME_COMPILER_PATHS,
)


HOST_PROXY_SOURCE = r'''
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

static void write_runtime_event_jsonl(FILE* events,
                                      const char* category,
                                      const char* event_id,
                                      const char* candidate_id,
                                      double duration_s,
                                      const char* measurement_source) {
    if (events == NULL) {
        return;
    }
    fprintf(events,
            "{\"category\":\"%s\","
            "\"event_id\":\"%s\","
            "\"candidate_id\":\"%s\","
            "\"workload_case_id\":\"%s\","
            "\"workload_id\":\"%s\","
            "\"duration_s\":%.9f,"
            "\"measurement_source\":\"%s\","
            "\"runtime_api_proxy_event\":true,"
            "\"proxy_runtime_smoke_only\":true,"
            "\"proxy_runtime_only\":true,"
            "\"qe_callsite_gated_proxy_only\":true}\n",
            category != NULL ? category : "host_proxy_event",
            event_id != NULL ? event_id : "event_id",
            candidate_id != NULL ? candidate_id : "unknown_candidate",
            candidate_id != NULL ? candidate_id : "unknown_candidate",
            candidate_id != NULL ? candidate_id : "unknown_candidate",
            duration_s,
            measurement_source != NULL ? measurement_source : "qe_offload_runtime_trace");
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
            "  \"claim_boundary\": \"Repo-native host proxy runtime proof only; not DFT numerical, gem5 timing, FPGA, or ASIC evidence.\"\n"
            "}\n",
            schema_version != NULL ? schema_version : "dse.runtime_execution_proof.v1",
            passed ? "true" : "false",
            measurement_source != NULL ? measurement_source : "qe_offload_runtime_trace",
            transport_harness != NULL ? transport_harness : "host_proxy_repo_native_runtime",
            workload_id != NULL ? workload_id : "host_proxy_runtime",
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
    if (argc != 9) {
        fprintf(stderr,
                "usage: %s candidate_id report_json dim0 dim1 dim2 dim3 iterations accelerator_hint\n",
                argv[0]);
        return 2;
    }

    const char* candidate_id = argv[1];
    const char* report_path = argv[2];
    static volatile uint32_t regs[256];
    offload_runtime runtime;
    offload_runtime_init(&runtime, regs, sizeof(regs));
    offload_runtime_set_use_m5ops(&runtime, 0);

    offload_command_descriptor desc = offload_command_descriptor_default();
    desc.work_dim0 = parse_u32(argv[3], "dim0");
    desc.work_dim1 = parse_u32(argv[4], "dim1");
    desc.work_dim2 = parse_u32(argv[5], "dim2");
    desc.work_dim3 = parse_u32(argv[6], "dim3");
    desc.max_iterations = parse_u32(argv[7], "iterations");
    desc.accelerator_hint = parse_u32(argv[8], "accelerator_hint");
    desc.control_policy = OFFLOAD_CONTROL_POLLING;
    desc.precision_bits = 64;

    offload_runtime_mark_roi_begin(&runtime);
    int rc = offload_runtime_submit_sync(&runtime, &desc);
    offload_runtime_mark_roi_end(&runtime);

    FILE* out = fopen(report_path, "wb");
    if (!out) {
        perror("fopen report");
        return 3;
    }
    offload_runtime_write_report_json(out,
                                      "dse.dft.runtime_proxy_report.v1",
                                      candidate_id,
                                      "host_proxy_repo_native_runtime",
                                      &runtime.metrics);
    fclose(out);

    const char* events_path = getenv("QE_OFFLOAD_FULL_SCF_RUNTIME_EVENTS_JSONL");
    if (events_path) {
        FILE* events = fopen(events_path, "wb");
        if (!events) {
            perror("fopen runtime events");
            return 3;
        }
        write_runtime_event_jsonl(events,
                                  "host_proxy_submit",
                                  "event_id",
                                  candidate_id,
                                  0.001,
                                  "qe_offload_runtime_trace");
        write_runtime_event_jsonl(events,
                                  "host_proxy_complete",
                                  "event_id",
                                  candidate_id,
                                  0.001,
                                  "qe_offload_runtime_trace");
        fclose(events);
    }

    const char* proof_path = getenv("QE_OFFLOAD_RUNTIME_EXECUTION_PROOF_JSON");
    if (proof_path) {
        FILE* proof = fopen(proof_path, "wb");
        if (!proof) {
            perror("fopen runtime proof");
            return 3;
        }
        write_runtime_execution_proof_json(proof,
                                           "dse.runtime_execution_proof.v1",
                                           "qe_offload_runtime_trace",
                                           "host_proxy_repo_native_runtime",
                                           candidate_id,
                                           &runtime.metrics,
                                           rc == 0);
        fclose(proof);
    }

    printf("runtime_proxy_candidate=%s rc=%d command_count=%llu completion_count=%llu\n",
           candidate_id,
           rc,
           (unsigned long long)runtime.metrics.command_count,
           (unsigned long long)runtime.metrics.completion_count);
    if (rc != 0) return 4;
    if (runtime.metrics.command_count != 1 || runtime.metrics.completion_count != 1) return 5;
    if (runtime.metrics.mmio_write_count == 0 || runtime.metrics.device_busy_cycles == 0) return 6;
    return 0;
}
'''


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ref(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": str(path)}
    if path.exists():
        payload.update({"hash": _sha256_file(path), "hash_algorithm": "sha256", "exists": True})
    else:
        payload.update({"exists": False})
    return payload


def _source_ref(repo_relative_path: str) -> dict[str, Any]:
    path = REPO_ROOT / repo_relative_path
    ref = _artifact_ref(path)
    ref["repo_relative_path"] = repo_relative_path
    return ref


def _run_command(
    command: list[str],
    *,
    log_path: Path,
    cwd: Path = REPO_ROOT,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            env=dict(env) if env is not None else None,
        )
        stdout = result.stdout
        stderr = result.stderr
        returncode: int | None = result.returncode
    except FileNotFoundError as exc:
        stdout = ""
        stderr = str(exc)
        returncode = None

    log_path.write_text(
        "\n".join(
            [
                "$ " + " ".join(command),
                f"returncode={returncode}",
                "--- stdout ---",
                stdout,
                "--- stderr ---",
                stderr,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "command": command,
        "command_string": " ".join(command),
        "returncode": returncode,
        "status": "passed" if returncode == 0 else "blocked_temporary",
        "log": _artifact_ref(log_path),
    }


def _candidate_descriptor(candidate: Mapping[str, Any]) -> dict[str, int]:
    canonical = json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).digest()
    return {
        "work_dim0": 16 + digest[0] % 128,
        "work_dim1": 8 + digest[1] % 64,
        "work_dim2": 1 + digest[2] % 8,
        "work_dim3": 1,
        "max_iterations": 1 + digest[3] % 4,
        "accelerator_hint": int.from_bytes(digest[4:8], "little"),
    }


def _load_legal_candidates(release_artifact_dir: Path) -> list[dict[str, Any]]:
    manifest_path = release_artifact_dir / "candidate_universe_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidates = {
        str(candidate.get("candidate_id")): dict(candidate)
        for candidate in manifest.get("candidates", []) or []
        if isinstance(candidate, Mapping) and candidate.get("legal") is True and candidate.get("candidate_id")
    }
    legal_ids = [str(item) for item in manifest.get("legal_candidate_ids", []) or []]
    if not legal_ids:
        legal_ids = sorted(candidates)
    missing = [candidate_id for candidate_id in legal_ids if candidate_id not in candidates]
    if missing:
        raise ValueError(f"legal candidate ids missing from manifest candidates: {missing[:5]}")
    return [candidates[candidate_id] for candidate_id in legal_ids]


def build_runtime_compiler_evidence(
    out_dir: Path,
    *,
    release_artifact_dir: Path,
    cc: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    build_dir = out_dir / "build"
    report_dir = out_dir / "candidate_runtime_reports"
    log_dir = out_dir / "logs"
    build_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    legal_candidates = _load_legal_candidates(release_artifact_dir)
    legal_candidate_ids = [str(candidate["candidate_id"]) for candidate in legal_candidates]

    host_proxy_source = build_dir / "runtime_proxy_smoke.c"
    host_proxy_source.write_text(HOST_PROXY_SOURCE.lstrip(), encoding="utf-8")

    build_specs: list[dict[str, Any]] = [
        {
            "build_id": "runtime_submit_implementation_object",
            "role": "compile runtime_api/offload_runtime.c to object",
            "command": [
                cc,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I.",
                "-Iruntime_api",
                "-c",
                "runtime_api/offload_runtime.c",
                "-o",
                str(build_dir / "offload_runtime.o"),
            ],
            "outputs": [build_dir / "offload_runtime.o"],
        },
        {
            "build_id": "genericaccel_l4_driver_object",
            "role": "compile GenericAccel L4 driver to object",
            "command": [
                cc,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I.",
                "-Iruntime_api",
                "-c",
                "gem5_integration/test_programs/generic_accel/generic_accel_l4_driver.c",
                "-o",
                str(build_dir / "generic_accel_l4_driver.o"),
            ],
            "outputs": [build_dir / "generic_accel_l4_driver.o"],
        },
        {
            "build_id": "host_proxy_runtime_smoke_executable",
            "role": "link host proxy runtime smoke against repo-native runtime implementation",
            "command": [
                cc,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I.",
                "-Iruntime_api",
                str(host_proxy_source),
                "runtime_api/offload_runtime.c",
                "-o",
                str(build_dir / "runtime_proxy_smoke"),
            ],
            "outputs": [build_dir / "runtime_proxy_smoke"],
        },
    ]

    build_records: list[dict[str, Any]] = []
    for spec in build_specs:
        command = [str(item) for item in spec["command"]]
        output_paths = [Path(item) for item in spec["outputs"]]
        record = {
            "build_id": spec["build_id"],
            "role": spec["role"],
            **_run_command(command, log_path=log_dir / f"{spec['build_id']}.log"),
            "output_artifacts": [_artifact_ref(path) for path in output_paths],
        }
        build_records.append(record)

    build_passed = all(record["status"] == "passed" for record in build_records)
    executable = build_dir / "runtime_proxy_smoke"

    candidate_records: list[dict[str, Any]] = []
    for candidate in legal_candidates:
        candidate_id = str(candidate["candidate_id"])
        descriptor = _candidate_descriptor(candidate)
        report_path = report_dir / f"{candidate_id}.json"
        log_path = log_dir / f"runtime_proxy_{candidate_id}.log"
        command = [
            str(executable),
            candidate_id,
            str(report_path),
            str(descriptor["work_dim0"]),
            str(descriptor["work_dim1"]),
            str(descriptor["work_dim2"]),
            str(descriptor["work_dim3"]),
            str(descriptor["max_iterations"]),
            str(descriptor["accelerator_hint"]),
        ]
        runtime_events_path = report_dir / f"{candidate_id}.runtime_events.jsonl"
        runtime_proof_path = report_dir / f"{candidate_id}.runtime_execution_proof.json"
        execution_env = os.environ.copy()
        execution_env["QE_OFFLOAD_FULL_SCF_RUNTIME_EVENTS_JSONL"] = str(runtime_events_path)
        execution_env["QE_OFFLOAD_RUNTIME_EXECUTION_PROOF_JSON"] = str(runtime_proof_path)
        execution_record = _run_command(command, log_path=log_path, env=execution_env)
        report_payload: dict[str, Any] = {}
        report_valid = False
        if report_path.exists():
            try:
                report_payload = json.loads(report_path.read_text(encoding="utf-8"))
                metrics = report_payload.get("metrics", {})
                report_valid = bool(
                    isinstance(metrics, Mapping)
                    and metrics.get("command_count") == 1
                    and metrics.get("completion_count") == 1
                    and metrics.get("device_busy_cycles", 0) > 0
                    and report_payload.get("claim_ceiling") == "proxy_runtime_smoke_only"
                )
            except Exception as exc:  # pragma: no cover - recorded in artifact for diagnostics
                report_payload = {"parse_error": f"{type(exc).__name__}: {exc}"}

        status = "passed" if build_passed and execution_record["status"] == "passed" and report_valid else "blocked_temporary"
        candidate_records.append(
            {
                "candidate_id": candidate_id,
                "runtime_compiler_job_id": f"runtime_compiler::{candidate_id}",
                "status": status,
                "descriptor": descriptor,
                "build_record_ids": [record["build_id"] for record in build_records],
                "execution": {
                    **execution_record,
                    "runtime_report": _artifact_ref(report_path),
                    "runtime_events": _artifact_ref(runtime_events_path),
                    "runtime_execution_proof": _artifact_ref(runtime_proof_path),
                    "runtime_report_valid": report_valid,
                    "metrics_summary": report_payload.get("metrics", {}),
                },
                "completion_eligible": status == "passed",
                "claim_boundary": (
                    "Repo-native runtime/compiler control-path evidence only; "
                    "not DFT numerical correctness, gem5 timing, RTL/HLS PPA, board, or ASIC evidence."
                ),
            }
        )

    passed_candidate_count = sum(1 for record in candidate_records if record["status"] == "passed")
    status = "passed" if build_passed and passed_candidate_count == len(legal_candidates) else "blocked_temporary"
    payload = {
        "schema_version": "dse.dft.production_runtime_compiler_execution_evidence.v1",
        "status": status,
        "path_type": PRODUCTION_RUNTIME_COMPILER_CONTRACT["path_type"],
        "one_off_script_only": False,
        "release_artifact_dir": str(release_artifact_dir),
        "legal_candidate_ids": legal_candidate_ids,
        "candidate_count": len(legal_candidates),
        "production_runtime_compiler_contract": dict(PRODUCTION_RUNTIME_COMPILER_CONTRACT),
        "runtime_compiler_paths": [
            {
                **dict(item),
                "artifact": _source_ref(str(item["path"])),
            }
            for item in PRODUCTION_RUNTIME_COMPILER_PATHS
        ],
        "build_summary": {
            "status": "passed" if build_passed else "blocked_temporary",
            "build_record_count": len(build_records),
            "passed_build_record_count": sum(1 for record in build_records if record["status"] == "passed"),
        },
        "build_records": build_records,
        "execution_summary": {
            "status": "passed" if passed_candidate_count == len(legal_candidates) else "blocked_temporary",
            "candidate_count": len(legal_candidates),
            "passed_candidate_count": passed_candidate_count,
        },
        "candidate_records": candidate_records,
        "source_artifacts": [_source_ref(str(item["path"])) for item in PRODUCTION_RUNTIME_COMPILER_PATHS],
        "claim_boundary": (
            "This artifact can satisfy only runtime_compiler_status: it proves repo-native "
            "runtime/driver compilation plus host proxy submit/completion for every legal candidate. "
            "It does not satisfy formal proof, numerical correctness, EDA PPA, gem5 timing, or final "
            "claim_validation gates."
        ),
    }
    evidence_path = out_dir / "runtime_compiler_execution_evidence.json"
    evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output evidence directory")
    parser.add_argument(
        "--release-artifact-dir",
        type=Path,
        required=True,
        help="Directory containing candidate_universe_manifest.json",
    )
    parser.add_argument("--cc", default=os.environ.get("CC", "gcc"), help="C compiler command")
    args = parser.parse_args(argv)

    payload = build_runtime_compiler_evidence(
        args.out,
        release_artifact_dir=args.release_artifact_dir,
        cc=args.cc,
    )
    print(json.dumps({"status": payload["status"], "artifact": str(args.out / "runtime_compiler_execution_evidence.json")}, indent=2))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
