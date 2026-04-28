#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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
    refusal_report,
    validate_request,
    validate_report,
)

DEFAULT_LEGACY_B3_REPORT = ROOT / "docs/benchmarks/results/qe_dse_gem5_systemc_smoke_report_v0.json"
DEFAULT_SYSTEMC_EXECUTABLE = ROOT / "model/qe_band_solver_model/build/qe_band_solver_model"
DEFAULT_GEM5_EXECUTABLE = ROOT / "gem5_integration/gem5/build/X86/gem5.opt"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or refuse backend execution request v0")
    parser.add_argument("--request", required=True, help="BackendExecutionRequest JSON path")
    parser.add_argument("--output", required=True, help="BackendExecutionReport JSON output path")
    parser.add_argument("--mode", required=True, choices=sorted(MODE_TO_CLAIM_CEILING))
    parser.add_argument("--dry-run", action="store_true", help="Do not execute; emit a refused report")
    parser.add_argument("--allow-execute", action="store_true", help="Allow local backend executable invocation")
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


def _systemc_executable(request: Mapping[str, Any], request_root: Path) -> Path:
    refs = _request_input_refs(request)
    return _path_from_ref(refs.get("systemc_executable"), request_root) or DEFAULT_SYSTEMC_EXECUTABLE


def _gem5_executable(request: Mapping[str, Any], request_root: Path) -> Path:
    refs = _request_input_refs(request)
    return _path_from_ref(refs.get("gem5_executable"), request_root) or DEFAULT_GEM5_EXECUTABLE


def _systemc_candidate_result_path(request: Mapping[str, Any], request_root: Path) -> Path | None:
    refs = _request_input_refs(request)
    for key in ("systemc_candidate_result", "systemc_result_json", "systemc_report"):
        path = _path_from_ref(refs.get(key), request_root)
        if path is not None:
            return path
    return None


def _systemc_candidate_output_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.systemc_candidate_result.json")


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

    # Compatibility aliases consumed by the current qe_band_solver_model/sc_main.cpp.
    arch_config = _resolved_input_ref(
        request,
        request_root,
        "architecture_config",
        "arch_config",
        "systemc_config",
    )
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
    return env


def _accept_direct_backend_report(
    request: Mapping[str, Any],
    output_path: Path,
    mode: str,
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
    except Exception as exc:
        report = refusal_report(
            request,
            mode=mode,
            reason=f"direct BackendExecutionReport validation failed: {exc}",
            artifact_refs={"direct_backend_execution_report": str(output_path)},
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


def _run_systemc(request: Mapping[str, Any], output_path: Path, mode: str, request_root: Path) -> int:
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
    completed = subprocess.run([str(executable)], cwd=str(executable.parent), env=env, check=False)
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
            },
        )
        report["execution_status"] = "failed"
        report["status_reason"] = report.pop("refusal_reason")
        write_report(output_path, report)
        return 1
    if output_path.exists():
        _accept_direct_backend_report(request, output_path, mode)
        return 0
    return _convert_existing_systemc_result(request, output_path, mode, result_path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    request_path = Path(args.request)
    request_root = request_path.resolve().parent
    output_path = Path(args.output)
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

    if mode in {"systemc_standalone", "systemc_timed_functional"}:
        result_path = _systemc_candidate_result_path(request, request_root)
        if result_path is not None:
            return _convert_existing_systemc_result(request, output_path, mode, result_path)
        return _run_systemc(request, output_path, mode, request_root)

    if mode in {"gem5_systemc_smoke", "gem5_systemc_timed_proxy"}:
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
        report = refusal_report(
            request,
            mode=mode,
            reason="direct gem5 execution is not implemented in P0a; use --legacy-b3-report for B3 conversion",
            artifact_refs={"gem5_executable": str(executable)},
        )
        write_report(output_path, report)
        return 0

    report = refusal_report(request, mode=mode, reason=f"unsupported backend mode: {mode}")
    write_report(output_path, report)
    validate_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
