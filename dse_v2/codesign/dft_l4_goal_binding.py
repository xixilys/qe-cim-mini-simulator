#!/usr/bin/env python3
"""Fail-closed L4/gem5 binding artifact for the DFT hardware DSE goal.

The existing complete-DSE L4 matrix proves software-visible GenericAccel/gem5
behavior for its own candidate/workload matrix.  The DFT hardware closure lane
uses a different candidate/kernel matrix, so this module makes that relationship
explicit instead of silently treating historical L4 evidence as current
candidate-specific proof.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.dft_scf_workstreams import STRICT_DFT_QE_WORKLOAD_CLASSES


DFT_L4_GOAL_BINDING_SCHEMA = "dse.dft.l4_goal_binding.v1"
DFT_L4_GOAL_BINDING_VALIDATION_SCHEMA = "dse.dft.l4_goal_binding_validation.v1"
DFT_L4_GOAL_BINDING_STATUS_SCHEMA = "dse.dft.l4_goal_binding_status.v1"

L4_MATRIX_SCHEMA = "dse.codesign.l4_evidence_matrix.v1"
L4_REPORT_SCHEMA = "dse.codesign.complete_dse_full_l4_report.v1"

DEFAULT_CANDIDATE_MAPPING_POLICY = "separate_l4_matrix_no_wave36_candidate_equivalence"
DEFAULT_WORKLOAD_MAPPING_POLICY = "legacy_qe_mainflow_not_six_scf"

REQUIRED_CURRENT_GOAL_WORKLOAD_IDS = tuple(STRICT_DFT_QE_WORKLOAD_CLASSES)
VALID_CANDIDATE_EQUIVALENCE_SCOPES = {
    "same_identity_regenerated_l4",
    "explicit_current_goal_l4_candidate",
}
VALID_WORKLOAD_EQUIVALENCE_SCOPES = {
    "same_strict_scf_workload",
    "explicit_current_goal_l4_workload",
}

CLAIM_BOUNDARY = (
    "DFT L4 goal binding cites software-visible gem5/GenericAccel evidence for "
    "audit visibility only. It is not FPGA/ASIC PPA evidence, not a substitute "
    "for per-kernel hard gates, and not final DFT full-SCF closure unless "
    "candidate and workload identity mappings are explicit and validated."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _artifact_ref(path: Path) -> Dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else None,
        "sha256": _sha256(path),
    }


def _candidate_ids_from_step5(step5_run: Path | None) -> list[str]:
    if step5_run is None:
        return []
    release_gate = _as_mapping(_load_json(step5_run / "dft_hardware_closure_release_gate.json"))
    rows = _as_list(release_gate.get("candidate_rows"))
    ids = [
        str(row.get("candidate_id"))
        for row in rows
        if isinstance(row, Mapping) and row.get("candidate_id")
    ]
    if ids:
        return sorted(dict.fromkeys(ids))
    packet_index = _as_mapping(_load_json(step5_run / "dft_hardware_closure_packet_index.json"))
    units = _as_list(packet_index.get("units"))
    return sorted(dict.fromkeys(
        str(unit.get("candidate_id"))
        for unit in units
        if isinstance(unit, Mapping) and unit.get("candidate_id")
    ))


def _load_crosswalk(path: Path | None) -> Mapping[str, Any]:
    payload = _load_json(path) if path else {}
    return payload if isinstance(payload, Mapping) else {}


def _crosswalk_entries(crosswalk: Mapping[str, Any], primary_key: str) -> Mapping[str, Any]:
    pairs = crosswalk.get(primary_key, crosswalk.get("mappings", crosswalk))
    return pairs if isinstance(pairs, Mapping) else {}


def _equivalence_scope(entry: Mapping[str, Any]) -> str:
    return str(entry.get("equivalence_scope") or entry.get("identity_equivalence") or "").strip()


def _confidence_one(entry: Mapping[str, Any]) -> bool:
    try:
        return float(entry.get("confidence", 0.0)) >= 1.0
    except (TypeError, ValueError):
        return False


def _normalize_candidate_crosswalk(crosswalk: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize and validate a current-goal candidate -> L4 candidate crosswalk.

    Simple ``{"cand": "cdse"}`` maps are visible for diagnostics but do not
    count as identity proof.  Final binding requires structured entries with an
    explicit equivalence scope so a historical L4 matrix cannot be silently
    reused for unrelated DFT candidates.
    """

    raw_pairs = _crosswalk_entries(crosswalk, "candidate_crosswalk")
    pairs: dict[str, str] = {}
    valid_structured: dict[str, str] = {}
    invalid_entries: list[Dict[str, Any]] = []
    for source_id, raw_entry in raw_pairs.items():
        source = str(source_id)
        if isinstance(raw_entry, str):
            pairs[source] = raw_entry
            invalid_entries.append({
                "source_id": source,
                "reason": "candidate_crosswalk_entry_must_be_structured",
            })
            continue
        if not isinstance(raw_entry, Mapping):
            invalid_entries.append({"source_id": source, "reason": "candidate_crosswalk_entry_not_object"})
            continue
        target = str(
            raw_entry.get("l4_candidate_id")
            or raw_entry.get("cdse_candidate_id")
            or raw_entry.get("target_candidate_id")
            or ""
        ).strip()
        if target:
            pairs[source] = target
        scope = _equivalence_scope(raw_entry)
        if not target:
            invalid_entries.append({"source_id": source, "reason": "missing_l4_candidate_id"})
        elif scope not in VALID_CANDIDATE_EQUIVALENCE_SCOPES:
            invalid_entries.append({
                "source_id": source,
                "target_id": target,
                "reason": "unsupported_candidate_equivalence_scope",
                "equivalence_scope": scope or None,
            })
        elif not _confidence_one(raw_entry):
            invalid_entries.append({
                "source_id": source,
                "target_id": target,
                "reason": "candidate_crosswalk_confidence_below_one",
                "confidence": raw_entry.get("confidence"),
            })
        else:
            valid_structured[source] = target
    return {
        "pairs": pairs,
        "valid_structured_pairs": valid_structured,
        "invalid_entries": invalid_entries,
    }


