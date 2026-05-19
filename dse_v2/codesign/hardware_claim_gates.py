#!/usr/bin/env python3
"""Fail-closed FPGA/ASIC hardware claim evidence gates.

The validator in this module is deliberately data-oriented: it consumes Step3
or Step4 evidence records and decides whether they can support a hardware claim
without running any tools itself.  Missing, unavailable, failed, or
wrong-branch evidence remains an auditable blocker and never becomes pass
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple


HARDWARE_CLAIM_GATE_SCHEMA = "dse.codesign.hardware_claim_gate.v1"

PASS_STATUSES = {
    "pass",
    "passed",
    "success",
    "succeeded",
    "complete",
    "completed",
}
BLOCKER_STATUSES = {
    "blocked",
    "blocked_temporary",
    "missing",
    "not_attempted",
    "tool_unavailable",
    "unavailable",
    "unsupported",
}
FAIL_STATUSES = {"error", "fail", "failed", "timeout"}


@dataclass(frozen=True)
class HardwareClaimStage:
    """One required stage in a hardware-claim evidence chain."""

    stage_id: str
    accepted_evidence_types: Tuple[str, ...]
    description: str


COMMON_ACCELERATED_KERNEL_STAGES: Tuple[HardwareClaimStage, ...] = (
    HardwareClaimStage(
        "golden_correctness",
        ("golden_correctness", "kernel_correctness", "numerical_correctness"),
        (
            "Golden software/reference correctness must pass before "
            "acceleration evidence is claimable."
        ),
    ),
    HardwareClaimStage(
        "hls_or_rtl_sim",
        ("hls_csim", "rtl_sim"),
        (
            "HLS C-simulation or RTL simulation must pass before "
            "synthesis evidence is claimable."
        ),
    ),
    HardwareClaimStage(
        "hls_or_rtl_synth",
        ("hls_csynth", "rtl_synth"),
        (
            "HLS C-synthesis or RTL synthesis must pass before "
            "physical-tool evidence is claimable."
        ),
    ),
)

FPGA_CLAIM_STAGES: Tuple[HardwareClaimStage, ...] = (
    COMMON_ACCELERATED_KERNEL_STAGES
    + (
        HardwareClaimStage(
            "vivado_fpga_synth_or_impl",
            ("vivado_synth", "vivado_impl", "vivado_implementation"),
            "FPGA claims require Vivado synthesis or implementation evidence.",
        ),
    )
)

ASIC_CLAIM_STAGES: Tuple[HardwareClaimStage, ...] = (
    COMMON_ACCELERATED_KERNEL_STAGES
    + (
        HardwareClaimStage(
            "dc_synth",
            ("dc_synth", "dc_synth_timing_area"),
            "ASIC claims require Design Compiler synthesis evidence.",
        ),
        HardwareClaimStage(
            "dc_timing",
            ("dc_timing", "dc_synth_timing_area"),
            "ASIC claims require Design Compiler timing evidence.",
        ),
        HardwareClaimStage(
            "dc_area",
            ("dc_area", "dc_synth_timing_area"),
            "ASIC claims require Design Compiler area evidence.",
        ),
    )
)

HARDWARE_CLAIM_REQUIREMENTS: Dict[str, Tuple[HardwareClaimStage, ...]] = {
    "fpga": FPGA_CLAIM_STAGES,
    "asic": ASIC_CLAIM_STAGES,
    "fpga_asic": FPGA_CLAIM_STAGES + tuple(
        stage
        for stage in ASIC_CLAIM_STAGES
        if stage.stage_id
        not in {item.stage_id for item in COMMON_ACCELERATED_KERNEL_STAGES}
    ),
}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _evidence_type(record: Mapping[str, Any]) -> str:
    explicit = (
        record.get("evidence_type")
        or record.get("artifact_class")
        or record.get("stage")
        or record.get("type")
    )
    if explicit:
        return _norm(explicit)
    tool = _norm(record.get("tool"))
    stage = _norm(record.get("tool_stage") or record.get("stage"))
    if tool in {"vivado", "vivado_hls"}:
        if stage in {
            "implementation",
            "impl",
            "place_route",
            "place_and_route",
        }:
            return "vivado_impl"
        if stage in {"synth", "synthesis"}:
            return "vivado_synth"
    if tool in {"dc", "dc_shell", "design_compiler"}:
        if stage in {"synth_timing_area", "synthesis_timing_area", "ppa"}:
            return "dc_synth_timing_area"
        if stage in {"synth", "synthesis"}:
            return "dc_synth"
        if stage == "timing":
            return "dc_timing"
        if stage == "area":
            return "dc_area"
    return ""


def _status(record: Mapping[str, Any]) -> str:
    status = _norm(record.get("status") or record.get("result"))
    if not status and record.get("passed") is True:
        return "passed"
    if not status and record.get("passed") is False:
        return "failed"
    return status


def _passed(record: Mapping[str, Any]) -> bool:
    return _status(record) in PASS_STATUSES


def _blocked_or_failed(record: Mapping[str, Any]) -> bool:
    status = _status(record)
    return status in BLOCKER_STATUSES or status in FAIL_STATUSES


def _public_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    fields = [
        "evidence_id",
        "artifact",
        "path",
        "tool",
        "tool_stage",
        "status",
        "result",
        "command",
        "environment",
        "failure_evidence",
        "completion_eligible",
    ]
    public = {field: record[field] for field in fields if field in record}
    public["evidence_type"] = _evidence_type(record)
    public["normalized_status"] = _status(record)
    return public


def _stage_result(
    stage: HardwareClaimStage,
    evidence: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    matching = [
        record
        for record in evidence
        if _evidence_type(record) in set(stage.accepted_evidence_types)
    ]
    passing = [record for record in matching if _passed(record)]
    blocking = [
        record
        for record in matching
        if _blocked_or_failed(record) and not _passed(record)
    ]
    return {
        "stage_id": stage.stage_id,
        "description": stage.description,
        "accepted_evidence_types": list(stage.accepted_evidence_types),
        "passed": bool(passing),
        "passing_evidence": [_public_record(record) for record in passing],
        "blocking_evidence": [_public_record(record) for record in blocking],
    }


def validate_hardware_claim_evidence(
    claim_type: str,
    evidence_records: Iterable[Mapping[str, Any]],
    *,
    candidate_id: str | None = None,
    kernel_id: str | None = None,
) -> Dict[str, Any]:
    """Validate whether evidence records satisfy a hardware claim type.

    ``claim_type`` currently supports ``fpga``, ``asic``, and ``fpga_asic``.
    The function is fail-closed: only explicit pass-like statuses on the
    required claim branch satisfy a stage.  DC evidence cannot satisfy FPGA
    claims, Vivado evidence cannot satisfy ASIC claims, and tool-unavailable
    records remain blockers even when they contain a transcript.
    """

    normalized_claim_type = _norm(claim_type)
    if normalized_claim_type not in HARDWARE_CLAIM_REQUIREMENTS:
        raise ValueError(f"unsupported hardware claim type: {claim_type}")

    evidence = [
        record for record in evidence_records if isinstance(record, Mapping)
    ]
    stages = HARDWARE_CLAIM_REQUIREMENTS[normalized_claim_type]
    stage_results = [_stage_result(stage, evidence) for stage in stages]
    missing_stages = [
        result["stage_id"]
        for result in stage_results
        if result["passed"] is not True
    ]
    blocking_evidence = [
        item
        for result in stage_results
        for item in result["blocking_evidence"]
    ]
    evidence_types = {_evidence_type(record) for record in evidence}
    reasons = [
        f"missing_or_blocked_stage:{stage_id}"
        for stage_id in missing_stages
    ]

    if normalized_claim_type == "fpga" and any(
        item.startswith("dc_") for item in evidence_types
    ):
        reasons.append("dc_evidence_does_not_satisfy_fpga_claim")
    if normalized_claim_type == "asic" and any(
        item.startswith("vivado_") for item in evidence_types
    ):
        reasons.append("vivado_evidence_does_not_satisfy_asic_claim")
    if any(
        item["normalized_status"] in BLOCKER_STATUSES
        for item in blocking_evidence
    ):
        reasons.append("tool_unavailable_or_blocked_evidence_is_not_pass")

    has_failed_required_record = any(
        item["normalized_status"] in FAIL_STATUSES
        for item in blocking_evidence
    )
    status = (
        "passed"
        if not missing_stages
        else ("failed" if has_failed_required_record else "blocked")
    )
    trusted = status == "passed"
    return {
        "schema_version": HARDWARE_CLAIM_GATE_SCHEMA,
        "claim_type": normalized_claim_type,
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
        "status": status,
        "trusted": trusted,
        "claim_allowed": trusted,
        "stage_results": stage_results,
        "missing_or_blocked_stages": missing_stages,
        "blocking_evidence": blocking_evidence,
        "reasons": sorted(dict.fromkeys(reasons)),
        "claim_boundary": (
            "Accelerated-kernel hardware claims require golden correctness, "
            "HLS/RTL simulation, HLS/RTL synthesis, and the claim-specific "
            "physical tool branch. Wrong-branch, unavailable, failed, "
            "missing, or diagnostic-only evidence is a blocker, not pass "
            "evidence."
        ),
    }


__all__ = [
    "ASIC_CLAIM_STAGES",
    "BLOCKER_STATUSES",
    "COMMON_ACCELERATED_KERNEL_STAGES",
    "FAIL_STATUSES",
    "FPGA_CLAIM_STAGES",
    "HARDWARE_CLAIM_GATE_SCHEMA",
    "HARDWARE_CLAIM_REQUIREMENTS",
    "HardwareClaimStage",
    "PASS_STATUSES",
    "validate_hardware_claim_evidence",
]
