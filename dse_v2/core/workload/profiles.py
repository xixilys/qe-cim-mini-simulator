#!/usr/bin/env python3
"""Declarative workload profiles for domain-neutral DSE ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional


FULL_CLAIM_BOUNDARIES = {"full_workload", "full", "end_to_end"}
DIAGNOSTIC_CLAIM_BOUNDARIES = {"reduced", "synthetic", "trace_only", "diagnostic", "diagnostic-only", "smoke", "smoke-only"}


@dataclass(frozen=True)
class WorkloadProfile:
    """Declarative contract for one workload family/profile.

    Profiles own policy and wording.  Importers own source parsing.  Core DSE
    stages consume these fields generically and must not special-case one
    workload family.
    """

    profile_id: str
    profile_version: str
    workload_family: str
    accepted_source_kinds: List[str]
    graph_pattern: str
    lowering_policy: str
    default_mapping_policies: List[str]
    domain_validation: Dict[str, Any]
    default_claim_boundary: str = "full_workload"
    required_coverage: List[str] = field(default_factory=list)
    mapping_preferences: Dict[str, List[str]] = field(default_factory=dict)
    unsupported_constructs: List[str] = field(default_factory=list)
    unavailable_metric_labels: List[str] = field(default_factory=list)
    description: str = ""
    plugin_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def accepted_sources(self) -> List[str]:
        return list(self.accepted_source_kinds)

    @property
    def final_claim_boundary(self) -> str:
        return self.default_claim_boundary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "dse.workload_profile.v1",
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "workload_family": self.workload_family,
            "accepted_source_kinds": list(self.accepted_source_kinds),
            "accepted_sources": list(self.accepted_source_kinds),
            "graph_pattern": self.graph_pattern,
            "lowering_policy": self.lowering_policy,
            "default_mapping_policies": list(self.default_mapping_policies),
            "mapping_preferences": {key: list(value) for key, value in self.mapping_preferences.items()},
            "domain_validation": dict(self.domain_validation),
            "default_claim_boundary": self.default_claim_boundary,
            "final_claim_boundary": self.default_claim_boundary,
            "required_coverage": list(self.required_coverage),
            "unsupported_constructs": list(self.unsupported_constructs),
            "unavailable_metric_labels": list(self.unavailable_metric_labels),
            "description": self.description,
            "plugin_metadata": dict(self.plugin_metadata),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "WorkloadProfile":
        profile_id = str(data.get("profile_id", data.get("workload_family", "dynamic_custom")))
        accepted = data.get("accepted_source_kinds", data.get("accepted_sources", []))
        return WorkloadProfile(
            profile_id=profile_id,
            profile_version=str(data.get("profile_version", "v1")),
            workload_family=str(data.get("workload_family", profile_id)),
            accepted_source_kinds=[str(item) for item in accepted or []],
            graph_pattern=str(data.get("graph_pattern", "custom")),
            lowering_policy=str(data.get("lowering_policy", "identity_dag")),
            default_mapping_policies=[str(item) for item in data.get("default_mapping_policies", []) or []],
            mapping_preferences={
                str(key): [str(item) for item in value or []]
                for key, value in dict(data.get("mapping_preferences", {}) or {}).items()
            },
            domain_validation=dict(data.get("domain_validation", {}) or {}),
            default_claim_boundary=str(data.get("default_claim_boundary", data.get("final_claim_boundary", "full_workload"))),
            required_coverage=[str(item) for item in data.get("required_coverage", []) or []],
            unsupported_constructs=[str(item) for item in data.get("unsupported_constructs", []) or []],
            unavailable_metric_labels=[str(item) for item in data.get("unavailable_metric_labels", []) or []],
            description=str(data.get("description", "")),
            plugin_metadata=dict(data.get("plugin_metadata", {}) or {}),
        )


@dataclass
class ProfileRegistry:
    profiles: Dict[str, WorkloadProfile] = field(default_factory=dict)
    aliases: Dict[str, str] = field(default_factory=dict)

    def register(self, profile: WorkloadProfile, aliases: Optional[Iterable[str]] = None) -> "ProfileRegistry":
        self.profiles[profile.profile_id] = profile
        self.aliases[profile.profile_id] = profile.profile_id
        self.aliases[profile.workload_family] = profile.profile_id
        for alias in aliases or []:
            self.aliases[str(alias)] = profile.profile_id
        return self

    def get(self, profile_id: str) -> WorkloadProfile:
        key = self.aliases.get(str(profile_id), str(profile_id))
        if key not in self.profiles:
            raise KeyError(f"unknown workload profile: {profile_id}")
        return self.profiles[key]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "dse.workload_profile_registry.v1",
            "profiles": [profile.to_dict() for profile in self.profiles.values()],
            "aliases": dict(self.aliases),
        }


DEFAULT_WORKLOAD_PROFILES: Dict[str, WorkloadProfile] = {
    "ml_tensor": WorkloadProfile(
        profile_id="ml_tensor",
        profile_version="v1",
        workload_family="ml_tensor",
        accepted_source_kinds=["onnx_like", "framework_export", "hand_authored", "generic_json", "generated"],
        graph_pattern="dag_or_bounded_dynamic_axes",
        lowering_policy="identity_dag_or_summarize_bounded_dynamic_axes",
        default_mapping_policies=["host-baseline", "gpu-tensor", "fpga-systolic", "cim-eligible", "memory-placement"],
        mapping_preferences={
            "placeholder": ["host"],
            "gemm": ["gpu", "fpga", "cim", "host"],
            "batched_gemm": ["gpu", "fpga", "host"],
            "conv2d": ["gpu", "fpga", "host"],
            "attention": ["gpu", "fpga", "host"],
            "softmax": ["gpu", "host"],
            "relu": ["gpu", "cim", "fpga", "host"],
            "elementwise": ["gpu", "cim", "fpga", "host"],
        },
        domain_validation={
            "timing_only_allowed": True,
            "correctness_artifacts": ["profile_model_output_reference.json", "profile_accuracy_report.json"],
            "correctness_claim_requires_profile_evidence": True,
            "unclaimed_domain_correctness": "ML accuracy/model-output equivalence is not inferred from generic timing evidence.",
        },
        unavailable_metric_labels=["ml_accuracy", "model_output_equivalence"],
        description="Tensor graph workflow for ML-style operators and pipelines.",
    ),
    "sparse_la": WorkloadProfile(
        profile_id="sparse_la",
        profile_version="v1",
        workload_family="sparse_la",
        accepted_source_kinds=["matrix_market", "csr", "csc", "coo", "block_sparse", "solver_trace", "generic_json", "generated"],
        graph_pattern="dag_or_bounded_solver_loop",
        lowering_policy="identity_dag_or_summarize_bounded_solver_loop",
        default_mapping_policies=["host-baseline", "fpga-sparse-pipeline", "memory-rich", "near-memory-reduction"],
        mapping_preferences={
            "dma_load": ["fpga", "gpu", "host"],
            "spmv": ["fpga", "gpu", "host"],
            "sparse_matvec": ["fpga", "gpu", "host"],
            "gather": ["fpga", "host"],
            "scatter": ["fpga", "host"],
            "reduction": ["fpga", "gpu", "cim", "host"],
            "preconditioner": ["fpga", "gpu", "host"],
        },
        domain_validation={
            "timing_only_allowed": True,
            "correctness_artifacts": ["profile_sparse_residual_report.json", "profile_reference_vector.json"],
            "correctness_claim_requires_profile_evidence": True,
            "unclaimed_domain_correctness": "Sparse residual convergence/reference-vector equivalence is not inferred from generic timing evidence.",
        },
        unavailable_metric_labels=["sparse_residual", "solver_convergence"],
        description="Sparse matrix/vector and iterative sparse solver workflow.",
    ),
    "stencil_streaming": WorkloadProfile(
        profile_id="stencil_streaming",
        profile_version="v1",
        workload_family="stencil_streaming",
        accepted_source_kinds=["stencil_dsl", "structured_grid", "fft_pipeline", "signal_pipeline", "generic_json", "generated"],
        graph_pattern="bounded_loop_or_streaming_feedback",
        lowering_policy="unroll_or_summarize_or_backend_native_streaming",
        default_mapping_policies=["host-baseline", "fpga-streaming", "hbm-tile-buffer", "overlap-dma-compute", "low-power"],
        mapping_preferences={
            "dma_load": ["fpga", "host"],
            "stencil": ["fpga", "gpu", "host"],
            "fft": ["fpga", "gpu", "host"],
            "residual_check": ["fpga", "gpu", "host"],
            "elementwise": ["fpga", "gpu", "cim", "host"],
            "reduction": ["fpga", "gpu", "cim", "host"],
        },
        domain_validation={
            "timing_only_allowed": True,
            "correctness_artifacts": ["profile_stencil_error_norms.json", "profile_signal_reference.json"],
            "correctness_claim_requires_profile_evidence": True,
            "unclaimed_domain_correctness": "PDE/signal numerical equivalence is not inferred from generic timing evidence.",
        },
        unavailable_metric_labels=["stencil_error_norm", "conservation_check", "signal_equivalence"],
        description="Stencil, FFT/signal, and streaming producer-consumer workflow.",
    ),
    "graph_analytics": WorkloadProfile(
        profile_id="graph_analytics",
        profile_version="v1",
        workload_family="graph_analytics",
        accepted_source_kinds=["graph_format", "algorithm_config", "traversal_trace", "gnn_message_passing", "generic_json", "generated"],
        graph_pattern="frontier_loop_or_message_passing_region",
        lowering_policy="summarize_iteration_or_trace_distribution",
        default_mapping_policies=["host-baseline", "memory-rich", "fpga-frontier", "near-memory-reduction"],
        mapping_preferences={
            "dma_load": ["fpga", "host"],
            "frontier_expand": ["fpga", "gpu", "host"],
            "message_passing": ["gpu", "fpga", "host"],
            "reduction": ["fpga", "gpu", "cim", "host"],
            "scatter": ["fpga", "host"],
            "gather": ["fpga", "host"],
        },
        domain_validation={
            "timing_only_allowed": True,
            "correctness_artifacts": ["profile_graph_result_validation.json", "profile_convergence_report.json"],
            "correctness_claim_requires_profile_evidence": True,
            "unclaimed_domain_correctness": "Traversal/ranking/convergence quality is not inferred from generic timing evidence.",
        },
        unavailable_metric_labels=["graph_result_equivalence", "graph_convergence"],
        description="Graph traversal, ranking, connected-component, SSSP, and message-passing workflow.",
    ),
    "database_vector_search": WorkloadProfile(
        profile_id="database_vector_search",
        profile_version="v1",
        workload_family="database_vector_search",
        accepted_source_kinds=["query_plan", "vector_index", "relational_pipeline", "synthetic_benchmark", "generic_json", "generated"],
        graph_pattern="query_pipeline_dag_or_bounded_iterative_search",
        lowering_policy="identity_dag_or_summarize_bounded_search",
        default_mapping_policies=["host-baseline", "gpu-distance", "fpga-filter-topk", "memory-rich-index-resident"],
        mapping_preferences={
            "index_scan": ["fpga", "host"],
            "distance_compute": ["gpu", "fpga", "host"],
            "topk": ["fpga", "gpu", "host"],
            "predicate_filter": ["fpga", "host"],
            "aggregation": ["fpga", "gpu", "host"],
            "join": ["fpga", "gpu", "host"],
        },
        domain_validation={
            "timing_only_allowed": True,
            "correctness_artifacts": ["profile_query_equivalence.json", "profile_recall_precision.json"],
            "correctness_claim_requires_profile_evidence": True,
            "unclaimed_domain_correctness": "Query equivalence/recall/precision is not inferred from generic timing evidence.",
        },
        unavailable_metric_labels=["query_equivalence", "recall", "precision", "transaction_semantics"],
        description="Database query pipeline and vector-search workflow.",
    ),
    "dynamic_custom": WorkloadProfile(
        profile_id="dynamic_custom",
        profile_version="v1",
        workload_family="dynamic_custom",
        accepted_source_kinds=["custom_json", "python_export", "dsl_export", "trace_summary", "hand_authored", "generated"],
        graph_pattern="custom_with_declared_bounds_or_summary",
        lowering_policy="identity_unroll_summarize_or_unsupported",
        default_mapping_policies=["host-baseline", "capability-greedy", "profile-declared"],
        mapping_preferences={
            "state_update": ["host", "fpga"],
            "data_dependent_branch": ["host", "fpga"],
            "custom": ["fpga", "host"],
            "elementwise": ["gpu", "cim", "fpga", "host"],
        },
        domain_validation={
            "timing_only_allowed": True,
            "correctness_artifacts": ["profile_custom_validation.json"],
            "correctness_claim_requires_profile_evidence": True,
            "unclaimed_domain_correctness": "Custom domain correctness is unavailable unless supplied by the profile/importer.",
        },
        unsupported_constructs=["unbounded_recursion", "unbounded_data_dependent_iteration", "undeclared_side_effect_state"],
        unavailable_metric_labels=["custom_domain_correctness"],
        description="Fallback profile for user-defined scientific graphs and dynamic-control workloads.",
    ),
}

FAMILY_ALIASES = {
    "custom": "dynamic_custom",
    "user_defined": "dynamic_custom",
    "stencil": "stencil_streaming",
    "streaming": "stencil_streaming",
    "database_pipeline": "database_vector_search",
    "vector_search": "database_vector_search",
    "ml": "ml_tensor",
}


def default_profile_registry() -> ProfileRegistry:
    registry = ProfileRegistry(aliases=dict(FAMILY_ALIASES))
    for profile in DEFAULT_WORKLOAD_PROFILES.values():
        registry.register(profile)
    return registry


def canonical_workload_family(workload_family: str) -> str:
    family = str(workload_family or "dynamic_custom")
    return FAMILY_ALIASES.get(family, family)


def get_workload_profile(profile_id: str) -> WorkloadProfile:
    registry = default_profile_registry()
    try:
        return registry.get(profile_id)
    except KeyError:
        return registry.get("dynamic_custom")


def default_profile_dict() -> Dict[str, Dict[str, Any]]:
    return {profile_id: profile.to_dict() for profile_id, profile in DEFAULT_WORKLOAD_PROFILES.items()}


def resolve_profile_metadata(profile_id: str, override: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    base = get_workload_profile(profile_id).to_dict()
    for key, value in dict(override or {}).items():
        if key == "domain_validation" and isinstance(value, Mapping):
            merged = dict(base.get("domain_validation", {}))
            merged.update(dict(value))
            base[key] = merged
        elif key in {
            "accepted_sources",
            "accepted_source_kinds",
            "default_mapping_policies",
            "required_coverage",
            "unsupported_constructs",
            "unavailable_metric_labels",
        }:
            values = [str(item) for item in value or []]
            base[key] = values
            if key == "accepted_sources":
                base["accepted_source_kinds"] = values
            elif key == "accepted_source_kinds":
                base["accepted_sources"] = values
        elif key == "mapping_preferences" and isinstance(value, Mapping):
            base[key] = {str(k): [str(item) for item in v or []] for k, v in value.items()}
        else:
            base[key] = value
    base["profile_id"] = str(base.get("profile_id", profile_id))
    base["workload_family"] = canonical_workload_family(str(base.get("workload_family", profile_id)))
    return base


def required_coverage_from_profile(
    profile_id: str,
    profile: Optional[Mapping[str, Any]],
    graph_nodes: Iterable[str],
    topological_order: Optional[Iterable[str]] = None,
) -> List[str]:
    metadata = resolve_profile_metadata(profile_id, profile)
    explicit = [str(item) for item in metadata.get("required_coverage", []) or []]
    if explicit:
        return explicit
    order = list(topological_order or [])
    if order:
        return [str(node_id) for node_id in order]
    return sorted(str(node_id) for node_id in graph_nodes)
