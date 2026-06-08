#!/usr/bin/env python3
"""GPU baseline building for QE-IC real opportunity campaigns."""

from __future__ import annotations

import math
import os
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


def _qe_program_record(environment_summary: Mapping[str, Any], program: str) -> Mapping[str, Any]:
    discovery = _as_mapping(_as_mapping(_as_mapping(environment_summary.get("tools")).get("qe_discovery")).get("programs"))
    return _as_mapping(discovery.get(program))


def _qe_gpu_support(environment_summary: Mapping[str, Any], program: str) -> str:
    return str(_qe_program_record(environment_summary, program).get("gpu_support") or "unknown")


def _qe_is_gpu_capable(environment_summary: Mapping[str, Any], program: str) -> bool:
    return _qe_gpu_support(environment_summary, program) != "not_detected"


def _qe_gpu_build_failed(environment_summary: Mapping[str, Any], program: str | None = None) -> bool:
    build_probe = _as_mapping(_as_mapping(environment_summary.get("tools")).get("qe_gpu_build_probe"))
    if build_probe.get("status") != "gpu_qe_build_failed":
        return False
    if program and _qe_is_gpu_capable(environment_summary, program):
        return False
    return True


def _case_declares_missing_pseudo(case: Mapping[str, Any]) -> bool:
    return case.get("pseudo_status") == "pseudo_missing" or (
        case.get("case_origin") == "generated_benchmark" and case.get("pseudo_file_path") in (None, "")
    )


def _output_reports_missing_pseudo(text: str) -> bool:
    lowered = text.lower()
    return "readpp" in lowered and "not found" in lowered and "pseudo" in lowered


def _gpu_preflight_blocker(blockers: list[str]) -> dict[str, Any]:
    return {
        "evidence_status": "evidence_missing",
        "measurements_are_real": False,
        "artifact": None,
        "validation": {
            "status": "failed",
            "errors": [{"field": "gpu_baseline_preflight", "message": ", ".join(blockers)}],
        },
        "blocker_reasons": blockers,
        "run_records": [],
    }


def _run_ready_cases(
    *,
    cases: Sequence[Mapping[str, Any]],
    environment_summary: Mapping[str, Any],
    repeat_count: int,
    timeout_seconds: int,
    run_root: Path | None,
    target_type: str,
) -> dict[str, Any]:
    ready_cases = [
        case
        for case in cases
        if isinstance(case, Mapping)
        and case.get("case_status") == "ready"
        and isinstance(case.get("run_command"), str)
        and case.get("run_command")
    ]
    if not ready_cases:
        return {
            "evidence_status": "evidence_missing",
            "measurements_are_real": False,
            "artifact": None,
            "validation": {
                "status": "not_applicable",
                "errors": [],
                "warnings": [{"field": "run_records", "message": f"no {target_type} baseline-ready cases supplied"}],
            },
            "blocker_reasons": [
                "blocked_by_missing_input_deck"
                if any(isinstance(case, Mapping) and case.get("case_status") == "input_deck_missing" for case in cases)
                else f"{target_type}_baseline_runs_missing"
            ],
            "run_records": [],
        }
    tools = _as_mapping(environment_summary.get("tools"))
    qe_tools = _as_mapping(tools.get("qe"))
    gpu = _as_mapping(environment_summary.get("gpu"))
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
                "run_records": execution_records,
            }
        if target_type == "gpu_only":
            preflight_blockers: list[str] = []
            if _qe_gpu_build_failed(environment_summary, program):
                preflight_blockers.append("gpu_qe_build_failed")
            elif not _qe_is_gpu_capable(environment_summary, program):
                preflight_blockers.append("gpu_qe_binary_cpu_only")
            if _case_declares_missing_pseudo(case):
                preflight_blockers.append("gpu_qe_execution_unavailable_due_to_pseudopotential")
            if preflight_blockers:
                return _gpu_preflight_blocker(preflight_blockers)
        command = str(case["run_command"])
        if target_type == "cpu_only":
            command = f"QE_ENABLE_GPU=0 CUDA_VISIBLE_DEVICES= {command}"
        for run_index in range(repeat_count):
            run_dir = (run_root or Path("runs/qe_ic_real_opportunity_campaign")) / str(case["case_id"]) / f"{target_type}_baseline"
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
                env={**os.environ, "CUDA_VISIBLE_DEVICES": ""} if target_type == "cpu_only" else None,
            )
            elapsed = time.perf_counter() - start
            end_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            stdout_path.write_text(result.stdout or "", encoding="utf-8")
            stderr_path.write_text(result.stderr or "", encoding="utf-8")
            output = (result.stdout or "") + (result.stderr or "")
            output_hash = _sha256_text(output)
            if result.returncode != 0:
                blocker = (
                    "gpu_qe_execution_unavailable_due_to_pseudopotential"
                    if target_type == "gpu_only" and _output_reports_missing_pseudo(output)
                    else f"{target_type}_baseline_command_failed"
                )
                return {
                    "evidence_status": "evidence_missing",
                    "measurements_are_real": False,
                    "artifact": None,
                    "validation": {
                        "status": "failed",
                        "errors": [{"field": "run_command", "message": f"command failed on run {run_index + 1}"}],
                    },
                    "blocker_reasons": [blocker],
                    "run_records": execution_records,
                }
            profile_hash = output_hash
            execution_record = {
                "workload_family_id": case["workload_family_id"],
                "case_id": case["case_id"],
                "program": program,
                "input_deck_hash": case["input_deck_hash"],
                "precision": case["precision"],
                "target_type": target_type,
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
            "gpu_name": str(gpu.get("gpu_model") or ("cpu_only_disabled" if target_type == "cpu_only" else "unknown_gpu")),
            "cpu_name": "local_host",
            "memory": str(gpu.get("gpu_memory_total_mib") or "unknown_memory"),
            "qe_version": str(_qe_program_record(environment_summary, str(ready_cases[0].get("program"))).get("version") or "unknown_qe"),
            "cuda_version": str(gpu.get("cuda_version") or "unknown_cuda"),
            "driver_version": str(gpu.get("driver_version") or "unknown_driver"),
            "precision": str(ready_cases[0].get("precision") or "unknown_precision"),
        },
    )
    baseline["run_records"] = execution_records
    if target_type == "cpu_only":
        artifact = _as_mapping(baseline.get("artifact"))
        if artifact:
            baseline_records = []
            for record in _as_list(artifact.get("baseline_records")):
                if isinstance(record, Mapping):
                    baseline_records.append({**dict(record), "target_type": "cpu_only"})
            baseline["artifact"] = {
                **dict(artifact),
                "measurement_role": "cpu_only_baseline",
                "target_type": "cpu_only",
                "baseline_records": baseline_records,
                "claim_boundary": "CPU-only baseline timing context; not GPU-only baseline evidence.",
            }
    return baseline


def run_cpu_baseline_commands_if_available(
    *,
    cases: Sequence[Mapping[str, Any]],
    environment_summary: Mapping[str, Any],
    repeat_count: int = 3,
    timeout_seconds: int = 3600,
    run_root: Path | None = None,
) -> dict[str, Any]:
    """Run ready CPU-only QE baseline commands when possible."""

    return _run_ready_cases(
        cases=cases,
        environment_summary=environment_summary,
        repeat_count=repeat_count,
        timeout_seconds=timeout_seconds,
        run_root=run_root,
        target_type="cpu_only",
    )


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
    return _run_ready_cases(
        cases=cases,
        environment_summary=environment_summary,
        repeat_count=repeat_count,
        timeout_seconds=timeout_seconds,
        run_root=run_root,
        target_type="gpu_only",
    )
