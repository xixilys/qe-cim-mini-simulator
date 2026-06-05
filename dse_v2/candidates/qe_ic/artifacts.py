#!/usr/bin/env python3
"""Artifact I/O for QE-IC Layer-4 candidate plans."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.candidates.qe_ic.plan import (
    build_qe_ic_candidate_plan,
    validate_qe_ic_candidate_plan_inputs,
)
from dse_v2.candidates.qe_ic.schema import (
    DOWNSTREAM_CONSUMERS,
    LAYER_NAME,
    MANIFEST_CLAIM_BOUNDARY,
    PRODUCER,
    QE_IC_CANDIDATE_PLAN_ARTIFACT,
    QE_IC_CANDIDATE_PLAN_ARTIFACTS,
    QE_IC_CANDIDATE_PLAN_MANIFEST_ARTIFACT,
    QE_IC_CANDIDATE_PLAN_MANIFEST_SCHEMA_VERSION,
    QE_IC_CANDIDATE_PLAN_README_ARTIFACT,
    QE_IC_CANDIDATE_PLAN_VALIDATION_ARTIFACT,
    QE_IC_CANDIDATE_PLAN_VALIDATION_SCHEMA_VERSION,
)
from dse_v2.candidates.qe_ic.validation import validate_qe_ic_candidate_plan


class QeIcCandidatePlanArtifactError(ValueError):
    """Raised when persisted QE-IC candidate-plan artifacts fail validation."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open() as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise QeIcCandidatePlanArtifactError(f"{path} does not exist") from exc
    if not isinstance(payload, dict):
        raise QeIcCandidatePlanArtifactError(f"{path} did not contain a JSON object")
    return payload


def _remove_stale_canonical_artifacts(out_dir: Path) -> None:
    for artifact_name in (
        QE_IC_CANDIDATE_PLAN_ARTIFACT,
        QE_IC_CANDIDATE_PLAN_MANIFEST_ARTIFACT,
        QE_IC_CANDIDATE_PLAN_README_ARTIFACT,
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
        "schema_version": QE_IC_CANDIDATE_PLAN_VALIDATION_SCHEMA_VERSION,
        "status": "failed",
        "errors": errors,
        "warnings": warnings or [],
        "candidate_count": 0,
        "promotion_decision_count": 0,
        "evaluation_request_count": 0,
    }


def build_qe_ic_candidate_plan_manifest() -> dict[str, Any]:
    """Build the QE-IC Layer-4 candidate-plan artifact manifest."""

    return {
        "schema_version": QE_IC_CANDIDATE_PLAN_MANIFEST_SCHEMA_VERSION,
        "artifact_role": "dse_layer4_candidate_plan",
        "candidate_plan_artifact": QE_IC_CANDIDATE_PLAN_ARTIFACT,
        "validation_artifact": QE_IC_CANDIDATE_PLAN_VALIDATION_ARTIFACT,
        "readme_artifact": QE_IC_CANDIDATE_PLAN_README_ARTIFACT,
        "producer": PRODUCER,
        "layer": LAYER_NAME,
        "downstream_consumers": list(DOWNSTREAM_CONSUMERS),
        "claim_boundary": MANIFEST_CLAIM_BOUNDARY,
    }


