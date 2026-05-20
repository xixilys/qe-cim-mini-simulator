#!/usr/bin/env python3
"""Targeted checks for the DFT FFT/iFFT/fFFT RTL evidence lane."""

from __future__ import annotations

import json

from dse_v2.codesign.dft_hardware_evidence import build_major_kernel_evidence_matrix
from dse_v2.reference_workloads.dft_hardware_closure_source_flow_plan import (
    build_dft_hardware_closure_source_flow_plan,
)
from dse_v2.reference_workloads.dft_fft_ifft_rtl_flow import (
    FFT_IFFT_KERNEL_ID,
    build_fft_ifft_ffft_evidence_rows,
    default_kernel_dispositions,
    initialize_fft_ifft_ffft_rtl_flow,
    write_fft_ifft_ffft_major_kernel_matrix,
)
from dse_v2.scripts.dse.run_dft_fft_ifft_rtl_flow import main as run_fft_ifft_flow


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


def test_fft_ifft_rtl_flow_generates_deterministic_sources_and_golden(tmp_path):
    initialized = initialize_fft_ifft_ffft_rtl_flow(tmp_path)

    assert initialized["manifest"]["kernel_id"] == FFT_IFFT_KERNEL_ID
    assert (tmp_path / "fft_ifft_ffft.v").exists()
    assert (tmp_path / "tb_fft_ifft_ffft.v").exists()
    assert "module fft_ifft_ffft" in (tmp_path / "fft_ifft_ffft.v").read_text(encoding="utf-8")
    assert "FFT_IFFT_FFFT_RTL_PASS" in (tmp_path / "tb_fft_ifft_ffft.v").read_text(encoding="utf-8")
    golden = json.loads((tmp_path / "golden_correctness.json").read_text(encoding="utf-8"))
    assert golden["kernel_id"] == FFT_IFFT_KERNEL_ID
    assert golden["status"] == "passed"
    assert golden["cases"]["fft_complex_4pt"]["expected"] == [[0, 0], [16, 0], [0, 0], [0, 0]]
    assert golden["cases"]["ifft_complex_4pt"]["expected"] == [[4, 0], [0, 4], [-4, 0], [0, -4]]
    assert golden["cases"]["ffft_real_4pt"]["expected"] == [[10, 0], [-2, 2], [-2, 0], [-2, -2]]


def test_fft_ifft_rtl_flow_is_fail_closed_before_remote_tool_outputs(tmp_path):
    initialize_fft_ifft_ffft_rtl_flow(tmp_path)

    evidence = build_fft_ifft_ffft_evidence_rows(tmp_path)
    matrix = write_fft_ifft_ffft_major_kernel_matrix(
        tmp_path,
        candidate_id="unit-fft-before-tools",
        evidence_rows=evidence["evidence_rows"],
    )

    assert {row["kernel_id"] for row in evidence["evidence_rows"]} == {FFT_IFFT_KERNEL_ID}
    assert evidence["fpga_gate_candidate"] is False
    assert evidence["asic_gate_candidate"] is False
    assert evidence["asic_attempt_evidence_rows"][0]["status"] == "blocked"
    assert matrix["status"] == "blocked"
    fft_row = next(row for row in matrix["kernel_rows"] if row["kernel_id"] == FFT_IFFT_KERNEL_ID)
    assert fft_row["hardware_claim_gate"]["missing_or_blocked_stages"] == [
        "hls_or_rtl_sim",
        "hls_or_rtl_synth",
        "vivado_fpga_synth_or_impl",
    ]


