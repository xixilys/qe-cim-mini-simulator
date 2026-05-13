#!/usr/bin/env python3

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping

from dse_v2.interfaces.types import DesignPoint


@dataclass(frozen=True)
class FamilyEstimate:
    family: str
    model_name: str
    time_s: float
    energy_j: float
    area_mm2: float
    power_w: float
    status: str
    feasible: bool
    kernel_times_s: Dict[str, float] = field(default_factory=dict)
    resource_utilization: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, float] = field(default_factory=dict)


class FamilyModel(ABC):
    family: str
    model_name: str

    def evaluate(self, design_point: DesignPoint | Mapping[str, Any], workload: Mapping[str, Any]) -> FamilyEstimate:
        point = design_point.to_dict() if hasattr(design_point, 'to_dict') else dict(design_point)
        family = str(point.get('family', getattr(self, 'family', 'F0')))
        params = point.get('parameters', {})
        system = dict(params.get('system_level', {}))
        workload_dict = dict(workload)

        problem_size = max(1.0, float(workload_dict.get('problem_size', 4096)))
        feature_size = max(1.0, float(workload_dict.get('feature_size', max(16.0, problem_size / 32.0))))
        batch_size = max(1.0, float(workload_dict.get('batch_size', 16)))
        iterations = max(1.0, float(workload_dict.get('iterations', workload_dict.get('total_iterations', 1.0))))
        mix = self._kernel_mix(workload_dict)

        compute_ops = (5.0 * problem_size * math.log2(max(2.0, problem_size)) * batch_size) + (2.0 * problem_size * feature_size * batch_size)
        solve_ops = max(1.0, (feature_size ** 3) * max(1.0, batch_size / 16.0))
        reduce_ops = max(1.0, problem_size * batch_size * 0.5)
        update_ops = max(1.0, problem_size * batch_size * 0.25)
        bytes_moved = (problem_size * batch_size * 16.0) + (problem_size * feature_size * 16.0) + (batch_size * batch_size * 16.0)

        kernel_times = self._kernel_times(
            compute_ops=compute_ops,
            solve_ops=solve_ops,
            reduce_ops=reduce_ops,
            update_ops=update_ops,
            bytes_moved=bytes_moved,
            iterations=iterations,
            mix=mix,
            system=system,
            workload=workload_dict,
        )
        time_s = self._combine_kernel_times(kernel_times, mix, system, workload_dict, iterations)
        power_w = self._power_estimate(system, workload_dict, kernel_times, time_s)
        energy_j = max(0.0, time_s * power_w)
        area_mm2 = self._area_estimate(system, workload_dict)
        resource_utilization = self._resource_utilization(point, system, area_mm2, power_w)
        feasible = self._feasible(point, resource_utilization, time_s, area_mm2, power_w)
        status = 'passed' if feasible else 'failed'
        return FamilyEstimate(
            family=family,
            model_name=self.model_name,
            time_s=time_s,
            energy_j=energy_j,
            area_mm2=area_mm2,
            power_w=power_w,
            status=status,
            feasible=feasible,
            kernel_times_s=kernel_times,
            resource_utilization=resource_utilization,
            metadata={'kernel_mix_compute': mix['compute'], 'kernel_mix_solve': mix['solve'], 'kernel_mix_reduce': mix['reduce'], 'kernel_mix_update': mix['update']},
        )

    def _kernel_mix(self, workload: Mapping[str, Any]) -> Dict[str, float]:
        raw = workload.get('kernel_mix', {})
        if not isinstance(raw, Mapping):
            raw = {}
        mix = {
            'compute': float(raw.get('compute', 0.55)),
            'solve': float(raw.get('solve', 0.20)),
            'reduce': float(raw.get('reduce', 0.15)),
            'update': float(raw.get('update', 0.10)),
        }
        total = sum(max(0.0, value) for value in mix.values())
        if total <= 0.0:
            return {'compute': 0.55, 'solve': 0.20, 'reduce': 0.15, 'update': 0.10}
        return {key: max(0.0, value) / total for key, value in mix.items()}

    def _kernel_times(
        self,
        *,
        compute_ops: float,
        solve_ops: float,
        reduce_ops: float,
        update_ops: float,
        bytes_moved: float,
        iterations: float,
        mix: Mapping[str, float],
        system: Mapping[str, Any],
        workload: Mapping[str, Any],
    ) -> Dict[str, float]:
        raise NotImplementedError

    def _combine_kernel_times(
        self,
        kernel_times: Mapping[str, float],
        mix: Mapping[str, float],
        system: Mapping[str, Any],
        workload: Mapping[str, Any],
        iterations: float,
    ) -> float:
        raise NotImplementedError

    def _power_estimate(
        self,
        system: Mapping[str, Any],
        workload: Mapping[str, Any],
        kernel_times: Mapping[str, float],
        time_s: float,
    ) -> float:
        base = float(system.get('base_power_w', 26.0))
        activity = float(workload.get('activity_scale', 1.0))
        return base + activity * (sum(kernel_times.values()) / max(time_s, 1e-12)) * 0.15

    def _area_estimate(self, system: Mapping[str, Any], workload: Mapping[str, Any]) -> float:
        return 18.0 + float(system.get('area_scale', 1.0)) * 6.0 + float(workload.get('footprint_scale', 1.0)) * 2.0

    def _resource_utilization(self, design_point: Mapping[str, Any], system: Mapping[str, Any], area_mm2: float, power_w: float) -> Dict[str, float]:
        dsp_budget = max(1e-9, float(system.get('dsp_budget', 1.0)))
        bram_budget = max(1e-9, float(system.get('bram_budget', 1.0)))
        lut_budget = max(1e-9, float(system.get('lut_budget', 1.0)))
        dsp_capacity = dsp_budget * 12288.0
        bram_capacity = bram_budget * 34000.0
        lut_capacity = lut_budget * 600000.0
        power_capacity = float(system.get('power_budget_w', 80.0))
        area_capacity = max(1.0, float(design_point.get('resource_limits', {}).get('max_area_mm2', 120.0)))
        dsp_use = float(system.get('dsp_use', 4200.0)) + area_mm2 * 25.0
        bram_use = float(system.get('bram_use', 6800.0)) + area_mm2 * 18.0
        lut_use = float(system.get('lut_use', 120000.0)) + area_mm2 * 5000.0
        return {
            'dsp_utilization': dsp_use / max(dsp_capacity, 1e-12),
            'bram_utilization': bram_use / max(bram_capacity, 1e-12),
            'lut_utilization': lut_use / max(lut_capacity, 1e-12),
            'power_utilization': power_w / max(power_capacity, 1e-12),
            'area_utilization': area_mm2 / area_capacity,
        }

    def _feasible(self, design_point: Mapping[str, Any], resource_utilization: Mapping[str, float], time_s: float, area_mm2: float, power_w: float) -> bool:
        limits = design_point.get('resource_limits')
        if hasattr(limits, 'to_dict'):
            limits = limits.to_dict()
        if not isinstance(limits, Mapping):
            limits = {}
        max_area = float(limits.get('max_area_mm2', 120.0))
        max_power = float(limits.get('max_power_w', 80.0))
        max_latency = float(limits.get('max_latency_ms', 1000.0))
        return (
            resource_utilization['dsp_utilization'] <= 1.0
            and resource_utilization['bram_utilization'] <= 1.0
            and resource_utilization['lut_utilization'] <= 1.0
            and resource_utilization['power_utilization'] <= 1.0
            and resource_utilization['area_utilization'] <= 1.0
            and (time_s * 1000.0) <= max_latency
            and area_mm2 <= max_area
            and power_w <= max_power
        )


