#!/usr/bin/env python3
"""Integration test for the complete DSE v2 framework.

Tests the full stack:
1. Architecture description
2. Compute graph IR
3. Task graph IR
4. Execution IR
5. DSE orchestration
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dse_v2.core.architecture.accelerator import (
    Accelerator, SystemArchitecture,
    create_gpu_a100, create_fpga_u280, create_cim_array,
    create_example_system,
)
from dse_v2.core.ir.compute_graph import create_gemm_graph, create_dft_scf_graph
from dse_v2.core.ir.task_graph import map_compute_to_tasks
from dse_v2.core.ir.execution import create_example_timeline
from dse_v2.dse.orchestrator import SearchSpace, AnalyticalEvaluator, DSEOrchestrator


def test_architecture():
    print("Testing Architecture IR...")
    sys = create_example_system()
    assert len(sys.accelerators) == 3
    assert sys.total_compute_capacity("FP64") > 0
    print(f"  System: {sys.system_id}")
    print(f"  Accelerators: {len(sys.accelerators)}")
    print(f"  Total FP64: {sys.total_compute_capacity('FP64')/1e12:.1f} TFLOPS")
    print("  PASS")


def test_compute_graph():
    print("\nTesting Compute Graph IR...")
    
    # GEMM graph
    gemm = create_gemm_graph()
    assert len(gemm.nodes) == 4
    assert len(gemm.edges) == 3
    topo = gemm.topological_sort()
    assert len(topo) == 4
    print(f"  GEMM graph: {len(gemm.nodes)} nodes, {gemm.total_flops()/1e9:.2f} GFLOPs")
    
    # DFT graph
    dft = create_dft_scf_graph()
    assert dft.metadata.get("domain") == "dft"
    print(f"  DFT graph: {len(dft.nodes)} nodes, {dft.total_flops()/1e9:.2f} GFLOPs")
    print("  PASS")


def test_task_graph():
    print("\nTesting Task Graph IR...")
    cg = create_gemm_graph()
    mapping = {"A": "cpu", "B": "cpu", "gemm": "gpu-0", "bias": "gpu-0"}
    bandwidths = {("cpu", "gpu-0"): 64.0, ("gpu-0", "cpu"): 64.0}
    
    tg = map_compute_to_tasks(cg, mapping, bandwidths)
    assert len(tg.tasks) == 4
    
    # Set schedules for critical path test
    from dse_v2.core.ir.task_graph import TaskSchedule
    tg.tasks["task_A"].schedule = TaskSchedule(0, 0.1)
    tg.tasks["task_B"].schedule = TaskSchedule(0, 0.1)
    tg.tasks["task_gemm"].schedule = TaskSchedule(0.1, 10.1)
    tg.tasks["task_bias"].schedule = TaskSchedule(10.1, 10.2)
    
    cp = tg.critical_path()
    assert len(cp) > 0
    print(f"  Tasks: {len(tg.tasks)}")
    print(f"  Critical path: {cp}")
    print("  PASS")


def test_execution():
    print("\nTesting Execution IR...")
    timeline = create_example_timeline()
    summary = timeline.compute_summary()
    assert summary["total_duration_ms"] > 0
    print(f"  Duration: {summary['total_duration_ms']:.1f} ms")
    print(f"  Compute: {summary['total_compute_time_ms']:.1f} ms")
    print(f"  Transfer: {summary['total_transfer_time_ms']:.1f} ms")
    print("  PASS")


def test_dse():
    print("\nTesting DSE Orchestration...")
    cg = create_gemm_graph()
    
    ss = SearchSpace(
        accelerator_options=[create_gpu_a100("gpu-0"), create_fpga_u280("fpga-0")],
        max_accelerators=2,
        max_power_w=500.0,
    )
    
    evaluator = AnalyticalEvaluator()
    orchestrator = DSEOrchestrator(ss, evaluator)
    results = orchestrator.explore(cg, max_points=50)
    
    assert len(results) > 0
    best = orchestrator.get_best_design("latency")
    assert best is not None
    
    print(f"  Explored: {len(orchestrator.results)} points")
    print(f"  Pareto: {len(results)} points")
    print(f"  Best latency: {best.latency_ms:.2f} ms")
    print("  PASS")


def test_end_to_end():
    print("\nTesting End-to-End Integration...")
    
    # 1. Define workload
    dft = create_dft_scf_graph()
    print(f"  1. Workload: {dft.graph_id} ({len(dft.nodes)} ops)")
    
    # 2. Define architecture
    sys = create_example_system()
    print(f"  2. Architecture: {len(sys.accelerators)} accelerators")
    
    # 3. Define search space
    ss = SearchSpace(
        accelerator_options=sys.accelerators,
        max_accelerators=3,
        max_power_w=1000.0,
    )
    print(f"  3. Search space: up to {ss.max_accelerators} accelerators")
    
    # 4. Run DSE
    evaluator = AnalyticalEvaluator()
    orchestrator = DSEOrchestrator(ss, evaluator)
    results = orchestrator.explore(dft, max_points=20)
    
    print(f"  4. DSE complete: {len(results)} Pareto points")
    
    # 5. Show best design
    best = orchestrator.get_best_design("latency")
    if best:
        print(f"  5. Best design: {best.latency_ms:.2f} ms, {best.energy_j:.2f} J")
    
    print("  PASS")


def main():
    print("=" * 70)
    print("DSE v2 Framework Integration Test")
    print("=" * 70)
    
    tests = [
        ("Architecture IR", test_architecture),
        ("Compute Graph IR", test_compute_graph),
        ("Task Graph IR", test_task_graph),
        ("Execution IR", test_execution),
        ("DSE Orchestration", test_dse),
        ("End-to-End", test_end_to_end),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            test_func()
            results.append((name, True))
        except Exception as e:
            print(f"\n  FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    all_passed = True
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {name}")
        if not result:
            all_passed = False
    
    print("=" * 70)
    
    if all_passed:
        print("\nAll integration tests passed!")
        return 0
    else:
        print("\nSome tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())