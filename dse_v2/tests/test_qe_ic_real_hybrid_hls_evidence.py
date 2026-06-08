#!/usr/bin/env python3
"""Tests for non-stub real hybrid HLS evidence generation."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
    build_real_hybrid_architecture_specs,
    build_evidence_row_static_metadata,
    build_combined_vcs_sidecar_accounting,
    build_integrated_vcs_sidecar_accounting,
    build_real_hybrid_claim_closure,
    build_trace_replay_workflow_accounting,
    classify_real_hybrid_vs_gpu,
    materialize_integrated_vcs_sidecar_project,
    materialize_hls_project,
    materialize_vcs_rtl_project,
    merge_combined_vcs_sidecar_comparisons,
    merge_integrated_vcs_sidecar_comparisons,
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


def test_real_hybrid_campaign_summary_includes_combined_vcs_sidecar_accounting(tmp_path: Path, monkeypatch):
    import importlib.util
    import argparse

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "run_qe_ic_real_hybrid_hls_campaign.py"
    spec = importlib.util.spec_from_file_location("run_qe_ic_real_hybrid_hls_campaign", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "measurements_are_real": True,
                "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}],
            }
        ),
        encoding="utf-8",
    )
    gpu_runs_root = tmp_path / "runs"
    run_dir = gpu_runs_root / "case-a" / "gpu_only_baseline"
    run_dir.mkdir(parents=True)
    (run_dir / "run_001.stdout.log").write_text(
        """
     h_psi        :      0.10s CPU      0.30s WALL (       4 calls)
     sum_band     :      0.01s CPU      0.20s WALL (       5 calls)
     mix_rho      :      0.02s CPU      0.10s WALL (       3 calls)
     h_psi:calbec :      0.01s CPU      0.04s WALL (       3 calls)
     calbec       :      0.01s CPU      0.03s WALL (       3 calls)
     PWSCF        :      0.90s CPU      1.00s WALL
""",
        encoding="utf-8",
    )

    def fake_run_one_architecture(spec_row, *, out_dir, fpga_part, timeout_seconds):
        vcs_latency_by_architecture = {
            "hybrid_hpsi_local_potential_v1": 96,
            "hybrid_sum_band_density_accumulator_v1": 128,
            "hybrid_tiled_complex_axpy_v1": 64,
        }
        architecture_id = spec_row["architecture_id"]
        row = {
            **build_evidence_row_static_metadata(spec_row),
            "architecture_id": architecture_id,
            "kernel_name": spec_row["kernel_name"],
            "target_type": spec_row["target_type"],
            "motif_id": spec_row["motif_id"],
            "implementation_maturity": spec_row["implementation_maturity"],
            "evidence_level": spec_row["evidence_level"],
            "status": "executed",
            "tool": "vivado_hls",
            "fpga_part": fpga_part,
            "csim_passed": True,
            "csynth_parsed": {
                "status": "parsed",
                "latency_cycles_max": 100,
                "estimated_clock_ns": 8.75,
                "resource": {"bram_18k": 1, "dsp48e": 1, "ff": 1, "lut": 1, "uram": 0},
                "resource_available": {"bram_18k": 280, "dsp48e": 220, "ff": 106400, "lut": 53200, "uram": 0},
                "resource_feasible": True,
                "blockers": [],
            },
            "cosim_passed": True,
            "cosim_parsed": {
                "status": "parsed",
                "rtl_status": "Pass",
                "latency_cycles_min": 100,
                "latency_cycles_avg": 100,
                "latency_cycles_max": 100,
                "blockers": [],
            },
            "performance_latency_source": "vivado_hls_cosim",
            "performance_latency_cycles_max": 100,
            "vcs_attempted": architecture_id in vcs_latency_by_architecture,
            "vcs_passed": architecture_id in vcs_latency_by_architecture,
            "vcs_parsed": {
                "status": "parsed",
                "rtl_status": "Pass",
                "latency_cycles": vcs_latency_by_architecture.get(architecture_id),
                "samples": 64,
                "blockers": [],
            }
            if architecture_id in vcs_latency_by_architecture
            else {},
            "blockers": [],
        }
        row_path = out_dir / "runs" / architecture_id / "real_hybrid_hls_evidence.json"
        row_path.parent.mkdir(parents=True, exist_ok=True)
        row["evidence_json_path"] = str(row_path)
        return row

    monkeypatch.setattr(module, "run_one_architecture", fake_run_one_architecture)
    args = argparse.Namespace(
        gpu_baseline=baseline_path,
        out=tmp_path / "out",
        max_architectures=len(build_real_hybrid_architecture_specs()),
        fpga_part="xc7z020clg400-1",
        gpu_runs_root=gpu_runs_root,
        timeout_seconds=1,
    )

    summary = module.run_campaign(args)

    combined = summary["combined_vcs_sidecar_accounting"]
    assert combined
    assert combined[0]["status"] == "trace_replay_combined_vcs_sidecar_sensitivity"
    assert combined[0]["fpga_component_count"] == 3
    combined_rows = [
        row
        for row in summary["classification"]["architecture_comparisons"]
        if row["architecture_id"] == "hybrid_combined_vcs_sidecar_v1"
    ]
    assert combined_rows
    assert combined_rows[0]["latency_source"] == "combined_vcs_rtl"


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


def test_materialize_integrated_vcs_sidecar_project_contains_three_non_stub_motifs(tmp_path: Path):
    specs = build_real_hybrid_architecture_specs()

    project = materialize_integrated_vcs_sidecar_project(specs, tmp_path)

    rtl = Path(project["rtl_sv"]).read_text()
    tb = Path(project["tb_sv"]).read_text()
    assert project["architecture_id"] == "hybrid_integrated_combined_sidecar_v1"
    assert "module qeic_real_integrated_combined_sidecar_rtl" in rtl
    assert "MODE_HPSI" in rtl
    assert "MODE_SUM_BAND" in rtl
    assert "MODE_AXPY" in rtl
    assert "rho_acc_next" in rtl
    assert "alpha_x_re" in rtl
    assert "lap_re" in rtl
    assert "stub" not in rtl.lower()
    assert "DSE_REAL_RTL_PASS qeic_real_integrated_combined_sidecar_rtl" in tb
    assert "DSE_REAL_RTL_COMPONENT hpsi" in tb
    assert "DSE_REAL_RTL_COMPONENT sum_band" in tb
    assert "DSE_REAL_RTL_COMPONENT axpy" in tb
    assert project["samples"] == 96 + 128 + 64
    assert set(project["component_samples"]) == {"hpsi", "sum_band", "axpy"}


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


def test_parse_vcs_rtl_run_log_extracts_integrated_component_breakdown():
    log = """
