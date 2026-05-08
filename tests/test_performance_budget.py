#!/usr/bin/env python3

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dse_v2.models.fast.performance_model import FastPerformanceModel
from dse_v2.models.mid.python_tlm import PythonTLM
from dse_v2.orchestrator import ThreeLayerOrchestrator
from dse_v2.promotion.promotion_engine import PromotionEngine
from interfaces.types import DesignPoint, ResourceLimits, WorkloadSpecialization

FPGA_SPECS = {
    'peak_gflops': 1300,
    'memory_bw_gbs': 77,
    'pcie_bw_gbs': 16,
    'bram_kb': 34000,
    'dsp_count': 12288,
}


def make_design_point(family: str = 'F4', **overrides) -> DesignPoint:
    system_level = {
        'family': family,
        'n_gemm_tiles': 4,
        'n_eigen_tiles': 1,
        'tile_local_mem_kb': 512,
        'parallel_units': 4,
        'pipeline_depth': 4,
        'dataflow_pattern': 'streaming',
        'pcie_bw_gbps': 64.0,
        'dram_bw_gbps': 128.0,
        'max_power_w': 75.0,
    }
    system_level.update(overrides)
    return DesignPoint(
        design_point_id=f'dp_{family.lower()}_budget',
        family=family,
        topology_type='mesh_2d',
        parameters={'system_level': system_level},
        workload_specialization=WorkloadSpecialization(workload_id='qe_cbands_si8', kernels=['h_psi', 'cdiaghg'], precision='FP64'),
        target_layers=['L1', 'L2', 'L3'],
        resource_limits=ResourceLimits(max_area_mm2=140.0, max_power_w=75.0, max_latency_ms=2000.0),
        constraints={'max_power_w': 75.0, 'max_latency_ms': 2000.0},
        provenance={'input_hash': 'd' * 64, 'generated_at': '2026-01-01T00:00:00', 'tool_version': 'pytest'},
    )


def workload():
    return {'npw': 2945, 'nkb': 144, 'm': 16, 'iterations': 8, 'kernel_mix': {'h_psi': 0.68, 'cdiaghg': 0.23, 'reduction': 0.04, 'refresh': 0.05}}


def test_layer1_executes_under_one_second():
    model = FastPerformanceModel(FPGA_SPECS)
    start = time.perf_counter()
    result = model.evaluate_design_point(make_design_point(), workload())
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0
    assert result.metrics['time_s'] > 0.0
    assert result.layer_results[0].execution_time_seconds == result.metrics['time_s']


def test_layer2_executes_under_one_minute():
    tlm = PythonTLM()
    start = time.perf_counter()
    output = tlm.run_episode(make_design_point().to_dict(), workload())
    elapsed = time.perf_counter() - start

    assert elapsed < 60.0
    assert output.metrics['latency_ms'] > 0.0
    assert output.confidence > 0.0


def test_resource_budget_checks_reject_oversubscribed_design_point():
    model = FastPerformanceModel(FPGA_SPECS)
    constrained_point = make_design_point(family='F2', area_scale=20.0, dsp_budget=0.2, bram_budget=0.2, lut_budget=0.2, power_budget_w=30.0, max_power_w=30.0)

    result = model.evaluate_design_point(constrained_point, workload())
    constraints = model.check_constraints(constrained_point.to_dict())

    assert result.status == 'failed'
    assert max(result.resource_utilization.values()) > 1.0
    assert constraints['all_ok'] is False
    assert constraints['dsp_ok'] is False or constraints['bram_ok'] is False or constraints['power_ok'] is False


def test_promotion_budget_exhaustion_is_reported_explicitly():
    orchestrator = ThreeLayerOrchestrator(promotion_engine=PromotionEngine(budgets={'L2': 0, 'L3': 0}))
    result = orchestrator.evaluate_design_point(make_design_point(), workload())

    assert result.fidelity_level_achieved == 'L1'
    assert result.promotion_recommendation == 'hold'
    assert result.provenance['promotion_trace'][0]['reason'] == 'budget_exhausted'
