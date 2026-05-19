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


def test_matching_fpga_and_asic_branches_can_pass_their_own_claims():
    fpga = validate_hardware_claim_evidence(
        "fpga",
        [
            *_common_passed_kernel_evidence(),
            {
                "evidence_type": "vivado_synth",
                "status": "passed",
                "artifact": "vivado_synth.rpt",
            },
        ],
    )
    asic = validate_hardware_claim_evidence(
        "asic",
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

    assert fpga["status"] == "passed"
    assert fpga["trusted"] is True
    assert asic["status"] == "passed"
    assert asic["trusted"] is True
