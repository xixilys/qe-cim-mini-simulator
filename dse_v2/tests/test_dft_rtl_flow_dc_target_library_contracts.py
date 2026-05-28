#!/usr/bin/env python3
"""Regression checks for DFT RTL-flow DC target-library and archive contracts."""

from __future__ import annotations

from pathlib import Path

from dse_v2.reference_workloads.dft_complex_gemm_gemv_rtl_flow import initialize_complex_gemm_gemv_rtl_flow
from dse_v2.reference_workloads.dft_dma_hbm_rtl_flow import initialize_dma_hbm_rtl_flow
from dse_v2.reference_workloads.dft_fft_ifft_rtl_flow import (
    build_fft_ifft_ffft_evidence_rows,
    initialize_fft_ifft_ffft_rtl_flow,
)
from dse_v2.reference_workloads.dft_hpsi_local_rtl_flow import initialize_hpsi_local_rtl_flow
from dse_v2.reference_workloads.dft_kinetic_add_rtl_flow import initialize_kinetic_add_rtl_flow
from dse_v2.reference_workloads.dft_nonlocal_projector_rtl_flow import initialize_nonlocal_projector_rtl_flow
from dse_v2.reference_workloads.dft_reduction_dot_rtl_flow import initialize_reduction_dot_tree_rtl_flow
from dse_v2.reference_workloads.dft_transpose_layout_rtl_flow import initialize_transpose_layout_rtl_flow


_FLOW_INITIALIZERS = [
    initialize_complex_gemm_gemv_rtl_flow,
    initialize_dma_hbm_rtl_flow,
    initialize_fft_ifft_ffft_rtl_flow,
    initialize_hpsi_local_rtl_flow,
    initialize_kinetic_add_rtl_flow,
    initialize_nonlocal_projector_rtl_flow,
    initialize_reduction_dot_tree_rtl_flow,
    initialize_transpose_layout_rtl_flow,
]


_RUNNER_SCRIPTS = [
    "run_dft_complex_gemm_gemv_rtl_flow.py",
    "run_dft_dma_hbm_rtl_flow.py",
    "run_dft_fft_ifft_rtl_flow.py",
    "run_dft_hpsi_local_rtl_flow.py",
    "run_dft_kinetic_add_rtl_flow.py",
    "run_dft_nonlocal_projector_rtl_flow.py",
    "run_dft_reduction_dot_rtl_flow.py",
    "run_dft_transpose_layout_rtl_flow.py",
]


def test_all_dft_rtl_flows_emit_real_dc_target_library_discovery_and_ddc_write(tmp_path: Path) -> None:
    for initializer in _FLOW_INITIALIZERS:
        flow_dir = tmp_path / initializer.__name__
        initializer(flow_dir)
        dc_tcl = (flow_dir / "dc_synth.tcl").read_text(encoding="utf-8")
        assert "set candidate_target_libraries [list" in dc_tcl
        assert "fsa0a_c_generic_core_tt1p8v25c.db" in dc_tcl
        assert "fsa0a_c_generic_core_ff1p98vm40c.db" in dc_tcl
        assert "fsa0a_c_generic_core_ss1p62v125c.db" in dc_tcl
        assert "foreach lib $candidate_target_libraries" in dc_tcl
        assert "file exists $lib" in dc_tcl
        assert "set synthetic_library [list standard.sldb]" in dc_tcl
        assert "set target_library [list $selected_target_library]" in dc_tcl
        assert 'set link_library [concat "*" $target_library $synthetic_library]' in dc_tcl
        assert "set target_library [list your_library.db]" in dc_tcl
        assert "create_clock -name $dft_clock_name -period 10" in dc_tcl
        assert "write -format ddc -hierarchy -output dc_synth.ddc" in dc_tcl


def test_all_dft_rtl_flow_runners_archive_existing_dc_synth_ddc_without_fallback_loss() -> None:
    scripts_dir = Path("dse_v2/scripts/dse")
    for script_name in _RUNNER_SCRIPTS:
        source = (scripts_dir / script_name).read_text(encoding="utf-8")
        assert "dc_synth.ddc" in source
        assert "dc_files=" in source
        assert r'mkdir -p \"$HOME/tmp\"' in source
        assert "export TMPDIR=$HOME/tmp TEMP=$HOME/tmp TMP=$HOME/tmp" in source
        assert "dc_shell -f dc_synth.tcl" in source
        assert "ls dc_*.rpt dc_stdout.log dc_stderr.log" in source
        assert "tar czf results_dc.tgz $dc_files" in source
        assert "tar czf results_dc.tgz dc_stdout.log dc_stderr.log" not in source


def test_dc_summary_allows_real_target_library_logs_that_also_load_gtech(tmp_path: Path) -> None:
    """DC commonly logs gtech.db loading before final mapping to a real library."""

    flow_dir = tmp_path / "fft_dc"
    initialize_fft_ifft_ffft_rtl_flow(flow_dir, candidate_id="cand-a")
    (flow_dir / "dc_stdout.log").write_text(
        "Loading db file 'gtech.db'\n"
        "Loading target library 'fsa0a_c_generic_core_tt1p8v25c'\n"
        "slack (MET) 4.34\n"
        "total cell area: 33469.732933\n",
        encoding="utf-8",
    )
    (flow_dir / "dc_timing.rpt").write_text(
        "Library: fsa0a_c_generic_core_tt1p8v25c\nslack (MET) 4.34\n",
        encoding="utf-8",
    )
    (flow_dir / "dc_area.rpt").write_text("total cell area: 33469.732933\n", encoding="utf-8")
    (flow_dir / "dc_synth.ddc").write_text("ddc\n", encoding="utf-8")

    summary = build_fft_ifft_ffft_evidence_rows(flow_dir)

    assert summary["asic_gate_candidate"] is True
    [dc_row] = summary["asic_attempt_evidence_rows"]
    assert dc_row["status"] == "passed"
    assert dc_row.get("failure_evidence") is None