class F1PipelineModel(FamilyModel):
    family = 'F1'
    model_name = 'F1PipelineModel'

    def _kernel_times(self, *, compute_ops: float, solve_ops: float, reduce_ops: float, update_ops: float, bytes_moved: float, iterations: float, mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any]) -> Dict[str, float]:
        scale = max(1.0, iterations)
        clock_mhz = float(system.get('clock_mhz', 250.0))
        pipeline_depth = float(system.get('pipeline_depth', 4.0))
        parallel_units = max(1.0, float(system.get('parallel_units', 4.0)))
        rate = clock_mhz * parallel_units * 1.0e6 * (0.55 + 0.05 * pipeline_depth)
        t_h = compute_ops * mix['compute'] * scale / rate
        t_c = solve_ops * mix['solve'] * scale / (rate * 0.35)
        t_r = reduce_ops * mix['reduce'] * scale / (rate * 0.75)
        t_f = update_ops * mix['update'] * scale / (rate * 0.85)
        return {
            'compute': t_h,
            'solve': t_c,
            'reduce': t_r,
            'update': t_f,
        }

    def _combine_kernel_times(self, kernel_times: Mapping[str, float], mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any], iterations: float) -> float:
        scale = max(1.0, iterations)
        per_iter = {key: value / scale for key, value in kernel_times.items()}
        barrier = (per_iter['compute'] + per_iter['solve'] + per_iter['reduce'] + per_iter['update']) * 0.12
        return (max(per_iter.values()) + barrier) * scale