DSE_REAL_RTL_COMPONENT hpsi samples=96 cycles=96
DSE_REAL_RTL_COMPONENT sum_band samples=128 cycles=128
DSE_REAL_RTL_COMPONENT axpy samples=64 cycles=64
DSE_REAL_RTL_PASS qeic_real_integrated_combined_sidecar_rtl samples=288
DSE_REAL_RTL_LATENCY_CYCLES 288
"""

    parsed = parse_vcs_rtl_run_log(log)

    assert parsed["status"] == "parsed"
    assert parsed["rtl_status"] == "Pass"
    assert parsed["latency_cycles"] == 288
    assert parsed["samples"] == 288
    assert parsed["component_cycles"]["hpsi"]["cycles"] == 96
    assert parsed["component_cycles"]["sum_band"]["samples"] == 128
    assert parsed["component_cycles"]["axpy"]["cycles"] == 64



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


def test_build_real_hybrid_claim_closure_records_hard_gate_statuses():
    gpu_baseline = {
        "measurements_are_real": True,
        "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}],
    }
    rows = []
    for arch, coverage, vcs_latency in (
        ("hybrid_tiled_complex_axpy_v1", "partial_sidecar_motif", 64),
        ("hybrid_sum_band_density_accumulator_v1", "qe_routine_equivalent_miniapp", 128),
        ("hybrid_hpsi_local_potential_v1", "qe_routine_equivalent_miniapp", 96),
    ):
        rows.append(
            {
                "architecture_id": arch,
                "implementation_maturity": "real_hls_kernel",
                "implementation_coverage": coverage,
                "csim_passed": True,
                "cosim_passed": True,
                "vcs_passed": True,
                "vcs_parsed": {"status": "parsed", "rtl_status": "Pass", "latency_cycles": vcs_latency, "samples": vcs_latency, "blockers": []},
                "csynth_parsed": {
                    "status": "parsed",
                    "latency_cycles_max": 70,
                    "estimated_clock_ns": 7.0,
                    "resource": {"bram_18k": 1, "dsp48e": 1, "ff": 1, "lut": 1, "uram": 0},
                    "resource_available": {"bram_18k": 280, "dsp48e": 220, "ff": 106400, "lut": 53200, "uram": 0},
                    "resource_feasible": True,
                    "blockers": [],
                },
                "workflow_accounting": [
                    {
                        "status": "trace_replay_vcs_rtl_sensitivity",
                        "case_id": "case-a",
                        "latency_source": "vcs_rtl",
                        "mapped_timer_names": ["sum_band"],
                        "scf_control_seconds": 0.1,
                        "cpu_retained_seconds": 0.8,
                        "host_device_transfer_seconds": 0.00005,
                        "synchronization_seconds": 0.00005,
                        "launch_overhead_seconds": 0.00005,
                        "hybrid_workflow_runtime_seconds": 0.8001,
                        "implementation_coverage": coverage,
                    }
                ],
            }
        )
    classification = classify_real_hybrid_vs_gpu(gpu_baseline, rows)

    closure = build_real_hybrid_claim_closure(gpu_baseline, rows, classification)

    gates = {gate["gate_id"]: gate for gate in closure["gates"]}
    assert closure["preliminary_label"] == "fpga_hybrid_weaker"
    assert closure["final_claim_allowed"] is False
    assert gates["measured_gpu_baseline"]["status"] == "satisfied"
    assert gates["multiple_real_architectures"]["status"] == "satisfied"
    assert gates["vcs_or_cosim_performance"]["status"] == "satisfied"
    assert gates["vcs_or_cosim_performance"]["evidence"]["vcs_passed_architecture_count"] == 3
    assert gates["full_qe_kernel_integration"]["status"] == "missing"
    assert gates["physical_fpga_board_measurement"]["status"] == "missing"
    assert "full_qe_kernel_integration" in closure["missing_gate_ids"]
    assert closure["claim_verdict"] == "not_superior_current_evidence"


def test_build_combined_vcs_sidecar_accounting_sums_multiple_timer_replacements(tmp_path: Path):
    run_dir = tmp_path / "runs" / "case-a" / "gpu_only_baseline"
    run_dir.mkdir(parents=True)
    (run_dir / "run_001.stdout.log").write_text(
        """
     h_psi        :      0.10s CPU      0.30s WALL (       4 calls)
     sum_band     :      0.01s CPU      0.20s WALL (       5 calls)
     mix_rho      :      0.02s CPU      0.10s WALL (       3 calls)
     PWSCF        :      0.90s CPU      1.00s WALL
""",
        encoding="utf-8",
    )
    gpu_baseline = {
        "measurements_are_real": True,
        "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}],
    }
    rows = [
        {
            "architecture_id": "hybrid_hpsi_local_potential_v1",
            "mapped_qe_timer_names": ["h_psi"],
            "vcs_passed": True,
            "vcs_parsed": {"status": "parsed", "rtl_status": "Pass", "latency_cycles": 96, "samples": 96, "blockers": []},
            "csynth_parsed": {"estimated_clock_ns": 8.75, "resource_feasible": True, "blockers": []},
        },
        {
            "architecture_id": "hybrid_sum_band_density_accumulator_v1",
            "mapped_qe_timer_names": ["sum_band"],
            "vcs_passed": True,
            "vcs_parsed": {"status": "parsed", "rtl_status": "Pass", "latency_cycles": 128, "samples": 128, "blockers": []},
            "csynth_parsed": {"estimated_clock_ns": 8.75, "resource_feasible": True, "blockers": []},
        },
        {
            "architecture_id": "hybrid_tiled_complex_axpy_v1",
            "mapped_qe_timer_names": ["mix_rho"],
            "vcs_passed": True,
            "vcs_parsed": {"status": "parsed", "rtl_status": "Pass", "latency_cycles": 64, "samples": 64, "blockers": []},
            "csynth_parsed": {"estimated_clock_ns": 8.75, "resource_feasible": True, "blockers": []},
        },
    ]

    accounting = build_combined_vcs_sidecar_accounting(gpu_baseline, tmp_path / "runs", rows)

    assert len(accounting) == 1
    item = accounting[0]
    assert item["architecture_id"] == "hybrid_combined_vcs_sidecar_v1"
    assert item["status"] == "trace_replay_combined_vcs_sidecar_sensitivity"
    assert set(item["mapped_timer_names"]) == {"h_psi", "sum_band", "mix_rho"}
    assert item["replaceable_seconds_mean"] == 0.60
    assert item["fpga_component_count"] == 3
    assert item["hybrid_workflow_runtime_seconds"] < 1.0
    assert item["implementation_coverage"] == "combined_partial_sidecar_motif"
    assert "not full-QE integration" in item["claim_boundary"]


def test_merge_combined_vcs_sidecar_comparisons_appends_combined_candidate():
    gpu_baseline = {"baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}]}
    classification = {
        "preliminary_label": "fpga_hybrid_weaker",
        "final_claim_allowed": False,
        "blockers": ["physical_fpga_board_measurement_missing"],
        "architecture_comparisons": [],
    }
    combined = [
        {
            "architecture_id": "hybrid_combined_vcs_sidecar_v1",
            "status": "trace_replay_combined_vcs_sidecar_sensitivity",
            "case_id": "case-a",
            "latency_source": "combined_vcs_rtl",
            "mapped_timer_names": ["h_psi", "sum_band"],
            "hybrid_workflow_runtime_seconds": 0.75,
            "replaceable_seconds_mean": 0.30,
            "implementation_coverage": "combined_partial_sidecar_motif",
            "fpga_component_count": 2,
            "fpga_components": [{"architecture_id": "a"}, {"architecture_id": "b"}],
        }
    ]

    merged = merge_combined_vcs_sidecar_comparisons(gpu_baseline, classification, combined)

    assert merged["best_architecture_id"] == "hybrid_combined_vcs_sidecar_v1"
    assert merged["best_speedup_vs_gpu_mean"] == 1.0 / 0.75
    assert merged["architecture_comparisons"][0]["latency_source"] == "combined_vcs_rtl"
    assert merged["architecture_comparisons"][0]["workflow_accounting_status"] == "trace_replay_combined_vcs_sidecar_sensitivity"
    assert "full_qe_kernel_integration_missing" in merged["blockers"]
    assert merged["final_claim_allowed"] is False


def test_build_integrated_vcs_sidecar_accounting_uses_single_integrated_rtl_result(tmp_path: Path):
    run_dir = tmp_path / "runs" / "case-a" / "gpu_only_baseline"
    run_dir.mkdir(parents=True)
    (run_dir / "run_001.stdout.log").write_text(
        """
     h_psi        :      0.10s CPU      0.30s WALL (       4 calls)
     sum_band     :      0.01s CPU      0.20s WALL (       5 calls)
     mix_rho      :      0.02s CPU      0.10s WALL (       3 calls)
     PWSCF        :      0.90s CPU      1.00s WALL
