#!/usr/bin/env python3
"""DSE Core: Multi-accelerator design space exploration.

This module provides the core DSE functionality for heterogeneous systems:
1. Search space definition
2. Design point generation
3. Evaluation orchestration
4. Result aggregation

Design principles:
1. Multi-objective: Optimize for performance, power, cost simultaneously
2. Heterogeneous-aware: Consider different accelerator capabilities
3. Communication-aware: Account for data movement costs
4. Extensible: Support custom search strategies and evaluators
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Callable
import itertools

from dse_v2.core.architecture.accelerator import SystemArchitecture, Accelerator
from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.ir.task_graph import TaskGraph, map_compute_to_tasks


@dataclass
class DesignPoint:
    """A single design point in the search space.
    
    Represents a complete hardware/software configuration:
    - System architecture (which accelerators, how connected)
    - Task mapping (which tasks run on which accelerators)
    - Scheduling policy (static, dynamic, etc.)
    """
    design_point_id: str
    
    # Hardware configuration
    system_architecture: SystemArchitecture
    
    # Software mapping
    task_mapping: Dict[str, str]  # task_id -> accel_id
    
    # Scheduling configuration
    scheduling_policy: str = "static"  # "static", "dynamic", "pipeline"
    
    # Additional configuration
    config: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "design_point_id": self.design_point_id,
            "system_architecture": self.system_architecture.to_dict(),
            "task_mapping": self.task_mapping,
            "scheduling_policy": self.scheduling_policy,
            "config": self.config,
        }


@dataclass
class EvaluationResult:
    """Result of evaluating a design point."""
    design_point_id: str
    
    # Performance metrics
    latency_ms: float = 0.0
    throughput_gops: float = 0.0
    
    # Resource metrics
    power_w: float = 0.0
    energy_j: float = 0.0
    area_mm2: float = 0.0
    
    # Efficiency metrics
    compute_efficiency: float = 0.0  # Actual / peak FLOPS
    memory_efficiency: float = 0.0   # Actual / peak bandwidth
    
    # Communication metrics
    total_data_movement_mb: float = 0.0
    communication_overhead_ms: float = 0.0
    
    # Feasibility
    feasible: bool = True
    violation_reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "design_point_id": self.design_point_id,
            "latency_ms": self.latency_ms,
            "throughput_gops": self.throughput_gops,
            "power_w": self.power_w,
            "energy_j": self.energy_j,
            "area_mm2": self.area_mm2,
            "compute_efficiency": self.compute_efficiency,
            "memory_efficiency": self.memory_efficiency,
            "total_data_movement_mb": self.total_data_movement_mb,
            "communication_overhead_ms": self.communication_overhead_ms,
            "feasible": self.feasible,
            "violation_reasons": self.violation_reasons,
        }


@dataclass
class SearchSpace:
    """Defines the search space for DSE.
    
    Specifies which parameters to explore and their ranges.
    """
    # Architecture options
    accelerator_options: List[Accelerator] = field(default_factory=list)
    max_accelerators: int = 4
    
    # Mapping options
    mapping_strategies: List[str] = field(default_factory=lambda: ["static", "dynamic"])
    
    # Scheduling options
    scheduling_policies: List[str] = field(default_factory=lambda: ["static", "pipeline"])
    
    # Constraints
    max_power_w: float = 1000.0
    max_area_mm2: float = 2000.0
    max_cost_usd: float = 100000.0
    
    def generate_design_points(
        self,
        compute_graph: ComputeGraph,
        point_id_prefix: str = "dp",
    ) -> List[DesignPoint]:
        """Generate all valid design points in the search space."""
        design_points = []
        point_idx = 0
        
        # Generate all combinations of accelerators (1 to max_accelerators)
        for num_accels in range(1, self.max_accelerators + 1):
            for accel_combo in itertools.combinations(self.accelerator_options, num_accels):
                # Create system architecture
                sys_arch = SystemArchitecture(
                    system_id=f"sys_{point_idx}",
                    accelerators=list(accel_combo),
                )
                
                # Generate all possible task mappings
                node_ids = list(compute_graph.nodes.keys())
                accel_ids = [accel.accel_id for accel in accel_combo] + ["cpu"]
                
                for mapping_combo in itertools.product(accel_ids, repeat=len(node_ids)):
                    mapping = dict(zip(node_ids, mapping_combo))
                    
                    # Check feasibility
                    feasible, violations = self._check_feasibility(sys_arch, mapping, compute_graph)
                    
                    for scheduling in self.scheduling_policies:
                        dp = DesignPoint(
                            design_point_id=f"{point_id_prefix}_{point_idx}",
                            system_architecture=sys_arch,
                            task_mapping=mapping,
                            scheduling_policy=scheduling,
                        )
                        
                        if feasible:
                            design_points.append(dp)
                        
                        point_idx += 1
                        
                        # Limit search space size for practicality
                        if point_idx >= 1000:
                            return design_points
        
        return design_points
    
    def _check_feasibility(
        self,
        sys_arch: SystemArchitecture,
        mapping: Dict[str, str],
        compute_graph: ComputeGraph,
    ) -> Tuple[bool, List[str]]:
        """Check if a design point is feasible."""
        violations = []
        
        # Check power constraint
        total_power = sum(
            accel.power.static_power_w
            for accel in sys_arch.accelerators
        )
        if total_power > self.max_power_w:
            violations.append(f"Power {total_power}W > {self.max_power_w}W")
        
        # Check if all mapped accelerators exist
        for node_id, accel_id in mapping.items():
            if accel_id != "cpu" and not sys_arch.get_accelerator(accel_id):
                violations.append(f"Accelerator {accel_id} not in system")
            
            # Check if accelerator supports the operation
            if accel_id != "cpu":
                accel = sys_arch.get_accelerator(accel_id)
                node = compute_graph.get_node(node_id)
                if accel and node and not accel.can_execute(node.op_type):
                    violations.append(f"Accelerator {accel_id} cannot execute {node.op_type}")
        
        return len(violations) == 0, violations


class Evaluator:
    """Base class for design point evaluators."""
    
    def evaluate(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
    ) -> EvaluationResult:
        raise NotImplementedError


class AnalyticalEvaluator(Evaluator):
    """Fast analytical evaluator using roofline model."""
    
    def evaluate(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
    ) -> EvaluationResult:
        # Map compute graph to task graph
        accel_bandwidths = {}
        for accel1 in design_point.system_architecture.accelerators:
            for accel2 in design_point.system_architecture.accelerators:
                if accel1 != accel2:
                    # Use minimum of peer link bandwidths
                    bw = 64.0  # Default PCIe bandwidth
                    for link in accel1.communication.peer_links:
                        if link.target_accel_id == accel2.accel_id:
                            bw = link.bandwidth_gbps
                    accel_bandwidths[(accel1.accel_id, accel2.accel_id)] = bw
        
        task_graph = map_compute_to_tasks(compute_graph, design_point.task_mapping, accel_bandwidths)
        
        # Estimate latency for each task
        total_latency_ms = 0.0
        total_flops = 0.0
        total_power_w = 0.0
        total_data_movement_mb = 0.0
        
        for task_id, task in task_graph.tasks.items():
            if not task.placement:
                continue
            
            accel_id = task.placement.accel_id
            if accel_id == "cpu":
                # CPU execution
                compute_latency_ms = task.required_compute_flops / 100e9 * 1000  # Assume 100 GFLOPS CPU
                power_w = 100.0
            else:
                accel = design_point.system_architecture.get_accelerator(accel_id)
                if accel:
                    peak_flops = accel.compute.get_peak_flops("FP64")
                    efficiency = accel.compute.get_op_efficiency("gemm")  # Default
                    compute_latency_ms = task.required_compute_flops / max(peak_flops * efficiency, 1.0) * 1000
                    power_w = accel.power.static_power_w
                else:
                    compute_latency_ms = 0.0
                    power_w = 0.0
            
            # Data movement latency
            movement_latency_ms = sum(mv.transfer_time_ms for mv in task.input_movements)
            total_data_movement_mb += sum(mv.size_bytes for mv in task.input_movements) / (1024.0 * 1024.0)
            
            task.schedule.start_time_ms = total_latency_ms
            task.schedule.end_time_ms = total_latency_ms + compute_latency_ms + movement_latency_ms
            
            total_latency_ms += compute_latency_ms + movement_latency_ms
            total_flops += task.required_compute_flops
            total_power_w += power_w
        
        # Calculate metrics
        throughput_gops = total_flops / max(total_latency_ms, 1.0) / 1e6
        energy_j = total_power_w * total_latency_ms / 1000.0
        
        return EvaluationResult(
            design_point_id=design_point.design_point_id,
            latency_ms=total_latency_ms,
            throughput_gops=throughput_gops,
            power_w=total_power_w,
            energy_j=energy_j,
            total_data_movement_mb=total_data_movement_mb,
            feasible=True,
        )


class DSEOrchestrator:
    """Orchestrates the design space exploration."""
    
    def __init__(
        self,
        search_space: SearchSpace,
        evaluator: Evaluator,
    ):
        self.search_space = search_space
        self.evaluator = evaluator
        self.results: List[EvaluationResult] = []
    
    def explore(
        self,
        compute_graph: ComputeGraph,
        max_points: int = 100,
    ) -> List[EvaluationResult]:
        """Explore the design space and return Pareto-optimal results."""
        # Generate design points
        design_points = self.search_space.generate_design_points(compute_graph)
        
        # Evaluate each design point
        self.results = []
        for dp in design_points[:max_points]:
            result = self.evaluator.evaluate(dp, compute_graph)
            self.results.append(result)
        
        # Filter to Pareto-optimal points
        pareto_results = self._find_pareto_frontier(self.results)
        
        return pareto_results
    
    def _find_pareto_frontier(self, results: List[EvaluationResult]) -> List[EvaluationResult]:
        """Find Pareto-optimal design points."""
        pareto = []
        for r1 in results:
            if not r1.feasible:
                continue
            dominated = False
            for r2 in results:
                if r1 == r2 or not r2.feasible:
                    continue
                # Check if r2 dominates r1 (better in all objectives)
                if (r2.latency_ms <= r1.latency_ms and
                    r2.energy_j <= r1.energy_j and
                    r2.total_data_movement_mb <= r1.total_data_movement_mb and
                    (r2.latency_ms < r1.latency_ms or
                     r2.energy_j < r1.energy_j or
                     r2.total_data_movement_mb < r1.total_data_movement_mb)):
                    dominated = True
                    break
            if not dominated:
                pareto.append(r1)
        
        return pareto
    
    def get_best_design(self, objective: str = "latency") -> Optional[EvaluationResult]:
        """Get the best design point for a given objective."""
        feasible_results = [r for r in self.results if r.feasible]
        if not feasible_results:
            return None
        
        if objective == "latency":
            return min(feasible_results, key=lambda r: r.latency_ms)
        elif objective == "energy":
            return min(feasible_results, key=lambda r: r.energy_j)
        elif objective == "throughput":
            return max(feasible_results, key=lambda r: r.throughput_gops)
        else:
            return feasible_results[0]