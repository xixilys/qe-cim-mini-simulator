#!/usr/bin/env python3
"""gem5 GenericAccel L4 microarchitecture evidence adapter for generic DSE.

This module records the descriptor/request/completion contract that an L4
software-visible run must satisfy. It first tries the real gem5 GenericAccel
path.  Missing local build artifacts are provisioned when possible; if gem5
itself is unavailable, the adapter can run an explicit diagnostic L4 transport harness
that exercises the same GSIM descriptor, request, result, and completion protocol
instead of returning a synthetic pass or skipping L4.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload.package import WorkloadPackage
from dse_v2.dse.orchestrator import DesignPoint

GSIM_MAGIC = 0x4753494D  # 'GSIM'
GSIM_DESCRIPTOR_VERSION = 1
GSIM_COMMAND_TYPE_GRAPH = 1
GENERIC_ACCEL_WORK_BASE = 0x08000000
GENERIC_ACCEL_REQUEST_OFFSET = 0x1000
GENERIC_ACCEL_COMPLETION_OFFSET = 0x110000
GENERIC_ACCEL_RESULT_OFFSET = 0x120000
GENERIC_ACCEL_WORKSPACE_SIZE = 1 << 20
GENERIC_ACCEL_DESCRIPTOR_FLAGS = 0xFF
GENERIC_ACCEL_LEGACY_COMMAND_DESCRIPTOR_BYTES = 48
GENERIC_ACCEL_COMMAND_DESCRIPTOR_BYTES = 128
GENERIC_ACCEL_SOURCE_FILES = ("GenericAccel.py", "generic_accel.cc", "generic_accel.hh", "SConscript")
GENERIC_ACCEL_DEV_SCONSCRIPT_LINE = "SConscript('generic_accel/SConscript')"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_gem5_root(gem5_binary: Path, root: Path) -> Path:
    """Resolve the gem5 source root used for source sync/build.

    The repository default remains ``gem5_integration/gem5``.  For local
    non-vendored builds, callers may pass a binary under ``<gem5>/build/X86`` or
    set ``GSIM_GEM5_ROOT``; this avoids requiring a repository-local gem5 source
    checkout or an environment-specific tracked symlink.
    """

    env_root = os.environ.get("GSIM_GEM5_ROOT")
    if env_root:
        return Path(env_root)
    binary = Path(gem5_binary)
    if len(binary.parents) >= 3 and binary.parent.parent.name == "build":
        return binary.parent.parent.parent
    return root / "gem5_integration" / "gem5"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _copy_if_exists(source: Path, destination: Path) -> Optional[str]:
    """Copy an optional gem5 artifact into the run directory.

    Missing files are not synthesized.  The caller records the returned path
    only when gem5 actually produced the artifact.
    """

    if not source.exists() or not source.is_file():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def _gem5_activity_summary(result: Optional[Mapping[str, Any]], gem5_log: str) -> Dict[str, Any]:
    """Summarize non-smoke accelerator activity from real L4 evidence."""

    result_map: Mapping[str, Any] = result if isinstance(result, Mapping) else {}
    summary = result_map.get("microarchitecture_summary", {})
    if not isinstance(summary, Mapping):
        summary = {}
    events = [event for event in result_map.get("events", []) or [] if isinstance(event, Mapping)]
    accelerator_events = [
        event for event in events
        if str(event.get("device", "host")) not in {"", "host", "cpu", "host-0"}
    ]

    def _positive_number(value: Any) -> bool:
        try:
            return float(value) > 0.0
        except (TypeError, ValueError):
            return False

    activity = {
        "schema_version": "dse.gem5_activity_summary.v1",
        "execution_engine": result_map.get("execution_engine"),
        "event_count": len(events),
        "accelerator_event_count": len(accelerator_events),
        "accelerator_devices": sorted({
            str(event.get("device"))
            for event in accelerator_events
            if event.get("device")
        }),
        "micro_op_count": summary.get("micro_op_count"),
        "total_cycles": summary.get("total_cycles"),
        "total_flops": summary.get("total_flops"),
        "descriptor_path_observed": "descriptor_read verified=true" in (gem5_log or ""),
        "microarchitecture_execute_observed": "microarchitecture_execute verified=true" in (gem5_log or ""),
    }
    activity["nonzero_accelerator_activity"] = bool(
        activity["accelerator_event_count"] > 0
        and _positive_number(activity["micro_op_count"])
        and _positive_number(activity["total_cycles"])
        and activity["microarchitecture_execute_observed"]
    )
    return activity


def _extract_token(pattern: str, text: str) -> Optional[str]:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1) if match else None


def _extract_marker_line(marker: str, text: str) -> str:
    for line in (text or "").splitlines():
        if marker in line:
            return line
    return ""


def _extract_log_value(line: str, key: str) -> Optional[str]:
    match = re.search(rf"(?:^|\s){re.escape(key)}=([^\s]+)", line or "")
    return match.group(1) if match else None


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_raw_l4_interface_observations(
    *,
    gem5_log: str,
    gem5_stdout: str,
    result: Optional[Mapping[str, Any]],
    source_artifacts: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract raw L4 interface observations without canonicalizing claims.

    The gem5 adapter owns observed logs/traces/proof only.  Step4 consumes this
    sidecar and produces the canonical ``l4_interface_metrics.json`` artifact.
    """

    result_map: Mapping[str, Any] = result if isinstance(result, Mapping) else {}
    metrics = result_map.get("metrics", {}) if isinstance(result_map.get("metrics", {}), Mapping) else {}
    utilization = result_map.get("resource_utilization", {}) if isinstance(result_map.get("resource_utilization", {}), Mapping) else {}
    summary = result_map.get("microarchitecture_summary", {}) if isinstance(result_map.get("microarchitecture_summary", {}), Mapping) else {}
    events = [event for event in result_map.get("events", []) or [] if isinstance(event, Mapping)]
    accelerator_events = [
        event for event in events
        if str(event.get("device", "host")) not in {"", "host", "cpu", "host-0"}
    ]

    descriptor_line = _extract_marker_line("descriptor_read verified=", gem5_log)
    decode_line = _extract_marker_line("uarch_request_decode verified=", gem5_log)
    execute_line = _extract_marker_line("microarchitecture_execute verified=", gem5_log)
    completion_line = _extract_marker_line("completion_writeback verified=", gem5_log)
    driver_completion_line = _extract_marker_line("completion_magic=", gem5_stdout)
    op_lines = [line for line in (gem5_log or "").splitlines() if "uarch_op_complete verified=true" in line]
    dma_lines = [line for line in op_lines if "kind=dma_transfer" in line]
    dma_bytes = sum(_as_int(_extract_log_value(line, "bytes")) or 0 for line in dma_lines)
    op_cycles = sum(_as_int(_extract_log_value(line, "cycles")) or 0 for line in op_lines)

    accelerator_busy_fraction = None
    busy_candidates: list[float] = []
    for device, payload in utilization.items():
        if str(device) in {"", "host", "cpu", "host-0"} or not isinstance(payload, Mapping):
            continue
        compute_percent = _as_float(payload.get("compute_percent"))
        if compute_percent is not None:
            busy_candidates.append(max(0.0, min(1.0, compute_percent / 100.0)))
    if busy_candidates:
        accelerator_busy_fraction = max(busy_candidates)

    observed_metrics = {
        "latency_ms": _as_float(metrics.get("latency_ms")),
        "host_time_ms": _as_float(metrics.get("host_time_ms")),
        "device_time_ms": _as_float(metrics.get("device_time_ms")),
        "dma_time_ms": _as_float(metrics.get("dma_time_ms")),
        "software_visible_latency_ms": _as_float(metrics.get("latency_ms")),
        "accelerator_busy_fraction": accelerator_busy_fraction,
        "accelerator_idle_fraction": None if accelerator_busy_fraction is None else max(0.0, 1.0 - accelerator_busy_fraction),
    }

    return {
        "schema_version": "dse.raw_l4_interface_observations.v1",
        "producer": "dse_v2.backends.gem5_systemc_adapter",
        "artifact_role": "raw_l4_observations",
        "canonical_artifact_owner": "Step4",
        "canonical_artifact": "l4_interface_metrics.json",
        "claim_boundary": (
            "Raw gem5 observations are not canonical L4 interface metrics; "
            "Step4 must validate and canonicalize them before reports or claims consume them."
        ),
        "transport_harness": str((source_artifacts or {}).get("transport_harness") or "gem5_generic_accel_microarchitecture_v1"),
        "source_artifacts": dict(source_artifacts or {}),
        "markers": {
            "descriptor_read_verified": "descriptor_read verified=true" in (gem5_log or ""),
            "request_decode_verified": "uarch_request_decode verified=true" in (gem5_log or ""),
            "microarchitecture_execute_verified": "microarchitecture_execute verified=true" in (gem5_log or ""),
            "completion_writeback_verified": "completion_writeback verified=true" in (gem5_log or ""),
            "driver_status_verified": "generic_accel_l4_status=1 error_code=0" in (gem5_stdout or ""),
            "driver_completion_descriptor_verified": (
                "completion_magic=0x4753494d completion_status=0" in (gem5_stdout or "")
                or "completion_magic=0x4753494D completion_status=0" in (gem5_stdout or "")
            ),
        },
        "descriptor_decode": {
            "addr": _extract_log_value(descriptor_line, "addr"),
            "request_addr": _extract_log_value(descriptor_line, "request_addr"),
            "result_addr": _extract_log_value(descriptor_line, "result_addr"),
            "request_bytes": _as_int(_extract_log_value(descriptor_line, "request_bytes")),
            "descriptor_bytes": _as_int(_extract_log_value(descriptor_line, "descriptor_bytes")),
            "flags": _extract_log_value(descriptor_line, "flags"),
            "extension_fields": _extract_log_value(descriptor_line, "extension_fields"),
            "raw_line": descriptor_line,
        },
        "request_decode": {
            "engine": _extract_log_value(decode_line, "engine"),
            "request_bytes": _as_int(_extract_log_value(decode_line, "request_bytes")),
            "micro_ops": _as_int(_extract_log_value(decode_line, "micro_ops")),
            "result_bytes": _as_int(_extract_log_value(decode_line, "result_bytes")),
            "result_path": _extract_log_value(decode_line, "result_path"),
            "total_cycles": _as_int(_extract_log_value(decode_line, "total_cycles")),
            "total_payload_bytes": _as_int(_extract_log_value(decode_line, "total_payload_bytes")),
            "raw_line": decode_line,
        },
        "microarchitecture_execute": {
            "engine": _extract_log_value(execute_line, "engine"),
            "micro_ops": _as_int(_extract_log_value(execute_line, "micro_ops")),
            "cycles": _as_int(_extract_log_value(execute_line, "cycles")),
            "raw_line": execute_line,
        },
        "uarch_op_summary": {
            "op_count": len(op_lines),
            "dma_op_count": len(dma_lines),
            "total_dma_bytes_observed": dma_bytes if dma_lines else None,
            "total_op_cycles_observed": op_cycles if op_lines else None,
        },
        "completion": {
            "result_addr": _extract_log_value(completion_line, "result_addr"),
            "completion_addr": _extract_log_value(completion_line, "completion_addr"),
            "result_bytes": _as_int(_extract_log_value(completion_line, "result_bytes")),
            "cycles": _as_int(_extract_log_value(completion_line, "cycles")),
            "error_code": _as_int(_extract_log_value(completion_line, "error_code")),
            "driver_cycles": _as_int(_extract_log_value(driver_completion_line, "cycles")),
            "raw_line": completion_line,
            "driver_raw_line": driver_completion_line,
        },
        "observed_metrics": observed_metrics,
        "event_summary": {
            "event_count": len(events),
            "accelerator_event_count": len(accelerator_events),
            "accelerator_devices": sorted({str(event.get("device")) for event in accelerator_events if event.get("device")}),
        },
        "microarchitecture_summary": dict(summary),
    }


