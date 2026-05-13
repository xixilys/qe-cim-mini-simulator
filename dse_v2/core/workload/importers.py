#!/usr/bin/env python3
"""Workload importer plugins for profile-driven DSE ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload.package import WorkloadPackage, package_from_graph
from dse_v2.core.workload.profiles import WorkloadProfile, default_profile_registry, resolve_profile_metadata


class WorkloadImporter:
    importer_id = "base"
    importer_version = "v1"
    supported_source_kinds: List[str] = []
    compatible_profiles: List[str] = []

    def import_workload(
        self,
        source: Any,
        *,
        profile: WorkloadProfile | Mapping[str, Any],
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> WorkloadPackage:
        raise NotImplementedError

    def validate_workload_package(self, package: WorkloadPackage) -> Dict[str, Any]:
        return package.validate()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "importer_id": self.importer_id,
            "importer_version": self.importer_version,
            "supported_source_kinds": list(self.supported_source_kinds),
            "compatible_profiles": list(self.compatible_profiles),
        }

    # Deprecated compatibility with older scripts that called the importer an
    # adapter.  New code should call import_workload(profile=...).
    def emit_workload_package(self, source: Any, parameters: Optional[Mapping[str, Any]] = None) -> WorkloadPackage:
        parameters = dict(parameters or {})
        profile_id = str(parameters.get("profile_id", parameters.get("workload_family", self.compatible_profiles[0] if self.compatible_profiles else "dynamic_custom")))
        profile = default_profile_registry().get(profile_id)
        return self.import_workload(source, profile=profile, parameters=parameters)

    def default_mapping_policies(self, package: WorkloadPackage) -> List[Dict[str, Any]]:
        profile = package.resolved_profile()
        policies = profile.get("default_mapping_policies", []) or ["host-baseline", "capability-greedy"]
        return [{"policy_id": str(policy), "owner": "profile"} for policy in policies]

    def domain_report_metrics(self, package: WorkloadPackage, result: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        return {}


def _profile_payload(profile: WorkloadProfile | Mapping[str, Any]) -> Dict[str, Any]:
    if isinstance(profile, WorkloadProfile):
        return profile.to_dict()
    return dict(profile)


@dataclass
class ImporterRegistry:
    importers: Dict[str, WorkloadImporter] = field(default_factory=dict)

    def register(self, importer: WorkloadImporter) -> "ImporterRegistry":
        self.importers[importer.importer_id] = importer
        return self

    def get(self, importer_id: str) -> WorkloadImporter:
        if importer_id not in self.importers:
            raise KeyError(f"unknown workload importer: {importer_id}")
        return self.importers[importer_id]

    def import_workload(
        self,
        importer_id: str,
        source: Any,
        *,
        profile: WorkloadProfile | Mapping[str, Any],
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> WorkloadPackage:
        return self.get(importer_id).import_workload(source, profile=profile, parameters=parameters)

    # Deprecated compatibility with the old registry method name.
    def emit(self, importer_id: str, source: Any, parameters: Optional[Mapping[str, Any]] = None) -> WorkloadPackage:
        parameters = dict(parameters or {})
        profile_id = str(parameters.get("profile_id", parameters.get("workload_family", "dynamic_custom")))
        profile = default_profile_registry().get(profile_id)
        return self.import_workload(importer_id, source, profile=profile, parameters=parameters)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "dse.workload_importer_registry.v1",
            "importers": [importer.to_dict() for importer in self.importers.values()],
        }


class GenericJsonImporter(WorkloadImporter):
    importer_id = "generic_json"
    importer_version = "v1"
    supported_source_kinds = ["hand_authored", "imported_graph", "external_ir", "generated", "generic_json"]
    compatible_profiles = ["ml_tensor", "sparse_la", "stencil_streaming", "graph_analytics", "database_vector_search", "dynamic_custom"]

    def import_workload(
        self,
        source: Any,
        *,
        profile: WorkloadProfile | Mapping[str, Any],
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> WorkloadPackage:
        parameters = dict(parameters or {})
        profile_payload = _profile_payload(profile)
        if isinstance(source, WorkloadPackage):
            return source
        if isinstance(source, ComputeGraph):
            graph = source
            payload: Mapping[str, Any] = {}
        elif isinstance(source, Mapping):
            payload = source
            graph_payload = payload.get("graph", payload)
            graph = graph_payload if isinstance(graph_payload, ComputeGraph) else ComputeGraph.from_dict(graph_payload)
        else:
            raise TypeError("GenericJsonImporter source must be a WorkloadPackage, ComputeGraph, or mapping")

        profile_override = parameters.get("profile", parameters.get("workflow", payload.get("profile", payload.get("workflow", {}))))
        profile_payload = resolve_profile_metadata(str(profile_payload.get("profile_id", profile_payload.get("workload_family", "dynamic_custom"))), profile_override if isinstance(profile_override, Mapping) else {})
        workload_family = str(parameters.get("workload_family", payload.get("workload_family", profile_payload.get("workload_family", "dynamic_custom"))))
        graph.metadata["profile_id"] = str(profile_payload.get("profile_id", workload_family))
        graph.metadata["workload_family"] = workload_family
        graph.metadata["profile"] = profile_payload
        graph.metadata["workflow"] = profile_payload
        graph.metadata["importer_id"] = self.importer_id
        return package_from_graph(
            graph,
            workload_id=str(parameters.get("workload_id", getattr(graph, "graph_id", "custom_workload"))),
            workload_family=workload_family,
            profile_id=str(profile_payload.get("profile_id", workload_family)),
            profile_version=str(profile_payload.get("profile_version", "v1")),
            importer_id=self.importer_id,
            importer_version=self.importer_version,
            claim_boundary=str(parameters.get("claim_boundary", profile_payload.get("default_claim_boundary", "full_workload"))),
            source_kind=str(parameters.get("source_kind", payload.get("source_kind", "hand_authored"))),
            source_path=parameters.get("source_path", payload.get("source_path")),
            domain_metadata=parameters.get("domain_metadata", payload.get("domain_metadata", {})),
            profile=profile_payload,
        )

def default_importer_registry() -> ImporterRegistry:
    return ImporterRegistry().register(GenericJsonImporter())