def build_qe_ic_candidate_plan_readme(plan: Mapping[str, Any]) -> str:
    """Build README text shipped beside generated Layer-4 artifacts."""

    summary = plan.get("summary") if isinstance(plan.get("summary"), Mapping) else {}
    diversity = summary.get("diversity") if isinstance(summary.get("diversity"), Mapping) else {}
    budget_used = summary.get("budget_used") if isinstance(summary.get("budget_used"), Mapping) else {}
    budget_limits = summary.get("budget_limits") if isinstance(summary.get("budget_limits"), Mapping) else {}
    by_target_lines: list[str] = []
    by_target_type = summary.get("by_target_type") if isinstance(summary.get("by_target_type"), Mapping) else {}
    for target_type, row in sorted(by_target_type.items()):
        if isinstance(row, Mapping):
            by_target_lines.append(
                f"- `{target_type}`: candidates={row.get('candidate_count')}, "
                f"baseline={row.get('baseline_count')}, promote={row.get('promote_count')}, "
                f"hold={row.get('hold_count')}, reject={row.get('reject_count')}."
            )

    return "\n".join(
        [
            "# QE-IC Candidate Plan v1",
            "",
            "## Layer-4 Role",
            "",
            "Layer-4 is the first QE-IC layer that turns workload, motif, and "
            "target-viability analysis into DSE decisions. It generates candidate "
            "design specifications, promotion decisions, and planned next-fidelity "
            "evaluation requests for later runners.",
            "",
            "## Candidate Generation Boundary",
            "",
            "Candidates are generated from Layer-3 viability records and a template "
            "registry. GPU-only records produce baseline reference candidates. Reject "
            "records do not produce accelerator candidates. Maybe and viable records "
            "can produce FPGA-only or GPU+FPGA hybrid candidates when the campaign "
            "allows the target type and template family.",
            "",
            "## Promotion Policy Boundary",
            "",
            "The default policy is deterministic and modular. It extracts features "
            "from candidates and source viability records, scores them with explicit "
            "weights, applies budget and diversity filters, and assigns reason codes. "
            "The policy is a planning rule, not a final performance adjudicator.",
            "",
            "## Budget Constraints",
            "",
            f"L1 cost-model requests used: {budget_used.get('max_l1_cost_model_requests')} "
            f"of {budget_limits.get('max_l1_cost_model_requests')}. SystemC, gem5, "
            "Vivado, DC, and real-QE request budgets are zero in this Layer-4 artifact.",
            "",
            "## Diversity Logic",
            "",
            f"Target-type diversity required: {diversity.get('target_type_required')}. "
            f"Motif diversity required: {diversity.get('motif_required')}. "
            f"Promoted target types: {', '.join(diversity.get('promoted_target_types', []))}. "
            f"Promoted motifs: {', '.join(diversity.get('promoted_motifs', []))}.",
            "",
            "## Summary",
            "",
            f"Candidates: {summary.get('candidate_count')}; baseline={summary.get('baseline_count')}; "
            f"promote={summary.get('promote_count')}; hold={summary.get('hold_count')}; "
            f"reject={summary.get('reject_count')}; evaluation requests={summary.get('evaluation_request_count')}.",
            "",
            *by_target_lines,
            "",
            "## Offline Replay Validation Meaning",
            "",
            "Synthetic replay labels can be used to check whether a promotion policy "
            "avoids obvious false promotions and reports wasted-budget and precision "
            "metrics. Those labels are controlled test fixtures only. They are not "
            "real QE, FPGA, GPU, or hardware evidence.",
            "",
            "## Claim Boundary",
            "",
            str(plan.get("claim_boundary")),
            "",
            "No execution results are included. No SystemC, gem5, Vivado, DC, real QE, "
            "RTL, or HLS tool was run by Layer-4. No final performance, PPA, FPGA, "
            "GPU, or GPU+FPGA superiority claim is made by this artifact.",
            "",
        ]
    )


def write_qe_ic_candidate_plan_artifacts(
    out_dir: Path,
    suite_path: Path,
    motif_profile_path: Path,
    target_viability_path: Path,
    campaign_config_path: Path,
) -> dict[str, Any]:
    """Write candidate plan, validation, manifest, and README artifacts."""

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        suite = _load_json_object(suite_path)
        motif_profile = _load_json_object(motif_profile_path)
        target_viability = _load_json_object(target_viability_path)
        campaign_config = _load_json_object(campaign_config_path)
    except QeIcCandidatePlanArtifactError as exc:
        _remove_stale_canonical_artifacts(out_dir)
        validation = _failed_validation(errors=[{"field": "input", "message": str(exc)}])
        _write_json(out_dir / QE_IC_CANDIDATE_PLAN_VALIDATION_ARTIFACT, validation)
        return {
            "status": "failed",
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_CANDIDATE_PLAN_VALIDATION_ARTIFACT],
        }

    input_validation = validate_qe_ic_candidate_plan_inputs(
        suite,
        motif_profile,
        target_viability,
        campaign_config,
    )
    _remove_stale_canonical_artifacts(out_dir)
    if input_validation["status"] != "passed":
        validation = _failed_validation(
            errors=list(input_validation["errors"]),
            warnings=list(input_validation["warnings"]),
        )
        _write_json(out_dir / QE_IC_CANDIDATE_PLAN_VALIDATION_ARTIFACT, validation)
        return {
            "status": "failed",
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_CANDIDATE_PLAN_VALIDATION_ARTIFACT],
        }

    plan = build_qe_ic_candidate_plan(
        suite,
        motif_profile,
        target_viability,
        campaign_config,
    )
    validation = validate_qe_ic_candidate_plan(plan)
    _write_json(out_dir / QE_IC_CANDIDATE_PLAN_VALIDATION_ARTIFACT, validation)
    if validation["status"] != "passed":
        return {
            "status": validation["status"],
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_CANDIDATE_PLAN_VALIDATION_ARTIFACT],
        }

    manifest = build_qe_ic_candidate_plan_manifest()
    readme = build_qe_ic_candidate_plan_readme(plan)
    _write_json(out_dir / QE_IC_CANDIDATE_PLAN_ARTIFACT, plan)
    _write_json(out_dir / QE_IC_CANDIDATE_PLAN_MANIFEST_ARTIFACT, manifest)
    (out_dir / QE_IC_CANDIDATE_PLAN_README_ARTIFACT).write_text(readme)

    return {
        "status": validation["status"],
        "out_dir": str(out_dir),
        "artifacts": list(QE_IC_CANDIDATE_PLAN_ARTIFACTS),
    }


def load_qe_ic_candidate_plan(path: Path) -> dict[str, Any]:
    """Load and validate a persisted QE-IC Layer-4 candidate plan."""

    payload = _load_json_object(path)
    validation = validate_qe_ic_candidate_plan(payload)
    if validation["status"] != "passed":
        raise QeIcCandidatePlanArtifactError(
            f"{path} failed QE-IC candidate-plan validation: {validation['errors']}"
        )
    return payload

