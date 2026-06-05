#!/usr/bin/env python3
"""Claim-gate computations for QE-IC GPU-vs-FPGA opportunity records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dse_v2.evidence.qe_ic.schema import (
    OPPORTUNITY_FOUND_VERDICTS,
    REQUIRED_HIGH_FIDELITY_PROVENANCE_FIELDS,
    TARGET_TYPES,
    WORKFLOW_LEVEL_EVIDENCE_LEVELS,
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _num(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def speedup_vs_gpu_mean(
    baseline: Mapping[str, Any] | None,
    candidate_result: Mapping[str, Any],
) -> float | None:
    """Compute mean workflow speedup against GPU-only baseline."""

    if not baseline:
        return None
    gpu_mean = _num(_as_mapping(baseline).get("runtime_seconds_mean"))
    candidate_mean = _num(candidate_result.get("workflow_runtime_seconds_mean"))
    if gpu_mean is None or candidate_mean is None or gpu_mean <= 0.0 or candidate_mean <= 0.0:
        return None
    return gpu_mean / candidate_mean


def conservative_ci_speedup(
    baseline: Mapping[str, Any] | None,
    candidate_result: Mapping[str, Any],
) -> float | None:
    """Compute conservative CI speedup as GPU low bound over candidate high bound."""

    if not baseline:
        return None
    baseline_low = _num(_as_mapping(_as_mapping(baseline).get("confidence_interval_95")).get("low"))
    candidate_high = _num(_as_mapping(candidate_result.get("confidence_interval_95")).get("high"))
    if baseline_low is None or candidate_high is None or baseline_low <= 0.0 or candidate_high <= 0.0:
        return None
    return baseline_low / candidate_high


def _has_required_high_fidelity_provenance(candidate_result: Mapping[str, Any]) -> bool:
    provenance = _as_mapping(candidate_result.get("tool_provenance"))
    return all(
        isinstance(provenance.get(field), str) and provenance.get(field)
        for field in REQUIRED_HIGH_FIDELITY_PROVENANCE_FIELDS
    )


def evaluate_qe_ic_claim_gate(
    *,
    baseline: Mapping[str, Any] | None,
    baseline_payload_real: bool,
    candidate_result: Mapping[str, Any],
    candidate_payload_real: bool,
    opportunity_config: Mapping[str, Any],
    preexisting_blockers: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate opportunity claim gates and return recomputable gate state."""

    blockers: list[str] = list(preexisting_blockers or [])
    failure_reasons: list[str] = []
    failure_reasons.extend(blockers)
    claim_gates = _as_mapping(opportunity_config.get("claim_gates"))
    thresholds = _as_mapping(opportunity_config.get("analysis_thresholds"))
    minimum_speedup = float(claim_gates.get("minimum_speedup_for_strong_claim", 1.10))
    minimum_runs = int(claim_gates.get("minimum_repeated_runs", 3))
    require_ci = claim_gates.get("require_confidence_interval_not_crossing_one") is True
    require_resource = claim_gates.get("require_resource_feasible") is True
    require_timing = claim_gates.get("require_timing_feasible") is True
    require_workflow = claim_gates.get("require_workflow_level_or_trace_replay") is True
    allow_kernel_only = claim_gates.get("allow_kernel_only_claim") is True
    transfer_threshold = float(thresholds.get("transfer_overhead_dominant_ratio", 0.30))
    workflow_threshold = float(thresholds.get("workflow_overhead_high", 0.20))
    gpu_dominant_threshold = float(thresholds.get("gpu_dominant_utilization", 0.70))

    if baseline is None:
        blockers.append("gpu_baseline_missing")
        failure_reasons.append("gpu_baseline_missing")
    elif not baseline_payload_real or baseline.get("evidence_status") != "measured":
        blockers.append("fixture_only_evidence")
        failure_reasons.append("fixture_only_evidence")
    if not candidate_payload_real or candidate_result.get("evidence_status") == "fixture_example":
        blockers.append("fixture_only_evidence")
        failure_reasons.append("fixture_only_evidence")

    evidence_level = candidate_result.get("evidence_level")
    if evidence_level == "l1_estimate_only":
        blockers.append("l1_only_insufficient")
        failure_reasons.append("l1_only_insufficient")
    if require_workflow and evidence_level not in WORKFLOW_LEVEL_EVIDENCE_LEVELS:
        blockers.append("kernel_only_insufficient")
    if (
        candidate_result.get("evidence_status") == "high_fidelity_estimate"
        and not _has_required_high_fidelity_provenance(candidate_result)
    ):
        blockers.append("high_fidelity_provenance_missing")
        failure_reasons.append("high_fidelity_provenance_missing")

    workflow_runtime = _num(candidate_result.get("workflow_runtime_seconds_mean"))
    if workflow_runtime is None and not allow_kernel_only:
        blockers.append("kernel_only_insufficient")
        failure_reasons.append("kernel_only_insufficient")

    runs = _as_list(candidate_result.get("runtime_seconds_runs"))
    if len(runs) < minimum_runs:
        blockers.append("repeated_runs_missing")
        failure_reasons.append("repeated_runs_missing")

    resource = _as_mapping(candidate_result.get("resource"))
    if require_resource and resource.get("resource_feasible") is not True:
        blockers.append("resource_infeasible")
        failure_reasons.append("resource_infeasible")
    if require_timing and resource.get("timing_feasible") is not True:
        blockers.append("timing_infeasible")
        failure_reasons.append("timing_infeasible")

    transfer_seconds = _num(candidate_result.get("transfer_overhead_seconds"))
    workflow_overhead_seconds = _num(candidate_result.get("workflow_overhead_seconds"))
    transfer_ratio = None
    workflow_overhead_ratio = None
    if workflow_runtime and transfer_seconds is not None:
        transfer_ratio = transfer_seconds / workflow_runtime
        if transfer_ratio >= transfer_threshold:
            failure_reasons.append("transfer_overhead_dominates")
    if workflow_runtime and workflow_overhead_seconds is not None:
        workflow_overhead_ratio = workflow_overhead_seconds / workflow_runtime
        if workflow_overhead_ratio >= workflow_threshold:
            failure_reasons.append("workflow_overhead_dominates")

    gpu_utilization = _num(_as_mapping(baseline).get("gpu_utilization_mean")) if baseline else None
    if gpu_utilization is not None and gpu_utilization >= gpu_dominant_threshold:
        failure_reasons.append("gpu_utilization_high")

    mean_speedup = speedup_vs_gpu_mean(baseline, candidate_result)
    ci_speedup = conservative_ci_speedup(baseline, candidate_result)
    if mean_speedup is None:
        blockers.append("workflow_speedup_missing")
    elif mean_speedup < minimum_speedup:
        blockers.append("no_speedup_vs_gpu")
        failure_reasons.append("no_speedup_vs_gpu")
    if require_ci and (ci_speedup is None or ci_speedup <= 1.0):
        blockers.append("confidence_interval_crosses_one")
        failure_reasons.append("confidence_interval_crosses_one")

    target_type = str(candidate_result.get("target_type", ""))
    if target_type not in TARGET_TYPES:
        blockers.append("unsupported_target_type")
        failure_reasons.append("unsupported_target_type")

    blockers = list(dict.fromkeys(blockers))
    failure_reasons = list(dict.fromkeys(failure_reasons))
    claim_allowed = not blockers
    if claim_allowed:
        failure_reasons.append("speedup_claim_gate_passed")

    if "gpu_baseline_missing" in blockers:
        verdict = "evidence_missing"
    elif "unknown_candidate_not_claimable" in blockers or "candidate_not_tracked_by_l1_or_layer6" in blockers:
        verdict = "evidence_missing"
    elif "fixture_only_evidence" in blockers:
        verdict = "fixture_only_inconclusive"
    elif "resource_infeasible" in blockers or "timing_infeasible" in blockers:
        verdict = "candidate_invalid_resource"
    elif "transfer_overhead_dominates" in failure_reasons:
        verdict = "candidate_invalid_transfer_overhead"
    elif "workflow_overhead_dominates" in failure_reasons:
        verdict = "candidate_invalid_workflow_overhead"
    elif claim_allowed and target_type == "fpga_only":
        verdict = "fpga_opportunity_found"
    elif claim_allowed and target_type == "gpu_fpga_hybrid":
        verdict = "hybrid_opportunity_found"
    elif "gpu_utilization_high" in failure_reasons and "no_speedup_vs_gpu" in failure_reasons:
        verdict = "gpu_dominant_no_fpga_opportunity"
    else:
        verdict = "fpga_or_hybrid_inconclusive"

    claim_strength = "strong" if claim_allowed and verdict in OPPORTUNITY_FOUND_VERDICTS else "none"
    if not claim_allowed and mean_speedup is not None and mean_speedup >= minimum_speedup:
        claim_strength = "moderate" if "fixture_only_evidence" not in blockers else "none"

    return {
        "speedup_vs_gpu_mean": mean_speedup,
        "speedup_vs_gpu_conservative_ci": ci_speedup,
        "claim_allowed": claim_allowed,
        "claim_strength": claim_strength,
        "claim_blockers": blockers,
        "failure_reasons": failure_reasons,
        "verdict": verdict,
        "transfer_overhead_ratio": transfer_ratio,
        "workflow_overhead_ratio": workflow_overhead_ratio,
        "is_real_measurement_claim": claim_allowed
        and baseline_payload_real
        and candidate_payload_real
        and candidate_result.get("evidence_status") in {"measured", "high_fidelity_estimate"},
    }
