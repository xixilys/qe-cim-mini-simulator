#!/usr/bin/env python3
"""Shared remote VCS command construction for DFT RTL flow scripts."""

from __future__ import annotations

import shlex


def remote_tmp_dir(remote_dir: str) -> str:
    """Return the run-local remote temp directory used to avoid broken host /tmp."""
    return f"{remote_dir.rstrip('/')}/tmp"


def remote_vcs_command(remote_dir: str, rtl_source: str, testbench_source: str) -> str:
    """Build a VCS compile/run command with TMPDIR/TEMP/TMP scoped to remote_dir."""
    tmp_dir = shlex.quote(remote_tmp_dir(remote_dir))
    mdir = "vcs_mdir"
    return (
        "source ~/.bashrc; "
        f"TMPDIR={tmp_dir}; TEMP=\"$TMPDIR\"; TMP=\"$TMPDIR\"; export TMPDIR TEMP TMP; "
        f"mkdir -p \"$TMPDIR\" {mdir}; "
        f"vcs -full64 -sverilog {rtl_source} {testbench_source} -Mdir={mdir} -o simv > vcs_compile.log 2>&1 "
        "&& ./simv > vcs_run.log 2>&1; "
        f"tar czf results_vcs.tgz vcs_compile.log vcs_run.log simv* csrc {mdir} 2>/dev/null "
        "|| tar czf results_vcs.tgz vcs_compile.log vcs_run.log"
    )
