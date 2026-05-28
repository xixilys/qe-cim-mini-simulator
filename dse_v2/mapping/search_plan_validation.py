#!/usr/bin/env python3
"""Fail-closed validation for Step2 search-iteration plans.

The validator is domain-neutral: it checks that a persisted
``dse.step2.search_iteration_plan.v1`` artifact is internally consistent,
keeps proposal/admission records provenance-only, and does not silently turn
Step2 search output into Step3 execution authority or trusted completion
claims.
"""

from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from dse_v2.mapping.search_policy import (
    IDENTITY_ALIAS_PARAMETER_KEYS,
    NON_CANDIDATE_ALIAS_PARAMETER_KEYS,
    SIMULATION_BLOCKERS,
    SIMULATION_ELIGIBLE,
    STEP2_SCREENABLE,
    STEP3_EVALUABLE,
)

SEARCH_ITERATION_PLAN_VALIDATION_SCHEMA = "dse.step2.search_iteration_plan_validation.v1"
SEARCH_ITERATION_PLAN_SCHEMA = "dse.step2.search_iteration_plan.v1"


_FALSE_TRUST_FLAGS = (
    "trusted_final_claim",
    "release_completion_eligible",
    "deliverable_complete",
)
_PROVENANCE_ONLY_FLAGS = (
    "not_a_step3_queue_entry",
    "provenance_only",
)
_ADMISSION_ALIAS_FIELDS = (
    "queue_entry_id",
    "plan_entry_id",
    "candidate_id",
    "complete_dse_candidate_id",
    "mapping_candidate_id",
    "search_policy_candidate_id",
    "parameter_hash",
    "mapping_parameter_hash",
    "search_policy_parameter_hash",
    "top_k_entry_id",
)
_REQUIRED_CANDIDATE_PROVENANCE_EXCLUDES = (
    "proposal_order",
    "budget",
    "feedback_order",
    "transient_rank",
)
_ADMISSION_PROJECTION_MATCH_FIELDS = (
    "search_policy_candidate_id",
    "complete_dse_candidate_id",
    "architecture_id",
    "taxonomy_id",
    "design_point_id",
    "mapping_id",
    "mapping_candidate_id",
    "compile_schedule_id",
    "runtime_schedule_id",
    "parameter_profile_id",
    "parameter_hash",
    "search_policy_parameter_hash",
    "mapping_parameter_hash",
    "candidate_record_hash",
    "release_subset_hash",
    "candidate_identity_policy",
    "search_policy_rank",
    "queue_state",
    "admission_required_before_execution",
)
_ADMISSION_PROJECTION_BOOL_FIELDS = (
    SIMULATION_ELIGIBLE,
    STEP3_EVALUABLE,
    STEP2_SCREENABLE,
    "promoted_for_simulation",
)
_CHECKPOINT_PROPOSAL_MATCH_FIELDS = (
    "search_policy_candidate_id",
    "parameter_hash",
    "generation_reason",
    "candidate_identity_policy",
    "queue_state",
    "claim_status",
)
_CHECKPOINT_PROPOSAL_DEEP_MATCH_FIELDS = (
    "parameters",
    "candidate_identity",
    "promotion_reasons",
    "blocker_reasons",
    SIMULATION_BLOCKERS,
    "observed_metrics",
)
_CHECKPOINT_PROPOSAL_BOOL_FIELDS = (
    SIMULATION_ELIGIBLE,
    STEP3_EVALUABLE,
    STEP2_SCREENABLE,
    "promoted_for_simulation",
)
_FEEDBACK_ROUTE_CANDIDATE_REF_ALIAS_FIELDS = (
    "search_policy_candidate_id",
    "complete_dse_candidate_id",
    "candidate_id",
    "mapping_candidate_id",
    "mapping_parameter_hash",
    "parameter_hash",
    "architecture_id",
    "design_point_id",
    "mapping_id",
    "top_k_entry_id",
    "queue_entry_id",
)
_SOURCE_PROVENANCE_REQUIRED_ROLES = {
    "input_search_checkpoint": (
        "input_search_checkpoint_ref",
        "search_checkpoint.json",
        True,
    ),
    "feedback_update": ("feedback_update_ref", "feedback_update.json", True),
    "calibration_record": ("calibration_record_ref", "calibration_record.json", False),
}
_REQUIRED_FEEDBACK_CONTRACT_FIELDS = (
    "feedback_observation_routing",
    "feedback_observation_count",
    "feedback_unresolved_observation_count",
    "feedback_routing_status",
)
CAMPAIGN_SCOPE_FIELDS = ("campaign_id", "workload_run_id", "trial_id")
ROW_SCOPE_NESTED_MAPS = (
    "parameters",
    "candidate_refs",
    "provenance",
    "candidate_identity",
    "observed_metrics",
    "metrics",
)


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _is_non_string_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _as_list(value: Any) -> List[Any]:
    if _is_non_string_sequence(value):
        return list(value)
    return []


def _string(value: Any) -> str:
    return str(value or "")


def _invalid_run_local_ref_reason(value: str) -> str:
    candidate = PurePosixPath(value)
    if candidate.is_absolute():
        return "absolute paths are not run-local evidence references"
    if ".." in candidate.parts:
        return "parent-directory traversal is not allowed in evidence references"
    if str(candidate) in {"", "."}:
        return "empty queue reference is not a run-local evidence reference"
    return ""


def _error(errors: List[Dict[str, Any]], field: str, message: str, **extra: Any) -> None:
    row = {"field": field, "message": message}
    row.update(extra)
    errors.append(row)


def _check_list_container(
    errors: List[Dict[str, Any]],
    payload: Mapping[str, Any],
    *,
    field_name: str,
    field_path: str,
    row_description: str,
) -> None:
    if field_name not in payload:
        return
    value = payload.get(field_name)
    if not _is_non_string_sequence(value):
        _error(
            errors,
            field_path,
            f"{row_description} field must be a list",
            actual_type=type(value).__name__,
        )


