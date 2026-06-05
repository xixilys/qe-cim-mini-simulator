#!/usr/bin/env python3
"""Template registry for QE-IC Layer-4 candidate generation."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


def _template(
    *,
    template_id: str,
    family: str,
    target_type: str,
    candidate_type: str,
    motif_categories: list[str],
    motif_ids: list[str] | None = None,
    priority: int = 50,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "template_id": template_id,
        "template_family": family,
        "target_type": target_type,
        "candidate_type": candidate_type,
        "motif_categories": motif_categories,
        "motif_ids": motif_ids or [],
        "priority": priority,
        "default_parameters": dict(parameters or {}),
    }


_TEMPLATES = [
    _template(
        template_id="gpu_baseline_reference",
        family="baseline_reference",
        target_type="gpu_only",
        candidate_type="baseline",
        motif_categories=["*"],
        priority=0,
        parameters={
            "execution_role": "reference_only",
            "next_fidelity_intent": "baseline_context",
        },
    ),
    _template(
        template_id="fpga_streaming_pipeline",
        family="fpga_pipeline",
        target_type="fpga_only",
        candidate_type="fpga_candidate",
        motif_categories=["spectral_transform", "operator_application", "communication"],
        priority=10,
        parameters={
            "pipeline_style": "streaming_dataflow",
            "buffering": "line_or_tile",
            "host_role": "control_and_io_retained",
        },
    ),
    _template(
        template_id="fpga_memory_reuse_engine",
        family="fpga_memory",
        target_type="fpga_only",
        candidate_type="fpga_candidate",
        motif_categories=["memory", "io_memory", "post_processing"],
        priority=20,
        parameters={
            "reuse_strategy": "scratchpad_tile_reuse",
            "memory_binding": "local_bram_uram_when_available",
            "host_role": "control_and_io_retained",
        },
    ),
    _template(
        template_id="fpga_reduction_tree",
        family="fpga_reduction",
        target_type="fpga_only",
        candidate_type="fpga_candidate",
        motif_categories=["communication"],
        motif_ids=["reduction_collective"],
        priority=5,
        parameters={
            "reduction_topology": "tree",
            "accumulation": "deterministic_ordering_required",
            "host_role": "collective_orchestration_retained",
        },
    ),
    _template(
        template_id="fpga_fft_transpose_engine",
        family="fpga_fft",
        target_type="fpga_only",
        candidate_type="fpga_candidate",
        motif_categories=["spectral_transform"],
        motif_ids=["fft_transpose"],
        priority=5,
        parameters={
            "data_mover": "streaming_transpose",
            "tile_schedule": "motif_runtime_weighted",
            "host_role": "scf_control_retained",
        },
    ),
    _template(
        template_id="fpga_projector_pipeline",
        family="fpga_projector",
        target_type="fpga_only",
        candidate_type="fpga_candidate",
        motif_categories=["operator_application"],
        motif_ids=["projector_nonlocal", "hpsi"],
        priority=5,
        parameters={
            "pipeline_style": "operator_stream",
            "precision_policy": "golden_correctness_required_before_claims",
            "host_role": "diagonalization_and_mixing_retained",
        },
    ),
    _template(
        template_id="hybrid_transpose_sidecar",
        family="hybrid_sidecar",
        target_type="gpu_fpga_hybrid",
        candidate_type="hybrid_candidate",
        motif_categories=["spectral_transform"],
        motif_ids=["fft_transpose"],
        priority=5,
        parameters={
            "partition": "gpu_compute_fpga_transpose_sidecar",
            "overlap_intent": "pcie_overlap_candidate",
            "host_role": "control_and_io_retained",
        },
    ),
    _template(
        template_id="hybrid_reduction_sidecar",
        family="hybrid_sidecar",
        target_type="gpu_fpga_hybrid",
        candidate_type="hybrid_candidate",
        motif_categories=["communication"],
        motif_ids=["reduction_collective"],
        priority=5,
        parameters={
            "partition": "gpu_compute_fpga_reduction_sidecar",
            "overlap_intent": "collective_staging_candidate",
            "host_role": "mpi_orchestration_retained",
        },
    ),
    _template(
        template_id="hybrid_dma_overlap_sidecar",
        family="hybrid_dma",
        target_type="gpu_fpga_hybrid",
        candidate_type="hybrid_candidate",
        motif_categories=["memory", "io_memory", "communication"],
        priority=15,
        parameters={
            "partition": "gpu_primary_fpga_dma_overlap",
            "overlap_intent": "hide_transfer_for_repeated_motif",
            "host_role": "runtime_scheduling_retained",
        },
    ),
    _template(
        template_id="hybrid_runtime_controller",
        family="hybrid_runtime",
        target_type="gpu_fpga_hybrid",
        candidate_type="hybrid_candidate",
        motif_categories=["workflow_parallelism", "response_solve", "post_processing"],
        priority=25,
        parameters={
            "partition": "gpu_primary_fpga_runtime_controller",
            "control_scope": "offload_queue_and_dependency_tracking",
            "host_role": "scf_control_retained",
        },
    ),
    _template(
        template_id="hybrid_memory_staging_sidecar",
        family="hybrid_memory",
        target_type="gpu_fpga_hybrid",
        candidate_type="hybrid_candidate",
        motif_categories=["memory", "io_memory"],
        priority=10,
        parameters={
            "partition": "gpu_compute_fpga_memory_staging",
            "staging_scope": "motif_local_reuse_and_transfer_batching",
            "host_role": "control_and_io_retained",
        },
    ),
]


def get_qe_ic_candidate_template_registry() -> dict[str, Any]:
    """Return a JSON-visible template registry."""

    templates = {template["template_id"]: copy.deepcopy(template) for template in _TEMPLATES}
    return {
        "registry_id": "qe_ic_candidate_template_registry_v1",
        "schema_version": "dse.qe_ic.candidate_template_registry.v1",
        "selection_policy": (
            "Templates are selected by target_type, candidate_type, allowed "
            "template family, motif_id override, and motif category fallback."
        ),
        "templates": templates,
    }


def select_templates_for_record(
    record: Mapping[str, Any],
    *,
    motif_registry: Mapping[str, Any],
    allowed_template_families: set[str],
    max_templates: int,
) -> list[dict[str, Any]]:
    """Select target-aware and motif-aware templates for a Layer-3 viability record."""

    target_type = str(record.get("target_type", ""))
    motif_id = str(record.get("motif_id", ""))
    motif = motif_registry.get(motif_id)
    category = str(motif.get("category", "")) if isinstance(motif, Mapping) else ""
    registry = get_qe_ic_candidate_template_registry()["templates"]
    matched: list[dict[str, Any]] = []
    for template in registry.values():
        if template["target_type"] != target_type:
            continue
        if template["template_family"] not in allowed_template_families:
            continue
        motif_ids = set(template.get("motif_ids", []))
        categories = set(template.get("motif_categories", []))
        if "*" not in categories and motif_id not in motif_ids and category not in categories:
            continue
        matched.append(copy.deepcopy(template))
    matched.sort(
        key=lambda template: (
            0 if motif_id in set(template.get("motif_ids", [])) else 1,
            int(template.get("priority", 50)),
            str(template.get("template_id", "")),
        )
    )
    return matched[:max_templates]

