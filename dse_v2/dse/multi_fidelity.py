#!/usr/bin/env python3
"""Multi-fidelity evaluation framework.

Automatically selects appropriate fidelity level based on:
1. Design point confidence/promotion score
2. Available time budget
3. Required accuracy

Fidelity levels:
- L1 (Fast): Analytical/Roofline model - ~ms evaluation
- L2 (TLM): Transaction-level model - ~100ms evaluation  
- L3 (SystemC): Cycle-accurate simulation - ~minutes evaluation
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.dse.orchestrator import DesignPoint
from dse_v2.dse.analytical_evaluator import EnhancedAnalyticalEvaluator
from dse_v2.dse.tlm_evaluator import TLMEvaluator
from dse_v2.dse.systemc_evaluator import SystemCEvaluator


class MultiFidelityEvaluator:
    """Multi-fidelity evaluator with automatic level selection."""
    
    def __init__(
        self,
        enable_tlm: bool = True,
        enable_systemc: bool = False,
        tlm_threshold: float = 0.7,
        systemc_threshold: float = 0.9,
    ):
        self.l1_evaluator = EnhancedAnalyticalEvaluator()
        self.l2_evaluator = TLMEvaluator() if enable_tlm else None
        self.l3_evaluator = SystemCEvaluator() if enable_systemc else None
        
        self.tlm_threshold = tlm_threshold
        self.systemc_threshold = systemc_threshold
        
        self.evaluation_history: List[Dict[str, Any]] = []
    
    def evaluate(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
        force_fidelity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Evaluate design point at appropriate fidelity level.
        
        Args:
            design_point: The design point to evaluate
            compute_graph: The workload compute graph
            force_fidelity: Force specific fidelity ('L1', 'L2', 'L3')
        
        Returns:
            Evaluation result with fidelity level metadata
        """
        if force_fidelity:
            return self._evaluate_at_fidelity(design_point, compute_graph, force_fidelity)
        
        # Start with L1 (fast)
        result = self._evaluate_at_fidelity(design_point, compute_graph, "L1")
        
        # Check if we should promote to L2
        if self.l2_evaluator and self._should_promote_to_l2(result):
            result = self._evaluate_at_fidelity(design_point, compute_graph, "L2")
            
            # Check if we should promote to L3
            if self.l3_evaluator and self._should_promote_to_l3(result):
                result = self._evaluate_at_fidelity(design_point, compute_graph, "L3")
        
        return result
    
    def _evaluate_at_fidelity(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
        fidelity: str,
    ) -> Dict[str, Any]:
        """Evaluate at specific fidelity level."""
        if fidelity == "L1":
            result = self.l1_evaluator.evaluate(design_point, compute_graph)
        elif fidelity == "L2" and self.l2_evaluator:
            result = self.l2_evaluator.evaluate(design_point, compute_graph)
        elif fidelity == "L3" and self.l3_evaluator:
            result = self.l3_evaluator.evaluate(design_point, compute_graph)
        else:
            raise ValueError(f"Invalid fidelity level: {fidelity}")
        
        # Add fidelity metadata
        result["fidelity_level"] = fidelity
        result["fidelity_description"] = {
            "L1": "Fast analytical model",
            "L2": "Transaction-level model",
            "L3": "Cycle-accurate SystemC simulation",
        }.get(fidelity, "Unknown")
        
        # Record evaluation
        self.evaluation_history.append({
            "design_point_id": design_point.design_point_id,
            "fidelity": fidelity,
            "latency_ms": result.get("latency_ms", 0.0),
        })
        
        return result
    
    def _should_promote_to_l2(self, l1_result: Dict[str, Any]) -> bool:
        """Determine if L1 result should be promoted to L2."""
        # Promote if confidence is low or design is near boundary
        confidence = l1_result.get("compute_efficiency", 0.0)
        
        # Also promote if data movement is significant
        data_movement = l1_result.get("total_data_movement_mb", 0.0)
        has_significant_data_movement = data_movement > 1.0
        
        return confidence < self.tlm_threshold or has_significant_data_movement
    
    def _should_promote_to_l3(self, l2_result: Dict[str, Any]) -> bool:
        """Determine if L2 result should be promoted to L3."""
        # Get promotion score from TLM
        tlm_details = l2_result.get("tlm_details", {})
        promotion_score = tlm_details.get("promotion_score", 0.0)
        confidence = tlm_details.get("confidence", 0.0)
        
        # Promote if TLM confidence is high enough
        return promotion_score > self.systemc_threshold and confidence > 0.8
    
    def get_fidelity_statistics(self) -> Dict[str, Any]:
        """Get statistics about fidelity level usage."""
        if not self.evaluation_history:
            return {}
        
        total = len(self.evaluation_history)
        l1_count = sum(1 for e in self.evaluation_history if e["fidelity"] == "L1")
        l2_count = sum(1 for e in self.evaluation_history if e["fidelity"] == "L2")
        l3_count = sum(1 for e in self.evaluation_history if e["fidelity"] == "L3")
        
        return {
            "total_evaluations": total,
            "l1_count": l1_count,
            "l2_count": l2_count,
            "l3_count": l3_count,
            "l1_percentage": l1_count / total * 100,
            "l2_percentage": l2_count / total * 100,
            "l3_percentage": l3_count / total * 100,
        }
