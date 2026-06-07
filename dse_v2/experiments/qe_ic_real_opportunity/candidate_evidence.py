#!/usr/bin/env python3
"""Candidate high-fidelity evidence ingestion for QE-IC real opportunity campaigns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
import statistics
from pathlib import Path
from typing import Any

from dse_v2.evidence.qe_ic.candidate_result import validate_qe_ic_candidate_high_fidelity_results
from dse_v2.evidence.qe_ic.schema import (
    CANDIDATE_RESULT_CLAIM_BOUNDARY,
    REQUIRED_HIGH_FIDELITY_PROVENANCE_FIELDS,
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _selected_by_id(selected_candidates: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate.get("candidate_id")): candidate
        for candidate in selected_candidates
        if isinstance(candidate, Mapping) and isinstance(candidate.get("candidate_id"), str)
    }


def _record_has_provenance(record: Mapping[str, Any]) -> bool:
    provenance = _as_mapping(record.get("tool_provenance"))
    return all(isinstance(provenance.get(field), str) and provenance.get(field) for field in REQUIRED_HIGH_FIDELITY_PROVENANCE_FIELDS)


def _normalize_record(record: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized.setdefault("claim_boundary", CANDIDATE_RESULT_CLAIM_BOUNDARY)
    return normalized


def build_candidate_high_fidelity_evidence(
    *,
    candidate_records: Sequence[Mapping[str, Any]] | None = None,
    selected_candidates: Sequence[Mapping[str, Any]] | None = None,
    provided_artifact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build candidate high-fidelity artifact or emit evidence_missing."""

    selected = _selected_by_id(selected_candidates or [])
    if provided_artifact is not None:
        artifact = dict(provided_artifact)
        validation = validate_qe_ic_candidate_high_fidelity_results(artifact)
        if validation["status"] == "passed" and artifact.get("results_are_real") is True:
            return {
                "evidence_status": "measured_or_high_fidelity",
                "results_are_real": True,
                "artifact": artifact,
                "validation": validation,
                "blocker_reasons": [],
            }
        return {
            "evidence_status": "evidence_missing",
            "results_are_real": False,
            "artifact": None,
            "validation": validation,
            "blocker_reasons": ["provided_candidate_evidence_not_valid_real_high_fidelity"],
        }

    records = [_normalize_record(record) for record in (candidate_records or []) if isinstance(record, Mapping)]
    if not records:
        return {
            "evidence_status": "evidence_missing",
            "results_are_real": False,
            "artifact": None,
            "validation": {"status": "not_applicable", "errors": [], "warnings": []},
            "blocker_reasons": ["blocked_by_missing_candidate_evidence"],
        }

    blockers: list[str] = []
    selected_ids = set(selected)
    if selected_ids:
        for record in records:
            if str(record.get("candidate_id")) not in selected_ids:
                blockers.append("candidate_evidence_not_selected_from_layer4")
    for record in records:
        if record.get("evidence_level") == "l1_estimate_only" or record.get("source_label_kind") == "synthetic_feedback":
            blockers.append("l1_or_synthetic_not_high_fidelity")
        if record.get("evidence_status") == "high_fidelity_estimate" and not _record_has_provenance(record):
            blockers.append("high_fidelity_provenance_missing")
    if blockers:
        return {
            "evidence_status": "evidence_missing",
            "results_are_real": False,
            "artifact": None,
            "validation": {
                "status": "failed",
                "errors": [{"field": "candidate_results", "message": ", ".join(sorted(set(blockers)))}],
            },
            "blocker_reasons": sorted(set(blockers)),
        }

    artifact = {
        "schema_version": "dse.qe_ic.candidate_high_fidelity_results.v1",
        "results_are_real": True,
        "candidate_results": records,
    }
    validation = validate_qe_ic_candidate_high_fidelity_results(artifact)
    if validation["status"] != "passed":
        return {
            "evidence_status": "evidence_missing",
            "results_are_real": False,
            "artifact": None,
            "validation": validation,
            "blocker_reasons": ["candidate_high_fidelity_schema_validation_failed"],
        }
    return {
        "evidence_status": "measured_or_high_fidelity",
        "results_are_real": True,
        "artifact": artifact,
        "validation": validation,
        "blocker_reasons": [],
    }


