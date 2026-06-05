#!/usr/bin/env python3
"""Fail-closed validation for QE-IC real-baseline opportunity reports."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.campaigns.qe_ic import validate_qe_ic_closed_loop_dse_results
from dse_v2.candidates.qe_ic import validate_qe_ic_candidate_plan
from dse_v2.evaluation.qe_ic.l1_cost_model import validate_qe_ic_l1_cost_model_results
from dse_v2.evidence.qe_ic.candidate_result import validate_qe_ic_candidate_high_fidelity_results
from dse_v2.evidence.qe_ic.claim_gate import evaluate_qe_ic_claim_gate
from dse_v2.evidence.qe_ic.gpu_baseline import (
    baseline_match_key,
    baseline_records_by_match_key,
    validate_qe_ic_gpu_baseline_measurements,
)
from dse_v2.evidence.qe_ic.schema import (
    ALLOWED_VERDICTS,
    ANALYSIS_ROLE,
    CLAIM_BOUNDARY,
    CLAIM_STRENGTHS,
    FORBIDDEN_REPORT_TERMS,
    OPPORTUNITY_FOUND_VERDICTS,
    QE_IC_REAL_BASELINE_OPPORTUNITY_REPORT_SCHEMA_VERSION,
    QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_SCHEMA_VERSION,
    REQUIRED_INPUT_ARTIFACT_KEYS,
    SYSTEM_VERDICTS,
)
from dse_v2.profiling.qe_ic import validate_qe_ic_motif_profile
from dse_v2.viability.qe_ic import validate_qe_ic_target_viability
from dse_v2.workloads.qe_ic import validate_qe_ic_workload_suite


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _warning(warnings: list[dict[str, str]], field: str, message: str) -> None:
    warnings.append({"field": field, "message": message})


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _compare(expected: Any, actual: Any, *, eps: float = 1e-12) -> bool:
    if expected is None or actual is None:
        return expected is actual
    if _is_number(expected) and _is_number(actual):
        return abs(float(expected) - float(actual)) <= eps
    return expected == actual


def _forbidden_paths(value: Any, *, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_path = f"{prefix}.{key}" if prefix else str(key)
            lowered = str(key).lower()
            if lowered in FORBIDDEN_REPORT_TERMS:
                paths.append(key_path)
            paths.extend(_forbidden_paths(nested, prefix=key_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_forbidden_paths(nested, prefix=f"{prefix}[{index}]"))
    elif isinstance(value, str):
        lowered_value = value.lower()
        if "hardware_proven" in lowered_value:
            paths.append(prefix)
    return paths


def _superiority_claim_paths(value: Any, *, prefix: str = "") -> list[str]:
    allowed = {"system_conclusion.answer_to_research_question"}
    paths: list[str] = []
    phrases = (
        "fpga is stronger than gpu",
        "gpu+fpga is stronger than gpu",
        "hybrid is stronger than gpu",
        "fpga/hybrid is stronger than gpu",
        "fpga is faster than gpu",
        "gpu+fpga is faster than gpu",
        "hybrid is faster than gpu",
    )
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_path = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_superiority_claim_paths(nested, prefix=key_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_superiority_claim_paths(nested, prefix=f"{prefix}[{index}]"))
    elif isinstance(value, str) and prefix not in allowed:
        lowered = value.lower()
        if any(phrase in lowered for phrase in phrases):
            paths.append(prefix)
    return paths


def _load_json_for_validation(path: Path) -> Any:
    with path.open() as handle:
        return json.load(handle)


def _load_referenced_input_artifacts(
    report: Mapping[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Mapping[str, Any]]:
    index = _as_mapping(report.get("input_artifact_index"))
    loaded: dict[str, Mapping[str, Any]] = {}
    if set(index) != set(REQUIRED_INPUT_ARTIFACT_KEYS):
        _error(errors, "input_artifact_index", f"input_artifact_index must contain {REQUIRED_INPUT_ARTIFACT_KEYS}")
        return loaded
    validators = {
        "layer1_workload_suite": validate_qe_ic_workload_suite,
        "layer2_motif_profile": validate_qe_ic_motif_profile,
        "layer3_target_viability": validate_qe_ic_target_viability,
        "layer4_candidate_plan": validate_qe_ic_candidate_plan,
        "layer5a_l1_cost_model": validate_qe_ic_l1_cost_model_results,
        "layer6_closed_loop_dse": validate_qe_ic_closed_loop_dse_results,
        "gpu_baseline_measurements": validate_qe_ic_gpu_baseline_measurements,
        "candidate_high_fidelity_results": validate_qe_ic_candidate_high_fidelity_results,
    }
    for key in REQUIRED_INPUT_ARTIFACT_KEYS:
        raw_path = index.get(key)
        if not isinstance(raw_path, str) or not raw_path:
            _error(errors, f"input_artifact_index.{key}", "referenced input artifact path must be non-empty")
            continue
        path = Path(raw_path)
        try:
            payload = _load_json_for_validation(path)
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            _error(errors, f"input_artifact_index.{key}", f"referenced artifact could not be loaded: {exc}")
            continue
        if not isinstance(payload, Mapping):
            _error(errors, f"input_artifact_index.{key}", "referenced artifact must contain a JSON object")
            continue
        loaded[key] = payload
        validation = validators[key](payload)
        if validation.get("status") != "passed":
            for row in _as_list(validation.get("errors")):
                if isinstance(row, Mapping):
                    _error(errors, f"input_artifact_index.{key}.{row.get('field', '$')}", str(row.get("message", "")))
        for row in _as_list(validation.get("warnings")):
            if isinstance(row, Mapping):
                _warning(warnings, f"input_artifact_index.{key}.{row.get('field', '$')}", str(row.get("message", "")))
    return loaded


def _candidate_by_id(candidate_plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate.get("candidate_id")): candidate
        for candidate in _as_list(candidate_plan.get("candidates"))
        if isinstance(candidate, Mapping) and isinstance(candidate.get("candidate_id"), str)
    }


def _candidate_result_by_id(candidate_results: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(record.get("candidate_id")): record
        for record in _as_list(candidate_results.get("candidate_results"))
        if isinstance(record, Mapping) and isinstance(record.get("candidate_id"), str)
    }


def _validate_candidate_result_consistency(
    *,
    candidate_plan: Mapping[str, Any],
    candidate_high_fidelity_results: Mapping[str, Any],
    errors: list[dict[str, str]],
    prefix: str,
) -> None:
    candidates = _candidate_by_id(candidate_plan)
    for index, result in enumerate(_as_list(candidate_high_fidelity_results.get("candidate_results"))):
        row_prefix = f"{prefix}.candidate_results[{index}]"
        if not isinstance(result, Mapping):
            continue
        candidate_id = str(result.get("candidate_id", ""))
        candidate = _as_mapping(candidates.get(candidate_id))
        if not candidate:
            _error(errors, f"{row_prefix}.candidate_id", "candidate_result must reference a Layer-4 candidate")
            continue
        for field in ("workload_family_id", "motif_id", "target_type"):
            if result.get(field) != candidate.get(field):
                _error(errors, f"{row_prefix}.{field}", f"{field} must match Layer-4 candidate")
        expected_family = _as_mapping(candidate.get("candidate_parameters")).get("template_family")
        actual_family = _as_mapping(result.get("architecture_summary")).get("architecture_family")
        if expected_family and actual_family != expected_family:
            _error(
                errors,
                f"{row_prefix}.architecture_summary.architecture_family",
                "architecture_family must match Layer-4 candidate template_family",
            )


def _validate_raw_inputs_against_referenced_artifacts(
    *,
    report: Mapping[str, Any],
    referenced: Mapping[str, Mapping[str, Any]],
    errors: list[dict[str, str]],
) -> None:
    candidate_results = _candidate_result_by_id(_as_mapping(referenced.get("candidate_high_fidelity_results")))
    baselines = baseline_records_by_match_key(_as_mapping(referenced.get("gpu_baseline_measurements")))
    for index, record in enumerate(_as_list(report.get("opportunity_records"))):
        if not isinstance(record, Mapping):
            continue
        prefix = f"opportunity_records[{index}].raw_claim_gate_inputs"
        raw = _as_mapping(record.get("raw_claim_gate_inputs"))
        raw_candidate = _as_mapping(raw.get("candidate_result"))
        candidate_id = str(raw_candidate.get("candidate_id", ""))
        referenced_candidate = candidate_results.get(candidate_id)
        if referenced_candidate is None:
            _error(
                errors,
                f"{prefix}.candidate_result",
                "raw candidate_result is not present in referenced artifact",
            )
        elif dict(raw_candidate) != dict(referenced_candidate):
            _error(
                errors,
                f"{prefix}.candidate_result",
                "raw candidate_result does not match referenced artifact",
            )
        raw_baseline = raw.get("gpu_baseline_record")
        baseline_key = baseline_match_key(raw_candidate)
        referenced_baseline = baselines.get(baseline_key)
        if raw_baseline is None:
            if referenced_baseline is not None:
                _error(
                    errors,
                    f"{prefix}.gpu_baseline_record",
                    "raw GPU baseline record is null but referenced artifact contains an exact matching baseline",
                )
            continue
        if not isinstance(raw_baseline, Mapping):
            _error(errors, f"{prefix}.gpu_baseline_record", "raw GPU baseline record must be a mapping or null")
            continue
        if referenced_baseline is None:
            _error(
                errors,
                f"{prefix}.gpu_baseline_record",
                "raw GPU baseline record is not present in referenced artifact",
            )
        elif dict(raw_baseline) != dict(referenced_baseline):
            _error(
                errors,
                f"{prefix}.gpu_baseline_record",
                "raw GPU baseline record does not match referenced artifact",
            )


def _referenced_payload_real_flags(
    referenced: Mapping[str, Mapping[str, Any]],
) -> tuple[bool | None, bool | None]:
    baseline_payload = referenced.get("gpu_baseline_measurements")
    candidate_payload = referenced.get("candidate_high_fidelity_results")
    baseline_real = baseline_payload.get("measurements_are_real") is True if isinstance(baseline_payload, Mapping) else None
    candidate_real = candidate_payload.get("results_are_real") is True if isinstance(candidate_payload, Mapping) else None
    return baseline_real, candidate_real


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


def _validate_candidate_tracking_consistency(
    *,
    candidate_high_fidelity_results: Mapping[str, Any],
    l1_results: Mapping[str, Any],
    closed_loop_results: Mapping[str, Any],
    errors: list[dict[str, str]],
    prefix: str,
) -> None:
    tracked = _tracked_candidate_ids(
        l1_results=l1_results,
        closed_loop_results=closed_loop_results,
    )
    for index, result in enumerate(_as_list(candidate_high_fidelity_results.get("candidate_results"))):
        if not isinstance(result, Mapping):
            continue
        candidate_id = str(result.get("candidate_id", ""))
        if candidate_id not in tracked:
            _error(
                errors,
                f"{prefix}.candidate_results[{index}].candidate_id",
                "candidate_result must reference a Layer-5A and Layer-6 tracked candidate",
            )


def _validate_embedded_inputs(report: Mapping[str, Any], errors: list[dict[str, str]]) -> None:
    for index, record in enumerate(_as_list(report.get("opportunity_records"))):
        prefix = f"opportunity_records[{index}].raw_claim_gate_inputs"
        raw = _as_mapping(record.get("raw_claim_gate_inputs"))
        candidate_result = _as_mapping(raw.get("candidate_result"))
        candidate_payload = {
            "schema_version": "dse.qe_ic.candidate_high_fidelity_results.v1",
            "results_are_real": record.get("evidence_status") != "fixture_example"
            and "fixture_only_evidence" not in _as_list(record.get("claim_blockers")),
            "candidate_results": [dict(candidate_result)] if candidate_result else [],
        }
        validation = validate_qe_ic_candidate_high_fidelity_results(candidate_payload)
        if validation.get("status") != "passed":
            for row in _as_list(validation.get("errors")):
                if isinstance(row, Mapping):
                    _error(errors, f"{prefix}.candidate_result.{row.get('field', '$')}", str(row.get("message", "")))
        baseline = raw.get("gpu_baseline_record")
        if isinstance(baseline, Mapping):
            baseline_payload = {
                "schema_version": "dse.qe_ic.gpu_baseline_measurements.v1",
                "measurement_role": "gpu_only_baseline",
                "evidence_status": baseline.get("evidence_status"),
                "measurements_are_real": baseline.get("evidence_status") == "measured"
                and "fixture_only_evidence" not in _as_list(record.get("claim_blockers")),
                "platform": {
                    "gpu_name": "embedded-validation",
                    "cpu_name": "embedded-validation",
                    "memory": "embedded-validation",
                    "qe_version": "embedded-validation",
                    "cuda_version": "embedded-validation",
                    "driver_version": "embedded-validation",
                    "precision": "embedded-validation",
                },
                "baseline_records": [dict(baseline)],
                "claim_boundary": (
                    "GPU baseline records are only real measurement evidence when "
                    "measurements_are_real is true and evidence_status is measured."
                ),
            }
            baseline_validation = validate_qe_ic_gpu_baseline_measurements(baseline_payload)
            if baseline_validation.get("status") != "passed":
                for row in _as_list(baseline_validation.get("errors")):
                    if isinstance(row, Mapping):
                        _error(errors, f"{prefix}.gpu_baseline_record.{row.get('field', '$')}", str(row.get("message", "")))


def _validate_record_fields_match_raw_inputs(record: Mapping[str, Any], *, prefix: str, errors: list[dict[str, str]]) -> None:
    raw = _as_mapping(record.get("raw_claim_gate_inputs"))
    candidate_result = _as_mapping(raw.get("candidate_result"))
    baseline = raw.get("gpu_baseline_record")
    for field in (
        "candidate_id",
        "workload_family_id",
        "motif_id",
        "target_type",
        "evidence_level",
        "evidence_status",
    ):
        if record.get(field) != candidate_result.get(field):
            _error(errors, f"{prefix}.{field}", f"{field} must match raw candidate_result")
    if record.get("architecture_summary") != candidate_result.get("architecture_summary"):
        _error(errors, f"{prefix}.architecture_summary", "architecture_summary must match raw candidate_result")
    expected_baseline_id = baseline.get("baseline_id") if isinstance(baseline, Mapping) else None
    if record.get("gpu_baseline_id") != expected_baseline_id:
        _error(errors, f"{prefix}.gpu_baseline_id", "gpu_baseline_id must match raw GPU baseline record")


def _expected_system_conclusion(records: list[Mapping[str, Any]]) -> dict[str, Any]:
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
    counter: Counter[str] = Counter()
    for record in records:
        counter.update(str(reason) for reason in _as_list(record.get("failure_reasons")))
    return {
        "overall_verdict": overall,
        "best_candidate_id": best.get("candidate_id") if best else None,
        "best_speedup_vs_gpu": best.get("speedup_vs_gpu_mean") if best else None,
        "dominant_failure_modes": [reason for reason, _count in counter.most_common()],
    }


def validate_qe_ic_opportunity_input_artifacts(
    *,
    workload_suite: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
    target_viability: Mapping[str, Any],
    candidate_plan: Mapping[str, Any],
    l1_results: Mapping[str, Any],
    closed_loop_results: Mapping[str, Any],
    gpu_baseline_measurements: Mapping[str, Any],
    candidate_high_fidelity_results: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate all opportunity-analysis inputs before report construction."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    validators = [
        ("layer1_workload_suite", validate_qe_ic_workload_suite(workload_suite)),
        ("layer2_motif_profile", validate_qe_ic_motif_profile(motif_profile)),
        ("layer3_target_viability", validate_qe_ic_target_viability(target_viability)),
        ("layer4_candidate_plan", validate_qe_ic_candidate_plan(candidate_plan)),
        ("layer5a_l1_cost_model", validate_qe_ic_l1_cost_model_results(l1_results)),
        ("layer6_closed_loop_dse", validate_qe_ic_closed_loop_dse_results(closed_loop_results)),
        ("gpu_baseline_measurements", validate_qe_ic_gpu_baseline_measurements(gpu_baseline_measurements)),
        ("candidate_high_fidelity_results", validate_qe_ic_candidate_high_fidelity_results(candidate_high_fidelity_results)),
    ]
    for prefix, validation in validators:
        if validation.get("status") != "passed":
            for row in _as_list(validation.get("errors")):
                if isinstance(row, Mapping):
                    _error(errors, f"{prefix}.{row.get('field', '$')}", str(row.get("message", "")))
        for row in _as_list(validation.get("warnings")):
            if isinstance(row, Mapping):
                _warning(warnings, f"{prefix}.{row.get('field', '$')}", str(row.get("message", "")))
    _validate_candidate_result_consistency(
        candidate_plan=candidate_plan,
        candidate_high_fidelity_results=candidate_high_fidelity_results,
        errors=errors,
        prefix="candidate_high_fidelity_results",
    )
    _validate_candidate_tracking_consistency(
        candidate_high_fidelity_results=candidate_high_fidelity_results,
        l1_results=l1_results,
        closed_loop_results=closed_loop_results,
        errors=errors,
        prefix="candidate_high_fidelity_results",
    )
    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
    }


def validate_qe_ic_real_baseline_opportunity_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a QE-IC opportunity report and recompute claim gates."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(report, Mapping):
        _error(errors, "$", "opportunity report must be a mapping")
        return {
            "schema_version": QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_SCHEMA_VERSION,
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "opportunity_record_count": 0,
        }

    if report.get("schema_version") != QE_IC_REAL_BASELINE_OPPORTUNITY_REPORT_SCHEMA_VERSION:
        _error(errors, "schema_version", "schema_version is incorrect")
    if report.get("analysis_role") != ANALYSIS_ROLE:
        _error(errors, "analysis_role", "analysis_role is incorrect")
    if report.get("claim_boundary") != CLAIM_BOUNDARY:
        _error(errors, "claim_boundary", "claim_boundary must match canonical claim boundary")
    referenced = _load_referenced_input_artifacts(report, errors, warnings)
    if "layer4_candidate_plan" in referenced and "candidate_high_fidelity_results" in referenced:
        _validate_candidate_result_consistency(
            candidate_plan=referenced["layer4_candidate_plan"],
            candidate_high_fidelity_results=referenced["candidate_high_fidelity_results"],
            errors=errors,
            prefix="input_artifact_index.candidate_high_fidelity_results",
        )
    if {
        "layer5a_l1_cost_model",
        "layer6_closed_loop_dse",
        "candidate_high_fidelity_results",
    }.issubset(referenced):
        _validate_candidate_tracking_consistency(
            candidate_high_fidelity_results=referenced["candidate_high_fidelity_results"],
            l1_results=referenced["layer5a_l1_cost_model"],
            closed_loop_results=referenced["layer6_closed_loop_dse"],
            errors=errors,
            prefix="input_artifact_index.candidate_high_fidelity_results",
        )
    if "gpu_baseline_measurements" in referenced and "candidate_high_fidelity_results" in referenced:
        _validate_raw_inputs_against_referenced_artifacts(
            report=report,
            referenced=referenced,
            errors=errors,
        )
    for path in _forbidden_paths(report):
        _error(errors, path, "forbidden hardware_proven or final superiority claim term is present")
    for path in _superiority_claim_paths(report):
        _error(errors, path, "superiority claim outside system_conclusion is forbidden")

    records = [row for row in _as_list(report.get("opportunity_records")) if isinstance(row, Mapping)]
    if len(records) != len(_as_list(report.get("opportunity_records"))):
        _error(errors, "opportunity_records", "all opportunity records must be mappings")
    _validate_embedded_inputs(report, errors)
    for index, record in enumerate(records):
        prefix = f"opportunity_records[{index}]"
        _validate_record_fields_match_raw_inputs(record, prefix=prefix, errors=errors)
        if record.get("verdict") not in ALLOWED_VERDICTS:
            _error(errors, f"{prefix}.verdict", "verdict is unsupported")
        if record.get("claim_strength") not in CLAIM_STRENGTHS:
            _error(errors, f"{prefix}.claim_strength", "claim_strength is unsupported")
        if not isinstance(record.get("claim_allowed"), bool):
            _error(errors, f"{prefix}.claim_allowed", "claim_allowed must be boolean")
        if record.get("claim_allowed") is False and record.get("claim_strength") == "strong":
            _error(errors, f"{prefix}.claim_strength", "claim_allowed false cannot have strong claim strength")
        if record.get("verdict") in OPPORTUNITY_FOUND_VERDICTS and record.get("claim_allowed") is not True:
            _error(errors, f"{prefix}.verdict", "opportunity_found verdict requires claim_allowed true")
        if record.get("claim_allowed") is True and "fixture_only_evidence" in _as_list(record.get("claim_blockers")):
            _error(errors, f"{prefix}.claim_allowed", "fixture evidence cannot allow a real claim")
        if record.get("claim_strength") == "strong" and record.get("evidence_status") == "fixture_example":
            _error(errors, f"{prefix}.claim_strength", "fixture evidence cannot make a strong claim")
        if record.get("claim_strength") == "strong" and record.get("evidence_level") == "l1_estimate_only":
            _error(errors, f"{prefix}.claim_strength", "l1_estimate_only cannot make a strong claim")
        raw = _as_mapping(record.get("raw_claim_gate_inputs"))
        candidate_result = _as_mapping(raw.get("candidate_result"))
        baseline = raw.get("gpu_baseline_record")
        baseline_mapping = _as_mapping(baseline) if isinstance(baseline, Mapping) else None
        raw_config = _as_mapping(raw.get("opportunity_config"))
        referenced_baseline_real, referenced_candidate_real = _referenced_payload_real_flags(referenced)
        baseline_payload_real = referenced_baseline_real if referenced_baseline_real is not None else (
            baseline_mapping is not None
            and baseline_mapping.get("evidence_status") == "measured"
            and "fixture_only_evidence" not in _as_list(record.get("claim_blockers"))
        )
        candidate_payload_real = referenced_candidate_real if referenced_candidate_real is not None else (
            record.get("evidence_status") != "fixture_example"
            and "fixture_only_evidence" not in _as_list(record.get("claim_blockers"))
        )
        expected_gate = evaluate_qe_ic_claim_gate(
            baseline=baseline_mapping,
            baseline_payload_real=baseline_payload_real,
            candidate_result=candidate_result,
            candidate_payload_real=candidate_payload_real,
            opportunity_config=raw_config,
        )
        comparisons = {
            "speedup_vs_gpu_mean": expected_gate["speedup_vs_gpu_mean"],
            "speedup_vs_gpu_conservative_ci": expected_gate["speedup_vs_gpu_conservative_ci"],
            "claim_allowed": expected_gate["claim_allowed"],
            "claim_strength": expected_gate["claim_strength"],
            "verdict": expected_gate["verdict"],
        }
        for field, expected in comparisons.items():
            if not _compare(expected, record.get(field)):
                _error(errors, f"{prefix}.{field}", f"{field} does not match recomputed claim gate")
        for field in ("claim_blockers", "failure_reasons"):
            if record.get(field) != expected_gate[field]:
                _error(errors, f"{prefix}.{field}", f"{field} does not match recomputed claim gate")

    conclusion = _as_mapping(report.get("system_conclusion"))
    if conclusion.get("overall_verdict") not in SYSTEM_VERDICTS:
        _error(errors, "system_conclusion.overall_verdict", "overall_verdict is unsupported")
    expected_conclusion = _expected_system_conclusion(records)
    for field, expected in expected_conclusion.items():
        if not _compare(expected, conclusion.get(field)):
            _error(errors, f"system_conclusion.{field}", f"{field} does not match opportunity records")
    if any(record.get("claim_allowed") for record in records):
        if "passes the claim gate" not in str(conclusion.get("answer_to_research_question", "")):
            _error(errors, "system_conclusion.answer_to_research_question", "claimable conclusions must be inside claim-gated answer")
    elif "stronger" in str(conclusion.get("answer_to_research_question", "")).lower() and "insufficient" not in str(conclusion.get("answer_to_research_question", "")).lower():
        _error(errors, "system_conclusion.answer_to_research_question", "unclaimable reports must not make superiority claims")

    return {
        "schema_version": QE_IC_REAL_BASELINE_OPPORTUNITY_VALIDATION_SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "opportunity_record_count": len(records),
        "overall_verdict": conclusion.get("overall_verdict"),
        "best_candidate_id": conclusion.get("best_candidate_id"),
    }