""",
        encoding="utf-8",
    )
    gpu_baseline = {
        "measurements_are_real": True,
        "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}],
    }
    integrated_result = {
        "architecture_id": "hybrid_integrated_combined_sidecar_v1",
        "vcs_passed": True,
        "vcs_parsed": {
            "status": "parsed",
            "rtl_status": "Pass",
            "latency_cycles": 288,
            "samples": 288,
            "component_cycles": {
                "hpsi": {"samples": 96, "cycles": 96},
                "sum_band": {"samples": 128, "cycles": 128},
                "axpy": {"samples": 64, "cycles": 64},
            },
            "blockers": [],
        },
        "clock_ns": 8.75,
    }

    accounting = build_integrated_vcs_sidecar_accounting(gpu_baseline, tmp_path / "runs", integrated_result)

    assert len(accounting) == 1
    item = accounting[0]
    assert item["architecture_id"] == "hybrid_integrated_combined_sidecar_v1"
    assert item["status"] == "trace_replay_integrated_vcs_sidecar_sensitivity"
    assert item["latency_source"] == "integrated_vcs_rtl"
    assert set(item["mapped_timer_names"]) == {"h_psi", "sum_band", "mix_rho"}
    assert item["integrated_latency_cycles"] == 288
    assert item["fpga_component_count"] == 3
    assert item["hybrid_workflow_runtime_seconds"] < 1.0
    assert item["implementation_coverage"] == "integrated_partial_sidecar_motif"
    assert "single integrated RTL/VCS sidecar" in item["claim_boundary"]


def test_merge_integrated_vcs_sidecar_comparisons_appends_integrated_candidate():
    gpu_baseline = {"baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}]}
    classification = {
        "preliminary_label": "fpga_hybrid_weaker",
        "final_claim_allowed": False,
        "blockers": ["physical_fpga_board_measurement_missing"],
        "architecture_comparisons": [],
    }
    integrated = [
        {
            "architecture_id": "hybrid_integrated_combined_sidecar_v1",
            "status": "trace_replay_integrated_vcs_sidecar_sensitivity",
            "case_id": "case-a",
            "latency_source": "integrated_vcs_rtl",
            "mapped_timer_names": ["h_psi", "sum_band"],
            "hybrid_workflow_runtime_seconds": 0.8,
            "replaceable_seconds_mean": 0.30,
            "implementation_coverage": "integrated_partial_sidecar_motif",
            "fpga_component_count": 2,
            "fpga_components": [{"component_id": "hpsi"}, {"component_id": "sum_band"}],
        }
    ]

    merged = merge_integrated_vcs_sidecar_comparisons(gpu_baseline, classification, integrated)

    assert merged["best_architecture_id"] == "hybrid_integrated_combined_sidecar_v1"
    assert merged["best_speedup_vs_gpu_mean"] == 1.25
    assert merged["architecture_comparisons"][0]["latency_source"] == "integrated_vcs_rtl"
    assert merged["architecture_comparisons"][0]["workflow_accounting_status"] == "trace_replay_integrated_vcs_sidecar_sensitivity"
    assert "full_qe_kernel_integration_missing" in merged["blockers"]
    assert merged["final_claim_allowed"] is False


def test_materialize_integrated_vivado_impl_project_contains_impl_tcl_and_rtl(tmp_path: Path):
    from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
        materialize_integrated_vivado_impl_project,
    )

    project = materialize_integrated_vivado_impl_project(
        build_real_hybrid_architecture_specs(), tmp_path, fpga_part="xc7z020clg400-1"
    )

    assert project["architecture_id"] == "hybrid_integrated_combined_sidecar_v1"
    assert project["fpga_part"] == "xc7z020clg400-1"
    assert project["top_module"] == "qeic_real_integrated_combined_sidecar_impl_top"
    rtl = Path(project["rtl_sv"]).read_text()
    tcl = Path(project["vivado_impl_tcl"]).read_text()
    assert "module qeic_real_integrated_combined_sidecar_rtl" in rtl
    assert "MODE_HPSI" in rtl and "MODE_SUM_BAND" in rtl and "MODE_AXPY" in rtl
    wrapper = Path(project["wrapper_sv"]).read_text()
    assert "module qeic_real_integrated_combined_sidecar_impl_top" in wrapper
    assert "qeic_real_integrated_combined_sidecar_rtl" in wrapper
    assert "checksum_reg" in wrapper
    assert "read_verilog -sv qeic_real_integrated_combined_sidecar_rtl.sv" in tcl
    assert "read_verilog -sv qeic_real_integrated_combined_sidecar_impl_top.sv" in tcl
    assert "synth_design -top qeic_real_integrated_combined_sidecar_impl_top -part xc7z020clg400-1" in tcl
    assert "place_design" in tcl
    assert "route_design" in tcl
    assert "report_utilization -file vivado_utilization.rpt" in tcl
    assert "report_timing_summary -file vivado_timing_summary.rpt" in tcl
    assert "stub" not in rtl.lower()


def test_parse_vivado_impl_utilization_and_timing_reports():
    from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
        parse_vivado_impl_timing_summary_report,
        parse_vivado_impl_utilization_report,
    )

    utilization = """
+----------------------------+------+-------+-----------+-------+
|          Site Type         | Used | Fixed | Available | Util% |
+----------------------------+------+-------+-----------+-------+
| Slice LUTs                 | 1234 |     0 |     53200 |  2.32 |
| Slice Registers            | 2345 |     0 |    106400 |  2.20 |
| Block RAM Tile             |    4 |     0 |       140 |  2.86 |
| DSPs                       |   12 |     0 |       220 |  5.45 |
+----------------------------+------+-------+-----------+-------+
"""
    timing = """
