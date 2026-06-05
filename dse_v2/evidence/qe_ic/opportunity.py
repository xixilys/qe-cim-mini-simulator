#!/usr/bin/env python3
"""QE-IC real GPU-baseline opportunity report construction."""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping
from typing import Any

from dse_v2.evidence.qe_ic.candidate_result import candidate_results_by_id
from dse_v2.evidence.qe_ic.claim_gate import evaluate_qe_ic_claim_gate
from dse_v2.evidence.qe_ic.gpu_baseline import baseline_match_key, baseline_records_by_match_key
from dse_v2.evidence.qe_ic.schema import (
    ANALYSIS_ROLE,
    CLAIM_BOUNDARY,
    LAYER_NAME,
    OPPORTUNITY_FOUND_VERDICTS,
    PRODUCER,
    QE_IC_REAL_BASELINE_OPPORTUNITY_REPORT_SCHEMA_VERSION,
    TARGET_TYPES,
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _candidate_index(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate.get("candidate_id")): candidate
        for candidate in _as_list(plan.get("candidates"))
        if isinstance(candidate, Mapping)
    }


def _tracked_candidate_ids(
    *,
    l1_results: Mapping[str, Any],
    closed_loop_results: Mapping[str, Any],
) -> set[str]:
    l1_ids = {
        str(row.get("candidate_id"))
        for row in _as_list(l1_results.get("results"))
        if isinstance(row, Mapping) and isinstance(row.get("candidate_id"), str)
    }
    closed_loop_ids = {
        str(row.get("candidate_id"))
        for row in _as_list(closed_loop_results.get("candidate_trajectory"))
        if isinstance(row, Mapping) and isinstance(row.get("candidate_id"), str)
    }
    return l1_ids & closed_loop_ids


