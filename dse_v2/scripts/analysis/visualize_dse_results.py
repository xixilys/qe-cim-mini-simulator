#!/usr/bin/env python3

import pandas as pd
import numpy as np
import ast
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

def load_and_parse_trials(csv_path):
    df = pd.read_csv(csv_path)
    
    params_list = []
    for idx, row in df.iterrows():
        params = ast.literal_eval(row['parameters'])
        result = ast.literal_eval(row['result'])
        
        flat_row = {**params}
        flat_row['time_s'] = result['time_s']
        flat_row['energy_j'] = result['energy_j']
        flat_row['dsp_utilization'] = result['area']['dsp_utilization']
        flat_row['bram_utilization'] = result['area']['bram_utilization']
        flat_row['dsp_count'] = result['area']['dsp_count']
        flat_row['bram_kb'] = result['area']['bram_kb']
        flat_row['lut_count'] = result['area']['lut_count']
        flat_row['trial_id'] = idx
        
        params_list.append(flat_row)
    
    return pd.DataFrame(params_list)

def plot_pareto_frontier(df, output_dir):
    plt.figure(figsize=(10, 6))
    
    plt.scatter(df['time_s']*1e6, df['energy_j']*1e3, 
                c=df['parallel_units'], cmap='viridis', 
                s=100, alpha=0.6, edgecolors='black')
    
    min_time_idx = df['time_s'].idxmin()
    plt.scatter(df.loc[min_time_idx, 'time_s']*1e6, 
                df.loc[min_time_idx, 'energy_j']*1e3,
                c='red', s=300, marker='*', 
                edgecolors='black', linewidths=2,
                label='Optimal Design', zorder=10)
    
    plt.xlabel('Time (μs)', fontsize=12)
    plt.ylabel('Energy (mJ)', fontsize=12)
    plt.title('DSE Results: Time vs Energy Trade-off', fontsize=14, fontweight='bold')
    plt.colorbar(label='Parallel Units')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    output_path = output_dir / 'pareto_frontier.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_path}")
    plt.close()

def plot_convergence(df, output_dir):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    cummin_time = df['time_s'].cummin()
    cummin_energy = df['energy_j'].cummin()
    
    ax1.plot(df['trial_id'], df['time_s']*1e6, 'o-', alpha=0.5, label='Trial Time')
    ax1.plot(df['trial_id'], cummin_time*1e6, 'r-', linewidth=2, label='Best So Far')
    ax1.set_xlabel('Trial Number', fontsize=11)
    ax1.set_ylabel('Time (μs)', fontsize=11)
    ax1.set_title('Convergence: Time Optimization', fontsize=12, fontweight='bold')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    ax2.plot(df['trial_id'], df['energy_j']*1e3, 'o-', alpha=0.5, label='Trial Energy')
    ax2.plot(df['trial_id'], cummin_energy*1e3, 'r-', linewidth=2, label='Best So Far')
    ax2.set_xlabel('Trial Number', fontsize=11)
    ax2.set_ylabel('Energy (mJ)', fontsize=11)
    ax2.set_title('Convergence: Energy Optimization', fontsize=12, fontweight='bold')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    output_path = output_dir / 'convergence.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_path}")
    plt.close()

