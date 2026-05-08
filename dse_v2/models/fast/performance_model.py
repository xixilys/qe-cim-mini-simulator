#!/usr/bin/env python3

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping

from interfaces.types import DesignPoint, EvaluationResult, LayerResult, ResourceLimits

from .family_models import (
    F1PipelineModel,
    F2SystolicModel,
    F3DataflowModel,
    F4CimDspHbmModel,
    F5CgraModel,
    F6CustomModel,
    F7FutureModel,
    FamilyEstimate,
    FamilyModel,
)


FAMILY_MODELS: dict[str, FamilyModel] = {
    'F1': F1PipelineModel(),
    'F2': F2SystolicModel(),
    'F3': F3DataflowModel(),
    'F4': F4CimDspHbmModel(),
    'F5': F5CgraModel(),
    'F6': F6CustomModel(),
    'F7': F7FutureModel(),
}


@dataclass
class HardwareSpecs:
    peak_gflops: float = 1300.0
    memory_bw_gbs: float = 77.0
    pcie_bw_gbs: float = 16.0
    bram_kb: float = 34000.0
    dsp_count: float = 12288.0


class FastPerformanceModel:
    def __init__(self, fpga_specs: Mapping[str, Any] | None = None):
        specs = dict(fpga_specs or {})
        self.specs = HardwareSpecs(
            peak_gflops=float(specs.get('peak_gflops', 1300.0)),
            memory_bw_gbs=float(specs.get('memory_bw_gbs', 77.0)),
            pcie_bw_gbs=float(specs.get('pcie_bw_gbs', 16.0)),
            bram_kb=float(specs.get('bram_kb', 34000.0)),
            dsp_count=float(specs.get('dsp_count', 12288.0)),
        )

    def _coerce_point(self, design_point: DesignPoint | Mapping[str, Any]) -> Dict[str, Any]:
        if hasattr(design_point, 'to_dict'):
            return dict(design_point.to_dict())
        return dict(design_point)

    def _family_model(self, family: str) -> FamilyModel:
        return FAMILY_MODELS.get(family, FAMILY_MODELS['F7'])

    def _unknown_family_result(self, family: str, point: Dict[str, Any], workload: Mapping[str, Any], message: str) -> EvaluationResult:
        result_id = f"res_{point.get('design_point_id', family.lower())}"
        layer = LayerResult(
            layer_id='L1',
            fidelity_level='L1',
            status='failed',
            metrics={
                'latency_ms': 0.0,
                'throughput_gops': 0.0,
                'power_w': 0.0,
                'area_mm2': 0.0,
            },
            resource_utilization={},
            promotion_score=0.0,
            model_used='unknown_family',
            execution_time_seconds=0.0,
            uncertainty={'error': message},
        )
        return EvaluationResult(
            result_id=result_id,
            design_point_id=str(point.get('design_point_id', f'dp_{family.lower()}')),
            evaluation_config_ref=str(point.get('architecture_spec_ref', '')) or None,
            fidelity_level_achieved='L1',
            layer_results=[layer],
            promotion_recommendation='reject',
            promotion_score=0.0,
            metrics={
                'time_s': 0.0,
                'energy_j': 0.0,
                'area_mm2': 0.0,
                'power_w': 0.0,
                'latency_ms': 0.0,
                'throughput_gops': 0.0,
            },
            status='failed',
            uncertainty={
                'confidence_level': 0.0,
                'mape_percent': 100.0,
                'assumptions': [
                    'family_validation_failed',
                ],
                'sample_size': 0,
                'error': message,
            },
            resource_utilization={},
            provenance={
                'model_used': 'unknown_family',
                'family': family,
                'error': message,
            },
        )

    def evaluate_design_point(self, design_point: DesignPoint | Mapping[str, Any], workload: Mapping[str, Any]) -> EvaluationResult:
        point = self._coerce_point(design_point)
        family = str(point.get('family', 'F7'))
        if family not in FAMILY_MODELS:
            message = f"Unknown family '{family}' is not supported; expected one of {', '.join(sorted(FAMILY_MODELS))}"
            return self._unknown_family_result(family, point, workload, message)
        model = self._family_model(family)
        estimate = model.evaluate(point, workload)
        result_id = f"res_{point.get('design_point_id', family.lower())}"
        layer = LayerResult(
            layer_id='L1',
            fidelity_level='L1',
            status=estimate.status,
            metrics={
                'latency_ms': estimate.time_s * 1000.0,
                'throughput_gops': self._throughput_gops(estimate.time_s, workload),
                'power_w': estimate.power_w,
                'area_mm2': estimate.area_mm2,
            },
            resource_utilization=dict(estimate.resource_utilization),
            promotion_score=self._promotion_score(estimate),
            model_used=estimate.model_name,
            execution_time_seconds=estimate.time_s,
        )
        status = estimate.status
        promotion_score = self._promotion_score(estimate)
        uncertainty = {
            'confidence_level': self._confidence(estimate),
            'mape_percent': self._mape_percent(estimate),
            'assumptions': [
                f'family_model={estimate.model_name}',
                'roofline_style_aggregation',
                'resource_utilization_penalty_applied',
            ],
            'sample_size': 1,
        }
        layer.uncertainty = dict(uncertainty)
        return EvaluationResult(
            result_id=result_id,
            design_point_id=str(point.get('design_point_id', f'dp_{family.lower()}')),
            evaluation_config_ref=str(point.get('architecture_spec_ref', '')) or None,
            fidelity_level_achieved='L1',
            layer_results=[layer],
            promotion_recommendation='promote' if estimate.feasible else 'reject',
            promotion_score=promotion_score,
            metrics={
                'time_s': estimate.time_s,
                'energy_j': estimate.energy_j,
                'area_mm2': estimate.area_mm2,
                'power_w': estimate.power_w,
                'latency_ms': estimate.time_s * 1000.0,
                'throughput_gops': self._throughput_gops(estimate.time_s, workload),
            },
            status=status,
            uncertainty=uncertainty,
            resource_utilization=dict(estimate.resource_utilization),
            provenance={
                'model_used': estimate.model_name,
                'family': family,
                'kernel_times_s': dict(estimate.kernel_times_s),
            },
        )


    def _confidence(self, estimate: FamilyEstimate) -> float:
        penalty = max(estimate.resource_utilization.values(), default=0.0)
        confidence = 1.0 - min(1.0, penalty * 0.7)
        if estimate.status != 'passed':
            confidence *= 0.5
        return max(0.0, min(1.0, confidence))

    def _mape_percent(self, estimate: FamilyEstimate) -> float:
        confidence = self._confidence(estimate)
        return max(5.0, 24.0 * (1.0 - confidence))

    def _throughput_gops(self, time_s: float, workload: Mapping[str, Any]) -> float:
        npw = max(1.0, float(workload.get('npw', 2945)))
        nkb = max(1.0, float(workload.get('nkb', 144)))
        m = max(1.0, float(workload.get('m', 16)))
        ops = (5.0 * npw * math.log2(max(2.0, npw)) * m) + (2.0 * npw * nkb * m)
        return ops / max(time_s, 1e-12) / 1.0e9

    def _promotion_score(self, estimate: FamilyEstimate) -> float:
        confidence = self._confidence(estimate)
        score = confidence
        if estimate.status != 'passed':
            score *= 0.5
        return max(0.0, min(1.0, score))

    # compatibility helpers used by older scripts
    def estimate_h_psi_time(self, design_point: Mapping[str, Any], workload: Mapping[str, Any]) -> float:
        return self.evaluate_design_point(design_point, workload).metrics['time_s']

    def estimate_energy(self, design_point: Mapping[str, Any], time: float) -> float:
        return max(0.0, time * 28.0)

    def estimate_area(self, design_point: Mapping[str, Any]) -> Dict[str, float]:
        return {'dsp_count': 0.0, 'dsp_utilization': 0.0, 'bram_kb': 0.0, 'bram_utilization': 0.0, 'lut_count': 0.0, 'lut_utilization': 0.0}

    def compute_area_cost(self, design_point: Mapping[str, Any]) -> float:
        return 0.0

    def check_constraints(self, design_point: Mapping[str, Any]) -> Dict[str, bool]:
        result = self.evaluate_design_point(design_point, {'npw': 2945, 'nkb': 144, 'm': 16})
        return {
            'dsp_ok': result.resource_utilization.get('dsp_utilization', 0.0) <= 1.0,
            'bram_ok': result.resource_utilization.get('bram_utilization', 0.0) <= 1.0,
            'lut_ok': result.resource_utilization.get('lut_utilization', 0.0) <= 1.0,
            'power_ok': result.resource_utilization.get('power_utilization', 0.0) <= 1.0,
            'all_ok': result.status == 'passed',
        }
