#!/usr/bin/env python3

import numpy as np
from typing import Dict, Any

class FastPerformanceModel:
    
    def __init__(self, fpga_specs: Dict[str, Any]):
        self.peak_gflops = fpga_specs['peak_gflops']
        self.memory_bw_gbs = fpga_specs['memory_bw_gbs']
        self.pcie_bw_gbs = fpga_specs['pcie_bw_gbs']
        self.bram_kb = fpga_specs['bram_kb']
        self.dsp_count = fpga_specs['dsp_count']
    
    def estimate_h_psi_time(self, design_point: Dict, workload: Dict) -> float:
        npw = workload['npw']
        nkb = workload['nkb']
        m = workload['m']
        
        fft_flops = 5 * npw * np.log2(npw) * m
        gemm_flops = 2 * npw * nkb * m
        total_flops = fft_flops + gemm_flops
        
        psi_bytes = npw * m * 16
        beta_bytes = npw * nkb * 16
        total_bytes = psi_bytes + beta_bytes
        
        compute_intensity = total_flops / total_bytes
        
        compute_bound_time = total_flops / (self.peak_gflops * 1e9)
        memory_bound_time = total_bytes / (self.memory_bw_gbs * 1e9)
        
        base_time = max(compute_bound_time, memory_bound_time)
        
        pipeline_efficiency = 0.7 + 0.05 * design_point['pipeline_depth']
        parallel_speedup = min(design_point['parallel_units'], m) * 0.8
        
        dataflow_overhead = {
            'streaming': 1.0,
            'buffered': 1.1,
            'hybrid': 1.05,
        }[design_point['dataflow_pattern']]
        
        tile_overhead = 1.0 + (npw / design_point['tile_npw'] - 1) * 0.05
        
        estimated_time = (base_time / (pipeline_efficiency * parallel_speedup)) * dataflow_overhead * tile_overhead
        
        return estimated_time
    
    def estimate_energy(self, design_point: Dict, time: float) -> float:
        base_power_w = 25
        dynamic_power_w = (
            design_point['parallel_units'] * 5 +
            design_point['pipeline_depth'] * 2
        )
        
        total_power_w = base_power_w + dynamic_power_w
        energy_j = total_power_w * time
        
        return energy_j
    
    def estimate_area(self, design_point: Dict) -> Dict[str, float]:
        dsp_usage = (
            design_point['parallel_units'] * 100 +
            design_point['pipeline_depth'] * 20
        )
        
        bram_usage_kb = (
            design_point['intermediate_buffer_kb'] +
            design_point['tile_npw'] * design_point['tile_m'] * 16 / 1024
        )
        
        lut_usage = dsp_usage * 50 + bram_usage_kb * 10
        
        return {
            'dsp_count': dsp_usage,
            'dsp_utilization': dsp_usage / self.dsp_count,
            'bram_kb': bram_usage_kb,
            'bram_utilization': bram_usage_kb / self.bram_kb,
            'lut_count': lut_usage,
            'lut_utilization': lut_usage / 600000,
        }
    
    def compute_area_cost(self, design_point: Dict) -> float:
        area = self.estimate_area(design_point)
        
        dsp_cost = area['dsp_count'] * 1.0
        bram_cost = area['bram_kb'] * 0.1
        lut_cost = area['lut_count'] * 0.001
        
        total_cost = dsp_cost + bram_cost + lut_cost
        
        return total_cost
    
    def check_constraints(self, design_point: Dict) -> Dict[str, bool]:
        area = self.estimate_area(design_point)
        time = self.estimate_h_psi_time(design_point, {'npw': 2945, 'nkb': 144, 'm': 16})
        power = self.estimate_energy(design_point, time) / time
        
        constraints = {
            'dsp_ok': area['dsp_utilization'] <= 0.80,
            'bram_ok': area['bram_utilization'] <= 0.70,
            'lut_ok': area['lut_utilization'] <= 0.60,
            'power_ok': power <= 75.0,
        }
        
        constraints['all_ok'] = all(constraints.values())
        
        return constraints
    
    def evaluate_design_point(self, design_point: Dict, workload: Dict) -> Dict[str, Any]:
        time = self.estimate_h_psi_time(design_point, workload)
        energy = self.estimate_energy(design_point, time)
        area = self.estimate_area(design_point)
        
        feasible = (
            area['dsp_utilization'] < 0.9 and
            area['bram_utilization'] < 0.9
        )
        
        return {
            'time_s': time,
            'energy_j': energy,
            'area': area,
            'feasible': feasible,
        }

if __name__ == '__main__':
    fpga_specs = {
        'peak_gflops': 1300,
        'memory_bw_gbs': 77,
        'pcie_bw_gbs': 16,
        'bram_kb': 34000,
        'dsp_count': 12288,
    }
    
    model = FastPerformanceModel(fpga_specs)
    
    design_point = {
        'offload_strategy': 'h_s_psi_fused',
        'pipeline_depth': 4,
        'parallel_units': 4,
        'dataflow_pattern': 'streaming',
        'tile_npw': 1024,
        'tile_nkb': 64,
        'tile_m': 16,
        'intermediate_buffer_kb': 256,
    }
    
    workload = {
        'npw': 2945,
        'nkb': 144,
        'm': 16,
    }
    
    result = model.evaluate_design_point(design_point, workload)
    print(f"Estimated time: {result['time_s']*1000:.2f} ms")
    print(f"Estimated energy: {result['energy_j']:.2f} J")
    print(f"DSP utilization: {result['area']['dsp_utilization']*100:.1f}%")
    print(f"BRAM utilization: {result['area']['bram_utilization']*100:.1f}%")
    print(f"Feasible: {result['feasible']}")
