#!/usr/bin/env python3
"""Build candidate/kernel source-flow maps from generated source-flow roots.

The source-flow map is a replayable discovery artifact.  It scans generated
RTL/HLS source-flow roots for ``manifest.json`` files, accepts only manifests
that carry exact packetized ``candidate_id`` and ``kernel_id`` provenance, and
writes a ``source_flow_map.json`` consumable by the source-flow plan builder.
It never runs tools, materializes raw evidence, adjudicates gates, or upgrades
hardware/deliverable completion claims.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.reference_workloads.dft_hardware_closure_source_flow_plan import (
    _all_units,
    _manifest_identity,
)

DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_SCHEMA = (
    "dse.dft.hardware_closure_source_flow_map.v1"
)
DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_VALIDATION_SCHEMA = (
    "dse.dft.hardware_closure_source_flow_map_validation.v1"
)
DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_STATUS_SCHEMA = (
    "dse.dft.hardware_closure_source_flow_map_status.v1"
)

_CLAIM_BOUNDARY = (
    "DFT hardware closure source-flow map discovery binds generated source-flow "
    "directories to packetized candidate/kernel units by exact manifest "
    "provenance only. It does not run tools, copy raw evidence, parse pass/fail "
    "results, adjudicate hard gates, certify PPA, select trusted Pareto winners, "
    "or upgrade hardware/deliverable completion."
)
_ADJUDICATION_RESULT = "not_adjudicated_by_source_flow_map"
_READY_STATUS = "source_flow_map_ready_pending_plan"
_PARTIAL_STATUS = "blocked_partial_source_flow_map"
_EMPTY_STATUS = "blocked_no_candidate_specific_source_flows"
_INVALID_PACKET_STATUS = "failed_invalid_packet_index"
_MAPPED_UNIT_STATUS = "source_flow_mapped_pending_plan"
_MISSING_UNIT_STATUS = "blocked_missing_source_flow_dir"
_DUPLICATE_UNIT_STATUS = "blocked_duplicate_source_flow_dirs"


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "exists": candidate.exists() and candidate.is_file(),
        "sha256": (
            sha256_file(candidate)
            if candidate.exists() and candidate.is_file()
            else None
        ),
        "hash_algorithm": "sha256",
    }


def _directory_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "resolved_path": (
            str(candidate.resolve()) if candidate.exists() else str(candidate)
        ),
        "exists": candidate.exists() and candidate.is_dir(),
        "hash_algorithm": None,
        "sha256": None,
    }


def _manifest_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "resolved_path": (
            str(candidate.resolve()) if candidate.exists() else str(candidate)
        ),
        "exists": candidate.exists() and candidate.is_file(),
        "sha256": (
            sha256_file(candidate)
            if candidate.exists() and candidate.is_file()
            else None
        ),
        "hash_algorithm": "sha256",
    }


def _iter_manifest_paths(root: Path) -> Iterable[Path]:
    if root.exists() and root.is_file() and root.name == "manifest.json":
        yield root
        return
    if root.exists() and root.is_dir():
        direct = root / "manifest.json"
        if direct.exists() and direct.is_file():
            yield direct
        for manifest_path in sorted(root.rglob("manifest.json")):
            if manifest_path != direct:
                yield manifest_path


def _unit_key(unit: Mapping[str, Any]) -> tuple[str, str]:
    return str(unit.get("candidate_id", "")), str(unit.get("kernel_id", ""))


def _discovered_flow_row(
    manifest_path: Path, *, root: Path, packet_unit_keys: set[tuple[str, str]]
) -> Dict[str, Any]:
    manifest = _load_json(manifest_path)
    candidate_id, kernel_id = _manifest_identity(manifest)
    key = (candidate_id, kernel_id)
    source_flow_dir = manifest_path.parent
    blockers: list[Dict[str, str]] = []
    if not candidate_id:
        blockers.append(
            {
                "blocker_id": "source_flow_candidate_id_missing",
                "message": "Source-flow manifest.json must declare candidate_id, release_candidate_id, or architecture_candidate_id.",
            }
        )
    if not kernel_id:
        blockers.append(
            {
                "blocker_id": "source_flow_kernel_id_missing",
                "message": "Source-flow manifest.json must declare kernel_id or major_kernel_id.",
            }
        )
    if candidate_id and kernel_id and key not in packet_unit_keys:
        blockers.append(
            {
                "blocker_id": "source_flow_not_in_packet_index",
                "message": "Source-flow manifest candidate/kernel identity is not present in the closure packet index.",
            }
        )
    status = (
        "candidate_kernel_source_flow_discovered"
        if not blockers
        else "blocked_invalid_or_orphan_source_flow"
    )
    return {
        "status": status,
        "candidate_id": candidate_id or None,
        "kernel_id": kernel_id or None,
        "source_flow_dir": str(source_flow_dir),
        "source_flow_resolved_dir": (
            str(source_flow_dir.resolve())
            if source_flow_dir.exists()
            else str(source_flow_dir)
        ),
        "source_flow_root": str(root),
        "manifest_schema_version": manifest.get("schema_version"),
        "manifest_ref": _manifest_ref(manifest_path),
        "blocker_ids": [item["blocker_id"] for item in blockers],
        "blockers": blockers,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _flow_entry(row: Mapping[str, Any]) -> Dict[str, str]:
    source_ref = (
        row.get("source_flow_ref", {})
        if isinstance(row.get("source_flow_ref", {}), Mapping)
        else {}
    )
    return {
        "candidate_id": str(row.get("candidate_id", "")),
        "kernel_id": str(row.get("kernel_id", "")),
        "source_flow_dir": str(row.get("source_flow_dir", "")),
        "source_flow_resolved_dir": str(
            row.get("source_flow_resolved_dir") or source_ref.get("resolved_path") or ""
        ),
    }


def _row_for_unit(
    unit: Mapping[str, Any], matches: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        **dict(unit),
        "source_flow_mapped": False,
        "source_flow_map_eligible": False,
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
            "status": _MISSING_UNIT_STATUS,
            "blocker_ids": ["missing_source_flow_dir"],
            "blockers": [
                {
                    "blocker_id": "missing_source_flow_dir",
                    "message": "No generated source-flow directory with matching candidate_id/kernel_id manifest was found.",
                }
            ],
        }
    if len(matches) > 1:
        return {
            **base,
            "status": _DUPLICATE_UNIT_STATUS,
            "source_flow_candidates": [_flow_entry(row) for row in matches],
            "blocker_ids": ["duplicate_source_flow_dirs_for_unit"],
            "blockers": [
                {
                    "blocker_id": "duplicate_source_flow_dirs_for_unit",
                    "message": "Multiple generated source-flow directories declare the same packetized candidate_id/kernel_id.",
                }
            ],
        }
    match = matches[0]
    source_flow_dir = Path(str(match.get("source_flow_dir", "")))
    manifest_ref = (
        match.get("manifest_ref", {})
        if isinstance(match.get("manifest_ref", {}), Mapping)
        else {}
    )
    return {
        **base,
        "status": _MAPPED_UNIT_STATUS,
        "source_flow_mapped": True,
        "source_flow_map_eligible": True,
        "source_flow_dir": str(source_flow_dir),
        "source_flow_resolved_dir": (
            str(source_flow_dir.resolve())
            if source_flow_dir.exists()
            else str(source_flow_dir)
        ),
        "source_flow_ref": _directory_ref(source_flow_dir),
        "manifest_ref": dict(manifest_ref),
        "manifest_candidate_id": str(match.get("candidate_id", "")),
        "manifest_kernel_id": str(match.get("kernel_id", "")),
    }


def build_dft_hardware_closure_source_flow_map(
    *,
    closure_packet_index_path: Path,
    source_flow_roots: Sequence[Path],
) -> Dict[str, Any]:
    """Discover source-flow directories and build a fail-closed map artifact."""

    packet_index_path = Path(closure_packet_index_path)
    packet_index, units, packet_errors = _all_units(packet_index_path)
    packet_unit_keys = {_unit_key(unit) for unit in units}
    root_refs = [_directory_ref(Path(root)) for root in source_flow_roots]

    discovered_rows: list[Dict[str, Any]] = []
    seen_manifest_paths: set[Path] = set()
    for root in source_flow_roots:
        root_path = Path(root)
        for manifest_path in _iter_manifest_paths(root_path):
            resolved_manifest = manifest_path.resolve()
            if resolved_manifest in seen_manifest_paths:
                continue
            seen_manifest_paths.add(resolved_manifest)
            discovered_rows.append(
                _discovered_flow_row(
                    manifest_path, root=root_path, packet_unit_keys=packet_unit_keys
                )
            )

    valid_discovered_by_key: Dict[tuple[str, str], list[Dict[str, Any]]] = {}
    for row in discovered_rows:
        if row.get("status") != "candidate_kernel_source_flow_discovered":
            continue
        key = (str(row.get("candidate_id", "")), str(row.get("kernel_id", "")))
        valid_discovered_by_key.setdefault(key, []).append(row)

    unit_rows = [
        _row_for_unit(unit, valid_discovered_by_key.get(_unit_key(unit), []))
        for unit in units
    ]
    mapped_unit_count = sum(
        1 for row in unit_rows if row.get("source_flow_mapped") is True
    )
    missing_unit_count = sum(
        1 for row in unit_rows if row.get("status") == _MISSING_UNIT_STATUS
    )
    duplicate_unit_count = sum(
        1 for row in unit_rows if row.get("status") == _DUPLICATE_UNIT_STATUS
    )
    blocked_unit_count = sum(
        1 for row in unit_rows if row.get("source_flow_mapped") is not True
    )
    invalid_manifest_count = sum(
        1
        for row in discovered_rows
        if "source_flow_candidate_id_missing" in row.get("blocker_ids", [])
        or "source_flow_kernel_id_missing" in row.get("blocker_ids", [])
    )
    orphan_source_flow_count = sum(
        1
        for row in discovered_rows
        if "source_flow_not_in_packet_index" in row.get("blocker_ids", [])
    )
    root_missing_count = sum(1 for ref in root_refs if ref.get("exists") is not True)
    flows = [
        _flow_entry(row) for row in unit_rows if row.get("source_flow_mapped") is True
    ]

    if packet_errors or not units:
        status = _INVALID_PACKET_STATUS
    elif mapped_unit_count == len(unit_rows) and duplicate_unit_count == 0:
        status = _READY_STATUS
    elif mapped_unit_count:
        status = _PARTIAL_STATUS
    else:
        status = _EMPTY_STATUS

    return {
        "schema_version": DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_SCHEMA,
        "status": status,
        "source_artifacts": {
            "closure_packet_index": _source_ref(packet_index_path),
            "source_flow_roots": root_refs,
        },
        "release_id": packet_index.get("release_id"),
        "candidate_count": packet_index.get("candidate_count"),
        "major_kernel_count": packet_index.get("major_kernel_count"),
        "planned_unit_count": len(unit_rows),
        "unit_count": len(unit_rows),
        "source_flow_mapped_count": mapped_unit_count,
        "source_flow_missing_count": missing_unit_count,
        "blocked_unit_count": blocked_unit_count,
        "duplicate_unit_count": duplicate_unit_count,
        "root_missing_count": root_missing_count,
        "discovered_source_flow_count": len(discovered_rows),
        "invalid_manifest_count": invalid_manifest_count,
        "orphan_source_flow_count": orphan_source_flow_count,
        "error_count": len(packet_errors),
        "errors": packet_errors,
        "flows": flows,
        "units": unit_rows,
        "discovered_source_flows": discovered_rows,
        "adjudication_result": _ADJUDICATION_RESULT,
        "passed_stage_count": 0,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_source_flow_map(
    payload_or_path: Mapping[str, Any] | Path,
) -> Dict[str, Any]:
    payload = (
        _load_json(payload_or_path)
        if isinstance(payload_or_path, Path)
        else dict(payload_or_path)
    )
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_SCHEMA:
        errors.append(
            {"field": "schema_version", "message": "unexpected source-flow map schema"}
        )
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            errors.append(
                {
                    "field": field,
                    "message": "source-flow map discovery cannot upgrade claims",
                }
            )
    if payload.get("adjudication_result") != _ADJUDICATION_RESULT:
        errors.append(
            {
                "field": "adjudication_result",
                "message": "source-flow map discovery cannot adjudicate gates",
            }
        )
    if int(payload.get("passed_stage_count", 0) or 0) != 0:
        errors.append(
            {
                "field": "passed_stage_count",
                "message": "source-flow map discovery cannot pass stages",
            }
        )
    for error_index, build_error in enumerate(payload.get("errors", []) or []):
        errors.append({"field": f"errors[{error_index}]", "message": str(build_error)})

    units = payload.get("units", [])
    if not isinstance(units, list) or not units:
        errors.append(
            {
                "field": "units",
                "message": "non-empty source-flow map unit rows required",
            }
        )
        units = []
    flows = payload.get("flows", [])
    if not isinstance(flows, list):
        errors.append({"field": "flows", "message": "flows must be a list"})
        flows = []

    mapped_count = 0
    missing_count = 0
    duplicate_count = 0
    blocked_count = 0
    mapped_keys: set[tuple[str, str]] = set()
    flow_keys: set[tuple[str, str]] = set()
    for flow_index, flow in enumerate(flows):
        if not isinstance(flow, Mapping):
            errors.append(
                {
                    "field": f"flows[{flow_index}]",
                    "message": "flow row must be an object",
                }
            )
            continue
        key = (str(flow.get("candidate_id", "")), str(flow.get("kernel_id", "")))
        if not key[0] or not key[1] or not flow.get("source_flow_dir"):
            errors.append(
                {
                    "field": f"flows[{flow_index}]",
                    "message": "flow rows require candidate_id, kernel_id, and source_flow_dir",
                }
            )
        if key in flow_keys:
            errors.append(
                {"field": f"flows[{flow_index}]", "message": "duplicate flow key"}
            )
        flow_keys.add(key)

    for unit_index, unit in enumerate(units):
        if not isinstance(unit, Mapping):
            errors.append(
                {
                    "field": f"units[{unit_index}]",
                    "message": "unit row must be an object",
                }
            )
            continue
        for field in ("hardware_completion_eligible", "deliverable_complete"):
            if unit.get(field) is True:
                errors.append(
                    {
                        "field": f"units[{unit_index}].{field}",
                        "message": "unit cannot upgrade claims",
                    }
                )
        expected_files = unit.get("expected_evidence_files", [])
        if expected_files is not None and not isinstance(expected_files, list):
            errors.append(
                {
                    "field": f"units[{unit_index}].expected_evidence_files",
                    "message": "expected_evidence_files must be a list",
                }
            )
            expected_files = []
        if int(unit.get("expected_evidence_file_count", 0) or 0) != len(
            expected_files or []
        ):
            errors.append(
                {
                    "field": f"units[{unit_index}].expected_evidence_file_count",
                    "message": "expected evidence file count must match listed files",
                }
            )
        key = (str(unit.get("candidate_id", "")), str(unit.get("kernel_id", "")))
        blocker_ids = [str(item) for item in unit.get("blocker_ids", []) or []]
        source_flow_mapped = unit.get("source_flow_mapped") is True
        map_eligible = unit.get("source_flow_map_eligible") is True
        if source_flow_mapped:
            mapped_count += 1
            mapped_keys.add(key)
            if unit.get("status") != _MAPPED_UNIT_STATUS:
                errors.append(
                    {
                        "field": f"units[{unit_index}].status",
                        "message": "mapped source-flow rows must remain pending plan",
                    }
                )
            if blocker_ids:
                errors.append(
                    {
                        "field": f"units[{unit_index}].blocker_ids",
                        "message": "mapped source-flow rows cannot have blockers",
                    }
                )
            if not map_eligible:
                errors.append(
                    {
                        "field": f"units[{unit_index}].source_flow_map_eligible",
                        "message": "mapped rows must be source-flow-map eligible",
                    }
                )
            if (
                unit.get("manifest_candidate_id") != key[0]
                or unit.get("manifest_kernel_id") != key[1]
            ):
                errors.append(
                    {
                        "field": f"units[{unit_index}].manifest_identity",
                        "message": "mapped manifest identity must exactly match unit candidate_id/kernel_id",
                    }
                )
            source_ref = unit.get("source_flow_ref", {})
            manifest_ref = unit.get("manifest_ref", {})
            if (
                not isinstance(source_ref, Mapping)
                or source_ref.get("exists") is not True
            ):
                errors.append(
                    {
                        "field": f"units[{unit_index}].source_flow_ref",
                        "message": "mapped rows require an existing source-flow directory ref",
                    }
                )
            if (
                not isinstance(manifest_ref, Mapping)
                or manifest_ref.get("exists") is not True
            ):
                errors.append(
                    {
                        "field": f"units[{unit_index}].manifest_ref",
                        "message": "mapped rows require an existing manifest ref",
                    }
                )
            elif manifest_ref.get("sha256") and manifest_ref.get("resolved_path"):
                manifest_path = Path(str(manifest_ref.get("resolved_path")))
                if not manifest_path.exists() or not manifest_path.is_file():
                    errors.append(
                        {
                            "field": f"units[{unit_index}].manifest_ref.path",
                            "message": "manifest ref file must exist",
                        }
                    )
                elif manifest_ref.get("sha256") != sha256_file(manifest_path):
                    errors.append(
                        {
                            "field": f"units[{unit_index}].manifest_ref.sha256",
                            "message": "manifest hash mismatch",
                        }
                    )
        else:
            blocked_count += 1
            if map_eligible:
                errors.append(
                    {
                        "field": f"units[{unit_index}].source_flow_map_eligible",
                        "message": "blocked rows cannot be source-flow-map eligible",
                    }
                )
            if not blocker_ids:
                errors.append(
                    {
                        "field": f"units[{unit_index}].blocker_ids",
                        "message": "blocked rows must explain blockers",
                    }
                )
        if unit.get("status") == _MISSING_UNIT_STATUS:
            missing_count += 1
        if unit.get("status") == _DUPLICATE_UNIT_STATUS:
            duplicate_count += 1

    if flow_keys != mapped_keys:
        errors.append(
            {
                "field": "flows",
                "message": "flows must exactly match mapped unit candidate/kernel keys",
            }
        )

    discovered = payload.get("discovered_source_flows", [])
    if not isinstance(discovered, list):
        errors.append(
            {
                "field": "discovered_source_flows",
                "message": "discovered_source_flows must be a list",
            }
        )
        discovered = []
    invalid_manifest_count = sum(
        1
        for row in discovered
        if isinstance(row, Mapping)
        and (
            "source_flow_candidate_id_missing"
            in [str(item) for item in row.get("blocker_ids", []) or []]
            or "source_flow_kernel_id_missing"
            in [str(item) for item in row.get("blocker_ids", []) or []]
        )
    )
    orphan_count = sum(
        1
        for row in discovered
        if isinstance(row, Mapping)
        and "source_flow_not_in_packet_index"
        in [str(item) for item in row.get("blocker_ids", []) or []]
    )
    source_artifacts = (
        payload.get("source_artifacts", {})
        if isinstance(payload.get("source_artifacts", {}), Mapping)
        else {}
    )
    root_refs = (
        source_artifacts.get("source_flow_roots", [])
        if isinstance(source_artifacts.get("source_flow_roots", []), list)
        else []
    )
    root_missing_count = sum(
        1
        for ref in root_refs
        if isinstance(ref, Mapping) and ref.get("exists") is not True
    )

    expected_counts = {
        "unit_count": len(units),
        "planned_unit_count": len(units),
        "source_flow_mapped_count": mapped_count,
        "source_flow_missing_count": missing_count,
        "blocked_unit_count": blocked_count,
        "duplicate_unit_count": duplicate_count,
        "root_missing_count": root_missing_count,
        "discovered_source_flow_count": len(discovered),
        "invalid_manifest_count": invalid_manifest_count,
        "orphan_source_flow_count": orphan_count,
        "error_count": len(payload.get("errors", []) or []),
    }
    for field, expected in expected_counts.items():
        if int(payload.get(field, 0) or 0) != expected:
            errors.append(
                {"field": field, "message": f"expected {expected} from artifact rows"}
            )

    return {
        "schema_version": DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_VALIDATION_SCHEMA,
        "valid": not errors,
        "unit_count": len(units),
        "source_flow_mapped_count": mapped_count,
        "blocked_unit_count": blocked_count,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_source_flow_map(
    out_dir: Path,
    *,
    closure_packet_index_path: Path,
    source_flow_roots: Sequence[Path],
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_source_flow_map(
        closure_packet_index_path=closure_packet_index_path,
        source_flow_roots=source_flow_roots,
    )
    write_json(out_dir / "source_flow_map.json", payload)
    validation = validate_dft_hardware_closure_source_flow_map(payload)
    write_json(out_dir / "source_flow_map_validation.json", validation)
    status = {
        "schema_version": DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_STATUS_SCHEMA,
        "status": "passed" if validation["valid"] else "failed",
        "map_status": payload["status"],
        "source_flow_map": "source_flow_map.json",
        "validation": "source_flow_map_validation.json",
        "unit_count": payload["unit_count"],
        "source_flow_mapped_count": payload["source_flow_mapped_count"],
        "source_flow_missing_count": payload["source_flow_missing_count"],
        "blocked_unit_count": payload["blocked_unit_count"],
        "duplicate_unit_count": payload["duplicate_unit_count"],
        "root_missing_count": payload["root_missing_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "source_flow_map_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_SCHEMA",
    "DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_STATUS_SCHEMA",
    "DFT_HARDWARE_CLOSURE_SOURCE_FLOW_MAP_VALIDATION_SCHEMA",
    "build_dft_hardware_closure_source_flow_map",
    "validate_dft_hardware_closure_source_flow_map",
    "write_dft_hardware_closure_source_flow_map",
]
