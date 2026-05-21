#!/usr/bin/env python3
"""Fresh candidate-specific PPA execution lane tests."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.reference_workloads import dft_candidate_specific_ppa_execution as execution
from dse_v2.reference_workloads.dft_candidate_specific_ppa_execution import (
    DFT_CANDIDATE_SPECIFIC_PPA_EXECUTION_SCHEMA,
    build_dft_candidate_specific_ppa_execution,
    build_dft_candidate_specific_ppa_execution_aggregate,
    materialize_fresh_candidate_specific_outputs,
    validate_dft_candidate_specific_ppa_execution,
    write_dft_candidate_specific_ppa_execution_aggregate,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _candidate_bundle(run_dir: Path, candidate_id: str, kernel_id: str) -> dict:
    files = []
    for stage_id, names in {
        "golden_correctness": [
            "golden_correctness_report.json",
            "golden_reference_trace.json",
            "candidate_input_manifest.json",
        ],
        "hls_or_rtl_sim": [
            "hls_csim_or_rtl_sim_transcript.log",
            "rtl_or_hls_sim_result.json",
            "sim_waveform_manifest.json",
        ],
        "hls_or_rtl_synth": [
            "hls_or_rtl_synth_report.json",
            "hls_or_rtl_synth_utilization.json",
            "hls_or_rtl_synth_transcript.log",
        ],
        "vivado_fpga_synth_or_impl": [
            "vivado_synth_or_impl.log",
            "vivado_timing_summary.rpt",
            "vivado_utilization.rpt",
            "vivado_route_status.json",
        ],
        "dc_asic_synth_timing_area": [
            "dc_shell.log",
            "dc_timing.rpt",
            "dc_area.rpt",
            "dc_qor.rpt",
            "dc_synth.ddc",
        ],
    }.items():
        for name in names:
            files.append(
                {
                    "stage_id": stage_id,
                    "path": f"candidate_specific_evidence/{candidate_id}/{kernel_id}/{name}",
                    "required": True,
                }
            )
    for name in [
        "tool_versions.json",
        "command_manifest.json",
        "raw_transcript_index.json",
        "source_bundle_manifest.json",
    ]:
        files.append(
            {
                "stage_id": "all",
                "path": f"candidate_specific_evidence/{candidate_id}/{kernel_id}/{name}",
                "required": True,
            }
        )
    return {
        "schema_version": "unit-test.candidate_bundle.v1",
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
        "expected_evidence_files": files,
    }


def _seed_fresh_work_dir(work_dir: Path) -> None:
    _write_json(
        work_dir / "golden_correctness.json",
        {
            "schema_version": "unit-test.golden.v1",
            "status": "passed",
            "inputs": {"x": [1, 2]},
            "expected": {"y": [3]},
        },
    )
    _write_json(work_dir / "manifest.json", {"schema_version": "unit-test.manifest.v1"})
    _write_text(work_dir / "vcs_compile.log", "compiled\n")
    _write_text(work_dir / "vcs_run.log", "RTL_PASS\n")
    _write_text(work_dir / "vivado_stdout.log", "synth_design completed successfully\nROUTE_DESIGN COMPLETE\n")
    _write_text(work_dir / "vivado_stderr.log", "")
    _write_text(work_dir / "vivado_timing_summary.rpt", "WNS: 0.11\n")
    _write_text(work_dir / "vivado_utilization.rpt", "Slice LUTs 10\n")
    _write_text(work_dir / "vivado_route_status.rpt", "route complete\n")
    _write_text(work_dir / "dc_stdout.log", "Library: fsa0a_c_generic_core_tt1p8v25c\n")
    _write_text(work_dir / "dc_timing.rpt", "Library: fsa0a_c_generic_core_tt1p8v25c\nslack (MET) 0.04\n")
    _write_text(work_dir / "dc_area.rpt", "Total cell area: 12.3\n")
    _write_text(work_dir / "dc_synth.ddc", "binary-ddc-placeholder-for-unit-test\n")


def test_materialize_fresh_outputs_do_not_write_source_flow_admission(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "cand-a"
    kernel_id = "complex_gemm_gemv_tile"
    unit_dir = run_dir / "candidate_specific_evidence" / candidate_id / kernel_id
    work_dir = unit_dir / "fresh_tool_work" / "run-1"
    bundle = _candidate_bundle(run_dir, candidate_id, kernel_id)
    _seed_fresh_work_dir(work_dir)

    rows = materialize_fresh_candidate_specific_outputs(
        run_dir=run_dir,
        unit_dir=unit_dir,
        work_dir=work_dir,
        candidate_bundle=bundle,
        candidate_id=candidate_id,
        kernel_id=kernel_id,
        stage_ids=[
            "golden_correctness",
            "hls_or_rtl_sim",
            "hls_or_rtl_synth",
            "vivado_fpga_synth_or_impl",
            "dc_asic_synth_timing_area",
        ],
        command_run_id="fresh-run-1",
    )

    assert len(rows) >= 16
    candidate_input = json.loads((unit_dir / "candidate_input_manifest.json").read_text())
    assert "source_flow_dir" not in candidate_input
    assert candidate_input["input_source"] == "fresh_candidate_specific_tool_execution"
    assert candidate_input["fresh_execution_work_dir"].endswith("fresh_tool_work/run-1")
    assert json.loads((unit_dir / "vivado_route_status.json").read_text())["implementation_route_completed"] is True
    assert (unit_dir / "dc_synth.ddc").exists()


def test_execution_skip_remote_clears_stale_raw_and_records_provenance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "cand-a"
    kernel_id = "complex_gemm_gemv_tile"
    unit_dir = run_dir / "candidate_specific_evidence" / candidate_id / kernel_id
    bundle_path = run_dir / "candidate_specific_bundles" / candidate_id / kernel_id / "candidate_bundle.json"
    _write_json(bundle_path, _candidate_bundle(run_dir, candidate_id, kernel_id))
    _write_text(unit_dir / "dc_shell.log", "STALE DC SHOULD BE REMOVED\n")
    _write_json(
        run_dir / "parsed_hard_gate_results" / candidate_id / kernel_id / "golden_correctness_parsed_result.json",
        {"verdict": "passed"},
    )
    _write_json(
        unit_dir / "command_manifest.json",
        {
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "command_templates": [
                {"template_id": "template_golden", "stage_ids": ["golden_correctness"], "tool": "python3"}
            ],
        },
    )
    queue = {
        "schema_version": "unit-test.queue.v1",
        "work_items": [
            {
                "candidate_id": candidate_id,
                "kernel_id": kernel_id,
                "stage_id": stage_id,
                "candidate_bundle_json": str(bundle_path),
                "unit_evidence_dir": str(unit_dir),
            }
            for stage_id in [
                "golden_correctness",
                "hls_or_rtl_sim",
                "hls_or_rtl_synth",
                "vivado_fpga_synth_or_impl",
                "dc_asic_synth_timing_area",
            ]
        ],
    }
    _write_json(run_dir / "dft_hardware_tie_breaker_execution_queue.json", queue)
    monkeypatch.setattr(
        execution,
        "_probe_tool_versions",
        lambda **_: {
            "tool_versions_recorded": True,
            "probe_command": {"status": "passed", "returncode": 0},
            "tool_rows": [{"tool": "vivado", "available": True}],
        },
    )

    payload = build_dft_candidate_specific_ppa_execution(
        run_dir=run_dir,
        candidate_ids=[candidate_id],
        kernel_ids=[kernel_id],
        max_units=1,
        skip_remote=True,
        timeout_s=60,
    )
    validation = validate_dft_candidate_specific_ppa_execution(payload)

    assert payload["schema_version"] == DFT_CANDIDATE_SPECIFIC_PPA_EXECUTION_SCHEMA
    assert validation["valid"] is True
    assert payload["selected_unit_count"] == 1
    assert payload["materialized_raw_file_count"] == 3
    assert not (unit_dir / "dc_shell.log").exists()
    assert not (run_dir / "parsed_hard_gate_results" / candidate_id / kernel_id / "golden_correctness_parsed_result.json").exists()
    tool_versions = json.loads((unit_dir / "tool_versions.json").read_text())
    command_manifest = json.loads((unit_dir / "command_manifest.json").read_text())
    source_bundle = json.loads((unit_dir / "source_bundle_manifest.json").read_text())
    assert tool_versions["tool_versions_recorded"] is True
    assert command_manifest["commands_executed"] is True
    assert source_bundle["fresh_execution_work_dir"]
    assert source_bundle["shared_microkernel_smoke_only"] is False


def test_aggregate_fresh_execution_shards_deduplicates_latest_unit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    unit_a_old = {
        "candidate_id": "cand-a",
        "kernel_id": "fft_ifft_ffft",
        "status": "blocked_fresh_candidate_specific_execution",
        "materialized_raw_file_count": 1,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": "old",
    }
    unit_a_new = {
        "candidate_id": "cand-a",
        "kernel_id": "fft_ifft_ffft",
        "status": "fresh_candidate_specific_execution_recorded",
        "materialized_raw_file_count": 18,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": "new",
    }
    unit_b = {
        "candidate_id": "cand-b",
        "kernel_id": "dma_hbm_movement_engine",
        "status": "fresh_candidate_specific_execution_recorded",
        "materialized_raw_file_count": 18,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": "new",
    }
    _write_json(
        run_dir / "fresh_candidate_specific_ppa_execution_001" / "dft_candidate_specific_ppa_execution.json",
        {
            "schema_version": DFT_CANDIDATE_SPECIFIC_PPA_EXECUTION_SCHEMA,
            "generated_at": "2026-05-21T00:00:00Z",
            "units": [unit_a_old],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "fresh_candidate_specific_ppa_execution_002" / "dft_candidate_specific_ppa_execution.json",
        {
            "schema_version": DFT_CANDIDATE_SPECIFIC_PPA_EXECUTION_SCHEMA,
            "generated_at": "2026-05-21T01:00:00Z",
            "units": [unit_a_new, unit_b],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    aggregate = build_dft_candidate_specific_ppa_execution_aggregate(run_dir)
    status = write_dft_candidate_specific_ppa_execution_aggregate(run_dir)

    assert aggregate["executed_unit_count"] == 2
    assert aggregate["blocked_unit_count"] == 0
    assert aggregate["materialized_raw_file_count"] == 36
    assert status["status"] == "passed"
    written = json.loads((run_dir / "dft_candidate_specific_ppa_execution.json").read_text())
    assert written["executed_unit_count"] == 2
    assert written["deliverable_complete"] is False
