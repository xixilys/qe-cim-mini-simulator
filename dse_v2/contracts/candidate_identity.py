"""Canonical candidate-identity sidecars for Step2+ queues.

The identity is intentionally domain-neutral: workload-specific kernels or
physics facts may appear only as node IDs/sets already chosen by adapters or
profiles.  Evidence status is excluded from the hash; target-platform intent is
included so FPGA and ASIC hard-gate queues cannot share an ambiguous identity.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


CANDIDATE_IDENTITY_SCHEMA_VERSION = "dse.candidate_identity.v1"

CANDIDATE_IDENTITY_REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "candidate_id",
    "deployment_boundary",
    "host_device_partition",
    "accelerated_sets",
    "cpu_retained_sets",
    "architecture_template_parameters",
    "mapping_layout",
    "runtime_co_scheduling",
    "descriptor_granularity",
    "fallback_policy",
    "target_platform",
    "identity_hash",
)


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    elif hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _identity_hash(payload: Mapping[str, Any]) -> str:
    data = dict(payload)
    data.pop("identity_hash", None)
    encoded = json.dumps(
        _json_safe(data),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _stable_string_list(values: Iterable[Any]) -> List[str]:
    return sorted({str(value) for value in values if value not in (None, "")})


def _deployment_boundary(
    *,
    accelerated_node_ids: Sequence[str],
    cpu_retained_node_ids: Sequence[str],
    explicit: Optional[str],
) -> str:
    if explicit:
        return explicit
    if accelerated_node_ids and cpu_retained_node_ids:
        return "host_device_hybrid"
    if accelerated_node_ids:
        return "device_resident_candidate"
    return "host_only_candidate"


def build_candidate_identity(
    *,
    candidate_id: str,
    architecture_id: str,
    mapping_candidate_id: str,
    mapping_id: str,
    design_point_id: str,
    node_to_target: Mapping[str, Any],
    scheduling_policy: str,
    simulation_backend: str,
    architecture_family: Optional[str] = None,
    architecture_template_parameters: Optional[Mapping[str, Any]] = None,
    data_placement: Optional[Mapping[str, Any]] = None,
    runtime_schedule_id: Optional[str] = None,
    descriptor_granularity: Optional[str] = None,
    fallback_policy: Optional[Mapping[str, Any]] = None,
    deployment_boundary: Optional[str] = None,
    target_platform: Optional[Mapping[str, Any]] = None,
    accelerated_node_ids: Optional[Sequence[Any]] = None,
    cpu_retained_node_ids: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Build a complete, hash-bound candidate identity sidecar."""

    inferred_accelerated_node_ids = _stable_string_list(
        node_id
        for node_id, target in node_to_target.items()
        if str(target or "").lower() not in {"", "host", "cpu"}
    )
    inferred_cpu_retained_node_ids = _stable_string_list(
        node_id
        for node_id, target in node_to_target.items()
        if str(target or "").lower() in {"", "host", "cpu"}
    )
    accelerated_node_ids = (
        _stable_string_list(accelerated_node_ids)
        if accelerated_node_ids is not None
        else inferred_accelerated_node_ids
    )
    cpu_retained_node_ids = (
        _stable_string_list(cpu_retained_node_ids)
        if cpu_retained_node_ids is not None
        else inferred_cpu_retained_node_ids
    )
    arch_params = dict(architecture_template_parameters or {})
    arch_params.setdefault("architecture_id", architecture_id)
    if architecture_family:
        arch_params.setdefault("architecture_family", architecture_family)

    platform = dict(target_platform or {})
    platform.setdefault("simulation_backend", simulation_backend)

    identity: Dict[str, Any] = {
        "schema_version": CANDIDATE_IDENTITY_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "deployment_boundary": _deployment_boundary(
            accelerated_node_ids=accelerated_node_ids,
            cpu_retained_node_ids=cpu_retained_node_ids,
            explicit=deployment_boundary,
        ),
        "host_device_partition": {
            "accelerated_node_ids": accelerated_node_ids,
            "cpu_retained_node_ids": cpu_retained_node_ids,
        },
        "accelerated_sets": accelerated_node_ids,
        "cpu_retained_sets": cpu_retained_node_ids,
        "architecture_template_parameters": arch_params,
        "mapping_layout": {
            "mapping_candidate_id": mapping_candidate_id,
            "mapping_id": mapping_id,
            "node_to_target": dict(node_to_target),
            "data_placement": dict(data_placement or {}),
        },
        "runtime_co_scheduling": {
            "scheduling_policy": scheduling_policy or "static",
            "runtime_schedule_id": runtime_schedule_id or f"runtime::{design_point_id}",
        },
        "descriptor_granularity": descriptor_granularity or "graph_node_command",
        "fallback_policy": dict(fallback_policy or {"unsupported_ops": "host_fallback_visible"}),
        "target_platform": platform,
    }
    identity["identity_hash"] = _identity_hash(identity)
    return identity


