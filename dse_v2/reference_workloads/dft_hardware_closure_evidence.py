#!/usr/bin/env python3
"""Fail-closed intake for DFT/QE hardware closure evidence files.

The intake reads a closure packet index, opens each packet JSON, and checks
whether the expected candidate-specific bundle/evidence files exist under an
evidence root.  It is a presence/provenance gate only: even a fully populated
intake does not adjudicate numerical correctness, Vivado/DC PPA, trusted Pareto,
or deliverable completion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_SCHEMA = "dse.dft.hardware_closure_evidence_intake.v1"
DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_VALIDATION_SCHEMA = "dse.dft.hardware_closure_evidence_intake_validation.v1"

_CLAIM_BOUNDARY = (
    "dft_hardware_closure_evidence_intake.json checks candidate-specific "
    "bundle/evidence file presence against closure packets. It does not parse "
    "or adjudicate numerical correctness, Vivado FPGA implementation, DC ASIC "
    "timing/area, trusted Pareto, or deliverable completion."
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


def _safe_child_path(root: Path, rel_path: Any) -> tuple[Path | None, str | None]:
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


def _file_ref(root: Path, rel_path: Any) -> Dict[str, Any]:
    rel = str(rel_path or "")
    candidate, error = _safe_child_path(root, rel)
    exists = candidate is not None and candidate.exists() and candidate.is_file()
    return {
        "path": rel,
        "exists": exists,
        "sha256": sha256_file(candidate) if exists else None,
        "hash_algorithm": "sha256",
        "path_valid": error is None,
        "path_error": error,
    }


def _packet_path(packet_index_path: Path, ref: Mapping[str, Any]) -> Path:
    rel = str(ref.get("path", ""))
    candidate, _error = _safe_child_path(packet_index_path.parent, rel)
    return candidate or (packet_index_path.parent / "__invalid_packet_path__")


def _unit_intake_row(evidence_root: Path, unit: Mapping[str, Any]) -> Dict[str, Any]:
    candidate_bundle = _file_ref(evidence_root, unit.get("candidate_bundle_json"))
    expected_rows = []
    for expected in unit.get("expected_evidence_files", []) or []:
        if not isinstance(expected, Mapping):
            continue
        file_ref = _file_ref(evidence_root, expected.get("path"))
        expected_rows.append(
            {
                "stage_id": str(expected.get("stage_id", "")),
                "path": file_ref["path"],
                "required": bool(expected.get("required", True)),
                "exists": file_ref["exists"],
                "sha256": file_ref["sha256"],
                "hash_algorithm": file_ref["hash_algorithm"],
                "path_valid": file_ref["path_valid"],
                "path_error": file_ref["path_error"],
                "claim_role": expected.get("claim_role"),
            }
        )
    required_rows = [row for row in expected_rows if row.get("required")]
    missing = [row["path"] for row in required_rows if not row.get("exists")]
    present = [row["path"] for row in required_rows if row.get("exists")]
    bundle_missing = not candidate_bundle["exists"]
    status = "blocked_missing_candidate_bundle_or_evidence" if missing or bundle_missing else "files_present_unadjudicated"
    return {
        "unit_id": str(unit.get("unit_id", "")),
        "candidate_id": str(unit.get("candidate_id", "")),
        **{
            field: (
                dict(unit.get(field, {}))
                if isinstance(unit.get(field), Mapping)
                else unit.get(field)
            )
            for field in _CANDIDATE_METADATA_FIELDS
            if unit.get(field) not in (None, {}, [])
        },
        "kernel_id": str(unit.get("kernel_id", "")),
        "kernel_name": str(unit.get("kernel_name", unit.get("kernel_id", ""))),
        "stage_ids": [str(item) for item in unit.get("stage_ids", []) or []],
        "candidate_bundle": candidate_bundle,
        "candidate_bundle_present": candidate_bundle["exists"],
        "candidate_bundle_path_valid": candidate_bundle["path_valid"],
        "expected_evidence_file_count": len(required_rows),
        "present_evidence_file_count": len(present),
        "missing_evidence_file_count": len(missing),
        "missing_evidence_files": missing,
        "expected_evidence_files": expected_rows,
        "status": status,
        "adjudication_status": "not_adjudicated_by_intake",
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_hardware_closure_evidence_intake(
    *,
    closure_packet_index_path: Path,
    evidence_root: Path | None = None,
) -> Dict[str, Any]:
    """Return a fail-closed presence ledger for closure packet evidence."""

    packet_index_path = Path(closure_packet_index_path)
    evidence_root = Path(evidence_root or packet_index_path.parent)
    packet_index = _load_json(packet_index_path)
    packet_rows: list[Dict[str, Any]] = []
    for packet_summary in packet_index.get("packets", []) or []:
        if not isinstance(packet_summary, Mapping):
            continue
        packet_json_ref = packet_summary.get("packet_json", {})
        if not isinstance(packet_json_ref, Mapping):
            packet_json_ref = {}
        packet_path = _packet_path(packet_index_path, packet_json_ref)
        packet = _load_json(packet_path)
        unit_rows = [
            _unit_intake_row(evidence_root, unit)
            for unit in packet.get("units", []) or []
            if isinstance(unit, Mapping)
        ]
        missing_count = sum(int(row["missing_evidence_file_count"]) for row in unit_rows)
        present_count = sum(int(row["present_evidence_file_count"]) for row in unit_rows)
        packet_rows.append(
            {
                "packet_id": packet.get("packet_id", packet_summary.get("packet_id")),
                "shard_id": packet.get("shard_id", packet_summary.get("shard_id")),
                "packet_json": _source_ref(packet_path),
                "status": "blocked_missing_candidate_bundle_or_evidence" if any(row["status"].startswith("blocked") for row in unit_rows) else "files_present_unadjudicated",
                "unit_count": len(unit_rows),
                "expected_evidence_file_count": sum(int(row["expected_evidence_file_count"]) for row in unit_rows),
                "present_evidence_file_count": present_count,
                "missing_evidence_file_count": missing_count,
                "candidate_bundle_count": sum(1 for row in unit_rows if row.get("candidate_bundle_present")),
                "unit_rows": unit_rows,
                "adjudication_status": "not_adjudicated_by_intake",
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
                "claim_boundary": _CLAIM_BOUNDARY,
            }
        )
    expected_count = sum(int(row["expected_evidence_file_count"]) for row in packet_rows)
    present_count = sum(int(row["present_evidence_file_count"]) for row in packet_rows)
    missing_count = sum(int(row["missing_evidence_file_count"]) for row in packet_rows)
    bundle_count = sum(int(row["candidate_bundle_count"]) for row in packet_rows)
    status = "blocked_missing_candidate_bundle_or_evidence" if missing_count or bundle_count < sum(int(row["unit_count"]) for row in packet_rows) else "files_present_unadjudicated"
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_SCHEMA,
        "status": status if packet_rows else "failed_empty_packet_index",
        "source_artifacts": {"closure_packet_index": _source_ref(packet_index_path)},
        "evidence_root": str(evidence_root),
        "release_id": packet_index.get("release_id"),
        "candidate_count": packet_index.get("candidate_count"),
        "major_kernel_count": packet_index.get("major_kernel_count"),
        "packet_count": len(packet_rows),
        "unit_count": sum(int(row["unit_count"]) for row in packet_rows),
        "expected_evidence_file_count": expected_count,
        "present_evidence_file_count": present_count,
        "missing_evidence_file_count": missing_count,
        "candidate_bundle_count": bundle_count,
        "adjudication_status": "not_adjudicated_by_intake",
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "packets": packet_rows,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_evidence_intake(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    if isinstance(payload_or_path, Path):
        payload = _load_json(payload_or_path)
    else:
        payload = dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected closure evidence intake schema"})
    packets = payload.get("packets", [])
    if not isinstance(packets, list) or not packets:
        errors.append({"field": "packets", "message": "non-empty packet intake rows required"})
        packets = []
    if payload.get("hardware_completion_eligible") is True or payload.get("deliverable_complete") is True:
        errors.append({"field": "hardware_completion_eligible", "message": "intake cannot be hardware-completion or deliverable-complete evidence"})
    if payload.get("adjudication_status") != "not_adjudicated_by_intake":
        errors.append({"field": "adjudication_status", "message": "intake must not adjudicate hard gates"})
    seen_packets: set[str] = set()
    for packet_index, packet in enumerate(packets):
        if not isinstance(packet, Mapping):
            errors.append({"field": f"packets[{packet_index}]", "message": "packet row must be an object"})
            continue
        packet_id = str(packet.get("packet_id", ""))
        if not packet_id:
            errors.append({"field": f"packets[{packet_index}].packet_id", "message": "packet_id required"})
        if packet_id in seen_packets:
            errors.append({"field": f"packets[{packet_index}].packet_id", "message": "duplicate packet_id"})
        seen_packets.add(packet_id)
        for field in ("hardware_completion_eligible", "deliverable_complete"):
            if packet.get(field) is True:
                errors.append({"field": f"packets[{packet_index}].{field}", "message": "packet intake cannot upgrade claims"})
        if packet.get("adjudication_status") != "not_adjudicated_by_intake":
            errors.append({"field": f"packets[{packet_index}].adjudication_status", "message": "packet intake must not adjudicate gates"})
        units = packet.get("unit_rows", [])
        if not isinstance(units, list) or not units:
            errors.append({"field": f"packets[{packet_index}].unit_rows", "message": "non-empty unit rows required"})
            continue
        for unit_index, unit in enumerate(units):
            if not isinstance(unit, Mapping):
                errors.append({"field": f"packets[{packet_index}].unit_rows[{unit_index}]", "message": "unit row must be an object"})
                continue
            for field in ("hardware_completion_eligible", "deliverable_complete"):
                if unit.get(field) is True:
                    errors.append({"field": f"packets[{packet_index}].unit_rows[{unit_index}].{field}", "message": "unit intake cannot upgrade claims"})
            if unit.get("adjudication_status") != "not_adjudicated_by_intake":
                errors.append({"field": f"packets[{packet_index}].unit_rows[{unit_index}].adjudication_status", "message": "unit intake must not adjudicate gates"})
            bundle_ref = unit.get("candidate_bundle", {})
            if isinstance(bundle_ref, Mapping) and bundle_ref.get("path_valid") is False:
                errors.append({"field": f"packets[{packet_index}].unit_rows[{unit_index}].candidate_bundle.path", "message": "candidate bundle path must stay inside evidence root"})
            expected_files = unit.get("expected_evidence_files", [])
            if not isinstance(expected_files, list):
                errors.append({"field": f"packets[{packet_index}].unit_rows[{unit_index}].expected_evidence_files", "message": "expected evidence rows must be a list"})
                continue
            for expected_index, expected in enumerate(expected_files):
                if not isinstance(expected, Mapping):
                    errors.append({"field": f"packets[{packet_index}].unit_rows[{unit_index}].expected_evidence_files[{expected_index}]", "message": "expected evidence row must be an object"})
                    continue
                if expected.get("path_valid") is False:
                    errors.append({"field": f"packets[{packet_index}].unit_rows[{unit_index}].expected_evidence_files[{expected_index}].path", "message": "expected evidence path must stay inside evidence root"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_VALIDATION_SCHEMA,
        "valid": not errors,
        "packet_count": len(packets),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_evidence_intake(
    out_dir: Path,
    *,
    closure_packet_index_path: Path,
    evidence_root: Path | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_evidence_intake(
        closure_packet_index_path=closure_packet_index_path,
        evidence_root=evidence_root,
    )
    write_json(out_dir / "dft_hardware_closure_evidence_intake.json", payload)
    validation = validate_dft_hardware_closure_evidence_intake(payload)
    write_json(out_dir / "dft_hardware_closure_evidence_intake_validation.json", validation)
    status = {
        "schema_version": "dse.dft.hardware_closure_evidence_intake_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "intake": "dft_hardware_closure_evidence_intake.json",
        "validation": "dft_hardware_closure_evidence_intake_validation.json",
        "packet_count": payload["packet_count"],
        "unit_count": payload["unit_count"],
        "expected_evidence_file_count": payload["expected_evidence_file_count"],
        "present_evidence_file_count": payload["present_evidence_file_count"],
        "missing_evidence_file_count": payload["missing_evidence_file_count"],
        "candidate_bundle_count": payload["candidate_bundle_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_evidence_intake_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_SCHEMA",
    "DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_VALIDATION_SCHEMA",
    "build_dft_hardware_closure_evidence_intake",
    "validate_dft_hardware_closure_evidence_intake",
    "write_dft_hardware_closure_evidence_intake",
]
