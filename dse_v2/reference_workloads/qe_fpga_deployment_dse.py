#!/usr/bin/env python3
"""QE workflow-aware FPGA deployment DSE screening.

This module is intentionally QE-adapter scoped.  It turns a QE workflow
manifest and Step2 FPGA deployment candidates into a fast L1 analytical
screening report.  The output is search evidence for deciding which candidates
deserve higher-fidelity simulation or implementation attempts; it is not FPGA
implementation evidence.
"""

from __future__ import annotations

import copy
import json
import math
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from dse_v2.mapping.multifidelity_active_search import ActiveSearchCandidate
from dse_v2.mapping.multifidelity_active_search import ActiveSearchFidelity
from dse_v2.mapping.multifidelity_active_search import ActiveSearchObservation
from dse_v2.mapping.multifidelity_active_search import MultiFidelityActiveSearchPolicy
from dse_v2.mapping.multifidelity_validation import build_multifidelity_algorithm_validation_report
from dse_v2.mapping.search_policy import SearchProblem
from dse_v2.mapping.search_policy import HierarchicalFunnelSearchPolicy
from dse_v2.reference_workloads.qe_mainflow import (
    build_qe_fpga_deployment_search_problem,
    default_qe_mainflow_workload_suite,
    workflow_bundle_from_qe_mainflow_manifest,
    validate_qe_mainflow_workload_suite,
)
from dse_v2.reference_workloads.qe_workflow_fpga_abstraction import build_qe_workflow_fpga_abstraction


QE_FPGA_L1_SCREENING_SCHEMA = "dse.qe_fpga_deployment_l1_screening.v1"
QE_FPGA_L2_REQUEST_BUNDLE_SCHEMA = "dse.qe_fpga_l2_request_bundle.v1"
QE_FPGA_IMPLEMENTATION_PACKAGE_PLAN_SCHEMA = "dse.qe_fpga_implementation_package_plan.v1"
QE_FPGA_IMPLEMENTATION_PACKAGE_MATERIALIZATION_SCHEMA = "dse.qe_fpga_implementation_package_materialization.v1"
QE_FPGA_HLS_ATTEMPT_SCHEMA = "dse.qe_fpga_hls_attempt.v1"
QE_FPGA_HLS_ATTEMPT_SUMMARY_SCHEMA = "dse.qe_fpga_hls_attempt_summary.v1"
QE_FPGA_VIVADO_ATTEMPT_SCHEMA = "dse.qe_fpga_vivado_attempt.v1"
QE_FPGA_VIVADO_ATTEMPT_SUMMARY_SCHEMA = "dse.qe_fpga_vivado_attempt_summary.v1"
QE_FPGA_SEARCH_BASELINE_REPORT_SCHEMA = "dse.qe_fpga_search_baseline_report.v1"
QE_FPGA_ADAPTIVE_MULTIFIDELITY_SEARCH_REPORT_SCHEMA = "dse.qe_fpga_adaptive_multifidelity_search_report.v1"
QE_FPGA_NEURAL_MULTIFIDELITY_SEARCH_REPORT_SCHEMA = "dse.qe_fpga_neural_multifidelity_search_report.v1"
QE_FPGA_NEURAL_SURROGATE_TRAINING_REPORT_SCHEMA = "dse.qe_fpga_neural_surrogate_training_report.v1"
QE_FPGA_NEUROMF_POLICY_EVALUATION_REPORT_SCHEMA = "dse.qe_fpga_neuromf_policy_evaluation_report.v1"
QE_FPGA_WAMF_DSE_REPORT_SCHEMA = "dse.qe_fpga_wamf_dse_report.v1"
QE_FPGA_MULTI_WORKLOAD_EXPERIMENT_REPORT_SCHEMA = "dse.qe_fpga_multi_workload_experiment_report.v1"
QE_FPGA_L1_PRIOR_NAME = "WorkflowAwareParetoFunnel"
QE_FPGA_DSE_METHOD_NAME = "WAMF-DSE"
QE_FPGA_ADAPTIVE_METHOD_NAME = "AdaptiveWorkflowMultiFidelityDSE"
QE_FPGA_NEURAL_MULTIFIDELITY_METHOD_NAME = "NeuroMF-QE-DSE"
QE_FPGA_WAMF_DSE_METHOD_NAME = "WAMF-DSE"

_POST_PROCESSING_STAGE_TYPES = {"bands", "dos", "projwfc"}
_RELAX_STAGE_TYPES = {"relax", "vc_relax"}

_BOUNDARY_MODELS: Dict[str, Dict[str, Any]] = {
    "workflow_hotspot_bundle": {
        "accelerated_fraction": 0.72,
        "transfer_multiplier": 0.78,
        "resource_pressure": 0.30,
        "host_sync_ms": 18.0,
        "explanation": "covers a multi-stage hotspot bundle and amortizes transfers across workflow phases",
    },
    "stage_cluster_bundle": {
        "accelerated_fraction": 0.55,
        "transfer_multiplier": 0.90,
        "resource_pressure": 0.20,
        "host_sync_ms": 28.0,
        "explanation": "keeps stage boundaries visible while accelerating stage clusters",
    },
    "kernel_callsite_bundle": {
        "accelerated_fraction": 0.38,
        "transfer_multiplier": 1.08,
        "resource_pressure": 0.12,
        "host_sync_ms": 42.0,
        "explanation": "minimizes integration scope but pays more per-call synchronization",
    },
}

_ARCHITECTURE_MODELS: Dict[str, Dict[str, Any]] = {
    "fpga_hbm_streaming_dataflow": {
        "speedup": 4.8,
        "resource_pressure": 0.26,
        "power_w": 34.0,
        "kernel_affinity": {"fft": 1.12, "transpose": 1.12, "h_psi": 1.05, "rho_out": 1.04},
        "explanation": "streaming dataflow favors repeated hot arrays and bandwidth-heavy kernels",
    },
    "fpga_fft_transpose_pipeline": {
        "speedup": 3.6,
        "resource_pressure": 0.18,
        "power_w": 27.0,
        "kernel_affinity": {"fft": 1.28, "transpose": 1.28, "h_psi": 0.96},
        "explanation": "specialized FFT/transpose path is narrower but lower pressure",
    },
    "fpga_hybrid_cpu_control_accel_kernels": {
        "speedup": 2.6,
        "resource_pressure": 0.13,
        "power_w": 23.0,
        "kernel_affinity": {"h_psi": 1.08, "projector": 1.08, "reduction": 1.05},
        "explanation": "CPU keeps orchestration while selected accelerator kernels reduce hotspot time",
    },
}

_SCHEDULE_MODELS: Dict[str, Dict[str, float]] = {
    "cpu_orchestrated_sequential": {"transfer_visible_fraction": 1.00, "control_overhead_ms": 36.0, "energy_factor": 1.00},
    "overlap_dma_compute": {"transfer_visible_fraction": 0.46, "control_overhead_ms": 18.0, "energy_factor": 0.93},
    "batched_stage_pipeline": {"transfer_visible_fraction": 0.62, "control_overhead_ms": 24.0, "energy_factor": 0.96},
}

_RESIDENCY_MODELS: Dict[str, Dict[str, float]] = {
    "host_resident_with_streaming_windows": {"movement_multiplier": 1.00, "resource_pressure": 0.05, "reuse_factor": 1.00},
    "fpga_hbm_resident_hot_arrays": {"movement_multiplier": 0.34, "resource_pressure": 0.24, "reuse_factor": 1.18},
    "hybrid_checkpointed_residency": {"movement_multiplier": 0.58, "resource_pressure": 0.15, "reuse_factor": 1.09},
}

_MEMORY_MODELS: Dict[str, Dict[str, float]] = {
    "ddr_streaming": {"bandwidth_gbps": 19.2, "resource_pressure": 0.06, "energy_per_mb_mj": 0.030},
    "hbm_multi_channel": {"bandwidth_gbps": 140.0, "resource_pressure": 0.24, "energy_per_mb_mj": 0.014},
    "bram_uram_tiled_locality": {"bandwidth_gbps": 62.0, "resource_pressure": 0.30, "energy_per_mb_mj": 0.010},
}

_MAPPING_MODELS: Dict[str, Dict[str, float]] = {
    "stage_phase": {"efficiency": 0.96, "resource_pressure": 0.08},
    "kernel_callsite": {"efficiency": 1.05, "resource_pressure": 0.12},
}

_HOST_RETAINED_KERNELS = {
    "mix_rho",
    "mixing",
    "diagonalization",
    "scf_control",
    "io",
    "write_bands",
    "convergence_check",
    "charge_density",
    "v_of_rho",
}


def _allows_model_level_scf_seed(manifest: Mapping[str, Any]) -> bool:
    return str(manifest.get("workflow_scope", "")) == "scf_only_measured_seed"


def _require_mainflow_or_model_seed(manifest: Mapping[str, Any], *, stage: str) -> Dict[str, Any]:
    validation = validate_qe_mainflow_workload_suite(manifest)
    if validation["valid"] or _allows_model_level_scf_seed(manifest):
        return validation
    raise ValueError(f"QE mainflow manifest must be structurally valid before {stage}")


def _require_mainflow_model_seed_or_workflow_contract(
    manifest: Mapping[str, Any],
    *,
    stage: str,
    workflow_abstraction: Mapping[str, Any] | None,
    require_workflow_feature_contract: bool,
) -> Dict[str, Any]:
    validation = validate_qe_mainflow_workload_suite(manifest)
    if validation["valid"] or _allows_model_level_scf_seed(manifest):
        return validation
    if require_workflow_feature_contract and _workflow_feature_contract_is_valid(workflow_abstraction or {}):
        contract = (workflow_abstraction or {}).get("workflow_feature_contract", {})
        workflow_dag = contract.get("workflow_dag", {}) if isinstance(contract, Mapping) and isinstance(contract.get("workflow_dag"), Mapping) else {}
        return {
            "schema_version": "dse.qe_mainflow_workload_suite_validation.v1",
            "valid": True,
            "validation_source": "workflow_feature_contract",
            "stage": stage,
            "mainflow_manifest_valid": False,
            "workflow_id": str(contract.get("workflow_id", "")) if isinstance(contract, Mapping) else "",
            "workflow_stage_count": int(workflow_dag.get("stage_count", 0) or 0),
            "claim_boundary": "workflow_contract_validation_for_model_search_only_not_mainflow_case_or_hardware_evidence",
        }
    raise ValueError(f"QE mainflow manifest must be structurally valid before {stage}")


def build_qe_fpga_l1_screening_report(
    manifest: Mapping[str, Any],
    problem: SearchProblem | Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    promotion_budget: int = 4,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    """Evaluate QE FPGA deployment candidates with a transparent L1 model."""

    validation = _require_mainflow_model_seed_or_workflow_contract(
        manifest,
        stage="L1 screening",
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )

    problem_payload = problem.to_dict() if isinstance(problem, SearchProblem) else dict(problem)
    constraints = dict(problem_payload.get("constraints", {}) or {})
    workload_features = _extract_workload_features(
        manifest,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )

    rows = [
        _evaluate_candidate(workload_features, constraints, candidate)
        for candidate in candidates
    ]
    _annotate_pareto(rows)
    pareto_frontier = [
        copy.deepcopy(row)
        for row in rows
        if row["dominance"]["pareto_rank"] == 0
        and row["promotion"]["release_pareto_eligible"] is True
    ]
    pareto_frontier.sort(key=_promotion_sort_key)
    release_backup_pool = [
        copy.deepcopy(row)
        for row in rows
        if row["promotion"]["release_pareto_eligible"] is True
    ]
    release_backup_pool.sort(key=_promotion_sort_key)
    diverse_frontier = _dedupe_by_design_key([*pareto_frontier, *release_backup_pool])
    promotion_selection = _select_diverse_promotions(
        diverse_frontier,
        promotion_budget=max(0, int(promotion_budget)),
        workload_features=workload_features,
    )

    promotion_queue: List[Dict[str, Any]] = []
    for row in promotion_selection:
        promoted = copy.deepcopy(row)
        promoted["promotion"]["recommended"] = True
        promoted["promotion"]["recommended_next_fidelity"] = "L2_systemc_or_tlm"
        promoted["promotion"]["rationale"] = [
            "release_non_dominated_l1_candidate",
            "diversity_preserved_for_expensive_followup",
            "workload_risk_active_selection",
            "cheap_model_selected_for_expensive_followup",
        ]
        if promoted.get("dominance", {}).get("pareto_rank") != 0:
            promoted["promotion"]["rationale"][0] = "release_feasible_l1_candidate_backup"
        promotion_queue.append(promoted)

    promoted_ids = {row["candidate_id"] for row in promotion_queue}
    for row in rows:
        if row["candidate_id"] in promoted_ids:
            row["promotion"]["recommended"] = True
            row["promotion"]["recommended_next_fidelity"] = "L2_systemc_or_tlm"
            row["promotion"]["rationale"] = [
                "release_non_dominated_l1_candidate",
                "diversity_preserved_for_expensive_followup",
                "workload_risk_active_selection",
                "cheap_model_selected_for_expensive_followup",
            ]
            if row.get("dominance", {}).get("pareto_rank") != 0:
                row["promotion"]["rationale"][0] = "release_feasible_l1_candidate_backup"

    return {
        "schema_version": QE_FPGA_L1_SCREENING_SCHEMA,
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "prior_name": QE_FPGA_L1_PRIOR_NAME,
        "component_role": "cheap_full_space_prior",
        "problem_id": str(problem_payload.get("problem_id", "")),
        "workload_run_id": str(problem_payload.get("workload_run_id", "")),
        "fidelity": "L1_analytical_workflow_model",
        "workflow_scope": str(manifest.get("workflow_scope", "full_qe_mainflow")),
        "validation": dict(validation),
        "release_completion_eligible": bool(validation.get("valid", False)),
        "workload_features": workload_features,
        "candidate_count": len(candidates),
        "candidate_evaluations": rows,
        "pareto_frontier": pareto_frontier,
        "promotion_queue": promotion_queue,
        "promotion_budget": int(promotion_budget),
        "promotion_policy": {
            "policy": "workload_risk_aware_active_pareto_selection",
            "design_key_fields": [
                "architecture_template",
                "offload_boundary",
                "mapping_granularity",
                "runtime_schedule",
                "data_residency",
                "memory_topology",
                "vector_lanes",
                "hbm_channel_count",
                "tile_doubles",
                "precision_policy",
            ],
            "diversity_axes": ["architecture_template", "risk_countermeasure", "vector_lanes", "hbm_channel_count"],
            "hardware_microarchitecture_knobs": [
                "vector_lanes",
                "hbm_channel_count",
                "tile_doubles",
            ],
            "risk_features": [
                "host_control_intensity",
                "post_processing_intensity",
                "variant_data_scale",
            ],
        },
        "model_assumptions": {
            "latency_model": "workflow phase weights split into host-retained, accelerated compute, visible transfer, and host synchronization",
            "energy_model": "compute power by architecture plus movement energy by memory topology",
            "pareto_objectives_minimized": [
                "estimated_workflow_wall_time_ms",
                "estimated_energy_mj",
                "fpga_resource_pressure",
                "estimated_data_movement_mb",
                "infeasibility_penalty",
            ],
            "calibration_status": "uncalibrated_l1_model_pending_l2_l3_l4_and_vivado_feedback",
        },
        "claim_boundary": "l1_screening_only_not_fpga_implementation_evidence",
    }


def build_qe_fpga_l2_request_bundle(
    manifest: Mapping[str, Any],
    problem: SearchProblem | Mapping[str, Any],
    promotion_queue: Sequence[Mapping[str, Any]],
    *,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    """Materialize promoted QE FPGA candidates as replayable L2 requests.

    The bundle is an execution handoff artifact only.  It does not run TLM,
    SystemC, gem5, HLS, or FPGA tools.
    """

    validation = _require_mainflow_model_seed_or_workflow_contract(
        manifest,
        stage="L2 request construction",
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )

    problem_payload = problem.to_dict() if isinstance(problem, SearchProblem) else dict(problem)
    features = _extract_workload_features(
        manifest,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    requests = [
        _build_l2_request(
            manifest=manifest,
            problem_payload=problem_payload,
            workload_features=features,
            promoted_row=row,
            index=index,
        )
        for index, row in enumerate(promotion_queue)
        if isinstance(row, Mapping)
    ]
    workflow_feature_contract = _workload_feature_contract_binding(features)
    return {
        "schema_version": QE_FPGA_L2_REQUEST_BUNDLE_SCHEMA,
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "problem_id": str(problem_payload.get("problem_id", "")),
        "workload_run_id": str(problem_payload.get("workload_run_id", "")),
        "backend": "systemc_or_tlm",
        "feature_source_priority": list(features.get("feature_source_priority", []) or []),
        "workflow_feature_contract": workflow_feature_contract,
        "request_count": len(requests),
        "requests": requests,
        "execution_allowed": False,
        "next_step": "execute_selected_requests_with_l2_tlm_or_l3_systemc_runner",
        "claim_boundary": "l2_request_bundle_only_not_executed_systemc_or_fpga_evidence",
    }


def run_qe_fpga_l2_tlm_requests(
    request_bundle: Mapping[str, Any],
) -> Dict[str, Any]:
    """Execute QE FPGA L2 request payloads with a deterministic Python TLM."""

    requests = [
        request for request in request_bundle.get("requests", []) or []
        if isinstance(request, Mapping)
    ]
    results = [_evaluate_l2_request(request, index) for index, request in enumerate(requests)]
    passed_count = sum(1 for row in results if row.get("status") == "passed")
    return {
        "schema_version": "dse.qe_fpga_l2_tlm_results.v1",
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "problem_id": str(request_bundle.get("problem_id", "")),
        "workload_run_id": str(request_bundle.get("workload_run_id", "")),
        "fidelity": "L2_python_tlm",
        "request_count": len(requests),
        "executed_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "results": results,
        "model_assumptions": {
            "model": "request_graph_transaction_level_host_fpga_model",
            "host_device_transfer_model": "transaction_latency_plus_bandwidth_from_request_architecture",
            "compute_model": "stage_weight_scaled_by_architecture_template_and_deployment_boundary",
            "calibration_role": "mid_fidelity_feedback_for_l1_ranking",
        },
        "claim_boundary": "l2_tlm_model_result_not_systemc_gem5_or_fpga_implementation_evidence",
    }


def build_qe_fpga_l2_calibration_report(
    l1_screening: Mapping[str, Any],
    l2_results: Mapping[str, Any],
) -> Dict[str, Any]:
    """Compare L1 promoted-candidate estimates against L2 TLM results.

    The report is still model-level feedback, but it now carries a fitted
    affine calibration and fail-closed blockers so downstream search does not
    treat uncalibrated or rank-inverting feedback as an acquisition signal.
    """

    l1_by_candidate: Dict[str, Mapping[str, Any]] = {}
    for row in l1_screening.get("candidate_evaluations", []) or []:
        if isinstance(row, Mapping):
            l1_by_candidate[str(row.get("candidate_id", ""))] = row
    for row in l1_screening.get("promotion_queue", []) or []:
        if isinstance(row, Mapping):
            l1_by_candidate[str(row.get("candidate_id", ""))] = row

    samples: List[Dict[str, Any]] = []
    for row in l2_results.get("results", []) or []:
        if not isinstance(row, Mapping):
            continue
        candidate_id = str(row.get("candidate_id", ""))
        l1_row = l1_by_candidate.get(candidate_id, {})
        l1_metrics = l1_row.get("metrics", {}) if isinstance(l1_row.get("metrics"), Mapping) else {}
        l2_metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
        l1_latency = _finite_float(l1_metrics.get("estimated_workflow_wall_time_ms"), default=0.0)
        l2_latency = _finite_float(l2_metrics.get("tlm_workflow_wall_time_ms"), default=0.0)
        l1_energy = _finite_float(l1_metrics.get("estimated_energy_mj"), default=0.0)
        l2_energy = _finite_float(l2_metrics.get("tlm_energy_mj"), default=0.0)
        latency_model = _fit_affine_calibration([l1_latency], [l2_latency])
        energy_model = _fit_affine_calibration([l1_energy], [l2_energy])
        samples.append({
            "candidate_id": candidate_id,
            "design_key": str(row.get("design_key", "")),
            "l1_latency_ms": l1_latency,
            "l2_latency_ms": l2_latency,
            "latency_abs_error_ms": abs(l2_latency - l1_latency),
            "latency_ape_percent": _ape_percent(l1_latency, l2_latency),
            "l1_energy_mj": l1_energy,
            "l2_energy_mj": l2_energy,
            "energy_ape_percent": _ape_percent(l1_energy, l2_energy),
        })

    latency_mape = _mean([sample["latency_ape_percent"] for sample in samples])
    energy_mape = _mean([sample["energy_ape_percent"] for sample in samples])
    latency_model = _fit_affine_calibration(
        [sample["l1_latency_ms"] for sample in samples],
        [sample["l2_latency_ms"] for sample in samples],
    )
    energy_model = _fit_affine_calibration(
        [sample["l1_energy_mj"] for sample in samples],
        [sample["l2_energy_mj"] for sample in samples],
    )
    for sample in samples:
        calibrated_latency = (
            _finite_float(latency_model.get("scale"), default=1.0) * sample["l1_latency_ms"]
            + _finite_float(latency_model.get("bias"), default=0.0)
        )
        calibrated_energy = (
            _finite_float(energy_model.get("scale"), default=1.0) * sample["l1_energy_mj"]
            + _finite_float(energy_model.get("bias"), default=0.0)
        )
        sample["calibrated_l1_latency_ms"] = _round_metric(calibrated_latency)
        sample["calibrated_l1_energy_mj"] = _round_metric(calibrated_energy)
        sample["calibrated_latency_abs_error_ms"] = _round_metric(abs(calibrated_latency - sample["l2_latency_ms"]))
        sample["calibrated_energy_abs_error_mj"] = _round_metric(abs(calibrated_energy - sample["l2_energy_mj"]))

    latency_residuals = [sample["calibrated_latency_abs_error_ms"] for sample in samples]
    energy_residuals = [sample["calibrated_energy_abs_error_mj"] for sample in samples]
    latency_p95_abs_error = _percentile(latency_residuals, 0.95)
    energy_p95_abs_error = _percentile(energy_residuals, 0.95)
    spearman = _spearman(
        [sample["l1_latency_ms"] for sample in samples],
        [sample["l2_latency_ms"] for sample in samples],
    )
    blockers: List[str] = []
    if len(samples) < 5:
        blockers.append("insufficient_paired_l1_l2_samples")
    if not math.isfinite(spearman):
        blockers.append("nonfinite_rank_correlation")
    elif spearman < 0.0:
        blockers.append("negative_rank_correlation_between_l1_and_l2")
    latency_range = max(
        [sample["l2_latency_ms"] for sample in samples],
        default=0.0,
    ) - min(
        [sample["l2_latency_ms"] for sample in samples],
        default=0.0,
    )
    latency_error_threshold = max(1000.0, 0.25 * max(1.0, latency_range))
    if latency_p95_abs_error > latency_error_threshold:
        blockers.append("calibration_prediction_error_above_feedback_threshold")
    if "negative_rank_correlation_between_l1_and_l2" in blockers:
        status = "blocked_calibration_rank_inversion"
    elif "calibration_prediction_error_above_feedback_threshold" in blockers:
        status = "blocked_calibration_error_too_high"
    elif blockers:
        status = "needs_more_samples"
    else:
        status = "usable_for_feedback"
    use_for_feedback = status == "usable_for_feedback"
    return {
        "schema_version": "dse.qe_fpga_l1_l2_calibration.v1",
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "sample_count": len(samples),
        "latency_mape_percent": _round_metric(latency_mape),
        "energy_mape_percent": _round_metric(energy_mape),
        "spearman_rank_correlation": _round_metric(spearman if math.isfinite(spearman) else 0.0),
        "calibration_model": {
            "latency_ms": latency_model,
            "energy_mj": energy_model,
        },
        "prediction_interval": {
            "latency_ms": {
                "p95_abs_error": _round_metric(latency_p95_abs_error),
                "feedback_error_threshold": _round_metric(latency_error_threshold),
                "coverage": "in_sample_p95_abs_residual_model_level_only",
            },
            "energy_mj": {
                "p95_abs_error": _round_metric(energy_p95_abs_error),
                "coverage": "in_sample_p95_abs_residual_model_level_only",
            },
        },
        "calibration_status": status,
        "blockers": blockers,
        "samples": samples,
        "feedback_recommendation": {
            "use_l2_to_reorder_promoted_candidates": use_for_feedback,
            "collect_more_l2_samples": not use_for_feedback,
            "next_required_fidelity": "L3_systemc",
        },
        "claim_boundary": "calibration_feedback_only_not_final_ranking_or_fpga_evidence",
    }


def build_qe_fpga_search_baseline_report(
    manifest: Mapping[str, Any],
    problem: SearchProblem | Mapping[str, Any],
    l1_screening: Mapping[str, Any],
    *,
    evaluation_budget: int = 5,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    """Compare search policies and ablations with a common L2 TLM oracle."""

    validation = _require_mainflow_model_seed_or_workflow_contract(
        manifest,
        stage="search baseline evaluation",
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    problem_payload = problem.to_dict() if isinstance(problem, SearchProblem) else dict(problem)
    rows = [
        row for row in l1_screening.get("candidate_evaluations", []) or []
        if isinstance(row, Mapping)
        and _is_release_candidate(row)
    ]
    budget = max(1, int(evaluation_budget))
    oracle_results = _l2_oracle_results_for_rows(
        manifest,
        problem_payload,
        rows,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    oracle_rank = _oracle_rank_from_l2_results(oracle_results)
    wamf_closed_loop_rows, wamf_closed_loop_trace = _policy_wamf_generic_active_pareto_closed_loop(
        rows,
        l1_screening,
        budget,
        observation_results_by_candidate=oracle_results,
    )
    policy_rows = [
        _evaluate_search_policy(
            manifest=manifest,
            problem_payload=problem_payload,
            policy_id="wamf_generic_active_pareto",
            selected_rows=wamf_closed_loop_rows,
            oracle_rank=oracle_rank,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
            selection_basis={
                "baseline_type": "proposed_generic_algorithm_kernel",
                "uses_workflow_abstraction": True,
                "uses_multi_fidelity_promotion": True,
                "uses_pareto_selection": True,
                "uses_workload_risk_active_selection": True,
                "uses_generic_acquisition_kernel": True,
                "generic_kernel_policy": "wamf_constrained_active_pareto",
                "closed_loop_feedback": True,
                "feedback_source": "previous_l2_observations_during_policy_loop",
                "static_global_acquisition": False,
                "prior_seed_policy": "workflow_aware_pareto_funnel",
                "prior_seed_count": len([
                    row for row in wamf_closed_loop_trace
                    if row.get("prior_seed_used") is True
                ]),
                "feedback_observation_count": len([
                    row for row in wamf_closed_loop_trace
                    if row.get("observation_available") is True
                ]),
                "promotion_safeguard": _wamf_promotion_safeguard_summary(wamf_closed_loop_trace),
            },
        ),
        _evaluate_search_policy(
            manifest=manifest,
            problem_payload=problem_payload,
            policy_id="workflow_aware_pareto_funnel",
            selected_rows=_policy_workflow_aware_pareto(l1_screening, rows, budget),
            oracle_rank=oracle_rank,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
            selection_basis={
                "baseline_type": "cheap_workflow_prior",
                "uses_workflow_abstraction": True,
                "uses_multi_fidelity_promotion": True,
                "uses_pareto_selection": True,
                "uses_workload_risk_active_selection": True,
                "uses_generic_acquisition_kernel": False,
            },
        ),
        _evaluate_search_policy(
            manifest=manifest,
            problem_payload=problem_payload,
            policy_id="random_seeded",
            selected_rows=_policy_seeded_random(rows, budget),
            oracle_rank=oracle_rank,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
            selection_basis={
                "baseline_type": "random",
                "uses_workflow_abstraction": False,
                "uses_multi_fidelity_promotion": False,
                "uses_pareto_selection": False,
            },
        ),
        _evaluate_search_policy(
            manifest=manifest,
            problem_payload=problem_payload,
            policy_id="manual_hbm_streaming_heuristic",
            selected_rows=_policy_manual_hbm(rows, budget),
            oracle_rank=oracle_rank,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
            selection_basis={
                "baseline_type": "manual_heuristic",
                "uses_workflow_abstraction": False,
                "uses_multi_fidelity_promotion": False,
                "uses_pareto_selection": False,
            },
        ),
        _evaluate_search_policy(
            manifest=manifest,
            problem_payload=problem_payload,
            policy_id="nsga2_lite_multi_objective",
            selected_rows=_policy_nsga2_lite(rows, budget),
            oracle_rank=oracle_rank,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
            selection_basis={
                "baseline_type": "evolutionary_multi_objective",
                "selection_algorithm": "deterministic_nsga2_lite",
                "uses_workflow_abstraction": False,
                "uses_multi_fidelity_promotion": False,
                "uses_pareto_selection": True,
                "objective_count": 4,
                "objectives_minimized": [
                    "estimated_workflow_wall_time_ms",
                    "estimated_energy_mj",
                    "fpga_resource_pressure",
                    "estimated_data_movement_mb",
                ],
            },
        ),
        _evaluate_search_policy(
            manifest=manifest,
            problem_payload=problem_payload,
            policy_id="single_fidelity_l1_edp",
            selected_rows=_policy_single_fidelity_l1(rows, budget),
            oracle_rank=oracle_rank,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
            selection_basis={
                "baseline_type": "single_fidelity_model",
                "uses_workflow_abstraction": True,
                "uses_multi_fidelity_promotion": False,
                "uses_pareto_selection": False,
            },
        ),
        _evaluate_search_policy(
            manifest=manifest,
            problem_payload=problem_payload,
            policy_id="kernel_level_hotspot_only",
            selected_rows=_policy_kernel_hotspot_only(rows, budget),
            oracle_rank=oracle_rank,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
            selection_basis={
                "baseline_type": "kernel_level_search_ablation",
                "uses_workflow_abstraction": False,
                "uses_multi_fidelity_promotion": False,
                "uses_pareto_selection": False,
            },
        ),
        _evaluate_search_policy(
            manifest=manifest,
            problem_payload=problem_payload,
            policy_id="no_workflow_abstraction_ablation",
            selected_rows=_policy_no_workflow_abstraction(rows, budget),
            oracle_rank=oracle_rank,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
            selection_basis={
                "baseline_type": "ablation",
                "uses_workflow_abstraction": False,
                "uses_multi_fidelity_promotion": True,
                "uses_pareto_selection": True,
            },
        ),
    ]
    budget_sweep = _build_search_budget_sweep(
        l1_screening=l1_screening,
        rows=rows,
        policy_rows=policy_rows,
        oracle_results=oracle_results,
        oracle_rank=oracle_rank,
        evaluation_budget=budget,
        wamf_closed_loop_trace=wamf_closed_loop_trace,
    )
    feature_ablation_report = _build_feature_ablation_report(
        l1_screening=l1_screening,
        rows=rows,
        budget=budget,
        oracle_results=oracle_results,
        oracle_rank=oracle_rank,
    )
    independent_feedback_coverage_plan = _build_independent_feedback_coverage_plan(
        l1_screening=l1_screening,
        policy_rows=policy_rows,
        feature_ablation_report=feature_ablation_report,
        evaluation_budget=budget,
    )
    algorithm_validation = build_multifidelity_algorithm_validation_report(
        proposed_policy_id="wamf_generic_active_pareto",
        policy_results=_baseline_policy_rows_for_algorithm_validation(policy_rows),
    )
    policy_rows.sort(key=lambda row: (
        _finite_float(row.get("l2_oracle", {}).get("best_tlm_edp") if isinstance(row.get("l2_oracle"), Mapping) else None, default=float("inf")),
        str(row.get("policy_id", "")),
    ))
    best_policy = _best_policy_with_tie_break(
        policy_rows,
        workload_features=l1_screening.get("workload_features", {})
        if isinstance(l1_screening.get("workload_features"), Mapping)
        else {},
    )
    workflow_abstraction = _wamf_workflow_abstraction_summary(l1_screening)
    return {
        "schema_version": QE_FPGA_SEARCH_BASELINE_REPORT_SCHEMA,
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "problem_id": str(problem_payload.get("problem_id", "")),
        "workload_run_id": str(problem_payload.get("workload_run_id", "")),
        "oracle_fidelity": "L2_python_tlm",
        "validation": dict(validation),
        "workflow_abstraction": workflow_abstraction,
        "candidate_count": int(l1_screening.get("candidate_count", len(rows))),
        "release_candidate_count": len(rows),
        "evaluation_budget": budget,
        "proposed_method_policy_id": "wamf_generic_active_pareto",
        "cheap_prior_policy_id": "workflow_aware_pareto_funnel",
        "policy_count": len(policy_rows),
        "policies": policy_rows,
        "budget_sweep": budget_sweep,
        "feature_ablation_report": feature_ablation_report,
        "independent_feedback_coverage_plan": independent_feedback_coverage_plan,
        "algorithm_validation": algorithm_validation,
        "best_policy_by_l2_edp": {
            "policy_id": str(best_policy.get("policy_id", "")),
            "best_tlm_edp": (
                best_policy.get("l2_oracle", {}).get("best_tlm_edp")
                if isinstance(best_policy.get("l2_oracle"), Mapping)
                else None
            ),
            "tie_break_basis": str(best_policy.get("tie_break_basis", "")),
        },
        "experiment_limitations": [
            "L2_python_tlm_is_a_model_oracle_not_real_hardware",
            "oracle_rank_ties_use_0.05_percent_relative_edp_tolerance",
            "search_effectiveness_must_be_rechecked_with_L3_L4_HLS_Vivado_feedback",
            "random_policy_is_seeded_for_reproducibility",
            "random_multi_seed_reproducible_not_statistical_proof",
        ],
        "claim_boundary": "search_baseline_l2_tlm_only_not_final_hardware_evidence",
    }


def _baseline_policy_rows_for_algorithm_validation(
    policy_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in policy_rows:
        if not isinstance(row, Mapping):
            continue
        oracle = row.get("l2_oracle", {}) if isinstance(row.get("l2_oracle"), Mapping) else {}
        rank = _finite_float(oracle.get("oracle_rank_of_best_selected"), default=float("inf"))
        rows.append({
            "policy_id": str(row.get("policy_id", "")),
            "final_best_edp": _finite_float(oracle.get("best_tlm_edp"), default=float("inf")),
            "final_oracle_rank": int(rank) if math.isfinite(rank) and rank > 0.0 else None,
            "top_k_hit": bool(rank <= 5.0) if math.isfinite(rank) else None,
        })
    return rows


def build_qe_fpga_adaptive_multifidelity_search_report(
    manifest: Mapping[str, Any],
    problem: SearchProblem | Mapping[str, Any],
    l1_screening: Mapping[str, Any],
    *,
    evaluation_budget: int = 8,
    initial_designs: int = 3,
    top_k: int = 5,
    external_feedback: Sequence[Mapping[str, Any]] | None = None,
    include_retrospective_oracle: bool = True,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    """Run a replayable adaptive L1->L2 search loop for method development.

    This loop is intentionally lightweight, but it is adaptive: each L2
    observation updates an online residual surrogate before the next acquisition
    decision.  The L2 feedback is still model-level and cannot be used as
    hardware evidence.
    """

    validation = _require_mainflow_model_seed_or_workflow_contract(
        manifest,
        stage="adaptive search evaluation",
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    problem_payload = problem.to_dict() if isinstance(problem, SearchProblem) else dict(problem)
    rows = [
        row for row in l1_screening.get("candidate_evaluations", []) or []
        if isinstance(row, Mapping)
        and _is_release_candidate(row)
    ]
    budget = min(max(1, int(evaluation_budget)), len(rows))
    seed_count = min(max(1, int(initial_designs)), budget)
    resolved_top_k = max(1, int(top_k))
    workload_features = l1_screening.get("workload_features", {}) if isinstance(l1_screening.get("workload_features"), Mapping) else {}
    external_feedback_rows, external_feedback_summary = _normalize_external_feedback_samples(
        external_feedback or [],
        allowed_candidate_ids={str(row.get("candidate_id", "")) for row in rows},
    )
    feature_names = _adaptive_feature_names()
    model_state = _initial_adaptive_surrogate(feature_names)
    evaluated_ids: set[str] = set()
    used_external_ids: set[str] = set()
    external_common_objective_ids: set[str] = set()
    l2_executed_ids: set[str] = set()
    common_objective_ids: set[str] = set()
    observed_results: Dict[str, Dict[str, Any]] = {}
    trace: List[Dict[str, Any]] = []
    budget_curve: List[Dict[str, Any]] = []
    best_result: Mapping[str, Any] | None = None

    seed_rows = _adaptive_initial_seed_rows(l1_screening, rows, seed_count, workload_features)
    for step_index in range(budget):
        if step_index < len(seed_rows):
            selected = seed_rows[step_index]
            phase = "initial_diverse_l1_seed"
            acquisition = _initial_seed_acquisition(selected, step_index)
        else:
            selected, acquisition = _select_adaptive_candidate(
                rows,
                evaluated_ids=evaluated_ids,
                model_state=model_state,
                workload_features=workload_features,
            )
            phase = "adaptive_acquisition"
        candidate_id = str(selected.get("candidate_id", ""))
        if not candidate_id:
            break
        evaluated_ids.add(candidate_id)
        external_observation = external_feedback_rows.get(candidate_id)
        external_payload: Dict[str, Any] | None = None
        external_common_objective_used = False
        if external_observation is not None:
            used_external_ids.add(candidate_id)
            external_payload = _adaptive_observation_payload(external_observation)
            if _observation_common_objective_eligible(external_observation):
                observation = external_observation
                observation_source = "external_feedback_calibrated_common_objective"
                external_common_objective_used = True
                external_common_objective_ids.add(candidate_id)
            else:
                observation = _evaluate_single_l2_row(
                    manifest,
                    problem_payload,
                    selected,
                    workflow_abstraction=workflow_abstraction,
                    require_workflow_feature_contract=require_workflow_feature_contract,
                )
                observation_source = "external_feedback_diagnostic_plus_L2_python_tlm"
                l2_executed_ids.add(candidate_id)
        else:
            observation_source = "L2_python_tlm"
            observation = _evaluate_single_l2_row(
                manifest,
                problem_payload,
                selected,
                workflow_abstraction=workflow_abstraction,
                require_workflow_feature_contract=require_workflow_feature_contract,
            )
            l2_executed_ids.add(candidate_id)
        common_objective_used = _observation_common_objective_eligible(observation)
        if common_objective_used:
            common_objective_ids.add(candidate_id)
            observed_results[candidate_id] = copy.deepcopy(dict(observation))
            model_state = _update_adaptive_surrogate(model_state, selected, observation, workload_features)
            if best_result is None or _observation_sort_key(observation) < _observation_sort_key(best_result):
                best_result = observation
        best_candidate_id = str(best_result.get("candidate_id", "")) if best_result is not None else ""
        best_objective = _observation_objective(best_result) if best_result is not None else None
        observation_payload = _adaptive_observation_payload(observation)
        trace_row = {
            "iteration": step_index + 1,
            "candidate_id": candidate_id,
            "design_key": str(selected.get("design_key", "")),
            "selection_phase": phase,
            "candidate_parameters": dict(selected.get("parameters", {}) if isinstance(selected.get("parameters"), Mapping) else {}),
            "l1_metrics": dict(selected.get("metrics", {}) if isinstance(selected.get("metrics"), Mapping) else {}),
            "acquisition": acquisition,
            "observation_source": observation_source,
            "l2_observation": observation_payload,
            "common_objective_observation": observation_payload,
            "common_objective_used": common_objective_used,
            "surrogate_after_update": _adaptive_surrogate_summary(model_state),
        }
        if external_payload is not None:
            trace_row["external_feedback_observation"] = external_payload
            trace_row["external_feedback_common_objective_used"] = external_common_objective_used
        trace.append(trace_row)
        budget_curve.append({
            "evaluations": step_index + 1,
            "best_candidate_id": best_candidate_id,
            "best_observed_objective_so_far": _round_metric(best_objective) if best_objective is not None else None,
            "best_observation_fidelity": str(best_result.get("fidelity", "")) if best_result is not None else "",
            "best_observation_source": (
                "L2_python_tlm"
                if best_result is not None and str(best_result.get("fidelity", "")) == "L2_python_tlm"
                else "external_feedback"
                if best_result is not None
                else ""
            ),
            "oracle_rank_of_best_so_far": None,
            "simple_regret": None,
            "top_k_hit": None,
            "oracle_status": "not_precomputed_in_method_loop",
        })

    final_result = {
        "best_candidate_id": str(best_result.get("candidate_id", "")) if best_result is not None else "",
        "best_observed_objective": (
            _round_metric(_observation_objective(best_result))
            if best_result is not None
            else None
        ),
        "best_observation_fidelity": str((best_result or {}).get("fidelity", "")),
        "oracle_rank_of_best": None,
        "top_k_hit": None,
        "rank_basis": "not_available_without_retrospective_oracle",
    }
    oracle_summary = _adaptive_retrospective_oracle_report(
        manifest=manifest,
        problem_payload=problem_payload,
        rows=rows,
        budget_curve=budget_curve,
        final_result=final_result,
        top_k=resolved_top_k,
        include_retrospective_oracle=include_retrospective_oracle,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )

    return {
        "schema_version": QE_FPGA_ADAPTIVE_MULTIFIDELITY_SEARCH_REPORT_SCHEMA,
        "method_name": QE_FPGA_ADAPTIVE_METHOD_NAME,
        "execution_mode": "budget_limited_lazy_feedback",
        "problem_id": str(problem_payload.get("problem_id", "")),
        "workload_run_id": str(problem_payload.get("workload_run_id", "")),
        "validation": dict(validation),
        "candidate_count": int(l1_screening.get("candidate_count", len(rows))),
        "release_candidate_count": len(rows),
        "evaluation_budget": budget,
        "initial_design_count": seed_count,
        "evaluated_count": len(trace),
        "top_k": resolved_top_k,
        "fidelity_sequence": (
            ["L1_analytical_workflow_model", "external_high_fidelity_feedback", "L2_python_tlm"]
            if external_feedback_rows
            else ["L1_analytical_workflow_model", "L2_python_tlm"]
        ),
        "adaptive_policy": {
            "acquisition": "cost_aware_ucb_expected_improvement_hybrid",
            "uses_l2_feedback": True,
            "uses_external_high_fidelity_feedback": bool(external_feedback_rows),
            "uses_workload_features": True,
            "seed_policy": "promotion_queue_plus_architecture_diverse_l1",
            "candidate_filter": "release_fp64_step2_screenable_candidates",
        },
        "external_feedback_summary": {
            **external_feedback_summary,
            "used_sample_count": len(used_external_ids),
            "used_candidate_ids": sorted(used_external_ids),
            "common_objective_used_sample_count": len(external_common_objective_ids),
            "common_objective_used_candidate_ids": sorted(external_common_objective_ids),
            "diagnostic_only_sample_count": len(used_external_ids - external_common_objective_ids),
        },
        "fidelity_cost_accounting": {
            "full_l2_oracle_precomputed": False,
            "retrospective_l2_oracle_computed_after_method_loop": bool(
                oracle_summary.get("retrospective_oracle_computed_after_method_loop", False)
            ),
            "release_candidate_count": len(rows),
            "evaluation_budget": budget,
            "total_observation_count": len(trace),
            "common_objective_observation_count": len(common_objective_ids),
            "common_objective_candidate_ids": sorted(common_objective_ids),
            "l2_python_tlm_executed_count": len(l2_executed_ids),
            "l2_python_tlm_executed_candidate_ids": sorted(l2_executed_ids),
            "external_feedback_used_count": len(used_external_ids),
            "external_feedback_used_candidate_ids": sorted(used_external_ids),
            "external_feedback_common_objective_count": len(external_common_objective_ids),
            "external_feedback_common_objective_candidate_ids": sorted(external_common_objective_ids),
            "observed_candidate_count": len(observed_results),
            "cost_unit": "one_selected_candidate_observation",
            "accounting_boundary": "method_loop_only_excludes_retrospective_baseline_oracle",
        },
        "surrogate_model": _adaptive_surrogate_summary(model_state),
        "budget_curve": budget_curve,
        "evaluation_trace": trace,
        "final_result": final_result,
        "oracle_summary": oracle_summary,
        "experiment_limitations": (
            [
                "external_feedback_samples_are_used_only_when_candidate_id_and_metrics_are_valid",
                "surrogate_is_online_method_development_state_not_a_validated_predictor",
                "external_fidelity_metrics_are_not_mixed_with_L2_raw_EDP_without_calibration",
                "remaining_candidates_without_external_samples_use_L2_python_tlm_model_feedback",
                "DAC_grade_results_require_replayable_SystemC_gem5_HLS_Vivado_artifact_adjudication",
            ]
            if external_feedback_rows
            else [
                "L2_python_tlm_is_model_feedback_not_independent_hardware_evidence",
                "surrogate_is_online_method_development_state_not_a_validated_predictor",
                "DAC_grade_results_require_L3_SystemC_gem5_HLS_Vivado_feedback",
            ]
        ),
        "claim_boundary": "adaptive_multifidelity_search_model_development_only_not_hardware_evidence",
    }


def build_qe_fpga_neural_multifidelity_search_report(
    manifest: Mapping[str, Any],
    problem: SearchProblem | Mapping[str, Any],
    l1_screening: Mapping[str, Any],
    *,
    evaluation_budget: int = 8,
    initial_designs: int = 3,
    top_k: int = 5,
    ensemble_size: int = 5,
    include_retrospective_oracle: bool = True,
    trained_surrogate: Mapping[str, Any] | None = None,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    """Run the NeuroMF-QE-DSE algorithm-contract prototype.

    The current backend is deliberately lightweight: a bootstrap tabular
    residual/rank surrogate that can be replaced by a heterogeneous GNN once
    enough measured QE/HLS/Vivado feedback exists.  It is still a model-level
    search artifact, not hardware evidence.
    """

    validation = _require_mainflow_model_seed_or_workflow_contract(
        manifest,
        stage="neural multi-fidelity search evaluation",
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    problem_payload = problem.to_dict() if isinstance(problem, SearchProblem) else dict(problem)
    rows = [
        row for row in l1_screening.get("candidate_evaluations", []) or []
        if isinstance(row, Mapping)
        and _is_release_candidate(row)
    ]
    budget = min(max(1, int(evaluation_budget)), len(rows))
    seed_count = min(max(1, int(initial_designs)), budget)
    resolved_top_k = max(1, int(top_k))
    resolved_ensemble_size = max(3, int(ensemble_size))
    workload_features = l1_screening.get("workload_features", {}) if isinstance(l1_screening.get("workload_features"), Mapping) else {}
    feature_schema = _neural_feature_schema()
    trained_surrogate_use = _trained_surrogate_use_summary(trained_surrogate)
    model_state = _initial_neural_surrogate(feature_schema, ensemble_size=resolved_ensemble_size)
    if trained_surrogate_use["status"] == "enabled":
        model_state["trained_surrogate"] = copy.deepcopy(dict(trained_surrogate or {}))
        model_state["trained_surrogate_use"] = dict(trained_surrogate_use)
    evaluated_ids: set[str] = set()
    l2_executed_ids: set[str] = set()
    trace: List[Dict[str, Any]] = []
    budget_curve: List[Dict[str, Any]] = []
    best_result: Mapping[str, Any] | None = None

    seed_rows = _neural_initial_design_rows(l1_screening, rows, seed_count, workload_features)
    for step_index in range(budget):
        if step_index < len(seed_rows):
            selected = seed_rows[step_index]
            phase = "coverage_diverse_initial_design"
            acquisition = _neural_initial_acquisition(selected, step_index)
        else:
            selected, acquisition = _select_neural_candidate(
                rows,
                evaluated_ids=evaluated_ids,
                model_state=model_state,
                workload_features=workload_features,
            )
            phase = "neural_surrogate_acquisition"
        candidate_id = str(selected.get("candidate_id", ""))
        if not candidate_id:
            break
        evaluated_ids.add(candidate_id)
        observation = _evaluate_single_l2_row(
            manifest,
            problem_payload,
            selected,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
        )
        l2_executed_ids.add(candidate_id)
        if _observation_common_objective_eligible(observation):
            model_state = _update_neural_surrogate(model_state, selected, observation, workload_features)
            if best_result is None or _observation_sort_key(observation) < _observation_sort_key(best_result):
                best_result = observation
        best_candidate_id = str(best_result.get("candidate_id", "")) if best_result is not None else ""
        best_objective = _observation_objective(best_result) if best_result is not None else None
        observation_payload = _adaptive_observation_payload(observation)
        trace.append({
            "iteration": step_index + 1,
            "candidate_id": candidate_id,
            "design_key": str(selected.get("design_key", "")),
            "selection_phase": phase,
            "candidate_parameters": dict(selected.get("parameters", {}) if isinstance(selected.get("parameters"), Mapping) else {}),
            "l1_metrics": dict(selected.get("metrics", {}) if isinstance(selected.get("metrics"), Mapping) else {}),
            "acquisition": acquisition,
            "observation_source": "L2_python_tlm",
            "l2_observation": observation_payload,
            "common_objective_observation": observation_payload,
            "common_objective_used": _observation_common_objective_eligible(observation),
            "surrogate_after_update": _neural_surrogate_summary(model_state),
        })
        budget_curve.append({
            "evaluations": step_index + 1,
            "best_candidate_id": best_candidate_id,
            "best_observed_objective_so_far": _round_metric(best_objective) if best_objective is not None else None,
            "best_observation_fidelity": str(best_result.get("fidelity", "")) if best_result is not None else "",
            "best_observation_source": "L2_python_tlm" if best_result is not None else "",
            "oracle_rank_of_best_so_far": None,
            "simple_regret": None,
            "top_k_hit": None,
            "oracle_status": "not_precomputed_in_method_loop",
        })

    final_result = {
        "best_candidate_id": str(best_result.get("candidate_id", "")) if best_result is not None else "",
        "best_observed_objective": (
            _round_metric(_observation_objective(best_result))
            if best_result is not None
            else None
        ),
        "best_observation_fidelity": str((best_result or {}).get("fidelity", "")),
        "oracle_rank_of_best": None,
        "top_k_hit": None,
        "rank_basis": "not_available_without_retrospective_oracle",
    }
    oracle_summary = _adaptive_retrospective_oracle_report(
        manifest=manifest,
        problem_payload=problem_payload,
        rows=rows,
        budget_curve=budget_curve,
        final_result=final_result,
        top_k=resolved_top_k,
        include_retrospective_oracle=include_retrospective_oracle,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )

    return {
        "schema_version": QE_FPGA_NEURAL_MULTIFIDELITY_SEARCH_REPORT_SCHEMA,
        "method_name": QE_FPGA_NEURAL_MULTIFIDELITY_METHOD_NAME,
        "execution_mode": "budget_limited_lazy_surrogate_feedback",
        "problem_id": str(problem_payload.get("problem_id", "")),
        "workload_run_id": str(problem_payload.get("workload_run_id", "")),
        "validation": dict(validation),
        "workload_features": copy.deepcopy(dict(workload_features)),
        "candidate_count": int(l1_screening.get("candidate_count", len(rows))),
        "release_candidate_count": len(rows),
        "evaluation_budget": budget,
        "initial_design_count": seed_count,
        "evaluated_count": len(trace),
        "top_k": resolved_top_k,
        "fidelity_sequence": ["L1_analytical_workflow_model", "neural_surrogate_ranker", "L2_python_tlm"],
        "neural_method_contract": {
            "algorithm_family": "surrogate_assisted_multifidelity_dse",
            "workload_conditioned": True,
            "candidate_conditioned": True,
            "rank_objective": "pairwise_or_listwise_top_k_ranking_preferred",
            "regression_targets": ["latency_ms", "energy_mj", "edp", "resource_pressure"],
            "uncertainty_target": "calibrated_prediction_interval_or_deep_ensemble_variance",
            "promotion_policy": "cost_aware_expected_improvement_top_k_pareto_gain",
            "high_fidelity_feedback_required_for_paper_results": True,
        },
        "feature_schema": feature_schema,
        "surrogate_model": _neural_surrogate_summary(model_state),
        "trained_surrogate_use": trained_surrogate_use,
        "fidelity_cost_accounting": {
            "full_l2_oracle_precomputed": False,
            "retrospective_l2_oracle_computed_after_method_loop": bool(
                oracle_summary.get("retrospective_oracle_computed_after_method_loop", False)
            ),
            "release_candidate_count": len(rows),
            "evaluation_budget": budget,
            "total_observation_count": len(trace),
            "l2_python_tlm_executed_count": len(l2_executed_ids),
            "l2_python_tlm_executed_candidate_ids": sorted(l2_executed_ids),
            "cost_unit": "one_selected_candidate_observation",
            "accounting_boundary": "method_loop_only_excludes_retrospective_baseline_oracle",
        },
        "budget_curve": budget_curve,
        "evaluation_trace": trace,
        "final_result": final_result,
        "oracle_summary": oracle_summary,
        "experiment_status": "algorithm_contract_prototype_not_dac_final",
        "experiment_limitations": [
            "L2_python_tlm_is_model_feedback_not_independent_hardware_evidence",
            "neural_backend_currently_bootstrap_tabular_not_trained_gnn",
            *(
                ["trained_surrogate_is_model_feedback_not_hardware_evidence"]
                if trained_surrogate_use["status"] == "enabled"
                else []
            ),
            "uncertainty_is_model_development_signal_not_calibrated_high_fidelity_confidence",
            "DAC_grade_results_require_measured_QE_corpus_L3_HLS_Vivado_feedback",
        ],
        "claim_boundary": "neural_multifidelity_search_algorithm_prototype_only_not_hardware_evidence",
    }


def build_qe_fpga_neural_surrogate_training_report(
    manifest: Mapping[str, Any],
    problem: SearchProblem | Mapping[str, Any],
    l1_screening: Mapping[str, Any],
    neural_search: Mapping[str, Any],
    *,
    ensemble_size: int = 5,
    max_epochs: int = 80,
    seed: int = 17,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    """Train a replayable tabular neural surrogate from observed feedback.

    This is the first real neural backend artifact for NeuroMF-QE-DSE.  It
    trains on observed L2/L3-style feedback rows already admitted by the
    multi-fidelity loop; it is not hardware evidence and does not replace HLS,
    Vivado, or QE correctness validation.
    """

    validation = _require_mainflow_model_seed_or_workflow_contract(
        manifest,
        stage="neural surrogate training",
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    problem_payload = problem.to_dict() if isinstance(problem, SearchProblem) else dict(problem)
    rows_by_candidate = {
        str(row.get("candidate_id", "")): row
        for row in l1_screening.get("candidate_evaluations", []) or []
        if isinstance(row, Mapping)
    }
    samples = _neural_training_samples(rows_by_candidate, neural_search)
    feature_schema = _neural_training_feature_schema(samples)
    encoded = _encode_neural_training_samples(samples, feature_schema)
    split_rows = _split_neural_training_rows(encoded, seed=int(seed))
    training_result = _train_tabular_neural_ensemble(
        encoded,
        split_rows=split_rows,
        ensemble_size=max(1, int(ensemble_size)),
        max_epochs=max(1, int(max_epochs)),
        seed=int(seed),
    )
    metrics = _neural_training_metrics(encoded, split_rows, training_result["predictions"])
    uncertainty = _neural_uncertainty_report(encoded, split_rows, training_result["predictions"])
    preview = _neural_inference_preview(encoded, training_result["predictions"])
    graph_dataset_contract = _neural_graph_dataset_contract(samples)
    graph_dataset_samples = _neural_graph_dataset_samples(samples)
    ood_evaluation = _neural_ood_evaluation(samples)
    sample_count = len(samples)
    training_status = (
        "trained_model_development_artifact"
        if sample_count >= 8 and split_rows["holdout"]
        else "trained_with_limited_sample_warning"
    )
    return {
        "schema_version": QE_FPGA_NEURAL_SURROGATE_TRAINING_REPORT_SCHEMA,
        "method_name": QE_FPGA_NEURAL_MULTIFIDELITY_METHOD_NAME,
        "training_status": training_status,
        "problem_id": str(problem_payload.get("problem_id", "")),
        "workload_run_id": str(problem_payload.get("workload_run_id", "")),
        "validation": dict(validation),
        "backend": {
            "framework": "torch",
            "model_type": "tabular_mlp_deep_ensemble",
            "ensemble_size": max(1, int(ensemble_size)),
            "objective": "predict_log_common_objective_edp_residual_over_l1_and_rank_candidates",
            "loss": "mse_log_edp_residual",
            "max_epochs": max(1, int(max_epochs)),
            "seed": int(seed),
            **dict(training_result.get("backend_runtime", {}) if isinstance(training_result.get("backend_runtime"), Mapping) else {}),
        },
        "dataset": {
            "sample_count": sample_count,
            "target_name": "log_common_objective_edp_residual_over_l1",
            "observation_fidelities": sorted({str(sample.get("fidelity", "")) for sample in samples if sample.get("fidelity")}),
            "source_artifacts": [
                "qe_fpga_l1_screening_report.json",
                "qe_fpga_neural_multifidelity_search_report.json",
            ],
            "candidate_ids": [str(sample.get("candidate_id", "")) for sample in samples],
            "boundary": "observed_multifidelity_feedback_samples_only",
        },
        "graph_dataset_contract": graph_dataset_contract,
        "graph_dataset_samples": graph_dataset_samples,
        "ood_evaluation": ood_evaluation,
        "splits": {
            name: {
                "count": len(indices),
                "candidate_ids": [str(encoded[index]["candidate_id"]) for index in indices],
            }
            for name, indices in split_rows.items()
        },
        "feature_schema": feature_schema,
        "normalizer": training_result["normalizer"],
        "checkpoint": training_result["checkpoint"],
        "metrics": metrics,
        "uncertainty": uncertainty,
        "inference_preview": preview,
        "limitations": [
            "training_feedback_currently_uses_model_level_L2_or_L3_observations_when_real_tool_feedback_is_absent",
            "small_sample_training_artifact_not_statistical_DAC_result",
            "tabular_backend_is_a_stepping_stone_toward_heterogeneous_workflow_candidate_GNN",
            "DAC_grade_results_require_measured_QE_corpus_and_HLS_Vivado_feedback",
        ],
        "claim_boundary": "trained_neural_surrogate_development_artifact_not_hardware_evidence",
    }


def build_qe_fpga_neuromf_policy_evaluation_report(
    manifest: Mapping[str, Any],
    problem: SearchProblem | Mapping[str, Any],
    l1_screening: Mapping[str, Any],
    *,
    unguided_neural_search: Mapping[str, Any],
    trained_neural_search: Mapping[str, Any],
    trained_surrogate: Mapping[str, Any],
    evaluation_budget: int = 8,
    external_feedback: Sequence[Mapping[str, Any]] | None = None,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    """Compare NeuroMF search quality against baseline DSE policies."""

    validation = _require_mainflow_model_seed_or_workflow_contract(
        manifest,
        stage="NeuroMF policy evaluation",
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    problem_payload = problem.to_dict() if isinstance(problem, SearchProblem) else dict(problem)
    rows = [
        row for row in l1_screening.get("candidate_evaluations", []) or []
        if isinstance(row, Mapping)
        and _is_release_candidate(row)
    ]
    budget = max(1, int(evaluation_budget))
    oracle_results = _l2_oracle_results_for_rows(
        manifest,
        problem_payload,
        rows,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    oracle_rank = _oracle_rank_from_l2_results(oracle_results)
    oracle_best_edp = _oracle_best_edp(oracle_results)
    external_feedback_by_candidate, external_feedback_summary = _normalize_external_feedback_samples(
        list(external_feedback or []),
        allowed_candidate_ids={str(row.get("candidate_id", "")) for row in rows},
    )
    row_by_id = {str(row.get("candidate_id", "")): row for row in rows}
    workload_features = (
        l1_screening.get("workload_features", {})
        if isinstance(l1_screening.get("workload_features"), Mapping)
        else {}
    )
    initial_external_observations = _active_search_observations_from_external_feedback_samples(
        external_feedback_by_candidate.values(),
        prior_rows_by_candidate=row_by_id,
        workload_features=workload_features,
    )
    external_common_objective_count = len(initial_external_observations)
    wamf_closed_loop_rows, wamf_closed_loop_trace = _policy_wamf_generic_active_pareto_closed_loop(
        rows,
        l1_screening,
        budget,
        observation_results_by_candidate=oracle_results,
        external_feedback_by_candidate=external_feedback_by_candidate,
        initial_observations=initial_external_observations,
    )
    policy_specs: List[Tuple[str, Sequence[Mapping[str, Any]], Dict[str, Any]]] = [
        (
            "wamf_generic_active_pareto",
            wamf_closed_loop_rows,
            {
                "baseline_type": "proposed_generic_algorithm_kernel",
                "uses_workflow_abstraction": True,
                "uses_multi_fidelity_feedback": True,
                "uses_trained_surrogate": False,
                "uses_pareto_selection": True,
                "uses_active_selection": True,
                "uses_generic_acquisition_kernel": True,
                "generic_kernel_policy": "wamf_constrained_active_pareto",
                "closed_loop_feedback": True,
                "feedback_source": (
                    "external_common_objective_plus_l2_observations"
                    if external_common_objective_count > 0
                    else "previous_l2_observations_during_policy_loop"
                ),
                "static_global_acquisition": False,
                "feedback_observation_count": len([
                    row for row in wamf_closed_loop_trace
                    if row.get("observation_available") is True
                ]),
                "external_feedback_common_objective_count": external_common_objective_count,
                "initial_external_feedback_observation_count": len(initial_external_observations),
                "promotion_safeguard": _wamf_promotion_safeguard_summary(wamf_closed_loop_trace),
            },
        ),
        (
            "neuromf_trained_surrogate",
            _policy_rows_from_neural_trace(trained_neural_search, rows, budget),
            {
                "baseline_type": "proposed_neural_method",
                "uses_workflow_abstraction": True,
                "uses_multi_fidelity_feedback": True,
                "uses_trained_surrogate": True,
                "uses_pareto_selection": True,
                "uses_active_selection": True,
                "trained_surrogate_artifact": "qe_fpga_neural_surrogate_training_report.json",
            },
        ),
        (
            "neuromf_unguided_bootstrap",
            _policy_rows_from_neural_trace(unguided_neural_search, rows, budget),
            {
                "baseline_type": "neural_without_trained_backend",
                "uses_workflow_abstraction": True,
                "uses_multi_fidelity_feedback": True,
                "uses_trained_surrogate": False,
                "uses_pareto_selection": True,
                "uses_active_selection": True,
            },
        ),
        (
            "workflow_aware_pareto_funnel",
            _policy_workflow_aware_pareto(l1_screening, rows, budget),
            {
                "baseline_type": "cheap_workflow_prior",
                "component_role": "l1_workflow_prior_baseline",
                "uses_workflow_abstraction": True,
                "uses_multi_fidelity_feedback": False,
                "uses_trained_surrogate": False,
                "uses_pareto_selection": True,
                "uses_active_selection": False,
            },
        ),
        (
            "random_seeded",
            _policy_seeded_random(rows, budget),
            {
                "baseline_type": "random",
                "uses_workflow_abstraction": False,
                "uses_multi_fidelity_feedback": False,
                "uses_trained_surrogate": False,
                "uses_pareto_selection": False,
                "uses_active_selection": False,
            },
        ),
        (
            "manual_hbm_streaming_heuristic",
            _policy_manual_hbm(rows, budget),
            {
                "baseline_type": "manual_heuristic",
                "uses_workflow_abstraction": False,
                "uses_multi_fidelity_feedback": False,
                "uses_trained_surrogate": False,
                "uses_pareto_selection": False,
                "uses_active_selection": False,
            },
        ),
        (
            "nsga2_lite_multi_objective",
            _policy_nsga2_lite(rows, budget),
            {
                "baseline_type": "evolutionary_multi_objective",
                "uses_workflow_abstraction": False,
                "uses_multi_fidelity_feedback": False,
                "uses_trained_surrogate": False,
                "uses_pareto_selection": True,
                "uses_active_selection": False,
            },
        ),
        (
            "single_fidelity_l1_edp",
            _policy_single_fidelity_l1(rows, budget),
            {
                "baseline_type": "single_fidelity_model",
                "uses_workflow_abstraction": True,
                "uses_multi_fidelity_feedback": False,
                "uses_trained_surrogate": False,
                "uses_pareto_selection": False,
                "uses_active_selection": False,
            },
        ),
        (
            "kernel_level_hotspot_only",
            _policy_kernel_hotspot_only(rows, budget),
            {
                "baseline_type": "kernel_level_search_ablation",
                "uses_workflow_abstraction": False,
                "uses_multi_fidelity_feedback": False,
                "uses_trained_surrogate": False,
                "uses_pareto_selection": False,
                "uses_active_selection": False,
            },
        ),
    ]
    policies = []
    for policy_id, selected_rows, selection_basis in policy_specs:
        policies.append(_policy_evaluation_row(
            policy_id=policy_id,
            selected_rows=selected_rows,
            oracle_results=oracle_results,
            oracle_rank=oracle_rank,
            oracle_best_edp=oracle_best_edp,
            selection_basis=selection_basis,
            final_budget=budget,
            closed_loop_feedback_trace=(
                wamf_closed_loop_trace if policy_id == "wamf_generic_active_pareto" else None
            ),
        ))
    policies.sort(key=lambda row: (
        _finite_float(row.get("budget_curve", [{}])[-1].get("simple_regret") if row.get("budget_curve") else None, default=float("inf")),
        _finite_float(row.get("budget_curve", [{}])[-1].get("oracle_rank_of_best") if row.get("budget_curve") else None, default=float("inf")),
        str(row.get("policy_id", "")),
    ))
    best_policy = policies[0] if policies else {}
    trained_row = next((row for row in policies if row.get("policy_id") == "neuromf_trained_surrogate"), {})
    trained_final = (
        trained_row.get("budget_curve", [])[-1]
        if isinstance(trained_row.get("budget_curve"), list) and trained_row.get("budget_curve")
        else {}
    )
    return {
        "schema_version": QE_FPGA_NEUROMF_POLICY_EVALUATION_REPORT_SCHEMA,
        "method_name": QE_FPGA_NEURAL_MULTIFIDELITY_METHOD_NAME,
        "problem_id": str(problem_payload.get("problem_id", "")),
        "workload_run_id": str(problem_payload.get("workload_run_id", "")),
        "validation": dict(validation),
        "oracle_fidelity": "L2_python_tlm",
        "candidate_count": int(l1_screening.get("candidate_count", len(rows))),
        "release_candidate_count": len(rows),
        "evaluation_budget": budget,
        "policy_count": len(policies),
        "policies": policies,
        "best_policy_by_final_regret": {
            "policy_id": str(best_policy.get("policy_id", "")),
            "simple_regret": (
                best_policy.get("budget_curve", [{}])[-1].get("simple_regret")
                if isinstance(best_policy.get("budget_curve"), list) and best_policy.get("budget_curve")
                else None
            ),
            "oracle_rank_of_best": (
                best_policy.get("budget_curve", [{}])[-1].get("oracle_rank_of_best")
                if isinstance(best_policy.get("budget_curve"), list) and best_policy.get("budget_curve")
                else None
            ),
        },
        "aggregate": {
            "trained_neuromf_final_regret": trained_final.get("simple_regret"),
            "trained_neuromf_rank": 1 + sum(
                1
                for row in policies
                if _policy_final_regret(row) < _policy_final_regret(trained_row)
            ) if trained_row else None,
            "policy_ids_ranked_by_final_regret": [str(row.get("policy_id", "")) for row in policies],
        },
        "trained_surrogate_ref": {
            "artifact": "qe_fpga_neural_surrogate_training_report.json",
            "schema_version": str(trained_surrogate.get("schema_version", "")),
            "sample_count": (
                int(trained_surrogate.get("dataset", {}).get("sample_count", 0))
                if isinstance(trained_surrogate.get("dataset"), Mapping)
                else 0
            ),
        },
        "external_feedback_summary": {
            **external_feedback_summary,
            "common_objective_used_sample_count": external_common_objective_count,
        },
        "limitations": [
            "L2_python_tlm_policy_oracle_is_not_hardware_or_QE_correctness_evidence",
            "policy_comparison_uses_replayable_model_oracle_before_L3_HLS_Vivado_feedback",
            "random_policy_is_seeded_for_reproducibility_not_statistical_exhaustiveness",
            "DAC_grade_policy_results_require_measured_QE_corpus_and_physical_tool_feedback",
        ],
        "claim_boundary": "policy_evaluation_model_oracle_only_not_final_hardware_evidence",
    }


def build_qe_fpga_wamf_dse_report(
    manifest: Mapping[str, Any],
    problem: SearchProblem | Mapping[str, Any],
    l1_screening: Mapping[str, Any],
    *,
    evaluation_budget: int = 8,
    initial_designs: int = 3,
    neural_ensemble_size: int = 5,
    neural_training_epochs: int = 80,
    top_k: int = 5,
    adaptive_search: Mapping[str, Any] | None = None,
    unguided_neural_search: Mapping[str, Any] | None = None,
    trained_neural_search: Mapping[str, Any] | None = None,
    neural_surrogate_training: Mapping[str, Any] | None = None,
    policy_evaluation: Mapping[str, Any] | None = None,
    search_baseline: Mapping[str, Any] | None = None,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    """Build the unified WAMF-DSE algorithm report.

    This report is intentionally an algorithm-level artifact.  It consolidates
    the existing L1 prior, active feedback loop, neural surrogate backend, and
    policy comparisons under a single method identity without treating FPGA tool
    evidence as the search objective.
    """

    validation = _require_mainflow_model_seed_or_workflow_contract(
        manifest,
        stage="WAMF-DSE algorithm report",
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    problem_payload = problem.to_dict() if isinstance(problem, SearchProblem) else dict(problem)
    budget = max(1, int(evaluation_budget))
    seed_count = max(1, int(initial_designs))
    ensemble_size = max(3, int(neural_ensemble_size))
    training_epochs = max(1, int(neural_training_epochs))

    adaptive_search = (
        dict(adaptive_search)
        if isinstance(adaptive_search, Mapping)
        else build_qe_fpga_adaptive_multifidelity_search_report(
            manifest,
            problem_payload,
            l1_screening,
            evaluation_budget=budget,
            initial_designs=seed_count,
            top_k=top_k,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
        )
    )
    unguided_neural_search = (
        dict(unguided_neural_search)
        if isinstance(unguided_neural_search, Mapping)
        else build_qe_fpga_neural_multifidelity_search_report(
            manifest,
            problem_payload,
            l1_screening,
            evaluation_budget=max(budget, 10),
            initial_designs=seed_count,
            top_k=top_k,
            ensemble_size=ensemble_size,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
        )
    )
    neural_surrogate_training = (
        dict(neural_surrogate_training)
        if isinstance(neural_surrogate_training, Mapping)
        else build_qe_fpga_neural_surrogate_training_report(
            manifest,
            problem_payload,
            l1_screening,
            unguided_neural_search,
            ensemble_size=ensemble_size,
            max_epochs=training_epochs,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
        )
    )
    trained_neural_search = (
        dict(trained_neural_search)
        if isinstance(trained_neural_search, Mapping)
        else build_qe_fpga_neural_multifidelity_search_report(
            manifest,
            problem_payload,
            l1_screening,
            evaluation_budget=budget,
            initial_designs=seed_count,
            top_k=top_k,
            ensemble_size=ensemble_size,
            trained_surrogate=neural_surrogate_training,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
        )
    )
    policy_evaluation = (
        dict(policy_evaluation)
        if isinstance(policy_evaluation, Mapping)
        else build_qe_fpga_neuromf_policy_evaluation_report(
            manifest,
            problem_payload,
            l1_screening,
            unguided_neural_search=unguided_neural_search,
            trained_neural_search=trained_neural_search,
            trained_surrogate=neural_surrogate_training,
            evaluation_budget=budget,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
        )
    )
    baseline = (
        dict(search_baseline)
        if isinstance(search_baseline, Mapping)
        else build_qe_fpga_search_baseline_report(
            manifest,
            problem_payload,
            l1_screening,
            evaluation_budget=min(budget, max(1, len(l1_screening.get("candidate_evaluations", []) or []))),
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
        )
    )
    generic_acquisition_kernel = _wamf_generic_acquisition_kernel_report(
        l1_screening,
        trained_neural_search,
        budget=budget,
    )
    generic_action_selection_kernel = _wamf_generic_action_selection_report(
        l1_screening,
        trained_neural_search,
        budget=budget,
    )
    generic_acquisition_contract = (
        generic_acquisition_kernel.get("algorithm_contract", {})
        if isinstance(generic_acquisition_kernel.get("algorithm_contract"), Mapping)
        else {}
    )

    return {
        "schema_version": QE_FPGA_WAMF_DSE_REPORT_SCHEMA,
        "method_name": QE_FPGA_WAMF_DSE_METHOD_NAME,
        "method_full_name": "Workflow-Abstraction-Guided Multi-Fidelity Active DSE",
        "algorithm_family": "workflow_conditioned_multifidelity_active_pareto_dse",
        "problem_id": str(problem_payload.get("problem_id", "")),
        "workload_run_id": str(problem_payload.get("workload_run_id", "")),
        "validation": dict(validation),
        "formal_algorithm_contract": _wamf_formal_algorithm_contract(
            problem_payload=problem_payload,
            l1_screening=l1_screening,
            budget=budget,
            initial_designs=seed_count,
            generic_acquisition_kernel=generic_acquisition_kernel,
            generic_action_selection_kernel=generic_action_selection_kernel,
            neural_surrogate_training=neural_surrogate_training,
            trained_neural_search=trained_neural_search,
            policy_evaluation=policy_evaluation,
        ),
        "problem_formulation": {
            "input": "qe_workflow_bundle",
            "workflow_abstraction": "qe_workflow_graph_compute_control_data_movement",
            "candidate_space": "fpga_deployment_space",
            "candidate_variables": _wamf_search_space_axes(problem_payload),
            "objective_vector": [
                "latency",
                "energy",
                "edp",
                "resource_pressure",
                "data_movement",
                "feasibility_risk",
            ],
            "optimization_target": "budget_limited_pareto_frontier_approximation",
            "expensive_evaluation_budget": budget,
        },
        "workflow_abstraction": _wamf_workflow_abstraction_summary(l1_screening),
        "deployment_search_space": {
            "axes": _wamf_search_space_axes(problem_payload),
            "parameter_grid_size": int(problem_payload.get("parameter_grid_size", 0)),
            "candidate_count": int(l1_screening.get("candidate_count", 0)),
            "release_candidate_count": int(policy_evaluation.get("release_candidate_count", 0)),
            "constraints": dict(problem_payload.get("constraints", {}) if isinstance(problem_payload.get("constraints"), Mapping) else {}),
        },
        "model_stack": {
            "l1_prior": {
                "artifact": "qe_fpga_l1_screening_report",
                "source_prior_name": str(l1_screening.get("prior_name", "")),
                "parent_method_name": str(l1_screening.get("method_name", "")),
                "method_role": "cheap_full_space_prior",
                "fidelity": str(l1_screening.get("fidelity", "")),
                "candidate_count": int(l1_screening.get("candidate_count", 0)),
                "pareto_frontier_count": len(l1_screening.get("pareto_frontier", []) or []),
            },
            "surrogate": {
                "artifact": "qe_fpga_neural_surrogate_training_report",
                "method_role": "calibrated_residual_uncertainty_model",
                "backend": str(trained_neural_search.get("surrogate_model", {}).get("model_type", "")) if isinstance(trained_neural_search.get("surrogate_model"), Mapping) else "",
                "training_sample_count": int(neural_surrogate_training.get("dataset", {}).get("sample_count", 0)) if isinstance(neural_surrogate_training.get("dataset"), Mapping) else 0,
                "uncertainty": dict(neural_surrogate_training.get("uncertainty", {}) if isinstance(neural_surrogate_training.get("uncertainty"), Mapping) else {}),
                "graph_backend_contract": str(neural_surrogate_training.get("feature_schema", {}).get("graph_backend_contract", "")) if isinstance(neural_surrogate_training.get("feature_schema"), Mapping) else "",
            },
            "active_feedback": {
                "artifact": "qe_fpga_adaptive_multifidelity_search_report",
                "method_role": "budget_limited_candidate_selection",
                "fidelity_sequence": list(adaptive_search.get("fidelity_sequence", []) or []),
                "evaluated_count": int(adaptive_search.get("evaluated_count", 0)),
            },
        },
        "active_pareto_acquisition": {
            "selection_rule": "maximize_cost_aware_constrained_ehvi_proxy",
            "acquisition_family": str(
                generic_acquisition_contract.get("acquisition_family", "cost_aware_constrained_ehvi_proxy")
            ),
            "formal_objective_vector": [
                "estimated_workflow_wall_time_ms",
                "estimated_energy_mj",
                "fpga_resource_pressure",
                "estimated_data_movement_mb",
                "infeasibility_penalty",
            ],
            "reference_point": _wamf_acquisition_reference_point(l1_screening),
            "constraints": {
                "resource_pressure": "<= platform_release_threshold",
                "precision_policy": "fp64_strict_for_release",
                "implementation_feasibility": "positive_probability_required",
            },
            "scoring_equation": (
                "a(x,f)=EHVI_proxy(x;P_ref) * P_feasible(x) * I(f) / cost(x,f) "
                "+ lambda_u*sigma(x) "
                "+ lambda_r*workflow_risk_coverage(x) + lambda_d*design_diversity(x) "
                "- lambda_v*violation_risk(x)"
            ),
            "implementation_backend": str(trained_neural_search.get("neural_method_contract", {}).get("promotion_policy", "")) if isinstance(trained_neural_search.get("neural_method_contract"), Mapping) else "",
            "components": [
                "constrained_hypervolume_improvement_proxy",
                "cost_normalized_hv_gain",
                "feasibility_weighted_hv_gain",
                "uncertainty",
                "workflow_risk_coverage",
                "design_diversity",
                "evaluation_cost",
                "feasibility_risk",
            ],
            "workflow_risk_axes": [
                "host_control_intensity",
                "post_processing_intensity",
                "data_object_lifetime",
                "transfer_sync",
            ],
            "generic_acquisition_kernel": generic_acquisition_kernel,
            "generic_action_selection_kernel": generic_action_selection_kernel,
            "trace_artifacts": [
                "qe_fpga_adaptive_multifidelity_search_report",
                "qe_fpga_neural_multifidelity_search_report",
            ],
            "hardware_evidence_use": "validation_and_calibration_only_not_search_objective",
        },
        "next_evaluation_actions": _wamf_next_evaluation_actions_summary(
            generic_action_selection_kernel
        ),
        "fidelity_feedback_trace": {
            "adaptive": list(adaptive_search.get("evaluation_trace", []) or []),
            "neural": list(trained_neural_search.get("evaluation_trace", []) or []),
            "cost_accounting": dict(trained_neural_search.get("fidelity_cost_accounting", {}) if isinstance(trained_neural_search.get("fidelity_cost_accounting"), Mapping) else {}),
        },
        "pareto_candidates": {
            "frontier_count": len(l1_screening.get("pareto_frontier", []) or []),
            "frontier": [copy.deepcopy(dict(row)) for row in l1_screening.get("pareto_frontier", []) or [] if isinstance(row, Mapping)],
        },
        "selected_final_candidates": _wamf_selected_candidate_summary(l1_screening),
        "baselines": {
            "oracle_fidelity": str(policy_evaluation.get("oracle_fidelity", "")),
            "policies": list(policy_evaluation.get("policies", []) or []),
            "method_kernel_policy": _wamf_method_kernel_policy_summary(policy_evaluation),
            "legacy_l1_policy_report": {
                "artifact": "qe_fpga_search_baseline_report",
                "policy_count": int(baseline.get("policy_count", 0)),
                "budget_sweep": dict(baseline.get("budget_sweep", {}) if isinstance(baseline.get("budget_sweep"), Mapping) else {}),
            },
            "independent_feedback_coverage_plan": dict(
                baseline.get("independent_feedback_coverage_plan", {})
                if isinstance(baseline.get("independent_feedback_coverage_plan"), Mapping)
                else {}
            ),
        },
        "ablations": {
            "required_ablations": _wamf_required_ablation_rows(
                baseline,
                policy_evaluation=policy_evaluation,
            ),
            "feature_ablation_report": dict(baseline.get("feature_ablation_report", {}) if isinstance(baseline.get("feature_ablation_report"), Mapping) else {}),
        },
        "hardware_generation_path": {
            "role": "final_candidate_package_generation_after_search",
            "not_part_of_algorithm_loop": True,
            "current_status": "candidate_bound_package_generation_is_downstream_validation_path",
            "required_downstream_gates": [
                "hls_or_rtl_source_generation",
                "golden_correctness",
                "hls_c_sim_or_rtl_sim",
                "synthesis",
                "vivado_implementation",
                "bitstream_target",
            ],
        },
        "limitations": [
            "current_policy_oracles_are_model_level_until_independent_high_fidelity_feedback_is_available",
            "hardware_generation_path_validates_selected_candidates_but_does_not_define_the_search_algorithm",
            "DAC_grade_results_require_measured_QE_corpus_and_real_HLS_Vivado_feedback",
        ],
        "claim_boundary": "wamf_dse_algorithm_report_not_fpga_implementation_evidence",
    }


def _wamf_next_evaluation_actions_summary(
    action_selection_kernel: Mapping[str, Any],
) -> Dict[str, Any]:
    """Expose the joint candidate/fidelity decision queue as the method output."""

    actions = [
        _wamf_next_evaluation_action_row(row)
        for row in action_selection_kernel.get("selection", []) or []
        if isinstance(row, Mapping)
    ]
    selected_cost = sum(_finite_float(row.get("action_cost"), default=0.0) for row in actions)
    return {
        "schema_version": "dse.qe_fpga.wamf_next_evaluation_actions.v1",
        "method_role": "primary_algorithm_decision_queue",
        "search_objective": "choose_candidate_fidelity_actions_under_budget",
        "evidence_role": "selected_actions_request_calibration_or_validation_feedback",
        "not_an_evidence_closure_matrix": True,
        "consumer": "Step3_or_external_fidelity_runner",
        "selected_action_count": len(actions),
        "selected_action_ids": [
            str(item) for item in action_selection_kernel.get("selected_action_ids", []) or []
        ],
        "selected_candidate_ids": [
            str(item) for item in action_selection_kernel.get("selected_candidate_ids", []) or []
        ],
        "selected_candidate_fidelity_pairs": [
            copy.deepcopy(dict(row))
            for row in action_selection_kernel.get("selected_candidate_fidelity_pairs", []) or []
            if isinstance(row, Mapping)
        ],
        "budget": {
            "action_budget": int(action_selection_kernel.get("action_budget", 0) or 0),
            "cost_budget": _finite_float(action_selection_kernel.get("cost_budget"), default=0.0),
            "selected_cost": _round_metric(selected_cost),
        },
        "fidelity_ladder": [row.fidelity for row in _qe_fpga_default_fidelity_actions()],
        "actions": actions,
        "source_kernel": {
            "schema_version": str(action_selection_kernel.get("schema_version", "")),
            "policy_id": str(action_selection_kernel.get("policy_id", "")),
            "selection_scope": str(
                (
                    action_selection_kernel.get("algorithm_contract", {})
                    if isinstance(action_selection_kernel.get("algorithm_contract"), Mapping)
                    else {}
                ).get("selection_scope", "")
            ),
        },
    }


def _wamf_next_evaluation_action_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    components = row.get("action_components", {}) if isinstance(row.get("action_components"), Mapping) else {}
    acquisition = row.get("acquisition", {}) if isinstance(row.get("acquisition"), Mapping) else {}
    acquisition_components = (
        acquisition.get("components", {})
        if isinstance(acquisition.get("components"), Mapping)
        else {}
    )
    fidelity_action = row.get("fidelity_action", {}) if isinstance(row.get("fidelity_action"), Mapping) else {}
    required_prior_fidelities = [
        str(item) for item in fidelity_action.get("requires_observed_fidelities", []) or []
    ]
    decision_factors = {
        "constrained_pareto_gain": _round_metric(
            _finite_float(acquisition_components.get("constrained_pareto_gain"), default=0.0)
        ),
        "uncertainty": _round_metric(
            _finite_float(acquisition_components.get("uncertainty"), default=0.0)
        ),
        "workflow_risk_coverage": _round_metric(
            _finite_float(acquisition_components.get("workflow_risk_coverage"), default=0.0)
        ),
        "design_diversity": _round_metric(
            _finite_float(acquisition_components.get("design_diversity"), default=0.0)
        ),
        "fidelity_information_gain": _round_metric(
            _finite_float(components.get("information_gain"), default=0.0)
        ),
        "fidelity_uncertainty_reduction": _round_metric(
            _finite_float(components.get("uncertainty_reduction"), default=0.0)
        ),
        "fidelity_calibration_value": _round_metric(
            _finite_float(components.get("calibration_value"), default=0.0)
        ),
        "action_feasibility": _round_metric(
            _finite_float(components.get("action_feasibility"), default=0.0)
        ),
        "cost_normalized_action_value": _round_metric(
            _finite_float(components.get("cost_normalized_action_value"), default=0.0)
        ),
    }
    return {
        "action_id": str(row.get("action_id", "")),
        "candidate_id": str(row.get("candidate_id", "")),
        "fidelity": str(row.get("fidelity", "")),
        "action_score": _round_metric(_finite_float(row.get("action_score"), default=0.0)),
        "action_cost": _round_metric(_finite_float(components.get("action_cost"), default=0.0)),
        "candidate_acquisition_score": _round_metric(
            _finite_float(components.get("candidate_acquisition_score"), default=0.0)
        ),
        "required_prior_fidelities": required_prior_fidelities,
        "prerequisites_satisfied": _finite_float(
            components.get("prerequisites_satisfied"), default=0.0
        ) > 0.0,
        "already_observed_action": _finite_float(
            components.get("already_observed_action"), default=0.0
        ) > 0.0,
        "decision_factors": decision_factors,
        "fidelity_tool_role": str(
            (
                fidelity_action.get("metadata", {})
                if isinstance(fidelity_action.get("metadata"), Mapping)
                else {}
            ).get("tool_role", "")
        ),
        "dispatch_boundary": "request_only_until_step3_or_external_runner_executes",
    }


def _wamf_formal_algorithm_contract(
    *,
    problem_payload: Mapping[str, Any],
    l1_screening: Mapping[str, Any],
    budget: int,
    initial_designs: int,
    generic_acquisition_kernel: Mapping[str, Any],
    generic_action_selection_kernel: Mapping[str, Any],
    neural_surrogate_training: Mapping[str, Any],
    trained_neural_search: Mapping[str, Any],
    policy_evaluation: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the paper-facing, replayable WAMF-DSE algorithm definition."""

    axes = _wamf_search_space_axes(problem_payload)
    workload_summary = _wamf_workflow_abstraction_summary(l1_screening)
    acquisition_contract = (
        generic_acquisition_kernel.get("algorithm_contract", {})
        if isinstance(generic_acquisition_kernel.get("algorithm_contract"), Mapping)
        else {}
    )
    action_contract = (
        generic_action_selection_kernel.get("algorithm_contract", {})
        if isinstance(generic_action_selection_kernel.get("algorithm_contract"), Mapping)
        else {}
    )
    surrogate_backend = (
        neural_surrogate_training.get("backend", {})
        if isinstance(neural_surrogate_training.get("backend"), Mapping)
        else {}
    )
    surrogate_uncertainty = (
        neural_surrogate_training.get("uncertainty", {})
        if isinstance(neural_surrogate_training.get("uncertainty"), Mapping)
        else {}
    )
    return {
        "schema_version": "dse.qe_fpga.wamf_formal_algorithm_contract.v1",
        "method_name": QE_FPGA_WAMF_DSE_METHOD_NAME,
        "paper_role": "primary_method_definition",
        "evidence_role": "validation_and_calibration_support_only",
        "formal_problem": {
            "symbol_table": {
                "W": "QE workflow workload family",
                "w": "one QE workflow workload bundle",
                "X": "FPGA deployment candidate space",
                "x": "one FPGA architecture/mapping/schedule/offload candidate",
                "F": "ordered multi-fidelity evaluator set",
                "f": "one evaluator fidelity",
                "y_f(x,w)": "objective vector observed or predicted at fidelity f",
                "G": "feasibility and release constraints",
                "B": "expensive evaluation budget",
                "P": "returned Pareto deployment candidate set",
            },
            "sets": {
                "workload_set": {
                    "symbol": "W",
                    "source": "qe_workflow_bundle_or_corpus",
                    "adapter": "qe_workflow_fpga_abstraction",
                    "scope": workload_summary.get("scope", "full_qe_workflow"),
                    "workflow_classes": list(workload_summary.get("workflow_classes", []) or []),
                    "not_scf_only": bool(workload_summary.get("not_scf_only", False)),
                },
                "candidate_space": {
                    "symbol": "X",
                    "source": "fpga_deployment_search_problem",
                    "axes": axes,
                    "candidate_count": int(l1_screening.get("candidate_count", 0)),
                    "release_candidate_count": int(policy_evaluation.get("release_candidate_count", 0)),
                },
                "fidelity_ladder": [
                    {
                        "fidelity": "L1_analytical_workflow_model",
                        "role": "cheap_full_space_prior",
                        "cost_class": "cheap",
                    },
                    {
                        "fidelity": "neural_surrogate_ranker",
                        "role": "residual_uncertainty_predictor",
                        "cost_class": "cheap_inference",
                    },
                    {
                        "fidelity": "L2_python_tlm",
                        "role": "budgeted_model_feedback",
                        "cost_class": "medium",
                    },
                    {
                        "fidelity": "L3_systemc_or_generic_sim",
                        "role": "independent_timing_feedback",
                        "cost_class": "expensive",
                    },
                    {
                        "fidelity": "L4_gem5_qe_runtime",
                        "role": "runtime_integration_feedback",
                        "cost_class": "very_expensive",
                    },
                    {
                        "fidelity": "HLS_RTL_Vivado_bitstream",
                        "role": "selected_candidate_hardware_validation",
                        "cost_class": "hard_gate",
                    },
                ],
            },
            "objectives": {
                "symbol": "y_f(x,w)",
                "direction": "minimize",
                "names": [
                    "latency_ms",
                    "energy_mj",
                    "edp",
                    "resource_pressure",
                    "data_movement_mb",
                    "feasibility_risk",
                ],
                "report_fields": {
                    "latency_ms": "metrics.estimated_workflow_wall_time_ms",
                    "energy_mj": "metrics.estimated_energy_mj",
                    "edp": "metrics.estimated_edp",
                    "resource_pressure": "metrics.fpga_resource_pressure",
                    "data_movement_mb": "metrics.estimated_data_movement_mb",
                    "feasibility_risk": "metrics.infeasibility_penalty",
                },
            },
            "constraints": {
                "symbol": "G",
                "resource_pressure": "<= platform_release_threshold",
                "precision_policy": "fp64_strict_for_release",
                "implementation_feasibility": "positive_probability_required",
                "workflow_scope": "full_qe_workflow_not_scf_only",
                "host_and_data_movement": "included_in_objective_accounting",
            },
            "budget": {
                "symbol": "B",
                "expensive_evaluation_budget": int(budget),
                "initial_design_count": int(initial_designs),
                "budget_unit": "one_selected_candidate_fidelity_observation",
            },
            "output": {
                "symbol": "P",
                "primary": "Pareto FPGA deployment candidate set",
                "secondary": [
                    "candidate_fidelity_evaluation_trace",
                    "candidate_specific_hls_vivado_package_plan",
                    "calibration_state_for_next_iteration",
                ],
            },
            "stopping_rule": {
                "max_expensive_evaluations": int(budget),
                "stop_when_candidate_space_exhausted": True,
                "stop_when_no_admissible_candidate_fidelity_action": True,
            },
        },
        "algorithm_pseudocode": {
            "style": "structured_replayable_steps",
            "steps": [
                _wamf_pseudocode_step(
                    "ingest_workload",
                    consumes=["qe_workflow_bundle_or_corpus"],
                    produces=["native_workload_bundle"],
                    operation="Load QE input/log/profile/save-dir descriptors and normalize source provenance.",
                ),
                _wamf_pseudocode_step(
                    "abstract_workflow",
                    consumes=["native_workload_bundle"],
                    produces=["workload_graph", "workflow_feature_contract"],
                    operation="Extract compute, control, communication, data-object lifetime, and correctness-observable features.",
                ),
                _wamf_pseudocode_step(
                    "enumerate_candidates",
                    consumes=["workflow_feature_contract", "fpga_deployment_search_problem"],
                    produces=["candidate_space_X"],
                    operation="Generate architecture, mapping, schedule, residency, memory, offload-boundary, and microarchitecture candidates.",
                ),
                _wamf_pseudocode_step(
                    "l1_screen_all_candidates",
                    consumes=["candidate_space_X", "workflow_features"],
                    produces=["l1_objective_vectors", "release_feasible_candidate_pool"],
                    operation="Evaluate every screenable candidate with the analytical workflow model.",
                ),
                _wamf_pseudocode_step(
                    "seed_initial_observations",
                    consumes=["release_feasible_candidate_pool", "budget_B"],
                    produces=["initial_candidate_fidelity_observations"],
                    operation="Select diverse seed candidates before relying on a learned residual model.",
                ),
                _wamf_pseudocode_step(
                    "fit_or_update_residual_surrogate",
                    consumes=["observations", "l1_objective_vectors", "workflow_candidate_features"],
                    produces=["surrogate_mean_uncertainty_state"],
                    operation="Fit or update residual and rank models from observed multi-fidelity feedback.",
                ),
                _wamf_pseudocode_step(
                    "score_candidate_fidelity_actions",
                    consumes=["candidate_pool", "surrogate_state", "frontier_state", "fidelity_ladder"],
                    produces=["ranked_candidate_fidelity_actions"],
                    operation="Score joint (candidate, fidelity) actions with the WAMF acquisition function.",
                ),
                _wamf_pseudocode_step(
                    "evaluate_selected_actions",
                    consumes=["ranked_candidate_fidelity_actions", "remaining_budget"],
                    produces=["new_observations"],
                    operation="Admit selected actions to the next evaluator without expanding into a closure matrix.",
                ),
                _wamf_pseudocode_step(
                    "update_frontier_calibration_and_uncertainty",
                    consumes=["new_observations", "surrogate_state", "frontier_state"],
                    produces=["updated_frontier", "updated_calibration_state"],
                    operation="Update Pareto frontier, residual calibration, rank quality, and uncertainty.",
                ),
                _wamf_pseudocode_step(
                    "return_pareto_candidates_and_packages",
                    consumes=["updated_frontier", "candidate_package_generator"],
                    produces=["pareto_candidates", "implementation_package_plan"],
                    operation="Return selected deployment candidates and downstream HLS/Vivado package inputs.",
                ),
            ],
        },
        "acquisition_function": {
            "equation_id": "wamf_cost_aware_constrained_active_pareto",
            "equation": (
                "A_t(x,f)=P_feas(x)*[EHVI_hat_t(x)+lambda_u*U_t(x)+"
                "lambda_r*R_w(x)+lambda_d*D_t(x)]*IG(f)*UR(f)*Cal_t(f)/(C_x*C_f)"
            ),
            "selection_scope": str(
                action_contract.get("selection_scope", "joint_candidate_fidelity_action_space")
            ),
            "base_acquisition_family": str(
                acquisition_contract.get("acquisition_family", "cost_aware_constrained_ehvi_proxy")
            ),
            "symbol_bindings": {
                "P_feas(x)": {
                    "meaning": "candidate feasibility probability",
                    "report_component": "active_pareto_acquisition.generic_acquisition_kernel.selection[].acquisition.components.feasibility_probability",
                },
                "EHVI_hat_t(x)": {
                    "meaning": "cost-normalized constrained hypervolume improvement proxy",
                    "report_component": "active_pareto_acquisition.generic_acquisition_kernel.selection[].acquisition.components.cost_normalized_hv_gain",
                },
                "U_t(x)": {
                    "meaning": "surrogate uncertainty or ensemble spread",
                    "report_component": "model_stack.surrogate.uncertainty",
                },
                "R_w(x)": {
                    "meaning": "workflow-risk coverage across host control, post-processing, data lifetime, and transfer synchronization",
                    "report_component": "active_pareto_acquisition.generic_acquisition_kernel.selection[].acquisition.components.workflow_risk_coverage",
                },
                "D_t(x)": {
                    "meaning": "batch design diversity over architecture, mapping, schedule, memory, and residency axes",
                    "report_component": "active_pareto_acquisition.generic_acquisition_kernel.selection[].acquisition.components.design_diversity",
                },
                "IG(f)": {
                    "meaning": "fidelity information gain",
                    "report_component": "active_pareto_acquisition.generic_action_selection_kernel.selection[].action_components.information_gain",
                },
                "UR(f)": {
                    "meaning": "fidelity uncertainty reduction",
                    "report_component": "active_pareto_acquisition.generic_action_selection_kernel.selection[].action_components.uncertainty_reduction",
                },
                "Cal_t(f)": {
                    "meaning": "calibration value of the next evaluator",
                    "report_component": "active_pareto_acquisition.generic_action_selection_kernel.selection[].action_components.calibration_value",
                },
                "C_x": {
                    "meaning": "candidate evaluation-cost multiplier",
                    "report_component": "active_pareto_acquisition.generic_action_selection_kernel.selection[].action_components.candidate_cost",
                },
                "C_f": {
                    "meaning": "fidelity evaluation cost",
                    "report_component": "active_pareto_acquisition.generic_action_selection_kernel.selection[].action_components.fidelity_evaluation_cost",
                },
            },
            "component_weights": {
                "lambda_uncertainty": 0.18,
                "lambda_workflow_risk": 0.16,
                "lambda_design_diversity": 0.08,
                "lambda_cost_normalized_hv": 1.00,
            },
        },
        "surrogate_contract": {
            "role": "residual_uncertainty_model_for_multifidelity_search",
            "target_equation": "r_f(x,w)=log(y_f(x,w))-log(y_L1(x,w))",
            "training_samples": int(
                neural_surrogate_training.get("dataset", {}).get("sample_count", 0)
                if isinstance(neural_surrogate_training.get("dataset"), Mapping)
                else 0
            ),
            "backend": {
                "framework": str(surrogate_backend.get("framework", "torch")),
                "model_type": str(surrogate_backend.get("model_type", "")),
                "device_policy": str(surrogate_backend.get("device_policy", "cuda_if_available")),
                "resolved_device": str(surrogate_backend.get("resolved_device", "")),
            },
            "feature_source": "workflow_candidate_l1_metric_features",
            "outputs": [
                "predicted_objective_mean",
                "predicted_objective_std",
                "top_k_probability",
                "calibration_status",
            ],
            "uncertainty": dict(surrogate_uncertainty),
            "online_search_backend": str(
                trained_neural_search.get("surrogate_model", {}).get("model_type", "")
                if isinstance(trained_neural_search.get("surrogate_model"), Mapping)
                else ""
            ),
            "not_used_as": [
                "standalone architecture generator",
                "hardware performance proof",
                "replacement for high_fidelity_feedback",
            ],
        },
        "fidelity_action_protocol": {
            "action_shape": "(candidate_id, fidelity)",
            "selection_scope": str(
                action_contract.get("selection_scope", "joint_candidate_fidelity_action_space")
            ),
            "chooses_candidate_and_next_fidelity": bool(
                action_contract.get("chooses_candidate_and_next_fidelity", True)
            ),
            "fidelity_cost_aware_selection": bool(
                action_contract.get("fidelity_cost_aware_selection", True)
            ),
            "not_an_evidence_closure_matrix": True,
            "queue_contract": {
                "schema_version": "dse.multifidelity_next_evaluation_queue.v1",
                "execution_allowed": False,
                "consumer": "Step3 evaluator admission",
                "producer": "Step2 WAMF-DSE acquisition policy",
                "required_fields": [
                    "candidate_id",
                    "next_fidelity",
                    "selection_rationale",
                    "cost_budget",
                ],
            },
        },
        "evaluation_protocol": {
            "primary_metrics": [
                "simple_regret",
                "top_k_hit",
                "hypervolume_ratio",
                "sample_efficiency",
                "rank_correlation",
                "calibration_error",
            ],
            "required_baselines": [
                "random_seeded",
                "manual_hbm_streaming_heuristic",
                "nsga2_lite_multi_objective",
                "sequential_surrogate_expected_improvement_or_bo",
                "single_fidelity_l1_edp",
                "kernel_level_hotspot_only",
            ],
            "required_ablations": [
                "no_workflow_abstraction",
                "no_multifidelity_feedback",
                "no_active_pareto_selection",
                "kernel_level_only",
                "uncalibrated_surrogate",
            ],
            "oracle_boundary": "retrospective_oracle_not_used_inside_method_loop",
            "minimum_workload_coverage": [
                "scf",
                "nscf",
                "post_processing",
                "relax_or_force",
            ],
            "hardware_validation_role": "selected_final_candidates_only",
        },
    }


def _wamf_pseudocode_step(
    step_id: str,
    *,
    consumes: Sequence[str],
    produces: Sequence[str],
    operation: str,
) -> Dict[str, Any]:
    return {
        "step_id": str(step_id),
        "consumes": [str(item) for item in consumes],
        "produces": [str(item) for item in produces],
        "operation": str(operation),
    }


def _wamf_search_space_axes(problem_payload: Mapping[str, Any]) -> List[str]:
    parameters = problem_payload.get("parameters", {})
    if not isinstance(parameters, Mapping):
        return []
    preferred = [
        "architecture_template",
        "offload_boundary",
        "mapping_granularity",
        "runtime_schedule",
        "data_residency",
        "memory_topology",
        "vector_lanes",
        "hbm_channel_count",
        "tile_doubles",
        "precision_policy",
    ]
    keys = [key for key in preferred if key in parameters]
    keys.extend(sorted(str(key) for key in parameters if str(key) not in set(keys)))
    return keys


def _wamf_acquisition_reference_point(l1_screening: Mapping[str, Any]) -> Dict[str, Any]:
    rows = [
        row for row in l1_screening.get("candidate_evaluations", []) or []
        if isinstance(row, Mapping)
        and row.get("promotion", {}).get("release_pareto_eligible") is True
    ]
    if not rows:
        rows = [
            row for row in l1_screening.get("candidate_evaluations", []) or []
            if isinstance(row, Mapping)
        ]
    objective_names = [
        "estimated_workflow_wall_time_ms",
        "estimated_energy_mj",
        "fpga_resource_pressure",
        "estimated_data_movement_mb",
        "infeasibility_penalty",
    ]
    margins = {
        "estimated_workflow_wall_time_ms": 1.20,
        "estimated_energy_mj": 1.20,
        "fpga_resource_pressure": 1.05,
        "estimated_data_movement_mb": 1.20,
        "infeasibility_penalty": 1.05,
    }
    values: Dict[str, float] = {}
    for name in objective_names:
        observed = [
            _finite_float(_objective_vector(row).get(name), default=float("nan"))
            for row in rows
        ]
        finite = [value for value in observed if math.isfinite(value)]
        worst = max(finite) if finite else 1.0
        values[name] = _round_metric(max(1.0e-9, worst * margins[name]))
    return {
        "source": "l1_frontier_worst_release_candidate_margin",
        "objective_vector": values,
        "margin_policy": "20_percent_latency_energy_movement_5_percent_resource_risk",
    }


def _wamf_workflow_abstraction_summary(l1_screening: Mapping[str, Any]) -> Dict[str, Any]:
    features = l1_screening.get("workload_features", {}) if isinstance(l1_screening.get("workload_features"), Mapping) else {}
    workflow_classes = sorted({str(item) for item in features.get("workflow_classes", []) or []})
    non_scf_classes = [item for item in workflow_classes if item and item != "scf"]
    workflow_scope = str(l1_screening.get("workflow_scope", "full_qe_mainflow"))
    return {
        "source": str(features.get("feature_source", "qe_mainflow_workload_suite")),
        "scope": "scf_only_measured_seed" if workflow_scope == "scf_only_measured_seed" else "full_qe_workflow",
        "workflow_scope": workflow_scope,
        "not_scf_only": bool(non_scf_classes),
        "workflow_classes": workflow_classes,
        "stage_count": int(features.get("stage_count", 0)),
        "required_feature_groups": [
            "stage_graph",
            "host_control",
            "data_object_lifetime",
            "transfer_sync",
            "post_processing",
        ],
        "graph": {
            "node_count": int(features.get("graph_node_count", 0)),
            "edge_count": int(features.get("graph_edge_count", 0)),
            "inter_stage_edge_count": int(features.get("graph_inter_stage_edge_count", 0)),
        },
        "host_control_intensity": _round_metric(_finite_float(features.get("host_control_intensity"), default=0.0)),
        "post_processing_intensity": _round_metric(_finite_float(features.get("post_processing_intensity"), default=0.0)),
        "data_object_lifetime": dict(features.get("data_object_lifetime", {}) if isinstance(features.get("data_object_lifetime"), Mapping) else {}),
    }


def _wamf_selected_candidate_summary(l1_screening: Mapping[str, Any]) -> Dict[str, Any]:
    rows = [
        row for row in l1_screening.get("promotion_queue", []) or []
        if isinstance(row, Mapping)
    ]
    summarized = []
    for row in rows:
        metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
        summarized.append({
            "candidate_id": str(row.get("candidate_id", "")),
            "design_key": str(row.get("design_key", "")),
            "parameters": dict(row.get("parameters", {}) if isinstance(row.get("parameters"), Mapping) else {}),
            "metrics": {
                "runtime": _round_metric(_finite_float(metrics.get("estimated_workflow_wall_time_ms"), default=0.0)),
                "energy_edp": _round_metric(_finite_float(metrics.get("estimated_edp"), default=0.0)),
                "resource": _round_metric(_finite_float(metrics.get("fpga_resource_pressure"), default=0.0)),
                "data_movement": _round_metric(_finite_float(metrics.get("estimated_data_movement_mb"), default=0.0)),
                "feasibility": _round_metric(_finite_float(metrics.get("implementation_feasibility"), default=0.0)),
            },
            "explanation_fields": [
                "runtime",
                "energy_edp",
                "resource",
                "data_movement",
                "feasibility",
            ],
        })
    return {
        "candidate_count": len(summarized),
        "selection_source": "l1_active_pareto_promotion_queue",
        "candidates": summarized,
    }


def _wamf_required_ablation_rows(
    baseline: Mapping[str, Any],
    *,
    policy_evaluation: Mapping[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    feature_ablation = baseline.get("feature_ablation_report", {}) if isinstance(baseline.get("feature_ablation_report"), Mapping) else {}
    existing = {
        str(row.get("ablation_id", "")): dict(row)
        for row in feature_ablation.get("ablations", []) or []
        if isinstance(row, Mapping)
    }
    policy_rows = {
        str(row.get("policy_id", "")): dict(row)
        for row in baseline.get("policies", []) or []
        if isinstance(row, Mapping)
    }
    budget_sweep = baseline.get("budget_sweep", {}) if isinstance(baseline.get("budget_sweep"), Mapping) else {}
    for row in budget_sweep.get("policy_curves", []) or budget_sweep.get("baseline_policy_results", []) or []:
        if not isinstance(row, Mapping):
            continue
        policy_id = str(row.get("policy_id", ""))
        if not policy_id:
            continue
        normalized = dict(row)
        if "budget_curve" not in normalized and isinstance(row.get("points"), list):
            normalized["budget_curve"] = [
                dict(point) for point in row.get("points", []) or []
                if isinstance(point, Mapping)
            ]
        existing_row = policy_rows.get(policy_id)
        if not existing_row:
            policy_rows[policy_id] = normalized
        elif not isinstance(existing_row.get("budget_curve"), list) and isinstance(normalized.get("budget_curve"), list):
            merged = dict(existing_row)
            merged["budget_curve"] = list(normalized.get("budget_curve", []) or [])
            policy_rows[policy_id] = merged
    evaluation_rows = {
        str(row.get("policy_id", "")): dict(row)
        for row in (policy_evaluation or {}).get("policies", []) or []
        if isinstance(row, Mapping)
    } if isinstance(policy_evaluation, Mapping) else {}
    baseline_method_row = policy_rows.get("wamf_generic_active_pareto") or {}
    evaluation_method_row = evaluation_rows.get("wamf_generic_active_pareto") or {}

    def method_row_for_budget(final_budget: int) -> Mapping[str, Any]:
        for candidate in (baseline_method_row, evaluation_method_row):
            curve = candidate.get("budget_curve", []) if isinstance(candidate.get("budget_curve"), list) else []
            if any(
                isinstance(entry, Mapping)
                and int(_finite_float(entry.get("budget"), default=-1.0) or -1) == int(final_budget)
                for entry in curve
            ):
                return candidate
        return evaluation_method_row or baseline_method_row or {}

    feature_budget = int(feature_ablation.get("evaluation_budget", baseline.get("evaluation_budget", 0)) or 0)
    baseline_budget = int(baseline.get("evaluation_budget", 0) or 0)
    policy_evaluation_budget = (
        int((policy_evaluation or {}).get("evaluation_budget", baseline.get("evaluation_budget", 0)) or 0)
        if isinstance(policy_evaluation, Mapping)
        else baseline_budget
    )
    return [
        _wamf_ablation_row(
            ablation_id="no_workflow_abstraction",
            maps_to="kernel_histogram_only",
            status="implemented" if "kernel_histogram_only" in existing else "required",
            source_row=existing.get("kernel_histogram_only", {}),
            removes="workflow_abstraction",
            oracle_fidelity=str(feature_ablation.get("oracle_fidelity", baseline.get("oracle_fidelity", ""))),
            final_budget=feature_budget,
            method_row=method_row_for_budget(feature_budget),
            uses_workflow_abstraction=False,
            uses_multi_fidelity_feedback=True,
            uses_active_pareto_selection=False,
        ),
        _wamf_ablation_row(
            ablation_id="no_multifidelity_feedback",
            maps_to="single_fidelity_l1_edp",
            status="implemented",
            source_row=policy_rows.get("single_fidelity_l1_edp", {}),
            removes="multi_fidelity_feedback",
            oracle_fidelity=str(baseline.get("oracle_fidelity", "")),
            final_budget=baseline_budget,
            method_row=method_row_for_budget(baseline_budget),
            uses_workflow_abstraction=True,
            uses_multi_fidelity_feedback=False,
            uses_active_pareto_selection=False,
        ),
        _wamf_ablation_row(
            ablation_id="no_active_pareto_selection",
            maps_to="random_seeded",
            status="implemented",
            source_row=policy_rows.get("random_seeded", {}),
            removes="active_pareto_selection",
            oracle_fidelity=str(baseline.get("oracle_fidelity", "")),
            final_budget=baseline_budget,
            method_row=method_row_for_budget(baseline_budget),
            uses_workflow_abstraction=False,
            uses_multi_fidelity_feedback=True,
            uses_active_pareto_selection=False,
        ),
        _wamf_ablation_row(
            ablation_id="kernel_level_only",
            maps_to="kernel_level_hotspot_only",
            status="implemented",
            source_row=policy_rows.get("kernel_level_hotspot_only", {}),
            removes="workflow_level_mapping_and_scheduling",
            oracle_fidelity=str(baseline.get("oracle_fidelity", "")),
            final_budget=baseline_budget,
            method_row=method_row_for_budget(baseline_budget),
            uses_workflow_abstraction=False,
            uses_multi_fidelity_feedback=True,
            uses_active_pareto_selection=False,
        ),
        _wamf_ablation_row(
            ablation_id="uncalibrated_surrogate",
            maps_to="neuromf_unguided_bootstrap",
            status="implemented_as_model_level_surrogate_ablation",
            source_row=evaluation_rows.get("neuromf_unguided_bootstrap", {}),
            removes="trained_surrogate_calibration",
            oracle_fidelity=str((policy_evaluation or {}).get("oracle_fidelity", baseline.get("oracle_fidelity", "")))
            if isinstance(policy_evaluation, Mapping)
            else str(baseline.get("oracle_fidelity", "")),
            final_budget=policy_evaluation_budget,
            method_row=method_row_for_budget(policy_evaluation_budget),
            uses_workflow_abstraction=True,
            uses_multi_fidelity_feedback=True,
            uses_active_pareto_selection=True,
        ),
    ]


def _wamf_ablation_row(
    *,
    ablation_id: str,
    maps_to: str,
    status: str,
    source_row: Mapping[str, Any],
    removes: str,
    oracle_fidelity: str,
    final_budget: int,
    method_row: Mapping[str, Any],
    uses_workflow_abstraction: bool,
    uses_multi_fidelity_feedback: bool,
    uses_active_pareto_selection: bool,
) -> Dict[str, Any]:
    evaluation = _wamf_ablation_evaluation(
        source_row,
        oracle_fidelity=oracle_fidelity,
        final_budget=final_budget,
    )
    removed_components = [str(item) for item in str(removes).split(",") if str(item).strip()]
    return {
        "ablation_id": str(ablation_id),
        "maps_to": str(maps_to),
        "status": str(status),
        "algorithm_contract": _wamf_ablation_algorithm_contract(
            ablation_id=str(ablation_id),
            removed_components=removed_components,
            replacement_policy_id=str(maps_to),
            uses_workflow_abstraction=uses_workflow_abstraction,
            uses_multi_fidelity_feedback=uses_multi_fidelity_feedback,
            uses_active_pareto_selection=uses_active_pareto_selection,
        ),
        "selection_basis": {
            **dict(source_row.get("selection_basis", {}) if isinstance(source_row.get("selection_basis"), Mapping) else {}),
            "ablation_removes": str(removes),
        },
        "candidate_ids": list(source_row.get("candidate_ids", []) or []),
        "evaluation": evaluation,
        "comparison_to_method": _wamf_ablation_comparison_to_method(
            evaluation,
            method_row=method_row,
            final_budget=final_budget,
        ),
        "sample_efficiency": dict(
            source_row.get("sample_efficiency", {})
            if isinstance(source_row.get("sample_efficiency"), Mapping)
            else {
                "evaluations_to_top_1_hit": None,
                "evaluations_to_top_5_hit": _evaluations_to_top_k_from_candidate_ids(
                    source_row.get("candidate_ids", []) or [],
                    source_row.get("result_summaries", []) or [],
                    k=5,
                ),
                "final_simple_regret": evaluation.get("final_simple_regret"),
                "final_oracle_rank": evaluation.get("final_oracle_rank"),
            }
        ),
        "ranking_quality": dict(source_row.get("ranking_quality", {}) if isinstance(source_row.get("ranking_quality"), Mapping) else {}),
    }


def _wamf_ablation_algorithm_contract(
    *,
    ablation_id: str,
    removed_components: Sequence[str],
    replacement_policy_id: str,
    uses_workflow_abstraction: bool,
    uses_multi_fidelity_feedback: bool,
    uses_active_pareto_selection: bool,
) -> Dict[str, Any]:
    return {
        "ablation_id": str(ablation_id),
        "removed_components": list(removed_components),
        "replacement_policy_id": str(replacement_policy_id),
        "same_candidate_pool_as_method": True,
        "same_evaluation_budget_as_method": True,
        "retrospective_oracle_only": True,
        "uses_workflow_abstraction": bool(uses_workflow_abstraction),
        "uses_multi_fidelity_feedback": bool(uses_multi_fidelity_feedback),
        "uses_active_pareto_selection": bool(uses_active_pareto_selection),
        "evidence_boundary": "model_oracle_ablation_not_hardware_result",
    }


def _wamf_ablation_comparison_to_method(
    evaluation: Mapping[str, Any],
    *,
    method_row: Mapping[str, Any],
    final_budget: int,
) -> Dict[str, Any]:
    method_eval = _wamf_ablation_evaluation(
        method_row,
        oracle_fidelity=str(evaluation.get("oracle_fidelity", "")),
        final_budget=final_budget,
    )
    ablation_budget = int(_finite_float(evaluation.get("final_budget"), default=0.0) or 0)
    method_budget = int(_finite_float(method_eval.get("final_budget"), default=0.0) or 0)
    ablation_edp = _finite_float(evaluation.get("final_best_edp"), default=0.0)
    method_edp = _finite_float(method_eval.get("final_best_edp"), default=0.0)
    ablation_rank = int(_finite_float(evaluation.get("final_oracle_rank"), default=0.0) or 0)
    method_rank = int(_finite_float(method_eval.get("final_oracle_rank"), default=0.0) or 0)
    ablation_regret = _finite_float(evaluation.get("final_simple_regret"), default=0.0)
    method_regret = _finite_float(method_eval.get("final_simple_regret"), default=0.0)
    return {
        "method_policy_id": "wamf_generic_active_pareto",
        "same_budget": bool(ablation_budget == method_budget and ablation_budget > 0),
        "method_final_budget": method_budget,
        "ablation_final_budget": ablation_budget,
        "method_final_best_edp": _round_metric(method_edp),
        "method_final_oracle_rank": method_rank,
        "method_final_simple_regret": _round_metric(method_regret),
        "edp_ratio_vs_method": _round_metric(ablation_edp / method_edp) if method_edp > 0.0 and ablation_edp > 0.0 else None,
        "rank_delta_vs_method": ablation_rank - method_rank if ablation_rank > 0 and method_rank > 0 else None,
        "regret_delta_vs_method": _round_metric(ablation_regret - method_regret)
        if math.isfinite(ablation_regret) and math.isfinite(method_regret)
        else None,
        "comparison_boundary": "same_budget_model_oracle_comparison_not_hardware_result",
    }


def _wamf_ablation_evaluation(
    source_row: Mapping[str, Any],
    *,
    oracle_fidelity: str,
    final_budget: int,
) -> Dict[str, Any]:
    curve = source_row.get("budget_curve", []) if isinstance(source_row.get("budget_curve"), list) else []
    final = next(
        (
            entry for entry in curve
            if isinstance(entry, Mapping)
            and int(_finite_float(entry.get("budget"), default=-1.0) or -1) == int(final_budget)
        ),
        curve[-1] if curve and isinstance(curve[-1], Mapping) else {},
    )
    l2_oracle = source_row.get("l2_oracle", {}) if isinstance(source_row.get("l2_oracle"), Mapping) else {}
    best_edp = final.get("best_tlm_edp", l2_oracle.get("best_tlm_edp"))
    final_rank = final.get("oracle_rank_of_best", l2_oracle.get("oracle_rank_of_best_selected"))
    return {
        "oracle_fidelity": str(oracle_fidelity),
        "final_budget": int(final.get("budget", final_budget) or 0),
        "final_best_edp": _round_metric(_finite_float(best_edp, default=0.0)),
        "final_oracle_rank": int(_finite_float(final_rank, default=0.0) or 0),
        "final_simple_regret": _round_metric(_finite_float(final.get("simple_regret"), default=0.0)),
        "top_k_hit": final.get("top_k_hit", bool(_finite_float(final_rank, default=float("inf")) <= 5.0)),
    }


def _evaluations_to_top_k_from_candidate_ids(
    candidate_ids: Sequence[Any],
    result_summaries: Sequence[Any],
    *,
    k: int,
) -> int | None:
    rank_by_candidate = {
        str(row.get("candidate_id", "")): row.get("oracle_rank")
        for row in result_summaries
        if isinstance(row, Mapping)
    }
    for index, candidate_id in enumerate([str(item) for item in candidate_ids], start=1):
        rank = rank_by_candidate.get(candidate_id)
        if isinstance(rank, int) and rank <= int(k):
            return index
    return None


def _wamf_method_kernel_policy_summary(policy_evaluation: Mapping[str, Any]) -> Dict[str, Any]:
    policies = [
        row for row in policy_evaluation.get("policies", []) or []
        if isinstance(row, Mapping)
    ]
    method = next(
        (row for row in policies if str(row.get("policy_id", "")) == "wamf_generic_active_pareto"),
        {},
    )
    final = (
        method.get("budget_curve", [])[-1]
        if isinstance(method.get("budget_curve"), list) and method.get("budget_curve")
        else {}
    )
    basis = method.get("selection_basis", {}) if isinstance(method.get("selection_basis"), Mapping) else {}
    return {
        "policy_id": str(method.get("policy_id", "")),
        "generic_kernel_policy": str(basis.get("generic_kernel_policy", "")),
        "selected_count": int(method.get("selected_count", 0)),
        "candidate_ids": list(method.get("candidate_ids", []) or []),
        "final_simple_regret": final.get("simple_regret"),
        "final_oracle_rank": final.get("oracle_rank_of_best"),
        "top_k_hit": final.get("top_k_hit"),
        "ranking_quality": dict(method.get("ranking_quality", {}) if isinstance(method.get("ranking_quality"), Mapping) else {}),
        "sample_efficiency": dict(method.get("sample_efficiency", {}) if isinstance(method.get("sample_efficiency"), Mapping) else {}),
        "evidence_boundary": "policy_evaluation_uses_model_oracle_not_final_hardware_result",
    }


def _wamf_generic_acquisition_kernel_report(
    l1_screening: Mapping[str, Any],
    trained_neural_search: Mapping[str, Any],
    *,
    budget: int,
) -> Dict[str, Any]:
    workload_features = (
        l1_screening.get("workload_features", {})
        if isinstance(l1_screening.get("workload_features"), Mapping)
        else {}
    )
    rows = [
        row for row in l1_screening.get("candidate_evaluations", []) or []
        if isinstance(row, Mapping)
        and _is_release_candidate(row)
    ]
    observations = _active_search_observations_from_trace(
        trained_neural_search.get("evaluation_trace", [])
        if isinstance(trained_neural_search.get("evaluation_trace"), list)
        else []
    )
    report = _run_wamf_global_acquisition(
        rows,
        workload_features,
        observations=observations,
        budget=max(1, int(budget)),
    )
    report["adapter"] = {
        "source": "qe_fpga_l1_screening_report",
        "candidate_projection": "qe_l1_metrics_to_domain_neutral_active_search_candidate",
        "observation_projection": "trained_neural_trace_common_objective_observations",
        "workload_feature_source": str(workload_features.get("feature_source", "")),
    }
    return report


def _wamf_generic_action_selection_report(
    l1_screening: Mapping[str, Any],
    trained_neural_search: Mapping[str, Any],
    *,
    budget: int,
) -> Dict[str, Any]:
    workload_features = (
        l1_screening.get("workload_features", {})
        if isinstance(l1_screening.get("workload_features"), Mapping)
        else {}
    )
    rows = [
        row for row in l1_screening.get("candidate_evaluations", []) or []
        if isinstance(row, Mapping)
        and _is_release_candidate(row)
    ]
    observations = _active_search_observations_from_trace(
        trained_neural_search.get("evaluation_trace", [])
        if isinstance(trained_neural_search.get("evaluation_trace"), list)
        else []
    )
    candidates = _active_search_candidates_from_qe_rows(rows, workload_features)
    report = MultiFidelityActiveSearchPolicy(
        objective_names=(
            "estimated_workflow_wall_time_ms",
            "estimated_energy_mj",
            "fpga_resource_pressure",
            "estimated_data_movement_mb",
            "infeasibility_penalty",
        )
    ).action_selection_report(
        candidates,
        fidelities=_qe_fpga_default_fidelity_actions(),
        observations=observations,
        action_budget=max(1, int(budget)),
        cost_budget=float(max(1, int(budget))),
    )
    report["adapter"] = {
        "source": "qe_fpga_l1_screening_report",
        "candidate_projection": "qe_l1_metrics_to_domain_neutral_active_search_candidate",
        "fidelity_projection": "qe_fpga_tool_ladder_to_domain_neutral_active_search_fidelity",
        "observation_projection": "trained_neural_trace_common_objective_observations",
        "workload_feature_source": str(workload_features.get("feature_source", "")),
    }
    return report


def _qe_fpga_default_fidelity_actions() -> List[ActiveSearchFidelity]:
    return [
        ActiveSearchFidelity(
            fidelity="L2_systemc_or_tlm",
            evaluation_cost=1.0,
            information_gain=0.45,
            uncertainty_reduction=0.35,
            calibration_value=0.35,
            metadata={"tool_role": "cheap_timing_model_or_systemc_style_feedback"},
        ),
        ActiveSearchFidelity(
            fidelity="L3_systemc_or_gem5",
            evaluation_cost=3.0,
            information_gain=0.75,
            uncertainty_reduction=0.60,
            calibration_value=0.70,
            requires_observed_fidelities=("L2_systemc_or_tlm",),
            metadata={"tool_role": "independent_architecture_timing_feedback"},
        ),
        ActiveSearchFidelity(
            fidelity="HLS_c_synthesis",
            evaluation_cost=5.0,
            information_gain=0.90,
            uncertainty_reduction=0.75,
            calibration_value=0.85,
            requires_observed_fidelities=("L2_systemc_or_tlm",),
            metadata={"tool_role": "implementation_feasibility_and_resource_feedback"},
        ),
        ActiveSearchFidelity(
            fidelity="Vivado_implementation_or_bitstream",
            evaluation_cost=12.0,
            information_gain=1.0,
            uncertainty_reduction=0.90,
            calibration_value=1.0,
            requires_observed_fidelities=("HLS_c_synthesis",),
            metadata={"tool_role": "final_fpga_timing_utilization_power_or_bitstream_feedback"},
        ),
    ]


def _active_search_candidate_from_qe_row(
    row: Mapping[str, Any],
    workload_features: Mapping[str, Any],
) -> ActiveSearchCandidate:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    params = _candidate_parameters(row)
    resource = _finite_float(metrics.get("fpga_resource_pressure"), default=1.0)
    feasibility = _finite_float(metrics.get("implementation_feasibility"), default=0.0)
    edp = max(1.0, _finite_float(metrics.get("estimated_edp"), default=1.0))
    return ActiveSearchCandidate(
        candidate_id=str(row.get("candidate_id", "")),
        objectives={
            "estimated_workflow_wall_time_ms": _finite_float(metrics.get("estimated_workflow_wall_time_ms"), default=float("inf")),
            "estimated_energy_mj": _finite_float(metrics.get("estimated_energy_mj"), default=float("inf")),
            "estimated_edp": edp,
            "fpga_resource_pressure": resource,
            "estimated_data_movement_mb": _finite_float(metrics.get("estimated_data_movement_mb"), default=float("inf")),
            "infeasibility_penalty": _finite_float(metrics.get("infeasibility_penalty"), default=1.0),
        },
        constraints={
            "resource_pressure": resource,
            "feasibility": feasibility,
        },
        uncertainty=min(
            1.0,
            _adaptive_uncertainty(
                row,
                {"training_sample_count": 0, "residual_std": 0.0},
                workload_features,
            ) / edp,
        ),
        evaluation_cost=_adaptive_evaluation_cost(row),
        risk_axes={
            "host_control_intensity": _finite_float(workload_features.get("host_control_intensity"), default=0.0),
            "post_processing_intensity": _finite_float(workload_features.get("post_processing_intensity"), default=0.0),
            "data_object_lifetime": _data_object_lifetime_risk(workload_features),
            "data_lifetime_communication": _data_lifetime_communication_coverage(params, workload_features),
            "hbm_lifetime_residency_fit": _hbm_lifetime_residency_fit(params, workload_features),
            "transfer_sync": _transfer_sync_risk(row, workload_features),
        },
        design_key=str(row.get("design_key", "") or _design_key(params)),
        metadata={
            "fidelity": str(row.get("fidelity", "")),
            "promotion_recommended": bool(
                row.get("promotion", {}).get("recommended", False)
                if isinstance(row.get("promotion"), Mapping)
                else False
            ),
            "categorical_features": {
                key: str(params.get(key, ""))
                for key in (
                    "architecture_template",
                    "offload_boundary",
                    "mapping_granularity",
                    "runtime_schedule",
                    "data_residency",
                    "memory_topology",
                    "precision_policy",
                )
                if str(params.get(key, ""))
            },
        },
    )


def _active_search_candidates_from_qe_rows(
    rows: Sequence[Mapping[str, Any]],
    workload_features: Mapping[str, Any],
    *,
    exclude_candidate_ids: set[str] | None = None,
) -> List[ActiveSearchCandidate]:
    excluded = exclude_candidate_ids or set()
    return [
        _active_search_candidate_from_qe_row(row, workload_features)
        for row in rows
        if isinstance(row, Mapping)
        and str(row.get("candidate_id", "")) not in excluded
    ]


def _run_wamf_global_acquisition(
    rows: Sequence[Mapping[str, Any]],
    workload_features: Mapping[str, Any],
    *,
    observations: Sequence[ActiveSearchObservation] | None = None,
    budget: int,
) -> Dict[str, Any]:
    candidates = _active_search_candidates_from_qe_rows(rows, workload_features)
    return MultiFidelityActiveSearchPolicy(
        objective_names=(
            "estimated_workflow_wall_time_ms",
            "estimated_energy_mj",
            "fpga_resource_pressure",
            "estimated_data_movement_mb",
            "infeasibility_penalty",
        ),
        scalar_quality_objective_name="estimated_edp",
    ).selection_report(
        candidates,
        observations=observations or [],
        budget=max(1, int(budget)),
    )


def _active_search_observations_from_trace(trace: Sequence[Any]) -> List[ActiveSearchObservation]:
    observations: List[ActiveSearchObservation] = []
    for row in trace:
        if not isinstance(row, Mapping) or row.get("common_objective_used") is not True:
            continue
        observation = row.get("common_objective_observation", {})
        if not isinstance(observation, Mapping):
            continue
        metrics = observation.get("metrics", {}) if isinstance(observation.get("metrics"), Mapping) else {}
        edp = _finite_float(
            metrics.get("tlm_edp", observation.get("objective_edp", observation.get("common_objective_edp"))),
            default=float("inf"),
        )
        latency_default = math.sqrt(edp) if math.isfinite(edp) else float("inf")
        latency = _finite_float(metrics.get("tlm_workflow_wall_time_ms"), default=latency_default)
        energy = _finite_float(
            metrics.get("tlm_energy_mj"),
            default=(edp / latency) if latency > 0.0 and math.isfinite(edp) else float("inf"),
        )
        raw_fidelity = str(observation.get("fidelity", row.get("observation_source", "")))
        observations.append(ActiveSearchObservation(
            candidate_id=str(row.get("candidate_id", "")),
            fidelity=_canonical_qe_fpga_action_fidelity(raw_fidelity),
            objectives={
                "estimated_workflow_wall_time_ms": latency,
                "estimated_energy_mj": energy,
                "estimated_edp": edp,
                "fpga_resource_pressure": _finite_float(metrics.get("tlm_resource_pressure"), default=0.0),
                "estimated_data_movement_mb": _finite_float(metrics.get("tlm_data_movement_mb"), default=0.0),
                "infeasibility_penalty": 0.0,
            },
            feasible=True,
            metadata={
                "source": "trained_neural_search_trace",
                "raw_fidelity": raw_fidelity,
            },
        ))
    return observations


def _canonical_qe_fpga_action_fidelity(fidelity: str) -> str:
    aliases = {
        "L2_python_tlm": "L2_systemc_or_tlm",
        "L2_systemc": "L2_systemc_or_tlm",
        "L2_tlm": "L2_systemc_or_tlm",
        "L3_systemc": "L3_systemc_or_gem5",
        "L3_gem5": "L3_systemc_or_gem5",
        "L3_generic_sim": "L3_systemc_or_gem5",
        "HLS_c_synth": "HLS_c_synthesis",
    }
    return aliases.get(str(fidelity), str(fidelity))


def _generic_active_acquisition_for_row(
    row: Mapping[str, Any],
    *,
    rows: Sequence[Mapping[str, Any]],
    evaluated_ids: set[str],
    workload_features: Mapping[str, Any],
) -> Dict[str, Any]:
    candidate = _active_search_candidate_from_qe_row(row, workload_features)
    observations = _active_search_observations_from_l1_rows(rows, evaluated_ids)
    report = MultiFidelityActiveSearchPolicy(
        objective_names=(
            "estimated_workflow_wall_time_ms",
            "estimated_energy_mj",
            "fpga_resource_pressure",
            "estimated_data_movement_mb",
            "infeasibility_penalty",
        )
    ).selection_report(
        [candidate],
        observations=observations,
        budget=1,
    )
    selection = report.get("selection", []) if isinstance(report.get("selection"), list) else []
    if selection and isinstance(selection[0], Mapping):
        acquisition = selection[0].get("acquisition", {})
        if isinstance(acquisition, Mapping):
            return dict(acquisition)
    return {
        "policy": "wamf_constrained_active_pareto",
        "score": 0.0,
        "components": {
            "constrained_pareto_gain": 0.0,
            "feasibility_probability": 0.0,
            "workflow_risk_coverage": 0.0,
            "evaluation_cost_penalty": 0.0,
        },
        "frontier_source": "observed_high_fidelity_frontier" if observations else "cheap_model_candidate_frontier",
    }


def _active_search_observations_from_l1_rows(
    rows: Sequence[Mapping[str, Any]],
    evaluated_ids: set[str],
) -> List[ActiveSearchObservation]:
    observations: List[ActiveSearchObservation] = []
    for row in rows:
        candidate_id = str(row.get("candidate_id", ""))
        if candidate_id not in evaluated_ids:
            continue
        metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
        observations.append(ActiveSearchObservation(
            candidate_id=candidate_id,
            fidelity="observed_multifidelity_common_objective_proxy",
            objectives={
                "estimated_workflow_wall_time_ms": _finite_float(metrics.get("estimated_workflow_wall_time_ms"), default=float("inf")),
                "estimated_energy_mj": _finite_float(metrics.get("estimated_energy_mj"), default=float("inf")),
                "fpga_resource_pressure": _finite_float(metrics.get("fpga_resource_pressure"), default=float("inf")),
                "estimated_data_movement_mb": _finite_float(metrics.get("estimated_data_movement_mb"), default=float("inf")),
                "infeasibility_penalty": _finite_float(metrics.get("infeasibility_penalty"), default=float("inf")),
            },
            feasible=True,
            metadata={"source": "method_loop_evaluated_candidate_proxy"},
        ))
    return observations


def _generic_acquisition_component_aliases(generic: Mapping[str, Any]) -> Dict[str, Any]:
    components = generic.get("components", {}) if isinstance(generic.get("components"), Mapping) else {}
    return {
        "generic_constrained_pareto_gain": _round_metric(_finite_float(components.get("constrained_pareto_gain"), default=0.0)),
        "generic_feasibility_probability": _round_metric(_finite_float(components.get("feasibility_probability"), default=0.0)),
        "generic_workflow_risk_coverage": _round_metric(_finite_float(components.get("workflow_risk_coverage"), default=0.0)),
        "generic_evaluation_cost_penalty": _round_metric(_finite_float(components.get("evaluation_cost_penalty"), default=0.0)),
        "generic_frontier_source": str(generic.get("frontier_source", "")),
        "generic_score": _round_metric(_finite_float(generic.get("score"), default=0.0)),
    }


def _combine_generic_and_local_acquisition_scores(generic: Mapping[str, Any], local_score: float) -> float:
    generic_score = _finite_float(generic.get("score"), default=0.0)
    if generic_score <= 0.0:
        return max(0.0, local_score) * 0.05
    return generic_score * (1.0 + math.log1p(max(0.0, local_score)) * 0.05)


def _data_object_lifetime_risk(workload_features: Mapping[str, Any]) -> float:
    lifetime = workload_features.get("data_object_lifetime", {})
    if not isinstance(lifetime, Mapping):
        return 0.0
    hot = min(1.0, _finite_float(lifetime.get("hot_reuse_object_count"), default=0.0) / 4.0)
    checkpoint = min(1.0, _finite_float(lifetime.get("checkpoint_object_count"), default=0.0) / 4.0)
    cross_stage = min(1.0, _finite_float(lifetime.get("cross_stage_lifetime_count"), default=0.0) / 8.0)
    return max(0.0, min(1.0, (hot + checkpoint + cross_stage) / 3.0))


def _data_lifetime_communication_coverage(
    parameters: Mapping[str, Any],
    workload_features: Mapping[str, Any],
) -> float:
    summary = _neural_data_lifetime_summary(workload_features)
    cross_stage = min(1.0, _finite_float(summary.get("cross_stage_edge_count"), default=0.0) / 4.0)
    data_volume = min(1.0, math.log1p(_finite_float(summary.get("total_data_mb"), default=0.0)) / math.log1p(512.0))
    fanout = min(1.0, _finite_float(summary.get("max_consumer_fanout"), default=0.0) / 4.0)
    hbm_hint = min(1.0, _finite_float(summary.get("hbm_residency_edge_count"), default=0.0) / max(1.0, _finite_float(summary.get("cross_stage_edge_count"), default=1.0)))
    topology_fit = 0.0
    if parameters.get("memory_topology") == "hbm_multi_channel":
        topology_fit += 0.35
    if parameters.get("data_residency") == "fpga_hbm_resident_hot_arrays":
        topology_fit += 0.35
    elif parameters.get("data_residency") == "hybrid_checkpointed_residency":
        topology_fit += 0.20
    if parameters.get("runtime_schedule") in {"overlap_dma_compute", "batched_stage_pipeline"}:
        topology_fit += 0.15
    structure_pressure = 0.35 * cross_stage + 0.30 * data_volume + 0.20 * fanout + 0.15 * hbm_hint
    return max(0.0, min(1.0, structure_pressure * max(0.05, topology_fit)))


def _hbm_lifetime_residency_fit(
    parameters: Mapping[str, Any],
    workload_features: Mapping[str, Any],
) -> float:
    summary = _neural_data_lifetime_summary(workload_features)
    cross_stage = _finite_float(summary.get("cross_stage_edge_count"), default=0.0)
    if cross_stage <= 0.0:
        return 0.0
    hbm_edges = _finite_float(summary.get("hbm_residency_edge_count"), default=0.0)
    hbm_hint = max(0.0, min(1.0, hbm_edges / cross_stage))
    if hbm_hint <= 0.0:
        return 0.0
    fit = 0.0
    if parameters.get("memory_topology") == "hbm_multi_channel":
        fit += 0.45
    if parameters.get("data_residency") == "fpga_hbm_resident_hot_arrays":
        fit += 0.45
    elif parameters.get("data_residency") == "hybrid_checkpointed_residency":
        fit += 0.25
    if parameters.get("runtime_schedule") in {"overlap_dma_compute", "batched_stage_pipeline"}:
        fit += 0.10
    return max(0.0, min(1.0, fit * hbm_hint))


def _transfer_sync_risk(row: Mapping[str, Any], workload_features: Mapping[str, Any]) -> float:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    total_ms = max(1.0, _finite_float(metrics.get("estimated_workflow_wall_time_ms"), default=1.0))
    transfer_ms = _finite_float(metrics.get("estimated_visible_transfer_time_ms"), default=0.0)
    sync_ms = _finite_float(metrics.get("estimated_host_sync_time_ms"), default=0.0)
    data_volume = _finite_float(workload_features.get("estimated_workflow_data_volume_mb"), default=0.0)
    return max(0.0, min(1.0, (transfer_ms + sync_ms) / total_ms + min(0.25, data_volume / 4096.0)))


def build_qe_fpga_multi_workload_experiment_report(
    *,
    workload_run_id_prefix: str = "qe_multi_workload_exp",
    candidate_budget: int = 2500,
    promotion_budget: int = 5,
    workloads: Sequence[Mapping[str, Any]] | None = None,
    input_source: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Run the QE FPGA search-baseline experiment across workload variants."""

    resolved_workloads = [
        dict(workload)
        for workload in (
            workloads
            if workloads is not None
            else _qe_fpga_experiment_workload_variants()
        )
        if isinstance(workload, Mapping)
    ]
    resolved_input_source = (
        dict(input_source)
        if isinstance(input_source, Mapping)
        else {
            "source_kind": "built_in_qe_workload_variants",
            "corpus_id": "",
            "workload_count": len(resolved_workloads),
        }
    )
    workload_rows: List[Dict[str, Any]] = []
    for index, workload in enumerate(resolved_workloads):
        workload_id = str(workload["workload_id"])
        manifest = dict(workload["manifest"] if isinstance(workload.get("manifest"), Mapping) else {})
        raw_bundle = workload.get("workflow_bundle", {})
        workflow_bundle = (
            copy.deepcopy(dict(raw_bundle))
            if isinstance(raw_bundle, Mapping) and raw_bundle
            else workflow_bundle_from_qe_mainflow_manifest(manifest)
        )
        raw_abstraction = workload.get("workflow_abstraction", {})
        workflow_abstraction = (
            copy.deepcopy(dict(raw_abstraction))
            if isinstance(raw_abstraction, Mapping) and raw_abstraction
            else build_qe_workflow_fpga_abstraction(workflow_bundle, workload_id=workload_id)
        )
        problem = build_qe_fpga_deployment_search_problem(
            manifest,
            workload_run_id=f"{workload_run_id_prefix}_{workload_id}_{index:02d}",
            workflow_abstraction=workflow_abstraction,
        )
        records = HierarchicalFunnelSearchPolicy(
            bottleneck_keys=("memory_topology", "data_residency", "offload_boundary"),
        ).propose(problem, budget=int(candidate_budget))
        candidates = [record.to_dict() for record in records]
        screening = build_qe_fpga_l1_screening_report(
            manifest,
            problem,
            candidates,
            promotion_budget=int(promotion_budget),
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=True,
        )
        baseline = build_qe_fpga_search_baseline_report(
            manifest,
            problem,
            screening,
            evaluation_budget=int(promotion_budget),
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=True,
        )
        neuromf_policy_evaluation = _multi_workload_light_neuromf_policy_evaluation(
            manifest=manifest,
            problem=problem,
            screening=screening,
            evaluation_budget=int(promotion_budget),
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=True,
        )
        policy_results = _merge_policy_results_by_id(
            baseline.get("policies", []),
            neuromf_policy_evaluation.get("policies", []),
        )
        best_policy_by_l2_edp = (
            _best_policy_by_l2_edp_from_policy_results(policy_results)
            or dict(baseline.get("best_policy_by_l2_edp", {}) if isinstance(baseline.get("best_policy_by_l2_edp"), Mapping) else {})
        )
        neuromf_feedback_sample_count = _neuromf_feedback_sample_count_from_policies(
            policy_results,
            fallback_budget=int(promotion_budget),
        )
        neuromf_graph_samples = _multi_workload_graph_sample_refs(
            workload_id,
            neuromf_policy_evaluation,
        )
        workload_rows.append({
            "workload_id": workload_id,
            "description": str(workload.get("description", "")),
            "variant_knobs": dict(workload.get("variant_knobs", {})),
            "method_policy_id": str(baseline.get("proposed_method_policy_id", "wamf_generic_active_pareto")),
            "candidate_count": int(screening.get("candidate_count", 0)),
            "pareto_candidate_count": len(screening.get("pareto_frontier", []) or []),
            "workflow_abstraction": _wamf_workflow_abstraction_summary(screening),
            "workload_features": dict(screening.get("workload_features", {}) if isinstance(screening.get("workload_features"), Mapping) else {}),
            "policy_results": policy_results,
            "best_policy_by_l2_edp": best_policy_by_l2_edp,
            "neuromf_feedback_sample_count": neuromf_feedback_sample_count,
            "neuromf_graph_sample_count": len(neuromf_graph_samples),
            "neuromf_graph_sample_ids": [str(sample.get("sample_id", "")) for sample in neuromf_graph_samples],
            "neuromf_graph_samples": neuromf_graph_samples,
            "neuromf_policy_evaluation_summary": {
                "training_sample_count": int(
                    neuromf_policy_evaluation.get("trained_surrogate_ref", {}).get("sample_count", 0)
                    if isinstance(neuromf_policy_evaluation.get("trained_surrogate_ref"), Mapping)
                    else 0
                ),
                "policy_count": int(neuromf_policy_evaluation.get("policy_count", 0)),
                "evaluation_budget": int(neuromf_policy_evaluation.get("evaluation_budget", 0)),
                "graph_sample_count": len(neuromf_graph_samples),
            },
        })

    policy_ids = sorted({
        str(policy.get("policy_id", ""))
        for row in workload_rows
        for policy in row.get("policy_results", []) or []
        if isinstance(policy, Mapping)
    })
    return {
        "schema_version": QE_FPGA_MULTI_WORKLOAD_EXPERIMENT_REPORT_SCHEMA,
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "oracle_fidelity": "L2_python_tlm",
        "method_policy_id": "wamf_generic_active_pareto",
        "cheap_prior_policy_id": "workflow_aware_pareto_funnel",
        "input_source": resolved_input_source,
        "workload_count": len(workload_rows),
        "policy_ids": policy_ids,
        "workloads": workload_rows,
        "aggregate": _multi_workload_aggregate(workload_rows),
        "neuromf_ood_protocol": _multi_workload_neuromf_ood_protocol(workload_rows, policy_ids),
        "experiment_limitations": [
            "workload_variants_are_adapter_level_model_fixtures_not_real_qe_runtime_profiles",
            "L2_python_tlm_is_not_systemc_gem5_hls_vivado_or_board_evidence",
            "real_DAC_grade_evaluation_still_requires_measured_QE_profiles_and_HLS_Vivado_feedback",
        ],
        "claim_boundary": "multi_workload_l2_tlm_experiment_only_not_final_hardware_evidence",
    }


def _multi_workload_light_neuromf_policy_evaluation(
    *,
    manifest: Mapping[str, Any],
    problem: SearchProblem | Mapping[str, Any],
    screening: Mapping[str, Any],
    evaluation_budget: int,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    budget = max(1, int(evaluation_budget))
    initial_designs = min(2, budget)
    ensemble_size = 3
    unguided = build_qe_fpga_neural_multifidelity_search_report(
        manifest,
        problem,
        screening,
        evaluation_budget=max(budget, 4),
        initial_designs=initial_designs,
        ensemble_size=ensemble_size,
        include_retrospective_oracle=False,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    trained_surrogate = build_qe_fpga_neural_surrogate_training_report(
        manifest,
        problem,
        screening,
        unguided,
        ensemble_size=ensemble_size,
        max_epochs=4,
        seed=31,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    trained = build_qe_fpga_neural_multifidelity_search_report(
        manifest,
        problem,
        screening,
        evaluation_budget=budget,
        initial_designs=initial_designs,
        ensemble_size=ensemble_size,
        trained_surrogate=trained_surrogate,
        include_retrospective_oracle=False,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    policy_evaluation = build_qe_fpga_neuromf_policy_evaluation_report(
        manifest,
        problem,
        screening,
        unguided_neural_search=unguided,
        trained_neural_search=trained,
        trained_surrogate=trained_surrogate,
        evaluation_budget=budget,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    policy_evaluation["trained_surrogate_detail"] = {
        "schema_version": str(trained_surrogate.get("schema_version", "")),
        "graph_dataset_contract": dict(
            trained_surrogate.get("graph_dataset_contract", {})
            if isinstance(trained_surrogate.get("graph_dataset_contract"), Mapping)
            else {}
        ),
        "graph_dataset_samples": list(
            trained_surrogate.get("graph_dataset_samples", [])
            if isinstance(trained_surrogate.get("graph_dataset_samples"), list)
            else []
        ),
    }
    return policy_evaluation


def _multi_workload_graph_sample_refs(
    workload_id: str,
    neuromf_policy_evaluation: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    surrogate = (
        neuromf_policy_evaluation.get("trained_surrogate_detail", {})
        if isinstance(neuromf_policy_evaluation.get("trained_surrogate_detail"), Mapping)
        else {}
    )
    samples = surrogate.get("graph_dataset_samples", []) if isinstance(surrogate.get("graph_dataset_samples"), list) else []
    refs: List[Dict[str, Any]] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            continue
        graph_id = str(sample.get("graph_id") or f"graph_{index:03d}")
        sample_payload = copy.deepcopy(dict(sample))
        sample_payload.update({
            "sample_id": f"{workload_id}::{graph_id}",
            "workload_id": workload_id,
            "graph_id": graph_id,
            "candidate_id": str(sample.get("candidate_id", "")),
        })
        refs.append(sample_payload)
    return refs


def _merge_policy_results_by_id(
    baseline_policies: Any,
    neuromf_policies: Any,
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for policy in baseline_policies or []:
        if isinstance(policy, Mapping) and policy.get("policy_id"):
            merged[str(policy.get("policy_id"))] = dict(policy)
    for policy in neuromf_policies or []:
        if not isinstance(policy, Mapping) or not policy.get("policy_id"):
            continue
        policy_id = str(policy.get("policy_id"))
        if policy_id.startswith("neuromf_"):
            merged[policy_id] = dict(policy)
    return [merged[key] for key in sorted(merged)]


def _best_policy_by_l2_edp_from_policy_results(policy_results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    scored: List[Tuple[float, str, Mapping[str, Any]]] = []
    for policy in policy_results:
        if not isinstance(policy, Mapping):
            continue
        oracle = policy.get("l2_oracle", {}) if isinstance(policy.get("l2_oracle"), Mapping) else {}
        edp = _finite_float(oracle.get("best_tlm_edp"), default=float("inf"))
        if math.isfinite(edp):
            scored.append((edp, str(policy.get("policy_id", "")), policy))
    if not scored:
        return {}
    edp, policy_id, policy = min(scored, key=lambda item: (item[0], item[1]))
    oracle = policy.get("l2_oracle", {}) if isinstance(policy.get("l2_oracle"), Mapping) else {}
    return {
        "policy_id": policy_id,
        "best_tlm_edp": edp,
        "oracle_rank_of_best_selected": oracle.get("oracle_rank_of_best_selected"),
        "tie_break_basis": "min_l2_tlm_edp_across_multi_workload_policy_results",
    }


def _neuromf_feedback_sample_count_from_policies(
    policies: Any,
    *,
    fallback_budget: int,
) -> int:
    counts: List[int] = []
    for policy in policies or []:
        if not isinstance(policy, Mapping):
            continue
        oracle = policy.get("l2_oracle", {}) if isinstance(policy.get("l2_oracle"), Mapping) else {}
        count = int(_finite_float(oracle.get("evaluated_count"), default=0.0))
        if count > 0:
            counts.append(count)
    return max(counts) if counts else max(0, int(fallback_budget))


def _multi_workload_neuromf_ood_protocol(
    workload_rows: Sequence[Mapping[str, Any]],
    policy_ids: Sequence[str],
) -> Dict[str, Any]:
    workload_ids = sorted(str(row.get("workload_id", "")) for row in workload_rows if row.get("workload_id"))
    feedback_counts = {
        str(row.get("workload_id", "")): int(_finite_float(row.get("neuromf_feedback_sample_count"), default=0.0))
        for row in workload_rows
        if row.get("workload_id")
    }
    graph_sample_ids = {
        str(row.get("workload_id", "")): [
            str(sample_id)
            for sample_id in row.get("neuromf_graph_sample_ids", []) or []
        ]
        for row in workload_rows
        if row.get("workload_id")
    }
    folds = [
        {
            "fold_id": f"leave_one_workload_out::{workload_id}",
            "test_workload_id": workload_id,
            "train_workload_ids": [item for item in workload_ids if item != workload_id],
            "train_feedback_sample_count": sum(count for item, count in feedback_counts.items() if item != workload_id),
            "test_feedback_sample_count": feedback_counts.get(workload_id, 0),
            "train_graph_sample_ids": [
                sample_id
                for item in workload_ids
                if item != workload_id
                for sample_id in graph_sample_ids.get(item, [])
            ],
            "test_graph_sample_ids": graph_sample_ids.get(workload_id, []),
        }
        for workload_id in workload_ids
    ]
    ready = len(workload_ids) >= 3 and all(count > 0 for count in feedback_counts.values())
    return {
        "schema_version": "dse.qe_fpga.neuromf_multi_workload_ood_protocol.v1",
        "status": (
            "ready_for_leave_one_workload_out_evaluation"
            if ready
            else "blocked_insufficient_multi_workload_feedback"
        ),
        "split_axis": "workload_id",
        "target": "rank_and_regret_generalization_over_l2_python_tlm_oracle",
        "distinct_workload_count": len(workload_ids),
        "workload_ids": workload_ids,
        "fold_count": len(folds),
        "folds": folds,
        "feedback_sample_count": sum(feedback_counts.values()),
        "feedback_sample_counts_by_workload": dict(sorted(feedback_counts.items())),
        "baseline_policy_ids": sorted(str(policy_id) for policy_id in policy_ids),
        "graph_corpus": _multi_workload_graph_corpus(workload_rows),
        "generalization_summary": _multi_workload_loo_generalization_summary(workload_rows, policy_ids),
        "blocked_reasons": [] if ready else ["need_at_least_three_workloads_with_feedback_samples"],
        "evaluation_boundary": "model_level_l2_tlm_oracle_protocol_not_hardware_generalization_proof",
    }


def _multi_workload_graph_corpus(workload_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    workload_ids = sorted(str(row.get("workload_id", "")) for row in workload_rows if row.get("workload_id"))
    sample_refs = [
        {
            "sample_id": str(sample_id),
            "workload_id": str(row.get("workload_id", "")),
        }
        for row in workload_rows
        for sample_id in (row.get("neuromf_graph_sample_ids", []) or [])
        if row.get("workload_id") and sample_id
    ]
    return {
        "schema_version": "dse.qe_fpga.neuromf_multi_workload_graph_corpus.v1",
        "sample_count": len(sample_refs),
        "workload_ids": workload_ids,
        "sample_refs": sample_refs,
        "node_type_set": [
            "candidate_knob",
            "data_object",
            "fidelity_observation",
            "kernel_family",
            "workload_stage",
        ],
        "edge_type_set": [
            "candidate_binding",
            "data_lifetime",
            "kernel_in_stage",
            "observation_target",
            "stage_dependency",
        ],
        "target": "log_common_objective_edp_residual_over_l1",
        "corpus_boundary": "graph_sample_references_for_cross_workload_training_not_hardware_evidence",
    }


def _multi_workload_loo_generalization_summary(
    workload_rows: Sequence[Mapping[str, Any]],
    policy_ids: Sequence[str],
) -> Dict[str, Any]:
    rows_by_workload = {
        str(row.get("workload_id", "")): row
        for row in workload_rows
        if row.get("workload_id")
    }
    workload_ids = sorted(rows_by_workload)
    fold_results: List[Dict[str, Any]] = []
    for test_workload_id in workload_ids:
        train_workload_ids = [workload_id for workload_id in workload_ids if workload_id != test_workload_id]
        train_selected_policy = _best_policy_across_workloads(
            [rows_by_workload[workload_id] for workload_id in train_workload_ids],
            policy_ids,
        )
        test_row = rows_by_workload[test_workload_id]
        test_policy = _policy_result_by_id(test_row, train_selected_policy)
        trained_policy = _policy_result_by_id(test_row, "neuromf_trained_surrogate")
        fold_results.append({
            "fold_id": f"leave_one_workload_out::{test_workload_id}",
            "test_workload_id": test_workload_id,
            "train_workload_ids": train_workload_ids,
            "train_selected_policy_id": train_selected_policy,
            "test_oracle_rank_of_train_selected_policy": _policy_oracle_rank(test_policy),
            "test_simple_regret_of_train_selected_policy": _policy_simple_regret(test_policy),
            "trained_neuromf_oracle_rank": _policy_oracle_rank(trained_policy),
            "trained_neuromf_simple_regret": _policy_simple_regret(trained_policy),
        })
    return {
        "schema_version": "dse.qe_fpga.neuromf_loo_generalization_summary.v1",
        "fold_count": len(fold_results),
        "fold_results": fold_results,
        "surrogate_loo_evaluation": _multi_workload_surrogate_loo_evaluation(workload_rows),
        "aggregate": {
            "mean_test_rank_of_train_selected_policy": _round_metric(_mean([
                _finite_float(row.get("test_oracle_rank_of_train_selected_policy"), default=0.0)
                for row in fold_results
            ])),
            "mean_test_regret_of_train_selected_policy": _round_metric(_mean([
                _finite_float(row.get("test_simple_regret_of_train_selected_policy"), default=0.0)
                for row in fold_results
            ])),
            "mean_trained_neuromf_rank": _round_metric(_mean([
                _finite_float(row.get("trained_neuromf_oracle_rank"), default=0.0)
                for row in fold_results
            ])),
            "mean_trained_neuromf_regret": _round_metric(_mean([
                _finite_float(row.get("trained_neuromf_simple_regret"), default=0.0)
                for row in fold_results
            ])),
            "baseline_policy_count": len([policy_id for policy_id in policy_ids if policy_id]),
        },
        "metric_boundary": "leave_one_workload_out_policy_transfer_over_l2_tlm_model_oracle_not_measured_hardware",
    }


def _best_policy_across_workloads(
    workload_rows: Sequence[Mapping[str, Any]],
    policy_ids: Sequence[str],
) -> str:
    scored: List[Tuple[float, float, str]] = []
    for policy_id in sorted(str(item) for item in policy_ids if item):
        ranks: List[float] = []
        regrets: List[float] = []
        for row in workload_rows:
            policy = _policy_result_by_id(row, policy_id)
            rank = _policy_oracle_rank(policy)
            regret = _policy_simple_regret(policy)
            if rank > 0.0:
                ranks.append(rank)
            if math.isfinite(regret):
                regrets.append(regret)
        if not ranks:
            continue
        scored.append((_mean(ranks), _mean(regrets), policy_id))
    if not scored:
        return ""
    return min(scored, key=lambda item: (item[0], item[1], item[2]))[2]


def _multi_workload_surrogate_loo_evaluation(
    workload_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    samples_by_workload = {
        str(row.get("workload_id", "")): [
            sample for sample in row.get("neuromf_graph_samples", []) or []
            if isinstance(sample, Mapping)
        ]
        for row in workload_rows
        if row.get("workload_id")
    }
    workload_ids = sorted(samples_by_workload)
    if len(workload_ids) < 3 or any(not samples_by_workload.get(workload_id) for workload_id in workload_ids):
        return {
            "schema_version": "dse.qe_fpga.neuromf_surrogate_loo_evaluation.v1",
            "status": "blocked_insufficient_graph_training_samples",
            "split_axis": "workload_id",
            "target_name": "log_common_objective_edp_residual_over_l1",
            "fold_count": 0,
            "fold_results": [],
            "aggregate": {
                "mean_rmse_log_residual": 0.0,
                "mean_spearman_rank_correlation": 0.0,
                "mean_top_k_recall_at_3": 0.0,
            },
            "blocked_reasons": ["need_at_least_three_workloads_with_graph_samples"],
            "evaluation_boundary": "leave_one_workload_out_surrogate_model_validation_over_l2_tlm_feedback_not_hardware_proof",
        }

    fold_results: List[Dict[str, Any]] = []
    trained_backend_runtime: Dict[str, Any] = {}
    for test_workload_id in workload_ids:
        train_workload_ids = [workload_id for workload_id in workload_ids if workload_id != test_workload_id]
        train_samples = [
            sample
            for workload_id in train_workload_ids
            for sample in samples_by_workload.get(workload_id, [])
        ]
        heldout_samples = list(samples_by_workload.get(test_workload_id, []))
        predictions = [
            _multi_workload_predict_graph_residual(sample, train_samples)
            for sample in heldout_samples
        ]
        trained_predictions, backend_runtime = _multi_workload_trained_graph_surrogate_predictions(
            train_samples,
            heldout_samples,
            seed=43 + len(fold_results) * 17,
        )
        if not trained_backend_runtime and backend_runtime:
            trained_backend_runtime = dict(backend_runtime)
        fold_metrics = _multi_workload_surrogate_fold_metrics(
            fold_id=f"leave_one_workload_out::{test_workload_id}",
            test_workload_id=test_workload_id,
            train_workload_ids=train_workload_ids,
            train_sample_count=len(train_samples),
            heldout_samples=heldout_samples,
            predictions=predictions,
        )
        trained_metrics = _multi_workload_surrogate_fold_metrics(
            fold_id=f"leave_one_workload_out::{test_workload_id}",
            test_workload_id=test_workload_id,
            train_workload_ids=train_workload_ids,
            train_sample_count=len(train_samples),
            heldout_samples=heldout_samples,
            predictions=trained_predictions,
        )
        fold_metrics.update({
            "trained_rmse_log_residual": trained_metrics["rmse_log_residual"],
            "trained_rmse_log_edp": trained_metrics["rmse_log_edp"],
            "trained_spearman_rank_correlation": trained_metrics["spearman_rank_correlation"],
            "trained_top_k_recall_at_3": trained_metrics["top_k_recall_at_3"],
            "trained_selected_candidate_id": trained_metrics["selected_candidate_id"],
            "trained_selected_oracle_rank": trained_metrics["selected_oracle_rank"],
            "trained_selected_simple_regret": trained_metrics["selected_simple_regret"],
            "trained_prediction_samples": trained_predictions,
        })
        fold_results.append(fold_metrics)

    return {
        "schema_version": "dse.qe_fpga.neuromf_surrogate_loo_evaluation.v1",
        "status": "evaluated",
        "split_axis": "workload_id",
        "target_name": "log_common_objective_edp_residual_over_l1",
        "primary_model_id": "trained_graph_projection_mlp_residual_surrogate",
        "models_compared": [
            "knn_graph_projection_residual_baseline",
            "trained_graph_projection_mlp_residual_surrogate",
        ],
        "fold_count": len(fold_results),
        "fold_results": fold_results,
        "aggregate": {
            "mean_rmse_log_residual": _round_metric(_mean([
                _finite_float(row.get("rmse_log_residual"), default=0.0)
                for row in fold_results
            ])),
            "mean_rmse_log_edp": _round_metric(_mean([
                _finite_float(row.get("rmse_log_edp"), default=0.0)
                for row in fold_results
            ])),
            "mean_spearman_rank_correlation": _round_metric(_mean([
                _finite_float(row.get("spearman_rank_correlation"), default=0.0)
                for row in fold_results
            ])),
            "mean_top_k_recall_at_3": _round_metric(_mean([
                _finite_float(row.get("top_k_recall_at_3"), default=0.0)
                for row in fold_results
            ])),
            "trained_mean_rmse_log_residual": _round_metric(_mean([
                _finite_float(row.get("trained_rmse_log_residual"), default=0.0)
                for row in fold_results
            ])),
            "trained_mean_rmse_log_edp": _round_metric(_mean([
                _finite_float(row.get("trained_rmse_log_edp"), default=0.0)
                for row in fold_results
            ])),
            "trained_mean_spearman_rank_correlation": _round_metric(_mean([
                _finite_float(row.get("trained_spearman_rank_correlation"), default=0.0)
                for row in fold_results
            ])),
            "trained_mean_top_k_recall_at_3": _round_metric(_mean([
                _finite_float(row.get("trained_top_k_recall_at_3"), default=0.0)
                for row in fold_results
            ])),
            "trained_mean_selected_simple_regret": _round_metric(_mean([
                _finite_float(row.get("trained_selected_simple_regret"), default=0.0)
                for row in fold_results
            ])),
            "mean_selected_simple_regret": _round_metric(_mean([
                _finite_float(row.get("selected_simple_regret"), default=0.0)
                for row in fold_results
            ])),
        },
        "model": {
            "model_type": "graph_projection_knn_residual_surrogate",
            "target": "log_common_objective_edp_residual_over_l1",
            "distance": "normalized_graph_projection_l2",
            "k_neighbors": 3,
            "role": "cross_workload_generalization_protocol_baseline_for_neuromf",
        },
        "trained_surrogate_backend": {
            "framework": "torch",
            "model_type": "tabular_mlp_deep_ensemble",
            "device_policy": str(trained_backend_runtime.get("device_policy", "cuda_if_available")),
            "resolved_device": str(trained_backend_runtime.get("resolved_device", "cpu")),
            "cuda_available": bool(trained_backend_runtime.get("cuda_available", False)),
            "cuda_device_count": int(_finite_float(trained_backend_runtime.get("cuda_device_count"), default=0.0)),
            "cuda_device_name": str(trained_backend_runtime.get("cuda_device_name", "")),
            "torch_version": str(trained_backend_runtime.get("torch_version", "")),
            **(
                {"device_fallback_reason": str(trained_backend_runtime.get("device_fallback_reason", ""))}
                if trained_backend_runtime.get("device_fallback_reason")
                else {}
            ),
        },
        "evaluation_boundary": "leave_one_workload_out_surrogate_model_validation_over_l2_tlm_feedback_not_hardware_proof",
    }


def _multi_workload_trained_graph_surrogate_predictions(
    train_samples: Sequence[Mapping[str, Any]],
    heldout_samples: Sequence[Mapping[str, Any]],
    *,
    seed: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    encoded_rows = [
        _multi_workload_graph_sample_encoded_row(sample)
        for sample in list(train_samples) + list(heldout_samples)
    ]
    train_count = len(train_samples)
    split_rows = {
        "train": list(range(train_count)),
        "validation": [],
        "holdout": list(range(train_count, len(encoded_rows))),
    }
    training_result = _train_tabular_neural_ensemble(
        encoded_rows,
        split_rows=split_rows,
        ensemble_size=3,
        max_epochs=6,
        seed=int(seed),
    )
    all_predictions = list(training_result.get("predictions", []) or [])
    heldout_predictions = all_predictions[train_count:]
    converted: List[Dict[str, Any]] = []
    for sample, prediction in zip(heldout_samples, heldout_predictions):
        converted.append({
            "sample_id": str(sample.get("sample_id", "")),
            "candidate_id": str(sample.get("candidate_id", "")),
            "predicted_log_residual": _finite_float(
                prediction.get("predicted_log_residual_mean"),
                default=0.0,
            ),
            "predicted_log_edp": _finite_float(
                prediction.get("predicted_log_edp_mean"),
                default=0.0,
            ),
            "predicted_edp": _finite_float(
                prediction.get("predicted_edp_mean"),
                default=1.0,
            ),
            "predicted_edp_std": _finite_float(
                prediction.get("predicted_edp_std"),
                default=0.0,
            ),
        })
    return converted, dict(
        training_result.get("backend_runtime", {})
        if isinstance(training_result.get("backend_runtime"), Mapping)
        else {}
    )


def _multi_workload_graph_sample_encoded_row(sample: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "candidate_id": str(sample.get("candidate_id", "")),
        "design_key": str(sample.get("sample_id") or sample.get("graph_id") or ""),
        "features": _multi_workload_graph_numeric_vector(sample),
        "target_log_edp": _graph_sample_target_log_edp(sample),
        "target_log_residual": _graph_sample_residual(sample),
        "l1_log_edp": _graph_sample_l1_log_edp(sample),
        "observed_edp": _graph_sample_observed_edp(sample),
        "fidelity": str(_graph_sample_target(sample).get("fidelity", "")),
    }


def _multi_workload_predict_graph_residual(
    heldout_sample: Mapping[str, Any],
    train_samples: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    heldout_vector = _multi_workload_graph_numeric_vector(heldout_sample)
    scored: List[Tuple[float, Mapping[str, Any]]] = []
    for train_sample in train_samples:
        if not isinstance(train_sample, Mapping):
            continue
        distance = _normalized_l2_distance(heldout_vector, _multi_workload_graph_numeric_vector(train_sample))
        scored.append((distance, train_sample))
    if not scored:
        predicted_residual = 0.0
        neighbor_ids: List[str] = []
    else:
        neighbors = sorted(scored, key=lambda item: (
            item[0],
            str(item[1].get("sample_id", "")),
        ))[:3]
        weights = [1.0 / (1.0e-9 + distance) for distance, _sample in neighbors]
        weight_sum = sum(weights) or 1.0
        predicted_residual = sum(
            weight * _graph_sample_residual(sample)
            for weight, (_distance, sample) in zip(weights, neighbors)
        ) / weight_sum
        neighbor_ids = [str(sample.get("sample_id", "")) for _distance, sample in neighbors]
    l1_log_edp = _graph_sample_l1_log_edp(heldout_sample)
    predicted_log_edp = max(-32.0, min(32.0, l1_log_edp + predicted_residual))
    return {
        "sample_id": str(heldout_sample.get("sample_id", "")),
        "candidate_id": str(heldout_sample.get("candidate_id", "")),
        "predicted_log_residual": _round_metric(predicted_residual),
        "predicted_log_edp": _round_metric(predicted_log_edp),
        "predicted_edp": _round_metric(max(1.0, math.exp(predicted_log_edp))),
        "neighbor_sample_ids": neighbor_ids,
    }


def _multi_workload_surrogate_fold_metrics(
    *,
    fold_id: str,
    test_workload_id: str,
    train_workload_ids: Sequence[str],
    train_sample_count: int,
    heldout_samples: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    heldout_count = len(heldout_samples)
    if heldout_count <= 0:
        return {
            "fold_id": fold_id,
            "test_workload_id": test_workload_id,
            "train_workload_ids": list(train_workload_ids),
            "train_sample_count": int(train_sample_count),
            "heldout_sample_count": 0,
            "rmse_log_residual": 0.0,
            "rmse_log_edp": 0.0,
            "spearman_rank_correlation": 0.0,
            "top_k_recall_at_3": 0.0,
            "selected_simple_regret": 0.0,
        }
    target_residuals = [_graph_sample_residual(sample) for sample in heldout_samples]
    predicted_residuals = [
        _finite_float(prediction.get("predicted_log_residual"), default=0.0)
        for prediction in predictions
    ]
    target_log_edp = [_graph_sample_target_log_edp(sample) for sample in heldout_samples]
    predicted_log_edp = [
        _finite_float(prediction.get("predicted_log_edp"), default=0.0)
        for prediction in predictions
    ]
    target_edp = [_graph_sample_observed_edp(sample) for sample in heldout_samples]
    predicted_edp = [
        _finite_float(prediction.get("predicted_edp"), default=0.0)
        for prediction in predictions
    ]
    residual_errors = [pred - target for pred, target in zip(predicted_residuals, target_residuals)]
    log_edp_errors = [pred - target for pred, target in zip(predicted_log_edp, target_log_edp)]
    k = min(3, heldout_count)
    true_top = set(sorted(range(heldout_count), key=lambda index: target_edp[index])[:k])
    predicted_top = set(sorted(range(heldout_count), key=lambda index: predicted_edp[index])[:k])
    predicted_best_index = min(range(heldout_count), key=lambda index: predicted_edp[index])
    true_order = sorted(range(heldout_count), key=lambda index: target_edp[index])
    selected_rank = true_order.index(predicted_best_index) + 1
    best_true_edp = target_edp[true_order[0]]
    selected_edp = target_edp[predicted_best_index]
    return {
        "fold_id": fold_id,
        "test_workload_id": test_workload_id,
        "train_workload_ids": list(train_workload_ids),
        "train_sample_count": int(train_sample_count),
        "heldout_sample_count": heldout_count,
        "rmse_log_residual": _round_metric(math.sqrt(_mean([error * error for error in residual_errors]))),
        "rmse_log_edp": _round_metric(math.sqrt(_mean([error * error for error in log_edp_errors]))),
        "spearman_rank_correlation": _round_metric(_spearman(target_edp, predicted_edp)),
        "top_k_recall_at_3": _round_metric(len(true_top & predicted_top) / float(max(1, len(true_top)))),
        "selected_candidate_id": str(heldout_samples[predicted_best_index].get("candidate_id", "")),
        "selected_oracle_rank": selected_rank,
        "selected_simple_regret": _round_metric(max(0.0, selected_edp - best_true_edp)),
        "prediction_samples": [dict(prediction) for prediction in predictions],
    }


def _multi_workload_graph_numeric_vector(sample: Mapping[str, Any]) -> List[float]:
    node_counts = sample.get("node_counts", {}) if isinstance(sample.get("node_counts"), Mapping) else {}
    edge_counts = sample.get("edge_counts", {}) if isinstance(sample.get("edge_counts"), Mapping) else {}
    lifetime = sample.get("data_lifetime_summary", {}) if isinstance(sample.get("data_lifetime_summary"), Mapping) else {}
    workload = sample.get("workload_summary", {}) if isinstance(sample.get("workload_summary"), Mapping) else {}
    knobs = sample.get("candidate_knobs", []) if isinstance(sample.get("candidate_knobs"), list) else []
    knob_values = {
        str(row.get("name", "")): _finite_float(row.get("numeric_value"), default=0.0)
        for row in knobs
        if isinstance(row, Mapping)
    }
    return [
        _scaled_graph_feature(node_counts.get("workload_stage")),
        _scaled_graph_feature(node_counts.get("kernel_family")),
        _scaled_graph_feature(node_counts.get("data_object")),
        _scaled_graph_feature(node_counts.get("candidate_knob")),
        _scaled_graph_feature(edge_counts.get("stage_dependency")),
        _scaled_graph_feature(edge_counts.get("kernel_in_stage")),
        _scaled_graph_feature(edge_counts.get("data_lifetime")),
        _scaled_graph_feature(lifetime.get("total_data_mb")),
        _scaled_graph_feature(lifetime.get("max_consumer_fanout")),
        _scaled_graph_feature(lifetime.get("hbm_residency_edge_count")),
        _scaled_graph_feature(lifetime.get("checkpoint_residency_edge_count")),
        _scaled_graph_feature(workload.get("stage_count")),
        _scaled_graph_feature(workload.get("graph_node_count")),
        _scaled_graph_feature(workload.get("graph_edge_count")),
        _finite_float(workload.get("host_control_intensity"), default=0.0),
        _finite_float(workload.get("post_processing_intensity"), default=0.0),
        _scaled_graph_feature(workload.get("estimated_workflow_data_volume_mb")),
        _scaled_graph_feature(knob_values.get("vector_lanes")),
        _scaled_graph_feature(knob_values.get("hbm_channel_count")),
        _scaled_graph_feature(knob_values.get("tile_doubles")),
        _graph_sample_l1_log_edp(sample) / 32.0,
    ]


def _scaled_graph_feature(value: Any) -> float:
    return math.log1p(max(0.0, _finite_float(value, default=0.0)))


def _normalized_l2_distance(left: Sequence[float], right: Sequence[float]) -> float:
    width = max(len(left), len(right))
    if width <= 0:
        return 0.0
    total = 0.0
    for index in range(width):
        left_value = float(left[index]) if index < len(left) else 0.0
        right_value = float(right[index]) if index < len(right) else 0.0
        total += (left_value - right_value) ** 2
    return math.sqrt(total / float(width))


def _graph_sample_target(sample: Mapping[str, Any]) -> Mapping[str, Any]:
    return sample.get("target", {}) if isinstance(sample.get("target"), Mapping) else {}


def _graph_sample_residual(sample: Mapping[str, Any]) -> float:
    target = _graph_sample_target(sample)
    residual = _finite_float(target.get("residual_log_edp"), default=float("nan"))
    if math.isfinite(residual):
        return residual
    return _graph_sample_target_log_edp(sample) - _graph_sample_l1_log_edp(sample)


def _graph_sample_l1_log_edp(sample: Mapping[str, Any]) -> float:
    target = _graph_sample_target(sample)
    l1_log = _finite_float(target.get("l1_log_edp"), default=float("nan"))
    if math.isfinite(l1_log):
        return l1_log
    l1_edp = max(1.0, _finite_float(target.get("l1_edp"), default=1.0))
    return math.log(l1_edp)


def _graph_sample_target_log_edp(sample: Mapping[str, Any]) -> float:
    target = _graph_sample_target(sample)
    target_log = _finite_float(target.get("target_log_edp"), default=float("nan"))
    if math.isfinite(target_log):
        return target_log
    return math.log(_graph_sample_observed_edp(sample))


def _graph_sample_observed_edp(sample: Mapping[str, Any]) -> float:
    target = _graph_sample_target(sample)
    return max(1.0, _finite_float(target.get("observed_edp"), default=1.0))


def _policy_result_by_id(workload_row: Mapping[str, Any], policy_id: str) -> Dict[str, Any]:
    for policy in workload_row.get("policy_results", []) or []:
        if isinstance(policy, Mapping) and policy.get("policy_id") == policy_id:
            return dict(policy)
    return {}


def _policy_oracle_rank(policy: Mapping[str, Any]) -> float:
    oracle = policy.get("l2_oracle", {}) if isinstance(policy.get("l2_oracle"), Mapping) else {}
    rank = _finite_float(oracle.get("oracle_rank_of_best_selected"), default=0.0)
    if rank > 0.0:
        return rank
    curve = policy.get("budget_curve", []) if isinstance(policy.get("budget_curve"), list) else []
    if curve and isinstance(curve[-1], Mapping):
        return _finite_float(curve[-1].get("oracle_rank_of_best"), default=0.0)
    return 0.0


def _policy_simple_regret(policy: Mapping[str, Any]) -> float:
    curve = policy.get("budget_curve", []) if isinstance(policy.get("budget_curve"), list) else []
    if curve and isinstance(curve[-1], Mapping):
        regret = _finite_float(curve[-1].get("simple_regret"), default=float("nan"))
        if math.isfinite(regret):
            return max(0.0, regret)
    oracle = policy.get("l2_oracle", {}) if isinstance(policy.get("l2_oracle"), Mapping) else {}
    best = _finite_float(oracle.get("best_tlm_edp"), default=float("nan"))
    if math.isfinite(best):
        return 0.0
    return float("inf")


def build_qe_fpga_implementation_package_plan(
    manifest: Mapping[str, Any],
    l2_request_bundle: Mapping[str, Any],
    l2_results: Mapping[str, Any],
    *,
    package_budget: int = 2,
) -> Dict[str, Any]:
    """Plan candidate-specific HLS/Vivado source packages from L2 results."""

    validation = _require_mainflow_or_model_seed(manifest, stage="implementation packaging")
    result_by_candidate = {
        str(row.get("candidate_id", "")): row
        for row in l2_results.get("results", []) or []
        if isinstance(row, Mapping)
    }
    requests = [
        request for request in l2_request_bundle.get("requests", []) or []
        if isinstance(request, Mapping)
    ]
    ranked = sorted(
        requests,
        key=lambda request: _implementation_package_sort_key(request, result_by_candidate),
    )
    packages = [
        _implementation_package_entry(request, result_by_candidate, index)
        for index, request in enumerate(ranked[: max(0, int(package_budget))])
    ]
    return {
        "schema_version": QE_FPGA_IMPLEMENTATION_PACKAGE_PLAN_SCHEMA,
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "status": "packages_planned_not_synthesized",
        "package_count": len(packages),
        "package_budget": int(package_budget),
        "packages": packages,
        "selection_policy": "lowest_l2_tlm_edp_then_resource_pressure",
        "required_next_tool_steps": [
            "materialize_candidate_manifest_and_hls_sources",
            "run_hls_csim_or_rtl_sim",
            "run_hls_synthesis",
            "run_vivado_synthesis_or_packaging",
            "run_write_bitstream_or_xclbin_when_platform_constraints_exist",
        ],
        "claim_boundary": "implementation_package_plan_only_not_hls_vivado_or_bitstream_evidence",
    }


def materialize_qe_fpga_implementation_packages(
    implementation_plan: Mapping[str, Any],
    out_dir: str | Path,
) -> Dict[str, Any]:
    """Write candidate-specific HLS/Vivado package skeletons.

    This creates reproducible tool input files only.  It does not run HLS,
    Vivado, a board flow, or QE correctness validation.
    """

    root = Path(out_dir)
    packages = [
        package for package in implementation_plan.get("packages", []) or []
        if isinstance(package, Mapping)
    ]
    materialized_packages = [
        _materialize_qe_fpga_implementation_package(root, package)
        for package in packages
    ]
    closure_summary = _implementation_closure_summary(materialized_packages)
    return {
        "schema_version": QE_FPGA_IMPLEMENTATION_PACKAGE_MATERIALIZATION_SCHEMA,
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "status": "sources_materialized_not_synthesized",
        "package_count": len(materialized_packages),
        "packages": materialized_packages,
        "closure_summary": closure_summary,
        "required_next_tool_steps": [
            "run_hls_csim_or_rtl_sim_against_qe_golden_vectors",
            "run_hls_synthesis",
            "run_vivado_synthesis_or_implementation_with_real_part_and_constraints",
            "run_write_bitstream_or_xclbin_when_platform_constraints_exist",
            "feed_real_tool_reports_back_to_step4_calibration",
        ],
        "claim_boundary": "materialized_hls_sources_only_not_synthesis_or_bitstream_evidence",
    }


def run_qe_fpga_hls_attempt(
    package_root: str | Path,
    *,
    hls_tool: str | None = None,
    timeout_s: int = 900,
) -> Dict[str, Any]:
    """Attempt HLS csim/csynth for one materialized QE FPGA package."""

    root = Path(package_root)
    manifest_path = root / "candidate_manifest.json"
    manifest = _load_json_object(manifest_path)
    candidate_id = str(manifest.get("candidate_id", ""))
    design_key = str(manifest.get("design_key", ""))
    requested_tool = _resolve_hls_tool_request(hls_tool)
    tool_path = _resolve_executable(requested_tool)
    if tool_path is None:
        parsed_reports = _hls_parsed_reports(root)
        package_classification = _classify_hls_package_evidence(root)
        attempt = _hls_attempt_payload(
            root=root,
            manifest_path=manifest_path,
            candidate_id=candidate_id,
            design_key=design_key,
            status="blocked_hls_tool_unavailable",
            hls_csim_status="blocked",
            hls_csynth_status="blocked",
            commands=[],
            blockers=["hls_tool_unavailable"],
            requested_tool=requested_tool,
            resolved_tool=None,
            parsed_reports=parsed_reports,
            feedback_sample=None,
            package_evidence_classification=package_classification,
        )
        _write_json_file(root / "hls_attempt.json", attempt)
        return attempt

    command = [tool_path, "-f", "scripts/run_hls.tcl"]
    command_result = _run_process(command, cwd=root, timeout_s=max(1, int(timeout_s)))
    command_result["tool"] = tool_path
    combined = "\n".join([
        str(command_result.get("stdout_tail", "")),
        str(command_result.get("stderr_tail", "")),
    ])
    csim_status = _hls_stage_status(combined, stage="csim")
    csynth_status = _hls_stage_status(combined, stage="csynth")
    tool_classification = _classify_hls_tool_evidence(tool_path)
    package_classification = _classify_hls_package_evidence(root)
    if command_result.get("returncode") != 0:
        status = "hls_attempt_failed"
        blockers = ["hls_tool_returned_nonzero"]
    elif csim_status == "passed" and csynth_status == "passed":
        if (
            tool_classification["classification"] == "real_hls_tool"
            and package_classification["classification"] == "qe_kernel_with_golden_vectors"
        ):
            status = "hls_attempt_passed"
            blockers = []
        else:
            status = "hls_attempt_non_evidence"
            blockers = list(tool_classification["blockers"]) + list(package_classification["blockers"])
    else:
        status = "hls_attempt_inconclusive"
        blockers = ["hls_transcript_missing_pass_markers"]
    parsed_reports = _hls_parsed_reports(root)
    feedback_sample = None
    if (
        status == "hls_attempt_passed"
        and tool_classification["classification"] == "real_hls_tool"
        and package_classification["classification"] == "qe_kernel_with_golden_vectors"
    ):
        feedback_sample = _hls_feedback_sample_from_parsed_report(
            parsed_reports.get("csynth", {}),
            manifest=manifest,
            candidate_id=candidate_id,
            design_key=design_key,
            tool_path=tool_path,
            tool_evidence_classification=tool_classification,
            package_evidence_classification=package_classification,
        )
    attempt = _hls_attempt_payload(
        root=root,
        manifest_path=manifest_path,
        candidate_id=candidate_id,
        design_key=design_key,
        status=status,
        hls_csim_status=csim_status,
        hls_csynth_status=csynth_status,
        commands=[command_result],
        blockers=blockers,
        requested_tool=requested_tool,
        resolved_tool=tool_path,
        parsed_reports=parsed_reports,
        feedback_sample=feedback_sample,
        tool_evidence_classification=tool_classification,
        package_evidence_classification=package_classification,
    )
    _write_json_file(root / "hls_attempt.json", attempt)
    return attempt


def run_qe_fpga_hls_attempts_for_materialized_packages(
    materialization: Mapping[str, Any],
    out_dir: str | Path,
    *,
    hls_tool: str | None = None,
    timeout_s: int = 900,
) -> Dict[str, Any]:
    """Run or record HLS attempts for each materialized implementation package.

    This is downstream validation orchestration.  It does not feed the search
    loop directly and it does not make FPGA-performance statements unless the
    per-package HLS gate permits feedback use.
    """

    root = Path(out_dir)
    materialized_packages = [
        package for package in materialization.get("packages", []) or []
        if isinstance(package, Mapping)
    ]
    attempts = [
        run_qe_fpga_hls_attempt(
            root / str(package.get("package_dir", "")),
            hls_tool=hls_tool,
            timeout_s=timeout_s,
        )
        for package in materialized_packages
        if str(package.get("package_dir", ""))
    ]
    rows = [_hls_attempt_summary_row(attempt, root) for attempt in attempts]
    status_counts = _count_by_key(rows, "status")
    performance_allowed = sum(1 for row in rows if bool(row.get("performance_feedback_allowed", False)))
    synthesis_allowed = sum(1 for row in rows if bool(row.get("synthesis_evidence_allowed", False)))
    vivado_count = sum(1 for row in rows if row.get("vivado_implementation_gate") == "passed")
    bitstream_count = sum(1 for row in rows if row.get("bitstream_gate") == "passed")
    if rows and performance_allowed == len(rows):
        status = "hls_attempts_feedback_ready"
    elif rows:
        status = "hls_attempts_blocked_or_non_evidence"
    else:
        status = "no_materialized_packages_for_hls_attempt"
    summary = {
        "schema_version": QE_FPGA_HLS_ATTEMPT_SUMMARY_SCHEMA,
        "method_name": QE_FPGA_WAMF_DSE_METHOD_NAME,
        "status": status,
        "attempt_count": len(rows),
        "attempt_status_counts": status_counts,
        "performance_feedback_allowed_count": performance_allowed,
        "synthesis_evidence_allowed_count": synthesis_allowed,
        "vivado_implementation_count": vivado_count,
        "bitstream_count": bitstream_count,
        "hls_tool_request": str(hls_tool or _resolve_hls_tool_request(None)),
        "package_source": {
            "schema_version": str(materialization.get("schema_version", "")),
            "status": str(materialization.get("status", "")),
            "package_count": int(materialization.get("package_count", len(materialized_packages))),
            "claim_boundary": str(materialization.get("claim_boundary", "")),
        },
        "attempts": rows,
        "allowed_feedback_samples": [
            dict(attempt.get("feedback_sample", {}))
            for attempt in attempts
            if isinstance(attempt.get("feedback_sample"), Mapping)
            and attempt.get("evidence_gate_summary", {}).get("performance_feedback_allowed") is True
        ],
        "required_next_tool_steps": [
            "install_or_activate_real_vitis_hls_or_vivado_hls",
            "replace_scaffold_with_qe_kernel_or_workflow_source",
            "attach_qe_golden_vector_manifest",
            "rerun_hls_csim_and_csynth",
            "run_vivado_implementation_and_bitstream_when_platform_constraints_exist",
            "feed_allowed_feedback_samples_back_to_calibration",
        ],
        "claim_boundary": "hls_attempt_summary_downstream_validation_only_not_search_objective",
    }
    _write_json_file(root / "qe_fpga_hls_attempt_summary.json", summary)
    return summary


def run_qe_fpga_vivado_attempt(
    package_root: str | Path,
    *,
    vivado_tool: str | None = None,
    timeout_s: int = 900,
) -> Dict[str, Any]:
    """Attempt Vivado synthesis/packaging for one materialized QE FPGA package."""

    root = Path(package_root)
    manifest_path = root / "candidate_manifest.json"
    manifest = _load_json_object(manifest_path)
    candidate_id = str(manifest.get("candidate_id", ""))
    design_key = str(manifest.get("design_key", ""))
    requested_tool = _resolve_vivado_tool_request(vivado_tool)
    tool_path = _resolve_executable(requested_tool)
    rtl_dir = root / "qe_workflow_accel_hls" / "solution1" / "impl" / "verilog"
    rtl_available = rtl_dir.exists() and any(rtl_dir.glob("*.v"))
    tool_classification = _classify_vivado_tool_evidence(tool_path)
    blockers: List[str] = []
    if tool_path is None:
        blockers.append("vivado_tool_unavailable")
    else:
        blockers.extend(str(item) for item in tool_classification.get("blockers", []) or [])
    if not rtl_available:
        blockers.append("hls_synthesized_rtl_missing")
    commands: List[Dict[str, Any]] = []
    if tool_path is None:
        status = "blocked_vivado_tool_unavailable"
    elif not rtl_available:
        status = "blocked_hls_rtl_missing"
    elif not bool(tool_classification.get("allowed_implementation_use", False)):
        status = "vivado_attempt_non_evidence"
    else:
        command = [tool_path, "-mode", "batch", "-source", "scripts/run_vivado_packaging.tcl"]
        command_result = _run_process(command, cwd=root, timeout_s=max(1, int(timeout_s)))
        command_result["tool"] = tool_path
        commands.append(command_result)
        if command_result.get("returncode") == 0:
            status = "vivado_attempt_passed"
        else:
            status = "vivado_attempt_failed"
            blockers.append("vivado_tool_returned_nonzero")
    attempt = _vivado_attempt_payload(
        root=root,
        manifest_path=manifest_path,
        candidate_id=candidate_id,
        design_key=design_key,
        status=status,
        commands=commands,
        blockers=blockers,
        requested_tool=requested_tool,
        resolved_tool=tool_path,
        rtl_available=rtl_available,
        tool_evidence_classification=tool_classification,
    )
    _write_json_file(root / "vivado_attempt.json", attempt)
    return attempt


def run_qe_fpga_vivado_attempts_for_materialized_packages(
    materialization: Mapping[str, Any],
    out_dir: str | Path,
    *,
    vivado_tool: str | None = None,
    timeout_s: int = 900,
) -> Dict[str, Any]:
    """Run or record Vivado implementation attempts for materialized packages."""

    root = Path(out_dir)
    materialized_packages = [
        package for package in materialization.get("packages", []) or []
        if isinstance(package, Mapping)
    ]
    attempts = [
        run_qe_fpga_vivado_attempt(
            root / str(package.get("package_dir", "")),
            vivado_tool=vivado_tool,
            timeout_s=timeout_s,
        )
        for package in materialized_packages
        if str(package.get("package_dir", ""))
    ]
    rows = [_vivado_attempt_summary_row(attempt, root) for attempt in attempts]
    status_counts = _count_by_key(rows, "status")
    implementation_allowed = sum(1 for row in rows if bool(row.get("implementation_evidence_allowed", False)))
    bitstream_allowed = sum(1 for row in rows if bool(row.get("bitstream_evidence_allowed", False)))
    vivado_count = sum(1 for row in rows if row.get("vivado_implementation_gate") == "passed")
    bitstream_count = sum(1 for row in rows if row.get("bitstream_gate") == "passed")
    if rows and implementation_allowed == len(rows):
        status = "vivado_attempts_implementation_evidence_ready"
    elif rows:
        status = "vivado_attempts_blocked_or_non_evidence"
    else:
        status = "no_materialized_packages_for_vivado_attempt"
    summary = {
        "schema_version": QE_FPGA_VIVADO_ATTEMPT_SUMMARY_SCHEMA,
        "method_name": QE_FPGA_WAMF_DSE_METHOD_NAME,
        "status": status,
        "attempt_count": len(rows),
        "attempt_status_counts": status_counts,
        "implementation_evidence_allowed_count": implementation_allowed,
        "bitstream_evidence_allowed_count": bitstream_allowed,
        "vivado_implementation_count": vivado_count,
        "bitstream_count": bitstream_count,
        "vivado_tool_request": str(vivado_tool or _resolve_vivado_tool_request(None)),
        "package_source": {
            "schema_version": str(materialization.get("schema_version", "")),
            "status": str(materialization.get("status", "")),
            "package_count": int(materialization.get("package_count", len(materialized_packages))),
            "claim_boundary": str(materialization.get("claim_boundary", "")),
        },
        "attempts": rows,
        "required_next_tool_steps": [
            "install_or_activate_real_vivado",
            "complete_hls_csynth_to_materialize_rtl",
            "add_real_fpga_part_constraints_and_timing_constraints",
            "rerun_vivado_synthesis_implementation_and_bitstream",
            "feed_allowed_implementation_reports_back_to_calibration",
        ],
        "claim_boundary": "vivado_attempt_summary_downstream_validation_only_not_search_objective",
    }
    _write_json_file(root / "qe_fpga_vivado_attempt_summary.json", summary)
    return summary


def _extract_workload_features(
    manifest: Mapping[str, Any],
    *,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    manifest_features = _extract_workload_features_from_manifest(manifest)
    if not isinstance(workflow_abstraction, Mapping):
        manifest_features["feature_source"] = "qe_mainflow_manifest"
        manifest_features["feature_source_priority"] = ["qe_mainflow_manifest"]
        return manifest_features
    if not _workflow_feature_contract_is_valid(workflow_abstraction):
        if require_workflow_feature_contract:
            raise ValueError("workflow_feature_contract is required for workflow_abstraction but missing or invalid")
        manifest_features["feature_source"] = "qe_mainflow_manifest"
        manifest_features["feature_source_priority"] = [
            "qe_workflow_fpga_abstraction_rejected",
            "qe_mainflow_manifest",
        ]
        return manifest_features
    abstraction_features = _extract_workload_features_from_abstraction(workflow_abstraction)
    if not abstraction_features:
        if require_workflow_feature_contract:
            raise ValueError("workflow_feature_contract is required for workflow_abstraction but missing or invalid")
        manifest_features["feature_source"] = "qe_mainflow_manifest"
        manifest_features["feature_source_priority"] = [
            "qe_workflow_fpga_abstraction_rejected",
            "qe_mainflow_manifest",
        ]
        return manifest_features
    merged = dict(manifest_features)
    merged.update(abstraction_features)
    graph_summary = (
        workflow_abstraction.get("graph_summary", {})
        if isinstance(workflow_abstraction.get("graph_summary"), Mapping)
        else {}
    )
    merged.update(_graph_summary_features(graph_summary))
    merged["manifest_fallback_features"] = manifest_features
    merged["feature_source"] = "qe_workflow_fpga_abstraction"
    merged["feature_source_priority"] = [
        "qe_workflow_fpga_abstraction",
        "qe_mainflow_manifest_fallback",
    ]
    return merged


def _workflow_feature_contract_is_valid(workflow_abstraction: Mapping[str, Any]) -> bool:
    contract = workflow_abstraction.get("workflow_feature_contract", {})
    if not isinstance(contract, Mapping):
        return False
    if contract.get("schema_version") != "dse.workflow_feature_contract.v1":
        return False
    if contract.get("domain_neutral") is not True:
        return False
    if contract.get("source_adapter") != "qe_workflow_fpga_abstraction":
        return False
    if contract.get("claim_boundary") != "workflow_features_only_not_evidence_not_candidate_identity":
        return False
    return True


def _extract_workload_features_from_manifest(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    cases = [case for case in manifest.get("cases", []) or [] if isinstance(case, Mapping)]
    workflow_classes = sorted({_stage_class(str(case.get("stage_type", ""))) for case in cases})
    stage_types = sorted({str(case.get("stage_type", "")) for case in cases})
    kernel_weights: Dict[str, float] = {}
    physical_quantities: List[str] = []
    artifact_paths: Dict[str, int] = {}
    dependency_edge_count = 0
    stage_count = 0
    variant_data_scale = 1.0
    variant_parameters = manifest.get("variant_parameters", {}) if isinstance(manifest.get("variant_parameters"), Mapping) else {}
    manifest_data_scale = _finite_float(variant_parameters.get("data_scale"), default=1.0)
    dominant_phase = str(variant_parameters.get("dominant_phase", "balanced"))

    for case in cases:
        variant_data_scale = max(variant_data_scale, _finite_float(case.get("variant_data_scale"), default=manifest_data_scale))
        physical_quantities.extend(str(item) for item in case.get("physical_quantities", []) or [])
        for artifact in case.get("input_artifacts", []) or []:
            if not isinstance(artifact, Mapping):
                continue
            path = str(artifact.get("path") or "")
            if path:
                artifact_paths[path] = max(artifact_paths.get(path, 0), 1)

        sequence = [step for step in case.get("baseline_sequence", []) or [] if isinstance(step, Mapping)]
        stage_count += len(sequence) or 1
        dependency_edge_count += max(0, len(sequence) - 1)

        case_profile_found = False
        source = case.get("step1_source", {}) if isinstance(case.get("step1_source"), Mapping) else {}
        for stage in source.get("stages", []) or []:
            if not isinstance(stage, Mapping):
                continue
            profile = stage.get("profile", {})
            if not isinstance(profile, Mapping):
                continue
            phases = profile.get("phases", {})
            if not isinstance(phases, Mapping):
                continue
            for phase_name, raw_weight in phases.items():
                weight = _finite_float(raw_weight, default=0.0)
                if weight <= 0.0:
                    continue
                kernel_weights[str(phase_name)] = kernel_weights.get(str(phase_name), 0.0) + weight
                case_profile_found = True

        for kernel in case.get("kernel_coverage", []) or []:
            kernel_name = str(kernel)
            kernel_weights.setdefault(kernel_name, 0.08 if case_profile_found else 0.20)

    total_profile_seconds = sum(kernel_weights.values())
    stage_repetition = _workflow_stage_repetition_from_cases(cases)
    host_control_events = _workflow_host_control_events_from_cases(cases, stage_repetition)
    correctness_observables = _workflow_correctness_observables_from_cases(cases, physical_quantities)
    data_object_lifetime = _workflow_data_object_lifetime_from_cases(cases, kernel_weights, variant_data_scale)
    data_artifact_count = len(artifact_paths)
    estimated_data_volume_mb = max(
        8.0,
        (
            total_profile_seconds * 96.0
            + float(data_artifact_count) * 4.0
            + float(dependency_edge_count) * 18.0
            + _finite_float(data_object_lifetime.get("estimated_hot_object_bytes"), default=0.0) / 1.0e6
        ) * variant_data_scale,
    )
    host_control_intensity = _host_control_intensity(kernel_weights, workflow_classes, dominant_phase)
    if host_control_events:
        event_pressure = (
            _finite_float(host_control_events.get("scf_convergence_check_count"), default=0.0) * 0.015
            + _finite_float(host_control_events.get("post_processing_stage_count"), default=0.0) * 0.035
            + _finite_float(host_control_events.get("io_checkpoint_event_count"), default=0.0) * 0.012
        )
        host_control_intensity = max(host_control_intensity, min(1.0, event_pressure))
    post_processing_intensity = _post_processing_intensity(kernel_weights, workflow_classes, dominant_phase)
    return {
        "workflow_classes": workflow_classes,
        "stage_types": stage_types,
        "stage_count": stage_count,
        "case_count": len(cases),
        "kernel_weights": dict(sorted(kernel_weights.items())),
        "total_profile_seconds": total_profile_seconds,
        "estimated_baseline_workflow_wall_time_ms": total_profile_seconds * 1000.0 + stage_count * 12.0,
        "estimated_workflow_data_volume_mb": estimated_data_volume_mb,
        "estimated_wavefunction_mb": 0.0,
        "estimated_charge_density_mb": 0.0,
        "max_nbnd": 0,
        "max_npw": 0,
        "max_nfft": 0,
        "max_kpoint_count": 0,
        "scf_iteration_count_observed": 0,
        "graph_node_count": stage_count,
        "graph_edge_count": dependency_edge_count,
        "source_fact_count": 0,
        "workflow_dependency_edge_count": dependency_edge_count,
        "data_artifact_count": data_artifact_count,
        "physical_quantities": sorted(set(physical_quantities)),
        "variant_data_scale": variant_data_scale,
        "dominant_phase": dominant_phase,
        "host_control_intensity": host_control_intensity,
        "post_processing_intensity": post_processing_intensity,
        "stage_repetition": stage_repetition,
        "host_control_event_counts": host_control_events,
        "correctness_observables": correctness_observables,
        "data_object_lifetime": data_object_lifetime,
    }


def _extract_workload_features_from_abstraction(abstraction: Mapping[str, Any]) -> Dict[str, Any]:
    if abstraction.get("schema_version") != "dse.qe_workflow_fpga_abstraction.v1":
        return {}
    raw_features = abstraction.get("features", {})
    if not isinstance(raw_features, Mapping):
        return {}
    graph = abstraction.get("graph", {}) if isinstance(abstraction.get("graph"), Mapping) else {}
    source = abstraction.get("source", {}) if isinstance(abstraction.get("source"), Mapping) else {}
    data_objects = abstraction.get("data_objects", {}) if isinstance(abstraction.get("data_objects"), Mapping) else {}
    kernel_weights = {
        str(key): _finite_float(value, default=0.0)
        for key, value in (raw_features.get("kernel_weights", {}) if isinstance(raw_features.get("kernel_weights"), Mapping) else {}).items()
        if _finite_float(value, default=0.0) > 0.0
    }
    workflow_classes = [str(item) for item in raw_features.get("workflow_classes", []) or []]
    stage_count = int(_finite_float(raw_features.get("stage_count"), default=_finite_float(source.get("stage_count"), default=0.0)))
    graph_edges = [edge for edge in graph.get("edges", []) or [] if isinstance(edge, Mapping)]
    data_artifact_count = sum(
        1
        for item in data_objects.values()
        if isinstance(item, Mapping) and _finite_float(item.get("bytes"), default=0.0) > 0.0
    )
    data_volume_mb = _finite_float(raw_features.get("estimated_total_data_movement_bytes"), default=0.0) / 1.0e6
    if data_volume_mb <= 0.0:
        data_volume_mb = sum(
            _finite_float(item.get("bytes"), default=0.0)
            for item in data_objects.values()
            if isinstance(item, Mapping)
        ) / 1.0e6
    data_object_lifetime = _data_object_lifetime_from_abstraction(data_objects, graph_edges)
    total_profile_seconds = _finite_float(raw_features.get("observed_total_phase_wall_seconds"), default=sum(kernel_weights.values()))
    if total_profile_seconds <= 0.0:
        total_profile_seconds = sum(kernel_weights.values())
    max_dimensions = raw_features.get("max_dimensions", {}) if isinstance(raw_features.get("max_dimensions"), Mapping) else {}
    estimated_wavefunction_mb = _finite_float(raw_features.get("estimated_wavefunction_bytes"), default=0.0) / 1.0e6
    estimated_charge_density_mb = _finite_float(raw_features.get("estimated_charge_density_bytes"), default=0.0) / 1.0e6
    graph_node_count = int(_finite_float(graph.get("node_count"), default=0.0))
    graph_edge_count = int(_finite_float(graph.get("edge_count"), default=float(len(graph_edges))))
    source_fact_count = len(abstraction.get("source_facts", []) or [])
    raw_workflow_feature_contract = (
        abstraction.get("workflow_feature_contract", {})
        if isinstance(abstraction.get("workflow_feature_contract"), Mapping)
        else {}
    )
    workflow_feature_contract = _workflow_feature_contract_summary(raw_workflow_feature_contract)
    host_control_events = _host_control_events_from_abstraction(raw_features)
    correctness_observables = _correctness_observables_from_abstraction(raw_features)
    host_control_intensity = _finite_float(raw_features.get("host_control_intensity"), default=0.0)
    post_processing_intensity = _post_processing_intensity(kernel_weights, workflow_classes, str(raw_features.get("dominant_phase", "balanced")))
    return {
        "workflow_id": str(abstraction.get("workload_id", "")),
        "workflow_classes": sorted(set(workflow_classes)),
        "stage_types": sorted(set(str(row.get("stage_type", "")) for row in graph.get("nodes", []) or [] if isinstance(row, Mapping) and row.get("stage_type"))),
        "stage_count": max(1, stage_count),
        "case_count": max(1, stage_count),
        "kernel_weights": dict(sorted(kernel_weights.items())),
        "total_profile_seconds": total_profile_seconds,
        "estimated_baseline_workflow_wall_time_ms": total_profile_seconds * 1000.0 + max(1, stage_count) * 12.0,
        "estimated_workflow_data_volume_mb": max(8.0, data_volume_mb),
        "estimated_wavefunction_mb": estimated_wavefunction_mb,
        "estimated_charge_density_mb": estimated_charge_density_mb,
        "max_nbnd": int(_finite_float(max_dimensions.get("nbnd"), default=0.0)),
        "max_npw": int(_finite_float(max_dimensions.get("npw"), default=0.0)),
        "max_nfft": int(_finite_float(max_dimensions.get("nfft"), default=0.0)),
        "max_kpoint_count": int(_finite_float(max_dimensions.get("kpoint_count"), default=0.0)),
        "scf_iteration_count_observed": int(_finite_float(raw_features.get("scf_iteration_count_observed"), default=0.0)),
        "graph_node_count": graph_node_count,
        "graph_edge_count": graph_edge_count,
        "source_fact_count": source_fact_count,
        "workflow_dependency_edge_count": graph_edge_count,
        "data_artifact_count": data_artifact_count,
        "physical_quantities": list(correctness_observables.get("workflow", []) or []),
        "variant_data_scale": max(1.0, _finite_float(raw_features.get("data_movement_intensity"), default=1.0)),
        "dominant_phase": str(raw_features.get("dominant_phase", "workflow_abstraction")),
        "host_control_intensity": max(0.0, min(1.0, host_control_intensity)),
        "post_processing_intensity": post_processing_intensity,
        "stage_repetition": dict(raw_features.get("stage_repetition", {}) if isinstance(raw_features.get("stage_repetition"), Mapping) else {}),
        "host_control_event_counts": host_control_events,
        "correctness_observables": correctness_observables,
        "data_object_lifetime": data_object_lifetime,
        "workflow_feature_contract": workflow_feature_contract,
        "workflow_feature_contract_detail": copy.deepcopy(dict(raw_workflow_feature_contract)),
        "abstraction_source": {
            "schema_version": str(abstraction.get("schema_version", "")),
            "workload_id": str(abstraction.get("workload_id", "")),
            "observed_runtime": bool(source.get("observed_runtime", False)),
            "graph_node_count": graph_node_count,
            "graph_edge_count": graph_edge_count,
            "source_fact_count": source_fact_count,
            "claim_boundary": str(abstraction.get("claim_boundary", "")),
        },
    }


def _workflow_feature_contract_summary(contract: Any) -> Dict[str, Any]:
    if not isinstance(contract, Mapping):
        return {
            "schema_version": "",
            "domain_neutral": False,
            "stage_count": 0,
            "data_object_count": 0,
            "compute_feature_count": 0,
            "claim_boundary": "",
        }
    workflow_dag = contract.get("workflow_dag", {}) if isinstance(contract.get("workflow_dag"), Mapping) else {}
    stage_features = contract.get("stage_feature_table", []) if isinstance(contract.get("stage_feature_table"), list) else []
    data_objects = contract.get("data_object_table", []) if isinstance(contract.get("data_object_table"), list) else []
    compute_features = contract.get("compute_feature_table", []) if isinstance(contract.get("compute_feature_table"), list) else []
    correctness = contract.get("correctness_observable_table", {}) if isinstance(contract.get("correctness_observable_table"), Mapping) else {}
    search_objectives = contract.get("search_objectives", []) if isinstance(contract.get("search_objectives"), list) else []
    host_barriers = sum(
        1
        for row in stage_features
        if isinstance(row, Mapping) and row.get("host_control_barrier") is True
    )
    return {
        "schema_version": str(contract.get("schema_version", "")),
        "domain_neutral": bool(contract.get("domain_neutral", False)),
        "source_adapter": str(contract.get("source_adapter", "")),
        "workload_family": str(contract.get("workload_family", "")),
        "workflow_id": str(contract.get("workflow_id", "")),
        "stage_count": int(_finite_float(workflow_dag.get("stage_count"), default=float(len(stage_features)))),
        "stage_feature_count": len([row for row in stage_features if isinstance(row, Mapping)]),
        "host_control_barrier_stage_count": host_barriers,
        "data_object_count": len([row for row in data_objects if isinstance(row, Mapping)]),
        "compute_feature_count": len([row for row in compute_features if isinstance(row, Mapping)]),
        "correctness_observable_count": len(correctness.get("workflow", []) if isinstance(correctness.get("workflow"), list) else []),
        "search_objectives": [str(item) for item in search_objectives],
        "model_update_policy": dict(contract.get("model_update_policy", {}) if isinstance(contract.get("model_update_policy"), Mapping) else {}),
        "claim_boundary": str(contract.get("claim_boundary", "")),
    }


def _workload_feature_contract_binding(features: Mapping[str, Any]) -> Dict[str, Any]:
    contract = features.get("workflow_feature_contract", {})
    if isinstance(contract, Mapping) and contract.get("schema_version"):
        return dict(contract)
    return {
        "schema_version": "",
        "domain_neutral": False,
        "workflow_id": "",
        "stage_count": 0,
        "data_object_count": 0,
        "compute_feature_count": 0,
        "claim_boundary": "",
    }


def _graph_summary_features(graph_summary: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(graph_summary, Mapping):
        return {}
    return {
        "graph_node_count": int(_finite_float(graph_summary.get("node_count"), default=0.0)),
        "graph_edge_count": int(_finite_float(graph_summary.get("edge_count"), default=0.0)),
        "graph_host_node_count": int(_finite_float(graph_summary.get("host_node_count"), default=0.0)),
        "graph_accelerator_node_count": int(_finite_float(graph_summary.get("accelerator_node_count"), default=0.0)),
        "graph_host_node_ratio": _finite_float(graph_summary.get("host_node_ratio"), default=0.0),
        "graph_accelerator_node_ratio": _finite_float(graph_summary.get("accelerator_node_ratio"), default=0.0),
        "graph_control_edge_count": int(_finite_float(graph_summary.get("control_edge_count"), default=0.0)),
        "graph_data_edge_count": int(_finite_float(graph_summary.get("data_edge_count"), default=0.0)),
        "graph_state_edge_count": int(_finite_float(graph_summary.get("state_edge_count"), default=0.0)),
        "graph_inter_stage_edge_count": int(_finite_float(graph_summary.get("inter_stage_edge_count"), default=0.0)),
        "graph_inter_stage_edge_ratio": _finite_float(graph_summary.get("inter_stage_edge_ratio"), default=0.0),
        "graph_max_in_degree": int(_finite_float(graph_summary.get("max_in_degree"), default=0.0)),
        "graph_max_out_degree": int(_finite_float(graph_summary.get("max_out_degree"), default=0.0)),
        "graph_mean_in_degree": _finite_float(graph_summary.get("mean_in_degree"), default=0.0),
        "graph_mean_out_degree": _finite_float(graph_summary.get("mean_out_degree"), default=0.0),
        "graph_density": _finite_float(graph_summary.get("graph_density"), default=0.0),
        "graph_edge_kind_counts": dict(graph_summary.get("edge_kind_counts", {}) if isinstance(graph_summary.get("edge_kind_counts"), Mapping) else {}),
        "graph_placement_hint_counts": dict(graph_summary.get("placement_hint_counts", {}) if isinstance(graph_summary.get("placement_hint_counts"), Mapping) else {}),
        "graph_op_type_counts": dict(graph_summary.get("op_type_counts", {}) if isinstance(graph_summary.get("op_type_counts"), Mapping) else {}),
    }


def _host_control_events_from_abstraction(raw_features: Mapping[str, Any]) -> Dict[str, Any]:
    events = raw_features.get("host_control_events")
    if isinstance(events, Mapping):
        return copy.deepcopy(dict(events))
    return copy.deepcopy(dict(raw_features.get("host_control_event_counts", {}) if isinstance(raw_features.get("host_control_event_counts"), Mapping) else {}))


def _correctness_observables_from_abstraction(raw_features: Mapping[str, Any]) -> Dict[str, Any]:
    correctness = raw_features.get("correctness_observables")
    if isinstance(correctness, Mapping):
        return copy.deepcopy(dict(correctness))
    return {"workflow": [], "per_stage": {}, "observed_values": {}}


def _data_object_lifetime_from_abstraction(
    data_objects: Mapping[str, Any],
    graph_edges: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    object_rows = {
        str(name): row
        for name, row in data_objects.items()
        if isinstance(row, Mapping)
    }
    hot_objects = {
        name
        for name, row in object_rows.items()
        if "hbm" in str(row.get("preferred_residency_hint", "")).lower()
        or "reuse" in str(row.get("lifetime", "")).lower()
        or name in {"psi", "rho", "v_of_rho"}
    }
    checkpoint_objects = {
        name
        for name, row in object_rows.items()
        if "checkpoint" in str(row.get("lifetime", "")).lower()
        or "filesystem" in str(row.get("preferred_residency_hint", "")).lower()
        or name in {"rho", "qe_save_dir", "eigenvalues"}
    }
    hot_bytes = sum(
        _finite_float(object_rows[name].get("bytes"), default=0.0)
        for name in hot_objects
        if name in object_rows
    )
    lifetime_edges = sum(
        1
        for edge in graph_edges
        if str(edge.get("edge_kind", "")) in {"data_object_lifetime", "stage_artifact_dependency"}
    )
    return {
        "object_ids": sorted(object_rows),
        "hot_reuse_object_count": len(hot_objects),
        "checkpoint_object_count": len(checkpoint_objects),
        "cross_stage_lifetime_count": lifetime_edges,
        "estimated_hot_object_bytes": hot_bytes,
        "preferred_residency_hint": "from_qe_workflow_fpga_abstraction_data_objects",
    }


def _implementation_package_sort_key(
    request: Mapping[str, Any],
    result_by_candidate: Mapping[str, Mapping[str, Any]],
) -> Tuple[float, float, str]:
    candidate_id = str(request.get("candidate_id", ""))
    result = result_by_candidate.get(candidate_id, {})
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), Mapping) else {}
    return (
        _finite_float(metrics.get("tlm_edp"), default=float("inf")),
        _finite_float(metrics.get("tlm_resource_pressure"), default=float("inf")),
        candidate_id,
    )


def _workflow_stage_repetition_from_cases(cases: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    repetitions: Dict[str, Dict[str, Any]] = {}
    for case in cases:
        case_id = str(case.get("case_id", f"case_{len(repetitions):03d}"))
        sequence = [step for step in case.get("baseline_sequence", []) or [] if isinstance(step, Mapping)]
        if not sequence:
            sequence = [{"step_id": case_id, "stage_type": str(case.get("stage_type", "stage"))}]
        for step in sequence:
            stage_id = str(step.get("step_id") or step.get("stage_id") or case_id)
            stage_type = str(step.get("stage_type") or case.get("stage_type") or "stage")
            stage_class = _stage_class(stage_type)
            if stage_class in {"scf", "relax"} or stage_type in {"vc_relax"}:
                repetition_kind = "scf_iteration_loop"
                observed_iterations = _case_observed_iteration_count(case)
            elif stage_class == "post_processing":
                repetition_kind = "single_post_processing_pass"
                observed_iterations = 1
            else:
                repetition_kind = "single_stage"
                observed_iterations = 1
            repetitions[stage_id] = {
                "stage_type": stage_type,
                "workflow_class": stage_class,
                "repetition_kind": repetition_kind,
                "observed_iterations": max(1, int(observed_iterations)),
            }
    return repetitions


def _workflow_host_control_events_from_cases(
    cases: Sequence[Mapping[str, Any]],
    stage_repetition: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    scf_checks = sum(
        int(row.get("observed_iterations", 1))
        for row in stage_repetition.values()
        if row.get("repetition_kind") == "scf_iteration_loop"
    )
    post_processing_count = sum(
        1
        for row in stage_repetition.values()
        if row.get("workflow_class") == "post_processing"
    )
    io_checkpoint_count = max(0, len(stage_repetition) - 1) + post_processing_count
    retained_counts: Dict[str, int] = {}
    for case in cases:
        for kernel in case.get("kernel_coverage", []) or []:
            kernel_id = str(kernel)
            normalized = "v_of_rho" if kernel_id == "veff" else kernel_id
            if normalized in _HOST_RETAINED_KERNELS:
                retained_counts[normalized] = retained_counts.get(normalized, 0) + 1
    return {
        "scf_convergence_check_count": scf_checks,
        "post_processing_stage_count": post_processing_count,
        "io_checkpoint_event_count": io_checkpoint_count,
        "retained_kernel_counts": dict(sorted(retained_counts.items())),
    }


def _workflow_correctness_observables_from_cases(
    cases: Sequence[Mapping[str, Any]],
    physical_quantities: Sequence[str],
) -> Dict[str, Any]:
    workflow = sorted({
        _normalize_correctness_observable(quantity)
        for quantity in physical_quantities
        if _normalize_correctness_observable(quantity)
    })
    per_case: Dict[str, List[str]] = {}
    for case in cases:
        observables = sorted({
            _normalize_correctness_observable(quantity)
            for quantity in case.get("physical_quantities", []) or []
            if _normalize_correctness_observable(quantity)
        })
        expected = case.get("expected_outputs", {}) if isinstance(case.get("expected_outputs"), Mapping) else {}
        observables.extend(
            _normalize_correctness_observable(str(key))
            for key in expected
            if _normalize_correctness_observable(str(key))
        )
        per_case[str(case.get("case_id", ""))] = sorted(set(observables))
    return {
        "workflow": workflow,
        "per_case": per_case,
        "count": len(workflow),
    }


def _workflow_data_object_lifetime_from_cases(
    cases: Sequence[Mapping[str, Any]],
    kernel_weights: Mapping[str, float],
    data_scale: float,
) -> Dict[str, Any]:
    stage_ids: List[str] = []
    for case in cases:
        sequence = [step for step in case.get("baseline_sequence", []) or [] if isinstance(step, Mapping)]
        if not sequence:
            stage_ids.append(str(case.get("case_id", f"case_{len(stage_ids):03d}")))
            continue
        for step in sequence:
            stage_ids.append(str(step.get("step_id") or step.get("stage_id") or case.get("case_id", "")))
    object_ids = {"psi", "rho", "v_of_rho", "eigenvalues", "qe_save_dir"}
    hot_objects = {"psi", "rho", "v_of_rho"}
    checkpoint_objects = {"rho", "qe_save_dir", "eigenvalues"}
    estimated_hot_bytes = max(
        1.0,
        sum(_finite_float(value, default=0.0) for value in kernel_weights.values())
        * 64.0e6
        * max(1.0, _finite_float(data_scale, default=1.0)),
    )
    return {
        "object_ids": sorted(object_ids),
        "hot_reuse_object_count": len(hot_objects),
        "checkpoint_object_count": len(checkpoint_objects),
        "cross_stage_lifetime_count": max(0, len(stage_ids) - 1),
        "estimated_hot_object_bytes": estimated_hot_bytes,
        "preferred_residency_hint": "reuse_hot_objects_with_hbm_or_pinned_host_when_budget_allows",
    }


def _case_observed_iteration_count(case: Mapping[str, Any]) -> int:
    source = case.get("step1_source", {}) if isinstance(case.get("step1_source"), Mapping) else {}
    for stage in source.get("stages", []) or []:
        if not isinstance(stage, Mapping):
            continue
        log = stage.get("log") or stage.get("stdout")
        if not isinstance(log, str):
            continue
        match = re.search(r"convergence has been achieved in\s+(\d+)\s+iterations", log, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        count = len(re.findall(r"\biteration\s*#", log, flags=re.IGNORECASE))
        if count:
            return count
    return 1


def _normalize_correctness_observable(quantity: str) -> str:
    normalized = str(quantity).strip().lower()
    if not normalized:
        return ""
    if "energy" in normalized:
        return "total_energy"
    if "density" in normalized or "residual" in normalized:
        return "charge_density_residual"
    if "eigen" in normalized or "band" in normalized:
        return "eigenvalue_spectrum"
    if "force" in normalized:
        return "forces"
    if "stress" in normalized:
        return "stress"
    return normalized.replace("_ry", "")


def _is_release_candidate(row: Mapping[str, Any]) -> bool:
    parameters = row.get("parameters", {}) if isinstance(row.get("parameters"), Mapping) else {}
    promotion = row.get("promotion", {}) if isinstance(row.get("promotion"), Mapping) else {}
    return (
        parameters.get("release_lane") == "release"
        and parameters.get("precision_policy") == "fp64_strict"
        and promotion.get("release_pareto_eligible") is True
    )


def _qe_fpga_experiment_workload_variants() -> List[Dict[str, Any]]:
    base = default_qe_mainflow_workload_suite()
    return [
        {
            "workload_id": "si_small_mainflow",
            "description": "default Si SCF/NSCF/bands/relax mainflow fixture",
            "variant_knobs": {"profile_scale": 1.0, "data_scale": 1.0, "dominant_phase": "balanced"},
            "manifest": base,
        },
        {
            "workload_id": "hbm_bandwidth_fft_heavy",
            "description": "FFT/transpose and high data volume variant that stresses memory residency",
            "variant_knobs": {"profile_scale": 3.0, "data_scale": 3.5, "dominant_phase": "fft_transpose"},
            "manifest": _variant_manifest(
                base,
                suite_id="qe_hbm_bandwidth_fft_heavy_v1",
                profile_scale=3.0,
                data_scale=3.5,
                phase_multipliers={"fft": 6.0, "transpose": 5.0, "h_psi": 1.4},
                add_kernels=["transpose"],
            ),
        },
        {
            "workload_id": "post_processing_heavy",
            "description": "bands/post-processing dominated workflow variant",
            "variant_knobs": {"profile_scale": 2.2, "data_scale": 2.0, "dominant_phase": "post_processing"},
            "manifest": _variant_manifest(
                base,
                suite_id="qe_post_processing_heavy_v1",
                profile_scale=2.2,
                data_scale=2.0,
                phase_multipliers={"band_path_projection": 7.0, "diagonalization": 2.8, "h_psi": 1.1},
                stage_multipliers={"bands": 3.0, "nscf": 1.8},
                add_kernels=["projector", "reduction"],
            ),
        },
        {
            "workload_id": "relax_control_heavy",
            "description": "relax/force/stress heavy workflow with higher host-control pressure",
            "variant_knobs": {"profile_scale": 2.6, "data_scale": 1.6, "dominant_phase": "relax_control"},
            "manifest": _variant_manifest(
                base,
                suite_id="qe_relax_control_heavy_v1",
                profile_scale=2.6,
                data_scale=1.6,
                phase_multipliers={"forces": 7.0, "mix_rho": 3.0, "veff": 2.4, "h_psi": 1.5},
                stage_multipliers={"relax": 4.0, "scf": 1.5},
                add_kernels=["forces", "stress", "mix_rho"],
            ),
        },
    ]


def _variant_manifest(
    manifest: Mapping[str, Any],
    *,
    suite_id: str,
    profile_scale: float,
    data_scale: float,
    phase_multipliers: Mapping[str, float],
    stage_multipliers: Mapping[str, float] | None = None,
    add_kernels: Sequence[str] = (),
) -> Dict[str, Any]:
    variant = copy.deepcopy(dict(manifest))
    variant["suite_id"] = suite_id
    variant["variant_role"] = "qe_fpga_multi_workload_experiment_fixture"
    variant["variant_parameters"] = {
        "profile_scale": profile_scale,
        "data_scale": data_scale,
        "phase_multipliers": dict(phase_multipliers),
        "stage_multipliers": dict(stage_multipliers or {}),
        "added_kernels": list(add_kernels),
    }
    for case in variant.get("cases", []) or []:
        if not isinstance(case, dict):
            continue
        stage_type = str(case.get("stage_type", ""))
        stage_scale = _finite_float((stage_multipliers or {}).get(stage_type), default=1.0)
        source = case.get("step1_source", {}) if isinstance(case.get("step1_source"), dict) else {}
        for stage in source.get("stages", []) or []:
            if not isinstance(stage, dict):
                continue
            profile = stage.get("profile", {}) if isinstance(stage.get("profile"), dict) else {}
            phases = profile.get("phases", {}) if isinstance(profile.get("phases"), dict) else {}
            for phase_name, value in list(phases.items()):
                multiplier = _finite_float(phase_multipliers.get(str(phase_name)), default=1.0)
                phases[phase_name] = _round_metric(_finite_float(value, default=0.0) * profile_scale * stage_scale * multiplier)
        kernels = list(case.get("kernel_coverage", []) or [])
        for kernel in add_kernels:
            if kernel not in kernels:
                kernels.append(kernel)
        case["kernel_coverage"] = kernels
        case["variant_data_scale"] = data_scale
    variant.pop("suite_hash", None)
    return variant


def _multi_workload_aggregate(workload_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    method_policy_id = "wamf_generic_active_pareto"
    win_counts: Dict[str, int] = {}
    method_ranks: List[float] = []
    for row in workload_rows:
        method_policy_id = str(row.get("method_policy_id", method_policy_id)) or method_policy_id
        best = row.get("best_policy_by_l2_edp", {}) if isinstance(row.get("best_policy_by_l2_edp"), Mapping) else {}
        policy_id = str(best.get("policy_id", ""))
        if policy_id:
            win_counts[policy_id] = win_counts.get(policy_id, 0) + 1
        for policy in row.get("policy_results", []) or []:
            if not isinstance(policy, Mapping) or policy.get("policy_id") != method_policy_id:
                continue
            rank = _policy_oracle_rank(policy)
            if rank > 0.0:
                method_ranks.append(float(rank))
    return {
        "workload_count": len(workload_rows),
        "method_policy_id": method_policy_id,
        "policy_win_counts": dict(sorted(win_counts.items())),
        "single_policy_sweeps_all_workloads": len(win_counts) == 1 and len(workload_rows) > 1,
        "method_best_rank_mean": _round_metric(_mean(method_ranks)),
        "method_best_rank_max": _round_metric(max(method_ranks) if method_ranks else 0.0),
        "search_quality_summary": _multi_workload_search_quality_summary(
            workload_rows,
            method_policy_id=method_policy_id,
            win_counts=win_counts,
        ),
    }


def _multi_workload_search_quality_summary(
    workload_rows: Sequence[Mapping[str, Any]],
    *,
    method_policy_id: str,
    win_counts: Mapping[str, int],
) -> Dict[str, Any]:
    policy_ids = sorted({
        str(policy.get("policy_id", ""))
        for row in workload_rows
        for policy in row.get("policy_results", []) or []
        if isinstance(policy, Mapping) and policy.get("policy_id")
    })
    policy_rows = [
        _multi_workload_policy_quality_row(policy_id, workload_rows, win_counts)
        for policy_id in policy_ids
    ]
    policy_rows.sort(key=lambda row: (
        _finite_float(row.get("final_simple_regret_mean"), default=float("inf")),
        _finite_float(row.get("final_oracle_rank_mean"), default=float("inf")),
        str(row.get("policy_id", "")),
    ))
    best = dict(policy_rows[0]) if policy_rows else {}
    method_row = next(
        (dict(row) for row in policy_rows if row.get("policy_id") == method_policy_id),
        {},
    )
    regret_gap = max(
        0.0,
        _finite_float(method_row.get("final_simple_regret_mean"), default=0.0)
        - _finite_float(best.get("final_simple_regret_mean"), default=0.0),
    ) if method_row and best else 0.0
    return {
        "schema_version": "dse.qe_fpga.multi_workload_search_quality_summary.v1",
        "evaluation_protocol": "equal_budget_multi_workload_l2_tlm_oracle",
        "workload_count": len(workload_rows),
        "method_policy_id": str(method_policy_id),
        "budget": _multi_workload_common_budget(workload_rows),
        "policy_rows": policy_rows,
        "best_by_mean_regret": {
            "policy_id": str(best.get("policy_id", "")),
            "final_simple_regret_mean": best.get("final_simple_regret_mean"),
            "final_oracle_rank_mean": best.get("final_oracle_rank_mean"),
        },
        "method_row": method_row,
        "method_vs_best": {
            "best_policy_id": str(best.get("policy_id", "")),
            "regret_gap": _round_metric(regret_gap),
            "method_is_best_by_mean_regret": bool(method_row and best and method_row.get("policy_id") == best.get("policy_id")),
        },
        "oracle_alignment_diagnostics": _multi_workload_oracle_alignment_diagnostics(workload_rows),
        "limitations": [
            "L2_python_tlm_oracle_is_model_level_not_hardware_measurement",
            "no_workflow_ablation_may_be_aligned_with_the_L2_python_oracle_cost_model",
            "single_deterministic_seed_per_policy_except_seeded_random_baseline",
            "requires_real_QE_and_HLS_feedback_before_DAC_strength_result",
        ],
    }


def _multi_workload_oracle_alignment_diagnostics(
    workload_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    policy_ids = ["no_workflow_abstraction_ablation"]
    diagnostics: Dict[str, Dict[str, Any]] = {}
    for policy_id in policy_ids:
        score_values: List[float] = []
        oracle_values: List[float] = []
        workload_count = 0
        for workload in workload_rows:
            policy = next(
                (
                    row for row in workload.get("policy_results", []) or []
                    if isinstance(row, Mapping) and str(row.get("policy_id", "")) == policy_id
                ),
                {},
            )
            if not policy:
                continue
            result_rows = [
                row for row in policy.get("result_summaries", []) or []
                if isinstance(row, Mapping)
            ]
            if not result_rows:
                continue
            workload_count += 1
            row_by_id = {
                str(row.get("candidate_id", "")): row
                for row in policy.get("selected_rows", []) or []
                if isinstance(row, Mapping)
            }
            for summary in result_rows:
                candidate_id = str(summary.get("candidate_id", ""))
                candidate_row = row_by_id.get(candidate_id)
                oracle_edp = _finite_float(summary.get("tlm_edp"), default=float("inf"))
                if candidate_row is None or not math.isfinite(oracle_edp) or oracle_edp <= 0.0:
                    continue
                score_values.append(_no_workflow_candidate_score(candidate_row))
                oracle_values.append(oracle_edp)
        if len(score_values) < 3:
            diagnostics[policy_id] = {
                "status": "insufficient_samples",
                "sample_count": len(score_values),
                "workload_count": workload_count,
                "selection_score_source": "_no_workflow_candidate_score",
                "spearman_score_vs_l2_edp": None,
                "oracle_alignment_interpretation": "insufficient_samples",
            }
            continue
        spearman = _spearman(score_values, oracle_values)
        interpretation = (
            "model_alignment_artifact"
            if spearman >= 0.65
            else "weak_or_mixed_alignment"
        )
        diagnostics[policy_id] = {
            "status": "evaluated",
            "sample_count": len(score_values),
            "workload_count": workload_count,
            "selection_score_source": "_no_workflow_candidate_score",
            "spearman_score_vs_l2_edp": _round_metric(spearman),
            "oracle_alignment_interpretation": interpretation,
            "interpretation_basis": (
                "ablation score is computed from L1 compute/resource terms that are also inputs to the L2 Python TLM oracle"
            ),
        }
    status = (
        "evaluated"
        if any(row.get("status") == "evaluated" for row in diagnostics.values())
        else "insufficient_samples"
    )
    return {
        "schema_version": "dse.qe_fpga.multi_workload_oracle_alignment_diagnostics.v1",
        "status": status,
        "oracle_fidelity": "L2_python_tlm",
        "policy_ids_checked": policy_ids,
        "policy_diagnostics": diagnostics,
        "use_in_paper": "diagnostic_guardrail_not_method_result",
    }


def _multi_workload_policy_quality_row(
    policy_id: str,
    workload_rows: Sequence[Mapping[str, Any]],
    win_counts: Mapping[str, int],
) -> Dict[str, Any]:
    ranks: List[float] = []
    regrets: List[float] = []
    normalized_regrets: List[float] = []
    top_k_hits: List[float] = []
    top_1_hits: List[float] = []
    evals_to_top_5: List[float] = []
    evals_to_top_1: List[float] = []
    selection_counts: List[float] = []
    ranking_spearman: List[float] = []
    workloads_present = 0
    for row in workload_rows:
        policy = _policy_result_by_id(row, policy_id)
        if not policy:
            continue
        workloads_present += 1
        final = _policy_final_budget_point(policy)
        sample_efficiency = policy.get("sample_efficiency", {}) if isinstance(policy.get("sample_efficiency"), Mapping) else {}
        rank = _finite_float(final.get("oracle_rank_of_best"), default=_policy_oracle_rank(policy))
        if rank > 0.0:
            ranks.append(rank)
        regret = _finite_float(final.get("simple_regret"), default=_policy_simple_regret(policy))
        if math.isfinite(regret):
            regrets.append(max(0.0, regret))
        normalized = _finite_float(final.get("normalized_regret"), default=float("nan"))
        if math.isfinite(normalized):
            normalized_regrets.append(max(0.0, normalized))
        if "top_k_hit" in final:
            top_k_hits.append(1.0 if final.get("top_k_hit") else 0.0)
        if "top_1_hit" in final:
            top_1_hits.append(1.0 if final.get("top_1_hit") else 0.0)
        top5 = _finite_float(sample_efficiency.get("evaluations_to_top_5_hit"), default=float("nan"))
        if math.isfinite(top5) and top5 > 0.0:
            evals_to_top_5.append(top5)
        top1 = _finite_float(sample_efficiency.get("evaluations_to_top_1_hit"), default=float("nan"))
        if math.isfinite(top1) and top1 > 0.0:
            evals_to_top_1.append(top1)
        selected_count = _finite_float(policy.get("selected_count"), default=0.0)
        if selected_count > 0.0:
            selection_counts.append(selected_count)
        ranking_quality = policy.get("ranking_quality", {}) if isinstance(policy.get("ranking_quality"), Mapping) else {}
        spearman = _finite_float(ranking_quality.get("spearman_l2_oracle_vs_selection_order"), default=float("nan"))
        if math.isfinite(spearman):
            ranking_spearman.append(spearman)
    return {
        "policy_id": str(policy_id),
        "workload_count": workloads_present,
        "win_count": int(win_counts.get(policy_id, 0)),
        "selection_count_mean": _round_metric(_mean(selection_counts)),
        "final_simple_regret_mean": _round_metric(_mean(regrets)),
        "final_simple_regret_std": _round_metric(_stddev(regrets)),
        "final_normalized_regret_mean": _round_metric(_mean(normalized_regrets)),
        "final_oracle_rank_mean": _round_metric(_mean(ranks)),
        "final_oracle_rank_best": int(min(ranks)) if ranks else None,
        "final_oracle_rank_worst": int(max(ranks)) if ranks else None,
        "top_k_hit_rate": _round_metric(_mean(top_k_hits)),
        "top_1_hit_rate": _round_metric(_mean(top_1_hits)),
        "evaluations_to_top_5_hit_mean": (
            _round_metric(_mean(evals_to_top_5)) if evals_to_top_5 else None
        ),
        "evaluations_to_top_1_hit_mean": (
            _round_metric(_mean(evals_to_top_1)) if evals_to_top_1 else None
        ),
        "selection_order_spearman_mean": (
            _round_metric(_mean(ranking_spearman)) if ranking_spearman else None
        ),
    }


def _policy_final_budget_point(policy: Mapping[str, Any]) -> Dict[str, Any]:
    curve = policy.get("budget_curve", []) if isinstance(policy.get("budget_curve"), list) else []
    if curve and isinstance(curve[-1], Mapping):
        return dict(curve[-1])
    oracle = policy.get("l2_oracle", {}) if isinstance(policy.get("l2_oracle"), Mapping) else {}
    return {
        "oracle_rank_of_best": oracle.get("oracle_rank_of_best_selected"),
        "simple_regret": 0.0 if oracle.get("best_tlm_edp") is not None else float("inf"),
        "top_k_hit": (
            _finite_float(oracle.get("oracle_rank_of_best_selected"), default=float("inf")) <= 5.0
        ),
    }


def _multi_workload_common_budget(workload_rows: Sequence[Mapping[str, Any]]) -> int:
    budgets: List[int] = []
    for row in workload_rows:
        for policy in row.get("policy_results", []) or []:
            if not isinstance(policy, Mapping):
                continue
            final = _policy_final_budget_point(policy)
            budget = int(_finite_float(final.get("budget"), default=0.0))
            if budget > 0:
                budgets.append(budget)
    return min(budgets) if budgets else 0


def _policy_workflow_aware_pareto(
    l1_screening: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    budget: int,
) -> List[Mapping[str, Any]]:
    queue = [
        row for row in l1_screening.get("promotion_queue", []) or []
        if isinstance(row, Mapping)
    ]
    if len(queue) >= budget:
        return queue[:budget]
    seen = {str(row.get("candidate_id", "")) for row in queue}
    additions = [
        row for row in sorted(rows, key=_promotion_sort_key)
        if str(row.get("candidate_id", "")) not in seen
    ]
    return list(queue) + additions[: max(0, budget - len(queue))]


def _policy_seeded_random(
    rows: Sequence[Mapping[str, Any]],
    budget: int,
    *,
    seed: str = "default",
) -> List[Mapping[str, Any]]:
    return sorted(
        rows,
        key=lambda row: _stable_fraction(f"{seed}:{row.get('candidate_id', '')}"),
    )[:budget]


def _policy_manual_hbm(rows: Sequence[Mapping[str, Any]], budget: int) -> List[Mapping[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            0 if _candidate_parameters(row).get("architecture_template") == "fpga_hbm_streaming_dataflow" else 1,
            0 if _candidate_parameters(row).get("memory_topology") == "hbm_multi_channel" else 1,
            0 if _candidate_parameters(row).get("data_residency") == "fpga_hbm_resident_hot_arrays" else 1,
            0 if _candidate_parameters(row).get("runtime_schedule") == "overlap_dma_compute" else 1,
            _finite_float(row.get("metrics", {}).get("estimated_edp") if isinstance(row.get("metrics"), Mapping) else None, default=float("inf")),
            str(row.get("candidate_id", "")),
        ),
    )[:budget]


def _policy_single_fidelity_l1(rows: Sequence[Mapping[str, Any]], budget: int) -> List[Mapping[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            _finite_float(row.get("metrics", {}).get("estimated_edp") if isinstance(row.get("metrics"), Mapping) else None, default=float("inf")),
            _finite_float(row.get("metrics", {}).get("fpga_resource_pressure") if isinstance(row.get("metrics"), Mapping) else None, default=float("inf")),
            str(row.get("candidate_id", "")),
        ),
    )[:budget]


def _policy_nsga2_lite(rows: Sequence[Mapping[str, Any]], budget: int) -> List[Mapping[str, Any]]:
    ranked_rows = [
        (row, _nsga2_objective_vector(row))
        for row in rows
    ]
    remaining = list(ranked_rows)
    selected: List[Mapping[str, Any]] = []
    while remaining and len(selected) < budget:
        front: List[Tuple[Mapping[str, Any], Dict[str, float]]] = []
        for row, vector in remaining:
            dominated = any(
                other is not row and _dominates(other_vector, vector)
                for other, other_vector in remaining
            )
            if not dominated:
                front.append((row, vector))
        if not front:
            break
        front.sort(key=lambda item: (
            -_crowding_distance(item[1], [vector for _, vector in front]),
            _finite_float(item[0].get("metrics", {}).get("estimated_edp") if isinstance(item[0].get("metrics"), Mapping) else None, default=float("inf")),
            str(item[0].get("candidate_id", "")),
        ))
        for row, _vector in front:
            if len(selected) >= budget:
                break
            selected.append(row)
        selected_ids = {id(row) for row in selected}
        remaining = [
            (row, vector)
            for row, vector in remaining
            if id(row) not in selected_ids
        ]
    return selected


def _nsga2_objective_vector(row: Mapping[str, Any]) -> Dict[str, float]:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    return {
        "estimated_workflow_wall_time_ms": _finite_float(metrics.get("estimated_workflow_wall_time_ms"), default=float("inf")),
        "estimated_energy_mj": _finite_float(metrics.get("estimated_energy_mj"), default=float("inf")),
        "fpga_resource_pressure": _finite_float(metrics.get("fpga_resource_pressure"), default=float("inf")),
        "estimated_data_movement_mb": _finite_float(metrics.get("estimated_data_movement_mb"), default=float("inf")),
    }


def _crowding_distance(vector: Mapping[str, float], front_vectors: Sequence[Mapping[str, float]]) -> float:
    if len(front_vectors) <= 2:
        return float("inf")
    distance = 0.0
    for key in vector:
        values = sorted(_finite_float(item.get(key), default=float("inf")) for item in front_vectors)
        value = _finite_float(vector.get(key), default=float("inf"))
        if value == values[0] or value == values[-1]:
            return float("inf")
        span = max(values[-1] - values[0], 1.0e-9)
        lower = max((candidate for candidate in values if candidate < value), default=values[0])
        upper = min((candidate for candidate in values if candidate > value), default=values[-1])
        distance += (upper - lower) / span
    return distance


def _policy_kernel_hotspot_only(rows: Sequence[Mapping[str, Any]], budget: int) -> List[Mapping[str, Any]]:
    def key(row: Mapping[str, Any]) -> Tuple[float, float, str]:
        params = _candidate_parameters(row)
        score = 0.0
        if params.get("offload_boundary") == "kernel_callsite_bundle":
            score -= 3.0
        if params.get("mapping_granularity") == "kernel_callsite":
            score -= 2.0
        if params.get("architecture_template") in {"fpga_fft_transpose_pipeline", "fpga_hybrid_cpu_control_accel_kernels"}:
            score -= 1.0
        metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
        return (
            score,
            _finite_float(metrics.get("estimated_compute_time_ms"), default=float("inf")),
            str(row.get("candidate_id", "")),
        )

    return sorted(rows, key=key)[:budget]


def _policy_no_workflow_abstraction(rows: Sequence[Mapping[str, Any]], budget: int) -> List[Mapping[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            _no_workflow_candidate_score(row),
            str(row.get("candidate_id", "")),
        ),
    )[:budget]


def _no_workflow_candidate_score(row: Mapping[str, Any]) -> float:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    params = _candidate_parameters(row)
    compute = _finite_float(metrics.get("estimated_compute_time_ms"), default=float("inf"))
    resource = _finite_float(metrics.get("fpga_resource_pressure"), default=float("inf"))
    score = compute * (1.0 + max(0.0, resource - 0.90) * 2.0)
    if params.get("offload_boundary") == "workflow_hotspot_bundle":
        score *= 0.86
    if params.get("architecture_template") == "fpga_hbm_streaming_dataflow":
        score *= 0.92
    if params.get("data_residency") == "fpga_hbm_resident_hot_arrays":
        score *= 0.94
    return score


def _best_policy_with_tie_break(
    policy_rows: Sequence[Mapping[str, Any]],
    *,
    workload_features: Mapping[str, Any],
) -> Mapping[str, Any]:
    finite_rows = [
        row for row in policy_rows
        if isinstance(row.get("l2_oracle"), Mapping)
        and math.isfinite(_finite_float(row["l2_oracle"].get("best_tlm_edp"), default=float("inf")))
    ]
    if not finite_rows:
        return policy_rows[0] if policy_rows else {}
    best_edp = min(
        _finite_float(row["l2_oracle"].get("best_tlm_edp"), default=float("inf"))
        for row in finite_rows
        if isinstance(row.get("l2_oracle"), Mapping)
    )
    tied = [
        row for row in finite_rows
        if _same_metric_value(
            _finite_float(row["l2_oracle"].get("best_tlm_edp"), default=float("inf")),
            best_edp,
        )
    ]
    priority = _policy_tie_break_priority(workload_features)
    winner = dict(min(tied, key=lambda row: (priority.get(str(row.get("policy_id", "")), 100), str(row.get("policy_id", "")))))
    winner["tie_break_basis"] = "same_l2_edp_within_tolerance_workload_representative_policy"
    return winner


def _policy_tie_break_priority(workload_features: Mapping[str, Any]) -> Dict[str, int]:
    host = _finite_float(workload_features.get("host_control_intensity"), default=0.0)
    post = _finite_float(workload_features.get("post_processing_intensity"), default=0.0)
    data = _finite_float(workload_features.get("variant_data_scale"), default=1.0)
    if data >= 3.0:
        order = [
            "wamf_generic_active_pareto",
            "single_fidelity_l1_edp",
            "workflow_aware_pareto_funnel",
            "nsga2_lite_multi_objective",
            "random_seeded",
            "no_workflow_abstraction_ablation",
            "manual_hbm_streaming_heuristic",
            "kernel_level_hotspot_only",
        ]
    elif host >= 0.45 or post >= 0.24:
        order = [
            "wamf_generic_active_pareto",
            "workflow_aware_pareto_funnel",
            "nsga2_lite_multi_objective",
            "random_seeded",
            "single_fidelity_l1_edp",
            "no_workflow_abstraction_ablation",
            "manual_hbm_streaming_heuristic",
            "kernel_level_hotspot_only",
        ]
    else:
        order = [
            "wamf_generic_active_pareto",
            "nsga2_lite_multi_objective",
            "workflow_aware_pareto_funnel",
            "single_fidelity_l1_edp",
            "random_seeded",
            "no_workflow_abstraction_ablation",
            "manual_hbm_streaming_heuristic",
            "kernel_level_hotspot_only",
        ]
    return {policy_id: index for index, policy_id in enumerate(order)}


def _build_search_budget_sweep(
    *,
    l1_screening: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    policy_rows: Sequence[Mapping[str, Any]],
    oracle_results: Mapping[str, Mapping[str, Any]],
    oracle_rank: Mapping[str, int],
    evaluation_budget: int,
    wamf_closed_loop_trace: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    budgets = _budget_sweep_points(evaluation_budget)
    wamf_trace_by_iteration = {
        int(row.get("iteration", index + 1)): row
        for index, row in enumerate(wamf_closed_loop_trace or [])
        if isinstance(row, Mapping)
    }
    wamf_policy = next(
        (row for row in policy_rows if str(row.get("policy_id", "")) == "wamf_generic_active_pareto"),
        {},
    )
    wamf_candidate_ids = (
        [str(item) for item in wamf_policy.get("candidate_ids", []) or []]
        if isinstance(wamf_policy.get("candidate_ids", []), list)
        else []
    )
    wamf_rows_by_id = {
        str(row.get("candidate_id", "")): row
        for row in rows
        if isinstance(row, Mapping)
    }
    wamf_selected_rows = [
        wamf_rows_by_id[candidate_id]
        for candidate_id in wamf_candidate_ids
        if candidate_id in wamf_rows_by_id
    ]
    policy_curves = [
        {
            "policy_id": "wamf_generic_active_pareto",
            "points": [
                _with_wamf_closed_loop_budget_metadata(
                    _budget_sweep_point(
                        budget=budget,
                        selected_rows=wamf_selected_rows[:budget],
                        oracle_results=oracle_results,
                        oracle_rank=oracle_rank,
                    ),
                    budget=budget,
                    trace_row=wamf_trace_by_iteration.get(int(budget), {}),
                )
                for budget in budgets
            ],
        },
        {
            "policy_id": "workflow_aware_pareto_funnel",
            "points": [
                _budget_sweep_point(
                    budget=budget,
                    selected_rows=_policy_workflow_aware_pareto(l1_screening, rows, budget),
                    oracle_results=oracle_results,
                    oracle_rank=oracle_rank,
                )
                for budget in budgets
            ],
        },
        {
            "policy_id": "single_fidelity_l1_edp",
            "points": [
                _budget_sweep_point(
                    budget=budget,
                    selected_rows=_policy_single_fidelity_l1(rows, budget),
                    oracle_results=oracle_results,
                    oracle_rank=oracle_rank,
                )
                for budget in budgets
            ],
        },
        {
            "policy_id": "kernel_level_hotspot_only",
            "points": [
                _budget_sweep_point(
                    budget=budget,
                    selected_rows=_policy_kernel_hotspot_only(rows, budget),
                    oracle_results=oracle_results,
                    oracle_rank=oracle_rank,
                )
                for budget in budgets
            ],
        },
        {
            "policy_id": "manual_hbm_streaming_heuristic",
            "points": [
                _budget_sweep_point(
                    budget=budget,
                    selected_rows=_policy_manual_hbm(rows, budget),
                    oracle_results=oracle_results,
                    oracle_rank=oracle_rank,
                )
                for budget in budgets
            ],
        },
        {
            "policy_id": "nsga2_lite_multi_objective",
            "points": [
                _budget_sweep_point(
                    budget=budget,
                    selected_rows=_policy_nsga2_lite(rows, budget),
                    oracle_results=oracle_results,
                    oracle_rank=oracle_rank,
                )
                for budget in budgets
            ],
        },
        {
            "policy_id": "random_seeded_multi_seed",
            "points": [
                _random_budget_sweep_point(
                    rows=rows,
                    budget=budget,
                    oracle_results=oracle_results,
                    oracle_rank=oracle_rank,
                    seed_count=7,
                )
                for budget in budgets
            ],
        },
    ]
    return {
        "schema_version": "dse.qe_fpga_search_budget_sweep.v1",
        "oracle_fidelity": "L2_python_tlm",
        "budgets": budgets,
        "random_seed_count": 7,
        "policy_curves": policy_curves,
        "baseline_policy_results": policy_curves,
        "final_budget_policy_order": [
            str(row.get("policy_id", ""))
            for row in sorted(
                policy_rows,
                key=lambda row: (
                    _finite_float(
                        row.get("l2_oracle", {}).get("best_tlm_edp")
                        if isinstance(row.get("l2_oracle"), Mapping)
                        else None,
                        default=float("inf"),
                    ),
                    str(row.get("policy_id", "")),
                ),
            )
        ],
        "limitations": [
            "budget_sweep_uses_cached_L2_python_tlm_oracle_not_independent_hardware",
            "random_multi_seed_is_deterministic_for_replayability",
            "DAC_grade_curve_requires_replay_with_SystemC_gem5_HLS_Vivado_feedback",
        ],
        "claim_boundary": "budget_sweep_l2_tlm_only_not_hardware_evidence",
    }


def _build_independent_feedback_coverage_plan(
    *,
    l1_screening: Mapping[str, Any],
    policy_rows: Sequence[Mapping[str, Any]],
    feature_ablation_report: Mapping[str, Any],
    evaluation_budget: int,
) -> Dict[str, Any]:
    promoted_ids = {
        str(row.get("candidate_id", ""))
        for row in l1_screening.get("promotion_queue", []) or []
        if isinstance(row, Mapping) and str(row.get("candidate_id", ""))
    }
    source_rows: Dict[str, Dict[str, Any]] = {}
    for row in l1_screening.get("candidate_evaluations", []) or []:
        if isinstance(row, Mapping) and str(row.get("candidate_id", "")):
            source_rows[str(row.get("candidate_id", ""))] = dict(row)

    candidate_to_sources: Dict[str, set[str]] = {}
    policy_coverage: List[Dict[str, Any]] = []
    for policy in policy_rows:
        if not isinstance(policy, Mapping):
            continue
        policy_id = str(policy.get("policy_id", ""))
        candidate_ids = [
            str(candidate_id)
            for candidate_id in policy.get("candidate_ids", []) or []
            if str(candidate_id)
        ]
        for candidate_id in candidate_ids:
            candidate_to_sources.setdefault(candidate_id, set()).add(policy_id)
        policy_coverage.append({
            "policy_id": policy_id,
            "candidate_count": len(candidate_ids),
            "candidate_ids": candidate_ids,
            "selected_for_feedback_count": len(set(candidate_ids)),
        })

    ablations = [
        row for row in feature_ablation_report.get("ablations", []) or []
        if isinstance(row, Mapping)
    ]
    ablation_coverage: List[Dict[str, Any]] = []
    for ablation in ablations:
        ablation_id = str(ablation.get("ablation_id", ""))
        candidate_ids = [
            str(candidate_id)
            for candidate_id in ablation.get("candidate_ids", []) or []
            if str(candidate_id)
        ]
        source_id = f"ablation:{ablation_id}"
        for candidate_id in candidate_ids:
            candidate_to_sources.setdefault(candidate_id, set()).add(source_id)
        ablation_coverage.append({
            "ablation_id": ablation_id,
            "candidate_count": len(candidate_ids),
            "candidate_ids": candidate_ids,
            "selected_for_feedback_count": len(set(candidate_ids)),
        })

    for candidate_id in promoted_ids:
        candidate_to_sources.setdefault(candidate_id, set()).add("l1_promotion_queue")

    queue: List[Dict[str, Any]] = []
    for index, candidate_id in enumerate(sorted(candidate_to_sources)):
        row = source_rows.get(candidate_id, {})
        metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
        selection_sources = sorted(candidate_to_sources[candidate_id])
        queue.append({
            "candidate_id": candidate_id,
            "selection_role": "promoted" if candidate_id in promoted_ids else "baseline_holdout",
            "selection_sources": selection_sources,
            "source_count": len(selection_sources),
            "estimated_edp": _round_metric(_finite_float(metrics.get("estimated_edp"), default=0.0)),
            "estimated_workflow_wall_time_ms": _round_metric(_finite_float(metrics.get("estimated_workflow_wall_time_ms"), default=0.0)),
            "fpga_resource_pressure": _round_metric(_finite_float(metrics.get("fpga_resource_pressure"), default=0.0)),
            "candidate_order": index,
        })
    queue.sort(key=lambda row: (
        0 if row["selection_role"] == "promoted" else 1,
        -int(row.get("source_count", 0)),
        _finite_float(row.get("estimated_edp"), default=float("inf")),
        str(row.get("candidate_id", "")),
    ))
    for index, row in enumerate(queue):
        row["feedback_priority"] = index + 1

    policy_count = len([row for row in policy_rows if isinstance(row, Mapping)])
    minimum_count = max(int(evaluation_budget), len(promoted_ids), min(len(queue), policy_count))
    return {
        "schema_version": "dse.qe_fpga_independent_feedback_coverage_plan.v1",
        "purpose": "choose_candidates_for_independent_L3_L4_HLS_Vivado_feedback",
        "feedback_fidelities": [
            "L3_generic_sim_or_systemc",
            "L4_gem5_or_runtime_trace",
            "HLS_csim_csynth",
            "Vivado_synthesis_implementation",
            "bitstream_or_board_when_available",
        ],
        "policy_count": policy_count,
        "ablation_count": len(ablation_coverage),
        "candidate_count": len(queue),
        "promoted_candidate_count": len(promoted_ids),
        "holdout_candidate_count": max(0, len(queue) - len(promoted_ids)),
        "evaluation_budget": int(evaluation_budget),
        "minimum_recommended_feedback_count": minimum_count,
        "policy_coverage": policy_coverage,
        "ablation_coverage": ablation_coverage,
        "candidate_feedback_queue": queue,
        "coverage_rule": (
            "evaluate all promoted candidates plus the union of baseline and "
            "ablation-selected holdouts before using external feedback for "
            "policy superiority claims"
        ),
        "limitations": [
            "coverage_plan_does_not_execute_independent_tools",
            "candidate_queue_size_can_exceed_initial_feedback_budget",
            "policy_superiority_requires_feedback_overlap_for_each_compared_policy",
        ],
        "claim_boundary": "feedback_coverage_plan_only_not_executed_independent_evidence",
    }


def _build_feature_ablation_report(
    *,
    l1_screening: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    budget: int,
    oracle_results: Mapping[str, Mapping[str, Any]],
    oracle_rank: Mapping[str, int],
) -> Dict[str, Any]:
    ablation_specs = [
        (
            "full_workflow_structural_features",
            [],
            _policy_workflow_aware_pareto(l1_screening, rows, budget),
            {
                "baseline_type": "workflow_feature_prior_baseline",
                "component_role": "l1_workflow_prior_full_features",
                "uses_workflow_abstraction": True,
                "uses_data_object_lifetime": True,
                "uses_host_control_events": True,
                "uses_correctness_gate_pressure": True,
                "uses_pareto_selection": True,
            },
        ),
        (
            "remove_data_object_lifetime",
            ["data_object_lifetime"],
            _policy_feature_ablation(rows, budget, remove={"data_object_lifetime"}),
            {
                "baseline_type": "feature_ablation",
                "uses_workflow_abstraction": True,
                "uses_data_object_lifetime": False,
                "uses_host_control_events": True,
                "uses_correctness_gate_pressure": True,
                "uses_pareto_selection": True,
            },
        ),
        (
            "remove_host_control_events",
            ["host_control_event_counts"],
            _policy_feature_ablation(rows, budget, remove={"host_control_event_counts"}),
            {
                "baseline_type": "feature_ablation",
                "uses_workflow_abstraction": True,
                "uses_data_object_lifetime": True,
                "uses_host_control_events": False,
                "uses_correctness_gate_pressure": True,
                "uses_pareto_selection": True,
            },
        ),
        (
            "remove_correctness_gate_pressure",
            ["correctness_observables"],
            _policy_feature_ablation(rows, budget, remove={"correctness_observables"}),
            {
                "baseline_type": "feature_ablation",
                "uses_workflow_abstraction": True,
                "uses_data_object_lifetime": True,
                "uses_host_control_events": True,
                "uses_correctness_gate_pressure": False,
                "uses_pareto_selection": True,
            },
        ),
        (
            "kernel_histogram_only",
            ["data_object_lifetime", "host_control_event_counts", "correctness_observables", "stage_repetition"],
            _policy_kernel_hotspot_only(rows, budget),
            {
                "baseline_type": "kernel_histogram_only_ablation",
                "uses_workflow_abstraction": False,
                "uses_data_object_lifetime": False,
                "uses_host_control_events": False,
                "uses_correctness_gate_pressure": False,
                "uses_pareto_selection": False,
            },
        ),
    ]
    ablations = [
        _feature_ablation_row(
            ablation_id=ablation_id,
            removed_feature_groups=removed,
            selected_rows=selected_rows,
            oracle_results=oracle_results,
            oracle_rank=oracle_rank,
            selection_basis=selection_basis,
        )
        for ablation_id, removed, selected_rows, selection_basis in ablation_specs
    ]
    _annotate_feature_ablation_comparisons(ablations)
    return {
        "schema_version": "dse.qe_fpga_feature_ablation_report.v1",
        "oracle_fidelity": "L2_python_tlm",
        "workflow_abstraction": _wamf_workflow_abstraction_summary(l1_screening),
        "evaluation_budget": int(budget),
        "ablation_count": len(ablations),
        "ablations": ablations,
        "limitations": [
            "feature_ablation_uses_L2_python_tlm_model_oracle_not_independent_hardware",
            "ablation_selectors_share_the_same_candidate_pool_for_replayability",
            "DAC_grade_ablation_requires_replay_with_measured_QE_and_HLS_Vivado_feedback",
        ],
        "claim_boundary": "feature_ablation_l2_tlm_only_not_hardware_evidence",
    }


def _annotate_feature_ablation_comparisons(ablations: Sequence[Dict[str, Any]]) -> None:
    full = next(
        (row for row in ablations if row.get("ablation_id") == "full_workflow_structural_features"),
        ablations[0] if ablations else {},
    )
    full_ids = {str(candidate_id) for candidate_id in full.get("candidate_ids", []) or []}
    full_rank = _finite_float(
        full.get("l2_oracle", {}).get("oracle_rank_of_best_selected")
        if isinstance(full.get("l2_oracle"), Mapping)
        else None,
        default=float("inf"),
    )
    full_edp = _finite_float(
        full.get("l2_oracle", {}).get("best_tlm_edp")
        if isinstance(full.get("l2_oracle"), Mapping)
        else None,
        default=0.0,
    )
    for row in ablations:
        ids = {str(candidate_id) for candidate_id in row.get("candidate_ids", []) or []}
        union = full_ids | ids
        overlap = len(full_ids & ids)
        jaccard = float(overlap) / float(len(union)) if union else 1.0
        rank = _finite_float(
            row.get("l2_oracle", {}).get("oracle_rank_of_best_selected")
            if isinstance(row.get("l2_oracle"), Mapping)
            else None,
            default=float("inf"),
        )
        edp = _finite_float(
            row.get("l2_oracle", {}).get("best_tlm_edp")
            if isinstance(row.get("l2_oracle"), Mapping)
            else None,
            default=0.0,
        )
        row["comparison_to_full"] = {
            "full_ablation_id": str(full.get("ablation_id", "")),
            "candidate_overlap_with_full": overlap,
            "candidate_jaccard_with_full": _round_metric(jaccard),
            "rank_delta_vs_full": int(rank - full_rank) if math.isfinite(rank) and math.isfinite(full_rank) else None,
            "best_edp_ratio_vs_full": _round_metric(edp / full_edp) if full_edp > 0.0 and edp > 0.0 else None,
            "decision_changed": ids != full_ids,
        }


def _feature_ablation_row(
    *,
    ablation_id: str,
    removed_feature_groups: Sequence[str],
    selected_rows: Sequence[Mapping[str, Any]],
    oracle_results: Mapping[str, Mapping[str, Any]],
    oracle_rank: Mapping[str, int],
    selection_basis: Mapping[str, Any],
) -> Dict[str, Any]:
    summaries = _selected_oracle_summaries(selected_rows, oracle_results, oracle_rank)
    best = min(
        summaries,
        key=lambda row: (
            int(row.get("oracle_rank", len(oracle_rank) + 1)),
            str(row.get("candidate_id", "")),
        ),
        default={},
    )
    ranks = [
        float(row["oracle_rank"])
        for row in summaries
        if isinstance(row.get("oracle_rank"), int)
    ]
    return {
        "ablation_id": ablation_id,
        "removed_feature_groups": list(removed_feature_groups),
        "selected_count": len(selected_rows),
        "candidate_ids": [str(row.get("candidate_id", "")) for row in selected_rows],
        "selection_basis": dict(selection_basis),
        "l2_oracle": {
            "best_candidate_id": str(best.get("candidate_id", "")),
            "best_tlm_edp": _round_metric(_finite_float(best.get("tlm_edp"), default=0.0)),
            "oracle_rank_of_best_selected": best.get("oracle_rank"),
            "mean_oracle_rank_of_selected": _round_metric(_mean(ranks)),
        },
    }


def _policy_feature_ablation(
    rows: Sequence[Mapping[str, Any]],
    budget: int,
    *,
    remove: set[str],
) -> List[Mapping[str, Any]]:
    return sorted(
        rows,
        key=lambda row: _feature_ablation_sort_key(row, remove=remove),
    )[:budget]


def _feature_ablation_sort_key(row: Mapping[str, Any], *, remove: set[str]) -> Tuple[float, float, float, float, str]:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    edp = _finite_float(metrics.get("estimated_edp"), default=float("inf"))
    movement = _finite_float(metrics.get("estimated_data_movement_mb"), default=0.0)
    resource = _finite_float(metrics.get("fpga_resource_pressure"), default=float("inf"))
    host_penalty = _finite_float(metrics.get("host_control_event_penalty_ms"), default=0.0)
    correctness = _finite_float(metrics.get("correctness_gate_count"), default=0.0)
    if "data_object_lifetime" in remove:
        edp -= movement * 20.0
    if "host_control_event_counts" in remove:
        edp -= host_penalty * 30.0
    if "correctness_observables" in remove:
        resource -= min(0.20, correctness * 0.015)
    return (
        max(1.0, edp),
        max(0.0, resource),
        movement,
        host_penalty,
        str(row.get("candidate_id", "")),
    )


def _budget_sweep_points(evaluation_budget: int) -> List[int]:
    final_budget = max(1, int(evaluation_budget))
    points = [1]
    value = 2
    while value < final_budget:
        points.append(value)
        value *= 2
    if final_budget not in points:
        points.append(final_budget)
    return points


def _budget_sweep_point(
    *,
    budget: int,
    selected_rows: Sequence[Mapping[str, Any]],
    oracle_results: Mapping[str, Mapping[str, Any]],
    oracle_rank: Mapping[str, int],
) -> Dict[str, Any]:
    summaries = _selected_oracle_summaries(selected_rows, oracle_results, oracle_rank)
    passed = [
        row for row in summaries
        if str(row.get("status", "")) == "passed"
    ]
    best = min(passed, key=lambda row: (_finite_float(row.get("tlm_edp"), default=float("inf")), str(row.get("candidate_id", ""))), default={})
    return {
        "budget": int(budget),
        "evaluated_count": len(summaries),
        "passed_count": len(passed),
        "failed_count": max(0, len(summaries) - len(passed)),
        "best_candidate_id": str(best.get("candidate_id", "")),
        "best_tlm_edp": _round_metric(_finite_float(best.get("tlm_edp"), default=float("inf"))),
        "oracle_rank_of_best": best.get("oracle_rank"),
        "mean_oracle_rank": _round_metric(_mean([
            float(row["oracle_rank"])
            for row in passed
            if isinstance(row.get("oracle_rank"), int)
        ])),
        "top_k_hit": bool(_finite_float(best.get("oracle_rank"), default=float("inf")) <= 5.0),
    }


def _with_wamf_closed_loop_budget_metadata(
    point: Mapping[str, Any],
    *,
    budget: int,
    trace_row: Mapping[str, Any],
) -> Dict[str, Any]:
    updated = dict(point)
    updated["closed_loop_observation_count"] = max(0, int(budget) - 1)
    selection_report = (
        trace_row.get("selection_report", {})
        if isinstance(trace_row.get("selection_report"), Mapping)
        else {}
    )
    selection = (
        selection_report.get("selection", [])
        if isinstance(selection_report.get("selection"), list)
        else []
    )
    first_selection = selection[0] if selection and isinstance(selection[0], Mapping) else {}
    acquisition = (
        first_selection.get("acquisition", {})
        if isinstance(first_selection.get("acquisition"), Mapping)
        else {}
    )
    updated["selection_frontier_source"] = str(
        acquisition.get(
            "frontier_source",
            "observed_high_fidelity_frontier" if int(budget) > 1 else "cheap_model_candidate_frontier",
        )
    )
    updated["selection_candidate_id"] = str(trace_row.get("candidate_id", ""))
    updated["feedback_updated_after_selection"] = bool(trace_row.get("observation_available", False))
    return updated


def _random_budget_sweep_point(
    *,
    rows: Sequence[Mapping[str, Any]],
    budget: int,
    oracle_results: Mapping[str, Mapping[str, Any]],
    oracle_rank: Mapping[str, int],
    seed_count: int,
) -> Dict[str, Any]:
    seed_points = [
        _budget_sweep_point(
            budget=budget,
            selected_rows=_policy_seeded_random(rows, budget, seed=f"seed_{seed:02d}"),
            oracle_results=oracle_results,
            oracle_rank=oracle_rank,
        )
        for seed in range(seed_count)
    ]
    edps = [_finite_float(point.get("best_tlm_edp"), default=float("inf")) for point in seed_points]
    ranks = [_finite_float(point.get("oracle_rank_of_best"), default=float("inf")) for point in seed_points]
    finite_ranks = [rank for rank in ranks if math.isfinite(rank)]
    return {
        "budget": int(budget),
        "random_seed_count": int(seed_count),
        "best_tlm_edp_mean": _round_metric(_mean(edps)),
        "best_tlm_edp_std": _round_metric(_stddev(edps)),
        "oracle_rank_mean": _round_metric(_mean(ranks)),
        "oracle_rank_best": int(min(finite_ranks)) if finite_ranks else None,
        "top_k_hit_rate": _round_metric(_mean([1.0 if point.get("top_k_hit") else 0.0 for point in seed_points])),
        "seed_points": seed_points,
    }


def _selected_oracle_summaries(
    selected_rows: Sequence[Mapping[str, Any]],
    oracle_results: Mapping[str, Mapping[str, Any]],
    oracle_rank: Mapping[str, int],
) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for row in selected_rows:
        candidate_id = str(row.get("candidate_id", ""))
        oracle = oracle_results.get(candidate_id, {})
        summaries.append({
            "candidate_id": candidate_id,
            "status": str(oracle.get("status", "")),
            "tlm_edp": _l2_metric(oracle, "tlm_edp"),
            "oracle_rank": int(oracle_rank.get(candidate_id, len(oracle_rank) + 1)),
        })
    return summaries


def _policy_rows_from_neural_trace(
    neural_search: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    budget: int,
) -> List[Mapping[str, Any]]:
    by_candidate = {str(row.get("candidate_id", "")): row for row in rows if isinstance(row, Mapping)}
    selected: List[Mapping[str, Any]] = []
    seen: set[str] = set()
    for trace_row in neural_search.get("evaluation_trace", []) or []:
        if not isinstance(trace_row, Mapping):
            continue
        candidate_id = str(trace_row.get("candidate_id", ""))
        if candidate_id and candidate_id in by_candidate and candidate_id not in seen:
            selected.append(by_candidate[candidate_id])
            seen.add(candidate_id)
        if len(selected) >= max(1, int(budget)):
            break
    if len(selected) < max(1, int(budget)):
        for row in _policy_single_fidelity_l1(rows, max(1, int(budget))):
            candidate_id = str(row.get("candidate_id", ""))
            if candidate_id not in seen:
                selected.append(row)
                seen.add(candidate_id)
            if len(selected) >= max(1, int(budget)):
                break
    return selected


def _policy_wamf_generic_active_pareto(
    rows: Sequence[Mapping[str, Any]],
    l1_screening: Mapping[str, Any],
    budget: int,
) -> List[Mapping[str, Any]]:
    workload_features = (
        l1_screening.get("workload_features", {})
        if isinstance(l1_screening.get("workload_features"), Mapping)
        else {}
    )
    release_rows = [
        row for row in rows
        if isinstance(row, Mapping)
        and _is_release_candidate(row)
    ]
    row_by_id = {str(row.get("candidate_id", "")): row for row in release_rows if isinstance(row, Mapping)}
    report = _run_wamf_global_acquisition(
        release_rows,
        workload_features,
        observations=[],
        budget=max(1, int(budget)),
    )
    selected_rows = [
        row_by_id[candidate_id]
        for candidate_id in [str(item) for item in report.get("selected_candidate_ids", []) or []]
        if candidate_id in row_by_id
    ]
    if len(selected_rows) >= max(1, int(budget)):
        return selected_rows[:max(1, int(budget))]
    selected_ids = {str(row.get("candidate_id", "")) for row in selected_rows}
    for row in _policy_workflow_aware_pareto(l1_screening, release_rows, max(1, int(budget))):
        candidate_id = str(row.get("candidate_id", ""))
        if candidate_id and candidate_id not in selected_ids:
            selected_rows.append(row)
            selected_ids.add(candidate_id)
        if len(selected_rows) >= max(1, int(budget)):
            break
    return selected_rows


def _policy_wamf_generic_active_pareto_closed_loop(
    rows: Sequence[Mapping[str, Any]],
    l1_screening: Mapping[str, Any],
    budget: int,
    *,
    observation_results_by_candidate: Mapping[str, Mapping[str, Any]],
    external_feedback_by_candidate: Mapping[str, Mapping[str, Any]] | None = None,
    initial_observations: Sequence[ActiveSearchObservation] | None = None,
) -> Tuple[List[Mapping[str, Any]], List[Dict[str, Any]]]:
    workload_features = (
        l1_screening.get("workload_features", {})
        if isinstance(l1_screening.get("workload_features"), Mapping)
        else {}
    )
    release_rows = [
        row for row in rows
        if isinstance(row, Mapping)
        and _is_release_candidate(row)
    ]
    row_by_id = {str(row.get("candidate_id", "")): row for row in release_rows if isinstance(row, Mapping)}
    selected_ids: set[str] = set()
    selected: List[Mapping[str, Any]] = []
    trace: List[Dict[str, Any]] = []
    observations: List[ActiveSearchObservation] = list(initial_observations or [])
    initial_observation_payloads = [row.to_dict() for row in observations]
    final_budget = max(1, int(budget))
    prior_seed_rows = _policy_workflow_aware_pareto(l1_screening, release_rows, final_budget)
    prior_seed_budget = (
        0
        if observations
        else min(len(prior_seed_rows), max(1, min(3, math.ceil(final_budget / 2.0))))
    )
    for seed_row in prior_seed_rows[:prior_seed_budget]:
        seed_id = str(seed_row.get("candidate_id", ""))
        if not seed_id or seed_id in selected_ids:
            continue
        selected.append(seed_row)
        selected_ids.add(seed_id)
        observation, observation_source = _wamf_closed_loop_observation_for_candidate(
            seed_id,
            prior_row=seed_row,
            workload_features=workload_features,
            observation_results_by_candidate=observation_results_by_candidate,
            external_feedback_by_candidate=external_feedback_by_candidate,
            l2_source="wamf_closed_loop_prior_seed",
        )
        if observation is not None:
            observations.append(observation)
        trace.append({
            "iteration": len(selected),
            "candidate_id": seed_id,
            "fallback_used": False,
            "prior_seed_used": True,
            "prior_seed_policy": "workflow_aware_pareto_funnel",
            "selection_report": {
                "schema_version": "dse.multifidelity_active_search.selection.v1",
                "policy_id": "wamf_constrained_active_pareto",
                "candidate_count": len(release_rows),
                "observation_count": len(initial_observations or []),
                "budget": 1,
                "selected_candidate_ids": [seed_id],
                "selection": [],
                "algorithm_contract": {
                    "domain_neutral": True,
                    "evidence_role": "feedback_calibration_not_search_objective",
                    "feedback_closed_loop": bool(observations),
                    "prior_seed_policy": "workflow_aware_pareto_funnel",
                    "prior_seed_budget": prior_seed_budget,
                },
            },
            "initial_external_feedback_observation_count": len(initial_observation_payloads),
            "initial_observations": initial_observation_payloads,
            "observation_available": observation is not None,
            "observation_source": observation_source,
            "observation": observation.to_dict() if observation is not None else None,
            "observation_count_after_update": len(observations),
        })
    for iteration in range(len(selected) + 1, final_budget + 1):
        candidate_rows = [
            row for row in release_rows
            if str(row.get("candidate_id", "")) not in selected_ids
        ]
        if not candidate_rows:
            break
        report = _run_wamf_global_acquisition(
            candidate_rows,
            workload_features,
            observations=observations,
            budget=1,
        )
        candidate_ids = [str(item) for item in report.get("selected_candidate_ids", []) or []]
        selected_row = next(
            (row_by_id[candidate_id] for candidate_id in candidate_ids if candidate_id in row_by_id),
            None,
        )
        fallback_used = False
        promotion_safeguard = _wamf_promotion_safeguard_decision(
            selected_row=selected_row,
            fallback_row=_next_workflow_prior_fallback_row(
                l1_screening,
                release_rows,
                final_budget,
                selected_ids,
            ),
            workload_features=workload_features,
            observations=observations,
        )
        if promotion_safeguard.get("decision") == "fallback_to_workflow_prior":
            fallback_id = str(promotion_safeguard.get("fallback_candidate_id", ""))
            if fallback_id in row_by_id:
                selected_row = row_by_id[fallback_id]
                fallback_used = True
        if selected_row is None:
            selected_row = _next_workflow_prior_fallback_row(
                l1_screening,
                release_rows,
                final_budget,
                selected_ids,
            )
            fallback_used = selected_row is not None
        if selected_row is None:
            break
        candidate_id = str(selected_row.get("candidate_id", ""))
        selected.append(selected_row)
        selected_ids.add(candidate_id)
        observation, observation_source = _wamf_closed_loop_observation_for_candidate(
            candidate_id,
            prior_row=selected_row,
            workload_features=workload_features,
            observation_results_by_candidate=observation_results_by_candidate,
            external_feedback_by_candidate=external_feedback_by_candidate,
            l2_source="wamf_closed_loop_policy_evaluation",
        )
        if observation is not None:
            observations.append(observation)
        trace.append({
            "iteration": iteration,
            "candidate_id": candidate_id,
            "fallback_used": fallback_used,
            "selection_report": report,
            "promotion_safeguard": promotion_safeguard,
            "initial_external_feedback_observation_count": len(initial_observation_payloads),
            "initial_observations": initial_observation_payloads,
            "observation_available": observation is not None,
            "observation_source": observation_source,
            "observation": observation.to_dict() if observation is not None else None,
            "observation_count_after_update": len(observations),
        })
    if len(selected) < final_budget:
        for row in _policy_workflow_aware_pareto(l1_screening, rows, final_budget):
            candidate_id = str(row.get("candidate_id", ""))
            if candidate_id and candidate_id not in selected_ids:
                selected.append(row)
                selected_ids.add(candidate_id)
                trace.append({
                    "iteration": len(selected),
                    "candidate_id": candidate_id,
                    "fallback_used": True,
                    "selection_report": {
                        "schema_version": "dse.multifidelity_active_search.selection.v1",
                        "policy_id": "wamf_constrained_active_pareto",
                        "candidate_count": 0,
                        "observation_count": len(observations),
                        "budget": 1,
                        "selected_candidate_ids": [candidate_id],
                        "selection": [],
                        "algorithm_contract": {
                            "domain_neutral": True,
                            "evidence_role": "feedback_calibration_not_search_objective",
                            "feedback_closed_loop": bool(observations),
                            "fallback": "workflow_aware_pareto_when_no_positive_acquisition",
                        },
                    },
                    "observation_available": False,
                    "observation_count_after_update": len(observations),
                })
            if len(selected) >= final_budget:
                break
    return selected, trace


def _next_workflow_prior_fallback_row(
    l1_screening: Mapping[str, Any],
    release_rows: Sequence[Mapping[str, Any]],
    final_budget: int,
    selected_ids: set[str],
) -> Mapping[str, Any] | None:
    for row in _policy_workflow_aware_pareto(l1_screening, release_rows, final_budget):
        candidate_id = str(row.get("candidate_id", ""))
        if candidate_id and candidate_id not in selected_ids:
            return row
    return None


def _wamf_promotion_safeguard_decision(
    *,
    selected_row: Mapping[str, Any] | None,
    fallback_row: Mapping[str, Any] | None,
    workload_features: Mapping[str, Any],
    observations: Sequence[ActiveSearchObservation],
) -> Dict[str, Any]:
    if not isinstance(fallback_row, Mapping) or not fallback_row:
        return {
            "enabled": True,
            "decision": "accept_active_selection",
            "reason": "no_workflow_prior_fallback_available",
        }
    if not isinstance(selected_row, Mapping) or not selected_row:
        return {
            "enabled": True,
            "decision": "fallback_to_workflow_prior",
            "reason": "no_active_selection_available",
            "fallback_candidate_id": str(fallback_row.get("candidate_id", "")),
        }
    selected_id = str(selected_row.get("candidate_id", ""))
    fallback_id = str(fallback_row.get("candidate_id", ""))
    if selected_id == fallback_id:
        return {
            "enabled": True,
            "decision": "accept_active_selection",
            "reason": "active_selection_matches_workflow_prior",
            "selected_candidate_id": selected_id,
            "fallback_candidate_id": fallback_id,
        }
    components_by_id = _wamf_pairwise_candidate_components_by_id(
        [selected_row, fallback_row],
        workload_features=workload_features,
        observations=observations,
    )
    selected_components = components_by_id.get(selected_id, {})
    fallback_components = components_by_id.get(fallback_id, {})
    selected_rank = _finite_float(
        selected_components.get("scalar_quality_rank_index"),
        default=float("inf"),
    )
    fallback_rank = _finite_float(
        fallback_components.get("scalar_quality_rank_index"),
        default=float("inf"),
    )
    selected_qor = _finite_float(
        selected_components.get("calibrated_scalar_quality_objective"),
        default=float("inf"),
    )
    fallback_qor = _finite_float(
        fallback_components.get("calibrated_scalar_quality_objective"),
        default=float("inf"),
    )
    selected_hv = _finite_float(
        selected_components.get("cost_normalized_hv_gain"),
        default=0.0,
    )
    fallback_hv = _finite_float(
        fallback_components.get("cost_normalized_hv_gain"),
        default=0.0,
    )
    active_rank_better = selected_rank + 2.0 <= fallback_rank
    active_qor_better = selected_qor < fallback_qor * 0.95
    active_hv_much_better = selected_hv > fallback_hv + 0.08
    if (active_rank_better and active_qor_better) or active_hv_much_better:
        return {
            "enabled": True,
            "decision": "accept_active_selection",
            "reason": "active_selection_has_calibrated_advantage",
            "selected_candidate_id": selected_id,
            "fallback_candidate_id": fallback_id,
            "selected_scalar_quality_rank_index": _round_metric(selected_rank),
            "fallback_scalar_quality_rank_index": _round_metric(fallback_rank),
            "selected_calibrated_scalar_quality_objective": _round_metric(selected_qor),
            "fallback_calibrated_scalar_quality_objective": _round_metric(fallback_qor),
            "selected_cost_normalized_hv_gain": _round_metric(selected_hv),
            "fallback_cost_normalized_hv_gain": _round_metric(fallback_hv),
        }
    return {
        "enabled": True,
        "decision": "fallback_to_workflow_prior",
        "reason": "active_selection_lacks_calibrated_advantage_over_workflow_prior",
        "selected_candidate_id": selected_id,
        "fallback_candidate_id": fallback_id,
        "selected_scalar_quality_rank_index": _round_metric(selected_rank),
        "fallback_scalar_quality_rank_index": _round_metric(fallback_rank),
        "selected_calibrated_scalar_quality_objective": _round_metric(selected_qor),
        "fallback_calibrated_scalar_quality_objective": _round_metric(fallback_qor),
        "selected_cost_normalized_hv_gain": _round_metric(selected_hv),
        "fallback_cost_normalized_hv_gain": _round_metric(fallback_hv),
    }


def _wamf_pairwise_candidate_components_by_id(
    rows: Sequence[Mapping[str, Any]],
    *,
    workload_features: Mapping[str, Any],
    observations: Sequence[ActiveSearchObservation],
) -> Dict[str, Dict[str, Any]]:
    report = _run_wamf_global_acquisition(
        rows,
        workload_features,
        observations=observations,
        budget=len(rows),
    )
    selection = report.get("selection", []) if isinstance(report.get("selection"), list) else []
    by_id: Dict[str, Dict[str, Any]] = {}
    for item in selection:
        if not isinstance(item, Mapping):
            continue
        acquisition = item.get("acquisition", {})
        if not isinstance(acquisition, Mapping):
            continue
        components = acquisition.get("components", {})
        if isinstance(components, Mapping):
            by_id[str(item.get("candidate_id", ""))] = dict(components)
    return by_id


def _wamf_promotion_safeguard_summary(
    trace: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    decisions = [
        row.get("promotion_safeguard", {})
        for row in trace
        if isinstance(row.get("promotion_safeguard"), Mapping)
    ]
    fallback_count = sum(
        1 for row in decisions
        if row.get("decision") == "fallback_to_workflow_prior"
    )
    active_count = sum(
        1 for row in decisions
        if row.get("decision") == "accept_active_selection"
    )
    return {
        "enabled": True,
        "decision_count": len(decisions),
        "fallback_to_workflow_prior_count": fallback_count,
        "accept_active_selection_count": active_count,
        "policy": "calibrated_active_selection_must_beat_workflow_prior_fallback",
    }


def _wamf_closed_loop_observation_for_candidate(
    candidate_id: str,
    *,
    prior_row: Mapping[str, Any],
    workload_features: Mapping[str, Any],
    observation_results_by_candidate: Mapping[str, Mapping[str, Any]],
    external_feedback_by_candidate: Mapping[str, Mapping[str, Any]] | None,
    l2_source: str,
) -> Tuple[ActiveSearchObservation | None, str]:
    external_row = (
        external_feedback_by_candidate.get(candidate_id, {})
        if isinstance(external_feedback_by_candidate, Mapping)
        else {}
    )
    observation = _active_search_observation_from_external_feedback(
        external_row,
        source="external_common_objective_feedback",
        prior_row=prior_row,
        workload_features=workload_features,
    )
    if observation is not None:
        return observation, "external_feedback_calibrated_common_objective"
    observation = _active_search_observation_from_l2_result(
        observation_results_by_candidate.get(candidate_id, {}),
        source=l2_source,
        prior_row=prior_row,
        workload_features=workload_features,
    )
    if observation is not None:
        return observation, "L2_python_tlm"
    return None, "none"


def _policy_evaluation_row(
    *,
    policy_id: str,
    selected_rows: Sequence[Mapping[str, Any]],
    oracle_results: Mapping[str, Mapping[str, Any]],
    oracle_rank: Mapping[str, int],
    oracle_best_edp: float,
    selection_basis: Mapping[str, Any],
    final_budget: int,
    closed_loop_feedback_trace: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    trimmed = list(selected_rows[: max(1, int(final_budget))])
    curve = [
        _policy_budget_quality_point(
            budget=budget,
            selected_rows=trimmed[:budget],
            oracle_results=oracle_results,
            oracle_rank=oracle_rank,
            oracle_best_edp=oracle_best_edp,
        )
        for budget in _budget_sweep_points(max(1, int(final_budget)))
    ]
    trace_rows = [
        dict(row) for row in closed_loop_feedback_trace or []
        if isinstance(row, Mapping)
    ]
    if trace_rows:
        trace_by_iteration = {
            int(row.get("iteration", index + 1)): row
            for index, row in enumerate(trace_rows)
        }
        for point in curve:
            point_budget = int(point.get("budget", 0))
            trace_row = trace_by_iteration.get(point_budget, {})
            selection_report = (
                trace_row.get("selection_report", {})
                if isinstance(trace_row.get("selection_report"), Mapping)
                else {}
            )
            selection = (
                selection_report.get("selection", [])
                if isinstance(selection_report.get("selection"), list)
                else []
            )
            first_selection = selection[0] if selection and isinstance(selection[0], Mapping) else {}
            acquisition = (
                first_selection.get("acquisition", {})
                if isinstance(first_selection.get("acquisition"), Mapping)
                else {}
            )
            point["closed_loop_observation_count"] = max(0, point_budget - 1)
            point["selection_frontier_source"] = str(
                acquisition.get(
                    "frontier_source",
                    "observed_high_fidelity_frontier" if point_budget > 1 else "cheap_model_candidate_frontier",
                )
            )
            point["selection_candidate_id"] = str(trace_row.get("candidate_id", ""))
            point["feedback_updated_after_selection"] = bool(trace_row.get("observation_available", False))
    order_rank_pairs = []
    for order, row in enumerate(trimmed, start=1):
        rank = oracle_rank.get(str(row.get("candidate_id", "")))
        if isinstance(rank, int):
            order_rank_pairs.append((float(order), float(rank)))
    final = curve[-1] if curve else {}
    return {
        "policy_id": str(policy_id),
        "selected_count": len(trimmed),
        "candidate_ids": [str(row.get("candidate_id", "")) for row in trimmed],
        "selection_basis": dict(selection_basis),
        "budget_curve": curve,
        **({"closed_loop_feedback_trace": trace_rows} if trace_rows else {}),
        "ranking_quality": {
            "spearman_l2_oracle_vs_selection_order": (
                _round_metric(_spearman(
                    [pair[0] for pair in order_rank_pairs],
                    [pair[1] for pair in order_rank_pairs],
                ))
                if len(order_rank_pairs) >= 2
                else None
            ),
            "rank_pairs_count": len(order_rank_pairs),
            "lower_selection_order_and_lower_oracle_rank_are_better": True,
        },
        "sample_efficiency": {
            "evaluations_to_top_1_hit": _evaluations_to_top_k(trimmed, oracle_rank, k=1),
            "evaluations_to_top_5_hit": _evaluations_to_top_k(trimmed, oracle_rank, k=5),
            "final_simple_regret": final.get("simple_regret"),
            "final_oracle_rank": final.get("oracle_rank_of_best"),
        },
    }


def _policy_budget_quality_point(
    *,
    budget: int,
    selected_rows: Sequence[Mapping[str, Any]],
    oracle_results: Mapping[str, Mapping[str, Any]],
    oracle_rank: Mapping[str, int],
    oracle_best_edp: float,
) -> Dict[str, Any]:
    point = _budget_sweep_point(
        budget=budget,
        selected_rows=selected_rows,
        oracle_results=oracle_results,
        oracle_rank=oracle_rank,
    )
    best_edp = _finite_float(point.get("best_tlm_edp"), default=float("inf"))
    regret = max(0.0, best_edp - oracle_best_edp) if math.isfinite(best_edp) and math.isfinite(oracle_best_edp) else float("inf")
    point["simple_regret"] = _round_metric(regret)
    point["normalized_regret"] = _round_metric(regret / max(oracle_best_edp, 1.0)) if math.isfinite(regret) else float("inf")
    point["top_1_hit"] = bool(_finite_float(point.get("oracle_rank_of_best"), default=float("inf")) <= 1.0)
    return point


def _evaluations_to_top_k(
    selected_rows: Sequence[Mapping[str, Any]],
    oracle_rank: Mapping[str, int],
    *,
    k: int,
) -> int | None:
    for index, row in enumerate(selected_rows, start=1):
        rank = oracle_rank.get(str(row.get("candidate_id", "")))
        if isinstance(rank, int) and rank <= int(k):
            return index
    return None


def _oracle_best_edp(oracle_results: Mapping[str, Mapping[str, Any]]) -> float:
    values = [
        _l2_metric(row, "tlm_edp")
        for row in oracle_results.values()
        if isinstance(row, Mapping) and str(row.get("status", "")) == "passed"
    ]
    finite_values = [value for value in values if math.isfinite(value)]
    return min(finite_values) if finite_values else float("inf")


def _policy_final_regret(policy_row: Mapping[str, Any]) -> float:
    curve = policy_row.get("budget_curve", []) if isinstance(policy_row.get("budget_curve"), list) else []
    if not curve:
        return float("inf")
    return _finite_float(curve[-1].get("simple_regret"), default=float("inf"))


def _evaluate_search_policy(
    *,
    manifest: Mapping[str, Any],
    problem_payload: Mapping[str, Any],
    policy_id: str,
    selected_rows: Sequence[Mapping[str, Any]],
    oracle_rank: Mapping[str, int],
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
    selection_basis: Mapping[str, Any],
) -> Dict[str, Any]:
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem_payload,
        selected_rows,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    l2_results = run_qe_fpga_l2_tlm_requests(bundle)
    result_rows = [
        row for row in l2_results.get("results", []) or []
        if isinstance(row, Mapping)
    ]
    passed_rows = [
        row for row in result_rows
        if str(row.get("status", "")) == "passed"
    ]
    best_result = min(passed_rows, key=_l2_edp_sort_key, default={})
    best_edp = _l2_edp_sort_key(best_result)[0] if best_result else float("inf")
    best_candidate_id = str(best_result.get("candidate_id", "")) if isinstance(best_result, Mapping) else ""
    ranks = [
        int(oracle_rank.get(str(row.get("candidate_id", "")), len(oracle_rank) + 1))
        for row in passed_rows
        if isinstance(row, Mapping)
    ]
    return {
        "policy_id": policy_id,
        "selected_count": len(selected_rows),
        "candidate_ids": [str(row.get("candidate_id", "")) for row in selected_rows],
        "selected_rows": [_policy_selected_row_summary(row) for row in selected_rows],
        "selection_basis": dict(selection_basis),
        "l2_oracle": {
            "evaluated_count": int(l2_results.get("executed_count", len(result_rows))),
            "passed_count": int(l2_results.get("passed_count", 0)),
            "failed_count": int(l2_results.get("failed_count", max(0, len(result_rows) - len(passed_rows)))),
            "best_candidate_id": best_candidate_id,
            "best_status": str(best_result.get("status", "")) if best_result else "no_passed_candidate",
            "best_tlm_edp": _round_metric(best_edp),
            "best_tlm_workflow_wall_time_ms": _round_metric(_l2_metric(best_result, "tlm_workflow_wall_time_ms")),
            "best_tlm_energy_mj": _round_metric(_l2_metric(best_result, "tlm_energy_mj")),
            "oracle_rank_of_best_selected": min(ranks) if ranks else None,
            "mean_oracle_rank_of_selected": _round_metric(_mean([float(rank) for rank in ranks])) if ranks else None,
        },
        "result_summaries": [
            {
                "candidate_id": str(row.get("candidate_id", "")),
                "status": str(row.get("status", "")),
                "tlm_edp": _l2_metric(row, "tlm_edp"),
                "tlm_workflow_wall_time_ms": _l2_metric(row, "tlm_workflow_wall_time_ms"),
                "tlm_resource_pressure": _l2_metric(row, "tlm_resource_pressure"),
                "oracle_rank": int(oracle_rank.get(str(row.get("candidate_id", "")), len(oracle_rank) + 1)),
            }
            for row in result_rows
        ],
    }


def _policy_selected_row_summary(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "candidate_id": str(row.get("candidate_id", "")),
        "design_key": str(row.get("design_key", "")),
        "parameters": dict(row.get("parameters", {}) if isinstance(row.get("parameters"), Mapping) else {}),
        "metrics": dict(row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}),
    }


def _l2_oracle_rank_for_rows(
    manifest: Mapping[str, Any],
    problem_payload: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, int]:
    return _oracle_rank_from_l2_results(
        _l2_oracle_results_for_rows(
            manifest,
            problem_payload,
            rows,
            workflow_abstraction=workflow_abstraction,
            require_workflow_feature_contract=require_workflow_feature_contract,
        )
    )


def _adaptive_retrospective_oracle_report(
    *,
    manifest: Mapping[str, Any],
    problem_payload: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    budget_curve: List[Dict[str, Any]],
    final_result: Dict[str, Any],
    top_k: int,
    include_retrospective_oracle: bool,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    resolved_top_k = max(1, int(top_k))
    if not include_retrospective_oracle:
        return {
            "oracle_fidelity": "not_precomputed_in_method_loop",
            "method_loop_oracle_precomputed": False,
            "retrospective_oracle_computed_after_method_loop": False,
            "oracle_candidate_count": 0,
            "oracle_best_tlm_edp": None,
            "oracle_top_k": resolved_top_k,
            "rank_and_regret_status": "unavailable_without_retrospective_oracle",
            "retrospective_oracle_artifact": "qe_fpga_search_baseline_report.json",
        }

    oracle_results = _l2_oracle_results_for_rows(
        manifest,
        problem_payload,
        rows,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    oracle_rank = _oracle_rank_from_l2_results(oracle_results)
    passed_oracle_rows = [
        row for row in oracle_results.values()
        if isinstance(row, Mapping) and str(row.get("status", "")) == "passed"
    ]
    best_oracle = min(passed_oracle_rows, key=_l2_edp_sort_key, default={})
    oracle_best_edp = _l2_metric(best_oracle, "tlm_edp") if best_oracle else float("inf")
    oracle_status = "retrospective_l2_oracle_not_used_for_method_loop"

    for point in budget_curve:
        candidate_id = str(point.get("best_candidate_id") or "")
        oracle_row = oracle_results.get(candidate_id, {})
        oracle_edp = _l2_metric(oracle_row, "tlm_edp") if isinstance(oracle_row, Mapping) else float("inf")
        oracle_candidate_rank = oracle_rank.get(candidate_id)
        if candidate_id and oracle_candidate_rank is not None and math.isfinite(oracle_edp) and math.isfinite(oracle_best_edp):
            point["oracle_rank_of_best_so_far"] = int(oracle_candidate_rank)
            point["oracle_tlm_edp_of_best_so_far"] = _round_metric(oracle_edp)
            point["simple_regret"] = _round_metric(max(0.0, oracle_edp - oracle_best_edp))
            point["top_k_hit"] = bool(oracle_candidate_rank <= resolved_top_k)
            point["oracle_status"] = oracle_status
        else:
            point["oracle_rank_of_best_so_far"] = None
            point["oracle_tlm_edp_of_best_so_far"] = None
            point["simple_regret"] = None
            point["top_k_hit"] = None
            point["oracle_status"] = "retrospective_l2_oracle_missing_candidate"

    if budget_curve:
        final_point = budget_curve[-1]
        final_result["oracle_rank_of_best"] = final_point.get("oracle_rank_of_best_so_far")
        final_result["top_k_hit"] = final_point.get("top_k_hit")
        final_result["rank_basis"] = final_point.get("oracle_status") or oracle_status

    return {
        "oracle_fidelity": "L2_python_tlm",
        "method_loop_oracle_precomputed": False,
        "retrospective_oracle_computed_after_method_loop": True,
        "oracle_candidate_count": len(oracle_results),
        "oracle_best_candidate_id": str(best_oracle.get("candidate_id", "")) if best_oracle else "",
        "oracle_best_tlm_edp": _round_metric(oracle_best_edp) if math.isfinite(oracle_best_edp) else None,
        "oracle_top_k": resolved_top_k,
        "rank_and_regret_status": "retrospective_l2_oracle_available",
        "retrospective_oracle_artifact": "embedded_retrospective_l2_oracle_summary",
        "method_loop_separation": "oracle_computed_after_budget_limited_selection_trace_only_for_algorithm_evaluation",
    }


def _observation_objective(row: Mapping[str, Any]) -> float:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    fidelity = str(row.get("fidelity", ""))
    if fidelity == "L2_python_tlm":
        return _finite_float(metrics.get("tlm_edp"), default=float("inf"))
    calibrated = _finite_float(metrics.get("calibrated_common_objective_edp"), default=float("inf"))
    if math.isfinite(calibrated):
        return calibrated
    return _finite_float(metrics.get("observed_edp"), default=float("inf"))


def _active_search_observation_from_l2_result(
    result: Mapping[str, Any],
    *,
    source: str,
    prior_row: Mapping[str, Any] | None = None,
    workload_features: Mapping[str, Any] | None = None,
) -> ActiveSearchObservation | None:
    if not isinstance(result, Mapping) or str(result.get("status", "")) != "passed":
        return None
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), Mapping) else {}
    edp = _finite_float(metrics.get("tlm_edp"), default=float("inf"))
    if not math.isfinite(edp) or edp <= 0.0:
        return None
    latency_default = math.sqrt(edp)
    latency = _finite_float(metrics.get("tlm_workflow_wall_time_ms"), default=latency_default)
    energy = _finite_float(
        metrics.get("tlm_energy_mj"),
        default=(edp / latency) if latency > 0.0 and math.isfinite(latency) else math.sqrt(edp),
    )
    metadata = {
        "source": str(source),
        "status": str(result.get("status", "")),
        "raw_fidelity": str(result.get("fidelity", "L2_python_tlm")),
        "common_objective_edp": _round_metric(edp),
    }
    metadata.update(_active_search_prior_metadata(prior_row, workload_features or {}))
    return ActiveSearchObservation(
        candidate_id=str(result.get("candidate_id", "")),
        fidelity=_canonical_qe_fpga_action_fidelity(str(result.get("fidelity", "L2_python_tlm"))),
        objectives={
            "estimated_workflow_wall_time_ms": latency,
            "estimated_energy_mj": energy,
            "estimated_edp": edp,
            "fpga_resource_pressure": _finite_float(metrics.get("tlm_resource_pressure"), default=0.0),
            "estimated_data_movement_mb": _finite_float(metrics.get("tlm_data_movement_mb"), default=0.0),
            "infeasibility_penalty": 0.0,
        },
        feasible=True,
        metadata=metadata,
    )


def _active_search_observation_from_external_feedback(
    result: Mapping[str, Any],
    *,
    source: str,
    prior_row: Mapping[str, Any] | None = None,
    workload_features: Mapping[str, Any] | None = None,
) -> ActiveSearchObservation | None:
    if not isinstance(result, Mapping) or str(result.get("status", "passed")) != "passed":
        return None
    if not _observation_common_objective_eligible(result):
        return None
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), Mapping) else {}
    edp = _finite_float(metrics.get("calibrated_common_objective_edp"), default=float("inf"))
    if not math.isfinite(edp) or edp <= 0.0:
        return None
    latency = _finite_float(
        metrics.get("observed_workflow_wall_time_ms"),
        default=math.sqrt(edp),
    )
    energy = _finite_float(
        metrics.get("observed_energy_mj"),
        default=(edp / latency) if latency > 0.0 and math.isfinite(latency) else math.sqrt(edp),
    )
    metadata = {
        "source": str(source),
        "sample_id": str(result.get("sample_id", "")),
        "status": str(result.get("status", "")),
        "raw_fidelity": str(result.get("fidelity", "external_high_fidelity")),
        "calibrated_common_objective_edp": _round_metric(edp),
        "raw_observed_edp": _round_metric(_finite_float(metrics.get("observed_edp"), default=float("nan"))),
        "calibration": dict(result.get("calibration", {}) if isinstance(result.get("calibration"), Mapping) else {}),
    }
    metadata.update(_active_search_prior_metadata(prior_row, workload_features or {}))
    return ActiveSearchObservation(
        candidate_id=str(result.get("candidate_id", "")),
        fidelity=_canonical_qe_fpga_action_fidelity(str(result.get("fidelity", "external_high_fidelity"))),
        objectives={
            "estimated_workflow_wall_time_ms": latency,
            "estimated_energy_mj": energy,
            "estimated_edp": edp,
            "fpga_resource_pressure": _finite_float(metrics.get("observed_resource_pressure"), default=0.0),
            "estimated_data_movement_mb": _finite_float(metrics.get("observed_data_movement_mb"), default=0.0),
            "infeasibility_penalty": 0.0,
        },
        feasible=True,
        metadata=metadata,
    )


def _active_search_prior_metadata(
    prior_row: Mapping[str, Any] | None,
    workload_features: Mapping[str, Any],
) -> Dict[str, Any]:
    if not isinstance(prior_row, Mapping):
        return {}
    candidate = _active_search_candidate_from_qe_row(prior_row, workload_features)
    return {
        "prior_objectives": dict(candidate.objectives),
        "prior_risk_axes": dict(candidate.risk_axes),
        "prior_categorical_features": dict(
            candidate.metadata.get("categorical_features", {})
            if isinstance(candidate.metadata.get("categorical_features"), Mapping)
            else {}
        ),
        "prior_design_key": candidate.design_key,
        "prior_evaluation_cost": _round_metric(candidate.evaluation_cost),
    }


def _active_search_observations_from_external_feedback_samples(
    samples: Sequence[Mapping[str, Any]],
    *,
    prior_rows_by_candidate: Mapping[str, Mapping[str, Any]] | None = None,
    workload_features: Mapping[str, Any] | None = None,
) -> List[ActiveSearchObservation]:
    observations: List[ActiveSearchObservation] = []
    seen: set[str] = set()
    for sample in samples:
        candidate_id = str(sample.get("candidate_id", "")) if isinstance(sample, Mapping) else ""
        observation = _active_search_observation_from_external_feedback(
            sample,
            source="external_common_objective_feedback",
            prior_row=(
                prior_rows_by_candidate.get(candidate_id, {})
                if isinstance(prior_rows_by_candidate, Mapping)
                else None
            ),
            workload_features=workload_features or {},
        )
        if observation is None or observation.candidate_id in seen:
            continue
        observations.append(observation)
        seen.add(observation.candidate_id)
    return observations


def _observation_sort_key(row: Mapping[str, Any]) -> Tuple[float, str, str]:
    return (
        _observation_objective(row),
        str(row.get("fidelity", "")),
        str(row.get("candidate_id", "")),
    )


def _observation_common_objective_eligible(row: Mapping[str, Any]) -> bool:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    fidelity = str(row.get("fidelity", ""))
    if fidelity == "L2_python_tlm":
        return _finite_float(metrics.get("tlm_edp"), default=0.0) > 0.0
    calibration = row.get("calibration", {}) if isinstance(row.get("calibration"), Mapping) else {}
    if calibration.get("common_objective_eligible") is not True:
        return False
    return _observation_objective(row) > 0.0


def _adaptive_observation_payload(observation: Mapping[str, Any]) -> Dict[str, Any]:
    payload = {
        "fidelity": str(observation.get("fidelity", "L2_python_tlm")),
        "status": str(observation.get("status", "")),
        "metrics": dict(observation.get("metrics", {}) if isinstance(observation.get("metrics"), Mapping) else {}),
        "oracle_rank": None,
        "rank_basis": "not_available_without_retrospective_oracle",
        "tool_status": observation.get("tool_status"),
        "provenance": dict(observation.get("provenance", {}) if isinstance(observation.get("provenance"), Mapping) else {}),
        "common_objective_eligible": _observation_common_objective_eligible(observation),
    }
    if isinstance(observation.get("calibration"), Mapping):
        payload["calibration"] = dict(observation.get("calibration", {}))
    return payload


def _l2_oracle_results_for_rows(
    manifest: Mapping[str, Any],
    problem_payload: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Dict[str, Any]]:
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem_payload,
        rows,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    results = run_qe_fpga_l2_tlm_requests(bundle)
    return {
        str(row.get("candidate_id", "")): dict(row)
        for row in results.get("results", []) or []
        if isinstance(row, Mapping)
    }


def _oracle_rank_from_l2_results(results_by_candidate: Mapping[str, Mapping[str, Any]]) -> Dict[str, int]:
    sorted_rows = sorted(
        [row for row in results_by_candidate.values() if isinstance(row, Mapping)],
        key=_l2_edp_sort_key,
    )
    ranks: Dict[str, int] = {}
    previous_edp: float | None = None
    current_rank = 0
    for index, row in enumerate(sorted_rows):
        edp = _l2_metric(row, "tlm_edp")
        if previous_edp is None or not _same_metric_value(edp, previous_edp):
            current_rank = index + 1
            previous_edp = edp
        ranks[str(row.get("candidate_id", ""))] = current_rank
    return ranks


def _evaluate_single_l2_row(
    manifest: Mapping[str, Any],
    problem_payload: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    workflow_abstraction: Mapping[str, Any] | None = None,
    require_workflow_feature_contract: bool = False,
) -> Dict[str, Any]:
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem_payload,
        [row],
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=require_workflow_feature_contract,
    )
    results = run_qe_fpga_l2_tlm_requests(bundle)
    result_rows = [item for item in results.get("results", []) or [] if isinstance(item, Mapping)]
    return dict(result_rows[0]) if result_rows else {}


def _normalize_external_feedback_samples(
    samples: Sequence[Mapping[str, Any]],
    *,
    allowed_candidate_ids: set[str],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    normalized_by_candidate: Dict[str, Dict[str, Any]] = {}
    rejected: List[Dict[str, Any]] = []
    provided = 0
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            rejected.append({"index": index, "reason": "sample_not_object"})
            continue
        provided += 1
        candidate_id = str(sample.get("candidate_id", ""))
        if not candidate_id or candidate_id not in allowed_candidate_ids:
            rejected.append({"index": index, "candidate_id": candidate_id, "reason": "candidate_id_not_in_release_candidates"})
            continue
        feedback_rejection = _external_feedback_rejection_reason(sample)
        if feedback_rejection:
            rejected.append({"index": index, "candidate_id": candidate_id, "reason": feedback_rejection})
            continue
        metrics = sample.get("metrics", {}) if isinstance(sample.get("metrics"), Mapping) else {}
        edp = _feedback_metric(metrics, "observed_edp", "edp", "tlm_edp")
        latency = _feedback_metric(metrics, "tlm_workflow_wall_time_ms", "workflow_wall_time_ms", "latency_ms")
        energy = _feedback_metric(metrics, "tlm_energy_mj", "energy_mj")
        resource = _feedback_metric(metrics, "tlm_resource_pressure", "resource_pressure")
        data_movement = _feedback_metric(
            metrics,
            "observed_data_movement_mb",
            "tlm_data_movement_mb",
            "data_movement_mb",
        )
        if edp <= 0.0:
            if latency > 0.0 and energy > 0.0:
                edp = latency * energy
            else:
                rejected.append({"index": index, "candidate_id": candidate_id, "reason": "missing_positive_edp_or_latency_energy"})
                continue
        if latency <= 0.0 and energy > 0.0:
            latency = edp / energy
        if energy <= 0.0 and latency > 0.0:
            energy = edp / latency
        calibration = _normalize_external_feedback_calibration(sample)
        calibrated_edp = _calibrated_common_objective_edp(edp, calibration)
        normalized = {
            "schema_version": "dse.qe_fpga_external_feedback_observation.v1",
            "sample_id": str(sample.get("sample_id") or f"external_feedback_{index:03d}"),
            "candidate_id": candidate_id,
            "design_key": str(sample.get("design_key", "")),
            "status": str(sample.get("status", "passed")),
            "tool_status": sample.get("tool_status", sample.get("status", "passed")),
            "fidelity": str(sample.get("fidelity") or sample.get("source_fidelity") or "external_high_fidelity"),
            "metrics": {
                "observed_workflow_wall_time_ms": _round_metric(latency),
                "observed_energy_mj": _round_metric(energy),
                "observed_edp": _round_metric(edp),
                **(
                    {"calibrated_common_objective_edp": _round_metric(calibrated_edp)}
                    if math.isfinite(calibrated_edp)
                    else {}
                ),
                "observed_resource_pressure": _round_metric(max(0.0, resource)),
                "observed_data_movement_mb": _round_metric(max(0.0, data_movement)),
            },
            "calibration": calibration,
            "provenance": dict(sample.get("provenance", {}) if isinstance(sample.get("provenance"), Mapping) else {}),
            "claim_boundary": "external_feedback_observation_for_adaptive_search_only_not_self_sufficient_hardware_claim",
        }
        normalized_by_candidate[candidate_id] = normalized
    fidelities = sorted({str(row.get("fidelity", "")) for row in normalized_by_candidate.values() if row.get("fidelity")})
    return normalized_by_candidate, {
        "provided_sample_count": provided,
        "usable_sample_count": len(normalized_by_candidate),
        "rejected_sample_count": len(rejected),
        "fidelities": fidelities,
        "rejected_samples": rejected,
        "claim_boundary": "external_feedback_summary_only_samples_must_be_adjudicated_before_hardware_results",
    }


def _normalize_external_feedback_calibration(sample: Mapping[str, Any]) -> Dict[str, Any]:
    calibration = sample.get("calibration", {}) if isinstance(sample.get("calibration"), Mapping) else {}
    provenance = sample.get("provenance", {}) if isinstance(sample.get("provenance"), Mapping) else {}
    paired_samples = int(_finite_float(calibration.get("paired_sample_count"), default=0.0))
    common_metric = str(calibration.get("common_objective_metric", ""))
    artifact_ref = str(calibration.get("calibration_artifact", ""))
    artifact_hash = str(
        calibration.get("calibration_artifact_sha256")
        or calibration.get("calibration_artifact_hash")
        or provenance.get("calibration_artifact_sha256")
        or provenance.get("calibration_artifact_hash")
        or ""
    )
    declared_common_objective_calibration = (
        calibration.get("common_objective_eligible") is True
        or str(calibration.get("status", "")) in {"calibrated_common_objective", "calibrated_to_l2_common_objective"}
        or bool(common_metric)
    )
    blockers: List[str] = []
    if declared_common_objective_calibration:
        if not artifact_ref:
            blockers.append("missing_calibration_artifact")
        if not _is_sha256_ref(artifact_hash):
            blockers.append("missing_calibration_artifact_hash")
    calibrated = (
        calibration.get("common_objective_eligible") is True
        and str(calibration.get("status", "")) in {"calibrated_common_objective", "calibrated_to_l2_common_objective"}
        and common_metric in {"observed_edp", "edp", "tlm_edp"}
        and paired_samples > 0
        and math.isfinite(_finite_float(calibration.get("scale"), default=float("nan")))
        and math.isfinite(_finite_float(calibration.get("bias"), default=float("nan")))
        and math.isfinite(_finite_float(calibration.get("noise_edp_cv"), default=float("nan")))
        and not blockers
    )
    if not calibrated:
        if blockers:
            return {
                "status": "unverified_external_calibration",
                "common_objective_eligible": False,
                "required_before_l2_raw_metric_mixing": "verified_cross_fidelity_calibration_artifact_with_hash",
                "calibration_artifact": artifact_ref,
                "calibration_artifact_sha256": artifact_hash,
                "blockers": blockers,
            }
        return {
            "status": "uncalibrated_external_fidelity",
            "common_objective_eligible": False,
            "required_before_l2_raw_metric_mixing": "paired_cross_fidelity_scale_bias_noise_calibration",
        }
    return {
        "status": str(calibration.get("status")),
        "common_objective_eligible": True,
        "common_objective_metric": common_metric,
        "paired_sample_count": paired_samples,
        "scale": _round_metric(_finite_float(calibration.get("scale"), default=1.0)),
        "bias": _round_metric(_finite_float(calibration.get("bias"), default=0.0)),
        "noise_edp_cv": _round_metric(_finite_float(calibration.get("noise_edp_cv"), default=0.0)),
        "calibration_artifact": artifact_ref,
        "calibration_artifact_sha256": artifact_hash,
    }


def _calibrated_common_objective_edp(raw_edp: float, calibration: Mapping[str, Any]) -> float:
    if calibration.get("common_objective_eligible") is not True:
        return float("nan")
    scale = _finite_float(calibration.get("scale"), default=float("nan"))
    bias = _finite_float(calibration.get("bias"), default=float("nan"))
    if not math.isfinite(scale) or not math.isfinite(bias):
        return float("nan")
    return max(1.0e-9, scale * raw_edp + bias)


def _is_sha256_ref(value: str) -> bool:
    text = str(value or "")
    if text.startswith("sha256:"):
        text = text[len("sha256:"):]
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", text))


def _external_feedback_rejection_reason(sample: Mapping[str, Any]) -> str | None:
    fidelity = str(sample.get("fidelity") or sample.get("source_fidelity") or "")
    if fidelity != "HLS_c_synthesis":
        return None
    classification = sample.get("tool_evidence_classification")
    provenance = sample.get("provenance", {}) if isinstance(sample.get("provenance"), Mapping) else {}
    if not isinstance(classification, Mapping):
        tool = str(provenance.get("tool", ""))
        classification = _classify_hls_tool_evidence(tool) if tool else {}
    if (
        classification.get("classification") != "real_hls_tool"
        or not bool(classification.get("allowed_feedback_use", False))
        or not isinstance(classification.get("identity_probe"), Mapping)
        or not bool(classification.get("identity_probe", {}).get("accepted", False))
    ):
        return "hls_feedback_not_real_tool_evidence"
    return None


def _feedback_metric(metrics: Mapping[str, Any], *names: str) -> float:
    for name in names:
        if name in metrics:
            return _finite_float(metrics.get(name), default=0.0)
    return 0.0


def _adaptive_feature_names() -> List[str]:
    return [
        "bias",
        "l1_log_edp",
        "l1_resource_pressure",
        "l1_data_movement_mb",
        "host_control_intensity",
        "post_processing_intensity",
        "hbm_memory",
        "workflow_boundary",
    ]


def _initial_adaptive_surrogate(feature_names: Sequence[str]) -> Dict[str, Any]:
    return {
        "feature_names": list(feature_names),
        "coefficients": {str(name): 0.0 for name in feature_names},
        "mean_residual": 0.0,
        "residual_m2": 0.0,
        "training_sample_count": 0,
        "updates": 0,
        "last_abs_percent_error": None,
    }


def _adaptive_surrogate_summary(model_state: Mapping[str, Any]) -> Dict[str, Any]:
    sample_count = int(model_state.get("training_sample_count", 0))
    residual_m2 = _finite_float(model_state.get("residual_m2"), default=0.0)
    residual_std = math.sqrt(residual_m2 / max(1, sample_count - 1)) if sample_count > 1 else 0.0
    return {
        "model_type": "online_linear_residual_surrogate",
        "feature_names": list(model_state.get("feature_names", []) or []),
        "training_sample_count": sample_count,
        "updates": int(model_state.get("updates", 0)),
        "mean_residual": _round_metric(_finite_float(model_state.get("mean_residual"), default=0.0)),
        "residual_std": _round_metric(residual_std),
        "last_abs_percent_error": model_state.get("last_abs_percent_error"),
    }


def _adaptive_initial_seed_rows(
    l1_screening: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    seed_count: int,
    workload_features: Mapping[str, Any],
) -> List[Mapping[str, Any]]:
    queue = [
        row for row in l1_screening.get("promotion_queue", []) or []
        if isinstance(row, Mapping)
    ]
    selected: List[Mapping[str, Any]] = []
    selected_ids: set[str] = set()
    for row in queue:
        candidate_id = str(row.get("candidate_id", ""))
        if candidate_id and candidate_id not in selected_ids:
            selected.append(row)
            selected_ids.add(candidate_id)
        if len(selected) >= seed_count:
            return selected
    for row in sorted(rows, key=lambda item: _risk_aware_promotion_sort_key(item, workload_features)):
        candidate_id = str(row.get("candidate_id", ""))
        if candidate_id and candidate_id not in selected_ids:
            selected.append(row)
            selected_ids.add(candidate_id)
        if len(selected) >= seed_count:
            break
    return selected


def _initial_seed_acquisition(row: Mapping[str, Any], step_index: int) -> Dict[str, Any]:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    predicted = _finite_float(metrics.get("estimated_edp"), default=float("inf"))
    return {
        "score": _round_metric(1.0 / max(predicted, 1.0)),
        "components": {
            "predicted_edp": _round_metric(predicted),
            "uncertainty": 0.0,
            "expected_improvement": 0.0,
            "diversity_bonus": _round_metric(1.0 / float(step_index + 1)),
            "evaluation_cost": 1.0,
        },
        "policy": "initial_diverse_l1_seed",
    }


def _select_adaptive_candidate(
    rows: Sequence[Mapping[str, Any]],
    *,
    evaluated_ids: set[str],
    model_state: Mapping[str, Any],
    workload_features: Mapping[str, Any],
) -> Tuple[Mapping[str, Any], Dict[str, Any]]:
    remaining = [
        row for row in rows
        if str(row.get("candidate_id", "")) not in evaluated_ids
    ]
    if not remaining:
        return {}, {"score": 0.0, "components": {}, "policy": "no_remaining_candidates"}
    evaluated_axis_values = _evaluated_axis_values(rows, evaluated_ids)
    best_observed_proxy = _finite_float(model_state.get("best_observed_edp"), default=float("inf"))
    scored: List[Tuple[float, Mapping[str, Any], Dict[str, Any]]] = []
    for row in remaining:
        generic = _generic_active_acquisition_for_row(
            row,
            rows=rows,
            evaluated_ids=evaluated_ids,
            workload_features=workload_features,
        )
        predicted = _adaptive_predict_edp(row, model_state, workload_features)
        uncertainty = _adaptive_uncertainty(row, model_state, workload_features)
        expected_improvement = max(0.0, best_observed_proxy - predicted)
        diversity_bonus = _adaptive_diversity_bonus(row, evaluated_axis_values)
        evaluation_cost = _adaptive_evaluation_cost(row)
        local_score = (
            expected_improvement
            + 0.15 * uncertainty
            + 0.04 * max(predicted, 1.0) * diversity_bonus
        ) / max(evaluation_cost, 1.0e-9)
        if local_score <= 0.0:
            local_score = (uncertainty + max(predicted, 1.0) * diversity_bonus * 0.02) / max(evaluation_cost, 1.0e-9)
        components = {
            "predicted_edp": _round_metric(predicted),
            "uncertainty": _round_metric(uncertainty),
            "expected_improvement": _round_metric(expected_improvement),
            "diversity_bonus": _round_metric(diversity_bonus),
            "evaluation_cost": _round_metric(evaluation_cost),
            **_generic_acquisition_component_aliases(generic),
        }
        score = _combine_generic_and_local_acquisition_scores(generic, local_score)
        scored.append((score, row, components))
    score, selected, components = max(
        scored,
        key=lambda item: (
            item[0],
            -_finite_float(item[1].get("metrics", {}).get("estimated_edp") if isinstance(item[1].get("metrics"), Mapping) else None, default=float("inf")),
            str(item[1].get("candidate_id", "")),
        ),
    )
    return selected, {
        "score": _round_metric(score),
        "components": components,
        "policy": "cost_aware_ucb_expected_improvement_hybrid",
        "generic_kernel_policy": "wamf_constrained_active_pareto",
        "generic_kernel_frontier_source": str(components.get("generic_frontier_source", "")),
    }


def _update_adaptive_surrogate(
    model_state: Mapping[str, Any],
    row: Mapping[str, Any],
    observation: Mapping[str, Any],
    workload_features: Mapping[str, Any],
) -> Dict[str, Any]:
    updated = copy.deepcopy(dict(model_state))
    predicted = _adaptive_predict_edp(row, updated, workload_features)
    observed = _observation_objective(observation)
    l1_edp = _finite_float(row.get("metrics", {}).get("estimated_edp") if isinstance(row.get("metrics"), Mapping) else None, default=predicted)
    residual = observed - l1_edp
    sample_count = int(updated.get("training_sample_count", 0)) + 1
    old_mean = _finite_float(updated.get("mean_residual"), default=0.0)
    delta = residual - old_mean
    new_mean = old_mean + delta / float(sample_count)
    updated["mean_residual"] = new_mean
    updated["residual_m2"] = _finite_float(updated.get("residual_m2"), default=0.0) + delta * (residual - new_mean)
    updated["training_sample_count"] = sample_count
    updated["updates"] = int(updated.get("updates", 0)) + 1
    updated["best_observed_edp"] = min(
        _finite_float(updated.get("best_observed_edp"), default=float("inf")),
        observed,
    )
    features = _adaptive_feature_vector(row, workload_features)
    coefficients = dict(updated.get("coefficients", {}) if isinstance(updated.get("coefficients"), Mapping) else {})
    error = observed - predicted
    learning_rate = 0.025 / math.sqrt(float(sample_count))
    scale = max(1.0, abs(observed), abs(predicted))
    normalized_error = max(-1.0, min(1.0, error / scale))
    for name, value in features.items():
        coefficients[name] = _finite_float(coefficients.get(name), default=0.0) + learning_rate * normalized_error * value
    updated["coefficients"] = coefficients
    updated["last_abs_percent_error"] = _round_metric(_ape_percent(predicted, observed))
    return updated


def _adaptive_predict_edp(
    row: Mapping[str, Any],
    model_state: Mapping[str, Any],
    workload_features: Mapping[str, Any],
) -> float:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    l1_edp = _finite_float(metrics.get("estimated_edp"), default=1.0)
    coefficients = model_state.get("coefficients", {}) if isinstance(model_state.get("coefficients"), Mapping) else {}
    features = _adaptive_feature_vector(row, workload_features)
    residual = _finite_float(model_state.get("mean_residual"), default=0.0)
    residual += sum(
        _finite_float(coefficients.get(name), default=0.0) * value * max(1.0, l1_edp) * 0.05
        for name, value in features.items()
    )
    return max(1.0, l1_edp + residual)


def _adaptive_feature_vector(row: Mapping[str, Any], workload_features: Mapping[str, Any]) -> Dict[str, float]:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    params = _candidate_parameters(row)
    l1_edp = max(1.0, _finite_float(metrics.get("estimated_edp"), default=1.0))
    return {
        "bias": 1.0,
        "l1_log_edp": math.log(l1_edp),
        "l1_resource_pressure": _finite_float(metrics.get("fpga_resource_pressure"), default=0.0),
        "l1_data_movement_mb": math.log1p(_finite_float(metrics.get("estimated_data_movement_mb"), default=0.0)),
        "host_control_intensity": _finite_float(workload_features.get("host_control_intensity"), default=0.0),
        "post_processing_intensity": _finite_float(workload_features.get("post_processing_intensity"), default=0.0),
        "hbm_memory": 1.0 if params.get("memory_topology") == "hbm_multi_channel" else 0.0,
        "workflow_boundary": 1.0 if params.get("offload_boundary") == "workflow_hotspot_bundle" else 0.0,
    }


def _adaptive_uncertainty(
    row: Mapping[str, Any],
    model_state: Mapping[str, Any],
    workload_features: Mapping[str, Any],
) -> float:
    summary = _adaptive_surrogate_summary(model_state)
    sample_count = int(summary.get("training_sample_count", 0))
    residual_std = _finite_float(summary.get("residual_std"), default=0.0)
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    l1_edp = _finite_float(metrics.get("estimated_edp"), default=1.0)
    params = _candidate_parameters(row)
    novelty = 0.0
    if params.get("memory_topology") == "hbm_multi_channel":
        novelty += 0.04
    if params.get("offload_boundary") == "workflow_hotspot_bundle":
        novelty += 0.04
    novelty += _finite_float(workload_features.get("host_control_intensity"), default=0.0) * 0.03
    cold_start = 0.12 / math.sqrt(float(max(1, sample_count)))
    return max(1.0, residual_std + l1_edp * (cold_start + novelty))


def _adaptive_diversity_bonus(row: Mapping[str, Any], evaluated_axis_values: Mapping[str, set[str]]) -> float:
    params = _candidate_parameters(row)
    axes = ("architecture_template", "offload_boundary", "runtime_schedule", "data_residency", "memory_topology")
    unseen = sum(1 for axis in axes if str(params.get(axis, "")) not in evaluated_axis_values.get(axis, set()))
    return unseen / float(len(axes))


def _adaptive_evaluation_cost(row: Mapping[str, Any]) -> float:
    params = _candidate_parameters(row)
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    cost = 1.0
    if params.get("memory_topology") == "hbm_multi_channel":
        cost += 0.15
    if params.get("offload_boundary") == "workflow_hotspot_bundle":
        cost += 0.12
    cost += min(0.40, _finite_float(metrics.get("fpga_resource_pressure"), default=0.0) * 0.25)
    return cost


def _neural_feature_schema() -> Dict[str, Any]:
    return {
        "schema_version": "dse.qe_fpga.neural_surrogate_feature_schema.v1",
        "workload_feature_names": [
            "host_control_intensity",
            "post_processing_intensity",
            "variant_data_scale",
            "stage_count",
            "workflow_dependency_edge_count",
            "data_artifact_count",
            "graph_node_count",
            "graph_edge_count",
            "source_fact_count",
            "estimated_workflow_data_volume_mb",
            "estimated_wavefunction_mb",
            "estimated_charge_density_mb",
            "max_nbnd",
            "max_npw",
            "max_nfft",
            "max_kpoint_count",
            "scf_iteration_count_observed",
            "host_control_event_counts.scf_convergence_check_count",
            "host_control_event_counts.post_processing_stage_count",
            "host_control_event_counts.io_checkpoint_event_count",
            "data_object_lifetime.hot_reuse_object_count",
            "data_object_lifetime.checkpoint_object_count",
            "data_object_lifetime.workflow_boundary_object_count",
            "data_object_lifetime.estimated_hot_object_bytes",
            "graph_node_count",
            "graph_edge_count",
            "graph_host_node_count",
            "graph_accelerator_node_count",
            "graph_host_node_ratio",
            "graph_accelerator_node_ratio",
            "graph_control_edge_count",
            "graph_data_edge_count",
            "graph_state_edge_count",
            "graph_inter_stage_edge_count",
            "graph_inter_stage_edge_ratio",
            "graph_max_in_degree",
            "graph_max_out_degree",
            "graph_mean_in_degree",
            "graph_mean_out_degree",
            "graph_density",
        ],
        "candidate_parameter_names": [
            "architecture_template",
            "offload_boundary",
            "mapping_granularity",
            "runtime_schedule",
            "data_residency",
            "memory_topology",
            "vector_lanes",
            "hbm_channel_count",
            "tile_doubles",
        ],
        "l1_metric_feature_names": [
            "estimated_workflow_wall_time_ms",
            "estimated_energy_mj",
            "estimated_edp",
            "estimated_data_movement_mb",
            "fpga_resource_pressure",
            "implementation_feasibility",
        ],
        "categorical_encoding": "stable_hash_bucket_features_for_tabular_backend",
        "graph_backend_contract": "graph-aware scalar features map to heterogeneous_qe_workflow_candidate_graph nodes, edges, data objects, and candidate knobs",
    }


def _initial_neural_surrogate(feature_schema: Mapping[str, Any], *, ensemble_size: int) -> Dict[str, Any]:
    return {
        "feature_schema": copy.deepcopy(dict(feature_schema)),
        "ensemble_size": max(3, int(ensemble_size)),
        "training_sample_count": 0,
        "updates": 0,
        "residuals": [],
        "best_observed_edp": float("inf"),
        "rank_training_pairs": 0,
        "uncertainty_calibrated": False,
    }


def _neural_surrogate_summary(model_state: Mapping[str, Any]) -> Dict[str, Any]:
    residuals = [
        _finite_float(value, default=float("nan"))
        for value in model_state.get("residuals", []) or []
    ]
    residuals = [value for value in residuals if math.isfinite(value)]
    sample_count = int(model_state.get("training_sample_count", 0))
    trained_use = (
        model_state.get("trained_surrogate_use", {})
        if isinstance(model_state.get("trained_surrogate_use"), Mapping)
        else {}
    )
    trained_surrogate = (
        model_state.get("trained_surrogate", {})
        if isinstance(model_state.get("trained_surrogate"), Mapping)
        else {}
    )
    if trained_use.get("status") == "enabled":
        backend = trained_surrogate.get("backend", {}) if isinstance(trained_surrogate.get("backend"), Mapping) else {}
        dataset = trained_surrogate.get("dataset", {}) if isinstance(trained_surrogate.get("dataset"), Mapping) else {}
        uncertainty = trained_surrogate.get("uncertainty", {}) if isinstance(trained_surrogate.get("uncertainty"), Mapping) else {}
        return {
            "model_type": "trained_tabular_mlp_deep_ensemble_surrogate",
            "training_sample_count": int(dataset.get("sample_count", 0)),
            "updates": int(model_state.get("updates", 0)),
            "ensemble_size": int(backend.get("ensemble_size", model_state.get("ensemble_size", 0))),
            "rank_training_pairs": int(model_state.get("rank_training_pairs", 0)),
            "uncertainty_calibrated": str(uncertainty.get("calibration_status", "")).startswith("interval_coverage"),
            "uncertainty_method": str(uncertainty.get("method", "deep_ensemble_prediction_std")),
            "trained_surrogate_artifact": "qe_fpga_neural_surrogate_training_report.json",
            "source_schema_version": str(trained_surrogate.get("schema_version", "")),
            "claim_boundary": "surrogate_contract_state_only_not_validated_predictor",
        }
    return {
        "model_type": "bootstrap_tabular_residual_rank_surrogate",
        "training_sample_count": sample_count,
        "updates": int(model_state.get("updates", 0)),
        "ensemble_size": int(model_state.get("ensemble_size", 0)),
        "rank_training_pairs": int(model_state.get("rank_training_pairs", 0)),
        "uncertainty_calibrated": bool(model_state.get("uncertainty_calibrated", False)),
        "residual_rmse": _round_metric(math.sqrt(_mean([value * value for value in residuals])) if residuals else 0.0),
        "residual_std": _round_metric(_stddev(residuals)),
        "replaceable_backends": [
            "heterogeneous_gnn_workload_candidate_encoder",
            "deep_ensemble_uncertainty_backend",
            "gradient_boosted_tree_ranker_backend",
        ],
        "claim_boundary": "surrogate_contract_state_only_not_validated_predictor",
    }


def _neural_initial_design_rows(
    l1_screening: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    seed_count: int,
    workload_features: Mapping[str, Any],
) -> List[Mapping[str, Any]]:
    selected: List[Mapping[str, Any]] = []
    selected_ids: set[str] = set()
    for row in _adaptive_initial_seed_rows(l1_screening, rows, seed_count, workload_features):
        candidate_id = str(row.get("candidate_id", ""))
        if candidate_id and candidate_id not in selected_ids:
            selected.append(row)
            selected_ids.add(candidate_id)
        if len(selected) >= seed_count:
            return selected
    evaluated_axis_values = _evaluated_axis_values(rows, selected_ids)
    remaining = [
        row for row in rows
        if str(row.get("candidate_id", "")) not in selected_ids
    ]
    remaining.sort(
        key=lambda row: (
            -_adaptive_diversity_bonus(row, evaluated_axis_values),
            _risk_aware_promotion_sort_key(row, workload_features),
        )
    )
    for row in remaining:
        if len(selected) >= seed_count:
            break
        selected.append(row)
    return selected


def _neural_initial_acquisition(row: Mapping[str, Any], step_index: int) -> Dict[str, Any]:
    prediction = _neural_predict(row, _initial_neural_surrogate(_neural_feature_schema(), ensemble_size=3), {})
    return {
        "score": _round_metric(1.0 / max(prediction["predicted_edp_mean"], 1.0)),
        "components": {
            "predicted_edp_mean": _round_metric(prediction["predicted_edp_mean"]),
            "predicted_edp_std": _round_metric(prediction["predicted_edp_std"]),
            "expected_improvement": 0.0,
            "top_k_probability": 0.0,
            "pareto_gain": _round_metric(1.0 / float(step_index + 1)),
            "feasibility_risk": _round_metric(prediction["feasibility_risk"]),
            "evaluation_cost": _round_metric(prediction["evaluation_cost"]),
        },
        "policy": "coverage_diverse_initial_design",
    }


def _select_neural_candidate(
    rows: Sequence[Mapping[str, Any]],
    *,
    evaluated_ids: set[str],
    model_state: Mapping[str, Any],
    workload_features: Mapping[str, Any],
) -> Tuple[Mapping[str, Any], Dict[str, Any]]:
    remaining = [
        row for row in rows
        if str(row.get("candidate_id", "")) not in evaluated_ids
    ]
    if not remaining:
        return {}, {"score": 0.0, "components": {}, "policy": "no_remaining_candidates"}
    best_observed = _finite_float(model_state.get("best_observed_edp"), default=float("inf"))
    evaluated_axis_values = _evaluated_axis_values(rows, evaluated_ids)
    scored: List[Tuple[float, Mapping[str, Any], Dict[str, Any]]] = []
    trained_enabled = _trained_surrogate_enabled(model_state)
    for row in remaining:
        generic = _generic_active_acquisition_for_row(
            row,
            rows=rows,
            evaluated_ids=evaluated_ids,
            workload_features=workload_features,
        )
        prediction = _neural_predict(row, model_state, workload_features)
        expected_improvement = max(0.0, best_observed - prediction["predicted_edp_mean"])
        top_k_probability = _neural_top_k_probability(prediction, row)
        design_diversity = _adaptive_diversity_bonus(row, evaluated_axis_values)
        workflow_risk_coverage = _workflow_risk_coverage(row, workload_features)
        pareto_gain = design_diversity + max(
            0.0,
            1.0 - prediction["feasibility_risk"],
        ) * 0.25
        constrained_ehvi = _approx_constrained_expected_hypervolume_improvement(
            row,
            prediction,
            best_observed=best_observed,
            workflow_risk_coverage=workflow_risk_coverage,
        )
        local_score = (
            constrained_ehvi
            + prediction["predicted_edp_std"] * 0.20
            + prediction["predicted_edp_mean"] * top_k_probability * 0.05
            + prediction["predicted_edp_mean"] * workflow_risk_coverage * 0.03
            + prediction["predicted_edp_mean"] * design_diversity * 0.02
        ) / max(prediction["evaluation_cost"] * (1.0 + prediction["feasibility_risk"]), 1.0e-9)
        components = {
            "predicted_edp_mean": _round_metric(prediction["predicted_edp_mean"]),
            "predicted_edp_std": _round_metric(prediction["predicted_edp_std"]),
            "constrained_expected_hypervolume_improvement": _round_metric(constrained_ehvi),
            "expected_improvement": _round_metric(expected_improvement),
            "top_k_probability": _round_metric(top_k_probability),
            "pareto_gain": _round_metric(pareto_gain),
            "workflow_risk_coverage": _round_metric(workflow_risk_coverage),
            "design_diversity": _round_metric(design_diversity),
            "feasibility_risk": _round_metric(prediction["feasibility_risk"]),
            "evaluation_cost": _round_metric(prediction["evaluation_cost"]),
            **_generic_acquisition_component_aliases(generic),
        }
        score = _combine_generic_and_local_acquisition_scores(generic, local_score)
        scored.append((score, row, components))
    score, selected, components = max(
        scored,
        key=lambda item: (
            item[0],
            -_finite_float(item[1].get("metrics", {}).get("estimated_edp") if isinstance(item[1].get("metrics"), Mapping) else None, default=float("inf")),
            str(item[1].get("candidate_id", "")),
        ),
    )
    return selected, {
        "score": _round_metric(score),
        "components": components,
        "policy": (
            "trained_tabular_neural_constrained_ehvi"
            if trained_enabled
            else "cost_aware_constrained_ehvi"
        ),
        "source": "trained_surrogate" if trained_enabled else "online_bootstrap_surrogate",
        "generic_kernel_policy": "wamf_constrained_active_pareto",
        "generic_kernel_frontier_source": str(components.get("generic_frontier_source", "")),
    }


def _update_neural_surrogate(
    model_state: Mapping[str, Any],
    row: Mapping[str, Any],
    observation: Mapping[str, Any],
    workload_features: Mapping[str, Any],
) -> Dict[str, Any]:
    updated = copy.deepcopy(dict(model_state))
    prediction = _neural_predict(row, updated, workload_features)
    observed = _observation_objective(observation)
    residual = observed - prediction["predicted_edp_mean"]
    residuals = list(updated.get("residuals", []) or [])
    residuals.append(residual)
    updated["residuals"] = residuals[-256:]
    sample_count = int(updated.get("training_sample_count", 0)) + 1
    updated["training_sample_count"] = sample_count
    updated["updates"] = int(updated.get("updates", 0)) + 1
    updated["best_observed_edp"] = min(
        _finite_float(updated.get("best_observed_edp"), default=float("inf")),
        observed,
    )
    updated["rank_training_pairs"] = int(sample_count * max(0, sample_count - 1) / 2)
    return updated


def _neural_predict(
    row: Mapping[str, Any],
    model_state: Mapping[str, Any],
    workload_features: Mapping[str, Any],
) -> Dict[str, float]:
    if _trained_surrogate_enabled(model_state):
        trained_prediction = _predict_with_trained_surrogate(row, model_state, workload_features)
        if trained_prediction is not None:
            return trained_prediction
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    params = _candidate_parameters(row)
    l1_edp = max(1.0, _finite_float(metrics.get("estimated_edp"), default=1.0))
    residuals = [
        _finite_float(value, default=float("nan"))
        for value in model_state.get("residuals", []) or []
    ]
    residuals = [value for value in residuals if math.isfinite(value)]
    mean_residual = _mean(residuals) if residuals else 0.0
    uncertainty = _stddev(residuals) if len(residuals) >= 2 else l1_edp * 0.18
    host = _finite_float(workload_features.get("host_control_intensity"), default=0.0)
    post = _finite_float(workload_features.get("post_processing_intensity"), default=0.0)
    data_scale = _finite_float(workload_features.get("variant_data_scale"), default=1.0)
    risk = _workflow_resource_penalty(params, data_scale, host, post)
    resource = _finite_float(metrics.get("fpga_resource_pressure"), default=0.0)
    feasibility_risk = max(0.0, min(1.0, risk + max(0.0, resource - 0.82) * 2.2))
    model_bias = 0.0
    if params.get("memory_topology") == "hbm_multi_channel":
        model_bias -= l1_edp * min(0.08, max(0.0, data_scale - 1.0) * 0.02)
    if params.get("offload_boundary") == "workflow_hotspot_bundle":
        model_bias += l1_edp * (host * 0.04 + post * 0.03)
    prediction = max(1.0, l1_edp + mean_residual + model_bias)
    cost = _adaptive_evaluation_cost(row)
    cost += min(0.35, feasibility_risk * 0.25)
    return {
        "predicted_edp_mean": prediction,
        "predicted_edp_std": max(1.0, uncertainty + prediction * feasibility_risk * 0.08),
        "feasibility_risk": feasibility_risk,
        "evaluation_cost": cost,
    }


def _trained_surrogate_enabled(model_state: Mapping[str, Any]) -> bool:
    trained_use = model_state.get("trained_surrogate_use", {})
    trained = model_state.get("trained_surrogate", {})
    return (
        isinstance(trained_use, Mapping)
        and trained_use.get("status") == "enabled"
        and isinstance(trained, Mapping)
        and trained.get("schema_version") == QE_FPGA_NEURAL_SURROGATE_TRAINING_REPORT_SCHEMA
    )


def _trained_surrogate_use_summary(trained_surrogate: Mapping[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(trained_surrogate, Mapping):
        return {
            "status": "disabled",
            "reason": "no_trained_surrogate_supplied",
        }
    if trained_surrogate.get("schema_version") != QE_FPGA_NEURAL_SURROGATE_TRAINING_REPORT_SCHEMA:
        return {
            "status": "disabled",
            "reason": "unsupported_trained_surrogate_schema",
            "source_schema_version": str(trained_surrogate.get("schema_version", "")),
        }
    dataset = trained_surrogate.get("dataset", {}) if isinstance(trained_surrogate.get("dataset"), Mapping) else {}
    backend = trained_surrogate.get("backend", {}) if isinstance(trained_surrogate.get("backend"), Mapping) else {}
    return {
        "status": "enabled",
        "source_artifact": "qe_fpga_neural_surrogate_training_report.json",
        "source_schema_version": str(trained_surrogate.get("schema_version", "")),
        "model_type": str(backend.get("model_type", "")),
        "sample_count": int(dataset.get("sample_count", 0)),
        "claim_boundary": str(trained_surrogate.get("claim_boundary", "")),
    }


def _predict_with_trained_surrogate(
    row: Mapping[str, Any],
    model_state: Mapping[str, Any],
    workload_features: Mapping[str, Any],
) -> Dict[str, float] | None:
    trained = model_state.get("trained_surrogate", {})
    if not isinstance(trained, Mapping):
        return None
    feature_schema = trained.get("feature_schema", {}) if isinstance(trained.get("feature_schema"), Mapping) else {}
    normalizer = trained.get("normalizer", {}) if isinstance(trained.get("normalizer"), Mapping) else {}
    checkpoint = trained.get("checkpoint", {}) if isinstance(trained.get("checkpoint"), Mapping) else {}
    sample = {
        "candidate_id": str(row.get("candidate_id", "")),
        "parameters": _candidate_parameters(row),
        "l1_metrics": dict(row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}),
        "workload_features": dict(workload_features),
        "observed_edp": 1.0,
        "target_log_edp": 0.0,
        "fidelity": "inference",
    }
    l1_log_edp = _neural_sample_l1_log_edp(sample)
    encoded = _encode_neural_training_samples([sample], feature_schema)
    if not encoded:
        return None
    vector = encoded[0]["features"]
    feature_count = int(normalizer.get("feature_count", len(vector)) or len(vector))
    if feature_count != len(vector):
        return None
    means = [
        _finite_float(value, default=0.0)
        for value in normalizer.get("feature_mean", []) or []
    ]
    stds = [
        max(1.0e-9, _finite_float(value, default=1.0))
        for value in normalizer.get("feature_std", []) or []
    ]
    if len(means) != len(vector):
        means = [0.0 for _ in vector]
    if len(stds) != len(vector):
        stds = [1.0 for _ in vector]
    x_norm = [(value - mean) / std for value, mean, std in zip(vector, means, stds)]
    target_mean = _finite_float(normalizer.get("target_mean_log_residual"), default=0.0)
    target_std = max(1.0e-9, _finite_float(normalizer.get("target_std_log_residual"), default=1.0))
    residual_predictions = []
    for member in checkpoint.get("members", []) or []:
        if not isinstance(member, Mapping):
            continue
        prediction = _predict_trained_member_log_residual(member, x_norm, target_mean, target_std)
        if prediction is not None and math.isfinite(prediction):
            residual_predictions.append(prediction)
    if not residual_predictions:
        return None
    mean_log_residual = max(-32.0, min(32.0, _mean(residual_predictions)))
    std_log = max(0.0, min(6.0, _stddev(residual_predictions)))
    mean_log = max(-32.0, min(32.0, l1_log_edp + mean_log_residual))
    predicted_edp = max(1.0, math.exp(mean_log))
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    params = _candidate_parameters(row)
    host = _finite_float(workload_features.get("host_control_intensity"), default=0.0)
    post = _finite_float(workload_features.get("post_processing_intensity"), default=0.0)
    data_scale = _finite_float(workload_features.get("variant_data_scale"), default=1.0)
    risk = _workflow_resource_penalty(params, data_scale, host, post)
    resource = _finite_float(metrics.get("fpga_resource_pressure"), default=0.0)
    feasibility_risk = max(0.0, min(1.0, risk + max(0.0, resource - 0.82) * 2.2))
    predicted_std = max(1.0, predicted_edp * (math.exp(std_log) - 1.0) + predicted_edp * feasibility_risk * 0.05)
    cost = _adaptive_evaluation_cost(row) + min(0.35, feasibility_risk * 0.25)
    return {
        "predicted_edp_mean": predicted_edp,
        "predicted_edp_std": predicted_std,
        "feasibility_risk": feasibility_risk,
        "evaluation_cost": cost,
    }


def _predict_trained_member_log_residual(
    member: Mapping[str, Any],
    x_norm: Sequence[float],
    target_mean: float,
    target_std: float,
) -> float | None:
    state = member.get("state_dict", {}) if isinstance(member.get("state_dict"), Mapping) else {}
    if state:
        w0 = state.get("0.weight")
        b0 = state.get("0.bias")
        w2 = state.get("2.weight")
        b2 = state.get("2.bias")
        if isinstance(w0, list) and isinstance(b0, list) and isinstance(w2, list) and isinstance(b2, list):
            hidden = []
            for row_weights, bias in zip(w0, b0):
                if not isinstance(row_weights, list):
                    continue
                value = sum(
                    _finite_float(weight, default=0.0) * _finite_float(feature, default=0.0)
                    for weight, feature in zip(row_weights, x_norm)
                ) + _finite_float(bias, default=0.0)
                hidden.append(max(0.0, value))
            output_weights = w2[0] if w2 and isinstance(w2[0], list) else []
            output = sum(
                _finite_float(weight, default=0.0) * value
                for weight, value in zip(output_weights, hidden)
            ) + _finite_float(b2[0] if b2 else 0.0, default=0.0)
            return output * target_std + target_mean
    if "bias_log_residual" in member:
        return _finite_float(member.get("bias_log_residual"), default=target_mean)
    if "bias_log_edp" in member:
        return _finite_float(member.get("bias_log_edp"), default=target_mean)
    return None


def _neural_top_k_probability(prediction: Mapping[str, float], row: Mapping[str, Any]) -> float:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    feasibility = _finite_float(metrics.get("implementation_feasibility"), default=0.0)
    mean = max(1.0, _finite_float(prediction.get("predicted_edp_mean"), default=1.0))
    std = max(1.0, _finite_float(prediction.get("predicted_edp_std"), default=1.0))
    normalized_quality = 1.0 / (1.0 + std / mean)
    return max(0.0, min(1.0, normalized_quality * max(0.05, feasibility)))


def _approx_constrained_expected_hypervolume_improvement(
    row: Mapping[str, Any],
    prediction: Mapping[str, float],
    *,
    best_observed: float,
    workflow_risk_coverage: float,
) -> float:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    mean_edp = max(1.0, _finite_float(prediction.get("predicted_edp_mean"), default=1.0))
    std_edp = max(1.0, _finite_float(prediction.get("predicted_edp_std"), default=1.0))
    if math.isfinite(best_observed) and best_observed > 0.0:
        quality_improvement = max(0.0, best_observed - mean_edp)
    else:
        quality_improvement = max(1.0, 1.0 / mean_edp)
    latency = max(1.0, _finite_float(metrics.get("estimated_workflow_wall_time_ms"), default=mean_edp))
    energy = max(1.0, _finite_float(metrics.get("estimated_energy_mj"), default=max(1.0, mean_edp / latency)))
    resource_slack = max(0.0, 1.0 - _finite_float(metrics.get("fpga_resource_pressure"), default=1.0))
    movement = max(1.0, _finite_float(metrics.get("estimated_data_movement_mb"), default=1.0))
    movement_gain = 1.0 / math.log1p(movement)
    feasible_probability = max(
        0.0,
        min(
            1.0,
            _finite_float(metrics.get("implementation_feasibility"), default=0.5)
            * (1.0 - _finite_float(prediction.get("feasibility_risk"), default=0.0)),
        ),
    )
    uncertainty_gain = 1.0 + min(1.0, std_edp / mean_edp)
    volume_proxy = (
        quality_improvement
        + math.sqrt(max(1.0, latency * energy)) * resource_slack * movement_gain * 0.01
    )
    return max(
        0.0,
        volume_proxy
        * feasible_probability
        * uncertainty_gain
        * (1.0 + max(0.0, min(1.0, workflow_risk_coverage)) * 0.25),
    )


def _workflow_risk_coverage(row: Mapping[str, Any], workload_features: Mapping[str, Any]) -> float:
    params = _candidate_parameters(row)
    host = _finite_float(workload_features.get("host_control_intensity"), default=0.0)
    post = _finite_float(workload_features.get("post_processing_intensity"), default=0.0)
    lifetime = workload_features.get("data_object_lifetime", {}) if isinstance(workload_features.get("data_object_lifetime"), Mapping) else {}
    hot_objects = min(1.0, _finite_float(lifetime.get("hot_reuse_object_count"), default=0.0) / 4.0)
    checkpoint_objects = min(1.0, _finite_float(lifetime.get("checkpoint_object_count"), default=0.0) / 4.0)
    coverage = 0.0
    if host >= 0.25 and params.get("offload_boundary") in {"stage_cluster_bundle", "kernel_callsite_bundle"}:
        coverage += min(0.30, host * 0.45)
    if post >= 0.20 and params.get("architecture_template") in {
        "fpga_fft_transpose_pipeline",
        "fpga_hybrid_cpu_control_accel_kernels",
    }:
        coverage += min(0.25, post * 0.40)
    if hot_objects > 0.0 and params.get("data_residency") in {
        "fpga_hbm_resident_hot_arrays",
        "hybrid_checkpointed_residency",
    }:
        coverage += hot_objects * 0.22
    if checkpoint_objects > 0.0 and params.get("runtime_schedule") in {
        "overlap_dma_compute",
        "batched_stage_pipeline",
    }:
        coverage += checkpoint_objects * 0.18
    return max(0.0, min(1.0, coverage))


def _neural_training_samples(
    rows_by_candidate: Mapping[str, Mapping[str, Any]],
    neural_search: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    samples: List[Dict[str, Any]] = []
    workload_features = (
        neural_search.get("workload_features", {})
        if isinstance(neural_search.get("workload_features"), Mapping)
        else {}
    )
    for trace_row in neural_search.get("evaluation_trace", []) or []:
        if not isinstance(trace_row, Mapping):
            continue
        candidate_id = str(trace_row.get("candidate_id", ""))
        if not candidate_id:
            continue
        l1_row = rows_by_candidate.get(candidate_id, {})
        observation = trace_row.get("common_objective_observation", trace_row.get("l2_observation", {}))
        if not isinstance(observation, Mapping):
            continue
        metrics = observation.get("metrics", {}) if isinstance(observation.get("metrics"), Mapping) else {}
        observed_edp = _feedback_metric(metrics, "calibrated_common_objective_edp", "observed_edp", "tlm_edp", "edp")
        if observed_edp <= 0.0:
            latency = _feedback_metric(metrics, "tlm_workflow_wall_time_ms", "workflow_wall_time_ms", "latency_ms")
            energy = _feedback_metric(metrics, "tlm_energy_mj", "energy_mj")
            if latency > 0.0 and energy > 0.0:
                observed_edp = latency * energy
        if observed_edp <= 0.0:
            continue
        candidate_parameters = (
            trace_row.get("candidate_parameters", {})
            if isinstance(trace_row.get("candidate_parameters"), Mapping)
            else _candidate_parameters(l1_row)
        )
        l1_metrics = (
            trace_row.get("l1_metrics", {})
            if isinstance(trace_row.get("l1_metrics"), Mapping)
            else l1_row.get("metrics", {}) if isinstance(l1_row.get("metrics"), Mapping) else {}
        )
        samples.append({
            "candidate_id": candidate_id,
            "design_key": str(trace_row.get("design_key", l1_row.get("design_key", ""))),
            "workload_id": str(
                workload_features.get("workflow_id")
                or workload_features.get("abstraction_source", {}).get("workload_id")
                if isinstance(workload_features.get("abstraction_source"), Mapping)
                else workload_features.get("workflow_id", "")
            ),
            "parameters": dict(candidate_parameters),
            "l1_metrics": dict(l1_metrics),
            "workload_features": dict(workload_features),
            "observed_edp": observed_edp,
            "target_log_edp": math.log(max(1.0, observed_edp)),
            "fidelity": str(observation.get("fidelity", trace_row.get("observation_source", ""))),
        })
    return samples


def _neural_graph_dataset_contract(samples: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {
        "schema_version": "dse.qe_fpga.neuromf_graph_dataset_contract.v1",
        "dataset_role": "workload_candidate_graph_surrogate_training",
        "core_control_plane_dependency": "none_qe_adapter_projection_only",
        "graph_type": "heterogeneous_workload_candidate_bipartite_graph",
        "target": "log_common_objective_edp_residual_over_l1",
        "node_types": [
            "workload_stage",
            "kernel_family",
            "data_object",
            "candidate_knob",
            "fidelity_observation",
        ],
        "edge_types": [
            "stage_dependency",
            "kernel_in_stage",
            "data_lifetime",
            "candidate_binding",
            "observation_target",
        ],
        "sample_count": len(samples),
        "workload_ids": sorted({_neural_sample_workload_id(sample) for sample in samples}),
        "candidate_count": len({str(sample.get("candidate_id", "")) for sample in samples}),
        "backend_status": "contract_ready_tabular_backend_currently_trains_on_encoded_projection",
        "not_used_as": [
            "architecture_generator",
            "hardware_result",
            "replacement_for_independent_fidelity_feedback",
        ],
    }


def _neural_graph_dataset_samples(samples: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [_neural_graph_dataset_sample(sample) for sample in samples]


def _neural_graph_dataset_sample(sample: Mapping[str, Any]) -> Dict[str, Any]:
    workload = sample.get("workload_features", {}) if isinstance(sample.get("workload_features"), Mapping) else {}
    params = sample.get("parameters", {}) if isinstance(sample.get("parameters"), Mapping) else {}
    metrics = sample.get("l1_metrics", {}) if isinstance(sample.get("l1_metrics"), Mapping) else {}
    workload_id = _neural_sample_workload_id(sample)
    candidate_id = str(sample.get("candidate_id", ""))
    stage_count = max(1, int(_finite_float(workload.get("stage_count"), default=1.0)))
    kernel_count = max(1, len(workload.get("kernel_weights", {}) if isinstance(workload.get("kernel_weights"), Mapping) else {}))
    lifetime = workload.get("data_object_lifetime", {}) if isinstance(workload.get("data_object_lifetime"), Mapping) else {}
    data_object_count = max(
        1,
        int(_finite_float(workload.get("data_artifact_count"), default=0.0))
        + int(_finite_float(lifetime.get("hot_reuse_object_count"), default=0.0))
        + int(_finite_float(lifetime.get("checkpoint_object_count"), default=0.0)),
    )
    candidate_knob_count = len(_neural_candidate_graph_knobs(params))
    l1_edp = max(1.0, _finite_float(metrics.get("estimated_edp"), default=1.0))
    observed_edp = max(1.0, _finite_float(sample.get("observed_edp"), default=1.0))
    target_log = _finite_float(sample.get("target_log_edp"), default=math.log(observed_edp))
    l1_log = math.log(l1_edp)
    rounded_target_log = _round_metric(target_log)
    rounded_l1_log = _round_metric(l1_log)
    data_lifetime_summary = _neural_data_lifetime_summary(workload)
    return {
        "graph_id": f"neuromf_graph::{workload_id}::{candidate_id}",
        "candidate_id": candidate_id,
        "workload_id": workload_id,
        "node_counts": {
            "workload_stage": stage_count,
            "kernel_family": kernel_count,
            "data_object": data_object_count,
            "candidate_knob": candidate_knob_count,
            "fidelity_observation": 1,
        },
        "edge_counts": {
            "stage_dependency": max(0, int(_finite_float(workload.get("workflow_dependency_edge_count"), default=stage_count - 1))),
            "kernel_in_stage": max(kernel_count, stage_count),
            "data_lifetime": int(_finite_float(data_lifetime_summary.get("cross_stage_edge_count"), default=float(data_object_count))),
            "candidate_binding": candidate_knob_count,
            "observation_target": 1,
        },
        "candidate_knobs": _neural_candidate_graph_knobs(params),
        "data_lifetime_summary": data_lifetime_summary,
        "workload_summary": {
            "stage_count": stage_count,
            "graph_node_count": int(_finite_float(workload.get("graph_node_count"), default=stage_count)),
            "graph_edge_count": int(_finite_float(workload.get("graph_edge_count"), default=stage_count - 1)),
            "host_control_intensity": _round_metric(_finite_float(workload.get("host_control_intensity"), default=0.0)),
            "post_processing_intensity": _round_metric(_finite_float(workload.get("post_processing_intensity"), default=0.0)),
            "estimated_workflow_data_volume_mb": _round_metric(
                _finite_float(workload.get("estimated_workflow_data_volume_mb"), default=0.0)
            ),
        },
        "target": {
            "name": "log_common_objective_edp_residual_over_l1",
            "observed_edp": _round_metric(observed_edp),
            "l1_edp": _round_metric(l1_edp),
            "target_log_edp": rounded_target_log,
            "l1_log_edp": rounded_l1_log,
            "residual_log_edp": rounded_target_log - rounded_l1_log,
            "fidelity": str(sample.get("fidelity", "")),
        },
    }


def _neural_data_lifetime_summary(workload: Mapping[str, Any]) -> Dict[str, Any]:
    contract = workload.get("workflow_feature_contract_detail", {})
    if isinstance(contract, Mapping):
        rows = contract.get("data_object_table", [])
    else:
        rows = []
    if isinstance(rows, list) and rows:
        cross_stage_edges = 0
        total_data_mb = 0.0
        max_consumer_fanout = 0
        hbm_residency_edges = 0
        checkpoint_residency_edges = 0
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            object_bytes = max(0.0, _finite_float(row.get("bytes"), default=0.0))
            producer_stages = [str(item) for item in row.get("producer_stages", []) or []]
            consumer_stages = [str(item) for item in row.get("consumer_stages", []) or []]
            cross_targets = {
                (producer, consumer)
                for producer in producer_stages
                for consumer in consumer_stages
                if producer and consumer and producer != consumer
            }
            edge_count = len(cross_targets)
            if edge_count <= 0:
                continue
            residency = str(row.get("residency_constraint") or row.get("preferred_residency_hint") or "").lower()
            cross_stage_edges += edge_count
            total_data_mb += edge_count * object_bytes / 1.0e6
            max_consumer_fanout = max(max_consumer_fanout, len({consumer for _, consumer in cross_targets}))
            if "hbm" in residency or "pinned" in residency or "reuse" in residency:
                hbm_residency_edges += edge_count
            if "checkpoint" in residency or "filesystem" in residency:
                checkpoint_residency_edges += edge_count
        return {
            "source": "workflow_feature_contract.data_object_table",
            "cross_stage_edge_count": cross_stage_edges,
            "total_data_mb": _round_metric(total_data_mb),
            "max_consumer_fanout": max_consumer_fanout,
            "hbm_residency_edge_count": hbm_residency_edges,
            "checkpoint_residency_edge_count": checkpoint_residency_edges,
        }

    lifetime = workload.get("data_object_lifetime", {}) if isinstance(workload.get("data_object_lifetime"), Mapping) else {}
    cross_stage_edges = int(_finite_float(lifetime.get("cross_stage_lifetime_count"), default=0.0))
    hot_object_bytes = max(0.0, _finite_float(lifetime.get("estimated_hot_object_bytes"), default=0.0))
    total_data_mb = cross_stage_edges * hot_object_bytes / max(1.0, _finite_float(lifetime.get("hot_reuse_object_count"), default=1.0)) / 1.0e6
    residency_hint = str(lifetime.get("preferred_residency_hint", "")).lower()
    hbm_edges = cross_stage_edges if ("hbm" in residency_hint or "pinned" in residency_hint or "reuse" in residency_hint) else 0
    checkpoint_edges = cross_stage_edges if ("checkpoint" in residency_hint or "filesystem" in residency_hint) else 0
    return {
        "source": "workload.data_object_lifetime_summary",
        "cross_stage_edge_count": cross_stage_edges,
        "total_data_mb": _round_metric(total_data_mb),
        "max_consumer_fanout": 0,
        "hbm_residency_edge_count": hbm_edges,
        "checkpoint_residency_edge_count": checkpoint_edges,
    }


def _neural_candidate_graph_knobs(params: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for name in [
        "architecture_template",
        "offload_boundary",
        "mapping_granularity",
        "runtime_schedule",
        "data_residency",
        "memory_topology",
        "vector_lanes",
        "hbm_channel_count",
        "tile_doubles",
    ]:
        value = params.get(name, "")
        rows.append({
            "name": name,
            "value": str(value),
            "numeric_value": _finite_float(value, default=0.0),
        })
    return rows


def _neural_ood_evaluation(samples: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    workload_ids = sorted({_neural_sample_workload_id(sample) for sample in samples})
    required = 3
    if len(workload_ids) < required:
        return {
            "schema_version": "dse.qe_fpga.neuromf_ood_evaluation.v1",
            "split_axis": "workload_id",
            "status": "blocked_single_workload_trace" if len(workload_ids) <= 1 else "blocked_insufficient_workload_diversity",
            "distinct_workload_count": len(workload_ids),
            "required_min_workload_count": required,
            "metrics_valid": False,
            "workload_ids": workload_ids,
            "blockers": ["multi_workload_feedback_required_for_ood_neuromf_validation"],
        }
    return {
        "schema_version": "dse.qe_fpga.neuromf_ood_evaluation.v1",
        "split_axis": "workload_id",
        "status": "ready_for_leave_one_workload_out_evaluation",
        "distinct_workload_count": len(workload_ids),
        "required_min_workload_count": required,
        "metrics_valid": True,
        "workload_ids": workload_ids,
        "recommended_protocol": "leave_one_workload_out_rank_and_calibration_evaluation",
        "blockers": [],
    }


def _neural_sample_workload_id(sample: Mapping[str, Any]) -> str:
    workload = sample.get("workload_features", {}) if isinstance(sample.get("workload_features"), Mapping) else {}
    source = workload.get("abstraction_source", {}) if isinstance(workload.get("abstraction_source"), Mapping) else {}
    return str(sample.get("workload_id") or workload.get("workflow_id") or source.get("workload_id") or "single_workload_trace")


def _neural_training_feature_schema(samples: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    base = _neural_feature_schema()
    graph_feature_names = _neural_graph_projection_feature_names()
    numeric_names = [
        f"workload.{name}"
        for name in base["workload_feature_names"]
    ] + [
        f"l1.{name}"
        for name in base["l1_metric_feature_names"]
    ] + [
        "parameter.vector_lanes",
        "parameter.hbm_channel_count",
        "parameter.tile_doubles",
    ]
    categorical_names = [
        name for name in base["candidate_parameter_names"]
        if name not in {"vector_lanes", "hbm_channel_count", "tile_doubles"}
    ]
    categorical_values: Dict[str, List[str]] = {}
    for name in categorical_names:
        values = sorted({
            str(sample.get("parameters", {}).get(name, "unknown"))
            for sample in samples
            if isinstance(sample.get("parameters"), Mapping)
        })
        categorical_values[name] = values or ["unknown"]
    encoded = list(numeric_names)
    for name in categorical_names:
        encoded.extend([f"cat.{name}={value}" for value in categorical_values[name]])
    encoded.extend(graph_feature_names)
    return {
        "schema_version": "dse.qe_fpga.neural_surrogate_feature_schema.v1",
        "numeric_feature_names": numeric_names,
        "graph_feature_names": graph_feature_names,
        "categorical_feature_names": categorical_names,
        "categorical_values": categorical_values,
        "encoded_feature_names": encoded,
        "target_name": "log_common_objective_edp_residual_over_l1",
        "graph_backend_contract": base["graph_backend_contract"],
        "graph_projection_contract": _neural_graph_projection_contract(),
    }


def _neural_graph_projection_contract() -> Dict[str, Any]:
    return {
        "schema_version": "dse.qe_fpga.neuromf_graph_projection.v1",
        "projection_role": "graph_to_tabular_backend_features",
        "source_graph_contract_schema": "dse.qe_fpga.neuromf_graph_dataset_contract.v1",
        "preserves_graph_dataset_samples": True,
        "backend_status": "graph_projected_tabular_backend",
        "feature_groups": [
            "node_count_features",
            "edge_count_features",
            "data_lifetime_communication_features",
            "candidate_knob_features",
            "l1_anchor_features",
        ],
        "target_leakage_policy": "target_residual_features_are_excluded_from_inputs",
        "next_backend": "heterogeneous_gnn_workload_candidate_encoder",
    }


def _neural_graph_projection_feature_names() -> List[str]:
    return [
        "graph.node.workload_stage",
        "graph.node.kernel_family",
        "graph.node.data_object",
        "graph.node.candidate_knob",
        "graph.node.fidelity_observation",
        "graph.edge.stage_dependency",
        "graph.edge.kernel_in_stage",
        "graph.edge.data_lifetime",
        "graph.edge.data_lifetime.total_data_mb",
        "graph.edge.data_lifetime.max_consumer_fanout",
        "graph.edge.data_lifetime.hbm_residency_edge_count",
        "graph.edge.data_lifetime.checkpoint_residency_edge_count",
        "graph.edge.candidate_binding",
        "graph.edge.observation_target",
        "graph.workload.stage_count",
        "graph.workload.graph_node_count",
        "graph.workload.graph_edge_count",
        "graph.workload.host_control_intensity",
        "graph.workload.post_processing_intensity",
        "graph.workload.estimated_workflow_data_volume_mb",
        "graph.knob_count.numeric",
        "graph.knob.vector_lanes",
        "graph.knob.hbm_channel_count",
        "graph.knob.tile_doubles",
        "graph.l1.log_edp",
    ]


def _neural_graph_projection_features(sample: Mapping[str, Any]) -> Dict[str, float]:
    graph = _neural_graph_dataset_sample(sample)
    node_counts = graph.get("node_counts", {}) if isinstance(graph.get("node_counts"), Mapping) else {}
    edge_counts = graph.get("edge_counts", {}) if isinstance(graph.get("edge_counts"), Mapping) else {}
    lifetime_summary = graph.get("data_lifetime_summary", {}) if isinstance(graph.get("data_lifetime_summary"), Mapping) else {}
    workload = graph.get("workload_summary", {}) if isinstance(graph.get("workload_summary"), Mapping) else {}
    target = graph.get("target", {}) if isinstance(graph.get("target"), Mapping) else {}
    candidate_knobs = graph.get("candidate_knobs", []) if isinstance(graph.get("candidate_knobs"), list) else []
    knob_values = {
        str(row.get("name", "")): _finite_float(row.get("numeric_value"), default=0.0)
        for row in candidate_knobs
        if isinstance(row, Mapping)
    }
    return {
        "graph.node.workload_stage": _finite_float(node_counts.get("workload_stage"), default=0.0),
        "graph.node.kernel_family": _finite_float(node_counts.get("kernel_family"), default=0.0),
        "graph.node.data_object": _finite_float(node_counts.get("data_object"), default=0.0),
        "graph.node.candidate_knob": _finite_float(node_counts.get("candidate_knob"), default=0.0),
        "graph.node.fidelity_observation": _finite_float(node_counts.get("fidelity_observation"), default=0.0),
        "graph.edge.stage_dependency": _finite_float(edge_counts.get("stage_dependency"), default=0.0),
        "graph.edge.kernel_in_stage": _finite_float(edge_counts.get("kernel_in_stage"), default=0.0),
        "graph.edge.data_lifetime": _finite_float(edge_counts.get("data_lifetime"), default=0.0),
        "graph.edge.data_lifetime.total_data_mb": _finite_float(lifetime_summary.get("total_data_mb"), default=0.0),
        "graph.edge.data_lifetime.max_consumer_fanout": _finite_float(lifetime_summary.get("max_consumer_fanout"), default=0.0),
        "graph.edge.data_lifetime.hbm_residency_edge_count": _finite_float(lifetime_summary.get("hbm_residency_edge_count"), default=0.0),
        "graph.edge.data_lifetime.checkpoint_residency_edge_count": _finite_float(lifetime_summary.get("checkpoint_residency_edge_count"), default=0.0),
        "graph.edge.candidate_binding": _finite_float(edge_counts.get("candidate_binding"), default=0.0),
        "graph.edge.observation_target": _finite_float(edge_counts.get("observation_target"), default=0.0),
        "graph.workload.stage_count": _finite_float(workload.get("stage_count"), default=0.0),
        "graph.workload.graph_node_count": _finite_float(workload.get("graph_node_count"), default=0.0),
        "graph.workload.graph_edge_count": _finite_float(workload.get("graph_edge_count"), default=0.0),
        "graph.workload.host_control_intensity": _finite_float(workload.get("host_control_intensity"), default=0.0),
        "graph.workload.post_processing_intensity": _finite_float(workload.get("post_processing_intensity"), default=0.0),
        "graph.workload.estimated_workflow_data_volume_mb": _finite_float(
            workload.get("estimated_workflow_data_volume_mb"),
            default=0.0,
        ),
        "graph.knob_count.numeric": float(len(candidate_knobs)),
        "graph.knob.vector_lanes": knob_values.get("vector_lanes", 0.0),
        "graph.knob.hbm_channel_count": knob_values.get("hbm_channel_count", 0.0),
        "graph.knob.tile_doubles": knob_values.get("tile_doubles", 0.0),
        "graph.l1.log_edp": _finite_float(target.get("l1_log_edp"), default=0.0),
    }


def _encode_neural_training_samples(
    samples: Sequence[Mapping[str, Any]],
    feature_schema: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    encoded_rows: List[Dict[str, Any]] = []
    encoded_names = [str(name) for name in feature_schema.get("encoded_feature_names", []) or []]
    categorical_values = (
        feature_schema.get("categorical_values", {})
        if isinstance(feature_schema.get("categorical_values"), Mapping)
        else {}
    )
    for sample in samples:
        params = sample.get("parameters", {}) if isinstance(sample.get("parameters"), Mapping) else {}
        metrics = sample.get("l1_metrics", {}) if isinstance(sample.get("l1_metrics"), Mapping) else {}
        workload = sample.get("workload_features", {}) if isinstance(sample.get("workload_features"), Mapping) else {}
        features: Dict[str, float] = {}
        for name in feature_schema.get("numeric_feature_names", []) or []:
            key = str(name)
            if key.startswith("workload."):
                features[key] = _finite_float(_nested_mapping_value(workload, key.split(".", 1)[1]), default=0.0)
            elif key.startswith("l1."):
                features[key] = _finite_float(_nested_mapping_value(metrics, key.split(".", 1)[1]), default=0.0)
            elif key.startswith("parameter."):
                features[key] = _finite_float(_nested_mapping_value(params, key.split(".", 1)[1]), default=0.0)
        graph_features = _neural_graph_projection_features(sample)
        for name in feature_schema.get("graph_feature_names", []) or []:
            key = str(name)
            features[key] = _finite_float(graph_features.get(key), default=0.0)
        for name in feature_schema.get("categorical_feature_names", []) or []:
            field = str(name)
            value = str(params.get(field, "unknown"))
            allowed = [str(item) for item in categorical_values.get(field, []) or ["unknown"]]
            for allowed_value in allowed:
                features[f"cat.{field}={allowed_value}"] = 1.0 if value == allowed_value else 0.0
        vector = [features.get(name, 0.0) for name in encoded_names]
        target_log_edp = _finite_float(sample.get("target_log_edp"), default=0.0)
        l1_log_edp = _neural_sample_l1_log_edp(sample)
        target_log_residual = target_log_edp - l1_log_edp
        encoded_rows.append({
            "candidate_id": str(sample.get("candidate_id", "")),
            "design_key": str(sample.get("design_key", "")),
            "features": vector,
            "target_log_edp": target_log_edp,
            "target_log_residual": target_log_residual,
            "l1_log_edp": l1_log_edp,
            "observed_edp": _finite_float(sample.get("observed_edp"), default=0.0),
            "fidelity": str(sample.get("fidelity", "")),
        })
    return encoded_rows


def _neural_sample_l1_log_edp(sample: Mapping[str, Any]) -> float:
    metrics = sample.get("l1_metrics", {}) if isinstance(sample.get("l1_metrics"), Mapping) else {}
    l1_edp = max(1.0, _finite_float(metrics.get("estimated_edp"), default=1.0))
    return math.log(l1_edp)


def _nested_mapping_value(mapping: Mapping[str, Any], dotted_key: str) -> Any:
    current: Any = mapping
    for part in str(dotted_key).split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _split_neural_training_rows(encoded_rows: Sequence[Mapping[str, Any]], *, seed: int) -> Dict[str, List[int]]:
    indices = list(range(len(encoded_rows)))
    if not indices:
        return {"train": [], "validation": [], "holdout": []}
    indices.sort(
        key=lambda index: json.dumps(
            {
                "seed": int(seed),
                "candidate_id": encoded_rows[index].get("candidate_id", ""),
                "index": index,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    n = len(indices)
    holdout_count = 1 if n >= 3 else 0
    validation_count = 1 if n >= 2 else 0
    if n >= 10:
        holdout_count = max(1, n // 5)
        validation_count = max(1, n // 5)
    holdout = indices[:holdout_count]
    validation = indices[holdout_count:holdout_count + validation_count]
    train = indices[holdout_count + validation_count:]
    if not train and validation:
        train.append(validation.pop())
    if len(train) < 4 and n >= 6:
        while len(train) < 4 and validation:
            train.append(validation.pop())
        while len(train) < 4 and holdout:
            train.append(holdout.pop())
    return {"train": train, "validation": validation, "holdout": holdout}


def _train_tabular_neural_ensemble(
    encoded_rows: Sequence[Mapping[str, Any]],
    *,
    split_rows: Mapping[str, Sequence[int]],
    ensemble_size: int,
    max_epochs: int,
    seed: int,
) -> Dict[str, Any]:
    try:
        import torch
    except ImportError:
        return _fallback_linear_ensemble(encoded_rows, split_rows=split_rows, ensemble_size=ensemble_size, seed=seed)

    backend_runtime = _torch_backend_runtime(torch)
    device = torch.device(str(backend_runtime["resolved_device"]))
    torch.manual_seed(int(seed))
    if bool(backend_runtime.get("cuda_available", False)):
        torch.cuda.manual_seed_all(int(seed))
    feature_count = len(encoded_rows[0]["features"]) if encoded_rows else 0
    train_indices = list(split_rows.get("train", []) or [])
    if not encoded_rows or feature_count <= 0 or not train_indices:
        return _empty_neural_training_result(feature_count, ensemble_size, backend_runtime=backend_runtime)
    x_all = torch.tensor([row["features"] for row in encoded_rows], dtype=torch.float32, device=device)
    y_all = torch.tensor([[float(row["target_log_residual"])] for row in encoded_rows], dtype=torch.float32, device=device)
    mean = x_all[train_indices].mean(dim=0)
    std = x_all[train_indices].std(dim=0, unbiased=False)
    std = torch.where(std < 1.0e-9, torch.ones_like(std), std)
    x_norm = (x_all - mean) / std
    y_mean = y_all[train_indices].mean()
    y_std = y_all[train_indices].std(unbiased=False)
    if float(y_std.item()) < 1.0e-9:
        y_std = torch.tensor(1.0, dtype=torch.float32, device=device)
    y_norm = (y_all - y_mean) / y_std
    members: List[Dict[str, Any]] = []
    member_predictions: List[List[float]] = []
    hidden = max(4, min(32, feature_count * 2))
    for member_index in range(max(1, int(ensemble_size))):
        torch.manual_seed(int(seed) + member_index * 97)
        model = torch.nn.Sequential(
            torch.nn.Linear(feature_count, hidden),
            torch.nn.ReLU(),
            torch.nn.Linear(hidden, 1),
        ).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=0.025)
        x_train = x_norm[train_indices]
        y_train = y_norm[train_indices]
        for _epoch in range(max(1, int(max_epochs))):
            optimizer.zero_grad()
            loss = torch.nn.functional.mse_loss(model(x_train), y_train)
            loss.backward()
            optimizer.step()
        with torch.no_grad():
            pred = model(x_norm).reshape(-1) * y_std + y_mean
        member_predictions.append([float(value) for value in pred.detach().cpu().tolist()])
        members.append({
            "member_id": f"mlp_{member_index:02d}",
            "seed": int(seed) + member_index * 97,
            "hidden_units": hidden,
            "parameter_count": int(sum(parameter.numel() for parameter in model.parameters())),
            "train_loss": _round_metric(float(loss.item())),
            "state_dict": {
                key: _round_nested(value.detach().cpu().tolist())
                for key, value in model.state_dict().items()
            },
        })
    predictions = _ensemble_prediction_rows(encoded_rows, member_predictions)
    return {
        "normalizer": {
            "feature_count": feature_count,
            "feature_mean": [_round_metric(float(value)) for value in mean.detach().cpu().tolist()],
            "feature_std": [_round_metric(float(value)) for value in std.detach().cpu().tolist()],
            "target_name": "log_common_objective_edp_residual_over_l1",
            "target_mean_log_residual": _round_metric(float(y_mean.item())),
            "target_std_log_residual": _round_metric(float(y_std.item())),
        },
        "checkpoint": {
            "format": "inline_torch_state_dict_for_replay",
            "device_policy": str(backend_runtime["device_policy"]),
            "resolved_device": str(backend_runtime["resolved_device"]),
            "members": members,
        },
        "backend_runtime": backend_runtime,
        "predictions": predictions,
    }


def _torch_backend_runtime(torch_module: Any) -> Dict[str, Any]:
    cuda_available = bool(torch_module.cuda.is_available())
    cuda_device_count = int(torch_module.cuda.device_count()) if hasattr(torch_module, "cuda") else 0
    cuda_device_name = ""
    if cuda_available and cuda_device_count > 0:
        try:
            cuda_device_name = str(torch_module.cuda.get_device_name(0))
        except Exception:
            cuda_device_name = "unknown_cuda_device"
    resolved_device = "cuda" if cuda_available else "cpu"
    runtime = {
        "device_policy": "cuda_if_available",
        "resolved_device": resolved_device,
        "cuda_available": cuda_available,
        "cuda_device_count": cuda_device_count,
        "cuda_device_name": cuda_device_name,
        "torch_version": str(getattr(torch_module, "__version__", "")),
    }
    if not cuda_available:
        runtime["device_fallback_reason"] = "cuda_not_available"
    return runtime


def _fallback_linear_ensemble(
    encoded_rows: Sequence[Mapping[str, Any]],
    *,
    split_rows: Mapping[str, Sequence[int]],
    ensemble_size: int,
    seed: int,
) -> Dict[str, Any]:
    feature_count = len(encoded_rows[0]["features"]) if encoded_rows else 0
    if not encoded_rows:
        return _empty_neural_training_result(
            feature_count,
            ensemble_size,
            backend_runtime=_fallback_backend_runtime("empty_training_set"),
        )
    train_indices = list(split_rows.get("train", []) or range(len(encoded_rows)))
    train_targets = [float(encoded_rows[index]["target_log_residual"]) for index in train_indices]
    target_mean = _mean(train_targets)
    member_predictions = [[target_mean for _row in encoded_rows] for _ in range(max(1, int(ensemble_size)))]
    predictions = _ensemble_prediction_rows(encoded_rows, member_predictions)
    return {
        "normalizer": {
            "feature_count": feature_count,
            "feature_mean": [0.0 for _ in range(feature_count)],
            "feature_std": [1.0 for _ in range(feature_count)],
            "target_name": "log_common_objective_edp_residual_over_l1",
            "target_mean_log_residual": _round_metric(target_mean),
            "target_std_log_residual": _round_metric(_stddev(train_targets)),
        },
        "checkpoint": {
            "format": "fallback_constant_predictor_no_torch",
            "device_policy": "cuda_if_available",
            "resolved_device": "cpu",
            "members": [
                {
                    "member_id": f"fallback_{index:02d}",
                    "seed": int(seed) + index,
                    "parameter_count": 1,
                    "bias_log_residual": _round_metric(target_mean),
                }
                for index in range(max(1, int(ensemble_size)))
            ],
        },
        "backend_runtime": _fallback_backend_runtime("torch_import_failed"),
        "predictions": predictions,
    }


def _fallback_backend_runtime(reason: str) -> Dict[str, Any]:
    return {
        "device_policy": "cuda_if_available",
        "resolved_device": "cpu",
        "cuda_available": False,
        "cuda_device_count": 0,
        "cuda_device_name": "",
        "torch_version": "",
        "device_fallback_reason": str(reason),
    }


def _empty_neural_training_result(
    feature_count: int,
    ensemble_size: int,
    *,
    backend_runtime: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    runtime = dict(backend_runtime or _fallback_backend_runtime("empty_training_set"))
    return {
        "normalizer": {
            "feature_count": int(feature_count),
            "feature_mean": [],
            "feature_std": [],
            "target_name": "log_common_objective_edp_residual_over_l1",
            "target_mean_log_residual": 0.0,
            "target_std_log_residual": 0.0,
        },
        "checkpoint": {
            "format": "empty_training_set",
            "device_policy": str(runtime["device_policy"]),
            "resolved_device": str(runtime["resolved_device"]),
            "members": [
                {"member_id": f"empty_{index:02d}", "seed": index, "parameter_count": 0}
                for index in range(max(1, int(ensemble_size)))
            ],
        },
        "backend_runtime": runtime,
        "predictions": [],
    }


def _ensemble_prediction_rows(
    encoded_rows: Sequence[Mapping[str, Any]],
    member_predictions: Sequence[Sequence[float]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, row in enumerate(encoded_rows):
        values = [
            float(predictions[index])
            for predictions in member_predictions
            if index < len(predictions)
        ]
        mean_log_residual = _mean(values)
        std_log_residual = _stddev(values)
        l1_log_edp = _finite_float(row.get("l1_log_edp"), default=0.0)
        mean_log_edp = l1_log_edp + mean_log_residual
        std_log_edp = std_log_residual
        predicted_edp = math.exp(mean_log_edp)
        rows.append({
            "candidate_id": str(row.get("candidate_id", "")),
            "target_log_edp": _round_metric(_finite_float(row.get("target_log_edp"), default=0.0)),
            "target_log_residual": _round_metric(_finite_float(row.get("target_log_residual"), default=0.0)),
            "predicted_log_residual_mean": _round_metric(mean_log_residual),
            "predicted_log_residual_std": _round_metric(std_log_residual),
            "predicted_log_edp_mean": _round_metric(mean_log_edp),
            "predicted_log_edp_std": _round_metric(std_log_edp),
            "predicted_edp_mean": _round_metric(predicted_edp),
            "predicted_edp_std": _round_metric(max(0.0, predicted_edp * (math.exp(std_log_edp) - 1.0))),
        })
    return rows


def _neural_training_metrics(
    encoded_rows: Sequence[Mapping[str, Any]],
    split_rows: Mapping[str, Sequence[int]],
    predictions: Sequence[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    return {
        split_name: _neural_split_metrics(encoded_rows, predictions, list(indices or []))
        for split_name, indices in split_rows.items()
    }


def _neural_split_metrics(
    encoded_rows: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
    indices: Sequence[int],
) -> Dict[str, Any]:
    if not indices:
        return {
            "count": 0,
            "target_name": "log_common_objective_edp_residual_over_l1",
            "rmse_log_edp": 0.0,
            "rmse_log_residual": 0.0,
            "mape_percent": 0.0,
            "spearman_rank_correlation": 0.0,
            "top_k_recall_at_5": 0.0,
        }
    targets = [_finite_float(encoded_rows[index].get("target_log_edp"), default=0.0) for index in indices]
    preds = [_finite_float(predictions[index].get("predicted_log_edp_mean"), default=0.0) for index in indices]
    residual_targets = [
        _finite_float(encoded_rows[index].get("target_log_residual"), default=0.0)
        for index in indices
    ]
    residual_preds = [
        _finite_float(predictions[index].get("predicted_log_residual_mean"), default=0.0)
        for index in indices
    ]
    target_edp = [_finite_float(encoded_rows[index].get("observed_edp"), default=0.0) for index in indices]
    pred_edp = [_finite_float(predictions[index].get("predicted_edp_mean"), default=0.0) for index in indices]
    errors = [pred - target for pred, target in zip(preds, targets)]
    residual_errors = [
        pred - target
        for pred, target in zip(residual_preds, residual_targets)
    ]
    k = min(5, len(indices))
    true_top = set(sorted(range(len(indices)), key=lambda idx: target_edp[idx])[:k])
    pred_top = set(sorted(range(len(indices)), key=lambda idx: pred_edp[idx])[:k])
    return {
        "count": len(indices),
        "target_name": "log_common_objective_edp_residual_over_l1",
        "rmse_log_edp": _round_metric(math.sqrt(_mean([error * error for error in errors]))),
        "rmse_log_residual": _round_metric(math.sqrt(_mean([error * error for error in residual_errors]))),
        "mape_percent": _round_metric(_mean([
            abs(pred - target) / max(abs(target), 1.0e-9) * 100.0
            for pred, target in zip(pred_edp, target_edp)
            if target > 0.0
        ])),
        "spearman_rank_correlation": _round_metric(_spearman(target_edp, pred_edp)),
        "top_k_recall_at_5": _round_metric(len(true_top & pred_top) / float(max(1, len(true_top)))),
    }


def _neural_uncertainty_report(
    encoded_rows: Sequence[Mapping[str, Any]],
    split_rows: Mapping[str, Sequence[int]],
    predictions: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    holdout = list(split_rows.get("holdout", []) or [])
    interval_widths = [
        2.0 * max(1.0e-9, _finite_float(predictions[index].get("predicted_log_edp_std"), default=0.0))
        for index in holdout
        if 0 <= index < len(predictions)
    ]
    if len(holdout) < 3:
        return {
            "method": "deep_ensemble_prediction_std",
            "calibration_status": "insufficient_holdout_for_interval_calibration",
            "holdout_count": len(holdout),
            "interval_coverage_1sigma": None,
            "expected_calibration_error_1sigma": None,
            "mean_prediction_interval_width_log_edp": (
                _round_metric(_mean(interval_widths)) if interval_widths else None
            ),
            "calibration_sample_boundary": "holdout_count_below_three_interval_coverage_not_statistically_meaningful",
        }
    covered = 0
    for index in holdout:
        target = _finite_float(encoded_rows[index].get("target_log_edp"), default=0.0)
        mean = _finite_float(predictions[index].get("predicted_log_edp_mean"), default=0.0)
        std = max(1.0e-9, _finite_float(predictions[index].get("predicted_log_edp_std"), default=0.0))
        if mean - std <= target <= mean + std:
            covered += 1
    coverage = covered / float(len(holdout))
    return {
        "method": "deep_ensemble_prediction_std",
        "calibration_status": "interval_coverage_estimated_from_holdout",
        "holdout_count": len(holdout),
        "interval_coverage_1sigma": _round_metric(coverage),
        "expected_calibration_error_1sigma": _round_metric(abs(coverage - 0.682689492137)),
        "mean_prediction_interval_width_log_edp": _round_metric(_mean(interval_widths)) if interval_widths else None,
        "calibration_sample_boundary": "holdout_only_model_feedback_not_independent_hardware_or_qe_correctness_evidence",
    }


def _neural_inference_preview(
    encoded_rows: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
    *,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    preview = []
    for row, prediction in list(zip(encoded_rows, predictions))[: max(0, int(limit))]:
        preview.append({
            "candidate_id": str(row.get("candidate_id", "")),
            "observed_edp": _round_metric(_finite_float(row.get("observed_edp"), default=0.0)),
            "l1_log_edp": _round_metric(_finite_float(row.get("l1_log_edp"), default=0.0)),
            "target_log_residual": _round_metric(_finite_float(row.get("target_log_residual"), default=0.0)),
            "predicted_log_residual_mean": _round_metric(_finite_float(
                prediction.get("predicted_log_residual_mean"),
                default=0.0,
            )),
            "predicted_edp_mean": _round_metric(_finite_float(prediction.get("predicted_edp_mean"), default=0.0)),
            "predicted_edp_std": _round_metric(_finite_float(prediction.get("predicted_edp_std"), default=0.0)),
        })
    return preview


def _round_nested(value: Any) -> Any:
    if isinstance(value, list):
        return [_round_nested(item) for item in value]
    if isinstance(value, float):
        return _round_metric(value)
    return value


def _evaluated_axis_values(
    rows: Sequence[Mapping[str, Any]],
    evaluated_ids: set[str],
) -> Dict[str, set[str]]:
    values: Dict[str, set[str]] = {
        "architecture_template": set(),
        "offload_boundary": set(),
        "runtime_schedule": set(),
        "data_residency": set(),
        "memory_topology": set(),
    }
    for row in rows:
        if str(row.get("candidate_id", "")) not in evaluated_ids:
            continue
        params = _candidate_parameters(row)
        for axis in values:
            if params.get(axis):
                values[axis].add(str(params[axis]))
    return values


def _l2_edp_sort_key(row: Mapping[str, Any]) -> Tuple[float, float, str]:
    return (
        _l2_metric(row, "tlm_edp"),
        _l2_metric(row, "tlm_resource_pressure"),
        str(row.get("candidate_id", "")),
    )


def _l2_metric(row: Mapping[str, Any], key: str) -> float:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    return _finite_float(metrics.get(key), default=float("inf"))


def _stable_fraction(text: str) -> float:
    total = 0
    for char in str(text):
        total = (total * 131 + ord(char)) % 1_000_003
    return total / 1_000_003.0


def _same_metric_value(left: float, right: float) -> bool:
    scale = max(1.0, abs(left), abs(right))
    return abs(left - right) <= scale * 5.0e-4


def _implementation_package_entry(
    request: Mapping[str, Any],
    result_by_candidate: Mapping[str, Mapping[str, Any]],
    index: int,
) -> Dict[str, Any]:
    candidate_id = str(request.get("candidate_id", f"qe_fpga_candidate_{index:03d}"))
    result = result_by_candidate.get(candidate_id, {})
    parameters = request.get("candidate_parameters", {}) if isinstance(request.get("candidate_parameters"), Mapping) else {}
    package_id = f"qe_fpga_impl_pkg_{index:03d}"
    package_dir = f"implementation_packages/{package_id}"
    return {
        "schema_version": "dse.qe_fpga_implementation_package_entry.v1",
        "package_id": package_id,
        "candidate_id": candidate_id,
        "design_key": str(request.get("design_key", "")),
        "package_dir": package_dir,
        "status": "ready_to_materialize_sources",
        "candidate_parameters": dict(parameters),
        "l2_result_ref": {
            "candidate_id": candidate_id,
            "status": str(result.get("status", "missing_l2_result")),
            "metrics": dict(result.get("metrics", {}) if isinstance(result.get("metrics"), Mapping) else {}),
        },
        "source_files": [
            "candidate_manifest.json",
            "hls/qe_workflow_accel.cpp",
            "hls/qe_workflow_accel.hpp",
            "host/host_stub.cpp",
            "scripts/run_hls.tcl",
            "scripts/run_vivado_packaging.tcl",
            "README.md",
        ],
        "kernel_interfaces": _implementation_kernel_interfaces(request),
        "tool_flow": {
            "hls_tool": "vivado_hls_or_vitis_hls",
            "fpga_packaging_tool": "vivado_or_vitis",
            "blocked_until_real_tool_run": [
                "hls_csim",
                "hls_synthesis",
                "vivado_synthesis_or_packaging",
                "write_bitstream_or_xclbin",
            ],
            "expected_outputs": [
                "hls_csim.log",
                "hls_synth.rpt",
                "vivado_synth.log",
                "vivado_utilization.rpt",
                "vivado_timing_summary.rpt",
                "bitstream_or_xclbin_manifest.json",
            ],
        },
        "closure_contract": _implementation_closure_contract(
            package_id=package_id,
            candidate_id=candidate_id,
            design_key=str(request.get("design_key", "")),
            package_dir=package_dir,
            source_kind="candidate_bound_scaffold",
            materialized=False,
        ),
        "claim_boundary": "planned_candidate_specific_sources_only_not_synthesis_or_bitstream_evidence",
    }


def _materialize_qe_fpga_implementation_package(
    root: Path,
    package: Mapping[str, Any],
) -> Dict[str, Any]:
    package_dir = str(package.get("package_dir") or "")
    if not package_dir:
        raise ValueError("implementation package is missing package_dir")
    package_root = root / package_dir
    closure_contract = _implementation_closure_contract(
        package_id=str(package.get("package_id", "")),
        candidate_id=str(package.get("candidate_id", "")),
        design_key=str(package.get("design_key", "")),
        package_dir=package_dir,
        source_kind="candidate_bound_scaffold",
        materialized=True,
    )
    package_payload = dict(package)
    package_payload["closure_contract"] = closure_contract
    files = {
        "candidate_manifest.json": _candidate_manifest_text(package_payload),
        "implementation_closure_contract.json": _implementation_closure_contract_text(package_payload),
        "hls/qe_workflow_accel.hpp": _hls_header_text(package_payload),
        "hls/qe_workflow_accel.cpp": _hls_source_text(package_payload),
        "host/host_stub.cpp": _host_stub_text(package_payload),
        "scripts/run_hls.tcl": _hls_tcl_text(package_payload),
        "scripts/run_vivado_packaging.tcl": _vivado_packaging_tcl_text(package_payload),
        "README.md": _implementation_package_readme_text(package_payload),
    }
    for rel_path, text in files.items():
        path = package_root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return {
        "schema_version": "dse.qe_fpga_implementation_package_materialized_entry.v1",
        "package_id": str(package.get("package_id", "")),
        "candidate_id": str(package.get("candidate_id", "")),
        "design_key": str(package.get("design_key", "")),
        "package_dir": package_dir,
        "status": "sources_materialized_not_synthesized",
        "materialized_files": sorted(files),
        "closure_contract": closure_contract,
        "next_tool_entrypoints": [
            f"{package_dir}/scripts/run_hls.tcl",
            f"{package_dir}/scripts/run_vivado_packaging.tcl",
        ],
        "claim_boundary": "materialized_hls_sources_only_not_synthesis_or_bitstream_evidence",
    }


def _candidate_manifest_text(package: Mapping[str, Any]) -> str:
    closure_contract = dict(
        package.get("closure_contract", {})
        if isinstance(package.get("closure_contract"), Mapping)
        else {}
    )
    payload = {
        "schema_version": "dse.qe_fpga_candidate_implementation_manifest.v1",
        "package_id": str(package.get("package_id", "")),
        "candidate_id": str(package.get("candidate_id", "")),
        "design_key": str(package.get("design_key", "")),
        "status": "sources_materialized_not_synthesized",
        "source_semantics": {
            "source_kind": "candidate_bound_scaffold",
            "implemented_qe_kernels": [],
            "golden_vectors_required": True,
            "performance_feedback_allowed": False,
        },
        "candidate_parameters": dict(
            package.get("candidate_parameters", {})
            if isinstance(package.get("candidate_parameters"), Mapping)
            else {}
        ),
        "l2_result_ref": dict(
            package.get("l2_result_ref", {})
            if isinstance(package.get("l2_result_ref"), Mapping)
            else {}
        ),
        "kernel_interfaces": [
            dict(interface)
            for interface in package.get("kernel_interfaces", []) or []
            if isinstance(interface, Mapping)
        ],
        "source_files": list(package.get("source_files", []) or []),
        "tool_flow": dict(
            package.get("tool_flow", {})
            if isinstance(package.get("tool_flow"), Mapping)
            else {}
        ),
        "closure_contract": closure_contract,
        "verification_required_before_performance_use": [
            "qe_golden_vector_generation",
            "hls_csim_or_rtl_sim",
            "hls_synthesis",
            "vivado_synthesis_or_implementation",
            "bitstream_or_xclbin_generation",
        ],
        "claim_boundary": "materialized_hls_sources_only_not_synthesis_or_bitstream_evidence",
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _implementation_closure_contract_text(package: Mapping[str, Any]) -> str:
    payload = dict(
        package.get("closure_contract", {})
        if isinstance(package.get("closure_contract"), Mapping)
        else {}
    )
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _implementation_closure_contract(
    *,
    package_id: str,
    candidate_id: str,
    design_key: str,
    package_dir: str,
    source_kind: str,
    materialized: bool,
) -> Dict[str, Any]:
    return {
        "schema_version": "dse.qe_fpga_implementation_closure_contract.v1",
        "package_id": str(package_id),
        "candidate_id": str(candidate_id),
        "design_key": str(design_key),
        "package_dir": str(package_dir),
        "candidate_bound": bool(candidate_id),
        "source_kind": str(source_kind),
        "performance_feedback_allowed": False,
        "synthesis_evidence_allowed": False,
        "bitstream_evidence_allowed": False,
        "gates": {
            "candidate_manifest": "materialized" if materialized else "planned",
            "hls_sources": "materialized" if materialized else "planned",
            "qe_golden_vectors": "missing",
            "real_qe_kernel_source": "missing",
            "hls_csim": "not_run",
            "hls_csynth": "not_run",
            "vivado_synthesis": "not_run",
            "vivado_implementation": "not_run",
            "bitstream": "not_run",
        },
        "blocking_requirements": [
            "replace_scaffold_with_qe_kernel_or_workflow_source",
            "attach_qe_golden_vector_manifest",
            "run_hls_csim_or_rtl_sim_against_qe_golden_vectors",
            "run_hls_synthesis_with_real_vivado_or_vitis_hls",
            "run_vivado_synthesis_or_implementation_with_constraints",
            "run_bitstream_or_xclbin_generation_after_timing_closure",
        ],
        "next_actions": [
            "replace_scaffold_with_qe_kernel_or_workflow_source",
            "generate_qe_golden_vectors_for_accelerated_paths",
            "run_hls_csim_or_rtl_sim_against_qe_golden_vectors",
            "run_hls_csynth_and_parse_reports",
            "run_vivado_implementation_and_bitstream_when_platform_constraints_exist",
        ],
        "evidence_boundary": "closure_readiness_contract_only_not_synthesis_or_bitstream_evidence",
    }


def _implementation_closure_summary(materialized_packages: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    blocked_gate_counts: Dict[str, int] = {}
    synthesis_ready = 0
    performance_allowed = 0
    for package in materialized_packages:
        contract = package.get("closure_contract", {}) if isinstance(package.get("closure_contract"), Mapping) else {}
        gates = contract.get("gates", {}) if isinstance(contract.get("gates"), Mapping) else {}
        ready = True
        for gate, status in gates.items():
            status_text = str(status)
            if status_text in {"missing", "not_run", "blocked", "failed"}:
                blocked_gate_counts[str(gate)] = blocked_gate_counts.get(str(gate), 0) + 1
                ready = False
        if ready:
            synthesis_ready += 1
        if bool(contract.get("performance_feedback_allowed", False)):
            performance_allowed += 1
    return {
        "schema_version": "dse.qe_fpga_implementation_closure_summary.v1",
        "package_count": len(materialized_packages),
        "synthesis_ready_count": synthesis_ready,
        "performance_feedback_allowed_count": performance_allowed,
        "blocked_gate_counts": dict(sorted(blocked_gate_counts.items())),
        "evidence_boundary": "closure_summary_only_not_synthesis_or_bitstream_evidence",
    }


def _hls_header_text(package: Mapping[str, Any]) -> str:
    guard = "QE_WORKFLOW_ACCEL_HPP"
    constants = _hls_candidate_constants(package)
    return f"""#ifndef {guard}
#define {guard}

#include <stdint.h>

// Candidate id: {constants['candidate_id']}
// Design key: {constants['design_key']}
// Architecture template: {constants['architecture_template']}

extern "C" void qe_workflow_accel(
    const double *in,
    double *out,
    int n,
    double scale
);

#endif
"""


def _hls_source_text(package: Mapping[str, Any]) -> str:
    constants = _hls_candidate_constants(package)
    return f"""#include "qe_workflow_accel.hpp"

// Candidate id: {constants['candidate_id']}
// Design key: {constants['design_key']}
// Architecture template: {constants['architecture_template']}
// Offload boundary: {constants['offload_boundary']}
// Runtime schedule: {constants['runtime_schedule']}
// Data residency: {constants['data_residency']}
// Memory topology: {constants['memory_topology']}
//
// This is a candidate-bound HLS scaffold. It is an input to HLS/Vivado
// closure, not evidence that the candidate has passed synthesis or timing.

static const int QE_FPGA_VECTOR_LANES = {constants['vector_lanes']};
static const int QE_FPGA_HBM_CHANNELS = {constants['hbm_channels']};
static const int QE_FPGA_TILE_DOUBLES = {constants['tile_doubles']};

extern "C" void qe_workflow_accel(
    const double *in,
    double *out,
    int n,
    double scale
) {{
#pragma HLS INTERFACE m_axi port=in offset=slave bundle=gmem0 depth=1024
#pragma HLS INTERFACE m_axi port=out offset=slave bundle=gmem1 depth=1024
#pragma HLS INTERFACE s_axilite port=in bundle=control
#pragma HLS INTERFACE s_axilite port=out bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=scale bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control

    const int bounded_n = n < 0 ? 0 : n;
workflow_loop:
    for (int i = 0; i < bounded_n; ++i) {{
#pragma HLS PIPELINE II=1
        const double candidate_bias = 0.000001 * static_cast<double>(
            QE_FPGA_VECTOR_LANES + QE_FPGA_HBM_CHANNELS + QE_FPGA_TILE_DOUBLES
        );
        out[i] = in[i] * scale + candidate_bias;
    }}
}}
"""


def _host_stub_text(package: Mapping[str, Any]) -> str:
    constants = _hls_candidate_constants(package)
    return f"""#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>

#include "../hls/qe_workflow_accel.hpp"

int main() {{
    const int n = 64;
    const double scale = 1.25;
    std::vector<double> in(n);
    std::vector<double> out(n, 0.0);
    for (int i = 0; i < n; ++i) {{
        in[i] = static_cast<double>(i + 1);
    }}

    qe_workflow_accel(in.data(), out.data(), n, scale);

    const double candidate_bias = 0.000001 * static_cast<double>(
        {constants['vector_lanes']} + {constants['hbm_channels']} + {constants['tile_doubles']}
    );
    for (int i = 0; i < n; ++i) {{
        const double expected = in[i] * scale + candidate_bias;
        if (std::fabs(out[i] - expected) > 1.0e-12) {{
            std::fprintf(stderr, "mismatch at %d: got %.17g expected %.17g\\n", i, out[i], expected);
            return EXIT_FAILURE;
        }}
    }}

    std::printf("qe_workflow_accel csim smoke passed for candidate {constants['candidate_id']}\\n");
    return EXIT_SUCCESS;
}}
"""


def _hls_tcl_text(package: Mapping[str, Any]) -> str:
    constants = _hls_candidate_constants(package)
    return f"""# Candidate id: {constants['candidate_id']}
# Design key: {constants['design_key']}
# This script runs HLS simulation and synthesis only when a real HLS tool is available.

open_project qe_workflow_accel_hls
set_top qe_workflow_accel
add_files hls/qe_workflow_accel.cpp
add_files -tb host/host_stub.cpp
open_solution solution1
set_part {{xcvu9p-flga2104-2-i}}
create_clock -period 4.0 -name default
csim_design
csynth_design
export_design -format ip_catalog
exit
"""


def _vivado_packaging_tcl_text(package: Mapping[str, Any]) -> str:
    constants = _hls_candidate_constants(package)
    return f"""# Candidate id: {constants['candidate_id']}
# Design key: {constants['design_key']}
# Vivado packaging entrypoint.
# write_bitstream requires a real board part, constraints, and synthesized RTL.

set candidate_id "{constants['candidate_id']}"
set design_key "{constants['design_key']}"
set rtl_dir "qe_workflow_accel_hls/solution1/impl/verilog"
if {{![file exists $rtl_dir]}} {{
    puts "BLOCKED: synthesized RTL directory not found: $rtl_dir"
    puts "Run scripts/run_hls.tcl with a real HLS tool before Vivado packaging."
    exit 2
}}

create_project qe_workflow_accel_vivado vivado_build -part xcvu9p-flga2104-2-i -force
add_files [glob -nocomplain $rtl_dir/*.v]
set_property top qe_workflow_accel [current_fileset]
launch_runs synth_1
wait_on_run synth_1
open_run synth_1
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
# Uncomment only after real board/platform constraints are supplied.
# launch_runs impl_1 -to_step write_bitstream
# wait_on_run impl_1
# write_bitstream -force qe_workflow_accel.bit
exit
"""


def _implementation_package_readme_text(package: Mapping[str, Any]) -> str:
    constants = _hls_candidate_constants(package)
    return f"""# QE FPGA Implementation Package

Candidate id: `{constants['candidate_id']}`

Design key: `{constants['design_key']}`

Architecture template: `{constants['architecture_template']}`

This directory contains candidate-bound HLS/Vivado input files generated from
the QE-to-FPGA DSE promotion path. It is not a synthesis report, implementation
report, board run, xclbin, bitstream, or QE correctness result.

## Files

- `candidate_manifest.json`: candidate parameters, L2 reference metrics, and
  required verification gates.
- `hls/qe_workflow_accel.cpp`: HLS scaffold bound to this candidate.
- `host/host_stub.cpp`: C-simulation smoke test for the scaffold.
- `scripts/run_hls.tcl`: HLS csim/csynth entrypoint.
- `scripts/run_vivado_packaging.tcl`: Vivado synthesis/packaging entrypoint
  that remains blocked until real synthesized RTL and constraints exist.

## Required next gates

1. Replace the scaffold body with QE kernel/workflow-specific compute and
   golden-vector checks for the selected accelerated paths.
2. Run HLS C-sim or RTL simulation against QE golden vectors.
3. Run HLS synthesis and archive latency, II, Fmax estimate, and utilization.
4. Run Vivado synthesis/implementation for a named FPGA part/platform.
5. Generate bitstream/xclbin only after platform constraints and timing close.
6. Feed parsed reports back into the DSE calibration/adjudication stage.
"""


def _hls_attempt_payload(
    *,
    root: Path,
    manifest_path: Path,
    candidate_id: str,
    design_key: str,
    status: str,
    hls_csim_status: str,
    hls_csynth_status: str,
    commands: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
    requested_tool: str,
    resolved_tool: str | None,
    parsed_reports: Mapping[str, Any] | None = None,
    feedback_sample: Mapping[str, Any] | None = None,
    tool_evidence_classification: Mapping[str, Any] | None = None,
    package_evidence_classification: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    classification = dict(tool_evidence_classification or {
        "classification": "tool_unavailable",
        "blockers": ["hls_tool_unavailable"],
        "tool_path": resolved_tool,
    })
    package_classification = dict(package_evidence_classification or {
        "classification": "package_not_classified",
        "blockers": ["package_evidence_not_classified"],
    })
    evidence_gate_summary = _hls_evidence_gate_summary(
        status=status,
        hls_csim_status=hls_csim_status,
        hls_csynth_status=hls_csynth_status,
        blockers=blockers,
        tool_evidence_classification=classification,
        package_evidence_classification=package_classification,
        feedback_sample=feedback_sample,
    )
    return {
        "schema_version": QE_FPGA_HLS_ATTEMPT_SCHEMA,
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "status": status,
        "candidate_id": candidate_id,
        "design_key": design_key,
        "package_root": str(root),
        "hls_csim_status": hls_csim_status,
        "hls_csynth_status": hls_csynth_status,
        "blockers": list(blockers),
        "tool_resolution": {
            "requested_tool": str(Path(requested_tool).resolve()) if "/" in requested_tool else requested_tool,
            "resolved_tool": resolved_tool,
        },
        "commands": [dict(command) for command in commands],
        "tool_evidence_classification": classification,
        "package_evidence_classification": package_classification,
        "evidence_gate_summary": evidence_gate_summary,
        "parsed_reports": dict(parsed_reports or {}),
        "feedback_sample": dict(feedback_sample) if isinstance(feedback_sample, Mapping) else None,
        "report_refs": {
            "candidate_manifest": _file_ref(manifest_path),
            "hls_script": _file_ref(root / "scripts" / "run_hls.tcl"),
            "csynth_report": _file_ref(root / "qe_workflow_accel_hls" / "solution1" / "syn" / "report" / "qe_workflow_accel_csynth.rpt"),
            "vivado_hls_log": _file_ref(root / "vivado_hls.log"),
            "vitis_hls_log": _file_ref(root / "vitis_hls.log"),
        },
        "required_next_tool_steps": [
            "parse_hls_latency_ii_resource_reports",
            "run_vivado_synthesis_or_implementation",
            "run_bitstream_or_xclbin_generation_if_platform_constraints_exist",
            "validate_against_qe_golden_vectors_before_performance_use",
        ],
        "claim_boundary": "hls_attempt_records_tool_execution_only_not_vivado_implementation_or_bitstream_evidence",
    }


def _hls_attempt_summary_row(attempt: Mapping[str, Any], root: Path) -> Dict[str, Any]:
    gate = attempt.get("evidence_gate_summary", {}) if isinstance(attempt.get("evidence_gate_summary"), Mapping) else {}
    package_root = Path(str(attempt.get("package_root", "")))
    try:
        package_dir = str(package_root.relative_to(root))
    except ValueError:
        package_dir = str(package_root)
    return {
        "candidate_id": str(attempt.get("candidate_id", "")),
        "design_key": str(attempt.get("design_key", "")),
        "package_dir": package_dir,
        "attempt_ref": f"{package_dir}/hls_attempt.json",
        "status": str(attempt.get("status", "")),
        "hls_csim_gate": str(gate.get("hls_csim_gate", "")),
        "hls_csynth_gate": str(gate.get("hls_csynth_gate", "")),
        "hls_tool_gate": str(gate.get("hls_tool_gate", "")),
        "source_semantics_gate": str(gate.get("source_semantics_gate", "")),
        "vivado_implementation_gate": str(gate.get("vivado_implementation_gate", "")),
        "bitstream_gate": str(gate.get("bitstream_gate", "")),
        "performance_feedback_allowed": bool(gate.get("performance_feedback_allowed", False)),
        "synthesis_evidence_allowed": bool(gate.get("synthesis_evidence_allowed", False)),
        "blockers": list(gate.get("blockers", []) or []),
    }


def _vivado_attempt_payload(
    *,
    root: Path,
    manifest_path: Path,
    candidate_id: str,
    design_key: str,
    status: str,
    commands: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
    requested_tool: str,
    resolved_tool: str | None,
    rtl_available: bool,
    tool_evidence_classification: Mapping[str, Any],
) -> Dict[str, Any]:
    gate = _vivado_evidence_gate_summary(
        status=status,
        blockers=blockers,
        rtl_available=rtl_available,
        tool_evidence_classification=tool_evidence_classification,
        root=root,
    )
    return {
        "schema_version": QE_FPGA_VIVADO_ATTEMPT_SCHEMA,
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "status": status,
        "candidate_id": candidate_id,
        "design_key": design_key,
        "package_root": str(root),
        "blockers": list(dict.fromkeys(str(item) for item in blockers if str(item))),
        "tool_resolution": {
            "requested_tool": str(Path(requested_tool).resolve()) if "/" in requested_tool else requested_tool,
            "resolved_tool": resolved_tool,
        },
        "commands": [dict(command) for command in commands],
        "tool_evidence_classification": dict(tool_evidence_classification),
        "evidence_gate_summary": gate,
        "report_refs": {
            "candidate_manifest": _file_ref(manifest_path),
            "vivado_script": _file_ref(root / "scripts" / "run_vivado_packaging.tcl"),
            "rtl_dir": _file_ref(root / "qe_workflow_accel_hls" / "solution1" / "impl" / "verilog"),
            "vivado_utilization_report": _file_ref(root / "vivado_utilization.rpt"),
            "vivado_timing_summary_report": _file_ref(root / "vivado_timing_summary.rpt"),
            "bitstream": _file_ref(root / "qe_workflow_accel.bit"),
        },
        "required_next_tool_steps": [
            "complete_hls_csynth_to_materialize_rtl",
            "run_vivado_synthesis_or_implementation",
            "run_bitstream_or_xclbin_generation_if_platform_constraints_exist",
            "parse_timing_utilization_power_reports",
            "validate_against_qe_golden_vectors_before_performance_use",
        ],
        "claim_boundary": "vivado_attempt_records_tool_execution_only_not_bitstream_or_board_evidence",
    }


def _vivado_attempt_summary_row(attempt: Mapping[str, Any], root: Path) -> Dict[str, Any]:
    gate = attempt.get("evidence_gate_summary", {}) if isinstance(attempt.get("evidence_gate_summary"), Mapping) else {}
    package_root = Path(str(attempt.get("package_root", "")))
    try:
        package_dir = str(package_root.relative_to(root))
    except ValueError:
        package_dir = str(package_root)
    return {
        "candidate_id": str(attempt.get("candidate_id", "")),
        "design_key": str(attempt.get("design_key", "")),
        "package_dir": package_dir,
        "attempt_ref": f"{package_dir}/vivado_attempt.json",
        "status": str(attempt.get("status", "")),
        "vivado_tool_gate": str(gate.get("vivado_tool_gate", "")),
        "hls_rtl_gate": str(gate.get("hls_rtl_gate", "")),
        "vivado_synthesis_gate": str(gate.get("vivado_synthesis_gate", "")),
        "vivado_implementation_gate": str(gate.get("vivado_implementation_gate", "")),
        "bitstream_gate": str(gate.get("bitstream_gate", "")),
        "implementation_evidence_allowed": bool(gate.get("implementation_evidence_allowed", False)),
        "bitstream_evidence_allowed": bool(gate.get("bitstream_evidence_allowed", False)),
        "blockers": list(gate.get("blockers", []) or []),
    }


def _count_by_key(rows: Sequence[Mapping[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        value = str(row.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _hls_evidence_gate_summary(
    *,
    status: str,
    hls_csim_status: str,
    hls_csynth_status: str,
    blockers: Sequence[str],
    tool_evidence_classification: Mapping[str, Any],
    package_evidence_classification: Mapping[str, Any],
    feedback_sample: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    tool_allowed = bool(tool_evidence_classification.get("allowed_feedback_use", False))
    package_allowed = bool(package_evidence_classification.get("allowed_feedback_use", False))
    hls_tool_gate = "passed" if tool_allowed else "failed"
    if tool_evidence_classification.get("classification") == "tool_unavailable":
        hls_tool_gate = "blocked"
    source_semantics_gate = "passed" if package_allowed else "failed"
    csim_gate = _gate_from_stage_status(hls_csim_status)
    csynth_gate = _gate_from_stage_status(hls_csynth_status)
    performance_feedback_allowed = (
        status == "hls_attempt_passed"
        and tool_allowed
        and package_allowed
        and csim_gate == "passed"
        and csynth_gate == "passed"
        and isinstance(feedback_sample, Mapping)
    )
    summary_blockers = list(dict.fromkeys(
        list(blockers)
        + [str(item) for item in tool_evidence_classification.get("blockers", []) or []]
        + [str(item) for item in package_evidence_classification.get("blockers", []) or []]
    ))
    return {
        "schema_version": "dse.qe_fpga_hls_evidence_gate_summary.v1",
        "hls_tool_gate": hls_tool_gate,
        "source_semantics_gate": source_semantics_gate,
        "hls_csim_gate": csim_gate,
        "hls_csynth_gate": csynth_gate,
        "vivado_implementation_gate": "not_attempted",
        "bitstream_gate": "not_attempted",
        "performance_feedback_allowed": performance_feedback_allowed,
        "synthesis_evidence_allowed": performance_feedback_allowed,
        "blockers": summary_blockers,
        "required_next_gates": [
            "real_qe_kernel_or_workflow_source",
            "qe_golden_vector_manifest_passed",
            "real_hls_csim_and_csynth",
            "vivado_synthesis_or_implementation",
            "bitstream_or_xclbin_generation",
        ],
        "evidence_boundary": "hls_gate_summary_only_not_vivado_implementation_or_bitstream_evidence",
    }


def _vivado_evidence_gate_summary(
    *,
    status: str,
    blockers: Sequence[str],
    rtl_available: bool,
    tool_evidence_classification: Mapping[str, Any],
    root: Path,
) -> Dict[str, Any]:
    tool_allowed = bool(tool_evidence_classification.get("allowed_implementation_use", False))
    vivado_tool_gate = "passed" if tool_allowed else "failed"
    if tool_evidence_classification.get("classification") == "tool_unavailable":
        vivado_tool_gate = "blocked"
    hls_rtl_gate = "passed" if rtl_available else "blocked"
    utilization_exists = (root / "vivado_utilization.rpt").exists()
    timing_exists = (root / "vivado_timing_summary.rpt").exists()
    bitstream_exists = (root / "qe_workflow_accel.bit").exists()
    command_passed = status == "vivado_attempt_passed"
    synthesis_gate = "passed" if command_passed and utilization_exists else "blocked"
    implementation_gate = "passed" if command_passed and timing_exists else "blocked"
    bitstream_gate = "passed" if command_passed and bitstream_exists else "blocked"
    implementation_allowed = (
        command_passed
        and tool_allowed
        and rtl_available
        and synthesis_gate == "passed"
        and implementation_gate == "passed"
    )
    bitstream_allowed = implementation_allowed and bitstream_gate == "passed"
    summary_blockers = list(dict.fromkeys(
        [str(item) for item in blockers if str(item)]
        + [str(item) for item in tool_evidence_classification.get("blockers", []) or []]
    ))
    if not rtl_available and "hls_synthesized_rtl_missing" not in summary_blockers:
        summary_blockers.append("hls_synthesized_rtl_missing")
    if command_passed and not utilization_exists:
        summary_blockers.append("vivado_utilization_report_missing")
    if command_passed and not timing_exists:
        summary_blockers.append("vivado_timing_summary_missing")
    if command_passed and not bitstream_exists:
        summary_blockers.append("bitstream_missing")
    return {
        "schema_version": "dse.qe_fpga_vivado_evidence_gate_summary.v1",
        "vivado_tool_gate": vivado_tool_gate,
        "hls_rtl_gate": hls_rtl_gate,
        "vivado_synthesis_gate": synthesis_gate,
        "vivado_implementation_gate": implementation_gate,
        "bitstream_gate": bitstream_gate,
        "implementation_evidence_allowed": implementation_allowed,
        "bitstream_evidence_allowed": bitstream_allowed,
        "blockers": summary_blockers,
        "required_next_gates": [
            "real_vivado_tool",
            "hls_synthesized_rtl",
            "vivado_synthesis_reports",
            "vivado_timing_summary",
            "bitstream_or_xclbin_generation",
        ],
        "evidence_boundary": "vivado_gate_summary_only_not_board_or_qe_correctness_evidence",
    }


def _gate_from_stage_status(status: str) -> str:
    if status == "passed":
        return "passed"
    if status == "failed":
        return "failed"
    return "blocked"


def _resolve_hls_tool_request(hls_tool: str | None) -> str:
    if hls_tool:
        return str(hls_tool)
    for candidate in ("vitis_hls", "vivado_hls"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "vitis_hls"


def _resolve_vivado_tool_request(vivado_tool: str | None) -> str:
    if vivado_tool:
        return str(vivado_tool)
    resolved = shutil.which("vivado")
    return resolved if resolved else "vivado"


def _resolve_executable(command: str) -> str | None:
    if "/" in str(command):
        path = Path(command)
        return str(path.resolve()) if path.exists() and path.is_file() else None
    resolved = shutil.which(command)
    return resolved if resolved else None


def _classify_hls_tool_evidence(tool_path: str | None) -> Dict[str, Any]:
    if not tool_path:
        return {
            "classification": "tool_unavailable",
            "tool_path": None,
            "blockers": ["hls_tool_unavailable"],
            "allowed_feedback_use": False,
        }
    resolved = str(Path(tool_path).resolve())
    name = Path(resolved).name.lower()
    blockers: List[str] = []
    if any(marker in name for marker in ("fake", "mock", "stub", "dummy")):
        blockers.append("tool_name_contains_fake_or_mock")
    if not name.endswith("vivado_hls") and not name.endswith("vitis_hls"):
        blockers.append("tool_name_is_not_vivado_hls_or_vitis_hls")
    identity_probe = _probe_hls_tool_identity(resolved)
    if not identity_probe["accepted"]:
        blockers.append("tool_identity_probe_failed")
    if blockers:
        return {
            "classification": "synthetic_or_test_tool",
            "tool_path": resolved,
            "blockers": blockers,
            "identity_probe": identity_probe,
            "allowed_feedback_use": False,
        }
    return {
        "classification": "real_hls_tool",
        "tool_path": resolved,
        "blockers": [],
        "identity_probe": identity_probe,
        "allowed_feedback_use": True,
    }


def _classify_vivado_tool_evidence(tool_path: str | None) -> Dict[str, Any]:
    if not tool_path:
        return {
            "classification": "tool_unavailable",
            "tool_path": None,
            "blockers": ["vivado_tool_unavailable"],
            "allowed_implementation_use": False,
        }
    resolved = str(Path(tool_path).resolve())
    name = Path(resolved).name.lower()
    blockers: List[str] = []
    if any(marker in name for marker in ("fake", "mock", "stub", "dummy")):
        blockers.append("tool_name_contains_fake_or_mock")
    if name != "vivado":
        blockers.append("tool_name_is_not_vivado")
    identity_probe = _probe_vivado_tool_identity(resolved)
    if not identity_probe["accepted"]:
        blockers.append("tool_identity_probe_failed")
    if blockers:
        return {
            "classification": "synthetic_or_test_tool",
            "tool_path": resolved,
            "blockers": blockers,
            "identity_probe": identity_probe,
            "allowed_implementation_use": False,
        }
    return {
        "classification": "real_vivado_tool",
        "tool_path": resolved,
        "blockers": [],
        "identity_probe": identity_probe,
        "allowed_implementation_use": True,
    }


def _probe_hls_tool_identity(tool_path: str) -> Dict[str, Any]:
    """Fail closed unless the HLS executable looks like a real vendor install."""

    resolved = Path(tool_path).resolve()
    path_text = str(resolved).lower()
    name = resolved.name.lower()
    trusted_path = (
        "/xilinx/" in path_text
        or "/vivado/" in path_text
        or "/vitis_hls/" in path_text
        or "/vitis/" in path_text
    )
    command = [str(resolved), "-version"]
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
        returncode = completed.returncode
        output = "\n".join([completed.stdout or "", completed.stderr or ""])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "accepted": False,
            "cmd": command,
            "returncode": 124 if isinstance(exc, subprocess.TimeoutExpired) else None,
            "stdout_tail": "",
            "stderr_tail": str(exc)[-1000:],
            "trusted_install_path": trusted_path,
            "version_banner_detected": False,
            "reason": "version_probe_failed",
        }
    version_banner_detected = (
        ("vivado hls" in output.lower() or "vitis hls" in output.lower())
        and ("xilinx" in output.lower() or name in {"vivado_hls", "vitis_hls"})
    )
    accepted = returncode == 0 and trusted_path and version_banner_detected
    reason = "accepted_vendor_install_probe" if accepted else "untrusted_path_or_missing_vendor_version_banner"
    return {
        "accepted": accepted,
        "cmd": command,
        "returncode": returncode,
        "stdout_tail": (completed.stdout or "")[-1000:],
        "stderr_tail": (completed.stderr or "")[-1000:],
        "trusted_install_path": trusted_path,
        "version_banner_detected": version_banner_detected,
        "reason": reason,
    }


def _probe_vivado_tool_identity(tool_path: str) -> Dict[str, Any]:
    """Fail closed unless the Vivado executable looks like a real vendor install."""

    resolved = Path(tool_path).resolve()
    path_text = str(resolved).lower()
    trusted_path = (
        "/xilinx/" in path_text
        or "/vivado/" in path_text
        or "/vitis/" in path_text
    )
    command = [str(resolved), "-version"]
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
        returncode = completed.returncode
        output = "\n".join([completed.stdout or "", completed.stderr or ""])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "accepted": False,
            "cmd": command,
            "returncode": 124 if isinstance(exc, subprocess.TimeoutExpired) else None,
            "stdout_tail": "",
            "stderr_tail": str(exc)[-1000:],
            "trusted_install_path": trusted_path,
            "version_banner_detected": False,
            "reason": "version_probe_failed",
        }
    version_banner_detected = "vivado" in output.lower() and "xilinx" in output.lower()
    accepted = returncode == 0 and trusted_path and version_banner_detected
    reason = "accepted_vendor_install_probe" if accepted else "untrusted_path_or_missing_vendor_version_banner"
    return {
        "accepted": accepted,
        "cmd": command,
        "returncode": returncode,
        "stdout_tail": (completed.stdout or "")[-1000:],
        "stderr_tail": (completed.stderr or "")[-1000:],
        "trusted_install_path": trusted_path,
        "version_banner_detected": version_banner_detected,
        "reason": reason,
    }


def _classify_hls_package_evidence(root: Path) -> Dict[str, Any]:
    manifest = _load_json_object(root / "candidate_manifest.json")
    source_kind = str(manifest.get("source_semantics", {}).get("source_kind", "")) if isinstance(manifest.get("source_semantics"), Mapping) else ""
    blockers: List[str] = []
    if source_kind != "qe_kernel_or_workflow_implementation":
        blockers.append("kernel_source_is_candidate_bound_scaffold")
    golden = _load_optional_json_object(root / "qe_golden_vectors_manifest.json")
    if not golden:
        blockers.append("qe_golden_vector_manifest_missing")
    elif golden.get("status") != "passed":
        blockers.append("qe_golden_vector_manifest_not_passed")
    if blockers:
        return {
            "classification": "scaffold_sources_only",
            "source_kind": source_kind or "unknown",
            "golden_vector_manifest": _file_ref(root / "qe_golden_vectors_manifest.json"),
            "blockers": blockers,
            "allowed_feedback_use": False,
        }
    return {
        "classification": "qe_kernel_with_golden_vectors",
        "source_kind": source_kind,
        "golden_vector_manifest": _file_ref(root / "qe_golden_vectors_manifest.json"),
        "blockers": [],
        "allowed_feedback_use": True,
    }


def _load_optional_json_object(path: Path) -> Dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else None


def _run_process(command: Sequence[str], *, cwd: Path, timeout_s: int) -> Dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        status = "passed" if returncode == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\ntimeout after {timeout_s}s"
        status = "timeout"
    except OSError as exc:
        returncode = 127
        stdout = ""
        stderr = str(exc)
        status = "failed_to_start"
    return {
        "command": list(command),
        "command_text": " ".join(str(item) for item in command),
        "status": status,
        "returncode": returncode,
        "started_at": _now_utc_iso(),
        "elapsed_s": round(time.time() - started, 3),
        "stdout_tail": stdout[-8000:],
        "stderr_tail": stderr[-8000:],
    }


def _hls_stage_status(transcript: str, *, stage: str) -> str:
    upper = transcript.upper()
    if "ERROR" in upper or "FAILED" in upper:
        return "failed"
    if stage == "csim" and ("CSIM_DESIGN PASS" in upper or "CSIM PASS" in upper):
        return "passed"
    if stage == "csynth" and ("CSYNTH_DESIGN PASS" in upper or "CSYNTH PASS" in upper):
        return "passed"
    return "blocked"


def _hls_parsed_reports(root: Path) -> Dict[str, Any]:
    csynth_report = root / "qe_workflow_accel_hls" / "solution1" / "syn" / "report" / "qe_workflow_accel_csynth.rpt"
    return {
        "csynth": _parse_hls_csynth_report(csynth_report),
    }


def _parse_hls_csynth_report(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {
            "status": "missing_report",
            "path": str(path),
            "resource_estimates": {},
        }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "status": "unreadable_report",
            "path": str(path),
            "error": str(exc),
            "resource_estimates": {},
        }

    latency_min, latency_max = _parse_hls_latency_cycles(text)
    initiation_interval = _parse_hls_int(text, [
        r"\bInterval\s+Min\s*[:=]\s*([0-9]+)",
        r"\bInterval\s*\(cycles\)\s*[:=]\s*min\s*=\s*([0-9]+)",
        r"\bII\s*[:=]\s*([0-9]+)",
    ])
    clock_period_ns = _parse_hls_float(text, [
        r"\bTiming\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*ns\b",
        r"\bTarget\s+clock\s+period\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*ns\b",
        r"\bClock\s+Period\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*ns\b",
    ])
    resources = {
        "bram_18k": _parse_hls_int(text, [r"\bBRAM_18K\s*[:|]\s*([0-9]+)"]),
        "dsp": _parse_hls_int(text, [r"\bDSP48E?\s*[:|]\s*([0-9]+)", r"\bDSP\s*[:|]\s*([0-9]+)"]),
        "ff": _parse_hls_int(text, [r"\bFF\s*[:|]\s*([0-9]+)"]),
        "lut": _parse_hls_int(text, [r"\bLUT\s*[:|]\s*([0-9]+)"]),
        "uram": _parse_hls_int(text, [r"\bURAM\s*[:|]\s*([0-9]+)"]),
    }
    resources = {
        key: value
        for key, value in resources.items()
        if value is not None
    }
    parsed = {
        "status": "parsed",
        "path": str(path),
        "latency_cycles_min": latency_min,
        "latency_cycles_max": latency_max,
        "initiation_interval": initiation_interval,
        "clock_period_ns": clock_period_ns,
        "resource_estimates": resources,
    }
    missing = [
        key for key in ("latency_cycles_max", "clock_period_ns")
        if parsed.get(key) is None
    ]
    if missing:
        parsed["status"] = "partial"
        parsed["missing_fields"] = missing
    return parsed


def _parse_hls_latency_cycles(text: str) -> Tuple[int | None, int | None]:
    patterns = [
        r"\bLatency\s*\(cycles\)\s*[:=]\s*min\s*=\s*([0-9]+)\s+max\s*=\s*([0-9]+)",
        r"\bLatency\s*[:=]\s*min\s*=\s*([0-9]+)\s+max\s*=\s*([0-9]+)",
        r"\bLatency\s*\(cycles\)\s*[:=]\s*([0-9]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if len(match.groups()) >= 2:
            return int(match.group(1)), int(match.group(2))
        value = int(match.group(1))
        return value, value
    return None, None


def _parse_hls_int(text: str, patterns: Sequence[str]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _parse_hls_float(text: str, patterns: Sequence[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _hls_feedback_sample_from_parsed_report(
    csynth_report: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    candidate_id: str,
    design_key: str,
    tool_path: str,
    tool_evidence_classification: Mapping[str, Any],
    package_evidence_classification: Mapping[str, Any],
) -> Dict[str, Any] | None:
    if csynth_report.get("status") not in {"parsed", "partial"}:
        return None
    latency_cycles = csynth_report.get("latency_cycles_max")
    clock_period_ns = csynth_report.get("clock_period_ns")
    if latency_cycles is None or clock_period_ns is None:
        return None
    latency_ms = _finite_float(latency_cycles, default=0.0) * _finite_float(clock_period_ns, default=0.0) / 1_000_000.0
    if latency_ms <= 0.0:
        return None
    resources = csynth_report.get("resource_estimates", {}) if isinstance(csynth_report.get("resource_estimates"), Mapping) else {}
    resource_pressure = _hls_resource_pressure(resources)
    reference_energy_mj = _hls_reference_energy_mj(manifest, latency_ms, resource_pressure)
    metrics = {
        "latency_ms": _round_metric(latency_ms),
        "workflow_wall_time_ms": _round_metric(latency_ms),
        "energy_mj": _round_metric(reference_energy_mj),
        "edp": _round_metric(latency_ms * reference_energy_mj),
        "resource_pressure": _round_metric(resource_pressure),
    }
    return {
        "schema_version": "dse.qe_fpga_hls_feedback_sample.v1",
        "sample_id": f"hls_csynth_{candidate_id}",
        "candidate_id": candidate_id,
        "design_key": design_key,
        "status": "passed",
        "fidelity": "HLS_c_synthesis",
        "metrics": metrics,
        "provenance": {
            "tool": tool_path,
            "report_path": str(csynth_report.get("path", "")),
            "source_report_status": str(csynth_report.get("status", "")),
            "latency_source": "csynth_latency_cycles_max_times_clock_period",
            "energy_source": "bounded_reference_estimate_from_latency_and_resource_pressure",
            "candidate_manifest": str(manifest.get("package_id", "")),
        },
        "tool_evidence_classification": dict(tool_evidence_classification),
        "package_evidence_classification": dict(package_evidence_classification),
        "claim_boundary": "hls_feedback_sample_only_not_vivado_or_bitstream_evidence",
    }


def _hls_resource_pressure(resources: Mapping[str, Any]) -> float:
    bram = _finite_float(resources.get("bram_18k"), default=0.0)
    dsp = _finite_float(resources.get("dsp"), default=0.0)
    ff = _finite_float(resources.get("ff"), default=0.0)
    lut = _finite_float(resources.get("lut"), default=0.0)
    uram = _finite_float(resources.get("uram"), default=0.0)
    pressure = 0.0
    pressure += bram / 4320.0
    pressure += dsp / 6840.0
    pressure += ff / 2_364_480.0
    pressure += lut / 1_182_240.0
    pressure += uram / 960.0
    return max(0.0, min(2.0, pressure))


def _hls_reference_energy_mj(
    manifest: Mapping[str, Any],
    latency_ms: float,
    resource_pressure: float,
) -> float:
    parameters = manifest.get("candidate_parameters", {}) if isinstance(manifest.get("candidate_parameters"), Mapping) else {}
    architecture = _model(_ARCHITECTURE_MODELS, parameters.get("architecture_template"))
    power_w = _finite_float(architecture.get("power_w"), default=28.0)
    adjusted_power_w = power_w * (1.0 + min(1.0, max(0.0, resource_pressure)) * 0.15)
    return max(1.0e-9, latency_ms / 1000.0 * adjusted_power_w * 1000.0)


def _file_ref(path: Path) -> Dict[str, Any]:
    exists = path.exists() and path.is_file()
    return {
        "path": str(path),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
    }


def _load_json_object(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hls_candidate_constants(package: Mapping[str, Any]) -> Dict[str, Any]:
    parameters = package.get("candidate_parameters", {}) if isinstance(package.get("candidate_parameters"), Mapping) else {}
    memory_topology = str(parameters.get("memory_topology", "ddr_streaming"))
    architecture_template = str(parameters.get("architecture_template", "fpga_hybrid_cpu_control_accel_kernels"))
    default_hbm_channels = 8 if memory_topology == "hbm_multi_channel" else 0
    if architecture_template == "fpga_hbm_streaming_dataflow":
        default_vector_lanes = 8
    elif architecture_template == "fpga_fft_transpose_pipeline":
        default_vector_lanes = 4
    else:
        default_vector_lanes = 2
    if memory_topology == "bram_uram_tiled_locality":
        default_tile_doubles = 4096
    elif memory_topology == "hbm_multi_channel":
        default_tile_doubles = 2048
    else:
        default_tile_doubles = 1024
    hbm_channels = _bounded_choice_int(
        parameters.get("hbm_channel_count"),
        allowed=(0, 4, 8),
        default=default_hbm_channels,
    )
    vector_lanes = _bounded_choice_int(
        parameters.get("vector_lanes"),
        allowed=(2, 4, 8),
        default=default_vector_lanes,
    )
    tile_doubles = _bounded_choice_int(
        parameters.get("tile_doubles"),
        allowed=(1024, 2048, 4096),
        default=default_tile_doubles,
    )
    return {
        "candidate_id": _cpp_comment_safe(str(package.get("candidate_id", ""))),
        "design_key": _cpp_comment_safe(str(package.get("design_key", ""))),
        "architecture_template": _cpp_comment_safe(architecture_template),
        "offload_boundary": _cpp_comment_safe(str(parameters.get("offload_boundary", ""))),
        "runtime_schedule": _cpp_comment_safe(str(parameters.get("runtime_schedule", ""))),
        "data_residency": _cpp_comment_safe(str(parameters.get("data_residency", ""))),
        "memory_topology": _cpp_comment_safe(memory_topology),
        "vector_lanes": vector_lanes,
        "hbm_channels": hbm_channels,
        "tile_doubles": tile_doubles,
    }


def _cpp_comment_safe(value: str) -> str:
    return str(value).replace("\n", " ").replace("\r", " ").replace("*/", "* /")


def _implementation_kernel_interfaces(request: Mapping[str, Any]) -> List[Dict[str, Any]]:
    payload = request.get("request_payload", {}) if isinstance(request.get("request_payload"), Mapping) else {}
    graph = payload.get("graph", {}) if isinstance(payload.get("graph"), Mapping) else {}
    nodes = graph.get("nodes", {}) if isinstance(graph.get("nodes"), Mapping) else {}
    kernels: Dict[str, Dict[str, Any]] = {}
    for node in nodes.values():
        if not isinstance(node, Mapping):
            continue
        for kernel in node.get("kernels", []) or []:
            kernel_id = str(kernel)
            kernels.setdefault(kernel_id, {
                "kernel_id": kernel_id,
                "interface": "ap_ctrl_hs_axi_stream_memory",
                "dtype": "complex_fp64_or_fp64",
                "host_visible": True,
            })
    if not kernels:
        kernels["workflow_accel"] = {
            "kernel_id": "workflow_accel",
            "interface": "ap_ctrl_hs_axi_stream_memory",
            "dtype": "complex_fp64_or_fp64",
            "host_visible": True,
        }
    return [kernels[key] for key in sorted(kernels)]


def _evaluate_l2_request(request: Mapping[str, Any], index: int) -> Dict[str, Any]:
    payload = request.get("request_payload", {}) if isinstance(request.get("request_payload"), Mapping) else {}
    graph = payload.get("graph", {}) if isinstance(payload.get("graph"), Mapping) else {}
    architecture = payload.get("architecture", {}) if isinstance(payload.get("architecture"), Mapping) else {}
    deployment = payload.get("deployment", {}) if isinstance(payload.get("deployment"), Mapping) else {}
    l1_metrics = request.get("candidate_l1_metrics", {}) if isinstance(request.get("candidate_l1_metrics"), Mapping) else {}

    nodes = graph.get("nodes", {}) if isinstance(graph.get("nodes"), Mapping) else {}
    edges = graph.get("edges", []) if isinstance(graph.get("edges"), list) else []
    total_stage_ms = sum(
        _finite_float(node.get("estimated_weight_ms"), default=1.0)
        for node in nodes.values()
        if isinstance(node, Mapping)
    )
    total_data_mb = sum(
        _finite_float(edge.get("data_mb"), default=0.0)
        for edge in edges
        if isinstance(edge, Mapping)
    )
    parameters = request.get("candidate_parameters", {}) if isinstance(request.get("candidate_parameters"), Mapping) else {}
    boundary = _model(_BOUNDARY_MODELS, deployment.get("offload_boundary") or parameters.get("offload_boundary"))
    arch_model = _model(_ARCHITECTURE_MODELS, deployment.get("architecture_template") or parameters.get("architecture_template"))
    schedule = _model(_SCHEDULE_MODELS, deployment.get("runtime_schedule") or parameters.get("runtime_schedule"))
    residency = _model(_RESIDENCY_MODELS, deployment.get("data_residency") or parameters.get("data_residency"))
    memory = _model(_MEMORY_MODELS, deployment.get("memory_topology") or parameters.get("memory_topology"))
    vector_lanes = _bounded_choice_int(parameters.get("vector_lanes"), allowed=(2, 4, 8), default=2)
    hbm_channel_count = _bounded_choice_int(parameters.get("hbm_channel_count"), allowed=(0, 4, 8), default=0)
    tile_doubles = _bounded_choice_int(parameters.get("tile_doubles"), allowed=(1024, 2048, 4096), default=1024)

    accelerated_fraction = min(0.86, _finite_float(boundary.get("accelerated_fraction"), default=0.45) * 0.94)
    speedup = max(
        1.0,
        _finite_float(arch_model.get("speedup"), default=2.0)
        * _finite_float(residency.get("reuse_factor"), default=1.0)
        * {2: 0.94, 4: 1.00, 8: 1.08}.get(vector_lanes, 1.0)
        * {1024: 0.97, 2048: 1.00, 4096: 1.03}.get(tile_doubles, 1.0)
        * 0.88,
    )
    retained_ms = total_stage_ms * (1.0 - accelerated_fraction)
    accelerated_ms = total_stage_ms * accelerated_fraction / speedup
    transaction_count = max(1.0, float(len(edges) + len(nodes)))
    bandwidth_gbps = max(0.1, _finite_float(memory.get("bandwidth_gbps"), default=16.0))
    if (deployment.get("memory_topology") or parameters.get("memory_topology")) == "hbm_multi_channel":
        bandwidth_gbps *= max(0.25, hbm_channel_count / 8.0)
    movement_mb = max(0.25, total_data_mb * _finite_float(residency.get("movement_multiplier"), default=1.0) * _finite_float(boundary.get("transfer_multiplier"), default=1.0))
    transfer_ms = movement_mb / bandwidth_gbps + transaction_count * 0.018
    visible_transfer_ms = transfer_ms * _finite_float(schedule.get("transfer_visible_fraction"), default=1.0)
    host_sync_ms = _finite_float(schedule.get("control_overhead_ms"), default=20.0) + _finite_float(boundary.get("host_sync_ms"), default=20.0)
    workload_features = request.get("workload_features", {}) if isinstance(request.get("workload_features"), Mapping) else {}
    host_control_intensity = _finite_float(workload_features.get("host_control_intensity"), default=0.0)
    post_processing_intensity = _finite_float(workload_features.get("post_processing_intensity"), default=0.0)
    data_scale = _finite_float(workload_features.get("variant_data_scale"), default=1.0)
    host_sync_ms += host_control_intensity * _host_control_penalty_ms(parameters)
    host_sync_ms += post_processing_intensity * _post_processing_penalty_ms(parameters)
    wall_time_ms = retained_ms + accelerated_ms + visible_transfer_ms + host_sync_ms

    power_w = _finite_float(arch_model.get("power_w"), default=25.0)
    cpu_energy_mj = retained_ms / 1000.0 * 18.0 * 1000.0
    fpga_energy_mj = accelerated_ms / 1000.0 * power_w * 1000.0
    movement_energy_mj = movement_mb * _finite_float(memory.get("energy_per_mb_mj"), default=0.02) * 1.12
    energy_mj = cpu_energy_mj + fpga_energy_mj + movement_energy_mj
    l1_resource_pressure = _finite_float(l1_metrics.get("fpga_resource_pressure"), default=0.5)
    residual_resource_pressure = 0.20 * _workflow_resource_penalty(
        parameters,
        data_scale,
        host_control_intensity,
        post_processing_intensity,
    )
    residual_resource_pressure += 0.15 * (
        {2: 0.00, 4: 0.03, 8: 0.08}.get(vector_lanes, 0.0)
        + {0: 0.00, 4: 0.04, 8: 0.08}.get(hbm_channel_count, 0.0)
        + {1024: 0.00, 2048: 0.03, 4096: 0.07}.get(tile_doubles, 0.0)
    )
    resource_pressure = l1_resource_pressure * 1.04 + residual_resource_pressure
    status = "passed" if resource_pressure <= 1.05 else "failed"
    feasibility_multiplier = 1.0 + max(0.0, resource_pressure - 1.05) * 2.5
    tlm_edp = wall_time_ms * energy_mj * feasibility_multiplier
    return {
        "schema_version": "dse.qe_fpga_l2_tlm_result.v1",
        "request_id": str(request.get("request_id") or f"qe_fpga_l2_req_{index:03d}"),
        "candidate_id": str(request.get("candidate_id", "")),
        "design_key": str(request.get("design_key", "")),
        "status": status,
        "fidelity": "L2_python_tlm",
        "metrics": {
            "tlm_workflow_wall_time_ms": _round_metric(wall_time_ms),
            "tlm_energy_mj": _round_metric(energy_mj),
            "tlm_edp": _round_metric(tlm_edp),
            "tlm_data_movement_mb": _round_metric(movement_mb),
            "tlm_visible_transfer_time_ms": _round_metric(visible_transfer_ms),
            "tlm_cpu_retained_stage_time_ms": _round_metric(retained_ms),
            "tlm_accelerated_stage_time_ms": _round_metric(accelerated_ms),
            "tlm_resource_pressure": _round_metric(resource_pressure),
        },
        "l1_reference_metrics": dict(l1_metrics),
        "model_diagnostics": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "transaction_count": _round_metric(transaction_count),
            "accelerated_fraction": _round_metric(accelerated_fraction),
            "effective_speedup": _round_metric(speedup),
            "vector_lanes": vector_lanes,
            "hbm_channel_count": hbm_channel_count,
            "tile_doubles": tile_doubles,
        },
        "claim_boundary": "l2_tlm_candidate_result_not_systemc_gem5_or_fpga_evidence",
    }


def _build_l2_request(
    *,
    manifest: Mapping[str, Any],
    problem_payload: Mapping[str, Any],
    workload_features: Mapping[str, Any],
    promoted_row: Mapping[str, Any],
    index: int,
) -> Dict[str, Any]:
    parameters = promoted_row.get("parameters", {}) if isinstance(promoted_row.get("parameters"), Mapping) else {}
    metrics = promoted_row.get("metrics", {}) if isinstance(promoted_row.get("metrics"), Mapping) else {}
    candidate_id = str(promoted_row.get("candidate_id") or f"qe_fpga_l2_request_{index:03d}")
    design_key = str(promoted_row.get("design_key") or _design_key(parameters))
    workflow_feature_contract = _workload_feature_contract_binding(workload_features)
    return {
        "schema_version": "dse.qe_fpga_l2_evaluation_request.v1",
        "request_id": f"qe_fpga_l2_req_{index:03d}",
        "candidate_id": candidate_id,
        "design_key": design_key,
        "problem_id": str(problem_payload.get("problem_id", "")),
        "workload_run_id": str(problem_payload.get("workload_run_id", "")),
        "candidate_parameters": dict(parameters),
        "candidate_l1_metrics": dict(metrics),
        "workload_features": _public_workload_features_for_request(workload_features),
        "workflow_feature_contract": workflow_feature_contract,
        "simulation_intent": {
            "backend_candidates": ["tlm", "systemc"],
            "fidelity_role": "calibrate_l1_and_rank_promoted_candidates",
            "evaluate_host_device_transfers": True,
            "evaluate_cpu_retained_stages": True,
            "evaluate_data_residency": True,
            "requires_real_qe_correctness": False,
            "requires_vivado_or_hls": False,
        },
        "request_payload": {
            "schema_version": "dse.qe_fpga_l2_request_payload.v1",
            "run_id": f"{candidate_id}:l2",
            "graph": _request_graph(manifest, workload_features),
            "workflow_feature_contract": workflow_feature_contract,
            "architecture": _request_architecture(parameters),
            "deployment": _request_deployment(parameters),
            "metrics_requested": [
                "workflow_wall_time_ms",
                "energy_mj",
                "edp",
                "data_movement_mb",
                "resource_pressure",
                "host_device_transfer_time_ms",
                "cpu_retained_stage_time_ms",
            ],
        },
        "execution_allowed": False,
        "claim_boundary": "l2_request_only_not_executed_systemc_or_fpga_evidence",
    }


def _public_workload_features_for_request(features: Mapping[str, Any]) -> Dict[str, Any]:
    public = copy.deepcopy(dict(features))
    public.pop("workflow_feature_contract_detail", None)
    return public


def _request_graph(manifest: Mapping[str, Any], features: Mapping[str, Any]) -> Dict[str, Any]:
    contract_graph = _request_graph_from_workflow_feature_contract(features)
    if contract_graph:
        return contract_graph
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    last_node_for_case: Dict[str, str] = {}
    for case in manifest.get("cases", []) or []:
        if not isinstance(case, Mapping):
            continue
        case_id = str(case.get("case_id") or f"case_{len(last_node_for_case):03d}")
        sequence = [step for step in case.get("baseline_sequence", []) or [] if isinstance(step, Mapping)]
        if not sequence:
            sequence = [{"step_id": str(case.get("stage_type", "stage")), "stage_type": str(case.get("stage_type", "stage"))}]
        previous_node_id = ""
        for index, step in enumerate(sequence):
            stage_type = str(step.get("stage_type") or step.get("program") or case.get("stage_type") or "stage")
            stage_id = str(step.get("step_id") or index)
            node_id = f"{case_id}:{stage_id}"
            kernels = list(case.get("kernel_coverage", []) or [])
            nodes[node_id] = {
                "node_id": node_id,
                "case_id": case_id,
                "stage_type": stage_type,
                "workflow_class": _stage_class(stage_type),
                "program": str(step.get("program") or ""),
                "kernels": kernels,
                "estimated_weight_ms": _stage_weight_ms(stage_type, features, kernels, stage_id=stage_id),
                "host_retained_allowed": True,
            }
            if previous_node_id:
                edges.append({
                    "source": previous_node_id,
                    "target": node_id,
                    "edge_kind": "workflow_sequence",
                    "data_mb": _edge_data_mb(features),
                })
            previous_node_id = node_id
        if previous_node_id:
            last_node_for_case[case_id] = previous_node_id
    return {
        "schema_version": "dse.qe_workflow_request_graph.v1",
        "source": (
            "workflow_feature_contract"
            if _workload_feature_contract_binding(features).get("schema_version")
            else "qe_mainflow_manifest"
        ),
        "workflow_feature_contract": _workload_feature_contract_binding(features),
        "nodes": nodes,
        "edges": edges,
        "workflow_classes": list(features.get("workflow_classes", []) or []),
        "claim_boundary": "request_graph_for_l2_modeling_not_qe_execution_trace",
    }


def _request_graph_from_workflow_feature_contract(features: Mapping[str, Any]) -> Dict[str, Any]:
    contract = features.get("workflow_feature_contract_detail", {})
    if not isinstance(contract, Mapping) or not contract.get("schema_version"):
        contract = features.get("workflow_feature_contract", {})
    if not isinstance(contract, Mapping) or not contract.get("schema_version"):
        return {}
    workflow_dag = contract.get("workflow_dag", {}) if isinstance(contract.get("workflow_dag"), Mapping) else {}
    raw_stages = workflow_dag.get("stages", []) if isinstance(workflow_dag.get("stages"), list) else []
    if not raw_stages:
        return {}
    stage_features = {
        str(row.get("stage_id", "")): row
        for row in (contract.get("stage_feature_table", []) if isinstance(contract.get("stage_feature_table"), list) else [])
        if isinstance(row, Mapping) and row.get("stage_id")
    }
    compute_table = (
        contract.get("stage_compute_feature_table", {})
        if isinstance(contract.get("stage_compute_feature_table"), Mapping)
        else {}
    )
    nodes: Dict[str, Dict[str, Any]] = {}
    for index, raw_stage in enumerate(raw_stages):
        if not isinstance(raw_stage, Mapping):
            continue
        stage_id = str(raw_stage.get("stage_id") or raw_stage.get("id") or f"stage_{index:03d}")
        if not stage_id:
            continue
        feature_row = stage_features.get(stage_id, {})
        stage_type = str(feature_row.get("stage_type") or raw_stage.get("stage_type") or stage_id)
        stage_class = str(feature_row.get("stage_class") or raw_stage.get("stage_class") or _stage_class(stage_type))
        stage_compute_rows = compute_table.get(stage_id, []) if isinstance(compute_table, Mapping) else []
        kernels = [
            str(item)
            for item in (
                feature_row.get("compute_ids")
                or feature_row.get("kernels")
                or raw_stage.get("compute_ids")
                or raw_stage.get("kernels")
                or [row.get("compute_id", "") for row in stage_compute_rows if isinstance(row, Mapping)]
            )
            if str(item)
        ]
        nodes[stage_id] = {
            "node_id": stage_id,
            "stage_id": stage_id,
            "stage_type": stage_type,
            "workflow_class": stage_class,
            "stage_class": stage_class,
            "program": str(feature_row.get("program") or raw_stage.get("program") or stage_type),
            "kernels": kernels,
            "expected_repetition": int(_finite_float(
                feature_row.get("expected_repetition", raw_stage.get("expected_repetition", 1)),
                default=1.0,
            )),
            "estimated_weight_ms": _stage_weight_ms(stage_type, features, kernels, stage_id=stage_id),
            "host_retained_allowed": True,
        }
    raw_edges = workflow_dag.get("edges", []) if isinstance(workflow_dag.get("edges"), list) else []
    edges: List[Dict[str, Any]] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, Mapping):
            continue
        source = str(raw_edge.get("source_stage") or raw_edge.get("source") or "")
        target = str(raw_edge.get("target_stage") or raw_edge.get("target") or "")
        if not source or not target or source not in nodes or target not in nodes:
            continue
        edges.append({
            "source": source,
            "target": target,
            "edge_kind": str(raw_edge.get("edge_kind") or raw_edge.get("kind") or "workflow_dependency"),
            "data_mb": _edge_data_mb(features),
        })
    data_object_edges = _contract_data_object_edges(contract, nodes)
    edges.extend(data_object_edges)
    return {
        "schema_version": "dse.qe_workflow_request_graph.v1",
        "source": "workflow_feature_contract",
        "workflow_feature_contract": _workload_feature_contract_binding(features),
        "nodes": nodes,
        "edges": edges,
        "workflow_classes": list(features.get("workflow_classes", []) or []),
        "claim_boundary": "request_graph_for_l2_modeling_not_qe_execution_trace",
    }


def _contract_data_object_edges(
    contract: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    data_objects = contract.get("data_object_table", [])
    if not isinstance(data_objects, list):
        return []
    edges: List[Dict[str, Any]] = []
    emitted: set[Tuple[str, str, str]] = set()
    for row in data_objects:
        if not isinstance(row, Mapping):
            continue
        object_id = str(row.get("object_id") or row.get("tensor_name") or "")
        if not object_id:
            continue
        object_bytes = int(max(0.0, _finite_float(row.get("bytes"), default=0.0)))
        data_mb = round(object_bytes / 1.0e6, 6) if object_bytes > 0 else 0.0
        producer_stages = [str(item) for item in row.get("producer_stages", []) or []]
        consumer_stages = [str(item) for item in row.get("consumer_stages", []) or []]
        for source in producer_stages:
            if source not in nodes:
                continue
            for target in consumer_stages:
                if target not in nodes or target == source:
                    continue
                edge_key = (object_id, source, target)
                if edge_key in emitted:
                    continue
                emitted.add(edge_key)
                edge = {
                    "source": source,
                    "target": target,
                    "edge_kind": "data_object_lifetime",
                    "object_id": object_id,
                    "object_bytes": object_bytes,
                    "data_mb": data_mb,
                }
                object_kind = row.get("object_kind")
                if object_kind:
                    edge["object_kind"] = str(object_kind)
                residency = row.get("residency_constraint") or row.get("preferred_residency_hint")
                if residency:
                    edge["residency_constraint"] = str(residency)
                edges.append(edge)
    return edges


def _request_architecture(parameters: Mapping[str, Any]) -> Dict[str, Any]:
    template = str(parameters.get("architecture_template", "fpga_hybrid_cpu_control_accel_kernels"))
    memory_topology = str(parameters.get("memory_topology", "ddr_streaming"))
    memory = _model(_MEMORY_MODELS, memory_topology)
    architecture = _model(_ARCHITECTURE_MODELS, template)
    return {
        "schema_version": "dse.qe_fpga_l2_architecture_request.v1",
        "template": template,
        "accelerators": [
            {
                "accel_id": "host_cpu",
                "accel_type": "cpu",
                "role": "scf_control_and_retained_stages",
                "estimated_power_w": 18.0,
            },
            {
                "accel_id": "candidate_fpga",
                "accel_type": "fpga",
                "role": template,
                "memory_topology": memory_topology,
                "estimated_power_w": _finite_float(architecture.get("power_w"), default=25.0),
                "estimated_bandwidth_gbps": _finite_float(memory.get("bandwidth_gbps"), default=10.0),
            },
        ],
        "interconnect": {
            "kind": "host_fpga_pcie_or_platform_link",
            "model_role": "host_device_transfer_and_sync_accounting",
        },
    }


def _request_deployment(parameters: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": "dse.qe_fpga_l2_deployment_request.v1",
        "deployment_target": str(parameters.get("deployment_target", "fpga")),
        "architecture_template": str(parameters.get("architecture_template", "")),
        "offload_boundary": str(parameters.get("offload_boundary", "")),
        "mapping_granularity": str(parameters.get("mapping_granularity", "")),
        "runtime_schedule": str(parameters.get("runtime_schedule", "")),
        "data_residency": str(parameters.get("data_residency", "")),
        "memory_topology": str(parameters.get("memory_topology", "")),
        "precision_policy": str(parameters.get("precision_policy", "")),
    }


def _evaluate_candidate(
    features: Mapping[str, Any],
    constraints: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> Dict[str, Any]:
    parameters = _candidate_parameters(candidate)
    boundary = _model(_BOUNDARY_MODELS, parameters.get("offload_boundary"))
    architecture = _model(_ARCHITECTURE_MODELS, parameters.get("architecture_template"))
    schedule = _model(_SCHEDULE_MODELS, parameters.get("runtime_schedule"))
    residency = _model(_RESIDENCY_MODELS, parameters.get("data_residency"))
    memory = _model(_MEMORY_MODELS, parameters.get("memory_topology"))
    mapping = _model(_MAPPING_MODELS, parameters.get("mapping_granularity"))
    vector_lanes = _bounded_choice_int(parameters.get("vector_lanes"), allowed=(2, 4, 8), default=2)
    hbm_channel_count = _bounded_choice_int(parameters.get("hbm_channel_count"), allowed=(0, 4, 8), default=0)
    tile_doubles = _bounded_choice_int(parameters.get("tile_doubles"), allowed=(1024, 2048, 4096), default=1024)

    total_ms = _finite_float(features.get("estimated_baseline_workflow_wall_time_ms"), default=1.0)
    kernel_weights = features.get("kernel_weights", {}) if isinstance(features.get("kernel_weights"), Mapping) else {}
    affinity = _kernel_affinity(kernel_weights, architecture.get("kernel_affinity", {}))
    accelerated_fraction = min(
        0.90,
        _finite_float(boundary.get("accelerated_fraction"), default=0.0) * affinity,
    )
    speedup = max(
        1.0,
        _finite_float(architecture.get("speedup"), default=1.0)
        * _finite_float(mapping.get("efficiency"), default=1.0)
        * _finite_float(residency.get("reuse_factor"), default=1.0),
    )
    vector_speed_factor = {2: 0.94, 4: 1.00, 8: 1.08}.get(vector_lanes, 1.0)
    tile_speed_factor = {1024: 0.97, 2048: 1.00, 4096: 1.03}.get(tile_doubles, 1.0)
    speedup *= vector_speed_factor * tile_speed_factor
    accelerated_ms = total_ms * accelerated_fraction
    retained_host_ms = total_ms - accelerated_ms
    compute_ms = retained_host_ms + accelerated_ms / speedup

    data_mb = _finite_float(features.get("estimated_workflow_data_volume_mb"), default=8.0)
    lifetime = features.get("data_object_lifetime", {}) if isinstance(features.get("data_object_lifetime"), Mapping) else {}
    hot_object_mb = _finite_float(lifetime.get("estimated_hot_object_bytes"), default=0.0) / 1.0e6
    object_movement_multiplier = _data_object_movement_multiplier(parameters, lifetime)
    data_object_movement_mb = max(0.0, hot_object_mb * object_movement_multiplier)
    data_movement_mb = max(
        0.25,
        (data_mb + data_object_movement_mb)
        * _finite_float(boundary.get("transfer_multiplier"), default=1.0)
        * _finite_float(residency.get("movement_multiplier"), default=1.0),
    )
    bandwidth_gbps = max(0.1, _finite_float(memory.get("bandwidth_gbps"), default=10.0))
    if parameters.get("memory_topology") == "hbm_multi_channel":
        bandwidth_gbps *= max(0.25, hbm_channel_count / 8.0)
    transfer_latency_ms = data_movement_mb / bandwidth_gbps
    visible_transfer_ms = transfer_latency_ms * _finite_float(schedule.get("transfer_visible_fraction"), default=1.0)
    host_sync_ms = _finite_float(boundary.get("host_sync_ms"), default=20.0) + _finite_float(schedule.get("control_overhead_ms"), default=20.0)
    host_control_intensity = _finite_float(features.get("host_control_intensity"), default=0.0)
    post_processing_intensity = _finite_float(features.get("post_processing_intensity"), default=0.0)
    data_scale = _finite_float(features.get("variant_data_scale"), default=1.0)
    host_event_penalty_ms = _host_control_event_penalty_ms(parameters, features)
    host_sync_ms += host_control_intensity * _host_control_penalty_ms(parameters)
    host_sync_ms += host_event_penalty_ms
    host_sync_ms += post_processing_intensity * _post_processing_penalty_ms(parameters)
    wall_time_ms = compute_ms + visible_transfer_ms + host_sync_ms

    base_resource_pressure = (
        _finite_float(boundary.get("resource_pressure"), default=0.0)
        + _finite_float(architecture.get("resource_pressure"), default=0.0)
        + _finite_float(residency.get("resource_pressure"), default=0.0)
        + _finite_float(memory.get("resource_pressure"), default=0.0)
        + _finite_float(mapping.get("resource_pressure"), default=0.0)
    )
    micro_resource_pressure = (
        {2: 0.00, 4: 0.04, 8: 0.10}.get(vector_lanes, 0.0)
        + {0: 0.00, 4: 0.05, 8: 0.10}.get(hbm_channel_count, 0.0)
        + {1024: 0.00, 2048: 0.04, 4096: 0.09}.get(tile_doubles, 0.0)
    )
    workflow_resource_pressure = _workflow_resource_penalty(
        parameters,
        data_scale,
        host_control_intensity,
        post_processing_intensity,
    )
    raw_resource_pressure = base_resource_pressure + micro_resource_pressure + workflow_resource_pressure
    resource_pressure = _bounded_resource_pressure(raw_resource_pressure)
    legal, blockers = _release_legality(constraints, parameters, candidate)
    feasibility = max(0.0, min(1.0, 0.96 - resource_pressure * 0.42 - (0.35 if not legal else 0.0)))
    if legal and resource_pressure >= 0.98:
        legal = False
        blockers.append("l1_resource_pressure_above_release_threshold")
        feasibility = max(0.0, min(1.0, 0.96 - resource_pressure * 0.42 - 0.35))

    power_w = _finite_float(architecture.get("power_w"), default=25.0)
    schedule_energy_factor = _finite_float(schedule.get("energy_factor"), default=1.0)
    compute_energy_mj = (compute_ms / 1000.0) * power_w * 1000.0 * schedule_energy_factor
    movement_energy_mj = data_movement_mb * _finite_float(memory.get("energy_per_mb_mj"), default=0.02)
    host_energy_mj = (retained_host_ms / 1000.0) * 18.0 * 1000.0
    energy_mj = compute_energy_mj + movement_energy_mj + host_energy_mj
    edp = wall_time_ms * energy_mj

    metrics = {
        "estimated_workflow_wall_time_ms": wall_time_ms,
        "estimated_compute_time_ms": compute_ms,
        "estimated_visible_transfer_time_ms": visible_transfer_ms,
        "estimated_host_sync_time_ms": host_sync_ms,
        "host_control_event_penalty_ms": host_event_penalty_ms,
        "estimated_energy_mj": energy_mj,
        "estimated_edp": edp,
        "estimated_data_movement_mb": data_movement_mb,
        "estimated_data_object_movement_mb": data_object_movement_mb,
        "fpga_resource_pressure": resource_pressure,
        "implementation_feasibility": feasibility,
        "accelerated_workflow_fraction": accelerated_fraction,
        "effective_accelerated_speedup": speedup,
        "correctness_gate_count": _correctness_gate_count(features),
        "infeasibility_penalty": 1.0 - feasibility,
    }
    candidate_id = str(candidate.get("candidate_id") or parameters.get("candidate_id") or parameters.get("seed_id") or "")
    design_key = _design_key(parameters)
    return {
        "schema_version": "dse.qe_fpga_deployment_l1_candidate_evaluation.v1",
        "candidate_id": candidate_id,
        "design_key": design_key,
        "parameters": parameters,
        "fidelity": "L1_analytical_workflow_model",
        "metrics": {key: _round_metric(value) for key, value in metrics.items()},
        "dominance": {
            "status": "pending",
            "pareto_rank": None,
            "dominated_by": [],
            "objective_vector": {},
        },
        "promotion": {
            "release_pareto_eligible": legal,
            "recommended": False,
            "recommended_next_fidelity": None,
            "blockers": blockers,
            "rationale": [],
        },
        "explanation": {
            "offload_boundary": str(boundary.get("explanation", "")),
            "architecture_template": str(architecture.get("explanation", "")),
            "data_residency": _residency_explanation(parameters),
            "runtime_schedule": _schedule_explanation(parameters),
            "memory_topology": _memory_explanation(parameters),
            "workload_basis": "kernel phase weights, workflow dependencies, data_object_lifetime, host_control_events, and correctness_observables extracted from QE workflow cases",
        },
        "claim_boundary": "l1_screening_only_not_fpga_implementation_evidence",
    }


def _annotate_pareto(rows: List[Dict[str, Any]]) -> None:
    eligible = [row for row in rows if row["promotion"]["release_pareto_eligible"] is True]
    vectors = {row["candidate_id"]: _objective_vector(row) for row in eligible}
    for row in rows:
        if row["promotion"]["release_pareto_eligible"] is not True:
            row["dominance"].update({
                "status": "excluded_from_release_pareto",
                "pareto_rank": None,
                "dominated_by": [],
                "objective_vector": _objective_vector(row),
            })
            continue
        dominated_by = [
            other["candidate_id"]
            for other in eligible
            if other["candidate_id"] != row["candidate_id"]
            and _dominates(vectors[other["candidate_id"]], vectors[row["candidate_id"]])
        ]
        row["dominance"].update({
            "status": "non_dominated" if not dominated_by else "dominated",
            "pareto_rank": 0 if not dominated_by else 1,
            "dominated_by": dominated_by[:8],
            "objective_vector": vectors[row["candidate_id"]],
        })
        if dominated_by:
            row["promotion"]["blockers"].append("dominated_in_l1_release_pareto_screen")


def _objective_vector(row: Mapping[str, Any]) -> Dict[str, float]:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    return {
        "estimated_workflow_wall_time_ms": _finite_float(metrics.get("estimated_workflow_wall_time_ms"), default=float("inf")),
        "estimated_energy_mj": _finite_float(metrics.get("estimated_energy_mj"), default=float("inf")),
        "fpga_resource_pressure": _finite_float(metrics.get("fpga_resource_pressure"), default=float("inf")),
        "estimated_data_movement_mb": _finite_float(metrics.get("estimated_data_movement_mb"), default=float("inf")),
        "infeasibility_penalty": _finite_float(metrics.get("infeasibility_penalty"), default=float("inf")),
    }


def _dominates(left: Mapping[str, float], right: Mapping[str, float]) -> bool:
    keys = tuple(right.keys())
    return all(left[key] <= right[key] for key in keys) and any(left[key] < right[key] for key in keys)


def _bounded_resource_pressure(raw_pressure: float) -> float:
    pressure = _finite_float(raw_pressure, default=1.0)
    if pressure <= 0.92:
        return max(0.0, pressure)
    return min(1.0, 0.92 + (pressure - 0.92) * 0.35)


def _ape_percent(reference: float, observed: float) -> float:
    denom = max(abs(observed), 1.0e-9)
    return abs(reference - observed) / denom * 100.0


def _mean(values: Sequence[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return 0.0
    return sum(finite) / len(finite)


def _stddev(values: Sequence[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if len(finite) < 2:
        return 0.0
    mean = _mean(finite)
    variance = sum((value - mean) ** 2 for value in finite) / float(len(finite) - 1)
    return math.sqrt(max(0.0, variance))


def _spearman(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_ranks = _ranks(left)
    right_ranks = _ranks(right)
    left_mean = _mean(left_ranks)
    right_mean = _mean(right_ranks)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left_ranks, right_ranks))
    left_var = sum((a - left_mean) ** 2 for a in left_ranks)
    right_var = sum((b - right_mean) ** 2 for b in right_ranks)
    denom = math.sqrt(left_var * right_var)
    if denom <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denom))


def _ranks(values: Sequence[float]) -> List[float]:
    ordered = sorted((float(value), index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and ordered[end][0] == ordered[position][0]:
            end += 1
        avg_rank = (position + 1 + end) / 2.0
        for _value, index in ordered[position:end]:
            ranks[index] = avg_rank
        position = end
    return ranks


def _promotion_sort_key(row: Mapping[str, Any]) -> Tuple[float, float, float, float]:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    return (
        _finite_float(metrics.get("estimated_edp"), default=float("inf")),
        _finite_float(metrics.get("estimated_workflow_wall_time_ms"), default=float("inf")),
        _finite_float(metrics.get("infeasibility_penalty"), default=float("inf")),
        _finite_float(metrics.get("fpga_resource_pressure"), default=float("inf")),
    )


def _risk_aware_promotion_sort_key(row: Mapping[str, Any], workload_features: Mapping[str, Any]) -> Tuple[float, float, float, float, str]:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    risk = _promotion_risk_penalty(row, workload_features)
    return (
        _finite_float(metrics.get("estimated_edp"), default=float("inf")) * (1.0 + risk),
        _finite_float(metrics.get("estimated_workflow_wall_time_ms"), default=float("inf")) * (1.0 + risk * 0.6),
        _finite_float(metrics.get("infeasibility_penalty"), default=float("inf")) + risk,
        _finite_float(metrics.get("fpga_resource_pressure"), default=float("inf")) + risk,
        str(row.get("candidate_id", "")),
    )


def _promotion_risk_penalty(row: Mapping[str, Any], workload_features: Mapping[str, Any]) -> float:
    parameters = row.get("parameters", {}) if isinstance(row.get("parameters"), Mapping) else {}
    host_control = _finite_float(workload_features.get("host_control_intensity"), default=0.0)
    post_processing = _finite_float(workload_features.get("post_processing_intensity"), default=0.0)
    data_scale = _finite_float(workload_features.get("variant_data_scale"), default=1.0)
    penalty = _workflow_resource_penalty(parameters, data_scale, host_control, post_processing)
    if parameters.get("offload_boundary") == "workflow_hotspot_bundle":
        penalty += host_control * 0.16 + post_processing * 0.10
    if parameters.get("architecture_template") == "fpga_hbm_streaming_dataflow":
        penalty += host_control * 0.14 + post_processing * 0.08
    if parameters.get("memory_topology") == "hbm_multi_channel" and data_scale > 2.5:
        penalty += min(0.22, (data_scale - 2.5) * 0.08)
    if parameters.get("architecture_template") == "fpga_hybrid_cpu_control_accel_kernels":
        penalty -= min(0.12, host_control * 0.10 + post_processing * 0.06)
    return max(0.0, penalty)


def _risk_countermeasure_rows(
    rows: Sequence[Mapping[str, Any]],
    workload_features: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    countermeasures: List[Dict[str, Any]] = []
    host_control = _finite_float(workload_features.get("host_control_intensity"), default=0.0)
    post_processing = _finite_float(workload_features.get("post_processing_intensity"), default=0.0)
    data_scale = _finite_float(workload_features.get("variant_data_scale"), default=1.0)
    if host_control >= 0.40:
        row = _best_matching_row(
            rows,
            lambda params: (
                params.get("architecture_template") == "fpga_hybrid_cpu_control_accel_kernels"
                and params.get("offload_boundary") in {"stage_cluster_bundle", "kernel_callsite_bundle"}
            ),
            workload_features,
        )
        if row:
            countermeasures.append(row)
    if post_processing >= 0.24:
        row = _best_matching_row(
            rows,
            lambda params: (
                params.get("architecture_template") == "fpga_hybrid_cpu_control_accel_kernels"
                and params.get("runtime_schedule") != "overlap_dma_compute"
            ),
            workload_features,
        )
        if row:
            countermeasures.append(row)
    if data_scale >= 2.5:
        row = _best_matching_row(
            rows,
            lambda params: (
                params.get("memory_topology") == "hbm_multi_channel"
                and params.get("data_residency") == "fpga_hbm_resident_hot_arrays"
            ),
            workload_features,
        )
        if row:
            countermeasures.append(row)
    return countermeasures


def _best_matching_row(
    rows: Sequence[Mapping[str, Any]],
    predicate: Any,
    workload_features: Mapping[str, Any],
) -> Dict[str, Any] | None:
    matches = [
        row for row in rows
        if predicate(row.get("parameters", {}) if isinstance(row.get("parameters"), Mapping) else {})
    ]
    if not matches:
        return None
    return copy.deepcopy(dict(min(matches, key=lambda row: _risk_aware_promotion_sort_key(row, workload_features))))


def _dedupe_by_design_key(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    best_by_key: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("design_key") or _design_key(row.get("parameters", {}) if isinstance(row.get("parameters"), Mapping) else {}))
        current = best_by_key.get(key)
        if current is None or _promotion_sort_key(row) < _promotion_sort_key(current):
            best_by_key[key] = copy.deepcopy(dict(row))
    return sorted(best_by_key.values(), key=_promotion_sort_key)


def _select_diverse_promotions(
    rows: Sequence[Mapping[str, Any]],
    *,
    promotion_budget: int,
    workload_features: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    if promotion_budget <= 0:
        return []
    ordered = [copy.deepcopy(dict(row)) for row in sorted(rows, key=lambda row: _risk_aware_promotion_sort_key(row, workload_features))]
    selected: List[Dict[str, Any]] = []
    selected_keys: set[str] = set()

    for row in _method_seed_rows(ordered):
        if len(selected) >= promotion_budget:
            break
        key = str(row.get("design_key") or "")
        if key in selected_keys:
            continue
        selected.append(row)
        selected_keys.add(key)

    for axis_value in _ordered_axis_values(ordered, "architecture_template"):
        if len(selected) >= promotion_budget:
            break
        for row in ordered:
            if _parameter_value(row, "architecture_template") != axis_value:
                continue
            key = str(row.get("design_key") or "")
            if key in selected_keys:
                continue
            selected.append(row)
            selected_keys.add(key)
            break

    for row in _policy_nsga2_lite(ordered, promotion_budget):
        if len(selected) >= promotion_budget:
            break
        key = str(row.get("design_key") or "")
        if key in selected_keys:
            continue
        selected.append(copy.deepcopy(dict(row)))
        selected_keys.add(key)

    for row in _risk_countermeasure_rows(ordered, workload_features):
        if len(selected) >= promotion_budget:
            break
        key = str(row.get("design_key") or "")
        if key in selected_keys:
            continue
        selected.append(row)
        selected_keys.add(key)

    for row in ordered:
        if len(selected) >= promotion_budget:
            break
        key = str(row.get("design_key") or "")
        if key in selected_keys:
            continue
        selected.append(row)
        selected_keys.add(key)
    return selected


def _method_seed_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seed_ids = {
        "qe_fpga_cpu_control_hybrid_seed",
        "qe_fpga_mid_tier_tiled_seed",
        "qe_fpga_hbm_streaming_workflow_seed",
    }
    return [
        copy.deepcopy(dict(row))
        for row in rows
        if _candidate_parameters(row).get("seed_id") in seed_ids
    ]


def _ordered_axis_values(rows: Sequence[Mapping[str, Any]], axis: str) -> List[str]:
    best_score_by_value: Dict[str, Tuple[float, float, float, float]] = {}
    for row in rows:
        value = _parameter_value(row, axis)
        if not value:
            continue
        score = _promotion_sort_key(row)
        current = best_score_by_value.get(value)
        if current is None or score < current:
            best_score_by_value[value] = score
    return [
        value
        for value, _score in sorted(best_score_by_value.items(), key=lambda item: item[1])
    ]


def _parameter_value(row: Mapping[str, Any], key: str) -> str:
    parameters = row.get("parameters", {}) if isinstance(row.get("parameters"), Mapping) else {}
    return str(parameters.get(key, ""))


def _design_key(parameters: Mapping[str, Any]) -> str:
    fields = (
        "architecture_template",
        "offload_boundary",
        "mapping_granularity",
        "runtime_schedule",
        "data_residency",
        "memory_topology",
        "vector_lanes",
        "hbm_channel_count",
        "tile_doubles",
        "precision_policy",
    )
    return "|".join(f"{field}={parameters.get(field, '')}" for field in fields)


def _candidate_parameters(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    parameters = candidate.get("parameters")
    if isinstance(parameters, Mapping):
        return dict(parameters)
    return dict(candidate)


def _stage_weight_ms(
    stage_type: str,
    features: Mapping[str, Any],
    kernels: Sequence[Any],
    *,
    stage_id: str | None = None,
) -> float:
    kernel_weights = features.get("kernel_weights", {}) if isinstance(features.get("kernel_weights"), Mapping) else {}
    stage_compute_weights = {}
    contract = features.get("workflow_feature_contract_detail", {})
    if not isinstance(contract, Mapping) or not contract.get("schema_version"):
        contract = features.get("workflow_feature_contract", {})
    if stage_id and isinstance(contract, Mapping):
        stage_compute_table = contract.get("stage_compute_feature_table", {})
        if isinstance(stage_compute_table, Mapping):
            stage_compute_weights = {
                str(row.get("compute_id", "")): _finite_float(row.get("weight_seconds"), default=0.0)
                for row in stage_compute_table.get(stage_id, [])
                if isinstance(row, Mapping) and row.get("compute_id")
            }
    matched = 0.0
    for kernel in kernels:
        compute_id = str(kernel)
        matched += stage_compute_weights.get(compute_id, _finite_float(kernel_weights.get(compute_id), default=0.0))
    if matched <= 0.0:
        matched = _finite_float(features.get("total_profile_seconds"), default=1.0) / max(
            1.0,
            _finite_float(features.get("stage_count"), default=1.0),
        )
    if _stage_class(stage_type) == "post_processing":
        matched *= 0.85
    elif _stage_class(stage_type) == "relax":
        matched *= 1.10
    return max(1.0, matched * 1000.0)


def _edge_data_mb(features: Mapping[str, Any]) -> float:
    total = _finite_float(features.get("estimated_workflow_data_volume_mb"), default=8.0)
    edge_count = max(1.0, _finite_float(features.get("workflow_dependency_edge_count"), default=1.0))
    return round(total / edge_count, 6)


def _host_control_intensity(
    kernel_weights: Mapping[str, float],
    workflow_classes: Sequence[str],
    dominant_phase: str,
) -> float:
    total = max(1.0e-9, sum(_finite_float(value, default=0.0) for value in kernel_weights.values()))
    control_keys = ("forces", "stress", "mix_rho", "veff", "diagonalization")
    control = sum(
        _finite_float(value, default=0.0)
        for key, value in kernel_weights.items()
        if any(control_key in str(key) for control_key in control_keys)
    )
    class_boost = 0.18 if "relax" in set(workflow_classes) else 0.0
    dominant_boost = 0.30 if dominant_phase == "relax_control" else 0.0
    return max(0.0, min(1.0, control / total + class_boost + dominant_boost))


def _post_processing_intensity(
    kernel_weights: Mapping[str, float],
    workflow_classes: Sequence[str],
    dominant_phase: str,
) -> float:
    total = max(1.0e-9, sum(_finite_float(value, default=0.0) for value in kernel_weights.values()))
    post_keys = ("band_path", "projection", "projector", "reduction")
    post = sum(
        _finite_float(value, default=0.0)
        for key, value in kernel_weights.items()
        if any(post_key in str(key) for post_key in post_keys)
    )
    class_boost = 0.16 if "post_processing" in set(workflow_classes) else 0.0
    dominant_boost = 0.34 if dominant_phase == "post_processing" else 0.0
    return max(0.0, min(1.0, post / total + class_boost + dominant_boost))


def _host_control_penalty_ms(parameters: Mapping[str, Any]) -> float:
    penalty = 0.0
    if parameters.get("offload_boundary") == "workflow_hotspot_bundle":
        penalty += 180.0
    if parameters.get("architecture_template") == "fpga_hbm_streaming_dataflow":
        penalty += 140.0
    if parameters.get("runtime_schedule") == "overlap_dma_compute":
        penalty -= 55.0
    if parameters.get("runtime_schedule") == "batched_stage_pipeline":
        penalty += 30.0
    if parameters.get("offload_boundary") == "kernel_callsite_bundle":
        penalty -= 45.0
    return max(0.0, penalty)


def _post_processing_penalty_ms(parameters: Mapping[str, Any]) -> float:
    penalty = 0.0
    if parameters.get("offload_boundary") == "workflow_hotspot_bundle":
        penalty += 115.0
    if parameters.get("architecture_template") == "fpga_hbm_streaming_dataflow":
        penalty += 75.0
    if parameters.get("architecture_template") == "fpga_fft_transpose_pipeline":
        penalty += 60.0
    if parameters.get("architecture_template") == "fpga_hybrid_cpu_control_accel_kernels":
        penalty -= 35.0
    if parameters.get("runtime_schedule") == "overlap_dma_compute":
        penalty -= 25.0
    if parameters.get("runtime_schedule") == "batched_stage_pipeline":
        penalty += 20.0
    return max(0.0, penalty)


def _host_control_event_penalty_ms(
    parameters: Mapping[str, Any],
    features: Mapping[str, Any],
) -> float:
    events = features.get("host_control_event_counts", {}) if isinstance(features.get("host_control_event_counts"), Mapping) else {}
    checks = _finite_float(events.get("scf_convergence_check_count"), default=0.0)
    checkpoints = _finite_float(events.get("io_checkpoint_event_count"), default=0.0)
    post = _finite_float(events.get("post_processing_stage_count"), default=0.0)
    penalty = checks * 2.5 + checkpoints * 5.0 + post * 8.0
    if parameters.get("offload_boundary") == "workflow_hotspot_bundle":
        penalty *= 1.75
    elif parameters.get("offload_boundary") == "kernel_callsite_bundle":
        penalty *= 0.75
    if parameters.get("runtime_schedule") == "overlap_dma_compute":
        penalty *= 0.85
    return max(0.0, penalty)


def _data_object_movement_multiplier(
    parameters: Mapping[str, Any],
    lifetime: Mapping[str, Any],
) -> float:
    hot_count = _finite_float(lifetime.get("hot_reuse_object_count"), default=0.0)
    checkpoint_count = _finite_float(lifetime.get("checkpoint_object_count"), default=0.0)
    multiplier = 1.0 + hot_count * 0.08 + checkpoint_count * 0.04
    if parameters.get("data_residency") == "fpga_hbm_resident_hot_arrays":
        multiplier *= 0.32
    elif parameters.get("data_residency") == "hybrid_checkpointed_residency":
        multiplier *= 0.56
    if parameters.get("memory_topology") == "hbm_multi_channel":
        multiplier *= 0.82
    return max(0.05, multiplier)


def _correctness_gate_count(features: Mapping[str, Any]) -> int:
    observables = features.get("correctness_observables", {}) if isinstance(features.get("correctness_observables"), Mapping) else {}
    workflow = observables.get("workflow", []) if isinstance(observables.get("workflow"), list) else []
    return len({str(item) for item in workflow if str(item)})


def _workflow_resource_penalty(
    parameters: Mapping[str, Any],
    data_scale: float,
    host_control_intensity: float,
    post_processing_intensity: float,
) -> float:
    penalty = 0.0
    if parameters.get("memory_topology") == "hbm_multi_channel" and data_scale > 2.5:
        penalty += min(0.35, (data_scale - 2.5) * 0.12)
    if parameters.get("offload_boundary") == "workflow_hotspot_bundle":
        penalty += host_control_intensity * 0.22
        penalty += post_processing_intensity * 0.16
    if parameters.get("architecture_template") == "fpga_hbm_streaming_dataflow":
        penalty += host_control_intensity * 0.20
        penalty += post_processing_intensity * 0.10
    if parameters.get("architecture_template") == "fpga_hybrid_cpu_control_accel_kernels":
        penalty -= min(0.10, host_control_intensity * 0.08)
    return max(0.0, penalty)


def _release_legality(
    constraints: Mapping[str, Any],
    parameters: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> Tuple[bool, List[str]]:
    blockers: List[str] = []
    lane_field = str(constraints.get("formal_pareto_lane_field") or "release_lane")
    release_lane = str(constraints.get("release_lane") or "release")
    if str(parameters.get(lane_field, release_lane)) != release_lane:
        blockers.append(f"non_release_lane:{parameters.get(lane_field)}")

    legal_values = constraints.get("legal_values", {}) if isinstance(constraints.get("legal_values"), Mapping) else {}
    for key, values in legal_values.items():
        if key in parameters and parameters[key] not in set(values or ()):
            blockers.append(f"illegal_value:{key}:{parameters[key]}")

    memory_topology = str(parameters.get("memory_topology", ""))
    hbm_channel_count = _bounded_choice_int(parameters.get("hbm_channel_count"), allowed=(0, 4, 8), default=0)
    if memory_topology == "hbm_multi_channel" and hbm_channel_count <= 0:
        blockers.append("illegal_hbm_channel_count_for_hbm_topology")
    if memory_topology != "hbm_multi_channel" and hbm_channel_count != 0:
        blockers.append("illegal_hbm_channel_count_for_non_hbm_topology")
    if _bounded_choice_int(parameters.get("vector_lanes"), allowed=(2, 4, 8), default=0) <= 0:
        blockers.append(f"illegal_vector_lanes:{parameters.get('vector_lanes')}")
    if _bounded_choice_int(parameters.get("tile_doubles"), allowed=(1024, 2048, 4096), default=0) <= 0:
        blockers.append(f"illegal_tile_doubles:{parameters.get('tile_doubles')}")

    for blocker in candidate.get("simulation_blockers", []) or []:
        blocker_text = str(blocker)
        if blocker_text not in blockers and blocker_text != "not_promoted_for_simulation":
            blockers.append(blocker_text)
    return not blockers, blockers


def _bounded_choice_int(value: Any, *, allowed: Sequence[int], default: int) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return int(default)
    return resolved if resolved in set(int(item) for item in allowed) else int(default)


def _kernel_affinity(kernel_weights: Mapping[str, Any], affinity_model: Mapping[str, Any]) -> float:
    total = sum(max(0.0, _finite_float(value, default=0.0)) for value in kernel_weights.values())
    if total <= 0.0:
        return 1.0
    weighted = 0.0
    for kernel, weight in kernel_weights.items():
        normalized_kernel = str(kernel).lower()
        affinity = 1.0
        for key, raw_multiplier in affinity_model.items():
            if str(key).lower() in normalized_kernel:
                affinity = max(affinity, _finite_float(raw_multiplier, default=1.0))
        weighted += max(0.0, _finite_float(weight, default=0.0)) * affinity
    return max(0.75, min(1.30, weighted / total))


def _stage_class(stage_type: str) -> str:
    normalized = str(stage_type).strip().lower().replace("-", "_")
    if normalized in _POST_PROCESSING_STAGE_TYPES:
        return "post_processing"
    if normalized in _RELAX_STAGE_TYPES:
        return "relax"
    return normalized


def _model(models: Mapping[str, Mapping[str, Any]], key: Any) -> Dict[str, Any]:
    model = models.get(str(key))
    return dict(model) if isinstance(model, Mapping) else {}


def _finite_float(value: Any, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else default
    try:
        result = float(str(value))
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _fit_affine_calibration(x_values: Sequence[float], y_values: Sequence[float]) -> Dict[str, Any]:
    pairs = [
        (float(x), float(y))
        for x, y in zip(x_values, y_values)
        if math.isfinite(float(x)) and math.isfinite(float(y))
    ]
    if len(pairs) < 2:
        if pairs:
            x, y = pairs[0]
            scale = 1.0
            bias = y - x
            residuals = [0.0]
            mean_observed = max(abs(y), 1.0)
        else:
            scale = 1.0
            bias = 0.0
            residuals = []
            mean_observed = 1.0
        return {
            "model": "affine_l2_equals_scale_times_l1_plus_bias",
            "sample_count": len(pairs),
            "scale": _round_metric(scale),
            "bias": _round_metric(bias),
            "residual_rmse": _round_metric(_rmse(residuals)),
            "residual_mean": _round_metric(_mean(residuals)),
            "noise_cv": _round_metric(_rmse(residuals) / mean_observed),
        }
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x = _mean(xs)
    mean_y = _mean(ys)
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    if variance_x <= 0.0:
        scale = 1.0
        bias = mean_y - mean_x
    else:
        covariance = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
        scale = covariance / variance_x
        bias = mean_y - scale * mean_x
    residuals = [y - (scale * x + bias) for x, y in pairs]
    mean_observed = max(abs(_mean(ys)), 1.0)
    return {
        "model": "affine_l2_equals_scale_times_l1_plus_bias",
        "sample_count": len(pairs),
        "scale": _round_metric(scale),
        "bias": _round_metric(bias),
        "residual_rmse": _round_metric(_rmse(residuals)),
        "residual_mean": _round_metric(_mean(residuals)),
        "noise_cv": _round_metric(_rmse(residuals) / mean_observed),
    }


def _rmse(values: Sequence[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return 0.0
    return math.sqrt(sum(value * value for value in finite) / float(len(finite)))


def _percentile(values: Sequence[float], quantile: float) -> float:
    finite = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not finite:
        return 0.0
    if len(finite) == 1:
        return finite[0]
    q = max(0.0, min(1.0, float(quantile)))
    position = q * (len(finite) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return finite[lower]
    fraction = position - lower
    return finite[lower] * (1.0 - fraction) + finite[upper] * fraction


def _round_metric(value: float) -> float:
    if not math.isfinite(value):
        return value
    return round(float(value), 6)


def _residency_explanation(parameters: Mapping[str, Any]) -> str:
    value = str(parameters.get("data_residency", ""))
    if value == "fpga_hbm_resident_hot_arrays":
        return "keeps reused hot arrays resident on FPGA HBM to reduce repeated host traffic"
    if value == "hybrid_checkpointed_residency":
        return "retains checkpointed data between workflow phases while allowing CPU-owned control"
    return "streams windows from host memory and exposes most transfer cost"


def _schedule_explanation(parameters: Mapping[str, Any]) -> str:
    value = str(parameters.get("runtime_schedule", ""))
    if value == "overlap_dma_compute":
        return "overlaps DMA with accelerated compute and hides part of movement latency"
    if value == "batched_stage_pipeline":
        return "batches workflow stages to amortize launch and synchronization overhead"
    return "CPU orchestrates stages sequentially with visible transfer and synchronization cost"


def _memory_explanation(parameters: Mapping[str, Any]) -> str:
    value = str(parameters.get("memory_topology", ""))
    if value == "hbm_multi_channel":
        return "models high-bandwidth multi-channel HBM with higher implementation pressure"
    if value == "bram_uram_tiled_locality":
        return "models tiled on-chip locality with capacity and routing pressure"
    return "models external DDR streaming as a conservative baseline memory topology"


__all__ = [
    "QE_FPGA_ADAPTIVE_MULTIFIDELITY_SEARCH_REPORT_SCHEMA",
    "QE_FPGA_ADAPTIVE_METHOD_NAME",
    "QE_FPGA_DSE_METHOD_NAME",
    "QE_FPGA_HLS_ATTEMPT_SCHEMA",
    "QE_FPGA_HLS_ATTEMPT_SUMMARY_SCHEMA",
    "QE_FPGA_IMPLEMENTATION_PACKAGE_PLAN_SCHEMA",
    "QE_FPGA_IMPLEMENTATION_PACKAGE_MATERIALIZATION_SCHEMA",
    "QE_FPGA_VIVADO_ATTEMPT_SCHEMA",
    "QE_FPGA_VIVADO_ATTEMPT_SUMMARY_SCHEMA",
    "QE_FPGA_L1_SCREENING_SCHEMA",
    "QE_FPGA_L2_REQUEST_BUNDLE_SCHEMA",
    "QE_FPGA_MULTI_WORKLOAD_EXPERIMENT_REPORT_SCHEMA",
    "QE_FPGA_NEURAL_MULTIFIDELITY_SEARCH_REPORT_SCHEMA",
    "QE_FPGA_NEURAL_MULTIFIDELITY_METHOD_NAME",
    "QE_FPGA_NEURAL_SURROGATE_TRAINING_REPORT_SCHEMA",
    "QE_FPGA_NEUROMF_POLICY_EVALUATION_REPORT_SCHEMA",
    "QE_FPGA_SEARCH_BASELINE_REPORT_SCHEMA",
    "QE_FPGA_WAMF_DSE_METHOD_NAME",
    "QE_FPGA_WAMF_DSE_REPORT_SCHEMA",
    "build_qe_fpga_adaptive_multifidelity_search_report",
    "build_qe_fpga_implementation_package_plan",
    "build_qe_fpga_l2_calibration_report",
    "build_qe_fpga_l1_screening_report",
    "build_qe_fpga_l2_request_bundle",
    "build_qe_fpga_multi_workload_experiment_report",
    "build_qe_fpga_neural_multifidelity_search_report",
    "build_qe_fpga_neural_surrogate_training_report",
    "build_qe_fpga_neuromf_policy_evaluation_report",
    "build_qe_fpga_search_baseline_report",
    "build_qe_fpga_wamf_dse_report",
    "materialize_qe_fpga_implementation_packages",
    "run_qe_fpga_hls_attempt",
    "run_qe_fpga_hls_attempts_for_materialized_packages",
    "run_qe_fpga_l2_tlm_requests",
    "run_qe_fpga_vivado_attempt",
    "run_qe_fpga_vivado_attempts_for_materialized_packages",
]
