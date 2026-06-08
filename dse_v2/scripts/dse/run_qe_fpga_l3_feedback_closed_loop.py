#!/usr/bin/env python3
"""Run a replayable QE FPGA L3-feedback closed-loop experiment.

The experiment deliberately composes existing tools instead of embedding a new
search model:

1. run the QE-to-FPGA DSE pipeline to produce promoted L2 requests;
2. execute those requests with the standalone generic_sim feedback runner;
3. rerun the DSE pipeline using the generated feedback samples;
4. write a summary report that keeps the evidence boundary explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.qe_fpga_deployment_dse import build_qe_fpga_l2_request_bundle  # noqa: E402
from dse_v2.mapping.multifidelity_benchmark import build_multifidelity_search_benchmark_report  # noqa: E402
from dse_v2.mapping.multifidelity_benchmark import build_multifidelity_search_benchmark_suite_report  # noqa: E402
from dse_v2.mapping.multifidelity_benchmark import build_workflow_conditioned_multifidelity_benchmark_suite_report  # noqa: E402
from dse_v2.mapping.multifidelity_validation import build_multifidelity_algorithm_validation_report  # noqa: E402
from dse_v2.mapping.multifidelity_validation import build_validation_gated_next_evaluation_queue  # noqa: E402
from dse_v2.mapping.multifidelity_validation import build_validation_gated_search_control_report  # noqa: E402

PIPELINE = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_qe_fpga_deployment_dse.py"
RUN_L3_GSIM = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_qe_fpga_l3_generic_sim_feedback.py"
DEFAULT_GENERIC_SIM = REPO_ROOT / "model" / "generic_sim_backend" / "build" / "generic_sim"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workflow-bundle", type=Path, default=None)
    parser.add_argument("--workflow-corpus", type=Path, default=None)
    parser.add_argument("--workload-run-id", default="qe_fpga_l3_closed_loop")
    parser.add_argument("--candidate-budget", type=int, default=2500)
    parser.add_argument("--promotion-budget", type=int, default=5)
    parser.add_argument("--implementation-package-budget", type=int, default=2)
    parser.add_argument("--l3-max-requests", type=int, default=0, help="Optional L3 request cap; 0 means all")
    parser.add_argument("--l3-holdout-count", type=int, default=0, help="Additional non-promoted release candidates to execute as L3 holdout samples")
    parser.add_argument("--generic-sim", type=Path, default=DEFAULT_GENERIC_SIM)
    parser.add_argument("--timeout-s", type=int, default=120)
    parser.add_argument(
        "--include-relax",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include relax/force case when using the default built-in QE suite",
    )
    args = parser.parse_args(list(argv))
    if args.workflow_bundle is not None and args.workflow_corpus is not None:
        parser.error("--workflow-bundle and --workflow-corpus are mutually exclusive")
    invocation_cwd = Path.cwd()
    args.out = _resolve_cli_path(args.out, cwd=invocation_cwd)
    if args.workflow_bundle is not None:
        args.workflow_bundle = _resolve_cli_path(args.workflow_bundle, cwd=invocation_cwd)
    if args.workflow_corpus is not None:
        args.workflow_corpus = _resolve_cli_path(args.workflow_corpus, cwd=invocation_cwd)
    args.generic_sim = _resolve_cli_path(args.generic_sim, cwd=invocation_cwd)
    return args


def _resolve_cli_path(path: Path, *, cwd: Path) -> Path:
    return path if path.is_absolute() else (cwd / path).resolve()


def _load_json_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _artifact_ref(path: Path) -> Dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _file_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _stable_payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _finite_float(value: Any, *, default: float) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _pipeline_cmd(
    *,
    out: Path,
    workload_run_id: str,
    candidate_budget: int,
    promotion_budget: int,
    implementation_package_budget: int,
    workflow_bundle: Path | None,
    workflow_corpus: Path | None,
    feedback_samples: Path | None = None,
    include_relax: bool = True,
) -> List[str]:
    cmd = [
        sys.executable,
        str(PIPELINE),
        "--out",
        str(out),
    ]
    if workflow_bundle is not None:
        cmd.extend(["--workflow-bundle", str(workflow_bundle)])
    if workflow_corpus is not None:
        cmd.extend(["--workflow-corpus", str(workflow_corpus)])
    if feedback_samples is not None:
        cmd.extend(["--feedback-samples", str(feedback_samples)])
    cmd.extend([
        "--workload-run-id",
        workload_run_id,
        "--candidate-budget",
        str(int(candidate_budget)),
        "--promotion-budget",
        str(int(promotion_budget)),
        "--implementation-package-budget",
        str(int(implementation_package_budget)),
    ])
    if not include_relax:
        cmd.append("--no-include-relax")
    return cmd


def _run_command(cmd: Sequence[str], *, timeout_s: int) -> Dict[str, Any]:
    completed = subprocess.run(
        list(cmd),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=int(timeout_s),
        check=False,
    )
    return {
        "cmd": list(cmd),
        "returncode": completed.returncode,
        "stdout_tail": str(completed.stdout)[-2000:],
        "stderr_tail": str(completed.stderr)[-2000:],
    }


def _l3_cmd(
    *,
    l2_request_bundle: Path,
    l2_results: Path | None,
    out: Path,
    generic_sim: Path,
    max_requests: int,
    timeout_s: int,
) -> List[str]:
    cmd = [
        sys.executable,
        str(RUN_L3_GSIM),
        "--l2-request-bundle",
        str(l2_request_bundle),
        "--out",
        str(out),
        "--generic-sim",
        str(generic_sim),
        "--timeout-s",
        str(int(timeout_s)),
    ]
    if l2_results is not None:
        cmd.extend(["--l2-results", str(l2_results)])
    if int(max_requests) > 0:
        cmd.extend(["--max-requests", str(int(max_requests))])
    return cmd


def run_closed_loop(args: argparse.Namespace) -> Dict[str, Any]:
    out_dir = args.out
    seed_dir = out_dir / "seed_dse"
    l3_dir = out_dir / "l3_feedback"
    feedback_dir = out_dir / "feedback_dse"
    out_dir.mkdir(parents=True, exist_ok=True)

    seed_cmd = _pipeline_cmd(
        out=seed_dir,
        workload_run_id=f"{args.workload_run_id}_seed",
        candidate_budget=int(args.candidate_budget),
        promotion_budget=int(args.promotion_budget),
        implementation_package_budget=int(args.implementation_package_budget),
        workflow_bundle=args.workflow_bundle,
        workflow_corpus=args.workflow_corpus,
        include_relax=bool(args.include_relax),
    )
    seed_run = _run_command(seed_cmd, timeout_s=int(args.timeout_s))
    if seed_run["returncode"] != 0:
        report = _failure_report(args=args, stage="seed_dse", command_result=seed_run)
        _write_json(out_dir / "qe_fpga_l3_feedback_closed_loop_report.json", report)
        return report

    l3_cmd = _l3_cmd(
        l2_request_bundle=_l3_validation_request_bundle(
            seed_dir=seed_dir,
            holdout_count=int(args.l3_holdout_count),
            max_promoted=int(args.l3_max_requests),
        ),
        l2_results=seed_dir / "qe_fpga_l2_tlm_results.json",
        out=l3_dir,
        generic_sim=args.generic_sim,
        max_requests=0,
        timeout_s=int(args.timeout_s),
    )
    l3_run = _run_command(l3_cmd, timeout_s=max(int(args.timeout_s), 120))
    if l3_run["returncode"] != 0:
        report = _failure_report(args=args, stage="l3_feedback", command_result=l3_run)
        _write_json(out_dir / "qe_fpga_l3_feedback_closed_loop_report.json", report)
        return report

    feedback_samples_path = l3_dir / "feedback_samples.json"
    feedback_cmd = _pipeline_cmd(
        out=feedback_dir,
        workload_run_id=f"{args.workload_run_id}_feedback",
        candidate_budget=int(args.candidate_budget),
        promotion_budget=int(args.promotion_budget),
        implementation_package_budget=int(args.implementation_package_budget),
        workflow_bundle=args.workflow_bundle,
        workflow_corpus=args.workflow_corpus,
        feedback_samples=feedback_samples_path,
        include_relax=bool(args.include_relax),
    )
    feedback_run = _run_command(feedback_cmd, timeout_s=int(args.timeout_s))
    if feedback_run["returncode"] != 0:
        report = _failure_report(args=args, stage="feedback_dse", command_result=feedback_run)
        _write_json(out_dir / "qe_fpga_l3_feedback_closed_loop_report.json", report)
        return report

    seed_summary = _load_json_object(seed_dir / "qe_fpga_deployment_dse_summary.json")
    seed_baseline = _load_json_object(seed_dir / "qe_fpga_search_baseline_report.json")
    seed_neuromf_policy_evaluation = _load_json_object(seed_dir / "qe_fpga_neuromf_policy_evaluation_report.json")
    seed_neuromf_policy_evaluation_ref = _artifact_ref(seed_dir / "qe_fpga_neuromf_policy_evaluation_report.json")
    seed_wamf_dse = _load_json_object(seed_dir / "qe_fpga_wamf_dse_report.json")
    seed_wamf_dse_ref = _artifact_ref(seed_dir / "qe_fpga_wamf_dse_report.json")
    seed_multi_workload_experiment = _load_json_object(seed_dir / "qe_fpga_multi_workload_experiment_report.json")
    seed_multi_workload_experiment_ref = _artifact_ref(seed_dir / "qe_fpga_multi_workload_experiment_report.json")
    seed_workflow_abstraction = _load_json_object(seed_dir / "qe_workflow_fpga_abstraction.json")
    seed_workflow_abstraction_ref = _artifact_ref(seed_dir / "qe_workflow_fpga_abstraction.json")
    l3_report = _load_json_object(l3_dir / "qe_fpga_l3_generic_sim_feedback.json")
    feedback_summary = _load_json_object(feedback_dir / "qe_fpga_deployment_dse_summary.json")
    feedback_validation = _load_json_object(feedback_dir / "qe_fpga_external_feedback_validation_report.json")
    workflow_input = _workflow_input_summary(
        seed_dir=seed_dir,
        seed_summary=seed_summary,
        workflow_bundle=args.workflow_bundle,
        workflow_corpus=args.workflow_corpus,
    )

    feedback_validation_summary = feedback_summary.get("external_feedback_validation", {})
    policy_validation = feedback_validation.get("policy_validation", {})
    best_policy = policy_validation.get("best_policy_by_feedback", {}) if isinstance(policy_validation, Mapping) else {}
    report = {
        "schema_version": "dse.qe_fpga_l3_feedback_closed_loop_report.v1",
        "status": "passed",
        "method_name": "QEFPGA_L3_GenericSimFeedbackClosedLoop",
        "algorithm_method_name": str(seed_wamf_dse.get("method_name", "WAMF-DSE")),
        "algorithm_family": str(
            seed_wamf_dse.get("algorithm_family", "workflow_conditioned_multifidelity_active_pareto_dse")
        ),
        "workload_run_id": str(args.workload_run_id),
        "workflow_input": workflow_input,
        "seed_dse": {
            "path": str(seed_dir),
            "candidate_count": int(seed_summary.get("candidate_count", 0)),
            "promotion_count": int(seed_summary.get("l2_request_count", 0)),
            "summary_ref": _artifact_ref(seed_dir / "qe_fpga_deployment_dse_summary.json"),
        },
        "l3_feedback": {
            "path": str(l3_dir),
            "status": str(l3_report.get("status", "")),
            "executed_count": int(l3_report.get("executed_count", 0)),
            "passed_count": int(l3_report.get("passed_count", 0)),
            "feedback_sample_count": int(l3_report.get("feedback_sample_count", 0)),
            "selection_role_counts": dict(l3_report.get("selection_role_counts", {}) or {})
            if isinstance(l3_report.get("selection_role_counts"), Mapping)
            else {},
            "promoted_sample_count": int(l3_report.get("selection_role_counts", {}).get("promoted", 0))
            if isinstance(l3_report.get("selection_role_counts"), Mapping)
            else 0,
            "holdout_sample_count": int(l3_report.get("selection_role_counts", {}).get("holdout", 0))
            if isinstance(l3_report.get("selection_role_counts"), Mapping)
            else 0,
            "validation_metrics": dict(l3_report.get("validation_metrics", {}))
            if isinstance(l3_report.get("validation_metrics"), Mapping)
            else {},
            "calibration": dict(l3_report.get("calibration", {}))
            if isinstance(l3_report.get("calibration"), Mapping)
            else {},
            "report_ref": _artifact_ref(l3_dir / "qe_fpga_l3_generic_sim_feedback.json"),
        },
        "feedback_dse": {
            "path": str(feedback_dir),
            "feedback_sample_count": int(feedback_validation_summary.get("feedback_sample_count", 0)),
            "validation_status": str(feedback_validation_summary.get("status", "")),
            "policy_validation_status": str(feedback_validation_summary.get("policy_validation_status", "")),
            "best_policy_id": str(
                feedback_validation_summary.get("policy_validation_best_policy_id")
                or best_policy.get("policy_id")
                or ""
            ),
            "summary_ref": _artifact_ref(feedback_dir / "qe_fpga_deployment_dse_summary.json"),
            "validation_ref": _artifact_ref(feedback_dir / "qe_fpga_external_feedback_validation_report.json"),
        },
        "commands": {
            "seed_dse": seed_run,
            "l3_feedback": l3_run,
            "feedback_dse": feedback_run,
        },
        "artifact_refs": {
            "feedback_samples": _artifact_ref(feedback_samples_path),
            "seed_wamf_dse_report": seed_wamf_dse_ref,
            "seed_l2_request_bundle": _artifact_ref(seed_dir / "qe_fpga_l2_request_bundle.json"),
            "l3_validation_request_bundle": _artifact_ref(out_dir / "l3_validation_request_bundle.json"),
            "feedback_replay_manifest": _artifact_ref(feedback_dir / "qe_fpga_replay_manifest.json"),
        },
        "artifact_payload_hashes": {
            "seed_summary": _stable_payload_hash(seed_summary),
            "seed_wamf_dse_report": _stable_payload_hash(seed_wamf_dse),
            "seed_multi_workload_experiment_report": _stable_payload_hash(seed_multi_workload_experiment),
            "l3_feedback_report": _stable_payload_hash(l3_report),
            "feedback_summary": _stable_payload_hash(feedback_summary),
            "feedback_validation": _stable_payload_hash(feedback_validation),
        },
        "limitations": [
            "closed_loop_uses_generic_sim_timing_projection_not_qe_physics_correctness",
            "not_hls_vivado_or_bitstream_evidence",
            "DAC_grade_results_still_require_real_QE_corpus_and_hardware_tool_closure",
        ],
        "claim_boundary": "l3_feedback_closed_loop_experiment_only_not_final_hardware_result",
    }
    _write_json(out_dir / "qe_fpga_l3_feedback_closed_loop_report.json", report)
    paper_summary = _paper_ready_experiment_summary(
        report=report,
        seed_summary=seed_summary,
        seed_baseline=seed_baseline,
        neuromf_policy_evaluation_report=seed_neuromf_policy_evaluation,
        neuromf_policy_evaluation_ref=seed_neuromf_policy_evaluation_ref,
        seed_wamf_dse=seed_wamf_dse,
        seed_wamf_dse_ref=seed_wamf_dse_ref,
        seed_multi_workload_experiment=seed_multi_workload_experiment,
        seed_multi_workload_experiment_ref=seed_multi_workload_experiment_ref,
        seed_workflow_abstraction=seed_workflow_abstraction,
        seed_workflow_abstraction_ref=seed_workflow_abstraction_ref,
        feedback_validation=feedback_validation,
    )
    next_queue_path = out_dir / "qe_fpga_next_validation_gated_evaluation_queue.json"
    _write_json(next_queue_path, paper_summary["next_evaluation_queue"])
    paper_summary.setdefault("artifact_refs", {})["next_evaluation_queue"] = _artifact_ref(next_queue_path)
    _write_json(out_dir / "paper_ready_experiment_summary.json", paper_summary)
    return report


def _l3_validation_request_bundle(
    *,
    seed_dir: Path,
    holdout_count: int,
    max_promoted: int,
) -> Path:
    seed_bundle_path = seed_dir / "qe_fpga_l2_request_bundle.json"
    out_path = seed_dir.parent / "l3_validation_request_bundle.json"
    seed_bundle = _load_json_object(seed_bundle_path)
    promoted_requests = [
        dict(request)
        for request in seed_bundle.get("requests", []) or []
        if isinstance(request, Mapping)
    ]
    if int(max_promoted) > 0:
        promoted_requests = promoted_requests[: int(max_promoted)]
    for request in promoted_requests:
        request["selection_role"] = "promoted"
    holdout_requests = _holdout_l2_requests(seed_dir=seed_dir, promoted_requests=promoted_requests, holdout_count=int(holdout_count))
    requests = promoted_requests + holdout_requests
    bundle = dict(seed_bundle)
    bundle["schema_version"] = "dse.qe_fpga_l3_validation_request_bundle.v1"
    bundle["request_count"] = len(requests)
    bundle["requests"] = requests
    bundle["selection_role_counts"] = {
        "holdout": len(holdout_requests),
        "promoted": len(promoted_requests),
    }
    bundle["source_l2_request_bundle"] = _artifact_ref(seed_bundle_path)
    bundle["claim_boundary"] = "l3_validation_request_bundle_only_not_executed_or_hardware_evidence"
    _write_json(out_path, bundle)
    return out_path


def _holdout_l2_requests(
    *,
    seed_dir: Path,
    promoted_requests: Sequence[Mapping[str, Any]],
    holdout_count: int,
) -> List[Dict[str, Any]]:
    if holdout_count <= 0:
        return []
    manifest = _load_json_object(seed_dir / "qe_mainflow_workload_suite.json")
    problem = _load_json_object(seed_dir / "qe_fpga_search_problem.json")
    screening = _load_json_object(seed_dir / "qe_fpga_l1_screening_report.json")
    promoted_ids = {str(request.get("candidate_id", "")) for request in promoted_requests}
    holdout_rows = [
        row
        for row in screening.get("candidate_evaluations", []) or []
        if isinstance(row, Mapping)
        and str(row.get("candidate_id", "")) not in promoted_ids
        and row.get("promotion", {}).get("release_pareto_eligible") is True
    ]
    holdout_rows.sort(key=_holdout_sort_key)
    bundle = build_qe_fpga_l2_request_bundle(manifest, problem, holdout_rows[:holdout_count])
    requests = [
        dict(request)
        for request in bundle.get("requests", []) or []
        if isinstance(request, Mapping)
    ]
    for index, request in enumerate(requests):
        request["selection_role"] = "holdout"
        request["request_id"] = f"qe_fpga_l3_holdout_req_{index:03d}"
    return requests


def _holdout_sort_key(row: Mapping[str, Any]) -> tuple[float, float, str]:
    metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), Mapping) else {}
    return (
        -float(metrics.get("implementation_feasibility", 0.0) or 0.0),
        float(metrics.get("estimated_edp", float("inf")) or float("inf")),
        str(row.get("candidate_id", "")),
    )


def _workflow_input_summary(
    *,
    seed_dir: Path,
    seed_summary: Mapping[str, Any],
    workflow_bundle: Path | None,
    workflow_corpus: Path | None,
) -> Dict[str, Any]:
    if workflow_corpus is not None:
        corpus_report_path = seed_dir / "qe_fpga_workload_corpus_report.json"
        corpus_report = _load_json_object(corpus_report_path)
        coverage = corpus_report.get("coverage", {}) if isinstance(corpus_report.get("coverage"), Mapping) else {}
        return {
            "source_kind": "workflow_corpus",
            "path": str(workflow_corpus),
            "corpus_id": str(corpus_report.get("corpus_id", "")),
            "workload_count": int(corpus_report.get("workload_count", 0)),
            "primary_workload_id": str(corpus_report.get("primary_workload_id", "")),
            "coverage": {
                "workflow_classes": list(coverage.get("workflow_classes", []) or []),
                "max_dimensions": dict(coverage.get("max_dimensions", {}) or {}),
                "observed_runtime_workload_count": int(coverage.get("observed_runtime_workload_count", 0)),
                "measured_qe_ready_workload_count": int(coverage.get("measured_qe_ready_workload_count", 0)),
            },
            "measured_qe_corpus_readiness": dict(corpus_report.get("measured_qe_corpus_readiness", {}))
            if isinstance(corpus_report.get("measured_qe_corpus_readiness"), Mapping)
            else {},
            "corpus_report_ref": _artifact_ref(corpus_report_path),
            "limitation": "corpus_coverage_reports_input_diversity_not_true_representativeness_without_measured_QE_suite_curation",
        }
    if workflow_bundle is not None:
        bundle = seed_summary.get("input_workflow_bundle", {})
        return {
            "source_kind": "workflow_bundle",
            "path": str(workflow_bundle),
            "bundle_ref": dict(bundle) if isinstance(bundle, Mapping) else {},
            "limitation": "single_workflow_bundle_closed_loop_is_not_multi_workload_evidence",
        }
    return {
        "source_kind": "built_in_fixture",
        "suite_id": str(seed_summary.get("workload_suite_id", "")),
        "limitation": "built_in_fixture_closed_loop_is_pipeline_evidence_not_QE_corpus_result",
    }


def _paper_ready_experiment_summary(
    *,
    report: Mapping[str, Any],
    seed_summary: Mapping[str, Any],
    seed_baseline: Mapping[str, Any],
    neuromf_policy_evaluation_report: Mapping[str, Any],
    neuromf_policy_evaluation_ref: Mapping[str, Any],
    seed_wamf_dse: Mapping[str, Any],
    seed_wamf_dse_ref: Mapping[str, Any],
    seed_multi_workload_experiment: Mapping[str, Any],
    seed_multi_workload_experiment_ref: Mapping[str, Any],
    seed_workflow_abstraction: Mapping[str, Any] | None = None,
    seed_workflow_abstraction_ref: Mapping[str, Any] | None = None,
    feedback_validation: Mapping[str, Any],
) -> Dict[str, Any]:
    workflow_input = report.get("workflow_input", {}) if isinstance(report.get("workflow_input"), Mapping) else {}
    coverage = workflow_input.get("coverage", {}) if isinstance(workflow_input.get("coverage"), Mapping) else {}
    neuromf_report = (
        neuromf_policy_evaluation_report if isinstance(neuromf_policy_evaluation_report, Mapping) else {}
    )
    neuromf_summary = (
        seed_summary.get("neuromf_policy_evaluation", {})
        if isinstance(seed_summary.get("neuromf_policy_evaluation"), Mapping)
        else {}
    )
    policy_validation = (
        feedback_validation.get("policy_validation", {})
        if isinstance(feedback_validation.get("policy_validation"), Mapping)
        else {}
    )
    policy_rows = [
        {
            "policy_id": str(row.get("policy_id", "")),
            "feedback_overlap_count": int(row.get("feedback_overlap_count", 0)),
            "best_feedback_candidate_id": str(row.get("best_feedback_candidate_id", "")),
            "best_feedback_edp": row.get("best_feedback_edp"),
            "feedback_rank_of_best": row.get("feedback_rank_of_best"),
            "feedback_top_k_hit_at_5": bool(row.get("feedback_top_k_hit_at_5", False)),
        }
        for row in policy_validation.get("policies", []) or []
        if isinstance(row, Mapping)
    ]
    budget_sweep = (
        seed_baseline.get("budget_sweep", {})
        if isinstance(seed_baseline.get("budget_sweep"), Mapping)
        else {}
    )
    feature_ablation = (
        seed_baseline.get("feature_ablation_report", {})
        if isinstance(seed_baseline.get("feature_ablation_report"), Mapping)
        else {}
    )
    feedback_coverage_plan = (
        seed_baseline.get("independent_feedback_coverage_plan", {})
        if isinstance(seed_baseline.get("independent_feedback_coverage_plan"), Mapping)
        else {}
    )
    neuromf_paper_rows = _paper_neuromf_policy_rows(neuromf_report)
    workflow_abstractions = [
        seed_workflow_abstraction
        for seed_workflow_abstraction in [seed_workflow_abstraction]
        if isinstance(seed_workflow_abstraction, Mapping)
    ]
    if workflow_abstractions:
        independent_benchmark_suite = build_workflow_conditioned_multifidelity_benchmark_suite_report(
            workflow_abstractions=workflow_abstractions,
            candidate_count=max(64, int(seed_summary.get("candidate_count", 0) or 0)),
            budgets=(2, 4, 8),
            top_k=5,
            include_ablations=True,
        )
        independent_benchmark = dict(independent_benchmark_suite.get("scenario_reports", [{}])[0])
    else:
        independent_benchmark = build_multifidelity_search_benchmark_report(
            scenario_id="workflow_shift_resource_cliff",
            candidate_count=max(64, int(seed_summary.get("candidate_count", 0) or 0)),
            budgets=(2, 4, 8),
            top_k=5,
            include_ablations=True,
        )
        independent_benchmark_suite = build_multifidelity_search_benchmark_suite_report(
            scenario_ids=(
                "workflow_shift_resource_cliff",
                "host_control_heavy_shift",
                "data_residency_resource_cliff",
            ),
            candidate_count=max(64, int(seed_summary.get("candidate_count", 0) or 0)),
            budgets=(2, 4, 8),
            top_k=5,
            include_ablations=False,
        )
    independent_benchmark_rows = _paper_independent_algorithm_benchmark_rows(independent_benchmark)
    wamf_report = seed_wamf_dse if isinstance(seed_wamf_dse, Mapping) else {}
    wamf_summary = dict(wamf_report)
    wamf_summary["artifact"] = "qe_fpga_wamf_dse_report.json"
    wamf_summary["artifact_ref"] = dict(seed_wamf_dse_ref) if isinstance(seed_wamf_dse_ref, Mapping) else {}
    wamf_summary["next_evaluation_action_count"] = (
        int(wamf_report.get("next_evaluation_actions", {}).get("selected_action_count", 0))
        if isinstance(wamf_report.get("next_evaluation_actions"), Mapping)
        else 0
    )
    wamf_paper_rows = _paper_wamf_method_rows(wamf_report)
    multi_workload_report = (
        dict(seed_multi_workload_experiment)
        if isinstance(seed_multi_workload_experiment, Mapping)
        else {}
    )
    if multi_workload_report:
        multi_workload_report["artifact"] = "qe_fpga_multi_workload_experiment_report.json"
        multi_workload_report["artifact_ref"] = (
            dict(seed_multi_workload_experiment_ref)
            if isinstance(seed_multi_workload_experiment_ref, Mapping)
            else {}
        )
    baseline_budget_rows = _paper_baseline_budget_curve_rows(budget_sweep)
    l3_validation_metrics = dict(
        report.get("l3_feedback", {}).get("validation_metrics", {})
        if isinstance(report.get("l3_feedback"), Mapping)
        and isinstance(report.get("l3_feedback", {}).get("validation_metrics"), Mapping)
        else {}
    )
    algorithm_validation = build_multifidelity_algorithm_validation_report(
        proposed_policy_id="wamf_generic_active_pareto",
        policy_results=baseline_budget_rows,
        independent_feedback=l3_validation_metrics,
    )
    search_control = build_validation_gated_search_control_report(
        validation_report=algorithm_validation,
        candidates=_search_control_candidates_from_feedback_plan(feedback_coverage_plan),
        budget=max(1, int(seed_summary.get("promotion_count", 0) or 1)),
    )
    next_evaluation_queue = build_validation_gated_next_evaluation_queue(
        search_control=search_control,
        nominal_candidates=_search_control_candidates_from_feedback_plan(feedback_coverage_plan),
        budget=max(1, int(seed_summary.get("promotion_count", 0) or 1)),
        next_fidelity="L3_generic_sim_or_systemc",
    )
    wamf_method_name = str(wamf_summary.get("method_name", "WAMF-DSE"))
    neuromf_best_policy = (
        neuromf_report.get("best_policy_by_final_regret", {})
        if isinstance(neuromf_report.get("best_policy_by_final_regret"), Mapping)
        else {}
    )
    neuromf_aggregate = (
        neuromf_report.get("aggregate", {})
        if isinstance(neuromf_report.get("aggregate"), Mapping)
        else {}
    )
    return {
        "schema_version": "dse.qe_fpga_paper_ready_experiment_summary.v1",
        "status": "fixture_l3_closed_loop_complete_not_dac_final",
        "method_name": wamf_method_name,
        "method_full_name": str(wamf_summary.get("method_full_name", "")),
        "algorithm_family": str(wamf_summary.get("algorithm_family", "")),
        "experiment_method_name": str(report.get("method_name", "")),
        "workload_run_id": str(report.get("workload_run_id", "")),
        "neuromf_policy_evaluation": {
            "artifact": "qe_fpga_neuromf_policy_evaluation_report.json",
            "artifact_ref": dict(neuromf_policy_evaluation_ref) if isinstance(neuromf_policy_evaluation_ref, Mapping) else {},
            "policy_count": int(neuromf_report.get("policy_count", neuromf_summary.get("policy_count", 0))),
            "best_policy_id": str(
                neuromf_best_policy.get("policy_id", neuromf_summary.get("best_policy_id", ""))
            ),
            "best_policy_simple_regret": neuromf_best_policy.get(
                "simple_regret",
                neuromf_summary.get("best_policy_simple_regret"),
            ),
            "best_policy_oracle_rank": neuromf_best_policy.get(
                "oracle_rank_of_best",
                neuromf_summary.get("best_policy_oracle_rank"),
            ),
            "trained_neuromf_rank": neuromf_aggregate.get(
                "trained_neuromf_rank",
                neuromf_summary.get("trained_neuromf_rank"),
            ),
            "trained_neuromf_final_regret": neuromf_aggregate.get(
                "trained_neuromf_final_regret",
                neuromf_summary.get("trained_neuromf_final_regret"),
            ),
            "policy_ids_ranked_by_final_regret": list(
                neuromf_aggregate.get(
                    "policy_ids_ranked_by_final_regret",
                    neuromf_summary.get("policy_ids_ranked_by_final_regret", []),
                )
                or []
            ),
            "claim_boundary": str(
                neuromf_report.get("claim_boundary", neuromf_summary.get("claim_boundary", ""))
            ),
        },
        "independent_algorithm_benchmark": {
            "schema_version": str(independent_benchmark.get("schema_version", "")),
            "scenario_id": str(independent_benchmark.get("scenario_id", "")),
            "oracle_kind": str(
                independent_benchmark.get("oracle", {}).get("oracle_kind", "")
                if isinstance(independent_benchmark.get("oracle"), Mapping)
                else ""
            ),
            "oracle_pareto_frontier_size": int(
                independent_benchmark.get("oracle", {}).get("pareto_frontier_size", 0)
                if isinstance(independent_benchmark.get("oracle"), Mapping)
                else 0
            ),
            "oracle_reference_hypervolume": (
                independent_benchmark.get("oracle", {}).get("reference_hypervolume")
                if isinstance(independent_benchmark.get("oracle"), Mapping)
                else None
            ),
            "best_policy_id": _best_independent_benchmark_policy(independent_benchmark).get("policy_id", ""),
            "best_policy_simple_regret": _best_independent_benchmark_policy(independent_benchmark).get(
                "final_simple_regret"
            ),
            "workflow_conditioning": dict(
                independent_benchmark.get("workflow_conditioning", {})
                if isinstance(independent_benchmark.get("workflow_conditioning"), Mapping)
                else {}
            ),
            "workflow_abstraction_ref": dict(seed_workflow_abstraction_ref)
            if isinstance(seed_workflow_abstraction_ref, Mapping)
            else {},
            "claim_boundary": "algorithm_method_validation_not_hardware_evidence",
        },
        "independent_algorithm_benchmark_suite": {
            "schema_version": str(independent_benchmark_suite.get("schema_version", "")),
            "conditioning_source": str(independent_benchmark_suite.get("conditioning_source", "")),
            "workflow_ids": list(independent_benchmark_suite.get("workflow_ids", []) or []),
            "scenario_ids": list(independent_benchmark_suite.get("scenario_ids", []) or []),
            "scenario_count": int(independent_benchmark_suite.get("scenario_count", 0)),
            "budgets": list(independent_benchmark_suite.get("budgets", []) or []),
            "final_budget": int(independent_benchmark_suite.get("final_budget", 0)),
            "policy_statistics": list(independent_benchmark_suite.get("policy_statistics", []) or []),
            "best_policy_by_mean_regret": dict(
                independent_benchmark_suite.get("best_policy_by_mean_regret", {})
                if isinstance(independent_benchmark_suite.get("best_policy_by_mean_regret"), Mapping)
                else {}
            ),
            "claim_boundary": "algorithm_robustness_validation_not_hardware_evidence",
        },
        "workload_corpus": {
            "source_kind": str(workflow_input.get("source_kind", "")),
            "corpus_id": str(workflow_input.get("corpus_id", workflow_input.get("suite_id", ""))),
            "workload_count": int(workflow_input.get("workload_count", 0)),
            "workflow_classes": list(coverage.get("workflow_classes", []) or []),
            "max_dimensions": dict(coverage.get("max_dimensions", {}) or {}),
            "observed_runtime_workload_count": int(coverage.get("observed_runtime_workload_count", 0)),
            "measured_qe_ready_workload_count": int(coverage.get("measured_qe_ready_workload_count", 0)),
            "measured_qe_corpus_readiness": dict(workflow_input.get("measured_qe_corpus_readiness", {}))
            if isinstance(workflow_input.get("measured_qe_corpus_readiness"), Mapping)
            else {},
        },
        "search": {
            "candidate_count": int(seed_summary.get("candidate_count", 0)),
            "pareto_candidate_count": int(seed_summary.get("pareto_candidate_count", 0)),
            "promotion_count": int(seed_summary.get("promotion_count", 0)),
            "implementation_package_count": int(seed_summary.get("implementation_package_count", 0)),
        },
        "wamf_dse": wamf_summary,
        "multi_workload_experiment": multi_workload_report,
        "l3_feedback": dict(report.get("l3_feedback", {}) if isinstance(report.get("l3_feedback"), Mapping) else {}),
        "l3_validation_metrics": l3_validation_metrics,
        "algorithm_validation": algorithm_validation,
        "search_control": search_control,
        "next_evaluation_queue": next_evaluation_queue,
        "artifact_refs": {},
        "policy_validation": {
            "status": str(policy_validation.get("status", "")),
            "feedback_fidelity": str(policy_validation.get("feedback_fidelity", "")),
            "feedback_candidate_count": int(policy_validation.get("feedback_candidate_count", 0)),
            "best_policy_by_feedback": dict(
                policy_validation.get("best_policy_by_feedback", {})
                if isinstance(policy_validation.get("best_policy_by_feedback"), Mapping)
                else {}
            ),
        },
        "search_quality": {
            "baseline_oracle_fidelity": str(seed_baseline.get("oracle_fidelity", "")),
            "budget_sweep": {
                "oracle_fidelity": str(budget_sweep.get("oracle_fidelity", "")),
                "budgets": list(budget_sweep.get("budgets", []) or []),
                "random_seed_count": int(budget_sweep.get("random_seed_count", 0)),
                "final_budget_policy_order": list(budget_sweep.get("final_budget_policy_order", []) or []),
            },
            "feature_ablation": {
                "oracle_fidelity": str(feature_ablation.get("oracle_fidelity", "")),
                "evaluation_budget": int(feature_ablation.get("evaluation_budget", 0)),
                "ablation_count": int(feature_ablation.get("ablation_count", 0)),
            },
            "independent_feedback_coverage_plan": {
                "schema_version": str(feedback_coverage_plan.get("schema_version", "")),
                "candidate_count": int(feedback_coverage_plan.get("candidate_count", 0)),
                "minimum_recommended_feedback_count": int(
                    feedback_coverage_plan.get("minimum_recommended_feedback_count", 0)
                ),
                "policy_count": int(feedback_coverage_plan.get("policy_count", 0)),
                "promoted_candidate_count": int(feedback_coverage_plan.get("promoted_candidate_count", 0)),
                "holdout_candidate_count": int(feedback_coverage_plan.get("holdout_candidate_count", 0)),
                "claim_boundary": str(feedback_coverage_plan.get("claim_boundary", "")),
            },
            "limitations": [
                "baseline_and_ablation_rows_use_L2_python_tlm_oracle",
                "closed_loop_L3_feedback_only_covers_sampled_candidates",
                "paper_ready_search_quality_is_fixture_experiment_evidence_not_final_DAC_result",
            ],
        },
        "paper_table_rows": {
            "workloads": _paper_workload_rows(workflow_input),
            "wamf_dse": wamf_paper_rows,
            "next_evaluation_actions": _paper_next_evaluation_action_rows(wamf_report),
            "policy_validation": policy_rows,
            "neuromf_policy_evaluation": neuromf_paper_rows,
            "independent_algorithm_benchmark": independent_benchmark_rows,
            "baseline_budget_curves": baseline_budget_rows,
            "feature_ablations": _paper_feature_ablation_rows(feature_ablation),
            "method_component_ablations": _paper_method_component_ablation_rows(
                budget_sweep,
                neuromf_report=neuromf_report,
                wamf_report=wamf_report,
            ),
            "wamf_required_ablations": _paper_wamf_required_ablation_rows(wamf_report),
        },
        "limitations": [
            "fixture_corpus_not_measured_QE_benchmark_suite",
            "generic_sim_feedback_not_QE_correctness_or_hardware_timing",
            "HLS_Vivado_bitstream_results_still_missing",
        ],
        "claim_boundary": "paper_ready_summary_for_fixture_experiment_only_not_DAC_final_result",
    }


def _paper_next_evaluation_action_rows(wamf_report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    next_actions = (
        wamf_report.get("next_evaluation_actions", {})
        if isinstance(wamf_report.get("next_evaluation_actions"), Mapping)
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


def _paper_neuromf_policy_rows(neuromf_report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    policies = [
        row for row in neuromf_report.get("policies", []) or []
        if isinstance(row, Mapping)
    ]
    aggregate = neuromf_report.get("aggregate", {}) if isinstance(neuromf_report.get("aggregate"), Mapping) else {}
    rows: List[Dict[str, Any]] = []
    for policy_row in policies:
        policy_id = str(policy_row.get("policy_id", ""))
        budget_curve = policy_row.get("budget_curve", []) if isinstance(policy_row.get("budget_curve"), list) else []
        final = budget_curve[-1] if budget_curve else {}
        is_trained = policy_id == "neuromf_trained_surrogate"
        closed_loop_trace = (
            policy_row.get("closed_loop_feedback_trace", [])
            if isinstance(policy_row.get("closed_loop_feedback_trace"), list)
            else []
        )
        selection_basis = (
            policy_row.get("selection_basis", {})
            if isinstance(policy_row.get("selection_basis"), Mapping)
            else {}
        )
        rows.append({
            "policy_id": policy_id,
            "final_budget": int(final.get("budget", 0)) if final else 0,
            "final_best_edp": final.get("best_tlm_edp", final.get("best_tlm_edp_mean")),
            "final_oracle_rank": final.get("oracle_rank_of_best", final.get("oracle_rank_of_best_mean")),
            "trained_neuromf_rank": aggregate.get("trained_neuromf_rank") if is_trained else None,
            "trained_neuromf_final_regret": aggregate.get("trained_neuromf_final_regret") if is_trained else None,
            "closed_loop_feedback": bool(selection_basis.get("closed_loop_feedback", False)),
            "feedback_observation_count": int(selection_basis.get("feedback_observation_count", 0) or 0),
            "external_feedback_common_objective_count": int(
                selection_basis.get("external_feedback_common_objective_count", 0) or 0
            ),
            "initial_external_feedback_observation_count": int(
                selection_basis.get("initial_external_feedback_observation_count", 0) or 0
            ),
            "final_selection_frontier_source": str(final.get("selection_frontier_source", "")),
            "closed_loop_trace_count": len(closed_loop_trace),
        })
    return rows


def _paper_wamf_required_ablation_rows(wamf_report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    ablations = (
        wamf_report.get("ablations", {}).get("required_ablations", [])
        if isinstance(wamf_report.get("ablations"), Mapping)
        else []
    )
    rows: List[Dict[str, Any]] = []
    for row in ablations:
        if not isinstance(row, Mapping):
            continue
        evaluation = (
            row.get("evaluation", {})
            if isinstance(row.get("evaluation"), Mapping)
            else {}
        )
        selection_basis = (
            row.get("selection_basis", {})
            if isinstance(row.get("selection_basis"), Mapping)
            else {}
        )
        sample_efficiency = (
            row.get("sample_efficiency", {})
            if isinstance(row.get("sample_efficiency"), Mapping)
            else {}
        )
        algorithm_contract = (
            row.get("algorithm_contract", {})
            if isinstance(row.get("algorithm_contract"), Mapping)
            else {}
        )
        comparison_to_method = (
            row.get("comparison_to_method", {})
            if isinstance(row.get("comparison_to_method"), Mapping)
            else {}
        )
        rows.append({
            "ablation_id": str(row.get("ablation_id", "")),
            "maps_to": str(row.get("maps_to", "")),
            "status": str(row.get("status", "")),
            "removed_component": str(selection_basis.get("ablation_removes", "")),
            "algorithm_contract": dict(algorithm_contract),
            "removed_components": list(algorithm_contract.get("removed_components", []) or []),
            "uses_workflow_abstraction": bool(algorithm_contract.get("uses_workflow_abstraction", False)),
            "uses_multi_fidelity_feedback": bool(algorithm_contract.get("uses_multi_fidelity_feedback", False)),
            "uses_active_pareto_selection": bool(algorithm_contract.get("uses_active_pareto_selection", False)),
            "same_candidate_pool_as_method": bool(algorithm_contract.get("same_candidate_pool_as_method", False)),
            "same_evaluation_budget_as_method": bool(algorithm_contract.get("same_evaluation_budget_as_method", False)),
            "retrospective_oracle_only": bool(algorithm_contract.get("retrospective_oracle_only", False)),
            "oracle_fidelity": str(evaluation.get("oracle_fidelity", "")),
            "final_budget": int(evaluation.get("final_budget", 0) or 0),
            "final_best_edp": _finite_float(evaluation.get("final_best_edp"), default=0.0),
            "final_oracle_rank": int(_finite_float(evaluation.get("final_oracle_rank"), default=0.0) or 0),
            "final_simple_regret": _finite_float(evaluation.get("final_simple_regret"), default=0.0),
            "top_k_hit": bool(evaluation.get("top_k_hit", False)),
            "method_policy_id": str(comparison_to_method.get("method_policy_id", "")),
            "same_budget_vs_method": bool(comparison_to_method.get("same_budget", False)),
            "edp_ratio_vs_method": comparison_to_method.get("edp_ratio_vs_method"),
            "rank_delta_vs_method": comparison_to_method.get("rank_delta_vs_method"),
            "regret_delta_vs_method": comparison_to_method.get("regret_delta_vs_method"),
            "evaluations_to_top_5_hit": sample_efficiency.get("evaluations_to_top_5_hit"),
        })
    return rows


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


def _paper_independent_algorithm_benchmark_rows(benchmark: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for policy in benchmark.get("policies", []) or []:
        if not isinstance(policy, Mapping):
            continue
        curve = policy.get("budget_curve", []) if isinstance(policy.get("budget_curve"), list) else []
        final = curve[-1] if curve else {}
        rows.append({
            "policy_id": str(policy.get("policy_id", "")),
            "final_budget": int(final.get("budget", 0)) if final else 0,
            "final_simple_regret": final.get("simple_regret"),
            "final_oracle_rank": final.get("oracle_rank_of_best"),
            "top_k_hit": bool(final.get("top_k_hit", False)),
            "final_hypervolume_ratio": final.get("hypervolume_ratio"),
            "final_feasibility_weighted_hv_ratio": final.get("feasibility_weighted_hv_ratio"),
            "final_cost_normalized_hv_gain": final.get("cost_normalized_hv_gain_at_budget"),
            "final_pareto_coverage": final.get("oracle_pareto_coverage_at_budget"),
            "selected_pareto_hit_count": int(final.get("selected_pareto_hit_count", 0) or 0),
            "selection_model": str(policy.get("selection_model", "")),
            "uses_oracle_during_selection": bool(policy.get("uses_oracle_during_selection", False)),
        })
    return rows


def _best_independent_benchmark_policy(benchmark: Mapping[str, Any]) -> Dict[str, Any]:
    rows = _paper_independent_algorithm_benchmark_rows(benchmark)
    if not rows:
        return {}
    return min(
        rows,
        key=lambda row: (
            _finite_positive(row.get("final_simple_regret"), default=float("inf")),
            _finite_positive(row.get("final_oracle_rank"), default=float("inf")),
            str(row.get("policy_id", "")),
        ),
    )


def _paper_wamf_method_rows(wamf_report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    wamf = dict(wamf_report if isinstance(wamf_report, Mapping) else {})
    if "schema_version" not in wamf and isinstance(wamf.get("wamf_dse"), Mapping):
        wamf = dict(wamf.get("wamf_dse", {}))
    model_stack = dict(wamf.get("model_stack", {}) if isinstance(wamf.get("model_stack"), Mapping) else {})
    pareto = dict(wamf.get("pareto_candidates", {}) if isinstance(wamf.get("pareto_candidates"), Mapping) else {})
    baselines = dict(wamf.get("baselines", {}) if isinstance(wamf.get("baselines"), Mapping) else {})
    selected = dict(wamf.get("selected_final_candidates", {}) if isinstance(wamf.get("selected_final_candidates"), Mapping) else {})
    method_kernel = (
        dict(baselines.get("method_kernel_policy", {}))
        if isinstance(baselines.get("method_kernel_policy"), Mapping)
        else {}
    )
    policy_rows = [
        row for row in baselines.get("policies", []) or []
        if isinstance(row, Mapping)
    ]
    rows: List[Dict[str, Any]] = []
    for key, label in [
        ("selected_final_candidates", "WAMF-selected"),
        ("wamf_generic_active_pareto", "WAMF-kernel"),
        ("workflow_aware_pareto_funnel", "Workflow-aware prior"),
        ("neuromf_trained_surrogate", "Neural surrogate"),
    ]:
        if key == "selected_final_candidates":
            candidate_count = int(selected.get("candidate_count", 0))
            best_rank = (
                int(selected.get("candidates", [{}])[0].get("metrics", {}).get("oracle_rank", 0))
                if selected.get("candidates")
                else 0
            )
            best_edp = (
                selected.get("candidates", [{}])[0].get("metrics", {}).get("energy_edp")
                if selected.get("candidates")
                else None
            )
            row = {
                "policy_id": key,
                "label": label,
                "final_budget": int(wamf.get("problem_formulation", {}).get("expensive_evaluation_budget", 0)),
                "final_best_edp": best_edp,
                "final_oracle_rank": best_rank if best_rank > 0 else None,
                "selected_candidate_count": candidate_count,
                "method_name": str(wamf.get("method_name", "")),
                "component_role": "active_pareto_selection",
                "surrogate_backend": str(model_stack.get("surrogate", {}).get("backend", "")) if isinstance(model_stack.get("surrogate"), Mapping) else "",
                "pareto_frontier_count": int(pareto.get("frontier_count", 0)),
            }
        elif key == "wamf_generic_active_pareto":
            method_rows = [
                row for row in policy_rows
                if str(row.get("policy_id", "")) == "wamf_generic_active_pareto"
            ]
            method_row = method_rows[0] if method_rows else {}
            final = method_row.get("budget_curve", [])[-1] if method_row.get("budget_curve") else {}
            selection_basis = (
                method_row.get("selection_basis", {})
                if isinstance(method_row.get("selection_basis"), Mapping)
                else {}
            )
            row = {
                "policy_id": str(method_kernel.get("policy_id", key)) or key,
                "label": label,
                "final_budget": int(final.get("budget", 0)) if final else 0,
                "final_best_edp": final.get("best_tlm_edp", final.get("best_tlm_edp_mean")),
                "final_oracle_rank": final.get("oracle_rank_of_best", final.get("oracle_rank_of_best_mean")),
                "selected_candidate_count": int(method_kernel.get("selected_count", len(method_rows))),
                "method_name": str(wamf.get("method_name", "WAMF-DSE")),
                "component_role": "domain_neutral_active_pareto_kernel",
                "surrogate_backend": str(model_stack.get("surrogate", {}).get("backend", "")) if isinstance(model_stack.get("surrogate"), Mapping) else "",
                "pareto_frontier_count": int(pareto.get("frontier_count", 0)),
                "generic_kernel_policy": str(method_kernel.get("generic_kernel_policy", "")),
                "final_simple_regret": method_kernel.get("final_simple_regret"),
                "top_k_hit": method_kernel.get("top_k_hit"),
                "evidence_boundary": str(method_kernel.get("evidence_boundary", "")),
                "closed_loop_feedback": bool(selection_basis.get("closed_loop_feedback", False)),
                "feedback_observation_count": int(selection_basis.get("feedback_observation_count", 0) or 0),
                "external_feedback_common_objective_count": int(
                    selection_basis.get("external_feedback_common_objective_count", 0) or 0
                ),
                "initial_external_feedback_observation_count": int(
                    selection_basis.get("initial_external_feedback_observation_count", 0) or 0
                ),
                "final_selection_frontier_source": str(final.get("selection_frontier_source", "")),
            }
        elif key == "workflow_aware_pareto_funnel":
            baseline_rows = [
                row for row in policy_rows
                if str(row.get("policy_id", "")) == "workflow_aware_pareto_funnel"
            ]
            final = baseline_rows[0].get("budget_curve", [])[-1] if baseline_rows and baseline_rows[0].get("budget_curve") else {}
            row = {
                "policy_id": key,
                "label": label,
                "final_budget": int(final.get("budget", 0)) if final else 0,
                "final_best_edp": final.get("best_tlm_edp", final.get("best_tlm_edp_mean")),
                "final_oracle_rank": final.get("oracle_rank_of_best", final.get("oracle_rank_of_best_mean")),
                "selected_candidate_count": len(baseline_rows),
                "method_name": str(wamf.get("method_name", "WAMF-DSE")),
                "component_role": "l1_workflow_prior_baseline",
                "surrogate_backend": "",
                "pareto_frontier_count": int(pareto.get("frontier_count", 0)),
            }
        else:
            neuromf_rows = [
                row for row in policy_rows
                if str(row.get("policy_id", "")) == "neuromf_trained_surrogate"
            ]
            final = neuromf_rows[0].get("budget_curve", [])[-1] if neuromf_rows and neuromf_rows[0].get("budget_curve") else {}
            row = {
                "policy_id": key,
                "label": label,
                "final_budget": int(final.get("budget", 0)) if final else 0,
                "final_best_edp": final.get("best_tlm_edp", final.get("best_tlm_edp_mean")),
                "final_oracle_rank": final.get("oracle_rank_of_best", final.get("oracle_rank_of_best_mean")),
                "selected_candidate_count": len(neuromf_rows),
                "method_name": str(wamf.get("method_name", "WAMF-DSE")),
                "component_role": "surrogate_policy_baseline",
                "surrogate_backend": str(model_stack.get("surrogate", {}).get("backend", "")) if isinstance(model_stack.get("surrogate"), Mapping) else "",
                "pareto_frontier_count": int(pareto.get("frontier_count", 0)),
            }
        rows.append(row)
    return rows


def _paper_baseline_budget_curve_rows(budget_sweep: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for curve in budget_sweep.get("policy_curves", []) or []:
        if not isinstance(curve, Mapping):
            continue
        points = [point for point in curve.get("points", []) or [] if isinstance(point, Mapping)]
        final = points[-1] if points else {}
        rows.append({
            "policy_id": str(curve.get("policy_id", "")),
            "point_count": len(points),
            "final_budget": int(final.get("budget", 0)) if final else 0,
            "final_best_edp": final.get("best_tlm_edp", final.get("best_tlm_edp_mean")),
            "final_best_edp_std": final.get("best_tlm_edp_std"),
            "final_oracle_rank": final.get("oracle_rank_of_best", final.get("oracle_rank_of_best_mean")),
            "random_seed_count": final.get("random_seed_count"),
        })
    return rows


def _paper_method_component_ablation_rows(
    budget_sweep: Mapping[str, Any],
    *,
    neuromf_report: Mapping[str, Any] | None = None,
    wamf_report: Mapping[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    baseline_rows = _paper_baseline_budget_curve_rows(budget_sweep)
    neuromf_rows = _paper_neuromf_policy_rows(neuromf_report or {})
    by_policy = {str(row.get("policy_id", "")): row for row in baseline_rows}
    by_policy.update({
        str(row.get("policy_id", "")): row
        for row in neuromf_rows
        if str(row.get("policy_id", ""))
    })
    wamf_baselines = (
        wamf_report.get("baselines", {})
        if isinstance(wamf_report, Mapping) and isinstance(wamf_report.get("baselines"), Mapping)
        else {}
    )
    method_kernel = (
        wamf_baselines.get("method_kernel_policy", {})
        if isinstance(wamf_baselines.get("method_kernel_policy"), Mapping)
        else {}
    )
    method_policy_id = str(method_kernel.get("policy_id", "wamf_generic_active_pareto")) or "wamf_generic_active_pareto"
    full = by_policy.get(method_policy_id, {})
    full_edp = _finite_positive(full.get("final_best_edp"), default=0.0)
    components = [
        {
            "component_id": "full_method",
            "policy_id": method_policy_id,
            "removed_component": "none",
            "method_kernel_policy": str(method_kernel.get("generic_kernel_policy", "")),
        },
        {
            "component_id": "no_multifidelity_feedback",
            "policy_id": "single_fidelity_l1_edp",
            "removed_component": "multi_fidelity_feedback",
        },
        {
            "component_id": "no_pareto_active_selection",
            "policy_id": "random_seeded_multi_seed",
            "removed_component": "pareto_active_selection",
        },
        {
            "component_id": "kernel_only_search",
            "policy_id": "kernel_level_hotspot_only",
            "removed_component": "workflow_abstraction",
        },
        {
            "component_id": "manual_heuristic",
            "policy_id": "manual_hbm_streaming_heuristic",
            "removed_component": "learned_or_pareto_search",
        },
        {
            "component_id": "nsga2_lite",
            "policy_id": "nsga2_lite_multi_objective",
            "removed_component": "workflow_risk_active_selection",
        },
    ]
    rows: List[Dict[str, Any]] = []
    for component in components:
        policy = by_policy.get(component["policy_id"], {})
        best_edp = _finite_positive(policy.get("final_best_edp"), default=0.0)
        rows.append({
            **component,
            "final_budget": int(policy.get("final_budget", 0) or 0),
            "final_best_edp": policy.get("final_best_edp"),
            "final_oracle_rank": policy.get("final_oracle_rank"),
            "edp_ratio_vs_full": (
                round(best_edp / full_edp, 9)
                if full_edp > 0.0 and best_edp > 0.0
                else None
            ),
            "comparison_basis": "final_budget_L2_python_tlm_oracle_row",
        })
    return rows


def _finite_positive(value: Any, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) and result > 0.0 else default


def _paper_feature_ablation_rows(feature_ablation: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for ablation in feature_ablation.get("ablations", []) or []:
        if not isinstance(ablation, Mapping):
            continue
        oracle = ablation.get("l2_oracle", {}) if isinstance(ablation.get("l2_oracle"), Mapping) else {}
        comparison = (
            ablation.get("comparison_to_full", {})
            if isinstance(ablation.get("comparison_to_full"), Mapping)
            else {}
        )
        rows.append({
            "ablation_id": str(ablation.get("ablation_id", "")),
            "removed_feature_groups": list(ablation.get("removed_feature_groups", []) or []),
            "selected_count": int(ablation.get("selected_count", 0)),
            "best_candidate_id": str(oracle.get("best_candidate_id", "")),
            "best_tlm_edp": oracle.get("best_tlm_edp"),
            "oracle_rank_of_best": oracle.get("oracle_rank_of_best_selected"),
            "mean_oracle_rank": oracle.get("mean_oracle_rank_of_selected"),
            "comparison_to_full": {
                "decision_changed": bool(comparison.get("decision_changed", False)),
                "candidate_overlap_with_full": comparison.get("candidate_overlap_with_full"),
                "candidate_jaccard_with_full": comparison.get("candidate_jaccard_with_full"),
                "rank_delta_vs_full": comparison.get("rank_delta_vs_full"),
                "best_edp_ratio_vs_full": comparison.get("best_edp_ratio_vs_full"),
            },
        })
    return rows


def _paper_workload_rows(workflow_input: Mapping[str, Any]) -> List[Dict[str, Any]]:
    corpus_ref = workflow_input.get("corpus_report_ref", {})
    if not isinstance(corpus_ref, Mapping) or not corpus_ref.get("path"):
        return []
    try:
        corpus_report = _load_json_object(Path(str(corpus_ref["path"])))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return []
    rows: List[Dict[str, Any]] = []
    for row in corpus_report.get("workloads", []) or []:
        if not isinstance(row, Mapping):
            continue
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), Mapping) else {}
        rows.append({
            "workload_id": str(row.get("workload_id", "")),
            "material": str(row.get("material") or metadata.get("material", "")),
            "size_class": str(row.get("size_class") or metadata.get("size_class", "")),
            "workflow_classes": list(
                row.get("workflow_roles")
                or metadata.get("workflow_roles", [])
                or row.get("workflow_classes", [])
                or []
            ),
            "stage_count": int(row.get("stage_count", 0)),
            "observed_runtime": bool(row.get("observed_runtime", False)),
        })
    return rows


def _failure_report(
    *,
    args: argparse.Namespace,
    stage: str,
    command_result: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": "dse.qe_fpga_l3_feedback_closed_loop_report.v1",
        "status": "failed",
        "method_name": "QEFPGA_L3_GenericSimFeedbackClosedLoop",
        "workload_run_id": str(args.workload_run_id),
        "failed_stage": stage,
        "commands": {stage: dict(command_result)},
        "limitations": [
            "closed_loop_uses_generic_sim_timing_projection_not_qe_physics_correctness",
            "not_hls_vivado_or_bitstream_evidence",
            "DAC_grade_results_still_require_real_QE_corpus_and_hardware_tool_closure",
        ],
        "claim_boundary": "l3_feedback_closed_loop_experiment_only_not_final_hardware_result",
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = run_closed_loop(args)
    print(json.dumps({
        "status": report["status"],
        "out": str(args.out),
        "seed_promotions": report.get("seed_dse", {}).get("promotion_count", 0),
        "l3_feedback_samples": report.get("l3_feedback", {}).get("feedback_sample_count", 0),
        "policy_validation_status": report.get("feedback_dse", {}).get("policy_validation_status", ""),
    }, sort_keys=True))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
