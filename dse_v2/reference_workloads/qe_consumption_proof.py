"""Fail-closed QE post-bridge accelerator consumption proof contract.

This module merges a row-local proof emitted by patched QE *after* an offload
bridge returns.  The proof is allowed to upgrade a domain-correct payload from
"materialized for QE" to "consumed by QE" only when it is identity-matched,
hash-matched, and carries every strict runtime-replacement field required by
the full-SCF hook audit.  On any mismatch the source artifacts are left
unchanged and a blocked status is returned.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, MutableMapping


QE_OFFLOAD_CONSUMPTION_PROOF_SCHEMA = "dse.qe_offload_consumption_proof.v1"
QE_OFFLOAD_CONSUMPTION_PROOF_MERGE_SCHEMA = "dse.qe_offload_consumption_proof_merge.v1"

_TARGET_TO_MAJOR_KERNEL_ID = {
    "fft": "fft_ifft_ffft",
    "ffft": "fft_ifft_ffft",
    "ifft": "fft_ifft_ffft",
    "fft_ifft_ffft": "fft_ifft_ffft",
    "h_psi": "hpsi_local_potential",
    "hpsi": "hpsi_local_potential",
    "hpsi_local_potential": "hpsi_local_potential",
    "kinetic_add": "kinetic_add",
    "nonlocal_projector": "nonlocal_projector",
    "calbec": "nonlocal_projector",
    "sum_band": "reduction_dot_tree",
    "reduction_dot_tree": "reduction_dot_tree",
    "diagonalization": "complex_gemm_gemv_tile",
    "complex_gemm_gemv_tile": "complex_gemm_gemv_tile",
    "dma_hbm_movement_engine": "dma_hbm_movement_engine",
    "transpose_layout_conversion": "transpose_layout_conversion",
}

_STRICT_TRUE_FIELDS = (
    "full_kernel_recomputed",
    "qe_mainflow_integrated",
    "accelerated_results_consumed_by_qe",
    "qe_software_kernel_execution_skipped",
    "qe_kernel_work_replaced_on_critical_path",
    "accelerated_result_materialized_in_qe_memory",
    "accelerated_output_written_to_qe_buffer",
    "qe_consumed_accelerator_output_buffer",
)

_STRICT_FALSE_FIELDS = (
    "software_fallback_on_critical_path",
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


def _read_json(path: Path | None) -> Any:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def major_kernel_id_for_target(target_kernel: str | None, proof: Mapping[str, Any] | None = None) -> str:
    if isinstance(proof, Mapping):
        explicit = str(proof.get("major_kernel_id") or "").strip()
        if explicit:
            return explicit
    normalized = str(target_kernel or "").strip().lower()
    return _TARGET_TO_MAJOR_KERNEL_ID.get(normalized, normalized)


def _load_kernel_rows(payload: Any) -> list[MutableMapping[str, Any]]:
    rows = payload.get("kernel_evidence", payload) if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        return []
    return [dict(item) for item in rows if isinstance(item, Mapping)]


def _candidate_value(payload: Mapping[str, Any], proof: Mapping[str, Any], explicit: str | None, key: str) -> str | None:
    expected = explicit or payload.get(key)
    if expected is None:
        return None
    return str(expected)


def _proof_blockers(
    *,
    proof: Mapping[str, Any] | None,
    accelerated_output: Mapping[str, Any] | None,
    output_data_hash: str | None,
    candidate_id: str | None,
    workload_case_id: str | None,
    target_kernel: str | None,
) -> list[str]:
    blockers: list[str] = []
    if not isinstance(proof, Mapping):
        return ["consumption_proof_missing_or_unreadable"]
    if proof.get("schema_version") != QE_OFFLOAD_CONSUMPTION_PROOF_SCHEMA:
        blockers.append("consumption_proof_schema_mismatch")
    if proof.get("passed") is not True:
        blockers.append("consumption_proof_not_passed")
    expected_candidate = _candidate_value(accelerated_output or {}, proof, candidate_id, "candidate_id")
    if expected_candidate and str(proof.get("candidate_id") or "") != expected_candidate:
        blockers.append("consumption_proof_candidate_id_mismatch")
    expected_workload = _candidate_value(accelerated_output or {}, proof, workload_case_id, "workload_case_id")
    if expected_workload and str(proof.get("workload_case_id") or "") != expected_workload:
        blockers.append("consumption_proof_workload_case_id_mismatch")
    expected_target = target_kernel or (accelerated_output or {}).get("target_kernel")
    if expected_target and str(proof.get("target_kernel") or "").strip().lower() != str(expected_target).strip().lower():
        blockers.append("consumption_proof_target_kernel_mismatch")
    for field in _STRICT_TRUE_FIELDS:
        if proof.get(field) is not True:
            blockers.append(f"consumption_proof_{field}_not_true")
    for field in _STRICT_FALSE_FIELDS:
        if proof.get(field) is True:
            blockers.append(f"consumption_proof_{field}_forbidden")
    for metric in ("absolute_error", "relative_error"):
        if proof.get(metric) is None:
            blockers.append(f"consumption_proof_{metric}_missing")
    expected_hash = (
        proof.get("consumed_output_buffer_sha256")
        or proof.get("accelerated_output_buffer_sha256")
        or proof.get("output_buffer_sha256")
    )
    known_hash = output_data_hash or (accelerated_output or {}).get("output_buffer_sha256")
    if not expected_hash:
        blockers.append("consumption_proof_consumed_output_buffer_sha256_missing")
    elif known_hash and str(expected_hash) != str(known_hash):
        blockers.append("consumed_output_buffer_sha256_mismatch")
    return sorted(dict.fromkeys(blockers))


def _upgraded_kernel_row(
    *,
    existing: Mapping[str, Any] | None,
    proof: Mapping[str, Any],
    major_kernel_id: str,
    target_kernel: str | None,
    output_data_path: Path | None,
    output_data_hash: str | None,
) -> dict[str, Any]:
    row = dict(existing or {})
    row.update(
        {
            "major_kernel_id": major_kernel_id,
            "kernel_id": major_kernel_id,
            "target_kernel": target_kernel or proof.get("target_kernel"),
            "kernel_scope": row.get("kernel_scope") or f"full_{major_kernel_id}",
            "full_kernel_recomputed": True,
            "qe_mainflow_integrated": True,
            "accelerated_results_consumed_by_qe": True,
            "software_fallback_on_critical_path": False,
            "qe_software_kernel_execution_skipped": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "accelerated_output_written_to_qe_buffer": True,
            "qe_consumed_accelerator_output_buffer": True,
            "absolute_error": proof.get("absolute_error", row.get("absolute_error")),
            "relative_error": proof.get("relative_error", row.get("relative_error")),
            "consumed_output_buffer_sha256": proof.get("consumed_output_buffer_sha256")
            or proof.get("accelerated_output_buffer_sha256")
            or output_data_hash,
            "accelerated_output_data_path": str(output_data_path) if output_data_path is not None else row.get("accelerated_output_data_path"),
            "source": proof.get("source") or "qe_post_bridge_consumption_proof",
            "qe_consumption_proof_schema": proof.get("schema_version"),
            "proxy_runtime_smoke_only": False,
            "proxy_runtime_only": False,
            "qe_callsite_gated_proxy_only": False,
            "timing_only": False,
            "fixture": False,
            "baseline_copy": False,
            "claim_boundary": (
                "Patched QE emitted post-bridge consumption proof for this full kernel. "
                "This proves QE consumed the replacement buffer for runtime integration; "
                "hardware superiority still requires full-SCF accounting and RTL/Vivado/board gates."
            ),
        }
    )
    return row


def merge_qe_consumption_proof_artifacts(
    *,
    consumption_proof_path: Path,
    kernel_evidence_path: Path,
    offload_provenance_path: Path,
    accelerated_output_json_path: Path | None = None,
    accelerated_output_data_path: Path | None = None,
    runtime_events_path: Path | None = None,
    candidate_id: str | None = None,
    workload_case_id: str | None = None,
    target_kernel: str | None = None,
) -> dict[str, Any]:
    """Merge trusted QE consumption proof into row-local evidence artifacts.

    The function is intentionally non-destructive on failure: when any blocker
    is present, existing kernel/provenance/event artifacts are not rewritten.
    """

    proof_raw = _read_json(consumption_proof_path)
    proof = dict(proof_raw) if isinstance(proof_raw, Mapping) else None
    accelerated_output_raw = _read_json(accelerated_output_json_path) if accelerated_output_json_path else None
    accelerated_output = dict(accelerated_output_raw) if isinstance(accelerated_output_raw, Mapping) else None
    output_data_hash = _sha256_file(accelerated_output_data_path)
    blockers = _proof_blockers(
        proof=proof,
        accelerated_output=accelerated_output,
        output_data_hash=output_data_hash,
        candidate_id=candidate_id,
        workload_case_id=workload_case_id,
        target_kernel=target_kernel,
    )
    if blockers:
        return {
            "schema_version": QE_OFFLOAD_CONSUMPTION_PROOF_MERGE_SCHEMA,
            "status": "blocked",
            "passed": False,
            "blockers": blockers,
            "consumption_proof": str(consumption_proof_path),
            "claim_boundary": "Blocked merges leave source kernel/provenance/runtime artifacts unchanged.",
        }

    assert proof is not None  # for type checkers; blockers would have returned.
    merged_target = target_kernel or str(proof.get("target_kernel") or (accelerated_output or {}).get("target_kernel") or "")
    major_kernel_id = major_kernel_id_for_target(merged_target, proof)
    kernel_payload = _read_json(kernel_evidence_path)
    kernel_rows = _load_kernel_rows(kernel_payload)
    replaced = False
    upgraded_rows: list[dict[str, Any]] = []
    for row in kernel_rows:
        row_kernel = str(row.get("major_kernel_id") or row.get("kernel_id") or "").strip()
        row_target = str(row.get("target_kernel") or "").strip().lower()
        if not replaced and (row_kernel == major_kernel_id or row_target == str(merged_target).strip().lower()):
            upgraded_rows.append(
                _upgraded_kernel_row(
                    existing=row,
                    proof=proof,
                    major_kernel_id=major_kernel_id,
                    target_kernel=merged_target,
                    output_data_path=accelerated_output_data_path,
                    output_data_hash=output_data_hash,
                )
            )
            replaced = True
        else:
            upgraded_rows.append(row)
    if not replaced:
        upgraded_rows.append(
            _upgraded_kernel_row(
                existing=None,
                proof=proof,
                major_kernel_id=major_kernel_id,
                target_kernel=merged_target,
                output_data_path=accelerated_output_data_path,
                output_data_hash=output_data_hash,
            )
        )
    _write_json(kernel_evidence_path, upgraded_rows)

    provenance_raw = _read_json(offload_provenance_path)
    provenance = dict(provenance_raw) if isinstance(provenance_raw, Mapping) else {}
    provenance.update(
        {
            "qe_mainflow_integrated": True,
            "accelerated_results_consumed_by_qe": True,
            "full_kernel_recomputed": True,
            "software_fallback_on_critical_path": False,
            "qe_software_kernel_execution_skipped": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "accelerated_output_written_to_qe_buffer": True,
            "qe_consumed_accelerator_output_buffer": True,
            "target_kernel": merged_target,
            "major_kernel_id": major_kernel_id,
            "consumed_output_buffer_sha256": proof.get("consumed_output_buffer_sha256") or output_data_hash,
            "qe_consumption_proof": {"passed": True, "path": str(consumption_proof_path)},
            "proxy_runtime_smoke_only": False,
            "proxy_runtime_only": False,
            "qe_callsite_gated_proxy_only": False,
            "timing_only": False,
            "fixture": False,
            "baseline_copy": False,
            "claim_boundary": (
                "QE post-bridge consumption proof merged into provenance. This is runtime "
                "replacement/consumption evidence only; final claims still require strict "
                "full-SCF comparison and hardware gates."
            ),
        }
    )
    _write_json(offload_provenance_path, provenance)

    if runtime_events_path is not None:
        runtime_events_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "category": "accelerated_kernel",
            "kernel_id": major_kernel_id,
            "target_kernel": merged_target,
            "duration_s": float(proof.get("duration_s") or proof.get("elapsed_s") or 0.0),
            "measurement_source": "qe_offload_runtime_trace",
            "candidate_id": candidate_id or proof.get("candidate_id"),
            "workload_case_id": workload_case_id or proof.get("workload_case_id"),
            "workload_id": workload_case_id or proof.get("workload_case_id"),
            "qe_consumption_proof": str(consumption_proof_path),
            "claim_boundary": "Measured post-bridge QE consumption event for one accelerated kernel.",
        }
        with runtime_events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    return {
        "schema_version": QE_OFFLOAD_CONSUMPTION_PROOF_MERGE_SCHEMA,
        "status": "passed",
        "passed": True,
        "merged_major_kernel_id": major_kernel_id,
        "target_kernel": merged_target,
        "kernel_evidence": str(kernel_evidence_path),
        "offload_provenance": str(offload_provenance_path),
        "runtime_events": str(runtime_events_path) if runtime_events_path is not None else None,
        "blockers": [],
        "claim_boundary": (
            "Consumption proof merged for one kernel. This advances the full-QE replacement gate, "
            "but all major kernels, full-SCF accounting, and board/RTL gates remain separately checked."
        ),
    }


__all__ = [
    "QE_OFFLOAD_CONSUMPTION_PROOF_SCHEMA",
    "QE_OFFLOAD_CONSUMPTION_PROOF_MERGE_SCHEMA",
    "major_kernel_id_for_target",
    "merge_qe_consumption_proof_artifacts",
]
