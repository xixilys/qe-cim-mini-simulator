#!/usr/bin/env python3
"""Complete DSE search-space foundation for QE/gem5 closure planning.

This module is intentionally domain-neutral at the core candidate-identity
boundary: QE workload facts can seed release-v1 architecture templates, but
workload IDs, evidence fidelity, promotion policy, and tool/blocker state never
enter stable candidate IDs.  The helpers here build a finite release subset and
its freeze-gate artifacts; downstream lanes own QE correctness, gem5 L4 rows,
and final completion claims.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from dse_v2.codesign.release_domain import stable_json_hash

COMPLETE_DSE_SCHEMA = "dse.codesign.complete_dse_search_space.v1"
CANDIDATE_ID_SCHEMA = "dse.codesign.complete_dse_candidate_identity.v1"
RELEASE_ID = "complete_dse_qe_release_v1"

IDENTITY_LAYER_KEYS = (
    "algorithm_parameters",
    "architecture_parameters",
    "mapping_layout_parameters",
    "compile_time_schedule_parameters",
    "runtime_scheduling_parameters",
)

NON_IDENTITY_FIELDS = (
    "workload_case_id",
    "workload_id",
    "evidence_fidelity",
    "evidence_tier",
    "promotion_policy",
    "queue_order",
    "tool_status",
    "blocker_status",
    "retry_count",
    "claim_label",
)

CLAIM_LABELS = (
    "research_projection",
    "screening_projection",
    "release_l3_projection",
    "vertical_slice_only",
    "mvp_partial",
    "l4_trusted_speedup",
    "blocked",
    "deliverable_complete",
)

RESEARCH_ONLY_CLAIMS = (
    "research_projection",
    "screening_projection",
    "blocked",
)
RELEASE_ALLOWED_CLAIMS = (
    "release_l3_projection",
    "vertical_slice_only",
    "mvp_partial",
    "l4_trusted_speedup",
    "blocked",
    "deliverable_complete",
)
BANNED_COMPLETION_SUBSETS = (
    "top_k",
    "representative",
    "pareto",
    "promoted_only",
)

REQUIRED_BASE_FAMILIES = (
    "streaming_pipeline",
    "simd_vector",
    "spatial_pe_array",
    "task_parallel_engines",
)

REQUIRED_HYBRID_TEMPLATES = (
    "pipeline_simd_fused",
    "pipeline_spatial_array",
    "task_parallel_simd",
    "task_parallel_spatial_array",
    "pipeline_task_overlap",
)

REQUIRED_TAXONOMY_IDS = REQUIRED_BASE_FAMILIES + REQUIRED_HYBRID_TEMPLATES


def _stable_hash_without(
    payload: Mapping[str, Any], *excluded_keys: str
) -> str:
    return stable_json_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in excluded_keys
        }
    )


def _as_dict(value: Any, *, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{field_name} must be a non-empty mapping")
    return {str(key): value[key] for key in sorted(value)}


def _indexed_by_id(
    rows: Iterable[Mapping[str, Any]], key: str = "id"
) -> Dict[str, Mapping[str, Any]]:
    indexed: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        row_id = str(row[key])
        if row_id in indexed:
            raise ValueError(f"duplicate {key}: {row_id}")
        indexed[row_id] = row
    return indexed


def canonical_candidate_identity(
    identity_layers: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the hash payload used for stable complete-DSE candidate IDs.

    Only the five semantic identity layers are accepted.  Evaluation metadata is
    deliberately excluded by callers before this function is invoked.
    """
    missing = [
        layer for layer in IDENTITY_LAYER_KEYS if layer not in identity_layers
    ]
    if missing:
        raise ValueError(
            f"missing candidate identity layers: {', '.join(missing)}"
        )

    forbidden = sorted(set(identity_layers).intersection(NON_IDENTITY_FIELDS))
    if forbidden:
        raise ValueError(
            f"non-identity fields supplied as identity layers: {', '.join(forbidden)}"
        )

    layers = {
        layer: _as_dict(identity_layers[layer], field_name=layer)
        for layer in IDENTITY_LAYER_KEYS
    }
    return {
        "schema_version": CANDIDATE_ID_SCHEMA,
        "identity_layer_order": list(IDENTITY_LAYER_KEYS),
        "identity_layers": layers,
        "candidate_id_rule": (
            "cdse_ + sha256(schema + ordered identity layers)[:20]; "
            "workload/evidence/promotion/tool/blocker state excluded"
        ),
        "excluded_fields": list(NON_IDENTITY_FIELDS),
    }


def complete_dse_candidate_id(identity_layers: Mapping[str, Any]) -> str:
    payload = canonical_candidate_identity(identity_layers)
    return "cdse_" + stable_json_hash(payload)[:20]


def build_candidate_record(
    identity_layers: Mapping[str, Any],
    *,
    evaluation_context: Mapping[str, Any] | None = None,
    legality_reasons: Sequence[str] | None = None,
    generation_source: str = "predeclared_release_v1_seed",
) -> Dict[str, Any]:
    identity = canonical_candidate_identity(identity_layers)
    candidate_id = complete_dse_candidate_id(identity_layers)
    legal = not legality_reasons
    record = {
        "schema_version": "dse.codesign.complete_dse_candidate_record.v1",
        "candidate_id": candidate_id,
        "identity": identity,
        "identity_hash": stable_json_hash(identity),
        "legal": legal,
        "illegal_reasons": list(legality_reasons or []),
        "generation_source": generation_source,
        "evaluation_context": dict(evaluation_context or {}),
        "candidate_id_provenance": {
            "identity_layers": list(IDENTITY_LAYER_KEYS),
            "excluded_fields": list(NON_IDENTITY_FIELDS),
            "workload_affects_identity": False,
            "evidence_fidelity_affects_identity": False,
            "promotion_policy_affects_identity": False,
            "tool_status_affects_identity": False,
            "stable_id_requires_all_identity_layers": True,
        },
    }
    record["record_hash"] = _stable_hash_without(record, "record_hash")
    return record


