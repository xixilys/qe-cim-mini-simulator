#!/usr/bin/env python3
"""Fail-closed validation for the QE-IC Layer-1 workload suite."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from dse_v2.workloads.qe_ic.registry import REQUIRED_FIRST_VERSION_FAMILY_IDS
from dse_v2.workloads.qe_ic.schema import (
    CLAIM_BOUNDARY,
    DOWNSTREAM_CONSUMERS,
    PROFILING_CONTRACT_REQUIRED_FIELDS,
    QE_IC_ARTIFACTS,
    QE_IC_WORKLOAD_SUITE_ARTIFACT,
    QE_IC_WORKLOAD_SUITE_ID,
    QE_IC_WORKLOAD_SUITE_MANIFEST_ARTIFACT,
    QE_IC_WORKLOAD_SUITE_MANIFEST_SCHEMA_VERSION,
    QE_IC_WORKLOAD_SUITE_README_ARTIFACT,
    QE_IC_WORKLOAD_SUITE_SCHEMA_VERSION,
    QE_IC_WORKLOAD_SUITE_VALIDATION_ARTIFACT,
    QE_IC_WORKLOAD_SUITE_VALIDATION_SCHEMA_VERSION,
    REQUIRED_WORKLOAD_FAMILY_FIELDS,
)


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _warning(warnings: list[dict[str, str]], field: str, message: str) -> None:
    warnings.append({"field": field, "message": message})


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _ids_from_families(families: list[Any]) -> list[str]:
    ids: list[str] = []
    for family in families:
        if isinstance(family, Mapping) and isinstance(family.get("family_id"), str):
            ids.append(family["family_id"])
    return ids


def _validate_claim_boundary(
    boundary: str,
    *,
    field: str,
    errors: list[dict[str, str]],
) -> None:
    lowered = boundary.lower()
    required_terms = ("profiling", "architecture", "performance", "viability", "promotion")
    if not boundary:
        _error(errors, field, "claim_boundary must be non-empty")
        return
    for term in required_terms:
        if term not in lowered:
            _error(errors, field, f"claim_boundary must mention absence of {term}")
    if "not" not in lowered and "does not contain" not in lowered:
        _error(errors, field, "claim_boundary must be an explicit negative boundary")


def _validate_family(
    family: Mapping[str, Any],
    *,
    index: int,
    family_ids: set[str],
    motif_registry: Mapping[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    prefix = f"workload_families[{index}]"
    for field in REQUIRED_WORKLOAD_FAMILY_FIELDS:
        if field not in family:
            _error(errors, f"{prefix}.{field}", "required workload-family field is missing")

    family_id = family.get("family_id")
    if not isinstance(family_id, str) or not family_id:
        _error(errors, f"{prefix}.family_id", "family_id must be a non-empty string")

    for list_field in (
        "representative_programs",
        "depends_on_families",
        "device_relevance",
        "expected_motifs",
        "source_basis",
    ):
        value = family.get(list_field)
        if not isinstance(value, list):
            _error(errors, f"{prefix}.{list_field}", f"{list_field} must be a list")
        elif list_field != "depends_on_families" and not value:
            _error(errors, f"{prefix}.{list_field}", f"{list_field} must be non-empty")
        elif not all(isinstance(item, str) and item for item in value):
            _error(errors, f"{prefix}.{list_field}", f"{list_field} must contain non-empty strings")

    for dep_id in _as_list(family.get("depends_on_families")):
        if isinstance(dep_id, str) and dep_id not in family_ids:
            _error(errors, f"{prefix}.depends_on_families", f"unknown dependency {dep_id!r}")

    for motif_id in _as_list(family.get("expected_motifs")):
        if not isinstance(motif_id, str):
            continue
        motif = motif_registry.get(motif_id)
        if not isinstance(motif, Mapping):
            _error(errors, f"{prefix}.expected_motifs", f"unknown motif {motif_id!r}")
        elif "provisional" not in motif:
            _error(errors, f"motif_registry.{motif_id}.provisional", "motif must declare provisional")
        elif not isinstance(motif.get("provisional"), bool):
            _error(errors, f"motif_registry.{motif_id}.provisional", "provisional must be boolean")
        for field in (
            "measurable_profile_fields",
            "possible_target_relevance",
        ):
            if not isinstance(motif.get(field), list) or not motif.get(field):
                _error(errors, f"motif_registry.{motif_id}.{field}", f"{field} must be a non-empty list")
        for field in ("known_gpu_strength", "known_fpga_risk", "layer2_readiness"):
            if not isinstance(motif.get(field), str) or not motif.get(field):
                _error(errors, f"motif_registry.{motif_id}.{field}", f"{field} must be a non-empty string")
        if motif.get("layer2_readiness") not in {"ready", "provisional"}:
            _error(
                errors,
                f"motif_registry.{motif_id}.layer2_readiness",
                "layer2_readiness must be ready or provisional",
            )

    contract = _as_mapping(family.get("profiling_contract"))
    if contract.get("required_next_layer") != "motif_profiling":
        _error(
            errors,
            f"{prefix}.profiling_contract.required_next_layer",
            "profiling contract must point to motif_profiling",
        )
    expected_fields = contract.get("expected_profile_fields")
    if not isinstance(expected_fields, list):
        _error(
            errors,
            f"{prefix}.profiling_contract.expected_profile_fields",
            "expected_profile_fields must be a list",
        )
    else:
        missing = [
            field
            for field in PROFILING_CONTRACT_REQUIRED_FIELDS
            if field not in expected_fields
        ]
        if missing:
            _error(
                errors,
                f"{prefix}.profiling_contract.expected_profile_fields",
                f"missing required profile fields: {missing}",
            )
    if contract.get("gpu_baseline_required") is not True:
        _error(
            errors,
            f"{prefix}.profiling_contract.gpu_baseline_required",
            "gpu_baseline_required must be true",
        )

    external_reference_programs = family.get("external_reference_programs", [])
    if external_reference_programs and not isinstance(external_reference_programs, list):
        _error(
            errors,
            f"{prefix}.external_reference_programs",
            "external_reference_programs must be a list",
        )
    if isinstance(external_reference_programs, list):
        overlap = sorted(set(external_reference_programs) & set(family.get("representative_programs", [])))
        if overlap:
            _error(
                errors,
                f"{prefix}.external_reference_programs",
                f"external reference programs must not also be representative QE programs: {overlap}",
            )
    if isinstance(external_reference_programs, list) and "perturbo" in external_reference_programs:
        notes = family.get("notes", [])
        if not isinstance(notes, list) or not any("external" in str(note).lower() for note in notes):
            _warning(
                warnings,
                f"{prefix}.external_reference_programs",
                "Perturbo should be documented as an external transport reference",
            )


def _validate_manifest_consistency(
    manifest: Mapping[str, Any] | None,
    *,
    errors: list[dict[str, str]],
) -> None:
    if manifest is None:
        return
    if manifest.get("schema_version") != QE_IC_WORKLOAD_SUITE_MANIFEST_SCHEMA_VERSION:
        _error(errors, "manifest.schema_version", "manifest schema_version is incorrect")
    expected = {
        "suite_artifact": QE_IC_WORKLOAD_SUITE_ARTIFACT,
        "validation_artifact": QE_IC_WORKLOAD_SUITE_VALIDATION_ARTIFACT,
        "readme_artifact": QE_IC_WORKLOAD_SUITE_README_ARTIFACT,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            _error(errors, f"manifest.{field}", f"manifest must reference {value}")
    if manifest.get("artifact_role") != "dse_layer1_workload_suite":
        _error(errors, "manifest.artifact_role", "manifest artifact_role is incorrect")
    if manifest.get("producer") != "dse_v2.workloads.qe_ic":
        _error(errors, "manifest.producer", "manifest producer is incorrect")
    if manifest.get("layer") != "layer1_workload_suite_definition":
        _error(errors, "manifest.layer", "manifest layer is incorrect")
    if manifest.get("downstream_consumers") != DOWNSTREAM_CONSUMERS:
        _error(errors, "manifest.downstream_consumers", "manifest downstream consumers are incorrect")
    _validate_claim_boundary(
        str(manifest.get("claim_boundary", "")),
        field="manifest.claim_boundary",
        errors=errors,
    )


def validate_qe_ic_workload_suite(
    suite: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate suite structure, registry consistency, dependencies, and scenario weights."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not isinstance(suite, Mapping):
        _error(errors, "$", "suite must be a mapping")
        return {
            "schema_version": QE_IC_WORKLOAD_SUITE_VALIDATION_SCHEMA_VERSION,
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "family_count": 0,
            "scenario_count": 0,
            "motif_count": 0,
            "excluded_workflow_count": 0,
        }

    if suite.get("schema_version") != QE_IC_WORKLOAD_SUITE_SCHEMA_VERSION:
        _error(errors, "schema_version", "schema_version is incorrect")
    if suite.get("suite_id") != QE_IC_WORKLOAD_SUITE_ID:
        _error(errors, "suite_id", "suite_id is incorrect")

    families = _as_list(suite.get("workload_families"))
    family_ids = _ids_from_families(families)
    family_id_set = set(family_ids)
    motif_registry = _as_mapping(suite.get("motif_registry"))
    scenarios = _as_list(suite.get("scenarios"))
    excluded_workflows = _as_list(suite.get("excluded_workflows"))

    if not families:
        _error(errors, "workload_families", "workload_families must be non-empty")
    if len(family_ids) != len(set(family_ids)):
        _error(errors, "workload_families", "family_id values must be unique")
    missing_required = [
        family_id
        for family_id in REQUIRED_FIRST_VERSION_FAMILY_IDS
        if family_id not in family_id_set
    ]
    if missing_required:
        _error(
            errors,
            "workload_families",
            f"missing first-version required workload families: {missing_required}",
        )

    for family_id in REQUIRED_FIRST_VERSION_FAMILY_IDS:
        matching = [
            family
            for family in families
            if isinstance(family, Mapping) and family.get("family_id") == family_id
        ]
        if matching and matching[0].get("first_version_required") is not True:
            _error(
                errors,
                f"workload_families.{family_id}.first_version_required",
                "required first-version family must set first_version_required true",
            )

    for index, family in enumerate(families):
        if not isinstance(family, Mapping):
            _error(errors, f"workload_families[{index}]", "family entry must be a mapping")
            continue
        _validate_family(
            family,
            index=index,
            family_ids=family_id_set,
            motif_registry=motif_registry,
            errors=errors,
            warnings=warnings,
        )

    primary_scenario_id = suite.get("primary_scenario_id")
    scenario_ids = {
        scenario.get("scenario_id")
        for scenario in scenarios
        if isinstance(scenario, Mapping)
    }
    if primary_scenario_id not in scenario_ids:
        _error(errors, "primary_scenario_id", "primary_scenario_id must reference a scenario")

    for index, scenario in enumerate(scenarios):
        prefix = f"scenarios[{index}]"
        if not isinstance(scenario, Mapping):
            _error(errors, prefix, "scenario entry must be a mapping")
            continue
        scenario_id = scenario.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            _error(errors, f"{prefix}.scenario_id", "scenario_id must be a non-empty string")
        weights = scenario.get("weights")
        if not isinstance(weights, Mapping):
            _error(errors, f"{prefix}.weights", "scenario weights must be a mapping")
            continue
        unknown_weight_ids = sorted(set(weights) - family_id_set)
        missing_weight_ids = sorted(family_id_set - set(weights))
        if unknown_weight_ids:
            _error(
                errors,
                f"{prefix}.weights",
                f"scenario weights reference unknown families: {unknown_weight_ids}",
            )
        if missing_weight_ids:
            _error(
                errors,
                f"{prefix}.weights",
                f"scenario weights omit families: {missing_weight_ids}",
            )
        if not all(isinstance(value, int | float) and not isinstance(value, bool) for value in weights.values()):
            _error(errors, f"{prefix}.weights", "scenario weights must be numeric")
        elif not math.isclose(float(sum(weights.values())), 1.0, rel_tol=0.0, abs_tol=1e-9):
            _error(errors, f"{prefix}.weights", "scenario weights must sum to 1.0")

    if not excluded_workflows:
        _error(errors, "excluded_workflows", "excluded_workflows must be non-empty")
    for index, row in enumerate(excluded_workflows):
        prefix = f"excluded_workflows[{index}]"
        if not isinstance(row, Mapping):
            _error(errors, prefix, "excluded workflow entry must be a mapping")
            continue
        if not row.get("workflow"):
            _error(errors, f"{prefix}.workflow", "excluded workflow must name a workflow")
        if not row.get("reason"):
            _error(errors, f"{prefix}.reason", "excluded workflow must include a reason")

    downstream = _as_mapping(suite.get("downstream_contract"))
    if downstream.get("next_layer") != "motif_profiling":
        _error(errors, "downstream_contract.next_layer", "next layer must be motif_profiling")
    if downstream.get("required_consumers") != DOWNSTREAM_CONSUMERS:
        _error(
            errors,
            "downstream_contract.required_consumers",
            "downstream required consumers are incorrect",
        )

    _validate_claim_boundary(
        str(suite.get("claim_boundary", "")),
        field="claim_boundary",
        errors=errors,
    )
    if suite.get("claim_boundary") != CLAIM_BOUNDARY:
        _warning(
            warnings,
            "claim_boundary",
            "claim_boundary differs from the canonical Layer-1 wording",
        )

    _validate_manifest_consistency(manifest, errors=errors)

    status = "passed" if not errors else "failed"
    return {
        "schema_version": QE_IC_WORKLOAD_SUITE_VALIDATION_SCHEMA_VERSION,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "family_count": len(families),
        "scenario_count": len(scenarios),
        "motif_count": len(motif_registry),
        "excluded_workflow_count": len(excluded_workflows),
        "artifact_names": list(QE_IC_ARTIFACTS),
        "manifest_artifact": QE_IC_WORKLOAD_SUITE_MANIFEST_ARTIFACT,
    }
