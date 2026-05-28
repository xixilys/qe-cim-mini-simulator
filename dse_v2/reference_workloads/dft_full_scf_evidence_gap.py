#!/usr/bin/env python3
"""Machine-readable strict full-SCF evidence gap contract.

This module records *why* a DFT/QE accelerated row is still blocked without
turning diagnostics into evidence.  The contract is DFT-profile local: it names
the required QE/offload runtime artifacts, major SCF kernels, host-bound phases,
runtime overheads, physical metrics, and forbidden downgrade markers for a
candidate × workload row.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
)


STRICT_FULL_SCF_EVIDENCE_GAP_SCHEMA = "dse.dft.numerical.strict_full_scf_evidence_gap.v1"

REQUIRED_FULL_SCF_PHYSICAL_METRICS = (
    "total_energy_error_ry",
    "density_residual",
    "eigenvalue_summary_error_ry",
)

STRICT_FULL_SCF_FORBIDDEN_SHORTCUTS = (
    "fixture",
    "baseline_copy",
    "timing_only",
    "synthetic",
    "model_estimate",
    "component_model_reference_replay_only",
    "software_component_model_not_l4",
    "single_hpsi_call_smoke_only",
    "proxy_runtime_smoke_only",
    "proxy_runtime_only",
    "qe_callsite_gated_proxy_only",
    "qe_callsite_trace_diagnostic_only",
)


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


def _existing_required_artifacts(artifacts: Mapping[str, Path | None]) -> list[str]:
    return [
        name
        for name, path in artifacts.items()
        if path is not None and Path(path).exists()
    ]


def _missing_required_artifacts(artifacts: Mapping[str, Path | None]) -> list[str]:
    return [
        name
        for name, path in artifacts.items()
        if path is None or not Path(path).exists()
    ]


def build_strict_full_scf_evidence_gap_payload(
    *,
    candidate_id: str,
    workload_case_id: str,
    artifacts: Mapping[str, Path | None],
    blockers: Sequence[str],
    trusted_accelerated_numeric_source: bool,
    callsite_trace_summary: Mapping[str, Any] | None = None,
    runtime_trace_materialization: Mapping[str, Any] | None = None,
    runtime_trace_postprocess: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a fail-closed row-local evidence-gap payload.

    ``blockers`` are passed through from the producer/evidence validators.  The
    resulting artifact is diagnostic only; it is intentionally not accepted by
    strict row materializers as a replacement for runtime trace/accounting.
    """

    blocker_list = sorted(dict.fromkeys(str(item) for item in blockers))
    missing_artifacts = _missing_required_artifacts(artifacts)
    passed = trusted_accelerated_numeric_source and not blocker_list and not missing_artifacts
    return {
        "schema_version": STRICT_FULL_SCF_EVIDENCE_GAP_SCHEMA,
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "status": "passed" if passed else "blocked_temporary",
        "passed": passed,
        "trusted_accelerated_numeric_source": trusted_accelerated_numeric_source,
        "missing_required_artifact_labels": missing_artifacts,
        "existing_required_artifact_labels": _existing_required_artifacts(artifacts),
        "required_artifacts": {
            name: _artifact_ref(path)
            for name, path in sorted(artifacts.items())
        },
        "required_runtime_event_categories": {
            "accelerated_kernel": {
                "id_field": "kernel_id",
                "required_ids": list(MAJOR_SCF_KERNEL_IDS),
                "required_semantics": (
                    "measured accelerated costs for all claimed major SCF kernels; "
                    "events must carry candidate/workload identity and trusted source"
                ),
            },
            "host_bound_phase": {
                "id_field": "phase_id",
                "required_ids": list(REQUIRED_HOST_BOUND_PHASE_IDS),
                "required_semantics": (
                    "host-bound I/O, SCF control, convergence, diagonalization, and mixing "
                    "costs included in the full-SCF end-to-end row"
                ),
            },
            "runtime_overhead": {
                "id_field": "overhead_id",
                "required_ids": list(REQUIRED_OVERHEAD_PHASE_IDS),
                "required_semantics": (
                    "host/device transfer, synchronization, queueing, and layout overhead "
                    "costs included in the full-SCF row"
                ),
            },
        },
        "required_qe_numeric_outputs": {
            "physical_metrics": list(REQUIRED_FULL_SCF_PHYSICAL_METRICS),
            "kernel_evidence": (
                "kernel_evidence.json must contain full-kernel recomputation rows for every "
                "major SCF kernel claimed accelerated, with accelerated_results_consumed_by_qe"
            ),
            "offload_provenance": (
                "offload_provenance.json must show QE mainflow integration, accelerated results "
                "consumed by QE, and a passed L4/runtime execution proof"
            ),
        },
        "forbidden_shortcuts": list(STRICT_FULL_SCF_FORBIDDEN_SHORTCUTS),
        "callsite_trace_summary": dict(callsite_trace_summary or {}),
        "runtime_trace_postprocess": dict(runtime_trace_postprocess or {}),
        "runtime_trace_materialization": dict(runtime_trace_materialization or {}),
        "blockers": blocker_list,
        "required_next_evidence": (
            "Instrumented QE/offload runtime must emit trusted kernel_evidence.json, "
            "offload_provenance.json, full_scf_runtime_events.jsonl plus passed "
            "runtime_execution_proof.json, or a passed full_scf_row_accounting.json; "
            "callsite/proxy/timing diagnostics remain blocked."
            if not passed
            else "none"
        ),
        "claim_boundary": (
            "Diagnostic gap contract only. This artifact cannot satisfy strict full-SCF "
            "row accounting or numerical comparison by itself; it records the exact "
            "runtime/numeric evidence still required without downgrading to smoke, "
            "proxy, timing-model, or callsite-only evidence."
        ),
    }


def write_strict_full_scf_evidence_gap_payload(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


__all__ = [
    "REQUIRED_FULL_SCF_PHYSICAL_METRICS",
    "STRICT_FULL_SCF_EVIDENCE_GAP_SCHEMA",
    "STRICT_FULL_SCF_FORBIDDEN_SHORTCUTS",
    "build_strict_full_scf_evidence_gap_payload",
    "write_strict_full_scf_evidence_gap_payload",
]
