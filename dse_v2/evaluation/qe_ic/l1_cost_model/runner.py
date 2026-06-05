#!/usr/bin/env python3
"""Runner for QE-IC Layer-5A L1 analytical cost-model estimates."""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping
from typing import Any

from dse_v2.candidates.qe_ic import validate_qe_ic_candidate_plan
from dse_v2.evaluation.qe_ic.l1_cost_model.model import build_l1_result
from dse_v2.evaluation.qe_ic.l1_cost_model.model_config import validate_qe_ic_l1_cost_model_config
from dse_v2.evaluation.qe_ic.l1_cost_model.schema import (
    CLAIM_BOUNDARY,
    LAYER_NAME,
    PRODUCER,
    QE_IC_L1_COST_MODEL_RESULTS_SCHEMA_VERSION,
    SOURCE_LAYER1_SUITE_ARTIFACT,
    SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
    SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT,
    SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT,
)
from dse_v2.profiling.qe_ic import validate_qe_ic_motif_profile
from dse_v2.viability.qe_ic import validate_qe_ic_target_viability
from dse_v2.workloads.qe_ic import validate_qe_ic_workload_suite


def _prefixed_errors(validation: Mapping[str, Any], *, prefix: str, label: str) -> list[dict[str, str]]:
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


def validate_qe_ic_l1_cost_model_inputs(
    suite: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
    target_viability: Mapping[str, Any],
    candidate_plan: Mapping[str, Any],
    model_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate Layer-5A inputs fail-closed."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for payload, validator, prefix, label in (
        (suite, validate_qe_ic_workload_suite, "layer1_suite", "Layer-1 suite"),
        (motif_profile, validate_qe_ic_motif_profile, "layer2_motif_profile", "Layer-2 motif profile"),
        (target_viability, validate_qe_ic_target_viability, "layer3_target_viability", "Layer-3 target viability"),
        (candidate_plan, validate_qe_ic_candidate_plan, "layer4_candidate_plan", "Layer-4 candidate plan"),
        (model_config, validate_qe_ic_l1_cost_model_config, "model_config", "model config"),
    ):
        validation = validator(payload)
        if validation.get("status") != "passed":
            errors.extend(_prefixed_errors(validation, prefix=prefix, label=label))
        for warning in validation.get("warnings", []):
            if isinstance(warning, Mapping):
                warnings.append(
                    {
                        "field": f"{prefix}.{warning.get('field', '$')}",
                        "message": str(warning.get("message", "")),
                    }
                )
    return {"status": "passed" if not errors else "failed", "errors": errors, "warnings": warnings}


def _candidate_by_id(candidate_plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate.get("candidate_id")): candidate
        for candidate in candidate_plan.get("candidates", [])
        if isinstance(candidate, Mapping)
    }


def _decision_by_candidate(candidate_plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(decision.get("candidate_id")): decision
        for decision in candidate_plan.get("promotion_decisions", [])
        if isinstance(decision, Mapping)
    }


def _source_records(candidate_plan: Mapping[str, Any]) -> Mapping[str, Any]:
    source_indexes = candidate_plan.get("source_indexes")
    if not isinstance(source_indexes, Mapping):
        return {}
    records = source_indexes.get("viability_records_by_id")
    return records if isinstance(records, Mapping) else {}


def _motif_profile_index(motif_profile: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    index: dict[tuple[str, str], Mapping[str, Any]] = {}
    for group in motif_profile.get("family_target_profiles", []):
        if not isinstance(group, Mapping):
            continue
        family_id = str(group.get("workload_family_id", ""))
        for motif in group.get("motif_profiles", []):
            if isinstance(motif, Mapping):
                index[(family_id, str(motif.get("motif_id", "")))] = motif
    return index


def _baseline_references(candidate_plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    baselines: list[dict[str, Any]] = []
    for candidate in candidate_plan.get("candidates", []):
        if not isinstance(candidate, Mapping) or candidate.get("candidate_type") != "baseline":
            continue
        baselines.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "target_type": candidate.get("target_type"),
                "workload_family_id": candidate.get("workload_family_id"),
                "motif_id": candidate.get("motif_id"),
                "source_viability_record_id": candidate.get("source_viability_record_id"),
                "metadata_role": "baseline_reference_only_no_l1_accelerator_result",
            }
        )
    baselines.sort(key=lambda item: str(item["candidate_id"]))
    return baselines


