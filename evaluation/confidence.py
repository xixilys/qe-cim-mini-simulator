#!/usr/bin/env python3
"""
Confidence Quantification Module

Provides statistical confidence metrics for DSE results including:
- MAPE (Mean Absolute Percentage Error)
- Confidence intervals
- Coverage metrics
- Convergence detection
"""

import math
import json
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from statistics import mean, stdev


@dataclass
class ConfidenceMetrics:
    mape: float
    confidence_95_interval: Tuple[float, float]
    sample_size: int
    convergence_rate: float
    is_converged: bool
    
    def to_dict(self) -> Dict:
        return {
            "mape": self.mape,
            "confidence_95_interval": list(self.confidence_95_interval),
            "sample_size": self.sample_size,
            "convergence_rate": self.convergence_rate,
            "is_converged": self.is_converged
        }


class ConfidenceQuantifier:
    def __init__(self, target_mape: float = 0.05, min_samples: int = 30):
        self.target_mape = target_mape
        self.min_samples = min_samples
    
    def calculate_mape(self, predicted: List[float], actual: List[float]) -> float:
        if len(predicted) != len(actual) or len(predicted) == 0:
            return float('inf')
        
        errors = []
        for p, a in zip(predicted, actual):
            if a != 0:
                errors.append(abs((p - a) / a))
        
        return mean(errors) if errors else float('inf')
    
    def calculate_confidence_interval(self, values: List[float], confidence: float = 0.95) -> Tuple[float, float]:
        if len(values) < 2:
            return (0.0, 0.0)
        
        n = len(values)
        m = mean(values)
        
        if n < 30:
            # Use t-distribution for small samples
            from statistics import NormalDist
            z = NormalDist().inv_cdf((1 + confidence) / 2)
        else:
            z = 1.96  # 95% confidence
        
        try:
            s = stdev(values)
        except:
            s = 0.0
        
        margin = z * (s / math.sqrt(n))
        return (m - margin, m + margin)
    
    def check_convergence(self, mape_history: List[float]) -> Tuple[bool, float]:
        if len(mape_history) < self.min_samples:
            return False, 0.0
        
        recent = mape_history[-self.min_samples:]
        
        if len(recent) < 2:
            return False, 0.0
        
        # Check if MAPE is below target
        current_mape = recent[-1]
        
        # Check convergence rate (slope of recent MAPE)
        if len(recent) >= 10:
            half = len(recent) // 2
            first_half = mean(recent[:half])
            second_half = mean(recent[half:])
            convergence_rate = (first_half - second_half) / first_half if first_half > 0 else 0.0
        else:
            convergence_rate = 0.0
        
        is_converged = current_mape < self.target_mape and abs(convergence_rate) < 0.1
        
        return is_converged, convergence_rate
    
    def evaluate_confidence(self, 
                          predicted_values: List[float], 
                          actual_values: List[float],
                          mape_history: Optional[List[float]] = None) -> ConfidenceMetrics:
        mape = self.calculate_mape(predicted_values, actual_values)
        
        if mape_history is None:
            mape_history = [mape]
        
        ci = self.calculate_confidence_interval(predicted_values)
        is_converged, rate = self.check_convergence(mape_history)
        
        return ConfidenceMetrics(
            mape=mape,
            confidence_95_interval=ci,
            sample_size=len(predicted_values),
            convergence_rate=rate,
            is_converged=is_converged
        )
    
    def quantify_design_point_confidence(self, 
                                       evaluation_results: List[Dict],
                                       reference_results: Optional[List[Dict]] = None) -> Dict:
        if not evaluation_results:
            return {"error": "No evaluation results provided"}
        
        latencies = [r["metrics"]["latency_ms"] for r in evaluation_results if "metrics" in r]
        throughputs = [r["metrics"]["throughput_gops"] for r in evaluation_results if "metrics" in r]
        
        if not latencies:
            return {"error": "No valid metrics found"}
        
        lat_ci = self.calculate_confidence_interval(latencies)
        tp_ci = self.calculate_confidence_interval(throughputs)
        
        result = {
            "latency": {
                "mean_ms": mean(latencies),
                "ci_95": list(lat_ci),
                "relative_width": (lat_ci[1] - lat_ci[0]) / mean(latencies) if mean(latencies) > 0 else 0
            },
            "throughput": {
                "mean_gops": mean(throughputs),
                "ci_95": list(tp_ci),
                "relative_width": (tp_ci[1] - tp_ci[0]) / mean(throughputs) if mean(throughputs) > 0 else 0
            },
            "sample_size": len(evaluation_results),
            "confidence_level": "high" if len(evaluation_results) >= self.min_samples else "medium"
        }
        
        if reference_results:
            ref_latencies = [r["metrics"]["latency_ms"] for r in reference_results if "metrics" in r]
            if ref_latencies and latencies:
                mape = self.calculate_mape(latencies[:len(ref_latencies)], ref_latencies)
                result["mape_vs_reference"] = mape
                result["is_accurate"] = mape < self.target_mape
        
        return result


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Confidence Quantification")
    parser.add_argument("--results", type=str, required=True, help="JSON file with evaluation results")
    parser.add_argument("--reference", type=str, help="Optional reference results for MAPE calculation")
    parser.add_argument("--target-mape", type=float, default=0.05)
    args = parser.parse_args()
    
    with open(args.results) as f:
        results = json.load(f)
    
    reference = None
    if args.reference:
        with open(args.reference) as f:
            reference = json.load(f)
    
    quantifier = ConfidenceQuantifier(target_mape=args.target_mape)
    confidence = quantifier.quantify_design_point_confidence(results, reference)
    
    print(json.dumps(confidence, indent=2))
    return 0


if __name__ == "__main__":
    exit(main())
