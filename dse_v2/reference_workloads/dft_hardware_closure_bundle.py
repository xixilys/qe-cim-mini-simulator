#!/usr/bin/env python3
"""Candidate-specific bundle templates for DFT/QE hardware closure packets.

This layer materializes the per-unit ``candidate_bundle.json`` files referenced
by closure packets.  A bundle is execution metadata only: it names the candidate,
kernel, expected raw evidence files, and replay command templates.  It never
creates raw tool evidence and therefore cannot close any hard gate by itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_SCHEMA = "dse.dft.hardware_closure_candidate_bundle.v1"
DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_INDEX_SCHEMA = "dse.dft.hardware_closure_candidate_bundle_index.v1"
DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_VALIDATION_SCHEMA = "dse.dft.hardware_closure_candidate_bundle_validation.v1"

_CLAIM_BOUNDARY = (
    "Candidate-specific hardware closure bundles are execution metadata and "
    "source/evidence placement contracts only. They do not contain raw VCS/HLS, "
    "Vivado, DC, correctness, timing, area, PPA, trusted Pareto, or deliverable "
    "completion evidence."
)


def _load_json(path: Path) -> Dict[str, Any]:
    if not Path(path).exists():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
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
    """Resolve ``rel_path`` under ``root`` without allowing path escape."""

    rel = str(rel_path or "")
    if not rel:
        return None, "relative path is empty"
    rel_candidate = Path(rel)
    if rel_candidate.is_absolute():
        return None, f"absolute paths are not allowed: {rel}"
    if any(part == ".." for part in rel_candidate.parts):
        return None, f"parent traversal is not allowed: {rel}"
    root_resolved = Path(root).resolve()
    candidate = (root_resolved / rel_candidate).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None, f"path escapes evidence root: {rel}"
    return candidate, None


def _bundle_ref_path(payload: Mapping[str, Any], ref: Mapping[str, Any]) -> Path:
    raw_path = Path(str(ref.get("path", "")))
    if raw_path.is_absolute():
        return raw_path
    evidence_root = Path(str(payload.get("evidence_root") or "."))
    return evidence_root / raw_path


def _packet_path(packet_index_path: Path, packet_summary: Mapping[str, Any]) -> Path:
    ref = packet_summary.get("packet_json", {})
    if not isinstance(ref, Mapping):
        ref = {}
    rel = str(ref.get("path", ""))
    candidate = Path(rel)
    return candidate if candidate.is_absolute() else packet_index_path.parent / candidate


def _bundle_payload(*, packet_path: Path, packet: Mapping[str, Any], unit: Mapping[str, Any]) -> Dict[str, Any]:
    expected = [dict(row) for row in unit.get("expected_evidence_files", []) or [] if isinstance(row, Mapping)]
    raw_required = [row for row in expected if row.get("required", True)]
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_SCHEMA,
        "status": "bundle_template_only_missing_raw_evidence",
        "packet_id": packet.get("packet_id"),
        "shard_id": packet.get("shard_id"),
        "release_id": packet.get("release_id"),
        "unit_id": str(unit.get("unit_id", "")),
        "candidate_id": str(unit.get("candidate_id", "")),
        "kernel_id": str(unit.get("kernel_id", "")),
        "kernel_name": unit.get("kernel_name"),
        "kernel_family": unit.get("kernel_family"),
        "stage_ids": [str(item) for item in unit.get("stage_ids", []) or []],
        "work_item_ids": [str(item) for item in unit.get("work_item_ids", []) or []],
        "required_tools": [str(item) for item in unit.get("required_tools", []) or []],
        "required_command_template_ids": [str(item) for item in unit.get("required_command_template_ids", []) or []],
        "expected_evidence_files": expected,
        "expected_evidence_file_count": len(raw_required),
        "raw_evidence_file_count": 0,
        "source_artifacts": {
            "closure_packet": _source_ref(packet_path),
        },
        "candidate_specific_bundle_present": True,
        "raw_evidence_present": False,
        "adjudication_status": "not_adjudicated_by_bundle",
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_hardware_closure_candidate_bundle_index(
    *,
    closure_packet_index_path: Path,
    evidence_root: Path | None = None,
    max_units: int | None = None,
) -> Dict[str, Any]:
    """Write candidate bundle templates referenced by a packet index.

    ``evidence_root`` defaults to the packet-index directory, matching the
    intake default.  Raw evidence files are intentionally not created.
    """

    packet_index_path = Path(closure_packet_index_path)
    evidence_root = Path(evidence_root or packet_index_path.parent)
    packet_index = _load_json(packet_index_path)
    bundle_rows: list[Dict[str, Any]] = []
    build_errors: list[Dict[str, Any]] = []
    unit_budget = max_units if max_units and max_units > 0 else None
    for packet_summary in packet_index.get("packets", []) or []:
        if not isinstance(packet_summary, Mapping):
            continue
        packet_path = _packet_path(packet_index_path, packet_summary)
        packet = _load_json(packet_path)
        for unit in packet.get("units", []) or []:
            if not isinstance(unit, Mapping):
                continue
            if unit_budget is not None and len(bundle_rows) >= unit_budget:
                break
            rel_bundle = str(unit.get("candidate_bundle_json") or "")
            if not rel_bundle:
                continue
            bundle_path, bundle_error = _safe_child_path(evidence_root, rel_bundle)
            if bundle_path is None:
                build_errors.append(
                    {
                        "unit_id": str(unit.get("unit_id", "")),
                        "candidate_id": str(unit.get("candidate_id", "")),
                        "kernel_id": str(unit.get("kernel_id", "")),
                        "candidate_bundle_json": rel_bundle,
                        "message": bundle_error,
                    }
                )
                continue
            payload = _bundle_payload(packet_path=packet_path, packet=packet, unit=unit)
            write_json(bundle_path, payload)
            bundle_rows.append(
                {
                    "unit_id": payload["unit_id"],
                    "candidate_id": payload["candidate_id"],
                    "kernel_id": payload["kernel_id"],
                    "candidate_bundle": _source_ref(bundle_path),
                    "expected_evidence_file_count": payload["expected_evidence_file_count"],
                    "raw_evidence_file_count": 0,
                    "status": payload["status"],
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                    "claim_boundary": _CLAIM_BOUNDARY,
                }
            )
        if unit_budget is not None and len(bundle_rows) >= unit_budget:
            break
    status = (
        "failed_invalid_candidate_bundle_path"
        if build_errors
        else "bundle_templates_written_missing_raw_evidence"
        if bundle_rows
        else "failed_no_units"
    )
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_INDEX_SCHEMA,
        "status": status,
        "source_artifacts": {"closure_packet_index": _source_ref(packet_index_path)},
        "evidence_root": str(evidence_root),
        "release_id": packet_index.get("release_id"),
        "candidate_count": packet_index.get("candidate_count"),
        "major_kernel_count": packet_index.get("major_kernel_count"),
        "bundle_count": len(bundle_rows),
        "expected_evidence_file_count": sum(int(row["expected_evidence_file_count"]) for row in bundle_rows),
        "raw_evidence_file_count": 0,
        "error_count": len(build_errors),
        "errors": build_errors,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "bundles": bundle_rows,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_candidate_bundle_index(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    if isinstance(payload_or_path, Path):
        payload = _load_json(payload_or_path)
    else:
        payload = dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_INDEX_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected candidate-bundle index schema"})
    if payload.get("hardware_completion_eligible") is True or payload.get("deliverable_complete") is True:
        errors.append({"field": "hardware_completion_eligible", "message": "bundle index cannot upgrade claims"})
    for error_index, build_error in enumerate(payload.get("errors", []) or []):
        if isinstance(build_error, Mapping):
            errors.append({"field": f"errors[{error_index}]", "message": str(build_error.get("message", "bundle build error"))})
        else:
            errors.append({"field": f"errors[{error_index}]", "message": "bundle build error"})
    if int(payload.get("raw_evidence_file_count", 0) or 0) != 0:
        errors.append({"field": "raw_evidence_file_count", "message": "bundle index cannot contain raw evidence"})
    bundles = payload.get("bundles", [])
    if not isinstance(bundles, list) or not bundles:
        errors.append({"field": "bundles", "message": "non-empty bundle rows required"})
        bundles = []
    seen: set[str] = set()
    for index, row in enumerate(bundles):
        if not isinstance(row, Mapping):
            errors.append({"field": f"bundles[{index}]", "message": "bundle row must be an object"})
            continue
        unit_id = str(row.get("unit_id", ""))
        if not unit_id:
            errors.append({"field": f"bundles[{index}].unit_id", "message": "unit_id required"})
        if unit_id in seen:
            errors.append({"field": f"bundles[{index}].unit_id", "message": "duplicate unit_id"})
        seen.add(unit_id)
        for field in ("hardware_completion_eligible", "deliverable_complete"):
            if row.get(field) is True:
                errors.append({"field": f"bundles[{index}].{field}", "message": "bundle row cannot upgrade claims"})
        if int(row.get("raw_evidence_file_count", 0) or 0) != 0:
            errors.append({"field": f"bundles[{index}].raw_evidence_file_count", "message": "bundle row cannot contain raw evidence"})
        bundle_ref = row.get("candidate_bundle", {})
        if not isinstance(bundle_ref, Mapping) or bundle_ref.get("exists") is not True or not bundle_ref.get("sha256"):
            errors.append({"field": f"bundles[{index}].candidate_bundle", "message": "candidate bundle file ref with hash required"})
            continue
        bundle_path = _bundle_ref_path(payload, bundle_ref)
        if not bundle_path.exists() or not bundle_path.is_file():
            errors.append({"field": f"bundles[{index}].candidate_bundle.path", "message": "candidate bundle file must exist"})
            continue
        actual_sha = sha256_file(bundle_path)
        if bundle_ref.get("sha256") != actual_sha:
            errors.append({"field": f"bundles[{index}].candidate_bundle.sha256", "message": "candidate bundle hash mismatch"})
        bundle_payload = _load_json(bundle_path)
        if bundle_payload.get("schema_version") != DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_SCHEMA:
            errors.append({"field": f"bundles[{index}].candidate_bundle.schema_version", "message": "unexpected candidate bundle schema"})
        for field in ("unit_id", "candidate_id", "kernel_id"):
            if str(bundle_payload.get(field, "")) != str(row.get(field, "")):
                errors.append({"field": f"bundles[{index}].candidate_bundle.{field}", "message": "bundle payload does not match index row"})
        if bundle_payload.get("status") != "bundle_template_only_missing_raw_evidence":
            errors.append({"field": f"bundles[{index}].candidate_bundle.status", "message": "bundle payload must remain template-only"})
        if int(bundle_payload.get("raw_evidence_file_count", 0) or 0) != 0:
            errors.append({"field": f"bundles[{index}].candidate_bundle.raw_evidence_file_count", "message": "bundle payload cannot contain raw evidence"})
        if bundle_payload.get("raw_evidence_present") is not False:
            errors.append({"field": f"bundles[{index}].candidate_bundle.raw_evidence_present", "message": "bundle payload cannot mark raw evidence present"})
        if bundle_payload.get("adjudication_status") != "not_adjudicated_by_bundle":
            errors.append({"field": f"bundles[{index}].candidate_bundle.adjudication_status", "message": "bundle payload cannot adjudicate gates"})
        for field in ("hardware_completion_eligible", "deliverable_complete"):
            if bundle_payload.get(field) is True:
                errors.append({"field": f"bundles[{index}].candidate_bundle.{field}", "message": "bundle payload cannot upgrade claims"})
        expected_rows = bundle_payload.get("expected_evidence_files", [])
        if not isinstance(expected_rows, list):
            errors.append({"field": f"bundles[{index}].candidate_bundle.expected_evidence_files", "message": "expected evidence rows must be a list"})
            continue
        for expected_index, expected in enumerate(expected_rows):
            if not isinstance(expected, Mapping):
                errors.append({"field": f"bundles[{index}].candidate_bundle.expected_evidence_files[{expected_index}]", "message": "expected evidence row must be an object"})
                continue
            if expected.get("present") is True or expected.get("exists") is True:
                errors.append({"field": f"bundles[{index}].candidate_bundle.expected_evidence_files[{expected_index}]", "message": "bundle template cannot mark evidence present"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_VALIDATION_SCHEMA,
        "valid": not errors,
        "bundle_count": len(bundles),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_candidate_bundles(
    out_dir: Path,
    *,
    closure_packet_index_path: Path,
    evidence_root: Path | None = None,
    max_units: int | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_candidate_bundle_index(
        closure_packet_index_path=closure_packet_index_path,
        evidence_root=evidence_root,
        max_units=max_units,
    )
    write_json(out_dir / "dft_hardware_closure_candidate_bundle_index.json", payload)
    validation = validate_dft_hardware_closure_candidate_bundle_index(payload)
    write_json(out_dir / "dft_hardware_closure_candidate_bundle_index_validation.json", validation)
    status = {
        "schema_version": "dse.dft.hardware_closure_candidate_bundle_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "candidate_bundle_index": "dft_hardware_closure_candidate_bundle_index.json",
        "validation": "dft_hardware_closure_candidate_bundle_index_validation.json",
        "bundle_count": payload["bundle_count"],
        "raw_evidence_file_count": payload["raw_evidence_file_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_candidate_bundle_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_SCHEMA",
    "DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_INDEX_SCHEMA",
    "DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_VALIDATION_SCHEMA",
    "build_dft_hardware_closure_candidate_bundle_index",
    "validate_dft_hardware_closure_candidate_bundle_index",
    "write_dft_hardware_closure_candidate_bundles",
]