def identity_for_target(
    identity: Mapping[str, Any],
    *,
    deployment_target: str,
) -> Dict[str, Any]:
    """Return an identity copy rebound to a concrete FPGA/ASIC target."""

    payload = dict(_json_safe(identity))
    platform = dict(payload.get("target_platform", {}) if isinstance(payload.get("target_platform", {}), Mapping) else {})
    platform["deployment_target"] = deployment_target
    payload["target_platform"] = platform
    payload["identity_hash"] = _identity_hash(payload)
    return payload


def validate_candidate_identity(
    identity: Any,
    *,
    field_prefix: str,
) -> List[Dict[str, Any]]:
    """Return structured validation errors for a candidate identity sidecar."""

    errors: List[Dict[str, Any]] = []
    if not isinstance(identity, Mapping):
        return [{"field": field_prefix, "message": "candidate_identity must be an object"}]
    for field in CANDIDATE_IDENTITY_REQUIRED_FIELDS:
        if field not in identity or identity.get(field) in (None, ""):
            errors.append({"field": f"{field_prefix}.{field}", "message": "required"})
    if identity.get("schema_version") != CANDIDATE_IDENTITY_SCHEMA_VERSION:
        errors.append({"field": f"{field_prefix}.schema_version", "message": "unexpected candidate_identity schema"})
    partition = identity.get("host_device_partition")
    if not isinstance(partition, Mapping):
        errors.append({"field": f"{field_prefix}.host_device_partition", "message": "must be an object"})
    else:
        if not isinstance(partition.get("accelerated_node_ids"), list):
            errors.append({"field": f"{field_prefix}.host_device_partition.accelerated_node_ids", "message": "must be a list"})
        if not isinstance(partition.get("cpu_retained_node_ids"), list):
            errors.append({"field": f"{field_prefix}.host_device_partition.cpu_retained_node_ids", "message": "must be a list"})
    for field in ("architecture_template_parameters", "mapping_layout", "runtime_co_scheduling", "fallback_policy", "target_platform"):
        if field in identity and not isinstance(identity.get(field), Mapping):
            errors.append({"field": f"{field_prefix}.{field}", "message": "must be an object"})
    expected_hash = _identity_hash(identity)
    actual_hash = str(identity.get("identity_hash") or "")
    if actual_hash and actual_hash != expected_hash:
        errors.append({"field": f"{field_prefix}.identity_hash", "message": "must match candidate_identity payload"})
    elif actual_hash and not actual_hash.startswith("sha256:"):
        errors.append({"field": f"{field_prefix}.identity_hash", "message": "must use sha256 prefix"})
    return errors


__all__ = [
    "CANDIDATE_IDENTITY_REQUIRED_FIELDS",
    "CANDIDATE_IDENTITY_SCHEMA_VERSION",
    "build_candidate_identity",
    "identity_for_target",
    "validate_candidate_identity",
]