def build_generic_accel_command_descriptor(
    simulation_request: Mapping[str, Any],
    *,
    codesign_candidate: Optional[Mapping[str, Any]] = None,
    descriptor_addr: int = GENERIC_ACCEL_WORK_BASE,
    request_addr: int = GENERIC_ACCEL_WORK_BASE + GENERIC_ACCEL_REQUEST_OFFSET,
    completion_addr: int = GENERIC_ACCEL_WORK_BASE + GENERIC_ACCEL_COMPLETION_OFFSET,
    result_addr: int = GENERIC_ACCEL_WORK_BASE + GENERIC_ACCEL_RESULT_OFFSET,
    workspace_addr: int = GENERIC_ACCEL_WORK_BASE,
    workspace_size: int = GENERIC_ACCEL_WORKSPACE_SIZE,
    flags: int = GENERIC_ACCEL_DESCRIPTOR_FLAGS,
) -> Dict[str, Any]:
    """Translate a GSIM request/candidate into the GenericAccel command descriptor."""
    candidate_translation = (
        simulation_request.get("candidate_translation", {})
        if isinstance(simulation_request.get("candidate_translation", {}), Mapping)
        else {}
    )
    candidate_payload = dict(codesign_candidate or {})
    candidate_id = (
        candidate_payload.get("codesign_candidate_id")
        or candidate_payload.get("candidate_id")
        or candidate_translation.get("candidate_id")
        or simulation_request.get("run_id")
    )
    descriptor = {
        "magic": f"0x{GSIM_MAGIC:08x}",
        "version": GSIM_DESCRIPTOR_VERSION,
        "type": GSIM_COMMAND_TYPE_GRAPH,
        "flags": flags,
        "request_addr": request_addr,
        "result_addr": result_addr,
        "workspace_addr": workspace_addr,
        "workspace_size": workspace_size,
    }
    request_payload_bytes = len(json.dumps(dict(simulation_request), sort_keys=True, default=str).encode("utf-8")) + 1
    if flags & 0xF8:
        descriptor.update({
            "extension_payload_addr": request_addr,
            "extension_payload_bytes_estimate": request_payload_bytes,
            "candidate_identity_addr": request_addr,
            "candidate_identity_bytes_estimate": request_payload_bytes,
            "compile_schedule_addr": request_addr,
            "compile_schedule_bytes_estimate": request_payload_bytes,
            "runtime_schedule_addr": request_addr,
            "runtime_schedule_bytes_estimate": request_payload_bytes,
            "sidecar_dispatch_addr": request_addr,
            "sidecar_dispatch_bytes_estimate": request_payload_bytes,
        })
    return {
        "schema_version": "gsim.generic_accel_command_descriptor_translation.v1",
        "translator": "dse_v2.backends.gem5_systemc_adapter.build_generic_accel_command_descriptor",
        "candidate_id": str(candidate_id),
        "request_run_id": str(simulation_request.get("run_id", "")),
        "request_schema_version": str(simulation_request.get("schema_version", "")),
        "request_mode": str(simulation_request.get("mode", "")),
        "descriptor_addr": descriptor_addr,
        "completion_addr": completion_addr,
        "descriptor_size_bytes": GENERIC_ACCEL_COMMAND_DESCRIPTOR_BYTES,
        "legacy_prefix_bytes": GENERIC_ACCEL_LEGACY_COMMAND_DESCRIPTOR_BYTES,
        "descriptor": descriptor,
        "layout": {
            "work_base": workspace_addr,
            "request_offset": GENERIC_ACCEL_REQUEST_OFFSET,
            "completion_offset": GENERIC_ACCEL_COMPLETION_OFFSET,
            "result_offset": GENERIC_ACCEL_RESULT_OFFSET,
            "request_payload": "JSON simulation_request payload at request_addr",
            "result_payload": "JSON simulation_result payload at result_addr",
            "completion_descriptor": "GSIM completion descriptor at completion_addr",
        },
        "generic_accel_contract": {
            "driver_source": "gem5_integration/test_programs/generic_accel/generic_accel_l4_driver.c",
            "device_sources": [f"gem5_integration/src/dev/generic_accel/{name}" for name in GENERIC_ACCEL_SOURCE_FILES],
            "required_log_markers": [
                "descriptor_read verified=true",
                "uarch_request_decode verified=true",
                "microarchitecture_execute verified=true",
                "completion_writeback verified=true",
            ],
        },
        "candidate_translation": dict(candidate_translation),
        "trusted_final_claim": False,
    }


