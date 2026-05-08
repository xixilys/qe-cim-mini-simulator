#!/usr/bin/env python3

from dataclasses import asdict, is_dataclass
import logging
from typing import Any, Dict, List, Mapping, Optional

from dse_v2.models.fast.performance_model import FastPerformanceModel
from dse_v2.models.mid.python_tlm import Layer2Output, PythonTLM
from dse_v2.promotion.promotion_engine import PromotionDecision, PromotionEngine
from interfaces.types import (
    ArchitectureSpec, DataflowSpec, DesignPoint, EvaluationResult,
    LayerResult, MappingSpec, ResourceLimits, WorkloadSpec,
)


LOGGER = logging.getLogger(__name__)


class ThreeLayerOrchestrator:
    def __init__(
        self,
        promotion_engine: Optional[PromotionEngine] = None,
        l1_model: Optional[Any] = None,
        l2_model: Optional[PythonTLM] = None,
        systemc_backend: Optional[Any] = None,
        fpga_specs: Optional[Mapping[str, Any]] = None,
        budgets: Optional[Mapping[str, int]] = None,
        l3_mode: str = 'projection_only',
    ):
        self.fpga_specs = dict(fpga_specs or {})
        self.l1_model = l1_model or FastPerformanceModel(self.fpga_specs)
        self.l2_model = l2_model or PythonTLM()
        self.systemc_backend = systemc_backend
        self.promotion_engine = promotion_engine or PromotionEngine(budgets=budgets)
        self.l3_mode = l3_mode

    def evaluate_design_point(self, design_point: Any, workload: Optional[Mapping[str, Any]] = None) -> EvaluationResult:
        design = self._normalize_design_point(design_point)
        family = design.architecture.family
        design_point_id = design.design_point_id
        result_id = f'res_{design_point_id}'
        workload_dict = self._build_workload(design, workload)

        l1_result = self._evaluate_l1(design, family, workload_dict)
        l1_decision = self.promotion_engine.evaluate(l1_result)
        layer_results: List[LayerResult] = [self._to_layer_result('L1', l1_result)]

        if not l1_decision.promote:
            return self._build_result(result_id, design_point_id, 'L1', layer_results, l1_result, [asdict(l1_decision)])

        l2_output = self.l2_model.run_episode(design, workload_dict)
        l2_result = self._layer2_to_result(l2_output, design_point_id)
        l2_decision = self.promotion_engine.evaluate(l2_result)
        layer_results.append(self._to_layer_result('L2', l2_result))

        if not l2_decision.promote:
            return self._build_result(result_id, design_point_id, 'L2', layer_results, l2_result, [asdict(l1_decision), asdict(l2_decision)])

        l3_result = self._project_l3(design, workload_dict, l2_result, design_point_id)
        l3_promote = self.promotion_engine.should_promote_to_l3(l3_result)
        l3_decision = self.promotion_engine.evaluate(l3_result)
        l3_trace = asdict(l3_decision)
        l3_trace['from_layer'] = 'L2'
        l3_trace['promote'] = l3_promote
        l3_trace['to_layer'] = 'L3' if l3_promote else None
        l3_trace['reason'] = 'eligible' if l3_promote else 'projection_only'
        l3_trace.setdefault('details', {})['decision_reason'] = l3_decision.reason
        promotion_trace = [asdict(l1_decision), asdict(l2_decision), l3_trace]

        if not l3_promote:
            return self._build_result(result_id, design_point_id, 'L2', layer_results, l2_result, promotion_trace, layer3_projection=True)

        layer_results.append(self._to_layer_result('L3', l3_result))
        return self._build_result(result_id, design_point_id, 'L3', layer_results, l3_result, promotion_trace, l3_mode=self.l3_mode)

    def _build_result(self, result_id: str, design_point_id: str, fidelity: str, layer_results: List[LayerResult], payload: Mapping[str, Any], promotion_trace: List[Any], layer3_projection: bool = False, l3_mode: Optional[str] = None) -> EvaluationResult:
        provenance: Dict[str, Any] = {'promotion_trace': promotion_trace}
        if layer3_projection:
            provenance['layer3_projection'] = True
        if l3_mode is not None:
            provenance['layer3_projection'] = l3_mode == 'projection_only'
            provenance['l3_mode'] = l3_mode
        return EvaluationResult(
            result_id=result_id,
            design_point_id=design_point_id,
            fidelity_level_achieved=fidelity,
            layer_results=layer_results,
            promotion_recommendation='promote' if fidelity == 'L3' else 'hold',
            promotion_score=float(payload.get('promotion_score', 0.0)),
            metrics=dict(payload.get('metrics', {})),
            status=str(payload.get('status', 'unknown')),
            uncertainty=dict(payload.get('uncertainty', {})),
            resource_utilization=dict(payload.get('resource_utilization', {})),
            provenance=provenance,
        )

    def _evaluate_l1(self, design: DesignPoint, family: str, workload: Mapping[str, Any]) -> Dict[str, Any]:
        arch = design.architecture
        mapping = design.mapping
        dataflow = design.dataflow

        npw = float(workload.get('npw', design.workload.npw))
        nkb = float(workload.get('nkb', design.workload.nkb))
        m = float(workload.get('m', design.workload.m))
        iterations = float(workload.get('iterations', design.workload.iterations))
        gemm_tiles = max(1.0, float(arch.gemm_tiles))
        eigen_tiles = max(1.0, float(arch.eigen_tiles))
        local_mem_kb = max(1.0, float(arch.local_mem_kb))

        latency_ms = self._compute_scf_latency(design, npw, nkb, m, iterations)
        throughput_gops = ((2.0 * npw * nkb * m * iterations) + (nkb * nkb * m * iterations)) / max(latency_ms, 1.0e-9) / 1.0e6
        power_w = 20.0 + 2.4 * gemm_tiles + 3.0 * eigen_tiles + 0.0015 * local_mem_kb
        area_mm2 = 22.0 + 2.1 * gemm_tiles + 2.9 * eigen_tiles + 0.0012 * local_mem_kb
        resource_utilization = {
            'compute_percent': min(100.0, (gemm_tiles * 0.85 + eigen_tiles * 0.95) / 12.0 * 100.0),
            'memory_percent': min(100.0, local_mem_kb / 2048.0 * 100.0),
            'bandwidth_percent': min(100.0, 30.0 + 2.5 * iterations),
        }
        resource_margin = max(0.0, 1.0 - max(resource_utilization.values()) / 100.0)
        confidence = max(0.0, min(0.95, 0.76 + 0.14 * resource_margin))
        accuracy_vs_reference = max(0.0, min(0.98, 0.84 + 0.10 * confidence + 0.04 * resource_margin))
        promotion_score = max(0.0, min(1.0, 0.48 * accuracy_vs_reference + 0.30 * confidence + 0.17 * resource_margin + 0.05))
        status = 'passed' if max(resource_utilization.values()) <= 100.0 and power_w <= arch.max_power_w else 'failed'

        return {
            'family': family,
            'status': status,
            'metrics': {
                'latency_ms': latency_ms,
                'throughput_gops': throughput_gops,
                'power_w': power_w,
                'area_mm2': area_mm2,
                'energy_efficiency_gops_per_w': throughput_gops / max(power_w, 1.0e-9),
                'accuracy_vs_reference': accuracy_vs_reference,
            },
            'uncertainty': {'confidence_level': confidence, 'mape_percent': max(5.0, 24.0 * (1.0 - confidence)), 'sample_size': 1},
            'resource_utilization': resource_utilization,
            'promotion_score': promotion_score,
            'confidence': confidence,
            'fidelity_level_achieved': 'L1',
            'pareto_frontier': [],
        }

    def _compute_scf_latency(self, design: DesignPoint, npw: float, nkb: float, m: float, iterations: float) -> float:
        arch = design.architecture
        mapping = design.mapping
        dataflow = design.dataflow

        gemm_tiles = max(1.0, float(arch.gemm_tiles))
        eigen_tiles = max(1.0, float(arch.eigen_tiles))
        local_mem_kb = max(1.0, float(arch.local_mem_kb))

        base_latency = ((2.0 * npw * nkb * m * iterations) / max(gemm_tiles * 110.0, 1.0e-9) + (nkb * nkb * m * iterations) / max(eigen_tiles * 55.0, 1.0e-9)) / 1.0e6
        base_latency += 2.5 + local_mem_kb / 1024.0

        mapping_penalty = self._mapping_penalty(mapping, arch)
        dataflow_speedup = self._dataflow_speedup(dataflow, arch)

        return base_latency * (1.0 + mapping_penalty) * (1.0 - dataflow_speedup)

    def _mapping_penalty(self, mapping: MappingSpec, arch: ArchitectureSpec) -> float:
        penalty = 0.0
        phases = ['operator_sweep', 'reduced_build', 'diag', 'refresh']
        for phase in phases:
            target = mapping.get_target(phase)
            if target == 'cpu':
                penalty += 0.15
            elif target == 'auto':
                penalty += 0.05
        return min(0.5, penalty)

    def _dataflow_speedup(self, dataflow: DataflowSpec, arch: ArchitectureSpec) -> float:
        speedup = 0.0
        if dataflow.double_buffer:
            speedup += 0.08
        if dataflow.overlap_dma_compute:
            speedup += 0.12
        if dataflow.keep_resident:
            speedup += 0.05
        return min(0.25, speedup)

    def _build_l1_design(self, design: DesignPoint) -> Dict[str, Any]:
        arch = design.architecture
        return {
            'design_point_id': design.design_point_id,
            'family': arch.family,
            'topology_type': arch.topology_type,
            'parameters': {
                'system_level': {
                    'family': arch.family,
                    'clock_mhz': arch.clock_mhz,
                    'parallel_units': arch.parallel_units,
                    'n_gemm_tiles': arch.gemm_tiles,
                    'n_eigen_tiles': arch.eigen_tiles,
                    'tile_local_mem_kb': arch.local_mem_kb,
                    'max_power_w': arch.max_power_w,
                    'pcie_bw_gbps': arch.pcie_bw_gbps,
                    'dram_bw_gbps': arch.dram_bw_gbps,
                },
                'mapping': design.mapping.to_dict(),
                'dataflow': design.dataflow.to_dict(),
            },
            'resource_limits': design.resource_limits.to_dict(),
        }

    def _layer1_from_external(self, external_result: Any, family: str) -> Dict[str, Any]:
        if hasattr(external_result, 'to_dict'):
            payload = external_result.to_dict()
        elif is_dataclass(external_result):
            payload = asdict(external_result)
        elif isinstance(external_result, Mapping):
            payload = dict(external_result)
        else:
            raise TypeError('l1_model must return a mapping or dataclass')
        if 'layer_results' in payload and payload['layer_results']:
            layer = payload['layer_results'][0]
            if hasattr(layer, 'to_dict'):
                layer = layer.to_dict()
            elif is_dataclass(layer):
                layer = asdict(layer)
            uncertainty = dict(payload.get('uncertainty') or layer.get('uncertainty', {}))
            confidence = self._confidence_from_payload(payload, layer)
            payload = {
                'family': family,
                'status': payload.get('status', layer.get('status', 'passed')),
                'metrics': dict(payload.get('metrics', layer.get('metrics', {}))),
                'uncertainty': uncertainty,
                'resource_utilization': dict(payload.get('resource_utilization', layer.get('resource_utilization', {}))),
                'promotion_score': float(payload.get('promotion_score', layer.get('promotion_score', 0.0))),
                'confidence': confidence,
                'fidelity_level_achieved': 'L1',
                'pareto_frontier': payload.get('pareto_frontier', []),
                'model_used': payload.get('model_used', payload.get('provenance', {}).get('model_used', 'layer1_model')),
            }
        else:
            payload.setdefault('family', family)
            payload.setdefault('fidelity_level_achieved', 'L1')
            payload.setdefault('pareto_frontier', [])
            payload.setdefault('uncertainty', {})
            payload.setdefault('model_used', payload.get('provenance', {}).get('model_used', 'layer1_model'))
            payload['confidence'] = self._confidence_from_payload(payload)
        return payload

    def _confidence_from_payload(self, payload: Mapping[str, Any], layer: Optional[Mapping[str, Any]] = None) -> float:
        uncertainty = payload.get('uncertainty', {}) or {}
        confidence = uncertainty.get('confidence_level')
        if confidence is not None:
            return float(confidence)
        if payload.get('confidence') is not None:
            return float(payload['confidence'])
        if layer is not None:
            layer_uncertainty = layer.get('uncertainty', {}) or {}
            confidence = layer_uncertainty.get('confidence_level')
            if confidence is not None:
                return float(confidence)
            if layer.get('confidence') is not None:
                return float(layer['confidence'])
        return 0.0

    def _layer2_to_result(self, layer2: Layer2Output, design_point_id: str) -> Dict[str, Any]:
        payload = layer2.to_dict()
        payload['metrics'] = dict(payload.get('metrics', {}))
        payload['metrics'].setdefault('accuracy_vs_reference', min(0.99, 0.70 + 0.25 * float(payload.get('confidence', 0.0))))
        payload['fidelity_level_achieved'] = 'L2'
        payload['design_point_id'] = design_point_id
        return payload

    def _project_l3(self, design: DesignPoint, workload: Mapping[str, Any], l2_result: Mapping[str, Any], design_point_id: str) -> Dict[str, Any]:
        if self.l3_mode == 'systemc_execution':
            if self.systemc_backend is None:
                from dse_v2.backends.systemc_backend import SystemCBackend
                self.systemc_backend = SystemCBackend()
            sc_result = self.systemc_backend.run_episode(design, workload)
            if sc_result['status'] == 'passed':
                sc_result['fidelity_level_achieved'] = 'L3'
                sc_result['promotion_score'] = l2_result.get('promotion_score', 0.0) * 1.05
                sc_result['confidence'] = sc_result['uncertainty'].get('confidence_level', 0.85)
                return sc_result
            else:
                return self._projection_only_l3(l2_result, design_point_id)
        return self._projection_only_l3(l2_result, design_point_id)

    def _projection_only_l3(self, l2_result: Mapping[str, Any], design_point_id: str) -> Dict[str, Any]:
        metrics = dict(l2_result['metrics'])
        metrics['latency_ms'] = metrics['latency_ms'] * 0.92
        metrics['throughput_gops'] = metrics['throughput_gops'] * 1.08
        metrics['power_w'] = metrics['power_w'] * 0.97
        metrics['energy_efficiency_gops_per_w'] = metrics['throughput_gops'] / max(metrics['power_w'], 1.0e-9)
        metrics['accuracy_vs_reference'] = min(0.99, metrics.get('accuracy_vs_reference', 0.9) + 0.04)
        confidence = min(0.99, float(l2_result['confidence']) + 0.04)
        resource_utilization = dict(l2_result['resource_utilization'])
        resource_utilization['bandwidth_percent'] = max(0.0, resource_utilization.get('bandwidth_percent', 0.0) * 0.92)
        resource_margin = max(0.0, 1.0 - max(resource_utilization.values()) / 100.0)
        promotion_score = max(0.0, min(1.0, 0.48 * metrics['accuracy_vs_reference'] + 0.30 * confidence + 0.17 * resource_margin + 0.05))
        projection_uncertainty = 0.20
        return {
            'family': l2_result['family'],
            'status': 'projection_only',
            'is_projection': True,
            'projection_uncertainty': projection_uncertainty,
            'metrics': metrics,
            'uncertainty': {
                'confidence_level': confidence,
                'mape_percent': max(3.0, float(l2_result['uncertainty']['mape_percent']) * 0.8),
                'sample_size': int(l2_result['uncertainty'].get('sample_size', 1)),
                'projection_uncertainty': projection_uncertainty,
            },
            'resource_utilization': resource_utilization,
            'promotion_score': promotion_score,
            'confidence': confidence,
            'fidelity_level_achieved': 'L3',
            'design_point_id': design_point_id,
            'model_used': 'layer3_projection',
        }

    def _to_layer_result(self, layer_id: str, payload: Mapping[str, Any]) -> LayerResult:
        return LayerResult(
            layer_id=layer_id,
            fidelity_level=layer_id,
            status=str(payload['status']),
            metrics=dict(payload['metrics']),
            uncertainty=dict(payload.get('uncertainty', {})),
            resource_utilization=dict(payload.get('resource_utilization', {})),
            promotion_score=float(payload.get('promotion_score', 0.0)),
            model_used=str(payload.get('model_used', 'layer2_tlm' if layer_id == 'L2' else ('layer3_projection' if layer_id == 'L3' else 'layer1_model'))),
            is_projection=bool(payload.get('is_projection', False)),
            projection_uncertainty=float(payload.get('projection_uncertainty', 0.0)),
        )

    def _normalize_design_point(self, value: Any) -> DesignPoint:
        if isinstance(value, DesignPoint):
            return value
        if hasattr(value, 'to_dict'):
            value = value.to_dict()
        if isinstance(value, Mapping):
            return self._dict_to_design_point(dict(value))
        raise TypeError('design_point must be a DesignPoint, mapping, dataclass, or expose to_dict()')

    def _dict_to_design_point(self, data: Dict[str, Any]) -> DesignPoint:
        if 'architecture' in data:
            arch = ArchitectureSpec(**data['architecture'])
        else:
            arch = ArchitectureSpec(
                family=data.get('family', 'F1'),
                topology_type=data.get('topology_type', 'pipeline'),
                parameters=data.get('parameters', {}),
            )

        mapping = MappingSpec(**data.get('mapping', {}))
        dataflow = DataflowSpec(**data.get('dataflow', {}))
        workload = WorkloadSpec(**data.get('workload', {}))
        resource_limits = ResourceLimits(**data.get('resource_limits', {}))

        return DesignPoint(
            design_point_id=data.get('design_point_id', 'dp_auto'),
            architecture=arch,
            mapping=mapping,
            dataflow=dataflow,
            workload=workload,
            resource_limits=resource_limits,
            target_layers=data.get('target_layers', ['L1', 'L2', 'L3']),
            schema_version=data.get('schema_version', 'design_point_v2'),
            architecture_spec_ref=data.get('architecture_spec_ref'),
            constraints=data.get('constraints', {}),
            provenance=data.get('provenance', {}),
            family=data.get('family'),
            topology_type=data.get('topology_type'),
            parameters=data.get('parameters'),
            workload_specialization=data.get('workload_specialization'),
        )

    def _build_workload(self, design: DesignPoint, override: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        workload = design.workload.to_dict()
        if override:
            workload.update(override)
        workload['mapping'] = design.mapping.to_dict()
        workload['dataflow'] = design.dataflow.to_dict()
        workload['architecture_family'] = design.architecture.family
        return workload

    def _as_mapping(self, value: Any) -> Mapping[str, Any]:
        if hasattr(value, 'to_dict'):
            return value.to_dict()
        if isinstance(value, Mapping):
            return value
        if is_dataclass(value):
            return asdict(value)
        raise TypeError('design_point must be a mapping, dataclass, or expose to_dict()')

    def _system_params(self, design_point: Mapping[str, Any]) -> Mapping[str, Any]:
        if hasattr(design_point, 'to_dict'):
            design_point = design_point.to_dict()
        if isinstance(design_point, Mapping) and 'parameters' in design_point and isinstance(design_point['parameters'], Mapping):
            params = design_point['parameters']
            if 'system_level' in params and isinstance(params['system_level'], Mapping):
                merged = dict(params['system_level'])
                for key, value in params.items():
                    if key != 'system_level' and key not in merged:
                        merged[key] = value
                return merged
            return params
        return design_point