def _duplicate_values(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for value in values:
        if not value:
            continue
        if value in seen:
            dupes.add(value)
        seen.add(value)
    return sorted(dupes)


def _plan_scope(plan: Mapping[str, Any]) -> Dict[str, str]:
    return {
        field: _string(plan.get(field))
        for field in CAMPAIGN_SCOPE_FIELDS
        if _string(plan.get(field))
    }


def _row_scope_values(row: Mapping[str, Any], field: str) -> Dict[str, List[str]]:
    values_by_source: Dict[str, List[str]] = {}
    direct = _string(row.get(field))
    if direct:
        values_by_source.setdefault(direct, []).append("direct")
    for nested_key in ROW_SCOPE_NESTED_MAPS:
        nested = _as_mapping(row.get(nested_key))
        nested_value = _string(nested.get(field))
        if nested_value:
            values_by_source.setdefault(nested_value, []).append(nested_key)
    return values_by_source


def _check_row_scope_matches_plan(
    errors: List[Dict[str, Any]],
    row: Mapping[str, Any],
    *,
    prefix: str,
    plan_scope: Mapping[str, str],
) -> None:
    """Reject row-local Campaign/Trial scope rebinding inside search artifacts."""

    for field in CAMPAIGN_SCOPE_FIELDS:
        values_by_source = _row_scope_values(row, field)
        if len(values_by_source) > 1:
            _error(
                errors,
                f"{prefix}.{field}",
                "row scope field must not disagree between direct and nested payloads",
                scope_field=field,
                observed_values=sorted(values_by_source),
                sources_by_value={
                    value: sorted(sources)
                    for value, sources in sorted(values_by_source.items())
                },
            )
        expected = _string(plan_scope.get(field))
        if not expected:
            if values_by_source:
                _error(
                    errors,
                    f"{prefix}.{field}",
                    "search iteration row scope field requires top-level plan scope",
                    scope_field=field,
                    observed_values=sorted(values_by_source),
                    sources_by_value={
                        value: sorted(sources)
                        for value, sources in sorted(values_by_source.items())
                    },
                )
            continue
        for actual, sources in values_by_source.items():
            if actual != expected:
                _error(
                    errors,
                    f"{prefix}.{field}",
                    "search iteration row scope field must match the plan scope",
                    scope_field=field,
                    expected=expected,
                    actual=actual,
                    sources=sorted(sources),
                )


def _check_false_flags(
    errors: List[Dict[str, Any]],
    payload: Mapping[str, Any],
    *,
    prefix: str,
) -> None:
    for key in _FALSE_TRUST_FLAGS:
        if payload.get(key) is True:
            _error(errors, f"{prefix}.{key}", f"{key} must remain false")
    if payload.get("execution_allowed") is True:
        _error(errors, f"{prefix}.execution_allowed", "execution_allowed must remain false")


def _check_provenance_flags(
    errors: List[Dict[str, Any]],
    payload: Mapping[str, Any],
    *,
    prefix: str,
) -> None:
    _check_false_flags(errors, payload, prefix=prefix)
    for key in _PROVENANCE_ONLY_FLAGS:
        if payload.get(key) is not True:
            _error(errors, f"{prefix}.{key}", f"{key} must be true")


def _append_alias(aliases: List[str], value: Any) -> None:
    alias = _string(value)
    if alias and alias not in aliases:
        aliases.append(alias)


def _row_aliases(row: Mapping[str, Any]) -> List[str]:
    aliases: List[str] = []
    parameters = _as_mapping(row.get("parameters"))
    provenance = _as_mapping(row.get("provenance"))
    for field in _ADMISSION_ALIAS_FIELDS:
        _append_alias(aliases, row.get(field))
        _append_alias(aliases, parameters.get(field))
        _append_alias(aliases, provenance.get(field))
    return aliases


def _row_alias_duplicates(rows: Sequence[Any]) -> Dict[str, List[str]]:
    owners_by_alias: Dict[str, set[str]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        owner = _string(row.get("candidate_id")) or _string(row.get("queue_entry_id")) or f"row[{index}]"
        for alias in _row_aliases(row):
            owners_by_alias.setdefault(alias, set()).add(owner)
    return {
        alias: sorted(owners)
        for alias, owners in owners_by_alias.items()
        if alias and len(owners) > 1
    }


def _append_feedback_alias(aliases: List[str], value: Any) -> None:
    alias = _string(value)
    if alias and alias not in aliases:
        aliases.append(alias)


def _feedback_observation_aliases(row: Mapping[str, Any]) -> List[str]:
    """Return aliases that Step4 feedback routing may use for a checkpoint row.

    This mirrors ``candidate_observation_id_lookup`` in ``search_policy`` but
    keeps owner sets visible so the validator can fail closed when a persisted
    route names an alias that no longer has exactly one checkpoint owner.
    """

    aliases: List[str] = []
    for field in (
        "candidate_id",
        "search_policy_candidate_id",
        "complete_dse_candidate_id",
        "mapping_candidate_id",
        "search_policy_parameter_hash",
        "mapping_parameter_hash",
        "parameter_hash",
        "architecture_id",
        "mapping_id",
        "design_point_id",
        "top_k_entry_id",
        "queue_entry_id",
    ):
        _append_feedback_alias(aliases, row.get(field))

    provenance = _as_mapping(row.get("provenance"))
    for field in (
        "parameter_hash",
        "search_policy_candidate_id",
        "complete_dse_candidate_id",
        "mapping_candidate_id",
        "architecture_id",
    ):
        _append_feedback_alias(aliases, provenance.get(field))

    candidate_refs = _as_mapping(row.get("candidate_refs"))
    for field in (
        "search_policy_candidate_id",
        "complete_dse_candidate_id",
        "candidate_id",
        "mapping_candidate_id",
        "mapping_parameter_hash",
        "parameter_hash",
        "architecture_id",
    ):
        _append_feedback_alias(aliases, candidate_refs.get(field))

    parameters = _as_mapping(row.get("parameters"))
    for key, value in parameters.items():
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                if (
                    nested_key in NON_CANDIDATE_ALIAS_PARAMETER_KEYS
                    or nested_key not in IDENTITY_ALIAS_PARAMETER_KEYS
                ):
                    continue
                if isinstance(nested_value, (str, int, float, bool)) and nested_value not in (None, ""):
                    _append_feedback_alias(aliases, nested_value)
            continue
        if key in NON_CANDIDATE_ALIAS_PARAMETER_KEYS or key not in IDENTITY_ALIAS_PARAMETER_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) and value not in (None, ""):
            _append_feedback_alias(aliases, value)
    return aliases


def _feedback_alias_owner_maps(rows: Sequence[Any]) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    owners_by_alias: Dict[str, set[str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        owner = _string(row.get("candidate_id"))
        if not owner:
            continue
        for alias in _feedback_observation_aliases(row):
            owners_by_alias.setdefault(alias, set()).add(owner)
    unique_owners: Dict[str, str] = {}
    ambiguous_owners: Dict[str, List[str]] = {}
    for alias, owners in owners_by_alias.items():
        if not alias:
            continue
        if len(owners) == 1:
            unique_owners[alias] = next(iter(owners))
        else:
            ambiguous_owners[alias] = sorted(owners)
    return unique_owners, ambiguous_owners


def _candidate_ids(rows: Sequence[Any]) -> List[str]:
    return [
        str(row.get("candidate_id") or "")
        for row in rows
        if isinstance(row, Mapping)
    ]


def _candidate_identity(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _compare_projection_value(value: Any) -> str:
    return "" if value is None else str(value)


def _check_admission_projection_matches_proposal(
    errors: List[Dict[str, Any]],
    *,
    proposal: Mapping[str, Any],
    admission: Mapping[str, Any],
    prefix: str,
) -> None:
    """Ensure Step2 admission projections cannot rebind proposal identity.

    ``next_step3_admission_candidates`` is a narrowed materialization projection
    of ``next_candidates``.  It may omit broad proposal-only context, but any
    executable/admission identity it carries must be copied from the matching
    proposal row rather than forged after candidate ordering.
    """

    candidate_id = _string(proposal.get("candidate_id"))
    if _string(admission.get("candidate_id")) != candidate_id:
        _error(
            errors,
            f"{prefix}.candidate_id",
            "admission candidate_id must match its proposal candidate_id",
            expected=candidate_id,
            actual=admission.get("candidate_id"),
        )
    for field in _ADMISSION_PROJECTION_MATCH_FIELDS:
        expected = _compare_projection_value(proposal.get(field))
        actual = _compare_projection_value(admission.get(field))
        if actual != expected:
            _error(
                errors,
                f"{prefix}.{field}",
                "admission projection field must match the corresponding proposal row",
                expected=expected,
                actual=actual,
            )
    for field in _ADMISSION_PROJECTION_BOOL_FIELDS:
        if admission.get(field) is not proposal.get(field):
            _error(
                errors,
                f"{prefix}.{field}",
                "admission projection eligibility flags must match the corresponding proposal row",
                expected=proposal.get(field),
                actual=admission.get(field),
            )
    expected_blockers = _as_list(proposal.get(SIMULATION_BLOCKERS))
    actual_blockers = _as_list(admission.get(SIMULATION_BLOCKERS))
    if actual_blockers != expected_blockers:
        _error(
            errors,
            f"{prefix}.{SIMULATION_BLOCKERS}",
            "admission projection blockers must match the corresponding proposal row",
            expected=expected_blockers,
            actual=actual_blockers,
        )
    expected_identity = _candidate_identity(proposal.get("candidate_identity"))
    actual_identity = _candidate_identity(admission.get("candidate_identity"))
    if actual_identity != expected_identity:
        _error(
            errors,
            f"{prefix}.candidate_identity",
            "admission projection candidate_identity must match the corresponding proposal row",
            expected=expected_identity,
            actual=actual_identity,
        )


def _checkpoint_candidates_by_id(plan: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    checkpoint = _as_mapping(plan.get("next_checkpoint"))
    rows = _as_list(checkpoint.get("candidates"))
    return {
        _string(row.get("candidate_id")): row
        for row in rows
        if isinstance(row, Mapping) and _string(row.get("candidate_id"))
    }


def _non_negative_int_value(
    errors: List[Dict[str, Any]],
    *,
    field: str,
    value: Any,
    default: int,
) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _error(
            errors,
            field,
            "count field must be a non-negative integer",
            actual=value,
            actual_type=type(value).__name__,
        )
        return default
    return value


def _score_value(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    score = float(value)
    return score if math.isfinite(score) else None


def _check_next_checkpoint_consistency(
    errors: List[Dict[str, Any]],
    *,
    plan: Mapping[str, Any],
    proposals_by_id: Mapping[str, Mapping[str, Any]],
    plan_scope: Mapping[str, str],
) -> Dict[str, Mapping[str, Any]]:
    """Bind proposal rows to the replay checkpoint they claim to update."""

    checkpoint = _as_mapping(plan.get("next_checkpoint"))
    if not checkpoint:
        _error(
            errors,
            "next_checkpoint",
            "search iteration plans must preserve the replayable next_checkpoint",
        )
        return {}
    if checkpoint.get("schema_version") != "dse.step2.search_checkpoint.v1":
        _error(
            errors,
            "next_checkpoint.schema_version",
            "next_checkpoint schema_version must match the canonical search checkpoint contract",
            expected="dse.step2.search_checkpoint.v1",
            actual=checkpoint.get("schema_version"),
        )
    for key in ("policy_name", "problem_id"):
        if _string(checkpoint.get(key)) != _string(plan.get(key)):
            _error(
                errors,
                f"next_checkpoint.{key}",
                f"next_checkpoint {key} must match the search iteration plan",
                expected=plan.get(key),
                actual=checkpoint.get(key),
            )

    _check_list_container(
        errors,
        checkpoint,
        field_name="candidates",
        field_path="next_checkpoint.candidates",
        row_description="next_checkpoint candidates",
    )
    checkpoint_rows = _as_list(checkpoint.get("candidates"))
    for index, raw_row in enumerate(checkpoint_rows):
        prefix = f"next_checkpoint.candidates[{index}]"
        if not isinstance(raw_row, Mapping):
            _error(errors, prefix, "checkpoint candidate row must be a mapping")
            continue
        _check_row_scope_matches_plan(
            errors,
            raw_row,
            prefix=prefix,
            plan_scope=plan_scope,
        )
    checkpoint_candidates_by_id = _checkpoint_candidates_by_id(plan)
    duplicate_checkpoint_ids = _duplicate_values([
        _string(row.get("candidate_id"))
        for row in checkpoint_rows
        if isinstance(row, Mapping)
    ])
    if duplicate_checkpoint_ids:
        _error(
            errors,
            "next_checkpoint.candidates",
            "checkpoint candidate IDs must be unique",
            duplicates=duplicate_checkpoint_ids,
        )
    for count_key in ("candidate_count", "proposed_count"):
        declared = checkpoint.get(count_key)
        if declared is not None and _non_negative_int_value(
            errors,
            field=f"next_checkpoint.{count_key}",
            value=declared,
            default=len(checkpoint_rows),
        ) != len(checkpoint_rows):
            _error(
                errors,
                f"next_checkpoint.{count_key}",
                f"next_checkpoint {count_key} must equal len(next_checkpoint.candidates)",
                declared=declared,
                actual=len(checkpoint_rows),
            )
    checkpoint_proposal_budget = checkpoint.get("proposal_budget")
    next_proposal_budget = plan.get("next_proposal_budget")
    if (
        checkpoint_proposal_budget is not None
        and _non_negative_int_value(
            errors,
            field="next_checkpoint.proposal_budget",
            value=checkpoint_proposal_budget,
            default=-1,
        )
        != _non_negative_int_value(
            errors,
            field="next_proposal_budget",
            value=next_proposal_budget,
            default=-2,
        )
    ):
        _error(
            errors,
            "next_checkpoint.proposal_budget",
            "next_checkpoint proposal_budget must match next_proposal_budget",
            expected=plan.get("next_proposal_budget"),
            actual=checkpoint_proposal_budget,
        )

    checkpoint_best_candidate_id = _string(checkpoint.get("best_candidate_id"))
    next_best_candidate_id = _string(plan.get("next_best_candidate_id"))
    if checkpoint_best_candidate_id != next_best_candidate_id:
        _error(
            errors,
            "next_checkpoint.best_candidate_id",
            "next_checkpoint best_candidate_id must match next_best_candidate_id",
            expected=next_best_candidate_id,
            actual=checkpoint.get("best_candidate_id"),
        )
    if checkpoint_best_candidate_id and checkpoint_best_candidate_id not in checkpoint_candidates_by_id:
        _error(
            errors,
            "next_checkpoint.best_candidate_id",
            "next_checkpoint best_candidate_id must refer to a checkpoint candidate",
            actual=checkpoint_best_candidate_id,
        )
    scored_checkpoint_rows: List[Tuple[float, str, int]] = []
    for index, raw_row in enumerate(checkpoint_rows):
        if not isinstance(raw_row, Mapping):
            continue
        candidate_id = _string(raw_row.get("candidate_id"))
        score = _score_value(raw_row.get("score"))
        if score is None:
            _error(
                errors,
                f"next_checkpoint.candidates[{index}].score",
                "next_checkpoint candidate scores must be finite numbers so best_candidate_id can be recomputed",
                actual=raw_row.get("score"),
            )
            continue
        if candidate_id:
            scored_checkpoint_rows.append((score, candidate_id, index))
    if scored_checkpoint_rows:
        best_score = max(score for score, _, _ in scored_checkpoint_rows)
        best_score_rows = [
            (candidate_id, index)
            for score, candidate_id, index in scored_checkpoint_rows
            if score == best_score
        ]

        def tie_break_key(item: Tuple[str, int]) -> Tuple[int, int, str]:
            candidate_id, index = item
            rank = proposals_by_id.get(candidate_id, {}).get("search_policy_rank")
            if isinstance(rank, int) and not isinstance(rank, bool) and rank > 0:
                rank_key = rank
            else:
                rank_key = index + 1
            return (rank_key, index, candidate_id)

        expected_best_candidate_id = min(best_score_rows, key=tie_break_key)[0]
        if checkpoint_best_candidate_id != expected_best_candidate_id:
            actual_row = checkpoint_candidates_by_id.get(checkpoint_best_candidate_id, {})
            _error(
                errors,
                "next_checkpoint.best_candidate_id",
                "next_checkpoint best_candidate_id must be recomputed from the highest candidate score with deterministic rank tie-break",
                expected=expected_best_candidate_id,
                actual=checkpoint_best_candidate_id or checkpoint.get("best_candidate_id"),
                expected_score=best_score,
                actual_score=actual_row.get("score") if isinstance(actual_row, Mapping) else None,
            )

    missing_checkpoint_ids = sorted(set(proposals_by_id) - set(checkpoint_candidates_by_id))
    if missing_checkpoint_ids:
        _error(
            errors,
            "next_checkpoint.candidates",
            "every next candidate must also be present in next_checkpoint candidates",
            missing_candidate_ids=missing_checkpoint_ids,
        )
    extra_checkpoint_ids = sorted(set(checkpoint_candidates_by_id) - set(proposals_by_id))
    if extra_checkpoint_ids:
        _error(
            errors,
            "next_checkpoint.candidates",
            "next_checkpoint candidates must not contain candidates absent from next_candidates",
            extra_candidate_ids=extra_checkpoint_ids,
        )
    for candidate_id, proposal in proposals_by_id.items():
        checkpoint_row = checkpoint_candidates_by_id.get(candidate_id)
        if checkpoint_row is None:
            continue
        for field in _CHECKPOINT_PROPOSAL_MATCH_FIELDS:
            expected = _compare_projection_value(checkpoint_row.get(field))
            actual = _compare_projection_value(proposal.get(field))
            if actual != expected:
                _error(
                    errors,
                    f"next_candidates[{candidate_id}].{field}",
                    "proposal field must match the corresponding next_checkpoint candidate row",
                    expected=expected,
                    actual=actual,
                )
        for field in _CHECKPOINT_PROPOSAL_DEEP_MATCH_FIELDS:
            expected = checkpoint_row.get(field)
            actual = proposal.get(field)
            if actual != expected:
                _error(
                    errors,
                    f"next_candidates[{candidate_id}].{field}",
                    "proposal payload must match the corresponding next_checkpoint candidate row",
                    expected=expected,
                    actual=actual,
                )
        for field in _CHECKPOINT_PROPOSAL_BOOL_FIELDS:
            if proposal.get(field) is not checkpoint_row.get(field):
                _error(
                    errors,
                    f"next_candidates[{candidate_id}].{field}",
                    "proposal eligibility flag must match the corresponding next_checkpoint candidate row",
                    expected=checkpoint_row.get(field),
                    actual=proposal.get(field),
                )
        checkpoint_score = _compare_projection_value(checkpoint_row.get("score"))
        proposal_score = _compare_projection_value(proposal.get("score"))
        if proposal_score != checkpoint_score:
            _error(
                errors,
                f"next_candidates[{candidate_id}].score",
                "proposal score must match the corresponding next_checkpoint candidate row",
                expected=checkpoint_score,
                actual=proposal_score,
            )
    return checkpoint_candidates_by_id


def _check_feedback_observation_route(
    errors: List[Dict[str, Any]],
    route: Mapping[str, Any],
    *,
    prefix: str,
) -> None:
    _check_provenance_flags(errors, route, prefix=prefix)
    routed = route.get("routed_to_search_policy") is True
    matched_candidate_id = _string(route.get("matched_candidate_id"))
    matched_alias = _string(route.get("matched_candidate_alias"))
    blockers = _as_list(route.get("routing_blockers"))
    if routed:
        if route.get("routing_status") != "resolved_to_search_policy":
            _error(
                errors,
                f"{prefix}.routing_status",
                "resolved feedback routes must use resolved_to_search_policy status",
                actual=route.get("routing_status"),
            )
        if not matched_candidate_id:
            _error(errors, f"{prefix}.matched_candidate_id", "routed feedback must name matched_candidate_id")
        if not matched_alias:
            _error(errors, f"{prefix}.matched_candidate_alias", "routed feedback must name matched_candidate_alias")
        if blockers:
            _error(errors, f"{prefix}.routing_blockers", "routed feedback must not carry routing blockers", blockers=blockers)
    else:
        if route.get("routing_status") != "unresolved_candidate_alias":
            _error(
                errors,
                f"{prefix}.routing_status",
                "unresolved feedback routes must use unresolved_candidate_alias status",
                actual=route.get("routing_status"),
            )
        if matched_candidate_id or matched_alias:
            _error(
                errors,
                f"{prefix}.matched_candidate_id",
                "unresolved feedback must not claim a matched candidate or alias",
                matched_candidate_id=matched_candidate_id,
                matched_candidate_alias=matched_alias,
            )
        if not blockers:
            _error(errors, f"{prefix}.routing_blockers", "unresolved feedback must explain routing blockers")
    if not _string(route.get("observation_id")):
        _error(errors, f"{prefix}.observation_id", "feedback route observation_id is required")
    if not _as_list(route.get("candidate_aliases")):
        _error(errors, f"{prefix}.candidate_aliases", "feedback route must preserve checked candidate aliases")


def _check_source_artifact_provenance(
    errors: List[Dict[str, Any]],
    plan: Mapping[str, Any],
    *,
    applied_feedback_count: int,
) -> None:
    provenance = _as_mapping(plan.get("source_artifact_provenance"))
    if applied_feedback_count > 0 and not provenance:
        _error(
            errors,
            "source_artifact_provenance",
            "plans with applied feedback must bind checkpoint/feedback source refs to payload hashes",
        )
        return

    for role, (ref_field, canonical_name, schema_required) in _SOURCE_PROVENANCE_REQUIRED_ROLES.items():
        ref = _string(plan.get(ref_field))
        if applied_feedback_count > 0 and not ref:
            _error(errors, ref_field, f"{ref_field} is required for feedback-informed search plans")
        if ref and Path(ref).name != canonical_name:
            _error(
                errors,
                ref_field,
                "search iteration source refs must use the canonical artifact name",
                expected=canonical_name,
                actual=ref,
            )

        row = _as_mapping(provenance.get(role))
        if not row:
            if applied_feedback_count > 0 or ref:
                _error(
                    errors,
                    f"source_artifact_provenance.{role}",
                    "source provenance row is required for named search iteration source refs",
                    ref_field=ref_field,
                    ref=ref,
                )
            continue

        if _string(row.get("role")) != role:
            _error(
                errors,
                f"source_artifact_provenance.{role}.role",
                "source provenance role must match its map key",
                expected=role,
                actual=row.get("role"),
            )
        if _string(row.get("ref")) != ref:
            _error(
                errors,
                f"source_artifact_provenance.{role}.ref",
                "source provenance ref must match the top-level search iteration ref",
                expected=ref,
                actual=row.get("ref"),
            )
        payload_hash = _string(row.get("payload_hash"))
        if not payload_hash.startswith("sha256:"):
            _error(
                errors,
                f"source_artifact_provenance.{role}.payload_hash",
                "source provenance payload_hash must use sha256: prefix",
                actual=row.get("payload_hash"),
            )
        if schema_required and not _string(row.get("schema_version")):
            _error(
                errors,
                f"source_artifact_provenance.{role}.schema_version",
                "source provenance must preserve the consumed artifact schema_version",
            )


def _scope_error_summaries(errors: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "field": error.get("field"),
            "message": error.get("message"),
            "scope_field": error.get("scope_field"),
            "expected": error.get("expected"),
            "actual": error.get("actual"),
            "sources": error.get("sources"),
            "observed_values": error.get("observed_values"),
            "sources_by_value": error.get("sources_by_value"),
        }
        for error in errors
        if error.get("scope_field") in CAMPAIGN_SCOPE_FIELDS
    ]


def validate_search_iteration_plan(plan: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a Step2 search-iteration plan without granting execution authority."""

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    plan_scope = _plan_scope(plan)

    if plan.get("schema_version") != SEARCH_ITERATION_PLAN_SCHEMA:
        _error(
            errors,
            "schema_version",
            "search iteration plan schema_version must match the canonical contract",
            expected=SEARCH_ITERATION_PLAN_SCHEMA,
            actual=plan.get("schema_version"),
        )

    if plan.get("top_k_queue_provenance_only") is not True:
        _error(
            errors,
            "top_k_queue_provenance_only",
            "top-k/search proposal queue must remain provenance-only",
        )
    if plan.get("hidden_evidence_fanout_allowed") is not False:
        _error(
            errors,
            "hidden_evidence_fanout_allowed",
            "search iteration plans must not authorize hidden evidence fanout",
        )
    _check_false_flags(errors, plan, prefix="plan")

    _check_list_container(
        errors,
        plan,
        field_name="next_candidates",
        field_path="next_candidates",
        row_description="next_candidates",
    )
    _check_list_container(
        errors,
        plan,
        field_name="next_step3_admission_candidates",
        field_path="next_step3_admission_candidates",
        row_description="next_step3_admission_candidates",
    )
    next_candidates = _as_list(plan.get("next_candidates"))
    admission_candidates = _as_list(plan.get("next_step3_admission_candidates"))
    next_proposed_count = _non_negative_int_value(
        errors,
        field="next_proposed_count",
        value=plan.get("next_proposed_count"),
        default=-1,
    )
    if next_proposed_count != len(next_candidates):
        _error(
            errors,
            "next_proposed_count",
            "next_proposed_count must equal len(next_candidates)",
            declared=plan.get("next_proposed_count"),
            actual=len(next_candidates),
        )
    next_step3_admission_candidate_count = _non_negative_int_value(
        errors,
        field="next_step3_admission_candidate_count",
        value=plan.get("next_step3_admission_candidate_count"),
        default=-1,
    )
    if next_step3_admission_candidate_count != len(admission_candidates):
        _error(
            errors,
            "next_step3_admission_candidate_count",
            "next_step3_admission_candidate_count must equal len(next_step3_admission_candidates)",
            declared=plan.get("next_step3_admission_candidate_count"),
            actual=len(admission_candidates),
        )
    step3_admission_queue_ref = _string(plan.get("next_step3_admission_queue_ref"))
    if not step3_admission_queue_ref:
        _error(
            errors,
            "next_step3_admission_queue_ref",
            "Step3 admission queue reference is required before any candidate can execute",
        )
    else:
        invalid_queue_ref_reason = _invalid_run_local_ref_reason(step3_admission_queue_ref)
        if invalid_queue_ref_reason:
            _error(
                errors,
                "next_step3_admission_queue_ref",
                "Step3 admission queue reference must be a run-local relative artifact path",
                actual=step3_admission_queue_ref,
                reason=invalid_queue_ref_reason,
            )
    if _string(plan.get("step3_admission_queue")) != step3_admission_queue_ref:
        _error(
            errors,
            "step3_admission_queue",
            "step3_admission_queue must match next_step3_admission_queue_ref",
            expected=step3_admission_queue_ref,
            actual=plan.get("step3_admission_queue"),
        )

    candidate_ids = _candidate_ids(next_candidates)
    admission_ids = _candidate_ids(admission_candidates)
    duplicate_candidate_ids = _duplicate_values(candidate_ids)
    duplicate_admission_ids = _duplicate_values(admission_ids)
    if duplicate_candidate_ids:
        _error(errors, "next_candidates", "candidate IDs must be unique", duplicates=duplicate_candidate_ids)
    if duplicate_admission_ids:
        _error(errors, "next_step3_admission_candidates", "admission candidate IDs must be unique", duplicates=duplicate_admission_ids)
    duplicate_candidate_aliases = _row_alias_duplicates(next_candidates)
    if duplicate_candidate_aliases:
        _error(
            errors,
            "next_candidates.aliases",
            "candidate aliases must identify at most one proposal candidate",
            duplicates=duplicate_candidate_aliases,
        )
    duplicate_admission_aliases = _row_alias_duplicates(admission_candidates)
    if duplicate_admission_aliases:
        _error(
            errors,
            "next_step3_admission_candidates.aliases",
            "admission candidate aliases must identify at most one Step3 materialization candidate",
            duplicates=duplicate_admission_aliases,
        )

    candidate_by_id: Dict[str, Mapping[str, Any]] = {}
    eligible_candidate_ids: set[str] = set()
    parameter_hashes: List[str] = []
    complete_grid_seen = True
    bounded_enumeration_seen = False

    for index, raw_candidate in enumerate(next_candidates):
        prefix = f"next_candidates[{index}]"
        if not isinstance(raw_candidate, Mapping):
            _error(errors, prefix, "candidate row must be a mapping")
            continue
        candidate_id = _string(raw_candidate.get("candidate_id"))
        if not candidate_id:
            _error(errors, f"{prefix}.candidate_id", "candidate_id is required")
            continue
        _check_row_scope_matches_plan(
            errors,
            raw_candidate,
            prefix=prefix,
            plan_scope=plan_scope,
        )
        if _string(raw_candidate.get("search_policy_candidate_id")) not in ("", candidate_id):
            _error(
                errors,
                f"{prefix}.search_policy_candidate_id",
                "proposal search_policy_candidate_id must remain the local candidate_id",
                expected=candidate_id,
                actual=raw_candidate.get("search_policy_candidate_id"),
            )
        candidate_by_id[candidate_id] = raw_candidate
        _check_provenance_flags(errors, raw_candidate, prefix=prefix)
        if raw_candidate.get("admission_required_before_execution") != step3_admission_queue_ref:
            _error(
                errors,
                f"{prefix}.admission_required_before_execution",
                "proposal candidates must require the canonical Step3 admission queue before execution",
                expected=step3_admission_queue_ref,
                actual=raw_candidate.get("admission_required_before_execution"),
            )

        parameter_hash = _string(raw_candidate.get("parameter_hash"))
        parameter_hashes.append(parameter_hash)
        if not parameter_hash.startswith("sha256:"):
            _error(errors, f"{prefix}.parameter_hash", "parameter_hash must use sha256: prefix")
        if not _as_mapping(raw_candidate.get("parameters")):
            _error(errors, f"{prefix}.parameters", "candidate parameters must be present")

        provenance = _as_mapping(raw_candidate.get("provenance"))
        if not provenance:
            _error(errors, f"{prefix}.provenance", "candidate provenance is required")
        missing_excludes = sorted(
            set(_REQUIRED_CANDIDATE_PROVENANCE_EXCLUDES)
            - set(_as_list(provenance.get("candidate_identity_excludes")))
        )
        if missing_excludes:
            _error(
                errors,
                f"{prefix}.provenance.candidate_identity_excludes",
                "candidate identity must exclude transient search-order fields",
                missing=missing_excludes,
            )

        enumeration = _as_mapping(provenance.get("search_space_enumeration"))
        if enumeration:
            grid_count = _non_negative_int_value(
                errors,
                field=f"{prefix}.provenance.search_space_enumeration.grid_candidate_count",
                value=enumeration.get("grid_candidate_count"),
                default=-1,
            )
            enumerated_count = _non_negative_int_value(
                errors,
                field=f"{prefix}.provenance.search_space_enumeration.grid_candidate_enumerated_count",
                value=enumeration.get("grid_candidate_enumerated_count"),
                default=-1,
            )
            if grid_count < 0 or enumerated_count < 0 or enumerated_count > grid_count:
                _error(
                    errors,
                    f"{prefix}.provenance.search_space_enumeration",
                    "grid enumeration counts must be non-negative and bounded by the grid size",
                    grid_candidate_count=enumeration.get("grid_candidate_count"),
                    grid_candidate_enumerated_count=enumeration.get("grid_candidate_enumerated_count"),
                )
            complete_grid = enumeration.get("complete_grid_enumeration") is True
            complete_grid_seen = complete_grid_seen and complete_grid
            if not complete_grid:
                bounded_enumeration_seen = True
                if enumeration.get("max_candidate_enumeration") in (None, ""):
                    _error(
                        errors,
                        f"{prefix}.provenance.search_space_enumeration.max_candidate_enumeration",
                        "incomplete grid enumeration must declare max_candidate_enumeration",
                    )
        else:
            complete_grid_seen = False
            _error(
                errors,
                f"{prefix}.provenance.search_space_enumeration",
                "candidate must preserve explicit search-space enumeration provenance",
            )

        eligible = raw_candidate.get(SIMULATION_ELIGIBLE) is True
        step3_evaluable = raw_candidate.get(STEP3_EVALUABLE) is True
        step2_screenable = raw_candidate.get(STEP2_SCREENABLE) is True
        blockers = _as_list(raw_candidate.get(SIMULATION_BLOCKERS))
        if eligible:
            eligible_candidate_ids.add(candidate_id)
            if not step3_evaluable or not step2_screenable:
                _error(
                    errors,
                    f"{prefix}.{SIMULATION_ELIGIBLE}",
                    "simulation_eligible candidates must also be step2_screenable and step3_evaluable",
                )
            if blockers:
                _error(
                    errors,
                    f"{prefix}.{SIMULATION_BLOCKERS}",
                    "simulation_eligible candidates must not carry simulation_blockers",
                    blockers=blockers,
                )
            if raw_candidate.get("queue_state") != "scheduled_for_simulation":
                _error(
                    errors,
                    f"{prefix}.queue_state",
                    "simulation_eligible candidates must be scheduled_for_simulation at proposal level",
                    actual=raw_candidate.get("queue_state"),
                )
        else:
            if not blockers:
                _error(
                    errors,
                    f"{prefix}.{SIMULATION_BLOCKERS}",
                    "non-eligible candidates must explain simulation blockers",
                )

    duplicate_parameter_hashes = _duplicate_values(parameter_hashes)
    if duplicate_parameter_hashes:
        _error(
            errors,
            "next_candidates.parameter_hash",
            "parameter hashes must uniquely identify proposal parameter records",
            duplicates=duplicate_parameter_hashes,
        )

    admission_id_set = set(admission_ids)
    missing_admission_ids = sorted(eligible_candidate_ids - admission_id_set)
    extra_admission_ids = sorted(admission_id_set - eligible_candidate_ids)
    if missing_admission_ids:
        _error(
            errors,
            "next_step3_admission_candidates",
            "every simulation_eligible proposal must be represented in admission candidates",
            missing_candidate_ids=missing_admission_ids,
        )
    if extra_admission_ids:
        _error(
            errors,
            "next_step3_admission_candidates",
            "admission candidates must be a subset of simulation_eligible proposals",
            extra_candidate_ids=extra_admission_ids,
        )

    for index, raw_admission in enumerate(admission_candidates):
        prefix = f"next_step3_admission_candidates[{index}]"
        if not isinstance(raw_admission, Mapping):
            _error(errors, prefix, "admission row must be a mapping")
            continue
        _check_row_scope_matches_plan(
            errors,
            raw_admission,
            prefix=prefix,
            plan_scope=plan_scope,
        )
        _check_provenance_flags(errors, raw_admission, prefix=prefix)
        candidate_id = _string(raw_admission.get("candidate_id"))
        proposal = candidate_by_id.get(candidate_id)
        if proposal is None:
            continue
        _check_admission_projection_matches_proposal(
            errors,
            proposal=proposal,
            admission=raw_admission,
            prefix=prefix,
        )
        if raw_admission.get("admission_status") != "requires_step3_queue_materialization":
            _error(
                errors,
                f"{prefix}.admission_status",
                "admission candidates must require canonical Step3 queue materialization",
                actual=raw_admission.get("admission_status"),
            )
        if raw_admission.get("admission_required_before_execution") != step3_admission_queue_ref:
            _error(
                errors,
                f"{prefix}.admission_required_before_execution",
                "admission candidates must require the canonical Step3 admission queue before execution",
                expected=step3_admission_queue_ref,
                actual=raw_admission.get("admission_required_before_execution"),
            )
        if raw_admission.get("claim_status") != "step2_materialization_candidate_only":
            _error(
                errors,
                f"{prefix}.claim_status",
                "admission candidate claim_status must remain Step2 materialization only",
                actual=raw_admission.get("claim_status"),
            )
        if raw_admission.get("execution_allowed") is True:
            _error(errors, f"{prefix}.execution_allowed", "admission candidate cannot execute directly")
        if _string(proposal.get("complete_dse_candidate_id")):
            for key in (
                "complete_dse_candidate_id",
                "architecture_id",
                "mapping_candidate_id",
                "candidate_identity_policy",
            ):
                if not _string(raw_admission.get(key)):
                    _error(errors, f"{prefix}.{key}", f"{key} is required for complete-DSE admission bridge")
            if not _as_mapping(raw_admission.get("candidate_identity")):
                _error(
                    errors,
                    f"{prefix}.candidate_identity",
                    "candidate_identity is required for complete-DSE admission bridge",
                )

    checkpoint_candidates_by_id = _check_next_checkpoint_consistency(
        errors,
        plan=plan,
        proposals_by_id=candidate_by_id,
        plan_scope=plan_scope,
    )
    checkpoint_feedback_alias_owners, ambiguous_checkpoint_feedback_aliases = _feedback_alias_owner_maps(
        _as_list(_as_mapping(plan.get("next_checkpoint")).get("candidates"))
    )

    next_best_candidate_id = _string(plan.get("next_best_candidate_id"))
    if next_best_candidate_id and next_best_candidate_id not in candidate_by_id:
        _error(
            errors,
            "next_best_candidate_id",
            "next_best_candidate_id must refer to a next candidate",
            actual=next_best_candidate_id,
        )
    applied_feedback_count = _non_negative_int_value(
        errors,
        field="applied_feedback_count",
        value=plan.get("applied_feedback_count"),
        default=0,
    )
    if applied_feedback_count > 0:
        for field in CAMPAIGN_SCOPE_FIELDS:
            if not _string(plan.get(field)):
                _error(
                    errors,
                    field,
                    "feedback-informed search plans must declare top-level Campaign/Workload/Trial scope",
                    scope_field=field,
                )
    input_observed_count = _non_negative_int_value(
        errors,
        field="input_observed_count",
        value=plan.get("input_observed_count"),
        default=0,
    )
    output_observed_count = _non_negative_int_value(
        errors,
        field="output_observed_count",
        value=plan.get("output_observed_count"),
        default=0,
    )
    candidate_alias_count = _non_negative_int_value(
        errors,
        field="candidate_alias_count",
        value=plan.get("candidate_alias_count"),
        default=0,
    )
    if applied_feedback_count > 0 and candidate_alias_count <= 0:
        _error(
            errors,
            "candidate_alias_count",
            "plans with applied feedback must expose candidate aliases used for routing",
        )
    _check_source_artifact_provenance(
        errors,
        plan,
        applied_feedback_count=applied_feedback_count,
    )

    _check_list_container(
        errors,
        plan,
        field_name="feedback_observation_routing",
        field_path="feedback_observation_routing",
        row_description="feedback_observation_routing",
    )
    for field in _REQUIRED_FEEDBACK_CONTRACT_FIELDS:
        if field not in plan:
            _error(
                errors,
                field,
                "search iteration plans must preserve the explicit feedback routing contract",
            )
    feedback_routes = _as_list(plan.get("feedback_observation_routing"))
    route_count_declared = plan.get("feedback_observation_count")
    unresolved_count_declared = plan.get("feedback_unresolved_observation_count")
    if applied_feedback_count > 0 and not feedback_routes:
        _error(
            errors,
            "feedback_observation_routing",
            "plans with applied feedback must preserve feedback observation routing rows",
        )
    route_count = _non_negative_int_value(
        errors,
        field="feedback_observation_count",
        value=route_count_declared,
        default=-1,
    )
    unresolved_count = _non_negative_int_value(
        errors,
        field="feedback_unresolved_observation_count",
        value=unresolved_count_declared,
        default=-1,
    )
    if route_count != len(feedback_routes):
        _error(
            errors,
            "feedback_observation_count",
            "feedback_observation_count must equal len(feedback_observation_routing)",
            declared=route_count_declared,
            actual=len(feedback_routes),
        )
    if applied_feedback_count > 0 and "input_observed_count" not in plan:
        _error(
            errors,
            "input_observed_count",
            "plans with applied feedback must declare the input observed-count checkpoint",
        )
    if applied_feedback_count > 0 and "output_observed_count" not in plan:
        _error(
            errors,
            "output_observed_count",
            "plans with applied feedback must declare the output observed-count checkpoint",
        )
    if applied_feedback_count > 0 and not checkpoint_candidates_by_id:
        _error(
            errors,
            "next_checkpoint.candidates",
            "plans with applied feedback must preserve next_checkpoint candidates for route auditing",
        )
    checkpoint = _as_mapping(plan.get("next_checkpoint"))
    checkpoint_observed_count = checkpoint.get("observed_count")
    if applied_feedback_count > 0 and "observed_count" not in checkpoint:
        _error(
            errors,
            "next_checkpoint.observed_count",
            "plans with applied feedback must preserve next_checkpoint observed_count",
        )
    elif checkpoint_observed_count is not None and _non_negative_int_value(
        errors,
        field="next_checkpoint.observed_count",
        value=checkpoint_observed_count,
        default=-1,
    ) != output_observed_count:
        _error(
            errors,
            "next_checkpoint.observed_count",
            "next_checkpoint observed_count must match output_observed_count",
            declared=checkpoint_observed_count,
            actual=output_observed_count,
        )
    if output_observed_count != input_observed_count + applied_feedback_count:
        _error(
            errors,
            "output_observed_count",
            "output_observed_count must equal input_observed_count plus applied_feedback_count",
            input_observed_count=input_observed_count,
            applied_feedback_count=applied_feedback_count,
            actual=output_observed_count,
        )
    routed_route_count = 0
    unresolved_route_count = 0
    for index, raw_route in enumerate(feedback_routes):
        prefix = f"feedback_observation_routing[{index}]"
        if not isinstance(raw_route, Mapping):
            _error(errors, prefix, "feedback observation route must be a mapping")
            continue
        _check_row_scope_matches_plan(
            errors,
            raw_route,
            prefix=prefix,
            plan_scope=plan_scope,
        )
        if raw_route.get("routed_to_search_policy") is True:
            routed_route_count += 1
            matched_candidate_id = _string(raw_route.get("matched_candidate_id"))
            if checkpoint_candidates_by_id and matched_candidate_id not in checkpoint_candidates_by_id:
                _error(
                    errors,
                    f"{prefix}.matched_candidate_id",
                    "routed feedback matched_candidate_id must exist in next_checkpoint candidates",
                    actual=matched_candidate_id,
                )
            if matched_candidate_id and matched_candidate_id not in candidate_by_id:
                _error(
                    errors,
                    f"{prefix}.matched_candidate_id",
                    "routed feedback matched_candidate_id must refer to a next candidate proposal",
                    actual=matched_candidate_id,
                )
            matched_candidate_alias = _string(raw_route.get("matched_candidate_alias"))
            if matched_candidate_alias:
                ambiguous_alias_owners = ambiguous_checkpoint_feedback_aliases.get(matched_candidate_alias)
                if ambiguous_alias_owners:
                    _error(
                        errors,
                        f"{prefix}.matched_candidate_alias",
                        "routed feedback matched_candidate_alias must have exactly one checkpoint candidate owner",
                        matched_candidate_id=matched_candidate_id,
                        actual=matched_candidate_alias,
                        candidate_owners=ambiguous_alias_owners,
                    )
                else:
                    alias_owner = checkpoint_feedback_alias_owners.get(matched_candidate_alias)
                    if not alias_owner:
                        _error(
                            errors,
                            f"{prefix}.matched_candidate_alias",
                            "routed feedback matched_candidate_alias must resolve to the matched checkpoint candidate through a unique alias owner",
                            matched_candidate_id=matched_candidate_id,
                            actual=matched_candidate_alias,
                        )
                    elif alias_owner != matched_candidate_id:
                        _error(
                            errors,
                            f"{prefix}.matched_candidate_alias",
                            "routed feedback matched_candidate_alias must resolve to the matched checkpoint candidate through a unique alias owner",
                            matched_candidate_id=matched_candidate_id,
                            actual=matched_candidate_alias,
                            alias_owner=alias_owner,
                        )
            route_candidate_aliases = [
                _string(alias)
                for alias in _as_list(raw_route.get("candidate_aliases"))
                if _string(alias)
            ]
            route_aliases = set(route_candidate_aliases)
            checked_route_aliases = [
                _string(alias)
                for alias in _as_list(raw_route.get("checked_candidate_aliases"))
                if _string(alias)
            ]
            source_candidate_id = _string(raw_route.get("source_candidate_id"))
            if (
                source_candidate_id
                and route_candidate_aliases
                and source_candidate_id != route_candidate_aliases[0]
            ):
                _error(
                    errors,
                    f"{prefix}.source_candidate_id",
                    "feedback route source_candidate_id must match the first candidate_aliases entry",
                    source_candidate_id=source_candidate_id,
                    first_candidate_alias=route_candidate_aliases[0],
                )
            candidate_refs = _as_mapping(raw_route.get("candidate_refs"))
            for ref_field in _FEEDBACK_ROUTE_CANDIDATE_REF_ALIAS_FIELDS:
                ref_alias = _string(candidate_refs.get(ref_field))
                if ref_alias and ref_alias not in route_aliases:
                    _error(
                        errors,
                        f"{prefix}.candidate_refs.{ref_field}",
                        "feedback route candidate_refs aliases must be preserved in candidate_aliases",
                        candidate_ref_alias=ref_alias,
                        candidate_aliases=route_candidate_aliases,
                    )
            metrics = _as_mapping(raw_route.get("metrics"))
            metric_source_alias = _string(metrics.get("step4_feedback_source_candidate_id"))
            if metric_source_alias and source_candidate_id and metric_source_alias != source_candidate_id:
                _error(
                    errors,
                    f"{prefix}.metrics.step4_feedback_source_candidate_id",
                    "feedback metric source alias must match route source_candidate_id",
                    metric_source_alias=metric_source_alias,
                    source_candidate_id=source_candidate_id,
                )
            if matched_candidate_alias and matched_candidate_alias not in route_aliases:
                _error(
                    errors,
                    f"{prefix}.candidate_aliases",
                    "routed feedback candidate_aliases must include matched_candidate_alias",
                    matched_candidate_alias=matched_candidate_alias,
                    candidate_aliases=sorted(route_aliases),
                )
            if matched_candidate_alias:
                if matched_candidate_alias not in set(checked_route_aliases):
                    _error(
                        errors,
                        f"{prefix}.checked_candidate_aliases",
                        "routed feedback checked_candidate_aliases must include matched_candidate_alias",
                        matched_candidate_alias=matched_candidate_alias,
                        checked_candidate_aliases=checked_route_aliases,
                    )
                elif checked_route_aliases[-1] != matched_candidate_alias:
                    _error(
                        errors,
                        f"{prefix}.checked_candidate_aliases",
                        "routed feedback checked_candidate_aliases must stop at matched_candidate_alias",
                        matched_candidate_alias=matched_candidate_alias,
                        checked_candidate_aliases=checked_route_aliases,
                    )
            metric_matched_alias = _string(metrics.get("step4_feedback_matched_candidate_alias"))
            if metric_matched_alias and metric_matched_alias != matched_candidate_alias:
                _error(
                    errors,
                    f"{prefix}.metrics.step4_feedback_matched_candidate_alias",
                    "feedback metric matched alias must match route matched_candidate_alias",
                    metric_matched_alias=metric_matched_alias,
                    matched_candidate_alias=matched_candidate_alias,
                )
        else:
            unresolved_route_count += 1
        _check_feedback_observation_route(errors, raw_route, prefix=prefix)
    if applied_feedback_count != routed_route_count:
        _error(
            errors,
            "applied_feedback_count",
            "applied_feedback_count must match routed feedback observation rows",
            declared=applied_feedback_count,
            actual=routed_route_count,
        )
    if unresolved_count != unresolved_route_count:
        _error(
            errors,
            "feedback_unresolved_observation_count",
            "feedback_unresolved_observation_count must match unresolved feedback routes",
            declared=unresolved_count_declared,
            actual=unresolved_route_count,
        )
    expected_status = (
        "no_feedback_observations"
        if not feedback_routes
        else "all_feedback_observations_routed"
        if unresolved_route_count == 0
        else "partial_unresolved_feedback_observations"
    )
    if plan.get("feedback_routing_status") != expected_status:
        _error(
            errors,
            "feedback_routing_status",
            "feedback_routing_status must summarize feedback route resolution",
            expected=expected_status,
            actual=plan.get("feedback_routing_status"),
        )

    scope_errors = _scope_error_summaries(errors)
    scope_valid = not scope_errors
    valid = not errors
    return {
        "schema_version": SEARCH_ITERATION_PLAN_VALIDATION_SCHEMA,
        "status": "passed" if valid else "failed",
        "valid": valid,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "campaign_scope_validation": {
            "schema_version": "dse.campaign.scope_validation.v1",
            "status": "passed" if scope_valid else "failed",
            "valid": scope_valid,
            "scope_fields": list(CAMPAIGN_SCOPE_FIELDS),
            "plan_scope": dict(plan_scope),
            "row_scope_error_count": len(scope_errors),
            "row_scope_errors": scope_errors,
        },
        "summary": {
            "next_candidate_count": len(next_candidates),
            "eligible_candidate_count": len(eligible_candidate_ids),
            "admission_candidate_count": len(admission_candidates),
            "duplicate_candidate_alias_count": len(duplicate_candidate_aliases),
            "duplicate_admission_alias_count": len(duplicate_admission_aliases),
            "ambiguous_checkpoint_feedback_alias_count": len(ambiguous_checkpoint_feedback_aliases),
            "complete_grid_enumeration": complete_grid_seen,
            "bounded_enumeration_seen": bounded_enumeration_seen,
            "next_best_candidate_id": next_best_candidate_id or None,
            "feedback_observation_count": len(feedback_routes),
            "applied_feedback_count": applied_feedback_count,
        },
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Search-iteration plan validation proves internal Step2 proposal/admission "
            "consistency only. It does not execute Step3, prove timing/numerical/PPA "
            "evidence, or select a trusted final winner."
        ),
    }


def load_search_iteration_plan(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_search_iteration_plan_validation(
    plan_path: Path,
    out_dir: Path,
    *,
    artifact_name: str = "search_iteration_plan_validation.json",
) -> Dict[str, Any]:
    plan = load_search_iteration_plan(plan_path)
    validation = validate_search_iteration_plan(plan)
    out_dir.mkdir(parents=True, exist_ok=True)
    validation_path = out_dir / artifact_name
    validation_path.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "schema_version": "dse.step2.search_iteration_plan_validation_status.v1",
        "status": validation["status"],
        "valid": validation["valid"],
        "plan": str(plan_path),
        "validation": artifact_name,
        "error_count": validation["error_count"],
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
    }
    (out_dir / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status


__all__ = [
    "SEARCH_ITERATION_PLAN_SCHEMA",
    "SEARCH_ITERATION_PLAN_VALIDATION_SCHEMA",
    "load_search_iteration_plan",
    "validate_search_iteration_plan",
    "write_search_iteration_plan_validation",
]
