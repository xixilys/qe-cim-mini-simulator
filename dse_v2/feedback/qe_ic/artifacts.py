#!/usr/bin/env python3
"""Artifact I/O for QE-IC Layer-6 synthetic feedback calibration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.candidates.qe_ic import validate_qe_ic_candidate_plan
from dse_v2.evaluation.qe_ic.l1_cost_model import validate_qe_ic_l1_cost_model_results
from dse_v2.feedback.qe_ic.calibration import run_qe_ic_feedback_calibration
from dse_v2.feedback.qe_ic.feedback_config import validate_qe_ic_feedback_config
from dse_v2.feedback.qe_ic.replay import validate_qe_ic_synthetic_high_fidelity_labels
from dse_v2.feedback.qe_ic.schema import (
    MANIFEST_CLAIM_BOUNDARY,
    PRODUCER,
    QE_IC_FEEDBACK_ARTIFACTS,
    QE_IC_FEEDBACK_CALIBRATION_ARTIFACT,
    QE_IC_FEEDBACK_MANIFEST_ARTIFACT,
    QE_IC_FEEDBACK_MANIFEST_SCHEMA_VERSION,
    QE_IC_FEEDBACK_README_ARTIFACT,
    QE_IC_FEEDBACK_VALIDATION_ARTIFACT,
    QE_IC_FEEDBACK_VALIDATION_SCHEMA_VERSION,
)
from dse_v2.feedback.qe_ic.validation import validate_qe_ic_feedback_calibration


class QeIcFeedbackArtifactError(ValueError):
    """Raised when persisted QE-IC feedback artifacts fail validation."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open() as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise QeIcFeedbackArtifactError(f"{path} does not exist") from exc
    if not isinstance(payload, dict):
        raise QeIcFeedbackArtifactError(f"{path} did not contain a JSON object")
    return payload


def _remove_stale_canonical_artifacts(out_dir: Path) -> None:
    for artifact_name in (
        QE_IC_FEEDBACK_CALIBRATION_ARTIFACT,
        QE_IC_FEEDBACK_MANIFEST_ARTIFACT,
        QE_IC_FEEDBACK_README_ARTIFACT,
    ):
        artifact_path = out_dir / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()


def _failed_validation(
    *,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": QE_IC_FEEDBACK_VALIDATION_SCHEMA_VERSION,
        "status": "failed",
        "errors": errors,
        "warnings": warnings or [],
        "candidate_feedback_record_count": 0,
        "promotion_precision": None,
        "false_promotion_rate": None,
        "wasted_budget_ratio": None,
    }


def _prefixed_errors(validation: Mapping[str, Any], prefix: str) -> list[dict[str, str]]:
    return [
        {
            "field": f"{prefix}.{error.get('field', '$')}",
            "message": str(error.get("message", "")),
        }
        for error in validation.get("errors", [])
        if isinstance(error, Mapping)
    ]


def _validate_inputs(
    candidate_plan: Mapping[str, Any],
    l1_results: Mapping[str, Any],
    labels: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for prefix, validation in (
        ("candidate_plan", validate_qe_ic_candidate_plan(candidate_plan)),
        ("l1_results", validate_qe_ic_l1_cost_model_results(l1_results)),
        ("synthetic_high_fidelity_labels", validate_qe_ic_synthetic_high_fidelity_labels(labels)),
        ("feedback_config", validate_qe_ic_feedback_config(config)),
    ):
        if validation.get("status") != "passed":
            errors.extend(_prefixed_errors(validation, prefix))
        for warning in validation.get("warnings", []):
            if isinstance(warning, Mapping):
                warnings.append(
                    {
                        "field": f"{prefix}.{warning.get('field', '$')}",
                        "message": str(warning.get("message", "")),
                    }
                )
    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
    }


def build_qe_ic_feedback_manifest() -> dict[str, Any]:
    """Build the Layer-6 feedback artifact manifest."""

    return {
        "schema_version": QE_IC_FEEDBACK_MANIFEST_SCHEMA_VERSION,
        "artifact_role": "dse_layer6_feedback_calibration",
        "calibration_artifact": QE_IC_FEEDBACK_CALIBRATION_ARTIFACT,
        "validation_artifact": QE_IC_FEEDBACK_VALIDATION_ARTIFACT,
        "readme_artifact": QE_IC_FEEDBACK_README_ARTIFACT,
        "producer": PRODUCER,
        "layer": "layer6_feedback_calibration",
        "source_artifacts": [
            "qe_ic_candidate_plan.json",
            "qe_ic_l1_cost_model_results.json",
            "qe_ic_synthetic_high_fidelity_labels_fixture.json",
            "qe_ic_feedback_config_fixture.json",
        ],
        "claim_boundary": MANIFEST_CLAIM_BOUNDARY,
    }