def build_search_space_schema() -> Dict[str, Any]:
    payload = {
        "schema_version": COMPLETE_DSE_SCHEMA,
        "status": "draft",
        "release_id": RELEASE_ID,
        "tiers": {
            "research_space": {
                "purpose": "large hierarchical exploration and screening",
                "finite_release_subset": False,
                "allowed_claims": list(RESEARCH_ONLY_CLAIMS),
                "completion_eligible": False,
            },
            "release_subset": {
                "purpose": "predeclared finite closure universe",
                "finite_release_subset": True,
                "allowed_claims": list(RELEASE_ALLOWED_CLAIMS),
                "completion_eligible": True,
                "completion_rule": (
                    "deliverable_complete only after every legal release candidate "
                    "times every frozen QE mainflow case closes L4 gates"
                ),
            },
        },
        "identity_layers": list(IDENTITY_LAYER_KEYS),
        "non_identity_fields": list(NON_IDENTITY_FIELDS),
        "claim_labels": list(CLAIM_LABELS),
        "anti_downgrade_rules": {
            "research_rows_can_claim_deliverable_complete": False,
            "top_k_or_representative_subset_can_complete": False,
            "projection_or_descriptor_only_can_complete": False,
            "blocked_rows_can_complete": False,
        },
    }
    payload["schema_hash"] = _stable_hash_without(payload, "schema_hash")
    return payload


def build_architecture_taxonomy_manifest() -> Dict[str, Any]:
    base_rows = [
        {
            "id": "streaming_pipeline",
            "kind": "base_family",
            "compute_organization": "streaming/pipelined datapath",
            "release_v1_status": "required",
            "preferred_workload_features": [
                "fft",
                "rho",
                "potential_update",
                "producer_consumer",
            ],
            "claim_boundary": "architecture identity only; evidence rows close separately",
        },
        {
            "id": "simd_vector",
            "kind": "base_family",
            "compute_organization": "vector lanes / SIMD execution",
            "release_v1_status": "required",
            "preferred_workload_features": [
                "residual",
                "mix_rho",
                "vector_update",
                "reduction",
            ],
            "claim_boundary": "architecture identity only; evidence rows close separately",
        },
        {
            "id": "spatial_pe_array",
            "kind": "base_family",
            "compute_organization": "systolic/spatial PE fabric",
            "release_v1_status": "required",
            "preferred_workload_features": [
                "h_psi",
                "s_psi",
                "build_H_sub",
                "dense_block",
            ],
            "claim_boundary": "architecture identity only; evidence rows close separately",
        },
        {
            "id": "task_parallel_engines",
            "kind": "base_family",
            "compute_organization": "multiple task-specific engines",
            "release_v1_status": "required",
            "preferred_workload_features": [
                "multi_kernel_overlap",
                "heterogeneous_qe_iteration",
            ],
            "claim_boundary": "architecture identity only; evidence rows close separately",
        },
    ]
    hybrid_rows = [
        {
            "id": "pipeline_simd_fused",
            "kind": "hybrid_template",
            "compute_organization": "streaming pipeline + SIMD vector",
            "components": ["streaming_pipeline", "simd_vector"],
            "release_v1_status": "required_finite_hybrid",
            "arbitrary_cross_product": False,
        },
        {
            "id": "pipeline_spatial_array",
            "kind": "hybrid_template",
            "compute_organization": "streaming pipeline + spatial PE array",
            "components": ["streaming_pipeline", "spatial_pe_array"],
            "release_v1_status": "required_finite_hybrid",
            "arbitrary_cross_product": False,
        },
        {
            "id": "task_parallel_simd",
            "kind": "hybrid_template",
            "compute_organization": "task engines + SIMD vector",
            "components": ["task_parallel_engines", "simd_vector"],
            "release_v1_status": "required_finite_hybrid",
            "arbitrary_cross_product": False,
        },
        {
            "id": "task_parallel_spatial_array",
            "kind": "hybrid_template",
            "compute_organization": "task engines + spatial PE array",
            "components": ["task_parallel_engines", "spatial_pe_array"],
            "release_v1_status": "required_finite_hybrid",
            "arbitrary_cross_product": False,
        },
        {
            "id": "pipeline_task_overlap",
            "kind": "hybrid_template",
            "compute_organization": "streaming pipeline + task overlap",
            "components": ["streaming_pipeline", "task_parallel_engines"],
            "release_v1_status": "required_finite_hybrid",
            "arbitrary_cross_product": False,
        },
    ]
    rows = base_rows + hybrid_rows
    payload = {
        "schema_version": "dse.codesign.complete_dse.architecture_taxonomy.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "entries": rows,
        "required_base_families": list(REQUIRED_BASE_FAMILIES),
        "required_hybrid_templates": list(REQUIRED_HYBRID_TEMPLATES),
        "arbitrary_base_family_cross_product_allowed": False,
    }
    payload["taxonomy_hash"] = _stable_hash_without(payload, "taxonomy_hash")
    return payload


def build_hybrid_template_manifest() -> Dict[str, Any]:
    taxonomy = build_architecture_taxonomy_manifest()
    hybrids = [
        dict(row)
        for row in taxonomy["entries"]
        if row["kind"] == "hybrid_template"
    ]
    for row in hybrids:
        row["legal_binding_rule"] = (
            "template must appear by id in this manifest; unlisted base-family "
            "composites remain research-only or illegal for release v1"
        )
    payload = {
        "schema_version": "dse.codesign.complete_dse.hybrid_template_manifest.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "templates": hybrids,
        "required_template_ids": list(REQUIRED_HYBRID_TEMPLATES),
    }
    payload["manifest_hash"] = _stable_hash_without(payload, "manifest_hash")
    return payload


