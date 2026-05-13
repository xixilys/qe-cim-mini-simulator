#!/usr/bin/env python3
"""Generic workload graph fixtures for profile/importer-driven DSE tests."""

from __future__ import annotations

from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode, DataEdge, GraphRegion, TensorSpec
from dse_v2.core.workload.importers import (
    GenericJsonImporter,
    ImporterRegistry,
    WorkloadImporter,
    default_importer_registry,
)

def create_tensor_chain_graph(graph_id: str = "ml_tensor_chain") -> ComputeGraph:
    graph = ComputeGraph(graph_id=graph_id, metadata={"workload_family": "ml_tensor", "importer_id": "generic_json"})
    graph.add_node(ComputeNode(
        node_id="input",
        op_type="placeholder",
        outputs=["x"],
        output_specs={"x": TensorSpec(shape=(32, 128), dtype="FP32")},
    ))
    graph.add_node(ComputeNode(
        node_id="linear",
        op_type="gemm",
        inputs=["x", "w"],
        outputs=["y"],
        input_specs={"x": TensorSpec(shape=(32, 128), dtype="FP32"), "w": TensorSpec(shape=(128, 64), dtype="FP32")},
        output_specs={"y": TensorSpec(shape=(32, 64), dtype="FP32")},
        estimated_flops=2.0 * 32 * 128 * 64,
        estimated_memory_bytes=(32 * 128 + 128 * 64 + 32 * 64) * 4,
    ))
    graph.add_node(ComputeNode(
        node_id="activation",
        op_type="relu",
        inputs=["y"],
        outputs=["z"],
        input_specs={"y": TensorSpec(shape=(32, 64), dtype="FP32")},
        output_specs={"z": TensorSpec(shape=(32, 64), dtype="FP32")},
        estimated_flops=32 * 64,
        estimated_memory_bytes=32 * 64 * 4 * 2,
    ))
    graph.add_edge(DataEdge("input", "linear", "x", TensorSpec(shape=(32, 128), dtype="FP32")))
    graph.add_edge(DataEdge("linear", "activation", "y", TensorSpec(shape=(32, 64), dtype="FP32")))
    return graph


def create_sparse_spmv_graph(graph_id: str = "sparse_spmv_pipeline") -> ComputeGraph:
    graph = ComputeGraph(graph_id=graph_id, metadata={"workload_family": "sparse_la", "importer_id": "generic_json"})
    graph.add_node(ComputeNode(
        "load_csr",
        "dma_load",
        outputs=["csr"],
        output_specs={"csr": TensorSpec(shape=(4096, 16), dtype="FP32")},
        estimated_memory_bytes=4096 * 16 * 4,
        attributes={"sparse_format": "csr", "nnz_per_row_hint": 16},
    ))
    graph.add_node(ComputeNode(
        "spmv",
        "spmv",
        inputs=["csr", "x"],
        outputs=["y"],
        input_specs={"csr": TensorSpec(shape=(4096, 16), dtype="FP32"), "x": TensorSpec(shape=(4096,), dtype="FP32")},
        output_specs={"y": TensorSpec(shape=(4096,), dtype="FP32")},
        estimated_flops=2.0 * 4096 * 16,
        estimated_memory_bytes=(4096 * 16 + 4096 + 4096) * 4,
        attributes={"sparse_format": "csr"},
    ))
    graph.add_node(ComputeNode(
        "norm",
        "reduction",
        inputs=["y"],
        outputs=["residual_norm"],
        input_specs={"y": TensorSpec(shape=(4096,), dtype="FP32")},
        output_specs={"residual_norm": TensorSpec(shape=(1,), dtype="FP32")},
        estimated_flops=4096,
        estimated_memory_bytes=4096 * 4,
        attributes={"domain_metric": "residual_norm_unclaimed_without_profile_validator"},
    ))
    graph.add_edge(DataEdge("load_csr", "spmv", "csr", TensorSpec(shape=(4096, 16), dtype="FP32")))
    graph.add_edge(DataEdge("spmv", "norm", "y", TensorSpec(shape=(4096,), dtype="FP32")))
    return graph


