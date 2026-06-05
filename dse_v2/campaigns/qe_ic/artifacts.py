#!/usr/bin/env python3
"""Artifact I/O for the QE-IC closed-loop DSE campaign."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.campaigns.qe_ic.runner import QeIcClosedLoopCampaignError, run_qe_ic_closed_loop_dse_campaign
from dse_v2.campaigns.qe_ic.schema import (
    MANIFEST_CLAIM_BOUNDARY,
    PRODUCER,
    QE_IC_CLOSED_LOOP_ARTIFACTS,
    QE_IC_CLOSED_LOOP_MANIFEST_ARTIFACT,
    QE_IC_CLOSED_LOOP_MANIFEST_SCHEMA_VERSION,
    QE_IC_CLOSED_LOOP_README_ARTIFACT,
    QE_IC_CLOSED_LOOP_RESULTS_ARTIFACT,
    QE_IC_CLOSED_LOOP_VALIDATION_ARTIFACT,
    QE_IC_CLOSED_LOOP_VALIDATION_SCHEMA_VERSION,
    REQUIRED_LAYERS,
)
from dse_v2.campaigns.qe_ic.validation import validate_qe_ic_closed_loop_dse_results


class QeIcClosedLoopArtifactError(ValueError):
    """Raised when persisted QE-IC closed-loop artifacts fail validation."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open() as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise QeIcClosedLoopArtifactError(f"{path} does not exist") from exc
    if not isinstance(payload, dict):
        raise QeIcClosedLoopArtifactError(f"{path} did not contain a JSON object")
    return payload


def _remove_stale_canonical_artifacts(out_dir: Path) -> None:
    for artifact_name in (
        QE_IC_CLOSED_LOOP_RESULTS_ARTIFACT,
        QE_IC_CLOSED_LOOP_MANIFEST_ARTIFACT,
        QE_IC_CLOSED_LOOP_README_ARTIFACT,
    ):
        artifact_path = out_dir / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()


def _failed_validation(errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": QE_IC_CLOSED_LOOP_VALIDATION_SCHEMA_VERSION,
        "status": "failed",
        "errors": errors,
        "warnings": [],
        "candidate_trajectory_count": 0,
        "layer_count": 0,
        "stop_decision": None,
    }


def build_qe_ic_closed_loop_dse_manifest(results: Mapping[str, Any]) -> dict[str, Any]:
    """Build the closed-loop campaign manifest."""

    return {
        "schema_version": QE_IC_CLOSED_LOOP_MANIFEST_SCHEMA_VERSION,
        "artifact_role": "dse_system_qe_ic_closed_loop_dse",
        "results_artifact": QE_IC_CLOSED_LOOP_RESULTS_ARTIFACT,
        "validation_artifact": QE_IC_CLOSED_LOOP_VALIDATION_ARTIFACT,
        "readme_artifact": QE_IC_CLOSED_LOOP_README_ARTIFACT,
        "producer": PRODUCER,
        "layers": list(REQUIRED_LAYERS),
        "artifact_index": dict(results.get("artifact_index", {})),
        "claim_boundary": MANIFEST_CLAIM_BOUNDARY,
    }


def build_qe_ic_closed_loop_dse_readme(results: Mapping[str, Any]) -> str:
    """Build README text for closed-loop campaign artifacts."""

    summary = results.get("system_summary") if isinstance(results.get("system_summary"), Mapping) else {}
    return "\n".join(
        [
            "# QE-IC Closed-Loop DSE Campaign v1",
            "",
            "## System Goal",
            "",
            "This artifact bundle connects the QE-IC Layer-1 workload suite through "
            "Layer-6 synthetic feedback calibration. It asks whether a budgeted DSE "
            "loop can reduce false promotions and improve next-round candidate "
            "selection under a fixed synthetic replay budget.",
            "",
            "## Result Summary",
            "",
            f"- Candidates: {summary.get('candidate_count')}.",
            f"- Promoted by Layer-4: {summary.get('promoted_candidate_count')}.",
            f"- L1 analytical result count: {summary.get('l1_result_count')}.",
            f"- Synthetic labels replayed: {summary.get('synthetic_label_count')}.",
            f"- Useful synthetic candidates: {summary.get('useful_candidate_count')}.",
            f"- False promotions: {summary.get('false_promotion_count')}.",
            f"- Promotion precision: {summary.get('promotion_precision')}.",
            f"- Wasted budget ratio: {summary.get('wasted_budget_ratio')}.",
            f"- Synthetic stop decision: {summary.get('stop_decision')}.",
            "",
            "## Layer-6 Synthetic Feedback",
            "",
            "Layer-6 synthetic feedback compares L1 estimates and Layer-4 promotion "
            "decisions with replay labels, then emits adaptive policy state and a "
            "next-round plan. This is not measured hardware performance.",
            "",
            "## Claim Boundary",
            "",
            str(results.get("claim_boundary")),
            "",
            "The bundle does not prove FPGA is faster than GPU, does not prove "
            "GPU+FPGA is faster than GPU, and does not include final PPA or "
            "hardware-proven candidate claims.",
            "",
        ]
    )


def write_qe_ic_closed_loop_dse_artifacts(
    out_dir: Path,
    campaign_config_path: Path,
) -> dict[str, Any]:
    """Write closed-loop results, validation, manifest, and README artifacts."""

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        config = _load_json_object(campaign_config_path)
        results = run_qe_ic_closed_loop_dse_campaign(config)
        validation = validate_qe_ic_closed_loop_dse_results(results)
    except (QeIcClosedLoopArtifactError, QeIcClosedLoopCampaignError) as exc:
        _remove_stale_canonical_artifacts(out_dir)
        validation = _failed_validation(errors=[{"field": "input", "message": str(exc)}])
        _write_json(out_dir / QE_IC_CLOSED_LOOP_VALIDATION_ARTIFACT, validation)
        return {
            "status": "failed",
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_CLOSED_LOOP_VALIDATION_ARTIFACT],
        }

    _remove_stale_canonical_artifacts(out_dir)
    _write_json(out_dir / QE_IC_CLOSED_LOOP_VALIDATION_ARTIFACT, validation)
    if validation["status"] != "passed":
        return {
            "status": validation["status"],
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_CLOSED_LOOP_VALIDATION_ARTIFACT],
        }

    manifest = build_qe_ic_closed_loop_dse_manifest(results)
    readme = build_qe_ic_closed_loop_dse_readme(results)
    _write_json(out_dir / QE_IC_CLOSED_LOOP_RESULTS_ARTIFACT, results)
    _write_json(out_dir / QE_IC_CLOSED_LOOP_MANIFEST_ARTIFACT, manifest)
    (out_dir / QE_IC_CLOSED_LOOP_README_ARTIFACT).write_text(readme)
    return {
        "status": validation["status"],
        "out_dir": str(out_dir),
        "artifacts": list(QE_IC_CLOSED_LOOP_ARTIFACTS),
    }


def load_qe_ic_closed_loop_dse_results(path: Path) -> dict[str, Any]:
    """Load and validate persisted QE-IC closed-loop campaign results."""

    payload = _load_json_object(path)
    validation = validate_qe_ic_closed_loop_dse_results(payload)
    if validation["status"] != "passed":
        raise QeIcClosedLoopArtifactError(
            f"{path} failed QE-IC closed-loop campaign validation: {validation['errors']}"
        )
    return payload
