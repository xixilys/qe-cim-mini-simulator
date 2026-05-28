#!/usr/bin/env python3
"""Summarize search feedback/replay safety audits across DSE run directories.

This is a read-only control-plane auditor.  It validates existing
``search_feedback_closure_audit.json`` and ``search_replay_safety_audit.json``
artifacts and reports whether a set of runs is ready for the next search
iteration without re-requesting observed or rejected candidates.  It does not
execute Step3, widen Campaign budgets, claim convergence, or select winners.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.contracts import CONTRACT_VERSION, SCHEMA_REGISTRY, validate_instance
from dse_v2.codesign.release_domain import stable_json_hash


RELEASE_PACKAGE_NAME = "complete_dse_release_artifact_package.json"
RELEASE_HASH_MANIFEST_NAME = "complete_dse_release_artifact_hash_manifest.json"


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _payload_sha256(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_ref(path: Path, *, required: bool) -> Dict[str, Any]:
    exists = path.is_file()
    return {
        "path": str(path),
        "required": required,
        "exists": exists,
        "sha256": _file_sha256(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _ordered_unique(values: Iterable[Any]) -> List[str]:
    ordered: List[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "")
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _row_values(row: Mapping[str, Any], keys: Sequence[str]) -> List[str]:
    values: List[str] = []
    for key in keys:
        value = str(row.get(key) or "")
        if value and value not in values:
            values.append(value)
    refs = row.get("candidate_refs")
    if isinstance(refs, Mapping):
        for key in keys:
            value = str(refs.get(key) or "")
            if value and value not in values:
                values.append(value)
    return values


_CANDIDATE_ID_KEYS = (
    "selected_candidate_id",
    "candidate_id",
    "search_iteration_candidate_id",
    "matched_search_candidate_id",
    "search_policy_candidate_id",
    "materialized_architecture_candidate_id",
    "source_proposal_id",
    "mapping_candidate_id",
)

_PARAMETER_HASH_KEYS = (
    "architecture_parameter_hash",
    "architecture_instance_hash",
    "source_proposal_hash",
    "parameter_hash",
    "candidate_parameter_hash",
    "selected_candidate_parameter_hash",
    "selected_parameter_hash",
    "search_iteration_parameter_hash",
    "matched_search_candidate_parameter_hash",
    "request_parameter_hash",
    "search_policy_parameter_hash",
    "request_search_policy_parameter_hash",
    "mapping_parameter_hash",
    "request_mapping_parameter_hash",
)


def _is_parameter_hash(value: Any) -> bool:
    return str(value or "").startswith("sha256:")


def _row_has_materialized_architecture_identity(row: Mapping[str, Any]) -> bool:
    return bool(
        _row_values(
            row,
            (
                "materialized_architecture_candidate_id",
                "architecture_parameter_hash",
                "architecture_instance_hash",
                "source_proposal_hash",
                "source_proposal_id",
            ),
        )
    )


def _candidate_aliases(row: Mapping[str, Any]) -> List[str]:
    if _row_has_materialized_architecture_identity(row):
        return _ordered_unique(
            value
            for value in _row_values(
                row,
                (
                    "selected_candidate_id",
                    "candidate_id",
                    "search_iteration_candidate_id",
                    "matched_search_candidate_id",
                    "search_policy_candidate_id",
                    "materialized_architecture_candidate_id",
                    "source_proposal_id",
                    "mapping_candidate_id",
                ),
            )
            if not _is_parameter_hash(value)
        )
    return _ordered_unique(
        value
        for value in _row_values(row, _CANDIDATE_ID_KEYS)
        if not _is_parameter_hash(value)
    )


def _candidate_parameter_hashes(row: Mapping[str, Any]) -> List[str]:
    parameter_keys = (
        (
            "architecture_parameter_hash",
            "architecture_instance_hash",
            "source_proposal_hash",
            "parameter_hash",
            "candidate_parameter_hash",
            "selected_candidate_parameter_hash",
            "selected_parameter_hash",
        )
        if _row_has_materialized_architecture_identity(row)
        else _PARAMETER_HASH_KEYS
    )
    values = list(_row_values(row, parameter_keys))
    raw_hashes = row.get("parameter_hashes")
    if isinstance(raw_hashes, list):
        values.extend(str(value or "") for value in raw_hashes)
    refs = row.get("candidate_refs")
    if isinstance(refs, Mapping) and isinstance(refs.get("parameter_hashes"), list):
        values.extend(str(value or "") for value in refs.get("parameter_hashes", []) or [])
    raw_aliases = row.get("aliases") if isinstance(row.get("aliases"), list) else [row.get("alias")]
    values.extend(str(value or "") for value in raw_aliases if _is_parameter_hash(value))
    return _ordered_unique(value for value in values if _is_parameter_hash(value))


def _non_hash_aliases(values: Iterable[Any]) -> List[str]:
    return _ordered_unique(
        value for value in values if str(value or "") and not _is_parameter_hash(value)
    )


def _first_row_value(row: Mapping[str, Any], keys: Sequence[str]) -> str:
    values = _row_values(row, keys)
    return values[0] if values else ""


def _discover_run_dirs(
    roots: Iterable[Path],
    *,
    max_depth: int = 5,
    max_dirs: int = 50_000,
) -> List[Path]:
    discovered: List[Path] = []
    seen: set[Path] = set()
    audit_names = {"search_feedback_closure_audit.json", "search_replay_safety_audit.json"}
    for root in roots:
        root = root.resolve()
        if not root.exists():
            continue
        if not root.is_dir():
            continue
        stack: List[tuple[Path, int]] = [(root, 0)]
        visited_count = 0
        while stack:
            current, depth = stack.pop()
            visited_count += 1
            if visited_count > max_dirs:
                break
            try:
                has_audit = any((current / name).exists() for name in audit_names)
            except OSError:
                continue
            if has_audit:
                resolved = current.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    discovered.append(resolved)
            if depth >= max_depth:
                continue
            try:
                children = [child for child in current.iterdir() if child.is_dir() and not child.is_symlink()]
            except OSError:
                continue
            stack.extend((child, depth + 1) for child in reversed(sorted(children)))
    return sorted(discovered, key=lambda path: str(path))


def _validate_if_present(path: Path, schema_id: str) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = _load_json(path)
    _validate_registered_schema(payload, schema_id)
    return payload


def _validate_registered_schema(payload: Mapping[str, Any], schema_id: str) -> None:
    """Validate ``payload`` against a registered schema, fail-closed."""

    validate_instance(payload, SCHEMA_REGISTRY[schema_id])


def _global_check_failures(payload: Mapping[str, Any]) -> List[str]:
    checks = _as_mapping(payload.get("global_checks"))
    false_is_safe = {
        "campaign_plan_safe_to_execute_step3",
        "execution_allowed",
        "hidden_evidence_fanout_allowed",
        "release_completion_eligible",
        "search_plan_safe_to_execute_step3",
        "trusted_final_claim",
    }
    return sorted(
        key
        for key, value in checks.items()
        if value is False and key not in false_is_safe
    )


def _lineage_candidate_ids(closure: Mapping[str, Any]) -> List[str]:
    ids: List[str] = []
    seen: set[str] = set()
    for row in closure.get("lineage", []) or []:
        if not isinstance(row, Mapping):
            continue
        # Only rows that were actually submitted to the explicit sweep count as
        # consumed search budget for cross-round replay safety.
        if row.get("returncode") is None:
            continue
        value = str(row.get("selected_candidate_id") or "")
        if value and value not in seen:
            seen.add(value)
            ids.append(value)
    return ids


def _lineage_candidate_aliases(closure: Mapping[str, Any]) -> List[str]:
    aliases: List[str] = []
    seen: set[str] = set()
    for row in closure.get("lineage", []) or []:
        if not isinstance(row, Mapping):
            continue
        if row.get("returncode") is None:
            continue
        for value in _candidate_aliases(row):
            if value and value not in seen:
                seen.add(value)
                aliases.append(value)
    return aliases


def _lineage_candidate_parameter_hashes(closure: Mapping[str, Any]) -> List[str]:
    hashes: List[str] = []
    seen: set[str] = set()
    for row in closure.get("lineage", []) or []:
        if not isinstance(row, Mapping):
            continue
        if row.get("returncode") is None:
            continue
        for value in _candidate_parameter_hashes(row):
            if value and value not in seen:
                seen.add(value)
                hashes.append(value)
    return hashes


def _lineage_candidate_identity_rows(closure: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in closure.get("lineage", []) or []:
        if not isinstance(row, Mapping) or row.get("returncode") is None:
            continue
        selected_candidate_id = str(row.get("selected_candidate_id") or "")
        selected_hash = _first_row_value(
            row,
            (
                "selected_candidate_parameter_hash",
                "mapping_parameter_hash",
                "candidate_parameter_hash",
                "parameter_hash",
            ),
        )
        if selected_candidate_id:
            rows.append({
                "role": "executed_selected_candidate",
                "candidate_id": selected_candidate_id,
                "parameter_hash": selected_hash,
                "materialized_architecture_candidate_id": str(row.get("materialized_architecture_candidate_id") or ""),
                "architecture_id": str(row.get("architecture_id") or ""),
                "architecture_parameter_hash": str(row.get("architecture_parameter_hash") or ""),
                "source_proposal_hash": str(row.get("source_proposal_hash") or ""),
                "run_dir": str(row.get("run_dir") or ""),
                "source_materialized_dir": str(row.get("source_materialized_dir") or ""),
            })
        search_iteration_candidate_id = str(row.get("search_iteration_candidate_id") or "")
        search_iteration_hash = _first_row_value(
            row,
            (
                "search_iteration_parameter_hash",
                "search_policy_parameter_hash",
                "candidate_parameter_hash",
                "parameter_hash",
            ),
        )
        if search_iteration_candidate_id:
            rows.append({
                "role": "search_iteration_candidate",
                "candidate_id": search_iteration_candidate_id,
                "parameter_hash": search_iteration_hash,
                "materialized_architecture_candidate_id": str(row.get("materialized_architecture_candidate_id") or ""),
                "architecture_id": str(row.get("architecture_id") or ""),
                "architecture_parameter_hash": str(row.get("architecture_parameter_hash") or ""),
                "source_proposal_hash": str(row.get("source_proposal_hash") or ""),
                "run_dir": str(row.get("run_dir") or ""),
                "source_materialized_dir": str(row.get("source_materialized_dir") or ""),
            })
    return rows


def _observed_feedback_aliases(replay: Mapping[str, Any]) -> List[str]:
    aliases: List[str] = []
    seen: set[str] = set()
    for row in replay.get("observed_feedback_classification", []) or []:
        if not isinstance(row, Mapping):
            continue
        explicit_aliases = _non_hash_aliases(
            row.get("aliases") if isinstance(row.get("aliases"), list) else [row.get("alias")]
        )
        for value in [*explicit_aliases, *_candidate_aliases(row)]:
            alias = str(value or "")
            if alias and alias not in seen:
                seen.add(alias)
                aliases.append(alias)
    return aliases


def _observed_feedback_parameter_hashes(replay: Mapping[str, Any]) -> List[str]:
    hashes: List[str] = []
    seen: set[str] = set()
    for row in replay.get("observed_feedback_classification", []) or []:
        if not isinstance(row, Mapping):
            continue
        for value in _candidate_parameter_hashes(row):
            if value and value not in seen:
                seen.add(value)
                hashes.append(value)
    return hashes


def _request_candidate_ids(replay: Mapping[str, Any]) -> List[str]:
    ids: List[str] = []
    seen: set[str] = set()
    for row in replay.get("campaign_request_lineage", []) or []:
        if not isinstance(row, Mapping):
            continue
        for key in ("candidate_id", "matched_search_candidate_id"):
            value = str(row.get(key) or "")
            if value and value not in seen:
                seen.add(value)
                ids.append(value)
    return ids


def _request_candidate_aliases(replay: Mapping[str, Any]) -> List[str]:
    aliases: List[str] = []
    seen: set[str] = set()
    for row in replay.get("campaign_request_lineage", []) or []:
        if not isinstance(row, Mapping):
            continue
        explicit_aliases = _non_hash_aliases(
            row.get("aliases") if isinstance(row.get("aliases"), list) else []
        )
        for value in [*explicit_aliases, *_candidate_aliases(row)]:
            alias = str(value or "")
            if alias and alias not in seen:
                seen.add(alias)
                aliases.append(alias)
    return aliases


def _request_candidate_parameter_hashes(replay: Mapping[str, Any]) -> List[str]:
    hashes: List[str] = []
    seen: set[str] = set()
    for row in replay.get("campaign_request_lineage", []) or []:
        if not isinstance(row, Mapping):
            continue
        for value in _candidate_parameter_hashes(row):
            if value and value not in seen:
                seen.add(value)
                hashes.append(value)
    return hashes


def _feedback_influence_entry(run_dir: Path) -> Dict[str, Any]:
    """Return per-run feedback-influence audit fields from search_iteration_plan.

    Closure/replay audits prove that feedback was wired through safely.  This
    sidecar check proves that the feedback also affected the replayed search
    policy's ordering or scores.  It remains read-only and never upgrades the
    run into convergence/final-ranking evidence.
    """

    plan_path = run_dir / "search_iteration_plan.json"
    if not plan_path.exists():
        return {
            "search_iteration_plan_present": False,
            "feedback_influence_summary_present": False,
            "feedback_influenced_ordering": False,
            "feedback_influenced_scores": False,
            "feedback_influenced_candidate_selection": False,
            "feedback_influence_applied_feedback_count": 0,
            "feedback_influence_blocker_count": 1,
            "feedback_influence_blockers": [
                {
                    "reason_id": "missing_search_iteration_plan_for_feedback_influence",
                    "run_dir": str(run_dir),
                }
            ],
            "feedback_influence_claim_boundary": "",
        }
    plan = _load_json(plan_path)
    _validate_registered_schema(plan, "dse.step2.search_iteration_plan.v1")
    influence = _as_mapping(plan.get("feedback_influence_summary"))
    if not influence:
        return {
            "search_iteration_plan_present": True,
            "feedback_influence_summary_present": False,
            "feedback_influenced_ordering": False,
            "feedback_influenced_scores": False,
            "feedback_influenced_candidate_selection": False,
            "feedback_influence_applied_feedback_count": int(plan.get("applied_feedback_count", 0) or 0),
            "feedback_influence_blocker_count": 1,
            "feedback_influence_blockers": [
                {
                    "reason_id": "missing_feedback_influence_summary",
                    "run_dir": str(run_dir),
                }
            ],
            "feedback_influence_claim_boundary": "",
        }

    raw_blockers = [
        str(item or "")
        for item in influence.get("feedback_influence_blockers", []) or []
        if str(item or "")
    ]
    applied_feedback_count = int(influence.get("applied_feedback_count", 0) or 0)
    influenced_ordering = bool(influence.get("feedback_influenced_ordering"))
    influenced_scores = bool(influence.get("feedback_influenced_scores"))
    influenced_selection = bool(
        influence.get("feedback_influenced_candidate_selection")
        or influenced_ordering
        or influenced_scores
    )
    blockers: List[Dict[str, str]] = [
        {
            "reason_id": f"feedback_influence_summary_blocker:{reason}",
            "run_dir": str(run_dir),
        }
        for reason in raw_blockers
    ]
    if applied_feedback_count <= 0:
        blockers.append({
            "reason_id": "feedback_influence_no_applied_feedback",
            "run_dir": str(run_dir),
        })
    if not influenced_selection:
        blockers.append({
            "reason_id": "feedback_did_not_influence_ordering_or_scores",
            "run_dir": str(run_dir),
        })
    if influence.get("safe_to_execute_step3_from_summary") not in (None, False):
        blockers.append({
            "reason_id": "feedback_influence_summary_claims_step3_execution_authority",
            "run_dir": str(run_dir),
        })
    if influence.get("safe_to_claim_convergence_from_summary") not in (None, False):
        blockers.append({
            "reason_id": "feedback_influence_summary_claims_convergence_authority",
            "run_dir": str(run_dir),
        })
    if influence.get("trusted_final_claim") not in (None, False):
        blockers.append({
            "reason_id": "feedback_influence_summary_trusted_final_claim",
            "run_dir": str(run_dir),
        })
    if influence.get("release_completion_eligible") not in (None, False):
        blockers.append({
            "reason_id": "feedback_influence_summary_release_completion_eligible",
            "run_dir": str(run_dir),
        })

    return {
        "search_iteration_plan_present": True,
        "feedback_influence_summary_present": True,
        "feedback_influenced_ordering": influenced_ordering,
        "feedback_influenced_scores": influenced_scores,
        "feedback_influenced_candidate_selection": influenced_selection,
        "feedback_influence_applied_feedback_count": applied_feedback_count,
        "feedback_influence_blocker_count": len(blockers),
        "feedback_influence_blockers": blockers,
        "feedback_influence_claim_boundary": str(influence.get("claim_boundary") or ""),
    }


def _cross_run_replay_audit(entries: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Check ordered multi-round summaries for candidate replay regressions.

    Per-run replay audits prove one sweep does not immediately re-request the
    feedback it just observed.  This aggregate check adds the chain-level guard:
    later run dirs must not spend budget on candidates consumed by earlier run
    dirs.  The check is order-sensitive and follows the caller/discovery order.
    """

    prior_observed: set[str] = set()
    prior_executed: set[str] = set()
    prior_executed_hashes: set[str] = set()
    prior_observed_hashes: set[str] = set()
    duplicate_executed: List[str] = []
    duplicate_executed_hashes: List[str] = []
    re_requested_observed: List[str] = []
    re_requested_observed_hashes: List[str] = []
    blockers: List[Dict[str, str]] = []
    seen_duplicate_executed: set[str] = set()
    seen_duplicate_executed_hashes: set[str] = set()
    seen_re_requested: set[str] = set()
    seen_re_requested_hashes: set[str] = set()

    for entry in entries:
        run_dir = str(entry.get("run_dir") or "")
        request_ids = set(entry.get("campaign_request_candidate_ids", []) or [])
        request_aliases = set(entry.get("campaign_request_candidate_aliases", []) or [])
        request_hashes = set(entry.get("campaign_request_candidate_parameter_hashes", []) or [])
        executed_ids = set(entry.get("executed_candidate_ids", []) or [])
        executed_aliases = set(entry.get("executed_candidate_aliases", []) or [])
        executed_hashes = set(entry.get("executed_candidate_parameter_hashes", []) or [])
        observed_aliases = set(entry.get("observed_feedback_aliases", []) or [])
        observed_hashes = set(entry.get("observed_feedback_parameter_hashes", []) or [])

        repeated_execution = sorted(executed_ids & prior_executed)
        for candidate_id in repeated_execution:
            if candidate_id not in seen_duplicate_executed:
                seen_duplicate_executed.add(candidate_id)
                duplicate_executed.append(candidate_id)
            blockers.append({
                "reason_id": "cross_run_candidate_executed_more_than_once",
                "run_dir": run_dir,
                "candidate_id": candidate_id,
            })

        if not repeated_execution:
            repeated_execution_hashes = sorted(executed_hashes & prior_executed_hashes)
            for parameter_hash in repeated_execution_hashes:
                if parameter_hash not in seen_duplicate_executed_hashes:
                    seen_duplicate_executed_hashes.add(parameter_hash)
                    duplicate_executed_hashes.append(parameter_hash)
                blockers.append({
                    "reason_id": "cross_run_candidate_parameter_hash_executed_more_than_once",
                    "run_dir": run_dir,
                    "parameter_hash": parameter_hash,
                })

        re_requested = sorted((request_ids | request_aliases) & prior_observed)
        for candidate_id in re_requested:
            if candidate_id not in seen_re_requested:
                seen_re_requested.add(candidate_id)
                re_requested_observed.append(candidate_id)
            blockers.append({
                "reason_id": "cross_run_observed_candidate_re_requested",
                "run_dir": run_dir,
                "candidate_id": candidate_id,
            })

        if not re_requested:
            re_requested_hashes = sorted(request_hashes & prior_observed_hashes)
            for parameter_hash in re_requested_hashes:
                if parameter_hash not in seen_re_requested_hashes:
                    seen_re_requested_hashes.add(parameter_hash)
                    re_requested_observed_hashes.append(parameter_hash)
                blockers.append({
                    "reason_id": "cross_run_observed_candidate_parameter_hash_re_requested",
                    "run_dir": run_dir,
                    "parameter_hash": parameter_hash,
                })

        prior_executed.update(executed_ids)
        prior_executed_hashes.update(executed_hashes)
        prior_observed.update(executed_ids)
        prior_observed.update(executed_aliases)
        prior_observed.update(observed_aliases)
        prior_observed_hashes.update(executed_hashes)
        prior_observed_hashes.update(observed_hashes)

    return {
        "ordered_run_count": len(entries),
        "cross_run_replay_safe": not blockers,
        "cross_run_blocker_count": len(blockers),
        "cross_run_blockers": blockers,
        "duplicate_executed_candidate_count": len(duplicate_executed),
        "duplicate_executed_candidate_ids": duplicate_executed,
        "duplicate_executed_candidate_parameter_hash_count": len(duplicate_executed_hashes),
        "duplicate_executed_candidate_parameter_hashes": duplicate_executed_hashes,
        "re_requested_observed_candidate_count": len(re_requested_observed),
        "re_requested_observed_candidate_ids": re_requested_observed,
        "re_requested_observed_candidate_parameter_hash_count": len(re_requested_observed_hashes),
        "re_requested_observed_candidate_parameter_hashes": re_requested_observed_hashes,
        "claim_boundary": (
            "Cross-run replay checks are ordered control-plane checks only. "
            "They do not execute evidence or prove search convergence."
        ),
    }


