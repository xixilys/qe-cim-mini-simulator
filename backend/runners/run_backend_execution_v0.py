#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
REPORT_WRITERS = ROOT / "backend" / "report_writers"
if str(REPORT_WRITERS) not in sys.path:
    sys.path.insert(0, str(REPORT_WRITERS))

from gem5_smoke_report import convert_legacy_b3_smoke_report  # type: ignore  # noqa: E402
from systemc_report import (  # type: ignore  # noqa: E402
    MODE_TO_CLAIM_CEILING,
    convert_systemc_candidate_result,
    make_report,
    refusal_report,
    request_validity_class,
    validate_request,
    validate_request_for_execution,
    validate_report,
)

DEFAULT_LEGACY_B3_REPORT = ROOT / "docs/benchmarks/results/qe_dse_gem5_systemc_smoke_report_v0.json"
DEFAULT_SYSTEMC_EXECUTABLE = ROOT / "model/qe_band_solver_model/build/qe_band_solver_model"
DEFAULT_GEM5_EXECUTABLE = ROOT / "gem5_integration/gem5/build/X86/gem5.opt"
DEFAULT_QE_GEM5_CONFIG = ROOT / "gem5_integration/configs/fpga/qe_fpga_system.py"
REAL_QE_GEM5_SE_ARTIFACT_SUBTYPE = "real_qe_gem5_se_scf_smoke_v0"
REAL_QE_GEM5_SE_DEFAULT_CPU_TYPE = "atomic"
REAL_QE_NON_CLAIMS = [
    "no_qe_equivalent_scf_claim",
    "no_cycle_accuracy_claim",
    "no_rtl_hls_board_or_asic_implementation_claim",
    "no_final_architecture_recommendation",
    "no_fpga_systemc_offload_claim",
    "no_performance_acceleration_claim",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or refuse backend execution request v0")
    parser.add_argument("--request", required=True, help="BackendExecutionRequest JSON path")
    parser.add_argument("--output", required=True, help="BackendExecutionReport JSON output path")
    parser.add_argument("--mode", required=True, choices=sorted(MODE_TO_CLAIM_CEILING))
    parser.add_argument("--dry-run", action="store_true", help="Do not execute; emit a refused report")
    parser.add_argument("--allow-execute", action="store_true", help="Allow local backend executable invocation")
    parser.add_argument(
        "--allow-non-executable-debug",
        action="store_true",
        help=(
            "Accept invalid/debug/projection candidates only as a debug refusal path; "
            "never emits an executed report"
        ),
    )
    parser.add_argument(
        "--strict-report-validation",
        action="store_true",
        help="Return nonzero when a direct BackendExecutionReport fails validation",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=300.0,
        help="Maximum seconds for a local backend process before writing a failed report",
    )
    parser.add_argument(
        "--legacy-b3-report",
        nargs="?",
        const=str(DEFAULT_LEGACY_B3_REPORT),
        help="Convert a legacy qe_dse_gem5_systemc_smoke_report_v0 JSON instead of running gem5",
    )
    return parser.parse_args(argv)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(path: Path, payload: Mapping[str, Any]) -> None:
    report = dict(payload)
    try:
        validate_report(report)
    except Exception as exc:
        mode = report.get("fidelity")
        if not isinstance(mode, str) or mode not in MODE_TO_CLAIM_CEILING:
            mode = "systemc_standalone"
        fallback_request = {"candidate_id": str(report.get("candidate_id") or "unknown_candidate")}
        report = refusal_report(
            fallback_request,
            mode=mode,
            reason=f"backend runner refused to write invalid report: {exc}",
            artifact_refs={"invalid_report_candidate": "not_written"},
        )
        validate_report(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _invalid_direct_report_path(output_path: Path) -> Path:
    suffix = output_path.suffix or ".json"
    return output_path.with_name(f"{output_path.stem}.invalid_backend_execution_report{suffix}")


def _preserve_invalid_direct_report(output_path: Path) -> Path:
    preserved = _invalid_direct_report_path(output_path)
    if output_path.exists():
        preserved.write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")
    return preserved


def _request_input_refs(request: Mapping[str, Any]) -> Mapping[str, Any]:
    value = request.get("input_refs")
    return value if isinstance(value, Mapping) else {}


def _path_from_ref(value: Any, request_root: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = request_root / path
    return path


def _input_ref_value(request: Mapping[str, Any], *keys: str) -> Any:
    refs = _request_input_refs(request)
    for key in keys:
        value = refs.get(key)
        if value not in (None, ""):
            return value
    return None


def _real_qe_smoke_requested(request: Mapping[str, Any]) -> bool:
    refs = _request_input_refs(request)
    return any(
        key in refs
        for key in (
            "qe_binary",
            "qe_pw_binary",
            "pw_binary",
            "qe_input",
            "qe_input_template",
            "qe_pseudo_dir",
            "qe_run_dir",
            "gem5_max_ticks",
        )
    )


def _real_qe_input_path(request: Mapping[str, Any], request_root: Path) -> Path | None:
    return _resolved_input_ref(
        request,
        request_root,
        "qe_input_template",
        "qe_input",
        "qe_scf_input",
    )


def _real_qe_binary_path(request: Mapping[str, Any], request_root: Path) -> Path | None:
    return _resolved_input_ref(
        request,
        request_root,
        "qe_binary",
        "qe_pw_binary",
        "pw_binary",
    )


def _real_qe_pseudo_dir(request: Mapping[str, Any], request_root: Path) -> Path | None:
    return _resolved_input_ref(request, request_root, "qe_pseudo_dir", "pseudo_dir")


def _real_qe_run_dir(request: Mapping[str, Any], request_root: Path, output_path: Path) -> Path:
    value = _input_ref_value(request, "qe_run_dir", "run_dir")
    path = _path_from_ref(value, request_root)
    if path is not None:
        return path
    return output_path.with_name(f"{output_path.stem}.real_qe_gem5_se_scf")


def _real_qe_max_ticks(request: Mapping[str, Any]) -> int:
    value = _input_ref_value(request, "gem5_max_ticks", "qe_gem5_max_ticks")
    if value is None:
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError("gem5_max_ticks must be an integer")
    if parsed < 0:
        raise ValueError("gem5_max_ticks must be non-negative")
    return parsed


def _real_qe_cpu_type(request: Mapping[str, Any]) -> str:
    value = _input_ref_value(request, "gem5_cpu_type", "qe_gem5_cpu_type")
    if value is None:
        return REAL_QE_GEM5_SE_DEFAULT_CPU_TYPE
    if not isinstance(value, str):
        raise ValueError("gem5_cpu_type must be a string")
    normalized = value.strip().lower()
    if normalized not in {"atomic", "timing"}:
        raise ValueError("gem5_cpu_type must be one of: atomic, timing")
    return normalized


def _ensure_writable_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError(f"not a directory: {path}")
    probe = path / ".qebs_write_probe"
    probe.write_text("ok\n", encoding="utf-8")
    probe.unlink()


def _reset_generated_dir(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"not a directory: {path}")
        shutil.rmtree(path)
    _ensure_writable_dir(path)


def _replace_qe_control_path(input_text: str, key: str, value: Path) -> str:
    pattern = re.compile(
        rf"(?m)^(\s*{re.escape(key)}\s*=\s*)['\"][^'\"]*['\"](\s*,?\s*)$",
        re.IGNORECASE,
    )
    replacement = rf"\1'{str(value)}'\2"
    updated, count = pattern.subn(replacement, input_text, count=1)
    if count == 0:
        raise ValueError(f"QE input template is missing {key}")
    return updated


def _prepare_real_qe_input(
    template: Path,
    pseudo_dir: Path,
    outdir: Path,
    run_dir: Path,
    label: str,
) -> Path:
    text = template.read_text(encoding="utf-8")
    text = _replace_qe_control_path(text, "pseudo_dir", pseudo_dir)
    text = _replace_qe_control_path(text, "outdir", outdir)
    output = run_dir / f"{template.stem}.{label}.abs{template.suffix or '.in'}"
    output.write_text(text, encoding="utf-8")
    return output


def _pseudo_filenames_from_qe_input(template: Path) -> list[str]:
    filenames: list[str] = []
    in_species = False
    for raw_line in template.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        upper = line.upper()
        if not line or line.startswith("!") or line.startswith("#"):
            continue
        if upper.startswith("ATOMIC_SPECIES"):
            in_species = True
            continue
        if in_species and (
            upper.startswith("ATOMIC_POSITIONS")
            or upper.startswith("K_POINTS")
            or upper.startswith("CELL_PARAMETERS")
            or upper.startswith("&")
        ):
            break
        if in_species:
            parts = line.split()
            if len(parts) >= 3:
                filenames.append(parts[2])
    return filenames


def _run_ldd(binary: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["ldd", str(binary)],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return {
            "status": "ldd_unavailable",
            "returncode": None,
            "stdout": "",
            "stderr": "ldd command not found",
        }
    output = (completed.stdout or "") + (completed.stderr or "")
    lowered = output.lower()
    if "not found" in lowered:
        status = "missing_dependency"
    elif completed.returncode == 0:
        status = "ok"
    elif "not a dynamic executable" in lowered or "statically linked" in lowered:
        status = "not_dynamic_or_static"
    else:
        status = "failed"
    return {
        "status": status,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _parse_float_token(value: str) -> float | None:
    try:
        return float(value.replace("D", "E").replace("d", "e"))
    except ValueError:
        return None


def _parse_qe_stdout(stdout: str) -> dict[str, Any]:
    convergence = re.search(
        r"convergence\s+has\s+been\s+achieved(?:\s+in\s+(\d+)\s+iterations)?",
        stdout,
        re.IGNORECASE,
    )
    total_energy = re.search(
        r"!\s+total\s+energy\s+=\s*([-+0-9.EeDd]+)\s+Ry",
        stdout,
        re.IGNORECASE,
    )
    estimated_accuracy = re.findall(
        r"estimated\s+scf\s+accuracy\s+<\s*([-+0-9.EeDd]+)\s+Ry",
        stdout,
        re.IGNORECASE,
    )
    exit_match = re.search(r"Exiting\s+@\s+tick\s+(\d+)\s+because\s+(.+)", stdout)
    exit_cause = exit_match.group(2).strip() if exit_match else None
    return {
        "scf_converged": convergence is not None,
        "scf_iterations": int(convergence.group(1)) if convergence and convergence.group(1) else None,
        "job_done": "JOB DONE" in stdout,
        "final_total_energy_ry": _parse_float_token(total_energy.group(1)) if total_energy else None,
        "estimated_scf_accuracy_ry": (
            _parse_float_token(estimated_accuracy[-1]) if estimated_accuracy else None
        ),
        "gem5_exit_tick": int(exit_match.group(1)) if exit_match else None,
        "gem5_exit_cause": exit_cause,
        "gem5_hit_tick_limit": (
            isinstance(exit_cause, str)
            and any(token in exit_cause.lower() for token in ("simulate() limit", "tick limit", "max tick"))
        ),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _real_qe_failure_report(
    request: Mapping[str, Any],
    output_path: Path,
    mode: str,
    reason: str,
    *,
    artifact_refs: Mapping[str, Any],
    environment: Mapping[str, Any] | None = None,
    control_path: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    notes: list[str] | None = None,
) -> None:
    report = make_report(
        request,
        mode=mode,
        execution_status="failed",
        reason=reason,
        environment=environment,
        control_path=control_path,
        metrics=metrics,
        artifact_refs=artifact_refs,
        non_claims=REAL_QE_NON_CLAIMS,
        notes=notes,
    )
    write_report(output_path, report)


def _systemc_executable(request: Mapping[str, Any], request_root: Path) -> Path:
    refs = _request_input_refs(request)
    return _path_from_ref(refs.get("systemc_executable"), request_root) or DEFAULT_SYSTEMC_EXECUTABLE


def _gem5_executable(request: Mapping[str, Any], request_root: Path) -> Path:
    refs = _request_input_refs(request)
    return _path_from_ref(refs.get("gem5_executable"), request_root) or DEFAULT_GEM5_EXECUTABLE


def _gem5_config(request: Mapping[str, Any], request_root: Path) -> Path | None:
    refs = _request_input_refs(request)
    for key in ("gem5_config", "gem5_config_py", "gem5_system_config"):
        path = _path_from_ref(refs.get(key), request_root)
        if path is not None:
            return path
    return None


def _systemc_candidate_result_path(request: Mapping[str, Any], request_root: Path) -> Path | None:
    refs = _request_input_refs(request)
    for key in ("systemc_candidate_result", "systemc_result_json", "systemc_report"):
        path = _path_from_ref(refs.get(key), request_root)
        if path is not None:
            return path
    return None


def _systemc_candidate_output_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.systemc_candidate_result.json")


def _subprocess_log_paths(output_path: Path, stem: str) -> dict[str, Path]:
    return {
        "stdout": output_path.with_name(f"{output_path.stem}.{stem}.stdout.log"),
        "stderr": output_path.with_name(f"{output_path.stem}.{stem}.stderr.log"),
    }


def _run_logged_subprocess(
    command: list[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    logs: Mapping[str, Path],
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    logs["stdout"].parent.mkdir(parents=True, exist_ok=True)
    logs["stderr"].parent.mkdir(parents=True, exist_ok=True)
    with logs["stdout"].open("w", encoding="utf-8") as stdout_file, logs["stderr"].open(
        "w",
        encoding="utf-8",
    ) as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=dict(env),
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )
        try:
            returncode = process.wait(timeout=max(0.1, timeout_s))
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            stdout_file.flush()
            stderr_file.flush()
            exc.output = logs["stdout"].read_text(encoding="utf-8")
            exc.stderr = logs["stderr"].read_text(encoding="utf-8")
            raise
    stdout = logs["stdout"].read_text(encoding="utf-8")
    stderr = logs["stderr"].read_text(encoding="utf-8")
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def _set_env(env: dict[str, str], key: str, value: Any) -> None:
    if value is None or isinstance(value, (Mapping, list, tuple)):
        return
    env[key] = str(value)


def _set_mapping_env(env: dict[str, str], prefix: str, value: Any) -> None:
    if not isinstance(value, Mapping):
        return
    for key, item in value.items():
        env_key = f"{prefix}_{str(key).upper()}"
        _set_env(env, env_key, item)


def _resolved_input_ref_env(request: Mapping[str, Any], request_root: Path) -> dict[str, str]:
    refs = _request_input_refs(request)
    env: dict[str, str] = {}
    for key, value in refs.items():
        path = _path_from_ref(value, request_root)
        if path is not None:
            env[f"QEBS_INPUT_REF_{str(key).upper()}"] = str(path)
    return env


def _resolved_input_ref(request: Mapping[str, Any], request_root: Path, *keys: str) -> Path | None:
    refs = _request_input_refs(request)
    for key in keys:
        path = _path_from_ref(refs.get(key), request_root)
        if path is not None:
            return path
    return None


def _request_env(
    request: Mapping[str, Any],
    request_root: Path,
    result_path: Path,
    backend_report_path: Path,
) -> dict[str, str]:
    env: dict[str, str] = {}
    workload_identity = request.get("workload_identity")
    workload_identity = workload_identity if isinstance(workload_identity, Mapping) else {}
    candidate_identity = request.get("candidate_identity")
    candidate_identity = candidate_identity if isinstance(candidate_identity, Mapping) else {}
    design_axes = candidate_identity.get("design_axes")
    design_axes = design_axes if isinstance(design_axes, Mapping) else {}
    software_runtime = request.get("software_runtime")
    software_runtime = software_runtime if isinstance(software_runtime, Mapping) else {}
    domain_extension = request.get("domain_extension")
    domain_extension = domain_extension if isinstance(domain_extension, Mapping) else {}
    qe_extension = domain_extension.get("qe")
    qe_extension = qe_extension if isinstance(qe_extension, Mapping) else {}
    systemc_config = request.get("systemc_config")
    systemc_config = systemc_config if isinstance(systemc_config, Mapping) else {}

    _set_env(env, "QEBS_RESULT_JSON", result_path)
    _set_env(env, "QEBS_BACKEND_EXECUTION_REPORT_JSON", backend_report_path)
    _set_env(env, "QEBS_BACKEND_REPORT_JSON", backend_report_path)
    _set_env(env, "QEBS_CANDIDATE_ID", request.get("candidate_id"))
    _set_env(env, "QEBS_REQUESTED_FIDELITY", request.get("requested_fidelity"))
    _set_env(env, "QEBS_EXECUTION_MODE", request.get("execution_mode"))
    _set_env(env, "QEBS_WORKLOAD_ID", workload_identity.get("workload_id"))
    _set_env(env, "QEBS_WORKLOAD_DOMAIN", workload_identity.get("domain"))
    _set_env(env, "QEBS_WORKLOAD_ADAPTER", workload_identity.get("adapter"))
    _set_env(env, "QEBS_ARCHITECTURE_TEMPLATE_ID", candidate_identity.get("architecture_template_id"))
    _set_env(env, "QEBS_TARGET_CLASS", candidate_identity.get("target_class"))
    _set_env(env, "QEBS_CANDIDATE_FAMILY", candidate_identity.get("candidate_family"))
    _set_env(env, "QEBS_BACKEND_PROFILE_ID", candidate_identity.get("backend_profile_id"))
    _set_env(env, "QEBS_SOFTWARE_RUNTIME_MODE", software_runtime.get("mode"))
    _set_env(env, "QEBS_CONTROL_POLICY", software_runtime.get("control_policy"))
    _set_env(env, "QEBS_QE_CASE_ID", qe_extension.get("case_id"))
    _set_env(env, "QEBS_QE_PSEUDOPOTENTIAL_FAMILY", qe_extension.get("pseudopotential_family"))
    _set_env(env, "QEBS_QE_SOLVER_PATH_CLASS", qe_extension.get("solver_path_class"))
    _set_env(env, "QEBS_QE_TOLERANCE_SCHEMA_ID", qe_extension.get("qe_tolerance_schema_id"))
    _set_mapping_env(env, "QEBS_DESIGN_AXIS", design_axes)
    _set_mapping_env(env, "QEBS_SYSTEMC_CONFIG", systemc_config)
    env.update(_resolved_input_ref_env(request, request_root))

    systemc_config_ref = _resolved_input_ref(request, request_root, "systemc_config")
    architecture_config_ref = _resolved_input_ref(request, request_root, "architecture_config", "arch_config")

    # Compatibility aliases consumed by the current qe_band_solver_model/sc_main.cpp.
    # Prefer the separated architecture_config sidecar when present; fall back to
    # systemc_config only for older descriptor bundles that predate the split.
    arch_config = architecture_config_ref or systemc_config_ref
    _set_env(env, "QEBS_CASE_ID", qe_extension.get("case_id") or workload_identity.get("workload_id"))
    _set_env(
        env,
        "QEBS_ARCH_FAMILY",
        design_axes.get("family")
        or candidate_identity.get("candidate_family")
        or candidate_identity.get("architecture_template_id"),
    )
    _set_env(env, "QEBS_ASSUMPTION_SET_ID", candidate_identity.get("backend_profile_id"))
    _set_env(env, "QEBS_SIGNATURE_ID", workload_identity.get("signature_id"))
    _set_env(env, "QEBS_PSEUDOPOTENTIAL_FAMILY", qe_extension.get("pseudopotential_family"))
    _set_env(env, "QEBS_SOLVER_PATH_CLASS", qe_extension.get("solver_path_class"))
    _set_env(env, "QEBS_OFFLOAD_SCOPE", design_axes.get("offload_scope"))
    _set_env(env, "QEBS_RESIDENT_POLICY", design_axes.get("resident_policy"))
    _set_env(env, "QEBS_ARCH_CONFIG", arch_config)
    _set_env(env, "QEBS_ARCHITECTURE_CONFIG", architecture_config_ref)
    _set_env(env, "QEBS_SYSTEMC_CONFIG_REF", systemc_config_ref)
    return env


def _gem5_env(
    request: Mapping[str, Any],
    request_root: Path,
    output_path: Path,
    mode: str,
    gem5_config: Path,
    systemc_bridge: Path | None = None,
) -> dict[str, str]:
    env = _request_env(
        request,
        request_root,
        output_path.with_name(f"{output_path.stem}.gem5_proxy_metrics.json"),
        output_path,
    )
    env["QEBS_GEM5_CONFIG"] = str(gem5_config)
    env["QEBS_GEM5_MODE"] = "SE"
    env["QEBS_FPGA_EXECUTION_MODE"] = (
        "smoke" if mode == "gem5_systemc_smoke" else "real_bridge"
    )
    env["QEBS_REAL_SYSTEMC_TARGET"] = "1" if systemc_bridge is not None else "0"
    if systemc_bridge is not None:
        env["QEBS_SYSTEMC_BRIDGE"] = str(systemc_bridge)
    env["QEBS_GEM5_OUTPUT_DIR"] = str(output_path.parent)
    return env


def _b4_systemc_bridge_ref(request: Mapping[str, Any], request_root: Path) -> Path | None:
    return _resolved_input_ref(
        request,
        request_root,
        "systemc_bridge",
        "systemc_bridge_library",
        "systemc_target",
        "real_systemc_target",
    )


def _validate_b4_timed_proxy_report_shape(
    payload: Mapping[str, Any],
    *,
    expected_systemc_bridge: Path | None = None,
) -> None:
    control_path = payload.get("control_path")
    metrics = payload.get("metrics")
    environment = payload.get("environment")
    artifact_refs = payload.get("artifact_refs")
    if not isinstance(control_path, Mapping) or not isinstance(metrics, Mapping):
        raise ValueError("B4 timed proxy report requires control_path and metrics objects")
    if not isinstance(environment, Mapping):
        raise ValueError("B4 timed proxy report requires environment provenance")
    if environment.get("fpga_execution_mode") != "real_bridge":
        raise ValueError("B4 timed proxy report requires environment.fpga_execution_mode=real_bridge")
    if str(environment.get("real_systemc_target")) != "1":
        raise ValueError("B4 timed proxy report requires environment.real_systemc_target=1")
    bridge_value = environment.get("systemc_bridge")
    if not bridge_value:
        raise ValueError("B4 timed proxy report requires environment.systemc_bridge provenance")
    if expected_systemc_bridge is not None and str(bridge_value) != str(expected_systemc_bridge):
        raise ValueError("B4 timed proxy report systemc_bridge does not match requested bridge artifact")
    if isinstance(artifact_refs, Mapping) and artifact_refs.get("systemc_bridge") not in (None, bridge_value):
        raise ValueError("B4 timed proxy report artifact_refs.systemc_bridge conflicts with environment")
    required_control = (
        "mmio_read_count",
        "mmio_write_count",
        "polling_read_count",
        "interrupt_count",
        "command_issue_tick",
        "device_accept_tick",
        "systemc_start_tick",
        "systemc_end_tick",
        "completion_tick",
        "dma_start_tick",
        "dma_end_tick",
    )
    required_metrics = (
        "host_control_mmio_read_count",
        "host_control_mmio_write_count",
        "host_control_polling_read_count",
        "host_control_interrupt_count",
        "host_control_queue_wait_ns",
        "systemc_datapath_device_busy_ns",
        "systemc_datapath_compute_ns",
        "systemc_datapath_dma_read_ns",
        "systemc_datapath_dma_write_ns",
        "systemc_datapath_queue_depth",
        "systemc_datapath_backpressure_count",
        "logical_dma_payload_bytes",
        "observed_gem5_dma_stat_bytes",
        "successful_dma_transfer_bytes",
        "dma_warning_count",
    )
    for key in required_control:
        if key not in control_path:
            raise ValueError(f"B4 timed proxy report missing control_path.{key}")
    for key in required_metrics:
        if key not in metrics:
            raise ValueError(f"B4 timed proxy report missing metrics.{key}")


def _accept_direct_backend_report(
    request: Mapping[str, Any],
    output_path: Path,
    mode: str,
    *,
    expected_systemc_bridge: Path | None = None,
) -> bool:
    if not output_path.exists():
        return False
    try:
        payload = load_json(output_path)
        if not isinstance(payload, Mapping):
            raise ValueError("direct BackendExecutionReport root must be an object")
        validate_report(payload)
        if payload.get("candidate_id") != request.get("candidate_id"):
            raise ValueError("direct BackendExecutionReport candidate_id does not match request")
        if payload.get("fidelity") != mode:
            raise ValueError("direct BackendExecutionReport fidelity does not match CLI mode")
        if mode == "gem5_systemc_timed_proxy":
            _validate_b4_timed_proxy_report_shape(
                payload, expected_systemc_bridge=expected_systemc_bridge
            )
    except Exception as exc:
        preserved_report = _preserve_invalid_direct_report(output_path)
        report = refusal_report(
            request,
            mode=mode,
            reason=f"direct BackendExecutionReport validation failed: {exc}",
            artifact_refs={
                "direct_backend_execution_report": str(preserved_report),
                "direct_backend_execution_report_status": "invalid",
            },
        )
        write_report(output_path, report)
        return False
    return True


def _load_request_or_refuse(request_path: Path, output_path: Path, mode: str) -> tuple[dict[str, Any] | None, int | None]:
    try:
        request = load_json(request_path)
        if not isinstance(request, dict):
            raise ValueError("request JSON root must be an object")
        validate_request(request, mode=mode)
        return request, None
    except Exception as exc:
        report = refusal_report(
            None,
            mode=mode,
            reason=f"invalid backend execution request: {exc}",
            artifact_refs={"request": str(request_path)},
        )
        write_report(output_path, report)
        return None, 2


def _refuse_non_executable_candidate(
    request: Mapping[str, Any],
    output_path: Path,
    mode: str,
    reason: str,
) -> None:
    validity = request_validity_class(request) or "missing"
    report = refusal_report(
        request,
        mode=mode,
        reason=reason,
        artifact_refs={
            "candidate_validity_class": validity,
            "candidate_execution_status": "not_attempted",
        },
    )
    write_report(output_path, report)


def _candidate_execution_gate(
    request: Mapping[str, Any],
    output_path: Path,
    mode: str,
    *,
    allow_non_executable_debug: bool,
) -> tuple[bool, int]:
    try:
        validate_request_for_execution(request)
        return True, 0
    except Exception as exc:
        _refuse_non_executable_candidate(request, output_path, mode, str(exc))
    return False, 0 if allow_non_executable_debug else 2


def _convert_legacy_b3(request: Mapping[str, Any], output_path: Path, legacy_path: Path) -> int:
    if not legacy_path.exists():
        report = refusal_report(
            request,
            mode="gem5_systemc_smoke",
            reason=f"legacy B3 smoke report is missing: {legacy_path}",
            artifact_refs={"legacy_b3_smoke_report": str(legacy_path)},
        )
        write_report(output_path, report)
        return 0
    try:
        legacy = load_json(legacy_path)
        report = convert_legacy_b3_smoke_report(legacy, request, source_path=legacy_path)
    except Exception as exc:
        report = refusal_report(
            request,
            mode="gem5_systemc_smoke",
            reason=f"legacy B3 smoke report conversion failed: {exc}",
            artifact_refs={"legacy_b3_smoke_report": str(legacy_path)},
        )
    write_report(output_path, report)
    return 0


def _convert_existing_systemc_result(request: Mapping[str, Any], output_path: Path, mode: str, result_path: Path) -> int:
    if not result_path.exists():
        report = refusal_report(
            request,
            mode=mode,
            reason=f"SystemC candidate result artifact is missing: {result_path}",
            artifact_refs={
                "systemc_candidate_result": str(result_path),
                "systemc_candidate_result_status": "missing",
            },
        )
        write_report(output_path, report)
        return 0
    try:
        candidate = load_json(result_path)
        report = convert_systemc_candidate_result(candidate, request, source_path=result_path, mode=mode)
    except Exception as exc:
        report = refusal_report(
            request,
            mode=mode,
            reason=f"SystemC candidate result conversion failed: {exc}",
            artifact_refs={"systemc_candidate_result": str(result_path)},
        )
    write_report(output_path, report)
    return 0


def _run_systemc(
    request: Mapping[str, Any],
    output_path: Path,
    mode: str,
    request_root: Path,
    strict_report_validation: bool,
) -> int:
    executable = _systemc_executable(request, request_root)
    if not executable.exists():
        report = refusal_report(
            request,
            mode=mode,
            reason=f"SystemC executable is missing: {executable}",
            artifact_refs={"systemc_executable": str(executable)},
        )
        write_report(output_path, report)
        return 0

    result_path = _systemc_candidate_output_path(output_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    if result_path.exists():
        result_path.unlink()
    if output_path.exists():
        output_path.unlink()
    env = os.environ.copy()
    env.update(_request_env(request, request_root, result_path, output_path))
    logs = _subprocess_log_paths(output_path, "systemc")
    try:
        completed = subprocess.run(
            [str(executable)],
            cwd=str(executable.parent),
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        logs["stdout"].write_text(completed.stdout, encoding="utf-8")
        logs["stderr"].write_text(completed.stderr, encoding="utf-8")
    except OSError as exc:
        report = refusal_report(
            request,
            mode=mode,
            reason=f"SystemC executable could not be launched: {exc}",
            artifact_refs={
                "systemc_executable": str(executable),
                "systemc_stdout_log": str(logs["stdout"]),
                "systemc_stderr_log": str(logs["stderr"]),
            },
        )
        write_report(output_path, report)
        return 0
    if completed.returncode != 0:
        result_status = "present" if result_path.exists() else "missing"
        report = refusal_report(
            request,
            mode=mode,
            reason=f"SystemC executable returned nonzero status {completed.returncode}",
            artifact_refs={
                "systemc_executable": str(executable),
                "systemc_candidate_result": str(result_path),
                "systemc_candidate_result_status": result_status,
                "systemc_stdout_log": str(logs["stdout"]),
                "systemc_stderr_log": str(logs["stderr"]),
            },
        )
        report["execution_status"] = "failed"
        report["status_reason"] = report.pop("refusal_reason")
        write_report(output_path, report)
        return 1
    if output_path.exists():
        if not _accept_direct_backend_report(request, output_path, mode):
            return 1 if strict_report_validation else 0
        return 0
    return _convert_existing_systemc_result(request, output_path, mode, result_path)


def _run_gem5(
    request: Mapping[str, Any],
    output_path: Path,
    mode: str,
    request_root: Path,
    timeout_s: float,
    strict_report_validation: bool,
) -> int:
    executable = _gem5_executable(request, request_root)
    if not executable.exists():
        report = refusal_report(
            request,
            mode=mode,
            reason=f"gem5 executable is missing: {executable}",
            artifact_refs={"gem5_executable": str(executable)},
        )
        write_report(output_path, report)
        return 0

    real_qe_smoke = mode == "gem5_systemc_smoke" and _real_qe_smoke_requested(request)
    gem5_config = _gem5_config(request, request_root)
    if gem5_config is None and real_qe_smoke:
        gem5_config = DEFAULT_QE_GEM5_CONFIG
    if gem5_config is None or not gem5_config.exists():
        refs: dict[str, Any] = {"gem5_executable": str(executable)}
        if gem5_config is not None:
            refs["gem5_config"] = str(gem5_config)
            refs["gem5_config_status"] = "missing"
        report = refusal_report(
            request,
            mode=mode,
            reason=(
                "direct gem5 execution is not implemented without an explicit "
                "gem5_config/gem5_config_py artifact; no smoke/timed_proxy fallback "
                "was attempted"
            ),
            artifact_refs=refs,
        )
        write_report(output_path, report)
        return 0

    if mode == "gem5_systemc_timed_proxy":
        # B4 is deliberately guarded: it may execute only through an explicit gem5
        # config and an explicit real SystemC bridge/target artifact. It must never
        # silently reuse the B3 smoke stub or the local timed_proxy fallback path.
        bridge_ref = _b4_systemc_bridge_ref(request, request_root)
        if bridge_ref is None:
            report = refusal_report(
                request,
                mode=mode,
                reason=(
                    "B4 timed proxy requires an explicit systemc_bridge/"
                    "systemc_bridge_library/systemc_target input ref; "
                    "no smoke/timed_proxy fallback was attempted"
                ),
                artifact_refs={
                    "gem5_executable": str(executable),
                    "gem5_config": str(gem5_config),
                    "systemc_bridge_status": "missing_input_ref",
                },
            )
            write_report(output_path, report)
            return 0
        if not bridge_ref.exists():
            report = refusal_report(
                request,
                mode=mode,
                reason=f"B4 timed proxy SystemC bridge artifact is missing: {bridge_ref}",
                artifact_refs={
                    "gem5_executable": str(executable),
                    "gem5_config": str(gem5_config),
                    "systemc_bridge": str(bridge_ref),
                    "systemc_bridge_status": "missing",
                },
            )
            write_report(output_path, report)
            return 0
    else:
        bridge_ref = None

    real_qe_context: dict[str, Any] | None = None
    if real_qe_smoke:
        if output_path.exists():
            output_path.unlink()
        manifest_path = output_path.with_name(f"{output_path.stem}.real_qe_gem5_manifest.json")
        native_logs = _subprocess_log_paths(output_path, "native_qe")
        qe_binary = _real_qe_binary_path(request, request_root)
        qe_input_template = _real_qe_input_path(request, request_root)
        qe_pseudo_dir = _real_qe_pseudo_dir(request, request_root)
        try:
            max_ticks = _real_qe_max_ticks(request)
            cpu_type = _real_qe_cpu_type(request)
        except ValueError as exc:
            report = refusal_report(
                request,
                mode=mode,
                reason=str(exc),
                artifact_refs={"artifact_subtype": REAL_QE_GEM5_SE_ARTIFACT_SUBTYPE},
            )
            write_report(output_path, report)
            return 0

        preflight_refs: dict[str, Any] = {
            "artifact_subtype": REAL_QE_GEM5_SE_ARTIFACT_SUBTYPE,
            "gem5_executable": str(executable),
            "gem5_config": str(gem5_config),
            "run_manifest": str(manifest_path),
        }
        if qe_binary is not None:
            preflight_refs["qe_binary"] = str(qe_binary)
        if qe_input_template is not None:
            preflight_refs["qe_input_template"] = str(qe_input_template)
        if qe_pseudo_dir is not None:
            preflight_refs["qe_pseudo_dir"] = str(qe_pseudo_dir)

        if qe_binary is None:
            report = refusal_report(
                request,
                mode=mode,
                reason="real QE gem5 smoke requires input_refs.qe_binary/qe_pw_binary/pw_binary",
                artifact_refs=preflight_refs,
            )
            write_report(output_path, report)
            return 0
        if not qe_binary.exists() or not qe_binary.is_file():
            report = refusal_report(
                request,
                mode=mode,
                reason=f"QE pw.x executable is missing: {qe_binary}",
                artifact_refs={**preflight_refs, "qe_binary_status": "missing"},
            )
            write_report(output_path, report)
            return 0
        if not os.access(qe_binary, os.X_OK):
            report = refusal_report(
                request,
                mode=mode,
                reason=f"QE pw.x is not executable: {qe_binary}",
                artifact_refs={**preflight_refs, "qe_binary_status": "not_executable"},
            )
            write_report(output_path, report)
            return 0
        if qe_input_template is None or not qe_input_template.exists() or not qe_input_template.is_file():
            report = refusal_report(
                request,
                mode=mode,
                reason=f"QE input template is missing: {qe_input_template}",
                artifact_refs={**preflight_refs, "qe_input_template_status": "missing"},
            )
            write_report(output_path, report)
            return 0
        if qe_pseudo_dir is None or not qe_pseudo_dir.exists() or not qe_pseudo_dir.is_dir():
            report = refusal_report(
                request,
                mode=mode,
                reason=f"QE pseudo_dir is missing: {qe_pseudo_dir}",
                artifact_refs={**preflight_refs, "qe_pseudo_dir_status": "missing"},
            )
            write_report(output_path, report)
            return 0
        pseudo_filenames = _pseudo_filenames_from_qe_input(qe_input_template)
        missing_pseudos = [name for name in pseudo_filenames if not (qe_pseudo_dir / name).exists()]
        if missing_pseudos:
            report = refusal_report(
                request,
                mode=mode,
                reason=f"QE pseudo_dir is missing pseudopotential files: {', '.join(missing_pseudos)}",
                artifact_refs={
                    **preflight_refs,
                    "qe_pseudo_dir_status": "missing_pseudopotential_files",
                    "missing_qe_pseudo_files": missing_pseudos,
                },
            )
            write_report(output_path, report)
            return 0

        run_dir = _real_qe_run_dir(request, request_root, output_path)
        native_qe_outdir = run_dir / "native_qe_outdir"
        gem5_qe_outdir = run_dir / "gem5_qe_outdir"
        m5out_dir = run_dir / "m5out"
        try:
            _ensure_writable_dir(run_dir)
            _reset_generated_dir(native_qe_outdir)
            _reset_generated_dir(gem5_qe_outdir)
            _reset_generated_dir(m5out_dir)
            native_qe_input = _prepare_real_qe_input(
                qe_input_template,
                qe_pseudo_dir,
                native_qe_outdir,
                run_dir,
                "native",
            )
            gem5_qe_input = _prepare_real_qe_input(
                qe_input_template,
                qe_pseudo_dir,
                gem5_qe_outdir,
                run_dir,
                "gem5",
            )
        except OSError as exc:
            report = refusal_report(
                request,
                mode=mode,
                reason=f"real QE run directory is not writable: {exc}",
                artifact_refs=preflight_refs,
            )
            write_report(output_path, report)
            return 0
        except ValueError as exc:
            report = refusal_report(
                request,
                mode=mode,
                reason=f"QE input template could not be made absolute: {exc}",
                artifact_refs=preflight_refs,
            )
            write_report(output_path, report)
            return 0

        ldd_result = _run_ldd(qe_binary)
        manifest: dict[str, Any] = {
            "artifact_subtype": REAL_QE_GEM5_SE_ARTIFACT_SUBTYPE,
            "gem5_executable": str(executable),
            "gem5_config": str(gem5_config),
            "qe_binary": str(qe_binary),
            "qe_input_template": str(qe_input_template),
            "qe_input": str(gem5_qe_input),
            "gem5_qe_input": str(gem5_qe_input),
            "native_qe_input": str(native_qe_input),
            "qe_pseudo_dir": str(qe_pseudo_dir),
            "qe_pseudo_files": pseudo_filenames,
            "qe_outdir": str(gem5_qe_outdir),
            "gem5_qe_outdir": str(gem5_qe_outdir),
            "native_qe_outdir": str(native_qe_outdir),
            "qe_run_dir": str(run_dir),
            "m5out_dir": str(m5out_dir),
            "outdir_isolation": {
                "native_and_gem5_outdirs_shared": False,
                "native_generated_subdir_reset": str(native_qe_outdir),
                "gem5_generated_subdir_reset": str(gem5_qe_outdir),
            },
            "gem5_max_ticks": max_ticks,
            "gem5_cpu_type": cpu_type,
            "ldd": ldd_result,
            "non_claims": REAL_QE_NON_CLAIMS,
        }
        _write_json(manifest_path, manifest)
        if ldd_result.get("status") in {"missing_dependency", "failed"}:
            report = refusal_report(
                request,
                mode=mode,
                reason=f"QE pw.x dependency preflight failed: ldd_status={ldd_result.get('status')}",
                artifact_refs={
                    **preflight_refs,
                    "qe_binary": str(qe_binary),
                    "qe_input": str(gem5_qe_input),
                    "gem5_qe_input": str(gem5_qe_input),
                    "native_qe_input": str(native_qe_input),
                    "qe_run_dir": str(run_dir),
                    "ldd_status": ldd_result.get("status"),
                },
            )
            write_report(output_path, report)
            return 0

        native_command = [str(qe_binary), "-in", str(native_qe_input)]
        try:
            native_completed = subprocess.run(
                native_command,
                cwd=str(run_dir),
                check=False,
                capture_output=True,
                text=True,
                timeout=max(0.1, timeout_s),
            )
            native_logs["stdout"].write_text(native_completed.stdout, encoding="utf-8")
            native_logs["stderr"].write_text(native_completed.stderr, encoding="utf-8")
        except subprocess.TimeoutExpired as exc:
            native_logs["stdout"].write_text(exc.stdout or "", encoding="utf-8")
            native_logs["stderr"].write_text(exc.stderr or "", encoding="utf-8")
            manifest.update(
                {
                    "native_command": native_command,
                    "native_timeout_s": timeout_s,
                    "native_stdout_log": str(native_logs["stdout"]),
                    "native_stderr_log": str(native_logs["stderr"]),
                }
            )
            _write_json(manifest_path, manifest)
            _real_qe_failure_report(
                request,
                output_path,
                mode,
                f"native QE baseline exceeded timeout_s={timeout_s}",
                artifact_refs={
                    **preflight_refs,
                    "qe_binary": str(qe_binary),
                    "qe_input": str(gem5_qe_input),
                    "gem5_qe_input": str(gem5_qe_input),
                    "native_qe_input": str(native_qe_input),
                    "qe_run_dir": str(run_dir),
                    "native_stdout_log": str(native_logs["stdout"]),
                    "native_stderr_log": str(native_logs["stderr"]),
                },
                environment={"source": "native_qe_preflight"},
            )
            return 1
        except OSError as exc:
            report = refusal_report(
                request,
                mode=mode,
                reason=f"native QE baseline could not be launched: {exc}",
                artifact_refs={
                    **preflight_refs,
                    "qe_binary": str(qe_binary),
                    "qe_input": str(gem5_qe_input),
                    "gem5_qe_input": str(gem5_qe_input),
                    "native_qe_input": str(native_qe_input),
                    "qe_run_dir": str(run_dir),
                    "native_stdout_log": str(native_logs["stdout"]),
                    "native_stderr_log": str(native_logs["stderr"]),
                },
            )
            write_report(output_path, report)
            return 0

        native_parse = _parse_qe_stdout(native_completed.stdout)
        manifest.update(
            {
                "native_command": native_command,
                "native_returncode": native_completed.returncode,
                "native_stdout_log": str(native_logs["stdout"]),
                "native_stderr_log": str(native_logs["stderr"]),
                "native_parse": native_parse,
            }
        )
        _write_json(manifest_path, manifest)
        native_artifacts = {
            **preflight_refs,
            "qe_binary": str(qe_binary),
            "qe_input_template": str(qe_input_template),
            "qe_input": str(gem5_qe_input),
            "gem5_qe_input": str(gem5_qe_input),
            "native_qe_input": str(native_qe_input),
            "qe_pseudo_dir": str(qe_pseudo_dir),
            "qe_outdir": str(gem5_qe_outdir),
            "gem5_qe_outdir": str(gem5_qe_outdir),
            "native_qe_outdir": str(native_qe_outdir),
            "qe_run_dir": str(run_dir),
            "native_stdout_log": str(native_logs["stdout"]),
            "native_stderr_log": str(native_logs["stderr"]),
        }
        if native_completed.returncode != 0:
            _real_qe_failure_report(
                request,
                output_path,
                mode,
                f"native QE baseline returned nonzero status {native_completed.returncode}",
                artifact_refs=native_artifacts,
                environment={"source": "native_qe_preflight"},
            )
            return 1
        if not native_parse.get("scf_converged") or not native_parse.get("job_done"):
            _real_qe_failure_report(
                request,
                output_path,
                mode,
                "native QE baseline did not expose both convergence and JOB DONE markers",
                artifact_refs=native_artifacts,
                environment={"source": "native_qe_preflight"},
            )
            return 1
        real_qe_context = {
            "manifest_path": manifest_path,
            "manifest": manifest,
            "native_parse": native_parse,
            "native_logs": native_logs,
            "qe_binary": qe_binary,
            "qe_input_template": qe_input_template,
            "qe_input": gem5_qe_input,
            "gem5_qe_input": gem5_qe_input,
            "native_qe_input": native_qe_input,
            "qe_pseudo_dir": qe_pseudo_dir,
            "qe_outdir": gem5_qe_outdir,
            "gem5_qe_outdir": gem5_qe_outdir,
            "native_qe_outdir": native_qe_outdir,
            "run_dir": run_dir,
            "m5out_dir": m5out_dir,
            "max_ticks": max_ticks,
            "cpu_type": cpu_type,
        }

    if output_path.exists():
        output_path.unlink()
    logs = _subprocess_log_paths(output_path, "gem5")
    env = os.environ.copy()
    env.update(_gem5_env(request, request_root, output_path, mode, gem5_config, bridge_ref))
    if real_qe_context is not None:
        qe_binary = real_qe_context["qe_binary"]
        qe_input = real_qe_context["qe_input"]
        run_dir = real_qe_context["run_dir"]
        m5out_dir = real_qe_context["m5out_dir"]
        max_ticks = real_qe_context["max_ticks"]
        cpu_type = real_qe_context["cpu_type"]
        command = [
            str(executable),
            "-d",
            str(m5out_dir),
            str(gem5_config),
            "--binary",
            str(qe_binary),
            "--options",
            f"-in {qe_input}",
            "--fpga-execution-mode",
            "smoke",
            "--max-ticks",
            str(max_ticks),
            "--cpu-type",
            str(cpu_type),
        ]
        cwd = str(run_dir)
    else:
        command = [str(executable), str(gem5_config)]
        cwd = str(gem5_config.parent)
    try:
        completed = _run_logged_subprocess(
            command,
            cwd=cwd,
            env=env,
            logs=logs,
            timeout_s=max(0.1, timeout_s),
        )
    except subprocess.TimeoutExpired as exc:
        if not logs["stdout"].exists():
            logs["stdout"].write_text(exc.stdout or "", encoding="utf-8")
        if not logs["stderr"].exists():
            logs["stderr"].write_text(exc.stderr or "", encoding="utf-8")
        report = refusal_report(
            request,
            mode=mode,
            reason=f"gem5 execution exceeded timeout_s={timeout_s}",
            artifact_refs={
                "gem5_executable": str(executable),
                "gem5_config": str(gem5_config),
                "gem5_stdout_log": str(logs["stdout"]),
                "gem5_stderr_log": str(logs["stderr"]),
            },
        )
        report["execution_status"] = "failed"
        report["status_reason"] = report.pop("refusal_reason")
        write_report(output_path, report)
        return 1
    except OSError as exc:
        report = refusal_report(
            request,
            mode=mode,
            reason=f"gem5 executable could not be launched: {exc}",
            artifact_refs={
                "gem5_executable": str(executable),
                "gem5_config": str(gem5_config),
                "gem5_stdout_log": str(logs["stdout"]),
                "gem5_stderr_log": str(logs["stderr"]),
            },
        )
        write_report(output_path, report)
        return 0

    if real_qe_context is not None:
        gem5_parse = _parse_qe_stdout(completed.stdout)
        manifest = dict(real_qe_context["manifest"])
        manifest.update(
            {
                "gem5_command": command,
                "gem5_returncode": completed.returncode,
                "gem5_stdout_log": str(logs["stdout"]),
                "gem5_stderr_log": str(logs["stderr"]),
                "gem5_parse": gem5_parse,
            }
        )
        _write_json(real_qe_context["manifest_path"], manifest)

    if completed.returncode != 0:
        if real_qe_context is not None:
            _real_qe_failure_report(
                request,
                output_path,
                mode,
                f"gem5 executable returned nonzero status {completed.returncode}",
                artifact_refs={
                    "artifact_subtype": REAL_QE_GEM5_SE_ARTIFACT_SUBTYPE,
                    "gem5_executable": str(executable),
                    "gem5_config": str(gem5_config),
                    "gem5_command": command,
                    "gem5_cpu_type": str(real_qe_context["cpu_type"]),
                    "gem5_stdout_log": str(logs["stdout"]),
                    "gem5_stderr_log": str(logs["stderr"]),
                    "native_stdout_log": str(real_qe_context["native_logs"]["stdout"]),
                    "native_stderr_log": str(real_qe_context["native_logs"]["stderr"]),
                    "qe_binary": str(real_qe_context["qe_binary"]),
                    "qe_input": str(real_qe_context["qe_input"]),
                    "gem5_qe_input": str(real_qe_context["gem5_qe_input"]),
                    "native_qe_input": str(real_qe_context["native_qe_input"]),
                    "qe_outdir": str(real_qe_context["qe_outdir"]),
                    "gem5_qe_outdir": str(real_qe_context["gem5_qe_outdir"]),
                    "native_qe_outdir": str(real_qe_context["native_qe_outdir"]),
                    "qe_run_dir": str(real_qe_context["run_dir"]),
                    "m5out_dir": str(real_qe_context["m5out_dir"]),
                    "run_manifest": str(real_qe_context["manifest_path"]),
                },
                environment={
                    "source": "gem5_se_real_pw_stdout_parser",
                    "gem5_mode": "SE",
                    "gem5_cpu_type": str(real_qe_context["cpu_type"]),
                    "fpga_execution_mode": "smoke",
                },
                control_path={"host_launch_count": 1, "completion_source": "gem5_se_real_pw_stdout_parser"},
            )
            return 1
        report = refusal_report(
            request,
            mode=mode,
            reason=f"gem5 executable returned nonzero status {completed.returncode}",
            artifact_refs={
                "gem5_executable": str(executable),
                "gem5_config": str(gem5_config),
                "gem5_stdout_log": str(logs["stdout"]),
                "gem5_stderr_log": str(logs["stderr"]),
                "gem5_command": command,
            },
        )
        report["execution_status"] = "failed"
        report["status_reason"] = report.pop("refusal_reason")
        write_report(output_path, report)
        return 1

    if output_path.exists():
        if not _accept_direct_backend_report(
            request, output_path, mode, expected_systemc_bridge=bridge_ref
        ):
            return 1 if strict_report_validation else 0
        payload = load_json(output_path)
        payload_artifacts = payload.get("artifact_refs")
        if isinstance(payload_artifacts, dict):
            payload_artifacts.setdefault("gem5_executable", str(executable))
            payload_artifacts.setdefault("gem5_config", str(gem5_config))
            payload_artifacts.setdefault("gem5_stdout_log", str(logs["stdout"]))
            payload_artifacts.setdefault("gem5_stderr_log", str(logs["stderr"]))
            if bridge_ref is not None:
                payload_artifacts.setdefault("systemc_bridge", str(bridge_ref))
            if real_qe_context is not None:
                payload_artifacts.setdefault("artifact_subtype", REAL_QE_GEM5_SE_ARTIFACT_SUBTYPE)
                payload_artifacts.setdefault("run_manifest", str(real_qe_context["manifest_path"]))
                payload_artifacts.setdefault("qe_binary", str(real_qe_context["qe_binary"]))
                payload_artifacts.setdefault("qe_input", str(real_qe_context["qe_input"]))
                payload_artifacts.setdefault("gem5_qe_input", str(real_qe_context["gem5_qe_input"]))
                payload_artifacts.setdefault("native_qe_input", str(real_qe_context["native_qe_input"]))
                payload_artifacts.setdefault("qe_outdir", str(real_qe_context["qe_outdir"]))
                payload_artifacts.setdefault("gem5_qe_outdir", str(real_qe_context["gem5_qe_outdir"]))
                payload_artifacts.setdefault("native_qe_outdir", str(real_qe_context["native_qe_outdir"]))
                payload_artifacts.setdefault("gem5_cpu_type", str(real_qe_context["cpu_type"]))
            write_report(output_path, payload)
        return 0

    if real_qe_context is not None:
        gem5_parse = _parse_qe_stdout(completed.stdout)
        ticks = gem5_parse.get("gem5_exit_tick")
        success = (
            gem5_parse.get("scf_converged") is True
            and gem5_parse.get("job_done") is True
            and isinstance(ticks, int)
            and gem5_parse.get("gem5_hit_tick_limit") is not True
        )
        common_artifacts: dict[str, Any] = {
            "artifact_subtype": REAL_QE_GEM5_SE_ARTIFACT_SUBTYPE,
            "gem5_executable": str(executable),
            "gem5_config": str(gem5_config),
            "gem5_command": command,
            "gem5_cpu_type": str(real_qe_context["cpu_type"]),
            "gem5_stdout_log": str(logs["stdout"]),
            "gem5_stderr_log": str(logs["stderr"]),
            "native_stdout_log": str(real_qe_context["native_logs"]["stdout"]),
            "native_stderr_log": str(real_qe_context["native_logs"]["stderr"]),
            "qe_binary": str(real_qe_context["qe_binary"]),
            "qe_input_template": str(real_qe_context["qe_input_template"]),
            "qe_input": str(real_qe_context["qe_input"]),
            "gem5_qe_input": str(real_qe_context["gem5_qe_input"]),
            "native_qe_input": str(real_qe_context["native_qe_input"]),
            "qe_pseudo_dir": str(real_qe_context["qe_pseudo_dir"]),
            "qe_outdir": str(real_qe_context["qe_outdir"]),
            "gem5_qe_outdir": str(real_qe_context["gem5_qe_outdir"]),
            "native_qe_outdir": str(real_qe_context["native_qe_outdir"]),
            "qe_run_dir": str(real_qe_context["run_dir"]),
            "m5out_dir": str(real_qe_context["m5out_dir"]),
            "run_manifest": str(real_qe_context["manifest_path"]),
        }
        metrics = {
            "cycle_proxy": ticks if isinstance(ticks, int) else None,
            "runtime_smoke_ticks": ticks if isinstance(ticks, int) else None,
        }
        control_path = {
            "host_launch_count": 1,
            "completion_count": 1 if success else 0,
            "fallback_count": 0,
            "deadlock": False,
            "completion_source": "gem5_se_real_pw_stdout_parser",
        }
        environment = {
            "source": "gem5_se_real_pw_stdout_parser",
            "gem5_mode": "SE",
            "gem5_cpu_type": str(real_qe_context["cpu_type"]),
            "fpga_execution_mode": "smoke",
        }
        if success:
            report = make_report(
                request,
                mode=mode,
                execution_status="executed",
                environment=environment,
                control_path=control_path,
                metrics=metrics,
                artifact_refs=common_artifacts,
                non_claims=REAL_QE_NON_CLAIMS,
                notes=["real_qe_gem5_se_scf_smoke_v0; report remains bounded by smoke-only non-claims"],
            )
            write_report(output_path, report)
            return 0
        reason = "gem5 real QE smoke did not expose required convergence, JOB DONE, and exit tick markers"
        if gem5_parse.get("gem5_hit_tick_limit") is True:
            reason = "gem5 real QE smoke stopped at the configured tick limit before accepted completion"
        _real_qe_failure_report(
            request,
            output_path,
            mode,
            reason,
            artifact_refs=common_artifacts,
            environment=environment,
            control_path=control_path,
            metrics=metrics,
            notes=["real_qe_gem5_se_scf_smoke_v0 failed parser acceptance; no elevated claim is made"],
        )
        return 1

    report = refusal_report(
        request,
        mode=mode,
        reason="gem5 execution completed but did not produce a BackendExecutionReport",
        artifact_refs={
            "gem5_executable": str(executable),
            "gem5_config": str(gem5_config),
            "gem5_stdout_log": str(logs["stdout"]),
            "gem5_stderr_log": str(logs["stderr"]),
            "backend_execution_report_status": "missing",
        },
    )
    report["execution_status"] = "failed"
    report["status_reason"] = report.pop("refusal_reason")
    write_report(output_path, report)
    return 1

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    request_path = Path(args.request).resolve()
    request_root = request_path.resolve().parent
    output_path = Path(args.output).resolve()
    mode = args.mode

    request, early_rc = _load_request_or_refuse(request_path, output_path, mode)
    if early_rc is not None:
        return early_rc
    assert request is not None

    if args.dry_run:
        report = refusal_report(
            request,
            mode=mode,
            reason="dry-run requested; backend execution was not attempted",
            artifact_refs={"request": str(request_path)},
        )
        write_report(output_path, report)
        return 0

    if args.legacy_b3_report is not None:
        if mode != "gem5_systemc_smoke":
            report = refusal_report(
                request,
                mode=mode,
                reason="--legacy-b3-report is only valid with gem5_systemc_smoke mode",
                artifact_refs={"legacy_b3_smoke_report": args.legacy_b3_report},
            )
            write_report(output_path, report)
            return 0
        executable_candidate, gate_rc = _candidate_execution_gate(
            request,
            output_path,
            mode,
            allow_non_executable_debug=args.allow_non_executable_debug,
        )
        if not executable_candidate:
            return gate_rc
        return _convert_legacy_b3(request, output_path, Path(args.legacy_b3_report))

    if not args.allow_execute:
        report = refusal_report(
            request,
            mode=mode,
            reason="execution requires explicit --allow-execute opt-in",
            artifact_refs={"request": str(request_path)},
        )
        write_report(output_path, report)
        return 0

    executable_candidate, gate_rc = _candidate_execution_gate(
        request,
        output_path,
        mode,
        allow_non_executable_debug=args.allow_non_executable_debug,
    )
    if not executable_candidate:
        return gate_rc

    if mode in {"systemc_standalone", "systemc_timed_functional"}:
        result_path = _systemc_candidate_result_path(request, request_root)
        if result_path is not None:
            return _convert_existing_systemc_result(request, output_path, mode, result_path)
        return _run_systemc(
            request,
            output_path,
            mode,
            request_root,
            args.strict_report_validation,
        )

    if mode in {"gem5_systemc_smoke", "gem5_systemc_timed_proxy"}:
        return _run_gem5(
            request,
            output_path,
            mode,
            request_root,
            args.timeout_s,
            args.strict_report_validation,
        )

    report = refusal_report(request, mode=mode, reason=f"unsupported backend mode: {mode}")
    write_report(output_path, report)
    validate_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
