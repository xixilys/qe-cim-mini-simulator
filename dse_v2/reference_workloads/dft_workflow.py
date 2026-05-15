#!/usr/bin/env python3
"""DFT workflow and claim summaries for the Step1 DFT adapter.

This module is intentionally outside the domain-neutral workload core.  It
models DFT workflow reconstruction facts and evidence-labeled hotspot claims so
Step1 can hand useful workload facts to later stages without selecting mapping,
placement, scheduling, runtime policy, descriptor protocol, simulator verdicts,
or architecture resources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional


DFT_WORKFLOW_SPEC_SCHEMA = "dse.dft.workflow_spec.v1"
DFT_WORKFLOW_SUMMARY_SCHEMA = "dse.domain_workflow_summary.v1"
DFT_CLAIM_SUMMARY_SCHEMA = "dse.domain_claim_summary.v1"

ALLOWED_EVIDENCE_LABELS = {"observed", "predicted", "user_confirmed"}
ALLOWED_CLAIM_KINDS = {"hotspot", "dominance"}


@dataclass(frozen=True)
class DftClaimEvidence:
    """Provenance for a workflow or claim fact."""

    evidence_level: str
    source_type: str = "heuristic"
    confidence: str = "medium"
    source_fact_ids: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "evidence_level": self.evidence_level,
            "source_type": self.source_type,
            "confidence": self.confidence,
            "source_fact_ids": list(self.source_fact_ids),
        }
        if self.description:
            payload["description"] = self.description
        return payload

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "DftClaimEvidence":
        return DftClaimEvidence(
            evidence_level=str(data.get("evidence_level", "heuristic")),
            source_type=str(data.get("source_type", "heuristic")),
            confidence=str(data.get("confidence", "medium")),
            source_fact_ids=[str(item) for item in data.get("source_fact_ids", []) or []],
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True)
class DftReviewGate:
    """Explicit user/agent review gate for uncertain DFT workflow facts."""

    gate_id: str
    reason: str
    severity: str = "needs_review"
    related_stage_ids: list[str] = field(default_factory=list)
    related_phase_ids: list[str] = field(default_factory=list)
    related_claim_ids: list[str] = field(default_factory=list)
    required_reviewer: str = "user_or_domain_expert"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "reason": self.reason,
            "severity": self.severity,
            "related_stage_ids": list(self.related_stage_ids),
            "related_phase_ids": list(self.related_phase_ids),
            "related_claim_ids": list(self.related_claim_ids),
            "required_reviewer": self.required_reviewer,
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "DftReviewGate":
        return DftReviewGate(
            gate_id=str(data.get("gate_id", "review_gate")),
            reason=str(data.get("reason", "review required")),
            severity=str(data.get("severity", "needs_review")),
            related_stage_ids=[str(item) for item in data.get("related_stage_ids", []) or []],
            related_phase_ids=[str(item) for item in data.get("related_phase_ids", []) or []],
            related_claim_ids=[str(item) for item in data.get("related_claim_ids", []) or []],
            required_reviewer=str(data.get("required_reviewer", "user_or_domain_expert")),
        )


@dataclass(frozen=True)
class DftStageDependency:
    """Architecture-independent dependency between DFT workflow stages."""

    source_stage_id: str
    target_stage_id: str
    artifact_names: list[str] = field(default_factory=list)
    dependency_kind: str = "data_dependency"
    evidence: Optional[DftClaimEvidence] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "source_stage_id": self.source_stage_id,
            "target_stage_id": self.target_stage_id,
            "artifact_names": list(self.artifact_names),
            "dependency_kind": self.dependency_kind,
            "non_decision_note": "dependency fact only; not a selected execution schedule",
        }
        if self.evidence is not None:
            payload["evidence"] = self.evidence.to_dict()
        return payload

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "DftStageDependency":
        evidence = data.get("evidence")
        return DftStageDependency(
            source_stage_id=str(data.get("source_stage_id", "")),
            target_stage_id=str(data.get("target_stage_id", "")),
            artifact_names=[str(item) for item in data.get("artifact_names", []) or []],
            dependency_kind=str(data.get("dependency_kind", "data_dependency")),
            evidence=DftClaimEvidence.from_dict(evidence) if isinstance(evidence, Mapping) else None,
        )


@dataclass(frozen=True)
class DftStage:
    """One stage in a normalized DFT workflow reconstruction."""

    stage_id: str
    stage_type: str
    source_program: str
    calculation_kind: str = "unknown"
    phase_skeleton: list[Dict[str, Any]] = field(default_factory=list)
    input_artifacts: list[str] = field(default_factory=list)
    output_artifacts: list[str] = field(default_factory=list)
    evidence: list[DftClaimEvidence] = field(default_factory=list)
    source_facts: list[Dict[str, Any]] = field(default_factory=list)
    review_flags: list[str] = field(default_factory=list)
    coverage_level: str = "recognized"
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "stage_type": self.stage_type,
            "source_program": self.source_program,
            "calculation_kind": self.calculation_kind,
            "coverage_level": self.coverage_level,
            "phase_skeleton": [dict(item) for item in self.phase_skeleton],
            "input_artifacts": list(self.input_artifacts),
            "output_artifacts": list(self.output_artifacts),
            "evidence": [item.to_dict() for item in self.evidence],
            "source_facts": [dict(item) for item in self.source_facts],
            "review_flags": sorted(set(self.review_flags)),
            "attributes": dict(self.attributes),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "DftStage":
        return DftStage(
            stage_id=str(data.get("stage_id", "")),
            stage_type=str(data.get("stage_type", "unknown")),
            source_program=str(data.get("source_program", "unknown")),
            calculation_kind=str(data.get("calculation_kind", data.get("stage_type", "unknown"))),
            phase_skeleton=[dict(item) for item in data.get("phase_skeleton", []) or [] if isinstance(item, Mapping)],
            input_artifacts=[str(item) for item in data.get("input_artifacts", []) or []],
            output_artifacts=[str(item) for item in data.get("output_artifacts", []) or []],
            evidence=[DftClaimEvidence.from_dict(item) for item in data.get("evidence", []) or [] if isinstance(item, Mapping)],
            source_facts=[dict(item) for item in data.get("source_facts", []) or [] if isinstance(item, Mapping)],
            review_flags=[str(item) for item in data.get("review_flags", []) or []],
            coverage_level=str(data.get("coverage_level", "recognized")),
            attributes=dict(data.get("attributes", {}) or {}),
        )


@dataclass(frozen=True)
class DftHotspotClaim:
    """Evidence-labeled hotspot or dominance claim.

    ``evidence_label`` is deliberately distinct from source evidence level so
    artifacts can keep observed, predicted, and user-confirmed claims separate.
    """

    claim_id: str
    stage_id: str
    phase_id: str
    kernel_kind: str
    claim_kind: str = "hotspot"
    evidence_label: str = "predicted"
    estimated_flops: float = 0.0
    estimated_memory_bytes: float = 0.0
    tensor_shapes: Dict[str, Any] = field(default_factory=dict)
    complexity_terms: Dict[str, Any] = field(default_factory=dict)
    evidence_level: str = "heuristic"
    confidence: str = "medium"
    source_fact_ids: list[str] = field(default_factory=list)
    review_status: str = "not_required"
    reason: str = ""
    margin: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.evidence_label not in ALLOWED_EVIDENCE_LABELS:
            raise ValueError(f"unsupported evidence_label: {self.evidence_label}")
        if self.claim_kind not in ALLOWED_CLAIM_KINDS:
            raise ValueError(f"unsupported claim_kind: {self.claim_kind}")
        if self.evidence_label == "observed" and self.evidence_level not in {"observed_timing", "observed_profile", "observed_runtime", "observed_preprocessed"}:
            raise ValueError("observed claims require observed evidence_level")

    @property
    def summary_key(self) -> str:
        if self.claim_kind == "hotspot":
            return f"{self.evidence_label}_hotspots"
        return f"{self.evidence_label}_dominance"

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "claim_id": self.claim_id,
            "stage_id": self.stage_id,
            "phase_id": self.phase_id,
            "kernel_kind": self.kernel_kind,
            "claim_kind": self.claim_kind,
            "evidence_label": self.evidence_label,
            "estimated_flops": float(self.estimated_flops),
            "estimated_memory_bytes": float(self.estimated_memory_bytes),
            "tensor_shapes": dict(self.tensor_shapes),
            "complexity_terms": dict(self.complexity_terms),
            "evidence_level": self.evidence_level,
            "confidence": self.confidence,
            "source_fact_ids": list(self.source_fact_ids),
            "review_status": self.review_status,
            "reason": self.reason,
        }
        if self.margin is not None:
            payload["margin"] = float(self.margin)
        if self.attributes:
            payload["attributes"] = dict(self.attributes)
        return payload

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "DftHotspotClaim":
        return DftHotspotClaim(
            claim_id=str(data.get("claim_id", "")),
            stage_id=str(data.get("stage_id", "")),
            phase_id=str(data.get("phase_id", "")),
            kernel_kind=str(data.get("kernel_kind", "unknown")),
            claim_kind=str(data.get("claim_kind", "hotspot")),
            evidence_label=str(data.get("evidence_label", "predicted")),
            estimated_flops=float(data.get("estimated_flops", 0.0) or 0.0),
            estimated_memory_bytes=float(data.get("estimated_memory_bytes", 0.0) or 0.0),
            tensor_shapes=dict(data.get("tensor_shapes", {}) or {}),
            complexity_terms=dict(data.get("complexity_terms", {}) or {}),
            evidence_level=str(data.get("evidence_level", "heuristic")),
            confidence=str(data.get("confidence", "medium")),
            source_fact_ids=[str(item) for item in data.get("source_fact_ids", []) or []],
            review_status=str(data.get("review_status", "not_required")),
            reason=str(data.get("reason", "")),
            margin=float(data["margin"]) if data.get("margin") is not None else None,
            attributes=dict(data.get("attributes", {}) or {}),
        )


@dataclass(frozen=True)
class DftWorkflowSpec:
    """Normalized DFT workflow reconstruction for optional Step1 adapters."""

    workflow_id: str
    workflow_family: str = "dft"
    source_software: str = "unknown"
    coverage_level: str = "recognized"
    stages: list[DftStage] = field(default_factory=list)
    dependencies: list[DftStageDependency] = field(default_factory=list)
    hotspot_claims: list[DftHotspotClaim] = field(default_factory=list)
    review_gates: list[DftReviewGate] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    review_flags: list[str] = field(default_factory=list)
    schema_version: str = DFT_WORKFLOW_SPEC_SCHEMA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "workflow_family": self.workflow_family,
            "source_software": self.source_software,
            "coverage_level": self.coverage_level,
            "stages": [stage.to_dict() for stage in self.stages],
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
            "hotspot_claims": [claim.to_dict() for claim in self.hotspot_claims],
            "review_gates": [gate.to_dict() for gate in self.review_gates],
            "limitations": sorted(set(self.limitations)),
            "review_flags": sorted(set(self.review_flags)),
            "non_decision_contract": {
                "analysis_scope": "architecture_independent",
                "note": "DFT workflow reconstruction reports facts and claims only; no mapping, placement, execution ordering policy, runtime policy, descriptor protocol, simulator verdict, or hardware resource is selected.",
            },
        }

    def workflow_summary(self) -> Dict[str, Any]:
        by_stage_type: Dict[str, int] = {}
        for stage in self.stages:
            by_stage_type[stage.stage_type] = by_stage_type.get(stage.stage_type, 0) + 1
        return {
            "schema_version": DFT_WORKFLOW_SUMMARY_SCHEMA,
            "workflow_id": self.workflow_id,
            "workflow_family": self.workflow_family,
            "source_software": self.source_software,
            "coverage_level": self.coverage_level,
            "stage_count": len(self.stages),
            "dependency_count": len(self.dependencies),
            "by_stage_type": dict(sorted(by_stage_type.items())),
            "stages": [stage.to_dict() for stage in self.stages],
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
            "review_gates": [gate.to_dict() for gate in self.review_gates],
            "review_flags": sorted(set(self.review_flags)),
            "limitations": sorted(set(self.limitations)),
            "analysis_scope": "architecture_independent",
        }

    def claim_summary(self) -> Dict[str, Any]:
        grouped: Dict[str, list[Dict[str, Any]]] = {
            "observed_hotspots": [],
            "predicted_hotspots": [],
            "user_confirmed_hotspots": [],
            "observed_dominance": [],
            "predicted_dominance": [],
            "user_confirmed_dominance": [],
        }
        needs_review: list[Dict[str, Any]] = []
        conflicts: list[Dict[str, Any]] = []
        for claim in self.hotspot_claims:
            payload = claim.to_dict()
            grouped.setdefault(claim.summary_key, []).append(payload)
            if claim.review_status in {"needs_review", "conflict"}:
                needs_review.append(payload)
            if claim.review_status == "conflict":
                conflicts.append(payload)
        return {
            "schema_version": DFT_CLAIM_SUMMARY_SCHEMA,
            "workflow_id": self.workflow_id,
            "analysis_scope": "architecture_independent",
            **grouped,
            "needs_review": needs_review,
            "conflicts": conflicts,
            "review_gates": [gate.to_dict() for gate in self.review_gates],
            "review_flags": sorted(set(self.review_flags)),
            "limitations": sorted(set(self.limitations)),
            "claim_label_contract": {
                "observed": "runtime/profile/log-derived facts only",
                "predicted": "static formula, software-semantics, template, or calibrated-fixture prediction",
                "user_confirmed": "prediction or domain fact explicitly confirmed by a user/domain expert",
            },
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "DftWorkflowSpec":
        return DftWorkflowSpec(
            schema_version=str(data.get("schema_version", DFT_WORKFLOW_SPEC_SCHEMA)),
            workflow_id=str(data.get("workflow_id", "")),
            workflow_family=str(data.get("workflow_family", "dft")),
            source_software=str(data.get("source_software", "unknown")),
            coverage_level=str(data.get("coverage_level", "recognized")),
            stages=[DftStage.from_dict(item) for item in data.get("stages", []) or [] if isinstance(item, Mapping)],
            dependencies=[DftStageDependency.from_dict(item) for item in data.get("dependencies", []) or [] if isinstance(item, Mapping)],
            hotspot_claims=[DftHotspotClaim.from_dict(item) for item in data.get("hotspot_claims", []) or [] if isinstance(item, Mapping)],
            review_gates=[DftReviewGate.from_dict(item) for item in data.get("review_gates", []) or [] if isinstance(item, Mapping)],
            limitations=[str(item) for item in data.get("limitations", []) or []],
            review_flags=[str(item) for item in data.get("review_flags", []) or []],
        )