Report Timing Summary
Design Timing Summary
---------------------
WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints
0.872        0.000    0                      128
WHS(ns)      THS(ns)  THS Failing Endpoints  THS Total Endpoints
0.099        0.000    0                      128
WPWS(ns)     TPWS(ns) TPWS Failing Endpoints TPWS Total Endpoints
1.100        0.000    0                      128
"""

    util = parse_vivado_impl_utilization_report(utilization)
    parsed_timing = parse_vivado_impl_timing_summary_report(timing)

    assert util["status"] == "parsed"
    assert util["resource"] == {"lut": 1234, "ff": 2345, "bram_tile": 4, "dsp": 12}
    assert util["resource_available"] == {"lut": 53200, "ff": 106400, "bram_tile": 140, "dsp": 220}
    assert util["resource_feasible"] is True
    assert util["blockers"] == []
    assert parsed_timing["status"] == "parsed"
    assert parsed_timing["wns_ns"] == 0.872
    assert parsed_timing["tns_ns"] == 0.0
    assert parsed_timing["timing_met"] is True
    assert parsed_timing["blockers"] == []


def test_merge_integrated_vivado_impl_evidence_into_summary_and_claim_closure():
    from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
        merge_integrated_vivado_impl_evidence_into_summary,
    )

    summary = {
        "classification": {
            "preliminary_label": "fpga_hybrid_weaker",
            "confidence": "medium",
            "final_claim_allowed": False,
            "best_architecture_id": "hybrid_integrated_combined_sidecar_v1",
            "best_speedup_vs_gpu_mean": 1.55,
            "blockers": ["full_qe_kernel_integration_missing", "physical_fpga_board_measurement_missing"],
            "architecture_comparisons": [],
            "claim_boundary": "old boundary",
        },
        "evidence_rows": [],
    }
    vivado_result = {
        "architecture_id": "hybrid_integrated_combined_sidecar_v1",
        "vivado_impl_attempted": True,
        "vivado_impl_passed": True,
        "vivado_impl_utilization_parsed": {
            "status": "parsed",
            "resource": {"lut": 1234, "ff": 2345, "bram_tile": 4, "dsp": 12},
            "resource_feasible": True,
            "blockers": [],
        },
        "vivado_impl_timing_parsed": {"status": "parsed", "wns_ns": 0.872, "timing_met": True, "blockers": []},
        "vivado_impl_evidence_json_path": "runs/hybrid/vivado_impl/real_hybrid_integrated_vivado_impl_evidence.json",
        "vivado_impl_evidence_json_hash": "sha256:" + "2" * 64,
        "claim_boundary": "Integrated Vivado implementation evidence; still not board measurement or full QE integration.",
    }

    merged = merge_integrated_vivado_impl_evidence_into_summary(summary, vivado_result)

    assert merged["integrated_vivado_impl_result"]["vivado_impl_passed"] is True
    assert merged["classification"]["integrated_vivado_impl_passed"] is True
    assert merged["classification"]["integrated_vivado_impl_timing_met"] is True
    assert "vivado_impl_resource_feasible" in merged["classification"]["satisfied_preliminary_gates"]
    assert "full_qe_kernel_integration_missing" in merged["classification"]["blockers"]
    assert "physical_fpga_board_measurement_missing" in merged["classification"]["blockers"]
    assert merged["classification"]["final_claim_allowed"] is False
    assert "not board measurement" in merged["claim_boundary"]


def test_merge_integrated_vivado_impl_evidence_moves_legacy_non_v1_to_architecture_key():
    from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
        merge_integrated_vivado_impl_evidence_into_summary,
    )

    summary = {
        "integrated_vivado_impl_result": {
            "architecture_id": "hybrid_integrated_pipelined_sidecar_v2",
            "vivado_impl_attempted": True,
            "vivado_impl_passed": True,
            "vivado_impl_utilization_parsed": {"resource": {"lut": 805, "ff": 696, "bram_tile": 0, "dsp": 8}, "resource_feasible": True, "blockers": []},
            "vivado_impl_timing_parsed": {"wns_ns": 0.946, "timing_met": True, "blockers": []},
        },
        "classification": {"preliminary_label": "fpga_hybrid_weaker", "architecture_comparisons": []},
        "evidence_rows": [],
    }
    streaming_result = {
        "architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
        "vivado_impl_attempted": True,
        "vivado_impl_passed": True,
        "vivado_impl_utilization_parsed": {"resource": {"lut": 848, "ff": 736, "bram_tile": 0, "dsp": 8}, "resource_feasible": True, "blockers": []},
        "vivado_impl_timing_parsed": {"wns_ns": 0.962, "timing_met": True, "blockers": []},
        "claim_boundary": "Streaming Vivado implementation evidence; not final hardware claim.",
    }

    merged = merge_integrated_vivado_impl_evidence_into_summary(summary, streaming_result)

    assert "integrated_vivado_impl_result" not in merged
    assert merged["integrated_pipelined_vivado_impl_result"]["architecture_id"] == "hybrid_integrated_pipelined_sidecar_v2"
    assert merged["integrated_streaming_vivado_impl_result"]["architecture_id"] == "hybrid_integrated_streaming_pipeline_sidecar_v3"
    assert set(merged["classification"]["integrated_vivado_impl_architecture_ids"]) == {
        "hybrid_integrated_pipelined_sidecar_v2",
        "hybrid_integrated_streaming_pipeline_sidecar_v3",
    }


def test_real_hybrid_vivado_impl_runner_merges_result_into_summary(tmp_path: Path, monkeypatch):
    import argparse
    import importlib.util

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "run_qe_ic_real_hybrid_vivado_impl.py"
    spec = importlib.util.spec_from_file_location("run_qe_ic_real_hybrid_vivado_impl", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"measurements_are_real": True, "baseline_records": []}), encoding="utf-8")
    summary_path = out_dir / "real_hybrid_hls_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "gpu_baseline_path": str(baseline_path),
                "classification": {
                    "preliminary_label": "fpga_hybrid_weaker",
                    "confidence": "medium",
                    "final_claim_allowed": False,
                    "blockers": ["full_qe_kernel_integration_missing", "physical_fpga_board_measurement_missing"],
                    "architecture_comparisons": [],
                    "claim_boundary": "old boundary",
                },
                "evidence_rows": [],
            }
        ),
        encoding="utf-8",
    )

    def fake_run(*, out_dir, fpga_part, clock_period_ns, timeout_seconds, architecture_id="hybrid_integrated_combined_sidecar_v1"):
        return {
            "architecture_id": "hybrid_integrated_combined_sidecar_v1",
            "vivado_impl_attempted": True,
            "vivado_impl_passed": True,
            "implemented_clock_ns": clock_period_ns,
            "implemented_clock_source": "vivado_post_route_timing_met",
            "vivado_impl_utilization_parsed": {
                "status": "parsed",
                "resource": {"lut": 1234, "ff": 2345, "bram_tile": 4, "dsp": 12},
                "resource_feasible": True,
                "blockers": [],
            },
            "vivado_impl_timing_parsed": {"status": "parsed", "wns_ns": 0.872, "timing_met": True, "blockers": []},
            "vivado_impl_evidence_json_path": str(out_dir / "runs" / "hybrid_integrated_combined_sidecar_v1" / "vivado_impl" / "real_hybrid_integrated_vivado_impl_evidence.json"),
            "vivado_impl_evidence_json_hash": "sha256:" + "3" * 64,
            "blockers": [],
            "claim_boundary": "Integrated Vivado implementation evidence; not board measurement or full QE integration.",
        }

    monkeypatch.setattr(module, "run_integrated_vivado_impl", fake_run)
    args = argparse.Namespace(out=out_dir, summary=summary_path, fpga_part="xc7z020clg400-1", clock_period_ns=10.0, timeout_seconds=1)

    status = module.run_campaign(args)
    merged = json.loads(summary_path.read_text(encoding="utf-8"))
    report = (out_dir / "real_hybrid_hls_report.md").read_text(encoding="utf-8")

    assert status["status"] == "passed"
    assert merged["integrated_vivado_impl_result"]["vivado_impl_passed"] is True
    assert merged["classification"]["integrated_vivado_impl_timing_met"] is True
    assert "vivado_impl_timing_met" in merged["classification"]["satisfied_preliminary_gates"]
    assert "Integrated Vivado implementation" in report
    assert "WNS" in report
    assert "LUT" in report


def test_parse_vivado_impl_timing_summary_uses_design_summary_not_later_empty_tables():
    from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import parse_vivado_impl_timing_summary_report

    timing = """
| Design Timing Summary
| ---------------------
    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints      WHS(ns)      THS(ns)  THS Failing Endpoints  THS Total Endpoints     WPWS(ns)     TPWS(ns)  TPWS Failing Endpoints  TPWS Total Endpoints
    -------      -------  ---------------------  -------------------      -------      -------  ---------------------  -------------------     --------     --------  ----------------------  --------------------
     -8.569     -960.241                    192                  604        0.263        0.000                      0                  604        4.500        0.000                       0                   306
| Inter Clock Table
| -----------------
From Clock    To Clock          WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints      WHS(ns)      THS(ns)  THS Failing Endpoints  THS Total Endpoints
----------    --------          -------      -------  ---------------------  -------------------      -------      -------  ---------------------  -------------------
Setup :          192  Failing Endpoints,  Worst Slack       -8.569ns,  Total Violation     -960.241ns
"""

    parsed = parse_vivado_impl_timing_summary_report(timing)

    assert parsed["wns_ns"] == -8.569
    assert parsed["tns_ns"] == -960.241
    assert parsed["whs_ns"] == 0.263
    assert parsed["ths_ns"] == 0.0
    assert parsed["wpws_ns"] == 4.5
    assert parsed["tpws_ns"] == 0.0
    assert parsed["timing_met"] is False
    assert "vivado_impl_setup_timing_not_met" in parsed["blockers"]


def test_build_integrated_vcs_sidecar_accounting_uses_vivado_impl_clock_when_provided(tmp_path: Path):
    run_dir = tmp_path / "runs" / "case-a" / "gpu_only_baseline"
    run_dir.mkdir(parents=True)
    (run_dir / "run_001.stdout.log").write_text(
        """
     h_psi        :      0.10s CPU      0.30s WALL (       4 calls)
     sum_band     :      0.01s CPU      0.20s WALL (       5 calls)
     mix_rho      :      0.02s CPU      0.10s WALL (       3 calls)
     PWSCF        :      0.90s CPU      1.00s WALL
""",
        encoding="utf-8",
    )
    gpu_baseline = {"measurements_are_real": True, "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}]}
    integrated_result = {
        "architecture_id": "hybrid_integrated_combined_sidecar_v1",
        "vcs_passed": True,
        "vcs_parsed": {
            "status": "parsed",
            "rtl_status": "Pass",
            "latency_cycles": 288,
            "samples": 288,
            "component_cycles": {
                "hpsi": {"samples": 96, "cycles": 96},
                "sum_band": {"samples": 128, "cycles": 128},
                "axpy": {"samples": 64, "cycles": 64},
            },
            "blockers": [],
        },
        "clock_ns": 8.75,
        "implemented_clock_ns": 20.0,
        "implemented_clock_source": "vivado_post_route_timing_met",
    }

    accounting = build_integrated_vcs_sidecar_accounting(gpu_baseline, tmp_path / "runs", integrated_result)

    item = accounting[0]
    assert item["fpga_clock_ns"] == 20.0
    assert item["fpga_clock_source"] == "vivado_post_route_timing_met"
    assert item["fpga_components"][0]["clock_ns"] == 20.0


def test_vivado_impl_runner_accepts_clock_period_argument():
    import importlib.util

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "run_qe_ic_real_hybrid_vivado_impl.py"
    spec = importlib.util.spec_from_file_location("run_qe_ic_real_hybrid_vivado_impl", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    args = module.parse_args(["--clock-period-ns", "20.0"])

    assert args.clock_period_ns == 20.0


def test_real_hybrid_vivado_impl_runner_recomputes_integrated_trace_replay_with_implemented_clock(tmp_path: Path, monkeypatch):
    import argparse
    import importlib.util

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "run_qe_ic_real_hybrid_vivado_impl.py"
    spec = importlib.util.spec_from_file_location("run_qe_ic_real_hybrid_vivado_impl", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"measurements_are_real": True, "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}]}),
        encoding="utf-8",
    )
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "case-a" / "gpu_only_baseline"
    run_dir.mkdir(parents=True)
    (run_dir / "run_001.stdout.log").write_text(
        """
     h_psi        :      0.10s CPU      0.30s WALL (       4 calls)
     sum_band     :      0.01s CPU      0.20s WALL (       5 calls)
     mix_rho      :      0.02s CPU      0.10s WALL (       3 calls)
     PWSCF        :      0.90s CPU      1.00s WALL
