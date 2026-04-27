#!/usr/bin/env python3
"""
Step 2: Kernel Mapping Layer DSE

For identified hardware-friendly kernels, systematically explore:
- Tile sizes (npw, nkb, m dimensions)
- Loop orderings (6 permutations)
- Dataflow strategies (weight-stationary, output-stationary, row-stationary)
- Buffer allocation (L1, L2, L3 sizes)

Output:
- Utilization for each mapping configuration
- Roofline analysis
- Bottleneck identification
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from itertools import permutations, product
from pathlib import Path
from typing import Any

COMPLEX_FP64_BYTES = 16
REAL_FP64_BYTES = 8


@dataclass
class TileConfig:
    """Tile size configuration"""
    tile_npw: int
    tile_nkb: int
    tile_m: int


@dataclass
class LoopOrdering:
    """Loop ordering configuration"""
    outer: str
    middle: str
    inner: str
    
    def to_tuple(self) -> tuple[str, str, str]:
        return (self.outer, self.middle, self.inner)


@dataclass
class DataflowStrategy:
    """Dataflow strategy"""
    name: str
    stationary_operand: str
    streaming_operands: list[str]
    accumulation_operand: str


@dataclass
class BufferAllocation:
    """Buffer hierarchy allocation"""
    l1_size_kb: int
    l2_size_kb: int
    l3_size_kb: int


@dataclass
class MappingConfig:
    """Complete mapping configuration"""
    tile: TileConfig
    loop_order: LoopOrdering
    dataflow: DataflowStrategy
    buffer: BufferAllocation


@dataclass
class PerformanceMetrics:
    """Performance metrics for a mapping"""
    compute_utilization: float
    memory_utilization: float
    arithmetic_intensity: float
    peak_flops: float
    achieved_flops: float
    peak_bandwidth_gbs: float
    achieved_bandwidth_gbs: float
    bottleneck: str
    roofline_position: str


@dataclass
class MappingResult:
    """Result of mapping analysis"""
    config: MappingConfig
    metrics: PerformanceMetrics
    feasible: bool
    reason: str


class ProjectorGEMMMapper:
    """Mapper for Projector GEMM kernel (beta^H * psi)"""
    
    def __init__(self, npw: int, nkb: int, m: int, pe_count: int = 256, 
                 peak_bandwidth_gbs: float = 200.0):
        self.npw = npw
        self.nkb = nkb
        self.m = m
        self.pe_count = pe_count
        self.peak_bandwidth_gbs = peak_bandwidth_gbs
        self.peak_flops = pe_count * 2 * 1e9
    
    def estimate_compute_ops(self, tile: TileConfig) -> int:
        """Estimate compute operations for tiled execution"""
        num_tiles_npw = math.ceil(self.npw / tile.tile_npw)
        num_tiles_nkb = math.ceil(self.nkb / tile.tile_nkb)
        num_tiles_m = math.ceil(self.m / tile.tile_m)
        
        ops_per_tile = tile.tile_npw * tile.tile_nkb * tile.tile_m * 8
        total_ops = num_tiles_npw * num_tiles_nkb * num_tiles_m * ops_per_tile
        
        return int(total_ops)
    
    def estimate_memory_traffic(self, tile: TileConfig, dataflow: DataflowStrategy) -> int:
        """Estimate memory traffic based on dataflow"""
        num_tiles_npw = math.ceil(self.npw / tile.tile_npw)
        num_tiles_nkb = math.ceil(self.nkb / tile.tile_nkb)
        num_tiles_m = math.ceil(self.m / tile.tile_m)
        
        if dataflow.name == 'weight_stationary':
            beta_traffic = self.npw * self.nkb * COMPLEX_FP64_BYTES
            psi_traffic = num_tiles_nkb * (self.npw * self.m * COMPLEX_FP64_BYTES)
            output_traffic = self.nkb * self.m * COMPLEX_FP64_BYTES
            
        elif dataflow.name == 'output_stationary':
            beta_traffic = num_tiles_m * (self.npw * self.nkb * COMPLEX_FP64_BYTES)
            psi_traffic = num_tiles_nkb * (self.npw * self.m * COMPLEX_FP64_BYTES)
            output_traffic = self.nkb * self.m * COMPLEX_FP64_BYTES
            
        else:
            beta_traffic = num_tiles_m * (self.npw * self.nkb * COMPLEX_FP64_BYTES)
            psi_traffic = num_tiles_nkb * (self.npw * self.m * COMPLEX_FP64_BYTES)
            output_traffic = num_tiles_npw * (self.nkb * self.m * COMPLEX_FP64_BYTES)
        
        return int(beta_traffic + psi_traffic + output_traffic)
    
    def check_buffer_feasibility(self, tile: TileConfig, buffer: BufferAllocation) -> tuple[bool, str]:
        """Check if tile fits in buffer hierarchy"""
        beta_tile_size = tile.tile_npw * tile.tile_nkb * COMPLEX_FP64_BYTES
        psi_tile_size = tile.tile_npw * tile.tile_m * COMPLEX_FP64_BYTES
        output_tile_size = tile.tile_nkb * tile.tile_m * COMPLEX_FP64_BYTES
        
        l1_required = output_tile_size
        l2_required = psi_tile_size
        l3_required = beta_tile_size
        
        l1_available = buffer.l1_size_kb * 1024
        l2_available = buffer.l2_size_kb * 1024
        l3_available = buffer.l3_size_kb * 1024
        
        if l1_required > l1_available:
            return False, f"L1 overflow: need {l1_required/1024:.1f}KB, have {buffer.l1_size_kb}KB"
        if l2_required > l2_available:
            return False, f"L2 overflow: need {l2_required/1024:.1f}KB, have {buffer.l2_size_kb}KB"
        if l3_required > l3_available:
            return False, f"L3 overflow: need {l3_required/1024:.1f}KB, have {buffer.l3_size_kb}KB"
        
        return True, "Feasible"
    
    def estimate_utilization(self, tile: TileConfig, loop_order: LoopOrdering) -> float:
        """Estimate compute utilization based on tile size and loop order"""
        tile_ops = tile.tile_npw * tile.tile_nkb * tile.tile_m
        max_parallel = min(tile_ops, self.pe_count)
        
        edge_penalty = 1.0
        if self.npw % tile.tile_npw != 0:
            edge_penalty *= 0.9
        if self.nkb % tile.tile_nkb != 0:
            edge_penalty *= 0.9
        if self.m % tile.tile_m != 0:
            edge_penalty *= 0.9
        
        loop_efficiency = 1.0
        if loop_order.inner == 'npw':
            loop_efficiency *= 0.95
        elif loop_order.inner == 'm':
            loop_efficiency *= 0.98
        
        utilization = (max_parallel / self.pe_count) * edge_penalty * loop_efficiency
        return min(utilization, 1.0)
    
    def analyze_mapping(self, config: MappingConfig) -> MappingResult:
        """Analyze a complete mapping configuration"""
        feasible, reason = self.check_buffer_feasibility(config.tile, config.buffer)
        
        if not feasible:
            return MappingResult(
                config=config,
                metrics=PerformanceMetrics(
                    compute_utilization=0.0,
                    memory_utilization=0.0,
                    arithmetic_intensity=0.0,
                    peak_flops=self.peak_flops,
                    achieved_flops=0.0,
                    peak_bandwidth_gbs=self.peak_bandwidth_gbs,
                    achieved_bandwidth_gbs=0.0,
                    bottleneck='infeasible',
                    roofline_position='infeasible'
                ),
                feasible=False,
                reason=reason
            )
        
        compute_ops = self.estimate_compute_ops(config.tile)
        memory_traffic = self.estimate_memory_traffic(config.tile, config.dataflow)
        arithmetic_intensity = compute_ops / memory_traffic if memory_traffic > 0 else 0
        
        compute_util = self.estimate_utilization(config.tile, config.loop_order)
        achieved_flops = self.peak_flops * compute_util
        
        compute_time = compute_ops / achieved_flops if achieved_flops > 0 else float('inf')
        memory_time = memory_traffic / (self.peak_bandwidth_gbs * 1e9) if self.peak_bandwidth_gbs > 0 else float('inf')
        
        if compute_time > memory_time:
            bottleneck = 'compute_bound'
            achieved_bandwidth = memory_traffic / compute_time / 1e9
            memory_util = achieved_bandwidth / self.peak_bandwidth_gbs
        else:
            bottleneck = 'memory_bound'
            achieved_bandwidth = self.peak_bandwidth_gbs
            memory_util = 1.0
            achieved_flops = compute_ops / memory_time
            compute_util = achieved_flops / self.peak_flops
        
        ridge_point = self.peak_flops / (self.peak_bandwidth_gbs * 1e9)
        if arithmetic_intensity > ridge_point:
            roofline_position = 'compute_bound_region'
        else:
            roofline_position = 'memory_bound_region'
        
        metrics = PerformanceMetrics(
            compute_utilization=compute_util,
            memory_utilization=memory_util,
            arithmetic_intensity=arithmetic_intensity,
            peak_flops=self.peak_flops,
            achieved_flops=achieved_flops,
            peak_bandwidth_gbs=self.peak_bandwidth_gbs,
            achieved_bandwidth_gbs=achieved_bandwidth,
            bottleneck=bottleneck,
            roofline_position=roofline_position
        )
        
        return MappingResult(
            config=config,
            metrics=metrics,
            feasible=True,
            reason='Feasible'
        )


def generate_tile_configs(npw: int, nkb: int, m: int) -> list[TileConfig]:
    """Generate candidate tile configurations"""
    configs = []
    
    tile_npw_options = [128, 256, 512, min(1024, npw)]
    tile_nkb_options = [16, 32, 64, min(144, nkb)]
    tile_m_options = [4, 8, 16, min(32, m)]
    
    for tnpw, tnkb, tm in product(tile_npw_options, tile_nkb_options, tile_m_options):
        if tnpw <= npw and tnkb <= nkb and tm <= m:
            configs.append(TileConfig(tnpw, tnkb, tm))
    
    return configs


def generate_loop_orderings() -> list[LoopOrdering]:
    """Generate all loop orderings"""
    orderings = []
    dims = ['npw', 'nkb', 'm']
    
    for perm in permutations(dims):
        orderings.append(LoopOrdering(outer=perm[0], middle=perm[1], inner=perm[2]))
    
    return orderings


def generate_dataflow_strategies() -> list[DataflowStrategy]:
    """Generate dataflow strategies"""
    return [
        DataflowStrategy(
            name='weight_stationary',
            stationary_operand='beta',
            streaming_operands=['psi'],
            accumulation_operand='output'
        ),
        DataflowStrategy(
            name='output_stationary',
            stationary_operand='output',
            streaming_operands=['beta', 'psi'],
            accumulation_operand='output'
        ),
        DataflowStrategy(
            name='row_stationary',
            stationary_operand='none',
            streaming_operands=['beta', 'psi'],
            accumulation_operand='output'
        ),
    ]


def generate_buffer_configs() -> list[BufferAllocation]:
    """Generate buffer configurations"""
    return [
        BufferAllocation(l1_size_kb=64, l2_size_kb=512, l3_size_kb=2048),
        BufferAllocation(l1_size_kb=128, l2_size_kb=1024, l3_size_kb=4096),
        BufferAllocation(l1_size_kb=256, l2_size_kb=2048, l3_size_kb=8192),
    ]


def run_dse_sweep(npw: int, nkb: int, m: int, output_dir: Path):
    """Run complete DSE sweep for a kernel"""
    
    print(f"Running Kernel Mapping DSE for: npw={npw}, nkb={nkb}, m={m}")
    print()
    
    mapper = ProjectorGEMMMapper(npw, nkb, m)
    
    tile_configs = generate_tile_configs(npw, nkb, m)
    loop_orderings = generate_loop_orderings()
    dataflow_strategies = generate_dataflow_strategies()
    buffer_configs = generate_buffer_configs()
    
    print(f"Design space size:")
    print(f"  Tile configs: {len(tile_configs)}")
    print(f"  Loop orderings: {len(loop_orderings)}")
    print(f"  Dataflow strategies: {len(dataflow_strategies)}")
    print(f"  Buffer configs: {len(buffer_configs)}")
    print(f"  Total configurations: {len(tile_configs) * len(loop_orderings) * len(dataflow_strategies) * len(buffer_configs)}")
    print()
    
    results = []
    feasible_count = 0
    
    for tile in tile_configs:
        for loop in loop_orderings:
            for dataflow in dataflow_strategies:
                for buffer in buffer_configs:
                    config = MappingConfig(tile, loop, dataflow, buffer)
                    result = mapper.analyze_mapping(config)
                    results.append(result)
                    
                    if result.feasible:
                        feasible_count += 1
    
    print(f"Analysis complete:")
    print(f"  Total configurations: {len(results)}")
    print(f"  Feasible configurations: {feasible_count}")
    print(f"  Infeasible configurations: {len(results) - feasible_count}")
    print()
    
    feasible_results = [r for r in results if r.feasible]
    
    if feasible_results:
        best_compute_util = max(feasible_results, key=lambda r: r.metrics.compute_utilization)
        best_ai = max(feasible_results, key=lambda r: r.metrics.arithmetic_intensity)
        
        print("Best configurations:")
        print(f"  Best compute utilization: {best_compute_util.metrics.compute_utilization:.2%}")
        print(f"    Tile: npw={best_compute_util.config.tile.tile_npw}, nkb={best_compute_util.config.tile.tile_nkb}, m={best_compute_util.config.tile.tile_m}")
        print(f"    Loop: {best_compute_util.config.loop_order.to_tuple()}")
        print(f"    Dataflow: {best_compute_util.config.dataflow.name}")
        print()
        print(f"  Best arithmetic intensity: {best_ai.metrics.arithmetic_intensity:.2f} FLOPs/Byte")
        print(f"    Tile: npw={best_ai.config.tile.tile_npw}, nkb={best_ai.config.tile.tile_nkb}, m={best_ai.config.tile.tile_m}")
        print(f"    Dataflow: {best_ai.config.dataflow.name}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_data = {
        'kernel_params': {'npw': npw, 'nkb': nkb, 'm': m},
        'design_space': {
            'tile_configs': len(tile_configs),
            'loop_orderings': len(loop_orderings),
            'dataflow_strategies': len(dataflow_strategies),
            'buffer_configs': len(buffer_configs),
            'total_configs': len(results),
        },
        'results_summary': {
            'total': len(results),
            'feasible': feasible_count,
            'infeasible': len(results) - feasible_count,
        },
        'best_configs': {
            'best_compute_util': asdict(best_compute_util) if feasible_results else None,
            'best_ai': asdict(best_ai) if feasible_results else None,
        },
        'all_results': [asdict(r) for r in results[:100]],
    }
    
    output_file = output_dir / f'kernel_mapping_dse_npw{npw}_nkb{nkb}_m{m}.json'
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nResults saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Step 2: Kernel Mapping Layer DSE')
    parser.add_argument('--npw', type=int, required=True, help='Number of plane waves')
    parser.add_argument('--nkb', type=int, required=True, help='Number of projectors')
    parser.add_argument('--m', type=int, required=True, help='Block size')
    parser.add_argument('--output-dir', type=Path, default=Path('/tmp/qe_dse_step2'), help='Output directory')
    args = parser.parse_args()
    
    run_dse_sweep(args.npw, args.nkb, args.m, args.output_dir)


if __name__ == '__main__':
    main()
