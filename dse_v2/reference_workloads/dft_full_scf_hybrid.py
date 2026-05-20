#!/usr/bin/env python3
"""DFT-scoped full-SCF evaluated-hybrid descriptor and cost payloads.

This module is intentionally kept under ``reference_workloads`` so the generic
DSE control plane does not learn DFT/QE phase names.  The first prototype is a
host-orchestrated full-SCF evaluated hybrid: only the eight major SCF kernels may
carry hardware-acceleration claims, while host-bound SCF phases and runtime
overheads must be explicit costs in the end-to-end model.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence


DFT_FULL_SCF_HYBRID_DESCRIPTOR_SCHEMA = "dse.dft_scf.full_scf_evaluated_hybrid_descriptor.v1"
DFT_FULL_SCF_HYBRID_VALIDATION_SCHEMA = "dse.dft_scf.full_scf_evaluated_hybrid_validation.v1"
DFT_FULL_SCF_RUNTIME_SCHEDULE_SCHEMA = "dse.dft_scf.full_scf_runtime_schedule.v1"
DFT_FULL_SCF_DATA_RESIDENCY_SCHEMA = "dse.dft_scf.full_scf_data_residency_plan.v1"
DFT_FULL_SCF_CORRECTNESS_REPORT_SCHEMA = "dse.dft_scf.full_scf_correctness_report.v1"
DFT_FULL_SCF_PPA_SUMMARY_SCHEMA = "dse.dft_scf.full_scf_ppa_summary.v1"

FULL_SCF_HYBRID_ARTIFACT_NAMES: tuple[str, ...] = (
    "full_scf_accelerator_descriptor.json",
    "full_scf_runtime_schedule.json",
    "full_scf_data_residency_plan.json",
    "full_scf_correctness_report.json",
    "full_scf_ppa_summary.json",
)

MAJOR_SCF_ACCELERATED_KERNEL_IDS: tuple[str, ...] = (
    "fft_ifft_ffft",
    "transpose_layout_conversion",
    "hpsi_local_potential",
    "kinetic_add",
    "nonlocal_projector",
    "complex_gemm_gemv_tile",
    "reduction_dot_tree",
    "dma_hbm_movement_engine",
)

REQUIRED_HOST_BOUND_PHASE_IDS: tuple[str, ...] = (
    "io",
    "scf_control",
    "convergence",
    "diagonalization",
    "mixing",
)

REQUIRED_OVERHEAD_PHASE_IDS: tuple[str, ...] = (
    "transfer",
    "synchronization",
    "queueing",
    "layout",
)

_ALLOWED_CATEGORIES = {"accelerated_kernel", "host_bound_phase", "runtime_overhead"}


class DftFullScfHybridValidationError(ValueError):
    """Raised when a fail-closed full-SCF hybrid payload is incomplete."""


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite_nonnegative(value: Any, *, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise DftFullScfHybridValidationError(
            f"{field_name} must be a finite non-negative number, got {value!r}"
        ) from exc
    if not math.isfinite(parsed) or parsed < 0.0:
        raise DftFullScfHybridValidationError(
            f"{field_name} must be a finite non-negative number, got {value!r}"
        )
    return parsed


def _require_costs(
    costs_s: Mapping[str, Any],
    required_ids: Sequence[str],
    *,
    field_name: str,
) -> Dict[str, float]:
    missing = [phase_id for phase_id in required_ids if phase_id not in costs_s]
    if missing:
        raise DftFullScfHybridValidationError(
            f"{field_name} missing required cost ids: {', '.join(missing)}"
        )
    return {
        phase_id: _finite_nonnegative(costs_s[phase_id], field_name=f"{field_name}.{phase_id}")
        for phase_id in required_ids
    }


def _schedule_piece_ids(schedule: Iterable[Mapping[str, Any]], category: str, id_key: str) -> set[str]:
    return {
        str(piece.get(id_key) or "")
        for piece in schedule
        if piece.get("category") == category and str(piece.get(id_key) or "")
    }


def _blocker(blocker_id: str, reason: str, **extra: Any) -> Dict[str, Any]:
    return {"id": blocker_id, "reason": reason, **extra}


def validate_full_scf_evaluated_hybrid_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a DFT/QE full-SCF evaluated-hybrid descriptor fail-closed.

    The validator intentionally rejects payloads that hide required host-bound
    costs, add non-major-kernel acceleration claims, or mark host/overhead work
    as hardware acceleration.  It validates the DFT reference payload only; it
    does not satisfy the independent HLS/RTL/FPGA/ASIC evidence gates.
    """

    blockers: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_FULL_SCF_HYBRID_DESCRIPTOR_SCHEMA:
        blockers.append(
            _blocker(
                "unsupported_schema_version",
                "payload must use the full-SCF evaluated-hybrid descriptor schema",
                expected=DFT_FULL_SCF_HYBRID_DESCRIPTOR_SCHEMA,
                actual=payload.get("schema_version"),
            )
        )
    if payload.get("prototype_boundary") != "full_scf_evaluated_hybrid":
        blockers.append(
            _blocker(
                "wrong_prototype_boundary",
                "first prototype must be full-SCF evaluated hybrid",
                actual=payload.get("prototype_boundary"),
            )
        )
    if payload.get("device_residency") == "full_scf_device_resident":
        blockers.append(
            _blocker(
                "device_resident_boundary_forbidden",
                "first prototype is not a full-SCF device-resident accelerator",
            )
        )

    raw_schedule = payload.get("schedule")
    schedule = [piece for piece in raw_schedule if isinstance(piece, Mapping)] if isinstance(raw_schedule, list) else []
    if not schedule:
        blockers.append(_blocker("missing_schedule", "payload must include schedule pieces"))

    accelerated_ids = _schedule_piece_ids(schedule, "accelerated_kernel", "kernel_id")
    host_ids = _schedule_piece_ids(schedule, "host_bound_phase", "phase_id")
    overhead_ids = _schedule_piece_ids(schedule, "runtime_overhead", "overhead_id")

    missing_accelerated = sorted(set(MAJOR_SCF_ACCELERATED_KERNEL_IDS) - accelerated_ids)
    if missing_accelerated:
        blockers.append(
            _blocker(
                "missing_accelerated_kernel_phase",
                "all eight major SCF accelerated-kernel schedule pieces must be present",
                missing_kernel_ids=missing_accelerated,
            )
        )
    missing_host = sorted(set(REQUIRED_HOST_BOUND_PHASE_IDS) - host_ids)
    if missing_host:
        blockers.append(
            _blocker(
                "missing_host_bound_phase",
                "host-bound SCF phases must be explicit and costed",
                missing_phase_ids=missing_host,
            )
        )
    missing_overhead = sorted(set(REQUIRED_OVERHEAD_PHASE_IDS) - overhead_ids)
    if missing_overhead:
        blockers.append(
            _blocker(
                "missing_runtime_overhead_phase",
                "transfer/sync/queue/layout overheads must be explicit and costed",
                missing_overhead_ids=missing_overhead,
            )
        )

    allowed_accelerated = set(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
    required_host = set(REQUIRED_HOST_BOUND_PHASE_IDS)
    required_overhead = set(REQUIRED_OVERHEAD_PHASE_IDS)
    for index, piece in enumerate(schedule):
        category = str(piece.get("category") or "")
        if category not in _ALLOWED_CATEGORIES:
            blockers.append(
                _blocker(
                    "unsupported_schedule_category",
                    "schedule piece category must be accelerated_kernel, host_bound_phase, or runtime_overhead",
                    schedule_index=index,
                    category=category,
                )
            )
            continue
        try:
            _finite_nonnegative(piece.get("cost_s"), field_name=f"schedule[{index}].cost_s")
        except DftFullScfHybridValidationError as exc:
            blockers.append(
                _blocker(
                    "invalid_schedule_cost",
                    str(exc),
                    schedule_index=index,
                    piece_id=piece.get("piece_id"),
                )
            )
        claims_accel = bool(piece.get("hardware_acceleration_claim"))
        if category == "accelerated_kernel":
            kernel_id = str(piece.get("kernel_id") or "")
            if kernel_id not in allowed_accelerated:
                blockers.append(
                    _blocker(
                        "unsupported_accelerated_kernel",
                        "hardware acceleration claims are restricted to the eight major SCF kernels",
                        schedule_index=index,
                        kernel_id=kernel_id,
                    )
                )
            if not claims_accel:
                blockers.append(
                    _blocker(
                        "accelerated_kernel_missing_claim_marker",
                        "accelerated-kernel schedule pieces must explicitly mark hardware_acceleration_claim=true",
                        schedule_index=index,
                        kernel_id=kernel_id,
                    )
                )
            phase_id = str(piece.get("phase_id") or "")
            if phase_id in required_host:
                blockers.append(
                    _blocker(
                        "host_bound_phase_counted_as_acceleration",
                        "host-bound SCF phases cannot be counted as hardware acceleration",
                        schedule_index=index,
                        phase_id=phase_id,
                    )
                )
        elif category == "host_bound_phase":
            phase_id = str(piece.get("phase_id") or "")
            if phase_id not in required_host:
                blockers.append(
                    _blocker(
                        "unsupported_host_bound_phase",
                        "host-bound first-prototype phase is not part of the required SCF host set",
                        schedule_index=index,
                        phase_id=phase_id,
                    )
                )
            if claims_accel:
                blockers.append(
                    _blocker(
                        "host_bound_phase_counted_as_acceleration",
                        "host-bound SCF phases cannot be counted as hardware acceleration",
                        schedule_index=index,
                        phase_id=phase_id,
                    )
                )
        elif category == "runtime_overhead":
            overhead_id = str(piece.get("overhead_id") or "")
            if overhead_id not in required_overhead:
                blockers.append(
                    _blocker(
                        "unsupported_runtime_overhead_phase",
                        "runtime overhead must be transfer, synchronization, queueing, or layout",
                        schedule_index=index,
                        overhead_id=overhead_id,
                    )
                )
            if claims_accel:
                blockers.append(
                    _blocker(
                        "runtime_overhead_counted_as_acceleration",
                        "transfer/sync/queue/layout overheads cannot be counted as hardware acceleration",
                        schedule_index=index,
                        overhead_id=overhead_id,
                    )
                )

    cost_model = _as_mapping(payload.get("cost_model"))
    if not cost_model:
        blockers.append(_blocker("missing_cost_model", "payload must include machine-readable cost_model"))
    else:
        for field_name in (
            "accelerated_kernel_cost_s",
            "host_bound_cost_s",
            "runtime_overhead_cost_s",
            "evaluated_hybrid_scf_time_s",
        ):
            if field_name not in cost_model:
                blockers.append(
                    _blocker(
                        "missing_cost_model_field",
                        "cost_model is missing a required aggregate field",
                        field=field_name,
                    )
                )
            else:
                try:
                    _finite_nonnegative(cost_model[field_name], field_name=f"cost_model.{field_name}")
                except DftFullScfHybridValidationError as exc:
                    blockers.append(_blocker("invalid_cost_model_field", str(exc), field=field_name))

    return {
        "schema_version": DFT_FULL_SCF_HYBRID_VALIDATION_SCHEMA,
        "status": "passed" if not blockers else "blocked",
        "passed": not blockers,
        "blockers": blockers,
        "blocker_ids": [str(item["id"]) for item in blockers],
        "required_accelerated_kernel_ids": list(MAJOR_SCF_ACCELERATED_KERNEL_IDS),
        "required_host_bound_phase_ids": list(REQUIRED_HOST_BOUND_PHASE_IDS),
        "required_overhead_phase_ids": list(REQUIRED_OVERHEAD_PHASE_IDS),
        "claim_boundary": (
            "Validates only the DFT-scoped full-SCF evaluated-hybrid descriptor/cost shape; "
            "it is not HLS/RTL/FPGA/ASIC evidence or final DSE completion."
        ),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_full_scf_evaluated_hybrid_artifact_bundle(
    payload: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Build the Wave-4 full-SCF evaluated-hybrid artifact bundle.

    The bundle is descriptor/cost/schedule evidence only.  It deliberately keeps
    numerical correctness and PPA claim eligibility false until independent
    golden/HLS-or-RTL/Vivado/DC gates are attached.
    """

    validation = validate_full_scf_evaluated_hybrid_payload(payload)
    descriptor = dict(payload)
    descriptor["validation"] = validation

    schedule = [dict(piece) for piece in payload.get("schedule", []) if isinstance(piece, Mapping)]
    cost_model = dict(_as_mapping(payload.get("cost_model")))
    accelerated_kernel_ids = [
        str(piece.get("kernel_id"))
        for piece in schedule
        if piece.get("category") == "accelerated_kernel"
    ]
    host_bound_phase_ids = [
        str(piece.get("phase_id"))
        for piece in schedule
        if piece.get("category") == "host_bound_phase"
    ]
    runtime_overhead_ids = [
        str(piece.get("overhead_id"))
        for piece in schedule
        if piece.get("category") == "runtime_overhead"
    ]

    common_scope = {
        "descriptor_id": payload.get("descriptor_id"),
        "candidate_id": payload.get("candidate_id"),
        "campaign_id": payload.get("campaign_id"),
        "workload_run_id": payload.get("workload_run_id"),
        "trial_id": payload.get("trial_id"),
        "prototype_boundary": payload.get("prototype_boundary"),
        "device_residency": payload.get("device_residency"),
        "completion_claim": False,
    }
    runtime_schedule = {
        "schema_version": DFT_FULL_SCF_RUNTIME_SCHEDULE_SCHEMA,
        **common_scope,
        "schedule": schedule,
        "accelerated_kernel_ids": accelerated_kernel_ids,
        "host_bound_phase_ids": host_bound_phase_ids,
        "runtime_overhead_ids": runtime_overhead_ids,
        "host_orchestrated": True,
        "claim_boundary": (
            "Runtime schedule for a full-SCF evaluated hybrid.  Host-bound "
            "control/diagonalization/mixing and runtime overheads are counted "
            "and are not hardware acceleration benefits."
        ),
    }
    data_residency_plan = {
        "schema_version": DFT_FULL_SCF_DATA_RESIDENCY_SCHEMA,
        **common_scope,
        "host_resident_phase_ids": host_bound_phase_ids,
        "accelerator_kernel_ids": accelerated_kernel_ids,
        "runtime_movement_overhead_ids": runtime_overhead_ids,
        "data_residency_boundary": (
            "First prototype is not full-SCF device-resident.  I/O, SCF "
            "control, convergence, diagonalization, and mixing remain host "
            "resident unless a later artifact passes the same claim gates."
        ),
        "claim_boundary": "Residency plan is accounting evidence, not PPA or correctness evidence.",
    }
    correctness_report = {
        "schema_version": DFT_FULL_SCF_CORRECTNESS_REPORT_SCHEMA,
        **common_scope,
        "status": "blocked_temporary",
        "descriptor_validation": validation,
        "descriptor_shape_valid": bool(validation.get("passed", False)),
        "numerical_correctness_claim_eligible": False,
        "required_before_correctness_claim": [
            "golden reference outputs for each strict workload case",
            "per-kernel golden correctness",
            "end-to-end SCF numerical comparison for host+accelerator schedule",
        ],
        "claim_boundary": (
            "Descriptor validation is not numerical correctness.  The full-SCF "
            "correctness claim remains blocked until reference outputs and "
            "comparison artifacts are attached."
        ),
    }
    ppa_summary = {
        "schema_version": DFT_FULL_SCF_PPA_SUMMARY_SCHEMA,
        **common_scope,
        "status": "blocked_temporary",
        "cost_model": cost_model,
        "accelerated_kernel_costs_s": cost_model.get("accelerated_kernel_costs_s", {}),
        "host_bound_phase_costs_s": cost_model.get("host_bound_phase_costs_s", {}),
        "runtime_overhead_costs_s": cost_model.get("runtime_overhead_costs_s", {}),
        "ppa_claim_eligible": False,
        "required_before_fpga_ppa_claim": [
            "per-claimed-kernel golden correctness",
            "HLS C-sim or RTL sim",
            "HLS C-synth or RTL synth",
            "Vivado synthesis/implementation evidence",
        ],
        "required_before_asic_ppa_claim": [
            "per-claimed-kernel golden correctness",
            "HLS C-sim or RTL sim",
            "HLS C-synth or RTL synth",
            "DC synthesis/timing/area evidence with a real target library",
        ],
        "claim_boundary": (
            "This is evaluated-hybrid cost accounting.  It is not FPGA/ASIC PPA "
            "closure and cannot satisfy hardware claim gates by itself."
        ),
    }
    return {
        "full_scf_accelerator_descriptor": descriptor,
        "full_scf_runtime_schedule": runtime_schedule,
        "full_scf_data_residency_plan": data_residency_plan,
        "full_scf_correctness_report": correctness_report,
        "full_scf_ppa_summary": ppa_summary,
    }


def write_full_scf_evaluated_hybrid_artifacts(
    out_dir: Path,
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    """Write the Wave-4 full-SCF evaluated-hybrid artifact bundle."""

    out_dir = Path(out_dir)
    bundle = build_full_scf_evaluated_hybrid_artifact_bundle(payload)
    artifact_paths = {
        "full_scf_accelerator_descriptor": "full_scf_accelerator_descriptor.json",
        "full_scf_runtime_schedule": "full_scf_runtime_schedule.json",
        "full_scf_data_residency_plan": "full_scf_data_residency_plan.json",
        "full_scf_correctness_report": "full_scf_correctness_report.json",
        "full_scf_ppa_summary": "full_scf_ppa_summary.json",
    }
    for key, rel_path in artifact_paths.items():
        _write_json(out_dir / rel_path, bundle[key])
    return {
        "schema_version": "dse.dft_scf.full_scf_evaluated_hybrid_artifact_bundle_status.v1",
        "status": "passed",
        "artifact_paths": artifact_paths,
        "completion_claim": False,
        "claim_boundary": (
            "Wave-4 full-SCF evaluated-hybrid artifacts were written.  This "
            "does not complete full-SCF device residency, numerical correctness, "
            "or FPGA/ASIC PPA closure."
        ),
    }


def build_full_scf_evaluated_hybrid_payload(
    *,
    candidate_id: str,
    campaign_id: str,
    workload_run_id: str,
    trial_id: str,
    accelerated_kernel_costs_s: Mapping[str, Any],
    host_bound_costs_s: Mapping[str, Any],
    overhead_costs_s: Mapping[str, Any],
    baseline_scf_time_s: float | None = None,
    descriptor_id: str | None = None,
    evidence_refs: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """Build a fail-closed full-SCF evaluated-hybrid descriptor/cost payload.

    Required cost mappings must include all eight allowed accelerated kernels,
    all required host-bound phases, and transfer/synchronization/queueing/layout
    overheads.  Missing required rows raise ``DftFullScfHybridValidationError``.
    """

    accelerated_costs = _require_costs(
        accelerated_kernel_costs_s,
        MAJOR_SCF_ACCELERATED_KERNEL_IDS,
        field_name="accelerated_kernel_costs_s",
    )
    host_costs = _require_costs(
        host_bound_costs_s,
        REQUIRED_HOST_BOUND_PHASE_IDS,
        field_name="host_bound_costs_s",
    )
    overhead_costs = _require_costs(
        overhead_costs_s,
        REQUIRED_OVERHEAD_PHASE_IDS,
        field_name="overhead_costs_s",
    )

    unexpected_accelerated = sorted(set(accelerated_kernel_costs_s) - set(MAJOR_SCF_ACCELERATED_KERNEL_IDS))
    if unexpected_accelerated:
        raise DftFullScfHybridValidationError(
            "accelerated_kernel_costs_s contains unsupported acceleration ids: "
            + ", ".join(unexpected_accelerated)
        )

    schedule: list[Dict[str, Any]] = []
    for kernel_id in MAJOR_SCF_ACCELERATED_KERNEL_IDS:
        schedule.append(
            {
                "piece_id": f"accelerated.{kernel_id}",
                "category": "accelerated_kernel",
                "kernel_id": kernel_id,
                "execution_target": "hardware_candidate",
                "cost_s": accelerated_costs[kernel_id],
                "hardware_acceleration_claim": True,
                "claim_boundary": (
                    "Acceleration is allowed only for this major SCF kernel and still requires "
                    "separate claim-specific evidence gates."
                ),
            }
        )
    for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS:
        schedule.append(
            {
                "piece_id": f"host.{phase_id}",
                "category": "host_bound_phase",
                "phase_id": phase_id,
                "execution_target": "host_cpu",
                "cost_s": host_costs[phase_id],
                "hardware_acceleration_claim": False,
                "claim_boundary": "Host-bound SCF work is counted in full-SCF cost and is not acceleration benefit.",
            }
        )
    for overhead_id in REQUIRED_OVERHEAD_PHASE_IDS:
        schedule.append(
            {
                "piece_id": f"overhead.{overhead_id}",
                "category": "runtime_overhead",
                "overhead_id": overhead_id,
                "execution_target": "host_runtime_or_interconnect",
                "cost_s": overhead_costs[overhead_id],
                "hardware_acceleration_claim": False,
                "claim_boundary": "Runtime overhead is counted in end-to-end SCF cost and is not acceleration benefit.",
            }
        )

    accelerated_total = sum(accelerated_costs.values())
    host_total = sum(host_costs.values())
    overhead_total = sum(overhead_costs.values())
    evaluated_total = accelerated_total + host_total + overhead_total
    cost_model: Dict[str, Any] = {
        "accelerated_kernel_cost_s": accelerated_total,
        "host_bound_cost_s": host_total,
        "runtime_overhead_cost_s": overhead_total,
        "evaluated_hybrid_scf_time_s": evaluated_total,
        "host_bound_phase_costs_s": dict(host_costs),
        "accelerated_kernel_costs_s": dict(accelerated_costs),
        "runtime_overhead_costs_s": dict(overhead_costs),
    }
    if baseline_scf_time_s is not None:
        baseline = _finite_nonnegative(baseline_scf_time_s, field_name="baseline_scf_time_s")
        if baseline == 0.0:
            raise DftFullScfHybridValidationError("baseline_scf_time_s must be positive when provided")
        if evaluated_total == 0.0:
            raise DftFullScfHybridValidationError("evaluated_hybrid_scf_time_s must be positive when baseline is provided")
        cost_model["baseline_scf_time_s"] = baseline
        cost_model["end_to_end_scf_evaluated_speedup"] = baseline / evaluated_total

    payload = {
        "schema_version": DFT_FULL_SCF_HYBRID_DESCRIPTOR_SCHEMA,
        "descriptor_id": descriptor_id or f"full-scf-hybrid:{candidate_id}:{trial_id}",
        "candidate_id": candidate_id,
        "campaign_id": campaign_id,
        "workload_run_id": workload_run_id,
        "trial_id": trial_id,
        "prototype_boundary": "full_scf_evaluated_hybrid",
        "device_residency": "host_orchestrated_hybrid",
        "completion_claim": False,
        "hardware_acceleration_claim_scope": list(MAJOR_SCF_ACCELERATED_KERNEL_IDS),
        "host_bound_phase_scope": list(REQUIRED_HOST_BOUND_PHASE_IDS),
        "runtime_overhead_scope": list(REQUIRED_OVERHEAD_PHASE_IDS),
        "schedule": schedule,
        "cost_model": cost_model,
        "evidence_refs": [dict(ref) for ref in evidence_refs],
        "claim_boundary": (
            "First prototype full-SCF evaluated hybrid: host-bound phases and runtime overheads "
            "are explicit end-to-end costs, and only the eight major kernels may carry "
            "hardware-acceleration claims."
        ),
    }
    validation = validate_full_scf_evaluated_hybrid_payload(payload)
    if not validation["passed"]:
        raise DftFullScfHybridValidationError(
            "full-SCF evaluated hybrid payload blocked: " + ", ".join(validation["blocker_ids"])
        )
    payload["validation"] = validation
    return payload
