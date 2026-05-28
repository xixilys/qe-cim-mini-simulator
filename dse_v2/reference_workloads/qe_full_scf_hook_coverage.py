#!/usr/bin/env python3
"""Audit QE call-site hook coverage against strict DFT full-SCF kernel gates.

The patched-QE text trace proves that QE reached named call sites while running
the SCF mainflow.  It does *not* prove accelerated values were consumed by QE,
nor does it provide trusted runtime costs.  This module keeps that distinction
machine-readable by mapping observed call sites to the full-SCF major-kernel
gate contract and reporting the exact hook/replacement gaps that still block
strict full-SCF numerical closure.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.reference_workloads.dft_full_scf_accounting import (
    FULL_SCF_RUNTIME_TRACE_SCHEMAS,
    TRUSTED_RUNTIME_TRACE_SOURCES,
)
from dse_v2.reference_workloads.dft_full_scf_hybrid import REQUIRED_HOST_BOUND_PHASE_IDS


QE_FULL_SCF_HOOK_COVERAGE_AUDIT_SCHEMA = "dse.qe.full_scf_hook_coverage_audit.v1"

# Direct call-site names currently emitted by the QE patch.  A direct hit still
# remains diagnostic unless the runtime emits replacement/consumption evidence.
DIRECT_MAJOR_KERNEL_HOOKS: Mapping[str, tuple[str, ...]] = {
    "fft_ifft_ffft": ("fft", "ifft", "ffft", "fft3d", "fft_3d"),
    "transpose_layout_conversion": (
        "transpose_layout_conversion",
        "layout_conversion",
        "fft_transpose",
        "transpose",
    ),
    "dma_hbm_movement_engine": (
        "dma_hbm_movement_engine",
        "hbm_dma",
        "host_device_dma",
        "dma",
    ),
}

# Composite call sites reach a higher-level QE routine that contains one or more
# major kernel concepts.  These are useful for patch placement, but final gates
# still require per-major-kernel replacement evidence.
COMPOSITE_MAJOR_KERNEL_HOOKS: Mapping[str, tuple[str, ...]] = {
    "hpsi_local_potential": ("h_psi", "hpsi"),
    "kinetic_add": ("h_psi", "hpsi"),
    "nonlocal_projector": ("h_psi", "hpsi", "s_psi", "spsi"),
    "complex_gemm_gemv_tile": ("diagonalization", "s_psi", "spsi"),
    "reduction_dot_tree": ("rho_out", "mix_rho", "diagonalization"),
}

MISSING_DIRECT_HOOK_KERNELS = {
    "transpose_layout_conversion",
    "dma_hbm_movement_engine",
}

RUNTIME_PRIMARY_OBSERVATION_KERNELS = {
    "dma_hbm_movement_engine",
}

HOST_BOUND_CALLSITE_HINTS: Mapping[str, tuple[str, ...]] = {
    "scf_control": ("scf",),
    "convergence": ("rho_out",),
    "diagonalization": ("diagonalization",),
    "mixing": ("mix_rho",),
}

FORBIDDEN_CLOSURE_SHORTCUTS = (
    "qe_callsite_trace_diagnostic_only",
    "callsite_coverage_only",
    "proxy_runtime_smoke_only",
    "proxy_runtime_only",
    "timing_only",
    "baseline_copy",
)

RUNTIME_HOOK_CONTRACT_FORBIDDEN_FLAGS = (
    "fixture",
    "baseline_copy",
    "timing_only",
    "synthetic",
    "model_estimate",
    "component_model_reference_replay_only",
    "software_component_model_not_l4",
    "host_stage_reference_assisted",
    "single_hpsi_call_smoke_only",
    "proxy_runtime_smoke_only",
    "proxy_runtime_only",
    "qe_callsite_gated_proxy_only",
    "qe_callsite_trace_diagnostic_only",
    "boundary_norm_probe_only",
)

REQUIRED_STRICT_REPLACEMENT_FIELDS: Mapping[str, Any] = {
    "software_fallback_on_critical_path": False,
    "qe_software_kernel_execution_skipped": True,
    "qe_kernel_work_replaced_on_critical_path": True,
    "accelerated_result_materialized_in_qe_memory": True,
    "accelerated_output_written_to_qe_buffer": True,
    "qe_consumed_accelerator_output_buffer": True,
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ref(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False}
    payload: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if path.exists():
        payload.update({"hash_algorithm": "sha256", "hash": _sha256_file(path)})
    return payload


def _load_json_artifact(path: Path | None) -> tuple[Any | None, list[str]]:
    if path is None:
        return None, ["path_not_configured"]
    if not path.exists():
        return None, [f"path_missing:{path}"]
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except Exception as exc:  # pragma: no cover - defensive artifact preservation
        return None, [f"json_unreadable:{type(exc).__name__}:{exc}"]


def _kernel_evidence_rows(payload: Any) -> list[Mapping[str, Any]]:
    rows = payload.get("kernel_evidence", payload) if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, Mapping)]


def _kernel_id_from_row(row: Mapping[str, Any]) -> str:
    # Strict full-SCF closure uses exact major-kernel IDs.  Legacy QE routine
    # names such as "h_psi" remain useful call-site diagnostics, but must not be
    # silently upgraded into Hψ/local/kinetic/nonlocal major-kernel evidence.
    return str(
        row.get("major_kernel_id")
        or row.get("kernel_id")
        or row.get("target_kernel")
        or row.get("kernel")
        or ""
    ).strip()


def _proof_passed(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("passed") is True:
        return True
    for key in (
        "runtime_execution_proof",
        "l4_execution_proof",
        "hardware_counter_proof",
        "tool_execution_proof",
    ):
        proof = payload.get(key)
        if isinstance(proof, Mapping) and proof.get("passed") is True:
            return True
    return False


def _global_provenance_blockers(provenance: Any, proof_payload: Any) -> list[str]:
    blockers: list[str] = []
    if not isinstance(provenance, Mapping):
        return ["offload_provenance_missing_or_unreadable"]
    if provenance.get("qe_mainflow_integrated") is not True:
        blockers.append("offload_provenance_qe_mainflow_integrated_not_true")
    if provenance.get("accelerated_results_consumed_by_qe") is not True:
        blockers.append("offload_provenance_accelerated_results_consumed_by_qe_not_true")
    for key, expected in REQUIRED_STRICT_REPLACEMENT_FIELDS.items():
        if provenance.get(key) is not expected:
            blockers.append(f"offload_provenance_{key}_not_{str(expected).lower()}")
    for key in RUNTIME_HOOK_CONTRACT_FORBIDDEN_FLAGS:
        if provenance.get(key) is True:
            blockers.append(f"offload_provenance_{key}_forbidden")
    if not (_proof_passed(provenance) or _proof_passed(proof_payload)):
        blockers.append("offload_provenance_missing_passed_runtime_or_l4_proof")
    return blockers


def _kernel_replacement_blockers(row: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if row.get("full_kernel_recomputed") is not True:
        blockers.append("full_kernel_recomputed_not_true")
    if row.get("qe_mainflow_integrated") is not True:
        blockers.append("qe_mainflow_integrated_not_true")
    if row.get("accelerated_results_consumed_by_qe") is not True:
        blockers.append("accelerated_results_consumed_by_qe_not_true")
    for key, expected in REQUIRED_STRICT_REPLACEMENT_FIELDS.items():
        if row.get(key) is not expected:
            blockers.append(f"{key}_not_{str(expected).lower()}")
    for metric in ("absolute_error", "relative_error"):
        if row.get(metric) is None:
            blockers.append(f"{metric}_missing")
    for key in RUNTIME_HOOK_CONTRACT_FORBIDDEN_FLAGS:
        if row.get(key) is True:
            blockers.append(f"{key}_forbidden")
    return blockers


def _trace_events(trace: Any) -> list[Mapping[str, Any]]:
    if not isinstance(trace, Mapping):
        return []
    for key in ("events", "runtime_events", "schedule", "schedule_events"):
        value = trace.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _runtime_trace_trust_blockers(trace: Any, proof_payload: Any) -> list[str]:
    if not isinstance(trace, Mapping):
        return ["runtime_trace_missing_or_unreadable"]
    blockers: list[str] = []
    if trace.get("schema_version") not in FULL_SCF_RUNTIME_TRACE_SCHEMAS:
        blockers.append("runtime_trace_schema_mismatch")
    if trace.get("trusted_runtime_trace") is not True and trace.get("trusted_runtime_execution") is not True:
        blockers.append("runtime_trace_not_marked_trusted")
    if trace.get("runtime_trace_source") not in TRUSTED_RUNTIME_TRACE_SOURCES and trace.get("source_kind") not in TRUSTED_RUNTIME_TRACE_SOURCES:
        source = trace.get("runtime_trace_source") or trace.get("source_kind") or "missing"
        blockers.append(f"runtime_trace_untrusted_source:{source}")
    if trace.get("comparison_scope") != "full_scf_host_accelerator_end_to_end":
        blockers.append("runtime_trace_scope_not_full_scf_host_accelerator_end_to_end")
    if not (_proof_passed(trace) or _proof_passed(proof_payload)):
        blockers.append("runtime_trace_missing_passed_execution_proof")
    for key in RUNTIME_HOOK_CONTRACT_FORBIDDEN_FLAGS:
        if trace.get(key) is True:
            blockers.append(f"runtime_trace_{key}_forbidden")
    return blockers


def _event_cost_present(event: Mapping[str, Any]) -> bool:
    for field_name in ("duration_s", "cost_s", "elapsed_s", "elapsed_seconds", "wall_time_s"):
        if event.get(field_name) is None:
            continue
        try:
            return float(event[field_name]) >= 0.0
        except (TypeError, ValueError):
            return False
    return False


def _runtime_event_records(trace: Any, kernel_id: str) -> list[Mapping[str, Any]]:
    return [
        event
        for event in _trace_events(trace)
        if str(event.get("category") or "").strip() == "accelerated_kernel"
        and str(event.get("kernel_id") or event.get("id") or "").strip() == kernel_id
    ]


def _runtime_event_blockers(events: Sequence[Mapping[str, Any]]) -> list[str]:
    if not events:
        return ["runtime_event_missing_for_kernel"]
    blockers: list[str] = []
    if not any(_event_cost_present(event) for event in events):
        blockers.append("runtime_event_missing_measured_cost")
    for index, event in enumerate(events):
        source = str(
            event.get("measurement_source")
            or event.get("source_kind")
            or event.get("source")
            or ""
        ).strip()
        if source not in TRUSTED_RUNTIME_TRACE_SOURCES:
            blockers.append(f"runtime_event_{index}_untrusted_source:{source or 'missing'}")
        for key in RUNTIME_HOOK_CONTRACT_FORBIDDEN_FLAGS:
            if event.get(key) is True:
                blockers.append(f"runtime_event_{index}_{key}_forbidden")
    return sorted(dict.fromkeys(blockers))


def parse_qe_offload_callsite_trace(path: Path) -> tuple[Counter[str], list[str]]:
    """Parse ``QE_OFFLOAD_CALLSITE`` text trace rows into call-site counts."""
    counts: Counter[str] = Counter()
    sample: list[str] = []
    if not path.exists():
        return counts, sample
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text:
            continue
        parts = text.split()
        if len(parts) >= 2 and parts[0] == "QE_OFFLOAD_CALLSITE":
            callsite = parts[1]
            counts[callsite] += 1
            if len(sample) < 20:
                sample.append(text)
    return counts, sample


def _observed_hooks(counts: Mapping[str, int], hooks: Iterable[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for hook in hooks:
        count = int(counts.get(hook, 0))
        if count > 0:
            records.append({"callsite": hook, "count": count})
    return records


def build_qe_full_scf_hook_coverage_audit(
    *,
    callsite_trace_path: Path | None = None,
    callsite_counts: Mapping[str, int] | None = None,
    kernel_evidence_path: Path | None = None,
    offload_provenance_path: Path | None = None,
    runtime_trace_path: Path | None = None,
    runtime_execution_proof_path: Path | None = None,
    candidate_id: str | None = None,
    workload_case_id: str | None = None,
) -> dict[str, Any]:
    """Build a fail-closed hook coverage audit payload."""
    counts = Counter({str(k): int(v) for k, v in (callsite_counts or {}).items()})
    sample: list[str] = []
    if callsite_trace_path is not None:
        parsed_counts, sample = parse_qe_offload_callsite_trace(callsite_trace_path)
        if not callsite_counts:
            counts = parsed_counts

    kernel_evidence_payload, kernel_evidence_artifact_blockers = _load_json_artifact(kernel_evidence_path)
    offload_provenance_payload, offload_provenance_artifact_blockers = _load_json_artifact(offload_provenance_path)
    runtime_trace_payload, runtime_trace_artifact_blockers = _load_json_artifact(runtime_trace_path)
    runtime_execution_proof_payload, runtime_proof_artifact_blockers = _load_json_artifact(runtime_execution_proof_path)
    kernel_rows = _kernel_evidence_rows(kernel_evidence_payload)
    provenance_blockers = _global_provenance_blockers(
        offload_provenance_payload,
        runtime_execution_proof_payload,
    )
    runtime_trace_blockers = _runtime_trace_trust_blockers(
        runtime_trace_payload,
        runtime_execution_proof_payload,
    )

    kernel_records: list[dict[str, Any]] = []
    blockers: list[str] = []
    for kernel_id in MAJOR_SCF_KERNEL_IDS:
        direct_hooks = DIRECT_MAJOR_KERNEL_HOOKS.get(kernel_id, ())
        composite_hooks = COMPOSITE_MAJOR_KERNEL_HOOKS.get(kernel_id, ())
        direct_observed = _observed_hooks(counts, direct_hooks)
        composite_observed = _observed_hooks(counts, composite_hooks)
        if direct_observed:
            status = "observed_diagnostic_only"
            blockers.append(f"kernel_hook_observed_without_replacement_evidence::{kernel_id}")
        elif composite_observed:
            status = "observed_composite_diagnostic_only"
            blockers.append(f"kernel_hook_composite_only::{kernel_id}")
        else:
            status = "missing_hook_observation"
            blockers.append(f"kernel_hook_missing::{kernel_id}")
        matching_kernel_rows = [
            row for row in kernel_rows if _kernel_id_from_row(row) == kernel_id
        ]
        trusted_kernel_rows = [
            row for row in matching_kernel_rows if not _kernel_replacement_blockers(row)
        ]
        runtime_events = _runtime_event_records(runtime_trace_payload, kernel_id)
        runtime_event_blockers = _runtime_event_blockers(runtime_events)
        if kernel_id in MISSING_DIRECT_HOOK_KERNELS and not direct_observed:
            if kernel_id in RUNTIME_PRIMARY_OBSERVATION_KERNELS:
                if not runtime_events:
                    blockers.append(f"kernel_runtime_movement_hook_missing::{kernel_id}")
            else:
                blockers.append(f"kernel_direct_qe_hook_missing::{kernel_id}")
        runtime_hook_contract_blockers = sorted(
            dict.fromkeys(
                [
                    *([] if trusted_kernel_rows else [f"kernel_replacement_evidence_missing_or_untrusted::{kernel_id}"]),
                    *[f"kernel_replacement_evidence::{kernel_id}::{item}" for row in matching_kernel_rows for item in _kernel_replacement_blockers(row)],
                    *[f"offload_provenance::{kernel_id}::{item}" for item in provenance_blockers],
                    *[f"runtime_trace::{kernel_id}::{item}" for item in runtime_trace_blockers],
                    *[f"runtime_event::{kernel_id}::{item}" for item in runtime_event_blockers],
                ]
            )
        )
        if runtime_hook_contract_blockers:
            blockers.extend(runtime_hook_contract_blockers)
        kernel_records.append(
            {
                "kernel_id": kernel_id,
                "status": status,
                "required_observation_surface": (
                    "runtime_movement_event"
                    if kernel_id in RUNTIME_PRIMARY_OBSERVATION_KERNELS
                    else "qe_callsite_or_runtime_replacement_event"
                ),
                "direct_hook_names": list(direct_hooks),
                "composite_hook_names": list(composite_hooks),
                "observed_direct_hooks": direct_observed,
                "observed_composite_hooks": composite_observed,
                "kernel_evidence_rows": len(matching_kernel_rows),
                "trusted_replacement_evidence_present": bool(trusted_kernel_rows),
                "accelerated_results_consumed_by_qe": any(
                    row.get("accelerated_results_consumed_by_qe") is True
                    for row in trusted_kernel_rows
                ),
                "runtime_event_count": len(runtime_events),
                "trusted_runtime_cost_event_present": bool(runtime_events) and not runtime_trace_blockers and not runtime_event_blockers,
                "runtime_hook_contract_passed": not runtime_hook_contract_blockers,
                "runtime_hook_contract_blockers": runtime_hook_contract_blockers,
                "claim_boundary": (
                    "QE call-site observation only; strict closure still requires "
                    "runtime-emitted full-kernel evidence and QE consumption proof."
                ),
            }
        )

    host_records: list[dict[str, Any]] = []
    for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS:
        hints = HOST_BOUND_CALLSITE_HINTS.get(phase_id, ())
        observed = _observed_hooks(counts, hints)
        host_records.append(
            {
                "phase_id": phase_id,
                "status": "observed_diagnostic_only" if observed else "missing_or_not_hooked",
                "callsite_hints": list(hints),
                "observed_hooks": observed,
                "host_bound_cost_evidence_present": False,
            }
        )

    passed = False
    return {
        "schema_version": QE_FULL_SCF_HOOK_COVERAGE_AUDIT_SCHEMA,
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "status": "blocked_temporary",
        "passed": passed,
        "callsite_trace": _artifact_ref(callsite_trace_path),
        "kernel_evidence": _artifact_ref(kernel_evidence_path),
        "offload_provenance": _artifact_ref(offload_provenance_path),
        "runtime_trace": _artifact_ref(runtime_trace_path),
        "runtime_execution_proof": _artifact_ref(runtime_execution_proof_path),
        "artifact_read_blockers": sorted(
            dict.fromkeys(
                [
                    *[f"kernel_evidence::{item}" for item in kernel_evidence_artifact_blockers],
                    *[f"offload_provenance::{item}" for item in offload_provenance_artifact_blockers],
                    *[f"runtime_trace::{item}" for item in runtime_trace_artifact_blockers],
                    *[f"runtime_execution_proof::{item}" for item in runtime_proof_artifact_blockers],
                ]
            )
        ),
        "callsite_counts": dict(sorted(counts.items())),
        "sample": sample,
        "major_kernel_records": kernel_records,
        "host_bound_phase_records": host_records,
        "covered_major_kernel_count_diagnostic": sum(
            1 for record in kernel_records if record["status"] != "missing_hook_observation"
        ),
        "required_major_kernel_count": len(MAJOR_SCF_KERNEL_IDS),
        "trusted_runtime_cost_event_count": sum(
            1 for record in kernel_records if record["trusted_runtime_cost_event_present"]
        ),
        "runtime_hook_contract_passed_count": sum(
            1 for record in kernel_records if record["runtime_hook_contract_passed"]
        ),
        "trusted_replacement_evidence_count": sum(
            1 for record in kernel_records if record["trusted_replacement_evidence_present"]
        ),
        "accelerated_results_consumed_by_qe_count": sum(
            1 for record in kernel_records if record["accelerated_results_consumed_by_qe"]
        ),
        "forbidden_closure_shortcuts": list(FORBIDDEN_CLOSURE_SHORTCUTS),
        "blockers": sorted(
            dict.fromkeys(
                [
                    *blockers,
                    *[f"kernel_evidence::{item}" for item in kernel_evidence_artifact_blockers],
                    *[f"offload_provenance::{item}" for item in offload_provenance_artifact_blockers],
                    *[f"runtime_trace::{item}" for item in runtime_trace_artifact_blockers],
                    *[f"runtime_execution_proof::{item}" for item in runtime_proof_artifact_blockers],
                ]
            )
        ),
        "required_next_evidence": (
            "Replace diagnostic QE callsite observations with per-major-kernel runtime "
            "hooks that emit trusted kernel_evidence.json, offload_provenance.json, "
            "measured full_scf_runtime_events.jsonl, and proof that accelerated results "
            "were consumed by QE."
        ),
        "claim_boundary": (
            "Hook coverage audit only. It cannot satisfy full-SCF row accounting, "
            "numerical comparison, FPGA/ASIC PPA gates, or deliverable-complete claims."
        ),
    }


def write_qe_full_scf_hook_coverage_audit(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


__all__ = [
    "QE_FULL_SCF_HOOK_COVERAGE_AUDIT_SCHEMA",
    "build_qe_full_scf_hook_coverage_audit",
    "parse_qe_offload_callsite_trace",
    "write_qe_full_scf_hook_coverage_audit",
]
