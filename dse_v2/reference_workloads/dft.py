#!/usr/bin/env python3
"""Optional DFT workload frontdoor kept outside the domain-neutral core.

The objects in this module form a small Step1 domain-plugin seam:
source-specific parsers emit provenance-carrying ``SourceFact`` records,
normalization folds those facts into a standardized ``DftCase``, and the graph
builder emits an ordinary ``ComputeGraph``.  No function in this module selects
mapping, placement, schedule, runtime policy, descriptor protocol, simulator
backend, or architecture resources.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode, DataEdge, GraphRegion, TensorSpec
from dse_v2.core.workload.package import WorkloadPackage, package_from_graph
from dse_v2.core.workload.profiles import WorkloadProfile
from dse_v2.reference_workloads.dft_profile_schema import (
    attach_dft_profile_contract,
    dft_profile_metadata_contract,
)
from dse_v2.reference_workloads.dft_workflow import (
    DftClaimEvidence,
    DftHotspotClaim,
    DftReviewGate,
    DftStage,
    DftStageDependency,
    DftWorkflowSpec,
)


SOURCE_FACT_SCHEMA = "dse.dft.source_fact.v1"
DFT_CASE_SCHEMA = "dse.dft.case.v1"
DFT_COVERAGE_SCHEMA = "dse.dft.coverage.v1"
DFT_PHASE_SUMMARY_SCHEMA = "dse.domain_phase_summary.v1"

SOURCE_TYPE_PRECEDENCE = {
    "profile": 50,
    "log": 40,
    "input": 30,
    "generated": 20,
    "heuristic": 10,
}

OBSERVED_TIMING_SOURCE_TYPES = {"profile", "log"}
MAIN_HOTSPOT_PHASE_IDS = {
    "fft",
    "h_psi",
    "diagonalization",
    "charge_density",
    "mixing",
    "augmentation",
    "forces",
    "stress",
    "extension:quantum_chemistry:two_electron_integrals",
}

CANONICAL_PHASE_IDS = {
    "scf_iteration",
    "fft",
    "diagonalization",
    "h_psi",
    "charge_density",
    "mixing",
    "augmentation",
    "forces",
    "stress",
    "io",
    "setup",
}

IMPORTANT_INPUT_FIELDS = {
    "input.calculation",
    "dimension.nat",
    "dimension.ntyp",
    "dimension.nbnd",
    "dimension.nspin",
    "dimension.kpoint_grid",
    "dimension.kpoint_count",
    "parameter.ecutwfc",
    "parameter.ecutrho",
    "parameter.conv_thr",
    "parameter.mixing_beta",
    "parameter.diagonalization",
}

PROJECT_CRITICAL_FIELDS = {
    "dimension.npw",
    "dimension.nfft",
    "dimension.nbnd",
    "dimension.kpoint_grid",
    "dimension.kpoint_count",
    "parameter.ecutwfc",
    "parameter.ecutrho",
}

NON_DECISION_NOTE = (
    "Step1 DFT normalization reports source facts, phase summaries, and graph "
    "skeleton hints only; it does not choose mapping, placement, schedule, "
    "runtime policy, descriptor protocol, simulator verdict, or architecture resources."
)


@dataclass(frozen=True)
class SourceFact:
    """One deterministic parser/normalizer fact with provenance."""

    field: str
    value: Any
    unit: str = ""
    source_type: str = "input"
    source_path: Optional[str] = None
    evidence_level: str = "declared"
    confidence: str = "medium"
    raw_excerpt: Optional[str] = None
    run_id: Optional[str] = None
    fact_id: Optional[str] = None
    schema_version: str = SOURCE_FACT_SCHEMA

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPE_PRECEDENCE:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        if self.fact_id is None:
            object.__setattr__(self, "fact_id", make_fact_id(
                self.field,
                self.value,
                self.unit,
                self.source_type,
                self.evidence_level,
                self.raw_excerpt,
                self.run_id,
            ))

    @property
    def precedence(self) -> int:
        return SOURCE_TYPE_PRECEDENCE[self.source_type]

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "fact_id": self.fact_id,
            "field": self.field,
            "value": self.value,
            "unit": self.unit,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "evidence_level": self.evidence_level,
            "confidence": self.confidence,
        }
        if self.raw_excerpt is not None:
            payload["raw_excerpt"] = self.raw_excerpt
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        return payload

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "SourceFact":
        return SourceFact(
            fact_id=str(data.get("fact_id")) if data.get("fact_id") else None,
            field=str(data.get("field", "")),
            value=data.get("value"),
            unit=str(data.get("unit", "")),
            source_type=str(data.get("source_type", "input")),
            source_path=str(data.get("source_path")) if data.get("source_path") is not None else None,
            evidence_level=str(data.get("evidence_level", "declared")),
            confidence=str(data.get("confidence", "medium")),
            raw_excerpt=str(data.get("raw_excerpt")) if data.get("raw_excerpt") is not None else None,
            run_id=str(data.get("run_id")) if data.get("run_id") is not None else None,
        )


@dataclass(frozen=True)
class DftKernelShape:
    """Architecture-independent kernel shape summary inside a DFT phase."""

    kernel_id: str
    op_type: str
    dimensions: Dict[str, Any] = field(default_factory=dict)
    estimated_flops: float = 0.0
    estimated_memory_bytes: float = 0.0
    input_tensors: Dict[str, TensorSpec] = field(default_factory=dict)
    output_tensors: Dict[str, TensorSpec] = field(default_factory=dict)
    source_fact_ids: List[str] = field(default_factory=list)
    evidence_level: str = "heuristic_shape"
    confidence: str = "low"
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kernel_id": self.kernel_id,
            "op_type": self.op_type,
            "dimensions": dict(self.dimensions),
            "estimated_flops": float(self.estimated_flops),
            "estimated_memory_bytes": float(self.estimated_memory_bytes),
            "input_tensors": {name: spec.to_dict() for name, spec in self.input_tensors.items()},
            "output_tensors": {name: spec.to_dict() for name, spec in self.output_tensors.items()},
            "source_fact_ids": list(self.source_fact_ids),
            "evidence_level": self.evidence_level,
            "confidence": self.confidence,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class DftPhase:
    """Normalized DFT phase fact bundle before graph emission."""

    phase_id: str
    label: str
    kernels: List[DftKernelShape] = field(default_factory=list)
    source_fact_ids: List[str] = field(default_factory=list)
    evidence_level: str = "heuristic_phase"
    confidence: str = "low"
    dominance: str = "candidate"
    dominance_reason: str = "no observed timing evidence"
    estimated_time_seconds: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "phase_id": self.phase_id,
            "label": self.label,
            "kernels": [kernel.to_dict() for kernel in self.kernels],
            "source_fact_ids": list(self.source_fact_ids),
            "evidence_level": self.evidence_level,
            "confidence": self.confidence,
            "dominance": self.dominance,
            "dominance_reason": self.dominance_reason,
            "attributes": dict(self.attributes),
        }
        if self.estimated_time_seconds is not None:
            payload["estimated_time_seconds"] = float(self.estimated_time_seconds)
        return payload


@dataclass(frozen=True)
class DftCoverageReport:
    """Reviewable coverage/claim boundary for a normalized DFT case."""

    claim_boundary: str
    full_workload_reconstruction: bool
    supported_phase_ids: List[str]
    unsupported_phase_ids: List[str] = field(default_factory=list)
    unavailable_claims: List[str] = field(default_factory=list)
    review_flags: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    schema_version: str = DFT_COVERAGE_SCHEMA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "claim_boundary": self.claim_boundary,
            "full_workload_reconstruction": bool(self.full_workload_reconstruction),
            "supported_phase_ids": list(self.supported_phase_ids),
            "unsupported_phase_ids": list(self.unsupported_phase_ids),
            "unavailable_claims": list(self.unavailable_claims),
            "review_flags": list(self.review_flags),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class DftCase:
    """Standardized DFT workload description produced by optional importers."""

    case_id: str
    workload_family: str
    profile_id: str
    importer_id: str
    source_program: str
    source_facts: List[SourceFact]
    fact_summaries: Dict[str, Any]
    conflicts: List[Dict[str, Any]]
    phases: List[DftPhase]
    coverage: DftCoverageReport
    review_flags: List[str] = field(default_factory=list)
    input_parameters: Dict[str, Any] = field(default_factory=dict)
    claim_boundary: str = "diagnostic"
    limitations: List[str] = field(default_factory=list)
    schema_version: str = DFT_CASE_SCHEMA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "workload_family": self.workload_family,
            "profile_id": self.profile_id,
            "importer_id": self.importer_id,
            "source_program": self.source_program,
            "claim_boundary": self.claim_boundary,
            "source_facts": [fact.to_dict() for fact in self.source_facts],
            "fact_summaries": dict(self.fact_summaries),
            "conflicts": list(self.conflicts),
            "phases": [phase.to_dict() for phase in self.phases],
            "coverage": self.coverage.to_dict(),
            "review_flags": sorted(set(self.review_flags)),
            "input_parameters": dict(self.input_parameters),
            "limitations": sorted(set(self.limitations)),
            "non_decision_contract": {
                "analysis_scope": "architecture_independent",
                "note": NON_DECISION_NOTE,
            },
        }

    def to_domain_metadata(self) -> Dict[str, Any]:
        payload = self.to_dict()
        return {
            "schema_version": payload["schema_version"],
            "case_id": payload["case_id"],
            "source_program": payload["source_program"],
            "claim_boundary": payload["claim_boundary"],
            "source_facts": payload["source_facts"],
            "fact_summaries": payload["fact_summaries"],
            "conflicts": payload["conflicts"],
            "phases": payload["phases"],
            "coverage": payload["coverage"],
            "review_flags": payload["review_flags"],
            "input_parameters": payload["input_parameters"],
            "limitations": payload["limitations"],
            "non_decision_contract": payload["non_decision_contract"],
        }


def make_fact_id(
    field: str,
    value: Any,
    unit: str,
    source_type: str,
    evidence_level: str,
    raw_excerpt: Optional[str],
    run_id: Optional[str],
) -> str:
    """Return a deterministic fact id independent of parse order."""
    payload = {
        "field": str(field),
        "value": _jsonable(value),
        "unit": str(unit),
        "source_type": str(source_type),
        "evidence_level": str(evidence_level),
        "raw_excerpt": _normalize_text(raw_excerpt or ""),
        "run_id": str(run_id or ""),
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    return f"fact:{digest}"


def stable_unknown_phase_id(raw_label: str) -> str:
    normalized = _normalize_text(raw_label).lower()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"unknown:{digest}"


def canonicalize_phase_id(raw_label: str, *, extension_namespace: str = "qe") -> str:
    label = _normalize_text(raw_label).lower().replace("-", "_")
    label = re.sub(r"[^a-z0-9_:.]+", "_", label).strip("_")
    if not label:
        return stable_unknown_phase_id(raw_label)
    if label in CANONICAL_PHASE_IDS:
        return label
    if label.startswith("extension:"):
        parts = [part for part in label.split(":") if part]
        if len(parts) >= 3:
            namespace = re.sub(r"[^a-z0-9_]+", "_", parts[1]).strip("_") or extension_namespace
            phase = re.sub(r"[^a-z0-9_]+", "_", "_".join(parts[2:])).strip("_")
            return f"extension:{namespace}:{phase or 'unknown'}"

    aliases = [
        ("h_psi", "h_psi"),
        ("hpsi", "h_psi"),
        ("hamilton", "h_psi"),
        ("fft", "fft"),
        ("fftx", "fft"),
        ("fftw", "fft"),
        ("c_bands", "diagonalization"),
        ("cegterg", "diagonalization"),
        ("diag", "diagonalization"),
        ("eigen", "diagonalization"),
        ("rho", "charge_density"),
        ("density", "charge_density"),
        ("mix", "mixing"),
        ("v_of_rho", "charge_density"),
        ("augmentation", "augmentation"),
        ("addus", "augmentation"),
        ("force", "forces"),
        ("stress", "stress"),
        ("setup", "setup"),
        ("init", "setup"),
        ("read", "io"),
        ("write", "io"),
        ("io", "io"),
        ("scf", "scf_iteration"),
        ("electrons", "scf_iteration"),
    ]
    for token, phase_id in aliases:
        if token in label:
            return phase_id
    if "two_electron" in label or "2e_integral" in label or label in {"eri", "electron_repulsion_integrals"}:
        return "extension:quantum_chemistry:two_electron_integrals"
    if label.startswith("extension_"):
        remainder = label[len("extension_"):]
        return f"extension:{extension_namespace}:{remainder or 'unknown'}"
    return stable_unknown_phase_id(label)


def merge_source_facts(
    facts: Iterable[SourceFact | Mapping[str, Any]],
    *,
    important_fields: Optional[Iterable[str]] = None,
    project_critical_fields: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Preserve all facts and compute preferred fact summaries by precedence."""
    normalized = [fact if isinstance(fact, SourceFact) else SourceFact.from_dict(fact) for fact in facts]
    important = set(important_fields or IMPORTANT_INPUT_FIELDS)
    critical = set(project_critical_fields or PROJECT_CRITICAL_FIELDS)
    by_field: Dict[str, List[SourceFact]] = {}
    for fact in normalized:
        by_field.setdefault(fact.field, []).append(fact)

    summaries: Dict[str, Any] = {}
    conflicts: List[Dict[str, Any]] = []
    review_flags: List[str] = []
    for field, field_facts in sorted(by_field.items()):
        ordered = sorted(
            field_facts,
            key=lambda fact: (-fact.precedence, _confidence_rank(fact.confidence) * -1, str(fact.fact_id)),
        )
        preferred = ordered[0]
        summaries[field] = {
            "preferred_fact_id": preferred.fact_id,
            "preferred_value": preferred.value,
            "unit": preferred.unit,
            "source_type": preferred.source_type,
            "evidence_level": preferred.evidence_level,
            "confidence": preferred.confidence,
            "fact_ids": [fact.fact_id for fact in ordered],
        }
        distinct_values = {_normalized_value_key(fact.value) for fact in field_facts}
        if len(distinct_values) > 1:
            flags = []
            if field in critical:
                flags.append("project_critical_conflict")
            if field in important:
                flags.append("important_input_parameter")
            if not flags:
                flags.append("conflicting_source_facts")
            review_flags.extend(flags)
            conflicts.append({
                "field": field,
                "fact_ids": [fact.fact_id for fact in ordered],
                "values": [fact.value for fact in ordered],
                "source_types": [fact.source_type for fact in ordered],
                "preferred_fact_id": preferred.fact_id,
                "review_flags": sorted(set(flags)),
                "reason": "source facts disagree; all evidence is preserved and only a precedence summary is provided",
            })
        if field in important:
            review_flags.append("important_input_parameter")

    return {
        "schema_version": "dse.dft.source_fact_set.v1",
        "source_type_precedence": dict(SOURCE_TYPE_PRECEDENCE),
        "facts": [fact.to_dict() for fact in sorted(normalized, key=lambda fact: str(fact.fact_id))],
        "fact_summaries": summaries,
        "conflicts": conflicts,
        "review_flags": sorted(set(review_flags)),
    }