def _normalize_workload_crosswalk(crosswalk: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize and validate a strict-SCF workload -> L4 workload crosswalk."""

    raw_pairs = _crosswalk_entries(crosswalk, "workload_crosswalk")
    pairs: dict[str, list[str]] = {}
    valid_structured: dict[str, list[str]] = {}
    invalid_entries: list[Dict[str, Any]] = []
    for source_id, raw_entry in raw_pairs.items():
        source = str(source_id)
        targets: list[str] = []
        if isinstance(raw_entry, str):
            targets = [raw_entry]
            invalid_entries.append({
                "source_id": source,
                "reason": "workload_crosswalk_entry_must_be_structured",
            })
        elif isinstance(raw_entry, list):
            targets = [str(item) for item in raw_entry if item]
            invalid_entries.append({
                "source_id": source,
                "reason": "workload_crosswalk_entry_must_be_structured",
            })
        elif isinstance(raw_entry, Mapping):
            raw_targets = (
                raw_entry.get("l4_workload_case_ids")
                or raw_entry.get("target_workload_case_ids")
                or raw_entry.get("l4_workload_case_id")
                or raw_entry.get("target_workload_case_id")
            )
            if isinstance(raw_targets, list):
                targets = [str(item) for item in raw_targets if item]
            elif raw_targets:
                targets = [str(raw_targets)]
            scope = _equivalence_scope(raw_entry)
            if not targets:
                invalid_entries.append({"source_id": source, "reason": "missing_l4_workload_case_ids"})
            elif scope not in VALID_WORKLOAD_EQUIVALENCE_SCOPES:
                invalid_entries.append({
                    "source_id": source,
                    "target_ids": targets,
                    "reason": "unsupported_workload_equivalence_scope",
                    "equivalence_scope": scope or None,
                })
            elif not _confidence_one(raw_entry):
                invalid_entries.append({
                    "source_id": source,
                    "target_ids": targets,
                    "reason": "workload_crosswalk_confidence_below_one",
                    "confidence": raw_entry.get("confidence"),
                })
            else:
                valid_structured[source] = targets
        else:
            invalid_entries.append({"source_id": source, "reason": "workload_crosswalk_entry_not_object"})
        if targets:
            pairs[source] = targets
    return {
        "pairs": pairs,
        "valid_structured_pairs": valid_structured,
        "invalid_entries": invalid_entries,
    }


def _row_proof_paths(l4_root: Path, rows: Sequence[Any]) -> list[str]:
    paths: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        candidate_id = row.get("candidate_id")
        workload_case_id = row.get("workload_case_id")
        if not candidate_id or not workload_case_id:
            continue
        proof = l4_root / "rows" / str(candidate_id) / str(workload_case_id) / "l4_gem5" / "gem5_l4_proof.json"
        if proof.exists():
            paths.append(str(proof))
    return sorted(paths)


def _row_proof_pass_status(paths: Sequence[str]) -> Dict[str, Any]:
    passed: list[str] = []
    failed: list[Dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        payload = _as_mapping(_load_json(path))
        if payload.get("passed") is True:
            passed.append(str(path))
        else:
            failed.append({
                "path": str(path),
                "proof_status": payload.get("proof_status"),
                "missing_evidence": _as_list(payload.get("missing_evidence"))[:8],
            })
    return {
        "passed_paths": passed,
        "failed": failed,
        "passed_count": len(passed),
        "failed_count": len(failed),
    }


def build_dft_l4_goal_binding(
    *,
    l4_root: Path,
    step5_run: Path | None = None,
    candidate_crosswalk: Path | None = None,
    workload_crosswalk: Path | None = None,
    candidate_mapping_policy: str = DEFAULT_CANDIDATE_MAPPING_POLICY,
    workload_mapping_policy: str = DEFAULT_WORKLOAD_MAPPING_POLICY,
) -> Dict[str, Any]:
    """Build a fail-closed L4 binding payload.

    ``current_goal_l4_bound`` is intentionally stricter than
    ``l4_software_visible_proof_present``.  The latter says the cited L4 matrix
    is real and complete for its own scope; the former also requires explicit
    current-goal candidate/workload identity crosswalks.
    """

    l4_root = Path(l4_root)
    step5_run = Path(step5_run) if step5_run else None
    matrix_path = l4_root / "l4_evidence_matrix.json"
    report_path = l4_root / "complete_dse_full_l4_evidence_report.json"
    evidence_rows_path = l4_root / "evidence_rows.json"
    gem5_preflight_path = l4_root / "gem5_preflight.json"

    matrix = _as_mapping(_load_json(matrix_path))
    report = _as_mapping(_load_json(report_path))
    evidence_rows_payload = _as_mapping(_load_json(evidence_rows_path))
    gem5_preflight = _as_mapping(_load_json(gem5_preflight_path))
    rows = _as_list(matrix.get("rows"))

    l4_candidate_ids = [str(item) for item in _as_list(matrix.get("legal_candidate_ids"))]
    l4_workload_case_ids = [str(item) for item in _as_list(matrix.get("workload_case_ids"))]
    step5_candidate_ids = _candidate_ids_from_step5(step5_run)

    candidate_crosswalk_payload = _load_crosswalk(candidate_crosswalk)
    workload_crosswalk_payload = _load_crosswalk(workload_crosswalk)
    candidate_crosswalk_normalized = _normalize_candidate_crosswalk(candidate_crosswalk_payload)
    workload_crosswalk_normalized = _normalize_workload_crosswalk(workload_crosswalk_payload)
    candidate_pairs = _as_mapping(candidate_crosswalk_normalized.get("pairs"))
    candidate_structured_pairs = _as_mapping(candidate_crosswalk_normalized.get("valid_structured_pairs"))
    workload_pairs = _as_mapping(workload_crosswalk_normalized.get("pairs"))
    workload_structured_pairs = _as_mapping(workload_crosswalk_normalized.get("valid_structured_pairs"))
    mapped_step5_candidates = sorted(str(item) for item in candidate_pairs.keys())
    mapped_l4_candidates = sorted(str(item) for item in candidate_pairs.values())
    mapped_goal_workloads = sorted(str(item) for item in workload_pairs.keys())
    mapped_l4_workloads = sorted(
        dict.fromkeys(
            str(item)
            for values in workload_pairs.values()
            for item in (values if isinstance(values, list) else [values])
        )
    )

    row_proofs = _row_proof_paths(l4_root, rows)
    matrix_row_count = int(matrix.get("row_count", len(rows)) or 0)
    expected_row_count = int(matrix.get("expected_row_count", 0) or 0)
    blocked_row_count = int(matrix.get("blocked_row_count", 0) or 0)
    report_status = str(report.get("status", ""))
    preflight_blockers = _as_list(gem5_preflight.get("blockers"))

    l4_matrix_shape_complete = (
        matrix.get("schema_version") == L4_MATRIX_SCHEMA
        and matrix_row_count > 0
        and expected_row_count == matrix_row_count
    )
    l4_matrix_deliverable_complete = (
        l4_matrix_shape_complete
        and matrix.get("coverage_status") == "passed"
        and blocked_row_count == 0
        and matrix.get("deliverable_complete_eligible") is True
    )
    report_deliverable_complete = (
        report.get("schema_version") == L4_REPORT_SCHEMA
        and report_status == "deliverable_complete"
        and int(report.get("row_count", 0) or 0) == matrix_row_count
        and int(report.get("expected_row_count", 0) or 0) == matrix_row_count
    )
    row_proofs_complete = len(row_proofs) == matrix_row_count
    row_proof_status = _row_proof_pass_status(row_proofs)
    row_proofs_passed = (
        row_proofs_complete
        and row_proof_status["passed_count"] == matrix_row_count
        and row_proof_status["failed_count"] == 0
    )
    preflight_passed = gem5_preflight_path.exists() and not preflight_blockers
    l4_software_visible_proof_present = bool(
        l4_matrix_shape_complete and row_proofs_passed and preflight_passed
    )

    candidate_crosswalk_errors = _as_list(candidate_crosswalk_normalized.get("invalid_entries"))
    workload_crosswalk_errors = _as_list(workload_crosswalk_normalized.get("invalid_entries"))
    required_workload_ids = set(REQUIRED_CURRENT_GOAL_WORKLOAD_IDS)
    candidate_keys_exact = set(step5_candidate_ids) == set(candidate_structured_pairs.keys())
    mapped_l4_candidates_unique = len(set(mapped_l4_candidates)) == len(mapped_l4_candidates)
    candidate_identity_binding_explicit = (
        candidate_mapping_policy == "explicit_crosswalk"
        and bool(step5_candidate_ids)
        and candidate_keys_exact
        and mapped_l4_candidates_unique
        and set(mapped_l4_candidates).issubset(set(l4_candidate_ids))
        and not candidate_crosswalk_errors
    )
    workload_keys_exact = required_workload_ids == set(workload_structured_pairs.keys())
    workload_identity_binding_explicit = (
        workload_mapping_policy == "explicit_crosswalk"
        and workload_keys_exact
        and set(mapped_l4_workloads).issubset(set(l4_workload_case_ids))
        and not workload_crosswalk_errors
    )
    current_goal_l4_bound = bool(
        l4_software_visible_proof_present
        and candidate_identity_binding_explicit
        and workload_identity_binding_explicit
    )

    blockers: list[str] = []
    non_l4_deliverable_blockers: list[str] = []
    if not l4_matrix_shape_complete:
        blockers.append("l4_matrix_not_complete_for_its_scope")
    if not l4_matrix_deliverable_complete:
        non_l4_deliverable_blockers.append("l4_matrix_not_deliverable_complete_for_its_scope")
    if not report_deliverable_complete:
        non_l4_deliverable_blockers.append("l4_report_not_deliverable_complete_for_its_scope")
    if not row_proofs_complete:
        blockers.append("row_level_gem5_l4_proof_files_incomplete")
    if row_proofs_complete and not row_proofs_passed:
        blockers.append("row_level_gem5_l4_proofs_not_all_passed")
    if not preflight_passed:
        blockers.append("gem5_preflight_blocked_or_missing")
    if not candidate_identity_binding_explicit:
        blockers.append("candidate_identity_crosswalk_missing_or_incomplete")
    if not workload_identity_binding_explicit:
        blockers.append("workload_identity_crosswalk_missing_or_incomplete")

    status = (
        "passed_current_goal_l4_bound"
        if current_goal_l4_bound
        else "blocked_l4_visible_but_identity_or_workload_unbound"
        if l4_software_visible_proof_present
        else "blocked_missing_or_invalid_l4_evidence"
    )
    return {
        "schema_version": DFT_L4_GOAL_BINDING_SCHEMA,
        "generated_at": _now_iso(),
        "status": status,
        "l4_root": str(l4_root),
        "step5_run": str(step5_run) if step5_run else None,
        "artifacts": {
            "l4_evidence_matrix.json": _artifact_ref(matrix_path),
            "complete_dse_full_l4_evidence_report.json": _artifact_ref(report_path),
            "evidence_rows.json": _artifact_ref(evidence_rows_path),
            "gem5_preflight.json": _artifact_ref(gem5_preflight_path),
            "candidate_crosswalk": _artifact_ref(candidate_crosswalk) if candidate_crosswalk else None,
            "workload_crosswalk": _artifact_ref(workload_crosswalk) if workload_crosswalk else None,
        },
        "l4_matrix": {
            "schema_version": matrix.get("schema_version"),
            "coverage_status": matrix.get("coverage_status"),
            "row_count": matrix_row_count,
            "expected_row_count": expected_row_count,
            "blocked_row_count": blocked_row_count,
            "deliverable_complete_eligible": bool(matrix.get("deliverable_complete_eligible", False)),
            "matrix_hash": matrix.get("matrix_hash"),
            "candidate_count": len(l4_candidate_ids),
            "workload_case_count": len(l4_workload_case_ids),
            "candidate_ids": l4_candidate_ids,
            "workload_case_ids": l4_workload_case_ids,
        },
        "l4_report": {
            "schema_version": report.get("schema_version"),
            "status": report_status,
            "row_count": report.get("row_count"),
            "expected_row_count": report.get("expected_row_count"),
            "claims": report.get("claims"),
        },
        "gem5_preflight": {
            "present": gem5_preflight_path.exists(),
            "blockers": preflight_blockers,
            "gem5_binary_exists": gem5_preflight.get("gem5_binary_exists"),
            "driver_binary_exists": gem5_preflight.get("driver_binary_exists"),
            "gem5_config_exists": gem5_preflight.get("gem5_config_exists"),
        },
        "row_level_proofs": {
            "expected_gem5_l4_proof_count": matrix_row_count,
            "present_gem5_l4_proof_count": len(row_proofs),
            "passed_gem5_l4_proof_count": row_proof_status["passed_count"],
            "failed_gem5_l4_proof_count": row_proof_status["failed_count"],
            "failed_samples": row_proof_status["failed"][:8],
            "sample_paths": row_proofs[:8],
        },
        "current_goal_binding": {
            "candidate_mapping_policy": candidate_mapping_policy,
            "workload_mapping_policy": workload_mapping_policy,
            "step5_candidate_count": len(step5_candidate_ids),
            "step5_candidate_ids": step5_candidate_ids,
            "candidate_crosswalk_count": len(candidate_pairs),
            "candidate_structured_crosswalk_count": len(candidate_structured_pairs),
            "candidate_identity_binding_explicit": candidate_identity_binding_explicit,
            "candidate_keys_exact": candidate_keys_exact,
            "mapped_l4_candidates_unique": mapped_l4_candidates_unique,
            "candidate_crosswalk_errors": candidate_crosswalk_errors,
            "required_goal_workload_ids": list(REQUIRED_CURRENT_GOAL_WORKLOAD_IDS),
            "workload_crosswalk_count": len(workload_pairs),
            "workload_structured_crosswalk_count": len(workload_structured_pairs),
            "workload_identity_binding_explicit": workload_identity_binding_explicit,
            "workload_keys_exact": workload_keys_exact,
            "workload_crosswalk_errors": workload_crosswalk_errors,
            "current_goal_l4_bound": current_goal_l4_bound,
        },
        "l4_software_visible_proof_present": l4_software_visible_proof_present,
        "final_closure_eligible": current_goal_l4_bound,
        "deliverable_complete": False,
        "blockers": blockers,
        "non_l4_deliverable_blockers": non_l4_deliverable_blockers,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def validate_dft_l4_goal_binding(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    payload = _load_json(payload_or_path) if isinstance(payload_or_path, Path) else dict(payload_or_path)
    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("schema_version") != DFT_L4_GOAL_BINDING_SCHEMA:
        errors.append("schema_version_mismatch")
    artifacts = _as_mapping(payload.get("artifacts"))
    for name in [
        "l4_evidence_matrix.json",
        "complete_dse_full_l4_evidence_report.json",
        "evidence_rows.json",
        "gem5_preflight.json",
    ]:
        ref = _as_mapping(artifacts.get(name))
        if ref.get("exists") is not True:
            errors.append(f"missing_required_l4_artifact:{name}")
    if payload.get("l4_software_visible_proof_present") is not True:
        errors.append("l4_software_visible_proof_not_complete")
    current = _as_mapping(payload.get("current_goal_binding"))
    if current.get("candidate_identity_binding_explicit") is not True:
        warnings.append("candidate_identity_crosswalk_missing_or_incomplete")
    if current.get("workload_identity_binding_explicit") is not True:
        warnings.append("workload_identity_crosswalk_missing_or_incomplete")
    if payload.get("deliverable_complete") is True:
        errors.append("binding_artifact_must_not_mark_deliverable_complete")
    return {
        "schema_version": DFT_L4_GOAL_BINDING_VALIDATION_SCHEMA,
        "generated_at": _now_iso(),
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def write_dft_l4_goal_binding(
    out_dir: Path,
    *,
    l4_root: Path,
    step5_run: Path | None = None,
    candidate_crosswalk: Path | None = None,
    workload_crosswalk: Path | None = None,
    candidate_mapping_policy: str = DEFAULT_CANDIDATE_MAPPING_POLICY,
    workload_mapping_policy: str = DEFAULT_WORKLOAD_MAPPING_POLICY,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_l4_goal_binding(
        l4_root=l4_root,
        step5_run=step5_run,
        candidate_crosswalk=candidate_crosswalk,
        workload_crosswalk=workload_crosswalk,
        candidate_mapping_policy=candidate_mapping_policy,
        workload_mapping_policy=workload_mapping_policy,
    )
    validation = validate_dft_l4_goal_binding(payload)
    binding_path = out_dir / "dft_l4_goal_binding.json"
    validation_path = out_dir / "dft_l4_goal_binding_validation.json"
    status_path = out_dir / "dft_l4_goal_binding_status.json"
    binding_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    validation_path.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "schema_version": DFT_L4_GOAL_BINDING_STATUS_SCHEMA,
        "status": "passed" if validation["valid"] else "blocked",
        "binding_status": payload.get("status"),
        "l4_software_visible_proof_present": payload.get("l4_software_visible_proof_present"),
        "current_goal_l4_bound": _as_mapping(payload.get("current_goal_binding")).get("current_goal_l4_bound"),
        "final_closure_eligible": payload.get("final_closure_eligible"),
        "deliverable_complete": False,
        "validation": "dft_l4_goal_binding_validation.json",
        "binding": "dft_l4_goal_binding.json",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status


__all__ = [
    "CLAIM_BOUNDARY",
    "DEFAULT_CANDIDATE_MAPPING_POLICY",
    "DEFAULT_WORKLOAD_MAPPING_POLICY",
    "DFT_L4_GOAL_BINDING_SCHEMA",
    "build_dft_l4_goal_binding",
    "validate_dft_l4_goal_binding",
    "write_dft_l4_goal_binding",
]
