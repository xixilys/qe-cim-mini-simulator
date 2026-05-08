#!/usr/bin/env python3
"""Tests for the new v2 DesignPoint with 4 orthogonal dimensions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from interfaces.types import (
    ArchitectureSpec, DataflowSpec, DesignPoint, EvaluationResult,
    LayerResult, MappingSpec, ResourceLimits, WorkloadSpec,
)
from dse_v2.orchestrator import ThreeLayerOrchestrator


def test_architecture_spec():
    print("Testing ArchitectureSpec...")
    arch = ArchitectureSpec(family='F4', topology_type='cim_dsp_hbm', clock_mhz=300)
    assert arch.family == 'F4'
    assert arch.topology_type == 'cim_dsp_hbm'
    assert arch.clock_mhz == 300.0
    assert arch.gemm_tiles == 4
    d = arch.to_dict()
    assert d['family'] == 'F4'
    print("  ArchitectureSpec: PASS")


def test_mapping_spec():
    print("Testing MappingSpec...")
    mapping = MappingSpec(
        operator_sweep='cluster_a',
        reduced_build='cluster_b',
        diag='cpu',
        refresh='cluster_d',
    )
    assert mapping.get_target('operator_sweep') == 'cluster_a'
    assert mapping.get_target('diag') == 'cpu'
    assert mapping.get_target('unknown') == 'cpu'
    d = mapping.to_dict()
    assert d['operator_sweep'] == 'cluster_a'
    print("  MappingSpec: PASS")


def test_dataflow_spec():
    print("Testing DataflowSpec...")
    df = DataflowSpec(double_buffer=True, overlap_dma_compute=True)
    assert df.double_buffer is True
    assert df.overlap_dma_compute is True
    assert df.keep_resident is False
    d = df.to_dict()
    assert d['double_buffer'] is True
    print("  DataflowSpec: PASS")


def test_workload_spec():
    print("Testing WorkloadSpec...")
    wl = WorkloadSpec(npw=2945, nkb=144, m=16, iterations=4)
    assert wl.npw == 2945
    assert wl.iterations == 4
    assert wl.kernel_mix['h_psi'] == 0.68
    d = wl.to_dict()
    assert d['npw'] == 2945
    print("  WorkloadSpec: PASS")


def test_design_point_v2():
    print("Testing DesignPoint v2...")
    dp = DesignPoint(
        design_point_id='dp_test_v2',
        architecture=ArchitectureSpec(family='F4'),
        mapping=MappingSpec(diag='cpu'),
        dataflow=DataflowSpec(double_buffer=True),
        workload=WorkloadSpec(iterations=4),
        resource_limits=ResourceLimits(max_power_w=80.0),
    )
    assert dp.schema_version == 'design_point_v2'
    assert dp.architecture.family == 'F4'
    assert dp.mapping.diag == 'cpu'
    assert dp.dataflow.double_buffer is True
    assert dp.workload.iterations == 4
    d = dp.to_dict()
    assert d['schema_version'] == 'design_point_v2'
    print("  DesignPoint v2: PASS")


def test_orchestrator_v2():
    print("Testing ThreeLayerOrchestrator with v2 DesignPoint...")
    orch = ThreeLayerOrchestrator()

    dp = DesignPoint(
        design_point_id='dp_f4_test',
        architecture=ArchitectureSpec(family='F4', gemm_tiles=8, eigen_tiles=2),
        mapping=MappingSpec(operator_sweep='cluster_a', reduced_build='cluster_b', diag='cluster_c', refresh='cluster_d'),
        dataflow=DataflowSpec(double_buffer=True, overlap_dma_compute=True),
        workload=WorkloadSpec(npw=2945, nkb=144, m=16, iterations=2),
        resource_limits=ResourceLimits(max_power_w=80.0, max_latency_ms=1000.0),
    )

    result = orch.evaluate_design_point(dp)
    assert isinstance(result, EvaluationResult)
    assert result.design_point_id == 'dp_f4_test'
    assert result.fidelity_level_achieved in ['L1', 'L2', 'L3']
    assert len(result.layer_results) >= 1
    assert 'latency_ms' in result.metrics
    assert result.metrics['latency_ms'] > 0
    print(f"  Orchestrator v2: PASS (fidelity={result.fidelity_level_achieved}, latency={result.metrics['latency_ms']:.2f}ms)")


def test_orchestrator_legacy_compat():
    print("Testing orchestrator backward compatibility...")
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
    assert isinstance(result, EvaluationResult)
    assert result.design_point_id == 'dp_legacy'
    print(f"  Legacy compatibility: PASS (fidelity={result.fidelity_level_achieved})")


def test_mapping_penalty():
    print("Testing mapping penalty calculation...")
    orch = ThreeLayerOrchestrator()

    dp_fpga = DesignPoint(
        design_point_id='dp_fpga',
        architecture=ArchitectureSpec(family='F1'),
        mapping=MappingSpec(operator_sweep='cluster_a', reduced_build='cluster_b', diag='cluster_c', refresh='cluster_d'),
        dataflow=DataflowSpec(),
        workload=WorkloadSpec(iterations=1),
        resource_limits=ResourceLimits(),
    )

    dp_cpu = DesignPoint(
        design_point_id='dp_cpu',
        architecture=ArchitectureSpec(family='F1'),
        mapping=MappingSpec(operator_sweep='cpu', reduced_build='cpu', diag='cpu', refresh='cpu'),
        dataflow=DataflowSpec(),
        workload=WorkloadSpec(iterations=1),
        resource_limits=ResourceLimits(),
    )

    result_fpga = orch.evaluate_design_point(dp_fpga)
    result_cpu = orch.evaluate_design_point(dp_cpu)

    assert result_cpu.metrics['latency_ms'] > result_fpga.metrics['latency_ms']
    print(f"  Mapping penalty: PASS (FPGA={result_fpga.metrics['latency_ms']:.2f}ms, CPU={result_cpu.metrics['latency_ms']:.2f}ms)")


def test_dataflow_speedup():
    print("Testing dataflow speedup calculation...")
    orch = ThreeLayerOrchestrator()

    dp_baseline = DesignPoint(
        design_point_id='dp_base',
        architecture=ArchitectureSpec(family='F1'),
        mapping=MappingSpec(),
        dataflow=DataflowSpec(double_buffer=False, overlap_dma_compute=False),
        workload=WorkloadSpec(iterations=2),
        resource_limits=ResourceLimits(),
    )

    dp_optimized = DesignPoint(
        design_point_id='dp_opt',
        architecture=ArchitectureSpec(family='F1'),
        mapping=MappingSpec(),
        dataflow=DataflowSpec(double_buffer=True, overlap_dma_compute=True, keep_resident=True),
        workload=WorkloadSpec(iterations=2),
        resource_limits=ResourceLimits(),
    )

    result_base = orch.evaluate_design_point(dp_baseline)
    result_opt = orch.evaluate_design_point(dp_optimized)

    assert result_opt.metrics['latency_ms'] < result_base.metrics['latency_ms']
    speedup = result_base.metrics['latency_ms'] / result_opt.metrics['latency_ms']
    print(f"  Dataflow speedup: PASS (baseline={result_base.metrics['latency_ms']:.2f}ms, optimized={result_opt.metrics['latency_ms']:.2f}ms, speedup={speedup:.2f}x)")


def test_scf_dag_phases():
    print("Testing SCF DAG phase tracking...")
    orch = ThreeLayerOrchestrator()

    dp = DesignPoint(
        design_point_id='dp_dag',
        architecture=ArchitectureSpec(family='F3'),
        mapping=MappingSpec(operator_sweep='cluster_a', reduced_build='cluster_b', diag='cluster_c', refresh='cluster_d'),
        dataflow=DataflowSpec(),
        workload=WorkloadSpec(npw=1024, nkb=64, m=8, iterations=1),
        resource_limits=ResourceLimits(),
    )

    result = orch.evaluate_design_point(dp)
    assert result.fidelity_level_achieved in ['L1', 'L2', 'L3']
    assert 'latency_ms' in result.metrics
    print(f"  SCF DAG phases: PASS (fidelity={result.fidelity_level_achieved})")


def main():
    print("=" * 70)
    print("DSE v2 DesignPoint v2 + SCF DAG Tests")
    print("=" * 70)

    tests = [
        ("ArchitectureSpec", test_architecture_spec),
        ("MappingSpec", test_mapping_spec),
        ("DataflowSpec", test_dataflow_spec),
        ("WorkloadSpec", test_workload_spec),
        ("DesignPoint v2", test_design_point_v2),
        ("Orchestrator v2", test_orchestrator_v2),
        ("Legacy compatibility", test_orchestrator_legacy_compat),
        ("Mapping penalty", test_mapping_penalty),
        ("Dataflow speedup", test_dataflow_speedup),
        ("SCF DAG phases", test_scf_dag_phases),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            test_func()
            results.append((test_name, True))
        except Exception as e:
            print(f"  FAILED: {e}")
            results.append((test_name, False))

    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)

    all_passed = True
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {test_name}")
        if not result:
            all_passed = False

    print("=" * 70)

    if all_passed:
        print("\nAll tests passed!")
        return 0
    else:
        print("\nSome tests failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())