def build_qe_ic_feedback_readme(calibration: Mapping[str, Any]) -> str:
    """Build README text shipped beside Layer-6 feedback artifacts."""

    metrics = calibration.get("metrics") if isinstance(calibration.get("metrics"), Mapping) else {}
    stopping = calibration.get("stopping_condition_evaluation") if isinstance(calibration.get("stopping_condition_evaluation"), Mapping) else {}
    return "\n".join(
        [
            "# QE-IC Layer-6 Synthetic Feedback Calibration",
            "",
            "## Artifact Role",
            "",
            "This artifact compares Layer-4 promotion decisions and Layer-5A L1 "
            "analytical estimates against synthetic high-fidelity replay labels. "
            "It calibrates the next-round search policy and records whether the "
            "campaign should continue under synthetic replay stopping conditions.",
            "",
            "## Metrics",
            "",
            f"- Promotion precision: {metrics.get('promotion_precision')}.",
            f"- False promotion rate: {metrics.get('false_promotion_rate')}.",
            f"- Wasted budget ratio: {metrics.get('wasted_budget_ratio')}.",
            f"- Useful candidate count: {metrics.get('useful_candidate_count')}.",
            f"- Top-k useful count: {metrics.get('top_k_useful_count')}.",
            "",
            "## Stopping Decision",
            "",
            f"Decision basis: `{stopping.get('decision_basis')}`. Decision: `{stopping.get('stop_decision')}`. "
            f"Reasons: {', '.join(stopping.get('stop_reasons', [])) if isinstance(stopping.get('stop_reasons'), list) else ''}.",
            "",
            "## Claim Boundary",
            "",
            str(calibration.get("claim_boundary")),
            "",
            "No SystemC, gem5, Vivado, DC, QE, RTL, or HLS execution was run. "
            "The labels are synthetic replay labels only and are not measured "
            "hardware performance.",
            "",
        ]
    )


def write_qe_ic_feedback_artifacts(
    out_dir: Path,
    candidate_plan_path: Path,
    l1_results_path: Path,
    synthetic_labels_path: Path,
    feedback_config_path: Path,
) -> dict[str, Any]:
    """Write feedback calibration, validation, manifest, and README artifacts."""

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        candidate_plan = _load_json_object(candidate_plan_path)
        l1_results = _load_json_object(l1_results_path)
        labels = _load_json_object(synthetic_labels_path)
        config = _load_json_object(feedback_config_path)
    except QeIcFeedbackArtifactError as exc:
        _remove_stale_canonical_artifacts(out_dir)
        validation = _failed_validation(errors=[{"field": "input", "message": str(exc)}])
        _write_json(out_dir / QE_IC_FEEDBACK_VALIDATION_ARTIFACT, validation)
        return {
            "status": "failed",
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_FEEDBACK_VALIDATION_ARTIFACT],
        }

    input_validation = _validate_inputs(candidate_plan, l1_results, labels, config)
    _remove_stale_canonical_artifacts(out_dir)
    if input_validation["status"] != "passed":
        validation = _failed_validation(
            errors=list(input_validation["errors"]),
            warnings=list(input_validation["warnings"]),
        )
        _write_json(out_dir / QE_IC_FEEDBACK_VALIDATION_ARTIFACT, validation)
        return {
            "status": "failed",
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_FEEDBACK_VALIDATION_ARTIFACT],
        }

    calibration = run_qe_ic_feedback_calibration(candidate_plan, l1_results, labels, config)
    validation = validate_qe_ic_feedback_calibration(calibration)
    _write_json(out_dir / QE_IC_FEEDBACK_VALIDATION_ARTIFACT, validation)
    if validation["status"] != "passed":
        return {
            "status": validation["status"],
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_FEEDBACK_VALIDATION_ARTIFACT],
        }

    manifest = build_qe_ic_feedback_manifest()
    readme = build_qe_ic_feedback_readme(calibration)
    _write_json(out_dir / QE_IC_FEEDBACK_CALIBRATION_ARTIFACT, calibration)
    _write_json(out_dir / QE_IC_FEEDBACK_MANIFEST_ARTIFACT, manifest)
    (out_dir / QE_IC_FEEDBACK_README_ARTIFACT).write_text(readme)
    return {
        "status": validation["status"],
        "out_dir": str(out_dir),
        "artifacts": list(QE_IC_FEEDBACK_ARTIFACTS),
    }


def load_qe_ic_feedback_calibration(path: Path) -> dict[str, Any]:
    """Load and validate persisted QE-IC Layer-6 feedback calibration."""

    payload = _load_json_object(path)
    validation = validate_qe_ic_feedback_calibration(payload)
    if validation["status"] != "passed":
        raise QeIcFeedbackArtifactError(
            f"{path} failed QE-IC feedback validation: {validation['errors']}"
        )
    return payload
