#!/usr/bin/env python3
"""Tests for non-stub real hybrid HLS evidence generation."""

from __future__ import annotations

from pathlib import Path

from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
    build_real_hybrid_architecture_specs,
    build_trace_replay_workflow_accounting,
    classify_real_hybrid_vs_gpu,
    materialize_hls_project,
    parse_qe_timer_stdout,
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

        assert m_axi_lines, spec["architecture_id"]
        assert all("depth=" in line for line in m_axi_lines), spec["architecture_id"]
        assert any("depth=64" in line for line in m_axi_lines), spec["architecture_id"]


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
                "vcs_passed": False,
                "implementation_maturity": "real_hls_kernel",
                "workflow_accounting": {"status": "not_available_microkernel_only"},
            }
        )

    result = classify_real_hybrid_vs_gpu(gpu_baseline, rows)

    assert result["preliminary_label"] == "insufficient_evidence"
    assert "full_scf_workflow_accounting_required" in result["blockers"]
    assert result["microkernel_evidence"][0]["rtl_cosim_latency_cycles_max"] == 70
    assert result["final_claim_allowed"] is False

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