def dft_phase_reference_profile() -> WorkloadProfile:
    """Optional DFT/QE profile for source-derived phase/kernel graphs."""
    profile = WorkloadProfile(
        profile_id="dft_qe_pw_static",
        profile_version="v1",
        workload_family="dft",
        accepted_source_kinds=[
            "qe_pw_bundle",
            "qe_workflow_bundle",
            "qe_pw_input",
            "qe_pw_log",
            "qe_pw_profile",
            "dft_config",
            "generated",
        ],
        graph_pattern="dft_phase_kernel_graph",
        lowering_policy="identity_dag_or_bounded_phase_regions",
        default_mapping_policies=[],
        mapping_preferences={},
        domain_validation={
            "timing_only_allowed": True,
            "numerical_correctness_claimed": False,
            "correctness_claim_requires_external_domain_evidence": True,
            "unclaimed_domain_correctness": "DFT numerical/physics correctness, convergence, pseudopotential validity, and scientific result equivalence are not claimed by Step1 workload characterization.",
        },
        default_claim_boundary="diagnostic",
        required_coverage=[],
        unavailable_metric_labels=[
            "dft_numerical_correctness",
            "scf_convergence_correctness",
            "pseudopotential_validity",
            "scientific_result_equivalence",
        ],
        description="Optional DFT/QE static source frontdoor that emits architecture-independent phase/kernel workload facts.",
        plugin_metadata={"reference_only": True, "domain": "dft", "source_program": "qe_pw"},
    )
    return WorkloadProfile.from_dict(attach_dft_profile_contract(profile.to_dict(), source_program="qe_pw"))


