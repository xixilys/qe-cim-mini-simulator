#!/usr/bin/env python3
"""Enhanced Analytical Evaluator with proper data movement and parallel scheduling.

This evaluator provides fast analytical performance estimates using:
1. Roofline model for compute-bound vs memory-bound analysis
2. Proper data movement calculation between accelerators
3. Parallel task scheduling (not just sequential)
4. Memory bandwidth bottleneck detection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
import heapq

from dse_v2.core.architecture.accelerator import SystemArchitecture, Accelerator
from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode
from dse_v2.core.ir.task_graph import TaskGraph, Task, TaskPlacement, TaskSchedule, DataMovement, map_compute_to_tasks
from dse_v2.core.ir.execution import ExecutionTimeline, ExecutionEvent, ResourceUsage, DataTransfer


@dataclass
class RooflineAnalysis:
    """Roofline model analysis for a task on an accelerator."""
    task_id: str
    accel_id: str
    
    # Compute intensity (FLOPs / byte)
    arithmetic_intensity: float = 0.0
    
    # Performance limits
    peak_compute_gflops: float = 0.0
    peak_memory_bw_gbps: float = 0.0
    
    # Actual performance
    compute_bound_gflops: float = 0.0
    memory_bound_gflops: float = 0.0
    actual_gflops: float = 0.0
    
    # Bottleneck
    bottleneck: str = "compute"  # "compute" or "memory"
    
    def latency_ms(self, flops: float) -> float:
        if self.actual_gflops <= 0:
            return float('inf')
        return flops / (self.actual_gflops * 1e9) * 1000.0


class EnhancedAnalyticalEvaluator:
    """Enhanced analytical evaluator with proper parallel scheduling and data movement."""
    
    def evaluate(
        self,
        design_point: Any,
        compute_graph: ComputeGraph,
    ) -> Any:
        # Build accelerator bandwidth matrix
        accel_bandwidths = self._build_bandwidth_matrix(design_point.system_architecture)
        
        # Map compute graph to task graph
        task_graph = map_compute_to_tasks(
            compute_graph,
            design_point.task_mapping,
            accel_bandwidths,
        )
        
        # Perform roofline analysis for each task
        roofline_results = {}
        for task_id, task in task_graph.tasks.items():
            if task.placement:
                roofline_results[task_id] = self._roofline_analysis(
                    task, design_point.system_architecture
                )
        
        # Schedule tasks with parallel execution
        timeline = self._schedule_tasks_parallel(task_graph, roofline_results, design_point)
        
        # Calculate metrics from timeline
        return self._calculate_metrics(timeline, design_point, compute_graph)
    
    def _build_bandwidth_matrix(self, sys_arch: SystemArchitecture) -> Dict[Tuple[str, str], float]:
        """Build bandwidth matrix between all accelerator pairs."""
        bandwidths = {}
        
        # Add explicit peer links
        for accel in sys_arch.accelerators:
            for link in accel.communication.peer_links:
                bandwidths[(accel.accel_id, link.target_accel_id)] = link.bandwidth_gbps
                bandwidths[(link.target_accel_id, accel.accel_id)] = link.bandwidth_gbps
        
        # Default host link bandwidth
        for accel in sys_arch.accelerators:
            if accel.communication.host_link:
                bw = accel.communication.host_link.bandwidth_gbps
                bandwidths[(accel.accel_id, "cpu")] = bw
                bandwidths[("cpu", accel.accel_id)] = bw
        
        # CPU to CPU
        bandwidths[("cpu", "cpu")] = 1000.0  # Assume high bandwidth for same-device
        
        return bandwidths
    
    def _roofline_analysis(self, task: Task, sys_arch: SystemArchitecture) -> RooflineAnalysis:
        """Perform roofline analysis for a task on its assigned accelerator."""
        accel_id = task.placement.accel_id if task.placement else "cpu"
        
        if accel_id == "cpu":
            # CPU defaults
            peak_compute = 100.0  # 100 GFLOPS
            peak_memory_bw = 50.0  # 50 GB/s
            efficiency = 0.8
        else:
            accel = sys_arch.get_accelerator(accel_id)
            if not accel:
                return RooflineAnalysis(task_id=task.task_id, accel_id=accel_id)
            
            peak_compute = accel.compute.get_peak_flops("FP64") / 1e9  # Convert to GFLOPS
            
            # Get memory bandwidth from first memory level
            if accel.memory.levels:
                peak_memory_bw = accel.memory.levels[0].bandwidth_gbps
            else:
                peak_memory_bw = 10.0
            
            # Get operation efficiency
            efficiency = 0.8  # Default
            # Try to find matching op efficiency
            for op_type in ["gemm", "eigen", "reduction", "fft"]:
                if accel.compute.get_op_efficiency(op_type) > 0:
                    efficiency = accel.compute.get_op_efficiency(op_type)
                    break
        
        # Calculate arithmetic intensity
        bytes_accessed = task.required_memory_bytes
        if bytes_accessed > 0:
            arithmetic_intensity = task.required_compute_flops / bytes_accessed
        else:
            arithmetic_intensity = float('inf')
        
        # Roofline model
        compute_bound = peak_compute * efficiency
        memory_bound = peak_memory_bw * arithmetic_intensity
        
        actual = min(compute_bound, memory_bound)
        bottleneck = "compute" if compute_bound <= memory_bound else "memory"
        
        return RooflineAnalysis(
            task_id=task.task_id,
            accel_id=accel_id,
            arithmetic_intensity=arithmetic_intensity,
            peak_compute_gflops=peak_compute,
            peak_memory_bw_gbps=peak_memory_bw,
            compute_bound_gflops=compute_bound,
            memory_bound_gflops=memory_bound,
            actual_gflops=actual,
            bottleneck=bottleneck,
        )
    
    def _schedule_tasks_parallel(
        self,
        task_graph: TaskGraph,
        roofline_results: Dict[str, RooflineAnalysis],
        design_point: DesignPoint,
    ) -> ExecutionTimeline:
        """Schedule tasks with parallel execution across accelerators."""
        timeline = ExecutionTimeline(timeline_id=f"exec_{design_point.design_point_id}")
        
        # Track accelerator availability
        accel_available_at: Dict[str, float] = {accel.accel_id: 0.0 for accel in design_point.system_architecture.accelerators}
        accel_available_at["cpu"] = 0.0
        
        # Track task completion times
        task_completion: Dict[str, float] = {}
        
        # Topological sort for dependency order
        topo_order = []
        visited: Set[str] = set()
        
        def visit(task_id: str):
            if task_id in visited:
                return
            visited.add(task_id)
            task = task_graph.tasks.get(task_id)
            if task:
                for dep in task.dependencies:
                    visit(dep)
            topo_order.append(task_id)
        
        for task_id in task_graph.tasks:
            visit(task_id)
        
        # Schedule each task
        for task_id in topo_order:
            task = task_graph.tasks.get(task_id)
            if not task or not task.placement:
                continue
            
            accel_id = task.placement.accel_id
            roofline = roofline_results.get(task_id)
            
            # Compute latency
            if roofline:
                compute_latency_ms = roofline.latency_ms(task.required_compute_flops)
            else:
                compute_latency_ms = 0.0
            
            # Data movement latency (wait for dependencies + transfer)
            movement_latency_ms = 0.0
            for movement in task.input_movements:
                dep_task_id = movement.source_task
                dep_completion = task_completion.get(dep_task_id, 0.0)
                transfer_time = movement.transfer_time_ms
                movement_latency_ms = max(movement_latency_ms, dep_completion + transfer_time)
            
            # Earliest start time
            earliest_start = max(accel_available_at.get(accel_id, 0.0), movement_latency_ms)
            
            # Update schedule
            task.schedule.start_time_ms = earliest_start
            task.schedule.end_time_ms = earliest_start + compute_latency_ms
            
            # Update accelerator availability
            accel_available_at[accel_id] = task.schedule.end_time_ms
            
            # Track completion
            task_completion[task_id] = task.schedule.end_time_ms
            
            # Add events to timeline
            timeline.add_event(ExecutionEvent(
                timestamp_ms=task.schedule.start_time_ms,
                event_type="task_start",
                task_id=task_id,
                accel_id=accel_id,
                details={"flops": task.required_compute_flops},
            ))
            
            timeline.add_event(ExecutionEvent(
                timestamp_ms=task.schedule.end_time_ms,
                event_type="task_end",
                task_id=task_id,
                accel_id=accel_id,
                details={"latency_ms": compute_latency_ms},
            ))
            
            # Add data transfers
            for movement in task.input_movements:
                transfer_start = task_completion.get(movement.source_task, 0.0)
                transfer_end = transfer_start + movement.transfer_time_ms
                timeline.add_data_transfer(DataTransfer(
                    transfer_id=f"xfer_{movement.source_task}_{task_id}",
                    source_accel=movement.source_accel,
                    target_accel=movement.target_accel,
                    tensor_name=movement.tensor_name,
                    size_bytes=movement.size_bytes,
                    start_time_ms=transfer_start,
                    end_time_ms=transfer_end,
                    bandwidth_gbps=movement.bandwidth_gbps,
                ))
            
            # Add resource usage snapshot
            timeline.add_resource_usage(ResourceUsage(
                timestamp_ms=task.schedule.start_time_ms,
                accel_id=accel_id,
                compute_utilization=0.8 if roofline else 0.0,
                memory_used_bytes=task.required_memory_bytes,
                memory_total_bytes=80 * 1024 * 1024 * 1024,  # 80GB default
            ))
        
        return timeline
    
    def _calculate_metrics(
        self,
        timeline: ExecutionTimeline,
        design_point: Any,
        compute_graph: ComputeGraph,
    ) -> Any:
        summary = timeline.compute_summary()
        
        total_flops = compute_graph.total_flops()
        total_latency_ms = summary.get("total_duration_ms", 0.0)
        total_transfer_mb = summary.get("total_data_transferred_mb", 0.0)
        
        throughput_gops = total_flops / max(total_latency_ms, 1.0) / 1e6
        
        total_power_w = 0.0
        for accel in design_point.system_architecture.accelerators:
            total_power_w += accel.power.static_power_w
        
        for event in timeline.events:
            if event.event_type == "task_start":
                accel = design_point.system_architecture.get_accelerator(event.accel_id)
                if accel:
                    total_power_w += accel.power.compute_power_per_flop * 1e12
        
        energy_j = total_power_w * total_latency_ms / 1000.0
        
        peak_flops = design_point.system_architecture.total_compute_capacity("FP64")
        compute_efficiency = (total_flops / max(total_latency_ms, 1.0) * 1000.0) / max(peak_flops, 1.0)
        
        from dse_v2.dse.orchestrator import EvaluationResult
        return EvaluationResult(
            design_point_id=design_point.design_point_id,
            latency_ms=total_latency_ms,
            throughput_gops=throughput_gops,
            power_w=total_power_w,
            energy_j=energy_j,
            compute_efficiency=compute_efficiency,
            memory_efficiency=0.5,
            total_data_movement_mb=total_transfer_mb,
            communication_overhead_ms=summary.get("total_transfer_time_ms", 0.0),
            feasible=True,
        )



