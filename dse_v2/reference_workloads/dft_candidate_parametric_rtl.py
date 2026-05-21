#!/usr/bin/env python3
"""Candidate-parameter sidecar helpers for DFT RTL/HLS source flows.

The DFT hardware closure flow must not treat a candidate-id stamped copy of a
static RTL microkernel as candidate-parametric PPA evidence.  These helpers
extract design-shaping assignments from candidate bundles/packet units, derive a
stable RTL parameter manifest, and stamp generated source files with a
candidate-parameter hash.  The hash is provenance for generated source identity;
it is not a PPA score and must not be used to break physical Vivado/DC metric
ties by itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


DFT_CANDIDATE_PARAMETER_MANIFEST_SCHEMA = "dse.dft.hardware_candidate_parameter_manifest.v1"

_DESIGN_ASSIGNMENT_KEYS = (
    "algorithm_variants",
    "hardware_microarchitecture",
    "mapping_data_layout",
    "schedule_runtime_policy",
    "interface_descriptor_protocol",
    "precision_policy",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _short_hash(payload: Mapping[str, Any], *, modulo: int) -> int:
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % modulo


def _mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _run_dir_from_candidate_bundle_path(path: Path) -> Path | None:
    parts = path.parts
    if "candidate_specific_bundles" not in parts:
        return None
    index = parts.index("candidate_specific_bundles")
    if index == 0:
        return None
    return Path(*parts[:index])


def _ranking_metadata_for_candidate(path: Path, candidate_id: str) -> dict[str, Any]:
    run_dir = _run_dir_from_candidate_bundle_path(path)
    if run_dir is None or not candidate_id:
        return {}
    ranking = _load_json(run_dir / "dft_hardware_ppa_ranking.json")
    rows = ranking.get("candidate_rows", [])
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, Mapping) or str(row.get("candidate_id", "")) != candidate_id:
            continue
        return {
            key: dict(row.get(key, {})) if isinstance(row.get(key), Mapping) else row.get(key)
            for key in (
                "design_candidate_id",
                "assignments",
                "identity_assignments",
                "non_identity_assignments",
                "applicability_assignments",
                "evaluation_policy_assignments",
            )
            if row.get(key) not in (None, {}, [])
        }
    return {}


def _design_assignments(payload: Mapping[str, Any]) -> dict[str, Any]:
    direct = _mapping(payload, "design_assignments")
    if direct:
        return {key: direct[key] for key in _DESIGN_ASSIGNMENT_KEYS if key in direct}
    assignments = _mapping(payload, "assignments")
    identity = _mapping(payload, "identity_assignments")
    merged = {key: assignments[key] for key in _DESIGN_ASSIGNMENT_KEYS if key in assignments}
    for key, value in identity.items():
        if key in _DESIGN_ASSIGNMENT_KEYS:
            merged.setdefault(key, value)
    return merged


def _derive_rtl_parameters(*, kernel_id: str, design_assignments: Mapping[str, Any]) -> dict[str, int]:
    """Derive deterministic hardware-shaping parameters from design assignments."""

    hardware = str(design_assignments.get("hardware_microarchitecture", "generic"))
    mapping = str(design_assignments.get("mapping_data_layout", "generic"))
    schedule = str(design_assignments.get("schedule_runtime_policy", "generic"))
    interface = str(design_assignments.get("interface_descriptor_protocol", "generic"))
    algorithm = str(design_assignments.get("algorithm_variants", "generic"))
    seed = {"kernel_id": kernel_id, "design_assignments": dict(design_assignments)}
    return {
        "rtl_lane_count": 4 if "balanced" in hardware else 2 if "minimal" in hardware else 1 + _short_hash(seed, modulo=4),
        "rtl_hbm_channel_count": 4 if "hbm" in mapping else 2,
        "rtl_tile_factor": 4 if "batched" in algorithm or "systolic" in mapping else 2,
        "rtl_pipeline_depth": 3 if "overlap" in schedule else 1,
        "rtl_descriptor_fifo_depth": 8 if "batched" in interface else 4,
        "rtl_kernel_variant": _short_hash(seed, modulo=65536),
    }


def load_candidate_parameter_manifest(
    source: Mapping[str, Any] | Path | str | None,
    *,
    candidate_id: str | None = None,
    kernel_id: str | None = None,
) -> dict[str, Any]:
    """Return a canonical candidate parameter manifest, or ``{}`` when absent."""

    source_path: Path | None = None
    if source is None:
        payload: dict[str, Any] = {}
    elif isinstance(source, Mapping):
        payload = dict(source)
    else:
        source_path = Path(source)
        payload = _load_json(source_path)
    candidate = str(candidate_id or payload.get("candidate_id") or payload.get("release_candidate_id") or "")
    if source_path is not None:
        for key, value in _ranking_metadata_for_candidate(source_path, candidate).items():
            payload.setdefault(key, value)
    design_assignments = _design_assignments(payload)
    rtl_parameters = _mapping(payload, "rtl_parameter_values") or _mapping(payload, "rtl_parameters")
    kernel = str(kernel_id or payload.get("kernel_id") or "")
    if not design_assignments and not rtl_parameters and not payload.get("design_candidate_id"):
        return {}
    if not rtl_parameters:
        rtl_parameters = _derive_rtl_parameters(kernel_id=kernel, design_assignments=design_assignments)
    hash_payload = {
        "schema_version": DFT_CANDIDATE_PARAMETER_MANIFEST_SCHEMA,
        "kernel_id": kernel,
        "design_assignments": design_assignments,
        "rtl_parameter_values": rtl_parameters,
    }
    param_hash = hashlib.sha256(_canonical_json(hash_payload).encode("utf-8")).hexdigest()
    return {
        **hash_payload,
        "design_candidate_id": payload.get("design_candidate_id"),
        "candidate_id": candidate,
        "candidate_parametric_source_hash": param_hash,
        "hash_algorithm": "sha256",
        "basis": "design_assignments_and_derived_rtl_parameters",
        "excluded_from_hash": [
            "candidate_id",
            "design_candidate_id",
            "dft_phase_hotspot_selection",
            "evidence_fidelity_promotion_policy",
            "design_score",
        ],
        "claim_boundary": (
            "This manifest proves generated RTL source provenance consumed design "
            "assignments. It is not a physical PPA score or a tie-breaker unless "
            "Vivado/DC metrics also differ through generated candidate-specific source."
        ),
    }


def candidate_parameter_manifest_fields(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not manifest:
        return {}
    return {
        "candidate_parameter_manifest": "candidate_parameter_manifest.json",
        "candidate_parametric_source_hash": manifest.get("candidate_parametric_source_hash"),
        "rtl_parameter_values": dict(manifest.get("rtl_parameter_values", {}))
        if isinstance(manifest.get("rtl_parameter_values"), Mapping)
        else {},
        "candidate_parameter_basis": manifest.get("basis"),
    }


def write_candidate_parameter_manifest(out_dir: Path, manifest: Mapping[str, Any]) -> None:
    if not manifest:
        return
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "candidate_parameter_manifest.json").write_text(
        json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parametrize_rtl_source(kernel_id: str, rtl_text: str, manifest: Mapping[str, Any] | None) -> str:
    """Stamp RTL text with candidate-parameter provenance when available."""

    if not manifest:
        return rtl_text
    param_hash = str(manifest.get("candidate_parametric_source_hash") or "")
    if not param_hash:
        return rtl_text
    short = param_hash[:16]
    variant = int(str(manifest.get("rtl_parameter_values", {}).get("rtl_kernel_variant", 0) or 0)) & 0xFFFF
    safe_kernel = re.sub(r"[^A-Za-z0-9_]+", "_", kernel_id)
    header = [
        "// DFT_CANDIDATE_PARAMETRIC_RTL_BEGIN",
        f"// candidate_parametric_source_hash: {param_hash}",
        f"// rtl_parameter_values: {_canonical_json(manifest.get('rtl_parameter_values', {}))}",
        "// assignment-derived sidecars remain non-ranking metadata until physical PPA metrics differ.",
        f"module dft_candidate_parametric_anchor_{safe_kernel}_{short}();",
        f"  localparam [15:0] DFT_CANDIDATE_RTL_VARIANT = 16'h{variant:04x};",
        "endmodule",
        "// DFT_CANDIDATE_PARAMETRIC_RTL_END",
        "",
    ]
    return "\n".join(header) + rtl_text
