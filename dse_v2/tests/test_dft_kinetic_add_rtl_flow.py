#!/usr/bin/env python3
"""Direct DFT kinetic-add RTL smoke-flow regressions."""

from __future__ import annotations

import json
import subprocess
import sys

from dse_v2.reference_workloads.dft_hardware_closure_source_flow_plan import (
    build_dft_hardware_closure_source_flow_plan,
)
from dse_v2.reference_workloads.dft_kinetic_add_rtl_flow import (
    KINETIC_ADD_KERNEL_ID,
    build_kinetic_add_evidence_rows,
    initialize_kinetic_add_rtl_flow,
    write_kinetic_add_major_kernel_matrix,
)


def _assert_candidate_source_flow(out_dir, *, candidate_id: str, kernel_id: str) -> None:
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    matrix = json.loads((out_dir / "dft_hardware_evidence_matrix.json").read_text(encoding="utf-8"))

    assert manifest["candidate_id"] == candidate_id
    assert manifest["kernel_id"] == kernel_id
    assert matrix["candidate_id"] == candidate_id
    assert (out_dir / manifest["golden_correctness"]).exists()
    assert all((out_dir / rel_path).exists() for rel_path in manifest["source_files"].values())


def _packet_index_for_source_flow_plan(tmp_path, *, candidate_id: str, kernel_id: str):
    packet = {
        "packet_id": "unit-packet",
        "units": [
            {
                "unit_id": f"{candidate_id}:{kernel_id}",
                "candidate_id": candidate_id,
                "kernel_id": kernel_id,
                "expected_evidence_files": [],
                "expected_evidence_file_count": 0,
            }
        ],
    }
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    index = {
        "packets": [{"packet_id": "unit-packet", "packet_json": {"path": packet_path.name}}],
        "candidate_count": 1,
        "major_kernel_count": 1,
    }
    index_path = tmp_path / "packet_index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    return index_path


def _assert_source_flow_candidate_blockers(tmp_path, *, initialize_flow, candidate_id: str, kernel_id: str) -> None:
    packet_index = _packet_index_for_source_flow_plan(tmp_path, candidate_id=candidate_id, kernel_id=kernel_id)

    missing_candidate_flow = tmp_path / "missing_candidate_flow"
    initialize_flow(missing_candidate_flow)
    missing_plan = build_dft_hardware_closure_source_flow_plan(
        closure_packet_index_path=packet_index,
        source_flow_entries=[f"{candidate_id}:{kernel_id}={missing_candidate_flow}"],
    )
    missing_row = missing_plan["units"][0]
    assert missing_row["source_flow_present"] is False
    assert missing_row["status"] == "blocked_invalid_source_flow_manifest"
    assert "source_flow_candidate_id_missing" in missing_row["blocker_ids"]

    wrong_candidate_flow = tmp_path / "wrong_candidate_flow"
    initialize_flow(wrong_candidate_flow, candidate_id="wrong-release-candidate")
    wrong_plan = build_dft_hardware_closure_source_flow_plan(
        closure_packet_index_path=packet_index,
        source_flow_entries=[f"{candidate_id}:{kernel_id}={wrong_candidate_flow}"],
    )
    wrong_row = wrong_plan["units"][0]
    assert wrong_row["source_flow_present"] is False
    assert wrong_row["status"] == "blocked_wrong_candidate_source_flow"
    assert "source_flow_candidate_id_mismatch" in wrong_row["blocker_ids"]


def test_kinetic_add_flow_writes_sources_and_blocks_before_tool_outputs(tmp_path):
    initialized = initialize_kinetic_add_rtl_flow(tmp_path)

    evidence = build_kinetic_add_evidence_rows(tmp_path)
    matrix = write_kinetic_add_major_kernel_matrix(
        tmp_path,
        candidate_id="kinetic-add-direct-before-tools",
        evidence_rows=evidence["evidence_rows"],
    )

    assert initialized["manifest"]["kernel_id"] == KINETIC_ADD_KERNEL_ID
    assert (tmp_path / "kinetic_add.v").exists()
    assert (tmp_path / "tb_kinetic_add.v").exists()
    assert (tmp_path / "vivado_synth.tcl").exists()
    assert (tmp_path / "dc_synth.tcl").exists()
    assert evidence["fpga_gate_candidate"] is False
    assert evidence["asic_gate_candidate"] is False
    assert matrix["status"] == "blocked"
    kinetic = next(row for row in matrix["kernel_rows"] if row["kernel_id"] == KINETIC_ADD_KERNEL_ID)
    assert kinetic["claim_allowed"] is False
    assert "vivado_fpga_synth_or_impl" in kinetic["hardware_claim_gate"]["missing_or_blocked_stages"]


