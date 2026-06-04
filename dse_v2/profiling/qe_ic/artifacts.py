#!/usr/bin/env python3
"""Artifact I/O for QE-IC Layer-2 motif profiles."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.profiling.qe_ic.aggregation import build_qe_ic_motif_profile
from dse_v2.profiling.qe_ic.schema import (
    DOWNSTREAM_CONSUMERS,
    MANIFEST_CLAIM_BOUNDARY,
    QE_IC_MOTIF_PROFILE_ARTIFACT,
    QE_IC_MOTIF_PROFILE_ARTIFACTS,
    QE_IC_MOTIF_PROFILE_MANIFEST_ARTIFACT,
    QE_IC_MOTIF_PROFILE_MANIFEST_SCHEMA_VERSION,
    QE_IC_MOTIF_PROFILE_README_ARTIFACT,
    QE_IC_MOTIF_PROFILE_VALIDATION_ARTIFACT,
    SOURCE_LAYER1_SUITE_ARTIFACT,
)
from dse_v2.profiling.qe_ic.source_registry import extract_profile_sources
from dse_v2.profiling.qe_ic.validation import validate_qe_ic_motif_profile


class QeIcMotifProfileArtifactError(ValueError):
    """Raised when persisted QE-IC motif-profile artifacts fail validation."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _remove_stale_canonical_artifacts(out_dir: Path) -> None:
    for artifact_name in (
        QE_IC_MOTIF_PROFILE_ARTIFACT,
        QE_IC_MOTIF_PROFILE_MANIFEST_ARTIFACT,
        QE_IC_MOTIF_PROFILE_README_ARTIFACT,
    ):
        artifact_path = out_dir / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open() as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise QeIcMotifProfileArtifactError(f"{path} does not exist") from exc
    if not isinstance(payload, dict):
        raise QeIcMotifProfileArtifactError(f"{path} did not contain a JSON object")
    return payload


def build_qe_ic_motif_profile_manifest() -> dict[str, Any]:
    """Build the QE-IC Layer-2 artifact manifest."""

    return {
        "schema_version": QE_IC_MOTIF_PROFILE_MANIFEST_SCHEMA_VERSION,
        "artifact_role": "dse_layer2_motif_profile",
        "profile_artifact": QE_IC_MOTIF_PROFILE_ARTIFACT,
        "validation_artifact": QE_IC_MOTIF_PROFILE_VALIDATION_ARTIFACT,
        "readme_artifact": QE_IC_MOTIF_PROFILE_README_ARTIFACT,
        "producer": "dse_v2.profiling.qe_ic",
        "layer": "layer2_motif_profiling",
        "source_layer1_suite_artifact": SOURCE_LAYER1_SUITE_ARTIFACT,
        "downstream_consumers": list(DOWNSTREAM_CONSUMERS),
        "claim_boundary": MANIFEST_CLAIM_BOUNDARY,
    }


def build_qe_ic_motif_profile_readme(profile: Mapping[str, Any]) -> str:
    """Build README text shipped beside generated profile artifacts."""

    group_lines = []
    for group in profile.get("family_target_profiles", []):
        if not isinstance(group, Mapping):
            continue
        unmapped_ratio = group.get("unmapped_time_ratio")
        unmapped_text = (
            f"{float(unmapped_ratio):.3f}"
            if isinstance(unmapped_ratio, int | float) and not isinstance(unmapped_ratio, bool)
            else str(unmapped_ratio)
        )
        motifs = ", ".join(
            f"{motif.get('motif_id')}={float(motif.get('runtime_ratio')):.3f}"
            for motif in group.get("motif_profiles", [])
            if isinstance(motif, Mapping)
            and isinstance(motif.get("runtime_ratio"), int | float)
            and not isinstance(motif.get("runtime_ratio"), bool)
        )
        group_lines.append(
            f"- `{group.get('workload_family_id')}` on `{group.get('target')}`: "
            f"total_time_ms={group.get('total_time_ms')}, "
            f"unmapped_time_ratio={unmapped_text}, motifs: {motifs}."
        )

    return "\n".join(
        [
            "# QE-IC Motif Profile v1",
            "",
            "## Artifact Role",
            "",
            "This Layer-2 artifact consumes the Layer-1 QE-IC workload suite and "
            "profile-source fixtures or log summaries. It maps raw profile events "
            "to registered workload motifs and aggregates runtime, memory movement, "
            "communication, parallel axes, unmapped time, and GPU-baseline coverage "
            "per workload family and target.",
            "",
            "## Family-Target Profiles",
            "",
            *group_lines,
            "",
            "## Source Boundary",
            "",
            "The first implementation supports `manual_profile_table` ingestion. "
            "`qe_timer_log`, `nsight_summary`, and `mpi_trace_summary` records may "
            "be registered, but parser support is intentionally reported as "
            "`parser_not_implemented_for_source_type` until implemented.",
            "",
            "## Claim Boundary",
            "",
            str(profile.get("claim_boundary")),
            "",
            "Layer-2 does not generate architectures, compare targets, decide "
            "viability, promote candidates, produce hardware implementation "
            "results, or make final performance claims.",
            "",
        ]
    )


def write_qe_ic_motif_profile_artifacts(
    out_dir: Path,
    suite_path: Path,
    profile_sources_path: Path,
) -> dict[str, Any]:
    """Write profile, validation, manifest, and README artifacts."""

    out_dir.mkdir(parents=True, exist_ok=True)
    suite = _load_json_object(suite_path)
    profile_sources_payload = _load_json_object(profile_sources_path)
    profile_sources = extract_profile_sources(profile_sources_payload)
    profile = build_qe_ic_motif_profile(suite, profile_sources)
    validation = validate_qe_ic_motif_profile(profile)
    _remove_stale_canonical_artifacts(out_dir)
    _write_json(out_dir / QE_IC_MOTIF_PROFILE_VALIDATION_ARTIFACT, validation)
    if validation["status"] != "passed":
        return {
            "status": validation["status"],
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_MOTIF_PROFILE_VALIDATION_ARTIFACT],
        }

    manifest = build_qe_ic_motif_profile_manifest()
    readme = build_qe_ic_motif_profile_readme(profile)

    _write_json(out_dir / QE_IC_MOTIF_PROFILE_ARTIFACT, profile)
    _write_json(out_dir / QE_IC_MOTIF_PROFILE_MANIFEST_ARTIFACT, manifest)
    (out_dir / QE_IC_MOTIF_PROFILE_README_ARTIFACT).write_text(readme)

    return {
        "status": validation["status"],
        "out_dir": str(out_dir),
        "artifacts": list(QE_IC_MOTIF_PROFILE_ARTIFACTS),
    }


def load_qe_ic_motif_profile(path: Path) -> dict[str, Any]:
    """Load and validate persisted motif profile."""

    payload = _load_json_object(path)
    validation = validate_qe_ic_motif_profile(payload)
    if validation["status"] != "passed":
        raise QeIcMotifProfileArtifactError(
            f"{path} failed QE-IC motif-profile validation: {validation['errors']}"
        )
    return payload
