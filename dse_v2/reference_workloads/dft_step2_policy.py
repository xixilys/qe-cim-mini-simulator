#!/usr/bin/env python3
"""Reference DFT Step2 policy kept outside the generic mapping core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from dse_v2.architecture.catalog import ArchitectureCatalog
from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.mapping.domain_policy import (
    Step2CandidateHints,
    Step2DomainPolicyRegistry,
    Step2PolicyInput,
)

DFT_STEP2_POLICY_ID = "dft-fpga-reference-v1"
DFT_DOMAIN_KEY = "dft"

DFT_HARD_REVIEW_FLAGS = {"project_critical_conflict", "segmentation_uncertain"}
DFT_SOFT_REVIEW_FLAGS = {"insufficient_evidence", "important_input_parameter"}

_SAFE_GENERIC_OP_PREFERENCES: Dict[str, List[str]] = {
    "gemm": ["gpu", "fpga", "host"],
    "batched_gemm": ["gpu", "fpga", "host"],
    "fft": ["fpga", "gpu", "host"],
    "eigen": ["gpu", "fpga", "host"],
    "eigensolver": ["gpu", "fpga", "host"],
    "reduction": ["fpga", "gpu", "cim", "host"],
    "elementwise": ["gpu", "fpga", "cim", "host"],
    "dma_load": ["fpga", "gpu", "host"],
    "placeholder": ["host"],
}


@dataclass(frozen=True)
class _DftNodeHint:
    node_id: str
    op_type: str
    phase_id: str
    phase_group: str
    preferences: List[str]
    candidate_only: bool
    reason: str
    adapter: Dict[str, Any]


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _dft_metadata(policy_input: Step2PolicyInput) -> Dict[str, Any]:
    return _as_mapping(policy_input.workload_package.domain_metadata.get(DFT_DOMAIN_KEY))


def _domain_phase_summary(policy_input: Step2PolicyInput) -> Dict[str, Any]:
    characterization = _as_mapping(policy_input.workload_characterization)
    summary = characterization.get("domain_phase_summary")
    if isinstance(summary, Mapping):
        return dict(summary)
    domain_characterization = _as_mapping(policy_input.workload_package.domain_metadata.get("characterization"))
    summary = domain_characterization.get("domain_phase_summary")
    return dict(summary) if isinstance(summary, Mapping) else {}


def _graph_with_nodes(policy_input: Step2PolicyInput) -> ComputeGraph:
    return policy_input.executable_graph or policy_input.source_graph


def _adapter_nodes(graph: ComputeGraph) -> List[Tuple[str, str, Dict[str, Any]]]:
    nodes: List[Tuple[str, str, Dict[str, Any]]] = []
    for node_id, node in graph.nodes.items():
        adapter = node.attributes.get("adapter:dft")
        if isinstance(adapter, Mapping):
            nodes.append((str(node_id), str(node.op_type), dict(adapter)))
    return nodes


def _phase_records(metadata: Mapping[str, Any], summary: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    phases: Dict[str, Dict[str, Any]] = {}
    for phase in metadata.get("phases", []) or []:
        if isinstance(phase, Mapping) and phase.get("phase_id"):
            phases[str(phase["phase_id"])] = dict(phase)
    for phase in summary.get("phase_summaries", []) or []:
        if isinstance(phase, Mapping) and phase.get("phase_id"):
            existing = dict(phases.get(str(phase["phase_id"]), {}))
            existing.update({k: v for k, v in dict(phase).items() if v is not None})
            phases[str(phase["phase_id"])] = existing
    return phases


def _phase_group(phase_id: str, op_type: str) -> str:
    phase = phase_id.lower()
    op = op_type.lower()
    if phase.startswith("unknown:") or phase.startswith("extension:"):
        return "extension_or_unknown"
    if phase in {"h_psi", "s_psi", "v_psi", "subspace_rotation", "rotate_wfc"} or op in {"gemm", "batched_gemm"}:
        return "dense_linear_algebra"
    if "fft" in phase or "density" in phase or "rho" in phase or "grid" in phase or op == "fft":
        return "fft_grid_density"
    if "diag" in phase or "eigen" in phase or op in {"eigen", "eigensolver"}:
        return "diagonalization"
    if "mix" in phase or "reduction" in phase or op == "reduction":
        return "mixing_reduction"
    if op in _SAFE_GENERIC_OP_PREFERENCES:
        return "generic_dft_safe_op"
    return "generic_dft_candidate"


def _preferences_for(phase_group: str, op_type: str) -> Tuple[List[str], bool, str]:
    op = op_type.lower()
    if phase_group == "dense_linear_algebra":
        return ["fpga", "gpu", "host"], False, "dense linear algebra phase can seed FPGA/GPU candidates"
    if phase_group == "fft_grid_density":
        return ["fpga", "gpu", "host"], False, "FFT/grid/density phase can seed streaming FPGA/HBM candidates"
    if phase_group == "diagonalization":
        return ["gpu", "fpga", "host"], False, "eigensolver phase can seed GPU/FPGA hybrid candidates"
    if phase_group == "mixing_reduction":
        return ["fpga", "gpu", "cim", "host"], False, "mixing/reduction phase can seed reduction-friendly candidates"
    if phase_group == "extension_or_unknown" and op in _SAFE_GENERIC_OP_PREFERENCES:
        return list(_SAFE_GENERIC_OP_PREFERENCES[op]), True, "extension/unknown phase constrained to generic op-type preferences"
    if phase_group == "extension_or_unknown":
        return ["host"], True, "extension/unknown phase remains host-visible until reviewed"
    if op in _SAFE_GENERIC_OP_PREFERENCES:
        return list(_SAFE_GENERIC_OP_PREFERENCES[op]), False, "generic DFT phase uses generic op-type preferences"
    return ["host"], True, "unclassified DFT phase remains candidate-only and host-visible"


def _review_flags(metadata: Mapping[str, Any], summary: Mapping[str, Any]) -> List[str]:
    flags = set(str(flag) for flag in metadata.get("review_flags", []) or [])
    coverage = _as_mapping(metadata.get("coverage"))
    flags.update(str(flag) for flag in coverage.get("review_flags", []) or [])
    flags.update(str(flag) for flag in summary.get("review_flags", []) or [])
    for conflict in metadata.get("conflicts", []) or []:
        if isinstance(conflict, Mapping):
            flags.update(str(flag) for flag in conflict.get("review_flags", []) or [])
    return sorted(flags)


def _node_hints(policy_input: Step2PolicyInput, phases: Mapping[str, Mapping[str, Any]]) -> List[_DftNodeHint]:
    hints: List[_DftNodeHint] = []
    for node_id, op_type, adapter in _adapter_nodes(_graph_with_nodes(policy_input)):
        phase_id = str(adapter.get("phase_id", "unknown:missing_phase"))
        group = _phase_group(phase_id, op_type)
        preferences, candidate_only, reason = _preferences_for(group, op_type)
        phase = _as_mapping(phases.get(phase_id, {}))
        if phase.get("dominance") == "dominant" and "host" in preferences and preferences[-1] != "host":
            preferences = [item for item in preferences if item != "host"] + ["host"]
        hints.append(_DftNodeHint(
            node_id=node_id,
            op_type=op_type,
            phase_id=phase_id,
            phase_group=group,
            preferences=preferences,
            candidate_only=candidate_only,
            reason=reason,
            adapter=adapter,
        ))
    return hints


def _phase_group_summary(hints: Sequence[_DftNodeHint]) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for hint in hints:
        groups.setdefault(hint.phase_group, [])
        if hint.phase_id not in groups[hint.phase_group]:
            groups[hint.phase_group].append(hint.phase_id)
    return {group: sorted(values) for group, values in groups.items()}


def _dominant_phase_ids(summary: Mapping[str, Any], phases: Mapping[str, Mapping[str, Any]]) -> List[str]:
    dominance = _as_mapping(summary.get("dominance_summary"))
    dominant = [str(item) for item in dominance.get("dominant_phase_ids", []) or []]
    if dominant:
        return dominant
    return sorted(str(phase_id) for phase_id, phase in phases.items() if phase.get("dominance") == "dominant")


class DftStep2ReferencePolicy:
    """Reference DFT policy that emits candidate-only Step2 hints."""

    policy_id = DFT_STEP2_POLICY_ID
    domain_key = DFT_DOMAIN_KEY

    def matches(self, policy_input: Step2PolicyInput) -> bool:
        metadata = _dft_metadata(policy_input)
        summary = _domain_phase_summary(policy_input)
        return bool(metadata or summary or _adapter_nodes(_graph_with_nodes(policy_input)))

    def augment_catalog(self, policy_input: Step2PolicyInput, catalog: ArchitectureCatalog) -> ArchitectureCatalog:
        # Lane B emits reference hints only.  Catalog augmentation/ranking is kept
        # additive and may be performed by a later Step2 architecture-candidate lane.
        return catalog

    def build_hints(
        self,
        policy_input: Step2PolicyInput,
        catalog: ArchitectureCatalog,
        architecture_id: str,
    ) -> Step2CandidateHints:
        if not self.matches(policy_input):
            return Step2CandidateHints.no_match(policy_id=self.policy_id, domain_key=self.domain_key)
        metadata = _dft_metadata(policy_input)
        summary = _domain_phase_summary(policy_input)
        phases = _phase_records(metadata, summary)
        node_hints = _node_hints(policy_input, phases)
        review_flags = _review_flags(metadata, summary)
        if any(hint.phase_group == "extension_or_unknown" for hint in node_hints):
            review_flags = sorted(set(review_flags) | {"segmentation_uncertain"})
        hard_flags = sorted(set(review_flags) & DFT_HARD_REVIEW_FLAGS)
        soft_flags = sorted(set(review_flags) & DFT_SOFT_REVIEW_FLAGS)
        dominant = _dominant_phase_ids(summary, phases)
        phase_groups = _phase_group_summary(node_hints)
        node_preferences = {hint.node_id: list(hint.preferences) for hint in node_hints}
        candidate_only_nodes = [hint.node_id for hint in node_hints if hint.candidate_only]
        priority_reasons = [
            "dominant_phase_present" if dominant else "candidate_phase_only",
            "hard_review_gate_present" if hard_flags else "no_hard_review_gate_from_dft_policy",
        ]
        priority_score = max(0.1, 1.0 + (0.5 if dominant else 0.0) - (0.5 if hard_flags else 0.0))
        return Step2CandidateHints(
            policy_id=self.policy_id,
            domain_key=self.domain_key,
            matched=True,
            architecture_candidates=[
                {
                    "architecture_id": "dft-fpga-hbm-streaming-v0",
                    "candidate_role": "FPGA/HBM/host-oriented candidate for FFT, density, grid, and reductions",
                    "candidate_only": True,
                    "trusted_final_claim": False,
                },
                {
                    "architecture_id": "dft-fpga-diag-hybrid-v0",
                    "candidate_role": "FPGA+GPU hybrid candidate for diagonalization and dense phases",
                    "candidate_only": True,
                    "trusted_final_claim": False,
                },
            ],
            architecture_preferences=[
                {
                    "architecture_id": architecture_id,
                    "reason": "selected architecture remains generic; DFT policy only adds optional candidate hints",
                    "trusted_final_claim": False,
                }
            ],
            node_target_preferences=node_preferences,
            mapping_seeds=[
                {
                    "seed_name": f"policy:{self.policy_id}:phase_aware_balanced",
                    "description": "balance DFT phase groups across legal FPGA/GPU/host targets",
                    "node_target_preferences": node_preferences,
                    "candidate_only_nodes": candidate_only_nodes,
                    "trusted_final_claim": False,
                },
                {
                    "seed_name": f"policy:{self.policy_id}:dominant_phase_offload",
                    "description": "prioritize observed dominant DFT phases for accelerator offload when legal",
                    "dominant_phase_ids": dominant,
                    "trusted_final_claim": False,
                },
                {
                    "seed_name": f"policy:{self.policy_id}:host_visible_review_safe",
                    "description": "keep hard-gated, extension, or unknown phases host-visible for user review",
                    "review_flags": review_flags,
                    "candidate_only_nodes": candidate_only_nodes,
                    "trusted_final_claim": False,
                },
            ],
            data_placement={
                "intent": "prefer accelerator-local/HBM streaming buffers for FFT, density, grid, and reduction phase groups when legal",
                "phase_groups": phase_groups,
                "data_locality_intent": "candidate_only",
                "trusted_final_claim": False,
            },
            runtime_schedule={
                "intent": "phase-order-preserving candidate schedule with dominant-phase offload opportunities",
                "dominant_phase_ids": dominant,
                "review_status": "review_required" if review_flags else "no_domain_review_flags",
                "trusted_final_claim": False,
            },
            descriptor_protocol={
                "intent": "preserve generic GSIM descriptor protocol; DFT policy adds no required command fields",
                "claim_boundary": "candidate_only_requires_step3_evidence",
                "trusted_final_claim": False,
            },
            memory_policy={
                "intent": "candidate HBM/streaming locality hints only; no Step2 numerical correctness claim",
                "phase_groups": phase_groups,
                "trusted_final_claim": False,
            },
            review_flags=review_flags,
            hard_block_flags=hard_flags,
            review_required_flags=soft_flags,
            step3_queue={
                "priority_score": priority_score,
                "priority_reasons": priority_reasons,
                "simulation_budget_hint": "selected_entry_only_v1",
                "review_required": bool(review_flags),
                "trusted_final_claim": False,
            },
            annotations={
                "dft": {
                    "source_program": metadata.get("source_program") or summary.get("source_program"),
                    "phase_ids": sorted(phases) or sorted({hint.phase_id for hint in node_hints}),
                    "dominant_phase_ids": dominant,
                    "phase_groups": phase_groups,
                    "node_phase_map": [
                        {
                            "node_id": hint.node_id,
                            "phase_id": hint.phase_id,
                            "phase_group": hint.phase_group,
                            "op_type": hint.op_type,
                            "preferences": list(hint.preferences),
                            "candidate_only": bool(hint.candidate_only),
                            "reason": hint.reason,
                            "source_fact_ids": list(hint.adapter.get("source_fact_ids", []) or []),
                            "evidence_level": hint.adapter.get("evidence_level"),
                            "dominance": hint.adapter.get("dominance"),
                        }
                        for hint in node_hints
                    ],
                    "phase_summaries": list(phases.values()),
                    "review_flags": review_flags,
                    "hard_block_flags": hard_flags,
                    "review_required_flags": soft_flags,
                    "conflicts": list(metadata.get("conflicts", []) or []),
                    "limitations": sorted(set(list(metadata.get("limitations", []) or []) + list(summary.get("limitations", []) or []))),
                    "policy_scope": "candidate_generation_only_no_step2_final_claim",
                }
            },
            trusted_final_claim=False,
        )


def register_dft_step2_policy(registry: Optional[Step2DomainPolicyRegistry] = None) -> Step2DomainPolicyRegistry:
    """Register the reference DFT policy in an explicit Step2 registry."""
    registry = registry or Step2DomainPolicyRegistry()
    return registry.register(DftStep2ReferencePolicy())


def dft_step2_policy_registry() -> Step2DomainPolicyRegistry:
    """Return a registry containing only the explicit DFT reference policy."""
    return register_dft_step2_policy(Step2DomainPolicyRegistry())


__all__ = [
    "DFT_DOMAIN_KEY",
    "DFT_HARD_REVIEW_FLAGS",
    "DFT_SOFT_REVIEW_FLAGS",
    "DFT_STEP2_POLICY_ID",
    "DftStep2ReferencePolicy",
    "dft_step2_policy_registry",
    "register_dft_step2_policy",
]
