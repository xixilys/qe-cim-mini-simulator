#!/usr/bin/env python3
"""Bind DFT hierarchical search candidates to the frozen release universe.

The hierarchical DFT template search and the seven-axis release universe use
separate candidate-id rules.  This DFT-profile helper emits an auditable binding
map between those IDs so trial ledgers can cite both without pretending that a
heuristic binding is hard evidence or trusted Pareto proof.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_CANDIDATE_BINDING_MAP_SCHEMA = "dse.dft.candidate_binding_map.v1"
DFT_CANDIDATE_BINDING_MAP_VALIDATION_SCHEMA = "dse.dft.candidate_binding_map_validation.v1"

_TEMPLATE_AXIS_PREFERENCES: Dict[str, Dict[str, Sequence[str]]] = {
    "streaming_fft_hpsi_pipeline": {
        "dft_phase_hotspot_selection": ("scf_hpsi_density",),
        "algorithm_variants": ("iterative_diag_fft",),
        "mapping_data_layout": ("fft_grid_hbm_tiled",),
        "hardware_microarchitecture": ("host_fpga_minimal_v0",),
        "interface_descriptor_protocol": ("genericaccel_descriptor_v1",),
        "evidence_fidelity_promotion_policy": ("systemc_gem5_eda_formal_ladder", "systemc_then_gem5_non_smoke"),
    },
    "memory_hbm_dma_transpose": {
        "dft_phase_hotspot_selection": ("scf_hpsi_density",),
        "algorithm_variants": ("iterative_diag_fft",),
        "mapping_data_layout": ("fft_grid_hbm_tiled",),
        "hardware_microarchitecture": ("host_fpga_minimal_v0",),
        "interface_descriptor_protocol": ("genericaccel_descriptor_v1",),
        "evidence_fidelity_promotion_policy": ("systemc_gem5_eda_formal_ladder", "systemc_then_gem5_non_smoke"),
    },
    "hybrid_cpu_fpga_scf_sidecar": {
        "dft_phase_hotspot_selection": ("scf_hpsi_density", "hybrid_exx_fft"),
        "algorithm_variants": ("iterative_diag_fft", "batched_gemm_exx"),
        "mapping_data_layout": ("fft_grid_hbm_tiled", "band_block_systolic"),
        "hardware_microarchitecture": ("host_fpga_minimal_v0", "balanced_generic_systemc_v0"),
        "interface_descriptor_protocol": ("genericaccel_descriptor_v1",),
        "evidence_fidelity_promotion_policy": ("systemc_gem5_eda_formal_ladder", "systemc_then_gem5_non_smoke"),
    },
    "projector_heavy_gemm_gemv": {
        "dft_phase_hotspot_selection": ("hybrid_exx_fft",),
        "algorithm_variants": ("batched_gemm_exx",),
        "mapping_data_layout": ("band_block_systolic",),
        "hardware_microarchitecture": ("balanced_generic_systemc_v0", "host_fpga_minimal_v0"),
        "interface_descriptor_protocol": ("genericaccel_descriptor_v1", "batched_kernel_descriptor_v1"),
        "evidence_fidelity_promotion_policy": ("systemc_then_gem5_non_smoke", "systemc_gem5_eda_formal_ladder"),
    },
    "asic_tile_array_template": {
        "dft_phase_hotspot_selection": ("hybrid_exx_fft", "scf_hpsi_density"),
        "algorithm_variants": ("batched_gemm_exx",),
        "mapping_data_layout": ("band_block_systolic",),
        "hardware_microarchitecture": ("balanced_generic_systemc_v0",),
        "interface_descriptor_protocol": ("genericaccel_descriptor_v1",),
        "evidence_fidelity_promotion_policy": ("systemc_gem5_eda_formal_ladder",),
    },
}

_AXIS_WEIGHTS = {
    "dft_phase_hotspot_selection": 2.0,
    "algorithm_variants": 2.0,
    "mapping_data_layout": 1.5,
    "hardware_microarchitecture": 1.5,
    "interface_descriptor_protocol": 1.0,
    "evidence_fidelity_promotion_policy": 1.0,
    "schedule_runtime_policy": 0.5,
}

_CLAIM_BOUNDARY = (
    "Candidate binding maps relate DFT hierarchical search ids to frozen "
    "seven-axis release candidate ids for audit/resume. They are heuristic "
    "profile metadata, not hardware evidence, numerical correctness, trusted "
    "Pareto proof, or completion eligibility."
)


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path) -> Dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "hash_algorithm": "sha256",
    }


def _release_policy_from_search_row(search_row: Mapping[str, Any]) -> Dict[str, Any]:
    metadata = search_row.get("policy_metadata", {})
    metadata = metadata if isinstance(metadata, Mapping) else {}
    for candidate in (
        metadata.get("release_policy"),
        (metadata.get("template_policy", {}) if isinstance(metadata.get("template_policy"), Mapping) else {}).get("release_policy"),
    ):
        if isinstance(candidate, Mapping):
            lane = str(candidate.get("lane") or "exploratory")
            return {
                "lane": lane,
                "formal_pareto_allowed": bool(candidate.get("formal_pareto_allowed", lane == "release")),
                "exploratory_only": bool(candidate.get("exploratory_only", lane != "release")),
                "authority": str(candidate.get("authority") or "search_row.policy_metadata.release_policy"),
                "legacy_candidate_tier_authoritative": False,
            }
    if metadata.get("formal_pareto_eligible") is True:
        return {
            "lane": "release",
            "formal_pareto_allowed": True,
            "exploratory_only": False,
            "authority": "search_row.policy_metadata.formal_pareto_eligible",
            "legacy_candidate_tier_authoritative": False,
        }
    return {
        "lane": "exploratory",
        "formal_pareto_allowed": False,
        "exploratory_only": True,
        "authority": "default_fail_closed_release_policy",
        "legacy_candidate_tier_authoritative": False,
    }


def _search_records(report: Mapping[str, Any]) -> list[Dict[str, Any]]:
    rows = report.get("all_records")
    if not isinstance(rows, list) or not rows:
        rows = list(report.get("formal_pareto_records", []) or []) + list(report.get("exploratory_records", []) or [])
    result: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows or []:
        if isinstance(row, Mapping) and row.get("candidate_id"):
            candidate_id = str(row["candidate_id"])
            if candidate_id not in seen:
                seen.add(candidate_id)
                result.append(dict(row))
    return result


def _legal_release_candidates(manifest: Mapping[str, Any]) -> list[Dict[str, Any]]:
    return [
        dict(row)
        for row in manifest.get("candidates", []) or []
        if isinstance(row, Mapping) and row.get("legal") is True and row.get("candidate_id")
    ]


def _schedule_preference(params: Mapping[str, Any]) -> str:
    hbm = int(params.get("hbm_channels", 0) or 0)
    dma = int(params.get("dma_outstanding", 0) or 0)
    return "overlap_dma_compute" if hbm >= 8 or dma >= 16 else "host_orchestrated_sync"


def _score_binding(search_record: Mapping[str, Any], release_candidate: Mapping[str, Any]) -> tuple[float, list[str]]:
    params = search_record.get("parameters", {}) if isinstance(search_record.get("parameters", {}), Mapping) else {}
    template = str(params.get("template_family", ""))
    preferences = dict(_TEMPLATE_AXIS_PREFERENCES.get(template, {}))
    preferences["schedule_runtime_policy"] = (_schedule_preference(params),)
    assignments = release_candidate.get("assignments", {}) if isinstance(release_candidate.get("assignments", {}), Mapping) else {}
    score = 0.0
    reasons: list[str] = []
    for axis, preferred_values in preferences.items():
        actual = str(assignments.get(axis, ""))
        if actual in preferred_values:
            rank = list(preferred_values).index(actual)
            axis_score = _AXIS_WEIGHTS.get(axis, 1.0) / float(rank + 1)
            score += axis_score
            reasons.append(f"{axis}:{actual}:rank{rank}")
    screening = release_candidate.get("screening", {}) if isinstance(release_candidate.get("screening", {}), Mapping) else {}
    score += float(screening.get("score", 0.0) or 0.0) * 0.01
    return score, reasons


def build_dft_candidate_binding_map(
    *,
    hierarchical_search_report_path: Path,
    candidate_universe_manifest_path: Path,
    per_candidate_evidence_ledger_path: Path | None = None,
) -> Dict[str, Any]:
    search_report = _load_json(hierarchical_search_report_path)
    manifest = _load_json(candidate_universe_manifest_path)
    evidence_ledger = _load_json(per_candidate_evidence_ledger_path) if per_candidate_evidence_ledger_path else {}
    search_rows = _search_records(search_report)
    legal_candidates = _legal_release_candidates(manifest)
    evidence_ids = {
        str(row.get("candidate_id"))
        for row in evidence_ledger.get("rows", []) or []
        if isinstance(row, Mapping) and row.get("candidate_id")
    }
    binding_rows: list[Dict[str, Any]] = []
    for search_row in search_rows:
        params = search_row.get("parameters", {}) if isinstance(search_row.get("parameters", {}), Mapping) else {}
        scored = [
            (*_score_binding(search_row, candidate), candidate)
            for candidate in legal_candidates
        ]
        scored.sort(key=lambda item: (item[0], float((item[2].get("screening", {}) or {}).get("score", 0.0) or 0.0), str(item[2].get("candidate_id"))), reverse=True)
        if scored and scored[0][0] > 0:
            score, reasons, candidate = scored[0]
            release_candidate_id = str(candidate["candidate_id"])
            status = "matched_by_template_axis_heuristic"
            confidence = min(1.0, score / sum(_AXIS_WEIGHTS.values()))
            assignments = dict(candidate.get("assignments", {}) or {})
            evidence_row_present = release_candidate_id in evidence_ids if evidence_ids else None
        else:
            release_candidate_id = None
            status = "unmatched_no_legal_release_candidate"
            confidence = 0.0
            reasons = []
            assignments = {}
            evidence_row_present = False if evidence_ids else None
        binding_rows.append({
            "search_candidate_id": str(search_row["candidate_id"]),
            "release_candidate_id": release_candidate_id,
            "binding_status": status,
            "confidence": confidence,
            "template_family": params.get("template_family"),
            "release_policy": _release_policy_from_search_row(search_row),
            "release_assignments": assignments,
            "evidence_row_present": evidence_row_present,
            "reasons": reasons,
            "completion_eligible": False,
            "claim_boundary": _CLAIM_BOUNDARY,
        })
    unmatched = [row for row in binding_rows if not row.get("release_candidate_id")]
    duplicate_release_ids = sorted({
        row["release_candidate_id"]
        for row in binding_rows
        if row.get("release_candidate_id") and sum(1 for other in binding_rows if other.get("release_candidate_id") == row.get("release_candidate_id")) > 1
    })
    return {
        "schema_version": DFT_CANDIDATE_BINDING_MAP_SCHEMA,
        "status": "passed" if not unmatched else "blocked_temporary",
        "workload_suite_id": search_report.get("workload_suite_id"),
        "release_id": manifest.get("release_id"),
        "source_artifacts": {
            "hierarchical_search_report": _source_ref(hierarchical_search_report_path),
            "candidate_universe_manifest": _source_ref(candidate_universe_manifest_path),
            **({"per_candidate_evidence_ledger": _source_ref(per_candidate_evidence_ledger_path)} if per_candidate_evidence_ledger_path else {}),
        },
        "search_candidate_count": len(search_rows),
        "legal_release_candidate_count": len(legal_candidates),
        "bound_candidate_count": len(binding_rows) - len(unmatched),
        "unmatched_candidate_count": len(unmatched),
        "unique_release_candidate_count": len({row.get("release_candidate_id") for row in binding_rows if row.get("release_candidate_id")}),
        "duplicate_release_candidate_ids": duplicate_release_ids,
        "binding_rows": binding_rows,
        "completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_candidate_binding_map(binding_map: Mapping[str, Any] | Path) -> Dict[str, Any]:
    if isinstance(binding_map, Path):
        payload = _load_json(binding_map)
    else:
        payload = dict(binding_map)
    errors: list[Dict[str, Any]] = []
    rows = payload.get("binding_rows", [])
    if payload.get("schema_version") != DFT_CANDIDATE_BINDING_MAP_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected candidate binding schema"})
    if not isinstance(rows, list) or not rows:
        errors.append({"field": "binding_rows", "message": "non-empty binding_rows required"})
        rows = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append({"field": f"binding_rows[{index}]", "message": "binding row must be an object"})
            continue
        search_id = str(row.get("search_candidate_id", ""))
        if not search_id:
            errors.append({"field": f"binding_rows[{index}].search_candidate_id", "message": "search_candidate_id required"})
        if search_id in seen:
            errors.append({"field": f"binding_rows[{index}].search_candidate_id", "message": "duplicate search_candidate_id"})
        seen.add(search_id)
        if not row.get("release_candidate_id"):
            errors.append({"field": f"binding_rows[{index}].release_candidate_id", "message": "release_candidate_id required for every search candidate"})
        if row.get("binding_status") == "matched_by_template_axis_heuristic" and not row.get("release_candidate_id"):
            errors.append({"field": f"binding_rows[{index}].release_candidate_id", "message": "matched row requires release_candidate_id"})
        if row.get("completion_eligible") is True:
            errors.append({"field": f"binding_rows[{index}].completion_eligible", "message": "binding rows cannot be completion eligible"})
    if payload.get("bound_candidate_count") != len(rows):
        errors.append({"field": "bound_candidate_count", "message": "all binding rows must be bound to a release candidate"})
    if payload.get("unmatched_candidate_count") not in (0, None):
        errors.append({"field": "unmatched_candidate_count", "message": "unmatched candidate bindings are invalid"})
    if payload.get("deliverable_complete") is True or payload.get("completion_eligible") is True:
        errors.append({"field": "deliverable_complete", "message": "candidate binding map cannot be deliverable-complete evidence"})
    return {
        "schema_version": DFT_CANDIDATE_BINDING_MAP_VALIDATION_SCHEMA,
        "valid": not errors,
        "row_count": len(rows),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_candidate_binding_map(
    out_dir: Path,
    *,
    hierarchical_search_report_path: Path,
    candidate_universe_manifest_path: Path,
    per_candidate_evidence_ledger_path: Path | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_candidate_binding_map(
        hierarchical_search_report_path=hierarchical_search_report_path,
        candidate_universe_manifest_path=candidate_universe_manifest_path,
        per_candidate_evidence_ledger_path=per_candidate_evidence_ledger_path,
    )
    map_path = out_dir / "dft_candidate_binding_map.json"
    write_json(map_path, payload)
    validation = validate_dft_candidate_binding_map(payload)
    write_json(out_dir / "dft_candidate_binding_map_validation.json", validation)
    status = {
        "schema_version": "dse.dft.candidate_binding_map_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "binding_map": "dft_candidate_binding_map.json",
        "validation": "dft_candidate_binding_map_validation.json",
        "bound_candidate_count": payload["bound_candidate_count"],
        "unmatched_candidate_count": payload["unmatched_candidate_count"],
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_candidate_binding_map_status.json", status)
    return status


__all__ = [
    "DFT_CANDIDATE_BINDING_MAP_SCHEMA",
    "DFT_CANDIDATE_BINDING_MAP_VALIDATION_SCHEMA",
    "build_dft_candidate_binding_map",
    "validate_dft_candidate_binding_map",
    "write_dft_candidate_binding_map",
]