def plot_parameter_impact(df, output_dir):
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    params = ['parallel_units', 'pipeline_depth', 'offload_strategy', 'dataflow_pattern']
    titles = ['Parallel Units', 'Pipeline Depth', 'Offload Strategy', 'Dataflow Pattern']
    
    for ax, param, title in zip(axes.flat, params, titles):
        grouped = df.groupby(param)['time_s'].agg(['mean', 'min', 'max'])
        grouped = grouped.sort_values('mean')
        
        x = range(len(grouped))
        ax.bar(x, grouped['mean']*1e6, alpha=0.7, label='Mean')
        ax.errorbar(x, grouped['mean']*1e6, 
                    yerr=[(grouped['mean']-grouped['min'])*1e6, 
                          (grouped['max']-grouped['mean'])*1e6],
                    fmt='none', ecolor='black', capsize=5)
        
        ax.set_xticks(x)
        ax.set_xticklabels(grouped.index, rotation=45, ha='right')
        ax.set_ylabel('Time (μs)', fontsize=10)
        ax.set_title(f'{title} Impact on Performance', fontsize=11, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    output_path = output_dir / 'parameter_impact.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_path}")
    plt.close()

def plot_correlation_heatmap(df, output_dir):
    numeric_cols = ['time_s', 'energy_j', 'parallel_units', 'pipeline_depth', 
                    'dsp_utilization', 'bram_utilization', 'intermediate_buffer_kb',
                    'tile_npw', 'tile_nkb', 'tile_m', 'dma_channels', 'pcie_gen']
    
    corr_matrix = df[numeric_cols].corr()
    
    plt.figure(figsize=(12, 10))
    sns.heatmap(corr_matrix, annot=True, fmt='.2f', cmap='coolwarm', 
                center=0, square=True, linewidths=1,
                cbar_kws={'label': 'Correlation Coefficient'})
    plt.title('Parameter Correlation Matrix', fontsize=14, fontweight='bold', pad=20)
    plt.tight_layout()
    
    output_path = output_dir / 'correlation_heatmap.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_path}")
    plt.close()

def plot_resource_utilization(df, output_dir):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    scatter1 = ax1.scatter(df['dsp_utilization']*100, df['time_s']*1e6,
                          c=df['parallel_units'], cmap='viridis',
                          s=100, alpha=0.6, edgecolors='black')
    ax1.set_xlabel('DSP Utilization (%)', fontsize=11)
    ax1.set_ylabel('Time (μs)', fontsize=11)
    ax1.set_title('DSP Utilization vs Performance', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    plt.colorbar(scatter1, ax=ax1, label='Parallel Units')
    
    scatter2 = ax2.scatter(df['bram_utilization']*100, df['time_s']*1e6,
                          c=df['pipeline_depth'], cmap='plasma',
                          s=100, alpha=0.6, edgecolors='black')
    ax2.set_xlabel('BRAM Utilization (%)', fontsize=11)
    ax2.set_ylabel('Time (μs)', fontsize=11)
    ax2.set_title('BRAM Utilization vs Performance', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    plt.colorbar(scatter2, ax=ax2, label='Pipeline Depth')
    
    plt.tight_layout()
    output_path = output_dir / 'resource_utilization.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_path}")
    plt.close()

def plot_design_space_coverage(df, output_dir):
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    
    categorical_params = [
        ('parallel_units', 'Parallel Units'),
        ('pipeline_depth', 'Pipeline Depth'),
        ('offload_strategy', 'Offload Strategy'),
        ('dataflow_pattern', 'Dataflow Pattern'),
        ('h_psi_impl', 'H_psi Implementation'),
        ('gemm_impl', 'GEMM Implementation')
    ]
    
    for ax, (param, title) in zip(axes.flat, categorical_params):
        counts = df[param].value_counts()
        ax.bar(range(len(counts)), counts.values, alpha=0.7)
        ax.set_xticks(range(len(counts)))
        ax.set_xticklabels(counts.index, rotation=45, ha='right', fontsize=9)
        ax.set_ylabel('Trial Count', fontsize=10)
        ax.set_title(f'{title} Sampling', fontsize=11, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    output_path = output_dir / 'design_space_coverage.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_path}")
    plt.close()

def main():
    trials_path = Path('results/pareto/all_trials_v2.csv')
    output_dir = Path('results/visualizations')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("📊 Loading and parsing trial data...")
    df = load_and_parse_trials(trials_path)
    print(f"✅ Loaded {len(df)} trials")
    
    print("\n🎨 Generating visualizations...")
    plot_pareto_frontier(df, output_dir)
    plot_convergence(df, output_dir)
    plot_parameter_impact(df, output_dir)
    plot_correlation_heatmap(df, output_dir)
    plot_resource_utilization(df, output_dir)
    plot_design_space_coverage(df, output_dir)
    
    print(f"\n✅ All visualizations saved to {output_dir}/")
    print("\nGenerated plots:")
    print("  1. pareto_frontier.png - Time vs Energy scatter plot")
    print("  2. convergence.png - Optimization convergence over trials")
    print("  3. parameter_impact.png - Impact of key parameters on performance")
    print("  4. correlation_heatmap.png - Parameter correlation matrix")
    print("  5. resource_utilization.png - DSP/BRAM utilization vs performance")
    print("  6. design_space_coverage.png - Sampling distribution across parameters")

if __name__ == '__main__':
    main()
