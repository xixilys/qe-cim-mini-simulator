#!/usr/bin/env python3
"""Numerical correctness oracle for QE reference workload rows.

This module evaluates correctness evidence only.  It intentionally refuses to
infer numerical validity from timing-only data, and it keeps kernel-equivalence
and SCF/physical-equivalence gates independent so either gate can fail without
hiding the other result.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence


QE_NUMERICAL_CORRECTNESS_ORACLE_SCHEMA = "dse.qe_numerical_correctness_oracle.v1"
QE_NUMERICAL_CORRECTNESS_TOLERANCE_SCHEMA = "dse.qe_numerical_correctness_tolerances.v1"
QE_NUMERICAL_CORRECTNESS_RESULT_SCHEMA = "dse.qe_numerical_correctness_result.v1"

REQUIRED_TOLERANCE_FIELDS = (
    "kernel_absolute_tolerance",
    "kernel_relative_tolerance",
    "kernel_error_metric",
    "scf_total_energy_tolerance_ry",
    "density_residual_tolerance",
    "eigenvalue_summary_tolerance_ry",
    "force_tolerance_ry_bohr",
    "stress_tolerance_kbar",
    "source",
    "rationale",
)
NUMERIC_TOLERANCE_FIELDS = (
    "kernel_absolute_tolerance",
    "kernel_relative_tolerance",
    "scf_total_energy_tolerance_ry",
    "density_residual_tolerance",
    "eigenvalue_summary_tolerance_ry",
    "force_tolerance_ry_bohr",
    "stress_tolerance_kbar",
)
TRUSTED_CLAIM_LABELS = {"l4_trusted_speedup", "deliverable_complete"}
PLACEHOLDER_STRINGS = {"", "todo", "tbd", "placeholder", "null", "none", "unknown"}


def default_qe_correctness_tolerances(*, status: str = "draft") -> Dict[str, Any]:
    """Return a complete tolerance profile required before trusted rows."""
    return {
        "schema_version": QE_NUMERICAL_CORRECTNESS_TOLERANCE_SCHEMA,
        "status": status,
        "tolerance_profile_id": "qe_mainflow_correctness_v1",
        "kernel_absolute_tolerance": 1.0e-10,
        "kernel_relative_tolerance": 1.0e-8,
        "kernel_error_metric": "max_abs_and_relative_l2",
        "scf_total_energy_tolerance_ry": 1.0e-6,
        "density_residual_tolerance": 1.0e-7,
        "eigenvalue_summary_tolerance_ry": 1.0e-5,
        "force_tolerance_ry_bohr": 1.0e-4,
        "stress_tolerance_kbar": 1.0e-2,
        "source": "repo_defined_qe_mainflow_contract",
        "rationale": "Draft release-v1 oracle fields; real campaign may tighten per frozen workload case.",
    }


def numerical_correctness_oracle_schema(*, status: str = "draft") -> Dict[str, Any]:
    return {
        "schema_version": QE_NUMERICAL_CORRECTNESS_ORACLE_SCHEMA,
        "status": status,
        "required_tolerance_fields": list(REQUIRED_TOLERANCE_FIELDS),
        "gate_policy": {
            "kernel_gate_required": True,
            "scf_physical_gate_required": True,
            "timing_only_evidence_allowed_for_correctness": False,
            "trusted_claim_labels_blocked_when_any_gate_missing_or_failed": sorted(TRUSTED_CLAIM_LABELS),
        },
    }


def _placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in PLACEHOLDER_STRINGS:
        return True
    return False


def validate_qe_correctness_tolerances(tolerances: Mapping[str, Any]) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    if tolerances.get("schema_version") != QE_NUMERICAL_CORRECTNESS_TOLERANCE_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected QE correctness tolerance schema"})
    for field in REQUIRED_TOLERANCE_FIELDS:
        if field not in tolerances or _placeholder(tolerances.get(field)):
            errors.append({"field": field, "message": "required tolerance field is missing or placeholder"})
    for field in NUMERIC_TOLERANCE_FIELDS:
        if field not in tolerances or _placeholder(tolerances.get(field)):
            continue
        try:
            value = float(tolerances[field])
        except Exception:
            errors.append({"field": field, "message": "numeric tolerance field must be numeric"})
            continue
        if value <= 0.0:
            errors.append({"field": field, "message": "numeric tolerance field must be positive"})
    return {
        "schema_version": "dse.qe_numerical_correctness_tolerance_validation.v1",
        "valid": not errors,
        "errors": errors,
    }


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _kernel_check(observation: Mapping[str, Any], tolerances: Mapping[str, Any], index: int) -> Dict[str, Any]:
    kernel_id = str(observation.get("kernel_id", f"kernel_{index}"))
    abs_error = _float_or_none(observation.get("absolute_error"))
    rel_error = _float_or_none(observation.get("relative_error"))
    observed = _float_or_none(observation.get("observed"))
    reference = _float_or_none(observation.get("reference"))
    if abs_error is None and observed is not None and reference is not None:
        abs_error = abs(observed - reference)
    if rel_error is None and abs_error is not None and reference is not None:
        rel_error = abs_error / max(abs(reference), 1.0e-300)
    missing = abs_error is None or rel_error is None
    passed = (
        not missing
        and abs_error <= float(tolerances["kernel_absolute_tolerance"])
        and rel_error <= float(tolerances["kernel_relative_tolerance"])
    )
    return {
        "kernel_id": kernel_id,
        "status": "missing" if missing else ("passed" if passed else "failed"),
        "absolute_error": abs_error,
        "relative_error": rel_error,
        "absolute_tolerance": float(tolerances["kernel_absolute_tolerance"]),
        "relative_tolerance": float(tolerances["kernel_relative_tolerance"]),
    }


def _physical_check(name: str, value: Any, tolerance: float, *, required: bool = True) -> Dict[str, Any]:
    metric = _float_or_none(value)
    if metric is None:
        return {"metric": name, "status": "missing" if required else "not_applicable", "value": None, "tolerance": tolerance}
    return {
        "metric": name,
        "status": "passed" if abs(metric) <= tolerance else "failed",
        "value": metric,
        "tolerance": tolerance,
    }


def _gate_status(checks: Sequence[Mapping[str, Any]]) -> str:
    statuses = [str(check.get("status")) for check in checks]
    if not checks or any(status == "missing" for status in statuses):
        return "missing"
    if any(status == "failed" for status in statuses):
        return "failed"
    if all(status in {"passed", "not_applicable"} for status in statuses):
        return "passed"
    return "failed"


def evaluate_qe_correctness_row(
    row: Mapping[str, Any],
    tolerances: Mapping[str, Any],
    *,
    requested_claim: str = "l4_trusted_speedup",
) -> Dict[str, Any]:
    """Evaluate kernel and SCF/physical correctness gates for one evidence row."""
    tolerance_report = validate_qe_correctness_tolerances(tolerances)
    downgrade_blocks: List[str] = []
    if not tolerance_report["valid"]:
        downgrade_blocks.append("invalid_or_placeholder_tolerances")

    timing_only = bool(row.get("timing_only")) or str(row.get("evidence_kind", "")).lower() == "timing_only"
    if timing_only:
        downgrade_blocks.append("timing_only_evidence_cannot_satisfy_correctness")

    kernel_observations = row.get("kernel_evidence", [])
    if not isinstance(kernel_observations, list):
        kernel_observations = []
    if tolerance_report["valid"]:
        kernel_checks = [_kernel_check(observation, tolerances, index) for index, observation in enumerate(kernel_observations) if isinstance(observation, Mapping)]
    else:
        kernel_checks = []
    kernel_gate = {
        "status": _gate_status(kernel_checks),
        "checks": kernel_checks,
        "required": True,
    }
    if kernel_gate["status"] != "passed":
        downgrade_blocks.append(f"kernel_gate_{kernel_gate['status']}")

    physical_evidence = row.get("physical_evidence", {})
    if not isinstance(physical_evidence, Mapping):
        physical_evidence = {}
    relax_like = str(row.get("workload_stage_type", "")).lower().replace("-", "_") in {"relax", "vc_relax"} or bool(row.get("relax_like"))
    physical_checks: List[Dict[str, Any]] = []
    if tolerance_report["valid"]:
        physical_checks = [
            _physical_check("total_energy_error_ry", physical_evidence.get("total_energy_error_ry"), float(tolerances["scf_total_energy_tolerance_ry"])),
            _physical_check("density_residual", physical_evidence.get("density_residual"), float(tolerances["density_residual_tolerance"])),
            _physical_check("eigenvalue_summary_error_ry", physical_evidence.get("eigenvalue_summary_error_ry"), float(tolerances["eigenvalue_summary_tolerance_ry"])),
            _physical_check("force_error_ry_bohr", physical_evidence.get("force_error_ry_bohr"), float(tolerances["force_tolerance_ry_bohr"]), required=relax_like),
            _physical_check("stress_error_kbar", physical_evidence.get("stress_error_kbar"), float(tolerances["stress_tolerance_kbar"]), required=relax_like),
        ]
    scf_physical_gate = {
        "status": _gate_status(physical_checks),
        "checks": physical_checks,
        "required": True,
    }
    if scf_physical_gate["status"] != "passed":
        downgrade_blocks.append(f"scf_physical_gate_{scf_physical_gate['status']}")

    trusted_claim_eligible = (
        tolerance_report["valid"]
        and not timing_only
        and kernel_gate["status"] == "passed"
        and scf_physical_gate["status"] == "passed"
    )
    allowed_claim_labels = ["blocked", "research_projection", "vertical_slice_only"]
    if trusted_claim_eligible:
        allowed_claim_labels.extend(sorted(TRUSTED_CLAIM_LABELS))
    elif requested_claim in TRUSTED_CLAIM_LABELS:
        downgrade_blocks.append(f"requested_{requested_claim}_blocked_by_correctness_oracle")

    return {
        "schema_version": QE_NUMERICAL_CORRECTNESS_RESULT_SCHEMA,
        "row_id": str(row.get("row_id", "qe_correctness_row")),
        "candidate_id": row.get("candidate_id"),
        "workload_case_id": row.get("workload_case_id"),
        "tolerance_validation": tolerance_report,
        "kernel_gate": kernel_gate,
        "scf_physical_gate": scf_physical_gate,
        "timing_only": timing_only,
        "trusted_claim_eligible": trusted_claim_eligible,
        "allowed_claim_labels": allowed_claim_labels,
        "requested_claim": requested_claim,
        "requested_claim_status": "passed" if requested_claim in allowed_claim_labels else "blocked",
        "downgrade_blocks": sorted(dict.fromkeys(downgrade_blocks)),
    }


__all__ = [
    "NUMERIC_TOLERANCE_FIELDS",
    "QE_NUMERICAL_CORRECTNESS_ORACLE_SCHEMA",
    "QE_NUMERICAL_CORRECTNESS_RESULT_SCHEMA",
    "QE_NUMERICAL_CORRECTNESS_TOLERANCE_SCHEMA",
    "REQUIRED_TOLERANCE_FIELDS",
    "TRUSTED_CLAIM_LABELS",
    "default_qe_correctness_tolerances",
    "evaluate_qe_correctness_row",
    "numerical_correctness_oracle_schema",
    "validate_qe_correctness_tolerances",
]