def build_dft_phase_graph(case: DftCase, *, graph_id: Optional[str] = None) -> ComputeGraph:
    """Emit a generic ComputeGraph from a normalized DFT case."""
    graph = ComputeGraph(
        graph_id=graph_id or f"{_safe_id(case.case_id)}_graph",
        metadata={
            "workload_family": case.workload_family,
            "profile_id": case.profile_id,
            "importer_id": case.importer_id,
            "source_program": case.source_program,
            "analysis_scope": "architecture_independent",
            "domain_metadata_keys": ["dft"],
            "non_decision_contract": NON_DECISION_NOTE,
        },
    )
    previous_node_id: Optional[str] = None
    scf_region_nodes: List[str] = []
    for index, phase in enumerate(case.phases):
        node_id = _phase_node_id(phase.phase_id, index)
        kernel = phase.kernels[0] if phase.kernels else _fallback_kernel_for_phase(phase.phase_id, case.input_parameters)
        graph.add_node(ComputeNode(
            node_id=node_id,
            op_type=kernel.op_type,
            inputs=list(kernel.input_tensors),
            outputs=list(kernel.output_tensors) or [f"{node_id}_out"],
            input_specs=dict(kernel.input_tensors),
            output_specs=dict(kernel.output_tensors),
            estimated_flops=float(kernel.estimated_flops),
            estimated_memory_bytes=float(kernel.estimated_memory_bytes),
            attributes={
                "adapter:dft": {
                    "phase_id": phase.phase_id,
                    "label": phase.label,
                    "kernel_id": kernel.kernel_id,
                    "source_fact_ids": list(set(phase.source_fact_ids + kernel.source_fact_ids)),
                    "evidence_level": phase.evidence_level,
                    "confidence": phase.confidence,
                    "dominance": phase.dominance,
                    "dominance_reason": phase.dominance_reason,
                    "analysis_scope": "architecture_independent",
                }
            },
        ))
        if previous_node_id is not None:
            tensor_name = f"{previous_node_id}_to_{node_id}"
            graph.add_edge(DataEdge(
                previous_node_id,
                node_id,
                tensor_name=tensor_name,
                tensor_spec=_small_phase_token_spec(),
                edge_kind="data",
                attributes={"adapter:dft": {"reason": "phase-order skeleton; not a schedule"}},
            ))
        previous_node_id = node_id
        if phase.phase_id not in {"setup", "io"}:
            scf_region_nodes.append(node_id)

    scf_count = _int_value(case.fact_summaries, "iteration.scf.count")
    if scf_count and scf_count > 0 and len(scf_region_nodes) > 1:
        graph.add_region(GraphRegion(
            region_id="scf_iteration_region",
            region_type="loop",
            node_ids=scf_region_nodes,
            entry_nodes=scf_region_nodes[:1],
            exit_nodes=scf_region_nodes[-1:],
            semantics={
                "iteration_count": scf_count,
                "bounded": True,
                "source": "observed_or_declared_source_fact",
            },
            attributes={"adapter:dft": {"phase_id": "scf_iteration", "analysis_scope": "architecture_independent"}},
        ))
    return graph


def domain_phase_summary_from_case(case: DftCase) -> Dict[str, Any]:
    """Return a generic optional phase summary for workload_characterization."""
    timing = [phase for phase in case.phases if phase.estimated_time_seconds is not None]
    total_observed = sum(float(phase.estimated_time_seconds or 0.0) for phase in timing)
    return {
        "schema_version": DFT_PHASE_SUMMARY_SCHEMA,
        "analysis_scope": "architecture_independent",
        "source_program": case.source_program,
        "phase_count": len(case.phases),
        "phase_summaries": [
            {
                "phase_id": phase.phase_id,
                "label": phase.label,
                "kernel_count": len(phase.kernels),
                "estimated_flops": float(sum(kernel.estimated_flops for kernel in phase.kernels)),
                "estimated_memory_bytes": float(sum(kernel.estimated_memory_bytes for kernel in phase.kernels)),
                "observed_time_seconds": float(phase.estimated_time_seconds) if phase.estimated_time_seconds is not None else None,
                "observed_time_fraction": (float(phase.estimated_time_seconds or 0.0) / total_observed) if total_observed else None,
                "dominance": phase.dominance,
                "dominance_reason": phase.dominance_reason,
                "evidence_level": phase.evidence_level,
                "confidence": phase.confidence,
            }
            for phase in case.phases
        ],
        "dominance_summary": {
            "dominant_phase_ids": [phase.phase_id for phase in case.phases if phase.dominance == "dominant"],
            "dominance_rule": "domain_phase_summary dominant_phase_ids are observed profile/log timing facts only; static predicted/user-confirmed dominance claims, when present, live in domain_claim_summary",
        },
        "coverage_summary": case.coverage.to_dict(),
        "review_flags": sorted(set(case.review_flags)),
        "limitations": sorted(set(case.limitations + [NON_DECISION_NOTE])),
    }


def dft_stage_from_case(
    case: DftCase,
    *,
    stage_id: Optional[str] = None,
    stage_type: Optional[str] = None,
    source_program: Optional[str] = None,
    coverage_level: str = "common_mode",
) -> DftStage:
    """Return a reviewable workflow stage view over a normalized DFT case."""
    resolved_stage_type = stage_type or _stage_type_from_case(case)
    resolved_stage_id = stage_id or f"stage_00_{_safe_id(source_program or case.source_program)}_{_safe_id(resolved_stage_type)}"
    phase_skeleton = [
        {
            "phase_id": phase.phase_id,
            "label": phase.label,
            "kernel_count": len(phase.kernels),
            "estimated_flops": float(sum(kernel.estimated_flops for kernel in phase.kernels)),
            "estimated_memory_bytes": float(sum(kernel.estimated_memory_bytes for kernel in phase.kernels)),
            "observed_time_seconds": float(phase.estimated_time_seconds) if phase.estimated_time_seconds is not None else None,
            "evidence_level": phase.evidence_level,
            "confidence": phase.confidence,
            "dominance": phase.dominance,
            "dominance_reason": phase.dominance_reason,
            "source_fact_ids": list(phase.source_fact_ids),
        }
        for phase in case.phases
    ]
    return DftStage(
        stage_id=resolved_stage_id,
        stage_type=resolved_stage_type,
        source_program=source_program or case.source_program,
        calculation_kind=str(case.input_parameters.get("calculation", resolved_stage_type)),
        phase_skeleton=phase_skeleton,
        input_artifacts=_default_stage_inputs(resolved_stage_type),
        output_artifacts=_default_stage_outputs(resolved_stage_type),
        evidence=[
            DftClaimEvidence(
                evidence_level="source_fact_summary",
                source_type="mixed",
                confidence="medium",
                source_fact_ids=[fact.fact_id for fact in case.source_facts],
                description="stage reconstructed from normalized DFT source facts",
            )
        ],
        source_facts=[fact.to_dict() for fact in case.source_facts],
        review_flags=sorted(set(case.review_flags)),
        coverage_level=coverage_level,
        attributes={
            "claim_boundary": case.claim_boundary,
            "full_workload_reconstruction": case.coverage.full_workload_reconstruction,
        },
    )


