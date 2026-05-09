#!/usr/bin/env python3
"""DFT Workload Evaluation Demo

Demonstrates the generic DSE framework with a realistic DFT (SCF iteration) workload.
Shows how the framework evaluates different accelerator configurations.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dse_v2.core.architecture.accelerator import (
    Accelerator, SystemArchitecture, ComputeCapability, MemoryHierarchy,
    MemoryLevel, CommunicationCapability, PeerLink, HostLink, PowerModel,
    create_gpu_a100, create_fpga_u280, create_cim_array,
)
from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode, DataEdge, TensorSpec
from dse_v2.core.ir.task_graph import map_compute_to_tasks
from dse_v2.dse.orchestrator import SearchSpace, AnalyticalEvaluator, DSEOrchestrator, DesignPoint


def create_realistic_dft_graph() -> ComputeGraph:
    """Create a realistic DFT SCF iteration graph.
    
    Based on QE subspace diagonalization with:
    - npw = 2945 (plane waves)
    - nkb = 144 (k-points × bands)
    - m = 16 (subspace dimension)
    """
    graph = ComputeGraph(
        graph_id="qe_scf_iter",
        metadata={
            "domain": "dft",
            "solver": "scf",
            "description": "QE subspace diagonalization iteration",
            "npw": 2945,
            "nkb": 144,
            "m": 16,
        },
    )
    
    npw, nkb, m = 2945, 144, 16
    
    # Node 1: h_psi - Apply Hamiltonian (GEMM)
    # H @ psi: (npw × npw) @ (npw × nkb) -> bottleneck
    h_psi_flops = 2.0 * npw * npw * nkb
    h_psi_memory = (npw*npw + npw*nkb + npw*nkb) * 8
    graph.add_node(ComputeNode(
        node_id="h_psi",
        op_type="gemm",
        inputs=["H", "psi"],
        outputs=["h_psi_out"],
        input_specs={
            "H": TensorSpec(shape=(npw, npw), dtype="FP64"),
            "psi": TensorSpec(shape=(npw, nkb), dtype="FP64"),
        },
        output_specs={"h_psi_out": TensorSpec(shape=(npw, nkb), dtype="FP64")},
        estimated_flops=h_psi_flops,
        estimated_memory_bytes=h_psi_memory,
        attributes={"description": "Apply Hamiltonian to wavefunctions"},
    ))
    
    # Node 2: build_H_sub - Build reduced Hamiltonian
    # psi^T @ h_psi: (nkb × npw) @ (npw × nkb) -> (nkb × nkb)
    build_H_flops = 2.0 * nkb * npw * nkb
    build_H_memory = (nkb*npw + npw*nkb + nkb*nkb) * 8
    graph.add_node(ComputeNode(
        node_id="build_H_sub",
        op_type="reduction",
        inputs=["psi", "h_psi_out"],
        outputs=["H_sub"],
        input_specs={
            "psi": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "h_psi_out": TensorSpec(shape=(npw, nkb), dtype="FP64"),
        },
        output_specs={"H_sub": TensorSpec(shape=(nkb, nkb), dtype="FP64")},
        estimated_flops=build_H_flops,
        estimated_memory_bytes=build_H_memory,
        attributes={"description": "Build reduced subspace Hamiltonian"},
    ))
    
    # Node 3: diagonalize - Solve eigenvalue problem
    # Generalized Hermitian eigensolver: O(nkb^3)
    diag_flops = (nkb ** 3) * 4.0  # More accurate for generalized problem
    diag_memory = (nkb*nkb + nkb + nkb*nkb) * 8
    graph.add_node(ComputeNode(
        node_id="diagonalize",
        op_type="eigen",
        inputs=["H_sub"],
        outputs=["eigenvalues", "eigenvectors"],
        input_specs={"H_sub": TensorSpec(shape=(nkb, nkb), dtype="FP64")},
        output_specs={
            "eigenvalues": TensorSpec(shape=(nkb,), dtype="FP64"),
            "eigenvectors": TensorSpec(shape=(nkb, nkb), dtype="FP64"),
        },
        estimated_flops=diag_flops,
        estimated_memory_bytes=diag_memory,
        attributes={"description": "Generalized Hermitian eigensolver"},
    ))
    
    # Node 4: refresh - Update wavefunctions
    # psi @ eigenvectors: (npw × nkb) @ (nkb × nkb)
    refresh_flops = 2.0 * npw * nkb * nkb
    refresh_memory = (npw*nkb + nkb*nkb + npw*nkb) * 8
    graph.add_node(ComputeNode(
        node_id="refresh",
        op_type="gemm",
        inputs=["psi", "eigenvectors"],
        outputs=["psi_new"],
        input_specs={
            "psi": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "eigenvectors": TensorSpec(shape=(nkb, nkb), dtype="FP64"),
        },
        output_specs={"psi_new": TensorSpec(shape=(npw, nkb), dtype="FP64")},
        estimated_flops=refresh_flops,
        estimated_memory_bytes=refresh_memory,
        attributes={"description": "Update wavefunctions from eigenvectors"},
    ))
    
    # Edges
    graph.add_edge(DataEdge("h_psi", "build_H_sub", "h_psi_out",
                           TensorSpec(shape=(npw, nkb), dtype="FP64")))
    graph.add_edge(DataEdge("build_H_sub", "diagonalize", "H_sub",
                           TensorSpec(shape=(nkb, nkb), dtype="FP64")))
    graph.add_edge(DataEdge("diagonalize", "refresh", "eigenvectors",
                           TensorSpec(shape=(nkb, nkb), dtype="FP64")))
    
    return graph


def evaluate_single_accelerator(graph: ComputeGraph, accel: Accelerator) -> dict:
    """Evaluate workload on a single accelerator."""
    sys_arch = SystemArchitecture(
        system_id=f"single_{accel.accel_id}",
        accelerators=[accel],
    )
    
    mapping = {node_id: accel.accel_id for node_id in graph.nodes}
    
    dp = DesignPoint(
        design_point_id=f"dp_{accel.accel_id}",
        system_architecture=sys_arch,
        task_mapping=mapping,
    )
    
    evaluator = AnalyticalEvaluator()
    result = evaluator.evaluate(dp, graph)
    
    return {
        "accelerator": accel.accel_id,
        "type": accel.accel_type,
        "latency_ms": result["latency_ms"],
        "throughput_gops": result["throughput_gops"],
        "power_w": result["power_w"],
        "energy_j": result["energy_j"],
        "data_movement_mb": result.get("total_data_movement_mb", 0.0),
    }


def main():
    print("=" * 80)
    print("DFT Workload Evaluation Demo")
    print("=" * 80)
    
    # 1. Create workload
    print("\n[1] Creating DFT workload...")
    dft_graph = create_realistic_dft_graph()
    print(f"  Graph: {dft_graph.graph_id}")
    print(f"  Operations: {len(dft_graph.nodes)}")
    print(f"  Total FLOPs: {dft_graph.total_flops()/1e9:.2f} GFLOPs")
    print(f"  Total Memory: {dft_graph.total_memory_bytes()/1e6:.2f} MB")
    
    # Show operation breakdown
    print("\n  Operation breakdown:")
    for node_id, node in dft_graph.nodes.items():
        print(f"    {node_id:15s} {node.op_type:12s} {node.estimated_flops/1e9:8.2f} GFLOPs  "
              f"{node.estimated_memory_bytes/1e6:8.2f} MB")
    
    # 2. Define accelerators
    print("\n[2] Defining accelerators...")
    gpu = create_gpu_a100("gpu-0")
    fpga = create_fpga_u280("fpga-0")
    cim = create_cim_array("cim-0")
    
    accelerators = [gpu, fpga, cim]
    for accel in accelerators:
        fp64_flops = accel.compute.get_peak_flops("FP64")
        print(f"  {accel.accel_id:10s} ({accel.accel_type:6s}): {fp64_flops/1e12:.2f} TFLOPS (FP64)")
    
    # 3. Single accelerator evaluation
    print("\n[3] Single-accelerator evaluation:")
    print("-" * 80)
    print(f"{'Accelerator':<12s} {'Latency (ms)':<14s} {'Throughput':<14s} {'Power (W)':<10s} {'Energy (J)':<12s}")
    print("-" * 80)
    
    single_results = []
    for accel in accelerators:
        result = evaluate_single_accelerator(dft_graph, accel)
        single_results.append(result)
        print(f"{result['accelerator']:<12s} {result['latency_ms']:<14.2f} "
              f"{result['throughput_gops']:<14.2f} {result['power_w']:<10.1f} {result['energy_j']:<12.2f}")
    
    # 4. Multi-accelerator DSE
    print("\n[4] Multi-accelerator DSE:")
    print("-" * 80)
    
    ss = SearchSpace(
        accelerator_options=accelerators,
        max_accelerators=3,
        max_power_w=1000.0,
    )
    
    evaluator = AnalyticalEvaluator()
    orchestrator = DSEOrchestrator(ss, evaluator)
    pareto_results = orchestrator.explore(dft_graph, max_points=50)
    
    print(f"  Design points explored: {len(orchestrator.results)}")
    print(f"  Pareto-optimal points: {len(pareto_results)}")
    
    # Show top 5 designs by latency
    print("\n  Top 5 designs (by latency):")
    sorted_results = sorted(orchestrator.results, key=lambda r: r["latency_ms"])
    print(f"{'Rank':<6s} {'Latency (ms)':<14s} {'Throughput':<14s} {'Power (W)':<10s} {'Energy (J)':<12s} {'Data (MB)':<10s} {'Feasible':<8s}")
    print("-" * 90)
    for i, result in enumerate(sorted_results[:5]):
        print(f"{i+1:<6d} {result['latency_ms']:<14.2f} {result['throughput_gops']:<14.2f} "
              f"{result['power_w']:<10.1f} {result['energy_j']:<12.2f} {result['total_data_movement_mb']:<10.2f} {'Yes' if result['feasible'] else 'No':<8s}")
    
    print("\n  Designs with highest data movement:")
    sorted_by_data = sorted(orchestrator.results, key=lambda r: r["total_data_movement_mb"], reverse=True)
    for i, result in enumerate(sorted_by_data[:3]):
        print(f"    {result['design_point_id']}: latency={result['latency_ms']:.2f}ms data={result['total_data_movement_mb']:.2f}MB")
    
    # 5. Best design details
    print("\n[5] Best design point details:")
    best = orchestrator.get_best_design("latency")
    if best:
        print(f"  Latency: {best['latency_ms']:.2f} ms")
        print(f"  Throughput: {best['throughput_gops']:.2f} GOPS")
        print(f"  Power: {best['power_w']:.1f} W")
        print(f"  Energy: {best['energy_j']:.2f} J")
        print(f"  Data movement: {best['total_data_movement_mb']:.2f} MB")
        print(f"  Compute efficiency: {best['compute_efficiency']:.2%}")
        print(f"  Memory efficiency: {best['memory_efficiency']:.2%}")
    
    # 6. Scaling analysis
    print("\n[6] Scaling analysis (10 SCF iterations):")
    if best:
        total_latency = best['latency_ms'] * 10
        total_energy = best['energy_j'] * 10
        print(f"  Single iteration: {best['latency_ms']:.2f} ms")
        print(f"  10 iterations: {total_latency:.2f} ms ({total_latency/1000:.2f} s)")
        print(f"  Total energy: {total_energy:.2f} J")
    
    print("\n" + "=" * 80)
    print("Evaluation complete!")
    print("=" * 80)


if __name__ == "__main__":
    sys.exit(main())