class F2SystolicModel(FamilyModel):
    family = 'F2'
    model_name = 'F2SystolicModel'

    def _kernel_times(self, *, compute_ops: float, solve_ops: float, reduce_ops: float, update_ops: float, bytes_moved: float, iterations: float, mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any]) -> Dict[str, float]:
        scale = max(1.0, iterations)
        array_size = max(1.0, float(system.get('array_size', workload.get('array_size', 1024.0))))
        f_pe = max(1.0, float(system.get('f_pe', 1.0)))
        util = max(0.05, float(system.get('utilization', 0.85)))
        gemm_time = compute_ops * mix['compute'] * scale / (array_size * f_pe * util * 1.0e6)
        diag_time = solve_ops * mix['solve'] * scale / (array_size * f_pe * util * 3.5e5)
        reduction_time = reduce_ops * mix['reduce'] * scale / (array_size * f_pe * util * 7.5e5)
        refresh_time = update_ops * mix['update'] * scale / (array_size * f_pe * util * 9.0e5)
        return {'compute': gemm_time, 'solve': diag_time, 'reduce': reduction_time, 'update': refresh_time}

    def _combine_kernel_times(self, kernel_times: Mapping[str, float], mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any], iterations: float) -> float:
        scale = max(1.0, iterations)
        per_iter = {key: value / scale for key, value in kernel_times.items()}
        return sum(per_iter.values()) * 0.88 * scale


class F3DataflowModel(FamilyModel):
    family = 'F3'
    model_name = 'F3DataflowModel'

    def _kernel_times(self, *, compute_ops: float, solve_ops: float, reduce_ops: float, update_ops: float, bytes_moved: float, iterations: float, mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any]) -> Dict[str, float]:
        scale = max(1.0, iterations)
        compute_scale = max(0.5, float(system.get('compute_scale', 1.0)))
        memory_scale = max(0.5, float(system.get('memory_scale', 1.0)))
        interconnect_scale = max(0.5, float(system.get('interconnect_scale', 1.0)))
        compute = (compute_ops * mix['compute'] + solve_ops * mix['solve'] + reduce_ops * mix['reduce'] + update_ops * mix['update']) * scale / (2.5e9 * compute_scale)
        memory = bytes_moved * scale / (77.0e9 * memory_scale)
        interconnect = (bytes_moved * 0.12) * scale / (40.0e9 * interconnect_scale)
        return {'compute': compute, 'solve': compute * mix['solve'], 'reduce': compute * mix['reduce'], 'update': compute * mix['update'], 'memory': memory, 'interconnect': interconnect}

    def _combine_kernel_times(self, kernel_times: Mapping[str, float], mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any], iterations: float) -> float:
        scale = max(1.0, iterations)
        per_iter = {key: value / scale for key, value in kernel_times.items()}
        return (max(per_iter['compute'], per_iter['memory']) + per_iter['interconnect']) * scale


class F4CimDspHbmModel(FamilyModel):
    family = 'F4'
    model_name = 'F4CimDspHbmModel'

    def _kernel_times(self, *, compute_ops: float, solve_ops: float, reduce_ops: float, update_ops: float, bytes_moved: float, iterations: float, mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any]) -> Dict[str, float]:
        scale = max(1.0, iterations)
        cim_rate = float(system.get('cim_rate_scale', 1.0)) * 3.2e9
        dsp_rate = float(system.get('dsp_rate_scale', 1.0)) * 2.1e9
        hbm_bw = float(system.get('hbm_bw_gbs', 128.0)) * 1.0e9
        operator = min(compute_ops / cim_rate, compute_ops / dsp_rate) * mix['compute'] * scale
        diag = solve_ops * mix['solve'] * scale / (1.8e9)
        reduction = reduce_ops * mix['reduce'] * scale / (2.8e9)
        refresh = update_ops * mix['update'] * scale / (3.2e9)
        memory = bytes_moved * scale / hbm_bw
        return {'compute': operator, 'solve': diag, 'reduce': reduction, 'update': refresh, 'memory': memory}

    def _combine_kernel_times(self, kernel_times: Mapping[str, float], mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any], iterations: float) -> float:
        scale = max(1.0, iterations)
        per_iter = {key: value / scale for key, value in kernel_times.items()}
        compute = per_iter['compute'] + per_iter['solve'] + per_iter['reduce'] + per_iter['update']
        return (max(compute, per_iter['memory']) + 0.5 * per_iter['memory']) * scale


