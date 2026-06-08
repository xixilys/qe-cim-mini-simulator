#!/usr/bin/env python3
"""Tests for non-stub real hybrid HLS evidence generation."""

from __future__ import annotations

from pathlib import Path

from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
    build_real_hybrid_architecture_specs,
    build_evidence_row_static_metadata,
    build_trace_replay_workflow_accounting,
    classify_real_hybrid_vs_gpu,
    materialize_hls_project,
    materialize_vcs_rtl_project,
    merge_vcs_rtl_evidence_into_summary,
    parse_qe_timer_stdout,
    parse_vcs_rtl_run_log,
    render_real_hybrid_hls_report,
    parse_vivado_hls_cosim_report,
    parse_vivado_hls_csynth_report,
)


def test_real_hybrid_specs_are_not_stub_or_proxy():
    specs = build_real_hybrid_architecture_specs()

    assert len(specs) >= 3
    assert {spec["architecture_id"] for spec in specs} >= {
        "hybrid_streaming_reduction_accumulator_v1",
        "hybrid_tiled_complex_axpy_v1",
        "hybrid_fft_twiddle_stream_v1",
        "hybrid_sum_band_density_accumulator_v1",
    }
    for spec in specs:
        text = " ".join(str(value).lower() for value in spec.values())
        assert spec["target_type"] == "gpu_fpga_hybrid"
        assert spec["implementation_maturity"] == "real_hls_kernel"
        assert spec["evidence_level"] == "vivado_hls_csim_csynth_cosim_attempt"
        assert spec["kernel_name"].startswith("qeic_real_")
        assert spec["golden_vector_length"] >= 32
        assert spec["algorithm_description"]
        assert "stub" not in text
        assert "proxy" not in text


def test_real_hybrid_specs_include_qe_routine_equivalent_candidate():
    specs = build_real_hybrid_architecture_specs()
    by_id = {spec["architecture_id"]: spec for spec in specs}

    spec = by_id["hybrid_sum_band_density_accumulator_v1"]

    assert spec["motif_id"] == "sum_band_density_accumulation"
    assert spec["implementation_coverage"] == "qe_routine_equivalent_miniapp"
    assert spec["mapped_qe_timer_names"] == ["sum_band"]
    assert spec["golden_grid_points"] >= 16
    assert spec["golden_band_count"] >= 4



def test_real_hybrid_specs_include_h_psi_local_potential_candidate():
    specs = build_real_hybrid_architecture_specs()
    by_id = {spec["architecture_id"]: spec for spec in specs}

    spec = by_id["hybrid_hpsi_local_potential_v1"]

    assert spec["motif_id"] == "h_psi_local_potential"
    assert spec["implementation_coverage"] == "qe_routine_equivalent_miniapp"
    assert spec["mapped_qe_timer_names"] == ["h_psi"]
    assert spec["golden_grid_points"] >= 32
    assert spec["golden_stencil_radius"] == 1



def test_hpsi_local_potential_testbench_escapes_printf_newlines(tmp_path: Path):
    spec = next(
        item
        for item in build_real_hybrid_architecture_specs()
        if item["architecture_id"] == "hybrid_hpsi_local_potential_v1"
    )

    project = materialize_hls_project(spec, tmp_path, fpga_part="xc7z020clg400-1")

    tb_cpp = Path(project["tb_cpp"]).read_text()
    assert '%.12f\\n", g,' in tb_cpp
    assert '%d\\n", ngrid);' in tb_cpp
    assert ('%.12f' + chr(10) + '", g,') not in tb_cpp
    assert ('%d' + chr(10) + '", ngrid);') not in tb_cpp

def test_hls_project_materialization_for_h_psi_local_potential_uses_neighbor_stencil(tmp_path: Path):
    spec = next(
        item
        for item in build_real_hybrid_architecture_specs()
        if item["architecture_id"] == "hybrid_hpsi_local_potential_v1"
    )

    project = materialize_hls_project(spec, tmp_path, fpga_part="xc7z020clg400-1")

    kernel_cpp = Path(project["kernel_cpp"]).read_text()
    tb_cpp = Path(project["tb_cpp"]).read_text()
    assert "vloc" in kernel_cpp
    assert "psi_re" in kernel_cpp
    assert "out_re" in kernel_cpp
    assert "left =" in kernel_cpp
    assert "right =" in kernel_cpp
    assert "lap_re" in kernel_cpp
    assert "vloc[g] * psi_re[g]" in kernel_cpp
    assert "DSE_REAL_HLS_PASS" in tb_cpp
    assert "expected_re[g]" in tb_cpp

def test_hls_project_materialization_for_sum_band_density_uses_nested_accumulation(tmp_path: Path):
    spec = next(
        item
        for item in build_real_hybrid_architecture_specs()
        if item["architecture_id"] == "hybrid_sum_band_density_accumulator_v1"
    )

    project = materialize_hls_project(spec, tmp_path, fpga_part="xc7z020clg400-1")

    kernel_cpp = Path(project["kernel_cpp"]).read_text()
    tb_cpp = Path(project["tb_cpp"]).read_text()
    assert "psi_re" in kernel_cpp
    assert "rho_out" in kernel_cpp
    assert "for (int g = 0" in kernel_cpp
    assert "for (int b = 0" in kernel_cpp
    assert "weights[b] * (re * re + im * im)" in kernel_cpp
    assert "DSE_REAL_HLS_PASS" in tb_cpp
    assert "expected[g]" in tb_cpp