def dft_claims_from_case(
    case: DftCase,
    *,
    stage_id: str,
    static_dominance_margin: Optional[float] = None,
    user_confirmed_dominance: Optional[Iterable[str] | str] = None,
) -> tuple[List[DftHotspotClaim], List[DftReviewGate]]:
    """Build strict observed/predicted/user-confirmed hotspot claims from a case."""
    margin = float(static_dominance_margin if static_dominance_margin is not None else case.input_parameters.get("static_dominance_margin", 4.0))
    confirmed = _confirmed_phase_set(user_confirmed_dominance if user_confirmed_dominance is not None else case.input_parameters.get("user_confirmed_dominance"))
    claims: List[DftHotspotClaim] = []
    review_gates: List[DftReviewGate] = []
    phase_metrics = [
        (phase, float(sum(kernel.estimated_flops for kernel in phase.kernels)), float(sum(kernel.estimated_memory_bytes for kernel in phase.kernels)))
        for phase in case.phases
        if phase.phase_id in MAIN_HOTSPOT_PHASE_IDS or phase.estimated_time_seconds is not None
    ]
    for phase, flops, memory_bytes in phase_metrics:
        kernel = phase.kernels[0] if phase.kernels else _fallback_kernel_for_phase(phase.phase_id, case.input_parameters)
        tensor_shapes = _tensor_shapes_for_kernel(kernel)
        is_observed = phase.estimated_time_seconds is not None and phase.evidence_level.startswith("observed")
        evidence_label = "observed" if is_observed else "predicted"
        evidence_level = phase.evidence_level if is_observed else kernel.evidence_level
        confidence = phase.confidence if is_observed else max(phase.confidence, kernel.confidence, key=_confidence_rank)
        claim = DftHotspotClaim(
            claim_id=f"{stage_id}:{phase.phase_id}:{evidence_label}:hotspot",
            stage_id=stage_id,
            phase_id=phase.phase_id,
            kernel_kind=kernel.op_type,
            claim_kind="hotspot",
            evidence_label=evidence_label,
            estimated_flops=flops,
            estimated_memory_bytes=memory_bytes,
            tensor_shapes=tensor_shapes,
            complexity_terms=dict(kernel.dimensions),
            evidence_level=evidence_level,
            confidence=confidence,
            source_fact_ids=list(set(phase.source_fact_ids + kernel.source_fact_ids)),
            review_status="not_required" if is_observed else "needs_review",
            reason="observed profile/log timing" if is_observed else "static kernel shape prediction from source facts or defaults",
        )
        claims.append(claim)
        if phase.dominance == "dominant" and is_observed:
            claims.append(DftHotspotClaim(
                claim_id=f"{stage_id}:{phase.phase_id}:observed:dominance",
                stage_id=stage_id,
                phase_id=phase.phase_id,
                kernel_kind=kernel.op_type,
                claim_kind="dominance",
                evidence_label="observed",
                estimated_flops=flops,
                estimated_memory_bytes=memory_bytes,
                tensor_shapes=tensor_shapes,
                complexity_terms=dict(kernel.dimensions),
                evidence_level="observed_timing",
                confidence=phase.confidence,
                source_fact_ids=list(set(phase.source_fact_ids + kernel.source_fact_ids)),
                review_status="not_required",
                reason=phase.dominance_reason,
            ))

    if not any(claim.claim_kind == "dominance" and claim.evidence_label == "observed" for claim in claims):
        predicted = _predicted_dominance_claim(stage_id, phase_metrics, margin)
        if predicted is not None:
            claims.append(predicted)
            review_gates.append(DftReviewGate(
                gate_id=f"{stage_id}:static_dominance_review",
                reason="static dominance prediction requires user review before strong claim",
                related_stage_ids=[stage_id],
                related_phase_ids=[predicted.phase_id],
                related_claim_ids=[predicted.claim_id],
            ))

    for phase_id in confirmed:
        source = next((claim for claim in claims if claim.phase_id == phase_id and claim.claim_kind == "dominance"), None)
        if source is not None:
            claims.append(DftHotspotClaim(
                claim_id=f"{stage_id}:{phase_id}:user_confirmed:dominance",
                stage_id=stage_id,
                phase_id=phase_id,
                kernel_kind=source.kernel_kind,
                claim_kind="dominance",
                evidence_label="user_confirmed",
                estimated_flops=source.estimated_flops,
                estimated_memory_bytes=source.estimated_memory_bytes,
                tensor_shapes=dict(source.tensor_shapes),
                complexity_terms=dict(source.complexity_terms),
                evidence_level="user_confirmed",
                confidence="high",
                source_fact_ids=list(source.source_fact_ids),
                review_status="user_confirmed",
                reason="user/domain expert confirmed static or observed dominance claim",
                margin=source.margin,
            ))

    if case.conflicts:
        review_gates.append(DftReviewGate(
            gate_id=f"{stage_id}:source_fact_conflicts",
            reason="source facts conflict; preserve all facts and require review",
            severity="conflict",
            related_stage_ids=[stage_id],
            related_phase_ids=[phase.phase_id for phase in case.phases],
        ))
    return claims, review_gates


def workflow_from_dft_case(
    case: DftCase,
    *,
    workflow_id: Optional[str] = None,
    stage_id: Optional[str] = None,
    stage_type: Optional[str] = None,
    source_software: Optional[str] = None,
    coverage_level: str = "common_mode",
) -> DftWorkflowSpec:
    """Build a single-stage workflow spec from a DFT case."""
    stage = dft_stage_from_case(
        case,
        stage_id=stage_id,
        stage_type=stage_type,
        source_program=source_software or case.source_program,
        coverage_level=coverage_level,
    )
    claims, review_gates = dft_claims_from_case(case, stage_id=stage.stage_id)
    return DftWorkflowSpec(
        workflow_id=workflow_id or f"{case.case_id}_workflow",
        workflow_family=case.workload_family,
        source_software=source_software or case.source_program,
        coverage_level=coverage_level,
        stages=[stage],
        dependencies=[],
        hotspot_claims=claims,
        review_gates=review_gates,
        limitations=sorted(set(case.limitations)),
        review_flags=sorted(set(case.review_flags + [gate.severity for gate in review_gates])),
    )


def domain_workflow_summary_from_case(case: DftCase) -> Dict[str, Any]:
    return workflow_from_dft_case(case).workflow_summary()


def domain_claim_summary_from_case(case: DftCase) -> Dict[str, Any]:
    return workflow_from_dft_case(case).claim_summary()


