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
from dse_v2.mapping.search_policy import (
    HIERARCHICAL_FUNNEL_STAGES,
    HierarchicalFunnelSearchPolicy,
    SearchProblem,
)

DFT_STEP2_POLICY_ID = "dft-fpga-reference-v1"
DFT_DOMAIN_KEY = "dft"

DFT_HARD_REVIEW_FLAGS = {"project_critical_conflict", "segmentation_uncertain"}
DFT_SOFT_REVIEW_FLAGS = {"insufficient_evidence", "important_input_parameter"}

DFT_ARCHITECTURE_FAMILIES: List[Dict[str, Any]] = [
    {
        "architecture_id": "dft-cpu-baseline-v0",
        "candidate_role": "CPU-only DFT baseline and host-visible fallback reference",
        "phase_groups": ["generic_dft_safe_op", "extension_or_unknown"],
        "source_refs": ["S01", "S03", "S04", "S05", "S06"],
    },
    {
        "architecture_id": "dft-fpga-hbm-streaming-v0",
        "candidate_role": "FPGA/HBM streaming candidate for FFT, density, grid, reductions, and bandwidth-heavy kernels",
        "phase_groups": ["fft_grid_density", "mixing_reduction", "hybrid_exchange", "projector_augmentation"],
        "source_refs": ["S13", "S15", "S16", "S17", "S19", "S20", "S22"],
    },
    {
        "architecture_id": "dft-fpga-fft-grid-v0",
        "candidate_role": "FPGA FFT/grid pipeline candidate for reciprocal/real-space transforms and density grids",
        "phase_groups": ["fft_grid_density"],
        "source_refs": ["S17", "S19", "S20", "S25"],
    },
    {
        "architecture_id": "dft-fpga-systolic-gemm-v0",
        "candidate_role": "FPGA systolic GEMM/batched-GEMM candidate for h_psi, subspace rotation, and hybrid-exchange blocks",
        "phase_groups": ["dense_linear_algebra", "hybrid_exchange"],
        "source_refs": ["S09", "S10", "S21", "S22", "S23"],
    },
    {
        "architecture_id": "dft-fpga-gpu-diag-hybrid-v0",
        "candidate_role": "GPU+FPGA hybrid candidate for diagonalization/dense phases with FPGA streaming sidecar",
        "phase_groups": ["diagonalization", "dense_linear_algebra", "fft_grid_density"],
        "source_refs": ["S03", "S04", "S05", "S06", "S13", "S26"],
    },
    {
        "architecture_id": "dft-memory-rich-hbm-v0",
        "candidate_role": "Memory-rich HBM candidate for FFT/grid/reduction/sparse or block-matrix phases",
        "phase_groups": ["fft_grid_density", "mixing_reduction", "dense_linear_algebra", "projector_augmentation"],
        "source_refs": ["S15", "S16", "S17", "S18", "S24", "S25"],
    },
    {
        "architecture_id": "dft-low-power-fpga-v0",
        "candidate_role": "Energy-constrained FPGA candidate for smaller FFT/GEMM/reduction workloads",
        "phase_groups": ["fft_grid_density", "dense_linear_algebra", "mixing_reduction"],
        "source_refs": ["S11", "S15", "S22", "S23"],
    },
]

DFT_REQUIRED_HARDWARE_TEMPLATE_FAMILY_IDS: Tuple[str, ...] = (
    "streaming_fft_hpsi_pipeline",
    "projector_heavy_gemm_gemv",
    "memory_hbm_dma_transpose",
    "hybrid_cpu_fpga_scf_sidecar",
    "asic_tile_array_template",
)

DFT_EXPLORATORY_TEMPLATE_FAMILY_IDS: Tuple[str, ...] = (
    "wide_exploratory_noc_hls_variants",
)


