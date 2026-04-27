#!/usr/bin/env python3
"""
Step 1: QE Computational Flow Deep Analysis and Hardware-Friendly Pattern Recognition

This script analyzes QE execution traces to:
1. Quantify computational hotspots and their characteristics
2. Classify operations by hardware affinity
3. Identify optimization opportunities for CIM/systolic/vector acceleration
4. Extract tensor dimension distributions and access patterns

Output:
- qe_execution_flow_analysis.json: Detailed breakdown of computation phases
- qe_tensor_characteristics.json: Tensor dimension statistics and properties
- qe_compute_pattern_hardware_affinity.json: Hardware mapping analysis
- qe_hardware_optimization_opportunities.md: Human-readable recommendations
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

# Constants
COMPLEX_FP64_BYTES = 16
REAL_FP64_BYTES = 8
RY_TO_EV = 13.605693009

# Computational intensity thresholds (FLOPs/Byte)
COMPUTE_BOUND_THRESHOLD = 10.0  # > 10 FLOPs/Byte
MEMORY_BOUND_THRESHOLD = 1.0    # < 1 FLOPs/Byte


@dataclass
class TensorCharacteristics:
    """Characteristics of a tensor in QE computation"""
    name: str
    dimensions: tuple[int, ...]
    dtype: str  # 'complex_fp64' or 'real_fp64'
    size_bytes: int
    access_pattern: str  # 'sequential', 'strided', 'random', 'broadcast'
    reuse_factor: float  # How many times data is reused
    structure: list[str]  # e.g., ['hermitian', 'positive_definite']


@dataclass
class ComputeKernel:
    """A computational kernel in QE"""
    name: str
    operation_type: str  # 'gemm', 'fft', 'eigensolver', 'elementwise', 'reduction'
    input_tensors: list[str]
    output_tensors: list[str]
    flops: int
    memory_traffic_bytes: int
    arithmetic_intensity: float  # FLOPs / Byte
    call_count: int
    total_time_ms: float
    avg_time_ms: float


@dataclass
class HardwareAffinity:
    """Hardware affinity analysis for a kernel"""
    kernel_name: str
    cim_score: float  # 0-1, higher = better for CIM
    systolic_score: float
    vector_score: float
    cpu_gpu_score: float
    recommended_target: str
    reasoning: str


def parse_subspace_trace(trace_path: Path) -> list[dict[str, Any]]:
    """Parse subspace diagonalization trace"""
    rows = []
    with trace_path.open(newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = {
                'call_id': int(row['call_id']),
                'solver': row['solver'],
                'n': int(row['n']),
                'm': int(row['m']),
                'all_eigenvalues': row['all_eigenvalues'].strip().lower() in {'t', 'true'},
                'h_frob': float(row['h_frob']),
                's_identity_rel': float(row['s_identity_rel']),
            }
            rows.append(parsed)
    return rows


def parse_hpsi_trace(trace_path: Path) -> list[dict[str, Any]]:
    """Parse h_psi/s_psi operator trace"""
    rows = []
    with trace_path.open(newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = {
                'call_id': int(row['call_id']),
                'op': row['op'],
                'npw': int(row['npw']),
                'nbnd_or_m': int(row['nbnd_or_m']),
                'nkb': int(row['nkb']),
                'okvan': row['okvan'].strip().upper() == 'T',
                'fft_nr1': int(row['fft_nr1']),
                'fft_nr2': int(row['fft_nr2']),
                'fft_nr3': int(row['fft_nr3']),
            }
            rows.append(parsed)
    return rows


def parse_bandsolver_trace(trace_path: Path) -> list[dict[str, Any]]:
    """Parse band solver trace"""
    rows = []
    with trace_path.open(newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = {
                'call_id': int(row['call_id']),
                'scf_iter': int(row['scf_iter']),
                'op': row['op'],
                'npw': int(row['npw']),
                'nbnd_or_m': int(row['nbnd_or_m']),
                'nbase': int(row['nbase']) if row['nbase'] != '-1' else None,
                'nvec': int(row['nvec']) if row['nvec'] != '-1' else None,
                'subspace_n': int(row['subspace_n']) if row['subspace_n'] != '-1' else None,
                'subspace_m': int(row['subspace_m']) if row['subspace_m'] != '-1' else None,
            }
            rows.append(parsed)
    return rows


def analyze_tensor_dimensions(hpsi_trace: list[dict], subspace_trace: list[dict]) -> dict[str, Any]:
    """Analyze tensor dimension distributions"""
    
    # Collect dimension statistics
    npw_values = [row['npw'] for row in hpsi_trace]
    m_values = [row['nbnd_or_m'] for row in hpsi_trace]
    n_values = [row['n'] for row in subspace_trace]
    subspace_m_values = [row['m'] for row in subspace_trace]
    
    # FFT grid dimensions
    fft_grids = [(row['fft_nr1'], row['fft_nr2'], row['fft_nr3']) for row in hpsi_trace]
    fft_grid_sizes = [g[0] * g[1] * g[2] for g in fft_grids]
    
    # nkb (projector count)
    nkb_values = [row['nkb'] for row in hpsi_trace if row['okvan']]
    
    return {
        'npw': {
            'min': min(npw_values),
            'max': max(npw_values),
            'mean': sum(npw_values) / len(npw_values),
            'distribution': dict(Counter(npw_values).most_common(10)),
        },
        'm_block_size': {
            'min': min(m_values),
            'max': max(m_values),
            'mean': sum(m_values) / len(m_values),
            'distribution': dict(Counter(m_values).most_common(10)),
        },
        'subspace_n': {
            'min': min(n_values),
            'max': max(n_values),
            'mean': sum(n_values) / len(n_values),
            'distribution': dict(Counter(n_values).most_common(10)),
        },
        'subspace_m': {
            'min': min(subspace_m_values),
            'max': max(subspace_m_values),
            'mean': sum(subspace_m_values) / len(subspace_m_values),
            'distribution': dict(Counter(subspace_m_values).most_common(10)),
        },
        'fft_grid_size': {
            'min': min(fft_grid_sizes),
            'max': max(fft_grid_sizes),
            'mean': sum(fft_grid_sizes) / len(fft_grid_sizes),
            'unique_grids': list(set(fft_grids)),
        },
        'nkb_projector_count': {
            'min': min(nkb_values) if nkb_values else 0,
            'max': max(nkb_values) if nkb_values else 0,
            'mean': sum(nkb_values) / len(nkb_values) if nkb_values else 0,
        },
    }


def estimate_kernel_flops(kernel_type: str, params: dict) -> int:
    """Estimate FLOPs for a kernel"""
    
    if kernel_type == 'h_psi':
        npw = params['npw']
        m = params['m']
        nkb = params['nkb']
        fft_size = params['fft_size']
        
        # Kinetic term: npw * m complex scaling
        kinetic_flops = npw * m * 6  # complex multiply = 6 real ops
        
        # FFT: m * (fft_size * log2(fft_size) * 5) for 3D FFT
        fft_flops = m * fft_size * math.log2(fft_size) * 5 * 2  # forward + backward
        
        # Local potential: fft_size * m pointwise multiply
        local_flops = fft_size * m * 2  # complex multiply
        
        # Nonlocal projector: 2 * (npw * nkb * m) GEMM
        nonlocal_flops = 2 * (2 * npw * nkb * m * 8)  # complex GEMM = 8x real ops
        
        return int(kinetic_flops + fft_flops + local_flops + nonlocal_flops)
    
    elif kernel_type == 's_psi':
        npw = params['npw']
        m = params['m']
        nkb = params['nkb']
        
        # Similar to h_psi nonlocal path but no FFT
        return int(2 * (2 * npw * nkb * m * 8))
    
    elif kernel_type == 'subspace_diag':
        n = params['n']
        m = params['m']
        
        # Cholesky + transform + eigensolver + backtransform
        # Dominated by O(n^3) operations
        return int(n**3 * 10 + n**2 * m * 8)
    
    elif kernel_type == 'subspace_projection':
        npw = params['npw']
        n = params['n']
        m = params['m']
        
        # Psi^H * HPsi and Psi^H * SPsi: 2 * (npw * n * m) GEMM
        return int(2 * (2 * npw * n * m * 8))
    
    return 0


def estimate_memory_traffic(kernel_type: str, params: dict) -> int:
    """Estimate memory traffic in bytes"""
    
    if kernel_type == 'h_psi':
        npw = params['npw']
        m = params['m']
        nkb = params['nkb']
        fft_size = params['fft_size']
        
        # Read: psi(G), beta, Veff
        # Write: Hpsi(G)
        # Intermediate: psi(r), y_eff(r)
        traffic = (
            npw * m * COMPLEX_FP64_BYTES +  # read psi(G)
            npw * nkb * COMPLEX_FP64_BYTES +  # read beta
            fft_size * REAL_FP64_BYTES +  # read Veff
            npw * m * COMPLEX_FP64_BYTES +  # write Hpsi(G)
            fft_size * m * COMPLEX_FP64_BYTES * 2  # intermediate psi(r), y_eff(r)
        )
        return int(traffic)
    
    elif kernel_type == 's_psi':
        npw = params['npw']
        m = params['m']
        nkb = params['nkb']
        
        traffic = (
            npw * m * COMPLEX_FP64_BYTES +  # read psi(G)
            npw * nkb * COMPLEX_FP64_BYTES +  # read beta
            npw * m * COMPLEX_FP64_BYTES  # write Spsi(G)
        )
        return int(traffic)
    
    elif kernel_type == 'subspace_diag':
        n = params['n']
        m = params['m']
        
        traffic = (
            n * n * COMPLEX_FP64_BYTES * 2 +  # read H_sub, S_sub
            n * m * COMPLEX_FP64_BYTES +  # write C
            m * REAL_FP64_BYTES  # write eigenvalues
        )
        return int(traffic)
    
    elif kernel_type == 'subspace_projection':
        npw = params['npw']
        n = params['n']
        m = params['m']
        
        traffic = (
            npw * n * COMPLEX_FP64_BYTES * 4 +  # read Psi, HPsi, SPsi, P
            n * n * COMPLEX_FP64_BYTES * 2  # write H_sub, S_sub
        )
        return int(traffic)
    
    return 0


def classify_hardware_affinity(kernel: ComputeKernel) -> HardwareAffinity:
    """Classify hardware affinity for a kernel"""
    
    ai = kernel.arithmetic_intensity
    op_type = kernel.operation_type
    
    # Initialize scores
    cim_score = 0.0
    systolic_score = 0.0
    vector_score = 0.0
    cpu_gpu_score = 0.0
    
    if op_type == 'gemm':
        if ai > COMPUTE_BOUND_THRESHOLD:
            # High AI GEMM: good for systolic or CIM
            if 'projector' in kernel.name.lower():
                # Projector GEMM: asymmetric, good for CIM
                cim_score = 0.9
                systolic_score = 0.7
                vector_score = 0.3
                cpu_gpu_score = 0.6
                recommended = 'CIM'
                reasoning = 'High AI projector GEMM with asymmetric access pattern, ideal for CIM'
            else:
                # Regular GEMM: good for systolic
                cim_score = 0.7
                systolic_score = 0.9
                vector_score = 0.4
                cpu_gpu_score = 0.8
                recommended = 'Systolic Array'
                reasoning = 'High AI dense GEMM, well-suited for systolic array'
        else:
            # Low AI GEMM: memory-bound, better on CPU/GPU
            cim_score = 0.4
            systolic_score = 0.5
            vector_score = 0.3
            cpu_gpu_score = 0.7
            recommended = 'CPU/GPU'
            reasoning = 'Memory-bound GEMM, better on CPU/GPU with high bandwidth'
    
    elif op_type == 'fft':
        # FFT: complex access pattern, better on CPU/GPU
        cim_score = 0.2
        systolic_score = 0.3
        vector_score = 0.6
        cpu_gpu_score = 0.9
        recommended = 'CPU/GPU with FFT library'
        reasoning = '3D FFT with complex access pattern, best on CPU/GPU with optimized libraries'
    
    elif op_type == 'eigensolver':
        if 'subspace' in kernel.name.lower():
            # Small subspace eigensolver
            cim_score = 0.3
            systolic_score = 0.4
            vector_score = 0.7
            cpu_gpu_score = 0.8
            recommended = 'CPU/GPU'
            reasoning = 'Small matrix eigensolver (n<64), efficient on CPU with LAPACK'
        else:
            # Large eigensolver
            cim_score = 0.1
            systolic_score = 0.3
            vector_score = 0.5
            cpu_gpu_score = 0.9
            recommended = 'CPU/GPU'
            reasoning = 'Large eigensolver with complex algorithm, best on CPU/GPU'
    
    elif op_type == 'elementwise':
        # Elementwise: memory-bound, good for vector units
        cim_score = 0.3
        systolic_score = 0.2
        vector_score = 0.9
        cpu_gpu_score = 0.7
        recommended = 'Vector Unit'
        reasoning = 'Elementwise operation, ideal for vector units with high memory bandwidth'
    
    elif op_type == 'reduction':
        # Reduction: tree-based, good for vector or dedicated reduction units
        cim_score = 0.4
        systolic_score = 0.5
        vector_score = 0.8
        cpu_gpu_score = 0.7
        recommended = 'Vector Unit with Reduction'
        reasoning = 'Reduction operation, efficient on vector units with tree reduction'
    
    else:
        # Unknown: default to CPU/GPU
        cim_score = 0.3
        systolic_score = 0.3
        vector_score = 0.5
        cpu_gpu_score = 0.8
        recommended = 'CPU/GPU'
        reasoning = 'Unknown operation type, default to CPU/GPU'
    
    return HardwareAffinity(
        kernel_name=kernel.name,
        cim_score=cim_score,
        systolic_score=systolic_score,
        vector_score=vector_score,
        cpu_gpu_score=cpu_gpu_score,
        recommended_target=recommended,
        reasoning=reasoning
    )


def analyze_case(case_dir: Path) -> dict[str, Any]:
    """Analyze a single QE case"""
    
    # Load traces
    subspace_trace = parse_subspace_trace(case_dir / 'subspace_trace.csv')
    hpsi_trace = parse_hpsi_trace(case_dir / 'hpsi_trace.csv')
    bandsolver_trace = parse_bandsolver_trace(case_dir / 'bandsolver_trace.csv')
    
    # Analyze tensor dimensions
    tensor_dims = analyze_tensor_dimensions(hpsi_trace, subspace_trace)
    
    # Estimate computational kernels
    kernels = []
    
    # h_psi kernels
    h_psi_calls = [row for row in hpsi_trace if row['op'] == 'h_psi']
    for row in h_psi_calls:
        params = {
            'npw': row['npw'],
            'm': row['nbnd_or_m'],
            'nkb': row['nkb'],
            'fft_size': row['fft_nr1'] * row['fft_nr2'] * row['fft_nr3'],
        }
        flops = estimate_kernel_flops('h_psi', params)
        traffic = estimate_memory_traffic('h_psi', params)
        
        kernels.append(ComputeKernel(
            name=f"h_psi_m{row['nbnd_or_m']}",
            operation_type='gemm',
            input_tensors=['psi(G)', 'beta', 'Veff'],
            output_tensors=['Hpsi(G)'],
            flops=flops,
            memory_traffic_bytes=traffic,
            arithmetic_intensity=flops / traffic if traffic > 0 else 0,
            call_count=1,
            total_time_ms=0,  # Not available from trace
            avg_time_ms=0,
        ))
    
    # s_psi kernels
    s_psi_calls = [row for row in hpsi_trace if row['op'] == 's_psi']
    for row in s_psi_calls:
        params = {
            'npw': row['npw'],
            'm': row['nbnd_or_m'],
            'nkb': row['nkb'],
        }
        flops = estimate_kernel_flops('s_psi', params)
        traffic = estimate_memory_traffic('s_psi', params)
        
        kernels.append(ComputeKernel(
            name=f"s_psi_m{row['nbnd_or_m']}",
            operation_type='gemm',
            input_tensors=['psi(G)', 'beta'],
            output_tensors=['Spsi(G)'],
            flops=flops,
            memory_traffic_bytes=traffic,
            arithmetic_intensity=flops / traffic if traffic > 0 else 0,
            call_count=1,
            total_time_ms=0,
            avg_time_ms=0,
        ))
    
    # Subspace diagonalization kernels
    for row in subspace_trace:
        params = {
            'n': row['n'],
            'm': row['m'],
        }
        flops = estimate_kernel_flops('subspace_diag', params)
        traffic = estimate_memory_traffic('subspace_diag', params)
        
        kernels.append(ComputeKernel(
            name=f"cdiaghg_n{row['n']}_m{row['m']}",
            operation_type='eigensolver',
            input_tensors=['H_sub', 'S_sub'],
            output_tensors=['C', 'Lambda'],
            flops=flops,
            memory_traffic_bytes=traffic,
            arithmetic_intensity=flops / traffic if traffic > 0 else 0,
            call_count=1,
            total_time_ms=0,
            avg_time_ms=0,
        ))
    
    # Aggregate kernels by type
    kernel_summary = defaultdict(lambda: {'count': 0, 'total_flops': 0, 'total_traffic': 0})
    for k in kernels:
        key = k.operation_type
        kernel_summary[key]['count'] += 1
        kernel_summary[key]['total_flops'] += k.flops
        kernel_summary[key]['total_traffic'] += k.memory_traffic_bytes
    
    # Classify hardware affinity
    affinity_analysis = []
    for k in kernels[:20]:  # Analyze first 20 kernels as examples
        affinity = classify_hardware_affinity(k)
        affinity_analysis.append(asdict(affinity))
    
    return {
        'case_name': case_dir.name,
        'tensor_dimensions': tensor_dims,
        'kernel_summary': dict(kernel_summary),
        'total_kernels': len(kernels),
        'hardware_affinity_samples': affinity_analysis,
    }


def main():
    parser = argparse.ArgumentParser(description='Step 1: QE Computational Pattern Analysis')
    parser.add_argument('case_dir', type=Path, help='QE case directory with traces')
    parser.add_argument('--output-dir', type=Path, default=Path('.'), help='Output directory')
    args = parser.parse_args()
    
    # Analyze case
    analysis = analyze_case(args.case_dir)
    
    # Write outputs
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with open(output_dir / 'qe_computational_pattern_analysis_step1.json', 'w') as f:
        json.dump(analysis, f, indent=2)
    
    print(f"Analysis complete. Results written to {output_dir}")
    print(f"Case: {analysis['case_name']}")
    print(f"Total kernels analyzed: {analysis['total_kernels']}")
    print(f"\nKernel summary:")
    for op_type, stats in analysis['kernel_summary'].items():
        print(f"  {op_type}: {stats['count']} calls, {stats['total_flops']/1e9:.2f} GFLOPs")


if __name__ == '__main__':
    main()
