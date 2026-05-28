#!/usr/bin/env python3
"""DFT-profile candidate-set reconciliation across release evidence surfaces.

This module intentionally stays in ``reference_workloads``.  It compares the
release candidate IDs surfaced by the DFT hardware release gate, the DFT
candidate binding map, and the DFT trial ledger so Step5 can report stale or
inconsistent candidate universes without relying only on a goal-audit sidecar.

The artifact is reporting/provenance evidence only.  It never promotes Step3
execution, hardware PPA, numerical correctness, trusted final claims, or
deliverable completion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.codesign.release_domain import stable_json_hash

DFT_CANDIDATE_SET_CONSISTENCY_SCHEMA = "dse.dft.candidate_set_consistency.v1"
DFT_CANDIDATE_SET_CONSISTENCY_VALIDATION_SCHEMA = "dse.dft.candidate_set_consistency_validation.v1"

_SOURCE_DEFINITIONS = {
    "release_gate": {
        "artifact": "dft_hardware_closure_release_gate.json",
        "row_path": "candidate_rows[].candidate_id",
    },
    "binding_map": {
        "artifact": "dft_candidate_binding_map.json",
        "row_path": "binding_rows[].release_candidate_id",
    },
    "trial_ledger": {
        "artifact": "dft_trial_state_ledger.json",
        "row_path": "trial_rows[].candidate_binding.release_candidate_id",
    },
}

_CLAIM_BOUNDARY = (
    "dft_candidate_set_consistency.json reconciles release candidate IDs across "
    "the DFT hardware release gate, candidate binding map, and trial ledger for "
    "Step5 reporting. It is fail-closed provenance only: it does not authorize "
    "Step3 execution, upgrade numerical or hardware evidence, select a trusted "
    "winner, or mark deliverable completion."
)


def _load_json(path: Path | None) -> Dict[str, Any]:
    if path is None or not Path(path).exists():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path | None) -> Dict[str, Any]:
    if path is None:
        return {
            "path": None,
            "exists": False,
            "sha256": None,
            "hash_algorithm": "sha256",
            "status": "not_attached",
        }
    candidate = Path(path)
    exists = candidate.exists() and candidate.is_file()
    return {
        "path": str(candidate),
        "exists": exists,
        "sha256": sha256_file(candidate) if exists else None,
        "hash_algorithm": "sha256",
        "status": "present_hash_valid" if exists else "missing_required",
    }


def _candidate_ids_from_release_gate(payload: Mapping[str, Any]) -> list[str]:
    return sorted({
        str(row.get("candidate_id"))
        for row in payload.get("candidate_rows", []) or []
        if isinstance(row, Mapping) and row.get("candidate_id")
    })


def _candidate_ids_from_binding_map(payload: Mapping[str, Any]) -> list[str]:
    return sorted({
        str(row.get("release_candidate_id"))
        for row in payload.get("binding_rows", []) or []
        if isinstance(row, Mapping) and row.get("release_candidate_id")
    })


def _candidate_ids_from_trial_ledger(payload: Mapping[str, Any]) -> list[str]:
    candidate_ids: set[str] = set()
    for row in payload.get("trial_rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        binding = row.get("candidate_binding", {})
        if isinstance(binding, Mapping) and binding.get("release_candidate_id"):
            candidate_ids.add(str(binding["release_candidate_id"]))
    return sorted(candidate_ids)


def _duplicate_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _candidate_id_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if value is not None and str(value)]


def _candidate_ids_from_consistency_row(row: Mapping[str, Any]) -> list[str]:
    raw_ids = row.get("raw_candidate_ids")
    if isinstance(raw_ids, list):
        return _candidate_id_list(raw_ids)
    return _candidate_id_list(row.get("candidate_ids"))


def _candidate_set_blockers(
    *,
    missing_sources: list[str],
    empty_sources: list[str],
    duplicate_sources: list[str],
    pairwise_mismatches: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    blockers: list[Dict[str, Any]] = []
    if missing_sources:
        blockers.append({
            "blocker_id": "missing_candidate_set_sources",
            "sources": missing_sources,
            "reason": "All three DFT candidate-set sources must be present before the set can pass.",
        })
    if empty_sources:
        blockers.append({
            "blocker_id": "empty_candidate_sets",
            "sources": empty_sources,
            "reason": "All present candidate-set sources must contain at least one release candidate ID.",
        })
    if duplicate_sources:
        blockers.append({
            "blocker_id": "duplicate_candidate_ids",
            "sources": duplicate_sources,
            "reason": "Candidate-set rows must not contain duplicate release candidate IDs.",
        })
    if pairwise_mismatches:
        blockers.append({
            "blocker_id": "candidate_set_mismatch",
            "pairwise_mismatch_count": len(pairwise_mismatches),
            "reason": "Release-gate, binding-map, and trial-ledger release candidate ID sets do not match.",
        })
    return blockers


def _candidate_set_status(
    *,
    missing_sources: list[str],
    empty_sources: list[str],
    duplicate_sources: list[str],
    candidate_sets_match: bool,
) -> tuple[str, str]:
    if candidate_sets_match:
        return "passed", "candidate_sets_match"
    if missing_sources:
        return (
            "blocked_missing_candidate_set_sources",
            "candidate_sets_not_checked_missing_sources",
        )
    if empty_sources:
        return "blocked_empty_candidate_sets", "candidate_sets_empty"
    if duplicate_sources:
        return "blocked_duplicate_candidate_ids", "candidate_set_mismatch"
    return "blocked_candidate_set_mismatch", "candidate_set_mismatch"


def _recompute_candidate_set_summary(
    candidate_sets: Mapping[str, Any],
) -> Dict[str, Any]:
    """Recompute every derived candidate-set field from ``candidate_sets`` only."""

    normalized_rows: Dict[str, Dict[str, Any]] = {}
    set_by_source: Dict[str, set[str]] = {}
    raw_by_source: Dict[str, list[str]] = {}
    for source in _SOURCE_DEFINITIONS:
        row = candidate_sets.get(source, {})
        row = row if isinstance(row, Mapping) else {}
        raw_ids = _candidate_ids_from_consistency_row(row)
        candidate_ids = sorted(set(raw_ids))
        duplicate_ids = _duplicate_ids(raw_ids)
        raw_by_source[source] = raw_ids
        set_by_source[source] = set(candidate_ids)
        normalized_rows[source] = {
            "present": row.get("present") is True,
            "candidate_ids": candidate_ids,
            "candidate_count": len(candidate_ids),
            "duplicate_candidate_ids": duplicate_ids,
        }

    missing_sources = sorted(
        source
        for source, row in normalized_rows.items()
        if not row["present"]
    )
    empty_sources = sorted(
        source
        for source, row in normalized_rows.items()
        if row["present"] and not row["candidate_ids"]
    )
    duplicate_sources = sorted(
        source
        for source, row in normalized_rows.items()
        if row["duplicate_candidate_ids"]
    )
    union_ids = sorted(set().union(*set_by_source.values())) if set_by_source else []
    intersection_ids = (
        sorted(set.intersection(*set_by_source.values()))
        if set_by_source and all(set_by_source.values())
        else []
    )
    source_only = {
        source: sorted(
            values
            - set().union(
                *(other for name, other in set_by_source.items() if name != source)
            )
        )
        for source, values in set_by_source.items()
    }
    source_missing = {
        source: sorted(set(union_ids) - values)
        for source, values in set_by_source.items()
    }
    pairwise_mismatches: list[Dict[str, Any]] = []
    sources = list(_SOURCE_DEFINITIONS)
    for index, left in enumerate(sources):
        for right in sources[index + 1:]:
            left_ids = set_by_source[left]
            right_ids = set_by_source[right]
            if left_ids != right_ids:
                pairwise_mismatches.append({
                    "left_source": left,
                    "right_source": right,
                    "left_only_candidate_ids": sorted(left_ids - right_ids),
                    "right_only_candidate_ids": sorted(right_ids - left_ids),
                })

    all_required_sources_present = not missing_sources
    all_sources_nonempty = all_required_sources_present and not empty_sources
    candidate_sets_match = (
        all_sources_nonempty
        and not duplicate_sources
        and all(
            set_by_source[source] == set(union_ids)
            for source in _SOURCE_DEFINITIONS
        )
    )
    status, consistency_status = _candidate_set_status(
        missing_sources=missing_sources,
        empty_sources=empty_sources,
        duplicate_sources=duplicate_sources,
        candidate_sets_match=candidate_sets_match,
    )
    blockers = _candidate_set_blockers(
        missing_sources=missing_sources,
        empty_sources=empty_sources,
        duplicate_sources=duplicate_sources,
        pairwise_mismatches=pairwise_mismatches,
    )
    return {
        "status": status,
        "candidate_set_consistency_status": consistency_status,
        "required_source_count": len(_SOURCE_DEFINITIONS),
        "present_source_count": len(_SOURCE_DEFINITIONS) - len(missing_sources),
        "missing_sources": missing_sources,
        "empty_sources": empty_sources,
        "duplicate_sources": duplicate_sources,
        "all_required_sources_present": all_required_sources_present,
        "all_sources_nonempty": all_sources_nonempty,
        "all_required_sources_match_and_nonempty": candidate_sets_match,
        "union_candidate_count": len(union_ids),
        "union_candidate_ids": union_ids,
        "common_candidate_count": len(intersection_ids),
        "common_candidate_ids": intersection_ids,
        "source_only_candidate_ids": source_only,
        "source_missing_candidate_ids": source_missing,
        "release_gate_only_candidate_ids": source_only["release_gate"],
        "binding_map_only_candidate_ids": source_only["binding_map"],
        "trial_ledger_only_candidate_ids": source_only["trial_ledger"],
        "release_gate_missing_candidate_ids": source_missing["release_gate"],
        "binding_map_missing_candidate_ids": source_missing["binding_map"],
        "trial_ledger_missing_candidate_ids": source_missing["trial_ledger"],
        "pairwise_mismatch_count": len(pairwise_mismatches),
        "pairwise_mismatches": pairwise_mismatches,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "normalized_candidate_sets": normalized_rows,
        "raw_candidate_ids_by_source": raw_by_source,
    }


def _raw_candidate_ids(source: str, payload: Mapping[str, Any]) -> list[str]:
    if source == "release_gate":
        return [
            str(row.get("candidate_id"))
            for row in payload.get("candidate_rows", []) or []
            if isinstance(row, Mapping) and row.get("candidate_id")
        ]
    if source == "binding_map":
        return [
            str(row.get("release_candidate_id"))
            for row in payload.get("binding_rows", []) or []
            if isinstance(row, Mapping) and row.get("release_candidate_id")
        ]
    if source == "trial_ledger":
        values: list[str] = []
        for row in payload.get("trial_rows", []) or []:
            if not isinstance(row, Mapping):
                continue
            binding = row.get("candidate_binding", {})
            if isinstance(binding, Mapping) and binding.get("release_candidate_id"):
                values.append(str(binding["release_candidate_id"]))
        return values
    return []


def _source_payload(
    *,
    source: str,
    path: Path | None,
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    raw_ids = _raw_candidate_ids(source, payload)
    candidate_ids = sorted(set(raw_ids))
    definition = _SOURCE_DEFINITIONS[source]
    return {
        "artifact": definition["artifact"],
        "path": str(path) if path is not None else None,
        "present": bool(payload),
        "row_path": definition["row_path"],
        "candidate_count": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "raw_candidate_ids": raw_ids,
        "duplicate_candidate_ids": _duplicate_ids(raw_ids),
        "candidate_set_hash": stable_json_hash(candidate_ids) if candidate_ids else None,
    }


def build_dft_candidate_set_consistency(
    *,
    release_gate_path: Path | None = None,
    candidate_binding_map_path: Path | None = None,
    trial_state_ledger_path: Path | None = None,
) -> Dict[str, Any]:
    """Return a fail-closed reconciliation report for DFT release candidate IDs."""

    paths = {
        "release_gate": release_gate_path,
        "binding_map": candidate_binding_map_path,
        "trial_ledger": trial_state_ledger_path,
    }
    payloads = {
        "release_gate": _load_json(release_gate_path),
        "binding_map": _load_json(candidate_binding_map_path),
        "trial_ledger": _load_json(trial_state_ledger_path),
    }
    candidate_sets = {
        source: _source_payload(source=source, path=paths[source], payload=payloads[source])
        for source in _SOURCE_DEFINITIONS
    }
    recomputed = _recompute_candidate_set_summary(candidate_sets)
    union_ids = recomputed["union_candidate_ids"]

    payload: Dict[str, Any] = {
        "schema_version": DFT_CANDIDATE_SET_CONSISTENCY_SCHEMA,
        "status": recomputed["status"],
        "candidate_set_consistency_status": recomputed["candidate_set_consistency_status"],
        "required_sources": list(_SOURCE_DEFINITIONS),
        "source_artifacts": {
            "release_gate": _source_ref(release_gate_path),
            "binding_map": _source_ref(candidate_binding_map_path),
            "trial_ledger": _source_ref(trial_state_ledger_path),
        },
        "candidate_sets": candidate_sets,
        **{
            key: value
            for key, value in recomputed.items()
            if key
            not in {
                "status",
                "candidate_set_consistency_status",
                "normalized_candidate_sets",
                "raw_candidate_ids_by_source",
            }
        },
        "candidate_set_hash": (
            stable_json_hash({"candidate_ids": union_ids, "sources": candidate_sets})
            if union_ids
            else None
        ),
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    return payload


def validate_dft_candidate_set_consistency(
    consistency: Mapping[str, Any] | Path,
) -> Dict[str, Any]:
    """Validate artifact structure and recompute all derived fields fail-closed."""

    payload = _load_json(consistency) if isinstance(consistency, Path) else dict(consistency)
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_CANDIDATE_SET_CONSISTENCY_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected candidate-set consistency schema"})
    candidate_sets = payload.get("candidate_sets", {})
    if not isinstance(candidate_sets, Mapping):
        errors.append({"field": "candidate_sets", "message": "candidate_sets must be an object"})
        candidate_sets = {}
    for source in _SOURCE_DEFINITIONS:
        row = candidate_sets.get(source, {})
        if not isinstance(row, Mapping):
            errors.append({"field": f"candidate_sets.{source}", "message": "source row must be an object"})
            continue
        ids = row.get("candidate_ids", [])
        if not isinstance(ids, list):
            errors.append({"field": f"candidate_sets.{source}.candidate_ids", "message": "candidate_ids must be a list"})
            ids = []
        if row.get("candidate_count") != len(ids):
            errors.append({"field": f"candidate_sets.{source}.candidate_count", "message": "candidate_count must equal candidate_ids length"})
        raw_ids = _candidate_ids_from_consistency_row(row)
        recomputed_ids = sorted(set(raw_ids))
        if row.get("candidate_ids", []) != recomputed_ids:
            errors.append({
                "field": f"candidate_sets.{source}.candidate_ids",
                "message": "candidate_ids must equal the sorted unique IDs recomputed from candidate_sets",
                "expected": recomputed_ids,
                "actual": row.get("candidate_ids", []),
            })
        recomputed_duplicates = _duplicate_ids(raw_ids)
        if row.get("duplicate_candidate_ids", []) != recomputed_duplicates:
            errors.append({
                "field": f"candidate_sets.{source}.duplicate_candidate_ids",
                "message": "duplicate_candidate_ids must be recomputed from candidate_sets",
                "expected": recomputed_duplicates,
                "actual": row.get("duplicate_candidate_ids", []),
            })
    if payload.get("trusted_final_claim") is True:
        errors.append({"field": "trusted_final_claim", "message": "candidate-set consistency cannot be a trusted final claim"})
    if payload.get("release_completion_eligible") is True:
        errors.append({"field": "release_completion_eligible", "message": "candidate-set consistency cannot make release completion eligible"})
    if payload.get("deliverable_complete") is True:
        errors.append({"field": "deliverable_complete", "message": "candidate-set consistency cannot be deliverable-complete evidence"})

    recomputed = _recompute_candidate_set_summary(candidate_sets)
    for field in (
        "status",
        "candidate_set_consistency_status",
        "required_source_count",
        "present_source_count",
        "missing_sources",
        "empty_sources",
        "duplicate_sources",
        "all_required_sources_present",
        "all_sources_nonempty",
        "all_required_sources_match_and_nonempty",
        "union_candidate_count",
        "union_candidate_ids",
        "common_candidate_count",
        "common_candidate_ids",
        "source_only_candidate_ids",
        "source_missing_candidate_ids",
        "release_gate_only_candidate_ids",
        "binding_map_only_candidate_ids",
        "trial_ledger_only_candidate_ids",
        "release_gate_missing_candidate_ids",
        "binding_map_missing_candidate_ids",
        "trial_ledger_missing_candidate_ids",
        "pairwise_mismatch_count",
        "pairwise_mismatches",
        "blocker_count",
        "blockers",
    ):
        if payload.get(field) != recomputed[field]:
            errors.append({
                "field": field,
                "message": "derived candidate-set field does not match recomputed candidate_sets value",
                "expected": recomputed[field],
                "actual": payload.get(field),
            })

    return {
        "schema_version": DFT_CANDIDATE_SET_CONSISTENCY_VALIDATION_SCHEMA,
        "valid": not errors,
        "candidate_set_consistency_status": recomputed["candidate_set_consistency_status"],
        "status": recomputed["status"],
        "recomputed": {
            key: value
            for key, value in recomputed.items()
            if key != "raw_candidate_ids_by_source"
        },
        "errors": errors,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_candidate_set_consistency(
    out_dir: Path,
    *,
    release_gate_path: Path | None = None,
    candidate_binding_map_path: Path | None = None,
    trial_state_ledger_path: Path | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_candidate_set_consistency(
        release_gate_path=release_gate_path,
        candidate_binding_map_path=candidate_binding_map_path,
        trial_state_ledger_path=trial_state_ledger_path,
    )
    write_json(out_dir / "dft_candidate_set_consistency.json", payload)
    validation = validate_dft_candidate_set_consistency(payload)
    write_json(out_dir / "dft_candidate_set_consistency_validation.json", validation)
    validation_status = "passed" if validation["valid"] else "failed_validation"
    candidate_set_consistency_passed = bool(
        validation["valid"] and payload["status"] == "passed"
    )
    status = {
        "schema_version": "dse.dft.candidate_set_consistency_status.v1",
        "status": payload["status"] if validation["valid"] else "failed_validation",
        "validation_status": validation_status,
        "artifact_validation_valid": validation["valid"],
        "candidate_set_consistency_passed": candidate_set_consistency_passed,
        "consistency_result": payload["status"],
        "candidate_set_consistency_status": payload["candidate_set_consistency_status"],
        "candidate_set_consistency": "dft_candidate_set_consistency.json",
        "validation": "dft_candidate_set_consistency_validation.json",
        "present_source_count": payload["present_source_count"],
        "union_candidate_count": payload["union_candidate_count"],
        "blocker_count": payload["blocker_count"],
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_candidate_set_consistency_status.json", status)
    return status


__all__ = [
    "DFT_CANDIDATE_SET_CONSISTENCY_SCHEMA",
    "DFT_CANDIDATE_SET_CONSISTENCY_VALIDATION_SCHEMA",
    "build_dft_candidate_set_consistency",
    "validate_dft_candidate_set_consistency",
    "write_dft_candidate_set_consistency",
]
