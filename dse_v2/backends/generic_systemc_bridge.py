#!/usr/bin/env python3
"""Generic SystemC simulation backend Python bridge.

This backend sends domain-neutral workload packages and compute graphs to the
generic simulator path used by the DSE evidence flow.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload.lowering import lower_compute_graph
from dse_v2.core.workload.package import WorkloadPackage, package_from_graph
from dse_v2.core.workload.workflows import required_coverage_from_workflow
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
        workload_package: Optional[WorkloadPackage] = None,
    ) -> Dict[str, Any]:
        """Evaluate design point using generic SystemC simulation."""
        if not self.executable_path.exists():
            return self._error_result(
                design_point.design_point_id,
                f"Simulator not found: {self.executable_path}"
            )
        
        try:
            run = self.run_simulation(design_point, compute_graph, workload_package=workload_package, timeout=300)
            
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
        workload_package: Optional[WorkloadPackage] = None,
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
        
        request = self._build_request(design_point, compute_graph, workload_package=workload_package, output_dir=workspace)
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
        workload_package: Optional[WorkloadPackage] = None,
        output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Convert DesignPoint + ComputeGraph to simulation request."""
        output_dir = Path(output_dir) if output_dir else self.workspace
        step2_config = dict(design_point.config or {})
        step2_graph_lowering = step2_config.get("graph_lowering", {}) if isinstance(step2_config.get("graph_lowering", {}), dict) else {}
        
        workload_package = workload_package or package_from_graph(
            compute_graph,
            workload_id=compute_graph.graph_id,
            workload_family=str(compute_graph.metadata.get("workload_family", "dynamic_custom")),
            profile_id=str(compute_graph.metadata.get("profile_id", compute_graph.metadata.get("workload_family", "dynamic_custom"))),
            importer_id=str(compute_graph.metadata.get("importer_id", "direct_graph")),
            claim_boundary=str(compute_graph.metadata.get("claim_boundary", "full_workload")),
            source_kind="generated",
        )
        lowering = lower_compute_graph(compute_graph, workload_package)
        executable_graph = lowering.executable_graph or compute_graph
        workflow = workload_package.resolved_workflow()
        required_coverage = required_coverage_from_workflow(
            workload_package.workload_family,
            workflow,
            compute_graph.nodes.keys(),
            lowering.report.get("topological_order", []),
        )
        if step2_config.get("required_coverage"):
            required_coverage = [str(item) for item in step2_config.get("required_coverage", [])]

        # Build workload nodes
        nodes = {}
        for node_id, node in executable_graph.nodes.items():
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
        for edge in executable_graph.edges:
            edge_data = {
                "source": edge.source_node,
                "target": edge.target_node,
                "source_node": edge.source_node,
                "target_node": edge.target_node,
                "tensor_name": edge.tensor_name,
                "edge_kind": edge.edge_kind,
                "attributes": edge.attributes,
            }
            if edge.tensor_spec:
                edge_data["tensor_shape"] = list(edge.tensor_spec.shape)
                edge_data["tensor_dtype"] = edge.tensor_spec.dtype
                edge_data["element_size"] = edge.tensor_spec.element_size_bytes()
                edge_data["size_bytes"] = edge.tensor_spec.size_bytes()
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
        
        request = {
            "schema_version": "gsim.request.v1",
            "run_id": design_point.design_point_id,
            "mode": self.mode,
            "design_point": {
                "design_point_id": design_point.design_point_id,
                "workload_id": step2_config.get("workload_id", workload_package.workload_id),
                "architecture_id": step2_config.get("architecture_id", design_point.system_architecture.system_id),
                "mapping_id": step2_config.get("mapping_id"),
                "selected_candidate_id": step2_config.get("selected_candidate_id"),
                "scheduling_policy": design_point.scheduling_policy,
                "precision_policy": step2_config.get("precision_policy", {"default": "FP64"}),
                "fallback_policy": step2_config.get("fallback_policy", {"unsupported_ops": "host_fallback_visible"}),
                "objective_directions": step2_config.get("objective_directions", {}),
                "output_config": step2_config.get("output_config", {}),
                "replay_metadata": step2_config.get("replay_metadata", {}),
            },
            "step2_handoff": {
                "present": bool(step2_config.get("step") == "step2_architecture_mapping"),
                "source_graph_id": step2_config.get("source_graph_id", compute_graph.graph_id),
                "executable_graph_id": step2_config.get("executable_graph_id", executable_graph.graph_id),
                "source_to_executable_nodes": step2_graph_lowering.get("source_to_executable_nodes", lowering.report.get("source_to_executable_nodes", {})),
                "required_mapping_artifacts": (step2_config.get("output_config", {}) or {}).get("required_mapping_artifacts", []),
                "claim_boundary": step2_config.get("claim_boundary", workload_package.claim_boundary),
            },
            "workload": {
                "graph_id": executable_graph.graph_id,
                "source_graph_id": compute_graph.graph_id,
                "nodes": nodes,
                "edges": edges,
                "metadata": executable_graph.metadata,
                "graph_lowering": lowering.report,
                "workload_package": {
                    "schema_version": workload_package.schema_version,
                    "workload_id": workload_package.workload_id,
                    "workload_family": workload_package.workload_family,
                    "profile": dict(workload_package.resolved_profile()),
                    "importer": dict(workload_package.importer),
                    "source": dict(workload_package.source),
                    "claim_boundary": workload_package.claim_boundary,
                },
                "workflow": workflow,
                "required_coverage": required_coverage,
                "source_to_executable_nodes": step2_graph_lowering.get("source_to_executable_nodes", lowering.report.get("source_to_executable_nodes", {})),
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
        request["candidate_translation"] = self._candidate_translation_metadata(
            design_point=design_point,
            workload_package=workload_package,
            executable_graph=executable_graph,
        )
        return request

    def _candidate_translation_metadata(
        self,
        *,
        design_point: DesignPoint,
        workload_package: WorkloadPackage,
        executable_graph: ComputeGraph,
    ) -> Dict[str, Any]:
        """Describe the replayable Step2-candidate to SystemC-request mapping."""
        step2_config = dict(design_point.config or {})
        simulation_config = (
            step2_config.get("simulation_config", {})
            if isinstance(step2_config.get("simulation_config", {}), dict)
            else {}
        )
        replay_metadata = (
            step2_config.get("replay_metadata", {})
            if isinstance(step2_config.get("replay_metadata", {}), dict)
            else {}
        )
        return {
            "schema_version": "dse.step3.candidate_to_systemc_request.v1",
            "translator": "dse_v2.backends.generic_systemc_bridge.GenericSystemCBackend._build_request",
            "source": "design_point_config" if step2_config else "direct_design_point",
            "source_step": step2_config.get("step"),
            "step2_handoff_present": bool(step2_config.get("step") == "step2_architecture_mapping"),
            "request_schema_version": "gsim.request.v1",
            "backend_mode": self.mode,
            "candidate_id": step2_config.get("selected_candidate_id") or step2_config.get("candidate_id") or design_point.design_point_id,
            "design_point_id": design_point.design_point_id,
            "workload_id": step2_config.get("workload_id", workload_package.workload_id),
            "workload_family": step2_config.get("workload_family", workload_package.workload_family),
            "architecture_id": step2_config.get("architecture_id", design_point.system_architecture.system_id),
            "mapping_id": step2_config.get("mapping_id"),
            "source_graph_id": step2_config.get("source_graph_id", workload_package.graph.graph_id),
            "executable_graph_id": step2_config.get("executable_graph_id", executable_graph.graph_id),
            "claim_boundary": step2_config.get("claim_boundary", workload_package.claim_boundary),
            "required_coverage_source": "design_point_config" if step2_config.get("required_coverage") else "workflow_lowering",
            "simulation_config": {
                "backend": simulation_config.get("backend", "systemc" if self.mode == "standalone_systemc" else self.mode),
                "mode": simulation_config.get("mode", self.mode),
                "step3_request_builder": simulation_config.get(
                    "step3_request_builder",
                    "dse_v2.backends.generic_systemc_bridge.GenericSystemCBackend._build_request",
                ),
            },
            "replay_artifacts": {
                "design_point": "design_point.json" if step2_config else None,
                "workload_package": replay_metadata.get("workload_package"),
                "source_graph": replay_metadata.get("source_graph"),
                "executable_graph": replay_metadata.get("executable_graph"),
                "mapping_selected_record": replay_metadata.get("mapping_selected_record"),
                "graph_lowering": (
                    step2_config.get("graph_lowering", {}).get("artifact")
                    if isinstance(step2_config.get("graph_lowering", {}), dict)
                    else None
                ),
            },
            "trusted_final_claim": False,
            "claim_boundary_note": (
                "This records a deterministic SystemC request translation for the selected "
                "candidate; trusted final ranking still requires Step3 evidence and later gates."
            ),
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
