from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .interfaces import DesignPoint


@dataclass(frozen=True)
class DesignSpaceSpec:
    schema_version: str
    design_space_id: str
    authority_stage: dict[str, Any]
    design_axes: dict[str, list[str]]


@dataclass(frozen=True)
class FamilySupportStatus:
    family: str
    runtime_support_status: str
    stage_a_status: str
    runtime_executor_backed: bool
    runtime_projection_family: str


def load_design_space_spec(path: Path | str) -> DesignSpaceSpec:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    architecture_ir = payload["architecture_ir"]
    return DesignSpaceSpec(
        schema_version=payload["schema_version"],
        design_space_id=payload["design_space_id"],
        authority_stage=dict(payload["authority_stage"]),
        design_axes={key: list(value) for key, value in architecture_ir["design_axes"].items()},
    )


def make_design_point(
    spec: DesignSpaceSpec,
    family: str,
    diag_policy: str,
    offload_scope: str,
    resident_policy: str,
    partition_strategy: str,
) -> DesignPoint:
    if family not in spec.design_axes["family"]:
        raise ValueError(f"unknown architecture family: {family}")
    return DesignPoint(
        family=family,
        diag_policy=diag_policy,
        offload_scope=offload_scope,
        resident_policy=resident_policy,
        partition_strategy=partition_strategy,
    )


def family_support_status(spec: DesignSpaceSpec, family: str) -> FamilySupportStatus:
    if family not in spec.design_axes["family"]:
        raise ValueError(f"unknown architecture family: {family}")
    if family in ("F4", "F5", "custom"):
        return FamilySupportStatus(
            family=family,
            runtime_support_status="projection_scaffold",
            stage_a_status="projection_only",
            runtime_executor_backed=False,
            runtime_projection_family="F2",
        )
    return FamilySupportStatus(
        family=family,
        runtime_support_status="runtime_family_projection",
        stage_a_status="evidence_only",
        runtime_executor_backed=True,
        runtime_projection_family=family,
    )
