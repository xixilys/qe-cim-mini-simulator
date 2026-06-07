#!/usr/bin/env python3
"""Implementation quality audit for QE-IC real opportunity campaigns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _num(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _candidate_by_id(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate.get("candidate_id")): candidate
        for candidate in candidates
        if isinstance(candidate, Mapping) and isinstance(candidate.get("candidate_id"), str)
    }


def _quality_reasons(quality: Mapping[str, Any], opportunity_record: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    pipeline_util = _num(quality.get("pipeline_utilization"))
    memory_util = _num(quality.get("memory_bandwidth_utilization"))
    transfer_overlap = _num(quality.get("transfer_overlap"))
    resource = _as_mapping(opportunity_record.get("resource_summary"))
    if pipeline_util is not None and pipeline_util < 0.60:
        reasons.append("low pipeline utilization")
    if memory_util is not None and memory_util < 0.50:
        reasons.append("insufficient memory bandwidth")
    if transfer_overlap is not None and transfer_overlap < 0.50:
        reasons.append("poor transfer overlap")
    if _num(resource.get("fmax_mhz")) is not None and float(resource.get("fmax_mhz")) < 220.0:
        reasons.append("low fmax")
    if resource.get("resource_feasible") is False:
        reasons.append("resource pressure")
    overhead = _as_mapping(opportunity_record.get("overhead_summary"))
    if (_num(overhead.get("workflow_overhead_ratio")) or 0.0) >= 0.20:
        reasons.append("high synchronization overhead")
    if (_num(overhead.get("transfer_overhead_ratio")) or 0.0) >= 0.30:
        reasons.append("poor transfer overlap")
    if quality.get("mature_implementation") is False:
        reasons.append("immature implementation")
    if quality.get("functional_proxy_only") is True:
        reasons.append("functional proxy only")
    if quality.get("calibrated") is not True:
        reasons.append("SystemC/proxy not calibrated")
    return list(dict.fromkeys(reasons))


def _classification(
    *,
    opportunity_record: Mapping[str, Any],
    evidence: Mapping[str, Any],
    reasons: list[str],
) -> str:
    if not opportunity_record:
        return "evidence_missing"
    if opportunity_record.get("verdict") == "evidence_missing":
        return "evidence_missing"
    if opportunity_record.get("claim_allowed") is True:
        return "claim_gate_passed"
    blockers = set(str(row) for row in _as_list(opportunity_record.get("claim_blockers")))
    if "gpu_baseline_missing" in blockers or "fixture_only_evidence" in blockers:
        return "evidence_missing"
    resource = _as_mapping(opportunity_record.get("resource_summary"))
    if resource.get("resource_feasible") is False:
        return "resource_invalid"
    if resource.get("timing_feasible") is False:
        return "timing_invalid"
    failures = set(str(row) for row in _as_list(opportunity_record.get("failure_reasons")))
    if "transfer_overhead_dominates" in failures:
        return "transfer_overhead_invalid"
    if "workflow_overhead_dominates" in failures:
        return "workflow_overhead_invalid"
    upper_bound = _num(evidence.get("idealized_upper_bound_speedup_vs_gpu"))
    speedup = _num(opportunity_record.get("speedup_vs_gpu_mean"))
    if speedup is not None and speedup <= 1.0 and upper_bound is not None and upper_bound > 1.0:
        return "implementation_limited"
    quality = _as_mapping(evidence.get("implementation_quality"))
    if (
        speedup is not None
        and speedup <= 1.0
        and upper_bound is not None
        and upper_bound <= 1.0
        and quality.get("mature_implementation") is True
        and quality.get("calibrated") is True
        and not reasons
    ):
        return "fundamental_no_opportunity"
    if reasons:
        return "implementation_limited"
    return "inconclusive"


def audit_candidate_implementation_quality(
    *,
    candidate_selection: Sequence[Mapping[str, Any]],
    opportunity_records: Sequence[Mapping[str, Any]],
    candidate_evidence_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Classify implementation failures without collapsing them into no-opportunity claims."""

    selected = _candidate_by_id(candidate_selection)
    records_by_id = {
        str(record.get("candidate_id")): record
        for record in opportunity_records
        if isinstance(record, Mapping) and isinstance(record.get("candidate_id"), str)
    }
    evidence_by_id = candidate_evidence_by_id or {}
    rows: list[dict[str, Any]] = []
    for candidate_id in sorted(selected):
        record = _as_mapping(records_by_id.get(candidate_id))
        evidence = _as_mapping(evidence_by_id.get(candidate_id))
        quality = _as_mapping(evidence.get("implementation_quality"))
        reasons = _quality_reasons(quality, record)
        classification = _classification(
            opportunity_record=record,
            evidence=evidence,
            reasons=reasons,
        )
        upper_bound = _num(evidence.get("idealized_upper_bound_speedup_vs_gpu"))
        rows.append(
            {
                "candidate_id": candidate_id,
                "workload_family_id": selected[candidate_id].get("workload_family_id"),
                "motif_id": selected[candidate_id].get("motif_id"),
                "target_type": selected[candidate_id].get("target_type"),
                "implementation_quality_classification": classification,
                "implementation_limited_reasons": reasons,
                "idealized_upper_bound": {
                    "available": upper_bound is not None,
                    "speedup_vs_gpu": upper_bound,
                    "interpretation": "upper bound above one suggests implementation-limited loss"
                    if upper_bound is not None and upper_bound > 1.0
                    else "upper bound does not suggest speedup" if upper_bound is not None else "not available",
                },
                "quality_observations": dict(quality),
                "rule_boundary": (
                    "Actual loss with idealized upper bound above 1.0 is implementation_limited, "
                    "not fundamental_no_opportunity."
                ),
            }
        )
    return rows
