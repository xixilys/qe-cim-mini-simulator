#!/usr/bin/env python3
"""Artifact I/O for QE-IC Layer-5A L1 cost-model results."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.evaluation.qe_ic.l1_cost_model.runner import (
    run_qe_ic_l1_cost_model,
    validate_qe_ic_l1_cost_model_inputs,
)
from dse_v2.evaluation.qe_ic.l1_cost_model.schema import (
    DOWNSTREAM_CONSUMERS,
    LAYER_NAME,
    MANIFEST_CLAIM_BOUNDARY,
    PRODUCER,
    QE_IC_L1_COST_MODEL_ARTIFACTS,
    QE_IC_L1_COST_MODEL_MANIFEST_ARTIFACT,
    QE_IC_L1_COST_MODEL_MANIFEST_SCHEMA_VERSION,
    QE_IC_L1_COST_MODEL_README_ARTIFACT,
    QE_IC_L1_COST_MODEL_RESULTS_ARTIFACT,
    QE_IC_L1_COST_MODEL_VALIDATION_ARTIFACT,
    QE_IC_L1_COST_MODEL_VALIDATION_SCHEMA_VERSION,
)
from dse_v2.evaluation.qe_ic.l1_cost_model.validation import validate_qe_ic_l1_cost_model_results


class QeIcL1CostModelArtifactError(ValueError):
    """Raised when persisted QE-IC L1 cost-model artifacts fail validation."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open() as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise QeIcL1CostModelArtifactError(f"{path} does not exist") from exc
    if not isinstance(payload, dict):
        raise QeIcL1CostModelArtifactError(f"{path} did not contain a JSON object")
    return payload


def _remove_stale_canonical_artifacts(out_dir: Path) -> None:
    for artifact_name in (
        QE_IC_L1_COST_MODEL_RESULTS_ARTIFACT,
        QE_IC_L1_COST_MODEL_MANIFEST_ARTIFACT,
        QE_IC_L1_COST_MODEL_README_ARTIFACT,
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
        "schema_version": QE_IC_L1_COST_MODEL_VALIDATION_SCHEMA_VERSION,
        "status": "failed",
        "errors": errors,
        "warnings": warnings or [],
        "result_count": 0,
    }


def build_qe_ic_l1_cost_model_manifest() -> dict[str, Any]:
    """Build the QE-IC Layer-5A L1 cost-model artifact manifest."""

    return {
        "schema_version": QE_IC_L1_COST_MODEL_MANIFEST_SCHEMA_VERSION,
        "artifact_role": "dse_layer5a_l1_cost_model_results",
        "results_artifact": QE_IC_L1_COST_MODEL_RESULTS_ARTIFACT,
        "validation_artifact": QE_IC_L1_COST_MODEL_VALIDATION_ARTIFACT,
        "readme_artifact": QE_IC_L1_COST_MODEL_README_ARTIFACT,
        "producer": PRODUCER,
        "layer": LAYER_NAME,
        "downstream_consumers": list(DOWNSTREAM_CONSUMERS),
        "claim_boundary": MANIFEST_CLAIM_BOUNDARY,
    }


def build_qe_ic_l1_cost_model_readme(results: Mapping[str, Any]) -> str:
    """Build README text shipped beside generated Layer-5A artifacts."""

    summary = results.get("summary") if isinstance(results.get("summary"), Mapping) else {}
    model_config = results.get("model_config") if isinstance(results.get("model_config"), Mapping) else {}
    calibration = model_config.get("calibration") if isinstance(model_config.get("calibration"), Mapping) else {}
    by_target_lines: list[str] = []
    by_target_type = summary.get("by_target_type") if isinstance(summary.get("by_target_type"), Mapping) else {}
    for target_type, row in sorted(by_target_type.items()):
        if isinstance(row, Mapping):
            by_target_lines.append(
                f"- `{target_type}`: requests={row.get('request_count')}, "
                f"completed={row.get('completed_estimate_count')}, "
                f"failed={row.get('failed_estimate_count')}."
            )

    by_suggestion_lines: list[str] = []
    by_suggestion = summary.get("by_suggestion") if isinstance(summary.get("by_suggestion"), Mapping) else {}
    for suggestion, count in sorted(by_suggestion.items()):
        by_suggestion_lines.append(f"- `{suggestion}`: {count}.")

    return "\n".join(
        [
            "# QE-IC L1 Cost Model v1",
            "",
            "## Layer-5A Role",
            "",
            "Layer-5A consumes the Layer-4 QE-IC candidate plan and executes only "
            "planned `L1_cost_model` evaluation requests. It produces deterministic "
            "analytical estimates for promoted non-baseline FPGA-only and GPU+FPGA "
            "hybrid candidates.",
            "",
            "## Analytical Estimate Meaning",
            "",
            "An L1 cost-model result is a lightweight model estimate built from the "
            "candidate spec, template parameters, motif profile, target viability "
            "record, and promotion evidence. It estimates runtime, transfer, memory, "
            "communication, resource pressure, confidence, and risk. These estimates "
            "are not measured performance.",
            "",
            "## Inputs Consumed",
            "",
            f"- Layer-1 suite artifact: `{results.get('source_layer1_suite_artifact')}`.",
            f"- Layer-2 motif profile artifact: `{results.get('source_layer2_motif_profile_artifact')}`.",
            f"- Layer-3 target viability artifact: `{results.get('source_layer3_target_viability_artifact')}`.",
            f"- Layer-4 candidate plan artifact: `{results.get('source_layer4_candidate_plan_artifact')}`.",
            f"- Model config: `{model_config.get('config_id')}`.",
            "",
            "## What Was Executed",
            "",
            f"Layer-5A evaluated {summary.get('request_count')} planned L1 cost-model "
            f"requests. Completed estimates: {summary.get('completed_estimate_count')}; "
            f"failed estimates: {summary.get('failed_estimate_count')}. Baseline "
            "candidates are carried only as reference metadata and do not receive "
            "accelerator L1 result records.",
            "",
            *by_target_lines,
            "",
            "## Next-Fidelity Suggestions",
            "",
            "Suggestions are advisory `next_fidelity_suggestion` values for later "
            "request builders. They are not final promotion decisions and do not "
            "adjudicate FPGA, GPU, or hybrid superiority.",
            "",
            *by_suggestion_lines,
            "",
            "## Model Boundary",
            "",
            "The model is deterministic and local. It does not use randomness, "
            "network calls, hidden measurements, or external hardware-tool outputs. "
            "It does not run SystemC, gem5, Vivado, DC, real QE, HLS, RTL simulation, "
            "or any other high-fidelity execution path.",
            "",
            "## Calibration Status",
            "",
            f"Calibration status: `{calibration.get('calibration_status')}`. "
            f"Calibration source: `{calibration.get('calibration_source')}`. "
            f"Future high-fidelity calibration required: "
            f"{calibration.get('requires_future_high_fidelity_calibration')}.",
            "",
            "## Claim Boundary",
            "",
            str(results.get("claim_boundary")),
            "",
            "No SystemC/gem5/Vivado/DC/QE execution results are included. No HLS, RTL, "
            "FPGA, ASIC, or real-QE tool result is included. No final performance, "
            "PPA, FPGA, GPU, or GPU+FPGA superiority claim is made by this artifact.",
            "",
        ]
    )


