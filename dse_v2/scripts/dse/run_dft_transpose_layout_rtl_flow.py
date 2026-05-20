#!/usr/bin/env python3
"""Run the DFT transpose/layout-conversion RTL smoke flow through local/IC-EDA tools."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_transpose_layout_rtl_flow import (  # noqa: E402
    build_transpose_layout_evidence_rows,
    initialize_transpose_layout_rtl_flow,
    unpack_result_archive,
    write_json,
    write_transpose_layout_major_kernel_matrix,
)


REMOTE_FILES = ("transpose_layout_conversion.v", "tb_transpose_layout_conversion.v", "vivado_synth.tcl", "dc_synth.tcl")


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
            "command": " ".join(command),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "command": " ".join(command),
            "returncode": 124 if isinstance(exc, subprocess.TimeoutExpired) else 127,
            "stdout": getattr(exc, "stdout", "") or "",
            "stderr": str(exc),
        }


def _copy_to_remote(out_dir: Path, *, ssh_target: str, remote_dir: str, timeout_s: int) -> list[dict[str, Any]]:
    remote_dir_quoted = shlex.quote(remote_dir)
    remote_dir_slash_quoted = shlex.quote(remote_dir.rstrip("/") + "/")
    attempts = [
        _run(["ssh", ssh_target, f"rm -rf {remote_dir_quoted} && mkdir -p {remote_dir_quoted}"], timeout_s=timeout_s)
    ]
    attempts.append(
        _run(
            [
                "scp",
                *(str(out_dir / name) for name in REMOTE_FILES),
                f"{ssh_target}:{remote_dir_slash_quoted}",
            ],
            timeout_s=timeout_s,
        )
    )
    return attempts


def _remote_tool_attempts(out_dir: Path, *, ssh_target: str, remote_dir: str, timeout_s: int) -> list[dict[str, Any]]:
    remote_dir_quoted = shlex.quote(remote_dir)
    remote_dir_slash_quoted = shlex.quote(remote_dir.rstrip("/") + "/")
    tool_commands = [
        (
            "vcs",
            (
                "source ~/.bashrc; "
                "vcs -full64 -sverilog transpose_layout_conversion.v tb_transpose_layout_conversion.v -o simv > vcs_compile.log 2>&1 "
                "&& ./simv > vcs_run.log 2>&1; "
                "tar czf results_vcs.tgz vcs_compile.log vcs_run.log simv* csrc 2>/dev/null "
                "|| tar czf results_vcs.tgz vcs_compile.log vcs_run.log"
            ),
            "results_vcs.tgz",
        ),
        (
            "vivado",
            (
                "source ~/.bashrc; "
                "LC_ALL=C LANG=C vivado -mode batch -source vivado_synth.tcl "
                "> vivado_stdout.log 2> vivado_stderr.log; "
                "tar czf results_vivado.tgz vivado*.log vivado_*.rpt transpose_layout_conversion_synth.dcp *_routed.dcp vivado_route_status.rpt vivado_route_timing_summary.rpt .Xil "
                "2>/dev/null || tar czf results_vivado.tgz vivado*.log vivado_*.rpt 2>/dev/null || true"
            ),
            "results_vivado.tgz",
        ),
        (
            "dc_shell",
            (
                "source ~/.bashrc; "
                "dc_shell -f dc_synth.tcl > dc_stdout.log 2> dc_stderr.log; "
                "dc_files=\"$(ls dc_*.rpt dc_stdout.log dc_stderr.log transpose_layout_conversion_dc_mapped.v dc_synth.ddc command.log 2>/dev/null || true)\"; [ -n \"$dc_files\" ] && tar czf results_dc.tgz $dc_files "
                "2>/dev/null || true"
            ),
            "results_dc.tgz",
        ),
    ]
    attempts: list[dict[str, Any]] = []
    for tool, command, archive_name in tool_commands:
        remote = _run(["ssh", ssh_target, f"cd {remote_dir_quoted}; {command}"], timeout_s=timeout_s)
        remote["tool"] = tool
        attempts.append(remote)
        fetch = _run(
            ["scp", f"{ssh_target}:{remote_dir_slash_quoted}{archive_name}", str(out_dir / archive_name)],
            timeout_s=timeout_s,
        )
        fetch["tool"] = f"{tool}_artifact_fetch"
        attempts.append(fetch)
        if (out_dir / archive_name).exists():
            unpack_result_archive(out_dir / archive_name, out_dir)
    return attempts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidate-id", default=None, help="Release candidate id to stamp into source-flow manifest")
    parser.add_argument("--ssh-target", default="ic-eda")
    parser.add_argument("--remote-dir")
    parser.add_argument("--timeout-s", type=int, default=600)
    parser.add_argument("--skip-remote", action="store_true", help="Only write local sources/golden artifacts")
    parser.add_argument("--allow-blocked", action="store_true", help="Return 0 even when the matrix is blocked")
    args = parser.parse_args(argv)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    initialize_transpose_layout_rtl_flow(out_dir, candidate_id=args.candidate_id)
    remote_dir = args.remote_dir or f"/tmp/dft_accelerate_transpose_layout_conversion_{out_dir.name}"
    attempts: list[dict[str, Any]] = []
    if not args.skip_remote:
        attempts.extend(_copy_to_remote(out_dir, ssh_target=args.ssh_target, remote_dir=remote_dir, timeout_s=args.timeout_s))
        if all(item["returncode"] == 0 for item in attempts):
            attempts.extend(
                _remote_tool_attempts(
                    out_dir,
                    ssh_target=args.ssh_target,
                    remote_dir=remote_dir,
                    timeout_s=args.timeout_s,
                )
            )
    evidence = build_transpose_layout_evidence_rows(out_dir, environment=f"ssh {args.ssh_target}")
    matrix = write_transpose_layout_major_kernel_matrix(
        out_dir,
        candidate_id=args.candidate_id or f"transpose_layout_conversion_rtl_fpga_smoke::{out_dir.name}",
        evidence_rows=evidence["evidence_rows"],
    )
    status = {
        "schema_version": "dse.dft_scf.transpose_layout_conversion_rtl_flow_status.v1",
        "status": "passed" if matrix["status"] == "passed" else "blocked",
        "remote_dir": remote_dir,
        "attempts": attempts,
        "evidence_summary": str(out_dir / "transpose_layout_conversion_rtl_evidence_summary.json"),
        "dft_hardware_evidence_matrix": str(out_dir / "dft_hardware_evidence_matrix.json"),
        "claim_boundary": (
            "This flow can prove only the transpose_layout_conversion FPGA microkernel smoke gate. "
            "ASIC DC artifacts from this single-kernel flow are candidate-specific raw evidence only until parser, hard-gate, release-gate, all-kernel, and all-candidate Step5 adjudication pass."
        ),
    }
    write_json(out_dir / "status.json", status)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" or args.allow_blocked else 2


if __name__ == "__main__":
    raise SystemExit(main())
