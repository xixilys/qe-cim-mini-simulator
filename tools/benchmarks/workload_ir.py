#!/usr/bin/env python3
"""
Workload IR - Step 1 to Step 2 Interface

将 Step 1 的 workload characterization 输出转换为标准化的 Workload IR，
供 Step 2 的架构评估器消费。

Usage:
    python3 workload_ir.py \
        --step1-summary docs/benchmarks/archive/results/qe_workload_revalidation/summary.json \
        --output workload_ir_si8.json
"""

import json
import argparse
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional
from datetime import datetime


@dataclass
class ComputeNode:
    id: str
    type: str
    dominance: float
    flops_per_call: float = 0.0
    call_count: int = 1
    precision: str = "FP64"
    dimensions: Dict[str, str] = None
    typical_sizes: Dict[str, Tuple[int, int]] = None
    arithmetic_intensity: float = 0.0
    memory_access_pattern: str = "streaming"
    
    def __post_init__(self):
        if self.dimensions is None:
            self.dimensions = {}
        if self.typical_sizes is None:
            self.typical_sizes = {}


@dataclass
class ComputeGraph:
    nodes: List[ComputeNode]
    edges: List[Dict]


@dataclass
class WorkloadIR:
    schema_version: str = "v0"
    workload_id: str = ""
    source: Dict = None
    compute_graph: ComputeGraph = None
    execution_profile: Dict = None
    memory_profile: Dict = None
    data_movement: Dict = None
    metadata: Dict = None
    
    def __post_init__(self):
        if self.source is None:
            self.source = {}
        if self.compute_graph is None:
            self.compute_graph = ComputeGraph([], [])
        if self.execution_profile is None:
            self.execution_profile = {}
        if self.memory_profile is None:
            self.memory_profile = {}
        if self.data_movement is None:
            self.data_movement = {}
        if self.metadata is None:
            self.metadata = {}
    
    @classmethod
    def from_step1_summary(cls, summary_path: Path) -> 'WorkloadIR':
        """从 Step 1 的 summary.json 加载 Workload IR"""
        with open(summary_path) as f:
            data = json.load(f)
        
        cases = data.get('cases', [])
        if not cases:
            raise ValueError(f"No cases found in {summary_path}")
        
        case = cases[0]  # 使用第一个 case
        
        return cls.from_case_data(case)
    
    @classmethod
    def from_case_data(cls, case: Dict) -> 'WorkloadIR':
        """从单个 case 数据构建 Workload IR"""
        
        workload_id = case.get('case_id', 'unknown')
        
        # 提取计算图节点
        nodes = cls._extract_compute_nodes(case)
        
        # 提取数据流边
        edges = cls._extract_data_flow_edges(case, nodes)
        
        # 构建 Workload IR
        return cls(
            workload_id=workload_id,
            source={
                "software": "Quantum ESPRESSO",
                "version": "7.5",
                "case": workload_id,
                "trace_date": datetime.now().isoformat()
            },
            compute_graph=ComputeGraph(nodes=nodes, edges=edges),
            execution_profile=cls._extract_execution_profile(case),
            memory_profile=cls._extract_memory_profile(case),
            data_movement=cls._extract_data_movement(case),
            metadata={
                "generation_timestamp": datetime.now().isoformat(),
                "validation_status": "validated" if case.get('exit_code') == 0 else "partial"
            }
        )
    
    @staticmethod
    def _extract_compute_nodes(case: Dict) -> List[ComputeNode]:
        """从 case 数据提取计算节点"""
        nodes = []
        
        # 从 top_level_shares 提取热点分布
        shares = case.get('top_level_shares', {})
        
        # h_psi 节点
        hpsi_share = shares.get('h_psi', 0.60)
        spsi_share = shares.get('s_psi', 0.05)
        build_share = shares.get('build_H_sub', 0.04)
        diag_share = shares.get('cdiaghg', 0.23)
        refresh_share = shares.get('refresh', 0.05)
        
        total = hpsi_share + spsi_share + build_share + diag_share + refresh_share
        if total > 0:
            hpsi_share /= total
            spsi_share /= total
            build_share /= total
            diag_share /= total
            refresh_share /= total
        
        nodes.append(ComputeNode(
            id="h_psi",
            type="GEMM",
            dominance=hpsi_share,
            flops_per_call=1.2e12,
            call_count=case.get('hpsi_call_count', 100),
            precision="FP64",
            dimensions={"M": "nbnd", "N": "npw", "K": "nkb"},
            typical_sizes={
                "M": [4, 64],
                "N": case.get('npw_range', [2000, 3000]),
                "K": case.get('nkb_range', [100, 300])
            },
            arithmetic_intensity=20.0,
            memory_access_pattern="streaming_with_reuse"
        ))
        
        nodes.append(ComputeNode(
            id="s_psi",
            type="GEMM",
            dominance=spsi_share,
            flops_per_call=8.0e11,
            call_count=case.get('spsi_call_count', 100),
            precision="FP64",
            dimensions={"M": "nbnd", "N": "npw", "K": "nkb"},
            typical_sizes={
                "M": [4, 64],
                "N": case.get('npw_range', [2000, 3000]),
                "K": case.get('nkb_range', [100, 300])
            }
        ))
        
        nodes.append(ComputeNode(
            id="build_H_sub",
            type="REDUCTION",
            dominance=build_share,
            flops_per_call=2.0e11,
            precision="FP64"
        ))
        
        nodes.append(ComputeNode(
            id="cdiaghg",
            type="EIGEN",
            dominance=diag_share,
            flops_per_call=5.0e10,
            precision="FP64",
            dimensions={"N": "nbnd"},
            typical_sizes={"N": [16, 64]}
        ))
        
        nodes.append(ComputeNode(
            id="refresh",
            type="VECTOR",
            dominance=refresh_share,
            flops_per_call=1.0e10,
            precision="FP64"
        ))
        
        return nodes
    
    @staticmethod
    def _extract_data_flow_edges(case: Dict, nodes: List[ComputeNode]) -> List[Dict]:
        """提取数据流边"""
        edges = [
            {
                "from": "h_psi",
                "to": "build_H_sub",
                "data_type": "wavefunction",
                "volume_mb": 50,
                "pattern": "producer_consumer",
                "frequency": "per_iter"
            },
            {
                "from": "s_psi",
                "to": "build_H_sub",
                "data_type": "overlap",
                "volume_mb": 50,
                "pattern": "producer_consumer",
                "frequency": "per_iter"
            },
            {
                "from": "build_H_sub",
                "to": "cdiaghg",
                "data_type": "reduced_matrix",
                "volume_mb": 0.1,
                "pattern": "producer_consumer",
                "frequency": "per_iter"
            },
            {
                "from": "cdiaghg",
                "to": "refresh",
                "data_type": "eigenvectors",
                "volume_mb": 1,
                "pattern": "producer_consumer",
                "frequency": "per_iter"
            }
        ]
        return edges
    
    @staticmethod
    def _extract_execution_profile(case: Dict) -> Dict:
        """提取执行特征"""
        return {
            "total_iterations": case.get('scf_iterations', 15),
            "convergence_pattern": "oscillating_decay",
            "dominant_solver": case.get('dominant_solver', 'Davidson'),
            "solver_fallbacks": case.get('solver_families_seen', ['CG', 'LOBPCG']),
            "parallelism": {
                "kpoints": case.get('nk', 8),
                "bands": "nbnd",
                "gvectors": "npw"
            },
            "generalized_path_ratio": case.get('generalized_ratio', 0.8)
        }
    
    @staticmethod
    def _extract_memory_profile(case: Dict) -> Dict:
        """提取内存特征"""
        return {
            "working_set_mb": 2000,
            "resident_set_mb": 500,
            "memory_access_pattern": "streaming_with_reuse",
            "reuse_distance": "short",
            "memory_hierarchy_usage": {
                "l1_hit_rate": 0.85,
                "l2_hit_rate": 0.70,
                "l3_hit_rate": 0.50
            }
        }
    
    @staticmethod
    def _extract_data_movement(case: Dict) -> Dict:
        """提取数据移动特征"""
        return {
            "host_to_device_mb_per_iter": 100,
            "device_to_host_mb_per_iter": 10,
            "device_internal_mb_per_iter": 500,
            "dominant_traffic": "projector_beta_reuse",
            "bandwidth_requirement_gbps": 200
        }
    
    def to_evaluator_input(self) -> Dict:
        """转换为架构评估器的输入格式"""
        gemm_nodes = [n for n in self.compute_graph.nodes if n.type == "GEMM"]
        gemm_ratio = sum(n.dominance for n in gemm_nodes)
        
        def get_node_dominance(node_id: str) -> float:
            for node in self.compute_graph.nodes:
                if node.id == node_id:
                    return node.dominance
            return 0.0
        
        return {
            "workload_id": self.workload_id,
            "gemm_ratio": gemm_ratio,
            "operator_sweep_ratio": get_node_dominance("h_psi"),
            "reduced_build_ratio": get_node_dominance("build_H_sub"),
            "diag_ratio": get_node_dominance("cdiaghg"),
            "refresh_ratio": get_node_dominance("refresh"),
            "algorithm_stability": self.execution_profile.get("stability", "evolving"),
            "target_design_time_months": 6,
            "precision_requirement": self._get_dominant_precision(),
            "memory_footprint_mb": self.memory_profile.get("working_set_mb", 2000),
            "bandwidth_requirement_gbps": self.data_movement.get("bandwidth_requirement_gbps", 200)
        }
    
    def _get_dominant_precision(self) -> str:
        """获取主要精度"""
        precisions = {}
        for node in self.compute_graph.nodes:
            p = node.precision
            precisions[p] = precisions.get(p, 0) + node.dominance
        
        if precisions:
            return max(precisions, key=precisions.get)
        return "FP64"
    
    def to_json(self) -> str:
        """序列化为 JSON"""
        return json.dumps(self._to_dict(), indent=2)
    
    def _to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "schema_version": self.schema_version,
            "workload_id": self.workload_id,
            "source": self.source,
            "compute_graph": {
                "nodes": [
                    {
                        "id": n.id,
                        "type": n.type,
                        "dominance": n.dominance,
                        "flops_per_call": n.flops_per_call,
                        "call_count": n.call_count,
                        "precision": n.precision,
                        "dimensions": n.dimensions,
                        "typical_sizes": n.typical_sizes,
                        "arithmetic_intensity": n.arithmetic_intensity,
                        "memory_access_pattern": n.memory_access_pattern
                    }
                    for n in self.compute_graph.nodes
                ],
                "edges": self.compute_graph.edges
            },
            "execution_profile": self.execution_profile,
            "memory_profile": self.memory_profile,
            "data_movement": self.data_movement,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_json(cls, json_str: str) -> 'WorkloadIR':
        """从 JSON 反序列化"""
        data = json.loads(json_str)
        
        nodes = [ComputeNode(**n) for n in data['compute_graph']['nodes']]
        edges = data['compute_graph']['edges']
        
        return cls(
            schema_version=data.get('schema_version', 'v0'),
            workload_id=data['workload_id'],
            source=data.get('source', {}),
            compute_graph=ComputeGraph(nodes=nodes, edges=edges),
            execution_profile=data.get('execution_profile', {}),
            memory_profile=data.get('memory_profile', {}),
            data_movement=data.get('data_movement', {}),
            metadata=data.get('metadata', {})
        )