def build_dft_workflow_graph(workflow: DftWorkflowSpec, *, graph_id: Optional[str] = None) -> ComputeGraph:
    """Emit a generic graph from a DFT workflow reconstruction."""
    graph = ComputeGraph(
        graph_id=graph_id or f"{_safe_id(workflow.workflow_id)}_graph",
        metadata={
            "workload_family": workflow.workflow_family,
            "source_program": workflow.source_software,
            "analysis_scope": "architecture_independent",
            "domain_metadata_keys": ["dft"],
            "non_decision_contract": NON_DECISION_NOTE,
        },
    )
    claim_by_phase: Dict[tuple[str, str], List[DftHotspotClaim]] = {}
    for claim in workflow.hotspot_claims:
        if claim.claim_kind == "hotspot":
            claim_by_phase.setdefault((claim.stage_id, claim.phase_id), []).append(claim)

    for stage_index, stage in enumerate(workflow.stages):
        stage_node_id = f"stage_{stage_index:02d}_{_safe_id(stage.stage_id)}"
        graph.add_node(ComputeNode(
            node_id=stage_node_id,
            op_type="dft_workflow_stage",
            outputs=[f"{stage_node_id}_token"],
            output_specs={f"{stage_node_id}_token": _small_phase_token_spec()},
            attributes={
                "adapter:dft": {
                    "stage_id": stage.stage_id,
                    "stage_type": stage.stage_type,
                    "source_program": stage.source_program,
                    "coverage_level": stage.coverage_level,
                    "analysis_scope": "architecture_independent",
                }
            },
        ))
        previous_phase_node: Optional[str] = None
        for phase_index, phase in enumerate(stage.phase_skeleton):
            phase_id = str(phase.get("phase_id", f"phase_{phase_index}"))
            phase_node_id = f"{stage_node_id}_phase_{phase_index:02d}_{_safe_id(phase_id)}"
            phase_claims = claim_by_phase.get((stage.stage_id, phase_id), [])
            flops = float(sum(claim.estimated_flops for claim in phase_claims) or phase.get("estimated_flops", 0.0) or 0.0)
            memory_bytes = float(sum(claim.estimated_memory_bytes for claim in phase_claims) or phase.get("estimated_memory_bytes", 0.0) or 0.0)
            graph.add_node(ComputeNode(
                node_id=phase_node_id,
                op_type="dft_phase_skeleton",
                inputs=[f"{stage_node_id}_token"],
                outputs=[f"{phase_node_id}_out"],
                input_specs={f"{stage_node_id}_token": _small_phase_token_spec()},
                output_specs={f"{phase_node_id}_out": _small_phase_token_spec()},
                estimated_flops=flops,
                estimated_memory_bytes=memory_bytes,
                attributes={
                    "adapter:dft": {
                        "stage_id": stage.stage_id,
                        "phase_id": phase_id,
                        "label": phase.get("label", phase_id),
                        "evidence_level": phase.get("evidence_level", "unknown"),
                        "confidence": phase.get("confidence", "unknown"),
                        "analysis_scope": "architecture_independent",
                    }
                },
            ))
            source_for_edge = previous_phase_node or stage_node_id
            graph.add_edge(DataEdge(
                source_for_edge,
                phase_node_id,
                tensor_name=f"{source_for_edge}_to_{phase_node_id}",
                tensor_spec=_small_phase_token_spec(),
                edge_kind="data",
                attributes={"adapter:dft": {"reason": "workflow dependency skeleton; not a selected execution ordering policy"}},
            ))
            previous_phase_node = phase_node_id
            for claim_index, claim in enumerate(phase_claims):
                kernel_node_id = f"{phase_node_id}_hotspot_{claim_index:02d}_{_safe_id(claim.kernel_kind)}"
                graph.add_node(ComputeNode(
                    node_id=kernel_node_id,
                    op_type=claim.kernel_kind,
                    inputs=[f"{phase_node_id}_out"],
                    outputs=[f"{kernel_node_id}_out"],
                    input_specs={f"{phase_node_id}_out": _small_phase_token_spec()},
                    output_specs={f"{kernel_node_id}_out": _small_phase_token_spec()},
                    estimated_flops=float(claim.estimated_flops),
                    estimated_memory_bytes=float(claim.estimated_memory_bytes),
                    attributes={
                        "adapter:dft": {
                            "stage_id": stage.stage_id,
                            "phase_id": phase_id,
                            "claim_id": claim.claim_id,
                            "claim_kind": claim.claim_kind,
                            "evidence_label": claim.evidence_label,
                            "review_status": claim.review_status,
                            "analysis_scope": "architecture_independent",
                        }
                    },
                ))
                graph.add_edge(DataEdge(
                    phase_node_id,
                    kernel_node_id,
                    tensor_name=f"{phase_node_id}_to_{kernel_node_id}",
                    tensor_spec=_small_phase_token_spec(),
                    edge_kind="data",
                    attributes={"adapter:dft": {"reason": "hotspot kernel expansion from evidence-labeled Step1 claim"}},
                ))

    stage_node_by_id = {
        stage.stage_id: f"stage_{index:02d}_{_safe_id(stage.stage_id)}"
        for index, stage in enumerate(workflow.stages)
    }
    for dependency in workflow.dependencies:
        source = stage_node_by_id.get(dependency.source_stage_id)
        target = stage_node_by_id.get(dependency.target_stage_id)
        if source and target:
            graph.add_edge(DataEdge(
                source,
                target,
                tensor_name=f"{source}_to_{target}_artifact",
                tensor_spec=_small_phase_token_spec(),
                edge_kind="data",
                attributes={
                    "adapter:dft": {
                        "dependency_kind": dependency.dependency_kind,
                        "artifact_names": list(dependency.artifact_names),
                        "reason": "stage artifact dependency; not a selected execution ordering policy",
                    }
                },
            ))
    return graph


