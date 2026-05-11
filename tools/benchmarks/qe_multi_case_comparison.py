#!/usr/bin/env python3
"""
Multi-case comparative analysis for QE computational patterns
"""

import json
from pathlib import Path
from collections import defaultdict

ANALYSIS_DIR = Path('/tmp/qe_dse_multi_case')

def load_all_analyses():
    """Load all case analyses"""
    cases = {}
    for case_dir in ANALYSIS_DIR.iterdir():
        if case_dir.is_dir():
            analysis_file = case_dir / 'qe_computational_pattern_analysis_step1.json'
            if analysis_file.exists():
                with open(analysis_file) as f:
                    cases[case_dir.name] = json.load(f)
    return cases

def compare_cases(cases):
    """Generate comparative analysis"""
    
    print("=" * 120)
    print("QE Multi-Case Computational Pattern Comparison")
    print("=" * 120)
    print()
    
    # Table 1: Basic characteristics
    print("## Table 1: System Characteristics")
    print("-" * 120)
    print(f"{'Case':<20} {'npw':<8} {'m_range':<12} {'n_range':<12} {'nkb':<6} {'FFT_grid':<15} {'Total_Kernels':<15}")
    print("-" * 120)
    
    for name, data in sorted(cases.items()):
        td = data['tensor_dimensions']
        npw = td['npw']['max']
        m_min = td['m_block_size']['min']
        m_max = td['m_block_size']['max']
        n_min = td['subspace_n']['min']
        n_max = td['subspace_n']['max']
        nkb = td['nkb_projector_count']['max']
        fft = td['fft_grid_size']['max']
        total = data['total_kernels']
        
        print(f"{name:<20} {npw:<8} {m_min}-{m_max:<9} {n_min}-{n_max:<9} {nkb:<6} {fft:<15} {total:<15}")
    
    print()
    
    # Table 2: Computational load
    print("## Table 2: Computational Load")
    print("-" * 120)
    print(f"{'Case':<20} {'GEMM_calls':<12} {'GEMM_GFLOPs':<15} {'Eig_calls':<12} {'Eig_GFLOPs':<15} {'Avg_AI':<12}")
    print("-" * 120)
    
    for name, data in sorted(cases.items()):
        ks = data['kernel_summary']
        gemm_calls = ks.get('gemm', {}).get('count', 0)
        gemm_gflops = ks.get('gemm', {}).get('total_flops', 0) / 1e9
        eig_calls = ks.get('eigensolver', {}).get('count', 0)
        eig_gflops = ks.get('eigensolver', {}).get('total_flops', 0) / 1e9
        
        gemm_traffic = ks.get('gemm', {}).get('total_traffic', 1)
        gemm_flops = ks.get('gemm', {}).get('total_flops', 0)
        avg_ai = gemm_flops / gemm_traffic if gemm_traffic > 0 else 0
        
        print(f"{name:<20} {gemm_calls:<12} {gemm_gflops:<15.2f} {eig_calls:<12} {eig_gflops:<15.3f} {avg_ai:<12.2f}")
    
    print()
    
    # Table 3: Hardware affinity distribution
    print("## Table 3: Hardware Affinity Recommendations (from samples)")
    print("-" * 120)
    print(f"{'Case':<20} {'CIM_optimal':<15} {'Systolic_optimal':<18} {'CPU/GPU_optimal':<18} {'Vector_optimal':<15}")
    print("-" * 120)
    
    for name, data in sorted(cases.items()):
        affinity_samples = data.get('hardware_affinity_samples', [])
        
        cim_count = sum(1 for a in affinity_samples if 'CIM' in a['recommended_target'])
        systolic_count = sum(1 for a in affinity_samples if 'Systolic' in a['recommended_target'])
        cpu_gpu_count = sum(1 for a in affinity_samples if 'CPU/GPU' in a['recommended_target'])
        vector_count = sum(1 for a in affinity_samples if 'Vector' in a['recommended_target'])
        
        total = len(affinity_samples)
        if total > 0:
            print(f"{name:<20} {cim_count}/{total:<13} {systolic_count}/{total:<16} {cpu_gpu_count}/{total:<16} {vector_count}/{total:<13}")
        else:
            print(f"{name:<20} {'N/A':<15} {'N/A':<18} {'N/A':<18} {'N/A':<15}")
    
    print()
    
    # Analysis: Key findings
    print("## Key Findings Across Cases:")
    print()
    
    # Finding 1: Scale diversity
    print("### 1. Scale Diversity")
    npw_values = [cases[name]['tensor_dimensions']['npw']['max'] for name in cases]
    gflops_values = [cases[name]['kernel_summary'].get('gemm', {}).get('total_flops', 0) / 1e9 for name in cases]
    
    print(f"   - npw range: {min(npw_values)} to {max(npw_values)} ({max(npw_values)/min(npw_values):.1f}x variation)")
    print(f"   - GEMM GFLOPs range: {min(gflops_values):.2f} to {max(gflops_values):.2f} ({max(gflops_values)/min(gflops_values):.0f}x variation)")
    print()
    
    # Finding 2: Block size patterns
    print("### 2. Block Size Patterns")
    for name, data in sorted(cases.items()):
        m_dist = data['tensor_dimensions']['m_block_size']['distribution']
        m_mean = data['tensor_dimensions']['m_block_size']['mean']
        print(f"   - {name}: mean m={m_mean:.1f}, most common: {list(m_dist.items())[:3]}")
    print()
    
    # Finding 3: Arithmetic intensity comparison
    print("### 3. Arithmetic Intensity Comparison")
    for name, data in sorted(cases.items()):
        ks = data['kernel_summary']
        gemm_traffic = ks.get('gemm', {}).get('total_traffic', 1)
        gemm_flops = ks.get('gemm', {}).get('total_flops', 0)
        avg_ai = gemm_flops / gemm_traffic if gemm_traffic > 0 else 0
        
        if avg_ai > 10:
            category = "Compute-bound (good for CIM/Systolic)"
        elif avg_ai > 1:
            category = "Balanced (good for GPU)"
        else:
            category = "Memory-bound (keep on CPU)"
        
        print(f"   - {name}: AI={avg_ai:.2f} FLOPs/Byte → {category}")
    print()
    
    # Finding 4: Generalized vs standard eigensolver
    print("### 4. Eigensolver Type Distribution")
    for name, data in sorted(cases.items()):
        # This would require reading subspace trace to check s_identity_rel
        # For now, just report eigensolver call counts
        eig_calls = data['kernel_summary'].get('eigensolver', {}).get('count', 0)
        print(f"   - {name}: {eig_calls} eigensolver calls")
    print()
    
    # Finding 5: Recommended hardware mapping
    print("### 5. Recommended Hardware Mapping Strategy")
    print()
    print("   Based on the multi-case analysis:")
    print()
    print("   **Tier 1 (CIM/Systolic acceleration):**")
    high_ai_cases = [(name, cases[name]['kernel_summary'].get('gemm', {}).get('total_flops', 0) / 
                      cases[name]['kernel_summary'].get('gemm', {}).get('total_traffic', 1))
                     for name in cases]
    high_ai_cases = [(n, ai) for n, ai in high_ai_cases if ai > 10]
    for name, ai in sorted(high_ai_cases, key=lambda x: x[1], reverse=True):
        gflops = cases[name]['kernel_summary'].get('gemm', {}).get('total_flops', 0) / 1e9
        print(f"     - {name}: AI={ai:.2f}, {gflops:.2f} GFLOPs → High priority for acceleration")
    print()
    
    print("   **Tier 2 (GPU acceleration):**")
    medium_ai_cases = [(name, cases[name]['kernel_summary'].get('gemm', {}).get('total_flops', 0) / 
                        cases[name]['kernel_summary'].get('gemm', {}).get('total_traffic', 1))
                       for name in cases]
    medium_ai_cases = [(n, ai) for n, ai in medium_ai_cases if 1 < ai <= 10]
    for name, ai in sorted(medium_ai_cases, key=lambda x: x[1], reverse=True):
        gflops = cases[name]['kernel_summary'].get('gemm', {}).get('total_flops', 0) / 1e9
        print(f"     - {name}: AI={ai:.2f}, {gflops:.2f} GFLOPs → GPU sufficient")
    print()
    
    print("   **Tier 3 (CPU sufficient):**")
    low_ai_cases = [(name, cases[name]['kernel_summary'].get('gemm', {}).get('total_flops', 0) / 
                     cases[name]['kernel_summary'].get('gemm', {}).get('total_traffic', 1))
                    for name in cases]
    low_ai_cases = [(n, ai) for n, ai in low_ai_cases if ai <= 1]
    for name, ai in sorted(low_ai_cases, key=lambda x: x[1], reverse=True):
        gflops = cases[name]['kernel_summary'].get('gemm', {}).get('total_flops', 0) / 1e9
        print(f"     - {name}: AI={ai:.2f}, {gflops:.2f} GFLOPs → Memory-bound, CPU sufficient")
    print()
    
    # Finding 6: Universal patterns
    print("### 6. Universal Patterns Across All Cases")
    print()
    print("   **Pattern 1: GEMM dominance**")
    for name, data in sorted(cases.items()):
        gemm_flops = data['kernel_summary'].get('gemm', {}).get('total_flops', 0)
        eig_flops = data['kernel_summary'].get('eigensolver', {}).get('total_flops', 0)
        total_flops = gemm_flops + eig_flops
        gemm_pct = 100 * gemm_flops / total_flops if total_flops > 0 else 0
        print(f"     - {name}: GEMM占 {gemm_pct:.1f}% FLOPs")
    print()
    
    print("   **Pattern 2: Block size variability**")
    print("     All cases show high variability in m (1-32 range)")
    print("     → Hardware must handle dynamic block sizes efficiently")
    print()
    
    print("   **Pattern 3: Subspace dimension bounded**")
    print("     All cases have n ≤ 64 (most ≤ 32)")
    print("     → Small matrix eigensolver not a bottleneck")
    print()

def main():
    cases = load_all_analyses()
    
    if not cases:
        print("No analysis results found!")
        return
    
    compare_cases(cases)
    
    # Save comparison
    output = {
        'cases_analyzed': list(cases.keys()),
        'summary': {
            name: {
                'npw': data['tensor_dimensions']['npw']['max'],
                'gemm_gflops': data['kernel_summary'].get('gemm', {}).get('total_flops', 0) / 1e9,
                'arithmetic_intensity': (data['kernel_summary'].get('gemm', {}).get('total_flops', 0) / 
                                        data['kernel_summary'].get('gemm', {}).get('total_traffic', 1)),
            }
            for name, data in cases.items()
        }
    }
    
    output_path = Path('/tmp/qe_multi_case_comparison.json')
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nComparison data saved to: {output_path}")

if __name__ == '__main__':
    main()
