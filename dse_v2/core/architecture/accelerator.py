#!/usr/bin/env python3
"""Level 1 Hardware IR: System architecture description.

This module defines the hardware abstraction layer for the DSE framework.
It provides a generic way to describe heterogeneous computing systems including:
- Compute accelerators (GPU, FPGA, ASIC, CIM, etc.)
- Memory hierarchy (L1/L2/HBM/DRAM)
- Interconnect topology (PCIe, NVLink, CXL, NoC)
- Power and area constraints

Design principles:
1. Accelerator-agnostic: No assumption about specific accelerator types
2. Composable: Systems are built from connected components
3. Self-describing: Accelerators declare their own capabilities
4. Distributed-ready: Support multi-node configurations from day 1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class MemoryLevel:
    """A single level in the memory hierarchy."""
    name: str
    capacity_bytes: int
    bandwidth_gbps: float
    latency_ns: float
    mem_type: str  # "SRAM", "DRAM", "HBM", "NVM", "CIM"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "capacity_bytes": self.capacity_bytes,
            "bandwidth_gbps": self.bandwidth_gbps,
            "latency_ns": self.latency_ns,
            "type": self.mem_type,
        }


@dataclass
class MemoryHierarchy:
    """Multi-level memory hierarchy for an accelerator."""
    levels: List[MemoryLevel] = field(default_factory=list)
    
    def add_level(self, level: MemoryLevel) -> MemoryHierarchy:
        self.levels.append(level)
        return self
    
    def get_level(self, name: str) -> Optional[MemoryLevel]:
        for level in self.levels:
            if level.name == name:
                return level
        return None
    
    def total_capacity_bytes(self) -> int:
        return sum(level.capacity_bytes for level in self.levels)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "levels": [level.to_dict() for level in self.levels],
            "total_capacity_bytes": self.total_capacity_bytes(),
        }


@dataclass
class PeerLink:
    """Direct link between two accelerators."""
    target_accel_id: str
    link_type: str  # "nvlink", "pcie", "cxl", "noc", "custom"
    bandwidth_gbps: float
    latency_us: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_accel_id": self.target_accel_id,
            "link_type": self.link_type,
            "bandwidth_gbps": self.bandwidth_gbps,
            "latency_us": self.latency_us,
        }


@dataclass
class HostLink:
    """Link from accelerator to host CPU."""
    link_type: str  # "pcie", "cxl", "custom"
    bandwidth_gbps: float
    latency_us: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "link_type": self.link_type,
            "bandwidth_gbps": self.bandwidth_gbps,
            "latency_us": self.latency_us,
        }


@dataclass
class CommunicationCapability:
    """Communication capabilities of an accelerator."""
    peer_links: List[PeerLink] = field(default_factory=list)
    host_link: Optional[HostLink] = None
    supported_primitives: List[str] = field(default_factory=list)
    
    def add_peer_link(self, link: PeerLink) -> CommunicationCapability:
        self.peer_links.append(link)
        return self
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "peer_links": [link.to_dict() for link in self.peer_links],
            "host_link": self.host_link.to_dict() if self.host_link else None,
            "supported_primitives": self.supported_primitives,
        }


@dataclass
class ComputeCapability:
    """Compute capabilities of an accelerator.
    
    Key design decision: Peak FLOPS is split by precision because
    different accelerators have very different precision support.
    For example, A100: FP64=9.7TF, TF32=156TF, FP16=312TF
    """
    peak_flops: Dict[str, float] = field(default_factory=dict)
    supported_ops: List[str] = field(default_factory=list)
    op_efficiency: Dict[str, float] = field(default_factory=dict)
    special_capabilities: List[str] = field(default_factory=list)
    
    def get_peak_flops(self, precision: str = "FP64") -> float:
        return self.peak_flops.get(precision, 0.0)
    
    def get_op_efficiency(self, op_type: str) -> float:
        return self.op_efficiency.get(op_type, 0.0)
    
    def supports_op(self, op_type: str) -> bool:
        return op_type in self.supported_ops
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "peak_flops": self.peak_flops,
            "supported_ops": self.supported_ops,
            "op_efficiency": self.op_efficiency,
            "special_capabilities": self.special_capabilities,
        }


@dataclass
class PowerModel:
    """Power consumption model for an accelerator."""
    static_power_w: float = 0.0
    compute_power_per_flop: float = 0.0
    memory_power_per_byte: float = 0.0
    communication_power_per_bit: float = 0.0
    power_states: List[str] = field(default_factory=lambda: ["active", "idle"])
    state_transition_latency_ms: Dict[str, float] = field(default_factory=dict)
    
    def estimate_power(
        self,
        flops_per_second: float,
        bytes_per_second: float,
        bits_per_second: float,
        state: str = "active",
    ) -> float:
        if state != "active":
            return self.static_power_w
        return (
            self.static_power_w
            + flops_per_second * self.compute_power_per_flop
            + bytes_per_second * self.memory_power_per_byte
            + bits_per_second * self.communication_power_per_bit
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "static_power_w": self.static_power_w,
            "compute_power_per_flop": self.compute_power_per_flop,
            "memory_power_per_byte": self.memory_power_per_byte,
            "communication_power_per_bit": self.communication_power_per_bit,
            "power_states": self.power_states,
        }


@dataclass
class Accelerator:
    """Generic accelerator description.
    
    This is the core abstraction for hardware in the DSE framework.
    It is completely generic - no assumption about accelerator type.
    """
    accel_id: str
    accel_type: str  # "gpu", "fpga", "asic", "cim", "cpu", "custom"
    
    compute: ComputeCapability = field(default_factory=ComputeCapability)
    memory: MemoryHierarchy = field(default_factory=MemoryHierarchy)
    communication: CommunicationCapability = field(default_factory=CommunicationCapability)
    power: PowerModel = field(default_factory=PowerModel)
    
    # Optional metadata
    vendor: str = ""
    model: str = ""
    version: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "accel_id": self.accel_id,
            "accel_type": self.accel_type,
            "vendor": self.vendor,
            "model": self.model,
            "version": self.version,
            "compute": self.compute.to_dict(),
            "memory": self.memory.to_dict(),
            "communication": self.communication.to_dict(),
            "power": self.power.to_dict(),
        }
    
    def can_execute(self, op_type: str) -> bool:
        return self.compute.supports_op(op_type)
    
    def estimated_latency_ms(self, flops: float, bytes_moved: float) -> float:
        compute_latency_ms = flops / max(self.compute.get_peak_flops(), 1.0) * 1000.0
        memory_latency_ms = bytes_moved * 8.0 / max(self.memory.levels[0].bandwidth_gbps if self.memory.levels else 1.0, 1.0) * 1000.0
        return max(compute_latency_ms, memory_latency_ms)


@dataclass
class InterconnectTopology:
    """Network topology connecting accelerators."""
    topology_type: str  # "mesh", "torus", "fat_tree", "bus", "custom"
    bandwidth_gbps: float
    latency_us: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "topology_type": self.topology_type,
            "bandwidth_gbps": self.bandwidth_gbps,
            "latency_us": self.latency_us,
        }


@dataclass
class SystemArchitecture:
    """Complete system architecture description.
    
    This is the top-level hardware configuration for DSE.
    It describes all accelerators and their interconnections.
    """
    system_id: str
    
    # Host configuration
    host_cpu_cores: int = 1
    host_memory_gb: float = 32.0
    
    # Accelerators in the system
    accelerators: List[Accelerator] = field(default_factory=list)
    
    # Interconnect
    interconnect: Optional[InterconnectTopology] = None
    
    # Global constraints
    max_power_w: float = 1000.0
    max_area_mm2: float = 1000.0
    
    def add_accelerator(self, accel: Accelerator) -> SystemArchitecture:
        self.accelerators.append(accel)
        return self
    
    def get_accelerator(self, accel_id: str) -> Optional[Accelerator]:
        for accel in self.accelerators:
            if accel.accel_id == accel_id:
                return accel
        return None
    
    def get_accelerators_by_type(self, accel_type: str) -> List[Accelerator]:
        return [accel for accel in self.accelerators if accel.accel_type == accel_type]
    
    def total_compute_capacity(self, precision: str = "FP64") -> float:
        return sum(accel.compute.get_peak_flops(precision) for accel in self.accelerators)
    
    def total_memory_capacity_bytes(self) -> int:
        return sum(accel.memory.total_capacity_bytes() for accel in self.accelerators)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "system_id": self.system_id,
            "host_cpu_cores": self.host_cpu_cores,
            "host_memory_gb": self.host_memory_gb,
            "accelerators": [accel.to_dict() for accel in self.accelerators],
            "interconnect": self.interconnect.to_dict() if self.interconnect else None,
            "max_power_w": self.max_power_w,
            "max_area_mm2": self.max_area_mm2,
        }


# Pre-defined accelerator templates for common hardware

def create_gpu_a100(accel_id: str = "gpu-0") -> Accelerator:
    return Accelerator(
        accel_id=accel_id,
        accel_type="gpu",
        vendor="NVIDIA",
        model="A100",
        compute=ComputeCapability(
            peak_flops={"FP64": 9.7e12, "FP32": 19.5e12, "TF32": 156e12, "FP16": 312e12},
            supported_ops=["gemm", "conv2d", "batch_norm", "softmax", "attention", "fft", "eigen"],
            op_efficiency={"gemm": 0.90, "conv2d": 0.85, "fft": 0.60, "eigen": 0.20},
            special_capabilities=["tensor_cores", "sparse_tensor_cores", "nvlink"],
        ),
        memory=MemoryHierarchy([
            MemoryLevel("L1", 192*1024, 2000, 1, "SRAM"),
            MemoryLevel("L2", 40*1024*1024, 2000, 10, "SRAM"),
            MemoryLevel("HBM", 80*1024*1024*1024, 2000, 100, "HBM"),
        ]),
        communication=CommunicationCapability(
            peer_links=[PeerLink("nvlink_peer", "nvlink", 600, 1.0)],
            host_link=HostLink("pcie4", 64, 5.0),
            supported_primitives=["send", "recv", "broadcast", "allreduce"],
        ),
        power=PowerModel(
            static_power_w=50,
            compute_power_per_flop=1.5e-13,
            memory_power_per_byte=2.0e-12,
            communication_power_per_bit=1.0e-11,
        ),
    )


def create_fpga_u280(accel_id: str = "fpga-0") -> Accelerator:
    return Accelerator(
        accel_id=accel_id,
        accel_type="fpga",
        vendor="Xilinx",
        model="Alveo U280",
        compute=ComputeCapability(
            peak_flops={"FP64": 1.0e12, "FP32": 8.0e12, "INT8": 32.0e12},
            supported_ops=["gemm", "fft", "conv2d", "custom"],
            op_efficiency={"gemm": 0.95, "fft": 0.90, "custom": 0.95},
            special_capabilities=["reconfigurable", "streaming", "low_latency_io"],
        ),
        memory=MemoryHierarchy([
            MemoryLevel("BRAM", 30*1024*1024, 1000, 5, "SRAM"),
            MemoryLevel("HBM", 8*1024*1024*1024, 460, 50, "HBM"),
            MemoryLevel("DRAM", 32*1024*1024*1024, 77, 100, "DRAM"),
        ]),
        communication=CommunicationCapability(
            peer_links=[],
            host_link=HostLink("pcie4", 64, 5.0),
            supported_primitives=["send", "recv"],
        ),
        power=PowerModel(
            static_power_w=25,
            compute_power_per_flop=5.0e-14,
            memory_power_per_byte=1.0e-12,
            communication_power_per_bit=5.0e-12,
        ),
    )


def create_cim_array(accel_id: str = "cim-0") -> Accelerator:
    return Accelerator(
        accel_id=accel_id,
        accel_type="cim",
        vendor="Custom",
        model="CIM_Array",
        compute=ComputeCapability(
            peak_flops={"FP64": 0.1e12, "FP32": 0.5e12},
            supported_ops=["gemm", "vector_add", "elementwise"],
            op_efficiency={"gemm": 0.95, "vector_add": 0.90},
            special_capabilities=["in_memory_compute", "analog_compute", "low_precision"],
        ),
        memory=MemoryHierarchy([
            MemoryLevel("CIM_Array", 1*1024*1024, 10000, 0.1, "CIM"),
            MemoryLevel("SRAM", 64*1024*1024, 500, 10, "SRAM"),
        ]),
        communication=CommunicationCapability(
            peer_links=[],
            host_link=HostLink("custom", 32, 10.0),
            supported_primitives=["send", "recv"],
        ),
        power=PowerModel(
            static_power_w=5,
            compute_power_per_flop=1.0e-15,
            memory_power_per_byte=1.0e-13,
            communication_power_per_bit=1.0e-11,
        ),
    )


# Example: Create a heterogeneous system
def create_example_system() -> SystemArchitecture:
    return SystemArchitecture(
        system_id="heterogeneous_demo",
        host_cpu_cores=64,
        host_memory_gb=512.0,
        accelerators=[
            create_gpu_a100("gpu-0"),
            create_fpga_u280("fpga-0"),
            create_cim_array("cim-0"),
        ],
        interconnect=InterconnectTopology("mesh", 600, 1.0),
        max_power_w=1000.0,
        max_area_mm2=2000.0,
    )