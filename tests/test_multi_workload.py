#!/usr/bin/env python3

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dse_v2.orchestrator import ThreeLayerOrchestrator
from interfaces.types import DesignPoint, ResourceLimits, WorkloadSpecialization


def make_design_point(workload_id: str, dominant_solver: str) -> DesignPoint:
    return DesignPoint(
        design_point_id=f'dp_f4_{workload_id}',
        family='F4',
        topology_type='mesh_2d',
        parameters={
            'system_level': {
                'family': 'F4',
                'n_gemm_tiles': 4,
                'n_eigen_tiles': 1,
                'tile_local_mem_kb': 512,
                'parallel_units': 4,
                'pipeline_depth': 4,
                'pcie_bw_gbps': 64.0,
                'dram_bw_gbps': 128.0,
                'max_power_w': 75.0,
            }
        },
        workload_specialization=WorkloadSpecialization(
            workload_id=workload_id,
            kernels=['h_psi', 'cdiaghg', 'reduction', 'refresh'],
            precision='FP64',
            dominant_solver=dominant_solver,
        ),
        target_layers=['L1', 'L2', 'L3'],
        resource_limits=ResourceLimits(max_area_mm2=140.0, max_power_w=75.0, max_latency_ms=2000.0),
        constraints={'max_power_w': 75.0, 'max_latency_ms': 2000.0},
        provenance={'input_hash': 'e' * 64, 'generated_at': '2026-01-01T00:00:00', 'tool_version': 'pytest'},
    )


WORKLOADS = [
    (
        'si8_pbe_uspp_hpsi',
        {'npw': 4096, 'nkb': 96, 'm': 32, 'iterations': 6, 'kernel_mix': {'h_psi': 0.84, 'cdiaghg': 0.07, 'reduction': 0.04, 'refresh': 0.05}},
        'h_psi',
        'cdiaghg',
    ),
    (
        'si4_pbe_uspp_cdiaghg',
        {'npw': 512, 'nkb': 1024, 'm': 64, 'iterations': 4, 'kernel_mix': {'h_psi': 0.18, 'cdiaghg': 0.72, 'reduction': 0.05, 'refresh': 0.05}},
        'cdiaghg',
        'h_psi',
    ),
]


@pytest.mark.parametrize('workload_id, workload, dominant_kernel, secondary_kernel', WORKLOADS)
def test_workloads_specialize_to_the_expected_kernel_mix(workload_id, workload, dominant_kernel, secondary_kernel):
    orchestrator = ThreeLayerOrchestrator()
    point = make_design_point(workload_id, dominant_kernel)
    result = orchestrator.evaluate_design_point(point, workload)

    assert result.fidelity_level_achieved in {'L1', 'L2', 'L3'}
    assert result.metrics['latency_ms'] > 0.0
    assert point.workload_specialization.dominant_solver == dominant_kernel
    if len(result.layer_results) >= 2:
        l2 = result.layer_results[1]
        assert l2.metrics['latency_ms'] > 0.0
        assert l2.metrics['throughput_gops'] > 0.0
        assert l2.metrics[f'{dominant_kernel}_latency_ms'] > l2.metrics[f'{secondary_kernel}_latency_ms']


def test_h_psi_dominant_and_cdiaghg_heavy_workloads_diverge_in_latency_profile():
    orchestrator = ThreeLayerOrchestrator()
    h_psi_result = orchestrator.evaluate_design_point(make_design_point('si8_pbe_uspp_hpsi', 'h_psi'), WORKLOADS[0][1])
    cdiaghg_result = orchestrator.evaluate_design_point(make_design_point('si4_pbe_uspp_cdiaghg', 'cdiaghg'), WORKLOADS[1][1])

    if len(h_psi_result.layer_results) >= 2:
        assert h_psi_result.layer_results[1].metrics['h_psi_latency_ms'] > h_psi_result.layer_results[1].metrics['cdiaghg_latency_ms']
    if len(cdiaghg_result.layer_results) >= 2:
        assert cdiaghg_result.layer_results[1].metrics['cdiaghg_latency_ms'] > cdiaghg_result.layer_results[1].metrics['h_psi_latency_ms']
    assert h_psi_result.metrics['latency_ms'] != cdiaghg_result.metrics['latency_ms']
    assert h_psi_result.promotion_recommendation in {'hold', 'promote'}
    assert cdiaghg_result.promotion_recommendation in {'hold', 'promote'}
