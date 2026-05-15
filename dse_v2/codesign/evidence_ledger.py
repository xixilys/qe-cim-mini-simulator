#!/usr/bin/env python3
"""Per-candidate evidence ledger utilities for finite co-design releases.

The ledger deliberately separates *row closure* from *claim eligibility*:
a row is closed when every required evidence category has an explicit
status/path/hash record that validates.  A closed row can still be blocked for
deliverable-complete claims when a category status is diagnostic-only,
unsupported, or blocked_temporary.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence


LEDGER_SCHEMA = "dse.codesign.per_candidate_evidence_ledger.v1"
LEDGER_VALIDATION_SCHEMA = "dse.codesign.per_candidate_evidence_ledger_validation.v1"

EVIDENCE_STATUSES = {
    "passed",
    "blocked_temporary",
    "unsupported",
    "failed",
    "not_applicable",
}

CLAIM_STATUS_POLICY = (
    "vertical_slice",
    "partial_mvp",
    "pilot_only",
    "blocked_temporary",
    "unsupported",
    "not_attempted",
    "deliverable_complete",
)

REQUIRED_ROW_FIELDS = (
    "candidate_id",
    "assignments",
    "legality",
    "systemc_status",
    "gem5_status",
    "eda_status",
    "formal_status",
    "numerical_status",
    "runtime_compiler_status",
    "feedback_status",
    "blocker_status",
    "claim_eligibility",
    "provenance",
    "release_domain_hashes",
)

REQUIRED_EVIDENCE_REFS = (
    "systemc_status",
    "gem5_status",
    "eda_status",
    "formal_status",
    "numerical_status",
    "runtime_compiler_status",
    "feedback_status",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def artifact_ref(path: Path, *, base_dir: Path, status: str, evidence_class: str) -> Dict[str, Any]:
    if status not in EVIDENCE_STATUSES:
        raise ValueError(f"invalid evidence status: {status}")
    return {
        "status": status,
        "path": str(path.relative_to(base_dir)),
        "hash": sha256_file(path),
        "hash_algorithm": "sha256",
        "evidence_class": evidence_class,
    }


def validate_candidate_evidence_ledger(
    ledger: Mapping[str, Any] | Path,
    *,
    base_dir: Path | None = None,
    expected_legal_candidate_ids: Iterable[str] | None = None,
) -> Dict[str, Any]:
    """Validate row closure and artifact hash integrity for a candidate ledger."""
    if isinstance(ledger, Path):
        ledger_path = ledger
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        root = base_dir or ledger_path.parent
    else:
        payload = dict(ledger)
        root = base_dir or Path(".")

    errors: list[Dict[str, Any]] = []
    warnings: list[Dict[str, Any]] = []
    rows = payload.get("rows", [])
    if payload.get("schema_version") != LEDGER_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected ledger schema"})
    if not isinstance(rows, list) or not rows:
        errors.append({"field": "rows", "message": "ledger rows are required"})
        rows = []

    expected = set(str(item) for item in expected_legal_candidate_ids or payload.get("legal_candidate_ids", []) or [])
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append({"field": f"rows[{index}]", "message": "row must be an object"})
            continue
        candidate_id = str(row.get("candidate_id", ""))
        if not candidate_id:
            errors.append({"field": f"rows[{index}].candidate_id", "message": "candidate_id is required"})
        if candidate_id in seen:
            errors.append({"field": f"rows[{index}].candidate_id", "message": "duplicate candidate_id", "candidate_id": candidate_id})
        seen.add(candidate_id)

        for field in REQUIRED_ROW_FIELDS:
            if field not in row:
                errors.append({"field": f"rows[{index}].{field}", "message": "required field missing", "candidate_id": candidate_id})

        for field in REQUIRED_EVIDENCE_REFS:
            ref = row.get(field, {})
            if not isinstance(ref, Mapping):
                errors.append({"field": f"rows[{index}].{field}", "message": "evidence ref must be an object", "candidate_id": candidate_id})
                continue
            status = str(ref.get("status", ""))
            if status not in EVIDENCE_STATUSES:
                errors.append({"field": f"rows[{index}].{field}.status", "message": "invalid or missing status", "candidate_id": candidate_id, "status": status})
            rel_path = str(ref.get("path", ""))
            expected_hash = str(ref.get("hash", ""))
            if not rel_path:
                errors.append({"field": f"rows[{index}].{field}.path", "message": "path is required", "candidate_id": candidate_id})
                continue
            evidence_path = root / rel_path
            if not evidence_path.exists():
                errors.append({"field": f"rows[{index}].{field}.path", "message": "evidence artifact missing", "candidate_id": candidate_id, "path": rel_path})
                continue
            actual_hash = sha256_file(evidence_path)
            if not expected_hash:
                errors.append({"field": f"rows[{index}].{field}.hash", "message": "hash is required", "candidate_id": candidate_id, "path": rel_path})
            elif actual_hash != expected_hash:
                errors.append({
                    "field": f"rows[{index}].{field}.hash",
                    "message": "artifact hash mismatch",
                    "candidate_id": candidate_id,
                    "path": rel_path,
                    "expected": expected_hash,
                    "actual": actual_hash,
                })

        claim = row.get("claim_eligibility", {})
        if isinstance(claim, Mapping) and claim.get("deliverable_complete") is True:
            not_passed = [
                field
                for field in REQUIRED_EVIDENCE_REFS
                if isinstance(row.get(field), Mapping) and row[field].get("status") != "passed"
            ]
            if not_passed:
                errors.append({
                    "field": f"rows[{index}].claim_eligibility.deliverable_complete",
                    "message": "deliverable_complete cannot be true while evidence categories are blocked",
                    "candidate_id": candidate_id,
                    "blocked_fields": not_passed,
                })
        blockers = row.get("blocker_status", {})
        if isinstance(blockers, Mapping) and blockers.get("status") in {"none", "passed"}:
            not_passed = [
                field
                for field in REQUIRED_EVIDENCE_REFS
                if isinstance(row.get(field), Mapping) and row[field].get("status") != "passed"
            ]
            if not_passed:
                warnings.append({
                    "field": f"rows[{index}].blocker_status",
                    "message": "row has blocked evidence but blocker_status is clear",
                    "candidate_id": candidate_id,
                    "blocked_fields": not_passed,
                })

    if expected and seen != expected:
        errors.append({
            "field": "rows",
            "message": "ledger rows do not match expected legal candidate ids",
            "missing_candidate_ids": sorted(expected - seen),
            "extra_candidate_ids": sorted(seen - expected),
        })

    return {
        "schema_version": LEDGER_VALIDATION_SCHEMA,
        "valid": not errors,
        "row_count": len(rows),
        "expected_legal_candidate_count": len(expected) if expected else payload.get("legal_candidate_count"),
        "all_expected_candidates_present": not expected or seen == expected,
        "errors": errors,
        "warnings": warnings,
        "claim_boundary": (
            "Ledger validation proves row/status/path/hash closure. It does not "
            "upgrade blocked_temporary or unsupported evidence into deliverable_complete claims."
        ),
    }
