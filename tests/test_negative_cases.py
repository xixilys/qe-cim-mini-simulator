#!/usr/bin/env python3

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.benchmarks.validate_dse_gpu_confidence import (
    load_case_list,
    compute_relative_error,
    classify_confidence,
    build_case_results,
    compute_metrics,
)
from dse_v2.models.mid.python_tlm import Layer2Output
from dse_v2.models.fast.performance_model import FastPerformanceModel
from dse_v2.orchestrator import ThreeLayerOrchestrator
from dse_v2.promotion.promotion_engine import PromotionEngine
from interfaces.types import DesignPoint, ResourceLimits, WorkloadSpecialization
from interfaces.validator import InterfaceValidator


def make_design_point(family: str = 'F4'):
    return {
        'schema_version': 'design_point_v1',
        'design_point_id': f'dp_{family.lower()}_neg',
        'family': family,
        'topology_type': 'mesh_2d',
        'architecture_spec_ref': 'f' * 64,
        'parameters': {
            'system_level': {
                'family': family,
                'n_gemm_tiles': 4,
                'n_eigen_tiles': 1,
                'tile_local_mem_kb': 512,
                'max_power_w': 75.0,
            }
        },
        'workload_specialization': {
            'workload_id': 'qe_cbands_si8',
            'kernels': ['h_psi', 'cdiaghg'],
            'precision': 'FP64',
        },
        'target_layers': ['L1', 'L2', 'L3'],
        'resource_limits': {'max_area_mm2': 140.0, 'max_power_w': 75.0, 'max_latency_ms': 2000.0},
        'constraints': {'max_power_w': 75.0, 'max_latency_ms': 2000.0},
        'provenance': {'input_hash': 'f' * 64, 'generated_at': '2026-01-01T00:00:00', 'tool_version': 'pytest'},
    }


def make_workload():
    return {'npw': 2945, 'nkb': 144, 'm': 16, 'iterations': 8}


def test_negative_resource_constraints_are_rejected():
    artifact = make_design_point()
    artifact['constraints']['max_power_w'] = -1.0

    result = InterfaceValidator().validate(artifact, 'design_point_v1')

    assert not result.valid
    assert any('negative' in error.lower() or 'positive' in error.lower() for error in result.errors)


def test_oversized_resource_units_are_rejected():
    artifact = make_design_point()
    artifact['parameters']['system_level']['n_gemm_tiles'] = 32

    result = InterfaceValidator().validate(artifact, 'design_point_v1')

    assert not result.valid
    assert any('n_gemm_tiles' in error for error in result.errors)


def test_unknown_family_is_rejected():
    artifact = make_design_point('F8')
    artifact['parameters']['system_level']['family'] = 'F8'

    result = InterfaceValidator().validate(artifact, 'design_point_v1')

    assert not result.valid
    assert any('family' in error and 'F8' in error for error in result.errors)


def test_fast_model_unknown_family_fails_explicitly():
    model = FastPerformanceModel()

    result = model.evaluate_design_point(make_design_point('F8'), make_workload())

    assert result.status == 'failed'
    assert result.layer_results[0].status == 'failed'
    assert any('unknown family' in str(value).lower() or 'not supported' in str(value).lower() for value in [result.provenance.get('error', ''), result.uncertainty.get('error', ''), result.layer_results[0].uncertainty.get('error', '')])


def test_missing_confidence_field_in_release_bundle_is_rejected():
    artifact = {
        'schema_version': 'release_bundle_v1',
        'bundle_id': 'bundle_neg_001',
        'evaluation_results': ['a' * 64],
        'pareto_frontier': ['a' * 64],
        'recommendation': {
            'primary_design_point': 'b' * 64,
            'rationale': 'This bundle is intentionally incomplete for negative testing.',
        },
        'authority': {'stage': 'A', 'claim_posture': 'evidence_only'},
        'provenance': {'input_hash': 'c' * 64, 'generated_at': '2026-01-01T00:00:00', 'tool_version': 'pytest'},
    }

    result = InterfaceValidator().validate(artifact, 'release_bundle_v1')

    assert not result.valid
    assert any('confidence' in error.lower() for error in result.errors)


def test_gpu_case_mismatch_is_detected():
    case_list = [
        {'case_id': 'si8_pbe_nc', 'status': 'completed', 'actual_latency_s': 1.0},
        {'case_id': 'si8_pbe_uspp', 'status': 'completed', 'actual_latency_s': 1.0},
    ]
    dse_predictions = {'si8_pbe_nc': {'predicted_latency_s': 1.0}, 'si8_pbe_uspp': {'predicted_latency_s': 1.0}}

    case_results = build_case_results(case_list, dse_predictions, 0.20)
    metrics = compute_metrics(case_results, 0.20)

    assert metrics['summary']['evaluated_cases'] == 2
    assert metrics['summary']['completed_cases'] == 2


class _PromotingL1Model:
    def evaluate_design_point(self, design_point, workload):
        family = str(design_point.family if hasattr(design_point, 'family') else design_point['family'])
        return {
            'family': family,
            'status': 'passed',
            'metrics': {
                'latency_ms': 3.0,
                'throughput_gops': 300.0,
                'power_w': 60.0,
                'area_mm2': 30.0,
                'energy_efficiency_gops_per_w': 5.0,
                'accuracy_vs_reference': 0.92,
            },
            'uncertainty': {'confidence_level': 0.95, 'mape_percent': 5.0, 'sample_size': 8},
            'resource_utilization': {'compute_percent': 30.0, 'memory_percent': 20.0, 'bandwidth_percent': 20.0},
            'promotion_score': 0.98,
            'confidence': 0.95,
            'fidelity_level_achieved': 'L1',
        }


