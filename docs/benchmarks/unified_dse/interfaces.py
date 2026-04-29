from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields
from typing import Any, Mapping


DESIGN_POINT_IDENTITY_KEYS = (
    "family",
    "diag_policy",
    "offload_scope",
    "resident_policy",
    "partition_strategy",
)

WORKLOAD_IDENTITY_KEYS = (
    "workload_id",
    "workload_group_id",
    "domain",
    "app_adapter",
    "qe_tolerance_schema_id",
    "accounting_boundary_id",
    "fairness_policy_id",
    "power_boundary_id",
    "observability_contract_id",
)

WORKLOAD_DESCRIPTOR_CORE_KEYS = (
    "schema_version",
    "workload_id",
    "workload_group_id",
    "domain",
    "app_adapter",
    "qe_tolerance_schema_id",
    "accounting_boundary_id",
    "fairness_policy_id",
    "power_boundary_id",
    "observability_contract_id",
    "signature_id",
    "property_target",
    "pseudopotential_family",
    "solver_path_class",
    "workload_topology",
    "post_scf_extension_level",
    "projector_pressure",
    "nonlocal_pressure",
    "dimension_n",
    "dimension_m",
    "scf_iterations",
)

EVALUATION_RESULT_CORE_KEYS = (
    "workload",
    "design_point",
    "backend",
    "result_status",
    "source_kind",
    "metrics",
    "authority_scope",
    "promotion_state",
    "final_public_family_winner",
)


def _copy_required(payload: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload[key] for key in keys}


def _workload_defaults(payload: Mapping[str, Any]) -> dict[str, Any]:
    workload_id = str(payload.get("workload_id", "unknown_workload"))
    explicit_domain = payload.get("domain")
    explicit_adapter = payload.get("app_adapter") or payload.get("adapter")
    qe_signature_keys = (
        "qe_tolerance_schema_id",
        "pseudopotential_family",
        "solver_path_class",
        "projector_pressure",
        "nonlocal_pressure",
    )
    has_qe_signature = any(
        payload.get(key) not in (None, "", "not_applicable")
        for key in qe_signature_keys
    )
    domain_implies_qe = (
        explicit_domain in {"dft", "qe"}
        and explicit_adapter in (None, "", "not_applicable", "qe")
    )
    is_qe = explicit_adapter == "qe" or domain_implies_qe or has_qe_signature
    domain = explicit_domain or ("dft" if is_qe else "generic")
    app_adapter = explicit_adapter or ("qe" if is_qe else "generic_trace")
    qe_tolerance_schema_id = (
        payload.get("qe_tolerance_schema_id")
        or (payload.get("correctness_contract_id") if is_qe else None)
        or "not_applicable"
    )
    return {
        "schema_version": payload.get("schema_version", "unified_dse_workload_descriptor_v0"),
        "workload_id": workload_id,
        "workload_group_id": payload.get("workload_group_id", "default_workload_group"),
        "domain": domain,
        "app_adapter": app_adapter,
        "qe_tolerance_schema_id": qe_tolerance_schema_id,
        "accounting_boundary_id": payload.get("accounting_boundary_id", "not_applicable"),
        "fairness_policy_id": payload.get("fairness_policy_id", "not_applicable"),
        "power_boundary_id": payload.get("power_boundary_id", "not_applicable"),
        "observability_contract_id": payload.get("observability_contract_id", "not_applicable"),
        "signature_id": payload.get("signature_id", workload_id),
        "property_target": payload.get("property_target", "unknown"),
        "pseudopotential_family": payload.get("pseudopotential_family", "not_applicable"),
        "solver_path_class": payload.get("solver_path_class", "not_applicable"),
        "workload_topology": payload.get("workload_topology", "unknown"),
        "post_scf_extension_level": payload.get("post_scf_extension_level", "not_applicable"),
        "projector_pressure": payload.get("projector_pressure", "not_applicable"),
        "nonlocal_pressure": payload.get("nonlocal_pressure", "not_applicable"),
        "dimension_n": int(payload.get("dimension_n", payload.get("npw", 0)) or 0),
        "dimension_m": int(payload.get("dimension_m", payload.get("m", 0)) or 0),
        "scf_iterations": int(payload.get("scf_iterations", 1) or 1),
    }


@dataclass(frozen=True)
class DesignPoint:
    family: str
    diag_policy: str
    offload_scope: str
    resident_policy: str
    partition_strategy: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DesignPoint":
        return cls(**_copy_required(payload, DESIGN_POINT_IDENTITY_KEYS))

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in DESIGN_POINT_IDENTITY_KEYS}


@dataclass(frozen=True)
class WorkloadDescriptor:
    schema_version: str
    workload_id: str
    workload_group_id: str
    domain: str
    app_adapter: str
    qe_tolerance_schema_id: str
    accounting_boundary_id: str
    fairness_policy_id: str
    power_boundary_id: str
    observability_contract_id: str
    signature_id: str
    property_target: str
    pseudopotential_family: str
    solver_path_class: str
    workload_topology: str
    post_scf_extension_level: str
    projector_pressure: str
    nonlocal_pressure: str
    dimension_n: int
    dimension_m: int
    scf_iterations: int
    extra_fields: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkloadDescriptor":
        defaults = _workload_defaults(payload)
        extra_fields = {
            key: deepcopy(value)
            for key, value in payload.items()
            if key not in WORKLOAD_DESCRIPTOR_CORE_KEYS
        }
        return cls(
            **_copy_required(defaults, WORKLOAD_DESCRIPTOR_CORE_KEYS),
            extra_fields=extra_fields or None,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name != "extra_fields"
        }
        if self.extra_fields is not None:
            payload.update(deepcopy(self.extra_fields))
        return payload


@dataclass(frozen=True)
class EvaluationResult:
    workload: WorkloadDescriptor
    design_point: DesignPoint
    backend: str
    result_status: str
    source_kind: str
    metrics: dict[str, Any]
    authority_scope: str
    promotion_state: str
    final_public_family_winner: str | None
    extra_fields: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvaluationResult":
        extra_fields = {
            key: deepcopy(value)
            for key, value in payload.items()
            if key not in EVALUATION_RESULT_CORE_KEYS
        }
        return cls(
            workload=WorkloadDescriptor.from_dict(payload["workload"]),
            design_point=DesignPoint.from_dict(payload["design_point"]),
            backend=payload["backend"],
            result_status=payload["result_status"],
            source_kind=payload["source_kind"],
            metrics=dict(payload["metrics"]),
            authority_scope=payload["authority_scope"],
            promotion_state=payload["promotion_state"],
            final_public_family_winner=payload["final_public_family_winner"],
            extra_fields=extra_fields or None,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "workload": self.workload.to_dict(),
            "design_point": self.design_point.to_dict(),
            "backend": self.backend,
            "result_status": self.result_status,
            "source_kind": self.source_kind,
            "metrics": dict(self.metrics),
            "authority_scope": self.authority_scope,
            "promotion_state": self.promotion_state,
            "final_public_family_winner": self.final_public_family_winner,
        }
        if self.extra_fields is not None:
            payload.update(deepcopy(self.extra_fields))
        return payload
