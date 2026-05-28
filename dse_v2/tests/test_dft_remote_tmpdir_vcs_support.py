#!/usr/bin/env python3
"""Regression tests for DFT RTL remote scratch/TMPDIR handling."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pytest


_PER_KERNEL_RTL_RUNNERS = [
    "dse_v2.scripts.dse.run_dft_complex_gemm_gemv_rtl_flow",
    "dse_v2.scripts.dse.run_dft_dma_hbm_rtl_flow",
    "dse_v2.scripts.dse.run_dft_fft_ifft_rtl_flow",
    "dse_v2.scripts.dse.run_dft_hpsi_local_rtl_flow",
    "dse_v2.scripts.dse.run_dft_kinetic_add_rtl_flow",
    "dse_v2.scripts.dse.run_dft_nonlocal_projector_rtl_flow",
    "dse_v2.scripts.dse.run_dft_reduction_dot_rtl_flow",
    "dse_v2.scripts.dse.run_dft_transpose_layout_rtl_flow",
]


@pytest.mark.parametrize("module_name", _PER_KERNEL_RTL_RUNNERS)
def test_per_kernel_vcs_attempt_keeps_tmp_and_compile_artifacts_under_remote_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    module = importlib.import_module(module_name)
    captured_commands: list[list[str]] = []

    def fake_run(command: list[str], *, timeout_s: int) -> dict[str, Any]:
        captured_commands.append(list(command))
        return {"command": " ".join(command), "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(module, "_run", fake_run)

    remote_dir = "/home/ICer/tmp/dft_candidate_specific_unit"
    module._remote_tool_attempts(
        tmp_path / module_name.rsplit(".", 1)[-1],
        ssh_target="ic-eda-test",
        remote_dir=remote_dir,
        timeout_s=5,
    )

    vcs_remote_commands = [
        command[2]
        for command in captured_commands
        if command[:2] == ["ssh", "ic-eda-test"]
        and len(command) >= 3
        and "vcs" in command[2]
        and "results_vcs.tgz" in command[2]
    ]
    assert len(vcs_remote_commands) == 1

    vcs_command = vcs_remote_commands[0]
    assert "TMPDIR=" in vcs_command
    assert remote_dir in vcs_command
    assert re.search(r"mkdir\s+-p\s+[^;]*\$\{?TMPDIR\}?", vcs_command)
    assert re.search(r"\bvcs\b[^;]*\s-Mdir(?:=|\s+)", vcs_command)