def _summary(results: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_target_type: dict[str, dict[str, int]] = {}
    by_suggestion: Counter[str] = Counter()
    high_risk_count = 0
    recommended_count = 0
    completed = 0
    failed = 0
    for result in results:
        target_type = str(result.get("target_type"))
        bucket = by_target_type.setdefault(
            target_type,
            {
                "request_count": 0,
                "completed_estimate_count": 0,
                "failed_estimate_count": 0,
            },
        )
        bucket["request_count"] += 1
        status = str(result.get("result_status"))
        if status == "completed_estimate":
            completed += 1
            bucket["completed_estimate_count"] += 1
        elif status == "failed_estimate":
            failed += 1
            bucket["failed_estimate_count"] += 1
        suggestion = result.get("next_fidelity_suggestion", {}).get("suggestion") if isinstance(result.get("next_fidelity_suggestion"), Mapping) else None
        if isinstance(suggestion, str):
            by_suggestion[suggestion] += 1
            if suggestion.startswith("promote_to_"):
                recommended_count += 1
        risk = result.get("risk") if isinstance(result.get("risk"), Mapping) else {}
        if isinstance(risk.get("overall_l1_risk"), int | float) and risk["overall_l1_risk"] >= 0.65:
            high_risk_count += 1
    return {
        "request_count": len(results),
        "completed_estimate_count": completed,
        "failed_estimate_count": failed,
        "by_target_type": by_target_type,
        "by_suggestion": dict(sorted(by_suggestion.items())),
        "high_risk_count": high_risk_count,
        "recommended_next_fidelity_count": recommended_count,
    }


def run_qe_ic_l1_cost_model(
    suite: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
    target_viability: Mapping[str, Any],
    candidate_plan: Mapping[str, Any],
    model_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Run deterministic L1 analytical estimates for planned Layer-4 L1 requests."""

    input_validation = validate_qe_ic_l1_cost_model_inputs(
        suite,
        motif_profile,
        target_viability,
        candidate_plan,
        model_config,
    )
    if input_validation["status"] != "passed":
        raise ValueError(f"invalid QE-IC Layer-5A inputs: {input_validation['errors']}")

    candidates = _candidate_by_id(candidate_plan)
    decisions = _decision_by_candidate(candidate_plan)
    source_records = _source_records(candidate_plan)
    motif_index = _motif_profile_index(motif_profile)
    results: list[dict[str, Any]] = []
    for request in candidate_plan.get("evaluation_requests", []):
        if not isinstance(request, Mapping):
            continue
        if request.get("requested_fidelity") != "L1_cost_model" or request.get("status") != "planned_not_executed":
            continue
        candidate = candidates.get(str(request.get("candidate_id")))
        decision = decisions.get(str(request.get("candidate_id")))
        if not candidate or not decision or decision.get("decision") != "promote":
            continue
        if candidate.get("candidate_type") == "baseline":
            continue
        source_record = source_records.get(str(candidate.get("source_viability_record_id")), {})
        motif = motif_index.get((str(candidate.get("workload_family_id")), str(candidate.get("motif_id"))), {})
        results.append(
            build_l1_result(
                request=request,
                candidate=candidate,
                promotion_decision=decision,
                source_record=source_record if isinstance(source_record, Mapping) else {},
                motif_profile=motif if isinstance(motif, Mapping) else {},
                suite_id=str(suite.get("suite_id", "")),
            )
        )
    results.sort(key=lambda result: str(result["request_id"]))
    return {
        "schema_version": QE_IC_L1_COST_MODEL_RESULTS_SCHEMA_VERSION,
        "layer": LAYER_NAME,
        "producer": PRODUCER,
        "suite_id": suite.get("suite_id"),
        "source_layer1_suite_artifact": SOURCE_LAYER1_SUITE_ARTIFACT,
        "source_layer2_motif_profile_artifact": SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
        "source_layer3_target_viability_artifact": SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT,
        "source_layer4_candidate_plan_artifact": SOURCE_LAYER4_CANDIDATE_PLAN_ARTIFACT,
        "source_layer4_candidate_plan": copy.deepcopy(dict(candidate_plan)),
        "model_config": copy.deepcopy(dict(model_config)),
        "results": results,
        "baseline_references": _baseline_references(candidate_plan),
        "summary": _summary(results),
        "claim_boundary": CLAIM_BOUNDARY,
    }

