#!/usr/bin/env python3
"""TLM Backend - Transaction Level Model evaluator.

Integrates the existing PythonTLM model from dse_v2.models.mid.python_tlm
into the generic DSE framework.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.dse.orchestrator import DesignPoint


class TLMEvaluator:
    """Transaction Level Model evaluator.
    
    Wraps the existing PythonTLM model to provide mid-fidelity evaluation.
    """
    
    def __init__(self, clock_mhz: float = 250.0, pcie_bw_gbps: float = 64.0, dram_bw_gbps: float = 128.0):
        self.clock_mhz = clock_mhz
        self.pcie_bw_gbps = pcie_bw_gbps
        self.dram_bw_gbps = dram_bw_gbps
        self._tlm = None
    
    def _get_tlm(self):
        if self._tlm is None:
            from dse_v2.models.mid.python_tlm import PythonTLM
            self._tlm = PythonTLM(
                clock_mhz=self.clock_mhz,
                pcie_bw_gbps=self.pcie_bw_gbps,
                dram_bw_gbps=self.dram_bw_gbps,
            )
        return self._tlm
    
    def evaluate(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
    ) -> Dict[str, Any]:
        """Evaluate design point using TLM model."""
        tlm = self._get_tlm()
        
        # Convert design point to TLM format
        tlm_design_point = self._convert_design_point(design_point)
        
        # Extract workload parameters from compute graph
        workload = self._extract_workload(compute_graph)
        
        # Run TLM evaluation
        result = tlm.run_episode(tlm_design_point, workload)
        
        # Convert TLM result to standard format
        return self._convert_result(result, design_point.design_point_id)
    
    def _convert_design_point(self, design_point: DesignPoint) -> Dict[str, Any]:
        """Convert generic DesignPoint to TLM format."""
        arch = {
            "family": "F1",
            "clock_mhz": self.clock_mhz,
            "parallel_units": 4,
            "gemm_tiles": 4,
            "eigen_tiles": 1,
            "local_mem_kb": 512,
            "max_power_w": 75.0,
            "pcie_bw_gbps": self.pcie_bw_gbps,
            "dram_bw_gbps": self.dram_bw_gbps,
        }
        
        # Override with actual accelerator specs if available
        if design_point.system_architecture.accelerators:
            accel = design_point.system_architecture.accelerators[0]
            if accel.accel_type == "gpu":
                arch["family"] = "F3"
                arch["parallel_units"] = 16
            elif accel.accel_type == "fpga":
                arch["family"] = "F1"
                arch["parallel_units"] = 4
            elif accel.accel_type == "cim":
                arch["family"] = "F4"
                arch["parallel_units"] = 2
        
        return {
            "architecture": arch,
            "mapping": design_point.task_mapping,
            "dataflow": {"double_buffer": True, "overlap_dma_compute": True},
        }
    
    def _extract_workload(self, compute_graph: ComputeGraph) -> Dict[str, Any]:
        """Extract workload parameters from compute graph."""
        metadata = compute_graph.metadata
        
        # Get generic dimensions from metadata or estimate from nodes.
        problem_size = metadata.get("problem_size")
        feature_size = metadata.get("feature_size")
        batch_size = metadata.get("batch_size")
        if problem_size is None or feature_size is None or batch_size is None:
            total_flops = sum(max(0.0, float(node.estimated_flops)) for node in compute_graph.nodes.values())
            total_bytes = sum(max(0.0, float(node.estimated_memory_bytes)) for node in compute_graph.nodes.values())
            problem_size = int(max(1.0, (total_flops / max(total_bytes, 1.0)) * 1024.0))
            feature_size = int(max(16.0, len(compute_graph.nodes) * 64.0))
            batch_size = int(max(1.0, len(compute_graph.nodes)))
        iterations = metadata.get("iterations", metadata.get("total_iterations", 10))
        
        return {
            "problem_size": problem_size,
            "feature_size": feature_size,
            "batch_size": batch_size,
            "iterations": iterations,
            "total_iterations": iterations,
        }
    
    def _convert_result(self, tlm_result: Any, design_point_id: str) -> Dict[str, Any]:
        """Convert TLM result to standard evaluation format."""
        metrics = tlm_result.metrics if hasattr(tlm_result, 'metrics') else tlm_result.get('metrics', {})
        
        return {
            "design_point_id": design_point_id,
            "latency_ms": metrics.get('latency_ms', 0.0),
            "throughput_gops": metrics.get('throughput_gops', 0.0),
            "power_w": metrics.get('power_w', 0.0),
            "energy_j": metrics.get('power_w', 0.0) * metrics.get('latency_ms', 0.0) / 1000.0,
            "compute_efficiency": 0.0,
            "memory_efficiency": 0.0,
            "total_data_movement_mb": 0.0,
            "communication_overhead_ms": metrics.get('data_transfer_ms', 0.0),
            "feasible": tlm_result.status == 'passed' if hasattr(tlm_result, 'status') else tlm_result.get('status') == 'passed',
            "tlm_details": {
                "family": tlm_result.family if hasattr(tlm_result, 'family') else tlm_result.get('family'),
                "status": tlm_result.status if hasattr(tlm_result, 'status') else tlm_result.get('status'),
                "confidence": tlm_result.confidence if hasattr(tlm_result, 'confidence') else tlm_result.get('confidence'),
                "promotion_score": tlm_result.promotion_score if hasattr(tlm_result, 'promotion_score') else tlm_result.get('promotion_score'),
                "resource_utilization": tlm_result.resource_utilization if hasattr(tlm_result, 'resource_utilization') else tlm_result.get('resource_utilization'),
            },
        }
