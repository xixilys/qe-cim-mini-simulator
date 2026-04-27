#!/usr/bin/env python3

import json
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple
import torch
from ax.service.ax_client import AxClient
from ax.service.utils.instantiation import ObjectiveProperties

sys.path.append(str(Path(__file__).resolve().parents[2]))
from models.fast.performance_model import FastPerformanceModel
from scripts.dse.run_bayesian_dse import BayesianDSE


class MultiWorkloadDSE:
    
    def __init__(self, workloads: List[Dict], design_space_path: Path, fpga_specs: Dict):
        self.workloads = workloads
        self.design_space_path = design_space_path
        self.fpga_specs = fpga_specs
        self.fast_model = FastPerformanceModel(fpga_specs)
        
        with open(design_space_path) as f:
            self.design_space = json.load(f)
        
        self.ax_client = AxClient()
        self._setup_search_space()
        self.evaluation_history = []
    
    def _setup_search_space(self):
        parameters = []
        
        for param_name, values in self.design_space['categorical_params'].items():
            parameters.append({
                "name": param_name,
                "type": "choice",
                "values": values,
            })
        
        for param_name, config in self.design_space['integer_params'].items():
            if 'values' in config:
                parameters.append({
                    "name": param_name,
                    "type": "choice",
                    "values": config['values'],
                })
            else:
                parameters.append({
                    "name": param_name,
                    "type": "range",
                    "bounds": [config['min'], config['max']],
                    "value_type": "int",
                })
        
        self.ax_client.create_experiment(
            name="multi_workload_dse",
            parameters=parameters,
            objectives={
                "avg_time_s": ObjectiveProperties(minimize=True),
                "avg_energy_j": ObjectiveProperties(minimize=True),
            },
        )
    
    def evaluate_design(self, design_point: Dict) -> Dict:
        results = []
        
        for workload in self.workloads:
            result = self.fast_model.evaluate_design_point(design_point, workload)
            results.append(result)
        
        avg_time = np.mean([r['time_s'] for r in results])
        avg_energy = np.mean([r['energy_j'] for r in results])
        max_time = np.max([r['time_s'] for r in results])
        max_energy = np.max([r['energy_j'] for r in results])
        min_time = np.min([r['time_s'] for r in results])
        min_energy = np.min([r['energy_j'] for r in results])
        
        std_time = np.std([r['time_s'] for r in results])
        std_energy = np.std([r['energy_j'] for r in results])
        
        avg_dsp = np.mean([r['area']['dsp_utilization'] for r in results])
        avg_bram = np.mean([r['area']['bram_utilization'] for r in results])
        
        return {
            'avg_time_s': avg_time,
            'avg_energy_j': avg_energy,
            'max_time_s': max_time,
            'max_energy_j': max_energy,
            'min_time_s': min_time,
            'min_energy_j': min_energy,
            'std_time_s': std_time,
            'std_energy_j': std_energy,
            'avg_dsp_utilization': avg_dsp,
            'avg_bram_utilization': avg_bram,
            'per_workload_results': results,
        }
    
    def run_optimization(self, n_iterations: int = 50, strategy: str = 'average'):
        print(f"🚀 Starting Multi-Workload Bayesian Optimization")
        print(f"📊 Workloads: {len(self.workloads)}")
        print(f"🎯 Strategy: {strategy}")
        print(f"🔄 Iterations: {n_iterations}")
        print()
        
        for i in range(n_iterations):
            parameters, trial_index = self.ax_client.get_next_trial()
            
            results = self.evaluate_design(parameters)
            
            self.ax_client.complete_trial(
                trial_index=trial_index,
                raw_data={
                    'avg_time_s': (results['avg_time_s'], 0.0),
                    'avg_energy_j': (results['avg_energy_j'], 0.0),
                }
            )
            
            trial_data = {
                'trial_index': trial_index,
                'parameters': parameters,
                'results': results,
            }
            self.evaluation_history.append(trial_data)
            
            if (i + 1) % 10 == 0:
                print(f"Iteration {i+1}/{n_iterations} - Best avg time: {min([h['results']['avg_time_s'] for h in self.evaluation_history]):.6e}s")
        
        print(f"\n✅ Optimization complete!")
        return self.get_results()
    
    def get_results(self) -> pd.DataFrame:
        results_list = []
        
        for trial in self.evaluation_history:
            row = trial['parameters'].copy()
            row.update({
                'trial_index': trial['trial_index'],
                'avg_time_s': trial['results']['avg_time_s'],
                'avg_energy_j': trial['results']['avg_energy_j'],
                'max_time_s': trial['results']['max_time_s'],
                'max_energy_j': trial['results']['max_energy_j'],
                'std_time_s': trial['results']['std_time_s'],
                'std_energy_j': trial['results']['std_energy_j'],
                'avg_dsp_utilization': trial['results']['avg_dsp_utilization'],
                'avg_bram_utilization': trial['results']['avg_bram_utilization'],
            })
            results_list.append(row)
        
        return pd.DataFrame(results_list)
    
    def save_results(self, df_results: pd.DataFrame, output_path: Path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df_results.to_csv(output_path, index=False)
        print(f"\n✅ Results saved to {output_path}")
        print(f"📊 Total trials: {len(df_results)}")
        
        best_idx = df_results['avg_time_s'].idxmin()
        best_design = df_results.loc[best_idx]
        print(f"\n🏆 Best Design (Average Performance):")
        print(f"   Avg Time: {best_design['avg_time_s']:.6e}s")
        print(f"   Avg Energy: {best_design['avg_energy_j']:.6f}J")
        print(f"   Std Time: {best_design['std_time_s']:.6e}s")
        print(f"   Parallel Units: {best_design['parallel_units']}")
        print(f"   Pipeline Depth: {best_design['pipeline_depth']}")
        print(f"   Offload Strategy: {best_design['offload_strategy']}")


def main():
    fpga_specs = {
        'peak_gflops': 1300,
        'memory_bw_gbs': 77,
        'pcie_bw_gbs': 16,
        'bram_kb': 34000,
        'dsp_count': 12288,
    }
    
    design_space_path = Path('design_space/definitions/host_fpga_design_space_v2.json')
    selected_workloads_path = Path('workloads/analysis/selected_workloads_v2.csv')
    
    if not selected_workloads_path.exists():
        print(f"❌ Selected workloads not found: {selected_workloads_path}")
        print("Run: python3 scripts/workload/characterize_workloads.py")
        return
    
    df_workloads = pd.read_csv(selected_workloads_path)
    
    workloads = []
    for idx, row in df_workloads.iterrows():
        workloads.append({
            'id': row['workload_id'],
            'npw': int(row['npw']),
            'nkb': int(row['nkb']),
            'm': int(row['nbnd']),
        })
    
    print(f"📊 Multi-Workload DSE Configuration")
    print(f"=" * 60)
    print(f"Workloads ({len(workloads)}):")
    for i, w in enumerate(workloads, 1):
        print(f"  {i}. {w['id']:25s} - npw={w['npw']:5d}, nkb={w['nkb']:3d}, m={w['m']:2d}")
    print()
    
    dse = MultiWorkloadDSE(workloads, design_space_path, fpga_specs)
    
    results = dse.run_optimization(n_iterations=50, strategy='average')
    
    output_path = Path('results/multi_workload/average_performance_v2.csv')
    dse.save_results(results, output_path)


if __name__ == '__main__':
    main()