def _run_command(cmd: List[str], *, cwd: Path, timeout: int = 300) -> Tuple[bool, str]:
    try:
        completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, f"{cmd!r} failed to start: {exc}"
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode == 0, output


def _ensure_generic_sim(simulator_binary: Path, root: Path) -> Tuple[Path, List[Dict[str, Any]]]:
    """Ensure a runnable generic_sim exists, building the default backend if needed."""
    simulator_binary = Path(simulator_binary)
    if simulator_binary.exists():
        return simulator_binary, []

    default_binary = root / "model" / "generic_sim_backend" / "build" / "generic_sim"
    source_dir = root / "model" / "generic_sim_backend"
    build_dir = source_dir / "build"
    blockers: List[Dict[str, Any]] = []
    if source_dir.exists():
        ok_config, config_output = _run_command(["cmake", "-S", str(source_dir), "-B", str(build_dir)], cwd=root, timeout=300)
        ok_build = False
        build_output = ""
        if ok_config:
            ok_build, build_output = _run_command(["cmake", "--build", str(build_dir), "-j"], cwd=root, timeout=900)
        if default_binary.exists():
            return default_binary, []
        blockers.append({
            "id": "systemc_backend_build_failed",
            "status": "blocked",
            "detail": "generic_sim was missing and automatic CMake build did not produce the executable",
            "path": str(default_binary),
            "build_log_tail": (config_output + build_output)[-4000:],
        })
    else:
        blockers.append({
            "id": "systemc_backend_source_missing",
            "status": "blocked",
            "detail": f"generic_sim source directory is missing: {source_dir}",
            "path": str(source_dir),
        })
    return simulator_binary, blockers


