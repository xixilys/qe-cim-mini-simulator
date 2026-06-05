#!/usr/bin/env python3
"""Deterministic analytical L1 cost model for QE-IC candidates."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from dse_v2.evaluation.qe_ic.l1_cost_model.schema import RESULT_CLAIM_BOUNDARY


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a number into a closed interval."""

    return max(lo, min(hi, value))


def num(value: Any, default: float = 0.0) -> float:
    """Return a numeric value without accepting bool."""

    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def _result_id(request_id: str, candidate_id: str) -> str:
    digest = hashlib.sha1(f"{request_id}|{candidate_id}".encode("utf-8")).hexdigest()[:12]
    return f"qeic_l5a_l1_result_{digest}"


def _motif_profile_index(motif_profile: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    index: dict[tuple[str, str], Mapping[str, Any]] = {}
    for group in motif_profile.get("family_target_profiles", []):
        if not isinstance(group, Mapping):
            continue
        family_id = str(group.get("workload_family_id", ""))
        for motif in group.get("motif_profiles", []):
            if isinstance(motif, Mapping):
                index[(family_id, str(motif.get("motif_id", "")))] = motif
    return index


def _candidate_template_family(candidate: Mapping[str, Any]) -> str:
    parameters = candidate.get("candidate_parameters")
    if isinstance(parameters, Mapping):
        return str(parameters.get("template_family", ""))
    return ""


def _resource_pressure(candidate: Mapping[str, Any], record: Mapping[str, Any]) -> float:
    risk = record.get("risk") if isinstance(record.get("risk"), Mapping) else {}
    template_family = _candidate_template_family(candidate)
    base = num(risk.get("fpga_resource_risk"), num(candidate.get("candidate_parameters", {}).get("risk_score"), 0.5))
    if template_family in {"fpga_fft", "fpga_projector"}:
        base += 0.08
    if template_family in {"hybrid_dma", "hybrid_memory"}:
        base -= 0.05
    return clamp(base)


def _estimate_components(
    *,
    candidate: Mapping[str, Any],
    source_record: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
) -> dict[str, float]:
    upper = source_record.get("upper_bound") if isinstance(source_record.get("upper_bound"), Mapping) else {}
    risk = source_record.get("risk") if isinstance(source_record.get("risk"), Mapping) else {}
    params = candidate.get("candidate_parameters") if isinstance(candidate.get("candidate_parameters"), Mapping) else {}
    motif_time_ms = num(upper.get("motif_time_ms"), num(motif_profile.get("time_ms"), 1.0))
    family_total_time_ms = max(num(upper.get("family_total_time_ms"), motif_time_ms), 1e-9)
    transfer_ms = max(num(upper.get("estimated_transfer_time_ms")), 0.0)
    net_gain_ratio = num(upper.get("estimated_net_gain_ratio"), num(params.get("estimated_net_gain_ratio")))
    removable_ms = max(num(upper.get("estimated_removable_time_ms")), motif_time_ms * clamp(net_gain_ratio * family_total_time_ms / max(motif_time_ms, 1e-9)))
    retained_work_ms = max(motif_time_ms - removable_ms, motif_time_ms * 0.25)
    memory_bytes = max(num(motif_profile.get("memory_movement_bytes")), 0.0)
    communication_bytes = max(num(motif_profile.get("communication_bytes")), 0.0)
    memory_time_ms = min(motif_time_ms * 0.50, memory_bytes / 1.0e9)
    communication_time_ms = min(motif_time_ms * 0.40, communication_bytes / 8.0e8)
    resource_pressure = _resource_pressure(candidate, source_record)
    resource_penalty_ms = motif_time_ms * 0.12 * resource_pressure
    compute_time_ms = max(retained_work_ms - 0.35 * memory_time_ms - 0.25 * communication_time_ms, motif_time_ms * 0.05)
    estimated_latency_ms = max(
        compute_time_ms
        + memory_time_ms
        + communication_time_ms
        + transfer_ms
        + resource_penalty_ms,
        1e-9,
    )
    speedup_vs_gpu = motif_time_ms / estimated_latency_ms if estimated_latency_ms > 0 else 0.0
    transfer_risk = clamp(
        max(
            num(risk.get("transfer_overhead_risk")),
            transfer_ms / max(motif_time_ms, 1e-9),
        )
    )
    profile_quality_risk = clamp(num(risk.get("profile_quality_risk"), num(params.get("profile_quality_risk"), 0.5)))
    model_uncertainty_risk = clamp(0.20 + 0.50 * profile_quality_risk + 0.20 * resource_pressure)
    model_confidence = clamp(1.0 - model_uncertainty_risk)
    return {
        "estimated_latency_ms": estimated_latency_ms,
        "estimated_speedup_vs_gpu_baseline": speedup_vs_gpu,
        "estimated_net_gain_ratio": net_gain_ratio,
        "estimated_transfer_overhead_ms": transfer_ms,
        "estimated_compute_time_ms": compute_time_ms,
        "estimated_memory_time_ms": memory_time_ms,
        "estimated_communication_time_ms": communication_time_ms,
        "estimated_resource_pressure": resource_pressure,
        "estimated_model_confidence": model_confidence,
        "transfer_risk": transfer_risk,
        "profile_quality_risk": profile_quality_risk,
        "model_uncertainty_risk": model_uncertainty_risk,
    }


def _bottlenecks(estimate: Mapping[str, float], risk: Mapping[str, float]) -> dict[str, Any]:
    candidates = {
        "compute": num(estimate.get("estimated_compute_time_ms")),
        "memory": num(estimate.get("estimated_memory_time_ms")),
        "communication": num(estimate.get("estimated_communication_time_ms")),
        "transfer": num(estimate.get("estimated_transfer_overhead_ms")),
        "resource": num(estimate.get("estimated_latency_ms")) * num(estimate.get("estimated_resource_pressure")),
        "profile_quality": num(estimate.get("estimated_latency_ms")) * num(risk.get("profile_quality_risk")),
    }
    ordered = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))
    primary = ordered[0][0] if ordered and ordered[0][1] > 0 else "unknown"
    secondary = [
        name
        for name, value in ordered[1:3]
        if value > 0 and name != primary
    ]
    return {
        "primary_bottleneck": primary,
        "secondary_bottlenecks": secondary,
    }


