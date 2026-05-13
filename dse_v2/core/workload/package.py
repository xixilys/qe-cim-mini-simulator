#!/usr/bin/env python3
"""Domain-neutral workload package contract for generic DSE ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload.profiles import (
    FULL_CLAIM_BOUNDARIES,
    required_coverage_from_profile,
    resolve_profile_metadata,
)


@dataclass
class WorkloadPackage:
    """Versioned ingestion unit wrapping a ComputeGraph and profile/importer metadata."""

    workload_id: str
    workload_family: str
    graph: ComputeGraph
    source: Dict[str, Any] = field(default_factory=dict)
    profile: Dict[str, Any] = field(default_factory=dict)
    importer: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    calibration: Dict[str, Any] = field(default_factory=dict)
    domain_metadata: Dict[str, Any] = field(default_factory=dict)
    workflow: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "dse.workload_package.v1"

    @property
    def profile_id(self) -> str:
        return str(self.profile.get("profile_id", self.workflow.get("profile_id", self.workload_family)))

    @property
    def profile_version(self) -> str:
        return str(self.profile.get("profile_version", self.workflow.get("profile_version", "v1")))

    @property
    def importer_id(self) -> str:
        return str(self.importer.get("importer_id", "unknown"))

    @property
    def importer_version(self) -> str:
        return str(self.importer.get("importer_version", "unknown"))

    @property
    def claim_boundary(self) -> str:
        return str(self.importer.get("claim_boundary", "full_workload"))

    def is_full_workload(self) -> bool:
        return self.claim_boundary in FULL_CLAIM_BOUNDARIES

    def resolved_profile(self) -> Dict[str, Any]:
        override = dict(self.profile or self.workflow or {})
        return resolve_profile_metadata(self.profile_id or self.workload_family, override)

    def resolved_workflow(self) -> Dict[str, Any]:
        return self.resolved_profile()

    def required_coverage(self) -> Dict[str, Any]:
        workflow = self.resolved_workflow()
        try:
            order = self.graph.topological_sort()
        except Exception:
            order = []
        coverage = required_coverage_from_profile(
            self.profile_id or self.workload_family,
            workflow,
            self.graph.nodes.keys(),
            order,
        )
        missing = [item for item in coverage if item not in self.graph.nodes and item not in self.graph.regions]
        return {
            "schema_version": "dse.workload_required_coverage.v1",
            "workload_id": self.workload_id,
            "workload_family": self.workload_family,
            "profile_id": self.profile_id,
            "required_coverage": coverage,
            "missing_from_source_graph": missing,
            "coverage_resolved": not missing,
        }

    def validate(self) -> Dict[str, Any]:
        errors = []
        warnings = []
        if not self.workload_id:
            errors.append({"field": "workload_id", "message": "workload_id is required"})
        if not self.workload_family:
            errors.append({"field": "workload_family", "message": "workload_family is required"})
        if not self.profile_id:
            errors.append({"field": "profile.profile_id", "message": "profile_id is required"})
        if not self.importer_id or self.importer_id == "unknown":
            errors.append({"field": "importer.importer_id", "message": "importer_id is required"})
        if not self.importer_version or self.importer_version == "unknown":
            warnings.append({"field": "importer.importer_version", "message": "importer_version is recommended"})
        if not self.claim_boundary:
            warnings.append({"field": "importer.claim_boundary", "message": "claim_boundary defaulted to full_workload"})
        profile = self.resolved_profile()
        if not profile.get("workload_family"):
            errors.append({"field": "profile.workload_family", "message": "profile workload_family is required"})
        if not profile.get("lowering_policy"):
            errors.append({"field": "profile.lowering_policy", "message": "profile lowering_policy is required"})
        if not profile.get("domain_validation"):
            warnings.append({"field": "profile.domain_validation", "message": "domain validation boundary is recommended"})
        coverage = self.required_coverage()
        if self.is_full_workload() and not coverage.get("coverage_resolved", False):
            errors.append({
                "field": "workflow.required_coverage",
                "message": "required coverage does not resolve to source graph nodes or regions",
                "missing": coverage.get("missing_from_source_graph", []),
            })
        graph_report = self.graph.validate()
        for issue in graph_report.get("errors", []):
            errors.append({"field": f"graph.{issue.get('field')}", "message": issue.get("message"), "object_id": issue.get("object_id")})
        for issue in graph_report.get("warnings", []):
            warnings.append({"field": f"graph.{issue.get('field')}", "message": issue.get("message"), "object_id": issue.get("object_id")})
        return {
            "schema_version": "dse.workload_package_validation.v1",
            "workload_id": self.workload_id,
            "profile_id": self.profile_id,
            "importer_id": self.importer_id,
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "graph_validation": graph_report,
            "profile": profile,
            "workflow": profile,
            "required_coverage": coverage,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workload_id": self.workload_id,
            "workload_family": self.workload_family,
            "source": dict(self.source),
            "profile": self.resolved_profile(),
            "importer": dict(self.importer),
            "graph": self.graph.to_dict(),
            "constraints": dict(self.constraints),
            "calibration": dict(self.calibration),
            "domain_metadata": dict(self.domain_metadata),
            "workflow": self.resolved_profile(),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> WorkloadPackage:
        graph_payload = data.get("graph", {})
        graph = graph_payload if isinstance(graph_payload, ComputeGraph) else ComputeGraph.from_dict(graph_payload if isinstance(graph_payload, Mapping) else {})
        return WorkloadPackage(
            schema_version=str(data.get("schema_version", "dse.workload_package.v1")),
            workload_id=str(data.get("workload_id", "")),
            workload_family=str(data.get("workload_family", "")),
            source=dict(data.get("source", {}) or {}),
            profile=dict(data.get("profile", data.get("workflow", {})) or {}),
            importer=dict(data.get("importer", {}) or {}),
            graph=graph,
            constraints=dict(data.get("constraints", {}) or {}),
            calibration=dict(data.get("calibration", {}) or {}),
            domain_metadata=dict(data.get("domain_metadata", {}) or {}),
            workflow=dict(data.get("workflow", {}) or {}),
        )


def package_from_graph(
    graph: ComputeGraph,
    *,
    workload_id: Optional[str] = None,
    workload_family: str = "custom",
    profile_id: Optional[str] = None,
    profile_version: str = "v1",
    importer_id: str = "generic_json",
    importer_version: str = "v1",
    claim_boundary: str = "full_workload",
    source_kind: str = "hand_authored",
    source_path: Optional[str] = None,
    domain_metadata: Optional[Mapping[str, Any]] = None,
    profile: Optional[Mapping[str, Any]] = None,
    workflow: Optional[Mapping[str, Any]] = None,
    required_coverage: Optional[Mapping[str, Any] | list[str]] = None,
) -> WorkloadPackage:
    resolved_profile_id = profile_id or workload_family
    profile_override = dict(profile or workflow or {})
    profile_payload = resolve_profile_metadata(resolved_profile_id, profile_override)
    if isinstance(required_coverage, list):
        profile_payload["required_coverage"] = [str(item) for item in required_coverage]
    profile_payload["profile_id"] = str(profile_payload.get("profile_id", resolved_profile_id))
    profile_payload["profile_version"] = str(profile_payload.get("profile_version", profile_version))
    resolved_importer_id = importer_id
    resolved_importer_version = importer_version
    importer_payload = {
        "importer_id": resolved_importer_id,
        "importer_version": resolved_importer_version,
        "claim_boundary": claim_boundary,
    }
    source_payload = {"kind": source_kind, "provenance": "constructed in Python"}
    if source_path is not None:
        source_payload["path"] = str(source_path)
    graph.metadata["profile_id"] = profile_payload["profile_id"]
    graph.metadata["workload_family"] = workload_family
    graph.metadata["profile"] = profile_payload
    graph.metadata["workflow"] = profile_payload
    graph.metadata["importer_id"] = resolved_importer_id
    return WorkloadPackage(
        workload_id=workload_id or graph.graph_id,
        workload_family=workload_family,
        graph=graph,
        source=source_payload,
        profile=profile_payload,
        importer=importer_payload,
        domain_metadata=dict(domain_metadata or {}),
        workflow=profile_payload,
    )
