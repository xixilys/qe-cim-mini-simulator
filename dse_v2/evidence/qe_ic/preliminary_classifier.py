#!/usr/bin/env python3
"""Preliminary QE-IC FPGA/hybrid-vs-GPU opportunity classifier.

This module is intentionally a *preliminary reporting adapter* over the existing
claim-gated opportunity report. It answers the advisor-facing seven-day question
without upgrading model/high-fidelity side evidence into a final FPGA or hybrid
hardware superiority claim.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

ADVISOR_LABELS = {
    "fpga_hybrid_stronger",
    "fpga_hybrid_weaker",
    "gpu_dominant",
    "fundamental_no_opportunity",
}

PRELIMINARY_LABELS = ADVISOR_LABELS | {"insufficient_evidence"}

OPPORTUNITY_FOUND_VERDICTS = {
    "fpga_opportunity_found",
    "hybrid_opportunity_found",
}

GPU_DOMINANT_SIGNALS = {
    "gpu_dominant_no_fpga_opportunity",
    "gpu_utilization_high",
    "dense_gpu_dominant",
}

STRUCTURAL_NO_OPPORTUNITY_SIGNALS = {
    "structural_upper_bound_below_threshold",
    "host_bound_full_scf_dominates",
    "low_removable_fraction",
    "nonremovable_workflow_fraction_dominates",
    "full_scf_control_path_dominates",
    "fpga_upper_bound_too_low",
    "hybrid_upper_bound_too_low",
}

EVIDENCE_MISSING_BLOCKERS = {
    "gpu_baseline_missing",
    "fixture_only_evidence",
    "l1_only_insufficient",
    "kernel_only_insufficient",
    "repeated_runs_missing",
    "high_fidelity_provenance_missing",
    "workflow_speedup_missing",
}

CLAIM_BOUNDARY = (
    "not_final_hardware_superiority_claim: preliminary labels summarize current "
    "GPU-baseline and FPGA/hybrid evidence for triage only. Final FPGA/hybrid "
    "claims still require workload-representative full-SCF accounting plus the "
    "tool-specific correctness, synthesis, implementation, and timing gates."
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _string_values(values: Iterable[Any]) -> list[str]:
    return [str(value) for value in values if str(value)]


def _record_reasons(record: Mapping[str, Any]) -> list[str]:
    return _string_values(
        [record.get("verdict")]
        + _as_list(record.get("failure_reasons"))
        + _as_list(record.get("claim_blockers"))
    )


def _dominant_reasons(records: list[Mapping[str, Any]], system_conclusion: Mapping[str, Any]) -> list[str]:
    counter: Counter[str] = Counter()
    for record in records:
        counter.update(_record_reasons(record))
    counter.update(_string_values(_as_list(system_conclusion.get("dominant_failure_modes"))))
    return [reason for reason, _count in counter.most_common()]


def _best_record(records: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    scored: list[tuple[float, bool, Mapping[str, Any]]] = []
    for record in records:
        speedup = _num(record.get("speedup_vs_gpu_mean"))
        if speedup is None:
            continue
        scored.append((speedup, record.get("claim_allowed") is True, record))
    if not scored:
        return records[0] if records else None
    scored.sort(key=lambda row: (row[1], row[0]), reverse=True)
    return scored[0][2]


def _evidence_tier(report: Mapping[str, Any], records: list[Mapping[str, Any]]) -> str:
    baseline = _as_mapping(report.get("gpu_baseline_summary"))
    candidate = _as_mapping(report.get("candidate_evidence_summary"))
    if baseline.get("measurements_are_real") is not True or candidate.get("results_are_real") is not True:
        return "insufficient_evidence"
    levels = {
        str(record.get("evidence_level"))
        for record in records
        if isinstance(record, Mapping) and record.get("evidence_level")
    }
    statuses = {
        str(record.get("evidence_status"))
        for record in records
        if isinstance(record, Mapping) and record.get("evidence_status")
    }
    if "real_qe_run" in levels and "measured" in statuses:
        return "measured_workflow_preliminary"
    if levels & {"gem5_systemc", "systemc_timing", "trace_replay", "vivado_resource_timing"}:
        return "high_fidelity_preliminary"
    if "l1_estimate_only" in levels:
        return "screening_only"
    return "unclassified_preliminary"


def _initial_blockers(report: Mapping[str, Any], records: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    baseline = _as_mapping(report.get("gpu_baseline_summary"))
    candidate = _as_mapping(report.get("candidate_evidence_summary"))
    system_conclusion = _as_mapping(report.get("system_conclusion"))
    if baseline.get("measurements_are_real") is not True or int(baseline.get("baseline_record_count") or 0) <= 0:
        blockers.append("measured_gpu_baseline_missing")
    if candidate.get("results_are_real") is not True or int(candidate.get("candidate_result_count") or 0) <= 0:
        blockers.append("real_or_high_fidelity_candidate_evidence_missing")
    for missing in _as_list(system_conclusion.get("what_evidence_is_missing")):
        blockers.append(f"missing:{missing}")
    if not records:
        blockers.append("opportunity_records_missing")
    for record in records:
        for blocker in _as_list(record.get("claim_blockers")):
            if str(blocker) in EVIDENCE_MISSING_BLOCKERS:
                blockers.append(str(blocker))
    return list(dict.fromkeys(blockers))


def _required_next_evidence(label: str, blockers: list[str], dominant_reasons: list[str]) -> list[str]:
    required: list[str] = []
    if blockers:
        required.append("replace missing/fixture evidence with measured GPU baseline and real or high-fidelity candidate records")
    if label == "fpga_hybrid_stronger":
        required.extend(
            [
                "run representative full-SCF repetitions with host, transfer, synchronization, and convergence accounting",
                "close claimed accelerated kernels through golden correctness plus HLS/RTL simulation and synthesis gates",
                "run Vivado implementation for FPGA claims or DC timing/area for ASIC claims before final superiority wording",
            ]
        )
    elif label == "fpga_hybrid_weaker":
        required.append("check whether alternative candidate families or overlap schedules can reduce transfer/workflow overhead before final rejection")
    elif label == "gpu_dominant":
        required.append("confirm GPU utilization, memory bandwidth, and transfer counters on the representative deck across repeated runs")
    elif label == "fundamental_no_opportunity":
        required.append("derive and document a structural upper bound over removable full-SCF time before treating this as fundamental")
    if "transfer_overhead_dominates" in dominant_reasons:
        required.append("measure or model host-device/interconnect transfer costs at full-SCF granularity")
    if "workflow_overhead_dominates" in dominant_reasons:
        required.append("account for SCF control, diagonalization, mixing, synchronization, and launch overheads end-to-end")
    return list(dict.fromkeys(required))


def _confidence(label: str, evidence_tier: str, blockers: list[str], records: list[Mapping[str, Any]]) -> str:
    if label == "insufficient_evidence" or blockers:
        return "low"
    if evidence_tier == "measured_workflow_preliminary":
        return "high"
    if evidence_tier == "high_fidelity_preliminary":
        return "medium"
    if label == "fundamental_no_opportunity" and records:
        return "medium"
    return "low"


def _all_candidate_speedups_below_one(records: list[Mapping[str, Any]]) -> bool:
    speedups = [_num(record.get("speedup_vs_gpu_mean")) for record in records]
    numeric = [value for value in speedups if value is not None]
    return bool(numeric) and all(value < 1.0 for value in numeric)


def classify_preliminary_opportunity(opportunity_report: Mapping[str, Any]) -> dict[str, Any]:
    """Classify current evidence into advisor-facing preliminary opportunity labels.

    The classifier is deliberately fail-closed: if measured GPU baseline or real /
    high-fidelity candidate evidence is missing, it returns ``insufficient_evidence``
    instead of forcing one of the four advisor labels.
    """

    report = _as_mapping(opportunity_report)
    records = [row for row in _as_list(report.get("opportunity_records")) if isinstance(row, Mapping)]
    system_conclusion = _as_mapping(report.get("system_conclusion"))
    blockers = _initial_blockers(report, records)
    reasons = _dominant_reasons(records, system_conclusion)
    reason_set = set(reasons)
    evidence_tier = _evidence_tier(report, records)
    best = _best_record(records)

    if blockers:
        label = "insufficient_evidence"
    elif any(
        record.get("claim_allowed") is True and record.get("verdict") in OPPORTUNITY_FOUND_VERDICTS
        for record in records
    ):
        label = "fpga_hybrid_stronger"
    elif reason_set & STRUCTURAL_NO_OPPORTUNITY_SIGNALS and not (
        reason_set - STRUCTURAL_NO_OPPORTUNITY_SIGNALS - {"fpga_or_hybrid_inconclusive"}
    ):
        label = "fundamental_no_opportunity"
    elif reason_set & GPU_DOMINANT_SIGNALS:
        label = "gpu_dominant"
    elif _all_candidate_speedups_below_one(records):
        label = "fpga_hybrid_weaker"
    elif reason_set & STRUCTURAL_NO_OPPORTUNITY_SIGNALS:
        label = "fundamental_no_opportunity"
    else:
        label = "insufficient_evidence"
        blockers.append("preliminary_label_not_resolved")

    if label == "fundamental_no_opportunity" and not (reason_set & STRUCTURAL_NO_OPPORTUNITY_SIGNALS):
        blockers.append("no_strong_fundamental_claim_without_structural_evidence")
        label = "insufficient_evidence"

    confidence = _confidence(label, evidence_tier, blockers, records)
    required_next_evidence = _required_next_evidence(label, blockers, reasons)
    best_speedup = _num(best.get("speedup_vs_gpu_mean")) if best else None

    return {
        "schema_version": "dse.qe_ic.preliminary_opportunity_classification.v1",
        "preliminary_label": label,
        "advisor_labels_supported": label in ADVISOR_LABELS,
        "confidence": confidence,
        "evidence_tier": evidence_tier,
        "best_candidate_id": best.get("candidate_id") if best else None,
        "best_target_type": best.get("target_type") if best else None,
        "best_speedup_vs_gpu": best_speedup,
        "record_count": len(records),
        "dominant_reasons": reasons,
        "blockers": list(dict.fromkeys(blockers)),
        "required_next_evidence": required_next_evidence,
        "claim_gate_passed": label == "fpga_hybrid_stronger",
        "final_claim_allowed": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
