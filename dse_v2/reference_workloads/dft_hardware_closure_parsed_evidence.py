#!/usr/bin/env python3
"""Fail-closed parsed-evidence manifest for DFT/QE hardware closure.

The manifest is the handoff point between raw tool/evidence files and hard-gate
adjudication.  It defines one expected parsed-result file for every
candidate×kernel×stage row in the closure adjudication ledger, validates any
present parsed result against a minimal schema, and records parser readiness.
It does not itself pass stages or upgrade hardware/Pareto/deliverable claims.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_MANIFEST_SCHEMA = "dse.dft.hardware_closure_parsed_evidence_manifest.v1"
DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_MANIFEST_VALIDATION_SCHEMA = "dse.dft.hardware_closure_parsed_evidence_manifest_validation.v1"
DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA = "dse.dft.hardware_parsed_stage_result.v1"

_STAGE_TO_TOOL_KIND = {
    "golden_correctness": "golden_reference",
    "hls_or_rtl_sim": "vcs_or_hls_csim",
    "hls_or_rtl_synth": "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl": "vivado",
    "dc_asic_synth_timing_area": "dc_shell",
}

_ALLOWED_VERDICTS = {"passed", "failed", "inconclusive", "blocked"}

_CLAIM_BOUNDARY = (
    "dft_hardware_closure_parsed_evidence_manifest.json records parsed-result "
    "file presence and schema validity for candidate-specific hard-gate rows. "
    "It is parser/readiness evidence only and cannot pass stages, certify "
    "numerical correctness, Vivado FPGA implementation, DC ASIC timing/area, "
    "trusted Pareto, or deliverable completion without a separate adjudicator."
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


def _safe_slug(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    chars = [ch if ch.isalnum() or ch in "._-" else "_" for ch in text]
    slug = "".join(chars).strip("_")
    return slug or "unknown"


def _expected_parsed_result_path(unit: Mapping[str, Any], stage: Mapping[str, Any]) -> str:
    return (
        "parsed_hard_gate_results/"
        f"{_safe_slug(unit.get('candidate_id'))}/"
        f"{_safe_slug(unit.get('kernel_id'))}/"
        f"{_safe_slug(stage.get('stage_id'))}_parsed_result.json"
    )


def _expected_parsed_result_rel_path(
    *,
    parsed_root: Path,
    unit: Mapping[str, Any],
    stage: Mapping[str, Any],
) -> str:
    """Return the parsed-result path relative to ``parsed_root``.

    ``parsed_root`` may be either the run/base directory or the canonical
    ``parsed_hard_gate_results`` directory itself.  Avoid double-prefixing the
    latter so parser-run output and parsed-evidence manifest lookup stay in
    lockstep.
    """

    rel = _expected_parsed_result_path(unit, stage)
    if Path(parsed_root).name == "parsed_hard_gate_results":
        prefix = "parsed_hard_gate_results/"
        return rel[len(prefix) :] if rel.startswith(prefix) else rel
    return rel


def _validate_parsed_stage_result(
    payload: Mapping[str, Any],
    *,
    expected_candidate_id: str,
    expected_kernel_id: str,
    expected_stage_id: str,
) -> list[Dict[str, str]]:
    errors: list[Dict[str, str]] = []
    if payload.get("schema_version") != DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected parsed stage result schema"})
    for field, expected in (
        ("candidate_id", expected_candidate_id),
        ("kernel_id", expected_kernel_id),
        ("stage_id", expected_stage_id),
    ):
        if str(payload.get(field, "")) != expected:
            errors.append({"field": field, "message": f"expected {expected}"})
    if str(payload.get("verdict", "")) not in _ALLOWED_VERDICTS:
        errors.append({"field": "verdict", "message": "verdict must be passed/failed/inconclusive/blocked"})
    raw_refs = payload.get("raw_evidence_refs", [])
    if not isinstance(raw_refs, list) or not raw_refs:
        errors.append({"field": "raw_evidence_refs", "message": "non-empty raw evidence refs required"})
    if not payload.get("parser_id"):
        errors.append({"field": "parser_id", "message": "parser_id required"})
    if payload.get("hardware_completion_eligible") is True or payload.get("deliverable_complete") is True:
        errors.append({"field": "hardware_completion_eligible", "message": "parsed result cannot upgrade completion claims"})
    return errors


def _parsed_row(
    *,
    parsed_root: Path,
    packet_id: Any,
    shard_id: Any,
    unit: Mapping[str, Any],
    stage: Mapping[str, Any],
) -> Dict[str, Any]:
    candidate_id = str(unit.get("candidate_id", ""))
    kernel_id = str(unit.get("kernel_id", ""))
    stage_id = str(stage.get("stage_id", ""))
    rel_path = _expected_parsed_result_rel_path(parsed_root=parsed_root, unit=unit, stage=stage)
    path = parsed_root / rel_path
    present = path.exists() and path.is_file()
    payload = _load_json(path) if present else {}
    schema_errors = _validate_parsed_stage_result(
        payload,
        expected_candidate_id=candidate_id,
        expected_kernel_id=kernel_id,
        expected_stage_id=stage_id,
    ) if present else []
    if not present:
        status = "missing_parsed_result"
    elif schema_errors:
        status = "invalid_parsed_result"
    else:
        status = f"parsed_{payload.get('verdict')}_pending_adjudication"
    return {
        "packet_id": packet_id,
        "shard_id": shard_id,
        "unit_id": unit.get("unit_id"),
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
        "kernel_name": unit.get("kernel_name"),
        "stage_id": stage_id,
        "tool_kind": _STAGE_TO_TOOL_KIND.get(stage_id, "unknown"),
        "expected_parsed_result": {
            "path": rel_path,
            "exists": present,
            "sha256": sha256_file(path) if present else None,
            "hash_algorithm": "sha256",
        },
        "parsed_result_present": present,
        "parsed_result_schema_valid": present and not schema_errors,
        "parsed_result_schema_errors": schema_errors,
        "parsed_verdict": payload.get("verdict") if present and not schema_errors else None,
        "parsed_blocker_ids": payload.get("blocker_ids", []) if present and isinstance(payload.get("blocker_ids", []), list) else [],
        "raw_evidence_ref_count": len(payload.get("raw_evidence_refs", []) or []) if present and isinstance(payload.get("raw_evidence_refs", []), list) else 0,
        "parser_id": payload.get("parser_id") if present else None,
        "status": status,
        "adjudication_result": "not_adjudicated_by_parsed_manifest",
        "passed": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_hardware_closure_parsed_evidence_manifest(
    *,
    closure_adjudication_path: Path,
    parsed_root: Path | None = None,
) -> Dict[str, Any]:
    """Return expected/observed parsed evidence rows for hard-gate stages."""

    adjudication_path = Path(closure_adjudication_path)
    parsed_root = Path(parsed_root or adjudication_path.parent)
    adjudication = _load_json(adjudication_path)
    rows: list[Dict[str, Any]] = []
    for unit in adjudication.get("unit_rows", []) or []:
        if not isinstance(unit, Mapping):
            continue
        for stage in unit.get("stage_rows", []) or []:
            if isinstance(stage, Mapping):
                rows.append(
                    _parsed_row(
                        parsed_root=parsed_root,
                        packet_id=unit.get("packet_id"),
                        shard_id=unit.get("shard_id"),
                        unit=unit,
                        stage=stage,
                    )
                )
    present_count = sum(1 for row in rows if row.get("parsed_result_present"))
    valid_count = sum(1 for row in rows if row.get("parsed_result_schema_valid"))
    invalid_count = sum(1 for row in rows if row.get("parsed_result_present") and not row.get("parsed_result_schema_valid"))
    missing_count = sum(1 for row in rows if not row.get("parsed_result_present"))
    verdict_counts: Dict[str, int] = {verdict: 0 for verdict in sorted(_ALLOWED_VERDICTS)}
    for row in rows:
        verdict = row.get("parsed_verdict")
        if verdict in verdict_counts:
            verdict_counts[str(verdict)] += 1
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_MANIFEST_SCHEMA,
        "status": "blocked_missing_parsed_results" if missing_count else "parsed_results_present_waiting_for_adjudication" if rows else "failed_empty_adjudication",
        "source_artifacts": {"closure_adjudication": _source_ref(adjudication_path)},
        "parsed_root": str(parsed_root),
        "release_id": adjudication.get("release_id"),
        "candidate_count": adjudication.get("candidate_count"),
        "major_kernel_count": adjudication.get("major_kernel_count"),
        "packet_count": adjudication.get("packet_count"),
        "unit_count": adjudication.get("unit_count"),
        "stage_count": len(rows),
        "expected_parsed_result_count": len(rows),
        "present_parsed_result_count": present_count,
        "missing_parsed_result_count": missing_count,
        "valid_parsed_result_count": valid_count,
        "invalid_parsed_result_count": invalid_count,
        "parsed_verdict_counts": verdict_counts,
        "adjudication_result": "not_adjudicated_by_parsed_manifest",
        "passed_stage_count": 0,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "parsed_rows": rows,
        "parsed_stage_result_schema": {
            "schema_version": DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA,
            "required_fields": [
                "schema_version",
                "candidate_id",
                "kernel_id",
                "stage_id",
                "verdict",
                "parser_id",
                "raw_evidence_refs",
            ],
            "allowed_verdicts": sorted(_ALLOWED_VERDICTS),
            "claim_boundary": "A parsed stage result is parser output only; a separate adjudicator must decide whether it satisfies the stage gate.",
        },
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_parsed_evidence_manifest(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    if isinstance(payload_or_path, Path):
        payload = _load_json(payload_or_path)
    else:
        payload = dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_MANIFEST_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected parsed evidence manifest schema"})
    rows = payload.get("parsed_rows", [])
    if not isinstance(rows, list) or not rows:
        errors.append({"field": "parsed_rows", "message": "non-empty parsed rows required"})
        rows = []
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            errors.append({"field": field, "message": "parsed evidence manifest cannot upgrade claims"})
    if payload.get("adjudication_result") != "not_adjudicated_by_parsed_manifest":
        errors.append({"field": "adjudication_result", "message": "parsed evidence manifest must not adjudicate stages"})
    if int(payload.get("passed_stage_count", 0) or 0) != 0:
        errors.append({"field": "passed_stage_count", "message": "parsed evidence manifest cannot pass stages"})
    seen: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append({"field": f"parsed_rows[{index}]", "message": "parsed row must be an object"})
            continue
        key = (str(row.get("candidate_id", "")), str(row.get("kernel_id", "")), str(row.get("stage_id", "")))
        if key in seen:
            errors.append({"field": f"parsed_rows[{index}]", "message": "duplicate candidate/kernel/stage parsed row"})
        seen.add(key)
        for field in ("passed", "hardware_completion_eligible", "deliverable_complete"):
            if row.get(field) is True:
                errors.append({"field": f"parsed_rows[{index}].{field}", "message": "parsed row cannot upgrade claims"})
        if row.get("adjudication_result") != "not_adjudicated_by_parsed_manifest":
            errors.append({"field": f"parsed_rows[{index}].adjudication_result", "message": "parsed row must not adjudicate"})
        if row.get("parsed_result_present") is True and row.get("parsed_result_schema_valid") is not True:
            if not row.get("parsed_result_schema_errors"):
                errors.append({"field": f"parsed_rows[{index}].parsed_result_schema_errors", "message": "invalid present parsed results need errors"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_MANIFEST_VALIDATION_SCHEMA,
        "valid": not errors,
        "parsed_row_count": len(rows),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_parsed_evidence_manifest(
    out_dir: Path,
    *,
    closure_adjudication_path: Path,
    parsed_root: Path | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_parsed_evidence_manifest(
        closure_adjudication_path=closure_adjudication_path,
        parsed_root=parsed_root,
    )
    write_json(out_dir / "dft_hardware_closure_parsed_evidence_manifest.json", payload)
    validation = validate_dft_hardware_closure_parsed_evidence_manifest(payload)
    write_json(out_dir / "dft_hardware_closure_parsed_evidence_manifest_validation.json", validation)
    status = {
        "schema_version": "dse.dft.hardware_closure_parsed_evidence_manifest_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "manifest": "dft_hardware_closure_parsed_evidence_manifest.json",
        "validation": "dft_hardware_closure_parsed_evidence_manifest_validation.json",
        "stage_count": payload["stage_count"],
        "present_parsed_result_count": payload["present_parsed_result_count"],
        "missing_parsed_result_count": payload["missing_parsed_result_count"],
        "valid_parsed_result_count": payload["valid_parsed_result_count"],
        "invalid_parsed_result_count": payload["invalid_parsed_result_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_parsed_evidence_manifest_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_MANIFEST_SCHEMA",
    "DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_MANIFEST_VALIDATION_SCHEMA",
    "DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA",
    "build_dft_hardware_closure_parsed_evidence_manifest",
    "validate_dft_hardware_closure_parsed_evidence_manifest",
    "write_dft_hardware_closure_parsed_evidence_manifest",
]
