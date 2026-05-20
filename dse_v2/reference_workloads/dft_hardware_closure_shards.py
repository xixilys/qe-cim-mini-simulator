#!/usr/bin/env python3
"""Shard DFT/QE hardware closure work into parallel execution queues.

The shard queue is an execution-management artifact derived from
``dft_hardware_completion_workplan.json``.  It groups candidate × kernel closure
units so humans or agents can assign work in parallel.  It deliberately remains
fail-closed: queueing work does not provide candidate-specific RTL/HLS bundles,
numerical correctness, Vivado/DC PPA, trusted Pareto, or completion evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_HARDWARE_CLOSURE_SHARDS_SCHEMA = "dse.dft.hardware_closure_shards.v1"
DFT_HARDWARE_CLOSURE_SHARDS_VALIDATION_SCHEMA = "dse.dft.hardware_closure_shards_validation.v1"

_CLAIM_BOUNDARY = (
    "dft_hardware_closure_shards.json is a parallel execution queue derived "
    "from the hardware completion workplan. It does not attach "
    "candidate-specific RTL/HLS bundles or real candidate-specific Vivado/DC "
    "closure evidence, and cannot upgrade hardware, numerical, Pareto, or "
    "deliverable-completion claims."
)


def _load_json(path: Path) -> Dict[str, Any]:
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


def _unit_key(item: Mapping[str, Any]) -> tuple[str, str]:
    return (str(item.get("candidate_id", "")), str(item.get("kernel_id", "")))


def _candidate_kernel_units(workplan: Mapping[str, Any]) -> list[Dict[str, Any]]:
    grouped: Dict[tuple[str, str], list[Dict[str, Any]]] = {}
    for item in workplan.get("work_items", []) or []:
        if isinstance(item, Mapping):
            grouped.setdefault(_unit_key(item), []).append(dict(item))

    units: list[Dict[str, Any]] = []
    for (candidate_id, kernel_id), items in sorted(grouped.items()):
        items = sorted(items, key=lambda row: str(row.get("stage_id", "")))
        kernel_name = str(items[0].get("kernel_name", kernel_id)) if items else kernel_id
        kernel_family = str(items[0].get("kernel_family", "")) if items else ""
        stage_ids = [str(item.get("stage_id", "")) for item in items]
        required_tools = sorted({str(item.get("tool_id")) for item in items if item.get("tool_id")})
        units.append(
            {
                "unit_id": f"{candidate_id}:{kernel_id}",
                "candidate_id": candidate_id,
                "kernel_id": kernel_id,
                "kernel_name": kernel_name,
                "kernel_family": kernel_family,
                "stage_ids": stage_ids,
                "required_tools": required_tools,
                "work_item_ids": [str(item.get("work_item_id", "")) for item in items],
                "work_item_count": len(items),
                "blocked_work_item_count": sum(1 for item in items if item.get("blocked") is True),
                "shared_microkernel_smoke_stage_count": sum(
                    1 for item in items if item.get("shared_microkernel_smoke_stage_passed") is True
                ),
                "candidate_specific_evidence_present": False,
                "candidate_specific_bundle_required": True,
                "candidate_specific_bundle_ref": None,
                "execution_status": "queued_blocked_until_candidate_specific_bundle_and_real_tool_execution",
                "claim_boundary": _CLAIM_BOUNDARY,
            }
        )
    return units


def build_dft_hardware_closure_shard_queue(
    *,
    hardware_completion_workplan_path: Path,
    max_units_per_shard: int = 16,
) -> Dict[str, Any]:
    """Return a deterministic parallel queue for candidate × kernel closure."""

    if max_units_per_shard < 1:
        raise ValueError("max_units_per_shard must be >= 1")
    workplan = _load_json(hardware_completion_workplan_path)
    units = _candidate_kernel_units(workplan)
    shards: list[Dict[str, Any]] = []
    for shard_index, start in enumerate(range(0, len(units), max_units_per_shard)):
        shard_units = units[start : start + max_units_per_shard]
        candidate_ids = sorted({unit["candidate_id"] for unit in shard_units})
        kernel_ids = sorted({unit["kernel_id"] for unit in shard_units})
        required_tools = sorted({tool for unit in shard_units for tool in unit.get("required_tools", [])})
        shards.append(
            {
                "shard_id": f"dft_hardware_closure_shard_{shard_index:04d}",
                "execution_lane": f"parallel_lane_{shard_index % max(1, min(8, len(shard_units))):02d}",
                "candidate_ids": candidate_ids,
                "kernel_ids": kernel_ids,
                "required_tools": required_tools,
                "unit_count": len(shard_units),
                "work_item_count": sum(int(unit["work_item_count"]) for unit in shard_units),
                "blocked_work_item_count": sum(int(unit["blocked_work_item_count"]) for unit in shard_units),
                "candidate_specific_bundle_count": 0,
                "execution_status": "queued_blocked_until_candidate_specific_bundle_and_real_tool_execution",
                "units": shard_units,
                "claim_boundary": _CLAIM_BOUNDARY,
            }
        )

    return {
        "schema_version": DFT_HARDWARE_CLOSURE_SHARDS_SCHEMA,
        "status": "queued_fail_closed" if shards else "failed_empty_workplan",
        "source_artifacts": {
            "hardware_completion_workplan": _source_ref(hardware_completion_workplan_path),
        },
        "release_id": workplan.get("release_id"),
        "candidate_count": workplan.get("candidate_count"),
        "major_kernel_count": workplan.get("major_kernel_count"),
        "unit_count": len(units),
        "shard_count": len(shards),
        "max_units_per_shard": max_units_per_shard,
        "work_item_count": sum(int(unit["work_item_count"]) for unit in units),
        "blocked_work_item_count": sum(int(unit["blocked_work_item_count"]) for unit in units),
        "candidate_specific_bundle_count": 0,
        "candidate_specific_evidence_present_count": 0,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "shards": shards,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_shard_queue(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    if isinstance(payload_or_path, Path):
        payload = _load_json(payload_or_path)
    else:
        payload = dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    shards = payload.get("shards", [])
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_SHARDS_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected hardware closure shard schema"})
    if not isinstance(shards, list) or not shards:
        errors.append({"field": "shards", "message": "non-empty shards required"})
        shards = []
    seen_shards: set[str] = set()
    seen_units: set[str] = set()
    for shard_index, shard in enumerate(shards):
        if not isinstance(shard, Mapping):
            errors.append({"field": f"shards[{shard_index}]", "message": "shard must be an object"})
            continue
        shard_id = str(shard.get("shard_id", ""))
        if not shard_id:
            errors.append({"field": f"shards[{shard_index}].shard_id", "message": "shard_id required"})
        if shard_id in seen_shards:
            errors.append({"field": f"shards[{shard_index}].shard_id", "message": "duplicate shard_id"})
        seen_shards.add(shard_id)
        if shard.get("candidate_specific_bundle_count") not in (0, None):
            errors.append({"field": f"shards[{shard_index}].candidate_specific_bundle_count", "message": "shard queue cannot fabricate candidate-specific bundles"})
        units = shard.get("units", [])
        if not isinstance(units, list) or not units:
            errors.append({"field": f"shards[{shard_index}].units", "message": "non-empty shard units required"})
            continue
        for unit_index, unit in enumerate(units):
            if not isinstance(unit, Mapping):
                errors.append({"field": f"shards[{shard_index}].units[{unit_index}]", "message": "unit must be an object"})
                continue
            unit_id = str(unit.get("unit_id", ""))
            if not unit_id:
                errors.append({"field": f"shards[{shard_index}].units[{unit_index}].unit_id", "message": "unit_id required"})
            if unit_id in seen_units:
                errors.append({"field": f"shards[{shard_index}].units[{unit_index}].unit_id", "message": "duplicate unit_id"})
            seen_units.add(unit_id)
            if unit.get("candidate_specific_evidence_present") is True or unit.get("candidate_specific_bundle_ref"):
                errors.append({"field": f"shards[{shard_index}].units[{unit_index}]", "message": "queued unit cannot contain candidate-specific evidence yet"})
            if unit.get("blocked_work_item_count", 0) != unit.get("work_item_count", 0):
                errors.append({"field": f"shards[{shard_index}].units[{unit_index}].blocked_work_item_count", "message": "all queued work items must remain blocked"})
    if payload.get("hardware_completion_eligible") is True or payload.get("deliverable_complete") is True:
        errors.append({"field": "hardware_completion_eligible", "message": "closure shard queue cannot be completion evidence"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_SHARDS_VALIDATION_SCHEMA,
        "valid": not errors,
        "shard_count": len(shards),
        "unit_count": len(seen_units),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_shard_queue(
    out_dir: Path,
    *,
    hardware_completion_workplan_path: Path,
    max_units_per_shard: int = 16,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_shard_queue(
        hardware_completion_workplan_path=hardware_completion_workplan_path,
        max_units_per_shard=max_units_per_shard,
    )
    write_json(out_dir / "dft_hardware_closure_shards.json", payload)
    validation = validate_dft_hardware_closure_shard_queue(payload)
    write_json(out_dir / "dft_hardware_closure_shards_validation.json", validation)
    status = {
        "schema_version": "dse.dft.hardware_closure_shards_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "shards": "dft_hardware_closure_shards.json",
        "validation": "dft_hardware_closure_shards_validation.json",
        "shard_count": payload["shard_count"],
        "unit_count": payload["unit_count"],
        "work_item_count": payload["work_item_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_shards_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_SHARDS_SCHEMA",
    "DFT_HARDWARE_CLOSURE_SHARDS_VALIDATION_SCHEMA",
    "build_dft_hardware_closure_shard_queue",
    "validate_dft_hardware_closure_shard_queue",
    "write_dft_hardware_closure_shard_queue",
]
