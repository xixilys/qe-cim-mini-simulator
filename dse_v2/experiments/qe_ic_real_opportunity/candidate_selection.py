#!/usr/bin/env python3
"""Layer-4-only candidate selection for QE-IC real opportunity campaigns."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


KIND_MATCHERS = {
    "fpga_fft_transpose_pipeline": {
        "target_type": "fpga_only",
        "template_ids": {"fpga_fft_transpose_engine", "fpga_streaming_pipeline"},
        "template_families": {"fpga_fft", "fpga_pipeline"},
        "motif_ids": {"fft_transpose"},
    },
    "hybrid_reduction_sidecar": {
        "target_type": "gpu_fpga_hybrid",
        "template_ids": {"hybrid_reduction_sidecar"},
        "template_families": {"hybrid_sidecar"},
        "motif_ids": {"reduction_collective"},
    },
    "hybrid_dma_or_memory_staging_sidecar": {
        "target_type": "gpu_fpga_hybrid",
        "template_ids": {"hybrid_dma_overlap_sidecar", "hybrid_memory_staging_sidecar"},
        "template_families": {"hybrid_dma", "hybrid_memory"},
        "motif_ids": {"reduction_collective", "dense_kq_interpolation", "wavefunction_memory"},
    },
}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _decision_by_candidate(candidate_plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(decision.get("candidate_id")): decision
        for decision in _as_list(candidate_plan.get("promotion_decisions"))
        if isinstance(decision, Mapping)
    }


def _matches_kind(candidate: Mapping[str, Any], kind: str) -> bool:
    matcher = KIND_MATCHERS.get(kind)
    if matcher is None:
        return False
    params = _as_mapping(candidate.get("candidate_parameters"))
    return (
        candidate.get("target_type") == matcher["target_type"]
        and (
            candidate.get("template_id") in matcher["template_ids"]
            or params.get("template_family") in matcher["template_families"]
        )
        and (
            not matcher["motif_ids"]
            or candidate.get("motif_id") in matcher["motif_ids"]
        )
    )


def _promotion_text(decision: Mapping[str, Any]) -> str:
    if not decision:
        return "unknown"
    return str(decision.get("decision") or "unknown")


def _selection_row(candidate: Mapping[str, Any], decision: Mapping[str, Any], kind: str) -> dict[str, Any]:
    params = _as_mapping(candidate.get("candidate_parameters"))
    return {
        "candidate_id": candidate.get("candidate_id"),
        "workload_family_id": candidate.get("workload_family_id"),
        "motif_id": candidate.get("motif_id"),
        "target_type": candidate.get("target_type"),
        "template_id": candidate.get("template_id"),
        "template_family": params.get("template_family"),
        "promotion_decision": _promotion_text(decision),
        "promotion_score": decision.get("promotion_score") if decision else None,
        "why_selected": f"selected for campaign target kind {kind} from Layer-4 candidate plan",
        "selection_source": "layer4_candidate_plan",
        "target_candidate_kind": kind,
        "candidate_parameters": dict(params),
    }


def select_layer4_candidates_for_campaign(
    *,
    candidate_plan: Mapping[str, Any],
    candidate_selection_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Select up to configured candidate kinds, never inventing candidate IDs."""

    if candidate_selection_config.get("select_from_layer4_only") is not True:
        return {
            "selection_status": "candidate_selection_blocked",
            "selected_candidates": [],
            "blocker_reasons": ["select_from_layer4_only_not_enabled"],
        }
    candidates = [
        candidate
        for candidate in _as_list(candidate_plan.get("candidates"))
        if isinstance(candidate, Mapping) and candidate.get("target_type") in {"fpga_only", "gpu_fpga_hybrid"}
    ]
    decisions = _decision_by_candidate(candidate_plan)
    max_candidates = int(candidate_selection_config.get("max_candidates", 3))
    target_kinds = [
        str(kind)
        for kind in _as_list(candidate_selection_config.get("target_candidate_kinds"))
        if isinstance(kind, str)
    ]
    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    used_ids: set[str] = set()
    for kind in target_kinds:
        matches = [candidate for candidate in candidates if _matches_kind(candidate, kind)]
        matches.sort(
            key=lambda candidate: (
                -float(_as_mapping(decisions.get(str(candidate.get("candidate_id")))).get("promotion_score") or 0.0),
                str(candidate.get("candidate_id")),
            )
        )
        match = next((candidate for candidate in matches if str(candidate.get("candidate_id")) not in used_ids), None)
        if match is None:
            missing.append(kind)
            continue
        candidate_id = str(match.get("candidate_id"))
        used_ids.add(candidate_id)
        selected.append(_selection_row(match, _as_mapping(decisions.get(candidate_id)), kind))
        if len(selected) >= max_candidates:
            break

    status = "selected" if len(selected) == min(max_candidates, len(target_kinds)) and not missing else "candidate_selection_blocked"
    blockers = ["missing_target_candidate_kinds"] if missing else []
    return {
        "selection_status": status,
        "selected_candidates": selected,
        "selected_candidate_count": len(selected),
        "requested_candidate_kinds": target_kinds,
        "missing_candidate_kinds": missing,
        "blocker_reasons": blockers,
        "claim_boundary": "Candidate selection is Layer-4-only and does not invent candidate IDs or imply speedup.",
    }
