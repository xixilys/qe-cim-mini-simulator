#!/usr/bin/env python3
"""Frozen DFT reference-profile contracts kept outside generic core.

The domain-neutral workload package may carry an opaque profile payload, but the
DFT/QE/VASP semantics in this file are owned by the reference workload adapter.
Core IR/control-plane code must not import this module or require these fields.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Sequence

from dse_v2.core.workload.profiles import WorkloadProfile


DFT_PROFILE_SCHEMA = "dse.dft.profile.v1"
DFT_PROFILE_METADATA_SCHEMA = "dse.dft.profile_metadata.v1"
DFT_DOMAIN_VALIDATION_SCHEMA = "dse.dft.domain_validation.v1"
DFT_DOMAIN_PHYSICS_VALIDATION_SCHEMA = "dse.dft.domain_physics_validation.v1"
DFT_CONFIG_PROFILE_SCHEMA = "dse.dft.config_profile.v1"
DFT_PROFILE_CONTRACT_VERSION = "2026-05-18.research-grade-closure"

DFT_PROFILE_OWNED_ARTIFACTS = {
    "dft_config": "dft_config.json",
    "profile_metadata": "dft_profile_metadata.json",
    "domain_physics_validation": "domain_physics_validation.json",
}

DFT_DOMAIN_VALIDATION_REQUIRED_FIELDS = [
    "schema_version",
    "timing_only_allowed",
    "numerical_correctness_claimed",
    "correctness_claim_requires_external_domain_evidence",
    "domain_physics_validation_artifact",
    "unclaimed_domain_correctness",
]

DFT_CORE_SEPARATION_CONTRACT = {
    "schema_version": DFT_PROFILE_METADATA_SCHEMA,
    "contract_version": DFT_PROFILE_CONTRACT_VERSION,
    "owner": "dse_v2.reference_workloads",
    "core_must_import": False,
    "core_required_fields": [],
    "profile_owned_fields": [
        "dft_config",
        "profile_metadata",
        "domain_validation",
        "domain_physics_validation",
        "source_program",
        "claim_boundary",
    ],
    "generic_bridge_fields": [
        "workload_family",
        "profile_id",
        "profile_version",
        "accepted_source_kinds",
        "graph_pattern",
        "lowering_policy",
        "default_claim_boundary",
    ],
    "claim_boundary": (
        "DFT profile/config/domain-validation semantics are adapter-owned; "
        "generic core may transport the profile payload but must not require or "
        "interpret DFT/QE/VASP-specific fields."
    ),
}


def dft_domain_validation_contract(*, source_program: str = "qe_pw") -> Dict[str, Any]:
    """Return the frozen DFT domain-validation payload for profile metadata."""

    return {
        "schema_version": DFT_DOMAIN_VALIDATION_SCHEMA,
        "contract_version": DFT_PROFILE_CONTRACT_VERSION,
        "source_program": source_program,
        "timing_only_allowed": True,
        "numerical_correctness_claimed": False,
        "correctness_claim_requires_external_domain_evidence": True,
        "domain_physics_validation_artifact": DFT_PROFILE_OWNED_ARTIFACTS["domain_physics_validation"],
        "domain_physics_validation_schema": DFT_DOMAIN_PHYSICS_VALIDATION_SCHEMA,
        "step_ownership": {
            "step1": "source-fact/profile metadata only",
            "step2": "candidate/domain-policy hints only",
            "step3": "generic simulation execution only",
            "step4": "domain/numerical adjudication and claim validation",
            "step5": "claim presentation/reporting",
        },
        "unclaimed_domain_correctness": (
            "DFT numerical/physics correctness, convergence, pseudopotential validity, "
            "and scientific result equivalence are not claimed by Step1 workload "
            "characterization or Step3 timing evidence."
        ),
        "required_external_domain_evidence": [
            "reference_energy_or_residual_trace",
            "convergence_tolerance_record",
            "pseudopotential/input_provenance",
        ],
    }


def dft_profile_metadata_contract(*, source_program: str = "qe_pw") -> Dict[str, Any]:
    """Return profile-owned metadata that can be embedded under domain_metadata.dft."""

    return {
        **DFT_CORE_SEPARATION_CONTRACT,
        "source_program": source_program,
        "owned_artifacts": dict(DFT_PROFILE_OWNED_ARTIFACTS),
        "domain_validation_schema": DFT_DOMAIN_VALIDATION_SCHEMA,
        "domain_physics_validation_schema": DFT_DOMAIN_PHYSICS_VALIDATION_SCHEMA,
    }


def dft_config_profile_schema() -> Dict[str, Any]:
    """Return the frozen DFT config/profile schema description.

    This is a lightweight executable schema used by tests and DFT scripts; it is
    intentionally not registered in the generic core schema registry.
    """

    return {
        "schema_version": DFT_CONFIG_PROFILE_SCHEMA,
        "contract_version": DFT_PROFILE_CONTRACT_VERSION,
        "owner": "dse_v2.reference_workloads",
        "required_fields": ["schema_version", "profile_id", "source_program", "claim_boundary"],
        "optional_fields": ["input_parameters", "source_facts", "domain_validation", "profile_metadata"],
        "claim_boundary": "DFT config/profile data is profile-owned adapter input, not generic core IR.",
    }


def attach_dft_profile_contract(
    profile_payload: Mapping[str, Any],
    *,
    source_program: str = "qe_pw",
) -> Dict[str, Any]:
    """Return a profile payload with frozen DFT-owned schema metadata attached."""

    payload = dict(profile_payload)
    payload["schema_version"] = str(payload.get("schema_version", DFT_PROFILE_SCHEMA))
    payload["domain_validation"] = {
        **dft_domain_validation_contract(source_program=source_program),
        **dict(payload.get("domain_validation", {}) or {}),
    }
    # Preserve the frozen schema marker even if an older payload overrode fields.
    payload["domain_validation"]["schema_version"] = DFT_DOMAIN_VALIDATION_SCHEMA
    payload["domain_validation"]["contract_version"] = DFT_PROFILE_CONTRACT_VERSION
    plugin_metadata = dict(payload.get("plugin_metadata", {}) or {})
    plugin_metadata.update(dft_profile_metadata_contract(source_program=source_program))
    plugin_metadata["reference_only"] = True
    plugin_metadata["domain"] = "dft"
    payload["plugin_metadata"] = plugin_metadata
    return payload


def validate_dft_profile_contract(profile: WorkloadProfile | Mapping[str, Any]) -> Dict[str, Any]:
    """Validate that a DFT profile keeps DFT semantics in profile-owned fields."""

    payload = profile.to_dict() if isinstance(profile, WorkloadProfile) else dict(profile)
    errors = []
    warnings = []
    if payload.get("schema_version") not in {"dse.workload_profile.v1", DFT_PROFILE_SCHEMA}:
        warnings.append({"field": "schema_version", "message": "unexpected profile schema marker"})
    if payload.get("workload_family") != "dft":
        errors.append({"field": "workload_family", "message": "DFT profile must identify workload_family=dft"})
    domain_validation = payload.get("domain_validation", {}) if isinstance(payload.get("domain_validation"), Mapping) else {}
    for field in DFT_DOMAIN_VALIDATION_REQUIRED_FIELDS:
        if field not in domain_validation:
            errors.append({"field": f"domain_validation.{field}", "message": "required DFT domain-validation field missing"})
    if domain_validation.get("schema_version") != DFT_DOMAIN_VALIDATION_SCHEMA:
        errors.append({"field": "domain_validation.schema_version", "message": "DFT domain-validation schema is not frozen"})
    if domain_validation.get("numerical_correctness_claimed") is not False:
        errors.append({"field": "domain_validation.numerical_correctness_claimed", "message": "DFT profile must not claim domain correctness from timing metadata"})
    plugin_metadata = payload.get("plugin_metadata", {}) if isinstance(payload.get("plugin_metadata"), Mapping) else {}
    if plugin_metadata.get("owner") != "dse_v2.reference_workloads":
        errors.append({"field": "plugin_metadata.owner", "message": "DFT profile contract owner must remain outside core"})
    if plugin_metadata.get("core_must_import") is not False:
        errors.append({"field": "plugin_metadata.core_must_import", "message": "core must not import DFT profile contract"})
    if plugin_metadata.get("core_required_fields") not in ([], tuple()):
        errors.append({"field": "plugin_metadata.core_required_fields", "message": "DFT profile must not add core-required fields"})
    return {
        "schema_version": "dse.dft.profile_contract_validation.v1",
        "profile_id": payload.get("profile_id"),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "contract_hash": _stable_hash({
            "domain_validation": domain_validation,
            "plugin_metadata": {key: plugin_metadata.get(key) for key in sorted(DFT_CORE_SEPARATION_CONTRACT)},
        }),
    }


def profile_contract_from_package(package_payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract DFT profile-owned metadata from a WorkloadPackage-like payload."""

    domain_metadata = package_payload.get("domain_metadata", {}) if isinstance(package_payload.get("domain_metadata"), Mapping) else {}
    dft_metadata = domain_metadata.get("dft", {}) if isinstance(domain_metadata.get("dft"), Mapping) else {}
    profile_metadata = dft_metadata.get("profile_metadata", {}) if isinstance(dft_metadata.get("profile_metadata"), Mapping) else {}
    return {
        "schema_version": "dse.dft.package_profile_contract_view.v1",
        "has_dft_domain_metadata": bool(dft_metadata),
        "profile_metadata": dict(profile_metadata),
        "top_level_dft_keys": sorted(key for key in package_payload if str(key).startswith(("dft", "qe", "vasp"))),
        "core_required_fields": list(profile_metadata.get("core_required_fields", []) or []),
        "claim_boundary": profile_metadata.get("claim_boundary"),
    }


def _stable_hash(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    import hashlib

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()
