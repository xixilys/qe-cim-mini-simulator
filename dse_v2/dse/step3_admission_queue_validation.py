#!/usr/bin/env python3
"""Fail-closed validation for canonical Step3 admission queues.

The validator is domain-neutral.  It proves that Campaign Step3 work plans are
backed by explicit entries in ``step2/step3_simulation_queue.json`` and keeps
search-feedback proposals or materialization requests from masquerading as
executed Step3 work.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


STEP3_ADMISSION_QUEUE_VALIDATION_SCHEMA = "dse.step3.admission_queue_validation.v1"
STEP3_SIMULATION_QUEUE_SCHEMA = "dse.step3.simulation_queue.v1"
ALLOWED_QUEUE_MODES = {"selected-entry-only", "complete-dse-release-universe"}
FALSE_CLAIM_FLAGS = (
    "trusted_final_claim",
    "release_completion_eligible",
    "deliverable_complete",
)
MATERIALIZED_QUEUE_IDENTITY_FIELDS = (
    "queue_entry_id",
    "candidate_id",
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
    "mapping_parameter_hash",
    "candidate_record_hash",
    "release_subset_hash",
)
SEARCH_ADMISSION_QUEUE_IDENTITY_FIELDS = (
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
ROW_IDENTITY_NESTED_MAPS = ("parameters", "candidate_refs", "provenance")
ROW_IDENTITY_FIELDS = tuple(
    dict.fromkeys(
        MATERIALIZED_QUEUE_IDENTITY_FIELDS + SEARCH_ADMISSION_QUEUE_IDENTITY_FIELDS
    )
)
SCHEDULED_QUEUE_VALIDITY_FIELDS = (
    "step2_screenable",
    "step3_evaluable",
    "simulation_eligible",
    "simulation_blockers",
    "claim_status",
    "admission_source",
)
SCHEDULED_QUEUE_TRUE_FIELDS = (
    "step2_screenable",
    "step3_evaluable",
    "simulation_eligible",
)
PROPOSAL_ONLY_ADMISSION_SOURCE_BASENAMES = {
    "top_k_candidate_queue.json",
    "search_iteration_plan.json",
    "search_iteration_plan_validation.json",
}
FORBIDDEN_SCHEDULED_QUEUE_CLAIM_STATUSES = {
    "deliverable_complete",
    "release_complete",
    "release_completion_eligible",
    "trusted_final_claim",
    "trusted_final_winner",
    "final_winner",
}
ALLOWED_ADMISSION_STATUSES = {
    "proposal_only",
    "step2_materialization_required",
    "step3_queue_write_required",
}


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


def _int_count_or_default(
    errors: List[Dict[str, Any]],
    *,
    field: str,
    value: Any,
    default: int,
    required: bool = False,
) -> int:
    if value is None:
        if required:
            _error(
                errors,
                field,
                "count field is required",
                actual=None,
                actual_type="NoneType",
            )
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        _error(
            errors,
            field,
            "count field must be a non-negative integer",
            actual=value,
            actual_type=type(value).__name__,
        )
        return default
    if value < 0:
        _error(
            errors,
            field,
            "count field must be a non-negative integer",
            actual=value,
            actual_type=type(value).__name__,
        )
        return default
    return value


def _error(errors: List[Dict[str, Any]], field: str, message: str, **extra: Any) -> None:
    row = {"field": field, "message": message}
    row.update(extra)
    errors.append(row)


def _warning(warnings: List[Dict[str, Any]], field: str, message: str, **extra: Any) -> None:
    row = {"field": field, "message": message}
    row.update(extra)
    warnings.append(row)


def _stable_hash_without(payload: Mapping[str, Any], *excluded_keys: str) -> str:
    encoded = json.dumps(
        {key: value for key, value in payload.items() if key not in excluded_keys},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _append_alias(aliases: List[str], value: Any) -> None:
    alias = _string(value)
    if alias and alias not in aliases:
        aliases.append(alias)


def _row_aliases(row: Mapping[str, Any]) -> List[str]:
    aliases: List[str] = []
    parameters = _as_mapping(row.get("parameters"))
    provenance = _as_mapping(row.get("provenance"))
    for key in (
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
    ):
        _append_alias(aliases, row.get(key))
        _append_alias(aliases, parameters.get(key))
        _append_alias(aliases, provenance.get(key))
    return aliases


def _duplicate_values(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if not value:
            continue
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _queue_alias_index(entries: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        for alias in _row_aliases(entry):
            index.setdefault(alias, dict(entry))
    return index


def _queue_alias_duplicates(entries: Sequence[Mapping[str, Any]]) -> Dict[str, List[str]]:
    owners_by_alias: Dict[str, set[str]] = {}
    for index, entry in enumerate(entries):
        owner = _string(entry.get("queue_entry_id")) or _string(entry.get("candidate_id")) or f"entry[{index}]"
        for alias in _row_aliases(entry):
            owners_by_alias.setdefault(alias, set()).add(owner)
    return {
        alias: sorted(owners)
        for alias, owners in owners_by_alias.items()
        if alias and len(owners) > 1
    }


def _row_alias_occurrence_duplicates(entries: Sequence[Mapping[str, Any]]) -> Dict[str, List[str]]:
    owners_by_alias: Dict[str, List[str]] = {}
    for index, entry in enumerate(entries):
        owner = (
            _string(entry.get("plan_entry_id"))
            or _string(entry.get("request_id"))
            or _string(entry.get("queue_entry_id"))
            or _string(entry.get("candidate_id"))
            or _string(entry.get("search_policy_candidate_id"))
            or f"entry[{index}]"
        )
        for alias in _row_aliases(entry):
            owners_by_alias.setdefault(alias, []).append(owner)
    return {
        alias: sorted(owners)
        for alias, owners in owners_by_alias.items()
        if alias and len(owners) > 1
    }


def _matching_queue_entry(row: Mapping[str, Any], alias_index: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    for alias in _row_aliases(row):
        if alias in alias_index:
            return dict(alias_index[alias])
    return {}


_DEFINITIVE_QUEUE_MATCH_FIELDS = (
    "queue_entry_id",
    "candidate_id",
    "complete_dse_candidate_id",
    "parameter_hash",
    "search_policy_parameter_hash",
    "candidate_record_hash",
    "release_subset_hash",
)


def _has_identity_overlap(row: Mapping[str, Any], queue_entry: Mapping[str, Any], fields: Sequence[str]) -> bool:
    for field in fields:
        row_values = set(_row_identity_values(row, field))
        queue_values = set(_row_identity_values(queue_entry, field))
        if row_values and queue_values and row_values.intersection(queue_values):
            return True
    return False


def _identity_preserving_queue_match(
    row: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str],
) -> Dict[str, Any]:
    """Return a materialized queue row only when shared identity is consistent.

    Proposal rows can share broad aliases such as ``mapping_candidate_id`` with
    an existing Step3 row while still carrying a distinct SearchPolicy
    ``parameter_hash`` namespace.  Treating the first broad alias as a queue
    match makes those proposal rows fail validation even though they still need
    Step2 materialization.  A row is therefore considered already materialized
    only when it shares at least one alias with a queue entry and every
    populated identity field shared by both rows agrees.
    """

    row_aliases = set(_row_aliases(row))
    if not row_aliases:
        return {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if not row_aliases.intersection(_row_aliases(entry)):
            continue
        if not _has_identity_overlap(row, entry, _DEFINITIVE_QUEUE_MATCH_FIELDS):
            continue
        mismatch = False
        for field in fields:
            row_values = set(_row_identity_values(row, field))
            queue_values = set(_row_identity_values(entry, field))
            if row_values and queue_values and not row_values.intersection(queue_values):
                mismatch = True
                break
        if not mismatch:
            return dict(entry)
    return {}


def _row_nested_values(
    row: Mapping[str, Any],
    field: str,
    *,
    nested_maps: Sequence[str],
) -> Dict[str, List[str]]:
    values_by_source: Dict[str, List[str]] = {}
    direct = _string(row.get(field))
    if direct:
        values_by_source.setdefault(direct, []).append("direct")
    for nested_key in nested_maps:
        nested = _as_mapping(row.get(nested_key))
        nested_value = _string(nested.get(field))
        if nested_value:
            values_by_source.setdefault(nested_value, []).append(nested_key)
    return values_by_source


def _row_identity_values(row: Mapping[str, Any], field: str) -> Dict[str, List[str]]:
    return _row_nested_values(row, field, nested_maps=ROW_IDENTITY_NESTED_MAPS)


def _candidate_identity_payload_values(row: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    values_by_payload: Dict[str, Dict[str, Any]] = {}
    direct = row.get("candidate_identity")
    if isinstance(direct, Mapping):
        payload = dict(direct)
        payload_key = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        values_by_payload.setdefault(payload_key, {"payload": payload, "sources": []})
        values_by_payload[payload_key]["sources"].append("direct")
    for nested_key in ROW_IDENTITY_NESTED_MAPS:
        nested = _as_mapping(row.get(nested_key))
        nested_identity = nested.get("candidate_identity")
        if not isinstance(nested_identity, Mapping):
            continue
        payload = dict(nested_identity)
        payload_key = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        values_by_payload.setdefault(payload_key, {"payload": payload, "sources": []})
        values_by_payload[payload_key]["sources"].append(nested_key)
    return values_by_payload


def _check_candidate_identity_payload_consistency(
    errors: List[Dict[str, Any]],
    row: Mapping[str, Any],
    *,
    prefix: str,
) -> None:
    payloads_by_source = _candidate_identity_payload_values(row)
    if len(payloads_by_source) <= 1:
        return
    _error(
        errors,
        f"{prefix}.candidate_identity",
        "row candidate_identity payload must not disagree between direct and nested payloads",
        observed_payloads=[
            {
                "payload": record["payload"],
                "sources": sorted(record["sources"]),
            }
            for _payload_key, record in sorted(payloads_by_source.items())
        ],
    )


def _check_row_identity_consistency(
    errors: List[Dict[str, Any]],
    row: Mapping[str, Any],
    *,
    prefix: str,
    fields: Sequence[str],
) -> None:
    for field in fields:
        values_by_source = _row_identity_values(row, field)
        if len(values_by_source) > 1:
            _error(
                errors,
                f"{prefix}.{field}",
                "row identity field must not disagree between direct and nested payloads",
                identity_field=field,
                observed_values=sorted(values_by_source),
                sources_by_value={
                    value: sorted(sources)
                    for value, sources in sorted(values_by_source.items())
                },
            )


def _check_queue_identity_match(
    errors: List[Dict[str, Any]],
    *,
    row: Mapping[str, Any],
    queue_entry: Mapping[str, Any],
    prefix: str,
    fields: Sequence[str],
) -> None:
    """Fail closed when an alias-backed row rebinding another identity field."""

    for field in fields:
        actual_values = _row_identity_values(row, field)
        expected_values = _row_identity_values(queue_entry, field)
        if not actual_values or not expected_values:
            continue
        expected_value_list = sorted(expected_values)
        expected_payload: Any = (
            expected_value_list[0]
            if len(expected_value_list) == 1
            else expected_value_list
        )
        for actual, sources in sorted(actual_values.items()):
            if actual not in expected_values:
                _error(
                    errors,
                    f"{prefix}.{field}",
                    "alias-backed Step3 queue row must match the materialized queue entry identity",
                    expected=expected_payload,
                    actual=actual,
                    sources=sorted(sources),
                    expected_sources_by_value={
                        value: sorted(expected_sources)
                        for value, expected_sources in sorted(expected_values.items())
                    },
                    matched_queue_entry_id=queue_entry.get("queue_entry_id"),
                    matched_candidate_id=queue_entry.get("candidate_id"),
                )


def _check_planned_entry_validity_match(
    errors: List[Dict[str, Any]],
    *,
    entry: Mapping[str, Any],
    queue_entry: Mapping[str, Any],
    prefix: str,
) -> None:
    """Require scheduled/executable Campaign plan rows to preserve queue facts."""

    queue_scheduled = _string(queue_entry.get("queue_state")).startswith("scheduled_for_simulation")
    executable = entry.get("execution_allowed") is True
    if not queue_scheduled and not executable:
        return

    missing_fields = [
        field
        for field in SCHEDULED_QUEUE_VALIDITY_FIELDS
        if field not in entry
    ]
    if missing_fields:
        _error(
            errors,
            f"{prefix}.validity_fields",
            "planned scheduled/executable Step3 entries must carry explicit queue validity/admission fields",
            missing_fields=missing_fields,
        )

    for field in SCHEDULED_QUEUE_TRUE_FIELDS:
        if field in entry and entry.get(field) is not True:
            _error(
                errors,
                f"{prefix}.{field}",
                f"planned scheduled/executable Step3 entries must not set {field}=false",
                actual=entry.get(field),
            )
    if "simulation_blockers" in entry and _as_list(entry.get("simulation_blockers")):
        _error(
            errors,
            f"{prefix}.simulation_blockers",
            "planned scheduled/executable Step3 entries must not carry simulation_blockers",
            blockers=entry.get("simulation_blockers"),
        )

    claim_status = _string(entry.get("claim_status"))
    if claim_status in FORBIDDEN_SCHEDULED_QUEUE_CLAIM_STATUSES:
        _error(
            errors,
            f"{prefix}.claim_status",
            "planned scheduled/executable Step3 entries cannot claim final/release completion",
            actual=claim_status,
        )

    for field in SCHEDULED_QUEUE_VALIDITY_FIELDS:
        if field in entry and field in queue_entry and entry.get(field) != queue_entry.get(field):
            _error(
                errors,
                f"{prefix}.{field}",
                "planned Step3 validity/admission field must match the materialized queue entry",
                expected=queue_entry.get(field),
                actual=entry.get(field),
            )


def _check_candidate_identity_payload_match(
    errors: List[Dict[str, Any]],
    *,
    row: Mapping[str, Any],
    search_candidate: Mapping[str, Any],
    prefix: str,
) -> None:
    actual_payloads = _candidate_identity_payload_values(row)
    expected_payloads = _candidate_identity_payload_values(search_candidate)
    if not actual_payloads or not expected_payloads:
        return
    expected_payload_list = [
        record["payload"]
        for _payload_key, record in sorted(expected_payloads.items())
    ]
    expected_payload: Any = (
        expected_payload_list[0]
        if len(expected_payload_list) == 1
        else expected_payload_list
    )
    for payload_key, record in sorted(actual_payloads.items()):
        if payload_key not in expected_payloads:
            _error(
                errors,
                f"{prefix}.candidate_identity",
                "Campaign materialized Step3 queue write must preserve the search-admission candidate identity",
                expected=expected_payload,
                actual=record["payload"],
                sources=sorted(record["sources"]),
                expected_sources_by_payload=[
                    {
                        "payload": expected_record["payload"],
                        "sources": sorted(expected_record["sources"]),
                    }
                    for _expected_key, expected_record in sorted(expected_payloads.items())
                ],
            )


def _check_search_admission_backing(
    errors: List[Dict[str, Any]],
    *,
    row: Mapping[str, Any],
    search_admission_candidates: Sequence[Mapping[str, Any]],
    search_admission_alias_index: Mapping[str, Mapping[str, Any]],
    prefix: str,
    row_description: str,
    expected_step3_queue_ref: str,
) -> None:
    _check_admission_required_ref(
        errors,
        row,
        prefix=prefix,
        expected=expected_step3_queue_ref,
    )
    if not search_admission_candidates:
        _error(
            errors,
            prefix,
            f"{row_description} requires search_iteration_plan.next_step3_admission_candidates backing",
        )
        return
    match = _matching_queue_entry(row, search_admission_alias_index)
    if not match:
        _error(
            errors,
            prefix,
            f"{row_description} is not backed by a search_iteration_plan admission candidate",
        )
        return
    _check_queue_identity_match(
        errors,
        row=row,
        queue_entry=match,
        prefix=prefix,
        fields=SEARCH_ADMISSION_QUEUE_IDENTITY_FIELDS,
    )
    _check_candidate_identity_payload_match(
        errors,
        row=row,
        search_candidate=match,
        prefix=prefix,
    )


def _check_false_claim_flags(
    errors: List[Dict[str, Any]],
    payload: Mapping[str, Any],
    *,
    prefix: str,
) -> None:
    for flag in FALSE_CLAIM_FLAGS:
        if payload.get(flag) is True:
            _error(errors, f"{prefix}.{flag}", f"{flag} must remain false")


def _check_ref_matches(
    errors: List[Dict[str, Any]],
    payload: Mapping[str, Any],
    *,
    prefix: str,
    field: str,
    expected: str,
    required: bool = False,
) -> None:
    actual = _string(payload.get(field))
    if not actual:
        if required:
            _error(errors, f"{prefix}.{field}", "artifact reference is required", expected=expected)
        return
    if actual != expected:
        _error(
            errors,
            f"{prefix}.{field}",
            "artifact reference must match the canonical Step3 admission validation input",
            expected=expected,
            actual=actual,
        )


def _check_admission_required_ref(
    errors: List[Dict[str, Any]],
    row: Mapping[str, Any],
    *,
    prefix: str,
    expected: str,
) -> None:
    actual = _string(row.get("admission_required_before_execution"))
    if not actual:
        _error(
            errors,
            f"{prefix}.admission_required_before_execution",
            "row-level Step3 admission authority reference is required before execution",
            expected=expected,
        )
        return
    if actual != expected:
        _error(
            errors,
            f"{prefix}.admission_required_before_execution",
            "row-level Step3 admission authority reference must match the canonical Step3 queue",
            expected=expected,
            actual=actual,
        )


def _expected_campaign_scope(scope_validation: Mapping[str, Any]) -> Dict[str, str]:
    expected: Dict[str, str] = {}
    observed = _as_mapping(scope_validation.get("observed"))
    for field in CAMPAIGN_SCOPE_FIELDS:
        values_by_source = _as_mapping(observed.get(field))
        if len(values_by_source) == 1:
            expected[field] = next(iter(values_by_source))
    return expected


def _row_scope_values(row: Mapping[str, Any], field: str) -> Dict[str, List[str]]:
    return _row_nested_values(row, field, nested_maps=ROW_SCOPE_NESTED_MAPS)


def _check_row_scope_matches_campaign(
    errors: List[Dict[str, Any]],
    row: Mapping[str, Any],
    *,
    prefix: str,
    expected_scope: Mapping[str, str],
) -> None:
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
        expected = _string(expected_scope.get(field))
        if not expected:
            if values_by_source:
                _error(
                    errors,
                    f"{prefix}.{field}",
                    "Step3 admission row scope field requires an unambiguous top-level Campaign/Trial scope",
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
                    "Step3 admission row scope field must match the Campaign/Trial scope",
                    scope_field=field,
                    expected=expected,
                    actual=actual,
                    sources=sorted(sources),
                )


def _validate_campaign_scope_consistency(
    errors: List[Dict[str, Any]],
    artifacts: Sequence[Tuple[str, Mapping[str, Any]]],
) -> Dict[str, Any]:
    """Fail closed when Campaign/Trial scope IDs disagree across artifacts."""

    observed: Dict[str, Dict[str, List[str]]] = {
        field: {}
        for field in CAMPAIGN_SCOPE_FIELDS
    }
    for source, payload in artifacts:
        if not payload:
            continue
        for field in CAMPAIGN_SCOPE_FIELDS:
            value = _string(payload.get(field))
            if value:
                observed[field].setdefault(value, []).append(source)

    conflicts: List[Dict[str, Any]] = []
    for field, values_by_source in observed.items():
        if len(values_by_source) <= 1:
            continue
        conflict = {
            "field": field,
            "observed_values": sorted(values_by_source),
            "sources_by_value": {
                value: sorted(sources)
                for value, sources in sorted(values_by_source.items())
            },
        }
        conflicts.append(conflict)
        _error(
            errors,
            f"campaign_scope.{field}",
            "Campaign scope field must agree across Step3 admission artifacts",
            scope_field=field,
            observed_values=conflict["observed_values"],
            sources_by_value=conflict["sources_by_value"],
        )

    return {
        "schema_version": "dse.campaign.scope_validation.v1",
        "status": "passed" if not conflicts else "failed",
        "valid": not conflicts,
        "scope_fields": list(CAMPAIGN_SCOPE_FIELDS),
        "observed": {
            field: {
                value: sorted(sources)
                for value, sources in sorted(values_by_source.items())
            }
            for field, values_by_source in observed.items()
        },
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }


def _campaign_scope_validation_with_row_errors(
    campaign_scope_validation: Mapping[str, Any],
    errors: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Report row-local scope failures through the campaign-scope summary.

    ``_validate_campaign_scope_consistency`` validates only top-level artifact
    scope.  Row-local checks run later after queue/search/Campaign rows are
    normalized, so fold those failures back into the summary before returning
    the validation artifact.
    """

    row_scope_errors = [
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
        and not _string(error.get("field")).startswith("campaign_scope.")
    ]
    row_scope_error_count = len(row_scope_errors)
    top_level_conflict_count = int(campaign_scope_validation.get("conflict_count", 0) or 0)
    valid = bool(campaign_scope_validation.get("valid")) and row_scope_error_count == 0
    summary = dict(campaign_scope_validation)
    summary.update({
        "status": "passed" if valid else "failed",
        "valid": valid,
        "row_scope_error_count": row_scope_error_count,
        "total_scope_error_count": top_level_conflict_count + row_scope_error_count,
        "row_scope_errors": row_scope_errors,
    })
    return summary


