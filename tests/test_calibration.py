#!/usr/bin/env python3

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dse_v2.models.fast.performance_model import FastPerformanceModel
from dse_v2.models.mid.python_tlm import PythonTLM
from dse_v2.orchestrator import ThreeLayerOrchestrator
from interfaces.types import DesignPoint, EvaluationResult, LayerResult, ResourceLimits, WorkloadSpecialization

FPGA_SPECS = {
    'peak_gflops': 1300,
    'memory_bw_gbs': 77,
    'pcie_bw_gbs': 16,
    'bram_kb': 34000,
    'dsp_count': 12288,
}

FAMILIES = ['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7']
FIXTURE_DIR = ROOT / 'tests' / 'fixtures' / 'data'


class LayerConfidenceOnlyModel:
    def evaluate_design_point(self, design_point, workload):
        layer = LayerResult(
            layer_id='L1',
            fidelity_level='L1',
            status='passed',
            metrics={'latency_ms': 1.0, 'throughput_gops': 10.0, 'power_w': 5.0, 'area_mm2': 4.0},
            uncertainty={'confidence_level': 0.87, 'mape_percent': 11.0, 'assumptions': ['layer_only_uncertainty']},
            resource_utilization={'compute_percent': 10.0, 'memory_percent': 10.0, 'bandwidth_percent': 10.0},
            promotion_score=0.9,
            model_used='LayerConfidenceOnlyModel',
        )
        return EvaluationResult(
            result_id='res_layer_confidence_only',
            design_point_id=str(design_point['design_point_id']),
            fidelity_level_achieved='L1',
            layer_results=[layer],
            promotion_recommendation='promote',
            promotion_score=0.9,
            metrics=dict(layer.metrics),
            status='passed',
            uncertainty={},
            resource_utilization=dict(layer.resource_utilization),
            provenance={'model_used': 'LayerConfidenceOnlyModel'},
        )


def make_design_point(family: str) -> DesignPoint:
    return DesignPoint(
        design_point_id=f'dp_{family.lower()}_cal',
        family=family,
        topology_type='mesh_2d',
        parameters={
            'system_level': {
                'family': family,
                'n_gemm_tiles': 2,
                'n_eigen_tiles': 1,
                'tile_local_mem_kb': 512,
                'parallel_units': 2,
                'pipeline_depth': 4,
                'pcie_bw_gbps': 64.0,
                'dram_bw_gbps': 128.0,
                'max_power_w': 75.0,
            }
        },
        workload_specialization=WorkloadSpecialization(workload_id='qe_cbands_si8', kernels=['h_psi', 'cdiaghg'], precision='FP64'),
        target_layers=['L1', 'L2', 'L3'],
        resource_limits=ResourceLimits(max_area_mm2=140.0, max_power_w=75.0, max_latency_ms=2000.0),
        constraints={'max_power_w': 75.0, 'max_latency_ms': 2000.0},
        provenance={'input_hash': 'f' * 64, 'generated_at': '2026-01-01T00:00:00', 'tool_version': 'pytest'},
    )


def workload():
    return {'npw': 1024, 'nkb': 128, 'm': 1, 'iterations': 1, 'kernel_mix': {'h_psi': 0.68, 'cdiaghg': 0.23, 'reduction': 0.04, 'refresh': 0.05}}


def rel_error(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1.0e-12)


def _kendall_tau(order_a: list[str], order_b: list[str]) -> float:
    pairs = 0
    concordant = 0
    discordant = 0
    for i, left in enumerate(order_a):
        for right in order_a[i + 1:]:
            pairs += 1
            sign_a = order_a.index(left) - order_a.index(right)
            sign_b = order_b.index(left) - order_b.index(right)
            if sign_a * sign_b > 0:
                concordant += 1
            elif sign_a * sign_b < 0:
                discordant += 1
    return (concordant - discordant) / max(pairs, 1)


