"""Claim-specific FPGA/ASIC hardware evidence gate regressions."""

from __future__ import annotations

from dse_v2.codesign.hardware_claim_gates import (
    validate_hardware_claim_evidence,
)


def _common_passed_kernel_evidence():
    return [
        {
            "evidence_type": "golden_correctness",
            "status": "passed",
            "artifact": "golden.json",
        },
        {
            "evidence_type": "hls_csim",
            "status": "passed",
            "artifact": "hls_csim.log",
        },
        {
            "evidence_type": "hls_csynth",
            "status": "passed",
            "artifact": "hls_csynth.rpt",
        },
    ]


def test_unavailable_tool_log_is_blocker_not_pass():
    result = validate_hardware_claim_evidence(
        "fpga",
        [
            *_common_passed_kernel_evidence(),
            {
                "evidence_type": "vivado_synth",
                "status": "unavailable",
                "tool": "vivado",
                "command": "LC_ALL=C LANG=C vivado -version",
                "environment": "IC VM",
                "failure_evidence": (
                    "vivado command unavailable in the probed shell"
                ),
                "completion_eligible": False,
            },
        ],
        candidate_id="cand-fpga",
        kernel_id="fft3d",
    )

    assert result["status"] == "blocked"
    assert result["trusted"] is False
    assert result["claim_allowed"] is False
    assert result["missing_or_blocked_stages"] == ["vivado_fpga_synth_or_impl"]
    assert (
        "tool_unavailable_or_blocked_evidence_is_not_pass"
        in result["reasons"]
    )
    assert result["blocking_evidence"][0]["command"] == (
        "LC_ALL=C LANG=C vivado -version"
    )
    assert result["blocking_evidence"][0]["completion_eligible"] is False


def test_dc_only_rejected_for_fpga_claim():
    result = validate_hardware_claim_evidence(
        "fpga",
        [
            *_common_passed_kernel_evidence(),
            {
                "evidence_type": "dc_synth_timing_area",
                "status": "passed",
                "tool": "dc_shell",
                "artifact": "dc_ppa.rpt",
            },
        ],
    )

    assert result["status"] == "blocked"
    assert result["trusted"] is False
    assert result["claim_allowed"] is False
    assert result["missing_or_blocked_stages"] == ["vivado_fpga_synth_or_impl"]
    assert "dc_evidence_does_not_satisfy_fpga_claim" in result["reasons"]


def test_vivado_only_rejected_for_asic_claim():
    result = validate_hardware_claim_evidence(
        "asic",
        [
            *_common_passed_kernel_evidence(),
            {
                "evidence_type": "vivado_impl",
                "status": "passed",
                "tool": "vivado",
                "artifact": "vivado_impl.rpt",
            },
        ],
    )

    assert result["status"] == "blocked"
    assert result["trusted"] is False
    assert result["claim_allowed"] is False
    assert result["missing_or_blocked_stages"] == [
        "dc_synth",
        "dc_timing",
        "dc_area",
    ]
    assert "vivado_evidence_does_not_satisfy_asic_claim" in result["reasons"]


def _dc_passed_kernel_evidence():
    return {
        "evidence_type": "dc_synth_timing_area",
        "status": "passed",
        "tool": "dc_shell",
        "artifact": "dc_qor.rpt",
        "dc_synth_ddc": "dc_synth.ddc",
        "dc_timing_report": "dc_timing.rpt",
        "dc_area_report": "dc_area.rpt",
        "dc_target_library_discovery": "real_target_library_present",
        "dc_target_libraries": ["fsa0a_c_generic_core_tt1p8v25c"],
    }


def test_asic_claim_requires_dc_synth_ddc_and_real_target_library():
    result = validate_hardware_claim_evidence(
        "asic",
        [
            *_common_passed_kernel_evidence(),
            {
                "evidence_type": "dc_synth_timing_area",
                "status": "passed",
                "tool": "dc_shell",
                "artifact": "dc_ppa.rpt",
                "dc_timing_report": "dc_timing.rpt",
                "dc_area_report": "dc_area.rpt",
            },
        ],
    )

    assert result["status"] == "blocked"
    assert result["trusted"] is False
    assert result["claim_allowed"] is False
    assert result["missing_or_blocked_stages"] == [
        "dc_synth",
        "dc_timing",
        "dc_area",
    ]
    assert "asic_dc_synth_ddc_required" in result["reasons"]
    assert "asic_dc_target_library_evidence_required" in result["reasons"]


def test_matching_fpga_and_asic_branches_can_pass_their_own_claims():
    fpga = validate_hardware_claim_evidence(
        "fpga",
        [
            *_common_passed_kernel_evidence(),
            {
                "evidence_type": "vivado_impl",
                "status": "passed",
                "artifact": "vivado_route_status.rpt",
            },
        ],
    )
    asic = validate_hardware_claim_evidence(
        "asic",
        [
            *_common_passed_kernel_evidence(),
            _dc_passed_kernel_evidence(),
        ],
    )

    assert fpga["status"] == "passed"
    assert fpga["trusted"] is True
    assert asic["status"] == "passed"
    assert asic["trusted"] is True


def test_fpga_claim_blocks_vivado_synth_only_without_route_completion():
    result = validate_hardware_claim_evidence(
        "fpga",
        [
            *_common_passed_kernel_evidence(),
            {
                "evidence_type": "vivado_synth",
                "status": "passed",
                "artifact": "vivado_utilization.rpt",
            },
        ],
    )

    assert result["status"] == "blocked"
    assert result["claim_allowed"] is False
    assert result["missing_or_blocked_stages"] == ["vivado_fpga_synth_or_impl"]
    assert "vivado_implementation_route_required" in result["reasons"]


def test_fpga_claim_allows_vivado_synth_row_with_explicit_route_completion():
    result = validate_hardware_claim_evidence(
        "fpga",
        [
            *_common_passed_kernel_evidence(),
            {
                "evidence_type": "vivado_synth",
                "status": "passed",
                "artifact": "vivado_utilization.rpt",
                "implementation_route_completed": True,
            },
        ],
    )

    assert result["status"] == "passed"
    assert result["trusted"] is True


def test_claim_gate_rejects_cross_kernel_evidence_substitution():
    result = validate_hardware_claim_evidence(
        "fpga",
        [
            {
                "kernel_id": "nonlocal_projector",
                "evidence_type": "golden_correctness",
                "status": "passed",
            },
            {
                "kernel_id": "nonlocal_projector",
                "evidence_type": "hls_csim",
                "status": "passed",
            },
            {
                "kernel_id": "nonlocal_projector",
                "evidence_type": "hls_csynth",
                "status": "passed",
            },
            {
                "kernel_id": "fft_ifft_ffft",
                "evidence_type": "vivado_synth",
                "status": "passed",
            },
        ],
        kernel_id="nonlocal_projector",
    )

    assert result["status"] == "blocked"
    assert result["claim_allowed"] is False
    assert result["missing_or_blocked_stages"] == ["vivado_fpga_synth_or_impl"]
    assert "cross_kernel_evidence_ignored" in result["reasons"]
    assert result["ignored_kernel_evidence"][0]["evidence_type"] == "vivado_synth"