def _release_policy(lane: str) -> Dict[str, Any]:
    """Return authoritative release/exploratory policy metadata.

    This is deliberately metadata, not a search parameter.  Older artifacts used
    a release/exploratory lane pseudo-parameter; current DFT Step2 artifacts
    keep the lane here so it cannot enter candidate identity, Trial params, or
    formal search knobs.
    """

    normalized = str(lane).strip().lower()
    if normalized not in {"release", "exploratory"}:
        normalized = "exploratory"
    return {
        "lane": normalized,
        "formal_pareto_allowed": normalized == "release",
        "exploratory_only": normalized != "release",
        "authority": "dft_step2_release_policy_metadata",
        "candidate_tier_authoritative": False,
    }


DFT_HARDWARE_TEMPLATE_FAMILIES: Tuple[Dict[str, Any], ...] = (
    {
        "template_family_id": "streaming_fft_hpsi_pipeline",
        "label": "Streaming FFT/Hψ pipeline seed",
        "release_policy": _release_policy("release"),
        "seed_kind": "literature_fpga_hbm_fft_hls_seed",
        "major_kernel_ids": [
            "fft_ifft_ffft",
            "transpose_layout_conversion",
            "hpsi_local_potential",
            "kinetic_add",
            "dma_hbm_movement_engine",
        ],
        "default_knobs": {
            "fft_engine_count": 2,
            "hbm_channels": 4,
            "dma_outstanding": 8,
            "tile_points": 512,
            "reduction_tree_radix": 2,
            "precision_mode": "fp64_strict",
        },
        "source_refs": ["S03", "S15", "S17", "S19", "S20", "S25"],
    },
    {
        "template_family_id": "projector_heavy_gemm_gemv",
        "label": "Projector-heavy GEMM/GEMV seed",
        "release_policy": _release_policy("release"),
        "seed_kind": "projector_dense_tile_hls_seed",
        "major_kernel_ids": [
            "nonlocal_projector",
            "complex_gemm_gemv_tile",
            "reduction_dot_tree",
            "dma_hbm_movement_engine",
        ],
        "default_knobs": {
            "fft_engine_count": 1,
            "hbm_channels": 4,
            "dma_outstanding": 8,
            "tile_points": 256,
            "reduction_tree_radix": 4,
            "precision_mode": "fp64_strict",
        },
        "source_refs": ["S09", "S10", "S21", "S22", "S23"],
    },
    {
        "template_family_id": "memory_hbm_dma_transpose",
        "label": "Memory/HBM DMA transpose seed",
        "release_policy": _release_policy("release"),
        "seed_kind": "fpga_hbm_dma_noc_seed",
        "major_kernel_ids": [
            "transpose_layout_conversion",
            "dma_hbm_movement_engine",
            "fft_ifft_ffft",
            "reduction_dot_tree",
        ],
        "default_knobs": {
            "fft_engine_count": 2,
            "hbm_channels": 8,
            "dma_outstanding": 16,
            "tile_points": 512,
            "reduction_tree_radix": 2,
            "precision_mode": "fp64_strict",
        },
        "source_refs": ["S15", "S16", "S17", "S18", "S19", "S24"],
    },
    {
        "template_family_id": "hybrid_cpu_fpga_scf_sidecar",
        "label": "Hybrid CPU+FPGA full-SCF evaluated sidecar",
        "release_policy": _release_policy("release"),
        "seed_kind": "host_orchestrated_full_scf_evaluated_seed",
        "major_kernel_ids": [
            "fft_ifft_ffft",
            "transpose_layout_conversion",
            "hpsi_local_potential",
            "kinetic_add",
            "nonlocal_projector",
            "complex_gemm_gemv_tile",
            "reduction_dot_tree",
            "dma_hbm_movement_engine",
        ],
        "default_knobs": {
            "fft_engine_count": 2,
            "hbm_channels": 4,
            "dma_outstanding": 8,
            "tile_points": 256,
            "reduction_tree_radix": 4,
            "precision_mode": "fp64_strict",
        },
        "source_refs": ["S03", "S13", "S15", "S22", "GENERIC_DSE_V2"],
    },
    {
        "template_family_id": "asic_tile_array_template",
        "label": "ASIC tile-array comparison template",
        "release_policy": _release_policy("release"),
        "seed_kind": "asic_dc_physical_closure_seed",
        "major_kernel_ids": [
            "hpsi_local_potential",
            "kinetic_add",
            "nonlocal_projector",
            "complex_gemm_gemv_tile",
            "reduction_dot_tree",
        ],
        "default_knobs": {
            "fft_engine_count": 1,
            "hbm_channels": 2,
            "dma_outstanding": 4,
            "tile_points": 256,
            "reduction_tree_radix": 4,
            "precision_mode": "fp64_strict",
        },
        "source_refs": ["S09", "S10", "S21", "GENERIC_DSE_V2"],
    },
    {
        "template_family_id": "wide_exploratory_noc_hls_variants",
        "label": "Wide exploratory NoC/HLS variant space",
        "release_policy": _release_policy("exploratory"),
        "seed_kind": "wide_space_legality_pruning_only",
        "major_kernel_ids": [
            "fft_ifft_ffft",
            "transpose_layout_conversion",
            "hpsi_local_potential",
            "nonlocal_projector",
            "complex_gemm_gemv_tile",
            "dma_hbm_movement_engine",
        ],
        "default_knobs": {
            "fft_engine_count": 4,
            "hbm_channels": 8,
            "dma_outstanding": 16,
            "tile_points": 1024,
            "reduction_tree_radix": 4,
            "precision_mode": "mixed_precision_exploratory",
        },
        "source_refs": ["S15", "S19", "S21", "S22"],
    },
)

