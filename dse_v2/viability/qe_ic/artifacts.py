#!/usr/bin/env python3
"""Artifact I/O for QE-IC Layer-3 target viability reports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.profiling.qe_ic import validate_qe_ic_motif_profile
from dse_v2.viability.qe_ic.model import build_qe_ic_target_viability
from dse_v2.viability.qe_ic.schema import (
    DOWNSTREAM_CONSUMERS,
    MANIFEST_CLAIM_BOUNDARY,
    QE_IC_TARGET_VIABILITY_ARTIFACT,
    QE_IC_TARGET_VIABILITY_ARTIFACTS,
    QE_IC_TARGET_VIABILITY_MANIFEST_ARTIFACT,
    QE_IC_TARGET_VIABILITY_MANIFEST_SCHEMA_VERSION,
    QE_IC_TARGET_VIABILITY_README_ARTIFACT,
    QE_IC_TARGET_VIABILITY_VALIDATION_ARTIFACT,
    QE_IC_TARGET_VIABILITY_VALIDATION_SCHEMA_VERSION,
)
from dse_v2.viability.qe_ic.target_config import validate_qe_ic_target_config
from dse_v2.viability.qe_ic.validation import validate_qe_ic_target_viability
from dse_v2.workloads.qe_ic import validate_qe_ic_workload_suite


class QeIcTargetViabilityArtifactError(ValueError):
    """Raised when persisted QE-IC target-viability artifacts fail validation."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open() as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise QeIcTargetViabilityArtifactError(f"{path} does not exist") from exc
    if not isinstance(payload, dict):
        raise QeIcTargetViabilityArtifactError(f"{path} did not contain a JSON object")
    return payload


def _remove_stale_canonical_artifacts(out_dir: Path) -> None:
    for artifact_name in (
        QE_IC_TARGET_VIABILITY_ARTIFACT,
        QE_IC_TARGET_VIABILITY_MANIFEST_ARTIFACT,
        QE_IC_TARGET_VIABILITY_README_ARTIFACT,
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
        "schema_version": QE_IC_TARGET_VIABILITY_VALIDATION_SCHEMA_VERSION,
        "status": "failed",
        "errors": errors,
        "warnings": warnings or [],
        "record_count": 0,
        "target_count": 0,
    }


def _prefixed_errors(
    validation: Mapping[str, Any],
    *,
    prefix: str,
    label: str,
) -> list[dict[str, str]]:
    errors = [
        {
            "field": f"{prefix}.{error.get('field', '$')}",
            "message": f"invalid {label}: {error.get('message', '')}",
        }
        for error in validation.get("errors", [])
        if isinstance(error, Mapping)
    ]
    if not errors:
        errors.append({"field": prefix, "message": f"invalid {label}"})
    return errors


def _input_validation_failure(
    suite: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
    target_config: Mapping[str, Any],
) -> dict[str, Any] | None:
    layer1_validation = validate_qe_ic_workload_suite(suite)
    if layer1_validation.get("status") != "passed":
        return _failed_validation(
            errors=_prefixed_errors(layer1_validation, prefix="layer1_suite", label="Layer-1 suite")
        )

    layer2_validation = validate_qe_ic_motif_profile(motif_profile)
    if layer2_validation.get("status") != "passed":
        return _failed_validation(
            errors=_prefixed_errors(layer2_validation, prefix="layer2_motif_profile", label="Layer-2 motif profile")
        )

    target_validation = validate_qe_ic_target_config(target_config)
    if target_validation.get("status") != "passed":
        return _failed_validation(
            errors=_prefixed_errors(target_validation, prefix="target_config", label="target config")
        )
    return None


def build_qe_ic_target_viability_manifest() -> dict[str, Any]:
    """Build the QE-IC Layer-3 target-viability artifact manifest."""

    return {
        "schema_version": QE_IC_TARGET_VIABILITY_MANIFEST_SCHEMA_VERSION,
        "artifact_role": "dse_layer3_target_viability",
        "viability_artifact": QE_IC_TARGET_VIABILITY_ARTIFACT,
        "validation_artifact": QE_IC_TARGET_VIABILITY_VALIDATION_ARTIFACT,
        "readme_artifact": QE_IC_TARGET_VIABILITY_README_ARTIFACT,
        "producer": "dse_v2.viability.qe_ic",
        "layer": "layer3_target_viability_test",
        "downstream_consumers": list(DOWNSTREAM_CONSUMERS),
        "claim_boundary": MANIFEST_CLAIM_BOUNDARY,
    }