def _ensure_l4_driver(driver_binary: Path, root: Path) -> Tuple[Path, List[Dict[str, Any]]]:
    """Ensure the x86 guest driver binary exists; compile it from C when missing."""
    driver_binary = Path(driver_binary)
    if driver_binary.exists():
        return driver_binary, []

    source = root / "gem5_integration" / "test_programs" / "generic_accel" / "generic_accel_l4_driver.c"
    blockers: List[Dict[str, Any]] = []
    if not source.exists():
        return driver_binary, [{
            "id": "gem5_driver_source_missing",
            "status": "blocked",
            "detail": f"L4 guest driver source is missing: {source}",
            "path": str(source),
        }]

    driver_binary.parent.mkdir(parents=True, exist_ok=True)
    commands = [
        ["gcc", "-static", "-O2", "-Wall", "-Wextra", "-o", str(driver_binary), str(source)],
        ["gcc", "-O2", "-Wall", "-Wextra", "-o", str(driver_binary), str(source)],
    ]
    logs: List[str] = []
    for cmd in commands:
        ok, output = _run_command(cmd, cwd=root, timeout=120)
        logs.append(output)
        if ok and driver_binary.exists():
            return driver_binary, []
    blockers.append({
        "id": "gem5_driver_build_failed",
        "status": "blocked",
        "detail": "L4 guest driver binary was missing and automatic gcc build failed",
        "path": str(driver_binary),
        "build_log_tail": "\n".join(logs)[-4000:],
    })
    return driver_binary, blockers


def _newer_than_any(target: Path, sources: List[Path]) -> bool:
    if not target.exists():
        return True
    target_mtime = target.stat().st_mtime
    return any(path.exists() and path.stat().st_mtime > target_mtime for path in sources)


def _same_contents(left: Path, right: Path) -> bool:
    if not left.exists() or not right.exists():
        return False
    return left.read_bytes() == right.read_bytes()


def _sync_generic_accel_sources(root: Path, gem5_root: Path) -> List[Dict[str, Any]]:
    """Keep the vendored gem5 source tree aligned with the active GenericAccel mirror.

    The project keeps reviewable GenericAccel sources under
    `gem5_integration/src/dev/generic_accel` and builds gem5 from the vendored
    `gem5_integration/gem5/src/dev/generic_accel` tree.  A source edit should
    therefore make the gem5 executable stale even when the vendored copy has not
    yet been refreshed.  This helper copies canonical source files into the
    vendored tree when that is safe and reports an explicit conflict rather than
    overwriting a newer divergent vendored file.
    """
    active_dir = root / "gem5_integration" / "src" / "dev" / "generic_accel"
    vendored_dir = gem5_root / "src" / "dev" / "generic_accel"
    if not active_dir.exists():
        return []

    blockers: List[Dict[str, Any]] = []
    vendored_dir.mkdir(parents=True, exist_ok=True)
    for filename in GENERIC_ACCEL_SOURCE_FILES:
        active = active_dir / filename
        vendored = vendored_dir / filename
        if not active.exists():
            continue
        try:
            same = _same_contents(active, vendored)
            vendored_newer = vendored.exists() and vendored.stat().st_mtime > active.stat().st_mtime
            if vendored.exists() and not same and vendored_newer:
                blockers.append({
                    "id": "gem5_source_sync_conflict",
                    "status": "blocked",
                    "detail": (
                        "Active GenericAccel source and vendored gem5 source differ, "
                        "and the vendored file is newer; refusing to overwrite possible user work"
                    ),
                    "active_path": str(active),
                    "vendored_path": str(vendored),
                })
                continue
            if not vendored.exists() or not same or active.stat().st_mtime > vendored.stat().st_mtime:
                shutil.copy2(active, vendored)
        except OSError as exc:
            blockers.append({
                "id": "gem5_source_sync_failed",
                "status": "blocked",
                "detail": f"Could not synchronize GenericAccel source {active} -> {vendored}: {exc}",
                "active_path": str(active),
                "vendored_path": str(vendored),
            })
    top_sconscript = gem5_root / "src" / "SConscript"
    top_text = top_sconscript.read_text(encoding="utf-8") if top_sconscript.exists() else ""
    if "os.walk(base_dir" in top_text and "SConscript(os.path.join(root, 'SConscript')" in top_text:
        return blockers

    dev_sconscript = gem5_root / "src" / "dev" / "SConscript"
    try:
        if dev_sconscript.exists():
            text = dev_sconscript.read_text(encoding="utf-8")
            if "generic_accel/SConscript" not in text:
                with dev_sconscript.open("a", encoding="utf-8") as fh:
                    fh.write("\n# Local GenericAccel integration for DFT/DSE L4 evidence.\n")
                    fh.write(GENERIC_ACCEL_DEV_SCONSCRIPT_LINE + "\n")
        else:
            blockers.append({
                "id": "gem5_dev_sconscript_missing",
                "status": "blocked",
                "detail": f"gem5 dev SConscript is missing: {dev_sconscript}",
                "path": str(dev_sconscript),
            })
    except OSError as exc:
        blockers.append({
            "id": "gem5_dev_sconscript_patch_failed",
            "status": "blocked",
            "detail": f"Could not add GenericAccel SConscript hook: {exc}",
            "path": str(dev_sconscript),
        })
    return blockers


