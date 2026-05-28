#!/usr/bin/env python3
"""Target-tied full-SCF evaluated-hybrid accounting for DFT deployments.

This module records the narrow Step5 handoff that binds a scoped hardware-PPA
winner, a selected FPGA/ASIC target, and a full-SCF evaluated-hybrid cost
descriptor.  It is deliberately DFT-profile scoped and fail-closed: the artifact
can prove that target-tied accounting is present, but it cannot turn planning
state into a targeted/final deployment recommendation without independent
trusted full-SCF numerical/runtime rows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    DFT_FULL_SCF_RUNTIME_SCHEDULE_SCHEMA,
    MAJOR_SCF_ACCELERATED_KERNEL_IDS,
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
    validate_full_scf_evaluated_hybrid_payload,
)


DFT_FULL_SCF_TARGETED_DEPLOYMENT_ACCOUNTING_SCHEMA = (
    "dse.dft.full_scf_targeted_deployment_accounting.v1"
)
DFT_FULL_SCF_TARGETED_DEPLOYMENT_ACCOUNTING_VALIDATION_SCHEMA = (
    "dse.dft.full_scf_targeted_deployment_accounting_validation.v1"
)
DFT_FULL_SCF_TARGETED_DEPLOYMENT_ACCOUNTING_STATUS_SCHEMA = (
    "dse.dft.full_scf_targeted_deployment_accounting_status.v1"
)

TARGETED_ACCOUNTING_ARTIFACT_NAME = "dft_full_scf_targeted_deployment_accounting.json"
TARGETED_ACCOUNTING_VALIDATION_NAME = (
    "dft_full_scf_targeted_deployment_accounting_validation.json"
)
TARGETED_ACCOUNTING_STATUS_NAME = "dft_full_scf_targeted_deployment_accounting_status.json"

_DEPLOYMENTS = ("fpga", "asic")
_FORBIDDEN_FINAL_TRUE_FIELDS = (
    "can_name_targeted_deployment_recommendation",
    "can_name_final_recommendation",
    "trusted_final_claim",
    "deliverable_complete",
)
_CLAIM_BOUNDARY = (
    "DFT target-tied full-SCF accounting binds scoped hardware-PPA planning "
    "winners, selected deployment targets, and evaluated-hybrid host+accelerator "
    "cost models. It is accounting evidence only: it does not replace trusted "
    "full-SCF numerical/runtime rows and cannot mark a targeted/final FPGA/ASIC "
    "deployment recommendation complete."
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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _unique_strings(values: Sequence[Any]) -> list[str]:
    return sorted({str(value) for value in values if value not in (None, "")})


def _full_scf_comparison_path(run_dir: Path, full_scf_comparison_path: Path | None) -> Path:
    if full_scf_comparison_path is not None:
        return Path(full_scf_comparison_path)
    recheck = run_dir / "full_scf_end_to_end_comparison.recheck.json"
    if recheck.exists() and recheck.is_file():
        return recheck
    return run_dir / "full_scf_end_to_end_comparison.json"


def _hybrid_descriptor_path(
    run_dir: Path,
    *,
    deployment: str,
    hybrid_artifact_dir: Path | None,
) -> Path:
    if hybrid_artifact_dir is not None:
        return Path(hybrid_artifact_dir) / "full_scf_accelerator_descriptor.json"
    return (
        run_dir
        / "full_scf_targeted_deployment_accounting"
        / deployment
        / "full_scf_accelerator_descriptor.json"
    )


def _hybrid_runtime_schedule_path(
    run_dir: Path,
    *,
    deployment: str,
    hybrid_artifact_dir: Path | None,
) -> Path:
    if hybrid_artifact_dir is not None:
        return Path(hybrid_artifact_dir) / "full_scf_runtime_schedule.json"
    return (
        run_dir
        / "full_scf_targeted_deployment_accounting"
        / deployment
        / "full_scf_runtime_schedule.json"
    )


def _cost_mapping_complete(costs: Any, required_ids: Sequence[str]) -> tuple[bool, list[str]]:
    if not isinstance(costs, Mapping):
        return False, list(required_ids)
    missing = [item_id for item_id in required_ids if item_id not in costs]
    return not missing, missing


def _target_binding_from_runtime_abi(runtime_schedule: Mapping[str, Any]) -> Mapping[str, Any]:
    binding = _mapping(runtime_schedule.get("target_binding"))
    if binding:
        return binding
    for key in ("deployment_target", "selected_target", "target"):
        target = _mapping(runtime_schedule.get(key))
        if target:
            return {"selected_target": target}
    return {}


def _target_identity_mismatches(
    *,
    selected_target: Mapping[str, Any],
    runtime_target: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    mismatches: list[Dict[str, Any]] = []
    for key, runtime_value in runtime_target.items():
        if key not in selected_target:
            continue
        selected_value = selected_target.get(key)
        if str(selected_value) != str(runtime_value):
            mismatches.append(
                {
                    "field": str(key),
                    "decision_packet_value": selected_value,
                    "runtime_abi_value": runtime_value,
                }
            )
    return mismatches


def _runtime_schedule_blockers(
    *,
    deployment: str,
    runtime_schedule: Mapping[str, Any],
    candidate_id: str,
    selected_target: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    blockers: list[Dict[str, Any]] = []
    if runtime_schedule.get("schema_version") != DFT_FULL_SCF_RUNTIME_SCHEDULE_SCHEMA:
        blockers.append(
            {
                "blocker_id": "full_scf_runtime_schedule_schema_mismatch",
                "expected": DFT_FULL_SCF_RUNTIME_SCHEDULE_SCHEMA,
                "actual": runtime_schedule.get("schema_version"),
            }
        )
    runtime_candidate_id = str(runtime_schedule.get("candidate_id") or "")
    if runtime_candidate_id and candidate_id and runtime_candidate_id != candidate_id:
        blockers.append(
            {
                "blocker_id": "full_scf_runtime_schedule_candidate_mismatch",
                "winner_candidate_id": candidate_id,
                "runtime_schedule_candidate_id": runtime_candidate_id,
            }
        )
    if runtime_schedule.get("host_orchestrated") is not True:
        blockers.append({"blocker_id": "full_scf_runtime_schedule_not_host_orchestrated"})
    if set(runtime_schedule.get("accelerated_kernel_ids", []) or []) != set(
        MAJOR_SCF_ACCELERATED_KERNEL_IDS
    ):
        blockers.append(
            {
                "blocker_id": "full_scf_runtime_schedule_missing_major_kernels",
                "expected_kernel_ids": list(MAJOR_SCF_ACCELERATED_KERNEL_IDS),
                "actual_kernel_ids": runtime_schedule.get("accelerated_kernel_ids", []),
            }
        )
    if set(runtime_schedule.get("host_bound_phase_ids", []) or []) != set(
        REQUIRED_HOST_BOUND_PHASE_IDS
    ):
        blockers.append(
            {
                "blocker_id": "full_scf_runtime_schedule_missing_host_bound_phases",
                "expected_phase_ids": list(REQUIRED_HOST_BOUND_PHASE_IDS),
                "actual_phase_ids": runtime_schedule.get("host_bound_phase_ids", []),
            }
        )
    if set(runtime_schedule.get("runtime_overhead_ids", []) or []) != set(
        REQUIRED_OVERHEAD_PHASE_IDS
    ):
        blockers.append(
            {
                "blocker_id": "full_scf_runtime_schedule_missing_runtime_overheads",
                "expected_overhead_ids": list(REQUIRED_OVERHEAD_PHASE_IDS),
                "actual_overhead_ids": runtime_schedule.get("runtime_overhead_ids", []),
            }
        )
    target_binding = _target_binding_from_runtime_abi(runtime_schedule)
    binding_deployment = str(target_binding.get("deployment") or "")
    if binding_deployment and binding_deployment != deployment:
        blockers.append(
            {
                "blocker_id": "selected_target_runtime_abi_deployment_mismatch",
                "decision_packet_deployment": deployment,
                "runtime_abi_deployment": binding_deployment,
            }
        )
    runtime_target = _mapping(target_binding.get("selected_target"))
    mismatches = _target_identity_mismatches(
        selected_target=selected_target,
        runtime_target=runtime_target,
    )
    if mismatches:
        blockers.append(
            {
                "blocker_id": "selected_target_runtime_abi_mismatch",
                "mismatches": mismatches,
            }
        )
    return blockers


def _candidate_full_scf_gate(full_scf_comparison: Mapping[str, Any], candidate_id: str) -> Dict[str, Any]:
    candidate_records = [
        record
        for record in _list(full_scf_comparison.get("candidate_records"))
        if isinstance(record, Mapping) and str(record.get("candidate_id") or "") == candidate_id
    ]
    row_records = [
        record
        for record in _list(full_scf_comparison.get("row_records"))
        if isinstance(record, Mapping) and str(record.get("candidate_id") or "") == candidate_id
    ]
    candidate_record = dict(candidate_records[0]) if candidate_records else {}
    row_count = len(row_records)
    passed_row_count = sum(1 for row in row_records if row.get("passed") is True)
    candidate_passed = bool(candidate_record.get("passed") is True)
    top_level_passed = full_scf_comparison.get("passed") is True
    return {
        "comparison_present": bool(full_scf_comparison),
        "candidate_record_present": bool(candidate_record),
        "candidate_passed": candidate_passed,
        "top_level_comparison_passed": top_level_passed,
        "passed": bool(top_level_passed and candidate_passed),
        "row_record_count": row_count,
        "passed_row_record_count": passed_row_count,
        "blocked_row_record_count": max(0, row_count - passed_row_count),
        "trusted_accelerated_numeric_source": bool(
            candidate_record.get("trusted_accelerated_numeric_source", False)
        ),
        "blockers": candidate_record.get("blockers", []) if candidate_record else [],
    }


def _deployment_from_sources(
    *,
    deployment: str,
    run_dir: Path,
    decision_packet_path: Path,
    decision_packet: Mapping[str, Any],
    full_scf_comparison: Mapping[str, Any],
    hybrid_artifact_dir: Path | None,
) -> Dict[str, Any]:
    decision_deployment = _mapping(_mapping(decision_packet.get("deployments")).get(deployment))
    winner = _mapping(decision_deployment.get("scoped_hardware_ppa_winner"))
    selected_target = _mapping(decision_deployment.get("selected_target"))
    candidate_id = str(winner.get("candidate_id") or "")
    design_candidate_id = str(winner.get("design_candidate_id") or winner.get("design_identity") or "")
    descriptor_path = _hybrid_descriptor_path(
        run_dir,
        deployment=deployment,
        hybrid_artifact_dir=hybrid_artifact_dir,
    )
    runtime_schedule_path = _hybrid_runtime_schedule_path(
        run_dir,
        deployment=deployment,
        hybrid_artifact_dir=hybrid_artifact_dir,
    )
    descriptor = _load_json(descriptor_path)
    runtime_schedule = _load_json(runtime_schedule_path)
    descriptor_validation = (
        validate_full_scf_evaluated_hybrid_payload(descriptor)
        if descriptor
        else {
            "passed": False,
            "status": "blocked",
            "blocker_ids": ["full_scf_hybrid_descriptor_missing"],
        }
    )
    descriptor_candidate_id = str(descriptor.get("candidate_id") or "")
    cost_model = _mapping(descriptor.get("cost_model"))
    accelerated_costs = _mapping(cost_model.get("accelerated_kernel_costs_s"))
    host_costs = _mapping(cost_model.get("host_bound_phase_costs_s"))
    overhead_costs = _mapping(cost_model.get("runtime_overhead_costs_s"))
    accelerated_complete, missing_accelerated = _cost_mapping_complete(
        accelerated_costs,
        MAJOR_SCF_ACCELERATED_KERNEL_IDS,
    )
    host_complete, missing_host = _cost_mapping_complete(
        host_costs,
        REQUIRED_HOST_BOUND_PHASE_IDS,
    )
    overhead_complete, missing_overhead = _cost_mapping_complete(
        overhead_costs,
        REQUIRED_OVERHEAD_PHASE_IDS,
    )

    blockers: list[Dict[str, Any]] = []
    if not decision_deployment:
        blockers.append({"blocker_id": "decision_packet_deployment_missing"})
    if not winner:
        blockers.append({"blocker_id": "scoped_hardware_ppa_winner_missing"})
    if not candidate_id:
        blockers.append({"blocker_id": "scoped_hardware_ppa_winner_candidate_missing"})
    if not selected_target:
        blockers.append({"blocker_id": "selected_deployment_target_missing"})
    if not descriptor:
        blockers.append({"blocker_id": "full_scf_hybrid_descriptor_missing"})
    if not runtime_schedule:
        blockers.append({"blocker_id": "full_scf_runtime_schedule_missing"})
    if descriptor and descriptor_validation.get("passed") is not True:
        blockers.append(
            {
                "blocker_id": "full_scf_hybrid_descriptor_validation_blocked",
                "descriptor_validation_status": descriptor_validation.get("status"),
                "descriptor_validation_blocker_ids": descriptor_validation.get("blocker_ids", []),
            }
        )
    if descriptor_candidate_id and candidate_id and descriptor_candidate_id != candidate_id:
        blockers.append(
            {
                "blocker_id": "full_scf_hybrid_descriptor_candidate_mismatch",
                "winner_candidate_id": candidate_id,
                "descriptor_candidate_id": descriptor_candidate_id,
            }
        )
    if runtime_schedule:
        blockers.extend(
            _runtime_schedule_blockers(
                deployment=deployment,
                runtime_schedule=runtime_schedule,
                candidate_id=candidate_id,
                selected_target=selected_target,
            )
        )
    if not accelerated_complete:
        blockers.append(
            {
                "blocker_id": "accelerated_kernel_costs_missing",
                "missing_kernel_ids": missing_accelerated,
            }
        )
    if not host_complete:
        blockers.append(
            {
                "blocker_id": "host_bound_phase_costs_missing",
                "missing_phase_ids": missing_host,
            }
        )
    if not overhead_complete:
        blockers.append(
            {
                "blocker_id": "runtime_overhead_costs_missing",
                "missing_overhead_ids": missing_overhead,
            }
        )

    full_scf_gate = _candidate_full_scf_gate(full_scf_comparison, candidate_id)
    accounting_ready = not blockers
    final_claim_blockers: list[Dict[str, Any]] = []
    if full_scf_gate.get("passed") is not True:
        final_claim_blockers.append(
            {
                "blocker_id": "full_scf_numerical_gate_not_passed",
                "comparison_present": full_scf_gate.get("comparison_present"),
                "candidate_record_present": full_scf_gate.get("candidate_record_present"),
                "candidate_passed": full_scf_gate.get("candidate_passed"),
                "top_level_comparison_passed": full_scf_gate.get("top_level_comparison_passed"),
                "trusted_accelerated_numeric_source": full_scf_gate.get(
                    "trusted_accelerated_numeric_source"
                ),
            }
        )
    return {
        "schema_version": "dse.dft.full_scf_targeted_deployment_accounting.deployment.v1",
        "deployment": deployment,
        "status": (
            "targeted_accounting_ready_pending_full_scf_numerical_gate"
            if accounting_ready and full_scf_gate.get("passed") is not True
            else "targeted_accounting_ready_full_scf_gate_passed_final_review_required"
            if accounting_ready
            else "blocked_targeted_accounting"
        ),
        "accounting_ready": accounting_ready,
        "projection_only": bool((not accounting_ready) or full_scf_gate.get("passed") is not True),
        "full_scf_numerical_gate_passed": bool(full_scf_gate.get("passed", False)),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "candidate_id": candidate_id,
        "representative_candidate_id": str(winner.get("representative_candidate_id") or candidate_id),
        "design_candidate_id": design_candidate_id,
        "scoped_hardware_ppa_metrics": dict(_mapping(winner.get("metrics"))),
        "selected_target": dict(selected_target),
        "descriptor_candidate_id": descriptor_candidate_id,
        "descriptor_validation_status": descriptor_validation.get("status"),
        "descriptor_validation_passed": bool(descriptor_validation.get("passed", False)),
        "cost_model": dict(cost_model),
        "accelerated_kernel_costs_s": dict(accelerated_costs),
        "host_bound_phase_costs_s": dict(host_costs),
        "runtime_overhead_costs_s": dict(overhead_costs),
        "host_bound_costs_included": host_complete,
        "runtime_overheads_included": overhead_complete,
        "accelerated_kernel_costs_included": accelerated_complete,
        "covered_accelerated_kernel_ids": list(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
        if accelerated_complete
        else _unique_strings(accelerated_costs.keys()),
        "host_bound_phase_ids": list(REQUIRED_HOST_BOUND_PHASE_IDS) if host_complete else _unique_strings(host_costs.keys()),
        "runtime_overhead_ids": list(REQUIRED_OVERHEAD_PHASE_IDS) if overhead_complete else _unique_strings(overhead_costs.keys()),
        "full_scf_numerical_gate": full_scf_gate,
        "source_artifacts": {
            "decision_packet": _source_ref(decision_packet_path, required=False),
            "full_scf_hybrid_descriptor": _source_ref(descriptor_path, required=True),
            "full_scf_runtime_schedule": _source_ref(runtime_schedule_path, required=True),
        },
        "blockers": blockers,
        "blocker_ids": [str(blocker.get("blocker_id")) for blocker in blockers],
        "final_claim_blockers": final_claim_blockers,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_full_scf_targeted_deployment_accounting(
    run_dir: Path,
    *,
    decision_packet_path: Path | None = None,
    fpga_hybrid_artifact_dir: Path | None = None,
    asic_hybrid_artifact_dir: Path | None = None,
    full_scf_comparison_path: Path | None = None,
) -> Dict[str, Any]:
    """Build target-tied full-SCF accounting from decision packet and descriptors."""

    run_dir = Path(run_dir)
    decision_path = Path(decision_packet_path) if decision_packet_path else run_dir / "dft_hardware_deployment_decision_packet.json"
    comparison_path = _full_scf_comparison_path(run_dir, full_scf_comparison_path)
    decision_packet = _load_json(decision_path)
    full_scf_comparison = _load_json(comparison_path)
    hybrid_dirs = {
        "fpga": fpga_hybrid_artifact_dir,
        "asic": asic_hybrid_artifact_dir,
    }
    deployments = {
        deployment: _deployment_from_sources(
            deployment=deployment,
            run_dir=run_dir,
            decision_packet_path=decision_path,
            decision_packet=decision_packet,
            full_scf_comparison=full_scf_comparison,
            hybrid_artifact_dir=hybrid_dirs[deployment],
        )
        for deployment in _DEPLOYMENTS
    }
    targeted_accounting_ready = all(
        deployments[deployment].get("accounting_ready") is True
        for deployment in _DEPLOYMENTS
    )
    full_scf_passed = all(
        deployments[deployment].get("full_scf_numerical_gate_passed") is True
        for deployment in _DEPLOYMENTS
    )
    payload = {
        "schema_version": DFT_FULL_SCF_TARGETED_DEPLOYMENT_ACCOUNTING_SCHEMA,
        "generated_at": _now_iso(),
        "status": (
            "targeted_accounting_ready_final_recommendation_blocked"
            if targeted_accounting_ready and not full_scf_passed
            else "targeted_accounting_ready_full_scf_gate_passed_final_review_required"
            if targeted_accounting_ready and full_scf_passed
            else "blocked_targeted_accounting"
        ),
        "run_dir": str(run_dir),
        "targeted_accounting_ready": targeted_accounting_ready,
        "projection_only": bool((not targeted_accounting_ready) or not full_scf_passed),
        "full_scf_numerical_gate_passed": full_scf_passed,
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "deployments": deployments,
        "source_artifacts": {
            "decision_packet": _source_ref(decision_path, required=True),
            "full_scf_end_to_end_comparison": _source_ref(comparison_path, required=False),
        },
        "final_claim_blockers": [
            {
                "deployment": deployment,
                **blocker,
            }
            for deployment in _DEPLOYMENTS
            for blocker in deployments[deployment].get("final_claim_blockers", [])
        ],
        "blocker_ids": _unique_strings(
            [
                f"{deployment}:{blocker_id}"
                for deployment in _DEPLOYMENTS
                for blocker_id in deployments[deployment].get("blocker_ids", [])
            ]
        ),
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    payload["validation"] = validate_dft_full_scf_targeted_deployment_accounting(payload)
    return payload


def validate_dft_full_scf_targeted_deployment_accounting(
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    """Validate fail-closed target-tied accounting semantics."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_FULL_SCF_TARGETED_DEPLOYMENT_ACCOUNTING_SCHEMA:
        errors.append("schema_version_mismatch")
    for field in _FORBIDDEN_FINAL_TRUE_FIELDS:
        if payload.get(field) is True:
            errors.append(f"{field}_must_remain_false")
    deployments = _mapping(payload.get("deployments"))
    if set(deployments.keys()) != set(_DEPLOYMENTS):
        errors.append("deployments_must_include_fpga_and_asic")
    top_ready = all(
        _mapping(deployments.get(deployment)).get("accounting_ready") is True
        for deployment in _DEPLOYMENTS
    )
    if payload.get("targeted_accounting_ready") is not bool(top_ready):
        errors.append("targeted_accounting_ready_flag_mismatch")
    full_scf_passed = all(
        _mapping(deployments.get(deployment)).get("full_scf_numerical_gate_passed") is True
        for deployment in _DEPLOYMENTS
    )
    if payload.get("full_scf_numerical_gate_passed") is not bool(full_scf_passed):
        errors.append("full_scf_numerical_gate_passed_flag_mismatch")
    expected_projection_only = bool((not top_ready) or not full_scf_passed)
    if payload.get("projection_only") is not expected_projection_only:
        errors.append("projection_only_flag_mismatch")
    for deployment in _DEPLOYMENTS:
        item = _mapping(deployments.get(deployment))
        for field in _FORBIDDEN_FINAL_TRUE_FIELDS:
            if item.get(field) is True:
                errors.append(f"{deployment}_{field}_must_remain_false")
        expected_item_projection_only = bool(
            item.get("accounting_ready") is not True
            or item.get("full_scf_numerical_gate_passed") is not True
        )
        if item.get("projection_only") is not expected_item_projection_only:
            errors.append(f"{deployment}_projection_only_flag_mismatch")
        if item.get("accounting_ready") is True:
            if not item.get("candidate_id"):
                errors.append(f"{deployment}_accounting_ready_without_candidate_id")
            if not item.get("design_candidate_id"):
                errors.append(f"{deployment}_accounting_ready_without_design_candidate_id")
            if not _mapping(item.get("selected_target")):
                errors.append(f"{deployment}_accounting_ready_without_selected_target")
            if item.get("descriptor_validation_passed") is not True:
                errors.append(f"{deployment}_accounting_ready_without_descriptor_validation")
            if item.get("descriptor_candidate_id") != item.get("candidate_id"):
                errors.append(f"{deployment}_accounting_ready_descriptor_candidate_mismatch")
            if item.get("host_bound_costs_included") is not True:
                errors.append(f"{deployment}_accounting_ready_without_host_costs")
            if item.get("runtime_overheads_included") is not True:
                errors.append(f"{deployment}_accounting_ready_without_runtime_overheads")
            if item.get("accelerated_kernel_costs_included") is not True:
                errors.append(f"{deployment}_accounting_ready_without_accelerated_kernel_costs")
            if set(item.get("covered_accelerated_kernel_ids", []) or []) != set(
                MAJOR_SCF_ACCELERATED_KERNEL_IDS
            ):
                errors.append(f"{deployment}_accounting_ready_without_all_major_kernels")
        if item.get("full_scf_numerical_gate_passed") is not True and not _list(
            item.get("final_claim_blockers")
        ):
            errors.append(f"{deployment}_missing_full_scf_final_claim_blocker")
    if payload.get("full_scf_numerical_gate_passed") is not True and not _list(
        payload.get("final_claim_blockers")
    ):
        errors.append("missing_top_level_full_scf_final_claim_blocker")
    return {
        "schema_version": DFT_FULL_SCF_TARGETED_DEPLOYMENT_ACCOUNTING_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def summarize_full_scf_targeted_deployment_accounting(
    payload: Mapping[str, Any],
    validation: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return readiness-friendly summary for a target-tied accounting artifact."""

    validation = validation or {}
    deployments = _mapping(payload.get("deployments"))
    result: Dict[str, Any] = {
        "present": bool(payload),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status") if payload else "missing",
        "validation_valid": validation.get("valid") if validation else None,
        "targeted_accounting_ready": bool(payload.get("targeted_accounting_ready", False)),
        "projection_only": bool(payload.get("projection_only", True)),
        "full_scf_numerical_gate_passed": bool(payload.get("full_scf_numerical_gate_passed", False)),
        "blocker_ids": payload.get("blocker_ids", []) if payload else ["targeted_accounting_missing"],
        "deployments": {},
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    for deployment in _DEPLOYMENTS:
        item = _mapping(deployments.get(deployment))
        ready = bool(
            payload
            and validation.get("valid") is True
            and item.get("accounting_ready") is True
        )
        result["deployments"][deployment] = {
            "present": bool(item),
            "status": item.get("status") if item else "missing",
            "accounting_ready": ready,
            "projection_only": bool(item.get("projection_only", True)),
            "candidate_id": item.get("candidate_id"),
            "design_candidate_id": item.get("design_candidate_id"),
            "selected_target": item.get("selected_target", {}) if item else {},
            "host_bound_costs_included": bool(item.get("host_bound_costs_included", False)),
            "runtime_overheads_included": bool(item.get("runtime_overheads_included", False)),
            "accelerated_kernel_costs_included": bool(
                item.get("accelerated_kernel_costs_included", False)
            ),
            "host_bound_phase_ids": list(item.get("host_bound_phase_ids", []) or []),
            "runtime_overhead_ids": list(item.get("runtime_overhead_ids", []) or []),
            "covered_accelerated_kernel_ids": list(
                item.get("covered_accelerated_kernel_ids", []) or []
            ),
            "host_bound_phase_costs_s": dict(_mapping(item.get("host_bound_phase_costs_s"))),
            "runtime_overhead_costs_s": dict(_mapping(item.get("runtime_overhead_costs_s"))),
            "accelerated_kernel_costs_s": dict(_mapping(item.get("accelerated_kernel_costs_s"))),
            "full_scf_numerical_gate_passed": bool(
                item.get("full_scf_numerical_gate_passed", False)
            ),
            "blocker_ids": item.get("blocker_ids", []) if item else ["targeted_accounting_missing"],
            "final_claim_blockers": item.get("final_claim_blockers", []) if item else [],
        }
    return result


def write_dft_full_scf_targeted_deployment_accounting(
    run_dir: Path,
    *,
    decision_packet_path: Path | None = None,
    fpga_hybrid_artifact_dir: Path | None = None,
    asic_hybrid_artifact_dir: Path | None = None,
    full_scf_comparison_path: Path | None = None,
) -> Dict[str, Any]:
    """Write target-tied full-SCF accounting, validation, and status artifacts."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_full_scf_targeted_deployment_accounting(
        run_dir,
        decision_packet_path=decision_packet_path,
        fpga_hybrid_artifact_dir=fpga_hybrid_artifact_dir,
        asic_hybrid_artifact_dir=asic_hybrid_artifact_dir,
        full_scf_comparison_path=full_scf_comparison_path,
    )
    validation = validate_dft_full_scf_targeted_deployment_accounting(payload)
    payload["validation"] = validation
    write_json(run_dir / TARGETED_ACCOUNTING_ARTIFACT_NAME, payload)
    write_json(run_dir / TARGETED_ACCOUNTING_VALIDATION_NAME, validation)
    status = {
        "schema_version": DFT_FULL_SCF_TARGETED_DEPLOYMENT_ACCOUNTING_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "targeted_accounting_status": payload.get("status"),
        "targeted_accounting_ready": payload.get("targeted_accounting_ready"),
        "projection_only": payload.get("projection_only", True),
        "full_scf_numerical_gate_passed": payload.get("full_scf_numerical_gate_passed"),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / TARGETED_ACCOUNTING_STATUS_NAME, status)
    return {
        "schema_version": "dse.dft.full_scf_targeted_deployment_accounting_artifact_status.v1",
        "status": status["status"],
        "targeted_accounting": str(run_dir / TARGETED_ACCOUNTING_ARTIFACT_NAME),
        "targeted_accounting_validation": str(run_dir / TARGETED_ACCOUNTING_VALIDATION_NAME),
        "targeted_accounting_status": str(run_dir / TARGETED_ACCOUNTING_STATUS_NAME),
        "targeted_accounting_ready": payload.get("targeted_accounting_ready"),
        "projection_only": payload.get("projection_only", True),
        "full_scf_numerical_gate_passed": payload.get("full_scf_numerical_gate_passed"),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_FULL_SCF_TARGETED_DEPLOYMENT_ACCOUNTING_SCHEMA",
    "DFT_FULL_SCF_TARGETED_DEPLOYMENT_ACCOUNTING_STATUS_SCHEMA",
    "DFT_FULL_SCF_TARGETED_DEPLOYMENT_ACCOUNTING_VALIDATION_SCHEMA",
    "TARGETED_ACCOUNTING_ARTIFACT_NAME",
    "TARGETED_ACCOUNTING_STATUS_NAME",
    "TARGETED_ACCOUNTING_VALIDATION_NAME",
    "build_dft_full_scf_targeted_deployment_accounting",
    "summarize_full_scf_targeted_deployment_accounting",
    "validate_dft_full_scf_targeted_deployment_accounting",
    "write_dft_full_scf_targeted_deployment_accounting",
]
