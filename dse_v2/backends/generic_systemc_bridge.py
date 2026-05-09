#!/usr/bin/env python3
"""Generic SystemC Simulation Backend - Python bridge.

Replaces QE-specific systemc_backend.py with a generic backend
that can simulate any accelerator type and workload.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.dse.orchestrator import DesignPoint


class GenericSystemCBackend:
    """Generic SystemC simulation backend.
    
    Uses JSON file-based IPC to communicate with C++ simulator.
    """
    
    def __init__(
        self,
        executable_path: Optional[str] = None,
        mode: str = "standalone_systemc",
    ):
        if executable_path is None:
            project_root = Path(__file__).resolve().parents[3]
            self.executable_path = project_root / "model" / "generic_sim_backend" / "build" / "generic_sim"
            if not self.executable_path.exists():
                self.executable_path = Path("model/generic_sim_backend/build/generic_sim")
        else:
            self.executable_path = Path(executable_path)
        
        self.mode = mode
        self.workspace = Path(tempfile.gettempdir()) / "gsim"
        self.workspace.mkdir(parents=True, exist_ok=True)
    
    def evaluate(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
    ) -> Dict[str, Any]:
        """Evaluate design point using generic SystemC simulation."""
        if not self.executable_path.exists():
            return self._error_result(
                design_point.design_point_id,
                f"Simulator not found: {self.executable_path}"
            )
        
        try:
            run = self.run_simulation(design_point, compute_graph, timeout=300)
            
            if run["returncode"] != 0:
                return self._error_result(
                    design_point.design_point_id,
                    f"Simulation failed: {run['stderr'][:500]}"
                )
            
            if run["result"] is None:
                return self._error_result(
                    design_point.design_point_id,
                    "Result file not generated"
                )
            
            return self._normalize_result(run["result"])
            
        except subprocess.TimeoutExpired:
            return self._error_result(design_point.design_point_id, "Simulation timed out (300s)")
        except Exception as e:
            return self._error_result(design_point.design_point_id, f"Simulation error: {str(e)}")

    def run_simulation(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
        output_dir: Optional[Path] = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """Run the simulator and return raw artifacts for evidence capture."""
        if not self.executable_path.exists():
            return {
                "run_id": design_point.design_point_id,
                "returncode": 127,
                "stdout": "",
                "stderr": f"Simulator not found: {self.executable_path}",
                "request": None,
                "result": None,
                "request_path": None,
                "result_path": None,
                "trace_path": None,
                "cmd": [],
            }
        
        workspace = Path(output_dir) if output_dir else self.workspace
        workspace.mkdir(parents=True, exist_ok=True)
        
        run_id = design_point.design_point_id
        request_path = workspace / "simulation_request.json"
        result_path = workspace / "simulation_result.raw.json"
        trace_path = workspace / "simulation_trace.json"
        
        request = self._build_request(design_point, compute_graph, output_dir=workspace)
        with open(request_path, "w") as f:
            json.dump(request, f, indent=2)
        
        cmd = [
            str(self.executable_path),
            "--request", str(request_path),
            "--result", str(result_path),
        ]
        
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        sim_result = None
        if result_path.exists():
            with open(result_path) as f:
                sim_result = json.load(f)
        
        return {
            "run_id": run_id,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "request": request,
            "result": sim_result,
            "request_path": request_path,
            "result_path": result_path,
            "trace_path": trace_path,
            "cmd": cmd,
        }
    
    def _build_request(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
        output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Convert DesignPoint + ComputeGraph to simulation request."""
        output_dir = Path(output_dir) if output_dir else self.workspace
        
        # Build workload nodes
        nodes = {}
        for node_id, node in compute_graph.nodes.items():
            nodes[node_id] = {
                "op_type": node.op_type,
                "inputs": node.inputs,
                "outputs": node.outputs,
                "estimated_flops": node.estimated_flops,
                "estimated_memory_bytes": node.estimated_memory_bytes,
                "attributes": node.attributes,
            }
        
        # Build edges
        edges = []
        for edge in compute_graph.edges:
            edge_data = {
                "source": edge.source_node,
                "target": edge.target_node,
                "tensor_name": edge.tensor_name,
            }
            if edge.tensor_spec:
                edge_data["tensor_shape"] = list(edge.tensor_spec.shape)
                edge_data["tensor_dtype"] = edge.tensor_spec.dtype
            edges.append(edge_data)
        
        # Build architecture
        accelerators = []
        for accel in design_point.system_architecture.accelerators:
            accel_desc = {
                "accel_id": accel.accel_id,
                "accel_type": accel.accel_type,
                "clock_mhz": 250,  # Default
                "local_memory_kb": 2048,  # Default
                "power": {
                    "static_w": accel.power.static_power_w,
                    "max_w": 100.0,
                },
                "capabilities": {},
            }
            
            # Add capabilities from compute capability
            for op_type in accel.compute.supported_ops:
                peak_gflops = accel.compute.get_peak_flops("FP64") / 1e9
                efficiency = accel.compute.get_op_efficiency(op_type)
                accel_desc["capabilities"][op_type] = {
                    "peak_gops": peak_gflops,
                    "efficiency": efficiency,
                }
            
            accelerators.append(accel_desc)
        
        # Build interconnect
        interconnect = None
        if design_point.system_architecture.interconnect:
            ic = design_point.system_architecture.interconnect
            interconnect = {
                "type": ic.topology_type,
                "bandwidth_gbps": ic.bandwidth_gbps,
                "latency_ns": ic.latency_us * 1000,
            }
        
        return {
            "schema_version": "gsim.request.v1",
            "run_id": design_point.design_point_id,
            "mode": self.mode,
            "workload": {
                "graph_id": compute_graph.graph_id,
                "nodes": nodes,
                "edges": edges,
                "metadata": compute_graph.metadata,
            },
            "architecture": {
                "host": {
                    "cpu_model": "abstract",
                    "clock_mhz": 3000,
                    "memory_bw_gbps": 100,
                    "cores": design_point.system_architecture.host_cpu_cores,
                },
                "interconnect": interconnect,
                "accelerators": accelerators,
            },
            "mapping": design_point.task_mapping,
            "scheduling": {
                "policy": design_point.scheduling_policy,
                "allow_overlap_dma_compute": True,
                "double_buffer": True,
            },
            "output": {
                "result_json": str(output_dir / "simulation_result.raw.json"),
                "trace_json": str(output_dir / "simulation_trace.json"),
            },
        }
    
    def _normalize_result(self, sim_result: Dict[str, Any]) -> Dict[str, Any]:
        """Convert simulation result to standard evaluation format."""
        metrics = sim_result.get("metrics", {})
        
        return {
            "design_point_id": sim_result.get("run_id", "unknown"),
            "latency_ms": metrics.get("latency_ms", 0.0),
            "throughput_gops": metrics.get("throughput_gops", 0.0),
            "power_w": metrics.get("power_w", 0.0),
            "energy_j": metrics.get("energy_j", 0.0),
            "compute_efficiency": 0.0,
            "memory_efficiency": 0.0,
            "total_data_movement_mb": metrics.get("total_data_movement_mb", 0.0),
            "communication_overhead_ms": metrics.get("dma_time_ms", 0.0),
            "feasible": sim_result.get("status") == "passed",
            "fidelity_level": "L3",
            "fidelity_description": "Generic SystemC simulation",
            "simulation_details": {
                "status": sim_result.get("status"),
                "resource_utilization": sim_result.get("resource_utilization", {}),
                "events": sim_result.get("events", []),
                "uncertainty": sim_result.get("uncertainty", {}),
            },
        }
    
    def _error_result(self, run_id: str, error: str) -> Dict[str, Any]:
        """Create error result."""
        return {
            "design_point_id": run_id,
            "latency_ms": 0.0,
            "throughput_gops": 0.0,
            "power_w": 0.0,
            "energy_j": 0.0,
            "feasible": False,
            "error": error,
            "fidelity_level": "L3",
        }