""",
        encoding="utf-8",
    )
    summary_path = out_dir / "real_hybrid_hls_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "gpu_baseline_path": str(baseline_path),
                "gpu_runs_root": str(runs_root),
                "classification": {
                    "preliminary_label": "fpga_hybrid_weaker",
                    "confidence": "medium",
                    "final_claim_allowed": False,
                    "blockers": ["full_qe_kernel_integration_missing", "physical_fpga_board_measurement_missing"],
                    "architecture_comparisons": [],
                    "claim_boundary": "old boundary",
                },
                "evidence_rows": [
                    {
                        "architecture_id": "hybrid_hpsi_local_potential_v1",
                        "implementation_maturity": "real_hls_kernel",
                        "csim_passed": True,
                        "cosim_passed": True,
                        "csynth_parsed": {"status": "parsed", "estimated_clock_ns": 8.75, "resource_feasible": True, "blockers": []},
                        "cosim_parsed": {"status": "parsed", "latency_cycles_max": 96, "blockers": []},
                        "workflow_accounting": [],
                    },
                    {
                        "architecture_id": "hybrid_sum_band_density_accumulator_v1",
                        "implementation_maturity": "real_hls_kernel",
                        "csim_passed": True,
                        "cosim_passed": True,
                        "csynth_parsed": {"status": "parsed", "estimated_clock_ns": 8.75, "resource_feasible": True, "blockers": []},
                        "cosim_parsed": {"status": "parsed", "latency_cycles_max": 128, "blockers": []},
                        "workflow_accounting": [],
                    },
                ],
                "integrated_vcs_sidecar_result": {
                    "architecture_id": "hybrid_integrated_combined_sidecar_v1",
                    "vcs_passed": True,
                    "clock_ns": 8.75,
                    "vcs_parsed": {
                        "status": "parsed",
                        "rtl_status": "Pass",
                        "latency_cycles": 288,
                        "samples": 288,
                        "component_cycles": {
                            "hpsi": {"samples": 96, "cycles": 96},
                            "sum_band": {"samples": 128, "cycles": 128},
                            "axpy": {"samples": 64, "cycles": 64},
                        },
                        "blockers": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run(*, out_dir, fpga_part, clock_period_ns, timeout_seconds, architecture_id="hybrid_integrated_combined_sidecar_v1"):
        return {
            "architecture_id": "hybrid_integrated_combined_sidecar_v1",
            "vivado_impl_attempted": True,
            "vivado_impl_passed": True,
            "implemented_clock_ns": clock_period_ns,
            "implemented_clock_source": "vivado_post_route_timing_met",
            "vivado_impl_utilization_parsed": {"status": "parsed", "resource": {"lut": 1, "ff": 1, "bram_tile": 0, "dsp": 1}, "resource_feasible": True, "blockers": []},
            "vivado_impl_timing_parsed": {"status": "parsed", "wns_ns": 1.0, "tns_ns": 0.0, "timing_met": True, "blockers": []},
            "blockers": [],
            "claim_boundary": "Integrated Vivado implementation evidence; not board measurement or full QE integration.",
        }

    monkeypatch.setattr(module, "run_integrated_vivado_impl", fake_run)
    args = argparse.Namespace(out=out_dir, summary=summary_path, fpga_part="xc7z020clg400-1", clock_period_ns=20.0, timeout_seconds=1)

    module.run_campaign(args)
    merged = json.loads(summary_path.read_text(encoding="utf-8"))

    clocks = {row["fpga_clock_ns"] for row in merged["integrated_vcs_sidecar_accounting"] if row["status"] == "trace_replay_integrated_vcs_sidecar_sensitivity"}
    assert clocks == {20.0}
    assert merged["integrated_vcs_sidecar_result"]["implemented_clock_ns"] == 20.0
    assert merged["classification"]["integrated_vivado_impl_passed"] is True
    integrated_comparisons = [row for row in merged["classification"]["architecture_comparisons"] if row["architecture_id"] == "hybrid_integrated_combined_sidecar_v1"]
    assert integrated_comparisons
    assert integrated_comparisons[0]["microkernel"]["fpga_components"][0]["clock_ns"] == 20.0


def test_real_hybrid_vivado_impl_runner_drops_stale_synthetic_sidecar_comparisons(tmp_path: Path, monkeypatch):
    import argparse
    import importlib.util

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "run_qe_ic_real_hybrid_vivado_impl.py"
    spec = importlib.util.spec_from_file_location("run_qe_ic_real_hybrid_vivado_impl", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"measurements_are_real": True, "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}]}), encoding="utf-8")
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "case-a" / "gpu_only_baseline"
    run_dir.mkdir(parents=True)
    (run_dir / "run_001.stdout.log").write_text(
        """
     h_psi        :      0.10s CPU      0.30s WALL (       4 calls)
     sum_band     :      0.01s CPU      0.20s WALL (       5 calls)
     mix_rho      :      0.02s CPU      0.10s WALL (       3 calls)
     PWSCF        :      0.90s CPU      1.00s WALL
