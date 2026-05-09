#!/usr/bin/env python3
"""Complete DFT Evaluation Report Generator."""

from __future__ import annotations

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


def generate_report():
    print("=" * 80)
    print("DFT Evaluation Report - Multi-Fidelity Framework")
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
    
    # 3. Single-Accelerator Performance (L1)
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
    
    # 5. TLM Evaluation (L2)
    print("\n[5] TLM Evaluation (L2 - Mid-Fidelity)")
    print("-" * 80)
    
    tlm_evaluator = MultiFidelityEvaluator(enable_systemc=False)
    
    for accel in accelerators:
        sys_arch = SystemArchitecture(
            system_id=f"single_{accel.accel_id}",
            accelerators=[accel],
        )
        mapping = {nid: accel.accel_id for nid in basic_graph.nodes}
        dp = DesignPoint(f"dp_{accel.accel_id}", sys_arch, mapping)
        
        result = tlm_evaluator.evaluate(dp, basic_graph, force_fidelity="L2")
        tlm_details = result.get("tlm_details", {})
        print(f"  {accel.accel_id:10s}: latency={result['latency_ms']:.2f}ms  "
              f"power={result['power_w']:.1f}W  confidence={tlm_details.get('confidence', 0):.2f}  "
              f"promotion={tlm_details.get('promotion_score', 0):.2f}")
    
    # 6. SystemC Evaluation (L3)
    print("\n[6] SystemC Evaluation (L3 - High-Fidelity)")
    print("-" * 80)
    
    systemc_evaluator = MultiFidelityEvaluator(enable_systemc=True)
    
    for accel in accelerators[:1]:  # Only test GPU for speed
        sys_arch = SystemArchitecture(
            system_id=f"single_{accel.accel_id}",
            accelerators=[accel],
        )
        mapping = {nid: accel.accel_id for nid in basic_graph.nodes}
        dp = DesignPoint(f"dp_{accel.accel_id}", sys_arch, mapping)
        
        result = systemc_evaluator.evaluate(dp, basic_graph, force_fidelity="L3")
        sc_details = result.get("systemc_details", {})
        print(f"  {accel.accel_id:10s}: latency={result['latency_ms']:.4f}ms  "
              f"cycles={sc_details.get('ref_cycles', 0)}  "
              f"convergence={sc_details.get('convergence', 'unknown')}")
    
    # 7. Fidelity Comparison
    print("\n[7] Fidelity Comparison")
    print("-" * 80)
    
    sys_arch = SystemArchitecture(
        system_id="comparison",
        accelerators=[gpu],
    )
    mapping = {nid: "gpu-0" for nid in basic_graph.nodes}
    dp = DesignPoint("comparison", sys_arch, mapping)
    
    for fidelity in ["L1", "L2", "L3"]:
        result = systemc_evaluator.evaluate(dp, basic_graph, force_fidelity=fidelity)
        print(f"  {fidelity:3s}: latency={result['latency_ms']:.4f}ms  "
              f"power={result['power_w']:.1f}W  {result['fidelity_description']}")
    
    # 8. Scaling Analysis
    print("\n[8] Scaling Analysis (10 SCF iterations)")
    print("-" * 80)
    
    if best:
        print(f"  Single iteration: {best['latency_ms']:.2f} ms")
        print(f"  10 iterations: {best['latency_ms'] * 10:.2f} ms ({best['latency_ms'] * 10 / 1000:.2f} s)")
        print(f"  Total energy: {best['energy_j'] * 10:.2f} J")
    
    # 9. Fidelity Statistics
    print("\n[9] Fidelity Usage Statistics")
    print("-" * 80)
    
    stats = systemc_evaluator.get_fidelity_statistics()
    if stats:
        print(f"  Total evaluations: {stats['total_evaluations']}")
        print(f"  L1 (Fast): {stats['l1_count']} ({stats['l1_percentage']:.1f}%)")
        print(f"  L2 (TLM):  {stats['l2_count']} ({stats['l2_percentage']:.1f}%)")
        print(f"  L3 (SystemC): {stats['l3_count']} ({stats['l3_percentage']:.1f}%)")
    
    print("\n" + "=" * 80)
    print("Report Complete")
    print("=" * 80)


if __name__ == "__main__":
    sys.exit(generate_report())