def _normal_entries(raw_entries: Any) -> Tuple[List[Dict[str, Any]], List[int]]:
    entries: List[Dict[str, Any]] = []
    bad_indices: List[int] = []
    for index, raw_entry in enumerate(_as_list(raw_entries)):
        if isinstance(raw_entry, Mapping):
            entries.append(dict(raw_entry))
        else:
            bad_indices.append(index)
    return entries, bad_indices


def _check_bad_mapping_indices(
    errors: List[Dict[str, Any]],
    *,
    prefix: str,
    bad_indices: Sequence[int],
    row_description: str,
) -> None:
    for index in bad_indices:
        _error(errors, f"{prefix}[{index}]", f"{row_description} must be a mapping")


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


def _validate_queue_entries(
    *,
    errors: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    prefix_root: str = "step3_simulation_queue.entries",
) -> Dict[str, Any]:
    queue_entry_ids = [_string(entry.get("queue_entry_id")) for entry in entries]
    candidate_ids = [_string(entry.get("candidate_id")) for entry in entries]
    coverage = {
        "scheduled_entry_count": 0,
        "entries_missing_validity_fields": 0,
        "missing_fields_by_entry": [],
    }
    duplicate_queue_entry_ids = _duplicate_values(queue_entry_ids)
    duplicate_candidate_ids = _duplicate_values(candidate_ids)
    if duplicate_queue_entry_ids:
        _error(errors, f"{prefix_root}.queue_entry_id", "queue_entry_id values must be unique", duplicates=duplicate_queue_entry_ids)
    if duplicate_candidate_ids:
        _error(errors, f"{prefix_root}.candidate_id", "candidate_id values must be unique", duplicates=duplicate_candidate_ids)

    for index, entry in enumerate(entries):
        prefix = f"{prefix_root}[{index}]"
        _check_row_identity_consistency(
            errors,
            entry,
            prefix=prefix,
            fields=ROW_IDENTITY_FIELDS,
        )
        _check_candidate_identity_payload_consistency(errors, entry, prefix=prefix)
        _check_false_claim_flags(errors, entry, prefix=prefix)
        if entry.get("execution_allowed") is True:
            _error(errors, f"{prefix}.execution_allowed", "Step3 queue entries must not self-authorize execution")
        if entry.get("not_a_step3_queue_entry") is True or entry.get("provenance_only") is True:
            _error(errors, prefix, "Step3 queue entries must be materialized queue rows, not provenance-only proposals")
        for key in ("queue_entry_id", "candidate_id", "architecture_id", "queue_state"):
            if not _string(entry.get(key)):
                _error(errors, f"{prefix}.{key}", f"{key} is required")
        if not _string(entry.get("mapping_candidate_id")) and not _string(entry.get("complete_dse_candidate_id")):
            _error(
                errors,
                f"{prefix}.mapping_candidate_id",
                "queue entries require a mapping_candidate_id or complete_dse_candidate_id alias",
            )
        scheduled = _string(entry.get("queue_state")).startswith("scheduled_for_simulation")
        if scheduled:
            missing_validity_fields = [
                field for field in SCHEDULED_QUEUE_VALIDITY_FIELDS
                if field not in entry
            ]
            coverage["scheduled_entry_count"] += 1
            if missing_validity_fields:
                coverage["entries_missing_validity_fields"] += 1
                coverage["missing_fields_by_entry"].append({
                    "entry_index": index,
                    "queue_entry_id": entry.get("queue_entry_id"),
                    "candidate_id": entry.get("candidate_id"),
                    "missing_fields": missing_validity_fields,
                })
                _error(
                    errors,
                    f"{prefix}.validity_fields",
                    (
                        "scheduled queue entries must carry explicit Step2/Step3 "
                        "eligibility, blockers, claim_status, and admission_source fields"
                    ),
                    missing_fields=missing_validity_fields,
                )
            for field in SCHEDULED_QUEUE_TRUE_FIELDS:
                if field in entry and entry.get(field) is not True:
                    _error(
                        errors,
                        f"{prefix}.{field}",
                        f"scheduled queue entries must not set {field}=false",
                        actual=entry.get(field),
                    )
            if "simulation_blockers" in entry and _as_list(entry.get("simulation_blockers")):
                _error(
                    errors,
                    f"{prefix}.simulation_blockers",
                    "scheduled queue entries must not carry simulation_blockers",
                    blockers=entry.get("simulation_blockers"),
                )
            claim_status = _string(entry.get("claim_status"))
            if claim_status in FORBIDDEN_SCHEDULED_QUEUE_CLAIM_STATUSES:
                _error(
                    errors,
                    f"{prefix}.claim_status",
                    "scheduled queue entries cannot claim final/release completion",
                    actual=claim_status,
                )
            admission_source = _string(entry.get("admission_source"))
            if Path(admission_source).name in PROPOSAL_ONLY_ADMISSION_SOURCE_BASENAMES:
                _error(
                    errors,
                    f"{prefix}.admission_source",
                    "scheduled queue entries cannot cite proposal-only artifacts as admission authority",
                    actual=admission_source,
                )
        if scheduled and entry.get("promoted_for_simulation") is not True:
            _error(errors, f"{prefix}.promoted_for_simulation", "scheduled queue entries must be promoted_for_simulation")
        if scheduled and _as_list(entry.get("blocked_reasons")):
            _error(errors, f"{prefix}.blocked_reasons", "scheduled queue entries must not carry blocked_reasons")
        if entry.get("promoted_for_simulation") is True and not scheduled:
            _error(
                errors,
                f"{prefix}.queue_state",
                "promoted queue entries must be scheduled_for_simulation",
                queue_state=entry.get("queue_state"),
            )
    return coverage


