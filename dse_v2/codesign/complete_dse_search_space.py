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
DEFAULT_FROZEN_WORKLOAD_CASE_COUNT = 6
PARAMETERIZED_RELEASE_GENERATOR_SOURCE = "bounded_parameterized_release_generator_v1"
LEGACY_PREDECLARED_RELEASE_SOURCE = "predeclared_release_v1_seed_rows"

IDENTITY_LAYER_KEYS = (
    "deployment_boundary_parameters",
    "algorithm_parameters",
    "architecture_parameters",
    "mapping_layout_parameters",
    "compile_time_schedule_parameters",
    "runtime_scheduling_parameters",
    "target_platform_parameters",
)

NON_IDENTITY_FIELDS = (
    "workload_case_id",
    "workload_id",
    "evidence_status",
    "evidence_fidelity",
    "evidence_tier",
    "promotion_policy",
    "promotion_status",
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

PARAMETER_PROFILE_ORDER = (
    "latency_balanced",
    "throughput_scaled",
)

PARAMETER_PROFILES: Dict[str, Dict[str, Any]] = {
    "latency_balanced": {
        "profile_id": "latency_balanced",
        "architecture": {
            "clock_target_mhz": 250,
            "pipeline_depth": "moderate",
            "parallel_lanes": 8,
            "scratchpad_kib": 512,
        },
        "algorithm": {
            "kernel_batching": "small_batch_low_latency",
            "unroll_factor": 2,
        },
        "mapping": {
            "tile_scale": "latency_tile",
            "buffering": "double_buffered",
            "dma_burst_bytes": 256,
        },
        "compile": {
            "ii_target": 1,
            "resource_bias": "balanced_lut_dsp",
        },
        "runtime": {
            "queue_depth": 2,
            "overlap_window": "single_iteration",
        },
    },
    "throughput_scaled": {
        "profile_id": "throughput_scaled",
        "architecture": {
            "clock_target_mhz": 300,
            "pipeline_depth": "deep",
            "parallel_lanes": 16,
            "scratchpad_kib": 1024,
        },
        "algorithm": {
            "kernel_batching": "large_batch_throughput",
            "unroll_factor": 4,
        },
        "mapping": {
            "tile_scale": "throughput_tile",
            "buffering": "ping_pong_hbm",
            "dma_burst_bytes": 512,
        },
        "compile": {
            "ii_target": 1,
            "resource_bias": "throughput_dsp_hbm",
        },
        "runtime": {
            "queue_depth": 4,
            "overlap_window": "multi_kernel_window",
        },
    },
}

REQUIRED_TARGET_PLATFORM_IDS = (
    "fpga_vivado_release_v1",
    "asic_synopsys_dc_release_v1",
)

REQUIRED_TARGET_PLATFORM_KINDS = (
    "fpga",
    "asic",
)

REQUIRED_IDENTITY_LAYER_FIELDS = {
    "deployment_boundary_parameters": (
        "deployment_boundary_id",
        "host_device_partition_id",
        "accelerated_kernels",
        "cpu_retained_stages",
        "descriptor_granularity",
        "fallback_policy",
    ),
    "algorithm_parameters": (
        "algorithm_id",
        "family",
        "variant",
    ),
    "architecture_parameters": (
        "taxonomy_id",
        "kind",
        "compute_organization",
        "release_v1_status",
    ),
    "mapping_layout_parameters": (
        "mapping_id",
        "layout",
        "memory_layout_id",
        "memory_hierarchy_target",
    ),
    "compile_time_schedule_parameters": (
        "compile_schedule_id",
        "tiling",
        "loop_order",
    ),
    "runtime_scheduling_parameters": (
        "runtime_schedule_id",
        "co_scheduling_policy_id",
        "queue_policy",
        "engine_assignment",
    ),
    "target_platform_parameters": (
        "target_platform_id",
        "platform_kind",
        "toolchain_flow",
        "required_claim_gate",
    ),
}

RELEASE_MATRIX_ROW_STATUSES = (
    "trusted_pass",
    "trusted_fail",
    "pruned_with_reason",
    "blocked_missing_input",
    "blocked_tool_unavailable",
    "blocked_invalid_evidence",
    "projection_only_not_claimable",
)

DEFAULT_RELEASE_WORKFLOW_CASES = (
    {
        "workflow_case_id": "release_workflow_case_00",
        "workflow_family": "external_frozen_workflow_suite",
        "workflow_role": "mainflow_case_00",
    },
    {
        "workflow_case_id": "release_workflow_case_01",
        "workflow_family": "external_frozen_workflow_suite",
        "workflow_role": "mainflow_case_01",
    },
    {
        "workflow_case_id": "release_workflow_case_02",
        "workflow_family": "external_frozen_workflow_suite",
        "workflow_role": "mainflow_case_02",
    },
    {
        "workflow_case_id": "release_workflow_case_03",
        "workflow_family": "external_frozen_workflow_suite",
        "workflow_role": "mainflow_case_03",
    },
    {
        "workflow_case_id": "release_workflow_case_04",
        "workflow_family": "external_frozen_workflow_suite",
        "workflow_role": "mainflow_case_04",
    },
    {
        "workflow_case_id": "release_workflow_case_05",
        "workflow_family": "external_frozen_workflow_suite",
        "workflow_role": "mainflow_case_05",
    },
)

DEFAULT_RELEASE_EVIDENCE_GATES = (
    {
        "evidence_gate_id": "golden_correctness",
        "gate_family": "correctness",
        "applies_to_target_platform_kinds": ["fpga", "asic"],
    },
    {
        "evidence_gate_id": "hls_or_rtl_simulation",
        "gate_family": "simulation",
        "applies_to_target_platform_kinds": ["fpga", "asic"],
    },
    {
        "evidence_gate_id": "hls_or_rtl_synthesis",
        "gate_family": "synthesis",
        "applies_to_target_platform_kinds": ["fpga", "asic"],
    },
    {
        "evidence_gate_id": "vivado_synthesis_or_implementation",
        "gate_family": "fpga_tool_closure",
        "applies_to_target_platform_kinds": ["fpga"],
    },
    {
        "evidence_gate_id": "dc_synthesis_timing_area",
        "gate_family": "asic_tool_closure",
        "applies_to_target_platform_kinds": ["asic"],
    },
)

_RELEASE_SUBSET_DERIVED_MATRIX_FIELDS = {
    "candidate_workflow_deployment_target_matrix",
    "candidate_workflow_deployment_target_matrix_rows_hash",
}
_RELEASE_SUBSET_DERIVED_PROVENANCE_FIELDS = {
    "candidate_workflow_deployment_target_matrix_rows_hash",
    "candidate_workflow_deployment_target_matrix_validation_hash",
}


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


def _release_subset_hash_payload(
    release_subset: Mapping[str, Any],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key, value in release_subset.items():
        key_text = str(key)
        if key_text == "release_subset_hash":
            continue
        if key_text in _RELEASE_SUBSET_DERIVED_MATRIX_FIELDS:
            continue
        if key_text == "generation_provenance" and isinstance(value, Mapping):
            payload[key_text] = {
                provenance_key: provenance_value
                for provenance_key, provenance_value in value.items()
                if str(provenance_key)
                not in _RELEASE_SUBSET_DERIVED_PROVENANCE_FIELDS
            }
            continue
        if key_text == "candidates" and isinstance(value, list):
            payload[key_text] = [
                {
                    candidate_key: candidate_value
                    for candidate_key, candidate_value in candidate.items()
                    if str(candidate_key) != "recommendation_input_provenance"
                }
                if isinstance(candidate, Mapping)
                else candidate
                for candidate in value
            ]
            continue
        payload[key_text] = value
    return payload


def _release_subset_hash(release_subset: Mapping[str, Any]) -> str:
    return stable_json_hash(_release_subset_hash_payload(release_subset))


def _as_dict(value: Any, *, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{field_name} must be a non-empty mapping")
    return {str(key): value[key] for key in sorted(value)}


def _missing_identity_layer_fields(
    layers: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    missing: list[str] = []
    for layer_name, required_fields in REQUIRED_IDENTITY_LAYER_FIELDS.items():
        layer = layers.get(layer_name, {})
        for field in required_fields:
            value = layer.get(field) if isinstance(layer, Mapping) else None
            if value in (None, "", [], {}):
                missing.append(f"{layer_name}.{field}")
    return missing


def _forbidden_identity_field_paths(value: Any, *, prefix: str = "") -> list[str]:
    """Return paths where evaluation/workload metadata contaminates identity.

    Candidate identity is allowed to contain only design semantics.  The old
    seven-axis release slice used evidence/promotion metadata as an axis; the
    complete-DSE identity contract rejects those fields even when they are
    nested inside an otherwise valid identity layer.
    """
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in NON_IDENTITY_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_identity_field_paths(child, prefix=path))
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, child in enumerate(value):
            paths.extend(
                _forbidden_identity_field_paths(
                    child, prefix=f"{prefix}[{index}]"
                )
            )
    return paths


def _deterministic_replay_metadata(
    *,
    artifact_name: str,
    builder: str,
    inputs: Mapping[str, Any],
) -> Dict[str, Any]:
    """Describe how a generated release artifact can be rebuilt deterministically."""
    input_hash = stable_json_hash(inputs)
    payload = {
        "schema_version": "dse.codesign.complete_dse.deterministic_replay.v1",
        "artifact_name": artifact_name,
        "builder": builder,
        "input_hash": input_hash,
        "stable_hash_function": "sha256(json.dumps(sort_keys=True,separators=(',', ':')))",
        "replay_command": [
            "python3",
            "dse_v2/scripts/dse/build_complete_dse_search_space_artifacts.py",
            "--out",
            "<output_dir>",
        ],
        "deterministic_ordering": [
            "identity_layer_order",
            "default_release_seed_rows",
            "candidate_id",
            "artifact file name",
        ],
        "claim_boundary": "replay metadata proves deterministic artifact regeneration only",
    }
    payload["replay_hash"] = _stable_hash_without(payload, "replay_hash")
    return payload


def _candidate_record_hash(candidate: Mapping[str, Any]) -> str:
    """Hash the stable candidate record while excluding derived self-refs."""

    return stable_json_hash(
        {
            key: value
            for key, value in candidate.items()
            if key not in {"record_hash", "recommendation_input_provenance"}
        }
    )


def _release_universe_artifact_provenance(
    *,
    release_subset: Mapping[str, Any],
    matrix: Mapping[str, Any],
    matrix_validation: Mapping[str, Any],
    candidate: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    generation_provenance = release_subset.get("generation_provenance", {})
    generation_provenance = (
        generation_provenance
        if isinstance(generation_provenance, Mapping)
        else {}
    )
    payload: Dict[str, Any] = {
        "release_subset_artifact": "release_subset_manifest.json",
        "release_subset_hash": release_subset.get("release_subset_hash"),
        "candidate_workflow_deployment_target_matrix_artifact": (
            "candidate_workflow_deployment_target_matrix.json"
        ),
        "candidate_workflow_deployment_target_matrix_hash": matrix.get(
            "matrix_hash"
        ),
        "candidate_workflow_deployment_target_matrix_validation_artifact": (
            "candidate_workflow_deployment_target_matrix_validation.json"
        ),
        "candidate_workflow_deployment_target_matrix_validation_hash": (
            matrix_validation.get("validation_hash")
        ),
        "release_pruning_rationale_artifact": (
            "release_pruning_rationale_report.json"
        ),
        "release_pruning_rationale_hash": generation_provenance.get(
            "pruning_rationale_hash"
        ),
        "legality_constraints_artifact": "legality_constraints_manifest.json",
        "legality_constraints_hash": generation_provenance.get(
            "legality_constraints_hash"
        ),
        "deterministic_replay_hash": (
            (release_subset.get("deterministic_replay", {}) or {}).get(
                "replay_hash"
            )
            if isinstance(release_subset.get("deterministic_replay", {}), Mapping)
            else None
        ),
    }
    if candidate is not None:
        payload.update(
            {
                "candidate_id": candidate.get("candidate_id"),
                "candidate_record_hash": candidate.get("record_hash"),
                "candidate_identity_hash": candidate.get("identity_hash"),
            }
        )
    return payload


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


def _count_values(values: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _duplicate_values(values: Iterable[str]) -> list[Dict[str, Any]]:
    return [
        {"value": value, "count": count}
        for value, count in _count_values(values).items()
        if count > 1
    ]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def canonical_candidate_identity(
    identity_layers: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the hash payload used for stable complete-DSE candidate IDs.

    Only the declared semantic identity layers are accepted.  Evaluation
    metadata is deliberately excluded by callers before this function is
    invoked.
    """
    missing = [
        layer for layer in IDENTITY_LAYER_KEYS if layer not in identity_layers
    ]
    if missing:
        raise ValueError(
            f"missing candidate identity layers: {', '.join(missing)}"
        )

    unexpected = sorted(set(identity_layers) - set(IDENTITY_LAYER_KEYS))
    unexpected_non_identity = [
        field for field in unexpected if field in NON_IDENTITY_FIELDS
    ]
    unexpected_design = [
        field for field in unexpected if field not in NON_IDENTITY_FIELDS
    ]
    if unexpected_design:
        raise ValueError(
            f"unknown candidate identity layers: {', '.join(unexpected_design)}"
        )

    forbidden = sorted(set(_forbidden_identity_field_paths(identity_layers)))
    forbidden.extend(
        field
        for field in unexpected_non_identity
        if field not in forbidden
    )
    if forbidden:
        raise ValueError(
            f"non-identity fields supplied as identity layers: {', '.join(forbidden)}"
        )

    layers = {
        layer: _as_dict(identity_layers[layer], field_name=layer)
        for layer in IDENTITY_LAYER_KEYS
    }
    missing_fields = _missing_identity_layer_fields(layers)
    if missing_fields:
        raise ValueError(
            "missing required candidate identity fields: "
            + ", ".join(missing_fields)
        )
    return {
        "schema_version": CANDIDATE_ID_SCHEMA,
        "identity_layer_order": list(IDENTITY_LAYER_KEYS),
        "identity_layers": layers,
        "candidate_id_rule": (
            "cdse_ + sha256(schema + ordered identity layers)[:20]; "
            "deployment/partition/mapping/runtime/target design semantics included; "
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
    record["record_hash"] = _candidate_record_hash(record)
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
        "required_identity_layer_fields": {
            layer: list(fields)
            for layer, fields in REQUIRED_IDENTITY_LAYER_FIELDS.items()
        },
        "non_identity_fields": list(NON_IDENTITY_FIELDS),
        "release_matrix_row_statuses": list(RELEASE_MATRIX_ROW_STATUSES),
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


def build_parameter_profile_manifest() -> Dict[str, Any]:
    """Return bounded release-v1 tunable profiles used by candidate generation.

    The release subset must be a generated, parameterized universe rather than
    one hand-picked candidate per taxonomy.  These profiles add deterministic
    design parameters to the stable identity layers while keeping workload,
    evidence, promotion, tool, blocker, and claim state out of identity.
    """

    profiles = [
        {
            **PARAMETER_PROFILES[profile_id],
            "claim_boundary": (
                "bounded design-tunable profile only; downstream L3/L4/EDA "
                "evidence still decides performance and claim eligibility"
            ),
        }
        for profile_id in PARAMETER_PROFILE_ORDER
    ]
    payload = {
        "schema_version": "dse.codesign.complete_dse.parameter_profile_manifest.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "profile_count": len(profiles),
        "profile_ids": list(PARAMETER_PROFILE_ORDER),
        "profiles": profiles,
        "identity_layer_participation": {
            "algorithm_parameters": True,
            "architecture_parameters": True,
            "mapping_layout_parameters": True,
            "compile_time_schedule_parameters": True,
            "runtime_scheduling_parameters": True,
            "target_platform_parameters": True,
            "workload_or_evidence_state": False,
        },
        "claim_boundary": (
            "parameter profiles size the frozen release search universe; they "
            "are not timing, PPA, correctness, or completion evidence"
        ),
    }
    payload["manifest_hash"] = _stable_hash_without(payload, "manifest_hash")
    return payload


def build_target_platform_space() -> Dict[str, Any]:
    platforms = [
        {
            "id": "fpga_vivado_release_v1",
            "platform_kind": "fpga",
            "toolchain_flow": "hls_or_rtl_to_vivado",
            "required_claim_gate": "hls_or_rtl_sim_synth_plus_vivado_synth_impl_timing_utilization",
            "claim_boundary": (
                "target identity only; FPGA claims still require "
                "FPGA/HLS/RTL/Vivado evidence rows"
            ),
        },
        {
            "id": "asic_synopsys_dc_release_v1",
            "platform_kind": "asic",
            "toolchain_flow": "rtl_to_synopsys_dc",
            "required_claim_gate": "rtl_sim_plus_dc_synthesis_timing_area_power",
            "claim_boundary": (
                "target identity only; ASIC claims still require "
                "RTL/DC/timing/area evidence rows"
            ),
        },
    ]
    payload = {
        "schema_version": "dse.codesign.complete_dse.target_platform_space.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "target_platforms": platforms,
        "required_target_platform_ids": list(REQUIRED_TARGET_PLATFORM_IDS),
        "required_target_platform_kinds": list(REQUIRED_TARGET_PLATFORM_KINDS),
        "finite": True,
        "claim_boundary": (
            "target-platform identity space only; tool evidence gates close "
            "downstream and never enter candidate identity"
        ),
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
            "reason": "stable IDs cannot be emitted until all required design-only identity layers exist",
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


def build_workload_architecture_prior_report() -> Dict[str, Any]:
    """Describe pre-freeze QE workload priors without making workload an axis."""
    seed_rows: list[Dict[str, Any]] = []
    feature_map = {
        "streaming_pipeline": [
            "fft_grid_stream",
            "rho_accumulation",
            "producer_consumer_density_update",
        ],
        "simd_vector": [
            "band_residual_update",
            "mix_rho_vector_reduction",
            "contiguous_band_iteration",
        ],
        "spatial_pe_array": [
            "h_psi_s_psi_dense_blocks",
            "subspace_diagonalization",
            "band_block_linear_algebra",
        ],
        "task_parallel_engines": [
            "heterogeneous_kernel_graph",
            "independent_qe_kernel_classes",
            "host_fallback_per_kernel",
        ],
        "pipeline_simd_fused": [
            "mixed_fft_vector_update_flow",
            "streamed_density_plus_residual_path",
        ],
        "pipeline_spatial_array": [
            "streaming_frontend_plus_dense_block_backend",
            "fft_to_hpsi_pipeline",
        ],
        "task_parallel_simd": [
            "task_graph_with_vector_residuals",
            "multi_kernel_vector_update_overlap",
        ],
        "task_parallel_spatial_array": [
            "task_graph_with_dense_subspace_kernels",
            "mixed_engine_hpsi_spsi_overlap",
        ],
        "pipeline_task_overlap": [
            "pipeline_stages_overlapped_with_qe_task_windows",
            "producer_consumer_task_queue",
        ],
    }
    for seed in default_release_seed_rows():
        taxonomy_id = seed["taxonomy_id"]
        seed_rows.append(
            {
                "taxonomy_id": taxonomy_id,
                "seed": dict(seed),
                "qe_workload_features": feature_map[taxonomy_id],
                "prior_rule": "pre_freeze_seed_only",
                "may_remove_frozen_rows": False,
                "candidate_identity_participation": False,
                "claim_boundary": (
                    "workload facts justify pre-freeze seed inclusion; "
                    "candidate identity remains design-only"
                ),
            }
        )
    payload = {
        "schema_version": "dse.codesign.complete_dse.workload_architecture_prior_report.v1",
        "status": "passed",
        "release_id": RELEASE_ID,
        "source_workload_suite": "qe_mainflow_release_v1_reference_facts",
        "seed_rows": seed_rows,
        "seed_row_count": len(seed_rows),
        "workload_facts_affect_identity": False,
        "workload_facts_affect_post_freeze_pruning": False,
        "allowed_use": "pre_freeze_seed_and_pruning_rationale_only",
        "claim_boundary": "architecture priors are not Top-K selection or completion evidence",
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def build_schedule_legality_report() -> Dict[str, Any]:
    """Classify algorithm/mapping/compile/runtime schedule legality per seed."""
    indices = _space_indices()
    rows: list[Dict[str, Any]] = []
    for seed in default_release_seed_rows():
        taxonomy_id = seed["taxonomy_id"]
        identity_layers = _identity_from_seed(seed)
        legal, reasons = classify_candidate_legality(identity_layers)
        axis_checks = {
            "algorithm": taxonomy_id
            in indices["algorithm"][seed["algorithm_id"]][
                "compatible_taxonomy_ids"
            ],
            "mapping": taxonomy_id
            in indices["mapping"][seed["mapping_id"]]["compatible_taxonomy_ids"],
            "compile_time_schedule": taxonomy_id
            in indices["compile"][seed["compile_schedule_id"]][
                "compatible_taxonomy_ids"
            ],
            "runtime_scheduling": taxonomy_id
            in indices["runtime"][seed["runtime_schedule_id"]][
                "compatible_taxonomy_ids"
            ],
        }
        rows.append(
            {
                "taxonomy_id": taxonomy_id,
                "algorithm_id": seed["algorithm_id"],
                "mapping_id": seed["mapping_id"],
                "compile_schedule_id": seed["compile_schedule_id"],
                "runtime_schedule_id": seed["runtime_schedule_id"],
                "axis_checks": axis_checks,
                "legal": legal,
                "reasons": reasons,
                "candidate_id": complete_dse_candidate_id(identity_layers)
                if legal
                else None,
                "claim_boundary": "schedule legality only; not performance evidence",
            }
        )
    payload = {
        "schema_version": "dse.codesign.complete_dse.schedule_legality_report.v1",
        "status": "passed"
        if rows and all(row["legal"] for row in rows)
        else "failed",
        "release_id": RELEASE_ID,
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "all_algorithm_bindings_legal": all(
                row["axis_checks"]["algorithm"] for row in rows
            ),
            "all_mapping_bindings_legal": all(
                row["axis_checks"]["mapping"] for row in rows
            ),
            "all_compile_schedule_bindings_legal": all(
                row["axis_checks"]["compile_time_schedule"] for row in rows
            ),
            "all_runtime_schedule_bindings_legal": all(
                row["axis_checks"]["runtime_scheduling"] for row in rows
            ),
        },
        "claim_boundary": "axis legality report only; downstream L4 closure is separate",
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def _space_indices() -> Dict[str, Dict[str, Mapping[str, Any]]]:
    taxonomy = build_architecture_taxonomy_manifest()
    algorithms = build_algorithm_family_manifest()
    mappings = build_mapping_layout_space()
    compile_space = build_compile_schedule_space()
    runtime_space = build_runtime_schedule_space()
    target_space = build_target_platform_space()
    return {
        "taxonomy": _indexed_by_id(taxonomy["entries"]),
        "algorithm": _indexed_by_id(algorithms["families"]),
        "mapping": _indexed_by_id(mappings["mappings"]),
        "compile": _indexed_by_id(compile_space["compile_time_schedules"]),
        "runtime": _indexed_by_id(runtime_space["runtime_schedules"]),
        "target": _indexed_by_id(target_space["target_platforms"]),
    }


def _architecture_identity(taxonomy_id: str) -> Dict[str, Any]:
    taxonomy = _space_indices()["taxonomy"][taxonomy_id]
    return {
        "taxonomy_id": taxonomy_id,
        "kind": taxonomy["kind"],
        "compute_organization": taxonomy["compute_organization"],
        "release_v1_status": taxonomy["release_v1_status"],
    }


def _compatible_space_ids(index_name: str, taxonomy_id: str) -> list[str]:
    indices = _space_indices()[index_name]
    return sorted(
        item_id
        for item_id, row in indices.items()
        if taxonomy_id in row.get("compatible_taxonomy_ids", [])
    )


def _deployment_boundary_identity(
    seed: Mapping[str, str],
) -> Dict[str, Any]:
    algorithm_id = str(seed["algorithm_id"])
    taxonomy_id = str(seed["taxonomy_id"])
    accelerated_by_algorithm = {
        "streaming_fft_rho_pipeline": [
            "fft_grid_stream",
            "density_accumulation",
        ],
        "blocked_dense_subspace": [
            "hpsi_spsi_dense_block",
            "subspace_block_linear_algebra",
        ],
        "vector_residual_mixing": [
            "residual_vector_update",
            "mixing_reduction",
        ],
        "qe_task_graph_overlap": [
            "task_graph_kernel_dispatch",
            "heterogeneous_kernel_overlap",
        ],
    }
    accelerated = accelerated_by_algorithm.get(
        algorithm_id, [algorithm_id]
    )
    cpu_retained = [
        "workflow_io",
        "scf_control",
        "convergence_check",
        "global_mixing_control",
    ]
    if algorithm_id != "blocked_dense_subspace":
        cpu_retained.append("diagonalization_control")
    profile_id = str(seed.get("parameter_profile_id") or PARAMETER_PROFILE_ORDER[0])
    return {
        "deployment_boundary_id": f"hybrid_offload::{algorithm_id}",
        "host_device_partition_id": f"host_control_device_{taxonomy_id}",
        "parameter_profile_id": profile_id,
        "accelerated_kernels": accelerated,
        "cpu_retained_stages": cpu_retained,
        "descriptor_granularity": (
            "task_graph_window_descriptor"
            if algorithm_id == "qe_task_graph_overlap"
            else "per_kernel_batch_descriptor"
        ),
        "fallback_policy": "host_per_kernel_fallback",
    }


def _target_platform_identity(seed: Mapping[str, str]) -> Dict[str, Any]:
    indices = _space_indices()
    profile_id = str(seed.get("parameter_profile_id") or PARAMETER_PROFILE_ORDER[0])
    target_platform_id = str(
        seed.get("target_platform_id") or REQUIRED_TARGET_PLATFORM_IDS[0]
    )
    target = indices["target"][target_platform_id]
    return {
        "target_platform_id": target_platform_id,
        "platform_kind": target["platform_kind"],
        "parameter_profile_id": profile_id,
        "toolchain_flow": target["toolchain_flow"],
        "required_claim_gate": target["required_claim_gate"],
        "implementation_claim_scope": "platform_identity_only_not_evidence",
    }


def _identity_from_seed(seed: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    indices = _space_indices()
    taxonomy_id = str(seed["taxonomy_id"])
    algorithm_id = str(seed["algorithm_id"])
    mapping_id = str(seed["mapping_id"])
    compile_id = str(seed["compile_schedule_id"])
    runtime_id = str(seed["runtime_schedule_id"])
    profile_id = str(seed.get("parameter_profile_id") or PARAMETER_PROFILE_ORDER[0])
    profile = PARAMETER_PROFILES.get(profile_id)
    if profile is None:
        raise KeyError(f"unknown parameter_profile_id: {profile_id}")
    return {
        "deployment_boundary_parameters": _deployment_boundary_identity(seed),
        "algorithm_parameters": {
            "algorithm_id": algorithm_id,
            "family": indices["algorithm"][algorithm_id]["family"],
            "variant": indices["algorithm"][algorithm_id]["variant"],
            "parameter_profile_id": profile_id,
            **dict(profile["algorithm"]),
        },
        "architecture_parameters": {
            **_architecture_identity(taxonomy_id),
            "parameter_profile_id": profile_id,
            **dict(profile["architecture"]),
        },
        "mapping_layout_parameters": {
            "mapping_id": mapping_id,
            "layout": indices["mapping"][mapping_id]["layout"],
            "memory_layout_id": indices["mapping"][mapping_id]["layout"],
            "memory_hierarchy_target": indices["mapping"][mapping_id][
                "memory_hierarchy_target"
            ],
            "parameter_profile_id": profile_id,
            **dict(profile["mapping"]),
        },
        "compile_time_schedule_parameters": {
            "compile_schedule_id": compile_id,
            "tiling": indices["compile"][compile_id]["tiling"],
            "loop_order": indices["compile"][compile_id]["loop_order"],
            "parameter_profile_id": profile_id,
            **dict(profile["compile"]),
        },
        "runtime_scheduling_parameters": {
            "runtime_schedule_id": runtime_id,
            "co_scheduling_policy_id": indices["runtime"][runtime_id][
                "queue_policy"
            ],
            "queue_policy": indices["runtime"][runtime_id]["queue_policy"],
            "engine_assignment": indices["runtime"][runtime_id][
                "engine_assignment"
            ],
            "parameter_profile_id": profile_id,
            **dict(profile["runtime"]),
        },
        "target_platform_parameters": _target_platform_identity(seed),
    }


def default_release_seed_rows() -> list[Dict[str, str]]:
    """Return generated legal pre-freeze rows for the release-v1 universe.

    Earlier foundation artifacts used one hand-picked row per taxonomy.  The
    current contract emits the bounded Cartesian product of compatible
    algorithm, layout, compile, runtime, and parameter-profile choices for every
    required base family/hybrid.  Legality pruning still happens before freeze,
    and downstream evidence must still cover every legal row before completion.
    """

    rows: list[Dict[str, str]] = []
    for taxonomy_id in REQUIRED_TAXONOMY_IDS:
        for algorithm_id in _compatible_space_ids("algorithm", taxonomy_id):
            for mapping_id in _compatible_space_ids("mapping", taxonomy_id):
                for compile_schedule_id in _compatible_space_ids("compile", taxonomy_id):
                    for runtime_schedule_id in _compatible_space_ids("runtime", taxonomy_id):
                        for profile_id in PARAMETER_PROFILE_ORDER:
                            rows.append(
                                {
                                    "taxonomy_id": taxonomy_id,
                                    "algorithm_id": algorithm_id,
                                    "mapping_id": mapping_id,
                                    "compile_schedule_id": compile_schedule_id,
                                    "runtime_schedule_id": runtime_schedule_id,
                                    "parameter_profile_id": profile_id,
                                }
                            )
    return rows


def default_release_candidate_seed_rows() -> list[Dict[str, str]]:
    """Return the finite release universe seed rows including target platforms."""

    rows: list[Dict[str, str]] = []
    for seed in default_release_seed_rows():
        for target_platform_id in REQUIRED_TARGET_PLATFORM_IDS:
            rows.append({**seed, "target_platform_id": target_platform_id})
    return rows


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
    target_platform_id = str(
        layers["target_platform_parameters"].get("target_platform_id", "")
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
        ("target", target_platform_id),
    ]:
        if item_id not in indices[index_name]:
            reasons.append(f"{index_name} id is not declared: {item_id}")

    if target_platform_id in indices["target"]:
        declared_target = indices["target"][target_platform_id]
        target_identity = layers["target_platform_parameters"]
        for field in (
            "platform_kind",
            "toolchain_flow",
            "required_claim_gate",
        ):
            if (
                field in target_identity
                and target_identity.get(field) != declared_target.get(field)
            ):
                reasons.append(
                    f"target platform field {field} does not match "
                    f"declared target platform {target_platform_id}"
                )

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


def _release_pruning_rationale_contract_hash(seed_rows_hash: str) -> str:
    return stable_json_hash(
        {
            "schema_version": "dse.codesign.complete_dse.release_pruning_rationale_contract.v1",
            "release_id": RELEASE_ID,
            "seed_rows_hash": seed_rows_hash,
            "legality_constraints_hash": build_legality_constraints_manifest()[
                "constraints_hash"
            ],
            "pruning_phase": "pre_freeze_only",
            "post_freeze_row_removal_allowed": False,
        }
    )


def _release_matrix_cardinality_contract(
    legal_candidates: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    deployment_boundary_ids: list[str] = []
    target_platform_ids: list[str] = []
    target_platform_kinds: list[str] = []
    for candidate in legal_candidates:
        layers = _candidate_identity_layers(candidate)
        deployment = layers.get("deployment_boundary_parameters", {})
        target = layers.get("target_platform_parameters", {})
        if isinstance(deployment, Mapping):
            boundary_id = str(deployment.get("deployment_boundary_id") or "")
            if boundary_id and boundary_id not in deployment_boundary_ids:
                deployment_boundary_ids.append(boundary_id)
        if isinstance(target, Mapping):
            target_id = str(target.get("target_platform_id") or "")
            if target_id and target_id not in target_platform_ids:
                target_platform_ids.append(target_id)
            platform_kind = str(target.get("platform_kind") or "")
            if platform_kind and platform_kind not in target_platform_kinds:
                target_platform_kinds.append(platform_kind)
    missing_targets = [
        target_id
        for target_id in REQUIRED_TARGET_PLATFORM_IDS
        if target_id not in target_platform_ids
    ]
    missing_target_kinds = [
        platform_kind
        for platform_kind in REQUIRED_TARGET_PLATFORM_KINDS
        if platform_kind not in target_platform_kinds
    ]
    payload = {
        "schema_version": "dse.codesign.complete_dse.release_matrix_cardinality_contract.v1",
        "release_id": RELEASE_ID,
        "candidate_axis_count": len(legal_candidates),
        "candidate_axis_source": "release_subset_manifest.legal_candidate_ids",
        "workflow_axis_source": "external frozen workload suite",
        "deployment_boundary_axis_source": (
            "candidate.identity.identity_layers.deployment_boundary_parameters.deployment_boundary_id"
        ),
        "target_platform_axis_source": (
            "candidate.identity.identity_layers.target_platform_parameters.target_platform_id"
        ),
        "deployment_boundary_ids": deployment_boundary_ids,
        "target_platform_ids": target_platform_ids,
        "target_platform_kinds": target_platform_kinds,
        "required_target_platform_ids": list(REQUIRED_TARGET_PLATFORM_IDS),
        "required_target_platform_kinds": list(REQUIRED_TARGET_PLATFORM_KINDS),
        "target_axis_complete": not missing_targets,
        "missing_target_platform_ids": missing_targets,
        "target_kind_axis_complete": not missing_target_kinds,
        "missing_target_platform_kinds": missing_target_kinds,
        "row_status_vocabulary": list(RELEASE_MATRIX_ROW_STATUSES),
        "missing_matrix_rows_fail_closed": True,
        "claim_boundary": (
            "Step2 matrix contract defines required axes/status vocabulary; "
            "actual evidence rows close downstream"
        ),
    }
    payload["contract_hash"] = _stable_hash_without(payload, "contract_hash")
    return payload


def _normalised_workflow_cases(
    workflow_cases: Sequence[Mapping[str, Any]] | None = None,
) -> list[Dict[str, Any]]:
    cases = list(workflow_cases or DEFAULT_RELEASE_WORKFLOW_CASES)
    normalised: list[Dict[str, Any]] = []
    for index, case in enumerate(cases):
        case_id = str(
            case.get("workflow_case_id")
            or case.get("case_id")
            or f"workflow_case_{index:02d}"
        )
        normalised.append(
            {
                "workflow_case_id": case_id,
                "workflow_family": str(
                    case.get("workflow_family")
                    or case.get("family")
                    or "external_frozen_workflow_suite"
                ),
                "workflow_role": str(
                    case.get("workflow_role")
                    or case.get("stage_type")
                    or f"mainflow_case_{index:02d}"
                ),
                "candidate_identity_participation": False,
            }
        )
    return normalised


def _normalised_evidence_gates(
    evidence_gates: Sequence[Mapping[str, Any]] | None = None,
) -> list[Dict[str, Any]]:
    gates = list(evidence_gates or DEFAULT_RELEASE_EVIDENCE_GATES)
    normalised: list[Dict[str, Any]] = []
    for index, gate in enumerate(gates):
        gate_id = str(
            gate.get("evidence_gate_id")
            or gate.get("gate_id")
            or f"evidence_gate_{index:02d}"
        )
        kinds = [
            str(item)
            for item in (
                gate.get("applies_to_target_platform_kinds")
                or gate.get("target_platform_kinds")
                or REQUIRED_TARGET_PLATFORM_KINDS
            )
        ]
        normalised.append(
            {
                "evidence_gate_id": gate_id,
                "gate_family": str(
                    gate.get("gate_family") or gate.get("family") or "evidence"
                ),
                "applies_to_target_platform_kinds": kinds,
                "status_vocabulary": list(RELEASE_MATRIX_ROW_STATUSES),
                "candidate_identity_participation": False,
            }
        )
    return normalised


def _matrix_row_key_payload(
    *,
    candidate_id: str,
    workflow_case_id: str,
    deployment_boundary_id: str,
    target_platform_id: str,
    evidence_gate_id: str,
) -> Dict[str, str]:
    return {
        "candidate_id": candidate_id,
        "workflow_case_id": workflow_case_id,
        "deployment_boundary_id": deployment_boundary_id,
        "target_platform_id": target_platform_id,
        "evidence_gate_id": evidence_gate_id,
    }


def _matrix_row_id(row_key: Mapping[str, str]) -> str:
    return "cdse_mrow_" + stable_json_hash(row_key)[:20]


def _matrix_candidate_identity_provenance(
    candidate: Mapping[str, Any],
) -> Dict[str, Any]:
    identity_layers = _candidate_identity_layers(candidate)
    identity_payload = {
        layer: dict(identity_layers.get(layer, {}))
        for layer in IDENTITY_LAYER_KEYS
        if isinstance(identity_layers.get(layer, {}), Mapping)
    }
    return {
        "candidate_id": candidate.get("candidate_id"),
        "identity_hash": candidate.get("identity_hash"),
        "record_hash": candidate.get("record_hash"),
        "identity_layers_hash": stable_json_hash(identity_payload),
        "identity_layers": identity_payload,
        "claim_boundary": (
            "row-local identity provenance preserves design axes; workflow "
            "case and evidence status remain outside stable candidate identity"
        ),
    }


def _matrix_candidate_axis(
    release_subset: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    return [
        candidate
        for candidate in release_subset.get("candidates", []) or []
        if isinstance(candidate, Mapping) and candidate.get("legal", True) is True
    ]


def build_candidate_workflow_deployment_target_matrix(
    release_subset: Mapping[str, Any] | None = None,
    *,
    workflow_cases: Sequence[Mapping[str, Any]] | None = None,
    evidence_gates: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Build the Step2 finite release-universe matrix skeleton.

    Rows deliberately default to ``blocked_missing_input``.  Step2 owns the
    finite candidate/workflow/deployment/target/gate universe and provenance;
    Step3/Step4 may later replace row status with trusted evidence, but missing
    evidence remains fail-closed.
    """

    subset = dict(release_subset or {})
    candidates = _matrix_candidate_axis(subset)
    workflow_axis = _normalised_workflow_cases(
        workflow_cases
        if workflow_cases is not None
        else subset.get("release_workflow_cases")
        if isinstance(subset.get("release_workflow_cases"), list)
        else None
    )
    evidence_axis = _normalised_evidence_gates(
        evidence_gates
        if evidence_gates is not None
        else subset.get("release_evidence_gates")
        if isinstance(subset.get("release_evidence_gates"), list)
        else None
    )
    release_subset_hash = str(subset.get("release_subset_hash") or "")
    rows: list[Dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        layers = _candidate_identity_layers(candidate)
        deployment = layers.get("deployment_boundary_parameters", {})
        runtime = layers.get("runtime_scheduling_parameters", {})
        target = layers.get("target_platform_parameters", {})
        if (
            not isinstance(deployment, Mapping)
            or not isinstance(runtime, Mapping)
            or not isinstance(target, Mapping)
        ):
            continue
        deployment_boundary_id = str(
            deployment.get("deployment_boundary_id") or ""
        )
        runtime_schedule_id = str(runtime.get("runtime_schedule_id") or "")
        target_platform_id = str(target.get("target_platform_id") or "")
        target_kind = str(target.get("platform_kind") or "")
        applicable_gates = [
            gate
            for gate in evidence_axis
            if target_kind in gate["applies_to_target_platform_kinds"]
        ]
        for workflow_case in workflow_axis:
            workflow_case_id = workflow_case["workflow_case_id"]
            for gate in applicable_gates:
                row_key = _matrix_row_key_payload(
                    candidate_id=candidate_id,
                    workflow_case_id=workflow_case_id,
                    deployment_boundary_id=deployment_boundary_id,
                    target_platform_id=target_platform_id,
                    evidence_gate_id=gate["evidence_gate_id"],
                )
                row = {
                    "schema_version": "dse.codesign.complete_dse.release_matrix_row.v1",
                    "row_id": _matrix_row_id(row_key),
                    **row_key,
                    "target_platform_kind": target_kind,
                    "status": "blocked_missing_input",
                    "status_reason": (
                        "Step2 enumerates required evidence rows; Step3/Step4 "
                        "must attach trusted evidence before claims can pass"
                    ),
                    "workflow_case": dict(workflow_case),
                    "deployment_boundary": {
                        "deployment_boundary_id": deployment_boundary_id,
                        "host_device_partition_id": deployment.get(
                            "host_device_partition_id"
                        ),
                        "descriptor_granularity": deployment.get(
                            "descriptor_granularity"
                        ),
                    },
                    "runtime_scheduling": {
                        "runtime_schedule_id": runtime_schedule_id,
                        "co_scheduling_policy_id": runtime.get(
                            "co_scheduling_policy_id"
                        ),
                        "queue_policy": runtime.get("queue_policy"),
                        "engine_assignment": runtime.get("engine_assignment"),
                        "queue_depth": runtime.get("queue_depth"),
                        "overlap_window": runtime.get("overlap_window"),
                    },
                    "target_platform": {
                        "target_platform_id": target_platform_id,
                        "platform_kind": target_kind,
                        "toolchain_flow": target.get("toolchain_flow"),
                        "required_claim_gate": target.get(
                            "required_claim_gate"
                        ),
                    },
                    "evidence_gate": dict(gate),
                    "candidate_identity_provenance": (
                        _matrix_candidate_identity_provenance(candidate)
                    ),
                    "row_provenance": {
                        "candidate_id": candidate_id,
                        "candidate_identity_hash": candidate.get(
                            "identity_hash"
                        ),
                        "candidate_record_hash": candidate.get("record_hash"),
                        "release_subset_hash": release_subset_hash,
                        "row_key_hash": stable_json_hash(row_key),
                        "candidate_identity_affects_row": True,
                        "workflow_case_affects_row": True,
                        "deployment_boundary_affects_row": True,
                        "runtime_schedule_affects_row": True,
                        "target_platform_affects_row": True,
                        "evidence_gate_affects_row": True,
                    },
                    "deliverable_complete_eligible": False,
                    "claim_boundary": (
                        "Step2 matrix row only; blocked_missing_input rows are "
                        "not trusted evidence and cannot satisfy completion"
                    ),
                }
                row["row_hash"] = _stable_hash_without(row, "row_hash")
                rows.append(row)

    target_platform_ids = sorted(
        {
            str(row["target_platform_id"])
            for row in rows
            if row.get("target_platform_id")
        }
    )
    target_platform_kinds = sorted(
        {
            str(row["target_platform_kind"])
            for row in rows
            if row.get("target_platform_kind")
        }
    )
    payload = {
        "schema_version": "dse.codesign.complete_dse.candidate_workflow_deployment_target_matrix.v1",
        "release_id": RELEASE_ID,
        "release_subset_hash": release_subset_hash,
        "candidate_ids": [
            str(candidate.get("candidate_id") or "") for candidate in candidates
        ],
        "candidate_count": len(candidates),
        "workflow_cases": workflow_axis,
        "workflow_case_ids": [
            case["workflow_case_id"] for case in workflow_axis
        ],
        "workflow_case_count": len(workflow_axis),
        "deployment_boundary_ids": sorted(
            {
                str(
                    _candidate_identity_layers(candidate)
                    .get("deployment_boundary_parameters", {})
                    .get("deployment_boundary_id")
                    or ""
                )
                for candidate in candidates
            }
            - {""}
        ),
        "target_platform_ids": target_platform_ids,
        "target_platform_kinds": target_platform_kinds,
        "required_target_platform_ids": list(REQUIRED_TARGET_PLATFORM_IDS),
        "required_target_platform_kinds": list(REQUIRED_TARGET_PLATFORM_KINDS),
        "evidence_gates": evidence_axis,
        "evidence_gate_ids": [
            gate["evidence_gate_id"] for gate in evidence_axis
        ],
        "evidence_gate_count": len(evidence_axis),
        "allowed_row_statuses": list(RELEASE_MATRIX_ROW_STATUSES),
        "default_row_status": "blocked_missing_input",
        "expected_row_count": len(rows),
        "row_count": len(rows),
        "rows": rows,
        "deliverable_complete": False,
        "claim_boundary": (
            "Step2 release-universe matrix skeleton only; row status must stay "
            "inside the fail-closed vocabulary and cannot claim completion"
        ),
    }
    payload["matrix_hash"] = _stable_hash_without(payload, "matrix_hash")
    return payload


def _matrix_row_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("candidate_id") or ""),
        str(row.get("workflow_case_id") or ""),
        str(row.get("deployment_boundary_id") or ""),
        str(row.get("target_platform_id") or ""),
        str(row.get("evidence_gate_id") or ""),
    )


def validate_candidate_workflow_deployment_target_matrix(
    release_subset: Mapping[str, Any],
    matrix: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Fail-closed validation for the Step2 release-universe matrix."""

    actual = dict(
        matrix
        if isinstance(matrix, Mapping)
        else release_subset.get("candidate_workflow_deployment_target_matrix", {})
        if isinstance(
            release_subset.get("candidate_workflow_deployment_target_matrix", {}),
            Mapping,
        )
        else {}
    )
    expected = build_candidate_workflow_deployment_target_matrix(
        release_subset
    )
    blockers: list[Dict[str, Any]] = []
    if not actual:
        blockers.append({"id": "missing_candidate_workflow_deployment_target_matrix"})
        actual = {"rows": []}

    if actual.get("allowed_row_statuses") != list(RELEASE_MATRIX_ROW_STATUSES):
        blockers.append(
            {
                "id": "matrix_status_vocabulary_mismatch",
                "expected": list(RELEASE_MATRIX_ROW_STATUSES),
                "actual": actual.get("allowed_row_statuses"),
            }
        )

    raw_rows = actual.get("rows", [])
    rows = (
        [row for row in raw_rows if isinstance(row, Mapping)]
        if isinstance(raw_rows, list)
        else []
    )
    if not isinstance(raw_rows, list):
        blockers.append({"id": "matrix_rows_not_list"})
    elif len(rows) != len(raw_rows):
        blockers.append({"id": "matrix_rows_contain_non_object"})

    expected_by_key = {
        _matrix_row_key(row): row for row in expected["rows"]
    }
    actual_by_key: Dict[tuple[str, str, str, str, str], Mapping[str, Any]] = {}
    duplicate_keys: list[tuple[str, str, str, str, str]] = []
    candidate_by_id = {
        str(candidate.get("candidate_id") or ""): candidate
        for candidate in _matrix_candidate_axis(release_subset)
    }
    evidence_gate_by_id = {
        gate["evidence_gate_id"]: gate for gate in expected["evidence_gates"]
    }

    for index, row in enumerate(rows):
        key = _matrix_row_key(row)
        if key in actual_by_key:
            duplicate_keys.append(key)
        actual_by_key[key] = row
        status = str(row.get("status") or "")
        if status not in RELEASE_MATRIX_ROW_STATUSES:
            blockers.append(
                {
                    "id": "invalid_matrix_row_status",
                    "row_index": index,
                    "row_id": row.get("row_id"),
                    "status": status,
                }
            )
        expected_row = expected_by_key.get(key)
        if expected_row is None:
            blockers.append(
                {
                    "id": "unexpected_matrix_rows",
                    "row_index": index,
                    "row_key": list(key),
                }
            )

        row_key_payload = _matrix_row_key_payload(
            candidate_id=key[0],
            workflow_case_id=key[1],
            deployment_boundary_id=key[2],
            target_platform_id=key[3],
            evidence_gate_id=key[4],
        )
        if row.get("row_id") != _matrix_row_id(row_key_payload):
            blockers.append(
                {
                    "id": "matrix_row_id_mismatch",
                    "row_index": index,
                    "expected": _matrix_row_id(row_key_payload),
                    "actual": row.get("row_id"),
                }
            )
        if row.get("row_hash") != _stable_hash_without(row, "row_hash"):
            blockers.append(
                {
                    "id": "matrix_row_hash_mismatch",
                    "row_index": index,
                    "row_id": row.get("row_id"),
                }
            )

        candidate = candidate_by_id.get(key[0])
        if candidate is None:
            blockers.append(
                {
                    "id": "matrix_row_candidate_not_in_release_subset",
                    "row_index": index,
                    "candidate_id": key[0],
                }
            )
            continue
        layers = _candidate_identity_layers(candidate)
        deployment = layers.get("deployment_boundary_parameters", {})
        target = layers.get("target_platform_parameters", {})
        expected_axis = {
            "deployment_boundary_id": (
                deployment.get("deployment_boundary_id")
                if isinstance(deployment, Mapping)
                else None
            ),
            "target_platform_id": (
                target.get("target_platform_id")
                if isinstance(target, Mapping)
                else None
            ),
            "target_platform_kind": (
                target.get("platform_kind") if isinstance(target, Mapping) else None
            ),
        }
        if (
            key[3] != str(expected_axis["target_platform_id"] or "")
            or str(row.get("target_platform_kind") or "")
            != str(expected_axis["target_platform_kind"] or "")
        ):
            blockers.append(
                {
                    "id": "matrix_row_candidate_target_identity_mismatch",
                    "row_index": index,
                    "candidate_id": key[0],
                    "expected_target_platform_id": expected_axis[
                        "target_platform_id"
                    ],
                    "actual_target_platform_id": key[3],
                    "expected_target_platform_kind": expected_axis[
                        "target_platform_kind"
                    ],
                    "actual_target_platform_kind": row.get(
                        "target_platform_kind"
                    ),
                }
            )
        if (
            key[2] != str(expected_axis["deployment_boundary_id"] or "")
            or key[3] != str(expected_axis["target_platform_id"] or "")
            or str(row.get("target_platform_kind") or "")
            != str(expected_axis["target_platform_kind"] or "")
        ):
            blockers.append(
                {
                    "id": "matrix_row_axis_mismatch",
                    "row_index": index,
                    "candidate_id": key[0],
                    "expected": expected_axis,
                    "actual": {
                        "deployment_boundary_id": key[2],
                        "target_platform_id": key[3],
                        "target_platform_kind": row.get(
                            "target_platform_kind"
                        ),
                    },
                }
            )

        gate = evidence_gate_by_id.get(key[4])
        if gate is None:
            blockers.append(
                {
                    "id": "matrix_row_unknown_evidence_gate",
                    "row_index": index,
                    "evidence_gate_id": key[4],
                }
            )
        elif str(row.get("target_platform_kind") or "") not in gate[
            "applies_to_target_platform_kinds"
        ]:
            blockers.append(
                {
                    "id": "matrix_row_gate_target_mismatch",
                    "row_index": index,
                    "evidence_gate_id": key[4],
                    "target_platform_kind": row.get("target_platform_kind"),
                }
            )

        provenance = row.get("row_provenance", {})
        provenance = provenance if isinstance(provenance, Mapping) else {}
        if provenance.get("candidate_identity_hash") != candidate.get(
            "identity_hash"
        ):
            blockers.append(
                {
                    "id": "matrix_row_candidate_identity_hash_mismatch",
                    "row_index": index,
                    "candidate_id": key[0],
                }
            )
        expected_identity_provenance = _matrix_candidate_identity_provenance(
            candidate
        )
        if row.get("candidate_identity_provenance") != expected_identity_provenance:
            blockers.append(
                {
                    "id": "matrix_row_candidate_identity_provenance_mismatch",
                    "row_index": index,
                    "candidate_id": key[0],
                }
            )

    missing_keys = [
        key for key in expected_by_key if key not in actual_by_key
    ]
    if missing_keys:
        blockers.append(
            {
                "id": "missing_expected_matrix_rows",
                "count": len(missing_keys),
                "row_keys": [list(key) for key in missing_keys[:20]],
            }
        )
    if duplicate_keys:
        blockers.append(
            {
                "id": "duplicate_matrix_rows",
                "count": len(duplicate_keys),
                "row_keys": [list(key) for key in duplicate_keys[:20]],
            }
        )
    if int(actual.get("row_count") or -1) != len(rows) or len(rows) != len(
        expected_by_key
    ):
        blockers.append(
            {
                "id": "matrix_row_count_mismatch",
                "declared": actual.get("row_count"),
                "actual": len(rows),
                "expected": len(expected_by_key),
            }
        )
    if int(actual.get("expected_row_count") or -1) != len(expected_by_key):
        blockers.append(
            {
                "id": "matrix_expected_row_count_mismatch",
                "declared": actual.get("expected_row_count"),
                "expected": len(expected_by_key),
            }
        )
    if actual.get("matrix_hash") != _stable_hash_without(
        actual, "matrix_hash"
    ):
        blockers.append(
            {
                "id": "matrix_hash_mismatch",
                "expected": _stable_hash_without(actual, "matrix_hash"),
                "actual": actual.get("matrix_hash"),
            }
        )

    payload = {
        "schema_version": "dse.codesign.complete_dse.candidate_workflow_deployment_target_matrix_validation.v1",
        "valid": not blockers,
        "release_id": RELEASE_ID,
        "release_subset_hash": release_subset.get("release_subset_hash"),
        "matrix_hash": actual.get("matrix_hash"),
        "expected_matrix_hash": expected.get("matrix_hash"),
        "expected_row_count": len(expected_by_key),
        "actual_row_count": len(rows),
        "blockers": blockers,
        "allowed_row_statuses": list(RELEASE_MATRIX_ROW_STATUSES),
        "deliverable_complete": False,
        "claim_boundary": (
            "Matrix validation proves Step2 universe coverage only; it cannot "
            "upgrade blocked rows into trusted evidence."
        ),
    }
    payload["validation_hash"] = _stable_hash_without(
        payload, "validation_hash"
    )
    return payload


def build_release_subset_manifest(
    seed_rows: Sequence[Mapping[str, str]] | None = None,
) -> Dict[str, Any]:
    rows = list(seed_rows or default_release_candidate_seed_rows())
    seed_rows_hash = stable_json_hash(rows)
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
                generation_source=PARAMETERIZED_RELEASE_GENERATOR_SOURCE,
            )
        )
    legal_candidates = [
        candidate for candidate in candidates if candidate["legal"]
    ]
    matrix_contract = _release_matrix_cardinality_contract(legal_candidates)
    pruning_rationale_hash = _release_pruning_rationale_contract_hash(
        seed_rows_hash
    )
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
            taxonomy_id
            for taxonomy_id in REQUIRED_TAXONOMY_IDS
            if taxonomy_id
            in {
                candidate["identity"]["identity_layers"][
                    "architecture_parameters"
                ]["taxonomy_id"]
                for candidate in candidates
            }
        ],
        "release_workflow_cases": _normalised_workflow_cases(),
        "release_evidence_gates": _normalised_evidence_gates(),
        "candidate_workflow_deployment_target_matrix_contract": matrix_contract,
        "stable_id_status": "emitted_after_all_identity_layers_present",
        "generation_provenance": {
            "source": PARAMETERIZED_RELEASE_GENERATOR_SOURCE,
            "seed_rows_hash": seed_rows_hash,
            "generation_mode": "bounded_compatible_cartesian_product",
            "parameter_profile_ids": list(PARAMETER_PROFILE_ORDER),
            "taxonomy_order": list(REQUIRED_TAXONOMY_IDS),
            "pruning_rationale_hash": pruning_rationale_hash,
            "legality_constraints_hash": build_legality_constraints_manifest()[
                "constraints_hash"
            ],
            "candidate_workflow_deployment_target_matrix_contract_hash": matrix_contract[
                "contract_hash"
            ],
            "candidate_order": [
                candidate["candidate_id"] for candidate in candidates
            ],
            "workload_facts_used_only_before_freeze": True,
            "post_freeze_row_removal_allowed": False,
        },
        "deterministic_replay": _deterministic_replay_metadata(
            artifact_name="release_subset_manifest.json",
            builder="build_release_subset_manifest",
            inputs={
                "seed_rows_hash": seed_rows_hash,
                "pruning_rationale_hash": pruning_rationale_hash,
                "candidate_workflow_deployment_target_matrix_contract_hash": matrix_contract[
                    "contract_hash"
                ],
                "identity_layers": list(IDENTITY_LAYER_KEYS),
                "non_identity_fields": list(NON_IDENTITY_FIELDS),
            },
        ),
        "claim_boundary": "release subset identity manifest only; closure evidence is tracked downstream",
    }
    payload["release_subset_hash"] = _release_subset_hash(payload)
    matrix = build_candidate_workflow_deployment_target_matrix(payload)
    matrix_validation = validate_candidate_workflow_deployment_target_matrix(
        payload, matrix
    )
    payload["candidate_workflow_deployment_target_matrix"] = matrix
    payload["candidate_workflow_deployment_target_matrix_rows_hash"] = matrix[
        "matrix_hash"
    ]
    payload["generation_provenance"][
        "candidate_workflow_deployment_target_matrix_rows_hash"
    ] = matrix["matrix_hash"]
    payload["generation_provenance"][
        "candidate_workflow_deployment_target_matrix_validation_hash"
    ] = matrix_validation["validation_hash"]
    for index, candidate in enumerate(payload["candidates"]):
        if isinstance(candidate, Mapping):
            candidate["recommendation_input_provenance"] = (
                _recommendation_input_provenance_for_candidate(
                    candidate,
                    release_subset=payload,
                    matrix=matrix,
                    matrix_validation=matrix_validation,
                    candidate_index=index,
                )
            )
    return payload


def _recommendation_input_provenance_for_candidate(
    candidate: Mapping[str, Any],
    *,
    release_subset: Mapping[str, Any],
    matrix: Mapping[str, Any],
    matrix_validation: Mapping[str, Any],
    candidate_index: int,
) -> Dict[str, Any]:
    identity_layers = _candidate_identity_layers(candidate)
    deployment = identity_layers.get("deployment_boundary_parameters", {})
    runtime = identity_layers.get("runtime_scheduling_parameters", {})
    target = identity_layers.get("target_platform_parameters", {})
    generation_provenance = release_subset.get("generation_provenance", {})
    generation_provenance = generation_provenance if isinstance(generation_provenance, Mapping) else {}
    candidate_id = str(candidate.get("candidate_id") or "")
    matrix_rows = [
        row
        for row in matrix.get("rows", []) or []
        if isinstance(row, Mapping) and str(row.get("candidate_id") or "") == candidate_id
    ]
    matrix_row_statuses = [
        str(row.get("status") or "") for row in matrix_rows if str(row.get("status") or "")
    ]
    blocked_missing_input_count = sum(
        1 for status in matrix_row_statuses if status == "blocked_missing_input"
    )
    trusted_row_count = sum(
        1 for status in matrix_row_statuses if status in {"trusted_pass", "trusted_fail"}
    )
    missing_rows_fail_closed = bool(matrix_rows) and blocked_missing_input_count == len(matrix_rows)
    return {
        "schema_version": "dse.codesign.complete_dse.recommendation_input_provenance.v1",
        "release_id": release_subset.get("release_id"),
        "release_subset_hash": release_subset.get("release_subset_hash"),
        "candidate_id": candidate.get("candidate_id"),
        "candidate_record_hash": candidate.get("record_hash"),
        "candidate_identity_hash": candidate.get("identity_hash"),
        "candidate_order_index": candidate_index,
        "derived_from_reproducible_release_universe": True,
        "fixed_or_manual_top_k_seed": False,
        "search_policy_provenance": {
            "source": generation_provenance.get("source"),
            "generation_source": generation_provenance.get("source"),
            "generation_mode": generation_provenance.get("generation_mode"),
            "seed_rows_hash": generation_provenance.get("seed_rows_hash"),
            "pruning_rationale_hash": generation_provenance.get("pruning_rationale_hash"),
            "legality_constraints_hash": generation_provenance.get("legality_constraints_hash"),
            "matrix_contract_hash": generation_provenance.get(
                "candidate_workflow_deployment_target_matrix_contract_hash"
            ),
            "matrix_rows_hash": generation_provenance.get(
                "candidate_workflow_deployment_target_matrix_rows_hash"
            ),
            "matrix_validation_hash": generation_provenance.get(
                "candidate_workflow_deployment_target_matrix_validation_hash"
            ),
            "candidate_order": list(generation_provenance.get("candidate_order", []) or []),
        },
        "legality_provenance": {
            "legal": candidate.get("legal") is True,
            "illegal_reasons": list(candidate.get("illegal_reasons", []) or []),
            "pruning_phase": "pre_freeze_only",
            "post_freeze_row_removal_allowed": generation_provenance.get(
                "post_freeze_row_removal_allowed"
            ),
        },
        "deployment_boundary_provenance": {
            "deployment_boundary_id": deployment.get("deployment_boundary_id")
            if isinstance(deployment, Mapping)
            else None,
            "host_device_partition_id": deployment.get("host_device_partition_id")
            if isinstance(deployment, Mapping)
            else None,
            "accelerated_kernels": list(deployment.get("accelerated_kernels", []) or [])
            if isinstance(deployment, Mapping)
            else [],
            "cpu_retained_stages": list(deployment.get("cpu_retained_stages", []) or [])
            if isinstance(deployment, Mapping)
            else [],
            "descriptor_granularity": deployment.get("descriptor_granularity")
            if isinstance(deployment, Mapping)
            else None,
            "fallback_policy": deployment.get("fallback_policy")
            if isinstance(deployment, Mapping)
            else None,
        },
        "runtime_scheduling_provenance": {
            "runtime_schedule_id": runtime.get("runtime_schedule_id")
            if isinstance(runtime, Mapping)
            else None,
            "co_scheduling_policy_id": runtime.get("co_scheduling_policy_id")
            if isinstance(runtime, Mapping)
            else None,
            "queue_policy": runtime.get("queue_policy")
            if isinstance(runtime, Mapping)
            else None,
            "engine_assignment": runtime.get("engine_assignment")
            if isinstance(runtime, Mapping)
            else None,
            "queue_depth": runtime.get("queue_depth")
            if isinstance(runtime, Mapping)
            else None,
            "overlap_window": runtime.get("overlap_window")
            if isinstance(runtime, Mapping)
            else None,
        },
        "target_platform_provenance": {
            "target_platform_id": target.get("target_platform_id")
            if isinstance(target, Mapping)
            else None,
            "platform_kind": target.get("platform_kind")
            if isinstance(target, Mapping)
            else None,
            "toolchain_flow": target.get("toolchain_flow")
            if isinstance(target, Mapping)
            else None,
            "required_claim_gate": target.get("required_claim_gate")
            if isinstance(target, Mapping)
            else None,
        },
        "evidence_matrix_provenance": {
            "matrix_hash": matrix.get("matrix_hash"),
            "matrix_validation_hash": matrix_validation.get("validation_hash"),
            "matrix_row_count": len(matrix_rows),
            "matrix_row_statuses": matrix_row_statuses,
            "observed_row_statuses": list(dict.fromkeys(matrix_row_statuses)),
            "blocked_missing_input_row_count": blocked_missing_input_count,
            "trusted_row_count": trusted_row_count,
            "missing_evidence_rows_fail_closed": missing_rows_fail_closed,
            "trusted_ppa_evidence_ready": (
                not missing_rows_fail_closed and trusted_row_count > 0
            ),
            "blockers": (
                [{"id": "candidate_evidence_rows_blocked_missing_input"}]
                if missing_rows_fail_closed
                else []
            ),
        },
        "artifact_provenance": _release_universe_artifact_provenance(
            release_subset=release_subset,
            matrix=matrix,
            matrix_validation=matrix_validation,
            candidate=candidate,
        ),
        "claim_boundary": (
            "Recommendation-input provenance binds a release candidate to the "
            "reproducible release universe and fail-closed evidence matrix; it "
            "does not upgrade the candidate into PPA or completion evidence."
        ),
    }


def _identity_layer_keys(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    identity = candidate.get("identity", {})
    if not isinstance(identity, Mapping):
        return ()
    layers = identity.get("identity_layers", {})
    if not isinstance(layers, Mapping):
        return ()
    return tuple(str(key) for key in layers.keys())


def _candidate_identity_layers(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    identity = candidate.get("identity", {})
    if not isinstance(identity, Mapping):
        return {}
    layers = identity.get("identity_layers", {})
    return layers if isinstance(layers, Mapping) else {}


def validate_release_subset_candidate_bindings(
    release_subset: Mapping[str, Any],
) -> Dict[str, Any]:
    """Recompute frozen release-candidate identity and hash bindings."""

    errors: list[Dict[str, Any]] = []
    raw_candidates = release_subset.get("candidates", [])
    candidates = [
        row for row in raw_candidates if isinstance(row, Mapping)
    ] if isinstance(raw_candidates, list) else []
    candidate_rows_shape_valid = isinstance(raw_candidates, list) and len(
        candidates
    ) == len(raw_candidates)
    if not isinstance(raw_candidates, list):
        errors.append(
            {
                "field": "candidates",
                "message": "release subset candidates must be a list",
            }
        )

    if isinstance(raw_candidates, list):
        for index, candidate in enumerate(raw_candidates):
            if not isinstance(candidate, Mapping):
                errors.append(
                    {
                        "field": f"candidates[{index}]",
                        "message": "candidate row must be an object",
                        "actual_type": type(candidate).__name__,
                    }
                )

    canonical_seed_rows = default_release_candidate_seed_rows()
    canonical_seed_rows_hash = stable_json_hash(canonical_seed_rows)
    canonical_candidate_ids = [
        complete_dse_candidate_id(_identity_from_seed(seed))
        for seed in canonical_seed_rows
    ]
    canonical_legal_candidates = [
        build_candidate_record(
            _identity_from_seed(seed),
            generation_source=PARAMETERIZED_RELEASE_GENERATOR_SOURCE,
        )
        for seed in canonical_seed_rows
    ]
    canonical_matrix_contract = _release_matrix_cardinality_contract(
        canonical_legal_candidates
    )
    canonical_pruning_rationale_hash = _release_pruning_rationale_contract_hash(
        canonical_seed_rows_hash
    )
    canonical_taxonomy_ids = [
        taxonomy_id
        for taxonomy_id in REQUIRED_TAXONOMY_IDS
        if taxonomy_id in {str(seed["taxonomy_id"]) for seed in canonical_seed_rows}
    ]
    provenance = release_subset.get("generation_provenance", {})
    if not isinstance(provenance, Mapping):
        errors.append(
            {
                "field": "generation_provenance",
                "message": "generation_provenance must be an object",
            }
        )
        provenance = {}
    if provenance.get("source") != PARAMETERIZED_RELEASE_GENERATOR_SOURCE:
        errors.append(
            {
                "field": "generation_provenance.source",
                "message": (
                    "release subset must come from the canonical "
                    "parameterized release generator"
                ),
                "expected": PARAMETERIZED_RELEASE_GENERATOR_SOURCE,
                "actual": provenance.get("source"),
            }
        )
    if provenance.get("seed_rows_hash") != canonical_seed_rows_hash:
        errors.append(
            {
                "field": "generation_provenance.seed_rows_hash",
                "message": "seed_rows_hash must match canonical release-v1 seed rows",
                "expected": canonical_seed_rows_hash,
                "actual": provenance.get("seed_rows_hash"),
            }
        )
    if provenance.get("pruning_rationale_hash") != canonical_pruning_rationale_hash:
        errors.append(
            {
                "field": "generation_provenance.pruning_rationale_hash",
                "message": "pruning_rationale_hash must bind the canonical release pruning rationale",
                "expected": canonical_pruning_rationale_hash,
                "actual": provenance.get("pruning_rationale_hash"),
            }
        )
    if (
        provenance.get("candidate_workflow_deployment_target_matrix_contract_hash")
        != canonical_matrix_contract["contract_hash"]
    ):
        errors.append(
            {
                "field": "generation_provenance.candidate_workflow_deployment_target_matrix_contract_hash",
                "message": (
                    "matrix provenance hash must bind the canonical "
                    "candidate/workflow/deployment-boundary/target contract"
                ),
                "expected": canonical_matrix_contract["contract_hash"],
                "actual": provenance.get(
                    "candidate_workflow_deployment_target_matrix_contract_hash"
                ),
            }
        )
    replay = release_subset.get("deterministic_replay", {})
    expected_replay_input_hash = stable_json_hash(
        {
            "seed_rows_hash": canonical_seed_rows_hash,
            "pruning_rationale_hash": canonical_pruning_rationale_hash,
            "candidate_workflow_deployment_target_matrix_contract_hash": canonical_matrix_contract[
                "contract_hash"
            ],
            "identity_layers": list(IDENTITY_LAYER_KEYS),
            "non_identity_fields": list(NON_IDENTITY_FIELDS),
        }
    )
    actual_replay_input_hash = (
        replay.get("input_hash") if isinstance(replay, Mapping) else None
    )
    if actual_replay_input_hash != expected_replay_input_hash:
        errors.append(
            {
                "field": "deterministic_replay.input_hash",
                "message": (
                    "deterministic replay input hash must bind the "
                    "canonical release-v1 seed rows"
                ),
                "expected": expected_replay_input_hash,
                "actual": actual_replay_input_hash,
            }
        )

    candidate_ids: list[str] = []
    legal_candidate_ids: list[str] = []
    included_taxonomy_ids: list[str] = []
    for index, candidate in enumerate(candidates):
        field_prefix = f"candidates[{index}]"
        candidate_id = str(candidate.get("candidate_id") or "")
        if candidate_id:
            candidate_ids.append(candidate_id)
        identity_layers = _candidate_identity_layers(candidate)
        if not identity_layers:
            errors.append(
                {
                    "field": f"{field_prefix}.identity.identity_layers",
                    "message": "candidate requires identity layers",
                }
            )
            continue
        try:
            identity = canonical_candidate_identity(identity_layers)
            expected_candidate_id = complete_dse_candidate_id(identity_layers)
            expected_identity_hash = stable_json_hash(identity)
            expected_legal, expected_reasons = classify_candidate_legality(
                identity_layers
            )
        except ValueError as exc:
            errors.append(
                {
                    "field": f"{field_prefix}.identity.identity_layers",
                    "message": str(exc),
                    "candidate_id": candidate_id,
                }
            )
            continue

        if candidate_id != expected_candidate_id:
            errors.append(
                {
                    "field": f"{field_prefix}.candidate_id",
                    "message": "candidate_id must be recomputed from design-only identity layers",
                    "expected": expected_candidate_id,
                    "actual": candidate_id,
                }
            )
        if candidate.get("identity_hash") != expected_identity_hash:
            errors.append(
                {
                    "field": f"{field_prefix}.identity_hash",
                    "message": "identity_hash must match canonical candidate identity",
                    "candidate_id": candidate_id,
                    "expected": expected_identity_hash,
                    "actual": candidate.get("identity_hash"),
                }
            )
        if candidate.get("record_hash") != _candidate_record_hash(candidate):
            errors.append(
                {
                    "field": f"{field_prefix}.record_hash",
                    "message": "record_hash must match candidate record contents",
                    "candidate_id": candidate_id,
                }
            )
        if candidate.get("generation_source") != PARAMETERIZED_RELEASE_GENERATOR_SOURCE:
            errors.append(
                {
                    "field": f"{field_prefix}.generation_source",
                    "message": (
                        "release candidate rows must come from the canonical "
                        "parameterized release generator"
                    ),
                    "candidate_id": candidate_id,
                    "expected": PARAMETERIZED_RELEASE_GENERATOR_SOURCE,
                    "actual": candidate.get("generation_source"),
                }
            )
        if candidate.get("legal") is not expected_legal:
            errors.append(
                {
                    "field": f"{field_prefix}.legal",
                    "message": "legal flag must be recomputed from release legality constraints",
                    "candidate_id": candidate_id,
                    "expected": expected_legal,
                    "actual": candidate.get("legal"),
                }
            )
        expected_illegal_reasons = [] if expected_legal else list(expected_reasons)
        actual_illegal_reasons = [
            str(reason) for reason in candidate.get("illegal_reasons", []) or []
        ]
        if sorted(actual_illegal_reasons) != sorted(expected_illegal_reasons):
            errors.append(
                {
                    "field": f"{field_prefix}.illegal_reasons",
                    "message": "illegal_reasons must match release legality constraints",
                    "candidate_id": candidate_id,
                    "expected": sorted(expected_illegal_reasons),
                    "actual": sorted(actual_illegal_reasons),
                }
            )
        if expected_legal:
            legal_candidate_ids.append(expected_candidate_id)
        architecture = identity["identity_layers"]["architecture_parameters"]
        included_taxonomy_ids.append(str(architecture.get("taxonomy_id") or ""))

    included_taxonomy_ids = [
        taxonomy_id
        for taxonomy_id in REQUIRED_TAXONOMY_IDS
        if taxonomy_id in set(included_taxonomy_ids)
    ]

    duplicates = sorted(
        candidate_id
        for candidate_id in set(candidate_ids)
        if candidate_ids.count(candidate_id) > 1
    )
    if duplicates:
        errors.append(
            {
                "field": "candidates[].candidate_id",
                "message": "duplicate candidate IDs in release subset",
                "candidate_ids": duplicates,
            }
        )

    if int(release_subset.get("candidate_count", -1) or 0) != len(candidates):
        errors.append(
            {
                "field": "candidate_count",
                "message": "candidate_count must match candidates length",
                "expected": len(candidates),
                "actual": release_subset.get("candidate_count"),
            }
        )
    if int(release_subset.get("legal_candidate_count", -1) or 0) != len(
        legal_candidate_ids
    ):
        errors.append(
            {
                "field": "legal_candidate_count",
                "message": "legal_candidate_count must match recomputed legal candidates",
                "expected": len(legal_candidate_ids),
                "actual": release_subset.get("legal_candidate_count"),
            }
        )
    if int(release_subset.get("illegal_candidate_count", -1) or 0) != (
        len(candidates) - len(legal_candidate_ids)
    ):
        errors.append(
            {
                "field": "illegal_candidate_count",
                "message": "illegal_candidate_count must match recomputed legality",
                "expected": len(candidates) - len(legal_candidate_ids),
                "actual": release_subset.get("illegal_candidate_count"),
            }
        )
    if list(release_subset.get("legal_candidate_ids", []) or []) != legal_candidate_ids:
        errors.append(
            {
                "field": "legal_candidate_ids",
                "message": "legal_candidate_ids must match recomputed legal candidate order",
                "expected": legal_candidate_ids,
                "actual": list(release_subset.get("legal_candidate_ids", []) or []),
            }
        )
    if list(release_subset.get("included_taxonomy_ids", []) or []) != included_taxonomy_ids:
        errors.append(
            {
                "field": "included_taxonomy_ids",
                "message": "included_taxonomy_ids must match candidate identity order",
                "expected": included_taxonomy_ids,
                "actual": list(release_subset.get("included_taxonomy_ids", []) or []),
            }
        )
    if candidate_ids != canonical_candidate_ids:
        errors.append(
            {
                "field": "generation_provenance.candidate_order",
                "message": "candidate order must match canonical release-v1 seed order",
                "expected": canonical_candidate_ids,
                "actual": candidate_ids,
            }
        )
    if provenance.get("candidate_order") != canonical_candidate_ids:
        errors.append(
            {
                "field": "generation_provenance.candidate_order",
                "message": "generation provenance candidate_order must match canonical release-v1 seed order",
                "expected": canonical_candidate_ids,
                "actual": provenance.get("candidate_order"),
            }
        )
    if included_taxonomy_ids != canonical_taxonomy_ids:
        errors.append(
            {
                "field": "included_taxonomy_ids",
                "message": "included taxonomy order must match canonical release-v1 seed order",
                "expected": canonical_taxonomy_ids,
                "actual": included_taxonomy_ids,
            }
        )
    actual_matrix_contract = release_subset.get(
        "candidate_workflow_deployment_target_matrix_contract"
    )
    if actual_matrix_contract != canonical_matrix_contract:
        errors.append(
            {
                "field": "candidate_workflow_deployment_target_matrix_contract",
                "message": (
                    "matrix cardinality contract must match canonical "
                    "candidate/deployment/target axes and status vocabulary"
                ),
                "expected": canonical_matrix_contract,
                "actual": actual_matrix_contract,
            }
        )

    matrix_validation = validate_candidate_workflow_deployment_target_matrix(
        release_subset
    )
    if matrix_validation["valid"] is not True:
        errors.append(
            {
                "field": "candidate_workflow_deployment_target_matrix",
                "message": (
                    "candidate/workflow/deployment-boundary/target evidence "
                    "matrix must cover the frozen release universe"
                ),
                "blockers": matrix_validation["blockers"],
            }
        )

    provenance_rows_hash = provenance.get(
        "candidate_workflow_deployment_target_matrix_rows_hash"
    )
    matrix_rows_hash = release_subset.get(
        "candidate_workflow_deployment_target_matrix_rows_hash"
    )
    actual_matrix = release_subset.get(
        "candidate_workflow_deployment_target_matrix"
    )
    actual_matrix_hash = (
        actual_matrix.get("matrix_hash")
        if isinstance(actual_matrix, Mapping)
        else None
    )
    if not matrix_rows_hash or matrix_rows_hash != actual_matrix_hash:
        errors.append(
            {
                "field": "candidate_workflow_deployment_target_matrix_rows_hash",
                "message": "matrix rows hash must bind the emitted matrix",
                "expected": actual_matrix_hash,
                "actual": matrix_rows_hash,
            }
        )
    if not provenance_rows_hash or provenance_rows_hash != actual_matrix_hash:
        errors.append(
            {
                "field": "generation_provenance.candidate_workflow_deployment_target_matrix_rows_hash",
                "message": (
                    "generation provenance must bind the emitted matrix rows"
                ),
                "expected": actual_matrix_hash,
                "actual": provenance_rows_hash,
            }
        )
    provenance_validation_hash = provenance.get(
        "candidate_workflow_deployment_target_matrix_validation_hash"
    )
    if (
        not provenance_validation_hash
        or provenance_validation_hash != matrix_validation["validation_hash"]
    ):
        errors.append(
            {
                "field": "generation_provenance.candidate_workflow_deployment_target_matrix_validation_hash",
                "message": (
                    "generation provenance must bind fail-closed matrix "
                    "validation"
                ),
                "expected": matrix_validation["validation_hash"],
                "actual": provenance_validation_hash,
            }
        )

    expected_subset_hash = _release_subset_hash(release_subset)
    if (
        candidate_rows_shape_valid
        and release_subset.get("release_subset_hash") != expected_subset_hash
    ):
        errors.append(
            {
                "field": "release_subset_hash",
                "message": "release_subset_hash must match release subset contents",
                "expected": expected_subset_hash,
                "actual": release_subset.get("release_subset_hash"),
            }
        )

    return {
        "schema_version": "dse.codesign.complete_dse.release_subset_candidate_binding_validation.v1",
        "valid": not errors,
        "errors": errors,
        "candidate_count": len(candidates),
        "legal_candidate_count": len(legal_candidate_ids),
        "candidate_identity_layers_complete": bool(candidates)
        and all(_identity_layer_keys(candidate) == IDENTITY_LAYER_KEYS for candidate in candidates),
        "expected_legal_candidate_ids": legal_candidate_ids,
        "expected_included_taxonomy_ids": included_taxonomy_ids,
        "expected_candidate_workflow_deployment_target_matrix_contract": canonical_matrix_contract,
        "candidate_workflow_deployment_target_matrix_validation": matrix_validation,
        "expected_release_subset_hash": expected_subset_hash,
        "claim_boundary": (
            "Release subset binding validation proves candidate IDs and hashes "
            "are derived from frozen design identity rows; it is not evidence closure."
        ),
    }


def _search_generation_blockers_for_release_subset(
    release_subset: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    provenance = release_subset.get("generation_provenance", {})
    provenance = provenance if isinstance(provenance, Mapping) else {}
    source = str(provenance.get("source") or "")
    if source == LEGACY_PREDECLARED_RELEASE_SOURCE:
        return [
            {
                "id": "predeclared_seed_only_not_real_search",
                "reason": (
                    "canonical release-v1 seed replay proves frozen identity "
                    "bindings only; it is not a parameterized search, generated "
                    "candidate expansion, or workload-aware screening result"
                ),
                "required_before_real_search_claim": [
                    "architecture_search_space_definition",
                    "parameterized_candidate_generation_report",
                    "workload_aware_screening_or_pruning_report",
                    "generated_candidate_records_with_provenance",
                ],
            }
        ]
    if source != PARAMETERIZED_RELEASE_GENERATOR_SOURCE:
        return [
            {
                "id": "search_generation_source_not_parameterized_generator",
                "actual": source,
                "expected": PARAMETERIZED_RELEASE_GENERATOR_SOURCE,
            }
        ]
    return []


def _search_generation_status(blockers: Sequence[Mapping[str, Any]]) -> str:
    return "real_search_generation_ready" if not blockers else "predeclared_seed_replay_only"


def build_candidate_generation_report(
    release_subset: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    subset = dict(release_subset or build_release_subset_manifest())
    candidates = [
        row for row in subset.get("candidates", []) if isinstance(row, Mapping)
    ]
    legal_candidates = [
        row for row in candidates if row.get("legal", True) is True
    ]
    binding_validation = validate_release_subset_candidate_bindings(subset)
    all_have_layers = binding_validation["candidate_identity_layers_complete"]
    search_generation_blockers = _search_generation_blockers_for_release_subset(subset)
    real_search_generation_eligible = bool(
        candidates and binding_validation["valid"] and not search_generation_blockers
    )
    matrix = subset.get("candidate_workflow_deployment_target_matrix", {})
    matrix = matrix if isinstance(matrix, Mapping) else {}
    matrix_validation = binding_validation.get(
        "candidate_workflow_deployment_target_matrix_validation",
        {},
    )
    matrix_validation = matrix_validation if isinstance(matrix_validation, Mapping) else {}
    recommendation_input_blockers: list[Dict[str, Any]] = []
    missing_provenance_candidate_ids = [
        str(candidate.get("candidate_id") or "")
        for candidate in legal_candidates
        if not isinstance(candidate.get("recommendation_input_provenance"), Mapping)
    ]
    if missing_provenance_candidate_ids:
        recommendation_input_blockers.append(
            {
                "id": "missing_recommendation_input_provenance",
                "candidate_ids": missing_provenance_candidate_ids[:20],
                "count": len(missing_provenance_candidate_ids),
            }
        )
    matrix_rows = [
        row for row in matrix.get("rows", []) or [] if isinstance(row, Mapping)
    ]
    observed_matrix_statuses = [
        str(row.get("status") or "") for row in matrix_rows if str(row.get("status") or "")
    ]
    trusted_matrix_row_count = sum(
        1 for status in observed_matrix_statuses if status in {"trusted_pass", "trusted_fail"}
    )
    blocked_missing_input_count = sum(
        1 for status in observed_matrix_statuses if status == "blocked_missing_input"
    )
    if matrix_validation.get("valid") is not True:
        recommendation_input_blockers.append(
            {
                "id": "candidate_workflow_deployment_target_matrix_not_valid",
                "blocker_count": len(matrix_validation.get("blockers", []) or []),
            }
        )
    payload = {
        "schema_version": "dse.codesign.complete_dse.candidate_generation_report.v1",
        "status": "passed"
        if all_have_layers and candidates and binding_validation["valid"]
        else "failed",
        "release_id": RELEASE_ID,
        "release_subset_hash": subset.get("release_subset_hash"),
        "candidate_count": subset.get("candidate_count", 0),
        "legal_candidate_count": subset.get("legal_candidate_count", 0),
        "generation_mode": (
            subset.get("generation_provenance", {}) or {}
        ).get("generation_mode", "unknown"),
        "parameter_profile_ids": (
            subset.get("generation_provenance", {}) or {}
        ).get("parameter_profile_ids", []),
        "all_candidates_have_all_identity_layers": all_have_layers,
        "candidate_identity_binding_valid": binding_validation["valid"],
        "candidate_identity_binding_error_count": len(binding_validation["errors"]),
        "candidate_identity_binding_errors": binding_validation["errors"],
        "identity_layers": list(IDENTITY_LAYER_KEYS),
        "excluded_from_identity": list(NON_IDENTITY_FIELDS),
        "stable_candidate_ids_emitted": all_have_layers and binding_validation["valid"],
        "candidate_id_rule": "design-only release-universe stable hash; evaluation matrix metadata excluded",
        "search_generation_status": _search_generation_status(search_generation_blockers),
        "real_search_generation_eligible": real_search_generation_eligible,
        "search_generation_blockers": search_generation_blockers,
        "deployment_completion_candidate_source_ready": real_search_generation_eligible,
        "recommendation_candidate_input_contract": {
            "schema_version": (
                "dse.codesign.complete_dse.recommendation_candidate_input_contract.v1"
            ),
            "status": (
                "release_universe_candidate_inputs_ready_evidence_pending"
                if not recommendation_input_blockers
                else "blocked_release_universe_candidate_input_contract"
            ),
            "derived_from_reproducible_release_universe": real_search_generation_eligible,
            "fixed_or_manual_top_k_seed_source_allowed": False,
            "candidate_source": "release_subset_manifest.legal_candidate_ids",
            "candidate_count": len(legal_candidates),
            "candidate_ids": [
                str(candidate.get("candidate_id") or "")
                for candidate in legal_candidates
            ],
            "release_subset_hash": subset.get("release_subset_hash"),
            "generation_source": (
                subset.get("generation_provenance", {}) or {}
            ).get("source"),
            "generation_mode": (
                subset.get("generation_provenance", {}) or {}
            ).get("generation_mode"),
            "pruning_rationale_hash": (
                subset.get("generation_provenance", {}) or {}
            ).get("pruning_rationale_hash"),
            "legality_constraints_hash": (
                subset.get("generation_provenance", {}) or {}
            ).get("legality_constraints_hash"),
            "candidate_workflow_deployment_target_matrix_hash": matrix.get("matrix_hash"),
            "candidate_workflow_deployment_target_matrix_validation_hash": (
                matrix_validation.get("validation_hash")
            ),
            "artifact_provenance": _release_universe_artifact_provenance(
                release_subset=subset,
                matrix=matrix,
                matrix_validation=matrix_validation,
            ),
            "evidence_rows_fail_closed_by_default": (
                bool(matrix_rows)
                and blocked_missing_input_count == len(matrix_rows)
            ),
            "trusted_ppa_evidence_ready": trusted_matrix_row_count > 0,
            "observed_matrix_row_statuses": list(dict.fromkeys(observed_matrix_statuses)),
            "blockers": recommendation_input_blockers,
            "claim_boundary": (
                "Best/Pareto recommendation candidates must be sourced from the "
                "stable release universe; this contract is not PPA evidence and "
                "keeps missing evidence rows fail-closed."
            ),
        },
        "provenance": {
            "release_subset_hash": subset.get("release_subset_hash"),
            "expected_release_subset_hash": binding_validation.get("expected_release_subset_hash"),
            "candidate_ids": [
                str(candidate.get("candidate_id")) for candidate in candidates
            ],
            "candidate_record_hashes": [
                str(candidate.get("record_hash")) for candidate in candidates
            ],
            "pruning_rationale_hash": (
                subset.get("generation_provenance", {}) or {}
            ).get("pruning_rationale_hash"),
            "candidate_workflow_deployment_target_matrix_contract_hash": (
                subset.get("generation_provenance", {}) or {}
            ).get("candidate_workflow_deployment_target_matrix_contract_hash"),
            "deterministic_replay_hash": (
                subset.get("deterministic_replay", {}) or {}
            ).get("replay_hash"),
        },
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
        "provenance": {
            "release_subset_hash": subset.get("release_subset_hash"),
            "legality_constraints_hash": build_legality_constraints_manifest()[
                "constraints_hash"
            ],
            "pruning_phase": "pre_freeze_only",
            "post_freeze_row_removal_allowed": False,
        },
        "claim_boundary": "pruning explains pre-freeze release universe only; it is not completion evidence",
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def build_release_pruning_rationale_report(
    release_subset: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Alias the legality-pruning report under the PRD-required artifact name."""
    payload = dict(build_legality_pruning_report(release_subset))
    payload["schema_version"] = (
        "dse.codesign.complete_dse.release_pruning_rationale_report.v1"
    )
    payload["artifact_alias_for"] = "legality_pruning_report.json"
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
        "frozen_workload_case_count": DEFAULT_FROZEN_WORKLOAD_CASE_COUNT,
        "frozen_workload_cases_target_min": DEFAULT_FROZEN_WORKLOAD_CASE_COUNT,
        "frozen_workload_cases_hard_cap": DEFAULT_FROZEN_WORKLOAD_CASE_COUNT,
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
    frozen_workload_case_count: int = DEFAULT_FROZEN_WORKLOAD_CASE_COUNT,
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


def _candidate_identity_layers(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    identity = candidate.get("identity", {})
    if not isinstance(identity, Mapping):
        return {}
    layers = identity.get("identity_layers", {})
    if not isinstance(layers, Mapping):
        return {}
    return {str(key): layers[key] for key in layers}


def _candidate_axis_value(
    candidate: Mapping[str, Any],
    *,
    layer_name: str,
    field_name: str,
) -> str:
    layer = _candidate_identity_layers(candidate).get(layer_name, {})
    if not isinstance(layer, Mapping):
        return ""
    return str(layer.get(field_name) or "")


def _legal_release_candidates(
    release_subset: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    return [
        candidate
        for candidate in release_subset.get("candidates", []) or []
        if isinstance(candidate, Mapping) and candidate.get("legal", True) is True
    ]


def _legal_candidate_ids_from_records(
    release_subset: Mapping[str, Any],
) -> list[str]:
    return [
        str(candidate.get("candidate_id") or "")
        for candidate in _legal_release_candidates(release_subset)
    ]


def _expected_search_axis_ids() -> Dict[str, list[str]]:
    return {
        "taxonomy": list(REQUIRED_TAXONOMY_IDS),
        "algorithm": [
            str(row["id"]) for row in build_algorithm_family_manifest()["families"]
        ],
        "mapping": [
            str(row["id"]) for row in build_mapping_layout_space()["mappings"]
        ],
        "compile_schedule": [
            str(row["id"])
            for row in build_compile_schedule_space()["compile_time_schedules"]
        ],
        "runtime_schedule": [
            str(row["id"])
            for row in build_runtime_schedule_space()["runtime_schedules"]
        ],
        "parameter_profile": list(PARAMETER_PROFILE_ORDER),
        "target_platform": list(REQUIRED_TARGET_PLATFORM_IDS),
    }


def _search_axis_specs() -> Dict[str, Dict[str, str]]:
    return {
        "taxonomy": {
            "layer": "architecture_parameters",
            "field": "taxonomy_id",
        },
        "algorithm": {
            "layer": "algorithm_parameters",
            "field": "algorithm_id",
        },
        "mapping": {
            "layer": "mapping_layout_parameters",
            "field": "mapping_id",
        },
        "compile_schedule": {
            "layer": "compile_time_schedule_parameters",
            "field": "compile_schedule_id",
        },
        "runtime_schedule": {
            "layer": "runtime_scheduling_parameters",
            "field": "runtime_schedule_id",
        },
        "parameter_profile": {
            "layer": "algorithm_parameters",
            "field": "parameter_profile_id",
        },
        "target_platform": {
            "layer": "target_platform_parameters",
            "field": "target_platform_id",
        },
    }


def _axis_tuple(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    specs = _search_axis_specs()
    return tuple(
        _candidate_axis_value(
            candidate,
            layer_name=specs[axis]["layer"],
            field_name=specs[axis]["field"],
        )
        for axis in (
            "taxonomy",
            "algorithm",
            "mapping",
            "compile_schedule",
            "runtime_schedule",
            "parameter_profile",
            "target_platform",
        )
    )


def _profile_consistency_violations(
    candidates: Sequence[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    violations: list[Dict[str, Any]] = []
    for candidate in candidates:
        layers = _candidate_identity_layers(candidate)
        values: Dict[str, str] = {}
        for layer_name in IDENTITY_LAYER_KEYS:
            layer = layers.get(layer_name, {})
            if isinstance(layer, Mapping):
                values[layer_name] = str(layer.get("parameter_profile_id") or "")
            else:
                values[layer_name] = ""
        non_empty = {value for value in values.values() if value}
        if len(non_empty) != 1 or "" in values.values():
            violations.append(
                {
                    "candidate_id": str(candidate.get("candidate_id") or ""),
                    "profile_values_by_layer": values,
                }
            )
    return violations


def _non_identity_contamination(
    candidates: Sequence[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    contaminated: list[Dict[str, Any]] = []
    for candidate in candidates:
        layers = _candidate_identity_layers(candidate)
        paths = sorted(set(_forbidden_identity_field_paths(layers)))
        if paths:
            contaminated.append(
                {
                    "candidate_id": str(candidate.get("candidate_id") or ""),
                    "paths": paths,
                }
            )
    return contaminated


def _build_axis_coverage(
    candidates: Sequence[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    expected_by_axis = _expected_search_axis_ids()
    specs = _search_axis_specs()
    coverage: Dict[str, Dict[str, Any]] = {}
    for axis, expected_ids in expected_by_axis.items():
        spec = specs[axis]
        values = [
            _candidate_axis_value(
                candidate,
                layer_name=spec["layer"],
                field_name=spec["field"],
            )
            for candidate in candidates
        ]
        missing_value_count = sum(1 for value in values if not value)
        counts = _count_values(value for value in values if value)
        observed_ids = list(counts)
        missing_expected = [
            item for item in expected_ids if item not in set(observed_ids)
        ]
        unexpected = [
            item for item in observed_ids if item not in set(expected_ids)
        ]
        expected_count = len(expected_ids)
        coverage_ratio = (
            len(set(observed_ids).intersection(expected_ids)) / expected_count
            if expected_count
            else 1.0
        )
        degenerate = (
            len(observed_ids) <= 1
            and expected_count > 1
            and len(candidates) > 1
        )
        coverage[axis] = {
            "expected_ids": expected_ids,
            "observed_ids": observed_ids,
            "observed_count_by_id": counts,
            "expected_id_count": expected_count,
            "observed_id_count": len(observed_ids),
            "missing_expected_ids": missing_expected,
            "unexpected_ids": unexpected,
            "missing_value_count": missing_value_count,
            "coverage_ratio": coverage_ratio,
            "degenerate": degenerate,
            "passed": (
                not missing_expected
                and not unexpected
                and missing_value_count == 0
                and not degenerate
            ),
        }
    return coverage


def _build_template_coverage(
    axis_coverage: Mapping[str, Any],
) -> Dict[str, Any]:
    taxonomy_counts = dict(
        (
            axis_coverage.get("taxonomy", {})
            if isinstance(axis_coverage.get("taxonomy"), Mapping)
            else {}
        ).get("observed_count_by_id", {})
    )
    base_missing = [
        taxonomy_id
        for taxonomy_id in REQUIRED_BASE_FAMILIES
        if taxonomy_counts.get(taxonomy_id, 0) <= 0
    ]
    hybrid_missing = [
        taxonomy_id
        for taxonomy_id in REQUIRED_HYBRID_TEMPLATES
        if taxonomy_counts.get(taxonomy_id, 0) <= 0
    ]
    required_counts = [
        int(taxonomy_counts.get(taxonomy_id, 0))
        for taxonomy_id in REQUIRED_TAXONOMY_IDS
    ]
    return {
        "required_base_families": list(REQUIRED_BASE_FAMILIES),
        "required_hybrid_templates": list(REQUIRED_HYBRID_TEMPLATES),
        "candidate_count_by_taxonomy": taxonomy_counts,
        "missing_required_base_families": base_missing,
        "missing_required_hybrid_templates": hybrid_missing,
        "min_candidates_per_required_taxonomy": min(required_counts)
        if required_counts
        else 0,
        "max_candidates_per_required_taxonomy": max(required_counts)
        if required_counts
        else 0,
        "passed": not base_missing and not hybrid_missing,
        "claim_boundary": (
            "template coverage proves representation in the generated release "
            "universe only; it is not PPA, correctness, or winner evidence"
        ),
    }


def _build_queue_preservation_report(
    *,
    release_subset: Mapping[str, Any],
    step3_queue: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    expected_ids = _legal_candidate_ids_from_records(release_subset)
    release_hash = release_subset.get("release_subset_hash") or release_subset.get(
        "manifest_hash"
    )
    if step3_queue is None:
        return {
            "status": "not_applicable",
            "queue_supplied": False,
            "expected_candidate_count": len(expected_ids),
            "claim_boundary": (
                "queue preservation is evaluated after Step2 binding emits "
                "step3_simulation_queue.json"
            ),
        }

    entries = [
        entry
        for entry in step3_queue.get("entries", []) or []
        if isinstance(entry, Mapping)
    ]
    actual_ids = [str(entry.get("candidate_id") or "") for entry in entries]
    declared_ids = [
        str(item) for item in step3_queue.get("candidate_ids", []) or []
    ]
    expected_set = set(expected_ids)
    actual_set = set(actual_ids)
    blockers: list[Dict[str, Any]] = []
    dropped = [candidate_id for candidate_id in expected_ids if candidate_id not in actual_set]
    extra = [candidate_id for candidate_id in actual_ids if candidate_id not in expected_set]
    duplicate_ids = _duplicate_values(actual_ids)

    if dropped:
        blockers.append(
            {
                "id": "step2_queue_drops_release_candidate",
                "candidate_ids": dropped[:20],
                "count": len(dropped),
            }
        )
    if extra:
        blockers.append(
            {
                "id": "step2_queue_has_extra_candidate",
                "candidate_ids": extra[:20],
                "count": len(extra),
            }
        )
    if actual_ids != expected_ids:
        blockers.append(
            {
                "id": "step2_queue_candidate_order_mismatch",
                "first_expected": expected_ids[:5],
                "first_actual": actual_ids[:5],
            }
        )
    if declared_ids != actual_ids:
        blockers.append(
            {
                "id": "step2_queue_declared_ids_mismatch",
                "declared_count": len(declared_ids),
                "entry_count": len(actual_ids),
            }
        )
    if duplicate_ids:
        blockers.append(
            {
                "id": "step2_queue_duplicate_candidate_ids",
                "duplicates": duplicate_ids[:20],
            }
        )
    declared_entry_count = _optional_int(step3_queue.get("entry_count"))
    if declared_entry_count != len(entries):
        blockers.append(
            {
                "id": "step2_queue_entry_count_mismatch",
                "declared": step3_queue.get("entry_count"),
                "actual": len(entries),
            }
        )
    if step3_queue.get("release_subset_hash") != release_hash:
        blockers.append(
            {
                "id": "step2_queue_release_subset_hash_mismatch",
                "expected": release_hash,
                "actual": step3_queue.get("release_subset_hash"),
            }
        )
    if step3_queue.get("queue_mode") != "complete-dse-release-universe":
        blockers.append(
            {
                "id": "step2_queue_mode_not_release_universe",
                "actual": step3_queue.get("queue_mode"),
            }
        )
    if step3_queue.get("retention_policy") != "complete_dse_release_universe":
        blockers.append(
            {
                "id": "step2_queue_retention_policy_not_release_universe",
                "actual": step3_queue.get("retention_policy"),
            }
        )
    if step3_queue.get("trusted_final_claim") is True:
        blockers.append({"id": "step2_queue_forbidden_trusted_claim"})
    if step3_queue.get("top_k_queue_deferred") is not False:
        blockers.append(
            {
                "id": "step2_queue_top_k_or_deferred_policy_present",
                "actual": step3_queue.get("top_k_queue_deferred"),
            }
        )

    priority_reasons_ok = all(
        any(
            isinstance(reason, Mapping)
            and reason.get("reason_id")
            == "complete_dse_exhaustive_release_universe"
            for reason in entry.get("priority_reasons", []) or []
        )
        for entry in entries
    )
    return {
        "status": "passed" if not blockers else "blocked",
        "queue_supplied": True,
        "queue_mode": step3_queue.get("queue_mode"),
        "retention_policy": step3_queue.get("retention_policy"),
        "release_subset_hash": step3_queue.get("release_subset_hash"),
        "expected_candidate_count": len(expected_ids),
        "entry_count": len(entries),
        "declared_candidate_count": len(declared_ids),
        "candidate_order_preserved": actual_ids == expected_ids,
        "candidate_set_preserved": not dropped and not extra,
        "declared_ids_match_entries": declared_ids == actual_ids,
        "duplicate_candidate_ids": duplicate_ids,
        "dropped_candidate_ids": dropped,
        "extra_candidate_ids": extra,
        "priority_score_semantics": {
            "objective_scores_available": False,
            "priority_scores_are_objective_scores": False,
            "priority_scores_are_queue_order_only": True,
            "priority_reasons_all_exhaustive_release_universe": priority_reasons_ok,
            "unique_priority_score_count": len(
                {
                    str(entry.get("priority_score"))
                    for entry in entries
                    if entry.get("priority_score") is not None
                }
            ),
        },
        "blockers": blockers,
        "claim_boundary": (
            "queue preservation proves exhaustive Step2 admission only; it is "
            "not a ranking, PPA, correctness, or completion proof"
        ),
    }


def build_complete_dse_search_effectiveness_report(
    release_subset: Mapping[str, Any] | None = None,
    *,
    step3_queue: Mapping[str, Any] | None = None,
    selection_policy: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Audit that complete-DSE search is a non-degenerate release universe.

    The report intentionally stops at framework/search effectiveness: it checks
    axis coverage, identity uniqueness, and optional Step2 queue preservation.
    It never names FPGA/ASIC winners and never upgrades blocked downstream
    L4/QE/EDA evidence into completion.
    """

    subset = dict(release_subset or build_release_subset_manifest())
    candidates = [
        candidate
        for candidate in subset.get("candidates", []) or []
        if isinstance(candidate, Mapping)
    ]
    legal_candidates = _legal_release_candidates(subset)
    legal_candidate_ids = _legal_candidate_ids_from_records(subset)
    declared_legal_candidate_ids = [
        str(item) for item in subset.get("legal_candidate_ids", []) or []
    ]
    axis_coverage = _build_axis_coverage(legal_candidates)
    template_coverage = _build_template_coverage(axis_coverage)
    queue_preservation = _build_queue_preservation_report(
        release_subset=subset,
        step3_queue=step3_queue,
    )
    selection = dict(
        selection_policy
        or {"selection_kind": "predeclared_finite_release_subset"}
    )
    blockers: list[Dict[str, Any]] = []

    declared_candidate_count = _optional_int(subset.get("candidate_count"))
    declared_legal_count = _optional_int(subset.get("legal_candidate_count"))
    if declared_candidate_count != len(candidates):
        blockers.append(
            {
                "id": "candidate_count_mismatch",
                "declared": declared_candidate_count,
                "actual": len(candidates),
            }
        )
    if declared_legal_count != len(legal_candidates):
        blockers.append(
            {
                "id": "legal_candidate_count_mismatch",
                "declared": declared_legal_count,
                "actual": len(legal_candidates),
            }
        )
    if declared_legal_candidate_ids != legal_candidate_ids:
        blockers.append(
            {
                "id": "legal_candidate_ids_mismatch",
                "declared_count": len(declared_legal_candidate_ids),
                "actual_count": len(legal_candidate_ids),
            }
        )
    if not legal_candidates:
        blockers.append({"id": "no_legal_release_candidates"})

    illegal_candidate_ids = [
        str(candidate.get("candidate_id") or "")
        for candidate in candidates
        if candidate.get("legal", True) is not True
    ]
    if illegal_candidate_ids:
        blockers.append(
            {
                "id": "illegal_candidate_in_release_subset",
                "candidate_ids": illegal_candidate_ids[:20],
                "count": len(illegal_candidate_ids),
            }
        )

    for axis, coverage in axis_coverage.items():
        if coverage["missing_expected_ids"]:
            blockers.append(
                {
                    "id": "axis_missing_expected_values",
                    "axis": axis,
                    "missing": coverage["missing_expected_ids"],
                }
            )
        if coverage["unexpected_ids"]:
            blockers.append(
                {
                    "id": "axis_unexpected_values",
                    "axis": axis,
                    "unexpected": coverage["unexpected_ids"],
                }
            )
        if coverage["missing_value_count"]:
            blockers.append(
                {
                    "id": "axis_missing_candidate_values",
                    "axis": axis,
                    "missing_value_count": coverage["missing_value_count"],
                }
            )
        if coverage["degenerate"]:
            blockers.append(
                {
                    "id": "axis_degenerate",
                    "axis": axis,
                    "observed_ids": coverage["observed_ids"],
                }
            )

    if not template_coverage["passed"]:
        blockers.append(
            {
                "id": "template_coverage_missing_required_taxonomy",
                "missing_required_base_families": template_coverage[
                    "missing_required_base_families"
                ],
                "missing_required_hybrid_templates": template_coverage[
                    "missing_required_hybrid_templates"
                ],
            }
        )

    candidate_ids = [
        str(candidate.get("candidate_id") or "")
        for candidate in legal_candidates
    ]
    identity_hashes = [
        str(candidate.get("identity_hash") or "") for candidate in legal_candidates
    ]
    record_hashes = [
        str(candidate.get("record_hash") or "") for candidate in legal_candidates
    ]
    missing_candidate_ids = [
        str(index)
        for index, candidate in enumerate(legal_candidates)
        if not candidate.get("candidate_id")
    ]
    missing_identity_hashes = [
        str(candidate.get("candidate_id") or f"index::{index}")
        for index, candidate in enumerate(legal_candidates)
        if not candidate.get("identity_hash")
    ]
    missing_record_hashes = [
        str(candidate.get("candidate_id") or f"index::{index}")
        for index, candidate in enumerate(legal_candidates)
        if not candidate.get("record_hash")
    ]
    tuple_field_names = [
        "taxonomy_id",
        "algorithm_id",
        "mapping_id",
        "compile_schedule_id",
        "runtime_schedule_id",
        "parameter_profile_id",
        "target_platform_id",
    ]
    missing_identity_tuple_fields: list[Dict[str, Any]] = []
    for candidate in legal_candidates:
        axis_tuple = _axis_tuple(candidate)
        missing_fields = [
            tuple_field_names[index]
            for index, value in enumerate(axis_tuple)
            if not value
        ]
        if missing_fields:
            missing_identity_tuple_fields.append(
                {
                    "candidate_id": str(candidate.get("candidate_id") or ""),
                    "missing_fields": missing_fields,
                }
            )
    if missing_candidate_ids:
        blockers.append(
            {
                "id": "missing_candidate_id",
                "candidate_indexes": missing_candidate_ids[:20],
                "count": len(missing_candidate_ids),
            }
        )
    if missing_identity_hashes:
        blockers.append(
            {
                "id": "missing_identity_hash",
                "candidate_ids": missing_identity_hashes[:20],
                "count": len(missing_identity_hashes),
            }
        )
    if missing_record_hashes:
        blockers.append(
            {
                "id": "missing_record_hash",
                "candidate_ids": missing_record_hashes[:20],
                "count": len(missing_record_hashes),
            }
        )
    if missing_identity_tuple_fields:
        blockers.append(
            {
                "id": "missing_identity_tuple_fields",
                "violations": missing_identity_tuple_fields[:20],
                "count": len(missing_identity_tuple_fields),
            }
        )
    tuple_strings = [
        stable_json_hash({"axis_tuple": list(_axis_tuple(candidate))})
        for candidate in legal_candidates
    ]
    duplicate_candidate_ids = _duplicate_values(candidate_ids)
    duplicate_identity_hashes = _duplicate_values(identity_hashes)
    duplicate_record_hashes = _duplicate_values(record_hashes)
    duplicate_axis_tuples = _duplicate_values(tuple_strings)
    if duplicate_candidate_ids:
        blockers.append(
            {
                "id": "duplicate_candidate_ids",
                "duplicates": duplicate_candidate_ids[:20],
            }
        )
    if duplicate_identity_hashes:
        blockers.append(
            {
                "id": "duplicate_identity_hashes",
                "duplicates": duplicate_identity_hashes[:20],
            }
        )
    if duplicate_record_hashes:
        blockers.append(
            {
                "id": "duplicate_record_hashes",
                "duplicates": duplicate_record_hashes[:20],
            }
        )
    if duplicate_axis_tuples:
        blockers.append(
            {
                "id": "duplicate_identity_tuples",
                "duplicates": duplicate_axis_tuples[:20],
            }
        )

    profile_violations = _profile_consistency_violations(legal_candidates)
    if profile_violations:
        blockers.append(
            {
                "id": "parameter_profile_identity_layer_mismatch",
                "violations": profile_violations[:20],
            }
        )
    contaminated = _non_identity_contamination(legal_candidates)
    if contaminated:
        blockers.append(
            {
                "id": "non_identity_field_contaminates_candidate_identity",
                "violations": contaminated[:20],
            }
        )

    generation_mode = (
        subset.get("generation_provenance", {}) or {}
    ).get("generation_mode")
    if generation_mode != "bounded_compatible_cartesian_product":
        blockers.append(
            {
                "id": "search_generation_mode_not_parameterized_cartesian",
                "actual": generation_mode,
            }
        )
    if (subset.get("generation_provenance", {}) or {}).get(
        "post_freeze_row_removal_allowed"
    ) is not False:
        blockers.append({"id": "post_freeze_row_removal_not_forbidden"})

    selection_kind = str(selection.get("selection_kind", ""))
    downgraded_selection = selection_kind in BANNED_COMPLETION_SUBSETS
    fixed_candidate_only = selection.get("fixed_candidate_only") is True
    if downgraded_selection:
        blockers.append(
            {
                "id": "downgraded_subset_selection",
                "selection_kind": selection_kind,
            }
        )
    if fixed_candidate_only:
        blockers.append({"id": "fixed_candidate_only_downgrade"})

    queue_blockers = queue_preservation.get("blockers", [])
    if isinstance(queue_blockers, Sequence) and not isinstance(
        queue_blockers, (str, bytes, bytearray)
    ):
        blockers.extend(
            dict(blocker)
            for blocker in queue_blockers
            if isinstance(blocker, Mapping)
        )

    cross_axis_diversity = {
        "identity_tuple_fields": [
            "taxonomy_id",
            "algorithm_id",
            "mapping_id",
            "compile_schedule_id",
            "runtime_schedule_id",
            "parameter_profile_id",
        ],
        "candidate_tuple_count": len(tuple_strings),
        "unique_candidate_id_count": len(set(candidate_ids)),
        "unique_identity_hash_count": len(set(identity_hashes)),
        "unique_record_hash_count": len(set(record_hashes)),
        "unique_identity_tuple_count": len(set(tuple_strings)),
        "duplicate_candidate_ids": duplicate_candidate_ids,
        "duplicate_identity_hashes": duplicate_identity_hashes,
        "duplicate_record_hashes": duplicate_record_hashes,
        "duplicate_identity_tuples": duplicate_axis_tuples,
        "all_candidate_ids_unique": not duplicate_candidate_ids,
        "all_identity_hashes_unique": not duplicate_identity_hashes,
        "all_record_hashes_unique": not duplicate_record_hashes,
        "all_identity_tuples_unique": not duplicate_axis_tuples,
        "parameter_profile_consistent_across_identity_layers": not profile_violations,
        "non_identity_fields_absent_from_identity": not contaminated,
    }
    payload = {
        "schema_version": "dse.codesign.complete_dse.search_effectiveness_report.v1",
        "status": "passed" if not blockers else "blocked",
        "release_id": RELEASE_ID,
        "release_subset_hash": subset.get("release_subset_hash"),
        "candidate_counts": {
            "candidate_count": len(candidates),
            "legal_candidate_count": len(legal_candidates),
            "declared_candidate_count": subset.get("candidate_count"),
            "declared_legal_candidate_count": subset.get(
                "legal_candidate_count"
            ),
            "declared_legal_candidate_id_count": len(
                declared_legal_candidate_ids
            ),
        },
        "search_policy": {
            "generation_mode": generation_mode,
            "selection_policy": selection,
            "intended_exhaustive_release_universe": True,
            "exhaustive_release_universe": not blockers,
            "validated_exhaustive_release_universe": not blockers,
            "top_k_or_representative_completion_allowed": False,
            "fixed_candidate_completion_allowed": False,
            "post_freeze_row_removal_allowed": (
                subset.get("generation_provenance", {}) or {}
            ).get("post_freeze_row_removal_allowed"),
        },
        "axis_coverage": axis_coverage,
        "template_coverage": template_coverage,
        "cross_axis_diversity": cross_axis_diversity,
        "identity_integrity": {
            "missing_candidate_ids": missing_candidate_ids,
            "missing_identity_hashes": missing_identity_hashes,
            "missing_record_hashes": missing_record_hashes,
            "missing_identity_tuple_fields": missing_identity_tuple_fields,
            "all_candidate_ids_present": not missing_candidate_ids,
            "all_identity_hashes_present": not missing_identity_hashes,
            "all_record_hashes_present": not missing_record_hashes,
            "all_identity_tuple_fields_present": not missing_identity_tuple_fields,
        },
        "queue_preservation": queue_preservation,
        "score_diversity": {
            "status": "not_applicable",
            "objective_scores_available": False,
            "reason": (
                "complete-DSE release-v1 is an exhaustive admission universe; "
                "queue priority is not a winner/ranking score"
            ),
            "priority_score_semantics": queue_preservation.get(
                "priority_score_semantics",
                {
                    "objective_scores_available": False,
                    "priority_scores_are_objective_scores": False,
                },
            ),
        },
        "blockers": blockers,
        "can_name_best_fpga_or_asic": False,
        "trusted_ppa_or_winner_evidence_present": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Search effectiveness is framework/admission evidence only: it "
            "proves a non-degenerate generated release universe and optional "
            "Step2 queue preservation, but not QE correctness, L4 speedup, "
            "FPGA/ASIC PPA, winner selection, or deliverable completion."
        ),
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


def _missing_required_target_platform_ids(
    release_subset: Mapping[str, Any],
) -> list[str]:
    target_platform_ids: set[str] = set()
    for candidate in release_subset.get("candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        layers = _candidate_identity_layers(candidate)
        target = layers.get("target_platform_parameters", {})
        if not isinstance(target, Mapping):
            continue
        target_platform_id = str(target.get("target_platform_id") or "")
        if target_platform_id:
            target_platform_ids.add(target_platform_id)
    return [
        target_platform_id
        for target_platform_id in REQUIRED_TARGET_PLATFORM_IDS
        if target_platform_id not in target_platform_ids
    ]


def _missing_required_target_platform_kinds(
    release_subset: Mapping[str, Any],
) -> list[str]:
    platform_kinds: set[str] = set()
    for candidate in release_subset.get("candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        layers = _candidate_identity_layers(candidate)
        target = layers.get("target_platform_parameters", {})
        if not isinstance(target, Mapping):
            continue
        platform_kind = str(target.get("platform_kind") or "")
        if platform_kind:
            platform_kinds.add(platform_kind)
    return [
        platform_kind
        for platform_kind in REQUIRED_TARGET_PLATFORM_KINDS
        if platform_kind not in platform_kinds
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
    binding_validation = validate_release_subset_candidate_bindings(subset)
    matrix_validation = binding_validation[
        "candidate_workflow_deployment_target_matrix_validation"
    ]
    search_generation_blockers = _search_generation_blockers_for_release_subset(subset)
    real_search_generation_eligible = bool(
        binding_validation["valid"] and not search_generation_blockers
    )
    if binding_validation["valid"] is not True:
        blockers.append(
            {
                "id": "candidate_identity_binding_invalid",
                "error_count": len(binding_validation["errors"]),
                "errors": binding_validation["errors"],
            }
        )
    if matrix_validation["valid"] is not True:
        blockers.append(
            {
                "id": "candidate_workflow_deployment_target_matrix_invalid",
                "blocker_count": len(matrix_validation["blockers"]),
                "blockers": matrix_validation["blockers"],
            }
        )

    legal_count = int(subset.get("legal_candidate_count") or 0)
    hard_cap = int(
        budget_payload.get("legal_release_candidates_hard_cap") or 0
    )
    target_min = int(
        budget_payload.get("legal_release_candidates_target_min") or 0
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
    if target_min and 0 < legal_count < target_min:
        blockers.append(
            {
                "id": "candidate_count_below_target_min",
                "count": legal_count,
                "target_min": target_min,
                "reason": (
                    "release subset is too small to prove a meaningful "
                    "parameterized search universe"
                ),
            }
        )

    missing = _missing_required_taxonomy_ids(subset)
    if missing:
        blockers.append(
            {"id": "missing_required_taxonomy_entries", "missing": missing}
        )
    missing_target_platforms = _missing_required_target_platform_ids(subset)
    if missing_target_platforms:
        blockers.append(
            {
                "id": "missing_required_target_platform_entries",
                "missing": missing_target_platforms,
            }
        )
    missing_target_platform_kinds = _missing_required_target_platform_kinds(
        subset
    )
    if missing_target_platform_kinds:
        blockers.append(
            {
                "id": "missing_required_target_platform_kind_entries",
                "missing": missing_target_platform_kinds,
            }
        )

    unpredeclared_taxonomy_ids: list[str] = []
    illegal_candidate_ids: list[str] = []
    for candidate in subset.get("candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("candidate_id", "unknown_candidate"))
        if candidate.get("legal") is not True:
            illegal_candidate_ids.append(candidate_id)
        identity = candidate.get("identity", {})
        if not isinstance(identity, Mapping):
            continue
        layers = identity.get("identity_layers", {})
        if not isinstance(layers, Mapping):
            continue
        architecture = layers.get("architecture_parameters", {})
        if not isinstance(architecture, Mapping):
            continue
        taxonomy_id = str(architecture.get("taxonomy_id", ""))
        if taxonomy_id and taxonomy_id not in REQUIRED_TAXONOMY_IDS:
            unpredeclared_taxonomy_ids.append(taxonomy_id)

    if unpredeclared_taxonomy_ids:
        blockers.append(
            {
                "id": "unpredeclared_release_taxonomy",
                "taxonomy_ids": sorted(set(unpredeclared_taxonomy_ids)),
            }
        )
    if illegal_candidate_ids:
        blockers.append(
            {
                "id": "illegal_candidate_in_release_subset",
                "candidate_ids": sorted(set(illegal_candidate_ids)),
            }
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
    if policy.get("final_release_universe_claim") is True:
        provenance = subset.get("generation_provenance", {})
        provenance = provenance if isinstance(provenance, Mapping) else {}
        if not provenance.get("pruning_rationale_hash"):
            blockers.append(
                {
                    "id": "missing_release_pruning_rationale_provenance",
                    "reason": (
                        "a final release universe claim requires stable "
                        "pruning/rationale provenance"
                    ),
                }
            )
        matrix_contract = subset.get(
            "candidate_workflow_deployment_target_matrix_contract"
        )
        matrix_rows_hash = (
            policy.get("candidate_workflow_deployment_target_matrix_rows_hash")
            or subset.get("candidate_workflow_deployment_target_matrix_rows_hash")
            or provenance.get(
                "candidate_workflow_deployment_target_matrix_rows_hash"
            )
        )
        if (
            not provenance.get(
                "candidate_workflow_deployment_target_matrix_contract_hash"
            )
            or not isinstance(matrix_contract, Mapping)
            or not matrix_contract.get("contract_hash")
            or not matrix_rows_hash
        ):
            blockers.append(
                {
                    "id": "missing_candidate_workflow_deployment_target_matrix_provenance",
                    "reason": (
                        "a final release universe claim requires candidate × "
                        "workflow × deployment-boundary × target matrix "
                        "row provenance and fail-closed row status vocabulary"
                    ),
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

    all_have_layers = binding_validation["candidate_identity_layers_complete"]
    if not all_have_layers:
        blockers.append(
            {
                "id": "missing_identity_layer",
                "reason": "all required identity layers are required before freeze",
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
        "candidate_identity_binding_validation": binding_validation,
        "blockers": blockers,
        "search_generation_status": _search_generation_status(search_generation_blockers),
        "real_search_generation_eligible": real_search_generation_eligible,
        "deployment_completion_candidate_source_ready": real_search_generation_eligible,
        "search_generation_blockers": search_generation_blockers,
        "final_release_universe_claim": policy.get("final_release_universe_claim") is True,
        "final_release_universe_eligible": (
            policy.get("final_release_universe_claim") is True
            and not blockers
        ),
        "freeze_inputs": {
            "release_subset_hash": subset.get("release_subset_hash"),
            "expected_release_subset_hash": binding_validation.get("expected_release_subset_hash"),
            "budget_hash": budget_payload.get("budget_hash"),
            "research_space_hash": research_payload.get("manifest_hash"),
            "selection_policy_hash": stable_json_hash(policy),
        },
        "provenance": {
            "predeclared_release_subset": True,
            "generated_parameterized_release_universe": (
                (subset.get("generation_provenance", {}) or {}).get(
                    "generation_mode"
                )
                == "bounded_compatible_cartesian_product"
            ),
            "all_candidates_classified_before_freeze": not illegal_candidate_ids,
            "candidate_ids_recomputed_from_identity": binding_validation["valid"],
            "post_hoc_top_k_or_fixed_list": bool(
                selection_kind in BANNED_COMPLETION_SUBSETS
                or policy.get("fixed_candidate_only") is True
            ),
            "workload_or_evidence_axes_in_identity_allowed": False,
        },
        "deterministic_replay": _deterministic_replay_metadata(
            artifact_name="freeze_gate_verdict.json",
            builder="build_freeze_gate_verdict",
            inputs={
                "release_subset_hash": subset.get("release_subset_hash"),
                "budget_hash": budget_payload.get("budget_hash"),
                "research_space_hash": research_payload.get("manifest_hash"),
                "selection_policy_hash": stable_json_hash(policy),
            },
        ),
        "hard_completion_rule_preserved": not blockers,
        "top_k_or_representative_completion_allowed": False,
        "claim_boundary": (
            "freeze gate only; the parameterized generator preserves identity "
            "freeze and search-control provenance, but deliverable_complete "
            "still requires downstream L4, QE, FPGA, and ASIC evidence-gate "
            "closure"
        ),
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
        "parameter_profile_manifest": build_parameter_profile_manifest(),
        "target_platform_space": build_target_platform_space(),
        "legality_constraints": build_legality_constraints_manifest(),
        "research_space_manifest": build_research_space_manifest(),
        "workload_architecture_prior_report": build_workload_architecture_prior_report(),
        "architecture_prior_seed_manifest": build_architecture_prior_seed_manifest(),
        "release_subset_manifest": release_subset,
        "candidate_generation_report": build_candidate_generation_report(
            release_subset
        ),
        "complete_dse_search_effectiveness_report": build_complete_dse_search_effectiveness_report(
            release_subset
        ),
        "legality_pruning_report": build_legality_pruning_report(
            release_subset
        ),
        "release_pruning_rationale_report": build_release_pruning_rationale_report(
            release_subset
        ),
        "schedule_legality_report": build_schedule_legality_report(),
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
    def _raw(name: str) -> Any:
        return search_space.get(name, {})

    def _mapping(name: str) -> Mapping[str, Any]:
        value = _raw(name)
        return value if isinstance(value, Mapping) else {}

    sidecar_object_fields = (
        "search_space_schema",
        "architecture_taxonomy",
        "hybrid_template_manifest",
        "algorithm_family_manifest",
        "mapping_layout_space",
        "compile_schedule_space",
        "runtime_schedule_space",
        "target_platform_space",
        "legality_constraints",
        "research_space_manifest",
        "workload_architecture_prior_report",
        "architecture_prior_seed_manifest",
        "release_subset_manifest",
        "candidate_generation_report",
        "complete_dse_search_effectiveness_report",
        "legality_pruning_report",
        "release_pruning_rationale_report",
        "schedule_legality_report",
        "release_cardinality_budget",
        "release_l4_runtime_cost_report",
        "freeze_gate_verdict",
    )
    shape_errors = [
        {
            "field": field,
            "message": "architecture search-space sidecar must be an object",
            "actual_type": type(_raw(field)).__name__,
        }
        for field in sidecar_object_fields
        if field in search_space and not isinstance(_raw(field), Mapping)
    ]

    subset = _raw("release_subset_manifest")
    freeze = _raw("freeze_gate_verdict")
    candidate_report = _raw("candidate_generation_report")
    effectiveness_report = _raw("complete_dse_search_effectiveness_report")
    subset_payload = _mapping("release_subset_manifest")
    freeze_payload = _mapping("freeze_gate_verdict")
    candidate_report_payload = _mapping("candidate_generation_report")
    effectiveness_report_payload = _mapping("complete_dse_search_effectiveness_report")
    release_subset_binding_validation = validate_release_subset_candidate_bindings(
        subset_payload
    )
    expected_candidate_report = build_candidate_generation_report(subset_payload)
    expected_effectiveness_report = build_complete_dse_search_effectiveness_report(
        subset_payload
    )
    budget_payload = _mapping("release_cardinality_budget")
    research_payload = _mapping("research_space_manifest")
    selection_policy = (
        freeze_payload.get("selection_policy")
        if isinstance(freeze_payload.get("selection_policy"), Mapping)
        else None
    )
    expected_freeze_gate = build_freeze_gate_verdict(
        subset_payload,
        selection_policy=selection_policy,
        budget=budget_payload or None,
        research_space=research_payload or None,
    )
    legality_pruning_report = _raw("legality_pruning_report")
    expected_legality_pruning_report = build_legality_pruning_report(
        subset_payload
    )
    release_pruning_report = _raw("release_pruning_rationale_report")
    expected_release_pruning_report = build_release_pruning_rationale_report(
        subset_payload
    )
    l4_report = _raw("release_l4_runtime_cost_report")
    l4_report_payload = _mapping("release_l4_runtime_cost_report")
    frozen_workload_case_count = DEFAULT_FROZEN_WORKLOAD_CASE_COUNT
    try:
        frozen_workload_case_count = int(
            l4_report_payload.get("frozen_workload_case_count")
            or DEFAULT_FROZEN_WORKLOAD_CASE_COUNT
        )
    except (TypeError, ValueError):
        frozen_workload_case_count = DEFAULT_FROZEN_WORKLOAD_CASE_COUNT
    expected_l4_report = build_release_l4_runtime_cost_report(
        subset_payload,
        frozen_workload_case_count=frozen_workload_case_count,
    )
    expected_foundation_artifacts = {
        "search_space_schema": build_search_space_schema(),
        "architecture_taxonomy": build_architecture_taxonomy_manifest(),
        "hybrid_template_manifest": build_hybrid_template_manifest(),
        "algorithm_family_manifest": build_algorithm_family_manifest(),
        "mapping_layout_space": build_mapping_layout_space(),
        "compile_schedule_space": build_compile_schedule_space(),
        "runtime_schedule_space": build_runtime_schedule_space(),
        "target_platform_space": build_target_platform_space(),
        "legality_constraints": build_legality_constraints_manifest(),
        "research_space_manifest": build_research_space_manifest(),
        "workload_architecture_prior_report": (
            build_workload_architecture_prior_report()
        ),
        "architecture_prior_seed_manifest": (
            build_architecture_prior_seed_manifest()
        ),
        "schedule_legality_report": build_schedule_legality_report(),
        "release_cardinality_budget": build_release_cardinality_budget(),
    }
    checks = {
        **{
            f"{artifact_name}_matches_builder": (
                _raw(artifact_name) == expected_payload
            )
            for artifact_name, expected_payload in expected_foundation_artifacts.items()
        },
        "has_two_tiers": set(
            _mapping("search_space_schema").get("tiers", {})
        )
        == {"research_space", "release_subset"},
        "candidate_generation_report_passed": candidate_report_payload.get("status")
        == "passed",
        "candidate_identity_complete": candidate_report_payload.get(
            "all_candidates_have_all_identity_layers"
        )
        is True,
        "release_subset_candidate_identity_binding_valid": release_subset_binding_validation[
            "valid"
        ]
        is True,
        "candidate_generation_report_matches_release_subset": (
            candidate_report == expected_candidate_report
        ),
        "search_effectiveness_report_passed": effectiveness_report_payload.get(
            "status"
        )
        == "passed",
        "search_effectiveness_report_matches_release_subset": (
            effectiveness_report == expected_effectiveness_report
        ),
        "legality_pruning_report_matches_release_subset": (
            legality_pruning_report == expected_legality_pruning_report
        ),
        "release_pruning_rationale_report_matches_release_subset": (
            release_pruning_report == expected_release_pruning_report
        ),
        "release_l4_runtime_cost_report_matches_release_subset": (
            l4_report == expected_l4_report
        ),
        "freeze_gate_verdict_matches_release_subset": (
            freeze == expected_freeze_gate
        ),
        "search_space_hash_matches_content": (
            search_space.get("search_space_hash")
            == _stable_hash_without(search_space, "search_space_hash")
        ),
        "required_taxonomy_present": not _missing_required_taxonomy_ids(
            subset_payload
        ),
        "freeze_gate_passed": freeze_payload.get("status") == "passed",
        "workload_prior_report_passed": _mapping(
            "workload_architecture_prior_report"
        ).get("status")
        == "passed",
        "schedule_legality_report_passed": _mapping(
            "schedule_legality_report"
        ).get("status")
        == "passed",
        "no_completion_claim": search_space.get("claim_boundary", "").endswith(
            "no trusted speedup or completion claim"
        ),
    }
    payload = {
        "schema_version": "dse.codesign.complete_dse.validation.v1",
        "status": (
            "passed" if all(checks.values()) and not shape_errors else "failed"
        ),
        "checks": checks,
        "shape_errors": shape_errors,
        "search_space_hash": search_space.get("search_space_hash"),
        "release_subset_candidate_binding_validation": release_subset_binding_validation,
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
        "parameter_profile_manifest.json": search_space[
            "parameter_profile_manifest"
        ],
        "target_platform_space.json": search_space["target_platform_space"],
        "legality_constraints.json": search_space["legality_constraints"],
        "research_space_manifest.json": search_space[
            "research_space_manifest"
        ],
        "workload_architecture_prior_report.json": search_space[
            "workload_architecture_prior_report"
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
        "complete_dse_search_effectiveness_report.json": search_space[
            "complete_dse_search_effectiveness_report"
        ],
        "legality_pruning_report.json": search_space[
            "legality_pruning_report"
        ],
        "release_pruning_rationale_report.json": search_space[
            "release_pruning_rationale_report"
        ],
        "schedule_legality_report.json": search_space[
            "schedule_legality_report"
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