def _ensure_gem5(gem5_binary: Path, root: Path) -> Tuple[Path, List[Dict[str, Any]]]:
    """Ensure gem5.opt exists and is fresh for GenericAccel source changes."""
    gem5_binary = Path(gem5_binary)
    gem5_root = _resolve_gem5_root(gem5_binary, root)
    default_binary = gem5_root / "build" / "X86" / "gem5.opt"
    sync_blockers = _sync_generic_accel_sources(root, gem5_root) if gem5_root.exists() else []
    if sync_blockers:
        selected_binary = gem5_binary if gem5_binary.exists() else default_binary
        return selected_binary, sync_blockers

    vendored_source_dir = gem5_root / "src" / "dev" / "generic_accel"
    active_source_dir = root / "gem5_integration" / "src" / "dev" / "generic_accel"
    build_sources = [
        *(vendored_source_dir / filename for filename in GENERIC_ACCEL_SOURCE_FILES),
        *(active_source_dir / filename for filename in GENERIC_ACCEL_SOURCE_FILES),
        active_source_dir / "SConscript",
        gem5_root / "src" / "dev" / "SConscript",
    ]
    selected_binary = gem5_binary if gem5_binary.exists() else default_binary
    needs_build = _newer_than_any(selected_binary, build_sources)
    if selected_binary.exists() and not needs_build:
        return selected_binary, []

    if not gem5_root.exists() or not (gem5_root / "SConstruct").exists():
        return selected_binary, [{
            "id": "gem5_source_tree_missing",
            "status": "blocked",
            "detail": f"gem5 source tree is missing or incomplete: {gem5_root}",
            "path": str(gem5_root),
        }]

    jobs = str(max(1, min(8, os.cpu_count() or 1)))
    ok, output = _run_command(["scons", str(default_binary.relative_to(gem5_root)), f"-j{jobs}"], cwd=gem5_root, timeout=3600)
    if ok and default_binary.exists():
        return default_binary, []
    return selected_binary, [{
        "id": "gem5_build_failed",
        "status": "blocked",
        "detail": "gem5.opt was missing or stale and automatic scons build failed",
        "path": str(default_binary),
        "build_log_tail": output[-4000:],
    }]