def build_qe_ic_target_viability_readme(report: Mapping[str, Any]) -> str:
    """Build README text shipped beside generated Layer-3 artifacts."""

    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    by_target_lines = []
    for target_type, row in sorted(summary.get("by_target_type", {}).items()):
        if isinstance(row, Mapping):
            by_target_lines.append(
                f"- `{target_type}`: records={row.get('record_count')}, "
                f"baseline={row.get('baseline_count')}, viable={row.get('viable_count')}, "
                f"maybe={row.get('maybe_count')}, reject={row.get('reject_count')}."
            )

    return "\n".join(
        [
            "# QE-IC Target Viability v1",
            "",
            "## Artifact Role",
            "",
            "This Layer-3 artifact consumes the Layer-1 QE-IC workload suite, "
            "the Layer-2 QE-IC motif profile, and a target-platform config fixture. "
            "It emits deterministic target viability estimates for configured GPU, "
            "FPGA, and GPU+FPGA hybrid target types.",
            "",
            "## Summary",
            "",
            f"Record count: {summary.get('record_count')}.",
            f"Baseline: {summary.get('baseline_count')}; viable: {summary.get('viable_count')}; "
            f"maybe: {summary.get('maybe_count')}; reject: {summary.get('reject_count')}.",
            "",
            *by_target_lines,
            "",
            "## Modeling Boundary",
            "",
            "The target platform values in the fixture are model parameters, not "
            "measured platform claims. Transfer and risk values are heuristic "
            "viability estimates, not measured hardware performance. Hybrid "
            "transfer estimates use a conservative GPU-FPGA movement proxy rather "
            "than a measured implementation model.",
            "",
            "## Claim Boundary",
            "",
            str(report.get("claim_boundary")),
            "",
            "Layer-3 does not generate concrete architectures, RTL, SystemC/gem5 "
            "requests, Vivado requests, promotion decisions, hardware implementation "
            "results, or final performance claims.",
            "",
        ]
    )


def write_qe_ic_target_viability_artifacts(
    out_dir: Path,
    suite_path: Path,
    motif_profile_path: Path,
    target_config_path: Path,
) -> dict[str, Any]:
    """Write target viability, validation, manifest, and README artifacts."""

    out_dir.mkdir(parents=True, exist_ok=True)
    suite = _load_json_object(suite_path)
    motif_profile = _load_json_object(motif_profile_path)
    target_config = _load_json_object(target_config_path)
    input_failure = _input_validation_failure(suite, motif_profile, target_config)
    _remove_stale_canonical_artifacts(out_dir)
    if input_failure is not None:
        _write_json(out_dir / QE_IC_TARGET_VIABILITY_VALIDATION_ARTIFACT, input_failure)
        return {
            "status": "failed",
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_TARGET_VIABILITY_VALIDATION_ARTIFACT],
        }

    report = build_qe_ic_target_viability(suite, motif_profile, target_config)
    validation = validate_qe_ic_target_viability(report)
    _write_json(out_dir / QE_IC_TARGET_VIABILITY_VALIDATION_ARTIFACT, validation)
    if validation["status"] != "passed":
        return {
            "status": validation["status"],
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_TARGET_VIABILITY_VALIDATION_ARTIFACT],
        }

    manifest = build_qe_ic_target_viability_manifest()
    readme = build_qe_ic_target_viability_readme(report)
    _write_json(out_dir / QE_IC_TARGET_VIABILITY_ARTIFACT, report)
    _write_json(out_dir / QE_IC_TARGET_VIABILITY_MANIFEST_ARTIFACT, manifest)
    (out_dir / QE_IC_TARGET_VIABILITY_README_ARTIFACT).write_text(readme)

    return {
        "status": validation["status"],
        "out_dir": str(out_dir),
        "artifacts": list(QE_IC_TARGET_VIABILITY_ARTIFACTS),
    }


def load_qe_ic_target_viability(path: Path) -> dict[str, Any]:
    """Load and validate persisted target viability report."""

    payload = _load_json_object(path)
    validation = validate_qe_ic_target_viability(payload)
    if validation["status"] != "passed":
        raise QeIcTargetViabilityArtifactError(
            f"{path} failed QE-IC target-viability validation: {validation['errors']}"
        )
    return payload
