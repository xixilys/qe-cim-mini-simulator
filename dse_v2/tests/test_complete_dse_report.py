#!/usr/bin/env python3
"""Complete DFT Evaluation with Multi-Fidelity Framework and Generic Backends."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dse_v2.core.architecture.accelerator import (
    create_gpu_a100, create_fpga_u280, create_cim_array,
)
from dse_v2.core.ir.compute_graph import create_dft_scf_graph
from dse_v2.core.ir.dft_workload import create_complete_qe_scf_graph
from dse_v2.dse.orchestrator import SearchSpace, DSEOrchestrator, DesignPoint, SystemArchitecture
from dse_v2.dse.multi_fidelity import MultiFidelityEvaluator
from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend


def generate_report():
    print("=" * 80)
    print("DFT Evaluation Report - Generic Multi-Fidelity Framework")
    print("=" * 80)
    
    # 1. Workload Analysis
    print("\n[1] Workload Analysis")
    print("-" * 80)
    
    basic_graph = create_dft_scf_graph()
    complete_graph = create_complete_qe_scf_graph()
    
    print(f"Basic SCF Graph:")
    print(f"  Nodes: {len(basic_graph.nodes)}")
    print(f"  Edges: {len(basic_graph.edges)}")
    print(f"  Total FLOPs: {basic_graph.total_flops()/1e9:.2f} GFLOPs")
    print(f"  Total Memory: {basic_graph.total_memory_bytes()/1e6:.2f} MB")
    
    print(f"\nComplete SCF Graph:")
    print(f"  Nodes: {len(complete_graph.nodes)}")
    print(f"  Edges: {len(complete_graph.edges)}")
    print(f"  Total FLOPs: {complete_graph.total_flops()/1e9:.2f} GFLOPs")
    print(f"  Total Memory: {complete_graph.total_memory_bytes()/1e6:.2f} MB")
    
    # 2. Accelerator Characteristics
    print("\n[2] Accelerator Characteristics")
    print("-" * 80)
    
    gpu = create_gpu_a100("gpu-0")
    fpga = create_fpga_u280("fpga-0")
    cim = create_cim_array("cim-0")
    
    accelerators = [gpu, fpga, cim]
    for accel in accelerators:
        fp64 = accel.compute.get_peak_flops("FP64") / 1e12
        print(f"  {accel.accel_id:10s} ({accel.accel_type:6s}): {fp64:.2f} TFLOPS (FP64)")
    
    # 3. Single-Accelerator Performance (L1 - Analytical)
    print("\n[3] Single-Accelerator Performance (L1 - Analytical)")
    print("-" * 80)
    
    evaluator = MultiFidelityEvaluator(enable_systemc=False)
    
    for accel in accelerators:
        sys_arch = SystemArchitecture(
            system_id=f"single_{accel.accel_id}",
            accelerators=[accel],
        )
        mapping = {nid: accel.accel_id for nid in basic_graph.nodes}
        dp = DesignPoint(f"dp_{accel.accel_id}", sys_arch, mapping)
        
        result = evaluator.evaluate(dp, basic_graph, force_fidelity="L1")
        print(f"  {accel.accel_id:10s}: latency={result['latency_ms']:.2f}ms  "
              f"power={result['power_w']:.1f}W  energy={result['energy_j']:.3f}J  "
              f"data={result['total_data_movement_mb']:.2f}MB")
    
    # 4. Multi-Accelerator DSE (L1)
    print("\n[4] Multi-Accelerator DSE (L1 - Analytical)")
    print("-" * 80)
    
    ss = SearchSpace(
        accelerator_options=accelerators,
        max_accelerators=3,
        max_power_w=1000.0,
    )
    
    orchestrator = DSEOrchestrator(ss, evaluator.l1_evaluator)
    pareto_results = orchestrator.explore(basic_graph, max_points=50)
    
    print(f"  Design points explored: {len(orchestrator.results)}")
    print(f"  Pareto-optimal points: {len(pareto_results)}")
    
    best = orchestrator.get_best_design("latency")
    if best:
        print(f"\n  Best design (latency):")
        print(f"    Latency: {best['latency_ms']:.2f} ms")
        print(f"    Throughput: {best['throughput_gops']:.2f} GOPS")
        print(f"    Power: {best['power_w']:.1f} W")
        print(f"    Energy: {best['energy_j']:.2f} J")
        print(f"    Data movement: {best['total_data_movement_mb']:.2f} MB")
    
    # 5. Generic SystemC Backend (L3)
    print("\n[5] Generic SystemC Backend (L3 - Standalone)")
    print("-" * 80)
    
    generic_backend = GenericSystemCBackend()
    
    for accel in accelerators[:1]:  # Test with GPU only for speed
        sys_arch = SystemArchitecture(
            system_id=f"single_{accel.accel_id}",
            accelerators=[accel],
        )
        mapping = {nid: accel.accel_id for nid in basic_graph.nodes}
        dp = DesignPoint(f"dp_{accel.accel_id}", sys_arch, mapping)
        
        result = generic_backend.evaluate(dp, basic_graph)
        print(f"  {accel.accel_id:10s}: latency={result['latency_ms']:.2f}ms  "
              f"power={result['power_w']:.1f}W  "
              f"fidelity={result['fidelity_level']}  "
              f"feasible={result['feasible']}")
    
    # 6. Fidelity Comparison
    print("\n[6] Fidelity Comparison")
    print("-" * 80)
    
    sys_arch = SystemArchitecture(
        system_id="comparison",
        accelerators=[gpu],
    )
    mapping = {nid: "gpu-0" for nid in basic_graph.nodes}
    dp = DesignPoint("comparison", sys_arch, mapping)
    
    for fidelity in ["L1", "L2"]:
        result = evaluator.evaluate(dp, basic_graph, force_fidelity=fidelity)
        print(f"  {fidelity:3s}: latency={result['latency_ms']:.4f}ms  "
              f"power={result['power_w']:.1f}W  {result['fidelity_description']}")
    
    # L3 with generic backend
    result_l3 = generic_backend.evaluate(dp, basic_graph)
    print(f"  L3 : latency={result_l3['latency_ms']:.4f}ms  "
          f"power={result_l3['power_w']:.1f}W  Generic SystemC simulation")
    
    # 7. Scaling Analysis
    print("\n[7] Scaling Analysis (10 SCF iterations)")
    print("-" * 80)
    
    if best:
        print(f"  Single iteration: {best['latency_ms']:.2f} ms")
        print(f"  10 iterations: {best['latency_ms'] * 10:.2f} ms ({best['latency_ms'] * 10 / 1000:.2f} s)")
        print(f"  Total energy: {best['energy_j'] * 10:.2f} J")
    
    # 8. Fidelity Statistics
    print("\n[8] Fidelity Usage Statistics")
    print("-" * 80)
    
    stats = evaluator.get_fidelity_statistics()
    if stats:
        print(f"  Total evaluations: {stats['total_evaluations']}")
        print(f"  L1 (Fast): {stats['l1_count']} ({stats['l1_percentage']:.1f}%)")
        print(f"  L2 (TLM):  {stats['l2_count']} ({stats['l2_percentage']:.1f}%)")
    
    print("\n" + "=" * 80)
    print("Report Complete")
    print("=" * 80)
    
    print("\n[Next Steps]")
    print("-" * 80)
    print("1. Build gem5 with GenericAccel device model")
    print("2. Integrate gem5 + SystemC co-simulation (L4)")
    print("3. Add more operation models (stencil, conv2d)")
    print("4. Calibrate timing models with real hardware data")
    print("5. Add visualization tools for execution traces")


if __name__ == "__main__":
    sys.exit(generate_report())
