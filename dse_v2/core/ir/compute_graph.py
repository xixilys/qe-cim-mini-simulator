#!/usr/bin/env python3
"""Level 3 Compute Graph IR: domain-neutral workload graph.

The graph is intentionally not QE-specific and not DAG-only.  It can carry
ordinary dataflow DAGs, hierarchical regions, declared loop/feedback edges,
streaming/state/control dependencies, and opaque adapter metadata.  Execution
backends consume a lowered executable view produced by the workload lowering
layer when a source graph contains non-DAG semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple


KNOWN_DTYPE_WIDTHS = {
    "FP64": 8,
    "FP32": 4,
    "FP16": 2,
    "BF16": 2,
    "INT64": 8,
    "INT32": 4,
    "INT16": 2,
    "INT8": 1,
    "BOOL": 1,
    "COMPLEX_FP64": 16,
    "COMPLEX_FP32": 8,
}

CYCLE_DECLARING_EDGE_KINDS = {"feedback", "stream", "streaming", "state"}
NON_EXECUTABLE_EDGE_KINDS = {"metadata"}


@dataclass
class TensorSpec:
    """Tensor specification with explicit units and optional custom dtype width."""

    shape: Tuple[int, ...]
    dtype: str = "FP64"
    layout: str = "row_major"
    byte_width: Optional[int] = None

    def num_elements(self) -> int:
        result = 1
        for dim in self.shape:
            result *= max(1, int(dim))
        return result

    def element_size_bytes(self) -> int:
        if self.dtype in KNOWN_DTYPE_WIDTHS:
            return KNOWN_DTYPE_WIDTHS[self.dtype]
        if self.byte_width is not None and self.byte_width > 0:
            return int(self.byte_width)
        raise ValueError(f"unsupported dtype without explicit byte_width: {self.dtype}")

    def size_bytes(self) -> int:
        return self.num_elements() * self.element_size_bytes()

    def validate(self, prefix: str = "tensor") -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        if any(int(dim) <= 0 for dim in self.shape):
            issues.append({
                "object_type": "TensorSpec",
                "object_id": prefix,
                "field": "shape",
                "severity": "error",
                "message": "tensor dimensions must be positive integers",
            })
        if self.dtype not in KNOWN_DTYPE_WIDTHS and not (self.byte_width and self.byte_width > 0):
            issues.append({
                "object_type": "TensorSpec",
                "object_id": prefix,
                "field": "dtype",
                "severity": "error",
                "message": "unknown dtype requires explicit byte_width",
            })
        return issues

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "shape": list(self.shape),
            "dtype": self.dtype,
            "layout": self.layout,
            "num_elements": self.num_elements(),
        }
        if self.byte_width is not None:
            data["byte_width"] = self.byte_width
        try:
            data["size_bytes"] = self.size_bytes()
        except ValueError:
            data["size_bytes"] = None
            data["size_unavailable_reason"] = "unknown dtype without explicit byte_width"
        return data

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> TensorSpec:
        return TensorSpec(
            shape=tuple(int(dim) for dim in data.get("shape", ())),
            dtype=str(data.get("dtype", "FP64")),
            layout=str(data.get("layout", "row_major")),
            byte_width=data.get("byte_width"),
        )


@dataclass
class ComputeNode:
    """A generic compute/control/state operation in the workload graph."""

    node_id: str
    op_type: str
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    input_specs: Dict[str, TensorSpec] = field(default_factory=dict)
    output_specs: Dict[str, TensorSpec] = field(default_factory=dict)
    estimated_flops: float = 0.0
    estimated_memory_bytes: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        if not self.node_id:
            issues.append({"object_type": "ComputeNode", "object_id": self.node_id, "field": "node_id", "severity": "error", "message": "node_id is required"})
        if not self.op_type:
            issues.append({"object_type": "ComputeNode", "object_id": self.node_id, "field": "op_type", "severity": "error", "message": "op_type is required"})
        for name, spec in self.input_specs.items():
            issues.extend(spec.validate(prefix=f"{self.node_id}.input_specs.{name}"))
        for name, spec in self.output_specs.items():
            issues.extend(spec.validate(prefix=f"{self.node_id}.output_specs.{name}"))
        if self.estimated_flops < 0:
            issues.append({"object_type": "ComputeNode", "object_id": self.node_id, "field": "estimated_flops", "severity": "error", "message": "estimated_flops must be non-negative"})
        if self.estimated_memory_bytes < 0:
            issues.append({"object_type": "ComputeNode", "object_id": self.node_id, "field": "estimated_memory_bytes", "severity": "error", "message": "estimated_memory_bytes must be non-negative"})
        return issues

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "op_type": self.op_type,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "input_specs": {k: v.to_dict() for k, v in self.input_specs.items()},
            "output_specs": {k: v.to_dict() for k, v in self.output_specs.items()},
            "estimated_flops": self.estimated_flops,
            "estimated_memory_bytes": self.estimated_memory_bytes,
            "attributes": dict(self.attributes),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> ComputeNode:
        return ComputeNode(
            node_id=str(data.get("node_id", "")),
            op_type=str(data.get("op_type", "")),
            inputs=[str(item) for item in data.get("inputs", []) or []],
            outputs=[str(item) for item in data.get("outputs", []) or []],
            input_specs={str(k): TensorSpec.from_dict(v) for k, v in (data.get("input_specs", {}) or {}).items()},
            output_specs={str(k): TensorSpec.from_dict(v) for k, v in (data.get("output_specs", {}) or {}).items()},
            estimated_flops=float(data.get("estimated_flops", 0.0) or 0.0),
            estimated_memory_bytes=float(data.get("estimated_memory_bytes", 0.0) or 0.0),
            attributes=dict(data.get("attributes", {}) or {}),
        )


@dataclass
class DataEdge:
    """Typed dependency edge between compute nodes.

    ``edge_kind='data'`` is the data dependency specialization. Other supported
    kinds include control, state, feedback, stream/streaming, resource, order,
    and metadata. Cycles are executable only when at least one edge in the cycle
    declares loop/feedback/streaming/state semantics.
    """

    source_node: str
    target_node: str
    tensor_name: str = ""
    tensor_spec: Optional[TensorSpec] = None
    edge_kind: str = "data"
    attributes: Dict[str, Any] = field(default_factory=dict)
    cycle_semantics: Optional[Dict[str, Any]] = None

    @property
    def order_affecting(self) -> bool:
        return self.edge_kind not in NON_EXECUTABLE_EDGE_KINDS

    def declares_cycle_semantics(self) -> bool:
        if self.cycle_semantics:
            return True
        if self.edge_kind in CYCLE_DECLARING_EDGE_KINDS and self.attributes:
            return True
        return bool(self.attributes.get("loop") or self.attributes.get("feedback") or self.attributes.get("streaming") or self.attributes.get("state_update"))

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "source_node": self.source_node,
            "target_node": self.target_node,
            "source": self.source_node,
            "target": self.target_node,
            "tensor_name": self.tensor_name,
            "edge_kind": self.edge_kind,
            "attributes": dict(self.attributes),
            "tensor_spec": self.tensor_spec.to_dict() if self.tensor_spec else None,
        }
        if self.cycle_semantics is not None:
            data["cycle_semantics"] = dict(self.cycle_semantics)
        return data

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> DataEdge:
        tensor_spec = data.get("tensor_spec")
        if tensor_spec is None and "tensor_shape" in data:
            tensor_spec = {"shape": data.get("tensor_shape", []), "dtype": data.get("tensor_dtype", "FP64")}
        return DataEdge(
            source_node=str(data.get("source_node", data.get("source", ""))),
            target_node=str(data.get("target_node", data.get("target", ""))),
            tensor_name=str(data.get("tensor_name", "")),
            tensor_spec=TensorSpec.from_dict(tensor_spec) if isinstance(tensor_spec, Mapping) else None,
            edge_kind=str(data.get("edge_kind", "data")),
            attributes=dict(data.get("attributes", {}) or {}),
            cycle_semantics=dict(data.get("cycle_semantics")) if isinstance(data.get("cycle_semantics"), Mapping) else None,
        )


@dataclass
class GraphRegion:
    """Hierarchical region such as a loop body, pipeline stage, or fused kernel."""

    region_id: str
    region_type: str
    node_ids: List[str] = field(default_factory=list)
    entry_nodes: List[str] = field(default_factory=list)
    exit_nodes: List[str] = field(default_factory=list)
    semantics: Dict[str, Any] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)

    def has_lowering_semantics(self) -> bool:
        if self.region_type in {"loop", "feedback", "stream", "streaming"}:
            keys = {"iterations", "iteration_count", "trip_count", "trip_count_distribution", "convergence", "summary_model", "bounded"}
            return any(key in self.semantics for key in keys)
        if self.region_type in {"dynamic_control", "branch", "conditional"}:
            keys = {"branch_probabilities", "summary_model", "trace_distribution"}
            return any(key in self.semantics for key in keys)
        if self.region_type in {"recursion", "dynamic_recursion"}:
            return "summary_model" in self.semantics
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": self.region_id,
            "region_type": self.region_type,
            "node_ids": list(self.node_ids),
            "entry_nodes": list(self.entry_nodes),
            "exit_nodes": list(self.exit_nodes),
            "semantics": dict(self.semantics),
            "attributes": dict(self.attributes),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> GraphRegion:
        return GraphRegion(
            region_id=str(data.get("region_id", "")),
            region_type=str(data.get("region_type", "")),
            node_ids=[str(item) for item in data.get("node_ids", []) or []],
            entry_nodes=[str(item) for item in data.get("entry_nodes", []) or []],
            exit_nodes=[str(item) for item in data.get("exit_nodes", []) or []],
            semantics=dict(data.get("semantics", {}) or {}),
            attributes=dict(data.get("attributes", {}) or {}),
        )


@dataclass
class ComputeGraph:
    """Domain-neutral computation graph for application workloads."""

    graph_id: str
    nodes: Dict[str, ComputeNode] = field(default_factory=dict)
    edges: List[DataEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    regions: Dict[str, GraphRegion] = field(default_factory=dict)

    def add_node(self, node: ComputeNode) -> ComputeGraph:
        self.nodes[node.node_id] = node
        return self

    def add_edge(self, edge: DataEdge) -> ComputeGraph:
        self.edges.append(edge)
        return self

    def add_region(self, region: GraphRegion) -> ComputeGraph:
        self.regions[region.region_id] = region
        return self

    def get_node(self, node_id: str) -> Optional[ComputeNode]:
        return self.nodes.get(node_id)

    def predecessors(self, node_id: str, *, executable_only: bool = False) -> List[str]:
        return [edge.source_node for edge in self._ordered_edges(executable_only=executable_only) if edge.target_node == node_id]

    def successors(self, node_id: str, *, executable_only: bool = False) -> List[str]:
        return [edge.target_node for edge in self._ordered_edges(executable_only=executable_only) if edge.source_node == node_id]

    def _ordered_edges(self, *, executable_only: bool = False) -> List[DataEdge]:
        edges = [edge for edge in self.edges if edge.order_affecting]
        if executable_only:
            cycle_edge_ids: Set[int] = set()
            for cycle in self._cycle_edges(executable_only=False):
                for edge in cycle:
                    if edge.declares_cycle_semantics():
                        cycle_edge_ids.add(id(edge))
            edges = [edge for edge in edges if id(edge) not in cycle_edge_ids]
        return edges

    def _cycle_edges(self, executable_only: bool = False) -> List[List[DataEdge]]:
        edges = self._ordered_edges(executable_only=executable_only)
        adjacency: Dict[str, List[Tuple[str, DataEdge]]] = {node_id: [] for node_id in self.nodes}
        for edge in edges:
            if edge.source_node in adjacency and edge.target_node in self.nodes:
                adjacency[edge.source_node].append((edge.target_node, edge))

        visiting: Set[str] = set()
        visited: Set[str] = set()
        stack_nodes: List[str] = []
        stack_edges: List[DataEdge] = []
        cycles: List[List[DataEdge]] = []

        def visit(node_id: str) -> None:
            visiting.add(node_id)
            stack_nodes.append(node_id)
            for next_node, edge in adjacency.get(node_id, []):
                if next_node in visiting:
                    try:
                        idx = stack_nodes.index(next_node)
                    except ValueError:
                        idx = 0
                    cycles.append(stack_edges[idx:] + [edge])
                elif next_node not in visited:
                    stack_edges.append(edge)
                    visit(next_node)
                    stack_edges.pop()
            visiting.remove(node_id)
            visited.add(node_id)
            stack_nodes.pop()

        for node_id in self.nodes:
            if node_id not in visited:
                visit(node_id)
        return cycles

    def validate(self) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        if not self.graph_id:
            issues.append({"object_type": "ComputeGraph", "object_id": self.graph_id, "field": "graph_id", "severity": "error", "message": "graph_id is required"})
        for node_id, node in self.nodes.items():
            if node_id != node.node_id:
                issues.append({"object_type": "ComputeNode", "object_id": node_id, "field": "node_id", "severity": "error", "message": "node key and node_id differ"})
            issues.extend(node.validate())
        for idx, edge in enumerate(self.edges):
            edge_id = f"edge[{idx}]"
            if edge.source_node not in self.nodes:
                issues.append({"object_type": "DataEdge", "object_id": edge_id, "field": "source_node", "severity": "error", "message": f"missing source node {edge.source_node}"})
            if edge.target_node not in self.nodes:
                issues.append({"object_type": "DataEdge", "object_id": edge_id, "field": "target_node", "severity": "error", "message": f"missing target node {edge.target_node}"})
            if edge.edge_kind == "data" and not edge.tensor_name:
                issues.append({"object_type": "DataEdge", "object_id": edge_id, "field": "tensor_name", "severity": "warning", "message": "data edge has no tensor_name"})
            if edge.tensor_spec:
                issues.extend(edge.tensor_spec.validate(prefix=f"{edge_id}.tensor_spec"))
        for region_id, region in self.regions.items():
            if region_id != region.region_id:
                issues.append({"object_type": "GraphRegion", "object_id": region_id, "field": "region_id", "severity": "error", "message": "region key and region_id differ"})
            missing_nodes = [node_id for node_id in region.node_ids if node_id not in self.nodes]
            if missing_nodes:
                issues.append({"object_type": "GraphRegion", "object_id": region_id, "field": "node_ids", "severity": "error", "message": f"region references missing nodes: {', '.join(missing_nodes)}"})
            if not region.has_lowering_semantics():
                issues.append({"object_type": "GraphRegion", "object_id": region_id, "field": "semantics", "severity": "warning", "message": "region lacks enough lowering semantics for final executable evidence"})

        for cycle in self._cycle_edges(executable_only=False):
            if not any(edge.declares_cycle_semantics() for edge in cycle):
                cycle_desc = [f"{edge.source_node}->{edge.target_node}" for edge in cycle]
                issues.append({"object_type": "ComputeGraph", "object_id": self.graph_id, "field": "edges", "severity": "error", "message": f"unannotated dependency cycle: {'; '.join(cycle_desc)}"})
        for cycle in self._cycle_edges(executable_only=True):
            cycle_desc = [f"{edge.source_node}->{edge.target_node}" for edge in cycle]
            issues.append({"object_type": "ComputeGraph", "object_id": self.graph_id, "field": "edges", "severity": "error", "message": f"executable dependency cycle after removing declared feedback edges: {'; '.join(cycle_desc)}"})

        errors = [issue for issue in issues if issue.get("severity") == "error"]
        warnings = [issue for issue in issues if issue.get("severity") != "error"]
        return {
            "schema_version": "dse.compute_graph_validation.v1",
            "graph_id": self.graph_id,
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "issue_count": len(issues),
        }

    def topological_sort(self) -> List[str]:
        edges = self._ordered_edges(executable_only=True)
        in_degree = {node_id: 0 for node_id in self.nodes}
        adjacency: Dict[str, List[str]] = {node_id: [] for node_id in self.nodes}
        for edge in edges:
            if edge.source_node in adjacency and edge.target_node in in_degree:
                adjacency[edge.source_node].append(edge.target_node)
                in_degree[edge.target_node] += 1
        ready = [node_id for node_id in sorted(in_degree) if in_degree[node_id] == 0]
        order: List[str] = []
        while ready:
            node_id = ready.pop(0)
            order.append(node_id)
            for target in sorted(adjacency.get(node_id, [])):
                in_degree[target] -= 1
                if in_degree[target] == 0:
                    ready.append(target)
        if len(order) != len(self.nodes):
            unresolved = sorted(node_id for node_id, degree in in_degree.items() if degree > 0)
            raise ValueError(f"graph has an executable cycle involving: {', '.join(unresolved)}")
        return order

    def total_flops(self) -> float:
        return sum(node.estimated_flops for node in self.nodes.values())

    def total_memory_bytes(self) -> float:
        return sum(node.estimated_memory_bytes for node in self.nodes.values())

    def has_declared_non_dag_semantics(self) -> bool:
        return bool(self.regions) or any(edge.declares_cycle_semantics() for edge in self.edges)

    def clone_executable_view(self, graph_id: Optional[str] = None) -> ComputeGraph:
        data = self.to_dict()
        data["graph_id"] = graph_id or f"{self.graph_id}.executable"
        data["edges"] = [edge.to_dict() for edge in self._ordered_edges(executable_only=True)]
        data["regions"] = []
        metadata = dict(data.get("metadata", {}) or {})
        metadata["source_graph_id"] = self.graph_id
        metadata["executable_view"] = True
        data["metadata"] = metadata
        return ComputeGraph.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "dse.compute_graph.v1",
            "graph_id": self.graph_id,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "edges": [edge.to_dict() for edge in self.edges],
            "regions": [region.to_dict() for region in self.regions.values()],
            "metadata": dict(self.metadata),
            "total_flops": self.total_flops(),
            "total_memory_bytes": self.total_memory_bytes(),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> ComputeGraph:
        graph = ComputeGraph(
            graph_id=str(data.get("graph_id", "")),
            metadata=dict(data.get("metadata", {}) or {}),
        )
        nodes_payload = data.get("nodes", {}) or {}
        if isinstance(nodes_payload, Mapping):
            for node_id, node_data in nodes_payload.items():
                node = ComputeNode.from_dict({"node_id": node_id, **dict(node_data)}) if isinstance(node_data, Mapping) else ComputeNode(str(node_id), "")
                graph.add_node(node)
        else:
            for node_data in nodes_payload:
                node = ComputeNode.from_dict(node_data)
                graph.add_node(node)
        for edge_data in data.get("edges", []) or []:
            graph.add_edge(DataEdge.from_dict(edge_data))
        for region_data in data.get("regions", []) or []:
            region = GraphRegion.from_dict(region_data)
            graph.add_region(region)
        return graph


# Example: Create a simple GEMM-based compute graph.
def create_gemm_graph(graph_id: str = "gemm_example") -> ComputeGraph:
    graph = ComputeGraph(graph_id=graph_id)
    graph.add_node(ComputeNode(
        node_id="A",
        op_type="placeholder",
        outputs=["A"],
        output_specs={"A": TensorSpec(shape=(1024, 512), dtype="FP64")},
    ))
    graph.add_node(ComputeNode(
        node_id="B",
        op_type="placeholder",
        outputs=["B"],
        output_specs={"B": TensorSpec(shape=(512, 256), dtype="FP64")},
    ))
    gemm_flops = 2.0 * 1024 * 512 * 256
    graph.add_node(ComputeNode(
        node_id="gemm",
        op_type="gemm",
        inputs=["A", "B"],
        outputs=["C"],
        input_specs={"A": TensorSpec(shape=(1024, 512)), "B": TensorSpec(shape=(512, 256))},
        output_specs={"C": TensorSpec(shape=(1024, 256), dtype="FP64")},
        estimated_flops=gemm_flops,
        estimated_memory_bytes=(1024 * 512 + 512 * 256 + 1024 * 256) * 8,
    ))
    graph.add_node(ComputeNode(
        node_id="bias",
        op_type="add",
        inputs=["C"],
        outputs=["D"],
        input_specs={"C": TensorSpec(shape=(1024, 256))},
        output_specs={"D": TensorSpec(shape=(1024, 256), dtype="FP64")},
        estimated_flops=1024 * 256,
        estimated_memory_bytes=(1024 * 256 + 1024 * 256) * 8,
    ))
    graph.add_edge(DataEdge("A", "gemm", "A"))
    graph.add_edge(DataEdge("B", "gemm", "B"))
    graph.add_edge(DataEdge("gemm", "bias", "C"))
    return graph

