#!/usr/bin/env python3
"""Fail-closed DFT/QE hardware closure adjudication ledger.

This layer sits after evidence-file intake.  It turns per-unit expected-file
presence into explicit stage-level hard-gate adjudication rows.  Until later
lanes attach parsed candidate-specific correctness, simulation, synthesis,
Vivado, and DC results, every stage remains blocked or unadjudicated and no
hardware/Pareto/deliverable claim can be upgraded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_HARDWARE_CLOSURE_ADJUDICATION_SCHEMA = "dse.dft.hardware_closure_adjudication.v1"
DFT_HARDWARE_CLOSURE_ADJUDICATION_VALIDATION_SCHEMA = "dse.dft.hardware_closure_adjudication_validation.v1"

_REQUIRED_STAGE_ORDER = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)

_STAGE_CLAIM_ROLE = {
    "golden_correctness": "candidate_specific_numerical_correctness_gate",
    "hls_or_rtl_sim": "candidate_specific_hls_csim_or_rtl_sim_gate",
    "hls_or_rtl_synth": "candidate_specific_hls_cynth_or_rtl_synth_gate",
    "vivado_fpga_synth_or_impl": "candidate_specific_fpga_claim_gate",
    "dc_asic_synth_timing_area": "candidate_specific_asic_claim_gate",
}

_CLAIM_BOUNDARY = (
    "dft_hardware_closure_adjudication.json is a fail-closed stage ledger. It "
    "does not parse or certify numerical correctness, VCS/HLS simulation, HLS/RTL "
    "synthesis, Vivado FPGA implementation, DC ASIC timing/area, trusted Pareto, "
    "or deliverable completion unless later candidate-specific parsed evidence "
    "rows are attached and independently validated."
)

_CANDIDATE_METADATA_FIELDS = (
    "design_candidate_id",
    "assignments",
    "identity_assignments",
    "non_identity_assignments",
    "applicability_assignments",
    "evaluation_policy_assignments",
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


def _group_files_by_stage(unit_row: Mapping[str, Any]) -> Dict[str, list[Mapping[str, Any]]]:
    grouped: Dict[str, list[Mapping[str, Any]]] = {stage_id: [] for stage_id in _REQUIRED_STAGE_ORDER}
    for item in unit_row.get("expected_evidence_files", []) or []:
        if not isinstance(item, Mapping):
            continue
        stage_id = str(item.get("stage_id", ""))
        if stage_id in grouped:
            grouped[stage_id].append(item)
    return grouped


def _stage_row(unit_row: Mapping[str, Any], stage_id: str, files: list[Mapping[str, Any]]) -> Dict[str, Any]:
    required_files = [item for item in files if item.get("required", True)]
    present_files = [item for item in required_files if item.get("exists") is True]
    missing_files = [str(item.get("path", "")) for item in required_files if item.get("exists") is not True]
    candidate_bundle_present = bool(unit_row.get("candidate_bundle_present", False))
    if not candidate_bundle_present:
        status = "blocked_missing_candidate_bundle"
        blocker_id = "candidate_specific_bundle_missing"
    elif missing_files:
        status = "blocked_missing_stage_evidence_files"
        blocker_id = "candidate_specific_stage_evidence_files_missing"
    else:
        status = "files_present_waiting_for_parsed_adjudication"
        blocker_id = "parsed_stage_adjudication_missing"
    return {
        "stage_id": stage_id,
        "claim_role": _STAGE_CLAIM_ROLE[stage_id],
        "required_file_count": len(required_files),
        "present_file_count": len(present_files),
        "missing_file_count": len(missing_files),
        "missing_files": missing_files,
        "candidate_bundle_present": candidate_bundle_present,
        "parsed_result_present": False,
        "parsed_result_ref": None,
        "status": status,
        "blocker_id": blocker_id,
        "adjudication_result": "not_adjudicated",
        "passed": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _unit_row(packet_row: Mapping[str, Any], unit_row: Mapping[str, Any]) -> Dict[str, Any]:
    grouped = _group_files_by_stage(unit_row)
    stage_rows = [_stage_row(unit_row, stage_id, grouped[stage_id]) for stage_id in _REQUIRED_STAGE_ORDER]
    missing_stage_count = sum(1 for row in stage_rows if row["missing_file_count"] or not row["candidate_bundle_present"])
    files_present_unadjudicated_count = sum(1 for row in stage_rows if row["status"] == "files_present_waiting_for_parsed_adjudication")
    if missing_stage_count:
        status = "blocked_missing_candidate_bundle_or_stage_evidence"
    elif files_present_unadjudicated_count == len(stage_rows):
        status = "files_present_waiting_for_parsed_adjudication"
    else:
        status = "blocked_waiting_for_stage_adjudication"
    return {
        "packet_id": packet_row.get("packet_id"),
        "shard_id": packet_row.get("shard_id"),
        "unit_id": str(unit_row.get("unit_id", "")),
        "candidate_id": str(unit_row.get("candidate_id", "")),
        **{
            field: (
                dict(unit_row.get(field, {}))
                if isinstance(unit_row.get(field), Mapping)
                else unit_row.get(field)
            )
            for field in _CANDIDATE_METADATA_FIELDS
            if unit_row.get(field) not in (None, {}, [])
        },
        "kernel_id": str(unit_row.get("kernel_id", "")),
        "kernel_name": str(unit_row.get("kernel_name", unit_row.get("kernel_id", ""))),
        "stage_count": len(stage_rows),
        "passed_stage_count": 0,
        "blocked_stage_count": sum(1 for row in stage_rows if row["status"].startswith("blocked")),
        "files_present_unadjudicated_stage_count": files_present_unadjudicated_count,
        "expected_evidence_file_count": sum(int(row["required_file_count"]) for row in stage_rows),
        "present_evidence_file_count": sum(int(row["present_file_count"]) for row in stage_rows),
        "missing_evidence_file_count": sum(int(row["missing_file_count"]) for row in stage_rows),
        "candidate_bundle_present": bool(unit_row.get("candidate_bundle_present", False)),
        "status": status,
        "adjudication_result": "not_adjudicated",
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "stage_rows": stage_rows,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_hardware_closure_adjudication(
    *,
    closure_evidence_intake_path: Path,
) -> Dict[str, Any]:
    """Return a fail-closed stage adjudication ledger from evidence intake."""

    intake_path = Path(closure_evidence_intake_path)
    intake = _load_json(intake_path)
    units: list[Dict[str, Any]] = []
    for packet in intake.get("packets", []) or []:
        if not isinstance(packet, Mapping):
            continue
        units.extend(
            _unit_row(packet, unit)
            for unit in packet.get("unit_rows", []) or []
            if isinstance(unit, Mapping)
        )
    stage_rows = [stage for unit in units for stage in unit.get("stage_rows", [])]
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_ADJUDICATION_SCHEMA,
        "status": "blocked_missing_candidate_bundle_or_stage_evidence" if units else "failed_empty_evidence_intake",
        "source_artifacts": {"closure_evidence_intake": _source_ref(intake_path)},
        "release_id": intake.get("release_id"),
        "candidate_count": intake.get("candidate_count"),
        "major_kernel_count": intake.get("major_kernel_count"),
        "packet_count": intake.get("packet_count"),
        "unit_count": len(units),
        "stage_count": len(stage_rows),
        "passed_stage_count": 0,
        "blocked_stage_count": sum(1 for row in stage_rows if str(row.get("status", "")).startswith("blocked")),
        "files_present_unadjudicated_stage_count": sum(1 for row in stage_rows if row.get("status") == "files_present_waiting_for_parsed_adjudication"),
        "expected_evidence_file_count": sum(int(unit["expected_evidence_file_count"]) for unit in units),
        "present_evidence_file_count": sum(int(unit["present_evidence_file_count"]) for unit in units),
        "missing_evidence_file_count": sum(int(unit["missing_evidence_file_count"]) for unit in units),
        "candidate_bundle_count": sum(1 for unit in units if unit.get("candidate_bundle_present")),
        "adjudication_result": "not_adjudicated",
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "unit_rows": units,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_adjudication(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    if isinstance(payload_or_path, Path):
        payload = _load_json(payload_or_path)
    else:
        payload = dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_ADJUDICATION_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected closure adjudication schema"})
    units = payload.get("unit_rows", [])
    if not isinstance(units, list) or not units:
        errors.append({"field": "unit_rows", "message": "non-empty unit rows required"})
        units = []
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            errors.append({"field": field, "message": "adjudication scaffold cannot upgrade claims"})
    if payload.get("adjudication_result") != "not_adjudicated":
        errors.append({"field": "adjudication_result", "message": "current scaffold must remain not_adjudicated"})
    if int(payload.get("passed_stage_count", 0) or 0) != 0:
        errors.append({"field": "passed_stage_count", "message": "current scaffold cannot record passed hard gates"})
    seen_units: set[str] = set()
    for unit_index, unit in enumerate(units):
        if not isinstance(unit, Mapping):
            errors.append({"field": f"unit_rows[{unit_index}]", "message": "unit row must be an object"})
            continue
        unit_id = str(unit.get("unit_id", ""))
        if not unit_id:
            errors.append({"field": f"unit_rows[{unit_index}].unit_id", "message": "unit_id required"})
        if unit_id in seen_units:
            errors.append({"field": f"unit_rows[{unit_index}].unit_id", "message": "duplicate unit_id"})
        seen_units.add(unit_id)
        for field in ("hardware_completion_eligible", "deliverable_complete"):
            if unit.get(field) is True:
                errors.append({"field": f"unit_rows[{unit_index}].{field}", "message": "unit row cannot upgrade claims"})
        if unit.get("adjudication_result") != "not_adjudicated":
            errors.append({"field": f"unit_rows[{unit_index}].adjudication_result", "message": "unit must remain not_adjudicated"})
        stages = unit.get("stage_rows", [])
        if not isinstance(stages, list) or len(stages) != len(_REQUIRED_STAGE_ORDER):
            errors.append({"field": f"unit_rows[{unit_index}].stage_rows", "message": "all required hard-gate stage rows required"})
            stages = []
        stage_ids = [stage.get("stage_id") for stage in stages if isinstance(stage, Mapping)]
        if sorted(stage_ids) != sorted(_REQUIRED_STAGE_ORDER):
            errors.append({"field": f"unit_rows[{unit_index}].stage_rows.stage_id", "message": "stage rows must cover required hard gates"})
        for stage_index, stage in enumerate(stages):
            if not isinstance(stage, Mapping):
                errors.append({"field": f"unit_rows[{unit_index}].stage_rows[{stage_index}]", "message": "stage row must be an object"})
                continue
            if stage.get("passed") is True:
                errors.append({"field": f"unit_rows[{unit_index}].stage_rows[{stage_index}].passed", "message": "stage cannot pass without parsed evidence"})
            if stage.get("parsed_result_present") is True or stage.get("parsed_result_ref"):
                errors.append({"field": f"unit_rows[{unit_index}].stage_rows[{stage_index}].parsed_result", "message": "current scaffold cannot attach parsed results"})
            for field in ("hardware_completion_eligible", "deliverable_complete"):
                if stage.get(field) is True:
                    errors.append({"field": f"unit_rows[{unit_index}].stage_rows[{stage_index}].{field}", "message": "stage row cannot upgrade claims"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_ADJUDICATION_VALIDATION_SCHEMA,
        "valid": not errors,
        "unit_count": len(units),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_adjudication(
    out_dir: Path,
    *,
    closure_evidence_intake_path: Path,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_adjudication(
        closure_evidence_intake_path=closure_evidence_intake_path,
    )
    write_json(out_dir / "dft_hardware_closure_adjudication.json", payload)
    validation = validate_dft_hardware_closure_adjudication(payload)
    write_json(out_dir / "dft_hardware_closure_adjudication_validation.json", validation)
    status = {
        "schema_version": "dse.dft.hardware_closure_adjudication_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "adjudication": "dft_hardware_closure_adjudication.json",
        "validation": "dft_hardware_closure_adjudication_validation.json",
        "unit_count": payload["unit_count"],
        "stage_count": payload["stage_count"],
        "passed_stage_count": payload["passed_stage_count"],
        "blocked_stage_count": payload["blocked_stage_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_adjudication_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_ADJUDICATION_SCHEMA",
    "DFT_HARDWARE_CLOSURE_ADJUDICATION_VALIDATION_SCHEMA",
    "build_dft_hardware_closure_adjudication",
    "validate_dft_hardware_closure_adjudication",
    "write_dft_hardware_closure_adjudication",
]