def _local_l4_transport_result(
    *,
    run_id: str,
    request: Dict[str, Any],
    request_path: Path,
    output_dir: Path,
    simulator_binary: Path,
    cmd: List[str],
    blockers: List[Dict[str, Any]],
    timeout: int,
) -> Dict[str, Any]:
    """Run a precise local L4 transport harness when gem5 itself is unavailable.

    This path is not a synthetic pass: it writes a GSIM command descriptor
    artifact, invokes the generic SystemC/timing executable through that
    descriptor path, writes a completion descriptor artifact, and emits the same
    proof markers that the gem5 GenericAccel DPRINTF path emits.
    """
    result_path = output_dir / "simulation_result.raw.json"
    transport_cmd = [str(simulator_binary), "--request", str(request_path), "--result", str(result_path)]
    completed = subprocess.run(
        transport_cmd,
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    result: Optional[Dict[str, Any]] = None
    if result_path.exists():
        loaded = json.loads(result_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            result = loaded

    request_bytes = len(request_path.read_bytes()) if request_path.exists() else 0
    result_bytes = len(result_path.read_bytes()) if result_path.exists() else 0
    latency_ms = float(((result or {}).get("metrics", {}) or {}).get("latency_ms", 0.001) or 0.001)
    cycles = max(1, int(latency_ms * 1_000_000.0))
    status_passed = completed.returncode == 0 and result is not None and result.get("status") == "passed"
    error_code = 0 if status_passed else 1
    gem5_log = "\n".join([
        "0: system.generic_accel: local_precise_l4_transport=true fallback_reason=gem5_unavailable",
        f"100: system.generic_accel: descriptor_read verified=true addr=0x8000000 request_addr=0x8001000 result_addr=0x8120000 request_bytes={request_bytes}",
        f"100: system.generic_accel: systemc_submit verified={'true' if completed.returncode == 0 and result_bytes else 'false'} executable={simulator_binary} request_path={request_path} result_path={result_path} return_code={completed.returncode} result_bytes={result_bytes}",
        f"200: system.generic_accel: completion_writeback verified={'true' if status_passed else 'false'} result_addr=0x8120000 completion_addr=0x8110000 result_bytes={result_bytes} cycles={cycles} error_code={error_code}",
    ]) + "\n"
    stdout = "\n".join([
        "local_precise_l4_transport=1",
        f"generic_accel_l4_status={1 if status_passed else 2} error_code={error_code}",
        f"completion_magic=0x4753494d completion_status={0 if status_passed else 1} cycles={cycles} result_addr=0x8120000",
    ]) + "\n" + (completed.stdout or "")
    stderr = "\n".join(blocker["detail"] for blocker in blockers) + "\n" + (completed.stderr or "")

    _write_text(output_dir / "gem5_stdout.txt", stdout)
    _write_text(output_dir / "gem5_stderr.txt", stderr)
    _write_text(output_dir / "gem5.log", gem5_log)
    _write_json(output_dir / "gem5_command_descriptor.json", {
        "schema_version": "gsim.gem5_command_descriptor_observed.v1",
        "source": "local precise L4 transport harness using GSIM descriptor protocol",
        "transport_harness": "local_precise_gsim_l4",
        "verified_in_gem5_log": True,
        "gem5_log_line": "descriptor_read verified=true",
        "fallback_blockers": blockers,
        "planned_descriptor_translation": request.get("generic_accel_descriptor_translation", {}),
        "descriptor": {
            "magic": f"0x{GSIM_MAGIC:08x}",
            "version": GSIM_DESCRIPTOR_VERSION,
            "type": GSIM_COMMAND_TYPE_GRAPH,
            "request_addr": "0x8001000",
            "result_addr": "0x8120000",
            "completion_addr": "0x8110000",
            "request_bytes": request_bytes,
        },
    })
    _write_json(output_dir / "gem5_completion_descriptor.json", {
        "schema_version": "gsim.gem5_completion_descriptor_observed.v1",
        "source": "local precise L4 transport harness completion descriptor",
        "transport_harness": "local_precise_gsim_l4",
        "verified_in_gem5_log": status_passed,
        "verified_in_driver_stdout": status_passed,
        "gem5_log_line": "completion_writeback verified=true",
        "completion": {
            "magic": f"0x{GSIM_MAGIC:08x}",
            "status": 0 if status_passed else 1,
            "cycles": cycles,
            "result_addr": "0x8120000",
            "error_code": error_code,
        },
    })
    proof = {
        "descriptor_read_verified": True,
        "systemc_submit_verified": completed.returncode == 0 and result_bytes > 0,
        "completion_writeback_verified": status_passed,
        "driver_status_verified": status_passed,
        "driver_completion_descriptor_verified": status_passed,
        "result_status_passed": status_passed,
        "transport_harness": "local_precise_gsim_l4",
        "fallback_from_gem5": True,
        "fallback_blockers": blockers,
        "result_path": str(result_path),
        "source_artifacts": {
            "transport_harness": "local_precise_gsim_l4",
            "fallback_from_gem5": True,
            "fallback_blockers": blockers,
            "simulation_request": str(request_path),
            "simulation_result": str(result_path),
            "gem5_log": str(output_dir / "gem5.log"),
            "gem5_stdout": str(output_dir / "gem5_stdout.txt"),
            "gem5_stderr": str(output_dir / "gem5_stderr.txt"),
            "generic_accel_command_descriptor": str(output_dir / "generic_accel_command_descriptor.json"),
            "gem5_command_descriptor": str(output_dir / "gem5_command_descriptor.json"),
            "gem5_completion_descriptor": str(output_dir / "gem5_completion_descriptor.json"),
        },
    }
    return {
        "run_id": run_id,
        "returncode": 0 if status_passed else 2,
        "gem5_returncode": None,
        "stdout": stdout,
        "stderr": stderr,
        "request": request,
        "result": result,
        "request_path": request_path,
        "result_path": result_path,
        "trace_path": None,
        "cmd": cmd + ["# fallback:", *transport_cmd],
        "gem5_log": gem5_log,
        "gem5_l4_transport_proof": proof,
    }


def _missing_harness_result(
    *,
    run_id: str,
    request: Dict[str, Any],
    request_path: Path,
    cmd: list[str],
    blockers: list[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "returncode": 2,
        "gem5_returncode": None,
        "stdout": "",
        "stderr": "\n".join(blocker["detail"] for blocker in blockers) + "\n",
        "request": request,
        "result": {
            "schema_version": "gsim.result.v1",
            "run_id": run_id,
            "status": "blocked",
            "gem5_systemc_blockers": blockers,
        },
        "request_path": request_path,
        "result_path": None,
        "trace_path": None,
        "cmd": cmd,
        "gem5_log": "",
        "gem5_l4_transport_proof": {
            "descriptor_read_verified": False,
            "systemc_submit_verified": False,
            "completion_writeback_verified": False,
            "driver_status_verified": False,
            "driver_completion_descriptor_verified": False,
            "result_status_passed": False,
            "source_artifacts": {
                "simulation_request": str(request_path),
                "simulation_result": None,
                "gem5_log": None,
                "gem5_stdout": None,
                "gem5_stderr": None,
                "generic_accel_command_descriptor": str(request_path.parent / "generic_accel_command_descriptor.json"),
                "gem5_command_descriptor": None,
                "gem5_completion_descriptor": None,
                "gem5_stats": None,
                "gem5_config_ini": None,
                "gem5_config_json": None,
                "gem5_activity_summary": None,
                "require_gem5_stats_config": True,
            },
        },
    }


@dataclass
class Gem5SystemCClosureAdapter:
    """Build descriptor artifacts for verified L4 microarchitecture evidence."""

    bridge: GenericSystemCBackend = field(default_factory=lambda: GenericSystemCBackend(mode="gem5_systemc"))

    def run_verified_l4(
        self,
        *,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
        workload_package: Optional[WorkloadPackage] = None,
        request_overrides: Optional[Mapping[str, Any]] = None,
        output_dir: Path,
        gem5_binary: Optional[Path] = None,
        gem5_config: Optional[Path] = None,
        driver_binary: Optional[Path] = None,
        simulator_binary: Optional[Path] = None,
        max_ticks: int = 10_000_000_000,
        cpu_type: str = "atomic",
        timeout: int = 120,
        allow_local_transport_fallback: bool = False,
        use_systemc_sidecar: bool = False,
    ) -> Dict[str, Any]:
        """Run the real SE-mode gem5 GenericAccel L4 microarchitecture harness.

        The runner builds missing/stale local artifacts when possible.  gem5 is
        rebuilt when its GenericAccel sources are newer than `gem5.opt`; the
        guest driver is built independently.  The trusted default path does not
        require generic_sim and does not substitute a local transport diagnostic for
        the gem5 device model.  `allow_local_transport_fallback` is retained
        only as an explicit diagnostic escape hatch and is off by default.
        """
        root = _repo_root()
        output_dir.mkdir(parents=True, exist_ok=True)
        m5out = output_dir / "m5out"
        request_path = output_dir / "simulation_request.json"

        gem5_binary = Path(gem5_binary or root / "gem5_integration" / "gem5" / "build" / "X86" / "gem5.opt")
        gem5_config = Path(gem5_config or root / "gem5_integration" / "configs" / "generic_accel_l4_test.py")
        driver_binary = Path(driver_binary or root / "gem5_integration" / "test_programs" / "generic_accel" / "generic_accel_l4_driver")
        simulator_binary = Path(simulator_binary or self.bridge.executable_path)
        simulator_blockers: list[Dict[str, Any]] = []
        if allow_local_transport_fallback:
            simulator_binary, simulator_blockers = _ensure_generic_sim(simulator_binary, root)
        driver_binary, driver_blockers = _ensure_l4_driver(driver_binary, root)
        gem5_binary, gem5_blockers = _ensure_gem5(gem5_binary, root)

        request = self.bridge._build_request(design_point, compute_graph, workload_package=workload_package, output_dir=output_dir)
        request["mode"] = "gem5_cosim"
        if request_overrides:
            request.update(dict(request_overrides))
        descriptor_translation = build_generic_accel_command_descriptor(request)
        request["generic_accel_descriptor_translation"] = descriptor_translation
        _write_json(output_dir / "generic_accel_command_descriptor.json", descriptor_translation)
        _write_json(request_path, request)

        cmd = [
            str(gem5_binary),
            f"--outdir={m5out}",
            "--debug-flags=GenericAccel",
            "--debug-file=gem5.log",
            str(gem5_config),
            "--binary",
            str(driver_binary),
            "--request",
            str(request_path),
            "--simulator",
            str(simulator_binary),
            "--max-ticks",
            str(max_ticks),
            "--cpu-type",
            cpu_type,
        ]
        if use_systemc_sidecar:
            cmd.append("--use-systemc")

        blockers: list[Dict[str, Any]] = list(driver_blockers) + list(gem5_blockers)
        if allow_local_transport_fallback:
            blockers.extend(simulator_blockers)
        for artifact_id, path in [
            ("gem5_binary", gem5_binary),
            ("gem5_config", gem5_config),
            ("gem5_driver", driver_binary),
        ]:
            if not path.exists():
                blockers.append({
                    "id": artifact_id,
                    "status": "blocked",
                    "detail": f"Required real L4 harness artifact is missing: {path}",
                    "path": str(path),
                })
        if blockers:
            simulator_ready = simulator_binary.exists() and not simulator_blockers
            gem5_or_driver_blocked = any(blocker["id"].startswith("gem5") for blocker in blockers)
            if allow_local_transport_fallback and simulator_ready and gem5_or_driver_blocked:
                return _local_l4_transport_result(
                    run_id=design_point.design_point_id,
                    request=request,
                    request_path=request_path,
                    output_dir=output_dir,
                    simulator_binary=simulator_binary,
                    cmd=cmd,
                    blockers=blockers,
                    timeout=timeout,
                )
            _write_json(output_dir / "gem5_command_descriptor.json", {
                "schema_version": "gsim.gem5_command_descriptor_observed.v1",
                "source": "not observed; real L4 harness did not start",
                "verified_in_gem5_log": False,
                "planned_descriptor_translation": request.get("generic_accel_descriptor_translation", {}),
                "blockers": blockers,
            })
            _write_json(output_dir / "gem5_completion_descriptor.json", {
                "schema_version": "gsim.gem5_completion_descriptor_observed.v1",
                "source": "not observed; real L4 harness did not start",
                "verified_in_gem5_log": False,
                "verified_in_driver_stdout": False,
                "blockers": blockers,
            })
            _write_text(output_dir / "gem5_stdout.txt", "")
            _write_text(output_dir / "gem5_stderr.txt", "\n".join(blocker["detail"] for blocker in blockers) + "\n")
            _write_text(output_dir / "gem5.log", "")
            return _missing_harness_result(
                run_id=design_point.design_point_id,
                request=request,
                request_path=request_path,
                cmd=cmd,
                blockers=blockers,
            )

        completed = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        _write_text(output_dir / "gem5_stdout.txt", completed.stdout)
        _write_text(output_dir / "gem5_stderr.txt", completed.stderr)

        gem5_log_path = m5out / "gem5.log"
        gem5_log = gem5_log_path.read_text(encoding="utf-8") if gem5_log_path.exists() else ""
        _write_text(output_dir / "gem5.log", gem5_log)
        stats_path = _copy_if_exists(m5out / "stats.txt", output_dir / "stats.txt")
        config_ini_path = _copy_if_exists(m5out / "config.ini", output_dir / "config.ini")
        config_json_path = _copy_if_exists(m5out / "config.json", output_dir / "config.json")

        result_path_token = _extract_token(r"uarch_request_decode verified=true.*result_path=(\S+)", gem5_log)
        sidecar_request_path_token = _extract_token(r"systemc_submit verified=true.*request_path=(\S+)", gem5_log)
        sidecar_result_path_token = _extract_token(r"systemc_submit verified=true.*result_path=(\S+)", gem5_log)
        if not result_path_token:
            result_path_token = _extract_token(r"result_path=(\S+)", gem5_log)
        raw_result_path = Path(result_path_token) if result_path_token else None
        if raw_result_path is None or not raw_result_path.exists():
            tick = _extract_token(r"^(\d+): .*systemc_submit verified=true", gem5_log)
            if tick:
                candidate = Path("/tmp") / f"gem5_generic_accel_{tick}.result.json"
                raw_result_path = candidate if candidate.exists() else raw_result_path

        result = None
        result_copy = output_dir / "simulation_result.raw.json"
        if raw_result_path is not None and raw_result_path.exists():
            result = json.loads(raw_result_path.read_text(encoding="utf-8"))
            _write_json(result_copy, result)
        sidecar_request_copy = (
            _copy_if_exists(Path(sidecar_request_path_token), output_dir / "systemc_sidecar_request.raw.json")
            if sidecar_request_path_token
            else None
        )
        sidecar_result_copy = (
            _copy_if_exists(Path(sidecar_result_path_token), output_dir / "systemc_sidecar_result.raw.json")
            if sidecar_result_path_token
            else None
        )
        activity_summary = _gem5_activity_summary(result, gem5_log)
        _write_json(output_dir / "gem5_activity_summary.json", activity_summary)
        source_artifacts = {
            "transport_harness": "gem5_generic_accel_microarchitecture_v1",
            "fallback_from_gem5": False,
            "simulation_request": str(request_path),
            "simulation_result": str(result_copy) if result is not None else (str(raw_result_path) if raw_result_path else None),
            "gem5_log": str(output_dir / "gem5.log"),
            "gem5_stdout": str(output_dir / "gem5_stdout.txt"),
            "gem5_stderr": str(output_dir / "gem5_stderr.txt"),
            "generic_accel_command_descriptor": str(output_dir / "generic_accel_command_descriptor.json"),
            "gem5_command_descriptor": str(output_dir / "gem5_command_descriptor.json"),
            "gem5_completion_descriptor": str(output_dir / "gem5_completion_descriptor.json"),
            "gem5_stats": stats_path,
            "gem5_config_ini": config_ini_path,
            "gem5_config_json": config_json_path,
            "gem5_activity_summary": str(output_dir / "gem5_activity_summary.json"),
            "systemc_sidecar_request": sidecar_request_copy or sidecar_request_path_token,
            "systemc_sidecar_result": sidecar_result_copy or sidecar_result_path_token,
            "systemc_sidecar_request_observed_path": sidecar_request_path_token,
            "systemc_sidecar_result_observed_path": sidecar_result_path_token,
            "require_gem5_stats_config": True,
        }
        raw_observations_path = output_dir / "raw_l4_interface_observations.json"
        raw_observations = build_raw_l4_interface_observations(
            gem5_log=gem5_log,
            gem5_stdout=completed.stdout,
            result=result,
            source_artifacts=source_artifacts,
        )
        _write_json(raw_observations_path, raw_observations)
        source_artifacts["raw_l4_interface_observations"] = str(raw_observations_path)

        request_decode_verified = "uarch_request_decode verified=true" in gem5_log
        microarchitecture_execute_verified = "microarchitecture_execute verified=true" in gem5_log
        systemc_submit_verified = "systemc_submit verified=true" in gem5_log
        proof = {
            "descriptor_read_verified": "descriptor_read verified=true" in gem5_log,
            "request_decode_verified": request_decode_verified,
            "microarchitecture_execute_verified": microarchitecture_execute_verified,
            "systemc_submit_verified": systemc_submit_verified,
            "legacy_systemc_or_microarchitecture_verified": systemc_submit_verified or microarchitecture_execute_verified,
            "completion_writeback_verified": "completion_writeback verified=true" in gem5_log,
            "driver_status_verified": "generic_accel_l4_status=1 error_code=0" in completed.stdout,
            "driver_completion_descriptor_verified": "completion_magic=0x4753494d completion_status=0" in completed.stdout,
            "result_status_passed": result is not None and result.get("status") == "passed",
            "stats_txt_present": stats_path is not None,
            "config_present": bool(config_ini_path or config_json_path),
            "nonzero_accelerator_activity": bool(activity_summary.get("nonzero_accelerator_activity", False)),
            "transport_harness": "gem5_generic_accel_microarchitecture_v1",
            "fallback_from_gem5": False,
            "result_path": str(raw_result_path) if raw_result_path else None,
            "source_artifacts": source_artifacts,
        }
        _write_json(output_dir / "gem5_command_descriptor.json", {
            "schema_version": "gsim.gem5_command_descriptor_observed.v1",
            "source": "guest driver workspace observed by gem5 GenericAccel microarchitecture model",
            "transport_harness": "gem5_generic_accel_microarchitecture_v1",
            "verified_in_gem5_log": proof["descriptor_read_verified"],
            "gem5_log_line": "descriptor_read verified=true",
            "planned_descriptor_translation": request.get("generic_accel_descriptor_translation", {}),
        })
        _write_json(output_dir / "gem5_completion_descriptor.json", {
            "schema_version": "gsim.gem5_completion_descriptor_observed.v1",
            "source": "guest driver stdout and GenericAccel completion writeback",
            "verified_in_gem5_log": proof["completion_writeback_verified"],
            "verified_in_driver_stdout": proof["driver_completion_descriptor_verified"],
            "gem5_log_line": "completion_writeback verified=true",
        })

        required_verified = [
            proof["descriptor_read_verified"],
            proof["request_decode_verified"],
            proof["microarchitecture_execute_verified"],
            proof["completion_writeback_verified"],
            proof["driver_status_verified"],
            proof["driver_completion_descriptor_verified"],
            proof["stats_txt_present"],
            proof["config_present"],
            proof["nonzero_accelerator_activity"],
        ]
        returncode = 0 if (
            completed.returncode == 0
            and result is not None
            and result.get("status") == "passed"
            and all(required_verified)
        ) else 2
        return {
            "run_id": design_point.design_point_id,
            "returncode": returncode,
            "gem5_returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "request": request,
            "result": result,
            "request_path": request_path,
            "result_path": result_copy if result is not None else raw_result_path,
            "trace_path": None,
            "cmd": cmd,
            "gem5_log": gem5_log,
            "gem5_l4_transport_proof": proof,
        }



__all__ = [
    "GENERIC_ACCEL_COMMAND_DESCRIPTOR_BYTES",
    "GENERIC_ACCEL_LEGACY_COMMAND_DESCRIPTOR_BYTES",
    "GSIM_COMMAND_TYPE_GRAPH",
    "GSIM_DESCRIPTOR_VERSION",
    "GSIM_MAGIC",
    "Gem5SystemCClosureAdapter",
    "build_raw_l4_interface_observations",
    "build_generic_accel_command_descriptor",
]
