#!/usr/bin/env python3
"""Level 2 Task Graph IR: Task-level parallel execution graph.

Maps compute graph nodes to tasks with placement, scheduling, and resource allocation.
This is the bridge between the application-level compute graph and hardware execution.

Key design decisions:
1. Task granularity: Each task can be a single compute node or a fused subgraph
2. Placement-aware: Tasks are mapped to specific accelerators
3. Schedule-aware: Tasks have timing information (start, end, dependencies)
4. Resource-aware: Tasks consume accelerator resources
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode


@dataclass
class TaskPlacement:
    """Placement of a task on a specific accelerator."""
    accel_id: str
    task_id: str
    
    # Resource allocation
    memory_bytes: int = 0
    compute_units: int = 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "accel_id": self.accel_id,
            "task_id": self.task_id,
            "memory_bytes": self.memory_bytes,
            "compute_units": self.compute_units,
        }


@dataclass
class TaskSchedule:
    """Schedule information for a task."""
    start_time_ms: float = 0.0
    end_time_ms: float = 0.0
    
    @property
    def duration_ms(self) -> float:
        return self.end_time_ms - self.start_time_ms
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "duration_ms": self.duration_ms,
        }


@dataclass
class DataMovement:
    """Data movement between tasks on different accelerators."""
    source_task: str
    target_task: str
    tensor_name: str
    size_bytes: int
    
    # Movement details
    source_accel: str
    target_accel: str
    bandwidth_gbps: float
    latency_ms: float
    
    @property
    def transfer_time_ms(self) -> float:
        return (self.size_bytes * 8.0 / max(self.bandwidth_gbps, 1.0)) / 1000.0 + self.latency_ms
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_task": self.source_task,
            "target_task": self.target_task,
            "tensor_name": self.tensor_name,
            "size_bytes": self.size_bytes,
            "source_accel": self.source_accel,
            "target_accel": self.target_accel,
            "transfer_time_ms": self.transfer_time_ms,
        }


@dataclass
class Task:
    """A task in the task graph.
    
    A task can represent:
    - A single compute node
    - A fused group of compute nodes
    - A control flow operation (loop, condition)
    """
    task_id: str
    task_type: str  # "compute", "fused", "control"
    
    # Source compute nodes (if mapped from compute graph)
    source_nodes: List[str] = field(default_factory=list)
    
    # Placement
    placement: Optional[TaskPlacement] = None
    
    # Schedule
    schedule: TaskSchedule = field(default_factory=TaskSchedule)
    
    # Resource requirements
    required_memory_bytes: int = 0
    required_compute_flops: float = 0.0
    
    # Dependencies
    dependencies: List[str] = field(default_factory=list)  # Task IDs this task depends on
    
    # Data movements (inputs from other accelerators)
    input_movements: List[DataMovement] = field(default_factory=list)
    
    # Data movements (outputs to other accelerators)
    output_movements: List[DataMovement] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "source_nodes": self.source_nodes,
            "placement": self.placement.to_dict() if self.placement else None,
            "schedule": self.schedule.to_dict(),
            "required_memory_bytes": self.required_memory_bytes,
            "required_compute_flops": self.required_compute_flops,
            "dependencies": self.dependencies,
            "input_movements": [m.to_dict() for m in self.input_movements],
            "output_movements": [m.to_dict() for m in self.output_movements],
        }


@dataclass
class TaskGraph:
    """Task-level execution graph.
    
    Maps compute graph to executable tasks with placement and scheduling.
    """
    graph_id: str
    tasks: Dict[str, Task] = field(default_factory=dict)
    
    # Mapping from compute graph nodes to tasks
    node_to_task: Dict[str, str] = field(default_factory=dict)
    
    # Global schedule
    makespan_ms: float = 0.0
    total_data_movement_mb: float = 0.0
    
    def add_task(self, task: Task) -> TaskGraph:
        self.tasks[task.task_id] = task
        return self
    
    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)
    
    def tasks_on_accelerator(self, accel_id: str) -> List[Task]:
        return [
            task for task in self.tasks.values()
            if task.placement and task.placement.accel_id == accel_id
        ]
    
    def critical_path(self) -> List[str]:
        """Find the critical path (longest dependency chain)."""
        # Simple critical path calculation
        earliest_start: Dict[str, float] = {}
        
        def get_earliest_start(task_id: str) -> float:
            if task_id in earliest_start:
                return earliest_start[task_id]
            
            task = self.tasks[task_id]
            if not task.dependencies:
                earliest_start[task_id] = 0.0
                return 0.0
            
            max_end = 0.0
            for dep_id in task.dependencies:
                dep = self.tasks[dep_id]
                dep_end = get_earliest_start(dep_id) + dep.schedule.duration_ms
                max_end = max(max_end, dep_end)
            
            earliest_start[task_id] = max_end
            return max_end
        
        # Calculate earliest start for all tasks
        for task_id in self.tasks:
            get_earliest_start(task_id)
        
        # Find the task with latest end time
        latest_end = 0.0
        last_task = ""
        for task_id, start in earliest_start.items():
            end = start + self.tasks[task_id].schedule.duration_ms
            if end > latest_end:
                latest_end = end
                last_task = task_id
        
        # Backtrack to find critical path
        path = []
        current = last_task
        while current:
            path.append(current)
            task = self.tasks[current]
            if not task.dependencies:
                break
            # Find the dependency that determines the start time
            max_end = 0.0
            critical_dep = ""
            for dep_id in task.dependencies:
                dep = self.tasks[dep_id]
                dep_end = earliest_start[dep_id] + dep.schedule.duration_ms
                if dep_end > max_end:
                    max_end = dep_end
                    critical_dep = dep_id
            current = critical_dep
        
        return list(reversed(path))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "node_to_task": self.node_to_task,
            "makespan_ms": self.makespan_ms,
            "total_data_movement_mb": self.total_data_movement_mb,
        }


# Example: Map compute graph to task graph
def map_compute_to_tasks(
    compute_graph: ComputeGraph,
    mapping: Dict[str, str],  # node_id -> accel_id
    accel_bandwidths: Dict[Tuple[str, str], float],  # (src, dst) -> gbps
) -> TaskGraph:
    """Map a compute graph to a task graph with given accelerator mapping."""
    task_graph = TaskGraph(graph_id=f"tasks_{compute_graph.graph_id}")
    
    # Create one task per compute node
    for node_id, node in compute_graph.nodes.items():
        accel_id = mapping.get(node_id, "cpu")
        
        task = Task(
            task_id=f"task_{node_id}",
            task_type="compute",
            source_nodes=[node_id],
            placement=TaskPlacement(
                accel_id=accel_id,
                task_id=f"task_{node_id}",
                memory_bytes=int(node.estimated_memory_bytes),
            ),
            required_memory_bytes=int(node.estimated_memory_bytes),
            required_compute_flops=node.estimated_flops,
        )
        task_graph.add_task(task)
        task_graph.node_to_task[node_id] = task.task_id
    
    # Add dependencies based on compute graph edges
    for edge in compute_graph.edges:
        source_task = task_graph.node_to_task.get(edge.source_node)
        target_task = task_graph.node_to_task.get(edge.target_node)
        if source_task and target_task:
            task_graph.tasks[target_task].dependencies.append(source_task)
            
            # Add data movement if tasks are on different accelerators
            source_accel = mapping.get(edge.source_node, "cpu")
            target_accel = mapping.get(edge.target_node, "cpu")
            if source_accel != target_accel:
                tensor_size = edge.tensor_spec.size_bytes() if edge.tensor_spec else 0
                bandwidth = accel_bandwidths.get((source_accel, target_accel), 64.0)
                
                movement = DataMovement(
                    source_task=source_task,
                    target_task=target_task,
                    tensor_name=edge.tensor_name,
                    size_bytes=tensor_size,
                    source_accel=source_accel,
                    target_accel=target_accel,
                    bandwidth_gbps=bandwidth,
                    latency_ms=0.01,
                )
                task_graph.tasks[target_task].input_movements.append(movement)
    
    return task_graph