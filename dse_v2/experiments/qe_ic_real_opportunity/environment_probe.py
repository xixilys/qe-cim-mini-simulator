#!/usr/bin/env python3
"""Local environment probing for QE-IC real opportunity campaigns."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


_REMOTE_EDA_PROBE_CACHE: dict[tuple[str, ...], dict[str, Any]] = {}
QE_PROGRAMS = ("pw.x", "ph.x", "epw.x")
GPU_LIBRARY_PATTERN = re.compile(
    r"\b(?:lib)?(?:cuda|cudart|cublas|cufft|cusolver|cusparse|nvhpc|openacc|acc|hip|rocblas|rocfft)[A-Za-z0-9_.-]*\.so(?:\.[A-Za-z0-9_.-]+)*",
    re.IGNORECASE,
)


def _which(name: str) -> str | None:
    return shutil.which(name)


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _normalize_qe_probe_output(output: str) -> str:
    normalized_lines: list[str] = []
    for line in output.splitlines():
        normalized_lines.append(
            re.sub(
                r"(starts on\s+).*?(\s+at\s+)\s*\d{1,2}:\s*\d{1,2}:\s*\d{1,2}",
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


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_map(value: Any) -> dict[str, str]:
    return {str(key): str(val) for key, val in _as_mapping(value).items() if isinstance(val, str)}


def _qe_runtime_env(config: Mapping[str, Any]) -> dict[str, str]:
    runtime = dict(_string_map(config.get("qe_runtime_env")))
    for key, value in _string_map(_as_mapping(config.get("qe_runtime")).get("env")).items():
        runtime.setdefault(key, value)
    return runtime


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


def _qe_gpu_build_probe_path(config: Mapping[str, Any], repo_root: Path) -> Path:
    for env_name in ("QE_GPU_BUILD_PROBE", "QE_BUILD_PROBE"):
        value = os.environ.get(env_name)
        if value:
            return Path(value).expanduser()
    value = config.get("qe_gpu_build_probe")
    if isinstance(value, str) and value:
        return Path(value).expanduser()
    return repo_root / "artifacts" / "qe_gpu_build" / "qe_gpu_build_probe.json"


def _load_qe_gpu_build_probe(config: Mapping[str, Any], repo_root: Path) -> dict[str, Any] | None:
    path = _qe_gpu_build_probe_path(config, repo_root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "path": str(path),
            "status": "gpu_qe_build_probe_unreadable",
            "failure_reason": str(exc),
            "program_count": 0,
        }
    programs = _as_list(payload.get("programs"))
    summary = {
        "path": str(path),
        "status": str(payload.get("status") or "unknown"),
        "failure_reason": payload.get("failure_reason"),
        "program_count": len(programs),
        "program_paths": {
            str(row.get("program")): row.get("path")
            for row in programs
            if isinstance(row, Mapping) and isinstance(row.get("program"), str)
        },
        "runtime_validation": payload.get("runtime_validation"),
    }
    source = _as_mapping(payload.get("source"))
    if source:
        summary["source"] = {
            key: source.get(key)
            for key in ("repo", "tag", "commit", "source_dir")
            if source.get(key) is not None
        }
    build = _as_mapping(payload.get("build"))
    if build:
        summary["build"] = {
            key: build.get(key)
            for key in ("build_dir", "configure_log", "build_logs")
            if build.get(key) is not None
        }
    return summary


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


def _extract_gpu_libraries(output: str) -> list[str]:
    libraries: list[str] = []
    seen: set[str] = set()
    for match in GPU_LIBRARY_PATTERN.finditer(output):
        library = match.group(0)
        if library not in seen:
            seen.add(library)
            libraries.append(library)
    return libraries


def _probe_dynamic_gpu_libraries(path: Path) -> dict[str, Any]:
    command = ["ldd", str(path)]
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
            "dynamic_gpu_library_support": "unknown",
            "dynamic_gpu_libraries": [],
            "ldd_command": command,
            "ldd_returncode": None,
            "ldd_output_hash": _sha256_text(str(exc)),
            "ldd_error": str(exc),
        }
    output = (result.stdout or "") + (result.stderr or "")
    libraries = _extract_gpu_libraries(output)
    return {
        "dynamic_gpu_library_support": "detected" if libraries else "not_detected",
        "dynamic_gpu_libraries": libraries,
        "ldd_command": command,
        "ldd_returncode": result.returncode,
        "ldd_output_hash": _sha256_text(output + f"\nreturncode={result.returncode}"),
    }


def _probe_qe_executable(path: Path, *, runtime_env: Mapping[str, str] | None = None) -> dict[str, Any]:
    command = [str(path), "-h"]
    env = {**os.environ, **dict(runtime_env or {})}
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "path": str(path),
            "runs": False,
            "version": None,
            "gpu_support": "unknown",
            "help_gpu_support": "unknown",
            "dynamic_gpu_library_support": "unknown",
            "dynamic_gpu_libraries": [],
            "probe_command": command,
            "probe_returncode": None,
            "probe_command_output_hash": _sha256_text(str(exc)),
            "probe_error": str(exc),
        }
    output = (result.stdout or "") + (result.stderr or "")
    help_gpu_support = "detected" if re.search(r"\b(cuda|gpu|openacc|hip|accelerat)", output, re.IGNORECASE) else "not_detected"
    dynamic_probe = _probe_dynamic_gpu_libraries(path)
    dynamic_gpu_support = str(dynamic_probe.get("dynamic_gpu_library_support") or "unknown")
    gpu_support = "detected" if dynamic_gpu_support == "detected" else "not_detected"
    return {
        "path": str(path),
        "runs": result.returncode == 0,
        "version": _extract_qe_version(output),
        "gpu_support": gpu_support,
        "help_gpu_support": help_gpu_support,
        **dynamic_probe,
        "probe_command": command,
        "probe_returncode": result.returncode,
        "probe_command_output_hash": normalized_qe_probe_output_hash(output, returncode=result.returncode),
        "runtime_env_keys": sorted((runtime_env or {}).keys()),
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
    runtime_env = _qe_runtime_env(config_map)
    records: dict[str, dict[str, Any]] = {}
    for program in programs:
        path = _find_qe_executable(config_map, str(program), root)
        if path is None:
            records[str(program)] = {
                "path": None,
                "runs": False,
                "version": None,
                "gpu_support": "unknown",
                "help_gpu_support": "unknown",
                "dynamic_gpu_library_support": "unknown",
                "dynamic_gpu_libraries": [],
                "probe_command": None,
                "probe_returncode": None,
                "probe_command_output_hash": None,
            }
            continue
        records[str(program)] = _probe_qe_executable(path, runtime_env=runtime_env)
    return {
        "discovery_status": "available" if any(record.get("path") for record in records.values()) else "missing",
        "programs": records,
        "runtime_env_keys": sorted(runtime_env.keys()),
    }


def parse_nvidia_smi_query_output(output: str) -> dict[str, Any]:
    """Parse `nvidia-smi --query-gpu=name,memory.total,driver_version[,cuda_version]` CSV output."""

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
    if len(parts) < 3:
        return {
            "gpu_present": False,
            "gpu_model": None,
            "gpu_memory_total_mib": None,
            "driver_version": None,
            "cuda_version": None,
            "parse_error": "expected at least three comma-separated fields",
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
        "cuda_version": parts[3] if len(parts) > 3 else None,
    }


def parse_nvidia_smi_cuda_version(output: str) -> str | None:
    """Parse CUDA Version from the normal `nvidia-smi` table output."""

    match = re.search(r"CUDA Version:\s*([0-9][0-9.]+)", output)
    return match.group(1) if match else None


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
                    "command -v vivado 2>/dev/null; command -v dc_shell 2>/dev/null; command -v vcs 2>/dev/null; command -v yosys 2>/dev/null",
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
        tool_paths = {
            Path(line.strip()).name: line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        }
        tools = [tool for tool in ("vivado", "dc_shell", "vcs", "yosys") if tool in tool_paths]
        rows.append(
            {
                "alias": alias,
                "probe_status": "available" if tools else "unavailable",
                "available_tools": tools,
                "available_tool_paths": {tool: tool_paths[tool] for tool in tools},
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


def merge_local_and_remote_eda_tools(
    *,
    local_tools: Mapping[str, str | None],
    remote_probe: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge local PATH tools and reachable remote EDA tools into one availability summary."""

    tool_names = ("vivado", "dc_shell", "vcs", "yosys")
    available: dict[str, str] = {
        tool: str(path)
        for tool, path in local_tools.items()
        if tool in tool_names and path
    }
    remote_available_count = 0
    for alias_row in _as_list(remote_probe.get("aliases")):
        if not isinstance(alias_row, Mapping) or alias_row.get("probe_status") != "available":
            continue
        alias = str(alias_row.get("alias") or "remote")
        paths = _as_mapping(alias_row.get("available_tool_paths"))
        remote_available_count += len(paths)
        for tool in tool_names:
            if tool in available:
                continue
            path = paths.get(tool)
            if isinstance(path, str) and path:
                available[tool] = f"ssh://{alias}{path}"
    return {
        "available_tools": available,
        "missing_tools": [tool for tool in tool_names if tool not in available],
        "remote_probe_status": remote_probe.get("remote_probe_status", "not_checked"),
        "remote_ssh_aliases_checked": len(_as_list(remote_probe.get("aliases"))),
        "remote_ssh_alias_count": len(_as_list(remote_probe.get("aliases"))),
        "remote_available_tool_count": remote_available_count,
        "speedup_claim_implication": "none",
    }


