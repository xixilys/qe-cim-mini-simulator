#!/usr/bin/env python3
"""Conservative deployment-objective producer for DFT/QE release decisions.

The selector requires an explicit objective before it may choose a target or
candidate.  This producer provides a mechanically auditable default objective
for release-lane closure work: it makes the objective explicit while preserving
all physical ties and avoiding candidate-id, architecture-label, or Step2-score
tie breakers.  It is intentionally non-upgrading; insufficient PPA evidence
still blocks the selector.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.reference_workloads.dft_deployment_selector import DFT_DEPLOYMENT_OBJECTIVE_SCHEMA


DFT_DEPLOYMENT_OBJECTIVE_VALIDATION_SCHEMA = "dse.dft.deployment_objective_validation.v1"
DFT_DEPLOYMENT_OBJECTIVE_PRODUCER_STATUS_SCHEMA = "dse.dft.deployment_objective_status.v1"

_CLAIM_BOUNDARY = (
    "This deployment objective is an explicit, conservative selector input. "
    "It assigns equal normalized target priors so FPGA-vs-ASIC ties remain "
    "blocked until real target-specific PPA and a non-neutral user/release "
    "cost model exist. It must not be used as deployment-winner evidence."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_ref(path: Path | None, *, required: bool = False) -> Dict[str, Any]:
    if path is None:
        return {"path": None, "required": required, "exists": False, "sha256": None, "hash_algorithm": "sha256"}
    candidate = Path(path)
    exists = candidate.exists() and candidate.is_file()
    return {
        "path": str(candidate),
        "required": required,
        "exists": exists,
        "sha256": sha256_file(candidate) if exists else None,
        "hash_algorithm": "sha256",
    }


def build_conservative_dft_deployment_objective(
    *,
    objective_id: str = "evidence-first-neutral-cross-target-v1",
    goal_path: Path | None = None,
    barrier_path: Path | None = None,
    prior_status_path: Path | None = None,
) -> Dict[str, Any]:
    """Return a fail-closed explicit objective for selector replay.

    Equal FPGA/ASIC normalized scores are deliberate: they remove the previous
    "missing objective" blocker but do not invent a cross-target preference.
    If both target recommendations become available, the selector must still
    preserve the objective tie.  If either target recommendation is missing, it
    blocks on the missing recommendation instead.
    """

    return {
        "schema_version": DFT_DEPLOYMENT_OBJECTIVE_SCHEMA,
        "generated_at": _now_iso(),
        "objective_id": objective_id,
        "status": "conservative_explicit_objective_available",
        "objective_kind": "fail_closed_neutral_cross_target",
        "deployment_target": "cross_target",
        "target_score_direction": "min",
        "target_score_normalization": "unitless_equal_target_prior_preserves_cross_target_ties",
        "target_scores": {"fpga": 1.0, "asic": 1.0},
        "selection_metrics": [],
        "constraints": [],
        "tie_policy": "preserve_physical_ties",
        "allow_non_physical_tie_breakers": False,
        "selection_upgrade_allowed": False,
        "evidence_requirements": {
            "fpga": [
                "golden_correctness",
                "hls_or_rtl_sim",
                "hls_or_rtl_synth",
                "vivado_fpga_synth_or_impl",
            ],
            "asic": [
                "golden_correctness",
                "hls_or_rtl_sim",
                "hls_or_rtl_synth",
                "dc_asic_synth_timing_area",
            ],
            "system_level": [
                "strict_six_class_real_qe_reference_hashes",
                "full_scf_evaluated_hybrid_runtime_accounting",
                "release_universe_candidate_identity_binding",
            ],
        },
        "source_artifacts": {
            "goal": _source_ref(goal_path),
            "barrier": _source_ref(barrier_path),
            "prior_status": _source_ref(prior_status_path),
        },
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_deployment_objective(payload: Mapping[str, Any]) -> Dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema_version") != DFT_DEPLOYMENT_OBJECTIVE_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("deployment_objective_must_not_mark_deliverable_complete")
    if payload.get("trusted_final_claim") is True:
        errors.append("deployment_objective_must_not_mark_trusted_final_claim")
    if payload.get("deployment_target") != "cross_target":
        errors.append("conservative_objective_must_be_cross_target")
    if payload.get("target_score_direction") != "min":
        errors.append("conservative_objective_target_score_direction_must_be_min")
    scores = payload.get("target_scores")
    if not isinstance(scores, Mapping):
        errors.append("target_scores_missing")
    else:
        fpga = scores.get("fpga")
        asic = scores.get("asic")
        if not isinstance(fpga, (int, float)) or not isinstance(asic, (int, float)):
            errors.append("target_scores_must_be_numeric")
        elif float(fpga) != float(asic):
            errors.append("conservative_objective_must_preserve_cross_target_tie")
    if not payload.get("target_score_normalization"):
        errors.append("target_score_normalization_required")
    if payload.get("tie_policy") != "preserve_physical_ties":
        errors.append("tie_policy_must_preserve_physical_ties")
    if payload.get("allow_non_physical_tie_breakers") is not False:
        errors.append("non_physical_tie_breakers_forbidden")
    if payload.get("selection_upgrade_allowed") is not False:
        errors.append("selection_upgrade_must_be_false")
    return {
        "schema_version": DFT_DEPLOYMENT_OBJECTIVE_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_conservative_dft_deployment_objective(
    out_dir: Path,
    *,
    objective_id: str = "evidence-first-neutral-cross-target-v1",
    goal_path: Path | None = None,
    barrier_path: Path | None = None,
    prior_status_path: Path | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    objective = build_conservative_dft_deployment_objective(
        objective_id=objective_id,
        goal_path=goal_path,
        barrier_path=barrier_path,
        prior_status_path=prior_status_path,
    )
    validation = validate_dft_deployment_objective(objective)
    write_json(out_dir / "dft_deployment_objective.json", objective)
    write_json(out_dir / "dft_deployment_objective_validation.json", validation)
    status = {
        "schema_version": DFT_DEPLOYMENT_OBJECTIVE_PRODUCER_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "objective": "dft_deployment_objective.json",
        "validation": "dft_deployment_objective_validation.json",
        "objective_present": True,
        "objective_id": objective.get("objective_id"),
        "deployment_target": objective.get("deployment_target"),
        "target_score_normalization": objective.get("target_score_normalization"),
        "selection_upgrade_allowed": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_deployment_objective_status.json", status)
    return status


__all__ = [
    "DFT_DEPLOYMENT_OBJECTIVE_PRODUCER_STATUS_SCHEMA",
    "DFT_DEPLOYMENT_OBJECTIVE_VALIDATION_SCHEMA",
    "build_conservative_dft_deployment_objective",
    "validate_dft_deployment_objective",
    "write_conservative_dft_deployment_objective",
]
