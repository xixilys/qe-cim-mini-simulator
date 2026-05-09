#!/usr/bin/env python3
"""SystemC Backend Bridge - Connects to existing SystemC model."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.dse.orchestrator import DesignPoint


class SystemCEvaluator:
    """SystemC backend evaluator.
    
    Wraps the existing SystemCBackend to provide high-fidelity evaluation.
    """
    
    def __init__(self, executable_path: str | None = None):
        if executable_path is None:
            project_root = Path(__file__).resolve().parents[3]
            self.executable_path = project_root / "model" / "qe_band_solver_model" / "build" / "qe_band_solver_model"
            if not self.executable_path.exists():
                self.executable_path = Path("model/qe_band_solver_model/build/qe_band_solver_model")
        else:
            self.executable_path = Path(executable_path)
    
    def evaluate(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
    ) -> Dict[str, Any]:
        """Evaluate design point using SystemC simulation."""
        # Check if executable exists
        if not self.executable_path.exists():
            return {
                "design_point_id": design_point.design_point_id,
                "latency_ms": 0.0,
                "throughput_gops": 0.0,
                "power_w": 0.0,
                "energy_j": 0.0,
                "feasible": False,
                "error": f"SystemC executable not found: {self.executable_path}",
            }
        
        # Build environment
        env = os.environ.copy()
        env.update(self._build_env(design_point, compute_graph))
        
        # Execute SystemC model
        try:
            result = subprocess.run(
                [str(self.executable_path)],
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            
            if result.returncode != 0:
                return {
                    "design_point_id": design_point.design_point_id,
                    "latency_ms": 0.0,
                    "throughput_gops": 0.0,
                    "power_w": 0.0,
                    "energy_j": 0.0,
                    "feasible": False,
                    "error": f"SystemC execution failed: {result.stderr[:500]}",
                }
            
            # Parse output
            return self._parse_output(result.stdout, design_point.design_point_id)
            
        except subprocess.TimeoutExpired:
            return {
                "design_point_id": design_point.design_point_id,
                "latency_ms": 0.0,
                "throughput_gops": 0.0,
                "power_w": 0.0,
                "energy_j": 0.0,
                "feasible": False,
                "error": "SystemC execution timed out (300s)",
            }
        except Exception as e:
            return {
                "design_point_id": design_point.design_point_id,
                "latency_ms": 0.0,
                "throughput_gops": 0.0,
                "power_w": 0.0,
                "energy_j": 0.0,
                "feasible": False,
                "error": f"SystemC execution error: {str(e)}",
            }
    
    def _build_env(self, design_point: DesignPoint, compute_graph: ComputeGraph) -> Dict[str, str]:
        """Build environment variables for SystemC model."""
        metadata = compute_graph.metadata
        
        env = {
            'QEBS_ARCH_FAMILY': 'F4',
            'QEBS_MAX_SCF_ITERS': str(metadata.get('iterations', 10)),
            'QEBS_NPW': str(metadata.get('npw', 2945)),
            'QEBS_NKB': str(metadata.get('nkb', 144)),
            'QEBS_M': str(metadata.get('m', 16)),
            'QEBS_EXECUTION_MODE': 'systemc',
            'QEBS_OUTPUT_FORMAT': 'json',
        }
        
        # Add mapping if available
        mapping = design_point.task_mapping
        if mapping:
            env['QEBS_MAPPING_OPERATOR_SWEEP'] = mapping.get('h_psi', 'cluster_a')
            env['QEBS_MAPPING_REDUCED_BUILD'] = mapping.get('build_H_sub', 'cluster_b')
            env['QEBS_MAPPING_DIAG'] = mapping.get('diagonalize', 'cluster_c')
            env['QEBS_MAPPING_REFRESH'] = mapping.get('refresh', 'cluster_d')
        
        return env
    
    def _parse_output(self, stdout: str, design_point_id: str) -> Dict[str, Any]:
        """Parse SystemC stdout to extract metrics."""
        import re
        
        metrics = {}
        
        # Parse ref_cycles
        ref_match = re.search(r'ref_cycles=(\d+)', stdout)
        if ref_match:
            ref_cycles = int(ref_match.group(1))
            latency_ms = ref_cycles / 300e6 * 1000.0
            metrics['latency_ms'] = latency_ms
            metrics['ref_cycles'] = ref_cycles
        else:
            metrics['latency_ms'] = 0.0
        
        # Parse device_busy_ref_cycles
        busy_match = re.search(r'device_busy_ref_cycles=(\d+)', stdout)
        if busy_match:
            metrics['device_busy_ref_cycles'] = int(busy_match.group(1))
        
        # Parse move_kib
        move_match = re.search(r'move_kib=([\d.]+)', stdout)
        if move_match:
            metrics['move_kib'] = float(move_match.group(1))
        
        # Parse convergence
        conv_match = re.search(r'convergence=(\w+)', stdout)
        convergence = conv_match.group(1) if conv_match else 'unknown'
        
        # Calculate power (simplified)
        power_w = 25.0 + 0.01 * metrics.get('device_busy_ref_cycles', 0) / 1000.0
        
        return {
            "design_point_id": design_point_id,
            "latency_ms": metrics.get('latency_ms', 0.0),
            "throughput_gops": 0.0,
            "power_w": power_w,
            "energy_j": power_w * metrics.get('latency_ms', 0.0) / 1000.0,
            "compute_efficiency": 0.0,
            "memory_efficiency": 0.0,
            "total_data_movement_mb": metrics.get('move_kib', 0.0) / 1024.0,
            "communication_overhead_ms": 0.0,
            "feasible": convergence != 'failed',
            "systemc_details": {
                "convergence": convergence,
                "ref_cycles": metrics.get('ref_cycles', 0),
                "device_busy_ref_cycles": metrics.get('device_busy_ref_cycles', 0),
                "move_kib": metrics.get('move_kib', 0.0),
            },
        }
