#!/usr/bin/env python3
"""GPU baseline building for QE-IC real opportunity campaigns."""

from __future__ import annotations

import math
import subprocess
import statistics
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from dse_v2.evidence.qe_ic.gpu_baseline import validate_qe_ic_gpu_baseline_measurements
from dse_v2.evidence.qe_ic.schema import GPU_BASELINE_CLAIM_BOUNDARY


REQUIRED_RUN_FIELDS = (
    "workload_family_id",
    "case_id",
    "program",
    "input_deck_hash",
    "precision",
    "runtime_seconds",
    "profile_artifact_hash",
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def _mean_or_none(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _availability(values: list[float | None]) -> str:
    return "measured" if any(value is not None for value in values) else "unavailable"


def _t_critical_95_two_sided(df: int) -> float:
    table = {
        1: 12.706204736432095,
        2: 4.302652729911275,
        3: 3.182446305284263,
        4: 2.7764451051977987,
        5: 2.5705818366147395,
        6: 2.4469118487916806,
        7: 2.3646242515927844,
        8: 2.306004135204166,
        9: 2.2621571627409915,
        10: 2.2281388519649385,
    }
    return table.get(df, 1.959963984540054)


def _runtime_stats(runs: list[float]) -> dict[str, Any]:
    mean = statistics.mean(runs)
    std = statistics.stdev(runs) if len(runs) > 1 else 0.0
    ci_delta = _t_critical_95_two_sided(len(runs) - 1) * std / math.sqrt(len(runs)) if len(runs) > 1 else 0.0
    return {
        "runtime_seconds_runs": runs,
        "runtime_seconds_mean": mean,
        "runtime_seconds_std": std,
        "confidence_interval_95": {
            "low": mean - ci_delta,
            "high": mean + ci_delta,
        },
    }


def _sha256_text(text: str) -> str:
    return "sha256:" + sha256(text.encode("utf-8", errors="replace")).hexdigest()


def build_gpu_baseline_measurements(
    *,
    run_records: Sequence[Mapping[str, Any]] | None = None,
    platform: Mapping[str, Any] | None = None,
    provided_artifact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build or validate a GPU-only baseline artifact from real supplied runs."""

    if provided_artifact is not None:
        validation = validate_qe_ic_gpu_baseline_measurements(provided_artifact)
        if validation["status"] == "passed" and provided_artifact.get("measurements_are_real") is True:
            return {
                "evidence_status": "measured",
                "measurements_are_real": True,
                "artifact": dict(provided_artifact),
                "validation": validation,
                "blocker_reasons": [],
            }
        return {
            "evidence_status": "evidence_missing",
            "measurements_are_real": False,
            "artifact": None,
            "validation": validation,
            "blocker_reasons": ["provided_gpu_baseline_not_valid_real_measurement"],
        }

    records = [dict(record) for record in (run_records or [])]
    if not records:
        return {
            "evidence_status": "evidence_missing",
            "measurements_are_real": False,
            "artifact": None,
            "validation": {
                "status": "not_applicable",
                "errors": [],
                "warnings": [{"field": "run_records", "message": "no GPU baseline run records supplied"}],
            },
            "blocker_reasons": ["gpu_baseline_runs_missing"],
        }
    missing = [
        field
        for field in REQUIRED_RUN_FIELDS
        if any(field not in record or record.get(field) in (None, "") for record in records)
    ]
    if missing:
        return {
            "evidence_status": "evidence_missing",
            "measurements_are_real": False,
            "artifact": None,
            "validation": {"status": "failed", "errors": [{"field": "run_records", "message": f"missing {missing}"}]},
            "blocker_reasons": ["gpu_baseline_run_record_incomplete"],
        }

    groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        runtime = _number(record.get("runtime_seconds"))
        if runtime is None or runtime <= 0.0:
            return {
                "evidence_status": "evidence_missing",
                "measurements_are_real": False,
                "artifact": None,
                "validation": {"status": "failed", "errors": [{"field": "runtime_seconds", "message": "runtime must be positive"}]},
                "blocker_reasons": ["gpu_baseline_runtime_invalid"],
            }
        key = (
            str(record["workload_family_id"]),
            str(record["case_id"]),
            str(record["program"]),
            str(record["input_deck_hash"]),
            str(record["precision"]),
        )
        groups[key].append(record)

    baseline_records: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        if len(group) < 3:
            return {
                "evidence_status": "evidence_missing",
                "measurements_are_real": False,
                "artifact": None,
                "validation": {"status": "failed", "errors": [{"field": "runtime_seconds_runs", "message": "at least three runs required"}]},
                "blocker_reasons": ["minimum_repeated_runs_missing"],
            }
        runtimes = [float(record["runtime_seconds"]) for record in group]
        stats = _runtime_stats(runtimes)
        gpu_utils = [_number(record.get("gpu_utilization")) for record in group]
        bw_utils = [_number(record.get("gpu_memory_bandwidth_utilization")) for record in group]
        transfers = [_number(record.get("host_device_transfer_seconds")) for record in group]
        comms = [_number(record.get("communication_seconds")) for record in group]
        first = group[0]
        baseline_records.append(
            {
                "baseline_id": f"gpu_baseline_{key[0]}_{key[1]}",
                "workload_family_id": key[0],
                "case_id": key[1],
                "program": key[2],
                "input_deck_hash": key[3],
                "precision": key[4],
                "target_type": "gpu_only",
                **stats,
                "gpu_utilization_mean": _mean_or_none([value for value in gpu_utils if value is not None]),
                "gpu_memory_bandwidth_utilization_mean": _mean_or_none([value for value in bw_utils if value is not None]),
                "host_device_transfer_seconds": _mean_or_none([value for value in transfers if value is not None]),
                "communication_seconds": _mean_or_none([value for value in comms if value is not None]),
                "profile_artifact_hash": str(first["profile_artifact_hash"]),
                "evidence_status": "measured",
                "metric_availability": {
                    "gpu_utilization_mean": _availability(gpu_utils),
                    "gpu_memory_bandwidth_utilization_mean": _availability(bw_utils),
                    "host_device_transfer_seconds": _availability(transfers),
                    "communication_seconds": _availability(comms),
                },
            }
        )

    platform_map = _as_mapping(platform)
    artifact = {
        "schema_version": "dse.qe_ic.gpu_baseline_measurements.v1",
        "measurement_role": "gpu_only_baseline",
        "evidence_status": "measured",
        "measurements_are_real": True,
        "platform": {
            "gpu_name": str(platform_map.get("gpu_name") or "unknown_gpu"),
            "cpu_name": str(platform_map.get("cpu_name") or "unknown_cpu"),
            "memory": str(platform_map.get("memory") or "unknown_memory"),
            "qe_version": str(platform_map.get("qe_version") or "unknown_qe"),
            "cuda_version": str(platform_map.get("cuda_version") or "unknown_cuda"),
            "driver_version": str(platform_map.get("driver_version") or "unknown_driver"),
            "precision": str(platform_map.get("precision") or baseline_records[0]["precision"]),
        },
        "baseline_records": baseline_records,
        "claim_boundary": GPU_BASELINE_CLAIM_BOUNDARY,
    }
    validation = validate_qe_ic_gpu_baseline_measurements(artifact)
    if validation["status"] != "passed":
        return {
            "evidence_status": "evidence_missing",
            "measurements_are_real": False,
            "artifact": None,
            "validation": validation,
            "blocker_reasons": ["gpu_baseline_schema_validation_failed"],
        }
    return {
        "evidence_status": "measured",
        "measurements_are_real": True,
        "artifact": artifact,
        "validation": validation,
        "blocker_reasons": [],
    }


def baseline_from_ingest_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build baseline from either a full artifact or {platform, run_records} payload."""

    if not isinstance(payload, Mapping):
        return build_gpu_baseline_measurements(run_records=[], platform={})
    if payload.get("schema_version") == "dse.qe_ic.gpu_baseline_measurements.v1":
        return build_gpu_baseline_measurements(provided_artifact=payload)
    return build_gpu_baseline_measurements(
        run_records=[row for row in _as_list(payload.get("run_records")) if isinstance(row, Mapping)],
        platform=_as_mapping(payload.get("platform")),
    )


def run_gpu_baseline_commands_if_available(
    *,
    cases: Sequence[Mapping[str, Any]],
    environment_summary: Mapping[str, Any],
    repeat_count: int = 3,
    timeout_seconds: int = 3600,
    run_root: Path | None = None,
) -> dict[str, Any]:
    """Run ready GPU-only baseline commands when the local environment allows it."""

    ready_cases = [
        case
        for case in cases
        if isinstance(case, Mapping)
        and case.get("case_status") == "ready"
        and isinstance(case.get("run_command"), str)
        and case.get("run_command")
    ]
    if not ready_cases:
        result = build_gpu_baseline_measurements(run_records=[], platform={})
        blockers = [
            "blocked_by_missing_input_deck"
            if any(isinstance(case, Mapping) and case.get("case_status") == "input_deck_missing" for case in cases)
            else "gpu_baseline_runs_missing"
        ]
        result["blocker_reasons"] = blockers
        return result
    gpu = _as_mapping(environment_summary.get("gpu"))
    tools = _as_mapping(environment_summary.get("tools"))
    qe_tools = _as_mapping(tools.get("qe"))
    run_records: list[dict[str, Any]] = []
    execution_records: list[dict[str, Any]] = []
    for case in ready_cases:
        program = str(case.get("program"))
        if not qe_tools.get(program):
            return {
                "evidence_status": "evidence_missing",
                "measurements_are_real": False,
                "artifact": None,
                "validation": {
                    "status": "failed",
                    "errors": [{"field": "environment.tools.qe", "message": f"{program} not available"}],
                },
                "blocker_reasons": ["blocked_by_missing_qe"],
            }
        command = str(case["run_command"])
        for run_index in range(repeat_count):
            run_dir = (run_root or Path("runs/qe_ic_real_opportunity_campaign")) / str(case["case_id"]) / "gpu_baseline"
            run_dir.mkdir(parents=True, exist_ok=True)
            stdout_path = run_dir / f"run_{run_index + 1:03d}.stdout.log"
            stderr_path = run_dir / f"run_{run_index + 1:03d}.stderr.log"
            start_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            start = time.perf_counter()
            result = subprocess.run(
                command,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            elapsed = time.perf_counter() - start
            end_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            stdout_path.write_text(result.stdout or "", encoding="utf-8")
            stderr_path.write_text(result.stderr or "", encoding="utf-8")
            output_hash = _sha256_text((result.stdout or "") + (result.stderr or ""))
            if result.returncode != 0:
                return {
                    "evidence_status": "evidence_missing",
                    "measurements_are_real": False,
                    "artifact": None,
                    "validation": {
                        "status": "failed",
                        "errors": [{"field": "run_command", "message": f"command failed on run {run_index + 1}"}],
                    },
                    "blocker_reasons": ["gpu_baseline_command_failed"],
                    "run_records": execution_records,
                }
            profile_hash = output_hash
            execution_record = {
                "workload_family_id": case["workload_family_id"],
                "case_id": case["case_id"],
                "program": program,
                "input_deck_hash": case["input_deck_hash"],
                "precision": case["precision"],
                "command": command,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "runtime_seconds": elapsed,
                "exit_code": result.returncode,
                "stdout_log_path": str(stdout_path),
                "stderr_log_path": str(stderr_path),
                "output_hash": output_hash,
                "profile_artifact_hash": profile_hash,
                "nvidia_smi_log_path": None,
                "gpu_utilization": None,
                "gpu_memory_bandwidth_utilization": None,
                "host_device_transfer_seconds": None,
                "communication_seconds": None,
            }
            execution_records.append(execution_record)
            run_records.append(
                {
                    key: execution_record[key]
                    for key in (
                        "workload_family_id",
                        "case_id",
                        "program",
                        "input_deck_hash",
                        "precision",
                        "runtime_seconds",
                        "gpu_utilization",
                        "gpu_memory_bandwidth_utilization",
                        "host_device_transfer_seconds",
                        "communication_seconds",
                        "profile_artifact_hash",
                    )
                }
            )
    baseline = build_gpu_baseline_measurements(
        run_records=run_records,
        platform={
            "gpu_name": str(gpu.get("gpu_model") or "unknown_gpu"),
            "cpu_name": "local_host",
            "memory": str(gpu.get("gpu_memory_total_mib") or "unknown_memory"),
            "qe_version": "unknown_qe",
            "cuda_version": str(gpu.get("cuda_version") or "unknown_cuda"),
            "driver_version": str(gpu.get("driver_version") or "unknown_driver"),
            "precision": str(ready_cases[0].get("precision") or "unknown_precision"),
        },
    )
    baseline["run_records"] = execution_records
    return baseline