""",
        encoding="utf-8",
    )
    summary_path = out_dir / "real_hybrid_hls_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "gpu_baseline_path": str(baseline_path),
                "gpu_runs_root": str(runs_root),
                "classification": {
                    "preliminary_label": "fpga_hybrid_weaker",
                    "confidence": "medium",
                    "final_claim_allowed": False,
                    "blockers": ["full_qe_kernel_integration_missing", "physical_fpga_board_measurement_missing"],
                    "architecture_comparisons": [
                        {
                            "architecture_id": "hybrid_integrated_combined_sidecar_v1",
                            "case_id": "case-a",
                            "latency_source": "integrated_vcs_rtl",
                            "speedup_vs_gpu_mean": 999.0,
                            "workflow_accounting_status": "trace_replay_integrated_vcs_sidecar_sensitivity",
                            "microkernel": {"fpga_components": [{"clock_ns": 8.75}]},
                        }
                    ],
                    "claim_boundary": "old boundary",
                },
                "evidence_rows": [],
                "integrated_vcs_sidecar_result": {
                    "architecture_id": "hybrid_integrated_combined_sidecar_v1",
                    "vcs_passed": True,
                    "clock_ns": 8.75,
                    "vcs_parsed": {
                        "status": "parsed",
                        "rtl_status": "Pass",
                        "latency_cycles": 288,
                        "samples": 288,
                        "component_cycles": {
                            "hpsi": {"samples": 96, "cycles": 96},
                            "sum_band": {"samples": 128, "cycles": 128},
                            "axpy": {"samples": 64, "cycles": 64},
                        },
                        "blockers": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run(*, out_dir, fpga_part, clock_period_ns, timeout_seconds, architecture_id="hybrid_integrated_combined_sidecar_v1"):
        return {
            "architecture_id": "hybrid_integrated_combined_sidecar_v1",
            "vivado_impl_attempted": True,
            "vivado_impl_passed": True,
            "implemented_clock_ns": clock_period_ns,
            "implemented_clock_source": "vivado_post_route_timing_met",
            "vivado_impl_utilization_parsed": {"status": "parsed", "resource": {"lut": 1, "ff": 1, "bram_tile": 0, "dsp": 1}, "resource_feasible": True, "blockers": []},
            "vivado_impl_timing_parsed": {"status": "parsed", "wns_ns": 1.0, "tns_ns": 0.0, "timing_met": True, "blockers": []},
            "blockers": [],
            "claim_boundary": "Integrated Vivado implementation evidence; not board measurement or full QE integration.",
        }

    monkeypatch.setattr(module, "run_integrated_vivado_impl", fake_run)
    args = argparse.Namespace(out=out_dir, summary=summary_path, fpga_part="xc7z020clg400-1", clock_period_ns=20.0, timeout_seconds=1)

    module.run_campaign(args)
    merged = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = [row for row in merged["classification"]["architecture_comparisons"] if row["architecture_id"] == "hybrid_integrated_combined_sidecar_v1"]

    assert len(rows) == 1
    assert rows[0]["speedup_vs_gpu_mean"] != 999.0
    assert rows[0]["microkernel"]["fpga_components"][0]["clock_ns"] == 20.0
    assert merged["classification"]["best_vivado_implemented_architecture_id"] == "hybrid_integrated_combined_sidecar_v1"


def test_render_real_hybrid_hls_report_distinguishes_vivado_implemented_best_speedup():
    summary = {
        "classification": {
            "preliminary_label": "fpga_hybrid_weaker",
            "confidence": "medium",
            "final_claim_allowed": False,
            "best_architecture_id": "hybrid_combined_vcs_sidecar_v1",
            "best_speedup_vs_gpu_mean": 1.5510985,
            "best_vivado_implemented_architecture_id": "hybrid_integrated_combined_sidecar_v1",
            "best_vivado_implemented_speedup_vs_gpu_mean": 1.5504687,
            "blockers": ["full_qe_kernel_integration_missing"],
            "architecture_comparisons": [],
            "claim_boundary": "boundary",
        },
        "evidence_rows": [],
        "integrated_vivado_impl_result": {
            "vivado_impl_passed": True,
            "implemented_clock_ns": 20.0,
            "vivado_impl_timing_parsed": {"timing_met": True, "wns_ns": 1.183, "tns_ns": 0.0},
            "vivado_impl_utilization_parsed": {"resource_feasible": True, "resource": {"lut": 731, "ff": 295, "bram_tile": 0, "dsp": 8}},
        },
    }

    report = render_real_hybrid_hls_report(summary)

    assert "Best Vivado-implemented architecture: `hybrid_integrated_combined_sidecar_v1`" in report
    assert "Best Vivado-implemented trace-replay speedup vs GPU: `1.55047x`" in report
    assert "implemented clock `20.0` ns" in report


def test_materialize_integrated_pipelined_vcs_sidecar_project_contains_pipeline_and_markers(tmp_path: Path):
    from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
        materialize_integrated_pipelined_vcs_sidecar_project,
    )

    project = materialize_integrated_pipelined_vcs_sidecar_project(build_real_hybrid_architecture_specs(), tmp_path)

    assert project["architecture_id"] == "hybrid_integrated_pipelined_sidecar_v2"
    assert project["pipeline_latency_cycles"] >= 4
    rtl = Path(project["rtl_sv"]).read_text()
    tb = Path(project["tb_sv"]).read_text()
    assert "module qeic_real_integrated_pipelined_sidecar_rtl" in rtl
    assert "stage1_valid" in rtl
    assert "stage2_valid" in rtl
    assert "stage3_valid" in rtl
    assert "stage4_valid" in rtl
    assert "DSE_REAL_RTL_PASS qeic_real_integrated_pipelined_sidecar_rtl" in tb
    assert "DSE_REAL_RTL_COMPONENT hpsi" in tb
    assert "DSE_REAL_RTL_COMPONENT sum_band" in tb
    assert "DSE_REAL_RTL_COMPONENT axpy" in tb
    assert "stub" not in rtl.lower()
    assert project["samples"] == 96 + 128 + 64
    assert project["component_samples"] == {"hpsi": 96, "sum_band": 128, "axpy": 64}


def test_materialize_integrated_pipelined_vivado_impl_project_uses_pipelined_rtl(tmp_path: Path):
    from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
        materialize_integrated_pipelined_vivado_impl_project,
    )

    project = materialize_integrated_pipelined_vivado_impl_project(
        build_real_hybrid_architecture_specs(), tmp_path, fpga_part="xc7z020clg400-1", clock_period_ns=10.0
    )

    assert project["architecture_id"] == "hybrid_integrated_pipelined_sidecar_v2"
    assert project["top_module"] == "qeic_real_integrated_pipelined_sidecar_impl_top"
    rtl = Path(project["rtl_sv"]).read_text()
    wrapper = Path(project["wrapper_sv"]).read_text()
    tcl = Path(project["vivado_impl_tcl"]).read_text()
    assert "module qeic_real_integrated_pipelined_sidecar_rtl" in rtl
    assert "module qeic_real_integrated_pipelined_sidecar_impl_top" in wrapper
    assert "qeic_real_integrated_pipelined_sidecar_rtl" in wrapper
    assert "synth_design -top qeic_real_integrated_pipelined_sidecar_impl_top -part xc7z020clg400-1" in tcl
    assert "create_clock -period 10.000" in Path(project["vivado_impl_xdc"]).read_text()


def test_materialize_integrated_streaming_vcs_sidecar_project_contains_ii1_markers(tmp_path: Path):
    from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
        materialize_integrated_streaming_vcs_sidecar_project,
    )

    project = materialize_integrated_streaming_vcs_sidecar_project(build_real_hybrid_architecture_specs(), tmp_path)

    assert project["architecture_id"] == "hybrid_integrated_streaming_pipeline_sidecar_v3"
    assert project["pipeline_latency_cycles"] == 4
    assert project["initiation_interval_cycles"] == 1
    rtl = Path(project["rtl_sv"]).read_text()
    tb = Path(project["tb_sv"]).read_text()
    assert "module qeic_real_integrated_streaming_pipeline_sidecar_rtl" in rtl
    assert "accepted_count" in rtl
    assert "completed_count" in rtl
    assert "stage1_valid" in rtl and "stage2_valid" in rtl and "stage3_valid" in rtl
    assert "TOTAL_SAMPLES + PIPELINE_LATENCY - 1" not in tb  # baked into generated evidence.
    assert "EXPECTED_LATENCY = 291" in tb
    assert "DSE_REAL_RTL_PASS qeic_real_integrated_streaming_pipeline_sidecar_rtl" in tb
    assert "DSE_REAL_RTL_COMPONENT hpsi samples=%0d cycles=%0d" in tb
    assert "stub" not in rtl.lower()
    assert project["samples"] == 96 + 128 + 64
    assert project["component_samples"] == {"hpsi": 96, "sum_band": 128, "axpy": 64}


def test_materialize_integrated_streaming_vivado_impl_project_uses_streaming_rtl(tmp_path: Path):
    from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
        materialize_integrated_streaming_vivado_impl_project,
    )

    project = materialize_integrated_streaming_vivado_impl_project(
        build_real_hybrid_architecture_specs(), tmp_path, fpga_part="xc7z020clg400-1", clock_period_ns=12.0
    )

    assert project["architecture_id"] == "hybrid_integrated_streaming_pipeline_sidecar_v3"
    assert project["top_module"] == "qeic_real_integrated_streaming_pipeline_sidecar_impl_top"
    assert project["initiation_interval_cycles"] == 1
    rtl = Path(project["rtl_sv"]).read_text()
    wrapper = Path(project["wrapper_sv"]).read_text()
    tcl = Path(project["vivado_impl_tcl"]).read_text()
    assert "module qeic_real_integrated_streaming_pipeline_sidecar_rtl" in rtl
    assert "module qeic_real_integrated_streaming_pipeline_sidecar_impl_top" in wrapper
    assert "qeic_real_integrated_streaming_pipeline_sidecar_rtl" in wrapper
    assert "synth_design -top qeic_real_integrated_streaming_pipeline_sidecar_impl_top -part xc7z020clg400-1" in tcl
    assert "create_clock -period 12.000" in Path(project["vivado_impl_xdc"]).read_text()


def test_build_integrated_vcs_sidecar_accounting_preserves_pipelined_architecture_id(tmp_path: Path):
    run_dir = tmp_path / "runs" / "case-a" / "gpu_only_baseline"
    run_dir.mkdir(parents=True)
    (run_dir / "run_001.stdout.log").write_text(
        """
     h_psi        :      0.10s CPU      0.30s WALL (       4 calls)
     sum_band     :      0.01s CPU      0.20s WALL (       5 calls)
     mix_rho      :      0.02s CPU      0.10s WALL (       3 calls)
     PWSCF        :      0.90s CPU      1.00s WALL