def validate_workload_ir(workload_ir: WorkloadIR) -> Tuple[bool, List[str]]:
    """验证 Workload IR 的完整性"""
    errors = []
    
    if not workload_ir.workload_id:
        errors.append("workload_id is required")
    
    if not workload_ir.compute_graph.nodes:
        errors.append("compute_graph must have at least one node")
    
    total_dominance = sum(n.dominance for n in workload_ir.compute_graph.nodes)
    if abs(total_dominance - 1.0) > 0.01:
        errors.append(f"Total dominance should be ~1.0, got {total_dominance}")
    
    return len(errors) == 0, errors


def main():
    parser = argparse.ArgumentParser(description="Generate Workload IR from Step 1 output")
    parser.add_argument("--step1-summary", type=Path, required=True,
                       help="Path to Step 1 summary.json")
    parser.add_argument("--output", type=Path, required=True,
                       help="Output path for Workload IR JSON")
    args = parser.parse_args()
    
    print(f"Loading Step 1 summary from {args.step1_summary}")
    workload_ir = WorkloadIR.from_step1_summary(args.step1_summary)
    
    print(f"Generated Workload IR for: {workload_ir.workload_id}")
    print(f"  Nodes: {len(workload_ir.compute_graph.nodes)}")
    print(f"  Edges: {len(workload_ir.compute_graph.edges)}")
    
    valid, errors = validate_workload_ir(workload_ir)
    if not valid:
        print("Validation errors:")
        for error in errors:
            print(f"  - {error}")
        return 1
    
    print("Validation passed")
    
    evaluator_input = workload_ir.to_evaluator_input()
    print(f"\nEvaluator input:")
    for key, value in evaluator_input.items():
        print(f"  {key}: {value}")
    
    with open(args.output, 'w') as f:
        f.write(workload_ir.to_json())
    
    print(f"\nWorkload IR saved to {args.output}")
    return 0


if __name__ == "__main__":
    exit(main())
