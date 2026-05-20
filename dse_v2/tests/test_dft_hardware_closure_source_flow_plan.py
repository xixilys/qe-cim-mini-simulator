#!/usr/bin/env python3
"""DFT hardware closure source-flow planning tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_hardware_closure_packets import write_dft_hardware_closure_packets
from dse_v2.reference_workloads.dft_hardware_closure_source_flow_plan import (
    DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_SCHEMA,
    validate_dft_hardware_closure_source_flow_plan,
    write_dft_hardware_closure_source_flow_plan,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts

STAGES = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)
CANDIDATE_IDS = ("cand-a", "cand-b")
KERNEL_IDS = ("fft_ifft_ffft", "complex_gemm_gemv_tile")


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _closure_shards(path: Path) -> Path:
    units = []
    for candidate_id in CANDIDATE_IDS:
        for kernel_id in KERNEL_IDS:
            units.append(
                {
                    "unit_id": f"{candidate_id}:{kernel_id}",
                    "candidate_id": candidate_id,
                    "kernel_id": kernel_id,
                    "kernel_name": kernel_id.replace("_", " "),
                    "kernel_family": "source_flow_plan_test",
                    "stage_ids": list(STAGES),
                    "required_tools": ["python3", "vcs", "vivado", "dc_shell"],
                    "work_item_ids": [f"{candidate_id}:{kernel_id}:{stage_id}" for stage_id in STAGES],
                    "work_item_count": len(STAGES),
                    "blocked_work_item_count": len(STAGES),
                    "candidate_specific_bundle_required": True,
                    "candidate_specific_evidence_present": False,
                }
            )
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_shards.v1",
            "status": "queued_fail_closed",
            "release_id": "release-source-flow-plan-test",
            "candidate_count": len(CANDIDATE_IDS),
            "major_kernel_count": len(KERNEL_IDS),
            "unit_count": len(units),
            "shard_count": 1,
            "work_item_count": len(units) * len(STAGES),
            "blocked_work_item_count": len(units) * len(STAGES),
            "candidate_specific_bundle_count": 0,
            "candidate_specific_evidence_present_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "shards": [
                {
                    "shard_id": "dft_hardware_closure_shard_0000",
                    "candidate_ids": list(CANDIDATE_IDS),
                    "kernel_ids": list(KERNEL_IDS),
                    "required_tools": ["python3", "vcs", "vivado", "dc_shell"],
                    "unit_count": len(units),
                    "work_item_count": len(units) * len(STAGES),
                    "blocked_work_item_count": len(units) * len(STAGES),
                    "candidate_specific_bundle_count": 0,
                    "units": units,
                }
            ],
        },
    )


def _packetized_run(run_dir: Path) -> Path:
    shards_path = _closure_shards(run_dir / "dft_hardware_closure_shards.json")
    write_dft_hardware_closure_packets(run_dir, hardware_closure_shards_path=shards_path)
    return run_dir / "dft_hardware_closure_packet_index.json"


def _source_flow(path: Path, *, candidate_id: str, kernel_id: str) -> Path:
    _write_json(
        path / "manifest.json",
        {
            "schema_version": f"dse.dft_scf.{kernel_id}.rtl_flow.v1",
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "source_files": {"rtl": f"{kernel_id}.v", "testbench": f"tb_{kernel_id}.v"},
            "claim_boundary": "candidate/kernel source-flow fixture for source-flow plan tests only",
        },
    )
    _write_json(
        path / "golden_correctness.json",
        {"schema_version": "dse.dft.kernel_golden_correctness.v1", "status": "passed"},
    )
    _write_text(path / f"{kernel_id}.v", "// rtl fixture\n")
    return path


def _source_flow_map(path: Path, rows: list[dict[str, str]]) -> Path:
    return _write_json(path, {"flows": rows})


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_source_flow_plan_enumerates_every_packet_candidate_kernel_unit_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    source_flow = _source_flow(tmp_path / "flows" / "cand-a-fft", candidate_id="cand-a", kernel_id="fft_ifft_ffft")
    source_flow_map = _source_flow_map(
        tmp_path / "source_flow_map.json",
        [{"candidate_id": "cand-a", "kernel_id": "fft_ifft_ffft", "source_flow_dir": str(source_flow)}],
    )

    status = write_dft_hardware_closure_source_flow_plan(
        run_dir,
        closure_packet_index_path=packet_index,
        source_flow_map_path=source_flow_map,
    )

    assert status["status"] == "passed"
    plan = _load(run_dir / "dft_hardware_closure_source_flow_plan.json")
    validation = _load(run_dir / "dft_hardware_closure_source_flow_plan_validation.json")
    assert plan["schema_version"] == DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_SCHEMA
    assert plan["unit_count"] == 4
    assert plan["source_flow_present_count"] == 1
    assert plan["source_flow_missing_count"] == 3
    assert plan["hardware_completion_eligible"] is False
    assert plan["deliverable_complete"] is False
    assert validation["valid"] is True
    assert {(row["candidate_id"], row["kernel_id"]) for row in plan["units"]} == {
        ("cand-a", "fft_ifft_ffft"),
        ("cand-a", "complex_gemm_gemv_tile"),
        ("cand-b", "fft_ifft_ffft"),
        ("cand-b", "complex_gemm_gemv_tile"),
    }

    present = next(row for row in plan["units"] if row["candidate_id"] == "cand-a" and row["kernel_id"] == "fft_ifft_ffft")
    assert present["source_flow_present"] is True
    assert present["materialization_eligible"] is True
    assert present["status"] == "source_flow_present_pending_materialization"
    assert present["manifest_ref"]["exists"] is True
    assert present["expected_evidence_file_count"] == len(present["expected_evidence_files"])
    assert {item["stage_id"] for item in present["expected_evidence_files"]} >= set(STAGES)

    missing = [row for row in plan["units"] if not row["source_flow_present"]]
    assert len(missing) == 3
    assert {row["status"] for row in missing} == {"blocked_missing_source_flow"}
    assert all(row["hardware_completion_eligible"] is False for row in plan["units"])


def test_source_flow_plan_marks_all_units_missing_when_source_flow_map_is_absent(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)

    status = write_dft_hardware_closure_source_flow_plan(run_dir, closure_packet_index_path=packet_index)

    assert status["status"] == "passed"
    plan = _load(run_dir / "dft_hardware_closure_source_flow_plan.json")
    assert plan["source_artifacts"]["source_flow_map"] is None
    assert plan["unit_count"] == 4
    assert plan["source_flow_present_count"] == 0
    assert plan["source_flow_missing_count"] == 4
    assert plan["blocked_unit_count"] == 4
    assert plan["hardware_completion_eligible"] is False
    assert plan["deliverable_complete"] is False
    assert {row["status"] for row in plan["units"]} == {"blocked_missing_source_flow"}
    assert all(row["source_flow_present"] is False for row in plan["units"])


def test_source_flow_plan_blocks_wrong_candidate_and_wrong_kernel_reuse(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    wrong_candidate_flow = _source_flow(
        tmp_path / "flows" / "cand-b-fft-labeled-as-cand-a",
        candidate_id="cand-b",
        kernel_id="fft_ifft_ffft",
    )
    wrong_kernel_flow = _source_flow(
        tmp_path / "flows" / "cand-b-fft-labeled-as-complex",
        candidate_id="cand-b",
        kernel_id="fft_ifft_ffft",
    )
    source_flow_map = _source_flow_map(
        tmp_path / "source_flow_map.json",
        [
            {"candidate_id": "cand-a", "kernel_id": "fft_ifft_ffft", "source_flow_dir": str(wrong_candidate_flow)},
            {"candidate_id": "cand-b", "kernel_id": "complex_gemm_gemv_tile", "source_flow_dir": str(wrong_kernel_flow)},
        ],
    )

    write_dft_hardware_closure_source_flow_plan(
        run_dir,
        closure_packet_index_path=packet_index,
        source_flow_map_path=source_flow_map,
    )
    plan = _load(run_dir / "dft_hardware_closure_source_flow_plan.json")
    validation = _load(run_dir / "dft_hardware_closure_source_flow_plan_validation.json")

    assert validation["valid"] is True
    assert plan["source_flow_present_count"] == 0
    assert plan["blocked_wrong_candidate_reuse_count"] == 1
    assert plan["blocked_wrong_kernel_reuse_count"] == 1
    assert plan["hardware_completion_eligible"] is False

    wrong_candidate = next(row for row in plan["units"] if row["candidate_id"] == "cand-a" and row["kernel_id"] == "fft_ifft_ffft")
    assert wrong_candidate["source_flow_present"] is False
    assert wrong_candidate["status"] == "blocked_wrong_candidate_source_flow"
    assert "source_flow_candidate_id_mismatch" in wrong_candidate["blocker_ids"]

    wrong_kernel = next(row for row in plan["units"] if row["candidate_id"] == "cand-b" and row["kernel_id"] == "complex_gemm_gemv_tile")
    assert wrong_kernel["source_flow_present"] is False
    assert wrong_kernel["status"] == "blocked_wrong_kernel_source_flow"
    assert "source_flow_kernel_id_mismatch" in wrong_kernel["blocker_ids"]
    assert all(row["hardware_completion_eligible"] is False for row in plan["units"])


def test_source_flow_plan_preserves_workspace_relative_source_flow_paths(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    source_flow = _source_flow(tmp_path / "flows" / "cand-a-fft", candidate_id="cand-a", kernel_id="fft_ifft_ffft")
    relative_source_flow = Path(os.path.relpath(source_flow, Path.cwd()))
    source_flow_map = _source_flow_map(
        run_dir / "maps" / "source_flow_map.json",
        [{"candidate_id": "cand-a", "kernel_id": "fft_ifft_ffft", "source_flow_dir": str(relative_source_flow)}],
    )

    write_dft_hardware_closure_source_flow_plan(
        run_dir,
        closure_packet_index_path=packet_index,
        source_flow_map_path=source_flow_map,
    )
    plan = _load(run_dir / "dft_hardware_closure_source_flow_plan.json")
    row = next(row for row in plan["units"] if row["candidate_id"] == "cand-a" and row["kernel_id"] == "fft_ifft_ffft")

    assert row["source_flow_present"] is True
    assert row["source_flow_dir"] == str(relative_source_flow)
    assert row["source_flow_ref"]["path"] == str(relative_source_flow)
    assert row["source_flow_dir"] != str(source_flow_map.parent / relative_source_flow)
    assert not Path(row["source_flow_dir"]).is_absolute()


def test_source_flow_plan_validator_rejects_claim_upgrade_and_fabricated_presence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    source_flow = _source_flow(tmp_path / "flows" / "cand-a-fft", candidate_id="cand-a", kernel_id="fft_ifft_ffft")
    source_flow_map = _source_flow_map(
        tmp_path / "source_flow_map.json",
        [{"candidate_id": "cand-a", "kernel_id": "fft_ifft_ffft", "source_flow_dir": str(source_flow)}],
    )
    write_dft_hardware_closure_source_flow_plan(
        run_dir,
        closure_packet_index_path=packet_index,
        source_flow_map_path=source_flow_map,
    )
    plan = _load(run_dir / "dft_hardware_closure_source_flow_plan.json")

    upgraded = json.loads(json.dumps(plan))
    upgraded["hardware_completion_eligible"] = True
    assert validate_dft_hardware_closure_source_flow_plan(upgraded)["valid"] is False

    unit_upgraded = json.loads(json.dumps(plan))
    unit_upgraded["units"][0]["hardware_completion_eligible"] = True
    unit_upgraded["units"][0]["deliverable_complete"] = True
    assert validate_dft_hardware_closure_source_flow_plan(unit_upgraded)["valid"] is False

    fabricated = json.loads(json.dumps(plan))
    fabricated["units"][1]["source_flow_present"] = True
    fabricated["units"][1]["materialization_eligible"] = True
    fabricated["units"][1]["status"] = "source_flow_present_pending_materialization"
    fabricated["source_flow_present_count"] += 1
    fabricated["source_flow_missing_count"] -= 1
    fabricated["blocked_unit_count"] -= 1
    assert validate_dft_hardware_closure_source_flow_plan(fabricated)["valid"] is False


def test_source_flow_plan_cli_writes_artifacts_without_materializing_or_upgrading_claims(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    source_flow = _source_flow(tmp_path / "flows" / "cand-a-fft", candidate_id="cand-a", kernel_id="fft_ifft_ffft")
    source_flow_map = _source_flow_map(
        tmp_path / "source_flow_map.json",
        [{"candidate_id": "cand-a", "kernel_id": "fft_ifft_ffft", "source_flow_dir": str(source_flow)}],
    )

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_source_flow_plan.py",
            "--out",
            str(run_dir),
            "--closure-packet-index",
            str(packet_index),
            "--source-flow-map",
            str(source_flow_map),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert (run_dir / "dft_hardware_closure_source_flow_plan.json").exists()
    assert (run_dir / "dft_hardware_closure_source_flow_plan_validation.json").exists()
    assert (run_dir / "dft_hardware_closure_source_flow_plan_status.json").exists()
    plan = _load(run_dir / "dft_hardware_closure_source_flow_plan.json")
    status = _load(run_dir / "dft_hardware_closure_source_flow_plan_status.json")
    assert status["status"] == "passed"
    assert plan["hardware_completion_eligible"] is False
    assert plan["deliverable_complete"] is False
    assert not (run_dir / "candidate_specific_evidence").exists()


def test_source_flow_plan_is_step5_visible_and_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    packet_index = _packetized_run(run_dir)
    source_flow = _source_flow(tmp_path / "flows" / "cand-a-fft", candidate_id="cand-a", kernel_id="fft_ifft_ffft")
    source_flow_map = _source_flow_map(
        tmp_path / "source_flow_map.json",
        [{"candidate_id": "cand-a", "kernel_id": "fft_ifft_ffft", "source_flow_dir": str(source_flow)}],
    )
    write_dft_hardware_closure_source_flow_plan(
        run_dir,
        closure_packet_index_path=packet_index,
        source_flow_map_path=source_flow_map,
    )
    _write_json(run_dir / "verdict.json", {"run_id": "source-flow-plan-step5", "backend": "step5", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": False})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})

    paths = write_step5_report_artifacts(run_dir, claims=[])
    report = _load(run_dir / paths["final_report_json"])
    campaign_summary = _load(run_dir / paths["campaign_summary"])
    markdown = (run_dir / paths["final_report_markdown"]).read_text(encoding="utf-8")
    section = report["dft_hardware_closure_source_flow_plan"]

    assert section["present"] is True
    assert section["status"] == "fail_closed_hardware_closure_source_flow_plan_present"
    assert section["unit_count"] == 4
    assert section["source_flow_present_count"] == 1
    assert section["source_flow_missing_count"] == 3
    assert section["hardware_completion_eligible"] is False
    assert section["deliverable_complete"] is False
    assert "DFT Hardware Closure Source Flow Plan" in markdown
    assert campaign_summary["dft_hardware_closure_source_flow_plan_summary"]["present"] is True
