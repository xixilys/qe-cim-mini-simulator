#!/usr/bin/env python3
"""Level 3 Compute Graph IR: Application-level computation graph.

Represents computations as a DAG of operations with data dependencies.
This is the interface between application workloads and the DSE framework.

Key design decisions:
1. Operator-agnostic: No predefined operator set
2. Shape-aware: Tensor shapes are first-class information
3. Precision-aware: Data type is part of the graph
4. Extensible: Custom operators via opaque attributes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class TensorSpec:
    """Tensor specification with shape and data type."""
    shape: Tuple[int, ...]
    dtype: str = "FP64"
    layout: str = "row_major"
    
    def num_elements(self) -> int:
        result = 1
        for dim in self.shape:
            result *= max(1, dim)
        return result
    
    def size_bytes(self) -> int:
        type_sizes = {"FP64": 8, "FP32": 4, "FP16": 2, "INT8": 1, "INT32": 4}
        return self.num_elements() * type_sizes.get(self.dtype, 8)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "shape": self.shape,
            "dtype": self.dtype,
            "layout": self.layout,
            "num_elements": self.num_elements(),
            "size_bytes": self.size_bytes(),
        }


@dataclass
class ComputeNode:
    """A single compute operation in the graph.
    
    This is intentionally minimal and generic. The op_type is a string
    that can represent any operation - from standard ML ops to custom
    scientific computing kernels.
    """
    node_id: str
    op_type: str
    
    # Inputs and outputs
    inputs: List[str] = field(default_factory=list)  # Input tensor names
    outputs: List[str] = field(default_factory=list)  # Output tensor names
    
    # Tensor specifications
    input_specs: Dict[str, TensorSpec] = field(default_factory=dict)
    output_specs: Dict[str, TensorSpec] = field(default_factory=dict)
    
    # Compute characteristics (can be estimated or measured)
    estimated_flops: float = 0.0
    estimated_memory_bytes: float = 0.0
    
    # Custom attributes for domain-specific information
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "op_type": self.op_type,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "input_specs": {k: v.to_dict() for k, v in self.input_specs.items()},
            "output_specs": {k: v.to_dict() for k, v in self.output_specs.items()},
            "estimated_flops": self.estimated_flops,
            "estimated_memory_bytes": self.estimated_memory_bytes,
            "attributes": self.attributes,
        }


@dataclass
class DataEdge:
    """Data dependency edge between compute nodes."""
    source_node: str
    target_node: str
    tensor_name: str
    tensor_spec: Optional[TensorSpec] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_node": self.source_node,
            "target_node": self.target_node,
            "tensor_name": self.tensor_name,
            "tensor_spec": self.tensor_spec.to_dict() if self.tensor_spec else None,
        }


@dataclass
class ComputeGraph:
    """Computation graph representing an application workload.
    
    This is a directed acyclic graph (DAG) of compute operations.
    It is completely generic and not tied to any specific domain.
    """
    graph_id: str
    nodes: Dict[str, ComputeNode] = field(default_factory=dict)
    edges: List[DataEdge] = field(default_factory=list)
    
    # Graph-level metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_node(self, node: ComputeNode) -> ComputeGraph:
        self.nodes[node.node_id] = node
        return self
    
    def add_edge(self, edge: DataEdge) -> ComputeGraph:
        self.edges.append(edge)
        return self
    
    def get_node(self, node_id: str) -> Optional[ComputeNode]:
        return self.nodes.get(node_id)
    
    def predecessors(self, node_id: str) -> List[str]:
        return [edge.source_node for edge in self.edges if edge.target_node == node_id]
    
    def successors(self, node_id: str) -> List[str]:
        return [edge.target_node for edge in self.edges if edge.source_node == node_id]
    
    def topological_sort(self) -> List[str]:
        visited: Set[str] = set()
        result: List[str] = []
        
        def visit(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)
            for succ in self.successors(node_id):
                visit(succ)
            result.append(node_id)
        
        for node_id in self.nodes:
            visit(node_id)
        
        return list(reversed(result))
    
    def total_flops(self) -> float:
        return sum(node.estimated_flops for node in self.nodes.values())
    
    def total_memory_bytes(self) -> float:
        return sum(node.estimated_memory_bytes for node in self.nodes.values())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "edges": [edge.to_dict() for edge in self.edges],
            "metadata": self.metadata,
            "total_flops": self.total_flops(),
            "total_memory_bytes": self.total_memory_bytes(),
        }


# Example: Create a simple GEMM-based compute graph
def create_gemm_graph(graph_id: str = "gemm_example") -> ComputeGraph:
    graph = ComputeGraph(graph_id=graph_id)
    
    # Node 1: Matrix A (input)
    graph.add_node(ComputeNode(
        node_id="A",
        op_type="placeholder",
        outputs=["A"],
        output_specs={"A": TensorSpec(shape=(1024, 512), dtype="FP64")},
    ))
    
    # Node 2: Matrix B (input)
    graph.add_node(ComputeNode(
        node_id="B",
        op_type="placeholder",
        outputs=["B"],
        output_specs={"B": TensorSpec(shape=(512, 256), dtype="FP64")},
    ))
    
    # Node 3: GEMM C = A @ B
    gemm_flops = 2.0 * 1024 * 512 * 256
    graph.add_node(ComputeNode(
        node_id="gemm",
        op_type="gemm",
        inputs=["A", "B"],
        outputs=["C"],
        input_specs={"A": TensorSpec(shape=(1024, 512)), "B": TensorSpec(shape=(512, 256))},
        output_specs={"C": TensorSpec(shape=(1024, 256), dtype="FP64")},
        estimated_flops=gemm_flops,
        estimated_memory_bytes=(1024*512 + 512*256 + 1024*256) * 8,
    ))
    
    # Node 4: Add bias
    graph.add_node(ComputeNode(
        node_id="bias",
        op_type="add",
        inputs=["C"],
        outputs=["D"],
        input_specs={"C": TensorSpec(shape=(1024, 256))},
        output_specs={"D": TensorSpec(shape=(1024, 256), dtype="FP64")},
        estimated_flops=1024 * 256,
        estimated_memory_bytes=(1024*256 + 1024*256) * 8,
    ))
    
    # Edges
    graph.add_edge(DataEdge("A", "gemm", "A"))
    graph.add_edge(DataEdge("B", "gemm", "B"))
    graph.add_edge(DataEdge("gemm", "bias", "C"))
    
    return graph


# Example: Create a DFT-specific compute graph (SCF iteration)
def create_dft_scf_graph(graph_id: str = "dft_scf") -> ComputeGraph:
    graph = ComputeGraph(
        graph_id=graph_id,
        metadata={"domain": "dft", "solver": "scf", "iterations": 10},
    )
    
    npw, nkb, m = 2945, 144, 16
    
    # h_psi: Apply Hamiltonian
    graph.add_node(ComputeNode(
        node_id="h_psi",
        op_type="gemm",
        inputs=["psi", "H"],
        outputs=["h_psi_out"],
        estimated_flops=2.0 * npw * nkb * m,
        estimated_memory_bytes=(npw*nkb + npw*m + nkb*m) * 8,
        attributes={"description": "Apply Hamiltonian to wavefunctions"},
    ))
    
    # build_H_sub: Build reduced Hamiltonian
    graph.add_node(ComputeNode(
        node_id="build_H_sub",
        op_type="reduction",
        inputs=["h_psi_out", "psi"],
        outputs=["H_sub"],
        estimated_flops=npw * m * m,
        estimated_memory_bytes=(npw*m + m*m) * 8,
        attributes={"description": "Build reduced subspace Hamiltonian"},
    ))
    
    # diagonalize: Solve eigenvalue problem
    graph.add_node(ComputeNode(
        node_id="diagonalize",
        op_type="eigen",
        inputs=["H_sub"],
        outputs=["eigenvalues", "eigenvectors"],
        estimated_flops=(nkb ** 3) * m / 16.0,
        estimated_memory_bytes=(nkb*nkb + m + m*m) * 8,
        attributes={"description": "Generalized Hermitian eigensolver"},
    ))
    
    # refresh: Update wavefunctions
    graph.add_node(ComputeNode(
        node_id="refresh",
        op_type="gemm",
        inputs=["psi", "eigenvectors"],
        outputs=["psi_new"],
        estimated_flops=2.0 * npw * m * m,
        estimated_memory_bytes=(npw*m + m*m + npw*m) * 8,
        attributes={"description": "Update wavefunctions from eigenvectors"},
    ))
    
    # Edges
    graph.add_edge(DataEdge("h_psi", "build_H_sub", "h_psi_out"))
    graph.add_edge(DataEdge("build_H_sub", "diagonalize", "H_sub"))
    graph.add_edge(DataEdge("diagonalize", "refresh", "eigenvectors"))
    
    return graph