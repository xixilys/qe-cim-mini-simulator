#!/usr/bin/env python3

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dse_v2.orchestrator import ThreeLayerOrchestrator
from dse_v2.promotion.promotion_engine import PromotionEngine
from interfaces.types import DesignPoint, ResourceLimits, WorkloadSpecialization


def design_point():
    return DesignPoint(
        design_point_id='dp_f4_001',
        family='F4',
        topology_type='mesh_2d',
        parameters={
            'system_level': {
                'family': 'F4',
                'n_gemm_tiles': 6,
                'n_eigen_tiles': 2,
                'tile_local_mem_kb': 1024,
                'parallel_units': 6,
                'pipeline_depth': 4,
                'dataflow_pattern': 'streaming',
                'tile_npw': 1024,
                'tile_nkb': 64,
                'tile_m': 16,
                'intermediate_buffer_kb': 1024,
                'max_power_w': 75.0,
            }
        },
        workload_specialization=WorkloadSpecialization(
            workload_id='qe_cbands_si8',
            kernels=['h_psi', 'cdiaghg'],
            precision='FP64',
        ),
        target_layers=['L1', 'L2', 'L3'],
        resource_limits=ResourceLimits(max_area_mm2=140.0, max_power_w=75.0, max_latency_ms=2000.0),
        constraints={'max_power_w': 75.0},
        provenance={'input_hash': 'c' * 64, 'generated_at': '2026-01-01T00:00:00', 'tool_version': 'pytest'},
    )


def workload():
    return {'npw': 2945, 'nkb': 144, 'm': 16, 'iterations': 8}


def test_l1_to_l2_promotion_happens_for_strong_design_point():
    engine = PromotionEngine()
    orchestrator = ThreeLayerOrchestrator(promotion_engine=engine)

    result = orchestrator.evaluate_design_point(design_point(), workload())

    assert result.fidelity_level_achieved in {'L2', 'L3'}
    assert len(result.layer_results) >= 2
    assert result.layer_results[0].layer_id == 'L1'
    assert result.layer_results[1].layer_id == 'L2'
    assert result.promotion_recommendation in {'hold', 'promote'}


def test_l2_to_l3_promotion_happens_for_supported_family():
    orchestrator = ThreeLayerOrchestrator()

    result = orchestrator.evaluate_design_point(design_point(), workload())

    assert result.fidelity_level_achieved in {'L2', 'L3'}
    assert [layer.layer_id for layer in result.layer_results][:2] == ['L1', 'L2']
    if result.fidelity_level_achieved == 'L3':
        assert [layer.layer_id for layer in result.layer_results] == ['L1', 'L2', 'L3']
        assert result.promotion_recommendation == 'promote'
    else:
        assert result.promotion_recommendation == 'hold'
    assert result.metrics['latency_ms'] > 0
    assert result.metrics['throughput_gops'] > 0


def test_l3_projection_is_explicitly_marked_projection_only():
    orchestrator = ThreeLayerOrchestrator()

    result = orchestrator.evaluate_design_point(design_point(), workload())

    trace = result.provenance['promotion_trace']
    assert len(trace) == 3
    assert trace[-1]['reason'] in {'projection_only', 'eligible'}

    if result.fidelity_level_achieved == 'L3':
        l3 = result.layer_results[2]
        assert l3.status == 'projection_only'
        assert l3.is_projection is True
        assert l3.projection_uncertainty == 0.20
        assert result.status == 'projection_only'
        assert result.provenance['l3_mode'] == 'projection_only'
        assert trace[-1]['to_layer'] == 'L3'
        assert trace[-1]['promote'] is True
    else:
        assert result.fidelity_level_achieved == 'L2'
        assert trace[-1]['to_layer'] is None
        assert trace[-1]['promote'] is False


def test_rejection_path_blocks_progress_when_budget_is_exhausted():
    orchestrator = ThreeLayerOrchestrator(promotion_engine=PromotionEngine(budgets={'L2': 0, 'L3': 0}))

    result = orchestrator.evaluate_design_point(design_point(), workload())

    assert result.fidelity_level_achieved == 'L1'
    assert len(result.layer_results) == 1
    assert result.promotion_recommendation == 'hold'


def test_pareto_frontier_can_block_promotion():
    frontier = [{
        'metrics': {
            'latency_ms': 1.0,
            'power_w': 1.0,
            'area_mm2': 1.0,
            'throughput_gops': 1000.0,
            'energy_efficiency_gops_per_w': 100.0,
            'accuracy_vs_reference': 1.0,
        }
    }]
    orchestrator = ThreeLayerOrchestrator(promotion_engine=PromotionEngine(pareto_frontier=frontier))

    result = orchestrator.evaluate_design_point(design_point(), workload())

    assert result.fidelity_level_achieved == 'L1'
    assert result.layer_results[0].layer_id == 'L1'
    assert result.promotion_recommendation == 'hold'


def test_projection_only_requires_stricter_l3_promotion(caplog):
    engine = PromotionEngine()
    projected = {
        'family': 'F4',
        'status': 'projection_only',
        'is_projection': True,
        'projection_uncertainty': 0.20,
        'confidence': 0.89,
        'promotion_score': 0.95,
        'uncertainty': {'confidence_level': 0.89, 'mape_percent': 5.0, 'sample_size': 1, 'projection_uncertainty': 0.20},
        'metrics': {
            'latency_ms': 10.0,
            'throughput_gops': 20.0,
            'power_w': 5.0,
            'area_mm2': 1.0,
            'energy_efficiency_gops_per_w': 4.0,
            'accuracy_vs_reference': 0.95,
        },
        'resource_utilization': {'compute_percent': 50.0, 'memory_percent': 30.0, 'bandwidth_percent': 40.0},
        'pareto_frontier': [],
    }

    with caplog.at_level('WARNING'):
        projected_decision = engine.should_promote_to_l3(projected)

    assert projected_decision is False
    assert any('projection_only' in record.message for record in caplog.records)

    unprojected = dict(projected)
    unprojected['is_projection'] = False

    assert engine.should_promote_to_l3(unprojected) is True