def build_algorithm_family_manifest() -> Dict[str, Any]:
    families = [
        {
            "id": "streaming_fft_rho_pipeline",
            "family": "fft_rho_flow",
            "variant": "streamed_density_update",
            "bounded_parameters": {
                "fft_batching": ["per_band"],
                "rho_accumulation": ["streamed"],
            },
            "compatible_taxonomy_ids": [
                "streaming_pipeline",
                "pipeline_simd_fused",
                "pipeline_task_overlap",
            ],
        },
        {
            "id": "blocked_dense_subspace",
            "family": "dense_subspace",
            "variant": "blocked_hpsi_spsi_subspace",
            "bounded_parameters": {
                "block_shape": ["band_block_16"],
                "solver_policy": ["direct_blocked"],
            },
            "compatible_taxonomy_ids": [
                "spatial_pe_array",
                "pipeline_spatial_array",
                "task_parallel_spatial_array",
            ],
        },
        {
            "id": "vector_residual_mixing",
            "family": "vector_update",
            "variant": "residual_mix_reduce",
            "bounded_parameters": {
                "lane_group": ["simd_8"],
                "reduction_tree": ["pairwise"],
            },
            "compatible_taxonomy_ids": [
                "simd_vector",
                "pipeline_simd_fused",
                "task_parallel_simd",
            ],
        },
        {
            "id": "qe_task_graph_overlap",
            "family": "task_graph",
            "variant": "heterogeneous_kernel_overlap",
            "bounded_parameters": {
                "graph_window": ["one_qe_iteration"],
                "fallback": ["host_per_kernel"],
            },
            "compatible_taxonomy_ids": [
                "task_parallel_engines",
                "task_parallel_simd",
                "task_parallel_spatial_array",
                "pipeline_task_overlap",
            ],
        },
    ]
    payload = {
        "schema_version": "dse.codesign.complete_dse.algorithm_family_manifest.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "families": families,
        "finite": True,
    }
    payload["manifest_hash"] = _stable_hash_without(payload, "manifest_hash")
    return payload


def build_mapping_layout_space() -> Dict[str, Any]:
    mappings = [
        {
            "id": "streamed_fft_grid_tiles",
            "tensor_placement": "device_streaming_buffer",
            "memory_hierarchy_target": "dma_stream_to_local_sram",
            "layout": "grid_tile_stream",
            "compatible_taxonomy_ids": [
                "streaming_pipeline",
                "pipeline_simd_fused",
                "pipeline_task_overlap",
            ],
        },
        {
            "id": "band_block_spatial_tiles",
            "tensor_placement": "device_spatial_array_sram",
            "memory_hierarchy_target": "double_buffered_tile_sram",
            "layout": "band_block_tile",
            "compatible_taxonomy_ids": [
                "spatial_pe_array",
                "pipeline_spatial_array",
                "task_parallel_spatial_array",
            ],
        },
        {
            "id": "vector_contiguous_bands",
            "tensor_placement": "device_vector_sram",
            "memory_hierarchy_target": "coalesced_vector_load_store",
            "layout": "contiguous_band_vector",
            "compatible_taxonomy_ids": [
                "simd_vector",
                "pipeline_simd_fused",
                "task_parallel_simd",
            ],
        },
        {
            "id": "task_graph_engine_affinity",
            "tensor_placement": "per_engine_owned_buffers",
            "memory_hierarchy_target": "host_device_queue_payloads",
            "layout": "kernel_payload_by_engine",
            "compatible_taxonomy_ids": [
                "task_parallel_engines",
                "task_parallel_simd",
                "task_parallel_spatial_array",
                "pipeline_task_overlap",
            ],
        },
    ]
    payload = {
        "schema_version": "dse.codesign.complete_dse.mapping_layout_space.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "mappings": mappings,
        "finite": True,
    }
    payload["space_hash"] = _stable_hash_without(payload, "space_hash")
    return payload


def build_compile_schedule_space() -> Dict[str, Any]:
    schedules = [
        {
            "id": "stream_fuse_vectorize",
            "tiling": "stream_tile",
            "loop_order": "producer_consumer",
            "fusion": "fft_rho_fused",
            "vectorization": "stage_local_vectorize",
            "compatible_taxonomy_ids": [
                "streaming_pipeline",
                "pipeline_simd_fused",
                "pipeline_task_overlap",
            ],
        },
        {
            "id": "blocked_gemm_unroll",
            "tiling": "band_block_tile",
            "loop_order": "ijk_blocked",
            "fusion": "subspace_block_fusion",
            "vectorization": "inner_product_unroll",
            "compatible_taxonomy_ids": [
                "spatial_pe_array",
                "pipeline_spatial_array",
                "task_parallel_spatial_array",
            ],
        },
        {
            "id": "vector_tile_reduce",
            "tiling": "band_vector_tile",
            "loop_order": "contiguous_band_major",
            "fusion": "residual_mix_split",
            "vectorization": "simd_lane_reduce",
            "compatible_taxonomy_ids": [
                "simd_vector",
                "pipeline_simd_fused",
                "task_parallel_simd",
            ],
        },
        {
            "id": "kernel_batching_split",
            "tiling": "per_kernel_batch",
            "loop_order": "task_topological",
            "fusion": "split_for_overlap",
            "vectorization": "per_engine_native",
            "compatible_taxonomy_ids": [
                "task_parallel_engines",
                "task_parallel_simd",
                "task_parallel_spatial_array",
                "pipeline_task_overlap",
            ],
        },
    ]
    payload = {
        "schema_version": "dse.codesign.complete_dse.compile_schedule_space.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "compile_time_schedules": schedules,
        "finite": True,
    }
    payload["space_hash"] = _stable_hash_without(payload, "space_hash")
    return payload