_SAFE_GENERIC_OP_PREFERENCES: Dict[str, List[str]] = {
    "gemm": ["gpu", "fpga", "host"],
    "batched_gemm": ["gpu", "fpga", "host"],
    "fft": ["fpga", "gpu", "host"],
    "eigen": ["gpu", "fpga", "host"],
    "eigensolver": ["gpu", "fpga", "host"],
    "sparse_matmul": ["fpga", "gpu", "host"],
    "spmm": ["fpga", "gpu", "host"],
    "reduction": ["fpga", "gpu", "cim", "host"],
    "elementwise": ["gpu", "fpga", "cim", "host"],
    "dma_load": ["fpga", "gpu", "host"],
    "placeholder": ["host"],
}


def dft_hardware_template_families() -> List[Dict[str, Any]]:
    """Return DFT-scoped hardware template families for Step2 search seeding.

    The rows are deliberately outside the generic mapping core.  Release rows
    are seed families allowed to enter formal evidence-gated Pareto ordering;
    the wide exploratory row may guide discovery but must not be treated as
    release-tier Pareto evidence.
    """

    return [
        {
            **dict(row),
            "major_kernel_ids": list(row.get("major_kernel_ids", []) or []),
            "default_knobs": dict(row.get("default_knobs", {}) or {}),
            "release_policy": dict(row.get("release_policy", _release_policy("exploratory"))),
            "source_refs": list(row.get("source_refs", []) or []),
            "claim_boundary": (
                "DFT Step2 template seed only; no hardware acceleration or "
                "PPA claim until the per-kernel evidence ladder closes."
            ),
        }
        for row in DFT_HARDWARE_TEMPLATE_FAMILIES
    ]