def _workflow_source_facts(workflow: DftWorkflowSpec) -> List[Dict[str, Any]]:
    """Return de-duplicated source facts preserved by workflow stages."""

    facts: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for stage in workflow.stages:
        for fact in stage.source_facts:
            if not isinstance(fact, Mapping):
                continue
            fact_id = str(fact.get("fact_id") or "")
            key = fact_id or json.dumps(fact, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            facts.append(dict(fact))
    return facts


def _domain_phase_summary_from_workflow(workflow: DftWorkflowSpec) -> Dict[str, Any]:
    """Return an aggregate phase summary for multi-stage DFT workflows."""

    rows: List[Dict[str, Any]] = []
    for stage in workflow.stages:
        for phase in stage.phase_skeleton:
            observed_time = phase.get("observed_time_seconds")
            try:
                observed_time_value = float(observed_time) if observed_time is not None else None
            except (TypeError, ValueError):
                observed_time_value = None
            rows.append({
                "stage_id": stage.stage_id,
                "stage_type": stage.stage_type,
                "phase_id": phase.get("phase_id"),
                "label": phase.get("label", phase.get("phase_id")),
                "kernel_count": int(phase.get("kernel_count", 0) or 0),
                "estimated_flops": float(phase.get("estimated_flops", 0.0) or 0.0),
                "estimated_memory_bytes": float(phase.get("estimated_memory_bytes", 0.0) or 0.0),
                "observed_time_seconds": observed_time_value,
                "observed_time_fraction": None,
                "dominance": phase.get("dominance"),
                "dominance_reason": phase.get("dominance_reason"),
                "evidence_level": phase.get("evidence_level", "unknown"),
                "confidence": phase.get("confidence", "unknown"),
            })
    total_observed = sum(float(row["observed_time_seconds"] or 0.0) for row in rows)
    if total_observed:
        for row in rows:
            row["observed_time_fraction"] = float(row["observed_time_seconds"] or 0.0) / total_observed
    dominant = [
        row for row in rows
        if row.get("dominance") == "dominant"
    ]
    return {
        "schema_version": DFT_PHASE_SUMMARY_SCHEMA,
        "analysis_scope": "architecture_independent",
        "source_program": workflow.source_software,
        "workflow_id": workflow.workflow_id,
        "phase_count": len(rows),
        "stage_count": len(workflow.stages),
        "phase_summaries": rows,
        "dominance_summary": {
            "dominant_phase_ids": [str(row.get("phase_id")) for row in dominant if row.get("phase_id")],
            "dominant_stage_phase_ids": [
                f"{row.get('stage_id')}:{row.get('phase_id')}"
                for row in dominant
                if row.get("stage_id") and row.get("phase_id")
            ],
            "dominance_rule": "workflow domain_phase_summary aggregates per-stage observed profile/log timing facts only; static predicted/user-confirmed dominance claims, when present, live in domain_claim_summary",
        },
        "coverage_summary": {
            "coverage_level": workflow.coverage_level,
            "workflow_family": workflow.workflow_family,
            "source_software": workflow.source_software,
        },
        "review_flags": sorted(set(workflow.review_flags)),
        "limitations": sorted(set(workflow.limitations + [NON_DECISION_NOTE])),
    }


def package_from_dft_workflow(
    workflow: DftWorkflowSpec,
    *,
    profile: Optional[WorkloadProfile | Mapping[str, Any]] = None,
    graph_id: Optional[str] = None,
    source_kind: str = "dft_workflow",
    source_path: Optional[str] = None,
    importer_id: str = "dft_workflow",
    importer_version: str = "v1",
    claim_boundary: str = "diagnostic",
) -> WorkloadPackage:
    """Wrap a normalized DFT workflow in the generic WorkloadPackage contract."""
    graph = build_dft_workflow_graph(workflow, graph_id=graph_id)
    profile_payload = profile.to_dict() if isinstance(profile, WorkloadProfile) else dict(profile or dft_phase_reference_profile().to_dict())
    profile_payload = attach_dft_profile_contract(profile_payload, source_program=workflow.source_software)
    source_facts = _workflow_source_facts(workflow)
    domain_metadata = {
        "dft": {
            "schema_version": "dse.dft.workflow_metadata.v1",
            "workflow": workflow.to_dict(),
            "source_facts": source_facts,
            "source_facts_by_stage": {
                stage.stage_id: [dict(fact) for fact in stage.source_facts]
                for stage in workflow.stages
            },
            "source_program": workflow.source_software,
            "profile_metadata": dft_profile_metadata_contract(source_program=workflow.source_software),
            "claim_boundary": claim_boundary,
            "review_flags": sorted(set(workflow.review_flags)),
            "limitations": sorted(set(workflow.limitations)),
            "non_decision_contract": {
                "analysis_scope": "architecture_independent",
                "note": NON_DECISION_NOTE,
            },
        },
        "characterization": {
            "domain_phase_summary": _domain_phase_summary_from_workflow(workflow),
            "domain_workflow_summary": workflow.workflow_summary(),
            "domain_claim_summary": workflow.claim_summary(),
        },
    }
    return package_from_graph(
        graph,
        workload_id=workflow.workflow_id,
        workload_family=workflow.workflow_family,
        profile_id=str(profile_payload.get("profile_id", workflow.workflow_family)),
        profile_version=str(profile_payload.get("profile_version", "v1")),
        importer_id=importer_id,
        importer_version=importer_version,
        claim_boundary=claim_boundary,
        source_kind=source_kind,
        source_path=source_path,
        domain_metadata=domain_metadata,
        profile=profile_payload,
    )


def package_from_dft_case(
    case: DftCase,
    *,
    profile: Optional[WorkloadProfile | Mapping[str, Any]] = None,
    graph_id: Optional[str] = None,
    source_kind: str = "dft_config",
    source_path: Optional[str] = None,
) -> WorkloadPackage:
    """Wrap a DFT case graph in the generic WorkloadPackage contract."""
    graph = build_dft_phase_graph(case, graph_id=graph_id)
    profile_payload = profile.to_dict() if isinstance(profile, WorkloadProfile) else dict(profile or dft_phase_reference_profile().to_dict())
    profile_payload = attach_dft_profile_contract(profile_payload, source_program=case.source_program)
    workflow = workflow_from_dft_case(case)
    domain_metadata = {
        "dft": {
            **case.to_domain_metadata(),
            "profile_metadata": dft_profile_metadata_contract(source_program=case.source_program),
            "workflow": workflow.to_dict(),
        },
        "characterization": {
            "domain_phase_summary": domain_phase_summary_from_case(case),
            "domain_workflow_summary": workflow.workflow_summary(),
            "domain_claim_summary": workflow.claim_summary(),
        },
    }
    return package_from_graph(
        graph,
        workload_id=case.case_id,
        workload_family=case.workload_family,
        profile_id=case.profile_id,
        profile_version=str(profile_payload.get("profile_version", "v1")),
        importer_id=case.importer_id,
        importer_version="v1",
        claim_boundary=case.claim_boundary,
        source_kind=source_kind,
        source_path=source_path,
        domain_metadata=domain_metadata,
        profile=profile_payload,
    )


def normalize_dft_case_from_facts(
    facts: Iterable[SourceFact | Mapping[str, Any]],
    *,
    case_id: str,
    source_program: str,
    workload_family: str = "dft",
    profile_id: str = "dft_qe_pw_static",
    importer_id: str = "dft_source_facts",
    claim_boundary: str = "diagnostic",
    parameters: Optional[Mapping[str, Any]] = None,
) -> DftCase:
    """Normalize generic DFT source facts into a DftCase."""
    parameters_payload = dict(parameters or {})
    fact_objects = [fact if isinstance(fact, SourceFact) else SourceFact.from_dict(fact) for fact in facts]
    generated_facts, generation_flags = _generated_dimension_facts(fact_objects, parameters_payload)
    all_facts = fact_objects + generated_facts
    merged = merge_source_facts(all_facts)
    summaries = dict(merged["fact_summaries"])
    timing_facts = _phase_timing_facts(all_facts)
    input_parameters = _input_parameters_from_summaries(summaries)
    input_parameters.update({
        key: value
        for key, value in parameters_payload.items()
        if key in {
            "npw",
            "nfft",
            "nbnd",
            "nkb",
            "m",
            "nproj",
            "static_dominance_margin",
            "user_confirmed_dominance",
            "stage_type",
            "calculation",
        }
    })

    phases = _phases_from_facts_and_parameters(timing_facts, summaries, input_parameters)
    review_flags = set(merged.get("review_flags", [])) | set(generation_flags)
    if not timing_facts:
        review_flags.add("insufficient_evidence")
    if _has_unknown_or_extension_phase(phases):
        review_flags.add("segmentation_uncertain")

    limitations = [NON_DECISION_NOTE]
    if generated_facts:
        limitations.append("some kernel dimensions were generated from defaults or heuristics because source evidence was incomplete")
    if not timing_facts:
        limitations.append("no observed profile/log timing was available; phase dominance remains candidate-only")

    coverage = DftCoverageReport(
        claim_boundary=claim_boundary,
        full_workload_reconstruction=claim_boundary in {"full_workload", "full", "end_to_end"} and not generated_facts,
        supported_phase_ids=[phase.phase_id for phase in phases if not phase.phase_id.startswith("unknown:")],
        unsupported_phase_ids=[phase.phase_id for phase in phases if phase.phase_id.startswith("unknown:")],
        unavailable_claims=[
            "dft_numerical_correctness",
            "scientific_result_equivalence",
            "step2_mapping_or_architecture_decision",
        ],
        review_flags=sorted(review_flags),
        notes=["DFT source normalization is an optional Step1 plugin outside the generic core."],
    )
    return DftCase(
        case_id=case_id,
        workload_family=workload_family,
        profile_id=profile_id,
        importer_id=importer_id,
        source_program=source_program,
        source_facts=all_facts,
        fact_summaries=summaries,
        conflicts=list(merged.get("conflicts", [])),
        phases=phases,
        coverage=coverage,
        review_flags=sorted(review_flags),
        input_parameters=input_parameters,
        claim_boundary=claim_boundary,
        limitations=limitations,
    )


def _generated_dimension_facts(facts: Sequence[SourceFact], parameters: Mapping[str, Any]) -> tuple[List[SourceFact], List[str]]:
    existing = {fact.field for fact in facts}
    generated: List[SourceFact] = []
    flags: List[str] = []

    def add(field: str, value: Any, unit: str = "count", reason: str = "missing source dimension") -> None:
        generated.append(SourceFact(
            field=field,
            value=value,
            unit=unit,
            source_type="generated",
            evidence_level="generated_default",
            confidence="low",
            raw_excerpt=reason,
        ))
        flags.append("insufficient_evidence")

    if "dimension.npw" not in existing:
        add("dimension.npw", int(parameters.get("npw", 1024)))
    if "dimension.nbnd" not in existing:
        add("dimension.nbnd", int(parameters.get("nbnd", parameters.get("m", 16))))
    if "dimension.nfft" not in existing:
        nfft = parameters.get("nfft")
        if nfft is None:
            try:
                npw = int(parameters.get("npw", 1024))
                nfft = max(4096, _next_power_of_two(npw * 4))
            except Exception:
                nfft = 4096
        add("dimension.nfft", int(nfft))
    if "dimension.kpoint_count" not in existing and "dimension.kpoint_grid" not in existing:
        add("dimension.kpoint_count", int(parameters.get("kpoint_count", 1)))
    return generated, flags


def _phases_from_facts_and_parameters(
    timing_facts: Sequence[SourceFact],
    summaries: Mapping[str, Any],
    parameters: Mapping[str, Any],
) -> List[DftPhase]:
    dims = _dimensions_from_summaries(summaries, parameters)
    phase_ids: List[str]
    if timing_facts:
        phase_ids = []
        for fact in timing_facts:
            phase_id = _phase_id_from_timing_field(fact.field)
            if phase_id not in phase_ids:
                phase_ids.append(phase_id)
    else:
        phase_ids = _default_phase_ids(summaries)

    timing_by_phase: Dict[str, SourceFact] = {}
    for fact in timing_facts:
        phase_id = _phase_id_from_timing_field(fact.field)
        current = timing_by_phase.get(phase_id)
        if current is None or fact.precedence > current.precedence:
            timing_by_phase[phase_id] = fact

    total_time = sum(float(fact.value or 0.0) for fact in timing_by_phase.values() if _is_number(fact.value))
    max_time = max([float(fact.value or 0.0) for fact in timing_by_phase.values() if _is_number(fact.value)] or [0.0])

    phases: List[DftPhase] = []
    for phase_id in phase_ids:
        timing_fact = timing_by_phase.get(phase_id)
        observed = timing_fact is not None and timing_fact.source_type in OBSERVED_TIMING_SOURCE_TYPES and _is_number(timing_fact.value)
        time_seconds = float(timing_fact.value) if observed else None
        dominance = "candidate"
        dominance_reason = "generated/input-derived phase candidate; no observed dominance evidence"
        confidence = "medium" if observed else "low"
        evidence_level = "observed_timing" if observed else "heuristic_phase"
        if observed:
            fraction = (time_seconds / total_time) if total_time else 0.0
            if time_seconds == max_time and fraction >= 0.4:
                dominance = "dominant"
                dominance_reason = "largest observed profile/log time share"
            else:
                dominance_reason = "observed timing present but phase is not dominant by share"
        source_fact_ids = [timing_fact.fact_id] if timing_fact else []
        kernel = _kernel_for_phase(phase_id, dims, source_fact_ids)
        phases.append(DftPhase(
            phase_id=phase_id,
            label=_phase_label(phase_id),
            kernels=[kernel],
            source_fact_ids=source_fact_ids,
            evidence_level=evidence_level,
            confidence=confidence,
            dominance=dominance,
            dominance_reason=dominance_reason,
            estimated_time_seconds=time_seconds,
            attributes={"analysis_scope": "architecture_independent"},
        ))
    return phases


def _kernel_for_phase(phase_id: str, dims: Mapping[str, int], source_fact_ids: Sequence[str]) -> DftKernelShape:
    npw = max(1, int(dims.get("npw", 1024)))
    nbnd = max(1, int(dims.get("nbnd", dims.get("m", 16))))
    nfft = max(1, int(dims.get("nfft", 4096)))
    nproj = max(1, int(dims.get("nproj", max(4, min(64, nbnd)))))
    kpoints = max(1, int(dims.get("kpoint_count", 1)))
    dtype = "COMPLEX_FP64"

    if phase_id == "setup":
        return DftKernelShape(
            kernel_id="setup_shape",
            op_type="metadata",
            dimensions=dict(dims),
            estimated_flops=0.0,
            estimated_memory_bytes=float((npw + nfft) * 16),
            output_tensors={"setup_state": TensorSpec(shape=(1,), dtype="FP64")},
            source_fact_ids=list(source_fact_ids),
            evidence_level="source_metadata",
            confidence="medium" if source_fact_ids else "low",
        )
    if phase_id == "h_psi":
        flops = float(kpoints * (2 * npw * nbnd * nproj + 2 * nfft * _log2_floor(nfft) * nbnd))
        mem = float(kpoints * (npw * nbnd + npw * nproj + nproj * nbnd) * 16)
        return DftKernelShape(
            kernel_id="h_psi_shape",
            op_type="gemm_fft_composite",
            dimensions=dict(dims),
            estimated_flops=flops,
            estimated_memory_bytes=mem,
            input_tensors={"psi": TensorSpec(shape=(npw, nbnd), dtype=dtype), "potential": TensorSpec(shape=(nfft,), dtype="FP64")},
            output_tensors={"hpsi": TensorSpec(shape=(npw, nbnd), dtype=dtype)},
            source_fact_ids=list(source_fact_ids),
        )
    if phase_id == "fft":
        flops = float(kpoints * nbnd * 5.0 * nfft * _log2_floor(nfft))
        mem = float(kpoints * nbnd * nfft * 16 * 2)
        return DftKernelShape(
            kernel_id="fft_shape",
            op_type="fft",
            dimensions=dict(dims),
            estimated_flops=flops,
            estimated_memory_bytes=mem,
            input_tensors={"reciprocal_grid": TensorSpec(shape=(nfft,), dtype=dtype)},
            output_tensors={"real_grid": TensorSpec(shape=(nfft,), dtype=dtype)},
            source_fact_ids=list(source_fact_ids),
        )
    if phase_id == "diagonalization":
        flops = float(kpoints * 8.0 * nbnd ** 3)
        mem = float(kpoints * (nbnd * nbnd * 16 + nbnd * 8))
        return DftKernelShape(
            kernel_id="diagonalization_shape",
            op_type="eigen",
            dimensions=dict(dims),
            estimated_flops=flops,
            estimated_memory_bytes=mem,
            input_tensors={"subspace_matrix": TensorSpec(shape=(nbnd, nbnd), dtype=dtype)},
            output_tensors={"eigenvectors": TensorSpec(shape=(nbnd, nbnd), dtype=dtype)},
            source_fact_ids=list(source_fact_ids),
        )
    if phase_id == "charge_density":
        flops = float(kpoints * nbnd * nfft * 2.0)
        mem = float((kpoints * nbnd * nfft + nfft) * 16)
        return DftKernelShape(
            kernel_id="charge_density_shape",
            op_type="reduction",
            dimensions=dict(dims),
            estimated_flops=flops,
            estimated_memory_bytes=mem,
            input_tensors={"wavefunctions": TensorSpec(shape=(npw, nbnd), dtype=dtype)},
            output_tensors={"rho": TensorSpec(shape=(nfft,), dtype="FP64")},
            source_fact_ids=list(source_fact_ids),
        )
    if phase_id == "mixing":
        flops = float(nfft * 4.0)
        mem = float(nfft * 8 * 3)
        return DftKernelShape(
            kernel_id="mixing_shape",
            op_type="elementwise",
            dimensions=dict(dims),
            estimated_flops=flops,
            estimated_memory_bytes=mem,
            input_tensors={"rho": TensorSpec(shape=(nfft,), dtype="FP64"), "rho_history": TensorSpec(shape=(nfft,), dtype="FP64")},
            output_tensors={"rho_mixed": TensorSpec(shape=(nfft,), dtype="FP64")},
            source_fact_ids=list(source_fact_ids),
        )
    if phase_id == "augmentation":
        flops = float(kpoints * npw * nproj * nbnd * 2.0)
        mem = float((npw * nproj + nproj * nbnd) * 16)
        return DftKernelShape(
            kernel_id="augmentation_shape",
            op_type="projection_reduction",
            dimensions=dict(dims),
            estimated_flops=flops,
            estimated_memory_bytes=mem,
            input_tensors={"projectors": TensorSpec(shape=(npw, nproj), dtype=dtype)},
            output_tensors={"augmentation_terms": TensorSpec(shape=(nproj, nbnd), dtype=dtype)},
            source_fact_ids=list(source_fact_ids),
        )
    if phase_id in {"forces", "stress"}:
        flops = float(kpoints * nbnd * npw * 4.0)
        mem = float(kpoints * nbnd * npw * 16)
        return DftKernelShape(
            kernel_id=f"{_safe_id(phase_id)}_shape",
            op_type="reduction",
            dimensions=dict(dims),
            estimated_flops=flops,
            estimated_memory_bytes=mem,
            input_tensors={"wavefunctions": TensorSpec(shape=(npw, nbnd), dtype=dtype)},
            output_tensors={f"{_safe_id(phase_id)}_out": TensorSpec(shape=(max(1, int(dims.get("nat", 1))), 3), dtype="FP64")},
            source_fact_ids=list(source_fact_ids),
        )
    if phase_id.startswith("extension:quantum_chemistry:two_electron_integrals"):
        nao = max(1, int(dims.get("nao", nbnd)))
        flops = float(nao ** 4)
        mem = float(nao ** 4 * 8)
        return DftKernelShape(
            kernel_id="two_electron_integrals_shape",
            op_type="tensor_contraction",
            dimensions={**dict(dims), "nao": nao},
            estimated_flops=flops,
            estimated_memory_bytes=mem,
            input_tensors={"basis": TensorSpec(shape=(nao, nao), dtype="FP64")},
            output_tensors={"eri_tensor": TensorSpec(shape=(nao, nao, nao, nao), dtype="FP64")},
            source_fact_ids=list(source_fact_ids),
            confidence="low",
            attributes={"extension_namespace": "quantum_chemistry"},
        )
    if phase_id == "io":
        return DftKernelShape(
            kernel_id="io_shape",
            op_type="io",
            dimensions=dict(dims),
            estimated_flops=0.0,
            estimated_memory_bytes=float((npw * nbnd + nfft) * 16),
            input_tensors={"state": TensorSpec(shape=(1,), dtype="FP64")},
            output_tensors={"checkpoint": TensorSpec(shape=(1,), dtype="FP64")},
            source_fact_ids=list(source_fact_ids),
        )
    return DftKernelShape(
        kernel_id=f"{_safe_id(phase_id)}_shape",
        op_type="custom",
        dimensions=dict(dims),
        estimated_flops=float(npw * nbnd),
        estimated_memory_bytes=float(npw * nbnd * 16),
        input_tensors={"input_state": TensorSpec(shape=(max(1, npw), max(1, nbnd)), dtype=dtype)},
        output_tensors={"output_state": TensorSpec(shape=(max(1, npw), max(1, nbnd)), dtype=dtype)},
        source_fact_ids=list(source_fact_ids),
        confidence="low",
        attributes={"phase_id": phase_id, "reason": "unknown phase shape skeleton"},
    )


def _fallback_kernel_for_phase(phase_id: str, parameters: Mapping[str, Any]) -> DftKernelShape:
    return _kernel_for_phase(phase_id, _dimensions_from_summaries({}, parameters), [])


def _default_phase_ids(summaries: Mapping[str, Any]) -> List[str]:
    calculation = str(_summary_value(summaries, "input.calculation", "scf")).lower()
    if "bands" in calculation:
        return ["setup", "diagonalization", "io"]
    if "dos" in calculation:
        return ["setup", "charge_density", "io"]
    if "projwfc" in calculation or "projection" in calculation:
        return ["setup", "augmentation", "io"]
    if "phonon" in calculation or calculation in {"ph", "dfpt"}:
        return ["setup", "h_psi", "fft", "diagonalization", "charge_density"]
    phases = ["setup", "h_psi", "diagonalization", "fft", "charge_density", "mixing"]
    if "relax" in calculation or "force" in calculation or "md" in calculation:
        phases.append("forces")
    if "vc" in calculation or "stress" in calculation:
        phases.append("stress")
    return phases


def _stage_type_from_case(case: DftCase) -> str:
    calculation = str(case.input_parameters.get("stage_type", case.input_parameters.get("calculation", ""))).lower().replace("-", "_")
    if calculation:
        if "vc" in calculation and "relax" in calculation:
            return "vc_relax"
        if "relax" in calculation:
            return "relax"
        if calculation in {"scf", "nscf", "bands", "dos", "projwfc", "phonon", "ph", "dfpt"}:
            return "phonon" if calculation in {"ph", "dfpt"} else calculation
    program = case.source_program.lower()
    if "bands" in program:
        return "bands"
    if "dos" in program:
        return "dos"
    if "projwfc" in program:
        return "projwfc"
    if "ph" in program:
        return "phonon"
    return "scf"


def _default_stage_inputs(stage_type: str) -> List[str]:
    if stage_type in {"nscf", "bands", "dos", "projwfc", "phonon"}:
        return ["charge_density", "wavefunctions"]
    if stage_type in {"relax", "vc_relax"}:
        return ["structure", "pseudopotentials"]
    return ["structure", "pseudopotentials", "kpoints"]


def _default_stage_outputs(stage_type: str) -> List[str]:
    mapping = {
        "scf": ["charge_density", "wavefunctions"],
        "nscf": ["wavefunctions"],
        "relax": ["relaxed_structure", "forces"],
        "vc_relax": ["relaxed_structure", "stress"],
        "bands": ["band_structure"],
        "dos": ["density_of_states"],
        "projwfc": ["projected_wavefunctions"],
        "phonon": ["dynamical_matrices"],
    }
    return mapping.get(stage_type, ["stage_outputs"])


def _tensor_shapes_for_kernel(kernel: DftKernelShape) -> Dict[str, Any]:
    return {
        "inputs": {name: list(spec.shape) for name, spec in kernel.input_tensors.items()},
        "outputs": {name: list(spec.shape) for name, spec in kernel.output_tensors.items()},
    }


def _confirmed_phase_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {canonicalize_phase_id(item.strip()) for item in value.split(",") if item.strip()}
    if isinstance(value, Iterable):
        return {canonicalize_phase_id(str(item)) for item in value if str(item).strip()}
    return set()


def _predicted_dominance_claim(
    stage_id: str,
    phase_metrics: Sequence[tuple[DftPhase, float, float]],
    margin: float,
) -> Optional[DftHotspotClaim]:
    ranked = sorted(
        [item for item in phase_metrics if item[1] > 0],
        key=lambda item: item[1],
        reverse=True,
    )
    if not ranked:
        return None
    top_phase, top_flops, top_memory = ranked[0]
    second_flops = ranked[1][1] if len(ranked) > 1 else 1.0
    ratio = top_flops / max(1.0, second_flops)
    if ratio < max(1.0, margin):
        return None
    kernel = top_phase.kernels[0] if top_phase.kernels else _fallback_kernel_for_phase(top_phase.phase_id, {})
    return DftHotspotClaim(
        claim_id=f"{stage_id}:{top_phase.phase_id}:predicted:dominance",
        stage_id=stage_id,
        phase_id=top_phase.phase_id,
        kernel_kind=kernel.op_type,
        claim_kind="dominance",
        evidence_label="predicted",
        estimated_flops=top_flops,
        estimated_memory_bytes=top_memory,
        tensor_shapes=_tensor_shapes_for_kernel(kernel),
        complexity_terms={**dict(kernel.dimensions), "dominance_ratio": ratio},
        evidence_level="static_complexity_model",
        confidence="medium",
        source_fact_ids=list(set(top_phase.source_fact_ids + kernel.source_fact_ids)),
        review_status="needs_review",
        reason="static complexity model exceeded configured dominance margin; user review required before strong claim",
        margin=ratio,
    )


def _phase_timing_facts(facts: Sequence[SourceFact]) -> List[SourceFact]:
    return [fact for fact in facts if fact.field.startswith("phase_timing.") and fact.field.endswith(".wall_seconds")]


def _phase_id_from_timing_field(field: str) -> str:
    remainder = field[len("phase_timing."):] if field.startswith("phase_timing.") else field
    return remainder[: -len(".wall_seconds")] if remainder.endswith(".wall_seconds") else remainder


def _dimensions_from_summaries(summaries: Mapping[str, Any], parameters: Mapping[str, Any]) -> Dict[str, int]:
    dims = {
        "npw": _int_value(summaries, "dimension.npw", parameters.get("npw", 1024)) or 1024,
        "nfft": _int_value(summaries, "dimension.nfft", parameters.get("nfft", 4096)) or 4096,
        "nbnd": _int_value(summaries, "dimension.nbnd", parameters.get("nbnd", parameters.get("m", 16))) or 16,
        "nproj": int(parameters.get("nproj", parameters.get("nkb", 0)) or 0),
        "nat": _int_value(summaries, "dimension.nat", parameters.get("nat", 1)) or 1,
        "kpoint_count": _int_value(summaries, "dimension.kpoint_count", parameters.get("kpoint_count", 1)) or 1,
    }
    if not dims["nproj"]:
        dims["nproj"] = max(4, min(64, dims["nbnd"]))
    kgrid = _summary_value(summaries, "dimension.kpoint_grid")
    if isinstance(kgrid, Sequence) and not isinstance(kgrid, (str, bytes)) and len(kgrid) >= 3:
        try:
            dims["kpoint_count"] = max(1, int(kgrid[0]) * int(kgrid[1]) * int(kgrid[2]))
        except Exception:
            pass
    return dims


def _input_parameters_from_summaries(summaries: Mapping[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for field in sorted(summaries):
        if field.startswith(("input.", "dimension.", "parameter.")):
            key = field.split(".", 1)[1]
            payload[key] = _summary_value(summaries, field)
    return payload


def _has_unknown_or_extension_phase(phases: Iterable[DftPhase]) -> bool:
    return any(phase.phase_id.startswith("unknown:") or phase.phase_id.startswith("extension:") for phase in phases)


def _phase_label(phase_id: str) -> str:
    if phase_id.startswith("extension:"):
        return phase_id.replace(":", " ")
    if phase_id.startswith("unknown:"):
        return "unknown source phase"
    return phase_id.replace("_", " ")


def _phase_node_id(phase_id: str, index: int) -> str:
    return f"phase_{index:02d}_{_safe_id(phase_id)}"


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(value)).strip("_") or "item"


def _small_phase_token_spec() -> TensorSpec:
    return TensorSpec(shape=(1,), dtype="FP64")


def _summary_value(summaries: Mapping[str, Any], field: str, default: Any = None) -> Any:
    summary = summaries.get(field)
    if isinstance(summary, Mapping):
        return summary.get("preferred_value", default)
    return default


def _int_value(summaries: Mapping[str, Any], field: str, default: Any = None) -> Optional[int]:
    value = _summary_value(summaries, field, default)
    try:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return int(value[0]) if value else None
        return int(float(str(value).replace("d", "e").replace("D", "e")))
    except Exception:
        return None


def _confidence_rank(confidence: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(confidence).lower(), 0)


def _normalized_value_key(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float):
        return round(value, 12)
    return value


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _next_power_of_two(value: int) -> int:
    value = max(1, int(value))
    return 1 << (value - 1).bit_length()


def _log2_floor(value: int) -> float:
    return max(1.0, math.log2(max(2, int(value))))


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except Exception:
        return False
