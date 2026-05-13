#!/usr/bin/env python3

from dataclasses import asdict, dataclass
from math import ceil
from typing import Any, Dict, Mapping


@dataclass(frozen=True)
class Layer2Output:
    family: str
    status: str
    metrics: Dict[str, float]
    uncertainty: Dict[str, Any]
    resource_utilization: Dict[str, float]
    promotion_score: float
    confidence: float
    fidelity_level_achieved: str = 'L2'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)



FAMILY_TIMING_SCALE = {
    'F1': 1.50,
    'F2': 1.25,
    'F3': 1.00,
    'F4': 1.00,
    'F5': 0.018,
    'F6': 1.00,
    'F7': 1.00,
}

class PythonTLM:
    def __init__(self, clock_mhz: float = 250.0, pcie_bw_gbps: float = 64.0, dram_bw_gbps: float = 128.0):
        self.clock_mhz = clock_mhz
        self.pcie_bw_gbps = pcie_bw_gbps
        self.dram_bw_gbps = dram_bw_gbps

    def run_episode(self, design_point: Mapping[str, Any], workload: Mapping[str, Any]) -> Layer2Output:
        params = self._system_params(design_point)
        problem_size = float(workload.get('problem_size', 4096))
        feature_size = float(workload.get('feature_size', 256))
        batch_size = float(workload.get('batch_size', 16))
        iterations = float(workload.get('iterations', workload.get('total_iterations', 1)))

        gemm_tiles = max(1.0, float(params.get('n_gemm_tiles', params.get('parallel_units', 4))))
        eigen_tiles = max(1.0, float(params.get('n_eigen_tiles', 1)))
        local_mem_kb = max(1.0, float(params.get('tile_local_mem_kb', params.get('intermediate_buffer_kb', 512))))
        family = str(params.get('family', design_point.get('family', 'F1')))
        max_power_w = float(params.get('max_power_w', design_point.get('max_power_w', 75.0)))
        pcie_bw_gbps = float(params.get('pcie_bw_gbps', design_point.get('pcie_bw_gbps', self.pcie_bw_gbps)))
        dram_bw_gbps = float(params.get('dram_bw_gbps', design_point.get('dram_bw_gbps', self.dram_bw_gbps)))

        dense_compute_flops = 2.0 * problem_size * feature_size * batch_size * iterations
        solver_flops = feature_size * feature_size * max(batch_size, 1.0) * iterations

        dense_compute_ms = self._compute_time_ms(dense_compute_flops, gemm_tiles, 88.0)
        dense_transfer_ms = self._transaction_time_ms(
            bytes_count=(problem_size * batch_size + problem_size * feature_size) * 16.0 * iterations,
            bandwidth_gbps=dram_bw_gbps,
            transaction_bytes=max(64.0, local_mem_kb * 1024.0 / 2.0),
            latency_us=0.55,
        )

        solver_compute_ms = self._compute_time_ms(solver_flops, eigen_tiles, 36.0)
        solver_transfer_ms = self._transaction_time_ms(
            bytes_count=(feature_size * feature_size + feature_size * batch_size) * 16.0 * iterations,
            bandwidth_gbps=dram_bw_gbps,
            transaction_bytes=max(32.0, local_mem_kb * 1024.0 / 4.0),
            latency_us=0.7,
        )

        host_device_transfer_ms = self._transaction_time_ms(
            bytes_count=(problem_size * feature_size + problem_size * batch_size) * 16.0,
            bandwidth_gbps=pcie_bw_gbps,
            transaction_bytes=4096.0,
            latency_us=1.4,
        )

        timing_scale = FAMILY_TIMING_SCALE.get(family, 1.0)
        dense_compute_ms *= timing_scale
        dense_transfer_ms *= timing_scale
        solver_compute_ms *= timing_scale
        solver_transfer_ms *= timing_scale
        host_device_transfer_ms *= timing_scale

        mapping_penalty = self._mapping_penalty(params)
        dataflow_speedup = self._dataflow_speedup(params)

        latency_ms = (dense_compute_ms + dense_transfer_ms + solver_compute_ms + solver_transfer_ms + host_device_transfer_ms)
        latency_ms *= (1.0 + mapping_penalty)
        latency_ms *= (1.0 - dataflow_speedup)

        power_w = 17.5 + 2.6 * gemm_tiles + 3.1 * eigen_tiles + 0.0018 * local_mem_kb + 0.02 * latency_ms
        area_mm2 = 18.0 + 2.2 * gemm_tiles + 3.0 * eigen_tiles + 0.0014 * local_mem_kb
        total_ops = dense_compute_flops + solver_flops
        throughput_gops = total_ops / max(latency_ms, 1.0e-9) / 1.0e6
        energy_efficiency = throughput_gops / max(power_w, 1.0e-9)

        resource_utilization = {
            'compute_percent': min(180.0, (gemm_tiles * 0.75 + eigen_tiles * 0.90) / 12.0 * 100.0),
            'memory_percent': min(180.0, local_mem_kb / 2048.0 * 100.0),
            'bandwidth_percent': min(180.0, (host_device_transfer_ms / max(latency_ms, 1.0e-9)) * 55.0),
        }
        resource_margin = max(0.0, 1.0 - max(resource_utilization.values()) / 100.0)
        balance = 1.0 - min(1.0, abs(gemm_tiles - eigen_tiles) / max(gemm_tiles + eigen_tiles, 1.0))
        confidence = max(0.0, min(0.97, 0.74 + 0.16 * resource_margin + 0.05 * balance + 0.03 * min(1.0, local_mem_kb / 1024.0)))
        accuracy_vs_reference = max(0.0, min(0.99, 0.82 + 0.12 * confidence + 0.06 * resource_margin))
        promotion_score = max(
            0.0,
            min(
                1.0,
                0.48 * accuracy_vs_reference
                + 0.30 * confidence
                + 0.17 * resource_margin
                + 0.05,
            ),
        )
        mape_percent = max(5.0, 22.0 * (1.0 - confidence))
        status = 'passed' if max(resource_utilization.values()) <= 100.0 and power_w <= max_power_w else 'failed'

        return Layer2Output(
            family=family,
            status=status,
            metrics={
                'latency_ms': latency_ms,
                'throughput_gops': throughput_gops,
                'power_w': power_w,
                'area_mm2': area_mm2,
                'energy_efficiency_gops_per_w': energy_efficiency,
                'accuracy_vs_reference': accuracy_vs_reference,
                'dense_compute_latency_ms': dense_compute_ms + dense_transfer_ms,
                'solver_latency_ms': solver_compute_ms + solver_transfer_ms,
                'data_transfer_ms': host_device_transfer_ms,
            },
            uncertainty={'confidence_level': confidence, 'mape_percent': mape_percent, 'sample_size': int(max(1, round(iterations)))},
            resource_utilization=resource_utilization,
            promotion_score=promotion_score,
            confidence=confidence,
        )

    def _system_params(self, design_point: Mapping[str, Any]) -> Mapping[str, Any]:
        if hasattr(design_point, 'to_dict'):
            design_point = design_point.to_dict()

        if isinstance(design_point, Mapping):
            if 'architecture' in design_point and isinstance(design_point['architecture'], Mapping):
                arch = design_point['architecture']
                params = {
                    'family': arch.get('family', 'F1'),
                    'clock_mhz': arch.get('clock_mhz', 250.0),
                    'parallel_units': arch.get('parallel_units', 4),
                    'n_gemm_tiles': arch.get('gemm_tiles', 4),
                    'n_eigen_tiles': arch.get('eigen_tiles', 1),
                    'tile_local_mem_kb': arch.get('local_mem_kb', 512.0),
                    'max_power_w': arch.get('max_power_w', 75.0),
                    'pcie_bw_gbps': arch.get('pcie_bw_gbps', self.pcie_bw_gbps),
                    'dram_bw_gbps': arch.get('dram_bw_gbps', self.dram_bw_gbps),
                }
                if 'mapping' in design_point:
                    params['mapping'] = design_point['mapping']
                if 'dataflow' in design_point:
                    params['dataflow'] = design_point['dataflow']
                return params

            if 'parameters' in design_point and isinstance(design_point['parameters'], Mapping):
                params = design_point['parameters']
                if 'system_level' in params and isinstance(params['system_level'], Mapping):
                    merged = dict(params['system_level'])
                    for key, value in params.items():
                        if key != 'system_level' and key not in merged:
                            merged[key] = value
                    return merged
                return params

        return design_point

    def _compute_time_ms(self, flops: float, tiles: float, base_gops_per_tile: float) -> float:
        efficiency = 0.72 + 0.03 * min(tiles, 8.0)
        throughput_gops = max(1.0, tiles * base_gops_per_tile * efficiency * (self.clock_mhz / 250.0))
        return flops / (throughput_gops * 1.0e9) * 1000.0

    def _transaction_time_ms(self, bytes_count: float, bandwidth_gbps: float, transaction_bytes: float, latency_us: float) -> float:
        bytes_count = max(0.0, float(bytes_count))
        bandwidth_gbps = max(1.0, float(bandwidth_gbps))
        transaction_bytes = max(1.0, float(transaction_bytes))
        transactions = max(1, int(ceil(bytes_count / transaction_bytes)))
        bandwidth_ms = bytes_count * 8.0 / (bandwidth_gbps * 1.0e9) * 1000.0
        latency_ms = transactions * latency_us / 1000.0
        return bandwidth_ms + latency_ms

    def _mapping_penalty(self, params: Mapping[str, Any]) -> float:
        mapping = params.get('mapping', {})
        if not mapping:
            return 0.0
        penalty = 0.0
        phases = ['compute', 'transform', 'solve', 'update']
        for phase in phases:
            target = mapping.get(phase, 'accel_compute')
            if target == 'cpu':
                penalty += 0.15
            elif target == 'auto':
                penalty += 0.05
        return min(0.5, penalty)

    def _dataflow_speedup(self, params: Mapping[str, Any]) -> float:
        dataflow = params.get('dataflow', {})
        if not dataflow:
            return 0.0
        speedup = 0.0
        if dataflow.get('double_buffer', False):
            speedup += 0.08
        if dataflow.get('overlap_dma_compute', False):
            speedup += 0.12
        if dataflow.get('keep_resident', False):
            speedup += 0.05
        return min(0.25, speedup)
