#!/usr/bin/env python3
"""Run a QE ``h_psi`` component sidecar through gem5 GenericAccel transport.

This command is designed to be used as ``QE_OFFLOAD_HPSI_SIDECAR_CMD`` by the
instrumented QE ``h_psi`` hook.  It launches the real GenericAccel L4 driver in
gem5 with ``--use-systemc``; the GenericAccel sidecar executable then writes
the h_psi result text file that QE consumes.

Claim boundary: the transport path is real gem5 GenericAccel evidence, but the
numeric payload is still produced by the Python component model.  The summary
therefore remains ``software_component_model_not_l4=true`` and must not unlock
trusted correctness or speedup gates by itself.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.qe_hpsi_sidecar import build_hpsi_boundary_probe_request  # noqa: E402


SCHEMA = "dse.qe_hpsi_gem5_component_sidecar_summary.v1"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_repo_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _complex_pairs(values: Any) -> list[complex]:
    out: list[complex] = []
    if not isinstance(values, list):
        return out
    for item in values:
        if isinstance(item, Sequence) and len(item) >= 2:
            try:
                out.append(complex(float(item[0]), float(item[1])))
            except (TypeError, ValueError):
                out.append(0.0 + 0.0j)
    return out


def _l2(values: Sequence[complex]) -> float:
    return math.sqrt(sum(abs(value) ** 2 for value in values))


def _snapshot_from_arrays(arrays: Mapping[str, Any]) -> dict[str, Any]:
    psi = _complex_pairs(arrays.get("psi_real_imag", []))
    hpsi = _complex_pairs(arrays.get("hpsi_reference_real_imag", []))
    return {
        "schema_version": "dse.qe_hpsi_kernel_boundary_snapshot.v1",
        "kernel_id": "h_psi",
        "dimensions": dict(arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}),
        "psi_l2_norm": _l2(psi),
        "hpsi_l2_norm": _l2(hpsi),
        "hpsi_abs_sum": sum(abs(value) for value in hpsi),
        "source": "qe_hpsi_gem5_component_sidecar_snapshot_from_arrays",
        "claim_boundary": "Derived from QE boundary arrays for gem5 sidecar transport; not accelerated output.",
    }


def _default_gem5_bin() -> Path:
    return REPO_ROOT / "gem5_integration" / "gem5" / "build" / "X86" / "gem5.opt"


def _default_gem5_config() -> Path:
    return REPO_ROOT / "gem5_integration" / "configs" / "generic_accel_l4_test.py"


def _default_gem5_driver() -> Path:
    return REPO_ROOT / "gem5_integration" / "test_programs" / "generic_accel" / "generic_accel_l4_driver"


def _default_sidecar_simulator() -> Path:
    return REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_qe_hpsi_component_gsim_sidecar.py"


def _check_log(
    log: str,
    stdout: str,
    returncode: int,
    result_txt: Path,
    component_summary: Mapping[str, Any],
    *,
    payload_mode: str,
) -> dict[str, Any]:
    expected_status = "passed_native_l4_payload" if payload_mode == "native_l4" else "passed_component_model"
    checks = {
        "gem5_returncode_zero": returncode == 0,
        "guest_status_passed": "generic_accel_l4_status=1 error_code=0" in stdout,
        "descriptor_read_verified": "descriptor_read verified=true" in log,
        "uarch_request_decode_verified": "uarch_request_decode verified=true" in log,
        "microarchitecture_execute_verified": "microarchitecture_execute verified=true" in log,
        "completion_writeback_verified": "completion_writeback verified=true" in log,
        "systemc_submit_verified": "systemc_submit verified=true" in log,
        "hpsi_result_txt_exists": result_txt.exists() and result_txt.stat().st_size > 0,
        "component_summary_passed": component_summary.get("status") == expected_status,
    }
    missing = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not missing,
        "transport_harness": "gem5_generic_accel_systemc_sidecar",
        "checks": checks,
        "missing_evidence": missing,
        "systemc_submit_result_path": _extract_token(r"systemc_submit verified=true.*result_path=(\\S+)", log),
    }


def _extract_token(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary-arrays", type=Path, required=True)
    parser.add_argument("--result-txt", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--gem5-bin", type=Path, default=_default_gem5_bin())
    parser.add_argument("--gem5-config", type=Path, default=_default_gem5_config())
    parser.add_argument("--gem5-driver", type=Path, default=_default_gem5_driver())
    parser.add_argument("--sidecar-simulator", type=Path, default=_default_sidecar_simulator())
    parser.add_argument(
        "--payload-mode",
        choices=["component_model", "native_l4"],
        default=os.environ.get("QE_OFFLOAD_HPSI_PAYLOAD_MODE", "component_model"),
        help="component_model preserves the old blocked Python payload; native_l4 dispatches a native h_psi payload executable.",
    )
    parser.add_argument(
        "--native-payload-bin",
        type=Path,
        default=Path(os.environ["QE_HPSI_NATIVE_PAYLOAD_BIN"]) if os.environ.get("QE_HPSI_NATIVE_PAYLOAD_BIN") else None,
        help="Native h_psi payload executable used when --payload-mode native_l4.",
    )
    parser.add_argument("--candidate-id", default=os.environ.get("QE_OFFLOAD_CANDIDATE_ID", "unknown_candidate"))
    parser.add_argument("--workload-case-id", default=os.environ.get("QE_OFFLOAD_WORKLOAD_CASE_ID", "unknown_workload"))
    parser.add_argument("--max-ticks", type=int, default=10_000_000_000)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--cpu-type", choices=["atomic", "timing"], default="atomic")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--fail-on-blocked", action="store_true")
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    boundary_arrays = _resolve_repo_path(args.boundary_arrays) or args.boundary_arrays
    result_txt = _resolve_repo_path(args.result_txt) or args.result_txt
    summary_json = _resolve_repo_path(args.summary_json) or args.summary_json
    work_dir = _resolve_repo_path(args.work_dir) if args.work_dir is not None else summary_json.parent / "gem5_hpsi_component_sidecar"
    assert work_dir is not None
    gem5_bin = _resolve_repo_path(args.gem5_bin) or args.gem5_bin
    gem5_config = _resolve_repo_path(args.gem5_config) or args.gem5_config
    gem5_driver = _resolve_repo_path(args.gem5_driver) or args.gem5_driver
    sidecar_simulator = _resolve_repo_path(args.sidecar_simulator) or args.sidecar_simulator
    native_payload_bin = _resolve_repo_path(args.native_payload_bin) if args.native_payload_bin is not None else None
    work_dir.mkdir(parents=True, exist_ok=True)

    arrays = _load_json(boundary_arrays)
    if not isinstance(arrays, Mapping):
        raise ValueError(f"boundary arrays must be a JSON object: {boundary_arrays}")
    snapshot = _snapshot_from_arrays(arrays)
    request = build_hpsi_boundary_probe_request(
        candidate_id=args.candidate_id,
        workload_case_id=args.workload_case_id,
        snapshot=snapshot,
    )
    extension = request.setdefault("extension_payload", {})
    if isinstance(extension, dict):
        extension["qe_hpsi_component_sidecar"] = {
            "schema_version": "dse.qe_hpsi_component_sidecar_dispatch.v1",
            "candidate_id": args.candidate_id,
            "workload_case_id": args.workload_case_id,
            "payload_mode": args.payload_mode,
            "boundary_arrays_json": str(boundary_arrays),
            "result_txt": str(result_txt),
            "summary_json": str(summary_json),
            "native_payload_executable": str(native_payload_bin) if native_payload_bin is not None else None,
            "claim_boundary": (
                "Payload requests a native QE-consumable h_psi result through GenericAccel sidecar transport. "
                "The claim is SystemC/GenericAccel model L4 offload plus kernel numerical evidence, not silicon/RTL proof."
                if args.payload_mode == "native_l4"
                else "Payload requests a QE-consumable h_psi component result through GenericAccel sidecar transport. "
                "The numeric model remains software and untrusted for final L4 correctness."
            ),
        }
    request["sidecar_dispatch"] = {
        "mode": "gem5_generic_accel_systemc_sidecar",
        "model": "qe_hpsi_component_gsim_sidecar",
        "payload_mode": args.payload_mode,
    }
    request_path = work_dir / "simulation_request.json"
    _write_json(request_path, request)

    m5out = work_dir / "m5out"
    stdout_path = work_dir / "gem5.stdout.log"
    stderr_path = work_dir / "gem5.stderr.log"
    cmd = [
        str(gem5_bin),
        f"--outdir={m5out}",
        "--debug-flags=GenericAccel",
        "--debug-file=gem5.log",
        str(gem5_config),
        "--binary",
        str(gem5_driver),
        "--request",
        str(request_path),
        "--simulator",
        str(sidecar_simulator),
        "--max-ticks",
        str(args.max_ticks),
        "--cpu-type",
        args.cpu_type,
        "--use-systemc",
    ]
    blockers: list[str] = []
    if args.payload_mode == "native_l4":
        if native_payload_bin is None:
            blockers.append("missing_native_hpsi_payload_bin")
        elif not native_payload_bin.exists():
            blockers.append(f"native_hpsi_payload_bin_missing:{native_payload_bin}")
    try:
        completed = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(cmd, 124, exc.stdout or "", exc.stderr or "")
        blockers.append(f"gem5_timeout:{args.timeout}")
    stdout_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")
    gem5_log_path = m5out / "gem5.log"
    gem5_log = gem5_log_path.read_text(encoding="utf-8", errors="replace") if gem5_log_path.exists() else ""
    component_summary: Mapping[str, Any] = {}
    if summary_json.exists():
        loaded = _load_json(summary_json)
        if isinstance(loaded, Mapping):
            component_summary = loaded
    proof = _check_log(
        gem5_log,
        completed.stdout or "",
        completed.returncode,
        result_txt,
        component_summary,
        payload_mode=args.payload_mode,
    )
    if not proof["passed"]:
        blockers.extend(str(item) for item in proof["missing_evidence"])
    trusted_native_payload = (
        args.payload_mode == "native_l4"
        and not blockers
        and component_summary.get("trusted_full_claim") is True
        and component_summary.get("software_component_model_not_l4") is not True
    )

    merged_summary = dict(component_summary)
    merged_summary.update(
        {
            "schema_version": SCHEMA,
            "status": (
                "passed_gem5_transport_native_l4_payload"
                if trusted_native_payload
                else ("passed_gem5_transport_component_model" if not blockers else "blocked")
            ),
            "blockers": sorted(dict.fromkeys([*map(str, component_summary.get("blockers", []) or []), *blockers])),
            "gem5_l4_transport_proof": proof,
            "payload_mode": args.payload_mode,
            "gem5_l4_artifacts": {
                "work_dir": str(work_dir),
                "request_json": str(request_path),
                "m5out": str(m5out),
                "gem5_log": str(gem5_log_path),
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
                "cmd": cmd,
            },
            "native_payload_executable": str(native_payload_bin) if native_payload_bin is not None else None,
            "software_component_model_not_l4": False if trusted_native_payload else True,
            "trusted_full_claim": trusted_native_payload,
            "claim_boundary": (
                "QE h_psi payload was produced through gem5 GenericAccel sidecar transport by a native payload model. "
                "This is SystemC/GenericAccel model L4 offload plus kernel numerical evidence, not silicon/RTL proof."
                if trusted_native_payload
                else "QE h_psi payload was produced through gem5 GenericAccel sidecar transport, but the payload is "
                "still computed by the Python component model. This is integration/foundation evidence and must "
                "remain blocked for trusted non-software L4 correctness."
            ),
        }
    )
    _write_json(summary_json, merged_summary)
    if not args.quiet:
        print(json.dumps(merged_summary, indent=2, sort_keys=True))
    return 2 if args.fail_on_blocked and blockers else 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
