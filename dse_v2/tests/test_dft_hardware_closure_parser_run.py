#!/usr/bin/env python3
"""DFT hardware closure parser-run tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.reference_workloads.dft_hardware_closure_evidence import (
    write_dft_hardware_closure_evidence_intake,
)
from dse_v2.codesign.evidence_ledger import sha256_file
from dse_v2.reference_workloads.dft_hardware_closure_adjudication import (
    write_dft_hardware_closure_adjudication,
)
from dse_v2.reference_workloads.dft_hardware_closure_packets import (
    write_dft_hardware_closure_packets,
)
from dse_v2.reference_workloads.dft_hardware_closure_parser_run import (
    DFT_HARDWARE_CLOSURE_PARSER_RUN_SCHEMA,
    build_dft_hardware_closure_parser_run,
    validate_dft_hardware_closure_parser_run,
    write_dft_hardware_closure_parser_run,
)
from dse_v2.reference_workloads.dft_hardware_closure_parsed_evidence import (
    DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA,
    build_dft_hardware_closure_parsed_evidence_manifest,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts
from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _closure_shards(path: Path) -> Path:
    unit = {
        "unit_id": "cand-a:fft_ifft_ffft",
        "candidate_id": "cand-a",
        "kernel_id": "fft_ifft_ffft",
        "kernel_name": "FFT / iFFT / fFFT",
        "kernel_family": "spectral_transform",
        "stage_ids": [
            "golden_correctness",
            "hls_or_rtl_sim",
            "hls_or_rtl_synth",
            "vivado_fpga_synth_or_impl",
            "dc_asic_synth_timing_area",
        ],
        "required_tools": ["dc_shell", "vcs", "vivado"],
        "work_item_ids": [
            "cand-a:fft_ifft_ffft:golden_correctness",
            "cand-a:fft_ifft_ffft:hls_or_rtl_sim",
            "cand-a:fft_ifft_ffft:hls_or_rtl_synth",
            "cand-a:fft_ifft_ffft:vivado_fpga_synth_or_impl",
            "cand-a:fft_ifft_ffft:dc_asic_synth_timing_area",
        ],
        "work_item_count": 5,
        "blocked_work_item_count": 5,
        "candidate_specific_bundle_required": True,
        "candidate_specific_evidence_present": False,
    }
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_shards.v1",
            "status": "queued_fail_closed",
            "release_id": "release-parser-run",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "unit_count": 1,
            "shard_count": 1,
            "work_item_count": 5,
            "blocked_work_item_count": 5,
            "candidate_specific_bundle_count": 0,
            "candidate_specific_evidence_present_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "shards": [
                {
                    "shard_id": "dft_hardware_closure_shard_0000",
                    "candidate_ids": ["cand-a"],
                    "kernel_ids": ["fft_ifft_ffft"],
                    "required_tools": ["dc_shell", "vcs", "vivado"],
                    "unit_count": 1,
                    "work_item_count": 5,
                    "blocked_work_item_count": 5,
                    "candidate_specific_bundle_count": 0,
                    "units": [unit],
                }
            ],
        },
    )


def _packetized_run(run_dir: Path) -> Path:
    shards_path = _closure_shards(run_dir / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(run_dir, hardware_closure_shards_path=shards_path)
    return run_dir / "dft_hardware_closure_packet_index.json"


def _unit_from_packet(run_dir: Path) -> dict:
    packet = json.loads(
        (run_dir / "dft_hardware_closure_packets" / "dft_hardware_closure_shard_0000_packet.json").read_text()
    )
    return packet["units"][0]


def _write_candidate_bundle(run_dir: Path, unit: dict) -> None:
    _write_json(
        run_dir / unit["candidate_bundle_json"],
        {
            "schema_version": "dse.dft.candidate_specific_bundle.test.v1",
            "candidate_id": unit["candidate_id"],
            "kernel_id": unit["kernel_id"],
        },
    )


def _write_stage_raw_files(run_dir: Path, unit: dict, stage_id: str, *, verdict: str = "PASS") -> list[Path]:
    written = []
    for expected in unit["expected_evidence_files"]:
        if expected["stage_id"] != stage_id:
            continue
        path = run_dir / expected["path"]
        if path.suffix == ".json":
            written.append(
                _write_json(
                    path,
                    {
                        "schema_version": "unit-test.raw_evidence.v1",
                        "status": verdict,
                        "verdict": verdict.lower(),
                        "passed": verdict.upper() in {"PASS", "PASSED", "SUCCESS", "MET"},
                        "max_abs_error": 0.0,
                    },
                )
            )
        else:
            written.append(_write_text(path, f"{stage_id} {verdict}\n"))
    return written


def _write_raw_transcript_refs(run_dir: Path, unit: dict, stage_id: str, raw_paths: list[Path], *, shared_smoke_only: bool = False) -> None:
    transcript_path = next(
        run_dir / expected["path"]
        for expected in unit["expected_evidence_files"]
        if expected["stage_id"] == "all" and Path(expected["path"]).name == "raw_transcript_index.json"
    )
    payload = json.loads(transcript_path.read_text())
    refs = []
    for raw_path in raw_paths:
        refs.append(
            {
                "stage_id": stage_id,
                "candidate_id": unit["candidate_id"],
                "kernel_id": unit["kernel_id"],
                "path": str(raw_path.relative_to(run_dir)),
                "sha256": sha256_file(raw_path),
                "hash_algorithm": "sha256",
                "candidate_specific": not shared_smoke_only,
                "shared_microkernel_smoke_only": shared_smoke_only,
            }
        )
    payload["raw_transcript_refs"] = refs
    payload["raw_stage_evidence_file_count"] = len(refs)
    _write_json(transcript_path, payload)


def _write_global_provenance_files(run_dir: Path, unit: dict, *, shared_smoke_only: bool = False) -> list[Path]:
    written = []
    for expected in unit["expected_evidence_files"]:
        if expected["stage_id"] != "all":
            continue
        path = run_dir / expected["path"]
        if path.name == "source_bundle_manifest.json":
            payload = {
                "schema_version": "dse.dft.candidate_source_bundle_manifest.test.v1",
                "candidate_id": unit["candidate_id"],
                "kernel_id": unit["kernel_id"],
                "candidate_specific_closure": not shared_smoke_only,
                "shared_microkernel_smoke_only": shared_smoke_only,
                "raw_evidence_scope": "shared_microkernel_smoke" if shared_smoke_only else "candidate_specific_closure",
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
            }
        else:
            payload = {
                "schema_version": "dse.dft.candidate_global_provenance.test.v1",
                "candidate_id": unit["candidate_id"],
                "kernel_id": unit["kernel_id"],
                "status": "present",
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
            }
        written.append(_write_json(path, payload))
    return written


def _write_intake(run_dir: Path) -> Path:
    packet_index = _packetized_run(run_dir)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )
    return run_dir / "dft_hardware_closure_evidence_intake.json"


def test_parser_run_blocks_missing_raw_evidence_without_writing_parsed_results(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    status = write_dft_hardware_closure_parser_run(
        run_dir,
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    assert status["status"] == "passed"
    assert not (run_dir / "parsed_hard_gate_results").exists()
    parser_run = json.loads((run_dir / "dft_hardware_closure_parser_run.json").read_text())
    validation = json.loads((run_dir / "dft_hardware_closure_parser_run_validation.json").read_text())
    assert parser_run["schema_version"] == DFT_HARDWARE_CLOSURE_PARSER_RUN_SCHEMA
    assert parser_run["status"] == "blocked_missing_raw_evidence"
    assert parser_run["parsed_result_written_count"] == 0
    assert parser_run["blocked_stage_count"] == 5
    assert {row["status"] for row in parser_run["parser_rows"]} == {"blocked_missing_candidate_specific_provenance"}
    assert parser_run["passed_stage_count"] == 0
    assert parser_run["hardware_completion_eligible"] is False
    assert parser_run["deliverable_complete"] is False
    assert validation["valid"] is True


def test_parser_run_writes_present_raw_parser_output_without_passing_gate(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    _write_global_provenance_files(run_dir, unit)
    raw_paths = _write_stage_raw_files(run_dir, unit, "golden_correctness", verdict="PASS")
    _write_raw_transcript_refs(run_dir, unit, "golden_correctness", raw_paths)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    assert parser_run["parsed_result_written_count"] == 1
    assert parser_run["blocked_stage_count"] == 4
    assert parser_run["passed_stage_count"] == 0
    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "golden_correctness")
    assert row["status"] == "parsed_result_written_pending_adjudication"
    assert row["passed"] is False
    assert row["adjudication_result"] == "not_adjudicated_by_parser_run"
    parsed_ref = row["parsed_result"]
    parsed = json.loads((run_dir / parsed_ref["path"]).read_text())
    assert parsed["schema_version"] == DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA
    assert parsed["candidate_id"] == "cand-a"
    assert parsed["kernel_id"] == "fft_ifft_ffft"
    assert parsed["stage_id"] == "golden_correctness"
    assert parsed["verdict"] == "passed"
    assert parsed["hardware_completion_eligible"] is False
    assert parsed["deliverable_complete"] is False

    write_dft_hardware_closure_adjudication(
        run_dir,
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
    )
    manifest = build_dft_hardware_closure_parsed_evidence_manifest(
        closure_adjudication_path=run_dir / "dft_hardware_closure_adjudication.json",
        parsed_root=run_dir,
    )
    assert manifest["present_parsed_result_count"] == 1
    assert manifest["valid_parsed_result_count"] == 1
    assert manifest["parsed_verdict_counts"]["passed"] == 1
    assert manifest["passed_stage_count"] == 0
    assert manifest["adjudication_result"] == "not_adjudicated_by_parsed_manifest"
    assert manifest["hardware_completion_eligible"] is False
    assert manifest["deliverable_complete"] is False


def test_parser_run_accepts_parsed_hard_gate_results_as_parsed_root_without_double_prefix(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    parsed_root = run_dir / "parsed_hard_gate_results"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    _write_global_provenance_files(run_dir, unit)
    raw_paths = _write_stage_raw_files(run_dir, unit, "golden_correctness", verdict="PASS")
    _write_raw_transcript_refs(run_dir, unit, "golden_correctness", raw_paths)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=parsed_root,
    )

    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "golden_correctness")
    assert parser_run["parsed_result_written_count"] == 1
    assert row["parsed_result"]["path"] == "cand-a/fft_ifft_ffft/golden_correctness_parsed_result.json"
    assert (parsed_root / "cand-a" / "fft_ifft_ffft" / "golden_correctness_parsed_result.json").exists()
    assert not (parsed_root / "parsed_hard_gate_results").exists()


def test_parser_run_blocks_absolute_or_escaped_intake_paths(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    unit_from_packet = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit_from_packet)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )
    intake_path = run_dir / "dft_hardware_closure_evidence_intake.json"
    intake = json.loads(intake_path.read_text())
    unit = intake["packets"][0]["unit_rows"][0]
    outside = _write_json(tmp_path / "outside_pass.json", {"passed": True})
    for expected in unit["expected_evidence_files"]:
        if expected["stage_id"] == "golden_correctness":
            expected["path"] = str(outside)
            expected["exists"] = True
            expected["path_valid"] = True
            break
    _write_json(intake_path, intake)

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=intake_path,
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "golden_correctness")
    assert row["status"] == "blocked_invalid_evidence_path"
    assert row["invalid_raw_file_count"] == 1
    assert parser_run["parsed_result_written_count"] == 0


def test_parser_run_failure_markers_dominate_passing_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    _write_global_provenance_files(run_dir, unit)
    raw_paths = []
    for expected in unit["expected_evidence_files"]:
        if expected["stage_id"] != "hls_or_rtl_sim":
            continue
        path = run_dir / expected["path"]
        if path.name == "rtl_or_hls_sim_result.json":
            raw_paths.append(_write_json(path, {"passed": True, "verdict": "passed"}))
        else:
            raw_paths.append(_write_text(path, "FATAL: simulator terminated\n"))
    _write_raw_transcript_refs(run_dir, unit, "hls_or_rtl_sim", raw_paths)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "hls_or_rtl_sim")
    assert row["status"] == "parsed_result_written_pending_adjudication"
    assert row["parsed_result"]["verdict"] == "failed"


def test_parser_run_synth_payload_ignores_benign_vivado_failed_nets_progress(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    _write_global_provenance_files(run_dir, unit)
    raw_paths = []
    for expected in unit["expected_evidence_files"]:
        if expected["stage_id"] != "hls_or_rtl_synth":
            continue
        path = run_dir / expected["path"]
        if path.suffix == ".json":
            raw_paths.append(_write_json(path, {"passed": True, "verdict": "passed", "status": "passed"}))
        else:
            raw_paths.append(
                _write_text(
                    path,
                    "\n".join(
                        [
                            "synth_design completed successfully",
                            "Number of Failed Nets               = 584",
                            "Number of Failed Nets               = 0",
                            "route_design completed successfully",
                            "ROUTE_DESIGN COMPLETE",
                        ]
                    ),
                )
            )
    _write_raw_transcript_refs(run_dir, unit, "hls_or_rtl_synth", raw_paths)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "hls_or_rtl_synth")
    assert row["status"] == "parsed_result_written_pending_adjudication"
    assert row["parsed_result"]["verdict"] == "passed"


def test_parser_run_vivado_route_status_ignores_intermediate_failed_nets_progress(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    _write_global_provenance_files(run_dir, unit)
    raw_paths = []
    for expected in unit["expected_evidence_files"]:
        if expected["stage_id"] != "vivado_fpga_synth_or_impl":
            continue
        path = run_dir / expected["path"]
        if path.name == "vivado_route_status.json":
            raw_paths.append(
                _write_json(
                    path,
                    {
                        "schema_version": "unit-test.vivado_route_status.v1",
                        "stage_id": "vivado_fpga_synth_or_impl",
                        "status": "passed",
                        "verdict": "passed",
                        "passed": True,
                        "synth_design_completed": True,
                        "implementation_route_completed": True,
                    },
                )
            )
        else:
            raw_paths.append(
                _write_text(
                    path,
                    "\n".join(
                        [
                            "synth_design completed successfully",
                            "Number of Failed Nets               = 1748",
                            "Number of Failed Nets               = 0",
                            "route_design completed successfully",
                            "ROUTE_DESIGN COMPLETE",
                        ]
                    ),
                )
            )
    _write_raw_transcript_refs(run_dir, unit, "vivado_fpga_synth_or_impl", raw_paths)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "vivado_fpga_synth_or_impl")
    assert row["status"] == "parsed_result_written_pending_adjudication"
    assert row["parsed_result"]["verdict"] == "passed"
    parsed = json.loads((run_dir / row["parsed_result"]["path"]).read_text())
    assert parsed["metrics"]["implementation_route_completed"] is True
    assert parsed["metrics"]["implementation_route_completed_source"] == "vivado_route_status_json"


def test_parser_run_blocks_vivado_synth_only_without_impl_route(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    _write_global_provenance_files(run_dir, unit)
    raw_paths = []
    for expected in unit["expected_evidence_files"]:
        if expected["stage_id"] != "vivado_fpga_synth_or_impl":
            continue
        path = run_dir / expected["path"]
        if path.name == "vivado_route_status.json":
            raw_paths.append(
                _write_json(
                    path,
                    {
                        "schema_version": "unit-test.vivado_route_status.v1",
                        "stage_id": "vivado_fpga_synth_or_impl",
                        "status": "passed",
                        "verdict": "passed",
                        "passed": True,
                        "synth_design_completed": True,
                        "implementation_route_completed": False,
                    },
                )
            )
        else:
            raw_paths.append(_write_text(path, "synth_design completed successfully\n"))
    _write_raw_transcript_refs(run_dir, unit, "vivado_fpga_synth_or_impl", raw_paths)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "vivado_fpga_synth_or_impl")
    assert row["status"] == "parsed_result_written_pending_adjudication"
    assert row["parsed_result"]["verdict"] == "blocked"
    assert row["parsed_blocker_ids"] == ["vivado_implementation_route_not_completed"]
    parsed = json.loads((run_dir / row["parsed_result"]["path"]).read_text())
    assert parsed["metrics"]["implementation_route_completed"] is False
    assert parsed["metrics"]["implementation_route_completed_source"] == "not_observed"
    assert parsed["blocker_ids"] == ["vivado_implementation_route_not_completed"]


def test_parser_run_blocks_dc_target_library_and_unmapped_gtech_outputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    _write_global_provenance_files(run_dir, unit)
    raw_paths = []
    dc_text_by_name = {
        "dc_shell.log": "Error: Could not read the following target libraries: your_library.db\n",
        "dc_timing.rpt": "Library: gtech\n(Path is unconstrained)\nslack (MET) 0.01\n",
        "dc_area.rpt": "Library(s) Used:\n    gtech\nTotal cell area:                     0.000000\nInformation: This design contains unmapped logic.\n",
        "dc_qor.rpt": "DC QoR blocked: target library unavailable\n",
        "dc_synth.ddc": "DC wrote a design database fixture, but the run is still gtech/unmapped.\n",
    }
    for expected in unit["expected_evidence_files"]:
        if expected["stage_id"] != "dc_asic_synth_timing_area":
            continue
        path = run_dir / expected["path"]
        raw_paths.append(_write_text(path, dc_text_by_name[Path(expected["path"]).name]))
    _write_raw_transcript_refs(run_dir, unit, "dc_asic_synth_timing_area", raw_paths)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "dc_asic_synth_timing_area")
    assert row["status"] == "parsed_result_written_pending_adjudication"
    assert row["parsed_result"]["verdict"] == "blocked"
    assert "dc_target_library_unavailable" in row["parsed_result"]["blocker_ids"]
    assert "dc_unmapped_logic" in row["parsed_blocker_ids"]
    parsed = json.loads((run_dir / row["parsed_result"]["path"]).read_text())
    assert parsed["verdict"] == "blocked"
    assert set(parsed["blocker_ids"]) >= {
        "dc_target_library_unavailable",
        "dc_uses_gtech_library_only",
        "dc_unmapped_logic",
        "dc_unconstrained_timing",
        "dc_area_not_physical",
    }
    assert parsed["hardware_completion_eligible"] is False
    assert parsed["deliverable_complete"] is False


def test_parser_run_ignores_binary_dc_synth_ddc_when_scanning_dc_text(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    _write_global_provenance_files(run_dir, unit)
    raw_paths = []
    dc_text_by_name = {
        "dc_shell.log": (
            "Loading db file '/real/lib/fsa0a_c_generic_core_tt1p8v25c.db'\n"
            "Loading link library 'fsa0a_c_generic_core_tt1p8v25c'\n"
        ),
        "dc_timing.rpt": "Operating Conditions: TCCOM   Library: fsa0a_c_generic_core_tt1p8v25c\nslack (MET) 0.04\n",
        "dc_area.rpt": "TOTAL AREA: undefined\nTotal cell area: 42.0\n",
        "dc_qor.rpt": "QoR ok\n",
    }
    for expected in unit["expected_evidence_files"]:
        if expected["stage_id"] != "dc_asic_synth_timing_area":
            continue
        path = run_dir / expected["path"]
        if Path(expected["path"]).name == "dc_synth.ddc":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x00GTECH\x00UNMAPPED LOGIC\x00TOTAL CELL AREA: 0.000000\x00")
            raw_paths.append(path)
        else:
            raw_paths.append(_write_text(path, dc_text_by_name[Path(expected["path"]).name]))
    _write_raw_transcript_refs(run_dir, unit, "dc_asic_synth_timing_area", raw_paths)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "dc_asic_synth_timing_area")
    assert row["parsed_result"]["verdict"] == "passed"
    assert row["parsed_blocker_ids"] == []
    assert row["stage_blocker_ids"] == []
    parsed = json.loads((run_dir / row["parsed_result"]["path"]).read_text())
    assert parsed["metrics"]["slack_ns"] == 0.04
    assert parsed["metrics"]["area"] == 42.0
    assert parsed["metrics"]["dc_target_library_discovery"] == "real_target_library_present"
    assert parsed["metrics"]["dc_target_libraries"] == ["fsa0a_c_generic_core_tt1p8v25c"]
    assert parsed["blocker_ids"] == []


def test_parser_run_blocks_zero_total_cell_area_not_total_area_undefined(tmp_path: Path) -> None:
    def build_case(case_dir: Path, cell_area: str) -> dict:
        packet_index = _packetized_run(case_dir)
        unit = _unit_from_packet(case_dir)
        _write_candidate_bundle(case_dir, unit)
        _write_global_provenance_files(case_dir, unit)
        raw_paths = []
        dc_text_by_name = {
            "dc_shell.log": "Loading link library 'fsa0a_c_generic_core_tt1p8v25c'\n",
            "dc_timing.rpt": "Library: fsa0a_c_generic_core_tt1p8v25c\nslack (MET) 0.01\n",
            "dc_area.rpt": f"TOTAL AREA: undefined\nTotal cell area: {cell_area}\n",
            "dc_qor.rpt": "QoR ok\n",
            "dc_synth.ddc": "ddc fixture\n",
        }
        for expected in unit["expected_evidence_files"]:
            if expected["stage_id"] != "dc_asic_synth_timing_area":
                continue
            path = case_dir / expected["path"]
            raw_paths.append(_write_text(path, dc_text_by_name[Path(expected["path"]).name]))
        _write_raw_transcript_refs(case_dir, unit, "dc_asic_synth_timing_area", raw_paths)
        write_dft_hardware_closure_evidence_intake(
            case_dir,
            closure_packet_index_path=packet_index,
            evidence_root=case_dir,
        )
        parser_run = build_dft_hardware_closure_parser_run(
            closure_evidence_intake_path=case_dir / "dft_hardware_closure_evidence_intake.json",
            evidence_root=case_dir,
            parsed_root=case_dir,
        )
        row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "dc_asic_synth_timing_area")
        return json.loads((case_dir / row["parsed_result"]["path"]).read_text())

    nonzero = build_case(tmp_path / "nonzero", "42.0")
    assert nonzero["verdict"] == "passed"
    assert nonzero["metrics"]["area"] == 42.0
    assert "dc_area_not_physical" not in nonzero["blocker_ids"]

    zero = build_case(tmp_path / "zero", "0.000000")
    assert zero["verdict"] == "blocked"
    assert zero["metrics"]["area"] == 0.0
    assert zero["blocker_ids"] == ["dc_area_not_physical"]


def test_parser_run_requires_raw_transcript_ref_hash(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    _write_global_provenance_files(run_dir, unit)
    raw_paths = _write_stage_raw_files(run_dir, unit, "golden_correctness", verdict="PASS")
    transcript_path = next(
        run_dir / expected["path"]
        for expected in unit["expected_evidence_files"]
        if expected["stage_id"] == "all" and Path(expected["path"]).name == "raw_transcript_index.json"
    )
    transcript = json.loads(transcript_path.read_text())
    transcript["raw_transcript_refs"] = [
        {
            "stage_id": "golden_correctness",
            "candidate_id": unit["candidate_id"],
            "kernel_id": unit["kernel_id"],
            "path": str(raw_paths[0].relative_to(run_dir)),
            "hash_algorithm": "sha256",
            "candidate_specific": True,
            "shared_microkernel_smoke_only": False,
        }
    ]
    _write_json(transcript_path, transcript)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "golden_correctness")
    assert row["status"] == "blocked_invalid_candidate_specific_provenance"
    assert "raw_transcript_ref_missing_hash" in row["candidate_specific_provenance_blockers"]


def test_parser_run_accepts_relative_evidence_root_for_staged_provenance(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    run_dir = Path("run")
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    _write_global_provenance_files(run_dir, unit)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "golden_correctness")
    assert row["status"] == "blocked_missing_raw_stage_evidence"
    assert row["candidate_specific_provenance_blockers"] == []


def test_parser_run_rejects_shared_microkernel_smoke_as_candidate_specific_stage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    _write_global_provenance_files(run_dir, unit, shared_smoke_only=True)
    _write_stage_raw_files(run_dir, unit, "golden_correctness", verdict="PASS")
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )

    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )

    assert parser_run["parsed_result_written_count"] == 0
    assert parser_run["blocked_stage_count"] == 5
    row = next(row for row in parser_run["parser_rows"] if row["stage_id"] == "golden_correctness")
    assert row["status"] == "blocked_invalid_candidate_specific_provenance"
    assert "source_bundle_is_shared_microkernel_smoke_only" in row["candidate_specific_provenance_blockers"]
    assert "source_bundle_raw_evidence_scope_not_candidate_specific" in row["candidate_specific_provenance_blockers"]


def test_parser_run_validator_rejects_claim_upgrade(tmp_path: Path) -> None:
    intake_path = _write_intake(tmp_path / "run")
    parser_run = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=intake_path,
        evidence_root=tmp_path / "run",
        parsed_root=tmp_path / "run",
    )

    upgraded = json.loads(json.dumps(parser_run))
    upgraded["hardware_completion_eligible"] = True
    upgraded["deliverable_complete"] = True
    upgraded["adjudication_result"] = "passed"
    upgraded["passed_stage_count"] = 1
    upgraded["parser_rows"][0]["passed"] = True
    upgraded["parser_rows"][0]["hardware_completion_eligible"] = True
    validation = validate_dft_hardware_closure_parser_run(upgraded)

    assert validation["valid"] is False
    assert validation["errors"]


def test_parser_run_cli_step5_and_goal_audit_visibility(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    packet_index = _packetized_run(run_dir)
    unit = _unit_from_packet(run_dir)
    _write_candidate_bundle(run_dir, unit)
    write_dft_hardware_closure_evidence_intake(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
    )
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_dft_hardware_closure_parsers.py",
            "--out",
            str(run_dir),
            "--closure-evidence-intake",
            str(run_dir / "dft_hardware_closure_evidence_intake.json"),
            "--evidence-root",
            str(run_dir),
            "--parsed-root",
            str(run_dir),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr

    _write_json(run_dir / "verdict.json", {"run_id": "parser-run-step5", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text())
    markdown = (run_dir / paths["final_report_markdown"]).read_text()
    section = report["dft_hardware_closure_parser_run"]
    assert section["present"] is True
    assert section["status"] == "fail_closed_hardware_closure_parser_run_present"
    assert section["stage_count"] == 5
    assert section["parsed_result_written_count"] == 0
    assert section["blocked_stage_count"] == 5
    assert section["parser_status_counts"]["blocked_missing_candidate_specific_provenance"] == 5
    assert section["passed_stage_count"] == 0
    assert section["adjudication_result"] == "not_adjudicated_by_parser_run"
    assert section["hardware_completion_eligible"] is False
    assert campaign_summary["dft_hardware_closure_parser_run_summary"]["present"] is True
    assert campaign_summary["dft_hardware_closure_parser_run_summary"]["parser_status_counts"] == section[
        "parser_status_counts"
    ]
    assert "DFT Hardware Closure Parser Run" in markdown
    assert "Parser status counts" in markdown

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=run_dir,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    requirements = {item["requirement"]: item["status"] for item in audit["prompt_to_artifact_checklist"]}
    assert requirements["DFT hardware closure parser run is Step5-visible and fail-closed"] == "passed"