def test_sum_band_density_kernel_declares_band_grid_index_once(tmp_path: Path):
    spec = next(
        item
        for item in build_real_hybrid_architecture_specs()
        if item["architecture_id"] == "hybrid_sum_band_density_accumulator_v1"
    )

    project = materialize_hls_project(spec, tmp_path, fpga_part="xc7z020clg400-1")

    kernel_cpp = Path(project["kernel_cpp"]).read_text()
    assert kernel_cpp.count("int idx = b * ngrid + g;") == 1

def test_real_hybrid_campaign_default_includes_all_current_architectures():
    import importlib.util

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "run_qe_ic_real_hybrid_hls_campaign.py"
    spec = importlib.util.spec_from_file_location("run_qe_ic_real_hybrid_hls_campaign", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    args = module.parse_args([])

    assert args.max_architectures == len(build_real_hybrid_architecture_specs())
    assert args.max_architectures >= 4

def test_hls_project_materialization_contains_golden_correctness_and_cosim(tmp_path: Path):
    spec = build_real_hybrid_architecture_specs()[0]

    project = materialize_hls_project(spec, tmp_path, fpga_part="xc7z020clg400-1")

    kernel_cpp = Path(project["kernel_cpp"]).read_text()
    tb_cpp = Path(project["tb_cpp"]).read_text()
    tcl = Path(project["run_hls_tcl"]).read_text()
    assert "DSE_REAL_HLS_PASS" in tb_cpp
    assert "fabs" in tb_cpp or "abs" in tb_cpp
    assert "expected" in tb_cpp
    assert "for (int" in kernel_cpp
    assert "* 1." not in kernel_cpp  # reject constant-scale generated stub pattern
    assert spec["kernel_name"] in kernel_cpp
    assert "csim_design" in tcl
    assert "csynth_design" in tcl
    assert "cosim_design" in tcl



def test_hls_project_materialization_declares_axi_depths_for_cosim(tmp_path: Path):
    """Vivado-HLS cosim otherwise defaults m_axi memories to depth=1."""

    for spec in build_real_hybrid_architecture_specs():
        project = materialize_hls_project(spec, tmp_path, fpga_part="xc7z020clg400-1")
        kernel_cpp = Path(project["kernel_cpp"]).read_text()
        m_axi_lines = [line for line in kernel_cpp.splitlines() if "INTERFACE m_axi" in line]

        depths = [int(line.split("depth=", 1)[1].split()[0]) for line in m_axi_lines if "depth=" in line]
        required_depth = min(64, int(spec.get("golden_vector_length") or 64))

        assert m_axi_lines, spec["architecture_id"]
        assert len(depths) == len(m_axi_lines), spec["architecture_id"]
        assert max(depths) >= required_depth, spec["architecture_id"]


def test_parse_real_vivado_2019_loop_detail_report_with_unknown_top_latency():
    report = """
+ Timing (ns):
    * Summary:
    +--------+-------+----------+------------+
    |  Clock | Target| Estimated| Uncertainty|
    +--------+-------+----------+------------+
    |ap_clk  |  10.00|     9.376|        1.25|
    +--------+-------+----------+------------+

+ Latency (clock cycles):
    * Summary:
    +-----+-----+-----+-----+---------+
    |  Latency  |  Interval | Pipeline|
    | min | max | min | max |   Type  |
    +-----+-----+-----+-----+---------+
    |    ?|    ?|    ?|    ?|   none  |
    +-----+-----+-----+-----+---------+

    + Detail:
        * Loop:
        +----------+-----+-----+----------+-----------+-----------+------+----------+
        |          |  Latency  | Iteration|  Initiation Interval  | Trip |          |
        | Loop Name| min | max |  Latency |  achieved |   target  | Count| Pipelined|
        +----------+-----+-----+----------+-----------+-----------+------+----------+
        |- Loop 1  |    ?|    ?|        36|          5|          1|     ?|    yes   |
        +----------+-----+-----+----------+-----------+-----------+------+----------+

== Utilization Estimates
* Summary:
+-----------------+---------+-------+--------+-------+-----+
|       Name      | BRAM_18K| DSP48E|   FF   |  LUT  | URAM|
+-----------------+---------+-------+--------+-------+-----+
|Instance         |       16|     25|    3981|   6374|    -|
|Register         |        6|      -|    1390|     35|    -|
+-----------------+---------+-------+--------+-------+-----+
|Total            |       22|     25|    5371|   6916|    0|
+-----------------+---------+-------+--------+-------+-----+
"""

    parsed = parse_vivado_hls_csynth_report(report, fallback_trip_count=64)

    assert parsed["status"] == "parsed"
    assert parsed["target_clock_ns"] == 10.0
    assert parsed["estimated_clock_ns"] == 9.376
    assert parsed["loop_iteration_latency_cycles"] == 36
    assert parsed["loop_achieved_ii_cycles"] == 5
    assert parsed["latency_cycles_max"] == 351
    assert parsed["interval_cycles_max"] == 320
    assert parsed["resource"] == {
        "bram_18k": 22,
        "dsp48e": 25,
        "ff": 5371,
        "lut": 6916,
        "uram": 0,
    }
    assert parsed["blockers"] == []

def test_parse_vivado_hls_csynth_report_extracts_latency_timing_and_resources():
    report = """
+ Timing (ns):
    * Summary:
    +--------+----------+----------+------------+
    |  Clock |  Target  | Estimated| Uncertainty|
    +--------+----------+----------+------------+
    |default | 10.00    | 7.325    | 1.25       |
    +--------+----------+----------+------------+
+ Latency (clock cycles):
    * Summary:
    +---------+---------+----------+----------+-----+-----+---------+
    |  Latency (cycles) |  Latency (absolute) | Interval | Pipeline |
    |   min   |   max   |    min   |    max   |   min | max | Type |
    +---------+---------+----------+----------+-----+-----+---------+
    |      64 |      68 | 0.640 us | 0.680 us |  65 |  69 | none |
    +---------+---------+----------+----------+-----+-----+---------+
+ Utilization Estimates
* Summary:
+-----+-----+-----+-----+-----+
| BRAM_18K | DSP48E | FF | LUT | URAM |
+-----+-----+-----+-----+-----+
| 4 | 8 | 1024 | 2048 | 0 |
+-----+-----+-----+-----+-----+
"""

    parsed = parse_vivado_hls_csynth_report(report)

    assert parsed["status"] == "parsed"
    assert parsed["latency_cycles_min"] == 64
    assert parsed["latency_cycles_max"] == 68
    assert parsed["interval_cycles_min"] == 65
    assert parsed["interval_cycles_max"] == 69
    assert parsed["estimated_clock_ns"] == 7.325
    assert parsed["target_clock_ns"] == 10.0
    assert parsed["resource"] == {
        "bram_18k": 4,
        "dsp48e": 8,
        "ff": 1024,
        "lut": 2048,
        "uram": 0,
    }
    assert parsed["blockers"] == []


def test_parse_vivado_hls_csynth_report_flags_resource_infeasible_when_total_exceeds_available():
    report = """
+ Timing (ns):
    * Summary:
    +--------+-------+----------+------------+
    |  Clock | Target| Estimated| Uncertainty|
    +--------+-------+----------+------------+
    |ap_clk  |  10.00|     8.750|        1.25|
    +--------+-------+----------+------------+
+ Latency (clock cycles):
    * Summary:
    +-----+-----+-----+-----+---------+
    |  Latency  |  Interval | Pipeline|
    | min | max | min | max |   Type  |
    +-----+-----+-----+-----+---------+
    |   10|   10|   10|   10|   none  |
    +-----+-----+-----+-----+---------+
== Utilization Estimates
* Summary:
+-----------------+---------+-------+--------+-------+-----+
|       Name      | BRAM_18K| DSP48E|   FF   |  LUT  | URAM|
+-----------------+---------+-------+--------+-------+-----+
|Total            |       48|    237|   18387|  23350|    0|
|Available        |      280|    220|  106400|  53200|    0|
+-----------------+---------+-------+--------+-------+-----+
"""

    parsed = parse_vivado_hls_csynth_report(report)

    assert parsed["resource"] == {
        "bram_18k": 48,
        "dsp48e": 237,
        "ff": 18387,
        "lut": 23350,
        "uram": 0,
    }
    assert parsed["resource_available"]["dsp48e"] == 220
    assert parsed["resource_feasible"] is False
    assert "hls_resource_infeasible" in parsed["blockers"]


def test_trace_replay_accounting_preserves_routine_equivalent_coverage(tmp_path: Path):
    run_dir = tmp_path / "runs" / "case-a" / "gpu_only_baseline"
    run_dir.mkdir(parents=True)
    (run_dir / "run_001.stdout.log").write_text(
        """
     sum_band     :      0.01s CPU      0.20s WALL (       5 calls)
     PWSCF        :      0.90s CPU      1.00s WALL
""",
        encoding="utf-8",
    )
    gpu_baseline = {
        "measurements_are_real": True,
        "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}],
    }
    row = {
        "architecture_id": "hybrid_sum_band_density_accumulator_v1",
        "motif_id": "sum_band_density_accumulation",
        "implementation_coverage": "qe_routine_equivalent_miniapp",
        "csynth_parsed": {"estimated_clock_ns": 10.0},
        "cosim_parsed": {"latency_cycles_max": 100},
    }

    accounting = build_trace_replay_workflow_accounting(gpu_baseline, tmp_path / "runs", row)

    assert accounting[0]["implementation_coverage"] == "qe_routine_equivalent_miniapp"
    assert accounting[0]["mapped_timer_names"] == ["sum_band"]



def test_evidence_row_static_metadata_carries_spec_coverage_and_timer_mapping():
    spec = next(
        item
        for item in build_real_hybrid_architecture_specs()
        if item["architecture_id"] == "hybrid_sum_band_density_accumulator_v1"
    )

    metadata = build_evidence_row_static_metadata(spec)

    assert metadata["implementation_coverage"] == "qe_routine_equivalent_miniapp"
    assert metadata["mapped_qe_timer_names"] == ["sum_band"]
    assert metadata["golden_problem_shape"] == {"grid_points": 32, "band_count": 4}



def test_classify_filters_resource_infeasible_architecture_but_uses_other_feasible_attempts():
    gpu_baseline = {
        "measurements_are_real": True,
        "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}],
    }
    common_accounting = {
        "status": "trace_replay_optimistic",
        "case_id": "case-a",
        "scf_control_seconds": 0.1,
        "cpu_retained_seconds": 0.85,
        "host_device_transfer_seconds": 0.00005,
        "synchronization_seconds": 0.00005,
        "launch_overhead_seconds": 0.00005,
        "hybrid_workflow_runtime_seconds": 0.8501,
        "implementation_coverage": "partial_sidecar_motif",
    }
    rows = []
    for arch, feasible in (
        ("hybrid_streaming_reduction_accumulator_v1", True),
        ("hybrid_tiled_complex_axpy_v1", True),
        ("hybrid_fft_twiddle_stream_v1", False),
    ):
        rows.append(
            {
                "architecture_id": arch,
                "status": "executed",
                "csim_passed": True,
                "csynth_parsed": {
                    "status": "parsed" if feasible else "partial",
                    "latency_cycles_max": 64,
                    "estimated_clock_ns": 7.0,
                    "resource": {"bram_18k": 1, "dsp48e": 1 if feasible else 999, "ff": 1, "lut": 1, "uram": 0},
                    "resource_available": {"bram_18k": 280, "dsp48e": 220, "ff": 106400, "lut": 53200, "uram": 0},
                    "resource_feasible": feasible,
                    "blockers": [] if feasible else ["hls_resource_infeasible"],
                },
                "cosim_passed": True,
                "cosim_parsed": {"status": "parsed", "latency_cycles_max": 70, "blockers": []},
                "vcs_passed": False,
                "implementation_maturity": "real_hls_kernel",
                "workflow_accounting": [dict(common_accounting)],
            }
        )

    result = classify_real_hybrid_vs_gpu(gpu_baseline, rows)

    assert result["preliminary_label"] == "fpga_hybrid_weaker"
    assert "resource_feasible_hls_required" not in result["blockers"]
    assert "hls_resource_infeasible_architectures_filtered" in result["blockers"]
    assert {row["architecture_id"] for row in result["architecture_comparisons"]} == {
        "hybrid_streaming_reduction_accumulator_v1",
        "hybrid_tiled_complex_axpy_v1",
    }

def test_classify_real_hybrid_marks_resource_infeasible_rows_as_insufficient():
    gpu_baseline = {
        "measurements_are_real": True,
        "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}],
    }
    rows = []
    for arch in ("hybrid_sum_band_density_accumulator_v1", "hybrid_tiled_complex_axpy_v1"):
        rows.append(
            {
                "architecture_id": arch,
                "status": "executed",
                "csim_passed": True,
                "csynth_parsed": {
                    "status": "partial",
                    "latency_cycles_max": 64,
                    "estimated_clock_ns": 7.0,
                    "resource": {"bram_18k": 1, "dsp48e": 999, "ff": 1, "lut": 1, "uram": 0},
                    "resource_available": {"bram_18k": 280, "dsp48e": 220, "ff": 106400, "lut": 53200, "uram": 0},
                    "resource_feasible": False,
                    "blockers": ["hls_resource_infeasible"],
                },
                "cosim_passed": True,
                "cosim_parsed": {"status": "parsed", "latency_cycles_max": 70, "blockers": []},
                "vcs_passed": False,
                "implementation_maturity": "real_hls_kernel",
                "workflow_accounting": [
                    {
                        "status": "trace_replay_optimistic",
                        "case_id": "case-a",
                        "scf_control_seconds": 0.1,
                        "cpu_retained_seconds": 0.7,
                        "host_device_transfer_seconds": 0.00005,
                        "synchronization_seconds": 0.00005,
                        "launch_overhead_seconds": 0.00005,
                        "hybrid_workflow_runtime_seconds": 0.7001,
                        "implementation_coverage": "full_qe_kernel_equivalent",
                    }
                ],
            }
        )

    result = classify_real_hybrid_vs_gpu(gpu_baseline, rows)

    assert result["preliminary_label"] == "insufficient_evidence"
    assert "resource_feasible_hls_required" in result["blockers"]
    assert result["final_claim_allowed"] is False

def test_parse_qe_timer_stdout_extracts_full_scf_routine_timers():
    stdout = """
     init_run     :      0.05s CPU      0.16s WALL (       1 calls)
     electrons    :      0.15s CPU      0.16s WALL (       1 calls)
     Called by electrons:
     c_bands      :      0.11s CPU      0.12s WALL (       5 calls)
     sum_band     :      0.01s CPU      0.02s WALL (       5 calls)
     mix_rho      :      0.02s CPU      0.02s WALL (       5 calls)
     fftw         :      0.00s CPU      0.01s WALL (     103 calls)
     PWSCF        :      0.21s CPU      0.34s WALL
"""

    parsed = parse_qe_timer_stdout(stdout)

    assert parsed["pwscf_wall_seconds"] == 0.34
    assert parsed["routines"]["sum_band"]["wall_seconds"] == 0.02
    assert parsed["routines"]["sum_band"]["calls"] == 5
    assert parsed["routines"]["fftw"]["wall_seconds"] == 0.01


def test_trace_replay_accounting_uses_qe_timers_and_marks_partial_sidecar(tmp_path: Path):
    run_dir = tmp_path / "runs" / "case-a" / "gpu_only_baseline"
    run_dir.mkdir(parents=True)
    (run_dir / "run_001.stdout.log").write_text(
        """
     sum_band     :      0.01s CPU      0.20s WALL (       5 calls)
     mix_rho      :      0.02s CPU      0.02s WALL (       5 calls)
     PWSCF        :      0.90s CPU      1.00s WALL
""",
        encoding="utf-8",
    )
    gpu_baseline = {
        "measurements_are_real": True,
        "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}],
    }
    row = {
        "architecture_id": "hybrid_streaming_reduction_accumulator_v1",
        "motif_id": "reduction_collective",
        "csynth_parsed": {"estimated_clock_ns": 10.0},
        "cosim_parsed": {"latency_cycles_max": 100},
    }

    accounting = build_trace_replay_workflow_accounting(gpu_baseline, tmp_path / "runs", row)

    assert len(accounting) == 1
    item = accounting[0]
    assert item["status"] == "trace_replay_optimistic"
    assert item["case_id"] == "case-a"
    assert item["mapped_timer_names"] == ["sum_band"]
    assert item["replaceable_seconds_mean"] == 0.20
    assert item["implementation_coverage"] == "partial_sidecar_motif"
    assert item["hybrid_workflow_runtime_seconds"] > 0.8



def test_trace_replay_accounting_adds_vcs_rtl_sensitivity_when_available(tmp_path: Path):
    run_dir = tmp_path / "runs" / "case-a" / "gpu_only_baseline"
    run_dir.mkdir(parents=True)
    (run_dir / "run_001.stdout.log").write_text(
        """
     sum_band     :      0.01s CPU      0.20s WALL (       5 calls)
     PWSCF        :      0.90s CPU      1.00s WALL
""",
        encoding="utf-8",
    )
    gpu_baseline = {
        "measurements_are_real": True,
        "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}],
    }
    row = {
        "architecture_id": "hybrid_sum_band_density_accumulator_v1",
        "motif_id": "sum_band_density_accumulation",
        "csynth_parsed": {"estimated_clock_ns": 10.0},
        "cosim_parsed": {"latency_cycles_max": 100},
        "vcs_passed": True,
        "vcs_parsed": {"status": "parsed", "rtl_status": "Pass", "latency_cycles": 25, "samples": 20, "blockers": []},
    }

    accounting = build_trace_replay_workflow_accounting(gpu_baseline, tmp_path / "runs", row)

    assert {item["latency_source"] for item in accounting} == {"vivado_hls_cosim", "vcs_rtl"}
    hls_item = next(item for item in accounting if item["latency_source"] == "vivado_hls_cosim")
    vcs_item = next(item for item in accounting if item["latency_source"] == "vcs_rtl")
    assert hls_item["status"] == "trace_replay_optimistic"
    assert vcs_item["status"] == "trace_replay_vcs_rtl_sensitivity"
    assert abs(vcs_item["fpga_kernel_seconds_per_transaction"] - 25 * 10.0e-9) < 1.0e-15
    assert vcs_item["hybrid_workflow_runtime_seconds"] < hls_item["hybrid_workflow_runtime_seconds"]
    assert "VCS RTL" in vcs_item["claim_boundary"]


def test_classify_trace_replay_partial_sidecars_reports_current_weaker_not_superior():
    gpu_baseline = {
        "measurements_are_real": True,
        "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}],
    }
    rows = []
    for arch in ("hybrid_streaming_reduction_accumulator_v1", "hybrid_tiled_complex_axpy_v1"):
        rows.append(
            {
                "architecture_id": arch,
                "status": "executed",
                "csim_passed": True,
                "csynth_parsed": {
                    "status": "parsed",
                    "latency_cycles_max": 64,
                    "estimated_clock_ns": 7.0,
                    "resource": {"bram_18k": 1, "dsp48e": 1, "ff": 1, "lut": 1, "uram": 0},
                    "blockers": [],
                },
                "cosim_passed": True,
                "cosim_parsed": {"status": "parsed", "latency_cycles_max": 70, "blockers": []},
                "vcs_passed": False,
                "implementation_maturity": "real_hls_kernel",
                "workflow_accounting": [
                    {
                        "status": "trace_replay_optimistic",
                        "case_id": "case-a",
                        "scf_control_seconds": 0.1,
                        "cpu_retained_seconds": 0.8,
                        "host_device_transfer_seconds": 0.00005,
                        "synchronization_seconds": 0.00005,
                        "launch_overhead_seconds": 0.00005,
                        "hybrid_workflow_runtime_seconds": 0.8001,
                        "implementation_coverage": "partial_sidecar_motif",
                    }
                ],
            }
        )

    result = classify_real_hybrid_vs_gpu(gpu_baseline, rows)

    assert result["preliminary_label"] == "fpga_hybrid_weaker"
    assert result["confidence"] == "medium"
    assert "full_qe_kernel_equivalent_missing" in result["blockers"]
    assert result["best_speedup_vs_gpu_mean"] > 1.0
    assert result["final_claim_allowed"] is False


def test_materialize_vcs_rtl_project_for_hpsi_contains_non_stub_stencil_and_latency_counter(tmp_path: Path):
    spec = next(
        item
        for item in build_real_hybrid_architecture_specs()
        if item["architecture_id"] == "hybrid_hpsi_local_potential_v1"
    )

    project = materialize_vcs_rtl_project(spec, tmp_path)

    rtl = Path(project["rtl_sv"]).read_text()
    tb = Path(project["tb_sv"]).read_text()
    assert "module qeic_real_hpsi_local_potential_rtl" in rtl
    assert "psi_re_left" in rtl
    assert "lap_re" in rtl
    assert "vloc_center" in rtl
    assert "assign out_re" in rtl
    assert "stub" not in rtl.lower()
    assert "DSE_REAL_RTL_PASS" in tb
    assert "DSE_REAL_RTL_LATENCY_CYCLES" in tb
    assert "expected_re" in tb




def test_materialize_vcs_rtl_project_for_axpy_contains_non_stub_complex_update(tmp_path: Path):
    spec = next(
        item
        for item in build_real_hybrid_architecture_specs()
        if item["architecture_id"] == "hybrid_tiled_complex_axpy_v1"
    )

    project = materialize_vcs_rtl_project(spec, tmp_path)

    rtl = Path(project["rtl_sv"]).read_text()
    tb = Path(project["tb_sv"]).read_text()
    assert "module qeic_real_tiled_complex_axpy_rtl" in rtl
    assert "alpha_re" in rtl
    assert "out_re <=" in rtl
    assert "out_im <=" in rtl
    assert "stub" not in rtl.lower()
    assert "DSE_REAL_RTL_PASS" in tb
    assert "DSE_REAL_RTL_LATENCY_CYCLES" in tb
    assert "expected_re" in tb
    assert project["samples"] == spec["golden_vector_length"]


def test_materialize_vcs_rtl_project_for_sum_band_contains_non_stub_density_accumulator(tmp_path: Path):
    spec = next(
        item
        for item in build_real_hybrid_architecture_specs()
        if item["architecture_id"] == "hybrid_sum_band_density_accumulator_v1"
    )

    project = materialize_vcs_rtl_project(spec, tmp_path)

    rtl = Path(project["rtl_sv"]).read_text()
    tb = Path(project["tb_sv"]).read_text()
    assert "module qeic_real_sum_band_density_accumulator_rtl" in rtl
    assert "sample_valid" in rtl
    assert "band_last" in rtl
    assert "rho_acc_next" in rtl
    assert "rho_out <= rho_acc_next" in rtl
    assert "stub" not in rtl.lower()
    assert "DSE_REAL_RTL_PASS" in tb
    assert "DSE_REAL_RTL_LATENCY_CYCLES" in tb
    assert "@(negedge clk);" in tb
    assert "expected_rho" in tb
    assert project["samples"] == spec["golden_grid_points"] * spec["golden_band_count"]

def test_parse_vcs_rtl_run_log_extracts_pass_and_latency():
    log = """
DSE_REAL_RTL_PASS qeic_real_hpsi_local_potential_rtl samples=96
DSE_REAL_RTL_LATENCY_CYCLES 192
"""

    parsed = parse_vcs_rtl_run_log(log)

    assert parsed == {
        "status": "parsed",
        "rtl_status": "Pass",
        "latency_cycles": 192,
        "samples": 96,
        "blockers": [],
    }



def test_merge_vcs_rtl_evidence_into_summary_updates_matching_architecture_row():
    summary = {
        "classification": {"preliminary_label": "fpga_hybrid_weaker", "blockers": []},
        "evidence_rows": [
            {
                "architecture_id": "hybrid_hpsi_local_potential_v1",
                "vcs_attempted": False,
                "vcs_passed": False,
                "csynth_parsed": {},
                "cosim_parsed": {},
            }
        ],
    }
    vcs_result = {
        "architecture_id": "hybrid_hpsi_local_potential_v1",
        "vcs_attempted": True,
        "vcs_passed": True,
        "vcs_parsed": {"status": "parsed", "rtl_status": "Pass", "latency_cycles": 192, "samples": 96, "blockers": []},
        "vcs_command": "ssh ic-eda vcs -full64 ...",
        "vcs_returncode": 0,
        "vcs_run_log_path": "runs/hpsi/vcs_rtl/vcs_run.log",
        "vcs_evidence_json_path": "runs/hpsi/vcs_rtl/real_hybrid_vcs_rtl_evidence.json",
        "vcs_evidence_json_hash": "sha256:" + "1" * 64,
        "claim_boundary": "Standalone handwritten RTL/VCS miniapp evidence for h_psi; not full QE integration.",
    }

    merged = merge_vcs_rtl_evidence_into_summary(summary, vcs_result)

    row = merged["evidence_rows"][0]
    assert row["vcs_attempted"] is True
    assert row["vcs_passed"] is True
    assert row["vcs_parsed"]["latency_cycles"] == 192
    assert row["vcs_command"].startswith("ssh ic-eda")
    assert row["vcs_returncode"] == 0
    assert row["vcs_run_log_path"].endswith("vcs_run.log")
    assert row["vcs_evidence_json_path"].endswith("real_hybrid_vcs_rtl_evidence.json")
    assert row["vcs_evidence_json_hash"].startswith("sha256:")
    assert "not full QE integration" in row["claim_boundary"]

def test_render_real_hybrid_hls_report_includes_vcs_rtl_evidence():
    summary = {
        "classification": {
            "preliminary_label": "fpga_hybrid_weaker",
            "confidence": "medium",
            "final_claim_allowed": False,
            "best_architecture_id": "hybrid_hpsi_local_potential_v1",
            "best_speedup_vs_gpu_mean": 1.01,
            "blockers": ["full_qe_kernel_integration_missing"],
            "claim_boundary": "boundary",
            "architecture_comparisons": [
                {
                    "architecture_id": "hybrid_hpsi_local_potential_v1",
                    "case_id": "case-a",
                    "latency_source": "vcs_rtl",
                    "mapped_timer_names": ["h_psi"],
                    "speedup_vs_gpu_mean": 1.01,
                    "workflow_accounting_status": "trace_replay_vcs_rtl_sensitivity",
                    "implementation_coverage": "qe_routine_equivalent_miniapp",
                }
            ],
        },
        "evidence_rows": [
            {
                "architecture_id": "hybrid_hpsi_local_potential_v1",
                "implementation_coverage": "qe_routine_equivalent_miniapp",
                "mapped_qe_timer_names": ["h_psi"],
                "csim_passed": True,
                "cosim_passed": True,
                "performance_latency_source": "vivado_hls_cosim",
                "performance_latency_cycles_max": 664,
                "vcs_attempted": True,
                "vcs_passed": True,
                "vcs_parsed": {"status": "parsed", "rtl_status": "Pass", "latency_cycles": 192, "samples": 96, "blockers": []},
                "csynth_parsed": {
                    "status": "parsed",
                    "estimated_clock_ns": 8.75,
                    "latency_cycles_max": 664,
                    "resource_feasible": True,
                    "resource": {"bram_18k": 34, "dsp48e": 28, "ff": 6561, "lut": 8762, "uram": 0},
                    "blockers": [],
                },
                "cosim_parsed": {"latency_cycles_max": 664},
            }
        ],
    }

    report = render_real_hybrid_hls_report(summary)

    assert "VCS RTL sim" in report
    assert "DSE_REAL_RTL" not in report
    assert "latency `192` cycles" in report
    assert "`vcs_rtl`" in report
    assert "`trace_replay_vcs_rtl_sensitivity`" in report

def test_parse_vivado_hls_cosim_report_extracts_verilog_pass_latency():
    report = """
Report time       : Mon Jun  8 18:21:12 CST 2026.
Solution          : sol1.
Simulation tool   : xsim.

+----------+----------+-----------------------------------------------+-----------------------------------------------+
|          |          |                    Latency                    |                    Interval                   |
+   RTL    +  Status  +-----------------------------------------------+-----------------------------------------------+
|          |          |      min      |      avg      |      max      |      min      |      avg      |      max      |
+----------+----------+-----------------------------------------------+-----------------------------------------------+
|      VHDL|        NA|             NA|             NA|             NA|             NA|             NA|             NA|
|   Verilog|      Pass|            175|            175|            175|             NA|             NA|             NA|
+----------+----------+-----------------------------------------------+-----------------------------------------------+
"""

    parsed = parse_vivado_hls_cosim_report(report)

    assert parsed == {
        "status": "parsed",
        "blockers": [],
        "rtl": "Verilog",
        "rtl_status": "Pass",
        "latency_cycles_min": 175,
        "latency_cycles_avg": 175,
        "latency_cycles_max": 175,
    }


def test_classify_real_hybrid_requires_full_scf_accounting_after_cosim():
    gpu_baseline = {
        "measurements_are_real": True,
        "baseline_records": [
            {"case_id": "case-a", "runtime_seconds_mean": 1.0},
        ],
    }
    rows = []
    for arch in ("hybrid_streaming_reduction_accumulator_v1", "hybrid_tiled_complex_axpy_v1"):
        rows.append(
            {
                "architecture_id": arch,
                "status": "executed",
                "csim_passed": True,
                "csynth_parsed": {
                    "status": "parsed",
                    "latency_cycles_max": 64,
                    "estimated_clock_ns": 7.0,
                    "resource": {"bram_18k": 1, "dsp48e": 1, "ff": 1, "lut": 1, "uram": 0},
                    "blockers": [],
                },
                "cosim_passed": True,
                "cosim_parsed": {
                    "status": "parsed",
                    "latency_cycles_max": 70,
                    "blockers": [],
                },
                "vcs_passed": arch == "hybrid_streaming_reduction_accumulator_v1",
                "vcs_parsed": {"status": "parsed", "rtl_status": "Pass", "latency_cycles": 50, "samples": 50, "blockers": []}
                if arch == "hybrid_streaming_reduction_accumulator_v1"
                else {},
                "implementation_maturity": "real_hls_kernel",
                "workflow_accounting": {"status": "not_available_microkernel_only"},
            }
        )

    result = classify_real_hybrid_vs_gpu(gpu_baseline, rows)

    assert result["preliminary_label"] == "insufficient_evidence"
    assert "full_scf_workflow_accounting_required" in result["blockers"]
    assert result["microkernel_evidence"][0]["rtl_cosim_latency_cycles_max"] == 70
    assert result["microkernel_evidence"][0]["vcs_rtl_latency_cycles"] == 50
    assert abs(result["microkernel_evidence"][0]["vcs_rtl_microkernel_seconds"] - 50 * 7.0e-9) < 1.0e-15
    assert result["final_claim_allowed"] is False


def test_render_real_hybrid_hls_report_includes_resource_filter_and_latency_source():
    summary = {
        "classification": {
            "preliminary_label": "fpga_hybrid_weaker",
            "confidence": "medium",
            "final_claim_allowed": False,
            "best_architecture_id": "hybrid_sum_band_density_accumulator_v1",
            "best_speedup_vs_gpu_mean": 1.02,
            "resource_infeasible_architecture_ids": ["hybrid_fft_twiddle_stream_v1"],
            "architecture_comparisons": [
                {
                    "architecture_id": "hybrid_sum_band_density_accumulator_v1",
                    "case_id": "case-a",
                    "mapped_timer_names": ["sum_band"],
                    "speedup_vs_gpu_mean": 1.02,
                    "implementation_coverage": "qe_routine_equivalent_miniapp",
                }
            ],
            "blockers": ["full_qe_kernel_integration_missing"],
            "claim_boundary": "boundary text",
        },
        "evidence_rows": [
            {
                "architecture_id": "hybrid_sum_band_density_accumulator_v1",
                "implementation_coverage": "qe_routine_equivalent_miniapp",
                "mapped_qe_timer_names": ["sum_band"],
                "csim_passed": True,
                "cosim_passed": True,
                "performance_latency_source": "vivado_hls_cosim",
                "performance_latency_cycles_max": 5068,
                "csynth_parsed": {
                    "status": "partial",
                    "estimated_clock_ns": 8.75,
                    "resource_feasible": True,
                    "resource": {"bram_18k": 16, "dsp48e": 25, "ff": 4652, "lut": 6465, "uram": 0},
                    "blockers": ["hls_latency_summary_missing"],
                },
                "cosim_parsed": {"latency_cycles_max": 5068},
            }
        ],
    }

    report = render_real_hybrid_hls_report(summary)

    assert "hybrid_sum_band_density_accumulator_v1" in report
    assert "vivado_hls_cosim" in report
    assert "Resource-infeasible architectures filtered" in report
    assert "hybrid_fft_twiddle_stream_v1" in report

def test_classify_real_hybrid_requires_multiple_architectures_and_not_synthesis_only():
    gpu_baseline = {
        "measurements_are_real": True,
        "baseline_records": [
            {"case_id": "case-a", "runtime_seconds_mean": 1.0},
        ],
    }
    synthesis_only = [
        {
            "architecture_id": "hybrid_streaming_reduction_accumulator_v1",
            "status": "executed",
            "csim_passed": True,
            "csynth_parsed": {"status": "parsed", "latency_cycles_max": 64, "estimated_clock_ns": 7.0, "blockers": []},
            "cosim_passed": False,
            "vcs_passed": False,
            "implementation_maturity": "real_hls_kernel",
        }
    ]

    result = classify_real_hybrid_vs_gpu(gpu_baseline, synthesis_only)

    assert result["preliminary_label"] == "insufficient_evidence"
    assert "at_least_two_architecture_families_required" in result["blockers"]
    assert "cosim_or_vcs_required_for_strong_conclusion" in result["blockers"]
    assert result["final_claim_allowed"] is False
