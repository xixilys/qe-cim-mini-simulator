#!/usr/bin/env python3
"""End-to-end validation test for HW/SW co-design DSE framework.

Validates:
1. L1 fast model produces consistent results with mapping/dataflow
2. L2 Python TLM produces consistent results
3. L3 SystemC backend accepts mapping/dataflow config
4. GPU baseline produces full SCF results
5. All three layers produce reasonable relative results
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from interfaces.types import (
    ArchitectureSpec, DataflowSpec, DesignPoint, MappingSpec, ResourceLimits, WorkloadSpec,
)
from dse_v2.orchestrator import ThreeLayerOrchestrator
from dse_v2.backends.gpu_baseline import run_gpu_baseline
from dse_v2.backends.systemc_backend import SystemCBackend


def test_l1_l2_consistency():
    print("Testing L1/L2 consistency...")
    orch = ThreeLayerOrchestrator()

    dp = DesignPoint(
        design_point_id='dp_consistency',
        architecture=ArchitectureSpec(family='F4', gemm_tiles=8, eigen_tiles=2),
        mapping=MappingSpec(),
        dataflow=DataflowSpec(),
        workload=WorkloadSpec(npw=1024, nkb=64, m=8, iterations=1),
        resource_limits=ResourceLimits(),
    )

    result = orch.evaluate_design_point(dp)

    assert result.fidelity_level_achieved in ['L1', 'L2', 'L3']
    assert result.metrics['latency_ms'] > 0
    assert result.metrics['throughput_gops'] > 0

    l1_latency = result.layer_results[0].metrics['latency_ms']
    print(f"  L1 latency: {l1_latency:.2f}ms")

    if len(result.layer_results) >= 2:
        l2_latency = result.layer_results[1].metrics['latency_ms']
        print(f"  L2 latency: {l2_latency:.2f}ms")
        ratio = max(l1_latency, l2_latency) / min(l1_latency, l2_latency)
        assert ratio < 10.0, f"L1/L2 ratio too large: {ratio:.1f}x"
        print(f"  L1/L2 ratio: {ratio:.2f}x (PASS)")
    else:
        print("  L2 not reached (promotion stopped)")

    print("  L1/L2 consistency: PASS")


def test_mapping_sensitivity():
    print("\nTesting mapping sensitivity across all layers...")
    orch = ThreeLayerOrchestrator()

    configs = [
        ('all_fpga', MappingSpec(operator_sweep='cluster_a', reduced_build='cluster_b', diag='cluster_c', refresh='cluster_d')),
        ('all_cpu', MappingSpec(operator_sweep='cpu', reduced_build='cpu', diag='cpu', refresh='cpu')),
        ('mixed', MappingSpec(operator_sweep='cluster_a', reduced_build='cpu', diag='cluster_c', refresh='cpu')),
    ]

    results = {}
    for name, mapping in configs:
        dp = DesignPoint(
            design_point_id=f'dp_{name}',
            architecture=ArchitectureSpec(family='F1'),
            mapping=mapping,
            dataflow=DataflowSpec(),
            workload=WorkloadSpec(npw=512, nkb=32, m=4, iterations=1),
            resource_limits=ResourceLimits(),
        )
        result = orch.evaluate_design_point(dp)
        results[name] = result.metrics['latency_ms']
        print(f"  {name}: {results[name]:.2f}ms")

    assert results['all_cpu'] > results['all_fpga'], "CPU mapping should be slower than FPGA"
    assert results['mixed'] > results['all_fpga'], "Mixed mapping should be slower than all FPGA"
    assert results['mixed'] < results['all_cpu'], "Mixed mapping should be faster than all CPU"
    print("  Mapping sensitivity: PASS")


def test_dataflow_sensitivity():
    print("\nTesting dataflow sensitivity...")
    orch = ThreeLayerOrchestrator()

    configs = [
        ('baseline', DataflowSpec(double_buffer=False, overlap_dma_compute=False, keep_resident=False)),
        ('double_buffer', DataflowSpec(double_buffer=True, overlap_dma_compute=False, keep_resident=False)),
        ('overlap', DataflowSpec(double_buffer=False, overlap_dma_compute=True, keep_resident=False)),
        ('all_on', DataflowSpec(double_buffer=True, overlap_dma_compute=True, keep_resident=True)),
    ]

    results = {}
    for name, dataflow in configs:
        dp = DesignPoint(
            design_point_id=f'dp_{name}',
            architecture=ArchitectureSpec(family='F3'),
            mapping=MappingSpec(),
            dataflow=dataflow,
            workload=WorkloadSpec(npw=512, nkb=32, m=4, iterations=2),
            resource_limits=ResourceLimits(),
        )
        result = orch.evaluate_design_point(dp)
        results[name] = result.metrics['latency_ms']
        print(f"  {name}: {results[name]:.2f}ms")

    assert results['all_on'] < results['baseline'], "All dataflow opts should improve over baseline"
    print("  Dataflow sensitivity: PASS")


def test_systemc_backend_config():
    print("\nTesting SystemC backend configuration...")
    backend = SystemCBackend()

    dp = DesignPoint(
        design_point_id='dp_sc',
        architecture=ArchitectureSpec(family='F4', max_power_w=75.0),
        mapping=MappingSpec(operator_sweep='cluster_a', diag='cluster_c'),
        dataflow=DataflowSpec(double_buffer=True),
        workload=WorkloadSpec(npw=2945, nkb=144, m=16, iterations=1),
        resource_limits=ResourceLimits(),
    )

    env = backend.build_environment(dp, dp.workload.to_dict())

    assert env['QEBS_ARCH_FAMILY'] == 'F4'
    assert env['QEBS_MAPPING_OPERATOR_SWEEP'] == 'cluster_a'
    assert env['QEBS_MAPPING_DIAG'] == 'cluster_c'
    assert env['QEBS_DATAFLOW_DOUBLE_BUFFER'] == '1'
    assert env['QEBS_DATAFLOW_OVERLAP'] == '0'
    print("  SystemC backend config: PASS")


def test_gpu_baseline_scf():
    print("\nTesting GPU baseline full SCF...")
    result = run_gpu_baseline("test_scf", 512, 32, 4, iterations=2, full_scf=True)

    assert result['success'], f"GPU baseline failed: {result.get('error')}"
    assert result['total_scf_latency_ms'] > 0
    assert len(result['scf_phases']) == 4

    print(f"  Total SCF latency: {result['total_scf_latency_ms']:.3f}ms")
    print(f"  Total GFLOPS: {result['total_scf_gflops']:.3f}")
    for phase in result['scf_phases']:
        print(f"    {phase['phase']}: {phase['latency_ms']:.3f}ms ({phase['throughput_gflops']:.3f} GFLOPS)")
    print("  GPU baseline SCF: PASS")


def test_cross_layer_comparison():
    print("\nTesting cross-layer comparison...")
    orch = ThreeLayerOrchestrator()

    dp = DesignPoint(
        design_point_id='dp_cross',
        architecture=ArchitectureSpec(family='F4', gemm_tiles=4, eigen_tiles=1),
        mapping=MappingSpec(),
        dataflow=DataflowSpec(),
        workload=WorkloadSpec(npw=512, nkb=32, m=4, iterations=1),
        resource_limits=ResourceLimits(),
    )

    result = orch.evaluate_design_point(dp)
    l1_latency = result.layer_results[0].metrics['latency_ms']

    gpu_result = run_gpu_baseline("cross_compare", 512, 32, 4, iterations=1, full_scf=True)
    gpu_latency = gpu_result['total_scf_latency_ms']

    print(f"  L1 latency: {l1_latency:.2f}ms")
    print(f"  GPU latency: {gpu_latency:.2f}ms")

    if gpu_latency > 0 and l1_latency > 0:
        ratio = max(l1_latency, gpu_latency) / min(l1_latency, gpu_latency)
        print(f"  L1/GPU ratio: {ratio:.1f}x")
        assert ratio < 1000.0, f"L1 and GPU results diverge too much: {ratio:.1f}x"
    print("  Cross-layer comparison: PASS")


def test_legacy_compatibility():
    print("\nTesting legacy DesignPoint compatibility...")
    orch = ThreeLayerOrchestrator()

    legacy_dp = {
        'design_point_id': 'dp_legacy',
        'family': 'F1',
        'topology_type': 'pipeline',
        'parameters': {
            'system_level': {
                'parallel_units': 4,
                'n_gemm_tiles': 4,
            }
        },
        'resource_limits': {'max_power_w': 80.0},
    }

    result = orch.evaluate_design_point(legacy_dp)
    assert result.fidelity_level_achieved in ['L1', 'L2', 'L3']
    assert result.metrics['latency_ms'] > 0
    print(f"  Legacy DP latency: {result.metrics['latency_ms']:.2f}ms")
    print("  Legacy compatibility: PASS")


def main():
    print("=" * 70)
    print("End-to-End Validation: HW/SW Co-Design DSE Framework")
    print("=" * 70)

    tests = [
        ("L1/L2 consistency", test_l1_l2_consistency),
        ("Mapping sensitivity", test_mapping_sensitivity),
        ("Dataflow sensitivity", test_dataflow_sensitivity),
        ("SystemC backend config", test_systemc_backend_config),
        ("GPU baseline SCF", test_gpu_baseline_scf),
        ("Cross-layer comparison", test_cross_layer_comparison),
        ("Legacy compatibility", test_legacy_compatibility),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            test_func()
            results.append((test_name, True))
        except Exception as e:
            print(f"\n  FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))

    print("\n" + "=" * 70)
    print("Validation Summary")
    print("=" * 70)

    all_passed = True
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {test_name}")
        if not result:
            all_passed = False

    print("=" * 70)

    if all_passed:
        print("\nAll validation tests passed!")
        return 0
    else:
        print("\nSome validation tests failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())