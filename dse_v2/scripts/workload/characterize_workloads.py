#!/usr/bin/env python3
"""
Workload Characterization Script

Analyzes QE workload characteristics to understand computational patterns
and guide multi-workload DSE.

Features computed:
- Compute intensity (FLOPs/byte)
- Memory pressure (data size / cache size)
- FFT pressure (FFT grid size)
- Projector density (nkb/npw ratio)
- Band count scaling (m)
- Solver complexity (generalized vs standard)
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List
import matplotlib.pyplot as plt
import seaborn as sns


class WorkloadCharacterizer:
    """Characterize QE workloads for DSE"""
    
    def __init__(self, workload_matrix_path: Path):
        with open(workload_matrix_path, 'r') as f:
            self.workload_data = json.load(f)
        
        # FPGA cache sizes (typical Xilinx Ultrascale+)
        self.l1_cache_kb = 32
        self.l2_cache_kb = 256
        
    def compute_features(self, workload: Dict) -> Dict:
        """Compute all features for a workload"""
        
        # Extract dimensions
        npw = workload['expected_dimensions']['npw']
        nkb = workload['expected_dimensions']['nkb']
        nbnd = workload['expected_dimensions']['nbnd']
        
        # 1. Compute Intensity (FLOPs/byte)
        # h_psi: FFT(npw) + GEMM(npw, nkb, nbnd)
        fft_flops = 5 * npw * np.log2(npw)  # Complex FFT
        gemm_flops = 2 * npw * nkb * nbnd   # Complex GEMM
        total_flops = fft_flops + gemm_flops
        
        # Data movement: psi(npw, nbnd) + beta(nkb, nbnd)
        psi_bytes = npw * nbnd * 16  # Complex double
        beta_bytes = nkb * nbnd * 16
        total_bytes = psi_bytes + beta_bytes
        
        compute_intensity = total_flops / total_bytes if total_bytes > 0 else 0
        
        # 2. Memory Pressure (data size / cache size)
        working_set_kb = (psi_bytes + beta_bytes) / 1024
        l1_pressure = working_set_kb / self.l1_cache_kb
        l2_pressure = working_set_kb / self.l2_cache_kb
        
        # 3. FFT Pressure (FFT size relative to typical)
        fft_pressure = npw / 4096  # Normalized to 4K FFT
        
        # 4. Projector Density (nkb/npw ratio)
        projector_density = nkb / npw if npw > 0 else 0
        
        # 5. Band Count Scaling
        band_scaling = nbnd / 16  # Normalized to 16 bands
        
        # 6. Problem Size Category
        problem_size = npw * nbnd
        if problem_size < 50000:
            size_category = "small"
        elif problem_size < 150000:
            size_category = "medium"
        else:
            size_category = "large"
        
        # 7. Solver Complexity (from pseudopotential type)
        pp_type = workload['dft_params']['pseudopotential']
        if pp_type == 'PAW':
            solver_complexity = 1.5  # More complex
        elif pp_type == 'USPP':
            solver_complexity = 1.0  # Standard
        else:
            solver_complexity = 0.8  # Simpler
        
        # 8. Arithmetic Intensity Classification
        if compute_intensity < 1.0:
            intensity_class = "memory_bound"
        elif compute_intensity < 5.0:
            intensity_class = "balanced"
        else:
            intensity_class = "compute_bound"
        
        return {
            'workload_id': workload['id'],
            'category': workload['category'],
            'material': workload['material'],
            'npw': npw,
            'nkb': nkb,
            'nbnd': nbnd,
            'compute_intensity': compute_intensity,
            'l1_pressure': l1_pressure,
            'l2_pressure': l2_pressure,
            'fft_pressure': fft_pressure,
            'projector_density': projector_density,
            'band_scaling': band_scaling,
            'problem_size': problem_size,
            'size_category': size_category,
            'solver_complexity': solver_complexity,
            'intensity_class': intensity_class,
            'working_set_kb': working_set_kb,
            'total_flops': total_flops,
            'total_bytes': total_bytes,
        }
    
    def characterize_all(self) -> pd.DataFrame:
        """Characterize all workloads"""
        features_list = []
        
        for workload in self.workload_data['workloads']:
            features = self.compute_features(workload)
            features_list.append(features)
        
        return pd.DataFrame(features_list)
    
    def select_representative_workloads(self, df: pd.DataFrame, n: int = 5) -> List[str]:
        """Select n representative workloads for DSE"""
        
        # Strategy: Maximize diversity in feature space
        # Use k-means clustering on normalized features
        from sklearn.preprocessing import StandardScaler
        from sklearn.cluster import KMeans
        
        # Select features for clustering
        feature_cols = [
            'compute_intensity', 'l1_pressure', 'fft_pressure',
            'projector_density', 'band_scaling', 'problem_size'
        ]
        
        X = df[feature_cols].values
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # Cluster into n groups
        kmeans = KMeans(n_clusters=n, random_state=42)
        df['cluster'] = kmeans.fit_predict(X_scaled)
        
        # Select one workload from each cluster (closest to centroid)
        selected = []
        for i in range(n):
            cluster_df = df[df['cluster'] == i]
            cluster_center = kmeans.cluster_centers_[i]
            
            # Find closest point to centroid
            distances = np.linalg.norm(
                X_scaled[cluster_df.index] - cluster_center, axis=1
            )
            closest_idx = cluster_df.index[np.argmin(distances)]
            selected.append(df.loc[closest_idx, 'workload_id'])
        
        return selected
    
    def visualize_features(self, df: pd.DataFrame, output_dir: Path):
        """Generate visualization plots"""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Feature distribution
        fig, axes = plt.subplots(2, 3, figsize=(15, 10))
        
        features = [
            ('compute_intensity', 'Compute Intensity (FLOPs/byte)'),
            ('l2_pressure', 'L2 Cache Pressure'),
            ('fft_pressure', 'FFT Pressure (normalized)'),
            ('projector_density', 'Projector Density (nkb/npw)'),
            ('band_scaling', 'Band Scaling (normalized)'),
            ('problem_size', 'Problem Size (npw × nbnd)')
        ]
        
        for ax, (feature, title) in zip(axes.flat, features):
            df.boxplot(column=feature, by='category', ax=ax)
            ax.set_title(title)
            ax.set_xlabel('Category')
            plt.sca(ax)
            plt.xticks(rotation=45, ha='right')
        
        plt.tight_layout()
        plt.savefig(output_dir / 'feature_distribution.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        # 2. Compute intensity vs memory pressure
        plt.figure(figsize=(10, 6))
        for category in df['category'].unique():
            cat_df = df[df['category'] == category]
            plt.scatter(cat_df['compute_intensity'], cat_df['l2_pressure'],
                       label=category, s=100, alpha=0.7)
        
        plt.xlabel('Compute Intensity (FLOPs/byte)', fontsize=12)
        plt.ylabel('L2 Cache Pressure', fontsize=12)
        plt.title('Workload Characterization: Compute vs Memory', fontsize=14, fontweight='bold')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(output_dir / 'compute_vs_memory.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        # 3. Problem size vs complexity
        plt.figure(figsize=(10, 6))
        scatter = plt.scatter(df['problem_size'], df['solver_complexity'],
                            c=df['compute_intensity'], s=200, alpha=0.7,
                            cmap='viridis', edgecolors='black')
        
        for idx, row in df.iterrows():
            plt.annotate(row['workload_id'], 
                        (row['problem_size'], row['solver_complexity']),
                        fontsize=8, ha='center')
        
        plt.xlabel('Problem Size (npw × nbnd)', fontsize=12)
        plt.ylabel('Solver Complexity', fontsize=12)
        plt.title('Workload Complexity Landscape', fontsize=14, fontweight='bold')
        plt.colorbar(scatter, label='Compute Intensity')
        plt.grid(True, alpha=0.3)
        plt.savefig(output_dir / 'complexity_landscape.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        # 4. Feature correlation heatmap
        feature_cols = [
            'compute_intensity', 'l2_pressure', 'fft_pressure',
            'projector_density', 'band_scaling', 'solver_complexity'
        ]
        
        plt.figure(figsize=(10, 8))
        corr = df[feature_cols].corr()
        sns.heatmap(corr, annot=True, fmt='.2f', cmap='coolwarm',
                   center=0, square=True, linewidths=1)
        plt.title('Workload Feature Correlation', fontsize=14, fontweight='bold')
        plt.tight_layout()
        plt.savefig(output_dir / 'feature_correlation.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✅ Saved visualizations to {output_dir}/")


def main():
    # Paths
    workload_matrix_path = Path('workloads/definitions/workload_matrix_v2.json')
    output_dir = Path('workloads/analysis')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("📊 Workload Characterization")
    print("=" * 60)
    
    # Initialize characterizer
    characterizer = WorkloadCharacterizer(workload_matrix_path)
    
    # Characterize all workloads
    print("\n1. Computing features for all workloads...")
    df = characterizer.characterize_all()
    
    # Save features
    output_csv = output_dir / 'workload_features_v2.csv'
    df.to_csv(output_csv, index=False)
    print(f"✅ Saved features to {output_csv}")
    
    # Print summary
    print("\n2. Workload Summary:")
    print(f"   Total workloads: {len(df)}")
    print(f"   Categories: {df['category'].nunique()}")
    print(f"   Size categories: {df['size_category'].value_counts().to_dict()}")
    print(f"   Intensity classes: {df['intensity_class'].value_counts().to_dict()}")
    
    # Print feature statistics
    print("\n3. Feature Statistics:")
    print(df[['compute_intensity', 'l2_pressure', 'fft_pressure', 
              'projector_density', 'band_scaling']].describe())
    
    # Select representative workloads
    print("\n4. Selecting 5 representative workloads...")
    selected = characterizer.select_representative_workloads(df, n=5)
    print("   Selected workloads:")
    for i, wid in enumerate(selected, 1):
        row = df[df['workload_id'] == wid].iloc[0]
        print(f"   {i}. {wid:25s} - {row['category']:15s} - {row['intensity_class']:15s} - Size: {row['size_category']}")
    
    # Save selected workloads
    selected_df = df[df['workload_id'].isin(selected)]
    selected_csv = output_dir / 'selected_workloads_v2.csv'
    selected_df.to_csv(selected_csv, index=False)
    print(f"✅ Saved selected workloads to {selected_csv}")
    
    # Generate visualizations
    print("\n5. Generating visualizations...")
    viz_dir = output_dir / 'visualizations'
    characterizer.visualize_features(df, viz_dir)
    
    print("\n" + "=" * 60)
    print("✅ Workload characterization complete!")
    print(f"\nOutputs:")
    print(f"  - Features: {output_csv}")
    print(f"  - Selected: {selected_csv}")
    print(f"  - Plots: {viz_dir}/")


if __name__ == '__main__':
    main()