def validate_step3_admission_queue(
    *,
    step3_simulation_queue: Mapping[str, Any],
    campaign_evaluation_plan: Optional[Mapping[str, Any]] = None,
    search_iteration_plan: Optional[Mapping[str, Any]] = None,
    campaign_search_admission_plan: Optional[Mapping[str, Any]] = None,
    refs: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Validate explicit Step3 queue materialization and admission boundaries."""

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    queue = _as_mapping(step3_simulation_queue)
    campaign_plan = _as_mapping(campaign_evaluation_plan)
    search_plan = _as_mapping(search_iteration_plan)
    admission_plan = _as_mapping(campaign_search_admission_plan)
    refs_payload = {
        "step3_simulation_queue": "step2/step3_simulation_queue.json",
        "campaign_evaluation_plan": "campaign_evaluation_plan.json",
        "search_iteration_plan": "search_iteration_plan.json",
        "search_iteration_plan_validation": "search_iteration_plan_validation.json",
        "campaign_search_admission_plan": "campaign_search_admission_plan.json",
        "top_k_candidate_queue": "step2/top_k_candidate_queue.json",
        **dict(refs or {}),
    }
    campaign_scope_validation = _validate_campaign_scope_consistency(
        errors,
        (
            ("step3_simulation_queue", queue),
            ("campaign_evaluation_plan", campaign_plan),
            ("search_iteration_plan", search_plan),
            ("campaign_search_admission_plan", admission_plan),
        ),
    )
    expected_scope = _expected_campaign_scope(campaign_scope_validation)

    _check_list_container(
        errors,
        queue,
        field_name="entries",
        field_path="step3_simulation_queue.entries",
        row_description="Step3 queue entries",
    )
    entries, bad_entry_indices = _normal_entries(queue.get("entries"))
    for index in bad_entry_indices:
        _error(errors, f"step3_simulation_queue.entries[{index}]", "queue entry must be a mapping")

    if queue.get("schema_version") != STEP3_SIMULATION_QUEUE_SCHEMA:
        _error(
            errors,
            "step3_simulation_queue.schema_version",
            "Step3 queue schema_version must match the canonical contract",
            expected=STEP3_SIMULATION_QUEUE_SCHEMA,
            actual=queue.get("schema_version"),
        )
    queue_mode = _string(queue.get("queue_mode"))
    if queue_mode not in ALLOWED_QUEUE_MODES:
        _error(
            errors,
            "step3_simulation_queue.queue_mode",
            "Step3 queue_mode is not a recognized materialized admission mode",
            allowed=sorted(ALLOWED_QUEUE_MODES),
            actual=queue.get("queue_mode"),
        )
    entry_count = _int_count_or_default(
        errors,
        field="step3_simulation_queue.entry_count",
        value=queue.get("entry_count"),
        default=len(entries),
        required=True,
    )
    if entry_count != len(entries):
        _error(
            errors,
            "step3_simulation_queue.entry_count",
            "entry_count must equal len(entries)",
            declared=queue.get("entry_count"),
            actual=len(entries),
        )
    if queue.get("queue_hash"):
        expected_hash = _stable_hash_without(queue, "queue_hash")
        if queue.get("queue_hash") != expected_hash:
            _error(
                errors,
                "step3_simulation_queue.queue_hash",
                "queue_hash must match the queue payload excluding queue_hash",
                expected=expected_hash,
                actual=queue.get("queue_hash"),
            )
    _check_false_claim_flags(errors, queue, prefix="step3_simulation_queue")
    if queue.get("hidden_evidence_fanout_allowed") is True:
        _error(errors, "step3_simulation_queue.hidden_evidence_fanout_allowed", "hidden evidence fanout must remain false")

    queue_entry_validity_field_coverage = _validate_queue_entries(
        errors=errors,
        warnings=warnings,
        entries=entries,
    )
    for index, entry in enumerate(entries):
        _check_row_scope_matches_campaign(
            errors,
            entry,
            prefix=f"step3_simulation_queue.entries[{index}]",
            expected_scope=expected_scope,
        )
    duplicate_aliases = _queue_alias_duplicates(entries)
    if duplicate_aliases:
        _error(
            errors,
            "step3_simulation_queue.entries.aliases",
            "queue entry aliases must identify at most one materialized Step3 row",
            duplicates=duplicate_aliases,
        )
    alias_index = _queue_alias_index(entries)

    planned_entries, bad_planned_entry_indices = _normal_entries(
        campaign_plan.get("planned_entries")
    )
    deferred_plan_entries, bad_deferred_plan_entry_indices = _normal_entries(
        campaign_plan.get("deferred_entries")
    )
    duplicate_planned_aliases = _row_alias_occurrence_duplicates(planned_entries)
    duplicate_deferred_plan_aliases = _row_alias_occurrence_duplicates(deferred_plan_entries)
    planned_alias_index = _queue_alias_index(planned_entries)
    if campaign_plan:
        _check_list_container(
            errors,
            campaign_plan,
            field_name="planned_entries",
            field_path="campaign_evaluation_plan.planned_entries",
            row_description="planned Step3 entries",
        )
        _check_list_container(
            errors,
            campaign_plan,
            field_name="deferred_entries",
            field_path="campaign_evaluation_plan.deferred_entries",
            row_description="Campaign deferred entries",
        )
        _check_bad_mapping_indices(
            errors,
            prefix="campaign_evaluation_plan.planned_entries",
            bad_indices=bad_planned_entry_indices,
            row_description="planned Step3 entry",
        )
        _check_bad_mapping_indices(
            errors,
            prefix="campaign_evaluation_plan.deferred_entries",
            bad_indices=bad_deferred_plan_entry_indices,
            row_description="Campaign deferred entry",
        )
        _check_ref_matches(
            errors,
            campaign_plan,
            prefix="campaign_evaluation_plan",
            field="step3_simulation_queue_ref",
            expected=refs_payload["step3_simulation_queue"],
            required=True,
        )
        _check_ref_matches(
            errors,
            campaign_plan,
            prefix="campaign_evaluation_plan",
            field="top_k_candidate_queue_ref",
            expected=refs_payload["top_k_candidate_queue"],
        )
        planned_entry_count = _int_count_or_default(
            errors,
            field="campaign_evaluation_plan.planned_entry_count",
            value=campaign_plan.get("planned_entry_count"),
            default=len(planned_entries),
            required=True,
        )
        if planned_entry_count != len(planned_entries):
            _error(
                errors,
                "campaign_evaluation_plan.planned_entry_count",
                "planned_entry_count must equal len(planned_entries)",
                declared=campaign_plan.get("planned_entry_count"),
                actual=len(planned_entries),
            )
        if duplicate_planned_aliases:
            _error(
                errors,
                "campaign_evaluation_plan.planned_entries.aliases",
                "planned Step3 entry aliases must identify at most one planned entry",
                duplicates=duplicate_planned_aliases,
            )
        if duplicate_deferred_plan_aliases:
            _error(
                errors,
                "campaign_evaluation_plan.deferred_entries.aliases",
                "Campaign deferred-entry aliases must identify at most one deferred entry",
                duplicates=duplicate_deferred_plan_aliases,
            )
        if campaign_plan.get("selected_entry_only") is not True:
            _error(errors, "campaign_evaluation_plan.selected_entry_only", "Campaign Step3 planning must remain selected-entry-only")
        if campaign_plan.get("broad_evidence_run") is True:
            _error(errors, "campaign_evaluation_plan.broad_evidence_run", "broad evidence runs require a separately materialized queue")
        admission_control = _as_mapping(campaign_plan.get("admission_control"))
        if admission_control.get("hidden_evidence_fanout_allowed") is True:
            _error(errors, "campaign_evaluation_plan.admission_control.hidden_evidence_fanout_allowed", "hidden evidence fanout must remain false")
        for index, entry in enumerate(planned_entries):
            prefix = f"campaign_evaluation_plan.planned_entries[{index}]"
            _check_row_identity_consistency(
                errors,
                entry,
                prefix=prefix,
                fields=ROW_IDENTITY_FIELDS,
            )
            _check_candidate_identity_payload_consistency(errors, entry, prefix=prefix)
            _check_row_scope_matches_campaign(
                errors,
                entry,
                prefix=prefix,
                expected_scope=expected_scope,
            )
            _check_false_claim_flags(errors, entry, prefix=prefix)
            if entry.get("admission_source") != refs_payload["step3_simulation_queue"]:
                _error(
                    errors,
                    f"{prefix}.admission_source",
                    "planned Step3 entries must cite the canonical Step3 queue",
                    expected=refs_payload["step3_simulation_queue"],
                    actual=entry.get("admission_source"),
                )
            match = _matching_queue_entry(entry, alias_index)
            if not match:
                _error(errors, prefix, "planned Step3 entry is not backed by a materialized queue entry")
            else:
                _check_queue_identity_match(
                    errors,
                    row=entry,
                    queue_entry=match,
                    prefix=prefix,
                    fields=MATERIALIZED_QUEUE_IDENTITY_FIELDS,
                )
                _check_planned_entry_validity_match(
                    errors,
                    entry=entry,
                    queue_entry=match,
                    prefix=prefix,
                )
                if (
                    entry.get("execution_allowed") is True
                    and not _string(match.get("queue_state")).startswith("scheduled_for_simulation")
                ):
                    _error(
                        errors,
                        f"{prefix}.execution_allowed",
                        "execution_allowed planned entries require a scheduled queue entry",
                    )
        for index, entry in enumerate(entries):
            if not _matching_queue_entry(entry, planned_alias_index):
                _error(
                    errors,
                    f"step3_simulation_queue.entries[{index}]",
                    "selected-entry Campaign plans must enumerate every materialized Step3 queue row",
                    queue_entry_id=entry.get("queue_entry_id"),
                    candidate_id=entry.get("candidate_id"),
                )
        for index, entry in enumerate(deferred_plan_entries):
            prefix = f"campaign_evaluation_plan.deferred_entries[{index}]"
            _check_row_identity_consistency(
                errors,
                entry,
                prefix=prefix,
                fields=ROW_IDENTITY_FIELDS,
            )
            _check_candidate_identity_payload_consistency(errors, entry, prefix=prefix)
            _check_row_scope_matches_campaign(
                errors,
                entry,
                prefix=prefix,
                expected_scope=expected_scope,
            )
            _check_false_claim_flags(errors, entry, prefix=prefix)
            if entry.get("execution_allowed") is True:
                _error(errors, f"{prefix}.execution_allowed", "deferred entries cannot execute")
            if entry.get("provenance_only") is False:
                _error(errors, f"{prefix}.provenance_only", "deferred entries must remain provenance-only")
            if _string(entry.get("queue_state")).startswith("scheduled_for_simulation"):
                _error(errors, f"{prefix}.queue_state", "deferred entries must not be scheduled_for_simulation queue rows")
            if _matching_queue_entry(entry, alias_index):
                _error(errors, prefix, "deferred entries that are already materialized must move to planned_entries")

    (
        search_admission_candidates,
        bad_search_admission_candidate_indices,
    ) = _normal_entries(search_plan.get("next_step3_admission_candidates"))
    duplicate_search_admission_aliases = _queue_alias_duplicates(search_admission_candidates)
    search_admission_alias_index = _queue_alias_index(search_admission_candidates)
    materialized_search_candidates: List[str] = []
    pending_search_candidates: List[str] = []
    if search_plan:
        _check_list_container(
            errors,
            search_plan,
            field_name="next_step3_admission_candidates",
            field_path="search_iteration_plan.next_step3_admission_candidates",
            row_description="search admission candidates",
        )
        _check_bad_mapping_indices(
            errors,
            prefix="search_iteration_plan.next_step3_admission_candidates",
            bad_indices=bad_search_admission_candidate_indices,
            row_description="search admission candidate",
        )
        _check_ref_matches(
            errors,
            search_plan,
            prefix="search_iteration_plan",
            field="next_step3_admission_queue_ref",
            expected=refs_payload["step3_simulation_queue"],
            required=True,
        )
        _check_ref_matches(
            errors,
            search_plan,
            prefix="search_iteration_plan",
            field="step3_admission_queue",
            expected=refs_payload["step3_simulation_queue"],
            required=True,
        )
        if duplicate_search_admission_aliases:
            _error(
                errors,
                "search_iteration_plan.next_step3_admission_candidates.aliases",
                "search admission candidate aliases must identify at most one Step3-admission candidate",
                duplicates=duplicate_search_admission_aliases,
            )
        for index, candidate in enumerate(search_admission_candidates):
            prefix = f"search_iteration_plan.next_step3_admission_candidates[{index}]"
            _check_row_identity_consistency(
                errors,
                candidate,
                prefix=prefix,
                fields=ROW_IDENTITY_FIELDS,
            )
            _check_candidate_identity_payload_consistency(errors, candidate, prefix=prefix)
            _check_row_scope_matches_campaign(
                errors,
                candidate,
                prefix=prefix,
                expected_scope=expected_scope,
            )
            _check_admission_required_ref(
                errors,
                candidate,
                prefix=prefix,
                expected=refs_payload["step3_simulation_queue"],
            )
            _check_false_claim_flags(errors, candidate, prefix=prefix)
            if candidate.get("execution_allowed") is True:
                _error(errors, f"{prefix}.execution_allowed", "search admission proposals cannot execute directly")
            candidate_id = _string(candidate.get("candidate_id"))
            match = _identity_preserving_queue_match(
                candidate,
                entries,
                fields=SEARCH_ADMISSION_QUEUE_IDENTITY_FIELDS,
            )
            broad_match = _matching_queue_entry(candidate, alias_index)
            if match:
                _check_queue_identity_match(
                    errors,
                    row=candidate,
                    queue_entry=match,
                    prefix=prefix,
                    fields=SEARCH_ADMISSION_QUEUE_IDENTITY_FIELDS,
                )
                materialized_search_candidates.append(candidate_id)
            elif broad_match and _has_identity_overlap(
                candidate,
                broad_match,
                _DEFINITIVE_QUEUE_MATCH_FIELDS,
            ):
                _check_queue_identity_match(
                    errors,
                    row=candidate,
                    queue_entry=broad_match,
                    prefix=prefix,
                    fields=SEARCH_ADMISSION_QUEUE_IDENTITY_FIELDS,
                )
                pending_search_candidates.append(candidate_id)
            else:
                pending_search_candidates.append(candidate_id)
        next_admission_candidate_count = _int_count_or_default(
            errors,
            field="search_iteration_plan.next_step3_admission_candidate_count",
            value=search_plan.get("next_step3_admission_candidate_count"),
            default=len(search_admission_candidates),
            required=True,
        )
        if next_admission_candidate_count != len(search_admission_candidates):
            _error(
                errors,
                "search_iteration_plan.next_step3_admission_candidate_count",
                "search admission candidate count must equal len(next_step3_admission_candidates)",
                declared=search_plan.get("next_step3_admission_candidate_count"),
                actual=len(search_admission_candidates),
            )

    (
        materialized_write_entries,
        bad_materialized_write_entry_indices,
    ) = _normal_entries(admission_plan.get("materialized_step3_queue_entries"))
    (
        step2_iteration_requests,
        bad_step2_iteration_request_indices,
    ) = _normal_entries(admission_plan.get("step2_iteration_requests"))
    deferred_candidates, bad_deferred_candidate_indices = _normal_entries(
        admission_plan.get("deferred_candidates")
    )
    if admission_plan:
        _check_list_container(
            errors,
            admission_plan,
            field_name="materialized_step3_queue_entries",
            field_path="campaign_search_admission_plan.materialized_step3_queue_entries",
            row_description="materialized Step3 queue writes",
        )
        _check_list_container(
            errors,
            admission_plan,
            field_name="step2_iteration_requests",
            field_path="campaign_search_admission_plan.step2_iteration_requests",
            row_description="Step2 materialization requests",
        )
        _check_list_container(
            errors,
            admission_plan,
            field_name="deferred_candidates",
            field_path="campaign_search_admission_plan.deferred_candidates",
            row_description="Campaign deferred candidates",
        )
        _check_bad_mapping_indices(
            errors,
            prefix="campaign_search_admission_plan.materialized_step3_queue_entries",
            bad_indices=bad_materialized_write_entry_indices,
            row_description="materialized Step3 queue write",
        )
        _check_bad_mapping_indices(
            errors,
            prefix="campaign_search_admission_plan.step2_iteration_requests",
            bad_indices=bad_step2_iteration_request_indices,
            row_description="Step2 materialization request",
        )
        _check_bad_mapping_indices(
            errors,
            prefix="campaign_search_admission_plan.deferred_candidates",
            bad_indices=bad_deferred_candidate_indices,
            row_description="Campaign deferred candidate",
        )
        _check_ref_matches(
            errors,
            admission_plan,
            prefix="campaign_search_admission_plan",
            field="campaign_evaluation_plan_ref",
            expected=refs_payload["campaign_evaluation_plan"],
            required=True,
        )
        _check_ref_matches(
            errors,
            admission_plan,
            prefix="campaign_search_admission_plan",
            field="search_iteration_plan_ref",
            expected=refs_payload["search_iteration_plan"],
            required=True,
        )
        _check_ref_matches(
            errors,
            admission_plan,
            prefix="campaign_search_admission_plan",
            field="search_iteration_plan_validation_ref",
            expected=refs_payload["search_iteration_plan_validation"],
            required=True,
        )
        _check_ref_matches(
            errors,
            admission_plan,
            prefix="campaign_search_admission_plan",
            field="step3_simulation_queue_ref",
            expected=refs_payload["step3_simulation_queue"],
            required=True,
        )
        _check_false_claim_flags(errors, admission_plan, prefix="campaign_search_admission_plan")
        for flag in ("execution_allowed", "hidden_evidence_fanout_allowed", "broad_evidence_run"):
            if admission_plan.get(flag) is True:
                _error(errors, f"campaign_search_admission_plan.{flag}", f"{flag} must remain false")
        admission_status = _string(admission_plan.get("admission_status"))
        if admission_status not in ALLOWED_ADMISSION_STATUSES:
            _error(
                errors,
                "campaign_search_admission_plan.admission_status",
                "campaign search admission plans must declare a recognized admission_status",
                allowed=sorted(ALLOWED_ADMISSION_STATUSES),
                actual=admission_plan.get("admission_status"),
            )
        admitted_entry_count = _int_count_or_default(
            errors,
            field="campaign_search_admission_plan.admitted_entry_count",
            value=admission_plan.get("admitted_entry_count"),
            default=0,
            required=True,
        )
        if admitted_entry_count != 0:
            _error(errors, "campaign_search_admission_plan.admitted_entry_count", "admission plans cannot mark entries admitted before Step3 queue write")
        materialized_write_entry_count = _int_count_or_default(
            errors,
            field="campaign_search_admission_plan.materialized_step3_queue_entry_count",
            value=admission_plan.get("materialized_step3_queue_entry_count"),
            default=len(materialized_write_entries),
            required=True,
        )
        if materialized_write_entry_count != len(materialized_write_entries):
            _error(
                errors,
                "campaign_search_admission_plan.materialized_step3_queue_entry_count",
                "materialized_step3_queue_entry_count must equal len(materialized_step3_queue_entries)",
                declared=admission_plan.get("materialized_step3_queue_entry_count"),
                actual=len(materialized_write_entries),
            )
        step2_iteration_request_count = _int_count_or_default(
            errors,
            field="campaign_search_admission_plan.step2_iteration_request_count",
            value=admission_plan.get("step2_iteration_request_count"),
            default=len(step2_iteration_requests),
            required=True,
        )
        if step2_iteration_request_count != len(step2_iteration_requests):
            _error(
                errors,
                "campaign_search_admission_plan.step2_iteration_request_count",
                "step2_iteration_request_count must equal len(step2_iteration_requests)",
                declared=admission_plan.get("step2_iteration_request_count"),
                actual=len(step2_iteration_requests),
            )
        deferred_candidate_count = _int_count_or_default(
            errors,
            field="campaign_search_admission_plan.deferred_candidate_count",
            value=admission_plan.get("deferred_candidate_count"),
            default=len(deferred_candidates),
            required=True,
        )
        if deferred_candidate_count != len(deferred_candidates):
            _error(
                errors,
                "campaign_search_admission_plan.deferred_candidate_count",
                "deferred_candidate_count must equal len(deferred_candidates)",
                declared=admission_plan.get("deferred_candidate_count"),
                actual=len(deferred_candidates),
            )
        duplicate_request_aliases = _queue_alias_duplicates(step2_iteration_requests)
        if duplicate_request_aliases:
            _error(
                errors,
                "campaign_search_admission_plan.step2_iteration_requests.aliases",
                "Step2 materialization request aliases must identify at most one pending request",
                duplicates=duplicate_request_aliases,
            )
        duplicate_deferred_aliases = _queue_alias_duplicates(deferred_candidates)
        if duplicate_deferred_aliases:
            _error(
                errors,
                "campaign_search_admission_plan.deferred_candidates.aliases",
                "deferred candidate aliases must identify at most one deferred candidate",
                duplicates=duplicate_deferred_aliases,
            )
        if admission_status == "step3_queue_write_required" and not materialized_write_entries:
            _error(errors, "campaign_search_admission_plan.admission_status", "step3_queue_write_required needs materialized_step3_queue_entries")
        if admission_status == "step2_materialization_required" and not step2_iteration_requests:
            _error(errors, "campaign_search_admission_plan.admission_status", "step2_materialization_required needs step2_iteration_requests")
        if step2_iteration_requests and admission_status != "step2_materialization_required":
            _error(
                errors,
                "campaign_search_admission_plan.admission_status",
                "plans with Step2 materialization requests must use step2_materialization_required",
                actual=admission_plan.get("admission_status"),
            )
        if materialized_write_entries and admission_status != "step3_queue_write_required":
            _error(
                errors,
                "campaign_search_admission_plan.admission_status",
                "plans with materialized Step3 queue writes must use step3_queue_write_required",
                actual=admission_plan.get("admission_status"),
            )
        _validate_queue_entries(
            errors=errors,
            warnings=warnings,
            entries=materialized_write_entries,
            prefix_root="campaign_search_admission_plan.materialized_step3_queue_entries",
        )
        duplicate_write_aliases = _queue_alias_duplicates(materialized_write_entries)
        if duplicate_write_aliases:
            _error(
                errors,
                "campaign_search_admission_plan.materialized_step3_queue_entries.aliases",
                "materialized write-entry aliases must identify at most one pending Step3 queue row",
                duplicates=duplicate_write_aliases,
            )
        for index, entry in enumerate(materialized_write_entries):
            prefix = f"campaign_search_admission_plan.materialized_step3_queue_entries[{index}]"
            _check_row_scope_matches_campaign(
                errors,
                entry,
                prefix=prefix,
                expected_scope=expected_scope,
            )
            existing_queue_match = _matching_queue_entry(entry, alias_index)
            if existing_queue_match:
                _error(
                    errors,
                    prefix,
                    "Campaign materialized Step3 queue writes must not duplicate aliases already owned by the existing Step3 queue",
                    matched_queue_entry_id=existing_queue_match.get("queue_entry_id"),
                    matched_candidate_id=existing_queue_match.get("candidate_id"),
                    shared_aliases=sorted(set(_row_aliases(entry)) & set(_row_aliases(existing_queue_match))),
                )
            missing_validity_fields = [
                field for field in SCHEDULED_QUEUE_VALIDITY_FIELDS
                if field not in entry
            ]
            if missing_validity_fields:
                _error(
                    errors,
                    f"{prefix}.validity_fields",
                    "Campaign materialized Step3 queue writes must carry explicit scheduled-row validity fields",
                    missing_fields=missing_validity_fields,
                )
            if entry.get("admission_source") != refs_payload["campaign_search_admission_plan"]:
                _error(
                    errors,
                    f"{prefix}.admission_source",
                    "Campaign materialized Step3 queue writes must cite the Campaign admission plan",
                    expected=refs_payload["campaign_search_admission_plan"],
                    actual=entry.get("admission_source"),
                )
            if not _string(entry.get("queue_state")).startswith("scheduled_for_simulation"):
                _error(
                    errors,
                    f"{prefix}.queue_state",
                    "Campaign materialized Step3 queue writes must be scheduled_for_simulation",
                    actual=entry.get("queue_state"),
                )
            if entry.get("promoted_for_simulation") is not True:
                _error(
                    errors,
                    f"{prefix}.promoted_for_simulation",
                    "Campaign materialized Step3 queue writes must be promoted_for_simulation",
                    actual=entry.get("promoted_for_simulation"),
                )
            _check_search_admission_backing(
                errors,
                row=entry,
                search_admission_candidates=search_admission_candidates,
                search_admission_alias_index=search_admission_alias_index,
                prefix=prefix,
                row_description="Campaign materialized Step3 queue write",
                expected_step3_queue_ref=refs_payload["step3_simulation_queue"],
            )
        for index, request in enumerate(step2_iteration_requests):
            prefix = f"campaign_search_admission_plan.step2_iteration_requests[{index}]"
            _check_row_identity_consistency(
                errors,
                request,
                prefix=prefix,
                fields=ROW_IDENTITY_FIELDS,
            )
            _check_candidate_identity_payload_consistency(errors, request, prefix=prefix)
            _check_row_scope_matches_campaign(
                errors,
                request,
                prefix=prefix,
                expected_scope=expected_scope,
            )
            if request.get("requested_action") != "materialize_step2_artifacts_for_step3_queue":
                _error(
                    errors,
                    f"{prefix}.requested_action",
                    "Step2 materialization requests must use the canonical materialize action",
                    expected="materialize_step2_artifacts_for_step3_queue",
                    actual=request.get("requested_action"),
                )
            if request.get("materialization_status") != "requested_pending_step2_writer":
                _error(
                    errors,
                    f"{prefix}.materialization_status",
                    "Step2 materialization requests must remain pending the Step2 writer",
                    expected="requested_pending_step2_writer",
                    actual=request.get("materialization_status"),
                )
            if request.get("not_a_step3_queue_entry") is not True:
                _error(
                    errors,
                    f"{prefix}.not_a_step3_queue_entry",
                    "Step2 materialization requests must not masquerade as Step3 queue entries",
                    expected=True,
                    actual=request.get("not_a_step3_queue_entry"),
                )
            if _string(request.get("queue_state")).startswith("scheduled_for_simulation"):
                _error(
                    errors,
                    f"{prefix}.queue_state",
                    "Step2 materialization requests must not be scheduled_for_simulation queue rows",
                    actual=request.get("queue_state"),
                )
            if request.get("execution_allowed") is True:
                _error(errors, f"{prefix}.execution_allowed", "Step2 materialization requests cannot execute")
            _check_false_claim_flags(errors, request, prefix=prefix)
            _check_search_admission_backing(
                errors,
                row=request,
                search_admission_candidates=search_admission_candidates,
                search_admission_alias_index=search_admission_alias_index,
                prefix=prefix,
                row_description="Campaign Step2 materialization request",
                expected_step3_queue_ref=refs_payload["step3_simulation_queue"],
            )
        for index, candidate in enumerate(deferred_candidates):
            prefix = f"campaign_search_admission_plan.deferred_candidates[{index}]"
            _check_row_identity_consistency(
                errors,
                candidate,
                prefix=prefix,
                fields=ROW_IDENTITY_FIELDS,
            )
            _check_candidate_identity_payload_consistency(errors, candidate, prefix=prefix)
            _check_row_scope_matches_campaign(
                errors,
                candidate,
                prefix=prefix,
                expected_scope=expected_scope,
            )
            _check_false_claim_flags(errors, candidate, prefix=prefix)
            if candidate.get("execution_allowed") is True:
                _error(errors, f"{prefix}.execution_allowed", "deferred candidates cannot execute")
            if candidate.get("not_a_step3_queue_entry") is not True:
                _error(
                    errors,
                    f"{prefix}.not_a_step3_queue_entry",
                    "deferred candidates must remain proposal-only and not Step3 queue rows",
                    expected=True,
                    actual=candidate.get("not_a_step3_queue_entry"),
                )
            if _string(candidate.get("queue_state")).startswith("scheduled_for_simulation"):
                _error(
                    errors,
                    f"{prefix}.queue_state",
                    "deferred candidates must not be scheduled_for_simulation queue rows",
                    actual=candidate.get("queue_state"),
                )
            _check_search_admission_backing(
                errors,
                row=candidate,
                search_admission_candidates=search_admission_candidates,
                search_admission_alias_index=search_admission_alias_index,
                prefix=prefix,
                row_description="Campaign deferred candidate",
                expected_step3_queue_ref=refs_payload["step3_simulation_queue"],
            )

    campaign_scope_validation = _campaign_scope_validation_with_row_errors(
        campaign_scope_validation,
        errors,
    )
    valid = not errors
    return {
        "schema_version": STEP3_ADMISSION_QUEUE_VALIDATION_SCHEMA,
        "status": "passed" if valid else "failed",
        "valid": valid,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "refs": refs_payload,
        "campaign_scope_validation": campaign_scope_validation,
        "summary": {
            "queue_mode": queue_mode or None,
            "queue_entry_count": len(entries),
            "planned_entry_count": len(planned_entries),
            "planned_entries_backed_by_queue": len(planned_entries) - len([
                entry for entry in planned_entries if not _matching_queue_entry(entry, alias_index)
            ]),
            "search_admission_candidate_count": len(search_admission_candidates),
            "materialized_search_admission_candidate_count": len(materialized_search_candidates),
            "pending_search_admission_candidate_count": len(pending_search_candidates),
            "queue_write_required_count": len(materialized_write_entries),
            "queue_entry_validity_field_coverage": queue_entry_validity_field_coverage,
        },
        "pending_search_admission_candidate_ids": pending_search_candidates,
        "materialized_search_admission_candidate_ids": materialized_search_candidates,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Step3 admission queue validation proves only materialization and "
            "Campaign handoff consistency. It does not execute Step3, adjudicate "
            "numerical/PPA evidence, or select a final FPGA/ASIC winner."
        ),
    }


def load_json_mapping(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_step3_admission_queue_validation(
    *,
    step3_queue_path: Path,
    out_dir: Path,
    campaign_evaluation_plan_path: Optional[Path] = None,
    search_iteration_plan_path: Optional[Path] = None,
    campaign_search_admission_plan_path: Optional[Path] = None,
    artifact_name: str = "step3_admission_queue_validation.json",
) -> Dict[str, Any]:
    validation = validate_step3_admission_queue(
        step3_simulation_queue=load_json_mapping(step3_queue_path),
        campaign_evaluation_plan=(
            load_json_mapping(campaign_evaluation_plan_path)
            if campaign_evaluation_plan_path and campaign_evaluation_plan_path.exists()
            else None
        ),
        search_iteration_plan=(
            load_json_mapping(search_iteration_plan_path)
            if search_iteration_plan_path and search_iteration_plan_path.exists()
            else None
        ),
        campaign_search_admission_plan=(
            load_json_mapping(campaign_search_admission_plan_path)
            if campaign_search_admission_plan_path and campaign_search_admission_plan_path.exists()
            else None
        ),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / artifact_name).write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "schema_version": "dse.step3.admission_queue_validation_status.v1",
        "status": validation["status"],
        "valid": validation["valid"],
        "step3_queue": str(step3_queue_path),
        "validation": artifact_name,
        "error_count": validation["error_count"],
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
    }
    (out_dir / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status


__all__ = [
    "STEP3_ADMISSION_QUEUE_VALIDATION_SCHEMA",
    "STEP3_SIMULATION_QUEUE_SCHEMA",
    "validate_step3_admission_queue",
    "write_step3_admission_queue_validation",
]
