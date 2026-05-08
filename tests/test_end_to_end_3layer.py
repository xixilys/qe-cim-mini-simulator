#!/usr/bin/env python3

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dse_v2.models.fast.performance_model import FastPerformanceModel
from dse_v2.orchestrator import ThreeLayerOrchestrator
from dse_v2.promotion.promotion_engine import PromotionEngine
from interfaces.types import DesignPoint, ResourceLimits, WorkloadSpecialization

FAMILIES = ['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7']


def make_design_point(family: str, **overrides) -> DesignPoint:
    system_level = {
        'family': family,
        'n_gemm_tiles': 4,
        'n_eigen_tiles': 1,
        'tile_local_mem_kb': 512,
        'parallel_units': 4,
        'pipeline_depth': 4,
        'dataflow_pattern': 'streaming',
        'tile_npw': 1024,
        'tile_nkb': 64,
        'tile_m': 16,
        'intermediate_buffer_kb': 1024,
        'pcie_bw_gbps': 64.0,
        'dram_bw_gbps': 128.0,
        'max_power_w': 75.0,
    }
    system_level.update(overrides)
    return DesignPoint(
        design_point_id=f'dp_{family.lower()}_001',
        family=family,
        topology_type='mesh_2d',
        parameters={'system_level': system_level},
        workload_specialization=WorkloadSpecialization(
            workload_id='qe_cbands_si8',
            kernels=['h_psi', 'cdiaghg', 'reduction', 'refresh'],
            precision='FP64',
            dominant_solver='subspace_diagonalization',
        ),
        target_layers=['L1', 'L2', 'L3'],
        resource_limits=ResourceLimits(max_area_mm2=140.0, max_power_w=75.0, max_latency_ms=2000.0),
        constraints={'max_power_w': 75.0, 'max_latency_ms': 2000.0},
        provenance={'input_hash': 'c' * 64, 'generated_at': '2026-01-01T00:00:00', 'tool_version': 'pytest'},
    )


def workload_profile(kind: str = 'balanced'):
    if kind == 'h_psi_dominant':
        return {'npw': 4096, 'nkb': 96, 'm': 32, 'iterations': 6, 'kernel_mix': {'h_psi': 0.84, 'cdiaghg': 0.07, 'reduction': 0.04, 'refresh': 0.05}}
    if kind == 'cdiaghg_heavy':
        return {'npw': 1024, 'nkb': 512, 'm': 64, 'iterations': 4, 'kernel_mix': {'h_psi': 0.24, 'cdiaghg': 0.64, 'reduction': 0.06, 'refresh': 0.06}}
    return {'npw': 2945, 'nkb': 144, 'm': 16, 'iterations': 8, 'kernel_mix': {'h_psi': 0.68, 'cdiaghg': 0.23, 'reduction': 0.04, 'refresh': 0.05}}


@pytest.mark.parametrize('family', FAMILIES)
def test_end_to_end_pipeline_uses_family_l1_model_and_preserves_confidence(family):
    orchestrator = ThreeLayerOrchestrator(promotion_engine=PromotionEngine())
    design_point = make_design_point(family)
    workload = workload_profile()
    result = orchestrator.evaluate_design_point(design_point, workload)
    expected_l1 = FastPerformanceModel().evaluate_design_point(design_point, workload)

    assert result.design_point_id == f'dp_{family.lower()}_001'
    assert result.layer_results[0].model_used == expected_l1.layer_results[0].model_used
    assert result.layer_results[0].metrics['latency_ms'] == pytest.approx(expected_l1.metrics['latency_ms'], rel=1e-9)
    assert result.layer_results[0].uncertainty['confidence_level'] == pytest.approx(expected_l1.uncertainty['confidence_level'], rel=1e-9)
    assert result.layer_results[0].uncertainty['confidence_level'] > 0.0

    if result.fidelity_level_achieved == 'L3':
        assert result.promotion_recommendation == 'promote'
        assert [layer.layer_id for layer in result.layer_results] == ['L1', 'L2', 'L3']
        assert result.layer_results[1].model_used == 'layer2_tlm'
        assert result.layer_results[2].model_used == 'layer3_projection'
        assert result.layer_results[2].metrics['latency_ms'] < result.layer_results[1].metrics['latency_ms']
        assert result.layer_results[2].metrics['throughput_gops'] > result.layer_results[1].metrics['throughput_gops']
        assert result.layer_results[2].metrics['accuracy_vs_reference'] >= result.layer_results[1].metrics['accuracy_vs_reference']
        assert result.provenance['layer3_projection'] is True
        assert len(result.provenance['promotion_trace']) == 3
        assert result.metrics['latency_ms'] == result.layer_results[2].metrics['latency_ms']
        assert result.metrics['throughput_gops'] == result.layer_results[2].metrics['throughput_gops']
    else:
        assert result.fidelity_level_achieved == 'L1'
        assert result.promotion_recommendation == 'hold'
        assert [layer.layer_id for layer in result.layer_results] == ['L1']
        assert len(result.provenance['promotion_trace']) == 1
        assert result.metrics['latency_ms'] == result.layer_results[0].metrics['latency_ms']
        assert result.metrics['throughput_gops'] == result.layer_results[0].metrics['throughput_gops']

    assert result.status in {'passed', 'projection_only'}
    assert 0.0 <= result.promotion_score <= 1.0


def test_end_to_end_results_aggregate_across_all_families():
    orchestrator = ThreeLayerOrchestrator(promotion_engine=PromotionEngine())
    results = [orchestrator.evaluate_design_point(make_design_point(family), workload_profile()) for family in FAMILIES]
    direct_l1 = [FastPerformanceModel().evaluate_design_point(make_design_point(family), workload_profile()) for family in FAMILIES]

    summary = {
        'family_count': len(results),
        'promoted_count': sum(result.fidelity_level_achieved == 'L3' for result in results),
        'average_latency_ms': sum(result.layer_results[0].metrics['latency_ms'] for result in results) / len(results),
        'best_throughput_gops': max(result.layer_results[0].metrics['throughput_gops'] for result in results),
        'fidelities': {result.fidelity_level_achieved for result in results},
        'families': {result.design_point_id for result in results},
        'layer_counts': {len(result.layer_results) for result in results},
    }

    assert summary['family_count'] == 7
    assert summary['promoted_count'] >= 1
    assert summary['average_latency_ms'] > 0.0
    assert summary['best_throughput_gops'] > 0.0
    assert summary['fidelities'].issubset({'L1', 'L3'})
    assert summary['layer_counts'].issubset({1, 3})
    assert len(summary['families']) == 7
    assert len({round(result.layer_results[0].metrics['latency_ms'], 6) for result in results}) > 1
    for result, expected in zip(results, direct_l1):
        assert result.layer_results[0].model_used == expected.layer_results[0].model_used
        assert result.layer_results[0].metrics['latency_ms'] == pytest.approx(expected.metrics['latency_ms'], rel=1e-9)
        assert result.layer_results[0].uncertainty['confidence_level'] == pytest.approx(expected.uncertainty['confidence_level'], rel=1e-9)
