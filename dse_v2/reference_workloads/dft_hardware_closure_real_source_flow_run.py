#!/usr/bin/env python3
"""Execute candidate/kernel RTL/HLS source-flow shards through real or local tools.

This DFT-profile helper is intentionally outside the generic control plane. It
turns a packetized closure matrix into concrete runner invocations for selected
candidate/kernel units, records every command/result, and emits a
``source_flow_map.json`` consumable by the source-flow plan.  The run artifact is
execution/provenance only: raw hard-gate files still must pass materialization,
parser, gate-adjudication, and release-gate stages before any claim can advance.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.reference_workloads.dft_hardware_closure_source_flow_plan import _all_units

DFT_HARDWARE_CLOSURE_REAL_SOURCE_FLOW_RUN_SCHEMA = (
    "dse.dft.hardware_closure_real_source_flow_run.v1"
)
DFT_HARDWARE_CLOSURE_REAL_SOURCE_FLOW_RUN_VALIDATION_SCHEMA = (
    "dse.dft.hardware_closure_real_source_flow_run_validation.v1"
)
DFT_HARDWARE_CLOSURE_REAL_SOURCE_FLOW_RUN_STATUS_SCHEMA = (
    "dse.dft.hardware_closure_real_source_flow_run_status.v1"
)
SOURCE_FLOW_MAP_SCHEMA = "dse.dft.hardware_closure_source_flow_map.v0.real_source_flow_run"

KERNEL_RUNNER_SCRIPTS: Dict[str, str] = {
    "complex_gemm_gemv_tile": "dse_v2/scripts/dse/run_dft_complex_gemm_gemv_rtl_flow.py",
    "dma_hbm_movement_engine": "dse_v2/scripts/dse/run_dft_dma_hbm_rtl_flow.py",
    "fft_ifft_ffft": "dse_v2/scripts/dse/run_dft_fft_ifft_rtl_flow.py",
    "hpsi_local_potential": "dse_v2/scripts/dse/run_dft_hpsi_local_rtl_flow.py",
    "kinetic_add": "dse_v2/scripts/dse/run_dft_kinetic_add_rtl_flow.py",
    "nonlocal_projector": "dse_v2/scripts/dse/run_dft_nonlocal_projector_rtl_flow.py",
    "reduction_dot_tree": "dse_v2/scripts/dse/run_dft_reduction_dot_rtl_flow.py",
    "transpose_layout_conversion": "dse_v2/scripts/dse/run_dft_transpose_layout_rtl_flow.py",
}

_CLAIM_BOUNDARY = (
    "DFT hardware closure real source-flow execution runs selected candidate/kernel "
    "RTL/HLS tool flows and records command/source-flow provenance. It does not "
    "materialize packet raw evidence, parse hard-gate pass/fail, certify PPA, "
    "select trusted Pareto winners, or mark hardware/deliverable completion."
)


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "exists": candidate.exists() and candidate.is_file(),
        "sha256": sha256_file(candidate) if candidate.exists() and candidate.is_file() else None,
        "hash_algorithm": "sha256",
    }


def _directory_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "resolved_path": str(candidate.resolve()) if candidate.exists() else str(candidate),
        "exists": candidate.exists() and candidate.is_dir(),
    }


def _split_values(values: Sequence[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for item in str(value).split(","):
            stripped = item.strip()
            if stripped:
                items.append(stripped)
    return items


def _remote_slug(value: object) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    slug = slug.strip("._-")
    return slug or "run"


def _unit_key(unit: Mapping[str, Any]) -> tuple[str, str]:
    return str(unit.get("candidate_id", "")), str(unit.get("kernel_id", ""))


def selected_units_from_packet_index(
    closure_packet_index_path: Path,
    *,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    max_units: int | None = None,
) -> tuple[Dict[str, Any], list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Return packet units selected for source-flow execution."""

    packet_index, units, packet_errors = _all_units(Path(closure_packet_index_path))
    candidate_filter = set(candidate_ids)
    kernel_filter = set(kernel_ids)
    selected: list[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for unit in units:
        key = _unit_key(unit)
        if key in seen:
            continue
        seen.add(key)
        if candidate_filter and key[0] not in candidate_filter:
            continue
        if kernel_filter and key[1] not in kernel_filter:
            continue
        selected.append(dict(unit))
        if max_units is not None and len(selected) >= max_units:
            break
    return packet_index, selected, packet_errors


def _manifest_identity(source_flow_dir: Path) -> tuple[str, str]:
    manifest = _load_json(source_flow_dir / "manifest.json")
    return str(manifest.get("candidate_id") or ""), str(manifest.get("kernel_id") or "")


def _command_for_unit(
    unit: Mapping[str, Any],
    *,
    out_root: Path,
    ssh_target: str,
    timeout_s: int,
    skip_remote: bool,
    allow_blocked: bool,
) -> tuple[Path, list[str], list[str]]:
    candidate_id, kernel_id = _unit_key(unit)
    script = KERNEL_RUNNER_SCRIPTS.get(kernel_id)
    if script is None:
        return out_root / candidate_id / kernel_id, [], [f"unsupported_kernel_runner:{kernel_id}"]
    source_flow_dir = out_root / candidate_id / kernel_id
    run_slug = _remote_slug(out_root.parent.name if out_root.name == "source_flows" else out_root.name)
    remote_dir = f"/tmp/dft_accelerate_{run_slug}_{_remote_slug(candidate_id)}_{_remote_slug(kernel_id)}"
    command = [
        sys.executable,
        script,
        "--out",
        str(source_flow_dir),
        "--candidate-id",
        candidate_id,
        "--ssh-target",
        ssh_target,
        "--timeout-s",
        str(timeout_s),
        "--remote-dir",
        remote_dir,
    ]
    candidate_bundle_json = str(
        unit.get("candidate_bundle_json_resolved") or unit.get("candidate_bundle_json") or ""
    )
    if candidate_bundle_json:
        command.extend(["--candidate-bundle", candidate_bundle_json])
    if skip_remote:
        command.append("--skip-remote")
    if allow_blocked:
        command.append("--allow-blocked")
    return source_flow_dir, command, []


def _run_one(
    unit: Mapping[str, Any],
    *,
    out_root: Path,
    ssh_target: str,
    timeout_s: int,
    skip_remote: bool,
    allow_blocked: bool,
) -> Dict[str, Any]:
    candidate_id, kernel_id = _unit_key(unit)
    source_flow_dir, command, command_errors = _command_for_unit(
        unit,
        out_root=out_root,
        ssh_target=ssh_target,
        timeout_s=timeout_s,
        skip_remote=skip_remote,
        allow_blocked=allow_blocked,
    )
    started = time.time()
    if command_errors:
        return {
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "status": "failed_no_runner",
            "source_flow_dir": str(source_flow_dir),
            "command": command,
            "returncode": 127,
            "elapsed_s": 0.0,
            "stdout_tail": "",
            "stderr_tail": "\n".join(command_errors),
            "manifest_candidate_id": None,
            "manifest_kernel_id": None,
            "source_flow_ready": False,
            "blocker_ids": command_errors,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": _CLAIM_BOUNDARY,
        }
    source_flow_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(timeout_s + 60, timeout_s),
        )
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\ntimeout after {timeout_s}s"
    except OSError as exc:
        returncode = 127
        stdout = ""
        stderr = str(exc)
    manifest_candidate_id, manifest_kernel_id = _manifest_identity(source_flow_dir)
    blocker_ids: list[str] = []
    if returncode != 0:
        blocker_ids.append("runner_returncode_nonzero")
    if manifest_candidate_id != candidate_id:
        blocker_ids.append("runner_manifest_candidate_id_mismatch_or_missing")
    if manifest_kernel_id != kernel_id:
        blocker_ids.append("runner_manifest_kernel_id_mismatch_or_missing")
    source_flow_ready = not blocker_ids
    status = "source_flow_ready_pending_step5" if source_flow_ready else "blocked_source_flow_runner"
    matrix = _load_json(source_flow_dir / "dft_hardware_evidence_matrix.json")
    flow_status = _load_json(source_flow_dir / "status.json")
    return {
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
        "status": status,
        "source_flow_dir": str(source_flow_dir),
        "source_flow_ref": _directory_ref(source_flow_dir),
        "manifest_ref": _source_ref(source_flow_dir / "manifest.json"),
        "manifest_candidate_id": manifest_candidate_id or None,
        "manifest_kernel_id": manifest_kernel_id or None,
        "command": command,
        "returncode": returncode,
        "elapsed_s": round(time.time() - started, 3),
        "stdout_tail": stdout[-2000:],
        "stderr_tail": stderr[-2000:],
        "flow_status": flow_status.get("status"),
        "matrix_status": matrix.get("status"),
        "matrix_trusted": bool(matrix.get("trusted", False)) if matrix else False,
        "source_flow_ready": source_flow_ready,
        "blocker_ids": blocker_ids,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_source_flow_map_payload(
    *,
    closure_packet_index_path: Path,
    run_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    flows = [
        {
            "candidate_id": str(row.get("candidate_id", "")),
            "kernel_id": str(row.get("kernel_id", "")),
            "source_flow_dir": str(row.get("source_flow_dir", "")),
        }
        for row in run_rows
        if row.get("source_flow_ready") is True
    ]
    return {
        "schema_version": SOURCE_FLOW_MAP_SCHEMA,
        "closure_packet_index": str(closure_packet_index_path),
        "flows": sorted(flows, key=lambda row: (row["candidate_id"], row["kernel_id"])),
        "flow_count": len(flows),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_hardware_closure_real_source_flow_run(
    *,
    closure_packet_index_path: Path,
    out_root: Path,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    max_units: int | None = None,
    jobs: int = 1,
    ssh_target: str = "ic-eda",
    timeout_s: int = 900,
    skip_remote: bool = False,
    allow_blocked: bool = True,
) -> Dict[str, Any]:
    packet_index, units, packet_errors = selected_units_from_packet_index(
        closure_packet_index_path,
        candidate_ids=candidate_ids,
        kernel_ids=kernel_ids,
        max_units=max_units,
    )
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    rows: list[Dict[str, Any]] = []
    if units:
        max_workers = max(1, min(int(jobs or 1), len(units)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    _run_one,
                    unit,
                    out_root=out_root,
                    ssh_target=ssh_target,
                    timeout_s=timeout_s,
                    skip_remote=skip_remote,
                    allow_blocked=allow_blocked,
                )
                for unit in units
            ]
            for future in concurrent.futures.as_completed(futures):
                rows.append(future.result())
    rows = sorted(rows, key=lambda row: (str(row.get("candidate_id", "")), str(row.get("kernel_id", ""))))
    ready_count = sum(1 for row in rows if row.get("source_flow_ready") is True)
    failed_count = len(rows) - ready_count
    status = (
        "failed_invalid_packet_index"
        if packet_errors
        else "failed_no_units_selected"
        if not units
        else "source_flows_ready_pending_step5"
        if ready_count == len(units)
        else "blocked_partial_source_flow_run"
        if ready_count
        else "blocked_no_source_flows_ready"
    )
    payload = {
        "schema_version": DFT_HARDWARE_CLOSURE_REAL_SOURCE_FLOW_RUN_SCHEMA,
        "status": status,
        "source_artifacts": {
            "closure_packet_index": _source_ref(Path(closure_packet_index_path)),
        },
        "release_id": packet_index.get("release_id"),
        "candidate_count": len({row.get("candidate_id") for row in rows}),
        "major_kernel_count": len({row.get("kernel_id") for row in rows}),
        "selected_unit_count": len(units),
        "run_unit_count": len(rows),
        "source_flow_ready_count": ready_count,
        "blocked_unit_count": failed_count,
        "ssh_target": ssh_target,
        "timeout_s": timeout_s,
        "jobs": jobs,
        "skip_remote": skip_remote,
        "allow_blocked": allow_blocked,
        "packet_error_count": len(packet_errors),
        "packet_errors": packet_errors,
        "units": rows,
        "source_flow_map": "source_flow_map.json",
        "adjudication_result": "not_adjudicated_by_real_source_flow_run",
        "passed_stage_count": 0,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    return payload


def validate_dft_hardware_closure_real_source_flow_run(
    payload_or_path: Mapping[str, Any] | Path,
) -> Dict[str, Any]:
    payload = _load_json(payload_or_path) if isinstance(payload_or_path, Path) else dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_REAL_SOURCE_FLOW_RUN_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected real source-flow run schema"})
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            errors.append({"field": field, "message": "real source-flow execution cannot upgrade claims"})
    if payload.get("adjudication_result") != "not_adjudicated_by_real_source_flow_run":
        errors.append({"field": "adjudication_result", "message": "real source-flow execution cannot adjudicate gates"})
    if int(payload.get("passed_stage_count", 0) or 0) != 0:
        errors.append({"field": "passed_stage_count", "message": "real source-flow execution cannot pass hard-gate stages"})
    units = payload.get("units", [])
    if not isinstance(units, list):
        errors.append({"field": "units", "message": "units must be a list"})
        units = []
    ready_count = 0
    blocked_count = 0
    for index, row in enumerate(units):
        if not isinstance(row, Mapping):
            errors.append({"field": f"units[{index}]", "message": "unit row must be an object"})
            continue
        for field in ("hardware_completion_eligible", "deliverable_complete"):
            if row.get(field) is True:
                errors.append({"field": f"units[{index}].{field}", "message": "unit cannot upgrade claims"})
        ready = row.get("source_flow_ready") is True
        blockers = [str(item) for item in row.get("blocker_ids", []) or []]
        if ready:
            ready_count += 1
            if row.get("status") != "source_flow_ready_pending_step5":
                errors.append({"field": f"units[{index}].status", "message": "ready rows must remain pending Step5"})
            if blockers:
                errors.append({"field": f"units[{index}].blocker_ids", "message": "ready rows cannot have blockers"})
            if row.get("manifest_candidate_id") != row.get("candidate_id"):
                errors.append({"field": f"units[{index}].manifest_candidate_id", "message": "manifest candidate mismatch"})
            if row.get("manifest_kernel_id") != row.get("kernel_id"):
                errors.append({"field": f"units[{index}].manifest_kernel_id", "message": "manifest kernel mismatch"})
            manifest_ref = row.get("manifest_ref", {}) if isinstance(row.get("manifest_ref", {}), Mapping) else {}
            if manifest_ref.get("exists") is not True:
                errors.append({"field": f"units[{index}].manifest_ref", "message": "ready rows require manifest ref"})
        else:
            blocked_count += 1
            if not blockers:
                errors.append({"field": f"units[{index}].blocker_ids", "message": "blocked rows must explain blockers"})
    if int(payload.get("source_flow_ready_count", 0) or 0) != ready_count:
        errors.append({"field": "source_flow_ready_count", "message": f"expected {ready_count} from unit rows"})
    if int(payload.get("blocked_unit_count", 0) or 0) != blocked_count:
        errors.append({"field": "blocked_unit_count", "message": f"expected {blocked_count} from unit rows"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_REAL_SOURCE_FLOW_RUN_VALIDATION_SCHEMA,
        "valid": not errors,
        "run_unit_count": len(units),
        "source_flow_ready_count": ready_count,
        "blocked_unit_count": blocked_count,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_real_source_flow_run(
    out_dir: Path,
    *,
    closure_packet_index_path: Path,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    max_units: int | None = None,
    jobs: int = 1,
    ssh_target: str = "ic-eda",
    timeout_s: int = 900,
    skip_remote: bool = False,
    allow_blocked: bool = True,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    flow_root = out_dir / "source_flows"
    payload = build_dft_hardware_closure_real_source_flow_run(
        closure_packet_index_path=closure_packet_index_path,
        out_root=flow_root,
        candidate_ids=candidate_ids,
        kernel_ids=kernel_ids,
        max_units=max_units,
        jobs=jobs,
        ssh_target=ssh_target,
        timeout_s=timeout_s,
        skip_remote=skip_remote,
        allow_blocked=allow_blocked,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    map_payload = build_source_flow_map_payload(
        closure_packet_index_path=Path(closure_packet_index_path),
        run_rows=payload.get("units", []),
    )
    write_json(out_dir / "source_flow_map.json", map_payload)
    write_json(out_dir / "dft_hardware_closure_real_source_flow_run.json", payload)
    validation = validate_dft_hardware_closure_real_source_flow_run(payload)
    write_json(out_dir / "dft_hardware_closure_real_source_flow_run_validation.json", validation)
    status = {
        "schema_version": DFT_HARDWARE_CLOSURE_REAL_SOURCE_FLOW_RUN_STATUS_SCHEMA,
        "status": "passed" if validation["valid"] else "failed",
        "run_status": payload["status"],
        "real_source_flow_run": "dft_hardware_closure_real_source_flow_run.json",
        "validation": "dft_hardware_closure_real_source_flow_run_validation.json",
        "source_flow_map": "source_flow_map.json",
        "selected_unit_count": payload["selected_unit_count"],
        "source_flow_ready_count": payload["source_flow_ready_count"],
        "blocked_unit_count": payload["blocked_unit_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_real_source_flow_run_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_REAL_SOURCE_FLOW_RUN_SCHEMA",
    "KERNEL_RUNNER_SCRIPTS",
    "build_dft_hardware_closure_real_source_flow_run",
    "build_source_flow_map_payload",
    "selected_units_from_packet_index",
    "validate_dft_hardware_closure_real_source_flow_run",
    "write_dft_hardware_closure_real_source_flow_run",
]
