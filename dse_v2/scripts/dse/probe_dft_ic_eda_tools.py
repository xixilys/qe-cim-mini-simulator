#!/usr/bin/env python3
"""Probe IC/EDA tools and emit a DFT hardware-DSE availability artifact.

This script deliberately records *tool reachability only*.  A passed artifact
must not be interpreted as per-kernel simulation, synthesis, implementation,
timing, area, or PPA evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.dft_hardware_evidence import (  # noqa: E402
    OPTIONAL_IC_EDA_TOOL_GROUPS,
    REQUIRED_IC_EDA_TOOLS,
    build_ic_eda_tool_availability_report,
)


TOOL_VERSION_COMMANDS = {
    "dc_shell": "dc_shell -version",
    "vcs": "vcs -ID",
    "vivado": "LC_ALL=C LANG=C vivado -version",
    "vitis_hls": "LC_ALL=C LANG=C vitis_hls -version",
    "vivado_hls": "LC_ALL=C LANG=C vivado_hls -version",
}


def _probe_tools() -> tuple[str, ...]:
    tools = list(REQUIRED_IC_EDA_TOOLS)
    for group_tools in OPTIONAL_IC_EDA_TOOL_GROUPS.values():
        for tool in group_tools:
            if tool not in tools:
                tools.append(tool)
    return tuple(tools)


def _tool_probe_shell(tool: str) -> str:
    """Return the repository-mandated shell probe for one IC/EDA tool."""

    return f"source ~/.bashrc; which {tool} || true; {TOOL_VERSION_COMMANDS[tool]}"


def _run(command: Sequence[str], *, timeout_s: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "returncode": 124 if isinstance(exc, subprocess.TimeoutExpired) else 127,
            "stdout": getattr(exc, "stdout", "") or "",
            "stderr": str(exc),
        }


def _availability_attempt(
    *,
    tool: str,
    command: str,
    result: Mapping[str, Any],
    transport: str,
    environment: str,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "command": command,
        "returncode": result.get("returncode"),
        "stdout": result.get("stdout", "") or "",
        "stderr": result.get("stderr", "") or "",
        "transport": transport,
        "environment": environment,
        "artifact_role": "tool_availability_only_not_kernel_ppa",
        "availability_only_not_kernel_ppa": True,
        "kernel_ppa_evidence": False,
        "hardware_completion_eligible": False,
    }


def _probe_local_ic(timeout_s: int) -> list[dict[str, Any]]:
    """Try the local `ic` launcher first, then let the caller decide fallback."""

    launcher_check = _run(["bash", "-lc", "command -v ic"], timeout_s=min(timeout_s, 10))
    if launcher_check["returncode"] != 0:
        return [
            _availability_attempt(
                tool=tool,
                command=f"ic <<'EOS'\n{_tool_probe_shell(tool)}\nexit\nEOS",
                result={
                    "returncode": 127,
                    "stdout": launcher_check.get("stdout", "") or "",
                    "stderr": (
                        "local ic launcher not found on PATH; falling back to ssh ic-eda.\n"
                        + (launcher_check.get("stderr", "") or "")
                    ).strip(),
                },
                transport="local_ic",
                environment="local ic launcher",
            )
            for tool in _probe_tools()
        ]

    results: list[dict[str, Any]] = []
    for tool in _probe_tools():
        probe_script = _tool_probe_shell(tool)
        command_text = f"ic <<'EOS'\n{probe_script}\nexit\nEOS"
        command = [
            "bash",
            "-lc",
            command_text,
        ]
        result = _run(command, timeout_s=timeout_s)
        results.append(
            _availability_attempt(
                tool=tool,
                command=command_text,
                result=result,
                transport="local_ic",
                environment="local ic launcher",
            )
        )
    return results


def _probe_ssh(target: str, timeout_s: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for tool in _probe_tools():
        remote_command = _tool_probe_shell(tool)
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={min(timeout_s, 30)}",
            target,
            remote_command,
        ]
        result = _run(command, timeout_s=timeout_s)
        results.append(
            _availability_attempt(
                tool=tool,
                command=" ".join(command),
                result=result,
                transport="ssh",
                environment=f"ssh {target}",
            )
        )
    return results


def _availability_passed(attempts: Sequence[Mapping[str, Any]], *, environment: str) -> bool:
    report = build_ic_eda_tool_availability_report(
        attempts,
        required_tools=REQUIRED_IC_EDA_TOOLS,
        optional_tool_groups=OPTIONAL_IC_EDA_TOOL_GROUPS,
        environment=environment,
    )
    return bool(report["all_required_tools_available"])


def _build_cli_report(
    selected_attempts: Sequence[Mapping[str, Any]],
    *,
    environment: str,
    raw_attempts: Sequence[Mapping[str, Any]],
    selected_probe_transport: str,
    probe_order: Sequence[str],
) -> dict[str, Any]:
    report = build_ic_eda_tool_availability_report(
        selected_attempts,
        required_tools=REQUIRED_IC_EDA_TOOLS,
        optional_tool_groups=OPTIONAL_IC_EDA_TOOL_GROUPS,
        environment=environment,
    )
    report["raw_attempts"] = list(raw_attempts)
    report["artifact_role"] = "tool_availability_only_not_kernel_ppa"
    report["availability_only_not_kernel_ppa"] = True
    report["kernel_ppa_evidence"] = False
    report["timing_area_evidence"] = False
    report["implementation_evidence"] = False
    report["hardware_completion_eligible"] = False
    report["deliverable_complete"] = False
    report["selected_probe_transport"] = selected_probe_transport
    report["probe_order"] = list(probe_order)
    report["probe_policy"] = (
        "Try local `ic` first; if it is missing or does not prove all required "
        "tools reachable, fall back to SSH target.  Both paths source ~/.bashrc "
        "and run `which` plus the tool version probe."
    )
    report["required_next_step"] = (
        "Run per-kernel golden/sim/synth/Vivado/DC flows before allowing "
        "FPGA/ASIC acceleration claims.  This availability artifact is not PPA."
    )
    return report


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument("--ssh-target", default="ic-eda", help="SSH target for IC/EDA VM")
    parser.add_argument("--timeout-s", type=int, default=60)
    parser.add_argument(
        "--local-ic-first",
        dest="local_ic_first",
        action="store_true",
        default=True,
        help="Try the local `ic` launcher before SSH (default; kept for backward compatibility).",
    )
    parser.add_argument(
        "--no-local-ic-first",
        dest="local_ic_first",
        action="store_false",
        help="Skip the local `ic` launcher and probe the SSH target directly.",
    )
    args = parser.parse_args()

    attempts: list[dict[str, Any]] = []
    probe_order: list[str] = []
    selected_attempts: list[dict[str, Any]] = []
    selected_transport = "ssh"
    selected_environment = f"ssh {args.ssh_target}"

    if args.local_ic_first:
        probe_order.append("local_ic")
        local_attempts = _probe_local_ic(args.timeout_s)
        attempts.extend(local_attempts)
        if _availability_passed(local_attempts, environment="local ic launcher"):
            selected_attempts = local_attempts
            selected_transport = "local_ic"
            selected_environment = "local ic launcher"

    if not selected_attempts:
        probe_order.append("ssh")
        ssh_attempts = _probe_ssh(args.ssh_target, args.timeout_s)
        attempts.extend(ssh_attempts)
        selected_attempts = ssh_attempts
        selected_transport = "ssh"
        selected_environment = f"ssh {args.ssh_target}"

    report = _build_cli_report(
        selected_attempts,
        environment=selected_environment,
        raw_attempts=attempts,
        selected_probe_transport=selected_transport,
        probe_order=probe_order,
    )

    _write_json(args.out / "ic_eda_tool_availability.json", report)
    _write_json(args.out / "ic_eda_tool_attempts.json", attempts)
    print(
        json.dumps(
            {
                "schema_version": "dse.dft_scf.ic_eda_probe_cli_status.v1",
                "status": report["status"],
                "all_required_tools_available": report["all_required_tools_available"],
                "selected_probe_transport": report["selected_probe_transport"],
                "availability_only_not_kernel_ppa": True,
                "hls_tool_available": report.get("hls_tool_available", False),
                "ic_eda_tool_availability": str(args.out / "ic_eda_tool_availability.json"),
                "ic_eda_tool_attempts": str(args.out / "ic_eda_tool_attempts.json"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
