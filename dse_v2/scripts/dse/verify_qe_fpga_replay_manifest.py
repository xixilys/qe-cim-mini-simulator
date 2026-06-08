#!/usr/bin/env python3
"""Verify QE FPGA DSE replay manifest artifact hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping


REPLAY_MANIFEST_NAME = "qe_fpga_replay_manifest.json"

ARTIFACT_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "qe_mainflow_workload_suite.json": {
        "schema_version": "dse.qe_mainflow_workload_suite_manifest.v1",
        "required_fields": ["suite_id", "cases", "required_mainflow_classes", "claim_boundary"],
    },
    "qe_workflow_fpga_abstraction.json": {
        "schema_version": "dse.qe_workflow_fpga_abstraction.v1",
        "required_fields": ["workload_id", "source", "graph", "features", "data_objects", "source_facts", "claim_boundary"],
    },
    "qe_fpga_search_problem.json": {
        "required_fields": ["problem_id", "workload_run_id", "parameters", "constraints", "objective"],
    },
    "qe_fpga_step2_candidates.json": {
        "schema_version": "dse.qe_fpga_step2_candidate_queue.v1",
        "required_fields": ["candidate_count", "candidate_budget", "candidates", "candidate_ids", "claim_boundary"],
    },
    "qe_fpga_l1_screening_report.json": {
        "schema_version": "dse.qe_fpga_deployment_l1_screening.v1",
        "required_fields": ["method_name", "candidate_count", "candidate_evaluations", "pareto_frontier", "promotion_queue", "claim_boundary"],
    },
    "qe_fpga_promotion_queue.json": {
        "schema_version": "dse.qe_fpga_l1_promotion_queue.v1",
        "required_fields": ["method_name", "promotion_count", "promotion_queue", "claim_boundary"],
    },
    "qe_fpga_l2_request_bundle.json": {
        "schema_version": "dse.qe_fpga_l2_request_bundle.v1",
        "required_fields": ["request_count", "requests", "claim_boundary"],
    },
    "qe_fpga_l2_tlm_results.json": {
        "schema_version": "dse.qe_fpga_l2_tlm_results.v1",
        "required_fields": ["executed_count", "results", "claim_boundary"],
    },
    "qe_fpga_l3_generic_sim_feedback.json": {
        "schema_version": "dse.qe_fpga_l3_generic_sim_feedback.v1",
        "required_fields": ["status", "request_count", "executed_count", "feedback_sample_count", "results", "claim_boundary"],
    },
    "qe_fpga_l1_l2_calibration_report.json": {
        "schema_version": "dse.qe_fpga_l1_l2_calibration.v1",
        "required_fields": ["sample_count", "calibration_status", "claim_boundary"],
    },
    "qe_fpga_adaptive_multifidelity_search_report.json": {
        "schema_version": "dse.qe_fpga_adaptive_multifidelity_search_report.v1",
        "required_fields": ["method_name", "evaluated_count", "evaluation_trace", "budget_curve", "final_result", "claim_boundary"],
    },
    "qe_fpga_neural_multifidelity_search_report.json": {
        "schema_version": "dse.qe_fpga_neural_multifidelity_search_report.v1",
        "required_fields": [
            "method_name",
            "execution_mode",
            "fidelity_sequence",
            "neural_method_contract",
            "feature_schema",
            "surrogate_model",
            "evaluated_count",
            "evaluation_trace",
            "budget_curve",
            "final_result",
            "claim_boundary",
        ],
    },
    "qe_fpga_neural_surrogate_training_report.json": {
        "schema_version": "dse.qe_fpga_neural_surrogate_training_report.v1",
        "required_fields": [
            "method_name",
            "training_status",
            "backend",
            "dataset",
            "splits",
            "feature_schema",
            "normalizer",
            "checkpoint",
            "metrics",
            "uncertainty",
            "inference_preview",
            "claim_boundary",
        ],
    },
    "qe_fpga_neuromf_policy_evaluation_report.json": {
        "schema_version": "dse.qe_fpga_neuromf_policy_evaluation_report.v1",
        "required_fields": [
            "method_name",
            "oracle_fidelity",
            "evaluation_budget",
            "policy_count",
            "policies",
            "best_policy_by_final_regret",
            "aggregate",
            "limitations",
            "claim_boundary",
        ],
    },
    "qe_fpga_wamf_dse_report.json": {
        "schema_version": "dse.qe_fpga_wamf_dse_report.v1",
        "required_fields": [
            "method_name",
            "method_full_name",
            "algorithm_family",
            "problem_formulation",
            "workflow_abstraction",
            "deployment_search_space",
            "model_stack",
            "active_pareto_acquisition",
            "pareto_candidates",
            "selected_final_candidates",
            "baselines",
            "ablations",
            "hardware_generation_path",
            "claim_boundary",
        ],
    },
    "qe_fpga_search_baseline_report.json": {
        "schema_version": "dse.qe_fpga_search_baseline_report.v1",
        "required_fields": ["policy_count", "policies", "claim_boundary"],
    },
    "qe_fpga_multi_workload_experiment_report.json": {
        "schema_version": "dse.qe_fpga_multi_workload_experiment_report.v1",
        "required_fields": ["workload_count", "policy_ids", "claim_boundary"],
    },
    "qe_fpga_workload_corpus_report.json": {
        "schema_version": "dse.qe_fpga_workload_corpus_report.v1",
        "required_fields": ["corpus_id", "primary_workload_id", "workload_count", "coverage", "workloads", "claim_boundary"],
    },
    "qe_fpga_implementation_package_plan.json": {
        "schema_version": "dse.qe_fpga_implementation_package_plan.v1",
        "required_fields": ["package_count", "packages", "claim_boundary"],
    },
    "qe_fpga_implementation_package_materialization.json": {
        "schema_version": "dse.qe_fpga_implementation_package_materialization.v1",
        "required_fields": ["status", "package_count", "packages", "claim_boundary"],
    },
    "qe_fpga_external_feedback_validation_report.json": {
        "schema_version": "dse.qe_fpga_external_feedback_validation_report.v1",
        "required_fields": ["status", "feedback_sample_count", "samples", "policy_validation", "claim_boundary"],
    },
    "qe_fpga_deployment_dse_summary.json": {
        "schema_version": "dse.qe_fpga_deployment_dse_summary.v1",
        "required_fields": ["method_name", "prototype_status", "candidate_count", "artifact_hashes", "claim_boundary"],
    },
    REPLAY_MANIFEST_NAME: {
        "schema_version": "dse.qe_fpga_replay_manifest.v1",
        "required_fields": ["method_name", "command", "environment", "input_refs", "artifact_byte_hashes", "artifact_payload_hashes", "claim_boundary"],
    },
}


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True, help="QE FPGA DSE run directory")
    return parser.parse_args(argv)


def _load_json_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _stable_payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_artifact_contract(rel_path: str, payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    contract = ARTIFACT_CONTRACTS.get(rel_path)
    if not contract:
        return []
    errors: List[Dict[str, Any]] = []
    expected_schema = contract.get("schema_version")
    if expected_schema is not None and payload.get("schema_version") != expected_schema:
        errors.append({
            "artifact": rel_path,
            "field": "schema_version",
            "message": "unexpected schema_version",
            "expected": expected_schema,
            "actual": payload.get("schema_version"),
        })
    for field in contract.get("required_fields", []) or []:
        if field not in payload or payload.get(field) is None:
            errors.append({
                "artifact": rel_path,
                "field": str(field),
                "message": "required field missing or null",
            })
    return errors


def _verify_file_ref(
    *,
    ref_id: str,
    ref: Mapping[str, Any],
    missing: List[str],
    mismatched: List[str],
) -> int:
    path = Path(str(ref.get("path", "")))
    if not path.exists() or not path.is_file():
        missing.append(ref_id)
        return 0
    expected_sha = str(ref.get("sha256", ""))
    expected_size = ref.get("size_bytes")
    if expected_sha and _file_sha256(path) != expected_sha:
        mismatched.append(ref_id)
    elif expected_size is not None and path.stat().st_size != int(expected_size):
        mismatched.append(ref_id)
    return 1


def _verify_directory_ref(
    *,
    ref_id: str,
    ref: Mapping[str, Any],
    missing: List[str],
    mismatched: List[str],
) -> int:
    path = Path(str(ref.get("path", "")))
    if not path.exists() or not path.is_dir():
        missing.append(ref_id)
        return 0
    checked = 1
    expected_file_count = ref.get("file_count")
    expected_size = ref.get("size_bytes")
    files = [child for child in path.rglob("*") if child.is_file()]
    if expected_file_count is not None and len(files) != int(expected_file_count):
        mismatched.append(ref_id)
    elif expected_size is not None and sum(child.stat().st_size for child in files) != int(expected_size):
        mismatched.append(ref_id)
    for file_ref in ref.get("files", []) or []:
        if isinstance(file_ref, Mapping):
            checked += _verify_file_ref(
                ref_id=f"{ref_id}/{file_ref.get('logical_path', file_ref.get('path', 'file'))}",
                ref=file_ref,
                missing=missing,
                mismatched=mismatched,
            )
    return checked


def _verify_input_refs(input_refs: Mapping[str, Any]) -> Dict[str, Any]:
    missing: List[str] = []
    mismatched: List[str] = []
    semantic_errors: List[Dict[str, Any]] = []
    checked = 0
    workflow_bundle = input_refs.get("workflow_bundle")
    if isinstance(workflow_bundle, Mapping):
        checked += _verify_file_ref(
            ref_id="workflow_bundle",
            ref=workflow_bundle,
            missing=missing,
            mismatched=mismatched,
        )
        for nested_ref in workflow_bundle.get("nested_artifact_refs", []) or []:
            if not isinstance(nested_ref, Mapping):
                continue
            logical_path = str(nested_ref.get("logical_path", nested_ref.get("path", "nested")))
            ref_id = f"workflow_bundle.nested:{logical_path}"
            kind = str(nested_ref.get("kind", "file"))
            if kind == "directory":
                checked += _verify_directory_ref(
                    ref_id=ref_id,
                    ref=nested_ref,
                    missing=missing,
                    mismatched=mismatched,
                )
            else:
                checked += _verify_file_ref(
                    ref_id=ref_id,
                    ref=nested_ref,
                    missing=missing,
                    mismatched=mismatched,
                )
    workflow_corpus = input_refs.get("workflow_corpus")
    if isinstance(workflow_corpus, Mapping):
        checked += _verify_file_ref(
            ref_id="workflow_corpus",
            ref=workflow_corpus,
            missing=missing,
            mismatched=mismatched,
        )
        for workload_ref in workflow_corpus.get("workloads", []) or []:
            if not isinstance(workload_ref, Mapping):
                continue
            workload_id = str(workload_ref.get("workload_id", "workload"))
            bundle_ref = workload_ref.get("bundle_ref", {})
            if isinstance(bundle_ref, Mapping):
                checked += _verify_file_ref(
                    ref_id=f"workflow_corpus.workload[{workload_id}].bundle",
                    ref=bundle_ref,
                    missing=missing,
                    mismatched=mismatched,
                )
            for nested_ref in workload_ref.get("nested_artifact_refs", []) or []:
                if not isinstance(nested_ref, Mapping):
                    continue
                logical_path = str(nested_ref.get("logical_path", nested_ref.get("path", "nested")))
                ref_id = f"workflow_corpus.workload[{workload_id}].nested:{logical_path}"
                kind = str(nested_ref.get("kind", "file"))
                if kind == "directory":
                    checked += _verify_directory_ref(
                        ref_id=ref_id,
                        ref=nested_ref,
                        missing=missing,
                        mismatched=mismatched,
                    )
                else:
                    checked += _verify_file_ref(
                        ref_id=ref_id,
                        ref=nested_ref,
                        missing=missing,
                        mismatched=mismatched,
                    )
    feedback_samples = input_refs.get("feedback_samples")
    if isinstance(feedback_samples, Mapping):
        checked += _verify_file_ref(
            ref_id="feedback_samples",
            ref=feedback_samples,
            missing=missing,
            mismatched=mismatched,
        )
    return {
        "checked_input_ref_count": checked,
        "missing_input_refs": missing,
        "mismatched_input_refs": mismatched,
    }


def verify_run_dir(run_dir: Path) -> Dict[str, Any]:
    manifest_path = run_dir / REPLAY_MANIFEST_NAME
    manifest = _load_json_object(manifest_path)
    byte_hashes = manifest.get("artifact_byte_hashes", {})
    payload_hashes = manifest.get("artifact_payload_hashes", {})
    if not isinstance(byte_hashes, Mapping) or not isinstance(payload_hashes, Mapping):
        return {
            "schema_version": "dse.qe_fpga_replay_manifest_verification.v1",
            "status": "failed",
            "run_dir": str(run_dir),
            "checked_artifact_count": 0,
            "missing_artifacts": [],
            "mismatched_artifacts": [],
            "errors": ["manifest_hash_tables_missing_or_malformed"],
            "claim_boundary": "replay_manifest_verification_only_not_hardware_evidence",
        }

    missing: List[str] = []
    mismatched: List[str] = []
    semantic_errors: List[Dict[str, Any]] = []
    checked = 0
    for rel_path, expected_byte_info in sorted(byte_hashes.items()):
        artifact_path = run_dir / str(rel_path)
        if not artifact_path.exists():
            missing.append(str(rel_path))
            continue
        checked += 1
        expected_sha = ""
        expected_size = None
        if isinstance(expected_byte_info, Mapping):
            expected_sha = str(expected_byte_info.get("sha256", ""))
            expected_size = expected_byte_info.get("size_bytes")
        actual_sha = _file_sha256(artifact_path)
        actual_size = artifact_path.stat().st_size
        payload = _load_json_object(artifact_path)
        actual_payload_hash = _stable_payload_hash(payload)
        expected_payload_hash = str(payload_hashes.get(str(rel_path), ""))
        if (
            actual_sha != expected_sha
            or actual_size != expected_size
            or actual_payload_hash != expected_payload_hash
        ):
            mismatched.append(str(rel_path))
        semantic_errors.extend(_validate_artifact_contract(str(rel_path), payload))

    semantic_errors.extend(_validate_artifact_contract(REPLAY_MANIFEST_NAME, manifest))

    input_ref_report = _verify_input_refs(
        manifest.get("input_refs", {}) if isinstance(manifest.get("input_refs"), Mapping) else {}
    )
    status = (
        "passed"
        if not missing and not mismatched
        and not input_ref_report["missing_input_refs"]
        and not input_ref_report["mismatched_input_refs"]
        and not semantic_errors
        else "failed"
    )
    return {
        "schema_version": "dse.qe_fpga_replay_manifest_verification.v1",
        "status": status,
        "run_dir": str(run_dir),
        "checked_artifact_count": checked,
        **input_ref_report,
        "missing_artifacts": missing,
        "mismatched_artifacts": mismatched,
        "semantic_error_artifacts": sorted({str(error.get("artifact", "")) for error in semantic_errors if error.get("artifact")}),
        "semantic_errors": semantic_errors,
        "errors": [],
        "claim_boundary": "replay_manifest_verification_only_not_hardware_evidence",
    }


def main(argv: List[str] | None = None) -> int:
    args = parse_args(list(argv) if argv is not None else sys.argv[1:])
    report = verify_run_dir(args.run_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
