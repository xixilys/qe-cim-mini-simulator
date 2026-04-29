from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from . import domain_contracts


SHORTLIST_NONE = "none"
SHORTLIST_TOP_FAST_UNCERTAIN_DIVERSE = "top_fast_uncertain_diverse"
SHORTLIST_TOP_FAST = "top_k_fast"
SHORTLIST_UNCERTAIN_DIVERSE_BASELINE = "uncertainty_diverse_baseline"
SHORTLIST_CALIBRATION_GAP = "calibration_gap"
SHORTLIST_POLICIES = (
    SHORTLIST_NONE,
    SHORTLIST_TOP_FAST_UNCERTAIN_DIVERSE,
    SHORTLIST_TOP_FAST,
    SHORTLIST_UNCERTAIN_DIVERSE_BASELINE,
    SHORTLIST_CALIBRATION_GAP,
)
DEFAULT_PLAN_NAME = "multi_fidelity_plan_v0.json"


def _candidate_id(row: Mapping[str, Any]) -> str:
    contract = row.get("systemc_feedback_contract", {})
    if isinstance(contract, Mapping) and contract.get("candidate_id"):
        return str(contract["candidate_id"])
    descriptor = row.get("candidate_descriptor", {})
    if isinstance(descriptor, Mapping) and descriptor.get("candidate_id"):
        return str(descriptor["candidate_id"])
    return str(row.get("candidate_id", "unknown_candidate"))


def _is_eligible(row: Mapping[str, Any]) -> bool:
    return (
        row.get("promotion_state") == "promotion-eligible"
        and row.get("design_validation", {}).get("validity_class") == "valid_executable"
    )


def apply_shortlist_policy(
    rows: Sequence[Mapping[str, Any]],
    policy: str = SHORTLIST_NONE,
    shortlist_size: int = 0,
) -> list[dict[str, Any]]:
    copied = [deepcopy(dict(row)) for row in rows]
    for row in copied:
        row["shortlist_policy"] = policy
        row["shortlisted_for_backend"] = False

    if policy == SHORTLIST_NONE or shortlist_size <= 0:
        return copied
    if policy not in {
        SHORTLIST_TOP_FAST_UNCERTAIN_DIVERSE,
        SHORTLIST_TOP_FAST,
        SHORTLIST_UNCERTAIN_DIVERSE_BASELINE,
        SHORTLIST_CALIBRATION_GAP,
    }:
        raise ValueError(f"unsupported shortlist policy: {policy}")

    eligible = [
        (index, row)
        for index, row in enumerate(copied)
        if _is_eligible(row)
    ]
    eligible.sort(key=lambda item: (item[1].get("screening_rank") or 10**9, item[0]))

    selected_indexes: list[int] = []
    selected_set: set[int] = set()
    selection_reasons: dict[int, str] = {}
    selected_families: set[str] = set()

    if policy in {SHORTLIST_TOP_FAST_UNCERTAIN_DIVERSE, SHORTLIST_UNCERTAIN_DIVERSE_BASELINE}:
        for index, row in eligible:
            family = str(row.get("design_point", {}).get("family", "unknown"))
            if family in selected_families:
                continue
            selected_indexes.append(index)
            selected_set.add(index)
            selected_families.add(family)
            selection_reasons[index] = "diverse_family_seed"
            if len(selected_indexes) >= shortlist_size:
                break

    if policy == SHORTLIST_CALIBRATION_GAP and len(selected_indexes) < shortlist_size:
        calibration_gap_rows = sorted(
            eligible,
            key=lambda item: (
                -_calibration_gap_score(item[1]),
                item[1].get("screening_rank") or 10**9,
                item[0],
            ),
        )
        for index, _row in calibration_gap_rows:
            if index in selected_set:
                continue
            selected_indexes.append(index)
            selected_set.add(index)
            selection_reasons[index] = "calibration_gap"
            if len(selected_indexes) >= shortlist_size:
                break

    if len(selected_indexes) < shortlist_size:
        for index, _row in eligible:
            if index in selected_set:
                continue
            selected_indexes.append(index)
            selected_set.add(index)
            selection_reasons[index] = "rank_fill"
            if len(selected_indexes) >= shortlist_size:
                break

    for order, index in enumerate(selected_indexes, start=1):
        copied[index]["shortlisted_for_backend"] = True
        copied[index]["shortlist_reason"] = selection_reasons.get(index, policy)
        copied[index]["shortlist_order"] = order
    return copied


