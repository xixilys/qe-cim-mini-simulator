#!/usr/bin/env python3
"""Candidate-specific PPA provenance audit for DFT/QE hardware DSE.

The hard-gate parser can prove that candidate-stamped files exist and parse, but
winner selection also needs command/tool provenance showing those files came
from fresh candidate-specific tool executions rather than copied/wrapped smoke
source-flow outputs.  This module is intentionally fail-closed: weak provenance
blocks best-architecture proof while preserving the parsed evidence as progress.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.reference_workloads.dft_hardware_ppa_ranking import REQUIRED_STAGE_IDS


DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_SCHEMA = (
    "dse.dft.candidate_specific_ppa_provenance_audit.v1"
)
DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_VALIDATION_SCHEMA = (
    "dse.dft.candidate_specific_ppa_provenance_audit_validation.v1"
)
DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_STATUS_SCHEMA = (
    "dse.dft.candidate_specific_ppa_provenance_audit_status.v1"
)
DFT_HARDWARE_TIE_BREAKER_EXECUTION_QUEUE_SCHEMA = (
    "dse.dft.hardware_tie_breaker_execution_queue.v1"
)

_CLAIM_BOUNDARY = (
    "Candidate-specific PPA provenance audit checks whether parsed hard-gate "
    "files are backed by fresh candidate-specific command/tool provenance. It "
    "can block FPGA/ASIC best-architecture proof, but it does not itself run "
    "EDA tools, pass hard gates, select winners, or mark deliverable completion."
)

_FORBIDDEN_SOURCE_BOUNDARY_TERMS = (
    "smoke",
    "not full-scf",
    "not full scf",
    "not full_scf",
    "not full-scf/all-kernel",
    "not full-scf/all kernel",
    "not full-scf/all-kernel closure",
)

_MATERIALIZED_SOURCE_TERMS = (
    "copies or wraps",
    "copy or wrap",
    "materialization copies",
    "materialized",
    "source_flow_",
    "existing candidate/kernel flow outputs",
)

_FORBIDDEN_SHORTCUTS = (
    "candidate-id deterministic tie order",
    "shared route_probe/source-flow evidence reused as candidate winner proof",
    "Step2 design_score or low-fidelity score as final PPA tie-breaker",
    "single-candidate full-SCF accounting bundle used as cross-candidate winner proof",
    "metadata-only source bundles or staged command templates treated as raw tool execution",
)

_TARGET_WORKLIST_NAME = "candidate_kernel_target_ppa_gate_worklist.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path, *, required: bool = True) -> Dict[str, Any]:
    path = Path(path)
    exists = path.exists() and path.is_file()
    return {
        "path": str(path),
        "required": required,
        "exists": exists,
        "sha256": sha256_file(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _resolve_path(run_dir: Path, path_text: Any) -> Path:
    path = Path(str(path_text or ""))
    if path.is_absolute():
        return path
    for candidate in (run_dir / path, Path.cwd() / path, path):
        if candidate.exists():
            return candidate
    return run_dir / path


def _text_contains_any(value: Any, terms: Iterable[str]) -> bool:
    text = str(value or "").lower()
    return any(term in text for term in terms)


def _summary_text(payload: Mapping[str, Any]) -> str:
    fields = (
        payload.get("status"),
        payload.get("claim_boundary"),
        payload.get("input_source"),
        payload.get("schema_version"),
    )
    return "\n".join(str(item or "") for item in fields)


def _release_candidate_ids(release_gate: Mapping[str, Any]) -> list[str]:
    rows = release_gate.get("candidate_rows", []) if isinstance(release_gate.get("candidate_rows", []), list) else []
    ids = [
        str(row.get("candidate_id"))
        for row in rows
        if isinstance(row, Mapping)
        and row.get("candidate_id")
        and row.get("candidate_hardware_gate_passed", True) is True
        and row.get("candidate_claim_eligible", True) is True
    ]
    return sorted(set(ids))


def _target_worklist(run_dir: Path) -> Dict[str, Any]:
    return _load_json(run_dir / _TARGET_WORKLIST_NAME)


def _target_worklist_candidate_ids(run_dir: Path) -> list[str]:
    worklist = _target_worklist(run_dir)
    return sorted(
        {
            str(item.get("candidate_id"))
            for item in worklist.get("work_items", []) or []
            if isinstance(item, Mapping) and item.get("candidate_id")
        }
    )


def _target_worklist_kernel_ids(run_dir: Path) -> list[str]:
    worklist = _target_worklist(run_dir)
    return sorted(
        {
            str(item.get("kernel_id"))
            for item in worklist.get("work_items", []) or []
            if isinstance(item, Mapping) and item.get("kernel_id")
        }
    )


def _target_worklist_candidate_kernel_pairs(run_dir: Path) -> list[tuple[str, str]]:
    worklist = _target_worklist(run_dir)
    return sorted(
        {
            (str(item.get("candidate_id")), str(item.get("kernel_id")))
            for item in worklist.get("work_items", []) or []
            if isinstance(item, Mapping) and item.get("candidate_id") and item.get("kernel_id")
        }
    )


def _fallback_candidate_ids(run_dir: Path) -> list[str]:
    ids: set[str] = set(_target_worklist_candidate_ids(run_dir))
    root = run_dir / "candidate_specific_evidence"
    if not root.exists():
        return sorted(ids)
    ids.update(path.name for path in root.iterdir() if path.is_dir())
    return sorted(ids)


def _kernel_ids(release_gate: Mapping[str, Any]) -> list[str]:
    expected = release_gate.get("expected_kernel_ids")
    if isinstance(expected, list) and expected:
        return sorted(str(item) for item in expected if item)
    return sorted(MAJOR_SCF_KERNEL_IDS)


def _stage_result_path(run_dir: Path, candidate_id: str, kernel_id: str, stage_id: str) -> Path:
    return run_dir / "parsed_hard_gate_results" / candidate_id / kernel_id / f"{stage_id}_parsed_result.json"


def _blocker(
    blocker_id: str,
    *,
    candidate_id: str,
    kernel_id: str,
    stage_id: str | None = None,
    **extra: Any,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "blocker_id": blocker_id,
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
    }
    if stage_id is not None:
        row["stage_id"] = stage_id
    row.update(extra)
    return row


def _source_flow_manifest(run_dir: Path, candidate_input_manifest: Mapping[str, Any]) -> tuple[Path | None, Dict[str, Any]]:
    raw = candidate_input_manifest.get("source_flow_dir")
    if not raw:
        return None, {}
    source_dir = _resolve_path(run_dir, raw)
    manifest_path = source_dir / "manifest.json"
    return manifest_path, _load_json(manifest_path)


def _command_templates_by_stage(command_manifest: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    templates: Dict[str, Dict[str, Any]] = {}
    for template in command_manifest.get("command_templates", []) or []:
        if not isinstance(template, Mapping):
            continue
        for stage_id in template.get("stage_ids", []) or []:
            templates[str(stage_id)] = dict(template)
    return templates


def _stage_audit(
    run_dir: Path,
    *,
    candidate_id: str,
    kernel_id: str,
    stage_id: str,
    command_manifest: Mapping[str, Any],
    tool_versions: Mapping[str, Any],
    candidate_input_manifest: Mapping[str, Any],
    source_flow_manifest: Mapping[str, Any],
    source_flow_manifest_path: Path | None,
) -> Dict[str, Any]:
    parsed_path = _stage_result_path(run_dir, candidate_id, kernel_id, stage_id)
    parsed = _load_json(parsed_path)
    raw_refs = [dict(ref) for ref in parsed.get("raw_evidence_refs", []) or [] if isinstance(ref, Mapping)]
    blockers: list[Dict[str, Any]] = []

    if not parsed:
        blockers.append(_blocker("missing_parsed_stage_result", candidate_id=candidate_id, kernel_id=kernel_id, stage_id=stage_id, path=str(parsed_path)))
    elif parsed.get("verdict") != "passed":
        blockers.append(_blocker("parsed_stage_not_passed", candidate_id=candidate_id, kernel_id=kernel_id, stage_id=stage_id, verdict=parsed.get("verdict")))
    if not raw_refs:
        blockers.append(_blocker("parsed_stage_raw_evidence_refs_missing", candidate_id=candidate_id, kernel_id=kernel_id, stage_id=stage_id))

    if tool_versions.get("tool_versions_recorded") is not True:
        blockers.append(_blocker("tool_versions_not_recorded", candidate_id=candidate_id, kernel_id=kernel_id, stage_id=stage_id, tool_versions_recorded=tool_versions.get("tool_versions_recorded")))
    if command_manifest.get("commands_executed") is not True:
        blockers.append(_blocker("commands_not_executed", candidate_id=candidate_id, kernel_id=kernel_id, stage_id=stage_id, commands_executed=command_manifest.get("commands_executed")))
    executed_commands = command_manifest.get("executed_commands", [])
    if not isinstance(executed_commands, list) or not executed_commands:
        blockers.append(_blocker("executed_command_list_empty", candidate_id=candidate_id, kernel_id=kernel_id, stage_id=stage_id))

    if candidate_input_manifest.get("source_flow_dir"):
        blockers.append(
            _blocker(
                "raw_evidence_materialized_from_source_flow",
                candidate_id=candidate_id,
                kernel_id=kernel_id,
                stage_id=stage_id,
                source_flow_dir=candidate_input_manifest.get("source_flow_dir"),
                reason="candidate input manifest records source_flow_dir; fresh candidate-specific command provenance is required for winner proof",
            )
        )
    if _text_contains_any(_summary_text(candidate_input_manifest), _MATERIALIZED_SOURCE_TERMS):
        blockers.append(
            _blocker(
                "candidate_input_manifest_declares_materialized_or_wrapped_source",
                candidate_id=candidate_id,
                kernel_id=kernel_id,
                stage_id=stage_id,
                status=candidate_input_manifest.get("status"),
                input_source=candidate_input_manifest.get("input_source"),
            )
        )
    if source_flow_manifest and _text_contains_any(_summary_text(source_flow_manifest), _FORBIDDEN_SOURCE_BOUNDARY_TERMS):
        blockers.append(
            _blocker(
                "source_flow_claim_boundary_not_full_closure",
                candidate_id=candidate_id,
                kernel_id=kernel_id,
                stage_id=stage_id,
                source_flow_manifest=str(source_flow_manifest_path) if source_flow_manifest_path else None,
                source_flow_status=source_flow_manifest.get("status"),
                source_flow_claim_boundary=source_flow_manifest.get("claim_boundary"),
            )
        )

    return {
        "stage_id": stage_id,
        "status": "trusted_stage_provenance" if not blockers else "blocked_stage_provenance",
        "provenance_trusted": not blockers,
        "parsed_result": _source_ref(parsed_path),
        "parsed_verdict": parsed.get("verdict"),
        "raw_evidence_ref_count": len(raw_refs),
        "command_template_id": _command_templates_by_stage(command_manifest).get(stage_id, {}).get("template_id"),
        "blockers": blockers,
    }


def _unit_audit(run_dir: Path, *, candidate_id: str, kernel_id: str) -> Dict[str, Any]:
    unit_dir = run_dir / "candidate_specific_evidence" / candidate_id / kernel_id
    source_bundle_manifest_path = unit_dir / "source_bundle_manifest.json"
    tool_versions_path = unit_dir / "tool_versions.json"
    command_manifest_path = unit_dir / "command_manifest.json"
    raw_transcript_index_path = unit_dir / "raw_transcript_index.json"
    candidate_input_manifest_path = unit_dir / "candidate_input_manifest.json"

    source_bundle = _load_json(source_bundle_manifest_path)
    tool_versions = _load_json(tool_versions_path)
    command_manifest = _load_json(command_manifest_path)
    raw_transcript_index = _load_json(raw_transcript_index_path)
    candidate_input_manifest = _load_json(candidate_input_manifest_path)
    source_flow_manifest_path, source_flow = _source_flow_manifest(run_dir, candidate_input_manifest)

    blockers: list[Dict[str, Any]] = []
    if not unit_dir.exists():
        blockers.append(_blocker("missing_candidate_specific_evidence_dir", candidate_id=candidate_id, kernel_id=kernel_id, path=str(unit_dir)))
    if not source_bundle:
        blockers.append(_blocker("missing_source_bundle_manifest", candidate_id=candidate_id, kernel_id=kernel_id, path=str(source_bundle_manifest_path)))
    else:
        if source_bundle.get("candidate_specific_closure") is not True:
            blockers.append(_blocker("source_bundle_not_candidate_specific_closure", candidate_id=candidate_id, kernel_id=kernel_id, value=source_bundle.get("candidate_specific_closure")))
        if source_bundle.get("shared_microkernel_smoke_only") is True:
            blockers.append(_blocker("source_bundle_shared_microkernel_smoke_only", candidate_id=candidate_id, kernel_id=kernel_id))
        if source_bundle.get("raw_evidence_scope") != "candidate_specific_closure":
            blockers.append(_blocker("source_bundle_raw_scope_not_candidate_specific_closure", candidate_id=candidate_id, kernel_id=kernel_id, raw_evidence_scope=source_bundle.get("raw_evidence_scope")))
        if not source_bundle.get("candidate_parametric_source_hash"):
            blockers.append(
                _blocker(
                    "candidate_parametric_source_hash_missing",
                    candidate_id=candidate_id,
                    kernel_id=kernel_id,
                    reason=(
                        "source bundle must prove generated RTL/source consumed design-shaping "
                        "candidate parameters before parsed PPA can support best-architecture proof"
                    ),
                )
            )
        if not source_bundle.get("candidate_parameter_manifest"):
            blockers.append(_blocker("candidate_parameter_manifest_missing", candidate_id=candidate_id, kernel_id=kernel_id))
        if not isinstance(source_bundle.get("rtl_parameter_values"), Mapping):
            blockers.append(_blocker("rtl_parameter_values_missing", candidate_id=candidate_id, kernel_id=kernel_id))
    if not tool_versions:
        blockers.append(_blocker("missing_tool_versions_manifest", candidate_id=candidate_id, kernel_id=kernel_id, path=str(tool_versions_path)))
    if not command_manifest:
        blockers.append(_blocker("missing_command_manifest", candidate_id=candidate_id, kernel_id=kernel_id, path=str(command_manifest_path)))
    if not raw_transcript_index:
        blockers.append(_blocker("missing_raw_transcript_index", candidate_id=candidate_id, kernel_id=kernel_id, path=str(raw_transcript_index_path)))
    if not candidate_input_manifest:
        blockers.append(_blocker("missing_candidate_input_manifest", candidate_id=candidate_id, kernel_id=kernel_id, path=str(candidate_input_manifest_path)))
    if candidate_input_manifest.get("source_flow_dir") and not source_flow:
        blockers.append(_blocker("missing_source_flow_manifest", candidate_id=candidate_id, kernel_id=kernel_id, path=str(source_flow_manifest_path)))

    stage_rows = [
        _stage_audit(
            run_dir,
            candidate_id=candidate_id,
            kernel_id=kernel_id,
            stage_id=stage_id,
            command_manifest=command_manifest,
            tool_versions=tool_versions,
            candidate_input_manifest=candidate_input_manifest,
            source_flow_manifest=source_flow,
            source_flow_manifest_path=source_flow_manifest_path,
        )
        for stage_id in REQUIRED_STAGE_IDS
    ]
    for row in stage_rows:
        blockers.extend(row.get("blockers", []) or [])

    return {
        "unit_id": f"{candidate_id}:{kernel_id}",
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
        "status": "trusted_unit_provenance" if not blockers else "blocked_unit_provenance",
        "provenance_trusted": not blockers,
        "unit_evidence_dir": str(unit_dir),
        "candidate_bundle_json": str(run_dir / "candidate_specific_bundles" / candidate_id / kernel_id / "candidate_bundle.json"),
        "artifact_refs": {
            "source_bundle_manifest": _source_ref(source_bundle_manifest_path),
            "tool_versions": _source_ref(tool_versions_path),
            "command_manifest": _source_ref(command_manifest_path),
            "raw_transcript_index": _source_ref(raw_transcript_index_path),
            "candidate_input_manifest": _source_ref(candidate_input_manifest_path),
            "source_flow_manifest": _source_ref(source_flow_manifest_path, required=False) if source_flow_manifest_path else {"path": None, "required": False, "exists": False, "sha256": None, "hash_algorithm": "sha256"},
        },
        "tool_versions_recorded": tool_versions.get("tool_versions_recorded"),
        "commands_executed": command_manifest.get("commands_executed"),
        "executed_command_count": len(command_manifest.get("executed_commands", []) or []) if isinstance(command_manifest.get("executed_commands", []), list) else 0,
        "source_flow_dir": candidate_input_manifest.get("source_flow_dir"),
        "source_flow_claim_boundary": source_flow.get("claim_boundary"),
        "stage_rows": stage_rows,
        "blockers": blockers,
        "blocker_ids": sorted({str(item.get("blocker_id")) for item in blockers}),
    }


def _rank_one_ids(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(
        str(row.get("candidate_id"))
        for row in rows
        if isinstance(row, Mapping) and row.get("rank") == 1 and row.get("candidate_id")
    )


def _tied_candidate_ids(ppa: Mapping[str, Any], candidate_ids: Sequence[str]) -> list[str]:
    fpga = _rank_one_ids(ppa.get("fpga_ranking", []) if isinstance(ppa.get("fpga_ranking", []), list) else [])
    asic = _rank_one_ids(ppa.get("asic_ranking", []) if isinstance(ppa.get("asic_ranking", []), list) else [])
    ids = sorted(set(fpga + asic))
    if ids:
        return ids
    return list(candidate_ids)


def build_dft_candidate_specific_ppa_provenance_audit(run_dir: Path) -> Dict[str, Any]:
    """Build a fail-closed provenance audit for candidate-specific PPA files."""

    run_dir = Path(run_dir)
    release_gate_path = run_dir / "dft_hardware_closure_release_gate.json"
    ppa_path = run_dir / "dft_hardware_ppa_ranking.json"
    release_gate = _load_json(release_gate_path)
    ppa = _load_json(ppa_path)
    release_candidate_ids = _release_candidate_ids(release_gate)
    target_worklist_pairs = _target_worklist_candidate_kernel_pairs(run_dir)
    candidate_ids = release_candidate_ids or _fallback_candidate_ids(run_dir)
    target_worklist_kernel_ids = _target_worklist_kernel_ids(run_dir)
    kernel_ids = _kernel_ids(release_gate)
    if not release_candidate_ids and target_worklist_kernel_ids:
        kernel_ids = target_worklist_kernel_ids
    unit_pairs = (
        target_worklist_pairs
        if not release_candidate_ids and target_worklist_pairs
        else [(candidate_id, kernel_id) for candidate_id in candidate_ids for kernel_id in kernel_ids]
    )
    unit_rows = [
        _unit_audit(run_dir, candidate_id=candidate_id, kernel_id=kernel_id)
        for candidate_id, kernel_id in unit_pairs
    ]
    blockers = [dict(blocker) for unit in unit_rows for blocker in unit.get("blockers", []) or []]
    blocker_counts: Dict[str, int] = {}
    for blocker in blockers:
        key = str(blocker.get("blocker_id"))
        blocker_counts[key] = blocker_counts.get(key, 0) + 1
    trusted_unit_count = sum(1 for unit in unit_rows if unit.get("provenance_trusted") is True)
    stage_rows = [stage for unit in unit_rows for stage in unit.get("stage_rows", []) or [] if isinstance(stage, Mapping)]
    trusted_stage_count = sum(1 for stage in stage_rows if stage.get("provenance_trusted") is True)
    winner_provenance_eligible = bool(unit_rows) and not blockers and trusted_unit_count == len(unit_rows)
    tied_candidate_ids = _tied_candidate_ids(ppa, candidate_ids)
    status = (
        "trusted_candidate_specific_ppa_provenance"
        if winner_provenance_eligible
        else "blocked_candidate_specific_ppa_provenance"
    )
    return {
        "schema_version": DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_SCHEMA,
        "generated_at": _now_iso(),
        "status": status,
        "source_artifacts": {
            "release_gate": _source_ref(release_gate_path, required=False),
            "dft_hardware_ppa_ranking": _source_ref(ppa_path, required=False),
            "candidate_kernel_target_ppa_gate_worklist": _source_ref(
                run_dir / _TARGET_WORKLIST_NAME,
                required=False,
            ),
        },
        "candidate_count": len(candidate_ids),
        "major_kernel_count": len(kernel_ids),
        "unit_count": len(unit_rows),
        "stage_count": len(stage_rows),
        "trusted_unit_count": trusted_unit_count,
        "blocked_unit_count": len(unit_rows) - trusted_unit_count,
        "trusted_stage_count": trusted_stage_count,
        "blocked_stage_count": len(stage_rows) - trusted_stage_count,
        "blocker_count": len(blockers),
        "blocker_id_counts": dict(sorted(blocker_counts.items())),
        "winner_provenance_eligible": winner_provenance_eligible,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "candidate_ids": list(candidate_ids),
        "kernel_ids": list(kernel_ids),
        "tied_candidate_ids_requiring_fresh_ppa": tied_candidate_ids,
        "unit_rows": unit_rows,
        "blockers": blockers[:500],
        "blocker_truncation": {"truncated": len(blockers) > 500, "total_blocker_count": len(blockers)},
        "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_candidate_specific_ppa_provenance_audit(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate provenance-audit consistency without upgrading claims."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("provenance_audit_must_not_mark_deliverable_complete")
    if payload.get("hardware_completion_eligible") is True:
        errors.append("provenance_audit_must_not_mark_hardware_completion_eligible")
    unit_count = int(payload.get("unit_count", 0) or 0)
    trusted_unit_count = int(payload.get("trusted_unit_count", 0) or 0)
    blocker_count = int(payload.get("blocker_count", 0) or 0)
    if payload.get("winner_provenance_eligible") is True and (not unit_count or trusted_unit_count != unit_count or blocker_count):
        errors.append("winner_provenance_eligible_with_blocked_units")
    if payload.get("winner_provenance_eligible") is False and str(payload.get("status")) == "trusted_candidate_specific_ppa_provenance":
        errors.append("trusted_status_without_winner_provenance_eligible")
    return {
        "schema_version": DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _queue_stage_item(
    run_dir: Path,
    *,
    audit_unit_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    candidate_id: str,
    kernel_id: str,
    stage_id: str,
) -> Dict[str, Any]:
    unit = audit_unit_by_key.get((candidate_id, kernel_id), {})
    command_manifest = _load_json(run_dir / "candidate_specific_evidence" / candidate_id / kernel_id / "command_manifest.json")
    template = _command_templates_by_stage(command_manifest).get(stage_id, {})
    unit_evidence_dir = run_dir / "candidate_specific_evidence" / candidate_id / kernel_id
    candidate_bundle_json = run_dir / "candidate_specific_bundles" / candidate_id / kernel_id / "candidate_bundle.json"
    return {
        "work_item_id": f"fresh_ppa:{candidate_id}:{kernel_id}:{stage_id}",
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
        "stage_id": stage_id,
        "required_tool": template.get("tool"),
        "command_template_id": template.get("template_id"),
        "command": template.get("command"),
        "alternate_command": template.get("alternate_command"),
        "required_outputs": template.get("required_outputs", []),
        "candidate_bundle_json": str(candidate_bundle_json),
        "unit_evidence_dir": str(unit_evidence_dir),
        "existing_unit_provenance_status": unit.get("status"),
        "existing_unit_blocker_ids": unit.get("blocker_ids", []),
        "fresh_execution_required": True,
        "no_shared_evidence_allowed": True,
    }


def build_dft_hardware_tie_breaker_execution_queue(
    run_dir: Path,
    *,
    provenance_audit: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a queue of fresh tool executions needed to break PPA ties/provenance blockers."""

    run_dir = Path(run_dir)
    audit = dict(provenance_audit or build_dft_candidate_specific_ppa_provenance_audit(run_dir))
    candidate_ids = [str(item) for item in audit.get("tied_candidate_ids_requiring_fresh_ppa", []) or []]
    if not candidate_ids:
        candidate_ids = [str(item) for item in audit.get("candidate_ids", []) or []]
    kernel_ids = [str(item) for item in audit.get("kernel_ids", []) or []]
    audit_unit_by_key = {
        (str(unit.get("candidate_id")), str(unit.get("kernel_id"))): dict(unit)
        for unit in audit.get("unit_rows", []) or []
        if isinstance(unit, Mapping)
    }
    audit_pairs = sorted(audit_unit_by_key) or [
        (candidate_id, kernel_id)
        for candidate_id in candidate_ids
        for kernel_id in kernel_ids
    ]
    work_items: list[Dict[str, Any]] = []
    for candidate_id, kernel_id in audit_pairs:
        unit = audit_unit_by_key.get((candidate_id, kernel_id), {})
        stage_by_id = {
            str(stage.get("stage_id")): dict(stage)
            for stage in unit.get("stage_rows", []) or []
            if isinstance(stage, Mapping)
        }
        for stage_id in REQUIRED_STAGE_IDS:
            stage = stage_by_id.get(stage_id, {})
            stage_trusted = stage.get("provenance_trusted") is True
            unit_trusted = unit.get("provenance_trusted") is True
            if unit_trusted and stage_trusted:
                continue
            work_items.append(
                _queue_stage_item(
                    run_dir,
                    audit_unit_by_key=audit_unit_by_key,
                    candidate_id=candidate_id,
                    kernel_id=kernel_id,
                    stage_id=stage_id,
                )
            )
    queued_candidate_ids = sorted({str(item.get("candidate_id")) for item in work_items if item.get("candidate_id")})
    queued_kernel_ids = sorted({str(item.get("kernel_id")) for item in work_items if item.get("kernel_id")})
    return {
        "schema_version": DFT_HARDWARE_TIE_BREAKER_EXECUTION_QUEUE_SCHEMA,
        "generated_at": _now_iso(),
        "status": "fresh_candidate_specific_ppa_execution_required" if work_items else "no_tie_breaker_work_items",
        "source_artifacts": {
            "provenance_audit": _source_ref(run_dir / "dft_candidate_specific_ppa_provenance_audit.json", required=False),
            "dft_hardware_ppa_ranking": _source_ref(run_dir / "dft_hardware_ppa_ranking.json", required=False),
            "dft_architecture_winner_resolution": _source_ref(run_dir / "dft_architecture_winner_resolution.json", required=False),
        },
        "reason": "candidate-specific hard-gate PPA is tied and/or lacks fresh command/tool provenance",
        "candidate_count": len(queued_candidate_ids),
        "major_kernel_count": len(queued_kernel_ids),
        "total_audit_candidate_count": len(candidate_ids),
        "total_audit_major_kernel_count": len(kernel_ids),
        "stage_count_per_unit": len(REQUIRED_STAGE_IDS),
        "work_item_count": len(work_items),
        "candidate_ids": queued_candidate_ids,
        "kernel_ids": queued_kernel_ids,
        "required_stage_ids": list(REQUIRED_STAGE_IDS),
        "work_items": work_items,
        "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_tie_breaker_execution_queue(payload: Mapping[str, Any]) -> Dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema_version") != DFT_HARDWARE_TIE_BREAKER_EXECUTION_QUEUE_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("tie_breaker_queue_must_not_mark_deliverable_complete")
    if payload.get("hardware_completion_eligible") is True:
        errors.append("tie_breaker_queue_must_not_mark_hardware_completion_eligible")
    expected = int(payload.get("candidate_count", 0) or 0) * int(payload.get("major_kernel_count", 0) or 0) * int(payload.get("stage_count_per_unit", 0) or 0)
    actual = int(payload.get("work_item_count", 0) or 0)
    if expected and actual > expected:
        errors.append("work_item_count_exceeds_queue_upper_bound")
    if actual and str(payload.get("status")) != "fresh_candidate_specific_ppa_execution_required":
        errors.append("nonempty_queue_requires_execution_required_status")
    if not actual and str(payload.get("status")) != "no_tie_breaker_work_items":
        errors.append("empty_queue_requires_no_work_status")
    return {
        "schema_version": "dse.dft.hardware_tie_breaker_execution_queue_validation.v1",
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_candidate_specific_ppa_provenance_audit(run_dir: Path) -> Dict[str, Any]:
    """Write provenance audit, tie-breaker queue, validations, and status."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    audit = build_dft_candidate_specific_ppa_provenance_audit(run_dir)
    validation = validate_dft_candidate_specific_ppa_provenance_audit(audit)
    queue = build_dft_hardware_tie_breaker_execution_queue(run_dir, provenance_audit=audit)
    queue_validation = validate_dft_hardware_tie_breaker_execution_queue(queue)
    write_json(run_dir / "dft_candidate_specific_ppa_provenance_audit.json", audit)
    write_json(run_dir / "dft_candidate_specific_ppa_provenance_audit_validation.json", validation)
    write_json(run_dir / "dft_hardware_tie_breaker_execution_queue.json", queue)
    write_json(run_dir / "dft_hardware_tie_breaker_execution_queue_validation.json", queue_validation)
    status = {
        "schema_version": DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] and queue_validation["valid"] else "failed",
        "provenance_status": audit.get("status"),
        "winner_provenance_eligible": audit.get("winner_provenance_eligible"),
        "unit_count": audit.get("unit_count"),
        "blocked_unit_count": audit.get("blocked_unit_count"),
        "blocker_count": audit.get("blocker_count"),
        "tie_breaker_work_item_count": queue.get("work_item_count"),
        "provenance_audit": "dft_candidate_specific_ppa_provenance_audit.json",
        "provenance_validation": "dft_candidate_specific_ppa_provenance_audit_validation.json",
        "tie_breaker_execution_queue": "dft_hardware_tie_breaker_execution_queue.json",
        "tie_breaker_execution_queue_validation": "dft_hardware_tie_breaker_execution_queue_validation.json",
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_candidate_specific_ppa_provenance_audit_status.json", status)
    return {
        "schema_version": "dse.dft.candidate_specific_ppa_provenance_audit_artifact_status.v1",
        "status": status["status"],
        "provenance_audit": str(run_dir / "dft_candidate_specific_ppa_provenance_audit.json"),
        "provenance_validation": str(run_dir / "dft_candidate_specific_ppa_provenance_audit_validation.json"),
        "provenance_status": str(run_dir / "dft_candidate_specific_ppa_provenance_audit_status.json"),
        "tie_breaker_execution_queue": str(run_dir / "dft_hardware_tie_breaker_execution_queue.json"),
        "tie_breaker_execution_queue_validation": str(run_dir / "dft_hardware_tie_breaker_execution_queue_validation.json"),
        "winner_provenance_eligible": audit.get("winner_provenance_eligible"),
        "blocker_count": audit.get("blocker_count"),
        "tie_breaker_work_item_count": queue.get("work_item_count"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_SCHEMA",
    "DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_STATUS_SCHEMA",
    "DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_VALIDATION_SCHEMA",
    "DFT_HARDWARE_TIE_BREAKER_EXECUTION_QUEUE_SCHEMA",
    "build_dft_candidate_specific_ppa_provenance_audit",
    "build_dft_hardware_tie_breaker_execution_queue",
    "validate_dft_candidate_specific_ppa_provenance_audit",
    "validate_dft_hardware_tie_breaker_execution_queue",
    "write_dft_candidate_specific_ppa_provenance_audit",
]