def _reason_codes(
    *,
    candidate: Mapping[str, Any],
    estimate: Mapping[str, float],
    risk: Mapping[str, float],
    bottleneck: Mapping[str, Any],
    suggestion: str,
) -> list[str]:
    codes: set[str] = set()
    if num(estimate.get("estimated_net_gain_ratio")) >= 0.08:
        codes.add("high_estimated_gain")
    else:
        codes.add("low_estimated_gain")
    if num(risk.get("transfer_risk")) >= 0.45:
        codes.add("transfer_overhead_high")
    else:
        codes.add("transfer_overhead_low")
    if num(estimate.get("estimated_resource_pressure")) >= 0.70:
        codes.add("resource_pressure_high")
    else:
        codes.add("resource_pressure_low")
    if num(estimate.get("estimated_model_confidence")) >= 0.65:
        codes.add("model_confidence_high")
    else:
        codes.add("model_confidence_low")
    if num(risk.get("profile_quality_risk")) >= 0.50:
        codes.add("profile_quality_limited")
    primary = str(bottleneck.get("primary_bottleneck", "unknown"))
    if primary == "memory":
        codes.add("memory_bottleneck")
    elif primary == "communication":
        codes.add("communication_bottleneck")
    elif primary == "compute":
        codes.add("compute_bottleneck")
    elif primary == "transfer":
        codes.add("transfer_bottleneck")
    elif primary == "resource":
        codes.add("resource_bottleneck")
    if candidate.get("target_type") == "gpu_fpga_hybrid" and num(risk.get("transfer_risk")) < 0.40:
        codes.add("hybrid_overlap_promising")
    if suggestion == "promote_to_systemc_request":
        codes.add("systemc_recommended")
    elif suggestion == "promote_to_gem5_systemc_request":
        codes.add("gem5_systemc_recommended")
    elif suggestion == "promote_to_vivado_resource_request":
        codes.add("vivado_resource_check_recommended")
    elif suggestion == "reject_before_high_fidelity":
        codes.add("reject_before_high_fidelity")
    elif suggestion == "hold_for_more_profile":
        codes.add("hold_for_more_profile")
    if num(estimate.get("estimated_model_confidence")) < 0.45:
        codes.add("insufficient_evidence")
    return sorted(codes)