def test_fft_ifft_rtl_flow_builds_fpga_matrix_and_cannot_satisfy_other_kernel_ids(tmp_path):
    initialize_fft_ifft_ffft_rtl_flow(tmp_path)
    (tmp_path / "vcs_run.log").write_text("FFT_IFFT_FFFT_RTL_PASS fft_ifft_ffft\n", encoding="utf-8")
    (tmp_path / "vivado_stdout.log").write_text("synth_design completed successfully\nROUTE_DESIGN COMPLETE\n", encoding="utf-8")
    (tmp_path / "vivado_utilization.rpt").write_text("LUTs | 32\n", encoding="utf-8")
    (tmp_path / "dc_stdout.log").write_text(
        "Error: Could not read the following target libraries: your_library.db\n",
        encoding="utf-8",
    )
    (tmp_path / "dc_area.rpt").write_text("Library(s) Used:\n    gtech\nunmapped logic\n", encoding="utf-8")

    evidence = build_fft_ifft_ffft_evidence_rows(tmp_path)
    matrix = write_fft_ifft_ffft_major_kernel_matrix(
        tmp_path,
        candidate_id="unit-fft-fpga-smoke",
        evidence_rows=evidence["evidence_rows"],
    )

    assert evidence["fpga_gate_candidate"] is True
    assert evidence["asic_gate_candidate"] is False
    assert matrix["status"] == "passed"
    fft_row = next(row for row in matrix["kernel_rows"] if row["kernel_id"] == FFT_IFFT_KERNEL_ID)
    assert fft_row["claim_allowed"] is True
    kinetic_dispositions = default_kernel_dispositions(accelerated_kernel_id="kinetic_add")
    kinetic_matrix = build_major_kernel_evidence_matrix(
        kinetic_dispositions,
        evidence_rows=evidence["evidence_rows"],
        candidate_id="unit-fft-not-kinetic",
    )
    kinetic_row = next(row for row in kinetic_matrix["kernel_rows"] if row["kernel_id"] == "kinetic_add")
    assert kinetic_row["status"] == "blocked"
    assert kinetic_row["hardware_claim_gate"]["missing_or_blocked_stages"] == [
        "golden_correctness",
        "hls_or_rtl_sim",
        "hls_or_rtl_synth",
        "vivado_fpga_synth_or_impl",
    ]


def test_fft_ifft_rtl_cli_writes_replayable_blocked_status(tmp_path):
    out_dir = tmp_path / "run"

    result = run_fft_ifft_flow(
        [
            "--out",
            str(out_dir),
            "--candidate-id",
            "release-cand-fft",
            "--skip-remote",
            "--allow-blocked",
        ]
    )

    assert result == 0
    status = json.loads((out_dir / "status.json").read_text(encoding="utf-8"))
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert status["status"] == "blocked"
    assert status["attempts"] == []
    _assert_candidate_source_flow(out_dir, candidate_id="release-cand-fft", kernel_id=FFT_IFFT_KERNEL_ID)
    assert manifest["candidate_id"] == "release-cand-fft"
    assert manifest["kernel_id"] == FFT_IFFT_KERNEL_ID
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "evidence_rows.json").exists()
    assert (out_dir / "dft_hardware_evidence_matrix.json").exists()

def test_fft_ifft_asic_dc_blocks_when_valid_reports_target_library_but_ddc_missing(tmp_path):
    initialize_fft_ifft_ffft_rtl_flow(tmp_path)
    (tmp_path / "vcs_run.log").write_text("FFT_IFFT_FFFT_RTL_PASS fft_ifft_ffft\n", encoding="utf-8")
    (tmp_path / "vivado_stdout.log").write_text("synth_design completed successfully\nROUTE_DESIGN COMPLETE\n", encoding="utf-8")
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

    evidence = build_fft_ifft_ffft_evidence_rows(tmp_path)
    asic_row = evidence["asic_attempt_evidence_rows"][0]

    assert evidence["fpga_gate_candidate"] is True
    assert evidence["asic_gate_candidate"] is False
    assert asic_row["status"] == "blocked"
    assert "dc_synth.ddc missing" in asic_row["failure_evidence"]
    assert asic_row["completion_eligible"] is False
    assert asic_row["dc_target_library_discovery"] == "real_target_library_present"
    assert asic_row["dc_target_library_required"] == "fsa0a_c_generic_core_*"
    assert not (tmp_path / "dc_synth.ddc").exists()



def test_fft_ifft_source_flow_plan_blocks_missing_or_wrong_candidate_id(tmp_path):
    _assert_source_flow_candidate_blockers(
        tmp_path,
        initialize_flow=initialize_fft_ifft_ffft_rtl_flow,
        candidate_id="release-cand-fft-ifft",
        kernel_id=FFT_IFFT_KERNEL_ID,
    )
