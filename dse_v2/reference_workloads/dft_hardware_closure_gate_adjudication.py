#!/usr/bin/env python3
"""Fail-closed hard-gate adjudication from parsed DFT/QE closure evidence.

This layer consumes ``dft_hardware_closure_parsed_evidence_manifest.json`` and
turns parser-output readiness into explicit stage-gate verdicts.  It may record
that an individual hard-gate stage passed when a valid parsed result says
``verdict=passed`` for the exact candidate/kernel/stage row, but it still does
not promote FPGA/ASIC PPA, trusted Pareto, or deliverable completion.  Release
completion remains a later all-candidates/all-kernels claim gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_SCHEMA = "dse.dft.hardware_closure_gate_adjudication.v1"
DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_VALIDATION_SCHEMA = (
    "dse.dft.hardware_closure_gate_adjudication_validation.v1"
)

_REQUIRED_STAGE_ORDER = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)

_CLAIM_BOUNDARY = (
    "dft_hardware_closure_gate_adjudication.json consumes parsed hard-gate "
    "results and records fail-closed per-stage/per-unit gate status. It may "
    "record stage_gate_passed for valid parsed 'passed' rows, but it cannot "
    "by itself certify full release completion, trusted Pareto, FPGA PPA, "
    "ASIC PPA, or deliverable completion."
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


def _stage_gate_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    parsed_present = bool(row.get("parsed_result_present", False))
    parsed_valid = bool(row.get("parsed_result_schema_valid", False))
    parsed_verdict = str(row.get("parsed_verdict", "") or "")
    if not parsed_present:
        gate_status = "blocked_missing_parsed_result"
        adjudication_result = "blocked_stage_gate"
        blocker_id = "parsed_result_missing"
        stage_gate_passed = False
    elif not parsed_valid:
        gate_status = "blocked_invalid_parsed_result"
        adjudication_result = "blocked_stage_gate"
        blocker_id = "parsed_result_schema_invalid"
        stage_gate_passed = False
    elif parsed_verdict == "passed":
        gate_status = "stage_gate_passed_pending_unit_closure"
        adjudication_result = "passed_stage_gate"
        blocker_id = None
        stage_gate_passed = True
    elif parsed_verdict == "failed":
        gate_status = "failed_parsed_result"
        adjudication_result = "failed_stage_gate"
        blocker_id = "parsed_result_failed"
        stage_gate_passed = False
    elif parsed_verdict == "inconclusive":
        gate_status = "blocked_inconclusive_parsed_result"
        adjudication_result = "blocked_stage_gate"
        blocker_id = "parsed_result_inconclusive"
        stage_gate_passed = False
    else:
        gate_status = "blocked_parser_reported_blocked_or_unknown"
        adjudication_result = "blocked_stage_gate"
        blocker_id = "parsed_result_blocked_or_unknown"
        stage_gate_passed = False
    parsed_ref = row.get("expected_parsed_result", {})
    parsed_ref = dict(parsed_ref) if isinstance(parsed_ref, Mapping) else {}
    return {
        "packet_id": row.get("packet_id"),
        "shard_id": row.get("shard_id"),
        "unit_id": row.get("unit_id"),
        "candidate_id": str(row.get("candidate_id", "")),
        "kernel_id": str(row.get("kernel_id", "")),
        "kernel_name": row.get("kernel_name"),
        "stage_id": str(row.get("stage_id", "")),
        "tool_kind": row.get("tool_kind"),
        "parsed_result": parsed_ref,
        "parsed_result_present": parsed_present,
        "parsed_result_schema_valid": parsed_valid,
        "parsed_verdict": parsed_verdict or None,
        "parsed_blocker_ids": row.get("parsed_blocker_ids", []) if isinstance(row.get("parsed_blocker_ids", []), list) else [],
        "raw_evidence_ref_count": row.get("raw_evidence_ref_count", 0),
        "parser_id": row.get("parser_id"),
        "stage_gate_passed": stage_gate_passed,
        "status": gate_status,
        "blocker_id": blocker_id,
        "adjudication_result": adjudication_result,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _unit_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("unit_id", "")),
        str(row.get("candidate_id", "")),
        str(row.get("kernel_id", "")),
    )


def _unit_rows(stage_rows: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    grouped: Dict[tuple[str, str, str], list[Dict[str, Any]]] = {}
    for row in stage_rows:
        grouped.setdefault(_unit_key(row), []).append(row)
    units: list[Dict[str, Any]] = []
    for (unit_id, candidate_id, kernel_id), rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda item: _REQUIRED_STAGE_ORDER.index(str(item.get("stage_id"))) if item.get("stage_id") in _REQUIRED_STAGE_ORDER else 999)
        passed_count = sum(1 for row in rows if row.get("stage_gate_passed"))
        failed_count = sum(1 for row in rows if row.get("adjudication_result") == "failed_stage_gate")
        blocked_count = sum(1 for row in rows if row.get("adjudication_result") == "blocked_stage_gate")
        all_required_present = sorted(str(row.get("stage_id")) for row in rows) == sorted(_REQUIRED_STAGE_ORDER)
        unit_gate_passed = all_required_present and passed_count == len(_REQUIRED_STAGE_ORDER)
        if failed_count:
            status = "failed_stage_gate"
            adjudication_result = "failed_unit_gate"
        elif unit_gate_passed:
            status = "all_stage_gates_passed_pending_release_claim"
            adjudication_result = "passed_unit_gate_pending_release_claim"
        else:
            status = "blocked_incomplete_stage_gates"
            adjudication_result = "blocked_unit_gate"
        units.append(
            {
                "unit_id": unit_id,
                "candidate_id": candidate_id,
                "kernel_id": kernel_id,
                "kernel_name": rows[0].get("kernel_name") if rows else None,
                "stage_count": len(rows),
                "stage_gate_passed_count": passed_count,
                "blocked_stage_count": blocked_count,
                "failed_stage_count": failed_count,
                "unit_gate_passed": unit_gate_passed,
                "status": status,
                "adjudication_result": adjudication_result,
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
                "stage_rows": rows,
                "claim_boundary": _CLAIM_BOUNDARY,
            }
        )
    return units


def build_dft_hardware_closure_gate_adjudication(
    *,
    parsed_evidence_manifest_path: Path,
) -> Dict[str, Any]:
    """Return hard-gate adjudication rows from a parsed-evidence manifest."""

    manifest_path = Path(parsed_evidence_manifest_path)
    manifest = _load_json(manifest_path)
    stage_rows = [
        _stage_gate_row(row)
        for row in manifest.get("parsed_rows", []) or []
        if isinstance(row, Mapping)
    ]
    units = _unit_rows(stage_rows)
    stage_passed_count = sum(1 for row in stage_rows if row.get("stage_gate_passed"))
    failed_stage_count = sum(1 for row in stage_rows if row.get("adjudication_result") == "failed_stage_gate")
    blocked_stage_count = sum(1 for row in stage_rows if row.get("adjudication_result") == "blocked_stage_gate")
    unit_gate_passed_count = sum(1 for unit in units if unit.get("unit_gate_passed"))
    if not stage_rows:
        status = "failed_empty_parsed_manifest"
        adjudication_result = "failed_empty_parsed_manifest"
    elif failed_stage_count:
        status = "failed_hard_gate"
        adjudication_result = "failed_hard_gate"
    elif unit_gate_passed_count == len(units) and units:
        status = "all_unit_stage_gates_passed_pending_release_claim"
        adjudication_result = "all_stage_gates_passed_pending_release_claim"
    else:
        status = "blocked_incomplete_hard_gate_evidence"
        adjudication_result = "blocked_incomplete_hard_gate_evidence"
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_SCHEMA,
        "status": status,
        "source_artifacts": {"parsed_evidence_manifest": _source_ref(manifest_path)},
        "release_id": manifest.get("release_id"),
        "candidate_count": manifest.get("candidate_count"),
        "major_kernel_count": manifest.get("major_kernel_count"),
        "packet_count": manifest.get("packet_count"),
        "unit_count": len(units),
        "stage_count": len(stage_rows),
        "stage_gate_passed_count": stage_passed_count,
        "blocked_stage_count": blocked_stage_count,
        "failed_stage_count": failed_stage_count,
        "unit_gate_passed_count": unit_gate_passed_count,
        "blocked_unit_count": sum(1 for unit in units if unit.get("adjudication_result") == "blocked_unit_gate"),
        "failed_unit_count": sum(1 for unit in units if unit.get("adjudication_result") == "failed_unit_gate"),
        "adjudication_result": adjudication_result,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "unit_rows": units,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_gate_adjudication(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    if isinstance(payload_or_path, Path):
        payload = _load_json(payload_or_path)
    else:
        payload = dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected gate adjudication schema"})
    units = payload.get("unit_rows", [])
    if not isinstance(units, list) or not units:
        errors.append({"field": "unit_rows", "message": "non-empty unit rows required"})
        units = []
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            errors.append({"field": field, "message": "gate adjudication cannot upgrade release completion claims"})
    stage_rows: list[Mapping[str, Any]] = []
    seen_stage_keys: set[tuple[str, str, str]] = set()
    for unit_index, unit in enumerate(units):
        if not isinstance(unit, Mapping):
            errors.append({"field": f"unit_rows[{unit_index}]", "message": "unit row must be an object"})
            continue
        for field in ("hardware_completion_eligible", "deliverable_complete"):
            if unit.get(field) is True:
                errors.append({"field": f"unit_rows[{unit_index}].{field}", "message": "unit row cannot upgrade release completion claims"})
        stages = unit.get("stage_rows", [])
        if not isinstance(stages, list) or len(stages) != len(_REQUIRED_STAGE_ORDER):
            errors.append({"field": f"unit_rows[{unit_index}].stage_rows", "message": "all required hard-gate stage rows required"})
            stages = []
        stage_ids = [str(stage.get("stage_id", "")) for stage in stages if isinstance(stage, Mapping)]
        if sorted(stage_ids) != sorted(_REQUIRED_STAGE_ORDER):
            errors.append({"field": f"unit_rows[{unit_index}].stage_rows.stage_id", "message": "stage rows must cover required hard gates"})
        for stage_index, stage in enumerate(stages):
            if not isinstance(stage, Mapping):
                errors.append({"field": f"unit_rows[{unit_index}].stage_rows[{stage_index}]", "message": "stage row must be an object"})
                continue
            stage_rows.append(stage)
            key = (str(stage.get("candidate_id", "")), str(stage.get("kernel_id", "")), str(stage.get("stage_id", "")))
            if key in seen_stage_keys:
                errors.append({"field": f"unit_rows[{unit_index}].stage_rows[{stage_index}]", "message": "duplicate candidate/kernel/stage row"})
            seen_stage_keys.add(key)
            for field in ("hardware_completion_eligible", "deliverable_complete"):
                if stage.get(field) is True:
                    errors.append({"field": f"unit_rows[{unit_index}].stage_rows[{stage_index}].{field}", "message": "stage row cannot upgrade release completion claims"})
            if stage.get("stage_gate_passed") is True:
                if stage.get("parsed_result_present") is not True or stage.get("parsed_result_schema_valid") is not True or stage.get("parsed_verdict") != "passed":
                    errors.append({"field": f"unit_rows[{unit_index}].stage_rows[{stage_index}].stage_gate_passed", "message": "stage pass requires a valid parsed 'passed' result"})
                if stage.get("adjudication_result") != "passed_stage_gate":
                    errors.append({"field": f"unit_rows[{unit_index}].stage_rows[{stage_index}].adjudication_result", "message": "passed stage must use passed_stage_gate result"})
    if int(payload.get("stage_gate_passed_count", 0) or 0) != sum(1 for row in stage_rows if row.get("stage_gate_passed")):
        errors.append({"field": "stage_gate_passed_count", "message": "stage pass count does not match rows"})
    if int(payload.get("unit_gate_passed_count", 0) or 0) != sum(1 for unit in units if isinstance(unit, Mapping) and unit.get("unit_gate_passed")):
        errors.append({"field": "unit_gate_passed_count", "message": "unit pass count does not match rows"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_VALIDATION_SCHEMA,
        "valid": not errors,
        "unit_count": len(units),
        "stage_count": len(stage_rows),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_gate_adjudication(
    out_dir: Path,
    *,
    parsed_evidence_manifest_path: Path,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_gate_adjudication(
        parsed_evidence_manifest_path=parsed_evidence_manifest_path,
    )
    write_json(out_dir / "dft_hardware_closure_gate_adjudication.json", payload)
    validation = validate_dft_hardware_closure_gate_adjudication(payload)
    write_json(out_dir / "dft_hardware_closure_gate_adjudication_validation.json", validation)
    status = {
        "schema_version": "dse.dft.hardware_closure_gate_adjudication_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "gate_adjudication": "dft_hardware_closure_gate_adjudication.json",
        "validation": "dft_hardware_closure_gate_adjudication_validation.json",
        "unit_count": payload["unit_count"],
        "stage_count": payload["stage_count"],
        "stage_gate_passed_count": payload["stage_gate_passed_count"],
        "blocked_stage_count": payload["blocked_stage_count"],
        "failed_stage_count": payload["failed_stage_count"],
        "unit_gate_passed_count": payload["unit_gate_passed_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_gate_adjudication_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_SCHEMA",
    "DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_VALIDATION_SCHEMA",
    "build_dft_hardware_closure_gate_adjudication",
    "validate_dft_hardware_closure_gate_adjudication",
    "write_dft_hardware_closure_gate_adjudication",
]
