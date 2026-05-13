#!/usr/bin/env python3
"""L3 SystemC evaluator backed by the generic simulator bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.dse.orchestrator import DesignPoint


class SystemCEvaluator:
    """Evaluate a design point through ``model/generic_sim_backend``."""

    def __init__(self, executable_path: str | Path | None = None):
        self.backend = GenericSystemCBackend(
            executable_path=str(executable_path) if executable_path is not None else None,
            mode="standalone_systemc",
        )

    @property
    def executable_path(self) -> Path:
        return self.backend.executable_path

    def evaluate(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
    ) -> Dict[str, Any]:
        """Return the generic L3 metrics in the historical evaluator shape."""
        result = self.backend.evaluate(design_point, compute_graph)
        metrics = result.get("metrics", {}) or {}
        feasible = result.get("status") == "passed"
        payload = {
            "design_point_id": design_point.design_point_id,
            "latency_ms": float(metrics.get("latency_ms", 0.0) or 0.0),
            "throughput_gops": float(metrics.get("throughput_gops", 0.0) or 0.0),
            "power_w": float(metrics.get("power_w", 0.0) or 0.0),
            "energy_j": float(metrics.get("energy_j", 0.0) or 0.0),
            "compute_efficiency": float(metrics.get("compute_efficiency", 0.0) or 0.0),
            "memory_efficiency": float(metrics.get("memory_efficiency", 0.0) or 0.0),
            "total_data_movement_mb": float(metrics.get("total_data_movement_mb", metrics.get("move_kib", 0.0) / 1024.0) or 0.0),
            "communication_overhead_ms": float(metrics.get("dma_time_ms", 0.0) or 0.0),
            "feasible": feasible,
            "systemc_details": result,
        }
        if not feasible and result.get("error"):
            payload["error"] = result["error"]
        return payload