def _family_ranking(path: Path, case_id: str) -> list[str]:
    payload = json.loads(path.read_text())
    rows = [row for row in payload['results'] if row['case_id'] == case_id]
    return [row['family'] for row in sorted(rows, key=lambda row: row['latency_s'])]


@pytest.mark.parametrize('family', FAMILIES)
def test_layer1_and_layer2_stay_within_the_calibration_band(family):
    point = make_design_point(family)
    l1 = FastPerformanceModel(FPGA_SPECS).evaluate_design_point(point, workload())
    l2 = PythonTLM().run_episode(point.to_dict(), workload())

    latency_ratio = max(l1.metrics['latency_ms'], l2.metrics['latency_ms']) / max(min(l1.metrics['latency_ms'], l2.metrics['latency_ms']), 1.0e-12)
    throughput_ratio = max(l1.metrics['throughput_gops'], l2.metrics['throughput_gops']) / max(min(l1.metrics['throughput_gops'], l2.metrics['throughput_gops']), 1.0e-12)
    power_ratio = max(l1.metrics['power_w'], l2.metrics['power_w']) / max(min(l1.metrics['power_w'], l2.metrics['power_w']), 1.0e-12)
    area_ratio = max(l1.metrics['area_mm2'], l2.metrics['area_mm2']) / max(min(l1.metrics['area_mm2'], l2.metrics['area_mm2']), 1.0e-12)

    assert latency_ratio <= 15.0
    assert throughput_ratio <= 100.0
    assert power_ratio <= 2.0
    assert area_ratio <= 2.0
    assert l1.status == l2.status == 'passed'



@pytest.mark.parametrize('family', FAMILIES)
def test_layer1_confidence_is_transmitted_through_orchestrator(family):
    point = make_design_point(family)
    orchestrator = ThreeLayerOrchestrator(l1_model=LayerConfidenceOnlyModel())
    result = orchestrator.evaluate_design_point(point, workload())

    assert result.layer_results[0].uncertainty['confidence_level'] == pytest.approx(0.87, rel=1e-9)
    assert result.layer_results[0].uncertainty['confidence_level'] == pytest.approx(0.87, rel=1e-9)
    assert result.layer_results[0].promotion_score > 0.0


@pytest.mark.parametrize('family', ['F1', 'F2', 'F3'])
def test_layer2_and_layer3_are_consistent_under_projection(family):
    point = make_design_point(family)
    result = ThreeLayerOrchestrator().evaluate_design_point(point, workload())
    l2 = result.layer_results[1]

    if len(result.layer_results) < 3:
        pytest.skip(f'L3 projection not generated for {family} (confidence below threshold)')

    l3 = result.layer_results[2]
    latency_ratio = max(l3.metrics['latency_ms'], l2.metrics['latency_ms']) / max(min(l3.metrics['latency_ms'], l2.metrics['latency_ms']), 1.0e-12)

    assert latency_ratio <= 1.5
    assert l3.metrics['latency_ms'] == pytest.approx(l2.metrics['latency_ms'] * 0.92, rel=1e-9)
    assert l3.metrics['throughput_gops'] == pytest.approx(l2.metrics['throughput_gops'] * 1.08, rel=1e-9)
    assert l3.metrics['power_w'] == pytest.approx(l2.metrics['power_w'] * 0.97, rel=1e-9)
    assert l3.metrics['accuracy_vs_reference'] >= l2.metrics['accuracy_vs_reference']
    assert l3.uncertainty['confidence_level'] >= l2.uncertainty['confidence_level']


@pytest.mark.parametrize('case_id', ['si8_pbe_nc', 'si8_pbe_uspp', 'si4_pbe_uspp_small'])
def test_ranking_stability_is_high_across_layer1_and_layer2(case_id):
    l1_ranking = _family_ranking(FIXTURE_DIR / 'layer1_results.json', case_id)
    l2_ranking = _family_ranking(FIXTURE_DIR / 'layer2_results.json', case_id)

    tau = _kendall_tau(l1_ranking, l2_ranking)

    assert tau >= 0.85
