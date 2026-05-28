#!/usr/bin/env python3
"""Fail-closed FPGA/ASIC deployment-summary artifact for DFT hardware winners.

This module is a thin export shell over the existing architecture winner
resolution artifacts.  It does not invent a new winner, relax a gate, or force a
device choice when the source evidence does not already bind one.  Its job is to
package the current best FPGA and ASIC deployment candidates into a single
reporting artifact that downstream Step5/summary code can consume.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json


DFT_FPGA_ASIC_DEPLOYMENT_SUMMARY_SCHEMA = "dse.dft.fpga_asic_deployment_summary.v1"
DFT_FPGA_ASIC_DEPLOYMENT_SUMMARY_VALIDATION_SCHEMA = (
    "dse.dft.fpga_asic_deployment_summary_validation.v1"
)
DFT_FPGA_ASIC_DEPLOYMENT_SUMMARY_STATUS_SCHEMA = (
    "dse.dft.fpga_asic_deployment_summary_status.v1"
)

_CLAIM_BOUNDARY = (
    "This summary only packages the already-derived FPGA/ASIC deployment winners "
    "from architecture winner resolution.  It cannot invent device selection, "
    "relax hard gates, or mark deliverable completion."
)

_DEPLOYMENTS = ("fpga", "asic")
_FPGA_DEVICE_HINT_KEYS = (
    "fpga_device",
    "fpga_part",
    "vivado_part",
    "target_part",
    "xilinx_part",
    "board",
    "device",
    "platform",
    "target_device",
    "fpga_model",
)
_ASIC_TARGET_HINT_KEYS = (
    "asic_target_library",
    "target_library",
    "dc_target_library",
    "technology_node",
    "process_node",
    "cell_library",
    "library",
)
_KERNEL_ROW_DEVICE_SELECTION_STATUSES = {
    "blocked_conflicting_kernel_row_target_evidence",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
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


def _source_freshness_errors(
    source_artifacts: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
) -> list[str]:
    """Return validation errors when recorded upstream hashes are stale."""

    errors: list[str] = []
    for key in keys:
        ref = source_artifacts.get(key)
        if not isinstance(ref, Mapping):
            errors.append(f"missing_required_source_artifact:{key}")
            continue
        path_text = str(ref.get("path") or "")
        if ref.get("exists") is not True or not path_text:
            errors.append(f"missing_required_source_artifact:{key}")
            continue
        path = Path(path_text)
        if not path.exists() or not path.is_file():
            errors.append(f"source_artifact_current_path_missing:{key}")
            continue
        expected_sha = str(ref.get("sha256") or "")
        actual_sha = sha256_file(path)
        if not expected_sha:
            errors.append(f"source_artifact_missing_recorded_sha256:{key}")
        elif actual_sha != expected_sha:
            errors.append(f"stale_source_artifact:{key}")
    return errors


def _first_non_empty(payload: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(payload.get(key) or "")
        if value:
            return value
    return ""


def _kernel_row_target_summary(
    deployment: str,
    winner: Mapping[str, Any],
) -> Dict[str, Any]:
    evidence = winner.get("deployment_target_evidence", {})
    evidence = evidence if isinstance(evidence, Mapping) else {}
    if evidence.get("deployment") != deployment:
        return {}
    return dict(evidence)


def _device_summary(deployment: str, winner: Mapping[str, Any] | None) -> Dict[str, Any]:
    winner = winner if isinstance(winner, Mapping) else {}
    identity = winner.get("identity_assignments", {})
    identity = identity if isinstance(identity, Mapping) else {}
    non_identity = winner.get("non_identity_assignments", {})
    non_identity = non_identity if isinstance(non_identity, Mapping) else {}
    combined = {**non_identity, **identity, **winner}
    kernel_row_target = _kernel_row_target_summary(deployment, winner)
    kernel_row_target_present = bool(kernel_row_target)
    kernel_row_status = str(kernel_row_target.get("status") or "")
    kernel_row_selected_target = str(kernel_row_target.get("selected_target") or "")
    if deployment == "fpga":
        selected_device = _first_non_empty(combined, _FPGA_DEVICE_HINT_KEYS)
        device_kind = "fpga"
        vendor_policy = "AMD/Xilinx preferred when evidence-backed; no new device claim without source hints"
        if kernel_row_status == "resolved_from_kernel_row_evidence" and kernel_row_selected_target:
            selected_device = kernel_row_selected_target
            device_selection_status = kernel_row_status
        elif kernel_row_status in _KERNEL_ROW_DEVICE_SELECTION_STATUSES:
            selected_device = ""
            device_selection_status = kernel_row_status
        elif kernel_row_target_present:
            selected_device = ""
            device_selection_status = "not_explicitly_proven"
        else:
            device_selection_status = "resolved_from_source_hints" if selected_device else "not_explicitly_proven"
        device_key = "selected_fpga_device"
        hint_keys = list(_FPGA_DEVICE_HINT_KEYS)
    else:
        selected_device = _first_non_empty(combined, _ASIC_TARGET_HINT_KEYS)
        device_kind = "asic"
        vendor_policy = "real_target_library_required"
        if kernel_row_status == "resolved_from_kernel_row_evidence" and kernel_row_selected_target:
            selected_device = kernel_row_selected_target
            device_selection_status = kernel_row_status
        elif kernel_row_status in _KERNEL_ROW_DEVICE_SELECTION_STATUSES:
            selected_device = ""
            device_selection_status = kernel_row_status
        elif kernel_row_target_present:
            selected_device = ""
            device_selection_status = "not_explicitly_proven"
        else:
            device_selection_status = "resolved_from_source_hints" if selected_device else "not_explicitly_proven"
        device_key = "selected_asic_target"
        hint_keys = list(_ASIC_TARGET_HINT_KEYS)
    return {
        "device_kind": device_kind,
        "selected_device": selected_device or None,
        device_key: selected_device or None,
        "device_selection_status": device_selection_status,
        "device_hint_keys": hint_keys,
        "vendor_policy": vendor_policy,
        "kernel_row_target_evidence": kernel_row_target,
        "device_selection_claim_boundary": (
            "Device/part selection is evidence-backed only when all major-kernel "
            "winner rows agree on the same physical-tool target evidence.  Legacy "
            "winner records without kernel-row target summaries may still expose "
            "explicit source hints, but assignment-level hints cannot override "
            "present kernel-row target blockers or conflicts.  Absent evidence "
            "consensus, the summary stays conservative and does not invent a "
            "deployment target."
        ),
    }


def _deployment_summary(
    deployment: str,
    *,
    resolution: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> Dict[str, Any]:
    winner = resolution.get("winner")
    winner = winner if isinstance(winner, Mapping) else {}
    source_artifacts = {
        "winner_resolution": _source_ref(Path(resolution.get("_source_resolution_path", ""))) if resolution.get("_source_resolution_path") else None,
        "winner_resolution_validation": _source_ref(Path(resolution.get("_source_validation_path", ""))) if resolution.get("_source_validation_path") else None,
        "winner_resolution_status": _source_ref(Path(resolution.get("_source_status_path", "")), required=False) if resolution.get("_source_status_path") else None,
    }
    source_artifacts = {key: value for key, value in source_artifacts.items() if value is not None}
    device_summary = _device_summary(deployment, winner)
    resolved = resolution.get("resolved") is True
    best_architecture = winner if resolved else None
    evidence_ids = [
        rel
        for rel in [
            "dft_architecture_winner_resolution.json",
            "dft_architecture_winner_resolution_validation.json",
            "dft_architecture_winner_resolution_status.json",
        ]
        if rel
    ]
    if resolved and isinstance(winner.get("evidence_ids"), list):
        evidence_ids = list(dict.fromkeys(evidence_ids + [str(item) for item in winner.get("evidence_ids", []) if item]))
    return {
        "deployment": deployment,
        "status": (
            "resolved_best_deployment"
            if resolved and validation.get("valid") is True
            else "blocked_no_best_deployment"
        ),
        "resolved": resolved and validation.get("valid") is True,
        "winner_resolution_status": resolution.get("status"),
        "winner_resolution_eligible": resolution.get("resolved") is True,
        "best_architecture": best_architecture,
        "best_candidate_id": winner.get("candidate_id") if resolved else None,
        "best_design_candidate_id": winner.get("design_candidate_id") if resolved else None,
        "equivalent_top_candidate_ids": list(winner.get("equivalent_top_candidate_ids", []) or []) if resolved else [],
        "metrics": dict(winner.get("metrics", {}) if isinstance(winner.get("metrics", {}), Mapping) else {}),
        "source_artifacts": source_artifacts,
        "evidence_ids": evidence_ids,
        "device_summary": device_summary,
        "device_selection_status": device_summary.get("device_selection_status"),
        "device_selection_claim_boundary": device_summary.get("device_selection_claim_boundary"),
        "required_next_evidence": resolution.get("required_next_evidence", []),
        "claim_boundary": (
            "Deployment summary packages the current best FPGA/ASIC architecture winners and "
            "their evidence-backed device hints only.  It remains scoped hardware-PPA "
            "evidence, not a full-SCF deliverable-complete claim."
        ),
    }


def build_dft_fpga_asic_deployment_summary(run_dir: Path) -> Dict[str, Any]:
    """Build the combined FPGA/ASIC deployment summary from winner-resolution artifacts."""

    run_dir = Path(run_dir)
    resolution_path = run_dir / "dft_architecture_winner_resolution.json"
    validation_path = run_dir / "dft_architecture_winner_resolution_validation.json"
    status_path = run_dir / "dft_architecture_winner_resolution_status.json"
    resolution = _load_json(resolution_path)
    validation = _load_json(validation_path)
    status_artifact = _load_json(status_path)
    deployments = resolution.get("deployments", {})
    deployments = deployments if isinstance(deployments, Mapping) else {}
    fpga_resolution = dict(deployments.get("fpga", {}) if isinstance(deployments.get("fpga", {}), Mapping) else {})
    asic_resolution = dict(deployments.get("asic", {}) if isinstance(deployments.get("asic", {}), Mapping) else {})
    for item in (fpga_resolution, asic_resolution):
        item["_source_resolution_path"] = str(resolution_path)
        item["_source_validation_path"] = str(validation_path)
        item["_source_status_path"] = str(status_path)
    summary_eligible = bool(
        resolution.get("hardware_winner_resolution_eligible") is True
        and resolution.get("trusted_best_architecture_claim_eligible") is True
        and validation.get("valid") is True
    )
    source_artifacts = {
        "dft_architecture_winner_resolution": _source_ref(resolution_path),
        "dft_architecture_winner_resolution_validation": _source_ref(validation_path),
        "dft_architecture_winner_resolution_status": _source_ref(status_path, required=False),
    }
    summary = {
        "schema_version": DFT_FPGA_ASIC_DEPLOYMENT_SUMMARY_SCHEMA,
        "generated_at": _now_iso(),
        "status": "resolved_best_deployment" if summary_eligible else "blocked_no_best_deployment",
        "source_artifacts": source_artifacts,
        "hardware_winner_resolution_eligible": bool(resolution.get("hardware_winner_resolution_eligible", False)),
        "trusted_best_architecture_claim_eligible": bool(
            resolution.get("trusted_best_architecture_claim_eligible", False)
            and validation.get("valid") is True
        ),
        "deliverable_complete": False,
        "fpga": _deployment_summary(
            "fpga",
            resolution=fpga_resolution,
            validation=validation,
        ),
        "asic": _deployment_summary(
            "asic",
            resolution=asic_resolution,
            validation=validation,
        ),
        "winner_resolution_status": resolution.get("status"),
        "winner_resolution_validation": {
            "present": bool(validation),
            "valid": validation.get("valid"),
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "status_artifact": status_artifact,
        "blocker_count": 0 if summary_eligible else 1,
        "blockers": []
        if summary_eligible
        else [
            {
                "blocker_id": "winner_resolution_or_validation_not_closed",
                "winner_resolution_status": resolution.get("status"),
                "validation_valid": validation.get("valid"),
            }
        ],
        "best_deployment_claim_eligible": summary_eligible,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    return summary


def validate_dft_fpga_asic_deployment_summary(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the combined deployment summary without upgrading claims."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_FPGA_ASIC_DEPLOYMENT_SUMMARY_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("deployment_summary_must_not_mark_deliverable_complete")
    errors.extend(
        _source_freshness_errors(
            payload.get("source_artifacts", {})
            if isinstance(payload.get("source_artifacts", {}), Mapping)
            else {},
            keys=(
                "dft_architecture_winner_resolution",
                "dft_architecture_winner_resolution_validation",
            ),
        )
    )
    if payload.get("best_deployment_claim_eligible") is True:
        if payload.get("hardware_winner_resolution_eligible") is not True:
            errors.append("best_deployment_claim_without_winner_resolution")
        if payload.get("trusted_best_architecture_claim_eligible") is not True:
            errors.append("best_deployment_claim_without_trusted_best_architecture_claim")
        if payload.get("blocker_count") not in (0, None):
            errors.append("best_deployment_claim_with_blockers")
        for deployment in _DEPLOYMENTS:
            item = payload.get(deployment, {})
            if not isinstance(item, Mapping):
                errors.append(f"{deployment}_summary_not_mapping")
                continue
            if item.get("resolved") is not True:
                errors.append(f"{deployment}_summary_unresolved")
            if not isinstance(item.get("best_architecture"), Mapping):
                errors.append(f"{deployment}_summary_missing_best_architecture")
            if item.get("device_selection_status") not in {
                "resolved_from_source_hints",
                "resolved_from_kernel_row_evidence",
                "blocked_conflicting_kernel_row_target_evidence",
                "not_explicitly_proven",
            }:
                errors.append(f"{deployment}_summary_invalid_device_selection_status")
    return {
        "schema_version": DFT_FPGA_ASIC_DEPLOYMENT_SUMMARY_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_fpga_asic_deployment_summary(run_dir: Path) -> Dict[str, Any]:
    """Write deployment-summary, validation, and status artifacts."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = build_dft_fpga_asic_deployment_summary(run_dir)
    validation = validate_dft_fpga_asic_deployment_summary(summary)
    write_json(run_dir / "dft_fpga_asic_deployment_summary.json", summary)
    write_json(run_dir / "dft_fpga_asic_deployment_summary_validation.json", validation)
    status = {
        "schema_version": DFT_FPGA_ASIC_DEPLOYMENT_SUMMARY_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "best_deployment_claim_eligible": summary.get("best_deployment_claim_eligible"),
        "blocker_count": summary.get("blocker_count"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_fpga_asic_deployment_summary_status.json", status)
    return {
        "schema_version": "dse.dft.fpga_asic_deployment_summary_artifact_status.v1",
        "status": status["status"],
        "deployment_summary": str(run_dir / "dft_fpga_asic_deployment_summary.json"),
        "deployment_summary_validation": str(run_dir / "dft_fpga_asic_deployment_summary_validation.json"),
        "deployment_summary_status": str(run_dir / "dft_fpga_asic_deployment_summary_status.json"),
        "best_deployment_claim_eligible": summary.get("best_deployment_claim_eligible"),
        "blocker_count": summary.get("blocker_count"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_FPGA_ASIC_DEPLOYMENT_SUMMARY_SCHEMA",
    "DFT_FPGA_ASIC_DEPLOYMENT_SUMMARY_STATUS_SCHEMA",
    "DFT_FPGA_ASIC_DEPLOYMENT_SUMMARY_VALIDATION_SCHEMA",
    "build_dft_fpga_asic_deployment_summary",
    "validate_dft_fpga_asic_deployment_summary",
    "write_dft_fpga_asic_deployment_summary",
]
