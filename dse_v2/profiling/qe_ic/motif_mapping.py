#!/usr/bin/env python3
"""Raw profile-event to QE-IC motif mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


EVENT_NAME_TO_MOTIF_RULES = {
    "fft": "fft_transpose",
    "transpose": "fft_transpose",
    "h_psi": "hpsi",
    "hpsi": "hpsi",
    "projector": "projector_nonlocal",
    "calbec": "projector_nonlocal",
    "diagonalization": "diagonalization",
    "cdiagh": "diagonalization",
    "gemm": "dense_linear_algebra",
    "mix_rho": "density_update",
    "reduction": "reduction_collective",
    "allreduce": "reduction_collective",
    "ph_rhs": "perturbation_rhs",
    "response": "response_accumulation",
    "epw_interp": "dense_kq_interpolation",
    "bte": "bte_collision_integral",
    "mobility": "bte_collision_integral",
}


def map_profile_event_to_motif(
    event: Mapping[str, Any],
    suite: Mapping[str, Any],
) -> dict[str, Any]:
    """Map raw profile event to registered motif or mark unmapped."""

    event_name = str(event.get("event_name", ""))
    motif_registry = suite.get("motif_registry", {})
    if not isinstance(motif_registry, Mapping):
        motif_registry = {}

    mapping_hint = event.get("mapping_hint")
    if isinstance(mapping_hint, str) and mapping_hint in motif_registry:
        return {
            "event_name": event_name,
            "motif_id": mapping_hint,
            "mapping_status": "mapped",
            "mapping_confidence": "high",
            "mapping_reason": "mapping_hint",
        }

    lowered_name = event_name.lower()
    for token, motif_id in EVENT_NAME_TO_MOTIF_RULES.items():
        if token in lowered_name and motif_id in motif_registry:
            return {
                "event_name": event_name,
                "motif_id": motif_id,
                "mapping_status": "mapped",
                "mapping_confidence": "medium",
                "mapping_reason": f"event_name_rule:{token}",
            }

    return {
        "event_name": event_name,
        "motif_id": "unmapped",
        "mapping_status": "unmapped",
        "mapping_confidence": "none",
        "mapping_reason": "no registered motif mapping",
    }

