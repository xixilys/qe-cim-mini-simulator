#!/usr/bin/env python3
"""
Integration test for full DSE pipeline with confidence quantification.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.confidence import ConfidenceQuantifier
from evaluation.executor import EvaluationExecutor


def test_full_dse_with_confidence():
    print("=" * 80)
    print("FULL DSE PIPELINE INTEGRATION TEST")
    print("=" * 80)
    
    executor = EvaluationExecutor()
    quantifier = ConfidenceQuantifier(target_mape=0.05, min_samples=30)
    
    design_point = {
        "parameters": {
            "system_level": {
                "family": "F4",
                "n_gemm_tiles": 6,
                "n_eigen_tiles": 2,
                "tile_local_mem_kb": 1024,
                "mesh_topology": "2x4",
                "tile_link_bw_gbps": 64
            }
        }
    }
    
    workload = {
        "compute_graph": {
            "nodes": [
                {
                    "id": "h_psi",
                    "typical_sizes": {"N": [2945], "K": [144], "M": [16]},
                    "flops_per_call": 1e9,
                    "call_count": 100
                }
            ]
        },
        "execution_profile": {
            "total_iterations": 10
        }
    }
    
    print("\n1. Testing Multi-Fidelity Evaluation")
    print("-" * 80)
    
    results_by_fidelity = {}
    for fidelity in ["L0", "L1", "L2", "L3", "L4"]:
        config = {"fidelity_level": fidelity}
        result = executor.evaluate(config, design_point, workload)
        results_by_fidelity[fidelity] = result
        
        print(f"\n{fidelity}:")
        print(f"  Latency: {result['metrics']['latency_ms']:.2f} ms")
        print(f"  Throughput: {result['metrics']['throughput_gops']:.2f} GOP/s")
        print(f"  Accuracy: {result['accuracy']:.2%}")
    
    print("\n2. Testing Confidence Quantification")
    print("-" * 80)
    
    evaluation_results = list(results_by_fidelity.values())
    confidence = quantifier.quantify_design_point_confidence(evaluation_results)
    
    print(f"\nConfidence Report:")
    print(f"  Sample Size: {confidence['sample_size']}")
    print(f"  Confidence Level: {confidence['confidence_level']}")
    print(f"  Latency Mean: {confidence['latency']['mean_ms']:.2f} ms")
    print(f"  Latency CI: [{confidence['latency']['ci_95'][0]:.2f}, {confidence['latency']['ci_95'][1]:.2f}]")
    print(f"  Throughput Mean: {confidence['throughput']['mean_gops']:.2f} GOP/s")
    print(f"  Throughput CI: [{confidence['throughput']['ci_95'][0]:.2f}, {confidence['throughput']['ci_95'][1]:.2f}]")
    
    print("\n3. Testing Convergence Detection")
    print("-" * 80)
    
    mape_history = [0.5, 0.3, 0.2, 0.15, 0.1, 0.08, 0.06, 0.05, 0.04, 0.035, 
                    0.03, 0.028, 0.025, 0.023, 0.022, 0.021, 0.02, 0.019, 0.018, 0.017,
                    0.016, 0.015, 0.014, 0.013, 0.012, 0.011, 0.01, 0.009, 0.008, 0.007]
    
    is_converged, rate = quantifier.check_convergence(mape_history)
    print(f"\nConvergence Test:")
    print(f"  MAPE History Length: {len(mape_history)}")
    print(f"  Is Converged: {is_converged}")
    print(f"  Convergence Rate: {rate:.4f}")
    
    print("\n4. Testing MAPE Calculation")
    print("-" * 80)
    
    predicted = [100.0, 200.0, 300.0, 400.0, 500.0]
    actual = [105.0, 195.0, 310.0, 390.0, 520.0]
    
    mape = quantifier.calculate_mape(predicted, actual)
    print(f"\nMAPE Test:")
    print(f"  Predicted: {predicted}")
    print(f"  Actual: {actual}")
    print(f"  MAPE: {mape:.2%}")
    
    print("\n" + "=" * 80)
    print("INTEGRATION TEST COMPLETE")
    print("=" * 80)
    
    assert confidence['sample_size'] == 5
    assert confidence['confidence_level'] == 'medium'
    assert mape < 0.1
    
    print("\n✓ All assertions passed")


if __name__ == "__main__":
    test_full_dse_with_confidence()
    sys.exit(0)