def build_runtime_schedule_space() -> Dict[str, Any]:
    schedules = [
        {
            "id": "sync_host_submit",
            "queue_policy": "host_ordered_fifo",
            "engine_assignment": "single_engine",
            "async_overlap": False,
            "control_behavior": "polling_completion",
            "compatible_taxonomy_ids": [
                "streaming_pipeline",
                "simd_vector",
                "spatial_pe_array",
            ],
        },
        {
            "id": "async_dma_compute_overlap",
            "queue_policy": "dma_compute_overlap_fifo",
            "engine_assignment": "stream_or_vector_engine",
            "async_overlap": True,
            "control_behavior": "descriptor_batch_polling",
            "compatible_taxonomy_ids": [
                "streaming_pipeline",
                "pipeline_simd_fused",
                "pipeline_spatial_array",
            ],
        },
        {
            "id": "multi_engine_work_stealing",
            "queue_policy": "work_stealing_ready_queue",
            "engine_assignment": "kernel_class_affinity",
            "async_overlap": True,
            "control_behavior": "interrupt_or_poll_hybrid",
            "compatible_taxonomy_ids": [
                "task_parallel_engines",
                "task_parallel_simd",
                "task_parallel_spatial_array",
            ],
        },
        {
            "id": "pipeline_task_queue_overlap",
            "queue_policy": "pipeline_stage_task_queue",
            "engine_assignment": "pipeline_plus_task_engines",
            "async_overlap": True,
            "control_behavior": "descriptor_batch_with_backpressure",
            "compatible_taxonomy_ids": [
                "pipeline_task_overlap",
                "pipeline_simd_fused",
                "pipeline_spatial_array",
            ],
        },
    ]
    payload = {
        "schema_version": "dse.codesign.complete_dse.runtime_schedule_space.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "runtime_schedules": schedules,
        "finite": True,
    }
    payload["space_hash"] = _stable_hash_without(payload, "space_hash")
    return payload


def build_legality_constraints_manifest() -> Dict[str, Any]:
    constraints = [
        {
            "id": "release_architecture_must_be_predeclared",
            "rejects": "taxonomy_id not in architecture_taxonomy or unlisted base-family composite",
            "reason": "release v1 allows required base families and finite hybrid templates only",
        },
        {
            "id": "algorithm_must_bind_to_architecture",
            "rejects": "algorithm compatible_taxonomy_ids missing taxonomy_id",
            "reason": "algorithm family is not legal for the selected compute organization",
        },
        {
            "id": "mapping_must_bind_to_architecture",
            "rejects": "mapping compatible_taxonomy_ids missing taxonomy_id",
            "reason": "mapping/layout does not satisfy data placement required by architecture",
        },
        {
            "id": "compile_schedule_must_bind_to_architecture",
            "rejects": "compile schedule compatible_taxonomy_ids missing taxonomy_id",
            "reason": "compile-time schedule is unsupported for architecture family/template",
        },
        {
            "id": "runtime_schedule_must_bind_to_architecture",
            "rejects": "runtime schedule compatible_taxonomy_ids missing taxonomy_id",
            "reason": "runtime policy cannot be observed/closed for this architecture template",
        },
        {
            "id": "all_identity_layers_required_before_stable_id",
            "rejects": "candidate missing any complete-DSE identity layer",
            "reason": "stable IDs cannot be emitted until all five design-only identity layers exist",
        },
    ]
    payload = {
        "schema_version": "dse.codesign.complete_dse.legality_constraints.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "constraints": constraints,
        "claim_boundary": "legality classification only; not L4 completion evidence",
    }
    payload["constraints_hash"] = _stable_hash_without(
        payload, "constraints_hash"
    )
    return payload


def _space_indices() -> Dict[str, Dict[str, Mapping[str, Any]]]:
    taxonomy = build_architecture_taxonomy_manifest()
    algorithms = build_algorithm_family_manifest()
    mappings = build_mapping_layout_space()
    compile_space = build_compile_schedule_space()
    runtime_space = build_runtime_schedule_space()
    return {
        "taxonomy": _indexed_by_id(taxonomy["entries"]),
        "algorithm": _indexed_by_id(algorithms["families"]),
        "mapping": _indexed_by_id(mappings["mappings"]),
        "compile": _indexed_by_id(compile_space["compile_time_schedules"]),
        "runtime": _indexed_by_id(runtime_space["runtime_schedules"]),
    }


def _architecture_identity(taxonomy_id: str) -> Dict[str, Any]:
    taxonomy = _space_indices()["taxonomy"][taxonomy_id]
    return {
        "taxonomy_id": taxonomy_id,
        "kind": taxonomy["kind"],
        "compute_organization": taxonomy["compute_organization"],
        "release_v1_status": taxonomy["release_v1_status"],
    }


def _identity_from_seed(seed: Mapping[str, str]) -> Dict[str, Dict[str, Any]]:
    indices = _space_indices()
    taxonomy_id = seed["taxonomy_id"]
    algorithm_id = seed["algorithm_id"]
    mapping_id = seed["mapping_id"]
    compile_id = seed["compile_schedule_id"]
    runtime_id = seed["runtime_schedule_id"]
    return {
        "algorithm_parameters": {
            "algorithm_id": algorithm_id,
            "family": indices["algorithm"][algorithm_id]["family"],
            "variant": indices["algorithm"][algorithm_id]["variant"],
        },
        "architecture_parameters": _architecture_identity(taxonomy_id),
        "mapping_layout_parameters": {
            "mapping_id": mapping_id,
            "layout": indices["mapping"][mapping_id]["layout"],
            "memory_hierarchy_target": indices["mapping"][mapping_id][
                "memory_hierarchy_target"
            ],
        },
        "compile_time_schedule_parameters": {
            "compile_schedule_id": compile_id,
            "tiling": indices["compile"][compile_id]["tiling"],
            "loop_order": indices["compile"][compile_id]["loop_order"],
        },
        "runtime_scheduling_parameters": {
            "runtime_schedule_id": runtime_id,
            "queue_policy": indices["runtime"][runtime_id]["queue_policy"],
            "engine_assignment": indices["runtime"][runtime_id][
                "engine_assignment"
            ],
        },
    }