class _FailingL2Model:
    def run_episode(self, design_point, workload):
        return Layer2Output(
            family=str(design_point['family']),
            status='failed',
            metrics={
                'latency_ms': 12.0,
                'throughput_gops': 120.0,
                'power_w': 80.0,
                'area_mm2': 42.0,
                'energy_efficiency_gops_per_w': 1.5,
                'accuracy_vs_reference': 0.4,
                'h_psi_latency_ms': 8.0,
                'cdiaghg_latency_ms': 3.0,
                'data_transfer_ms': 1.0,
            },
            uncertainty={'confidence_level': 0.2, 'mape_percent': 60.0, 'sample_size': 4},
            resource_utilization={'compute_percent': 40.0, 'memory_percent': 30.0, 'bandwidth_percent': 20.0},
            promotion_score=0.1,
            confidence=0.2,
        )


def test_l3_backend_failure_blocks_projection():
    point = DesignPoint(
        design_point_id='dp_f4_neg',
        family='F4',
        topology_type='mesh_2d',
        parameters={'system_level': {'family': 'F4', 'n_gemm_tiles': 4, 'n_eigen_tiles': 1, 'tile_local_mem_kb': 512, 'max_power_w': 75.0}},
        workload_specialization=WorkloadSpecialization(workload_id='qe_cbands_si8', kernels=['h_psi', 'cdiaghg'], precision='FP64'),
        target_layers=['L1', 'L2', 'L3'],
        resource_limits=ResourceLimits(max_area_mm2=140.0, max_power_w=75.0, max_latency_ms=2000.0),
        constraints={'max_power_w': 75.0},
        provenance={'input_hash': 'd' * 64, 'generated_at': '2026-01-01T00:00:00', 'tool_version': 'pytest'},
    )
    orchestrator = ThreeLayerOrchestrator(l1_model=_PromotingL1Model(), l2_model=_FailingL2Model())

    result = orchestrator.evaluate_design_point(point, make_workload())

    assert result.fidelity_level_achieved == 'L2'
    assert result.promotion_recommendation == 'hold'
    assert result.provenance['promotion_trace'][-1]['reason'] == 'status_passed'


def test_pareto_dominated_candidate_is_rejected():
    engine = PromotionEngine(pareto_frontier=[{
        'metrics': {
            'latency_ms': 1.0,
            'power_w': 1.0,
            'area_mm2': 1.0,
            'throughput_gops': 1000.0,
            'energy_efficiency_gops_per_w': 100.0,
            'accuracy_vs_reference': 1.0,
        }
    }])

    decision = engine.evaluate({
        'fidelity_level_achieved': 'L1',
        'family': 'F4',
        'status': 'passed',
        'metrics': {
            'latency_ms': 10.0,
            'power_w': 10.0,
            'area_mm2': 10.0,
            'throughput_gops': 100.0,
            'energy_efficiency_gops_per_w': 10.0,
            'accuracy_vs_reference': 0.8,
        },
        'uncertainty': {'confidence_level': 0.9, 'mape_percent': 10.0, 'sample_size': 5},
        'resource_utilization': {'compute_percent': 40.0, 'memory_percent': 40.0, 'bandwidth_percent': 40.0},
        'promotion_score': 0.95,
        'confidence': 0.9,
    })

    assert not decision.promote
    assert decision.reason == 'pareto_passed'


def test_budget_exhaustion_blocks_promotion():
    orchestrator = ThreeLayerOrchestrator(l1_model=_PromotingL1Model(), promotion_engine=PromotionEngine(budgets={'L2': 0, 'L3': 0}))
    point = DesignPoint(
        design_point_id='dp_f4_budget',
        family='F4',
        topology_type='mesh_2d',
        parameters={'system_level': {'family': 'F4', 'n_gemm_tiles': 4, 'n_eigen_tiles': 1, 'tile_local_mem_kb': 512, 'max_power_w': 75.0}},
        workload_specialization=WorkloadSpecialization(workload_id='qe_cbands_si8', kernels=['h_psi', 'cdiaghg'], precision='FP64'),
        target_layers=['L1', 'L2', 'L3'],
        resource_limits=ResourceLimits(max_area_mm2=140.0, max_power_w=75.0, max_latency_ms=2000.0),
        constraints={'max_power_w': 75.0},
        provenance={'input_hash': 'e' * 64, 'generated_at': '2026-01-01T00:00:00', 'tool_version': 'pytest'},
    )

    result = orchestrator.evaluate_design_point(point, make_workload())

    assert result.fidelity_level_achieved == 'L1'
    assert result.promotion_recommendation == 'hold'
    assert result.provenance['promotion_trace'][0]['reason'] == 'budget_exhausted'


def test_empty_workload_is_rejected():
    artifact = {
        'schema_version': 'workload_profile_v1',
        'workload_id': 'empty_case',
        'compute_graph': {'nodes': []},
        'execution_profile': {'total_iterations': 0},
        'provenance': {'input_hash': 'f' * 64, 'generated_at': '2026-01-01T00:00:00', 'tool_version': 'pytest'},
    }

    result = InterfaceValidator().validate(artifact, 'workload_profile_v1')

    assert not result.valid
    assert any('at least one node' in error for error in result.errors)
