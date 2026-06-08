#!/usr/bin/env python3
"""Independent benchmark oracles for multi-fidelity DSE algorithms.

This module is for method validation.  It builds synthetic but structured
candidate spaces where the expensive objective is intentionally not the same
formula as the cheap L1 objective.  That lets WAMF-DSE be tested under workflow
shift, resource cliffs, and data-residency interactions before real tool
feedback exists.
"""

from __future__ import annotations

import hashlib
import math
from random import Random
from typing import Any, Dict, List, Mapping, Sequence

from dse_v2.mapping.multifidelity_active_search import ActiveSearchCandidate
from dse_v2.mapping.multifidelity_active_search import MultiFidelityActiveSearchPolicy


_OBJECTIVE_NAMES = (
    "latency_ms",
    "energy_mj",
    "resource_pressure",
    "data_movement_mb",
)


def build_multifidelity_search_benchmark_report(
    *,
    scenario_id: str,
    candidate_count: int = 64,
    budgets: Sequence[int] = (2, 4, 8),
    top_k: int = 5,
    include_ablations: bool = False,
    workflow_conditioning: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a replayable method benchmark under controlled model mismatch."""

    resolved_budgets = sorted({max(1, int(budget)) for budget in budgets})
    resolved_candidate_count = max(max(resolved_budgets), int(candidate_count))
    top_k = max(1, int(top_k))
    conditioning = dict(workflow_conditioning or {})
    rows = _benchmark_candidates(scenario_id, resolved_candidate_count, workflow_conditioning=conditioning)
    oracle_rank = _oracle_rank(rows)
    oracle_best = min(row["oracle_objective"] for row in rows)
    oracle_best_candidate_id = min(
        rows,
        key=lambda row: (row["oracle_objective"], row["candidate_id"]),
    )["candidate_id"]
    oracle_pareto_ids = set(_oracle_pareto_candidate_ids(rows))
    oracle_pareto_signatures = {
        _candidate_gene_key(row)
        for row in rows
        if str(row["candidate_id"]) in oracle_pareto_ids
    }
    reference_hypervolume = _oracle_reference_hypervolume(rows)
    surrogate_ei_rows, surrogate_ei_trace = _select_sequential_surrogate_ei(
        rows,
        max(resolved_budgets),
    )
    ea_rows, ea_trace = _select_nsga2_ea_l1(rows, max(resolved_budgets), seed=31)
    policies = [
        _policy_report(
            policy_id="wamf_constrained_active_pareto",
            selected_rows=_select_wamf(rows, max(resolved_budgets)),
            rows=rows,
            budgets=resolved_budgets,
            oracle_rank=oracle_rank,
            oracle_best=oracle_best,
            oracle_pareto_ids=oracle_pareto_ids,
            oracle_pareto_signatures=oracle_pareto_signatures,
            reference_hypervolume=reference_hypervolume,
            top_k=top_k,
            uses_global_acquisition=True,
            uses_oracle_during_selection=False,
        ),
        _policy_report(
            policy_id="sequential_surrogate_expected_improvement",
            selected_rows=surrogate_ei_rows,
            rows=rows,
            budgets=resolved_budgets,
            oracle_rank=oracle_rank,
            oracle_best=oracle_best,
            oracle_pareto_ids=oracle_pareto_ids,
            oracle_pareto_signatures=oracle_pareto_signatures,
            reference_hypervolume=reference_hypervolume,
            top_k=top_k,
            uses_global_acquisition=False,
            uses_oracle_during_selection=False,
            extra={
                "selection_model": "online_residual_expected_improvement",
                "initial_design_count": min(3, max(resolved_budgets)),
                "observation_count": max(resolved_budgets),
                "surrogate_update_rule": "fit_residuals_only_from_previously_selected_observations",
                "trace": surrogate_ei_trace,
            },
        ),
        _policy_report(
            policy_id="nsga2_ea_l1_multi_objective",
            selected_rows=ea_rows,
            rows=rows,
            budgets=resolved_budgets,
            oracle_rank=oracle_rank,
            oracle_best=oracle_best,
            oracle_pareto_ids=oracle_pareto_ids,
            oracle_pareto_signatures=oracle_pareto_signatures,
            reference_hypervolume=reference_hypervolume,
            top_k=top_k,
            uses_global_acquisition=False,
            uses_oracle_during_selection=False,
            extra={
                "selection_model": "nsga2_style_evolutionary_search_on_l1_objectives",
                "objectives_minimized": list(_OBJECTIVE_NAMES),
                "population_size": 24,
                "generation_count": len(ea_trace),
                "random_seed": 31,
                "generation_trace": ea_trace,
            },
        ),
        _policy_report(
            policy_id="cheap_l1_edp",
            selected_rows=_select_cheap_l1(rows, max(resolved_budgets)),
            rows=rows,
            budgets=resolved_budgets,
            oracle_rank=oracle_rank,
            oracle_best=oracle_best,
            oracle_pareto_ids=oracle_pareto_ids,
            oracle_pareto_signatures=oracle_pareto_signatures,
            reference_hypervolume=reference_hypervolume,
            top_k=top_k,
            uses_global_acquisition=False,
            uses_oracle_during_selection=False,
        ),
        _policy_report(
            policy_id="random_seeded",
            selected_rows=_select_random(rows, max(resolved_budgets), seed=17),
            rows=rows,
            budgets=resolved_budgets,
            oracle_rank=oracle_rank,
            oracle_best=oracle_best,
            oracle_pareto_ids=oracle_pareto_ids,
            oracle_pareto_signatures=oracle_pareto_signatures,
            reference_hypervolume=reference_hypervolume,
            top_k=top_k,
            uses_global_acquisition=False,
            uses_oracle_during_selection=False,
            extra={"random_seed": 17},
        ),
        _policy_report(
            policy_id="manual_hbm_streaming",
            selected_rows=_select_manual_hbm(rows, max(resolved_budgets)),
            rows=rows,
            budgets=resolved_budgets,
            oracle_rank=oracle_rank,
            oracle_best=oracle_best,
            oracle_pareto_ids=oracle_pareto_ids,
            oracle_pareto_signatures=oracle_pareto_signatures,
            reference_hypervolume=reference_hypervolume,
            top_k=top_k,
            uses_global_acquisition=False,
            uses_oracle_during_selection=False,
        ),
        _policy_report(
            policy_id="kernel_hotspot_only",
            selected_rows=_select_kernel_hotspot(rows, max(resolved_budgets)),
            rows=rows,
            budgets=resolved_budgets,
            oracle_rank=oracle_rank,
            oracle_best=oracle_best,
            oracle_pareto_ids=oracle_pareto_ids,
            oracle_pareto_signatures=oracle_pareto_signatures,
            reference_hypervolume=reference_hypervolume,
            top_k=top_k,
            uses_global_acquisition=False,
            uses_oracle_during_selection=False,
        ),
    ]
    ablations: List[Dict[str, Any]] = []
    if include_ablations:
        ablations = [
            _policy_report(
                policy_id="wamf_no_workflow_risk",
                selected_rows=_select_wamf(rows, max(resolved_budgets), weights={"workflow_risk_coverage": 0.0}),
                rows=rows,
                budgets=resolved_budgets,
                oracle_rank=oracle_rank,
                oracle_best=oracle_best,
                oracle_pareto_ids=oracle_pareto_ids,
                oracle_pareto_signatures=oracle_pareto_signatures,
                reference_hypervolume=reference_hypervolume,
                top_k=top_k,
                uses_global_acquisition=True,
                uses_oracle_during_selection=False,
                extra={"removed_components": ["workflow_risk_coverage"]},
            ),
            _policy_report(
                policy_id="wamf_no_uncertainty",
                selected_rows=_select_wamf(rows, max(resolved_budgets), weights={"uncertainty": 0.0}),
                rows=rows,
                budgets=resolved_budgets,
                oracle_rank=oracle_rank,
                oracle_best=oracle_best,
                oracle_pareto_ids=oracle_pareto_ids,
                oracle_pareto_signatures=oracle_pareto_signatures,
                reference_hypervolume=reference_hypervolume,
                top_k=top_k,
                uses_global_acquisition=True,
                uses_oracle_during_selection=False,
                extra={"removed_components": ["uncertainty"]},
            ),
            _policy_report(
                policy_id="wamf_no_diversity",
                selected_rows=_select_wamf(rows, max(resolved_budgets), weights={"design_diversity": 0.0}),
                rows=rows,
                budgets=resolved_budgets,
                oracle_rank=oracle_rank,
                oracle_best=oracle_best,
                oracle_pareto_ids=oracle_pareto_ids,
                oracle_pareto_signatures=oracle_pareto_signatures,
                reference_hypervolume=reference_hypervolume,
                top_k=top_k,
                uses_global_acquisition=True,
                uses_oracle_during_selection=False,
                extra={"removed_components": ["design_diversity"]},
            ),
            _policy_report(
                policy_id="wamf_no_feasibility",
                selected_rows=_select_wamf(rows, max(resolved_budgets), feasibility_blind=True),
                rows=rows,
                budgets=resolved_budgets,
                oracle_rank=oracle_rank,
                oracle_best=oracle_best,
                oracle_pareto_ids=oracle_pareto_ids,
                oracle_pareto_signatures=oracle_pareto_signatures,
                reference_hypervolume=reference_hypervolume,
                top_k=top_k,
                uses_global_acquisition=True,
                uses_oracle_during_selection=False,
                extra={"removed_components": ["feasibility_probability"]},
            ),
        ]
    oracle_kind = (
        "workflow_conditioned_independent_synthetic_mismatch"
        if conditioning
        else "independent_synthetic_workflow_mismatch"
    )
    mismatch_axes = [
        "l1_bias",
        "noise",
        "resource_cliff",
        "data_residency_interaction",
        "workflow_shift",
        "host_control_penalty",
    ]
    if conditioning:
        mismatch_axes.extend([
            "workflow_conditioning",
            "host_control_pressure",
            "data_movement_pressure",
            "post_processing_pressure",
            "resource_pressure",
        ])
    report = {
        "schema_version": "dse.multifidelity_search_benchmark.v1",
        "scenario_id": str(scenario_id),
        "candidate_count": len(rows),
        "budgets": resolved_budgets,
        "top_k": top_k,
        "oracle": {
            "oracle_kind": oracle_kind,
            "not_derived_from_l1_objectives": True,
            "mismatch_axes": list(dict.fromkeys(mismatch_axes)),
            "best_candidate_id": oracle_best_candidate_id,
            "best_objective": _round(oracle_best),
            "pareto_frontier_size": len(oracle_pareto_ids),
            "pareto_design_signature_count": len(oracle_pareto_signatures),
            "reference_hypervolume": _round(reference_hypervolume),
        },
        "policies": policies,
        "ablations": ablations,
        "experiment_role": "algorithm_method_validation_not_hardware_evidence",
    }
    if conditioning:
        report["workflow_conditioning"] = conditioning
    return report


def build_workflow_conditioned_multifidelity_benchmark_suite_report(
    *,
    workflow_abstractions: Sequence[Mapping[str, Any]],
    candidate_count: int = 64,
    budgets: Sequence[int] = (2, 4, 8),
    top_k: int = 5,
    include_ablations: bool = False,
) -> Dict[str, Any]:
    """Aggregate benchmark reports whose oracle shifts are derived from workflow features.

    This keeps the benchmark oracle independent from the cheap L1 objective, but
    prevents the validation suite from being only a hand-authored synthetic
    scenario.  The conditioning fields are extracted from the domain-neutral
    workflow feature contract when present.
    """

    conditionings = [
        _workflow_conditioning_from_abstraction(abstraction, index=index)
        for index, abstraction in enumerate(workflow_abstractions)
        if isinstance(abstraction, Mapping)
    ]
    if not conditionings:
        conditionings = [
            {
                "scenario_id": "workflow_conditioned_default",
                "workflow_id": "workflow_conditioned_default",
                "source_schema": "",
                "feature_contract_schema": "",
                "conditioning_applied_to_oracle": True,
                "host_control_pressure": 0.25,
                "data_movement_pressure": 0.25,
                "post_processing_pressure": 0.0,
                "resource_pressure": 0.25,
                "stage_count": 1,
                "workflow_classes": [],
                "conditioning_boundary": "default_conditioning_without_workflow_abstraction",
            }
        ]
    resolved_budgets = sorted({max(1, int(budget)) for budget in budgets})
    scenario_reports = [
        build_multifidelity_search_benchmark_report(
            scenario_id=str(conditioning.get("scenario_id", f"workflow_conditioned_{index:02d}")),
            candidate_count=candidate_count,
            budgets=resolved_budgets,
            top_k=top_k,
            include_ablations=include_ablations,
            workflow_conditioning=conditioning,
        )
        for index, conditioning in enumerate(conditionings)
    ]
    policy_statistics = _benchmark_suite_policy_statistics(
        scenario_reports,
        final_budget=max(resolved_budgets),
    )
    best_policy = min(
        policy_statistics,
        key=lambda row: (
            float(row["mean_simple_regret"]),
            -float(row["top_k_hit_rate"]),
            str(row["policy_id"]),
        ),
    ) if policy_statistics else {}
    return {
        "schema_version": "dse.workflow_conditioned_multifidelity_search_benchmark_suite.v1",
        "conditioning_source": "workflow_feature_contract",
        "workflow_ids": [str(row.get("workflow_id", "")) for row in conditionings],
        "scenario_ids": [str(row.get("scenario_id", "")) for row in conditionings],
        "scenario_count": len(scenario_reports),
        "candidate_count": max(max(resolved_budgets), int(candidate_count)),
        "budgets": resolved_budgets,
        "final_budget": max(resolved_budgets),
        "top_k": max(1, int(top_k)),
        "scenario_reports": scenario_reports,
        "policy_statistics": policy_statistics,
        "best_policy_by_mean_regret": dict(best_policy),
        "experiment_role": "workflow_conditioned_algorithm_validation_not_hardware_evidence",
    }


def build_multifidelity_search_benchmark_suite_report(
    *,
    scenario_ids: Sequence[str],
    candidate_count: int = 64,
    budgets: Sequence[int] = (2, 4, 8),
    top_k: int = 5,
    include_ablations: bool = False,
) -> Dict[str, Any]:
    """Aggregate independent benchmark reports across mismatch scenarios."""

    scenarios = [str(item) for item in scenario_ids if str(item)]
    if not scenarios:
        scenarios = ["workflow_shift_resource_cliff"]
    resolved_budgets = sorted({max(1, int(budget)) for budget in budgets})
    scenario_reports = [
        build_multifidelity_search_benchmark_report(
            scenario_id=scenario_id,
            candidate_count=candidate_count,
            budgets=resolved_budgets,
            top_k=top_k,
            include_ablations=include_ablations,
        )
        for scenario_id in scenarios
    ]
    policy_statistics = _benchmark_suite_policy_statistics(
        scenario_reports,
        final_budget=max(resolved_budgets),
    )
    best_policy = min(
        policy_statistics,
        key=lambda row: (
            float(row["mean_simple_regret"]),
            -float(row["top_k_hit_rate"]),
            str(row["policy_id"]),
        ),
    ) if policy_statistics else {}
    return {
        "schema_version": "dse.multifidelity_search_benchmark_suite.v1",
        "scenario_ids": scenarios,
        "scenario_count": len(scenario_reports),
        "candidate_count": max(max(resolved_budgets), int(candidate_count)),
        "budgets": resolved_budgets,
        "final_budget": max(resolved_budgets),
        "top_k": max(1, int(top_k)),
        "scenario_reports": scenario_reports,
        "policy_statistics": policy_statistics,
        "best_policy_by_mean_regret": dict(best_policy),
        "experiment_role": "algorithm_robustness_validation_not_hardware_evidence",
    }


def _benchmark_suite_policy_statistics(
    scenario_reports: Sequence[Mapping[str, Any]],
    *,
    final_budget: int,
) -> List[Dict[str, Any]]:
    by_policy: Dict[str, List[Mapping[str, Any]]] = {}
    scenario_winners: Dict[str, int] = {}
    for report in scenario_reports:
        policy_points: List[tuple[str, Mapping[str, Any]]] = []
        for policy in report.get("policies", []) or []:
            if not isinstance(policy, Mapping):
                continue
            point = _policy_final_budget_point(policy, final_budget)
            if not point:
                continue
            policy_id = str(policy.get("policy_id", ""))
            by_policy.setdefault(policy_id, []).append(point)
            policy_points.append((policy_id, point))
        if policy_points:
            winner, _point = min(
                policy_points,
                key=lambda item: (
                    _finite_or_inf(item[1].get("simple_regret")),
                    _finite_or_inf(item[1].get("oracle_rank_of_best")),
                    item[0],
                ),
            )
            scenario_winners[winner] = scenario_winners.get(winner, 0) + 1
    rows: List[Dict[str, Any]] = []
    scenario_count = max(1, len(scenario_reports))
    for policy_id, points in sorted(by_policy.items()):
        regrets = [_finite_or_inf(point.get("simple_regret")) for point in points]
        regrets = [value for value in regrets if math.isfinite(value)]
        hv = [_finite_or_zero(point.get("hypervolume_ratio")) for point in points]
        fhv = [_finite_or_zero(point.get("feasibility_weighted_hv_ratio")) for point in points]
        coverage = [_finite_or_zero(point.get("oracle_pareto_coverage_at_budget")) for point in points]
        ranks = [_finite_or_inf(point.get("oracle_rank_of_best")) for point in points]
        finite_ranks = [value for value in ranks if math.isfinite(value)]
        rows.append({
            "policy_id": policy_id,
            "scenario_count": len(points),
            "final_budget": int(final_budget),
            "mean_simple_regret": _round(_mean(regrets)),
            "std_simple_regret": _round(_stddev(regrets)),
            "mean_oracle_rank": _round(_mean(finite_ranks)),
            "mean_hypervolume_ratio": _round(_mean(hv)),
            "mean_feasibility_weighted_hv_ratio": _round(_mean(fhv)),
            "mean_pareto_coverage": _round(_mean(coverage)),
            "top_k_hit_rate": _round(_mean([1.0 if point.get("top_k_hit") else 0.0 for point in points])),
            "win_rate_by_simple_regret": _round(
                float(scenario_winners.get(policy_id, 0)) / float(scenario_count)
            ),
        })
    return rows


def _policy_final_budget_point(policy: Mapping[str, Any], final_budget: int) -> Mapping[str, Any]:
    points = [
        point for point in policy.get("budget_curve", []) or []
        if isinstance(point, Mapping)
    ]
    for point in points:
        if int(point.get("budget", -1)) == int(final_budget):
            return point
    return points[-1] if points else {}


def _benchmark_candidates(
    scenario_id: str,
    candidate_count: int,
    *,
    workflow_conditioning: Mapping[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    conditioning = workflow_conditioning if isinstance(workflow_conditioning, Mapping) else {}
    host_pressure = _clamp01(conditioning.get("host_control_pressure"))
    transfer_pressure = _clamp01(conditioning.get("data_movement_pressure"))
    post_pressure = _clamp01(conditioning.get("post_processing_pressure"))
    resource_pressure = _clamp01(conditioning.get("resource_pressure"))
    stage_count = max(1, int(_finite_or_zero(conditioning.get("stage_count")) or 1))
    rows: List[Dict[str, Any]] = []
    for index in range(candidate_count):
        arch = ("hbm_streaming", "ddr_streaming", "uram_tiled", "cpu_control_hybrid")[index % 4]
        residency = ("hot_arrays_resident", "streaming_windows", "checkpoint_reuse")[index // 4 % 3]
        schedule = ("overlap_dma_compute", "sequential_host_control", "double_buffered")[index // 12 % 3]
        vector_lanes = (2, 4, 8)[index // 9 % 3]
        host = _scenario_value(scenario_id, "host", index)
        transfer = _scenario_value(scenario_id, "transfer", index)
        data_reuse = 1.0 if residency in {"hot_arrays_resident", "checkpoint_reuse"} else 0.25
        resource = min(1.0, 0.38 + 0.035 * vector_lanes + (0.20 if arch == "hbm_streaming" else 0.0))
        l1_latency = 220.0 - 7.5 * vector_lanes + (12.0 if arch == "ddr_streaming" else 0.0)
        l1_energy = 95.0 + 7.0 * resource + (10.0 if schedule == "sequential_host_control" else 0.0)
        l1_data = 180.0 - 42.0 * data_reuse + (35.0 if arch == "ddr_streaming" else 0.0)
        l1_edp = l1_latency * l1_energy
        resource_cliff = 1.0 + max(0.0, resource - 0.78) * 5.0
        data_interaction = 1.0 - 0.28 * data_reuse if arch == "hbm_streaming" else 1.0 + 0.20 * transfer
        workflow_shift = 1.0 + 0.42 * host if schedule == "sequential_host_control" else 1.0 - 0.18 * transfer
        host_penalty = 1.0 + 0.30 * host if arch == "hbm_streaming" and residency == "hot_arrays_resident" else 1.0
        noise = 1.0 + (_stable_unit(scenario_id, index, "noise") - 0.5) * 0.08
        oracle_objective = max(1.0, l1_edp * resource_cliff * data_interaction * workflow_shift * host_penalty * noise)
        if conditioning:
            workflow_host_penalty = (
                1.0
                + host_pressure * (0.42 if schedule == "sequential_host_control" else 0.08)
                + 0.04 * max(0, stage_count - 1)
            )
            workflow_transfer_penalty = 1.0 + transfer_pressure * (
                0.34 if residency == "streaming_windows" else 0.10
            )
            workflow_post_penalty = 1.0 + post_pressure * (
                0.28 if arch == "cpu_control_hybrid" else 0.08
            )
            workflow_resource_penalty = 1.0 + resource_pressure * max(0.0, resource - 0.72) * 2.2
            workflow_residency_bonus = 1.0 - transfer_pressure * (
                0.20 if arch == "hbm_streaming" and residency in {"hot_arrays_resident", "checkpoint_reuse"} else 0.0
            )
            workflow_overlap_bonus = 1.0 - host_pressure * (
                0.12 if schedule in {"overlap_dma_compute", "double_buffered"} else 0.0
            )
            oracle_objective *= max(
                0.25,
                workflow_host_penalty
                * workflow_transfer_penalty
                * workflow_post_penalty
                * workflow_resource_penalty
                * workflow_residency_bonus
                * workflow_overlap_bonus,
            )
        if arch == "uram_tiled" and schedule == "double_buffered":
            oracle_objective *= 0.72
        feasibility = max(0.05, min(0.98, 1.0 - max(0.0, resource - 0.80) * 1.8))
        if conditioning:
            feasibility = max(
                0.03,
                min(
                    0.99,
                    feasibility
                    - resource_pressure * max(0.0, resource - 0.74) * 0.35
                    + transfer_pressure * (0.05 if arch == "hbm_streaming" else 0.0),
                ),
            )
        risk_axes = {
            "host_control_intensity": max(host, host_pressure) if conditioning else host,
            "transfer_sync": max(transfer, transfer_pressure) if conditioning else transfer,
            "data_residency_interaction": 1.0 - data_reuse,
        }
        if conditioning:
            risk_axes.update({
                "post_processing_pressure": post_pressure,
                "workflow_resource_pressure": resource_pressure,
            })
        rows.append({
            "candidate_id": f"{scenario_id}:cand_{index:03d}",
            "design_key": f"{arch}/{residency}/{schedule}",
            "parameters": {
                "architecture_template": arch,
                "data_residency": residency,
                "runtime_schedule": schedule,
                "vector_lanes": vector_lanes,
            },
            "l1_objectives": {
                "latency_ms": l1_latency,
                "energy_mj": l1_energy,
                "resource_pressure": resource,
                "data_movement_mb": l1_data,
            },
            "l1_edp": l1_edp,
            "oracle_objective": oracle_objective,
            "constraints": {
                "resource_pressure": resource,
                "feasibility": feasibility,
            },
            "risk_axes": risk_axes,
            "uncertainty": min(1.0, 0.10 + 0.40 * abs(oracle_objective / max(l1_edp, 1.0) - 1.0)),
            "evaluation_cost": 1.0 + resource * 0.45 + (0.20 if arch == "hbm_streaming" else 0.0),
        })
    return rows


def _workflow_conditioning_from_abstraction(
    abstraction: Mapping[str, Any],
    *,
    index: int,
) -> Dict[str, Any]:
    features = abstraction.get("features", {}) if isinstance(abstraction.get("features"), Mapping) else {}
    contract = (
        abstraction.get("workflow_feature_contract", {})
        if isinstance(abstraction.get("workflow_feature_contract"), Mapping)
        else {}
    )
    graph_summary = (
        abstraction.get("graph_summary", {})
        if isinstance(abstraction.get("graph_summary"), Mapping)
        else {}
    )
    data_objects = abstraction.get("data_objects", {}) if isinstance(abstraction.get("data_objects"), Mapping) else {}
    workflow_id = str(
        contract.get("workflow_id")
        or abstraction.get("workload_id")
        or f"workflow_conditioned_{index:02d}"
    )
    workflow_classes = [str(item) for item in features.get("workflow_classes", []) or []]
    stage_count = int(_finite_or_zero(features.get("stage_count")) or _finite_or_zero(graph_summary.get("node_count")) or 1)
    host_control_events = (
        features.get("host_control_events", {})
        if isinstance(features.get("host_control_events"), Mapping)
        else {}
    )
    max_dims = features.get("max_dimensions", {}) if isinstance(features.get("max_dimensions"), Mapping) else {}
    wavefunction_bytes = _finite_or_zero(features.get("estimated_wavefunction_bytes"))
    data_movement_bytes = _finite_or_zero(features.get("estimated_total_data_movement_bytes"))
    observed_seconds = max(1.0e-9, _finite_or_zero(features.get("observed_total_phase_wall_seconds")))
    host_control_pressure = max(
        _clamp01(features.get("host_control_intensity")),
        _clamp01(
            (
                _finite_or_zero(host_control_events.get("scf_convergence_check_count"))
                + _finite_or_zero(host_control_events.get("post_processing_stage_count"))
            )
            / max(1.0, float(stage_count) * 4.0)
        ),
    )
    data_movement_pressure = max(
        _clamp01(features.get("data_movement_intensity")),
        _clamp01(data_movement_bytes / max(wavefunction_bytes, 1.0) / 8.0),
    )
    post_processing_pressure = max(
        1.0 if "post_processing" in workflow_classes else 0.0,
        _clamp01(_finite_or_zero(host_control_events.get("post_processing_stage_count")) / max(1.0, float(stage_count))),
    )
    resource_pressure = _clamp01(
        (
            _finite_or_zero(max_dims.get("nbnd")) / 96.0
            + _finite_or_zero(max_dims.get("npw")) / 16384.0
            + _finite_or_zero(max_dims.get("kpoint_count")) / 96.0
        )
        / 3.0
    )
    transfer_sync_counts: Dict[str, int] = {}
    for payload in data_objects.values():
        if not isinstance(payload, Mapping):
            continue
        hint = str(payload.get("preferred_residency_hint", ""))
        if "host_filesystem" in hint:
            transfer_sync_counts["host_checkpoint_barrier"] = transfer_sync_counts.get("host_checkpoint_barrier", 0) + 1
        elif "host_visible" in hint:
            transfer_sync_counts["host_visible_sync"] = transfer_sync_counts.get("host_visible_sync", 0) + 1
        else:
            transfer_sync_counts["device_or_pinned_reuse"] = transfer_sync_counts.get("device_or_pinned_reuse", 0) + 1
    return {
        "scenario_id": f"workflow_conditioned_{_safe_id(workflow_id)}",
        "workflow_id": workflow_id,
        "source_schema": str(abstraction.get("schema_version", "")),
        "feature_contract_schema": str(contract.get("schema_version", "")),
        "conditioning_applied_to_oracle": True,
        "stage_count": max(1, stage_count),
        "workflow_classes": workflow_classes,
        "host_control_pressure": _round(host_control_pressure),
        "data_movement_pressure": _round(data_movement_pressure),
        "post_processing_pressure": _round(post_processing_pressure),
        "resource_pressure": _round(resource_pressure),
        "observed_total_phase_wall_seconds": _round(observed_seconds),
        "estimated_total_data_movement_bytes": int(data_movement_bytes),
        "max_dimensions": dict(max_dims),
        "transfer_sync_counts": dict(sorted(transfer_sync_counts.items())),
        "conditioning_boundary": "workflow_features_shape_independent_oracle_not_hardware_evidence",
    }


def _scenario_value(scenario_id: str, axis: str, index: int) -> float:
    value = _stable_unit(scenario_id, index, axis)
    if "host_control_heavy" in scenario_id and axis == "host":
        return min(1.0, 0.55 + 0.45 * value)
    if "workflow_shift" in scenario_id and axis == "transfer":
        return min(1.0, 0.35 + 0.65 * value)
    return value


def _select_wamf(
    rows: Sequence[Mapping[str, Any]],
    budget: int,
    *,
    weights: Mapping[str, float] | None = None,
    feasibility_blind: bool = False,
) -> List[Mapping[str, Any]]:
    candidates = []
    for row in rows:
        constraints = dict(row["constraints"])
        if feasibility_blind:
            constraints["feasibility"] = 1.0
            constraints["resource_pressure"] = min(0.70, float(constraints.get("resource_pressure", 0.0)))
        candidates.append(ActiveSearchCandidate(
            candidate_id=str(row["candidate_id"]),
            objectives=dict(row["l1_objectives"]),
            constraints=constraints,
            uncertainty=float(row["uncertainty"]),
            evaluation_cost=float(row["evaluation_cost"]),
            risk_axes=dict(row["risk_axes"]),
            design_key=str(row["design_key"]),
            metadata={"source": "multifidelity_benchmark"},
        ))
    policy = MultiFidelityActiveSearchPolicy(objective_names=_OBJECTIVE_NAMES, weights=weights)
    selected_ids = [row.candidate_id for row in policy.select(candidates, budget=budget)]
    by_id = {str(row["candidate_id"]): row for row in rows}
    return [by_id[candidate_id] for candidate_id in selected_ids if candidate_id in by_id]


def _select_cheap_l1(rows: Sequence[Mapping[str, Any]], budget: int) -> List[Mapping[str, Any]]:
    ordered = sorted(rows, key=lambda row: (float(row["l1_edp"]), str(row["candidate_id"])))
    return ordered[:budget]


def _select_random(rows: Sequence[Mapping[str, Any]], budget: int, *, seed: int) -> List[Mapping[str, Any]]:
    shuffled = list(rows)
    Random(seed).shuffle(shuffled)
    return shuffled[:budget]


def _select_sequential_surrogate_ei(
    rows: Sequence[Mapping[str, Any]],
    budget: int,
) -> tuple[List[Mapping[str, Any]], List[Dict[str, Any]]]:
    """Sequential residual-surrogate baseline without peeking at unmeasured oracle rows."""

    final_budget = max(1, int(budget))
    remaining = {str(row["candidate_id"]): row for row in rows}
    selected: List[Mapping[str, Any]] = []
    observations: List[Mapping[str, Any]] = []
    trace: List[Dict[str, Any]] = []
    seed_rows = _surrogate_initial_design_rows(rows, min(3, final_budget))
    for row in seed_rows:
        candidate_id = str(row["candidate_id"])
        if candidate_id in remaining:
            observed_before = len(observations)
            selected.append(row)
            observations.append(row)
            remaining.pop(candidate_id, None)
            trace.append(_surrogate_trace_row(
                row=row,
                iteration=len(selected),
                observed_before=observed_before,
                selection_phase="initial_diverse_l1_seed",
                acquisition_score=None,
            ))
    while remaining and len(selected) < final_budget:
        scored = [
            (
                _surrogate_expected_improvement_score(candidate, observations),
                str(candidate["candidate_id"]),
                candidate,
            )
            for candidate in remaining.values()
        ]
        acquisition_score, _, row = min(scored, key=lambda item: (item[0], item[1]))
        observed_before = len(observations)
        selected.append(row)
        observations.append(row)
        remaining.pop(str(row["candidate_id"]), None)
        trace.append(_surrogate_trace_row(
            row=row,
            iteration=len(selected),
            observed_before=observed_before,
            selection_phase="surrogate_expected_improvement",
            acquisition_score=acquisition_score,
        ))
    return selected, trace


def _select_nsga2_ea_l1(
    rows: Sequence[Mapping[str, Any]],
    budget: int,
    *,
    seed: int,
) -> tuple[List[Mapping[str, Any]], List[Dict[str, Any]]]:
    """NSGA-II-style evolutionary baseline evaluated only with L1 objectives."""

    final_budget = max(1, int(budget))
    population_size = min(max(24, final_budget * 3), len(rows))
    generation_count = 5
    rng = Random(seed)
    by_key = {
        _candidate_gene_key(row): row
        for row in rows
    }
    population = _ea_initial_population(rows, population_size, rng)
    trace: List[Dict[str, Any]] = []
    for generation in range(1, generation_count + 1):
        ranked = _ea_rank_population(population)
        trace.append({
            "generation": generation,
            "population_size": len(population),
            "frontier_size": sum(1 for row in ranked if row["rank"] == 0),
            "oracle_used_for_fitness": False,
        })
        offspring = _ea_make_offspring(ranked, by_key, population_size, rng)
        population = _ea_survivor_selection([*population, *offspring], population_size)
    ranked_final = _ea_rank_population(population)
    selected: List[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    for item in sorted(ranked_final, key=lambda row: (row["rank"], -row["crowding"], _ea_l1_score(row["row"]), str(row["row"]["candidate_id"]))):
        candidate_id = str(item["row"]["candidate_id"])
        if candidate_id in seen_ids:
            continue
        selected.append(item["row"])
        seen_ids.add(candidate_id)
        if len(selected) >= final_budget:
            break
    if len(selected) < final_budget:
        for row in _select_cheap_l1(rows, final_budget):
            candidate_id = str(row["candidate_id"])
            if candidate_id in seen_ids:
                continue
            selected.append(row)
            seen_ids.add(candidate_id)
            if len(selected) >= final_budget:
                break
    return selected, trace


def _ea_initial_population(
    rows: Sequence[Mapping[str, Any]],
    population_size: int,
    rng: Random,
) -> List[Mapping[str, Any]]:
    seeds = _select_cheap_l1(rows, max(1, population_size // 3))
    shuffled = list(rows)
    rng.shuffle(shuffled)
    population: List[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    for row in [*seeds, *shuffled]:
        candidate_id = str(row["candidate_id"])
        if candidate_id in seen_ids:
            continue
        population.append(row)
        seen_ids.add(candidate_id)
        if len(population) >= population_size:
            break
    return population


def _ea_make_offspring(
    ranked_population: Sequence[Mapping[str, Any]],
    by_key: Mapping[tuple[str, str, str, int], Mapping[str, Any]],
    population_size: int,
    rng: Random,
) -> List[Mapping[str, Any]]:
    parents = [row["row"] for row in sorted(ranked_population, key=lambda item: (item["rank"], -item["crowding"], str(item["row"]["candidate_id"])))]
    if not parents:
        return []
    offspring: List[Mapping[str, Any]] = []
    attempts = 0
    while len(offspring) < population_size and attempts < population_size * 20:
        attempts += 1
        left = parents[rng.randrange(min(len(parents), max(2, population_size // 2)))]
        right = parents[rng.randrange(min(len(parents), max(2, population_size // 2)))]
        gene = _crossover_gene(left, right, rng)
        gene = _mutate_gene(gene, by_key, rng)
        child = by_key.get(gene)
        if child is not None:
            offspring.append(child)
    return offspring


def _ea_survivor_selection(
    rows: Sequence[Mapping[str, Any]],
    population_size: int,
) -> List[Mapping[str, Any]]:
    unique: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        unique.setdefault(str(row["candidate_id"]), row)
    ranked = _ea_rank_population(list(unique.values()))
    return [
        item["row"]
        for item in sorted(ranked, key=lambda row: (row["rank"], -row["crowding"], _ea_l1_score(row["row"]), str(row["row"]["candidate_id"])))[:population_size]
    ]


def _ea_rank_population(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    vectors = {str(row["candidate_id"]): _ea_objective_vector(row) for row in rows}
    fronts: List[List[Mapping[str, Any]]] = []
    remaining = list(rows)
    while remaining:
        front = [
            row for row in remaining
            if not any(
                other is not row and _dominates_vector(vectors[str(other["candidate_id"])], vectors[str(row["candidate_id"])])
                for other in remaining
            )
        ]
        fronts.append(front)
        front_ids = {str(row["candidate_id"]) for row in front}
        remaining = [row for row in remaining if str(row["candidate_id"]) not in front_ids]
    ranked: List[Dict[str, Any]] = []
    for rank, front in enumerate(fronts):
        crowding = _ea_crowding_distances(front)
        for row in front:
            ranked.append({
                "row": row,
                "rank": rank,
                "crowding": crowding.get(str(row["candidate_id"]), 0.0),
            })
    return ranked


def _ea_crowding_distances(rows: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    if not rows:
        return {}
    if len(rows) <= 2:
        return {str(row["candidate_id"]): float("inf") for row in rows}
    distances = {str(row["candidate_id"]): 0.0 for row in rows}
    for index, _name in enumerate(_OBJECTIVE_NAMES):
        ordered = sorted(rows, key=lambda row: (_ea_objective_vector(row)[index], str(row["candidate_id"])))
        distances[str(ordered[0]["candidate_id"])] = float("inf")
        distances[str(ordered[-1]["candidate_id"])] = float("inf")
        values = [_ea_objective_vector(row)[index] for row in ordered]
        span = max(values[-1] - values[0], 1.0e-9)
        for offset in range(1, len(ordered) - 1):
            candidate_id = str(ordered[offset]["candidate_id"])
            if math.isinf(distances[candidate_id]):
                continue
            distances[candidate_id] += (values[offset + 1] - values[offset - 1]) / span
    return distances


def _ea_objective_vector(row: Mapping[str, Any]) -> tuple[float, ...]:
    objectives = row.get("l1_objectives", {}) if isinstance(row.get("l1_objectives"), Mapping) else {}
    feasibility = 1.0
    if isinstance(row.get("constraints"), Mapping):
        feasibility = max(0.0, min(1.0, float(row["constraints"].get("feasibility", 1.0))))
    penalty = 1.0 + (1.0 - feasibility)
    return tuple(float(objectives.get(name, float("inf"))) * penalty for name in _OBJECTIVE_NAMES)


def _ea_l1_score(row: Mapping[str, Any]) -> float:
    vector = _ea_objective_vector(row)
    return sum(value / max(abs(value), 1.0) for value in vector)


def _dominates_vector(left: Sequence[float], right: Sequence[float]) -> bool:
    return all(a <= b for a, b in zip(left, right)) and any(a < b for a, b in zip(left, right))


def _candidate_gene_key(row: Mapping[str, Any]) -> tuple[str, str, str, int]:
    params = row.get("parameters", {}) if isinstance(row.get("parameters"), Mapping) else {}
    return (
        str(params.get("architecture_template", "")),
        str(params.get("data_residency", "")),
        str(params.get("runtime_schedule", "")),
        int(params.get("vector_lanes", 0)),
    )


def _crossover_gene(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    rng: Random,
) -> tuple[str, str, str, int]:
    left_gene = _candidate_gene_key(left)
    right_gene = _candidate_gene_key(right)
    return tuple(left_gene[index] if rng.random() < 0.5 else right_gene[index] for index in range(4))  # type: ignore[return-value]


def _mutate_gene(
    gene: tuple[str, str, str, int],
    by_key: Mapping[tuple[str, str, str, int], Mapping[str, Any]],
    rng: Random,
) -> tuple[str, str, str, int]:
    if rng.random() >= 0.35:
        return gene
    keys = list(by_key)
    replacement = keys[rng.randrange(len(keys))]
    index = rng.randrange(4)
    values = list(gene)
    values[index] = replacement[index]
    mutated = (str(values[0]), str(values[1]), str(values[2]), int(values[3]))
    return mutated if mutated in by_key else replacement


def _surrogate_trace_row(
    *,
    row: Mapping[str, Any],
    iteration: int,
    observed_before: int,
    selection_phase: str,
    acquisition_score: float | None,
) -> Dict[str, Any]:
    payload = {
        "iteration": int(iteration),
        "candidate_id": str(row["candidate_id"]),
        "selection_phase": selection_phase,
        "observed_before_selection_count": int(observed_before),
        "oracle_observation_available_after_selection": True,
        "unobserved_oracle_used_for_selection": False,
    }
    if acquisition_score is not None:
        payload["acquisition_score"] = _round(float(acquisition_score))
    return payload


def _surrogate_initial_design_rows(
    rows: Sequence[Mapping[str, Any]],
    seed_count: int,
) -> List[Mapping[str, Any]]:
    selected: List[Mapping[str, Any]] = []
    seen_keys: set[str] = set()
    for row in sorted(rows, key=lambda item: (float(item["l1_edp"]), str(item["candidate_id"]))):
        key = str(row.get("design_key", ""))
        if key in seen_keys:
            continue
        selected.append(row)
        seen_keys.add(key)
        if len(selected) >= max(1, int(seed_count)):
            break
    if len(selected) < max(1, int(seed_count)):
        selected_ids = {str(row["candidate_id"]) for row in selected}
        for row in sorted(rows, key=lambda item: (float(item["l1_edp"]), str(item["candidate_id"]))):
            if str(row["candidate_id"]) in selected_ids:
                continue
            selected.append(row)
            if len(selected) >= max(1, int(seed_count)):
                break
    return selected


def _surrogate_expected_improvement_score(
    row: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
) -> float:
    prediction = _surrogate_predicted_objective(row, observations)
    best_observed = min(float(item["oracle_objective"]) for item in observations) if observations else prediction
    residual_std = _surrogate_residual_std(observations)
    uncertainty = float(row.get("uncertainty", 0.0)) * max(float(row.get("l1_edp", 1.0)), 1.0)
    feasibility = float(row.get("constraints", {}).get("feasibility", 1.0)) if isinstance(row.get("constraints"), Mapping) else 1.0
    expected_improvement = max(0.0, best_observed - prediction) + 0.20 * residual_std + 0.15 * uncertainty
    feasibility_penalty = (1.0 - max(0.0, min(1.0, feasibility))) * max(float(row.get("l1_edp", 1.0)), 1.0)
    # Lower scores are selected first.  The term is intentionally simple: it is
    # a transparent BO-style baseline for benchmark comparison, not WAMF itself.
    return prediction - expected_improvement + feasibility_penalty


def _surrogate_predicted_objective(
    row: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
) -> float:
    l1 = float(row["l1_edp"])
    if not observations:
        return l1
    residuals = [
        float(item["oracle_objective"]) - float(item["l1_edp"])
        for item in observations
    ]
    mean_residual = sum(residuals) / len(residuals)
    params = row.get("parameters", {}) if isinstance(row.get("parameters"), Mapping) else {}
    matched = [
        float(item["oracle_objective"]) - float(item["l1_edp"])
        for item in observations
        if isinstance(item.get("parameters"), Mapping)
        and (
            item["parameters"].get("architecture_template") == params.get("architecture_template")
            or item["parameters"].get("data_residency") == params.get("data_residency")
            or item["parameters"].get("runtime_schedule") == params.get("runtime_schedule")
        )
    ]
    if matched:
        local_residual = sum(matched) / len(matched)
        return l1 + 0.45 * local_residual + 0.55 * mean_residual
    return l1 + mean_residual


def _surrogate_residual_std(observations: Sequence[Mapping[str, Any]]) -> float:
    if len(observations) < 2:
        return 0.0
    residuals = [
        float(item["oracle_objective"]) - float(item["l1_edp"])
        for item in observations
    ]
    mean = sum(residuals) / len(residuals)
    variance = sum((value - mean) ** 2 for value in residuals) / (len(residuals) - 1)
    return math.sqrt(max(0.0, variance))


def _select_manual_hbm(rows: Sequence[Mapping[str, Any]], budget: int) -> List[Mapping[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            0 if row["parameters"]["architecture_template"] == "hbm_streaming" else 1,
            0 if row["parameters"]["data_residency"] == "hot_arrays_resident" else 1,
            float(row["l1_objectives"]["data_movement_mb"]),
            str(row["candidate_id"]),
        ),
    )[:budget]


def _select_kernel_hotspot(rows: Sequence[Mapping[str, Any]], budget: int) -> List[Mapping[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -int(row["parameters"]["vector_lanes"]),
            float(row["l1_objectives"]["latency_ms"]),
            str(row["candidate_id"]),
        ),
    )[:budget]


def _policy_report(
    *,
    policy_id: str,
    selected_rows: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    budgets: Sequence[int],
    oracle_rank: Mapping[str, int],
    oracle_best: float,
    oracle_pareto_ids: set[str],
    oracle_pareto_signatures: set[tuple[str, str, str, int]],
    reference_hypervolume: float,
    top_k: int,
    uses_global_acquisition: bool,
    uses_oracle_during_selection: bool,
    extra: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    budget_curve = [
        _budget_point(
            selected_rows=selected_rows[:budget],
            budget=budget,
            oracle_rank=oracle_rank,
            oracle_best=oracle_best,
            oracle_pareto_ids=oracle_pareto_ids,
            oracle_pareto_signatures=oracle_pareto_signatures,
            reference_hypervolume=reference_hypervolume,
            top_k=top_k,
        )
        for budget in budgets
    ]
    return {
        "policy_id": policy_id,
        "selected_candidate_ids": [str(row["candidate_id"]) for row in selected_rows[: max(budgets)]],
        "uses_global_acquisition": bool(uses_global_acquisition),
        "uses_oracle_during_selection": bool(uses_oracle_during_selection),
        "budget_curve": budget_curve,
        **dict(extra or {}),
    }


def _budget_point(
    *,
    selected_rows: Sequence[Mapping[str, Any]],
    budget: int,
    oracle_rank: Mapping[str, int],
    oracle_best: float,
    oracle_pareto_ids: set[str],
    oracle_pareto_signatures: set[tuple[str, str, str, int]],
    reference_hypervolume: float,
    top_k: int,
) -> Dict[str, Any]:
    if not selected_rows:
        return {
            "budget": int(budget),
            "best_candidate_id": "",
            "best_oracle_objective": None,
            "oracle_rank_of_best": None,
            "simple_regret": None,
            "top_k_hit": False,
        }
    best = min(selected_rows, key=lambda row: (float(row["oracle_objective"]), str(row["candidate_id"])))
    best_objective = float(best["oracle_objective"])
    rank = int(oracle_rank[str(best["candidate_id"])])
    selected_ids = {str(row["candidate_id"]) for row in selected_rows}
    pareto_hit_count = len(selected_ids.intersection(oracle_pareto_ids))
    selected_pareto_signature_count = len({
        _candidate_gene_key(row)
        for row in selected_rows
    }.intersection(oracle_pareto_signatures))
    hypervolume = _oracle_hypervolume(selected_rows)
    feasibility_weighted_hypervolume = _oracle_hypervolume(
        selected_rows,
        feasibility_weighted=True,
    )
    return {
        "budget": int(budget),
        "best_candidate_id": str(best["candidate_id"]),
        "best_oracle_objective": _round(best_objective),
        "oracle_rank_of_best": rank,
        "simple_regret": _round(max(0.0, best_objective - oracle_best) / max(oracle_best, 1.0)),
        "top_k_hit": rank <= max(1, int(top_k)),
        "selected_pareto_hit_count": pareto_hit_count,
        "selected_pareto_signature_hit_count": selected_pareto_signature_count,
        "exact_oracle_pareto_coverage_at_budget": _round(
            pareto_hit_count / max(1, len(oracle_pareto_ids))
        ),
        "oracle_pareto_coverage_at_budget": _round(
            selected_pareto_signature_count / max(1, len(oracle_pareto_signatures))
        ),
        "hypervolume_ratio": _round(
            min(1.0, hypervolume / max(reference_hypervolume, 1.0e-9))
        ),
        "feasibility_weighted_hv_ratio": _round(
            min(1.0, feasibility_weighted_hypervolume / max(reference_hypervolume, 1.0e-9))
        ),
        "cost_normalized_hv_gain_at_budget": _round(
            feasibility_weighted_hypervolume
            / max(_selected_evaluation_cost(selected_rows), 1.0e-9)
        ),
    }


def _oracle_rank(rows: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    ordered = sorted(rows, key=lambda row: (float(row["oracle_objective"]), str(row["candidate_id"])))
    return {str(row["candidate_id"]): index + 1 for index, row in enumerate(ordered)}


def _oracle_pareto_candidate_ids(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    ids: List[str] = []
    for row in rows:
        vector = _oracle_quality_vector(row)
        dominated = any(
            other is not row and _dominates_vector(_oracle_quality_vector(other), vector)
            for other in rows
        )
        if not dominated:
            ids.append(str(row["candidate_id"]))
    return ids


def _oracle_quality_vector(row: Mapping[str, Any]) -> tuple[float, float, float]:
    objectives = row.get("l1_objectives", {}) if isinstance(row.get("l1_objectives"), Mapping) else {}
    return (
        float(row["oracle_objective"]),
        float(objectives.get("resource_pressure", 1.0)),
        float(objectives.get("data_movement_mb", 1.0)),
    )


def _oracle_reference_hypervolume(rows: Sequence[Mapping[str, Any]]) -> float:
    return _oracle_hypervolume(rows)


def _oracle_hypervolume(
    rows: Sequence[Mapping[str, Any]],
    *,
    feasibility_weighted: bool = False,
) -> float:
    if not rows:
        return 0.0
    selected = list(rows)
    ref_objective = max(float(row["oracle_objective"]) for row in selected) * 1.05
    ref_resource = max(
        float(row.get("l1_objectives", {}).get("resource_pressure", 1.0))
        if isinstance(row.get("l1_objectives"), Mapping)
        else 1.0
        for row in selected
    ) * 1.05
    ref_data = max(
        float(row.get("l1_objectives", {}).get("data_movement_mb", 1.0))
        if isinstance(row.get("l1_objectives"), Mapping)
        else 1.0
        for row in selected
    ) * 1.05
    volume = 0.0
    for row in selected:
        objective, resource, data = _oracle_quality_vector(row)
        row_volume = (
            max(0.0, ref_objective - objective)
            * max(0.0, ref_resource - resource)
            * max(0.0, ref_data - data)
        )
        if feasibility_weighted:
            constraints = row.get("constraints", {}) if isinstance(row.get("constraints"), Mapping) else {}
            row_volume *= max(0.0, min(1.0, float(constraints.get("feasibility", 1.0))))
        volume += row_volume
    return volume


def _selected_evaluation_cost(rows: Sequence[Mapping[str, Any]]) -> float:
    cost = 0.0
    for row in rows:
        value = float(row.get("evaluation_cost", 1.0))
        cost += value if math.isfinite(value) and value > 0.0 else 1.0
    return max(1.0e-9, cost)


def _stable_unit(*parts: Any) -> float:
    payload = "::".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(16 ** 12 - 1)


def _safe_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value).strip())
    return cleaned or "workflow"


def _clamp01(value: Any) -> float:
    number = _finite_or_zero(value)
    return max(0.0, min(1.0, number))


def _round(value: float) -> float:
    if not math.isfinite(value):
        return value
    return round(float(value), 6)


def _mean(values: Sequence[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return 0.0
    return sum(finite) / len(finite)


def _stddev(values: Sequence[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if len(finite) <= 1:
        return 0.0
    mean = _mean(finite)
    return math.sqrt(sum((value - mean) ** 2 for value in finite) / len(finite))


def _finite_or_inf(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("inf")
    return number if math.isfinite(number) else float("inf")


def _finite_or_zero(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0
