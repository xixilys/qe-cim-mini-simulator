#!/usr/bin/env python3

import pytest

from dse_v2.models.fast.family_models import (
    F1PipelineModel,
    F2SystolicModel,
    F3DataflowModel,
    F4CimDspHbmModel,
    F5CgraModel,
    F6CustomModel,
    F7FutureModel,
)
from interfaces.types import DesignPoint, ResourceLimits, WorkloadSpecialization


FAMILY_MODELS = {
    'F1': F1PipelineModel(),
    'F2': F2SystolicModel(),
    'F3': F3DataflowModel(),
    'F4': F4CimDspHbmModel(),
    'F5': F5CgraModel(),
    'F6': F6CustomModel(),
    'F7': F7FutureModel(),
}


def design_point_for_family(family: str) -> DesignPoint:
    return DesignPoint(
        design_point_id=f'dp_{family.lower()}_iter',
        family=family,
        topology_type='mesh_2d',
        parameters={
            'system_level': {
                'family': family,
                'array_size': 1024,
                'f_pe': 1.0,
                'utilization': 0.85,
                'compute_scale': 1.0,
                'memory_scale': 1.0,
                'interconnect_scale': 1.0,
                'chiplets': 4,
            }
        },
        workload_specialization=WorkloadSpecialization(
            workload_id='qe_cbands_si8',
            kernels=['h_psi', 'cdiaghg', 'reduction', 'refresh'],
            precision='FP64',
        ),
        target_layers=['L1'],
        resource_limits=ResourceLimits(max_area_mm2=120.0, max_power_w=80.0, max_latency_ms=1000.0),
        architecture_spec_ref='c' * 64,
        constraints={'max_area_mm2': 120.0, 'max_power_w': 80.0, 'max_latency_ms': 1000.0},
        provenance={'input_hash': 'c' * 64, 'generated_at': '2026-01-01T00:00:00', 'tool_version': 'pytest'},
    )


def base_workload(iterations: int) -> dict:
    return {
        'npw': 2945,
        'nkb': 144,
        'm': 16,
        'kernel_mix': {'h_psi': 0.68, 'cdiaghg': 0.23, 'reduction': 0.04, 'refresh': 0.05},
        'iterations': iterations,
    }


@pytest.mark.parametrize('family,model', list(FAMILY_MODELS.items()))
def test_family_latency_increases_monotonically_with_iterations(family, model):
    results = [model.evaluate(design_point_for_family(family), base_workload(iterations)) for iterations in (1, 4, 8, 16)]
    latencies = [result.time_s for result in results]

    assert latencies == sorted(latencies)
    assert all(latencies[idx] < latencies[idx + 1] for idx in range(len(latencies) - 1))


@pytest.mark.parametrize('family,model', list(FAMILY_MODELS.items()))
def test_family_latency_and_energy_scale_with_iterations(family, model):
    results = [model.evaluate(design_point_for_family(family), base_workload(iterations)) for iterations in (1, 4, 8, 16)]
    base_time = results[0].time_s
    base_energy = results[0].energy_j

    for iterations, result in zip((1, 4, 8, 16), results):
        assert result.time_s == pytest.approx(base_time * iterations, rel=1e-9, abs=1e-12)
        assert result.energy_j == pytest.approx(base_energy * iterations, rel=1e-9, abs=1e-12)
