#!/usr/bin/env python3
"""QE-IC Layer-4 candidate plan builder."""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping
from typing import Any

from dse_v2.candidates.qe_ic.campaign_config import validate_qe_ic_campaign_config
from dse_v2.candidates.qe_ic.generator import (
    generate_qe_ic_candidates,
    source_viability_record_index,
)
from dse_v2.candidates.qe_ic.promotion import (
    build_evaluation_requests,
    promote_qe_ic_candidates,
)
from dse_v2.candidates.qe_ic.schema import (
    CLAIM_BOUNDARY,
    LAYER_NAME,
    PRODUCER,
    QE_IC_CANDIDATE_PLAN_SCHEMA_VERSION,
    SOURCE_LAYER1_SUITE_ARTIFACT,
    SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
    SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT,
)
from dse_v2.candidates.qe_ic.template_registry import get_qe_ic_candidate_template_registry
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


def validate_qe_ic_candidate_plan_inputs(
    suite: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
    target_viability: Mapping[str, Any],
    campaign_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate Layer-4 inputs before candidate generation."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for payload, validator, prefix, label in (
        (suite, validate_qe_ic_workload_suite, "layer1_suite", "Layer-1 suite"),
        (motif_profile, validate_qe_ic_motif_profile, "layer2_motif_profile", "Layer-2 motif profile"),
        (target_viability, validate_qe_ic_target_viability, "layer3_target_viability", "Layer-3 target viability"),
        (campaign_config, validate_qe_ic_campaign_config, "campaign_config", "campaign config"),
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
    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
    }


def _source_indexes(
    suite: Mapping[str, Any],
    target_viability: Mapping[str, Any],
) -> dict[str, Any]:
    records = source_viability_record_index(target_viability)
    family_ids = [
        family.get("family_id")
        for family in suite.get("workload_families", [])
        if isinstance(family, Mapping)
    ]
    motif_ids = sorted(str(motif_id) for motif_id in suite.get("motif_registry", {}))
    return {
        "workload_family_ids": family_ids,
        "motif_ids": motif_ids,
        "viability_records_by_id": records,
    }


def _summary(
    *,
    candidates: list[dict[str, Any]],
    promotion_decisions: list[dict[str, Any]],
    evaluation_requests: list[dict[str, Any]],
    campaign_config: Mapping[str, Any],
) -> dict[str, Any]:
    decisions = Counter(decision["decision"] for decision in promotion_decisions)
    promoted_candidate_ids = {
        decision["candidate_id"]
        for decision in promotion_decisions
        if decision["decision"] == "promote"
    }
    candidate_by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    promoted_candidates = [
        candidate_by_id[candidate_id]
        for candidate_id in sorted(promoted_candidate_ids)
        if candidate_id in candidate_by_id
    ]
    promotion = campaign_config.get("promotion") if isinstance(campaign_config.get("promotion"), Mapping) else {}
    budget = promotion.get("budget") if isinstance(promotion.get("budget"), Mapping) else {}
    by_target_type: dict[str, dict[str, int]] = {}
    for candidate in candidates:
        target_type = str(candidate.get("target_type"))
        bucket = by_target_type.setdefault(
            target_type,
            {
                "candidate_count": 0,
                "baseline_count": 0,
                "promote_count": 0,
                "hold_count": 0,
                "reject_count": 0,
            },
        )
        bucket["candidate_count"] += 1
    decision_by_candidate = {
        decision["candidate_id"]: decision["decision"]
        for decision in promotion_decisions
    }
    for candidate in candidates:
        target_type = str(candidate.get("target_type"))
        decision = decision_by_candidate.get(candidate["candidate_id"])
        if decision in {"baseline", "promote", "hold", "reject"}:
            by_target_type[target_type][f"{decision}_count"] += 1
    return {
        "candidate_count": len(candidates),
        "baseline_count": decisions.get("baseline", 0),
        "promote_count": decisions.get("promote", 0),
        "hold_count": decisions.get("hold", 0),
        "reject_count": decisions.get("reject", 0),
        "evaluation_request_count": len(evaluation_requests),
        "budget_used": {
            "max_l1_cost_model_requests": decisions.get("promote", 0),
            "max_systemc_requests": 0,
            "max_gem5_requests": 0,
            "max_vivado_requests": 0,
            "max_real_qe_requests": 0,
        },
        "budget_limits": {
            "max_l1_cost_model_requests": int(budget.get("max_l1_cost_model_requests", 0)),
            "max_systemc_requests": int(budget.get("max_systemc_requests", 0)),
            "max_gem5_requests": int(budget.get("max_gem5_requests", 0)),
            "max_vivado_requests": int(budget.get("max_vivado_requests", 0)),
            "max_real_qe_requests": int(budget.get("max_real_qe_requests", 0)),
        },
        "diversity": {
            "target_type_required": promotion.get("require_diversity_across_target_type") is True,
            "motif_required": promotion.get("require_diversity_across_motif") is True,
            "promoted_target_types": sorted({str(candidate["target_type"]) for candidate in promoted_candidates}),
            "promoted_motifs": sorted({str(candidate["motif_id"]) for candidate in promoted_candidates}),
            "promoted_target_type_count": len({str(candidate["target_type"]) for candidate in promoted_candidates}),
            "promoted_motif_count": len({str(candidate["motif_id"]) for candidate in promoted_candidates}),
        },
        "by_target_type": by_target_type,
    }


def build_qe_ic_candidate_plan(
    suite: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
    target_viability: Mapping[str, Any],
    campaign_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Build QE-IC Layer-4 candidate specs, decisions, and next-fidelity plans."""

    input_validation = validate_qe_ic_candidate_plan_inputs(
        suite,
        motif_profile,
        target_viability,
        campaign_config,
    )
    if input_validation["status"] != "passed":
        raise ValueError(f"invalid QE-IC Layer-4 inputs: {input_validation['errors']}")

    source_indexes = _source_indexes(suite, target_viability)
    candidates = generate_qe_ic_candidates(suite, target_viability, campaign_config)
    promotion_decisions = promote_qe_ic_candidates(
        candidates,
        source_indexes["viability_records_by_id"],
        campaign_config,
    )
    evaluation_requests = build_evaluation_requests(promotion_decisions, candidates)
    return {
        "schema_version": QE_IC_CANDIDATE_PLAN_SCHEMA_VERSION,
        "layer": LAYER_NAME,
        "producer": PRODUCER,
        "suite_id": suite.get("suite_id"),
        "source_layer1_suite_artifact": SOURCE_LAYER1_SUITE_ARTIFACT,
        "source_layer2_motif_profile_artifact": SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
        "source_layer3_target_viability_artifact": SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT,
        "campaign_config": copy.deepcopy(dict(campaign_config)),
        "candidate_template_registry": get_qe_ic_candidate_template_registry(),
        "source_indexes": source_indexes,
        "candidates": candidates,
        "promotion_decisions": promotion_decisions,
        "evaluation_requests": evaluation_requests,
        "summary": _summary(
            candidates=candidates,
            promotion_decisions=promotion_decisions,
            evaluation_requests=evaluation_requests,
            campaign_config=campaign_config,
        ),
        "claim_boundary": CLAIM_BOUNDARY,
    }