def _suggestion(
    *,
    candidate: Mapping[str, Any],
    estimate: Mapping[str, float],
    risk: Mapping[str, float],
) -> str:
    gain = num(estimate.get("estimated_net_gain_ratio"))
    confidence = num(estimate.get("estimated_model_confidence"))
    resource = num(estimate.get("estimated_resource_pressure"))
    overall = num(risk.get("overall_l1_risk"))
    transfer = num(risk.get("transfer_risk"))
    if gain < 0.02 or overall >= 0.78:
        return "reject_before_high_fidelity"
    if confidence < 0.45:
        return "hold_for_more_profile"
    if resource >= 0.72:
        return "promote_to_vivado_resource_request" if gain >= 0.08 else "hold_for_more_profile"
    if candidate.get("target_type") == "gpu_fpga_hybrid" and gain >= 0.07 and transfer < 0.45:
        return "promote_to_gem5_systemc_request"
    if gain >= 0.08 and overall <= 0.60:
        return "promote_to_systemc_request"
    return "hold_for_more_profile"


def build_l1_result(
    *,
    request: Mapping[str, Any],
    candidate: Mapping[str, Any],
    promotion_decision: Mapping[str, Any],
    source_record: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
    suite_id: str,
) -> dict[str, Any]:
    """Build one deterministic L1 estimate result."""

    components = _estimate_components(
        candidate=candidate,
        source_record=source_record,
        motif_profile=motif_profile,
    )
    risk = {
        "model_uncertainty_risk": components.pop("model_uncertainty_risk"),
        "resource_risk": clamp(num(components.get("estimated_resource_pressure"))),
        "transfer_risk": components.pop("transfer_risk"),
        "profile_quality_risk": components.pop("profile_quality_risk"),
    }
    risk["overall_l1_risk"] = clamp(
        0.30 * risk["model_uncertainty_risk"]
        + 0.25 * risk["resource_risk"]
        + 0.25 * risk["transfer_risk"]
        + 0.20 * risk["profile_quality_risk"]
    )
    bottleneck = _bottlenecks(components, risk)
    suggestion = _suggestion(candidate=candidate, estimate=components, risk=risk)
    reason_codes = _reason_codes(
        candidate=candidate,
        estimate=components,
        risk=risk,
        bottleneck=bottleneck,
        suggestion=suggestion,
    )
    return {
        "result_id": _result_id(str(request.get("request_id")), str(candidate.get("candidate_id"))),
        "request_id": request.get("request_id"),
        "candidate_id": candidate.get("candidate_id"),
        "requested_fidelity": "L1_cost_model",
        "result_status": "completed_estimate",
        "candidate_type": candidate.get("candidate_type"),
        "target_type": candidate.get("target_type"),
        "workload_family_id": candidate.get("workload_family_id"),
        "motif_id": candidate.get("motif_id"),
        "template_id": candidate.get("template_id"),
        "source_traceability": {
            "layer1_suite_id": suite_id,
            "layer2_profile_artifact": "qe_ic_motif_profile.json",
            "layer3_viability_artifact": "qe_ic_target_viability.json",
            "layer4_candidate_plan_artifact": "qe_ic_candidate_plan.json",
            "source_viability_record_id": candidate.get("source_viability_record_id"),
            "promotion_decision_id": promotion_decision.get("promotion_decision_id"),
        },
        "estimate": components,
        "bottleneck_classification": bottleneck,
        "risk": risk,
        "next_fidelity_suggestion": {
            "suggestion": suggestion,
            "reason_codes": reason_codes,
        },
        "claim_boundary": RESULT_CLAIM_BOUNDARY,
    }