def default_release_seed_rows() -> list[Dict[str, str]]:
    """Return one pre-freeze legal seed per required base family/hybrid."""
    return [
        {
            "taxonomy_id": "streaming_pipeline",
            "algorithm_id": "streaming_fft_rho_pipeline",
            "mapping_id": "streamed_fft_grid_tiles",
            "compile_schedule_id": "stream_fuse_vectorize",
            "runtime_schedule_id": "async_dma_compute_overlap",
        },
        {
            "taxonomy_id": "simd_vector",
            "algorithm_id": "vector_residual_mixing",
            "mapping_id": "vector_contiguous_bands",
            "compile_schedule_id": "vector_tile_reduce",
            "runtime_schedule_id": "sync_host_submit",
        },
        {
            "taxonomy_id": "spatial_pe_array",
            "algorithm_id": "blocked_dense_subspace",
            "mapping_id": "band_block_spatial_tiles",
            "compile_schedule_id": "blocked_gemm_unroll",
            "runtime_schedule_id": "sync_host_submit",
        },
        {
            "taxonomy_id": "task_parallel_engines",
            "algorithm_id": "qe_task_graph_overlap",
            "mapping_id": "task_graph_engine_affinity",
            "compile_schedule_id": "kernel_batching_split",
            "runtime_schedule_id": "multi_engine_work_stealing",
        },
        {
            "taxonomy_id": "pipeline_simd_fused",
            "algorithm_id": "streaming_fft_rho_pipeline",
            "mapping_id": "streamed_fft_grid_tiles",
            "compile_schedule_id": "stream_fuse_vectorize",
            "runtime_schedule_id": "pipeline_task_queue_overlap",
        },
        {
            "taxonomy_id": "pipeline_spatial_array",
            "algorithm_id": "blocked_dense_subspace",
            "mapping_id": "band_block_spatial_tiles",
            "compile_schedule_id": "blocked_gemm_unroll",
            "runtime_schedule_id": "pipeline_task_queue_overlap",
        },
        {
            "taxonomy_id": "task_parallel_simd",
            "algorithm_id": "vector_residual_mixing",
            "mapping_id": "vector_contiguous_bands",
            "compile_schedule_id": "vector_tile_reduce",
            "runtime_schedule_id": "multi_engine_work_stealing",
        },
        {
            "taxonomy_id": "task_parallel_spatial_array",
            "algorithm_id": "blocked_dense_subspace",
            "mapping_id": "band_block_spatial_tiles",
            "compile_schedule_id": "blocked_gemm_unroll",
            "runtime_schedule_id": "multi_engine_work_stealing",
        },
        {
            "taxonomy_id": "pipeline_task_overlap",
            "algorithm_id": "qe_task_graph_overlap",
            "mapping_id": "task_graph_engine_affinity",
            "compile_schedule_id": "kernel_batching_split",
            "runtime_schedule_id": "pipeline_task_queue_overlap",
        },
    ]