def candidate_evidence_from_ingest_payload(
    payload: Mapping[str, Any] | None,
    *,
    selected_candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build candidate evidence from either full artifact or {candidate_results} payload."""

    if not isinstance(payload, Mapping):
        return build_candidate_high_fidelity_evidence(candidate_records=[], selected_candidates=selected_candidates)
    if payload.get("schema_version") == "dse.qe_ic.candidate_high_fidelity_results.v1":
        return build_candidate_high_fidelity_evidence(
            provided_artifact=payload,
            selected_candidates=selected_candidates,
        )
    return build_candidate_high_fidelity_evidence(
        candidate_records=[row for row in _as_list(payload.get("candidate_results")) if isinstance(row, Mapping)],
        selected_candidates=selected_candidates,
    )


def _bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes"}


def _float(value: str) -> float:
    return float(value.strip())


def _runs(value: str) -> list[float]:
    return [_float(part) for part in value.replace(";", "|").split("|") if part.strip()]


def candidate_evidence_from_csv(path: Path, *, selected_candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Ingest external CSV candidate evidence into the canonical high-fidelity artifact."""

    records: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            runtime_runs = _runs(row["runtime_seconds_runs"])
            runtime_mean = statistics.mean(runtime_runs)
            runtime_std = statistics.stdev(runtime_runs) if len(runtime_runs) > 1 else 0.0
            records.append(
                {
                    "candidate_id": row["candidate_id"],
                    "workload_family_id": row["workload_family_id"],
                    "motif_id": row["motif_id"],
                    "target_type": row["target_type"],
                    "case_id": row["case_id"],
                    "program": row["program"],
                    "input_deck_hash": row["input_deck_hash"],
                    "precision": row["precision"],
                    "evidence_level": row["evidence_level"],
                    "evidence_status": row["evidence_status"],
                    "architecture_summary": {
                        "architecture_id": row["architecture_id"],
                        "architecture_family": row["architecture_family"],
                        "gpu_role": row["gpu_role"],
                        "fpga_role": row["fpga_role"],
                        "host_role": row["host_role"],
                        "dataflow_summary": row["dataflow_summary"],
                        "memory_interface": row["memory_interface"],
                        "synchronization_model": row["synchronization_model"],
                    },
                    "runtime_seconds_runs": runtime_runs,
                    "runtime_seconds_mean": runtime_mean,
                    "runtime_seconds_std": runtime_std,
                    "confidence_interval_95": {
                        "low": min(runtime_runs),
                        "high": max(runtime_runs),
                    },
                    "workflow_runtime_seconds_mean": _float(row["workflow_runtime_seconds_mean"]),
                    "kernel_runtime_seconds_mean": _float(row["kernel_runtime_seconds_mean"]),
                    "transfer_overhead_seconds": _float(row["transfer_overhead_seconds"]),
                    "workflow_overhead_seconds": _float(row["workflow_overhead_seconds"]),
                    "resource": {
                        "resource_feasible": _bool(row["resource_feasible"]),
                        "timing_feasible": _bool(row["timing_feasible"]),
                        "lut_utilization": _float(row["lut_utilization"]),
                        "ff_utilization": _float(row["ff_utilization"]),
                        "bram_utilization": _float(row["bram_utilization"]),
                        "dsp_utilization": _float(row["dsp_utilization"]),
                        "hbm_port_utilization": _float(row["hbm_port_utilization"]),
                        "fmax_mhz": _float(row["fmax_mhz"]),
                    },
                    "evidence_artifact_hash": row["evidence_artifact_hash"],
                    "tool_provenance": {
                        "tool": row["tool"],
                        "version": row["version"],
                        "run_id": row["run_id"],
                        "config_hash": row["config_hash"],
                        "output_artifact_hash": row["output_artifact_hash"],
                    },
                }
            )
    return build_candidate_high_fidelity_evidence(
        candidate_records=records,
        selected_candidates=selected_candidates,
    )
