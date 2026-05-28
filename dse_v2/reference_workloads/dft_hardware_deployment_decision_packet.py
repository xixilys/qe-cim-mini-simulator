#!/usr/bin/env python3
"""Fail-closed DFT FPGA/ASIC deployment decision packet.

The deployment readiness artifact deliberately avoids naming winners.  This
packet is the complementary Step5 planning record: it may name the scoped
hardware-PPA FPGA/ASIC winners and selected deployment targets in one place, but
it remains fail-closed for targeted/final deployment recommendation claims until
trusted full-SCF host+accelerator numerical/runtime evidence closes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.reference_workloads.dft_full_scf_targeted_accounting import (
    TARGETED_ACCOUNTING_ARTIFACT_NAME,
    TARGETED_ACCOUNTING_VALIDATION_NAME,
    summarize_full_scf_targeted_deployment_accounting,
)


DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_SCHEMA = (
    "dse.dft.hardware_deployment_decision_packet.v1"
)
DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_VALIDATION_SCHEMA = (
    "dse.dft.hardware_deployment_decision_packet_validation.v1"
)
DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_STATUS_SCHEMA = (
    "dse.dft.hardware_deployment_decision_packet_status.v1"
)

_DEPLOYMENTS = ("fpga", "asic")
_FORBIDDEN_FINAL_TRUE_FIELDS = (
    "can_name_targeted_deployment_recommendation",
    "can_name_final_recommendation",
    "trusted_final_claim",
    "deliverable_complete",
)
_CLAIM_BOUNDARY = (
    "DFT hardware deployment decision packet may name scoped FPGA/ASIC "
    "hardware-PPA planning winners together with selected target context. It "
    "does not replace full-SCF host+accelerator numerical/runtime evidence, "
    "does not turn target selection into PPA evidence, and cannot mark a "
    "targeted or final FPGA/ASIC deployment recommendation complete."
)


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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _winner_from_resolution(
    winner_resolution: Mapping[str, Any],
    deployment: str,
) -> Dict[str, Any]:
    deployments = _mapping(winner_resolution.get("deployments"))
    deployment_resolution = _mapping(deployments.get(deployment))
    winner = _mapping(
        deployment_resolution.get("winner")
        or winner_resolution.get(f"{deployment}_best_architecture")
    )
    if not winner:
        return {}
    return dict(winner)


def _target_from_readiness(
    readiness: Mapping[str, Any],
    deployment: str,
) -> Dict[str, Any]:
    deployments = _mapping(readiness.get("deployments"))
    deployment_readiness = _mapping(deployments.get(deployment))
    target_selection = _mapping(deployment_readiness.get("target_selection"))
    return dict(target_selection)


def _target_selection_trust_gate_from_readiness(
    readiness: Mapping[str, Any],
    deployment: str,
) -> Dict[str, Any]:
    trust_gates = _mapping(readiness.get("deployment_target_selection_trust_gates"))
    gates = _mapping(trust_gates.get("gates"))
    gate_key = "fpga_target_catalog" if deployment == "fpga" else "asic_target_library_probe"
    gate = _mapping(gates.get(gate_key))
    blockers = _list(gate.get("blockers", []))
    return {
        "gate_key": gate_key,
        "trust_class": gate.get("trust_class") or gate_key,
        "present": gate.get("present") is True or bool(gate),
        "trusted": gate.get("trusted") is True,
        "source_ref_count": gate.get("source_ref_count", 0),
        "source_refs": _list(gate.get("source_refs", [])),
        "blocker_count": gate.get("blocker_count", len(blockers)),
        "blockers": blockers,
        "claim_boundary": gate.get("claim_boundary"),
    }


def _final_gate_passed(readiness: Mapping[str, Any]) -> bool:
    gate = _mapping(readiness.get("full_scf_numerical_gate"))
    release_gates = _mapping(readiness.get("release_completion_gates"))
    return bool(
        gate.get("passed") is True
        and release_gates.get("full_scf_numerical_passed") is True
    )


def _full_scf_blocker_summary(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    gate = _mapping(readiness.get("full_scf_numerical_gate"))
    workplan = _mapping(readiness.get("full_scf_numerical_closure_workplan"))
    return {
        "blocker_id": "full_scf_numerical_gate_not_passed",
        "status": gate.get("status"),
        "passed": bool(gate.get("passed", False)),
        "candidate_count": gate.get("candidate_count"),
        "blocked_candidate_count": gate.get("blocked_candidate_count"),
        "row_record_count": gate.get("row_record_count"),
        "blocked_row_record_count": gate.get("blocked_row_record_count"),
        "trusted_accelerated_numeric_source": bool(
            gate.get("trusted_accelerated_numeric_source", False)
        ),
        "work_item_count": workplan.get("work_item_count"),
        "class_row_work_item_count": workplan.get("class_row_work_item_count"),
        "required": bool(workplan.get("required", True)),
        "required_next_evidence": workplan.get("required_next_evidence", []),
    }


def _deployment_packet(
    *,
    deployment: str,
    winner_resolution: Mapping[str, Any],
    readiness: Mapping[str, Any],
    hardware_winners_ready: bool,
    full_scf_passed: bool,
) -> Dict[str, Any]:
    deployments = _mapping(winner_resolution.get("deployments"))
    deployment_resolution = _mapping(deployments.get(deployment))
    readiness_deployments = _mapping(readiness.get("deployments"))
    deployment_readiness = _mapping(readiness_deployments.get(deployment))
    winner = _winner_from_resolution(winner_resolution, deployment)
    target = _target_from_readiness(readiness, deployment)
    target_selection_trust_gate = _target_selection_trust_gate_from_readiness(readiness, deployment)
    target_ready = target.get("ready_for_targeted_recommendation") is True
    can_name_winner = bool(
        hardware_winners_ready
        and deployment_resolution.get("resolved") is True
        and deployment_readiness.get("can_name_hardware_ppa_winner") is True
        and winner
    )
    final_next = _list(deployment_readiness.get("final_recommendation_required_next_evidence"))
    hardware_next = _list(deployment_readiness.get("required_next_evidence"))
    planning_ready = bool(
        can_name_winner
        and target_ready
        and target_selection_trust_gate.get("trusted") is True
    )
    return {
        "schema_version": "dse.dft.hardware_deployment_decision_packet.deployment.v1",
        "deployment": deployment,
        "status": (
            "scoped_hardware_ppa_winner_and_target_ready_final_recommendation_blocked"
            if planning_ready and not full_scf_passed
            else "scoped_hardware_ppa_winner_and_target_ready_full_scf_gate_passed_final_review_required"
            if planning_ready and full_scf_passed
            else "blocked_scoped_hardware_ppa_winner_or_target_not_ready"
        ),
        "scoped_hardware_ppa_winner_named": can_name_winner,
        "can_name_hardware_ppa_winner": can_name_winner,
        "target_selection_ready": bool(target_ready),
        "planning_ready": planning_ready,
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "winner_resolution_status": deployment_resolution.get("status"),
        "winner_resolution_basis": deployment_resolution.get("winner_resolution_basis"),
        "top_rank_candidate_count": deployment_resolution.get("top_rank_candidate_count"),
        "top_rank_design_count": deployment_resolution.get("top_rank_design_count"),
        "top_rank_candidate_ids": deployment_resolution.get("top_rank_candidate_ids", []),
        "top_rank_design_ids": deployment_resolution.get("top_rank_design_ids", []),
        "duplicate_top_rank_evaluation_rows_collapsed": deployment_resolution.get(
            "duplicate_top_rank_evaluation_rows_collapsed"
        ),
        "scoped_hardware_ppa_winner": winner if can_name_winner else None,
        "representative_candidate_id": winner.get("representative_candidate_id") or winner.get("candidate_id"),
        "design_candidate_id": winner.get("design_candidate_id") or winner.get("design_identity"),
        "hardware_ppa_metrics": winner.get("metrics", {}) if can_name_winner else {},
        "target_selection": target,
        "target_selection_trust_gate": target_selection_trust_gate,
        "selected_target": target.get("selected_target", {}) if target_ready else {},
        "targeted_deployment_accounting": _mapping(
            deployment_readiness.get("targeted_deployment_accounting")
        ),
        "required_next_evidence": hardware_next,
        "final_recommendation_required_next_evidence": final_next,
        "final_claim_blockers": (
            [_full_scf_blocker_summary(readiness)] if not full_scf_passed else []
        )
        + final_next,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_hardware_deployment_decision_packet(
    run_dir: Path,
    *,
    architecture_winner_resolution_path: Path | None = None,
    deployment_recommendation_readiness_path: Path | None = None,
    deployment_target_selection_path: Path | None = None,
    targeted_deployment_accounting_path: Path | None = None,
) -> Dict[str, Any]:
    """Build a fail-closed packet tying scoped winners to selected targets."""

    run_dir = Path(run_dir)
    winner_path = (
        Path(architecture_winner_resolution_path)
        if architecture_winner_resolution_path
        else run_dir / "dft_architecture_winner_resolution.json"
    )
    readiness_path = (
        Path(deployment_recommendation_readiness_path)
        if deployment_recommendation_readiness_path
        else run_dir / "dft_hardware_deployment_recommendation_readiness.json"
    )
    target_path = (
        Path(deployment_target_selection_path)
        if deployment_target_selection_path
        else run_dir / "dft_hardware_deployment_target_selection.json"
    )
    accounting_path = (
        Path(targeted_deployment_accounting_path)
        if targeted_deployment_accounting_path
        else run_dir / TARGETED_ACCOUNTING_ARTIFACT_NAME
    )
    winner_validation_path = _companion(winner_path, "dft_architecture_winner_resolution_validation.json")
    readiness_validation_path = _companion(
        readiness_path,
        "dft_hardware_deployment_recommendation_readiness_validation.json",
    )
    target_validation_path = _companion(
        target_path,
        "dft_hardware_deployment_target_selection_validation.json",
    )
    accounting_validation_path = _companion(accounting_path, TARGETED_ACCOUNTING_VALIDATION_NAME)

    winner_resolution = _load_json(winner_path)
    readiness = _load_json(readiness_path)
    target_selection = _load_json(target_path)
    targeted_accounting = _load_json(accounting_path)
    winner_validation = _load_json(winner_validation_path)
    readiness_validation = _load_json(readiness_validation_path)
    target_validation = _load_json(target_validation_path)
    targeted_accounting_validation = _load_json(accounting_validation_path)

    winner_valid = winner_validation.get("valid") is True
    readiness_valid = readiness_validation.get("valid") is True
    target_valid = target_validation.get("valid") is True if target_validation else bool(target_selection)
    hardware_winners_ready = bool(
        winner_valid
        and readiness_valid
        and winner_resolution.get("hardware_winner_resolution_eligible") is True
        and readiness.get("can_name_hardware_ppa_winners") is True
    )
    target_payload_ready = bool(
        target_selection.get("deployment_target_selection_ready") is True
        or target_selection.get("status") == "target_selection_ready"
    )
    target_ready = bool(
        target_valid
        and readiness.get("deployment_target_selection_ready") is True
        and target_payload_ready
    )
    readiness_trust_gates = _mapping(readiness.get("deployment_target_selection_trust_gates"))
    readiness_trust_gate_rows = _mapping(readiness_trust_gates.get("gates"))
    target_input_gate_ready = bool(
        readiness_trust_gates.get("all_trusted") is True
        and all(
            _mapping(
                readiness_trust_gate_rows.get(
                    "fpga_target_catalog" if deployment == "fpga" else "asic_target_library_probe"
                )
            ).get("trusted") is True
            for deployment in _DEPLOYMENTS
        )
    )
    full_scf_passed = _final_gate_passed(readiness)
    planning_packet_ready = bool(hardware_winners_ready and target_ready and target_input_gate_ready)
    final_blockers: list[Dict[str, Any]] = []
    if not hardware_winners_ready:
        final_blockers.append(
            {
                "blocker_id": "scoped_hardware_ppa_winners_not_ready",
                "winner_validation_valid": winner_validation.get("valid"),
                "readiness_validation_valid": readiness_validation.get("valid"),
                "hardware_winner_resolution_eligible": winner_resolution.get(
                    "hardware_winner_resolution_eligible"
                ),
                "can_name_hardware_ppa_winners": readiness.get("can_name_hardware_ppa_winners"),
            }
        )
    if not target_ready:
        final_blockers.append(
            {
                "blocker_id": "deployment_target_selection_not_ready",
                "target_validation_valid": target_validation.get("valid"),
                "readiness_deployment_target_selection_ready": readiness.get(
                    "deployment_target_selection_ready"
                ),
                "target_selection_ready": target_selection.get("deployment_target_selection_ready"),
                "target_selection_status": target_selection.get("status"),
            }
        )
    if not target_input_gate_ready:
        final_blockers.append(
            {
                "blocker_id": "deployment_target_selection_trust_gates_not_ready",
                "deployment_target_selection_trust_gates": readiness.get(
                    "deployment_target_selection_trust_gates"
                ),
            }
        )
    if not full_scf_passed:
        final_blockers.append(_full_scf_blocker_summary(readiness))

    deployments = {
        deployment: _deployment_packet(
            deployment=deployment,
            winner_resolution=winner_resolution,
            readiness=readiness,
            hardware_winners_ready=hardware_winners_ready,
            full_scf_passed=full_scf_passed,
        )
        for deployment in _DEPLOYMENTS
    }
    return {
        "schema_version": DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_SCHEMA,
        "generated_at": _now_iso(),
        "status": (
            "scoped_hardware_ppa_planning_ready_final_recommendation_blocked"
            if planning_packet_ready and not full_scf_passed
            else "scoped_hardware_ppa_planning_ready_full_scf_gate_passed_final_review_required"
            if planning_packet_ready and full_scf_passed
            else "blocked_scoped_hardware_ppa_planning_packet"
        ),
        "source_artifacts": {
            "architecture_winner_resolution": _source_ref(winner_path, required=True),
            "architecture_winner_resolution_validation": _source_ref(
                winner_validation_path,
                required=True,
            ),
            "deployment_recommendation_readiness": _source_ref(readiness_path, required=True),
            "deployment_recommendation_readiness_validation": _source_ref(
                readiness_validation_path,
                required=True,
            ),
            "deployment_target_selection": _source_ref(target_path, required=False),
            "deployment_target_selection_validation": _source_ref(
                target_validation_path,
                required=False,
            ),
            "full_scf_targeted_deployment_accounting": _source_ref(
                accounting_path,
                required=False,
            ),
            "full_scf_targeted_deployment_accounting_validation": _source_ref(
                accounting_validation_path,
                required=False,
            ),
        },
        "release_id": readiness.get("release_id") or winner_resolution.get("release_id"),
        "candidate_count": readiness.get("candidate_count") or winner_resolution.get("candidate_count"),
        "ranking_eligible_candidate_count": readiness.get("ranking_eligible_candidate_count"),
        "planning_packet_ready": planning_packet_ready,
        "can_name_scoped_hardware_ppa_winners": hardware_winners_ready,
        "can_name_hardware_ppa_winners": hardware_winners_ready,
        "deployment_target_selection_ready": target_ready,
        "deployment_target_selection_trust_gates": readiness.get(
            "deployment_target_selection_trust_gates",
            {},
        ),
        "full_scf_numerical_gate_passed": full_scf_passed,
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "deployments": deployments,
        "full_scf_numerical_gate": readiness.get("full_scf_numerical_gate", {}),
        "full_scf_numerical_closure_workplan": readiness.get(
            "full_scf_numerical_closure_workplan",
            {},
        ),
        "full_scf_targeted_deployment_accounting": summarize_full_scf_targeted_deployment_accounting(
            targeted_accounting,
            validation=targeted_accounting_validation,
        ),
        "release_completion_gates": readiness.get("release_completion_gates", {}),
        "final_claim_blockers": final_blockers,
        "required_next_evidence": readiness.get("required_next_evidence", {}),
        "final_recommendation_required_next_evidence": readiness.get(
            "final_recommendation_required_next_evidence",
            {},
        ),
        "forbidden_shortcuts": readiness.get("forbidden_shortcuts", []),
        "completion_claim": (
            "scoped_hardware_ppa_winners_and_target_context_ready_not_final_recommendation"
            if planning_packet_ready
            else "blocked"
        ),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_deployment_decision_packet(
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    """Validate fail-closed decision packet semantics."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_SCHEMA:
        errors.append("schema_version_mismatch")
    for field in _FORBIDDEN_FINAL_TRUE_FIELDS:
        if payload.get(field) is True:
            errors.append(f"{field}_must_remain_false")
    if not payload.get("claim_boundary"):
        errors.append("claim_boundary_missing")
    deployments = _mapping(payload.get("deployments"))
    if set(deployments.keys()) != set(_DEPLOYMENTS):
        errors.append("deployments_must_include_fpga_and_asic")
    gate = _mapping(payload.get("full_scf_numerical_gate"))
    gates = _mapping(payload.get("release_completion_gates"))
    full_scf_passed = bool(
        gate.get("passed") is True
        and gates.get("full_scf_numerical_passed") is True
    )
    if payload.get("full_scf_numerical_gate_passed") is not full_scf_passed:
        errors.append("full_scf_gate_passed_flag_mismatch")
    if payload.get("planning_packet_ready") is True:
        if payload.get("can_name_scoped_hardware_ppa_winners") is not True:
            errors.append("planning_ready_without_scoped_winners")
        if payload.get("deployment_target_selection_ready") is not True:
            errors.append("planning_ready_without_target_selection")
        trust_gates = _mapping(payload.get("deployment_target_selection_trust_gates"))
        if trust_gates.get("all_trusted") is not True:
            errors.append("planning_ready_without_trusted_target_selection_gates")
    if payload.get("can_name_scoped_hardware_ppa_winners") is True:
        for deployment in _DEPLOYMENTS:
            item = _mapping(deployments.get(deployment))
            if item.get("scoped_hardware_ppa_winner_named") is not True:
                errors.append(f"{deployment}_winner_not_named_despite_top_level_ready")
            if not _mapping(item.get("scoped_hardware_ppa_winner")):
                errors.append(f"{deployment}_winner_payload_missing")
    for deployment in _DEPLOYMENTS:
        item = _mapping(deployments.get(deployment))
        for field in _FORBIDDEN_FINAL_TRUE_FIELDS:
            if item.get(field) is True:
                errors.append(f"{deployment}_{field}_must_remain_false")
        if item.get("planning_ready") is True:
            if item.get("scoped_hardware_ppa_winner_named") is not True:
                errors.append(f"{deployment}_planning_ready_without_winner")
            if item.get("target_selection_ready") is not True:
                errors.append(f"{deployment}_planning_ready_without_target")
            if not _mapping(item.get("selected_target")):
                errors.append(f"{deployment}_planning_ready_without_selected_target")
            target_selection_trust_gate = _mapping(item.get("target_selection_trust_gate"))
            if target_selection_trust_gate.get("trusted") is not True:
                errors.append(f"{deployment}_planning_ready_without_trusted_target_selection_gate")
        if item.get("scoped_hardware_ppa_winner_named") is True:
            winner = _mapping(item.get("scoped_hardware_ppa_winner"))
            if not winner.get("candidate_id"):
                errors.append(f"{deployment}_winner_missing_candidate_id")
            if not (winner.get("design_candidate_id") or winner.get("design_identity")):
                errors.append(f"{deployment}_winner_missing_design_identity")
            target_selection_trust_gate = _mapping(item.get("target_selection_trust_gate"))
            if target_selection_trust_gate.get("trusted") is not True:
                errors.append(f"{deployment}_winner_named_without_trusted_target_selection_gate")
    if not full_scf_passed and not _list(payload.get("final_claim_blockers")):
        errors.append("blocked_full_scf_gate_without_final_claim_blocker")
    return {
        "schema_version": DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_deployment_decision_packet(
    run_dir: Path,
    *,
    architecture_winner_resolution_path: Path | None = None,
    deployment_recommendation_readiness_path: Path | None = None,
    deployment_target_selection_path: Path | None = None,
    targeted_deployment_accounting_path: Path | None = None,
) -> Dict[str, Any]:
    """Write decision packet, validation, and status artifacts into ``run_dir``."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_deployment_decision_packet(
        run_dir,
        architecture_winner_resolution_path=architecture_winner_resolution_path,
        deployment_recommendation_readiness_path=deployment_recommendation_readiness_path,
        deployment_target_selection_path=deployment_target_selection_path,
        targeted_deployment_accounting_path=targeted_deployment_accounting_path,
    )
    validation = validate_dft_hardware_deployment_decision_packet(payload)
    write_json(run_dir / "dft_hardware_deployment_decision_packet.json", payload)
    write_json(run_dir / "dft_hardware_deployment_decision_packet_validation.json", validation)
    status = {
        "schema_version": DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "decision_packet_status": payload.get("status"),
        "planning_packet_ready": payload.get("planning_packet_ready"),
        "can_name_scoped_hardware_ppa_winners": payload.get(
            "can_name_scoped_hardware_ppa_winners"
        ),
        "deployment_target_selection_ready": payload.get("deployment_target_selection_ready"),
        "full_scf_numerical_gate_passed": payload.get("full_scf_numerical_gate_passed"),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_hardware_deployment_decision_packet_status.json", status)
    return {
        "schema_version": "dse.dft.hardware_deployment_decision_packet_artifact_status.v1",
        "status": status["status"],
        "decision_packet": str(run_dir / "dft_hardware_deployment_decision_packet.json"),
        "decision_packet_validation": str(
            run_dir / "dft_hardware_deployment_decision_packet_validation.json"
        ),
        "decision_packet_status": str(run_dir / "dft_hardware_deployment_decision_packet_status.json"),
        "planning_packet_ready": payload.get("planning_packet_ready"),
        "can_name_scoped_hardware_ppa_winners": payload.get(
            "can_name_scoped_hardware_ppa_winners"
        ),
        "deployment_target_selection_ready": payload.get("deployment_target_selection_ready"),
        "full_scf_numerical_gate_passed": payload.get("full_scf_numerical_gate_passed"),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_SCHEMA",
    "DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_STATUS_SCHEMA",
    "DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_VALIDATION_SCHEMA",
    "build_dft_hardware_deployment_decision_packet",
    "validate_dft_hardware_deployment_decision_packet",
    "write_dft_hardware_deployment_decision_packet",
]
