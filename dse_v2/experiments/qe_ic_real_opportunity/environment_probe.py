#!/usr/bin/env python3
"""Local environment probing for QE-IC real opportunity campaigns."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


_REMOTE_EDA_PROBE_CACHE: dict[tuple[str, ...], dict[str, Any]] = {}


def _which(name: str) -> str | None:
    return shutil.which(name)


def parse_nvidia_smi_query_output(output: str) -> dict[str, Any]:
    """Parse `nvidia-smi --query-gpu=name,memory.total,driver_version,cuda_version` CSV output."""

    first = next((line.strip() for line in output.splitlines() if line.strip()), "")
    if not first:
        return {
            "gpu_present": False,
            "gpu_model": None,
            "gpu_memory_total_mib": None,
            "driver_version": None,
            "cuda_version": None,
        }
    parts = [part.strip() for part in first.split(",")]
    if len(parts) < 4:
        return {
            "gpu_present": False,
            "gpu_model": None,
            "gpu_memory_total_mib": None,
            "driver_version": None,
            "cuda_version": None,
            "parse_error": "expected four comma-separated fields",
        }
    memory_text = parts[1].replace("MiB", "").replace("Mib", "").strip()
    try:
        memory_mib = int(memory_text)
    except ValueError:
        memory_mib = None
    return {
        "gpu_present": True,
        "gpu_model": parts[0],
        "gpu_memory_total_mib": memory_mib,
        "driver_version": parts[2],
        "cuda_version": parts[3],
    }


def parse_ssh_config_hosts(text: str) -> list[str]:
    """Return plausible remote EDA SSH aliases from ssh_config text."""

    aliases: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("host "):
            continue
        for alias in line.split()[1:]:
            if "*" in alias or "?" in alias or alias == "!":
                continue
            lowered = alias.lower()
            if any(token in lowered for token in ("eda", "vivado", "dc", "synopsys", "fpga")):
                aliases.append(alias)
    return list(dict.fromkeys(aliases))


def _ssh_config_aliases() -> list[str]:
    ssh_config = Path.home() / ".ssh" / "config"
    try:
        return parse_ssh_config_hosts(ssh_config.read_text(encoding="utf-8"))
    except OSError:
        return []


def probe_remote_eda_aliases(aliases: list[str], *, timeout_seconds: int = 5) -> dict[str, Any]:
    """Probe discovered remote EDA aliases with non-claiming tool checks."""

    rows: list[dict[str, Any]] = []
    for alias in aliases:
        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    f"ConnectTimeout={max(1, timeout_seconds)}",
                    alias,
                    "command -v vivado 2>/dev/null; command -v dc_shell 2>/dev/null; command -v yosys 2>/dev/null",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            rows.append(
                {
                    "alias": alias,
                    "probe_status": "failed",
                    "available_tools": [],
                    "error": str(exc),
                }
            )
            continue
        tools = [
            Path(line.strip()).name
            for line in result.stdout.splitlines()
            if line.strip()
        ]
        rows.append(
            {
                "alias": alias,
                "probe_status": "available" if result.returncode == 0 and tools else "unavailable",
                "available_tools": tools,
                "returncode": result.returncode,
            }
        )
    return {
        "remote_probe_status": "probed" if aliases else "no_aliases_discovered",
        "aliases": rows,
        "speedup_claim_implication": "none",
    }


def _cached_remote_eda_probe(aliases: list[str]) -> dict[str, Any]:
    key = tuple(aliases)
    if key not in _REMOTE_EDA_PROBE_CACHE:
        _REMOTE_EDA_PROBE_CACHE[key] = probe_remote_eda_aliases(aliases, timeout_seconds=1)
    return _REMOTE_EDA_PROBE_CACHE[key]


def probe_qe_ic_real_opportunity_environment() -> dict[str, Any]:
    """Probe local tools without requiring them for software validity."""

    nvidia_smi = _which("nvidia-smi")
    gpu = {
        "gpu_present": False,
        "gpu_model": None,
        "gpu_memory_total_mib": None,
        "driver_version": None,
        "cuda_version": None,
    }
    if nvidia_smi:
        try:
            result = subprocess.run(
                [
                    nvidia_smi,
                    "--query-gpu=name,memory.total,driver_version,cuda_version",
                    "--format=csv,noheader,nounits",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0:
            gpu = parse_nvidia_smi_query_output(result.stdout)
        else:
            gpu["probe_error"] = result.stderr.strip() if result is not None else "nvidia-smi execution failed"

    qe = {
        "pw.x": _which("pw.x"),
        "ph.x": _which("ph.x"),
        "epw.x": _which("epw.x"),
    }
    profilers = {
        "nsys": _which("nsys"),
        "ncu": _which("ncu"),
    }
    systemc = {
        "generic_sim": _which("generic_sim"),
        "systemc_runner": _which("systemc-runner"),
    }
    eda_tools = {
        "vivado": _which("vivado"),
        "dc_shell": _which("dc_shell"),
        "yosys": _which("yosys"),
    }
    remote_aliases = _ssh_config_aliases()
    if remote_aliases:
        _cached_remote_eda_probe(remote_aliases)
    eda_available = any(path is not None for path in eda_tools.values())
    qe_available = any(path is not None for path in qe.values())
    profiler_available = any(path is not None for path in profilers.values())
    systemc_available = any(path is not None for path in systemc.values())

    blockers: list[str] = []
    if not qe_available:
        blockers.append("blocked_by_missing_qe")
    if not profiler_available:
        blockers.append("blocked_by_missing_profiler")
    if not systemc_available:
        blockers.append("blocked_by_missing_systemc")
    if not eda_available:
        blockers.append("blocked_by_missing_eda")

    if qe_available and gpu.get("gpu_present") and profiler_available:
        status = "partially_ready" if blockers else "ready"
    else:
        status = "ingest_only_available"

    return {
        "environment_status": status,
        "blockers": blockers,
        "gpu": gpu,
        "tools": {
            "qe": qe,
            "profilers": profilers,
            "systemc": systemc,
            "eda": {
                "available_tools": {key: value for key, value in eda_tools.items() if value},
                "missing_tools": [key for key, value in eda_tools.items() if not value],
                "remote_ssh_aliases_checked": "redacted",
                "remote_ssh_alias_count": "redacted",
                "remote_probe_status": "checked_redacted",
                "remote_available_tool_count": "redacted",
                "speedup_claim_implication": "none",
            },
        },
    }
