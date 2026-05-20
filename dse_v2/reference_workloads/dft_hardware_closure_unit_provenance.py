#!/usr/bin/env python3
"""Candidate-specific unit provenance staging for DFT/QE hardware closure.

This layer writes the unit-level provenance files required before raw
candidate/kernel/stage evidence can be parsed:

* ``tool_versions.json``;
* ``command_manifest.json``;
* ``raw_transcript_index.json``;
* ``source_bundle_manifest.json``.

The files are provenance scaffolding only.  They do not create raw stage
evidence, pass hard gates, or upgrade FPGA/ASIC/PPA/deliverable claims.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_INDEX_SCHEMA = "dse.dft.hardware_closure_unit_provenance_index.v1"
DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_VALIDATION_SCHEMA = "dse.dft.hardware_closure_unit_provenance_validation.v1"
DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_STATUS_SCHEMA = "dse.dft.hardware_closure_unit_provenance_status.v1"

_GLOBAL_FILE_NAMES = {
    "tool_versions.json",
    "command_manifest.json",
    "raw_transcript_index.json",
    "source_bundle_manifest.json",
}

_CLAIM_BOUNDARY = (
    "DFT hardware closure unit provenance files stage candidate-specific "
    "source/tool/command/transcript metadata only. They do not contain raw "
    "stage evidence and cannot pass golden, simulation, synthesis, Vivado, DC, "
    "PPA, Pareto, hardware-completion, or deliverable-completion gates."
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


def _ref_path_inside_evidence_root(root: Path, ref: Mapping[str, Any]) -> tuple[Path | None, str | None]:
    """Resolve an index file ref and require it to remain under ``root``."""

    raw = str(ref.get("path", ""))
    if not raw:
        return None, "file reference path is empty"
    root_resolved = Path(root).resolve()
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None, f"file reference escapes evidence root: {raw}"
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


def _global_rows(unit: Mapping[str, Any]) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for item in unit.get("expected_evidence_files", []) or []:
        if not isinstance(item, Mapping):
            continue
        if item.get("stage_id") != "all":
            continue
        path = str(item.get("path", ""))
        if Path(path).name in _GLOBAL_FILE_NAMES:
            rows.append(dict(item))
    return rows


def _command_templates(packet: Mapping[str, Any], unit: Mapping[str, Any]) -> list[Dict[str, Any]]:
    required = {str(item) for item in unit.get("required_command_template_ids", []) or []}
    templates = []
    for template in packet.get("command_templates", []) or []:
        if isinstance(template, Mapping) and str(template.get("template_id", "")) in required:
            templates.append(dict(template))
    return templates


def _artifact_ref_if_present(root: Path, rel_path: Any) -> Dict[str, Any]:
    path, error = _safe_child_path(root, rel_path)
    exists = path is not None and path.exists() and path.is_file()
    return {
        "path": str(rel_path or ""),
        "exists": bool(exists),
        "sha256": sha256_file(path) if exists else None,
        "hash_algorithm": "sha256",
        "path_valid": error is None,
        "path_error": error,
    }


def _write_unit_file(path: Path, payload: Mapping[str, Any]) -> Dict[str, Any]:
    write_json(path, payload)
    return _source_ref(path)


def _load_error_message(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("message", "unit provenance build error"))
    return "unit provenance build error"


def _unit_payloads(
    *,
    evidence_root: Path,
    packet_path: Path,
    packet: Mapping[str, Any],
    unit: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    candidate_id = str(unit.get("candidate_id", ""))
    kernel_id = str(unit.get("kernel_id", ""))
    base = {
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
        "unit_id": str(unit.get("unit_id", "")),
        "candidate_specific_closure": True,
        "shared_microkernel_smoke_only": False,
        "raw_evidence_scope": "candidate_specific_closure",
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    command_templates = _command_templates(packet, unit)
    source_refs = [
        {
            "role": "candidate_bundle_template",
            **_artifact_ref_if_present(evidence_root, unit.get("candidate_bundle_json")),
        },
        {
            "role": "closure_packet",
            **_source_ref(packet_path),
        },
    ]
    return {
        "tool_versions.json": {
            "schema_version": "dse.dft.hardware_closure.tool_versions.v1",
            **base,
            "status": "staged_pending_real_tool_execution",
            "required_tools": [str(item) for item in unit.get("required_tools", []) or []],
            "tool_versions_recorded": False,
            "tool_rows": [],
        },
        "command_manifest.json": {
            "schema_version": "dse.dft.hardware_closure.command_manifest.v1",
            **base,
            "status": "staged_pending_command_execution",
            "commands_executed": False,
            "command_templates": command_templates,
            "executed_commands": [],
        },
        "raw_transcript_index.json": {
            "schema_version": "dse.dft.hardware_closure.raw_transcript_index.v1",
            **base,
            "status": "staged_pending_raw_stage_evidence",
            "raw_transcript_refs": [],
            "raw_stage_evidence_file_count": 0,
        },
        "source_bundle_manifest.json": {
            "schema_version": "dse.dft.hardware_closure.source_bundle_manifest.v1",
            **base,
            "status": "candidate_specific_source_bundle_staged_pending_raw_evidence",
            "source_refs": source_refs,
            "source_ref_count": len(source_refs),
            "stage_ids": [str(item) for item in unit.get("stage_ids", []) or []],
        },
    }


def build_dft_hardware_closure_unit_provenance_index(
    *,
    closure_packet_index_path: Path,
    evidence_root: Path | None = None,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    max_units: int | None = None,
) -> Dict[str, Any]:
    packet_index_path = Path(closure_packet_index_path)
    evidence_root = Path(evidence_root or packet_index_path.parent)
    packet_index = _load_json(packet_index_path)
    candidate_filter = {str(item) for item in candidate_ids}
    kernel_filter = {str(item) for item in kernel_ids}
    unit_budget = max_units if max_units and max_units > 0 else None
    unit_rows: list[Dict[str, Any]] = []
    errors: list[Dict[str, Any]] = []
    for packet_summary in packet_index.get("packets", []) or []:
        if not isinstance(packet_summary, Mapping):
            continue
        packet_path, packet_error = _packet_path(packet_index_path, packet_summary)
        if packet_path is None:
            errors.append(
                {
                    "packet_id": packet_summary.get("packet_id"),
                    "path": (packet_summary.get("packet_json", {}) or {}).get("path")
                    if isinstance(packet_summary.get("packet_json", {}), Mapping)
                    else None,
                    "message": packet_error,
                }
            )
            continue
        packet = _load_json(packet_path)
        for unit in packet.get("units", []) or []:
            if not isinstance(unit, Mapping):
                continue
            if not _matches_filter(unit, candidate_ids=candidate_filter, kernel_ids=kernel_filter):
                continue
            if unit_budget is not None and len(unit_rows) >= unit_budget:
                break
            refs: Dict[str, Dict[str, Any]] = {}
            payloads = _unit_payloads(
                evidence_root=evidence_root,
                packet_path=packet_path,
                packet=packet,
                unit=unit,
            )
            for global_row in _global_rows(unit):
                rel_path = str(global_row.get("path", ""))
                file_name = Path(rel_path).name
                payload = payloads.get(file_name)
                if payload is None:
                    continue
                target, error = _safe_child_path(evidence_root, rel_path)
                if target is None:
                    errors.append(
                        {
                            "unit_id": str(unit.get("unit_id", "")),
                            "path": rel_path,
                            "message": error,
                        }
                    )
                    continue
                refs[file_name] = _write_unit_file(target, payload)
            unit_rows.append(
                {
                    "unit_id": str(unit.get("unit_id", "")),
                    "candidate_id": str(unit.get("candidate_id", "")),
                    "kernel_id": str(unit.get("kernel_id", "")),
                    "packet_id": packet.get("packet_id"),
                    "shard_id": packet.get("shard_id"),
                    "status": "candidate_specific_provenance_staged_pending_raw_evidence",
                    "global_provenance_file_count": len(refs),
                    "raw_stage_evidence_file_count": 0,
                    "provenance_files": refs,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                    "claim_boundary": _CLAIM_BOUNDARY,
                }
            )
        if unit_budget is not None and len(unit_rows) >= unit_budget:
            break
    status = (
        "failed_invalid_unit_provenance_path"
        if errors
        else "candidate_specific_provenance_staged_pending_raw_evidence"
        if unit_rows
        else "failed_no_matching_units"
    )
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_INDEX_SCHEMA,
        "status": status,
        "source_artifacts": {"closure_packet_index": _source_ref(packet_index_path)},
        "evidence_root": str(evidence_root),
        "release_id": packet_index.get("release_id"),
        "candidate_count": packet_index.get("candidate_count"),
        "major_kernel_count": packet_index.get("major_kernel_count"),
        "staged_unit_count": len(unit_rows),
        "global_provenance_file_count": sum(int(row["global_provenance_file_count"]) for row in unit_rows),
        "raw_stage_evidence_file_count": 0,
        "error_count": len(errors),
        "errors": errors,
        "units": unit_rows,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_unit_provenance_index(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    payload = _load_json(payload_or_path) if isinstance(payload_or_path, Path) else dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    evidence_root = Path(str(payload.get("evidence_root") or "."))
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_INDEX_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected unit provenance index schema"})
    if payload.get("hardware_completion_eligible") is True or payload.get("deliverable_complete") is True:
        errors.append({"field": "hardware_completion_eligible", "message": "unit provenance cannot upgrade claims"})
    if int(payload.get("raw_stage_evidence_file_count", 0) or 0) != 0:
        errors.append({"field": "raw_stage_evidence_file_count", "message": "unit provenance index cannot contain raw stage evidence"})
    for error_index, build_error in enumerate(payload.get("errors", []) or []):
        errors.append({"field": f"errors[{error_index}]", "message": str(_load_error_message(build_error))})
    units = payload.get("units", [])
    if not isinstance(units, list) or not units:
        errors.append({"field": "units", "message": "non-empty unit provenance rows required"})
        units = []
    seen: set[str] = set()
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
        if unit.get("hardware_completion_eligible") is True or unit.get("deliverable_complete") is True:
            errors.append({"field": f"units[{unit_index}].hardware_completion_eligible", "message": "unit row cannot upgrade claims"})
        if int(unit.get("raw_stage_evidence_file_count", 0) or 0) != 0:
            errors.append({"field": f"units[{unit_index}].raw_stage_evidence_file_count", "message": "unit row cannot contain raw stage evidence"})
        refs = unit.get("provenance_files", {})
        if not isinstance(refs, Mapping):
            errors.append({"field": f"units[{unit_index}].provenance_files", "message": "provenance_files must be an object"})
            continue
        missing = sorted(_GLOBAL_FILE_NAMES - set(str(key) for key in refs))
        if missing:
            errors.append({"field": f"units[{unit_index}].provenance_files", "message": f"missing provenance files: {', '.join(missing)}"})
        for file_name, ref in refs.items():
            file_name = str(file_name)
            if file_name not in _GLOBAL_FILE_NAMES:
                errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}", "message": "unexpected provenance file name"})
                continue
            if not isinstance(ref, Mapping) or ref.get("exists") is not True or not ref.get("sha256"):
                errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}", "message": "existing hashed provenance file required"})
                continue
            path, path_error = _ref_path_inside_evidence_root(evidence_root, ref)
            if path is None:
                errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}.path", "message": str(path_error)})
                continue
            if not path.exists() or not path.is_file():
                errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}.path", "message": "provenance file must exist"})
                continue
            actual_sha = sha256_file(path)
            if ref.get("sha256") != actual_sha:
                errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}.sha256", "message": "provenance file hash mismatch"})
            payload_file = _load_json(path)
            if payload_file.get("candidate_id") != unit.get("candidate_id") or payload_file.get("kernel_id") != unit.get("kernel_id"):
                errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}", "message": "provenance payload must match unit candidate/kernel"})
            if payload_file.get("hardware_completion_eligible") is True or payload_file.get("deliverable_complete") is True:
                errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}", "message": "provenance payload cannot upgrade claims"})
            if payload_file.get("candidate_specific_closure") is not True:
                errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}", "message": "provenance payload must be candidate-specific closure"})
            if payload_file.get("shared_microkernel_smoke_only") is True:
                errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}", "message": "shared microkernel smoke cannot be staged as unit provenance"})
            if str(payload_file.get("raw_evidence_scope", "")) != "candidate_specific_closure":
                errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}", "message": "provenance payload must declare candidate-specific raw evidence scope"})
            if file_name == "raw_transcript_index.json":
                if int(payload_file.get("raw_stage_evidence_file_count", 0) or 0) != 0:
                    errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}.raw_stage_evidence_file_count", "message": "staged provenance cannot contain raw stage evidence"})
                refs_payload = payload_file.get("raw_transcript_refs", [])
                if refs_payload not in ([], None):
                    errors.append({"field": f"units[{unit_index}].provenance_files.{file_name}.raw_transcript_refs", "message": "staged provenance cannot claim raw transcript refs"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_VALIDATION_SCHEMA,
        "valid": not errors,
        "staged_unit_count": len(units),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_unit_provenance(
    out_dir: Path,
    *,
    closure_packet_index_path: Path,
    evidence_root: Path | None = None,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    max_units: int | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_unit_provenance_index(
        closure_packet_index_path=closure_packet_index_path,
        evidence_root=evidence_root,
        candidate_ids=candidate_ids,
        kernel_ids=kernel_ids,
        max_units=max_units,
    )
    write_json(out_dir / "dft_hardware_closure_unit_provenance_index.json", payload)
    validation = validate_dft_hardware_closure_unit_provenance_index(payload)
    write_json(out_dir / "dft_hardware_closure_unit_provenance_validation.json", validation)
    status = {
        "schema_version": DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_STATUS_SCHEMA,
        "status": "passed" if validation["valid"] else "failed",
        "unit_provenance_index": "dft_hardware_closure_unit_provenance_index.json",
        "validation": "dft_hardware_closure_unit_provenance_validation.json",
        "staged_unit_count": payload["staged_unit_count"],
        "global_provenance_file_count": payload["global_provenance_file_count"],
        "raw_stage_evidence_file_count": payload["raw_stage_evidence_file_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_unit_provenance_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_INDEX_SCHEMA",
    "DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_VALIDATION_SCHEMA",
    "DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_STATUS_SCHEMA",
    "build_dft_hardware_closure_unit_provenance_index",
    "validate_dft_hardware_closure_unit_provenance_index",
    "write_dft_hardware_closure_unit_provenance",
]