def build_dft_hierarchical_search_problem(
    *,
    workload_suite_id: str = "dft_scf_six_class_suite_v1",
) -> SearchProblem:
    """Build the DFT plugin's initial hierarchical funnel search problem."""

    release_template_ids = list(DFT_REQUIRED_HARDWARE_TEMPLATE_FAMILY_IDS)
    all_template_ids = release_template_ids + list(DFT_EXPLORATORY_TEMPLATE_FAMILY_IDS)
    seed_candidates: List[Dict[str, Any]] = []
    for family in dft_hardware_template_families():
        knobs = dict(family["default_knobs"])
        release_policy = dict(family.get("release_policy", _release_policy("exploratory")))
        seed_candidates.append({
            "template_family": family["template_family_id"],
            "seed_kind": family["seed_kind"],
            "seed_priority": 1000 if release_policy.get("formal_pareto_allowed") is True else -100,
            "accelerated_kernel_count": len(family["major_kernel_ids"]),
            **knobs,
        })
    return SearchProblem(
        problem_id=f"{workload_suite_id}:dft_hardware_hierarchical_funnel",
        workload_run_id=workload_suite_id,
        objective="maximize evidence_calibrated_full_scf_throughput",
        parameters={
            "template_family": all_template_ids,
            "fft_engine_count": [1, 2, 4],
            "hbm_channels": [2, 4, 8],
            "dma_outstanding": [4, 8, 16],
            "tile_points": [256, 512, 1024],
            "reduction_tree_radix": [2, 4],
            "precision_mode": ["fp64_strict", "mixed_precision_exploratory"],
        },
        constraints={
            "required_parameters": [
                "template_family",
                "fft_engine_count",
                "hbm_channels",
                "dma_outstanding",
                "tile_points",
                "reduction_tree_radix",
                "precision_mode",
            ],
            "legal_values": {
                "template_family": release_template_ids,
                "precision_mode": ["fp64_strict"],
            },
            "hierarchical_funnel_stages": list(HIERARCHICAL_FUNNEL_STAGES),
            "requires_physical_evidence": True,
            "major_kernel_gate_required": True,
            "claim_boundary": (
                "Wide/template search can order work; formal Pareto remains "
                "release-tier and per-kernel evidence-gated."
            ),
        },
        seed_candidates=tuple(seed_candidates),
    )


def _dft_search_policy_metadata(
    parameters: Mapping[str, Any],
    template_families_by_id: Mapping[str, Mapping[str, Any]],
    release_template_ids: Iterable[str],
    legal_precision_modes: Iterable[str],
) -> Dict[str, Any]:
    template_family = str(parameters.get("template_family", ""))
    family = dict(template_families_by_id.get(template_family, {}) or {})
    release_policy = dict(family.get("release_policy", _release_policy("exploratory")))
    lane = str(release_policy.get("lane", "exploratory"))
    release_templates = {str(item) for item in release_template_ids}
    legal_precisions = {str(item) for item in legal_precision_modes}
    precision_mode = str(parameters.get("precision_mode", ""))
    legal_template_family = template_family in release_templates
    legal_precision_mode = precision_mode in legal_precisions
    release_queue_eligible = release_policy.get("formal_pareto_allowed") is True and legal_template_family
    formal_pareto_eligible = release_queue_eligible and legal_precision_mode
    exploratory_queue_allowed = release_policy.get("exploratory_only") is True or not formal_pareto_eligible
    return {
        "template_policy": {
            "template_family_id": template_family,
            "release_policy": release_policy,
            "release_lane": lane,
            "label": family.get("label"),
            "seed_kind": family.get("seed_kind"),
        },
        "release_policy": release_policy,
        "release_queue_eligible": release_queue_eligible,
        "formal_pareto_eligible": formal_pareto_eligible,
        "exploratory_queue_allowed": exploratory_queue_allowed,
        "legal_template_family": legal_template_family,
        "legal_precision_mode": legal_precision_mode,
        "policy_source": "dft_hardware_template_families",
    }


def _with_dft_policy_metadata(
    record: Mapping[str, Any],
    template_families_by_id: Mapping[str, Mapping[str, Any]],
    release_template_ids: Iterable[str],
    legal_precision_modes: Iterable[str],
) -> Dict[str, Any]:
    enriched = dict(record)
    parameters = dict(enriched.get("parameters", {}) or {})
    parameters.pop("candidate_tier", None)
    enriched["parameters"] = parameters
    enriched["policy_metadata"] = _dft_search_policy_metadata(
        parameters,
        template_families_by_id,
        release_template_ids,
        legal_precision_modes,
    )
    return enriched


def _is_dft_formal_pareto_record(
    record: Mapping[str, Any],
    release_template_ids: Iterable[str],
    legal_precision_modes: Iterable[str],
) -> bool:
    parameters = _as_mapping(record.get("parameters"))
    metadata = _as_mapping(record.get("policy_metadata"))
    release_templates = {str(item) for item in release_template_ids}
    legal_precisions = {str(item) for item in legal_precision_modes}
    return (
        metadata.get("formal_pareto_eligible") is True
        and str(parameters.get("template_family", "")) in release_templates
        and str(parameters.get("precision_mode", "")) in legal_precisions
        and record.get("simulation_eligible") is True
    )


