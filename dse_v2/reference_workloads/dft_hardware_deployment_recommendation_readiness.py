#!/usr/bin/env python3
"""Fail-closed FPGA/ASIC deployment recommendation readiness for DFT/QE.

This DFT-profile helper summarizes whether the current hardware-closure run is
ready to *name* deployment-specific hardware-PPA winners and, when it is not,
which replayable evidence queues remain.  It deliberately does not surface the
winner objects themselves and never marks the full-SCF deliverable complete.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.reference_workloads.dft_architecture_winner_resolution import (
    validate_dft_architecture_winner_resolution,
)
from dse_v2.reference_workloads.dft_full_scf_numerical_closure import (
    build_full_scf_numerical_readiness_sections,
)
from dse_v2.reference_workloads.dft_full_scf_targeted_accounting import (
    TARGETED_ACCOUNTING_ARTIFACT_NAME,
    TARGETED_ACCOUNTING_STATUS_NAME,
    TARGETED_ACCOUNTING_VALIDATION_NAME,
    summarize_full_scf_targeted_deployment_accounting,
)
from dse_v2.reference_workloads.dft_hardware_deployment_target_selection import (
    validate_dft_hardware_deployment_target_selection,
)


DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_SCHEMA = (
    "dse.dft.hardware_deployment_recommendation_readiness.v1"
)
DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_VALIDATION_SCHEMA = (
    "dse.dft.hardware_deployment_recommendation_readiness_validation.v1"
)
DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_STATUS_SCHEMA = (
    "dse.dft.hardware_deployment_recommendation_readiness_status.v1"
)
DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_SCHEMA = (
    "dse.dft.hardware_deployment_target_selection.v1"
)

_DEPLOYMENTS = ("fpga", "asic")
_DEPLOYMENT_STAGE_IDS = {
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
_DEPLOYMENT_REQUIRED_TOOLS = {
    "fpga": ("vcs", "vivado"),
    "asic": ("vcs", "vivado", "dc_shell"),
}
_TARGET_SELECTION_TRUST_GATE_KEYS = {
    "fpga": "fpga_target_catalog",
    "asic": "asic_target_library_probe",
}
_FORBIDDEN_SHORTCUTS = (
    "candidate-id deterministic tie order",
    "shared route_probe/source-flow evidence reused as candidate winner proof",
    "Step2 design_score or low-fidelity score as final PPA tie-breaker",
    "single-candidate full-SCF accounting bundle used as cross-candidate winner proof",
    "tool-availability records treated as kernel PPA evidence",
    "DC-only evidence used for FPGA deployment claims",
    "Vivado-only evidence used for ASIC deployment claims",
    "hardware-PPA winner named as final deployment without a target device/library selection record",
)
_CLAIM_BOUNDARY = (
    "DFT hardware deployment recommendation readiness aggregates workplan, "
    "tie-breaker, tool-availability, and winner-resolution status into a "
    "replayable next-evidence plan. It may report readiness to name scoped "
    "hardware-PPA winners, but it does not name the winners, does not replace "
    "Vivado/DC/golden evidence, and cannot mark hardware completion, the "
    "full-SCF deliverable, or a final FPGA/ASIC deployment recommendation "
    "complete."
)


_RESERVED_WINNER_KEYS = {
    "winner",
    "winner_candidate_id",
    "best_architecture",
    "fpga_best_architecture",
    "asic_best_architecture",
    "named_winner",
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


def _companion(path: Path | None, suffix: str) -> Path | None:
    if path is None:
        return None
    return Path(path).with_name(suffix)


def _winner_resolution_validation_summary(
    companion_validation: Mapping[str, Any],
    recomputed_validation: Mapping[str, Any],
) -> Dict[str, Any]:
    companion_valid = companion_validation.get("valid") is True
    recomputed_valid = recomputed_validation.get("valid") is True
    errors: list[Dict[str, Any]] = []
    if companion_valid is not True:
        errors.append(
            {
                "source": "dft_architecture_winner_resolution_validation.json",
                "valid": companion_validation.get("valid"),
                "errors": list(companion_validation.get("errors", []) or []),
            }
        )
    if recomputed_valid is not True:
        errors.append(
            {
                "source": "recomputed_dft_architecture_winner_resolution_validation",
                "valid": recomputed_validation.get("valid"),
                "errors": list(recomputed_validation.get("errors", []) or []),
            }
        )
    return {
        "schema_version": (
            "dse.dft.hardware_deployment_recommendation_readiness."
            "winner_resolution_validation_summary.v1"
        ),
        "valid": companion_valid and recomputed_valid,
        "companion_valid": companion_valid,
        "recomputed_valid": recomputed_valid,
        "companion_errors": list(companion_validation.get("errors", []) or []),
        "recomputed_errors": list(recomputed_validation.get("errors", []) or []),
        "errors": errors,
        "claim_boundary": (
            "Deployment readiness revalidates dft_architecture_winner_resolution.json "
            "from the payload itself; a stale passing companion validation cannot "
            "authorize winner naming."
        ),
    }


def _full_scf_artifact_paths(run_dir: Path) -> tuple[Path | None, Path | None, Path | None]:
    comparison = run_dir / "full_scf_end_to_end_comparison.json"
    recheck = run_dir / "full_scf_end_to_end_comparison.recheck.json"
    if comparison.exists() and comparison.is_file():
        return (
            comparison,
            run_dir / "full_scf_end_to_end_comparison_validation.json",
            run_dir / "full_scf_end_to_end_comparison_status.json",
        )
    if recheck.exists() and recheck.is_file():
        return (
            recheck,
            run_dir / "full_scf_end_to_end_comparison.recheck_validation.json",
            run_dir / "full_scf_end_to_end_comparison.recheck_status.json",
        )
    # Default to the canonical artifact names so source refs and workplans expose
    # the missing evidence target directly.
    return (
        comparison,
        run_dir / "full_scf_end_to_end_comparison_validation.json",
        run_dir / "full_scf_end_to_end_comparison_status.json",
    )


def _path_if_exists(path: Path | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    return str(candidate) if candidate.exists() and candidate.is_file() else None


def _resolve_existing_ref_path(run_dir: Path, value: Any) -> Path | None:
    if not value:
        return None
    candidate = Path(str(value))
    if candidate.is_absolute():
        return candidate if candidate.exists() and candidate.is_file() else None
    if candidate.exists() and candidate.is_file():
        return candidate
    run_local = run_dir / candidate
    return run_local if run_local.exists() and run_local.is_file() else None


def _target_selection_validation_summary(
    companion_validation: Mapping[str, Any],
    recomputed_validation: Mapping[str, Any],
    *,
    present: bool,
) -> Dict[str, Any]:
    companion_valid = companion_validation.get("valid") is True
    recomputed_valid = recomputed_validation.get("valid") is True
    errors: list[Dict[str, Any]] = []
    if present and companion_valid is not True:
        errors.append(
            {
                "source": "dft_hardware_deployment_target_selection_validation.json",
                "valid": companion_validation.get("valid"),
                "errors": list(companion_validation.get("errors", []) or []),
            }
        )
    if present and recomputed_valid is not True:
        errors.append(
            {
                "source": "recomputed_dft_hardware_deployment_target_selection_validation",
                "valid": recomputed_validation.get("valid"),
                "errors": list(recomputed_validation.get("errors", []) or []),
            }
        )
    return {
        "schema_version": "dse.dft.hardware_deployment_recommendation_readiness.target_selection_validation_summary.v1",
        "present": present,
        "valid": (companion_valid and recomputed_valid) if present else False,
        "companion_valid": companion_valid if present else None,
        "recomputed_valid": recomputed_valid if present else None,
        "companion_errors": list(companion_validation.get("errors", []) or []) if present else [],
        "recomputed_errors": list(recomputed_validation.get("errors", []) or []) if present else [],
        "errors": errors,
        "claim_boundary": (
            "Deployment readiness revalidates dft_hardware_deployment_target_selection.json "
            "from the payload itself; stale or missing target-selection validation cannot "
            "authorize targeted deployment readiness."
        ),
    }


def _target_selection_input_trust_gate(
    target_selection: Mapping[str, Any],
    deployment: str,
) -> Dict[str, Any]:
    gate_key = _TARGET_SELECTION_TRUST_GATE_KEYS[deployment]
    gates = target_selection.get("input_trust_gates", {})
    gate = gates.get(gate_key, {}) if isinstance(gates, Mapping) else {}
    gate = gate if isinstance(gate, Mapping) else {}
    source_refs = [
        dict(ref)
        for ref in gate.get("source_refs", []) or []
        if isinstance(ref, Mapping)
    ]
    blockers = [
        dict(blocker)
        for blocker in gate.get("blockers", []) or []
        if isinstance(blocker, Mapping)
    ]
    source_ref_count = gate.get("source_ref_count")
    if type(source_ref_count) is not int:
        source_ref_count = len(source_refs)
    return {
        "gate_key": gate_key,
        "trust_class": gate.get("trust_class") or gate_key,
        "present": bool(gate),
        "trusted": gate.get("trusted") is True,
        "source_ref_count": source_ref_count,
        "source_refs": source_refs,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "claim_boundary": (
            "Target-selection input trust gates prove only that the FPGA "
            "catalog or ASIC library/probe input was hash-backed and non-"
            "placeholder. They are deployment-planning evidence, not PPA, "
            "full-SCF, or final recommendation evidence."
        ),
    }


def _target_selection_trust_gates_summary(
    target_selection: Mapping[str, Any],
) -> Dict[str, Any]:
    gates = {
        gate_key: _target_selection_input_trust_gate(target_selection, deployment)
        for deployment, gate_key in _TARGET_SELECTION_TRUST_GATE_KEYS.items()
    }
    present = bool(target_selection) and any(gate.get("present") is True for gate in gates.values())
    return {
        "schema_version": (
            "dse.dft.hardware_deployment_recommendation_readiness."
            "target_selection_trust_gates.v1"
        ),
        "present": present,
        "all_trusted": bool(present and all(gate.get("trusted") is True for gate in gates.values())),
        "gates": gates,
        "claim_boundary": (
            "Deployment target trust gates are carried forward explicitly so "
            "downstream readiness and decision packets can audit selected "
            "target inputs without upgrading targeted/final recommendation or "
            "deliverable claims."
        ),
    }


def _rows(payload: Mapping[str, Any], key: str) -> list[Dict[str, Any]]:
    value = payload.get(key, [])
    return [dict(row) for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _filter_stage_rows(rows: Sequence[Mapping[str, Any]], stage_ids: Sequence[str]) -> list[Dict[str, Any]]:
    allowed = set(stage_ids)
    return [dict(row) for row in rows if str(row.get("stage_id")) in allowed]


def _unique(values: Iterable[Any]) -> list[str]:
    return sorted({str(value) for value in values if value not in (None, "")})


def _scoped_next_evidence(
    items: Sequence[Mapping[str, Any]],
    evidence_scope: str,
) -> list[Dict[str, Any]]:
    scoped: list[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        copied = dict(item)
        copied.setdefault("evidence_scope", evidence_scope)
        scoped.append(copied)
    return scoped


def _next_evidence_items(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _next_evidence_identity(
    item: Mapping[str, Any],
    *,
    default_deployment: str = "",
    default_scope: str = "",
) -> tuple[str, str, str, str]:
    return (
        str(item.get("task_id") or ""),
        str(item.get("deployment") or default_deployment or ""),
        str(item.get("reason") or ""),
        str(item.get("evidence_scope") or default_scope or ""),
    )


def _missing_final_evidence_mirror_identities(
    final_next_evidence: Any,
    required_next_evidence: Any,
    *,
    deployment: str,
) -> list[tuple[str, str, str, str]]:
    expected = Counter(
        _next_evidence_identity(
            item,
            default_deployment=deployment,
            default_scope="final_deployment_recommendation",
        )
        for item in _next_evidence_items(final_next_evidence)
    )
    actual = Counter(
        _next_evidence_identity(item, default_deployment=deployment)
        for item in _next_evidence_items(required_next_evidence)
    )
    missing: list[tuple[str, str, str, str]] = []
    for identity, expected_count in expected.items():
        missing.extend([identity] * max(0, expected_count - actual.get(identity, 0)))
    return missing


def _summarize_workplan(workplan: Mapping[str, Any], stage_ids: Sequence[str]) -> Dict[str, Any]:
    rows = _filter_stage_rows(_rows(workplan, "work_items"), stage_ids)
    blocked_rows = [row for row in rows if row.get("blocked") is True]
    pending_rows = [row for row in rows if row.get("candidate_specific_evidence_present") is not True]
    present_stage_ids = [
        stage_id
        for stage_id in stage_ids
        if any(str(row.get("stage_id")) == stage_id for row in rows)
    ]
    missing_stage_ids = [
        stage_id
        for stage_id in stage_ids
        if stage_id not in present_stage_ids
    ]
    return {
        "present": bool(workplan),
        "release_id": workplan.get("release_id"),
        "candidate_count": workplan.get("candidate_count"),
        "major_kernel_count": workplan.get("major_kernel_count"),
        "stage_ids": list(stage_ids),
        "present_stage_ids": present_stage_ids,
        "missing_stage_ids": missing_stage_ids,
        "stage_coverage_complete": not missing_stage_ids,
        "work_item_count": len(rows),
        "blocked_work_item_count": len(blocked_rows),
        "pending_candidate_specific_work_item_count": len(pending_rows),
        "candidate_specific_evidence_present_count": sum(
            1 for row in rows if row.get("candidate_specific_evidence_present") is True
        ),
        "candidate_count_in_rows": len(_unique(row.get("candidate_id") for row in rows)),
        "kernel_count_in_rows": len(_unique(row.get("kernel_id") for row in rows)),
        "representative_work_item_ids": _unique(row.get("work_item_id") for row in pending_rows)[:20],
    }


def _summarize_queue(queue: Mapping[str, Any], stage_ids: Sequence[str]) -> Dict[str, Any]:
    all_rows = _rows(queue, "work_items")
    if all_rows:
        rows = _filter_stage_rows(all_rows, stage_ids)
        work_item_count = len(rows)
        candidate_ids = _unique(row.get("candidate_id") for row in rows)
        kernel_ids = _unique(row.get("kernel_id") for row in rows)
        representative_ids = _unique(row.get("work_item_id") for row in rows)[:20]
    else:
        # Some status fixtures carry only aggregate counts.  Preserve that count
        # so readiness does not accidentally erase a known pending queue.
        work_item_count = int(queue.get("work_item_count", 0) or 0)
        candidate_ids = _unique(
            queue.get("candidate_ids", [])
            if isinstance(queue.get("candidate_ids", []), list)
            else []
        )
        kernel_ids = _unique(
            queue.get("kernel_ids", [])
            if isinstance(queue.get("kernel_ids", []), list)
            else []
        )
        representative_ids = []
    return {
        "present": bool(queue),
        "status": queue.get("status"),
        "stage_ids": list(stage_ids),
        "work_item_count": work_item_count,
        "candidate_count": len(candidate_ids) if candidate_ids else queue.get("candidate_count"),
        "kernel_count": len(kernel_ids) if kernel_ids else queue.get("major_kernel_count"),
        "candidate_ids": candidate_ids,
        "kernel_ids": kernel_ids,
        "representative_work_item_ids": representative_ids,
    }


def _summarize_full_scf_trusted_queue(queue: Mapping[str, Any]) -> Dict[str, Any]:
    work_items = _rows(queue, "work_items")
    deployment_counts = {deployment: 0 for deployment in _DEPLOYMENTS}
    representative_ids = {deployment: [] for deployment in _DEPLOYMENTS}
    unscoped_ids: list[str] = []
    for row in work_items:
        scopes = [
            str(scope)
            for scope in row.get("target_scopes", []) or []
            if str(scope) in _DEPLOYMENTS
        ]
        if not scopes:
            work_item_id = str(row.get("work_item_id") or "")
            if work_item_id:
                unscoped_ids.append(work_item_id)
            continue
        for deployment in sorted(set(scopes)):
            deployment_counts[deployment] += 1
            work_item_id = str(row.get("work_item_id") or "")
            if work_item_id:
                representative_ids[deployment].append(work_item_id)
    work_item_count = len(work_items) if work_items else int(queue.get("work_item_count", 0) or 0)
    return {
        "present": bool(queue),
        "status": queue.get("status"),
        "queue_materialization_status": queue.get("queue_materialization_status"),
        "execution_required": bool(queue.get("execution_required", False)),
        "work_item_count": work_item_count,
        "candidate_count": queue.get("candidate_count"),
        "strict_scf_class_count": queue.get("strict_scf_class_count"),
        "winner_prioritization_trusted": bool(queue.get("winner_prioritization_trusted", False)),
        "deployment_work_item_counts": deployment_counts,
        "unscoped_work_item_count": max(0, work_item_count - sum(deployment_counts.values())),
        "representative_work_item_ids": {
            deployment: _unique(representative_ids[deployment])[:20]
            for deployment in _DEPLOYMENTS
        },
        "unscoped_representative_work_item_ids": _unique(unscoped_ids)[:20],
        "candidate_ids": _unique(
            queue.get("candidate_ids", [])
            if isinstance(queue.get("candidate_ids", []), list)
            else []
        ),
        "strict_scf_class_ids": _unique(
            queue.get("strict_scf_class_ids", [])
            if isinstance(queue.get("strict_scf_class_ids", []), list)
            else []
        ),
        "source_blocker_id_counts": queue.get("source_blocker_id_counts", {})
        if isinstance(queue.get("source_blocker_id_counts", {}), Mapping)
        else {},
        "trusted_final_claim": False,
        "hardware_completion_eligible": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Trusted full-SCF execution queue is scheduling metadata for real "
            "candidate/class QE/full-SCF runs; it is not final numerical or "
            "deployment evidence."
        ),
    }


def _full_scf_trusted_queue_task(
    deployment: str,
    queue_summary: Mapping[str, Any],
) -> Dict[str, Any] | None:
    counts = queue_summary.get("deployment_work_item_counts", {})
    count = int(counts.get(deployment, 0) or 0) if isinstance(counts, Mapping) else 0
    if count <= 0:
        return None
    representatives = queue_summary.get("representative_work_item_ids", {})
    representative_ids = (
        representatives.get(deployment, [])
        if isinstance(representatives, Mapping)
        else []
    )
    return {
        "task_id": f"{deployment}_run_full_scf_trusted_evidence_execution_queue",
        "deployment": deployment,
        "reason": "full_scf_trusted_execution_queue_pending",
        "queue_work_item_count": count,
        "queue_status": queue_summary.get("status"),
        "representative_work_item_ids": list(representative_ids or [])[:20],
        "required_artifacts": [
            "trusted QE accelerated numeric evidence bundle for each queued strict-SCF class",
            "full_scf_end_to_end_numerical_evidence.json for each queued candidate/class row",
            "runtime_proof.json proving real full-SCF host+accelerator execution",
            "full_scf_end_to_end_comparison.json recheck with the queued rows passing",
        ],
        "required_artifact_paths": [
            "full_scf_trusted_evidence_execution_queue.json",
            "full_scf_numerical_rows/<candidate>/<strict_scf_class>/full_scf_end_to_end_numerical_evidence.json",
            "full_scf_numerical_rows/<candidate>/<strict_scf_class>/runtime_proof.json",
            "full_scf_end_to_end_comparison.json",
        ],
        "acceptance_checks": [
            "queued rows use real QE/full-SCF host+accelerator runtime sources",
            "host-bound, runtime-overhead, and accelerated-kernel costs are populated",
            "density residual and total-energy error checks pass within tolerance",
            "hardware-PPA winner priority is not treated as numerical proof",
        ],
        "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
    }


def _tool_rows(tool_availability: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(row.get("tool")).lower(): dict(row)
        for row in tool_availability.get("tool_rows", []) or []
        if isinstance(row, Mapping) and row.get("tool")
    }


def _tool_readiness(tool_availability: Mapping[str, Any], deployment: str) -> Dict[str, Any]:
    rows = _tool_rows(tool_availability)
    required_tools = list(_DEPLOYMENT_REQUIRED_TOOLS[deployment])
    present = bool(tool_availability)
    available = [tool for tool in required_tools if rows.get(tool, {}).get("available") is True]
    unavailable = [tool for tool in required_tools if tool in rows and rows.get(tool, {}).get("available") is not True]
    unknown = [tool for tool in required_tools if tool not in rows]
    return {
        "present": present,
        "status": (
            "all_required_tools_available"
            if present and not unavailable and not unknown
            else "required_tools_unavailable"
            if present and unavailable
            else "required_tool_availability_unknown"
        ),
        "required_tools": required_tools,
        "available_tools": available,
        "unavailable_tools": unavailable,
        "unknown_tools": unknown,
        "availability_is_execution_precondition_only": True,
        "tool_rows": [rows[tool] for tool in required_tools if tool in rows],
    }


def _target_selection_task(deployment: str, reason: str) -> Dict[str, Any]:
    if deployment == "fpga":
        required_artifacts = [
            "dft_hardware_deployment_target_selection.json with selected FPGA part/SKU",
            "source refs for current device capacity and tool target part",
        ]
        acceptance_checks = [
            "budget policy records unbounded/no-budget selection intent or explicit constraint",
            "selected FPGA target has part/SKU, vendor/family, and capacity fields",
            "candidate PPA rows are checked against the selected target capacity before final recommendation",
        ]
    else:
        required_artifacts = [
            "dft_hardware_deployment_target_selection.json with ASIC process/library/PVT",
            "source refs for target library, process node, voltage, temperature, and timing corner",
        ]
        acceptance_checks = [
            "selected ASIC target records real target library id and PVT corner",
            "DC PPA rows use the same target library/process context",
            "candidate PPA rows are checked against the selected ASIC target before final recommendation",
        ]
    return {
        "task_id": f"{deployment}_attach_deployment_target_selection",
        "deployment": deployment,
        "reason": reason,
        "required_artifacts": required_artifacts,
        "required_artifact_paths": ["dft_hardware_deployment_target_selection.json"],
        "acceptance_checks": acceptance_checks,
        "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
    }


def _target_selection_summary(
    target_selection: Mapping[str, Any],
    deployment: str,
    target_selection_validation: Mapping[str, Any],
    input_trust_gate: Mapping[str, Any],
) -> Dict[str, Any]:
    deployments = target_selection.get("deployments", {})
    item = deployments.get(deployment, {}) if isinstance(deployments, Mapping) else {}
    item = item if isinstance(item, Mapping) else {}
    required_fields = (
        ("target_device_id", "part", "vendor")
        if deployment == "fpga"
        else ("target_library_id", "process_node", "pvt_corner")
    )
    missing_fields = [
        field
        for field in required_fields
        if item.get(field) in (None, "", [])
    ]
    present = bool(target_selection)
    selection_present = bool(item)
    selected = str(item.get("selection_status") or item.get("status") or "").lower() in {
        "selected",
        "passed",
        "ready",
        "target_selected",
    }
    source_refs = [
        dict(ref)
        for ref in item.get("source_refs", []) or []
        if isinstance(ref, Mapping)
    ]
    blockers: list[Dict[str, Any]] = []
    if not present:
        blockers.append({"blocker_id": "deployment_target_selection_missing"})
    elif not selection_present:
        blockers.append({"blocker_id": f"{deployment}_target_selection_missing"})
    if selection_present and not selected:
        blockers.append(
            {
                "blocker_id": f"{deployment}_target_not_selected",
                "selection_status": item.get("selection_status") or item.get("status"),
            }
        )
    if missing_fields:
        blockers.append(
            {
                "blocker_id": f"{deployment}_target_selection_missing_required_fields",
                "missing_fields": missing_fields,
            }
        )
    if selection_present and not source_refs:
        blockers.append({"blocker_id": f"{deployment}_target_selection_missing_source_refs"})
    if selection_present and input_trust_gate.get("trusted") is not True:
        blockers.append(
            {
                "blocker_id": f"{deployment}_target_selection_input_trust_gate_not_trusted",
                "gate_key": input_trust_gate.get("gate_key"),
                "present": input_trust_gate.get("present"),
                "trusted": input_trust_gate.get("trusted"),
                "gate_blockers": list(input_trust_gate.get("blockers", []) or []),
            }
        )
    if present and target_selection_validation.get("valid") is not True:
        blockers.append(
            {
                "blocker_id": "deployment_target_selection_validation_not_valid",
                "validation_valid": target_selection_validation.get("valid"),
                "companion_valid": target_selection_validation.get("companion_valid"),
                "recomputed_valid": target_selection_validation.get("recomputed_valid"),
                "recomputed_errors": list(target_selection_validation.get("recomputed_errors", []) or []),
            }
        )
    status = "target_selection_ready" if not blockers else "target_selection_required"
    return {
        "present": present,
        "selection_present": selection_present,
        "deployment": deployment,
        "status": status,
        "ready_for_targeted_recommendation": not blockers,
        "selection_status": item.get("selection_status") or item.get("status"),
        "budget_policy": item.get("budget_policy") or target_selection.get("budget_policy"),
        "required_fields": list(required_fields),
        "missing_fields": missing_fields,
        "selected_target": {
            key: item.get(key)
            for key in (
                "target_device_id",
                "target_library_id",
                "part",
                "vendor",
                "family",
                "process_node",
                "pvt_corner",
                "voltage_v",
                "temperature_c",
                "capacity",
                "capacity_units",
            )
            if key in item
        },
        "source_ref_count": len(source_refs),
        "source_refs": source_refs,
        "input_trust_gate": dict(input_trust_gate),
        "blockers": blockers,
        "required_next_evidence": [
            _target_selection_task(deployment, blockers[0]["blocker_id"])
        ]
        if blockers
        else [],
        "claim_boundary": (
            "Deployment target selection records FPGA part/SKU or ASIC "
            "library/process context for final recommendation planning only; "
            "it is not candidate PPA or winner evidence."
        ),
    }


def _source_missing_task(source_name: str, ref: Mapping[str, Any], deployment: str) -> Dict[str, Any] | None:
    if ref.get("exists") is True:
        return None
    if ref.get("required") is not True:
        return None
    return {
        "task_id": f"{deployment}_attach_{source_name}",
        "deployment": deployment,
        "reason": f"missing_required_source_artifact:{source_name}",
        "required_artifacts": [f"attach or rebuild {source_name}"],
        "required_artifact_paths": [ref.get("path") or f"<{source_name}>"],
        "acceptance_checks": [f"{source_name} exists and has a validation-valid companion when applicable"],
        "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
    }


def _identity_target(candidate_identity: Mapping[str, Any]) -> str:
    target_platform = candidate_identity.get("target_platform", {})
    if not isinstance(target_platform, Mapping):
        return ""
    return str(target_platform.get("deployment_target") or "")


def _identity_missing_binding_fields(candidate_identity: Mapping[str, Any]) -> list[str]:
    required = (
        "deployment_boundary",
        "host_device_partition",
        "architecture_template_parameters",
        "mapping_layout",
        "runtime_co_scheduling",
        "descriptor_granularity",
        "fallback_policy",
        "target_platform",
    )
    return [
        field
        for field in required
        if not isinstance(candidate_identity.get(field), Mapping)
        or not candidate_identity.get(field)
    ]


def _contains_forbidden_evidence_marker(value: Any) -> bool:
    """Return True for markers that cannot authorize deployment recommendations."""

    forbidden_needles = (
        "projection_only",
        "projection-only",
        "projected_only",
        "stale",
        "shared_microkernel_smoke_only",
        "smoke_only",
        "smoke-only",
        "wrong_target",
    )
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).lower()
            if key_text in {
                "status",
                "reason",
                "blocker_id",
                "evidence_scope",
                "raw_evidence_scope",
                "measurement_source_kind",
                "provenance_status",
            }:
                nested_text = str(nested).lower()
                if any(needle in nested_text for needle in forbidden_needles):
                    return True
            if key_text == "shared_microkernel_smoke_only" and nested is True:
                return True
            if _contains_forbidden_evidence_marker(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_evidence_marker(item) for item in value)
    return False


def _target_ppa_ranking_summary(
    ranking: Mapping[str, Any],
    ranking_validation: Mapping[str, Any],
    deployment: str,
) -> Dict[str, Any]:
    """Summarize deployment-scoped PPA rows required before winner naming."""

    ranking_key = f"{deployment}_ranking"
    rows = [
        dict(row)
        for row in ranking.get(ranking_key, []) or []
        if isinstance(row, Mapping)
    ]
    required_stage_ids = list(_DEPLOYMENT_STAGE_IDS[deployment])
    blockers: list[Dict[str, Any]] = []

    if not ranking:
        blockers.append({"blocker_id": "missing_hardware_ppa_ranking"})
    if ranking_validation.get("valid") is not True:
        blockers.append(
            {
                "blocker_id": "hardware_ppa_ranking_validation_not_valid",
                "valid": ranking_validation.get("valid"),
                "errors": list(ranking_validation.get("errors", []) or []),
            }
        )
    if not rows:
        blockers.append(
            {
                "blocker_id": "missing_candidate_target_ppa_rows",
                "ranking_key": ranking_key,
            }
        )

    wrong_target_rows: list[Dict[str, Any]] = []
    missing_identity_rows: list[Dict[str, Any]] = []
    blocked_or_untrusted_rows: list[Dict[str, Any]] = []
    forbidden_marker_rows: list[Dict[str, Any]] = []
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        candidate_identity = (
            row.get("candidate_identity", {})
            if isinstance(row.get("candidate_identity", {}), Mapping)
            else {}
        )
        row_target = str(row.get("ranking_target") or "")
        identity_target = _identity_target(candidate_identity)
        target_required_stage_ids = [
            str(stage_id)
            for stage_id in row.get("target_required_stage_ids", []) or []
        ]
        row_wrong_target_reasons = []
        if row_target != deployment:
            row_wrong_target_reasons.append("ranking_target_mismatch")
        if identity_target != deployment:
            row_wrong_target_reasons.append("candidate_identity_target_mismatch")
        if target_required_stage_ids and target_required_stage_ids != required_stage_ids:
            row_wrong_target_reasons.append("target_required_stage_ids_mismatch")
        if row_wrong_target_reasons:
            wrong_target_rows.append(
                {
                    "candidate_id": candidate_id,
                    "ranking_target": row_target,
                    "identity_target": identity_target,
                    "target_required_stage_ids": target_required_stage_ids,
                    "reasons": row_wrong_target_reasons,
                }
            )

        missing_fields = _identity_missing_binding_fields(candidate_identity)
        if missing_fields:
            missing_identity_rows.append(
                {
                    "candidate_id": candidate_id,
                    "missing_identity_fields": missing_fields,
                }
            )

        row_blockers = [
            dict(blocker)
            for blocker in (row.get("target_specific_blockers", []) or row.get("blockers", []) or [])
            if isinstance(blocker, Mapping)
        ]
        if row_blockers or row.get("ranking_eligible") is False or row.get("candidate_gate_passed") is False:
            blocked_or_untrusted_rows.append(
                {
                    "candidate_id": candidate_id,
                    "ranking_eligible": row.get("ranking_eligible"),
                    "candidate_gate_passed": row.get("candidate_gate_passed"),
                    "blocker_count": len(row_blockers),
                }
            )
        if _contains_forbidden_evidence_marker(row):
            forbidden_marker_rows.append({"candidate_id": candidate_id})

    if wrong_target_rows:
        blockers.append(
            {
                "blocker_id": "target_ppa_ranking_rows_not_target_scoped",
                "rows": wrong_target_rows,
            }
        )
    if missing_identity_rows:
        blockers.append(
            {
                "blocker_id": "target_ppa_ranking_rows_missing_identity_bindings",
                "rows": missing_identity_rows,
            }
        )
    if blocked_or_untrusted_rows:
        blockers.append(
            {
                "blocker_id": "target_ppa_ranking_rows_not_trusted",
                "rows": blocked_or_untrusted_rows,
            }
        )
    if forbidden_marker_rows:
        blockers.append(
            {
                "blocker_id": "target_ppa_ranking_rows_forbidden_projection_stale_smoke_or_wrong_target",
                "rows": forbidden_marker_rows,
            }
        )

    return {
        "present": bool(ranking),
        "validation_valid": ranking_validation.get("valid") is True,
        "deployment": deployment,
        "ranking_key": ranking_key,
        "row_count": len(rows),
        "candidate_ids": _unique(row.get("candidate_id") for row in rows),
        "required_stage_ids": required_stage_ids,
        "ready": not blockers,
        "blockers": blockers,
        "claim_boundary": (
            "Deployment readiness accepts only target-scoped PPA ranking rows "
            "whose candidate identity binds deployment boundary, partition, "
            "architecture/template parameters, mapping/layout, runtime policy, "
            "descriptor granularity, fallback, and target platform."
        ),
    }


def _target_ppa_required_next_evidence(
    deployment: str,
    blocker: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "task_id": f"{deployment}_attach_target_scoped_hardware_ppa_ranking",
        "deployment": deployment,
        "reason": blocker.get("blocker_id"),
        "required_artifacts": [
            f"dft_hardware_ppa_ranking.json with non-blocked {deployment}_ranking rows",
            "dft_hardware_ppa_ranking_validation.json with valid=true",
            "candidate-specific parsed hard-gate rows for candidate × workflow × deployment-boundary × target",
        ],
        "required_artifact_paths": [
            "dft_hardware_ppa_ranking.json",
            "dft_hardware_ppa_ranking_validation.json",
            "parsed_hard_gate_results/<candidate>/<kernel>/<stage>_parsed_result.json",
        ],
        "acceptance_checks": [
            f"{deployment}_ranking rows carry ranking_target={deployment}",
            f"candidate_identity.target_platform.deployment_target is {deployment}",
            "candidate identity binds deployment boundary, host/device partition, template params, mapping/layout, runtime policy, descriptor granularity, and fallback",
            "rows are not projection-only, stale, blocked, smoke-only, or wrong-target",
        ],
        "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
    }


def _deployment_readiness(
    deployment: str,
    *,
    workplan: Mapping[str, Any],
    queue: Mapping[str, Any],
    freshness_queue: Mapping[str, Any],
    full_scf_trusted_queue_summary: Mapping[str, Any],
    targeted_accounting_summary: Mapping[str, Any],
    hardware_ppa_ranking: Mapping[str, Any],
    hardware_ppa_ranking_validation: Mapping[str, Any],
    winner_resolution: Mapping[str, Any],
    winner_resolution_validation: Mapping[str, Any],
    release_gate: Mapping[str, Any],
    release_gate_validation: Mapping[str, Any],
    tool_availability: Mapping[str, Any],
    target_selection: Mapping[str, Any],
    target_selection_validation: Mapping[str, Any],
    source_artifacts: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    deployments = winner_resolution.get("deployments", {})
    resolution = deployments.get(deployment, {}) if isinstance(deployments, Mapping) else {}
    resolution = resolution if isinstance(resolution, Mapping) else {}
    stage_ids = list(_DEPLOYMENT_STAGE_IDS[deployment])
    workplan_summary = _summarize_workplan(workplan, stage_ids)
    queue_summary = _summarize_queue(queue, stage_ids)
    freshness_queue_summary = _summarize_queue(freshness_queue, stage_ids)
    target_ppa_summary = _target_ppa_ranking_summary(
        hardware_ppa_ranking,
        hardware_ppa_ranking_validation,
        deployment,
    )
    tool_summary = _tool_readiness(tool_availability, deployment)
    target_summary = _target_selection_summary(
        target_selection,
        deployment,
        target_selection_validation,
        _target_selection_input_trust_gate(target_selection, deployment),
    )
    validation_valid = winner_resolution_validation.get("valid") is True
    hardware_winner_resolution_eligible = winner_resolution.get("hardware_winner_resolution_eligible") is True
    resolved = resolution.get("resolved") is True
    release_gate_covers_workplan = bool(
        release_gate.get("hardware_completion_eligible") is True
        and release_gate_validation.get("valid") is True
        and int(release_gate.get("stage_gate_passed_count", 0) or 0) > 0
        and int(release_gate.get("candidate_gate_passed_count", 0) or 0) > 0
        and winner_resolution.get("hardware_completion_eligible") is True
    )
    workplan_summary["covered_by_release_gate"] = release_gate_covers_workplan
    workplan_summary["closure_source"] = (
        "dft_hardware_closure_release_gate"
        if release_gate_covers_workplan
        else "dft_hardware_completion_workplan"
        if workplan_summary.get("present")
        else "missing"
    )
    workplan_summary["release_gate_stage_gate_passed_count"] = release_gate.get("stage_gate_passed_count")
    workplan_summary["release_gate_candidate_gate_passed_count"] = release_gate.get("candidate_gate_passed_count")
    queue_empty = int(queue_summary.get("work_item_count", 0) or 0) == 0
    freshness_queue_empty = int(freshness_queue_summary.get("work_item_count", 0) or 0) == 0
    winner_core_ready = bool(
        hardware_winner_resolution_eligible
        and resolved
        and validation_valid
        and queue_empty
        and freshness_queue_empty
    )

    blockers: list[Dict[str, Any]] = []
    for source_name in (
        "hardware_completion_workplan",
        "hardware_ppa_ranking",
        "hardware_ppa_ranking_validation",
        "architecture_winner_resolution",
        "architecture_winner_resolution_validation",
        "tie_breaker_execution_queue",
    ):
        ref = source_artifacts.get(source_name, {})
        if source_name == "hardware_completion_workplan" and release_gate_covers_workplan:
            continue
        task = _source_missing_task(source_name, ref, deployment)
        if task is not None:
            blockers.append({"blocker_id": task["reason"], "source_artifact": source_name})
    if validation_valid is not True:
        blockers.append(
            {
                "blocker_id": "architecture_winner_resolution_validation_not_valid",
                "valid": winner_resolution_validation.get("valid"),
            }
        )
    if hardware_winner_resolution_eligible is not True:
        blockers.append({"blocker_id": "hardware_winner_resolution_not_eligible"})
    if resolved is not True:
        blockers.append(
            {
                "blocker_id": "deployment_winner_resolution_not_resolved",
                "deployment_status": resolution.get("status"),
                "top_rank_candidate_count": resolution.get("top_rank_candidate_count"),
                "top_rank_design_count": resolution.get("top_rank_design_count"),
            }
        )
    if not queue_empty:
        blockers.append(
            {
                "blocker_id": "fresh_tie_breaker_queue_pending",
                "work_item_count": queue_summary.get("work_item_count"),
            }
        )
    if not freshness_queue_empty:
        blockers.append(
            {
                "blocker_id": "candidate_specific_ppa_freshness_queue_pending",
                "work_item_count": freshness_queue_summary.get("work_item_count"),
                "queue_status": freshness_queue_summary.get("status"),
            }
        )
    if workplan_summary.get("present") is not True and not release_gate_covers_workplan:
        blockers.append({"blocker_id": "hardware_completion_workplan_missing"})
    if int(workplan_summary.get("work_item_count", 0) or 0) == 0 and not release_gate_covers_workplan:
        blockers.append(
            {
                "blocker_id": "deployment_workplan_has_no_stage_rows",
                "stage_ids": stage_ids,
            }
        )
    missing_stage_ids = [
        str(stage_id)
        for stage_id in workplan_summary.get("missing_stage_ids", []) or []
    ]
    if missing_stage_ids and not release_gate_covers_workplan:
        blockers.append(
            {
                "blocker_id": "deployment_workplan_missing_required_stage_rows",
                "missing_stage_ids": missing_stage_ids,
                "required_stage_ids": stage_ids,
            }
        )
    if int(workplan_summary.get("blocked_work_item_count", 0) or 0) and not release_gate_covers_workplan:
        blockers.append(
            {
                "blocker_id": "completion_workplan_has_blocked_stage_rows",
                "blocked_work_item_count": workplan_summary.get("blocked_work_item_count"),
            }
        )
    if (
        int(workplan_summary.get("pending_candidate_specific_work_item_count", 0) or 0)
        and not release_gate_covers_workplan
    ):
        blockers.append(
            {
                "blocker_id": "candidate_kernel_hard_gate_workplan_items_pending",
                "pending_candidate_specific_work_item_count": workplan_summary.get(
                    "pending_candidate_specific_work_item_count"
                ),
            }
        )
    if tool_summary.get("status") != "all_required_tools_available":
        blockers.append(
            {
                "blocker_id": "required_eda_tools_not_available",
                "status": tool_summary.get("status"),
                "unavailable_tools": tool_summary.get("unavailable_tools"),
                "unknown_tools": tool_summary.get("unknown_tools"),
            }
        )
    blockers.extend(dict(blocker) for blocker in target_ppa_summary.get("blockers", []) or [])
    top_rank_candidate_ids = _unique(resolution.get("top_rank_candidate_ids", []))
    target_ppa_candidate_ids = set(target_ppa_summary.get("candidate_ids", []) or [])
    missing_top_rank_candidate_ids = [
        candidate_id
        for candidate_id in top_rank_candidate_ids
        if candidate_id not in target_ppa_candidate_ids
    ]
    if missing_top_rank_candidate_ids:
        blockers.append(
            {
                "blocker_id": "winner_resolution_candidate_missing_target_ppa_row",
                "missing_candidate_ids": missing_top_rank_candidate_ids,
            }
        )

    required_next_evidence = [
        dict(item)
        for item in resolution.get("required_next_evidence", []) or []
        if isinstance(item, Mapping)
    ]
    if resolution.get("required_next_evidence"):
        blockers.append(
            {
                "blocker_id": "winner_resolution_required_next_evidence_present",
                "required_next_evidence_count": len(required_next_evidence),
            }
        )
    for source_name, ref in source_artifacts.items():
        if source_name == "hardware_completion_workplan" and release_gate_covers_workplan:
            continue
        task = _source_missing_task(source_name, ref, deployment)
        if task is not None:
            required_next_evidence.append(task)
    for blocker in target_ppa_summary.get("blockers", []) or []:
        if isinstance(blocker, Mapping):
            required_next_evidence.append(_target_ppa_required_next_evidence(deployment, blocker))
    if missing_top_rank_candidate_ids:
        required_next_evidence.append(
            {
                "task_id": f"{deployment}_align_winner_resolution_with_target_ppa_ranking",
                "deployment": deployment,
                "reason": "winner_resolution_candidate_missing_target_ppa_row",
                "missing_candidate_ids": missing_top_rank_candidate_ids,
                "required_artifacts": [
                    "dft_architecture_winner_resolution.json generated from the same target-scoped PPA ranking artifact"
                ],
                "required_artifact_paths": [
                    "dft_architecture_winner_resolution.json",
                    "dft_hardware_ppa_ranking.json",
                ],
                "acceptance_checks": [
                    "top-rank candidate IDs are present in the deployment-specific PPA ranking rows",
                    "winner resolution and PPA ranking share the same candidate IDs and deployment target",
                ],
                "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
            }
        )
    if queue_summary.get("work_item_count"):
        required_next_evidence.append(
            {
                "task_id": f"{deployment}_run_fresh_tie_breaker_queue",
                "deployment": deployment,
                "reason": "fresh_candidate_specific_ppa_queue_pending",
                "queue_work_item_count": queue_summary.get("work_item_count"),
                "queue_stage_ids": queue_summary.get("stage_ids"),
                "candidate_ids": queue_summary.get("candidate_ids"),
                "kernel_ids": queue_summary.get("kernel_ids"),
                "required_artifacts": [
                    "fresh candidate-specific golden/sim/synth tool outputs",
                    "fresh command manifests, raw transcript indexes, and tool-version records",
                ],
                "required_artifact_paths": [
                    "dft_hardware_tie_breaker_execution_queue.json",
                    "candidate_specific_evidence/<candidate>/<kernel>/command_manifest.json",
                    "candidate_specific_evidence/<candidate>/<kernel>/tool_versions.json",
                    "parsed_hard_gate_results/<candidate>/<kernel>/<stage>_parsed_result.json",
                ],
                "acceptance_checks": [
                    "all queued rows are rerun from candidate-specific source bundles",
                    "shared smoke/source-flow outputs are not reused as winner proof",
                ],
                "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
            }
        )
    if freshness_queue_summary.get("work_item_count"):
        required_next_evidence.append(
            {
                "task_id": f"{deployment}_run_candidate_specific_ppa_freshness_queue",
                "deployment": deployment,
                "reason": "candidate_specific_ppa_freshness_queue_pending",
                "queue_work_item_count": freshness_queue_summary.get("work_item_count"),
                "queue_stage_ids": freshness_queue_summary.get("stage_ids"),
                "candidate_ids": freshness_queue_summary.get("candidate_ids"),
                "kernel_ids": freshness_queue_summary.get("kernel_ids"),
                "required_artifacts": [
                    "fresh candidate-specific PPA reruns newer than the freshness threshold",
                    "updated dft_candidate_specific_ppa_execution.json aggregate",
                    "dft_candidate_specific_ppa_freshness_queue.json with no pending work items",
                ],
                "required_artifact_paths": [
                    "dft_candidate_specific_ppa_freshness_queue.json",
                    "dft_candidate_specific_ppa_execution.json",
                    "candidate_specific_evidence/<candidate>/<kernel>/command_manifest.json",
                ],
                "acceptance_checks": [
                    "freshness queue reports all selected units fresh enough",
                    "stage-scoped rerun rows are closed before deployment readiness",
                ],
                "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
            }
        )
    if int(workplan_summary.get("work_item_count", 0) or 0) == 0 and not release_gate_covers_workplan:
        required_next_evidence.append(
            {
                "task_id": f"{deployment}_attach_completion_workplan_stage_rows",
                "deployment": deployment,
                "reason": "completion_workplan_has_no_deployment_stage_rows",
                "stage_ids": stage_ids,
                "required_artifacts": [
                    "dft_hardware_completion_workplan.json with deployment-specific candidate × kernel × stage rows"
                ],
                "required_artifact_paths": ["dft_hardware_completion_workplan.json"],
                "acceptance_checks": [
                    "workplan contains every required deployment stage for every claimed candidate × major kernel",
                    "each row is superseded by candidate-specific hard-gate evidence before winner naming",
                ],
                "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
            }
        )
    if missing_stage_ids and not release_gate_covers_workplan:
        required_next_evidence.append(
            {
                "task_id": f"{deployment}_attach_missing_completion_workplan_stage_rows",
                "deployment": deployment,
                "reason": "completion_workplan_missing_required_deployment_stages",
                "missing_stage_ids": missing_stage_ids,
                "required_stage_ids": stage_ids,
                "required_artifacts": [
                    "dft_hardware_completion_workplan.json with every required deployment-specific stage"
                ],
                "required_artifact_paths": ["dft_hardware_completion_workplan.json"],
                "acceptance_checks": [
                    "workplan includes golden correctness, simulation, synthesis, and deployment-specific Vivado/DC rows",
                    "missing deployment-specific stage IDs are resolved before hardware-PPA winner naming",
                ],
                "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
            }
        )
    if workplan_summary.get("pending_candidate_specific_work_item_count") and not release_gate_covers_workplan:
        required_next_evidence.append(
            {
                "task_id": f"{deployment}_close_candidate_kernel_workplan",
                "deployment": deployment,
                "reason": "candidate_kernel_hard_gate_workplan_items_pending",
                "workplan_work_item_count": workplan_summary.get("work_item_count"),
                "pending_candidate_specific_work_item_count": workplan_summary.get(
                    "pending_candidate_specific_work_item_count"
                ),
                "representative_work_item_ids": workplan_summary.get("representative_work_item_ids"),
                "required_artifacts": [
                    "candidate-specific hard-gate outputs for every listed candidate × kernel × stage row"
                ],
                "required_artifact_paths": ["dft_hardware_completion_workplan.json"],
                "acceptance_checks": [
                    "workplan rows are superseded by parsed candidate-specific hard-gate evidence",
                    f"{deployment} deployment-specific stages close for every claimed major kernel",
                ],
                "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
            }
        )
    if tool_summary.get("status") != "all_required_tools_available":
        required_next_evidence.append(
            {
                "task_id": f"{deployment}_verify_required_eda_tools",
                "deployment": deployment,
                "reason": tool_summary.get("status"),
                "required_tools": tool_summary.get("required_tools"),
                "unavailable_tools": tool_summary.get("unavailable_tools"),
                "unknown_tools": tool_summary.get("unknown_tools"),
                "required_artifacts": ["ic_eda_tool_availability.json with required tool probes"],
                "required_artifact_paths": ["ic_eda_tool_availability.json"],
                "acceptance_checks": [
                    "tool availability is recorded before running queue rows",
                    "tool availability is not counted as kernel PPA evidence",
                ],
                "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
            }
        )
    final_recommendation_required_next_evidence = list(
        target_summary.get("required_next_evidence", []) or []
    )
    full_scf_queue_task = _full_scf_trusted_queue_task(deployment, full_scf_trusted_queue_summary)
    if full_scf_queue_task is not None:
        final_recommendation_required_next_evidence.append(full_scf_queue_task)
    targeted_accounting_deployments = (
        targeted_accounting_summary.get("deployments", {})
        if isinstance(targeted_accounting_summary.get("deployments", {}), Mapping)
        else {}
    )
    targeted_accounting = (
        targeted_accounting_deployments.get(deployment, {})
        if isinstance(targeted_accounting_deployments.get(deployment, {}), Mapping)
        else {}
    )
    targeted_accounting_ready = targeted_accounting.get("accounting_ready") is True
    if not targeted_accounting_ready:
        final_recommendation_required_next_evidence.append(
            {
                "task_id": f"{deployment}_full_scf_targeted_deployment_accounting",
                "deployment": deployment,
                "reason": "full_scf_targeted_deployment_accounting_required",
                "targeted_accounting_status": targeted_accounting.get("status"),
                "targeted_accounting_blocker_ids": targeted_accounting.get("blocker_ids", []),
                "required_artifacts": [
                    "full-SCF evaluated-hybrid report tied to the selected deployment target",
                    "host-bound, transfer, synchronization, queueing, and layout costs",
                ],
                "required_artifact_paths": [
                    TARGETED_ACCOUNTING_ARTIFACT_NAME,
                    "full_scf_accelerator_descriptor.json",
                    "final_report.json",
                    "dft_hardware_deployment_target_selection.json",
                ],
                "acceptance_checks": [
                    "hardware-PPA winner, target device/library, and full-SCF accounting refer to the same candidate and deployment",
                    "host-bound stages are included and not counted as accelerated benefits",
                ],
                "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
            }
        )
    scoped_hardware_next_evidence = _scoped_next_evidence(
        required_next_evidence,
        "hardware_ppa_winner_readiness",
    )
    scoped_final_next_evidence = _scoped_next_evidence(
        final_recommendation_required_next_evidence,
        "final_deployment_recommendation",
    )
    can_name_hardware_winner = bool(
        winner_core_ready
        and not blockers
        and not required_next_evidence
    )

    status = (
        "ready_to_name_hardware_ppa_winner_not_final_recommendation"
        if can_name_hardware_winner
        else "blocked_deployment_recommendation_evidence_pending"
    )
    return {
        "schema_version": "dse.dft.hardware_deployment_recommendation_readiness.deployment.v1",
        "deployment": deployment,
        "status": status,
        "can_name_winner": can_name_hardware_winner,
        "can_name_hardware_ppa_winner": can_name_hardware_winner,
        "can_name_final_recommendation": False,
        "resolved_by_winner_resolution": resolved,
        "hardware_winner_resolution_eligible": hardware_winner_resolution_eligible,
        "winner_resolution_status": resolution.get("status"),
        "top_rank_candidate_count": resolution.get("top_rank_candidate_count"),
        "top_rank_design_count": resolution.get("top_rank_design_count"),
        "duplicate_top_rank_evaluation_rows_collapsed": resolution.get(
            "duplicate_top_rank_evaluation_rows_collapsed"
        ),
        "target_ppa_ranking": target_ppa_summary,
        "workplan": workplan_summary,
        "tie_breaker_queue": queue_summary,
        "candidate_specific_ppa_freshness_queue": freshness_queue_summary,
        "tool_readiness": tool_summary,
        "target_selection": target_summary,
        "targeted_deployment_accounting": targeted_accounting,
        "can_name_targeted_deployment_recommendation": False,
        "next_runnable_work_item_counts": {
            "completion_workplan": workplan_summary.get("pending_candidate_specific_work_item_count"),
            "tie_breaker_queue": queue_summary.get("work_item_count"),
            "candidate_specific_ppa_freshness_queue": freshness_queue_summary.get("work_item_count"),
            "full_scf_trusted_evidence_execution_queue": (
                full_scf_queue_task.get("queue_work_item_count")
                if full_scf_queue_task is not None
                else 0
            ),
            "deployment_target_selection": 0
            if target_summary.get("ready_for_targeted_recommendation")
            else 1,
            "targeted_deployment_accounting": 0 if targeted_accounting_ready else 1,
        },
        "required_next_evidence": scoped_hardware_next_evidence + scoped_final_next_evidence,
        "final_recommendation_required_next_evidence": scoped_final_next_evidence,
        "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
        "blockers": blockers,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _contains_reserved_winner_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in _RESERVED_WINNER_KEYS:
                return True
            if _contains_reserved_winner_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_reserved_winner_key(item) for item in value)
    return False


def build_dft_hardware_deployment_recommendation_readiness(
    run_dir: Path,
    *,
    hardware_completion_workplan_path: Path | None = None,
    tie_breaker_execution_queue_path: Path | None = None,
    freshness_queue_path: Path | None = None,
    architecture_winner_resolution_path: Path | None = None,
    ic_eda_tool_availability_path: Path | None = None,
    deployment_target_selection_path: Path | None = None,
) -> Dict[str, Any]:
    """Build deployment readiness from fail-closed hardware closure artifacts."""

    run_dir = Path(run_dir)
    workplan_path = Path(hardware_completion_workplan_path) if hardware_completion_workplan_path else run_dir / "dft_hardware_completion_workplan.json"
    queue_path = Path(tie_breaker_execution_queue_path) if tie_breaker_execution_queue_path else run_dir / "dft_hardware_tie_breaker_execution_queue.json"
    freshness_path = Path(freshness_queue_path) if freshness_queue_path else run_dir / "dft_candidate_specific_ppa_freshness_queue.json"
    hardware_ppa_ranking_path = run_dir / "dft_hardware_ppa_ranking.json"
    winner_path = Path(architecture_winner_resolution_path) if architecture_winner_resolution_path else run_dir / "dft_architecture_winner_resolution.json"
    release_gate_path = run_dir / "dft_hardware_closure_release_gate.json"
    release_gate_validation_path = run_dir / "dft_hardware_closure_release_gate_validation.json"
    tool_path = Path(ic_eda_tool_availability_path) if ic_eda_tool_availability_path else run_dir / "ic_eda_tool_availability.json"
    target_path = Path(deployment_target_selection_path) if deployment_target_selection_path else run_dir / "dft_hardware_deployment_target_selection.json"
    full_scf_trusted_queue_path = run_dir / "full_scf_trusted_evidence_execution_queue.json"
    full_scf_trusted_queue_validation_path = run_dir / "full_scf_trusted_evidence_execution_queue_validation.json"
    full_scf_trusted_queue_status_path = run_dir / "full_scf_trusted_evidence_execution_queue_status.json"
    targeted_accounting_path = run_dir / TARGETED_ACCOUNTING_ARTIFACT_NAME
    targeted_accounting_validation_path = run_dir / TARGETED_ACCOUNTING_VALIDATION_NAME
    targeted_accounting_status_path = run_dir / TARGETED_ACCOUNTING_STATUS_NAME
    full_scf_path, full_scf_validation_path, full_scf_status_path = _full_scf_artifact_paths(run_dir)
    workplan_validation_path = _companion(workplan_path, "dft_hardware_completion_workplan_validation.json")
    queue_validation_path = _companion(queue_path, "dft_hardware_tie_breaker_execution_queue_validation.json")
    hardware_ppa_ranking_validation_path = _companion(hardware_ppa_ranking_path, "dft_hardware_ppa_ranking_validation.json")
    winner_validation_path = _companion(winner_path, "dft_architecture_winner_resolution_validation.json")
    target_validation_path = _companion(target_path, "dft_hardware_deployment_target_selection_validation.json")

    workplan = _load_json(workplan_path)
    queue = _load_json(queue_path)
    freshness_queue = _load_json(freshness_path)
    hardware_ppa_ranking = _load_json(hardware_ppa_ranking_path)
    hardware_ppa_ranking_validation = _load_json(hardware_ppa_ranking_validation_path)
    winner_resolution = _load_json(winner_path)
    winner_resolution_validation = _load_json(winner_validation_path)
    release_gate = _load_json(release_gate_path)
    release_gate_validation = _load_json(release_gate_validation_path)
    tool_availability = _load_json(tool_path)
    target_selection = _load_json(target_path)
    if not tool_availability and ic_eda_tool_availability_path is None:
        target_sources = (
            target_selection.get("source_artifacts", {})
            if isinstance(target_selection.get("source_artifacts", {}), Mapping)
            else {}
        )
        tool_ref = (
            target_sources.get("ic_eda_tool_availability", {})
            if isinstance(target_sources.get("ic_eda_tool_availability", {}), Mapping)
            else {}
        )
        inferred_tool_path = _resolve_existing_ref_path(run_dir, tool_ref.get("path"))
        if inferred_tool_path is not None:
            tool_path = inferred_tool_path
            tool_availability = _load_json(tool_path)
    full_scf_trusted_queue = _load_json(full_scf_trusted_queue_path)
    targeted_accounting = _load_json(targeted_accounting_path)
    targeted_accounting_validation = _load_json(targeted_accounting_validation_path)
    targeted_accounting_status = _load_json(targeted_accounting_status_path)
    full_scf = _load_json(full_scf_path)
    full_scf_validation = _load_json(full_scf_validation_path)
    full_scf_status = _load_json(full_scf_status_path)
    full_scf_sections = build_full_scf_numerical_readiness_sections(
        full_scf,
        validation=full_scf_validation,
        status_artifact=full_scf_status,
        artifact=_path_if_exists(full_scf_path),
        validation_artifact=_path_if_exists(full_scf_validation_path),
        status_artifact_path=_path_if_exists(full_scf_status_path),
    )
    full_scf_trusted_queue_summary = _summarize_full_scf_trusted_queue(full_scf_trusted_queue)
    targeted_accounting_summary = summarize_full_scf_targeted_deployment_accounting(
        targeted_accounting,
        validation=targeted_accounting_validation,
    )
    targeted_accounting_summary["status_artifact_status"] = targeted_accounting_status.get("status")
    recomputed_winner_resolution_validation = (
        validate_dft_architecture_winner_resolution(winner_resolution)
        if winner_resolution
        else {}
    )
    winner_resolution_validation_summary = _winner_resolution_validation_summary(
        winner_resolution_validation,
        recomputed_winner_resolution_validation,
    )
    target_selection_validation = _load_json(target_validation_path)
    recomputed_target_selection_validation = (
        validate_dft_hardware_deployment_target_selection(target_selection)
        if target_selection
        else {}
    )
    target_selection_validation_summary = _target_selection_validation_summary(
        target_selection_validation,
        recomputed_target_selection_validation,
        present=bool(target_selection),
    )
    target_selection_trust_gates = _target_selection_trust_gates_summary(target_selection)
    source_artifacts = {
        "hardware_completion_workplan": _source_ref(workplan_path, required=True),
        "hardware_completion_workplan_validation": _source_ref(workplan_validation_path, required=False),
        "hardware_closure_release_gate": _source_ref(release_gate_path, required=False),
        "hardware_closure_release_gate_validation": _source_ref(release_gate_validation_path, required=False),
        "tie_breaker_execution_queue": _source_ref(queue_path, required=True),
        "tie_breaker_execution_queue_validation": _source_ref(queue_validation_path, required=False),
        "candidate_specific_ppa_freshness_queue": _source_ref(freshness_path, required=False),
        "hardware_ppa_ranking": _source_ref(hardware_ppa_ranking_path, required=True),
        "hardware_ppa_ranking_validation": _source_ref(hardware_ppa_ranking_validation_path, required=True),
        "architecture_winner_resolution": _source_ref(winner_path, required=True),
        "architecture_winner_resolution_validation": _source_ref(winner_validation_path, required=True),
        "ic_eda_tool_availability": _source_ref(tool_path, required=False),
        "deployment_target_selection": _source_ref(target_path, required=False),
        "deployment_target_selection_validation": _source_ref(target_validation_path, required=False),
        "full_scf_end_to_end_comparison": _source_ref(full_scf_path, required=False),
        "full_scf_end_to_end_comparison_validation": _source_ref(full_scf_validation_path, required=False),
        "full_scf_end_to_end_comparison_status": _source_ref(full_scf_status_path, required=False),
        "full_scf_trusted_evidence_execution_queue": _source_ref(full_scf_trusted_queue_path, required=False),
        "full_scf_trusted_evidence_execution_queue_validation": _source_ref(
            full_scf_trusted_queue_validation_path,
            required=False,
        ),
        "full_scf_trusted_evidence_execution_queue_status": _source_ref(
            full_scf_trusted_queue_status_path,
            required=False,
        ),
        "full_scf_targeted_deployment_accounting": _source_ref(
            targeted_accounting_path,
            required=False,
        ),
        "full_scf_targeted_deployment_accounting_validation": _source_ref(
            targeted_accounting_validation_path,
            required=False,
        ),
        "full_scf_targeted_deployment_accounting_status": _source_ref(
            targeted_accounting_status_path,
            required=False,
        ),
    }
    deployments = {
        deployment: _deployment_readiness(
            deployment,
            workplan=workplan,
            queue=queue,
            freshness_queue=freshness_queue,
            full_scf_trusted_queue_summary=full_scf_trusted_queue_summary,
            targeted_accounting_summary=targeted_accounting_summary,
            hardware_ppa_ranking=hardware_ppa_ranking,
            hardware_ppa_ranking_validation=hardware_ppa_ranking_validation,
            winner_resolution=winner_resolution,
            winner_resolution_validation=winner_resolution_validation_summary,
            release_gate=release_gate,
            release_gate_validation=release_gate_validation,
            tool_availability=tool_availability,
            target_selection=target_selection,
            target_selection_validation=target_selection_validation_summary,
            source_artifacts=source_artifacts,
        )
        for deployment in _DEPLOYMENTS
    }
    can_name_fpga = deployments["fpga"].get("can_name_hardware_ppa_winner") is True
    can_name_asic = deployments["asic"].get("can_name_hardware_ppa_winner") is True
    target_selection_ready = all(
        deployments[deployment]
        .get("target_selection", {})
        .get("ready_for_targeted_recommendation")
        is True
        for deployment in _DEPLOYMENTS
    )
    status = (
        "ready_to_name_hardware_ppa_winners_not_final_recommendation"
        if can_name_fpga and can_name_asic
        else "blocked_deployment_recommendation_evidence_pending"
    )
    return {
        "schema_version": DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_SCHEMA,
        "generated_at": _now_iso(),
        "status": status,
        "source_artifacts": source_artifacts,
        "release_id": winner_resolution.get("release_id") or workplan.get("release_id"),
        "candidate_count": winner_resolution.get("candidate_count") or workplan.get("candidate_count"),
        "ranking_eligible_candidate_count": winner_resolution.get("ranking_eligible_candidate_count"),
        "architecture_winner_resolution_validation": winner_resolution_validation_summary,
        "deployment_target_selection_validation": target_selection_validation_summary,
        "deployment_target_selection_trust_gates": target_selection_trust_gates,
        "deployments": deployments,
        "fpga_can_name_winner": can_name_fpga,
        "asic_can_name_winner": can_name_asic,
        "can_name_hardware_ppa_winners": bool(can_name_fpga and can_name_asic),
        "deployment_target_selection_ready": target_selection_ready,
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "hardware_completion_eligible": False,
        "upstream_winner_resolution_hardware_completion_eligible": bool(
            winner_resolution.get("hardware_completion_eligible", False)
        ),
        "release_gate_hardware_completion_eligible": bool(
            release_gate.get("hardware_completion_eligible", False)
        ),
        "release_gate_validation_valid": release_gate_validation.get("valid"),
        "hardware_winner_resolution_eligible": bool(
            winner_resolution.get("hardware_winner_resolution_eligible", False)
        ),
        "deliverable_complete": False,
        "required_next_evidence": {
            deployment: deployments[deployment].get("required_next_evidence", [])
            for deployment in _DEPLOYMENTS
        },
        "final_recommendation_required_next_evidence": {
            deployment: deployments[deployment].get(
                "final_recommendation_required_next_evidence",
                [],
            )
            for deployment in _DEPLOYMENTS
        },
        "next_runnable_work_item_counts": {
            deployment: deployments[deployment].get("next_runnable_work_item_counts", {})
            for deployment in _DEPLOYMENTS
        },
        "full_scf_numerical_gate": full_scf_sections["full_scf_numerical_gate"],
        "full_scf_numerical_closure_workplan": full_scf_sections["full_scf_numerical_closure_workplan"],
        "full_scf_trusted_evidence_execution_queue": full_scf_trusted_queue_summary,
        "full_scf_targeted_deployment_accounting": targeted_accounting_summary,
        "release_completion_gates": full_scf_sections["release_completion_gates"],
        "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
        "completion_claim": (
            "hardware_ppa_winner_names_ready_not_final_recommendation"
            if can_name_fpga and can_name_asic
            else "blocked"
        ),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _validate_full_scf_readiness_sections(payload: Mapping[str, Any], errors: list[str]) -> None:
    forbidden_true_fields = {
        "trusted_final_claim",
        "deliverable_complete",
        "release_completion_eligible",
        "hardware_completion_eligible",
        "numerical_correctness_claim_eligible",
    }
    for section_name in ("full_scf_numerical_gate", "release_completion_gates"):
        section = payload.get(section_name, {})
        if not isinstance(section, Mapping):
            errors.append(f"{section_name}_missing_or_not_mapping")
            continue
        for field in sorted(forbidden_true_fields):
            if bool(section.get(field, False)):
                errors.append(f"{section_name}: must not set {field} true")

    gate = payload.get("full_scf_numerical_gate", {})
    if isinstance(gate, Mapping) and bool(gate.get("passed", False)):
        if gate.get("comparison_artifact_passed") is not True:
            errors.append("full_scf_numerical_gate: passed requires comparison_artifact_passed true")
        if gate.get("validation_passed") is not True:
            errors.append("full_scf_numerical_gate: passed requires validation_passed true")
        if gate.get("status_artifact_passed") is not True:
            errors.append("full_scf_numerical_gate: passed requires status_artifact_passed true")

    release_gates = payload.get("release_completion_gates", {})
    if isinstance(release_gates, Mapping):
        gate_passed = bool(gate.get("passed", False)) if isinstance(gate, Mapping) else False
        if release_gates.get("full_scf_numerical_passed") is True and not gate_passed:
            errors.append(
                "release_completion_gates: full_scf_numerical_passed requires full_scf_numerical_gate.passed true"
            )
        workplan_for_gate = payload.get("full_scf_numerical_closure_workplan", {})
        if isinstance(workplan_for_gate, Mapping):
            workplan_required = bool(workplan_for_gate.get("required", False))
            if release_gates.get("full_scf_numerical_closure_required") is False and workplan_required:
                errors.append(
                    "release_completion_gates: full_scf_numerical_closure_required false conflicts with required workplan"
                )

    workplan = payload.get("full_scf_numerical_closure_workplan", {})
    if not isinstance(workplan, Mapping):
        errors.append("full_scf_numerical_closure_workplan_missing_or_not_mapping")
        return
    workplan_forbidden = {
        "execution_allowed",
        "trusted_accelerated_numeric_source",
        "trusted_winner",
        "trusted_final_claim",
        "numerical_correctness_claim_eligible",
        "hardware_completion_eligible",
        "release_completion_eligible",
        "deliverable_complete",
    }
    for field in sorted(workplan_forbidden):
        if bool(workplan.get(field, False)):
            errors.append(f"full_scf_numerical_closure_workplan: must not set {field} true")
    for idx, item in enumerate(workplan.get("work_items", []) or []):
        if not isinstance(item, Mapping):
            errors.append(f"full_scf_numerical_closure_workplan.work_items[{idx}] is not an object")
            continue
        for field in sorted(workplan_forbidden):
            if bool(item.get(field, False)):
                errors.append(
                    f"full_scf_numerical_closure_workplan.work_items[{idx}]: must not set {field} true"
                )

    trusted_queue = payload.get("full_scf_trusted_evidence_execution_queue", {})
    if not isinstance(trusted_queue, Mapping):
        errors.append("full_scf_trusted_evidence_execution_queue_missing_or_not_mapping")
    else:
        for field in (
            "trusted_final_claim",
            "hardware_completion_eligible",
            "release_completion_eligible",
            "deliverable_complete",
        ):
            if bool(trusted_queue.get(field, False)):
                errors.append(f"full_scf_trusted_evidence_execution_queue: must not set {field} true")
        if trusted_queue.get("present") is True:
            if type(trusted_queue.get("work_item_count")) is not int:
                errors.append("full_scf_trusted_evidence_execution_queue: work_item_count must be an integer")
            deployment_counts = trusted_queue.get("deployment_work_item_counts", {})
            if not isinstance(deployment_counts, Mapping):
                errors.append("full_scf_trusted_evidence_execution_queue: deployment_work_item_counts must be a mapping")
            else:
                for deployment in _DEPLOYMENTS:
                    if type(deployment_counts.get(deployment, 0)) is not int:
                        errors.append(
                            "full_scf_trusted_evidence_execution_queue: "
                            f"{deployment} deployment count must be an integer"
                        )

    targeted_accounting = payload.get("full_scf_targeted_deployment_accounting", {})
    if not isinstance(targeted_accounting, Mapping):
        errors.append("full_scf_targeted_deployment_accounting_missing_or_not_mapping")
    else:
        for field in (
            "trusted_final_claim",
            "can_name_targeted_deployment_recommendation",
            "can_name_final_recommendation",
            "deliverable_complete",
        ):
            if bool(targeted_accounting.get(field, False)):
                errors.append(f"full_scf_targeted_deployment_accounting: must not set {field} true")
        deployments = targeted_accounting.get("deployments", {})
        if deployments and not isinstance(deployments, Mapping):
            errors.append("full_scf_targeted_deployment_accounting.deployments must be a mapping")
        elif isinstance(deployments, Mapping):
            for deployment in _DEPLOYMENTS:
                item = deployments.get(deployment, {})
                if not isinstance(item, Mapping):
                    continue
                for field in (
                    "trusted_final_claim",
                    "can_name_targeted_deployment_recommendation",
                    "can_name_final_recommendation",
                    "deliverable_complete",
                ):
                    if bool(item.get(field, False)):
                        errors.append(
                            "full_scf_targeted_deployment_accounting: "
                            f"{deployment} must not set {field} true"
                        )


def validate_dft_hardware_deployment_recommendation_readiness(
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    """Validate readiness consistency without upgrading any final claim."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("readiness_must_not_mark_deliverable_complete")
    if payload.get("trusted_final_claim") is True:
        errors.append("readiness_must_not_mark_trusted_final_claim")
    if payload.get("hardware_completion_eligible") is True:
        errors.append("readiness_must_not_mark_hardware_completion_eligible")
    if payload.get("can_name_final_recommendation") is True:
        errors.append("readiness_must_not_mark_final_recommendation_ready")
    if payload.get("can_name_targeted_deployment_recommendation") is True:
        errors.append("readiness_must_not_mark_targeted_deployment_recommendation_ready")
    if _contains_reserved_winner_key(payload):
        errors.append("readiness_must_not_name_winners")
    deployments = payload.get("deployments", {})
    if not isinstance(deployments, Mapping):
        errors.append("deployments_missing_or_not_mapping")
        deployments = {}
    top_level_final_next = payload.get("final_recommendation_required_next_evidence", {})
    if not isinstance(top_level_final_next, Mapping):
        errors.append("final_recommendation_required_next_evidence_not_mapping")
        top_level_final_next = {}
    top_level_required_next = payload.get("required_next_evidence", {})
    if not isinstance(top_level_required_next, Mapping):
        errors.append("required_next_evidence_not_mapping")
        top_level_required_next = {}
    ready_count = 0
    for deployment in _DEPLOYMENTS:
        item = deployments.get(deployment, {}) if isinstance(deployments, Mapping) else {}
        if not isinstance(item, Mapping):
            errors.append(f"{deployment}_readiness_not_mapping")
            continue
        can_name = item.get("can_name_winner") is True
        if can_name:
            ready_count += 1
            if item.get("can_name_final_recommendation") is True:
                errors.append(f"{deployment}_must_not_mark_final_recommendation_ready")
            if item.get("can_name_targeted_deployment_recommendation") is True:
                errors.append(f"{deployment}_must_not_mark_targeted_deployment_recommendation_ready")
            if item.get("resolved_by_winner_resolution") is not True:
                errors.append(f"{deployment}_can_name_without_winner_resolution")
            if item.get("hardware_winner_resolution_eligible") is not True:
                errors.append(f"{deployment}_can_name_without_hardware_winner_resolution_eligible")
            queue_counts = item.get("next_runnable_work_item_counts", {})
            if isinstance(queue_counts, Mapping) and int(queue_counts.get("tie_breaker_queue", 0) or 0):
                errors.append(f"{deployment}_can_name_with_pending_tie_breaker_queue")
        elif not item.get("required_next_evidence"):
            errors.append(f"{deployment}_blocked_without_required_next_evidence")
        final_next = item.get("final_recommendation_required_next_evidence", [])
        required_next = item.get("required_next_evidence", [])
        final_mirror_error = f"{deployment}_final_evidence_not_mirrored_in_required_next_evidence"
        if _missing_final_evidence_mirror_identities(
            final_next,
            required_next,
            deployment=deployment,
        ) and final_mirror_error not in errors:
            errors.append(final_mirror_error)
        if _missing_final_evidence_mirror_identities(
            top_level_final_next.get(deployment, []),
            top_level_required_next.get(deployment, []),
            deployment=deployment,
        ) and final_mirror_error not in errors:
            errors.append(final_mirror_error)
        target_selection = item.get("target_selection", {})
        if not isinstance(target_selection, Mapping):
            errors.append(f"{deployment}_target_selection_not_mapping")
        elif target_selection.get("ready_for_targeted_recommendation") is not True:
            if not _next_evidence_items(final_next):
                errors.append(f"{deployment}_target_selection_blocked_without_final_next_evidence")
        else:
            input_trust_gate = target_selection.get("input_trust_gate", {})
            if not isinstance(input_trust_gate, Mapping):
                errors.append(f"{deployment}_target_selection_input_trust_gate_missing_or_not_mapping")
            elif input_trust_gate.get("trusted") is not True:
                errors.append(f"{deployment}_target_selection_ready_without_trusted_input_gate")
    if payload.get("can_name_hardware_ppa_winners") is True and ready_count != len(_DEPLOYMENTS):
        errors.append("all_deployments_ready_flag_without_all_deployments_ready")
    trust_gates = payload.get("deployment_target_selection_trust_gates", {})
    if not isinstance(trust_gates, Mapping):
        errors.append("deployment_target_selection_trust_gates_missing_or_not_mapping")
    elif payload.get("deployment_target_selection_ready") is True and trust_gates.get("all_trusted") is not True:
        errors.append("target_selection_ready_without_all_target_input_trust_gates")
    if payload.get("deployment_target_selection_ready") is True:
        for deployment in _DEPLOYMENTS:
            item = deployments.get(deployment, {}) if isinstance(deployments, Mapping) else {}
            target_selection = item.get("target_selection", {}) if isinstance(item, Mapping) else {}
            if not isinstance(target_selection, Mapping) or target_selection.get("ready_for_targeted_recommendation") is not True:
                errors.append("target_selection_ready_without_all_deployments_ready")
                break
    _validate_full_scf_readiness_sections(payload, errors)
    return {
        "schema_version": DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_deployment_recommendation_readiness(
    run_dir: Path,
    *,
    hardware_completion_workplan_path: Path | None = None,
    tie_breaker_execution_queue_path: Path | None = None,
    freshness_queue_path: Path | None = None,
    architecture_winner_resolution_path: Path | None = None,
    ic_eda_tool_availability_path: Path | None = None,
    deployment_target_selection_path: Path | None = None,
) -> Dict[str, Any]:
    """Write readiness, validation, and status artifacts into ``run_dir``."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_deployment_recommendation_readiness(
        run_dir,
        hardware_completion_workplan_path=hardware_completion_workplan_path,
        tie_breaker_execution_queue_path=tie_breaker_execution_queue_path,
        freshness_queue_path=freshness_queue_path,
        architecture_winner_resolution_path=architecture_winner_resolution_path,
        ic_eda_tool_availability_path=ic_eda_tool_availability_path,
        deployment_target_selection_path=deployment_target_selection_path,
    )
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)
    write_json(run_dir / "dft_hardware_deployment_recommendation_readiness.json", payload)
    write_json(run_dir / "dft_hardware_deployment_recommendation_readiness_validation.json", validation)
    status = {
        "schema_version": DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "readiness_status": payload.get("status"),
        "fpga_status": payload.get("deployments", {}).get("fpga", {}).get("status"),
        "asic_status": payload.get("deployments", {}).get("asic", {}).get("status"),
        "fpga_can_name_winner": payload.get("fpga_can_name_winner"),
        "asic_can_name_winner": payload.get("asic_can_name_winner"),
        "can_name_hardware_ppa_winners": payload.get("can_name_hardware_ppa_winners"),
        "deployment_target_selection_ready": payload.get("deployment_target_selection_ready"),
        "full_scf_trusted_evidence_execution_queue": payload.get(
            "full_scf_trusted_evidence_execution_queue",
            {},
        ),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_hardware_deployment_recommendation_readiness_status.json", status)
    return {
        "schema_version": "dse.dft.hardware_deployment_recommendation_readiness_artifact_status.v1",
        "status": status["status"],
        "readiness": str(run_dir / "dft_hardware_deployment_recommendation_readiness.json"),
        "readiness_validation": str(run_dir / "dft_hardware_deployment_recommendation_readiness_validation.json"),
        "readiness_status": str(run_dir / "dft_hardware_deployment_recommendation_readiness_status.json"),
        "can_name_hardware_ppa_winners": payload.get("can_name_hardware_ppa_winners"),
        "deployment_target_selection_ready": payload.get("deployment_target_selection_ready"),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_SCHEMA",
    "DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_STATUS_SCHEMA",
    "DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_VALIDATION_SCHEMA",
    "build_dft_hardware_deployment_recommendation_readiness",
    "validate_dft_hardware_deployment_recommendation_readiness",
    "write_dft_hardware_deployment_recommendation_readiness",
]
