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
import re
import shlex
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

_FRESH_SOURCE_BUNDLE_SCHEMA = "dse.dft.hardware_closure.source_bundle_manifest.v1"
_FRESH_SOURCE_BUNDLE_STATUS = "fresh_candidate_specific_source_bundle_recorded"
_FRESH_COMMAND_MANIFEST_STATUS = "fresh_candidate_specific_commands_executed"
_FRESH_TOOL_VERSION_STATUS = "fresh_tool_versions_recorded"

_STAGE_FILE_NAMES: Dict[str, tuple[str, ...]] = {
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
_STAGE_REQUIRED_TOOL = {
    "golden_correctness": "python3",
    "hls_or_rtl_sim": "vcs_or_hls_csim",
    "hls_or_rtl_synth": "hls_or_rtl_synth_tool",
    "vivado_fpga_synth_or_impl": "vivado",
    "dc_asic_synth_timing_area": "dc_shell",
}
_TARGET_STAGE_IDS: Dict[str, tuple[str, ...]] = {
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
_EXCLUSIVE_STAGE_TARGET = {
    "vivado_fpga_synth_or_impl": "fpga",
    "dc_asic_synth_timing_area": "asic",
}


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


def _root_ref(path: Path, *, required: bool = True) -> Dict[str, Any]:
    path = Path(path)
    exists = path.exists() and path.is_dir()
    return {
        "path": str(path),
        "required": required,
        "exists": exists,
        "kind": "directory",
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


def _safe_slug(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    chars = [ch if ch.isalnum() or ch in "._-" else "_" for ch in text]
    return "".join(chars).strip("_") or "unknown"


def _compact_safe_slug(value: Any) -> str:
    """Return the path slug used by fresh candidate-specific execution.

    The parsed-hard-gate tree historically used character-by-character
    replacement, so ``a::b`` becomes ``a__b`` there. Fresh candidate-specific
    evidence directories use the regex-collapsed form from
    ``dft_candidate_specific_ppa_execution``, so ``a::b`` becomes ``a_b``.
    The audit recognizes all variants without making the raw candidate ID a
    filesystem contract.
    """

    text = str(value or "unknown").strip().lower()
    slug = re.sub(r"[^a-z0-9_.-]+", "_", text)
    return slug.strip("_") or "unknown"


def _path_slug_variants(value: Any) -> list[str]:
    variants = [str(value or "unknown"), _safe_slug(value), _compact_safe_slug(value)]
    unique: list[str] = []
    for item in variants:
        if item and item not in unique:
            unique.append(item)
    return unique


def _unit_artifact_dir(
    base_dir: Path,
    root_name: str,
    *,
    candidate_id: str,
    kernel_id: str,
) -> Path:
    """Resolve a candidate/kernel artifact dir across raw and slugged layouts."""

    root = base_dir / root_name
    candidates = [
        root / candidate_slug / kernel_slug
        for candidate_slug in _path_slug_variants(candidate_id)
        for kernel_slug in _path_slug_variants(kernel_id)
    ]
    for path in candidates:
        if path.exists():
            return path
    return root / _compact_safe_slug(candidate_id) / _compact_safe_slug(kernel_id)


def _fallback_candidate_ids(evidence_root: Path) -> list[str]:
    root = evidence_root / "candidate_specific_evidence"
    if not root.exists():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir())


def _kernel_ids(release_gate: Mapping[str, Any]) -> list[str]:
    expected = release_gate.get("expected_kernel_ids")
    if isinstance(expected, list) and expected:
        return sorted(str(item) for item in expected if item)
    return sorted(MAJOR_SCF_KERNEL_IDS)


def _stage_result_path(parsed_root: Path, candidate_id: str, kernel_id: str, stage_id: str) -> Path:
    candidates = [
        parsed_root
        / "parsed_hard_gate_results"
        / candidate_slug
        / kernel_slug
        / f"{stage_slug}_parsed_result.json"
        for candidate_slug in _path_slug_variants(candidate_id)
        for kernel_slug in _path_slug_variants(kernel_id)
        for stage_slug in _path_slug_variants(stage_id)
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return candidates[0]


def _candidate_required_stage_ids(ppa: Mapping[str, Any], candidate_id: str) -> list[str]:
    rows = ppa.get("candidate_rows", [])
    if isinstance(rows, list):
        for row in rows:
            if (
                isinstance(row, Mapping)
                and str(row.get("candidate_id") or "") == candidate_id
                and isinstance(row.get("required_stage_ids"), list)
                and row.get("required_stage_ids")
            ):
                return [str(stage_id) for stage_id in row.get("required_stage_ids", []) if stage_id]
    return list(REQUIRED_STAGE_IDS)


def _infer_target(candidate_id: str, stage_id: str, required_stage_ids: Sequence[str]) -> str:
    """Infer deployment target for a queue row without upgrading claims."""

    exclusive_target = _EXCLUSIVE_STAGE_TARGET.get(stage_id)
    if exclusive_target:
        return exclusive_target
    stage_set = {str(item) for item in required_stage_ids if item}
    has_fpga = "vivado_fpga_synth_or_impl" in stage_set
    has_asic = "dc_asic_synth_timing_area" in stage_set
    if has_fpga and not has_asic:
        return "fpga"
    if has_asic and not has_fpga:
        return "asic"
    lowered = str(candidate_id or "").lower()
    if "fpga" in lowered and "asic" not in lowered:
        return "fpga"
    if "asic" in lowered and "fpga" not in lowered:
        return "asic"
    return "mixed"


def _target_stage_ids(target: str, required_stage_ids: Sequence[str]) -> list[str]:
    if target in _TARGET_STAGE_IDS:
        target_set = set(_TARGET_STAGE_IDS[target])
        return [str(stage_id) for stage_id in required_stage_ids if str(stage_id) in target_set]
    return [str(stage_id) for stage_id in required_stage_ids if stage_id]


def _queue_execution_command(
    run_dir: Path,
    *,
    candidate_id: str,
    kernel_id: str,
    stage_id: str,
) -> str:
    out_dir = (
        run_dir
        / "fresh_candidate_specific_ppa_execution"
        / f"{_safe_slug(candidate_id)}__{_safe_slug(kernel_id)}__{_safe_slug(stage_id)}"
    )
    command = [
        "python3",
        "dse_v2/scripts/dse/run_dft_candidate_specific_ppa_execution.py",
        "--run-dir",
        str(run_dir),
        "--tie-breaker-queue",
        str(run_dir / "dft_hardware_tie_breaker_execution_queue.json"),
        "--out",
        str(out_dir),
        "--candidate-id",
        candidate_id,
        "--kernel-id",
        kernel_id,
        "--stage-id",
        stage_id,
        "--max-units",
        "1",
        "--ssh-target",
        "ic-eda",
    ]
    return " ".join(shlex.quote(str(item)) for item in command)


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


def _source_flow_manifest(
    run_dir: Path,
    evidence_root: Path,
    candidate_input_manifest: Mapping[str, Any],
) -> tuple[Path | None, Dict[str, Any]]:
    raw = candidate_input_manifest.get("source_flow_dir")
    if not raw:
        return None, {}
    source_dir = _resolve_path(evidence_root, raw)
    if not source_dir.exists():
        source_dir = _resolve_path(run_dir, raw)
    manifest_path = source_dir / "manifest.json"
    return manifest_path, _load_json(manifest_path)


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.absolute() == right.absolute()


def _fresh_candidate_specific_source_bundle_handoff(
    *,
    run_dir: Path,
    evidence_root: Path,
    candidate_id: str,
    kernel_id: str,
    source_bundle: Mapping[str, Any],
    command_manifest: Mapping[str, Any],
    tool_versions: Mapping[str, Any],
    candidate_input_manifest: Mapping[str, Any],
) -> bool:
    """Return true when source-flow handoff is backed by fresh per-unit tools.

    Step5 raw materialization necessarily records a ``source_flow_dir`` in the
    candidate-input manifest.  That is a blocker for legacy copied/wrapped smoke
    source flows, but it should not invalidate the fresh candidate-specific
    execution lane when the source bundle, command manifest, and tool-version
    manifest all prove that this exact candidate×kernel work directory was
    regenerated with candidate-shaped parameters.
    """

    raw_source_flow_dir = candidate_input_manifest.get("source_flow_dir")
    fresh_execution_work_dir = source_bundle.get("fresh_execution_work_dir")
    if not raw_source_flow_dir or not fresh_execution_work_dir:
        return False
    if source_bundle.get("schema_version") != _FRESH_SOURCE_BUNDLE_SCHEMA:
        return False
    if source_bundle.get("status") != _FRESH_SOURCE_BUNDLE_STATUS:
        return False
    if source_bundle.get("candidate_id") != candidate_id or source_bundle.get("kernel_id") != kernel_id:
        return False
    if source_bundle.get("candidate_specific_closure") is not True:
        return False
    if source_bundle.get("shared_microkernel_smoke_only") is True:
        return False
    if source_bundle.get("raw_evidence_scope") != "candidate_specific_closure":
        return False
    if command_manifest.get("status") != _FRESH_COMMAND_MANIFEST_STATUS:
        return False
    if command_manifest.get("candidate_id") != candidate_id or command_manifest.get("kernel_id") != kernel_id:
        return False
    if command_manifest.get("candidate_specific_closure") is not True:
        return False
    if command_manifest.get("shared_microkernel_smoke_only") is True:
        return False
    if command_manifest.get("commands_executed") is not True:
        return False
    if tool_versions.get("status") != _FRESH_TOOL_VERSION_STATUS:
        return False
    if tool_versions.get("candidate_id") != candidate_id or tool_versions.get("kernel_id") != kernel_id:
        return False
    if tool_versions.get("candidate_specific_closure") is not True:
        return False
    if tool_versions.get("shared_microkernel_smoke_only") is True:
        return False
    if tool_versions.get("tool_versions_recorded") is not True:
        return False
    source_flow_dir = _resolve_path(evidence_root, raw_source_flow_dir)
    if not source_flow_dir.exists():
        source_flow_dir = _resolve_path(run_dir, raw_source_flow_dir)
    fresh_dir = _resolve_path(evidence_root, fresh_execution_work_dir)
    if not fresh_dir.exists():
        fresh_dir = _resolve_path(run_dir, fresh_execution_work_dir)
    return _same_resolved_path(source_flow_dir, fresh_dir)


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
    parsed_root: Path,
    candidate_id: str,
    kernel_id: str,
    stage_id: str,
    command_manifest: Mapping[str, Any],
    tool_versions: Mapping[str, Any],
    candidate_input_manifest: Mapping[str, Any],
    source_flow_manifest: Mapping[str, Any],
    source_flow_manifest_path: Path | None,
    fresh_source_bundle_handoff: bool,
) -> Dict[str, Any]:
    parsed_path = _stage_result_path(parsed_root, candidate_id, kernel_id, stage_id)
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

    if candidate_input_manifest.get("source_flow_dir") and not fresh_source_bundle_handoff:
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
    if (
        _text_contains_any(_summary_text(candidate_input_manifest), _MATERIALIZED_SOURCE_TERMS)
        and not fresh_source_bundle_handoff
    ):
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
    if (
        source_flow_manifest
        and _text_contains_any(_summary_text(source_flow_manifest), _FORBIDDEN_SOURCE_BOUNDARY_TERMS)
        and not fresh_source_bundle_handoff
    ):
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
        "fresh_candidate_specific_source_bundle_handoff": fresh_source_bundle_handoff,
        "blockers": blockers,
    }


def _unit_audit(
    run_dir: Path,
    *,
    evidence_root: Path,
    parsed_root: Path,
    candidate_id: str,
    kernel_id: str,
    required_stage_ids: Sequence[str] = REQUIRED_STAGE_IDS,
) -> Dict[str, Any]:
    unit_dir = _unit_artifact_dir(
        evidence_root,
        "candidate_specific_evidence",
        candidate_id=candidate_id,
        kernel_id=kernel_id,
    )
    bundle_dir = _unit_artifact_dir(
        evidence_root,
        "candidate_specific_bundles",
        candidate_id=candidate_id,
        kernel_id=kernel_id,
    )
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
    source_flow_manifest_path, source_flow = _source_flow_manifest(run_dir, evidence_root, candidate_input_manifest)
    fresh_source_bundle_handoff = _fresh_candidate_specific_source_bundle_handoff(
        run_dir=run_dir,
        evidence_root=evidence_root,
        candidate_id=candidate_id,
        kernel_id=kernel_id,
        source_bundle=source_bundle,
        command_manifest=command_manifest,
        tool_versions=tool_versions,
        candidate_input_manifest=candidate_input_manifest,
    )

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

    stage_ids = [str(stage_id) for stage_id in required_stage_ids if stage_id]
    stage_rows = [
        _stage_audit(
            run_dir,
            parsed_root=parsed_root,
            candidate_id=candidate_id,
            kernel_id=kernel_id,
            stage_id=stage_id,
            command_manifest=command_manifest,
            tool_versions=tool_versions,
            candidate_input_manifest=candidate_input_manifest,
            source_flow_manifest=source_flow,
            source_flow_manifest_path=source_flow_manifest_path,
            fresh_source_bundle_handoff=fresh_source_bundle_handoff,
        )
        for stage_id in stage_ids
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
        "candidate_bundle_json": str(bundle_dir / "candidate_bundle.json"),
        "required_stage_ids": stage_ids,
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
        "fresh_candidate_specific_source_bundle_handoff": fresh_source_bundle_handoff,
        "stage_rows": stage_rows,
        "blockers": blockers,
        "blocker_ids": sorted({str(item.get("blocker_id")) for item in blockers}),
    }

def _winner_policy_candidate_ids(ppa: Mapping[str, Any]) -> list[str]:
    rows = ppa.get("candidate_rows", [])
    if not isinstance(rows, list):
        return []
    return sorted(
        {
            str(row.get("candidate_id"))
            for row in rows
            if isinstance(row, Mapping)
            and row.get("candidate_id")
            and isinstance(row.get("winner_policy_blockers"), list)
            and row.get("winner_policy_blockers")
        }
    )


def _winner_policy_candidate_kernel_pairs(ppa: Mapping[str, Any]) -> list[Dict[str, str]]:
    pairs: set[tuple[str, str]] = set()
    rows = ppa.get("candidate_rows", [])
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            candidate_id = str(row.get("candidate_id") or "")
            if not candidate_id:
                continue
            for blocker in row.get("winner_policy_blockers", []) or []:
                if not isinstance(blocker, Mapping):
                    continue
                kernel_id = str(blocker.get("kernel_id") or "")
                if kernel_id:
                    pairs.add((candidate_id, kernel_id))
    blockers = ppa.get("winner_policy_blockers", [])
    if isinstance(blockers, list):
        for blocker in blockers:
            if not isinstance(blocker, Mapping):
                continue
            candidate_id = str(blocker.get("candidate_id") or "")
            kernel_id = str(blocker.get("kernel_id") or "")
            if candidate_id and kernel_id:
                pairs.add((candidate_id, kernel_id))
    return [
        {"candidate_id": candidate_id, "kernel_id": kernel_id}
        for candidate_id, kernel_id in sorted(pairs)
    ]


def _tied_candidate_ids(ppa: Mapping[str, Any], candidate_ids: Sequence[str]) -> list[str]:
    # A physical rank tie is not, by itself, evidence that another tool run is
    # actionable. Requeue only candidates with explicit winner-policy blockers
    # such as non-distinguished candidate-parametric source/provenance. Missing
    # or untrusted raw evidence is handled by normal unit/stage checks without
    # forcing already-trusted units back into the fresh-variation queue.
    selected = set(candidate_ids)
    return [candidate_id for candidate_id in _winner_policy_candidate_ids(ppa) if candidate_id in selected]

def _filter_values(values: Sequence[str]) -> set[str]:
    return {str(item) for item in values if str(item)}


def _selected_unit_pairs(
    *,
    candidate_ids: Sequence[str],
    kernel_ids: Sequence[str],
    requested_candidate_ids: Sequence[str],
    requested_kernel_ids: Sequence[str],
    max_units: int | None = None,
) -> tuple[list[tuple[str, str]], Dict[str, Any]]:
    candidate_filter = _filter_values(requested_candidate_ids)
    kernel_filter = _filter_values(requested_kernel_ids)
    all_pairs = [
        (candidate_id, kernel_id)
        for candidate_id in candidate_ids
        for kernel_id in kernel_ids
    ]
    filtered_pairs = [
        (candidate_id, kernel_id)
        for candidate_id, kernel_id in all_pairs
        if (not candidate_filter or candidate_id in candidate_filter)
        and (not kernel_filter or kernel_id in kernel_filter)
    ]
    capped_pairs = list(filtered_pairs)
    unit_budget = max_units if max_units is not None and max_units > 0 else None
    if unit_budget is not None:
        capped_pairs = capped_pairs[:unit_budget]
    return capped_pairs, {
        "candidate_filter": sorted(candidate_filter),
        "kernel_filter": sorted(kernel_filter),
        "max_units": max_units,
        "candidate_count_before_filter": len(candidate_ids),
        "kernel_count_before_filter": len(kernel_ids),
        "unit_count_before_filter": len(all_pairs),
        "unit_count_after_filter_before_max_units": len(filtered_pairs),
        "skipped_by_filter_count": len(all_pairs) - len(filtered_pairs),
        "skipped_by_max_units_count": len(filtered_pairs) - len(capped_pairs),
    }


def build_dft_candidate_specific_ppa_provenance_audit(
    run_dir: Path,
    *,
    evidence_root: Path | None = None,
    parsed_root: Path | None = None,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    max_units: int | None = None,
) -> Dict[str, Any]:
    """Build a fail-closed provenance audit for candidate-specific PPA files."""

    run_dir = Path(run_dir)
    evidence_root = Path(evidence_root or run_dir)
    parsed_root = Path(parsed_root or evidence_root)
    release_gate_path = run_dir / "dft_hardware_closure_release_gate.json"
    ppa_path = run_dir / "dft_hardware_ppa_ranking.json"
    release_gate = _load_json(release_gate_path)
    ppa = _load_json(ppa_path)
    all_candidate_ids = _release_candidate_ids(release_gate) or _fallback_candidate_ids(evidence_root)
    all_kernel_ids = _kernel_ids(release_gate)
    unit_pairs, filter_summary = _selected_unit_pairs(
        candidate_ids=all_candidate_ids,
        kernel_ids=all_kernel_ids,
        requested_candidate_ids=candidate_ids,
        requested_kernel_ids=kernel_ids,
        max_units=max_units,
    )
    selected_candidate_ids = sorted({candidate_id for candidate_id, _kernel_id in unit_pairs})
    selected_kernel_ids = sorted({kernel_id for _candidate_id, kernel_id in unit_pairs})
    selected_pair_set = set(unit_pairs)
    unit_rows = [
        _unit_audit(
            run_dir,
            evidence_root=evidence_root,
            parsed_root=parsed_root,
            candidate_id=candidate_id,
            kernel_id=kernel_id,
            required_stage_ids=_candidate_required_stage_ids(ppa, candidate_id),
        )
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
    tied_candidate_ids = _tied_candidate_ids(ppa, selected_candidate_ids)
    tied_candidate_kernel_pairs = [
        pair
        for pair in _winner_policy_candidate_kernel_pairs(ppa)
        if (str(pair.get("candidate_id")), str(pair.get("kernel_id"))) in selected_pair_set
    ]
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
            "candidate_specific_evidence_root": _root_ref(evidence_root),
            "parsed_hard_gate_results_root": _root_ref(parsed_root),
        },
        "run_dir": str(run_dir),
        "evidence_root": str(evidence_root),
        "parsed_root": str(parsed_root),
        "filter_summary": filter_summary,
        "candidate_count": len(selected_candidate_ids),
        "major_kernel_count": len(selected_kernel_ids),
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
        "candidate_ids": list(selected_candidate_ids),
        "kernel_ids": list(selected_kernel_ids),
        "tied_candidate_ids_requiring_fresh_ppa": tied_candidate_ids,
        "tied_candidate_kernel_pairs_requiring_fresh_ppa": tied_candidate_kernel_pairs,
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
    evidence_root: Path,
    audit_unit_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    candidate_id: str,
    kernel_id: str,
    stage_id: str,
    required_stage_ids: Sequence[str],
) -> Dict[str, Any]:
    unit = audit_unit_by_key.get((candidate_id, kernel_id), {})
    unit_evidence_dir = _unit_artifact_dir(
        evidence_root,
        "candidate_specific_evidence",
        candidate_id=candidate_id,
        kernel_id=kernel_id,
    )
    candidate_bundle_dir = _unit_artifact_dir(
        evidence_root,
        "candidate_specific_bundles",
        candidate_id=candidate_id,
        kernel_id=kernel_id,
    )
    command_manifest = _load_json(unit_evidence_dir / "command_manifest.json")
    template = _command_templates_by_stage(command_manifest).get(stage_id, {})
    target = _infer_target(candidate_id, stage_id, required_stage_ids)
    canonical_outputs = list(_STAGE_FILE_NAMES.get(stage_id, ()))
    template_outputs = [
        str(item)
        for item in template.get("required_outputs", []) or []
        if item
    ]
    command = template.get("command") or _queue_execution_command(
        run_dir,
        candidate_id=candidate_id,
        kernel_id=kernel_id,
        stage_id=stage_id,
    )
    return {
        "work_item_id": f"fresh_ppa:{candidate_id}:{kernel_id}:{stage_id}",
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
        "stage_id": stage_id,
        "target": target,
        "target_stage_ids": _target_stage_ids(target, required_stage_ids),
        "required_tool": _STAGE_REQUIRED_TOOL.get(stage_id) or template.get("tool"),
        "command_template_id": template.get("template_id") or "fresh_candidate_specific_ppa_execution_cli",
        "command": command,
        "alternate_command": template.get("alternate_command"),
        "source_command_template_id": template.get("template_id"),
        "source_required_tool": template.get("tool"),
        "source_command": template.get("command"),
        "source_required_outputs": template_outputs,
        "execution_driver": "dse_v2/scripts/dse/run_dft_candidate_specific_ppa_execution.py",
        "default_ssh_target": "ic-eda",
        "required_outputs": canonical_outputs,
        "required_output_paths": [str(unit_evidence_dir / name) for name in canonical_outputs],
        "candidate_bundle_json": str(candidate_bundle_dir / "candidate_bundle.json"),
        "unit_evidence_dir": str(unit_evidence_dir),
        "existing_unit_provenance_status": unit.get("status"),
        "existing_unit_blocker_ids": unit.get("blocker_ids", []),
        "fresh_execution_required": True,
        "no_shared_evidence_allowed": True,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_hardware_tie_breaker_execution_queue(
    run_dir: Path,
    *,
    provenance_audit: Mapping[str, Any] | None = None,
    evidence_root: Path | None = None,
    parsed_root: Path | None = None,
) -> Dict[str, Any]:
    """Build a queue of fresh tool executions needed to break PPA ties/provenance blockers."""

    run_dir = Path(run_dir)
    evidence_root = Path(evidence_root or run_dir)
    audit = dict(
        provenance_audit
        or build_dft_candidate_specific_ppa_provenance_audit(
            run_dir,
            evidence_root=evidence_root,
            parsed_root=parsed_root,
        )
    )
    fresh_variation_unit_keys = {
        (str(item.get("candidate_id")), str(item.get("kernel_id")))
        for item in audit.get("tied_candidate_kernel_pairs_requiring_fresh_ppa", []) or []
        if isinstance(item, Mapping) and item.get("candidate_id") and item.get("kernel_id")
    }
    candidate_ids = sorted({candidate_id for candidate_id, _ in fresh_variation_unit_keys})
    if not candidate_ids:
        candidate_ids = [str(item) for item in audit.get("tied_candidate_ids_requiring_fresh_ppa", []) or []]
    fresh_variation_candidate_ids = set(candidate_ids)
    if not candidate_ids:
        candidate_ids = [str(item) for item in audit.get("candidate_ids", []) or []]
    kernel_ids = sorted({kernel_id for _, kernel_id in fresh_variation_unit_keys})
    if not kernel_ids:
        kernel_ids = [str(item) for item in audit.get("kernel_ids", []) or []]
    audit_unit_by_key = {
        (str(unit.get("candidate_id")), str(unit.get("kernel_id"))): dict(unit)
        for unit in audit.get("unit_rows", []) or []
        if isinstance(unit, Mapping)
    }
    work_items: list[Dict[str, Any]] = []
    for candidate_id in candidate_ids:
        for kernel_id in kernel_ids:
            if fresh_variation_unit_keys and (candidate_id, kernel_id) not in fresh_variation_unit_keys:
                continue
            unit = audit_unit_by_key.get((candidate_id, kernel_id), {})
            stage_by_id = {
                str(stage.get("stage_id")): dict(stage)
                for stage in unit.get("stage_rows", []) or []
                if isinstance(stage, Mapping)
            }
            required_stage_ids = [
                str(stage_id)
                for stage_id in unit.get("required_stage_ids", []) or []
                if stage_id
            ] or list(REQUIRED_STAGE_IDS)
            for stage_id in required_stage_ids:
                stage = stage_by_id.get(stage_id, {})
                stage_trusted = stage.get("provenance_trusted") is True
                unit_trusted = unit.get("provenance_trusted") is True
                fresh_variation_required = (
                    (candidate_id, kernel_id) in fresh_variation_unit_keys
                    if fresh_variation_unit_keys
                    else candidate_id in fresh_variation_candidate_ids
                )
                if unit_trusted and stage_trusted and not fresh_variation_required:
                    continue
                item = _queue_stage_item(
                    run_dir,
                    evidence_root=evidence_root,
                    audit_unit_by_key=audit_unit_by_key,
                    candidate_id=candidate_id,
                    kernel_id=kernel_id,
                    stage_id=stage_id,
                    required_stage_ids=required_stage_ids,
                )
                if fresh_variation_required:
                    item["fresh_variation_required"] = True
                    item["reason"] = "deployment_tie_or_winner_policy_requires_candidate_varying_ppa"
                work_items.append(item)
    queued_candidate_ids = sorted({str(item.get("candidate_id")) for item in work_items if item.get("candidate_id")})
    queued_kernel_ids = sorted({str(item.get("kernel_id")) for item in work_items if item.get("kernel_id")})
    queued_targets = sorted({str(item.get("target")) for item in work_items if item.get("target")})
    queued_stage_ids = {str(item.get("stage_id")) for item in work_items if item.get("stage_id")}
    target_work_item_counts = {
        target: sum(1 for item in work_items if item.get("target") == target)
        for target in queued_targets
    }
    per_unit_stage_counts: Dict[tuple[str, str], int] = {}
    for item in work_items:
        key = (str(item.get("candidate_id")), str(item.get("kernel_id")))
        per_unit_stage_counts[key] = per_unit_stage_counts.get(key, 0) + 1
    return {
        "schema_version": DFT_HARDWARE_TIE_BREAKER_EXECUTION_QUEUE_SCHEMA,
        "generated_at": _now_iso(),
        "status": "fresh_candidate_specific_ppa_execution_required" if work_items else "no_tie_breaker_work_items",
        "source_artifacts": {
            "provenance_audit": _source_ref(run_dir / "dft_candidate_specific_ppa_provenance_audit.json", required=False),
            "dft_hardware_ppa_ranking": _source_ref(run_dir / "dft_hardware_ppa_ranking.json", required=False),
            "dft_architecture_winner_resolution": _source_ref(run_dir / "dft_architecture_winner_resolution.json", required=False),
        },
        "run_dir": str(run_dir),
        "evidence_root": str(evidence_root),
        "reason": "candidate-specific hard-gate PPA is tied and/or lacks fresh command/tool provenance",
        "candidate_count": len(queued_candidate_ids),
        "major_kernel_count": len(queued_kernel_ids),
        "target_count": len(queued_targets),
        "total_audit_candidate_count": len(candidate_ids),
        "total_audit_major_kernel_count": len(kernel_ids),
        "stage_count_per_unit": max(per_unit_stage_counts.values()) if per_unit_stage_counts else 0,
        "work_item_count": len(work_items),
        "candidate_ids": queued_candidate_ids,
        "kernel_ids": queued_kernel_ids,
        "targets": queued_targets,
        "target_work_item_counts": target_work_item_counts,
        "required_stage_ids": [
            stage_id
            for stage_id in REQUIRED_STAGE_IDS
            if stage_id in queued_stage_ids
        ]
        or list(REQUIRED_STAGE_IDS),
        "fresh_variation_candidate_ids": sorted(fresh_variation_candidate_ids),
        "fresh_variation_unit_keys": [
            {"candidate_id": candidate_id, "kernel_id": kernel_id}
            for candidate_id, kernel_id in sorted(fresh_variation_unit_keys)
        ],
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
    work_items = payload.get("work_items", [])
    if not isinstance(work_items, list):
        errors.append("work_items_not_list")
        work_items = []
    target_counts = payload.get("target_work_item_counts", {})
    if isinstance(target_counts, Mapping) and sum(int(value or 0) for value in target_counts.values()) != len(work_items):
        errors.append("target_work_item_counts_must_sum_to_work_items")
    for index, item in enumerate(work_items):
        if not isinstance(item, Mapping):
            errors.append(f"work_item_{index}_not_object")
            continue
        stage_id = str(item.get("stage_id") or "")
        target = str(item.get("target") or "")
        if not target:
            errors.append(f"work_item_{index}_missing_target")
        elif target in _TARGET_STAGE_IDS and stage_id not in _TARGET_STAGE_IDS[target]:
            errors.append(f"work_item_{index}_stage_not_valid_for_target")
        elif target not in set(_TARGET_STAGE_IDS) | {"mixed"}:
            errors.append(f"work_item_{index}_unknown_target")
        if not item.get("required_tool"):
            errors.append(f"work_item_{index}_missing_required_tool")
        expected_tool = _STAGE_REQUIRED_TOOL.get(stage_id)
        if expected_tool and item.get("required_tool") != expected_tool:
            errors.append(f"work_item_{index}_required_tool_not_canonical")
        expected_outputs = list(_STAGE_FILE_NAMES.get(stage_id, ()))
        if expected_outputs and list(item.get("required_outputs", []) or []) != expected_outputs:
            errors.append(f"work_item_{index}_required_outputs_not_canonical")
        if expected_outputs and len(item.get("required_output_paths", []) or []) != len(expected_outputs):
            errors.append(f"work_item_{index}_required_output_paths_missing")
        if not item.get("command"):
            errors.append(f"work_item_{index}_missing_execution_command")
        if item.get("fresh_execution_required") is not True:
            errors.append(f"work_item_{index}_fresh_execution_required_not_true")
        if item.get("no_shared_evidence_allowed") is not True:
            errors.append(f"work_item_{index}_no_shared_evidence_allowed_not_true")
        if item.get("hardware_completion_eligible") is True or item.get("deliverable_complete") is True:
            errors.append(f"work_item_{index}_must_not_upgrade_claims")
    return {
        "schema_version": "dse.dft.hardware_tie_breaker_execution_queue_validation.v1",
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }

def write_dft_candidate_specific_ppa_provenance_audit(
    run_dir: Path,
    *,
    evidence_root: Path | None = None,
    parsed_root: Path | None = None,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    max_units: int | None = None,
) -> Dict[str, Any]:
    """Write provenance audit, tie-breaker queue, validations, and status."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = Path(evidence_root or run_dir)
    parsed_root = Path(parsed_root or evidence_root)
    audit = build_dft_candidate_specific_ppa_provenance_audit(
        run_dir,
        evidence_root=evidence_root,
        parsed_root=parsed_root,
        candidate_ids=candidate_ids,
        kernel_ids=kernel_ids,
        max_units=max_units,
    )
    validation = validate_dft_candidate_specific_ppa_provenance_audit(audit)
    queue = build_dft_hardware_tie_breaker_execution_queue(
        run_dir,
        provenance_audit=audit,
        evidence_root=evidence_root,
        parsed_root=parsed_root,
    )
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
