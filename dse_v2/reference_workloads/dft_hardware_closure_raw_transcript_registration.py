#!/usr/bin/env python3
"""Register candidate-specific raw stage evidence refs in raw transcript indexes.

This layer is the bridge between staged unit provenance and parser execution. It
hashes raw files that already exist under the evidence root and writes those
hash/path refs into the unit's ``raw_transcript_index.json``.  It never creates
raw tool evidence, never parses results, and never upgrades hard-gate or
completion claims.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_SCHEMA = "dse.dft.hardware_closure_raw_transcript_registration.v1"
DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_VALIDATION_SCHEMA = "dse.dft.hardware_closure_raw_transcript_registration_validation.v1"
DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_STATUS_SCHEMA = "dse.dft.hardware_closure_raw_transcript_registration_status.v1"

_CLAIM_BOUNDARY = (
    "DFT hardware closure raw transcript registration records SHA-256 refs for "
    "candidate-specific raw files that already exist under the evidence root. "
    "It does not create raw tool evidence, parse hard-gate results, pass gates, "
    "or upgrade FPGA/ASIC PPA, Pareto, hardware-completion, or "
    "deliverable-completion claims."
)

_GLOBAL_FILE_NAMES = {
    "tool_versions.json",
    "command_manifest.json",
    "raw_transcript_index.json",
    "source_bundle_manifest.json",
}


def _load_json(path: Path) -> Dict[str, Any]:
    if not Path(path).exists():
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "exists": candidate.exists() and candidate.is_file(),
        "sha256": sha256_file(candidate) if candidate.exists() and candidate.is_file() else None,
        "hash_algorithm": "sha256",
    }


def _safe_child_path(root: Path, rel_path: Any) -> tuple[Path | None, str | None]:
    rel = str(rel_path or "")
    if not rel:
        return None, "relative path is empty"
    candidate = Path(rel)
    if candidate.is_absolute():
        return None, f"absolute paths are not allowed: {rel}"
    if any(part == ".." for part in candidate.parts):
        return None, f"parent traversal is not allowed: {rel}"
    root_resolved = Path(root).resolve()
    resolved = (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None, f"path escapes evidence root: {rel}"
    return resolved, None


def _packet_path(packet_index_path: Path, packet_summary: Mapping[str, Any]) -> tuple[Path | None, str | None]:
    ref = packet_summary.get("packet_json", {})
    if not isinstance(ref, Mapping):
        ref = {}
    return _safe_child_path(packet_index_path.parent, ref.get("path", ""))


def _matches_filter(unit: Mapping[str, Any], *, candidate_ids: set[str], kernel_ids: set[str]) -> bool:
    candidate_id = str(unit.get("candidate_id", ""))
    kernel_id = str(unit.get("kernel_id", ""))
    if candidate_ids and candidate_id not in candidate_ids:
        return False
    if kernel_ids and kernel_id not in kernel_ids:
        return False
    return True


def _global_file_path(evidence_root: Path, unit: Mapping[str, Any], file_name: str) -> tuple[Path | None, str | None, str]:
    for item in unit.get("expected_evidence_files", []) or []:
        if not isinstance(item, Mapping) or item.get("stage_id") != "all":
            continue
        rel = str(item.get("path", ""))
        if Path(rel).name == file_name:
            path, error = _safe_child_path(evidence_root, rel)
            return path, error, rel
    return None, f"missing expected global provenance file {file_name}", ""


def _stage_file_rows(unit: Mapping[str, Any], stage_filter: set[str]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for item in unit.get("expected_evidence_files", []) or []:
        if not isinstance(item, Mapping):
            continue
        stage_id = str(item.get("stage_id", ""))
        if stage_id == "all" or not item.get("required", True):
            continue
        if stage_filter and stage_id not in stage_filter:
            continue
        rows.append(item)
    return rows


def _json_candidate_kernel_blocker(path: Path, *, candidate_id: str, kernel_id: str) -> str | None:
    if path.suffix.lower() != ".json":
        return None
    payload = _load_json(path)
    if not payload:
        return None
    raw_candidate = payload.get("candidate_id")
    raw_kernel = payload.get("kernel_id")
    if raw_candidate is not None and str(raw_candidate) != candidate_id:
        return "raw_json_candidate_id_mismatch"
    if raw_kernel is not None and str(raw_kernel) != kernel_id:
        return "raw_json_kernel_id_mismatch"
    if payload.get("shared_microkernel_smoke_only") is True:
        return "raw_json_is_shared_microkernel_smoke_only"
    return None


def _raw_ref(*, evidence_root: Path, unit: Mapping[str, Any], stage_id: str, rel_path: str, path: Path) -> Dict[str, Any]:
    return {
        "stage_id": stage_id,
        "candidate_id": str(unit.get("candidate_id", "")),
        "kernel_id": str(unit.get("kernel_id", "")),
        "path": rel_path,
        "sha256": sha256_file(path),
        "hash_algorithm": "sha256",
        "candidate_specific": True,
        "shared_microkernel_smoke_only": False,
        "source_role": "candidate_specific_raw_stage_evidence",
    }


def _write_transcript_index(path: Path, payload: Mapping[str, Any], refs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    updated = dict(payload)
    updated.update(
        {
            "status": "raw_transcript_refs_registered_pending_parser",
            "raw_transcript_refs": [dict(ref) for ref in refs],
            "raw_stage_evidence_file_count": len(refs),
            "candidate_specific_closure": True,
            "shared_microkernel_smoke_only": False,
            "raw_evidence_scope": "candidate_specific_closure",
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": _CLAIM_BOUNDARY,
        }
    )
    write_json(path, updated)
    return _source_ref(path)


def build_dft_hardware_closure_raw_transcript_registration(
    *,
    closure_packet_index_path: Path,
    evidence_root: Path | None = None,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    stage_ids: Sequence[str] = (),
    max_units: int | None = None,
) -> Dict[str, Any]:
    packet_index_path = Path(closure_packet_index_path)
    evidence_root = Path(evidence_root or packet_index_path.parent)
    packet_index = _load_json(packet_index_path)
    candidate_filter = {str(item) for item in candidate_ids}
    kernel_filter = {str(item) for item in kernel_ids}
    stage_filter = {str(item) for item in stage_ids}
    unit_budget = max_units if max_units and max_units > 0 else None
    units: list[Dict[str, Any]] = []
    errors: list[Dict[str, Any]] = []
    for packet_summary in packet_index.get("packets", []) or []:
        if not isinstance(packet_summary, Mapping):
            continue
        packet_path, packet_error = _packet_path(packet_index_path, packet_summary)
        if packet_path is None:
            errors.append({"packet_id": packet_summary.get("packet_id"), "message": packet_error})
            continue
        packet = _load_json(packet_path)
        for unit in packet.get("units", []) or []:
            if not isinstance(unit, Mapping):
                continue
            if not _matches_filter(unit, candidate_ids=candidate_filter, kernel_ids=kernel_filter):
                continue
            if unit_budget is not None and len(units) >= unit_budget:
                break
            candidate_id = str(unit.get("candidate_id", ""))
            kernel_id = str(unit.get("kernel_id", ""))
            transcript_path, transcript_error, transcript_rel = _global_file_path(
                evidence_root, unit, "raw_transcript_index.json"
            )
            refs: list[Dict[str, Any]] = []
            blockers: list[str] = []
            missing_raw_files: list[str] = []
            present_raw_files: list[str] = []
            invalid_raw_files: list[Dict[str, Any]] = []
            missing_global_files: list[str] = []
            for file_name in sorted(_GLOBAL_FILE_NAMES):
                global_path, global_error, global_rel = _global_file_path(evidence_root, unit, file_name)
                if global_error or global_path is None or not global_path.exists() or not global_path.is_file():
                    missing_global_files.append(global_rel or file_name)
            if transcript_error or transcript_path is None:
                blockers.append("missing_raw_transcript_index_path")
            elif not transcript_path.exists() or not transcript_path.is_file():
                blockers.append("missing_raw_transcript_index")
            else:
                transcript_payload = _load_json(transcript_path)
                if str(transcript_payload.get("candidate_id", "")) != candidate_id:
                    blockers.append("raw_transcript_index_candidate_id_mismatch")
                if str(transcript_payload.get("kernel_id", "")) != kernel_id:
                    blockers.append("raw_transcript_index_kernel_id_mismatch")
                if transcript_payload.get("shared_microkernel_smoke_only") is True:
                    blockers.append("raw_transcript_index_is_shared_microkernel_smoke_only")
                if transcript_payload.get("hardware_completion_eligible") is True or transcript_payload.get("deliverable_complete") is True:
                    blockers.append("raw_transcript_index_invalid_completion_claim")
                for expected in _stage_file_rows(unit, stage_filter):
                    rel = str(expected.get("path", ""))
                    path, error = _safe_child_path(evidence_root, rel)
                    stage_id = str(expected.get("stage_id", ""))
                    if error or path is None:
                        invalid_raw_files.append({"path": rel, "message": error})
                        continue
                    if not path.exists() or not path.is_file():
                        missing_raw_files.append(rel)
                        continue
                    blocker = _json_candidate_kernel_blocker(path, candidate_id=candidate_id, kernel_id=kernel_id)
                    if blocker:
                        invalid_raw_files.append({"path": rel, "message": blocker})
                        continue
                    present_raw_files.append(rel)
                    refs.append(_raw_ref(evidence_root=evidence_root, unit=unit, stage_id=stage_id, rel_path=rel, path=path))
            transcript_ref = None
            if refs and not blockers and not invalid_raw_files and transcript_path is not None:
                transcript_payload = _load_json(transcript_path)
                transcript_ref = _write_transcript_index(transcript_path, transcript_payload, refs)
            elif transcript_path is not None and transcript_path.exists() and transcript_path.is_file():
                transcript_ref = _source_ref(transcript_path)
            status = (
                "blocked_missing_unit_provenance"
                if missing_global_files or blockers
                else "blocked_invalid_raw_stage_evidence"
                if invalid_raw_files
                else "raw_transcript_refs_registered_pending_parser"
                if refs
                else "no_raw_stage_evidence_present"
            )
            units.append(
                {
                    "unit_id": str(unit.get("unit_id", "")),
                    "candidate_id": candidate_id,
                    "kernel_id": kernel_id,
                    "packet_id": packet.get("packet_id"),
                    "shard_id": packet.get("shard_id"),
                    "status": status,
                    "raw_transcript_index": transcript_ref,
                    "raw_transcript_index_path": transcript_rel,
                    "registered_raw_stage_evidence_file_count": len(refs) if status == "raw_transcript_refs_registered_pending_parser" else 0,
                    "present_raw_stage_evidence_file_count": len(present_raw_files),
                    "missing_raw_stage_evidence_file_count": len(missing_raw_files),
                    "invalid_raw_stage_evidence_file_count": len(invalid_raw_files),
                    "missing_global_provenance_files": missing_global_files,
                    "missing_raw_stage_evidence_files": missing_raw_files[:50],
                    "invalid_raw_stage_evidence_files": invalid_raw_files[:50],
                    "blockers": blockers,
                    "stage_ids": sorted(stage_filter) if stage_filter else [str(item) for item in unit.get("stage_ids", []) or []],
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                    "claim_boundary": _CLAIM_BOUNDARY,
                }
            )
        if unit_budget is not None and len(units) >= unit_budget:
            break
    registered_count = sum(int(row["registered_raw_stage_evidence_file_count"]) for row in units)
    blocked_count = sum(1 for row in units if str(row.get("status", "")).startswith("blocked"))
    status = (
        "failed_invalid_packet_index" if errors else
        "blocked_invalid_registration_inputs" if blocked_count else
        "raw_transcript_refs_registered_pending_parser" if registered_count else
        "no_raw_stage_evidence_present" if units else
        "failed_no_matching_units"
    )
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_SCHEMA,
        "status": status,
        "source_artifacts": {"closure_packet_index": _source_ref(packet_index_path)},
        "evidence_root": str(evidence_root),
        "release_id": packet_index.get("release_id"),
        "candidate_count": packet_index.get("candidate_count"),
        "major_kernel_count": packet_index.get("major_kernel_count"),
        "unit_count": len(units),
        "registered_unit_count": sum(1 for row in units if row.get("registered_raw_stage_evidence_file_count")),
        "blocked_unit_count": blocked_count,
        "registered_raw_stage_evidence_file_count": registered_count,
        "present_raw_stage_evidence_file_count": sum(int(row["present_raw_stage_evidence_file_count"]) for row in units),
        "missing_raw_stage_evidence_file_count": sum(int(row["missing_raw_stage_evidence_file_count"]) for row in units),
        "invalid_raw_stage_evidence_file_count": sum(int(row["invalid_raw_stage_evidence_file_count"]) for row in units),
        "error_count": len(errors),
        "errors": errors,
        "units": units,
        "adjudication_result": "not_adjudicated_by_raw_transcript_registration",
        "passed_stage_count": 0,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _ref_inside_root(root: Path, ref: Mapping[str, Any]) -> tuple[Path | None, str | None]:
    raw = str(ref.get("path", ""))
    if not raw:
        return None, "file reference path is empty"
    candidate = Path(raw)
    root_resolved = Path(root).resolve()
    resolved = candidate.resolve() if candidate.is_absolute() else (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None, f"file reference escapes evidence root: {raw}"
    return resolved, None


def validate_dft_hardware_closure_raw_transcript_registration(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    payload = _load_json(payload_or_path) if isinstance(payload_or_path, Path) else dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    evidence_root = Path(str(payload.get("evidence_root") or "."))
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected raw transcript registration schema"})
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            errors.append({"field": field, "message": "raw transcript registration cannot upgrade claims"})
    if payload.get("adjudication_result") != "not_adjudicated_by_raw_transcript_registration":
        errors.append({"field": "adjudication_result", "message": "raw transcript registration must not adjudicate gates"})
    if int(payload.get("passed_stage_count", 0) or 0) != 0:
        errors.append({"field": "passed_stage_count", "message": "raw transcript registration cannot pass stages"})
    for error_index, build_error in enumerate(payload.get("errors", []) or []):
        errors.append({"field": f"errors[{error_index}]", "message": str(build_error)})
    units = payload.get("units", [])
    if not isinstance(units, list) or not units:
        errors.append({"field": "units", "message": "non-empty unit rows required"})
        units = []
    seen: set[str] = set()
    registered_total = 0
    for unit_index, unit in enumerate(units):
        if not isinstance(unit, Mapping):
            errors.append({"field": f"units[{unit_index}]", "message": "unit row must be an object"})
            continue
        unit_id = str(unit.get("unit_id", ""))
        if not unit_id:
            errors.append({"field": f"units[{unit_index}].unit_id", "message": "unit_id required"})
        if unit_id in seen:
            errors.append({"field": f"units[{unit_index}].unit_id", "message": "duplicate unit_id"})
        seen.add(unit_id)
        for field in ("hardware_completion_eligible", "deliverable_complete"):
            if unit.get(field) is True:
                errors.append({"field": f"units[{unit_index}].{field}", "message": "unit row cannot upgrade claims"})
        registered_count = int(unit.get("registered_raw_stage_evidence_file_count", 0) or 0)
        registered_total += registered_count
        ref = unit.get("raw_transcript_index", {})
        if registered_count and not isinstance(ref, Mapping):
            errors.append({"field": f"units[{unit_index}].raw_transcript_index", "message": "registered unit requires transcript ref"})
            continue
        if isinstance(ref, Mapping) and ref:
            path, path_error = _ref_inside_root(evidence_root, ref)
            if path is None:
                errors.append({"field": f"units[{unit_index}].raw_transcript_index.path", "message": str(path_error)})
                continue
            if not path.exists() or not path.is_file():
                errors.append({"field": f"units[{unit_index}].raw_transcript_index.path", "message": "raw transcript index must exist"})
                continue
            if ref.get("sha256") and ref.get("sha256") != sha256_file(path):
                errors.append({"field": f"units[{unit_index}].raw_transcript_index.sha256", "message": "raw transcript index hash mismatch"})
            transcript = _load_json(path)
            if str(transcript.get("candidate_id", "")) != str(unit.get("candidate_id", "")):
                errors.append({"field": f"units[{unit_index}].raw_transcript_index.candidate_id", "message": "transcript candidate mismatch"})
            if str(transcript.get("kernel_id", "")) != str(unit.get("kernel_id", "")):
                errors.append({"field": f"units[{unit_index}].raw_transcript_index.kernel_id", "message": "transcript kernel mismatch"})
            if transcript.get("shared_microkernel_smoke_only") is True:
                errors.append({"field": f"units[{unit_index}].raw_transcript_index.shared_microkernel_smoke_only", "message": "shared smoke transcript cannot register closure refs"})
            if transcript.get("hardware_completion_eligible") is True or transcript.get("deliverable_complete") is True:
                errors.append({"field": f"units[{unit_index}].raw_transcript_index.hardware_completion_eligible", "message": "transcript cannot upgrade claims"})
            refs = transcript.get("raw_transcript_refs", [])
            if not isinstance(refs, list):
                errors.append({"field": f"units[{unit_index}].raw_transcript_index.raw_transcript_refs", "message": "refs must be a list"})
                refs = []
            if int(transcript.get("raw_stage_evidence_file_count", 0) or 0) != len(refs):
                errors.append({"field": f"units[{unit_index}].raw_transcript_index.raw_stage_evidence_file_count", "message": "transcript file count must match refs"})
            for ref_index, raw_ref in enumerate(refs):
                if not isinstance(raw_ref, Mapping):
                    errors.append({"field": f"units[{unit_index}].raw_transcript_index.raw_transcript_refs[{ref_index}]", "message": "raw ref must be an object"})
                    continue
                raw_path, raw_error = _safe_child_path(evidence_root, raw_ref.get("path", ""))
                if raw_path is None:
                    errors.append({"field": f"units[{unit_index}].raw_transcript_index.raw_transcript_refs[{ref_index}].path", "message": str(raw_error)})
                    continue
                if not raw_path.exists() or not raw_path.is_file():
                    errors.append({"field": f"units[{unit_index}].raw_transcript_index.raw_transcript_refs[{ref_index}].path", "message": "raw evidence file must exist"})
                    continue
                if not raw_ref.get("sha256"):
                    errors.append({"field": f"units[{unit_index}].raw_transcript_index.raw_transcript_refs[{ref_index}].sha256", "message": "raw ref hash required"})
                elif raw_ref.get("sha256") != sha256_file(raw_path):
                    errors.append({"field": f"units[{unit_index}].raw_transcript_index.raw_transcript_refs[{ref_index}].sha256", "message": "raw ref hash mismatch"})
                if raw_ref.get("hash_algorithm") != "sha256":
                    errors.append({"field": f"units[{unit_index}].raw_transcript_index.raw_transcript_refs[{ref_index}].hash_algorithm", "message": "hash_algorithm must be sha256"})
                if raw_ref.get("candidate_specific") is not True or raw_ref.get("shared_microkernel_smoke_only") is True:
                    errors.append({"field": f"units[{unit_index}].raw_transcript_index.raw_transcript_refs[{ref_index}].candidate_specific", "message": "raw ref must be candidate-specific closure"})
                if str(raw_ref.get("candidate_id", "")) != str(unit.get("candidate_id", "")) or str(raw_ref.get("kernel_id", "")) != str(unit.get("kernel_id", "")):
                    errors.append({"field": f"units[{unit_index}].raw_transcript_index.raw_transcript_refs[{ref_index}]", "message": "raw ref candidate/kernel mismatch"})
    if registered_total != int(payload.get("registered_raw_stage_evidence_file_count", 0) or 0):
        errors.append({"field": "registered_raw_stage_evidence_file_count", "message": "registered total must equal unit sum"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_VALIDATION_SCHEMA,
        "valid": not errors,
        "unit_count": len(units),
        "registered_raw_stage_evidence_file_count": registered_total,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_raw_transcript_registration(
    out_dir: Path,
    *,
    closure_packet_index_path: Path,
    evidence_root: Path | None = None,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    stage_ids: Sequence[str] = (),
    max_units: int | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_raw_transcript_registration(
        closure_packet_index_path=closure_packet_index_path,
        evidence_root=evidence_root,
        candidate_ids=candidate_ids,
        kernel_ids=kernel_ids,
        stage_ids=stage_ids,
        max_units=max_units,
    )
    write_json(out_dir / "dft_hardware_closure_raw_transcript_registration.json", payload)
    validation = validate_dft_hardware_closure_raw_transcript_registration(payload)
    write_json(out_dir / "dft_hardware_closure_raw_transcript_registration_validation.json", validation)
    status = {
        "schema_version": DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_STATUS_SCHEMA,
        "status": "passed" if validation["valid"] else "failed",
        "registration": "dft_hardware_closure_raw_transcript_registration.json",
        "validation": "dft_hardware_closure_raw_transcript_registration_validation.json",
        "unit_count": payload["unit_count"],
        "registered_unit_count": payload["registered_unit_count"],
        "registered_raw_stage_evidence_file_count": payload["registered_raw_stage_evidence_file_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_raw_transcript_registration_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_SCHEMA",
    "DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_VALIDATION_SCHEMA",
    "DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_STATUS_SCHEMA",
    "build_dft_hardware_closure_raw_transcript_registration",
    "validate_dft_hardware_closure_raw_transcript_registration",
    "write_dft_hardware_closure_raw_transcript_registration",
]
