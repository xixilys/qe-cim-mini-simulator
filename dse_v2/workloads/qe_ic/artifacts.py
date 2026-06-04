#!/usr/bin/env python3
"""Artifact I/O for the QE-IC Layer-1 workload suite."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.workloads.qe_ic.schema import (
    DOWNSTREAM_CONSUMERS,
    MANIFEST_CLAIM_BOUNDARY,
    QE_IC_ARTIFACTS,
    QE_IC_WORKLOAD_SUITE_ARTIFACT,
    QE_IC_WORKLOAD_SUITE_MANIFEST_ARTIFACT,
    QE_IC_WORKLOAD_SUITE_MANIFEST_SCHEMA_VERSION,
    QE_IC_WORKLOAD_SUITE_README_ARTIFACT,
    QE_IC_WORKLOAD_SUITE_VALIDATION_ARTIFACT,
)
from dse_v2.workloads.qe_ic.suite import build_default_qe_ic_workload_suite
from dse_v2.workloads.qe_ic.validation import validate_qe_ic_workload_suite


class QeIcWorkloadSuiteArtifactError(ValueError):
    """Raised when persisted QE-IC suite artifacts fail validation."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def build_qe_ic_workload_suite_manifest() -> dict[str, Any]:
    """Build the QE-IC Layer-1 artifact manifest."""

    return {
        "schema_version": QE_IC_WORKLOAD_SUITE_MANIFEST_SCHEMA_VERSION,
        "artifact_role": "dse_layer1_workload_suite",
        "suite_artifact": QE_IC_WORKLOAD_SUITE_ARTIFACT,
        "validation_artifact": QE_IC_WORKLOAD_SUITE_VALIDATION_ARTIFACT,
        "readme_artifact": QE_IC_WORKLOAD_SUITE_README_ARTIFACT,
        "producer": "dse_v2.workloads.qe_ic",
        "layer": "layer1_workload_suite_definition",
        "downstream_consumers": list(DOWNSTREAM_CONSUMERS),
        "claim_boundary": MANIFEST_CLAIM_BOUNDARY,
    }


