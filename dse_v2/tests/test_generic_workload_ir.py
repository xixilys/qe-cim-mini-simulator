#!/usr/bin/env python3
"""Regression coverage for domain-neutral WorkloadPackage and ComputeGraph IR."""

from __future__ import annotations

import pytest

from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode, DataEdge, GraphRegion, TensorSpec
from dse_v2.core.workload import WorkloadPackage, create_tensor_chain_graph, lower_compute_graph, package_from_graph


def test_workload_package_round_trip_for_non_qe_graph():
    graph = create_tensor_chain_graph("ml_graph")
    package = package_from_graph(
        graph,
        workload_id="ml_tensor_1",
        workload_family="ml_tensor",
        importer_id="generic_json",
        domain_metadata={"batch_size": 32},
    )

    validation = package.validate()
    restored = WorkloadPackage.from_dict(package.to_dict())

    assert validation["valid"] is True
    assert restored.workload_id == "ml_tensor_1"
    assert restored.workload_family == "ml_tensor"
    assert restored.importer_id == "generic_json"
    assert restored.domain_metadata == {"batch_size": 32}
    assert "npw" not in restored.to_dict()
    assert "h_psi" not in restored.graph.nodes


def test_compute_graph_accepts_unknown_operator_and_control_state_edges():
    graph = ComputeGraph(graph_id="custom_control")
    graph.add_node(ComputeNode("source", "custom_source", outputs=["x"]))
    graph.add_node(ComputeNode("branch", "if_then_else", inputs=["x"], outputs=["y"]))
    graph.add_node(ComputeNode("state", "state_update", inputs=["y"], outputs=["s"]))
    graph.add_edge(DataEdge("source", "branch", edge_kind="control", attributes={"predicate": "x > 0"}))
    graph.add_edge(DataEdge("branch", "state", edge_kind="state", attributes={"state_name": "accumulator"}))

    report = graph.validate()
    order = graph.topological_sort()

    assert report["valid"] is True
    assert order == ["source", "branch", "state"]
    assert graph.to_dict()["edges"][0]["edge_kind"] == "control"


def test_unannotated_cycle_is_rejected_but_declared_feedback_lowers():
    bad = ComputeGraph("bad_cycle")
    bad.add_node(ComputeNode("a", "op"))
    bad.add_node(ComputeNode("b", "op"))
    bad.add_edge(DataEdge("a", "b", edge_kind="data", tensor_name="x"))
    bad.add_edge(DataEdge("b", "a", edge_kind="data", tensor_name="y"))

    assert bad.validate()["valid"] is False
    with pytest.raises(ValueError):
        bad.topological_sort()

    good = ComputeGraph("declared_feedback")
    good.add_node(ComputeNode("produce", "stencil_step", outputs=["next"]));
    good.add_node(ComputeNode("consume", "residual_check", inputs=["next"]))
    good.add_edge(DataEdge("produce", "consume", "next", TensorSpec((64, 64), dtype="FP32")))
    good.add_edge(DataEdge(
        "consume",
        "produce",
        edge_kind="feedback",
        attributes={"loop": True, "iterations": 4},
        cycle_semantics={"kind": "bounded_loop", "iterations": 4},
    ))
    good.add_region(GraphRegion(
        region_id="iter_region",
        region_type="loop",
        node_ids=["produce", "consume"],
        semantics={"iterations": 4},
    ))

    validation = good.validate()
    package = package_from_graph(good, workload_family="stencil", importer_id="generic_json")
    lowering = lower_compute_graph(good, package)

    assert validation["valid"] is True
    assert lowering.report["status"] == "lowered"
    assert lowering.report["full_workload_eligible"] is True
    assert lowering.report["removed_or_summarized_edges"]
    assert lowering.executable_graph is not None
    assert lowering.executable_graph.topological_sort() == ["produce", "consume"]


def test_unsupported_dynamic_region_blocks_lowering():
    graph = ComputeGraph("dynamic_recursion")
    graph.add_node(ComputeNode("recur", "recursive_solver"))
    graph.add_region(GraphRegion(
        region_id="recursion",
        region_type="dynamic_recursion",
        node_ids=["recur"],
        semantics={},
    ))
    package = package_from_graph(graph, workload_family="custom", importer_id="generic_json")

    lowering = lower_compute_graph(graph, package)

    assert graph.validate()["valid"] is True
    assert lowering.report["status"] == "unsupported"
    assert lowering.report["unsupported_constructs"]
    assert lowering.executable_graph is None
