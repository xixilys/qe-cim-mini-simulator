#!/usr/bin/env python3
"""Generic finite-domain freeze and Cartesian candidate-universe utilities."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Mapping, Sequence


RELEASE_DOMAIN_SCHEMA = "dse.codesign.release_domain_freeze.v1"
CANDIDATE_UNIVERSE_SCHEMA = "dse.codesign.candidate_universe_manifest.v1"
CANDIDATE_LEGALITY_SCHEMA = "dse.codesign.candidate_legality_report.v1"

LegalityFn = Callable[[Mapping[str, str]], tuple[bool, Sequence[str]]]
ScoreFn = Callable[[Mapping[str, str]], Mapping[str, Any]]


def stable_json_hash(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AxisValue:
    """One finite value in a generic co-design axis."""

    value_id: str
    label: str
    description: str
    source_refs: tuple[str, ...]
    parameters: Dict[str, Any] = field(default_factory=dict)
    version: str = "v1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value_id": self.value_id,
            "label": self.label,
            "description": self.description,
            "source_refs": list(self.source_refs),
            "parameters": dict(self.parameters),
            "version": self.version,
        }


@dataclass(frozen=True)
class AxisDomain:
    """Finite, versioned axis domain."""

    axis_id: str
    label: str
    description: str
    values: tuple[AxisValue, ...]
    source_refs: tuple[str, ...]
    version: str = "v1"
    provenance: str = "repo_defined_release_domain"

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError(f"axis has no finite values: {self.axis_id}")
        value_ids = [value.value_id for value in self.values]
        if len(set(value_ids)) != len(value_ids):
            raise ValueError(f"axis has duplicate value ids: {self.axis_id}")
        if not self.source_refs:
            raise ValueError(f"axis has no source refs: {self.axis_id}")

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "axis_id": self.axis_id,
            "label": self.label,
            "description": self.description,
            "version": self.version,
            "provenance": self.provenance,
            "source_refs": list(self.source_refs),
            "finite": True,
            "value_count": len(self.values),
            "values": [value.to_dict() for value in self.values],
        }
        payload["axis_hash"] = stable_json_hash(payload)
        return payload


def build_domain_freeze(
    axes: Sequence[AxisDomain],
    *,
    release_id: str,
    source_ledger: Sequence[Mapping[str, Any]],
    claim_boundary: str,
) -> Dict[str, Any]:
    axis_ids = [axis.axis_id for axis in axes]
    if len(axis_ids) != len(set(axis_ids)):
        raise ValueError("duplicate axis ids in release domain")
    payload: Dict[str, Any] = {
        "schema_version": RELEASE_DOMAIN_SCHEMA,
        "release_id": release_id,
        "axis_count": len(axes),
        "axes": [axis.to_dict() for axis in axes],
        "source_ledger": [dict(item) for item in source_ledger],
        "claim_boundary": claim_boundary,
        "finite": True,
        "version": "v1",
    }
    payload["domain_hash"] = stable_json_hash({
        key: value for key, value in payload.items() if key != "domain_hash"
    })
    return payload


def _candidate_id(assignments: Mapping[str, str], *, prefix: str = "cand_") -> str:
    return prefix + stable_json_hash({"assignments": dict(sorted(assignments.items()))})[:16]


def build_candidate_universe(
    domain_freeze: Mapping[str, Any],
    *,
    legality_fn: LegalityFn | None = None,
    score_fn: ScoreFn | None = None,
    identity_axis_ids: Sequence[str] | None = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    axes = list(domain_freeze.get("axes", []) or [])
    axis_values: list[tuple[str, list[str]]] = []
    for axis in axes:
        values = [str(value["value_id"]) for value in axis.get("values", []) or []]
        if not values:
            raise ValueError(f"axis has no values in freeze: {axis.get('axis_id')}")
        axis_values.append((str(axis["axis_id"]), values))

    all_axis_ids = [axis_id for axis_id, _ in axis_values]
    identity_axis_id_list = list(identity_axis_ids) if identity_axis_ids is not None else list(all_axis_ids)
    unknown_identity_axes = [axis_id for axis_id in identity_axis_id_list if axis_id not in all_axis_ids]
    if unknown_identity_axes:
        raise ValueError(f"identity_axis_ids contains unknown axes: {unknown_identity_axes}")
    non_identity_axis_ids = [axis_id for axis_id in all_axis_ids if axis_id not in identity_axis_id_list]
    evidence_policy_affects_identity = not non_identity_axis_ids

    candidates: list[Dict[str, Any]] = []
    legality_rows: list[Dict[str, Any]] = []
    for combination in itertools.product(*[values for _, values in axis_values]):
        assignments = dict(zip(all_axis_ids, combination))
        identity_assignments = {axis_id: assignments[axis_id] for axis_id in identity_axis_id_list}
        non_identity_assignments = {axis_id: assignments[axis_id] for axis_id in non_identity_axis_ids}
        legal, reasons = legality_fn(assignments) if legality_fn else (True, [])
        score = dict(score_fn(assignments)) if score_fn else {}
        candidate_id = _candidate_id(assignments)
        design_candidate_id = _candidate_id(identity_assignments, prefix="design_cand_")
        provenance = {
            "source": "frozen_release_domain_cartesian_product",
            "release_id": domain_freeze.get("release_id"),
            "domain_hash": domain_freeze.get("domain_hash"),
            "axis_ids": all_axis_ids,
            "assignment_order": all_axis_ids,
            "candidate_id_rule": "cand_ + sha256(sorted all-axis assignment key/value pairs)[:16]",
            "candidate_id_kind": "evaluation_record_id" if non_identity_axis_ids else "design_candidate_id",
            "design_candidate_id_rule": "design_cand_ + sha256(sorted identity-axis assignment key/value pairs)[:16]",
            "identity_axis_ids": identity_axis_id_list,
            "non_identity_axis_ids": non_identity_axis_ids,
            "evidence_policy_affects_identity": evidence_policy_affects_identity,
        }
        candidate = {
            "candidate_id": candidate_id,
            "candidate_id_kind": provenance["candidate_id_kind"],
            "design_candidate_id": design_candidate_id,
            "assignments": assignments,
            "identity_assignments": identity_assignments,
            "non_identity_assignments": non_identity_assignments,
            "legal": bool(legal),
            "illegal_reasons": list(reasons),
            "screening": score,
            "domain_hash": domain_freeze.get("domain_hash"),
            "provenance": provenance,
        }
        candidates.append(candidate)
        legality_rows.append({
            "candidate_id": candidate["candidate_id"],
            "candidate_id_kind": candidate["candidate_id_kind"],
            "design_candidate_id": candidate["design_candidate_id"],
            "assignments": assignments,
            "identity_assignments": identity_assignments,
            "non_identity_assignments": non_identity_assignments,
            "legal": bool(legal),
            "reasons": list(reasons),
            "provenance": provenance,
        })

    legal_candidates = [candidate for candidate in candidates if candidate["legal"]]
    legal_design_candidate_ids = sorted({candidate["design_candidate_id"] for candidate in legal_candidates})
    manifest: Dict[str, Any] = {
        "schema_version": CANDIDATE_UNIVERSE_SCHEMA,
        "release_id": domain_freeze.get("release_id"),
        "domain_hash": domain_freeze.get("domain_hash"),
        "axis_ids": all_axis_ids,
        "axis_count": len(axis_values),
        "identity_axis_ids": identity_axis_id_list,
        "identity_axis_count": len(identity_axis_id_list),
        "non_identity_axis_ids": non_identity_axis_ids,
        "non_identity_axis_count": len(non_identity_axis_ids),
        "cartesian_count": len(candidates),
        "legal_candidate_count": len(legal_candidates),
        "illegal_candidate_count": len(candidates) - len(legal_candidates),
        "unique_design_candidate_count": len({candidate["design_candidate_id"] for candidate in candidates}),
        "legal_design_candidate_count": len(legal_design_candidate_ids),
        "candidates": candidates,
        "legal_candidate_ids": [candidate["candidate_id"] for candidate in legal_candidates],
        "legal_design_candidate_ids": legal_design_candidate_ids,
        "candidate_id_provenance": {
            "source": "frozen_release_domain_cartesian_product",
            "candidate_id_rule": "cand_ + sha256(sorted all-axis assignment key/value pairs)[:16]",
            "candidate_id_kind": "evaluation_record_id" if non_identity_axis_ids else "design_candidate_id",
            "design_candidate_id_rule": "design_cand_ + sha256(sorted identity-axis assignment key/value pairs)[:16]",
            "assignment_order": all_axis_ids,
            "identity_axis_ids": identity_axis_id_list,
            "non_identity_axis_ids": non_identity_axis_ids,
            "evidence_policy_affects_identity": evidence_policy_affects_identity,
            "domain_hash": domain_freeze.get("domain_hash"),
        },
        "claim_boundary": "candidate universe over frozen finite domain; evidence closure tracked separately",
    }
    manifest["universe_hash"] = stable_json_hash({
        key: value for key, value in manifest.items() if key != "universe_hash"
    })
    legality_report: Dict[str, Any] = {
        "schema_version": CANDIDATE_LEGALITY_SCHEMA,
        "release_id": domain_freeze.get("release_id"),
        "domain_hash": domain_freeze.get("domain_hash"),
        "universe_hash": manifest["universe_hash"],
        "status": "passed" if legal_candidates else "failed",
        "rows": legality_rows,
        "summary": {
            "cartesian_count": len(candidates),
            "legal_candidate_count": len(legal_candidates),
            "illegal_candidate_count": len(candidates) - len(legal_candidates),
            "unique_design_candidate_count": manifest["unique_design_candidate_count"],
            "legal_design_candidate_count": manifest["legal_design_candidate_count"],
            "all_candidates_classified": len(legality_rows) == len(candidates),
        },
    }
    legality_report["legality_hash"] = stable_json_hash({
        key: value for key, value in legality_report.items() if key != "legality_hash"
    })
    return manifest, legality_report


def axis_value_ids(domain_freeze: Mapping[str, Any]) -> Dict[str, list[str]]:
    return {
        str(axis.get("axis_id")): [str(value.get("value_id")) for value in axis.get("values", []) or []]
        for axis in domain_freeze.get("axes", []) or []
    }
