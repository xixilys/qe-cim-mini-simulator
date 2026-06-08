#!/usr/bin/env python3
"""Run the QE workflow to FPGA deployment L1 DSE prototype."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.mapping.search_policy import HierarchicalFunnelSearchPolicy
from dse_v2.mapping.search_policy import build_search_iteration_plan
from dse_v2.mapping.multifidelity_validation import build_multifidelity_algorithm_validation_report
from dse_v2.mapping.multifidelity_validation import build_validation_gated_next_evaluation_queue
from dse_v2.mapping.multifidelity_validation import build_validation_gated_search_control_report
from dse_v2.reference_workloads.qe_fpga_deployment_dse import (
    QE_FPGA_DSE_METHOD_NAME,
    QE_FPGA_WAMF_DSE_METHOD_NAME,
    build_qe_fpga_adaptive_multifidelity_search_report,
    build_qe_fpga_implementation_package_plan,
    build_qe_fpga_l2_calibration_report,
    build_qe_fpga_l1_screening_report,
    build_qe_fpga_l2_request_bundle,
    build_qe_fpga_multi_workload_experiment_report,
    build_qe_fpga_neural_multifidelity_search_report,
    build_qe_fpga_neural_surrogate_training_report,
    build_qe_fpga_neuromf_policy_evaluation_report,
    build_qe_fpga_search_baseline_report,
    build_qe_fpga_wamf_dse_report,
    materialize_qe_fpga_implementation_packages,
    run_qe_fpga_hls_attempts_for_materialized_packages,
    run_qe_fpga_l2_tlm_requests,
    run_qe_fpga_vivado_attempts_for_materialized_packages,
    _classify_hls_tool_evidence,
)
from dse_v2.reference_workloads.qe_workflow_fpga_abstraction import (
    build_qe_workflow_fpga_abstraction,
    load_qe_workflow_bundle,
)
from dse_v2.reference_workloads.dft_qe import parse_qe_pw_input
from dse_v2.reference_workloads.qe_mainflow import (
    build_qe_fpga_deployment_search_problem,
    default_qe_mainflow_workload_suite,
    workflow_bundle_from_qe_mainflow_manifest,
)

REPLAY_MANIFEST_NAME = "qe_fpga_replay_manifest.json"


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output run directory")
    parser.add_argument(
        "--workflow-bundle",
        type=Path,
        default=None,
        help="Optional QE workflow bundle JSON input. Defaults to the built-in QE mainflow suite.",
    )
    parser.add_argument(
        "--workflow-corpus",
        type=Path,
        default=None,
        help="Optional QE workflow corpus JSON input containing multiple workflow bundles.",
    )
    parser.add_argument(
        "--feedback-samples",
        type=Path,
        default=None,
        help="Optional external high-fidelity feedback samples JSON for adaptive search calibration.",
    )
    parser.add_argument("--workload-run-id", default="qe_mainflow_fpga_l1_run")
    parser.add_argument("--candidate-budget", type=int, default=2500)
    parser.add_argument("--promotion-budget", type=int, default=5)
    parser.add_argument("--implementation-package-budget", type=int, default=2)
    parser.add_argument(
        "--include-relax",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include relax/force workload case in the default QE suite",
    )
    args = parser.parse_args(argv)
    if args.workflow_bundle is not None and args.workflow_corpus is not None:
        parser.error("--workflow-bundle and --workflow-corpus are mutually exclusive")
    return args


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _stable_payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


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


def _round_metric(value: float) -> float:
    return round(float(value), 6) if math.isfinite(float(value)) else value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load_json_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_feedback_samples(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_samples: Any
    if isinstance(payload, list):
        raw_samples = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("samples"), list):
            raw_samples = payload.get("samples", [])
        elif isinstance(payload.get("feedback_sample"), Mapping):
            raw_samples = [payload["feedback_sample"]]
        else:
            raw_samples = []
    else:
        raise ValueError(f"{path} must contain a JSON object with samples or a JSON list")
    if not isinstance(raw_samples, Sequence) or isinstance(raw_samples, (str, bytes)):
        raise ValueError(f"{path} samples must be a list")
    return [dict(sample) for sample in raw_samples if isinstance(sample, Mapping)]


def _external_feedback_validation_report(
    *,
    feedback_samples: Sequence[Mapping[str, Any]],
    screening: Mapping[str, Any],
    l2_results: Mapping[str, Any],
    adaptive_search: Mapping[str, Any],
    search_baseline: Mapping[str, Any],
) -> Dict[str, Any]:
    l1_by_candidate = {
        str(row.get("candidate_id", "")): row
        for row in screening.get("candidate_evaluations", []) or []
        if isinstance(row, Mapping)
    }
    l2_by_candidate = {
        str(row.get("candidate_id", "")): row
        for row in l2_results.get("results", []) or []
        if isinstance(row, Mapping)
    }
    rows: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for index, sample in enumerate(feedback_samples):
        if not isinstance(sample, Mapping):
            rejected.append({"index": index, "reason": "sample_not_object"})
            continue
        candidate_id = str(sample.get("candidate_id", ""))
        feedback_rejection = _feedback_sample_rejection_reason(sample)
        if feedback_rejection:
            rejected.append({"index": index, "candidate_id": candidate_id, "reason": feedback_rejection})
            continue
        metrics = sample.get("metrics", {}) if isinstance(sample.get("metrics"), Mapping) else {}
        feedback_edp = _feedback_metric(metrics, "edp", "tlm_edp")
        latency = _feedback_metric(metrics, "workflow_wall_time_ms", "latency_ms", "tlm_workflow_wall_time_ms")
        energy = _feedback_metric(metrics, "energy_mj", "tlm_energy_mj")
        if feedback_edp <= 0.0 and latency > 0.0 and energy > 0.0:
            feedback_edp = latency * energy
        if not candidate_id or feedback_edp <= 0.0:
            rejected.append({"index": index, "candidate_id": candidate_id, "reason": "missing_candidate_or_positive_edp"})
            continue
        l1 = l1_by_candidate.get(candidate_id, {})
        l2 = l2_by_candidate.get(candidate_id, {})
        l1_metrics = l1.get("metrics", {}) if isinstance(l1.get("metrics"), Mapping) else {}
        l2_metrics = l2.get("metrics", {}) if isinstance(l2.get("metrics"), Mapping) else {}
        rows.append({
            "sample_id": str(sample.get("sample_id") or f"feedback_{index:03d}"),
            "candidate_id": candidate_id,
            "fidelity": str(sample.get("fidelity") or sample.get("source_fidelity") or "external_feedback"),
            "status": str(sample.get("status", "passed")),
            "feedback_edp": _round_metric(feedback_edp),
            "l1_estimated_edp": _round_metric(_finite_float(l1_metrics.get("estimated_edp"), default=0.0)),
            "l2_tlm_edp": _round_metric(_finite_float(l2_metrics.get("tlm_edp"), default=0.0)),
            "has_l1_row": bool(l1),
            "has_l2_row": bool(l2),
            "provenance": dict(sample.get("provenance", {}) if isinstance(sample.get("provenance"), Mapping) else {}),
        })
    correlation_rows = [row for row in rows if row["has_l1_row"] and row["l1_estimated_edp"] > 0.0]
    l2_correlation_rows = [row for row in rows if row["has_l2_row"] and row["l2_tlm_edp"] > 0.0]
    fidelities = sorted({row["fidelity"] for row in rows if row.get("fidelity")})
    adaptive_used = []
    summary = adaptive_search.get("external_feedback_summary", {}) if isinstance(adaptive_search.get("external_feedback_summary"), Mapping) else {}
    if isinstance(summary.get("used_candidate_ids"), list):
        adaptive_used = [str(item) for item in summary.get("used_candidate_ids", [])]
    report_status = "usable_for_rank_validation" if len(correlation_rows) >= 2 else "insufficient_for_correlation"
    policy_validation = _external_feedback_policy_validation(rows, search_baseline)
    return {
        "schema_version": "dse.qe_fpga_external_feedback_validation_report.v1",
        "status": report_status,
        "feedback_sample_count": len(rows),
        "provided_sample_count": len(feedback_samples),
        "rejected_sample_count": len(rejected),
        "fidelities": fidelities,
        "correlation_summary": {
            "overlap_count": len(correlation_rows),
            "l1_vs_feedback_spearman": _spearman(
                [row["l1_estimated_edp"] for row in correlation_rows],
                [row["feedback_edp"] for row in correlation_rows],
            ),
            "l2_vs_feedback_spearman": _spearman(
                [row["l2_tlm_edp"] for row in l2_correlation_rows],
                [row["feedback_edp"] for row in l2_correlation_rows],
            ),
            "top_k_overlap_at_5": _top_k_overlap_at_k(correlation_rows, k=5),
        },
        "adaptive_feedback_use": {
            "used_sample_count": int(summary.get("used_sample_count", 0)) if summary else 0,
            "used_candidate_ids": adaptive_used,
        },
        "policy_validation": policy_validation,
        "samples": rows,
        "rejected_samples": rejected,
        "limitations": [
            "external_feedback_validation_requires_real_independent_tool_provenance_to_support_paper_results",
            "single_sample_reports_are_ingestion_checks_not_rank_correlation_evidence",
            "L2_python_tlm_overlap_is_for_calibration_context_only_not_hardware_truth",
        ],
        "claim_boundary": "external_feedback_validation_only_not_hardware_result",
    }


def _feedback_sample_rejection_reason(sample: Mapping[str, Any]) -> str | None:
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


def _external_feedback_policy_validation(
    feedback_rows: Sequence[Mapping[str, Any]],
    search_baseline: Mapping[str, Any],
) -> Dict[str, Any]:
    feedback_by_candidate = {
        str(row.get("candidate_id", "")): row
        for row in feedback_rows
        if isinstance(row, Mapping) and row.get("candidate_id")
    }
    ordered_feedback = sorted(
        feedback_by_candidate.values(),
        key=lambda row: (_finite_float(row.get("feedback_edp"), default=float("inf")), str(row.get("candidate_id", ""))),
    )
    feedback_rank = {
        str(row.get("candidate_id", "")): index + 1
        for index, row in enumerate(ordered_feedback)
    }
    policies = []
    for policy in search_baseline.get("policies", []) or []:
        if not isinstance(policy, Mapping):
            continue
        candidate_ids = [str(candidate_id) for candidate_id in policy.get("candidate_ids", []) or []]
        overlap = [
            feedback_by_candidate[candidate_id]
            for candidate_id in candidate_ids
            if candidate_id in feedback_by_candidate
        ]
        best = min(
            overlap,
            key=lambda row: (_finite_float(row.get("feedback_edp"), default=float("inf")), str(row.get("candidate_id", ""))),
            default={},
        )
        best_candidate_id = str(best.get("candidate_id", "")) if isinstance(best, Mapping) else ""
        best_edp = _finite_float(best.get("feedback_edp") if isinstance(best, Mapping) else None, default=0.0)
        ranks = [feedback_rank[str(row.get("candidate_id", ""))] for row in overlap if str(row.get("candidate_id", "")) in feedback_rank]
        policies.append({
            "policy_id": str(policy.get("policy_id", "")),
            "selected_count": len(candidate_ids),
            "feedback_overlap_count": len(overlap),
            "feedback_coverage": _round_metric(len(overlap) / max(1, len(candidate_ids))),
            "best_feedback_candidate_id": best_candidate_id,
            "best_feedback_edp": _round_metric(best_edp),
            "feedback_rank_of_best": min(ranks) if ranks else None,
            "mean_feedback_rank": _round_metric(_mean([float(rank) for rank in ranks])) if ranks else None,
            "feedback_top_k_hit_at_5": bool(ranks and min(ranks) <= min(5, max(1, len(feedback_rank)))),
            "candidate_ids_with_feedback": [str(row.get("candidate_id", "")) for row in overlap],
            "selection_basis": dict(policy.get("selection_basis", {}) if isinstance(policy.get("selection_basis"), Mapping) else {}),
        })
    ranked = sorted(
        policies,
        key=lambda row: (
            0 if int(row.get("feedback_overlap_count", 0)) > 0 else 1,
            _finite_float(row.get("best_feedback_edp"), default=float("inf")),
            str(row.get("policy_id", "")),
        ),
    )
    best_policy = ranked[0] if ranked and int(ranked[0].get("feedback_overlap_count", 0)) > 0 else {}
    fidelities = sorted({str(row.get("fidelity", "")) for row in feedback_rows if row.get("fidelity")})
    return {
        "schema_version": "dse.qe_fpga_external_feedback_policy_validation.v1",
        "status": "usable_for_policy_comparison" if any(row["feedback_overlap_count"] > 0 for row in policies) else "insufficient_policy_overlap",
        "feedback_fidelity": fidelities[0] if len(fidelities) == 1 else ("mixed_external_feedback" if fidelities else "none"),
        "feedback_fidelities": fidelities,
        "feedback_candidate_count": len(feedback_by_candidate),
        "policy_count": len(policies),
        "policies": policies,
        "best_policy_by_feedback": {
            "policy_id": str(best_policy.get("policy_id", "")),
            "best_feedback_edp": best_policy.get("best_feedback_edp"),
            "feedback_rank_of_best": best_policy.get("feedback_rank_of_best"),
        },
        "limitations": [
            "policy_validation_only_covers_candidates_with_external_feedback_samples",
            "missing_feedback_for_selected_candidates_must_not_be_treated_as_failed_hardware",
            "DAC_grade_policy_comparison_requires_replayable_independent_feedback_for_all_compared_policy_budget_points",
        ],
        "claim_boundary": "policy_validation_external_feedback_only_not_final_hardware_evidence",
    }


def _feedback_metric(metrics: Mapping[str, Any], *names: str) -> float:
    for name in names:
        if name in metrics:
            return _finite_float(metrics.get(name), default=0.0)
    return 0.0


def _mean(values: Sequence[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return 0.0
    return sum(finite) / len(finite)


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
    return round(max(-1.0, min(1.0, numerator / denom)), 6)


def _ranks(values: Sequence[float]) -> List[float]:
    ordered = sorted((float(value), index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and ordered[end][0] == ordered[position][0]:
            end += 1
        rank = (position + 1 + end) / 2.0
        for _, original_index in ordered[position:end]:
            ranks[original_index] = rank
        position = end
    return ranks


def _top_k_overlap_at_k(rows: Sequence[Mapping[str, Any]], *, k: int) -> float:
    if not rows:
        return 0.0
    resolved_k = min(max(1, int(k)), len(rows))
    by_l1 = sorted(
        rows,
        key=lambda row: (_finite_float(row.get("l1_estimated_edp"), default=float("inf")), str(row.get("candidate_id", ""))),
    )
    by_feedback = sorted(
        rows,
        key=lambda row: (_finite_float(row.get("feedback_edp"), default=float("inf")), str(row.get("candidate_id", ""))),
    )
    l1_ids = {str(row.get("candidate_id", "")) for row in by_l1[:resolved_k]}
    feedback_ids = {str(row.get("candidate_id", "")) for row in by_feedback[:resolved_k]}
    return round(len(l1_ids.intersection(feedback_ids)) / float(resolved_k), 6)


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and revision else None


def _git_dirty() -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _candidate_queue(candidates: List[Mapping[str, Any]], *, budget: int) -> Dict[str, Any]:
    return {
        "schema_version": "dse.qe_fpga_step2_candidate_queue.v1",
        "candidate_count": len(candidates),
        "candidate_budget": int(budget),
        "candidates": [dict(candidate) for candidate in candidates],
        "candidate_ids": [str(candidate.get("candidate_id", "")) for candidate in candidates],
        "claim_boundary": "step2_candidate_queue_only_not_l1_or_fpga_implementation_evidence",
    }


def _search_checkpoint_summary(
    *,
    search_problem: Mapping[str, Any],
    search_checkpoint: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    proposal_budget: int,
) -> Dict[str, Any]:
    return {
        "schema_version": "dse.step2.search_checkpoint_summary.v1",
        "campaign_id": str(search_problem.get("problem_id", "qe_fpga_deployment_dse_campaign")),
        "workload_run_id": str(search_problem.get("workload_run_id", "")),
        "trial_id": str(search_problem.get("workload_run_id", "qe_fpga_trial")),
        "search_policy_name": "hierarchical_funnel",
        "search_policy_problem": dict(search_problem),
        "search_policy_checkpoint": dict(search_checkpoint),
        "search_policy_proposal_budget": int(proposal_budget),
        "search_policy_candidates": [dict(candidate) for candidate in candidates],
        "claim_boundary": "qe_fpga_step2_search_checkpoint_for_feedback_replay_only",
    }


def _build_step2_feedback_update_from_adaptive_search(
    adaptive_search: Mapping[str, Any],
    *,
    search_problem: Mapping[str, Any],
) -> Dict[str, Any]:
    updates: List[Dict[str, Any]] = []
    feedback_source_counts: Dict[str, int] = {}
    source_artifact_hashes: Dict[str, str] = {
        "qe_fpga_adaptive_multifidelity_search_report.json": _stable_payload_hash(dict(adaptive_search)),
    }
    trace_rows = [
        row for row in adaptive_search.get("evaluation_trace", []) or []
        if isinstance(row, Mapping)
    ]
    for row in trace_rows:
        external_common_objective = row.get("external_feedback_common_objective_used") is True
        if external_common_objective:
            observation = row.get("external_feedback_observation", {})
            feedback_kind = "external_calibrated_common_objective"
        else:
            observation = row.get("common_objective_observation", row.get("l2_observation", {}))
            feedback_kind = "model_common_objective"
        if not isinstance(observation, Mapping):
            continue
        metrics = observation.get("metrics", {}) if isinstance(observation.get("metrics"), Mapping) else {}
        provenance = observation.get("provenance", {}) if isinstance(observation.get("provenance"), Mapping) else {}
        candidate_id = str(row.get("candidate_id") or observation.get("candidate_id") or "")
        if not candidate_id:
            continue
        fidelity = str(observation.get("fidelity", ""))
        if external_common_objective:
            observed_edp = _finite_float(metrics.get("observed_edp"), default=0.0)
            objective_edp = _finite_float(metrics.get("calibrated_common_objective_edp"), default=observed_edp)
            observed_latency = _finite_float(metrics.get("observed_workflow_wall_time_ms"), default=0.0)
            observed_energy = _finite_float(metrics.get("observed_energy_mj"), default=0.0)
            observed_resource = _finite_float(metrics.get("observed_resource_pressure"), default=0.0)
        else:
            objective_edp = _finite_float(metrics.get("tlm_edp"), default=0.0)
            observed_edp = objective_edp
            observed_latency = _finite_float(metrics.get("tlm_workflow_wall_time_ms"), default=0.0)
            observed_energy = _finite_float(metrics.get("tlm_energy_mj"), default=0.0)
            observed_resource = _finite_float(metrics.get("tlm_resource_pressure"), default=0.0)
        if observed_edp <= 0.0 or objective_edp <= 0.0:
            continue
        source_artifacts = []
        if not external_common_objective:
            source_artifacts.append("qe_fpga_adaptive_multifidelity_search_report.json")
        if provenance.get("run_dir"):
            source_artifacts.append(str(provenance.get("run_dir")))
        if provenance.get("report_path"):
            source_artifacts.append(str(provenance.get("report_path")))
        if provenance.get("artifact_sha256"):
            source_artifacts.append(str(provenance.get("artifact_sha256")))
        calibration = observation.get("calibration", {}) if isinstance(observation.get("calibration"), Mapping) else {}
        calibration_artifact = str(calibration.get("calibration_artifact", ""))
        calibration_artifact_hash = str(calibration.get("calibration_artifact_sha256") or "")
        if calibration_artifact and calibration_artifact_hash:
            source_artifacts.append(calibration_artifact)
            source_artifact_hashes[calibration_artifact] = calibration_artifact_hash
        if provenance.get("artifact_sha256"):
            source_artifact_hashes[f"external_feedback:{candidate_id}"] = str(provenance.get("artifact_sha256"))
        feedback_source_counts[fidelity or feedback_kind] = feedback_source_counts.get(fidelity or feedback_kind, 0) + 1
        update_metrics = {
            "trusted_sample": bool(external_common_objective),
            "promoted": True,
            "step4_verdict": "trusted_pass" if external_common_objective else "model_feedback_pass",
            "objective_metric_name": "edp",
            "objective_metric_value": _round_metric(objective_edp),
            "objective_direction": "minimize",
            "objective_metric_weight": 0.0,
            "lower_is_better": True,
            "observed_edp": _round_metric(observed_edp),
            "latency_ms": _round_metric(observed_latency),
            "energy_mj": _round_metric(observed_energy),
            "resource_pressure": _round_metric(observed_resource),
            "calibrated_score_delta": _round_metric(100_000_000.0 / max(objective_edp, 1.0)),
            "step4_quality_score": _round_metric(100.0 / (1.0 + _finite_float(
                observation.get("calibration", {}).get("noise_edp_cv")
                if isinstance(observation.get("calibration"), Mapping)
                else 0.0,
                default=0.0,
            ))),
            "calibration_noise_edp_cv": _round_metric(_finite_float(
                observation.get("calibration", {}).get("noise_edp_cv")
                if isinstance(observation.get("calibration"), Mapping)
                else 0.0,
                default=0.0,
            )),
            "feedback_fidelity": fidelity,
            "feedback_kind": feedback_kind,
            "model_feedback_only": not external_common_objective,
        }
        if external_common_objective:
            update_metrics["calibrated_common_objective_edp"] = _round_metric(objective_edp)
        updates.append({
            "target": "search_policy",
            "status": "available",
            "candidate_id": candidate_id,
            "candidate_refs": {
                "candidate_id": candidate_id,
                "search_policy_candidate_id": candidate_id,
            },
            "metrics": update_metrics,
            "source_artifacts": source_artifacts,
            "calibration": dict(calibration),
            "provenance": provenance,
        })
    return {
        "schema_version": "dse.contract.feedback_update.v1",
        "producer_schema_version": "dse.qe_fpga_step2_feedback_update.v1",
        "campaign_id": str(search_problem.get("problem_id", "qe_fpga_deployment_dse_campaign")),
        "workload_run_id": str(search_problem.get("workload_run_id", "")),
        "trial_id": str(search_problem.get("workload_run_id", "qe_fpga_trial")),
        "source_adaptive_search_artifact": "qe_fpga_adaptive_multifidelity_search_report.json",
        "common_objective_update_count": len(updates),
        "feedback_source_counts": dict(sorted(feedback_source_counts.items())),
        "updates": updates,
        "source_artifact_hashes": source_artifact_hashes if updates else {},
        "limitations": [
            "L2_python_tlm_feedback_updates_next_search_ordering_but_remains_model_feedback",
            "calibrated_external_common_objective_feedback_is_trusted_more_than_model_feedback",
            "uncalibrated_external_feedback_remains_diagnostic_and_does_not_influence_next_iteration",
        ],
        "claim_boundary": "step2_feedback_update_for_next_search_iteration_only_not_hardware_result",
    }


def _build_feedback_informed_iteration_artifacts(
    *,
    search_problem: Mapping[str, Any],
    search_checkpoint: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    adaptive_search: Mapping[str, Any],
    proposal_budget: int,
) -> Tuple[Dict[str, Any], Dict[str, Any] | None]:
    feedback_update = _build_step2_feedback_update_from_adaptive_search(
        adaptive_search,
        search_problem=search_problem,
    )
    if int(feedback_update.get("common_objective_update_count", 0)) <= 0:
        return feedback_update, None
    checkpoint_summary = _search_checkpoint_summary(
        search_problem=search_problem,
        search_checkpoint=search_checkpoint,
        candidates=candidates,
        proposal_budget=proposal_budget,
    )
    iteration_plan = build_search_iteration_plan(
        search_checkpoint=checkpoint_summary,
        feedback_update=feedback_update,
        calibration_record={
            "schema_version": "dse.qe_fpga_external_feedback_common_objective_calibration_summary.v1",
            "confidence": 0.8,
            "error_metrics": {
                "basis": "external_feedback_declared_calibration_noise",
                "common_objective_update_count": int(feedback_update.get("common_objective_update_count", 0)),
            },
        },
        proposal_budget=int(proposal_budget),
        refs={
            "search_checkpoint": "search_checkpoint.json",
            "feedback_update": "feedback_update.json",
            "calibration_record": "calibration_record.json",
            "step3_simulation_queue": "step3_simulation_queue.json",
        },
    )
    return feedback_update, iteration_plan


def _build_validation_gated_queue_from_search_baseline(
    *,
    search_baseline: Mapping[str, Any],
    external_feedback_validation: Mapping[str, Any] | None,
    promotion_budget: int,
) -> Dict[str, Any]:
    budget_sweep = (
        search_baseline.get("budget_sweep", {})
        if isinstance(search_baseline.get("budget_sweep"), Mapping)
        else {}
    )
    policy_results = _policy_results_from_budget_sweep(budget_sweep)
    feedback_coverage_plan = (
        search_baseline.get("independent_feedback_coverage_plan", {})
        if isinstance(search_baseline.get("independent_feedback_coverage_plan"), Mapping)
        else {}
    )
    independent_feedback = (
        _independent_feedback_from_external_validation(external_feedback_validation)
        if isinstance(external_feedback_validation, Mapping)
        else {}
    )
    validation = build_multifidelity_algorithm_validation_report(
        proposed_policy_id=str(search_baseline.get("proposed_method_policy_id", "wamf_generic_active_pareto")),
        policy_results=policy_results,
        independent_feedback=independent_feedback,
    )
    search_control = build_validation_gated_search_control_report(
        validation_report=validation,
        candidates=_search_control_candidates_from_feedback_plan(feedback_coverage_plan),
        budget=max(1, int(promotion_budget)),
    )
    queue = build_validation_gated_next_evaluation_queue(
        search_control=search_control,
        nominal_candidates=_search_control_candidates_from_feedback_plan(feedback_coverage_plan),
        budget=max(1, int(promotion_budget)),
        next_fidelity="L2_systemc_or_tlm",
    )
    queue["algorithm_validation"] = validation
    queue["search_control"] = search_control
    queue["source_search_baseline"] = "qe_fpga_search_baseline_report.json"
    if isinstance(external_feedback_validation, Mapping):
        queue["source_external_feedback_validation"] = "qe_fpga_external_feedback_validation_report.json"
    return queue


def _policy_results_from_budget_sweep(budget_sweep: Mapping[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for curve in budget_sweep.get("policy_curves", []) or []:
        if not isinstance(curve, Mapping):
            continue
        points = [point for point in curve.get("points", []) or [] if isinstance(point, Mapping)]
        if not points:
            continue
        final = points[-1]
        results.append({
            "policy_id": str(curve.get("policy_id", "")),
            "final_budget": int(final.get("budget", 0) or 0),
            "final_best_edp": final.get("best_tlm_edp", final.get("best_tlm_edp_mean")),
            "final_oracle_rank": final.get("oracle_rank_of_best", final.get("oracle_rank_of_best_mean")),
            "top_k_hit": final.get("top_k_hit"),
        })
    return results


def _independent_feedback_from_external_validation(
    external_feedback_validation: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    if not isinstance(external_feedback_validation, Mapping):
        return {}
    correlation = (
        external_feedback_validation.get("correlation_summary", {})
        if isinstance(external_feedback_validation.get("correlation_summary"), Mapping)
        else {}
    )
    rank = correlation.get("l1_vs_feedback_spearman")
    return {
        "source": "external_feedback_validation",
        "sample_count": int(external_feedback_validation.get("feedback_sample_count", 0) or 0),
        "rank_correlation": {
            "status": (
                "usable"
                if external_feedback_validation.get("status") == "usable_for_rank_validation"
                else "insufficient"
            ),
            "l1_estimated_edp_vs_l3_edp_spearman": rank,
        },
    }


def _search_control_candidates_from_feedback_plan(
    feedback_coverage_plan: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    queue = (
        feedback_coverage_plan.get("candidate_feedback_queue", [])
        if isinstance(feedback_coverage_plan.get("candidate_feedback_queue"), list)
        else []
    )
    rows: List[Dict[str, Any]] = []
    max_source_count = max(
        [
            int(row.get("source_count", 0) or 0)
            for row in queue
            if isinstance(row, Mapping)
        ]
        or [1]
    )
    for row in queue:
        if not isinstance(row, Mapping):
            continue
        candidate_id = str(row.get("candidate_id", ""))
        if not candidate_id:
            continue
        source_count = int(row.get("source_count", 0) or 0)
        is_holdout = str(row.get("selection_role", "")) != "promoted"
        resource_pressure = _finite_float(row.get("fpga_resource_pressure"), default=0.0)
        rows.append({
            "candidate_id": candidate_id,
            "design_key": str(row.get("selection_role", "")),
            "uncertainty": min(1.0, source_count / float(max(1, max_source_count))),
            "risk_axes": {
                "feedback_holdout": 1.0 if is_holdout else 0.35,
                "resource_pressure": min(1.0, max(0.0, resource_pressure)),
            },
            "evaluation_cost": 1.0 + 0.25 * max(0.0, resource_pressure),
            "metadata": {
                "feedback_priority": int(row.get("feedback_priority", 0) or 0),
                "selection_sources": list(row.get("selection_sources", []) or []),
            },
        })
    return rows


def _feedback_informed_next_promotion_queue(
    search_iteration_plan: Mapping[str, Any] | None,
    *,
    promotion_budget: int,
    validation_gated_queue: Mapping[str, Any] | None = None,
) -> Dict[str, Any] | None:
    if not isinstance(search_iteration_plan, Mapping):
        return None
    next_candidates = [
        candidate for candidate in search_iteration_plan.get("next_candidates", []) or []
        if isinstance(candidate, Mapping)
    ]
    next_candidates = _apply_validation_gated_candidate_order(
        next_candidates,
        validation_gated_queue=validation_gated_queue,
    )
    validation_control_rows = _validation_control_rows_by_candidate(validation_gated_queue)
    control_mode = (
        str(validation_gated_queue.get("mode", "nominal_policy"))
        if isinstance(validation_gated_queue, Mapping)
        else "nominal_policy"
    )
    control_reason = (
        str(validation_gated_queue.get("control_reason", ""))
        if isinstance(validation_gated_queue, Mapping)
        else ""
    )
    validation_applied = bool(
        isinstance(validation_gated_queue, Mapping)
        and control_mode == "exploration_fallback"
        and validation_control_rows
    )
    promoted: List[Dict[str, Any]] = []
    for candidate in next_candidates:
        if len(promoted) >= max(0, int(promotion_budget)):
            break
        if not _candidate_can_enter_feedback_promotion_queue(candidate):
            continue
        row = copy.deepcopy(dict(candidate))
        control_row = validation_control_rows.get(str(row.get("candidate_id", "")), {})
        row["feedback_informed_rank"] = len(promoted) + 1
        row["source_search_policy_rank"] = int(row.get("search_policy_rank", len(promoted) + 1) or len(promoted) + 1)
        if control_row:
            row["validation_control_rank"] = int(control_row.get("validation_control_rank", 0) or 0)
            row["validation_control_reason"] = str(control_row.get("queue_reason", ""))
            if control_row.get("control_score") is not None:
                row["validation_control_score"] = control_row.get("control_score")
            rationale_head = "validation_gated_exploration_fallback"
        else:
            rationale_head = "calibrated_feedback_informed_next_iteration"
        row["promotion"] = {
            "recommended": True,
            "recommended_next_fidelity": "L2_systemc_or_tlm",
            "rationale": [
                rationale_head,
                "search_policy_feedback_generalization_applied_or_exact_match",
                "requires_step3_queue_materialization_before_execution",
            ],
        }
        row["execution_allowed"] = False
        row["not_a_step3_queue_entry"] = True
        row["provenance_only"] = True
        row["claim_status"] = "feedback_informed_next_promotion_only"
        promoted.append(row)
    if not promoted:
        return None
    return {
        "schema_version": "dse.qe_fpga_feedback_informed_next_promotion_queue.v1",
        "method_name": "AdaptiveWorkflowMultiFidelityDSE",
        "problem_id": str(search_iteration_plan.get("problem_id", "")),
        "workload_run_id": str(search_iteration_plan.get("workload_run_id", "")),
        "source_search_iteration_plan": "qe_fpga_search_iteration_plan.json",
        "source_feedback_update": "qe_fpga_step2_feedback_update.json",
        "validation_gated_queue_applied": validation_applied,
        "control_mode": control_mode,
        "control_reason": control_reason,
        "promotion_count": len(promoted),
        "promotion_budget": int(promotion_budget),
        "recommended_next_fidelity": "L2_systemc_or_tlm",
        "execution_allowed": False,
        "not_a_step3_queue": True,
        "promotion_queue": promoted,
        "candidate_ids": [str(candidate.get("candidate_id", "")) for candidate in promoted],
        "claim_boundary": "feedback_informed_next_promotion_queue_only_not_step3_execution_or_hardware_evidence",
    }


def _apply_validation_gated_candidate_order(
    next_candidates: Sequence[Mapping[str, Any]],
    *,
    validation_gated_queue: Mapping[str, Any] | None,
) -> List[Mapping[str, Any]]:
    if not isinstance(validation_gated_queue, Mapping):
        return list(next_candidates)
    if str(validation_gated_queue.get("mode", "")) != "exploration_fallback":
        return list(next_candidates)
    control_ids = [
        str(candidate_id)
        for candidate_id in validation_gated_queue.get("selected_candidate_ids", []) or []
        if str(candidate_id)
    ]
    if not control_ids:
        return list(next_candidates)
    candidate_by_id = {
        str(candidate.get("candidate_id", "")): candidate
        for candidate in next_candidates
        if isinstance(candidate, Mapping) and str(candidate.get("candidate_id", ""))
    }
    ordered: List[Mapping[str, Any]] = [
        candidate_by_id[candidate_id]
        for candidate_id in control_ids
        if candidate_id in candidate_by_id
    ]
    selected_ids = {str(candidate.get("candidate_id", "")) for candidate in ordered}
    ordered.extend([
        candidate
        for candidate in next_candidates
        if str(candidate.get("candidate_id", "")) not in selected_ids
    ])
    return ordered


def _validation_control_rows_by_candidate(
    validation_gated_queue: Mapping[str, Any] | None,
) -> Dict[str, Dict[str, Any]]:
    if not isinstance(validation_gated_queue, Mapping):
        return {}
    rows: Dict[str, Dict[str, Any]] = {}
    for index, row in enumerate(validation_gated_queue.get("queue", []) or [], start=1):
        if not isinstance(row, Mapping):
            continue
        candidate_id = str(row.get("candidate_id", ""))
        if not candidate_id:
            continue
        payload = dict(row)
        payload["validation_control_rank"] = int(payload.get("queue_order", index) or index)
        rows[candidate_id] = payload
    return rows


def _candidate_can_enter_feedback_promotion_queue(candidate: Mapping[str, Any]) -> bool:
    if candidate.get("step2_screenable") is not True:
        return False
    blockers = [
        str(blocker)
        for blocker in candidate.get("simulation_blockers", []) or []
        if str(blocker)
    ]
    non_promotion_blockers = [
        blocker for blocker in blockers
        if blocker != "not_promoted_for_simulation"
    ]
    return not non_promotion_blockers


def _feedback_informed_next_l2_request_bundle(
    manifest: Mapping[str, Any],
    problem: SearchProblem | Mapping[str, Any],
    next_promotion_queue: Mapping[str, Any] | None,
    *,
    workflow_abstraction: Mapping[str, Any] | None = None,
) -> Dict[str, Any] | None:
    if not isinstance(next_promotion_queue, Mapping):
        return None
    promotion_queue = [
        row for row in next_promotion_queue.get("promotion_queue", []) or []
        if isinstance(row, Mapping)
    ]
    if not promotion_queue:
        return None
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        promotion_queue,
        promotion_budget=len(promotion_queue),
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=True,
    )
    row_by_candidate = {
        str(row.get("candidate_id", "")): row
        for row in screening.get("candidate_evaluations", []) or []
        if isinstance(row, Mapping)
    }
    evaluated_queue: List[Dict[str, Any]] = []
    for row in promotion_queue:
        candidate_id = str(row.get("candidate_id", ""))
        evaluated = copy.deepcopy(dict(row_by_candidate.get(candidate_id, row)))
        if isinstance(row.get("observed_metrics"), Mapping):
            evaluated["observed_metrics"] = dict(row.get("observed_metrics", {}))
        evaluated_queue.append(evaluated)
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        evaluated_queue,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=True,
    )
    bundle["source_promotion_queue"] = "qe_fpga_next_promotion_queue.json"
    bundle["source_search_iteration_plan"] = "qe_fpga_search_iteration_plan.json"
    bundle["feedback_informed_next_iteration"] = True
    bundle["execution_allowed"] = False
    return bundle


def _promotion_queue(screening: Mapping[str, Any]) -> Dict[str, Any]:
    queue = [dict(row) for row in screening.get("promotion_queue", []) or [] if isinstance(row, Mapping)]
    return {
        "schema_version": "dse.qe_fpga_l1_promotion_queue.v1",
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "promotion_count": len(queue),
        "recommended_next_fidelity": "L2_systemc_or_tlm" if queue else None,
        "promotion_queue": queue,
        "claim_boundary": "l1_promotion_queue_only_not_systemc_gem5_or_vivado_evidence",
    }


def _summary(
    *,
    workload_suite: Mapping[str, Any],
    search_problem: Mapping[str, Any],
    candidate_queue: Mapping[str, Any],
    screening: Mapping[str, Any],
    promotion: Mapping[str, Any],
    l2_bundle: Mapping[str, Any],
    l2_results: Mapping[str, Any],
    calibration: Mapping[str, Any],
    adaptive_search: Mapping[str, Any],
    neural_multifidelity_search: Mapping[str, Any],
    neural_surrogate_training: Mapping[str, Any],
    neuromf_policy_evaluation: Mapping[str, Any],
    wamf_dse: Mapping[str, Any],
    search_baseline: Mapping[str, Any],
    multi_workload_experiment: Mapping[str, Any],
    implementation_plan: Mapping[str, Any],
    implementation_materialization: Mapping[str, Any],
    hls_attempt_summary: Mapping[str, Any],
    vivado_attempt_summary: Mapping[str, Any],
    external_feedback_validation: Mapping[str, Any] | None = None,
    step2_feedback_update: Mapping[str, Any] | None = None,
    search_iteration_plan: Mapping[str, Any] | None = None,
    next_promotion_queue: Mapping[str, Any] | None = None,
    validation_gated_queue: Mapping[str, Any] | None = None,
    next_l2_request_bundle: Mapping[str, Any] | None = None,
    next_l2_results: Mapping[str, Any] | None = None,
    input_workflow_bundle: Mapping[str, Any] | None = None,
    input_workflow_corpus: Mapping[str, Any] | None = None,
    input_feedback_samples: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    summary = {
        "schema_version": "dse.qe_fpga_deployment_dse_summary.v1",
        "method_name": QE_FPGA_WAMF_DSE_METHOD_NAME,
        "algorithm_family": "workflow_conditioned_multifidelity_active_pareto_dse",
        "prototype_status": "l1_screening_complete_not_hardware_closed",
        "workload_suite_id": str(workload_suite.get("suite_id", "")),
        "workload_run_id": str(search_problem.get("workload_run_id", "")),
        "problem_id": str(search_problem.get("problem_id", "")),
        "candidate_count": int(candidate_queue.get("candidate_count", 0)),
        "pareto_candidate_count": len(screening.get("pareto_frontier", []) or []),
        "promotion_count": int(promotion.get("promotion_count", 0)),
        "l2_request_count": int(l2_bundle.get("request_count", 0)),
        "l2_executed_count": int(l2_results.get("executed_count", 0)),
        "search_baseline_policy_count": int(search_baseline.get("policy_count", 0)),
        "multi_workload_experiment_workload_count": int(multi_workload_experiment.get("workload_count", 0)),
        "multi_workload_experiment": dict(multi_workload_experiment),
        "implementation_package_count": int(implementation_plan.get("package_count", 0)),
        "implementation_package_materialized_count": int(implementation_materialization.get("package_count", 0)),
        "hls_attempt_summary": {
            "artifact": "qe_fpga_hls_attempt_summary.json",
            "status": str(hls_attempt_summary.get("status", "")),
            "attempt_count": int(hls_attempt_summary.get("attempt_count", 0)),
            "performance_feedback_allowed_count": int(
                hls_attempt_summary.get("performance_feedback_allowed_count", 0)
            ),
            "synthesis_evidence_allowed_count": int(
                hls_attempt_summary.get("synthesis_evidence_allowed_count", 0)
            ),
            "vivado_implementation_count": int(hls_attempt_summary.get("vivado_implementation_count", 0)),
            "bitstream_count": int(hls_attempt_summary.get("bitstream_count", 0)),
            "claim_boundary": str(hls_attempt_summary.get("claim_boundary", "")),
        },
        "vivado_attempt_summary": {
            "artifact": "qe_fpga_vivado_attempt_summary.json",
            "status": str(vivado_attempt_summary.get("status", "")),
            "attempt_count": int(vivado_attempt_summary.get("attempt_count", 0)),
            "implementation_evidence_allowed_count": int(
                vivado_attempt_summary.get("implementation_evidence_allowed_count", 0)
            ),
            "bitstream_evidence_allowed_count": int(
                vivado_attempt_summary.get("bitstream_evidence_allowed_count", 0)
            ),
            "vivado_implementation_count": int(vivado_attempt_summary.get("vivado_implementation_count", 0)),
            "bitstream_count": int(vivado_attempt_summary.get("bitstream_count", 0)),
            "claim_boundary": str(vivado_attempt_summary.get("claim_boundary", "")),
        },
        "calibration_status": str(calibration.get("calibration_status", "")),
        "latency_mape_percent": calibration.get("latency_mape_percent"),
        "spearman_rank_correlation": calibration.get("spearman_rank_correlation"),
        "adaptive_search_evaluated_count": int(adaptive_search.get("evaluated_count", 0)),
        "adaptive_search_best_rank": (
            adaptive_search.get("final_result", {}).get("oracle_rank_of_best")
            if isinstance(adaptive_search.get("final_result"), Mapping)
            else None
        ),
        "adaptive_search_best_observed_objective": (
            adaptive_search.get("final_result", {}).get("best_observed_objective")
            if isinstance(adaptive_search.get("final_result"), Mapping)
            else None
        ),
        "adaptive_search_oracle_status": (
            adaptive_search.get("oracle_summary", {}).get("rank_and_regret_status")
            if isinstance(adaptive_search.get("oracle_summary"), Mapping)
            else None
        ),
        "neural_multifidelity_search": {
            "artifact": "qe_fpga_neural_multifidelity_search_report.json",
            "method_name": str(neural_multifidelity_search.get("method_name", "")),
            "execution_mode": str(neural_multifidelity_search.get("execution_mode", "")),
            "evaluated_count": int(neural_multifidelity_search.get("evaluated_count", 0)),
            "surrogate_model_type": str(
                neural_multifidelity_search.get("surrogate_model", {}).get("model_type", "")
                if isinstance(neural_multifidelity_search.get("surrogate_model"), Mapping)
                else ""
            ),
            "oracle_status": (
                neural_multifidelity_search.get("oracle_summary", {}).get("rank_and_regret_status")
                if isinstance(neural_multifidelity_search.get("oracle_summary"), Mapping)
                else None
            ),
            "best_rank": (
                neural_multifidelity_search.get("final_result", {}).get("oracle_rank_of_best")
                if isinstance(neural_multifidelity_search.get("final_result"), Mapping)
                else None
            ),
            "best_observed_objective": (
                neural_multifidelity_search.get("final_result", {}).get("best_observed_objective")
                if isinstance(neural_multifidelity_search.get("final_result"), Mapping)
                else None
            ),
            "claim_boundary": str(neural_multifidelity_search.get("claim_boundary", "")),
        },
        "neural_surrogate_training": {
            "artifact": "qe_fpga_neural_surrogate_training_report.json",
            "training_status": str(neural_surrogate_training.get("training_status", "")),
            "model_type": str(
                neural_surrogate_training.get("backend", {}).get("model_type", "")
                if isinstance(neural_surrogate_training.get("backend"), Mapping)
                else ""
            ),
            "device_policy": str(
                neural_surrogate_training.get("backend", {}).get("device_policy", "")
                if isinstance(neural_surrogate_training.get("backend"), Mapping)
                else ""
            ),
            "resolved_device": str(
                neural_surrogate_training.get("backend", {}).get("resolved_device", "")
                if isinstance(neural_surrogate_training.get("backend"), Mapping)
                else ""
            ),
            "cuda_available": bool(
                neural_surrogate_training.get("backend", {}).get("cuda_available", False)
                if isinstance(neural_surrogate_training.get("backend"), Mapping)
                else False
            ),
            "torch_version": str(
                neural_surrogate_training.get("backend", {}).get("torch_version", "")
                if isinstance(neural_surrogate_training.get("backend"), Mapping)
                else ""
            ),
            "sample_count": (
                int(neural_surrogate_training.get("dataset", {}).get("sample_count", 0))
                if isinstance(neural_surrogate_training.get("dataset"), Mapping)
                else 0
            ),
            "holdout_rmse_log_edp": (
                neural_surrogate_training.get("metrics", {}).get("holdout", {}).get("rmse_log_edp")
                if isinstance(neural_surrogate_training.get("metrics"), Mapping)
                and isinstance(neural_surrogate_training.get("metrics", {}).get("holdout"), Mapping)
                else None
            ),
            "uncertainty_calibration_status": (
                neural_surrogate_training.get("uncertainty", {}).get("calibration_status")
                if isinstance(neural_surrogate_training.get("uncertainty"), Mapping)
                else None
            ),
            "claim_boundary": str(neural_surrogate_training.get("claim_boundary", "")),
        },
        "neuromf_policy_evaluation": {
            "artifact": "qe_fpga_neuromf_policy_evaluation_report.json",
            "policy_count": int(neuromf_policy_evaluation.get("policy_count", 0)),
            "best_policy_id": str(
                neuromf_policy_evaluation.get("best_policy_by_final_regret", {}).get("policy_id", "")
                if isinstance(neuromf_policy_evaluation.get("best_policy_by_final_regret"), Mapping)
                else ""
            ),
            "trained_neuromf_rank": (
                neuromf_policy_evaluation.get("aggregate", {}).get("trained_neuromf_rank")
                if isinstance(neuromf_policy_evaluation.get("aggregate"), Mapping)
                else None
            ),
            "trained_neuromf_final_regret": (
                neuromf_policy_evaluation.get("aggregate", {}).get("trained_neuromf_final_regret")
                if isinstance(neuromf_policy_evaluation.get("aggregate"), Mapping)
                else None
            ),
            "claim_boundary": str(neuromf_policy_evaluation.get("claim_boundary", "")),
        },
        "wamf_dse": {
            "artifact": "qe_fpga_wamf_dse_report.json",
            "method_name": str(wamf_dse.get("method_name", "")),
            "selected_candidate_count": (
                int(wamf_dse.get("selected_final_candidates", {}).get("candidate_count", 0))
                if isinstance(wamf_dse.get("selected_final_candidates"), Mapping)
                else 0
            ),
            "next_evaluation_action_count": (
                int(wamf_dse.get("next_evaluation_actions", {}).get("selected_action_count", 0))
                if isinstance(wamf_dse.get("next_evaluation_actions"), Mapping)
                else 0
            ),
            "baseline_policy_count": (
                len(wamf_dse.get("baselines", {}).get("policies", []) or [])
                if isinstance(wamf_dse.get("baselines"), Mapping)
                else 0
            ),
            "required_ablation_count": (
                len(wamf_dse.get("ablations", {}).get("required_ablations", []) or [])
                if isinstance(wamf_dse.get("ablations"), Mapping)
                else 0
            ),
            "claim_boundary": str(wamf_dse.get("claim_boundary", "")),
        },
        "paper_table_rows": {
            "next_evaluation_actions": _paper_next_evaluation_action_rows(wamf_dse),
        },
        "next_required_fidelity": "L3_systemc",
        "required_future_evidence": [
            "L3_systemc_replay_for_promoted_candidates",
            "L4_runtime_trace_calibration",
            "candidate_specific_hls_or_rtl_package",
            "vivado_synthesis_or_implementation_for_selected_candidate",
            "qe_baseline_and_correctness_for_end_to_end_workflow",
        ],
        "artifact_hashes": {
            "qe_mainflow_workload_suite.json": _stable_payload_hash(workload_suite),
            "qe_fpga_search_problem.json": _stable_payload_hash(search_problem),
            "qe_fpga_step2_candidates.json": _stable_payload_hash(candidate_queue),
            "qe_fpga_l1_screening_report.json": _stable_payload_hash(screening),
            "qe_fpga_promotion_queue.json": _stable_payload_hash(promotion),
            "qe_fpga_l2_request_bundle.json": _stable_payload_hash(l2_bundle),
            "qe_fpga_l2_tlm_results.json": _stable_payload_hash(l2_results),
            "qe_fpga_l1_l2_calibration_report.json": _stable_payload_hash(calibration),
            "qe_fpga_adaptive_multifidelity_search_report.json": _stable_payload_hash(adaptive_search),
            "qe_fpga_neural_multifidelity_search_report.json": _stable_payload_hash(neural_multifidelity_search),
            "qe_fpga_neural_surrogate_training_report.json": _stable_payload_hash(neural_surrogate_training),
            "qe_fpga_neuromf_policy_evaluation_report.json": _stable_payload_hash(neuromf_policy_evaluation),
            "qe_fpga_wamf_dse_report.json": _stable_payload_hash(wamf_dse),
            "qe_fpga_search_baseline_report.json": _stable_payload_hash(search_baseline),
            "qe_fpga_multi_workload_experiment_report.json": _stable_payload_hash(multi_workload_experiment),
            "qe_fpga_implementation_package_plan.json": _stable_payload_hash(implementation_plan),
            "qe_fpga_implementation_package_materialization.json": _stable_payload_hash(implementation_materialization),
            "qe_fpga_hls_attempt_summary.json": _stable_payload_hash(hls_attempt_summary),
            "qe_fpga_vivado_attempt_summary.json": _stable_payload_hash(vivado_attempt_summary),
        },
        "git_revision": _git_revision(),
        "claim_boundary": "prototype_search_artifacts_only_not_fpga_implementation_evidence",
    }
    if external_feedback_validation is not None:
        summary["external_feedback_validation"] = {
            "status": str(external_feedback_validation.get("status", "")),
            "feedback_sample_count": int(external_feedback_validation.get("feedback_sample_count", 0)),
            "fidelities": list(external_feedback_validation.get("fidelities", []) or []),
            "artifact": "qe_fpga_external_feedback_validation_report.json",
        }
        policy_validation = external_feedback_validation.get("policy_validation", {})
        if isinstance(policy_validation, Mapping):
            summary["external_feedback_validation"]["policy_validation_status"] = str(policy_validation.get("status", ""))
            summary["external_feedback_validation"]["policy_validation_best_policy_id"] = str(
                policy_validation.get("best_policy_by_feedback", {}).get("policy_id", "")
                if isinstance(policy_validation.get("best_policy_by_feedback"), Mapping)
                else ""
            )
        summary["artifact_hashes"]["qe_fpga_external_feedback_validation_report.json"] = _stable_payload_hash(external_feedback_validation)
    if step2_feedback_update is not None and int(step2_feedback_update.get("common_objective_update_count", 0)) > 0:
        summary["artifact_hashes"]["qe_fpga_step2_feedback_update.json"] = _stable_payload_hash(step2_feedback_update)
    if search_iteration_plan is not None:
        search_policy_problem = (
            search_iteration_plan.get("search_policy_problem", {})
            if isinstance(search_iteration_plan.get("search_policy_problem"), Mapping)
            else {}
        )
        search_policy_constraints = (
            search_policy_problem.get("constraints", {})
            if isinstance(search_policy_problem.get("constraints"), Mapping)
            else {}
        )
        summary["feedback_informed_next_iteration"] = {
            "artifact": "qe_fpga_search_iteration_plan.json",
            "feedback_update_artifact": "qe_fpga_step2_feedback_update.json",
            "validation_gated_queue_artifact": (
                "qe_fpga_validation_gated_next_evaluation_queue.json"
                if validation_gated_queue is not None
                else None
            ),
            "next_promotion_queue_artifact": (
                "qe_fpga_next_promotion_queue.json"
                if next_promotion_queue is not None
                else None
            ),
            "next_l2_request_bundle_artifact": (
                "qe_fpga_next_l2_request_bundle.json"
                if next_l2_request_bundle is not None
                else None
            ),
            "next_l2_results_artifact": (
                "qe_fpga_next_l2_tlm_results.json"
                if next_l2_results is not None
                else None
            ),
            "next_promotion_count": (
                int(next_promotion_queue.get("promotion_count", 0))
                if isinstance(next_promotion_queue, Mapping)
                else 0
            ),
            "next_l2_executed_count": (
                int(next_l2_results.get("executed_count", 0))
                if isinstance(next_l2_results, Mapping)
                else 0
            ),
            "applied_feedback_count": int(search_iteration_plan.get("applied_feedback_count", 0)),
            "feedback_routing_status": str(search_iteration_plan.get("feedback_routing_status", "")),
            "feedback_informed_proposal_ordering": bool(search_iteration_plan.get("feedback_informed_proposal_ordering", False)),
            "validation_control_mode": (
                str(validation_gated_queue.get("mode", ""))
                if isinstance(validation_gated_queue, Mapping)
                else ""
            ),
            "validation_control_applied_to_next_promotion": (
                bool(next_promotion_queue.get("validation_gated_queue_applied", False))
                if isinstance(next_promotion_queue, Mapping)
                else False
            ),
            "feedback_generalization_axes": list(
                search_policy_constraints.get("feedback_generalization_axes", []) or []
            ),
            "feedback_generalization_strength": search_policy_constraints.get("feedback_generalization_strength"),
        }
        summary["artifact_hashes"]["qe_fpga_search_iteration_plan.json"] = _stable_payload_hash(search_iteration_plan)
    if validation_gated_queue is not None:
        summary["artifact_hashes"]["qe_fpga_validation_gated_next_evaluation_queue.json"] = _stable_payload_hash(validation_gated_queue)
    if next_promotion_queue is not None:
        summary["artifact_hashes"]["qe_fpga_next_promotion_queue.json"] = _stable_payload_hash(next_promotion_queue)
    if next_l2_request_bundle is not None:
        summary["artifact_hashes"]["qe_fpga_next_l2_request_bundle.json"] = _stable_payload_hash(next_l2_request_bundle)
    if next_l2_results is not None:
        summary["artifact_hashes"]["qe_fpga_next_l2_tlm_results.json"] = _stable_payload_hash(next_l2_results)
    if input_workflow_bundle is not None:
        summary["input_workflow_bundle"] = dict(input_workflow_bundle)
    if input_workflow_corpus is not None:
        summary["input_workflow_corpus"] = dict(input_workflow_corpus)
    constraints = search_problem.get("constraints", {}) if isinstance(search_problem.get("constraints"), Mapping) else {}
    summary["workflow_scope"] = str(constraints.get("workflow_scope", "full_qe_mainflow"))
    summary["release_completion_eligible"] = bool(constraints.get("release_completion_eligible", False))
    if constraints.get("model_level_seed_only"):
        summary["prototype_status"] = "measured_scf_seed_model_level_dse_not_release_complete"
        summary["workflow_coverage_limitations"] = list(constraints.get("workflow_coverage_limitations", []) or [])
    if input_feedback_samples is not None:
        summary["input_feedback_samples"] = dict(input_feedback_samples)
    return summary


def _paper_next_evaluation_action_rows(wamf_dse: Mapping[str, Any]) -> List[Dict[str, Any]]:
    next_actions = (
        wamf_dse.get("next_evaluation_actions", {})
        if isinstance(wamf_dse.get("next_evaluation_actions"), Mapping)
        else {}
    )
    rows: List[Dict[str, Any]] = []
    for row in next_actions.get("actions", []) or []:
        if not isinstance(row, Mapping):
            continue
        factors = row.get("decision_factors", {}) if isinstance(row.get("decision_factors"), Mapping) else {}
        rows.append(
            {
                "action_id": str(row.get("action_id", "")),
                "candidate_id": str(row.get("candidate_id", "")),
                "fidelity": str(row.get("fidelity", "")),
                "action_cost": row.get("action_cost"),
                "action_score": row.get("action_score"),
                "constrained_pareto_gain": factors.get("constrained_pareto_gain"),
                "workflow_risk_coverage": factors.get("workflow_risk_coverage"),
                "fidelity_information_gain": factors.get("fidelity_information_gain"),
                "method_role": str(next_actions.get("method_role", "")),
                "search_objective": str(next_actions.get("search_objective", "")),
                "not_an_evidence_closure_matrix": bool(next_actions.get("not_an_evidence_closure_matrix", False)),
            }
        )
    return rows


def _external_manifest_from_workflow_bundle(
    bundle: Mapping[str, Any],
    *,
    bundle_path: Path,
) -> Dict[str, Any]:
    stages = [stage for stage in bundle.get("stages", []) or [] if isinstance(stage, Mapping)]
    cases = [
        _case_from_external_stage(stage, index=index)
        for index, stage in enumerate(stages)
    ]
    classes = sorted({_stage_class(str(case.get("stage_type", ""))) for case in cases})
    manifest = {
        "schema_version": "dse.qe_mainflow_workload_suite_manifest.v1",
        "suite_id": str(bundle.get("workflow_id") or bundle.get("workload_id") or "external_qe_workflow_bundle"),
        "source_kind": "external_qe_workflow_bundle",
        "status": "external_input",
        "release_id": "external_qe_workflow_bundle_import",
        "external_bundle_ref": {
            "path": str(bundle_path),
            "sha256": _file_sha256(bundle_path),
            "format": "qe_workflow_bundle_json",
        },
        "required_mainflow_classes": ["scf", "nscf", "post_processing"],
        "relax_policy": {
            "status": "deferred",
            "stage_types": [],
            "rationale": "External workflow bundle did not provide relax/vc-relax stages; force/stress closure remains out of this imported suite.",
        },
        "cases": cases,
        "workflow_classes": classes,
        "candidate_identity_policy": {
            "workload_case_ids_participate": False,
            "workload_features_participate": False,
            "reason": "External workload facts steer search but do not enter candidate identity aliases.",
            "forbidden_candidate_identity_fields": [
                "case_id",
                "stage_type",
                "qe_command",
                "input_hashes",
                "expected_outputs",
                "kernel_coverage",
                "physical_quantities",
                "baseline_run_provenance",
            ],
        },
        "claim_boundary": "external_workload_manifest_only_not_qe_runtime_or_fpga_evidence",
    }
    manifest["suite_hash"] = _stable_hex_hash(_without_keys(manifest, "suite_hash"))
    return manifest


def _load_workflow_corpus(path: Path) -> Dict[str, Any]:
    payload = _load_json_object(path)
    raw_workloads = payload.get("workloads", [])
    if not isinstance(raw_workloads, Sequence) or isinstance(raw_workloads, (str, bytes)) or not raw_workloads:
        raise ValueError(f"{path} must contain a non-empty workloads list")
    workloads: List[Dict[str, Any]] = []
    for index, workload in enumerate(raw_workloads):
        if not isinstance(workload, Mapping):
            raise ValueError(f"{path} workloads[{index}] must be a JSON object")
        bundle_value = workload.get("bundle_path") or workload.get("workflow_bundle")
        if not bundle_value:
            raise ValueError(f"{path} workloads[{index}] must define bundle_path")
        bundle_entry_path = _resolve_bundle_path(str(bundle_value), base_dir=path.parent)
        resolved_bundle = load_qe_workflow_bundle(bundle_entry_path)
        bundle_path = Path(str(resolved_bundle.get("_bundle_manifest_path", bundle_entry_path)))
        workload_id = str(
            workload.get("workload_id")
            or resolved_bundle.get("workflow_id")
            or resolved_bundle.get("workload_id")
            or f"workload_{index:03d}"
        )
        nested_refs = _workflow_bundle_nested_artifact_refs(resolved_bundle)
        abstraction = build_qe_workflow_fpga_abstraction(resolved_bundle, workload_id=workload_id)
        workloads.append({
            "workload_id": workload_id,
            "bundle_path": bundle_path,
            "bundle": resolved_bundle,
            "metadata": {
                key: copy.deepcopy(value)
                for key, value in workload.items()
                if key not in {"bundle_path", "workflow_bundle"}
            },
            "nested_artifact_refs": nested_refs,
            "abstraction": abstraction,
        })
    primary_id = str(payload.get("primary_workload_id") or workloads[0]["workload_id"])
    primary = next((row for row in workloads if row["workload_id"] == primary_id), workloads[0])
    return {
        "raw": payload,
        "path": path,
        "corpus_id": str(payload.get("corpus_id") or path.stem),
        "primary_workload_id": str(primary["workload_id"]),
        "primary": primary,
        "workloads": workloads,
    }


def build_qe_fpga_workflow_corpus_report(path: Path) -> Dict[str, Any]:
    """Load a QE workflow corpus and return the provenance/readiness report."""

    return _workflow_corpus_report(_load_workflow_corpus(path))


def _workflow_corpus_report(corpus: Mapping[str, Any]) -> Dict[str, Any]:
    workloads = [row for row in corpus.get("workloads", []) or [] if isinstance(row, Mapping)]
    workflow_classes: set[str] = set()
    qe_programs: set[str] = set()
    max_dimensions = {"nbnd": 0, "npw": 0, "nfft": 0, "kpoint_count": 0, "nat": 0, "ntyp": 0}
    observed_runtime_count = 0
    measured_ready_count = 0
    total_stage_count = 0
    total_nested_ref_count = 0
    total_artifact_bytes = 0
    rows: List[Dict[str, Any]] = []
    corpus_blockers: List[str] = []
    for row in workloads:
        abstraction = row.get("abstraction", {}) if isinstance(row.get("abstraction"), Mapping) else {}
        features = abstraction.get("features", {}) if isinstance(abstraction.get("features"), Mapping) else {}
        source = abstraction.get("source", {}) if isinstance(abstraction.get("source"), Mapping) else {}
        data_objects = abstraction.get("data_objects", {}) if isinstance(abstraction.get("data_objects"), Mapping) else {}
        nested_refs = [ref for ref in row.get("nested_artifact_refs", []) or [] if isinstance(ref, Mapping)]
        workflow_classes.update(str(item) for item in features.get("workflow_classes", []) or [])
        qe_programs.update(str(item) for item in source.get("qe_programs", []) or [])
        dims = features.get("max_dimensions", {}) if isinstance(features.get("max_dimensions"), Mapping) else {}
        for key in max_dimensions:
            max_dimensions[key] = max(max_dimensions[key], int(_finite_float(dims.get(key), default=0.0)))
        if bool(source.get("observed_runtime")):
            observed_runtime_count += 1
        total_stage_count += int(source.get("stage_count", 0))
        total_nested_ref_count += len(nested_refs)
        data_bytes = sum(
            int(_finite_float(obj.get("bytes"), default=0.0))
            for obj in data_objects.values()
            if isinstance(obj, Mapping)
        )
        total_artifact_bytes += data_bytes
        bundle_path = row.get("bundle_path")
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), Mapping) else {}
        readiness = _measured_qe_workload_readiness(row)
        if readiness["status"] == "ready_for_model_level_experiments":
            measured_ready_count += 1
        else:
            corpus_blockers.extend(str(blocker) for blocker in readiness.get("blockers", []) or [])
        rows.append({
            "workload_id": str(row.get("workload_id", "")),
            "metadata": dict(metadata),
            "material": str(metadata.get("material", "")),
            "size_class": str(metadata.get("size_class", "")),
            "workflow_roles": list(metadata.get("workflow_roles", []) or []),
            "bundle_ref": {
                "path": str(bundle_path),
                "sha256": _file_sha256(bundle_path) if isinstance(bundle_path, Path) else None,
            },
            "nested_artifact_ref_count": len(nested_refs),
            "stage_count": int(source.get("stage_count", 0)),
            "workflow_classes": list(features.get("workflow_classes", []) or []),
            "qe_programs": list(source.get("qe_programs", []) or []),
            "observed_runtime": bool(source.get("observed_runtime")),
            "max_dimensions": dict(dims),
            "observed_total_phase_wall_seconds": features.get("observed_total_phase_wall_seconds"),
            "estimated_total_data_movement_bytes": int(
                _finite_float(features.get("estimated_total_data_movement_bytes"), default=0.0)
            ),
            "source_fact_count": len(abstraction.get("source_facts", []) or []),
            "measured_qe_readiness": readiness,
            "claim_boundary": "corpus_workload_row_only_not_representativeness_or_hardware_evidence",
        })
    corpus_ready = measured_ready_count == len(rows) and bool(rows)
    return {
        "schema_version": "dse.qe_fpga_workload_corpus_report.v1",
        "corpus_id": str(corpus.get("corpus_id", "")),
        "primary_workload_id": str(corpus.get("primary_workload_id", "")),
        "workload_count": len(rows),
        "coverage": {
            "workflow_classes": sorted(workflow_classes),
            "qe_programs": sorted(qe_programs),
            "max_dimensions": max_dimensions,
            "observed_runtime_workload_count": observed_runtime_count,
            "measured_qe_ready_workload_count": measured_ready_count,
            "total_stage_count": total_stage_count,
            "nested_artifact_ref_count": total_nested_ref_count,
            "estimated_data_object_bytes": total_artifact_bytes,
        },
        "measured_qe_corpus_readiness": {
            "schema_version": "dse.qe_fpga.measured_qe_corpus_readiness.v1",
            "status": "ready_for_model_level_experiments" if corpus_ready else "blocked",
            "measured_ready_workload_count": measured_ready_count,
            "workload_count": len(rows),
            "blockers": sorted(set(corpus_blockers)),
            "allowed_use": (
                "model_level_search_and_ablation_experiment_input"
                if corpus_ready
                else "provenance_and_fixture_pipeline_testing_only"
            ),
            "forbidden_use": [
                "hardware_performance_result",
                "qe_numerical_correctness_result",
                "representative_qe_benchmark_claim_without_selection_policy_review",
            ],
        },
        "workloads": rows,
        "limitations": [
            "workflow_corpus_report_records_input_coverage_and_provenance_only",
            "representative_QE_experiment_requires_curated_real_runs_and_documented_selection_policy",
            "hardware_or_search_quality_results_require_independent_fidelity_feedback",
        ],
        "claim_boundary": "workflow_corpus_provenance_only_not_representative_qe_or_hardware_evidence",
    }


def _workflow_bundle_from_workflow_corpus(corpus: Mapping[str, Any]) -> Dict[str, Any]:
    stages: List[Dict[str, Any]] = []
    workload_refs: List[Dict[str, Any]] = []
    for row in corpus.get("workloads", []) or []:
        if not isinstance(row, Mapping):
            continue
        workload_id = str(row.get("workload_id", "") or "workload")
        bundle = row.get("bundle", {}) if isinstance(row.get("bundle"), Mapping) else {}
        workload_refs.append({
            "workload_id": workload_id,
            "bundle_path": str(row.get("bundle_path", "")),
        })
        for index, stage in enumerate(bundle.get("stages", []) or []):
            if not isinstance(stage, Mapping):
                continue
            stage_row = copy.deepcopy(dict(stage))
            original_stage_id = str(stage_row.get("stage_id") or f"stage_{index:02d}")
            namespaced_stage_id = f"{workload_id}__{original_stage_id}"
            stage_row["stage_id"] = namespaced_stage_id
            stage_row["corpus_workload_id"] = workload_id
            stage_row["source_stage_id"] = original_stage_id
            stage_row["depends_on"] = [
                f"{workload_id}__{dependency}"
                for dependency in stage_row.get("depends_on", []) or []
            ]
            stages.append(stage_row)
    return {
        "schema_version": "dse.qe.native_workflow_bundle.v1",
        "workflow_id": str(corpus.get("corpus_id", "")) or "qe_workflow_corpus",
        "workload_id": str(corpus.get("corpus_id", "")) or "qe_workflow_corpus",
        "source_kind": "qe_workflow_corpus_aggregate_bundle",
        "workflow_scope": "corpus_level_multi_workload_coverage",
        "corpus_id": str(corpus.get("corpus_id", "")),
        "primary_workload_id": str(corpus.get("primary_workload_id", "")),
        "workload_refs": workload_refs,
        "stages": stages,
        "claim_boundary": "corpus_level_workflow_abstraction_input_only_not_single_qe_execution_trace",
    }


def _multi_workload_variants_from_workflow_corpus(corpus: Mapping[str, Any]) -> List[Dict[str, Any]]:
    variants: List[Dict[str, Any]] = []
    for row in corpus.get("workloads", []) or []:
        if not isinstance(row, Mapping):
            continue
        bundle = row.get("bundle", {}) if isinstance(row.get("bundle"), Mapping) else {}
        bundle_path = row.get("bundle_path")
        if not isinstance(bundle_path, Path):
            continue
        workload_id = str(row.get("workload_id", bundle.get("workflow_id", "workload")))
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), Mapping) else {}
        manifest = _manifest_from_single_workflow_corpus_row(row, corpus=corpus)
        workflow_abstraction = (
            copy.deepcopy(dict(row.get("abstraction", {})))
            if isinstance(row.get("abstraction"), Mapping)
            else build_qe_workflow_fpga_abstraction(bundle, workload_id=workload_id)
        )
        variants.append({
            "workload_id": workload_id,
            "description": str(
                metadata.get("description")
                or metadata.get("material")
                or bundle.get("workflow_id")
                or workload_id
            ),
            "variant_knobs": {
                "source_kind": "workflow_corpus",
                "corpus_id": str(corpus.get("corpus_id", "")),
                "bundle_path": str(bundle_path),
                "material": str(metadata.get("material", "")),
                "size_class": str(metadata.get("size_class", "")),
            },
            "manifest": manifest,
            "workflow_bundle": copy.deepcopy(dict(bundle)),
            "workflow_abstraction": workflow_abstraction,
        })
    return variants


def _manifest_from_single_workflow_corpus_row(
    row: Mapping[str, Any],
    *,
    corpus: Mapping[str, Any],
) -> Dict[str, Any]:
    bundle = row.get("bundle", {}) if isinstance(row.get("bundle"), Mapping) else {}
    bundle_path = row.get("bundle_path")
    if not isinstance(bundle_path, Path):
        raise ValueError("workflow corpus row must include resolved bundle_path")
    workload_id = str(row.get("workload_id", bundle.get("workflow_id", "workload")))
    manifest = _external_manifest_from_workflow_bundle(bundle, bundle_path=bundle_path)
    cases: List[Dict[str, Any]] = []
    for case in manifest.get("cases", []) or []:
        if not isinstance(case, Mapping):
            continue
        case_row = copy.deepcopy(dict(case))
        case_row["case_id"] = f"{workload_id}__{case_row.get('case_id', 'case')}"
        case_row["corpus_workload_id"] = workload_id
        case_row["source_kind"] = "workflow_corpus_external_qe_workflow_bundle"
        provenance = case_row.get("baseline_run_provenance", {})
        provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
        provenance["corpus_id"] = str(corpus.get("corpus_id", ""))
        provenance["corpus_workload_id"] = workload_id
        provenance["bundle_path"] = str(bundle_path)
        provenance["claim_boundary"] = "corpus source facts only; not trusted QE runtime/L4 performance evidence unless separately proven"
        case_row["baseline_run_provenance"] = provenance
        case_row["case_hash"] = _stable_hex_hash(_without_keys(case_row, "case_hash"))
        cases.append(case_row)
    classes = sorted({_stage_class(str(case.get("stage_type", ""))) for case in cases})
    manifest["suite_id"] = workload_id
    manifest["source_kind"] = "workflow_corpus_single_external_qe_workflow_bundle"
    manifest["status"] = "external_corpus_workload_input"
    manifest["workflow_scope"] = str(row.get("workflow_scope") or corpus.get("workflow_scope") or (
        "scf_only_measured_seed" if classes == ["scf"] else "external_qe_workflow_corpus"
    ))
    manifest["cases"] = cases
    manifest["workflow_classes"] = classes
    manifest["corpus"] = {
        "corpus_id": str(corpus.get("corpus_id", "")),
        "primary_workload_id": str(corpus.get("primary_workload_id", "")),
        "workload_count": len(corpus.get("workloads", []) or []),
    }
    manifest["suite_hash"] = _stable_hex_hash(_without_keys(manifest, "suite_hash"))
    return manifest


def _measured_qe_workload_readiness(row: Mapping[str, Any]) -> Dict[str, Any]:
    workload_id = str(row.get("workload_id", ""))
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), Mapping) else {}
    bundle = row.get("bundle", {}) if isinstance(row.get("bundle"), Mapping) else {}
    abstraction = row.get("abstraction", {}) if isinstance(row.get("abstraction"), Mapping) else {}
    source = abstraction.get("source", {}) if isinstance(abstraction.get("source"), Mapping) else {}
    features = abstraction.get("features", {}) if isinstance(abstraction.get("features"), Mapping) else {}
    data_objects = abstraction.get("data_objects", {}) if isinstance(abstraction.get("data_objects"), Mapping) else {}
    runtime_environment = features.get("runtime_environment", {}) if isinstance(features.get("runtime_environment"), Mapping) else {}
    correctness = features.get("correctness_observables", {}) if isinstance(features.get("correctness_observables"), Mapping) else {}
    observed_values = correctness.get("observed_values", {}) if isinstance(correctness.get("observed_values"), Mapping) else {}
    kernel_weights = features.get("kernel_weights", {}) if isinstance(features.get("kernel_weights"), Mapping) else {}
    qe_save_dir = data_objects.get("qe_save_dir", {}) if isinstance(data_objects.get("qe_save_dir"), Mapping) else {}
    marker_values = [
        str(metadata.get("measurement_source", "")),
        str(bundle.get("measurement_source", "")),
        str(bundle.get("source_kind", "")),
    ]
    measured_marker = any(value in {"measured_qe_run", "measured_qe_workflow_bundle", "real_qe_run"} for value in marker_values)
    selection_policy = str(metadata.get("selection_policy") or bundle.get("selection_policy") or "").strip()
    blockers: List[str] = []
    if not measured_marker:
        blockers.append(f"workload_not_marked_measured_qe:{workload_id}")
    if not selection_policy:
        blockers.append(f"selection_policy_missing:{workload_id}")
    if not source.get("observed_runtime"):
        blockers.append(f"observed_runtime_missing:{workload_id}")
    if not runtime_environment.get("qe_version"):
        blockers.append(f"qe_version_missing:{workload_id}")
    if not runtime_environment.get("mpi_processes"):
        blockers.append(f"mpi_processes_missing:{workload_id}")
    if not kernel_weights:
        blockers.append(f"phase_timing_missing:{workload_id}")
    if not observed_values.get("final_total_energy_ry"):
        blockers.append(f"final_total_energy_missing:{workload_id}")
    if not observed_values.get("scf_accuracy_ry"):
        blockers.append(f"scf_accuracy_missing:{workload_id}")
    if not qe_save_dir.get("observed_path") or int(_finite_float(qe_save_dir.get("observed_file_count"), default=0.0)) <= 0:
        blockers.append(f"qe_save_dir_artifacts_missing:{workload_id}")
    nested_refs = [ref for ref in row.get("nested_artifact_refs", []) or [] if isinstance(ref, Mapping)]
    has_file_backed_input = any(str(ref.get("logical_path", "")).endswith("input_path") and ref.get("exists") for ref in nested_refs)
    has_file_backed_log = any(str(ref.get("logical_path", "")).endswith("log_path") and ref.get("exists") for ref in nested_refs)
    if not has_file_backed_input:
        blockers.append(f"file_backed_qe_input_missing:{workload_id}")
    if not has_file_backed_log:
        blockers.append(f"file_backed_qe_log_missing:{workload_id}")
    status = "ready_for_model_level_experiments" if not blockers else "blocked"
    return {
        "schema_version": "dse.qe_fpga.measured_qe_workload_readiness.v1",
        "status": status,
        "blockers": blockers,
        "allowed_use": (
            "model_level_search_and_ablation_experiment_input"
            if status == "ready_for_model_level_experiments"
            else "provenance_and_fixture_pipeline_testing_only"
        ),
        "forbidden_use": [
            "hardware_performance_result",
            "qe_numerical_correctness_result",
            "representative_qe_benchmark_claim_without_selection_policy_review",
        ],
        "evidence": {
            "measurement_source": next((value for value in marker_values if value), None),
            "selection_policy": selection_policy or None,
            "runtime_environment": dict(runtime_environment),
            "observed_total_phase_wall_seconds": features.get("observed_total_phase_wall_seconds"),
            "observed_correctness_values": dict(observed_values),
            "qe_save_dir": {
                "observed_path": qe_save_dir.get("observed_path"),
                "observed_file_count": qe_save_dir.get("observed_file_count"),
                "bytes": qe_save_dir.get("bytes"),
            },
        },
        "evidence_boundary": "measured_qe_workload_readiness_only_not_hardware_or_correctness_result",
    }


def _manifest_from_workflow_corpus(corpus: Mapping[str, Any]) -> Dict[str, Any]:
    cases: List[Dict[str, Any]] = []
    for row in corpus.get("workloads", []) or []:
        if not isinstance(row, Mapping):
            continue
        bundle = row.get("bundle", {}) if isinstance(row.get("bundle"), Mapping) else {}
        bundle_path = row.get("bundle_path")
        if not isinstance(bundle_path, Path):
            continue
        workload_id = str(row.get("workload_id", bundle.get("workflow_id", "workload")))
        workload_manifest = _external_manifest_from_workflow_bundle(bundle, bundle_path=bundle_path)
        for case in workload_manifest.get("cases", []) or []:
            if not isinstance(case, Mapping):
                continue
            case_row = copy.deepcopy(dict(case))
            case_row["case_id"] = f"{workload_id}__{case_row.get('case_id', 'case')}"
            case_row["corpus_workload_id"] = workload_id
            case_row["source_kind"] = "workflow_corpus_external_qe_workflow_bundle"
            provenance = case_row.get("baseline_run_provenance", {})
            if isinstance(provenance, Mapping):
                provenance = dict(provenance)
            else:
                provenance = {}
            provenance["corpus_id"] = str(corpus.get("corpus_id", ""))
            provenance["corpus_workload_id"] = workload_id
            provenance["bundle_path"] = str(bundle_path)
            provenance["claim_boundary"] = "corpus source facts only; not trusted QE runtime/L4 performance evidence unless separately proven"
            case_row["baseline_run_provenance"] = provenance
            case_row["case_hash"] = _stable_hex_hash(_without_keys(case_row, "case_hash"))
            cases.append(case_row)
    classes = sorted({_stage_class(str(case.get("stage_type", ""))) for case in cases})
    has_relax = any(_stage_class(str(case.get("stage_type", ""))) in {"relax", "vc_relax"} for case in cases)
    manifest = {
        "schema_version": "dse.qe_mainflow_workload_suite_manifest.v1",
        "suite_id": str(corpus.get("corpus_id", "workflow_corpus")),
        "source_kind": "workflow_corpus_external_qe_workflow_bundles",
        "status": "external_corpus_input",
        "release_id": "external_qe_workflow_corpus_import",
        "workflow_scope": str(corpus.get("workflow_scope", "")) or (
            "scf_only_measured_seed" if classes == ["scf"] else "external_qe_workflow_corpus"
        ),
        "required_mainflow_classes": ["scf", "nscf", "post_processing"],
        "relax_policy": {
            "status": "included" if has_relax else "deferred",
            "stage_types": ["relax"] if has_relax else [],
            "rationale": (
                "Workflow corpus includes relax/vc-relax coverage."
                if has_relax
                else "Workflow corpus did not provide relax/vc-relax stages; force/stress closure remains out of this imported suite."
            ),
        },
        "cases": cases,
        "workflow_classes": classes,
        "corpus": {
            "corpus_id": str(corpus.get("corpus_id", "")),
            "primary_workload_id": str(corpus.get("primary_workload_id", "")),
            "workload_count": len(corpus.get("workloads", []) or []),
        },
        "candidate_identity_policy": {
            "workload_case_ids_participate": False,
            "workload_features_participate": False,
            "reason": "Corpus workload facts steer evaluation context but do not enter candidate identity aliases.",
            "forbidden_candidate_identity_fields": [
                "case_id",
                "stage_type",
                "qe_command",
                "input_hashes",
                "expected_outputs",
                "kernel_coverage",
                "physical_quantities",
                "baseline_run_provenance",
            ],
        },
        "claim_boundary": "workflow_corpus_manifest_only_not_representative_qe_runtime_or_fpga_evidence",
    }
    manifest["suite_hash"] = _stable_hex_hash(_without_keys(manifest, "suite_hash"))
    return manifest


def _workflow_corpus_input_ref(corpus: Mapping[str, Any]) -> Dict[str, Any]:
    path = corpus.get("path")
    workloads = [row for row in corpus.get("workloads", []) or [] if isinstance(row, Mapping)]
    return {
        "path": str(path),
        "sha256": _file_sha256(path) if isinstance(path, Path) else None,
        "workload_count": len(workloads),
        "workloads": [
            {
                "workload_id": str(row.get("workload_id", "")),
                "bundle_ref": {
                    "path": str(row.get("bundle_path")),
                    "sha256": _file_sha256(row.get("bundle_path")) if isinstance(row.get("bundle_path"), Path) else None,
                },
                "nested_artifact_ref_count": len(row.get("nested_artifact_refs", []) or []),
                "nested_artifact_refs": list(row.get("nested_artifact_refs", []) or []),
            }
            for row in workloads
        ],
    }


def _case_from_external_stage(stage: Mapping[str, Any], *, index: int) -> Dict[str, Any]:
    stage_type = _infer_external_stage_type(stage)
    stage_id = str(stage.get("stage_id") or f"external_stage_{index:02d}_{stage_type}")
    input_text = stage.get("input", stage.get("pw_input", stage.get("input_text", "")))
    log_text = stage.get("stdout", stage.get("log", stage.get("pw_log", stage.get("log_text"))))
    input_path = str(stage.get("input_path") or stage.get("pw_input_path") or f"external/{stage_id}.in")
    log_path = str(stage.get("log_path") or stage.get("pw_log_path") or f"external/{stage_id}.out")
    input_artifacts: List[Dict[str, Any]] = []
    if isinstance(input_text, str) and input_text:
        input_artifacts.append(_artifact_from_text(input_path, input_text, "qe_input"))
    elif stage.get("input_path") or stage.get("pw_input_path"):
        input_ref = _artifact_from_file(Path(input_path), "qe_input")
        if input_ref["exists"]:
            input_artifacts.append(input_ref)
    if isinstance(log_text, str) and log_text:
        input_artifacts.append(_artifact_from_text(log_path, log_text, "qe_stdout_observed_or_fixture"))
    elif stage.get("log_path") or stage.get("pw_log_path"):
        log_ref = _artifact_from_file(Path(log_path), "qe_stdout_observed_or_fixture")
        if log_ref["exists"]:
            input_artifacts.append(log_ref)
    profile = stage.get("profile", stage.get("profile_json", stage.get("timing")))
    if isinstance(profile, Mapping):
        profile_path = str(stage.get("profile_path") or f"external/{stage_id}_profile.json")
        input_artifacts.append(_artifact_from_payload(profile_path, profile, "qe_profile_or_timing_metadata"))
    elif stage.get("profile_path"):
        profile_ref = _artifact_from_file(Path(str(stage["profile_path"])), "qe_profile_or_timing_metadata")
        if profile_ref["exists"]:
            input_artifacts.append(profile_ref)
    workflow_stage = dict(stage)
    workflow_stage.setdefault("stage_id", stage_id)
    workflow_stage.setdefault("stage_type", stage_type)
    workflow_stage.setdefault("program", str(stage.get("program", "pw.x")))
    if "stdout" in workflow_stage and "log" not in workflow_stage:
        workflow_stage["log"] = workflow_stage["stdout"]
    if isinstance(input_text, str) and input_text:
        workflow_stage.setdefault("input", input_text)
        workflow_stage.setdefault("input_path", input_path)
    if isinstance(log_text, str) and log_text:
        workflow_stage.setdefault("log_path", log_path)
    kernel_coverage = sorted(set(_external_kernel_coverage(stage_type, stage)))
    physical_quantities = _external_physical_quantities(stage_type)
    case = {
        "case_id": stage_id,
        "stage_type": stage_type,
        "workflow_class": _stage_class(stage_type),
        "qe_command": _external_command(stage),
        "source_kind": "external_qe_workflow_bundle",
        "adapter_boundary": {
            "profile_id": "dft_qe_pw_static",
            "importer_id": "dft_qe_pw",
            "qe_specific_fields_scope": "reference_workload_domain_metadata_only",
            "generic_core_required_qe_fields": [],
        },
        "input_artifacts": input_artifacts,
        "input_hashes": {artifact["path"]: artifact["sha256"] for artifact in input_artifacts},
        "step1_source": {"stages": [workflow_stage]},
        "baseline_sequence": [
            {
                "step_id": stage_id,
                "program": str(workflow_stage.get("program", "pw.x")),
                "command": _external_command(stage),
                "input_path": input_path,
                "input": input_text if isinstance(input_text, str) else None,
                "include_in_performance": True,
            }
        ],
        "expected_outputs": _external_expected_outputs(stage_type, stage, physical_quantities),
        "kernel_coverage": kernel_coverage,
        "physical_quantities": physical_quantities,
        "baseline_run_provenance": {
            "status": "external_bundle_structural_input",
            "source": "user_supplied_qe_workflow_bundle",
            "command": _external_command(stage),
            "claim_boundary": "external source facts only; not trusted QE runtime/L4 performance evidence unless separately proven",
        },
        "tolerance_reference": {
            "tolerance_profile_id": "qe_mainflow_correctness_v1",
            "required_fields": [
                "kernel_absolute_tolerance",
                "kernel_relative_tolerance",
                "kernel_error_metric",
                "scf_total_energy_tolerance_ry",
                "density_residual_tolerance",
                "eigenvalue_summary_tolerance_ry",
                "source",
                "rationale",
            ],
        },
        "blocker_status": {
            "structural_status": "ready",
            "trusted_closure_status": "blocked_until_real_qe_baseline_and_l4_evidence",
            "reason": "External bundle supplies workload facts; trusted speedup still needs independent QE/L4/HLS evidence.",
        },
        "candidate_identity_participation": False,
    }
    case["case_hash"] = _stable_hex_hash(_without_keys(case, "case_hash"))
    return case


def _workflow_bundle_from_manifest(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    return workflow_bundle_from_qe_mainflow_manifest(manifest)


def _artifact_from_text(path: str, text: str, purpose: str) -> Dict[str, Any]:
    encoded = text.strip().encode("utf-8")
    return {
        "path": path,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "hash_algorithm": "sha256",
        "purpose": purpose,
    }


def _artifact_from_payload(path: str, payload: Mapping[str, Any], purpose: str) -> Dict[str, Any]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return {
        "path": path,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "hash_algorithm": "sha256",
        "purpose": purpose,
    }


def _artifact_from_file(path: Path, purpose: str) -> Dict[str, Any]:
    exists = path.exists() and path.is_file()
    return {
        "path": str(path),
        "sha256": _file_sha256(path).removeprefix("sha256:") if exists else "",
        "hash_algorithm": "sha256",
        "purpose": purpose,
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else 0,
    }


def _stable_hex_hash(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _without_keys(payload: Mapping[str, Any], *keys: str) -> Dict[str, Any]:
    excluded = set(keys)
    return {key: copy.deepcopy(value) for key, value in payload.items() if key not in excluded}


def _stage_class(stage_type: str) -> str:
    normalized = str(stage_type).strip().lower().replace("-", "_")
    return "post_processing" if normalized in {"bands", "dos", "projwfc"} else normalized


def _infer_external_stage_type(stage: Mapping[str, Any]) -> str:
    if stage.get("stage_type"):
        return str(stage["stage_type"]).strip().lower().replace("-", "_")
    program = str(stage.get("program", "pw.x")).lower()
    if "bands" in program:
        return "bands"
    if "dos" in program:
        return "dos"
    if "projwfc" in program:
        return "projwfc"
    text = stage.get("input", stage.get("pw_input", stage.get("input_text", "")))
    if isinstance(text, str):
        lowered = text.lower()
        if "calculation" in lowered:
            for item in ("vc-relax", "vc_relax", "relax", "nscf", "bands", "scf"):
                if item in lowered:
                    return item.replace("-", "_")
    input_path = stage.get("input_path") or stage.get("pw_input_path")
    if input_path:
        try:
            for fact in parse_qe_pw_input(str(input_path), source_path=str(input_path)):
                if fact.field == "input.calculation":
                    return str(fact.value).strip("'\"").lower().replace("-", "_")
        except Exception:
            pass
    return "scf" if program == "pw.x" else "unknown"


def _external_command(stage: Mapping[str, Any]) -> List[str]:
    command = stage.get("command")
    if isinstance(command, Sequence) and not isinstance(command, (str, bytes)):
        return [str(item) for item in command]
    program = str(stage.get("program", "pw.x"))
    input_path = str(stage.get("input_path") or stage.get("pw_input_path") or "external.in")
    return [program, "-in", input_path]


def _resolve_external_workflow_bundle_paths(bundle: Mapping[str, Any], *, base_dir: Path) -> Dict[str, Any]:
    resolved = copy.deepcopy(dict(bundle))
    stages = []
    for stage in resolved.get("stages", []) or []:
        if not isinstance(stage, Mapping):
            stages.append(stage)
            continue
        row = dict(stage)
        for key in ("input_path", "pw_input_path", "log_path", "pw_log_path", "profile_path", "save_dir", "prefix_save_dir"):
            if row.get(key):
                row[key] = str(_resolve_bundle_path(str(row[key]), base_dir=base_dir))
        if isinstance(row.get("pseudopotential_paths"), Sequence) and not isinstance(row.get("pseudopotential_paths"), (str, bytes)):
            row["pseudopotential_paths"] = [
                str(_resolve_bundle_path(str(path), base_dir=base_dir))
                for path in row.get("pseudopotential_paths", []) or []
            ]
        stages.append(row)
    resolved["stages"] = stages
    return resolved


def _resolve_bundle_path(path: str, *, base_dir: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return base_dir / candidate


def _workflow_bundle_nested_artifact_refs(bundle: Mapping[str, Any]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for index, stage in enumerate(bundle.get("stages", []) or []):
        if not isinstance(stage, Mapping):
            continue
        for key in ("input_path", "pw_input_path", "log_path", "pw_log_path", "profile_path"):
            if stage.get(key):
                refs.append(_nested_file_ref(f"stages[{index}].{key}", Path(str(stage[key]))))
        for key in ("save_dir", "prefix_save_dir"):
            if stage.get(key):
                refs.append(_nested_path_ref(f"stages[{index}].{key}", Path(str(stage[key]))))
        for pseudo_index, pseudo_path in enumerate(stage.get("pseudopotential_paths", []) or []):
            refs.append(_nested_file_ref(f"stages[{index}].pseudopotential_paths[{pseudo_index}]", Path(str(pseudo_path))))
    return refs


def _nested_file_ref(logical_path: str, path: Path) -> Dict[str, Any]:
    exists = path.exists() and path.is_file()
    return {
        "logical_path": logical_path,
        "path": str(path),
        "exists": exists,
        "kind": "file",
        "size_bytes": path.stat().st_size if exists else 0,
        "sha256": _file_sha256(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _nested_path_ref(logical_path: str, path: Path) -> Dict[str, Any]:
    exists = path.exists()
    file_refs = [
        _nested_file_ref(f"{logical_path}/{child.relative_to(path)}", child)
        for child in sorted(path.rglob("*"))
        if child.is_file()
    ] if exists and path.is_dir() else []
    return {
        "logical_path": logical_path,
        "path": str(path),
        "exists": exists,
        "kind": "directory" if path.is_dir() else "file",
        "file_count": len(file_refs),
        "size_bytes": sum(int(ref.get("size_bytes", 0)) for ref in file_refs),
        "sha256": _stable_payload_hash({"files": file_refs}) if file_refs else (_file_sha256(path) if exists and path.is_file() else None),
        "hash_algorithm": "sha256",
        "files": file_refs,
    }


def _external_kernel_coverage(stage_type: str, stage: Mapping[str, Any]) -> List[str]:
    explicit = stage.get("kernel_coverage")
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        return [str(item) for item in explicit]
    defaults = {
        "scf": ["h_psi", "fft", "rho_out", "mix_rho", "diagonalization"],
        "nscf": ["h_psi", "fft", "diagonalization", "subspace_rotation"],
        "relax": ["h_psi", "fft", "rho_out", "mix_rho", "forces"],
        "vc_relax": ["h_psi", "fft", "rho_out", "mix_rho", "forces", "stress"],
        "bands": ["band_path_projection", "diagonalization"],
        "dos": ["reduction", "io"],
        "projwfc": ["projector", "reduction"],
    }
    return defaults.get(stage_type, ["stage_compute"])


def _external_physical_quantities(stage_type: str) -> List[str]:
    if stage_type in {"scf", "relax", "vc_relax"}:
        return ["total_energy_ry", "density_residual", "forces", "stress"]
    if stage_type in {"nscf", "bands"}:
        return ["eigenvalue_summary", "band_occupations"]
    if stage_type in {"dos", "projwfc"}:
        return ["projected_density_of_states", "projection_weights"]
    return ["workflow_observable"]


def _external_expected_outputs(
    stage_type: str,
    stage: Mapping[str, Any],
    physical_quantities: Sequence[str],
) -> Dict[str, Any]:
    explicit = stage.get("expected_outputs")
    if isinstance(explicit, Mapping) and explicit:
        return dict(explicit)
    return {
        str(quantity): {
            "status": "required_not_supplied_by_external_bundle",
            "role": f"{stage_type}_correctness_oracle_placeholder",
            "required_before_trusted_closure": True,
            "claim_boundary": "placeholder records requirement only; not a physical oracle value",
        }
        for quantity in physical_quantities
    }


def _canonical_argv(args: argparse.Namespace) -> List[str]:
    argv = [
        "--out",
        str(args.out),
    ]
    if args.workflow_bundle is not None:
        argv.extend([
            "--workflow-bundle",
            str(args.workflow_bundle),
        ])
    if args.workflow_corpus is not None:
        argv.extend([
            "--workflow-corpus",
            str(args.workflow_corpus),
        ])
    if args.feedback_samples is not None:
        argv.extend([
            "--feedback-samples",
            str(args.feedback_samples),
        ])
    argv.extend([
        "--workload-run-id",
        str(args.workload_run_id),
        "--candidate-budget",
        str(int(args.candidate_budget)),
        "--promotion-budget",
        str(int(args.promotion_budget)),
    ])
    if int(args.implementation_package_budget) != 2:
        argv.extend([
            "--implementation-package-budget",
            str(int(args.implementation_package_budget)),
        ])
    if bool(args.include_relax) is False:
        argv.append("--no-include-relax")
    return argv


def _replay_manifest(
    *,
    out_dir: Path,
    argv: Sequence[str],
    payload_by_artifact: Mapping[str, Mapping[str, Any]],
    input_refs: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    artifact_byte_hashes: Dict[str, Dict[str, Any]] = {}
    artifact_payload_hashes: Dict[str, str] = {}
    for rel_path, payload in sorted(payload_by_artifact.items()):
        path = out_dir / rel_path
        artifact_byte_hashes[rel_path] = {
            "sha256": _file_sha256(path),
            "size_bytes": path.stat().st_size,
        }
        artifact_payload_hashes[rel_path] = _stable_payload_hash(payload)
    return {
        "schema_version": "dse.qe_fpga_replay_manifest.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "method_name": QE_FPGA_DSE_METHOD_NAME,
        "command": {
            "script": str(Path(__file__).resolve()),
            "argv": list(argv),
            "cwd": str(REPO_ROOT),
        },
        "environment": {
            "python_executable": sys.executable,
            "python_version": sys.version,
            "platform": sys.platform,
            "pid": os.getpid(),
        },
        "git": {
            "revision": _git_revision(),
            "dirty": _git_dirty(),
        },
        "input_refs": dict(input_refs or {}),
        "artifact_count": len(payload_by_artifact),
        "artifact_byte_hashes": artifact_byte_hashes,
        "artifact_payload_hashes": artifact_payload_hashes,
        "verification": {
            "status": "created_not_verified",
            "verifier": "dse_v2/scripts/dse/verify_qe_fpga_replay_manifest.py",
        },
        "claim_boundary": "replay_manifest_provenance_only_not_hardware_evidence",
    }


def run_pipeline(args: argparse.Namespace) -> Dict[str, Any]:
    out_dir = args.out
    input_refs: Dict[str, Any] = {}
    input_workflow_bundle: Dict[str, Any] | None = None
    input_workflow_corpus: Dict[str, Any] | None = None
    workload_corpus_report: Dict[str, Any] | None = None
    multi_workload_variants: List[Dict[str, Any]] | None = None
    multi_workload_input_source: Dict[str, Any] | None = None
    feedback_samples: List[Dict[str, Any]] = []
    if args.workflow_corpus is not None:
        workflow_corpus = _load_workflow_corpus(args.workflow_corpus)
        input_workflow_corpus = _workflow_corpus_input_ref(workflow_corpus)
        input_refs["workflow_corpus"] = input_workflow_corpus
        workload_corpus_report = _workflow_corpus_report(workflow_corpus)
        multi_workload_variants = _multi_workload_variants_from_workflow_corpus(workflow_corpus)
        multi_workload_input_source = {
            "source_kind": "workflow_corpus",
            "corpus_id": str(workflow_corpus.get("corpus_id", "")),
            "primary_workload_id": str(workflow_corpus.get("primary_workload_id", "")),
            "workload_count": len(multi_workload_variants),
            "path": str(args.workflow_corpus),
        }
        primary = workflow_corpus["primary"]
        input_workflow_bundle = {
            "path": str(primary["bundle_path"]),
            "sha256": _file_sha256(primary["bundle_path"]),
            "nested_artifact_ref_count": len(primary.get("nested_artifact_refs", []) or []),
            "nested_artifact_refs": list(primary.get("nested_artifact_refs", []) or []),
            "source": "workflow_corpus_primary_workload",
            "workload_id": str(primary.get("workload_id", "")),
        }
        manifest = _manifest_from_workflow_corpus(workflow_corpus)
        workflow_bundle = _workflow_bundle_from_workflow_corpus(workflow_corpus)
    elif args.workflow_bundle is not None:
        input_workflow_bundle = load_qe_workflow_bundle(args.workflow_bundle)
        resolved_bundle_path = Path(str(input_workflow_bundle.get("_bundle_manifest_path", args.workflow_bundle)))
        nested_artifact_refs = _workflow_bundle_nested_artifact_refs(input_workflow_bundle)
        manifest = _external_manifest_from_workflow_bundle(
            input_workflow_bundle,
            bundle_path=resolved_bundle_path,
        )
        workflow_bundle = copy.deepcopy(input_workflow_bundle)
        input_refs["workflow_bundle"] = {
            "path": str(resolved_bundle_path),
            "sha256": _file_sha256(resolved_bundle_path),
            "nested_artifact_ref_count": len(nested_artifact_refs),
            "nested_artifact_refs": nested_artifact_refs,
        }
    else:
        manifest = default_qe_mainflow_workload_suite(include_relax=bool(args.include_relax))
        workflow_bundle = _workflow_bundle_from_manifest(manifest)
    if args.feedback_samples is not None:
        feedback_samples = _load_feedback_samples(args.feedback_samples)
        input_refs["feedback_samples"] = {
            "path": str(args.feedback_samples),
            "sha256": _file_sha256(args.feedback_samples),
            "sample_count": len(feedback_samples),
        }
    workflow_abstraction = build_qe_workflow_fpga_abstraction(
        workflow_bundle,
        workload_id=str(args.workload_run_id),
    )
    problem = build_qe_fpga_deployment_search_problem(
        manifest,
        workload_run_id=str(args.workload_run_id),
        workflow_abstraction=workflow_abstraction,
    )
    search_policy = HierarchicalFunnelSearchPolicy(
        bottleneck_keys=("memory_topology", "data_residency", "offload_boundary"),
    )
    records = search_policy.propose(problem, budget=int(args.candidate_budget))
    search_checkpoint = search_policy.checkpoint(problem).to_dict()
    search_checkpoint["proposal_budget"] = int(args.candidate_budget)
    candidate_payloads = [record.to_dict() for record in records]
    candidate_queue = _candidate_queue(candidate_payloads, budget=int(args.candidate_budget))
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidate_payloads,
        promotion_budget=int(args.promotion_budget),
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=True,
    )
    promotion = _promotion_queue(screening)
    l2_bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        promotion["promotion_queue"],
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=True,
    )
    l2_results = run_qe_fpga_l2_tlm_requests(l2_bundle)
    calibration = build_qe_fpga_l2_calibration_report(screening, l2_results)
    adaptive_search = build_qe_fpga_adaptive_multifidelity_search_report(
        manifest,
        problem,
        screening,
        evaluation_budget=max(int(args.promotion_budget) + 3, int(args.promotion_budget)),
        initial_designs=min(3, max(1, int(args.promotion_budget))),
        external_feedback=feedback_samples,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=True,
    )
    unguided_neural_search = build_qe_fpga_neural_multifidelity_search_report(
        manifest,
        problem,
        screening,
        evaluation_budget=max(int(args.promotion_budget) + 3, int(args.promotion_budget)),
        initial_designs=min(3, max(1, int(args.promotion_budget))),
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=True,
    )
    neural_surrogate_training = build_qe_fpga_neural_surrogate_training_report(
        manifest,
        problem,
        screening,
        unguided_neural_search,
        max_epochs=20,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=True,
    )
    neural_multifidelity_search = build_qe_fpga_neural_multifidelity_search_report(
        manifest,
        problem,
        screening,
        evaluation_budget=max(int(args.promotion_budget) + 3, int(args.promotion_budget)),
        initial_designs=min(3, max(1, int(args.promotion_budget))),
        trained_surrogate=neural_surrogate_training,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=True,
    )
    neuromf_policy_evaluation = build_qe_fpga_neuromf_policy_evaluation_report(
        manifest,
        problem,
        screening,
        unguided_neural_search=unguided_neural_search,
        trained_neural_search=neural_multifidelity_search,
        trained_surrogate=neural_surrogate_training,
        evaluation_budget=max(int(args.promotion_budget) + 3, int(args.promotion_budget)),
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=True,
    )
    search_baseline = build_qe_fpga_search_baseline_report(
        manifest,
        problem,
        screening,
        evaluation_budget=int(args.promotion_budget),
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=True,
    )
    wamf_dse = build_qe_fpga_wamf_dse_report(
        manifest,
        problem,
        screening,
        evaluation_budget=max(int(args.promotion_budget) + 3, int(args.promotion_budget)),
        initial_designs=min(3, max(1, int(args.promotion_budget))),
        adaptive_search=adaptive_search,
        unguided_neural_search=unguided_neural_search,
        trained_neural_search=neural_multifidelity_search,
        neural_surrogate_training=neural_surrogate_training,
        policy_evaluation=neuromf_policy_evaluation,
        search_baseline=search_baseline,
        workflow_abstraction=workflow_abstraction,
        require_workflow_feature_contract=True,
    )
    external_feedback_validation = (
        _external_feedback_validation_report(
            feedback_samples=feedback_samples,
            screening=screening,
            l2_results=l2_results,
            adaptive_search=adaptive_search,
            search_baseline=search_baseline,
        )
        if feedback_samples
        else None
    )
    search_problem = problem.to_dict()
    step2_feedback_update, search_iteration_plan = _build_feedback_informed_iteration_artifacts(
        search_problem=search_problem,
        search_checkpoint=search_checkpoint,
        candidates=candidate_payloads,
        adaptive_search=adaptive_search,
        proposal_budget=int(args.candidate_budget),
    )
    validation_gated_queue = _build_validation_gated_queue_from_search_baseline(
        search_baseline=search_baseline,
        external_feedback_validation=external_feedback_validation,
        promotion_budget=int(args.promotion_budget),
    )
    next_promotion_queue = _feedback_informed_next_promotion_queue(
        search_iteration_plan,
        promotion_budget=int(args.promotion_budget),
        validation_gated_queue=validation_gated_queue,
    )
    next_l2_request_bundle = _feedback_informed_next_l2_request_bundle(
        manifest,
        problem,
        next_promotion_queue,
        workflow_abstraction=workflow_abstraction,
    )
    next_l2_results = None
    if next_l2_request_bundle is not None:
        next_l2_results = run_qe_fpga_l2_tlm_requests(next_l2_request_bundle)
        next_l2_results["feedback_informed_next_iteration"] = True
        next_l2_results["source_request_bundle"] = "qe_fpga_next_l2_request_bundle.json"
        next_l2_results["source_promotion_queue"] = "qe_fpga_next_promotion_queue.json"
        next_l2_results["claim_boundary"] = (
            "feedback_informed_next_l2_tlm_result_not_systemc_gem5_or_fpga_implementation_evidence"
        )
    multi_workload_experiment = build_qe_fpga_multi_workload_experiment_report(
        workload_run_id_prefix=str(args.workload_run_id),
        candidate_budget=int(args.candidate_budget),
        promotion_budget=int(args.promotion_budget),
        workloads=multi_workload_variants,
        input_source=multi_workload_input_source,
    )
    implementation_plan = build_qe_fpga_implementation_package_plan(
        manifest,
        l2_bundle,
        l2_results,
        package_budget=int(args.implementation_package_budget),
    )
    implementation_materialization = materialize_qe_fpga_implementation_packages(
        implementation_plan,
        out_dir,
    )
    hls_attempt_summary = run_qe_fpga_hls_attempts_for_materialized_packages(
        implementation_materialization,
        out_dir,
        timeout_s=120,
    )
    vivado_attempt_summary = run_qe_fpga_vivado_attempts_for_materialized_packages(
        implementation_materialization,
        out_dir,
        timeout_s=120,
    )
    summary = _summary(
        workload_suite=manifest,
        search_problem=search_problem,
        candidate_queue=candidate_queue,
        screening=screening,
        promotion=promotion,
        l2_bundle=l2_bundle,
        l2_results=l2_results,
        calibration=calibration,
        adaptive_search=adaptive_search,
        neural_multifidelity_search=neural_multifidelity_search,
        neural_surrogate_training=neural_surrogate_training,
        neuromf_policy_evaluation=neuromf_policy_evaluation,
        wamf_dse=wamf_dse,
        search_baseline=search_baseline,
        multi_workload_experiment=multi_workload_experiment,
        implementation_plan=implementation_plan,
        implementation_materialization=implementation_materialization,
        hls_attempt_summary=hls_attempt_summary,
        vivado_attempt_summary=vivado_attempt_summary,
        external_feedback_validation=external_feedback_validation,
        step2_feedback_update=step2_feedback_update,
        search_iteration_plan=search_iteration_plan,
        next_promotion_queue=next_promotion_queue,
        validation_gated_queue=validation_gated_queue,
        next_l2_request_bundle=next_l2_request_bundle,
        next_l2_results=next_l2_results,
        input_workflow_bundle=input_refs.get("workflow_bundle"),
        input_workflow_corpus=input_refs.get("workflow_corpus"),
        input_feedback_samples=input_refs.get("feedback_samples"),
    )
    if summary.get("workflow_scope") == "scf_only_measured_seed":
        summary["prototype_status"] = "measured_scf_seed_l2_tlm_calibrated_not_release_complete"
    else:
        summary["prototype_status"] = "l2_tlm_calibrated_not_hardware_closed"

    payload_by_artifact = {
        "qe_mainflow_workload_suite.json": manifest,
        "qe_workflow_fpga_abstraction.json": workflow_abstraction,
        "qe_fpga_search_problem.json": search_problem,
        "qe_fpga_step2_candidates.json": candidate_queue,
        "qe_fpga_l1_screening_report.json": screening,
        "qe_fpga_promotion_queue.json": promotion,
        "qe_fpga_l2_request_bundle.json": l2_bundle,
        "qe_fpga_l2_tlm_results.json": l2_results,
        "qe_fpga_l1_l2_calibration_report.json": calibration,
        "qe_fpga_adaptive_multifidelity_search_report.json": adaptive_search,
        "qe_fpga_neural_multifidelity_search_report.json": neural_multifidelity_search,
        "qe_fpga_neural_surrogate_training_report.json": neural_surrogate_training,
        "qe_fpga_neuromf_policy_evaluation_report.json": neuromf_policy_evaluation,
        "qe_fpga_wamf_dse_report.json": wamf_dse,
        "qe_fpga_search_baseline_report.json": search_baseline,
        "qe_fpga_multi_workload_experiment_report.json": multi_workload_experiment,
        "qe_fpga_implementation_package_plan.json": implementation_plan,
        "qe_fpga_implementation_package_materialization.json": implementation_materialization,
        "qe_fpga_hls_attempt_summary.json": hls_attempt_summary,
        "qe_fpga_vivado_attempt_summary.json": vivado_attempt_summary,
    }
    if workload_corpus_report is not None:
        payload_by_artifact["qe_fpga_workload_corpus_report.json"] = workload_corpus_report
        summary["artifact_hashes"]["qe_fpga_workload_corpus_report.json"] = _stable_payload_hash(workload_corpus_report)
    if external_feedback_validation is not None:
        payload_by_artifact["qe_fpga_external_feedback_validation_report.json"] = external_feedback_validation
    if int(step2_feedback_update.get("common_objective_update_count", 0)) > 0:
        payload_by_artifact["qe_fpga_step2_feedback_update.json"] = step2_feedback_update
    if search_iteration_plan is not None:
        payload_by_artifact["qe_fpga_search_iteration_plan.json"] = search_iteration_plan
    if validation_gated_queue is not None:
        payload_by_artifact["qe_fpga_validation_gated_next_evaluation_queue.json"] = validation_gated_queue
    if next_promotion_queue is not None:
        payload_by_artifact["qe_fpga_next_promotion_queue.json"] = next_promotion_queue
    if next_l2_request_bundle is not None:
        payload_by_artifact["qe_fpga_next_l2_request_bundle.json"] = next_l2_request_bundle
    if next_l2_results is not None:
        payload_by_artifact["qe_fpga_next_l2_tlm_results.json"] = next_l2_results
    for rel_path, payload in payload_by_artifact.items():
        _write_json(out_dir / rel_path, payload)
    summary["replay_manifest"] = {
        "path": REPLAY_MANIFEST_NAME,
        "artifact_count": len(payload_by_artifact) + 1,
        "verification_status": "created_not_verified",
    }
    _write_json(out_dir / "qe_fpga_deployment_dse_summary.json", summary)
    payload_by_artifact_with_summary = dict(payload_by_artifact)
    payload_by_artifact_with_summary["qe_fpga_deployment_dse_summary.json"] = summary
    replay_manifest = _replay_manifest(
        out_dir=out_dir,
        argv=_canonical_argv(args),
        payload_by_artifact=payload_by_artifact_with_summary,
        input_refs=input_refs,
    )
    _write_json(out_dir / REPLAY_MANIFEST_NAME, replay_manifest)
    return summary


def main(argv: List[str] | None = None) -> int:
    args = parse_args(list(argv) if argv is not None else sys.argv[1:])
    summary = run_pipeline(args)
    print(json.dumps({
        "status": summary["prototype_status"],
        "out": str(args.out),
        "candidate_count": summary["candidate_count"],
        "pareto_candidate_count": summary["pareto_candidate_count"],
        "promotion_count": summary["promotion_count"],
        "l2_request_count": summary["l2_request_count"],
        "l2_executed_count": summary["l2_executed_count"],
        "adaptive_search_evaluated_count": summary["adaptive_search_evaluated_count"],
        "neural_multifidelity_search_evaluated_count": summary["neural_multifidelity_search"]["evaluated_count"],
        "neural_surrogate_training_sample_count": summary["neural_surrogate_training"]["sample_count"],
        "neuromf_policy_evaluation_policy_count": summary["neuromf_policy_evaluation"]["policy_count"],
        "search_baseline_policy_count": summary["search_baseline_policy_count"],
        "multi_workload_experiment_workload_count": summary["multi_workload_experiment_workload_count"],
        "implementation_package_count": summary["implementation_package_count"],
        "implementation_package_materialized_count": summary["implementation_package_materialized_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
