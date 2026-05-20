#!/usr/bin/env python3
"""DFT hardware closure raw-stage materialization tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_hardware_closure_adjudication import (
    write_dft_hardware_closure_adjudication,
)
from dse_v2.reference_workloads.dft_hardware_closure_bundle import write_dft_hardware_closure_candidate_bundles
from dse_v2.reference_workloads.dft_hardware_closure_evidence import write_dft_hardware_closure_evidence_intake
from dse_v2.reference_workloads.dft_hardware_closure_gate_adjudication import (
    write_dft_hardware_closure_gate_adjudication,
)
from dse_v2.reference_workloads.dft_hardware_closure_packets import write_dft_hardware_closure_packets
from dse_v2.reference_workloads.dft_hardware_closure_parsed_evidence import (
    write_dft_hardware_closure_parsed_evidence_manifest,
)
from dse_v2.reference_workloads.dft_hardware_closure_parser_run import write_dft_hardware_closure_parser_run
from dse_v2.reference_workloads.dft_hardware_closure_raw_stage_materialization import (
    DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_SCHEMA,
    validate_dft_hardware_closure_raw_stage_materialization,
    write_dft_hardware_closure_raw_stage_materialization,
)
from dse_v2.reference_workloads.dft_hardware_closure_raw_transcript_registration import (
    write_dft_hardware_closure_raw_transcript_registration,
)
from dse_v2.reference_workloads.dft_hardware_closure_release_gate import (
    write_dft_hardware_closure_release_gate,
)
from dse_v2.reference_workloads.dft_hardware_closure_unit_provenance import (
    write_dft_hardware_closure_unit_provenance,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts
from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)

_STAGE_IDS = [
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
]


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
        "unit_id": "cand-a:complex_gemm_gemv_tile",
        "candidate_id": "cand-a",
        "kernel_id": "complex_gemm_gemv_tile",
        "kernel_name": "complex GEMM / GEMV tile",
        "kernel_family": "dense_linear_algebra",
        "stage_ids": list(_STAGE_IDS),
        "required_tools": ["dc_shell", "vcs", "vivado"],
        "work_item_ids": [f"cand-a:complex_gemm_gemv_tile:{stage_id}" for stage_id in _STAGE_IDS],
        "work_item_count": len(_STAGE_IDS),
        "blocked_work_item_count": len(_STAGE_IDS),
        "candidate_specific_bundle_required": True,
        "candidate_specific_evidence_present": False,
    }
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_shards.v1",
            "status": "queued_fail_closed",
            "release_id": "release-raw-stage-materialization",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "unit_count": 1,
            "shard_count": 1,
            "work_item_count": len(_STAGE_IDS),
            "blocked_work_item_count": len(_STAGE_IDS),
            "candidate_specific_bundle_count": 0,
            "candidate_specific_evidence_present_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "shards": [
                {
                    "shard_id": "dft_hardware_closure_shard_0000",
                    "candidate_ids": ["cand-a"],
                    "kernel_ids": ["complex_gemm_gemv_tile"],
                    "required_tools": ["dc_shell", "vcs", "vivado"],
                    "unit_count": 1,
                    "work_item_count": len(_STAGE_IDS),
                    "blocked_work_item_count": len(_STAGE_IDS),
                    "candidate_specific_bundle_count": 0,
                    "units": [unit],
                }
            ],
        },
    )


def _prepare_run(run_dir: Path) -> Path:
    shards_path = _closure_shards(run_dir / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(run_dir, hardware_closure_shards_path=shards_path)
    packet_index = run_dir / "dft_hardware_closure_packet_index.json"
    write_dft_hardware_closure_candidate_bundles(run_dir, closure_packet_index_path=packet_index, evidence_root=run_dir)
    write_dft_hardware_closure_unit_provenance(run_dir, closure_packet_index_path=packet_index, evidence_root=run_dir)
    return packet_index


def _source_flow(source_dir: Path) -> Path:
    _write_json(
        source_dir / "golden_correctness.json",
        {
            "schema_version": "dse.dft.kernel_golden_correctness.v1",
            "kernel_id": "complex_gemm_gemv_tile",
            "status": "passed",
            "inputs": {"matrix_complex_pairs": [[[1, 2]]], "vector_complex_pairs": [[2, -1]]},
            "expected": {"y": [[5, 16], [8, 11]]},
        },
    )
    _write_json(source_dir / "manifest.json", {"kernel_id": "complex_gemm_gemv_tile"})
    _write_text(source_dir / "vcs_compile.log", "compile ok\n")
    _write_text(source_dir / "vcs_run.log", "COMPLEX_GEMM_GEMV_RTL_PASS y0=5,16 y1=8,11\n")
    _write_text(source_dir / "vivado_stdout.log", "synth_design completed successfully\n")
    _write_text(source_dir / "vivado_stderr.log", "")
    _write_text(source_dir / "vivado_timing_summary.rpt", "WNS(ns)  1.250\n")
    _write_text(source_dir / "vivado_utilization.rpt", "Slice LUTs 12\n")
    _write_text(source_dir / "dc_stdout.log", "DC attempted but library unavailable\n")
    _write_text(source_dir / "dc_timing.rpt", "slack (MET) 0.01\n")
    _write_text(source_dir / "dc_area.rpt", "total cell area: 42.0\n")
    return source_dir


def test_raw_stage_materialization_feeds_registration_parser_and_gate_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    source_dir = _source_flow(tmp_path / "source_flow")
    packet_index = _prepare_run(run_dir)

    status = write_dft_hardware_closure_raw_stage_materialization(
        run_dir,
        closure_packet_index_path=packet_index,
        source_flow_dir=source_dir,
        evidence_root=run_dir,
        candidate_ids=["cand-a"],
        kernel_ids=["complex_gemm_gemv_tile"],
    )

    assert status["status"] == "passed"
    payload = json.loads((run_dir / "dft_hardware_closure_raw_stage_materialization.json").read_text())
    assert payload["schema_version"] == DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_SCHEMA
    assert payload["materialized_unit_count"] == 1
    assert payload["materialized_file_count"] >= 12
    assert payload["missing_required_raw_stage_file_count"] == 1
    assert payload["blocked_unit_count"] == 1
    unit_row = payload["units"][0]
    missing = unit_row["missing_required_raw_stage_files"]
    assert [Path(item["path"]).name for item in missing] == ["dc_synth.ddc"]
    assert missing[0]["blocker_id"] == "missing_dc_synth_ddc_design_database"
    assert {Path(item["path"]).name for item in missing[0]["source_alternatives_present"]} >= {
        "dc_timing.rpt",
        "dc_area.rpt",
        "dc_stdout.log",
    }
    assert payload["hardware_completion_eligible"] is False
    assert payload["deliverable_complete"] is False
    assert validate_dft_hardware_closure_raw_stage_materialization(payload)["valid"] is True

    write_dft_hardware_closure_raw_transcript_registration(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
        candidate_ids=["cand-a"],
        kernel_ids=["complex_gemm_gemv_tile"],
    )
    registration = json.loads((run_dir / "dft_hardware_closure_raw_transcript_registration.json").read_text())
    assert registration["registered_unit_count"] == 1
    assert registration["registered_raw_stage_evidence_file_count"] == payload["materialized_file_count"]
    assert registration["passed_stage_count"] == 0

    write_dft_hardware_closure_evidence_intake(run_dir, closure_packet_index_path=packet_index, evidence_root=run_dir)
    write_dft_hardware_closure_parser_run(
        run_dir,
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
        evidence_root=run_dir,
        parsed_root=run_dir,
    )
    parser_run = json.loads((run_dir / "dft_hardware_closure_parser_run.json").read_text())
    parsed_by_stage = {row["stage_id"]: row for row in parser_run["parser_rows"]}
    assert parsed_by_stage["golden_correctness"]["status"] == "parsed_result_written_pending_adjudication"
    assert parsed_by_stage["hls_or_rtl_sim"]["status"] == "parsed_result_written_pending_adjudication"
    assert parsed_by_stage["hls_or_rtl_synth"]["status"] == "parsed_result_written_pending_adjudication"
    assert parsed_by_stage["vivado_fpga_synth_or_impl"]["status"] == "parsed_result_written_pending_adjudication"
    assert parsed_by_stage["dc_asic_synth_timing_area"]["status"] == "blocked_missing_raw_stage_evidence"
    assert parsed_by_stage["dc_asic_synth_timing_area"]["stage_blocker_ids"] == [
        "missing_dc_synth_ddc_design_database"
    ]
    assert parsed_by_stage["dc_asic_synth_timing_area"]["raw_stage_blocker_details"][0]["file_name"] == "dc_synth.ddc"
    assert parser_run["passed_stage_count"] == 0
    assert parser_run["hardware_completion_eligible"] is False

    write_dft_hardware_closure_adjudication(
        run_dir,
        closure_evidence_intake_path=run_dir / "dft_hardware_closure_evidence_intake.json",
    )
    write_dft_hardware_closure_parsed_evidence_manifest(
        run_dir,
        closure_adjudication_path=run_dir / "dft_hardware_closure_adjudication.json",
        parsed_root=run_dir,
    )
    write_dft_hardware_closure_gate_adjudication(
        run_dir,
        parsed_evidence_manifest_path=run_dir / "dft_hardware_closure_parsed_evidence_manifest.json",
    )
    write_dft_hardware_closure_release_gate(
        run_dir,
        gate_adjudication_path=run_dir / "dft_hardware_closure_gate_adjudication.json",
    )
    gate = json.loads((run_dir / "dft_hardware_closure_gate_adjudication.json").read_text())
    release = json.loads((run_dir / "dft_hardware_closure_release_gate.json").read_text())
    assert gate["stage_gate_passed_count"] == 4
    assert gate["unit_gate_passed_count"] == 0
    assert release["release_gate_result"] == "blocked_incomplete_hardware_release_gate"
    assert release["hardware_completion_eligible"] is False
    assert release["deliverable_complete"] is False

    _write_json(run_dir / "verdict.json", {"run_id": "raw-stage-materialization-step5", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])
    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text())
    markdown = (run_dir / paths["final_report_markdown"]).read_text()
    section = report["dft_hardware_closure_raw_stage_materialization"]
    assert section["present"] is True
    assert section["status"] == "fail_closed_hardware_closure_raw_stage_materialization_present"
    assert section["materialized_unit_count"] == 1
    assert section["missing_required_raw_stage_file_count"] == 1
    assert section["materialization_blocker_ids"] == ["missing_dc_synth_ddc_design_database"]
    assert section["unit_refs"][0]["missing_required_raw_stage_files"][0]["blocker_id"] == (
        "missing_dc_synth_ddc_design_database"
    )
    assert section["passed_stage_count"] == 0
    assert section["hardware_completion_eligible"] is False
    assert "DFT Hardware Closure Raw Stage Materialization" in markdown
    assert "Materialization blocker ids" in markdown
    assert "missing_dc_synth_ddc_design_database" in markdown
    assert campaign_summary["dft_hardware_closure_raw_stage_materialization_summary"]["present"] is True
    assert campaign_summary["dft_hardware_closure_raw_stage_materialization_summary"][
        "materialization_blocker_ids"
    ] == ["missing_dc_synth_ddc_design_database"]
    audit = build_dft_scf_hardware_goal_completion_audit(run_dir=run_dir)
    requirements = {item["requirement"]: item["status"] for item in audit["prompt_to_artifact_checklist"]}
    assert requirements["DFT hardware closure raw-stage materialization is Step5-visible and fail-closed"] == "passed"


def test_raw_stage_materialization_copies_dc_synth_ddc_when_source_flow_provides_it(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    source_dir = _source_flow(tmp_path / "source_flow")
    source_ddc = source_dir / "dc_synth.ddc"
    source_ddc.write_bytes(b"\x00real-binary-ddc-fixture\xff")
    packet_index = _prepare_run(run_dir)

    write_dft_hardware_closure_raw_stage_materialization(
        run_dir,
        closure_packet_index_path=packet_index,
        source_flow_dir=source_dir,
        evidence_root=run_dir,
        candidate_ids=["cand-a"],
        kernel_ids=["complex_gemm_gemv_tile"],
    )

    payload = json.loads((run_dir / "dft_hardware_closure_raw_stage_materialization.json").read_text())
    unit_row = payload["units"][0]
    assert payload["missing_required_raw_stage_file_count"] == 0
    assert payload["blocked_unit_count"] == 0
    assert unit_row["status"] == "candidate_specific_raw_stage_files_materialized_pending_registration"
    assert unit_row["missing_required_raw_stage_files"] == []
    ddc_row = next(item for item in unit_row["materialized_files"] if item["file_name"] == "dc_synth.ddc")
    assert ddc_row["stage_id"] == "dc_asic_synth_timing_area"
    assert ddc_row["operation"] == "copy"
    assert ddc_row["artifact"]["generated_wrapper"] is False
    assert ddc_row["artifact"]["sha256"] == ddc_row["artifact"]["source"]["sha256"]
    assert (run_dir / ddc_row["artifact"]["path"]).read_bytes() == source_ddc.read_bytes()

    write_dft_hardware_closure_raw_transcript_registration(
        run_dir,
        closure_packet_index_path=packet_index,
        evidence_root=run_dir,
        candidate_ids=["cand-a"],
        kernel_ids=["complex_gemm_gemv_tile"],
    )
    transcript_path = (
        run_dir
        / "candidate_specific_evidence"
        / "cand-a"
        / "complex_gemm_gemv_tile"
        / "raw_transcript_index.json"
    )
    transcript = json.loads(transcript_path.read_text())
    assert any(Path(ref["path"]).name == "dc_synth.ddc" for ref in transcript["raw_transcript_refs"])


def test_raw_stage_materialization_cli_rejects_missing_source_flow(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _prepare_run(run_dir)
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_raw_stage_materialization.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(packet_index),
            "--source-flow-dir",
            str(tmp_path / "missing"),
            "--evidence-root",
            str(run_dir),
            "--candidate-id",
            "cand-a",
            "--kernel-id",
            "complex_gemm_gemv_tile",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 1
    status = json.loads((run_dir / "dft_hardware_closure_raw_stage_materialization_status.json").read_text())
    validation = json.loads((run_dir / "dft_hardware_closure_raw_stage_materialization_validation.json").read_text())
    assert status["status"] == "failed"
    assert validation["valid"] is False
