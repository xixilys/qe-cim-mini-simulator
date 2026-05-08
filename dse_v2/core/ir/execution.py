#!/usr/bin/env python3
"""Level 0 Execution IR: Concrete execution timeline.

Represents the actual execution of tasks on hardware with precise timing.
This is the lowest level of the IR stack, used for simulation and validation.

Key design decisions:
1. Timeline-based: Events happen at specific timestamps
2. Resource-tracking: Hardware resources are tracked over time
3. Data-movement-tracking: All data transfers are explicitly recorded
4. Observable: Can be used to generate traces and visualizations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ExecutionEvent:
    """A single event in the execution timeline."""
    timestamp_ms: float
    event_type: str  # "task_start", "task_end", "data_transfer_start", "data_transfer_end"
    task_id: str
    accel_id: str
    
    # Optional details
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_ms": self.timestamp_ms,
            "event_type": self.event_type,
            "task_id": self.task_id,
            "accel_id": self.accel_id,
            "details": self.details,
        }


@dataclass
class ResourceUsage:
    """Resource usage at a point in time."""
    timestamp_ms: float
    accel_id: str
    
    # Compute utilization (0.0 - 1.0)
    compute_utilization: float = 0.0
    
    # Memory usage (bytes)
    memory_used_bytes: int = 0
    memory_total_bytes: int = 0
    
    # Bandwidth utilization (0.0 - 1.0)
    bandwidth_utilization: float = 0.0
    
    @property
    def memory_utilization(self) -> float:
        if self.memory_total_bytes == 0:
            return 0.0
        return self.memory_used_bytes / self.memory_total_bytes
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_ms": self.timestamp_ms,
            "accel_id": self.accel_id,
            "compute_utilization": self.compute_utilization,
            "memory_used_bytes": self.memory_used_bytes,
            "memory_total_bytes": self.memory_total_bytes,
            "memory_utilization": self.memory_utilization,
            "bandwidth_utilization": self.bandwidth_utilization,
        }


@dataclass
class DataTransfer:
    """Recorded data transfer between accelerators."""
    transfer_id: str
    source_accel: str
    target_accel: str
    tensor_name: str
    size_bytes: int
    
    start_time_ms: float
    end_time_ms: float
    bandwidth_gbps: float
    
    @property
    def duration_ms(self) -> float:
        return self.end_time_ms - self.start_time_ms
    
    @property
    def effective_bandwidth_gbps(self) -> float:
        if self.duration_ms <= 0:
            return 0.0
        return (self.size_bytes * 8.0) / (self.duration_ms / 1000.0) / 1e9
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "transfer_id": self.transfer_id,
            "source_accel": self.source_accel,
            "target_accel": self.target_accel,
            "tensor_name": self.tensor_name,
            "size_bytes": self.size_bytes,
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "duration_ms": self.duration_ms,
            "effective_bandwidth_gbps": self.effective_bandwidth_gbps,
        }


@dataclass
class ExecutionTimeline:
    """Complete execution timeline for a workload.
    
    Records all events, resource usage, and data transfers during execution.
    """
    timeline_id: str
    events: List[ExecutionEvent] = field(default_factory=list)
    resource_usage: List[ResourceUsage] = field(default_factory=list)
    data_transfers: List[DataTransfer] = field(default_factory=list)
    
    # Summary statistics
    total_duration_ms: float = 0.0
    total_compute_time_ms: float = 0.0
    total_transfer_time_ms: float = 0.0
    total_idle_time_ms: float = 0.0
    
    def add_event(self, event: ExecutionEvent) -> ExecutionTimeline:
        self.events.append(event)
        self.events.sort(key=lambda e: e.timestamp_ms)
        return self
    
    def add_resource_usage(self, usage: ResourceUsage) -> ExecutionTimeline:
        self.resource_usage.append(usage)
        return self
    
    def add_data_transfer(self, transfer: DataTransfer) -> ExecutionTimeline:
        self.data_transfers.append(transfer)
        return self
    
    def get_events_on_accelerator(self, accel_id: str) -> List[ExecutionEvent]:
        return [e for e in self.events if e.accel_id == accel_id]
    
    def get_resource_usage_on_accelerator(self, accel_id: str) -> List[ResourceUsage]:
        return [u for u in self.resource_usage if u.accel_id == accel_id]
    
    def get_transfers_between(self, source: str, target: str) -> List[DataTransfer]:
        return [
            t for t in self.data_transfers
            if t.source_accel == source and t.target_accel == target
        ]
    
    def compute_summary(self) -> Dict[str, Any]:
        if not self.events:
            return {}
        
        # Find time range
        start_time = min(e.timestamp_ms for e in self.events)
        end_time = max(e.timestamp_ms for e in self.events)
        self.total_duration_ms = end_time - start_time
        
        # Compute total transfer time
        self.total_transfer_time_ms = sum(t.duration_ms for t in self.data_transfers)
        
        # Compute total compute time (sum of task durations)
        task_durations: Dict[str, float] = {}
        for event in self.events:
            if event.event_type == "task_start":
                task_durations[event.task_id] = -event.timestamp_ms
            elif event.event_type == "task_end":
                if event.task_id in task_durations:
                    task_durations[event.task_id] += event.timestamp_ms
        
        self.total_compute_time_ms = sum(d for d in task_durations.values() if d > 0)
        
        # Idle time is the difference
        self.total_idle_time_ms = max(0, self.total_duration_ms - self.total_compute_time_ms - self.total_transfer_time_ms)
        
        return {
            "total_duration_ms": self.total_duration_ms,
            "total_compute_time_ms": self.total_compute_time_ms,
            "total_transfer_time_ms": self.total_transfer_time_ms,
            "total_idle_time_ms": self.total_idle_time_ms,
            "num_events": len(self.events),
            "num_transfers": len(self.data_transfers),
            "total_data_transferred_mb": sum(t.size_bytes for t in self.data_transfers) / (1024.0 * 1024.0),
        }
    
    def to_dict(self) -> Dict[str, Any]:
        summary = self.compute_summary()
        return {
            "timeline_id": self.timeline_id,
            "events": [e.to_dict() for e in self.events],
            "resource_usage": [u.to_dict() for u in self.resource_usage],
            "data_transfers": [t.to_dict() for t in self.data_transfers],
            "summary": summary,
        }


# Example: Create a simple execution timeline
def create_example_timeline() -> ExecutionTimeline:
    timeline = ExecutionTimeline(timeline_id="example_execution")
    
    # Task 1 starts on GPU at t=0
    timeline.add_event(ExecutionEvent(
        timestamp_ms=0.0,
        event_type="task_start",
        task_id="gemm",
        accel_id="gpu-0",
    ))
    
    # Task 1 ends at t=10
    timeline.add_event(ExecutionEvent(
        timestamp_ms=10.0,
        event_type="task_end",
        task_id="gemm",
        accel_id="gpu-0",
    ))
    
    # Data transfer from GPU to CPU at t=10
    timeline.add_data_transfer(DataTransfer(
        transfer_id="xfer_1",
        source_accel="gpu-0",
        target_accel="cpu",
        tensor_name="C",
        size_bytes=1024*1024*100,  # 100MB
        start_time_ms=10.0,
        end_time_ms=12.5,
        bandwidth_gbps=64.0,
    ))
    
    # Task 2 starts on CPU at t=12.5
    timeline.add_event(ExecutionEvent(
        timestamp_ms=12.5,
        event_type="task_start",
        task_id="post_process",
        accel_id="cpu",
    ))
    
    # Task 2 ends at t=15
    timeline.add_event(ExecutionEvent(
        timestamp_ms=15.0,
        event_type="task_end",
        task_id="post_process",
        accel_id="cpu",
    ))
    
    # Resource usage snapshots
    timeline.add_resource_usage(ResourceUsage(
        timestamp_ms=5.0,
        accel_id="gpu-0",
        compute_utilization=0.95,
        memory_used_bytes=8*1024*1024*1024,
        memory_total_bytes=80*1024*1024*1024,
    ))
    
    return timeline