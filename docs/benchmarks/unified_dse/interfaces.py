from __future__ import annotations

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
    "qe_tolerance_schema_id",
    "accounting_boundary_id",
    "fairness_policy_id",
    "power_boundary_id",
    "observability_contract_id",
)


def _copy_required(payload: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload[key] for key in keys}


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

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkloadDescriptor":
        field_names = tuple(field.name for field in fields(cls))
        return cls(**_copy_required(payload, field_names))

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


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
            payload.update(self.extra_fields)
        return payload