""",
        encoding="utf-8",
    )
    gpu_baseline = {"measurements_are_real": True, "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}]}
    integrated_result = {
        "architecture_id": "hybrid_integrated_pipelined_sidecar_v2",
        "vcs_passed": True,
        "implemented_clock_ns": 10.0,
        "implemented_clock_source": "vivado_post_route_timing_met",
        "vcs_parsed": {
            "status": "parsed",
            "rtl_status": "Pass",
            "latency_cycles": 300,
            "samples": 288,
            "component_cycles": {
                "hpsi": {"samples": 96, "cycles": 100},
                "sum_band": {"samples": 128, "cycles": 132},
                "axpy": {"samples": 64, "cycles": 68},
            },
            "blockers": [],
        },
    }

    accounting = build_integrated_vcs_sidecar_accounting(gpu_baseline, tmp_path / "runs", integrated_result)

    assert accounting[0]["architecture_id"] == "hybrid_integrated_pipelined_sidecar_v2"
    assert accounting[0]["integrated_latency_cycles"] == 300
    assert accounting[0]["fpga_clock_ns"] == 10.0
    assert accounting[0]["fpga_clock_source"] == "vivado_post_route_timing_met"


def test_build_integrated_vcs_sidecar_accounting_marks_streaming_architecture(tmp_path: Path):
    run_dir = tmp_path / "runs" / "case-a" / "gpu_only_baseline"
    run_dir.mkdir(parents=True)
    (run_dir / "run_001.stdout.log").write_text(
        """
     h_psi        :      0.10s CPU      0.30s WALL (       4 calls)
     sum_band     :      0.01s CPU      0.20s WALL (       5 calls)
     mix_rho      :      0.02s CPU      0.10s WALL (       3 calls)
     PWSCF        :      0.90s CPU      1.00s WALL
