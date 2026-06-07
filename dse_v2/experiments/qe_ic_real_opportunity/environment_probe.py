#!/usr/bin/env python3
"""Local environment probing for QE-IC real opportunity campaigns."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


_REMOTE_EDA_PROBE_CACHE: dict[tuple[str, ...], dict[str, Any]] = {}
QE_PROGRAMS = ("pw.x", "ph.x", "epw.x")


def _which(name: str) -> str | None:
    return shutil.which(name)


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _normalize_qe_probe_output(output: str) -> str:
    normalized_lines: list[str] = []
    for line in output.splitlines():
        normalized_lines.append(
            re.sub(
                r"(starts on\s+).*?(\s+at\s+)\d{1,2}:\d{2}:\d{2}",
                r"\1<date>\2<time>",
                line,
                flags=re.IGNORECASE,
            )
        )
    return "\n".join(normalized_lines)


def normalized_qe_probe_output_hash(output: str, *, returncode: int | None) -> str:
    """Return a stable hash of QE probe output without volatile start timestamps."""

    return _sha256_text(_normalize_qe_probe_output(output) + f"\nreturncode={returncode}")


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _candidate_qe_dirs(config: Mapping[str, Any], repo_root: Path) -> list[Path]:
    dirs: list[Path] = []
    for env_name in ("QE_BIN", "QE_ROOT", "ESPRESSO_ROOT"):
        value = os.environ.get(env_name)
        if not value:
            continue
        root = Path(value).expanduser()
        dirs.append(root)
        dirs.append(root / "bin")
    for key in ("qe_bin", "qe_bin_dir", "qe_root", "espresso_root"):
        value = config.get(key)
        if isinstance(value, str) and value:
            root = Path(value).expanduser()
            dirs.append(root)
            dirs.append(root / "bin")
    for value in _as_mapping(config.get("qe_paths")).values():
        if isinstance(value, str) and value:
            dirs.append(Path(value).expanduser().parent)
    dirs.extend(
        [
            repo_root / "qe" / "bin",
            repo_root / "espresso" / "bin",
            repo_root.parent / "qe" / "bin",
            repo_root.parent / "espresso" / "bin",
            Path("/usr/local/bin"),
            Path("/opt/qe/bin"),
            Path("/opt/espresso/bin"),
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for directory in dirs:
        key = str(directory)
        if key not in seen:
            seen.add(key)
            unique.append(directory)
    return unique


def _explicit_qe_path(config: Mapping[str, Any], program: str) -> Path | None:
    for key in ("qe_executables", "qe_paths"):
        value = _as_mapping(config.get(key)).get(program)
        if isinstance(value, str) and value:
            return Path(value).expanduser()
    return None


def _find_qe_executable(config: Mapping[str, Any], program: str, repo_root: Path) -> Path | None:
    explicit = _explicit_qe_path(config, program)
    if explicit is not None:
        return explicit if explicit.exists() else None
    for directory in _candidate_qe_dirs(config, repo_root):
        candidate = directory / program
        if candidate.exists():
            return candidate
    which = _which(program)
    if which:
        return Path(which)
    return None


def _extract_qe_version(output: str) -> str | None:
    patterns = (
        r"(?:PWSCF|PHonon|EPW|Quantum ESPRESSO)[^\n]*?(?:v\.?|version)\s*([0-9][A-Za-z0-9_.-]*)",
        r"(?:v\.?|version)\s*([0-9][A-Za-z0-9_.-]*)",
    )
    for pattern in patterns:
        match = re.search(pattern, output, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _probe_qe_executable(path: Path) -> dict[str, Any]:
    command = [str(path), "-h"]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "path": str(path),
            "runs": False,
            "version": None,
            "gpu_support": "unknown",
            "probe_command": command,
            "probe_returncode": None,
            "probe_command_output_hash": _sha256_text(str(exc)),
            "probe_error": str(exc),
        }
    output = (result.stdout or "") + (result.stderr or "")
    gpu_support = "detected" if re.search(r"\b(cuda|gpu|openacc|hip|accelerat)", output, re.IGNORECASE) else "not_detected"
    return {
        "path": str(path),
        "runs": result.returncode == 0,
        "version": _extract_qe_version(output),
        "gpu_support": gpu_support,
        "probe_command": command,
        "probe_returncode": result.returncode,
        "probe_command_output_hash": normalized_qe_probe_output_hash(output, returncode=result.returncode),
    }


def discover_qe_executables(
    *,
    config: Mapping[str, Any] | None = None,
    programs: Sequence[str] = QE_PROGRAMS,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Discover QE executables from config, env vars, PATH, and common local paths."""

    config_map = _as_mapping(config)
    root = repo_root or Path.cwd()
    records: dict[str, dict[str, Any]] = {}
    for program in programs:
        path = _find_qe_executable(config_map, str(program), root)
        if path is None:
            records[str(program)] = {
                "path": None,
                "runs": False,
                "version": None,
                "gpu_support": "unknown",
                "probe_command": None,
                "probe_returncode": None,
                "probe_command_output_hash": None,
            }
            continue
        records[str(program)] = _probe_qe_executable(path)
    return {
        "discovery_status": "available" if any(record.get("path") for record in records.values()) else "missing",
        "programs": records,
    }


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


def probe_qe_ic_real_opportunity_environment(
    config: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
    include_qe_discovery: bool = False,
) -> dict[str, Any]:
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

    if include_qe_discovery:
        qe_discovery = discover_qe_executables(config=config, repo_root=repo_root)
        qe = {
            program: record.get("path")
            for program, record in _as_mapping(qe_discovery.get("programs")).items()
        }
    else:
        qe_discovery = None
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

    tools = {
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
    }
    if qe_discovery is not None:
        tools["qe_discovery"] = qe_discovery

    return {
        "environment_status": status,
        "blockers": blockers,
        "gpu": gpu,
        "tools": tools,
    }
