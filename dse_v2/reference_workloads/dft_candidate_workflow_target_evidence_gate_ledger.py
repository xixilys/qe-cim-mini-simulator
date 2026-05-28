#!/usr/bin/env python3
"""DFT/QE candidate/workflow/target evidence-gate ledger.

This producer turns the release candidate/workflow/deployment/target universe
into target-specific evidence-gate rows.  It is deliberately DFT-scoped and
fail-closed: the ledger can record trusted per-gate pass/fail evidence, but it
cannot mark hardware completion, name winners, or make the global deliverable
complete.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.codesign.release_domain import stable_json_hash


DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_SCHEMA = (
    "dse.dft.candidate_workflow_target_evidence_gate_ledger.v1"
)
DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_VALIDATION_SCHEMA = (
    "dse.dft.candidate_workflow_target_evidence_gate_ledger_validation.v1"
)
DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_STATUS_SCHEMA = (
    "dse.dft.candidate_workflow_target_evidence_gate_ledger_status.v1"
)
DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_REPORT_PACKAGE_CONTRACT_SCHEMA = (
    "dse.dft.candidate_workflow_target_evidence_gate_ledger_report_package_contract.v1"
)

LEDGER_ARTIFACT_NAME = "dft_candidate_workflow_target_evidence_gate_ledger.json"
LEDGER_VALIDATION_ARTIFACT_NAME = (
    "dft_candidate_workflow_target_evidence_gate_ledger_validation.json"
)
LEDGER_STATUS_ARTIFACT_NAME = (
    "dft_candidate_workflow_target_evidence_gate_ledger_status.json"
)
UNKNOWN_TARGET_EVIDENCE_GATE_ID = "__unknown_target__"

ROW_STATUSES: tuple[str, ...] = (
    "trusted_pass",
    "trusted_fail",
    "pruned_with_reason",
    "blocked_missing_input",
    "blocked_tool_unavailable",
    "blocked_invalid_evidence",
    "projection_only_not_claimable",
)

TARGET_REQUIRED_STAGE_IDS: Dict[str, tuple[str, ...]] = {
    "fpga": (
        "golden_correctness",
        "hls_or_rtl_sim",
        "hls_or_rtl_synth",
        "vivado_fpga_synth_or_impl",
    ),
    "asic": (
        "golden_correctness",
        "hls_or_rtl_sim",
        "hls_or_rtl_synth",
        "dc_asic_synth_timing_area",
    ),
}

SOURCE_MATRIX_GATE_TO_STAGE_ID = {
    "golden_correctness": "golden_correctness",
    "hls_or_rtl_simulation": "hls_or_rtl_sim",
    "hls_or_rtl_sim": "hls_or_rtl_sim",
    "hls_or_rtl_synthesis": "hls_or_rtl_synth",
    "hls_or_rtl_synth": "hls_or_rtl_synth",
    "vivado_synthesis_or_implementation": "vivado_fpga_synth_or_impl",
    "vivado_fpga_synth_or_impl": "vivado_fpga_synth_or_impl",
    "dc_synthesis_timing_area": "dc_asic_synth_timing_area",
    "dc_asic_synth_timing_area": "dc_asic_synth_timing_area",
}

EXCLUSIVE_STAGE_TARGET = {
    "vivado_fpga_synth_or_impl": "fpga",
    "dc_asic_synth_timing_area": "asic",
}

OPPOSITE_EXCLUSIVE_STAGE = {
    "fpga": "dc_asic_synth_timing_area",
    "asic": "vivado_fpga_synth_or_impl",
}

STAGE_REQUIRED_OUTPUTS: Dict[str, tuple[str, ...]] = {
    "golden_correctness": (
        "golden_correctness_report.json",
        "golden_reference_trace.json",
        "candidate_input_manifest.json",
    ),
    "hls_or_rtl_sim": (
        "hls_csim_or_rtl_sim_transcript.log",
        "rtl_or_hls_sim_result.json",
        "sim_waveform_manifest.json",
    ),
    "hls_or_rtl_synth": (
        "hls_or_rtl_synth_report.json",
        "hls_or_rtl_synth_utilization.json",
        "hls_or_rtl_synth_transcript.log",
    ),
    "vivado_fpga_synth_or_impl": (
        "vivado_synth_or_impl.log",
        "vivado_timing_summary.rpt",
        "vivado_utilization.rpt",
        "vivado_route_status.json",
    ),
    "dc_asic_synth_timing_area": (
        "dc_shell.log",
        "dc_timing.rpt",
        "dc_area.rpt",
        "dc_qor.rpt",
        "dc_synth.ddc",
    ),
}

STAGE_REQUIRED_TOOL = {
    "golden_correctness": "python3",
    "hls_or_rtl_sim": "vcs",
    "hls_or_rtl_synth": "hls_or_rtl_synth_tool",
    "vivado_fpga_synth_or_impl": "vivado",
    "dc_asic_synth_timing_area": "dc_shell",
}

_CLAIM_BOUNDARY = (
    "DFT candidate/workflow/target evidence-gate ledger records fail-closed "
    "target-specific golden/sim/synth/Vivado/DC gate status for current release "
    "run directories. Rows can cite trusted parsed gate evidence, but the "
    "artifact does not name final FPGA/ASIC recommendations, does not replace "
    "candidate-specific tool execution, and cannot mark hardware completion or "
    "deliverable completion."
)


def build_report_package_input_contract(run_dir: Path) -> Dict[str, Any]:
    """Return the stable package contract consumed by shared report integration."""

    run_dir = Path(run_dir)
    required_counter_fields = [
        "candidate_kernel_target_axis_count",
        "candidate_kernel_target_axis_counts_by_target",
        "row_counts_by_candidate_kernel_target_axis",
        "row_counts_by_target_platform_kind",
        "unknown_target_platform_kind_row_count",
        "parsed_stage_result_ref_count",
        "stable_blocker_reason_counts",
        "blocker_count",
    ]
    artifacts = [
        {
            "artifact_role": "target_evidence_gate_ledger",
            "canonical_name": LEDGER_ARTIFACT_NAME,
            "path": str(run_dir / LEDGER_ARTIFACT_NAME),
            "schema_id": DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_SCHEMA,
            "required_for_report_package": True,
            "validation_role": "validated_artifact",
        },
        {
            "artifact_role": "target_evidence_gate_ledger_validation",
            "canonical_name": LEDGER_VALIDATION_ARTIFACT_NAME,
            "path": str(run_dir / LEDGER_VALIDATION_ARTIFACT_NAME),
            "schema_id": DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_VALIDATION_SCHEMA,
            "required_for_report_package": True,
            "validation_role": "validation_artifact",
        },
        {
            "artifact_role": "target_evidence_gate_ledger_status",
            "canonical_name": LEDGER_STATUS_ARTIFACT_NAME,
            "path": str(run_dir / LEDGER_STATUS_ARTIFACT_NAME),
            "schema_id": DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_STATUS_SCHEMA,
            "required_for_report_package": True,
            "validation_role": "status_artifact",
        },
    ]
    return {
        "schema_version": (
            DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_REPORT_PACKAGE_CONTRACT_SCHEMA
        ),
        "package_id": "dft_candidate_workflow_target_evidence_gate_ledger",
        "package_role": "dft_target_evidence_gate_report_input",
        "consumer_hint": "run3_complete_dse_claims_report_integration",
        "artifact_names": [str(artifact["canonical_name"]) for artifact in artifacts],
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "required_counter_fields": required_counter_fields,
        "counter_field_groups": {
            "target_axis_counters": [
                "candidate_kernel_target_axis_count",
                "candidate_kernel_target_axis_counts_by_target",
                "row_counts_by_candidate_kernel_target_axis",
                "row_counts_by_target_platform_kind",
            ],
            "unknown_target_counters": ["unknown_target_platform_kind_row_count"],
            "parsed_stage_ref_counters": ["parsed_stage_result_ref_count"],
            "blocker_counters": ["stable_blocker_reason_counts", "blocker_count"],
        },
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path | None) -> Dict[str, Any]:
    if path is None:
        return {}
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_json_value(path: Path | None) -> Any:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _source_ref(path: Path | None, *, required: bool) -> Dict[str, Any]:
    if path is None:
        return {
            "path": None,
            "required": required,
            "exists": False,
            "status": "missing_required" if required else "not_attached",
            "sha256": None,
            "hash_algorithm": "sha256",
        }
    candidate = Path(path)
    exists = candidate.exists() and candidate.is_file()
    return {
        "path": str(candidate),
        "required": required,
        "exists": exists,
        "status": "present_hash_valid" if exists else "missing_required" if required else "not_attached",
        "sha256": sha256_file(candidate) if exists else None,
        "hash_algorithm": "sha256",
    }


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Dict[str, Any]]:
    return [dict(row) for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _discover_release_subset_path(run_dir: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return Path(explicit)
    for name in (
        "complete_dse_release_subset_manifest.json",
        "release_subset_manifest.json",
        "dft_release_subset_manifest.json",
    ):
        candidate = run_dir / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _discover_release_matrix_path(run_dir: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return Path(explicit)
    for name in (
        "candidate_workflow_deployment_target_matrix.json",
        "dft_candidate_workflow_deployment_target_matrix.json",
    ):
        candidate = run_dir / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _load_release_matrix(
    run_dir: Path,
    *,
    release_matrix_path: Path | None,
    release_subset_path: Path | None,
) -> tuple[Dict[str, Any], Path | None, Path | None]:
    matrix_path = _discover_release_matrix_path(run_dir, release_matrix_path)
    if matrix_path is not None and matrix_path.exists():
        return _load_json(matrix_path), matrix_path, _discover_release_subset_path(run_dir, release_subset_path)

    subset_path = _discover_release_subset_path(run_dir, release_subset_path)
    subset = _load_json(subset_path)
    matrix = _as_mapping(subset.get("candidate_workflow_deployment_target_matrix"))
    return matrix, None, subset_path


def _stage_evidence_refs(row: Mapping[str, Any]) -> list[Dict[str, Any]]:
    refs: list[Dict[str, Any]] = []
    parsed_result = _as_mapping(row.get("parsed_result"))
    if parsed_result:
        refs.append(
            {
                "path": parsed_result.get("path"),
                "exists": parsed_result.get("exists"),
                "sha256": parsed_result.get("sha256"),
                "hash_algorithm": parsed_result.get("hash_algorithm", "sha256"),
                "evidence_role": "parsed_stage_result",
            }
        )
    for ref in row.get("raw_evidence_refs", []) or []:
        if isinstance(ref, Mapping):
            copied = dict(ref)
            copied.setdefault("evidence_role", "raw_stage_evidence")
            refs.append(copied)
    return refs


def _stage_index(
    gate_adjudication: Mapping[str, Any],
) -> Dict[str, Dict[str, Dict[str, list[Dict[str, Any]]]]]:
    index: Dict[str, Dict[str, Dict[str, list[Dict[str, Any]]]]] = {}
    for unit in gate_adjudication.get("unit_rows", []) or []:
        if not isinstance(unit, Mapping):
            continue
        unit_candidate = str(unit.get("candidate_id") or "")
        unit_kernel = str(unit.get("kernel_id") or "")
        for stage in unit.get("stage_rows", []) or []:
            if not isinstance(stage, Mapping):
                continue
            row = dict(stage)
            candidate_id = str(row.get("candidate_id") or unit_candidate or "")
            kernel_id = str(row.get("kernel_id") or unit_kernel or "__unbound__")
            stage_id = str(row.get("stage_id") or "")
            if not candidate_id or not kernel_id or not stage_id:
                continue
            row.setdefault("kernel_id", kernel_id)
            index.setdefault(candidate_id, {}).setdefault(kernel_id, {}).setdefault(stage_id, []).append(row)
    return index


def _parsed_stage_result_refs_from_rows(rows: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    refs: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        for ref in row.get("evidence_refs", []) or []:
            if not isinstance(ref, Mapping) or ref.get("evidence_role") != "parsed_stage_result":
                continue
            copied = dict(ref)
            key = stable_json_hash(copied)
            if key in seen:
                continue
            seen.add(key)
            refs.append(copied)
    return refs


def _tool_availability_index(payload: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    rows = payload.get("tool_rows", [])
    index: Dict[str, Mapping[str, Any]] = {}
    if not isinstance(rows, list):
        return index
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        tool = str(row.get("tool") or "").strip().lower()
        if tool:
            index[tool] = row
    return index


def _tool_attempt_index(
    tool_availability: Mapping[str, Any],
    tool_attempts: Any,
) -> Dict[str, list[Dict[str, Any]]]:
    index: Dict[str, list[Dict[str, Any]]] = {}
    seen: set[str] = set()
    sources: list[Any] = []
    raw_attempts = tool_availability.get("raw_attempts", [])
    if isinstance(raw_attempts, list):
        sources.extend(raw_attempts)
    if isinstance(tool_attempts, list):
        sources.extend(tool_attempts)
    raw_transcript_refs = tool_availability.get("raw_command_transcript_refs", [])
    attached_transcript_keys = {
        stable_json_hash(ref)
        for attempt in sources
        if isinstance(attempt, Mapping)
        for ref in [_as_mapping(attempt.get("raw_command_transcript_ref"))]
        if ref
    }
    if isinstance(raw_transcript_refs, list):
        for ref in raw_transcript_refs:
            if not isinstance(ref, Mapping):
                continue
            if stable_json_hash(ref) in attached_transcript_keys:
                continue
            tool = str(ref.get("tool") or "").strip().lower()
            if not tool:
                continue
            sources.append(
                {
                    "tool": tool,
                    "command": None,
                    "returncode": ref.get("returncode"),
                    "stdout": "",
                    "stderr": "",
                    "transport": ref.get("transport"),
                    "environment": "raw_command_transcript_ref_only",
                    "artifact_role": "tool_availability_only_not_kernel_ppa",
                    "availability_only_not_kernel_ppa": True,
                    "kernel_ppa_evidence": False,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                    "raw_command_transcript_ref": dict(ref),
                }
            )

    for attempt in sources:
        if not isinstance(attempt, Mapping):
            continue
        row = dict(attempt)
        tool = str(row.get("tool") or "").strip().lower()
        if not tool:
            continue
        row.setdefault("artifact_role", "tool_availability_only_not_kernel_ppa")
        row.setdefault("availability_only_not_kernel_ppa", True)
        row.setdefault("kernel_ppa_evidence", False)
        row.setdefault("hardware_completion_eligible", False)
        row.setdefault("deliverable_complete", False)
        key = stable_json_hash(row)
        if key in seen:
            continue
        seen.add(key)
        index.setdefault(tool, []).append(row)
    return index


def _tool_attempt_refs(
    tool_attempt_index: Mapping[str, list[Dict[str, Any]]],
    tool: str | None,
) -> list[Dict[str, Any]]:
    if not tool:
        return []
    return [dict(attempt) for attempt in tool_attempt_index.get(tool.lower(), [])]


def _tool_attempt_evidence_refs(tool_attempt_refs: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    refs: list[Dict[str, Any]] = []
    for attempt in tool_attempt_refs:
        ref = {
            "evidence_role": "tool_availability_attempt",
            "artifact_role": attempt.get("artifact_role", "tool_availability_only_not_kernel_ppa"),
            "tool": attempt.get("tool"),
            "transport": attempt.get("transport"),
            "environment": attempt.get("environment"),
            "command": attempt.get("command"),
            "returncode": attempt.get("returncode"),
            "stdout": attempt.get("stdout", ""),
            "stderr": attempt.get("stderr", ""),
            "availability_only_not_kernel_ppa": True,
            "kernel_ppa_evidence": False,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        }
        transcript_ref = attempt.get("raw_command_transcript_ref")
        if isinstance(transcript_ref, Mapping):
            ref["raw_command_transcript_ref"] = dict(transcript_ref)
        refs.append(ref)
    return refs


def _tool_availability_source_ref(
    path: Path,
) -> Dict[str, Any]:
    ref = _source_ref(path, required=False)
    ref.update(
        {
            "artifact_role": "ic_eda_tool_availability",
            "availability_only_not_kernel_ppa": True,
            "kernel_ppa_evidence": False,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        }
    )
    return ref


def _stable_blocker_reason_id(classification: Mapping[str, Any]) -> str | None:
    status = str(classification.get("status") or "")
    reason = str(classification.get("status_reason") or "").strip()
    blocker_ids = [
        str(blocker).strip()
        for blocker in classification.get("blocker_ids", []) or []
        if str(blocker).strip()
    ]
    if status == "trusted_pass":
        return None
    if reason:
        return reason
    if blocker_ids:
        return blocker_ids[0]
    return status or None


def _replayable_tool_transcript_refs(
    tool_attempt_refs: Sequence[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    refs: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for attempt in tool_attempt_refs:
        ref = attempt.get("raw_command_transcript_ref")
        if not isinstance(ref, Mapping):
            continue
        copied = dict(ref)
        key = stable_json_hash(copied)
        if key in seen:
            continue
        seen.add(key)
        refs.append(copied)
    return refs


def _resolve_run_path(run_dir: Path, raw_path: Any) -> Path | None:
    if not raw_path:
        return None
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    return run_dir / candidate


def _candidate_specific_execution_transcript_refs(
    run_dir: Path,
    execution_payload: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    """Collect replayable raw transcript refs from fresh execution provenance.

    The candidate-specific execution aggregate records refs to each unit's
    ``raw_transcript_index.json``.  Loading those index files keeps QE/gem5/tool
    raw evidence traceability visible without turning the raw files into
    trusted gate evidence.
    """

    refs: list[Dict[str, Any]] = []
    seen: set[str] = set()

    def add_ref(ref: Mapping[str, Any]) -> None:
        copied = dict(ref)
        key = stable_json_hash(copied)
        if key in seen:
            return
        seen.add(key)
        refs.append(copied)

    def add_index_payload(index_payload: Mapping[str, Any]) -> None:
        raw_refs = index_payload.get("raw_transcript_refs", [])
        if not isinstance(raw_refs, list):
            return
        for raw_ref in raw_refs:
            if isinstance(raw_ref, Mapping):
                add_ref(raw_ref)

    direct_refs = execution_payload.get("raw_transcript_refs", [])
    if isinstance(direct_refs, list):
        for ref in direct_refs:
            if isinstance(ref, Mapping):
                add_ref(ref)

    for unit in execution_payload.get("units", []) or []:
        if not isinstance(unit, Mapping):
            continue
        provenance_refs = unit.get("provenance_refs", [])
        if isinstance(provenance_refs, Mapping):
            provenance_refs = list(provenance_refs.values())
        if not isinstance(provenance_refs, list):
            provenance_refs = []
        raw_index_candidates: list[Mapping[str, Any]] = []
        raw_index = unit.get("raw_transcript_index")
        if isinstance(raw_index, Mapping):
            raw_index_candidates.append(raw_index)
        raw_index_candidates.extend(
            ref
            for ref in provenance_refs
            if isinstance(ref, Mapping)
            and str(ref.get("path") or "").endswith("raw_transcript_index.json")
        )
        for raw_index_ref in raw_index_candidates:
            index_path = _resolve_run_path(run_dir, raw_index_ref.get("path"))
            index_payload = _load_json(index_path)
            if index_payload:
                add_index_payload(index_payload)
    return refs


def _candidate_specific_execution_stage_index(
    execution_payload: Mapping[str, Any],
) -> Dict[tuple[str, str, str], list[Dict[str, Any]]]:
    """Index fresh execution unit-stage rows by candidate and hard-gate stage.

    These refs are concrete candidate/kernel execution records, but they remain
    raw/provenance evidence until parser and gate adjudication promote them.
    """

    index: Dict[tuple[str, str, str], list[Dict[str, Any]]] = {}
    seen: set[str] = set()
    for unit in execution_payload.get("units", []) or []:
        if not isinstance(unit, Mapping):
            continue
        candidate_id = str(unit.get("candidate_id") or "")
        kernel_id = str(unit.get("kernel_id") or "")
        if not candidate_id or not kernel_id:
            continue
        unit_id = str(unit.get("unit_id") or f"{candidate_id}:{kernel_id}")
        unit_status = str(unit.get("status") or "")
        command_run_id = unit.get("command_run_id")
        unit_evidence_dir = unit.get("unit_evidence_dir")
        for stage_result in unit.get("stage_results", []) or []:
            if not isinstance(stage_result, Mapping):
                continue
            stage_id = str(stage_result.get("stage_id") or "")
            if not stage_id:
                continue
            ref = {
                "evidence_role": "candidate_specific_stage_execution",
                "candidate_id": candidate_id,
                "kernel_id": kernel_id,
                "unit_id": unit_id,
                "stage_id": stage_id,
                "stage_status": str(stage_result.get("status") or ""),
                "unit_status": unit_status,
                "command_run_id": command_run_id,
                "unit_evidence_dir": unit_evidence_dir,
                "required_outputs": [
                    dict(output)
                    for output in stage_result.get("required_outputs", []) or []
                    if isinstance(output, Mapping)
                ],
                "missing_required_outputs": [
                    str(output)
                    for output in stage_result.get("missing_required_outputs", []) or []
                    if str(output)
                ],
                "blocker_ids": [
                    str(blocker)
                    for blocker in stage_result.get("blocker_ids", []) or []
                    if str(blocker)
                ],
                "materialized_raw_file_count": int(
                    stage_result.get("materialized_raw_file_count", 0) or 0
                ),
                "candidate_specific": True,
                "availability_only_not_kernel_ppa": False,
                "kernel_ppa_evidence": False,
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
            }
            key = stable_json_hash(ref)
            if key in seen:
                continue
            seen.add(key)
            index.setdefault((candidate_id, kernel_id, stage_id), []).append(ref)
        materialized_rows_by_stage: Dict[str, list[Dict[str, Any]]] = {}
        for materialized_row in unit.get("materialized_rows", []) or []:
            if not isinstance(materialized_row, Mapping):
                continue
            stage_id = str(materialized_row.get("stage_id") or "")
            if not stage_id:
                continue
            materialized_rows_by_stage.setdefault(stage_id, []).append(dict(materialized_row))
        for stage_id, materialized_rows in materialized_rows_by_stage.items():
            ref = {
                "evidence_role": "candidate_specific_stage_execution",
                "candidate_id": candidate_id,
                "kernel_id": kernel_id,
                "unit_id": unit_id,
                "stage_id": stage_id,
                "stage_status": unit_status or "fresh_candidate_specific_execution_recorded",
                "unit_status": unit_status,
                "command_run_id": command_run_id,
                "unit_evidence_dir": unit_evidence_dir,
                "required_outputs": [
                    {
                        "file_name": str(row.get("file_name") or ""),
                        "path": row.get("path"),
                        "exists": True,
                    }
                    for row in materialized_rows
                    if str(row.get("file_name") or "")
                ],
                "missing_required_outputs": [],
                "blocker_ids": [
                    str(blocker)
                    for blocker in unit.get("blocker_ids", []) or []
                    if str(blocker)
                ],
                "materialized_raw_file_count": len(materialized_rows),
                "candidate_specific": True,
                "availability_only_not_kernel_ppa": False,
                "kernel_ppa_evidence": False,
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
            }
            key = stable_json_hash(ref)
            if key in seen:
                continue
            seen.add(key)
            index.setdefault((candidate_id, kernel_id, stage_id), []).append(ref)
    for refs in index.values():
        refs.sort(
            key=lambda item: (
                str(item.get("candidate_id") or ""),
                str(item.get("kernel_id") or ""),
                str(item.get("stage_id") or ""),
                str(item.get("command_run_id") or ""),
            )
        )
    return index


def _candidate_specific_execution_refs(
    stage_index: Mapping[tuple[str, str, str], list[Dict[str, Any]]],
    *,
    candidate_id: str,
    kernel_id: str,
    stage_id: str,
) -> list[Dict[str, Any]]:
    return [dict(ref) for ref in stage_index.get((candidate_id, kernel_id, stage_id), [])]


def _candidate_kernel_contexts(
    stage_rows_by_candidate: Mapping[str, Mapping[str, Mapping[str, list[Dict[str, Any]]]]],
    candidate_specific_execution: Mapping[str, Any],
) -> Dict[str, list[Dict[str, str]]]:
    contexts: Dict[str, Dict[str, Dict[str, str]]] = {}
    for candidate_id, kernel_stage_rows in stage_rows_by_candidate.items():
        for kernel_id in kernel_stage_rows:
            if kernel_id:
                contexts.setdefault(candidate_id, {}).setdefault(
                    kernel_id,
                    {"candidate_id": candidate_id, "kernel_id": kernel_id},
                )
    for unit in candidate_specific_execution.get("units", []) or []:
        if not isinstance(unit, Mapping):
            continue
        candidate_id = str(unit.get("candidate_id") or "")
        kernel_id = str(unit.get("kernel_id") or "")
        if not candidate_id or not kernel_id:
            continue
        contexts.setdefault(candidate_id, {}).setdefault(
            kernel_id,
            {"candidate_id": candidate_id, "kernel_id": kernel_id},
        )
    return {
        candidate_id: sorted(
            list(kernel_contexts.values()),
            key=lambda item: item["kernel_id"],
        )
        for candidate_id, kernel_contexts in contexts.items()
    }


def _tool_unavailable(tool_index: Mapping[str, Mapping[str, Any]], tool: str) -> bool:
    if not tool or tool == "python3":
        return False
    row = tool_index.get(tool.lower())
    return isinstance(row, Mapping) and row.get("available") is False


def _required_tool_availability_status(
    tool_index: Mapping[str, Mapping[str, Any]],
    tool_attempt_refs: Sequence[Mapping[str, Any]],
    tool: str | None,
) -> str:
    if not tool:
        return "not_required"
    if tool == "python3":
        return "local_required_not_ic_eda_probe"
    row = tool_index.get(tool.lower())
    if isinstance(row, Mapping):
        if row.get("available") is True:
            return "available_from_availability_probe"
        if row.get("available") is False:
            return "unavailable_from_availability_probe"
    if tool_attempt_refs:
        return "probed_without_structured_tool_row"
    return "not_probed"


def _availability_probe_transports(tool_attempt_refs: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            str(ref.get("transport") or "")
            for ref in tool_attempt_refs
            if str(ref.get("transport") or "")
        }
    )


def _availability_probe_kernel_ppa_evidence(
    tool_attempt_refs: Sequence[Mapping[str, Any]],
) -> bool:
    return any(ref.get("kernel_ppa_evidence") is True for ref in tool_attempt_refs)


def _parsed_result_blocker_id(row: Mapping[str, Any]) -> str | None:
    if row.get("candidate_kernel_axis_bound") is False or str(row.get("kernel_id") or "") == "__unbound__":
        return "parsed_result_kernel_axis_unbound"
    text = " ".join(
        str(row.get(field) or "")
        for field in (
            "artifact_role",
            "status",
            "status_reason",
            "evidence_scope",
            "completion_basis",
        )
    ).lower()
    if (
        row.get("availability_only_not_kernel_ppa") is True
        or "availability_only_not_kernel_ppa" in text
        or "tool_availability_only_not_kernel_ppa" in text
    ):
        return "parsed_result_not_kernel_ppa_evidence"
    if row.get("smoke_only_not_kernel_ppa") is True or "smoke_only" in text:
        return "parsed_result_smoke_only_not_kernel_ppa"
    if (
        row.get("projection_only_not_claimable") is True
        or "projection_only" in text
        or "model_only" in text
    ):
        return "parsed_result_projection_only_not_claimable"
    return None


def _stage_passed(row: Mapping[str, Any]) -> bool:
    if str(row.get("status") or "").startswith("blocked"):
        return False
    if _parsed_result_blocker_id(row):
        return False
    return (
        row.get("stage_gate_passed") is True
        or row.get("gate_passed") is True
        or str(row.get("adjudication_result") or "") == "passed_stage_gate"
        or str(row.get("parsed_verdict") or "").lower() == "passed"
    )


def _stage_failed(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("adjudication_result") or "") == "failed_stage_gate"
        or str(row.get("parsed_verdict") or "").lower() == "failed"
        or str(row.get("status") or "").startswith("failed")
    )


def _projection_marker(row: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in (
            "status",
            "status_reason",
            "claim_boundary",
            "completion_basis",
            "evidence_scope",
        )
    ).lower()
    return (
        "projection_only" in text
        or "projection-only" in text
        or "model_only" in text
        or "model-only" in text
    )


def _matrix_row_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("candidate_id") or ""),
        str(row.get("workflow_case_id") or ""),
        str(row.get("deployment_boundary_id") or ""),
        str(row.get("target_platform_id") or ""),
    )


def _source_matrix_evidence_gate_id(row: Mapping[str, Any]) -> str:
    evidence_gate = _as_mapping(row.get("evidence_gate"))
    return str(row.get("evidence_gate_id") or evidence_gate.get("evidence_gate_id") or "")


def _target_stage_ids_for_matrix_row(
    row: Mapping[str, Any],
    *,
    target: str,
) -> tuple[str, ...]:
    if target not in TARGET_REQUIRED_STAGE_IDS:
        return (UNKNOWN_TARGET_EVIDENCE_GATE_ID,)
    source_gate_id = _source_matrix_evidence_gate_id(row)
    if not source_gate_id:
        return TARGET_REQUIRED_STAGE_IDS[target]
    return (SOURCE_MATRIX_GATE_TO_STAGE_ID.get(source_gate_id, source_gate_id),)


def _row_id(row_key: Mapping[str, Any]) -> str:
    return "dft_cwteg_" + stable_json_hash(row_key)[:20]


def _candidate_kernel_target_axis_id(candidate_id: str, kernel_id: str, target: str) -> str:
    return f"{candidate_id}::{kernel_id}::{target}"


def _required_next_evidence(
    *,
    candidate_id: str,
    kernel_id: str | None = None,
    target: str,
    stage_id: str,
    reason: str,
    required_tool: str | None = None,
) -> list[Dict[str, Any]]:
    return [
        {
            "task_id": f"{target}_{stage_id}_candidate_specific_evidence",
            "deployment": target,
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "evidence_gate_id": stage_id,
            "reason": reason,
            "required_tool": required_tool,
            "required_artifacts": list(STAGE_REQUIRED_OUTPUTS.get(stage_id, ())),
            "evidence_scope": "candidate_workflow_deployment_target_gate",
            "target_specific_missing_input_reason": (
                f"missing_target_specific_gate_evidence:{target}:{stage_id}"
            ),
        }
    ]


def _unknown_target_next_evidence(
    *,
    candidate_id: str,
    kernel_id: str | None,
    target: str,
) -> list[Dict[str, Any]]:
    return [
        {
            "task_id": f"{target or 'unknown'}_canonical_target_contract_binding",
            "deployment": target,
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "evidence_gate_id": UNKNOWN_TARGET_EVIDENCE_GATE_ID,
            "reason": f"unknown_target_platform_kind:{target or '__missing__'}",
            "required_tool": None,
            "required_artifacts": [
                "candidate_workflow_deployment_target_matrix.json",
                "dft_hardware_closure_gate_adjudication.json",
            ],
            "evidence_scope": "candidate_workflow_deployment_target_gate",
            "target_specific_missing_input_reason": (
                f"unknown_target_platform_kind:{target or '__missing__'}"
            ),
        }
    ]


def _classification(
    *,
    matrix_row: Mapping[str, Any],
    candidate_id: str,
    kernel_id: str,
    target: str,
    stage_id: str,
    stage_rows_by_candidate: Mapping[str, Mapping[str, Mapping[str, list[Dict[str, Any]]]]],
    tool_index: Mapping[str, Mapping[str, Any]],
    tool_attempt_index: Mapping[str, list[Dict[str, Any]]],
) -> Dict[str, Any]:
    source_status = str(matrix_row.get("status") or "")
    source_reason = str(matrix_row.get("status_reason") or "")
    required_tool = STAGE_REQUIRED_TOOL.get(stage_id)
    evidence_refs: list[Dict[str, Any]] = []
    tool_attempt_refs: list[Dict[str, Any]] = []
    blocker_ids: list[str] = []
    required_next_evidence: list[Dict[str, Any]] = []
    wrong_target_evidence_rejected = False
    bound_kernel_id = kernel_id if kernel_id != "__unbound__" else None

    if target not in TARGET_REQUIRED_STAGE_IDS:
        blocker_id = f"unknown_target_platform_kind:{target or '__missing__'}"
        return {
            "status": "blocked_invalid_evidence",
            "status_reason": blocker_id,
            "evidence_refs": evidence_refs,
            "tool_attempt_refs": tool_attempt_refs,
            "blocker_ids": [blocker_id],
            "required_next_evidence": _unknown_target_next_evidence(
                candidate_id=candidate_id,
                kernel_id=bound_kernel_id,
                target=target,
            ),
            "wrong_target_evidence_rejected": False,
        }

    if source_status == "pruned_with_reason":
        reason = source_reason or "candidate_workflow_target_row_pruned"
        return {
            "status": "pruned_with_reason",
            "status_reason": reason,
            "evidence_refs": evidence_refs,
            "tool_attempt_refs": tool_attempt_refs,
            "blocker_ids": ["pruned_with_reason"],
            "required_next_evidence": [],
            "wrong_target_evidence_rejected": False,
        }

    if source_status == "projection_only_not_claimable" or _projection_marker(matrix_row):
        reason = source_reason or "projection_or_model_only_row_not_claimable"
        return {
            "status": "projection_only_not_claimable",
            "status_reason": reason,
            "evidence_refs": evidence_refs,
            "tool_attempt_refs": tool_attempt_refs,
            "blocker_ids": ["projection_only_not_claimable"],
            "required_next_evidence": _required_next_evidence(
                candidate_id=candidate_id,
                kernel_id=bound_kernel_id,
                target=target,
                stage_id=stage_id,
                reason="replace_projection_with_target_specific_tool_evidence",
                required_tool=required_tool,
            ),
            "wrong_target_evidence_rejected": False,
        }

    candidate_stage_rows = stage_rows_by_candidate.get(candidate_id, {})
    kernel_stage_rows = candidate_stage_rows.get(kernel_id, {}) if kernel_id else {}
    rows_for_stage = list(kernel_stage_rows.get(stage_id, []) or [])
    for stage_row in rows_for_stage:
        evidence_refs.extend(_stage_evidence_refs(stage_row))

    opposite_stage = OPPOSITE_EXCLUSIVE_STAGE.get(target)
    opposite_rows = list(kernel_stage_rows.get(opposite_stage, []) or []) if opposite_stage else []
    opposite_passed = any(_stage_passed(row) for row in opposite_rows)
    if (
        not rows_for_stage
        and opposite_passed
        and stage_id in set(EXCLUSIVE_STAGE_TARGET)
    ):
        wrong_target_evidence_rejected = True
        for row in opposite_rows:
            evidence_refs.extend(_stage_evidence_refs(row))
        blocker_id = (
            "dc_only_fpga_evidence_shortcut_rejected"
            if target == "fpga"
            else "vivado_only_asic_evidence_shortcut_rejected"
        )
        blocker_ids.append(blocker_id)
        required_next_evidence = _required_next_evidence(
            candidate_id=candidate_id,
            kernel_id=bound_kernel_id,
            target=target,
            stage_id=stage_id,
            reason=blocker_id,
            required_tool=required_tool,
        )
        return {
            "status": "blocked_invalid_evidence",
            "status_reason": (
                "wrong-target exclusive evidence cannot satisfy this target-specific gate"
            ),
            "evidence_refs": evidence_refs,
            "tool_attempt_refs": tool_attempt_refs,
            "blocker_ids": blocker_ids,
            "required_next_evidence": required_next_evidence,
            "wrong_target_evidence_rejected": wrong_target_evidence_rejected,
        }

    if rows_for_stage:
        if any(_stage_failed(row) for row in rows_for_stage):
            return {
                "status": "trusted_fail",
                "status_reason": "parsed_gate_evidence_failed",
                "evidence_refs": evidence_refs,
                "tool_attempt_refs": tool_attempt_refs,
                "blocker_ids": ["parsed_gate_evidence_failed"],
                "required_next_evidence": _required_next_evidence(
                    candidate_id=candidate_id,
                    kernel_id=bound_kernel_id,
                    target=target,
                    stage_id=stage_id,
                    reason="rerun_or_fix_failed_target_specific_gate",
                    required_tool=required_tool,
                ),
                "wrong_target_evidence_rejected": False,
            }
        if all(_stage_passed(row) for row in rows_for_stage):
            return {
                "status": "trusted_pass",
                "status_reason": "trusted_parsed_stage_gate_passed",
                "evidence_refs": evidence_refs,
                "tool_attempt_refs": tool_attempt_refs,
                "blocker_ids": [],
                "required_next_evidence": [],
                "wrong_target_evidence_rejected": False,
            }
        parsed_blockers = [
            str(blocker)
            for row in rows_for_stage
            for blocker in row.get("parsed_blocker_ids", []) or []
            if blocker
        ]
        blocker_ids = parsed_blockers or ["parsed_gate_evidence_invalid_or_inconclusive"]
        return {
            "status": "blocked_invalid_evidence",
            "status_reason": "parsed_gate_evidence_invalid_or_inconclusive",
            "evidence_refs": evidence_refs,
            "tool_attempt_refs": tool_attempt_refs,
            "blocker_ids": blocker_ids,
            "required_next_evidence": _required_next_evidence(
                candidate_id=candidate_id,
                kernel_id=bound_kernel_id,
                target=target,
                stage_id=stage_id,
                reason="replace_invalid_or_inconclusive_target_specific_gate_evidence",
                required_tool=required_tool,
            ),
            "wrong_target_evidence_rejected": False,
        }

    if required_tool and _tool_unavailable(tool_index, required_tool):
        blocker_id = f"required_tool_unavailable:{required_tool}"
        tool_attempt_refs = _tool_attempt_refs(tool_attempt_index, required_tool)
        evidence_refs.extend(_tool_attempt_evidence_refs(tool_attempt_refs))
        return {
            "status": "blocked_tool_unavailable",
            "status_reason": blocker_id,
            "evidence_refs": evidence_refs,
            "tool_attempt_refs": tool_attempt_refs,
            "blocker_ids": [blocker_id],
            "required_next_evidence": _required_next_evidence(
                candidate_id=candidate_id,
                kernel_id=bound_kernel_id,
                target=target,
                stage_id=stage_id,
                reason=blocker_id,
                required_tool=required_tool,
            ),
            "wrong_target_evidence_rejected": False,
        }

    missing_input_tool_attempt_refs = (
        _tool_attempt_refs(tool_attempt_index, required_tool) if required_tool else []
    )
    evidence_refs.extend(_tool_attempt_evidence_refs(missing_input_tool_attempt_refs))
    return {
        "status": "blocked_missing_input",
        "status_reason": "missing_target_specific_gate_evidence",
        "evidence_refs": evidence_refs,
        "tool_attempt_refs": missing_input_tool_attempt_refs,
        "blocker_ids": [f"missing_target_specific_gate_evidence:{stage_id}"],
        "required_next_evidence": _required_next_evidence(
            candidate_id=candidate_id,
            kernel_id=bound_kernel_id,
            target=target,
            stage_id=stage_id,
            reason="missing_target_specific_gate_evidence",
            required_tool=required_tool,
        ),
        "wrong_target_evidence_rejected": False,
    }


def build_dft_candidate_workflow_target_evidence_gate_ledger(
    run_dir: Path,
    *,
    release_matrix_path: Path | None = None,
    release_subset_path: Path | None = None,
    gate_adjudication_path: Path | None = None,
    candidate_specific_ppa_execution_path: Path | None = None,
    ic_eda_tool_availability_path: Path | None = None,
    ic_eda_tool_attempts_path: Path | None = None,
) -> Dict[str, Any]:
    """Return the fail-closed DFT evidence-gate ledger for a release run."""

    run_dir = Path(run_dir)
    matrix, matrix_path, subset_path = _load_release_matrix(
        run_dir,
        release_matrix_path=release_matrix_path,
        release_subset_path=release_subset_path,
    )
    gate_path = Path(gate_adjudication_path or run_dir / "dft_hardware_closure_gate_adjudication.json")
    execution_path = Path(
        candidate_specific_ppa_execution_path
        or run_dir / "dft_candidate_specific_ppa_execution.json"
    )
    tool_path = Path(ic_eda_tool_availability_path or run_dir / "ic_eda_tool_availability.json")
    tool_attempts_path = Path(
        ic_eda_tool_attempts_path
        or tool_path.with_name("ic_eda_tool_attempts.json")
    )
    gate_adjudication = _load_json(gate_path)
    candidate_specific_execution = _load_json(execution_path)
    tool_availability = _load_json(tool_path)
    tool_attempts = _load_json_value(tool_attempts_path)
    stage_rows_by_candidate = _stage_index(gate_adjudication)
    tool_index = _tool_availability_index(tool_availability)
    tool_attempt_index = _tool_attempt_index(tool_availability, tool_attempts)
    replayable_execution_transcript_refs = _candidate_specific_execution_transcript_refs(
        run_dir,
        candidate_specific_execution,
    )
    candidate_specific_execution_stage_index = _candidate_specific_execution_stage_index(
        candidate_specific_execution,
    )
    candidate_kernel_contexts = _candidate_kernel_contexts(
        stage_rows_by_candidate,
        candidate_specific_execution,
    )
    matrix_rows = _rows(matrix.get("rows", []))

    rows: list[Dict[str, Any]] = []
    stable_blocker_reasons: Counter[str] = Counter()
    replayable_tool_transcript_keys: set[str] = set()
    candidate_specific_execution_ref_keys: set[str] = set()
    tool_availability_source_ref = _tool_availability_source_ref(tool_path)
    for matrix_index, matrix_row in enumerate(matrix_rows):
        candidate_id = str(matrix_row.get("candidate_id") or "")
        workflow_case_id = str(matrix_row.get("workflow_case_id") or "")
        deployment_boundary_id = str(matrix_row.get("deployment_boundary_id") or "")
        target_platform_id = str(matrix_row.get("target_platform_id") or "")
        target = str(
            matrix_row.get("target_platform_kind")
            or _as_mapping(matrix_row.get("target_platform")).get("platform_kind")
            or ""
        ).lower()
        source_matrix_evidence_gate_id = _source_matrix_evidence_gate_id(matrix_row)
        stage_ids = _target_stage_ids_for_matrix_row(matrix_row, target=target)
        unknown_target_platform_kind = target not in TARGET_REQUIRED_STAGE_IDS
        kernel_contexts = candidate_kernel_contexts.get(candidate_id, [])
        if not kernel_contexts:
            kernel_contexts = [{"candidate_id": candidate_id, "kernel_id": "__unbound__"}]
        for stage_id in stage_ids:
            for kernel_context in kernel_contexts:
                kernel_id = str(kernel_context.get("kernel_id") or "")
                candidate_kernel_target_axis_id = _candidate_kernel_target_axis_id(
                    candidate_id,
                    kernel_id,
                    target,
                )
                row_key = {
                    "candidate_id": candidate_id,
                    "kernel_id": kernel_id,
                    "workflow_case_id": workflow_case_id,
                    "deployment_boundary_id": deployment_boundary_id,
                    "target_platform_id": target_platform_id,
                    "evidence_gate_id": stage_id,
                }
                classification = _classification(
                    matrix_row=matrix_row,
                    candidate_id=candidate_id,
                    kernel_id=kernel_id,
                    target=target,
                    stage_id=stage_id,
                    stage_rows_by_candidate=stage_rows_by_candidate,
                    tool_index=tool_index,
                    tool_attempt_index=tool_attempt_index,
                )
                tool_attempt_refs = list(classification["tool_attempt_refs"])
                required_tool = STAGE_REQUIRED_TOOL.get(stage_id)
                required_tool_availability_status = _required_tool_availability_status(
                    tool_index,
                    tool_attempt_refs,
                    required_tool,
                )
                availability_probe_transport = _availability_probe_transports(tool_attempt_refs)
                availability_probe_kernel_ppa_evidence = _availability_probe_kernel_ppa_evidence(
                    tool_attempt_refs
                )
                required_next_evidence = [
                    {
                        **dict(next_item),
                        "availability_prerequisite_status": required_tool_availability_status,
                        "candidate_kernel_specific_gate_required": True,
                        "availability_only_not_kernel_ppa": bool(tool_attempt_refs),
                        "kernel_ppa_evidence": False,
                    }
                    for next_item in classification["required_next_evidence"]
                    if isinstance(next_item, Mapping)
                ]
                replayable_transcript_refs = _replayable_tool_transcript_refs(tool_attempt_refs)
                candidate_specific_execution_refs = _candidate_specific_execution_refs(
                    candidate_specific_execution_stage_index,
                    candidate_id=candidate_id,
                    kernel_id=kernel_id,
                    stage_id=stage_id,
                )
                evidence_refs = list(classification["evidence_refs"]) + list(
                    candidate_specific_execution_refs
                )
                if classification["status"].startswith("blocked"):
                    evidence_refs.append(
                        {
                            **dict(tool_availability_source_ref),
                            "evidence_role": "ic_eda_tool_availability",
                        }
                    )
                for transcript_ref in replayable_transcript_refs:
                    replayable_tool_transcript_keys.add(stable_json_hash(transcript_ref))
                for execution_ref in candidate_specific_execution_refs:
                    candidate_specific_execution_ref_keys.add(stable_json_hash(execution_ref))
                stable_reason_id = _stable_blocker_reason_id(classification)
                if stable_reason_id:
                    stable_blocker_reasons.update([stable_reason_id])
                row_classification = {
                    "source_matrix_status": str(matrix_row.get("status") or ""),
                    "ledger_status": classification["status"],
                    "stable_blocker_reason_id": stable_reason_id,
                    "candidate_workflow_deployment_target_axes_bound": True,
                    "candidate_kernel_axis_bound": kernel_id != "__unbound__",
                    "availability_probe_only": bool(tool_attempt_refs),
                    "claim_upgrade_allowed": False,
                    "replayable_tool_transcript_ref_count": len(replayable_transcript_refs),
                }
                if tool_attempt_refs:
                    row_classification.update(
                        {
                            "required_tool": required_tool,
                            "required_tool_availability_status": (
                                required_tool_availability_status
                            ),
                            "availability_probe_transport": availability_probe_transport,
                            "availability_probe_kernel_ppa_evidence": (
                                availability_probe_kernel_ppa_evidence
                            ),
                        }
                    )
                row = {
                    "schema_version": "dse.dft.candidate_workflow_target_evidence_gate_ledger.row.v1",
                    "row_id": _row_id(row_key),
                    **row_key,
                    "target_platform_kind": target,
                    "evidence_gate_id": stage_id,
                    "evidence_gate": {
                        "evidence_gate_id": stage_id,
                        "gate_family": "dft_hardware_closure",
                        "applies_to_target_platform_kinds": [target],
                        "required_outputs": list(STAGE_REQUIRED_OUTPUTS.get(stage_id, ())),
                        "required_tool": STAGE_REQUIRED_TOOL.get(stage_id),
                    },
                    "workflow_case": _as_mapping(matrix_row.get("workflow_case")),
                    "deployment_boundary": _as_mapping(matrix_row.get("deployment_boundary")),
                    "target_platform": _as_mapping(matrix_row.get("target_platform")),
                    "source_matrix_evidence_gate_id": source_matrix_evidence_gate_id,
                    "target_required_stage_ids": list(stage_ids),
                    "candidate_kernel_target_axis_id": candidate_kernel_target_axis_id,
                    "status": classification["status"],
                    "status_reason": classification["status_reason"],
                    "row_classification": row_classification,
                    "wrong_target_evidence_rejected": classification[
                        "wrong_target_evidence_rejected"
                    ],
                    "evidence_refs": evidence_refs,
                    "tool_attempt_refs": tool_attempt_refs,
                    "tool_attempt_ref_count": len(tool_attempt_refs),
                    "candidate_specific_execution_refs": candidate_specific_execution_refs,
                    "candidate_specific_execution_ref_count": len(
                        candidate_specific_execution_refs
                    ),
                    "ic_eda_tool_availability_ref": dict(tool_availability_source_ref),
                    "blocker_ids": list(dict.fromkeys(classification["blocker_ids"])),
                    "required_next_evidence": required_next_evidence,
                    "source_matrix_row_index": matrix_index,
                    "source_matrix_row_id": matrix_row.get("row_id"),
                    "row_provenance": {
                        "source_matrix_row_hash": stable_json_hash(matrix_row),
                        "source_matrix_evidence_gate_id": source_matrix_evidence_gate_id,
                        "row_key_hash": stable_json_hash(row_key),
                        "candidate_workflow_deployment_target_axes_bound": True,
                        "candidate_kernel_axis_bound": kernel_id != "__unbound__",
                        "candidate_kernel_target_axis_id": candidate_kernel_target_axis_id,
                        "target_specific_gate_set": list(stage_ids),
                    },
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                    "claim_boundary": _CLAIM_BOUNDARY,
                }
                if unknown_target_platform_kind:
                    row["row_classification"]["unknown_target_platform_kind"] = True
                row["row_hash"] = stable_json_hash(
                    {key: value for key, value in row.items() if key != "row_hash"}
                )
                rows.append(row)

    status_counts = Counter(str(row.get("status") or "") for row in rows)
    availability_probe_only_row_count = sum(
        1
        for row in rows
        if _as_mapping(row.get("row_classification")).get("availability_probe_only") is True
    )
    wrong_target_evidence_rejected_row_count = sum(
        1 for row in rows if row.get("wrong_target_evidence_rejected") is True
    )
    smoke_only_not_kernel_ppa_row_count = sum(
        1
        for row in rows
        if "smoke_only" in " ".join(
            [str(row.get("status_reason") or "")]
            + [str(blocker) for blocker in row.get("blocker_ids", []) or []]
        ).lower()
    )
    candidate_kernel_axis_unbound_row_count = sum(
        1
        for row in rows
        if _as_mapping(row.get("row_classification")).get("candidate_kernel_axis_bound")
        is False
    )
    candidate_kernel_axes = {
        (str(row.get("candidate_id") or ""), str(row.get("kernel_id") or ""))
        for row in rows
        if str(row.get("candidate_id") or "") and str(row.get("kernel_id") or "")
    }
    candidate_kernel_target_axes = {
        str(row.get("candidate_kernel_target_axis_id") or "")
        for row in rows
        if str(row.get("candidate_kernel_target_axis_id") or "")
    }
    candidate_kernel_target_axis_counts_by_target = {
        target: sum(
            1
            for axis_id in candidate_kernel_target_axes
            if axis_id.endswith(f"::{target}")
        )
        for target in sorted(
            {str(row.get("target_platform_kind") or "") for row in rows} - {""}
        )
    }
    row_counts_by_candidate_kernel_target_axis = {
        axis_id: sum(
            1
            for row in rows
            if str(row.get("candidate_kernel_target_axis_id") or "") == axis_id
        )
        for axis_id in sorted(candidate_kernel_target_axes)
    }
    row_counts_by_target_platform_kind = {
        target: sum(1 for row in rows if row.get("target_platform_kind") == target)
        for target in sorted(
            {str(row.get("target_platform_kind") or "") for row in rows} - {""}
        )
    }
    parsed_stage_result_refs = _parsed_stage_result_refs_from_rows(rows)
    payload = {
        "schema_version": DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_SCHEMA,
        "generated_at": _now_iso(),
        "release_id": matrix.get("release_id"),
        "run_dir": str(run_dir),
        "report_package_input_contract": build_report_package_input_contract(run_dir),
        "source_artifacts": {
            "candidate_workflow_deployment_target_matrix": _source_ref(matrix_path, required=True),
            "release_subset_manifest": _source_ref(subset_path, required=False),
            "dft_hardware_closure_gate_adjudication": _source_ref(gate_path, required=False),
            "dft_candidate_specific_ppa_execution": _source_ref(execution_path, required=False),
            "ic_eda_tool_availability": _source_ref(tool_path, required=False),
            "ic_eda_tool_attempts": _source_ref(tool_attempts_path, required=False),
        },
        "target_required_stage_ids": {
            target: list(stage_ids)
            for target, stage_ids in TARGET_REQUIRED_STAGE_IDS.items()
        },
        "allowed_row_statuses": list(ROW_STATUSES),
        "matrix_row_count": len(matrix_rows),
        "candidate_ids": sorted({str(row.get("candidate_id") or "") for row in rows} - {""}),
        "candidate_count": len({str(row.get("candidate_id") or "") for row in rows} - {""}),
        "kernel_ids": sorted({str(row.get("kernel_id") or "") for row in rows} - {""}),
        "kernel_count": len({str(row.get("kernel_id") or "") for row in rows} - {""}),
        "candidate_kernel_axis_count": len(candidate_kernel_axes),
        "candidate_kernel_target_axis_count": len(candidate_kernel_target_axes),
        "candidate_kernel_target_axis_counts_by_target": candidate_kernel_target_axis_counts_by_target,
        "workflow_case_ids": sorted({str(row.get("workflow_case_id") or "") for row in rows} - {""}),
        "workflow_case_count": len({str(row.get("workflow_case_id") or "") for row in rows} - {""}),
        "deployment_boundary_ids": sorted({str(row.get("deployment_boundary_id") or "") for row in rows} - {""}),
        "deployment_boundary_count": len({str(row.get("deployment_boundary_id") or "") for row in rows} - {""}),
        "target_platform_ids": sorted({str(row.get("target_platform_id") or "") for row in rows} - {""}),
        "target_platform_kinds": sorted({str(row.get("target_platform_kind") or "") for row in rows} - {""}),
        "evidence_gate_ids": sorted({str(row.get("evidence_gate_id") or "") for row in rows} - {""}),
        "evidence_gate_count": len({str(row.get("evidence_gate_id") or "") for row in rows} - {""}),
        "expected_row_count": sum(
            len(
                _target_stage_ids_for_matrix_row(
                    row,
                    target=str(row.get("target_platform_kind") or "").lower(),
                )
            )
            * max(1, len(candidate_kernel_contexts.get(str(row.get("candidate_id") or ""), [])))
            for row in matrix_rows
        ),
        "row_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "stable_blocker_reason_counts": dict(sorted(stable_blocker_reasons.items())),
        "replayable_tool_transcript_ref_count": len(replayable_tool_transcript_keys),
        "replayable_execution_transcript_ref_count": len(replayable_execution_transcript_refs),
        "replayable_execution_transcript_refs": replayable_execution_transcript_refs,
        "candidate_specific_execution_ref_count": len(candidate_specific_execution_ref_keys),
        "row_counts_by_candidate_kernel_target_axis": row_counts_by_candidate_kernel_target_axis,
        "row_counts_by_target_platform_kind": row_counts_by_target_platform_kind,
        "blocked_row_count": sum(
            int(row.get("status") in {"blocked_missing_input", "blocked_tool_unavailable", "blocked_invalid_evidence"})
            for row in rows
        ),
        "trusted_pass_count": int(status_counts.get("trusted_pass", 0)),
        "trusted_fail_count": int(status_counts.get("trusted_fail", 0)),
        "fail_closed_row_count": len(rows) - int(status_counts.get("trusted_pass", 0)),
        "projection_only_row_count": int(status_counts.get("projection_only_not_claimable", 0)),
        "availability_probe_only_row_count": availability_probe_only_row_count,
        "wrong_target_evidence_rejected_row_count": wrong_target_evidence_rejected_row_count,
        "smoke_only_not_kernel_ppa_row_count": smoke_only_not_kernel_ppa_row_count,
        "candidate_kernel_axis_unbound_row_count": candidate_kernel_axis_unbound_row_count,
        "unknown_target_platform_kind_row_count": sum(
            1
            for row in rows
            if _as_mapping(row.get("row_classification")).get(
                "unknown_target_platform_kind"
            )
            is True
        ),
        "parsed_stage_result_ref_count": len(parsed_stage_result_refs),
        "parsed_stage_result_refs": parsed_stage_result_refs,
        "rows": rows,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    payload["ledger_hash"] = stable_json_hash(
        {key: value for key, value in payload.items() if key != "ledger_hash"}
    )
    return payload


def _expected_row_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(row.get("candidate_id") or ""),
        str(row.get("kernel_id") or ""),
        str(row.get("workflow_case_id") or ""),
        str(row.get("deployment_boundary_id") or ""),
        str(row.get("target_platform_id") or ""),
        str(row.get("evidence_gate_id") or ""),
    )


def validate_dft_candidate_workflow_target_evidence_gate_ledger(
    payload_or_path: Mapping[str, Any] | Path,
) -> Dict[str, Any]:
    payload = (
        _load_json(payload_or_path)
        if isinstance(payload_or_path, Path)
        else dict(payload_or_path)
    )
    blockers: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_SCHEMA:
        blockers.append({"id": "invalid_schema_version"})
    if payload.get("deliverable_complete") is True:
        blockers.append({"id": "ledger_must_not_mark_deliverable_complete"})
    if payload.get("hardware_completion_eligible") is True:
        blockers.append({"id": "ledger_must_not_mark_hardware_completion_eligible"})
    if payload.get("allowed_row_statuses") != list(ROW_STATUSES):
        blockers.append(
            {
                "id": "row_status_vocabulary_mismatch",
                "expected": list(ROW_STATUSES),
                "actual": payload.get("allowed_row_statuses"),
            }
        )
    contract = _as_mapping(payload.get("report_package_input_contract"))
    expected_artifact_names = [
        LEDGER_ARTIFACT_NAME,
        LEDGER_VALIDATION_ARTIFACT_NAME,
        LEDGER_STATUS_ARTIFACT_NAME,
    ]
    if contract.get("schema_version") != (
        DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_REPORT_PACKAGE_CONTRACT_SCHEMA
    ):
        blockers.append({"id": "report_package_input_contract_schema_mismatch"})
    if contract.get("package_id") != "dft_candidate_workflow_target_evidence_gate_ledger":
        blockers.append({"id": "report_package_input_contract_package_id_mismatch"})
    if contract.get("artifact_names") != expected_artifact_names:
        blockers.append(
            {
                "id": "report_package_input_contract_artifact_names_mismatch",
                "expected": expected_artifact_names,
                "actual": contract.get("artifact_names"),
            }
        )
    contract_artifacts = contract.get("artifacts", [])
    if not isinstance(contract_artifacts, list) or len(contract_artifacts) != len(expected_artifact_names):
        blockers.append({"id": "report_package_input_contract_artifact_entries_mismatch"})
    else:
        for artifact in contract_artifacts:
            artifact_mapping = _as_mapping(artifact)
            if artifact_mapping.get("required_for_report_package") is not True:
                blockers.append(
                    {
                        "id": "report_package_input_contract_artifact_not_required",
                        "canonical_name": artifact_mapping.get("canonical_name"),
                    }
                )

    raw_rows = payload.get("rows", [])
    rows = _rows(raw_rows)
    if not isinstance(raw_rows, list):
        blockers.append({"id": "ledger_rows_not_list"})
    elif len(rows) != len(raw_rows):
        blockers.append({"id": "ledger_rows_contain_non_object"})
    if not rows:
        blockers.append({"id": "ledger_has_no_candidate_workflow_target_gate_rows"})
    if int(payload.get("row_count", -1) or -1) != len(rows):
        blockers.append(
            {
                "id": "ledger_row_count_mismatch",
                "declared": payload.get("row_count"),
                "actual": len(rows),
            }
        )
    if int(payload.get("expected_row_count", -1) or -1) != len(rows):
        blockers.append(
            {
                "id": "ledger_expected_row_count_mismatch",
                "declared": payload.get("expected_row_count"),
                "actual": len(rows),
            }
        )

    seen_keys: set[tuple[str, str, str, str, str, str]] = set()
    duplicate_keys: list[tuple[str, str, str, str, str, str]] = []
    expected_by_axis: Dict[tuple[str, str, str, str, str], set[str]] = {}
    observed_by_axis: Dict[tuple[str, str, str, str, str], set[str]] = {}

    for index, row in enumerate(rows):
        key = _expected_row_key(row)
        if key in seen_keys:
            duplicate_keys.append(key)
        seen_keys.add(key)
        axis_key = key[:5]
        target = str(row.get("target_platform_kind") or "").lower()
        stage_id = key[5]
        expected_stage_ids_for_target = set(
            TARGET_REQUIRED_STAGE_IDS.get(target, (UNKNOWN_TARGET_EVIDENCE_GATE_ID,))
        )
        expected_by_axis.setdefault(axis_key, expected_stage_ids_for_target)
        observed_by_axis.setdefault(axis_key, set()).add(stage_id)
        if row.get("status") not in ROW_STATUSES:
            blockers.append(
                {
                    "id": "invalid_ledger_row_status",
                    "row_index": index,
                    "row_id": row.get("row_id"),
                    "status": row.get("status"),
                }
            )
        if not key[0] or not key[1] or not key[2] or not key[3] or not key[4] or not key[5]:
            blockers.append(
                {
                    "id": "ledger_row_missing_axis_value",
                    "row_index": index,
                    "row_id": row.get("row_id"),
                    "row_key": list(key),
                }
            )
        row_classification = _as_mapping(row.get("row_classification"))
        row_is_unknown_target_block = (
            target not in TARGET_REQUIRED_STAGE_IDS
            and stage_id == UNKNOWN_TARGET_EVIDENCE_GATE_ID
            and row.get("status") == "blocked_invalid_evidence"
            and row_classification.get("unknown_target_platform_kind") is True
        )
        if target not in TARGET_REQUIRED_STAGE_IDS and not row_is_unknown_target_block:
            blockers.append(
                {
                    "id": "ledger_row_unknown_target_kind",
                    "row_index": index,
                    "row_id": row.get("row_id"),
                    "target_platform_kind": row.get("target_platform_kind"),
                }
            )
        elif target in TARGET_REQUIRED_STAGE_IDS and stage_id not in TARGET_REQUIRED_STAGE_IDS[target]:
            blockers.append(
                {
                    "id": "ledger_row_gate_target_mismatch",
                    "row_index": index,
                    "row_id": row.get("row_id"),
                    "target_platform_kind": target,
                    "evidence_gate_id": stage_id,
                }
            )
        for field in ("claim_boundary", "evidence_refs", "blocker_ids", "required_next_evidence"):
            if field not in row:
                blockers.append(
                    {"id": "ledger_row_missing_required_field", "row_index": index, "field": field}
                )
        if not isinstance(row.get("evidence_refs", []), list):
            blockers.append({"id": "ledger_row_evidence_refs_not_list", "row_index": index})
        if not isinstance(row.get("blocker_ids", []), list):
            blockers.append({"id": "ledger_row_blocker_ids_not_list", "row_index": index})
        if not isinstance(row.get("required_next_evidence", []), list):
            blockers.append({"id": "ledger_row_required_next_evidence_not_list", "row_index": index})
        if row.get("deliverable_complete") is True or row.get("hardware_completion_eligible") is True:
            blockers.append(
                {
                    "id": "ledger_row_must_not_upgrade_claims",
                    "row_index": index,
                    "row_id": row.get("row_id"),
                }
            )
        if row.get("wrong_target_evidence_rejected") is True and row.get("status") != "blocked_invalid_evidence":
            blockers.append(
                {
                    "id": "wrong_target_rejection_requires_blocked_invalid_evidence",
                    "row_index": index,
                    "row_id": row.get("row_id"),
                }
            )
        if (
            row_classification.get("candidate_kernel_axis_bound") is False
            and row.get("status") == "trusted_pass"
        ):
            blockers.append(
                {
                    "id": "kernel_unbound_row_must_not_trust_pass",
                    "row_index": index,
                    "row_id": row.get("row_id"),
                }
            )
        row_without_hash = {key_name: value for key_name, value in row.items() if key_name != "row_hash"}
        if row.get("row_hash") != stable_json_hash(row_without_hash):
            blockers.append(
                {
                    "id": "ledger_row_hash_mismatch",
                    "row_index": index,
                    "row_id": row.get("row_id"),
                }
            )

    candidate_kernel_axis_unbound_row_count = sum(
        1
        for row in rows
        if _as_mapping(row.get("row_classification")).get("candidate_kernel_axis_bound")
        is False
    )
    unknown_target_platform_kind_row_count = sum(
        1
        for row in rows
        if _as_mapping(row.get("row_classification")).get(
            "unknown_target_platform_kind"
        )
        is True
    )
    candidate_kernel_axes = {
        (str(row.get("candidate_id") or ""), str(row.get("kernel_id") or ""))
        for row in rows
        if str(row.get("candidate_id") or "") and str(row.get("kernel_id") or "")
    }
    stable_blocker_reason_counts = {
        reason: sum(1 for row in rows if _as_mapping(row.get("row_classification")).get("stable_blocker_reason_id") == reason)
        for reason in sorted(
            {
                str(_as_mapping(row.get("row_classification")).get("stable_blocker_reason_id") or "")
                for row in rows
                if str(_as_mapping(row.get("row_classification")).get("stable_blocker_reason_id") or "")
            }
        )
    }
    candidate_kernel_target_axes = {
        str(row.get("candidate_kernel_target_axis_id") or "")
        for row in rows
        if str(row.get("candidate_kernel_target_axis_id") or "")
    }
    candidate_kernel_target_axis_counts_by_target = {
        target: sum(
            1
            for axis_id in candidate_kernel_target_axes
            if axis_id.endswith(f"::{target}")
        )
        for target in sorted(
            {str(row.get("target_platform_kind") or "") for row in rows} - {""}
        )
    }
    row_counts_by_candidate_kernel_target_axis = {
        axis_id: sum(
            1
            for row in rows
            if str(row.get("candidate_kernel_target_axis_id") or "") == axis_id
        )
        for axis_id in sorted(candidate_kernel_target_axes)
    }
    row_counts_by_target_platform_kind = {
        target: sum(1 for row in rows if row.get("target_platform_kind") == target)
        for target in sorted(
            {str(row.get("target_platform_kind") or "") for row in rows} - {""}
        )
    }
    if int(payload.get("candidate_kernel_axis_unbound_row_count", 0) or 0) != candidate_kernel_axis_unbound_row_count:
        blockers.append(
            {
                "id": "candidate_kernel_axis_unbound_row_count_mismatch",
                "declared": payload.get("candidate_kernel_axis_unbound_row_count"),
                "actual": candidate_kernel_axis_unbound_row_count,
            }
        )
    if int(payload.get("unknown_target_platform_kind_row_count", 0) or 0) != unknown_target_platform_kind_row_count:
        blockers.append(
            {
                "id": "unknown_target_platform_kind_row_count_mismatch",
                "declared": payload.get("unknown_target_platform_kind_row_count"),
                "actual": unknown_target_platform_kind_row_count,
            }
        )
    if int(payload.get("candidate_kernel_axis_count", 0) or 0) != len(candidate_kernel_axes):
        blockers.append(
            {
                "id": "candidate_kernel_axis_count_mismatch",
                "declared": payload.get("candidate_kernel_axis_count"),
                "actual": len(candidate_kernel_axes),
            }
        )
    if int(payload.get("candidate_kernel_target_axis_count", 0) or 0) != len(candidate_kernel_target_axes):
        blockers.append(
            {
                "id": "candidate_kernel_target_axis_count_mismatch",
                "declared": payload.get("candidate_kernel_target_axis_count"),
                "actual": len(candidate_kernel_target_axes),
            }
        )
    if payload.get("candidate_kernel_target_axis_counts_by_target") != candidate_kernel_target_axis_counts_by_target:
        blockers.append(
            {
                "id": "candidate_kernel_target_axis_counts_by_target_mismatch",
                "declared": payload.get("candidate_kernel_target_axis_counts_by_target"),
                "actual": candidate_kernel_target_axis_counts_by_target,
            }
        )
    if payload.get("row_counts_by_candidate_kernel_target_axis") != row_counts_by_candidate_kernel_target_axis:
        blockers.append(
            {
                "id": "row_counts_by_candidate_kernel_target_axis_mismatch",
                "declared": payload.get("row_counts_by_candidate_kernel_target_axis"),
                "actual": row_counts_by_candidate_kernel_target_axis,
            }
        )
    if payload.get("row_counts_by_target_platform_kind") != row_counts_by_target_platform_kind:
        blockers.append(
            {
                "id": "row_counts_by_target_platform_kind_mismatch",
                "declared": payload.get("row_counts_by_target_platform_kind"),
                "actual": row_counts_by_target_platform_kind,
            }
        )
    parsed_stage_result_refs = _parsed_stage_result_refs_from_rows(rows)
    if int(payload.get("parsed_stage_result_ref_count", 0) or 0) != len(parsed_stage_result_refs):
        blockers.append(
            {
                "id": "parsed_stage_result_ref_count_mismatch",
                "declared": payload.get("parsed_stage_result_ref_count"),
                "actual": len(parsed_stage_result_refs),
            }
        )
    payload_parsed_refs = payload.get("parsed_stage_result_refs", [])
    if not isinstance(payload_parsed_refs, list) or [
        dict(ref) for ref in payload_parsed_refs if isinstance(ref, Mapping)
    ] != parsed_stage_result_refs:
        blockers.append({"id": "parsed_stage_result_refs_mismatch"})

    if duplicate_keys:
        blockers.append(
            {
                "id": "duplicate_ledger_rows",
                "count": len(duplicate_keys),
                "row_keys": [list(key) for key in duplicate_keys[:20]],
            }
        )
    for axis_key, expected_stage_ids in expected_by_axis.items():
        observed = observed_by_axis.get(axis_key, set())
        if expected_stage_ids != observed:
            blockers.append(
                {
                    "id": "missing_candidate_workflow_target_gate_rows",
                    "axis_key": list(axis_key),
                    "expected_stage_ids": sorted(expected_stage_ids),
                    "observed_stage_ids": sorted(observed),
                }
            )

    expected_hash = stable_json_hash(
        {key: value for key, value in payload.items() if key != "ledger_hash"}
    )
    if payload.get("ledger_hash") != expected_hash:
        blockers.append(
            {
                "id": "ledger_hash_mismatch",
                "expected": expected_hash,
                "actual": payload.get("ledger_hash"),
            }
        )

    return {
        "schema_version": DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_VALIDATION_SCHEMA,
        "valid": not blockers,
        "row_count": len(rows),
        "expected_row_count": payload.get("expected_row_count"),
        "candidate_kernel_axis_count": len(candidate_kernel_axes),
        "candidate_kernel_target_axis_count": len(candidate_kernel_target_axes),
        "candidate_kernel_target_axis_counts_by_target": candidate_kernel_target_axis_counts_by_target,
        "row_counts_by_candidate_kernel_target_axis": row_counts_by_candidate_kernel_target_axis,
        "row_counts_by_target_platform_kind": row_counts_by_target_platform_kind,
        "candidate_kernel_axis_unbound_row_count": candidate_kernel_axis_unbound_row_count,
        "unknown_target_platform_kind_row_count": unknown_target_platform_kind_row_count,
        "parsed_stage_result_ref_count": len(parsed_stage_result_refs),
        "parsed_stage_result_refs": parsed_stage_result_refs,
        "stable_blocker_reason_counts": stable_blocker_reason_counts,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "allowed_row_statuses": list(ROW_STATUSES),
        "deliverable_complete": False,
        "claim_boundary": (
            "Ledger validation checks artifact shape, row coverage, target-specific "
            "gate sets, and fail-closed status vocabulary only. It cannot upgrade "
            "any row into a final FPGA/ASIC deployment claim."
        ),
        "report_package_input_contract": payload.get("report_package_input_contract"),
    }


def write_dft_candidate_workflow_target_evidence_gate_ledger(
    run_dir: Path,
    *,
    release_matrix_path: Path | None = None,
    release_subset_path: Path | None = None,
    gate_adjudication_path: Path | None = None,
    candidate_specific_ppa_execution_path: Path | None = None,
    ic_eda_tool_availability_path: Path | None = None,
    ic_eda_tool_attempts_path: Path | None = None,
) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = build_dft_candidate_workflow_target_evidence_gate_ledger(
        run_dir,
        release_matrix_path=release_matrix_path,
        release_subset_path=release_subset_path,
        gate_adjudication_path=gate_adjudication_path,
        candidate_specific_ppa_execution_path=candidate_specific_ppa_execution_path,
        ic_eda_tool_availability_path=ic_eda_tool_availability_path,
        ic_eda_tool_attempts_path=ic_eda_tool_attempts_path,
    )
    validation = validate_dft_candidate_workflow_target_evidence_gate_ledger(ledger)
    replayable_tool_transcript_refs: list[Dict[str, Any]] = []
    seen_transcript_keys: set[str] = set()
    availability_probe_only_row_count = 0
    claim_upgrade_allowed_count = 0
    for row in ledger.get("rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        row_classification = _as_mapping(row.get("row_classification"))
        if row_classification.get("availability_probe_only") is True:
            availability_probe_only_row_count += 1
        if row_classification.get("claim_upgrade_allowed") is True:
            claim_upgrade_allowed_count += 1
        for ref in row.get("tool_attempt_refs", []) or []:
            if not isinstance(ref, Mapping):
                continue
            transcript_ref = ref.get("raw_command_transcript_ref")
            if not isinstance(transcript_ref, Mapping):
                continue
            copied = dict(transcript_ref)
            key = stable_json_hash(copied)
            if key in seen_transcript_keys:
                continue
            seen_transcript_keys.add(key)
            replayable_tool_transcript_refs.append(copied)
    write_json(run_dir / LEDGER_ARTIFACT_NAME, ledger)
    write_json(run_dir / LEDGER_VALIDATION_ARTIFACT_NAME, validation)
    status = {
        "schema_version": DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "ledger_status": "recorded" if validation["valid"] else "invalid",
        "ledger": LEDGER_ARTIFACT_NAME,
        "validation": LEDGER_VALIDATION_ARTIFACT_NAME,
        "row_count": ledger.get("row_count"),
        "expected_row_count": ledger.get("expected_row_count"),
        "candidate_kernel_axis_count": ledger.get("candidate_kernel_axis_count"),
        "candidate_kernel_target_axis_count": ledger.get(
            "candidate_kernel_target_axis_count"
        ),
        "candidate_kernel_target_axis_counts_by_target": ledger.get(
            "candidate_kernel_target_axis_counts_by_target", {}
        ),
        "status_counts": ledger.get("status_counts", {}),
        "stable_blocker_reason_counts": ledger.get("stable_blocker_reason_counts", {}),
        "replayable_tool_transcript_ref_count": ledger.get(
            "replayable_tool_transcript_ref_count", len(replayable_tool_transcript_refs)
        ),
        "replayable_tool_transcript_refs": replayable_tool_transcript_refs,
        "replayable_execution_transcript_ref_count": ledger.get(
            "replayable_execution_transcript_ref_count", 0
        ),
        "replayable_execution_transcript_refs": ledger.get(
            "replayable_execution_transcript_refs", []
        ),
        "candidate_specific_execution_ref_count": ledger.get(
            "candidate_specific_execution_ref_count", 0
        ),
        "row_counts_by_candidate_kernel_target_axis": ledger.get(
            "row_counts_by_candidate_kernel_target_axis", {}
        ),
        "row_counts_by_target_platform_kind": ledger.get(
            "row_counts_by_target_platform_kind", {}
        ),
        "fail_closed_row_count": ledger.get("fail_closed_row_count"),
        "projection_only_row_count": ledger.get("projection_only_row_count"),
        "wrong_target_evidence_rejected_row_count": ledger.get(
            "wrong_target_evidence_rejected_row_count"
        ),
        "smoke_only_not_kernel_ppa_row_count": ledger.get(
            "smoke_only_not_kernel_ppa_row_count"
        ),
        "candidate_kernel_axis_unbound_row_count": ledger.get(
            "candidate_kernel_axis_unbound_row_count", 0
        ),
        "unknown_target_platform_kind_row_count": ledger.get(
            "unknown_target_platform_kind_row_count", 0
        ),
        "parsed_stage_result_ref_count": ledger.get("parsed_stage_result_ref_count", 0),
        "parsed_stage_result_refs": ledger.get("parsed_stage_result_refs", []),
        "availability_probe_only_row_count": availability_probe_only_row_count,
        "claim_upgrade_allowed_count": claim_upgrade_allowed_count,
        "blocker_count": validation.get("blocker_count", len(validation.get("blockers", []) or [])),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
        "report_package_input_contract": ledger.get("report_package_input_contract"),
    }
    write_json(run_dir / LEDGER_STATUS_ARTIFACT_NAME, status)
    return status


__all__ = [
    "DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_SCHEMA",
    "DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_REPORT_PACKAGE_CONTRACT_SCHEMA",
    "DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_STATUS_SCHEMA",
    "DFT_CANDIDATE_WORKFLOW_TARGET_EVIDENCE_GATE_LEDGER_VALIDATION_SCHEMA",
    "LEDGER_ARTIFACT_NAME",
    "LEDGER_STATUS_ARTIFACT_NAME",
    "LEDGER_VALIDATION_ARTIFACT_NAME",
    "ROW_STATUSES",
    "TARGET_REQUIRED_STAGE_IDS",
    "build_dft_candidate_workflow_target_evidence_gate_ledger",
    "build_report_package_input_contract",
    "validate_dft_candidate_workflow_target_evidence_gate_ledger",
    "write_dft_candidate_workflow_target_evidence_gate_ledger",
]