""",
        encoding="utf-8",
    )
    gpu_baseline = {"measurements_are_real": True, "baseline_records": [{"case_id": "case-a", "runtime_seconds_mean": 1.0}]}
    integrated_result = {
        "architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
        "vcs_passed": True,
        "implemented_clock_ns": 12.0,
        "implemented_clock_source": "vivado_post_route_timing_met",
        "vcs_parsed": {
            "status": "parsed",
            "rtl_status": "Pass",
            "latency_cycles": 291,
            "samples": 288,
            "component_cycles": {
                "hpsi": {"samples": 96, "cycles": 99},
                "sum_band": {"samples": 128, "cycles": 131},
                "axpy": {"samples": 64, "cycles": 67},
            },
            "blockers": [],
        },
    }

    accounting = build_integrated_vcs_sidecar_accounting(gpu_baseline, tmp_path / "runs", integrated_result)

    assert accounting[0]["architecture_id"] == "hybrid_integrated_streaming_pipeline_sidecar_v3"
    assert accounting[0]["implementation_coverage"] == "integrated_streaming_pipeline_sidecar_motif"
    assert accounting[0]["integrated_latency_cycles"] == 291
    assert accounting[0]["fpga_clock_ns"] == 12.0


def test_vivado_impl_runner_accepts_integrated_architecture_ids():
    import importlib.util

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "run_qe_ic_real_hybrid_vivado_impl.py"
    spec = importlib.util.spec_from_file_location("run_qe_ic_real_hybrid_vivado_impl", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    args = module.parse_args(["--architecture-id", "hybrid_integrated_streaming_pipeline_sidecar_v3"])

    assert args.architecture_id == "hybrid_integrated_streaming_pipeline_sidecar_v3"


def test_build_real_hybrid_superiority_proof_audit_fail_closes_current_artifacts():
    from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
        build_real_hybrid_superiority_proof_audit,
    )

    summary = {
        "classification": {
            "preliminary_label": "fpga_hybrid_weaker",
            "final_claim_allowed": False,
            "best_vivado_implemented_architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
            "best_vivado_implemented_speedup_vs_gpu_mean": 1.5508900953937812,
        },
        "integrated_vcs_sidecar_result": {
            "architecture_id": "hybrid_integrated_combined_sidecar_v1",
            "vcs_passed": True,
            "vcs_parsed": {"latency_cycles": 288, "samples": 288, "rtl_status": "Pass"},
        },
        "integrated_pipelined_vcs_sidecar_result": {
            "architecture_id": "hybrid_integrated_pipelined_sidecar_v2",
            "vcs_passed": True,
            "vcs_parsed": {"latency_cycles": 1152, "samples": 288, "rtl_status": "Pass"},
        },
        "integrated_streaming_vcs_sidecar_result": {
            "architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
            "vcs_passed": True,
            "vcs_parsed": {"latency_cycles": 291, "samples": 288, "rtl_status": "Pass"},
        },
        "integrated_vivado_impl_result": {
            "architecture_id": "hybrid_integrated_combined_sidecar_v1",
            "vivado_impl_passed": True,
            "implemented_clock_ns": 20.0,
            "vivado_impl_timing_parsed": {"timing_met": True, "wns_ns": 1.183},
            "vivado_impl_utilization_parsed": {"resource_feasible": True, "resource": {"lut": 731, "ff": 295, "dsp": 8, "bram_tile": 0}},
        },
        "integrated_pipelined_vivado_impl_result": {
            "architecture_id": "hybrid_integrated_pipelined_sidecar_v2",
            "vivado_impl_passed": True,
            "implemented_clock_ns": 12.0,
            "vivado_impl_timing_parsed": {"timing_met": True, "wns_ns": 0.946},
            "vivado_impl_utilization_parsed": {"resource_feasible": True, "resource": {"lut": 805, "ff": 696, "dsp": 8, "bram_tile": 0}},
        },
        "integrated_streaming_vivado_impl_result": {
            "architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
            "vivado_impl_passed": True,
            "implemented_clock_ns": 12.0,
            "vivado_impl_timing_parsed": {"timing_met": True, "wns_ns": 0.962},
            "vivado_impl_utilization_parsed": {"resource_feasible": True, "resource": {"lut": 848, "ff": 736, "dsp": 8, "bram_tile": 0}},
        },
    }
    closure = {
        "preliminary_label": "fpga_hybrid_weaker",
        "claim_verdict": "not_superior_current_evidence",
        "final_claim_allowed": False,
        "missing_gate_ids": ["full_qe_kernel_integration", "physical_fpga_board_measurement"],
    }
    gpu_baseline = {"measurements_are_real": True, "baseline_records": [{"case_id": "case-a"}, {"case_id": "case-b"}, {"case_id": "case-c"}]}

    audit = build_real_hybrid_superiority_proof_audit(summary=summary, claim_closure=closure, gpu_baseline=gpu_baseline)

    assert audit["schema_version"] == "dse.qe_ic.real_hybrid_superiority_proof_audit.v1"
    assert audit["decision"] == "fpga_hybrid_weaker"
    assert audit["claim_verdict"] == "not_superior_current_evidence"
    assert audit["strong_superiority_claim_allowed"] is False
    assert audit["missing_gate_ids"] == ["full_qe_kernel_integration", "physical_fpga_board_measurement"]
    assert audit["best_vivado_implemented_architecture_id"] == "hybrid_integrated_streaming_pipeline_sidecar_v3"
    assert audit["architecture_count"] == 3
    assert audit["vcs_passed_architecture_count"] == 3
    assert audit["vivado_passed_architecture_count"] == 3
    assert audit["checks_by_id"]["measured_gpu_baseline"]["status"] == "satisfied"
    assert audit["checks_by_id"]["multiple_distinct_integrated_architectures"]["status"] == "satisfied"
    assert audit["checks_by_id"]["full_qe_kernel_integration"]["status"] == "missing"
    assert audit["checks_by_id"]["physical_fpga_board_measurement"]["status"] == "missing"

    readiness = {
        "schema_version": "dse.qe_ic.full_qe_kernel_integration_readiness.v1",
        "status": "blocked_temporary",
        "passed": False,
        "full_qe_kernel_integration_gate_satisfied": False,
        "blockers": ["full_qe_pw_scf_consumption_proof_missing"],
    }
    audit_with_readiness = build_real_hybrid_superiority_proof_audit(
        summary=summary,
        claim_closure=closure,
        gpu_baseline=gpu_baseline,
        full_qe_integration_readiness=readiness,
    )
    full_qe_check = audit_with_readiness["checks_by_id"]["full_qe_kernel_integration"]
    assert full_qe_check["status"] == "missing"
    assert full_qe_check["evidence"]["readiness_audit_present"] is True
    assert full_qe_check["evidence"]["readiness_gate_satisfied"] is False
    assert full_qe_check["evidence"]["readiness_blockers"] == ["full_qe_pw_scf_consumption_proof_missing"]


def test_real_hybrid_superiority_audit_runner_writes_fail_closed_audit(tmp_path: Path):
    import argparse
    import importlib.util

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "audit_qe_ic_real_hybrid_superiority.py"
    spec = importlib.util.spec_from_file_location("audit_qe_ic_real_hybrid_superiority", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    summary_path = out_dir / "summary.json"
    closure_path = out_dir / "closure.json"
    baseline_path = out_dir / "baseline.json"
    audit_path = out_dir / "audit.json"
    summary_path.write_text(json.dumps({
        "classification": {
            "preliminary_label": "fpga_hybrid_weaker",
            "final_claim_allowed": False,
            "best_vivado_implemented_architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
            "best_vivado_implemented_speedup_vs_gpu_mean": 1.55,
        },
        "integrated_streaming_vcs_sidecar_result": {
            "architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
            "vcs_passed": True,
            "vcs_parsed": {"rtl_status": "Pass", "latency_cycles": 291},
        },
        "integrated_streaming_vivado_impl_result": {
            "architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
            "vivado_impl_passed": True,
            "implemented_clock_ns": 12.0,
            "vivado_impl_timing_parsed": {"timing_met": True, "wns_ns": 0.962},
            "vivado_impl_utilization_parsed": {"resource_feasible": True, "resource": {"lut": 848}},
        },
    }), encoding="utf-8")
    closure_path.write_text(json.dumps({
        "preliminary_label": "fpga_hybrid_weaker",
        "claim_verdict": "not_superior_current_evidence",
        "final_claim_allowed": False,
        "missing_gate_ids": ["full_qe_kernel_integration", "physical_fpga_board_measurement"],
    }), encoding="utf-8")
    baseline_path.write_text(json.dumps({"measurements_are_real": True, "baseline_records": [{"case_id": "case-a"}]}), encoding="utf-8")

    status = module.run_audit(argparse.Namespace(summary=summary_path, claim_closure=closure_path, gpu_baseline=baseline_path, out=audit_path))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert status["status"] == "written"
    assert audit["decision"] == "fpga_hybrid_weaker"
    assert audit["strong_superiority_claim_allowed"] is False
    assert audit["checks_by_id"]["physical_fpga_board_measurement"]["status"] == "missing"


def test_build_full_qe_kernel_integration_readiness_audit_fail_closes_sidecar_only_evidence():
    from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (
        build_full_qe_kernel_integration_readiness_audit,
    )

    summary = {
        "integrated_vcs_sidecar_result": {
            "architecture_id": "hybrid_integrated_combined_sidecar_v1",
            "vcs_passed": True,
            "vcs_parsed": {"rtl_status": "Pass", "latency_cycles": 288},
        },
        "integrated_streaming_vcs_sidecar_result": {
            "architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
            "vcs_passed": True,
            "vcs_parsed": {"rtl_status": "Pass", "latency_cycles": 291},
        },
        "integrated_vivado_impl_result": {
            "architecture_id": "hybrid_integrated_combined_sidecar_v1",
            "vivado_impl_passed": True,
            "implemented_clock_ns": 20.0,
            "vivado_impl_timing_parsed": {"timing_met": True},
            "vivado_impl_utilization_parsed": {"resource_feasible": True},
        },
        "integrated_streaming_vivado_impl_result": {
            "architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
            "vivado_impl_passed": True,
            "implemented_clock_ns": 12.0,
            "vivado_impl_timing_parsed": {"timing_met": True},
            "vivado_impl_utilization_parsed": {"resource_feasible": True},
        },
    }
    hook_audit = {
        "schema_version": "dse.qe.full_scf_hook_coverage_audit.v1",
        "passed": False,
        "required_major_kernel_count": 8,
        "runtime_hook_contract_passed_count": 0,
        "trusted_replacement_evidence_count": 0,
        "accelerated_results_consumed_by_qe_count": 0,
        "blockers": ["kernel_replacement_evidence_missing_or_untrusted::hpsi_local_potential"],
        "major_kernel_records": [
            {
                "kernel_id": "hpsi_local_potential",
                "trusted_replacement_evidence_present": False,
                "accelerated_results_consumed_by_qe": False,
                "runtime_hook_contract_passed": False,
            }
        ],
    }

    audit = build_full_qe_kernel_integration_readiness_audit(
        summary=summary,
        hook_coverage_audit=hook_audit,
        candidate_id="hybrid_integrated_streaming_pipeline_sidecar_v3",
        workload_case_id="ic_si_bulk_2atom_scf_v0",
    )

    assert audit["schema_version"] == "dse.qe_ic.full_qe_kernel_integration_readiness.v1"
    assert audit["status"] == "blocked_temporary"
    assert audit["passed"] is False
    assert audit["full_qe_kernel_integration_gate_satisfied"] is False
    assert audit["available_sidecar_evidence"]["vcs_passed_architecture_count"] == 2
    assert audit["available_sidecar_evidence"]["vivado_passed_architecture_count"] == 2
    assert audit["qe_runtime_replacement_evidence"]["hook_audit_present"] is True
    assert audit["qe_runtime_replacement_evidence"]["runtime_hook_contract_passed_count"] == 0
    assert "qe_runtime_replacement_contract_not_passed" in audit["blockers"]
    assert "full_qe_pw_scf_consumption_proof_missing" in audit["blockers"]
    assert "physical_fpga_board_measurement_missing" in audit["blockers"]
    assert audit["claim_boundary"].startswith("Readiness/admission audit only")


def test_full_qe_kernel_integration_readiness_runner_writes_fail_closed_artifact(tmp_path: Path):
    import argparse
    import importlib.util

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "audit_qe_ic_real_hybrid_full_qe_integration_readiness.py"
    spec = importlib.util.spec_from_file_location("audit_qe_ic_real_hybrid_full_qe_integration_readiness", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    summary_path = tmp_path / "summary.json"
    hook_path = tmp_path / "hook.json"
    out_path = tmp_path / "readiness.json"
    summary_path.write_text(json.dumps({
        "integrated_streaming_vcs_sidecar_result": {
            "architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
            "vcs_passed": True,
            "vcs_parsed": {"rtl_status": "Pass", "latency_cycles": 291},
        },
        "integrated_streaming_vivado_impl_result": {
            "architecture_id": "hybrid_integrated_streaming_pipeline_sidecar_v3",
            "vivado_impl_passed": True,
            "implemented_clock_ns": 12.0,
            "vivado_impl_timing_parsed": {"timing_met": True},
            "vivado_impl_utilization_parsed": {"resource_feasible": True},
        },
    }), encoding="utf-8")
    hook_path.write_text(json.dumps({
        "schema_version": "dse.qe.full_scf_hook_coverage_audit.v1",
        "passed": False,
        "required_major_kernel_count": 8,
        "runtime_hook_contract_passed_count": 0,
        "trusted_replacement_evidence_count": 0,
        "accelerated_results_consumed_by_qe_count": 0,
        "blockers": ["kernel_replacement_evidence_missing_or_untrusted::fft_ifft_ffft"],
    }), encoding="utf-8")

    status = module.run_audit(argparse.Namespace(
        summary=summary_path,
        hook_coverage_audit=hook_path,
        full_scf_comparison=None,
        candidate_id="hybrid_integrated_streaming_pipeline_sidecar_v3",
        workload_case_id="ic_si_bulk_2atom_scf_v0",
        out=out_path,
    ))
    audit = json.loads(out_path.read_text())

    assert status["status"] == "written"
    assert status["passed"] is False
    assert audit["admission_status"] == "not_admitted"
    assert audit["available_sidecar_evidence"]["vivado_passed_architecture_ids"] == ["hybrid_integrated_streaming_pipeline_sidecar_v3"]
    assert "qe_runtime_replacement_contract_not_passed" in audit["blockers"]