def classify_candidate_legality(
    identity_layers: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    try:
        canonical_candidate_identity(identity_layers)
    except ValueError as exc:
        return False, [str(exc)]

    indices = _space_indices()
    layers = canonical_candidate_identity(identity_layers)["identity_layers"]
    taxonomy_id = str(layers["architecture_parameters"].get("taxonomy_id", ""))
    algorithm_id = str(layers["algorithm_parameters"].get("algorithm_id", ""))
    mapping_id = str(layers["mapping_layout_parameters"].get("mapping_id", ""))
    compile_id = str(
        layers["compile_time_schedule_parameters"].get(
            "compile_schedule_id", ""
        )
    )
    runtime_id = str(
        layers["runtime_scheduling_parameters"].get("runtime_schedule_id", "")
    )

    if taxonomy_id not in indices["taxonomy"]:
        reasons.append(
            "taxonomy_id is not a predeclared release-v1 base family or hybrid template"
        )
    if "+" in taxonomy_id or "x" in taxonomy_id:
        reasons.append(
            "arbitrary base-family Cartesian composites are illegal for release v1"
        )

    for index_name, item_id in [
        ("algorithm", algorithm_id),
        ("mapping", mapping_id),
        ("compile", compile_id),
        ("runtime", runtime_id),
    ]:
        if item_id not in indices[index_name]:
            reasons.append(f"{index_name} id is not declared: {item_id}")

    if reasons or taxonomy_id not in indices["taxonomy"]:
        return False, reasons

    compatibility_checks = [
        (
            "algorithm",
            algorithm_id,
            "algorithm is not compatible with architecture taxonomy",
        ),
        (
            "mapping",
            mapping_id,
            "mapping/layout is not compatible with architecture taxonomy",
        ),
        (
            "compile",
            compile_id,
            "compile-time schedule is not compatible with architecture taxonomy",
        ),
        (
            "runtime",
            runtime_id,
            "runtime schedule is not compatible with architecture taxonomy",
        ),
    ]
    for index_name, item_id, reason in compatibility_checks:
        compatible = indices[index_name][item_id].get(
            "compatible_taxonomy_ids", []
        )
        if taxonomy_id not in compatible:
            reasons.append(reason)
    return not reasons, reasons


def build_research_space_manifest() -> Dict[str, Any]:
    payload = {
        "schema_version": "dse.codesign.complete_dse.research_space_manifest.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "tier": "research_space",
        "hierarchical": True,
        "parameterized": True,
        "stable_candidate_ids_emitted": False,
        "allowed_claims": list(RESEARCH_ONLY_CLAIMS),
        "completion_eligible": False,
        "estimated_broad_candidate_count": 20000,
        "search_methods": [
            "hierarchical_generators",
            "legality_pruning",
            "surrogate_screening",
            "multi_fidelity_promotion",
        ],
        "claim_boundary": "research projections can prioritize work but never satisfy deliverable_complete",
    }
    payload["manifest_hash"] = _stable_hash_without(payload, "manifest_hash")
    return payload


def build_release_subset_manifest(
    seed_rows: Sequence[Mapping[str, str]] | None = None,
) -> Dict[str, Any]:
    rows = list(seed_rows or default_release_seed_rows())
    candidates: list[Dict[str, Any]] = []
    for seed in rows:
        identity_layers = _identity_from_seed(seed)
        legal, reasons = classify_candidate_legality(identity_layers)
        candidates.append(
            build_candidate_record(
                identity_layers,
                evaluation_context={
                    "workload_case_id": "excluded_from_identity",
                    "evidence_tier": "excluded_from_identity",
                    "promotion_policy": "excluded_from_identity",
                    "tool_status": "excluded_from_identity",
                },
                legality_reasons=reasons if not legal else [],
            )
        )
    legal_candidates = [
        candidate for candidate in candidates if candidate["legal"]
    ]
    payload = {
        "schema_version": "dse.codesign.complete_dse.release_subset_manifest.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "tier": "release_subset",
        "finite": True,
        "predeclared": True,
        "identity_layers": list(IDENTITY_LAYER_KEYS),
        "non_identity_fields": list(NON_IDENTITY_FIELDS),
        "candidate_count": len(candidates),
        "legal_candidate_count": len(legal_candidates),
        "illegal_candidate_count": len(candidates) - len(legal_candidates),
        "candidates": candidates,
        "legal_candidate_ids": [
            candidate["candidate_id"] for candidate in legal_candidates
        ],
        "included_taxonomy_ids": [
            candidate["identity"]["identity_layers"][
                "architecture_parameters"
            ]["taxonomy_id"]
            for candidate in candidates
        ],
        "stable_id_status": "emitted_after_all_identity_layers_present",
        "claim_boundary": "release subset identity manifest only; closure evidence is tracked downstream",
    }
    payload["release_subset_hash"] = _stable_hash_without(
        payload, "release_subset_hash"
    )
    return payload


def build_candidate_generation_report(
    release_subset: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    subset = dict(release_subset or build_release_subset_manifest())
    candidates = [
        row for row in subset.get("candidates", []) if isinstance(row, Mapping)
    ]
    all_have_layers = all(
        tuple(candidate.get("identity", {}).get("identity_layers", {}).keys())
        == IDENTITY_LAYER_KEYS
        for candidate in candidates
    )
    payload = {
        "schema_version": "dse.codesign.complete_dse.candidate_generation_report.v1",
        "status": "passed" if all_have_layers and candidates else "failed",
        "release_id": RELEASE_ID,
        "release_subset_hash": subset.get("release_subset_hash"),
        "candidate_count": subset.get("candidate_count", 0),
        "legal_candidate_count": subset.get("legal_candidate_count", 0),
        "all_candidates_have_all_identity_layers": all_have_layers,
        "identity_layers": list(IDENTITY_LAYER_KEYS),
        "excluded_from_identity": list(NON_IDENTITY_FIELDS),
        "stable_candidate_ids_emitted": all_have_layers,
        "candidate_id_rule": "design-only five-layer stable hash; evaluation matrix metadata excluded",
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def build_legality_pruning_report(
    release_subset: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    subset = dict(release_subset or build_release_subset_manifest())
    illegal_probe_identity = _identity_from_seed(
        {
            "taxonomy_id": "streaming_pipeline",
            "algorithm_id": "blocked_dense_subspace",
            "mapping_id": "band_block_spatial_tiles",
            "compile_schedule_id": "blocked_gemm_unroll",
            "runtime_schedule_id": "multi_engine_work_stealing",
        }
    )
    _, illegal_probe_reasons = classify_candidate_legality(
        illegal_probe_identity
    )
    arbitrary_identity = {
        **illegal_probe_identity,
        "architecture_parameters": {
            "taxonomy_id": "streaming_pipeline+spatial_pe_array",
            "kind": "ad_hoc_composite",
            "compute_organization": "unlisted arbitrary composite",
            "release_v1_status": "not_predeclared",
        },
    }
    _, arbitrary_reasons = classify_candidate_legality(arbitrary_identity)
    pruned_rows: list[Dict[str, Any]] = [
        {
            "classification": "illegal",
            "candidate_like_payload": illegal_probe_identity,
            "reasons": illegal_probe_reasons,
        },
        {
            "classification": "illegal",
            "candidate_like_payload": arbitrary_identity,
            "reasons": arbitrary_reasons,
        },
        {
            "classification": "research_only",
            "reason": "additional unlisted hybrids are parked in research space until predeclared",
        },
    ]
    payload = {
        "schema_version": "dse.codesign.complete_dse.legality_pruning_report.v1",
        "status": "passed",
        "release_id": RELEASE_ID,
        "release_subset_hash": subset.get("release_subset_hash"),
        "legal_candidate_count": subset.get("legal_candidate_count", 0),
        "pruned_rows": pruned_rows,
        "all_pruned_rows_have_stable_reason": all(
            row.get("reasons") or row.get("reason") for row in pruned_rows
        ),
        "allowed_pruning_classifications": [
            "illegal",
            "research_only",
            "over_budget",
            "blocked",
        ],
        "claim_boundary": "pruning explains pre-freeze release universe only; it is not completion evidence",
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def build_release_cardinality_budget() -> Dict[str, Any]:
    payload = {
        "schema_version": "dse.codesign.complete_dse.release_cardinality_budget.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "legal_release_candidates_target_min": 64,
        "legal_release_candidates_target_max": 256,
        "legal_release_candidates_hard_cap": 512,
        "frozen_workload_cases_target_min": 4,
        "frozen_workload_cases_hard_cap": 8,
        "l4_evidence_rows_hard_cap": 4096,
        "hybrid_templates_required": len(REQUIRED_HYBRID_TEMPLATES),
        "hybrid_templates_hard_cap": 8,
        "research_to_release_ratio_cap": 0.05,
        "ambition_floor": {
            "required_base_families": list(REQUIRED_BASE_FAMILIES),
            "required_hybrid_templates": list(REQUIRED_HYBRID_TEMPLATES),
            "min_legal_candidate_per_required_taxonomy": 1,
        },
        "claim_boundary": "budget sizes the freeze; it does not reduce closure obligations after freeze",
    }
    payload["budget_hash"] = _stable_hash_without(payload, "budget_hash")
    return payload


def build_release_l4_runtime_cost_report(
    release_subset: Mapping[str, Any] | None = None,
    *,
    frozen_workload_case_count: int = 4,
) -> Dict[str, Any]:
    subset = dict(release_subset or build_release_subset_manifest())
    budget = build_release_cardinality_budget()
    legal_count = int(subset.get("legal_candidate_count") or 0)
    rows = legal_count * frozen_workload_case_count
    status = (
        "passed"
        if rows <= int(budget["l4_evidence_rows_hard_cap"])
        else "blocked"
    )
    payload = {
        "schema_version": "dse.codesign.complete_dse.release_l4_runtime_cost_report.v1",
        "status": status,
        "release_id": RELEASE_ID,
        "release_subset_hash": subset.get("release_subset_hash"),
        "legal_candidate_count": legal_count,
        "frozen_workload_case_count": frozen_workload_case_count,
        "required_l4_evidence_rows": rows,
        "hard_cap": budget["l4_evidence_rows_hard_cap"],
        "claim_boundary": "cost estimate only; missing rows remain blockers for deliverable_complete",
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def _missing_required_taxonomy_ids(
    release_subset: Mapping[str, Any],
) -> list[str]:
    included = set(
        str(item)
        for item in release_subset.get("included_taxonomy_ids", []) or []
    )
    return [
        taxonomy_id
        for taxonomy_id in REQUIRED_TAXONOMY_IDS
        if taxonomy_id not in included
    ]


def build_freeze_gate_verdict(
    release_subset: Mapping[str, Any] | None = None,
    *,
    selection_policy: Mapping[str, Any] | None = None,
    budget: Mapping[str, Any] | None = None,
    research_space: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    subset = dict(release_subset or build_release_subset_manifest())
    policy = dict(
        selection_policy
        or {"selection_kind": "predeclared_finite_release_subset"}
    )
    budget_payload = dict(budget or build_release_cardinality_budget())
    research_payload = dict(research_space or build_research_space_manifest())
    blockers: list[Dict[str, Any]] = []

    legal_count = int(subset.get("legal_candidate_count") or 0)
    hard_cap = int(
        budget_payload.get("legal_release_candidates_hard_cap") or 0
    )
    if legal_count <= 0:
        blockers.append(
            {
                "id": "no_legal_candidates",
                "reason": "release subset has no legal candidates",
            }
        )
    if hard_cap and legal_count > hard_cap:
        blockers.append(
            {
                "id": "candidate_count_over_hard_cap",
                "count": legal_count,
                "hard_cap": hard_cap,
            }
        )

    missing = _missing_required_taxonomy_ids(subset)
    if missing:
        blockers.append(
            {"id": "missing_required_taxonomy_entries", "missing": missing}
        )

    selection_kind = str(policy.get("selection_kind", ""))
    if selection_kind in BANNED_COMPLETION_SUBSETS:
        blockers.append(
            {
                "id": "downgraded_subset_selection",
                "selection_kind": selection_kind,
            }
        )
    if policy.get("fixed_candidate_only") is True:
        blockers.append(
            {
                "id": "fixed_candidate_only_downgrade",
                "reason": "fixed candidate lists cannot replace a generated release universe",
            }
        )

    research_count = int(
        research_payload.get("estimated_broad_candidate_count") or 0
    )
    ratio = (legal_count / research_count) if research_count else 1.0
    ratio_cap = float(
        budget_payload.get("research_to_release_ratio_cap") or 1.0
    )
    if ratio > ratio_cap:
        blockers.append(
            {
                "id": "release_subset_not_ambitiously_pruned",
                "ratio": ratio,
                "cap": ratio_cap,
            }
        )

    all_have_layers = all(
        tuple(candidate.get("identity", {}).get("identity_layers", {}).keys())
        == IDENTITY_LAYER_KEYS
        for candidate in subset.get("candidates", []) or []
        if isinstance(candidate, Mapping)
    )
    if not all_have_layers:
        blockers.append(
            {
                "id": "missing_identity_layer",
                "reason": "all five identity layers are required before freeze",
            }
        )

    payload = {
        "schema_version": "dse.codesign.complete_dse.freeze_gate_verdict.v1",
        "status": "passed" if not blockers else "blocked",
        "release_id": RELEASE_ID,
        "release_subset_hash": subset.get("release_subset_hash"),
        "budget_hash": budget_payload.get("budget_hash"),
        "selection_policy": policy,
        "legal_candidate_count": legal_count,
        "research_to_release_ratio": ratio,
        "blockers": blockers,
        "hard_completion_rule_preserved": not blockers,
        "top_k_or_representative_completion_allowed": False,
        "claim_boundary": "freeze gate only; deliverable_complete still requires downstream L4 matrix closure",
    }
    payload["verdict_hash"] = _stable_hash_without(payload, "verdict_hash")
    return payload


def build_architecture_prior_seed_manifest() -> Dict[str, Any]:
    seeds: list[Dict[str, Any]] = []
    for seed in default_release_seed_rows():
        row: Dict[str, Any] = dict(seed)
        row.update(
            {
                "seed_status": "pre_freeze_release_seed",
                "bounded_parameter_levels": {
                    "algorithm": seed["algorithm_id"],
                    "mapping": seed["mapping_id"],
                    "compile_schedule": seed["compile_schedule_id"],
                    "runtime_schedule": seed["runtime_schedule_id"],
                },
                "owner": "schema_dse_lane",
                "claim_boundary": "seed manifests predeclare release candidates; they are not Top-K completion",
            }
        )
        seeds.append(row)
    payload = {
        "schema_version": "dse.codesign.complete_dse.architecture_prior_seed_manifest.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "seeds": seeds,
        "finite": True,
        "pre_freeze_only": True,
    }
    payload["manifest_hash"] = _stable_hash_without(payload, "manifest_hash")
    return payload


def build_architecture_search_space() -> Dict[str, Any]:
    release_subset = build_release_subset_manifest()
    payload = {
        "schema_version": "dse.codesign.complete_dse.architecture_search_space.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "search_space_schema": build_search_space_schema(),
        "architecture_taxonomy": build_architecture_taxonomy_manifest(),
        "hybrid_template_manifest": build_hybrid_template_manifest(),
        "algorithm_family_manifest": build_algorithm_family_manifest(),
        "mapping_layout_space": build_mapping_layout_space(),
        "compile_schedule_space": build_compile_schedule_space(),
        "runtime_schedule_space": build_runtime_schedule_space(),
        "legality_constraints": build_legality_constraints_manifest(),
        "research_space_manifest": build_research_space_manifest(),
        "architecture_prior_seed_manifest": build_architecture_prior_seed_manifest(),
        "release_subset_manifest": release_subset,
        "candidate_generation_report": build_candidate_generation_report(
            release_subset
        ),
        "legality_pruning_report": build_legality_pruning_report(
            release_subset
        ),
        "release_cardinality_budget": build_release_cardinality_budget(),
        "release_l4_runtime_cost_report": build_release_l4_runtime_cost_report(
            release_subset
        ),
        "freeze_gate_verdict": build_freeze_gate_verdict(release_subset),
        "claim_boundary": "foundation artifacts only; no trusted speedup or completion claim",
    }
    payload["search_space_hash"] = _stable_hash_without(
        payload, "search_space_hash"
    )
    return payload


def validate_architecture_search_space(
    search_space: Mapping[str, Any],
) -> Dict[str, Any]:
    subset = search_space.get("release_subset_manifest", {})
    freeze = search_space.get("freeze_gate_verdict", {})
    candidate_report = search_space.get("candidate_generation_report", {})
    checks = {
        "has_two_tiers": set(
            search_space.get("search_space_schema", {}).get("tiers", {})
        )
        == {"research_space", "release_subset"},
        "candidate_identity_complete": candidate_report.get(
            "all_candidates_have_all_identity_layers"
        )
        is True,
        "required_taxonomy_present": not _missing_required_taxonomy_ids(
            subset if isinstance(subset, Mapping) else {}
        ),
        "freeze_gate_passed": freeze.get("status") == "passed",
        "no_completion_claim": search_space.get("claim_boundary", "").endswith(
            "no trusted speedup or completion claim"
        ),
    }
    payload = {
        "schema_version": "dse.codesign.complete_dse.validation.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "search_space_hash": search_space.get("search_space_hash"),
    }
    payload["validation_hash"] = _stable_hash_without(
        payload, "validation_hash"
    )
    return payload


def artifact_bundle() -> Dict[str, Dict[str, Any]]:
    search_space = build_architecture_search_space()
    return {
        "search_space_schema.json": search_space["search_space_schema"],
        "architecture_taxonomy.json": search_space["architecture_taxonomy"],
        "hybrid_template_manifest.json": search_space[
            "hybrid_template_manifest"
        ],
        "algorithm_family_manifest.json": search_space[
            "algorithm_family_manifest"
        ],
        "mapping_layout_space.json": search_space["mapping_layout_space"],
        "compile_schedule_space.json": search_space["compile_schedule_space"],
        "runtime_schedule_space.json": search_space["runtime_schedule_space"],
        "legality_constraints.json": search_space["legality_constraints"],
        "research_space_manifest.json": search_space[
            "research_space_manifest"
        ],
        "architecture_prior_seed_manifest.json": search_space[
            "architecture_prior_seed_manifest"
        ],
        "release_subset_manifest.json": search_space[
            "release_subset_manifest"
        ],
        "candidate_generation_report.json": search_space[
            "candidate_generation_report"
        ],
        "legality_pruning_report.json": search_space[
            "legality_pruning_report"
        ],
        "release_cardinality_budget.json": search_space[
            "release_cardinality_budget"
        ],
        "release_l4_runtime_cost_report.json": search_space[
            "release_l4_runtime_cost_report"
        ],
        "freeze_gate_verdict.json": search_space["freeze_gate_verdict"],
        "architecture_search_space.json": search_space,
        "validation_report.json": validate_architecture_search_space(
            search_space
        ),
    }


def write_complete_dse_search_space_artifacts(out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = artifact_bundle()
    artifacts: Dict[str, str] = {}
    for name, payload in bundle.items():
        path = out_dir / name
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifacts[name.removesuffix(".json")] = str(path)

    validation = bundle["validation_report.json"]
    status = {
        "schema_version": "dse.codesign.complete_dse.artifact_status.v1",
        "status": validation["status"],
        "release_id": RELEASE_ID,
        "artifacts": artifacts,
        "validation_hash": validation["validation_hash"],
        "claim_boundary": "artifact emission only; no deliverable_complete claim",
    }
    status["status_hash"] = _stable_hash_without(status, "status_hash")
    (out_dir / "status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return status
