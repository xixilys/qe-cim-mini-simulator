#!/usr/bin/env python3
"""
Multi-Workload DSE Analysis Script
Analyzes performance across different workloads and identifies robust designs.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import json

def load_results(results_dir: Path):
    """Load multi-workload DSE results."""
    df = pd.read_csv(results_dir / 'average_performance_v2.csv')
    return df

def analyze_workload_robustness(df: pd.DataFrame):
    """Analyze design robustness across workloads."""
    print("\n" + "="*80)
    print("📊 Workload Robustness Analysis")
    print("="*80)
    
    # Coefficient of variation (CV) = std / mean
    df['cv_time'] = df['std_time_s'] / df['avg_time_s']
    df['cv_energy'] = df['std_energy_j'] / df['avg_energy_j']
    
    # Worst-case penalty = max / avg
    df['worst_case_penalty'] = df['max_time_s'] / df['avg_time_s']
    
    print(f"\nCoefficient of Variation (Time):")
    print(f"  Mean: {df['cv_time'].mean():.3f}")
    print(f"  Min:  {df['cv_time'].min():.3f} (Trial {df['cv_time'].idxmin()})")
    print(f"  Max:  {df['cv_time'].max():.3f} (Trial {df['cv_time'].idxmax()})")
    
    print(f"\nWorst-Case Penalty:")
    print(f"  Mean: {df['worst_case_penalty'].mean():.3f}×")
    print(f"  Min:  {df['worst_case_penalty'].min():.3f}× (Trial {df['worst_case_penalty'].idxmin()})")
    print(f"  Max:  {df['worst_case_penalty'].max():.3f}× (Trial {df['worst_case_penalty'].idxmax()})")
    
    # Find most robust designs (low CV, low worst-case penalty)
    df['robustness_score'] = 1.0 / (df['cv_time'] * df['worst_case_penalty'])
    
    print(f"\n🏆 Top 5 Most Robust Designs:")
    top_robust = df.nsmallest(5, 'cv_time')
    for i, (idx, row) in enumerate(top_robust.iterrows(), 1):
        print(f"  {i}. Trial {int(row['trial_index']):2d}: CV={row['cv_time']:.3f}, "
              f"WCP={row['worst_case_penalty']:.2f}×, "
              f"PU={int(row['parallel_units'])}, PD={int(row['pipeline_depth'])}")
    
    return df

def analyze_parameter_impact(df: pd.DataFrame):
    """Analyze parameter impact on multi-workload performance."""
    print("\n" + "="*80)
    print("🔍 Parameter Impact Analysis")
    print("="*80)
    
    # Categorical parameters
    categorical_params = ['offload_strategy', 'dataflow_pattern', 'overlap_policy']
    
    for param in categorical_params:
        print(f"\n{param.upper()}:")
        grouped = df.groupby(param)['avg_time_s'].agg(['mean', 'std', 'count'])
        grouped = grouped.sort_values('mean')
        for strategy, row in grouped.iterrows():
            print(f"  {strategy:25s}: {row['mean']:.6e}s ± {row['std']:.6e}s (n={int(row['count'])})")
    
    # Numerical parameters
    numerical_params = ['parallel_units', 'pipeline_depth']
    
    for param in numerical_params:
        print(f"\n{param.upper()}:")
        grouped = df.groupby(param)['avg_time_s'].agg(['mean', 'std', 'count'])
        grouped = grouped.sort_values('mean')
        for value, row in grouped.iterrows():
            print(f"  {int(value):2d}: {row['mean']:.6e}s ± {row['std']:.6e}s (n={int(row['count'])})")

def create_visualizations(df: pd.DataFrame, output_dir: Path):
    """Create comprehensive visualizations."""
    print("\n" + "="*80)
    print("📈 Creating Visualizations")
    print("="*80)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Set style
    sns.set_style("whitegrid")
    plt.rcParams['figure.figsize'] = (12, 8)
    
    # 1. Pareto Frontier (Avg Time vs Avg Energy)
    fig, ax = plt.subplots(figsize=(10, 6))
    scatter = ax.scatter(df['avg_time_s']*1e6, df['avg_energy_j']*1e3, 
                        c=df['parallel_units'], cmap='viridis', 
                        s=100, alpha=0.6, edgecolors='black')
    
    # Highlight best design
    best_idx = df['avg_time_s'].idxmin()
    ax.scatter(df.loc[best_idx, 'avg_time_s']*1e6, 
              df.loc[best_idx, 'avg_energy_j']*1e3,
              color='red', s=300, marker='*', 
              edgecolors='black', linewidths=2, 
              label='Best Design', zorder=10)
    
    ax.set_xlabel('Average Time (μs)', fontsize=12)
    ax.set_ylabel('Average Energy (mJ)', fontsize=12)
    ax.set_title('Multi-Workload Pareto Frontier', fontsize=14, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('Parallel Units', fontsize=11)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'pareto_frontier_multi_workload.png', dpi=300, bbox_inches='tight')
    print(f"  ✓ Saved: pareto_frontier_multi_workload.png")
    plt.close()
    
    # 2. Robustness Analysis (CV vs Avg Time)
    fig, ax = plt.subplots(figsize=(10, 6))
    scatter = ax.scatter(df['avg_time_s']*1e6, df['cv_time'], 
                        c=df['parallel_units'], cmap='plasma', 
                        s=100, alpha=0.6, edgecolors='black')
    
    ax.set_xlabel('Average Time (μs)', fontsize=12)
    ax.set_ylabel('Coefficient of Variation (Time)', fontsize=12)
    ax.set_title('Design Robustness: Performance vs Variability', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('Parallel Units', fontsize=11)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'robustness_analysis.png', dpi=300, bbox_inches='tight')
    print(f"  ✓ Saved: robustness_analysis.png")
    plt.close()
    
    # 3. Worst-Case Penalty Distribution
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(df['worst_case_penalty'], bins=20, color='steelblue', 
            edgecolor='black', alpha=0.7)
    ax.axvline(df['worst_case_penalty'].mean(), color='red', 
               linestyle='--', linewidth=2, label=f'Mean: {df["worst_case_penalty"].mean():.2f}×')
    ax.set_xlabel('Worst-Case Penalty (Max/Avg)', fontsize=12)
    ax.set_ylabel('Frequency', fontsize=12)
    ax.set_title('Distribution of Worst-Case Performance Penalty', fontsize=14, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_dir / 'worst_case_penalty_dist.png', dpi=300, bbox_inches='tight')
    print(f"  ✓ Saved: worst_case_penalty_dist.png")
    plt.close()
    
    # 4. Parameter Impact Heatmap
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    # Parallel Units vs Pipeline Depth
    pivot_time = df.pivot_table(values='avg_time_s', 
                                 index='pipeline_depth', 
                                 columns='parallel_units', 
                                 aggfunc='mean')
    sns.heatmap(pivot_time*1e6, annot=True, fmt='.2f', cmap='YlOrRd_r', 
                ax=axes[0], cbar_kws={'label': 'Avg Time (μs)'})
    axes[0].set_title('Average Time vs PU/PD', fontweight='bold')
    axes[0].set_xlabel('Parallel Units')
    axes[0].set_ylabel('Pipeline Depth')
    
    # Energy heatmap
    pivot_energy = df.pivot_table(values='avg_energy_j', 
                                   index='pipeline_depth', 
                                   columns='parallel_units', 
                                   aggfunc='mean')
    sns.heatmap(pivot_energy*1e3, annot=True, fmt='.2f', cmap='YlGnBu_r', 
                ax=axes[1], cbar_kws={'label': 'Avg Energy (mJ)'})
    axes[1].set_title('Average Energy vs PU/PD', fontweight='bold')
    axes[1].set_xlabel('Parallel Units')
    axes[1].set_ylabel('Pipeline Depth')
    
    plt.tight_layout()
    plt.savefig(output_dir / 'parameter_impact_heatmap.png', dpi=300, bbox_inches='tight')
    print(f"  ✓ Saved: parameter_impact_heatmap.png")
    plt.close()
    
    # 5. Offload Strategy Comparison
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    strategy_stats = df.groupby('offload_strategy').agg({
        'avg_time_s': ['mean', 'std'],
        'avg_energy_j': ['mean', 'std']
    })
    
    strategies = strategy_stats.index
    time_means = strategy_stats['avg_time_s']['mean'].values * 1e6
    time_stds = strategy_stats['avg_time_s']['std'].values * 1e6
    energy_means = strategy_stats['avg_energy_j']['mean'].values * 1e3
    energy_stds = strategy_stats['avg_energy_j']['std'].values * 1e3
    
    x = np.arange(len(strategies))
    
    axes[0].bar(x, time_means, yerr=time_stds, capsize=5, 
                color='steelblue', edgecolor='black', alpha=0.7)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(strategies, rotation=45, ha='right')
    axes[0].set_ylabel('Average Time (μs)', fontsize=11)
    axes[0].set_title('Time by Offload Strategy', fontweight='bold')
    axes[0].grid(True, alpha=0.3, axis='y')
    
    axes[1].bar(x, energy_means, yerr=energy_stds, capsize=5, 
                color='seagreen', edgecolor='black', alpha=0.7)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(strategies, rotation=45, ha='right')
    axes[1].set_ylabel('Average Energy (mJ)', fontsize=11)
    axes[1].set_title('Energy by Offload Strategy', fontweight='bold')
    axes[1].grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_dir / 'offload_strategy_comparison.png', dpi=300, bbox_inches='tight')
    print(f"  ✓ Saved: offload_strategy_comparison.png")
    plt.close()
    
    # 6. Resource Utilization
    fig, ax = plt.subplots(figsize=(10, 6))
    scatter = ax.scatter(df['avg_dsp_utilization']*100, 
                        df['avg_bram_utilization']*100,
                        c=df['avg_time_s']*1e6, cmap='coolwarm_r', 
                        s=100, alpha=0.6, edgecolors='black')
    
    ax.set_xlabel('Average DSP Utilization (%)', fontsize=12)
    ax.set_ylabel('Average BRAM Utilization (%)', fontsize=12)
    ax.set_title('Resource Utilization vs Performance', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('Avg Time (μs)', fontsize=11)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'resource_utilization.png', dpi=300, bbox_inches='tight')
    print(f"  ✓ Saved: resource_utilization.png")
    plt.close()

def generate_report(df: pd.DataFrame, output_dir: Path):
    """Generate comprehensive analysis report."""
    report_path = output_dir / 'MULTI_WORKLOAD_ANALYSIS.md'
    
    best_idx = df['avg_time_s'].idxmin()
    best = df.loc[best_idx]
    
    most_robust_idx = df['cv_time'].idxmin()
    most_robust = df.loc[most_robust_idx]
    
    with open(report_path, 'w') as f:
        f.write("# Multi-Workload DSE Analysis Report\n\n")
        f.write("## Executive Summary\n\n")
        f.write(f"- **Total Trials**: {len(df)}\n")
        f.write(f"- **Workloads Tested**: 5 representative materials\n")
        f.write(f"- **Performance Range**: {df['avg_time_s'].max()/df['avg_time_s'].min():.2f}× speedup\n")
        f.write(f"- **Energy Range**: {df['avg_energy_j'].max()/df['avg_energy_j'].min():.2f}× variation\n\n")
        
        f.write("## Best Design (Average Performance)\n\n")
        f.write(f"**Trial {int(best['trial_index'])}**\n\n")
        f.write("### Performance Metrics\n")
        f.write(f"- Average Time: {best['avg_time_s']:.6e}s ({best['avg_time_s']*1e6:.2f}μs)\n")
        f.write(f"- Average Energy: {best['avg_energy_j']:.6f}J ({best['avg_energy_j']*1e3:.2f}mJ)\n")
        f.write(f"- Max Time: {best['max_time_s']:.6e}s ({best['max_time_s']*1e6:.2f}μs)\n")
        f.write(f"- Std Time: {best['std_time_s']:.6e}s\n")
        f.write(f"- CV (Time): {best['cv_time']:.3f}\n")
        f.write(f"- Worst-Case Penalty: {best['worst_case_penalty']:.2f}×\n\n")
        
        f.write("### Configuration\n")
        f.write(f"- Parallel Units: {int(best['parallel_units'])}\n")
        f.write(f"- Pipeline Depth: {int(best['pipeline_depth'])}\n")
        f.write(f"- Offload Strategy: `{best['offload_strategy']}`\n")
        f.write(f"- Dataflow Pattern: `{best['dataflow_pattern']}`\n")
        f.write(f"- Overlap Policy: `{best['overlap_policy']}`\n\n")
        
        f.write("### Resource Utilization\n")
        f.write(f"- Average DSP: {best['avg_dsp_utilization']:.2%}\n")
        f.write(f"- Average BRAM: {best['avg_bram_utilization']:.2%}\n\n")
        
        f.write("## Most Robust Design (Lowest Variability)\n\n")
        f.write(f"**Trial {int(most_robust['trial_index'])}**\n\n")
        f.write(f"- CV (Time): {most_robust['cv_time']:.3f}\n")
        f.write(f"- Worst-Case Penalty: {most_robust['worst_case_penalty']:.2f}×\n")
        f.write(f"- Average Time: {most_robust['avg_time_s']*1e6:.2f}μs\n")
        f.write(f"- Configuration: PU={int(most_robust['parallel_units'])}, "
                f"PD={int(most_robust['pipeline_depth'])}, "
                f"{most_robust['offload_strategy']}\n\n")
        
        f.write("## Top 5 Designs\n\n")
        f.write("| Rank | Trial | Avg Time (μs) | Avg Energy (mJ) | CV | WCP | PU | PD | Strategy |\n")
        f.write("|------|-------|---------------|-----------------|----|----|----|----|----------|\n")
        
        top5 = df.nsmallest(5, 'avg_time_s')
        for i, (idx, row) in enumerate(top5.iterrows(), 1):
            f.write(f"| {i} | {int(row['trial_index'])} | "
                   f"{row['avg_time_s']*1e6:.2f} | "
                   f"{row['avg_energy_j']*1e3:.2f} | "
                   f"{row['cv_time']:.3f} | "
                   f"{row['worst_case_penalty']:.2f}× | "
                   f"{int(row['parallel_units'])} | "
                   f"{int(row['pipeline_depth'])} | "
                   f"{row['offload_strategy']} |\n")
        
        f.write("\n## Key Findings\n\n")
        f.write("### Parameter Impact\n\n")
        
        # Parallel units impact
        pu_impact = df.groupby('parallel_units')['avg_time_s'].mean()
        f.write(f"1. **Parallel Units**: Strong impact on performance\n")
        for pu, time in pu_impact.items():
            f.write(f"   - PU={int(pu)}: {time*1e6:.2f}μs average\n")
        f.write(f"   - Best: PU={int(pu_impact.idxmin())} ({pu_impact.min()*1e6:.2f}μs)\n\n")
        
        # Pipeline depth impact
        pd_impact = df.groupby('pipeline_depth')['avg_time_s'].mean()
        f.write(f"2. **Pipeline Depth**: Moderate impact\n")
        for pd, time in pd_impact.items():
            f.write(f"   - PD={int(pd)}: {time*1e6:.2f}μs average\n")
        f.write(f"   - Best: PD={int(pd_impact.idxmin())} ({pd_impact.min()*1e6:.2f}μs)\n\n")
        
        # Offload strategy impact
        strategy_impact = df.groupby('offload_strategy')['avg_time_s'].mean().sort_values()
        f.write(f"3. **Offload Strategy**: Significant impact\n")
        for strategy, time in strategy_impact.items():
            f.write(f"   - `{strategy}`: {time*1e6:.2f}μs average\n")
        f.write(f"   - Best: `{strategy_impact.idxmin()}` ({strategy_impact.min()*1e6:.2f}μs)\n\n")
        
        f.write("### Robustness Analysis\n\n")
        f.write(f"- Mean CV (Time): {df['cv_time'].mean():.3f}\n")
        f.write(f"- Mean Worst-Case Penalty: {df['worst_case_penalty'].mean():.2f}×\n")
        f.write(f"- Most Robust Design: Trial {int(most_robust['trial_index'])} "
                f"(CV={most_robust['cv_time']:.3f})\n\n")
        
        f.write("## Design Recommendations\n\n")
        f.write("### For Average-Case Performance\n")
        f.write(f"- Use Trial {int(best['trial_index'])} configuration\n")
        f.write(f"- Expected performance: {best['avg_time_s']*1e6:.2f}μs average\n")
        f.write(f"- Variability: ±{best['cv_time']*100:.1f}%\n\n")
        
        f.write("### For Worst-Case Performance\n")
        worst_case_best = df.nsmallest(1, 'max_time_s').iloc[0]
        f.write(f"- Use Trial {int(worst_case_best['trial_index'])} configuration\n")
        f.write(f"- Worst-case time: {worst_case_best['max_time_s']*1e6:.2f}μs\n\n")
        
        f.write("### For Robustness\n")
        f.write(f"- Use Trial {int(most_robust['trial_index'])} configuration\n")
        f.write(f"- Lowest variability: CV={most_robust['cv_time']:.3f}\n")
        f.write(f"- Predictable performance across workloads\n\n")
        
        f.write("## Visualizations\n\n")
        f.write("See the following generated plots:\n\n")
        f.write("1. `pareto_frontier_multi_workload.png` - Time vs Energy tradeoff\n")
        f.write("2. `robustness_analysis.png` - Performance vs Variability\n")
        f.write("3. `worst_case_penalty_dist.png` - Distribution of worst-case penalties\n")
        f.write("4. `parameter_impact_heatmap.png` - PU/PD impact on time and energy\n")
        f.write("5. `offload_strategy_comparison.png` - Strategy comparison\n")
        f.write("6. `resource_utilization.png` - DSP/BRAM usage vs performance\n\n")
    
    print(f"\n  ✓ Saved: MULTI_WORKLOAD_ANALYSIS.md")

def main():
    # Setup paths
    project_root = Path(__file__).parent.parent.parent
    results_dir = project_root / 'results' / 'multi_workload'
    output_dir = project_root / 'results' / 'multi_workload' / 'analysis'
    
    print("\n" + "="*80)
    print("🚀 Multi-Workload DSE Analysis")
    print("="*80)
    
    # Load results
    print("\n📂 Loading results...")
    df = load_results(results_dir)
    print(f"  ✓ Loaded {len(df)} trials")
    
    # Analyze robustness
    df = analyze_workload_robustness(df)
    
    # Analyze parameter impact
    analyze_parameter_impact(df)
    
    # Create visualizations
    create_visualizations(df, output_dir)
    
    # Generate report
    print("\n📝 Generating report...")
    generate_report(df, output_dir)
    
    print("\n" + "="*80)
    print("✅ Analysis Complete!")
    print("="*80)
    print(f"\nResults saved to: {output_dir}")
    print("\nNext steps:")
    print("  1. Review MULTI_WORKLOAD_ANALYSIS.md")
    print("  2. Examine generated visualizations")
    print("  3. Select top designs for SystemC validation")

if __name__ == '__main__':
    main()
