#!/usr/bin/env python3
"""Fail-closed full-SCF evidence-gap probes for DFT/QE proof paths.

The hardware-side probe in this module records candidate/kernel
golden/RTL/Vivado/DC hard-gate progress only.  It deliberately does not emit
trusted runtime events, QE-consumed numeric rows, full-SCF seed eligibility, or
deliverable completion.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

KERNEL_HARDWARE_SIDE_EVIDENCE_PROGRESS_SCHEMA = (
    "dse.dft.kernel_hardware_side_evidence_progress.v1"
)
KERNEL_HARDWARE_SIDE_REQUIRED_STAGE_IDS = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_jsonish(path: Path) -> Iterable[tuple[str, Any]]:
    """Yield JSON payloads from a JSON or JSONL file, skipping unreadable rows."""

    if path.suffix == ".jsonl":
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                yield f"{path}:{line_no}", json.loads(line)
            except json.JSONDecodeError:
                continue
        return
    if path.suffix == ".json":
        try:
            yield str(path), json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _walk_mappings(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_mappings(item)


def _stage_identity_matches(
    row: Mapping[str, Any],
    *,
    candidate_id: str,
    workload_case_id: str,
    kernel_id: str,
) -> bool:
    row_workload_case_id = row.get("workload_case_id")
    if row_workload_case_id not in (None, "") and str(row_workload_case_id) != workload_case_id:
        return False
    return (
        str(row.get("candidate_id") or "") == candidate_id
        and str(row.get("kernel_id") or "") == kernel_id
        and str(row.get("stage_id") or "") in KERNEL_HARDWARE_SIDE_REQUIRED_STAGE_IDS
    )


def _stage_raw_ref_count(row: Mapping[str, Any]) -> int:
    refs = row.get("raw_evidence_refs")
    if not isinstance(refs, Sequence) or isinstance(refs, (str, bytes, bytearray)):
        return 0
    count = 0
    for ref in refs:
        if not isinstance(ref, Mapping):
            continue
        has_hash = bool(ref.get("sha256") or ref.get("hash"))
        if ref.get("path") and has_hash:
            count += 1
    return count


def _stage_blockers(row: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    for key in ("blocker_ids", "blockers"):
        values = row.get(key)
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            blockers.extend(str(item) for item in values if str(item))
    return sorted(dict.fromkeys(blockers))


def _stage_passed(row: Mapping[str, Any]) -> bool:
    verdict = str(row.get("verdict") or row.get("status") or "").strip().lower()
    if "passed" in row and row.get("passed") is not True:
        return False
    verdict_passed = row.get("passed") is True or verdict == "passed"
    return verdict_passed and not _stage_blockers(row) and _stage_raw_ref_count(row) > 0


def _is_hpsi_or_vloc_kernel(kernel_id: str) -> bool:
    kernel_text = str(kernel_id or "").lower().replace("ψ", "psi")
    normalized = "".join(ch for ch in kernel_text if ch.isalnum())
    return normalized == "hpsi" or (
        "psi" in normalized and ("vloc" in normalized or "localpotential" in normalized)
    )


def _hardware_stage_observation(locator: str, row: Mapping[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics")
    return {
        "locator": locator,
        "stage_id": str(row.get("stage_id") or ""),
        "candidate_id": row.get("candidate_id"),
        "kernel_id": row.get("kernel_id"),
        "verdict": row.get("verdict") or row.get("status"),
        "passed": _stage_passed(row),
        "parser_id": row.get("parser_id"),
        "blocker_ids": _stage_blockers(row),
        "raw_evidence_ref_count": _stage_raw_ref_count(row),
        "metrics": dict(metrics) if isinstance(metrics, Mapping) else {},
    }


def _best_hardware_stage_observation(
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not observations:
        return None
    for observation in observations:
        if observation.get("passed") is True:
            return dict(observation)
    return dict(observations[0])


def _kernel_hardware_next_command_or_fix(kernel_id: str) -> str:
    if _is_hpsi_or_vloc_kernel(kernel_id):
        producer_surface = "h_psi/vloc_psi"
        path_guidance = (
            "h_psi/vloc_psi path, including the vloc_psi_k_acc boundary-array "
            "producer surface,"
        )
        producer_command = (
            "then rerun dse_v2/scripts/dse/run_qe_accelerated_numeric_producer.py "
            "--enable-hpsi-component-sidecar for the candidate/workload, or an "
            "equivalent non-reference-assisted h_psi/vloc_psi producer, and replay "
            "build_dft_full_scf_numerical_rows.py --fail-on-blocked."
        )
    else:
        producer_surface = "selected-kernel"
        path_guidance = "diagonalization/s_psi path or its offload runtime"
        producer_command = (
            "then rerun dse_v2/scripts/dse/run_qe_accelerated_numeric_producer.py for the "
            "candidate/workload and replay build_dft_full_scf_numerical_rows.py --fail-on-blocked."
        )
    return (
        "Hardware side evidence exists only after the candidate-specific PPA stages pass. "
        f"To turn {kernel_id} into trusted full-SCF evidence, use the {producer_surface} "
        f"producer surface: instrument the QE {path_guidance} to emit "
        "QE_OFFLOAD_KERNEL_EVIDENCE_JSON and QE_OFFLOAD_PROVENANCE_JSON rows with "
        f"kernel_id={kernel_id}, full_kernel_recomputed=true, qe_mainflow_integrated=true, "
        "accelerated_results_consumed_by_qe=true, finite absolute_error/relative_error, "
        "candidate/workload identity, and a passed non-proxy runtime/L4 execution proof; "
        f"{producer_command}"
    )


def _json_paths(root: Path, *, candidate_id: str, kernel_id: str) -> list[Path]:
    if root.is_file() and root.suffix in {".json", ".jsonl"}:
        return [root]
    if root.is_dir():
        exact_parsed_dir = root / "parsed_hard_gate_results" / candidate_id / kernel_id
        if exact_parsed_dir.is_dir():
            return sorted(
                path
                for path in exact_parsed_dir.iterdir()
                if path.is_file() and path.suffix in {".json", ".jsonl"}
            )
        return sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix in {".json", ".jsonl"}
        )
    return []


def build_kernel_hardware_side_evidence_progress(
    *,
    candidate_id: str,
    workload_case_id: str,
    kernel_id: str,
    source_roots: Sequence[Path],
) -> dict[str, Any]:
    """Record candidate/kernel hardware-side evidence without upgrading QE trust.

    Parsed golden/RTL/HLS/Vivado/DC stage results are useful progress, but they
    do not prove that QE consumed accelerated results in the full-SCF mainflow
    and they do not create strict runtime events.  This diagnostic artifact
    records hardware closure separately and keeps QE-consumed numeric/runtime
    blockers explicit.
    """

    observations_by_stage: dict[str, list[dict[str, Any]]] = {
        stage_id: [] for stage_id in KERNEL_HARDWARE_SIDE_REQUIRED_STAGE_IDS
    }
    scanned_json_file_count = 0
    for root in source_roots:
        for path in _json_paths(Path(root), candidate_id=candidate_id, kernel_id=kernel_id):
            scanned_json_file_count += 1
            for locator, payload in _load_jsonish(path):
                for row in _walk_mappings(payload):
                    if not _stage_identity_matches(
                        row,
                        candidate_id=candidate_id,
                        workload_case_id=workload_case_id,
                        kernel_id=kernel_id,
                    ):
                        continue
                    stage_id = str(row.get("stage_id"))
                    observations_by_stage[stage_id].append(_hardware_stage_observation(locator, row))

    stage_records: list[dict[str, Any]] = []
    passed_stage_ids: list[str] = []
    missing_stage_ids: list[str] = []
    for stage_id in KERNEL_HARDWARE_SIDE_REQUIRED_STAGE_IDS:
        observations = observations_by_stage[stage_id]
        best = _best_hardware_stage_observation(observations)
        if best and best.get("passed") is True:
            passed_stage_ids.append(stage_id)
            stage_records.append(
                {
                    "stage_id": stage_id,
                    "status": "passed_hardware_side_stage",
                    "passed": True,
                    "best_observation": best,
                    "observation_count": len(observations),
                }
            )
            continue
        missing_stage_ids.append(stage_id)
        blockers = [f"hardware_side_stage_missing_or_blocked::{stage_id}"]
        for observation in observations:
            blockers.extend(str(item) for item in observation.get("blocker_ids", []) or [])
            if int(observation.get("raw_evidence_ref_count", 0) or 0) <= 0:
                blockers.append(f"hardware_side_stage_raw_refs_missing::{stage_id}")
        stage_records.append(
            {
                "stage_id": stage_id,
                "status": "missing_or_blocked",
                "passed": False,
                "best_observation": best,
                "observation_count": len(observations),
                "blockers": sorted(dict.fromkeys(blockers)),
            }
        )

    hardware_side_evidence_found = not missing_stage_ids
    remaining_blockers = [
        f"trusted_runtime_event_missing::{kernel_id}",
        f"trusted_qe_consumed_numeric_row_missing::{kernel_id}",
        f"qe_mainflow_consumption_evidence_missing::{kernel_id}",
    ]
    if not hardware_side_evidence_found:
        remaining_blockers.extend(
            f"hardware_side_stage_missing_or_blocked::{stage_id}" for stage_id in missing_stage_ids
        )
    status = (
        "hardware_side_evidence_found_qe_consumption_required"
        if hardware_side_evidence_found
        else "hardware_side_evidence_missing_or_incomplete"
    )
    queue_status = (
        "producer_required_after_hardware_side_evidence_found"
        if hardware_side_evidence_found
        else "hardware_side_evidence_required_before_qe_consumption"
    )
    queue_item = {
        "kind": "kernel_runtime_and_numeric_row",
        "kernel_id": kernel_id,
        "priority": 1,
        "status": queue_status,
        "required_fields": [
            "trusted accelerated_kernel runtime event",
            "QE_OFFLOAD_KERNEL_EVIDENCE_JSON row",
            "QE_OFFLOAD_PROVENANCE_JSON row",
            "full_kernel_recomputed=true",
            "qe_mainflow_integrated=true",
            "accelerated_results_consumed_by_qe=true",
            "finite absolute_error/relative_error",
            "passed non-proxy runtime/L4 execution proof",
            "candidate_id/workload_case_id match",
            "no proxy/callsite/smoke/timing/model markers",
        ],
        "blocking_reasons": sorted(dict.fromkeys(remaining_blockers)),
        "next_command_or_fix": _kernel_hardware_next_command_or_fix(kernel_id),
    }
    return {
        "schema_version": KERNEL_HARDWARE_SIDE_EVIDENCE_PROGRESS_SCHEMA,
        "generated_at": _now_iso(),
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "kernel_id": kernel_id,
        "status": status,
        "hardware_side_evidence_found": hardware_side_evidence_found,
        "hardware_stage_pass_count": len(passed_stage_ids),
        "hardware_stage_required_count": len(KERNEL_HARDWARE_SIDE_REQUIRED_STAGE_IDS),
        "passed_stage_ids": passed_stage_ids,
        "missing_or_blocked_stage_ids": missing_stage_ids,
        "stage_records": stage_records,
        "scanned_json_file_count": scanned_json_file_count,
        "trusted_runtime_event_found": False,
        "trusted_runtime_events_emitted": [],
        "trusted_qe_consumed_numeric_row_found": False,
        "trusted_numeric_rows_emitted": [],
        "remaining_blockers": sorted(dict.fromkeys(remaining_blockers)),
        "full_scf_seed_eligible": False,
        "deliverable_complete": False,
        "executable_repair_queue": [queue_item],
        "claim_boundary": (
            "Hardware side progress artifact only: parsed golden/VCS-or-RTL/Vivado/DC "
            "candidate-kernel evidence is not trusted QE-consumed numeric evidence and "
            "does not emit strict runtime events. Full-SCF trusted seed remains blocked "
            "until QE mainflow consumption, per-kernel numeric errors, and non-proxy "
            "runtime/accounting rows are produced and replayed."
        ),
    }


__all__ = [
    "KERNEL_HARDWARE_SIDE_EVIDENCE_PROGRESS_SCHEMA",
    "KERNEL_HARDWARE_SIDE_REQUIRED_STAGE_IDS",
    "build_kernel_hardware_side_evidence_progress",
]