class F5CgraModel(FamilyModel):
    family = 'F5'
    model_name = 'F5CgraModel'

    def _kernel_times(self, *, compute_ops: float, solve_ops: float, reduce_ops: float, update_ops: float, bytes_moved: float, iterations: float, mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any]) -> Dict[str, float]:
        scale = max(1.0, iterations)
        rows = max(1.0, float(system.get('cgra_rows', 16.0)))
        cols = max(1.0, float(system.get('cgra_cols', 16.0)))
        fabric = rows * cols * max(0.5, float(system.get('compute_scale', 1.0)))
        reconfig = float(workload.get('reconfiguration_cycles', 4000.0)) / (float(system.get('clock_mhz', 250.0)) * 1.0e6)
        h = compute_ops * mix['compute'] * scale / (fabric * 2.4e9)
        c = solve_ops * mix['solve'] * scale / (fabric * 0.85e9)
        r = reduce_ops * mix['reduce'] * scale / (fabric * 1.6e9)
        f = update_ops * mix['update'] * scale / (fabric * 1.9e9)
        return {'compute': h + reconfig * 0.35 * scale, 'solve': c, 'reduce': r, 'update': f, 'reconfig': reconfig * scale}

    def _combine_kernel_times(self, kernel_times: Mapping[str, float], mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any], iterations: float) -> float:
        scale = max(1.0, iterations)
        per_iter = {key: value / scale for key, value in kernel_times.items()}
        return (sum(per_iter[k] for k in ('compute', 'solve', 'reduce', 'update')) + per_iter['reconfig'] * 0.25) * scale


class F6CustomModel(FamilyModel):
    family = 'F6'
    model_name = 'F6CustomModel'

    def _kernel_times(self, *, compute_ops: float, solve_ops: float, reduce_ops: float, update_ops: float, bytes_moved: float, iterations: float, mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any]) -> Dict[str, float]:
        scale = max(1.0, iterations)
        chiplets = max(1.0, float(system.get('chiplets', 4.0)))
        noc_bw = float(system.get('noc_bw_gbs', 256.0)) * 1.0e9
        local = chiplets * float(system.get('local_compute_scale', 1.0))
        h = compute_ops * mix['compute'] * scale / (local * 2.1e9)
        c = solve_ops * mix['solve'] * scale / (local * 0.95e9)
        r = reduce_ops * mix['reduce'] * scale / (local * 1.7e9)
        f = update_ops * mix['update'] * scale / (local * 1.8e9)
        noc = bytes_moved * scale / noc_bw
        skew = 0.002 * math.log2(chiplets + 1.0) * scale
        return {'compute': h, 'solve': c, 'reduce': r, 'update': f, 'noc': noc, 'skew': skew}

    def _combine_kernel_times(self, kernel_times: Mapping[str, float], mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any], iterations: float) -> float:
        scale = max(1.0, iterations)
        per_iter = {key: value / scale for key, value in kernel_times.items()}
        return (max(per_iter['compute'] + per_iter['solve'] + per_iter['reduce'] + per_iter['update'], per_iter['noc']) + per_iter['skew']) * scale


class F7FutureModel(FamilyModel):
    family = 'F7'
    model_name = 'F7FutureModel'

    def _kernel_times(self, *, compute_ops: float, solve_ops: float, reduce_ops: float, update_ops: float, bytes_moved: float, iterations: float, mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any]) -> Dict[str, float]:
        scale = max(1.0, iterations)
        blend = 0.5 * (compute_ops / 2.0e9) + 0.3 * (solve_ops / 1.2e9) + 0.1 * (reduce_ops / 1.6e9) + 0.1 * (update_ops / 1.8e9)
        adaptive = blend / max(1.0, float(system.get('adaptivity_factor', 1.0)))
        return {'compute': adaptive * mix['compute'] * scale, 'solve': adaptive * mix['solve'] * scale, 'reduce': adaptive * mix['reduce'] * scale, 'update': adaptive * mix['update'] * scale, 'reconfigure': 0.003 * float(system.get('adaptivity_factor', 1.0)) * scale}

    def _combine_kernel_times(self, kernel_times: Mapping[str, float], mix: Mapping[str, float], system: Mapping[str, Any], workload: Mapping[str, Any], iterations: float) -> float:
        scale = max(1.0, iterations)
        per_iter = {key: value / scale for key, value in kernel_times.items()}
        return (sum(per_iter[k] for k in ('compute', 'solve', 'reduce', 'update')) + per_iter['reconfigure']) * scale
