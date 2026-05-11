#!/usr/bin/env python3
"""
Main script for running architecture comparison experiments
"""

import json
import argparse
import sys
from pathlib import Path
from typing import Any
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.architecture_comparison.comparison_framework import (
    WorkloadCharacteristics,
    compare_architectures,
)


def plot_comparison(results: dict[str, Any], output_dir: Path) -> None:
    """Generate comparison plots"""
    
    arch_names = list(results.keys())
    
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    fig.suptitle('Architecture Comparison', fontsize=16, fontweight='bold')
    
    speedups = [results[arch]['performance']['effective_gflops'] / 
                results['4cluster']['performance']['effective_gflops'] 
                for arch in arch_names]
    axes[0, 0].bar(arch_names, speedups, color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    axes[0, 0].set_ylabel('Speedup vs 4-Cluster')
    axes[0, 0].set_title('Performance Speedup')
    axes[0, 0].axhline(y=1.0, color='r', linestyle='--', label='Baseline')
    axes[0, 0].legend()
    axes[0, 0].grid(axis='y', alpha=0.3)
    
    utilizations = [results[arch]['performance']['utilization'] * 100 
                   for arch in arch_names]
    axes[0, 1].bar(arch_names, utilizations, color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    axes[0, 1].set_ylabel('Utilization (%)')
    axes[0, 1].set_title('Compute Utilization')
    axes[0, 1].axhline(y=60, color='orange', linestyle='--', label='Target (60%)')
    axes[0, 1].legend()
    axes[0, 1].grid(axis='y', alpha=0.3)
    
    energies = [results[arch]['energy']['total_energy_j'] / 1e6 
               for arch in arch_names]
    axes[0, 2].bar(arch_names, energies, color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    axes[0, 2].set_ylabel('Energy (MJ)')
    axes[0, 2].set_title('Total Energy Consumption')
    axes[0, 2].grid(axis='y', alpha=0.3)
    
    efficiencies = [results[arch]['energy']['energy_efficiency_gflops_w'] 
                   for arch in arch_names]
    axes[1, 0].bar(arch_names, efficiencies, color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    axes[1, 0].set_ylabel('GFLOPS/W')
    axes[1, 0].set_title('Energy Efficiency')
    axes[1, 0].grid(axis='y', alpha=0.3)
    
    areas = [results[arch]['area']['relative_area'] for arch in arch_names]
    axes[1, 1].bar(arch_names, areas, color=['#1f77b4', '#ff7f0e', '#2ca02c'])
    axes[1, 1].set_ylabel('Relative Area')
    axes[1, 1].set_title('Area Cost')
    axes[1, 1].axhline(y=1.0, color='r', linestyle='--', label='Baseline')
    axes[1, 1].legend()
    axes[1, 1].grid(axis='y', alpha=0.3)
    
    x = [results[arch]['performance']['effective_gflops'] for arch in arch_names]
    y = [results[arch]['energy']['energy_efficiency_gflops_w'] for arch in arch_names]
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c']
    axes[1, 2].scatter(x, y, s=200, c=colors, alpha=0.6)
    for i, arch in enumerate(arch_names):
        axes[1, 2].annotate(arch, (x[i], y[i]), fontsize=9, ha='center')
    axes[1, 2].set_xlabel('Effective GFLOPS')
    axes[1, 2].set_ylabel('Energy Efficiency (GFLOPS/W)')
    axes[1, 2].set_title('Performance vs Energy Efficiency')
    axes[1, 2].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'architecture_comparison.png', dpi=300, bbox_inches='tight')
    print(f"Saved plot to {output_dir / 'architecture_comparison.png'}")


def generate_report(results: dict[str, Any], output_dir: Path) -> None:
    """Generate markdown report"""
    
    report = []
    report.append("# Architecture Comparison Report\n")
    report.append("## Summary\n")
    
    report.append("| Architecture | Speedup | Utilization | Energy (MJ) | Efficiency (GFLOPS/W) | Area |\n")
    report.append("|--------------|---------|-------------|-------------|----------------------|------|\n")
    
    baseline_gflops = results['4cluster']['performance']['effective_gflops']
    
    for arch_name, data in results.items():
        speedup = data['performance']['effective_gflops'] / baseline_gflops
        util = data['performance']['utilization'] * 100
        energy = data['energy']['total_energy_j'] / 1e6
        efficiency = data['energy']['energy_efficiency_gflops_w']
        area = data['area']['relative_area']
        
        report.append(f"| {arch_name} | {speedup:.2f}x | {util:.1f}% | {energy:.2f} | {efficiency:.2f} | {area:.2f}x |\n")
    
    report.append("\n## Detailed Analysis\n")
    
    for arch_name, data in results.items():
        report.append(f"\n### {data['config'].name}\n")
        report.append(f"**Configuration:**\n")
        report.append(f"- Peak GFLOPS: {data['config'].peak_gflops}\n")
        report.append(f"- Compute Units: {data['config'].n_compute_units}\n")
        report.append(f"- Memory: L1={data['config'].l1_size_kb}KB, L2={data['config'].l2_size_kb}KB\n")
        report.append(f"- Off-chip BW: {data['config'].off_chip_bw_gbs} GB/s\n")
        report.append(f"- Interconnect: {data['config'].interconnect_type}\n")
        
        report.append(f"\n**Performance:**\n")
        report.append(f"- Total Time: {data['performance']['total_time_s']:.4f} s\n")
        report.append(f"- Effective GFLOPS: {data['performance']['effective_gflops']:.2f}\n")
        report.append(f"- Utilization: {data['performance']['utilization']*100:.1f}%\n")
        
        report.append(f"\n**Energy:**\n")
        report.append(f"- Total Energy: {data['energy']['total_energy_j']/1e6:.2f} MJ\n")
        report.append(f"- Energy Efficiency: {data['energy']['energy_efficiency_gflops_w']:.2f} GFLOPS/W\n")
        
        report.append(f"\n**Roofline Analysis:**\n")
        report.append(f"- Achievable GFLOPS: {data['roofline_gflops']:.2f}\n")
        report.append(f"- Bottleneck: {data['bottleneck']}\n")
    
    report.append("\n## Recommendations\n")
    
    best_perf = max(results.items(), key=lambda x: x[1]['performance']['effective_gflops'])
    best_energy = max(results.items(), key=lambda x: x[1]['energy']['energy_efficiency_gflops_w'])
    best_area = min(results.items(), key=lambda x: x[1]['area']['relative_area'])
    
    report.append(f"- **Best Performance**: {best_perf[0]} ({best_perf[1]['performance']['effective_gflops']:.2f} GFLOPS)\n")
    report.append(f"- **Best Energy Efficiency**: {best_energy[0]} ({best_energy[1]['energy']['energy_efficiency_gflops_w']:.2f} GFLOPS/W)\n")
    report.append(f"- **Smallest Area**: {best_area[0]} ({best_area[1]['area']['relative_area']:.2f}x)\n")
    
    report_path = output_dir / 'comparison_report.md'
    with open(report_path, 'w') as f:
        f.writelines(report)
    
    print(f"Saved report to {report_path}")


def main():
    parser = argparse.ArgumentParser(description='Run architecture comparison')
    parser.add_argument('--output-dir', type=str, default='results',
                       help='Output directory for results')
    parser.add_argument('--workload', type=str, default='si8',
                       choices=['si4', 'si8', 'graphene'],
                       help='Workload to use')
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)
    
    workload = WorkloadCharacteristics()
    
    print("Running architecture comparison...")
    results = compare_architectures(workload)
    
    results_json = output_dir / 'comparison_results.json'
    with open(results_json, 'w') as f:
        serializable_results = {}
        for arch_name, data in results.items():
            serializable_results[arch_name] = {
                'performance': data['performance'],
                'energy': data['energy'],
                'area': data['area'],
                'roofline_gflops': data['roofline_gflops'],
                'bottleneck': data['bottleneck']
            }
        json.dump(serializable_results, f, indent=2)
    
    print(f"Saved results to {results_json}")
    
    plot_comparison(results, output_dir)
    
    generate_report(results, output_dir)
    
    print("\nComparison complete!")
    print(f"Results saved to {output_dir}/")


if __name__ == '__main__':
    main()