def _search_feedback_influence_audit(entries: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    blockers: List[Dict[str, str]] = []
    influence_audit_count = 0
    influenced_round_count = 0
    for entry in entries:
        if entry.get("feedback_influence_summary_present"):
            influence_audit_count += 1
        if entry.get("feedback_influenced_candidate_selection"):
            influenced_round_count += 1
        blockers.extend(
            dict(blocker)
            for blocker in entry.get("feedback_influence_blockers", []) or []
            if isinstance(blocker, Mapping)
        )
    return {
        "feedback_influence_audit_count": influence_audit_count,
        "missing_feedback_influence_audit_count": max(0, len(entries) - influence_audit_count),
        "feedback_influenced_round_count": influenced_round_count,
        "feedback_influence_safe": bool(entries) and not blockers,
        "all_feedback_influence_effective": bool(entries) and influenced_round_count == len(entries) and not blockers,
        "feedback_influence_blocker_count": len(blockers),
        "feedback_influence_blockers": blockers,
        "claim_boundary": (
            "Feedback-influence loop checks prove only that existing Step4 "
            "feedback changed replayed Step2 search ordering or scores. They "
            "do not prove convergence, final ranking, Step3 execution authority, "
            "or release completion."
        ),
    }


def _search_progression_audit(entries: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Check that safe rounds also move new/actionable candidates forward.

    Replay safety alone can be vacuous: a loop may avoid duplicates while never
    turning requests into executed candidates or never discovering another
    actionable next candidate.  This audit stays read-only and claim-bounded; it
    only inspects existing run artifacts and reports whether the ordered chain is
    making control-plane progress toward new candidate work.
    """

    blockers: List[Dict[str, str]] = []
    enriched_entries: List[Dict[str, Any]] = []
    prior_seen_aliases: set[str] = set()
    prior_seen_hashes: set[str] = set()
    prior_executed_ids: set[str] = set()
    prior_executed_hashes: set[str] = set()
    prior_request_aliases: set[str] = set()
    prior_request_hashes: set[str] = set()
    new_executed_candidate_ids: List[str] = []
    new_executed_candidate_parameter_hashes: List[str] = []
    new_campaign_request_candidate_ids: List[str] = []
    new_campaign_request_candidate_parameter_hashes: List[str] = []
    request_to_execution_progressed_candidate_ids: List[str] = []
    request_to_execution_progressed_candidate_parameter_hashes: List[str] = []
    candidate_progression_ids: List[str] = []
    candidate_progression_parameter_hashes: List[str] = []
    effective_round_count = 0

    if not entries:
        blockers.append({
            "reason_id": "no_run_dirs_to_audit_for_search_progression",
            "run_dir": "",
        })

    for index, entry in enumerate(entries, start=1):
        run_dir = str(entry.get("run_dir") or "")
        executed_ids = _ordered_unique(entry.get("executed_candidate_ids", []) or [])
        executed_aliases = _ordered_unique([
            *executed_ids,
            *(entry.get("executed_candidate_aliases", []) or []),
        ])
        executed_hashes = _ordered_unique(entry.get("executed_candidate_parameter_hashes", []) or [])
        observed_aliases = _ordered_unique(entry.get("observed_feedback_aliases", []) or [])
        observed_hashes = _ordered_unique(entry.get("observed_feedback_parameter_hashes", []) or [])
        request_ids = _ordered_unique(entry.get("campaign_request_candidate_ids", []) or [])
        request_aliases = _ordered_unique([
            *request_ids,
            *(entry.get("campaign_request_candidate_aliases", []) or []),
        ])
        request_hashes = _ordered_unique(entry.get("campaign_request_candidate_parameter_hashes", []) or [])
        executed_count = int(entry.get("executed_candidate_count", len(executed_ids)) or 0)
        feedback_count = int(entry.get("feedback_update_count", 0) or 0)
        actionable_next_count = int(entry.get("actionable_next_candidate_count", 0) or 0)
        if actionable_next_count == 0:
            actionable_next_count = int(entry.get("campaign_step2_iteration_request_count", 0) or 0) + int(
                entry.get("campaign_materialized_step3_entry_count", 0) or 0
            )

        entry_blockers: List[Dict[str, str]] = []
        audits_present = bool(entry.get("closure_audit_present")) and bool(entry.get("replay_safety_audit_present"))
        if not audits_present:
            entry_blockers.append({
                "reason_id": "progression_not_evaluable_missing_audits",
                "run_dir": run_dir,
            })
        else:
            if executed_count <= 0:
                entry_blockers.append({
                    "reason_id": "no_executed_candidates_in_round",
                    "run_dir": run_dir,
                })
            if feedback_count <= 0:
                entry_blockers.append({
                    "reason_id": "no_feedback_updates_in_round",
                    "run_dir": run_dir,
                })
            if actionable_next_count <= 0:
                entry_blockers.append({
                    "reason_id": "no_actionable_next_candidate_for_followup",
                    "run_dir": run_dir,
                })
        new_round_executed_ids = [
            candidate_id
            for candidate_id in executed_ids
            if candidate_id not in prior_executed_ids and candidate_id not in prior_seen_aliases
        ]
        new_round_executed_hashes = [
            parameter_hash
            for parameter_hash in executed_hashes
            if parameter_hash not in prior_executed_hashes and parameter_hash not in prior_seen_hashes
        ]
        prior_request_hits = _ordered_unique(alias for alias in executed_aliases if alias in prior_request_aliases)
        prior_request_hash_hits = _ordered_unique(parameter_hash for parameter_hash in executed_hashes if parameter_hash in prior_request_hashes)
        request_progress_ids = [
            candidate_id
            for candidate_id in executed_ids
            if candidate_id in prior_request_aliases
        ]
        if not request_progress_ids and prior_request_hits:
            request_progress_ids = list(prior_request_hits)
        request_progress_hashes = [
            parameter_hash
            for parameter_hash in executed_hashes
            if parameter_hash in prior_request_hashes
        ]
        if not request_progress_hashes and prior_request_hash_hits:
            request_progress_hashes = list(prior_request_hash_hits)
        new_round_request_ids = [
            candidate_id
            for candidate_id in request_ids
            if candidate_id not in prior_seen_aliases and candidate_id not in prior_request_aliases
        ]
        new_round_request_hashes = [
            parameter_hash
            for parameter_hash in request_hashes
            if parameter_hash not in prior_seen_hashes and parameter_hash not in prior_request_hashes
        ]

        if audits_present and index > 1:
            if executed_count > 0 and not new_round_executed_ids:
                entry_blockers.append({
                    "reason_id": "no_new_executed_candidate_in_round",
                    "run_dir": run_dir,
                })
            if executed_count > 0 and executed_hashes and not new_round_executed_hashes:
                entry_blockers.append({
                    "reason_id": "no_new_executed_candidate_parameter_hash_in_round",
                    "run_dir": run_dir,
                })
        if audits_present and actionable_next_count > 0 and request_ids and not new_round_request_ids:
            entry_blockers.append({
                "reason_id": "no_new_actionable_campaign_request_candidate",
                "run_dir": run_dir,
            })
        if (
            audits_present
            and actionable_next_count > 0
            and request_hashes
            and not new_round_request_hashes
            and not any(request_id in prior_seen_aliases for request_id in request_ids)
        ):
            entry_blockers.append({
                "reason_id": "no_new_actionable_campaign_request_parameter_hash",
                "run_dir": run_dir,
            })

        for candidate_id in new_round_executed_ids:
            if candidate_id not in new_executed_candidate_ids:
                new_executed_candidate_ids.append(candidate_id)
            if candidate_id not in candidate_progression_ids:
                candidate_progression_ids.append(candidate_id)
        for parameter_hash in new_round_executed_hashes:
            if parameter_hash not in new_executed_candidate_parameter_hashes:
                new_executed_candidate_parameter_hashes.append(parameter_hash)
            if parameter_hash not in candidate_progression_parameter_hashes:
                candidate_progression_parameter_hashes.append(parameter_hash)
        for candidate_id in new_round_request_ids:
            if candidate_id not in new_campaign_request_candidate_ids:
                new_campaign_request_candidate_ids.append(candidate_id)
            if candidate_id not in candidate_progression_ids:
                candidate_progression_ids.append(candidate_id)
        for parameter_hash in new_round_request_hashes:
            if parameter_hash not in new_campaign_request_candidate_parameter_hashes:
                new_campaign_request_candidate_parameter_hashes.append(parameter_hash)
            if parameter_hash not in candidate_progression_parameter_hashes:
                candidate_progression_parameter_hashes.append(parameter_hash)
        for candidate_id in request_progress_ids:
            if candidate_id not in request_to_execution_progressed_candidate_ids:
                request_to_execution_progressed_candidate_ids.append(candidate_id)
            if candidate_id not in candidate_progression_ids:
                candidate_progression_ids.append(candidate_id)
        for parameter_hash in request_progress_hashes:
            if parameter_hash not in request_to_execution_progressed_candidate_parameter_hashes:
                request_to_execution_progressed_candidate_parameter_hashes.append(parameter_hash)
            if parameter_hash not in candidate_progression_parameter_hashes:
                candidate_progression_parameter_hashes.append(parameter_hash)

        effective_round = audits_present and not entry_blockers
        if effective_round:
            effective_round_count += 1
        blockers.extend(entry_blockers)
        enriched = dict(entry)
        enriched.update({
            "round_index": index,
            "actionable_next_candidate_count": actionable_next_count,
            "has_executed_feedback": bool(executed_count > 0 and feedback_count > 0),
            "new_executed_candidate_count": len(new_round_executed_ids),
            "new_executed_candidate_ids": new_round_executed_ids,
            "new_executed_candidate_parameter_hash_count": len(new_round_executed_hashes),
            "new_executed_candidate_parameter_hashes": new_round_executed_hashes,
            "new_campaign_request_candidate_count": len(new_round_request_ids),
            "new_campaign_request_candidate_ids": new_round_request_ids,
            "new_campaign_request_candidate_parameter_hash_count": len(new_round_request_hashes),
            "new_campaign_request_candidate_parameter_hashes": new_round_request_hashes,
            "request_to_execution_progressed_candidate_count": len(request_progress_ids),
            "request_to_execution_progressed_candidate_ids": request_progress_ids,
            "request_to_execution_progressed_candidate_parameter_hash_count": len(request_progress_hashes),
            "request_to_execution_progressed_candidate_parameter_hashes": request_progress_hashes,
            "effective_search_round": bool(effective_round),
            "progression_blocker_count": len(entry_blockers),
            "progression_blockers": entry_blockers,
        })
        enriched_entries.append(enriched)

        prior_executed_ids.update(executed_ids)
        prior_executed_hashes.update(executed_hashes)
        prior_seen_aliases.update(executed_aliases)
        prior_seen_aliases.update(observed_aliases)
        prior_seen_hashes.update(executed_hashes)
        prior_seen_hashes.update(observed_hashes)
        prior_request_aliases.update(request_aliases)
        prior_request_hashes.update(request_hashes)

    return {
        "progression_safe": bool(entries) and not blockers,
        "progression_blocker_count": len(blockers),
        "progression_blockers": blockers,
        "effective_round_count": effective_round_count,
        "new_candidate_execution_count": len(new_executed_candidate_ids),
        "new_executed_candidate_ids": new_executed_candidate_ids,
        "new_executed_candidate_parameter_hash_count": len(new_executed_candidate_parameter_hashes),
        "new_executed_candidate_parameter_hashes": new_executed_candidate_parameter_hashes,
        "new_candidate_discovery_count": len(new_campaign_request_candidate_ids),
        "new_campaign_request_candidate_ids": new_campaign_request_candidate_ids,
        "new_campaign_request_candidate_parameter_hash_count": len(new_campaign_request_candidate_parameter_hashes),
        "new_campaign_request_candidate_parameter_hashes": new_campaign_request_candidate_parameter_hashes,
        "request_to_execution_progression_count": len(request_to_execution_progressed_candidate_ids),
        "request_to_execution_progressed_candidate_ids": request_to_execution_progressed_candidate_ids,
        "request_to_execution_progressed_candidate_parameter_hash_count": len(request_to_execution_progressed_candidate_parameter_hashes),
        "request_to_execution_progressed_candidate_parameter_hashes": request_to_execution_progressed_candidate_parameter_hashes,
        "candidate_progression_count": len(candidate_progression_ids),
        "candidate_progression_ids": candidate_progression_ids,
        "candidate_progression_parameter_hash_count": len(candidate_progression_parameter_hashes),
        "candidate_progression_parameter_hashes": candidate_progression_parameter_hashes,
        "entries": enriched_entries,
        "claim_boundary": (
            "Search progression checks prove only that existing ordered rounds "
            "executed new candidates, fed them back, and exposed new actionable "
            "follow-up candidates. They do not prove convergence, winner quality, "
            "or release completion."
        ),
    }


def _entry_for_run(run_dir: Path) -> Dict[str, Any]:
    closure_path = run_dir / "search_feedback_closure_audit.json"
    replay_path = run_dir / "search_replay_safety_audit.json"
    closure = _validate_if_present(
        closure_path,
        "dse.contract.search_feedback_closure_audit.v1",
    )
    replay = _validate_if_present(
        replay_path,
        "dse.contract.search_replay_safety_audit.v1",
    )
    closure_blocker_count = int(closure.get("blocker_count", 0) or 0) if closure else 0
    replay_blocker_count = int(replay.get("blocker_count", 0) or 0) if replay else 0
    executed_candidate_ids = _lineage_candidate_ids(closure) if closure else []
    executed_candidate_aliases = _lineage_candidate_aliases(closure) if closure else []
    observed_feedback_aliases = _observed_feedback_aliases(replay) if replay else []
    observed_feedback_parameter_hashes = _observed_feedback_parameter_hashes(replay) if replay else []
    campaign_request_candidate_ids = _request_candidate_ids(replay) if replay else []
    campaign_request_candidate_aliases = _request_candidate_aliases(replay) if replay else []
    campaign_request_candidate_parameter_hashes = _request_candidate_parameter_hashes(replay) if replay else []
    executed_candidate_parameter_hashes = _lineage_candidate_parameter_hashes(closure) if closure else []
    candidate_identity_rows = _lineage_candidate_identity_rows(closure) if closure else []
    campaign_step2_iteration_request_count = int(
        replay.get("campaign_step2_iteration_request_count", 0) or 0
    ) if replay else 0
    campaign_materialized_step3_entry_count = int(
        replay.get("campaign_materialized_step3_entry_count", 0) or 0
    ) if replay else 0
    executed_candidate_count = int(closure.get("executed_candidate_count", 0) or 0) if closure else 0
    feedback_update_count = int(closure.get("feedback_update_count", 0) or 0) if closure else 0
    entry = {
        "run_dir": str(run_dir),
        "closure_audit_present": bool(closure),
        "replay_safety_audit_present": bool(replay),
        "closure_status": str(closure.get("status") or "missing") if closure else "missing",
        "replay_safety_status": str(replay.get("status") or "missing") if replay else "missing",
        "closure_blocker_count": closure_blocker_count,
        "replay_safety_blocker_count": replay_blocker_count,
        "closure_global_check_failures": _global_check_failures(closure) if closure else [],
        "replay_safety_global_check_failures": _global_check_failures(replay) if replay else [],
        "executed_candidate_count": executed_candidate_count,
        "feedback_update_count": feedback_update_count,
        "observed_feedback_alias_count": int(replay.get("observed_feedback_alias_count", 0) or 0) if replay else 0,
        "rejected_feedback_alias_count": int(replay.get("rejected_feedback_alias_count", 0) or 0) if replay else 0,
        "campaign_step2_iteration_request_count": campaign_step2_iteration_request_count,
        "campaign_materialized_step3_entry_count": campaign_materialized_step3_entry_count,
        "actionable_next_candidate_count": (
            campaign_step2_iteration_request_count + campaign_materialized_step3_entry_count
        ),
        "has_executed_feedback": bool(executed_candidate_count > 0 and feedback_update_count > 0),
        "executed_candidate_ids": executed_candidate_ids,
        "executed_candidate_aliases": executed_candidate_aliases,
        "executed_candidate_parameter_hashes": executed_candidate_parameter_hashes,
        "candidate_identity_rows": candidate_identity_rows,
        "observed_feedback_aliases": observed_feedback_aliases,
        "observed_feedback_parameter_hashes": observed_feedback_parameter_hashes,
        "campaign_request_candidate_ids": campaign_request_candidate_ids,
        "campaign_request_candidate_aliases": campaign_request_candidate_aliases or campaign_request_candidate_ids,
        "campaign_request_candidate_parameter_hashes": campaign_request_candidate_parameter_hashes,
    }
    entry.update(_feedback_influence_entry(run_dir))
    return entry


def _load_first_json(run_dir: Path, relpaths: Sequence[str]) -> tuple[str, Dict[str, Any]]:
    for relpath in relpaths:
        path = run_dir / relpath
        if path.exists():
            return relpath, _load_json(path)
    return "", {}


def _source_blocker(reason_id: str, source: str, **extra: Any) -> Dict[str, Any]:
    blocker = {"reason_id": reason_id, "source": source}
    blocker.update({key: value for key, value in extra.items() if value is not None})
    return blocker


def _release_package_target_evidence_linkage_audit(run_dir: Path) -> Dict[str, Any]:
    """Inspect optional release-package target-evidence linkage provenance.

    This check is intentionally downstream and read-only.  It consumes the
    release-package linkage when present so search-control audits can detect
    stale or blocked finite-release provenance, but it does not require a
    release package for ordinary search-effectiveness runs.
    """

    package_path = run_dir / RELEASE_PACKAGE_NAME
    manifest_path = run_dir / RELEASE_HASH_MANIFEST_NAME
    package_ref = _file_ref(package_path, required=False)
    manifest_ref = _file_ref(manifest_path, required=False)
    present = bool(package_ref["exists"] or manifest_ref["exists"])
    blockers: List[Dict[str, Any]] = []
    package: Dict[str, Any] = {}
    manifest: Dict[str, Any] = {}

    if not present:
        return {
            "schema_version": "dse.contract.search_release_package_target_evidence_linkage_audit.v1",
            "status": "not_supplied",
            "present": False,
            "closed": False,
            "package_ref": package_ref,
            "hash_manifest_ref": manifest_ref,
            "linkage": {},
            "linkage_hash": "",
            "source_matrix_evidence_gate_ids": [],
            "source_matrix_evidence_gate_id_count": 0,
            "blocker_count": 0,
            "blockers": [],
            "deliverable_complete": False,
            "claim_boundary": (
                "Release-package target-evidence linkage is optional provenance "
                "for this search-control audit. When absent, it cannot upgrade "
                "search, hardware, or deliverable-complete claims."
            ),
        }

    if package_ref["exists"] is not True:
        blockers.append(
            _source_blocker(
                "release_package_artifact_missing",
                RELEASE_PACKAGE_NAME,
                path=str(package_path),
            )
        )
    if manifest_ref["exists"] is not True:
        blockers.append(
            _source_blocker(
                "release_package_hash_manifest_missing",
                RELEASE_HASH_MANIFEST_NAME,
                path=str(manifest_path),
            )
        )

    if package_ref["exists"] is True:
        try:
            package = _load_json(package_path)
        except (OSError, json.JSONDecodeError) as exc:
            blockers.append(
                _source_blocker(
                    "release_package_artifact_unreadable",
                    RELEASE_PACKAGE_NAME,
                    error=str(exc),
                )
            )
    if manifest_ref["exists"] is True:
        try:
            manifest = _load_json(manifest_path)
        except (OSError, json.JSONDecodeError) as exc:
            blockers.append(
                _source_blocker(
                    "release_package_hash_manifest_unreadable",
                    RELEASE_HASH_MANIFEST_NAME,
                    error=str(exc),
                )
            )

    linkage = _as_mapping(package.get("target_evidence_gate_ledger_linkage"))
    manifest_linkage = _as_mapping(manifest.get("target_evidence_gate_ledger_linkage"))
    linkage_hash = str(linkage.get("linkage_hash") or "")
    source_gate_ids = [
        str(item)
        for item in linkage.get("source_matrix_evidence_gate_ids", []) or []
        if str(item)
    ]
    status = str(linkage.get("status") or "")

    if not linkage:
        blockers.append(
            _source_blocker(
                "release_package_target_evidence_linkage_missing",
                RELEASE_PACKAGE_NAME,
            )
        )
    else:
        expected_linkage_hash = stable_json_hash(
            {key: value for key, value in linkage.items() if key != "linkage_hash"}
        )
        if not linkage_hash:
            blockers.append(
                _source_blocker(
                    "release_package_target_evidence_linkage_missing_hash",
                    RELEASE_PACKAGE_NAME,
                )
            )
        elif linkage_hash != expected_linkage_hash:
            blockers.append(
                _source_blocker(
                    "release_package_target_evidence_linkage_hash_mismatch",
                    RELEASE_PACKAGE_NAME,
                    linkage_hash=linkage_hash,
                    expected_linkage_hash=expected_linkage_hash,
                )
            )
        if status != "bound":
            blockers.append(
                _source_blocker(
                    "release_package_target_evidence_linkage_not_bound",
                    RELEASE_PACKAGE_NAME,
                    linkage_status=status,
                )
            )
        if linkage.get("validation_valid") is not True:
            blockers.append(
                _source_blocker(
                    "release_package_target_evidence_linkage_validation_not_valid",
                    RELEASE_PACKAGE_NAME,
                )
            )
        if not source_gate_ids:
            blockers.append(
                _source_blocker(
                    "release_package_target_evidence_linkage_missing_source_matrix_gate_ids",
                    RELEASE_PACKAGE_NAME,
                )
            )
        if int(linkage.get("source_matrix_to_target_gate_row_count", 0) or 0) <= 0:
            blockers.append(
                _source_blocker(
                    "release_package_target_evidence_linkage_missing_target_gate_rows",
                    RELEASE_PACKAGE_NAME,
                )
            )
        if linkage.get("deliverable_complete") is not False:
            blockers.append(
                _source_blocker(
                    "release_package_target_evidence_linkage_claims_deliverable_complete",
                    RELEASE_PACKAGE_NAME,
                )
            )

    if manifest_ref["exists"] is True:
        if not manifest_linkage:
            blockers.append(
                _source_blocker(
                    "release_package_hash_manifest_missing_target_evidence_linkage",
                    RELEASE_HASH_MANIFEST_NAME,
                )
            )
        elif linkage and manifest_linkage != linkage:
            blockers.append(
                _source_blocker(
                    "release_package_target_evidence_linkage_hash_manifest_mismatch",
                    RELEASE_HASH_MANIFEST_NAME,
                )
            )
        if manifest.get("deliverable_complete") is not False:
            blockers.append(
                _source_blocker(
                    "release_package_hash_manifest_claims_deliverable_complete",
                    RELEASE_HASH_MANIFEST_NAME,
                )
            )

    if package.get("deliverable_complete") is not False:
        blockers.append(
            _source_blocker(
                "release_package_claims_deliverable_complete",
                RELEASE_PACKAGE_NAME,
            )
        )
    for key in ("trusted_final_claim", "release_completion_eligible", "hardware_completion_eligible"):
        if package.get(key) not in (None, False):
            blockers.append(
                _source_blocker(
                    f"release_package_claims_{key}",
                    RELEASE_PACKAGE_NAME,
                )
            )

    closed = present and not blockers
    return {
        "schema_version": "dse.contract.search_release_package_target_evidence_linkage_audit.v1",
        "status": "bound" if closed else "blocked",
        "present": True,
        "closed": closed,
        "package_ref": package_ref,
        "hash_manifest_ref": manifest_ref,
        "linkage": linkage,
        "linkage_hash": linkage_hash,
        "source_matrix_evidence_gate_ids": source_gate_ids,
        "source_matrix_evidence_gate_id_count": len(source_gate_ids),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "deliverable_complete": False,
        "claim_boundary": (
            "Search-control audit consumes the release-package target-evidence "
            "linkage as finite-release provenance only. It does not execute "
            "hardware evidence, trust availability probes, select a winner, or "
            "upgrade FPGA/ASIC/release-completion claims."
        ),
    }


def _release_package_recommendation_eligibility_audit(
    release_package_target_evidence_linkage_audit: Mapping[str, Any],
    *,
    effectiveness_gate_passed: bool,
) -> Dict[str, Any]:
    """Summarize whether release-package provenance can feed downstream recommendation use.

    The generic search smoke path must remain usable without a release package.
    When a release package is present, this audit only becomes eligible if the
    target-evidence linkage is bound and the search effectiveness gate is
    already closed.  It still never claims a final winner, hardware completion,
    or release completion.
    """

    present = bool(release_package_target_evidence_linkage_audit.get("present"))
    closed = bool(release_package_target_evidence_linkage_audit.get("closed"))
    linkage_status = str(release_package_target_evidence_linkage_audit.get("status") or "")
    source_gate_ids = [
        str(item)
        for item in release_package_target_evidence_linkage_audit.get("source_matrix_evidence_gate_ids", []) or []
        if str(item)
    ]
    linkage = _as_mapping(release_package_target_evidence_linkage_audit.get("linkage"))
    source_matrix_to_target_gate_row_count = int(
        linkage.get("source_matrix_to_target_gate_row_count", 0) or 0
    )
    blockers = [
        dict(blocker)
        for blocker in release_package_target_evidence_linkage_audit.get("blockers", []) or []
        if isinstance(blocker, Mapping)
    ] if present and not closed else []
    notes: List[Dict[str, Any]] = []

    if not present:
        notes.append(
            {
                "reason_id": "release_package_not_supplied_for_recommendation_input",
                "source": RELEASE_PACKAGE_NAME,
            }
        )

    if present and not closed and not blockers:
        blockers.append(
            {
                "reason_id": "release_package_target_evidence_linkage_not_bound",
                "source": RELEASE_PACKAGE_NAME,
            }
        )

    if present and closed and not effectiveness_gate_passed:
        blockers.append(
            {
                "reason_id": "search_effectiveness_gate_not_passed_for_recommendation_input",
                "source": "search_effectiveness_audit",
            }
        )

    eligible = bool(present and closed and effectiveness_gate_passed)
    if eligible:
        status = "eligible_for_downstream_recommendation_input"
    elif not present:
        status = "not_supplied_optional"
    elif not closed:
        status = "blocked_release_package_target_evidence_linkage"
    else:
        status = "blocked_search_effectiveness_gate"

    return {
        "schema_version": "dse.contract.search_release_package_recommendation_eligibility_audit.v1",
        "status": status,
        "present": present,
        "closed": eligible,
        "release_package_target_evidence_linkage_status": linkage_status,
        "release_package_target_evidence_linkage_closed": closed,
        "search_effectiveness_gate_passed": bool(effectiveness_gate_passed),
        "release_package_target_evidence_source_matrix_gate_id_count": len(source_gate_ids),
        "source_matrix_evidence_gate_ids": source_gate_ids,
        "source_matrix_to_target_gate_row_count": source_matrix_to_target_gate_row_count,
        "pareto_candidate_input_eligible": eligible,
        "recommendation_input_provenance_eligible": eligible,
        "hardware_completion_eligible": False,
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "non_blocking_notes": notes,
        "claim_boundary": (
            "Release-package target-evidence linkage can feed downstream "
            "recommendation/Pareto input eligibility only when the linkage is "
            "bound and search effectiveness is already closed. It does not "
            "authorize hardware completion, winner selection, or release "
            "completion."
        ),
    }


def build_search_effectiveness_audit(
    run_dir: Path,
    *,
    search_loop_summary: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a unified fail-closed audit for search/candidate effectiveness.

    This is a control-plane artifact only.  It ties together Step2 architecture
    search breadth, Campaign admission discipline, Step2 materialization
    coverage, and multi-round search-loop progression.  It never authorizes
    Step3 execution and never upgrades a result into convergence, final
    ranking, or release-completion evidence.
    """

    run_dir = Path(run_dir)
    blockers: List[Dict[str, Any]] = []

    coverage_ref, search_space = _load_first_json(
        run_dir,
        [
            "step2/architecture_search_space.json",
            "architecture_search_space.json",
        ],
    )
    if not coverage_ref:
        coverage_ref = "step2/architecture_search_space.json"
    coverage = _as_mapping(search_space.get("architecture_search_coverage_summary"))
    coverage_status = str(coverage.get("coverage_status") or "")
    coverage_blocker_count = int(coverage.get("blocker_count", 0) or 0) if coverage else 0
    coverage_effective = bool(
        coverage
        and coverage.get("search_space_effective") is True
        and coverage_status == "search_space_effective"
        and coverage_blocker_count == 0
    )
    coverage_count_requirements = {
        "family_count": 2,
        "parameterized_family_count": 1,
        "architecture_parameter_proposal_count": 1,
        "non_default_architecture_parameter_proposal_count": 1,
        "materialized_candidate_count": 1,
        "non_default_materialized_candidate_count": 1,
        "search_policy_candidate_count": 1,
        "non_seed_search_policy_enumeration_count": 1,
    }
    coverage_count_values = {
        field: int(coverage.get(field, 0) or 0) if coverage else 0
        for field in coverage_count_requirements
    }
    coverage_count_proof_present = bool(
        coverage
        and all(field in coverage for field in coverage_count_requirements)
    )
    coverage_count_proof_closed = bool(
        coverage_count_proof_present
        and all(
            coverage_count_values[field] >= minimum
            for field, minimum in coverage_count_requirements.items()
        )
        and coverage_count_values["family_count"] > 1
    )
    if not coverage:
        blockers.append(_source_blocker("missing_architecture_search_coverage_summary", "architecture_search_space"))
    else:
        if not coverage_effective:
            blockers.append(
                _source_blocker(
                    "architecture_search_coverage_not_effective",
                    "architecture_search_space",
                    coverage_status=coverage_status,
                    coverage_blocker_count=coverage_blocker_count,
                )
            )
        if not coverage_count_proof_present:
            blockers.append(
                _source_blocker(
                    "architecture_search_coverage_missing_count_proof",
                    "architecture_search_space",
                )
            )
        elif not coverage_count_proof_closed:
            blockers.append(
                _source_blocker(
                    "architecture_search_coverage_insufficient_count_proof",
                    "architecture_search_space",
                    family_count=coverage_count_values["family_count"],
                    parameterized_family_count=coverage_count_values["parameterized_family_count"],
                    architecture_parameter_proposal_count=coverage_count_values["architecture_parameter_proposal_count"],
                    non_default_architecture_parameter_proposal_count=coverage_count_values["non_default_architecture_parameter_proposal_count"],
                    materialized_candidate_count=coverage_count_values["materialized_candidate_count"],
                    non_default_materialized_candidate_count=coverage_count_values["non_default_materialized_candidate_count"],
                    search_policy_candidate_count=coverage_count_values["search_policy_candidate_count"],
                    non_seed_search_policy_enumeration_count=coverage_count_values[
                        "non_seed_search_policy_enumeration_count"
                    ],
                )
            )
        if coverage.get("execution_allowed") is not False:
            blockers.append(_source_blocker("architecture_search_coverage_allows_execution", "architecture_search_space"))
        if coverage.get("hidden_evidence_fanout_allowed") is not False:
            blockers.append(
                _source_blocker("architecture_search_coverage_allows_hidden_evidence_fanout", "architecture_search_space")
            )
        if coverage.get("trusted_final_claim") is not False:
            blockers.append(_source_blocker("architecture_search_coverage_claims_trusted_final_result", "architecture_search_space"))
        if coverage.get("release_completion_eligible") is not False:
            blockers.append(_source_blocker("architecture_search_coverage_claims_release_completion", "architecture_search_space"))
        if coverage.get("step3_admission_authority") not in {"step3_simulation_queue.json", "step2/step3_simulation_queue.json"}:
            blockers.append(
                _source_blocker(
                    "architecture_search_coverage_invalid_step3_admission_authority",
                    "architecture_search_space",
                    step3_admission_authority=coverage.get("step3_admission_authority"),
                )
            )
        summary_hash = str(coverage.get("summary_hash") or "")
        expected_summary_hash = _payload_sha256({
            key: value
            for key, value in coverage.items()
            if key != "summary_hash"
        })
        if not summary_hash:
            blockers.append(_source_blocker("architecture_search_coverage_missing_summary_hash", "architecture_search_space"))
        elif summary_hash != expected_summary_hash:
            blockers.append(
                _source_blocker(
                    "architecture_search_coverage_summary_hash_mismatch",
                    "architecture_search_space",
                    summary_hash=summary_hash,
                    expected_summary_hash=expected_summary_hash,
                )
            )

    admission_ref, admission = _load_first_json(run_dir, ["campaign_search_admission_plan.json"])
    if not admission_ref:
        admission_ref = "campaign_search_admission_plan.json"
    admitted_entry_count = int(admission.get("admitted_entry_count", 0) or 0) if admission else 0
    step2_iteration_request_count = int(admission.get("step2_iteration_request_count", 0) or 0) if admission else 0
    materialized_entry_count = int(admission.get("materialized_step3_queue_entry_count", 0) or 0) if admission else 0
    campaign_admission_safe = bool(
        admission
        and admission.get("execution_allowed") is False
        and admission.get("hidden_evidence_fanout_allowed") is False
        and admission.get("trusted_final_claim") is False
        and admission.get("release_completion_eligible") is False
        and admitted_entry_count == 0
    )
    if not admission:
        blockers.append(_source_blocker("missing_campaign_search_admission_plan", "campaign_search_admission_plan"))
    else:
        if admission.get("execution_allowed") is not False:
            blockers.append(_source_blocker("campaign_admission_plan_allows_execution", "campaign_search_admission_plan"))
        if admission.get("hidden_evidence_fanout_allowed") is not False:
            blockers.append(_source_blocker("campaign_admission_plan_allows_hidden_evidence_fanout", "campaign_search_admission_plan"))
        if admission.get("trusted_final_claim") is not False:
            blockers.append(_source_blocker("campaign_admission_plan_claims_trusted_final_result", "campaign_search_admission_plan"))
        if admission.get("release_completion_eligible") is not False:
            blockers.append(_source_blocker("campaign_admission_plan_claims_release_completion", "campaign_search_admission_plan"))
        if admitted_entry_count != 0:
            blockers.append(
                _source_blocker(
                    "campaign_admission_plan_contains_admitted_step3_entries",
                    "campaign_search_admission_plan",
                    admitted_entry_count=admitted_entry_count,
                )
            )

    materialization_ref, materialization = _load_first_json(run_dir, ["campaign_materialization_summary.json"])
    if not materialization_ref:
        materialization_ref = "campaign_materialization_summary.json"
    materialization_coverage_audit_ref = str(materialization.get("materialization_coverage_audit_ref") or "")
    materialization_coverage_audit_expected = bool(materialization_coverage_audit_ref)
    materialization_coverage_audit: Dict[str, Any] = {}
    if materialization_coverage_audit_ref:
        materialization_coverage_audit_path = run_dir / materialization_coverage_audit_ref
        if materialization_coverage_audit_path.exists():
            materialization_coverage_audit = _load_json(materialization_coverage_audit_path)
    else:
        materialization_coverage_audit_ref, materialization_coverage_audit = _load_first_json(
            run_dir,
            ["materialization_coverage_audit.json"],
        )
        materialization_coverage_audit_expected = bool(materialization_coverage_audit_ref)
    materialization_coverage = _as_mapping(materialization.get("materialization_coverage"))
    materialization_request_count = int(materialization.get("request_count", 0) or 0) if materialization else 0
    authorized_queue_entry_count = int(materialization.get("authorized_step3_queue_entry_count", 0) or 0) if materialization else 0
    materialization_blocker_count = int(materialization.get("materialization_coverage_blocker_count", 0) or 0) if materialization else 0
    materialization_coverage_closed = bool(
        materialization
        and materialization.get("coverage_closed") is True
        and materialization_coverage.get("coverage_closed") is True
        and materialization_blocker_count == 0
        and materialization_request_count > 0
        and authorized_queue_entry_count == materialization_request_count
        and materialization.get("execution_allowed") is False
        and materialization.get("hidden_evidence_fanout_allowed") is False
        and materialization.get("trusted_final_claim") is False
        and materialization.get("release_completion_eligible") is False
    )
    materialization_coverage_audit_closed = bool(
        materialization_coverage_audit
        and materialization_coverage_audit.get("coverage_closed") is True
        and materialization_coverage_audit.get("hash_bound_ref_status") == "present_hash_valid_non_claimable"
        and materialization_coverage_audit.get("execution_allowed") is False
        and materialization_coverage_audit.get("hidden_evidence_fanout_allowed") is False
        and materialization_coverage_audit.get("trusted_final_claim") is False
        and materialization_coverage_audit.get("release_completion_eligible") is False
    )
    if not materialization:
        blockers.append(_source_blocker("missing_campaign_materialization_summary", "campaign_materialization_summary"))
    else:
        if materialization_request_count <= 0:
            blockers.append(_source_blocker("no_materialized_step2_requests", "campaign_materialization_summary"))
        if materialization.get("coverage_closed") is not True or materialization_coverage.get("coverage_closed") is not True:
            blockers.append(_source_blocker("materialization_coverage_not_closed", "campaign_materialization_summary"))
        if materialization_blocker_count != 0:
            blockers.append(
                _source_blocker(
                    "materialization_coverage_has_blockers",
                    "campaign_materialization_summary",
                    materialization_coverage_blocker_count=materialization_blocker_count,
                )
            )
        if authorized_queue_entry_count != materialization_request_count:
            blockers.append(
                _source_blocker(
                    "authorized_step3_queue_entry_count_mismatch",
                    "campaign_materialization_summary",
                    request_count=materialization_request_count,
                    authorized_step3_queue_entry_count=authorized_queue_entry_count,
                )
            )
        if materialization.get("execution_allowed") is not False:
            blockers.append(_source_blocker("materialization_summary_allows_execution", "campaign_materialization_summary"))
        if materialization.get("hidden_evidence_fanout_allowed") is not False:
            blockers.append(_source_blocker("materialization_summary_allows_hidden_evidence_fanout", "campaign_materialization_summary"))
        if materialization.get("trusted_final_claim") is not False:
            blockers.append(_source_blocker("materialization_summary_claims_trusted_final_result", "campaign_materialization_summary"))
        if materialization.get("release_completion_eligible") is not False:
            blockers.append(_source_blocker("materialization_summary_claims_release_completion", "campaign_materialization_summary"))
    if materialization_coverage_audit_expected and not materialization_coverage_audit:
        blockers.append(_source_blocker("missing_materialization_coverage_audit", "materialization_coverage_audit"))
    elif materialization_coverage_audit_expected and not materialization_coverage_audit_closed:
        blockers.append(_source_blocker("materialization_coverage_audit_not_closed", "materialization_coverage_audit"))

    release_package_target_evidence_linkage_audit = _release_package_target_evidence_linkage_audit(run_dir)
    if release_package_target_evidence_linkage_audit.get("present") is True and not release_package_target_evidence_linkage_audit.get("closed"):
        blockers.extend(
            dict(blocker)
            for blocker in release_package_target_evidence_linkage_audit.get("blockers", []) or []
            if isinstance(blocker, Mapping)
        )

    if search_loop_summary is None:
        loop_ref, loop = _load_first_json(run_dir, ["search_loop_audit_summary.json"])
        if not loop_ref:
            loop_ref = "search_loop_audit_summary.json"
    else:
        loop_ref, loop = "search_loop_audit_summary.json", dict(search_loop_summary)
    search_loop_present = bool(loop)
    loop_status = str(loop.get("status") or "") if loop else ""
    loop_total_blocker_count = int(loop.get("total_blocker_count", 0) or 0) if loop else 0
    effective_round_count = int(loop.get("effective_round_count", 0) or 0) if loop else 0
    candidate_progression_count = int(loop.get("candidate_progression_count", 0) or 0) if loop else 0
    new_executed_candidate_parameter_hashes = list(loop.get("new_executed_candidate_parameter_hashes", []) or []) if loop else []
    new_campaign_request_candidate_parameter_hashes = list(
        loop.get("new_campaign_request_candidate_parameter_hashes", []) or []
    ) if loop else []
    request_to_execution_progressed_candidate_parameter_hashes = list(
        loop.get("request_to_execution_progressed_candidate_parameter_hashes", []) or []
    ) if loop else []
    request_to_execution_progression_count = int(loop.get("request_to_execution_progression_count", 0) or 0) if loop else 0
    request_to_execution_progressed_candidate_parameter_hash_count = len(
        request_to_execution_progressed_candidate_parameter_hashes
    )
    candidate_progression_parameter_hashes = list(
        loop.get("candidate_progression_parameter_hashes", []) or []
    ) if loop else []
    candidate_progression_parameter_hash_count = int(
        loop.get("candidate_progression_parameter_hash_count", len(candidate_progression_parameter_hashes)) or 0
    ) if loop else 0
    search_progression_safe = bool(
        loop
        and loop_status == "closed_for_next_iteration"
        and loop.get("progression_safe") is True
        and loop.get("cross_run_replay_safe") is True
        and loop.get("all_feedback_influence_effective") is True
        and loop_total_blocker_count == 0
    )
    candidate_progression_effective = bool(
        search_progression_safe
        and effective_round_count > 0
        and candidate_progression_count > 0
    )
    candidate_parameter_progression_effective = bool(
        search_progression_safe
        and candidate_progression_parameter_hash_count > 0
    )
    request_to_execution_progression_effective = bool(
        search_progression_safe
        and request_to_execution_progression_count > 0
        and request_to_execution_progressed_candidate_parameter_hash_count > 0
    )
    if not loop:
        blockers.append(_source_blocker("missing_search_loop_audit_summary", "search_loop_audit_summary"))
    else:
        if not search_progression_safe:
            blockers.append(
                _source_blocker(
                    "search_loop_progression_not_closed",
                    "search_loop_audit_summary",
                    status=loop_status,
                    total_blocker_count=loop_total_blocker_count,
                )
            )
        if effective_round_count <= 0:
            blockers.append(_source_blocker("no_effective_search_rounds", "search_loop_audit_summary"))
        if candidate_progression_count <= 0:
            blockers.append(_source_blocker("no_candidate_progression", "search_loop_audit_summary"))
        if candidate_progression_parameter_hash_count <= 0:
            blockers.append(_source_blocker("no_candidate_parameter_hash_progression", "search_loop_audit_summary"))
        if request_to_execution_progression_count <= 0:
            blockers.append(_source_blocker("no_request_to_execution_progression", "search_loop_audit_summary"))
        if request_to_execution_progressed_candidate_parameter_hash_count <= 0:
            blockers.append(
                _source_blocker(
                    "no_request_to_execution_parameter_hash_progression",
                    "search_loop_audit_summary",
                )
            )

    step3_admission_safe = bool(
        campaign_admission_safe
        and materialization_coverage_closed
        and step2_iteration_request_count == materialization_request_count
        and authorized_queue_entry_count == materialization_request_count
        and materialization_request_count > 0
    )
    if campaign_admission_safe and materialization_coverage_closed and step2_iteration_request_count != materialization_request_count:
        blockers.append(
            _source_blocker(
                "campaign_request_count_materialization_count_mismatch",
                "campaign_search_admission_plan",
                step2_iteration_request_count=step2_iteration_request_count,
                materialization_request_count=materialization_request_count,
            )
        )

    effectiveness_gate_passed = bool(
        coverage_effective
        and coverage_count_proof_closed
        and campaign_admission_safe
        and materialization_coverage_closed
        and search_progression_safe
        and candidate_progression_effective
        and candidate_parameter_progression_effective
        and request_to_execution_progression_effective
        and step3_admission_safe
        and not blockers
    )
    release_package_recommendation_eligibility_audit = _release_package_recommendation_eligibility_audit(
        release_package_target_evidence_linkage_audit,
        effectiveness_gate_passed=effectiveness_gate_passed,
    )
    return {
        "schema_version": CONTRACT_VERSION,
        "contract_version": CONTRACT_VERSION,
        "status": "closed_for_search_effectiveness" if effectiveness_gate_passed else "partial_blocked_not_complete",
        "run_dir": str(run_dir),
        "architecture_search_coverage_ref": coverage_ref,
        "campaign_search_admission_plan_ref": admission_ref,
        "campaign_materialization_summary_ref": materialization_ref,
        "materialization_coverage_audit_ref": materialization_coverage_audit_ref,
        "search_loop_audit_summary_ref": loop_ref,
        "architecture_search_coverage_summary": coverage,
        "coverage_effective": coverage_effective,
        "architecture_search_coverage_count_proof_present": coverage_count_proof_present,
        "architecture_search_coverage_count_proof_closed": coverage_count_proof_closed,
        "architecture_search_coverage_count_requirements": coverage_count_requirements,
        "architecture_search_coverage_count_values": coverage_count_values,
        "campaign_admission_safe": campaign_admission_safe,
        "materialization_coverage_closed": materialization_coverage_closed,
        "materialization_coverage_audit_closed": materialization_coverage_audit_closed,
        "release_package_target_evidence_linkage": release_package_target_evidence_linkage_audit.get("linkage", {}),
        "release_package_target_evidence_linkage_status": release_package_target_evidence_linkage_audit.get("status"),
        "release_package_target_evidence_linkage_closed": bool(
            release_package_target_evidence_linkage_audit.get("closed")
        ),
        "release_package_target_evidence_linkage_hash": release_package_target_evidence_linkage_audit.get("linkage_hash"),
        "release_package_target_evidence_source_matrix_gate_id_count": int(
            release_package_target_evidence_linkage_audit.get("source_matrix_evidence_gate_id_count", 0) or 0
        ),
        "release_package_target_evidence_linkage_blocker_count": int(
            release_package_target_evidence_linkage_audit.get("blocker_count", 0) or 0
        ),
        "release_package_recommendation_eligibility_audit": release_package_recommendation_eligibility_audit,
        "release_package_recommendation_input_provenance_eligible": bool(
            release_package_recommendation_eligibility_audit.get("recommendation_input_provenance_eligible")
            is True
        ),
        "search_progression_safe": search_progression_safe,
        "candidate_progression_effective": candidate_progression_effective,
        "candidate_parameter_progression_effective": candidate_parameter_progression_effective,
        "request_to_execution_progression_effective": request_to_execution_progression_effective,
        "step3_admission_safe": step3_admission_safe,
        "search_effective": effectiveness_gate_passed,
        "effectiveness_gate_passed": effectiveness_gate_passed,
        "search_loop_present": search_loop_present,
        "effective_round_count": effective_round_count,
        "candidate_progression_count": candidate_progression_count,
        "candidate_progression_parameter_hash_count": candidate_progression_parameter_hash_count,
        "candidate_progression_parameter_hashes": candidate_progression_parameter_hashes,
        "new_candidate_execution_count": int(loop.get("new_candidate_execution_count", 0) or 0) if loop else 0,
        "new_executed_candidate_parameter_hash_count": len(new_executed_candidate_parameter_hashes),
        "new_executed_candidate_parameter_hashes": new_executed_candidate_parameter_hashes,
        "new_candidate_discovery_count": int(loop.get("new_candidate_discovery_count", 0) or 0) if loop else 0,
        "new_campaign_request_candidate_parameter_hash_count": len(new_campaign_request_candidate_parameter_hashes),
        "new_campaign_request_candidate_parameter_hashes": new_campaign_request_candidate_parameter_hashes,
        "request_to_execution_progression_count": request_to_execution_progression_count,
        "request_to_execution_progressed_candidate_parameter_hash_count": (
            request_to_execution_progressed_candidate_parameter_hash_count
        ),
        "request_to_execution_progressed_candidate_parameter_hashes": (
            request_to_execution_progressed_candidate_parameter_hashes
        ),
        "step2_iteration_request_count": step2_iteration_request_count,
        "materialization_request_count": materialization_request_count,
        "authorized_step3_queue_entry_count": authorized_queue_entry_count,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "execution_allowed": False,
        "hidden_evidence_fanout_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Search effectiveness audits unify Step2 search breadth, Campaign admission, "
            "materialization coverage, release-package target-evidence linkage, and "
            "search-loop progression as control-plane checks only. They do not execute "
            "Step3 evidence, prove convergence, select a winner, or establish release "
            "completion."
        ),
    }


def build_search_loop_audit_summary(run_dirs: Sequence[Path]) -> Dict[str, Any]:
    """Build a machine-readable summary over existing search loop audits."""

    entries = [_entry_for_run(Path(run_dir).resolve()) for run_dir in run_dirs]
    missing_closure_count = sum(1 for entry in entries if not entry["closure_audit_present"])
    missing_replay_count = sum(1 for entry in entries if not entry["replay_safety_audit_present"])
    per_run_blocker_count = sum(
        int(entry["closure_blocker_count"]) + int(entry["replay_safety_blocker_count"])
        for entry in entries
    )
    cross_run = _cross_run_replay_audit(entries)
    total_blocker_count = per_run_blocker_count + int(cross_run["cross_run_blocker_count"])
    closure_closed_count = sum(1 for entry in entries if entry["closure_status"] == "closed_for_next_iteration")
    replay_closed_count = sum(1 for entry in entries if entry["replay_safety_status"] == "closed_for_next_iteration")
    all_closure_closed = bool(entries) and missing_closure_count == 0 and closure_closed_count == len(entries)
    all_replay_safe = bool(entries) and missing_replay_count == 0 and replay_closed_count == len(entries)
    all_global_checks_safe = all(
        not entry["closure_global_check_failures"]
        and not entry["replay_safety_global_check_failures"]
        for entry in entries
    )
    progression = _search_progression_audit(entries)
    entries = list(progression["entries"])
    total_blocker_count += int(progression["progression_blocker_count"])
    feedback_influence = _search_feedback_influence_audit(entries)
    total_blocker_count += int(feedback_influence["feedback_influence_blocker_count"])
    status = (
        "closed_for_next_iteration"
        if entries
        and all_closure_closed
        and all_replay_safe
        and all_global_checks_safe
        and cross_run["cross_run_replay_safe"]
        and progression["progression_safe"]
        and feedback_influence["all_feedback_influence_effective"]
        and total_blocker_count == 0
        else "partial_blocked_not_complete"
    )
    return {
        "schema_version": CONTRACT_VERSION,
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "run_count": len(entries),
        "closure_audit_count": len(entries) - missing_closure_count,
        "replay_safety_audit_count": len(entries) - missing_replay_count,
        "missing_closure_audit_count": missing_closure_count,
        "missing_replay_safety_audit_count": missing_replay_count,
        "closure_closed_count": closure_closed_count,
        "replay_safety_closed_count": replay_closed_count,
        "per_run_blocker_count": per_run_blocker_count,
        "total_blocker_count": total_blocker_count,
        "all_closure_closed": all_closure_closed,
        "all_replay_safe": all_replay_safe,
        "all_global_checks_safe": all_global_checks_safe,
        "cross_run_replay_safe": bool(cross_run["cross_run_replay_safe"]),
        "cross_run_blocker_count": int(cross_run["cross_run_blocker_count"]),
        "cross_run_blockers": list(cross_run["cross_run_blockers"]),
        "cross_run_duplicate_executed_candidate_count": int(cross_run["duplicate_executed_candidate_count"]),
        "cross_run_duplicate_executed_candidate_ids": list(cross_run["duplicate_executed_candidate_ids"]),
        "cross_run_duplicate_executed_candidate_parameter_hash_count": int(
            cross_run["duplicate_executed_candidate_parameter_hash_count"]
        ),
        "cross_run_duplicate_executed_candidate_parameter_hashes": list(
            cross_run["duplicate_executed_candidate_parameter_hashes"]
        ),
        "cross_run_re_requested_observed_candidate_count": int(cross_run["re_requested_observed_candidate_count"]),
        "cross_run_re_requested_observed_candidate_ids": list(cross_run["re_requested_observed_candidate_ids"]),
        "cross_run_re_requested_observed_candidate_parameter_hash_count": int(
            cross_run["re_requested_observed_candidate_parameter_hash_count"]
        ),
        "cross_run_re_requested_observed_candidate_parameter_hashes": list(
            cross_run["re_requested_observed_candidate_parameter_hashes"]
        ),
        "progression_safe": bool(progression["progression_safe"]),
        "progression_blocker_count": int(progression["progression_blocker_count"]),
        "progression_blockers": list(progression["progression_blockers"]),
        "effective_round_count": int(progression["effective_round_count"]),
        "new_candidate_execution_count": int(progression["new_candidate_execution_count"]),
        "new_executed_candidate_ids": list(progression["new_executed_candidate_ids"]),
        "new_executed_candidate_parameter_hash_count": int(
            progression["new_executed_candidate_parameter_hash_count"]
        ),
        "new_executed_candidate_parameter_hashes": list(progression["new_executed_candidate_parameter_hashes"]),
        "new_candidate_discovery_count": int(progression["new_candidate_discovery_count"]),
        "new_campaign_request_candidate_ids": list(progression["new_campaign_request_candidate_ids"]),
        "new_campaign_request_candidate_parameter_hash_count": int(
            progression["new_campaign_request_candidate_parameter_hash_count"]
        ),
        "new_campaign_request_candidate_parameter_hashes": list(
            progression["new_campaign_request_candidate_parameter_hashes"]
        ),
        "request_to_execution_progression_count": int(progression["request_to_execution_progression_count"]),
        "request_to_execution_progressed_candidate_ids": list(progression["request_to_execution_progressed_candidate_ids"]),
        "request_to_execution_progressed_candidate_parameter_hash_count": int(
            progression["request_to_execution_progressed_candidate_parameter_hash_count"]
        ),
        "request_to_execution_progressed_candidate_parameter_hashes": list(
            progression["request_to_execution_progressed_candidate_parameter_hashes"]
        ),
        "candidate_progression_count": int(progression["candidate_progression_count"]),
        "candidate_progression_ids": list(progression["candidate_progression_ids"]),
        "candidate_progression_parameter_hash_count": int(progression["candidate_progression_parameter_hash_count"]),
        "candidate_progression_parameter_hashes": list(progression["candidate_progression_parameter_hashes"]),
        "feedback_influence_audit_count": int(feedback_influence["feedback_influence_audit_count"]),
        "missing_feedback_influence_audit_count": int(feedback_influence["missing_feedback_influence_audit_count"]),
        "feedback_influenced_round_count": int(feedback_influence["feedback_influenced_round_count"]),
        "feedback_influence_safe": bool(feedback_influence["feedback_influence_safe"]),
        "all_feedback_influence_effective": bool(feedback_influence["all_feedback_influence_effective"]),
        "feedback_influence_blocker_count": int(feedback_influence["feedback_influence_blocker_count"]),
        "feedback_influence_blockers": list(feedback_influence["feedback_influence_blockers"]),
        "execution_allowed": False,
        "hidden_evidence_fanout_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "entries": entries,
        "claim_boundary": (
            "Search loop audit summaries validate existing control-plane closure "
            "and replay-safety artifacts only. They cannot execute Step3, prove "
            "convergence, select a final winner, or establish release completion."
        ),
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        action="append",
        type=Path,
        default=[],
        help="Run/sweep directory containing search feedback/replay audit artifacts. Repeatable.",
    )
    parser.add_argument(
        "--discover-under",
        action="append",
        type=Path,
        default=[],
        help="Directory tree to scan for search feedback/replay audit artifacts.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=5,
        help="Maximum directory depth for --discover-under scans; default keeps large run trees bounded.",
    )
    parser.add_argument(
        "--max-dirs",
        type=int,
        default=50_000,
        help="Maximum directories visited per --discover-under root before stopping discovery.",
    )
    parser.add_argument("--out", type=Path, default=None, help="Optional output JSON path.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when the summary is not closed_for_next_iteration.",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    run_dirs = [path.resolve() for path in args.run_dir]
    run_dirs.extend(
        _discover_run_dirs(
            args.discover_under,
            max_depth=max(0, int(args.max_depth)),
            max_dirs=max(1, int(args.max_dirs)),
        )
    )
    deduped: List[Path] = []
    seen: set[Path] = set()
    for run_dir in run_dirs:
        if run_dir not in seen:
            seen.add(run_dir)
            deduped.append(run_dir)
    summary = build_search_loop_audit_summary(deduped)
    _validate_registered_schema(summary, "dse.contract.search_loop_audit_summary.v1")
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.strict and summary["status"] != "closed_for_next_iteration":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
