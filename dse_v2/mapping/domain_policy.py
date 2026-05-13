#!/usr/bin/env python3
"""Generic Step2 domain-policy seam.

This module is intentionally domain-neutral.  It defines the optional contract
that lets reference workloads add Step2 candidate-generation hints without
adding domain-specific fields to the generic WorkloadPackage, ComputeGraph,
mapping, co-design, or Step3 handoff schemas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence

from dse_v2.architecture.catalog import ArchitectureCatalog
from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload.package import WorkloadPackage

STEP2_CANDIDATE_HINTS_SCHEMA = "dse.step2.candidate_hints.v1"
STEP2_POLICY_INPUT_SCHEMA = "dse.step2.policy_input.v1"


@dataclass(frozen=True)
class Step2PolicyInput:
    """Read-only Step2 context passed to optional domain policies."""

    workload_package: WorkloadPackage
    source_graph: ComputeGraph
    executable_graph: Optional[ComputeGraph]
    lowering_report: Mapping[str, Any]
    workload_characterization: Optional[Mapping[str, Any]] = None
    step1_handoff_summary: Optional[Mapping[str, Any]] = None
    backend: str = "systemc"
    evidence_mode: str = "summary"
    require_l4_proof: bool = False
    schema_version: str = STEP2_POLICY_INPUT_SCHEMA

    def summary_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe identity summary without embedding large graphs."""
        return {
            "schema_version": self.schema_version,
            "workload_id": self.workload_package.workload_id,
            "workload_family": self.workload_package.workload_family,
            "profile_id": self.workload_package.profile_id,
            "importer_id": self.workload_package.importer_id,
            "claim_boundary": self.workload_package.claim_boundary,
            "source_graph_id": self.source_graph.graph_id,
            "executable_graph_id": self.executable_graph.graph_id if self.executable_graph else None,
            "lowering_status": self.lowering_report.get("status"),
            "backend": self.backend,
            "evidence_mode": self.evidence_mode,
            "require_l4_proof": bool(self.require_l4_proof),
            "has_workload_characterization": self.workload_characterization is not None,
            "has_step1_handoff_summary": self.step1_handoff_summary is not None,
            "domain_metadata_keys": sorted(str(key) for key in self.workload_package.domain_metadata.keys()),
        }


@dataclass
class Step2CandidateHints:
    """JSON-friendly optional hints emitted by a Step2 domain policy.

    The payload is deliberately generic at the top level: mappings use generic
    node ids and resource target ids/types.  Domain-specific detail must remain
    optional and namespaced under ``annotations`` (for example
    ``annotations["dft"]``).
    """

    policy_id: str
    domain_key: str
    matched: bool = True
    architecture_candidates: List[Dict[str, Any]] = field(default_factory=list)
    architecture_preferences: List[Dict[str, Any]] = field(default_factory=list)
    node_target_preferences: Dict[str, List[str]] = field(default_factory=dict)
    mapping_seeds: List[Dict[str, Any]] = field(default_factory=list)
    data_placement: Dict[str, Any] = field(default_factory=dict)
    runtime_schedule: Dict[str, Any] = field(default_factory=dict)
    descriptor_protocol: Dict[str, Any] = field(default_factory=dict)
    memory_policy: Dict[str, Any] = field(default_factory=dict)
    review_flags: List[str] = field(default_factory=list)
    hard_block_flags: List[str] = field(default_factory=list)
    review_required_flags: List[str] = field(default_factory=list)
    step3_queue: Dict[str, Any] = field(default_factory=dict)
    annotations: Dict[str, Any] = field(default_factory=dict)
    trusted_final_claim: bool = False
    schema_version: str = STEP2_CANDIDATE_HINTS_SCHEMA

    @classmethod
    def no_match(cls, *, policy_id: str = "no_policy", domain_key: str = "generic") -> "Step2CandidateHints":
        return cls(policy_id=policy_id, domain_key=domain_key, matched=False)

    @property
    def review_required(self) -> bool:
        return bool(self.review_flags or self.review_required_flags or self.hard_block_flags)

    @property
    def hard_blocked(self) -> bool:
        return bool(self.hard_block_flags)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "domain_key": self.domain_key,
            "matched": bool(self.matched),
            "architecture_candidates": list(self.architecture_candidates),
            "architecture_preferences": list(self.architecture_preferences),
            "node_target_preferences": {str(k): [str(item) for item in v] for k, v in self.node_target_preferences.items()},
            "mapping_seeds": list(self.mapping_seeds),
            "data_placement": dict(self.data_placement),
            "runtime_schedule": dict(self.runtime_schedule),
            "descriptor_protocol": dict(self.descriptor_protocol),
            "memory_policy": dict(self.memory_policy),
            "review_flags": sorted(set(str(flag) for flag in self.review_flags)),
            "hard_block_flags": sorted(set(str(flag) for flag in self.hard_block_flags)),
            "review_required_flags": sorted(set(str(flag) for flag in self.review_required_flags)),
            "review_required": self.review_required,
            "hard_blocked": self.hard_blocked,
            "step3_queue": dict(self.step3_queue),
            "annotations": dict(self.annotations),
            "trusted_final_claim": False,
        }