def _candidate_records_for_analysis(
    candidate_plan: Mapping[str, Any],
    candidate_high_fidelity_results: Mapping[str, Any],
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    candidates = _candidate_index(candidate_plan)
    result_by_id = candidate_results_by_id(candidate_high_fidelity_results)
    pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for candidate_id in sorted(result_by_id):
        result = result_by_id[candidate_id]
        candidate = _as_mapping(candidates.get(candidate_id))
        if result.get("target_type") in TARGET_TYPES:
            pairs.append((candidate, result))
    return pairs


def _gpu_baseline_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    records = _as_list(payload.get("baseline_records"))
    by_family: Counter[str] = Counter()
    for record in records:
        if isinstance(record, Mapping):
            by_family[str(record.get("workload_family_id"))] += 1
    return {
        "measurement_role": payload.get("measurement_role"),
        "measurements_are_real": payload.get("measurements_are_real") is True,
        "evidence_status": payload.get("evidence_status"),
        "baseline_record_count": len([row for row in records if isinstance(row, Mapping)]),
        "workload_family_count": len(by_family),
        "records_by_workload_family": dict(sorted(by_family.items())),
    }


def _candidate_evidence_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    records = _as_list(payload.get("candidate_results"))
    by_target: Counter[str] = Counter()
    by_level: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    for record in records:
        if isinstance(record, Mapping):
            by_target[str(record.get("target_type"))] += 1
            by_level[str(record.get("evidence_level"))] += 1
            by_status[str(record.get("evidence_status"))] += 1
    return {
        "results_are_real": payload.get("results_are_real") is True,
        "candidate_result_count": len([row for row in records if isinstance(row, Mapping)]),
        "by_target_type": dict(sorted(by_target.items())),
        "by_evidence_level": dict(sorted(by_level.items())),
        "by_evidence_status": dict(sorted(by_status.items())),
    }


def _opportunity_record(
    *,
    candidate: Mapping[str, Any],
    candidate_result: Mapping[str, Any],
    baseline: Mapping[str, Any] | None,
    baseline_payload_real: bool,
    candidate_payload_real: bool,
    opportunity_config: Mapping[str, Any],
    tracked_candidate_ids: set[str],
) -> dict[str, Any]:
    preexisting_blockers: list[str] = []
    if not candidate:
        preexisting_blockers.append("unknown_candidate_not_claimable")
    elif str(candidate_result.get("candidate_id")) not in tracked_candidate_ids:
        preexisting_blockers.append("candidate_not_tracked_by_l1_or_layer6")
    gate = evaluate_qe_ic_claim_gate(
        baseline=baseline,
        baseline_payload_real=baseline_payload_real,
        candidate_result=candidate_result,
        candidate_payload_real=candidate_payload_real,
        opportunity_config=opportunity_config,
        preexisting_blockers=preexisting_blockers,
    )
    resource = _as_mapping(candidate_result.get("resource"))
    workflow_runtime = candidate_result.get("workflow_runtime_seconds_mean")
    return {
        "candidate_id": candidate_result.get("candidate_id"),
        "workload_family_id": candidate_result.get("workload_family_id") or candidate.get("workload_family_id"),
        "motif_id": candidate_result.get("motif_id") or candidate.get("motif_id"),
        "target_type": candidate_result.get("target_type") or candidate.get("target_type"),
        "architecture_summary": dict(_as_mapping(candidate_result.get("architecture_summary"))),
        "gpu_baseline_id": baseline.get("baseline_id") if baseline else None,
        "speedup_vs_gpu_mean": gate["speedup_vs_gpu_mean"],
        "speedup_vs_gpu_conservative_ci": gate["speedup_vs_gpu_conservative_ci"],
        "verdict": gate["verdict"],
        "claim_strength": gate["claim_strength"],
        "claim_allowed": gate["claim_allowed"],
        "claim_blockers": list(gate["claim_blockers"]),
        "failure_reasons": list(gate["failure_reasons"]),
        "resource_summary": {
            "resource_feasible": resource.get("resource_feasible"),
            "timing_feasible": resource.get("timing_feasible"),
            "lut_utilization": resource.get("lut_utilization"),
            "ff_utilization": resource.get("ff_utilization"),
            "bram_utilization": resource.get("bram_utilization"),
            "dsp_utilization": resource.get("dsp_utilization"),
            "hbm_port_utilization": resource.get("hbm_port_utilization"),
            "fmax_mhz": resource.get("fmax_mhz"),
        },
        "overhead_summary": {
            "workflow_runtime_seconds_mean": workflow_runtime,
            "kernel_runtime_seconds_mean": candidate_result.get("kernel_runtime_seconds_mean"),
            "transfer_overhead_seconds": candidate_result.get("transfer_overhead_seconds"),
            "workflow_overhead_seconds": candidate_result.get("workflow_overhead_seconds"),
            "transfer_overhead_ratio": gate["transfer_overhead_ratio"],
            "workflow_overhead_ratio": gate["workflow_overhead_ratio"],
        },
        "evidence_level": candidate_result.get("evidence_level"),
        "evidence_status": candidate_result.get("evidence_status"),
        "is_real_measurement_claim": gate["is_real_measurement_claim"],
        "raw_claim_gate_inputs": {
            "gpu_baseline_record": copy.deepcopy(dict(baseline)) if baseline else None,
            "candidate_result": copy.deepcopy(dict(candidate_result)),
            "opportunity_config": {
                "claim_gates": copy.deepcopy(dict(_as_mapping(opportunity_config.get("claim_gates")))),
                "analysis_thresholds": copy.deepcopy(dict(_as_mapping(opportunity_config.get("analysis_thresholds")))),
            },
        },
    }


def _missing_evidence(records: list[Mapping[str, Any]]) -> list[str]:
    missing: list[str] = []
    if not records:
        missing.append("candidate high-fidelity results for fpga_only or gpu_fpga_hybrid candidates")
    for record in records:
        for blocker in _as_list(record.get("claim_blockers")):
            if blocker == "gpu_baseline_missing":
                missing.append("matching measured GPU-only baseline record")
            elif blocker == "fixture_only_evidence":
                missing.append("real measured GPU baseline and real measured or high-fidelity candidate evidence")
            elif blocker == "l1_only_insufficient":
                missing.append("workflow-level SystemC/gem5/trace-replay/real-QE candidate runtime")
            elif blocker == "kernel_only_insufficient":
                missing.append("workflow-level candidate runtime including host, transfer, and synchronization costs")
            elif blocker == "repeated_runs_missing":
                missing.append("minimum repeated runtime runs")
            elif blocker == "high_fidelity_provenance_missing":
                missing.append("explicit tool provenance for high-fidelity estimate")
    return sorted(set(missing))


def _system_conclusion(records: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = [str(record.get("verdict")) for record in records]
    if not records:
        overall = "evidence_missing"
    elif all(verdict == "fixture_only_inconclusive" for verdict in verdicts):
        overall = "fixture_only_inconclusive"
    elif any(verdict == "hybrid_opportunity_found" for verdict in verdicts):
        overall = "hybrid_opportunity_found"
    elif any(verdict == "fpga_opportunity_found" for verdict in verdicts):
        overall = "fpga_opportunity_found"
    elif all(verdict in {"gpu_dominant_no_fpga_opportunity", "candidate_invalid_resource", "candidate_invalid_transfer_overhead", "candidate_invalid_workflow_overhead", "fpga_or_hybrid_inconclusive"} for verdict in verdicts):
        overall = "no_fpga_or_hybrid_opportunity_found"
    elif any(verdict == "evidence_missing" for verdict in verdicts):
        overall = "evidence_missing"
    else:
        overall = "mixed"

    claimable = [
        record
        for record in records
        if record.get("claim_allowed") is True and record.get("verdict") in OPPORTUNITY_FOUND_VERDICTS
    ]
    claimable.sort(key=lambda row: float(row.get("speedup_vs_gpu_mean") or 0.0), reverse=True)
    best = claimable[0] if claimable else None
    failure_counter: Counter[str] = Counter()
    for record in records:
        failure_counter.update(str(reason) for reason in _as_list(record.get("failure_reasons")))
    missing = _missing_evidence(records)

    if best:
        answer = (
            f"Candidate {best.get('candidate_id')} passes the claim gate with "
            f"{best.get('speedup_vs_gpu_mean'):.6g}x speedup vs GPU-only on workload "
            f"{best.get('workload_family_id')}/motif {best.get('motif_id')} under "
            f"evidence level {best.get('evidence_level')}."
        )
    elif overall == "fixture_only_inconclusive" or missing:
        answer = (
            "Current repository evidence is insufficient to conclude FPGA/hybrid is "
            "stronger or weaker than GPU under real GPU baseline."
        )
    else:
        dominant = ", ".join(reason for reason, _count in failure_counter.most_common(4))
        answer = (
            "Under the provided measured evidence, no FPGA/hybrid candidate passes "
            f"the opportunity claim gate; dominant blockers are {dominant}."
        )

    return {
        "overall_verdict": overall,
        "best_candidate_id": best.get("candidate_id") if best else None,
        "best_speedup_vs_gpu": best.get("speedup_vs_gpu_mean") if best else None,
        "dominant_failure_modes": [reason for reason, _count in failure_counter.most_common()],
        "what_evidence_is_missing": missing,
        "answer_to_research_question": answer,
    }


def analyze_qe_ic_real_baseline_opportunity(
    workload_suite: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
    target_viability: Mapping[str, Any],
    candidate_plan: Mapping[str, Any],
    l1_results: Mapping[str, Any],
    closed_loop_results: Mapping[str, Any],
    gpu_baseline_measurements: Mapping[str, Any],
    candidate_high_fidelity_results: Mapping[str, Any],
    opportunity_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a claim-gated GPU-vs-FPGA/hybrid opportunity report."""

    baseline_by_key = baseline_records_by_match_key(gpu_baseline_measurements)
    baseline_real = gpu_baseline_measurements.get("measurements_are_real") is True
    candidate_real = candidate_high_fidelity_results.get("results_are_real") is True
    tracked_candidate_ids = _tracked_candidate_ids(
        l1_results=l1_results,
        closed_loop_results=closed_loop_results,
    )
    records = [
        _opportunity_record(
            candidate=candidate,
            candidate_result=candidate_result,
            baseline=baseline_by_key.get(baseline_match_key(candidate_result)),
            baseline_payload_real=baseline_real,
            candidate_payload_real=candidate_real,
            opportunity_config=opportunity_config,
            tracked_candidate_ids=tracked_candidate_ids,
        )
        for candidate, candidate_result in _candidate_records_for_analysis(
            candidate_plan,
            candidate_high_fidelity_results,
        )
    ]
    return {
        "schema_version": QE_IC_REAL_BASELINE_OPPORTUNITY_REPORT_SCHEMA_VERSION,
        "analysis_role": ANALYSIS_ROLE,
        "layer": LAYER_NAME,
        "producer": PRODUCER,
        "input_artifact_index": dict(_as_mapping(opportunity_config.get("input_artifacts"))),
        "source_artifact_summaries": {
            "workload_family_count": len(_as_list(workload_suite.get("workload_families"))),
            "motif_profile_count": len(_as_list(motif_profile.get("family_target_profiles"))),
            "target_viability_record_count": len(_as_list(target_viability.get("viability_records"))),
            "candidate_count": len(_as_list(candidate_plan.get("candidates"))),
            "l1_result_count": len(_as_list(l1_results.get("results"))),
            "closed_loop_candidate_trajectory_count": len(_as_list(closed_loop_results.get("candidate_trajectory"))),
        },
        "gpu_baseline_summary": _gpu_baseline_summary(gpu_baseline_measurements),
        "candidate_evidence_summary": _candidate_evidence_summary(candidate_high_fidelity_results),
        "opportunity_records": records,
        "system_conclusion": _system_conclusion(records),
        "claim_boundary": CLAIM_BOUNDARY,
    }