def write_qe_ic_l1_cost_model_artifacts(
    out_dir: Path,
    suite_path: Path,
    motif_profile_path: Path,
    target_viability_path: Path,
    candidate_plan_path: Path,
    model_config_path: Path,
) -> dict[str, Any]:
    """Write L1 cost-model results, validation, manifest, and README artifacts."""

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        suite = _load_json_object(suite_path)
        motif_profile = _load_json_object(motif_profile_path)
        target_viability = _load_json_object(target_viability_path)
        candidate_plan = _load_json_object(candidate_plan_path)
        model_config = _load_json_object(model_config_path)
    except QeIcL1CostModelArtifactError as exc:
        _remove_stale_canonical_artifacts(out_dir)
        validation = _failed_validation(errors=[{"field": "input", "message": str(exc)}])
        _write_json(out_dir / QE_IC_L1_COST_MODEL_VALIDATION_ARTIFACT, validation)
        return {
            "status": "failed",
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_L1_COST_MODEL_VALIDATION_ARTIFACT],
        }

    input_validation = validate_qe_ic_l1_cost_model_inputs(
        suite,
        motif_profile,
        target_viability,
        candidate_plan,
        model_config,
    )
    _remove_stale_canonical_artifacts(out_dir)
    if input_validation["status"] != "passed":
        validation = _failed_validation(
            errors=list(input_validation["errors"]),
            warnings=list(input_validation["warnings"]),
        )
        _write_json(out_dir / QE_IC_L1_COST_MODEL_VALIDATION_ARTIFACT, validation)
        return {
            "status": "failed",
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_L1_COST_MODEL_VALIDATION_ARTIFACT],
        }

    results = run_qe_ic_l1_cost_model(
        suite,
        motif_profile,
        target_viability,
        candidate_plan,
        model_config,
    )
    validation = validate_qe_ic_l1_cost_model_results(results)
    _write_json(out_dir / QE_IC_L1_COST_MODEL_VALIDATION_ARTIFACT, validation)
    if validation["status"] != "passed":
        return {
            "status": validation["status"],
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_L1_COST_MODEL_VALIDATION_ARTIFACT],
        }

    manifest = build_qe_ic_l1_cost_model_manifest()
    readme = build_qe_ic_l1_cost_model_readme(results)
    _write_json(out_dir / QE_IC_L1_COST_MODEL_RESULTS_ARTIFACT, results)
    _write_json(out_dir / QE_IC_L1_COST_MODEL_MANIFEST_ARTIFACT, manifest)
    (out_dir / QE_IC_L1_COST_MODEL_README_ARTIFACT).write_text(readme)

    return {
        "status": validation["status"],
        "out_dir": str(out_dir),
        "artifacts": list(QE_IC_L1_COST_MODEL_ARTIFACTS),
    }


def load_qe_ic_l1_cost_model_results(path: Path) -> dict[str, Any]:
    """Load and validate persisted QE-IC Layer-5A L1 cost-model results."""

    payload = _load_json_object(path)
    validation = validate_qe_ic_l1_cost_model_results(payload)
    if validation["status"] != "passed":
        raise QeIcL1CostModelArtifactError(
            f"{path} failed QE-IC L1 cost-model validation: {validation['errors']}"
        )
    return payload
