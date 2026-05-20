#!/usr/bin/env python3
"""Plan candidate/kernel-specific source-flow bindings before raw materialization.

The source-flow plan is a fail-closed provenance layer between closure packets
and raw-stage materialization.  It enumerates every packetized candidate/kernel
unit, binds each unit to at most one source-flow directory, validates the source
manifest when present, and blocks candidate/kernel reuse before any files are
copied into packet-required raw evidence slots.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_SCHEMA = "dse.dft.hardware_closure_source_flow_plan.v1"
DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_VALIDATION_SCHEMA = (
    "dse.dft.hardware_closure_source_flow_plan_validation.v1"
)
DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_STATUS_SCHEMA = (
    "dse.dft.hardware_closure_source_flow_plan_status.v1"
)

_CLAIM_BOUNDARY = (
    "DFT hardware closure source-flow planning enumerates candidate/kernel "
    "source-flow provenance before raw-stage materialization. It does not run "
    "tools, copy raw evidence, parse pass/fail results, adjudicate hard gates, "
    "certify PPA, select trusted Pareto winners, or upgrade hardware/deliverable "
    "completion."
)
_ADJUDICATION_RESULT = "not_adjudicated_by_source_flow_plan"
_PRESENT_STATUS = "source_flow_present_pending_materialization"
_MISSING_STATUS = "blocked_missing_source_flow"


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


def _directory_ref(display_path: str, resolved_path: Path) -> Dict[str, Any]:
    path = Path(resolved_path)
    return {
        "path": display_path,
        "resolved_path": str(path),
        "exists": path.exists() and path.is_dir(),
        "hash_algorithm": None,
        "sha256": None,
    }


def _manifest_ref(display_dir: str, resolved_dir: Path) -> Dict[str, Any]:
    manifest = Path(resolved_dir) / "manifest.json"
    display = str(Path(display_dir) / "manifest.json") if display_dir else ""
    return {
        "path": display,
        "resolved_path": str(manifest),
        "exists": manifest.exists() and manifest.is_file(),
        "sha256": sha256_file(manifest) if manifest.exists() and manifest.is_file() else None,
        "hash_algorithm": "sha256",
    }


def _safe_child_path(root: Path, rel_path: Any) -> tuple[Path | None, str | None]:
    rel = str(rel_path or "")
    if not rel:
        return None, "relative path is empty"
    candidate = Path(rel)
    if candidate.is_absolute():
        return candidate, None
    if any(part == ".." for part in candidate.parts):
        return None, f"parent traversal is not allowed: {rel}"
    root_resolved = Path(root).resolve()
    resolved = (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None, f"path escapes packet-index root: {rel}"
    return resolved, None


def _packet_path(packet_index_path: Path, packet_summary: Mapping[str, Any]) -> tuple[Path | None, str | None]:
    ref = packet_summary.get("packet_json", {})
    if not isinstance(ref, Mapping):
        ref = {}
    return _safe_child_path(packet_index_path.parent, ref.get("path", ""))


def _entry_path(path_value: Any, *, base_dir: Path | None) -> tuple[str, Path]:
    display = str(path_value)
    path = Path(display)
    if path.is_absolute() or base_dir is None:
        return display, path
    # Preserve workspace-relative paths such as runs/dse/... when they resolve
    # from the current working directory; otherwise use a map-file-relative
    # resolved path while keeping the original display text for provenance.
    if path.exists():
        return display, path
    return display, base_dir / path


def _entry_from_mapping(item: Mapping[str, Any], *, base_dir: Path | None) -> Dict[str, Any] | None:
    raw_path = (
        item.get("source_flow_dir")
        or item.get("source_flow")
        or item.get("flow_dir")
        or item.get("path")
        or item.get("dir")
    )
    if raw_path is None:
        return None
    display, resolved = _entry_path(raw_path, base_dir=base_dir)
    return {
        "candidate_id": str(item.get("candidate_id", "") or ""),
        "kernel_id": str(item.get("kernel_id", "") or ""),
        "source_flow_dir": display,
        "source_flow_resolved_dir": resolved,
    }


def _entries_from_mapping(payload: Mapping[str, Any], *, base_dir: Path | None) -> list[Dict[str, Any]]:
    for key in ("flows", "entries", "source_flows", "kernel_flows"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [
                entry
                for item in rows
                if isinstance(item, Mapping)
                for entry in [_entry_from_mapping(item, base_dir=base_dir)]
                if entry
            ]
    entries: list[Dict[str, Any]] = []
    for outer_key, value in payload.items():
        if isinstance(value, str):
            display, resolved = _entry_path(value, base_dir=base_dir)
            entries.append(
                {
                    "candidate_id": "",
                    "kernel_id": str(outer_key),
                    "source_flow_dir": display,
                    "source_flow_resolved_dir": resolved,
                }
            )
        elif isinstance(value, Mapping):
            direct = _entry_from_mapping(value, base_dir=base_dir)
            if direct:
                if not direct.get("kernel_id"):
                    direct["kernel_id"] = str(outer_key)
                entries.append(direct)
            else:
                for inner_key, inner_value in value.items():
                    if isinstance(inner_value, str):
                        display, resolved = _entry_path(inner_value, base_dir=base_dir)
                        entries.append(
                            {
                                "candidate_id": str(outer_key),
                                "kernel_id": str(inner_key),
                                "source_flow_dir": display,
                                "source_flow_resolved_dir": resolved,
                            }
                        )
    return entries


def source_flow_map_entries(path: Path | None) -> list[Dict[str, Any]]:
    """Return normalized source-flow map entries preserving display paths."""

    if path is None:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    base_dir = Path(path).parent
    if isinstance(payload, list):
        return [
            entry
            for item in payload
            if isinstance(item, Mapping)
            for entry in [_entry_from_mapping(item, base_dir=base_dir)]
            if entry
        ]
    if isinstance(payload, Mapping):
        return _entries_from_mapping(payload, base_dir=base_dir)
    return []


def source_flow_entry(value: str) -> Dict[str, Any]:
    """Parse ``candidate:kernel=DIR``, ``kernel=DIR``, or plain ``DIR``."""

    if "=" not in value:
        display, resolved = _entry_path(value, base_dir=None)
        return {
            "candidate_id": "",
            "kernel_id": "",
            "source_flow_dir": display,
            "source_flow_resolved_dir": resolved,
        }
    selector, raw_path = value.split("=", 1)
    candidate_id = ""
    kernel_id = ""
    if ":" in selector:
        candidate_id, kernel_id = selector.split(":", 1)
    else:
        kernel_id = selector
    display, resolved = _entry_path(raw_path, base_dir=None)
    return {
        "candidate_id": candidate_id.strip(),
        "kernel_id": kernel_id.strip(),
        "source_flow_dir": display,
        "source_flow_resolved_dir": resolved,
    }


def _dedupe_entries(entries: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    deduped: list[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in entries:
        resolved = Path(entry.get("source_flow_resolved_dir", entry.get("source_flow_dir", "")))
        key = (str(entry.get("candidate_id", "")), str(entry.get("kernel_id", "")), str(resolved))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "candidate_id": key[0],
                "kernel_id": key[1],
                "source_flow_dir": str(entry.get("source_flow_dir", "")),
                "source_flow_resolved_dir": resolved,
            }
        )
    return deduped


def _all_units(packet_index_path: Path) -> tuple[Dict[str, Any], list[Dict[str, Any]], list[Dict[str, Any]]]:
    packet_index = _load_json(packet_index_path)
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
            units.append(
                {
                    "unit_id": str(unit.get("unit_id", "")),
                    "candidate_id": str(unit.get("candidate_id", "")),
                    "kernel_id": str(unit.get("kernel_id", "")),
                    "kernel_name": str(unit.get("kernel_name", unit.get("kernel_id", ""))),
                    "kernel_family": str(unit.get("kernel_family", "")),
                    "packet_id": packet.get("packet_id"),
                    "shard_id": packet.get("shard_id"),
                    "stage_ids": [str(stage_id) for stage_id in unit.get("stage_ids", []) or []],
                    "expected_evidence_files": [
                        {
                            "stage_id": str(item.get("stage_id", "")),
                            "path": str(item.get("path", "")),
                            "required": bool(item.get("required", True)),
                        }
                        for item in unit.get("expected_evidence_files", []) or []
                        if isinstance(item, Mapping)
                    ],
                    "expected_evidence_file_count": int(unit.get("expected_evidence_file_count", 0) or 0),
                    "unit_evidence_dir": str(unit.get("unit_evidence_dir", "")),
                    "candidate_bundle_json": str(unit.get("candidate_bundle_json", "")),
                }
            )
    return packet_index, units, errors


def _entry_matches_unit(entry: Mapping[str, Any], unit: Mapping[str, Any]) -> bool:
    entry_candidate = str(entry.get("candidate_id", ""))
    entry_kernel = str(entry.get("kernel_id", ""))
    if entry_candidate and entry_candidate != str(unit.get("candidate_id", "")):
        return False
    if entry_kernel and entry_kernel != str(unit.get("kernel_id", "")):
        return False
    return True


def _manifest_identity(manifest: Mapping[str, Any]) -> tuple[str, str]:
    candidate_id = str(
        manifest.get("candidate_id")
        or manifest.get("release_candidate_id")
        or manifest.get("architecture_candidate_id")
        or ""
    )
    kernel_id = str(manifest.get("kernel_id") or manifest.get("major_kernel_id") or "")
    return candidate_id, kernel_id


def _row_for_unit(
    unit: Mapping[str, Any],
    *,
    entries: Sequence[Mapping[str, Any]],
    reused_resolved_dirs: set[str],
) -> Dict[str, Any]:
    candidate_id = str(unit.get("candidate_id", ""))
    kernel_id = str(unit.get("kernel_id", ""))
    matches = [entry for entry in entries if _entry_matches_unit(entry, unit)]
    base: Dict[str, Any] = {
        **dict(unit),
        "source_flow_present": False,
        "materialization_eligible": False,
        "source_flow_dir": None,
        "source_flow_ref": None,
        "manifest_ref": None,
        "manifest_candidate_id": None,
        "manifest_kernel_id": None,
        "blocker_ids": [],
        "blockers": [],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    if not matches:
        return {
            **base,
            "status": _MISSING_STATUS,
            "blocker_ids": ["missing_source_flow"],
            "blockers": [
                {
                    "blocker_id": "missing_source_flow",
                    "message": "No source-flow map entry matched this candidate/kernel unit.",
                }
            ],
        }

    distinct_dirs = sorted({str(Path(entry.get("source_flow_resolved_dir", ""))) for entry in matches})
    if len(distinct_dirs) > 1:
        return {
            **base,
            "status": "blocked_ambiguous_source_flow",
            "source_flow_candidates": [
                {
                    "source_flow_dir": str(entry.get("source_flow_dir", "")),
                    "source_flow_resolved_dir": str(entry.get("source_flow_resolved_dir", "")),
                }
                for entry in matches
            ],
            "blocker_ids": ["ambiguous_multiple_source_flows_for_unit"],
            "blockers": [
                {
                    "blocker_id": "ambiguous_multiple_source_flows_for_unit",
                    "message": "Multiple distinct source-flow directories matched this exact unit.",
                }
            ],
        }

    entry = matches[0]
    display_dir = str(entry.get("source_flow_dir", ""))
    resolved_dir = Path(entry.get("source_flow_resolved_dir", display_dir))
    source_ref = _directory_ref(display_dir, resolved_dir)
    manifest_ref = _manifest_ref(display_dir, resolved_dir)
    blockers: list[Dict[str, Any]] = []
    if not source_ref["exists"]:
        blockers.append(
            {
                "blocker_id": "missing_source_flow_dir",
                "message": "Source-flow directory does not exist.",
            }
        )
    if not manifest_ref["exists"]:
        blockers.append(
            {
                "blocker_id": "missing_source_flow_manifest",
                "message": "Source-flow manifest.json is required before materialization eligibility.",
            }
        )
    manifest = _load_json(resolved_dir / "manifest.json") if manifest_ref["exists"] else {}
    manifest_candidate_id, manifest_kernel_id = _manifest_identity(manifest)
    if manifest_ref["exists"] and not manifest_kernel_id:
        blockers.append(
            {
                "blocker_id": "source_flow_kernel_id_missing",
                "message": "Source-flow manifest.json must declare kernel_id or major_kernel_id.",
            }
        )
    if manifest_kernel_id and manifest_kernel_id != kernel_id:
        blockers.append(
            {
                "blocker_id": "source_flow_kernel_id_mismatch",
                "message": f"Source-flow manifest kernel_id={manifest_kernel_id!r} does not match unit kernel_id={kernel_id!r}.",
            }
        )
    if manifest_ref["exists"] and not manifest_candidate_id:
        blockers.append(
            {
                "blocker_id": "source_flow_candidate_id_missing",
                "message": "Source-flow manifest.json must declare candidate_id, release_candidate_id, or architecture_candidate_id.",
            }
        )
    if manifest_candidate_id and manifest_candidate_id != candidate_id:
        blockers.append(
            {
                "blocker_id": "source_flow_candidate_id_mismatch",
                "message": f"Source-flow manifest candidate_id={manifest_candidate_id!r} does not match unit candidate_id={candidate_id!r}.",
            }
        )
    if str(resolved_dir) in reused_resolved_dirs:
        blockers.append(
            {
                "blocker_id": "source_flow_dir_reused_across_units",
                "message": "The same source-flow directory is bound to multiple candidate/kernel units; per-unit source-flow scope is required.",
            }
        )

    blocker_ids = [str(item["blocker_id"]) for item in blockers]
    status = _PRESENT_STATUS
    if "source_flow_candidate_id_mismatch" in blocker_ids:
        status = "blocked_wrong_candidate_source_flow"
    elif "source_flow_kernel_id_mismatch" in blocker_ids:
        status = "blocked_wrong_kernel_source_flow"
    elif "source_flow_dir_reused_across_units" in blocker_ids:
        status = "blocked_reused_source_flow_scope"
    elif blockers:
        status = "blocked_invalid_source_flow_manifest"

    present = not blockers
    return {
        **base,
        "status": status,
        "source_flow_present": present,
        "materialization_eligible": present,
        "source_flow_dir": display_dir,
        "source_flow_ref": source_ref,
        "manifest_ref": manifest_ref,
        "manifest_candidate_id": manifest_candidate_id or None,
        "manifest_kernel_id": manifest_kernel_id or None,
        "manifest_schema_version": manifest.get("schema_version"),
        "blocker_ids": blocker_ids,
        "blockers": blockers,
    }


def _reused_dirs_by_unit(entries: Sequence[Mapping[str, Any]], units: Sequence[Mapping[str, Any]]) -> set[str]:
    bindings: Dict[str, set[tuple[str, str]]] = {}
    for unit in units:
        matching_dirs = {
            str(Path(entry.get("source_flow_resolved_dir", "")))
            for entry in entries
            if _entry_matches_unit(entry, unit)
        }
        for source_dir in matching_dirs:
            bindings.setdefault(source_dir, set()).add((str(unit.get("candidate_id", "")), str(unit.get("kernel_id", ""))))
    return {source_dir for source_dir, unit_keys in bindings.items() if len(unit_keys) > 1}


def build_dft_hardware_closure_source_flow_plan(
    *,
    closure_packet_index_path: Path,
    source_flow_map_path: Path | None = None,
    source_flow_entries: Sequence[str] = (),
) -> Dict[str, Any]:
    packet_index_path = Path(closure_packet_index_path)
    map_path = Path(source_flow_map_path) if source_flow_map_path is not None else None
    packet_index, units, packet_errors = _all_units(packet_index_path)
    entries = _dedupe_entries(
        [
            *source_flow_map_entries(map_path),
            *(source_flow_entry(item) for item in source_flow_entries),
        ]
    )
    entry_errors = [
        {
            "field": f"source_flow_entries[{entry_index}]",
            "status": "failed_no_matching_units",
            "candidate_id": str(entry.get("candidate_id", "")),
            "kernel_id": str(entry.get("kernel_id", "")),
            "source_flow_dir": str(entry.get("source_flow_dir", "")),
            "message": "source-flow entry did not match any packetized candidate/kernel unit",
        }
        for entry_index, entry in enumerate(entries)
        if not any(_entry_matches_unit(entry, unit) for unit in units)
    ]
    reused_dirs = _reused_dirs_by_unit(entries, units)
    unit_rows = [_row_for_unit(unit, entries=entries, reused_resolved_dirs=reused_dirs) for unit in units]

    source_flow_present_count = sum(1 for row in unit_rows if row.get("source_flow_present") is True)
    source_flow_missing_count = sum(1 for row in unit_rows if row.get("status") == _MISSING_STATUS)
    blocked_wrong_candidate_reuse_count = sum(
        1 for row in unit_rows if "source_flow_candidate_id_mismatch" in set(row.get("blocker_ids", []) or [])
    )
    blocked_wrong_kernel_reuse_count = sum(
        1 for row in unit_rows if "source_flow_kernel_id_mismatch" in set(row.get("blocker_ids", []) or [])
    )
    blocked_reused_source_flow_count = sum(
        1 for row in unit_rows if "source_flow_dir_reused_across_units" in set(row.get("blocker_ids", []) or [])
    )
    blocked_invalid_manifest_count = sum(
        1
        for row in unit_rows
        if row.get("status") == "blocked_invalid_source_flow_manifest"
        or any(
            blocker_id in set(row.get("blocker_ids", []) or [])
            for blocker_id in ("missing_source_flow_manifest", "source_flow_candidate_id_missing", "source_flow_kernel_id_missing")
        )
    )
    blocked_unit_count = sum(1 for row in unit_rows if row.get("source_flow_present") is not True)
    status = (
        "failed_invalid_packet_index"
        if packet_errors or entry_errors
        else "source_flow_plan_ready_pending_materialization"
        if source_flow_present_count and not blocked_unit_count
        else "blocked_partial_source_flow_plan"
        if source_flow_present_count
        else "blocked_no_valid_source_flows"
    )
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_SCHEMA,
        "status": status,
        "source_artifacts": {
            "closure_packet_index": _source_ref(packet_index_path),
            "source_flow_map": _source_ref(map_path) if map_path is not None else None,
            "source_flow_entries": [
                {
                    "candidate_id": str(entry.get("candidate_id", "")),
                    "kernel_id": str(entry.get("kernel_id", "")),
                    "source_flow_dir": str(entry.get("source_flow_dir", "")),
                    "source_flow_resolved_dir": str(entry.get("source_flow_resolved_dir", "")),
                }
                for entry in entries
            ],
        },
        "release_id": packet_index.get("release_id"),
        "candidate_count": packet_index.get("candidate_count"),
        "major_kernel_count": packet_index.get("major_kernel_count"),
        "planned_unit_count": len(unit_rows),
        "unit_count": len(unit_rows),
        "source_flow_present_count": source_flow_present_count,
        "source_flow_missing_count": source_flow_missing_count,
        "blocked_unit_count": blocked_unit_count,
        "blocked_wrong_candidate_reuse_count": blocked_wrong_candidate_reuse_count,
        "blocked_wrong_kernel_reuse_count": blocked_wrong_kernel_reuse_count,
        "blocked_reused_source_flow_count": blocked_reused_source_flow_count,
        "blocked_invalid_manifest_count": blocked_invalid_manifest_count,
        "provenance_mismatch_count": blocked_wrong_candidate_reuse_count + blocked_wrong_kernel_reuse_count,
        "error_count": len(packet_errors) + len(entry_errors),
        "errors": [*packet_errors, *entry_errors],
        "units": unit_rows,
        "adjudication_result": _ADJUDICATION_RESULT,
        "passed_stage_count": 0,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_source_flow_plan(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    payload = _load_json(payload_or_path) if isinstance(payload_or_path, Path) else dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected source-flow plan schema"})
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            errors.append({"field": field, "message": "source-flow planning cannot upgrade claims"})
    if payload.get("adjudication_result") != _ADJUDICATION_RESULT:
        errors.append({"field": "adjudication_result", "message": "source-flow planning cannot adjudicate gates"})
    if int(payload.get("passed_stage_count", 0) or 0) != 0:
        errors.append({"field": "passed_stage_count", "message": "source-flow planning cannot pass stages"})
    for error_index, build_error in enumerate(payload.get("errors", []) or []):
        errors.append({"field": f"errors[{error_index}]", "message": str(build_error)})

    units = payload.get("units", [])
    if not isinstance(units, list) or not units:
        errors.append({"field": "units", "message": "non-empty source-flow plan unit rows required"})
        units = []
    present_count = 0
    missing_count = 0
    blocked_count = 0
    wrong_candidate_count = 0
    wrong_kernel_count = 0
    reused_count = 0
    invalid_manifest_count = 0
    for unit_index, unit in enumerate(units):
        if not isinstance(unit, Mapping):
            errors.append({"field": f"units[{unit_index}]", "message": "unit row must be an object"})
            continue
        for field in ("hardware_completion_eligible", "deliverable_complete"):
            if unit.get(field) is True:
                errors.append({"field": f"units[{unit_index}].{field}", "message": "unit cannot upgrade claims"})
        expected_files = unit.get("expected_evidence_files", [])
        if expected_files is not None and not isinstance(expected_files, list):
            errors.append({"field": f"units[{unit_index}].expected_evidence_files", "message": "expected_evidence_files must be a list"})
            expected_files = []
        if int(unit.get("expected_evidence_file_count", 0) or 0) != len(expected_files or []):
            errors.append({"field": f"units[{unit_index}].expected_evidence_file_count", "message": "expected evidence file count must match listed files"})
        blocker_ids = [str(item) for item in unit.get("blocker_ids", []) or []]
        source_flow_present = unit.get("source_flow_present") is True
        materialization_eligible = unit.get("materialization_eligible") is True
        if source_flow_present:
            present_count += 1
            if unit.get("status") != _PRESENT_STATUS:
                errors.append({"field": f"units[{unit_index}].status", "message": "present source-flow rows must remain pending materialization"})
            if blocker_ids:
                errors.append({"field": f"units[{unit_index}].blocker_ids", "message": "present source-flow rows cannot have blockers"})
            if not materialization_eligible:
                errors.append({"field": f"units[{unit_index}].materialization_eligible", "message": "present source-flow rows must be materialization eligible"})
            source_ref = unit.get("source_flow_ref", {})
            manifest_ref = unit.get("manifest_ref", {})
            if not isinstance(source_ref, Mapping) or source_ref.get("exists") is not True:
                errors.append({"field": f"units[{unit_index}].source_flow_ref", "message": "present source-flow rows require an existing directory ref"})
            if not isinstance(manifest_ref, Mapping) or manifest_ref.get("exists") is not True:
                errors.append({"field": f"units[{unit_index}].manifest_ref", "message": "present source-flow rows require an existing manifest ref"})
            elif manifest_ref.get("sha256") and manifest_ref.get("resolved_path"):
                manifest_path = Path(str(manifest_ref.get("resolved_path")))
                if not manifest_path.exists() or not manifest_path.is_file():
                    errors.append({"field": f"units[{unit_index}].manifest_ref.path", "message": "manifest ref file must exist"})
                elif manifest_ref.get("sha256") != sha256_file(manifest_path):
                    errors.append({"field": f"units[{unit_index}].manifest_ref.sha256", "message": "manifest hash mismatch"})
        else:
            blocked_count += 1
            if materialization_eligible:
                errors.append({"field": f"units[{unit_index}].materialization_eligible", "message": "blocked rows cannot be materialization eligible"})
            if not blocker_ids:
                errors.append({"field": f"units[{unit_index}].blocker_ids", "message": "blocked rows must explain blockers"})
        if unit.get("status") == _MISSING_STATUS:
            missing_count += 1
        if "source_flow_candidate_id_mismatch" in blocker_ids:
            wrong_candidate_count += 1
        if "source_flow_kernel_id_mismatch" in blocker_ids:
            wrong_kernel_count += 1
        if "source_flow_dir_reused_across_units" in blocker_ids:
            reused_count += 1
        if unit.get("status") == "blocked_invalid_source_flow_manifest" or any(
            blocker_id in set(blocker_ids)
            for blocker_id in ("missing_source_flow_manifest", "source_flow_candidate_id_missing", "source_flow_kernel_id_missing")
        ):
            invalid_manifest_count += 1

    expected_counts = {
        "unit_count": len(units),
        "planned_unit_count": len(units),
        "source_flow_present_count": present_count,
        "source_flow_missing_count": missing_count,
        "blocked_unit_count": blocked_count,
        "blocked_wrong_candidate_reuse_count": wrong_candidate_count,
        "blocked_wrong_kernel_reuse_count": wrong_kernel_count,
        "blocked_reused_source_flow_count": reused_count,
        "blocked_invalid_manifest_count": invalid_manifest_count,
        "provenance_mismatch_count": wrong_candidate_count + wrong_kernel_count,
    }
    for field, expected in expected_counts.items():
        if int(payload.get(field, 0) or 0) != expected:
            errors.append({"field": field, "message": f"expected {expected} from unit rows"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_VALIDATION_SCHEMA,
        "valid": not errors,
        "unit_count": len(units),
        "source_flow_present_count": present_count,
        "blocked_unit_count": blocked_count,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def materialization_entries_from_source_flow_plan(payload_or_path: Mapping[str, Any] | Path) -> list[Dict[str, Any]]:
    """Return materialization-safe entries from a validated source-flow plan."""

    payload = _load_json(payload_or_path) if isinstance(payload_or_path, Path) else dict(payload_or_path)
    entries: list[Dict[str, Any]] = []
    for unit in payload.get("units", []) or []:
        if not isinstance(unit, Mapping):
            continue
        if unit.get("source_flow_present") is not True or unit.get("materialization_eligible") is not True:
            continue
        source_ref = unit.get("source_flow_ref", {}) if isinstance(unit.get("source_flow_ref", {}), Mapping) else {}
        display_path = str(unit.get("source_flow_dir", ""))
        resolved_path = str(source_ref.get("resolved_path") or display_path)
        materialization_path = display_path if display_path and Path(display_path).exists() else resolved_path
        entries.append(
            {
                "candidate_id": str(unit.get("candidate_id", "")),
                "kernel_id": str(unit.get("kernel_id", "")),
                "source_flow_dir": Path(materialization_path),
                "source_flow_resolved_dir": Path(resolved_path),
            }
        )
    return entries


def write_dft_hardware_closure_source_flow_plan(
    out_dir: Path,
    *,
    closure_packet_index_path: Path,
    source_flow_map_path: Path | None = None,
    source_flow_entries: Sequence[str] = (),
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_source_flow_plan(
        closure_packet_index_path=closure_packet_index_path,
        source_flow_map_path=source_flow_map_path,
        source_flow_entries=source_flow_entries,
    )
    write_json(out_dir / "dft_hardware_closure_source_flow_plan.json", payload)
    validation = validate_dft_hardware_closure_source_flow_plan(payload)
    write_json(out_dir / "dft_hardware_closure_source_flow_plan_validation.json", validation)
    status = {
        "schema_version": DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_STATUS_SCHEMA,
        "status": "passed" if validation["valid"] else "failed",
        "source_flow_plan": "dft_hardware_closure_source_flow_plan.json",
        "validation": "dft_hardware_closure_source_flow_plan_validation.json",
        "unit_count": payload["unit_count"],
        "source_flow_present_count": payload["source_flow_present_count"],
        "source_flow_missing_count": payload["source_flow_missing_count"],
        "blocked_unit_count": payload["blocked_unit_count"],
        "blocked_wrong_candidate_reuse_count": payload["blocked_wrong_candidate_reuse_count"],
        "blocked_wrong_kernel_reuse_count": payload["blocked_wrong_kernel_reuse_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_source_flow_plan_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_SCHEMA",
    "DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_STATUS_SCHEMA",
    "DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_VALIDATION_SCHEMA",
    "build_dft_hardware_closure_source_flow_plan",
    "materialization_entries_from_source_flow_plan",
    "source_flow_entry",
    "source_flow_map_entries",
    "validate_dft_hardware_closure_source_flow_plan",
    "write_dft_hardware_closure_source_flow_plan",
]
