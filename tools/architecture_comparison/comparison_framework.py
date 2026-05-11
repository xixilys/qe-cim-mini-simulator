#!/usr/bin/env python3
"""
Architecture Comparison Framework

Provides analytical models for comparing different hardware architectures
for DFT acceleration based on workload characterization data.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
import numpy as np


@dataclass
class WorkloadCharacteristics:
    """Workload characteristics from characterization phase"""
    # Kernel time distribution
    h_psi_fraction: float = 0.68
    s_psi_fraction: float = 0.15
    build_fraction: float = 0.04
    cdiaghg_fraction: float = 0.23
    refresh_fraction: float = 0.05
    
    # Tensor dimensions
    npw: int = 2945
    nkb: int = 144
    m: int = 16
    n: int = 32
    
    # Arithmetic intensity (FLOPs/Byte)
    h_psi_ai: float = 11.0
    s_psi_ai: float = 11.0
    build_ai: float = 7.89
    cdiaghg_ai: float = 9.89
    
    # Total FLOPs
    total_flops: float = 18.35e9  # 18.35 GFLOPs for si8


@dataclass
class ArchitectureConfig:
    """Architecture configuration parameters"""
    name: str
    
    # Compute resources
    peak_gflops: float
    n_compute_units: int
    
    # Memory hierarchy
    l1_size_kb: int
    l2_size_kb: int
    off_chip_bw_gbs: float  # GB/s
    
    # Interconnect
    interconnect_type: str  # "fifo", "crossbar", "noc", "mesh"
    interconnect_bw_gbs: float
    
    # Power
    peak_power_w: float
    idle_power_w: float


class ArchitectureModel:
    """Base class for architecture analytical models"""
    
    def __init__(self, config: ArchitectureConfig, workload: WorkloadCharacteristics):
        self.config = config
        self.workload = workload
        
    def estimate_performance(self) -> Dict[str, float]:
        """Estimate performance metrics"""
        raise NotImplementedError
        
    def estimate_energy(self) -> Dict[str, float]:
        """Estimate energy consumption"""
        raise NotImplementedError
        
    def estimate_area(self) -> Dict[str, float]:
        """Estimate area/resource utilization"""
        raise NotImplementedError
        
    def roofline_analysis(self) -> Tuple[float, str]:
        """
        Roofline analysis to determine if compute-bound or memory-bound
        Returns: (achieved_gflops, bottleneck_type)
        """
        # Compute-bound performance
        compute_bound_gflops = self.config.peak_gflops
        
        # Memory-bound performance (AI × BW)
        avg_ai = (
            self.workload.h_psi_ai * self.workload.h_psi_fraction +
            self.workload.s_psi_ai * self.workload.s_psi_fraction +
            self.workload.build_ai * self.workload.build_fraction +
            self.workload.cdiaghg_ai * self.workload.cdiaghg_fraction
        )
        memory_bound_gflops = avg_ai * self.config.off_chip_bw_gbs
        
        if compute_bound_gflops < memory_bound_gflops:
            return compute_bound_gflops, "compute_bound"
        else:
            return memory_bound_gflops, "memory_bound"


class FourClusterPipeline(ArchitectureModel):
    """4-Cluster Pipeline architecture (current baseline)"""
    
    def estimate_performance(self) -> Dict[str, float]:
        """
        Performance model for 4-cluster pipeline
        T_total = T_A + barrier + T_B + barrier + T_C + T_D
        """
        # Assume each cluster has 1/4 of total compute
        cluster_gflops = self.config.peak_gflops / 4
        
        # Time for each cluster (proportional to workload fraction)
        t_a = (self.workload.h_psi_fraction + self.workload.s_psi_fraction) * \
              self.workload.total_flops / cluster_gflops
        t_b = self.workload.build_fraction * self.workload.total_flops / cluster_gflops
        t_c = self.workload.cdiaghg_fraction * self.workload.total_flops / cluster_gflops
        t_d = self.workload.refresh_fraction * self.workload.total_flops / cluster_gflops
        
        # Barrier overhead (assume 5% per barrier)
        barrier_overhead = 0.05 * (t_a + t_b + t_c)
        
        # Total time (sequential with barriers)
        t_total = t_a + t_b + t_c + t_d + barrier_overhead
        
        # Utilization (actual compute time / total time / num_clusters)
        utilization = (t_a + t_b + t_c + t_d) / (t_total * 4)
        
        # Effective throughput
        effective_gflops = self.workload.total_flops / t_total
        
        return {
            "total_time_s": t_total,
            "effective_gflops": effective_gflops,
            "utilization": utilization,
            "t_cluster_a": t_a,
            "t_cluster_b": t_b,
            "t_cluster_c": t_c,
            "t_cluster_d": t_d,
            "barrier_overhead": barrier_overhead
        }
    
    def estimate_energy(self) -> Dict[str, float]:
        perf = self.estimate_performance()
        
        # Active energy
        active_energy = perf["total_time_s"] * self.config.peak_power_w * perf["utilization"]
        
        # Idle energy (unused clusters)
        idle_energy = perf["total_time_s"] * self.config.idle_power_w * (1 - perf["utilization"]) * 4
        
        total_energy = active_energy + idle_energy
        
        return {
            "total_energy_j": total_energy,
            "active_energy_j": active_energy,
            "idle_energy_j": idle_energy,
            "energy_efficiency_gflops_w": perf["effective_gflops"] / (total_energy / perf["total_time_s"])
        }
    
    def estimate_area(self) -> Dict[str, float]:
        # Baseline area = 1.0
        return {
            "relative_area": 1.0,
            "compute_area": 0.6,
            "memory_area": 0.25,
            "interconnect_area": 0.15
        }


class UnifiedSystolicArray(ArchitectureModel):
    """Unified Systolic Array architecture"""
    
    def estimate_performance(self) -> Dict[str, float]:
        """
        Performance model for unified systolic array
        All GEMM operations use the same array, eigensolver is separate
        """
        # GEMM operations (h_psi + s_psi + build) use systolic array
        gemm_fraction = self.workload.h_psi_fraction + self.workload.s_psi_fraction + \
                       self.workload.build_fraction
        gemm_flops = gemm_fraction * self.workload.total_flops
        
        # Systolic array gets 80% of compute resources
        systolic_gflops = self.config.peak_gflops * 0.8
        t_gemm = gemm_flops / systolic_gflops
        
        # Eigensolver gets 20% of compute resources
        eigen_gflops = self.config.peak_gflops * 0.2
        eigen_flops = self.workload.cdiaghg_fraction * self.workload.total_flops
        t_eigen = eigen_flops / eigen_gflops
        
        # Refresh can overlap with eigensolver (assume 50% overlap)
        refresh_flops = self.workload.refresh_fraction * self.workload.total_flops
        t_refresh = refresh_flops / systolic_gflops * 0.5
        
        # Total time (GEMM sequential, eigen + refresh overlap)
        t_total = t_gemm + max(t_eigen, t_refresh)
        
        # Utilization
        total_compute_time = t_gemm + t_eigen + t_refresh
        utilization = total_compute_time / t_total
        
        effective_gflops = self.workload.total_flops / t_total
        
        return {
            "total_time_s": t_total,
            "effective_gflops": effective_gflops,
            "utilization": utilization,
            "t_gemm": t_gemm,
            "t_eigen": t_eigen,
            "t_refresh": t_refresh
        }
    
    def estimate_energy(self) -> Dict[str, float]:
        perf = self.estimate_performance()
        
        # Higher utilization = better energy efficiency
        active_energy = perf["total_time_s"] * self.config.peak_power_w * perf["utilization"]
        idle_energy = perf["total_time_s"] * self.config.idle_power_w * (1 - perf["utilization"])
        
        total_energy = active_energy + idle_energy
        
        return {
            "total_energy_j": total_energy,
            "active_energy_j": active_energy,
            "idle_energy_j": idle_energy,
            "energy_efficiency_gflops_w": perf["effective_gflops"] / (total_energy / perf["total_time_s"])
        }
    
    def estimate_area(self) -> Dict[str, float]:
        # Slightly smaller than 4-cluster (no FIFO overhead)
        return {
            "relative_area": 0.85,
            "compute_area": 0.65,
            "memory_area": 0.25,
            "interconnect_area": 0.10
        }


class DataflowFabric(ArchitectureModel):
    """Dataflow Fabric architecture with flexible interconnect"""
    
    def estimate_performance(self) -> Dict[str, float]:
        """
        Performance model for dataflow fabric
        Assumes dynamic PE allocation and good load balancing
        """
        # Assume 70% utilization due to better load balancing
        base_utilization = 0.70
        
        # NoC overhead (10% latency penalty)
        noc_overhead = 1.10
        
        # Effective compute
        effective_gflops = self.config.peak_gflops * base_utilization
        
        t_total = (self.workload.total_flops / effective_gflops) * noc_overhead
        
        return {
            "total_time_s": t_total,
            "effective_gflops": self.workload.total_flops / t_total,
            "utilization": base_utilization,
            "noc_overhead": noc_overhead - 1.0
        }
    
    def estimate_energy(self) -> Dict[str, float]:
        perf = self.estimate_performance()
        
        # NoC consumes extra power (15% overhead)
        noc_power_overhead = 1.15
        
        active_energy = perf["total_time_s"] * self.config.peak_power_w * \
                       perf["utilization"] * noc_power_overhead
        idle_energy = perf["total_time_s"] * self.config.idle_power_w * (1 - perf["utilization"])
        
        total_energy = active_energy + idle_energy
        
        return {
            "total_energy_j": total_energy,
            "active_energy_j": active_energy,
            "idle_energy_j": idle_energy,
            "energy_efficiency_gflops_w": perf["effective_gflops"] / (total_energy / perf["total_time_s"])
        }
    
    def estimate_area(self) -> Dict[str, float]:
        # Larger due to NoC
        return {
            "relative_area": 1.25,
            "compute_area": 0.55,
            "memory_area": 0.25,
            "interconnect_area": 0.20
        }


def compare_architectures(workload: WorkloadCharacteristics) -> Dict[str, Any]:
    """Compare all architecture candidates"""
    
    # Define architecture configurations
    configs = {
        "4cluster": ArchitectureConfig(
            name="4-Cluster Pipeline",
            peak_gflops=512,
            n_compute_units=4,
            l1_size_kb=512,
            l2_size_kb=4096,
            off_chip_bw_gbs=200,
            interconnect_type="fifo",
            interconnect_bw_gbs=64,
            peak_power_w=50,
            idle_power_w=5
        ),
        "systolic": ArchitectureConfig(
            name="Unified Systolic Array",
            peak_gflops=512,
            n_compute_units=1,
            l1_size_kb=512,
            l2_size_kb=2048,
            off_chip_bw_gbs=200,
            interconnect_type="crossbar",
            interconnect_bw_gbs=128,
            peak_power_w=45,
            idle_power_w=5
        ),
        "dataflow": ArchitectureConfig(
            name="Dataflow Fabric",
            peak_gflops=512,
            n_compute_units=16,
            l1_size_kb=1024,
            l2_size_kb=3072,
            off_chip_bw_gbs=200,
            interconnect_type="noc",
            interconnect_bw_gbs=256,
            peak_power_w=55,
            idle_power_w=6
        )
    }
    
    # Create models
    models = {
        "4cluster": FourClusterPipeline(configs["4cluster"], workload),
        "systolic": UnifiedSystolicArray(configs["systolic"], workload),
        "dataflow": DataflowFabric(configs["dataflow"], workload)
    }
    
    # Run comparison
    results = {}
    for name, model in models.items():
        perf = model.estimate_performance()
        energy = model.estimate_energy()
        area = model.estimate_area()
        roofline_gflops, bottleneck = model.roofline_analysis()
        
        results[name] = {
            "config": model.config,
            "performance": perf,
            "energy": energy,
            "area": area,
            "roofline_gflops": roofline_gflops,
            "bottleneck": bottleneck
        }
    
    return results


if __name__ == "__main__":
    # Example usage
    workload = WorkloadCharacteristics()
    results = compare_architectures(workload)
    
    print("=" * 80)
    print("Architecture Comparison Results")
    print("=" * 80)
    
    for arch_name, data in results.items():
        print(f"\n{data['config'].name}:")
        print(f"  Performance:")
        print(f"    Total Time: {data['performance']['total_time_s']:.4f} s")
        print(f"    Effective GFLOPS: {data['performance']['effective_gflops']:.2f}")
        print(f"    Utilization: {data['performance']['utilization']*100:.1f}%")
        print(f"  Energy:")
        print(f"    Total Energy: {data['energy']['total_energy_j']:.2f} J")
        print(f"    Energy Efficiency: {data['energy']['energy_efficiency_gflops_w']:.2f} GFLOPS/W")
        print(f"  Area:")
        print(f"    Relative Area: {data['area']['relative_area']:.2f}x")
        print(f"  Roofline:")
        print(f"    Achievable GFLOPS: {data['roofline_gflops']:.2f}")
        print(f"    Bottleneck: {data['bottleneck']}")
