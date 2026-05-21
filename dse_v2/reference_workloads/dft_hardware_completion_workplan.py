#!/usr/bin/env python3
"""DFT/QE hardware completion workplan for all-candidate kernel closure.

This DFT-profile helper expands the frozen release candidate/evidence rows into
explicit candidate × kernel × hard-gate work items.  It is an execution ledger:
it can show exactly which real Vivado/DC/VCS/HLS/RTL artifacts are still needed,
but it cannot make hardware completion eligible by itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.codesign.hardware_claim_gates import HARDWARE_CLAIM_REQUIREMENTS
from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNELS

DFT_HARDWARE_COMPLETION_WORKPLAN_SCHEMA = "dse.dft.hardware_completion_workplan.v1"
DFT_HARDWARE_COMPLETION_WORKPLAN_VALIDATION_SCHEMA = "dse.dft.hardware_completion_workplan_validation.v1"

_CLAIM_BOUNDARY = (
    "dft_hardware_completion_workplan.json is a DFT-profile execution plan for "
    "candidate × kernel hard-gate closure. Shared microkernel smoke evidence, "
    "tool availability, and work-item scheduling do not prove candidate-specific "
    "numerical correctness, FPGA implementation, ASIC timing/area, trusted Pareto, "
    "or deliverable completion."
)

_REQUIRED_STAGE_IDS = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)


def _load_json(path: Path | None) -> Dict[str, Any]:
    if path is None or not Path(path).exists():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path | None, *, required: bool) -> Dict[str, Any]:
    if path is None:
        return {
            "path": None,
            "exists": False,
            "required": required,
            "status": "missing_required" if required else "not_attached",
            "sha256": None,
            "hash_algorithm": "sha256",
        }
    candidate = Path(path)
    return {
        "path": str(candidate),
        "exists": candidate.exists() and candidate.is_file(),
        "required": required,
        "status": "present_hash_valid" if candidate.exists() and candidate.is_file() else "missing_required" if required else "not_attached",
        "sha256": sha256_file(candidate) if candidate.exists() and candidate.is_file() else None,
        "hash_algorithm": "sha256",
    }


def _release_candidate_ids(
    per_candidate_evidence_ledger: Mapping[str, Any],
    candidate_binding_map: Mapping[str, Any],
) -> list[str]:
    ids: list[str] = []
    for row in per_candidate_evidence_ledger.get("rows", []) or []:
        if isinstance(row, Mapping) and row.get("candidate_id"):
            ids.append(str(row["candidate_id"]))
    if not ids:
        for row in candidate_binding_map.get("binding_rows", []) or []:
            if isinstance(row, Mapping) and row.get("release_candidate_id"):
                ids.append(str(row["release_candidate_id"]))
    return sorted(set(ids))


def _candidate_universe_path(per_candidate_evidence_ledger_path: Path) -> Path | None:
    run_dir = Path(per_candidate_evidence_ledger_path).parent
    if run_dir.name == "dft_ledger":
        run_dir = run_dir.parent
    candidates = [
        run_dir / "candidate_universe_manifest.json",
        run_dir / "release_domain_current36" / "candidate_universe_manifest.json",
        run_dir / "release_domain" / "candidate_universe_manifest.json",
    ]
    candidates.extend(sorted(run_dir.glob("release_domain*/candidate_universe_manifest.json")))
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def _candidate_metadata_by_id(
    *,
    per_candidate_evidence_ledger: Mapping[str, Any],
    candidate_binding_map: Mapping[str, Any],
    candidate_universe_manifest: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    metadata: Dict[str, Dict[str, Any]] = {}
    for row in candidate_universe_manifest.get("candidates", []) or []:
        if isinstance(row, Mapping) and row.get("candidate_id"):
            metadata[str(row["candidate_id"])] = dict(row)
    for row in per_candidate_evidence_ledger.get("rows", []) or []:
        if not isinstance(row, Mapping) or not row.get("candidate_id"):
            continue
        candidate_id = str(row["candidate_id"])
        existing = metadata.setdefault(candidate_id, {"candidate_id": candidate_id})
        for field in (
            "design_candidate_id",
            "assignments",
            "identity_assignments",
            "non_identity_assignments",
            "applicability_assignments",
            "evaluation_policy_assignments",
        ):
            value = row.get(field)
            if value not in (None, {}, []):
                existing.setdefault(field, value)
    for row in candidate_binding_map.get("binding_rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        candidate_id = str(row.get("release_candidate_id") or row.get("candidate_id") or "")
        if not candidate_id:
            continue
        existing = metadata.setdefault(candidate_id, {"candidate_id": candidate_id})
        if row.get("design_candidate_id"):
            existing.setdefault("design_candidate_id", row.get("design_candidate_id"))
        if isinstance(row.get("release_assignments"), Mapping):
            existing.setdefault("assignments", dict(row["release_assignments"]))
    return metadata


def _tool_rows_by_id(tool_availability: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for row in tool_availability.get("tool_rows", []) or []:
        if isinstance(row, Mapping) and row.get("tool"):
            rows[str(row["tool"]).lower()] = dict(row)
    return rows


def _kernel_rows_by_id(matrix: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for row in matrix.get("kernel_rows", []) or []:
        if isinstance(row, Mapping) and row.get("kernel_id"):
            rows[str(row["kernel_id"])] = dict(row)
    return rows


def _stage_passed(kernel_row: Mapping[str, Any], stage_id: str) -> bool:
    gate = kernel_row.get("hardware_claim_gate", {})
    if not isinstance(gate, Mapping):
        return False
    for stage in gate.get("stage_results", []) or []:
        if isinstance(stage, Mapping) and stage.get("stage_id") == stage_id:
            return stage.get("passed") is True
    return False


def _stage_tool(stage_id: str) -> str | None:
    return {
        "hls_or_rtl_sim": "vcs",
        "hls_or_rtl_synth": "vivado",
        "vivado_fpga_synth_or_impl": "vivado",
        "dc_asic_synth_timing_area": "dc_shell",
    }.get(stage_id)


def _stage_required_evidence(stage_id: str) -> list[str]:
    if stage_id == "dc_asic_synth_timing_area":
        return ["dc_synth", "dc_timing", "dc_area"]
    for stage in HARDWARE_CLAIM_REQUIREMENTS["fpga_asic"]:
        if stage.stage_id == stage_id:
            return list(stage.accepted_evidence_types)
    return [stage_id]


def _build_work_item(
    *,
    candidate_id: str,
    kernel: Mapping[str, Any],
    stage_id: str,
    shared_kernel_row: Mapping[str, Any],
    tool_rows: Mapping[str, Mapping[str, Any]],
    candidate_metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    tool_id = _stage_tool(stage_id)
    tool_available = bool(tool_rows.get(tool_id or "", {}).get("available", False)) if tool_id else True
    shared_stage_passed = _stage_passed(shared_kernel_row, stage_id)
    if stage_id == "dc_asic_synth_timing_area":
        status = "missing_candidate_specific_dc_asic_closure"
        blocker_id = "candidate_specific_dc_asic_closure_missing"
    elif shared_stage_passed:
        status = "shared_microkernel_smoke_present_not_candidate_specific"
        blocker_id = "candidate_specific_stage_evidence_missing"
    elif tool_id and not tool_available:
        status = "tool_unavailable_for_candidate_specific_stage"
        blocker_id = "required_tool_unavailable"
    else:
        status = "candidate_specific_stage_evidence_missing"
        blocker_id = "candidate_specific_stage_evidence_missing"
    return {
        "work_item_id": f"{candidate_id}:{kernel['kernel_id']}:{stage_id}",
        "candidate_id": candidate_id,
        "design_candidate_id": candidate_metadata.get("design_candidate_id"),
        "assignments": dict(candidate_metadata.get("assignments", {}) if isinstance(candidate_metadata.get("assignments"), Mapping) else {}),
        "identity_assignments": dict(candidate_metadata.get("identity_assignments", {}) if isinstance(candidate_metadata.get("identity_assignments"), Mapping) else {}),
        "non_identity_assignments": dict(candidate_metadata.get("non_identity_assignments", {}) if isinstance(candidate_metadata.get("non_identity_assignments"), Mapping) else {}),
        "applicability_assignments": dict(candidate_metadata.get("applicability_assignments", {}) if isinstance(candidate_metadata.get("applicability_assignments"), Mapping) else {}),
        "evaluation_policy_assignments": dict(candidate_metadata.get("evaluation_policy_assignments", {}) if isinstance(candidate_metadata.get("evaluation_policy_assignments"), Mapping) else {}),
        "kernel_id": kernel["kernel_id"],
        "kernel_name": kernel["name"],
        "kernel_family": kernel["kernel_family"],
        "stage_id": stage_id,
        "required_evidence_types": _stage_required_evidence(stage_id),
        "tool_id": tool_id,
        "tool_available": tool_available,
        "shared_microkernel_smoke_stage_passed": shared_stage_passed,
        "candidate_specific_evidence_present": False,
        "status": status,
        "blocked": True,
        "blocker_id": blocker_id,
        "next_action": (
            "run candidate-specific DC synthesis/timing/area with a real target library"
            if stage_id == "dc_asic_synth_timing_area"
            else "run candidate-specific golden/simulation/synthesis/FPGA implementation evidence, not just shared microkernel smoke"
        ),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_hardware_completion_workplan(
    *,
    per_candidate_evidence_ledger_path: Path,
    dft_hardware_evidence_matrix_path: Path | None = None,
    ic_eda_tool_availability_path: Path | None = None,
    candidate_binding_map_path: Path | None = None,
    candidate_universe_manifest_path: Path | None = None,
) -> Dict[str, Any]:
    """Return candidate × kernel hard-gate work items for remaining closure."""

    ledger = _load_json(per_candidate_evidence_ledger_path)
    matrix = _load_json(dft_hardware_evidence_matrix_path)
    tools = _load_json(ic_eda_tool_availability_path)
    binding = _load_json(candidate_binding_map_path)
    universe_path = candidate_universe_manifest_path or _candidate_universe_path(per_candidate_evidence_ledger_path)
    universe = _load_json(universe_path)
    candidate_ids = _release_candidate_ids(ledger, binding)
    metadata_by_id = _candidate_metadata_by_id(
        per_candidate_evidence_ledger=ledger,
        candidate_binding_map=binding,
        candidate_universe_manifest=universe,
    )
    kernel_rows = _kernel_rows_by_id(matrix)
    tool_rows = _tool_rows_by_id(tools)
    work_items: list[Dict[str, Any]] = []
    for candidate_id in candidate_ids:
        for kernel in MAJOR_SCF_KERNELS:
            shared_kernel_row = kernel_rows.get(kernel["kernel_id"], {})
            for stage_id in _REQUIRED_STAGE_IDS:
                work_items.append(
                    _build_work_item(
                        candidate_id=candidate_id,
                        kernel=kernel,
                        stage_id=stage_id,
                        shared_kernel_row=shared_kernel_row,
                        tool_rows=tool_rows,
                        candidate_metadata=metadata_by_id.get(candidate_id, {}),
                    )
                )
    blocker_ids = sorted({str(item["blocker_id"]) for item in work_items if item.get("blocked")})
    return {
        "schema_version": DFT_HARDWARE_COMPLETION_WORKPLAN_SCHEMA,
        "status": "blocked_temporary" if work_items else "failed_no_candidates",
        "release_id": ledger.get("release_id") or binding.get("release_id"),
        "candidate_count": len(candidate_ids),
        "major_kernel_count": len(MAJOR_SCF_KERNELS),
        "required_stage_ids": list(_REQUIRED_STAGE_IDS),
        "required_work_item_count": len(work_items),
        "blocked_work_item_count": sum(1 for item in work_items if item.get("blocked")),
        "candidate_specific_evidence_present_count": sum(1 for item in work_items if item.get("candidate_specific_evidence_present") is True),
        "shared_microkernel_smoke_stage_present_count": sum(1 for item in work_items if item.get("shared_microkernel_smoke_stage_passed") is True),
        "blocker_ids": blocker_ids,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "source_artifacts": {
            "per_candidate_evidence_ledger": _source_ref(per_candidate_evidence_ledger_path, required=True),
            "dft_hardware_evidence_matrix": _source_ref(dft_hardware_evidence_matrix_path, required=False),
            "ic_eda_tool_availability": _source_ref(ic_eda_tool_availability_path, required=False),
            "candidate_binding_map": _source_ref(candidate_binding_map_path, required=False),
            "candidate_universe_manifest": _source_ref(universe_path, required=False),
        },
        "work_items": work_items,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_completion_workplan(workplan: Mapping[str, Any] | Path) -> Dict[str, Any]:
    if isinstance(workplan, Path):
        payload = _load_json(workplan)
    else:
        payload = dict(workplan)
    errors: list[Dict[str, Any]] = []
    rows = payload.get("work_items", [])
    if payload.get("schema_version") != DFT_HARDWARE_COMPLETION_WORKPLAN_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected hardware completion workplan schema"})
    if not isinstance(rows, list) or not rows:
        errors.append({"field": "work_items", "message": "non-empty work_items required"})
        rows = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append({"field": f"work_items[{index}]", "message": "work item must be an object"})
            continue
        work_item_id = str(row.get("work_item_id", ""))
        if not work_item_id:
            errors.append({"field": f"work_items[{index}].work_item_id", "message": "work_item_id required"})
        if work_item_id in seen:
            errors.append({"field": f"work_items[{index}].work_item_id", "message": "duplicate work_item_id"})
        seen.add(work_item_id)
        if row.get("blocked") is not True:
            errors.append({"field": f"work_items[{index}].blocked", "message": "current workplan rows must remain blocked until candidate-specific evidence is attached"})
        if row.get("candidate_specific_evidence_present") is True:
            errors.append({"field": f"work_items[{index}].candidate_specific_evidence_present", "message": "workplan cannot fabricate candidate-specific evidence"})
    if payload.get("hardware_completion_eligible") is True or payload.get("deliverable_complete") is True:
        errors.append({"field": "hardware_completion_eligible", "message": "workplan cannot be hardware-completion or deliverable-complete evidence"})
    return {
        "schema_version": DFT_HARDWARE_COMPLETION_WORKPLAN_VALIDATION_SCHEMA,
        "valid": not errors,
        "work_item_count": len(rows),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_completion_workplan(
    out_dir: Path,
    *,
    per_candidate_evidence_ledger_path: Path,
    dft_hardware_evidence_matrix_path: Path | None = None,
    ic_eda_tool_availability_path: Path | None = None,
    candidate_binding_map_path: Path | None = None,
    candidate_universe_manifest_path: Path | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_completion_workplan(
        per_candidate_evidence_ledger_path=per_candidate_evidence_ledger_path,
        dft_hardware_evidence_matrix_path=dft_hardware_evidence_matrix_path,
        ic_eda_tool_availability_path=ic_eda_tool_availability_path,
        candidate_binding_map_path=candidate_binding_map_path,
        candidate_universe_manifest_path=candidate_universe_manifest_path,
    )
    workplan_path = out_dir / "dft_hardware_completion_workplan.json"
    write_json(workplan_path, payload)
    validation = validate_dft_hardware_completion_workplan(payload)
    write_json(out_dir / "dft_hardware_completion_workplan_validation.json", validation)
    status = {
        "schema_version": "dse.dft.hardware_completion_workplan_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "workplan": "dft_hardware_completion_workplan.json",
        "validation": "dft_hardware_completion_workplan_validation.json",
        "required_work_item_count": payload["required_work_item_count"],
        "blocked_work_item_count": payload["blocked_work_item_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_completion_workplan_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_COMPLETION_WORKPLAN_SCHEMA",
    "DFT_HARDWARE_COMPLETION_WORKPLAN_VALIDATION_SCHEMA",
    "build_dft_hardware_completion_workplan",
    "validate_dft_hardware_completion_workplan",
    "write_dft_hardware_completion_workplan",
]
