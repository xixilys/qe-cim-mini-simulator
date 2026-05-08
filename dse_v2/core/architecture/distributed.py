#!/usr/bin/env python3
"""Distributed extension for multi-node DSE.

Extends the single-node system architecture to support distributed clusters.
Key additions:
1. Node abstraction (physical machine)
2. Network topology (rack, cluster, datacenter)
3. Distributed task placement
4. Communication cost modeling for multi-node

Design principles:
1. Transparent: Single-node code works without changes
2. Layered: Network topology is separate from accelerator topology
3. Cost-aware: Inter-node communication is explicitly modeled
4. Fault-tolerant: Failure domains are tracked
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from dse_v2.core.architecture.accelerator import SystemArchitecture, Accelerator


@dataclass
class NetworkLink:
    """Network link between two nodes."""
    source_node: str
    target_node: str
    link_type: str  # "ethernet", "infiniband", "nvlink", "custom"
    bandwidth_gbps: float
    latency_us: float
    
    def transfer_time_ms(self, size_bytes: int) -> float:
        return (size_bytes * 8.0 / max(self.bandwidth_gbps, 1.0)) / 1000.0 + self.latency_us / 1000.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_node": self.source_node,
            "target_node": self.target_node,
            "link_type": self.link_type,
            "bandwidth_gbps": self.bandwidth_gbps,
            "latency_us": self.latency_us,
        }


@dataclass
class Node:
    """A physical node (machine) in the distributed system.
    
    Each node contains:
    - Host CPU and memory
    - Local accelerators
    - Network interfaces
    """
    node_id: str
    
    # Host configuration
    host_cpu_cores: int = 64
    host_memory_gb: float = 512.0
    
    # Local system architecture (accelerators on this node)
    local_system: SystemArchitecture = field(default_factory=lambda: SystemArchitecture("local"))
    
    # Network position
    rack_id: str = "rack-0"
    cluster_id: str = "cluster-0"
    
    # Failure domain
    failure_domain: str = "node"  # "node", "rack", "cluster"
    
    # Network links to other nodes
    network_links: List[NetworkLink] = field(default_factory=list)
    
    def add_accelerator(self, accel: Accelerator) -> Node:
        self.local_system.add_accelerator(accel)
        return self
    
    def add_network_link(self, link: NetworkLink) -> Node:
        self.network_links.append(link)
        return self
    
    def get_link_to(self, target_node_id: str) -> Optional[NetworkLink]:
        for link in self.network_links:
            if link.target_node == target_node_id:
                return link
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "host_cpu_cores": self.host_cpu_cores,
            "host_memory_gb": self.host_memory_gb,
            "local_system": self.local_system.to_dict(),
            "rack_id": self.rack_id,
            "cluster_id": self.cluster_id,
            "failure_domain": self.failure_domain,
            "network_links": [link.to_dict() for link in self.network_links],
        }


@dataclass
class DistributedSystem:
    """Distributed system spanning multiple nodes.
    
    This is the top-level architecture for multi-node DSE.
    """
    system_id: str
    nodes: Dict[str, Node] = field(default_factory=dict)
    
    # Global network topology
    network_topology: str = "mesh"  # "mesh", "torus", "fat_tree", "custom"
    
    def add_node(self, node: Node) -> DistributedSystem:
        self.nodes[node.node_id] = node
        return self
    
    def get_node(self, node_id: str) -> Optional[Node]:
        return self.nodes.get(node_id)
    
    def get_nodes_in_rack(self, rack_id: str) -> List[Node]:
        return [node for node in self.nodes.values() if node.rack_id == rack_id]
    
    def get_all_accelerators(self) -> List[Tuple[str, Accelerator]]:
        """Get all accelerators with their node IDs."""
        result = []
        for node_id, node in self.nodes.items():
            for accel in node.local_system.accelerators:
                result.append((node_id, accel))
        return result
    
    def get_accelerator(self, node_id: str, accel_id: str) -> Optional[Accelerator]:
        node = self.nodes.get(node_id)
        if node:
            return node.local_system.get_accelerator(accel_id)
        return None
    
    def get_network_distance(self, node1_id: str, node2_id: str) -> int:
        """Get network distance in hops between two nodes."""
        if node1_id == node2_id:
            return 0
        
        # BFS to find shortest path
        visited: Set[str] = {node1_id}
        queue: List[Tuple[str, int]] = [(node1_id, 0)]
        
        while queue:
            current, distance = queue.pop(0)
            node = self.nodes.get(current)
            if not node:
                continue
            
            for link in node.network_links:
                if link.target_node == node2_id:
                    return distance + 1
                if link.target_node not in visited:
                    visited.add(link.target_node)
                    queue.append((link.target_node, distance + 1))
        
        return float('inf')  # Not connected
    
    def get_communication_cost(
        self,
        node1_id: str,
        node2_id: str,
        data_size_bytes: int,
    ) -> float:
        """Get communication cost (time in ms) between two nodes."""
        if node1_id == node2_id:
            return 0.0  # Same node, no network cost
        
        node1 = self.nodes.get(node1_id)
        if not node1:
            return float('inf')
        
        link = node1.get_link_to(node2_id)
        if link:
            return link.transfer_time_ms(data_size_bytes)
        
        # No direct link, use multi-hop estimate
        distance = self.get_network_distance(node1_id, node2_id)
        if distance == float('inf'):
            return float('inf')
        
        # Estimate based on average bandwidth
        avg_bandwidth = 100.0  # Default 100 Gbps
        return (data_size_bytes * 8.0 / avg_bandwidth) / 1000.0 * distance
    
    def total_compute_capacity(self, precision: str = "FP64") -> float:
        return sum(
            node.local_system.total_compute_capacity(precision)
            for node in self.nodes.values()
        )
    
    def total_memory_capacity_bytes(self) -> int:
        return sum(
            node.local_system.total_memory_capacity_bytes()
            for node in self.nodes.values()
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "system_id": self.system_id,
            "network_topology": self.network_topology,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "total_nodes": len(self.nodes),
            "total_accelerators": len(self.get_all_accelerators()),
        }


# Factory functions for common distributed configurations

def create_single_node_system(
    node_id: str = "node-0",
    accelerators: Optional[List[Accelerator]] = None,
) -> DistributedSystem:
    """Create a single-node system (backward compatible)."""
    node = Node(
        node_id=node_id,
        host_cpu_cores=64,
        host_memory_gb=512.0,
    )
    
    if accelerators:
        for accel in accelerators:
            node.add_accelerator(accel)
    
    return DistributedSystem(
        system_id=f"single_node_{node_id}",
        nodes={node_id: node},
    )


def create_dual_node_system(
    node1_id: str = "node-0",
    node2_id: str = "node-1",
    inter_node_bandwidth_gbps: float = 200.0,  # InfiniBand HDR
) -> DistributedSystem:
    """Create a dual-node system with high-speed interconnect."""
    node1 = Node(node_id=node1_id, rack_id="rack-0")
    node2 = Node(node_id=node2_id, rack_id="rack-0")
    
    # Add network links
    link1 = NetworkLink(
        source_node=node1_id,
        target_node=node2_id,
        link_type="infiniband",
        bandwidth_gbps=inter_node_bandwidth_gbps,
        latency_us=1.0,
    )
    link2 = NetworkLink(
        source_node=node2_id,
        target_node=node1_id,
        link_type="infiniband",
        bandwidth_gbps=inter_node_bandwidth_gbps,
        latency_us=1.0,
    )
    
    node1.add_network_link(link1)
    node2.add_network_link(link2)
    
    return DistributedSystem(
        system_id=f"dual_node_{node1_id}_{node2_id}",
        nodes={node1_id: node1, node2_id: node2},
    )


def create_cluster_system(
    num_nodes: int = 4,
    gpus_per_node: int = 8,
    inter_node_bandwidth_gbps: float = 200.0,
) -> DistributedSystem:
    """Create a cluster with multiple GPU nodes."""
    from dse_v2.core.architecture.accelerator import create_gpu_a100
    
    system = DistributedSystem(
        system_id=f"cluster_{num_nodes}x{gpus_per_node}gpu",
        network_topology="fat_tree",
    )
    
    for i in range(num_nodes):
        node_id = f"node-{i}"
        node = Node(
            node_id=node_id,
            rack_id=f"rack-{i // 2}",
            host_cpu_cores=128,
            host_memory_gb=1024.0,
        )
        
        # Add GPUs
        for j in range(gpus_per_node):
            gpu = create_gpu_a100(f"gpu-{i}-{j}")
            # Add NVLink between GPUs in same node
            for k in range(j):
                gpu.communication.peer_links.append(
                    NetworkLink(
                        source_node=node_id,
                        target_node=node_id,
                        link_type="nvlink",
                        bandwidth_gbps=600.0,
                        latency_us=0.5,
                    )
                )
            node.add_accelerator(gpu)
        
        system.add_node(node)
    
    # Add inter-node network links
    for i in range(num_nodes):
        for j in range(i + 1, num_nodes):
            node1_id = f"node-{i}"
            node2_id = f"node-{j}"
            
            link1 = NetworkLink(
                source_node=node1_id,
                target_node=node2_id,
                link_type="infiniband",
                bandwidth_gbps=inter_node_bandwidth_gbps,
                latency_us=1.0,
            )
            link2 = NetworkLink(
                source_node=node2_id,
                target_node=node1_id,
                link_type="infiniband",
                bandwidth_gbps=inter_node_bandwidth_gbps,
                latency_us=1.0,
            )
            
            system.nodes[node1_id].add_network_link(link1)
            system.nodes[node2_id].add_network_link(link2)
    
    return system