def build_dft_hierarchical_funnel_search_report(
    *,
    workload_suite_id: str = "dft_scf_six_class_suite_v1",
    budget: int = 32,
) -> Dict[str, Any]:
    """Return a replayable DFT hierarchical search report.

    The report is a Step2 planning/search artifact only.  It proves that the
    initial candidate generator separates release and exploratory rows and that
    all required template families can enter the evidence-gated release queue;
    it does not prove that any hardware candidate has closed PPA gates.
    """

    problem = build_dft_hierarchical_search_problem(workload_suite_id=workload_suite_id)
    policy = HierarchicalFunnelSearchPolicy(
        bottleneck_keys=("hbm_channels", "dma_outstanding", "tile_points")
    )
    template_families = dft_hardware_template_families()
    template_families_by_id = {
        str(family["template_family_id"]): family
        for family in template_families
    }
    release_template_ids = set(DFT_REQUIRED_HARDWARE_TEMPLATE_FAMILY_IDS)
    legal_precision_modes = {"fp64_strict"}
    records = [
        _with_dft_policy_metadata(
            record.to_dict(),
            template_families_by_id,
            release_template_ids,
            legal_precision_modes,
        )
        for record in policy.propose(problem, budget=budget)
    ]
    formal_pareto_records = [
        record for record in records
        if _is_dft_formal_pareto_record(record, release_template_ids, legal_precision_modes)
    ]
    exploratory_records = [
        record for record in records
        if not _is_dft_formal_pareto_record(record, release_template_ids, legal_precision_modes)
    ]
    covered_release_template_ids = {
        str(record["parameters"].get("template_family"))
        for record in formal_pareto_records
    }
    exploratory_in_formal = [
        record["candidate_id"]
        for record in formal_pareto_records
        if not record.get("policy_metadata", {}).get("release_queue_eligible")
        or not record.get("policy_metadata", {}).get("legal_precision_mode")
    ]
    missing_release_templates = sorted(release_template_ids - covered_release_template_ids)
    status = "passed" if not missing_release_templates and not exploratory_in_formal else "blocked"
    return {
        "schema_version": "dse.dft.step2.hierarchical_funnel_search_report.v1",
        "status": status,
        "workload_suite_id": workload_suite_id,
        "policy_name": policy.policy_name,
        "funnel_stage_order": list(HIERARCHICAL_FUNNEL_STAGES),
        "template_families": template_families,
        "required_release_template_family_ids": list(DFT_REQUIRED_HARDWARE_TEMPLATE_FAMILY_IDS),
        "exploratory_template_family_ids": list(DFT_EXPLORATORY_TEMPLATE_FAMILY_IDS),
        "candidate_generation": {
            "budget": budget,
            "records_emitted": len(records),
            "formal_pareto_record_count": len(formal_pareto_records),
            "exploratory_record_count": len(exploratory_records),
            "covered_release_template_family_ids": sorted(covered_release_template_ids),
            "missing_release_template_family_ids": missing_release_templates,
            "exploratory_candidate_ids_in_formal_pareto": exploratory_in_formal,
        },
        "wide_space_policy": {
            "wide_space_allowed": True,
            "wide_space_tier": "exploratory",
            "wide_space_can_order_future_work": True,
            "wide_space_can_enter_formal_pareto_without_release_gate": False,
            "seed_sources": [
                "literature_fpga_hbm_fft_designs",
                "existing_fpga_hbm_noc_hls_designs",
                "repo_genericaccel_and_systemc_seed_paths",
            ],
        },
        "formal_pareto_records": formal_pareto_records,
        "exploratory_records": exploratory_records,
        "all_records": records,
        "claim_boundary": (
            "Step2 DFT hierarchical search/candidate-generation report only; "
            "trusted Pareto and speedup require downstream golden, sim, synth, "
            "Vivado/DC, Step4 adjudication, and Step5 reporting evidence."
        ),
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
    dft_metadata = _dft_metadata(policy_input)
    summary = dft_metadata.get("domain_phase_summary")
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
    workflow = _as_mapping(metadata.get("workflow"))
    for stage in workflow.get("stages", []) or []:
        if not isinstance(stage, Mapping):
            continue
        for phase in stage.get("phase_skeleton", []) or []:
            if not isinstance(phase, Mapping) or not phase.get("phase_id"):
                continue
            phase_id = str(phase["phase_id"])
            existing = dict(phases.get(phase_id, {}))
            merged = dict(phase)
            merged.setdefault("stage_ids", [])
            stage_ids = list(merged.get("stage_ids", []) or [])
            if stage.get("stage_id") and stage.get("stage_id") not in stage_ids:
                stage_ids.append(stage.get("stage_id"))
            merged["stage_ids"] = stage_ids
            merged.setdefault("workflow_stage_type", stage.get("stage_type"))
            existing.update({k: v for k, v in merged.items() if v is not None})
            phases[phase_id] = existing
    for claim in workflow.get("hotspot_claims", []) or []:
        if not isinstance(claim, Mapping) or not claim.get("phase_id"):
            continue
        phase_id = str(claim["phase_id"])
        existing = dict(phases.get(phase_id, {}))
        if claim.get("claim_kind") in {"hotspot", "dominance"}:
            existing.setdefault("phase_id", phase_id)
            existing.setdefault("kernel_kind", claim.get("kernel_kind"))
            existing.setdefault("evidence_level", claim.get("evidence_level"))
            if claim.get("claim_kind") == "dominance":
                existing["dominance"] = "dominant"
        phases[phase_id] = existing
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
    if "exx" in phase or "exact_exchange" in phase or "hybrid" in phase or "fock" in phase:
        return "hybrid_exchange"
    if "uspp" in phase or "ultrasoft" in phase or "beta" in phase or "augmentation" in phase:
        return "projector_augmentation"
    if "nonlocal" in phase or "nloc" in phase or "projector" in phase:
        return "projector_augmentation"
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
    if phase_group == "hybrid_exchange":
        return ["fpga", "gpu", "host"], False, "hybrid/exact-exchange phase can seed tiled streaming FPGA/GPU candidates"
    if phase_group == "projector_augmentation":
        return ["fpga", "gpu", "host"], False, "projector/augmentation phase can seed bandwidth-aware FPGA/GPU candidates"
    if phase_group == "dense_linear_algebra":
        return ["fpga", "gpu", "host"], False, "dense linear algebra phase can seed FPGA/GPU candidates"
    if phase_group == "fft_grid_density":
        return ["fpga", "gpu", "host"], False, "FFT/grid/density phase can seed streaming FPGA/HBM candidates"
    if phase_group == "diagonalization":
        return ["gpu", "fpga", "host"], False, "eigensolver phase can seed GPU/FPGA hybrid candidates"
    if phase_group == "mixing_reduction":
        return ["fpga", "gpu", "cim", "host"], False, "mixing/reduction phase can seed reduction-friendly candidates"
    if phase_group == "extension_or_unknown" and op in _SAFE_GENERIC_OP_PREFERENCES:
        return list(_SAFE_GENERIC_OP_PREFERENCES[op]), False, "extension/unknown phase safely mapped by generic op-type preferences"
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
    summary_coverage = _as_mapping(summary.get("coverage_summary"))
    flags.update(str(flag) for flag in summary_coverage.get("review_flags", []) or [])
    for conflict in list(metadata.get("conflicts", []) or []) + list(summary.get("conflicts", []) or []):
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


def _catalog_step3_searchable(catalog: ArchitectureCatalog, architecture_id: str) -> Tuple[bool, List[str]]:
    instance = catalog.instances.get(architecture_id)
    if instance is None:
        return False, ["architecture instance is absent from the active catalog"]
    if not instance.components:
        return False, ["architecture has no concrete component set"]
    binding_id = instance.simulation_bindings.get("systemc")
    if not binding_id:
        return False, ["systemc binding is absent"]
    binding = catalog.simulation_bindings.get(binding_id)
    if binding is None:
        return False, [f"systemc binding {binding_id!r} is absent from catalog"]
    if not binding.is_trusted_eligible():
        return False, [binding.unavailable_reason or "systemc binding is not implemented for timing samples"]
    return True, []


def _dft_architecture_candidates(
    catalog: ArchitectureCatalog,
    phase_groups: Mapping[str, Sequence[str]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    observed_groups = set(str(group) for group in phase_groups)
    candidates: List[Dict[str, Any]] = []
    preferences: List[Dict[str, Any]] = []
    for family in DFT_ARCHITECTURE_FAMILIES:
        architecture_id = str(family["architecture_id"])
        step3_searchable, blockers = _catalog_step3_searchable(catalog, architecture_id)
        matched_groups = sorted(observed_groups & set(str(group) for group in family.get("phase_groups", []) or []))
        candidate = {
            "architecture_id": architecture_id,
            "candidate_role": family["candidate_role"],
            "matched_phase_groups": matched_groups,
            "source_refs": list(family.get("source_refs", []) or []),
            "step3_searchable": step3_searchable,
            "candidate_only": not step3_searchable,
            "step3_blockers": blockers,
            "trusted_final_claim": False,
        }
        candidates.append(candidate)
        score = len(matched_groups)
        if architecture_id == "dft-cpu-baseline-v0":
            score = max(score, 1)
        if score or step3_searchable:
            preferences.append({
                "architecture_id": architecture_id,
                "preference_score": float(score) + (0.25 if step3_searchable else 0.0),
                "matched_phase_groups": matched_groups,
                "reason": (
                    "matches observed DFT phase groups and is Step3-searchable"
                    if matched_groups and step3_searchable
                    else "kept as Step3-searchable baseline/fallback candidate"
                    if step3_searchable
                    else "candidate retained but Step3-blocked until blockers are resolved"
                ),
                "step3_searchable": step3_searchable,
                "trusted_final_claim": False,
            })
    preferences.sort(key=lambda item: (-float(item.get("preference_score", 0.0)), str(item.get("architecture_id"))))
    return candidates, preferences


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
        hard_flags = sorted(set(review_flags) & DFT_HARD_REVIEW_FLAGS)
        soft_flags = sorted(set(review_flags) & DFT_SOFT_REVIEW_FLAGS)
        dominant = _dominant_phase_ids(summary, phases)
        phase_groups = _phase_group_summary(node_hints)
        architecture_candidates, architecture_preferences = _dft_architecture_candidates(catalog, phase_groups)
        architecture_preferences.insert(0, {
            "architecture_id": architecture_id,
            "preference_score": 0.5,
            "reason": "currently selected architecture remains in consideration; DFT policy adds research-derived candidate preferences",
            "step3_searchable": bool(_catalog_step3_searchable(catalog, architecture_id)[0]),
            "trusted_final_claim": False,
        })
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
            architecture_candidates=architecture_candidates,
            architecture_preferences=architecture_preferences,
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
                    "architecture_taxonomy_doc": "docs/architecture/dft_architecture_family_research.md",
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
    "DFT_ARCHITECTURE_FAMILIES",
    "DFT_EXPLORATORY_TEMPLATE_FAMILY_IDS",
    "DFT_HARD_REVIEW_FLAGS",
    "DFT_HARDWARE_TEMPLATE_FAMILIES",
    "DFT_REQUIRED_HARDWARE_TEMPLATE_FAMILY_IDS",
    "DFT_SOFT_REVIEW_FLAGS",
    "DFT_STEP2_POLICY_ID",
    "DftStep2ReferencePolicy",
    "build_dft_hierarchical_funnel_search_report",
    "build_dft_hierarchical_search_problem",
    "dft_hardware_template_families",
    "dft_step2_policy_registry",
    "register_dft_step2_policy",
]