def create_stencil_streaming_graph(graph_id: str = "stencil_streaming_pipeline") -> ComputeGraph:
    graph = ComputeGraph(graph_id=graph_id, metadata={"workload_family": "stencil_streaming", "importer_id": "generic_json"})
    graph.add_node(ComputeNode(
        "load_tile",
        "dma_load",
        outputs=["tile"],
        output_specs={"tile": TensorSpec(shape=(64, 64), dtype="FP32")},
        estimated_memory_bytes=64 * 64 * 4,
        attributes={"tile_shape": [64, 64], "halo_depth": 1},
    ))
    graph.add_node(ComputeNode(
        "stencil_step",
        "stencil",
        inputs=["tile"],
        outputs=["tile_next"],
        input_specs={"tile": TensorSpec(shape=(64, 64), dtype="FP32")},
        output_specs={"tile_next": TensorSpec(shape=(64, 64), dtype="FP32")},
        estimated_flops=64 * 64 * 13,
        estimated_memory_bytes=64 * 64 * 4 * 2,
        attributes={"stencil_points": 5, "halo_depth": 1},
    ))
    graph.add_node(ComputeNode(
        "residual",
        "residual_check",
        inputs=["tile_next"],
        outputs=["residual"],
        input_specs={"tile_next": TensorSpec(shape=(64, 64), dtype="FP32")},
        output_specs={"residual": TensorSpec(shape=(1,), dtype="FP32")},
        estimated_flops=64 * 64,
        estimated_memory_bytes=64 * 64 * 4,
    ))
    graph.add_edge(DataEdge("load_tile", "stencil_step", "tile", TensorSpec(shape=(64, 64), dtype="FP32")))
    graph.add_edge(DataEdge("stencil_step", "residual", "tile_next", TensorSpec(shape=(64, 64), dtype="FP32")))
    graph.add_edge(DataEdge(
        "residual",
        "stencil_step",
        edge_kind="stream",
        attributes={"streaming": True, "bounded": True},
        cycle_semantics={"kind": "streaming_recurrence", "iterations": 8},
    ))
    graph.add_region(GraphRegion(
        region_id="time_loop",
        region_type="streaming",
        node_ids=["stencil_step", "residual"],
        semantics={"iterations": 8, "summary_model": "per_iteration_timing"},
    ))
    return graph


def create_graph_analytics_graph(graph_id: str = "graph_analytics_frontier") -> ComputeGraph:
    graph = ComputeGraph(graph_id=graph_id, metadata={"workload_family": "graph_analytics", "importer_id": "generic_json"})
    graph.add_node(ComputeNode("load_frontier", "dma_load", outputs=["frontier"], estimated_memory_bytes=1 << 20, attributes={"graph_format": "csr"}))
    graph.add_node(ComputeNode("expand_edges", "frontier_expand", inputs=["frontier"], outputs=["messages"], estimated_flops=2.0e6, estimated_memory_bytes=8.0e6))
    graph.add_node(ComputeNode("reduce_updates", "reduction", inputs=["messages"], outputs=["next_frontier"], estimated_flops=1.0e6, estimated_memory_bytes=4.0e6))
    graph.add_edge(DataEdge("load_frontier", "expand_edges", "frontier", TensorSpec(shape=(262144,), dtype="INT32")))
    graph.add_edge(DataEdge("expand_edges", "reduce_updates", "messages", TensorSpec(shape=(1048576,), dtype="INT32")))
    graph.add_region(GraphRegion(
        region_id="frontier_iteration",
        region_type="loop",
        node_ids=["expand_edges", "reduce_updates"],
        semantics={"max_iterations": 16, "trace_trip_count": 8, "summary_model": "frontier_iteration_distribution"},
    ))
    return graph


def create_vector_search_graph(graph_id: str = "vector_search_pipeline") -> ComputeGraph:
    graph = ComputeGraph(graph_id=graph_id, metadata={"workload_family": "database_vector_search", "importer_id": "generic_json"})
    graph.add_node(ComputeNode("scan_index", "index_scan", outputs=["candidates"], estimated_flops=1.0e6, estimated_memory_bytes=16.0e6, attributes={"index_type": "ivf_flat"}))
    graph.add_node(ComputeNode("distance", "distance_compute", inputs=["candidates", "query"], outputs=["scores"], estimated_flops=2.0e6, estimated_memory_bytes=8.0e6))
    graph.add_node(ComputeNode("topk", "topk", inputs=["scores"], outputs=["neighbors"], estimated_flops=2.0e5, estimated_memory_bytes=2.0e6))
    graph.add_node(ComputeNode("filter", "predicate_filter", inputs=["neighbors"], outputs=["result"], estimated_flops=1.0e5, estimated_memory_bytes=1.0e6, attributes={"selectivity_hint": 0.25}))
    graph.add_edge(DataEdge("scan_index", "distance", "candidates", TensorSpec(shape=(4096, 128), dtype="FP32")))
    graph.add_edge(DataEdge("distance", "topk", "scores", TensorSpec(shape=(4096,), dtype="FP32")))
    graph.add_edge(DataEdge("topk", "filter", "neighbors", TensorSpec(shape=(64,), dtype="INT32")))
    return graph


def create_dynamic_custom_graph(graph_id: str = "dynamic_custom_graph", *, supported: bool = False) -> ComputeGraph:
    graph = ComputeGraph(graph_id=graph_id, metadata={"workload_family": "dynamic_custom", "importer_id": "generic_json"})
    graph.add_node(ComputeNode("state", "state_update", outputs=["state"], estimated_flops=1024, estimated_memory_bytes=4096))
    graph.add_node(ComputeNode("branch", "data_dependent_branch", inputs=["state"], outputs=["next"], estimated_flops=2048, estimated_memory_bytes=4096))
    graph.add_edge(DataEdge("state", "branch", edge_kind="control", attributes={"predicate": "profile_or_importer_defined"}))
    semantics = {"max_iterations": 4, "summary_model": "profile_or_importer_supplied"} if supported else {}
    graph.add_region(GraphRegion(
        region_id="dynamic_region",
        region_type="dynamic_control",
        node_ids=["state", "branch"],
        semantics=semantics,
    ))
    return graph
