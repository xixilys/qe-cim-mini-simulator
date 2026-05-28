#!/usr/bin/env python3
"""Objective-driven deployment selector for DFT/QE hardware DSE.

The selector is deliberately narrower than the deployment comparator.  The
comparator can report target-scoped recommendation sets without a user
objective; this selector may pick a deployment target or candidate only when an
explicit objective/cost model is supplied and the objective produces a unique
best physical score.  It must not collapse a physical tie by candidate id,
architecture label, Step2 score, or any other non-physical side channel.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.reference_workloads.dft_deployment_comparator import (
    DFT_DEPLOYMENT_COMPARATOR_SCHEMA,
)


DFT_DEPLOYMENT_SELECTOR_SCHEMA = "dse.dft.deployment_selector.v1"
DFT_DEPLOYMENT_SELECTOR_VALIDATION_SCHEMA = "dse.dft.deployment_selector_validation.v1"
DFT_DEPLOYMENT_SELECTOR_STATUS_SCHEMA = "dse.dft.deployment_selector_status.v1"
DFT_DEPLOYMENT_OBJECTIVE_SCHEMA = "dse.dft.deployment_objective.v1"

_CLAIM_BOUNDARY = (
    "Deployment selector is an explicit-objective hardware-PPA selection aid. "
    "It can select a target or candidate only when a supplied objective/cost "
    "model gives a unique best physical score; it does not mark full-SCF "
    "deliverable completion or convert unresolved physical ties into winners."
)

_FORBIDDEN_TIE_BREAKERS = [
    "candidate_id_order",
    "step2_design_score",
    "architecture_family_label",
    "candidate_metadata_sidecar",
    "single_candidate_full_scf_bundle",
]
_FORBIDDEN_OBJECTIVE_FIELDS = set(_FORBIDDEN_TIE_BREAKERS) | {
    "candidate_id",
    "candidate_id_order",
    "design_candidate_id",
    "architecture_id",
    "architecture_family",
    "architecture_label",
    "step2_score",
    "step2_design_score",
    "design_score",
    "metadata_sidecar",
}

_ALLOWED_TARGETS = {"fpga", "asic", "cross_target", "any", "auto"}
_ALLOWED_DIRECTIONS = {"min", "max"}
_ALLOWED_CONSTRAINT_OPS = {"<=", ">=", "==", "<", ">"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path, *, required: bool = True) -> Dict[str, Any]:
    path = Path(path)
    exists = path.exists() and path.is_file()
    return {
        "path": str(path),
        "required": required,
        "exists": exists,
        "sha256": sha256_file(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _selector_source_artifacts(run_dir: Path, objective_source_path: Path | None = None) -> Dict[str, Any]:
    artifacts = {
        "dft_deployment_comparator": _source_ref(run_dir / "dft_deployment_comparator.json"),
        "dft_deployment_comparator_validation": _source_ref(
            run_dir / "dft_deployment_comparator_validation.json",
            required=False,
        ),
    }
    if objective_source_path is not None:
        artifacts["deployment_objective"] = _source_ref(objective_source_path, required=False)
    return artifacts


def _discover_objective_file(run_dir: Path) -> tuple[Path | None, Dict[str, Any]]:
    candidates = [
        path
        for path in sorted(Path(run_dir).glob("dft_deployment_objective*.json"))
        if path.is_file()
    ]
    preferred = Path(run_dir) / "dft_deployment_objective.json"
    if preferred in candidates:
        candidates.remove(preferred)
        candidates.insert(0, preferred)
    for candidate in candidates:
        payload = _load_json(candidate)
        if payload.get("schema_version") == DFT_DEPLOYMENT_OBJECTIVE_SCHEMA or payload.get("objective_id"):
            return candidate, payload
    return None, {}


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list_of_mappings(value: Any) -> list[Dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _metric_value(candidate: Mapping[str, Any], metric: str) -> float | None:
    metrics = _as_mapping(candidate.get("metrics"))
    return _numeric(metrics.get(metric))


def _target_from_objective(objective: Mapping[str, Any]) -> str | None:
    target = str(objective.get("deployment_target") or objective.get("target") or "").strip().lower()
    if target == "auto":
        return "cross_target"
    return target if target in _ALLOWED_TARGETS else None


def _objective_summary(objective: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": objective.get("schema_version"),
        "objective_id": objective.get("objective_id"),
        "deployment_target": objective.get("deployment_target", objective.get("target")),
        "target_score_direction": objective.get("target_score_direction"),
        "target_scores": _as_mapping(objective.get("target_scores")),
        "selection_metrics": _as_list_of_mappings(objective.get("selection_metrics")),
        "constraints": _as_list_of_mappings(objective.get("constraints")),
        "claim_boundary": (
            "Objective fields are used only as explicit physical/cost-model "
            "selection inputs; candidate ids are reported as identities, not "
            "as tie-break ordering."
        ),
    }


def _objective_policy_blockers(objective: Mapping[str, Any]) -> list[Dict[str, Any]]:
    blockers: list[Dict[str, Any]] = []
    if objective.get("allow_non_physical_tie_breakers") is True:
        blockers.append({"blocker_id": "non_physical_tie_breaker_requested"})
    tie_policy = str(objective.get("tie_policy") or "preserve_physical_ties")
    if tie_policy not in {"preserve_physical_ties", "physical_metrics_only"}:
        blockers.append({"blocker_id": "unsupported_or_non_physical_tie_policy", "tie_policy": tie_policy})
    for field_name in ("tie_breaker", "secondary_tie_breaker"):
        value = str(objective.get(field_name) or "")
        if value in _FORBIDDEN_OBJECTIVE_FIELDS:
            blockers.append({"blocker_id": "forbidden_objective_tie_breaker", "field": field_name, "value": value})
    for item in _as_list_of_mappings(objective.get("tie_breakers")):
        value = str(item.get("metric") or item.get("field") or item.get("tie_breaker") or "")
        if value in _FORBIDDEN_OBJECTIVE_FIELDS:
            blockers.append({"blocker_id": "forbidden_objective_tie_breaker", "field": "tie_breakers", "value": value})
    for collection_name in ("selection_metrics", "constraints"):
        for item in _as_list_of_mappings(objective.get(collection_name)):
            metric = str(item.get("metric") or "")
            if metric in _FORBIDDEN_OBJECTIVE_FIELDS:
                blockers.append(
                    {
                        "blocker_id": "forbidden_objective_metric",
                        "field": collection_name,
                        "metric": metric,
                    }
                )
    target = _target_from_objective(objective)
    if target in {"cross_target", "any"} and objective.get("target_scores"):
        normalization = str(
            objective.get("target_score_normalization")
            or objective.get("normalization")
            or objective.get("target_score_units")
            or ""
        ).strip()
        if not normalization:
            blockers.append({"blocker_id": "cross_target_score_normalization_required"})
    return blockers


def _failure(
    status: str,
    blockers: Sequence[Mapping[str, Any]],
    *,
    comparator: Mapping[str, Any],
    objective: Mapping[str, Any] | None,
    run_dir: Path,
    objective_source_path: Path | None = None,
) -> Dict[str, Any]:
    objective = objective or {}
    return {
        "schema_version": DFT_DEPLOYMENT_SELECTOR_SCHEMA,
        "generated_at": _now_iso(),
        "status": status,
        "selection_status": status,
        "objective_present": bool(objective),
        "objective": _objective_summary(objective),
        "source_artifacts": _selector_source_artifacts(run_dir, objective_source_path),
        "selected_deployment_target": None,
        "selected_candidate": None,
        "selected_candidate_id": None,
        "target_selection": {},
        "candidate_selection": {},
        "comparator_status": comparator.get("status"),
        "blockers": [dict(item) for item in blockers],
        "non_physical_tie_breakers_used": False,
        "forbidden_tie_breakers": list(_FORBIDDEN_TIE_BREAKERS),
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _constraint_passes(candidate: Mapping[str, Any], constraint: Mapping[str, Any]) -> tuple[bool, str | None]:
    metric = str(constraint.get("metric") or "")
    op = str(constraint.get("op") or "")
    expected = _numeric(constraint.get("value"))
    actual = _metric_value(candidate, metric)
    if not metric:
        return False, "constraint_metric_missing"
    if op not in _ALLOWED_CONSTRAINT_OPS:
        return False, f"unsupported_constraint_op:{op or 'missing'}"
    if actual is None:
        return False, f"constraint_metric_not_numeric:{metric}"
    if expected is None:
        return False, f"constraint_value_not_numeric:{metric}"
    if op == "<=":
        return actual <= expected, None
    if op == ">=":
        return actual >= expected, None
    if op == "==":
        return actual == expected, None
    if op == "<":
        return actual < expected, None
    if op == ">":
        return actual > expected, None
    return False, f"unsupported_constraint_op:{op}"


def _candidate_score(
    candidate: Mapping[str, Any],
    selection_metrics: Sequence[Mapping[str, Any]],
) -> tuple[float, ...] | None:
    score: list[float] = []
    for item in selection_metrics:
        metric = str(item.get("metric") or "")
        direction = str(item.get("direction") or "min").lower()
        if not metric or direction not in _ALLOWED_DIRECTIONS:
            return None
        value = _metric_value(candidate, metric)
        if value is None:
            return None
        score.append(value if direction == "min" else -value)
    return tuple(score)


def _select_candidate(
    target: str,
    recommendation: Mapping[str, Any],
    objective: Mapping[str, Any],
) -> Dict[str, Any]:
    candidates = _as_list_of_mappings(recommendation.get("top_candidates"))
    unique_winner = recommendation.get("unique_winner")
    if not candidates and isinstance(unique_winner, Mapping):
        candidates = [dict(unique_winner)]
    blockers: list[Dict[str, Any]] = []
    if not candidates:
        blockers.append({"blocker_id": f"no_{target}_candidate_recommendations"})
        return {
            "status": f"blocked_no_{target}_candidate_recommendations",
            "selected_candidate": None,
            "eligible_candidate_count": 0,
            "blockers": blockers,
        }

    constraints = _as_list_of_mappings(objective.get("constraints"))
    filtered: list[Dict[str, Any]] = []
    rejected: list[Dict[str, Any]] = []
    for candidate in candidates:
        reasons: list[str] = []
        for constraint in constraints:
            passed, reason = _constraint_passes(candidate, constraint)
            if not passed:
                reasons.append(reason or "constraint_not_satisfied")
        if reasons:
            rejected.append({"candidate_id": candidate.get("candidate_id"), "reasons": reasons})
        else:
            filtered.append(candidate)
    if not filtered:
        blockers.append({"blocker_id": "all_candidates_rejected_by_objective_constraints", "rejected": rejected})
        return {
            "status": "blocked_all_candidates_rejected_by_objective_constraints",
            "selected_candidate": None,
            "eligible_candidate_count": 0,
            "rejected_candidates": rejected,
            "blockers": blockers,
        }

    selection_metrics = _as_list_of_mappings(objective.get("selection_metrics"))
    if not selection_metrics:
        if len(filtered) == 1:
            return {
                "status": f"unique_{target}_candidate_selected_by_explicit_target_objective",
                "selected_candidate": filtered[0],
                "selected_candidate_id": filtered[0].get("candidate_id"),
                "eligible_candidate_count": 1,
                "score": [],
                "selection_metrics": [],
                "rejected_candidates": rejected,
                "blockers": [],
            }
        blockers.append({"blocker_id": "objective_selection_metrics_required_for_candidate_tie"})
        return {
            "status": "blocked_objective_selection_metrics_required_for_candidate_tie",
            "selected_candidate": None,
            "eligible_candidate_count": len(filtered),
            "tie_candidate_ids": [item.get("candidate_id") for item in filtered],
            "rejected_candidates": rejected,
            "blockers": blockers,
        }

    scored: list[tuple[tuple[float, ...], Dict[str, Any]]] = []
    for candidate in filtered:
        score = _candidate_score(candidate, selection_metrics)
        if score is None:
            blockers.append(
                {
                    "blocker_id": "selection_metric_missing_or_not_numeric",
                    "candidate_id": candidate.get("candidate_id"),
                }
            )
            continue
        scored.append((score, candidate))
    if blockers:
        return {
            "status": "blocked_selection_metric_missing_or_not_numeric",
            "selected_candidate": None,
            "eligible_candidate_count": len(filtered),
            "selection_metrics": selection_metrics,
            "rejected_candidates": rejected,
            "blockers": blockers,
        }
    best_score = min(score for score, _ in scored)
    best = [candidate for score, candidate in scored if score == best_score]
    if len(best) != 1:
        return {
            "status": "objective_tie_no_unique_candidate",
            "selected_candidate": None,
            "eligible_candidate_count": len(filtered),
            "tie_candidate_ids": [item.get("candidate_id") for item in best],
            "score": list(best_score),
            "selection_metrics": selection_metrics,
            "rejected_candidates": rejected,
            "blockers": [{"blocker_id": "objective_metrics_tie_no_unique_candidate"}],
        }
    return {
        "status": "unique_candidate_selected_by_explicit_objective",
        "selected_candidate": best[0],
        "selected_candidate_id": best[0].get("candidate_id"),
        "eligible_candidate_count": len(filtered),
        "score": list(best_score),
        "selection_metrics": selection_metrics,
        "rejected_candidates": rejected,
        "blockers": [],
    }


def _select_target(
    comparator: Mapping[str, Any],
    objective: Mapping[str, Any],
) -> Dict[str, Any]:
    target = _target_from_objective(objective)
    if target in {"fpga", "asic"}:
        recommendation = _as_mapping(comparator.get(f"{target}_recommendation"))
        kind = recommendation.get("recommendation_kind")
        if kind not in {"unique_candidate", "best_physical_tie_set"}:
            return {
                "status": f"blocked_no_{target}_target_recommendation",
                "selected_target": None,
                "blockers": [{"blocker_id": f"no_{target}_target_recommendation"}],
            }
        return {
            "status": "explicit_target_selected",
            "selected_target": target,
            "target_score": None,
            "blockers": [],
        }

    scores = _as_mapping(objective.get("target_scores"))
    direction = str(objective.get("target_score_direction") or "min").lower()
    if target not in {"cross_target", "any"}:
        return {
            "status": "blocked_missing_or_unsupported_deployment_target",
            "selected_target": None,
            "blockers": [{"blocker_id": "missing_or_unsupported_deployment_target"}],
        }
    if direction not in _ALLOWED_DIRECTIONS:
        return {
            "status": "blocked_unsupported_target_score_direction",
            "selected_target": None,
            "blockers": [{"blocker_id": "unsupported_target_score_direction"}],
        }
    if not scores:
        return {
            "status": "blocked_cross_target_scores_required",
            "selected_target": None,
            "blockers": [{"blocker_id": "cross_target_scores_required_for_cross_target_selection"}],
        }

    recommendation_kinds = {
        candidate_target: _as_mapping(comparator.get(f"{candidate_target}_recommendation")).get(
            "recommendation_kind"
        )
        for candidate_target in ("fpga", "asic")
    }
    missing_recommendation_targets = [
        candidate_target
        for candidate_target, kind in recommendation_kinds.items()
        if kind not in {"unique_candidate", "best_physical_tie_set"}
    ]
    if missing_recommendation_targets:
        return {
            "status": "blocked_cross_target_requires_fpga_and_asic_recommendations",
            "selected_target": None,
            "missing_recommendation_targets": missing_recommendation_targets,
            "recommendation_kinds": recommendation_kinds,
            "blockers": [
                {
                    "blocker_id": "cross_target_requires_fpga_and_asic_recommendations",
                    "missing_recommendation_targets": missing_recommendation_targets,
                }
            ],
        }

    available_scores: list[tuple[float, str]] = []
    blockers: list[Dict[str, Any]] = []
    for candidate_target in ("fpga", "asic"):
        recommendation = _as_mapping(comparator.get(f"{candidate_target}_recommendation"))
        if recommendation.get("recommendation_kind") not in {"unique_candidate", "best_physical_tie_set"}:
            continue
        value = _numeric(scores.get(candidate_target))
        if value is None:
            blockers.append({"blocker_id": "target_score_missing_or_not_numeric", "target": candidate_target})
            continue
        available_scores.append((value if direction == "min" else -value, candidate_target))
    if blockers:
        return {
            "status": "blocked_target_score_missing_or_not_numeric",
            "selected_target": None,
            "blockers": blockers,
        }
    if not available_scores:
        return {
            "status": "blocked_no_target_scores_for_available_recommendations",
            "selected_target": None,
            "blockers": [{"blocker_id": "no_target_scores_for_available_recommendations"}],
        }
    best_score = min(score for score, _ in available_scores)
    best_targets = [target_name for score, target_name in available_scores if score == best_score]
    if len(best_targets) != 1:
        return {
            "status": "cross_target_objective_tie_no_unique_target",
            "selected_target": None,
            "tie_targets": best_targets,
            "target_score": best_score,
            "blockers": [{"blocker_id": "cross_target_objective_tie_no_unique_target"}],
        }
    return {
        "status": "unique_target_selected_by_explicit_objective",
        "selected_target": best_targets[0],
        "target_score": best_score,
        "target_score_direction": direction,
        "target_scores": scores,
        "blockers": [],
    }


def build_dft_deployment_selector(
    run_dir: Path,
    *,
    objective: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a fail-closed deployment selector payload."""

    run_dir = Path(run_dir)
    objective_source_path: Path | None = None
    if objective is None:
        objective_source_path, discovered_objective = _discover_objective_file(run_dir)
        objective = discovered_objective
    else:
        objective = dict(objective)
    comparator_path = run_dir / "dft_deployment_comparator.json"
    comparator_validation_path = run_dir / "dft_deployment_comparator_validation.json"
    comparator = _load_json(comparator_path)
    comparator_validation = _load_json(comparator_validation_path)
    if not comparator:
        return _failure(
            "blocked_missing_deployment_comparator",
            [{"blocker_id": "missing_deployment_comparator"}],
            comparator=comparator,
            objective=objective,
            run_dir=run_dir,
            objective_source_path=objective_source_path,
        )
    if comparator.get("schema_version") != DFT_DEPLOYMENT_COMPARATOR_SCHEMA:
        return _failure(
            "blocked_invalid_deployment_comparator_schema",
            [{"blocker_id": "invalid_deployment_comparator_schema"}],
            comparator=comparator,
            objective=objective,
            run_dir=run_dir,
            objective_source_path=objective_source_path,
        )
    if comparator_validation and comparator_validation.get("valid") is not True:
        return _failure(
            "blocked_invalid_deployment_comparator_validation",
            [{"blocker_id": "deployment_comparator_validation_not_valid"}],
            comparator=comparator,
            objective=objective,
            run_dir=run_dir,
            objective_source_path=objective_source_path,
        )
    if not objective:
        return _failure(
            "blocked_missing_explicit_objective",
            [{"blocker_id": "explicit_objective_required"}],
            comparator=comparator,
            objective=objective,
            run_dir=run_dir,
            objective_source_path=objective_source_path,
        )
    if objective.get("schema_version") not in {None, DFT_DEPLOYMENT_OBJECTIVE_SCHEMA}:
        return _failure(
            "blocked_invalid_objective_schema",
            [{"blocker_id": "invalid_objective_schema"}],
            comparator=comparator,
            objective=objective,
            run_dir=run_dir,
            objective_source_path=objective_source_path,
        )
    objective_blockers = _objective_policy_blockers(objective)
    if objective_blockers:
        return _failure(
            "blocked_invalid_or_non_physical_objective",
            objective_blockers,
            comparator=comparator,
            objective=objective,
            run_dir=run_dir,
            objective_source_path=objective_source_path,
        )

    target_selection = _select_target(comparator, objective)
    selected_target = target_selection.get("selected_target")
    if not selected_target:
        return _failure(
            str(target_selection.get("status") or "blocked_no_selected_target"),
            _as_list_of_mappings(target_selection.get("blockers")),
            comparator=comparator,
            objective=objective,
            run_dir=run_dir,
            objective_source_path=objective_source_path,
        ) | {
            "target_selection": target_selection,
        }

    recommendation = _as_mapping(comparator.get(f"{selected_target}_recommendation"))
    candidate_selection = _select_candidate(selected_target, recommendation, objective)
    selected_candidate = candidate_selection.get("selected_candidate")
    selected_candidate_id = candidate_selection.get("selected_candidate_id")
    candidate_status = str(candidate_selection.get("status") or "")
    if selected_candidate:
        status = "unique_deployment_candidate_selected_by_explicit_objective"
    elif candidate_status == "objective_tie_no_unique_candidate":
        status = "objective_tie_no_unique_deployment_candidate"
    else:
        status = candidate_status or "blocked_no_unique_deployment_candidate"

    return {
        "schema_version": DFT_DEPLOYMENT_SELECTOR_SCHEMA,
        "generated_at": _now_iso(),
        "status": status,
        "selection_status": status,
        "objective_present": True,
        "objective": _objective_summary(objective),
        "source_artifacts": _selector_source_artifacts(run_dir, objective_source_path),
        "selected_deployment_target": selected_target,
        "selected_candidate": selected_candidate,
        "selected_candidate_id": selected_candidate_id,
        "target_selection": target_selection,
        "candidate_selection": candidate_selection,
        "comparator_status": comparator.get("status"),
        "blockers": _as_list_of_mappings(candidate_selection.get("blockers")),
        "non_physical_tie_breakers_used": False,
        "forbidden_tie_breakers": list(_FORBIDDEN_TIE_BREAKERS),
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_deployment_selector(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate selector consistency and claim boundaries."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_DEPLOYMENT_SELECTOR_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("deployment_selector_must_not_mark_deliverable_complete")
    if payload.get("trusted_final_claim") is True:
        errors.append("deployment_selector_must_not_mark_trusted_final_claim")
    if payload.get("non_physical_tie_breakers_used") is True:
        errors.append("non_physical_tie_breakers_forbidden")
    selected_candidate = payload.get("selected_candidate")
    if selected_candidate is not None and not isinstance(selected_candidate, Mapping):
        errors.append("selected_candidate_must_be_mapping_or_null")
    if selected_candidate is not None and payload.get("objective_present") is not True:
        errors.append("selected_candidate_requires_explicit_objective")
    if selected_candidate is not None and not payload.get("selected_candidate_id"):
        errors.append("selected_candidate_id_required")
    status = str(payload.get("status") or "")
    if selected_candidate is None and status == "unique_deployment_candidate_selected_by_explicit_objective":
        errors.append("unique_selection_status_without_selected_candidate")
    if selected_candidate is not None and status != "unique_deployment_candidate_selected_by_explicit_objective":
        errors.append("selected_candidate_with_non_unique_status")
    candidate_selection = _as_mapping(payload.get("candidate_selection"))
    if candidate_selection.get("status") == "objective_tie_no_unique_candidate" and selected_candidate is not None:
        errors.append("objective_tie_must_not_have_selected_candidate")
    target = payload.get("selected_deployment_target")
    if target is not None and target not in {"fpga", "asic"}:
        errors.append("selected_deployment_target_must_be_fpga_or_asic")
    return {
        "schema_version": DFT_DEPLOYMENT_SELECTOR_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_deployment_selector(
    run_dir: Path,
    *,
    objective: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Write selector, validation, and status artifacts."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    selector = build_dft_deployment_selector(run_dir, objective=objective)
    validation = validate_dft_deployment_selector(selector)
    write_json(run_dir / "dft_deployment_selector.json", selector)
    write_json(run_dir / "dft_deployment_selector_validation.json", validation)
    status = {
        "schema_version": DFT_DEPLOYMENT_SELECTOR_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "selection_status": selector.get("selection_status"),
        "objective_present": selector.get("objective_present"),
        "selected_deployment_target": selector.get("selected_deployment_target"),
        "selected_candidate_id": selector.get("selected_candidate_id"),
        "non_physical_tie_breakers_used": selector.get("non_physical_tie_breakers_used"),
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_deployment_selector_status.json", status)
    return {
        "schema_version": "dse.dft.deployment_selector_artifact_status.v1",
        "status": status["status"],
        "selection_status": selector.get("selection_status"),
        "dft_deployment_selector": str(run_dir / "dft_deployment_selector.json"),
        "dft_deployment_selector_validation": str(run_dir / "dft_deployment_selector_validation.json"),
        "dft_deployment_selector_status": str(run_dir / "dft_deployment_selector_status.json"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_DEPLOYMENT_OBJECTIVE_SCHEMA",
    "DFT_DEPLOYMENT_SELECTOR_SCHEMA",
    "DFT_DEPLOYMENT_SELECTOR_STATUS_SCHEMA",
    "DFT_DEPLOYMENT_SELECTOR_VALIDATION_SCHEMA",
    "build_dft_deployment_selector",
    "validate_dft_deployment_selector",
    "write_dft_deployment_selector",
]