class Step2DomainPolicy(Protocol):
    """Protocol implemented by optional, explicitly registered Step2 policies."""

    policy_id: str
    domain_key: str

    def matches(self, policy_input: Step2PolicyInput) -> bool:
        """Return true when this policy should contribute candidate hints."""

    def augment_catalog(self, policy_input: Step2PolicyInput, catalog: ArchitectureCatalog) -> ArchitectureCatalog:
        """Return a catalog view with optional candidate-only additions/ranking."""

    def build_hints(
        self,
        policy_input: Step2PolicyInput,
        catalog: ArchitectureCatalog,
        architecture_id: str,
    ) -> Step2CandidateHints:
        """Return replayable candidate hints for the selected architecture."""


class Step2DomainPolicyRegistry:
    """Static explicit registry for optional Step2 domain policies."""

    def __init__(self, policies: Optional[Iterable[Step2DomainPolicy]] = None) -> None:
        self._policies: List[Step2DomainPolicy] = []
        for policy in policies or []:
            self.register(policy)

    def register(self, policy: Step2DomainPolicy) -> "Step2DomainPolicyRegistry":
        if not getattr(policy, "policy_id", ""):
            raise ValueError("Step2 domain policy must declare policy_id")
        if not getattr(policy, "domain_key", ""):
            raise ValueError("Step2 domain policy must declare domain_key")
        if any(existing.policy_id == policy.policy_id for existing in self._policies):
            raise ValueError(f"duplicate Step2 domain policy_id {policy.policy_id!r}")
        self._policies.append(policy)
        return self

    def policies(self) -> List[Step2DomainPolicy]:
        return list(self._policies)

    def matching_policies(self, policy_input: Step2PolicyInput) -> List[Step2DomainPolicy]:
        return [policy for policy in self._policies if bool(policy.matches(policy_input))]

    def augment_catalog(self, policy_input: Step2PolicyInput, catalog: ArchitectureCatalog) -> ArchitectureCatalog:
        augmented = catalog
        for policy in self.matching_policies(policy_input):
            augmented = policy.augment_catalog(policy_input, augmented)
        return augmented

    def build_hints(
        self,
        policy_input: Step2PolicyInput,
        catalog: ArchitectureCatalog,
        architecture_id: str,
    ) -> List[Step2CandidateHints]:
        hints: List[Step2CandidateHints] = []
        for policy in self.matching_policies(policy_input):
            hint = policy.build_hints(policy_input, catalog, architecture_id)
            if hint.matched:
                hints.append(hint)
        return hints


def default_step2_domain_policy_registry() -> Step2DomainPolicyRegistry:
    """Return the generic no-op registry.

    Reference policies are not imported here; callers must explicitly register
    them through reference-scoped helper functions.
    """

    return Step2DomainPolicyRegistry()


__all__ = [
    "STEP2_CANDIDATE_HINTS_SCHEMA",
    "STEP2_POLICY_INPUT_SCHEMA",
    "Step2CandidateHints",
    "Step2DomainPolicy",
    "Step2DomainPolicyRegistry",
    "Step2PolicyInput",
    "default_step2_domain_policy_registry",
]