def probe_qe_ic_real_opportunity_environment(
    config: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
    include_qe_discovery: bool = False,
) -> dict[str, Any]:
    """Probe local tools without requiring them for software validity."""

    config_map = _as_mapping(config)
    root = repo_root or Path.cwd()
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
                    "--query-gpu=name,memory.total,driver_version",
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
            try:
                version_result = subprocess.run(
                    [nvidia_smi],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except (OSError, subprocess.SubprocessError):
                version_result = None
            if version_result is not None and version_result.returncode == 0:
                gpu["cuda_version"] = parse_nvidia_smi_cuda_version(version_result.stdout)
        else:
            gpu["probe_error"] = result.stderr.strip() if result is not None else "nvidia-smi execution failed"

    if include_qe_discovery:
        qe_discovery = discover_qe_executables(config=config_map, repo_root=root)
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
    qe_gpu_build_probe = _load_qe_gpu_build_probe(config_map, root)
    if qe_gpu_build_probe and qe_gpu_build_probe.get("status") == "gpu_qe_ready":
        for program, path in _as_mapping(qe_gpu_build_probe.get("program_paths")).items():
            if isinstance(path, str) and path:
                qe[program] = path
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
        "vcs": _which("vcs"),
        "yosys": _which("yosys"),
    }
    remote_aliases = _ssh_config_aliases()
    remote_probe = {"remote_probe_status": "no_aliases_discovered", "aliases": [], "speedup_claim_implication": "none"}
    if remote_aliases:
        remote_probe = _cached_remote_eda_probe(remote_aliases)
    eda_summary = merge_local_and_remote_eda_tools(local_tools=eda_tools, remote_probe=remote_probe)
    eda_available = bool(eda_summary["available_tools"])
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
            **eda_summary,
        },
    }
    qe_runtime_env = _qe_runtime_env(config_map)
    if qe_runtime_env:
        tools["qe_runtime_env"] = qe_runtime_env
    if qe_discovery is not None:
        tools["qe_discovery"] = qe_discovery
    if qe_gpu_build_probe is not None:
        tools["qe_gpu_build_probe"] = qe_gpu_build_probe

    return {
        "environment_status": status,
        "blockers": blockers,
        "gpu": gpu,
        "tools": tools,
    }