def build_qe_ic_workload_suite_readme(suite: Mapping[str, Any]) -> str:
    """Build the README text shipped beside generated suite artifacts."""

    families = suite.get("workload_families", [])
    scenarios = suite.get("scenarios", [])
    excluded = suite.get("excluded_workflows", [])

    family_lines = []
    for family in families if isinstance(families, list) else []:
        if not isinstance(family, Mapping):
            continue
        deps = ", ".join(family.get("depends_on_families") or ["none"])
        motifs = ", ".join(family.get("expected_motifs", []))
        family_lines.append(
            f"- `{family.get('family_id')}`: {family.get('family_name')} "
            f"({family.get('priority')}); dependencies: {deps}; motifs: {motifs}."
        )

    scenario_lines = []
    for scenario in scenarios if isinstance(scenarios, list) else []:
        if not isinstance(scenario, Mapping):
            continue
        weights = scenario.get("weights", {})
        weight_text = ", ".join(
            f"{family_id}={weight:.2f}" if isinstance(weight, float) else f"{family_id}={weight}"
            for family_id, weight in weights.items()
        ) if isinstance(weights, Mapping) else ""
        scenario_lines.append(
            f"- `{scenario.get('scenario_id')}`: {scenario.get('description')} "
            f"Weights: {weight_text}."
        )

    excluded_lines = []
    for row in excluded if isinstance(excluded, list) else []:
        if isinstance(row, Mapping):
            excluded_lines.append(f"- `{row.get('workflow')}`: {row.get('reason')}.")

    return "\n".join(
        [
            "# QE-IC Device Workload Suite v1",
            "",
            "## Suite Goal",
            "",
            "This Layer-1 artifact defines the workload scope for an IC-device-oriented "
            "DFT design-space exploration proof path. It gives later layers a stable "
            "registry of workload families, dependencies, expected motifs, scenario "
            "weights, excluded workflows, and the next-layer profiling contract.",
            "",
            "## Why IC Device Workloads",
            "",
            "The suite targets electronic-structure, phonon, transport, operating-condition, "
            "interface, and defect calculations that shape semiconductor and device "
            "co-design questions. These workloads are broad enough to exercise the "
            "generic DSE control plane while remaining scoped to a concrete QE-centered "
            "research proof path.",
            "",
            "## Why Mobility Is The Primary Scenario",
            "",
            "Carrier mobility and electron-phonon transport connect ground-state, DFPT, "
            "interpolation, scattering, and sweep workflows. That dependency chain makes "
            "mobility a demanding first scenario for multi-fidelity DSE. It also forces "
            "later layers to keep GPU baselines visible because QE/EPW and related "
            "transport workflows already have heterogeneous-computing baselines.",
            "",
            "## Workload Families",
            "",
            *family_lines,
            "",
            "## Scenario Weights",
            "",
            "Scenario weights describe how important each workload family is in a "
            "system-level IC design scenario. They are scenario facts, not intrinsic "
            "properties of the workload families.",
            "",
            *scenario_lines,
            "",
            "## Excluded Workflows",
            "",
            *excluded_lines,
            "",
            "## Interface To Layer-2 Motif Profiling",
            "",
            "Every workload family carries a `profiling_contract` requiring runtime "
            "breakdown, operation mix, memory movement, communication pattern, parallel "
            "axes, reuse opportunities, and an explicit GPU baseline field. Layer-2 "
            "must measure or otherwise justify those fields before target viability or "
            "promotion policy consumes this suite.",
            "",
            "## Performance And Claim Boundary",
            "",
            str(suite.get("claim_boundary")),
            "",
            "This artifact does not rank GPU, FPGA, GPU+FPGA, CPU, or ASIC targets. It "
            "does not contain profiling results, architecture candidates, performance "
            "estimates, target viability results, promotion decisions, or hardware "
            "claim evidence.",
            "",
            "## External Program Boundary",
            "",
            "`perturbo` is included only as a reference external transport program for "
            "`electron_phonon_mobility`; it is not treated as a core QE executable.",
            "",
        ]
    )


def write_qe_ic_workload_suite_artifacts(
    out_dir: Path,
    suite: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write suite, validation, manifest, and README artifacts."""

    out_dir.mkdir(parents=True, exist_ok=True)
    suite_payload = dict(suite) if suite is not None else build_default_qe_ic_workload_suite()
    manifest = build_qe_ic_workload_suite_manifest()
    validation = validate_qe_ic_workload_suite(suite_payload, manifest=manifest)
    _write_json(out_dir / QE_IC_WORKLOAD_SUITE_VALIDATION_ARTIFACT, validation)
    if validation["status"] != "passed":
        return {
            "status": validation["status"],
            "out_dir": str(out_dir),
            "artifacts": [QE_IC_WORKLOAD_SUITE_VALIDATION_ARTIFACT],
        }

    readme = build_qe_ic_workload_suite_readme(suite_payload)

    _write_json(out_dir / QE_IC_WORKLOAD_SUITE_ARTIFACT, suite_payload)
    _write_json(out_dir / QE_IC_WORKLOAD_SUITE_MANIFEST_ARTIFACT, manifest)
    (out_dir / QE_IC_WORKLOAD_SUITE_README_ARTIFACT).write_text(readme)

    return {
        "status": validation["status"],
        "out_dir": str(out_dir),
        "artifacts": list(QE_IC_ARTIFACTS),
    }


def load_qe_ic_workload_suite(path: Path) -> dict[str, Any]:
    """Load a persisted suite artifact and validate it fail-closed."""

    try:
        with path.open() as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise QeIcWorkloadSuiteArtifactError(f"{path} does not exist") from exc
    if not isinstance(payload, dict):
        raise QeIcWorkloadSuiteArtifactError(f"{path} did not contain a JSON object")
    validation = validate_qe_ic_workload_suite(payload)
    if validation["status"] != "passed":
        raise QeIcWorkloadSuiteArtifactError(
            f"{path} failed QE-IC workload-suite validation: {validation['errors']}"
        )
    return payload