def test_kinetic_add_flow_passes_fpga_microkernel_gate_with_realistic_logs_and_keeps_dc_blocked(tmp_path):
    initialize_kinetic_add_rtl_flow(tmp_path)
    (tmp_path / "vcs_run.log").write_text("KINETIC_ADD_RTL_PASS re=39 im=-7\n", encoding="utf-8")
    (tmp_path / "vivado_stdout.log").write_text("synth_design completed successfully\n", encoding="utf-8")
    (tmp_path / "vivado_utilization.rpt").write_text("Slice LUTs | 42\nDSPs | 2\n", encoding="utf-8")
    (tmp_path / "dc_stdout.log").write_text(
        "Error: Could not read the following target libraries: your_library.db\n",
        encoding="utf-8",
    )
    (tmp_path / "dc_area.rpt").write_text("Library(s) Used:\n    gtech\nunmapped logic\n", encoding="utf-8")

    evidence = build_kinetic_add_evidence_rows(tmp_path)
    matrix = write_kinetic_add_major_kernel_matrix(
        tmp_path,
        candidate_id="kinetic-add-direct-fpga-smoke",
        evidence_rows=evidence["evidence_rows"],
    )

    assert evidence["fpga_gate_candidate"] is True
    assert evidence["asic_gate_candidate"] is False
    assert evidence["asic_attempt_evidence_rows"][0]["status"] == "blocked"
    assert matrix["status"] == "passed"
    kinetic = next(row for row in matrix["kernel_rows"] if row["kernel_id"] == KINETIC_ADD_KERNEL_ID)
    assert kinetic["claim_allowed"] is True
    assert kinetic["hardware_claim_gate"]["missing_or_blocked_stages"] == []
    assert "not full-SCF completion" in matrix["claim_boundary"]


def test_kinetic_add_cli_can_emit_blocked_local_artifacts_without_downgrading(tmp_path):
    candidate_id = "release-cand-kinetic-add"
    completed = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_dft_kinetic_add_rtl_flow.py",
            "--out",
            str(tmp_path),
            "--candidate-id",
            candidate_id,
            "--skip-remote",
            "--allow-blocked",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode == 0
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "blocked"
    _assert_candidate_source_flow(tmp_path, candidate_id=candidate_id, kernel_id=KINETIC_ADD_KERNEL_ID)
    assert "ASIC DC artifacts from this single-kernel flow are candidate-specific raw evidence only" in status[
        "claim_boundary"
    ]
    assert (tmp_path / "kinetic_add_rtl_evidence_summary.json").exists()
    assert (tmp_path / "dft_hardware_evidence_matrix.json").exists()

def test_kinetic_add_asic_dc_blocks_when_valid_reports_target_library_but_ddc_missing(tmp_path):
    initialize_kinetic_add_rtl_flow(tmp_path)
    (tmp_path / "vcs_run.log").write_text("KINETIC_ADD_RTL_PASS re=39 im=-7\n", encoding="utf-8")
    (tmp_path / "vivado_stdout.log").write_text("synth_design completed successfully\n", encoding="utf-8")
    (tmp_path / "vivado_utilization.rpt").write_text("LUTs | 32\nDSPs | 2\n", encoding="utf-8")
    (tmp_path / "dc_stdout.log").write_text(
        "Using target library /libs/fsa0a_c_generic_core_tt1p8v25c.db\ncompile completed\n",
        encoding="utf-8",
    )
    (tmp_path / "dc_area.rpt").write_text(
        "Library(s) Used:\n    fsa0a_c_generic_core_tt1p8v25c\nTotal cell area: 123.456\n",
        encoding="utf-8",
    )
    (tmp_path / "dc_timing.rpt").write_text(
        "Startpoint: in0\nEndpoint: out0\nslack (MET) 0.120\ndata arrival time 9.880\n",
        encoding="utf-8",
    )

    evidence = build_kinetic_add_evidence_rows(tmp_path)
    asic_row = evidence["asic_attempt_evidence_rows"][0]

    assert evidence["fpga_gate_candidate"] is True
    assert evidence["asic_gate_candidate"] is False
    assert asic_row["status"] == "blocked"
    assert "dc_synth.ddc missing" in asic_row["failure_evidence"]
    assert asic_row["completion_eligible"] is False
    assert asic_row["dc_target_library_discovery"] == "real_target_library_present"
    assert asic_row["dc_target_library_required"] == "fsa0a_c_generic_core_*"
    assert not (tmp_path / "dc_synth.ddc").exists()




def test_kinetic_add_source_flow_plan_blocks_missing_or_wrong_candidate_id(tmp_path):
    _assert_source_flow_candidate_blockers(
        tmp_path,
        initialize_flow=initialize_kinetic_add_rtl_flow,
        candidate_id="release-cand-kinetic-add",
        kernel_id=KINETIC_ADD_KERNEL_ID,
    )