def _calibration_gap_score(row: Mapping[str, Any]) -> float:
    metadata = row.get("model_metadata", {})
    calibration = row.get("calibration_metadata", {})
    score = 0.0
    if isinstance(metadata, Mapping) and metadata.get("confidence") in {"low", "unknown"}:
        score += 1.0
    if isinstance(calibration, Mapping) and calibration.get("error_after") is not None:
        try:
            score += float(calibration["error_after"])
        except (TypeError, ValueError):
            pass
    if not isinstance(row.get("evidence_ir"), Mapping):
        score += 0.5
    return score


def build_multi_fidelity_plan(
    rows: Sequence[Mapping[str, Any]],
    policy: str = SHORTLIST_TOP_FAST_UNCERTAIN_DIVERSE,
    shortlist_size: int = 0,
    selected_fidelity: str = "B2",
    backend_capabilities: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    copied = apply_shortlist_policy(rows, policy=policy, shortlist_size=shortlist_size)
    selected_candidates = []
    unselected_valid_candidates = []
    blocked_candidates = []
    capabilities = dict(backend_capabilities or {})
    for row in copied:
        candidate_id = _candidate_id(row)
        validation = row.get("design_validation", {})
        validity_class = validation.get("validity_class") if isinstance(validation, Mapping) else None
        if validity_class != "valid_executable":
            blocked_candidates.append(
                {
                    "candidate_id": candidate_id,
                    "validity_class": validity_class,
                    "reason": "not_valid_executable",
                    "promotion_blockers": list(validation.get("promotion_blockers", []))
                    if isinstance(validation, Mapping)
                    else [],
                }
            )
            continue
        if row.get("shortlisted_for_backend"):
            request_ref = f"backend_execution_requests/{candidate_id}.json"
            selected_candidates.append(
                {
                    "candidate_id": candidate_id,
                    "selected_fidelity": selected_fidelity,
                    "rationale": row.get("shortlist_reason") or policy,
                    "screening_rank": row.get("screening_rank"),
                    "capability_requirements": {
                        "requested_fidelity": selected_fidelity,
                        "requires_device_diag_engine": row.get("design_point", {}).get("diag_policy")
                        == "aggressive_device",
                        "requires_target_resource_model": True,
                        "requires_host_device_link_model": row.get("design_point", {}).get("offload_scope")
                        == "device_heavy",
                    },
                    "backend_request_ref": request_ref,
                    "evidence_gaps": list(validation.get("missing_evidence", []))
                    if isinstance(validation, Mapping)
                    else [],
                }
            )
        else:
            unselected_valid_candidates.append(
                {
                    "candidate_id": candidate_id,
                    "validity_class": validity_class,
                    "screening_rank": row.get("screening_rank"),
                    "reason": "not_selected_by_policy",
                }
            )
    return {
        "schema_version": domain_contracts.MULTI_FIDELITY_PLAN_SCHEMA_VERSION,
        "policy": policy,
        "selected_fidelity": selected_fidelity,
        "selected_count": len(selected_candidates),
        "selected_candidates": selected_candidates,
        "unselected_valid_candidate_count": len(unselected_valid_candidates),
        "unselected_valid_candidates": unselected_valid_candidates,
        "blocked_candidate_count": len(blocked_candidates),
        "blocked_candidates": blocked_candidates,
        "backend_capability_requirements": capabilities,
        "scheduler_metadata": {
            "selection_axes": [
                "screening_rank",
                "model_confidence",
                "family_diversity",
                "calibration_gap",
                "required_baselines",
            ],
            "adaptive_feedback_ready": True,
            "backend_execution_performed_by_frontend": False,
        },
        "claim_ceiling": "descriptor_generation_only",
        "non_claims": [
            "not_backend_executed",
            "not_final_ranking_authority",
            "not_public_winner",
        ],
    }
